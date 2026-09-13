"""Servicio HTTP de Sinnema (FastAPI): la API y la web de usuario final.

Expone el caso de uso existente como producto distribuible:

- ``POST /api/series``               crea un job de generación y lo encola,
- ``GET  /api/jobs/{id}``            consulta el estado y el entregable,
- ``GET  /api/jobs/{id}/events``     progreso en vivo (Server-Sent Events),
- ``GET  /api/jobs/{id}/viewer``     visor HTML del entregable,
- ``GET  /api/projects``             los shows disponibles,
- ``POST/PUT/DELETE /api/projects``  gestión de proyectos vía archivos TOML,
- ``GET  /api/projects/{id}/prompts`` vista previa de prompts compuestos,
- ``GET  /api/projects/{id}/flujo-efectivo`` fases resueltas + hito + Mermaid,
- ``GET/DELETE /api/projects/{id}/lore`` memoria de continuidad,
- ``GET/POST /api/projects/{id}/anclas``           biblioteca de recursos ancla,
- ``GET/PUT/DELETE /api/projects/{id}/anclas/{a}`` detalle / editar / retirar,
- ``POST /api/projects/{id}/anclas/{a}/imagenes``  upload a la batería,
- ``GET  /api/projects/{id}/anclas/{a}/imagenes/{f}`` serving de la batería,
- ``POST /api/projects/{id}/anclas/{a}/lock``      lock con batería mínima,
- ``GET  /api/meta/roles``           catálogo de agentes para el formulario,
- ``GET  /``                         la interfaz web (gestión + generación).

Los proyectos viven en archivos TOML (fuente de verdad): la API los lee y
escribe con escritura atómica; cada job carga el spec vigente al arrancar.

El aislamiento por usuario es básico (header ``X-Owner``): los listados se
filtran por propietario. Autenticación real, rate limiting y TLS quedan para
el reverse proxy / capa de despliegue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import uvicorn
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field, ValidationError

from sinnema.application.graph import build_pipeline_graph
from sinnema.application.ports import ROLE_PLANNER, ROLE_SCRIPTWRITER
from sinnema.application.projects import (
    CONTRATOS_VALIDOS,
    ROLES_ESENCIALES,
    TIPOS_CUSTOM,
    FlowSpec,
    ProjectSpec,
    resolver_flujo,
)
from sinnema.application.prompts import build_role_system_prompts
from sinnema.application.registry import (
    AGENT_REGISTRY,
    CATALOGO_ENTRADAS,
    definiciones_custom,
    definiciones_del_proyecto,
)
from sinnema.application.requests import MAX_CRITIQUE_ATTEMPTS_LIMIT
from sinnema.application.tools import TOOLS_INTEGRADAS
from sinnema.application.use_cases import limite_de_recursion
from sinnema.domain.constants import ALCANCES, SERIES_MAX_CHAPTERS
from sinnema.domain.models.anclas import (
    BATERIA_MINIMA,
    ESTADOS_DE_ANCLA,
    ROLES_POR_TIPO,
    TIPOS_DE_ANCLA,
    RecursoAncla,
    bateria_minima_cumplida,
)
from sinnema.infrastructure.api.viewer import render_deliverable_html
from sinnema.infrastructure.anclas import JsonAnchorStore
from sinnema.infrastructure.llm.providers import (
    DEFAULT_CUSTOM_ROLE_SPEC,
    DEFAULT_ROLE_SPECS,
    PROVEEDORES,
    default_role_spec,
    resolve_role_spec,
)
from sinnema.infrastructure.lore import JsonLoreStore
from sinnema.infrastructure.media import (
    PROVEEDORES_DE_IMAGEN,
    AlmacenMedia,
    construir_dependencias_de_media,
)
from sinnema.infrastructure.projects import (
    ProjectFileStore,
    packaged_projects_dir,
    resolve_writable_projects_dir,
)
from sinnema.infrastructure.projects.store import fingerprint_spec
from sinnema.infrastructure.runtime.jobs import (
    TERMINAL_STATUSES,
    Job,
    JobStatus,
    SqliteJobStore,
)
from sinnema.infrastructure.runtime.runner import SeriesWorker

logger = logging.getLogger("sinnema.api")

# UI 3D (spec-red-3d §8.4/§12.3): build de Vite en `web/dist`. El legacy de
# `static/` fue reemplazado (Fase 6d, con la lista de paridad completa);
# sin build JS se sirve una página indicando cómo construir la UI.
WEB_DIST_DIR = Path(__file__).resolve().parents[3] / "web" / "dist"

_SIN_BUILD = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Sinnema — UI 3D sin construir</title></head>
<body style="background:#0f1115;color:#e8eaf0;font:15px/1.6 system-ui;max-width:640px;margin:80px auto">
<h1>Sinnema</h1>
<p>La UI 3D del monitor de la red de agentes aún no está construida.
Generala con:</p>
<pre style="background:#171a21;padding:12px;border-radius:8px">cd web &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>Mientras tanto, la <a style="color:#7aa2ff" href="/docs">API</a> sigue
completa.</p></body></html>"""

#: Raíz de datos del servicio (jobs, checkpoints, auditoría, lore, salidas).
DEFAULT_DATA_DIR = Path(
    os.environ.get("SINNEMA_DATA_DIR", "datos-servidor")
)

# Biblioteca de anclas (spec-recursos-ancla §9.1/§14): formatos y límite de
# los uploads de batería. La extensión viene del upload pero solo se acepta
# la de esta lista blanca; el content-type de serving es fijo por extensión.
EXTENSIONES_DE_IMAGEN = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
TAMANO_MAXIMO_DE_IMAGEN = 10 * 1024 * 1024  # 10 MB


def _siguiente_archivo_de_rol(ancla: RecursoAncla, rol: str, extension: str) -> str:
    """Nombre ``<rol>_<n>.<ext>`` con el correlativo siguiente del rol: el
    servidor genera siempre el nombre del archivo, nunca el cliente."""
    prefijo, n = f"{rol}_", 0
    for imagen in ancla.bateria:
        nombre = imagen.archivo
        if nombre.startswith(prefijo) and nombre.endswith(extension):
            cuerpo = nombre[len(prefijo):-len(extension)]
            if cuerpo.isdigit():
                n = max(n, int(cuerpo))
    return f"{prefijo}{n + 1}{extension}"


class SeriesRequestBody(BaseModel):
    """Cuerpo de ``POST /api/series``."""

    project_id: str = Field(..., min_length=1)
    topic: Optional[str] = Field(None, description="Vacío = tema por defecto del proyecto.")
    num_chapters: int = Field(3, ge=1, le=SERIES_MAX_CHAPTERS)
    max_critique_attempts: Optional[int] = Field(
        None, ge=1, le=MAX_CRITIQUE_ATTEMPTS_LIMIT,
        description="Vacío = default del proyecto (sección [pipeline]) o 2.",
    )


class _GatewayNulo:
    """Gateway que nunca genera: compila el grafo solo para derivar su forma."""

    def generate(self, *_a, **_k):  # pragma: no cover
        raise RuntimeError("El diagrama del grafo no ejecuta el pipeline.")


# ---------------------------------------------------------------------------
# Red efectiva (spec-red-3d §5.1): nodos + aristas del grafo compilado
# ---------------------------------------------------------------------------

#: Nodos estructurales escritos a mano en ``graph.py`` (sin agente propio).
_CIERRE_DESCRIPCIONES = {
    "commit_episode": (
        "Consolida el episodio aprobado, actualiza el lore y avanza el índice "
        "de capítulo."
    ),
    "fail_chapter": (
        "Descarta el capítulo y registra el fallo tras agotar los reintentos "
        "de QA."
    ),
    "consolidar_plan": (
        "Consolida el outline de la serie (hasta = plan): corrida sin episodios."
    ),
}


def _fases_del_flujo(proyecto: ProjectSpec, flujo: FlowSpec) -> Dict[str, str]:
    """Columna del layout (§9.1) por nodo, derivada del flujo efectivo."""
    definiciones = definiciones_del_proyecto(proyecto)
    fases = {"plan_series": "serie"}
    for rol in flujo.contexto:
        fases[definiciones[rol].nodo] = "contexto"
    fases[definiciones[ROLE_SCRIPTWRITER].nodo] = "escritura"
    for rol in flujo.transformaciones:
        fases[definiciones[rol].nodo] = "transformacion"
    if flujo.revisor is not None:
        fases[definiciones[flujo.revisor].nodo] = "compuerta"
    for rol in flujo.enriquecimiento:
        fases[definiciones[rol].nodo] = "enriquecimiento"
    fases.update({nodo: "cierre" for nodo in _CIERRE_DESCRIPCIONES})
    return fases


def _llm_resuelto(proyecto: ProjectSpec, rol: str) -> Dict[str, Any]:
    """LLMConfig del rol (§4): proyecto > entorno > default, con ``tools``.

    ``top_p``/``max_tokens`` ausentes no viajan en el dict (default del
    proveedor), espejo exacto de lo que ``build_provider_model`` recibirá.
    """
    config = proyecto.config_de_agente(rol)
    spec = resolve_role_spec(default_role_spec(rol), config)
    llm: Dict[str, Any] = {
        "proveedor": spec.provider,
        "modelo": spec.model,
        "temperatura": spec.temperature,
        "tools": list(config.tools),
    }
    if spec.top_p is not None:
        llm["top_p"] = spec.top_p
    if spec.max_tokens is not None:
        llm["max_tokens"] = spec.max_tokens
    return llm


def _red_efectiva(proyecto: ProjectSpec) -> Dict[str, Any]:
    """Hidratación completa de la escena 3D para un proyecto (§5.1).

    La topología se deriva de ``grafo.get_graph()`` —la misma fuente que el
    Mermaid de ``flujo-efectivo``— anotando cada nodo con su definición del
    registro/catálogo custom y el ``LLMConfig`` resuelto por rol. El wiring
    del grafo jamás se re-declara aquí ni en el cliente.
    """
    flujo = resolver_flujo(proyecto)
    grafo = build_pipeline_graph(_GatewayNulo(), proyecto)
    dibujo = grafo.get_graph()
    definiciones = definiciones_del_proyecto(proyecto)
    nodo_a_rol = {d.nodo: rol for rol, d in definiciones.items()}
    fases = _fases_del_flujo(proyecto, flujo)
    nodo_compuerta = definiciones[flujo.revisor].nodo if flujo.revisor else None

    nodes: List[Dict[str, Any]] = []
    for nid in dibujo.nodes:
        if nid in ("__start__", "__end__"):
            continue  # anclas discretas: solo aparecen como extremos de aristas
        rol = nodo_a_rol.get(nid)
        if rol is None:
            nodes.append({
                "id": nid,
                "rol": None,
                "tipo": "cierre",
                "fase": fases[nid],
                "estructural": True,
                "descripcion": _CIERRE_DESCRIPCIONES[nid],
                "esencial": False,
                "llm": None,
            })
            continue
        definicion = definiciones[rol]
        config = proyecto.config_de_agente(rol)
        node: Dict[str, Any] = {
            "id": nid,
            "rol": rol,
            "tipo": definicion.tipo,
            "fase": fases[nid],
            "estructural": nid in ("plan_series", nodo_compuerta),
            "descripcion": definicion.descripcion,
            "esencial": definicion.esencial,
            "llm": _llm_resuelto(proyecto, rol),
        }
        if config.es_custom:
            node["custom"] = {
                "contrato": config.contrato,
                "entradas": list(config.entradas),
                "instrucciones": config.instrucciones,
            }
        nodes.append(node)

    edges: List[Dict[str, Any]] = []
    por_par: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for arista in dibujo.edges:
        par = por_par.setdefault(
            (arista.source, arista.target), {"condicional": False, "labels": []}
        )
        if arista.conditional:
            par["condicional"] = True
            if arista.data:
                par["labels"].append(arista.data)
    for (origen, destino), info in por_par.items():
        edges.append({
            "id": f"{origen}->{destino}",
            "from": origen,
            "to": destino,
            "condicional": info["condicional"],
            "labels": info["labels"],
        })

    return {
        "project_id": proyecto.project_id,
        "declarado": flujo.declarado,
        "hasta": flujo.hasta,
        "nodes": nodes,
        "edges": edges,
        "limite_recursion": limite_de_recursion(flujo, 3, 2),
    }


def create_app(
    store: Optional[SqliteJobStore] = None,
    worker: Optional[SeriesWorker] = None,
    data_dir: Optional[Path] = None,
    project_store: Optional[ProjectFileStore] = None,
) -> FastAPI:
    """Fábrica de la aplicación (permite inyectar dobles en tests)."""
    data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
    store = store or SqliteJobStore(data_dir / "jobs.sqlite")
    if project_store is None:
        escribible = resolve_writable_projects_dir(data_dir)
        empaquetado = packaged_projects_dir()
        project_store = ProjectFileStore(
            escribible,
            builtin_dir=empaquetado if empaquetado != escribible else None,
        )
    lore_store = JsonLoreStore(root=data_dir / "continuidad")
    # Biblioteca de recursos ancla bajo el mismo raíz de datos (spec-recursos-
    # ancla §4.2): la lee el CRUD (Fase 1) y el cargador de baterías del media.
    anchor_store = JsonAnchorStore(root=data_dir / "anclas")
    worker = worker or SeriesWorker(
        store,
        checkpoint_dir=data_dir / "checkpoints",
        audit_root=data_dir / "auditoria",
        lore_root=data_dir / "continuidad",
        anchor_root=data_dir / "anclas",
        project_loader=project_store.load,
        spec_reader=project_store.read_raw,
        # Capa de media (spec-recursos-ancla §6, Fase 3): el factory devuelve
        # None salvo que el proyecto declare [media].keyframes = true — sin
        # media, ni siquiera se instancia un adaptador. Los eventos en vivo
        # los conecta el runner (sink del job → SSE).
        media_factory=lambda proyecto: construir_dependencias_de_media(
            proyecto,
            almacen=AlmacenMedia(root=data_dir / "media"),
            anchor_store=anchor_store,
        ),
    )
    worker.start()

    app = FastAPI(title="Sinnema", version="0.1.0",
                  description="Motor multi-agente de series de micro-videos verticales.")

    def _owner(x_owner: Optional[str]) -> str:
        return (x_owner or "anon").strip()[:60] or "anon"

    def _job_or_404(job_id: str) -> Job:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(404, f"No existe el job '{job_id}'.")
        return job

    def _proyecto_o_404(project_id: str):
        """Carga el ProjectSpec; 404 si no existe, 400 si el TOML es inválido."""
        try:
            return project_store.load(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc

    # --------------------------------- API ---------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "worker_activo": worker._thread is not None and worker._thread.is_alive(),
            "jobs_en_cola": worker.pending(),
        }

    @app.get("/api/projects")
    def projects() -> list[dict]:
        return [
            {
                "project_id": p.project_id,
                "brand_name": p.brand_name,
                "concepto": p.show_concept,
                "default_topic": p.default_topic,
                "audience": p.audience,
                "language": p.language,
                "editable": project_store.is_editable(p.project_id),
            }
            for p in project_store.list_merged()
        ]

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict:
        try:
            crudo = project_store.read_raw(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        crudo["editable"] = project_store.is_editable(project_id)
        return crudo

    @app.post("/api/projects", status_code=201)
    def create_project(cuerpo: dict) -> dict:
        try:
            spec = project_store.create(cuerpo)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"project_id": spec.project_id, "creado": True}

    @app.put("/api/projects/{project_id}")
    def update_project(project_id: str, cuerpo: dict) -> dict:
        try:
            project_store.update(project_id, cuerpo)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"project_id": project_id, "actualizado": True}

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: str) -> dict:
        activos = [
            j for j in store.list_jobs(project_id=project_id)
            if j.status in (JobStatus.QUEUED, JobStatus.RUNNING)
        ]
        if activos:
            raise HTTPException(
                409,
                f"El proyecto '{project_id}' tiene {len(activos)} job(s) en cola "
                "o en ejecución: esperá a que terminen antes de borrarlo.",
            )
        try:
            project_store.delete(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"project_id": project_id, "borrado": True}

    @app.get("/api/projects/{project_id}/prompts")
    def project_prompts(project_id: str) -> dict:
        proyecto = _proyecto_o_404(project_id)
        return build_role_system_prompts(proyecto)

    @app.get("/api/projects/{project_id}/flujo-efectivo")
    def project_flujo_efectivo(project_id: str) -> dict:
        """Fases resueltas del proyecto, hito, límite de recursión y Mermaid.

        Compila el grafo efectivo con un gateway nulo (nunca genera contenido)
        para obtener el diagrama Mermaid, como el modo diagrama de
        ``scripts/ver_grafo.py``. El límite de recursión se estima con los
        defaults de corrida (3 capítulos, 2 reintentos de crítica).
        """
        proyecto = _proyecto_o_404(project_id)
        flujo = resolver_flujo(proyecto)
        grafo = build_pipeline_graph(_GatewayNulo(), proyecto)
        customs = [
            {
                "rol": rol,
                "tipo": definicion.tipo,
                "contrato": proyecto.agentes[rol].contrato,
                "entradas": list(proyecto.agentes[rol].entradas),
                "descripcion": definicion.descripcion,
            }
            for rol, definicion in definiciones_custom(proyecto).items()
        ]
        return {
            "project_id": proyecto.project_id,
            "declarado": flujo.declarado,
            "hasta": flujo.hasta,
            "fases": {
                "serie": [ROLE_PLANNER],
                "contexto": list(flujo.contexto),
                "escritor": [ROLE_SCRIPTWRITER],
                "transformaciones": list(flujo.transformaciones),
                "revisor": flujo.revisor,
                "enriquecimiento": list(flujo.enriquecimiento),
            },
            "custom": customs,
            "limite_recursion": limite_de_recursion(flujo, 3, 2),
            "mermaid": grafo.get_graph().draw_mermaid(),
        }

    @app.get("/api/projects/{project_id}/red")
    def project_red(project_id: str) -> dict:
        """Red efectiva de agentes del proyecto (hidratación de la escena 3D).

        Nodos + aristas del grafo compilado con un gateway nulo (nunca genera
        contenido), anotados con el registro de agentes y el ``LLMConfig``
        resuelto por rol. La derivación vive en ``_red_efectiva``.
        """
        return _red_efectiva(_proyecto_o_404(project_id))

    @app.get("/api/projects/{project_id}/lore")
    def project_lore(project_id: str) -> list[dict]:
        _proyecto_o_404(project_id)
        try:
            entradas = lore_store.load(project_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return [e.model_dump(mode="json") for e in entradas]

    @app.delete("/api/projects/{project_id}/lore")
    def reset_project_lore(project_id: str) -> dict:
        _proyecto_o_404(project_id)
        lore_store.save(project_id, [])
        return {"project_id": project_id, "lore": []}

    # ------------------- Anclas: biblioteca visual (§9.1) -------------------

    def _biblioteca(project_id: str) -> list[RecursoAncla]:
        try:
            return anchor_store.load(project_id)
        except ValueError as exc:  # slug imposible: no expone 500 ni rutas
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    def _ancla_o_404(project_id: str, ancla_id: str) -> RecursoAncla:
        ancla = next(
            (a for a in _biblioteca(project_id) if a.ancla_id == ancla_id), None
        )
        if ancla is None:
            raise HTTPException(
                404, f"El proyecto '{project_id}' no tiene ancla '{ancla_id}'."
            )
        return ancla

    def _contrato_invalido(exc: ValidationError) -> HTTPException:
        """400 accionable: los errores de Pydantic aplanados a una línea."""
        detalle = "; ".join(
            f"{'.'.join(str(p) for p in error['loc']) or 'cuerpo'}: {error['msg']}"
            for error in exc.errors()
        )
        return HTTPException(400, f"Contrato de ancla inválido: {detalle}.")

    def _guardar(project_id: str, anclas: list[RecursoAncla]) -> None:
        try:
            anchor_store.save(project_id, anclas)
        except ValueError as exc:
            raise HTTPException(
                409 if "duplicado" in str(exc) else 400, str(exc)
            ) from exc

    def _qa_medio_por_ancla(project_id: str) -> Dict[str, Tuple[float, int]]:
        """QA medio por ancla sobre el media ENTREGADO de los jobs completados
        del proyecto (spec-recursos-ancla §9.2/§14: detectar baterías
        degradadas). Solo informes del candidato entregado por escena (los
        intentos intermedios ya están en ``qa_agotado`` y duplicarían); los
        informes de dedup (``ancla_id`` vacío) no corresponden a un ancla."""
        acumulado: Dict[str, List[float]] = {}
        for job in store.list_jobs(project_id=project_id):
            entregable = job.deliverable
            if not entregable:
                continue
            for episodio in entregable.get("episodes", []):
                for adjunto in episodio.get("adjuntos", []):
                    if adjunto.get("rol") != "media":
                        continue
                    keyframes = adjunto.get("artefacto", {}).get("keyframes", [])
                    for kf in keyframes:
                        for informe in kf.get("qa", []):
                            ancla_id = informe.get("ancla_id") or ""
                            if not ancla_id:
                                continue
                            acumulado.setdefault(ancla_id, []).append(
                                float(informe.get("score", 0.0))
                            )
        return {
            ancla: (sum(scores) / len(scores), len(scores))
            for ancla, scores in acumulado.items()
        }

    @app.get("/api/projects/{project_id}/anclas")
    def project_anclas(project_id: str) -> list[dict]:
        """Biblioteca de anclas del proyecto completa (batería, estado,
        version, QA medio del media entregado; spec-recursos-ancla §9.1)."""
        _proyecto_o_404(project_id)
        qa_medio = _qa_medio_por_ancla(project_id)
        salida = []
        for ancla in _biblioteca(project_id):
            datos = ancla.model_dump(mode="json")
            media, muestras = qa_medio.get(ancla.ancla_id, (None, 0))
            datos["qa_medio"] = None if media is None else round(media, 3)
            datos["qa_muestras"] = muestras
            salida.append(datos)
        return salida

    @app.post("/api/projects/{project_id}/anclas", status_code=201)
    def crear_ancla(project_id: str, cuerpo: dict) -> dict:
        """Alta de un ancla, siempre en estado ``borrador``: el lock va por
        ``POST .../lock`` y el retiro por ``DELETE`` (nunca por el cuerpo)."""
        _proyecto_o_404(project_id)
        datos = {
            clave: cuerpo[clave]
            for clave in ("ancla_id", "tipo", "nombre", "descripcion_canonica")
            if clave in cuerpo
        }
        datos["estado"] = "borrador"
        try:
            ancla = RecursoAncla.model_validate(datos)
        except ValidationError as exc:
            raise _contrato_invalido(exc) from exc
        biblioteca = _biblioteca(project_id)
        for existente in biblioteca:
            if existente.ancla_id == ancla.ancla_id:
                raise HTTPException(
                    409,
                    f"Ya existe un ancla con id '{ancla.ancla_id}' en el "
                    "proyecto (cada ancla necesita un slug único).",
                )
            if existente.nombre.casefold() == ancla.nombre.casefold():
                raise HTTPException(
                    409,
                    f"Ya existe un ancla llamada '{existente.nombre}' (los "
                    "nombres son únicos sin distinguir mayúsculas).",
                )
        _guardar(project_id, [*biblioteca, ancla])
        return ancla.model_dump(mode="json")

    @app.get("/api/projects/{project_id}/anclas/{ancla_id}")
    def detalle_ancla(project_id: str, ancla_id: str) -> dict:
        _proyecto_o_404(project_id)
        return _ancla_o_404(project_id, ancla_id).model_dump(mode="json")

    @app.put("/api/projects/{project_id}/anclas/{ancla_id}")
    def editar_ancla(project_id: str, ancla_id: str, cuerpo: dict) -> dict:
        """Edita ``nombre`` y ``descripcion_canonica``. Decisión de diseño: el
        estado NO se cambia por acá (claves extra → 400) — el lock es un
        endpoint propio con verificación de batería y el retiro es el DELETE;
        la batería se muta con el upload de imágenes."""
        _proyecto_o_404(project_id)
        ancla = _ancla_o_404(project_id, ancla_id)
        prohibidas = sorted(set(cuerpo) - {"nombre", "descripcion_canonica"})
        if prohibidas:
            raise HTTPException(
                400,
                "Solo se pueden editar 'nombre' y 'descripcion_canonica' "
                f"(rechazadas: {', '.join(prohibidas)}); el estado se cambia "
                "con lock/retiro y la batería con el upload de imágenes.",
            )
        datos = ancla.model_dump()
        datos.update(
            {clave: cuerpo[clave] for clave in ("nombre", "descripcion_canonica")
             if clave in cuerpo}
        )
        try:
            editada = RecursoAncla.model_validate(datos)
        except ValidationError as exc:
            raise _contrato_invalido(exc) from exc
        _guardar(
            project_id,
            [editada if a.ancla_id == ancla_id else a
             for a in _biblioteca(project_id)],
        )
        return editada.model_dump(mode="json")

    @app.delete("/api/projects/{project_id}/anclas/{ancla_id}")
    def retirar_ancla(project_id: str, ancla_id: str) -> dict:
        """Retiro (§4.1: retirar NO borra): el registro queda con estado
        ``retirado``, los archivos de la batería permanecen y las anclas ya
        citadas por episodios pasados siguen resolviendo. Idempotente."""
        _proyecto_o_404(project_id)
        ancla = _ancla_o_404(project_id, ancla_id)
        if ancla.estado != "retirado":
            datos = ancla.model_dump()
            datos["estado"] = "retirado"
            retirada = RecursoAncla.model_validate(datos)
            _guardar(
                project_id,
                [retirada if a.ancla_id == ancla_id else a
                 for a in _biblioteca(project_id)],
            )
            ancla = retirada
        return {
            "project_id": project_id,
            "ancla_id": ancla_id,
            "estado": ancla.estado,
            "retirado": True,
        }

    @app.post(
        "/api/projects/{project_id}/anclas/{ancla_id}/imagenes", status_code=201,
    )
    async def subir_imagen(
        project_id: str, ancla_id: str,
        rol: str = Form(...), archivo: UploadFile = File(...),
    ) -> dict:
        """Upload multipart de una imagen a la batería (origen ``subida``).

        Valida rol↔tipo (400), formato por extensión en lista blanca (400) y
        tamaño máximo (413). El nombre ``<rol>_<n>.<ext>`` lo genera el
        servidor con el correlativo siguiente del rol. Subir a una ancla
        lockeada cambia la batería: el almacén sube su ``version`` (§4.1).
        """
        _proyecto_o_404(project_id)
        ancla = _ancla_o_404(project_id, ancla_id)
        if rol not in ROLES_POR_TIPO[ancla.tipo]:
            raise HTTPException(
                400,
                f"El rol '{rol or 'vacío'}' no corresponde al tipo "
                f"'{ancla.tipo}' (válidos: "
                f"{', '.join(ROLES_POR_TIPO[ancla.tipo])}).",
            )
        extension = Path(archivo.filename or "").suffix.lower()
        if extension not in EXTENSIONES_DE_IMAGEN:
            raise HTTPException(
                400,
                f"Formato de imagen no soportado ('{extension or 'sin extensión'}'); "
                f"formatos aceptados: {', '.join(sorted(EXTENSIONES_DE_IMAGEN))}.",
            )
        datos = await archivo.read(TAMANO_MAXIMO_DE_IMAGEN + 1)
        if len(datos) > TAMANO_MAXIMO_DE_IMAGEN:
            raise HTTPException(
                413,
                "La imagen supera el máximo de "
                f"{TAMANO_MAXIMO_DE_IMAGEN // (1024 * 1024)} MB.",
            )
        nombre = _siguiente_archivo_de_rol(ancla, rol, extension)
        try:
            anchor_store.guardar_imagen(project_id, ancla_id, nombre, datos)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        ficha = ancla.model_dump()
        ficha["bateria"].append(
            {"rol": rol, "archivo": nombre, "origen": "subida"}
        )
        actualizada = RecursoAncla.model_validate(ficha)
        _guardar(
            project_id,
            [actualizada if a.ancla_id == ancla_id else a
             for a in _biblioteca(project_id)],
        )
        return actualizada.model_dump(mode="json")

    @app.get("/api/projects/{project_id}/anclas/{ancla_id}/imagenes/{archivo}")
    def servir_imagen(project_id: str, ancla_id: str, archivo: str):
        """Serving de media de la batería (§9.1/§14): nombre plano sin
        traversal y sin symlinks que escapen (``ruta_imagen`` del almacén),
        solo archivos registrados en la batería, content-type fijo por
        extensión y nombres generados por el servidor."""
        try:
            ancla = _ancla_o_404(project_id, ancla_id)
            if not any(i.archivo == archivo for i in ancla.bateria):
                raise HTTPException(
                    404,
                    f"La ancla '{ancla_id}' no tiene imagen '{archivo}'.",
                )
            media_type = EXTENSIONES_DE_IMAGEN.get(Path(archivo).suffix.lower())
            ruta = anchor_store.ruta_imagen(project_id, ancla_id, archivo)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if media_type is None or not ruta.is_file():
            raise HTTPException(
                404, f"La ancla '{ancla_id}' no tiene imagen '{archivo}'."
            )
        # El nombre (rol_n) nunca se re-escribe con otro contenido, así que
        # un cache de un día es seguro.
        return FileResponse(
            ruta,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.post("/api/projects/{project_id}/anclas/{ancla_id}/lock")
    def lockear_ancla(project_id: str, ancla_id: str) -> dict:
        """Lock humano (§1/§4.1): verifica la batería mínima del tipo y, si no
        alcanza, responde 400 con los roles faltantes (error accionable). El
        re-lock de una ancla ya lockeada es un no-op que la devuelve."""
        _proyecto_o_404(project_id)
        ancla = _ancla_o_404(project_id, ancla_id)
        roles = {imagen.rol for imagen in ancla.bateria}
        faltantes = [
            rol for rol in BATERIA_MINIMA[ancla.tipo] if rol not in roles
        ]
        if not bateria_minima_cumplida(ancla.tipo, roles):
            raise HTTPException(
                400,
                f"No se puede lockear '{ancla_id}': a la batería mínima de un "
                f"'{ancla.tipo}' le faltan imágenes de rol: "
                f"{', '.join(faltantes)} (spec-recursos-ancla §4.1).",
            )
        if ancla.estado != "lockeado":
            datos = ancla.model_dump()
            datos["estado"] = "lockeado"
            lockeada = RecursoAncla.model_validate(datos)
            _guardar(
                project_id,
                [lockeada if a.ancla_id == ancla_id else a
                 for a in _biblioteca(project_id)],
            )
            ancla = lockeada
        return ancla.model_dump(mode="json")

    @app.get("/api/meta/roles")
    def meta_roles() -> list[dict]:
        """Catálogo de agentes desde el registro (rol, tipo, descripción,
        esencial) con los defaults LLM de ``DEFAULT_ROLE_SPECS``."""
        defaults = {s.role: s for s in DEFAULT_ROLE_SPECS}
        respuesta = []
        for rol, definicion in AGENT_REGISTRY.items():
            item = {
                "rol": rol,
                "tipo": definicion.tipo,
                "descripcion": definicion.descripcion,
                "esencial": definicion.esencial,
                "desactivable": rol not in ROLES_ESENCIALES,
            }
            default = defaults.get(rol)
            if default is not None:
                item.update(
                    proveedor=default.provider,
                    modelo=default.model,
                    temperatura=default.temperature,
                )
            respuesta.append(item)
        return respuesta

    @app.get("/api/meta/catalogos")
    def meta_catalogos() -> dict:
        """Catálogos para los formularios de la web (spec-red-3d §5).

        Proveedores con sus modelos sugeridos (los que usan los defaults del
        sistema), tools integradas, hitos del pipeline, vocabulario de los
        agentes custom (tipos, contratos, entradas), catálogos de la
        biblioteca de anclas (tipos, estados, roles por tipo y batería mínima
        de lock, spec-recursos-ancla §9.1) y proveedores de imagen de la capa
        de media (Fase 3).
        """
        modelos: Dict[str, List[str]] = {proveedor: [] for proveedor in PROVEEDORES}
        for spec in (*DEFAULT_ROLE_SPECS, DEFAULT_CUSTOM_ROLE_SPEC):
            if spec.model not in modelos[spec.provider]:
                modelos[spec.provider].append(spec.model)
        return {
            "proveedores": list(PROVEEDORES),
            "modelos": modelos,
            "tools": [
                {"nombre": tool.nombre, "descripcion": tool.descripcion}
                for tool in TOOLS_INTEGRADAS.values()
            ],
            "hitos": list(ALCANCES),
            "tipos_custom": list(TIPOS_CUSTOM),
            "contratos": sorted(CONTRATOS_VALIDOS),
            "entradas_custom": sorted(CATALOGO_ENTRADAS),
            "proveedores_imagen": list(PROVEEDORES_DE_IMAGEN),
            "anclas": {
                "tipos": list(TIPOS_DE_ANCLA),
                "estados": list(ESTADOS_DE_ANCLA),
                "roles_por_tipo": {
                    tipo: list(roles) for tipo, roles in ROLES_POR_TIPO.items()
                },
                "bateria_minima": {
                    tipo: list(roles) for tipo, roles in BATERIA_MINIMA.items()
                },
            },
        }

    @app.post("/api/series", status_code=202)
    def create_series(cuerpo: SeriesRequestBody, x_owner: Optional[str] = Header(None)) -> dict:
        proyecto = _proyecto_o_404(cuerpo.project_id)
        tema = (cuerpo.topic or "").strip() or proyecto.default_topic
        intentos = (
            cuerpo.max_critique_attempts
            if cuerpo.max_critique_attempts is not None
            else (proyecto.pipeline.intentos_maximos_de_critica or 2)
        )
        job = store.create_job(
            owner=_owner(x_owner),
            project_id=proyecto.project_id,
            topic=tema,
            num_chapters=cuerpo.num_chapters,
            max_critique_attempts=intentos,
        )
        worker.submit(job.job_id)
        return {"job_id": job.job_id, "status": job.status.value}

    @app.get("/api/jobs")
    def jobs(
        x_owner: Optional[str] = Header(None),
        project_id: Optional[str] = None,
    ) -> list[dict]:
        owner = _owner(x_owner)
        return [
            _job_dict(j)
            for j in store.list_jobs(owner, project_id=project_id)
            if j.owner == owner
        ]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return _job_dict(_job_or_404(job_id), with_deliverable=True)

    def _job_dict(job: Job, with_deliverable: bool = False) -> dict:
        """Forma §4 del Job, con ``spec_desfasado`` (§11.4): para jobs en
        curso, True si el TOML cambió desde que se congeló su huella."""
        datos = job.to_dict(with_deliverable=with_deliverable)
        if job.status is JobStatus.RUNNING:
            desfasado = False
            if job.spec_fingerprint is not None:
                try:
                    vigente = fingerprint_spec(project_store.read_raw(job.project_id))
                    desfasado = vigente != job.spec_fingerprint
                except Exception:  # noqa: BLE001 - sin TOML legible no se afirma nada
                    logger.warning(
                        "No se pudo recalcular el fingerprint del job %s.",
                        job.job_id, exc_info=True,
                    )
            datos["spec_desfasado"] = desfasado
        return datos

    @app.get("/api/jobs/{job_id}/events/history")
    def job_events_history(job_id: str, since: int = 0) -> list[dict]:
        """Timeline completa del job (mismos registros que el SSE, §6.3)."""
        _job_or_404(job_id)
        return [_evento_dict(ev) for ev in store.events_since(job_id, since)]

    # ----------------------- Auditoría / artefactos -----------------------

    def _audit_dir_del_job(job: Job) -> Path:
        return getattr(worker, "audit_root", Path("auditoria")) / job.project_id / (
            f"serie_{job.job_id}"
        )

    @app.get("/api/jobs/{job_id}/artifacts")
    def job_artifacts(job_id: str) -> list[dict]:
        """Pasos de auditoría del job (§5): lista para el timeline del inspector."""
        job = _job_or_404(job_id)
        carpeta = _audit_dir_del_job(job)
        if not carpeta.is_dir():
            return []
        pasos = []
        for archivo in sorted(carpeta.glob("[0-9][0-9][0-9]_*.txt")):
            if archivo.stem.endswith("_prompts"):
                continue
            n, paso, resumen = _parsear_paso(archivo)
            pasos.append({"n": n, "paso": paso, "resumen": resumen})
        return pasos

    @app.get("/api/jobs/{job_id}/artifacts/{n}")
    def job_artifact(job_id: str, n: int) -> dict:
        """Un paso parseado: resumen, artefacto JSON y prompts (§7.4)."""
        job = _job_or_404(job_id)
        carpeta = _audit_dir_del_job(job)
        destino = next(
            (a for a in carpeta.glob(f"{n:03d}_*.txt") if not a.stem.endswith("_prompts")),
            None,
        )
        if destino is None:
            raise HTTPException(404, f"El job '{job_id}' no tiene paso {n:03d}.")
        n_leido, paso, resumen, artefacto = _parsear_paso(destino, con_artefacto=True)
        prompts_archivo = next(carpeta.glob(f"{n:03d}_*_prompts.txt"), None)
        return {
            "n": n_leido,
            "paso": paso,
            "resumen": resumen,
            "artefacto": artefacto,
            "prompts": (
                prompts_archivo.read_text(encoding="utf-8")
                if prompts_archivo is not None
                else None
            ),
        }

    def _parsear_paso(archivo: Path, con_artefacto: bool = False):
        lineas = archivo.read_text(encoding="utf-8").splitlines()
        # Encabezado: "Paso NNN · <paso>"; resumen tras la línea de fecha.
        titulo = lineas[0] if lineas else ""
        n = int(titulo.split("·")[0].split()[-1]) if "·" in titulo else 0
        paso = titulo.split("·", 1)[1].strip() if "·" in titulo else archivo.stem
        try:
            resumen = lineas[3]
        except IndexError:
            resumen = ""
        artefacto = None
        if con_artefacto and "Artefacto generado (JSON):" in lineas:
            desde = lineas.index("Artefacto generado (JSON):") + 1
            try:
                artefacto = json.loads("\n".join(lineas[desde:]).strip() or "null")
            except json.JSONDecodeError:
                artefacto = None
        return (n, paso, resumen, artefacto) if con_artefacto else (n, paso, resumen)

    def _evento_dict(ev) -> dict:
        """Forma §4 del RuntimeExecutionEvent: kind/job_id/ts + mensaje
        legacy o payload estructurado fusionado."""
        datos: Dict[str, Any] = {
            "kind": ev.kind, "job_id": ev.job_id, "ts": ev.ts,
        }
        if ev.payload is not None:
            datos.update(ev.payload)
        else:
            datos["mensaje"] = ev.message
        return datos

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str) -> StreamingResponse:
        """Progreso en vivo vía Server-Sent Events (§6.3): el frame conserva
        `id:` y `event: <kind>`; `data` es JSON con el kind y su payload."""
        _job_or_404(job_id)

        async def stream():
            last_id = 0
            while True:
                eventos = store.events_since(job_id, last_id)
                for ev in eventos:
                    last_id = ev.id
                    data = json.dumps(_evento_dict(ev), ensure_ascii=False)
                    yield f"id: {ev.id}\nevent: {ev.kind}\ndata: {data}\n\n"
                job = store.get_job(job_id)
                if job is not None and job.status in TERMINAL_STATUSES and not eventos:
                    yield "event: end\ndata: fin\n\n"
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/jobs/{job_id}/deliverable")
    def job_deliverable(job_id: str):
        job = _job_or_404(job_id)
        if job.deliverable is None:
            raise HTTPException(
                409, f"El job '{job_id}' aún no tiene entregable "
                     f"(estado: {job.status.value})."
            )
        return JSONResponse(content=job.deliverable)

    @app.get("/api/jobs/{job_id}/viewer", response_class=HTMLResponse)
    def job_viewer(job_id: str):
        job = _job_or_404(job_id)
        if job.deliverable is None:
            raise HTTPException(
                409, f"El job '{job_id}' aún no tiene entregable "
                     f"(estado: {job.status.value})."
            )
        return HTMLResponse(render_deliverable_html(job.deliverable))

    # --------------------------------- web ---------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index():
        # UI 3D (web/dist) si hay build; si no, la página "sin construir".
        dist_index = WEB_DIST_DIR / "index.html"
        if dist_index.is_file():
            return FileResponse(dist_index)
        return HTMLResponse(_SIN_BUILD)

    @app.get("/assets/{ruta:path}", include_in_schema=False)
    def assets(ruta: str) -> FileResponse:
        # Assets del build de Vite (JS/CSS). Con el legacy, esta ruta no existe.
        destino = (WEB_DIST_DIR / "assets" / ruta).resolve()
        raiz_assets = (WEB_DIST_DIR / "assets").resolve()
        if destino.is_file() and destino.is_relative_to(raiz_assets):
            return FileResponse(destino)
        raise HTTPException(404, "Asset no encontrado (¿falta `npm run build` en web/?)")

    return app


def main() -> int:
    """Entry point ``sinnema-server``: levanta la API + web."""
    logging.basicConfig(
        level=os.environ.get("SINNEMA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    host = os.environ.get("SINNEMA_HOST", "127.0.0.1")
    port = int(os.environ.get("SINNEMA_PORT", "8000"))
    if os.environ.get("SINNEMA_RELOAD", "").strip().lower() in ("1", "true", "yes"):
        # Hot reload (issue #14): exige import string porque el supervisor de
        # uvicorn relanza el proceso. Solo se vigila el código del motor:
        # reiniciar por un cambio de datos/TOML mataría los jobs en curso.
        opciones = {}
        if Path("sinnema").is_dir():
            opciones["reload_dirs"] = ["sinnema"]
        uvicorn.run(
            "sinnema.infrastructure.api.app:create_app",
            factory=True,
            host=host,
            port=port,
            reload=True,
            log_level="warning",
            **opciones,
        )
        return 0
    app = create_app()
    print(f"Sinnema sirviendo en http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

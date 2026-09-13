"""Pipeline con capa de media (spec-recursos-ancla §6, Fase 3 — Hito 2).

Cubren: parseo de ``[media]`` (defaults off, paridad), composición pura de
pedidos, topología con y sin ``render_keyframes``, adjunto ``media`` por
episodio (manifest con anclas_usadas EN ORDEN), encadenado last-frame →
first-frame, semántica de fallo (escena sin media, la corrida sigue) y
eventos ``media_start``/``media_end`` hasta el store del job (el mismo canal
que alimenta el SSE).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sinnema.application.graph import build_pipeline_graph
from sinnema.application.ports import DependenciasMedia
from sinnema.application.projects import MediaConfig, project_from_dict, resolver_flujo
from sinnema.application.requests import build_initial_state
from sinnema.application.use_cases import GenerateSeriesUseCase, limite_de_recursion
from sinnema.domain.models import MediaCrudo, ManifestDeGeneracion, ReferenciaAncla
from sinnema.domain.services import componer_pedido_escena, pares_identidad_primero
from sinnema.infrastructure.media import AlmacenMedia
from sinnema.infrastructure.runtime.jobs import SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker

from conftest import (
    gateway_con_serie,
    make_ancla,
    make_draft,
    make_package,
    make_project,
    make_request,
)

PROJECT_ID = "sinnema"
DESCRIPTOR = (
    "A friendly recurring character described with stable canonical traits "
    "for image models"
)


class AuditRegistrada:
    """Doble de AuditTrailPort que graba pasos, resúmenes y eventos."""

    def __init__(self) -> None:
        self.eventos: list[str] = []
        self.pasos: list[str] = []
        self.resumenes: list[str] = []
        self.fallos: list[str] = []

    def log_step(self, step, summary, artifact=None, details=None) -> None:
        self.pasos.append(step)
        self.resumenes.append(summary)

    def log_event(self, message: str) -> None:
        self.eventos.append(message)

    def log_failure(self, message: str) -> None:
        self.fallos.append(message)
        self.eventos.append(message)


def _correr(use_case, request):
    final = None
    for final in use_case.stream(request):
        pass
    return final


def _manifest_de(pedido, catalogo):
    """Manifest determinista del puerto falso: anclas_usadas EN ORDEN."""
    por_id = {a.ancla_id: a for a in catalogo}
    return ManifestDeGeneracion(
        proveedor="falso",
        modelo="falso-1",
        seed=None,
        prompt_final=pedido.prompt_final,
        anclas_usadas=[
            (r.ancla_id, por_id[r.ancla_id].version, r.roles[0] if r.roles else "hero_portrait")
            for r in pedido.anclas
        ],
        parametros={"aspect_ratio": pedido.aspect_ratio},
        id_externo=f"fake-{pedido.scene_number}",
        creado_en=datetime(2026, 9, 12, tzinfo=timezone.utc),
    )


class PuertoMediaFalso:
    """Doble de ``MediaGenerationPort``: graba pedidos y devuelve keyframes."""

    def __init__(self, fallar_escenas=(), ultimo_frame=b"frame-final"):
        self.pedidos = []
        self.catalogos = []
        self.fallar = set(fallar_escenas)
        self.ultimo_frame = ultimo_frame

    def generar_keyframe(self, pedido, catalogo):
        self.pedidos.append(pedido)
        self.catalogos.append(list(catalogo))
        if pedido.scene_number in self.fallar:
            raise RuntimeError("proveedor caído tras 3 intentos")
        datos = f"imagen-escena-{pedido.scene_number}".encode()
        return MediaCrudo(
            datos=datos,
            formato="png",
            manifest=_manifest_de(pedido, catalogo),
            ultimo_frame=self.ultimo_frame,
        )


def _deps(puerto, tmp_path, eventos=None, proveedor="gemini"):
    return DependenciasMedia(
        puerto=puerto,
        almacen=AlmacenMedia(root=tmp_path / "media"),
        eventos=eventos,
        proveedor=proveedor,
    )


def _proyecto_media(**overrides) -> object:
    datos = dict(keyframes=True, encadenar_frames=True, proveedor_imagen="gemini")
    datos.update(overrides)
    return make_project(media=MediaConfig(**datos))


# ============================ [media] en el TOML ============================


def test_sin_seccion_media_todo_default_off():
    config = project_from_dict({
        "proyecto": {
            "id": "prueba", "marca": "Prueba", "concepto": "Un concepto suficientemente largo",
            "tema_por_defecto": "Un tema por defecto suficientemente largo",
            "idioma": "Español neutro",
        },
        "voz": {"audiencia": "Público de prueba", "contexto_cultural": "Contexto de prueba",
                "tono": "Tono de prueba", "guia_de_estilo": "Guía corta", "restricciones": "Ninguna"},
        "visual": {"estilo_maestro": "3D isometric render style for testing purposes"},
    }).media
    assert config == MediaConfig()  # keyframes False, video False, encadena True


def test_seccion_media_se_parsea_y_valida():
    base = {
        "proyecto": {
            "id": "prueba", "marca": "Prueba", "concepto": "Un concepto suficientemente largo",
            "tema_por_defecto": "Un tema por defecto suficientemente largo",
            "idioma": "Español neutro",
        },
        "voz": {"audiencia": "Público de prueba", "contexto_cultural": "Contexto de prueba",
                "tono": "Tono de prueba", "guia_de_estilo": "Guía corta", "restricciones": "Ninguna"},
        "visual": {"estilo_maestro": "3D isometric render style for testing purposes"},
    }
    valido = dict(base, media={"keyframes": True, "proveedor_imagen": "openai", "intentos_qa": 2})
    config = project_from_dict(valido).media
    assert config.keyframes is True
    assert config.proveedor_imagen == "openai"
    assert config.encadenar_frames is True
    assert config.intentos_qa == 2

    with pytest.raises(ValueError, match="video"):
        project_from_dict(dict(base, media={"video": True}))

    with pytest.raises(ValueError, match="proveedor_imagen"):
        project_from_dict(dict(base, media={"proveedor_imagen": "veo"}))

    with pytest.raises(ValueError, match="clave desconocida"):
        project_from_dict(dict(base, media={"fotogramas": True}))

    with pytest.raises(ValueError, match="intentos_qa"):
        project_from_dict(dict(base, media={"intentos_qa": 9}))


# ===================== composición pura de pedidos =====================


def test_pedido_compone_prompt_final_con_descriptores_identidad_primero():
    catalogo = [
        make_ancla("protagonista", estado="lockeado"),
        make_ancla("la-nave", tipo="lugar", estado="lockeado"),
    ]
    paquete = make_package(make_draft("ch-01"))
    spec = paquete.visual_specs[0].model_copy(
        update={
            "anclas": [
                ReferenciaAncla(ancla_id="la-nave"),
                ReferenciaAncla(ancla_id="protagonista"),
            ]
        }
    )
    pedido = componer_pedido_escena(paquete, spec, catalogo)

    # Identidad primero: el descriptor del personaje va antes que el del lugar.
    assert pedido.prompt_final.index("Protagonista") < pedido.prompt_final.index("La nave")
    assert DESCRIPTOR in pedido.prompt_final
    assert pedido.prompt_final.startswith(spec.image_prompt)
    assert pedido.aspect_ratio == paquete.aspect_ratio
    assert pedido.negative_prompt == spec.negative_prompt
    assert pedido.chapter_id == "ch-01"
    # Las referencias del pedido ya viajan reordenadas identidad-primero.
    assert [r.ancla_id for r in pedido.anclas] == ["protagonista", "la-nave"]
    assert pedido.frame_inicial is None


def test_pedido_sin_anclas_usa_solo_el_image_prompt():
    paquete = make_package(make_draft("ch-01"))
    pedido = componer_pedido_escena(paquete, paquete.visual_specs[0], [])
    assert pedido.prompt_final == paquete.visual_specs[0].image_prompt
    assert pedido.anclas == []


def test_pedido_con_frame_inicial_para_encadenado():
    paquete = make_package(make_draft("ch-01"))
    pedido = componer_pedido_escena(
        paquete, paquete.visual_specs[0], [], frame_inicial=b"frame-anterior"
    )
    assert pedido.frame_inicial == b"frame-anterior"


# ============================ topología ============================


def test_con_media_el_nodo_entra_entre_enriquecimiento_y_commit(tmp_path):
    proyecto = _proyecto_media()
    grafo = build_pipeline_graph(
        gateway_con_serie(1), proyecto, media=_deps(PuertoMediaFalso(), tmp_path)
    )
    aristas = {(e.source, e.target) for e in grafo.get_graph().edges}
    assert ("technical_director", "render_keyframes") in aristas
    assert ("render_keyframes", "commit_episode") in aristas


def test_sin_media_la_topologia_es_la_de_siempre(tmp_path):
    proyecto = _proyecto_media()
    grafo = build_pipeline_graph(gateway_con_serie(1), proyecto)
    nombres = {n.name for n in grafo.get_graph().nodes.values()}
    assert "render_keyframes" not in nombres
    aristas = {(e.source, e.target) for e in grafo.get_graph().edges}
    assert ("technical_director", "commit_episode") in aristas

    # Con keyframes=false pero dependencias inyectadas: tampoco entra.
    proyecto_sin = make_project(media=MediaConfig(keyframes=False))
    grafo_sin = build_pipeline_graph(
        gateway_con_serie(1), proyecto_sin, media=_deps(PuertoMediaFalso(), tmp_path)
    )
    assert "render_keyframes" not in {
        n.name for n in grafo_sin.get_graph().nodes.values()
    }


def test_limite_de_recursion_con_media_suma_un_paso_por_capitulo():
    flujo = resolver_flujo(make_project())
    base = limite_de_recursion(flujo, 2, 2)
    con_media = limite_de_recursion(flujo, 2, 2, media=True)
    assert con_media == base + 2


# ==================== adjunto media por episodio ====================


def test_corrida_con_keyframes_adjunta_media_con_manifest_ordenado(tmp_path):
    puerto = PuertoMediaFalso()
    audit = AuditRegistrada()
    proyecto = _proyecto_media()
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(1), proyecto, audit=audit, media=_deps(puerto, tmp_path)
    )
    final = _correr(use_case, make_request(num_chapters=1, project=proyecto))

    episodio = final["completed_episodes"][0]
    adjunto = next(a for a in episodio.adjuntos if a.rol == "media")
    media_episodio = adjunto.artefacto
    assert media_episodio["chapter_id"] == "ch-01"
    assert len(media_episodio["keyframes"]) == 6  # una por escena del paquete
    primero = media_episodio["keyframes"][0]
    assert primero["archivo"] == f"{PROJECT_ID}/ch-01/escena_1.png"
    assert primero["qa"] is None  # Fase 4
    manifest = primero["manifest"]
    assert manifest["proveedor"] == "falso"
    assert manifest["prompt_final"] == puerto.pedidos[0].prompt_final
    assert manifest["id_externo"] == "fake-1"
    # anclas_usadas del manifest (EN ORDEN) y paridad con el pedido.
    assert manifest["anclas_usadas"] == [
        [r.ancla_id, 1, "hero_portrait"] for r in puerto.pedidos[0].anclas
    ]
    # Los archivos quedaron en disco bajo la raíz de media.
    assert (tmp_path / "media" / PROJECT_ID / "ch-01" / "escena_1.png").read_bytes() == (
        b"imagen-escena-1"
    )
    # La pizarra queda vaciada tras el commit (los adjuntos viajan en el episodio).
    assert "media" not in (final.get("artefactos") or {})


def test_sin_anclas_en_el_estado_los_keyframes_igual_se_generan(tmp_path):
    """Escena sin anclas (o proyecto sin biblioteca): keyframe con el
    image_prompt tal cual — el media nunca exige biblioteca."""
    puerto = PuertoMediaFalso()
    proyecto = _proyecto_media()
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(1), proyecto, media=_deps(puerto, tmp_path)
    )
    final = _correr(use_case, make_request(num_chapters=1, project=proyecto))
    adjunto = next(a for a in final["completed_episodes"][0].adjuntos if a.rol == "media")
    assert len(adjunto.artefacto["keyframes"]) == 6
    assert all(k["manifest"]["anclas_usadas"] == [] for k in adjunto.artefacto["keyframes"])


# ============================ encadenado ============================


def test_encadenado_pasa_el_ultimo_frame_de_escena_n_a_n_mas_1(tmp_path):
    puerto = PuertoMediaFalso(ultimo_frame=b"frame-final")
    proyecto = _proyecto_media()
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(1), proyecto, media=_deps(puerto, tmp_path)
    )
    _correr(use_case, make_request(num_chapters=1, project=proyecto))

    frames = [p.frame_inicial for p in puerto.pedidos]
    assert frames[0] is None  # la primera escena no tiene frame previo
    assert all(frame == b"frame-final" for frame in frames[1:])


def test_sin_encadenar_frames_ningun_pedido_lleva_frame(tmp_path):
    puerto = PuertoMediaFalso(ultimo_frame=b"frame-final")
    proyecto = _proyecto_media(encadenar_frames=False)
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(1), proyecto, media=_deps(puerto, tmp_path)
    )
    _correr(use_case, make_request(num_chapters=1, project=proyecto))
    assert all(p.frame_inicial is None for p in puerto.pedidos)


def test_proveedor_sin_ultimo_frame_degrada_a_sin_encadenado_con_registro(tmp_path):
    puerto = PuertoMediaFalso(ultimo_frame=None)
    audit = AuditRegistrada()
    proyecto = _proyecto_media()
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(1), proyecto, audit=audit, media=_deps(puerto, tmp_path)
    )
    _correr(use_case, make_request(num_chapters=1, project=proyecto))
    assert all(p.frame_inicial is None for p in puerto.pedidos)
    assert any("sin encadenado" in e for e in audit.eventos)


def test_tras_escena_fallida_el_encadenado_se_rompe_sin_arrastre(tmp_path):
    puerto = PuertoMediaFalso(ultimo_frame=b"frame-final", fallar_escenas={3})
    proyecto = _proyecto_media()
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(1), proyecto, media=_deps(puerto, tmp_path)
    )
    _correr(use_case, make_request(num_chapters=1, project=proyecto))
    frames = {p.scene_number: p.frame_inicial for p in puerto.pedidos}
    assert frames[2] == b"frame-final"
    assert frames[4] is None  # la escena 3 falló: la 4 va sin frame inicial


# ======================== semántica de fallo ========================


def test_fallo_del_proveedor_deja_la_escena_sin_media_y_la_corrida_sigue(tmp_path):
    puerto = PuertoMediaFalso(fallar_escenas={2, 5})
    audit = AuditRegistrada()
    proyecto = _proyecto_media()
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(1), proyecto, audit=audit, media=_deps(puerto, tmp_path)
    )
    final = _correr(use_case, make_request(num_chapters=1, project=proyecto))

    episodio = final["completed_episodes"][0]
    adjunto = next(a for a in episodio.adjuntos if a.rol == "media")
    assert len(adjunto.artefacto["keyframes"]) == 4
    errores = adjunto.artefacto["errores"]
    assert sorted(e["escena"] for e in errores) == [2, 5]
    assert all("proveedor caído" in e["error"] for e in errores)
    # Registro en auditoría y el episodio se consolida igual.
    assert len(audit.fallos) == 2
    assert episodio.chapter_id == "ch-01"


def test_proyecto_sin_paquete_tecnico_no_genera_media(tmp_path):
    """Sin director técnico no hay specs: el nodo no falla ni adjunta nada."""
    from sinnema.application.projects import AgentConfig

    from conftest import make_audit, make_adapted, make_directives, make_plan

    class GatewaySinDirector:
        def __init__(self):
            self.calls = []

        def generate(self, role, schema, system_prompt, user_prompt):
            self.calls.append(role)
            if role == "planner":
                return make_plan(1)
            if role == "continuity":
                return make_directives()
            if role == "scriptwriter":
                return make_draft("ch-01")
            if role == "adapter":
                return make_adapted(make_draft("ch-01"))
            if role == "critic":
                return make_audit(approved=True)
            raise AssertionError(f"rol inesperado: {role}")

    audit = AuditRegistrada()
    # Director técnico desactivado: ningún nodo produce TechnicalPackage.
    proyecto = make_project(
        media=MediaConfig(keyframes=True),
        agentes={"technical_director": AgentConfig(activo=False)},
    )
    use_case = GenerateSeriesUseCase(
        GatewaySinDirector(), proyecto, audit=audit, media=_deps(PuertoMediaFalso(), tmp_path)
    )
    final = _correr(use_case, make_request(num_chapters=1, project=proyecto))
    episodio = final["completed_episodes"][0]
    assert episodio.technical is None
    assert all(a.rol != "media" for a in episodio.adjuntos)
    assert any("Sin paquete técnico" in r for r in audit.resumenes)


# ============================== eventos ==============================


def test_nodo_emite_media_start_y_media_end_por_el_canal_inyectado(tmp_path):
    puerto = PuertoMediaFalso(fallar_escenas={2})
    eventos = []
    proyecto = _proyecto_media()
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(1), proyecto, media=_deps(puerto, tmp_path, eventos=eventos.append)
    )
    _correr(use_case, make_request(num_chapters=1, project=proyecto))

    arranques = [e for e in eventos if e["tipo"] == "media_start"]
    finales = [e for e in eventos if e["tipo"] == "media_end"]
    assert [e["escena"] for e in arranques] == list(range(1, 7))
    assert all(e["proveedor"] == "gemini" for e in arranques)
    con_archivo = [e for e in finales if "archivo" in e]
    con_error = [e for e in finales if "error" in e]
    assert len(con_archivo) == 5
    assert len(con_error) == 1
    assert con_archivo[0]["escena"] == 1
    assert con_archivo[0]["archivo"].endswith("escena_1.png")
    assert con_error[0]["escena"] == 2
    assert eventos[0]["tipo"] == "media_start"


def _worker_de_prueba(tmp_path, proyecto, **kwargs):
    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    (tmp_path / "checkpoints").mkdir(parents=True, exist_ok=True)
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
        anchor_root=tmp_path / "anclas",
        **kwargs,
    )
    return store, worker


def test_media_start_y_media_end_llegan_al_store_del_job(tmp_path):
    """El runner convierte los eventos del nodo en eventos del job: el MISMO
    canal que alimenta el SSE (mismos registros que token/tool_*)."""
    proyecto = _proyecto_media()
    store, worker = _worker_de_prueba(
        tmp_path, proyecto,
        gateway_factory=lambda p: gateway_con_serie(num_chapters=1),
        project_loader=lambda pid: proyecto,
        media_factory=lambda p: DependenciasMedia(
            puerto=PuertoMediaFalso(),
            almacen=AlmacenMedia(root=tmp_path / "media"),
            proveedor="gemini",
        ),
    )
    job = store.create_job(owner="ana", project_id=proyecto.project_id,
                           topic="Un tema de prueba suficientemente largo",
                           num_chapters=1, max_critique_attempts=1)
    worker._run_job(job.job_id)  # sin hilo: determinista

    tipos = [e.kind for e in store.events_since(job.job_id)]
    assert tipos.count("media_start") == 6
    assert tipos.count("media_end") == 6
    primer_fin = next(
        e for e in store.events_since(job.job_id)
        if e.kind == "media_end" and "archivo" in (e.payload or {})
    )
    assert primer_fin.payload["escena"] == 1
    assert primer_fin.payload["proveedor"] == "gemini"


def test_worker_sin_media_factory_corre_sin_el_nodo(tmp_path):
    """Paridad en el worker: sin media_factory, nada de media (ni eventos)."""
    proyecto = make_project(media=MediaConfig(keyframes=True))  # deps no inyectadas
    store, worker = _worker_de_prueba(
        tmp_path, proyecto,
        gateway_factory=lambda p: gateway_con_serie(num_chapters=1),
        project_loader=lambda pid: proyecto,
    )
    job = store.create_job(owner="ana", project_id=proyecto.project_id,
                           topic="Un tema de prueba suficientemente largo",
                           num_chapters=1, max_critique_attempts=1)
    worker._run_job(job.job_id)
    assert store.get_job(job.job_id).status.value == "completed"
    tipos = [e.kind for e in store.events_since(job.job_id)]
    assert "media_start" not in tipos
    episodio = store.get_job(job.job_id).deliverable["episodes"][0]
    assert all(a["rol"] != "media" for a in episodio["adjuntos"])

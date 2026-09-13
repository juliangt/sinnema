"""Caso de uso principal: generar una serie completa para un proyecto."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterator, List, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver

from sinnema.application.graph import build_pipeline_graph
from sinnema.application.ports import (
    AnchorStorePort,
    AuditTrailPort,
    DependenciasMedia,
    LoreStorePort,
    NullAnchorStore,
    NullAuditTrail,
    NullLoreStore,
    StructuredGenerationPort,
)
from sinnema.application.projects import ProjectSpec, resolver_flujo
from sinnema.application.requests import SeriesRequest, build_initial_state
from sinnema.application.settings import PipelineSettings
from sinnema.application.state import PipelineState
from sinnema.domain.constants import ALCANCE_DEFAULT
from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.models import (
    ImagenAncla,
    PedidoKeyframe,
    RecursoAncla,
    SeriesDeliverable,
)
from sinnema.domain.services import merge_lore, proponer_casting

logger = logging.getLogger("sinnema.use_cases")


def build_deliverable(state: Optional[PipelineState]) -> SeriesDeliverable:
    """Consolida el estado final del grafo en el entregable de salida."""
    if state is None or state.get("series_plan") is None:
        raise DomainValidationError(
            "El estado final no contiene un plan de serie: no se puede construir "
            "el entregable."
        )
    plan = state["series_plan"]
    episodios = state.get("completed_episodes", [])
    # Solo episodios con auditoría aportan score: los proyectos sin crítico
    # reportan 0.0 en vez de un promedio inventado.
    con_auditoria = [e.audit.overall_score for e in episodios if e.audit]
    promedio = (
        round(sum(con_auditoria) / len(con_auditoria), 2)
        if con_auditoria
        else 0.0
    )
    return SeriesDeliverable(
        project_id=state["project_id"],
        language=state["language"],
        series_title=plan.series_title,
        topic=state["topic"],
        audience=state["audience"],
        style_guide=state["style_guide"],
        alcance=state.get("alcance", ALCANCE_DEFAULT),
        total_chapters_planned=len(plan.chapters),
        episodes=episodios,
        failed_chapters=state.get("failed_chapters", []),
        average_quality_score=promedio,
        lore_glossary=state.get("lore_entries", []),
    )


def limite_de_recursion(
    flujo,
    num_chapters: int,
    max_attempts: int,
    media: bool = False,
) -> int:
    """Margen de pasos del grafo, derivado del flujo efectivo (§6.3).

    ``pasos_por_capitulo`` cubre el camino mínimo (contextos -> escritor ->
    transformaciones -> compuerta -> enriquecedores -> commit) y
    ``extra_por_reintento`` el ciclo de crítica (escritor -> ... -> revisor).
    Con la capa de media activa (``media = True``), ``render_keyframes`` suma
    un paso por capítulo.
    """
    pasos_por_capitulo = (
        len(flujo.contexto)
        + 1  # escritor
        + len(flujo.transformaciones)
        + (1 if flujo.revisor is not None else 0)
        + len(flujo.enriquecimiento)
        + (1 if media else 0)  # render_keyframes
        + 1  # commit
    )
    extra_por_reintento = 1 + len(flujo.transformaciones) + 1  # escritor->..->revisor
    return (
        10
        + num_chapters * pasos_por_capitulo
        + num_chapters * (max_attempts + 1) * extra_por_reintento
    )


class GenerateSeriesUseCase:
    """Orquesta el grafo completo para una petición de serie de un proyecto."""

    def __init__(
        self,
        gateway: StructuredGenerationPort,
        project: ProjectSpec,
        settings: Optional[PipelineSettings] = None,
        audit: Optional[AuditTrailPort] = None,
        lore_store: Optional[LoreStorePort] = None,
        anchor_store: Optional[AnchorStorePort] = None,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        media: Optional[DependenciasMedia] = None,
    ) -> None:
        self._project = project
        self._settings = settings or PipelineSettings()
        self._audit = audit or NullAuditTrail()
        self._lore_store: LoreStorePort = lore_store or NullLoreStore()
        self._anchor_store: AnchorStorePort = anchor_store or NullAnchorStore()
        #: Capa de media (spec-recursos-ancla §6): ``None`` = corrida sin
        #: media (nodo ``render_keyframes`` fuera del grafo: paridad).
        self._media = media
        # La biblioteca de anclas vive ANTES de la corrida (spec-recursos-ancla
        # §4.2): se carga una sola vez aquí y se siembra como catálogo fijo.
        # Solo participan las lockeadas (y nunca retiradas); un proyecto con
        # ``[visual] anclas = false`` la ignora por completo.
        self._anclas_lockeadas: List[RecursoAncla] = self._cargar_anclas_lockeadas()
        self._graph = build_pipeline_graph(
            gateway, project, self._settings, audit=self._audit,
            checkpointer=checkpointer, anclas=self._anclas_lockeadas,
            media=self._media,
        )

    def _cargar_anclas_lockeadas(self) -> List[RecursoAncla]:
        """Biblioteca lockeada del proyecto; vacía si el rol está desactivado."""
        if not self._project.anclas:
            return []
        anclas = self._anchor_store.load(self._project.project_id)
        return [
            ancla
            for ancla in anclas
            if ancla.estado == "lockeado" and ancla.estado != "retirado"
        ]

    @staticmethod
    def _recursion_limit(request: SeriesRequest, media: bool = False) -> int:
        """Margen de pasos del grafo: fórmula generalizada desde el flujo
        efectivo del proyecto (plan + capítulos + ciclos de crítica)."""
        return limite_de_recursion(
            resolver_flujo(request.project),
            request.num_chapters,
            request.max_critique_attempts,
            media=media,
        )

    def stream(
        self,
        request: SeriesRequest,
        thread_id: Optional[str] = None,
        on_nodo: Optional[Callable[[str, List[str], int], None]] = None,
    ) -> Iterator[PipelineState]:
        """Ejecuta el grafo cediendo el estado tras cada superstep (progreso).

        Siembra el lore persistido del proyecto como memoria inicial de la
        corrida; usar ``save_lore`` al terminar para consolidar la memoria.
        Con ``thread_id`` (y un checkpointer inyectado) el estado persiste y
        la corrida es reanudable bajo ese hilo.

        Con ``on_nodo`` (spec-red-3d §7.2) el stream suma el modo
        ``updates``: por cada nodo que corrió se invoca
        ``on_nodo(nodo, claves_actualizadas, superstep)`` — el runner lo
        traduce a los eventos ``node_start``/``node_end``. El contrato de
        salida del generador no cambia: sigue cediendo snapshots ``values``.
        """
        proyecto = request.project
        flujo = resolver_flujo(proyecto)
        self._audit.log_step(
            "solicitud",
            f"Generación solicitada para el proyecto '{proyecto.project_id}': "
            f"'{request.resolved_topic()}' ({request.num_chapters} capítulos).",
            details=[
                f"proyecto: {proyecto.project_id} ({proyecto.brand_name})",
                f"idioma: {proyecto.language}",
                f"tono de voz: {proyecto.tone_of_voice}",
                f"tema: {request.resolved_topic()}",
                f"capítulos: {request.num_chapters}",
                f"reintentos máx. de crítica: {request.max_critique_attempts}",
                f"alcance (hasta): {flujo.hasta}",
                f"flujo efectivo: {flujo.cadena()}",
                f"audiencia: {proyecto.audience}",
                f"contexto cultural: {proyecto.cultural_context}",
                f"guía de estilo: {proyecto.style_guide}",
                f"restricciones: {proyecto.constraints}",
            ],
        )
        lore_inicial = self._lore_store.load(proyecto.project_id)
        if lore_inicial:
            self._audit.log_event(
                f"Continuidad cargada: {len(lore_inicial)} entrada(s) de lore "
                "persistida(s) del proyecto."
            )
        if self._anclas_lockeadas:
            self._audit.log_event(
                f"Biblioteca de anclas cargada: {len(self._anclas_lockeadas)} "
                "ancla(s) lockeada(s) del proyecto siembran la corrida."
            )
        estado_inicial = build_initial_state(
            request,
            initial_lore=lore_inicial,
            initial_anclas=self._anclas_lockeadas,
        )
        config: Dict[str, Any] = {
            "recursion_limit": self._recursion_limit(
                request,
                media=self._media is not None and request.project.media.keyframes,
            )
        }
        if thread_id is not None:
            config["thread_id"] = thread_id
        if on_nodo is None:
            yield from self._graph.stream(estado_inicial, config=config, stream_mode="values")
            return
        superstep = 0
        for modo, datos in self._graph.stream(
            estado_inicial, config=config, stream_mode=["values", "updates"]
        ):
            if modo == "updates":
                superstep += 1
                for nodo, claves in datos.items():
                    if nodo.startswith("__"):
                        continue
                    on_nodo(nodo, list(claves.keys()), superstep)
            else:
                yield datos

    def save_lore(self, state: Optional[PipelineState]) -> None:
        """Consolida el lore acumulado de la corrida en el almacén del proyecto."""
        if state is None:
            return
        entradas = state.get("lore_entries", [])
        consolidado = merge_lore(self._lore_store.load(self._project.project_id), entradas)
        self._lore_store.save(self._project.project_id, consolidado)

    def save_anclas(self, state: Optional[PipelineState]) -> None:
        """Persiste la vigencia (first/last seen) que ``commit_episode`` estampó.

        Mismo camino que ``save_lore``: se llama una vez al final de la corrida
        sobre el estado final. Solo escribe si el libro contable cambió alguna
        ancla respecto de lo persistido (sin anclas usadas → sin escritura).
        El resto de la biblioteca (borradores, propuestos, retiradas) pasa
        intacta: el pipeline jamás modifica nada que no haya lockeado una
        persona.
        """
        if state is None:
            return
        de_corrida = state.get("anclas") or []
        if not de_corrida:
            return
        persistidas = self._anchor_store.load(self._project.project_id)
        por_id = {ancla.ancla_id: ancla for ancla in de_corrida}
        fusion: List[RecursoAncla] = []
        cambio = False
        for ancla in persistidas:
            actualizada = por_id.get(ancla.ancla_id)
            if actualizada is None:
                fusion.append(ancla)
                continue
            if (actualizada.chapter_first_seen, actualizada.chapter_last_seen) != (
                ancla.chapter_first_seen,
                ancla.chapter_last_seen,
            ):
                cambio = True
                fusion.append(actualizada)
            else:
                fusion.append(ancla)
        if cambio:
            self._anchor_store.save(self._project.project_id, fusion)

    # ---------------- Casting asistido (spec-recursos-ancla §8.2) ----------------

    def save_casting(self, state: Optional[PipelineState]) -> None:
        """Propuestas de ancla para personajes recurrentes sin ancla (§8.2).

        Consolidación de fin de corrida (junto a ``save_lore``/``save_anclas``):
        los términos de lore ``personaje`` sin ``ancla_id`` y recurrentes
        (≥2 episodios, ver ``proponer_casting``) nacen como anclas
        ``propuesto`` fusionadas con la biblioteca persistida SIN pisar nada
        existente (borradores/propuestas quedan tal cual). Con la capa de
        media activa se intenta además un hero portrait (``origen='generada'``
        con su manifest) guardado en la batería de la propuesta; si la
        generación falla la propuesta queda sin batería y la corrida sigue:
        el media nunca tumba.
        """
        if state is None or not self._project.anclas:
            return
        entradas = state.get("lore_entries", [])
        if not entradas:
            return
        plan = state.get("series_plan")
        biblioteca = self._anchor_store.load(self._project.project_id)
        propuestas = proponer_casting(
            entradas, list(plan.chapters) if plan else [], biblioteca
        )
        if not propuestas:
            return
        fusionadas: List[RecursoAncla] = []
        for propuesta in propuestas:
            retrato = self._retrato_hero_portrait(propuesta)
            if retrato is not None:
                propuesta = RecursoAncla.model_validate({
                    **propuesta.model_dump(mode="json"),
                    "bateria": [retrato.model_dump(mode="json")],
                })
            fusionadas.append(propuesta)
            self._audit.log_event(
                f"Casting asistido: propuesta de ancla '{propuesta.ancla_id}' "
                f"(personaje recurrente del lore, estado 'propuesto'"
                + (" con hero portrait generado)." if retrato is not None else ").")
            )
        self._anchor_store.save(
            self._project.project_id, [*biblioteca, *fusionadas]
        )

    def _retrato_hero_portrait(self, propuesta: RecursoAncla) -> Optional[ImagenAncla]:
        """Hero portrait de una propuesta vía el puerto de media inyectado.

        Pedido mínimo (prompt = descriptor canónico, sin anclas, sin capítulo
        real); el archivo va directo a la carpeta de batería del ancla con la
        convención ``<rol>_<n>.<ext>`` del upload. Cualquier fallo devuelve
        ``None`` (propuesta sin batería): el media nunca tumba la corrida.
        """
        media = self._media
        if media is None or not self._project.media.keyframes:
            return None
        pedido = PedidoKeyframe(
            scene_number=1,
            chapter_id="casting",
            prompt_final=propuesta.descripcion_canonica,
        )
        try:
            crudo = media.puerto.generar_keyframe(pedido, [])
            retrato = ImagenAncla(
                rol="hero_portrait",
                archivo=f"hero_portrait_1.{crudo.formato}",
                origen="generada",
                manifest=crudo.manifest,
            )
            self._anchor_store.guardar_imagen(
                self._project.project_id,
                propuesta.ancla_id,
                retrato.archivo,
                crudo.datos,
            )
            return retrato
        except Exception as exc:  # noqa: BLE001 - §8: el media nunca tumba
            logger.warning(
                "Casting asistido: la propuesta '%s' queda sin hero portrait "
                "(%s: %s).",
                propuesta.ancla_id, type(exc).__name__, exc,
            )
            return None

    def execute(self, request: SeriesRequest) -> SeriesDeliverable:
        """Ejecuta la serie completa, persiste lore, vigencia de anclas y
        propuestas de casting, y devuelve el entregable."""
        estado_final: Optional[PipelineState] = None
        for estado_final in self.stream(request):
            pass
        self.save_lore(estado_final)
        self.save_anclas(estado_final)
        self.save_casting(estado_final)
        return build_deliverable(estado_final)

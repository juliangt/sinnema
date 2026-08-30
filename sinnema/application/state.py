"""Grafo de estado global del pipeline (LangGraph).

El estado vive en un único ``TypedDict`` organizado en capas. Las listas
acumulativas (lore, episodios, fallos) usan el reducer ``operator.add`` para
garantizar que las actualizaciones parciales de los nodos se fusionen de
forma append-only sin perder historia.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict

from sinnema.domain.models import (
    AdaptedScript,
    ApprovedEpisode,
    ContinuityDirectives,
    FailedChapterRecord,
    LoreEntry,
    QualityAudit,
    ScriptDraft,
    SeriesPlan,
    TechnicalPackage,
)


def fusionar_por_clave(
    actuales: Optional[Dict[str, Any]], nuevos: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Reducer de la pizarra: fusión por clave (no append).

    Cada agente escribe su clave y la última gana; un valor ``None`` elimina
    la clave (los nodos de cierre la usan para vaciar la pizarra al terminar
    un capítulo, cosa que un dict vacío no logra con una fusión por clave).
    """
    fusion = dict(actuales or {})
    for clave, valor in (nuevos or {}).items():
        if valor is None:
            fusion.pop(clave, None)
        else:
            fusion[clave] = valor
    return fusion


class PipelineState(TypedDict, total=False):
    """Estado completo del grafo. Todas las claves son opcionales porque los
    nodos devuelven actualizaciones parciales que LangGraph fusiona."""

    # ------------------------------------------------------------------
    # a) INPUT STATE: parámetros de la corrida + proyección del proyecto
    # ------------------------------------------------------------------
    project_id: str
    language: str
    tone_of_voice: str
    topic: str
    audience: str
    cultural_context: str
    style_guide: str
    constraints: str
    num_chapters: int
    max_critique_attempts: int
    #: Último hito del pipeline que alcanza esta corrida (``[flujo].hasta``);
    #: el consolidador lo estampa en el entregable.
    alcance: str

    # ------------------------------------------------------------------
    # b) MACRO PLAN STATE: estructura global aprobada por el planificador
    # ------------------------------------------------------------------
    series_plan: Optional[SeriesPlan]

    # ------------------------------------------------------------------
    # c) CONTINUITY / LORE MEMORY: memoria acumulativa de la serie
    #    (reducer append-only: los nodos nunca sobrescriben el lore)
    # ------------------------------------------------------------------
    lore_entries: Annotated[List[LoreEntry], operator.add]

    # ------------------------------------------------------------------
    # d) ITERATION & RUNTIME STATE: punteros, reintentos y borradores
    # ------------------------------------------------------------------
    current_chapter_index: int
    critique_attempts: int
    continuity_directives: Optional[ContinuityDirectives]
    draft_script: Optional[ScriptDraft]
    adapted_script: Optional[AdaptedScript]
    pending_feedback: Optional[str]
    qa_verdict: Optional[QualityAudit]
    technical_package: Optional[TechnicalPackage]
    #: Pizarra genérica del capítulo: adjuntos de enriquecedores y notas de
    #: agentes sin slot canónico. ``commit_episode`` los embute en el episodio
    #: (``adjuntos``) y la vacía para el capítulo siguiente.
    artefactos: Annotated[Dict[str, Any], fusionar_por_clave]

    # ------------------------------------------------------------------
    # e) OUTPUT ARTIFACTS: entidades terminadas y aprobadas
    # ------------------------------------------------------------------
    completed_episodes: Annotated[List[ApprovedEpisode], operator.add]
    failed_chapters: Annotated[List[FailedChapterRecord], operator.add]

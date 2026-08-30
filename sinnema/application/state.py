"""Grafo de estado global del pipeline (LangGraph).

El estado vive en un único ``TypedDict`` organizado en capas. Las listas
acumulativas (lore, episodios, fallos) usan el reducer ``operator.add`` para
garantizar que las actualizaciones parciales de los nodos se fusionen de
forma append-only sin perder historia.
"""
from __future__ import annotations

import operator
from typing import Annotated, List, Optional, TypedDict

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

    # ------------------------------------------------------------------
    # e) OUTPUT ARTIFACTS: entidades terminadas y aprobadas
    # ------------------------------------------------------------------
    completed_episodes: Annotated[List[ApprovedEpisode], operator.add]
    failed_chapters: Annotated[List[FailedChapterRecord], operator.add]

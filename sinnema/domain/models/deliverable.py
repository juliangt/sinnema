"""Contrato final de salida: episodios aprobados y entregable de la serie."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from sinnema.domain.constants import (
    SCENE_DURATION_UNIVERSAL_MAX_SECONDS,
    SCENE_DURATION_UNIVERSAL_MIN_SECONDS,
    SCENES_UNIVERSAL_MAX_COUNT,
    SCENES_UNIVERSAL_MIN_COUNT,
    TOTAL_DURATION_UNIVERSAL_MAX_SECONDS,
    TOTAL_DURATION_UNIVERSAL_MIN_SECONDS,
)
from sinnema.domain.models.audit import QualityAudit
from sinnema.domain.models.content import Transition
from sinnema.domain.models.continuity import LoreEntry
from sinnema.domain.models.technical import TechnicalPackage

#: Tolerancia al comparar el promedio declarado con el recalculado (redondeo a 2 decimales).
_AVERAGE_TOLERANCE = 0.011


class FinalScene(BaseModel):
    """Escena consolidada: guion final adaptado + especificación técnica."""

    scene_number: int
    duration_seconds: float = Field(
        ...,
        ge=SCENE_DURATION_UNIVERSAL_MIN_SECONDS,
        le=SCENE_DURATION_UNIVERSAL_MAX_SECONDS,
    )
    visual_action: str
    narration: str = Field(..., description="Narración final (adaptada al público).")
    on_screen_text: Optional[str] = None
    transition: Transition
    image_prompt: str = Field(
        default="", description="Vacío = escena sin spec visual (director técnico desactivado)."
    )
    negative_prompt: str = Field(
        default="", description="Vacío = escena sin spec visual (director técnico desactivado)."
    )
    motion_direction: str = Field(
        default="", description="Vacío = escena sin spec visual (director técnico desactivado)."
    )


class ApprovedEpisode(BaseModel):
    """Episodio terminado y aprobado, listo para producción/render."""

    chapter_id: str
    order_index: int = Field(..., ge=1, description="Posición del episodio en la serie (1-based).")
    title: str
    hook: str
    scenes: List[FinalScene] = Field(
        ...,
        min_length=SCENES_UNIVERSAL_MIN_COUNT,
        max_length=SCENES_UNIVERSAL_MAX_COUNT,
    )
    call_to_action: str
    technical: Optional[TechnicalPackage] = Field(
        default=None,
        description="None = proyecto sin director técnico (episodio sin specs visuales).",
    )
    audit: Optional[QualityAudit] = Field(
        default=None,
        description="None = proyecto sin auditor QA (episodio sin dictamen).",
    )
    forced_acceptance: bool = Field(
        default=False,
        description="True si se aceptó tras agotar los reintentos de QA (best-effort).",
    )

    @model_validator(mode="after")
    def _escenas_y_duracion_coherentes(self) -> "ApprovedEpisode":
        numeros = sorted(s.scene_number for s in self.scenes)
        esperados = list(range(1, len(self.scenes) + 1))
        if numeros != esperados:
            raise ValueError(
                f"Los scene_number del episodio deben ser secuenciales desde 1 "
                f"(recibidos: {numeros})."
            )
        duracion = sum(s.duration_seconds for s in self.scenes)
        if not (
            TOTAL_DURATION_UNIVERSAL_MIN_SECONDS
            <= duracion
            <= TOTAL_DURATION_UNIVERSAL_MAX_SECONDS
        ):
            raise ValueError(
                f"La duración total del episodio debe quedar entre "
                f"{TOTAL_DURATION_UNIVERSAL_MIN_SECONDS:.0f} y "
                f"{TOTAL_DURATION_UNIVERSAL_MAX_SECONDS:.0f} s (recibida: {duracion:.1f} s)."
            )
        return self


class FailedChapterRecord(BaseModel):
    """Registro de capítulo descartado por política de reintentos agotados."""

    chapter_id: str
    title: str
    reason: str = Field(..., min_length=10)
    last_feedback: str = ""


class SeriesDeliverable(BaseModel):
    """Contrato final de salida para APIs, motores de render o persistencia."""

    schema_version: Literal["1.0"] = "1.0"
    project_id: str = Field(
        ...,
        min_length=1,
        description="Proyecto (show) para el que se generó la serie.",
    )
    language: str = Field(..., min_length=3, description="Idioma de la serie.")
    series_title: str
    topic: str
    audience: str
    style_guide: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_chapters_planned: int = Field(..., ge=0)
    episodes: List[ApprovedEpisode] = Field(default_factory=list)
    failed_chapters: List[FailedChapterRecord] = Field(default_factory=list)
    average_quality_score: float = Field(default=0.0, ge=0.0, le=10.0)
    lore_glossary: List[LoreEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistencia_de_serie(self) -> "SeriesDeliverable":
        # 1) Los episodios aprobados ocupan posiciones 1..N sin huecos ni repeticiones.
        indices = sorted(e.order_index for e in self.episodes)
        esperados = list(range(1, len(self.episodes) + 1))
        if indices != esperados:
            raise ValueError(
                f"order_index de los episodios debe ser secuencial desde 1 (recibidos: {indices})."
            )

        # 2) Ningún capítulo puede figurar como aprobado y descartado a la vez,
        #    y el total nunca supera lo planificado.
        ids_episodios = {e.chapter_id for e in self.episodes}
        ids_fallidos = {f.chapter_id for f in self.failed_chapters}
        solapados = sorted(ids_episodios & ids_fallidos)
        if solapados:
            raise ValueError(
                f"Capítulos aprobados y descartados a la vez: {solapados}."
            )
        total_reportados = len(self.episodes) + len(self.failed_chapters)
        if total_reportados > self.total_chapters_planned:
            raise ValueError(
                f"La serie reporta {total_reportados} capítulos (episodios + fallos) "
                f"pero solo se planificaron {self.total_chapters_planned}."
            )

        # 3) El promedio declarado debe coincidir con el recalculado. Solo
        #    participan los episodios con auditoría: los proyectos sin crítico
        #    no reportan score (0.0), nunca un score inventado.
        con_auditoria = [e.audit.overall_score for e in self.episodes if e.audit]
        if con_auditoria:
            esperado = round(sum(con_auditoria) / len(con_auditoria), 2)
        else:
            esperado = 0.0
        if abs(self.average_quality_score - esperado) > _AVERAGE_TOLERANCE:
            raise ValueError(
                f"average_quality_score ({self.average_quality_score}) no coincide con "
                f"el promedio recalculado de los episodios ({esperado})."
            )
        return self

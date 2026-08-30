"""Auditoría de calidad: hallazgos y dictamen del Chief Editor."""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, model_validator

AuditCriterion = Literal[
    "ritmo",
    "presupuesto",
    "adherencia_audiencia",
    "continuidad",
    "claridad_didactica",
    "cierre",
]


class AuditFinding(BaseModel):
    """Hallazgo puntual del auditor sobre una dimensión de calidad."""

    criterion: AuditCriterion
    severity: Literal["bloqueante", "mayor", "menor"]
    score: int = Field(..., ge=0, le=10)
    observation: str = Field(..., min_length=10)
    suggested_fix: str = Field(..., min_length=10)


class QualityAudit(BaseModel):
    """Dictamen de QA del Chief Editor."""

    approved: bool = Field(..., description="Veredicto booleano final.")
    overall_score: int = Field(..., ge=0, le=10)
    word_count_status: Literal["dentro_de_rango", "demasiado_corto", "demasiado_largo"]
    pacing_verdict: str = Field(..., min_length=10, description="Veredicto de ritmo/pacing.")
    audience_fit_verdict: str = Field(..., min_length=10, description="Veredicto de adherencia al público.")
    continuity_violations: List[str] = Field(
        default_factory=list,
        max_length=15,
        description="Conceptos re-explicados o contradicciones con el lore (vacía si no hay).",
    )
    findings: List[AuditFinding] = Field(default_factory=list, max_length=12)
    correction_feedback: str = Field(
        ...,
        min_length=10,
        description="Si se rechaza: correcciones numeradas y accionables. Si se aprueba: resumen breve.",
    )

    @model_validator(mode="after")
    def _coherencia_de_veredicto(self) -> "QualityAudit":
        tiene_bloqueante = any(f.severity == "bloqueante" for f in self.findings)
        if self.approved:
            if tiene_bloqueante:
                raise ValueError("Un dictamen aprobado no puede contener hallazgos bloqueantes.")
            # El score mínimo de aprobación lo fija el perfil de cada proyecto:
            # lo hace cumplir ``validate_audit_verdict`` tras la generación.
            if self.word_count_status != "dentro_de_rango":
                raise ValueError("Un dictamen aprobado exige word_count_status = dentro_de_rango.")
        else:
            # Un rechazo sin motivos documentados no es accionable para el guionista.
            if not self.findings and not self.continuity_violations:
                raise ValueError(
                    "Un dictamen rechazado debe incluir al menos un hallazgo o una "
                    "violación de continuidad que lo justifique."
                )
        return self

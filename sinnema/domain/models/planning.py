"""Planificación macro: el plan de serie y el desglose de capítulos."""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from sinnema.domain.constants import (
    CONCEPT_MAX_WORDS,
    NARRATION_UNIVERSAL_MAX_WORDS,
    NARRATION_UNIVERSAL_MIN_WORDS,
    SERIES_MAX_CHAPTERS,
)

_DIFICULTAD_ORDEN = {"inicial": 0, "intermedio": 1, "avanzado": 2}


class ChapterOutline(BaseModel):
    """Desglose de un capítulo dentro del plan maestro de la serie."""

    chapter_id: str = Field(
        ...,
        min_length=3,
        max_length=12,
        description="Identificador estable y único del capítulo, formato 'ch-01', 'ch-02', ...",
    )
    title: str = Field(
        ...,
        min_length=3,
        max_length=90,
        description="Título con gancho, ~60 caracteres, sin clickbait vacío.",
    )
    learning_objective: str = Field(
        ...,
        min_length=15,
        max_length=400,
        description="Qué debe entender el espectador al terminar el capítulo.",
    )
    key_concepts: List[str] = Field(
        ...,
        min_length=2,
        max_length=6,
        description="Conceptos clave (2-6). Alimentan el glosario/lore de la serie.",
    )
    prerequisites: List[str] = Field(
        default_factory=list,
        max_length=6,
        description="Conceptos de capítulos anteriores que este capítulo asume.",
    )
    difficulty: Literal["inicial", "intermedio", "avanzado"] = Field(
        default="inicial",
        description="Dificultad didáctica; la serie avanza de 'inicial' a 'avanzado'.",
    )
    word_budget: int = Field(
        default=140,
        ge=NARRATION_UNIVERSAL_MIN_WORDS,
        le=NARRATION_UNIVERSAL_MAX_WORDS,
        description="Presupuesto de palabras narradas del capítulo (debe caer en el rango objetivo del proyecto).",
    )

    @field_validator("chapter_id")
    @classmethod
    def _normalizar_id(cls, valor: str) -> str:
        limpio = valor.strip().lower().replace(" ", "")
        if not limpio:
            raise ValueError("chapter_id no puede quedar vacío tras la normalización.")
        return limpio

    @field_validator("key_concepts")
    @classmethod
    def _conceptos_limpios(cls, valor: List[str]) -> List[str]:
        limpios = [c.strip() for c in valor if c and c.strip()]
        if len(limpios) < 2:
            raise ValueError("Se requieren al menos 2 conceptos clave no vacíos.")
        demasiado_largos = [
            c for c in limpios if len(c.split()) > CONCEPT_MAX_WORDS
        ]
        if demasiado_largos:
            raise ValueError(
                f"Cada concepto clave debe tener como máximo {CONCEPT_MAX_WORDS} "
                f"palabras (demasiado largos: {demasiado_largos})."
            )
        return limpios


class SeriesPlan(BaseModel):
    """Plan macro de la serie: estructura global aprobada por el planificador."""

    series_title: str = Field(..., min_length=3, max_length=120)
    series_promise: str = Field(
        ...,
        min_length=10,
        description="Propuesta de valor de la serie en una frase.",
    )
    audience_summary: str = Field(
        ...,
        min_length=5,
        description="Síntesis del público objetivo tal como lo entendió el planificador.",
    )
    narrative_arc: str = Field(
        ...,
        min_length=10,
        description="Arco narrativo/didáctico que conecta los capítulos.",
    )
    chapters: List[ChapterOutline] = Field(
        ...,
        min_length=1,
        max_length=SERIES_MAX_CHAPTERS,
        description="Capítulos ordenados por curva de aprendizaje progresiva.",
    )
    recurring_elements: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="Elementos de identidad serial: mascota, apertura fija, eslogan de cierre.",
    )

    @model_validator(mode="after")
    def _coherencia_del_plan(self) -> "SeriesPlan":
        ids = [c.chapter_id for c in self.chapters]
        if len(ids) != len(set(ids)):
            duplicados = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"chapter_id duplicados en el plan: {duplicados}")

        # La curva de aprendizaje nunca retrocede: inicial -> intermedio -> avanzado.
        niveles = [_DIFICULTAD_ORDEN[c.difficulty] for c in self.chapters]
        if any(
            niveles[i + 1] < niveles[i] for i in range(len(niveles) - 1)
        ):
            progreso = [c.difficulty for c in self.chapters]
            raise ValueError(
                "La dificultad debe ser no decreciente a lo largo de la serie "
                f"(recibido: {progreso})."
            )

        # Un capítulo no puede asumir como prerrequisito un concepto que él
        # mismo introduce: eso delataría una planificación incoherente.
        for capitulo in self.chapters:
            propios = {c.strip().lower() for c in capitulo.key_concepts}
            solapados = [
                p for p in capitulo.prerequisites if p.strip().lower() in propios
            ]
            if solapados:
                raise ValueError(
                    f"El capítulo '{capitulo.chapter_id}' declara como prerrequisito "
                    f"un concepto que él mismo introduce: {solapados}."
                )
        return self

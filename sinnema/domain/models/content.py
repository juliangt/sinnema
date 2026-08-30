"""Contenido micro: escenas, borradores y adaptaciones de guion.

Los contratos hacen cumplir solo los límites UNIVERSALES de sanidad; el sobre
editorial concreto (escenas 6-8, palabras 100-200, etc.) es del proyecto y lo
aplica ``domain.services.format`` tras cada generación.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from sinnema.domain.constants import (
    NARRATION_UNIVERSAL_MAX_WORDS,
    NARRATION_UNIVERSAL_MAX_WORDS_PER_SCENE,
    NARRATION_UNIVERSAL_MIN_WORDS,
    ON_SCREEN_TEXT_UNIVERSAL_MAX_WORDS,
    SCENE_DURATION_UNIVERSAL_MAX_SECONDS,
    SCENE_DURATION_UNIVERSAL_MIN_SECONDS,
    SCENE_NUMBER_MAX,
    SCENE_NUMBER_MIN,
    SCENES_UNIVERSAL_MAX_COUNT,
    SCENES_UNIVERSAL_MIN_COUNT,
    TOTAL_DURATION_UNIVERSAL_MAX_SECONDS,
    TOTAL_DURATION_UNIVERSAL_MIN_SECONDS,
)

Transition = Literal[
    "corte_seco", "fundido", "zoom_in", "zoom_out", "deslizamiento", "whip_pan"
]


def _validar_texto_en_pantalla(valor: Optional[str]) -> Optional[str]:
    if valor is None:
        return valor
    limpio = " ".join(valor.split())
    if not limpio:
        return None
    if len(limpio.split()) > ON_SCREEN_TEXT_UNIVERSAL_MAX_WORDS:
        raise ValueError(
            f"on_screen_text admite como máximo {ON_SCREEN_TEXT_UNIVERSAL_MAX_WORDS} "
            f"palabras (recibido: '{limpio}')."
        )
    return limpio


def _numeros_secuenciales(numeros_ordenados: List[int], etiqueta: str) -> None:
    esperados = list(range(1, len(numeros_ordenados) + 1))
    if numeros_ordenados != esperados:
        raise ValueError(
            f"Los scene_number de {etiqueta} deben ser secuenciales desde 1 "
            f"(recibidos: {numeros_ordenados})."
        )


class Scene(BaseModel):
    """Escena atómica del guion de un capítulo."""

    scene_number: int = Field(..., ge=SCENE_NUMBER_MIN, le=SCENE_NUMBER_MAX)
    duration_seconds: float = Field(
        ...,
        ge=SCENE_DURATION_UNIVERSAL_MIN_SECONDS,
        le=SCENE_DURATION_UNIVERSAL_MAX_SECONDS,
    )
    visual_action: str = Field(
        ...,
        min_length=15,
        description="Qué se ve en pantalla (acción visual concreta).",
    )
    narration: str = Field(..., min_length=5, description="Texto narrado de la escena.")
    on_screen_text: Optional[str] = Field(
        default=None,
        max_length=60,
        description="Texto en pantalla (el proyecto limita las palabras).",
    )
    transition: Transition = "corte_seco"

    @field_validator("narration")
    @classmethod
    def _narracion_breve(cls, valor: str) -> str:
        if len(valor.split()) > NARRATION_UNIVERSAL_MAX_WORDS_PER_SCENE:
            raise ValueError(
                f"La narración de una escena admite como máximo "
                f"{NARRATION_UNIVERSAL_MAX_WORDS_PER_SCENE} palabras "
                f"(recibidas: {len(valor.split())})."
            )
        return valor

    @field_validator("on_screen_text")
    @classmethod
    def _texto_en_pantalla(cls, valor: Optional[str]) -> Optional[str]:
        return _validar_texto_en_pantalla(valor)


class ScriptDraft(BaseModel):
    """Borrador completo del guion de un capítulo, con métricas verificadas."""

    chapter_id: str = Field(..., min_length=3, max_length=12)
    title: str = Field(..., min_length=3, max_length=90)
    hook: str = Field(..., min_length=5, description="Primeras palabras narradas (escena 1, 0-5 s).")
    scenes: List[Scene] = Field(
        ...,
        min_length=SCENES_UNIVERSAL_MIN_COUNT,
        max_length=SCENES_UNIVERSAL_MAX_COUNT,
    )
    call_to_action: str = Field(..., min_length=5)
    total_duration_seconds: float = Field(
        default=0.0,
        description="Recalculado automáticamente: suma de duraciones de escena.",
    )
    word_count: int = Field(
        default=0,
        description="Recalculado automáticamente: hook + narraciones + CTA.",
    )

    @field_validator("chapter_id")
    @classmethod
    def _normalizar_id(cls, valor: str) -> str:
        limpio = valor.strip().lower().replace(" ", "")
        if not limpio:
            raise ValueError("chapter_id no puede quedar vacío tras la normalización.")
        return limpio

    @model_validator(mode="after")
    def _verificar_metricas(self) -> "ScriptDraft":
        _numeros_secuenciales(
            sorted(s.scene_number for s in self.scenes), "las escenas del borrador"
        )

        texto_total = " ".join(
            [self.hook] + [s.narration for s in self.scenes] + [self.call_to_action]
        )
        palabras = len(texto_total.split())
        # Solo el límite universal de sanidad; el rango editorial del proyecto
        # lo aplica ``validate_draft_format`` tras la generación.
        if not (NARRATION_UNIVERSAL_MIN_WORDS <= palabras <= NARRATION_UNIVERSAL_MAX_WORDS):
            raise ValueError(
                f"Palabras narradas fuera de los límites universales "
                f"({NARRATION_UNIVERSAL_MIN_WORDS}-{NARRATION_UNIVERSAL_MAX_WORDS}): {palabras}."
            )

        duracion_total = sum(s.duration_seconds for s in self.scenes)
        if not (
            TOTAL_DURATION_UNIVERSAL_MIN_SECONDS
            <= duracion_total
            <= TOTAL_DURATION_UNIVERSAL_MAX_SECONDS
        ):
            raise ValueError(
                f"Duración total fuera de los límites universales "
                f"({TOTAL_DURATION_UNIVERSAL_MIN_SECONDS:.0f}-"
                f"{TOTAL_DURATION_UNIVERSAL_MAX_SECONDS:.0f} s): {duracion_total:.1f} s."
            )

        self.word_count = palabras
        self.total_duration_seconds = round(duracion_total, 2)
        return self


class AdaptedScene(BaseModel):
    """Escena re-escrita por el adaptador de audiencia (numeración original)."""

    scene_number: int = Field(..., ge=SCENE_NUMBER_MIN, le=SCENE_NUMBER_MAX)
    narration: str = Field(..., min_length=5)
    on_screen_text: Optional[str] = Field(default=None, max_length=60)

    @field_validator("narration")
    @classmethod
    def _narracion_breve(cls, valor: str) -> str:
        if len(valor.split()) > NARRATION_UNIVERSAL_MAX_WORDS_PER_SCENE:
            raise ValueError(
                f"La narración adaptada de una escena admite como máximo "
                f"{NARRATION_UNIVERSAL_MAX_WORDS_PER_SCENE} palabras "
                f"(recibidas: {len(valor.split())})."
            )
        return valor

    @field_validator("on_screen_text")
    @classmethod
    def _texto_en_pantalla(cls, valor: Optional[str]) -> Optional[str]:
        return _validar_texto_en_pantalla(valor)


class AdaptedScript(BaseModel):
    """Guión final adaptado al registro y cultura del público objetivo."""

    chapter_id: str = Field(..., min_length=3, max_length=12)
    adapted_title: str = Field(..., min_length=3, max_length=90)
    adapted_hook: str = Field(..., min_length=5)
    adapted_scenes: List[AdaptedScene] = Field(
        ...,
        min_length=SCENES_UNIVERSAL_MIN_COUNT,
        max_length=SCENES_UNIVERSAL_MAX_COUNT,
    )
    adapted_cta: str = Field(..., min_length=5)
    register_notes: List[str] = Field(
        default_factory=list,
        max_length=8,
        description="Decisiones de registro (modismos usados y por qué).",
    )
    cultural_references: List[str] = Field(
        default_factory=list,
        max_length=8,
        description="Referencias culturales insertadas.",
    )

    @field_validator("chapter_id")
    @classmethod
    def _normalizar_id(cls, valor: str) -> str:
        limpio = valor.strip().lower().replace(" ", "")
        if not limpio:
            raise ValueError("chapter_id no puede quedar vacío tras la normalización.")
        return limpio

    @model_validator(mode="after")
    def _verificar_adaptacion(self) -> "AdaptedScript":
        _numeros_secuenciales(
            sorted(s.scene_number for s in self.adapted_scenes),
            "las escenas adaptadas",
        )
        texto_total = " ".join(
            [self.adapted_hook]
            + [s.narration for s in self.adapted_scenes]
            + [self.adapted_cta]
        )
        palabras = len(texto_total.split())
        if not (
            NARRATION_UNIVERSAL_MIN_WORDS <= palabras <= NARRATION_UNIVERSAL_MAX_WORDS
        ):
            raise ValueError(
                f"Palabras adaptadas fuera de los límites universales "
                f"({NARRATION_UNIVERSAL_MIN_WORDS}-{NARRATION_UNIVERSAL_MAX_WORDS}): {palabras}."
            )
        return self

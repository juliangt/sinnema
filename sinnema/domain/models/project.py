"""Perfil de formato: el sobre editorial numérico de un proyecto (show).

Cooperan tres niveles de límites:
1. Universales (``domain.constants``): pisos/techos de sanidad, aplicados por
   los contratos Pydantic de los artefactos.
2. Editoriales (este perfil): rangos que el pipeline HACE CUMPLIR tras cada
   generación mediante ``domain.services.format``.
3. Objetivo (campos ``*_target_*``): instruyen los prompts y los audita el
   crítico; no invalidan por sí solos.
"""
from __future__ import annotations

from typing import List, Literal, Tuple

from pydantic import BaseModel, Field, model_validator

from sinnema.domain.constants import (
    NARRATION_UNIVERSAL_MAX_WORDS,
    NARRATION_UNIVERSAL_MAX_WORDS_PER_SCENE,
    NARRATION_UNIVERSAL_MIN_WORDS,
    ON_SCREEN_TEXT_UNIVERSAL_MAX_WORDS,
    QA_SCORE_UNIVERSAL_MAX,
    QA_SCORE_UNIVERSAL_MIN,
    SCENE_DURATION_UNIVERSAL_MAX_SECONDS,
    SCENE_DURATION_UNIVERSAL_MIN_SECONDS,
    SCENES_UNIVERSAL_MAX_COUNT,
    SCENES_UNIVERSAL_MIN_COUNT,
    TOTAL_DURATION_UNIVERSAL_MAX_SECONDS,
    TOTAL_DURATION_UNIVERSAL_MIN_SECONDS,
)

AspectRatio = Literal["9:16", "1:1", "16:9"]


def _check_rango(
    problemas: List[str],
    par: Tuple[float, float],
    etiqueta: str,
    minimo_universal: float,
    maximo_universal: float,
) -> None:
    """Exige piso <= techo y que ambos queden dentro del rango universal."""
    piso, techo = par
    if piso > techo:
        problemas.append(f"{etiqueta}: el mínimo ({piso}) supera el máximo ({techo})")
        return
    if piso < minimo_universal or techo > maximo_universal:
        problemas.append(
            f"{etiqueta}: [{piso}, {techo}] fuera de los límites universales "
            f"[{minimo_universal}, {maximo_universal}]"
        )


class FormatProfile(BaseModel):
    """Límites editoriales que cada proyecto configura; defaults = show de 60 s."""

    aspect_ratio: AspectRatio = Field(
        default="9:16",
        description="Relación de aspecto de los videos del proyecto.",
    )
    narration_target_words: Tuple[int, int] = Field(
        default=(130, 150),
        description="Rango objetivo de palabras narradas: instruye prompts y audita el crítico.",
    )
    narration_hard_words: Tuple[int, int] = Field(
        default=(100, 200),
        description="Rango duro de palabras narradas: el pipeline rechaza fuera de él.",
    )
    scenes_count: Tuple[int, int] = Field(
        default=(6, 8),
        description="Cantidad de escenas exigida por capítulo.",
    )
    scene_duration_seconds: Tuple[float, float] = Field(
        default=(2.0, 15.0),
        description="Duración mínima y máxima por escena, en segundos.",
    )
    total_duration_target_seconds: Tuple[float, float] = Field(
        default=(55.0, 65.0),
        description="Duración total objetivo: instruye prompts y audita el crítico.",
    )
    total_duration_hard_seconds: Tuple[float, float] = Field(
        default=(45.0, 75.0),
        description="Duración total dura: el pipeline rechaza fuera de ella.",
    )
    narration_max_words_per_scene: int = Field(
        default=45,
        description="Techo de palabras narradas por escena.",
    )
    on_screen_text_max_words: int = Field(
        default=6,
        description="Techo de palabras del texto en pantalla.",
    )
    min_approval_score: int = Field(
        default=7,
        description="Score mínimo de QA para aprobar un capítulo.",
    )

    @model_validator(mode="after")
    def _coherencia_del_perfil(self) -> "FormatProfile":
        problemas: List[str] = []

        _check_rango(
            problemas, self.scenes_count, "scenes_count",
            SCENES_UNIVERSAL_MIN_COUNT, SCENES_UNIVERSAL_MAX_COUNT,
        )
        _check_rango(
            problemas, self.narration_target_words, "narration_target_words",
            NARRATION_UNIVERSAL_MIN_WORDS, NARRATION_UNIVERSAL_MAX_WORDS,
        )
        _check_rango(
            problemas, self.narration_hard_words, "narration_hard_words",
            NARRATION_UNIVERSAL_MIN_WORDS, NARRATION_UNIVERSAL_MAX_WORDS,
        )
        _check_rango(
            problemas, self.scene_duration_seconds, "scene_duration_seconds",
            SCENE_DURATION_UNIVERSAL_MIN_SECONDS, SCENE_DURATION_UNIVERSAL_MAX_SECONDS,
        )
        _check_rango(
            problemas, self.total_duration_target_seconds, "total_duration_target_seconds",
            TOTAL_DURATION_UNIVERSAL_MIN_SECONDS, TOTAL_DURATION_UNIVERSAL_MAX_SECONDS,
        )
        _check_rango(
            problemas, self.total_duration_hard_seconds, "total_duration_hard_seconds",
            TOTAL_DURATION_UNIVERSAL_MIN_SECONDS, TOTAL_DURATION_UNIVERSAL_MAX_SECONDS,
        )

        # El rango duro debe envolver al objetivo: si no, el objetivo pediría
        # algo que el propio perfil rechazaría.
        if (
            self.narration_hard_words[0] > self.narration_target_words[0]
            or self.narration_target_words[1] > self.narration_hard_words[1]
        ):
            problemas.append(
                "narration_hard_words debe envolver a narration_target_words "
                f"(duro {self.narration_hard_words} vs objetivo {self.narration_target_words})"
            )
        if (
            self.total_duration_hard_seconds[0] > self.total_duration_target_seconds[0]
            or self.total_duration_target_seconds[1] > self.total_duration_hard_seconds[1]
        ):
            problemas.append(
                "total_duration_hard_seconds debe envolver a total_duration_target_seconds "
                f"(dura {self.total_duration_hard_seconds} vs objetivo {self.total_duration_target_seconds})"
            )

        if not (
            1 <= self.narration_max_words_per_scene <= NARRATION_UNIVERSAL_MAX_WORDS_PER_SCENE
        ):
            problemas.append(
                f"narration_max_words_per_scene debe estar entre 1 y "
                f"{NARRATION_UNIVERSAL_MAX_WORDS_PER_SCENE} (recibido: {self.narration_max_words_per_scene})"
            )
        if not (1 <= self.on_screen_text_max_words <= ON_SCREEN_TEXT_UNIVERSAL_MAX_WORDS):
            problemas.append(
                f"on_screen_text_max_words debe estar entre 1 y "
                f"{ON_SCREEN_TEXT_UNIVERSAL_MAX_WORDS} (recibido: {self.on_screen_text_max_words})"
            )
        if not (
            QA_SCORE_UNIVERSAL_MIN <= self.min_approval_score <= QA_SCORE_UNIVERSAL_MAX
        ):
            problemas.append(
                f"min_approval_score debe estar entre {QA_SCORE_UNIVERSAL_MIN} y "
                f"{QA_SCORE_UNIVERSAL_MAX} (recibido: {self.min_approval_score})"
            )

        if problemas:
            raise ValueError(
                "Perfil de formato inválido: " + "; ".join(problemas) + "."
            )
        return self

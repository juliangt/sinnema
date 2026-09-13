"""Paquete técnico: especificaciones visuales y dirección de audio."""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from sinnema.domain.constants import (
    SCENE_NUMBER_MAX,
    SCENE_NUMBER_MIN,
    SCENES_UNIVERSAL_MAX_COUNT,
    SCENES_UNIVERSAL_MIN_COUNT,
)
from sinnema.domain.models.anclas import ReferenciaAncla
from sinnema.domain.text import contains_spanish_characters


def _rechazar_espanol(valor: str, campo: str) -> str:
    if contains_spanish_characters(valor):
        raise ValueError(
            f"El campo '{campo}' debe estar EN INGLÉS: contiene caracteres "
            "españoles (tildes, ñ o signos de apertura)."
        )
    return valor


class VisualAssetSpec(BaseModel):
    """Especificación visual por escena, con prompts en inglés."""

    scene_number: int = Field(..., ge=SCENE_NUMBER_MIN, le=SCENE_NUMBER_MAX)
    image_prompt: str = Field(
        ...,
        min_length=40,
        description="Prompt de imagen EN INGLÉS (sujeto + entorno + iluminación + composición + estilo).",
    )
    negative_prompt: str = Field(..., min_length=5, description="Negative prompt EN INGLÉS.")
    composition: str = Field(..., min_length=10, description="Encuadre/composición de cámara.")
    motion_direction: str = Field(
        ...,
        min_length=10,
        description="Dirección de cámara y movimiento para el modelo de video (EN INGLÉS).",
    )
    style_tags: List[str] = Field(..., min_length=3, max_length=10)
    #: Anclas citadas por esta escena (spec-recursos-ancla §5.3): entidades con
    #: apariencia fija presentes aquí. Default vacío = escena sin anclados
    #: (o proyecto sin biblioteca): compatible con specs y corridas previas.
    #: Los validadores de aplicación verifican existencia y lock (§11.2).
    anclas: List[ReferenciaAncla] = Field(default_factory=list)

    @field_validator("image_prompt")
    @classmethod
    def _prompt_imagen_en_ingles(cls, valor: str) -> str:
        return _rechazar_espanol(valor, "image_prompt")

    @field_validator("negative_prompt")
    @classmethod
    def _prompt_negativo_en_ingles(cls, valor: str) -> str:
        return _rechazar_espanol(valor, "negative_prompt")

    @field_validator("motion_direction")
    @classmethod
    def _motion_en_ingles(cls, valor: str) -> str:
        return _rechazar_espanol(valor, "motion_direction")

    @field_validator("style_tags")
    @classmethod
    def _tags_limpios(cls, valor: List[str]) -> List[str]:
        limpios = [t.strip() for t in valor if t and t.strip()]
        if len(limpios) < 3:
            raise ValueError("Se requieren al menos 3 style_tags no vacíos.")
        return limpios


class AudioDirection(BaseModel):
    """Dirección de voz, música y efectos por capítulo."""

    voice_style: str = Field(..., min_length=5)
    voice_direction_notes: str = Field(..., min_length=10)
    music_mood: str = Field(..., min_length=3)
    sfx_cues: List[str] = Field(default_factory=list, max_length=12)


class TechnicalPackage(BaseModel):
    """Paquete técnico de producción para un episodio aprobado."""

    chapter_id: str = Field(..., min_length=3, max_length=12)
    aspect_ratio: Literal["9:16", "1:1", "16:9"] = "9:16"
    render_style: str = Field(..., min_length=5, description="Estilo de render maestro de la serie.")
    visual_specs: List[VisualAssetSpec] = Field(
        ...,
        min_length=SCENES_UNIVERSAL_MIN_COUNT,
        max_length=SCENES_UNIVERSAL_MAX_COUNT,
    )
    audio_direction: AudioDirection
    thumbnail_prompt: str = Field(..., min_length=40, description="Prompt de miniatura EN INGLÉS.")

    @field_validator("chapter_id")
    @classmethod
    def _normalizar_id(cls, valor: str) -> str:
        limpio = valor.strip().lower().replace(" ", "")
        if not limpio:
            raise ValueError("chapter_id no puede quedar vacío tras la normalización.")
        return limpio

    @field_validator("thumbnail_prompt")
    @classmethod
    def _miniatura_en_ingles(cls, valor: str) -> str:
        return _rechazar_espanol(valor, "thumbnail_prompt")

    @model_validator(mode="after")
    def _specs_secuenciales(self) -> "TechnicalPackage":
        numeros = sorted(s.scene_number for s in self.visual_specs)
        esperados = list(range(1, len(self.visual_specs) + 1))
        if numeros != esperados:
            raise ValueError(
                f"Los scene_number de visual_specs deben ser secuenciales desde 1 "
                f"(recibidos: {numeros})."
            )
        return self

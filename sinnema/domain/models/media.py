"""Capa de media: contratos del pedido, la cruda y el adjunto por episodio.

(spec-recursos-ancla §6) La capa de media convierte specs en archivos FUERA de
los agentes LLM: un nodo estructural compone un ``PedidoKeyframe`` por escena,
lo entrega a un adaptador vía el puerto ``MediaGenerationPort`` (application)
y persiste el resultado como adjunto del episodio (``MediaDelEpisodio``),
sin tocar slots canónicos del estado.

Decisión de ubicación: los contratos de GENERACIÓN de media viven en este
módulo nuevo (``media.py``) y no en ``anclas.py`` porque son contratos
transitorios de la capa de media (pedido → cruda → adjunto), no de la
biblioteca de anclas; ``anclas.py`` queda como la fuente de verdad de la
biblioteca (entidades, baterías, manifests de sus imágenes).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from sinnema.domain.models.anclas import (
    ManifestDeGeneracion,
    ReferenciaAncla,
    _rechazar_espanol,
)


class PedidoKeyframe(BaseModel):
    """Pedido de generación del keyframe de una escena (spec-recursos-ancla §6).

    El nodo estructural lo compone desde el paquete técnico: ``prompt_final``
    es el ``image_prompt`` de la spec más los descriptores canónicos EN de las
    anclas citadas (identidad primero); ``anclas`` viaja ya en el orden en que
    el proveedor debe recibir las referencias (el resolver lo verifica).
    ``frame_inicial`` (opcional) es el último frame de la escena anterior para
    el encadenado ``encadenar_frames``: presente, el adaptador lo usa como
    imagen de entrada adicional; ``None`` = generación sin encadenado.
    """

    scene_number: int = Field(..., ge=1, description="Escena dentro del capítulo (1-based).")
    chapter_id: str = Field(..., min_length=1)
    prompt_final: str = Field(
        ...,
        min_length=10,
        description="Prompt final compuesto (image_prompt + descriptores canónicos), EN INGLÉS.",
    )
    negative_prompt: str = ""
    aspect_ratio: str = Field(default="9:16", description="Relación de aspecto del paquete (9:16, 1:1, 16:9).")
    anclas: List[ReferenciaAncla] = Field(default_factory=list)
    frame_inicial: Optional[bytes] = Field(
        default=None,
        description="Último frame de la escena anterior (encadenado §3.4); bytes de imagen.",
    )

    @field_validator("prompt_final")
    @classmethod
    def _prompt_en_ingles(cls, valor: str) -> str:
        return _rechazar_espanol(valor, "prompt_final")


class MediaCrudo(BaseModel):
    """Resultado crudo del adaptador: bytes + manifest de procedencia.

    El adaptador NO escribe archivos: devuelve bytes (imagen generada) y el
    ``ManifestDeGeneracion``; el nodo persiste con el almacén de media. Para
    keyframes fijos el propio keyframe es también el último frame (el
    proveedor no expone un ``lastFrame`` separado para imagen estática): los
    adaptadores de video futuros distinguirán ambos valores; un adaptador que
    no pueda exponerlo deja ``ultimo_frame = None`` y el nodo degrada a
    generación sin encadenado (con registro en auditoría).
    """

    datos: bytes
    formato: str = Field(default="png", description="Extensión sin punto (png, jpeg, webp).")
    manifest: ManifestDeGeneracion
    ultimo_frame: Optional[bytes] = None


class MediaGenerado(BaseModel):
    """Keyframe de una escena ya persistido, con su manifest (spec §6)."""

    archivo: str = Field(
        ...,
        min_length=1,
        description="Ruta relativa bajo la raíz de media: <project_id>/<chapter_id>/escena_<n>.<ext>.",
    )
    manifest: ManifestDeGeneracion
    #: Fase 4 (QA visual): lo llena el bucle de regeneración con el
    #: ``InformeQaVisual``; hasta entonces siempre ``None``.
    qa: Optional[Dict[str, Any]] = None


class ErrorDeMedia(BaseModel):
    """Fallo de una escena: el proveedor falló tras los reintentos de transporte.

    Semántica de fallo §6: la escena queda SIN keyframe, queda registrado aquí
    (y en auditoría) y la corrida SIGUE — el media nunca tumba episodios
    aprobados.
    """

    escena: int = Field(..., ge=1)
    proveedor: str = Field(..., min_length=1)
    error: str = Field(..., min_length=1)


class MediaDelEpisodio(BaseModel):
    """Adjunto del episodio con TODO el media del capítulo (spec §6).

    Viaja como ``ArtefactoAdjunto(rol="media")`` por el mecanismo existente de
    la pizarra: los keyframes logrados y los errores por escena conviven para
    que ni la UI ni la auditoría inventen éxito silencioso.
    """

    chapter_id: str = Field(..., min_length=1)
    keyframes: List[MediaGenerado] = Field(default_factory=list)
    errores: List[ErrorDeMedia] = Field(default_factory=list)

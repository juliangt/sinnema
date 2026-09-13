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

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from sinnema.domain.models.anclas import (
    ManifestDeGeneracion,
    ReferenciaAncla,
    _rechazar_espanol,
)

#: Métricas del QA visual (spec-recursos-ancla §7): similitud de cara con la
#: batería, escena sin cara (embeddings), adherencia prompt-imagen y dedup de
#: keyframes gemelas del capítulo.
MetricaQa = Literal["cara_coseno", "escena_dino", "clip_prompt", "phash_dedup"]


class InformeQaVisual(BaseModel):
    """Veredicto del QA visual sobre UNA comparación (spec-recursos-ancla §7).

    Un keyframe puede compararse contra varias anclas y varias métricas: cada
    comparación produce un informe. Un keyframe aprueba solo si TODOS sus
    informes aprueban. ``ancla_id`` vacío = hallazgo a nivel de capítulo (el
    dedup de escenas gemelas no corresponde a una ancla).
    """

    escena: int = Field(..., ge=1)
    ancla_id: str = Field(
        default="",
        description="Ancla comparada; vacío = hallazgo a nivel capítulo (dedup).",
    )
    metrica: MetricaQa
    score: float = Field(
        ...,
        description="Similitud medida (coseno [-1,1] o distancia de Hamming para dedup).",
    )
    umbral: float = Field(
        ...,
        description="Umbral de la métrica (mínimo exigido, o máximo para dedup).",
    )
    aprueba: bool
    detalle: str = Field(default="", description="Contexto accionable del veredicto.")


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
    peso_referencia: Optional[float] = Field(
        default=None,
        description="Peso de las referencias (escalado §7 en regeneraciones; None = pedido inicial).",
    )
    seed: Optional[int] = Field(
        default=None,
        description="Seed del intento (§7: cada regeneración lleva seed nueva; None = inicial).",
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
    #: Informes de QA del candidato ENTREGADO (spec §7). Es una lista y no un
    #: ``Optional[InformeQaVisual]`` porque una escena se compara contra varias
    #: anclas y métricas; los intentos intermedios del bucle de regeneración
    #: viajan aparte en ``MediaDelEpisodio.qa_agotado``. Vacío = QA no corrido
    #: (sin extras instalados) o escena previa a la Fase 4.
    qa: List[InformeQaVisual] = Field(default_factory=list)


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
    #: Informes de QA de TODOS los intentos de las escenas que agotaron su
    #: bucle de regeneración sin aprobar (spec §7: política honesta — el mejor
    #: candidato se entrega, pero los intentos quedan visibles).
    qa_agotado: List[InformeQaVisual] = Field(default_factory=list)

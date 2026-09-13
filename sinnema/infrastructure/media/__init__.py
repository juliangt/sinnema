"""Capa de media (spec-recursos-ancla §6): adaptadores de proveedores de
imagen, resolver de baterías, almacén de keyframes y reintentos de transporte.

Los SDKs (``google-genai``, ``openai``) viven en el extra opcional
``sinnema[media]``: este paquete se importa sin ellos (imports perezosos) y
los adaptadores fallan con error accionable al usarse si faltan.
"""
from sinnema.infrastructure.media.almacen import (
    DEFAULT_MEDIA_ROOT,
    AlmacenMedia,
)
from sinnema.infrastructure.media.fabrica import (
    INTENTOS_DEFAULT,
    PROVEEDOR_DEFAULT,
    PROVEEDORES_DE_IMAGEN,
    cargador_de_baterias,
    construir_dependencias_de_media,
    construir_puerto_de_media,
    politica_del_entorno,
    resolver_proveedor,
)
from sinnema.infrastructure.media.gemini import AdaptadorGeminiImage
from sinnema.infrastructure.media.openai import AdaptadorOpenAIImage
from sinnema.infrastructure.media.qa import (
    DISTANCIA_PHASH_GEMELA,
    UMBRAL_CARA_DEFAULT,
    UMBRAL_PROMPT_DEFAULT,
    QaVisualService,
    coseno,
    distancia_hamming,
)
from sinnema.infrastructure.media.resolver import (
    ReferenciaResuelta,
    ResolverDeBateria,
)
from sinnema.infrastructure.media.transporte import (
    PoliticaReintentos,
    con_reintentos,
)

__all__ = [
    "AdaptadorGeminiImage",
    "AdaptadorOpenAIImage",
    "AlmacenMedia",
    "DEFAULT_MEDIA_ROOT",
    "DISTANCIA_PHASH_GEMELA",
    "INTENTOS_DEFAULT",
    "PoliticaReintentos",
    "PROVEEDOR_DEFAULT",
    "PROVEEDORES_DE_IMAGEN",
    "QaVisualService",
    "ReferenciaResuelta",
    "ResolverDeBateria",
    "UMBRAL_CARA_DEFAULT",
    "UMBRAL_PROMPT_DEFAULT",
    "cargador_de_baterias",
    "coseno",
    "con_reintentos",
    "construir_dependencias_de_media",
    "construir_puerto_de_media",
    "construir_qa_visual",
    "distancia_hamming",
    "politica_del_entorno",
    "resolver_proveedor",
]

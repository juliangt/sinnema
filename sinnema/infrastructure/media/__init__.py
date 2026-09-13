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
    PROVEEDOR_DEFAULT,
    PROVEEDORES_DE_IMAGEN,
    construir_puerto_de_media,
    resolver_proveedor,
)
from sinnema.infrastructure.media.gemini import AdaptadorGeminiImage
from sinnema.infrastructure.media.openai import AdaptadorOpenAIImage
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
    "PoliticaReintentos",
    "PROVEEDOR_DEFAULT",
    "PROVEEDORES_DE_IMAGEN",
    "ReferenciaResuelta",
    "ResolverDeBateria",
    "con_reintentos",
    "construir_puerto_de_media",
    "resolver_proveedor",
]

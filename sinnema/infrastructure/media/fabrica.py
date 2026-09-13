"""Fábrica del puerto de media: elige el adaptador de imagen por nombre.

El nombre viene de ``[media].proveedor_imagen`` del TOML (``gemini`` |
``openai``) o del default del entorno (``MEDIA_PROVIDER`` → ``gemini``, el
wiring fino vive en la composición raíz). Devuelve SIEMPRE un adaptador
construido: sin claves ni SDK el objeto existe y falla con error accionable
al usarse (degradación elegante §6, como los proveedores LLM).
"""
from __future__ import annotations

from typing import Optional

from sinnema.application.ports import MediaGenerationPort
from sinnema.infrastructure.media.base import AdaptadorImagenBase
from sinnema.infrastructure.media.gemini import AdaptadorGeminiImage
from sinnema.infrastructure.media.openai import AdaptadorOpenAIImage
from sinnema.infrastructure.media.resolver import CargarImagenDeBateria
from sinnema.infrastructure.media.transporte import PoliticaReintentos

#: Proveedores de imagen soportados por la Fase 3 (catálogo de la API §9.1).
PROVEEDORES_DE_IMAGEN = ("gemini", "openai")

#: Default del entorno cuando ni el TOML ni ``MEDIA_PROVIDER`` dicen nada.
PROVEEDOR_DEFAULT = "gemini"

_ADAPTADORES = {
    AdaptadorGeminiImage.PROVEEDOR: AdaptadorGeminiImage,
    AdaptadorOpenAIImage.PROVEEDOR: AdaptadorOpenAIImage,
}


def resolver_proveedor(proveedor_toml: Optional[str], entorno: Optional[str]) -> str:
    """Precedencia del proveedor de imagen: TOML > entorno (``MEDIA_PROVIDER``)
    > default (``gemini``). Un valor desconocido es un error de configuración
    accionable (se reporta al cargar el proyecto o al armar el puerto)."""
    elegido = proveedor_toml or entorno or PROVEEDOR_DEFAULT
    elegido = (elegido or "").strip().lower()
    if elegido not in _ADAPTADORES:
        raise ValueError(
            f"proveedor_imagen debe ser uno de: {', '.join(PROVEEDORES_DE_IMAGEN)} "
            f"(recibido: '{elegido}')."
        )
    return elegido


def construir_puerto_de_media(
    proveedor: str,
    project_id: str,
    cargar_imagen: CargarImagenDeBateria,
    api_key: Optional[str] = None,
    modelo: Optional[str] = None,
    retry_policy: Optional[PoliticaReintentos] = None,
) -> MediaGenerationPort:
    """Construye el adaptador del proveedor elegido (sin validar claves: el
    adaptador degrada con error accionable al usarse)."""
    nombre = resolver_proveedor(proveedor, None)
    adaptador: AdaptadorImagenBase = _ADAPTADORES[nombre](
        project_id=project_id,
        cargar_imagen=cargar_imagen,
        api_key=api_key,
        modelo=modelo,
        retry_policy=retry_policy,
    )
    return adaptador

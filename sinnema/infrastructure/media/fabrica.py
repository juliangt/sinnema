"""Fábrica del puerto de media: elige el adaptador de imagen por nombre y
arma las dependencias completas por proyecto (wiring del Hito 3).

El nombre viene de ``[media].proveedor_imagen`` del TOML (``gemini`` |
``openai``) o del default del entorno (``MEDIA_PROVIDER`` → ``gemini``, el
mismo patrón que ``LLM_PROVIDER_<ROL>``); los reintentos de transporte se
afinan con ``MEDIA_MAX_INTENTOS``. Devuelve SIEMPRE un adaptador construido:
sin claves ni SDK el objeto existe y falla con error accionable al usarse
(degradación elegante §6, como los proveedores LLM).

``construir_dependencias_de_media`` es el punto único de wiring (CLI y
server): con ``[media].keyframes`` distinto de true devuelve ``None`` y NI
SIQUIERA se construye un adaptador — cero impacto en corridas sin media.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sinnema.application.ports import DependenciasMedia, MediaGenerationPort
from sinnema.application.projects import ProjectSpec
from sinnema.infrastructure.anclas import JsonAnchorStore
from sinnema.infrastructure.media.almacen import AlmacenMedia
from sinnema.infrastructure.media.base import AdaptadorImagenBase
from sinnema.infrastructure.media.gemini import AdaptadorGeminiImage
from sinnema.infrastructure.media.openai import AdaptadorOpenAIImage
from sinnema.infrastructure.media.resolver import (
    CargarImagenDeBateria,
)
from sinnema.infrastructure.media.transporte import PoliticaReintentos

logger = logging.getLogger("sinnema.media.fabrica")

#: Proveedores de imagen soportados por la Fase 3 (catálogo de la API §9.1).
PROVEEDORES_DE_IMAGEN = ("gemini", "openai")

#: Default del entorno cuando ni el TOML ni ``MEDIA_PROVIDER`` dicen nada.
PROVEEDOR_DEFAULT = "gemini"

#: Reintentos de transporte por defecto (``MEDIA_MAX_INTENTOS`` los ajusta).
INTENTOS_DEFAULT = 3

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


def cargador_de_baterias(anchor_store: JsonAnchorStore) -> CargarImagenDeBateria:
    """Cargador de imágenes de batería sobre el almacén de anclas (Fase 1):
    ruta validada anti-traversal y lectura de bytes en el momento del render."""
    def cargar(project_id: str, ancla_id: str, archivo: str) -> bytes:
        return anchor_store.ruta_imagen(project_id, ancla_id, archivo).read_bytes()

    return cargar


def politica_del_entorno() -> PoliticaReintentos:
    """``MEDIA_MAX_INTENTOS`` (default 3): un valor no numérico no tumba el
    arranque — se registra y rige el default (mismo espíritu que el worker)."""
    bruto = os.getenv("MEDIA_MAX_INTENTOS", "").strip()
    if not bruto:
        return PoliticaReintentos(max_retries=INTENTOS_DEFAULT)
    try:
        max_retries = int(bruto)
    except ValueError:
        logger.warning(
            "MEDIA_MAX_INTENTOS='%s' no es un entero: se usa %d.", bruto,
            INTENTOS_DEFAULT,
        )
        return PoliticaReintentos(max_retries=INTENTOS_DEFAULT)
    if max_retries < 1:
        logger.warning(
            "MEDIA_MAX_INTENTOS=%d es menor que 1: se usa %d.", max_retries,
            INTENTOS_DEFAULT,
        )
        return PoliticaReintentos(max_retries=INTENTOS_DEFAULT)
    return PoliticaReintentos(max_retries=max_retries)


def construir_dependencias_de_media(
    proyecto: ProjectSpec,
    almacen: AlmacenMedia,
    anchor_store: JsonAnchorStore,
    eventos=None,
) -> Optional[DependenciasMedia]:
    """Wiring completo de la capa de media para UN proyecto (§6/Hito 3).

    Solo si ``[media].keyframes = true``: construye el puerto del proveedor
    elegido (TOML > ``MEDIA_PROVIDER`` > gemini) con reintentos de
    ``MEDIA_MAX_INTENTOS`` y el cargador de baterías sobre ``anchor_store``.
    En cualquier otro caso devuelve ``None``: el nodo ``render_keyframes``
    ni se inserta y ningún adaptador se instancia.
    """
    if not proyecto.media.keyframes:
        return None
    proveedor = resolver_proveedor(
        proyecto.media.proveedor_imagen, os.getenv("MEDIA_PROVIDER")
    )
    puerto = construir_puerto_de_media(
        proveedor,
        proyecto.project_id,
        cargador_de_baterias(anchor_store),
        retry_policy=politica_del_entorno(),
    )
    logger.info(
        "Media activo para '%s': keyframes con proveedor '%s' (encadenado: %s).",
        proyecto.project_id, proveedor, proyecto.media.encadenar_frames,
    )
    return DependenciasMedia(
        puerto=puerto,
        almacen=almacen,
        eventos=eventos,
        proveedor=proveedor,
        qa=construir_qa_visual(anchor_store),
    )


def construir_qa_visual(anchor_store: JsonAnchorStore) -> Optional["QaVisualService"]:
    """QA visual si el extra ``sinnema[qa]`` está instalado (spec §7, §13-F4).

    Construye cada extractor en su propio bloque: una instalación parcial deja
    correr las métricas cuyas libs sí están (el servicio omite el resto con
    aviso). Sin NINGÚN extractor devuelve ``None`` y el nodo ``render_keyframes``
    avanza sin QA registrando el aviso — degradación elegante, nunca un tumbón.
    """
    cargar = cargador_de_baterias(anchor_store)

    def con_intento(constructor):
        try:
            return constructor()
        except Exception as exc:  # noqa: BLE001 - falta de deps/libs del extra 'qa'
            logger.info(
                "QA visual: extractor no disponible (%s: %s) — su métrica se omite.",
                type(exc).__name__, exc,
            )
            return None

    from sinnema.infrastructure.media.extractores import (
        ExtractorCarasInsightFace,
        ExtractorDinoClip,
        HasherPHash,
    )
    from sinnema.infrastructure.media.qa import QaVisualService

    caras = con_intento(ExtractorCarasInsightFace)
    embeddings = con_intento(ExtractorDinoClip)
    hasher = con_intento(HasherPHash)
    if caras is None and embeddings is None and hasher is None:
        return None
    return QaVisualService(
        cargar_imagen=cargar,
        extractor_caras=caras,
        extractor_embeddings=embeddings,
        hasher=hasher,
    )


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

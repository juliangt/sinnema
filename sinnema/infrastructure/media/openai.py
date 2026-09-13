"""Adaptador OpenAI ``gpt-image-1`` del puerto de media (spec §6/§3.1).

Implementa ``MediaGenerationPort`` sobre el SDK oficial ``openai`` (extra
opcional ``sinnema[media]``), por ``images.edit`` con multi-referencia
(~16 imágenes, ``LIMITES_OPENAI``). ``input_fidelity="high"`` preserva los
rasgos con máxima fidelidad SOLO en la primera imagen del array: por eso el
resolver garantiza que el ancla de identidad (personaje) viaje primera
(§3.1). OpenAI no expone ``seed``: el manifest la deja ``None``.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional, Tuple

from sinnema.domain.models import PedidoKeyframe
from sinnema.infrastructure.media.base import AdaptadorImagenBase

logger = logging.getLogger("sinnema.media.openai")

#: Techo global §3.1: gpt-image-1 acepta ~16 imágenes de entrada.
MAX_REFERENCIAS_OPENAI = 16

#: Relación de aspecto del paquete → tamaño nativo de gpt-image-1.
TAMANOS_POR_ASPECTO = {
    "9:16": "1024x1536",
    "1:1": "1024x1024",
    "16:9": "1536x1024",
}


class AdaptadorOpenAIImage(AdaptadorImagenBase):
    """Genera keyframes con ``gpt-image-1`` vía ``openai.images.edit``."""

    PROVEEDOR = "openai"
    MODELO_DEFAULT = "gpt-image-1"
    VAR_CLAVES = ("OPENAI_API_KEY",)
    MAX_CONSISTENCIA = MAX_REFERENCIAS_OPENAI
    MAX_ESTILO = MAX_REFERENCIAS_OPENAI
    MAX_TOTAL = MAX_REFERENCIAS_OPENAI

    # ------------------------------ SDK perezoso ------------------------------

    def _importar_sdk(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "El SDK 'openai' no está instalado: instálalo con el extra "
                "opcional de media ('pip install sinnema[media]' o "
                "'uv sync --extra media')."
            ) from exc
        return OpenAI

    def _cliente(self) -> Any:
        OpenAI = self._importar_sdk()
        return OpenAI(api_key=self.clave())

    # ------------------------------ llamada ------------------------------

    def _llamar(self, cliente: Any, pedido: PedidoKeyframe, referencias) -> Any:
        imagenes: list = [r.datos for r in referencias]
        encadenado = pedido.frame_inicial
        if encadenado is not None and len(imagenes) >= (self.MAX_TOTAL or 0):
            # Con la batería llena no queda hueco para el frame de la escena
            # anterior: se degrada a generación sin encadenado (§6).
            logger.warning(
                "Escena %s: batería llena (%d referencias); se omite el "
                "frame inicial del encadenado.",
                pedido.scene_number, len(imagenes),
            )
            encadenado = None
        if encadenado is not None:
            imagenes.append(encadenado)
        return cliente.images.edit(
            model=self._modelo,
            prompt=pedido.prompt_final,
            image=imagenes or None,
            # Fidelidad alta SOLO aplica a la primera imagen del array, que el
            # resolver garantiza ser el ancla de identidad (§3.1).
            input_fidelity="high" if referencias else None,
            size=TAMANOS_POR_ASPECTO.get(pedido.aspect_ratio, "auto"),
        )

    def _extraer_imagen(
        self, respuesta: Any, pedido: PedidoKeyframe
    ) -> Tuple[bytes, str]:
        for dato in getattr(respuesta, "data", None) or []:
            b64 = getattr(dato, "b64_json", None)
            if b64:
                return base64.b64decode(b64), "image/png"
        raise RuntimeError(
            f"OpenAI ({self._modelo}) no devolvió imagen para la escena "
            f"{pedido.scene_number} (¿bloqueo de moderación de contenido?)."
        )

    # ------------------------------ manifest ------------------------------

    def _seed(self, respuesta: Any) -> Optional[int]:
        # La API de imágenes de OpenAI no expone seed: el manifest es honesto.
        return None

    def _parametros(self, pedido, referencias, respuesta: Any) -> dict:
        parametros = super()._parametros(pedido, referencias, respuesta)
        parametros["input_fidelity"] = "high" if referencias else None
        parametros["size"] = TAMANOS_POR_ASPECTO.get(pedido.aspect_ratio, "auto")
        return parametros

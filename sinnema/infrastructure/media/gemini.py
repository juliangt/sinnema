"""Adaptador Gemini image ("Nano Banana") del puerto de media (spec §6/§3.1).

Implementa ``MediaGenerationPort`` sobre el SDK oficial ``google-genai``
(extra opcional ``sinnema[media]``). El resolver (``LIMITES_GEMINI``: ≤4
referencias de consistencia + ≤3 de estilo) entrega la batería en orden
identidad-primero; las imágenes viajan como ``Part.from_bytes`` junto al
prompt y el ``aspect_ratio`` va en la config de imagen. Gemini no expone
``seed`` en la respuesta de imagen: el manifest la deja ``None``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Tuple

from sinnema.domain.models import PedidoKeyframe
from sinnema.infrastructure.media.base import AdaptadorImagenBase

logger = logging.getLogger("sinnema.media.gemini")

#: Límites §3.1: Gemini image acepta ≤4 referencias de consistencia de
#: personaje (≤5 en Pro: se usa el techo conservador) + ≤3 de estilo.
MAX_REFERENCIAS_CONSISTENCIA_GEMINI = 4
MAX_REFERENCIAS_ESTILO_GEMINI = 3


class AdaptadorGeminiImage(AdaptadorImagenBase):
    """Genera keyframes con Gemini image vía ``google-genai``."""

    PROVEEDOR = "gemini"
    MODELO_DEFAULT = "gemini-2.5-flash-image"
    VAR_CLAVES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    MAX_CONSISTENCIA = MAX_REFERENCIAS_CONSISTENCIA_GEMINI
    MAX_ESTILO = MAX_REFERENCIAS_ESTILO_GEMINI

    # ------------------------------ SDK perezoso ------------------------------

    def _importar_sdk(self) -> Any:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise RuntimeError(
                "El SDK 'google-genai' no está instalado: instálalo con el "
                "extra opcional de media ('pip install sinnema[media]' o "
                "'uv sync --extra media')."
            ) from exc
        return genai, types

    def _cliente(self) -> Any:
        genai, _ = self._importar_sdk()
        return genai.Client(api_key=self.clave())

    # ------------------------------ llamada ------------------------------

    def _llamar(self, cliente: Any, pedido: PedidoKeyframe, referencias) -> Any:
        _, types = self._importar_sdk()
        contenido: list = [pedido.prompt_final]
        # Batería en orden identidad-primero (§3.1); el frame inicial del
        # encadenado viaja al final (condiciona, no es referencia de batería).
        contenido.extend(
            types.Part.from_bytes(data=r.datos, mime_type=r.mime)
            for r in referencias
        )
        if pedido.frame_inicial is not None:
            contenido.append(
                types.Part.from_bytes(
                    data=pedido.frame_inicial, mime_type="image/png"
                )
            )
        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=pedido.aspect_ratio),
        )
        return cliente.models.generate_content(
            model=self._modelo, contents=contenido, config=config
        )

    def _extraer_imagen(
        self, respuesta: Any, pedido: PedidoKeyframe
    ) -> Tuple[bytes, str]:
        for candidato in getattr(respuesta, "candidates", None) or []:
            for parte in getattr(getattr(candidato, "content", None), "parts", None) or []:
                inline = getattr(parte, "inline_data", None)
                datos = getattr(inline, "data", None) if inline is not None else None
                if datos:
                    mime = getattr(inline, "mime_type", None) or "image/png"
                    return bytes(datos), mime
        raise RuntimeError(
            f"Gemini ({self._modelo}) no devolvió imagen para la escena "
            f"{pedido.scene_number} (¿bloqueo de moderación o modelo sin "
            "capacidad de imagen?)."
        )

    # ------------------------------ manifest ------------------------------

    def _seed(self, respuesta: Any) -> Optional[int]:
        # La API de imagen de Gemini no expone seed: el manifest es honesto.
        return None

    def _id_externo(self, respuesta: Any) -> Optional[str]:
        return (
            getattr(respuesta, "response_id", None)
            or getattr(respuesta, "id", None)
        )

    def _parametros(self, pedido, referencias, respuesta: Any) -> dict:
        parametros = super()._parametros(pedido, referencias, respuesta)
        version = getattr(respuesta, "model_version", None)
        if version:
            parametros["modelo_version"] = version
        return parametros

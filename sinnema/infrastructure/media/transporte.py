"""Reintentos de transporte de la capa de media (patrón de ``infrastructure/llm``).

Solo cubre FALLOS DE TRANSPORTE (red, 429/5xx, timeouts del SDK): el bucle
reintenta la operación con backoff corto un número acotado de intentos.
Agotados, el error sube al nodo ``render_keyframes``, que aplica la semántica
de fallo §6 (escena sin keyframe + auditoría + la corrida sigue). Los
reintentos por QA (regeneración por score bajo) NO son cosa de este módulo:
llegan con la Fase 4.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

logger = logging.getLogger("sinnema.media.transporte")

T = TypeVar("T")


@dataclass(frozen=True)
class PoliticaReintentos:
    """Política de reintentos de transporte para llamadas a proveedores de media.

    Espejo de ``RetryPolicy`` del gateway LLM: máximos acotados y backoff
    lineal corto (el media es caro y lento: más de 3 intentos rara vez paga).
    """

    max_retries: int = 3
    backoff_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_retries < 1:
            raise ValueError(f"max_retries debe ser >= 1 (recibido: {self.max_retries}).")
        if self.backoff_seconds < 0:
            raise ValueError(
                f"backoff_seconds no puede ser negativo (recibido: {self.backoff_seconds})."
            )


def con_reintentos(
    operacion: Callable[[], T],
    politica: PoliticaReintentos,
    descripcion: str,
) -> T:
    """Ejecuta ``operacion`` reintentando fallos de transporte con backoff.

    Agotados los ``max_retries`` intentos, lanza ``RuntimeError`` accionable
    (el nodo lo registra y la escena sigue sin keyframe — §6). El backoff se
    duerme entre intentos pero no después del último.
    """
    ultimo_error: Exception = RuntimeError("sin intentos")
    for intento in range(1, politica.max_retries + 1):
        try:
            return operacion()
        except Exception as exc:  # noqa: BLE001 - reintenta cualquier fallo transitorio
            ultimo_error = exc
            logger.warning(
                "Media (%s): intento %s/%s falló (%s): %s",
                descripcion, intento, politica.max_retries,
                type(exc).__name__, exc,
            )
            if intento < politica.max_retries:
                time.sleep(politica.backoff_seconds * intento)
    raise RuntimeError(
        f"El proveedor de media falló tras {politica.max_retries} intentos "
        f"({descripcion}): {ultimo_error}"
    ) from ultimo_error

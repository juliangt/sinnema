"""Parámetros de runtime del grafo (no del producto)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RetryExhaustionPolicy = Literal["force_accept", "skip_chapter"]

_ALLOWED_POLICIES = ("force_accept", "skip_chapter")


@dataclass(frozen=True)
class PipelineSettings:
    """Configura el ciclo de crítica del grafo."""

    max_critique_attempts: int = 2
    retry_exhaustion_policy: RetryExhaustionPolicy = "force_accept"

    def __post_init__(self) -> None:
        if not (1 <= self.max_critique_attempts <= 5):
            raise ValueError(
                f"max_critique_attempts debe estar entre 1 y 5 "
                f"(recibido: {self.max_critique_attempts})."
            )
        if self.retry_exhaustion_policy not in _ALLOWED_POLICIES:
            raise ValueError(
                f"retry_exhaustion_policy debe ser una de {_ALLOWED_POLICIES} "
                f"(recibido: '{self.retry_exhaustion_policy}')."
            )

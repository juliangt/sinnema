"""Petición de serie (DTO de entrada) y estado inicial del grafo.

La petición agrupa solo los parámetros de la CORRIDA (tema, capítulos,
reintentos); toda la política de producto (voz, idioma, estilo, límites)
pertenece al ``ProjectSpec`` embebido, que llega ya validado desde el cargador.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sinnema.application.projects import (
    TOPIC_MAX_CHARS,
    TOPIC_MIN_CHARS,
    ProjectSpec,
)
from sinnema.application.state import PipelineState
from sinnema.domain.constants import SERIES_MAX_CHAPTERS
from sinnema.domain.models import LoreEntry

MAX_CRITIQUE_ATTEMPTS_LIMIT = 5


@dataclass(frozen=True)
class SeriesRequest:
    """Parámetros con los que se genera una serie completa para un proyecto."""

    project: ProjectSpec
    topic: Optional[str] = None  # None -> project.default_topic
    num_chapters: int = 3
    max_critique_attempts: int = 2

    def resolved_topic(self) -> str:
        """Tema efectivo de la corrida: el explícito o el del proyecto."""
        return (self.topic if self.topic is not None else self.project.default_topic).strip()

    def validate(self) -> None:
        """Valida todos los campos y reporta TODOS los problemas de una vez."""
        problemas: list[str] = []

        tema = self.resolved_topic()
        if len(tema) < TOPIC_MIN_CHARS:
            problemas.append(
                f"El tema debe tener al menos {TOPIC_MIN_CHARS} caracteres "
                f"(recibido: '{tema}')."
            )
        elif len(tema) > TOPIC_MAX_CHARS:
            problemas.append(
                f"El tema no puede superar {TOPIC_MAX_CHARS} caracteres "
                f"(recibido: {len(tema)})."
            )

        if not (1 <= self.num_chapters <= SERIES_MAX_CHAPTERS):
            problemas.append(
                f"num_chapters debe estar entre 1 y {SERIES_MAX_CHAPTERS} "
                f"(recibido: {self.num_chapters})."
            )
        if not (1 <= self.max_critique_attempts <= MAX_CRITIQUE_ATTEMPTS_LIMIT):
            problemas.append(
                f"max_critique_attempts debe estar entre 1 y "
                f"{MAX_CRITIQUE_ATTEMPTS_LIMIT} (recibido: {self.max_critique_attempts})."
            )

        if problemas:
            raise ValueError(
                "Petición de serie inválida: " + " | ".join(problemas)
            )


def build_initial_state(
    request: SeriesRequest,
    initial_lore: Optional[List[LoreEntry]] = None,
) -> PipelineState:
    """Proyecta la petición validada al estado inicial del grafo.

    ``initial_lore`` siembra la memoria de continuidad persistida del proyecto
    (vacía en la primera corrida); el grafo la amplía de forma append-only.
    """
    request.validate()
    proyecto = request.project
    return {
        # a) Input de corrida + proyección del proyecto (para audit/deliverable)
        "project_id": proyecto.project_id,
        "language": proyecto.language,
        "tone_of_voice": proyecto.tone_of_voice,
        "topic": request.resolved_topic(),
        "audience": proyecto.audience,
        "cultural_context": proyecto.cultural_context,
        "style_guide": proyecto.style_guide,
        "constraints": proyecto.constraints,
        "num_chapters": request.num_chapters,
        "max_critique_attempts": request.max_critique_attempts,
        # d) Runtime
        "current_chapter_index": 0,
        "critique_attempts": 0,
        # c/e) Acumuladores
        "lore_entries": list(initial_lore or []),
        "completed_episodes": [],
        "failed_chapters": [],
    }

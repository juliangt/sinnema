"""Prompts del CONTINUITY MASTER / LORE KEEPER por proyecto."""
from __future__ import annotations

from typing import List, Optional

from sinnema.application.projects import ProjectSpec
from sinnema.application.prompts._render import format_lore
from sinnema.domain.models import ChapterOutline, LoreEntry


def build_system_prompt(spec: ProjectSpec) -> str:
    return f"""Eres el CONTINUITY MASTER / LORE KEEPER de "{spec.brand_name}".

Custodias la memoria canónica de la serie (el "lore"): todos los conceptos,
términos, personajes y referencias ya establecidos en capítulos anteriores.
Tu misión: emitir directivas quirúrgicas para que el guionista construya SOBRE
lo ya visto, nunca repitiéndolo.

DIRECTIVAS QUE EMITES
- `recap_bridge`: 1-2 frases que conectan el capítulo anterior con este
  (guiño, no resumen). Si no hay capítulos previos, una apertura que plantee
  la promesa de la serie.
- `concepts_already_covered`: extraído ESTRICTAMENTE del lore acumulado;
  conceptos que este capítulo debe dar por sabidos.
- `callbacks_allowed`: 2-3 llamadas narrativas específicas a momentos o
  términos de capítulos anteriores (formato: "término -> cómo aludirlo").
- `new_terms_to_introduce`: términos nuevos de este capítulo que se sumarán
  al lore, como término canónico corto (1-4 palabras). Ninguno puede figurar
  en `concepts_already_covered`: sería nuevo y cubierto a la vez.
- `forbidden_reexplanations`: conceptos del lore cuya re-explicación o
  re-definición formal está prohibida en este capítulo.

REGLAS
- NO inventes entradas de lore que no estén en la memoria acumulada.
- Si la memoria está vacía, emite directivas de lanzamiento (premisa, tono,
  sin recap de capítulos previos).
- Sé específico y accionable: el guionista solo verá tus directivas.
- Escribe las directivas en {spec.language}.
- Responde EXCLUSIVAMENTE mediante el esquema estructurado."""


def build_user_message(
    chapter: ChapterOutline,
    previous_chapter: Optional[ChapterOutline],
    lore_entries: List[LoreEntry],
    recurring_elements: List[str],
) -> str:
    previo = (
        f"{previous_chapter.chapter_id} — {previous_chapter.title}"
        if previous_chapter is not None
        else "(ninguno: primer capítulo de la serie)"
    )
    return (
        "<contexto_de_continuidad>\n"
        "<capitulo_actual>\n"
        f"  id: {chapter.chapter_id}\n"
        f"  titulo: {chapter.title}\n"
        f"  objetivo: {chapter.learning_objective}\n"
        f"  conceptos_clave: {', '.join(chapter.key_concepts)}\n"
        f"  dificultad: {chapter.difficulty}\n"
        "</capitulo_actual>\n"
        f"<capitulo_anterior>{previo}</capitulo_anterior>\n"
        "<memoria_lore>\n"
        f"{format_lore(lore_entries)}\n"
        "</memoria_lore>\n"
        f"<elementos_recurrentes>{'; '.join(recurring_elements) or '(sin definir)'}</elementos_recurrentes>\n"
        "</contexto_de_continuidad>\n\n"
        "Emite las directivas de continuidad para este capítulo."
    )

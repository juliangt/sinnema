"""Serializadores compartidos entre constructores de mensajes de usuario."""
from __future__ import annotations

from typing import List

from sinnema.domain.models import LoreEntry, ScriptDraft


def format_lore(entries: List[LoreEntry]) -> str:
    """Serializa la memoria de lore en un bloque delimitado y legible."""
    if not entries:
        return "(memoria de continuidad vacía: este es el primer capítulo de la serie)"
    lineas = [
        f"- [{e.category}] {e.term} :: {e.definition} (visto en: {e.first_seen_title})"
        for e in entries
    ]
    return "\n".join(lineas)


def format_draft_scenes(draft: ScriptDraft) -> str:
    """Vuelca las escenas de un borrador con sus datos de producción."""
    lineas = [
        f"  Escena {s.scene_number} ({s.duration_seconds:.0f} s) | transición: {s.transition}\n"
        f"    visual: {s.visual_action}\n"
        f"    narración: {s.narration}\n"
        f"    texto_en_pantalla: {s.on_screen_text or '—'}"
        for s in draft.scenes
    ]
    return "\n".join(lineas)

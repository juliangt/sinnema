"""Serializadores compartidos entre constructores de mensajes de usuario."""
from __future__ import annotations

from typing import List, Optional

from sinnema.domain.models import LoreEntry, RecursoAncla, ScriptDraft


def format_lore(entries: List[LoreEntry]) -> str:
    """Serializa la memoria de lore en un bloque delimitado y legible."""
    if not entries:
        return "(memoria de continuidad vacía: este es el primer capítulo de la serie)"
    lineas = [
        f"- [{e.category}] {e.term} :: {e.definition} (visto en: {e.first_seen_title})"
        for e in entries
    ]
    return "\n".join(lineas)


def format_biblioteca_anclas(anclas: Optional[List[RecursoAncla]]) -> str:
    """Serializa la biblioteca lockeada (spec-recursos-ancla §5.1/§5.3).

    Una línea por ancla: tipo, id, nombre canónico y descriptor EN. El bloque
    resultante alimenta a continuity y al director técnico; vacío solo si no
    hay lockeadas (los llamadores omiten el bloque completo en ese caso).
    """
    return "\n".join(
        f"- [{a.tipo}] {a.ancla_id} :: {a.nombre} :: {a.descripcion_canonica}"
        for a in (anclas or [])
    )


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

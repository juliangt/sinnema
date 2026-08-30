"""Prompts del CONTENT CREATOR / SCRIPTWRITER por proyecto."""
from __future__ import annotations

from typing import Optional

from sinnema.application.projects import ProjectSpec
from sinnema.domain.models import ChapterOutline, ContinuityDirectives


def build_system_prompt(spec: ProjectSpec) -> str:
    f = spec.format
    w_min, w_max = f.narration_target_words
    d_min, d_max = f.total_duration_target_seconds
    s_min, s_max = f.scenes_count
    ds_min, ds_max = f.scene_duration_seconds
    return f"""Eres el CONTENT CREATOR / SCRIPTWRITER principal de "{spec.brand_name}".

Escribes guiones de {spec.show_concept} ({f.aspect_ratio}), con estructura de
bloques fijos y límites de ritmo no negociables.

ESTRUCTURA OBLIGATORIA
- Escena 1 (HOOK, 3-5 s): gancho que detiene el scroll (pregunta provocadora,
  promesa concreta o continuación del capítulo anterior).
- Escenas 2 a N-1 (DESARROLLO): una sola idea por escena, encadenadas en
  orden lógico didáctico.
- Escena final (CIERRE + CTA): remate memorable + llamada a la acción.

LÍMITES DUROS (el sistema los verifica y rechaza lo que los viole)
- Total de palabras narradas (hook + narraciones + CTA): {w_min}-{w_max}. Objetivo: {(w_min + w_max) // 2}.
- Escenas: entre {s_min} y {s_max}, numeradas 1..N sin huecos.
- Duración por escena: {ds_min:.0f}-{ds_max:.0f} s; la suma total debe quedar
  entre {d_min:.0f} y {d_max:.0f} s.
- Narración por escena: máximo {f.narration_max_words_per_scene} palabras (frases cortas).
- `on_screen_text`: máximo {f.on_screen_text_max_words} palabras, tipografía de impacto.

CONTINUIDAD (directivas del Lore Keeper)
- Abre con el `recap_bridge` provisto (adáptalo con tu voz, no lo copies tal cual).
- Usa los `callbacks_allowed` como guiños narrativos.
- Introduce cada término de `new_terms_to_introduce` con una definición veloz
  y natural (máx 8 palabras de definición).
- PROHIBIDO re-explicar cualquier concepto de `concepts_already_covered` o de
  `forbidden_reexplanations`: menciona el término y sigue adelante.

CORRECCIÓN
Si el bloque <correccion_feedback> está presente, es la palabra del Chief
Editor: aplica TODAS sus instrucciones numeradas o el guión volverá a ser
rechazado.

Escribes en {spec.language} con un registro base {spec.tone_of_voice}; otro
agente adaptará después el registro al público objetivo. Responde
EXCLUSIVAMENTE mediante el esquema estructurado."""


def build_user_message(
    spec: ProjectSpec,
    chapter: ChapterOutline,
    directives: ContinuityDirectives,
    feedback: Optional[str] = None,
) -> str:
    w_min, w_max = spec.format.narration_target_words
    s_min, s_max = spec.format.scenes_count
    d_min, d_max = spec.format.total_duration_target_seconds
    bloque_feedback = (
        f"<correccion_feedback>\n{feedback}\n</correccion_feedback>\n"
        if feedback
        else ""
    )
    return (
        "<encargo_de_guion>\n"
        "<capitulo>\n"
        f"  id: {chapter.chapter_id}\n"
        f"  titulo: {chapter.title}\n"
        f"  objetivo_de_aprendizaje: {chapter.learning_objective}\n"
        f"  conceptos_clave_a_introducir: {', '.join(chapter.key_concepts)}\n"
        f"  presupuesto_de_palabras: {chapter.word_budget} palabras narradas (rango {w_min}-{w_max})\n"
        "</capitulo>\n"
        "<directivas_de_continuidad>\n"
        f"  recap_bridge: {directives.recap_bridge}\n"
        f"  conceptos_ya_cubiertos (NO re-explicar): "
        f"{', '.join(directives.concepts_already_covered) or '(ninguno)'}\n"
        f"  callbacks_permitidos: {' | '.join(directives.callbacks_allowed) or '(ninguno)'}\n"
        f"  terminos_nuevos_a_introducir: {', '.join(directives.new_terms_to_introduce)}\n"
        f"  prohibido_reexplicar: "
        f"{', '.join(directives.forbidden_reexplanations) or '(nada adicional)'}\n"
        f"  notas: {directives.continuity_notes}\n"
        "</directivas_de_continuidad>\n"
        f"<audiencia>{spec.audience}</audiencia>\n"
        f"<guia_de_estilo>{spec.style_guide}</guia_de_estilo>\n"
        f"<restricciones>{spec.constraints}</restricciones>\n"
        f"{bloque_feedback}</encargo_de_guion>\n\n"
        f"Escribe el guion completo: {chapter.word_budget} palabras, "
        f"{s_min}-{s_max} escenas, {d_min:.0f}-{d_max:.0f} s de duración total."
    )

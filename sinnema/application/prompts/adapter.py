"""Prompts del PERSONA & AUDIENCE ADAPTER por proyecto."""
from __future__ import annotations

from sinnema.application.projects import ProjectSpec
from sinnema.application.prompts._render import format_draft_scenes
from sinnema.domain.models import ContinuityDirectives, ScriptDraft


def build_system_prompt(spec: ProjectSpec) -> str:
    f = spec.format
    w_min, w_max = f.narration_target_words
    return f"""Eres el PERSONA & AUDIENCE ADAPTER de "{spec.brand_name}".

Reescribes guiones para el PÚBLICO OBJETIVO del proyecto, sin perder un ápice
de rigor técnico.

PÚBLICO OBJETIVO: {spec.audience}
IDIOMA Y REGISTRO: {spec.language}; {spec.tone_of_voice}
CONTEXTO CULTURAL: {spec.cultural_context}

REGISTRO LINGÜÍSTICO
- Ajusta el tratamiento y la energía al público objetivo definido arriba.
- Modismos orgánicos del idioma y la cultura objetivo — entre 2 y 4 en todo el
  guión, nunca forzados ni exagerados.
- Referencias culturales actuales y creíbles para ese público, derivadas del
  contexto cultural; sin marcas registradas.
- PROHIBIDO: vulgaridad, doble sentido ofensivo, burlas a grupos, anglicismos
  innecesarios cuando existe término en el idioma del proyecto.

RESTRICCIONES DE INTEGRIDAD (el sistema las verifica)
- Conserva EXACTAMENTE la misma cantidad de escenas y la numeración original.
- Conserva la estructura narrativa y el orden de las ideas.
- Total de palabras narradas final: {w_min}-{w_max} (si falta espacio, recorta adorno,
  JAMÁS concepto didáctico).
- La precisión técnica es sagrada: puedes simplificar el tono, nunca el hecho.
- Adapta también `on_screen_text` al registro del proyecto (máx {f.on_screen_text_max_words} palabras).

DOCUMENTA tus decisiones en `register_notes` (qué modismos usaste y por qué)
y en `cultural_references` (qué referencias insertaste).
Responde EXCLUSIVAMENTE mediante el esquema estructurado."""


def build_user_message(
    spec: ProjectSpec,
    draft: ScriptDraft,
    directives: ContinuityDirectives,
) -> str:
    return (
        "<encargo_de_adaptacion>\n"
        f"<titulo_original>{draft.title}</titulo_original>\n"
        f"<hook_original>{draft.hook}</hook_original>\n"
        "<escenas_originales>\n"
        f"{format_draft_scenes(draft)}\n"
        "</escenas_originales>\n"
        f"<cta_original>{draft.call_to_action}</cta_original>\n"
        f"<audiencia>{spec.audience}</audiencia>\n"
        f"<contexto_cultural>{spec.cultural_context}</contexto_cultural>\n"
        "<callbacks_permitidos>\n"
        f"{' | '.join(directives.callbacks_allowed) or '(ninguno)'}\n"
        "</callbacks_permitidos>\n"
        "</encargo_de_adaptacion>\n\n"
        "Adapta el guion completo al público objetivo manteniendo escena por "
        "escena la numeración, la estructura y el presupuesto de palabras."
    )

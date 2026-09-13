"""Prompts del TECHNICAL ADAPTER / VISUAL & AUDIO DIRECTOR por proyecto."""
from __future__ import annotations

from typing import List, Optional

from sinnema.application.projects import ProjectSpec
from sinnema.application.prompts._render import format_biblioteca_anclas
from sinnema.domain.models import (
    AdaptedScript,
    AnclaDelCapitulo,
    ChapterOutline,
    RecursoAncla,
    ScriptDraft,
)

_SECCION_ANCLAS = """

BIBLIOTECA DE ANCLAS (identidad visual fija)
- Toda entidad con ancla presente en la escena DEBE declararse en `anclas`
  (su ancla_id) y describirse en `image_prompt` con su descriptor canónico;
  los personajes/lugares anclados NUNCA se describen con palabras nuevas.
- `thumbnail_prompt` puede citar el ancla de estilo y la del personaje
  principal del capítulo.
- Jamás declares un ancla_id ausente de la biblioteca: el sistema rechaza el
  paquete."""


def build_system_prompt(
    spec: ProjectSpec, anclas: Optional[List[RecursoAncla]] = None
) -> str:
    f = spec.format
    s_min, s_max = f.scenes_count
    prompt = f"""Eres el TECHNICAL ADAPTER / VISUAL & AUDIO DIRECTOR de "{spec.brand_name}".

Traduces guiones aprobados en {spec.language} a especificaciones técnicas de
producción para modelos generativos secundarios (imagen, video, voz, música,
miniatura).

ESTILO MAESTRO DE LA SERIE (aplica a TODO prompt visual)
- {spec.visual_master_style}

TUS RESPONSABILIDADES
1. `image_prompt` (por escena, EN INGLÉS, 40+ palabras): sujeto + entorno +
   acción + iluminación + composición {f.aspect_ratio} + estilo maestro. Mantén la
   consistencia de personajes/mascota repitiendo sus descriptores canónicos.
2. `negative_prompt` (EN INGLÉS): lo que nunca debe aparecer (watermark,
   text artifacts, blurry, extra fingers, realistic photo, horizontal
   layout, cluttered background, ...).
3. `motion_direction` (EN INGLÉS): cámara y movimiento de sujeto para el
   modelo de video (ej: "slow dolly-in toward the mascot while the data
   particles orbit clockwise").
4. `audio_direction`: estilo de voz acorde al proyecto ({spec.language};
   {spec.tone_of_voice}), notas de dirección por bloque (energía del hook,
   calma didáctica, cierre cálido), mood musical y 1-3 SFX por escena.
5. `thumbnail_prompt` (EN INGLÉS): portada {f.aspect_ratio} de alto CTR con el
   concepto clave del capítulo.

REGLAS
- Una especificación visual por cada escena del guion, misma numeración
  exacta (1..N sin huecos): el sistema rechaza paquetes desalineados.
- El paquete declara `aspect_ratio` = "{f.aspect_ratio}" y entre {s_min} y {s_max} specs,
  una por escena.
- Los prompts visuales SIEMPRE en inglés puro, con independencia del idioma
  del guion; nada de {spec.language} dentro de image/negative/motion prompts
  (ni tildes ni ñ: el sistema lo verifica).
- Coherencia total entre escenas: mismos personajes, misma paleta, mismo mundo.
Responde EXCLUSIVAMENTE mediante el esquema estructurado."""
    if not anclas:
        return prompt
    return prompt + _SECCION_ANCLAS


def build_user_message(
    spec: ProjectSpec,
    chapter: ChapterOutline,
    draft: ScriptDraft,
    adapted: AdaptedScript,
    recurring_elements: List[str],
    anclas: Optional[List[RecursoAncla]] = None,
    casting: Optional[List[AnclaDelCapitulo]] = None,
) -> str:
    visuales = {s.scene_number: s for s in draft.scenes}
    escenas = []
    for s in adapted.adapted_scenes:
        base = visuales.get(s.scene_number)
        escenas.append(
            f"  Escena {s.scene_number}\n"
            f"    duración: {base.duration_seconds:.0f} s | transición: {base.transition if base else 'corte_seco'}\n"
            f"    acción visual: {base.visual_action if base else '(sin referencia)'}\n"
            f"    narración final (referencia de contenido): {s.narration}"
        )
    bloque_biblioteca = (
        "<biblioteca_de_anclas>\n"
        f"{format_biblioteca_anclas(anclas)}\n"
        "</biblioteca_de_anclas>\n"
        if anclas
        else ""
    )
    bloque_casting = (
        "<casting_del_capitulo>\n"
        + "\n".join(
            f"- [{cita.tipo}] {cita.ancla_id} :: {cita.descriptor} | "
            f"instrucciones: {cita.instrucciones}"
            for cita in (casting or [])
        )
        + "\n</casting_del_capitulo>\n"
        if casting
        else ""
    )
    return (
        "<encargo_tecnico>\n"
        f"<capitulo>{chapter.chapter_id} — {chapter.title}</capitulo>\n"
        f"<guia_de_estilo>{spec.style_guide}</guia_de_estilo>\n"
        f"<estilo_maestro>{spec.visual_master_style}</estilo_maestro>\n"
        f"<elementos_recurrentes>{'; '.join(recurring_elements) or '(sin definir)'}</elementos_recurrentes>\n"
        f"{bloque_biblioteca}"
        f"{bloque_casting}"
        "<escenas_aprobadas>\n"
        f"{chr(10).join(escenas)}\n"
        "</escenas_aprobadas>\n"
        "</encargo_tecnico>\n\n"
        "Genera el paquete técnico completo de producción: una especificación "
        "visual por escena, dirección de audio y prompt de miniatura."
    )

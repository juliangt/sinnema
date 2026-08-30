"""Prompts del TECHNICAL ADAPTER / VISUAL & AUDIO DIRECTOR por proyecto."""
from __future__ import annotations

from typing import List

from sinnema.application.projects import ProjectSpec
from sinnema.domain.models import AdaptedScript, ChapterOutline, ScriptDraft


def build_system_prompt(spec: ProjectSpec) -> str:
    f = spec.format
    s_min, s_max = f.scenes_count
    return f"""Eres el TECHNICAL ADAPTER / VISUAL & AUDIO DIRECTOR de "{spec.brand_name}".

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


def build_user_message(
    spec: ProjectSpec,
    chapter: ChapterOutline,
    draft: ScriptDraft,
    adapted: AdaptedScript,
    recurring_elements: List[str],
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
    return (
        "<encargo_tecnico>\n"
        f"<capitulo>{chapter.chapter_id} — {chapter.title}</capitulo>\n"
        f"<guia_de_estilo>{spec.style_guide}</guia_de_estilo>\n"
        f"<estilo_maestro>{spec.visual_master_style}</estilo_maestro>\n"
        f"<elementos_recurrentes>{'; '.join(recurring_elements) or '(sin definir)'}</elementos_recurrentes>\n"
        "<escenas_aprobadas>\n"
        f"{chr(10).join(escenas)}\n"
        "</escenas_aprobadas>\n"
        "</encargo_tecnico>\n\n"
        "Genera el paquete técnico completo de producción: una especificación "
        "visual por escena, dirección de audio y prompt de miniatura."
    )

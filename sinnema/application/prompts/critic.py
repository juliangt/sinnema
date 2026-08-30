"""Prompts del CHIEF EDITOR / CRITIC (auditor) por proyecto."""
from __future__ import annotations

from typing import Optional

from sinnema.application.projects import ProjectSpec
from sinnema.domain.models import (
    AdaptedScript,
    ChapterOutline,
    ContinuityDirectives,
    ScriptDraft,
)


def build_system_prompt(spec: ProjectSpec) -> str:
    f = spec.format
    w_min, w_max = f.narration_target_words
    d_min, d_max = f.total_duration_target_seconds
    return f"""Eres el CHIEF EDITOR / CRITIC de "{spec.brand_name}": el auditor de calidad implacable.

Tu único objetivo es la excelencia del contenido final. No negocias estándares
ni te dejas llevar por el cariño al borrador: si no cumple, se rechaza.

AUDITAS SEIS DIMENSIONES (cada hallazgo con severidad y score 0-10)
1. ritmo: gancho en los primeros 5 s, una idea por escena, sin baches.
2. presupuesto: {w_min}-{w_max} palabras narradas; duración total entre {d_min:.0f} y {d_max:.0f} s.
3. adherencia_audiencia: registro y referencias creíbles para el público
   objetivo del proyecto ({spec.audience}); sin tono condescendiente ni
   académico seco.
4. continuidad: cero re-explicaciones de lo ya cubierto; callbacks usados con
   naturalidad; términos nuevos definidos al introducirse.
5. claridad_didactica: el objetivo de aprendizaje se logra en el tiempo del formato.
6. cierre: remate memorable + CTA que invita al siguiente capítulo.

VEREDICTO
- `approved: true` SOLO si overall_score >= {f.min_approval_score}, no existe
  ningún hallazgo "bloqueante" y el conteo de palabras está "dentro_de_rango".
- `approved: false` NUNCA sin motivo: incluye al menos un hallazgo en
  `findings` o una entrada en `continuity_violations` que justifique el rechazo.
- `correction_feedback`: SIEMPRE presente. Si rechazas: instrucciones
  numeradas, concretas y accionables, referenciando escenas exactas
  (ej: "Escena 4: elimina la definición de 'modelo'; ya se cubrió en ch-02;
  sustitúyela por un callback de 6 palabras"). Nada de consejos vagos.
  Si apruebas: un resumen breve de por qué pasó.
- `continuity_violations`: lista exacta de conceptos re-explicados o
  contradicciones con el lore (vacía si no hay).
Responde EXCLUSIVAMENTE mediante el esquema estructurado."""


def build_user_message(
    spec: ProjectSpec,
    chapter: ChapterOutline,
    draft: ScriptDraft,
    adapted: AdaptedScript,
    directives: Optional[ContinuityDirectives],
    actual_word_count: int,
) -> str:
    w_min, w_max = spec.format.narration_target_words
    visuales = {s.scene_number: s for s in draft.scenes}
    escenas = []
    for s in adapted.adapted_scenes:
        base = visuales.get(s.scene_number)
        duracion = f"{base.duration_seconds:.0f} s" if base else "n/d"
        visual = base.visual_action if base else "(sin referencia)"
        escenas.append(
            f"  Escena {s.scene_number} ({duracion})\n"
            f"    visual: {visual}\n"
            f"    narración final: {s.narration}\n"
            f"    texto_en_pantalla: {s.on_screen_text or '—'}"
        )
    escenas_texto = "\n".join(escenas)
    if directives is not None:
        bloque_directivas = (
            "<directivas_de_continuidad>\n"
            f"  conceptos_ya_cubiertos: {', '.join(directives.concepts_already_covered) or '(ninguno)'}\n"
            f"  prohibido_reexplicar: {', '.join(directives.forbidden_reexplanations) or '(nada)'}\n"
            f"  terminos_nuevos: {', '.join(directives.new_terms_to_introduce)}\n"
            "</directivas_de_continuidad>\n"
        )
    else:
        bloque_directivas = (
            "<directivas_de_continuidad>\n"
            "  (sin directivas: el agente de continuidad está desactivado en este "
            "proyecto; audita coherencia con los títulos de los capítulos)\n"
            "</directivas_de_continuidad>\n"
        )
    return (
        "<auditoria>\n"
        "<capitulo>\n"
        f"  id: {chapter.chapter_id}\n"
        f"  titulo: {chapter.title}\n"
        f"  objetivo_de_aprendizaje: {chapter.learning_objective}\n"
        "</capitulo>\n"
        "<guion_final_a_auditar>\n"
        f"  título: {adapted.adapted_title}\n"
        f"  hook: {adapted.adapted_hook}\n"
        f"  escenas:\n{escenas_texto}\n"
        f"  cta: {adapted.adapted_cta}\n"
        "</guion_final_a_auditar>\n"
        f"<audiencia_objetivo>{spec.audience}</audiencia_objetivo>\n"
        f"<presupuesto_requerido>{w_min}-{w_max} palabras narradas</presupuesto_requerido>\n"
        f"<conteo_real_palabras>{actual_word_count}</conteo_real_palabras>\n"
        f"<duracion_estimada_segundos>{draft.total_duration_seconds}</duracion_estimada_segundos>\n"
        f"{bloque_directivas}"
        "</auditoria>\n\n"
        "Emite el dictamen de calidad completo."
    )

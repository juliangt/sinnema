"""Prompts del CURRICULUM / STRATEGIC PLANNER por proyecto."""
from __future__ import annotations

from sinnema.application.projects import ProjectSpec


def build_system_prompt(spec: ProjectSpec) -> str:
    f = spec.format
    w_min, w_max = f.narration_target_words
    duracion_mid = (f.total_duration_target_seconds[0] + f.total_duration_target_seconds[1]) / 2
    return f"""Eres el CURRICULUM & STRATEGIC PLANNER de "{spec.brand_name}", un estudio de
{spec.show_concept}.

Tu misión: diseñar el plan maestro (macro) de una serie, desglosándola
en capítulos que formen una curva de aprendizaje progresiva y adictiva.

PRINCIPIOS DE DISEÑO
1. Curva de aprendizaje: ordena los capítulos de lo simple a lo complejo; cada
   capítulo construye sobre los conceptos del anterior SIN repetirlos. La
   dificultad declarada nunca retrocede (inicial -> intermedio -> avanzado).
2. Autocontención episódica: cada capítulo funciona por sí solo, pero premia
   haber visto los anteriores.
3. Presupuesto duro: cada capítulo se narra en {w_min}-{w_max} palabras y dura
   ~{duracion_mid:.0f} s; define objetivos que quepan en ese espacio (una sola
   idea fuerte por capítulo).
4. Continuidad: los `key_concepts` de cada capítulo alimentan el glosario (lore)
   de la serie; decláralos como términos canónicos, cortos (1-4 palabras) y
   reutilizables. Un capítulo nunca declara como prerrequisito un concepto que
   él mismo introduce.
5. Identidad serial: define `recurring_elements` (mascota, apertura fija,
   firma visual, eslogan de cierre) que amarran la serie.

REGLAS DE FORMATO
- `chapter_id`: "ch-01", "ch-02", ... (secuencial, minúsculas, dos dígitos).
- `title`: máximo ~60 caracteres, con gancho, sin clickbait vacío.
- `key_concepts`: entre 2 y 6 conceptos, cada uno de 1 a 4 palabras.
- `difficulty`: "inicial" -> "intermedio" -> "avanzado", orden no decreciente.
- `word_budget`: entre {w_min} y {w_max} palabras (presupuesto narrado del capítulo).
- Escribe títulos, objetivos y conceptos en {spec.language}.
- Responde EXACTAMENTE con el número de capítulos solicitado.
- Responde EXCLUSIVAMENTE mediante el esquema estructurado; nada de texto libre.

EJEMPLO DE UN BUEN CAPÍTULO (few-shot, estilo esperado)
  chapter_id: "ch-03"
  title: "¿Cómo 'aprende' una IA? Spoiler: con ejemplos"
  learning_objective: "Que el espectador entienda el entrenamiento por ejemplos
  como ajustar una línea hasta acertar, sin matemáticas formales."
  key_concepts: ["entrenamiento", "ejemplo etiquetado", "modelo"]
  difficulty: "inicial"
  word_budget: 140"""


def build_user_message(spec: ProjectSpec, topic: str, num_chapters: int) -> str:
    return (
        "<encargo_de_planificacion>\n"
        f"<tema>{topic}</tema>\n"
        f"<audiencia>{spec.audience}</audiencia>\n"
        f"<contexto_cultural>{spec.cultural_context}</contexto_cultural>\n"
        f"<guia_de_estilo>{spec.style_guide}</guia_de_estilo>\n"
        f"<restricciones>{spec.constraints}</restricciones>\n"
        f"<numero_de_capitulos>{num_chapters}</numero_de_capitulos>\n"
        "</encargo_de_planificacion>\n\n"
        f"Diseña el plan maestro de la serie con exactamente {num_chapters} capítulos, "
        "siguiendo tus principios de diseño."
    )

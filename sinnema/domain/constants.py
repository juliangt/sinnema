"""Constantes de dominio: límites universales de sanidad del motor.

El motor es multi-proyecto: cada proyecto (show) define su sobre editorial
concreto en un ``FormatProfile`` (rango objetivo y rango duro por métrica).
Aquí viven solo los pisos y techos UNIVERSALES que cualquier perfil debe
respetar: existen para rechazar basura estructural (un guion de 3 palabras,
2000 palabras, 40 escenas) antes de que circule por el pipeline.
"""
from __future__ import annotations

# --- Presupuesto narrado (palabras) ----------------------------------------
NARRATION_UNIVERSAL_MIN_WORDS = 30
NARRATION_UNIVERSAL_MAX_WORDS = 600
#: Techo universal por escena; el perfil editorial del proyecto lo aprieta.
NARRATION_UNIVERSAL_MAX_WORDS_PER_SCENE = 100

# --- Duración (segundos) -----------------------------------------------------
SCENE_DURATION_UNIVERSAL_MIN_SECONDS = 1.0
SCENE_DURATION_UNIVERSAL_MAX_SECONDS = 60.0
TOTAL_DURATION_UNIVERSAL_MIN_SECONDS = 10.0
TOTAL_DURATION_UNIVERSAL_MAX_SECONDS = 180.0

# --- Escenas -----------------------------------------------------------------
SCENE_NUMBER_MIN = 1
SCENE_NUMBER_MAX = 12
#: Cantidad de escenas (y de specs visuales) en cualquier proyecto.
SCENES_UNIVERSAL_MIN_COUNT = 1
SCENES_UNIVERSAL_MAX_COUNT = 12
ON_SCREEN_TEXT_UNIVERSAL_MAX_WORDS = 12

# --- Capítulos / serie --------------------------------------------------------
SERIES_MAX_CHAPTERS = 20
#: Un concepto clave o término de lore es un sintagma corto (1-4 palabras).
CONCEPT_MAX_WORDS = 4
LORE_TERM_MAX_WORDS = 4

# --- QA ------------------------------------------------------------------------
#: Rango universal del score de QA; el mínimo de aprobación lo fija el proyecto.
QA_SCORE_UNIVERSAL_MIN = 0
QA_SCORE_UNIVERSAL_MAX = 10

# --- Alcance del pipeline (hitos, de menor a mayor) -----------------------------
#: Último hito del pipeline que un proyecto alcanza (``[flujo].hasta`` y campo
#: ``alcance`` del entregable). Vocabulario cerrado y ordenado: la comparación
#: de orden (p. ej. "los fallos exigen compuerta") usa este índice.
ALCANCES = ("plan", "guion", "guion_final", "auditado", "produccion")
ALCANCE_DEFAULT = "produccion"
#: Primer alcance cuya corrida pasa por la compuerta de calidad (revisor):
#: solo a partir de ahí pueden existir capítulos descartados.
ALCANCE_COMPUERTA = "auditado"

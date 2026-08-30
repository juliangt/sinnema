"""Fábricas de entidades válidas y dobles de test compartidos.

Todas las fábricas devuelven objetos que cumplen TODOS los contratos de
dominio, listos para inyectarse en servicios, grafo o gateway falsos.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pytest

from sinnema.application.projects import ProjectSpec
from sinnema.application.requests import SeriesRequest
from sinnema.domain.models import (
    AdaptedScene,
    AdaptedScript,
    AuditFinding,
    AudioDirection,
    ChapterOutline,
    ContinuityDirectives,
    FormatProfile,
    LoreEntry,
    QualityAudit,
    Scene,
    ScriptDraft,
    SeriesPlan,
    TechnicalPackage,
    VisualAssetSpec,
)

# --- Valores del proyecto de referencia (espejan proyectos/sinnema.toml) -----
TEMA = "Los fundamentos de la inteligencia artificial explicados desde cero"
AUDIENCIA = "Adolescentes de 14 a 18 años en Latinoamérica"
CONTEXTO_CULTURAL = "Español neutro latinoamericano con modismos orgánicos"
GUIA_DE_ESTILO = "Estética 3D isométrica tech; formato vertical 9:16"
RESTRICCIONES = "Sin jerga ofensiva; precisión técnica intacta"


def frase(num_palabras: int, semilla: str = "palabra") -> str:
    """Genera una frase sintética de N palabras (evita acentos por simplicidad)."""
    return " ".join(f"{semilla}{i}" for i in range(num_palabras))


# =========================================================================
# FÁBRICAS DE DOMINIO
# =========================================================================


def make_chapter(index: int = 1, **overrides) -> ChapterOutline:
    datos = dict(
        chapter_id=f"ch-{index:02d}",
        title=f"Capítulo de prueba número {index}",
        learning_objective="Objetivo de aprendizaje suficientemente detallado para validar.",
        key_concepts=[f"concepto {index}a", f"concepto {index}b"],
        difficulty="inicial",
        word_budget=140,
    )
    datos.update(overrides)
    return ChapterOutline(**datos)


def make_plan(num_chapters: int = 2, **overrides) -> SeriesPlan:
    datos = dict(
        series_title="Serie de prueba sobre IA",
        series_promise="Una promesa clara de valor educativo.",
        audience_summary="Adolescentes latinoamericanos.",
        narrative_arc="Un arco narrativo que conecta los capítulos.",
        chapters=[make_chapter(i) for i in range(1, num_chapters + 1)],
        recurring_elements=["mascota Roby"],
    )
    datos.update(overrides)
    return SeriesPlan(**datos)


def make_directives(
    new_terms: tuple = ("término canónico",),
    concepts_covered: tuple = (),
) -> ContinuityDirectives:
    return ContinuityDirectives(
        recap_bridge="Puente narrativo que conecta con el capítulo anterior.",
        concepts_already_covered=list(concepts_covered),
        callbacks_allowed=["modelo -> guiño rápido"],
        new_terms_to_introduce=list(new_terms),
        forbidden_reexplanations=[],
        continuity_notes="Notas operativas para el guionista a cargo.",
    )


def make_scene(n: int, duration: float = 10.0, words: int = 20) -> Scene:
    return Scene(
        scene_number=n,
        duration_seconds=duration,
        visual_action=f"Acción visual descriptiva y concreta de la escena número {n}",
        narration=frase(words, f"nar{n}"),
        on_screen_text="texto en pantalla",
        transition="corte_seco",
    )


def make_draft(
    chapter_id: str = "ch-01", num_scenes: int = 6, words_per_scene: int = 20
) -> ScriptDraft:
    """Guión válido por defecto: 142 palabras narradas y 60 s de duración."""
    return ScriptDraft(
        chapter_id=chapter_id,
        title="Título de prueba del borrador",
        hook=frase(12, "gancho"),
        scenes=[
            make_scene(n, words=words_per_scene) for n in range(1, num_scenes + 1)
        ],
        call_to_action=frase(10, "cta"),
    )


def make_adapted(draft: ScriptDraft, words_per_scene: int = 19) -> AdaptedScript:
    """Adaptación válida: 134 palabras, misma numeración que el borrador."""
    return AdaptedScript(
        chapter_id=draft.chapter_id,
        adapted_title="Título adaptado juvenil de prueba",
        adapted_hook=frase(11, "hook"),
        adapted_scenes=[
            AdaptedScene(
                scene_number=s.scene_number,
                narration=frase(words_per_scene, f"ada{s.scene_number}"),
                on_screen_text="guiño juvenil",
            )
            for s in draft.scenes
        ],
        adapted_cta=frase(9, "accion"),
    )


def make_audit(
    approved: bool = True,
    score: Optional[int] = None,
    feedback: Optional[str] = None,
) -> QualityAudit:
    """Dictamen válido. Si approved=True el score debe ser >= 7 (se fuerza)."""
    hallazgos = []
    if not approved:
        hallazgos.append(
            AuditFinding(
                criterion="ritmo",
                severity="mayor",
                score=4,
                observation="Observación de prueba suficientemente extensa.",
                suggested_fix="Corrección concreta de prueba suficientemente extensa.",
            )
        )
    return QualityAudit(
        approved=approved,
        overall_score=score if score is not None else (9 if approved else 4),
        word_count_status="dentro_de_rango",
        pacing_verdict="El ritmo resulta ágil en todo el capítulo.",
        audience_fit_verdict="El registro encaja con el público objetivo.",
        continuity_violations=[],
        findings=hallazgos,
        correction_feedback=feedback
        or (
            "Resumen breve de por qué el guion aprueba la auditoría."
            if approved
            else "1. Corrige el ritmo del gancho inicial del guion."
        ),
    )


def make_package(
    draft: ScriptDraft, scene_numbers: Optional[List[int]] = None
) -> TechnicalPackage:
    numeros = (
        scene_numbers
        if scene_numbers is not None
        else [s.scene_number for s in draft.scenes]
    )
    return TechnicalPackage(
        chapter_id=draft.chapter_id,
        render_style="3D isometric tech style",
        visual_specs=[
            VisualAssetSpec(
                scene_number=n,
                image_prompt=(
                    "A clean isometric 3D render of a friendly robot teacher "
                    f"explaining data flows in a vertical neon lab for scene {n}, "
                    "soft studio lighting and pastel palette"
                ),
                negative_prompt="watermark, blurry, extra fingers, horizontal layout",
                composition="Vertical centered framing with subtle grid floor",
                motion_direction="Slow dolly in toward the subject while particles orbit",
                style_tags=["isometric", "neon", "vertical"],
            )
            for n in numeros
        ],
        audio_direction=AudioDirection(
            voice_style="Juvenil neutro latino",
            voice_direction_notes="Energía alta en el gancho, calma didáctica.",
            music_mood="electrónica suave",
            sfx_cues=["whoosh"],
        ),
        thumbnail_prompt=(
            "A vertical high CTR thumbnail with the mascot holding a glowing data core"
        ),
    )


def make_lore_entry(term: str = "modelo", chapter_id: str = "ch-01") -> LoreEntry:
    return LoreEntry(
        term=term,
        definition="Definición breve del término.",
        chapter_id=chapter_id,
        first_seen_title="Capítulo de origen",
        category="concepto",
    )


def make_project(**overrides) -> ProjectSpec:
    """Proyecto de referencia válido: el show educativo de 60 s."""
    datos = dict(
        project_id="sinnema",
        brand_name="Sinnema",
        show_concept="micro-videos educativos verticales de 60 segundos",
        default_topic=TEMA,
        language="Español neutro latinoamericano",
        audience=AUDIENCIA,
        cultural_context=CONTEXTO_CULTURAL,
        tone_of_voice="cómplice y energético, riguroso pero nunca académico seco",
        style_guide=GUIA_DE_ESTILO,
        constraints=RESTRICCIONES,
        visual_master_style=(
            "3D isometric render, vertical 9:16 framing, clean tech environment, "
            "soft studio lighting, pastel + neon accent palette"
        ),
        format=FormatProfile(),
    )
    datos.update(overrides)
    return ProjectSpec(**datos)


def make_request(
    num_chapters: int = 2,
    max_critique_attempts: int = 2,
    topic: Optional[str] = None,
    project: Optional[ProjectSpec] = None,
) -> SeriesRequest:
    return SeriesRequest(
        project=project or make_project(),
        topic=topic,
        num_chapters=num_chapters,
        max_critique_attempts=max_critique_attempts,
    )


# =========================================================================
# DOBLE DEL PUERTO LLM
# =========================================================================


class FakeGateway:
    """Doble en memoria de ``StructuredGenerationPort``.

    Guion por rol: cola de resultados; se consume uno por llamada y el último
    se repite (para reintentos del ciclo de crítica).
    """

    def __init__(self) -> None:
        self._guiones: Dict[str, List[Any]] = {}
        self.calls: List[str] = []

    def add(self, role: str, resultados: List[Any]) -> None:
        self._guiones.setdefault(role, []).extend(resultados)

    def generate(self, role: str, schema: Any, system_prompt: str, user_prompt: str) -> Any:
        self.calls.append(role)
        cola = self._guiones.get(role)
        if not cola:
            raise AssertionError(f"FakeGateway no tiene guion para el rol '{role}'.")
        return cola.pop(0) if len(cola) > 1 else cola[0]


def gateway_con_serie(
    num_chapters: int = 2,
    audits_por_capitulo: Optional[List[List[QualityAudit]]] = None,
) -> FakeGateway:
    """Gateway falso con una serie completa de N capítulos.

    Las colas son posicionales por rol. La secuencia de llamadas por capítulo
    es determinista: ``len(auditorías)`` llamadas a scriptwriter/adapter/critic
    (el ciclo de crítica re-invoca guionista y adaptador), 1 a continuity y 1 a
    technical_director (solo si el capítulo llega a producción). El último ítem
    de cada cola se repite si se hacen llamadas extra.
    """
    plan = make_plan(num_chapters)
    gw = FakeGateway()
    gw.add("planner", [plan])
    for i, capitulo in enumerate(plan.chapters):
        auditorias = (
            audits_por_capitulo[i]
            if audits_por_capitulo is not None
            else [make_audit(approved=True)]
        )
        draft = make_draft(capitulo.chapter_id)
        adapted = make_adapted(draft)
        gw.add("continuity", [make_directives(new_terms=(f"término nuevo {i + 1}",))])
        gw.add("scriptwriter", [draft] * len(auditorias))
        gw.add("adapter", [adapted] * len(auditorias))
        gw.add("critic", auditorias)
        gw.add("technical_director", [make_package(draft)])
    return gw


# =========================================================================
# FIXTURES
# =========================================================================


@pytest.fixture
def entorno_llm_limpio(monkeypatch):
    """Aísla el entorno de credenciales LLM y overrides por rol."""
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    for var in list(os.environ):
        if var.startswith(("LLM_PROVIDER_", "LLM_MODEL_")):
            monkeypatch.delenv(var, raising=False)
    return None

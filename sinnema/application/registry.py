"""Registro de agentes del pipeline: una definición por rol.

Consolida en un único lugar lo que antes vivía esparcido: la constante del
rol, su contrato de salida (esquema Pydantic), su módulo de prompts, el nombre
de su nodo del grafo, los slots del estado que lee/escribe y sus validadores
de dominio. Añadir un agente nuevo = una definición aquí + su módulo de
prompts + su contrato de dominio.

El ``tipo`` fija la semántica del nodo en la topología (fases del capítulo en
orden fijo; ver ``docs/spec-agentes-dinamicos.md`` §2.2):

    serie -> contexto -> escritor -> transformador* -> revisor -> enriquecedor*

El flujo por proyecto (Fase 1) compone con estos tipos; el TOML nunca redefine
la topología, solo elige y ordena agentes de código.

La garantía central se conserva: cada definición declara los validadores que
el nodo aplica sobre el artefacto generado ANTES de que circule por el estado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Type,
)

from pydantic import BaseModel

from sinnema.application.ports import (
    ROLE_ADAPTER,
    ROLE_CONTINUITY,
    ROLE_CRITIC,
    ROLE_DIRECTOR,
    ROLE_PLANNER,
    ROLE_SCRIPTWRITER,
    ROLE_SCHEMAS,
)
from sinnema.application.projects import AgentConfig, ProjectSpec
from sinnema.application.prompts import (
    adapter as adapter_prompts,
    continuity as continuity_prompts,
    critic as critic_prompts,
    director as director_prompts,
    planner as planner_prompts,
    scriptwriter as scriptwriter_prompts,
)
from sinnema.application.state import PipelineState
from sinnema.domain.models import (
    AdaptedScript,
    ContinuityDirectives,
    QualityAudit,
    ScriptDraft,
    SeriesPlan,
    TechnicalPackage,
)
from sinnema.domain.services import (
    identity_adaptation,
    validate_adaptation_format,
    validate_adaptation_matches_draft,
    validate_audit_verdict,
    validate_draft_format,
    validate_package_format,
    validate_package_matches_draft,
    validate_plan_format,
    validate_plan_size,
)
from sinnema.domain.text import count_words

#: Semántica de conexión del agente con la topología (fases del capítulo,
#: más el nivel de serie). Vocabulario cerrado: el TOML elige entre estos.
TipoAgente = Literal[
    "serie", "contexto", "escritor", "transformador", "revisor", "enriquecedor"
]

#: Firma de los ganchos declarativos de una definición.
MensajeBuilder = Callable[[ProjectSpec, PipelineState], str]
Validador = Callable[[BaseModel, ProjectSpec, PipelineState], None]
Actualizador = Callable[[BaseModel, PipelineState], Dict[str, Any]]
Resumen = Callable[[BaseModel, PipelineState], str]


class PromptModule(Protocol):
    """Contrato que cumple cada módulo de ``sinnema.application.prompts``."""

    def build_system_prompt(self, spec: ProjectSpec) -> str:
        ...

    def build_user_message(self, *args: Any, **kwargs: Any) -> str:
        ...


@dataclass(frozen=True)
class AgentDefinition:
    """Definición declarativa de un agente del pipeline.

    ``mensaje`` adapta la firma propia del módulo de prompts al contrato
    común ``(project, state) -> str``; ``validadores`` corre el chequeo de
    dominio post-generación (la garantía central); ``al_desactivar`` da el
    cortocircuito determinista cuando el proyecto apaga el rol (``None`` en
    roles sin deactivación: esenciales y la compuerta, cuya política vive en
    el nodo estructural del grafo); ``actualizacion_extra`` aporta las claves
    de estado adicionales que el nodo devuelve junto al artefacto.
    """

    rol: str
    tipo: TipoAgente
    esquema: Type[BaseModel]
    prompts: PromptModule
    nodo: str
    produce: str
    mensaje: MensajeBuilder
    consume: Tuple[str, ...] = ()
    validadores: Tuple[Validador, ...] = ()
    al_desactivar: Optional[Callable[[PipelineState], Dict[str, Any]]] = None
    resumen_desactivado: Optional[Callable[[PipelineState], str]] = None
    actualizacion_extra: Optional[Actualizador] = None
    resumen: Optional[Resumen] = None
    esencial: bool = False
    descripcion: str = ""


# ---------------------------------------------------------------------------
# Ayudantes de estado compartidos por los mensajes y resúmenes
# ---------------------------------------------------------------------------


def capitulo_actual(state: PipelineState):
    """Plan, capítulo en curso e índice desde el estado del grafo."""
    plan = state["series_plan"]
    indice = state.get("current_chapter_index", 0)
    if plan is None:
        raise RuntimeError("El plan de serie no está disponible en el estado.")
    return plan, plan.chapters[indice], indice


def _mensaje_planner(project: ProjectSpec, state: PipelineState) -> str:
    return planner_prompts.build_user_message(
        project, state["topic"], state.get("num_chapters", 3)
    )


def _mensaje_continuity(project: ProjectSpec, state: PipelineState) -> str:
    plan, capitulo, indice = capitulo_actual(state)
    previo = plan.chapters[indice - 1] if indice > 0 else None
    return continuity_prompts.build_user_message(
        chapter=capitulo,
        previous_chapter=previo,
        lore_entries=state.get("lore_entries", []),
        recurring_elements=plan.recurring_elements,
    )


def _mensaje_scriptwriter(project: ProjectSpec, state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    return scriptwriter_prompts.build_user_message(
        project,
        chapter=capitulo,
        directives=state["continuity_directives"],
        feedback=state.get("pending_feedback"),
    )


def _mensaje_adapter(project: ProjectSpec, state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    return adapter_prompts.build_user_message(
        project,
        draft=state["draft_script"],
        directives=state["continuity_directives"],
    )


def _mensaje_critic(project: ProjectSpec, state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    adaptado: AdaptedScript = state["adapted_script"]
    borrador: ScriptDraft = state["draft_script"]
    texto = " ".join(
        [adaptado.adapted_hook]
        + [s.narration for s in adaptado.adapted_scenes]
        + [adaptado.adapted_cta]
    )
    return critic_prompts.build_user_message(
        project,
        chapter=capitulo,
        draft=borrador,
        adapted=adaptado,
        directives=state["continuity_directives"],
        actual_word_count=count_words(texto),
    )


def _mensaje_director(project: ProjectSpec, state: PipelineState) -> str:
    plan, capitulo, _ = capitulo_actual(state)
    return director_prompts.build_user_message(
        project,
        chapter=capitulo,
        draft=state["draft_script"],
        adapted=state["adapted_script"],
        recurring_elements=plan.recurring_elements,
    )


# ---------------------------------------------------------------------------
# Ganchos por rol: validadores, cortocircuitos y actualizaciones extra
# ---------------------------------------------------------------------------


def _validar_adaptacion_coherente(
    adaptado: AdaptedScript, project: ProjectSpec, state: PipelineState
) -> None:
    validate_adaptation_matches_draft(state["draft_script"], adaptado)


def _validar_paquete_coherente(
    paquete: TechnicalPackage, project: ProjectSpec, state: PipelineState
) -> None:
    validate_package_matches_draft(state["draft_script"], paquete)


def _extras_scriptwriter(
    borrador: ScriptDraft, state: PipelineState
) -> Dict[str, Any]:
    return {"pending_feedback": None, "qa_verdict": None}


def _extras_critic(dictamen: QualityAudit, state: PipelineState) -> Dict[str, Any]:
    intentos = state.get("critique_attempts", 0) + 1
    return {
        "critique_attempts": intentos,
        "pending_feedback": (
            None if dictamen.approved else dictamen.correction_feedback
        ),
    }


def _extras_planner(plan: SeriesPlan, state: PipelineState) -> Dict[str, Any]:
    return {"current_chapter_index": 0, "critique_attempts": 0}


def _resumen_planner(plan: SeriesPlan, state: PipelineState) -> str:
    return f"Plan maestro '{plan.series_title}' con {len(plan.chapters)} capítulo(s)."


def _resumen_continuity(
    directivas: ContinuityDirectives, state: PipelineState
) -> str:
    _, capitulo, _ = capitulo_actual(state)
    return (
        f"Directivas de continuidad para {capitulo.chapter_id} "
        f"({len(directivas.new_terms_to_introduce)} término(s) nuevos)."
    )


def _resumen_scriptwriter(borrador: ScriptDraft, state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    return (
        f"Borrador de {borrador.chapter_id}: {borrador.word_count} palabras, "
        f"{borrador.total_duration_seconds:.1f} s "
        f"(intento de crítica #{state.get('critique_attempts', 0) + 1})."
    )


def _resumen_adapter(adaptado: AdaptedScript, state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    return (
        f"Guión de {capitulo.chapter_id} adaptado al público objetivo "
        f"({len(adaptado.adapted_scenes)} escenas conservadas)."
    )


def _resumen_critic(dictamen: QualityAudit, state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    veredicto = "APRUEBA" if dictamen.approved else "RECHAZA"
    return (
        f"QA {veredicto} {capitulo.chapter_id} "
        f"(score {dictamen.overall_score}/10, "
        f"intento {state.get('critique_attempts', 0)})."
    )


def _resumen_director(paquete: TechnicalPackage, state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    return (
        f"Paquete técnico de {capitulo.chapter_id}: "
        f"{len(paquete.visual_specs)} spec(s) visuales."
    )


def _desactivar_continuity(state: PipelineState) -> Dict[str, Any]:
    return {"continuity_directives": None}


def _desactivar_adapter(state: PipelineState) -> Dict[str, Any]:
    return {"adapted_script": identity_adaptation(state["draft_script"])}


def _desactivar_director(state: PipelineState) -> Dict[str, Any]:
    return {"technical_package": None}


def _resumen_desactivar_continuity(state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    return (
        f"Agente desactivado en el proyecto: {capitulo.chapter_id} "
        "avanza sin directivas de continuidad."
    )


def _resumen_desactivar_adapter(state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    return (
        f"Agente desactivado en el proyecto: el guion de "
        f"{capitulo.chapter_id} pasa tal cual (adaptación identidad)."
    )


def _resumen_desactivar_director(state: PipelineState) -> str:
    _, capitulo, _ = capitulo_actual(state)
    return (
        f"Agente desactivado en el proyecto: {capitulo.chapter_id} "
        "avanza sin paquete técnico."
    )


# ---------------------------------------------------------------------------
# Catálogo de agentes
# ---------------------------------------------------------------------------

AGENT_REGISTRY: Dict[str, AgentDefinition] = {
    ROLE_PLANNER: AgentDefinition(
        rol=ROLE_PLANNER,
        tipo="serie",
        esquema=SeriesPlan,
        prompts=planner_prompts,
        nodo="plan_series",
        produce="series_plan",
        mensaje=_mensaje_planner,
        consume=("topic", "num_chapters"),
        validadores=(
            lambda plan, project, state: validate_plan_size(
                plan, state.get("num_chapters", 3)
            ),
            lambda plan, project, state: validate_plan_format(
                plan, project.format
            ),
        ),
        actualizacion_extra=_extras_planner,
        resumen=_resumen_planner,
        esencial=True,
        descripcion="Strategic Planner (plan maestro)",
    ),
    ROLE_CONTINUITY: AgentDefinition(
        rol=ROLE_CONTINUITY,
        tipo="contexto",
        esquema=ContinuityDirectives,
        prompts=continuity_prompts,
        nodo="continuity_master",
        produce="continuity_directives",
        mensaje=_mensaje_continuity,
        consume=("series_plan", "current_chapter_index", "lore_entries"),
        al_desactivar=_desactivar_continuity,
        resumen_desactivado=_resumen_desactivar_continuity,
        resumen=_resumen_continuity,
        descripcion="Lore Keeper (directivas de continuidad)",
    ),
    ROLE_SCRIPTWRITER: AgentDefinition(
        rol=ROLE_SCRIPTWRITER,
        tipo="escritor",
        esquema=ScriptDraft,
        prompts=scriptwriter_prompts,
        nodo="scriptwriter",
        produce="draft_script",
        mensaje=_mensaje_scriptwriter,
        consume=(
            "series_plan", "current_chapter_index",
            "continuity_directives", "pending_feedback",
        ),
        validadores=(
            lambda draft, project, state: validate_draft_format(
                draft, project.format
            ),
        ),
        actualizacion_extra=_extras_scriptwriter,
        resumen=_resumen_scriptwriter,
        esencial=True,
        descripcion="Content Creator (borrador)",
    ),
    ROLE_ADAPTER: AgentDefinition(
        rol=ROLE_ADAPTER,
        tipo="transformador",
        esquema=AdaptedScript,
        prompts=adapter_prompts,
        nodo="persona_adapter",
        produce="adapted_script",
        mensaje=_mensaje_adapter,
        consume=(
            "series_plan", "current_chapter_index",
            "draft_script", "continuity_directives",
        ),
        validadores=(_validar_adaptacion_coherente,
                     lambda art, project, state: validate_adaptation_format(
                         art, project.format)),
        al_desactivar=_desactivar_adapter,
        resumen_desactivado=_resumen_desactivar_adapter,
        resumen=_resumen_adapter,
        descripcion="Audience Adapter (adaptación al público)",
    ),
    ROLE_CRITIC: AgentDefinition(
        rol=ROLE_CRITIC,
        tipo="revisor",
        esquema=QualityAudit,
        prompts=critic_prompts,
        nodo="chief_critic",
        produce="qa_verdict",
        mensaje=_mensaje_critic,
        consume=(
            "series_plan", "current_chapter_index",
            "draft_script", "adapted_script", "continuity_directives",
        ),
        validadores=(
            lambda dictamen, project, state: validate_audit_verdict(
                dictamen, project.format
            ),
        ),
        actualizacion_extra=_extras_critic,
        resumen=_resumen_critic,
        descripcion="Auditor (dictamen de calidad)",
    ),
    ROLE_DIRECTOR: AgentDefinition(
        rol=ROLE_DIRECTOR,
        tipo="enriquecedor",
        esquema=TechnicalPackage,
        prompts=director_prompts,
        nodo="technical_director",
        produce="technical_package",
        mensaje=_mensaje_director,
        consume=(
            "series_plan", "current_chapter_index",
            "draft_script", "adapted_script",
        ),
        validadores=(_validar_paquete_coherente,
                     lambda art, project, state: validate_package_format(
                         art, project.format)),
        al_desactivar=_desactivar_director,
        resumen_desactivado=_resumen_desactivar_director,
        resumen=_resumen_director,
        descripcion="Visual/Audio Director (paquete técnico)",
    ),
}


def _validar_registro() -> None:
    """Detecta wiring erróneo del catálogo en el arranque, no en plena corrida."""
    if set(AGENT_REGISTRY) != set(ROLE_SCHEMAS):
        raise RuntimeError(
            "El registro de agentes y ROLE_SCHEMAS discrepan: "
            f"registro={sorted(AGENT_REGISTRY)} schemas={sorted(ROLE_SCHEMAS)}."
        )
    for rol, definicion in AGENT_REGISTRY.items():
        if definicion.esquema is not ROLE_SCHEMAS[rol]:
            raise RuntimeError(
                f"El rol '{rol}' declara el esquema "
                f"'{definicion.esquema.__name__}' pero ROLE_SCHEMAS asocia "
                f"'{ROLE_SCHEMAS[rol].__name__}': wiring erróneo."
            )


_validar_registro()


# ---------------------------------------------------------------------------
# Consultas sobre el catálogo
# ---------------------------------------------------------------------------


def definicion(rol: str) -> AgentDefinition:
    """Definición del rol; error accionable si no existe en el registro."""
    try:
        return AGENT_REGISTRY[rol]
    except KeyError:
        raise KeyError(
            f"El rol '{rol}' no está en el registro de agentes "
            f"(válidos: {', '.join(sorted(AGENT_REGISTRY))})."
        ) from None


def roles_de_tipo(tipo: TipoAgente) -> List[str]:
    """Roles del registro con ese tipo, en orden de declaración."""
    return [rol for rol, d in AGENT_REGISTRY.items() if d.tipo == tipo]


# ---------------------------------------------------------------------------
# Prompts del sistema por rol (fuente única; prompts/__init__ delega aquí)
# ---------------------------------------------------------------------------


def _con_reglas(prompt_base: str, config: AgentConfig) -> str:
    """Apenda las reglas del proyecto al prompt del sistema de un rol."""
    if not config.reglas:
        return prompt_base
    reglas = "\n".join(f"- {r}" for r in config.reglas)
    return (
        f"{prompt_base}\n\n"
        "REGLAS ADICIONALES DEL PROYECTO (si conflitan con lo anterior, "
        f"prevalecen):\n{reglas}"
    )


def build_role_system_prompts(spec: ProjectSpec) -> Dict[str, str]:
    """System prompt de cada rol para un proyecto, indexado por rol.

    Cada prompt base del rol se compone con el ``ProjectSpec`` y luego recibe
    las ``reglas`` declaradas en ``[agentes.<rol>]`` del proyecto, si las hay.
    """
    prompts: Dict[str, str] = {}
    for rol, definicion_rol in AGENT_REGISTRY.items():
        base = definicion_rol.prompts.build_system_prompt(spec)
        prompts[rol] = _con_reglas(base, spec.config_de_agente(rol))
    return prompts

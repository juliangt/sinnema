"""Definición de proyecto (show): la unidad de reutilización del motor.

Un proyecto concentra toda la política editorial que antes vivía hardcodeada
en prompts, contratos y CLI: identidad, concepto, voz, idioma, estilo visual y
el sobre editorial numérico (``FormatProfile``). Vive en un archivo TOML que
carga la infraestructura y llega al pipeline como este objeto validado.

Desde la gestión web, cada proyecto además configura sus agentes (sección
``[agentes.<rol>]``: reglas, proveedor/modelo/temperatura y activación) y la
política del pipeline (sección ``[pipeline]``). Ambas son opcionales.

El mapeo ``project_from_dict`` es puro (sin I/O): la infraestructura se ocupa
de leer el archivo; la aplicación, de decir qué significa un proyecto válido.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sinnema.application.ports import (
    ROLE_ADAPTER,
    ROLE_CONTINUITY,
    ROLE_CRITIC,
    ROLE_DIRECTOR,
    ROLE_PLANNER,
    ROLE_SCRIPTWRITER,
)
from sinnema.application.tools import TOOLS_INTEGRADAS
from sinnema.domain.constants import (
    ALCANCE_COMPUERTA,
    ALCANCE_DEFAULT,
    ALCANCES,
)
from sinnema.domain.models import FormatProfile

#: Un id de proyecto es un slug estable: nombra carpetas de salida y lore.
PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PROJECT_ID_MAX_CHARS = 30

TOPIC_MIN_CHARS = 8
TOPIC_MAX_CHARS = 200

_VISUAL_MASTER_STYLE_MIN_CHARS = 40

#: Roles configurables en ``[agentes.<rol>]`` y los que no se pueden apagar:
#: sin plan ni borrador no hay serie; el resto del pipeline puede cortocircuitarse.
ROLES_CONFIGURABLES: Tuple[str, ...] = (
    ROLE_PLANNER, ROLE_CONTINUITY, ROLE_SCRIPTWRITER,
    ROLE_ADAPTER, ROLE_CRITIC, ROLE_DIRECTOR,
)
ROLES_ESENCIALES = frozenset({ROLE_PLANNER, ROLE_SCRIPTWRITER})

#: Proveedores LLM válidos para el override por agente (los mismos que resuelve
#: el adaptador de infraestructura; aquí solo se valida el nombre).
PROVEEDORES_VALIDOS = frozenset({"anthropic", "openai", "google", "ollama"})

#: Valores en español de ``politica_al_agotar`` -> literal interno del pipeline.
POLITICAS_DE_AGOTAMIENTO = {
    "aceptar_forzado": "force_accept",
    "saltar_capitulo": "skip_chapter",
}

TEMPERATURA_MIN = 0.0
TEMPERATURA_MAX = 2.0

#: Rango de ``top_p`` (nucleus sampling): ausente = default del proveedor.
TOP_P_MIN = 0.0
TOP_P_MAX = 1.0

#: Proveedores de imagen válidos para ``[media].proveedor_imagen`` (spec §4.3).
#: El default (sin clave en el TOML) lo resuelve el entorno (MEDIA_PROVIDER).
PROVEEDORES_DE_IMAGEN = ("gemini", "openai")
INTENTOS_QA_MAX = 5

# --- Agentes custom (declarados 100% en el TOML; spec-agentes-dinamicos §8) ----
#: Tipos permitidos para un agente custom: la compuerta (revisor) y las fases
#: periféricas. ``escritor``/``transformador`` exigen contratos de guion
#: tipados y se quedan en código.
TIPOS_CUSTOM = ("contexto", "enriquecedor", "revisor")
#: Contratos genéricos de salida; el revisor EXIGE el dictamen de dominio
#: (``QualityAudit``): la compuerta depende de esa semántica.
CONTRATO_REVISOR = "dictamen"
CONTRATOS_POR_TIPO = {
    "contexto": ("notas", "texto"),
    "enriquecedor": ("notas", "texto"),
    "revisor": (CONTRATO_REVISOR,),
}
CONTRATOS_VALIDOS = frozenset({"notas", "texto", CONTRATO_REVISOR})
INSTRUCCIONES_MAX_CHARS = 2000

#: Placeholders que ``instrucciones`` puede usar (se renderizan con el spec).
PLACEHOLDERS_INSTRUCCIONES = frozenset(
    {"marca", "concepto", "tema", "idioma", "audiencia", "tono",
     "contexto_cultural", "guia_de_estilo", "restricciones", "estilo_maestro"}
)
_PLACEHOLDER_PATTERN = re.compile(r"\{([a-z_]+)\}")


def _problemas_de_custom(rol: str, config: "AgentConfig") -> List[str]:
    """Problemas de SEMÁNTICA de un agente custom (§9.7-10 de la spec).

    La forma cruda (tipos/claves TOML) la valida ``_mapear_agentes``; aquí se
    chequea la coherencia de la configuración ya parseada. El catálogo de
    entradas vive en el registro (import diferido, mismo motivo que en
    ``FlowSpec.validar``).
    """
    problemas: List[str] = []
    assert config.tipo is not None  # solo se llama con customs

    if not ROL_CUSTOM_PATTERN.match(rol) or len(rol) > ROL_CUSTOM_MAX_CHARS:
        problemas.append(
            f"el rol custom '{rol}' debe ser un slug de hasta "
            f"{ROL_CUSTOM_MAX_CHARS} caracteres ([a-z0-9_], empieza con letra)."
        )
    if config.contrato is None:
        problemas.append(
            f"el agente custom '{rol}' exige 'contrato' "
            f"({', '.join(sorted(CONTRATOS_VALIDOS))})."
        )
    elif config.contrato not in CONTRATOS_POR_TIPO[config.tipo]:
        problemas.append(
            f"el contrato '{config.contrato}' no es válido para un agente custom "
            f"de tipo '{config.tipo}' (permitidos: "
            f"{', '.join(CONTRATOS_POR_TIPO[config.tipo])}); un 'revisor' exige "
            f"el contrato '{CONTRATO_REVISOR}' (la compuerta depende de esa "
            "semántica)."
        )
    if config.instrucciones is None or not config.instrucciones.strip():
        problemas.append(
            f"el agente custom '{rol}' exige 'instrucciones': su prompt base "
            "puede usar placeholders como {marca} o {audiencia}."
        )
    else:
        if len(config.instrucciones) > INSTRUCCIONES_MAX_CHARS:
            problemas.append(
                f"'instrucciones' del agente custom '{rol}' no puede superar "
                f"{INSTRUCCIONES_MAX_CHARS} caracteres "
                f"(recibidos: {len(config.instrucciones)})."
            )
        desconocidos = sorted(
            {
                nombre
                for nombre in _PLACEHOLDER_PATTERN.findall(config.instrucciones)
                if nombre not in PLACEHOLDERS_INSTRUCCIONES
            }
        )
        if desconocidos:
            problemas.append(
                f"'instrucciones' del agente custom '{rol}' usa placeholders "
                f"desconocidos: {', '.join(desconocidos)} (válidos: "
                f"{', '.join(sorted(PLACEHOLDERS_INSTRUCCIONES))})."
            )
    if not config.entradas:
        problemas.append(
            f"el agente custom '{rol}' exige 'entradas': los bloques del estado "
            "que recibe en su mensaje (p. ej. [\"capitulo\", \"lore\"])."
        )
    else:
        from sinnema.application.registry import CATALOGO_ENTRADAS

        fuera_de_catalogo = [
            entrada for entrada in config.entradas if entrada not in CATALOGO_ENTRADAS
        ]
        if fuera_de_catalogo:
            problemas.append(
                f"'entradas' del agente custom '{rol}' fuera del catálogo: "
                f"{', '.join(fuera_de_catalogo)} "
                f"(válidas: {', '.join(sorted(CATALOGO_ENTRADAS))})."
            )
    return problemas


@dataclass(frozen=True)
class AgentConfig:
    """Configuración de un agente (rol) dentro de un proyecto.

    Todo opcional y ``None``/vacío significa "usa el default global". Las
    ``reglas`` se apendan al final del prompt del sistema del rol; la
    precedencia de proveedor/modelo/temperatura es proyecto > entorno > default.
    ``top_p``/``max_tokens`` ausentes no se pasan al constructor del proveedor
    (rige su default); ``tools`` habilita tools integradas para el rol
    (``[]`` = sin tools, comportamiento actual).

    Un agente CUSTOM se declara con ``tipo`` (contexto | enriquecedor |
    revisor): exige ``instrucciones`` (su prompt base), ``contrato`` (salida
    genérica: notas | texto | dictamen) y ``entradas`` (bloques del estado que
    recibe en el mensaje). Los roles del registro ignoran estos campos.
    """

    activo: bool = True
    reglas: Tuple[str, ...] = ()
    proveedor: Optional[str] = None
    modelo: Optional[str] = None
    temperatura: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    tools: Tuple[str, ...] = ()
    #: La presencia de ``tipo`` convierte al rol en custom (fuera del registro).
    tipo: Optional[str] = None
    contrato: Optional[str] = None
    entradas: Tuple[str, ...] = ()
    instrucciones: Optional[str] = None

    def __post_init__(self) -> None:
        if self.temperatura is not None and not (
            TEMPERATURA_MIN <= self.temperatura <= TEMPERATURA_MAX
        ):
            raise ValueError(
                f"temperatura debe estar entre {TEMPERATURA_MIN} y "
                f"{TEMPERATURA_MAX} (recibida: {self.temperatura})."
            )
        if self.proveedor is not None and self.proveedor not in PROVEEDORES_VALIDOS:
            validos = ", ".join(sorted(PROVEEDORES_VALIDOS))
            raise ValueError(
                f"proveedor debe ser uno de: {validos} (recibido: '{self.proveedor}')."
            )
        if self.top_p is not None and not (TOP_P_MIN <= self.top_p <= TOP_P_MAX):
            raise ValueError(
                f"top_p debe estar entre {TOP_P_MIN} y {TOP_P_MAX} "
                f"(recibido: {self.top_p})."
            )
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError(
                f"max_tokens debe ser mayor que 0 (recibido: {self.max_tokens})."
            )
        desconocidas = [t for t in self.tools if t not in TOOLS_INTEGRADAS]
        if desconocidas:
            raise ValueError(
                f"tools desconocidas: {', '.join(desconocidas)} "
                f"(integradas: {', '.join(sorted(TOOLS_INTEGRADAS))})."
            )

    @property
    def es_custom(self) -> bool:
        return self.tipo is not None


@dataclass(frozen=True)
class PipelineConfig:
    """Política del pipeline declarada por el proyecto (sección [pipeline]).

    ``None`` en ambos campos = sin preferencia: rigen los defaults de corrida
    (``max_critique_attempts`` del request) y de ``PipelineSettings``.
    """

    intentos_maximos_de_critica: Optional[int] = None
    #: Literal interno: "force_accept" | "skip_chapter" (ver POLITICAS_DE_AGOTAMIENTO).
    politica_al_agotar: Optional[str] = None

    def __post_init__(self) -> None:
        if self.intentos_maximos_de_critica is not None and not (
            1 <= self.intentos_maximos_de_critica <= 5
        ):
            raise ValueError(
                "intentos_maximos_de_critica debe estar entre 1 y 5 "
                f"(recibido: {self.intentos_maximos_de_critica})."
            )
        if self.politica_al_agotar is not None and self.politica_al_agotar not in (
            "force_accept",
            "skip_chapter",
        ):
            raise ValueError(
                "politica_al_agotar debe ser 'aceptar_forzado' o 'saltar_capitulo' "
                f"(recibido: '{self.politica_al_agotar}')."
            )


@dataclass(frozen=True)
class MediaConfig:
    """Política de la capa de media declarada por el proyecto (sección [media],
    spec-recursos-ancla §4.3). TODO OPCIONAL: sin sección, todo default-off y
    la corrida es idéntica a la de siempre (paridad §1).

    ``proveedor_imagen`` ``None`` = sin preferencia: rige el entorno
    (``MEDIA_PROVIDER``, default ``gemini``). ``intentos_qa`` lo consume la
    Fase 4 (bucle de regeneración ante QA fallido); aquí solo se parsea.
    """

    keyframes: bool = False
    video: bool = False
    encadenar_frames: bool = True
    proveedor_imagen: Optional[str] = None
    intentos_qa: int = 1

    def __post_init__(self) -> None:
        if self.proveedor_imagen is not None and self.proveedor_imagen not in PROVEEDORES_DE_IMAGEN:
            validos = ", ".join(PROVEEDORES_DE_IMAGEN)
            raise ValueError(
                f"proveedor_imagen debe ser uno de: {validos} "
                f"(recibido: '{self.proveedor_imagen}')."
            )
        if not 0 <= self.intentos_qa <= INTENTOS_QA_MAX:
            raise ValueError(
                f"intentos_qa debe estar entre 0 y {INTENTOS_QA_MAX} "
                f"(recibido: {self.intentos_qa})."
            )


@dataclass(frozen=True)
class FlowSpec:
    """Flujo del pipeline declarado por el proyecto (sección opcional ``[flujo]``).

    Composición por fases del capítulo (ver ``registry.TipoAgente``): qué roles
    participan y en qué orden, más el ``hasta``: el último hito del pipeline
    que la corrida alcanza (``ALCANCES``, default ``produccion``). Sin sección
    ``[flujo]`` el proyecto no declara nada (``ProjectSpec.flujo is None``) y
    ``resolver_flujo`` reconstruye la topología legacy: los seis roles, donde
    ``activo = false`` conserva su cortocircuito.

    Los roles estructurales (``planner``, ``scriptwriter``) nunca se listan:
    siempre participan y sus nodos son del builder, no de estas fases.
    """

    contexto: Tuple[str, ...] = ()
    transformaciones: Tuple[str, ...] = ()
    #: Rol compuerta (tipo ``revisor``); ``None`` = aprobación directa.
    revisor: Optional[str] = None
    enriquecimiento: Tuple[str, ...] = ()
    hasta: str = ALCANCE_DEFAULT
    #: False en el flujo implícito legacy (reconstruido sin sección ``[flujo]``):
    #: allí la participación la decide ``activo``, no la lista.
    declarado: bool = True

    def validar(self, agentes: Mapping[str, "AgentConfig"]) -> List[str]:
        """Devuelve TODOS los problemas de composición y alcance del flujo.

        Acepta roles custom: los ``[agentes.<rol>]`` que declaran ``tipo``
        son roles conocidos con ese tipo (la validez de su configuración la
        chequea ``ProjectSpec.validate``).
        """
        problemas: List[str] = []
        # Import diferido: el registro importa este módulo (ciclo registry ->
        # prompts -> projects); en tiempo de llamada ya está construido.
        from sinnema.application.registry import AGENT_REGISTRY

        tipos_extra = {
            rol: config.tipo
            for rol, config in agentes.items()
            if config.es_custom
        }

        def _tipo_de(rol: str) -> Optional[str]:
            definicion = AGENT_REGISTRY.get(rol)
            if definicion is not None:
                return definicion.tipo
            return tipos_extra.get(rol)

        fases = (
            ("contexto", "contexto", self.contexto),
            ("transformaciones", "transformador", self.transformaciones),
            ("enriquecimiento", "enriquecedor", self.enriquecimiento),
        )
        listados: List[str] = []
        for fase, tipo, roles in fases:
            for rol in roles:
                tipo_rol = _tipo_de(rol)
                if tipo_rol is None:
                    problemas.append(
                        f"rol desconocido '{rol}' en '{fase}' de [flujo] "
                        f"(roles del registro: {', '.join(sorted(AGENT_REGISTRY))}; "
                        "o decláralo como custom en [agentes.<rol>] con su 'tipo')."
                    )
                    continue
                if rol in ROLES_ESENCIALES:
                    problemas.append(
                        f"el rol '{rol}' es estructural y no se lista en [flujo]: "
                        "siempre participa del pipeline."
                    )
                    continue
                if tipo_rol != tipo:
                    problemas.append(
                        f"el rol '{rol}' es de tipo '{tipo_rol}' y no puede "
                        f"ir en la fase '{fase}' de [flujo]."
                    )
                if rol in listados:
                    problemas.append(
                        f"el rol '{rol}' está repetido en [flujo]: un rol aparece "
                        "una sola vez en todo el flujo."
                    )
                listados.append(rol)
        if self.revisor is not None:
            tipo_revisor = _tipo_de(self.revisor)
            if tipo_revisor is None:
                problemas.append(
                    f"rol desconocido '{self.revisor}' en 'revisor' de [flujo] "
                    f"(roles del registro: {', '.join(sorted(AGENT_REGISTRY))}; "
                    "o decláralo como custom en [agentes.<rol>] con su 'tipo')."
                )
            elif self.revisor in ROLES_ESENCIALES:
                problemas.append(
                    f"el rol '{self.revisor}' es estructural y no se lista en "
                    "[flujo]: siempre participa del pipeline."
                )
            elif tipo_revisor != "revisor":
                problemas.append(
                    f"el rol '{self.revisor}' es de tipo '{tipo_revisor}' y no "
                    "puede hacer de 'revisor' en [flujo]."
                )
            elif self.revisor in listados:
                problemas.append(
                    f"el rol '{self.revisor}' está repetido en [flujo]: un rol "
                    "aparece una sola vez en todo el flujo."
                )
            listados.append(self.revisor)

        # Con [flujo] la lista es la fuente de verdad: apagar un rol listado
        # es contradicción (error accionable); en los no listados se ignora.
        for rol in listados:
            config = agentes.get(rol)
            if config is not None and not config.activo:
                problemas.append(
                    f"el rol '{rol}' tiene activo = false pero está listado en "
                    "[flujo]: quítalo del flujo (con [flujo], la lista manda)."
                )

        problemas.extend(self.validar_alcance())
        return problemas

    def validar_alcance(self) -> List[str]:
        """Coherencia del ``hasta`` con el vocabulario y con la compuerta."""
        problemas: List[str] = []
        if self.hasta not in ALCANCES:
            problemas.append(
                f"'hasta' en [flujo] debe ser uno de: {', '.join(ALCANCES)} "
                f"(default: '{ALCANCE_DEFAULT}'; recibido: '{self.hasta}')."
            )
        elif (
            ALCANCES.index(self.hasta) >= ALCANCES.index(ALCANCE_COMPUERTA)
            and self.revisor is None
        ):
            problemas.append(
                f"el hito '{self.hasta}' exige declarar un 'revisor' en [flujo]: "
                "los capítulos descartados solo pueden surgir de la compuerta "
                "de calidad."
            )
        return problemas

    def truncado(self) -> "FlowSpec":
        """El mismo flujo cortado en el hito ``hasta``: el flujo EFECTIVO.

        Los roles declarados por encima del hito no corren (permitido: el flujo
        puede declararse completo y compartirse entre shows). ``guion_final``
        con cero transformaciones es válido (equivale a ``guion``).
        """
        if self.hasta not in ALCANCES:
            return self  # hito inválido: ya se reporta en validar()
        corte = ALCANCES.index(self.hasta)
        return FlowSpec(
            contexto=self.contexto if corte >= ALCANCES.index("guion") else (),
            transformaciones=(
                self.transformaciones if corte >= ALCANCES.index("guion_final") else ()
            ),
            revisor=self.revisor if corte >= ALCANCES.index("auditado") else None,
            enriquecimiento=(
                self.enriquecimiento if corte >= ALCANCES.index("produccion") else ()
            ),
            hasta=self.hasta,
            declarado=self.declarado,
        )

    def roles_completos(self) -> Tuple[str, ...]:
        """Todos los roles que el flujo efectivo pone a trabajar, en orden.

        Incluye los estructurales (``planner``, ``scriptwriter``) salvo cuando
        el hito ``plan`` corta antes de escribir guiones: allí solo el planner
        necesita agente.
        """
        if self.hasta == "plan":
            return (ROLE_PLANNER,)
        roles = [ROLE_PLANNER, *self.contexto, ROLE_SCRIPTWRITER, *self.transformaciones]
        if self.revisor is not None:
            roles.append(self.revisor)
        roles.extend(self.enriquecimiento)
        return tuple(roles)

    def cadena(self) -> str:
        """Los pasos del flujo efectivo en orden, para auditoría y previews."""
        if self.hasta == "plan":
            return "plan_series (sin bucle de capítulos)"
        pasos = [*self.contexto, ROLE_SCRIPTWRITER, *self.transformaciones]
        if self.revisor is not None:
            pasos.append(self.revisor)
        pasos.extend(self.enriquecimiento)
        pasos.append("commit_episode")
        return " -> ".join(pasos)


def resolver_flujo(project: "ProjectSpec") -> FlowSpec:
    """Flujo efectivo de un proyecto: fases truncadas por el hito.

    Sin sección ``[flujo]`` reconstruye la topología legacy (los seis roles en
    el orden histórico): los nodos existen para todos y el cortocircuito por
    ``activo = false`` queda dentro de cada nodo, igual que siempre.
    """
    if project.flujo is None:
        return FlowSpec(
            contexto=(ROLE_CONTINUITY,),
            transformaciones=(ROLE_ADAPTER,),
            revisor=ROLE_CRITIC,
            enriquecimiento=(ROLE_DIRECTOR,),
            hasta=ALCANCE_DEFAULT,
            declarado=False,
        )
    return project.flujo.truncado()


def con_hasta(project: "ProjectSpec", hasta: str) -> "ProjectSpec":
    """Proyecto con el hito sobrescrito para una corrida (CLI ``--hasta``).

    Precedencia: flag > proyecto > default. Un hito por debajo del declarado
    trunca el flujo; por encima, exige que el flujo provea lo que el hito
    necesita (p. ej. ``auditado`` sin revisor es un error accionable).
    """
    if hasta not in ALCANCES:
        raise ValueError(
            f"'hasta' debe ser uno de: {', '.join(ALCANCES)} "
            f"(default: '{ALCANCE_DEFAULT}'; recibido: '{hasta}')."
        )
    declarado = project.flujo if project.flujo is not None else FlowSpec(
        contexto=(ROLE_CONTINUITY,),
        transformaciones=(ROLE_ADAPTER,),
        revisor=ROLE_CRITIC,
        enriquecimiento=(ROLE_DIRECTOR,),
        declarado=False,
    )
    nuevo = replace(declarado, hasta=hasta)
    problemas = nuevo.validar_alcance()
    if problemas:
        raise ValueError(
            f"--hasta '{hasta}' incompatible con el flujo del proyecto: "
            + " | ".join(problemas)
        )
    return replace(project, flujo=nuevo)


@dataclass(frozen=True)
class ProjectSpec:
    """Configuración completa de un show: todo lo que varía entre proyectos."""

    project_id: str
    brand_name: str
    show_concept: str
    default_topic: str
    language: str
    audience: str
    cultural_context: str
    tone_of_voice: str
    style_guide: str
    constraints: str
    visual_master_style: str
    format: FormatProfile
    agentes: Mapping[str, AgentConfig] = field(default_factory=dict)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    #: Flujo declarado por el proyecto (sección [flujo]); ``None`` = sin sección:
    #: ``resolver_flujo`` aplica la semántica legacy (los 6 roles menos los
    #: ``activo = false``, que conservan su cortocircuito).
    flujo: Optional[FlowSpec] = None
    #: Participación de la biblioteca de recursos ancla (clave ``anclas`` de
    #: ``[visual]``, spec-recursos-ancla §4.3): ``false`` la ignora por
    #: completo; default ``true`` (participación automática si hay lockeadas).
    anclas: bool = True
    #: Política de la capa de media (sección opcional ``[media]``, §4.3/§6):
    #: sin sección, todo default-off y la corrida es la de siempre.
    media: MediaConfig = field(default_factory=MediaConfig)

    def config_de_agente(self, rol: str) -> AgentConfig:
        """Config del rol para este proyecto (vacía si no se declaró nada)."""
        return self.agentes.get(rol, AgentConfig())

    def agente_activo(self, rol: str) -> bool:
        return self.config_de_agente(rol).activo

    def validate(self) -> None:
        """Valida todos los campos y reporta TODOS los problemas de una vez."""
        problemas: List[str] = []

        if (
            not self.project_id
            or len(self.project_id) > PROJECT_ID_MAX_CHARS
            or not PROJECT_ID_PATTERN.match(self.project_id)
        ):
            problemas.append(
                f"project_id debe ser un slug de hasta {PROJECT_ID_MAX_CHARS} "
                f"caracteres ([a-z0-9-], recibido: '{self.project_id}')."
            )

        for campo, valor, minimo in (
            ("brand_name", self.brand_name, 2),
            ("show_concept", self.show_concept, 10),
            ("language", self.language, 3),
            ("audience", self.audience, 5),
            ("cultural_context", self.cultural_context, 5),
            ("tone_of_voice", self.tone_of_voice, 5),
            ("style_guide", self.style_guide, 5),
            ("constraints", self.constraints, 5),
        ):
            if not valor or len(valor.strip()) < minimo:
                problemas.append(
                    f"El campo '{campo}' no puede estar vacío ni tener menos de "
                    f"{minimo} caracteres."
                )

        tema = self.default_topic.strip()
        if len(tema) < TOPIC_MIN_CHARS:
            problemas.append(
                f"El tema por defecto debe tener al menos {TOPIC_MIN_CHARS} "
                f"caracteres (recibido: '{tema}')."
            )
        elif len(tema) > TOPIC_MAX_CHARS:
            problemas.append(
                f"El tema por defecto no puede superar {TOPIC_MAX_CHARS} "
                f"caracteres (recibido: {len(tema)})."
            )

        if len(self.visual_master_style.strip()) < _VISUAL_MASTER_STYLE_MIN_CHARS:
            problemas.append(
                "El campo 'visual_master_style' debe describir el estilo visual "
                f"maestro en inglés (mínimo {_VISUAL_MASTER_STYLE_MIN_CHARS} caracteres)."
            )

        if not isinstance(self.anclas, bool):
            problemas.append(
                "'anclas' en [visual] debe ser booleano (true por defecto; "
                f"recibido: '{self.anclas}')."
            )

        for rol in sorted(ROLES_ESENCIALES & set(self.agentes)):
            if not self.agentes[rol].activo:
                problemas.append(
                    f"El rol '{rol}' no se puede desactivar: es estructural del "
                    "pipeline (sin él no hay serie)."
                )

        # Agentes custom: semántica de tipo/contrato/instrucciones/entradas
        # (§9.7-10 de la spec) y su participación en el flujo declarado.
        customs = {rol: cfg for rol, cfg in self.agentes.items() if cfg.es_custom}
        for rol, config in sorted(customs.items()):
            problemas.extend(_problemas_de_custom(rol, config))
        if customs and self.flujo is None:
            problemas.append(
                "hay agentes custom declarados en [agentes] pero el proyecto no "
                "declara [flujo]: un agente custom solo corre listado en un "
                "[flujo] (añade la sección o conviértelo en agente de código)."
            )
        if customs and self.flujo is not None:
            listados = set(self.flujo.roles_completos())
            for rol in sorted(customs):
                if rol not in listados:
                    problemas.append(
                        f"el agente custom '{rol}' no está listado en [flujo]: "
                        "un agente que no participa no tiene efecto (añádelo a "
                        "una fase o elimina su sección)."
                    )

        if self.flujo is not None:
            problemas.extend(self.flujo.validar(self.agentes))

        if problemas:
            raise ValueError(
                f"Proyecto '{self.project_id or '?'}' inválido: "
                + " | ".join(problemas)
            )


# ---------------------------------------------------------------------------
# Mapeo dict (TOML) -> ProjectSpec
# ---------------------------------------------------------------------------

#: Claves esperadas por sección del archivo de proyecto (en español).
_SECCION_PROYECTO = {
    "id": "project_id",
    "marca": "brand_name",
    "concepto": "show_concept",
    "tema_por_defecto": "default_topic",
    "idioma": "language",
}
_SECCION_VOZ = {
    "audiencia": "audience",
    "contexto_cultural": "cultural_context",
    "tono": "tone_of_voice",
    "guia_de_estilo": "style_guide",
    "restricciones": "constraints",
}
_SECCION_VISUAL = {"estilo_maestro": "visual_master_style"}
_SECCION_FORMATO = {
    "relacion_de_aspecto": "aspect_ratio",
    "palabras_objetivo": "narration_target_words",
    "palabras_duras": "narration_hard_words",
    "escenas": "scenes_count",
    "duracion_escena_segundos": "scene_duration_seconds",
    "duracion_total_objetivo_segundos": "total_duration_target_seconds",
    "duracion_total_dura_segundos": "total_duration_hard_seconds",
    "palabras_por_escena_max": "narration_max_words_per_scene",
    "texto_en_pantalla_max_palabras": "on_screen_text_max_words",
    "score_minimo_aprobacion": "min_approval_score",
}


def _mapear_seccion(
    datos: Dict[str, Any],
    seccion: str,
    claves: Dict[str, str],
    problemas: List[str],
    requerida: bool,
) -> Dict[str, Any]:
    contenido = datos.get(seccion)
    if contenido is None:
        if requerida:
            problemas.append(f"falta la sección [{seccion}]")
        return {}
    if not isinstance(contenido, dict):
        problemas.append(f"la sección [{seccion}] debe ser una tabla TOML")
        return {}
    for clave in claves:
        if requerida and clave not in contenido:
            problemas.append(f"falta la clave '{clave}' en [{seccion}]")
    return {claves[k]: v for k, v in contenido.items() if k in claves}


_CLAVES_AGENTE = frozenset(
    {"activo", "reglas", "proveedor", "modelo", "temperatura", "top_p",
     "max_tokens", "tools", "tipo", "contrato", "entradas", "instrucciones"}
)

#: Un rol custom es un slug nuevo (nombra su nodo del grafo y el sufijo de
#: sus variables de entorno LLM_PROVIDER_<ROL>).
ROL_CUSTOM_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
ROL_CUSTOM_MAX_CHARS = 30


def _mapear_agentes(datos: Dict[str, Any], problemas: List[str]) -> Dict[str, AgentConfig]:
    """Parsea ``[agentes.<rol>]`` acumulando todos los problemas de una vez.

    Acepta los roles del registro y, además, roles CUSTOM: un rol fuera del
    registro es válido si declara ``tipo`` (ver ``AgentConfig``).
    """
    crudo = datos.get("agentes")
    if crudo is None:
        return {}
    if not isinstance(crudo, dict):
        problemas.append("la sección [agentes] debe contener tablas [agentes.<rol>]")
        return {}

    configs: Dict[str, AgentConfig] = {}
    for rol, cfg in crudo.items():
        if rol not in ROLES_CONFIGURABLES:
            es_candidato_custom = isinstance(cfg, dict) and "tipo" in cfg
            if not es_candidato_custom:
                problemas.append(
                    f"[agentes.{rol}] no es un rol configurable "
                    f"(válidos: {', '.join(ROLES_CONFIGURABLES)}; para un agente "
                    "custom declara su 'tipo')."
                )
                continue
        if not isinstance(cfg, dict):
            problemas.append(f"[agentes.{rol}] debe ser una tabla TOML")
            continue
        for clave in cfg:
            if clave not in _CLAVES_AGENTE:
                problemas.append(
                    f"clave desconocida '{clave}' en [agentes.{rol}] "
                    f"(válidas: {', '.join(sorted(_CLAVES_AGENTE))})."
                )

        activo = cfg.get("activo", True)
        if not isinstance(activo, bool):
            problemas.append(f"'activo' en [agentes.{rol}] debe ser booleano.")
            activo = True
        if not activo and rol in ROLES_ESENCIALES:
            problemas.append(
                f"el rol '{rol}' no se puede desactivar: es estructural del "
                "pipeline (sin él no hay serie)."
            )

        reglas_crudas = cfg.get("reglas", [])
        if not isinstance(reglas_crudas, list) or not all(
            isinstance(r, str) for r in reglas_crudas
        ):
            problemas.append(f"'reglas' en [agentes.{rol}] debe ser una lista de textos.")
            reglas_crudas = []
        reglas = tuple(r.strip() for r in reglas_crudas if r and r.strip())

        proveedor = cfg.get("proveedor")
        if proveedor is not None and not isinstance(proveedor, str):
            problemas.append(f"'proveedor' en [agentes.{rol}] debe ser texto.")
            proveedor = None
        modelo = cfg.get("modelo")
        if modelo is not None and not isinstance(modelo, str):
            problemas.append(f"'modelo' en [agentes.{rol}] debe ser texto.")
            modelo = None
        temperatura = cfg.get("temperatura")
        if temperatura is not None and not isinstance(temperatura, (int, float)):
            problemas.append(f"'temperatura' en [agentes.{rol}] debe ser numérica.")
            temperatura = None
        top_p = cfg.get("top_p")
        if top_p is not None and not isinstance(top_p, (int, float)):
            problemas.append(f"'top_p' en [agentes.{rol}] debe ser numérica.")
            top_p = None
        max_tokens = cfg.get("max_tokens")
        if max_tokens is not None and not (
            isinstance(max_tokens, int) and not isinstance(max_tokens, bool)
        ):
            problemas.append(f"'max_tokens' en [agentes.{rol}] debe ser entero.")
            max_tokens = None
        tools_crudas = cfg.get("tools", [])
        if not isinstance(tools_crudas, list) or not all(
            isinstance(t, str) for t in tools_crudas
        ):
            problemas.append(
                f"'tools' en [agentes.{rol}] debe ser una lista de textos."
            )
            tools_crudas = []
        tools = tuple(t.strip() for t in tools_crudas if t and t.strip())

        # --- Agentes custom: forma de tipo/contrato/entradas/instrucciones ---
        tipo = cfg.get("tipo")
        if tipo is not None:
            if not isinstance(tipo, str) or tipo not in TIPOS_CUSTOM:
                problemas.append(
                    f"'tipo' en [agentes.{rol}] debe ser uno de: "
                    f"{', '.join(TIPOS_CUSTOM)} (recibido: '{tipo}')."
                )
                tipo = None
            elif rol in ROLES_CONFIGURABLES:
                problemas.append(
                    f"[agentes.{rol}] declara 'tipo' pero ya existe en el "
                    "registro: los agentes custom usan un rol nuevo."
                )
                tipo = None
        contrato = cfg.get("contrato")
        if contrato is not None and (
            not isinstance(contrato, str) or contrato not in CONTRATOS_VALIDOS
        ):
            problemas.append(
                f"'contrato' en [agentes.{rol}] debe ser uno de: "
                f"{', '.join(sorted(CONTRATOS_VALIDOS))} (recibido: '{contrato}')."
            )
            contrato = None
        entradas_crudas = cfg.get("entradas", [])
        if not isinstance(entradas_crudas, list) or not all(
            isinstance(e, str) for e in entradas_crudas
        ):
            problemas.append(
                f"'entradas' en [agentes.{rol}] debe ser una lista de textos."
            )
            entradas_crudas = []
        entradas = tuple(e.strip() for e in entradas_crudas if e and e.strip())
        instrucciones = cfg.get("instrucciones")
        if instrucciones is not None and not isinstance(instrucciones, str):
            problemas.append(
                f"'instrucciones' en [agentes.{rol}] debe ser texto."
            )
            instrucciones = None

        try:
            configs[rol] = AgentConfig(
                activo=activo,
                reglas=reglas,
                proveedor=proveedor.strip().lower() if proveedor else None,
                modelo=modelo.strip() if modelo else None,
                temperatura=float(temperatura) if temperatura is not None else None,
                top_p=float(top_p) if top_p is not None else None,
                max_tokens=max_tokens,
                tools=tools,
                tipo=tipo,
                contrato=contrato,
                entradas=entradas,
                instrucciones=instrucciones,
            )
        except ValueError as exc:
            problemas.append(f"[agentes.{rol}] inválido: {exc}")
    return configs
_CLAVES_PIPELINE = frozenset({"intentos_maximos_de_critica", "politica_al_agotar"})
_CLAVES_FLUJO = frozenset(
    {"contexto", "transformaciones", "revisor", "enriquecimiento", "hasta"}
)
_CLAVES_MEDIA = frozenset(
    {"keyframes", "video", "encadenar_frames", "proveedor_imagen", "intentos_qa"}
)




def _anclas_habilitadas(datos: Dict[str, Any], problemas: List[str]) -> bool:
    """Parsea la clave opcional ``anclas`` de ``[visual]`` (default ``true``).

    Opt-out de la biblioteca de recursos ancla (spec-recursos-ancla §4.3): sin
    la clave (o sin sección ``[visual]``) el proyecto participa; ``false`` la
    ignora por completo.
    """
    visual = datos.get("visual")
    if not isinstance(visual, dict) or "anclas" not in visual:
        return True
    valor = visual["anclas"]
    if not isinstance(valor, bool):
        problemas.append(
            "'anclas' en [visual] debe ser booleano "
            f"(true por defecto; recibido: '{valor}')."
        )
        return True
    return valor


def _mapear_pipeline(datos: Dict[str, Any], problemas: List[str]) -> PipelineConfig:
    """Parsea la sección opcional ``[pipeline]``."""
    crudo = datos.get("pipeline")
    if crudo is None:
        return PipelineConfig()
    if not isinstance(crudo, dict):
        problemas.append("la sección [pipeline] debe ser una tabla TOML")
        return PipelineConfig()
    for clave in crudo:
        if clave not in _CLAVES_PIPELINE:
            problemas.append(
                f"clave desconocida '{clave}' en [pipeline] "
                f"(válidas: {', '.join(sorted(_CLAVES_PIPELINE))})."
            )

    intentos = crudo.get("intentos_maximos_de_critica")
    if intentos is not None and not isinstance(intentos, int):
        problemas.append("'intentos_maximos_de_critica' en [pipeline] debe ser entero.")
        intentos = None
    politica_cruda = crudo.get("politica_al_agotar")
    politica: Optional[str] = None
    if politica_cruda is not None:
        if not isinstance(politica_cruda, str) or politica_cruda not in POLITICAS_DE_AGOTAMIENTO:
            problemas.append(
                "'politica_al_agotar' en [pipeline] debe ser "
                "'aceptar_forzado' o 'saltar_capitulo'."
            )
        else:
            politica = POLITICAS_DE_AGOTAMIENTO[politica_cruda]

    try:
        return PipelineConfig(
            intentos_maximos_de_critica=intentos,
            politica_al_agotar=politica,
        )
    except ValueError as exc:
        problemas.append(f"[pipeline] inválido: {exc}")
        return PipelineConfig()


def _mapear_flujo(datos: Dict[str, Any], problemas: List[str]) -> Optional[FlowSpec]:
    """Parsea la sección opcional ``[flujo]`` (composición + alcance).

    Devuelve ``None`` si la sección no existe (semántica legacy intacta). Los
    problemas de SHAPE se acumulan aquí; los de semántica (roles desconocidos,
    repetidos, ``activo = false``, coherencia del hito) los reporta
    ``FlowSpec.validar`` en ``ProjectSpec.validate``: todos juntos.
    """
    crudo = datos.get("flujo")
    if crudo is None:
        return None
    if not isinstance(crudo, dict):
        problemas.append("la sección [flujo] debe ser una tabla TOML")
        return None
    for clave in crudo:
        if clave not in _CLAVES_FLUJO:
            problemas.append(
                f"clave desconocida '{clave}' en [flujo] "
                f"(válidas: {', '.join(sorted(_CLAVES_FLUJO))})."
            )

    def _fase_lista(nombre: str) -> Tuple[str, ...]:
        valor = crudo.get(nombre)
        if valor is None:
            return ()
        if not isinstance(valor, list) or not all(
            isinstance(rol, str) for rol in valor
        ):
            problemas.append(
                f"'{nombre}' en [flujo] debe ser una lista de roles (texto)."
            )
            return ()
        return tuple(rol.strip() for rol in valor if rol.strip())

    revisor = crudo.get("revisor")
    if revisor is not None:
        if not isinstance(revisor, str) or not revisor.strip():
            problemas.append(
                "'revisor' en [flujo] debe ser el rol (texto) del agente compuerta."
            )
            revisor = None
        else:
            revisor = revisor.strip()

    hasta = crudo.get("hasta", ALCANCE_DEFAULT)
    if not isinstance(hasta, str) or not hasta.strip():
        problemas.append(
            f"'hasta' en [flujo] debe ser texto: uno de {', '.join(ALCANCES)} "
            f"(default: '{ALCANCE_DEFAULT}')."
        )
        hasta = ALCANCE_DEFAULT

    return FlowSpec(
        contexto=_fase_lista("contexto"),
        transformaciones=_fase_lista("transformaciones"),
        revisor=revisor,
        enriquecimiento=_fase_lista("enriquecimiento"),
        hasta=hasta.strip(),
    )


def _mapear_media(datos: Dict[str, Any], problemas: List[str]) -> MediaConfig:
    """Parsea la sección opcional ``[media]`` (spec-recursos-ancla §4.3).

    Sin sección (o sin la tabla) devuelve ``MediaConfig()``: todo default-off,
    corrida idéntica a la de siempre. ``video = true`` es hoy un error de
    configuración claro: la generación I2V pertenece a una fase posterior
    (§13) y no se acepta en silencio.
    """
    crudo = datos.get("media")
    if crudo is None:
        return MediaConfig()
    if not isinstance(crudo, dict):
        problemas.append("la sección [media] debe ser una tabla TOML")
        return MediaConfig()
    for clave in crudo:
        if clave not in _CLAVES_MEDIA:
            problemas.append(
                f"clave desconocida '{clave}' en [media] "
                f"(válidas: {', '.join(sorted(_CLAVES_MEDIA))})."
            )

    def _booleano(nombre: str, default: bool) -> bool:
        valor = crudo.get(nombre, default)
        if not isinstance(valor, bool):
            problemas.append(f"'{nombre}' en [media] debe ser booleano.")
            return default
        return valor

    keyframes = _booleano("keyframes", False)
    video = _booleano("video", False)
    encadenar = _booleano("encadenar_frames", True)
    if video:
        problemas.append(
            "'video' en [media] aún no está soportado: la generación I2V "
            "por escena llega en una fase posterior del plan (spec-recursos-"
            "ancla §13); usa keyframes = true."
        )
        video = False

    proveedor = crudo.get("proveedor_imagen")
    if proveedor is not None:
        if not isinstance(proveedor, str) or proveedor.strip().lower() not in PROVEEDORES_DE_IMAGEN:
            problemas.append(
                f"'proveedor_imagen' en [media] debe ser uno de: "
                f"{', '.join(PROVEEDORES_DE_IMAGEN)} (recibido: '{proveedor}')."
            )
            proveedor = None
        else:
            proveedor = proveedor.strip().lower()

    intentos_qa = crudo.get("intentos_qa", 1)
    if intentos_qa is not None and (
        not isinstance(intentos_qa, int) or isinstance(intentos_qa, bool)
    ):
        problemas.append("'intentos_qa' en [media] debe ser entero.")
        intentos_qa = None

    try:
        return MediaConfig(
            keyframes=keyframes,
            video=video,
            encadenar_frames=encadenar,
            proveedor_imagen=proveedor,
            intentos_qa=intentos_qa if intentos_qa is not None else 1,
        )
    except ValueError as exc:
        problemas.append(f"[media] inválido: {exc}")
        return MediaConfig()


def project_from_dict(datos: Dict[str, Any]) -> ProjectSpec:
    """Construye y valida un ``ProjectSpec`` desde el dict parseado del TOML."""
    problemas: List[str] = []

    proyecto = _mapear_seccion(datos, "proyecto", _SECCION_PROYECTO, problemas, requerida=True)
    voz = _mapear_seccion(datos, "voz", _SECCION_VOZ, problemas, requerida=True)
    visual = _mapear_seccion(datos, "visual", _SECCION_VISUAL, problemas, requerida=True)
    # La sección [formato] es opcional: sin ella rige el perfil por defecto
    # (show vertical de ~60 s con los límites históricos del motor).
    formato = _mapear_seccion(datos, "formato", _SECCION_FORMATO, problemas, requerida=False)

    if problemas:
        raise ValueError(
            "Archivo de proyecto mal formado: " + "; ".join(problemas) + "."
        )

    try:
        perfil = FormatProfile(**formato)
    except ValueError as exc:
        raise ValueError(f"[formato] inválido: {exc}") from exc

    agentes = _mapear_agentes(datos, problemas)
    pipeline = _mapear_pipeline(datos, problemas)
    flujo = _mapear_flujo(datos, problemas)
    anclas = _anclas_habilitadas(datos, problemas)
    media = _mapear_media(datos, problemas)
    if flujo is not None:
        # Semántica del flujo junto al resto de los problemas (§9: todos se
        # reportan de una vez al cargar el proyecto).
        problemas.extend(flujo.validar(agentes))
    if problemas:
        raise ValueError(
            "Archivo de proyecto mal formado: " + "; ".join(problemas) + "."
        )

    spec = ProjectSpec(
        **proyecto,
        **voz,
        **visual,
        format=perfil,
        agentes=agentes,
        pipeline=pipeline,
        flujo=flujo,
        anclas=anclas,
        media=media,
    )
    spec.validate()
    return spec

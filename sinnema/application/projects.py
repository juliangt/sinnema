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


@dataclass(frozen=True)
class AgentConfig:
    """Configuración de un agente (rol) dentro de un proyecto.

    Todo opcional y ``None``/vacío significa "usa el default global". Las
    ``reglas`` se apendan al final del prompt del sistema del rol; la
    precedencia de proveedor/modelo/temperatura es proyecto > entorno > default.
    """

    activo: bool = True
    reglas: Tuple[str, ...] = ()
    proveedor: Optional[str] = None
    modelo: Optional[str] = None
    temperatura: Optional[float] = None

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
        """Devuelve TODOS los problemas de composición y alcance del flujo."""
        problemas: List[str] = []
        # Import diferido: el registro importa este módulo (ciclo registry ->
        # prompts -> projects); en tiempo de llamada ya está construido.
        from sinnema.application.registry import AGENT_REGISTRY

        fases = (
            ("contexto", "contexto", self.contexto),
            ("transformaciones", "transformador", self.transformaciones),
            ("enriquecimiento", "enriquecedor", self.enriquecimiento),
        )
        listados: List[str] = []
        for fase, tipo, roles in fases:
            for rol in roles:
                definicion = AGENT_REGISTRY.get(rol)
                if definicion is None:
                    problemas.append(
                        f"rol desconocido '{rol}' en '{fase}' de [flujo] "
                        f"(roles del registro: {', '.join(sorted(AGENT_REGISTRY))})."
                    )
                    continue
                if rol in ROLES_ESENCIALES:
                    problemas.append(
                        f"el rol '{rol}' es estructural y no se lista en [flujo]: "
                        "siempre participa del pipeline."
                    )
                    continue
                if definicion.tipo != tipo:
                    problemas.append(
                        f"el rol '{rol}' es de tipo '{definicion.tipo}' y no puede "
                        f"ir en la fase '{fase}' de [flujo]."
                    )
                if rol in listados:
                    problemas.append(
                        f"el rol '{rol}' está repetido en [flujo]: un rol aparece "
                        "una sola vez en todo el flujo."
                    )
                listados.append(rol)
        if self.revisor is not None:
            definicion = AGENT_REGISTRY.get(self.revisor)
            if definicion is None:
                problemas.append(
                    f"rol desconocido '{self.revisor}' en 'revisor' de [flujo] "
                    f"(roles del registro: {', '.join(sorted(AGENT_REGISTRY))})."
                )
            elif self.revisor in ROLES_ESENCIALES:
                problemas.append(
                    f"el rol '{self.revisor}' es estructural y no se lista en "
                    "[flujo]: siempre participa del pipeline."
                )
            elif definicion.tipo != "revisor":
                problemas.append(
                    f"el rol '{self.revisor}' es de tipo '{definicion.tipo}' y no "
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

        for rol in sorted(ROLES_ESENCIALES & set(self.agentes)):
            if not self.agentes[rol].activo:
                problemas.append(
                    f"El rol '{rol}' no se puede desactivar: es estructural del "
                    "pipeline (sin él no hay serie)."
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


_CLAVES_AGENTE = frozenset({"activo", "reglas", "proveedor", "modelo", "temperatura"})
_CLAVES_PIPELINE = frozenset({"intentos_maximos_de_critica", "politica_al_agotar"})
_CLAVES_FLUJO = frozenset(
    {"contexto", "transformaciones", "revisor", "enriquecimiento", "hasta"}
)


def _mapear_agentes(datos: Dict[str, Any], problemas: List[str]) -> Dict[str, AgentConfig]:
    """Parsea ``[agentes.<rol>]`` acumulando todos los problemas de una vez."""
    crudo = datos.get("agentes")
    if crudo is None:
        return {}
    if not isinstance(crudo, dict):
        problemas.append("la sección [agentes] debe contener tablas [agentes.<rol>]")
        return {}

    configs: Dict[str, AgentConfig] = {}
    for rol, cfg in crudo.items():
        if rol not in ROLES_CONFIGURABLES:
            problemas.append(
                f"[agentes.{rol}] no es un rol configurable "
                f"(válidos: {', '.join(ROLES_CONFIGURABLES)})."
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

        try:
            configs[rol] = AgentConfig(
                activo=activo,
                reglas=reglas,
                proveedor=proveedor.strip().lower() if proveedor else None,
                modelo=modelo.strip() if modelo else None,
                temperatura=float(temperatura) if temperatura is not None else None,
            )
        except ValueError as exc:
            problemas.append(f"[agentes.{rol}] inválido: {exc}")
    return configs


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
    )
    spec.validate()
    return spec

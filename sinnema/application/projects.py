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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sinnema.application.ports import (
    ROLE_ADAPTER,
    ROLE_CONTINUITY,
    ROLE_CRITIC,
    ROLE_DIRECTOR,
    ROLE_PLANNER,
    ROLE_SCRIPTWRITER,
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
    )
    spec.validate()
    return spec

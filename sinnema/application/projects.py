"""Definición de proyecto (show): la unidad de reutilización del motor.

Un proyecto concentra toda la política editorial que antes vivía hardcodeada
en prompts, contratos y CLI: identidad, concepto, voz, idioma, estilo visual y
el sobre editorial numérico (``FormatProfile``). Vive en un archivo TOML que
carga la infraestructura y llega al pipeline como este objeto validado.

El mapeo ``project_from_dict`` es puro (sin I/O): la infraestructura se ocupa
de leer el archivo; la aplicación, de decir qué significa un proyecto válido.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List

from sinnema.domain.models import FormatProfile

#: Un id de proyecto es un slug estable: nombra carpetas de salida y lore.
PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
PROJECT_ID_MAX_CHARS = 30

TOPIC_MIN_CHARS = 8
TOPIC_MAX_CHARS = 200

_VISUAL_MASTER_STYLE_MIN_CHARS = 40


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

    spec = ProjectSpec(
        **proyecto,
        **voz,
        **visual,
        format=perfil,
    )
    spec.validate()
    return spec

"""Recursos ancla: biblioteca de consistencia visual por proyecto.

Contratos puros de la biblioteca (spec-recursos-ancla §4.1): cada ancla es una
entidad visual (personaje, lugar, objeto o estilo global) con una batería de
imágenes de referencia por rol y un descriptor canónico EN INGLÉS destinado a
modelos de imagen. ``ReferenciaAncla`` y ``ManifestDeGeneracion`` son los
contratos con los que fases posteriores citan anclas desde specs visuales y
trazan la procedencia del media generado; se definen aquí porque son
contratos de dominio puros (la spec los detalla en §5.3 y §6).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple, get_args

from pydantic import BaseModel, Field, field_validator, model_validator

from sinnema.domain.text import contains_spanish_characters

TipoDeAncla = Literal["personaje", "lugar", "objeto", "estilo"]
EstadoDeAncla = Literal["borrador", "propuesto", "lockeado", "retirado"]

RolDeImagen = Literal[
    "hero_portrait", "turnaround_front", "turnaround_quarter",
    "turnaround_side", "turnaround_back", "expression_sheet",
    "outfit_variant",                      # personaje
    "establishing_shot", "coverage_angle", "lighting_reference",  # lugar
    "prop_hero", "prop_detail",            # objeto
    "style_reference",                     # estilo
]

#: Vocabularios para catálogos de formularios (API §9.1) y validación.
TIPOS_DE_ANCLA: Tuple[str, ...] = get_args(TipoDeAncla)
ESTADOS_DE_ANCLA: Tuple[str, ...] = get_args(EstadoDeAncla)

#: Roles de batería válidos por tipo de ancla: la coherencia rol↔tipo es la
#: validación en profundidad §11.1 (un hero_portrait no puede vivir en un lugar).
ROLES_POR_TIPO: Dict[str, Tuple[str, ...]] = {
    "personaje": (
        "hero_portrait", "turnaround_front", "turnaround_quarter",
        "turnaround_side", "turnaround_back", "expression_sheet", "outfit_variant",
    ),
    "lugar": ("establishing_shot", "coverage_angle", "lighting_reference"),
    "objeto": ("prop_hero", "prop_detail"),
    "estilo": ("style_reference",),
}

#: Batería mínima para LOCKEAR cada tipo (spec §4.1): la Fase 1 (API lock) la
#: verifica con ``bateria_minima_cumplida``. Batería recomendada = §3.2.
BATERIA_MINIMA: Dict[str, Tuple[str, ...]] = {
    "personaje": (
        "hero_portrait", "turnaround_front", "turnaround_side", "turnaround_back",
    ),
    "lugar": ("establishing_shot",),
    "objeto": ("prop_hero",),
    "estilo": ("style_reference",),
}

DESCRIPCION_CANONICA_MIN_CHARS = 40

#: Un ``ancla_id`` es un slug estable: nombra su carpeta de batería en disco
#: (espejo de la regla de ``project_id``).
ANCLA_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ANCLA_ID_MAX_CHARS = 60


def _rechazar_espanol(valor: str, campo: str) -> str:
    # Espejo del helper de technical.py: mismo mensaje, misma regla (los
    # descriptores de imagen no llevan español, igual que los prompts visuales).
    if contains_spanish_characters(valor):
        raise ValueError(
            f"El campo '{campo}' debe estar EN INGLÉS: contiene caracteres "
            "españoles (tildes, ñ o signos de apertura)."
        )
    return valor


def _validar_ancla_id(valor: str) -> str:
    limpio = valor.strip()
    if (
        not limpio
        or len(limpio) > ANCLA_ID_MAX_CHARS
        or not ANCLA_ID_PATTERN.match(limpio)
    ):
        raise ValueError(
            f"ancla_id debe ser un slug de hasta {ANCLA_ID_MAX_CHARS} caracteres "
            f"([a-z0-9-], recibido: '{valor}')."
        )
    return limpio


def bateria_minima_cumplida(tipo: str, roles: Iterable[str]) -> bool:
    """True si ``roles`` cubre la batería mínima del tipo (spec-recursos-ancla §4.1)."""
    presentes = set(roles)
    return all(rol in presentes for rol in BATERIA_MINIMA.get(tipo, ()))


class ManifestDeGeneracion(BaseModel):
    """Procedencia interna de un media generado (spec-recursos-ancla §6).

    El seed de los proveedores no garantiza determinismo: este manifest es la
    fuente reproducible (prompt final, modelo exacto, referencias usadas EN
    ORDEN y parámetros de la llamada).
    """

    proveedor: str = Field(..., min_length=1, description="Adaptador que generó el media (gemini, openai, ...).")
    modelo: str = Field(..., min_length=1, description="Modelo y versión exactos del proveedor.")
    seed: Optional[int] = None
    prompt_final: str = Field(..., min_length=10, description="Prompt final compuesto, EN INGLÉS.")
    anclas_usadas: List[Tuple[str, int, RolDeImagen]] = Field(
        default_factory=list,
        description="(ancla_id, version, rol) EN ORDEN: el ancla de identidad va primero.",
    )
    parametros: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parámetros de la llamada (pesos de referencia, fidelidad, ...).",
    )
    id_externo: Optional[str] = None
    creado_en: datetime

    @field_validator("prompt_final")
    @classmethod
    def _prompt_en_ingles(cls, valor: str) -> str:
        return _rechazar_espanol(valor, "prompt_final")


class ImagenAncla(BaseModel):
    """Una imagen de la batería de un ancla."""

    rol: RolDeImagen
    archivo: str = Field(
        ...,
        min_length=1,
        description="Nombre de archivo relativo bajo anclas/<project_id>/<ancla_id>/.",
    )
    origen: Literal["subida", "generada"] = "subida"
    manifest: Optional[ManifestDeGeneracion] = None  # solo si origen = "generada"

    @field_validator("archivo")
    @classmethod
    def _archivo_plano(cls, valor: str) -> str:
        limpio = valor.strip()
        if (
            not limpio
            or "/" in limpio
            or "\\" in limpio
            or limpio in (".", "..")
            or limpio.startswith(".")
        ):
            raise ValueError(
                f"El campo 'archivo' debe ser un nombre de archivo simple dentro "
                f"de la carpeta del ancla (recibido: '{valor}')."
            )
        return limpio

    @model_validator(mode="after")
    def _manifest_solo_en_generadas(self) -> "ImagenAncla":
        if self.manifest is not None and self.origen != "generada":
            raise ValueError(
                "Una imagen de origen 'subida' no puede llevar manifest de "
                "generación (el manifest solo procede del pipeline de media)."
            )
        return self


class ReferenciaAncla(BaseModel):
    """Cita de un ancla desde una spec visual (spec-recursos-ancla §5.3)."""

    ancla_id: str
    roles: List[RolDeImagen] = Field(
        default_factory=list,
        description="Roles pedidos de la batería; vacío = la batería completa del tipo.",
    )

    @field_validator("ancla_id")
    @classmethod
    def _slug_estable(cls, valor: str) -> str:
        return _validar_ancla_id(valor)


class RecursoAncla(BaseModel):
    """Una entidad visual ancla del proyecto: identidad reutilizable entre escenas.

    Solo las anclas ``lockeadas`` (y no ``retiradas``) participan del pipeline;
    el lock es humano y exige batería mínima. Cambiar la batería de una ancla
    lockeada sube ``version`` (regla del almacén): lo ya generado conserva el
    manifest con la versión usada. Retirar no borra (los episodios pasados la
    citan).
    """

    ancla_id: str
    tipo: TipoDeAncla
    nombre: str = Field(..., min_length=1, max_length=80, description="Único case-insensitive por proyecto (lo verifica el almacén).")
    descripcion_canonica: str = Field(
        ...,
        min_length=DESCRIPCION_CANONICA_MIN_CHARS,
        description="Descriptor EN INGLÉS, destinado a modelos de imagen.",
    )
    estado: EstadoDeAncla = "borrador"
    bateria: List[ImagenAncla] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    chapter_first_seen: Optional[str] = None
    chapter_last_seen: Optional[str] = None

    @field_validator("ancla_id")
    @classmethod
    def _slug_estable(cls, valor: str) -> str:
        return _validar_ancla_id(valor)

    @field_validator("nombre")
    @classmethod
    def _nombre_con_contenido(cls, valor: str) -> str:
        limpio = " ".join(valor.split())
        if not limpio:
            raise ValueError("El nombre del ancla no puede quedar vacío.")
        return limpio

    @field_validator("descripcion_canonica")
    @classmethod
    def _descriptor_en_ingles(cls, valor: str) -> str:
        return _rechazar_espanol(valor, "descripcion_canonica")

    @model_validator(mode="after")
    def _bateria_coherente_con_tipo(self) -> "RecursoAncla":
        validos = ROLES_POR_TIPO[self.tipo]
        incoherentes = sorted(
            {imagen.rol for imagen in self.bateria if imagen.rol not in validos}
        )
        if incoherentes:
            raise ValueError(
                f"Roles de batería incoherentes con el tipo '{self.tipo}': "
                f"{', '.join(incoherentes)} (válidos: {', '.join(validos)})."
            )
        return self

    @model_validator(mode="after")
    def _lock_exige_bateria_minima(self) -> "RecursoAncla":
        if self.estado == "lockeado" and not bateria_minima_cumplida(
            self.tipo, (imagen.rol for imagen in self.bateria)
        ):
            raise ValueError(
                f"No se puede lockear '{self.ancla_id}': la batería mínima de un "
                f"'{self.tipo}' exige {', '.join(BATERIA_MINIMA[self.tipo])} "
                "(spec-recursos-ancla §4.1)."
            )
        return self

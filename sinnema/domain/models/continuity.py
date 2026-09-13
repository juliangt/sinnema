"""Continuidad y memoria de lore de la serie."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from sinnema.domain.constants import LORE_TERM_MAX_WORDS
from sinnema.domain.models.anclas import TipoDeAncla


class LoreEntry(BaseModel):
    """Entrada acumulativa de la memoria de continuidad de la serie."""

    term: str = Field(..., min_length=2, max_length=80, description="Término canónico corto (1-4 palabras).")
    definition: str = Field(..., min_length=5, description="Definición breve del término.")
    chapter_id: str = Field(..., description="Capítulo donde se introdujo por primera vez.")
    first_seen_title: str = Field(..., description="Título del capítulo de origen.")
    category: Literal["concepto", "termino", "personaje", "referencia", "formato"] = "concepto"
    #: Enlace opcional con la biblioteca de anclas (spec-recursos-ancla §4.4):
    #: la extracción de lore lo estampa cuando un término nuevo coincide con
    #: el nombre de una ancla lockeada del proyecto (cruce determinista).
    ancla_id: Optional[str] = None

    @field_validator("term")
    @classmethod
    def _termino_corto(cls, valor: str) -> str:
        limpio = " ".join(valor.split())
        if not limpio:
            raise ValueError("El término del lore no puede quedar vacío.")
        if len(limpio.split()) > LORE_TERM_MAX_WORDS:
            raise ValueError(
                f"El término del lore debe tener como máximo {LORE_TERM_MAX_WORDS} "
                f"palabras (recibido: '{limpio}')."
            )
        return limpio


class AnclaDelCapitulo(BaseModel):
    """Cita de un ancla en el casting del capítulo (spec-recursos-ancla §5.1).

    El continuity master selecciona del catálogo lockeado las entidades que
    participan del capítulo: el ``descriptor`` es copia EN del canónico
    (trazabilidad del prompt) y las ``instrucciones`` describen en el idioma
    del proyecto el rol del ancla aquí (vestuario, estado, tratamiento).
    """

    ancla_id: str = Field(..., min_length=1, description="ancla_id del catálogo lockeado del proyecto.")
    tipo: TipoDeAncla
    descriptor: str = Field(
        ...,
        min_length=1,
        description="Copia EN del descriptor canónico del ancla (sin paráfrasis).",
    )
    instrucciones: str = Field(
        ...,
        min_length=5,
        description="Rol del ancla en este capítulo (vestuario, estado, tratamiento).",
    )


class ContinuityDirectives(BaseModel):
    """Directivas quirúrgicas que el Lore Keeper emite para cada capítulo."""

    recap_bridge: str = Field(
        ...,
        min_length=5,
        description="Gancho de 1-2 frases que conecta con el capítulo anterior (o plantea la premisa si es el primero).",
    )
    concepts_already_covered: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="Conceptos del lore que este capítulo da por sabidos (prohibido re-explicar).",
    )
    callbacks_allowed: List[str] = Field(
        default_factory=list,
        max_length=5,
        description="Llamadas narrativas permitidas a momentos/términos de capítulos anteriores.",
    )
    new_terms_to_introduce: List[str] = Field(
        ...,
        min_length=1,
        max_length=6,
        description="Términos nuevos que este capítulo incorporará al lore.",
    )
    forbidden_reexplanations: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="Conceptos cuya re-definición formal está prohibida aquí.",
    )
    continuity_notes: str = Field(
        ...,
        min_length=5,
        description="Notas operativas para el guionista sobre hilos narrativos.",
    )
    #: Casting visual del capítulo (spec-recursos-ancla §5.1): anclas lockeadas
    #: que participan aquí, con su rol. Default vacío = proyecto sin anclas o
    #: capítulo sin anclados: compatible con contratos y corridas previas.
    anclas_del_capitulo: List[AnclaDelCapitulo] = Field(default_factory=list)

    @field_validator("new_terms_to_introduce")
    @classmethod
    def _terminos_nuevos_limpios(cls, valor: List[str]) -> List[str]:
        limpios = [t.strip() for t in valor if t and t.strip()]
        if not limpios:
            raise ValueError("Se requiere al menos un término nuevo no vacío.")
        demasiado_largos = [t for t in limpios if len(t.split()) > LORE_TERM_MAX_WORDS]
        if demasiado_largos:
            raise ValueError(
                f"Cada término nuevo debe tener como máximo {LORE_TERM_MAX_WORDS} "
                f"palabras (demasiado largos: {demasiado_largos})."
            )
        return limpios

    @model_validator(mode="after")
    def _sin_reintroducciones(self) -> "ContinuityDirectives":
        cubiertos = {c.strip().lower() for c in self.concepts_already_covered}
        nuevos = {t.strip().lower() for t in self.new_terms_to_introduce}
        solapados = sorted(nuevos & cubiertos)
        if solapados:
            raise ValueError(
                "Un término de new_terms_to_introduce ya está declarado en "
                f"concepts_already_covered (conflicto: {solapados}): no puede ser "
                "nuevo y estar cubierto a la vez."
            )
        return self

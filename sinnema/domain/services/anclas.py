"""Validadores post-generación de la biblioteca de anclas (spec-recursos-ancla §11.2).

Son la capa de validación en profundidad del pipeline con anclas: corren sobre
el artefacto que cada agente acaba de producir y ANTES de que circule por el
estado (mismo mecanismo que los validadores de formato y coherencia). Un
rechazo es duro: el fallo sube y el capítulo no avanza con referencias a
entidades que no existen o fichas alucinadas.
"""
from __future__ import annotations

from typing import Optional, Sequence

from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.models import (
    ContinuityDirectives,
    RecursoAncla,
    TechnicalPackage,
)


def _catalogo(anclas: Optional[Sequence[RecursoAncla]]) -> dict:
    return {ancla.ancla_id: ancla for ancla in (anclas or [])}


def validate_continuity_anchors(
    directivas: ContinuityDirectives,
    anclas: Optional[Sequence[RecursoAncla]] = None,
) -> None:
    """El casting del capítulo solo cita anclas lockeadas con su ficha exacta.

    Para cada ``AnclaDelCapitulo``: el ``ancla_id`` existe en el catálogo
    lockeado sembrado en el estado, el tipo coincide y el ``descriptor`` citado
    es la copia exacta del ``descripcion_canonica`` (sin alucinaciones de
    ficha). Con catálogo vacío, cualquier casting es una alucinación.
    """
    catalogo = _catalogo(anclas)
    for cita in directivas.anclas_del_capitulo:
        ancla = catalogo.get(cita.ancla_id)
        if ancla is None:
            raise DomainValidationError(
                f"El casting del capítulo cita el ancla '{cita.ancla_id}' que no "
                "existe en la biblioteca lockeada del proyecto (catálogo: "
                f"{sorted(catalogo) or '(vacío)'})."
            )
        if ancla.estado != "lockeado":
            raise DomainValidationError(
                f"El casting del capítulo cita el ancla '{cita.ancla_id}' en "
                f"estado '{ancla.estado}': solo las lockeadas participan del "
                "pipeline."
            )
        if cita.tipo != ancla.tipo:
            raise DomainValidationError(
                f"El casting del capítulo declara '{cita.ancla_id}' como "
                f"'{cita.tipo}' pero la biblioteca la tiene como "
                f"'{ancla.tipo}'."
            )
        if cita.descriptor.strip() != ancla.descripcion_canonica.strip():
            raise DomainValidationError(
                f"El descriptor citado para '{cita.ancla_id}' diverge del "
                "canónico de la biblioteca: los anclados se citan con su ficha "
                "exacta, nunca con descripciones nuevas."
            )

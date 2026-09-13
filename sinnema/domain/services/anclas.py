"""Validadores y servicios post-generación de la biblioteca de anclas
(spec-recursos-ancla §5.1, §5.3, §5.4, §11.2).

Los ``validate_*`` son la capa de validación en profundidad del pipeline con
anclas: corren sobre el artefacto que cada agente acaba de producir y ANTES de
que circule por el estado (mismo mecanismo que los validadores de formato y
coherencia). Un rechazo es duro: el fallo sube y el capítulo no avanza con
referencias a entidades que no existen o fichas alucinadas.

``cobertura_casting`` y ``registrar_vigencia_de_anclas`` son servicios puros
que el consolidador usa para la auditoría blanda de cobertura y el libro
contable de vigencia (chapter_first_seen/last_seen).
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.models import (
    AnclaDelCapitulo,
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


def validate_anchor_refs(
    paquete: TechnicalPackage,
    anclas: Optional[Sequence[RecursoAncla]] = None,
) -> None:
    """Toda referencia de ``spec.anclas`` existe y está lockeada (§5.3/§11.2).

    Rechazo duro ANTES de que el paquete circule: una spec que cite un ancla
    ausente, retirada o sin lock delataría un id alucinado o desactualizado.
    """
    catalogo = _catalogo(anclas)
    for spec in paquete.visual_specs:
        for ref in spec.anclas:
            ancla = catalogo.get(ref.ancla_id)
            if ancla is None:
                raise DomainValidationError(
                    f"La escena {spec.scene_number} referencia el ancla "
                    f"'{ref.ancla_id}' que no existe en la biblioteca lockeada "
                    f"del proyecto (catálogo: {sorted(catalogo) or '(vacío)'})."
                )
            if ancla.estado != "lockeado":
                raise DomainValidationError(
                    f"La escena {spec.scene_number} referencia el ancla "
                    f"'{ref.ancla_id}' en estado '{ancla.estado}': solo las "
                    "lockeadas participan del pipeline."
                )


def anclas_referenciadas(paquete: Optional[TechnicalPackage]) -> List[str]:
    """Ids de anclas citadas por las specs del paquete, sin duplicar."""
    if paquete is None:
        return []
    vistas: List[str] = []
    for spec in paquete.visual_specs:
        for ref in spec.anclas:
            if ref.ancla_id not in vistas:
                vistas.append(ref.ancla_id)
    return vistas


def cobertura_casting(
    casting: Sequence[AnclaDelCapitulo],
    paquete: Optional[TechnicalPackage],
) -> List[str]:
    """Anclas del casting SIN ninguna referencia en las specs (cobertura blanda).

    Cada ancla del casting del capítulo debería aparecer en ≥1 spec; las
    faltantes NO rechazan el paquete: el consolidador las reporta como hallazgo
    de auditoría (§5.3).
    """
    referenciadas = set(anclas_referenciadas(paquete))
    return [
        cita.ancla_id
        for cita in casting
        if cita.ancla_id not in referenciadas
    ]


def registrar_vigencia_de_anclas(
    anclas: Optional[Sequence[RecursoAncla]],
    usadas: Sequence[str],
    chapter_id: str,
) -> Optional[List[RecursoAncla]]:
    """Libro contable §5.4: first/last seen de las anclas usadas en un capítulo.

    Devuelve una NUEVA lista con copias actualizadas solo de las anclas cuyo
    rastro cambia (``chapter_first_seen`` solo si era None;
    ``chapter_last_seen`` siempre que el capítulo la use). ``None`` si nada
    cambió: el nodo del grafo omite la clave y el estado queda intacto.
    """
    usadas_set = set(usadas)
    if not usadas_set:
        return None
    cambios: List[RecursoAncla] = []
    hubo_cambios = False
    for ancla in (anclas or []):
        if ancla.ancla_id in usadas_set:
            actualizada = ancla.model_copy(
                update={
                    "chapter_first_seen": ancla.chapter_first_seen or chapter_id,
                    "chapter_last_seen": chapter_id,
                }
            )
            hubo = (
                actualizada.chapter_first_seen,
                actualizada.chapter_last_seen,
            ) != (ancla.chapter_first_seen, ancla.chapter_last_seen)
            hubo_cambios = hubo_cambios or hubo
            cambios.append(actualizada)
        else:
            cambios.append(ancla)
    return cambios if hubo_cambios else None

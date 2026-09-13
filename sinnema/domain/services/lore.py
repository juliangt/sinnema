"""Extracción determinista de nuevas entradas de lore por capítulo."""
from __future__ import annotations

from typing import List, Optional, Sequence

from sinnema.domain.models import (
    ChapterOutline,
    ContinuityDirectives,
    LoreEntry,
    RecursoAncla,
)

#: Mapeo tipo de ancla -> categoría de lore (spec-recursos-ancla §4.4): una
#: entidad con ficha visual entra a la memoria con su categoría más cercana y
#: el enlace exacto en ``ancla_id``.
CATEGORIA_POR_TIPO_DE_ANCLA = {
    "personaje": "personaje",
    "lugar": "referencia",
    "objeto": "referencia",
    "estilo": "formato",
}


def extract_new_lore(
    chapter: ChapterOutline,
    directives: Optional[ContinuityDirectives],
    existing: List[LoreEntry],
    anclas: Optional[Sequence[RecursoAncla]] = None,
) -> List[LoreEntry]:
    """Convierte conceptos clave + términos nuevos en entradas de lore,
    deduplicadas (case-insensitive) contra la memoria existente.

    Cruce determinista con la biblioteca (spec-recursos-ancla §4.4, sin LLM):
    un término NUEVO cuyo texto coincide (casefold) con el ``nombre`` de una
    ancla del catálogo se produce con la categoría mapeada del tipo y su
    ``ancla_id`` seteado. El resto del comportamiento es exacto al de siempre.
    """
    existentes = {e.term.strip().lower() for e in existing}
    anclas_por_nombre = {
        ancla.nombre.strip().casefold(): ancla for ancla in (anclas or [])
    }
    nuevas: List[LoreEntry] = []

    def _agregar(term: str, categoria: str, definicion: str) -> None:
        limpio = " ".join(term.split())
        if not limpio or limpio.lower() in existentes:
            return
        existentes.add(limpio.lower())
        ancla = anclas_por_nombre.get(limpio.casefold())
        nuevas.append(
            LoreEntry(
                term=limpio,
                definition=definicion,
                chapter_id=chapter.chapter_id,
                first_seen_title=chapter.title,
                category=(
                    CATEGORIA_POR_TIPO_DE_ANCLA[ancla.tipo]
                    if ancla is not None
                    else categoria
                ),  # type: ignore[arg-type]
                ancla_id=ancla.ancla_id if ancla is not None else None,
            )
        )

    for concepto in chapter.key_concepts:
        _agregar(concepto, "concepto", f"Concepto clave introducido en '{chapter.title}'.")
    if directives is not None:
        for termino in directives.new_terms_to_introduce:
            _agregar(termino, "termino", f"Término canónico introducido en '{chapter.title}'.")
    return nuevas


def merge_lore(
    existing: List[LoreEntry], incoming: List[LoreEntry]
) -> List[LoreEntry]:
    """Fusiona memorias de lore deduplicando términos (case-insensitive).

    Preserva el orden: primero la memoria existente, luego las entradas nuevas
    en su orden de llegada. Es la operación con la que el almacén persistente
    de cada proyecto consolida el lore acumulado entre corridas.
    """
    vistos = {e.term.strip().lower() for e in existing}
    fusionada = list(existing)
    for entrada in incoming:
        clave = entrada.term.strip().lower()
        if clave in vistos:
            continue
        vistos.add(clave)
        fusionada.append(entrada)
    return fusionada

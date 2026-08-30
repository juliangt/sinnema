"""Extracción determinista de nuevas entradas de lore por capítulo."""
from __future__ import annotations

from typing import List, Optional

from sinnema.domain.models import (
    ChapterOutline,
    ContinuityDirectives,
    LoreEntry,
)


def extract_new_lore(
    chapter: ChapterOutline,
    directives: Optional[ContinuityDirectives],
    existing: List[LoreEntry],
) -> List[LoreEntry]:
    """Convierte conceptos clave + términos nuevos en entradas de lore,
    deduplicadas (case-insensitive) contra la memoria existente."""
    existentes = {e.term.strip().lower() for e in existing}
    nuevas: List[LoreEntry] = []

    def _agregar(term: str, categoria: str, definicion: str) -> None:
        limpio = " ".join(term.split())
        if not limpio or limpio.lower() in existentes:
            return
        existentes.add(limpio.lower())
        nuevas.append(
            LoreEntry(
                term=limpio,
                definition=definicion,
                chapter_id=chapter.chapter_id,
                first_seen_title=chapter.title,
                category=categoria,  # type: ignore[arg-type]
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

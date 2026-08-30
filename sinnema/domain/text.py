"""Utilidades de texto puras compartidas por modelos y servicios.

Módulo hoja del dominio: no importa nada más del paquete (evita ciclos con
los modelos, que dependen de él).
"""
from __future__ import annotations

import re

#: Caracteres exclusivos del español: tildes, diéresis, eñe y signos de
#: apertura. Su presencia delata un prompt visual que debía estar en inglés.
_SPANISH_ONLY = re.compile(r"[áéíóúüñÁÉÍÓÚÜÑ¿¡]")


def count_words(texto: str) -> int:
    """Cuenta palabras por separación de espacios en blanco."""
    return len(texto.split())


def contains_spanish_characters(texto: str) -> bool:
    """True si el texto contiene caracteres exclusivos del español."""
    return bool(_SPANISH_ONLY.search(texto))

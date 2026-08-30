"""Excepciones del dominio."""
from __future__ import annotations


class DomainValidationError(ValueError):
    """Violación de una regla de negocio (semántica), no de formato.

    Se lanza cuando un artefacto cruza los límites entre agentes con datos
    incoherentes entre sí (ids de capítulo distintos, escenas desalineadas,
    planes con tamaño incorrecto, etc.).
    """

"""Contratos genéricos para agentes custom declarados en el TOML.

Los agentes definidos 100% desde la configuración (``[agentes.<rol>]`` con
``tipo``/``contrato``/``instrucciones``) no pueden llevar contratos de dominio
propios con validación cruzada: sus salidas se ajustan a uno de estos
contratos genéricos predefinidos (ver ``docs/spec-agentes-dinamicos.md`` §8).
El dictamen de un revisor custom usa directamente ``QualityAudit``: la
compuerta de calidad depende de esa semántica y no se negocia.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class NotasDelAgente(BaseModel):
    """Salida genérica de un agente de contexto o enriquecimiento."""

    nota_principal: str = Field(
        ..., min_length=1, description="Conclusión u observación central del agente."
    )
    puntos_clave: List[str] = Field(
        default_factory=list,
        description="Puntos específicos que acompañan a la nota principal.",
    )


class TextoLibre(BaseModel):
    """El contrato más simple: un texto producido por el agente."""

    contenido: str = Field(..., min_length=1, description="Texto generado.")

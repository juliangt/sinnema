"""Prompts del sistema por rol, parametrizados por proyecto.

Los prompts son política de la aplicación (no de infraestructura): definen el
*qué* se le pide a cada agente. El *cómo* (transporte, reintentos, proveedor)
vive en los adaptadores LLM.

Cada rol vive en su propio módulo con el mismo contrato: ``build_system_prompt(spec)``
devuelve el prompt de sistema del rol para un proyecto, y ``build_user_message(...)``
construye el mensaje de usuario con los datos de la corrida.

El catálogo rol → prompts vive en el registro de agentes
(``sinnema.application.registry``), junto a los esquemas y validadores de cada
rol; esta paquete conserva los módulos de prompts y delega el builder allí.
"""
from __future__ import annotations

from typing import Dict

from sinnema.application.projects import ProjectSpec
from sinnema.application.prompts import (
    adapter,
    continuity,
    critic,
    director,
    planner,
    scriptwriter,
)

__all__ = [
    "adapter",
    "continuity",
    "critic",
    "director",
    "planner",
    "scriptwriter",
    "build_role_system_prompts",
]


def build_role_system_prompts(spec: ProjectSpec) -> Dict[str, str]:
    """System prompt de cada rol para un proyecto, indexado por rol.

    Delega en el registro de agentes, fuente única del catálogo. La importación
    es diferida para no crear un ciclo de módulos (registro → prompts →
    projects) en tiempo de import.
    """
    from sinnema.application.registry import build_role_system_prompts as _desde_registro

    return _desde_registro(spec)

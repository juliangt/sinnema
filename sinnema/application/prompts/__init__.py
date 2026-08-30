"""Prompts del sistema por rol, parametrizados por proyecto.

Los prompts son política de la aplicación (no de infraestructura): definen el
*qué* se le pide a cada agente. El *cómo* (transporte, reintentos, proveedor)
vive en los adaptadores LLM.

Cada rol vive en su propio módulo con el mismo contrato: ``build_system_prompt(spec)``
devuelve el prompt de sistema del rol para un proyecto, y ``build_user_message(...)``
construye el mensaje de usuario con los datos de la corrida. El catálogo
``build_role_system_prompts`` conecta roles con sus prompts, en paralelo a
``ROLE_SCHEMAS``.
"""
from __future__ import annotations

from typing import Dict

from sinnema.application.ports import (
    ROLE_ADAPTER,
    ROLE_CONTINUITY,
    ROLE_CRITIC,
    ROLE_DIRECTOR,
    ROLE_PLANNER,
    ROLE_SCRIPTWRITER,
)
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
    """System prompt de cada rol para un proyecto, indexado por rol."""
    return {
        ROLE_PLANNER: planner.build_system_prompt(spec),
        ROLE_CONTINUITY: continuity.build_system_prompt(spec),
        ROLE_SCRIPTWRITER: scriptwriter.build_system_prompt(spec),
        ROLE_ADAPTER: adapter.build_system_prompt(spec),
        ROLE_CRITIC: critic.build_system_prompt(spec),
        ROLE_DIRECTOR: director.build_system_prompt(spec),
    }

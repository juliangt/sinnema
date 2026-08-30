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
from sinnema.application.projects import AgentConfig, ProjectSpec
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


def _con_reglas(prompt_base: str, config: AgentConfig) -> str:
    """Apenda las reglas del proyecto al prompt del sistema de un rol."""
    if not config.reglas:
        return prompt_base
    reglas = "\n".join(f"- {r}" for r in config.reglas)
    return (
        f"{prompt_base}\n\n"
        "REGLAS ADICIONALES DEL PROYECTO (si conflitan con lo anterior, "
        f"prevalecen):\n{reglas}"
    )


def build_role_system_prompts(spec: ProjectSpec) -> Dict[str, str]:
    """System prompt de cada rol para un proyecto, indexado por rol.

    Cada prompt base del rol se compone con el ``ProjectSpec`` y luego recibe
    las ``reglas`` declaradas en ``[agentes.<rol>]`` del proyecto, si las hay.
    """

    def _de(rol: str, builder) -> str:
        return _con_reglas(builder(spec), spec.config_de_agente(rol))

    return {
        ROLE_PLANNER: _de(ROLE_PLANNER, planner.build_system_prompt),
        ROLE_CONTINUITY: _de(ROLE_CONTINUITY, continuity.build_system_prompt),
        ROLE_SCRIPTWRITER: _de(ROLE_SCRIPTWRITER, scriptwriter.build_system_prompt),
        ROLE_ADAPTER: _de(ROLE_ADAPTER, adapter.build_system_prompt),
        ROLE_CRITIC: _de(ROLE_CRITIC, critic.build_system_prompt),
        ROLE_DIRECTOR: _de(ROLE_DIRECTOR, director.build_system_prompt),
    }

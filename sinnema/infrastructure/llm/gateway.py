"""Adaptador LLM que implementa ``StructuredGenerationPort`` con LangChain.

Responsabilidades de este adaptador (y de nadie más):
- vincular cada rol con su cliente LangChain y su esquema estructurado,
- reintentar las invocaciones con backoff ante fallos transitorios,
- detectar wiring erróneo (roles desconocidos, esquemas intercambiados).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Type, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from sinnema.application.ports import ROLE_SCHEMAS
from sinnema.application.projects import ProjectSpec, resolver_flujo
from sinnema.application.registry import definiciones_del_proyecto
from sinnema.infrastructure.llm.providers import build_role_clients

logger = logging.getLogger("sinnema.infrastructure.gateway")

TSchema = TypeVar("TSchema")


@dataclass(frozen=True)
class RetryPolicy:
    """Política de reintentos para invocaciones al LLM."""

    max_retries: int = 3
    backoff_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_retries < 1:
            raise ValueError(f"max_retries debe ser >= 1 (recibido: {self.max_retries}).")
        if self.backoff_seconds < 0:
            raise ValueError(
                f"backoff_seconds no puede ser negativo (recibido: {self.backoff_seconds})."
            )


class LangChainStructuredGateway:
    """Implementa el puerto de generación estructurada sobre LangChain."""

    def __init__(
        self,
        clients: Mapping[str, BaseChatModel],
        retry_policy: Optional[RetryPolicy] = None,
        schemas: Optional[Mapping[str, Type[BaseModel]]] = None,
    ) -> None:
        self._retry_policy = retry_policy or RetryPolicy()
        #: Catálogo rol -> contrato. Por defecto, el del registro global; un
        #: proyecto con agentes custom aporta su catálogo extendido.
        self._schemas: Mapping[str, Type[BaseModel]] = (
            schemas if schemas is not None else ROLE_SCHEMAS
        )

        roles_solicitados = set(clients)
        roles_conocidos = set(self._schemas)
        desconocidos = sorted(roles_solicitados - roles_conocidos)
        if desconocidos:
            raise ValueError(
                f"Clientes LLM con roles desconocidos: {desconocidos}. "
                f"Roles válidos: {sorted(roles_conocidos)}."
            )
        # Los roles sin cliente son los desactivados por el proyecto: se validan
        # al invocar ``generate`` (un nodo activo jamás debería pedirlos).

        self._structured: Dict[str, Any] = {
            role: clients[role].with_structured_output(self._schemas[role])
            for role in clients
        }

    def generate(
        self,
        role: str,
        schema: Type[TSchema],
        system_prompt: str,
        user_prompt: str,
    ) -> TSchema:
        if role not in self._structured:
            raise ValueError(
                f"El rol '{role}' no tiene cliente LLM configurado: si está "
                "desactivado en el proyecto, ningún nodo debería invocarlo."
            )
        if schema is not self._schemas[role]:
            raise ValueError(
                f"El rol '{role}' genera '{self._schemas[role].__name__}' pero se "
                f"solicitó '{getattr(schema, '__name__', schema)}': esquema y rol "
                "no coinciden (bug de wiring)."
            )

        mensajes = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        ultimo_error: Optional[Exception] = None
        for intento in range(1, self._retry_policy.max_retries + 1):
            try:
                resultado = self._structured[role].invoke(mensajes)
            except Exception as exc:  # noqa: BLE001 - reintentamos cualquier fallo transitorio
                ultimo_error = exc
                logger.warning(
                    "Rol '%s': intento %s/%s falló (%s): %s",
                    role, intento, self._retry_policy.max_retries,
                    type(exc).__name__, exc,
                )
                if intento < self._retry_policy.max_retries:
                    time.sleep(self._retry_policy.backoff_seconds * intento)
                continue
            if not isinstance(resultado, schema):
                raise RuntimeError(
                    f"El rol '{role}' devolvió '{type(resultado).__name__}' en lugar "
                    f"de '{schema.__name__}': salida estructurada corrupta."
                )
            return resultado
        raise RuntimeError(
            f"El LLM del rol '{role}' falló tras "
            f"{self._retry_policy.max_retries} intentos: {ultimo_error}"
        ) from ultimo_error


def _roles_con_cliente(project: ProjectSpec) -> list[str]:
    """Roles que necesitan cliente LLM para este proyecto.

    Con ``[flujo]`` declarado la lista manda: solo los roles del flujo
    EFECTIVO (``resolver_flujo``, ya truncado por ``hasta``) obtienen cliente;
    un rol fuera del flujo no exige clave de proveedor. Sin ``[flujo]`` rige
    la semántica legacy: el flujo implícito contiene a los seis roles y
    ``activo = false`` decide quién cortocircuita (también sin cliente).
    La intersección cubre además el override ``--hasta`` del CLI sobre un
    proyecto legacy: los roles truncados por el hito tampoco necesitan cliente.
    """
    flujo = resolver_flujo(project)
    en_flujo = set(flujo.roles_completos())
    if flujo.declarado:
        return [rol for rol in definiciones_del_proyecto(project) if rol in en_flujo]
    return [
        rol for rol in ROLE_SCHEMAS
        if rol in en_flujo and project.agente_activo(rol)
    ]


def _esquemas_del_proyecto(project: ProjectSpec) -> Mapping[str, Type[BaseModel]]:
    """Catálogo rol -> contrato del proyecto: registro global + customs."""
    return {
        **ROLE_SCHEMAS,
        **{
            rol: definicion.esquema
            for rol, definicion in definiciones_del_proyecto(project).items()
        },
    }


def build_gateway(
    project: Optional[ProjectSpec] = None,
    role_clients: Optional[Mapping[str, BaseChatModel]] = None,
    retry_policy: Optional[RetryPolicy] = None,
) -> LangChainStructuredGateway:
    """Composition helper: resuelve clientes por rol y devuelve el gateway.

    Con ``project``, aplica los overrides ``[agentes.<rol>]`` del proyecto
    (precedencia proyecto > entorno > default) y construye clientes solo para
    los roles del flujo efectivo: un rol que no corre (fuera del ``[flujo]``,
    truncado por ``hasta`` o desactivado en un proyecto legacy) no exige su
    clave de proveedor. Los agentes custom aportan su contrato genérico al
    catálogo de esquemas del gateway.
    """
    schemas: Optional[Mapping[str, Type[BaseModel]]] = None
    if role_clients is None:
        overrides = project.agentes if project is not None else None
        solo_roles = _roles_con_cliente(project) if project is not None else None
        role_clients = build_role_clients(overrides=overrides, solo_roles=solo_roles)
    if project is not None:
        schemas = _esquemas_del_proyecto(project)
    return LangChainStructuredGateway(dict(role_clients), retry_policy, schemas)

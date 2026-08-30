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

from sinnema.application.ports import ROLE_SCHEMAS
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
    ) -> None:
        self._retry_policy = retry_policy or RetryPolicy()

        roles_solicitados = set(clients)
        roles_conocidos = set(ROLE_SCHEMAS)
        desconocidos = sorted(roles_solicitados - roles_conocidos)
        if desconocidos:
            raise ValueError(
                f"Clientes LLM con roles desconocidos: {desconocidos}. "
                f"Roles válidos: {sorted(roles_conocidos)}."
            )
        faltantes = sorted(roles_conocidos - roles_solicitados)
        if faltantes:
            raise ValueError(
                f"Faltan clientes LLM para los roles: {faltantes}. "
                "El grafo necesita un cliente por rol."
            )

        self._structured: Dict[str, Any] = {
            role: clients[role].with_structured_output(ROLE_SCHEMAS[role])
            for role in ROLE_SCHEMAS
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
                f"Rol desconocido '{role}'. Roles válidos: {sorted(self._structured)}."
            )
        if schema is not ROLE_SCHEMAS[role]:
            raise ValueError(
                f"El rol '{role}' genera '{ROLE_SCHEMAS[role].__name__}' pero se "
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


def build_gateway(
    role_clients: Optional[Mapping[str, BaseChatModel]] = None,
    retry_policy: Optional[RetryPolicy] = None,
) -> LangChainStructuredGateway:
    """Composition helper: resuelve clientes por rol y devuelve el gateway."""
    clients = dict(role_clients) if role_clients is not None else build_role_clients()
    return LangChainStructuredGateway(clients, retry_policy)

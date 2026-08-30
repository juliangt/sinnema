"""Resolución de proveedores LLM por rol: specs por defecto, overrides de
entorno y cadena de fallback entre proveedores.

Este módulo es el único lugar del sistema que conoce paquetes concretos de
LangChain (``langchain-anthropic``, ``langchain-openai``, ...).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, Tuple

from langchain_core.language_models.chat_models import BaseChatModel

# --- Clientes LLM por proveedor (imports con guarda para instalar solo lo usado) ---
try:
    from langchain_anthropic import ChatAnthropic
except ImportError:  # pragma: no cover
    ChatAnthropic = None  # type: ignore[assignment]

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover
    ChatOpenAI = None  # type: ignore[assignment]

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:  # pragma: no cover
    ChatGoogleGenerativeAI = None  # type: ignore[assignment]

try:
    from langchain_ollama import ChatOllama
except ImportError:  # pragma: no cover
    ChatOllama = None  # type: ignore[assignment]

logger = logging.getLogger("sinnema.infrastructure.providers")

PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_GOOGLE = "google"
PROVIDER_OLLAMA = "ollama"


@dataclass(frozen=True)
class RoleSpec:
    """Asignación por defecto de proveedor/modelo para un rol de agente."""

    role: str
    provider: str
    model: str
    temperature: float
    fallback_providers: Tuple[str, ...] = ()

    def with_overrides(self, provider: str, model: str) -> "RoleSpec":
        return RoleSpec(
            self.role, provider, model, self.temperature, self.fallback_providers
        )


#: Razonamiento analítico (planificación/crítica) en Claude; redacción/adaptación
#: rápidas en GPT-4o; traducción visual en Gemini. Ollama como refugio local.
DEFAULT_ROLE_SPECS: Tuple[RoleSpec, ...] = (
    RoleSpec("planner", PROVIDER_ANTHROPIC, "claude-3-5-sonnet-latest", 0.2, ("openai", "google", "ollama")),
    RoleSpec("continuity", PROVIDER_OPENAI, "gpt-4o-mini", 0.1, ("anthropic", "google", "ollama")),
    RoleSpec("scriptwriter", PROVIDER_OPENAI, "gpt-4o", 0.8, ("anthropic", "google", "ollama")),
    RoleSpec("adapter", PROVIDER_OPENAI, "gpt-4o-mini", 0.7, ("anthropic", "google", "ollama")),
    RoleSpec("critic", PROVIDER_ANTHROPIC, "claude-3-5-sonnet-latest", 0.0, ("openai", "google", "ollama")),
    RoleSpec("technical_director", PROVIDER_GOOGLE, "gemini-1.5-pro", 0.4, ("openai", "anthropic", "ollama")),
)


def provider_available(provider: str) -> bool:
    """True si el paquete del proveedor está instalado y hay credenciales."""
    if provider == PROVIDER_ANTHROPIC:
        return ChatAnthropic is not None and bool(os.getenv("ANTHROPIC_API_KEY"))
    if provider == PROVIDER_OPENAI:
        return ChatOpenAI is not None and bool(os.getenv("OPENAI_API_KEY"))
    if provider == PROVIDER_GOOGLE:
        return ChatGoogleGenerativeAI is not None and bool(
            os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        )
    if provider == PROVIDER_OLLAMA:
        return ChatOllama is not None  # servidor local; sin clave requerida
    return False


def build_provider_model(provider: str, model: str, temperature: float) -> BaseChatModel:
    """Construye el cliente concreto de un proveedor dado."""
    if provider == PROVIDER_ANTHROPIC:
        if ChatAnthropic is None:
            raise RuntimeError("langchain-anthropic no está instalado.")
        return ChatAnthropic(model=model, temperature=temperature, timeout=60, max_retries=2)
    if provider == PROVIDER_OPENAI:
        if ChatOpenAI is None:
            raise RuntimeError("langchain-openai no está instalado.")
        return ChatOpenAI(model=model, temperature=temperature, timeout=60, max_retries=2)
    if provider == PROVIDER_GOOGLE:
        if ChatGoogleGenerativeAI is None:
            raise RuntimeError("langchain-google-genai no está instalado.")
        return ChatGoogleGenerativeAI(model=model, temperature=temperature)
    if provider == PROVIDER_OLLAMA:
        if ChatOllama is None:
            raise RuntimeError("langchain-ollama no está instalado.")
        return ChatOllama(model=model, temperature=temperature)
    raise RuntimeError(f"Proveedor desconocido: '{provider}'.")


def apply_env_overrides(spec: RoleSpec) -> RoleSpec:
    """Permite sobreescribir proveedor/modelo por rol: LLM_PROVIDER_<ROL>,
    LLM_MODEL_<ROL> (ej: LLM_PROVIDER_SCRIPTWRITER=ollama)."""
    sufijo = spec.role.upper()
    provider = os.getenv(f"LLM_PROVIDER_{sufijo}", spec.provider).strip().lower()
    model = os.getenv(f"LLM_MODEL_{sufijo}", spec.model).strip()
    return spec.with_overrides(provider, model)


def build_role_clients(
    role_specs: Tuple[RoleSpec, ...] = DEFAULT_ROLE_SPECS,
) -> Dict[str, BaseChatModel]:
    """Resuelve un cliente LLM por rol, con cadena de fallback entre proveedores.

    Lanza ``RuntimeError`` con instrucciones accionables si algún rol se queda
    sin proveedor utilizable.
    """
    clientes: Dict[str, BaseChatModel] = {}
    for spec_bruto in role_specs:
        spec = apply_env_overrides(spec_bruto)
        candidatos = (spec.provider,) + tuple(
            p for p in spec.fallback_providers if p != spec.provider
        )
        for proveedor in candidatos:
            if not provider_available(proveedor):
                continue
            clientes[spec.role] = build_provider_model(
                proveedor, spec.model, spec.temperature
            )
            if proveedor != spec.provider:
                logger.warning(
                    "Rol '%s': proveedor '%s' no disponible; usando fallback '%s' (%s).",
                    spec.role, spec.provider, proveedor, spec.model,
                )
            else:
                logger.info(
                    "Rol '%s' -> %s / %s (temp=%.2f)",
                    spec.role, proveedor, spec.model, spec.temperature,
                )
            break
        else:
            raise RuntimeError(
                f"No hay proveedor LLM disponible para el rol '{spec.role}'. "
                "Configura al menos una de las variables ANTHROPIC_API_KEY, "
                "OPENAI_API_KEY, GOOGLE_API_KEY (o un servidor Ollama local), "
                f"o define LLM_PROVIDER_{spec.role.upper()} hacia un proveedor activo."
            )
    return clientes

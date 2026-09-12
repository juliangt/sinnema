"""Resolución de proveedores LLM por rol: specs por defecto, overrides de
entorno y cadena de fallback entre proveedores.

Este módulo es el único lugar del sistema que conoce paquetes concretos de
LangChain (``langchain-anthropic``, ``langchain-openai``, ...).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from langchain_core.language_models.chat_models import BaseChatModel

from sinnema.application.projects import AgentConfig

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

#: Orden canónico de los proveedores para los catálogos de la API.
PROVEEDORES: Tuple[str, ...] = (
    PROVIDER_ANTHROPIC, PROVIDER_OPENAI, PROVIDER_GOOGLE, PROVIDER_OLLAMA,
)


@dataclass(frozen=True)
class RoleSpec:
    """Asignación por defecto de proveedor/modelo para un rol de agente.

    ``top_p``/``max_tokens`` ``None`` = sin override: no se pasan al
    constructor y rige el default del proveedor (igual que la temperatura,
    que siempre tiene valor por defecto en el spec del rol).
    """

    role: str
    provider: str
    model: str
    temperature: float
    fallback_providers: Tuple[str, ...] = ()
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None

    def with_overrides(self, provider: str, model: str) -> "RoleSpec":
        return RoleSpec(
            self.role, provider, model, self.temperature,
            self.fallback_providers, self.top_p, self.max_tokens,
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

#: Default genérico para agentes CUSTOM sin asignación propia en
#: ``DEFAULT_ROLE_SPECS``: un modelo barato y versátil, con la misma cadena de
#: fallback. El proyecto puede sobreescribirlo vía [agentes.<rol>] o entorno.
DEFAULT_CUSTOM_ROLE_SPEC = RoleSpec(
    "<custom>", PROVIDER_OPENAI, "gpt-4o-mini", 0.3,
    ("anthropic", "google", "ollama"),
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


#: Nombre del parámetro de límite de tokens de salida por constructor.
_PARAM_MAX_TOKENS = {
    PROVIDER_ANTHROPIC: "max_tokens",
    PROVIDER_OPENAI: "max_tokens",
    PROVIDER_GOOGLE: "max_output_tokens",
    PROVIDER_OLLAMA: "num_predict",
}


def _generation_kwargs(
    provider: str, top_p: Optional[float], max_tokens: Optional[int]
) -> Dict[str, Any]:
    """Traduce ``top_p``/``max_tokens`` al nombre de cada constructor.

    Los parámetros ausentes no se pasan: rige el default del proveedor.
    (``ChatOllama`` llama ``num_predict`` al límite de salida; Google,
    ``max_output_tokens``.)
    """
    kwargs: Dict[str, Any] = {}
    if top_p is not None:
        kwargs["top_p"] = top_p
    if max_tokens is not None:
        kwargs[_PARAM_MAX_TOKENS[provider]] = max_tokens
    return kwargs


def build_provider_model(
    provider: str,
    model: str,
    temperature: float,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> BaseChatModel:
    """Construye el cliente concreto de un proveedor dado.

    ``top_p``/``max_tokens`` opcionales se pasan al constructor con el nombre
    que cada paquete espera (ver ``_generation_kwargs``); ausentes = default
    del proveedor.
    """
    extra = _generation_kwargs(provider, top_p, max_tokens)
    if provider == PROVIDER_ANTHROPIC:
        if ChatAnthropic is None:
            raise RuntimeError("langchain-anthropic no está instalado.")
        return ChatAnthropic(
            model=model, temperature=temperature, timeout=60, max_retries=2,
            **extra,
        )
    if provider == PROVIDER_OPENAI:
        if ChatOpenAI is None:
            raise RuntimeError("langchain-openai no está instalado.")
        return ChatOpenAI(
            model=model, temperature=temperature, timeout=60, max_retries=2,
            **extra,
        )
    if provider == PROVIDER_GOOGLE:
        if ChatGoogleGenerativeAI is None:
            raise RuntimeError("langchain-google-genai no está instalado.")
        return ChatGoogleGenerativeAI(model=model, temperature=temperature, **extra)
    if provider == PROVIDER_OLLAMA:
        if ChatOllama is None:
            raise RuntimeError("langchain-ollama no está instalado.")
        return ChatOllama(model=model, temperature=temperature, **extra)
    raise RuntimeError(f"Proveedor desconocido: '{provider}'.")


def apply_env_overrides(spec: RoleSpec) -> RoleSpec:
    """Permite sobreescribir proveedor/modelo por rol: LLM_PROVIDER_<ROL>,
    LLM_MODEL_<ROL> (ej: LLM_PROVIDER_SCRIPTWRITER=ollama)."""
    sufijo = spec.role.upper()
    provider = os.getenv(f"LLM_PROVIDER_{sufijo}", spec.provider).strip().lower()
    model = os.getenv(f"LLM_MODEL_{sufijo}", spec.model).strip()
    return spec.with_overrides(provider, model)


def default_role_spec(rol: str) -> RoleSpec:
    """Spec por defecto de cualquier rol: del registro o el genérico custom."""
    for spec in DEFAULT_ROLE_SPECS:
        if spec.role == rol:
            return spec
    return RoleSpec(
        rol,
        DEFAULT_CUSTOM_ROLE_SPEC.provider,
        DEFAULT_CUSTOM_ROLE_SPEC.model,
        DEFAULT_CUSTOM_ROLE_SPEC.temperature,
        DEFAULT_CUSTOM_ROLE_SPEC.fallback_providers,
    )


def resolve_role_spec(spec: RoleSpec, config: AgentConfig) -> RoleSpec:
    """Precedencia completa de un rol: proyecto > entorno > default.

    ``top_p``/``max_tokens`` solo vienen del proyecto (el entorno cubre
    únicamente proveedor/modelo): sin override declarado quedan ``None`` y no
    se pasan al constructor.
    """
    base = apply_env_overrides(spec)
    return RoleSpec(
        role=base.role,
        provider=config.proveedor or base.provider,
        model=config.modelo or base.model,
        temperature=(
            config.temperatura
            if config.temperatura is not None
            else base.temperature
        ),
        fallback_providers=base.fallback_providers,
        top_p=config.top_p,
        max_tokens=config.max_tokens,
    )


def build_role_clients(
    role_specs: Tuple[RoleSpec, ...] = DEFAULT_ROLE_SPECS,
    overrides: Optional[Mapping[str, AgentConfig]] = None,
    solo_roles: Optional[Iterable[str]] = None,
) -> Dict[str, BaseChatModel]:
    """Resuelve un cliente LLM por rol, con cadena de fallback entre proveedores.

    ``overrides`` aplica la configuración ``[agentes.<rol>]`` del proyecto y
    ``solo_roles`` limita qué roles obtienen cliente (los desactivados por el
    proyecto no necesitan proveedor). Lanza ``RuntimeError`` con instrucciones
    accionables si algún rol solicitado se queda sin proveedor utilizable.
    """
    overrides = overrides or {}
    clientes: Dict[str, BaseChatModel] = {}
    # Los roles sin spec propio (agentes custom) reciben el default genérico;
    # los overrides [agentes.<rol>] y el entorno los sobreescriben después.
    specs: list = list(role_specs)
    if solo_roles is not None:
        cubiertos = {spec.role for spec in specs}
        for rol in solo_roles:
            if rol not in cubiertos:
                logger.info(
                    "Rol '%s' es custom: usando el default LLM genérico "
                    "(%s / %s).", rol,
                    DEFAULT_CUSTOM_ROLE_SPEC.provider,
                    DEFAULT_CUSTOM_ROLE_SPEC.model,
                )
                specs.append(default_role_spec(rol))
    for spec_bruto in specs:
        if solo_roles is not None and spec_bruto.role not in solo_roles:
            continue
        spec = resolve_role_spec(spec_bruto, overrides.get(spec_bruto.role, AgentConfig()))
        candidatos = (spec.provider,) + tuple(
            p for p in spec.fallback_providers if p != spec.provider
        )
        for proveedor in candidatos:
            if not provider_available(proveedor):
                continue
            clientes[spec.role] = build_provider_model(
                proveedor, spec.model, spec.temperature,
                top_p=spec.top_p, max_tokens=spec.max_tokens,
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

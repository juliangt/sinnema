"""Puertos (interfaces) que la aplicación necesita del mundo exterior.

La regla de dependencias de la arquitectura hexagonal apunta hacia dentro:
``infrastructure`` implementa estos puertos; ``application`` jamás importa un
adaptador concreto. Así el grafo se puede testear con dobles en memoria.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Final, Optional, Protocol, Sequence, Type, TypeVar

from pydantic import BaseModel

from sinnema.domain.models import (
    AdaptedScript,
    ContinuityDirectives,
    LoreEntry,
    QualityAudit,
    ScriptDraft,
    SeriesPlan,
    TechnicalPackage,
)

#: Roles de agente del pipeline (también sufijo de las variables de entorno
#: ``LLM_PROVIDER_<ROL>`` / ``LLM_MODEL_<ROL>``).
ROLE_PLANNER: Final = "planner"
ROLE_CONTINUITY: Final = "continuity"
ROLE_SCRIPTWRITER: Final = "scriptwriter"
ROLE_ADAPTER: Final = "adapter"
ROLE_CRITIC: Final = "critic"
ROLE_DIRECTOR: Final = "technical_director"

#: Esquema estructurado que cada rol debe devolver. Un solo lugar conecta
#: roles con sus contratos de dominio; el adaptador LLM lo usa para configurar
#: ``with_structured_output`` y para detectar wiring erróneo.
ROLE_SCHEMAS: Final[Dict[str, Type[BaseModel]]] = {
    ROLE_PLANNER: SeriesPlan,
    ROLE_CONTINUITY: ContinuityDirectives,
    ROLE_SCRIPTWRITER: ScriptDraft,
    ROLE_ADAPTER: AdaptedScript,
    ROLE_CRITIC: QualityAudit,
    ROLE_DIRECTOR: TechnicalPackage,
}

TSchema = TypeVar("TSchema", bound=BaseModel)


class AuditTrailPort(Protocol):
    """Puerto de auditoría de ejecución: registra qué hace el pipeline, paso a paso.

    La aplicación emite eventos a medida que avanza; el adaptador decide cómo
    persistirlos (p. ej. una carpeta de archivos de texto por ejecución). La
    auditoría es observadora: nunca altera el resultado ni puede tumbar la
    ejecución.
    """

    def log_step(
        self,
        step: str,
        summary: str,
        artifact: Optional[BaseModel] = None,
        details: Optional[Sequence[str]] = None,
    ) -> None:
        """Registra un paso completado (una generación, un commit, un fallo...)."""
        ...

    def log_event(self, message: str) -> None:
        """Registra un evento puntual solo en el log cronológico."""
        ...

    def log_failure(self, message: str) -> None:
        """Registra un fallo que degrada o aborta la ejecución."""
        ...


class NullAuditTrail:
    """Implementación no-op para cuando no se requiere auditoría."""

    def log_step(
        self,
        step: str,
        summary: str,
        artifact: Optional[BaseModel] = None,
        details: Optional[Sequence[str]] = None,
    ) -> None:
        return None

    def log_event(self, message: str) -> None:
        return None

    def log_failure(self, message: str) -> None:
        return None


class LoreStorePort(Protocol):
    """Puerto de persistencia del lore: la continuidad de cada proyecto.

    La memoria de continuidad vive ANTES y DESPUÉS de cada corrida: cargarla
    al empezar y guardarla al terminar es política de la aplicación; cómo y
    dónde se guarda es cosa del adaptador (p. ej. un JSON por proyecto).
    """

    def load(self, project_id: str) -> List[LoreEntry]:
        """Devuelve el lore acumulado del proyecto (vacío si no hay historia)."""
        ...

    def save(self, project_id: str, entries: List[LoreEntry]) -> None:
        """Reemplaza el lore almacenado del proyecto por ``entries``."""
        ...


class NullLoreStore:
    """Implementación no-op: cada corrida arranca sin memoria y no persiste."""

    def load(self, project_id: str) -> List[LoreEntry]:
        return []

    def save(self, project_id: str, entries: List[LoreEntry]) -> None:
        return None


#: Evento de generación en vivo (spec-red-3d §7.1): ``{"tipo": "token"|"tool_start"|
#: "tool_end", ...}``. ``token`` lleva ``texto``; ``tool_start`` lleva ``tool`` y
#: ``args``; ``tool_end`` lleva ``tool`` y ``resumen``.
EventoGeneracion = Dict[str, Any]

#: Callback opcional de streaming que consume el adaptador por cada evento.
EventCallback = Callable[[EventoGeneracion], None]


class StructuredGenerationPort(Protocol):
    """Puerto de generación estructurada por rol de agente.

    Recibe prompts ya construidos (política de aplicación) y devuelve una
    instancia validada del esquema solicitado. Las reintentos y el transporte
    son responsabilidad del adaptador que implemente el puerto.
    """

    def generate(
        self,
        role: str,
        schema: Type[TSchema],
        system_prompt: str,
        user_prompt: str,
        *,
        on_event: Optional[EventCallback] = None,
    ) -> TSchema:
        """Invoca el LLM del rol y devuelve una instancia de ``schema``.

        Con ``on_event`` el adaptador puede emitir eventos de generación
        (tokens de streaming, tools); es opcional con default ``None``: el
        camino sin eventos es exactamente el de siempre (§12.2).
        """
        ...

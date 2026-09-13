"""Puertos (interfaces) que la aplicación necesita del mundo exterior.

La regla de dependencias de la arquitectura hexagonal apunta hacia dentro:
``infrastructure`` implementa estos puertos; ``application`` jamás importa un
adaptador concreto. Así el grafo se puede testear con dobles en memoria.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Final, Optional, Protocol, Sequence, Type, TypeVar

from pydantic import BaseModel

from sinnema.domain.models import (
    AdaptedScript,
    ContinuityDirectives,
    LoreEntry,
    MediaCrudo,
    PedidoKeyframe,
    QualityAudit,
    RecursoAncla,
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

    def log_prompts(self, step: str, contenido: str) -> None:
        """Registra los prompts de un paso de agente (spec-red-3d §7.4).

        Es un método opcional del contrato: los adaptadores que no lo
        implementan simplemente no alimentan el inspector de prompts.
        """
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


class AnchorStorePort(Protocol):
    """Puerto de la biblioteca de recursos ancla de cada proyecto.

    La biblioteca (spec-recursos-ancla §4.2) vive ANTES de cada corrida: la
    siembra y lockea una persona desde la web, y el pipeline solo la lee.
    Cómo y dónde se guarda es cosa del adaptador (p. ej. un JSON + carpeta
    de media por proyecto).
    """

    def load(self, project_id: str) -> List[RecursoAncla]:
        """Devuelve las anclas del proyecto (vacío si no hay biblioteca)."""
        ...

    def save(self, project_id: str, anclas: List[RecursoAncla]) -> None:
        """Reemplaza la biblioteca almacenada del proyecto por ``anclas``."""
        ...


class NullAnchorStore:
    """Implementación no-op: cada corrida ve una biblioteca vacía y no persiste."""

    def load(self, project_id: str) -> List[RecursoAncla]:
        return []

    def save(self, project_id: str, anclas: List[RecursoAncla]) -> None:
        return None


#: Evento de generación en vivo (spec-red-3d §7.1): ``{"tipo": "token"|"tool_start"|
#: "tool_end", ...}``. ``token`` lleva ``texto``; ``tool_start`` lleva ``tool`` y
#: ``args``; ``tool_end`` lleva ``tool`` y ``resumen``.
EventoGeneracion = Dict[str, Any]

#: Callback opcional de streaming que consume el adaptador por cada evento.
EventCallback = Callable[[EventoGeneracion], None]


class MediaGenerationPort(Protocol):
    """Puerto de generación de media (spec-recursos-ancla §6).

    El nodo estructural ``render_keyframes`` compone un ``PedidoKeyframe`` por
    escena y lo entrega aquí; el adaptador concreto (Gemini image, OpenAI
    gpt-image-1, ...) traduce las referencias al payload nativo vía su
    resolver, reintenta fallos de transporte y devuelve los bytes crudos con
    su manifest de procedencia. NUNCA escribe archivos: persistir es política
    de la aplicación (nodo + ``MediaStorePort``).

    Degradación elegante (mismo espíritu que los proveedores LLM): el
    adaptador se construye sin claves ni SDK instalado; usarlo lanza un
    ``RuntimeError`` con instrucciones accionables.
    """

    def generar_keyframe(
        self,
        pedido: PedidoKeyframe,
        catalogo: Sequence[RecursoAncla],
    ) -> MediaCrudo:
        """Genera el keyframe de la escena del pedido.

        ``catalogo`` es la biblioteca lockeada del proyecto (el slot
        ``anclas`` del estado): el resolver del adaptador resuelve cada
        ``ancla_id`` contra él y verifica los máximos del proveedor ANTES de
        la llamada (excederlos es un error de wiring local, ``ValueError`` —
        §11.3 —, no un fallo remoto).
        """
        ...


class MediaStorePort(Protocol):
    """Puerto de persistencia del media generado por el pipeline.

    El nodo ``render_keyframes`` le entrega los bytes que devolvió el puerto
    de generación; cómo y dónde se guardan es cosa del adaptador (p. ej.
    ``media/<project_id>/<chapter_id>/escena_<n>.<ext>`` bajo la raíz de
    datos). Devuelve la ruta relativa (portable) que viaja en
    ``MediaGenerado.archivo``.
    """

    def guardar_keyframe(
        self,
        project_id: str,
        chapter_id: str,
        escena: int,
        formato: str,
        datos: bytes,
    ) -> str:
        """Escribe el keyframe y devuelve su ruta relativa bajo la raíz de media."""
        ...


@dataclass(frozen=True)
class DependenciasMedia:
    """Paquete de media inyectable en el grafo (opcional, spec §6/Hito 3).

    ``None`` en el use case/grafo = corrida sin capa de media (nodo
    ``render_keyframes`` ni se inserta: paridad con el pipeline de siempre).
    ``eventos`` es el canal en vivo de progreso: el nodo emite
    ``{"tipo": "media_start"|"media_end", "escena": n, "proveedor": ...}`` y
    el runner lo traduce a los eventos del job que llegan a SSE.
    """

    puerto: MediaGenerationPort
    almacen: MediaStorePort
    eventos: Optional[Callable[[Dict[str, Any]], None]] = None


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

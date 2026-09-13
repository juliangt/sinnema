"""Contratos de datos del dominio (Pydantic v2, structured outputs).

Re-exporta todos los esquemas para mantener una superficie de importación
estable (``from sinnema.domain.models import ScriptDraft``).
"""
from sinnema.domain.models.anclas import (
    EstadoDeAncla,
    ImagenAncla,
    ManifestDeGeneracion,
    RecursoAncla,
    ReferenciaAncla,
    RolDeImagen,
    TipoDeAncla,
)
from sinnema.domain.models.audit import AuditCriterion, AuditFinding, QualityAudit
from sinnema.domain.models.content import (
    AdaptedScene,
    AdaptedScript,
    Scene,
    ScriptDraft,
    Transition,
)
from sinnema.domain.models.continuity import (
    AnclaDelCapitulo,
    ContinuityDirectives,
    LoreEntry,
)
from sinnema.domain.models.media import (
    ErrorDeMedia,
    MediaCrudo,
    MediaDelEpisodio,
    MediaGenerado,
    PedidoKeyframe,
)
from sinnema.domain.models.deliverable import (
    ApprovedEpisode,
    ArtefactoAdjunto,
    FailedChapterRecord,
    FinalScene,
    SeriesDeliverable,
)
from sinnema.domain.models.genericos import NotasDelAgente, TextoLibre
from sinnema.domain.models.planning import ChapterOutline, SeriesPlan
from sinnema.domain.models.project import AspectRatio, FormatProfile
from sinnema.domain.models.technical import (
    AudioDirection,
    TechnicalPackage,
    VisualAssetSpec,
)

__all__ = [
    "AdaptedScene",
    "AdaptedScript",
    "AnclaDelCapitulo",
    "ApprovedEpisode",
    "AspectRatio",
    "AudioDirection",
    "AuditCriterion",
    "AuditFinding",
    "ChapterOutline",
    "ContinuityDirectives",
    "EstadoDeAncla",
    "FailedChapterRecord",
    "FinalScene",
    "FormatProfile",
    "ImagenAncla",
    "ErrorDeMedia",
    "LoreEntry",
    "ManifestDeGeneracion",
    "MediaCrudo",
    "MediaDelEpisodio",
    "MediaGenerado",
    "NotasDelAgente",
    "PedidoKeyframe",
    "QualityAudit",
    "RecursoAncla",
    "ReferenciaAncla",
    "RolDeImagen",
    "Scene",
    "ScriptDraft",
    "SeriesDeliverable",
    "SeriesPlan",
    "TechnicalPackage",
    "TextoLibre",
    "TipoDeAncla",
    "Transition",
    "VisualAssetSpec",
]

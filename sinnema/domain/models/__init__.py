"""Contratos de datos del dominio (Pydantic v2, structured outputs).

Re-exporta todos los esquemas para mantener una superficie de importación
estable (``from sinnema.domain.models import ScriptDraft``).
"""
from sinnema.domain.models.audit import AuditCriterion, AuditFinding, QualityAudit
from sinnema.domain.models.content import (
    AdaptedScene,
    AdaptedScript,
    Scene,
    ScriptDraft,
    Transition,
)
from sinnema.domain.models.continuity import ContinuityDirectives, LoreEntry
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
    "ApprovedEpisode",
    "AspectRatio",
    "AudioDirection",
    "AuditCriterion",
    "AuditFinding",
    "ChapterOutline",
    "ContinuityDirectives",
    "FailedChapterRecord",
    "FinalScene",
    "FormatProfile",
    "LoreEntry",
    "NotasDelAgente",
    "QualityAudit",
    "Scene",
    "ScriptDraft",
    "SeriesDeliverable",
    "SeriesPlan",
    "TechnicalPackage",
    "TextoLibre",
    "Transition",
    "VisualAssetSpec",
]

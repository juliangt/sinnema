"""Servicios de dominio: lógica de negocio pura sobre las entidades."""
from sinnema.domain.services.assembly import (
    assemble_episode,
    build_failed_record,
    identity_adaptation,
    validate_adaptation_matches_draft,
    validate_package_matches_draft,
    validate_plan_size,
)
from sinnema.domain.services.format import (
    validate_adaptation_format,
    validate_audit_verdict,
    validate_draft_format,
    validate_package_format,
    validate_plan_format,
)
from sinnema.domain.services.lore import extract_new_lore, merge_lore

__all__ = [
    "assemble_episode",
    "build_failed_record",
    "extract_new_lore",
    "identity_adaptation",
    "merge_lore",
    "validate_adaptation_format",
    "validate_adaptation_matches_draft",
    "validate_audit_verdict",
    "validate_draft_format",
    "validate_package_format",
    "validate_package_matches_draft",
    "validate_plan_format",
    "validate_plan_size",
]

"""Servicios de dominio: lógica de negocio pura sobre las entidades."""
from sinnema.domain.services.anclas import (
    anclas_referenciadas,
    cobertura_casting,
    proponer_casting,
    registrar_vigencia_de_anclas,
    slug_de_termino,
    validate_anchor_refs,
    validate_continuity_anchors,
)
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
from sinnema.domain.services.media import (
    componer_pedido_escena,
    componer_prompt_final,
    escena_de_archivo,
    pares_identidad_primero,
)

__all__ = [
    "anclas_referenciadas",
    "assemble_episode",
    "build_failed_record",
    "cobertura_casting",
    "componer_pedido_escena",
    "componer_prompt_final",
    "escena_de_archivo",
    "extract_new_lore",
    "identity_adaptation",
    "merge_lore",
    "pares_identidad_primero",
    "proponer_casting",
    "registrar_vigencia_de_anclas",
    "slug_de_termino",
    "validate_adaptation_format",
    "validate_adaptation_matches_draft",
    "validate_anchor_refs",
    "validate_audit_verdict",
    "validate_continuity_anchors",
    "validate_draft_format",
    "validate_package_format",
    "validate_package_matches_draft",
    "validate_plan_format",
    "validate_plan_size",
]

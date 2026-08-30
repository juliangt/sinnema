"""Ensamblaje de artefactos: consolida borrador + adaptación + specs técnicas.

También valida la coherencia cruzada entre artefactos que ninguno de los
contratos individuales puede verificar por sí solo (ids de capítulo y
numeración de escenas compartida entre agentes distintos).
"""
from __future__ import annotations

from typing import Optional

from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.models import (
    AdaptedScene,
    AdaptedScript,
    ApprovedEpisode,
    ChapterOutline,
    FailedChapterRecord,
    FinalScene,
    QualityAudit,
    ScriptDraft,
    TechnicalPackage,
)


def identity_adaptation(draft: ScriptDraft) -> AdaptedScript:
    """Adaptación identidad: el borrador pasa tal cual al siguiente agente.

    Se usa cuando el proyecto desactiva el adapter: el guion ya está escrito
    para la audiencia del proyecto (el prompt del guionista la incluye), así
    que la "adaptación" es conservar escena por escena el contenido original.
    """
    return AdaptedScript(
        chapter_id=draft.chapter_id,
        adapted_title=draft.title,
        adapted_hook=draft.hook,
        adapted_scenes=[
            AdaptedScene(
                scene_number=s.scene_number,
                narration=s.narration,
                on_screen_text=s.on_screen_text,
            )
            for s in draft.scenes
        ],
        adapted_cta=draft.call_to_action,
    )


def _mismo_chapter_id(esperado: str, artifacto: str, recibido: str) -> None:
    if recibido != esperado:
        raise DomainValidationError(
            f"El {artifacto} declara chapter_id '{recibido}' pero el capítulo en "
            f"curso es '{esperado}': los artefactos del episodio están mezclados."
        )


def validate_plan_size(plan, expected_chapters: int) -> None:
    """El planificador debe devolver exactamente los capítulos solicitados."""
    if len(plan.chapters) != expected_chapters:
        raise DomainValidationError(
            f"El plan de serie contiene {len(plan.chapters)} capítulo(s) pero se "
            f"solicitaron {expected_chapters}."
        )


def validate_adaptation_matches_draft(
    draft: ScriptDraft, adapted: AdaptedScript
) -> None:
    """La adaptación debe conservar exactamente las escenas del borrador."""
    _mismo_chapter_id(draft.chapter_id, "guión adaptado", adapted.chapter_id)
    base = {s.scene_number for s in draft.scenes}
    adaptadas = {s.scene_number for s in adapted.adapted_scenes}
    if adaptadas != base:
        faltantes = sorted(base - adaptadas)
        extra = sorted(adaptadas - base)
        raise DomainValidationError(
            "La adaptación no conserva la numeración de escenas del borrador "
            f"(faltantes: {faltantes}, añadidas: {extra})."
        )


def validate_package_matches_draft(
    draft: ScriptDraft, package: TechnicalPackage
) -> None:
    """El paquete técnico debe traer una spec por cada escena del borrador."""
    _mismo_chapter_id(draft.chapter_id, "paquete técnico", package.chapter_id)
    base = {s.scene_number for s in draft.scenes}
    specs = {s.scene_number for s in package.visual_specs}
    if specs != base:
        faltantes = sorted(base - specs)
        extra = sorted(specs - base)
        raise DomainValidationError(
            "El paquete técnico no cubre exactamente las escenas del borrador "
            f"(escenas sin spec: {faltantes}, specs de más: {extra})."
        )


def assemble_episode(
    *,
    chapter: ChapterOutline,
    order_index: int,
    draft: ScriptDraft,
    adapted: AdaptedScript,
    package: Optional[TechnicalPackage],
    audit: Optional[QualityAudit],
) -> ApprovedEpisode:
    """Consolida borrador + adaptación + specs técnicas en un episodio aprobado.

    ``package`` y ``audit`` pueden ser ``None`` (proyecto con el director
    técnico o el crítico desactivados): el episodio se ensambla igual, sin
    specs visuales o sin dictamen de calidad.
    """
    _mismo_chapter_id(chapter.chapter_id, "borrador", draft.chapter_id)
    validate_adaptation_matches_draft(draft, adapted)
    if package is not None:
        validate_package_matches_draft(draft, package)

    escenas_base = {s.scene_number: s for s in draft.scenes}
    escenas_adaptadas = {s.scene_number: s for s in adapted.adapted_scenes}
    specs = {s.scene_number: s for s in package.visual_specs} if package else {}

    escenas_finales = []
    for numero in sorted(escenas_base):
        base = escenas_base[numero]
        adaptada = escenas_adaptadas.get(numero)
        spec = specs.get(numero)
        escenas_finales.append(
            FinalScene(
                scene_number=numero,
                duration_seconds=base.duration_seconds,
                visual_action=base.visual_action,
                narration=adaptada.narration if adaptada else base.narration,
                on_screen_text=(
                    adaptada.on_screen_text
                    if adaptada and adaptada.on_screen_text
                    else base.on_screen_text
                ),
                transition=base.transition,
                image_prompt=spec.image_prompt if spec else "",
                negative_prompt=spec.negative_prompt if spec else "",
                motion_direction=spec.motion_direction if spec else "",
            )
        )

    return ApprovedEpisode(
        chapter_id=chapter.chapter_id,
        order_index=order_index,
        title=adapted.adapted_title,
        hook=adapted.adapted_hook,
        scenes=escenas_finales,
        call_to_action=adapted.adapted_cta,
        technical=package,
        audit=audit,
        forced_acceptance=audit is not None and not audit.approved,
    )


def build_failed_record(
    *,
    chapter: ChapterOutline,
    max_attempts: int,
    audit: Optional[QualityAudit],
) -> FailedChapterRecord:
    """Registra un capítulo descartado por política de reintentos agotados."""
    return FailedChapterRecord(
        chapter_id=chapter.chapter_id,
        title=chapter.title,
        reason=(
            f"QA rechazó el borrador {max_attempts} veces "
            f"(último score: {audit.overall_score if audit else 'n/d'}/10); "
            "política de reintentos agotados."
        ),
        last_feedback=audit.correction_feedback if audit else "",
    )

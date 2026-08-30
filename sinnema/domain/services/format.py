"""Validación de artefactos contra el perfil editorial del proyecto.

Los contratos Pydantic solo hacen cumplir los límites universales de sanidad;
este servicio aplica el sobre editorial concreto (``FormatProfile``) tras cada
generación, con el mismo estilo de fallo que el resto de validaciones cruzadas:
rápido, accionable y registrado en auditoría.
"""
from __future__ import annotations

from typing import List

from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.models import (
    AdaptedScript,
    QualityAudit,
    ScriptDraft,
    SeriesPlan,
    TechnicalPackage,
)
from sinnema.domain.models.project import FormatProfile


def validate_plan_format(plan: SeriesPlan, profile: FormatProfile) -> None:
    """Cada capítulo del plan declara un word_budget dentro del rango objetivo."""
    piso, techo = profile.narration_target_words
    fuera = [
        c.chapter_id for c in plan.chapters if not (piso <= c.word_budget <= techo)
    ]
    if fuera:
        raise DomainValidationError(
            f"Los capítulos {fuera} declaran un word_budget fuera del rango "
            f"editorial del proyecto ({piso}-{techo} palabras)."
        )


def validate_draft_format(draft: ScriptDraft, profile: FormatProfile) -> None:
    """El borrador respeta escenas, palabras y duraciones del perfil."""
    problemas = _problemas_de_formato(
        num_escenas=len(draft.scenes),
        palabras=draft.word_count,
        duracion_total=draft.total_duration_seconds,
        escenas=draft.scenes,
        perfil=profile,
        etiqueta="borrador",
    )
    if problemas:
        raise DomainValidationError(
            "El borrador viola el perfil editorial del proyecto: "
            + "; ".join(problemas)
            + "."
        )


def validate_adaptation_format(
    adapted: AdaptedScript, profile: FormatProfile
) -> None:
    """La adaptación respeta escenas y presupuesto de palabras del perfil."""
    texto_total = " ".join(
        [adapted.adapted_hook]
        + [s.narration for s in adapted.adapted_scenes]
        + [adapted.adapted_cta]
    )
    problemas = _problemas_de_formato(
        num_escenas=len(adapted.adapted_scenes),
        palabras=len(texto_total.split()),
        duracion_total=None,
        escenas=adapted.adapted_scenes,
        perfil=profile,
        etiqueta="adaptación",
    )
    if problemas:
        raise DomainValidationError(
            "La adaptación viola el perfil editorial del proyecto: "
            + "; ".join(problemas)
            + "."
        )


def validate_package_format(
    package: TechnicalPackage, profile: FormatProfile
) -> None:
    """El paquete técnico usa la relación de aspecto del proyecto y su rango
    de escenas (la alineación escena a escena con el borrador la verifica
    ``validate_package_matches_draft``)."""
    problemas: List[str] = []
    if package.aspect_ratio != profile.aspect_ratio:
        problemas.append(
            f"relación de aspecto {package.aspect_ratio} (el proyecto exige "
            f"{profile.aspect_ratio})"
        )
    piso, techo = profile.scenes_count
    if not (piso <= len(package.visual_specs) <= techo):
        problemas.append(
            f"specs visuales: {len(package.visual_specs)} (rango editorial {piso}-{techo})"
        )
    if problemas:
        raise DomainValidationError(
            "El paquete técnico viola el perfil editorial del proyecto: "
            + "; ".join(problemas)
            + "."
        )


def validate_audit_verdict(audit: QualityAudit, profile: FormatProfile) -> None:
    """Un dictamen aprobado exige el score mínimo que fijó el proyecto."""
    if audit.approved and audit.overall_score < profile.min_approval_score:
        raise DomainValidationError(
            f"Dictamen aprobado con score {audit.overall_score} por debajo del "
            f"mínimo del proyecto ({profile.min_approval_score})."
        )


# -----------------------------------------------------------------------------


def _problemas_de_formato(
    *,
    num_escenas: int,
    palabras: int,
    duracion_total: float,
    escenas,
    perfil: FormatProfile,
    etiqueta: str,
) -> List[str]:
    """Acumula todas las violaciones del perfil en una pasada."""
    problemas: List[str] = []

    piso_escenas, techo_escenas = perfil.scenes_count
    if not (piso_escenas <= num_escenas <= techo_escenas):
        problemas.append(
            f"escenas: {num_escenas} (rango editorial {piso_escenas}-{techo_escenas})"
        )

    piso_palabras, techo_palabras = perfil.narration_hard_words
    if not (piso_palabras <= palabras <= techo_palabras):
        problemas.append(
            f"palabras narradas: {palabras} (rango duro {piso_palabras}-{techo_palabras})"
        )

    if duracion_total is not None:
        piso_duracion, techo_duracion = perfil.total_duration_hard_seconds
        if not (piso_duracion <= duracion_total <= techo_duracion):
            problemas.append(
                f"duración total: {duracion_total:.1f} s "
                f"(rango duro {piso_duracion:.0f}-{techo_duracion:.0f} s)"
            )

    # Las escenas adaptadas no declaran duración propia (conservan la del
    # borrador): solo se verifican las que tienen el campo.
    piso_escena, techo_escena = perfil.scene_duration_seconds
    duraciones_invalidas = [
        s.scene_number
        for s in escenas
        if hasattr(s, "duration_seconds")
        and not (piso_escena <= s.duration_seconds <= techo_escena)
    ]
    if duraciones_invalidas:
        problemas.append(
            f"escenas con duración fuera de {piso_escena:.0f}-{techo_escena:.0f} s: "
            f"{duraciones_invalidas}"
        )

    narraciones_largas = [
        s.scene_number
        for s in escenas
        if len(s.narration.split()) > perfil.narration_max_words_per_scene
    ]
    if narraciones_largas:
        problemas.append(
            f"escenas que superan {perfil.narration_max_words_per_scene} palabras "
            f"de narración: {narraciones_largas}"
        )

    textos_pantalla_largos = [
        s.scene_number
        for s in escenas
        if s.on_screen_text
        and len(s.on_screen_text.split()) > perfil.on_screen_text_max_words
    ]
    if textos_pantalla_largos:
        problemas.append(
            f"escenas con texto en pantalla de más de "
            f"{perfil.on_screen_text_max_words} palabras: {textos_pantalla_largos}"
        )

    return problemas

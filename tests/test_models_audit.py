"""Tests de los contratos de auditoría de calidad (QualityAudit)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sinnema.domain.models import AuditFinding, QualityAudit

from conftest import make_audit


def test_dictamen_aprobado_valido():
    dictamen = make_audit(approved=True, score=9)
    assert dictamen.approved is True


def test_aprobado_con_hallazgo_bloqueante_rechazado():
    dictamen = make_audit(approved=True)
    datos = dictamen.model_dump()
    datos["findings"] = [
        AuditFinding(
            criterion="ritmo",
            severity="bloqueante",
            score=2,
            observation="Observación de prueba suficientemente extensa.",
            suggested_fix="Corrección concreta de prueba suficientemente extensa.",
        ).model_dump()
    ]
    with pytest.raises(ValidationError, match="bloqueantes"):
        QualityAudit(**datos)


def test_aprobado_con_score_bajo_aceptado_por_el_contrato():
    """El score mínimo de aprobación lo fija el perfil de cada proyecto y lo
    hace cumplir ``validate_audit_verdict`` (ver test_format_service); el
    contrato solo exige coherencia estructural."""
    dictamen = _dictamen_directo(approved=True, score=4)
    assert dictamen.approved is True


def test_aprobado_con_palabras_fuera_de_rango_rechazado():
    dictamen = make_audit(approved=True)
    datos = dictamen.model_dump()
    datos["word_count_status"] = "demasiado_corto"
    with pytest.raises(ValidationError, match="dentro_de_rango"):
        QualityAudit(**datos)


def test_rechazado_sin_motivo_rechazado():
    dictamen = make_audit(approved=False)
    datos = dictamen.model_dump()
    datos["findings"] = []
    datos["continuity_violations"] = []
    with pytest.raises(ValidationError, match="hallazgo o una violación"):
        QualityAudit(**datos)


def test_rechazado_con_violacion_de_continuidad_aceptado():
    dictamen = make_audit(approved=False)
    datos = dictamen.model_dump()
    datos["findings"] = []
    datos["continuity_violations"] = ["re-explica 'modelo' (ch-01)"]
    assert QualityAudit(**datos).approved is False


def _dictamen_directo(approved: bool, score: int) -> QualityAudit:
    """Construye un dictamen saltándose las comodidades de la fábrica."""
    return QualityAudit(
        approved=approved,
        overall_score=score,
        word_count_status="dentro_de_rango",
        pacing_verdict="El ritmo resulta ágil en todo el capítulo.",
        audience_fit_verdict="El registro encaja con el público objetivo.",
        continuity_violations=[],
        findings=[],
        correction_feedback="Corrección o resumen suficientemente largo.",
    )

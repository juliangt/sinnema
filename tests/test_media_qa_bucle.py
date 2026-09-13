"""Bucle acotado de regeneración por QA (Fase 4, spec-recursos-ancla §7).

Cubren: QA aprueba a la primera (1 intento), regeneración con escalado
(peso ↑, seed nueva) hasta aprobar, agotamiento con mejor candidato e informes
de TODOS los intentos adjuntos, ``intentos_qa = 0`` (QA informativo), dedup
con keyframes previos del capítulo y camino sin servicio de QA (paridad Fase 3).
"""
from __future__ import annotations

from conftest import gateway_con_serie, make_request

from sinnema.application.ports import DependenciasMedia
from sinnema.application.use_cases import GenerateSeriesUseCase
from sinnema.domain.models import InformeQaVisual

from test_media_pipeline import (
    AuditRegistrada,
    PuertoMediaFalso,
    _correr,
    _deps,
    _proyecto_media,
)

UMBRAL = 0.35


class QaFalso:
    """Doble de ``QaVisualPort``: scores guionados por llamada (global)."""

    def __init__(self, scores):
        # scores: lista de scores a devolver por llamada, en orden; el último
        # se repite si se agota. aprueba = score >= UMBRAL.
        self.scores = list(scores)
        self.llamadas = []

    def evaluar_keyframe(self, *, escena, project_id, prompt, datos_keyframe, pares, previos=()):
        self.llamadas.append({
            "escena": escena,
            "previos": list(previos),
            "prompt": prompt,
        })
        score = self.scores.pop(0) if len(self.scores) > 1 else self.scores[0]
        informe = InformeQaVisual(
            escena=escena,
            ancla_id="nita",
            metrica="cara_coseno",
            score=score,
            umbral=UMBRAL,
            aprueba=score >= UMBRAL,
            detalle="QA de juguete",
        )
        return [informe], []


def _correr_con_media(tmp_path, qa=None, **overrides_media):
    puerto = PuertoMediaFalso()
    audit = AuditRegistrada()
    eventos = []
    proyecto = _proyecto_media(**overrides_media)
    deps = DependenciasMedia(
        **{
            **_deps(puerto, tmp_path, eventos=eventos.append).__dict__,
            "qa": qa,
        }
    )
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(1), proyecto, audit=audit, media=deps
    )
    final = _correr(use_case, make_request(num_chapters=1, project=proyecto))
    episodio = final["completed_episodes"][0]
    adjunto = next(a for a in episodio.adjuntos if a.rol == "media")
    return puerto, audit, eventos, adjunto.artefacto


def _media_end_de(eventos, escena):
    return next(
        e for e in eventos
        if e["tipo"] == "media_end" and e["escena"] == escena and "archivo" in e
    )


# ============================ bucle §7 ============================


def test_qa_aprueba_a_la_primera_un_solo_intento(tmp_path):
    qa = QaFalso(scores=[0.9])
    puerto, audit, eventos, media = _correr_con_media(tmp_path, qa=qa)
    assert len(puerto.pedidos) == 6  # una generación por escena
    assert len(qa.llamadas) == 6
    assert all(kf["qa"] for kf in media["keyframes"])
    assert media["qa_agotado"] == []
    assert _media_end_de(eventos, 1)["qa"] == "aprobado"
    assert _media_end_de(eventos, 1)["intentos"] == 1
    # Ninguna mención de regeneración en la auditoría.
    assert not any("se regenera con escalado" in e for e in audit.eventos)


def test_qa_falla_una_vez_y_regenera_con_escalado(tmp_path):
    # Escena 1: intento 1 rechaza (0.10), intento 2 aprueba (0.80); el resto aprueba.
    qa = QaFalso(scores=[0.10, 0.80, 0.9])
    puerto, audit, eventos, media = _correr_con_media(tmp_path, qa=qa)
    # La escena 1 consumió 2 pedidos; las otras 5, uno.
    assert len(puerto.pedidos) == 7
    primero, segundo = puerto.pedidos[0], puerto.pedidos[1]
    assert primero.peso_referencia is None and primero.seed is None
    assert segundo.peso_referencia == 1.3  # escalado §7: peso ↑
    assert segundo.seed is not None
    assert qa.llamadas[0]["escena"] == 1
    # Auditoría registra el rechazo del primer intento.
    assert any("intento 1/2 de la escena 1 rechazado" in e for e in audit.eventos)
    # El keyframe entregado de la escena 1 lleva el informe que SÍ aprueba.
    kf1 = media["keyframes"][0]
    assert kf1["qa"][0]["score"] == 0.80
    assert media["qa_agotado"] == []
    fin1 = _media_end_de(eventos, 1)
    assert fin1["qa"] == "aprobado" and fin1["intentos"] == 2


def test_qa_agotado_entrega_mejor_candidato_con_informes_completos(tmp_path):
    # Escena 1: intento 1 (0.10), intento 2 (0.30): ambos bajo umbral → agotado.
    qa = QaFalso(scores=[0.10, 0.30, 0.9])
    puerto, audit, eventos, media = _correr_con_media(tmp_path, qa=qa)
    kf1 = media["keyframes"][0]
    assert kf1["qa"][0]["score"] == 0.30  # mejor (último) candidato entregado
    # Informes de TODOS los intentos quedan adjuntos (política honesta §7).
    assert sorted(i["score"] for i in media["qa_agotado"]) == [0.10, 0.30]
    assert any("ENTREGADO SIN APROBACIÓN QA" in r for r in audit.resumenes)
    assert _media_end_de(eventos, 1)["qa"] == "agotado"


def test_intentos_qa_cero_qa_solo_informativo(tmp_path):
    qa = QaFalso(scores=[0.10])
    puerto, audit, eventos, media = _correr_con_media(tmp_path, qa=qa, intentos_qa=0)
    assert len(puerto.pedidos) == 6  # sin regeneraciones
    kf1 = media["keyframes"][0]
    assert kf1["qa"][0]["aprueba"] is False
    # Con el score guionado, TODAS las escenas quedan sin aprobación: sus
    # informes (uno por intento, y hay un solo intento) quedan adjuntos.
    assert len(media["qa_agotado"]) == 6
    assert len({i["escena"] for i in media["qa_agotado"]}) == 6


def test_dedup_recibe_keyframes_previos_del_capitulo(tmp_path):
    qa = QaFalso(scores=[0.9])
    _puerto, _audit, _eventos, media = _correr_con_media(tmp_path, qa=qa)
    segunda = next(l for l in qa.llamadas if l["escena"] == 2)
    assert len(segunda["previos"]) == 1
    escena_previa, datos_previos = segunda["previos"][0]
    assert escena_previa == 1
    assert datos_previos == b"imagen-escena-1"


def test_sin_servicio_qa_el_camino_es_el_de_la_fase_3(tmp_path):
    puerto, audit, eventos, media = _correr_con_media(tmp_path, qa=None)
    assert len(puerto.pedidos) == 6
    assert all(kf["qa"] == [] for kf in media["keyframes"])
    assert media["qa_agotado"] == []
    assert not any("QA visual" in e for e in audit.eventos)

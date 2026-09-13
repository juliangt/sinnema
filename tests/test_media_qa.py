"""QA visual (Fase 4, spec-recursos-ancla §7/§11.4): servicio con extractores
de juguete — sin torch/insightface/CLIP ni red; umbrales, dedup, degradación.
"""
from __future__ import annotations

import pytest

from sinnema.domain.models import RecursoAncla, ReferenciaAncla
from sinnema.infrastructure.media.qa import (
    DISTANCIA_PHASH_GEMELA,
    UMBRAL_CARA_DEFAULT,
    UMBRAL_PROMPT_DEFAULT,
    QaVisualService,
    coseno,
    distancia_hamming,
)
from tests.conftest import make_ancla, make_imagen_ancla


# ------------------------------ fixtures ------------------------------

class CarasFijas:
    """Extractor de caras de juguete: devuelve el vector configurado."""

    def __init__(self, por_bytes=None, default=None):
        self._por_bytes = por_bytes or {}
        self._default = default

    def embedding_de_cara(self, datos: bytes):
        return self._por_bytes.get(datos, self._default)


class EmbeddingsFijos:
    """Embeddings de juguete: imagen/texto por tabla, default configurable."""

    def __init__(self, imagen=None, imagen_clip=None, texto=None):
        self._imagen = imagen or {}
        self._imagen_clip = imagen_clip or {}
        self._texto = texto or {}

    def embedding_imagen(self, datos):
        return self._imagen.get(datos)

    def embedding_imagen_clip(self, datos):
        return self._imagen_clip.get(datos)

    def embedding_texto(self, prompt):
        return self._texto.get(prompt)


class HasherFijo:
    """pHash de juguete: entero por tabla de bytes."""

    def __init__(self, por_bytes=None):
        self._por_bytes = por_bytes or {}

    def phash(self, datos):
        return self._por_bytes.get(datos)


def _cargador(biblioteca):
    def cargar(project_id, ancla_id, archivo):
        return biblioteca[(ancla_id, archivo)]
    return cargar


BIBLIOTECA = {
    ("nita", "hero_portrait_1.png"): b"hero-bytes",
    ("plaza", "establishing_shot_1.png"): b"establishing-bytes",
    ("plaza", "coverage_angle_1.png"): b"coverage-bytes",
}


def _servicio(**kwargs) -> QaVisualService:
    defaults = dict(cargar_imagen=_cargador(BIBLIOTECA))
    defaults.update(kwargs)
    return QaVisualService(**defaults)


def _par_personaje() -> RecursoAncla:
    return make_ancla(
        ancla_id="nita",
        tipo="personaje",
        estado="lockeado",
        bateria=[
            make_imagen_ancla(rol="hero_portrait", archivo="hero_portrait_1.png"),
            make_imagen_ancla(rol="turnaround_front", archivo="turnaround_front_1.png"),
            make_imagen_ancla(rol="turnaround_side", archivo="turnaround_side_1.png"),
            make_imagen_ancla(rol="turnaround_back", archivo="turnaround_back_1.png"),
        ],
    )


def _par_lugar() -> RecursoAncla:
    return make_ancla(
        ancla_id="plaza",
        tipo="lugar",
        estado="lockeado",
        bateria=[
            make_imagen_ancla(rol="establishing_shot", archivo="establishing_shot_1.png"),
            make_imagen_ancla(rol="coverage_angle", archivo="coverage_angle_1.png"),
        ],
    )


# ------------------------------ helpers puros ------------------------------


def test_coseno_basico():
    assert coseno([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert coseno([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert coseno([], [1.0]) == 0.0
    assert coseno([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_distancia_hamming():
    assert distancia_hamming(0b1010, 0b1010) == 0
    assert distancia_hamming(0b1010, 0b0101) == 4
    assert distancia_hamming(0, (1 << 64) - 1) == 64


# ------------------------------ cara ------------------------------


def test_cara_aprueba_sobre_umbral():
    servicio = _servicio(
        extractor_caras=CarasFijas(default=[1.0, 0.0]),
    )
    informes, avisos = servicio.evaluar_keyframe(
        escena=1,
        project_id="p1",
        prompt="the scene",
        datos_keyframe=b"keyframe",
        pares=[(ReferenciaAncla(ancla_id="nita"), _par_personaje())],
    )
    assert avisos == []
    assert len(informes) == 1
    informe = informes[0]
    assert (informe.metrica, informe.ancla_id, informe.aprueba) == (
        "cara_coseno", "nita", True,
    )
    assert informe.umbral == pytest.approx(UMBRAL_CARA_DEFAULT)


def test_cara_rechaza_bajo_umbral_y_configura_entorno(monkeypatch):
    monkeypatch.setenv("MEDIA_QA_UMBRAL_CARA", "0.9")
    servicio = _servicio(
        # Keyframe ortogonal al hero_portrait: coseno 0.0 < 0.9 → rechaza.
        extractor_caras=CarasFijas(
            por_bytes={b"keyframe": [0.0, 1.0]},
            default=[1.0, 0.0],
        ),
    )
    informes, _ = servicio.evaluar_keyframe(
        escena=2,
        project_id="p1",
        prompt="the scene",
        datos_keyframe=b"keyframe",
        pares=[(ReferenciaAncla(ancla_id="nita"), _par_personaje())],
    )
    informe = informes[0]
    assert informe.umbral == 0.9
    assert informe.score == pytest.approx(0.0)
    assert informe.aprueba is False


def test_cara_sin_cara_detectable_omite_con_aviso():
    servicio = _servicio(
        extractor_caras=CarasFijas(default=None),
    )
    informes, avisos = servicio.evaluar_keyframe(
        escena=1,
        project_id="p1",
        prompt="the scene",
        datos_keyframe=b"keyframe",
        pares=[(ReferenciaAncla(ancla_id="nita"), _par_personaje())],
    )
    assert informes == []
    assert any("sin cara detectable" in aviso for aviso in avisos)


def test_cara_sin_extractor_omite_con_aviso():
    servicio = _servicio()
    informes, avisos = servicio.evaluar_keyframe(
        escena=1,
        project_id="p1",
        prompt="the scene",
        datos_keyframe=b"keyframe",
        pares=[(ReferenciaAncla(ancla_id="nita"), _par_personaje())],
    )
    assert informes == []
    assert any("extra 'qa'" in aviso for aviso in avisos)


# ------------------------------ escena + prompt ------------------------------


def test_lugar_evalua_dino_maximo_y_clip():
    servicio = _servicio(
        extractor_embeddings=EmbeddingsFijos(
            imagen={
                b"keyframe": [1.0, 0.0],
                b"establishing-bytes": [0.6, 0.8],
                b"coverage-bytes": [0.98, 0.2],
            },
            imagen_clip={b"keyframe": [0.9, 0.1]},
            texto={"the scene": [0.8, 0.6]},
        ),
    )
    informes, avisos = servicio.evaluar_keyframe(
        escena=3,
        project_id="p1",
        prompt="the scene",
        datos_keyframe=b"keyframe",
        pares=[(ReferenciaAncla(ancla_id="plaza"), _par_lugar())],
    )
    assert avisos == []
    metricas = {informe.metrica: informe for informe in informes}
    dino = metricas["escena_dino"]
    # El máximo contra la batería es coverage_angle (0.98*1+0.2*0)/... ~0.98.
    assert dino.score > dino.umbral and dino.aprueba is True
    clip = metricas["clip_prompt"]
    assert clip.ancla_id == "plaza"
    esperado = (0.9 * 0.8 + 0.1 * 0.6) / ((0.9**2 + 0.1**2) ** 0.5 * (0.8**2 + 0.6**2) ** 0.5)
    assert clip.score == pytest.approx(esperado, abs=1e-3)


def test_lugar_roles_pedidos_acotan_la_bateria():
    servicio = _servicio(
        extractor_embeddings=EmbeddingsFijos(
            imagen={
                b"keyframe": [1.0, 0.0],
                b"establishing-bytes": [1.0, 0.0],
                b"coverage-bytes": [-1.0, 0.0],
            },
            imagen_clip={b"keyframe": [1.0, 0.0]},
            texto={"the scene": [1.0, 0.0]},
        ),
    )
    informes, _ = servicio.evaluar_keyframe(
        escena=1,
        project_id="p1",
        prompt="the scene",
        datos_keyframe=b"keyframe",
        pares=[(
            ReferenciaAncla(ancla_id="plaza", roles=["establishing_shot"]),
            _par_lugar(),
        )],
    )
    dino = next(i for i in informes if i.metrica == "escena_dino")
    assert dino.aprueba is True  # solo miró establishing (coverage es opuesto)
    assert "1 imagen(es)" in dino.detalle


# ------------------------------ dedup ------------------------------


def test_dedup_detecta_gemelas():
    hasher = HasherFijo({
        b"keyframe": 0b0000,
        b"previo": 0b0111,  # Hamming 3 <= 10: gemelas
    })
    servicio = _servicio(hasher=hasher)
    informes, avisos = servicio.evaluar_keyframe(
        escena=2,
        project_id="p1",
        prompt="the scene",
        datos_keyframe=b"keyframe",
        pares=[],
        previos=[(1, b"previo")],
    )
    assert avisos == []
    assert len(informes) == 1
    informe = informes[0]
    assert informe.metrica == "phash_dedup"
    assert informe.aprueba is False
    assert informe.ancla_id == ""
    assert "escena 1" in informe.detalle


def test_dedup_no_gemelas_no_informa():
    hasher = HasherFijo({
        b"keyframe": 0b0000,
        b"previo": (1 << 63),  # Hamming 1... no: bit 64, distancia 1? no — 2**63 es 1 bit
    })
    # 2**63 tiene un solo bit: usaría Hamming 1. Para "no gemela" usamos 11 bits:
    hasher = HasherFijo({b"keyframe": 0, b"previo": (1 << 11) - 1})
    servicio = _servicio(
        hasher=hasher,
        distancia_phash_maxima=DISTANCIA_PHASH_GEMELA,
    )
    informes, _ = servicio.evaluar_keyframe(
        escena=2,
        project_id="p1",
        prompt="the scene",
        datos_keyframe=b"keyframe",
        pares=[],
        previos=[(1, b"previo")],
    )
    assert informes == []


def test_dedup_previos_sin_hasher_avisa():
    servicio = _servicio()
    informes, avisos = servicio.evaluar_keyframe(
        escena=2,
        project_id="p1",
        prompt="the scene",
        datos_keyframe=b"keyframe",
        pares=[],
        previos=[(1, b"previo")],
    )
    assert informes == []
    assert any("dedup pHash omitido" in aviso for aviso in avisos)

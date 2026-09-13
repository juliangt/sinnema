"""Wiring de la capa de media (spec-recursos-ancla §6/§13 Fase 3, Hito 3).

Cubren: ``construir_dependencias_de_media`` (None salvo keyframes=true: los
adaptadores NI SE INSTANCIAN), precedencia del proveedor (TOML > MEDIA_PROVIDER
> gemini), ``MEDIA_MAX_INTENTOS``, el cargador de baterías sobre el almacén de
anclas y el TEST DE PARIDAD DURO: sin ``[media]`` la corrida (worker real +
gateway falso) produce el entregable de Fase 2 idéntico byte a byte (salvo
timestamps) sin exigir claves ni SDKs.
"""
from __future__ import annotations

import pytest

from sinnema.application.use_cases import GenerateSeriesUseCase
from sinnema.infrastructure.anclas import JsonAnchorStore
from sinnema.infrastructure.media import (
    AlmacenMedia,
    cargador_de_baterias,
    construir_dependencias_de_media,
    politica_del_entorno,
)
from sinnema.infrastructure.media import fabrica
from sinnema.infrastructure.runtime.jobs import JobStatus, SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker

from conftest import gateway_con_serie, make_project, make_request

PROJECT_ID = "sinnema"

VARS_DE_MEDIA = (
    "MEDIA_PROVIDER",
    "MEDIA_MAX_INTENTOS",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
)


@pytest.fixture
def entorno_media_limpio(monkeypatch):
    for var in VARS_DE_MEDIA:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def _bloquear_construccion_de_adaptadores(monkeypatch):
    """Cualquier intento de construir un adaptador revienta el test."""

    def _explosion(*args, **kwargs):
        raise AssertionError("Se intentó construir un adaptador de media sin [media].")

    monkeypatch.setattr(fabrica, "construir_puerto_de_media", _explosion)


# ===================== fábrica de dependencias =====================


def test_sin_keyframes_devuelve_none_y_no_instancia_adaptadores(
    entorno_media_limpio, monkeypatch, tmp_path
):
    from sinnema.application.projects import MediaConfig

    proyecto = make_project(media=MediaConfig(keyframes=False))
    _bloquear_construccion_de_adaptadores(monkeypatch)
    deps = construir_dependencias_de_media(
        proyecto,
        almacen=AlmacenMedia(root=tmp_path / "media"),
        anchor_store=JsonAnchorStore(root=tmp_path / "anclas"),
    )
    assert deps is None

    # Y un proyecto SIN sección [media] (defaults): igual.
    _bloquear_construccion_de_adaptadores(monkeypatch)
    assert construir_dependencias_de_media(
        make_project(),
        almacen=AlmacenMedia(root=tmp_path / "media"),
        anchor_store=JsonAnchorStore(root=tmp_path / "anclas"),
    ) is None


def test_con_keyframes_construye_puerto_con_proveedor_de_toml(
    entorno_media_limpio, tmp_path
):
    from sinnema.application.projects import MediaConfig

    proyecto = make_project(
        media=MediaConfig(keyframes=True, proveedor_imagen="openai")
    )
    deps = construir_dependencias_de_media(
        proyecto,
        almacen=AlmacenMedia(root=tmp_path / "media"),
        anchor_store=JsonAnchorStore(root=tmp_path / "anclas"),
    )
    assert deps is not None
    assert deps.proveedor == "openai"
    assert deps.eventos is None  # el runner conecta el sink del job
    assert isinstance(deps.almacen, AlmacenMedia)


def test_precedencia_del_proveedor_toml_gana_sobre_entorno(
    entorno_media_limpio, monkeypatch, tmp_path
):
    from sinnema.application.projects import MediaConfig

    monkeypatch.setenv("MEDIA_PROVIDER", "openai")
    proyecto_gemini = make_project(
        media=MediaConfig(keyframes=True, proveedor_imagen="gemini")
    )
    deps = construir_dependencias_de_media(
        proyecto_gemini,
        almacen=AlmacenMedia(root=tmp_path / "media"),
        anchor_store=JsonAnchorStore(root=tmp_path / "anclas"),
    )
    assert deps.proveedor == "gemini"  # TOML > entorno

    proyecto_sin_preferencia = make_project(media=MediaConfig(keyframes=True))
    deps_entorno = construir_dependencias_de_media(
        proyecto_sin_preferencia,
        almacen=AlmacenMedia(root=tmp_path / "media"),
        anchor_store=JsonAnchorStore(root=tmp_path / "anclas"),
    )
    assert deps_entorno.proveedor == "openai"  # entorno > default

    entorno_media_limpio.delenv("MEDIA_PROVIDER", raising=False)
    deps_default = construir_dependencias_de_media(
        proyecto_sin_preferencia,
        almacen=AlmacenMedia(root=tmp_path / "media"),
        anchor_store=JsonAnchorStore(root=tmp_path / "anclas"),
    )
    assert deps_default.proveedor == "gemini"  # default


def test_media_provider_invalido_es_error_accionable(
    entorno_media_limpio, monkeypatch, tmp_path
):
    from sinnema.application.projects import MediaConfig

    monkeypatch.setenv("MEDIA_PROVIDER", "veo")
    proyecto = make_project(media=MediaConfig(keyframes=True))
    with pytest.raises(ValueError, match="veo"):
        construir_dependencias_de_media(
            proyecto,
            almacen=AlmacenMedia(root=tmp_path / "media"),
            anchor_store=JsonAnchorStore(root=tmp_path / "anclas"),
        )


def test_media_max_intentos_afina_la_politica_de_transporte(
    entorno_media_limpio, monkeypatch
):
    assert politica_del_entorno().max_retries == 3  # default
    monkeypatch.setenv("MEDIA_MAX_INTENTOS", "5")
    assert politica_del_entorno().max_retries == 5
    monkeypatch.setenv("MEDIA_MAX_INTENTOS", "cero")
    assert politica_del_entorno().max_retries == 3  # inválido → default con aviso
    monkeypatch.setenv("MEDIA_MAX_INTENTOS", "0")
    assert politica_del_entorno().max_retries == 3  # <1 → default con aviso


def test_cargador_de_baterias_lee_los_bytes_del_almacen_de_anclas(tmp_path):
    store = JsonAnchorStore(root=tmp_path / "anclas")
    store.guardar_imagen(PROJECT_ID, "protagonista", "hero_portrait_1.png", b"png-falso")
    cargar = cargador_de_baterias(store)
    assert cargar(PROJECT_ID, "protagonista", "hero_portrait_1.png") == b"png-falso"
    with pytest.raises(ValueError):
        cargar(PROJECT_ID, "protagonista", "../../escape.png")


# ===================== paridad dura (criterio §13) =====================


def _worker_de_prueba(tmp_path, proyecto, **kwargs):
    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    (tmp_path / "checkpoints").mkdir(parents=True, exist_ok=True)
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
        anchor_root=tmp_path / "anclas",
        project_loader=lambda pid: proyecto,
        media_factory=lambda p: construir_dependencias_de_media(
            p,
            almacen=AlmacenMedia(root=tmp_path / "media"),
            anchor_store=JsonAnchorStore(root=tmp_path / "anclas"),
        ),
        **kwargs,
    )
    return store, worker


def _correr_job(store, worker, proyecto):
    job = store.create_job(
        owner="ana", project_id=proyecto.project_id,
        # Sin topic explícito equivalente: el job usa el default del proyecto,
        # igual que make_request (paridad del contenido del entregable).
        topic=proyecto.default_topic,
        num_chapters=1, max_critique_attempts=1,
    )
    worker._run_job(job.job_id)
    return store.get_job(job.job_id)


def test_sin_media_el_entregable_es_identico_y_no_se_construyen_adaptadores(
    entorno_media_limpio, monkeypatch, tmp_path
):
    """CRITERIO §13 Fase 3: sin ``[media]``, la corrida produce el entregable
    de Fase 2 idéntico y NO exige claves ni SDKs (ningún adaptador se
    construye; el nodo ni se inserta en el grafo)."""
    _bloquear_construccion_de_adaptadores(monkeypatch)
    proyecto = make_project()  # sin sección [media]
    store, worker = _worker_de_prueba(
        tmp_path, proyecto,
        gateway_factory=lambda p: gateway_con_serie(num_chapters=1),
    )
    job = _correr_job(store, worker, proyecto)

    assert job.status is JobStatus.COMPLETED
    episodio = job.deliverable["episodes"][0]
    assert all(a["rol"] != "media" for a in episodio["adjuntos"])
    assert not (tmp_path / "media").exists()  # nada escrito

    # Y el entregable es BYTE A BYTE el de una corrida Fase 2 (use case sin
    # kwarg media), salvo el timestamp del entregable.
    referencia = GenerateSeriesUseCase(
        gateway_con_serie(num_chapters=1), make_project()
    ).execute(make_request(num_chapters=1))
    esperado = referencia.model_dump(mode="json")
    esperado.pop("generated_at")
    obtenido = dict(job.deliverable)
    obtenido.pop("generated_at")
    assert obtenido == esperado

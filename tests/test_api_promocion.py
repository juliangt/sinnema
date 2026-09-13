"""Tests de la API de promoción de keyframes a batería (Fase 5, §8.1/§8.3).

Mismo patrón que ``test_api_anclas.py``: TestClient con almacenes temporales
y jobs completados inyectando el entregable a mano (sin pipeline). Los
keyframes viven como archivos sintéticos bajo la raíz de media compartida
por worker y API (mismo ``data_dir``).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sinnema.infrastructure.api.app import create_app
from sinnema.infrastructure.projects import ProjectFileStore
from sinnema.infrastructure.runtime.jobs import JobStatus, SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker

PNG = b"\x89PNG\r\n\x1a\n" + b"keyframe-sintetico-de-prueba"

MANIFEST = {
    "proveedor": "falso",
    "modelo": "falso-1",
    "seed": 7,
    "prompt_final": "A clean isometric render of the guide character in a neon lab",
    "anclas_usadas": [["protagonista", 1, "hero_portrait"]],
    "parametros": {},
    "id_externo": "fake-1",
    "creado_en": "2026-09-12T00:00:00+00:00",
}


def _keyframe(escena: int, qa: list, manifest=MANIFEST) -> dict:
    return {
        "archivo": f"mi-show/ch-01/escena_{escena}.png",
        "manifest": manifest,
        "qa": qa,
    }


INFORME_APROBADO = {
    "escena": 1, "ancla_id": "protagonista", "metrica": "cara_coseno",
    "score": 0.8, "umbral": 0.35, "aprueba": True, "detalle": "",
}


def _entregable_con_media(keyframes: list) -> dict:
    return {
        "episodes": [{
            "adjuntos": [{
                "rol": "media",
                "artefacto": {
                    "chapter_id": "ch-01",
                    "keyframes": keyframes,
                    "errores": [],
                    "qa_agotado": [],
                },
            }],
        }],
    }


@pytest.fixture
def cliente_promocion(tmp_path):
    """App aislada + proyecto 'mi-show' con ancla 'protagonista' (personaje).

    El job completado trae tres keyframes: escena 1 aprobada por QA (candidato),
    escena 2 rechazada y escena 3 sin informes (QA no corrió) — estas dos no
    son candidatos. Los archivos existen bajo la raíz de media compartida.
    """
    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    project_store = ProjectFileStore(tmp_path / "escribible", tmp_path / "empaquetado")
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
        project_loader=project_store.load,
    )
    client = TestClient(create_app(
        store=store, worker=worker, data_dir=tmp_path,
        project_store=project_store,
    ))
    assert client.post("/api/projects", json={
        "proyecto": {
            "id": "mi-show", "marca": "Mi Show",
            "concepto": "micro-videos de prueba verticales",
            "tema_por_defecto": "Un tema de prueba suficientemente largo",
            "idioma": "Español",
        },
        "voz": {
            "audiencia": "Audiencia de prueba", "contexto_cultural": "Contexto",
            "tono": "tono cercano", "guia_de_estilo": "guía de estilo",
            "restricciones": "restricciones",
        },
        "visual": {"estilo_maestro": "3D render style with clean environment and lighting"},
    }).status_code == 201
    assert client.post("/api/projects/mi-show/anclas", json={
        "ancla_id": "protagonista",
        "tipo": "personaje",
        "nombre": "Nita la guía",
        "descripcion_canonica": (
            "A friendly young guide with short dark hair, teal jacket and a "
            "glowing compass pendant"
        ),
    }).status_code == 201

    manifest_segunda = dict(MANIFEST, seed=8, id_externo="fake-4",
                            creado_en="2026-09-12T00:00:04+00:00")
    entregable = _entregable_con_media([
        _keyframe(1, [dict(INFORME_APROBADO, score=0.8),
                      dict(INFORME_APROBADO, score=0.5)]),
        _keyframe(2, [dict(INFORME_APROBADO, aprueba=False, score=0.1)]),
        _keyframe(3, []),  # QA no corrió: NO es candidato (§8)
        # Segunda escena aprobada (otra generación): sirve para el test de
        # versionado tras lock, sin pisar la idempotencia de la primera.
        _keyframe(4, [dict(INFORME_APROBADO, escena=4, score=0.9)],
                  manifest=manifest_segunda),
    ])
    job = store.create_job(owner="ana", project_id="mi-show",
                           topic="Un tema largo de prueba", num_chapters=1,
                           max_critique_attempts=1)
    store.set_status(job.job_id, JobStatus.COMPLETED, deliverable=entregable)

    # Los keyframes viven en la MISMA raíz de media que usa el worker.
    for escena in (1, 2, 3, 4):
        ruta = tmp_path / "media" / "mi-show" / "ch-01" / f"escena_{escena}.png"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(PNG + bytes([escena]))

    return client, tmp_path, store, job.job_id


# ----------------------------- GET candidatos -----------------------------


def test_candidatos_solo_keyframes_con_qa_aprobado(cliente_promocion):
    client, _, _, job_id = cliente_promocion
    res = client.get(f"/api/jobs/{job_id}/anclas-candidatas")
    assert res.status_code == 200
    candidatos = res.json()

    # Solo las escenas 1 y 4 aprueban; la 2 (rechazada) y la 3 (QA ausente) no.
    assert [c["archivo"] for c in candidatos] == [
        "mi-show/ch-01/escena_1.png",
        "mi-show/ch-01/escena_4.png",
        "mi-show/ch-01/escena_1.png",  # la entrada de estilo global es la primera aprobada
    ]
    por_ancla, otra, estilo_global = candidatos
    assert otra["ancla_id"] == "protagonista"
    assert otra["escena"] == 4
    assert por_ancla["ancla_id"] == "protagonista"
    assert por_ancla["rol_sugerido"] == "expression_sheet"  # personaje → §8.1
    assert por_ancla["chapter_id"] == "ch-01"
    assert por_ancla["escena"] == 1
    assert por_ancla["score_qa"] == 0.5  # el peor score de sus informes
    assert "manifest" not in por_ancla

    # Entrada especial de estilo global (§8.3): el PRIMER keyframe aprobado.
    assert estilo_global["ancla_id"] is None
    assert estilo_global["estilo_global"] is True
    assert estilo_global["rol_sugerido"] == "style_reference"
    assert estilo_global["archivo"] == "mi-show/ch-01/escena_1.png"


def test_candidatos_sin_entregable_da_409(cliente_promocion):
    client, _, store, _ = cliente_promocion
    pendiente = store.create_job(owner="ana", project_id="mi-show",
                                 topic="Otro tema largo de prueba",
                                 num_chapters=1, max_critique_attempts=1)
    res = client.get(f"/api/jobs/{pendiente.job_id}/anclas-candidatas")
    assert res.status_code == 409
    assert client.get("/api/jobs/no-existe/anclas-candidatas").status_code == 404


def test_entregable_sin_media_no_tiene_candidatos(cliente_promocion, tmp_path):
    client, _, store, _ = cliente_promocion
    job = store.create_job(owner="ana", project_id="mi-show",
                           topic="Otro tema largo de prueba",
                           num_chapters=1, max_critique_attempts=1)
    store.set_status(job.job_id, JobStatus.COMPLETED,
                     deliverable={"episodes": [{"adjuntos": []}]})
    assert client.get(f"/api/jobs/{job.job_id}/anclas-candidatas").json() == []


# ------------------------------ POST promover ------------------------------


def _promover(client, archivo="mi-show/ch-01/escena_1.png", rol="expression_sheet",
              ancla_id="protagonista"):
    return client.post(
        f"/api/projects/mi-show/anclas/{ancla_id}/promover",
        json={"archivo": archivo, "rol": rol},
    )


def test_promover_copia_conserva_manifest_y_versiona_si_lockeada(cliente_promocion):
    client, tmp_path, _, _ = cliente_promocion

    # Borrador: promover copia el archivo y conserva el manifest (version 1).
    res = _promover(client)
    assert res.status_code == 201
    ancla = res.json()
    promovida = ancla["bateria"][-1]
    assert promovida["rol"] == "expression_sheet"
    assert promovida["archivo"] == "expression_sheet_1.png"  # correlativo del rol
    assert promovida["origen"] == "generada"
    assert promovida["manifest"]["proveedor"] == "falso"
    assert promovida["manifest"]["anclas_usadas"] == [["protagonista", 1, "hero_portrait"]]
    assert ancla["version"] == 1  # no estaba lockeada
    copia = tmp_path / "anclas" / "mi-show" / "protagonista" / "expression_sheet_1.png"
    assert copia.read_bytes() == PNG + b"\x01"
    # Y la imagen promovida se sirve por el serving de batería existente.
    serving = client.get("/api/projects/mi-show/anclas/protagonista/imagenes/expression_sheet_1.png")
    assert serving.status_code == 200

    # Lockeada: cambiar la batería sube la versión (§4.1 vía el almacén).
    for rol in ("hero_portrait", "turnaround_front", "turnaround_side", "turnaround_back"):
        assert client.post(
            "/api/projects/mi-show/anclas/protagonista/imagenes",
            data={"rol": rol},
            files={"archivo": ("nita.png", PNG, "image/png")},
        ).status_code == 201
    assert client.post("/api/projects/mi-show/anclas/protagonista/lock").status_code == 200
    lockeada = _promover(
        client, archivo="mi-show/ch-01/escena_4.png", rol="expression_sheet",
    ).json()
    assert lockeada["version"] == 2
    assert lockeada["bateria"][-1]["archivo"] == "expression_sheet_2.png"


def test_promover_con_rol_incoherente_da_400(cliente_promocion):
    client, _, _, _ = cliente_promocion
    res = _promover(client, rol="prop_detail")  # rol de objeto, ancla personaje
    assert res.status_code == 400
    assert "prop_detail" in res.json()["detail"]


def test_promover_archivo_que_no_es_candidato_da_404(cliente_promocion):
    client, _, _, _ = cliente_promocion
    # QA rechazado y QA ausente: ninguno es candidato (§8).
    assert _promover(client, archivo="mi-show/ch-01/escena_2.png").status_code == 404
    assert _promover(client, archivo="mi-show/ch-01/escena_3.png").status_code == 404
    # Archivo ajeno a la raíz de media: también 404 (sin traversal).
    res = _promover(client, archivo="../../escape.png")
    assert res.status_code == 404


def test_promover_el_mismo_keyframe_dos_veces_da_409(cliente_promocion):
    """Idempotencia (§8.1): el mismo keyframe (mismo manifest de generación)
    no entra dos veces; el nombre nuevo lo delataría como imagen duplicada."""
    client, _, _, _ = cliente_promocion
    assert _promover(client).status_code == 201
    res = _promover(client)
    assert res.status_code == 409
    assert "ya fue promovido" in res.json()["detail"]


def test_promover_candidato_de_estilo_global_en_ancla_de_estilo(cliente_promocion):
    """§8.3: la persona crea el ancla de estilo y promueve el keyframe
    propuesto como style_reference con el mismo endpoint."""
    client, tmp_path, _, _ = cliente_promocion
    assert client.post("/api/projects/mi-show/anclas", json={
        "ancla_id": "look-principal",
        "tipo": "estilo",
        "nombre": "Look principal",
        "descripcion_canonica": (
            "Isometric 3D render style with neon accents and soft studio "
            "lighting for the whole show"
        ),
    }).status_code == 201
    res = _promover(client, ancla_id="look-principal", rol="style_reference")
    assert res.status_code == 201
    promovida = res.json()["bateria"][-1]
    assert promovida["archivo"] == "style_reference_1.png"
    assert promovida["origen"] == "generada"
    assert (tmp_path / "anclas" / "mi-show" / "look-principal" / "style_reference_1.png").exists()

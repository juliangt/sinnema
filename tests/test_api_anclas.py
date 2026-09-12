"""Tests de la API REST de recursos ancla (Fase 1, spec-recursos-ancla §9.1).

Mismo patrón que ``test_api.py``: TestClient con almacenes temporales; los
archivos de batería son bytes sintéticos (sin red ni claves de proveedor).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sinnema.infrastructure.anclas import JsonAnchorStore
from sinnema.infrastructure.api.app import TAMANO_MAXIMO_DE_IMAGEN, create_app
from sinnema.infrastructure.projects import ProjectFileStore
from sinnema.infrastructure.runtime.jobs import SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker

from conftest import gateway_con_serie, make_imagen_ancla

PNG = b"\x89PNG\r\n\x1a\n" + b"imagen-sintetica-de-prueba"


@pytest.fixture
def cliente_anclas(tmp_path):
    """App aislada con un proyecto editable creado por su propia API."""
    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    project_store = ProjectFileStore(tmp_path / "escribible", tmp_path / "empaquetado")
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
        gateway_factory=lambda proyecto: gateway_con_serie(num_chapters=1),
        project_loader=project_store.load,
    )
    client = TestClient(create_app(
        store=store, worker=worker, data_dir=tmp_path,
        project_store=project_store,
    ))
    cuerpo = {
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
    }
    assert client.post("/api/projects", json=cuerpo).status_code == 201
    return client, tmp_path


def _alta(client, ancla_id="protagonista", **cambios):
    cuerpo = {
        "ancla_id": ancla_id,
        "tipo": "personaje",
        "nombre": "Nita la guía",
        "descripcion_canonica": (
            "A friendly young guide with short dark hair, teal jacket and a "
            "glowing compass pendant"
        ),
    }
    cuerpo.update(cambios)
    return client.post(f"/api/projects/mi-show/anclas", json=cuerpo)


def _subir(client, ancla_id="protagonista", rol="hero_portrait", nombre="nita.png",
           contenido=PNG):
    return client.post(
        f"/api/projects/mi-show/anclas/{ancla_id}/imagenes",
        data={"rol": rol},
        files={"archivo": (nombre, contenido, "image/png")},
    )


# ------------------------------- CRUD básico -------------------------------


def test_biblioteca_vacia_y_alta_en_borrador(cliente_anclas):
    client, _ = cliente_anclas
    assert client.get("/api/projects/mi-show/anclas").json() == []

    res = _alta(client)
    assert res.status_code == 201
    ancla = res.json()
    assert ancla["ancla_id"] == "protagonista"
    assert ancla["estado"] == "borrador"  # el alta nunca nace lockeada
    assert ancla["version"] == 1
    assert ancla["bateria"] == []

    detalle = client.get("/api/projects/mi-show/anclas/protagonista").json()
    assert detalle["nombre"] == "Nita la guía"
    lista = client.get("/api/projects/mi-show/anclas").json()
    assert [a["ancla_id"] for a in lista] == ["protagonista"]


def test_alta_con_contrato_invalido_da_400_accionable(cliente_anclas):
    client, _ = cliente_anclas
    res = _alta(client, descripcion_canonica="muy corto")
    assert res.status_code == 400
    assert "descripcion_canonica" in res.json()["detail"]

    res = _alta(client, ancla_id="Protagonista")  # no es slug
    assert res.status_code == 400
    assert "ancla_id" in res.json()["detail"]

    res = _alta(client, nombre="   ")  # sin contenido
    assert res.status_code == 400
    assert not client.get("/api/projects/mi-show/anclas").json()


def test_alta_duplicada_da_409_por_id_y_por_nombre(cliente_anclas):
    client, _ = cliente_anclas
    assert _alta(client).status_code == 201

    res = _alta(client, nombre="Otro nombre")
    assert res.status_code == 409
    assert "id" in res.json()["detail"]

    res = _alta(client, ancla_id="guia", nombre="nita LA GUÍA")
    assert res.status_code == 409  # nombre único case-insensitive
    assert "Nita la guía" in res.json()["detail"]  # cita al existente


def test_ancla_inexistente_y_proyecto_inexistente(cliente_anclas):
    client, _ = cliente_anclas
    assert client.get("/api/projects/mi-show/anclas/fantasma").status_code == 404
    assert client.get("/api/projects/fantasma/anclas").status_code == 404
    assert client.delete("/api/projects/mi-show/anclas/fantasma").status_code == 404
    assert client.post("/api/projects/fantasma/anclas/fantasma/lock").status_code == 404


def test_editar_nombre_y_descriptor_persisten(cliente_anclas):
    client, _ = cliente_anclas
    _alta(client)
    res = client.put("/api/projects/mi-show/anclas/protagonista", json={
        "nombre": "Nita la navegante",
        "descripcion_canonica": (
            "A determined young navigator with short dark hair, teal jacket "
            "and a brass compass"
        ),
    })
    assert res.status_code == 200
    detalle = client.get("/api/projects/mi-show/anclas/protagonista").json()
    assert detalle["nombre"] == "Nita la navegante"
    assert detalle["descripcion_canonica"].startswith("A determined young navigator")


def test_editar_rechaza_estado_otras_claves_y_contratos(cliente_anclas):
    client, _ = cliente_anclas
    _alta(client)

    res = client.put("/api/projects/mi-show/anclas/protagonista", json={
        "estado": "lockeado",
    })
    assert res.status_code == 400
    assert "estado" in res.json()["detail"]
    assert client.get(
        "/api/projects/mi-show/anclas/protagonista"
    ).json()["estado"] == "borrador"

    res = client.put("/api/projects/mi-show/anclas/protagonista", json={
        "descripcion_canonica": "descriptor en español demasiado corto",
    })
    assert res.status_code == 400
    assert client.put(
        "/api/projects/mi-show/anclas/fantasma", json={"nombre": "X"},
    ).status_code == 404


def test_retirar_deja_el_registro_y_los_archivos(cliente_anclas):
    client, tmp_path = cliente_anclas
    _alta(client)
    _subir(client)
    _subir(client, rol="turnaround_front", nombre="frontal.png")

    res = client.delete("/api/projects/mi-show/anclas/protagonista")
    assert res.status_code == 200
    assert res.json()["estado"] == "retirado"

    lista = client.get("/api/projects/mi-show/anclas").json()
    assert [a["estado"] for a in lista] == ["retirado"]  # el registro sigue
    assert lista[0]["bateria"]  # la batería no se toca
    carpeta = tmp_path / "anclas" / "mi-show" / "protagonista"
    assert (carpeta / "hero_portrait_1.png").is_file()  # los archivos quedan

    # Idempotente: retirar dos veces no rompe.
    assert client.delete(
        "/api/projects/mi-show/anclas/protagonista"
    ).status_code == 200


# -------------------------------- Uploads ---------------------------------


def test_upload_nombres_correlativos_y_serving(cliente_anclas):
    client, tmp_path = cliente_anclas
    _alta(client)

    primera = _subir(client)
    assert primera.status_code == 201
    segunda = _subir(client)
    tercera = _subir(client, rol="turnaround_front", nombre="frente.jpg")
    assert all(r.status_code == 201 for r in (primera, segunda, tercera))

    bateria = client.get("/api/projects/mi-show/anclas/protagonista").json()["bateria"]
    assert [i["archivo"] for i in bateria] == [
        "hero_portrait_1.png", "hero_portrait_2.png", "turnaround_front_1.jpg",
    ]
    assert all(i["origen"] == "subida" for i in bateria)

    res = client.get(
        "/api/projects/mi-show/anclas/protagonista/imagenes/hero_portrait_2.png"
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content == PNG
    assert "max-age" in res.headers.get("cache-control", "")
    assert (tmp_path / "anclas" / "mi-show" / "protagonista" /
            "hero_portrait_2.png").is_file()


def test_upload_con_rol_incoherente_o_invalido_da_400(cliente_anclas):
    client, _ = cliente_anclas
    _alta(client)  # personaje

    res = _subir(client, rol="establishing_shot")  # rol de lugar
    assert res.status_code == 400
    assert "establishing_shot" in res.json()["detail"]
    assert "hero_portrait" in res.json()["detail"]  # lista los válidos

    res = _subir(client, rol="prop_hero")  # rol de objeto
    assert res.status_code == 400
    assert client.get("/api/projects/mi-show/anclas/protagonista").json()["bateria"] == []


def test_upload_con_formato_raro_o_tamanio_excesivo(cliente_anclas):
    client, _ = cliente_anclas
    _alta(client)

    res = _subir(client, nombre="animacion.gif")
    assert res.status_code == 400
    assert "Formato" in res.json()["detail"]

    res = _subir(client, nombre="sin-extension")
    assert res.status_code == 400

    grande = b"0" * (TAMANO_MAXIMO_DE_IMAGEN + 1)
    res = _subir(client, nombre="enorme.png", contenido=grande)
    assert res.status_code == 413
    assert "10 MB" in res.json()["detail"]


def test_upload_a_ancla_inexistente_da_404(cliente_anclas):
    client, _ = cliente_anclas
    assert _subir(client, ancla_id="fantasma").status_code == 404


def test_upload_a_lockeada_sube_version(cliente_anclas):
    """Regla §4.1: cambiar la batería de una lockeada sube su version."""
    client, _ = cliente_anclas
    _alta(client)
    for rol in ("hero_portrait", "turnaround_front", "turnaround_side",
                "turnaround_back"):
        _subir(client, rol=rol, nombre=f"{rol}.png")
    client.post("/api/projects/mi-show/anclas/protagonista/lock")

    res = _subir(client, rol="expression_sheet", nombre="enojada.png")
    assert res.status_code == 201
    assert res.json()["version"] == 2
    assert res.json()["estado"] == "lockeado"


# --------------------------------- Lock -----------------------------------


def test_lock_sin_bateria_minima_da_400_con_faltantes(cliente_anclas):
    client, _ = cliente_anclas
    _alta(client)
    _subir(client)  # solo hero_portrait

    res = client.post("/api/projects/mi-show/anclas/protagonista/lock")
    assert res.status_code == 400
    detalle = res.json()["detail"]
    for faltante in ("turnaround_front", "turnaround_side", "turnaround_back"):
        assert faltante in detalle


def test_lock_con_bateria_minima_persiste_el_estado(cliente_anclas):
    client, tmp_path = cliente_anclas
    _alta(client)
    for rol in ("hero_portrait", "turnaround_front", "turnaround_side",
                "turnaround_back"):
        _subir(client, rol=rol, nombre=f"{rol}.png")

    res = client.post("/api/projects/mi-show/anclas/protagonista/lock")
    assert res.status_code == 200
    assert res.json()["estado"] == "lockeado"
    assert res.json()["version"] == 1  # lockear no cambia la batería

    # Persistido en disco, visible en el listado.
    almacen = JsonAnchorStore(tmp_path / "anclas")
    assert almacen.load("mi-show")[0].estado == "lockeado"

    # Re-lock idempotente; editar el nombre no re-sube version.
    assert client.post(
        "/api/projects/mi-show/anclas/protagonista/lock"
    ).status_code == 200
    client.put("/api/projects/mi-show/anclas/protagonista", json={
        "nombre": "Nita la capitana",
    })
    assert client.get(
        "/api/projects/mi-show/anclas/protagonista"
    ).json()["version"] == 1


def test_lock_de_lugar_con_su_bateria_propia(cliente_anclas):
    client, _ = cliente_anclas
    _alta(client, ancla_id="laboratorio", tipo="lugar", nombre="El laboratorio")
    res = client.post("/api/projects/mi-show/anclas/laboratorio/lock")
    assert res.status_code == 400
    assert "establishing_shot" in res.json()["detail"]

    _subir(client, ancla_id="laboratorio", rol="establishing_shot",
           nombre="entrada.png")
    res = client.post("/api/projects/mi-show/anclas/laboratorio/lock")
    assert res.status_code == 200


# --------------------- Serving seguro (spec §14) ---------------------


def test_serving_rechaza_traversal_y_archivos_no_registrados(cliente_anclas):
    client, _ = cliente_anclas
    _alta(client)
    _subir(client)

    for archivo in ("..%2Fanclas.json", "hero_portrait_1.png%00.jpg", "anclas.json"):
        res = client.get(f"/api/projects/mi-show/anclas/protagonista/imagenes/{archivo}")
        assert res.status_code == 404, archivo

    # Nombre registrado no existe como archivo → 404 (no 500).
    res = client.get(
        "/api/projects/mi-show/anclas/protagonista/imagenes/hero_portrait_9.png"
    )
    assert res.status_code == 404


def test_serving_rechaza_symlink_que_escapa(cliente_anclas, tmp_path):
    """§14: un symlink registrado en la batería que apunta fuera de la
    carpeta del ancla se rechaza aunque el nombre esté registrado."""
    client, tmp_path = cliente_anclas
    _alta(client)
    secreto = tmp_path / "fuera-de-la-raiz.txt"
    secreto.write_text("dato fuera de la biblioteca", encoding="utf-8")

    almacen = JsonAnchorStore(tmp_path / "anclas")
    anclas = almacen.load("mi-show")
    anclas[0].bateria.append(
        make_imagen_ancla("hero_portrait", archivo="trap.png")
    )
    almacen.save("mi-show", anclas)
    carpeta = tmp_path / "anclas" / "mi-show" / "protagonista"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "trap.png").symlink_to(secreto)

    res = client.get("/api/projects/mi-show/anclas/protagonista/imagenes/trap.png")
    assert res.status_code == 404

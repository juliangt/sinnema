"""Tests de la API HTTP (FastAPI TestClient) con worker real + gateway falso."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from sinnema.infrastructure.api.app import create_app
from sinnema.infrastructure.projects import ProjectFileStore
from sinnema.infrastructure.runtime.jobs import JobStatus, SqliteJobStore
from sinnema.infrastructure.runtime.runner import SeriesWorker
from tests.conftest import gateway_con_serie, make_lore_entry


@pytest.fixture
def cliente(tmp_path):
    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
        gateway_factory=lambda proyecto: gateway_con_serie(num_chapters=2),
    )
    app = create_app(store=store, worker=worker, data_dir=tmp_path)
    return TestClient(app), store


@pytest.fixture
def gestion(tmp_path):
    """App con almacén de proyectos aislado en tmp (para el CRUD web)."""
    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    project_store = ProjectFileStore(tmp_path / "escribible", tmp_path / "empaquetado")
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
        gateway_factory=lambda proyecto: gateway_con_serie(num_chapters=2),
        project_loader=project_store.load,
    )
    app = create_app(
        store=store, worker=worker, data_dir=tmp_path, project_store=project_store,
    )
    return TestClient(app), store, project_store, tmp_path


def _proyecto_json(id: str = "mi-show", **secciones) -> dict:
    datos = {
        "proyecto": {
            "id": id,
            "marca": "Mi Show",
            "concepto": "micro-videos de prueba verticales",
            "tema_por_defecto": "Un tema de prueba suficientemente largo",
            "idioma": "Español",
        },
        "voz": {
            "audiencia": "Audiencia de prueba",
            "contexto_cultural": "Contexto cultural",
            "tono": "tono cercano",
            "guia_de_estilo": "guía de estilo",
            "restricciones": "restricciones",
        },
        "visual": {
            "estilo_maestro": "3D render style with clean environment and lighting",
        },
    }
    datos.update(secciones)
    return datos


def esperar(store, job_id, timeout_s=10.0):
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        job = store.get_job(job_id)
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return job
        time.sleep(0.1)
    raise AssertionError("Timeout esperando el job.")


def test_health(cliente):
    client, _ = cliente
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_lista_proyectos(cliente):
    client, _ = cliente
    res = client.get("/api/projects")
    assert res.status_code == 200
    ids = {p["project_id"] for p in res.json()}
    assert "educativo" in ids


def test_crear_job_y_consultar(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis en 60 segundos",
        "num_chapters": 2,
    }, headers={"X-Owner": "ana"})
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    job = esperar(store, job_id)
    assert job.status is JobStatus.COMPLETED

    detalle = client.get(f"/api/jobs/{job_id}").json()
    assert detalle["status"] == "completed"
    assert len(detalle["deliverable"]["episodes"]) == 2


def test_tema_vacio_usa_el_del_proyecto(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "num_chapters": 1,
    })
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    esperar(store, job_id)
    assert store.get_job(job_id).topic  # resolvió el tema por defecto


def test_proyecto_inexistente_devuelve_404(cliente):
    client, _ = cliente
    res = client.post("/api/series", json={"project_id": "fantasma"})
    assert res.status_code == 404
    assert "fantasma" in res.json()["detail"]


def test_listado_de_jobs_queda_acotado_por_owner(cliente):
    client, store = cliente
    r1 = client.post("/api/series", json={"project_id": "educativo", "num_chapters": 1},
                     headers={"X-Owner": "ana"})
    r2 = client.post("/api/series", json={"project_id": "educativo", "num_chapters": 1},
                     headers={"X-Owner": "beto"})
    esperar(store, r1.json()["job_id"])
    esperar(store, r2.json()["job_id"])

    propios = client.get("/api/jobs", headers={"X-Owner": "ana"}).json()
    assert len(propios) == 1
    assert propios[0]["owner"] == "ana"
    assert "deliverable" not in propios[0]  # el listado no arrastra entregables


def test_entregable_y_viewer(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis en 60 segundos",
        "num_chapters": 2,
    })
    job_id = res.json()["job_id"]
    esperar(store, job_id)

    datos = client.get(f"/api/jobs/{job_id}/deliverable").json()
    assert datos["series_title"]

    viewer = client.get(f"/api/jobs/{job_id}/viewer")
    assert viewer.status_code == 200
    assert "text/html" in viewer.headers["content-type"]
    assert datos["series_title"] in viewer.text


def test_entregable_antes_de_terminar_devuelve_409(cliente):
    client, store = cliente
    res = client.post("/api/series", json={"project_id": "educativo", "num_chapters": 2})
    job_id = res.json()["job_id"]
    job = store.get_job(job_id)
    if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
        assert client.get(f"/api/jobs/{job_id}/deliverable").status_code == 409
    esperar(store, job_id)  # dejamos terminar el hilo antes de cerrar
    assert client.get(f"/api/jobs/{job_id}/deliverable").status_code == 200


def test_eventos_sse_y_fin(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis en 60 segundos",
        "num_chapters": 2,
    })
    job_id = res.json()["job_id"]
    esperar(store, job_id)
    job = store.get_job(job_id)
    eventos = store.events_since(job_id)
    assert eventos[-1].kind == "done"
    assert job.status is JobStatus.COMPLETED


def test_home_sirve_la_interfaz(cliente):
    client, _ = cliente
    res = client.get("/")
    assert res.status_code == 200
    assert "Sinnema" in res.text


# --------------------------- Gestión de proyectos ---------------------------


def test_crear_proyecto_lo_lista_y_queda_editable(gestion):
    client, _, pstore, _ = gestion
    res = client.post("/api/projects", json=_proyecto_json())
    assert res.status_code == 201
    assert res.json()["project_id"] == "mi-show"

    listado = client.get("/api/projects").json()
    mio = next(p for p in listado if p["project_id"] == "mi-show")
    assert mio["editable"] is True
    assert mio["brand_name"] == "Mi Show"
    assert pstore.exists("mi-show")


def test_crear_proyecto_invalido_devuelve_400_con_detalles(gestion):
    client, _, pstore, _ = gestion
    datos = _proyecto_json()
    datos["proyecto"]["id"] = "Mal Id"  # slug inválido
    res = client.post("/api/projects", json=datos)
    assert res.status_code == 400
    assert "project_id" in res.json()["detail"]
    assert not pstore.exists("Mal Id")


def test_crear_proyecto_duplicado_devuelve_409(gestion):
    client, _, _, _ = gestion
    assert client.post("/api/projects", json=_proyecto_json()).status_code == 201
    res = client.post("/api/projects", json=_proyecto_json())
    assert res.status_code == 409


def test_detalle_devuelve_el_dict_crudo_en_forma_toml(gestion):
    client, _, _, _ = gestion
    client.post(
        "/api/projects",
        json=_proyecto_json(
            agentes={"critic": {"reglas": ["Ser implacable"], "activo": False}}
        ),
    )
    res = client.get("/api/projects/mi-show")
    assert res.status_code == 200
    crudo = res.json()
    assert crudo["proyecto"]["marca"] == "Mi Show"
    assert crudo["agentes"]["critic"]["reglas"] == ["Ser implacable"]
    assert crudo["editable"] is True


def test_detalle_de_proyecto_inexistente_devuelve_404(gestion):
    client, _, _, _ = gestion
    assert client.get("/api/projects/fantasma").status_code == 404


def test_actualizar_proyecto_cambia_el_archivo(gestion):
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json())
    datos = _proyecto_json()
    datos["proyecto"]["marca"] = "Marca Editada"
    res = client.put("/api/projects/mi-show", json=datos)
    assert res.status_code == 200
    assert client.get("/api/projects/mi-show").json()["proyecto"]["marca"] == "Marca Editada"


def test_actualizar_con_id_distinto_devuelve_400(gestion):
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json())
    res = client.put("/api/projects/mi-show", json=_proyecto_json(id="otro-id"))
    assert res.status_code == 400
    assert "inmutable" in res.json()["detail"]


def test_borrar_proyecto_quita_el_archivo(gestion):
    client, _, pstore, _ = gestion
    client.post("/api/projects", json=_proyecto_json())
    assert client.delete("/api/projects/mi-show").status_code == 200
    assert not pstore.exists("mi-show")
    assert client.get("/api/projects/mi-show").status_code == 404


def test_borrar_proyecto_inexistente_devuelve_404(gestion):
    client, _, _, _ = gestion
    assert client.delete("/api/projects/fantasma").status_code == 404


def test_borrar_proyecto_con_job_activo_devuelve_409(gestion):
    client, store, pstore, _ = gestion
    client.post("/api/projects", json=_proyecto_json())
    job = store.create_job(
        owner="ana", project_id="mi-show", topic="Un tema largo de prueba",
        num_chapters=1, max_critique_attempts=1,
    )
    store.set_status(job.job_id, JobStatus.RUNNING)
    assert client.delete("/api/projects/mi-show").status_code == 409

    store.set_status(job.job_id, JobStatus.COMPLETED, deliverable={})
    assert client.delete("/api/projects/mi-show").status_code == 200


def test_prompts_preview_compone_las_reglas_del_proyecto(gestion):
    client, _, _, _ = gestion
    client.post(
        "/api/projects",
        json=_proyecto_json(agentes={"critic": {"reglas": ["Exigir fuente"]}}),
    )
    res = client.get("/api/projects/mi-show/prompts")
    assert res.status_code == 200
    prompts = res.json()
    assert set(prompts) == {
        "planner", "continuity", "scriptwriter", "adapter", "critic",
        "technical_director",
    }
    assert "- Exigir fuente" in prompts["critic"]
    assert "REGLAS ADICIONALES" not in prompts["planner"]


def test_prompts_de_proyecto_inexistente_devuelve_404(gestion):
    client, _, _, _ = gestion
    assert client.get("/api/projects/fantasma/prompts").status_code == 404


def test_lore_ver_y_reiniciar(gestion):
    client, _, pstore, tmp_path = gestion
    client.post("/api/projects", json=_proyecto_json())
    assert client.get("/api/projects/mi-show/lore").json() == []

    from sinnema.infrastructure.lore import JsonLoreStore

    lore = JsonLoreStore(root=tmp_path / "continuidad")
    lore.save("mi-show", [make_lore_entry(term="modelo")])
    entradas = client.get("/api/projects/mi-show/lore").json()
    assert [e["term"] for e in entradas] == ["modelo"]

    assert client.delete("/api/projects/mi-show/lore").status_code == 200
    assert client.get("/api/projects/mi-show/lore").json() == []


def test_meta_roles_marca_los_estructurales(gestion):
    client, _, _, _ = gestion
    roles = {r["rol"]: r for r in client.get("/api/meta/roles").json()}
    assert set(roles) == {
        "planner", "continuity", "scriptwriter", "adapter", "critic",
        "technical_director",
    }
    assert roles["planner"]["desactivable"] is False
    assert roles["scriptwriter"]["desactivable"] is False
    assert roles["critic"]["desactivable"] is True
    assert roles["critic"]["proveedor"] == "anthropic"


def test_meta_roles_expone_tipo_descripcion_y_esencial_del_registro(gestion):
    client, _, _, _ = gestion
    roles = {r["rol"]: r for r in client.get("/api/meta/roles").json()}
    assert roles["scriptwriter"]["tipo"] == "escritor"
    assert roles["scriptwriter"]["esencial"] is True
    assert roles["adapter"]["tipo"] == "transformador"
    assert roles["adapter"]["esencial"] is False
    assert roles["critic"]["tipo"] == "revisor"
    assert roles["continuity"]["tipo"] == "contexto"
    assert roles["technical_director"]["tipo"] == "enriquecedor"
    assert roles["planner"]["tipo"] == "serie"
    for rol, datos in roles.items():
        assert datos["descripcion"], rol


def test_flujo_efectivo_del_proyecto_por_defecto(cliente):
    client, _ = cliente
    res = client.get("/api/projects/educativo/flujo-efectivo")
    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["project_id"] == "educativo"
    assert cuerpo["declarado"] is False  # sin [flujo]: semántica legacy
    assert cuerpo["hasta"] == "produccion"
    assert cuerpo["fases"]["contexto"] == ["continuity"]
    assert cuerpo["fases"]["revisor"] == "critic"
    assert cuerpo["fases"]["enriquecimiento"] == ["technical_director"]
    assert "technical_director" in cuerpo["mermaid"]
    assert cuerpo["limite_recursion"] > 0


def test_flujo_efectivo_con_flujo_declarado_y_truncado(gestion):
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json(flujo={
        "contexto": ["continuity"],
        "transformaciones": ["adapter"],
        "revisor": "critic",
        "enriquecimiento": ["technical_director"],
        "hasta": "guion_final",  # trunca: compuerta y enriquecedores no corren
    }))
    res = client.get("/api/projects/mi-show/flujo-efectivo")
    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["declarado"] is True
    assert cuerpo["hasta"] == "guion_final"
    assert cuerpo["fases"]["transformaciones"] == ["adapter"]
    assert cuerpo["fases"]["revisor"] is None
    assert cuerpo["fases"]["enriquecimiento"] == []
    assert "persona_adapter" in cuerpo["mermaid"]
    assert "chief_critic" not in cuerpo["mermaid"]


def test_flujo_efectivo_de_proyecto_inexistente_es_404(cliente):
    client, _ = cliente
    assert client.get("/api/projects/no-existe/flujo-efectivo").status_code == 404


def test_flujo_efectivo_expone_los_agentes_custom(gestion):
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json(
        flujo={"contexto": ["fact_checker"], "revisor": "critic"},
        agentes={
            "fact_checker": {
                "tipo": "contexto",
                "contrato": "notas",
                "entradas": ["capitulo", "lore"],
                "instrucciones": "Verifica los datos de {marca}.",
            },
        },
    ))
    cuerpo = client.get("/api/projects/mi-show/flujo-efectivo").json()
    assert cuerpo["fases"]["contexto"] == ["fact_checker"]
    assert cuerpo["custom"] == [{
        "rol": "fact_checker",
        "tipo": "contexto",
        "contrato": "notas",
        "entradas": ["capitulo", "lore"],
        "descripcion": "Agente custom (contexto; contrato notas)",
    }]


def test_crear_proyecto_con_flujo_invalido_reporta_problemas(gestion):
    client, _, _, _ = gestion
    res = client.post("/api/projects", json=_proyecto_json(flujo={
        "hasta": "auditado",  # sin revisor: error accionable
    }))
    assert res.status_code == 400
    assert "revisor" in str(res.json())


def test_crear_proyecto_con_flujo_valido_persiste_el_flujo(gestion):
    client, _, _, _ = gestion
    res = client.post("/api/projects", json=_proyecto_json(flujo={
        "contexto": ["continuity"],
        "revisor": "critic",
        "hasta": "auditado",
    }))
    assert res.status_code in (201, 200)
    crudo = client.get("/api/projects/mi-show").json()
    assert crudo["flujo"]["hasta"] == "auditado"
    assert crudo["flujo"]["revisor"] == "critic"


def test_jobs_filtrados_por_proyecto(gestion):
    client, store, pstore, _ = gestion
    client.post("/api/projects", json=_proyecto_json())
    store.create_job(owner="ana", project_id="mi-show", topic="t", num_chapters=1,
                     max_critique_attempts=1)
    store.create_job(owner="ana", project_id="otro", topic="t", num_chapters=1,
                     max_critique_attempts=1)
    res = client.get("/api/jobs", params={"project_id": "mi-show"},
                     headers={"X-Owner": "ana"})
    ids = {j["project_id"] for j in res.json()}
    assert ids == {"mi-show"}


def test_series_sin_intentos_usa_el_default_del_proyecto(gestion):
    client, store, _, _ = gestion
    client.post(
        "/api/projects",
        json=_proyecto_json(pipeline={"intentos_maximos_de_critica": 3}),
    )
    res = client.post("/api/series", json={
        "project_id": "mi-show", "topic": "Fotosíntesis en 60 segundos",
        "num_chapters": 2,
    }, headers={"X-Owner": "ana"})
    assert res.status_code == 202
    job = store.get_job(res.json()["job_id"])
    assert job.max_critique_attempts == 3

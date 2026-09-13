"""Tests de la API HTTP (FastAPI TestClient) con worker real + gateway falso."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sinnema.infrastructure.api.app import create_app
from sinnema.infrastructure.projects import ProjectFileStore, load_project
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


def test_home_cascada_web_dist_o_sin_build(cliente):
    """§8.4/§12.3: con build de Vite sirve `web/dist`; sin build, la página
    que indica cómo construirla (el legacy de static/ ya no existe)."""
    client, _ = cliente
    dist_index = Path(__file__).resolve().parents[1] / "web" / "dist" / "index.html"
    res = client.get("/")
    assert res.status_code == 200
    if dist_index.is_file():
        assert "Red de agentes 3D" in res.text
    else:
        assert "npm run build" in res.text


def test_assets_inexistente_da_404(cliente):
    client, _ = cliente
    res = client.get("/assets/que-no-existe.js")
    assert res.status_code == 404


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


# --------------------- /red: red efectiva (spec-red-3d §5.1) ---------------------


def _ids_de_mermaid(mermaid: str) -> set:
    """Ids de nodo declarados en el diagrama Mermaid de langgraph."""
    import re

    ids = set()
    for linea in mermaid.splitlines():
        m = re.match(r"^\t([A-Za-z0-9_]+)\(", linea)
        if m:
            ids.add(m.group(1))
    return ids


def test_red_del_proyecto_por_defecto(cliente):
    client, _ = cliente
    res = client.get("/api/projects/educativo/red")
    assert res.status_code == 200
    cuerpo = res.json()
    assert cuerpo["project_id"] == "educativo"
    assert cuerpo["declarado"] is False  # sin [flujo]: semántica legacy
    assert cuerpo["hasta"] == "produccion"
    assert cuerpo["limite_recursion"] > 0

    nodos = {n["id"]: n for n in cuerpo["nodes"]}
    assert set(nodos) == {
        "plan_series", "continuity_master", "scriptwriter", "persona_adapter",
        "chief_critic", "technical_director", "commit_episode", "fail_chapter",
    }
    # Anotación de registro: fase/tipo/estructural/esencial (§5.1).
    assert nodos["plan_series"]["rol"] == "planner"
    assert nodos["plan_series"]["fase"] == "serie"
    assert nodos["plan_series"]["estructural"] is True
    assert nodos["plan_series"]["esencial"] is True
    assert nodos["continuity_master"]["fase"] == "contexto"
    assert nodos["continuity_master"]["estructural"] is False
    assert nodos["persona_adapter"]["fase"] == "transformacion"
    assert nodos["chief_critic"]["fase"] == "compuerta"
    assert nodos["chief_critic"]["estructural"] is True
    assert nodos["technical_director"]["fase"] == "enriquecimiento"
    # Cierre: estructural, sin agente ni LLM.
    for cierre in ("commit_episode", "fail_chapter"):
        assert nodos[cierre]["tipo"] == "cierre"
        assert nodos[cierre]["fase"] == "cierre"
        assert nodos[cierre]["estructural"] is True
        assert nodos[cierre]["rol"] is None
        assert nodos[cierre]["llm"] is None
        assert nodos[cierre]["descripcion"]

    # LLMConfig resuelto por rol (registro, sin overrides): sin top_p/max_tokens.
    llm = nodos["scriptwriter"]["llm"]
    assert llm == {
        "proveedor": "openai", "modelo": "gpt-4o",
        "temperatura": 0.8, "tools": [],
    }

    aristas = {e["id"]: e for e in cuerpo["edges"]}
    assert "__start__->plan_series" in aristas
    assert "commit_episode->__end__" in aristas
    assert aristas["plan_series->continuity_master"]["condicional"] is False
    assert aristas["plan_series->continuity_master"]["labels"] == []
    # El ciclo de crítica con sus labels condicionales.
    assert aristas["chief_critic->scriptwriter"]["condicional"] is True
    assert aristas["chief_critic->scriptwriter"]["labels"] == ["revise"]
    assert aristas["chief_critic->fail_chapter"]["labels"] == ["skip_chapter"]
    assert aristas["commit_episode->__end__"]["labels"] == ["series_complete"]
    assert aristas["commit_episode->continuity_master"]["labels"] == ["next_chapter"]


def test_red_coincide_en_nodos_con_el_mermaid_por_proyecto_empaquetado(cliente):
    """Criterio de aceptación de la fase: /red == Mermaid de flujo-efectivo."""
    client, _ = cliente
    proyectos = [p["project_id"] for p in client.get("/api/projects").json()]
    assert len(proyectos) >= 5  # los shows empaquetados del repo
    for pid in proyectos:
        red = client.get(f"/api/projects/{pid}/red").json()
        mermaid = client.get(f"/api/projects/{pid}/flujo-efectivo").json()["mermaid"]
        ids_mermaid = _ids_de_mermaid(mermaid) - {"__start__", "__end__"}
        assert {n["id"] for n in red["nodes"]} == ids_mermaid, pid
        # Toda arista conecta nodos (o anclas) de la misma red.
        for arista in red["edges"]:
            extremos = {arista["from"], arista["to"]} - {"__start__", "__end__"}
            assert extremos <= ids_mermaid, (pid, arista)


def test_red_de_proyecto_inexistente_es_404(cliente):
    client, _ = cliente
    assert client.get("/api/projects/no-existe/red").status_code == 404


def test_red_refleja_los_overrides_llm_del_proyecto(gestion):
    """[agentes.<rol>] llega resuelto a la escena: proyecto > default."""
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json(
        flujo={"contexto": ["continuity"], "revisor": "critic"},
        agentes={
            "scriptwriter": {
                "proveedor": "ollama", "modelo": "llama3.1", "temperatura": 0.5,
                "top_p": 0.9, "max_tokens": 4096, "tools": ["buscar_lore"],
            },
        },
    ))
    red = client.get("/api/projects/mi-show/red").json()
    llm = next(n["llm"] for n in red["nodes"] if n["id"] == "scriptwriter")
    assert llm == {
        "proveedor": "ollama", "modelo": "llama3.1", "temperatura": 0.5,
        "top_p": 0.9, "max_tokens": 4096, "tools": ["buscar_lore"],
    }


def test_red_con_agente_custom(gestion):
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json(
        flujo={"contexto": ["fact_checker"], "revisor": "critic"},
        agentes={
            "fact_checker": {
                "tipo": "contexto", "contrato": "notas",
                "entradas": ["capitulo", "lore"],
                "instrucciones": "Verifica los datos de {marca}.",
                "top_p": 0.5,
            },
        },
    ))
    red = client.get("/api/projects/mi-show/red").json()
    nodos = {n["id"]: n for n in red["nodes"]}
    assert "fact_checker" in nodos  # el nodo del custom es su rol
    custom = nodos["fact_checker"]
    assert custom["fase"] == "contexto"
    assert custom["tipo"] == "contexto"
    assert custom["estructural"] is False
    assert custom["custom"] == {
        "contrato": "notas",
        "entradas": ["capitulo", "lore"],
        "instrucciones": "Verifica los datos de {marca}.",
    }
    # LLM del custom: default genérico (gpt-4o-mini) con el top_p del proyecto.
    assert custom["llm"]["modelo"] == "gpt-4o-mini"
    assert custom["llm"]["top_p"] == 0.5
    assert "__start__->plan_series" in {e["id"] for e in red["edges"]}


def test_red_con_hasta_plan_cierra_sin_bucle_de_capitulos(gestion):
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json(
        flujo={"contexto": ["continuity"], "hasta": "plan"},
    ))
    red = client.get("/api/projects/mi-show/red").json()
    assert red["hasta"] == "plan"
    nodos = {n["id"]: n for n in red["nodes"]}
    assert set(nodos) == {"plan_series", "consolidar_plan"}
    assert nodos["consolidar_plan"]["tipo"] == "cierre"
    assert nodos["consolidar_plan"]["llm"] is None
    ids_aristas = {e["id"] for e in red["edges"]}
    assert ids_aristas == {
        "__start__->plan_series",
        "plan_series->consolidar_plan",
        "consolidar_plan->__end__",
    }


# ------------- /red con la capa de media (spec-recursos-ancla §9.2) -------------


def test_red_sin_media_es_exactamente_la_de_siempre(gestion):
    """Paridad dura: sin sección [media], la red NO cambia (mismo nodo set
    que el test por defecto; render_keyframes ni se asoma)."""
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json())
    red = client.get("/api/projects/mi-show/red").json()
    assert {n["id"] for n in red["nodes"]} == {
        "plan_series", "continuity_master", "scriptwriter", "persona_adapter",
        "chief_critic", "technical_director", "commit_episode", "fail_chapter",
    }


def test_red_con_media_incluye_el_nodo_render_keyframes(gestion):
    """Con ``[media].keyframes = true`` el nodo estructural entra SOLO por
    derivación del grafo (§9.2), entre el enriquecimiento y el commit."""
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json(media={"keyframes": True}))
    red = client.get("/api/projects/mi-show/red").json()
    nodos = {n["id"]: n for n in red["nodes"]}
    assert set(nodos) == {
        "plan_series", "continuity_master", "scriptwriter", "persona_adapter",
        "chief_critic", "technical_director", "render_keyframes",
        "commit_episode", "fail_chapter",
    }
    media = nodos["render_keyframes"]
    assert media["rol"] is None
    assert media["tipo"] == "media"
    assert media["fase"] == "media"
    assert media["estructural"] is True
    assert media["esencial"] is False
    assert media["llm"] is None
    assert "keyframe" in media["descripcion"]
    # Cableado real del grafo: último enriquecedor → media → commit.
    aristas = {e["id"] for e in red["edges"]}
    assert "technical_director->render_keyframes" in aristas
    assert "render_keyframes->commit_episode" in aristas


def test_red_con_media_coincide_con_el_mermaid_de_flujo_efectivo(gestion):
    """El invariante /red == Mermaid se sostiene también con el nodo media."""
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json(media={"keyframes": True}))
    red = client.get("/api/projects/mi-show/red").json()
    mermaid = client.get("/api/projects/mi-show/flujo-efectivo").json()["mermaid"]
    ids_mermaid = _ids_de_mermaid(mermaid) - {"__start__", "__end__"}
    assert {n["id"] for n in red["nodes"]} == ids_mermaid
    assert "render_keyframes" in ids_mermaid


def test_red_con_media_y_hasta_plan_no_tiene_nodo_de_media(gestion):
    """hasta = plan: la corrida termina sin episodios, no hay escenas que
    renderizar — el nodo no entra (y el grafo compila sin aristas colgando)."""
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json(
        flujo={"contexto": ["continuity"], "hasta": "plan"},
        media={"keyframes": True},
    ))
    red = client.get("/api/projects/mi-show/red").json()
    assert {n["id"] for n in red["nodes"]} == {"plan_series", "consolidar_plan"}


# ------------------------ /api/meta/catalogos (spec §5) ------------------------


def test_meta_catalogos_para_los_formularios(cliente):
    client, _ = cliente
    cuerpo = client.get("/api/meta/catalogos").json()
    assert cuerpo["proveedores"] == ["anthropic", "openai", "google", "ollama"]
    # Modelos sugeridos: los que usan los defaults del sistema, por proveedor.
    assert "gpt-4o" in cuerpo["modelos"]["openai"]
    assert "gpt-4o-mini" in cuerpo["modelos"]["openai"]
    assert cuerpo["modelos"]["anthropic"] == ["claude-3-5-sonnet-latest"]
    assert cuerpo["modelos"]["google"] == ["gemini-1.5-pro"]
    assert cuerpo["modelos"]["ollama"] == []
    # Tools integradas con descripción (lo que el modelo ve del catálogo).
    tools = {t["nombre"]: t["descripcion"] for t in cuerpo["tools"]}
    assert set(tools) == {"buscar_lore", "leer_formato"}
    assert all(tools.values())
    assert cuerpo["hitos"] == [
        "plan", "guion", "guion_final", "auditado", "produccion",
    ]
    assert cuerpo["tipos_custom"] == ["contexto", "enriquecedor", "revisor"]
    assert set(cuerpo["contratos"]) == {"notas", "texto", "dictamen"}
    assert set(cuerpo["entradas_custom"]) == {
        "capitulo", "guion", "lore", "plan", "directivas",
    }


def test_meta_catalogos_expone_los_catalogos_de_anclas(cliente):
    """Catálogos de la biblioteca (spec-recursos-ancla §9.1): tipos, estados,
    roles de batería por tipo y batería mínima (checklist del lock en la web)."""
    client, _ = cliente
    anclas = client.get("/api/meta/catalogos").json()["anclas"]
    assert anclas["tipos"] == ["personaje", "lugar", "objeto", "estilo"]
    assert anclas["estados"] == ["borrador", "propuesto", "lockeado", "retirado"]
    assert anclas["roles_por_tipo"]["personaje"] == [
        "hero_portrait", "turnaround_front", "turnaround_quarter",
        "turnaround_side", "turnaround_back", "expression_sheet", "outfit_variant",
    ]
    assert anclas["roles_por_tipo"]["lugar"] == [
        "establishing_shot", "coverage_angle", "lighting_reference",
    ]
    assert anclas["roles_por_tipo"]["objeto"] == ["prop_hero", "prop_detail"]
    assert anclas["roles_por_tipo"]["estilo"] == ["style_reference"]
    assert anclas["bateria_minima"]["personaje"] == [
        "hero_portrait", "turnaround_front", "turnaround_side", "turnaround_back",
    ]
    assert anclas["bateria_minima"]["lugar"] == ["establishing_shot"]
    assert anclas["bateria_minima"]["objeto"] == ["prop_hero"]
    assert anclas["bateria_minima"]["estilo"] == ["style_reference"]


# ------------- Round-trip de la config LLM por PUT/GET (spec §14) -------------


def test_config_llm_hace_round_trip_por_put_y_get(gestion):
    """Criterio de aceptación: top_p/max_tokens/tools persisten en el TOML."""
    client, _, _, _ = gestion
    config = {
        "temperatura": 0.8, "top_p": 0.95, "max_tokens": 4096,
        "tools": ["buscar_lore"],
    }
    client.post("/api/projects", json=_proyecto_json(
        flujo={"contexto": ["continuity"], "revisor": "critic"},
        agentes={"scriptwriter": config},
    ))
    crudo = client.get("/api/projects/mi-show").json()
    assert crudo["agentes"]["scriptwriter"] == config

    # PUT del cuerpo crudo (sin la clave derivada `editable`) con mutación.
    crudo.pop("editable")
    crudo["agentes"]["scriptwriter"]["max_tokens"] = 8192
    crudo["agentes"]["scriptwriter"]["tools"] = ["buscar_lore", "leer_formato"]
    assert client.put("/api/projects/mi-show", json=crudo).status_code == 200

    re_leido = client.get("/api/projects/mi-show").json()
    assert re_leido["agentes"]["scriptwriter"]["max_tokens"] == 8192
    assert re_leido["agentes"]["scriptwriter"]["tools"] == [
        "buscar_lore", "leer_formato",
    ]
    assert re_leido["agentes"]["scriptwriter"]["top_p"] == 0.95


def test_put_con_config_llm_invalida_es_400(gestion):
    client, _, _, _ = gestion
    client.post("/api/projects", json=_proyecto_json())
    datos = _proyecto_json(agentes={"scriptwriter": {"top_p": 1.5}})
    res = client.put("/api/projects/mi-show", json=datos)
    assert res.status_code == 400
    assert "top_p" in res.json()["detail"]


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


# ----------------- Eventos por nodo y spec desfasado (red-3d) -----------------


def test_eventos_por_nodo_en_timeline(cliente):
    """Con el gateway falso, el timeline muestra la secuencia real de nodos:
    plan, compuerta y el pipeline completo, con rol y claves por paso."""
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis en 60 segundos",
        "num_chapters": 2,
    }, headers={"X-Owner": "ana"})
    job_id = res.json()["job_id"]
    esperar(store, job_id)

    historia = client.get(f"/api/jobs/{job_id}/events/history").json()
    kinds = {e["kind"] for e in historia}
    assert {"node_start", "node_end", "progress", "done"} <= kinds

    inicios = [e for e in historia if e["kind"] == "node_start"]
    nodos = [e["node"] for e in inicios]
    assert nodos[0] == "plan_series"
    assert "scriptwriter" in nodos and "chief_critic" in nodos

    # Payload §6.2: node_start trae node/rol/paso; node_end suma claves.
    arranque_plan = inicios[0]
    assert arranque_plan["rol"] == "planner"
    assert arranque_plan["paso"] == 1
    fin_plan = next(
        e for e in historia
        if e["kind"] == "node_end" and e["node"] == "plan_series"
    )
    assert "series_plan" in fin_plan["claves"]

    # Los nodos sin agente (cierre) reportan rol null; los legacy, mensaje.
    assert any(e["kind"] == "progress" and "mensaje" in e for e in historia)

    # El ciclo de crítica re-invoca al guionista (2 capítulos = 2 corridas).
    assert nodos.count("scriptwriter") >= 2


def test_sse_emite_data_json_y_termina(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis", "num_chapters": 2,
    }, headers={"X-Owner": "ana"})
    job_id = res.json()["job_id"]
    esperar(store, job_id)

    with client.stream("GET", f"/api/jobs/{job_id}/events") as respuesta:
        cuerpo = "".join(respuesta.iter_text())
    assert "event: node_start" in cuerpo
    assert '"kind": "node_start"' in cuerpo and '"node": "plan_series"' in cuerpo
    assert '"mensaje"' in cuerpo  # kinds legacy viajan como texto en el JSON
    assert "event: end" in cuerpo


def test_spec_desfasado_compara_con_toml_vigente(cliente):
    client, store = cliente
    job = store.create_job(owner="ana", project_id="comida", topic="Asado",
                           num_chapters=1, max_critique_attempts=2)
    store.set_status(job.job_id, JobStatus.RUNNING)

    # Sin huella congelada no se afirma desfasado (False, no un error).
    assert client.get(f"/api/jobs/{job.job_id}").json()["spec_desfasado"] is False

    # Huella vieja + TOML vigente distinto → desfasado.
    store.set_spec_fingerprint(job.job_id, "huella-vieja")
    detalle = client.get(f"/api/jobs/{job.job_id}").json()
    assert detalle["spec_desfasado"] is True

    # Con la huella correcta del TOML vigente → no desfasado. La app del
    # fixture resuelve "comida" por la misma cascada que en dev (repo).
    import tomllib
    from sinnema.infrastructure.projects import resolve_writable_projects_dir
    from sinnema.infrastructure.projects.store import fingerprint_spec
    with open(resolve_writable_projects_dir() / "comida.toml", "rb") as f:
        huella_vigente = fingerprint_spec(tomllib.load(f))
    store.set_spec_fingerprint(job.job_id, huella_vigente)
    assert client.get(f"/api/jobs/{job.job_id}").json()["spec_desfasado"] is False

    # Un job terminal no reporta el indicador.
    store.set_status(job.job_id, JobStatus.COMPLETED)
    assert "spec_desfasado" not in client.get(f"/api/jobs/{job.job_id}").json()


# --------------------- Artefactos de auditoría (§5/§7.4) ---------------------


def test_artifacts_lista_y_detalle_con_prompts(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis", "num_chapters": 2,
    }, headers={"X-Owner": "ana"})
    job_id = res.json()["job_id"]
    esperar(store, job_id)

    pasos = client.get(f"/api/jobs/{job_id}/artifacts").json()
    assert pasos, "el job completado debe tener pasos de auditoría"
    nombres = [p["paso"] for p in pasos]
    assert "solicitud" in nombres and "plan_series" in nombres
    assert [p["n"] for p in pasos] == sorted(p["n"] for p in pasos)

    # Detalle del paso del planner: artefacto JSON + prompts (con el gateway
    # real del runner; con gateway falso no hay prompts → al menos no explota).
    detalle = client.get(f"/api/jobs/{job_id}/artifacts/{pasos[0]['n']}").json()
    assert detalle["paso"] == pasos[0]["paso"]
    if detalle["paso"] == "plan_series":
        assert detalle["artefacto"] is not None
        assert detalle["artefacto"].get("chapters")


def test_artifacts_paso_inexistente_da_404(cliente):
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis", "num_chapters": 2,
    }, headers={"X-Owner": "ana"})
    job_id = res.json()["job_id"]
    esperar(store, job_id)
    assert client.get(f"/api/jobs/{job_id}/artifacts/999").status_code == 404


def test_prompts_del_paso_llegan_al_detalle(cliente, tmp_path):
    """El detalle de un paso empareja su NNN_<nodo>_prompts.txt (§7.4). El
    lado gateway (escritura vía prompt_audit) está cubierto en test_gateway;
    acá se valida el contrato del endpoint con el archivo presente."""
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis", "num_chapters": 2,
    }, headers={"X-Owner": "ana"})
    job_id = res.json()["job_id"]
    esperar(store, job_id)

    pasos = client.get(f"/api/jobs/{job_id}/artifacts").json()
    paso_plan = next(p for p in pasos if p["paso"] == "plan_series")

    carpeta = tmp_path / "auditoria" / "educativo" / f"serie_{job_id}"
    contenido = "=== SystemMessage ===\n...\n=== Respuesta estructurada (JSON) ===\n{}\n"
    (carpeta / f"{paso_plan['n']:03d}_plan_series_prompts.txt").write_text(
        contenido, encoding="utf-8"
    )

    detalle = client.get(f"/api/jobs/{job_id}/artifacts/{paso_plan['n']}").json()
    assert detalle["prompts"] == contenido
    assert detalle["artefacto"] is not None


# --------------------- Cobertura §13 restante (Fase 8a) ---------------------


def test_historia_eventos_con_since(cliente):
    """GET /events/history?since= devuelve solo los posteriores al id."""
    client, store = cliente
    res = client.post("/api/series", json={
        "project_id": "educativo", "topic": "Fotosíntesis", "num_chapters": 2,
    }, headers={"X-Owner": "ana"})
    job_id = res.json()["job_id"]
    esperar(store, job_id)

    completa = client.get(f"/api/jobs/{job_id}/events/history").json()
    assert len(completa) > 2
    eventos_store = store.events_since(job_id)
    desde = eventos_store[len(eventos_store) // 2].id
    parcial = client.get(f"/api/jobs/{job_id}/events/history?since={desde}").json()
    assert 0 < len(parcial) < len(completa)


def test_spec_desfasado_en_listado_de_jobs(cliente):
    """GET /api/jobs (lista) también expone spec_desfasado para running."""
    client, store = cliente
    job = store.create_job(owner="ana", project_id="comida", topic="Asado",
                           num_chapters=1, max_critique_attempts=2)
    store.set_status(job.job_id, JobStatus.RUNNING)
    store.set_spec_fingerprint(job.job_id, "huella-vieja")

    lista = client.get("/api/jobs", headers={"X-Owner": "ana"}).json()
    objetivo = next(j for j in lista if j["job_id"] == job.job_id)
    assert objetivo["spec_desfasado"] is True


def test_worker_publica_tool_start_y_tool_end(tmp_path):
    """El stream del job con tools termina en job_events (§13: gateway falso
    que emite tokens/tools)."""
    from sinnema.infrastructure.projects import load_project

    class GatewayConTools:
        def __init__(self, base):
            self._base = base
            self._sink = None

        def __call__(self, proyecto, event_sink=None, tools=None):
            self._sink = event_sink
            assert tools is not None  # el runner inyecta el registro del proyecto
            return self

        def generate(self, role, schema, system_prompt, user_prompt, *, on_event=None):
            if self._sink is not None and role == "scriptwriter":
                self._sink(role, {"tipo": "tool_start", "tool": "buscar_lore",
                                  "args": {"consulta": "fotosíntesis"}})
                self._sink(role, {"tipo": "tool_end", "tool": "buscar_lore",
                                  "resumen": "2 entradas"})
            return self._base.generate(role, schema, system_prompt, user_prompt)

    store = SqliteJobStore(tmp_path / "jobs.sqlite")
    worker = SeriesWorker(
        store,
        checkpoint_dir=tmp_path / "checkpoints",
        audit_root=tmp_path / "auditoria",
        lore_root=tmp_path / "continuidad",
        gateway_factory=GatewayConTools(gateway_con_serie(num_chapters=2)),
        project_loader=load_project,
    )
    worker.start()
    job = store.create_job(owner="ana", project_id="educativo",
                           topic="Fotosíntesis", num_chapters=2,
                           max_critique_attempts=2)
    worker.submit(job.job_id)
    for _ in range(100):
        leido = store.get_job(job.job_id)
        if leido.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            break
        time.sleep(0.1)
    assert leido.status is JobStatus.COMPLETED

    kinds = [e.kind for e in store.events_since(job.job_id)]
    assert "tool_start" in kinds and "tool_end" in kinds
    tool_end = next(e for e in store.events_since(job.job_id) if e.kind == "tool_end")
    assert tool_end.payload["node"] == "scriptwriter"
    assert tool_end.payload["resumen"].startswith("2 entradas")

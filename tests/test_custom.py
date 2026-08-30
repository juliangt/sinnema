"""Tests de agentes custom (definidos 100% en el TOML; spec §8).

Cubren las validaciones §9.7-10, la síntesis de definiciones, los prompts
custom (placeholders + reglas + bloques de entrada), el pipeline de punta a
punta con un agente custom de contexto y con un revisor custom, y el wiring
del gateway con contratos genéricos.
"""
from __future__ import annotations

import pytest

from sinnema.application.graph import build_pipeline_graph
from sinnema.application.ports import ROLE_PLANNER, ROLE_SCRIPTWRITER
from sinnema.application.projects import project_from_dict
from sinnema.application.registry import (
    CONTRATOS_GENERICOS,
    build_role_system_prompts,
    definiciones_custom,
)
from sinnema.application.requests import SeriesRequest, build_initial_state
from sinnema.application.settings import PipelineSettings
from sinnema.application.use_cases import build_deliverable
from sinnema.domain.models import NotasDelAgente, QualityAudit

from conftest import (
    FakeGateway,
    entorno_llm_limpio,  # noqa: F401 - fixture usada vía parámetro
    gateway_con_serie,
    make_audit,
    make_plan,
    make_project,
)


def _datos_proyecto(**extra):
    datos = {
        "proyecto": {
            "id": "custom-test",
            "marca": "Custom Test",
            "concepto": "micro-videos de prueba verticales",
            "tema_por_defecto": "Un tema de prueba suficientemente largo",
            "idioma": "Español",
        },
        "voz": {
            "audiencia": "Audiencia de prueba",
            "contexto_cultural": "Contexto cultural de prueba",
            "tono": "tono de prueba",
            "guia_de_estilo": "guía de prueba",
            "restricciones": "restricciones de prueba",
        },
        "visual": {
            "estilo_maestro": "3D render style with clean environment and lighting",
        },
        "flujo": {
            "contexto": ["continuity", "fact_checker"],
            "revisor": "critic",
        },
        "agentes": {
            "fact_checker": {
                "tipo": "contexto",
                "contrato": "notas",
                "entradas": ["capitulo", "lore"],
                "instrucciones": (
                    "Eres el verificador de datos de {marca}. Revisa el "
                    "capítulo y anota todo dato no verificable."
                ),
            },
        },
    }
    datos.update(extra)
    return datos


# ----------------------------- validaciones -----------------------------


def test_agente_custom_valido_carga():
    spec = project_from_dict(_datos_proyecto())
    config = spec.agentes["fact_checker"]
    assert config.es_custom
    assert config.tipo == "contexto"
    assert config.contrato == "notas"
    assert config.entradas == ("capitulo", "lore")
    assert "{marca}" in config.instrucciones


@pytest.mark.parametrize("cambios,fragmento", [
    ({"tipo": "escritor"}, "debe ser uno de"),                     # tipo vedado
    ({"contrato": "dictamen"}, "no es válido para un agente custom"),
    ({"instrucciones": ""}, "exige 'instrucciones'"),
    (
        {"instrucciones": "Usa el placeholder {render_final} siempre."},
        "placeholders desconocidos",
    ),
    ({"entradas": ["chisme"]}, "fuera del catálogo"),
])
def test_custom_invalido_reporta_problemas(cambios, fragmento):
    datos = _datos_proyecto()
    datos["agentes"]["fact_checker"].update(cambios)
    with pytest.raises(ValueError, match=fragmento):
        project_from_dict(datos)


def test_custom_sin_flujo_es_error():
    datos = _datos_proyecto()
    del datos["flujo"]
    with pytest.raises(ValueError, match="no declara \\[flujo\\]"):
        project_from_dict(datos)


def test_custom_no_listado_en_flujo_es_error():
    datos = _datos_proyecto()
    datos["flujo"]["contexto"] = ["continuity"]  # fact_checker queda fuera
    with pytest.raises(ValueError, match="no está listado en \\[flujo\\]"):
        project_from_dict(datos)


def test_rol_del_registro_no_puede_declarar_tipo():
    datos = _datos_proyecto()
    datos["agentes"]["adapter"] = {
        "tipo": "enriquecedor",
        "contrato": "notas",
        "entradas": ["guion"],
        "instrucciones": "Reescribe el guion.",
    }
    with pytest.raises(ValueError, match="ya existe en el registro"):
        project_from_dict(datos)


def test_revisor_custom_exige_contrato_dictamen():
    datos = _datos_proyecto()
    datos["flujo"] = {"revisor": "verificador_final"}
    datos["agentes"] = {
        "verificador_final": {
            "tipo": "revisor",
            "contrato": "notas",  # inválido para un revisor
            "entradas": ["guion"],
            "instrucciones": "Audita el guion con rigor.",
        },
    }
    with pytest.raises(ValueError, match="exige el contrato 'dictamen'"):
        project_from_dict(datos)


# ----------------------------- síntesis -----------------------------


def test_definiciones_custom_sintetiza_contexto_y_revisor():
    datos = _datos_proyecto()
    datos["flujo"]["revisor"] = "verificador_final"
    datos["agentes"]["verificador_final"] = {
        "tipo": "revisor",
        "contrato": "dictamen",
        "entradas": ["guion", "directivas"],
        "instrucciones": "Audita el guion de {marca} con rigor.",
    }
    spec = project_from_dict(datos)

    customs = definiciones_custom(spec)
    assert set(customs) == {"fact_checker", "verificador_final"}
    # contexto: adjunta a la pizarra
    assert customs["fact_checker"].adjunto is True
    assert customs["fact_checker"].produce == "artefactos"
    assert customs["fact_checker"].nodo == "fact_checker"
    assert customs["fact_checker"].esquema is CONTRATOS_GENERICOS["notas"]
    # revisor: escribe el slot canónico de la compuerta
    assert customs["verificador_final"].adjunto is False
    assert customs["verificador_final"].produce == "qa_verdict"
    assert customs["verificador_final"].esquema is QualityAudit


def test_system_prompt_custom_renderiza_placeholders_y_reglas():
    from sinnema.application.projects import AgentConfig

    spec = project_from_dict(_datos_proyecto(
        agentes={
            "fact_checker": {
                "tipo": "contexto",
                "contrato": "notas",
                "entradas": ["capitulo"],
                "instrucciones": "Eres el verificador de {marca}.",
                "reglas": ["Citar fuente en cada hallazgo"],
            },
        },
    ))
    prompts = build_role_system_prompts(spec)
    assert "Eres el verificador de Custom Test." in prompts["fact_checker"]
    assert "REGLAS ADICIONALES DEL PROYECTO" in prompts["fact_checker"]
    assert "Citar fuente en cada hallazgo" in prompts["fact_checker"]


# ----------------------------- pipeline punta a punta -----------------------------


def _correr(spec, gw, num_chapters: int = 1):
    request = SeriesRequest(project=spec, num_chapters=num_chapters)
    request.validate()
    grafo = build_pipeline_graph(gw, spec, PipelineSettings())
    final = None
    for snapshot in grafo.stream(
        build_initial_state(request), config={"recursion_limit": 300},
        stream_mode="values",
    ):
        final = snapshot
    return final


def test_agente_custom_de_contexto_corre_y_adjunta_al_episodio():
    spec = project_from_dict(_datos_proyecto())
    gw = gateway_con_serie(num_chapters=1)
    gw.add(
        "fact_checker",
        [NotasDelAgente(
            nota_principal="Todos los datos del capítulo son verificables.",
            puntos_clave=["Fuente: documentación técnica"],
        )],
    )
    final = _correr(spec, gw, num_chapters=1)

    # Orden: continuity -> fact_checker -> scriptwriter...
    assert gw.calls.index("continuity") < gw.calls.index("fact_checker")
    assert gw.calls.index("fact_checker") < gw.calls.index("scriptwriter")
    episodio = final["completed_episodes"][0]
    adjunto = next(
        (a for a in episodio.adjuntos if a.rol == "fact_checker"), None
    )
    assert adjunto is not None
    assert adjunto.artefacto["nota_principal"].startswith("Todos los datos")
    entregable = build_deliverable(final)
    assert entregable.alcance == "produccion"


def test_revisor_custom_hace_de_compuerta():
    datos = _datos_proyecto()
    datos["flujo"] = {
        "contexto": ["continuity"],
        "revisor": "verificador_final",
        "enriquecimiento": ["technical_director"],
    }
    datos["agentes"] = {
        "verificador_final": {
            "tipo": "revisor",
            "contrato": "dictamen",
            "entradas": ["guion"],
            "instrucciones": "Audita el guion de {marca} con rigor.",
        },
    }
    spec = project_from_dict(datos)
    gw = gateway_con_serie(num_chapters=1)
    gw.add("verificador_final", [make_audit(approved=True, score=9)])
    final = _correr(spec, gw, num_chapters=1)

    assert gw.calls.count("critic") == 0  # el crítico de código no participa
    episodio = final["completed_episodes"][0]
    assert episodio.audit is not None and episodio.audit.approved
    assert episodio.technical is not None


# ----------------------------- gateway -----------------------------


def test_build_gateway_construye_cliente_para_el_rol_custom(entorno_llm_limpio):
    from sinnema.infrastructure.llm.gateway import build_gateway

    spec = project_from_dict(_datos_proyecto())
    gateway = build_gateway(spec)
    assert "fact_checker" in gateway._structured
    # El catálogo de esquemas del gateway incluye el contrato genérico.
    assert gateway._schemas["fact_checker"] is NotasDelAgente


def test_gateway_detecta_esquema_intercambiado_en_rol_custom(entorno_llm_limpio):
    from sinnema.domain.models import TextoLibre
    from sinnema.infrastructure.llm.gateway import build_gateway

    spec = project_from_dict(_datos_proyecto())
    gateway = build_gateway(spec)
    with pytest.raises(ValueError, match="no coinciden"):
        gateway.generate(
            "fact_checker", TextoLibre, "system", "user",
        )

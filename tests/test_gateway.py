"""Tests del adaptador LangChainStructuredGateway (puerto -> LangChain)."""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from sinnema.application.ports import ROLE_SCHEMAS
from sinnema.domain.models import ContinuityDirectives, SeriesPlan
from sinnema.infrastructure.llm.gateway import (
    LangChainStructuredGateway,
    RetryPolicy,
)

from conftest import (
    make_adapted,
    make_audit,
    make_directives,
    make_draft,
    make_package,
    make_plan,
)


class FakeRunnable:
    """Runnable que falla N veces y después devuelve el resultado pactado."""

    def __init__(self, resultado, fallos: int = 0):
        self._resultado = resultado
        self._fallos = fallos
        self.invocaciones = 0
        self.ultimo_mensajes = None

    def invoke(self, mensajes):
        self.invocaciones += 1
        self.ultimo_mensajes = mensajes
        if self.invocaciones <= self._fallos:
            raise ConnectionError("fallo transitorio simulado")
        return self._resultado


class FakeChat:
    """ChatModel falso que recuerda el esquema con el que se configura."""

    def __init__(self, resultado, fallos: int = 0):
        self._resultado = resultado
        self._fallos = fallos
        self.runnable: FakeRunnable | None = None

    def with_structured_output(self, schema):
        assert schema is type(self._resultado), (
            f"wiring: se pidió {schema} pero el doble devuelve "
            f"{type(self._resultado)}"
        )
        self.runnable = FakeRunnable(self._resultado, self._fallos)
        return self.runnable


def clientes_completos(**fallos_por_rol) -> dict:
    """Clientes falsos para los 6 roles; opcionalmente con fallos por rol."""
    draft = make_draft()
    resultados = {
        "planner": make_plan(1),
        "continuity": make_directives(),
        "scriptwriter": draft,
        "adapter": make_adapted(draft),
        "critic": make_audit(),
        "technical_director": make_package(draft),
    }
    return {
        rol: FakeChat(resultado, fallos_por_rol.get(rol, 0))
        for rol, resultado in resultados.items()
    }


def test_generate_devuelve_instancia_del_esquema():
    gateway = LangChainStructuredGateway(clientes_completos(), RetryPolicy(1, 0.0))
    plan = gateway.generate(
        "planner", SeriesPlan, "sistema de prueba", "usuario de prueba"
    )
    assert isinstance(plan, SeriesPlan)


def test_generate_construye_mensajes_sistema_y_usuario():
    clientes = clientes_completos()
    gateway = LangChainStructuredGateway(clientes, RetryPolicy(1, 0.0))
    gateway.generate("planner", SeriesPlan, "PROMPT_SISTEMA", "PROMPT_USUARIO")
    mensajes = clientes["planner"].runnable.ultimo_mensajes
    assert isinstance(mensajes[0], SystemMessage) and mensajes[0].content == "PROMPT_SISTEMA"
    assert isinstance(mensajes[-1], HumanMessage) and mensajes[-1].content == "PROMPT_USUARIO"


def test_reintenta_y_recupera_tras_fallos_transitorios():
    clientes = clientes_completos(planner=2)
    gateway = LangChainStructuredGateway(clientes, RetryPolicy(3, 0.0))
    plan = gateway.generate("planner", SeriesPlan, "s", "u")
    assert isinstance(plan, SeriesPlan)
    assert clientes["planner"].runnable.invocaciones == 3


def test_agota_reintentos_y_falla_con_contexto():
    clientes = clientes_completos(planner=99)
    gateway = LangChainStructuredGateway(clientes, RetryPolicy(2, 0.0))
    with pytest.raises(RuntimeError, match="falló tras 2 intentos"):
        gateway.generate("planner", SeriesPlan, "s", "u")


def test_rol_desconocido_rechazado():
    gateway = LangChainStructuredGateway(clientes_completos(), RetryPolicy(1, 0.0))
    with pytest.raises(ValueError, match="Rol desconocido"):
        gateway.generate("traductor", SeriesPlan, "s", "u")


def test_esquema_que_no_coincide_con_el_rol_rechazado():
    gateway = LangChainStructuredGateway(clientes_completos(), RetryPolicy(1, 0.0))
    with pytest.raises(ValueError, match="no coinciden"):
        gateway.generate("planner", ContinuityDirectives, "s", "u")


def test_faltan_roles_por_cubrir_rechazado():
    clientes = clientes_completos()
    del clientes["critic"]
    with pytest.raises(ValueError, match="Faltan clientes"):
        LangChainStructuredGateway(clientes, RetryPolicy(1, 0.0))


def test_roles_desconocidos_en_el_wiring_rechazados():
    clientes = clientes_completos()
    clientes["productor"] = clientes["planner"]
    with pytest.raises(ValueError, match="roles desconocidos"):
        LangChainStructuredGateway(clientes, RetryPolicy(1, 0.0))


def test_resultado_de_tipo_inesperado_rechazado():
    class ChatCorrupto(FakeChat):
        def with_structured_output(self, schema):
            self.runnable = FakeRunnable("texto libre corrupto")
            return self.runnable

    clientes = clientes_completos()
    clientes["planner"] = ChatCorrupto(clientes["planner"]._resultado)
    gateway = LangChainStructuredGateway(clientes, RetryPolicy(1, 0.0))
    with pytest.raises(RuntimeError, match="corrupta"):
        gateway.generate("planner", SeriesPlan, "s", "u")


def test_politica_de_reintentos_invalida_rechazada():
    with pytest.raises(ValueError, match="max_retries"):
        RetryPolicy(max_retries=0)
    with pytest.raises(ValueError, match="backoff"):
        RetryPolicy(max_retries=1, backoff_seconds=-1)

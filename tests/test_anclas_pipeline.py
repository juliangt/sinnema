"""Pipeline con recursos ancla (spec-recursos-ancla §5, Fase 2).

Hito 1: siembra del catálogo fijo ``anclas`` en el estado (solo lockeadas,
opt-out por proyecto) y paridad: sin biblioteca lockeada la corrida es
idéntica a la de hoy.
"""
from __future__ import annotations

import copy

from sinnema.application.requests import build_initial_state
from sinnema.application.use_cases import GenerateSeriesUseCase
from sinnema.infrastructure.anclas import JsonAnchorStore

from conftest import gateway_con_serie, make_ancla, make_project, make_request

PROJECT_ID = "sinnema"


class AuditRegistrada:
    """Doble de AuditTrailPort que graba eventos para aserciones."""

    def __init__(self) -> None:
        self.eventos: list[str] = []
        self.pasos: list[str] = []

    def log_step(self, step, summary, artifact=None, details=None) -> None:
        self.pasos.append(step)

    def log_event(self, message: str) -> None:
        self.eventos.append(message)

    def log_failure(self, message: str) -> None:
        self.eventos.append(message)


def _almacen_con_lockeadas(root, project_id: str = PROJECT_ID) -> JsonAnchorStore:
    store = JsonAnchorStore(root=root)
    store.save(
        project_id,
        [
            make_ancla("protagonista", estado="lockeado"),
            make_ancla("la-nave", tipo="lugar", estado="borrador"),
        ],
    )
    return store


def _correr(use_case, request):
    final = None
    for final in use_case.stream(request):
        pass
    return final


# --------------------------- Hito 1: siembra ---------------------------


def test_estado_inicial_siembra_el_catalogo_de_anclas():
    lockeada = make_ancla("protagonista", estado="lockeado")
    request = make_request(num_chapters=1)
    estado = build_initial_state(request, initial_anclas=[lockeada])
    assert estado["anclas"] == [lockeada]


def test_estado_inicial_sin_anclas_queda_vacio():
    estado = build_initial_state(make_request(num_chapters=1))
    assert estado["anclas"] == []


def test_use_case_siembra_solo_las_anclas_lockeadas(tmp_path):
    store = _almacen_con_lockeadas(tmp_path)
    audit = AuditRegistrada()
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(num_chapters=1),
        make_project(),
        audit=audit,
        anchor_store=store,
    )
    final = _correr(use_case, make_request(num_chapters=1))

    ids = [a.ancla_id for a in final["anclas"]]
    assert ids == ["protagonista"]  # la borradora no participa
    assert all(a.estado == "lockeado" for a in final["anclas"])
    assert any("ancla" in e for e in audit.eventos)


def test_proyecto_con_anclas_false_ignora_la_biblioteca(tmp_path):
    store = _almacen_con_lockeadas(tmp_path)
    proyecto = make_project(anclas=False)
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(num_chapters=1), proyecto, anchor_store=store
    )
    final = _correr(use_case, make_request(num_chapters=1, project=proyecto))
    assert final["anclas"] == []


def test_use_case_sin_almacen_deja_el_estado_sin_anclas():
    use_case = GenerateSeriesUseCase(gateway_con_serie(num_chapters=1), make_project())
    final = _correr(use_case, make_request(num_chapters=1))
    assert final["anclas"] == []


# ------------------------- Hito 1: paridad base -------------------------


def test_sin_anclas_lockeadas_el_entregable_es_identico(tmp_path):
    """Paridad (spec-recursos-ancla §12): un proyecto sin anclas lockeadas
    produce el mismo entregable byte a byte (salvo timestamp), con o sin
    almacén inyectado y aunque la biblioteca tenga borradores."""
    gw = gateway_con_serie(num_chapters=1)
    sin_almacen = GenerateSeriesUseCase(copy.deepcopy(gw), make_project())
    con_almacen = GenerateSeriesUseCase(
        gw, make_project(), anchor_store=_almacen_con_lockeadas(tmp_path)
    )

    base = sin_almacen.execute(make_request(num_chapters=1)).model_dump(mode="json")
    con_biblioteca = con_almacen.execute(
        make_request(num_chapters=1)
    ).model_dump(mode="json")

    base.pop("generated_at")
    con_biblioteca.pop("generated_at")
    assert base == con_biblioteca

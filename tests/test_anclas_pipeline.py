"""Pipeline con recursos ancla (spec-recursos-ancla §5, Fase 2).

Hito 1: siembra del catálogo fijo ``anclas`` en el estado (solo lockeadas,
opt-out por proyecto) y paridad: sin biblioteca lockeada la corrida es
idéntica a la de hoy.
Hito 2: casting del capítulo (``AnclaDelCapitulo``), prompts de continuity y
guionista, validador ``validate_continuity_anchors`` y paridad de prompts.
"""
from __future__ import annotations

import copy

import pytest

from sinnema.application.prompts import continuity as continuity_prompts
from sinnema.application.prompts import director as director_prompts
from sinnema.application.prompts import scriptwriter as scriptwriter_prompts
from sinnema.application.requests import build_initial_state
from sinnema.application.use_cases import GenerateSeriesUseCase
from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.models import AnclaDelCapitulo, ReferenciaAncla, VisualAssetSpec
from sinnema.domain.services import (
    cobertura_casting,
    registrar_vigencia_de_anclas,
    validate_anchor_refs,
    validate_continuity_anchors,
)
from sinnema.infrastructure.anclas import JsonAnchorStore

from conftest import (
    FakeGateway,
    gateway_con_serie,
    make_adapted,
    make_ancla,
    make_audit,
    make_chapter,
    make_directives,
    make_draft,
    make_package,
    make_plan,
    make_project,
    make_request,
)

PROJECT_ID = "sinnema"
DESCRIPTOR = (
    "A friendly recurring character described with stable canonical traits "
    "for image models"
)


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


# ---------------- Hito 2: casting del capítulo y validador ----------------


def _directivas_con_casting(descriptor: str = DESCRIPTOR, ancla_id: str = "protagonista"):
    return make_directives().model_copy(
        update={
            "anclas_del_capitulo": [
                AnclaDelCapitulo(
                    ancla_id=ancla_id,
                    tipo="personaje",
                    descriptor=descriptor,
                    instrucciones="Viste su traje de laboratorio; llega con la energía alta.",
                )
            ]
        }
    )


def test_directivas_sin_casting_son_compatibles():
    directivas = make_directives()
    assert directivas.anclas_del_capitulo == []
    assert validate_continuity_anchors(directivas, []) is None


def test_validador_de_continuidad_acepta_casting_fiel_al_catalogo():
    directivas = _directivas_con_casting()
    catalogo = [make_ancla("protagonista", estado="lockeado")]
    validate_continuity_anchors(directivas, catalogo)


def test_validador_de_continuidad_rechaza_ancla_inexistente():
    directivas = _directivas_con_casting(ancla_id="fantasma")
    catalogo = [make_ancla("protagonista", estado="lockeado")]
    with pytest.raises(DomainValidationError, match="fantasma"):
        validate_continuity_anchors(directivas, catalogo)


def test_validador_de_continuidad_rechaza_ancla_no_lockeada():
    directivas = _directivas_con_casting()
    catalogo = [make_ancla("protagonista", estado="borrador")]
    with pytest.raises(DomainValidationError, match="lockeadas"):
        validate_continuity_anchors(directivas, catalogo)


def test_validador_de_continuidad_rechaza_descriptor_divergente():
    directivas = _directivas_con_casting(descriptor="A totally different visual description")
    catalogo = [make_ancla("protagonista", estado="lockeado")]
    with pytest.raises(DomainValidationError, match="diverge del"):
        validate_continuity_anchors(directivas, catalogo)


def test_validador_de_continuidad_rechaza_catalogo_vacio_con_casting():
    directivas = _directivas_con_casting()
    with pytest.raises(DomainValidationError, match="vacío"):
        validate_continuity_anchors(directivas, [])


def test_validador_de_continuidad_rechaza_tipo_divergente():
    directivas = _directivas_con_casting()
    directivas = directivas.model_copy(
        update={
            "anclas_del_capitulo": [
                directivas.anclas_del_capitulo[0].model_copy(update={"tipo": "lugar"})
            ]
        }
    )
    catalogo = [make_ancla("protagonista", estado="lockeado")]
    with pytest.raises(DomainValidationError, match="lugar"):
        validate_continuity_anchors(directivas, catalogo)


# ------------------- Hito 2: prompts con y sin biblioteca -------------------


class GatewayGrabador(FakeGateway):
    """FakeGateway que además graba los prompts (role, system, user)."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list = []

    def generate(self, role, schema, system_prompt, user_prompt):
        self.prompts.append((role, system_prompt, user_prompt))
        return super().generate(role, schema, system_prompt, user_prompt)


def test_system_prompt_de_continuidad_con_y_sin_biblioteca():
    proyecto = make_project()
    base = continuity_prompts.build_system_prompt(proyecto)
    con_anclas = continuity_prompts.build_system_prompt(
        proyecto, anclas=[make_ancla(estado="lockeado")]
    )

    assert "BIBLIOTECA DE ANCLAS" not in base
    assert "anclas_del_capitulo" not in base
    assert "BIBLIOTECA DE ANCLAS" in con_anclas
    assert "anclas_del_capitulo" in con_anclas
    assert "apariencia FIJA" in con_anclas
    assert con_anclas.startswith(base)  # la sección se agrega a la base común


def test_mensaje_de_continuidad_sin_anclas_es_idéntico_al_de_hoy():
    capitulo = make_chapter(1)
    sin_kwarg = continuity_prompts.build_user_message(
        chapter=capitulo,
        previous_chapter=None,
        lore_entries=[],
        recurring_elements=["mascota Roby"],
    )
    con_lista_vacia = continuity_prompts.build_user_message(
        chapter=capitulo,
        previous_chapter=None,
        lore_entries=[],
        recurring_elements=["mascota Roby"],
        anclas=[],
    )
    assert sin_kwarg == con_lista_vacia
    assert "<biblioteca_de_anclas>" not in sin_kwarg


def test_mensaje_de_continuidad_incluye_biblioteca_lockeada():
    mensaje = continuity_prompts.build_user_message(
        chapter=make_chapter(1),
        previous_chapter=None,
        lore_entries=[],
        recurring_elements=[],
        anclas=[make_ancla("protagonista", estado="lockeado")],
    )
    assert "<biblioteca_de_anclas>" in mensaje
    assert "[personaje] protagonista" in mensaje
    assert DESCRIPTOR in mensaje
    assert mensaje.count("<biblioteca_de_anclas>") == mensaje.count(
        "</biblioteca_de_anclas>"
    )


def test_mensaje_del_guionista_incluye_el_casting_cuando_hay():
    proyecto = make_project()
    capitulo = make_chapter(1)
    sin_casting = scriptwriter_prompts.build_user_message(
        proyecto, chapter=capitulo, directives=make_directives()
    )
    con_casting = scriptwriter_prompts.build_user_message(
        proyecto, chapter=capitulo, directives=_directivas_con_casting()
    )

    assert "casting_del_capitulo" not in sin_casting
    assert "casting_del_capitulo" in con_casting
    assert "protagonista [personaje]" in con_casting
    assert "traje de laboratorio" in con_casting
    assert DESCRIPTOR in con_casting
    assert con_casting.count("<directivas_de_continuidad>") == con_casting.count(
        "</directivas_de_continuidad>"
    )


def test_paridad_de_prompts_sin_anclas_lockeadas(tmp_path):
    """Sin biblioteca lockeada, TODOS los prompts de la corrida son byte a
    byte los de hoy (biblioteca ausente o con solo borradores)."""
    gw_sin = GatewayGrabador()
    gw_con = GatewayGrabador()
    plan = make_plan(1)
    draft = make_draft("ch-01")
    for gw in (gw_sin, gw_con):
        gw.add("planner", [plan])
        gw.add("continuity", [make_directives()])
        gw.add("scriptwriter", [draft])
        gw.add("adapter", [make_adapted(draft)])
        gw.add("critic", [make_audit(approved=True)])
        gw.add("technical_director", [make_package(draft)])

    store_borradores = JsonAnchorStore(root=tmp_path / "solo-borradores")
    store_borradores.save(
        PROJECT_ID, [make_ancla("la-nave", tipo="lugar", estado="borrador")]
    )

    use_case_sin = GenerateSeriesUseCase(gw_sin, make_project())
    use_case_con = GenerateSeriesUseCase(
        gw_con, make_project(), anchor_store=store_borradores
    )
    # La biblioteca del caso "con" tiene SOLO borradores: nada lockeado.
    assert use_case_con._anclas_lockeadas == []

    _correr(use_case_sin, make_request(num_chapters=1))
    _correr(use_case_con, make_request(num_chapters=1))

    assert len(gw_sin.prompts) == len(gw_con.prompts) > 0
    for (rol_sin, sys_sin, usr_sin), (rol_con, sys_con, usr_con) in zip(
        gw_sin.prompts, gw_con.prompts
    ):
        assert rol_sin == rol_con
        assert sys_sin == sys_con, f"system prompt divergente en {rol_sin}"
        assert usr_sin == usr_con, f"mensaje divergente en {rol_sin}"


# ----------------- Hito 2: integración del validador en el grafo -----------------


def _gateway_de_un_capitulo(directivas):
    gw = FakeGateway()
    plan = make_plan(1)
    draft = make_draft("ch-01")
    gw.add("planner", [plan])
    gw.add("continuity", [directivas])
    gw.add("scriptwriter", [draft])
    gw.add("adapter", [make_adapted(draft)])
    gw.add("critic", [make_audit(approved=True)])
    gw.add("technical_director", [make_package(draft)])
    return gw


def test_grafo_acepta_casting_fiel_y_propaga_directivas_al_guionista(tmp_path):
    store = JsonAnchorStore(root=tmp_path)
    store.save(PROJECT_ID, [make_ancla("protagonista", estado="lockeado")])
    use_case = GenerateSeriesUseCase(
        _gateway_de_un_capitulo(_directivas_con_casting()),
        make_project(),
        anchor_store=store,
    )
    final = _correr(use_case, make_request(num_chapters=1))
    assert len(final["completed_episodes"]) == 1


def test_grafo_rechaza_casting_con_ancla_alucinada(tmp_path):
    store = JsonAnchorStore(root=tmp_path)
    store.save(PROJECT_ID, [make_ancla("protagonista", estado="lockeado")])
    use_case = GenerateSeriesUseCase(
        _gateway_de_un_capitulo(_directivas_con_casting(ancla_id="fantasma")),
        make_project(),
        anchor_store=store,
    )
    with pytest.raises(DomainValidationError, match="fantasma"):
        _correr(use_case, make_request(num_chapters=1))


def test_grafo_rechaza_casting_sin_biblioteca_aun_con_rol_activo():
    """Sin catálogo sembrado, cualquier casting es una alucinación: rechazo."""
    use_case = GenerateSeriesUseCase(
        _gateway_de_un_capitulo(_directivas_con_casting()), make_project()
    )
    with pytest.raises(DomainValidationError, match="vacío"):
        _correr(use_case, make_request(num_chapters=1))


# ------------- Hito 3: specs con referencias y dirección técnica -------------
# (los tests de Hito 1/2 se conservan arriba; esta sección cubre §5.3/§5.4)


def _paquete_con_refs(draft, refs_por_escena):
    """Paquete válido del borrador con referencias de anclas por escena."""
    paquete = make_package(draft)
    specs = [
        spec.model_copy(update={"anclas": refs_por_escena.get(spec.scene_number, [])})
        for spec in paquete.visual_specs
    ]
    return paquete.model_copy(update={"visual_specs": specs})


def _gateway_de_un_capitulo_con_paquete(directivas, paquete):
    gw = FakeGateway()
    plan = make_plan(1)
    draft = make_draft("ch-01")
    gw.add("planner", [plan])
    gw.add("continuity", [directivas])
    gw.add("scriptwriter", [draft])
    gw.add("adapter", [make_adapted(draft)])
    gw.add("critic", [make_audit(approved=True)])
    gw.add("technical_director", [paquete])
    return gw


def test_spec_sin_anclas_es_compatible_y_las_conserva_si_hay():
    spec = VisualAssetSpec(
        scene_number=1,
        image_prompt=(
            "A clean isometric 3D render of a friendly robot teacher in a neon lab"
        ),
        negative_prompt="watermark, blurry",
        composition="Vertical centered framing",
        motion_direction="Slow dolly in toward the subject",
        style_tags=["isometric", "neon", "vertical"],
    )
    assert spec.anclas == []
    con_refs = spec.model_copy(
        update={"anclas": [ReferenciaAncla(ancla_id="protagonista")]}
    )
    assert con_refs.anclas[0].ancla_id == "protagonista"
    assert con_refs.anclas[0].roles == []  # vacío = batería completa del tipo


def test_validador_de_refs_acepta_referencias_lockeadas():
    paquete = make_package(make_draft("ch-01"))
    validate_anchor_refs(paquete, [make_ancla("protagonista", estado="lockeado")])


def test_validador_de_refs_rechaza_ancla_inexistente():
    draft = make_draft("ch-01")
    paquete = _paquete_con_refs(
        draft, {1: [ReferenciaAncla(ancla_id="fantasma", roles=["hero_portrait"])]}
    )
    with pytest.raises(DomainValidationError, match="fantasma"):
        validate_anchor_refs(paquete, [make_ancla("protagonista", estado="lockeado")])


def test_validador_de_refs_rechaza_ancla_no_lockeada():
    draft = make_draft("ch-01")
    paquete = _paquete_con_refs(draft, {2: [ReferenciaAncla(ancla_id="protagonista")]})
    with pytest.raises(DomainValidationError, match="lockeadas"):
        validate_anchor_refs(paquete, [make_ancla("protagonista", estado="borrador")])


def test_validador_de_refs_rechaza_sin_catalogo():
    paquete = _paquete_con_refs(
        make_draft("ch-01"), {3: [ReferenciaAncla(ancla_id="protagonista")]}
    )
    with pytest.raises(DomainValidationError, match="vacío"):
        validate_anchor_refs(paquete, [])


def test_cobertura_casting_reporta_solo_las_faltantes():
    draft = make_draft("ch-01")
    paquete = _paquete_con_refs(
        draft,
        {1: [ReferenciaAncla(ancla_id="protagonista")], 2: [ReferenciaAncla(ancla_id="la-nave")]},
    )
    casting = [
        AnclaDelCapitulo(
            ancla_id="protagonista",
            tipo="personaje",
            descriptor=DESCRIPTOR,
            instrucciones="Protagoniza todas las escenas.",
        ),
        AnclaDelCapitulo(
            ancla_id="la-nave",
            tipo="lugar",
            descriptor="A place descriptor",
            instrucciones="Escenario del capítulo.",
        ),
        AnclaDelCapitulo(
            ancla_id="mascota",
            tipo="objeto",
            descriptor="A prop descriptor",
            instrucciones="Aparece en el cierre.",
        ),
    ]
    faltantes = cobertura_casting(casting, paquete)
    assert faltantes == ["mascota"]
    assert cobertura_casting(casting, None) == [
        "protagonista",
        "la-nave",
        "mascota",
    ]


def test_vigencia_primer_y_ultimo_capitulo():
    catalogo = [
        make_ancla("protagonista", estado="lockeado"),
        make_ancla("la-nave", tipo="lugar", estado="lockeado"),
    ]
    # Capítulo 1: el protagonista se usa; el lugar no.
    actualizado = registrar_vigencia_de_anclas(catalogo, ["protagonista"], "ch-01")
    assert actualizado is not None
    por_id = {a.ancla_id: a for a in actualizado}
    assert por_id["protagonista"].chapter_first_seen == "ch-01"
    assert por_id["protagonista"].chapter_last_seen == "ch-01"
    assert por_id["la-nave"].chapter_first_seen is None

    # Capítulo 2: solo actualiza last_seen; first_seen se conserva.
    actualizado2 = registrar_vigencia_de_anclas(actualizado, ["protagonista"], "ch-02")
    por_id2 = {a.ancla_id: a for a in actualizado2}
    assert por_id2["protagonista"].chapter_first_seen == "ch-01"
    assert por_id2["protagonista"].chapter_last_seen == "ch-02"

    # Re-estampar el mismo capítulo no cambia nada: None (sin escritura).
    assert registrar_vigencia_de_anclas(actualizado2, ["protagonista"], "ch-02") is None
    # Sin usadas: None.
    assert registrar_vigencia_de_anclas(catalogo, [], "ch-01") is None


def test_prompts_del_director_con_y_sin_biblioteca():
    proyecto = make_project()
    borrador = make_draft("ch-01")
    adaptado = make_adapted(borrador)
    base = director_prompts.build_user_message(
        proyecto,
        chapter=make_chapter(1),
        draft=borrador,
        adapted=adaptado,
        recurring_elements=["mascota Roby"],
    )
    con_anclas = director_prompts.build_user_message(
        proyecto,
        chapter=make_chapter(1),
        draft=borrador,
        adapted=adaptado,
        recurring_elements=["mascota Roby"],
        anclas=[make_ancla("protagonista", estado="lockeado")],
        casting=_directivas_con_casting().anclas_del_capitulo,
    )

    assert base == director_prompts.build_user_message(
        proyecto,
        chapter=make_chapter(1),
        draft=borrador,
        adapted=adaptado,
        recurring_elements=["mascota Roby"],
        anclas=[],
        casting=[],
    )
    assert "<biblioteca_de_anclas>" not in base
    assert "<casting_del_capitulo>" not in base
    assert "<biblioteca_de_anclas>" in con_anclas
    assert "[personaje] protagonista" in con_anclas
    assert DESCRIPTOR in con_anclas
    assert "<casting_del_capitulo>" in con_anclas
    assert "traje de laboratorio" in con_anclas
    for tag in ("encargo_tecnico", "biblioteca_de_anclas", "casting_del_capitulo"):
        assert con_anclas.count(f"<{tag}>") == con_anclas.count(f"</{tag}>")


def test_system_prompt_del_director_gana_reglas_solo_con_biblioteca():
    proyecto = make_project()
    base = director_prompts.build_system_prompt(proyecto)
    con_anclas = director_prompts.build_system_prompt(
        proyecto, anclas=[make_ancla(estado="lockeado")]
    )
    assert "BIBLIOTECA DE ANCLAS" not in base
    assert "ancla_id" not in base
    assert "BIBLIOTECA DE ANCLAS" in con_anclas
    assert "DEBE declararse en `anclas`" in con_anclas
    assert "thumbnail_prompt" in con_anclas
    assert con_anclas.startswith(base)


# ---------------- Hito 3: integración en el grafo y persistencia ----------------


def test_grafo_acepta_refs_validas_y_el_paquete_viaja_intacto_al_episodio(tmp_path):
    store = JsonAnchorStore(root=tmp_path)
    store.save(
        PROJECT_ID,
        [
            make_ancla("protagonista", estado="lockeado"),
            make_ancla("la-nave", tipo="lugar", estado="lockeado"),
        ],
    )
    draft = make_draft("ch-01")
    refs = {
        1: [
            ReferenciaAncla(ancla_id="protagonista", roles=["hero_portrait"]),
            ReferenciaAncla(ancla_id="la-nave"),
        ],
        3: [ReferenciaAncla(ancla_id="protagonista")],
    }
    use_case = GenerateSeriesUseCase(
        _gateway_de_un_capitulo_con_paquete(
            _directivas_con_casting(), _paquete_con_refs(draft, refs)
        ),
        make_project(),
        anchor_store=store,
    )
    final = _correr(use_case, make_request(num_chapters=1))

    episodio = final["completed_episodes"][0]
    # El paquete técnico del episodio conserva las referencias intactas...
    specs = {s.scene_number: s for s in episodio.technical.visual_specs}
    assert [r.ancla_id for r in specs[1].anclas] == ["protagonista", "la-nave"]
    assert specs[1].anclas[0].roles == ["hero_portrait"]
    assert specs[3].anclas[0].roles == []
    # ...y también viajan en el adjunto serializado del director.
    adjunto_tecnico = next(
        a for a in episodio.adjuntos if a.rol == "technical_director"
    )
    serializadas = adjunto_tecnico.artefacto["visual_specs"]
    assert serializadas[0]["anclas"][0]["ancla_id"] == "protagonista"
    # El catálogo del estado queda vigente-estampado por el commit.
    por_id = {a.ancla_id: a for a in final["anclas"]}
    assert por_id["protagonista"].chapter_first_seen == "ch-01"
    assert por_id["protagonista"].chapter_last_seen == "ch-01"
    assert por_id["la-nave"].chapter_first_seen == "ch-01"


def test_grafo_rechaza_paquete_con_referencia_alucinada(tmp_path):
    store = JsonAnchorStore(root=tmp_path)
    store.save(PROJECT_ID, [make_ancla("protagonista", estado="lockeado")])
    paquete = _paquete_con_refs(
        make_draft("ch-01"), {1: [ReferenciaAncla(ancla_id="fantasma")]}
    )
    use_case = GenerateSeriesUseCase(
        _gateway_de_un_capitulo_con_paquete(_directivas_con_casting(), paquete),
        make_project(),
        anchor_store=store,
    )
    with pytest.raises(DomainValidationError, match="fantasma"):
        _correr(use_case, make_request(num_chapters=1))


def test_cobertura_blanda_queda_en_auditoria_sin_rechazar(tmp_path):
    store = JsonAnchorStore(root=tmp_path)
    store.save(PROJECT_ID, [make_ancla("protagonista", estado="lockeado")])
    audit = AuditRegistrada()
    # El paquete NO referencia al protagonista del casting: hallazgo, no fallo.
    use_case = GenerateSeriesUseCase(
        _gateway_de_un_capitulo_con_paquete(
            _directivas_con_casting(), make_package(make_draft("ch-01"))
        ),
        make_project(),
        audit=audit,
        anchor_store=store,
    )
    final = _correr(use_case, make_request(num_chapters=1))
    assert len(final["completed_episodes"]) == 1
    hallazgos = [e for e in audit.eventos if "Cobertura de anclas" in e]
    assert len(hallazgos) == 1
    assert "protagonista" in hallazgos[0]


def test_cobertura_completa_no_deja_hallazgo(tmp_path):
    store = JsonAnchorStore(root=tmp_path)
    store.save(PROJECT_ID, [make_ancla("protagonista", estado="lockeado")])
    audit = AuditRegistrada()
    paquete = _paquete_con_refs(
        make_draft("ch-01"), {1: [ReferenciaAncla(ancla_id="protagonista")]}
    )
    use_case = GenerateSeriesUseCase(
        _gateway_de_un_capitulo_con_paquete(_directivas_con_casting(), paquete),
        make_project(),
        audit=audit,
        anchor_store=store,
    )
    _correr(use_case, make_request(num_chapters=1))
    assert [e for e in audit.eventos if "Cobertura de anclas" in e] == []


def test_save_anclas_persiste_la_vigencia_y_no_escribe_si_no_hubo_cambios(tmp_path):
    store = JsonAnchorStore(root=tmp_path)
    store.save(PROJECT_ID, [make_ancla("protagonista", estado="lockeado")])
    paquete = _paquete_con_refs(
        make_draft("ch-01"), {2: [ReferenciaAncla(ancla_id="protagonista")]}
    )
    use_case = GenerateSeriesUseCase(
        _gateway_de_un_capitulo_con_paquete(
            _directivas_con_casting(), paquete
        ),
        make_project(),
        anchor_store=store,
    )
    use_case.execute(make_request(num_chapters=1))

    persistida = {a.ancla_id: a for a in store.load(PROJECT_ID)}
    assert persistida["protagonista"].chapter_first_seen == "ch-01"
    assert persistida["protagonista"].chapter_last_seen == "ch-01"
    version = persistida["protagonista"].version

    # Segunda corrida SIN referencias: sin anclas usadas → sin escritura.
    use_case_sin_uso = GenerateSeriesUseCase(
        _gateway_de_un_capitulo_con_paquete(
            _directivas_con_casting(), make_package(make_draft("ch-01"))
        ),
        make_project(),
        anchor_store=store,
    )
    use_case_sin_uso.execute(make_request(num_chapters=1))
    persistida2 = {a.ancla_id: a for a in store.load(PROJECT_ID)}
    assert persistida2["protagonista"].chapter_last_seen == "ch-01"
    assert persistida2["protagonista"].version == version


def test_save_anclas_sin_catalogo_no_escribe_nada(tmp_path):
    store = JsonAnchorStore(root=tmp_path)
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(num_chapters=1), make_project(), anchor_store=store
    )
    use_case.execute(make_request(num_chapters=1))
    assert store.load(PROJECT_ID) == []
    assert not (tmp_path / PROJECT_ID / "anclas.json").exists()

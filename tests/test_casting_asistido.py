"""Casting asistido (Fase 5, spec-recursos-ancla §8.2).

Cubren: personajes recurrentes del lore sin ancla → propuesta de ancla en
estado ``propuesto`` fusionada con la biblioteca persistida (sin pisar nada),
términos no recurrentes o ya cubiertos por una ancla → nada, y el hero
portrait best-effort con el puerto de media inyectado (fallos no tumban).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sinnema.application.ports import DependenciasMedia
from sinnema.application.projects import MediaConfig
from sinnema.application.use_cases import GenerateSeriesUseCase
from sinnema.domain.models import (
    LoreEntry,
    MediaCrudo,
    ManifestDeGeneracion,
)
from sinnema.domain.services import proponer_casting, slug_de_termino
from sinnema.infrastructure.anclas import JsonAnchorStore
from sinnema.infrastructure.lore import JsonLoreStore
from sinnema.infrastructure.media import AlmacenMedia

from conftest import (
    FakeGateway,
    make_adapted,
    make_audit,
    make_ancla,
    make_directives,
    make_draft,
    make_imagen_ancla,
    make_package,
    make_plan,
    make_project,
    make_request,
)

PROJECT_ID = "sinnema"


# ------------------------------ dobles de prueba ------------------------------


class PuertoRetratoFalso:
    """Doble de ``MediaGenerationPort`` para el hero portrait de las propuestas."""

    def __init__(self, fallar: bool = False) -> None:
        self.pedidos = []
        self.fallar = fallar

    def generar_keyframe(self, pedido, catalogo):
        self.pedidos.append(pedido)
        if self.fallar:
            raise RuntimeError("proveedor de imagen sin claves")
        return MediaCrudo(
            datos=b"retrato-sintetico",
            formato="png",
            manifest=ManifestDeGeneracion(
                proveedor="falso",
                modelo="falso-1",
                seed=None,
                prompt_final=pedido.prompt_final,
                anclas_usadas=[],
                parametros={},
                id_externo="hero-1",
                creado_en=datetime(2026, 9, 12, tzinfo=timezone.utc),
            ),
        )


def _lore_personaje(term: str = "nita", chapter_id: str = "ch-01") -> LoreEntry:
    return LoreEntry(
        term=term,
        definition="Definición breve del personaje recurrente.",
        chapter_id=chapter_id,
        first_seen_title="Capítulo de origen",
        category="personaje",
    )


def _gateway_con_personaje(termino: str = "nita", capitulo_con_termino=None):
    """Serie de 2 capítulos cuyo plan cita (o no) el término en key_concepts.

    ``capitulo_con_termino``: None = en TODOS (recurrente); un índice = solo
    ese capítulo; -1 = en ninguno (el término solo vive en el lore sembrado).
    """
    plan = make_plan(2)
    capitulos = []
    for indice, capitulo in enumerate(plan.chapters):
        conceptos = list(capitulo.key_concepts)
        if capitulo_con_termino is None or capitulo_con_termino == indice:
            conceptos = [termino, conceptos[0]]
        capitulos.append(capitulo.model_copy(update={"key_concepts": conceptos}))
    gw = FakeGateway()
    gw.add("planner", [plan.model_copy(update={"chapters": capitulos})])
    for i, capitulo in enumerate(plan.chapters):
        draft = make_draft(capitulo.chapter_id)
        gw.add("continuity", [make_directives(new_terms=(f"concepto nuevo {i + 1}",))])
        gw.add("scriptwriter", [draft])
        gw.add("adapter", [make_adapted(draft)])
        gw.add("critic", [make_audit(approved=True)])
        gw.add("technical_director", [make_package(draft)])
    return gw


def _use_case(gw, tmp_path, proyecto=None, media=None, lore_inicial=None):
    lore_store = JsonLoreStore(root=tmp_path / "continuidad")
    if lore_inicial:
        lore_store.save(PROJECT_ID, lore_inicial)
    anchor_store = JsonAnchorStore(root=tmp_path / "anclas")
    proyecto = proyecto or make_project()
    return (
        GenerateSeriesUseCase(
            gw, proyecto,
            lore_store=lore_store, anchor_store=anchor_store, media=media,
        ),
        anchor_store,
    )


# ---------------------------- servicio puro ----------------------------


def test_slug_de_termino_es_determinista():
    assert slug_de_termino("Nita la guía") == "nita-la-guia"
    assert slug_de_termino("  Doña Rosa!  ") == "dona-rosa"
    assert slug_de_termino("!!!") is None
    assert slug_de_termino("x" * 61) is None


def test_proponer_casting_solo_con_recurrencia_y_sin_ancla():
    entradas = [_lore_personaje("nita", "ch-01")]
    capitulos = list(make_plan(2).chapters)
    # Presente en un solo capítulo (el entry ch-01 + plan sin citas): nada.
    assert proponer_casting(entradas, capitulos, []) == []
    # Citado en los dos capítulos del plan: propuesta en estado propuesto.
    citados = [
        c.model_copy(update={"key_concepts": ["nita", c.key_concepts[0]]})
        for c in capitulos
    ]
    propuestas = proponer_casting(entradas, citados, [])
    assert len(propuestas) == 1
    propuesta = propuestas[0]
    assert propuesta.ancla_id == "nita"
    assert propuesta.estado == "propuesto"
    assert propuesta.descripcion_canonica.startswith(
        "Casting proposal for the recurring character nita"
    )
    assert len(propuesta.descripcion_canonica) >= 40
    assert propuesta.chapter_first_seen == "ch-01"
    assert propuesta.chapter_last_seen == "ch-02"


# --------------------- consolidación de fin de corrida ---------------------


def test_personaje_recurrente_sin_ancla_genera_propuesta(tmp_path):
    use_case, anchor_store = _use_case(
        _gateway_con_personaje(), tmp_path,
        lore_inicial=[_lore_personaje()],
    )
    use_case.execute(make_request(num_chapters=2))

    biblioteca = anchor_store.load(PROJECT_ID)
    assert [a.ancla_id for a in biblioteca] == ["nita"]
    propuesta = biblioteca[0]
    assert propuesta.tipo == "personaje"
    assert propuesta.estado == "propuesto"  # el lock sigue siendo humano
    assert propuesta.nombre == "nita"
    assert len(propuesta.descripcion_canonica) >= 40
    assert propuesta.bateria == []  # sin media: la propuesta nace solo con ficha
    assert propuesta.version == 1


def test_termino_no_recurrente_no_genera_propuesta(tmp_path):
    use_case, anchor_store = _use_case(
        # El término solo vive en el lore sembrado con chapter ch-01: el plan
        # no lo cita en ningún capítulo → presente en un solo episodio.
        _gateway_con_personaje(capitulo_con_termino=-1), tmp_path,
        lore_inicial=[_lore_personaje()],
    )
    use_case.execute(make_request(num_chapters=2))
    assert anchor_store.load(PROJECT_ID) == []


def test_termino_con_ancla_ya_o_enlazado_no_genera_propuesta(tmp_path):
    # Con ancla por nombre (casefold): la biblioteca ya cubre al personaje.
    anchor_store = JsonAnchorStore(root=tmp_path / "anclas")
    anchor_store.save(PROJECT_ID, [
        make_ancla("protagonista", estado="borrador", nombre="Nita"),
    ])
    # Con ancla_id seteado (enlazado por la Fase 2): tampoco propone.
    entradas = [
        _lore_personaje("roby", "ch-01").model_copy(update={"ancla_id": "protagonista"}),
    ]
    use_case = GenerateSeriesUseCase(
        _gateway_con_personaje(capitulo_con_termino=-1), make_project(),
        anchor_store=anchor_store,
    )
    estado = None
    for estado in use_case.stream(make_request(num_chapters=2)):
        pass
    use_case.save_lore(estado)
    use_case.save_casting(estado)

    biblioteca = anchor_store.load(PROJECT_ID)
    assert [a.ancla_id for a in biblioteca] == ["protagonista"]
    assert biblioteca[0].estado == "borrador"  # nada pisado


def test_propuesta_existente_no_se_pisa(tmp_path):
    anchor_store = JsonAnchorStore(root=tmp_path / "anclas")
    anchor_store.guardar_imagen(PROJECT_ID, "nita", "hero_portrait_1.png", b"previo")
    original = make_ancla(
        "nita", estado="propuesto",
        descripcion_canonica=(
            "Human drafted descriptor that the pipeline must never overwrite "
            "with its own text"
        ),
    )
    original = original.model_copy(update={
        "bateria": [make_imagen_ancla(rol="hero_portrait", archivo="hero_portrait_1.png")],
    })
    anchor_store.save(PROJECT_ID, [original])

    use_case, anchor_store = _use_case(
        _gateway_con_personaje(), tmp_path,
        lore_inicial=[_lore_personaje()],
    )
    use_case.execute(make_request(num_chapters=2))

    biblioteca = anchor_store.load(PROJECT_ID)
    assert [a.ancla_id for a in biblioteca] == ["nita"]
    assert biblioteca[0].descripcion_canonica == original.descripcion_canonica
    assert biblioteca[0].bateria == original.bateria
    assert biblioteca[0].version == 1


# --------------------------- hero portrait (media) ---------------------------


def test_con_media_la_propuesta_nace_con_hero_portrait(tmp_path):
    proyecto = make_project(media=MediaConfig(keyframes=True))
    puerto = PuertoRetratoFalso()
    media = DependenciasMedia(
        puerto=puerto,
        almacen=AlmacenMedia(root=tmp_path / "media"),
        proveedor="falso",
    )
    use_case, anchor_store = _use_case(
        _gateway_con_personaje(), tmp_path,
        proyecto=proyecto, media=media,
        lore_inicial=[_lore_personaje()],
    )
    use_case.execute(make_request(num_chapters=2, project=proyecto))

    propuesta = anchor_store.load(PROJECT_ID)[0]
    assert len(propuesta.bateria) == 1
    retrato = propuesta.bateria[0]
    assert retrato.rol == "hero_portrait"
    assert retrato.origen == "generada"
    assert retrato.archivo == "hero_portrait_1.png"
    assert retrato.manifest.proveedor == "falso"
    assert retrato.manifest.prompt_final == propuesta.descripcion_canonica
    # Copia en la carpeta de batería del ancla (convención del upload).
    assert (
        tmp_path / "anclas" / PROJECT_ID / "nita" / "hero_portrait_1.png"
    ).read_bytes() == b"retrato-sintetico"
    # Pedido mínimo: prompt = descriptor, sin anclas.
    pedido = puerto.pedidos[-1]
    assert pedido.prompt_final == propuesta.descripcion_canonica
    assert pedido.anclas == []


def test_fallo_del_media_deja_la_propuesta_sin_bateria_y_la_corrida_sigue(tmp_path):
    proyecto = make_project(media=MediaConfig(keyframes=True))
    media = DependenciasMedia(
        puerto=PuertoRetratoFalso(fallar=True),
        almacen=AlmacenMedia(root=tmp_path / "media"),
        proveedor="falso",
    )
    use_case, anchor_store = _use_case(
        _gateway_con_personaje(), tmp_path,
        proyecto=proyecto, media=media,
        lore_inicial=[_lore_personaje()],
    )
    entregable = use_case.execute(make_request(num_chapters=2, project=proyecto))

    assert len(entregable.episodes) == 2  # la corrida sigue
    propuesta = anchor_store.load(PROJECT_ID)[0]
    assert propuesta.estado == "propuesto"
    assert propuesta.bateria == []  # sin retrato, con descriptor

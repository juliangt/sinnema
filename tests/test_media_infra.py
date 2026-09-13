"""Infraestructura de media de la Fase 3 (spec-recursos-ancla §6/§11.3/§12).

Tests SIN red, claves ni SDKs: los adaptadores se ejercitan con SDKs falsos
inyectados (``_importar_sdk``), el resolver con catálogos de ``conftest`` y
los reintentos con operaciones falsas. Cubren: contratos del puerto, orden
identidad-primero del resolver, expansión de roles, máximos por proveedor
(como error de wiring LOCAL), re-verificación de lock, dedup, degradación
elegante sin clave/SDK, reintentos de transporte, manifest completo y
almacén de keyframes (naming + anti-traversal).
"""
from __future__ import annotations

import base64
import json

import pytest

from sinnema.domain.models import (
    ManifestDeGeneracion,
    MediaCrudo,
    PedidoKeyframe,
    ReferenciaAncla,
)
from sinnema.infrastructure.media import (
    AdaptadorGeminiImage,
    AdaptadorOpenAIImage,
    AlmacenMedia,
    PROVEEDORES_DE_IMAGEN,
    PoliticaReintentos,
    con_reintentos,
    construir_puerto_de_media,
)
from sinnema.infrastructure.media.resolver import ResolverDeBateria

from conftest import make_ancla

PROJECT_ID = "sinnema"


def _pedido(anclas=None, **overrides) -> PedidoKeyframe:
    datos = dict(
        scene_number=1,
        chapter_id="ch-01",
        prompt_final=(
            "A clean isometric 3D render of the recurring character teaching "
            "in a neon lab, soft studio lighting"
        ),
        negative_prompt="watermark, blurry",
        aspect_ratio="9:16",
        anclas=anclas or [],
    )
    datos.update(overrides)
    return PedidoKeyframe(**datos)


def _cargador(registro=None):
    def cargar(project_id, ancla_id, archivo):
        if registro is not None:
            registro.append((project_id, ancla_id, archivo))
        return b"bytes-de-" + ancla_id.encode() + b"-" + archivo.encode()

    return cargar


# ================================ contratos ================================


def test_media_crudo_y_manifest_son_contratos_validos():
    manifest = ManifestDeGeneracion(
        proveedor="gemini",
        modelo="gemini-2.5-flash-image",
        seed=None,
        prompt_final="A clean isometric render of the mascot",
        anclas_usadas=[("protagonista", 1, "hero_portrait")],
        parametros={"aspect_ratio": "9:16"},
        id_externo="resp-1",
        creado_en="2026-09-12T00:00:00Z",
    )
    crudo = MediaCrudo(datos=b"img", formato="png", manifest=manifest)
    assert crudo.ultimo_frame is None  # sin encadenado no hay frame expuesto
    # MediaGenerado nace con qa=None (Fase 4 lo llena).
    from sinnema.domain.models import MediaGenerado

    generado = MediaGenerado(archivo="sinnema/ch-01/escena_1.png", manifest=manifest)
    assert generado.qa == []  # Fase 4: sin QA corrido, la lista nace vacía
    serializado = json.dumps(generado.model_dump(mode="json"))  # viaja en adjunto
    assert "escena_1.png" in serializado


# ================================ resolver ================================


def _resolver(limite_consistencia=4, limite_estilo=3, limite_total=None, registro=None):
    return ResolverDeBateria(
        PROJECT_ID,
        _cargador(registro),
        maximo_consistencia=limite_consistencia,
        maximo_estilo=limite_estilo,
        maximo_total=limite_total,
    )


CATALOGO = lambda: [  # noqa: E731
    make_ancla("protagonista", estado="lockeado"),
    make_ancla("la-nave", tipo="lugar", estado="lockeado"),
    make_ancla("look", tipo="estilo", estado="lockeado"),
]


def test_resolver_ordena_identidad_primero_y_expande_roles_vacios():
    """§3.1: el pedido declara estilo primero; el resolver reordena identidad
    (personaje) → lugar → estilo y expande roles [] a la batería completa."""
    pedido = _pedido(
        anclas=[
            ReferenciaAncla(ancla_id="look"),
            ReferenciaAncla(ancla_id="la-nave"),
            ReferenciaAncla(ancla_id="protagonista", roles=["hero_portrait"]),
        ]
    )
    resueltas = _resolver().resolver(pedido, CATALOGO())

    orden = [(r.ancla_id, r.rol) for r in resueltas]
    assert orden == [
        ("protagonista", "hero_portrait"),
        ("la-nave", "establishing_shot"),
        ("look", "style_reference"),
    ]
    # El manifest estampa (ancla_id, version, rol) EN ORDEN.
    assert resueltas[0].triple == ("protagonista", 1, "hero_portrait")
    assert all(r.datos.startswith(b"bytes-de-") for r in resueltas)


def test_resolver_con_roles_acotados_solo_envia_esos():
    pedido = _pedido(anclas=[ReferenciaAncla(ancla_id="protagonista", roles=["hero_portrait"])])
    resueltas = _resolver().resolver(pedido, CATALOGO())
    assert [(r.ancla_id, r.rol) for r in resueltas] == [("protagonista", "hero_portrait")]


def test_resolver_deduplica_imagenes_repetidas():
    pedido = _pedido(
        anclas=[
            ReferenciaAncla(ancla_id="protagonista", roles=["hero_portrait"]),
            ReferenciaAncla(ancla_id="protagonista"),
        ]
    )
    resueltas = _resolver().resolver(pedido, CATALOGO())
    clave = [(r.ancla_id, r.rol) for r in resueltas]
    assert len(clave) == len(set(clave))
    assert clave.count(("protagonista", "hero_portrait")) == 1


def test_resolver_rechaza_ancla_ausente_o_no_lockeada_como_wiring_local():
    pedido = _pedido(anclas=[ReferenciaAncla(ancla_id="fantasma")])
    with pytest.raises(ValueError, match="Wiring de media"):
        _resolver().resolver(pedido, CATALOGO())

    pedido_borrador = _pedido(anclas=[ReferenciaAncla(ancla_id="borrador")])
    catalogo = [make_ancla("borrador", estado="borrador")]
    with pytest.raises(ValueError, match="lockeadas"):
        _resolver().resolver(pedido_borrador, catalogo)


def test_resolver_gemini_rechaza_maximo_de_consistencia_antes_de_cargar():
    """§11.3: exceder el máximo del proveedor es error de wiring LOCAL: se
    verifica ANTES de cargar bytes (ni una sola llamada al cargador)."""
    registro = []
    muchos = [
        make_ancla(f"extra-{i}", estado="lockeado") for i in range(2)
    ]
    catalogo = CATALOGO() + muchos  # 2 personajes (4 imgs c/u) + lugar + estilo
    pedido = _pedido(
        anclas=[ReferenciaAncla(ancla_id=a.ancla_id) for a in catalogo]
    )
    with pytest.raises(ValueError, match="consistencia"):
        _resolver(registro=registro).resolver(pedido, catalogo)
    assert registro == []  # nada se cargó: fallo local antes de I/O


def test_resolver_gemini_rechaza_maximo_de_estilo():
    estilos = [make_ancla(f"look-{i}", tipo="estilo", estado="lockeado") for i in range(4)]
    pedido = _pedido(
        anclas=[ReferenciaAncla(ancla_id=a.ancla_id) for a in estilos]
    )
    with pytest.raises(ValueError, match="estilo"):
        _resolver().resolver(pedido, estilos)


def test_resolver_openai_rechaza_maximo_total_de_16():
    """gpt-image-1 ~16: el techo es global, no por categoría."""
    personajes = [make_ancla(f"p-{i}", estado="lockeado") for i in range(5)]  # 20 imágenes
    pedido = _pedido(anclas=[ReferenciaAncla(ancla_id=a.ancla_id) for a in personajes])
    resolver = ResolverDeBateria(
        PROJECT_ID,
        _cargador(),
        maximo_consistencia=16,
        maximo_estilo=16,
        maximo_total=16,
    )
    with pytest.raises(ValueError, match="máximo"):
        resolver.resolver(pedido, personajes)


# ============================== adaptadores ==============================


class _ParteFalsa:
    def __init__(self, data, mime_type):
        self.inline_data = type("Inline", (), {"data": data, "mime_type": mime_type})

    @staticmethod
    def from_bytes(data, mime_type):
        return _ParteFalsa(data, mime_type)


class _TypesFalsos:
    """Doble de google.genai.types: configs pasan, Part construye partes."""

    Part = _ParteFalsa

    @staticmethod
    def ImageConfig(**kw):
        return kw

    @staticmethod
    def GenerateContentConfig(**kw):
        return kw


class SdkFalsoGemini:
    """Doble mínimo de google-genai: captura la llamada y devuelve una imagen."""

    Types = _TypesFalsos

    def __init__(self, fallas: int = 0):
        self.llamadas = []
        self.fallas = fallas
        self.api_key = None

    def respuesta(self):
        parte = _ParteFalsa(b"imagen-generada", "image/png")
        candidato = type("Cand", (), {"content": type("C", (), {"parts": [parte]})()})()
        return type(
            "Resp", (), {"candidates": [candidato], "model_version": "gemini-x", "id": "resp-77"}
        )()

    class Models:
        def __init__(self, sdk):
            self._sdk = sdk

        def generate_content(self, model, contents, config):
            sdk = self._sdk
            sdk.llamadas.append({"model": model, "contents": contents, "config": config})
            if sdk.fallas > 0:
                sdk.fallas -= 1
                raise ConnectionError("transporte caído")
            return sdk.respuesta()

    def Client(self, api_key):
        self.api_key = api_key
        sdk = self
        return type("Cliente", (), {"models": self.Models(sdk)})


def test_gemini_sin_clave_falla_accionable_al_usarse(monkeypatch):
    """Degradación elegante: el adaptador SE construye sin clave; usarlo da
    error accionable ANTES de importar SDK o gastar red."""
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    adaptador = AdaptadorGeminiImage(PROJECT_ID, _cargador())
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        adaptador.generar_keyframe(_pedido(), CATALOGO())


def test_gemini_genera_keyframe_con_manifest_completo(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")
    adaptador = AdaptadorGeminiImage(PROJECT_ID, _cargador())
    sdk = SdkFalsoGemini()
    monkeypatch.setattr(adaptador, "_importar_sdk", lambda: (sdk, sdk.Types()))

    crudo = adaptador.generar_keyframe(
        _pedido(anclas=[ReferenciaAncla(ancla_id="protagonista", roles=["hero_portrait"])]),
        CATALOGO(),
    )

    assert crudo.datos == b"imagen-generada"
    assert crudo.formato == "png"
    assert crudo.ultimo_frame == b"imagen-generada"  # el keyframe fijo ES el frame final
    llamada = sdk.llamadas[0]
    assert llamada["model"] == "gemini-2.5-flash-image"
    assert sdk.api_key == "clave-de-prueba"
    # contents: [prompt, referencia] — la identidad viaja primero.
    assert llamada["contents"][0] == crudo.manifest.prompt_final
    assert llamada["contents"][1].inline_data.data == b"bytes-de-protagonista-hero_portrait_1.png"

    manifest = crudo.manifest
    assert manifest.proveedor == "gemini"
    assert manifest.modelo == "gemini-2.5-flash-image"
    assert manifest.seed is None
    assert manifest.anclas_usadas == [("protagonista", 1, "hero_portrait")]
    assert manifest.id_externo == "resp-77"
    assert manifest.parametros["aspect_ratio"] == "9:16"


def test_gemini_reintenta_fallos_de_transporte(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    adaptador = AdaptadorGeminiImage(
        PROJECT_ID, _cargador(), retry_policy=PoliticaReintentos(max_retries=3, backoff_seconds=0)
    )
    sdk = SdkFalsoGemini(fallas=2)  # dos fallos y a la tercera va la vencida
    monkeypatch.setattr(adaptador, "_importar_sdk", lambda: (sdk, sdk.Types()))
    crudo = adaptador.generar_keyframe(_pedido(), CATALOGO())
    assert len(sdk.llamadas) == 3
    assert crudo.datos == b"imagen-generada"


def test_gemini_agota_reintentos_y_falla_con_error_claro(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "clave")
    adaptador = AdaptadorGeminiImage(
        PROJECT_ID, _cargador(), retry_policy=PoliticaReintentos(max_retries=2, backoff_seconds=0)
    )
    sdk = SdkFalsoGemini(fallas=99)
    monkeypatch.setattr(adaptador, "_importar_sdk", lambda: (sdk, sdk.Types()))
    with pytest.raises(RuntimeError, match="tras 2 intentos"):
        adaptador.generar_keyframe(_pedido(), CATALOGO())
    assert len(sdk.llamadas) == 2


class ClienteFalsoOpenAI:
    """Doble mínimo de openai.OpenAI: captura images.edit."""

    def __init__(self, fallas: int = 0):
        self.llamadas = []
        self.fallas = fallas
        self.images = self
        self.api_key = None

    def edit(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.fallas > 0:
            self.fallas -= 1
            raise ConnectionError("429 too many requests")
        b64 = base64.b64encode(b"imagen-openai").decode()
        dato = type("Dato", (), {"b64_json": b64})()
        return type("Resp", (), {"data": [dato], "id": "img-42"})()


def test_openai_sin_clave_falla_accionable_al_usarse(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    adaptador = AdaptadorOpenAIImage(PROJECT_ID, _cargador())
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        adaptador.generar_keyframe(_pedido(), CATALOGO())


def test_openai_genera_con_fidelidad_alta_y_primera_imagen_identidad(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    adaptador = AdaptadorOpenAIImage(PROJECT_ID, _cargador())
    cliente = ClienteFalsoOpenAI()
    monkeypatch.setattr(adaptador, "_importar_sdk", lambda: lambda api_key: cliente)

    crudo = adaptador.generar_keyframe(
        _pedido(
            anclas=[
                ReferenciaAncla(ancla_id="look"),
                ReferenciaAncla(ancla_id="protagonista", roles=["hero_portrait"]),
            ],
            aspect_ratio="16:9",
        ),
        CATALOGO(),
    )

    llamada = cliente.llamadas[0]
    assert llamada["model"] == "gpt-image-1"
    assert llamada["input_fidelity"] == "high"
    assert llamada["size"] == "1536x1024"
    # §3.1: la PRIMERA imagen del array es la identidad (personaje), no el estilo.
    assert llamada["image"][0] == b"bytes-de-protagonista-hero_portrait_1.png"
    assert llamada["image"][1] == b"bytes-de-look-style_reference_1.png"
    assert crudo.datos == b"imagen-openai"
    assert crudo.manifest.proveedor == "openai"
    assert crudo.manifest.anclas_usadas == [
        ("protagonista", 1, "hero_portrait"),
        ("look", 1, "style_reference"),
    ]
    assert crudo.manifest.parametros["input_fidelity"] == "high"
    assert base64.b64decode(base64.b64encode(b"imagen-openai")) == crudo.datos


def test_openai_sin_referencias_no_envia_fidelidad(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-prueba")
    adaptador = AdaptadorOpenAIImage(PROJECT_ID, _cargador())
    cliente = ClienteFalsoOpenAI()
    monkeypatch.setattr(adaptador, "_importar_sdk", lambda: lambda api_key: cliente)
    adaptador.generar_keyframe(_pedido(), CATALOGO())
    llamada = cliente.llamadas[0]
    assert llamada["image"] is None
    assert llamada["input_fidelity"] is None


# ======================== transporte y fábrica ========================


def test_con_reintentos_devuelve_el_valor_y_duerme_backoff_corto():
    politica = PoliticaReintentos(max_retries=2, backoff_seconds=0)
    intentos = []

    def operacion():
        intentos.append(1)
        if len(intentos) < 2:
            raise TimeoutError("lento")
        return "ok"

    assert con_reintentos(operacion, politica, "prueba") == "ok"
    assert len(intentos) == 2


def test_politica_de_reintentos_valida_sus_limites():
    with pytest.raises(ValueError, match="max_retries"):
        PoliticaReintentos(max_retries=0)
    with pytest.raises(ValueError, match="backoff"):
        PoliticaReintentos(backoff_seconds=-1)


def test_fabrica_construye_adaptadores_por_nombre_y_rechaza_desconocidos():
    cargador = _cargador()
    for nombre in PROVEEDORES_DE_IMAGEN:
        puerto = construir_puerto_de_media(nombre, PROJECT_ID, cargador)
        assert isinstance(puerto, AdaptadorGeminiImage if nombre == "gemini" else AdaptadorOpenAIImage)
    with pytest.raises(ValueError, match="proveedor_imagen"):
        construir_puerto_de_media("veo", PROJECT_ID, cargador)


def test_resolver_proveedor_con_precedencia():
    assert ResolverDeBateria is not None  # sanidad de import
    from sinnema.infrastructure.media.fabrica import (
        PROVEEDOR_DEFAULT,
        resolver_proveedor,
    )

    assert resolver_proveedor(None, None) == PROVEEDOR_DEFAULT == "gemini"
    assert resolver_proveedor(None, "openai") == "openai"
    assert resolver_proveedor("openai", "gemini") == "openai"  # TOML gana
    assert resolver_proveedor("OpenAI", None) == "openai"  # normaliza
    with pytest.raises(ValueError, match="veo"):
        resolver_proveedor("veo", None)


# ============================== almacén ==============================


def test_almacen_guarda_con_naming_coherente(tmp_path):
    almacen = AlmacenMedia(root=tmp_path / "media")
    relativa = almacen.guardar_keyframe(PROJECT_ID, "ch-01", 3, "png", b"datos")
    assert relativa == f"{PROJECT_ID}/ch-01/escena_3.png"
    destino = tmp_path / "media" / PROJECT_ID / "ch-01" / "escena_3.png"
    assert destino.read_bytes() == b"datos"


def test_almacen_rechaza_rutas_que_escapan(tmp_path):
    almacen = AlmacenMedia(root=tmp_path / "media")
    with pytest.raises(ValueError, match="inválida"):
        almacen.ruta_de("../escape.png")
    with pytest.raises(ValueError, match="chapter_id"):
        almacen.ruta_de(f"{PROJECT_ID}/../escape/escena_1.png")
    with pytest.raises(ValueError, match="Formato"):
        almacen.ruta_de(f"{PROJECT_ID}/ch-01/escena_1.exe")
    with pytest.raises(ValueError, match="escena_"):
        almacen.ruta_de(f"{PROJECT_ID}/ch-01/travesia_1.png")

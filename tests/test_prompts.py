"""Contract tests del paquete de prompts parametrizados por proyecto.

Un mismo contrato para los seis roles: el system prompt se construye desde el
``ProjectSpec`` (sin valores hardcodeados del show de referencia) y los
builders de usuario emiten bloques XML delimitados y balanceados.
"""
from __future__ import annotations

import re

from sinnema.application.ports import (
    ROLE_ADAPTER,
    ROLE_CONTINUITY,
    ROLE_CRITIC,
    ROLE_DIRECTOR,
    ROLE_PLANNER,
    ROLE_SCRIPTWRITER,
)
from sinnema.application.prompts import (
    adapter,
    continuity,
    critic,
    director,
    planner,
    scriptwriter,
)
from sinnema.application.prompts import build_role_system_prompts
from sinnema.application.projects import AgentConfig
from sinnema.domain.models import FormatProfile

from conftest import (
    make_adapted,
    make_chapter,
    make_directives,
    make_draft,
    make_project,
)

ROLES = [
    ROLE_PLANNER,
    ROLE_CONTINUITY,
    ROLE_SCRIPTWRITER,
    ROLE_ADAPTER,
    ROLE_CRITIC,
    ROLE_DIRECTOR,
]

#: Patrón de placeholders sin interpolar (ej: "{brand_name}").
_PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


#: Nombres de tags XML de apertura (ej: "<tema>").
_APERTURA = re.compile(r"<([a-z_][a-z0-9_]*)>")


def _assert_tags_balanceados(texto: str) -> None:
    """Cada tag de apertura tiene su cierre con el mismo nombre."""
    for nombre in set(_APERTURA.findall(texto)):
        assert texto.count(f"<{nombre}>") == texto.count(f"</{nombre}>"), (
            f"tag <{nombre}> desbalanceado en:\n{texto[:400]}"
        )


# ------------------------- System prompts por proyecto -------------------------


def test_catalogo_cubre_los_seis_roles():
    prompts = build_role_system_prompts(make_project())
    assert set(prompts) == set(ROLES)
    assert all(prompts[rol].strip() for rol in ROLES)


def test_system_prompts_interpolan_la_marca_y_nada_queda_por_reemplazar():
    proyecto = make_project(brand_name="Duelo de Motores")
    for rol, prompt in build_role_system_prompts(proyecto).items():
        assert "Duelo de Motores" in prompt, f"rol {rol}"
        assert not _PLACEHOLDER.search(prompt), (
            f"placeholder sin interpolar en el rol {rol}"
        )


def test_system_prompts_no_mencionan_la_marca_de_referencia():
    """El show 'Sinnema' es un proyecto más: ningún prompt la hardcodea."""
    proyecto = make_project(brand_name="Otra Marca")
    for rol, prompt in build_role_system_prompts(proyecto).items():
        assert "Sinnema" not in prompt, f"rol {rol}"


def test_prompts_reflejan_los_numeros_del_perfil_del_proyecto():
    perfil = FormatProfile(
        scenes_count=(3, 5),
        narration_target_words=(90, 110),
        narration_hard_words=(80, 120),
        min_approval_score=9,
        on_screen_text_max_words=4,
    )
    proyecto = make_project(format=perfil, language="Inglés americano")
    prompts = build_role_system_prompts(proyecto)

    assert "90-110" in prompts[ROLE_PLANNER]
    assert "entre 3 y 5" in prompts[ROLE_SCRIPTWRITER]
    assert "máximo 4 palabras" in prompts[ROLE_SCRIPTWRITER]
    assert ">= 9" in prompts[ROLE_CRITIC]
    assert "Inglés americano" in prompts[ROLE_CONTINUITY]


def test_prompt_del_adapter_lleva_audiencia_tono_e_idioma():
    proyecto = make_project(
        audience="Mecánicos aficionados de 30 años",
        tone_of_voice="directo y técnico",
        language="Español rioplatense",
    )
    prompt = adapter.build_system_prompt(proyecto)
    assert "Mecánicos aficionados de 30 años" in prompt
    assert "directo y técnico" in prompt
    assert "Español rioplatense" in prompt


def test_prompt_del_director_lleva_el_estilo_maestro_del_proyecto():
    proyecto = make_project(
        visual_master_style="cinematic live-action garage setup, warm key light"
    )
    prompt = director.build_system_prompt(proyecto)
    assert "cinematic live-action garage setup, warm key light" in prompt


# ---------------------------- Mensajes de usuario ----------------------------


def test_mensaje_del_planner_incluye_tema_y_capitulos():
    proyecto = make_project()
    mensaje = planner.build_user_message(proyecto, "Fotosíntesis en 60 s", 4)
    assert "<tema>Fotosíntesis en 60 s</tema>" in mensaje
    assert "<numero_de_capitulos>4</numero_de_capitulos>" in mensaje
    _assert_tags_balanceados(mensaje)


def test_mensaje_del_guionista_con_y_sin_feedback():
    proyecto = make_project()
    capitulo = make_chapter(1)
    directivas = make_directives()
    sin_feedback = scriptwriter.build_user_message(
        proyecto, chapter=capitulo, directives=directivas
    )
    con_feedback = scriptwriter.build_user_message(
        proyecto, chapter=capitulo, directives=directivas,
        feedback="1. Acelera el gancho.",
    )
    assert "<correccion_feedback>" not in sin_feedback
    assert "<correccion_feedback>\n1. Acelera el gancho.\n</correccion_feedback>" in con_feedback
    _assert_tags_balanceados(sin_feedback)
    _assert_tags_balanceados(con_feedback)


def test_mensaje_del_critico_incluye_conteo_real():
    proyecto = make_project()
    borrador = make_draft()
    mensaje = critic.build_user_message(
        proyecto,
        chapter=make_chapter(1),
        draft=borrador,
        adapted=make_adapted(borrador),
        directives=make_directives(),
        actual_word_count=137,
    )
    assert "<conteo_real_palabras>137</conteo_real_palabras>" in mensaje
    assert "130-150" in mensaje  # presupuesto del perfil por defecto
    _assert_tags_balanceados(mensaje)


def test_mensaje_del_director_incluye_estilo_maestro_y_escenas():
    proyecto = make_project()
    borrador = make_draft()
    mensaje = director.build_user_message(
        proyecto,
        chapter=make_chapter(1),
        draft=borrador,
        adapted=make_adapted(borrador),
        recurring_elements=["mascota Roby"],
    )
    assert proyecto.visual_master_style in mensaje
    assert "mascota Roby" in mensaje
    _assert_tags_balanceados(mensaje)


def test_mensaje_de_continuidad_con_memoria_vacia():
    mensaje = continuity.build_user_message(
        chapter=make_chapter(1),
        previous_chapter=None,
        lore_entries=[],
        recurring_elements=[],
    )
    assert "memoria de continuidad vacía" in mensaje
    _assert_tags_balanceados(mensaje)


# ------------------- Reglas por agente y directivas ausentes -------------------


def test_reglas_del_proyecto_se_inyectan_solo_en_el_rol_configurado():
    proyecto = make_project(
        agentes={
            ROLE_CRITIC: AgentConfig(
                reglas=("Exigir fuente verificable", "Cero emojis")
            ),
            ROLE_SCRIPTWRITER: AgentConfig(),  # declarado pero sin reglas
        }
    )
    prompts = build_role_system_prompts(proyecto)
    assert "REGLAS ADICIONALES DEL PROYECTO" in prompts[ROLE_CRITIC]
    assert "- Exigir fuente verificable" in prompts[ROLE_CRITIC]
    assert "- Cero emojis" in prompts[ROLE_CRITIC]
    assert "REGLAS ADICIONALES" not in prompts[ROLE_SCRIPTWRITER]
    assert "REGLAS ADICIONALES" not in prompts[ROLE_PLANNER]


def test_proyecto_sin_reglas_no_agrega_bloque():
    for rol, prompt in build_role_system_prompts(make_project()).items():
        assert "REGLAS ADICIONALES" not in prompt, f"rol {rol}"


def test_mensajes_tolera_directivas_none_por_continuidad_desactivada():
    proyecto = make_project()
    capitulo = make_chapter(1)
    borrador = make_draft()

    msg_guionista = scriptwriter.build_user_message(
        proyecto, chapter=capitulo, directives=None
    )
    assert "sin directivas" in msg_guionista
    _assert_tags_balanceados(msg_guionista)

    msg_adapter = adapter.build_user_message(
        proyecto, draft=borrador, directives=None
    )
    assert "(ninguno)" in msg_adapter
    _assert_tags_balanceados(msg_adapter)

    msg_critico = critic.build_user_message(
        proyecto,
        chapter=capitulo,
        draft=borrador,
        adapted=make_adapted(borrador),
        directives=None,
        actual_word_count=137,
    )
    assert "sin directivas" in msg_critico
    _assert_tags_balanceados(msg_critico)

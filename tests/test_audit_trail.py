"""Tests de la pista de auditoría: adaptador de filesystem e integración.

Cubren la carpeta por ejecución (``log.txt`` cronológico + un ``.txt`` por
paso), la numeración de pasos, la degradación ante fallos de escritura y el
registro completo de una generación (incluido el ciclo de crítica, los
descartes de capítulos y el resumen del CLI).
"""
from __future__ import annotations

import json

from sinnema.application.settings import PipelineSettings
from sinnema.application.use_cases import GenerateSeriesUseCase
from sinnema.infrastructure.audit import FilesystemAuditTrail
from sinnema.infrastructure.cli.main import main
from sinnema.application.ports import NullAuditTrail

from conftest import gateway_con_serie, make_audit, make_plan, make_project, make_request


# ------------------------- Adaptador FilesystemAuditTrail -------------------------


def test_inicializacion_crea_carpeta_y_log(tmp_path):
    trail = FilesystemAuditTrail(tmp_path / "auditoria" / "serie_1")

    assert (tmp_path / "auditoria" / "serie_1").is_dir()
    log = (tmp_path / "auditoria" / "serie_1" / "log.txt").read_text(encoding="utf-8")
    assert "Carpeta de auditoría" in log


def test_log_step_escribe_archivo_numerado_y_linea_en_log(tmp_path):
    trail = FilesystemAuditTrail(tmp_path / "aud")

    trail.log_step(
        "plan_series",
        "Plan maestro 'Serie de prueba' con 1 capítulo(s).",
        artifact=make_plan(1),
        details=["ch-01: Capítulo de prueba número 1"],
    )

    contenido = (tmp_path / "aud" / "001_plan_series.txt").read_text(encoding="utf-8")
    assert "Paso 001 · plan_series" in contenido
    assert "Plan maestro 'Serie de prueba'" in contenido
    assert "· ch-01: Capítulo de prueba número 1" in contenido
    assert '"series_title"' in contenido  # artefacto volcado como JSON

    log = (tmp_path / "aud" / "log.txt").read_text(encoding="utf-8")
    assert "paso 001 · plan_series — Plan maestro" in log


def test_el_json_del_artefacto_es_valido_y_legible(tmp_path):
    trail = FilesystemAuditTrail(tmp_path / "aud")
    trail.log_step("plan_series", "Plan listo", artifact=make_plan(2))

    contenido = (tmp_path / "aud" / "001_plan_series.txt").read_text(encoding="utf-8")
    volcado = json.loads(contenido.split("Artefacto generado (JSON):\n", 1)[1])
    assert len(volcado["chapters"]) == 2


def test_pasos_repetidos_incrementan_numeracion(tmp_path):
    trail = FilesystemAuditTrail(tmp_path / "aud")

    trail.log_step("scriptwriter", "Borrador 1")
    trail.log_step("scriptwriter", "Borrador 2")

    nombres = {p.name for p in (tmp_path / "aud").iterdir()}
    assert "001_scriptwriter.txt" in nombres
    assert "002_scriptwriter.txt" in nombres


def test_log_step_sin_artefacto_no_volca_json(tmp_path):
    trail = FilesystemAuditTrail(tmp_path / "aud")

    trail.log_step("solicitud", "Generación solicitada.", details=["capítulos: 3"])

    contenido = (tmp_path / "aud" / "001_solicitud.txt").read_text(encoding="utf-8")
    assert "· capítulos: 3" in contenido
    assert "Artefacto generado" not in contenido


def test_slug_sanitiza_nombres_de_paso(tmp_path):
    trail = FilesystemAuditTrail(tmp_path / "aud")

    trail.log_step("Paso con espacios y ¡signos!", "Resumen")

    assert (tmp_path / "aud" / "001_paso_con_espacios_y_signos.txt").exists()


def test_log_event_y_log_failure_solo_tocan_el_log(tmp_path):
    trail = FilesystemAuditTrail(tmp_path / "aud")

    trail.log_event("Evento puntual sin archivo propio.")
    trail.log_failure("Capítulo ch-01 descartado.")

    log = (tmp_path / "aud" / "log.txt").read_text(encoding="utf-8")
    assert "Evento puntual sin archivo propio." in log
    assert "ERROR · Capítulo ch-01 descartado." in log
    nombres = {p.name for p in (tmp_path / "aud").iterdir()}
    assert nombres == {"log.txt"}


def test_fallo_de_filesystem_desactiva_la_auditoria_sin_romper(tmp_path):
    bloqueado = tmp_path / "bloqueado"
    bloqueado.write_text("soy un archivo, no un directorio", encoding="utf-8")

    trail = FilesystemAuditTrail(bloqueado / "serie")

    trail.log_step("plan_series", "No debe explotar.")
    trail.log_failure("Tampoco aquí.")


def test_null_audit_trail_es_noop():
    audit = NullAuditTrail()
    audit.log_step("plan_series", "sin efectos", artifact=make_plan(1), details=["x"])
    audit.log_event("evento")
    audit.log_failure("fallo")


# --------------------- Integración: pipeline + pista de auditoría ---------------------


def nombres_de_pasos(carpeta):
    return [p.name.split("_", 1)[1] for p in sorted(carpeta.iterdir()) if p.name != "log.txt"]


def test_execute_deja_carpeta_de_auditoria_con_un_archivo_por_paso(tmp_path):
    carpeta = tmp_path / "auditoria" / "serie_x"
    audit = FilesystemAuditTrail(carpeta)
    use_case = GenerateSeriesUseCase(
        gateway_con_serie(num_chapters=1), make_project(), audit=audit
    )

    use_case.execute(make_request(num_chapters=1))

    assert nombres_de_pasos(carpeta) == [
        "solicitud.txt",
        "plan_series.txt",
        "continuity_master.txt",
        "scriptwriter.txt",
        "persona_adapter.txt",
        "chief_critic.txt",
        "technical_director.txt",
        "commit_episode.txt",
    ]
    log = (carpeta / "log.txt").read_text(encoding="utf-8")
    assert log.index("solicitud") < log.index("plan_series") < log.index("commit_episode")


def test_ciclo_de_critica_deja_constancia_de_cada_reintento(tmp_path):
    carpeta = tmp_path / "aud"
    audit = FilesystemAuditTrail(carpeta)
    gw = gateway_con_serie(
        num_chapters=1,
        audits_por_capitulo=[[make_audit(approved=False), make_audit(approved=True)]],
    )
    use_case = GenerateSeriesUseCase(gw, make_project(), audit=audit)

    use_case.execute(make_request(num_chapters=1))

    pasos = nombres_de_pasos(carpeta)
    assert pasos.count("scriptwriter.txt") == 2
    assert pasos.count("chief_critic.txt") == 2
    veredictos = [
        (carpeta / nombre).read_text(encoding="utf-8")
        for nombre in sorted(p.name for p in carpeta.iterdir())
        if nombre.endswith("chief_critic.txt")
    ]
    assert "RECHAZA" in veredictos[0]
    assert "APRUEBA" in veredictos[1]


def test_capitulo_descartado_queda_registrado_como_error_y_paso(tmp_path):
    carpeta = tmp_path / "aud"
    audit = FilesystemAuditTrail(carpeta)
    gw = gateway_con_serie(
        num_chapters=1,
        audits_por_capitulo=[[make_audit(approved=False, score=3)]],
    )
    ajustes = PipelineSettings(
        max_critique_attempts=1, retry_exhaustion_policy="skip_chapter"
    )
    use_case = GenerateSeriesUseCase(gw, make_project(), ajustes, audit=audit)

    entregable = use_case.execute(make_request(num_chapters=1, max_critique_attempts=1))

    assert len(entregable.failed_chapters) == 1
    assert "fail_chapter.txt" in nombres_de_pasos(carpeta)
    log = (carpeta / "log.txt").read_text(encoding="utf-8")
    assert "ERROR · Capítulo ch-01 descartado" in log


# ----------------------------- CLI de punta a punta -----------------------------


def test_cli_crea_carpeta_de_auditoria_y_resumen_por_ejecucion(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sinnema.infrastructure.cli.main.build_gateway",
        lambda proyecto: gateway_con_serie(num_chapters=2),
    )
    monkeypatch.setattr("sys.argv", ["sinnema", "-n", "2"])

    codigo = main()

    assert codigo == 0
    # La auditoría se namespacea por proyecto: auditoria/<pid>/serie_<marca>/
    carpetas_proyecto = list((tmp_path / "auditoria").iterdir())
    assert len(carpetas_proyecto) == 1  # solo el proyecto por defecto
    series = list(carpetas_proyecto[0].iterdir())
    assert len(series) == 1
    archivos = {p.name for p in series[0].iterdir()}
    assert "log.txt" in archivos
    assert "001_solicitud.txt" in archivos
    assert any("resumen" in nombre for nombre in archivos)

    resumen = next(p for p in series[0].iterdir() if "resumen" in p.name)
    texto = resumen.read_text(encoding="utf-8")
    assert "episodios aprobados" in texto
    assert "serie_" in texto  # ruta del entregable JSON

    assert list((tmp_path / "salidas").glob("*/serie_*.json"))
    assert "Auditoría de la ejecución:" in capsys.readouterr().out


# ----------------- Prompts por paso (red-3d §7.4) -----------------


def test_log_prompts_queda_emparejado_con_el_paso(tmp_path):
    pista = FilesystemAuditTrail(tmp_path / "run")
    pista.log_prompts("plan_series", "SYSTEM:\n...\nUSER:\n...")
    pista.log_step("plan_series", "El planner generó el plan.")

    prompts = pista._dir / "001_plan_series_prompts.txt"
    paso = pista._dir / "001_plan_series.txt"
    assert prompts.is_file() and paso.is_file()
    assert "USER:" in prompts.read_text(encoding="utf-8")

    # El siguiente paso avanza el contador sin arrastrar el de prompts.
    pista.log_step("compuerta", "dictamen")
    assert (pista._dir / "002_compuerta.txt").is_file()
    assert not (pista._dir / "002_plan_series_prompts.txt").exists()

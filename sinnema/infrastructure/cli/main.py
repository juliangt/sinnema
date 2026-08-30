"""CLI del motor multi-proyecto y composition root del sistema completo.

Este es el único módulo que arma el mundo: carga el proyecto (TOML), el
entorno, instancia el adaptador LLM (implementando el puerto de aplicación)
y el almacén de lore, compila el caso de uso, ejecuta con streaming de
progreso y exporta el JSON validado.

Uso:
    python main.py                                     # proyecto por defecto (sinnema)
    python main.py -p motores                          # show de motores eléctricos vs combustión
    python main.py -p motores -t "Motores híbridos" -n 4
    python main.py --list-projects

Requisitos de entorno (al menos un proveedor):
    ANTHROPIC_API_KEY / OPENAI_API_KEY / GOOGLE_API_KEY (o Gemini via
    GEMINI_API_KEY) / servidor Ollama local.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

try:  # carga opcional de .env si el usuario instaló python-dotenv
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from sinnema.application.projects import ProjectSpec
from sinnema.application.requests import (
    MAX_CRITIQUE_ATTEMPTS_LIMIT,
    SeriesRequest,
)
from sinnema.application.settings import PipelineSettings
from sinnema.application.state import PipelineState
from sinnema.application.use_cases import GenerateSeriesUseCase, build_deliverable
from sinnema.domain.constants import SERIES_MAX_CHAPTERS
from sinnema.domain.exceptions import DomainValidationError
from sinnema.domain.models import SeriesDeliverable
from sinnema.infrastructure.audit import FilesystemAuditTrail
from sinnema.infrastructure.llm.gateway import build_gateway
from sinnema.infrastructure.lore import JsonLoreStore
from sinnema.infrastructure.projects import list_projects, load_project

logger = logging.getLogger("sinnema.main")

#: Proyecto usado cuando el CLI no recibe ``-p/--project``.
DEFAULT_PROJECT_ID = "educativo"


# =========================================================================
# CLI
# =========================================================================


def _int_en_rango(minimo: int, maximo: int, mensaje: str):
    def _validar(valor: str) -> int:
        try:
            numero = int(valor)
        except ValueError:
            raise argparse.ArgumentTypeError(f"'{valor}' no es un entero.")
        if not (minimo <= numero <= maximo):
            raise argparse.ArgumentTypeError(f"{mensaje} (rango {minimo}-{maximo}).")
        return numero

    return _validar


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sinnema",
        description=(
            "Motor multi-agente de series de micro-videos verticales. "
            "Cada proyecto (show) define su voz, idioma, estilo y continuidad "
            "en proyectos/<id>.toml."
        ),
    )
    parser.add_argument(
        "-p", "--project", default=DEFAULT_PROJECT_ID,
        help=f"Proyecto/show a generar (por defecto: {DEFAULT_PROJECT_ID}). "
        "Ver --list-projects.",
    )
    parser.add_argument(
        "-t", "--topic", default=None,
        help="Tema de la serie (por defecto: el tema del proyecto).",
    )
    parser.add_argument(
        "-n", "--chapters", type=_int_en_rango(1, SERIES_MAX_CHAPTERS, "Número de capítulos inválido"),
        default=3, help=f"Cantidad de capítulos/videos de la serie (1-{SERIES_MAX_CHAPTERS}).",
    )
    parser.add_argument(
        "-m", "--max-critique-attempts", type=_int_en_rango(1, MAX_CRITIQUE_ATTEMPTS_LIMIT, "Reintentos inválidos"),
        default=2, help=f"Límite duro de reintentos del ciclo de crítica (1-{MAX_CRITIQUE_ATTEMPTS_LIMIT}).",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="Ruta del JSON de salida (por defecto salidas/<proyecto>/serie_<timestamp>.json).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Logging detallado (DEBUG)."
    )
    parser.add_argument(
        "--list-projects", action="store_true",
        help="Lista los proyectos disponibles y termina.",
    )
    return parser.parse_args()


def build_request_from_args(args: argparse.Namespace, project: ProjectSpec) -> SeriesRequest:
    """Traduce los argumentos del CLI y el proyecto a la petición validada."""
    request = SeriesRequest(
        project=project,
        topic=args.topic,
        num_chapters=args.chapters,
        max_critique_attempts=args.max_critique_attempts,
    )
    request.validate()
    return request


def _print_projects(proyectos: list[ProjectSpec]) -> None:
    print("Proyectos disponibles:")
    for proyecto in proyectos:
        print(f"  {proyecto.project_id:12} {proyecto.brand_name}: {proyecto.default_topic}")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


# =========================================================================
# PROGRESO Y RESUMEN
# =========================================================================


def _print_progress(paso: int, state: PipelineState) -> None:
    plan = state.get("series_plan")
    if plan is None:
        print(f"[paso {paso:03d}] planificando la serie...")
        return
    total = len(plan.chapters)
    indice = state.get("current_chapter_index", 0)
    visible = min(indice, total - 1)
    capitulo = plan.chapters[visible]
    print(
        f"[paso {paso:03d}] cap. {indice + 1 if indice < total else total}/{total} "
        f"'{capitulo.title}' · intentos de crítica: {state.get('critique_attempts', 0)} "
        f"· episodios listos: {len(state.get('completed_episodes', []))}"
    )


def _print_summary(
    deliverable: SeriesDeliverable, ruta: Path, carpeta_auditoria: Path
) -> None:
    print("\n" + "=" * 62)
    print(f"PROYECTO: {deliverable.project_id} · SERIE: {deliverable.series_title}")
    print(f"Episodios aprobados: {len(deliverable.episodes)}/{deliverable.total_chapters_planned} "
          f"(score medio: {deliverable.average_quality_score}/10)")
    for episodio in deliverable.episodes:
        estado = " · ACEPTADO FORZADO tras agotar reintentos" if episodio.forced_acceptance else ""
        print(
            f"  [{episodio.order_index:02d}] {episodio.title} "
            f"— QA {episodio.audit.overall_score}/10{estado}"
        )
    for fallo in deliverable.failed_chapters:
        print(f"  [xx] {fallo.title} — DESCARTADO: {fallo.reason}")
    print(f"Términos en el lore: {len(deliverable.lore_glossary)}")
    print(f"Entregable JSON: {ruta}")
    print(f"Auditoría de la ejecución: {carpeta_auditoria}")
    print("=" * 62)


def _auditar_resumen(
    audit: FilesystemAuditTrail, deliverable: SeriesDeliverable, ruta: Path
) -> None:
    """Escribe el paso final de resumen en la carpeta de auditoría."""
    detalles = [
        f"proyecto: {deliverable.project_id}",
        f"entregable JSON: {ruta}",
        f"términos en el lore: {len(deliverable.lore_glossary)}",
        *(
            f"episodio {e.order_index:02d}: {e.title} — QA {e.audit.overall_score}/10"
            + (" · aceptación forzada" if e.forced_acceptance else "")
            for e in deliverable.episodes
        ),
        *(f"descartado: {f.title} — {f.reason}" for f in deliverable.failed_chapters),
    ]
    audit.log_step(
        "resumen",
        f"Serie completa: {len(deliverable.episodes)}/{deliverable.total_chapters_planned} "
        f"episodios aprobados (score medio {deliverable.average_quality_score}/10).",
        details=detalles,
    )


# =========================================================================
# MAIN (composition root)
# =========================================================================


def main() -> int:
    args = _parse_args()
    _configure_logging(args.verbose)

    if args.list_projects:
        try:
            _print_projects(list_projects())
        except (RuntimeError, ValueError) as exc:
            print(f"[error de proyectos] {exc}", file=sys.stderr)
            return 2
        return 0

    try:
        proyecto = load_project(args.project)
    except RuntimeError as exc:
        print(f"[error de proyecto] {exc}", file=sys.stderr)
        return 2

    try:
        request = build_request_from_args(args, proyecto)
    except ValueError as exc:
        print(f"[error de petición] {exc}", file=sys.stderr)
        return 2

    try:
        gateway = build_gateway()
    except RuntimeError as exc:
        print(f"[error de configuración] {exc}", file=sys.stderr)
        return 2

    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta_auditoria = Path(f"auditoria/{proyecto.project_id}/serie_{marca}")
    audit = FilesystemAuditTrail(carpeta_auditoria)
    lore_store = JsonLoreStore()

    settings = PipelineSettings(max_critique_attempts=args.max_critique_attempts)
    use_case = GenerateSeriesUseCase(gateway, proyecto, settings, audit=audit, lore_store=lore_store)

    print(
        f"Compilando pipeline del proyecto '{proyecto.project_id}' "
        f"({proyecto.brand_name}) para '{request.resolved_topic()}' "
        f"({request.num_chapters} capítulos)..."
    )
    estado_final: Optional[PipelineState] = None
    paso = 0
    try:
        for paso, snapshot in enumerate(use_case.stream(request), start=1):
            estado_final = snapshot
            _print_progress(paso, estado_final)
    except Exception as exc:  # noqa: BLE001 - reportamos cualquier fallo de ejecución
        if args.verbose:
            logger.exception("La ejecución del pipeline falló en el paso %s.", paso)
        else:
            logger.error("La ejecución del pipeline falló en el paso %s: %s", paso, exc)
        audit.log_failure(f"La ejecución del pipeline falló en el paso {paso}: {exc}")
        print(f"[error] La ejecución del pipeline falló: {exc}", file=sys.stderr)
        return 1

    try:
        deliverable = build_deliverable(estado_final)
    except DomainValidationError as exc:
        audit.log_failure(f"No se pudo construir el entregable: {exc}")
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    use_case.save_lore(estado_final)

    ruta = Path(args.output or f"salidas/{proyecto.project_id}/serie_{marca}.json")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(deliverable.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _auditar_resumen(audit, deliverable, ruta)
    _print_summary(deliverable, ruta, carpeta_auditoria)
    return 0


if __name__ == "__main__":
    sys.exit(main())

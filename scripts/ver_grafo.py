#!/usr/bin/env python3
"""Visualización del grafo multi-agente: diagrama Mermaid y stream en vivo.

Modos:
    diagrama  Genera la representación Mermaid del grafo compilado (no
              llama a ningún LLM ni consume API keys).
    stream    Ejecuta el pipeline real con streaming (``stream_mode="updates"``)
              e imprime, paso a paso, qué nodo se ejecuta y qué claves del
              estado actualiza. Requiere proveedor LLM configurado.

Ejemplos:
    python scripts/ver_grafo.py diagrama                    # Mermaid a stdout
    python scripts/ver_grafo.py diagrama --png grafo.png    # PNG (usa mermaid.ink)
    python scripts/ver_grafo.py stream -p educativo -n 2    # corrida monitorizada
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:  # carga opcional de .env si el usuario instaló python-dotenv
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from sinnema.application.graph import build_pipeline_graph
from sinnema.application.registry import AGENT_REGISTRY
from sinnema.application.requests import (
    MAX_CRITIQUE_ATTEMPTS_LIMIT,
    SeriesRequest,
    build_initial_state,
)
from sinnema.application.settings import PipelineSettings
from sinnema.domain.constants import SERIES_MAX_CHAPTERS
from sinnema.infrastructure.llm.gateway import build_gateway
from sinnema.infrastructure.projects import list_projects, load_project

#: Descripción legible de cada nodo, para el stream en vivo. Los nodos de
#: agente salen del registro; los estructurales se describen aquí.
ROL_NODO: Dict[str, str] = {
    d.nodo: d.descripcion for d in AGENT_REGISTRY.values()
}
ROL_NODO.update({
    "commit_episode": "Consolidación del episodio + lore",
    "fail_chapter": "Capítulo descartado (reintentos agotados)",
})


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
        prog="ver_grafo",
        description="Visualiza el grafo multi-agente: diagrama Mermaid o stream en vivo.",
    )
    sub = parser.add_subparsers(dest="modo")

    def con_proyecto(p: argparse.ArgumentParser) -> None:
        p.add_argument("-p", "--project", default="educativo",
                       help="Proyecto/show (por defecto: educativo). Ver: --list-projects.")
        p.add_argument("-t", "--topic", default=None,
                       help="Tema de la serie (por defecto: el del proyecto).")
        p.add_argument("-n", "--chapters", type=_int_en_rango(1, SERIES_MAX_CHAPTERS, "Número de capítulos inválido"),
                       default=3, help=f"Capítulos de la serie (1-{SERIES_MAX_CHAPTERS}).")
        p.add_argument("-m", "--max-critique-attempts",
                       type=_int_en_rango(1, MAX_CRITIQUE_ATTEMPTS_LIMIT, "Reintentos inválido"),
                       default=2, help="Reintentos máximos del ciclo de crítica.")
        p.add_argument("-v", "--verbose", action="store_true", help="Logging detallado (DEBUG).")

    p_diag = sub.add_parser("diagrama", help="Imprime/guarda el diagrama Mermaid del grafo.")
    con_proyecto(p_diag)
    p_diag.add_argument("--png", metavar="RUTA", default=None,
                        help="Guarda además un PNG renderizando el Mermaid vía mermaid.ink (requiere red).")

    p_stream = sub.add_parser("stream", help="Ejecuta el pipeline mostrando cada nodo y su estado.")
    con_proyecto(p_stream)

    parser.add_argument("--list-projects", action="store_true",
                        help="Lista los proyectos disponibles y termina.")
    return parser.parse_args()


def _preparar(args: argparse.Namespace):
    """Carga el proyecto y compila el grafo (sin llamar al gateway todavía)."""
    proyecto = load_project(args.project)
    request = SeriesRequest(
        project=proyecto,
        topic=args.topic,
        num_chapters=args.chapters,
        max_critique_attempts=args.max_critique_attempts,
    )
    request.validate()
    settings = PipelineSettings(max_critique_attempts=args.max_critique_attempts)
    return proyecto, request, settings


# =========================================================================
# Modo diagrama
# =========================================================================


def modo_diagrama(args: argparse.Namespace) -> int:
    proyecto, request, settings = _preparar(args)

    class _GatewayNulo:  # el diagrama nunca genera contenido; no se invoca
        def generate(self, *_a, **_k):  # pragma: no cover
            raise RuntimeError("El modo diagrama no ejecuta el pipeline.")

    grafo = build_pipeline_graph(_GatewayNulo(), proyecto, settings)

    print(f"# Grafo del pipeline — proyecto '{proyecto.project_id}' ({proyecto.brand_name})")
    print("# Pégalo en https://mermaid.live o en cualquier visor Mermaid.\n")
    mermaid: str = grafo.get_graph().draw_mermaid()
    print(mermaid)

    if args.png:
        png: bytes = grafo.get_graph().draw_mermaid_png()
        ruta = Path(args.png)
        ruta.write_bytes(png)
        print(f"\nPNG guardado en: {ruta}")
    return 0


# =========================================================================
# Modo stream
# =========================================================================


def _resumen_nodo(nodo: str, actualizacion: Dict[str, Any]) -> str:
    """Una línea legible de qué produjo el nodo."""
    if nodo == "plan_series" and actualizacion.get("series_plan"):
        plan = actualizacion["series_plan"]
        return f"'{plan.series_title}' · {len(plan.chapters)} capítulo(s)"
    if nodo in ("chief_critic",) and actualizacion.get("qa_verdict"):
        d = actualizacion["qa_verdict"]
        veredicto = "APRUEBA" if d.approved else "RECHAZA"
        return f"{veredicto} · score {d.overall_score}/10 · intento {actualizacion.get('critique_attempts')}"
    if nodo == "commit_episode":
        return f"episodios listos: {len(actualizacion.get('completed_episodes', []))} · índice -> {actualizacion.get('current_chapter_index')}"
    if nodo == "fail_chapter":
        return f"capítulo descartado · índice -> {actualizacion.get('current_chapter_index')}"
    return ", ".join(actualizacion.keys())


def modo_stream(args: argparse.Namespace) -> int:
    import logging

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    proyecto, request, settings = _preparar(args)

    try:
        gateway = build_gateway()
    except RuntimeError as exc:
        print(f"[error de configuración] {exc}", file=sys.stderr)
        return 2

    grafo = build_pipeline_graph(gateway, proyecto, settings)
    estado_inicial = build_initial_state(request)

    print(
        f"Pipeline '{proyecto.project_id}' ({proyecto.brand_name}) · tema: "
        f"{request.resolved_topic()} · {request.num_chapters} capítulo(s)\n"
        + "-" * 70
    )

    config = {"recursion_limit": 8 * SERIES_MAX_CHAPTERS * (settings.max_critique_attempts + 1) + 50}
    paso = 0
    try:
        for actualizacion in grafo.stream(estado_inicial, config, stream_mode="updates"):
            for nodo, cambios in actualizacion.items():
                if nodo == "__interrupt__":
                    continue
                paso += 1
                rol = ROL_NODO.get(nodo, nodo)
                detalle = _resumen_nodo(nodo, cambios or {})
                print(f"[{paso:03d}] {nodo:20} {rol}\n      └─ {detalle}")
    except KeyboardInterrupt:
        print("\n[ejecución interrumpida por el usuario]")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\n[error] El pipeline falló tras {paso} paso(s): {exc}", file=sys.stderr)
        return 1

    print("-" * 70)
    print(f"Pipeline terminado: {paso} nodo(s) ejecutado(s).")
    return 0


# =========================================================================
# Main
# =========================================================================


def main() -> int:
    args = _parse_args()

    if args.list_projects or not args.modo:
        if not args.list_projects:
            print("Falta el subcomando: 'diagrama' o 'stream'. Usa -h para ayuda.",
                  file=sys.stderr)
            return 2
        print("Proyectos disponibles:")
        for proyecto in list_projects():
            print(f"  {proyecto.project_id:12} {proyecto.brand_name}: {proyecto.default_topic}")
        return 0

    try:
        if args.modo == "diagrama":
            return modo_diagrama(args)
        return modo_stream(args)
    except (RuntimeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

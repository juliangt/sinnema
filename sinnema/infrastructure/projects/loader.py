"""Cargador de proyectos desde archivos TOML (adaptador de infraestructura).

Cada proyecto (show) es un ``<id>.toml`` dentro del directorio de proyectos.
Este módulo solo se ocupa del I/O: parsear TOML y descubrir archivos; el
significado y la validación de los datos viven en
``sinnema.application.projects.project_from_dict``.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import List

from sinnema.application.projects import ProjectSpec, project_from_dict

def _resolve_projects_dir() -> Path:
    """Directorio de proyectos en cascada: env var > repo > paquete instalado."""
    import os

    env = os.environ.get("SINNEMA_PROJECTS_DIR")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[3] / "proyectos"
    if repo.is_dir():
        return repo
    empaquetado = Path(__file__).resolve().parents[2] / "proyectos"
    return empaquetado if empaquetado.is_dir() else repo


#: Directorio de proyectos por defecto, resuelto al importar.
DEFAULT_PROJECTS_DIR = _resolve_projects_dir()


def list_projects(directorio: Path = DEFAULT_PROJECTS_DIR) -> List[ProjectSpec]:
    """Carga todos los proyectos válidos del directorio (orden alfabético)."""
    archivos = sorted(Path(directorio).glob("*.toml"))
    return [project_from_dict(tomllib.loads(p.read_text(encoding="utf-8"))) for p in archivos]


def load_project(
    project_id: str, directorio: Path = DEFAULT_PROJECTS_DIR
) -> ProjectSpec:
    """Carga un proyecto por id; error accionable si no existe o es inválido."""
    disponibles = [p.stem for p in sorted(Path(directorio).glob("*.toml"))]
    ruta = Path(directorio) / f"{project_id}.toml"
    if not ruta.exists():
        raise RuntimeError(
            f"No existe el proyecto '{project_id}' (buscado en {ruta}). "
            f"Proyectos disponibles: {', '.join(disponibles) or '(ninguno)'}."
        )
    try:
        datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"No se pudo leer el proyecto '{project_id}' ({ruta}): {exc}.") from exc
    try:
        return project_from_dict(datos)
    except ValueError as exc:
        raise RuntimeError(f"El proyecto '{project_id}' es inválido ({ruta}): {exc}") from exc

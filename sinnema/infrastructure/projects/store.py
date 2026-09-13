"""Almacén de proyectos respaldado en archivos TOML (CRUD para la web).

Los archivos son la fuente de verdad: la web lee y escribe ``<id>.toml`` en el
directorio escribible, con escritura atómica (temporal + ``os.replace``) para
que un lector nunca vea un archivo a medias.

El listado fusiona el directorio escribible con los shows empaquetados de solo
lectura (el escribible gana por id): editar un show de muestra escribe una
copia local, y borrarla restaura el empaquetado.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

import tomli_w

from sinnema.application.projects import ProjectSpec, project_from_dict

#: Secciones válidas de un archivo de proyecto (también a nivel raíz).
SECCIONES_VALIDAS = frozenset(
    {"proyecto", "voz", "visual", "formato", "agentes", "pipeline", "flujo", "media"}
)


def resolve_writable_projects_dir(data_dir: Optional[Path] = None) -> Path:
    """Directorio escribible para proyectos: env > repo > <data_dir>/proyectos.

    Con ``SINNEMA_PROJECTS_DIR`` se respeta explícito (creándolo si falta);
    si no, se usa ``proyectos/`` del repo mientras sea escribible, y como
    último recurso un directorio dentro de la raíz de datos del servicio.
    """
    env = os.environ.get("SINNEMA_PROJECTS_DIR")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[3] / "proyectos"
    if repo.is_dir() and os.access(repo, os.W_OK):
        return repo
    data = Path(data_dir) if data_dir is not None else Path("datos-servidor")
    return data / "proyectos"


def packaged_projects_dir() -> Optional[Path]:
    """Shows de muestra empaquetados con la wheel (solo lectura), si existen."""
    empaquetado = Path(__file__).resolve().parents[2] / "proyectos"
    return empaquetado if empaquetado.is_dir() else None


def fingerprint_spec(datos: Dict[str, Any]) -> str:
    """Huella sha256 del spec congelado de un job (spec-red-3d §11.4).

    Canoniza el dict del TOML a su serialización TOML antes de hashear, de
    modo que la misma definición produzca siempre la misma huella; la API la
    recomputa contra el TOML vigente para detectar el spec desfasado.
    """
    import hashlib

    canonico = tomli_w.dumps(datos).encode("utf-8")
    return hashlib.sha256(canonico).hexdigest()


class ProjectFileStore:
    """CRUD de proyectos sobre archivos TOML, con fallback de solo lectura."""

    def __init__(
        self,
        writable_dir: Path,
        builtin_dir: Optional[Path] = None,
    ) -> None:
        self._dir = Path(writable_dir)
        self._builtin = Path(builtin_dir) if builtin_dir else None

    # ------------------------------- lectura -------------------------------

    @property
    def writable_dir(self) -> Path:
        return self._dir

    def _writable_path(self, project_id: str) -> Path:
        return self._dir / f"{project_id}.toml"

    def _builtin_path(self, project_id: str) -> Optional[Path]:
        if self._builtin is None:
            return None
        ruta = self._builtin / f"{project_id}.toml"
        return ruta if ruta.exists() else None

    def _read_path(self, ruta: Path, project_id: str) -> Dict[str, Any]:
        try:
            return tomllib.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise RuntimeError(
                f"No se pudo leer el proyecto '{project_id}' ({ruta}): {exc}."
            ) from exc

    def exists(self, project_id: str) -> bool:
        return self._writable_path(project_id).exists() or (
            self._builtin_path(project_id) is not None
        )

    def is_editable(self, project_id: str) -> bool:
        """True si el proyecto vive en el directorio escribible."""
        return self._writable_path(project_id).exists()

    def read_raw(self, project_id: str) -> Dict[str, Any]:
        """Dict crudo con la forma del TOML (claves en español) para el editor."""
        if self._writable_path(project_id).exists():
            return self._read_path(self._writable_path(project_id), project_id)
        builtin = self._builtin_path(project_id)
        if builtin is not None:
            return self._read_path(builtin, project_id)
        raise FileNotFoundError(
            f"No existe el proyecto '{project_id}' "
            f"(buscado en {self._writable_path(project_id)})."
        )

    def load(self, project_id: str) -> ProjectSpec:
        """Carga y valida el proyecto (escribible primero, luego empaquetado)."""
        try:
            return project_from_dict(self.read_raw(project_id))
        except ValueError as exc:
            raise RuntimeError(
                f"El proyecto '{project_id}' es inválido: {exc}"
            ) from exc

    def list_merged(self) -> List[ProjectSpec]:
        """Todos los proyectos válidos: escribibles + empaquetados, sin repetir."""
        vistos: set[str] = set()
        proyectos: List[ProjectSpec] = []
        for directorio in (self._dir, self._builtin):
            if directorio is None or not directorio.is_dir():
                continue
            for ruta in sorted(directorio.glob("*.toml")):
                if ruta.stem in vistos:
                    continue
                try:
                    proyectos.append(project_from_dict(self._read_path(ruta, ruta.stem)))
                    vistos.add(ruta.stem)
                except (ValueError, RuntimeError):
                    continue  # un archivo roto no esconde a los demás
        return proyectos

    # ------------------------------ escritura ------------------------------

    def _validate(self, datos: Dict[str, Any]) -> ProjectSpec:
        desconocidas = sorted(set(datos) - SECCIONES_VALIDAS)
        if desconocidas:
            raise ValueError(
                f"Secciones desconocidas en el proyecto: {desconocidas} "
                f"(válidas: {', '.join(sorted(SECCIONES_VALIDAS))})."
            )
        return project_from_dict(datos)

    @staticmethod
    def _write_atomic(ruta: Path, datos: Dict[str, Any]) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_name(ruta.name + ".tmp")
        temporal.write_bytes(tomli_w.dumps(datos).encode("utf-8"))
        os.replace(temporal, ruta)

    def create(self, datos: Dict[str, Any]) -> ProjectSpec:
        """Valida y persiste un proyecto nuevo (409-lógico si ya existe)."""
        spec = self._validate(datos)
        ruta = self._writable_path(spec.project_id)
        if ruta.exists():
            raise FileExistsError(
                f"Ya existe un proyecto '{spec.project_id}' en {ruta}."
            )
        self._write_atomic(ruta, datos)
        return spec

    def update(self, project_id: str, datos: Dict[str, Any]) -> ProjectSpec:
        """Sobreescribe un proyecto existente; el id es inmutable."""
        spec = self._validate(datos)
        if spec.project_id != project_id:
            raise ValueError(
                f"El id del proyecto es inmutable: la ruta declara '{project_id}' "
                f"pero el cuerpo declara '{spec.project_id}'."
            )
        if not self.exists(project_id):
            raise FileNotFoundError(
                f"No existe el proyecto '{project_id}' "
                f"(buscado en {self._writable_path(project_id)})."
            )
        # Si el original era un show empaquetado de solo lectura, la edición
        # escribe la copia local del directorio escribible (override).
        self._write_atomic(self._writable_path(project_id), datos)
        return spec

    def delete(self, project_id: str) -> None:
        """Borra el archivo escribible; los jobs históricos se conservan."""
        ruta = self._writable_path(project_id)
        if not ruta.exists():
            raise FileNotFoundError(
                f"No existe el proyecto editable '{project_id}' en {ruta}."
            )
        ruta.unlink()

"""Almacén de la biblioteca de recursos ancla por proyecto (AnchorStorePort).

Cada proyecto persiste su biblioteca en ``<raíz>/<project_id>/anclas.json`` y
los archivos de media de cada batería en ``<raíz>/<project_id>/<ancla_id>/``.

Semántica de fallo (spec-recursos-ancla §4.2): la lectura de un archivo
corrupto falla en voz alta y la ESCRITURA también — a diferencia del lore,
cuya escritura es best-effort porque nace de la corrida, la biblioteca de
anclas se escribe desde acciones humanas de la UI/API (y la persistencia de
vigencia de fin de corrida, que degrada con aviso en ``GenerateSeriesUseCase``):
un fallo de disco es un error accionable, nunca una pérdida silenciosa de la
biblioteca.

Al guardar se verifican las unicidades del proyecto (``ancla_id`` y ``nombre``
case-insensitive) y se aplica la regla de versionado §4.1: cambiar la batería
de una ancla lockeada sube su ``version``; lo ya generado conserva el manifest
con la versión usada.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

from pydantic import ValidationError

from sinnema.domain.models import RecursoAncla
from sinnema.domain.models.anclas import ANCLA_ID_PATTERN

logger = logging.getLogger("sinnema.anclas")

DEFAULT_ANCHAS_ROOT = Path("anclas")

#: Slug de proyecto: misma regla que ``application.projects`` (nombra carpetas
#: en disco; aquí se re-valida porque también compone rutas de serving).
_PROJECT_ID_PATTERN = ANCLA_ID_PATTERN


def _huella_bateria(ancla: RecursoAncla) -> list:
    """Identidad de la batería: la lista (rol, archivo) en orden."""
    return [(imagen.rol, imagen.archivo) for imagen in ancla.bateria]


class JsonAnchorStore:
    """Persiste la biblioteca de anclas de cada proyecto como lista JSON."""

    def __init__(self, root: Path = DEFAULT_ANCHAS_ROOT) -> None:
        self._root = Path(root)

    def _ruta(self, project_id: str) -> Path:
        return self._ruta_proyecto(project_id) / "anclas.json"

    def _ruta_proyecto(self, project_id: str) -> Path:
        if not _PROJECT_ID_PATTERN.match(project_id or ""):
            raise ValueError(
                f"project_id debe ser un slug ([a-z0-9-], recibido: '{project_id}')."
            )
        return self._root / project_id

    def load(self, project_id: str) -> List[RecursoAncla]:
        ruta = self._ruta(project_id)
        if not ruta.exists():
            return []
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            anclas = [RecursoAncla.model_validate(d) for d in datos]
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(
                f"La biblioteca de anclas del proyecto '{project_id}' está "
                f"corrupta ({ruta}): {exc}. Revísala o restáurala antes de "
                "generar; una corrida no debe silenciar la pérdida de la "
                "biblioteca visual."
            ) from exc
        return anclas

    def save(self, project_id: str, anclas: List[RecursoAncla]) -> None:
        self._rechazar_duplicados(anclas)
        ruta = self._ruta(project_id)
        # El versionado de lockeadas compara contra lo persistido: si el
        # archivo está corrupto se aborta en voz alta en vez de pisarlo sin
        # haber visto nunca la biblioteca anterior.
        previas = {
            ancla.ancla_id: ancla for ancla in self.load(project_id)
        }
        for ancla in anclas:
            previa = previas.get(ancla.ancla_id)
            if (
                ancla.estado == "lockeado"
                and previa is not None
                and previa.estado == "lockeado"
                and _huella_bateria(ancla) != _huella_bateria(previa)
            ):
                ancla.version = previa.version + 1
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(
                json.dumps(
                    [a.model_dump(mode="json") for a in anclas],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise RuntimeError(
                f"No se pudo persistir la biblioteca de anclas del proyecto "
                f"'{project_id}' ({ruta}): {exc}. La biblioteca en memoria "
                "queda sin guardar: revisá el disco y volvé a intentar la "
                "operación antes de seguir editando."
            ) from exc

    @staticmethod
    def _rechazar_duplicados(anclas: List[RecursoAncla]) -> None:
        """Unicidad dentro del proyecto: ``ancla_id`` y ``nombre`` (case-insensitive)."""
        ids_vistos = set()
        nombres_vistos = set()
        for ancla in anclas:
            if ancla.ancla_id in ids_vistos:
                raise ValueError(
                    f"ancla_id duplicado en el proyecto: '{ancla.ancla_id}' "
                    "(cada ancla necesita un slug único)."
                )
            ids_vistos.add(ancla.ancla_id)
            nombre = ancla.nombre.casefold()
            if nombre in nombres_vistos:
                raise ValueError(
                    f"nombre de ancla duplicado en el proyecto: '{ancla.nombre}' "
                    "(los nombres son únicos sin distinguir mayúsculas)."
                )
            nombres_vistos.add(nombre)

    def carpeta_de_ancla(self, project_id: str, ancla_id: str) -> Path:
        """Carpeta de batería del ancla: ``<raíz>/<project_id>/<ancla_id>``.

        Los archivos de media viven aplanados ahí (``<rol>_<n>.<ext>``, Fase 1
        los sube); sirve de raíz para las validaciones de serving.
        """
        if not ANCLA_ID_PATTERN.match(ancla_id or ""):
            raise ValueError(
                f"ancla_id debe ser un slug ([a-z0-9-], recibido: '{ancla_id}')."
            )
        return self._ruta_proyecto(project_id) / ancla_id

    def ruta_imagen(self, project_id: str, ancla_id: str, archivo: str) -> Path:
        """Ruta absoluta y validada de un archivo de batería (serving Fase 1).

        Anti path-traversal (spec-recursos-ancla §14): nombre de archivo plano
        (sin separadores ni ``..``) y contención real bajo la carpeta del
        ancla tras resolver symlinks; un symlink que escape de la raíz se
        rechaza.
        """
        limpio = (archivo or "").strip()
        if (
            not limpio
            or "/" in limpio
            or "\\" in limpio
            or limpio in (".", "..")
            or limpio.startswith(".")
        ):
            raise ValueError(
                f"El archivo pedido no es un nombre simple dentro de la "
                f"carpeta del ancla (recibido: '{archivo}')."
            )
        carpeta = self.carpeta_de_ancla(project_id, ancla_id).resolve()
        destino = (carpeta / limpio).resolve()
        if not destino.is_relative_to(carpeta):
            raise ValueError(
                f"El archivo pedido escapa de la carpeta del ancla "
                f"(recibido: '{archivo}')."
            )
        return destino

    def guardar_imagen(
        self, project_id: str, ancla_id: str, archivo: str, datos: bytes
    ) -> Path:
        """Escribe los bytes de una imagen de batería en su ruta validada.

        La ruta pasa por ``ruta_imagen`` (anti path-traversal §14); el nombre
        de archivo lo genera siempre el servidor (``<rol>_<n>.<ext>`` en la
        capa API), nunca el cliente.
        """
        destino = self.ruta_imagen(project_id, ancla_id, archivo)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
        return destino

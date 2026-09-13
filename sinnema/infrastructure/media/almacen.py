"""Almacén de media del pipeline (``MediaStorePort``): keyframes en disco.

Naming (spec-recursos-ancla §6, decisión de la Fase 3): cada keyframe vive en
``<raíz>/<project_id>/<chapter_id>/escena_<n>.<ext>`` con ``raíz`` = ``media/``
bajo el directorio de datos del servicio (o CWD en CLI), espejo de cómo
``anclas/``, ``continuidad/`` y ``auditoria/`` cuelgan de la misma raíz.
``MediaGenerado.archivo`` guarda la ruta RELATIVA a la raíz (portable, sobrevive
a cambios de ``SINNEMA_DATA_DIR``). Validación anti path-traversal con la misma
filosofía del serving de anclas (Fase 1): slugs validados y contención real
tras resolver symlinks.
"""
from __future__ import annotations

from pathlib import Path

from sinnema.domain.models.anclas import ANCLA_ID_PATTERN

#: Raíz por defecto del media de pipeline (bajo el directorio de datos).
DEFAULT_MEDIA_ROOT = Path("media")

CHAPTER_ID_PATTERN = ANCLA_ID_PATTERN  # chapter_id normalizado: mismo slug
FORMATOS_DE_IMAGEN = frozenset({"png", "jpeg", "webp"})


class AlmacenMedia:
    """Escribe los keyframes del pipeline y devuelve su ruta relativa."""

    def __init__(self, root: Path = DEFAULT_MEDIA_ROOT) -> None:
        self._root = Path(root)

    def guardar_keyframe(
        self,
        project_id: str,
        chapter_id: str,
        escena: int,
        formato: str,
        datos: bytes,
    ) -> str:
        """Persiste el keyframe y devuelve su ruta relativa bajo la raíz."""
        relativa = f"{project_id}/{chapter_id}/escena_{escena}.{formato}"
        destino = self.ruta_de(relativa)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
        return relativa

    def ruta_de(self, relativa: str) -> Path:
        """Ruta absoluta validada de un archivo de media (anti traversal).

        Acepta solo la forma ``<project>/<chapter>/escena_<n>.<ext>`` que este
        almacén genera; un symlink que escape de la raíz se rechaza.
        """
        partes = [p for p in relativa.split("/") if p]
        if len(partes) != 3:
            raise ValueError(
                f"Ruta de media inválida (se espera "
                f"<project_id>/<chapter_id>/escena_<n>.<ext>): '{relativa}'."
            )
        project_id, chapter_id, nombre = partes
        if not ANCLA_ID_PATTERN.match(project_id or ""):
            raise ValueError(
                f"project_id debe ser un slug ([a-z0-9-], recibido: '{project_id}')."
            )
        if not CHAPTER_ID_PATTERN.match(chapter_id or ""):
            raise ValueError(
                f"chapter_id debe ser un slug ([a-z0-9-], recibido: '{chapter_id}')."
            )
        prefijo, _, extension = nombre.rpartition(".")
        if not prefijo.startswith("escena_") or not prefijo[len("escena_"):].isdigit():
            raise ValueError(
                f"Nombre de keyframe inválido (se espera escena_<n>.<ext>): '{nombre}'."
            )
        if extension not in FORMATOS_DE_IMAGEN:
            raise ValueError(
                f"Formato de keyframe no soportado: '{extension}' "
                f"(aceptados: {', '.join(sorted(FORMATOS_DE_IMAGEN))})."
            )
        raiz = self._root.resolve()
        destino = (raiz / project_id / chapter_id / nombre).resolve()
        if not destino.is_relative_to(raiz):
            raise ValueError(
                f"La ruta de media escapa de la raíz: '{relativa}'."
            )
        return destino

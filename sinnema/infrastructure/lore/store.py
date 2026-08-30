"""Almacén de lore por proyecto en JSON (implementa LoreStorePort).

Cada proyecto persiste su memoria de continuidad en
``<raíz>/<project_id>/lore.json``. La lectura de un archivo corrupto falla en
voz alta (el lore es historia valiosa: mejor abortar que perderla en silencio);
la escritura es best-effort, como la auditoría: nunca tumba una corrida que ya
produjo episodios.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

from pydantic import ValidationError

from sinnema.domain.models import LoreEntry

logger = logging.getLogger("sinnema.lore")

DEFAULT_LORE_ROOT = Path("continuidad")


class JsonLoreStore:
    """Persiste el lore de cada proyecto como una lista JSON en disco."""

    def __init__(self, root: Path = DEFAULT_LORE_ROOT) -> None:
        self._root = Path(root)

    def _ruta(self, project_id: str) -> Path:
        return self._root / project_id / "lore.json"

    def load(self, project_id: str) -> List[LoreEntry]:
        ruta = self._ruta(project_id)
        if not ruta.exists():
            return []
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            entradas = [LoreEntry.model_validate(d) for d in datos]
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(
                f"El lore persistido del proyecto '{project_id}' está corrupto "
                f"({ruta}): {exc}. Revísalo o restauralo antes de generar; una "
                "corrida no debe silenciar la pérdida de continuidad."
            ) from exc
        return entradas

    def save(self, project_id: str, entries: List[LoreEntry]) -> None:
        ruta = self._ruta(project_id)
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(
                json.dumps(
                    [e.model_dump(mode="json") for e in entries],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning(
                "No se pudo persistir el lore del proyecto '%s' (%s): %s. "
                "La corrida continúa; el lore vive en la auditoría y el entregable.",
                project_id, ruta, exc,
            )

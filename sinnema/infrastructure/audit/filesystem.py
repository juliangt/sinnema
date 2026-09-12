"""Pista de auditoría en sistema de archivos: una carpeta de texto por ejecución.

Cada ejecución del pipeline crea su carpeta (p. ej. ``auditoria/serie_<ts>/``)
con dos tipos de archivos de texto plano:

- ``log.txt``: log cronológico con marca de tiempo de todo lo que ocurre,
- ``NNN_<paso>.txt``: un archivo por paso completado, con su descripción,
  detalles y el artefacto generado volcado en JSON.

La auditoría es best-effort: si el filesystem falla se desactiva con un
warning y el pipeline continúa.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from pydantic import BaseModel

logger = logging.getLogger("sinnema.infrastructure.audit")

_LOG_NAME = "log.txt"


def _slug(texto: str) -> str:
    """Sanitiza el nombre de un paso para usarlo como nombre de archivo."""
    limpio = re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")
    return limpio[:40] or "paso"


class FilesystemAuditTrail:
    """Implementa ``AuditTrailPort`` escribiendo archivos de texto plano."""

    def __init__(self, run_dir: Path) -> None:
        self._dir = Path(run_dir)
        self._counter = 0
        self._activo = True
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._append_log(f"Carpeta de auditoría de la ejecución: {self._dir.resolve()}")
        except OSError as exc:
            self._activo = False
            logger.warning(
                "Auditoría desactivada: no se pudo crear %s (%s).", run_dir, exc
            )

    # ------------------------------ API del puerto ------------------------------

    def log_step(
        self,
        step: str,
        summary: str,
        artifact: Optional[BaseModel] = None,
        details: Optional[Sequence[str]] = None,
    ) -> None:
        if not self._activo:
            return
        self._counter += 1
        nombre = f"{self._counter:03d}_{_slug(step)}.txt"
        lineas = [
            f"Paso {self._counter:03d} · {step}",
            f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            summary,
        ]
        if details:
            lineas += ["", *(f"· {detalle}" for detalle in details)]
        if artifact is not None:
            lineas += [
                "",
                "Artefacto generado (JSON):",
                json.dumps(artifact.model_dump(mode="json"), ensure_ascii=False, indent=2),
            ]
        try:
            (self._dir / nombre).write_text("\n".join(lineas) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("Auditoría: no se pudo escribir %s (%s).", nombre, exc)
            return
        resumen_corto = " ".join(summary.split())
        self._append_log(f"paso {self._counter:03d} · {step} — {resumen_corto}")

    def log_event(self, message: str) -> None:
        if self._activo:
            self._append_log(message)

    def log_failure(self, message: str) -> None:
        if self._activo:
            self._append_log(f"ERROR · {message}")

    def log_prompts(self, step: str, contenido: str) -> None:
        """Prompts de un paso de agente (§7.4): ``NNN_<nodo>_prompts.txt``.

        Usa el número del paso que está por escribirse (``counter + 1``) sin
        avanzarlo: el nodo llama a ``log_step`` inmediatamente después de
        generar, así el archivo de prompts queda emparejado con su paso.
        """
        if not self._activo:
            return
        nombre = f"{self._counter + 1:03d}_{_slug(step)}_prompts.txt"
        try:
            (self._dir / nombre).write_text(contenido, encoding="utf-8")
        except OSError as exc:
            logger.warning("Auditoría: no se pudo escribir %s (%s).", nombre, exc)

    # --------------------------------- internals ---------------------------------

    def _append_log(self, message: str) -> None:
        marca = datetime.now().strftime("%H:%M:%S")
        try:
            with (self._dir / _LOG_NAME).open("a", encoding="utf-8") as manejador:
                manejador.write(f"[{marca}] {message}\n")
        except OSError as exc:
            self._activo = False
            logger.warning(
                "Auditoría desactivada: no se pudo escribir en %s (%s).", _LOG_NAME, exc
            )

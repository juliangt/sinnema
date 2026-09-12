"""Almacén de trabajos de generación en SQLite (adaptador de persistencia).

Cada generación de serie es un *job* asíncrono: la API lo crea, un worker lo
procesa y cualquier cliente consulta su estado, su bitácora de progreso y su
entregable. El campo ``owner`` permite aislar los trabajos por usuario
(multi-tenant básico); la autenticación real queda aguas abajo.

El store es thread-safe: la API (event loop) y el worker (thread propio)
comparten la misma base con un lock y una única conexión.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED}


@dataclass
class JobEvent:
    """Un latido de progreso dentro de la ejecución de un job.

    ``payload`` (spec-red-3d §6.1) transporta el detalle estructurado de los
    kinds nuevos (``node_start``/``node_end``/``token``/``tool_*``); es
    ``None`` en los eventos legacy (``progress``/``error``/``done``) y en los
    registros previos a la migración, que siguen legibles como solo texto.
    """

    id: int
    job_id: str
    ts: str
    kind: str  # "progress" | "error" | "done" | "node_start" | "node_end" | ...
    message: str
    payload: Optional[dict] = None


@dataclass
class Job:
    """Estado completo de una generación de serie solicitada a la API."""

    job_id: str
    owner: str
    project_id: str
    topic: str
    num_chapters: int
    max_critique_attempts: int
    status: JobStatus
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    deliverable: Optional[dict] = field(default=None)
    #: Huella sha256 del spec congelado al arrancar (spec-red-3d §11.4); la
    #: API la compara contra el TOML vigente para calcular ``spec_desfasado``.
    spec_fingerprint: Optional[str] = None

    def to_dict(self, with_deliverable: bool = True) -> dict:
        datos = {
            "job_id": self.job_id,
            "owner": self.owner,
            "project_id": self.project_id,
            "topic": self.topic,
            "num_chapters": self.num_chapters,
            "max_critique_attempts": self.max_critique_attempts,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }
        if with_deliverable:
            datos["deliverable"] = self.deliverable
        return datos


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SqliteJobStore:
    """Persiste jobs y eventos de progreso en una base SQLite única."""

    def __init__(self, db_path: Path | str) -> None:
        self._lock = threading.Lock()
        ruta = Path(db_path)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(ruta), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    num_chapters INTEGER NOT NULL,
                    max_critique_attempts INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error TEXT,
                    deliverable TEXT
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_eventos_job
                    ON job_events(job_id, id);
                """
            )
            # Migración aditiva e idempotente (spec-red-3d §6.1, §12.1): las
            # ALTERs solo se aplican si la columna falta, de modo que bases
            # existentes de datos-servidor/ siguen operativas.
            columnas_jobs = {
                f["name"]
                for f in self._conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "spec_fingerprint" not in columnas_jobs:
                self._conn.execute(
                    "ALTER TABLE jobs ADD COLUMN spec_fingerprint TEXT"
                )
            columnas_eventos = {
                f["name"]
                for f in self._conn.execute("PRAGMA table_info(job_events)").fetchall()
            }
            if "payload" not in columnas_eventos:
                self._conn.execute(
                    "ALTER TABLE job_events ADD COLUMN payload TEXT"
                )

    # --------------------------------- jobs ---------------------------------

    def create_job(
        self,
        owner: str,
        project_id: str,
        topic: str,
        num_chapters: int,
        max_critique_attempts: int,
    ) -> Job:
        job = Job(
            job_id=uuid.uuid4().hex[:12],
            owner=owner,
            project_id=project_id,
            topic=topic,
            num_chapters=num_chapters,
            max_critique_attempts=max_critique_attempts,
            status=JobStatus.QUEUED,
            created_at=_now(),
        )
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO jobs (job_id, owner, project_id, topic,"
                " num_chapters, max_critique_attempts, status, created_at,"
                " started_at, finished_at, error, deliverable)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job.job_id, job.owner, job.project_id, job.topic,
                    job.num_chapters, job.max_critique_attempts,
                    job.status.value, job.created_at,
                    None, None, None, None,
                ),
            )
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            fila = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(fila) if fila else None

    def list_jobs(
        self,
        owner: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[Job]:
        consulta = "SELECT * FROM jobs"
        condiciones: List[str] = []
        params: list = []
        if owner is not None:
            condiciones.append("owner = ?")
            params.append(owner)
        if project_id is not None:
            condiciones.append("project_id = ?")
            params.append(project_id)
        if condiciones:
            consulta += " WHERE " + " AND ".join(condiciones)
        consulta += " ORDER BY created_at DESC"
        with self._lock:
            filas = self._conn.execute(consulta, tuple(params)).fetchall()
        return [self._row_to_job(f) for f in filas]

    def set_status(
        self,
        job_id: str,
        status: JobStatus,
        error: Optional[str] = None,
        deliverable: Optional[dict] = None,
    ) -> None:
        assignments = ["status = ?"]
        params: list = [status.value]
        if status is JobStatus.RUNNING:
            assignments.append("started_at = ?")
            params.append(_now())
        if status in TERMINAL_STATUSES:
            assignments.append("finished_at = ?")
            params.append(_now())
        if error is not None:
            assignments.append("error = ?")
            params.append(error)
        if deliverable is not None:
            assignments.append("deliverable = ?")
            params.append(json.dumps(deliverable, ensure_ascii=False))
        params.append(job_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE jobs SET {', '.join(assignments)} WHERE job_id = ?",
                params,
            )

    # -------------------------------- eventos --------------------------------

    def add_event(
        self,
        job_id: str,
        kind: str,
        message: str,
        payload: Optional[dict] = None,
    ) -> None:
        """Registra un evento; ``payload`` (§6.1) es opcional y solo lo
        traen los kinds estructurados. La firma anterior queda intacta."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO job_events (job_id, ts, kind, message, payload)"
                " VALUES (?,?,?,?,?)",
                (
                    job_id, _now(), kind, message,
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                ),
            )

    def events_since(self, job_id: str, last_id: int = 0) -> List[JobEvent]:
        with self._lock:
            filas = self._conn.execute(
                "SELECT * FROM job_events WHERE job_id = ? AND id > ? ORDER BY id",
                (job_id, last_id),
            ).fetchall()
        return [
            JobEvent(
                id=f["id"], job_id=f["job_id"], ts=f["ts"],
                kind=f["kind"], message=f["message"],
                payload=json.loads(f["payload"]) if f["payload"] else None,
            )
            for f in filas
        ]

    # ------------------------------ fingerprint ------------------------------

    def set_spec_fingerprint(self, job_id: str, fingerprint: str) -> None:
        """Congela en el job la huella del spec con el que arrancó (§11.4)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE jobs SET spec_fingerprint = ? WHERE job_id = ?",
                (fingerprint, job_id),
            )

    # ------------------------------- internals -------------------------------

    @staticmethod
    def _row_to_job(f: sqlite3.Row) -> Job:
        return Job(
            job_id=f["job_id"],
            owner=f["owner"],
            project_id=f["project_id"],
            topic=f["topic"],
            num_chapters=f["num_chapters"],
            max_critique_attempts=f["max_critique_attempts"],
            status=JobStatus(f["status"]),
            created_at=f["created_at"],
            started_at=f["started_at"],
            finished_at=f["finished_at"],
            error=f["error"],
            deliverable=json.loads(f["deliverable"]) if f["deliverable"] else None,
            spec_fingerprint=f["spec_fingerprint"],
        )

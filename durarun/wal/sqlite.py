"""SQLite-backed WAL implementation (Layer 1 — zero external dependencies)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

from .protocol import RunInfo, StepRecord

_CREATE_TABLES = """\
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    status     TEXT    NOT NULL DEFAULT 'running',
    steps_total INTEGER,
    created_at REAL    NOT NULL,
    updated_at REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS steps (
    run_id      TEXT NOT NULL,
    step_name   TEXT NOT NULL,
    result      TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    timestamp   REAL NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_steps_run_id ON steps(run_id);
"""


class SqliteWAL:
    """WAL backend that persists data to a local SQLite database.

    Designed for single-machine, single- or multi-threaded use.
    Uses SQLite WAL journal mode with ``synchronous=FULL`` so that
    ``fsync()`` guarantees crash-safe durability.
    """

    def __init__(self, db_path: str = "./durarun.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_CREATE_TABLES)
        self._conn.commit()

    # ------------------------------------------------------------------
    # WALBackend interface
    # ------------------------------------------------------------------

    def append(
        self,
        run_id: str,
        step_name: str,
        result: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a step result.  Registers the run on first call."""
        now = time.time()
        metadata = metadata or {}
        duration_ms = metadata.get("duration_ms", 0.0)
        timestamp = metadata.get("timestamp", now)
        result_json = json.dumps(result, ensure_ascii=False)
        metadata_json = json.dumps(metadata, ensure_ascii=False)

        with self._lock:
            # Ensure the run exists in the runs table.
            self._conn.execute(
                "INSERT OR IGNORE INTO runs (run_id, created_at, updated_at) "
                "VALUES (?, ?, ?)",
                (run_id, now, now),
            )
            self._conn.execute(
                "INSERT INTO steps (run_id, step_name, result, duration_ms, timestamp, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, step_name, result_json, duration_ms, timestamp, metadata_json),
            )
            self._conn.execute(
                "UPDATE runs SET updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )
            self._conn.commit()

    def read(self, run_id: str) -> list[StepRecord]:
        """Read back all step records for a given run, in insertion order."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT step_name, result, duration_ms, timestamp, metadata "
                "FROM steps WHERE run_id = ? ORDER BY rowid",
                (run_id,),
            )
            rows = cursor.fetchall()

        records: list[StepRecord] = []
        for step_name, result_json, duration_ms, timestamp, metadata_json in rows:
            records.append(
                StepRecord(
                    step_name=step_name,
                    result=json.loads(result_json),
                    duration_ms=duration_ms,
                    timestamp=timestamp,
                    metadata=json.loads(metadata_json),
                )
            )
        return records

    def mark_complete(self, run_id: str) -> None:
        """Mark the run as completed."""
        now = time.time()
        with self._lock:
            self._conn.execute(
                "UPDATE runs SET status = 'completed', updated_at = ? WHERE run_id = ?",
                (now, run_id),
            )

    def list_incomplete(self) -> list[RunInfo]:
        """Return info for every run still in 'running' state."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT r.run_id, r.steps_total, r.created_at, r.updated_at, "
                "       COUNT(s.rowid) AS steps_done, "
                "       ( SELECT s2.step_name FROM steps s2 "
                "         WHERE s2.run_id = r.run_id ORDER BY s2.rowid DESC LIMIT 1 "
                "       ) AS last_step "
                "FROM runs r "
                "LEFT JOIN steps s ON s.run_id = r.run_id "
                "WHERE r.status = 'running' "
                "GROUP BY r.run_id",
            )
            rows = cursor.fetchall()

        infos: list[RunInfo] = []
        for run_id, steps_total, created_at, updated_at, steps_done, last_step in rows:
            infos.append(
                RunInfo(
                    run_id=run_id,
                    steps_done=steps_done,
                    steps_total=steps_total,
                    last_step=last_step,
                    created_at=created_at,
                    updated_at=updated_at,
                )
            )
        return infos

    def fsync(self) -> None:
        """Commit the current transaction, forcing a disk flush (synchronous=FULL)."""
        with self._lock:
            self._conn.commit()

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass

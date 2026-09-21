"""Pure in-memory WAL backend for testing and development."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .protocol import RunInfo, StepRecord


@dataclass
class _RunState:
    """Internal bookkeeping for a single run."""

    status: str = "running"
    steps: list[StepRecord] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0


class MemoryWAL:
    """WAL backend that stores everything in memory.

    Useful for unit tests and short-lived development sessions where
    durability is not required.  All data is lost when the process exits.
    Thread-safe via a simple :class:`threading.Lock`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, _RunState] = {}

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
        """Store a step result in memory.  Registers the run on first call."""
        now = time.time()
        metadata = metadata or {}
        duration_ms = metadata.get("duration_ms", 0.0)
        timestamp = metadata.get("timestamp", now)

        record = StepRecord(
            step_name=step_name,
            result=result,
            duration_ms=duration_ms,
            timestamp=timestamp,
            metadata=metadata,
        )

        with self._lock:
            if run_id not in self._runs:
                self._runs[run_id] = _RunState(created_at=now, updated_at=now)
            state = self._runs[run_id]
            state.steps.append(record)
            state.updated_at = now

    def read(self, run_id: str) -> list[StepRecord]:
        """Return all step records for *run_id*, in insertion order."""
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                return []
            return list(state.steps)

    def mark_complete(self, run_id: str) -> None:
        """Mark the run as completed."""
        now = time.time()
        with self._lock:
            state = self._runs.get(run_id)
            if state is not None:
                state.status = "completed"
                state.updated_at = now

    def list_incomplete(self) -> list[RunInfo]:
        """Return summary info for every run still in 'running' state."""
        with self._lock:
            infos: list[RunInfo] = []
            for run_id, state in self._runs.items():
                if state.status != "running":
                    continue
                infos.append(
                    RunInfo(
                        run_id=run_id,
                        steps_done=len(state.steps),
                        steps_total=None,
                        last_step=state.steps[-1].step_name if state.steps else None,
                        created_at=state.created_at,
                        updated_at=state.updated_at,
                    )
                )
            return infos

    def fsync(self) -> None:
        """No-op — memory backend has nothing to flush."""

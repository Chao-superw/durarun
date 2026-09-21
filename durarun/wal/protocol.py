"""WAL backend protocol and shared data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class StepRecord:
    """A single persisted step result read back from the WAL."""

    step_name: str
    result: Any
    duration_ms: float
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunInfo:
    """Summary information about a run stored in the WAL."""

    run_id: str
    steps_done: int
    steps_total: int | None
    last_step: str | None
    created_at: float
    updated_at: float


class WALBackend(Protocol):
    """Protocol that every WAL storage backend must satisfy."""

    def append(
        self,
        run_id: str,
        step_name: str,
        result: Any,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append a completed step record to the WAL."""
        ...

    def read(self, run_id: str) -> list[StepRecord]:
        """Return all persisted step records for *run_id*, in insertion order."""
        ...

    def mark_complete(self, run_id: str) -> None:
        """Mark a run as completed so it no longer appears in *list_incomplete*."""
        ...

    def list_incomplete(self) -> list[RunInfo]:
        """Return summary info for every run whose status is still 'running'."""
        ...

    def fsync(self) -> None:
        """Force all buffered writes to durable storage."""
        ...

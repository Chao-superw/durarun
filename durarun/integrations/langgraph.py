"""LangGraph-compatible checkpointer backed by a durarun WALBackend.

This module does **not** import ``langgraph`` — it is an optional dependency.
The :class:`DurarunCheckpointer` exposes the three methods that LangGraph
expects (``get``, ``put``, ``list``) while delegating all persistence to a
:class:`~durarun.wal.protocol.WALBackend` instance.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from durarun.wal.protocol import WALBackend


# ---------------------------------------------------------------------------
# Public data class returned by ``get`` / ``list``
# ---------------------------------------------------------------------------

@dataclass
class CheckpointEntry:
    """A stored checkpoint together with its metadata."""

    checkpoint: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    checkpoint_id: str = ""
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Checkpointer
# ---------------------------------------------------------------------------

_THREAD_PREFIX = "langgraph::checkpoint::"


def _run_id_for(thread_id: str) -> str:
    """Derive a stable WAL ``run_id`` from a LangGraph thread id."""
    return f"{_THREAD_PREFIX}{thread_id}"


class DurarunCheckpointer:
    """A LangGraph-compatible checkpointer backed by a :class:`WALBackend`.

    Usage::

        from durarun.wal import SqliteWAL
        from durarun.integrations.langgraph import DurarunCheckpointer

        wal = SqliteWAL("checkpoints.db")
        checkpointer = DurarunCheckpointer(wal)

        # Then pass *checkpointer* wherever LangGraph expects one.

    Parameters
    ----------
    backend:
        Any object satisfying the :class:`~durarun.wal.protocol.WALBackend`
        protocol.
    """

    def __init__(self, backend: WALBackend) -> None:
        self._backend = backend

    # -- public API expected by LangGraph -----------------------------------

    def get(self, config: Dict[str, Any]) -> Optional[CheckpointEntry]:
        """Return the latest checkpoint for the thread specified in *config*.

        Parameters
        ----------
        config:
            A dict that must contain at least ``"thread_id"``.

        Returns
        -------
        :class:`CheckpointEntry` or ``None`` if no checkpoint exists for
        the thread.
        """
        thread_id: str = config["thread_id"]
        records = self._backend.read(_run_id_for(thread_id))
        if not records:
            return None
        last = records[-1]
        return _record_to_entry(last)

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist a checkpoint for the thread specified in *config*.

        The *checkpoint* dict is serialised to JSON and stored as a WAL step.

        Parameters
        ----------
        config:
            A dict that must contain at least ``"thread_id"``.
        checkpoint:
            Arbitrary JSON-serialisable checkpoint payload.
        metadata:
            Optional metadata to attach to this checkpoint.

        Returns
        -------
        An updated *config* dict that includes the ``checkpoint_id`` of the
        newly stored entry.
        """
        thread_id: str = config["thread_id"]
        checkpoint_id = str(uuid.uuid4())
        now = time.time()

        step_metadata: Dict[str, Any] = {
            "checkpoint_id": checkpoint_id,
            "timestamp": now,
        }
        if metadata:
            step_metadata["user_metadata"] = metadata

        payload = json.dumps(checkpoint, default=str)

        self._backend.append(
            run_id=_run_id_for(thread_id),
            step_name=checkpoint_id,
            result=payload,
            metadata=step_metadata,
        )
        self._backend.fsync()

        return {**config, "checkpoint_id": checkpoint_id}

    def list(self, config: Dict[str, Any]) -> List[CheckpointEntry]:
        """Return all checkpoints for the thread specified in *config*.

        Checkpoints are returned in insertion order (oldest first).

        Parameters
        ----------
        config:
            A dict that must contain at least ``"thread_id"``.
        """
        thread_id: str = config["thread_id"]
        records = self._backend.read(_run_id_for(thread_id))
        return [_record_to_entry(r) for r in records]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _record_to_entry(record: Any) -> CheckpointEntry:
    """Convert a :class:`~durarun.wal.protocol.StepRecord` to a
    :class:`CheckpointEntry`."""
    raw = record.result
    checkpoint = json.loads(raw) if isinstance(raw, str) else raw

    meta = record.metadata or {}
    checkpoint_id = meta.get("checkpoint_id", record.step_name)
    user_metadata = meta.get("user_metadata", {})
    timestamp = meta.get("timestamp", record.timestamp)

    return CheckpointEntry(
        checkpoint=checkpoint,
        metadata=user_metadata,
        checkpoint_id=checkpoint_id,
        timestamp=timestamp,
    )

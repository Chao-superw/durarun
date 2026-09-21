"""DurableRunner — core execution engine for durarun.

Provides the :class:`DurableRunner` class that orchestrates sequential step
execution with WAL-backed crash recovery, automatic retries, timeouts, and
OpenTelemetry tracing.
"""

from __future__ import annotations

import functools
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any, Callable

from durarun.context import Context
from durarun.errors import DurarunError, StepRetryExhausted, StepTimeout
from durarun.observe.tracer import DurarunTracer
from durarun.wal.protocol import RunInfo, StepRecord, WALBackend
from durarun.wal.sqlite import SqliteWAL


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------


@dataclass
class StepDetail:
    """Execution details for a single step within a run."""

    name: str
    result: Any
    duration_ms: float
    source: str  # "wal" or "live"
    retry_count: int


@dataclass
class RunResult:
    """Aggregate result returned by :meth:`DurableRunner.run`."""

    run_id: str
    steps: dict[str, Any] = field(default_factory=dict)
    total_ms: float = 0.0
    recovered_steps: int = 0
    step_details: list[StepDetail] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TIMEOUT_RE = re.compile(
    r"^\s*(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+(?:\.\d+)?)\s*m)?\s*(?:(\d+(?:\.\d+)?)\s*s?)?\s*$",
    re.IGNORECASE,
)

# Key used to stash decorator metadata on step functions.
_META_ATTR = "_durarun_meta"


@dataclass
class _StepMeta:
    """Metadata attached to a step function by the ``@runner.step`` decorator."""

    name: str
    retry: int | None = None
    timeout: str | int | float | None = None


# ---------------------------------------------------------------------------
# DurableRunner
# ---------------------------------------------------------------------------


class DurableRunner:
    """SDK entry-point that drives durable, WAL-backed step execution.

    Parameters
    ----------
    backend:
        URI for the WAL storage backend.  Only ``sqlite://`` is supported in
        this release.  Defaults to ``"sqlite://./durarun.db"``.
    otel_endpoint:
        Optional OTLP/gRPC collector endpoint.  ``None`` selects the built-in
        stdout exporter.
    run_id:
        Explicit run identifier.  When set the runner will attempt to resume
        from existing WAL records for this id.  ``None`` generates a UUID.
    max_retries:
        Default per-step retry limit (can be overridden per step).
    step_timeout:
        Default per-step timeout as an ``int`` (seconds), or a human string
        such as ``"5m"`` or ``"30s"``.
    """

    def __init__(
        self,
        backend: str = "sqlite://./durarun.db",
        otel_endpoint: str | None = None,
        run_id: str | None = None,
        max_retries: int = 3,
        step_timeout: str | int = "5m",
    ) -> None:
        self._wal: WALBackend = self._parse_backend(backend)
        self._tracer = DurarunTracer(otel_endpoint=otel_endpoint)
        self._run_id = run_id
        self._max_retries = max_retries
        self._step_timeout = step_timeout
        self._pool = ThreadPoolExecutor(max_workers=4)

    def close(self) -> None:
        """Shut down the shared thread pool."""
        self._pool.shutdown(wait=False)

    # ------------------------------------------------------------------
    # @runner.step decorator
    # ------------------------------------------------------------------

    def step(
        self,
        fn: Callable | None = None,
        *,
        name: str | None = None,
        retry: int | None = None,
        timeout: str | int | None = None,
    ) -> Callable:
        """Register a callable as a durable step.

        Supports both bare ``@runner.step`` and parameterised
        ``@runner.step(retry=3, timeout="2m")`` forms.

        The original function is returned *unwrapped*; the actual
        retry/timeout/WAL logic is applied at :meth:`run` time.
        """

        def _attach(func: Callable) -> Callable:
            step_name = name if name is not None else func.__name__
            setattr(
                func,
                _META_ATTR,
                _StepMeta(name=step_name, retry=retry, timeout=timeout),
            )
            # Preserve introspection metadata on the original callable.
            functools.update_wrapper(func, func)
            return func

        # Called as @runner.step (no parentheses) — *fn* is the decorated
        # function itself.
        if fn is not None:
            return _attach(fn)

        # Called as @runner.step(...) — return the real decorator.
        return _attach

    # ------------------------------------------------------------------
    # run / resume / list_runs
    # ------------------------------------------------------------------

    def run(self, steps: list[Callable]) -> RunResult:
        """Execute *steps* sequentially with WAL recovery.

        Steps whose results already exist in the WAL are skipped (recovered).
        """

        run_id = self._run_id or uuid.uuid4().hex
        self._run_id = run_id
        ctx = Context(task="", run_id=run_id)

        # Start OTEL root span.
        self._tracer.start_run_span(run_id, steps_total=len(steps))

        # Pre-load existing WAL records for this run (single read).
        existing_records = self._wal.read(run_id)
        wal_cache: dict[str, StepRecord] = {}
        for rec in existing_records:
            wal_cache[rec.step_name] = rec
            # Pre-populate context so later steps can reference earlier ones.
            ctx.set(rec.step_name, rec.result)

        result = RunResult(run_id=run_id)
        run_start = time.monotonic()

        try:
            for step_fn in steps:
                meta = self._get_meta(step_fn)
                step_name = meta.name

                max_retries = meta.retry if meta.retry is not None else self._max_retries
                timeout_raw = meta.timeout if meta.timeout is not None else self._step_timeout
                timeout_seconds = self._parse_timeout(timeout_raw) if timeout_raw is not None else None

                step_result, duration_ms, source, retry_count = self._run_step(
                    step_name=step_name,
                    fn=step_fn,
                    ctx=ctx,
                    max_retries=max_retries,
                    timeout_seconds=timeout_seconds,
                    wal_cache=wal_cache,
                )

                result.steps[step_name] = step_result
                detail = StepDetail(
                    name=step_name,
                    result=step_result,
                    duration_ms=duration_ms,
                    source=source,
                    retry_count=retry_count,
                )
                result.step_details.append(detail)

                if source == "wal":
                    result.recovered_steps += 1

                # Trace the step.
                self._tracer.record_step(
                    step_name=step_name,
                    duration_ms=duration_ms,
                    source=source,
                    retry_count=retry_count,
                )
        finally:
            result.total_ms = (time.monotonic() - run_start) * 1000
            self._tracer.finish_run(recovered_steps=result.recovered_steps)

        # Mark run as completed in WAL.
        self._wal.mark_complete(run_id)
        self._wal.fsync()

        result.timeline = self._tracer.get_timeline()

        return result

    def resume(self, steps: list[Callable] | None = None) -> RunResult:
        """Resume the most recent incomplete run.

        If *steps* is ``None`` the caller must have previously registered
        steps via ``@runner.step``; however for the function-list API the
        caller should pass the same step list used for the original run.

        Raises :class:`DurarunError` if no incomplete run can be found.
        """

        if self._run_id is None:
            incomplete = self._wal.list_incomplete()
            if not incomplete:
                raise DurarunError("No incomplete runs found to resume")
            # Pick the most recently updated run.
            latest = max(incomplete, key=lambda r: r.updated_at)
            self._run_id = latest.run_id

        if steps is None:
            raise DurarunError(
                "steps must be provided when using the function-list API"
            )

        return self.run(steps)

    def list_runs(self, status: str | None = None) -> list[RunInfo]:
        """List runs, optionally filtered by *status*.

        Currently only ``"incomplete"`` is a meaningful filter; any other
        value returns an empty list.  ``None`` returns incomplete runs (the
        only queryable set with the WAL protocol).
        """

        if status is None or status == "incomplete":
            return self._wal.list_incomplete()
        return []

    async def arun(self, steps: list[Callable]) -> RunResult:
        """Async version of :meth:`run`. Executes in a thread via asyncio."""
        import asyncio
        return await asyncio.to_thread(self.run, steps)

    # ------------------------------------------------------------------
    # Internal: single-step execution
    # ------------------------------------------------------------------

    def _run_step(
        self,
        step_name: str,
        fn: Callable,
        ctx: Context,
        max_retries: int,
        timeout_seconds: float | None,
        wal_cache: dict[str, StepRecord],
    ) -> tuple[Any, float, str, int]:
        """Execute a single step with WAL recovery, retry, and timeout.

        Returns ``(result, duration_ms, source, retry_count)``.
        """

        # 1. Check WAL cache.
        cached = wal_cache.get(step_name)
        if cached is not None:
            # Context was already populated during the pre-load phase.
            return cached.result, cached.duration_ms, "wal", 0

        # 2. Live execution with retry.
        last_exc: BaseException | None = None
        attempts = max_retries + 1  # first attempt + retries

        for attempt in range(attempts):
            try:
                step_result, duration_ms = self._exec_with_timeout(
                    fn, ctx, step_name, timeout_seconds
                )

                # 3. Persist to WAL.
                self._wal.append(
                    run_id=ctx.run_id,
                    step_name=step_name,
                    result=step_result,
                    metadata={
                        "duration_ms": duration_ms,
                        "timestamp": time.time(),
                    },
                )

                # 4. Update context.
                ctx.set(step_name, step_result)

                return step_result, duration_ms, "live", attempt

            except StepTimeout:
                # Timeouts are not retried — propagate immediately.
                raise

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                # Will retry if attempts remain.

        # All retries exhausted.
        raise StepRetryExhausted(
            step_name=step_name,
            max_retries=max_retries,
            last_exception=last_exc,
        )

    def _exec_with_timeout(
        self,
        fn: Callable,
        ctx: Context,
        step_name: str,
        timeout_seconds: float | None,
    ) -> tuple[Any, float]:
        """Run *fn(ctx)* with an optional timeout.

        Returns ``(result, duration_ms)``.
        """

        start = time.monotonic()

        if timeout_seconds is None:
            # No timeout — run inline.
            result = fn(ctx)
            duration_ms = (time.monotonic() - start) * 1000
            return result, duration_ms

        future = self._pool.submit(fn, ctx)
        try:
            result = future.result(timeout=timeout_seconds)
        except FutureTimeoutError:
            future.cancel()
            raise StepTimeout(
                step_name=step_name,
                timeout_seconds=timeout_seconds,
            ) from None
        duration_ms = (time.monotonic() - start) * 1000
        return result, duration_ms

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_meta(fn: Callable) -> _StepMeta:
        """Retrieve step metadata or synthesise a default from ``fn.__name__``."""
        meta = getattr(fn, _META_ATTR, None)
        if meta is not None:
            return meta
        return _StepMeta(name=fn.__name__)

    @staticmethod
    def _parse_backend(backend: str) -> WALBackend:
        if backend.startswith("memory://"):
            from durarun.wal.memory import MemoryWAL
            return MemoryWAL()

        if backend.startswith("sqlite://"):
            path = backend[len("sqlite://"):]
            return SqliteWAL(db_path=path or "./durarun.db")

        return SqliteWAL(db_path=backend)

    @staticmethod
    def _parse_timeout(timeout: str | int | float) -> float:
        """Convert a timeout value to seconds (float).

        Accepted forms:
        - ``int`` / ``float`` — already seconds
        - ``"30"`` — plain numeric string, seconds
        - ``"30s"`` — seconds
        - ``"5m"`` — minutes
        - ``"1h"`` — hours
        - ``"1h30m"`` — compound
        """

        if isinstance(timeout, (int, float)):
            return float(timeout)

        text = str(timeout).strip()

        # Try plain numeric first.
        try:
            return float(text)
        except ValueError:
            pass

        m = _TIMEOUT_RE.match(text)
        if m is None or not any(m.groups()):
            raise ValueError(f"Invalid timeout format: {timeout!r}")

        hours = float(m.group(1) or 0)
        minutes = float(m.group(2) or 0)
        seconds = float(m.group(3) or 0)
        return hours * 3600 + minutes * 60 + seconds

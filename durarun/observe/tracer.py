"""OTEL tracing wrapper for durarun — lazy-import edition.

``DurarunTracer`` provides a thin, dependency-safe facade over the
OpenTelemetry API. All OpenTelemetry packages are imported lazily.
When none are installed the tracer silently records a timeline without
emitting spans.
"""

from __future__ import annotations

import contextlib
from contextlib import contextmanager
from typing import Any, Iterator

_trace: Any = None
_otel_context: Any = None
_TracerProvider: Any = None
_BatchSpanProcessor: Any = None
_SDK_AVAILABLE: bool | None = None
_API_AVAILABLE: bool | None = None


def _load_otel() -> tuple[Any, Any]:
    global _trace, _otel_context, _TracerProvider, _BatchSpanProcessor
    global _SDK_AVAILABLE, _API_AVAILABLE
    if _API_AVAILABLE is not None:
        return _trace, _otel_context
    try:
        from opentelemetry import trace, context as ctx
        _trace = trace
        _otel_context = ctx
        _API_AVAILABLE = True
    except ImportError:
        _API_AVAILABLE = False
        _SDK_AVAILABLE = False
        return None, None
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        _TracerProvider = TracerProvider
        _BatchSpanProcessor = BatchSpanProcessor
        _SDK_AVAILABLE = True
    except ImportError:
        _SDK_AVAILABLE = False
    return _trace, _otel_context


class DurarunTracer:

    def __init__(
        self,
        service_name: str = "durarun",
        otel_endpoint: str | None = None,
    ) -> None:
        self._service_name = service_name
        self._otel_endpoint = otel_endpoint
        self._disabled = otel_endpoint == "disabled"
        self._provider: Any = None
        self._run_id: str | None = None
        self._tracer: Any = None
        self._run_span: Any = None
        self._run_token: object | None = None
        self._timeline: list[dict] = []
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized or self._disabled:
            return
        self._initialized = True
        trace, _ = _load_otel()
        if trace is None:
            self._disabled = True
            return
        self._setup_provider(self._otel_endpoint)
        self._tracer = trace.get_tracer(
            instrumenting_module_name="durarun",
            tracer_provider=self._provider,
        )

    def _setup_provider(self, otel_endpoint: str | None) -> None:
        if not _SDK_AVAILABLE:
            return
        from opentelemetry.sdk.resources import Resource
        resource = Resource.create({"service.name": self._service_name})
        provider = _TracerProvider(resource=resource)
        exporter = self._build_exporter(otel_endpoint)
        provider.add_span_processor(_BatchSpanProcessor(exporter))
        self._provider = provider

    @staticmethod
    def _build_exporter(otel_endpoint: str | None) -> Any:
        if otel_endpoint is not None:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )
                return OTLPSpanExporter(endpoint=otel_endpoint)
            except ImportError:
                import warnings
                warnings.warn(
                    "opentelemetry-exporter-otlp-proto-grpc is not installed. "
                    "Falling back to StdoutSpanExporter. "
                    "Install with: pip install durarun[otel]",
                    stacklevel=3,
                )
        from durarun.observe.stdout_exporter import StdoutSpanExporter
        return StdoutSpanExporter()

    def start_run_span(self, run_id: str, steps_total: int) -> Any:
        self._run_id = run_id
        self._timeline = []
        if self._disabled:
            return None
        self._ensure_initialized()
        if self._disabled:
            return None

        trace, otel_context = _load_otel()
        span = self._tracer.start_span(
            name="durarun.agent.run",
            attributes={
                "durarun.run_id": run_id,
                "durarun.steps_total": steps_total,
            },
        )
        ctx = trace.set_span_in_context(span)
        self._run_token = otel_context.attach(ctx)
        self._run_span = span
        return span

    def finish_run(self, recovered_steps: int) -> None:
        if self._disabled:
            self._run_id = None
            return
        if self._run_span is None:
            return
        self._run_span.set_attribute("durarun.recovered_steps", recovered_steps)
        self._run_span.end()
        if self._run_token is not None:
            _, otel_context = _load_otel()
            with contextlib.suppress(Exception):
                otel_context.detach(self._run_token)
            self._run_token = None
        self._run_span = None
        self._run_id = None

    def record_step(
        self,
        step_name: str,
        duration_ms: float,
        source: str,
        retry_count: int = 0,
    ) -> None:
        self._timeline.append({
            "step": step_name,
            "duration_ms": duration_ms,
            "source": source,
            "retry_count": retry_count,
        })
        if self._disabled or self._tracer is None:
            return

        span = self._tracer.start_span(
            name=f"durarun.step.{step_name}",
        )
        if self._run_id is not None:
            span.set_attribute("durarun.run_id", self._run_id)
        span.set_attribute("durarun.step.name", step_name)
        span.set_attribute("durarun.step.source", source)
        span.set_attribute("durarun.step.duration_ms", duration_ms)
        span.set_attribute("durarun.step.retry_count", retry_count)
        span.end()

    def get_timeline(self) -> list[dict]:
        return list(self._timeline)

    @contextmanager
    def trace_run(self, run_id: str, steps_total: int) -> Iterator[Any]:
        span = self.start_run_span(run_id, steps_total)
        try:
            yield span
        finally:
            if self._disabled or self._run_span is not None:
                self.finish_run(recovered_steps=0)

    def shutdown(self) -> None:
        if self._provider is not None:
            self._provider.shutdown()

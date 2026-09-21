"""Minimal span exporter that prints to stdout.

Used as the default exporter when ``opentelemetry-sdk`` is installed but no
OTLP endpoint has been configured.  The class satisfies the
``opentelemetry.sdk.trace.export.SpanExporter`` interface so it can be
plugged straight into a :class:`BatchSpanProcessor`.
"""

from __future__ import annotations

import sys
from typing import Sequence

# ---------------------------------------------------------------------------
# Attempt to import SDK types so we can properly implement the interface and
# return the correct export result enum.  When the SDK is absent the module
# is still importable — callers simply should not instantiate the class.
# ---------------------------------------------------------------------------

try:
    from opentelemetry.sdk.trace import ReadableSpan
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    _SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SDK_AVAILABLE = False

    # Provide thin stubs so the class definition does not crash at import
    # time even when the SDK is missing.
    class SpanExporter:  # type: ignore[no-redef]
        """Stub base — replaced by the real SDK class when available."""

    class SpanExportResult:  # type: ignore[no-redef]
        SUCCESS = 0

    ReadableSpan = object  # type: ignore[assignment,misc]


class StdoutSpanExporter(SpanExporter):
    """Print finished spans to *stdout* in a human-friendly one-line format.

    Example output::

        [TRACE] durarun.step.analyze | duration=3200.0ms | source=wal | run_id=abc-123
    """

    # ------------------------------------------------------------------
    # SpanExporter interface
    # ------------------------------------------------------------------

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:  # type: ignore[override]
        """Write each span as a single ``[TRACE]`` line to *stdout*."""
        for span in spans:
            attrs: dict = dict(span.attributes or {})
            line = (
                f"[TRACE] {span.name}"
                f" | duration={attrs.get('durarun.step.duration_ms', 'N/A')}ms"
                f" | source={attrs.get('durarun.step.source', 'N/A')}"
                f" | run_id={attrs.get('durarun.run_id', 'N/A')}"
            )
            print(line, file=sys.stdout, flush=True)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:  # noqa: D401
        """No-op — nothing to clean up for stdout."""

    def force_flush(self, timeout_millis: int | None = None) -> bool:
        """Flush stdout and return immediately."""
        sys.stdout.flush()
        return True

"""M4: OTEL tracing

Test that OpenTelemetry traces are produced when running steps.
When opentelemetry is not installed, these tests are skipped.
"""

import io
import sys
import time

import pytest

otel = pytest.importorskip("opentelemetry", reason="opentelemetry not installed")

from durarun import DurableRunner, DurarunTracer


def _capture_stdout(runner, steps):
    """Run steps while capturing stdout to a StringIO buffer."""
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        result = runner.run(steps)
    finally:
        sys.stdout = old_stdout
    time.sleep(0.5)
    old_stdout2 = sys.stdout
    sys.stdout = buf
    try:
        if hasattr(runner, "_tracer") and runner._tracer._provider is not None:
            runner._tracer._provider.force_flush(timeout_millis=2000)
    finally:
        sys.stdout = old_stdout2
    return result, buf.getvalue()


def test_otel_trace_output(tmp_db):
    """Stdout should contain [TRACE] lines with run_id, step, source, duration."""
    runner = DurableRunner(backend="sqlite://" + tmp_db)

    @runner.step
    def analyze(ctx):
        return "analysis"

    @runner.step
    def summarize(ctx):
        return "summary"

    @runner.step
    def finalize(ctx):
        return "done"

    result, output = _capture_stdout(runner, [analyze, summarize, finalize])

    assert "[TRACE]" in output, f"No [TRACE] in output: {output!r}"
    assert "durarun.step.analyze" in output
    assert "durarun.step.summarize" in output
    assert "durarun.step.finalize" in output
    assert "source=" in output
    assert "duration=" in output
    assert "run_id=" in output


def test_tracer_attributes_set():
    """DurarunTracer should properly store run_id and create spans."""
    tracer = DurarunTracer()

    span = tracer.start_run_span("test-run-123", steps_total=3)
    assert tracer._run_id == "test-run-123"
    assert tracer._run_span is not None

    tracer.record_step("step_a", duration_ms=100.0, source="live", retry_count=0)
    tracer.record_step("step_b", duration_ms=50.0, source="wal", retry_count=0)

    tracer.finish_run(recovered_steps=1)
    assert tracer._run_span is None
    assert tracer._run_id is None


def test_tracer_context_manager():
    """DurarunTracer.trace_run context manager brackets a run."""
    tracer = DurarunTracer()

    with tracer.trace_run("ctx-mgr-run", steps_total=2) as span:
        assert tracer._run_id == "ctx-mgr-run"
        tracer.record_step("s1", 10.0, "live")
        tracer.record_step("s2", 20.0, "wal")

    assert tracer._run_span is None


def test_otel_trace_recovery_shows_source(tmp_db):
    """Recovered steps should show source=wal in trace output."""
    run_id = "trace-recovery-run"

    runner1 = DurableRunner(backend="sqlite://" + tmp_db, run_id=run_id)

    @runner1.step
    def first(ctx):
        return 1

    @runner1.step
    def second(ctx):
        return 2

    runner1.run([first, second])

    runner2 = DurableRunner(backend="sqlite://" + tmp_db, run_id=run_id)

    @runner2.step
    def first(ctx):  # noqa: F811
        return 1

    @runner2.step
    def second(ctx):  # noqa: F811
        return 2

    @runner2.step
    def third(ctx):
        return 3

    result, output = _capture_stdout(runner2, [first, second, third])

    assert "source=wal" in output
    assert "source=live" in output
    assert result.recovered_steps == 2

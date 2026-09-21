"""M4: 零配置 OTEL span

Test that OpenTelemetry traces are produced when running steps.
The default configuration uses StdoutSpanExporter which prints [TRACE] lines.
We also verify the DurarunTracer attributes are set correctly.
"""

import io
import sys
import time

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
    # Give the BatchSpanProcessor a moment to flush
    time.sleep(0.5)
    # Force flush once more with stdout captured
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

    # Verify trace output contains expected patterns
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

    # start_run_span stores run_id
    span = tracer.start_run_span("test-run-123", steps_total=3)
    assert tracer._run_id == "test-run-123"
    assert tracer._run_span is not None

    # record_step should not raise
    tracer.record_step("step_a", duration_ms=100.0, source="live", retry_count=0)
    tracer.record_step("step_b", duration_ms=50.0, source="wal", retry_count=0)

    # finish_run clears state
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

    # After exiting the context manager, state should be cleaned up
    assert tracer._run_span is None


def test_otel_trace_recovery_shows_source(tmp_db):
    """Recovered steps should show source=wal in trace output."""
    run_id = "trace-recovery-run"

    # Phase 1: run 2 steps
    runner1 = DurableRunner(backend="sqlite://" + tmp_db, run_id=run_id)

    @runner1.step
    def first(ctx):
        return 1

    @runner1.step
    def second(ctx):
        return 2

    runner1.run([first, second])

    # Phase 2: recover + 1 new step
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

    # Should show both wal and live sources
    assert "source=wal" in output
    assert "source=live" in output
    assert result.recovered_steps == 2

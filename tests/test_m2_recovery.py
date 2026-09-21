"""M2: WAL 恢复跳步

Test crash recovery: run 3 steps, then create a new runner with the same
run_id + backend. Running all 5 steps should recover the first 3 from WAL
and only execute steps 4 and 5 live.
"""

from durarun import DurableRunner


def test_recovery_skips_completed_steps(tmp_db):
    """Steps already in the WAL are not re-executed."""
    invocation_log = []

    run_id = "test-recovery-run"

    # --- Phase 1: run the first 3 steps to completion ---
    runner1 = DurableRunner(backend="sqlite://" + tmp_db, run_id=run_id)

    @runner1.step
    def step1(ctx):
        invocation_log.append("step1")
        return "r1"

    @runner1.step
    def step2(ctx):
        invocation_log.append("step2")
        return "r2"

    @runner1.step
    def step3(ctx):
        invocation_log.append("step3")
        return "r3"

    runner1.run([step1, step2, step3])
    assert invocation_log == ["step1", "step2", "step3"]

    # --- Phase 2: "crash" and create a fresh runner with the same run_id ---
    invocation_log.clear()

    runner2 = DurableRunner(backend="sqlite://" + tmp_db, run_id=run_id)

    @runner2.step
    def step1(ctx):  # noqa: F811 — intentional re-definition
        invocation_log.append("step1")
        return "r1"

    @runner2.step
    def step2(ctx):  # noqa: F811
        invocation_log.append("step2")
        return "r2"

    @runner2.step
    def step3(ctx):  # noqa: F811
        invocation_log.append("step3")
        return "r3"

    @runner2.step
    def step4(ctx):
        invocation_log.append("step4")
        return "r4"

    @runner2.step
    def step5(ctx):
        invocation_log.append("step5")
        return "r5"

    result = runner2.run([step1, step2, step3, step4, step5])

    # Only steps 4 and 5 should have been invoked
    assert invocation_log == ["step4", "step5"]

    # All 5 results present
    assert len(result.steps) == 5
    assert result.steps["step1"] == "r1"
    assert result.steps["step5"] == "r5"

    # 3 recovered from WAL
    assert result.recovered_steps == 3

    # Source flags
    sources = [d.source for d in result.step_details]
    assert sources == ["wal", "wal", "wal", "live", "live"]


def test_full_recovery_no_re_execution(tmp_db):
    """When ALL steps are already in the WAL, none are re-executed."""
    invocation_log = []
    run_id = "full-recovery-run"

    runner1 = DurableRunner(backend="sqlite://" + tmp_db, run_id=run_id)

    @runner1.step
    def a(ctx):
        invocation_log.append("a")
        return 1

    @runner1.step
    def b(ctx):
        invocation_log.append("b")
        return 2

    runner1.run([a, b])
    assert len(invocation_log) == 2

    # Phase 2 — new runner, same run_id
    invocation_log.clear()
    runner2 = DurableRunner(backend="sqlite://" + tmp_db, run_id=run_id)

    @runner2.step
    def a(ctx):  # noqa: F811
        invocation_log.append("a")
        return 1

    @runner2.step
    def b(ctx):  # noqa: F811
        invocation_log.append("b")
        return 2

    result = runner2.run([a, b])

    assert invocation_log == []  # nothing re-executed
    assert result.recovered_steps == 2
    assert result.steps["a"] == 1
    assert result.steps["b"] == 2

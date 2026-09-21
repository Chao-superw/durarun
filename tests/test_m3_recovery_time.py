"""M3: 恢复耗时 < 全量 x 0.5

Each step sleeps 0.1s. A fresh 5-step run takes ~500ms.
A recovery run (3 from WAL, 2 live) takes ~200ms.
Assert: recovery time < full time * 0.5.
"""

import time

from durarun import DurableRunner


def test_recovery_is_faster_than_half(tmp_path):
    """Recovered steps add negligible time; total should be < 50% of full run."""
    db_full = str(tmp_path / "full.db")
    db_partial = str(tmp_path / "partial.db")

    run_id = "timing-run"

    # Helper to define 5 steps on a runner
    def make_steps(runner):
        @runner.step
        def s1(ctx):
            time.sleep(0.1)
            return 1

        @runner.step
        def s2(ctx):
            time.sleep(0.1)
            return 2

        @runner.step
        def s3(ctx):
            time.sleep(0.1)
            return 3

        @runner.step
        def s4(ctx):
            time.sleep(0.1)
            return 4

        @runner.step
        def s5(ctx):
            time.sleep(0.1)
            return 5

        return [s1, s2, s3, s4, s5]

    # --- Full run: 5 steps on a fresh DB, each 0.1s => ~500ms ---
    runner_full = DurableRunner(backend="sqlite://" + db_full, step_timeout=30)
    steps_full = make_steps(runner_full)
    result_full = runner_full.run(steps_full)
    full_time = result_full.total_ms

    # --- Phase 1 of recovery: run only 3 steps (simulate partial completion) ---
    runner_partial = DurableRunner(
        backend="sqlite://" + db_partial, run_id=run_id, step_timeout=30
    )
    steps_partial = make_steps(runner_partial)
    runner_partial.run(steps_partial[:3])  # only first 3

    # --- Phase 2: new runner, same run_id, all 5 steps ---
    runner_recovery = DurableRunner(
        backend="sqlite://" + db_partial, run_id=run_id, step_timeout=30
    )
    steps_recovery = make_steps(runner_recovery)
    result_recovery = runner_recovery.run(steps_recovery)
    recovery_time = result_recovery.total_ms

    # Sanity checks
    assert full_time >= 400, f"Full run too fast: {full_time:.0f}ms"
    assert result_recovery.recovered_steps == 3

    # Core assertion: recovery (3 from WAL + 2 live ~200ms) < 50% of full (~500ms)
    assert recovery_time < full_time * 0.5, (
        f"Recovery ({recovery_time:.0f}ms) is not < 50% of full ({full_time:.0f}ms)"
    )

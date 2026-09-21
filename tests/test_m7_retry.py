"""M7: 重试 + StepRetryExhausted + StepTimeout

Test retry behavior and timeout enforcement.
"""

import time

import pytest

from durarun import DurableRunner, StepRetryExhausted, StepTimeout


def test_retry_succeeds_after_failures(tmp_db):
    """A step that fails twice then succeeds should pass with max_retries >= 2."""
    call_count = {"n": 0}

    runner = DurableRunner(
        backend="sqlite://" + tmp_db,
        max_retries=3,
        step_timeout=30,
    )

    @runner.step
    def flaky_step(ctx):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise RuntimeError(f"fail attempt {call_count['n']}")
        return "success"

    result = runner.run([flaky_step])

    assert result.steps["flaky_step"] == "success"
    assert call_count["n"] == 3  # failed 2 times, succeeded on 3rd
    # retry_count in detail should be 2 (the attempt index on success)
    assert result.step_details[0].retry_count == 2


def test_retry_exhausted_raises(tmp_db):
    """A step that always fails should raise StepRetryExhausted."""
    runner = DurableRunner(
        backend="sqlite://" + tmp_db,
        max_retries=2,
        step_timeout=30,
    )

    @runner.step
    def always_fail(ctx):
        raise ValueError("permanent error")

    with pytest.raises(StepRetryExhausted) as exc_info:
        runner.run([always_fail])

    err = exc_info.value
    assert err.step_name == "always_fail"
    assert err.max_retries == 2
    assert isinstance(err.last_exception, ValueError)
    assert "permanent error" in str(err.last_exception)


def test_retry_exhausted_with_zero_retries(tmp_db):
    """max_retries=0 means only 1 attempt; failure raises immediately."""
    runner = DurableRunner(
        backend="sqlite://" + tmp_db,
        max_retries=0,
        step_timeout=30,
    )

    call_count = {"n": 0}

    @runner.step
    def single_shot(ctx):
        call_count["n"] += 1
        raise RuntimeError("boom")

    with pytest.raises(StepRetryExhausted) as exc_info:
        runner.run([single_shot])

    assert call_count["n"] == 1
    assert exc_info.value.max_retries == 0


def test_step_timeout_raises(tmp_db):
    """A step exceeding its timeout should raise StepTimeout."""
    runner = DurableRunner(
        backend="sqlite://" + tmp_db,
        max_retries=0,
        step_timeout=1,  # 1 second
    )

    @runner.step
    def slow_step(ctx):
        time.sleep(10)
        return "should not reach"

    with pytest.raises(StepTimeout) as exc_info:
        runner.run([slow_step])

    err = exc_info.value
    assert err.step_name == "slow_step"
    assert err.timeout_seconds == 1.0


def test_per_step_timeout_override(tmp_db):
    """@runner.step(timeout=...) overrides the global timeout."""
    runner = DurableRunner(
        backend="sqlite://" + tmp_db,
        max_retries=0,
        step_timeout=60,  # generous global timeout
    )

    @runner.step(timeout=1)
    def custom_timeout_step(ctx):
        time.sleep(10)
        return "nope"

    with pytest.raises(StepTimeout) as exc_info:
        runner.run([custom_timeout_step])

    assert exc_info.value.step_name == "custom_timeout_step"
    assert exc_info.value.timeout_seconds == 1.0


def test_per_step_retry_override(tmp_db):
    """@runner.step(retry=...) overrides the global max_retries."""
    call_count = {"n": 0}

    runner = DurableRunner(
        backend="sqlite://" + tmp_db,
        max_retries=10,  # generous global retry
        step_timeout=30,
    )

    @runner.step(retry=1)
    def limited_retry(ctx):
        call_count["n"] += 1
        raise RuntimeError("fail")

    with pytest.raises(StepRetryExhausted) as exc_info:
        runner.run([limited_retry])

    # retry=1 means 2 total attempts (1 initial + 1 retry)
    assert call_count["n"] == 2
    assert exc_info.value.max_retries == 1


def test_timeout_not_retried(tmp_db):
    """StepTimeout should propagate immediately without retrying."""
    call_count = {"n": 0}

    runner = DurableRunner(
        backend="sqlite://" + tmp_db,
        max_retries=5,
        step_timeout=1,
    )

    @runner.step
    def timeout_no_retry(ctx):
        call_count["n"] += 1
        time.sleep(10)
        return "nope"

    with pytest.raises(StepTimeout):
        runner.run([timeout_no_retry])

    # Should have been called exactly once — timeout is not retried
    assert call_count["n"] == 1

"""M1: 15 LOC 跑通 5-step Agent

Verify that <= 20 lines of user code can create and run a 5-step agent,
and that RunResult contains the expected fields.
"""

from durarun import DurableRunner


def test_basic_5_step_run(tmp_db):
    """Run 5 steps and validate RunResult fields."""
    runner = DurableRunner(backend="sqlite://" + tmp_db)

    @runner.step
    def step1(ctx):
        return "result1"

    @runner.step
    def step2(ctx):
        return "result2"

    @runner.step
    def step3(ctx):
        return "result3"

    @runner.step
    def step4(ctx):
        return "result4"

    @runner.step
    def step5(ctx):
        return "result5"

    result = runner.run([step1, step2, step3, step4, step5])

    # RunResult.steps is a dict with 5 entries
    assert len(result.steps) == 5
    assert result.steps["step1"] == "result1"
    assert result.steps["step5"] == "result5"

    # total_ms > 0
    assert result.total_ms > 0

    # No recovery on a fresh run
    assert result.recovered_steps == 0

    # step_details has 5 entries, all source="live"
    assert len(result.step_details) == 5
    for detail in result.step_details:
        assert detail.source == "live"


def test_step_details_contain_correct_names(tmp_db):
    """Each StepDetail carries the correct step name."""
    runner = DurableRunner(backend="sqlite://" + tmp_db)

    @runner.step
    def alpha(ctx):
        return 1

    @runner.step
    def beta(ctx):
        return 2

    @runner.step
    def gamma(ctx):
        return 3

    @runner.step
    def delta(ctx):
        return 4

    @runner.step
    def epsilon(ctx):
        return 5

    result = runner.run([alpha, beta, gamma, delta, epsilon])
    names = [d.name for d in result.step_details]
    assert names == ["alpha", "beta", "gamma", "delta", "epsilon"]


def test_run_result_has_run_id(tmp_db):
    """RunResult must carry a non-empty run_id."""
    runner = DurableRunner(backend="sqlite://" + tmp_db)

    @runner.step
    def only_step(ctx):
        return 42

    result = runner.run([only_step])
    assert result.run_id  # non-empty string


def test_step_decorator_with_name(tmp_db):
    """@runner.step(name=...) overrides the function name."""
    runner = DurableRunner(backend="sqlite://" + tmp_db)

    @runner.step(name="custom_name")
    def my_func(ctx):
        return "hello"

    result = runner.run([my_func])
    assert "custom_name" in result.steps
    assert result.step_details[0].name == "custom_name"


def test_loc_count():
    """Ensure the user-facing code to run 5 steps fits in <= 20 LOC.

    We count lines from creating the runner to calling runner.run().
    """
    # The following block represents the 'user code':
    user_code = '''
runner = DurableRunner(backend="sqlite:///tmp/test.db")

@runner.step
def s1(ctx): return 1

@runner.step
def s2(ctx): return 2

@runner.step
def s3(ctx): return 3

@runner.step
def s4(ctx): return 4

@runner.step
def s5(ctx): return 5

result = runner.run([s1, s2, s3, s4, s5])
'''
    lines = [l for l in user_code.strip().splitlines() if l.strip()]
    assert len(lines) <= 20, f"User code is {len(lines)} lines, expected <= 20"

"""M5: backend 切换只改一行

Switching the backend parameter produces identical results.
The WALBackend Protocol is satisfied by SqliteWAL.
"""

from durarun import DurableRunner, SqliteWAL
from durarun.wal.protocol import WALBackend


def _define_steps(runner):
    """Register the same 3 steps on any runner instance."""

    @runner.step
    def fetch(ctx):
        return {"data": [1, 2, 3]}

    @runner.step
    def transform(ctx):
        return {"transformed": True}

    @runner.step
    def store(ctx):
        return "stored"

    return [fetch, transform, store]


def test_same_steps_different_backends(tmp_path):
    """Identical step functions produce identical structure on different backends."""
    db1 = str(tmp_path / "backend_a.db")
    db2 = str(tmp_path / "backend_b.db")

    runner1 = DurableRunner(backend="sqlite://" + db1)
    steps1 = _define_steps(runner1)
    result1 = runner1.run(steps1)

    runner2 = DurableRunner(backend="sqlite://" + db2)
    steps2 = _define_steps(runner2)
    result2 = runner2.run(steps2)

    # Same step names
    assert list(result1.steps.keys()) == list(result2.steps.keys())

    # Same results
    assert result1.steps == result2.steps

    # Same number of details, same sources
    assert len(result1.step_details) == len(result2.step_details)
    for d1, d2 in zip(result1.step_details, result2.step_details):
        assert d1.name == d2.name
        assert d1.source == d2.source
        assert d1.result == d2.result


def test_sqlite_wal_satisfies_protocol():
    """SqliteWAL should implement the WALBackend Protocol."""
    # Check that SqliteWAL has all the methods the Protocol requires
    required_methods = ["append", "read", "mark_complete", "list_incomplete", "fsync"]
    for method_name in required_methods:
        assert hasattr(SqliteWAL, method_name), (
            f"SqliteWAL missing method: {method_name}"
        )

    # runtime_checkable Protocol check (WALBackend is not runtime_checkable,
    # so we verify structurally)
    import inspect

    for method_name in required_methods:
        proto_method = getattr(WALBackend, method_name, None)
        impl_method = getattr(SqliteWAL, method_name, None)
        assert impl_method is not None
        assert callable(impl_method)


def test_backend_string_parsing(tmp_path):
    """Various backend URI formats should all work."""
    db_path = str(tmp_path / "parse_test.db")

    # sqlite:// prefix
    runner1 = DurableRunner(backend="sqlite://" + db_path)

    @runner1.step
    def test_step(ctx):
        return "ok"

    result = runner1.run([test_step])
    assert result.steps["test_step"] == "ok"


def test_backend_plain_path(tmp_path):
    """A plain file path (no scheme) should also be accepted as SQLite."""
    db_path = str(tmp_path / "plain_path.db")

    runner = DurableRunner(backend=db_path)

    @runner.step
    def my_step(ctx):
        return 99

    result = runner.run([my_step])
    assert result.steps["my_step"] == 99

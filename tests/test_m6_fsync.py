"""M6: WAL fsync 持久化保证

Test that fsync guarantees data is readable by a new connection,
simulating a process restart.
"""

import time

from durarun import SqliteWAL


def test_single_record_survives_reconnect(tmp_path):
    """Append + fsync, then read from a brand new SqliteWAL instance."""
    db_path = str(tmp_path / "fsync_test.db")

    wal1 = SqliteWAL(db_path=db_path)
    wal1.append(
        run_id="run-1",
        step_name="step_a",
        result={"key": "value"},
        metadata={"duration_ms": 42.0, "timestamp": time.time()},
    )
    wal1.fsync()
    wal1.close()

    # New connection — simulates new process
    wal2 = SqliteWAL(db_path=db_path)
    records = wal2.read("run-1")
    wal2.close()

    assert len(records) == 1
    assert records[0].step_name == "step_a"
    assert records[0].result == {"key": "value"}
    assert records[0].duration_ms == 42.0


def test_multiple_records_survive_reconnect(tmp_path):
    """Append several records, fsync, then verify all from a new connection."""
    db_path = str(tmp_path / "fsync_multi.db")

    wal1 = SqliteWAL(db_path=db_path)
    for i in range(5):
        wal1.append(
            run_id="run-multi",
            step_name=f"step_{i}",
            result=i * 10,
            metadata={"duration_ms": float(i), "timestamp": time.time()},
        )
    wal1.fsync()
    wal1.close()

    wal2 = SqliteWAL(db_path=db_path)
    records = wal2.read("run-multi")
    wal2.close()

    assert len(records) == 5
    for i, rec in enumerate(records):
        assert rec.step_name == f"step_{i}"
        assert rec.result == i * 10


def test_mark_complete_persists(tmp_path):
    """mark_complete + fsync makes the run disappear from list_incomplete."""
    db_path = str(tmp_path / "fsync_complete.db")

    wal1 = SqliteWAL(db_path=db_path)
    wal1.append(
        run_id="run-done",
        step_name="only_step",
        result="ok",
        metadata={"duration_ms": 1.0, "timestamp": time.time()},
    )
    wal1.fsync()

    # Before marking complete, the run should be incomplete
    incomplete = wal1.list_incomplete()
    run_ids = [r.run_id for r in incomplete]
    assert "run-done" in run_ids

    wal1.mark_complete("run-done")
    wal1.fsync()
    wal1.close()

    # New connection — should NOT see it in incomplete
    wal2 = SqliteWAL(db_path=db_path)
    incomplete2 = wal2.list_incomplete()
    run_ids2 = [r.run_id for r in incomplete2]
    assert "run-done" not in run_ids2

    # But the data is still there
    records = wal2.read("run-done")
    assert len(records) == 1
    wal2.close()


def test_insertion_order_preserved(tmp_path):
    """Records must come back in insertion order after reconnect."""
    db_path = str(tmp_path / "fsync_order.db")

    wal1 = SqliteWAL(db_path=db_path)
    names = ["alpha", "beta", "gamma", "delta"]
    for name in names:
        wal1.append(
            run_id="ordered-run",
            step_name=name,
            result=name.upper(),
            metadata={"duration_ms": 1.0, "timestamp": time.time()},
        )
    wal1.fsync()
    wal1.close()

    wal2 = SqliteWAL(db_path=db_path)
    records = wal2.read("ordered-run")
    wal2.close()

    assert [r.step_name for r in records] == names
    assert [r.result for r in records] == [n.upper() for n in names]

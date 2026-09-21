import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """Provide a temporary SQLite database path"""
    return str(tmp_path / "test_durarun.db")


@pytest.fixture
def runner(tmp_db):
    """Provide a DurableRunner with temporary backend"""
    from durarun import DurableRunner

    return DurableRunner(backend="sqlite://" + tmp_db)

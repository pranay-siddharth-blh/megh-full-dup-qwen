"""Suite-wide guards."""
import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _checkpoints_off_the_real_database(monkeypatch):
    # The checkpointer is Postgres (app.checkpoint* in megh_db). Tests that run
    # the graph must never write those tables: each test gets an in-process
    # saver instead. A test that needs the Postgres branch sets the DSN itself
    # and fakes the driver.
    monkeypatch.setattr(settings, "PIPELINE_GRAPH_CHECKPOINTER_DSN", "memory")

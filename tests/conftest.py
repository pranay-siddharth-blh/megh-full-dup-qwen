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


@pytest.fixture(autouse=True)
def _generated_sql_off_the_chatbot_login(monkeypatch):
    # .env may name the megh_chatbot login (D-073). Tests run generated SQL on
    # the read-only pool path (usually faked); a test of the run_query path sets
    # the URL itself and fakes the pool.
    monkeypatch.setattr(settings, "CHATBOT_DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _guardrail_model_off(monkeypatch):
    # The model layer of app/guardrails.py is one extra classifier call per
    # question; tests that fake the classifier with a fixed reply sequence must
    # not have it consumed by the guard. tests/test_guardrails.py turns it on
    # with its own fake.
    monkeypatch.setattr(settings, "GUARDRAIL_MODEL_ENABLED", False)

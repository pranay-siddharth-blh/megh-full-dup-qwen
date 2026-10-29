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


@pytest.fixture(autouse=True)
def _sql_examples_from_yaml(monkeypatch):
    # SQL_EXAMPLES_SOURCE=qdrant (D-074) is one embedding call + Qdrant searches
    # per data turn, against the live gateway and collection. Tests fake the
    # models and pin prompts built from the YAML banks; the Qdrant path is
    # tested with its own fakes in tests/test_qdrant_two_collections_2026_10_27.py.
    monkeypatch.setattr(settings, "SQL_EXAMPLES_SOURCE", "yaml")
    # B1 meaning shadow (2026-10-27): a background embedding call that appends to
    # logs/metric_meaning_shadow.jsonl. Off in tests; its own tests switch it on
    # with a temporary file (tests/test_metric_meaning_shadow_b1_2026_10_27.py).
    monkeypatch.setattr(settings, "METRIC_MEANING_SHADOW", False)
    # B3 score tie-break (2026-10-27): one embedding + two Qdrant searches on some DATA
    # verdicts. Off in tests; tests/test_intent_scores_b3_2026_10_27.py fakes them.
    monkeypatch.setattr(settings, "INTENT_SCORE_TIEBREAK", False)
    # E1 query-plan shadow (2026-10-27): a background classifier call after each turn.
    # Off in tests; tests/test_query_plan_shadow_e1_2026_10_27.py drives it with fakes.
    monkeypatch.setattr(settings, "QUERY_PLAN_SHADOW", False)

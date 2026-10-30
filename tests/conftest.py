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
def _cross_figures_years_cache_starts_empty():
    # cross_figures caches each scheme's years held (_YEARS) for the process: a test
    # whose fake megh_db returned (2017, 2023) left PMAY-G's years for the next file,
    # whose fake held a range, so "a stated span" said FY 2022-23 was missing too
    # (test_chat_ui_audit_rows, only in some file orders; found 2026-10-30).
    from app import cross_figures
    cross_figures._YEARS.clear()
    yield
    cross_figures._YEARS.clear()


@pytest.fixture(autouse=True)
def _no_request_trace_from_an_earlier_test():
    # turn_trace keeps the request's start time in a context variable; a sync test
    # that started a trace and never finished it left it set for every later test,
    # so the KI-013 repair budget (elapsed since that start) read "120 s used" and
    # five repair tests failed only in the full run (2026-10-29, KI-622). Each test starts clean.
    from app import turn_trace
    token = turn_trace._trace_var.set(None)
    yield
    try:
        turn_trace._trace_var.reset(token)
    except ValueError:            # set in another context by the test itself
        turn_trace._trace_var.set(None)


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
    # E9 answer templates (2026-10-29): the suites written before them pin the composer's
    # own multi-row wording (the rollback path). tests/test_answer_format_e9_2026_10_29.py
    # switches them on.
    monkeypatch.setattr(settings, "ANSWER_TEMPLATES_ENABLED", False)

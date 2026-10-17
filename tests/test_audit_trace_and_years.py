"""2026-10-16: spoken years and "FY2022-23" are read (errors.md cases 10-11), and
the audit / metrics carry what the DATA path did (SQL, error, few-shot ids,
repairs, verifier rejections, outcome). Real functions."""
import asyncio

from app import annotations, turn_trace
from app import pipeline as p
from app import prompt_builder


# ── years ───────────────────────────────────────────────────────────────────

def test_fy_without_a_space_is_read():                              # case 10 / KI-289
    q = p._correct_fy_spacing("How many houses were sanctioned under PMAY-G in FY2022-23?")
    assert p._years_in_question(q)[0] == ["2022-23"]


def test_spoken_financial_year_is_read():                          # case 11
    q = p._correct_fy_spacing("top ten blocks in West Garo Hills for Focus Plus per financial year "
                              "twenty twenty five to twenty six?")
    assert "2025-26" in q and p._years_in_question(q)[0] == ["2025-26"]


def test_other_spoken_year_shapes():
    assert p._spoken_years_to_digits("person days in twenty twenty three") == "person days in 2023"
    assert p._spoken_years_to_digits("financial year twenty twenty-four twenty-five") == "financial year 2024-25"
    assert p._spoken_years_to_digits("houses in two thousand and twenty two") == "houses in 2022"
    assert p._spoken_years_to_digits("twenty nineteen to twenty twenty") == "2019-20"


def test_counts_are_not_mistaken_for_years():
    for q in ("show the top twenty five districts", "twenty blocks", "top ten villages"):
        assert p._spoken_years_to_digits(q) == q
    assert p._spoken_years_to_digits("twenty five blocks in twenty twenty") == "twenty five blocks in 2020"


# ── audit trace ─────────────────────────────────────────────────────────────

def test_few_shot_ids_reach_the_trace():
    annotations.load_all()
    t = turn_trace.start("rid-1")
    prompt_builder.build_sql_prompt("How many men worked under MGNREGA in Ri Bhoi in 2023-24?", ["MGNREGA"],
                                    {"resolved": {}, "display": {}, "notes": []})
    assert t["few_shot_ids"] and all(i.startswith("MGNREGA#") for i in t["few_shot_ids"])


def test_trace_survives_a_child_task():
    t = turn_trace.start("rid-2")

    async def node():
        turn_trace.note_repair('column "x" does not exist')
        turn_trace.note_verifier_rejection()

    async def main():
        await asyncio.create_task(node())        # LangGraph runs nodes in tasks like this
    asyncio.run(main())
    assert t["repairs"] == 1 and t["verifier_rejections"] == 1 and "does not exist" in t["sql_errors"][0]


def test_audit_fields_and_outcomes():
    t = turn_trace.start("rid-3")
    ok = {"route": "data", "sql": "SELECT 1 FROM curated.v_employment"}
    assert turn_trace.outcome(t, ok) == "ok_first_try"
    turn_trace.note_repair("boom")
    assert turn_trace.outcome(t, ok) == "ok_after_repair"
    a = turn_trace.audit_fields(t, ok)
    assert a["sql"].startswith("SELECT") and a["error"] == "boom" and a["request_id"] == "rid-3"
    turn_trace.note_final_error(ValueError("gave up"))
    kb = {"route": "knowledge", "answer": "From the KB"}
    assert turn_trace.outcome(t, kb) == "failed"              # a KB fallback is not a real knowledge answer
    assert turn_trace.outcome(turn_trace.start(), kb) == "knowledge"


def test_metrics_counters_and_rates():
    before = dict(turn_trace.COUNTERS)
    turn_trace.finish(turn_trace.start(), {"route": "data", "sql": "SELECT 1 FROM t"})
    t = turn_trace.start()
    turn_trace.note_repair("x")
    turn_trace.finish(t, {"route": "data", "sql": "SELECT 1 FROM t"})
    m = turn_trace.metrics()
    assert m["data_turns"] == before["data_turns"] + 2
    assert m["sql_ok_after_repair"] == before["sql_ok_after_repair"] + 1
    assert m["repairs_total"] == before["repairs_total"] + 1
    assert m["sql_success_rate_pct"] is not None
    assert "nl2sql_eval_latest" in m


def test_audit_row_carries_sql_error_and_few_shots(monkeypatch):
    import json as _json
    from app import conversation_store, db, sql_ast
    calls = []

    async def fake_fetchval(sql, params):
        return 1

    async def fake_execute(sql, params):
        calls.append((sql, params))

    monkeypatch.setattr(db, "fetchval", fake_fetchval)
    monkeypatch.setattr(db, "execute", fake_execute)
    result = {"route": "data", "intent": "DATA", "answer": "x", "sql": "SELECT 1 FROM curated.v_employment",
              "row_count": 1, "schemes": ["MGNREGA"]}
    audit = {"sql": result["sql"], "error": "column x missing", "few_shot_ids": ["MGNREGA#3"], "repairs": 1,
             "verifier_rejections": 0, "outcome": "ok_after_repair", "request_id": "rid-9"}
    asyncio.run(conversation_store._persist_turn("t", 1, "s", result, "q", 5.0, "u", "1.2.3.4", audit))
    sql, params = next(c for c in calls if "query_audit" in c[0])
    # the INSERT is valid SQL (sqlglot cannot tokenize "$1,$2" without a space; Postgres can)
    assert sql_ast.is_parseable(sql.replace(",$", ", $"))
    assert params[14] == result["sql"] and params[15] == "column x missing"
    assert _json.loads(params[16]) == ["MGNREGA#3"] and params[17] == 1 and params[19] == "ok_after_repair"
    assert params[20] == "rid-9"

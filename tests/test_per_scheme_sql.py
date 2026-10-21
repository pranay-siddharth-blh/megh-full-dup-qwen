"""KI-011: a multi-scheme SQL prompt over the 30B's budget is never sent. Each
scheme gets its own prompt and query (its own guards / repairs), and the rows
come back tagged with their scheme. Real functions; the model and DB stubbed."""
import asyncio

from app import annotations
from app import pipeline as p

annotations.load_all()
ER = {"resolved": {}, "display": {}, "notes": []}
Q = "How many beneficiaries are there in each scheme?"


def test_budget_decides_the_mode():
    assert not p._per_scheme_needed(Q, ["MGNREGA"], ER)                      # one scheme: never
    assert p._per_scheme_needed(Q, ["CM Elevate", "Focus Legacy"], ER)       # ~16.8k > 15,360
    assert p._per_scheme_needed(Q, list(p.SCHEME_CATALOG), ER)               # ~30k


def _d(schemes):
    return {"question": Q, "schemes": schemes, "entity_result": ER, "mg_det": None,
            "sql": None, "rows": None, "per_scheme": None}


def test_one_query_per_scheme_is_generated(monkeypatch):
    seen = []

    async def fake_generate(question, schemes, entity_result):
        seen.append((question, tuple(schemes)))
        return f"SELECT COUNT(*) AS n FROM curated.v_{schemes[0].lower().replace(' ', '_')}"

    monkeypatch.setattr(p, "generate_sql", fake_generate)
    d = _d(["CM Elevate", "Focus Legacy"])
    asyncio.run(p._data_sql_stage(d))
    assert [s for _, s in seen] == [("CM Elevate",), ("Focus Legacy",)]
    assert all("answer for" in q and "only" in q for q, _ in seen)
    assert [x[0] for x in d["per_scheme"]] == ["CM Elevate", "Focus Legacy"]
    assert d["sql"].count("SELECT") == 2


def test_rows_are_tagged_and_a_failing_scheme_is_named(monkeypatch):
    async def same(question, schemes, entity_result, sql):
        return sql

    async def run(question, schemes, entity_result, sql):
        if schemes == ["Focus Legacy"]:
            raise ValueError("column does not exist")
        return [{"n": 7}]

    async def repair(question, schemes, entity_result, sql, error):
        return sql

    monkeypatch.setattr(p, "_scheme_sql_rewrites", same)
    monkeypatch.setattr(p, "_execute_one_attempt", run)
    monkeypatch.setattr(p, "_repair_sql", repair)
    d = _d(["CM Elevate", "Focus Legacy"])
    d["per_scheme"] = [["CM Elevate", "SELECT COUNT(*) AS n FROM curated.v_cm_elevate", None],
                       ["Focus Legacy", "SELECT COUNT(*) AS n FROM curated.v_focus_legacy", None]]
    asyncio.run(p._data_per_scheme_rows(d))
    assert d["rows"] == [{"scheme": "CM Elevate", "n": 7}]
    notes = p._per_scheme_notes(d)
    assert any("Focus Legacy" in n and "No figure" in n for n in notes)


def test_every_scheme_failing_fails_the_turn(monkeypatch):
    async def same(question, schemes, entity_result, sql):
        return sql

    async def run(*a, **k):
        raise ValueError("bad")

    async def repair(question, schemes, entity_result, sql, error):
        return sql

    monkeypatch.setattr(p, "_scheme_sql_rewrites", same)
    monkeypatch.setattr(p, "_execute_one_attempt", run)
    monkeypatch.setattr(p, "_repair_sql", repair)
    d = _d(["CM Elevate", "Focus Legacy"])
    d["per_scheme"] = [["CM Elevate", "SELECT 1 FROM curated.v_cm_elevate", None],
                       ["Focus Legacy", "SELECT 1 FROM curated.v_focus_legacy", None]]
    try:
        asyncio.run(p._data_per_scheme_rows(d))
        raised = False
    except ValueError:
        raised = True
    assert raised

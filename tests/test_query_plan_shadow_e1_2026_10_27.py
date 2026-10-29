"""E1 stage 1 (RAG plan; D-078) — the query plan in SHADOW mode.

One background classifier call after the turn reads the question into a typed plan;
years, top-N, the measure (catalogue literal match) and the area level (the place
index) are filled deterministically. Logged beside what the pipeline decided; nothing
reads it. Live 2026-10-27 (tests/query_plan/run_eval.py, 25 questions): first draft
intent 22/23, measure 7/10, place 8/16; after the deterministic fields every field
agreed (79/79).

OFFLINE: the real query_plan functions and _update_context; the model is faked.
    .venv/Scripts/python.exe -m pytest tests/test_query_plan_shadow_e1_2026_10_27.py -q
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import entity_resolver, llm, metric_catalog as mc, pipeline as p, query_plan as qp  # noqa: E402
from app.config import settings  # noqa: E402

PD = mc.Metric(key="mgnrega_employment_generated", scheme="MGNREGA", display_name="Person days",
               expression="SUM(person_days)", base_object="curated.v_employment", unit="person days",
               notes="", alias="employment_generated", phrases=(("person", "day"),),
               columns=frozenset({"person_days", "year_key", "lgd_district"}))


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def catalogue(monkeypatch):
    monkeypatch.setitem(mc._state, "metrics", {PD.key: PD})
    monkeypatch.setitem(mc._state, "by_scheme", {"MGNREGA": [PD]})
    monkeypatch.setitem(mc._state, "loaded", True)
    monkeypatch.setattr(entity_resolver, "place_mentions",
                        lambda q: {"WEST GARO HILLS": "district"} if "West Garo Hills" in q else {})


def test_normalise_fills_years_top_n_measure_and_area(catalogue):
    q = "Top 5 blocks by person-days in West Garo Hills from 2022-23 to 2024-25"
    model = {"intent": "DATA", "schemes": ["MGNREGA"], "measure": "other", "place_level": "block",
             "group_by": "block", "shape": "ranking", "order": "highest"}
    plan = qp.normalise(q, model)
    assert plan["years"] == [2022, 2023, 2024] and plan["top_n"] == 5
    assert plan["measure"] == "mgnrega_employment_generated" and plan["measure_from"] == "catalogue"
    assert plan["place_level"] == "district" and plan["group_by"] == "block"   # area vs grouping


def test_a_grouping_alone_is_not_an_area(catalogue):
    plan = qp.normalise("person-days by district in 2023-24",
                        {"intent": "DATA", "schemes": ["MGNREGA"], "place_level": "district"})
    assert plan["place_level"] == "none" and plan["years"] == [2023]


def test_actual_reads_lists_limit_and_catalogue_measure():
    res = {"route": "data", "schemes": ["MGNREGA"],
           "sql": "/* metric:mgnrega_employment_generated ranking */ SELECT lgd_block, SUM(person_days) AS pd "
                  "FROM curated.v_employment GROUP BY lgd_block ORDER BY pd DESC LIMIT 5",
           "resolved_entities": {"district_list": ["EAST GARO HILLS", "WEST GARO HILLS"], "year_key": 2023}}
    act = qp.actual(res)
    assert act == {"intent": "DATA", "route": "data", "schemes": ["MGNREGA"],
                   "measure": "mgnrega_employment_generated", "place_level": "district", "years": [2023], "limit": 5}


def test_compare_counts_only_what_both_sides_state():
    plan = {"intent": "DATA", "schemes": ["MGNREGA"], "measure": "x", "place_level": "none", "years": [2023],
            "top_n": None}
    act = {"intent": "DATA", "schemes": ["MGNREGA"], "measure": None, "place_level": "none", "years": [2023]}
    assert qp.compare(plan, act) == {"intent": True, "schemes": True, "years": True}
    assert qp.compare({"intent": "OTHER"}, {"intent": "KNOWLEDGE"}) == {"intent": False}


def test_shadow_writes_one_record(catalogue, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "QUERY_PLAN_SHADOW", True)
    monkeypatch.setattr(settings, "QUERY_PLAN_FILE", str(tmp_path / "plan.jsonl"))

    async def classifier(*_a, **_kw):
        return json.dumps({"intent": "DATA", "schemes": ["MGNREGA"], "measure": "other", "place_level": "none",
                           "place_name": "", "group_by": "none", "all_years": False, "shape": "single_value",
                           "order": "none"})
    monkeypatch.setattr(llm, "call_classifier", classifier)
    res = {"route": "data", "schemes": ["MGNREGA"], "sql": "SELECT SUM(person_days) FROM curated.v_employment "
           "WHERE year_key = 2023", "resolved_entities": {"year_key": 2023}}
    rec = _run(qp.shadow("person-days in 2023-24", "person-days in 2023-24", res))
    assert rec["agree"] == {"intent": True, "schemes": True, "years": True}
    assert json.loads((tmp_path / "plan.jsonl").read_text(encoding="utf-8"))["plan"]["years"] == [2023]
    assert _run(qp.shadow("hi", "hi", {"route": "edge"})) is None          # only data / knowledge turns


def test_update_context_schedules_the_shadow_only_when_on(monkeypatch):
    calls = []

    async def fake_shadow(q, raw, result):
        calls.append(q)
    monkeypatch.setattr(qp, "shadow", fake_shadow)
    monkeypatch.setattr(settings, "CONTEXT_LAYER_ENABLED", False)

    async def turn(on):
        monkeypatch.setattr(settings, "QUERY_PLAN_SHADOW", on)
        await p._update_context(None, "person-days in 2023-24", {"route": "data"})
        await asyncio.sleep(0)
    _run(turn(False))
    assert calls == []
    _run(turn(True))
    assert calls == ["person-days in 2023-24"]

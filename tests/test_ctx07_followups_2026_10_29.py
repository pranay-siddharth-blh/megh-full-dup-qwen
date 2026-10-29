"""
CTX-07 (2026-10-29): two follow-ups the model rewrite got wrong, now rewritten
deterministically (c01 _c01_ctx07_*, wired in c14 step 0h''').

  KI-363  "Break it down by district" after a STATEWIDE answer was rewritten
          "... for all districts in Meghalaya ..." and answered with the total
          again. Now: the previous question by district.
  KI-364  "Compare the number of beneficiaries with Ri Bhoi" after an East Khasi
          Hills answer was not read as a follow-up at all (reproduced offline:
          intent followup=False) and was answered for Ri Bhoi alone. Now: the
          previous question for both places, same measure, scheme and year.

Both are reproduced offline through the real graph with the model unreachable;
the data path is stubbed and records the question it receives. KI-416 ("FY20?"
switching houses to the amount) is not here: offline, the rewrite guard already
rejects every money rewrite of a houses question (see the last test), so the
measure is lost after the rewrite (SQL generation, lane B1) — needs the live run.
    .venv/Scripts/python.exe -m pytest tests/test_ctx07_followups_2026_10_29.py -q
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import annotations, context_policy as cp, entity_resolver, llm  # noqa: E402
from app import pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers.query import build_turn  # noqa: E402
from app.session_store import Session, Turn  # noqa: E402
from _graph_turn import graph_turn, stub_data_path  # noqa: E402

STATEWIDE = "How much Focus Plus amount was disbursed in all of Meghalaya in FY 2025-26?"
EKH_Q = "How many PMAY-G beneficiaries are there in East Khasi Hills in FY 2023-24?"
BLOCK_Q = "How many MGNREGA person-days were generated in Mawphlang block in FY 2022-23?"


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()
    annotations.load_all()


def _prev(question, scheme, resolved):
    return Turn(question=question, raw_question=question, route="data", schemes=[scheme],
                resolved_entities=dict(resolved), answer="x")


STATEWIDE_PREV = _prev(STATEWIDE, "Focus Plus", {"year_key": 2025})
EKH_PREV = _prev(EKH_Q, "PMAY-G", {"district": "EAST KHASI HILLS", "year_key": 2023})
BLOCK_PREV = _prev(BLOCK_Q, "MGNREGA", {"district": "EAST KHASI HILLS", "block": "MAWPHLANG", "year_key": 2022})


# ── KI-363: a breakdown of a statewide answer ───────────────────────────────

@pytest.mark.parametrize("ask", ["Break it down by district", "Break that down by district", "district wise"])
def test_a_breakdown_of_a_statewide_answer_is_the_question_by_that_dimension(ask):
    assert p._c01_ctx07_breakdown_question(ask, STATEWIDE_PREV) == \
        "How much Focus Plus amount was disbursed in FY 2025-26 by district"


@pytest.mark.parametrize("ask,prev", [
    ("Break that down by block", EKH_PREV),                    # inside a district: keeps it (merge plan)
    ("break it down by district for PMAY-G", STATEWIDE_PREV),  # brings a scheme of its own
    ("show me by district in 2023", STATEWIDE_PREV),           # brings a year of its own
    ("What about Ri Bhoi?", STATEWIDE_PREV),                   # not a breakdown
])
def test_anything_else_is_left_to_the_rewrite(ask, prev):
    assert p._c01_ctx07_breakdown_question(ask, prev) is None


# ── KI-364: compare with another place ──────────────────────────────────────

@pytest.mark.parametrize("ask", ["Compare the number of beneficiaries with Ri Bhoi", "compare with Ri Bhoi",
                                 "and Ri Bhoi, compared?", "How does it compare against Ri Bhoi?"])
def test_compare_with_a_place_keeps_the_previous_place(ask):
    assert p._c01_ctx07_compare_place_question(ask, EKH_PREV) == \
        "Compare how many PMAY-G beneficiaries are there in East Khasi Hills and Ri Bhoi in FY 2023-24?"


def test_compare_with_a_block_keeps_the_block_level():
    out = p._c01_ctx07_compare_place_question("compare with Mylliem", BLOCK_PREV)
    assert out == "Compare how many MGNREGA person-days were generated in Mawphlang and Mylliem blocks in FY 2022-23?"


@pytest.mark.parametrize("ask", [
    "What about Ri Bhoi?",                              # a place SWAP: D-056, left to the model
    "Compare with Ri Bhoi in FY 2022-23",               # a new year too
    "Compare with Ri Bhoi under MGNREGA",               # another scheme
    "Compare the amount with Ri Bhoi",                  # another measure
    "Compare Ri Bhoi and West Garo Hills",              # two places: a question of its own
    "Compare with East Khasi Hills",                    # the same place
    "Compare with Mawphlang",                           # another level (a block after a district)
    "compare with PMAY-G",                              # no place at all
])
def test_compare_is_left_alone_when_anything_else_changes(ask):
    assert p._c01_ctx07_compare_place_question(ask, EKH_PREV) is None


# ── Through the graph ───────────────────────────────────────────────────────

@pytest.fixture
def chat(monkeypatch):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    seen = []
    resolved = {}

    async def data(question, scope=None, **kw):
        seen.append(question)
        return {"route": "data", "intent": "DATA", "schemes": [resolved["scheme"]], "sql": "SELECT 1",
                "resolved_entities": dict(resolved["entities"]), "rows": [{"n": 1}], "data": [{"n": 1}],
                "row_count": 1, "answer": "answer."}
    stub_data_path(monkeypatch, data)

    async def no_model(*a, **k):
        raise RuntimeError("no model offline")
    monkeypatch.setattr(llm, "call_rewriter", no_model)
    s = Session(session_id=f"ctx07-{time.time()}", user_id="u", created=time.time(), last_seen=time.time())

    def ask(q, scheme, entities):
        resolved.update(scheme=scheme, entities=entities)
        n = len(seen)
        out = asyncio.run(graph_turn(q, session=s))
        s.turns.append(build_turn(q, out))             # what the router does after the graph
        return seen[-1] if len(seen) > n else None
    return ask


def test_ki363_through_the_graph(chat):
    chat(STATEWIDE, "Focus Plus", {"year_key": 2025})
    assert chat("Break it down by district", "Focus Plus", {"year_key": 2025}) == \
        "How much Focus Plus amount was disbursed in FY 2025-26 by district"


def test_ki364_through_the_graph(chat):
    chat(EKH_Q, "PMAY-G", {"district": "EAST KHASI HILLS", "year_key": 2023})
    got = chat("Compare the number of beneficiaries with Ri Bhoi", "PMAY-G",
               {"district": "RI BHOI", "year_key": 2023})
    assert got == "Compare how many PMAY-G beneficiaries are there in East Khasi Hills and Ri Bhoi in FY 2023-24?"


def test_ki416_the_rewrite_guard_already_refuses_a_money_rewrite_of_a_houses_question():
    prev = "How many PMAY-G houses were sanctioned in East Khasi Hills in FY 2023-24?"
    allowed = "FY20?\n" + prev
    kw = dict(question="FY20?", allowed_text=allowed, denied_text="", allowed_schemes=["PMAY-G"])
    assert cp.rewrite_violation("How many PMAY-G houses were sanctioned in East Khasi Hills in FY 2019-20?",
                                **kw) is None
    assert cp.rewrite_violation("What was the PMAY-G sanctioned amount in East Khasi Hills in FY 2019-20?",
                                **kw) == "metric"

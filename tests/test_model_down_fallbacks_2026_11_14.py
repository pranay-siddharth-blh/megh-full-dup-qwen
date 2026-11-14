"""When the model server is down, a turn that needs no model still answers (2026-11-14).

The GPU behind the gateway crashed on 14 Nov. Every data question returned 502, also the ones a fixed query answers,
because three calls had no way out when the model call itself FAILED (each already had one for an unusable reply):

  extract_entity_mentions   the place span finder   -> the gazetteer's exact names (c07 _c07_mentions_by_rules)
  classify_intent           no cue decided          -> DATA, as for an unusable reply; and a figure across the schemes
                                                       ("the headline figure of every scheme") is DATA by cue
  compose_response          the answer writer       -> the deterministic answer built from the rows

Offline: the model calls are made to raise.
    .venv/Scripts/python.exe -m pytest tests/test_model_down_fallbacks_2026_11_14.py -q
"""
import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import annotations, entity_resolver, llm  # noqa: E402
from app import pipeline as p  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()
    annotations.load_all()


@pytest.fixture
def model_down(monkeypatch):
    calls = []

    async def down(*a, **k):
        calls.append(1)
        raise httpx.ConnectError("All connection attempts failed")
    for name in ("call_classifier", "call_response_composer", "call_rewriter"):
        monkeypatch.setattr(llm, name, down)
    return calls


def run(coro):
    return asyncio.run(coro)


# ── the place span finder ────────────────────────────────────────────────────

@pytest.mark.parametrize("q,want", [
    ("MGNREGA expenditure in West Garo Hills", {"district": "WEST GARO HILLS"}),
    ("Compare PMAY-G houses in Ri Bhoi and East Khasi Hills", {"districts": {"RI BHOI", "EAST KHASI HILLS"}}),
    ("How many MGNREGA person-days were generated in Mawphlang block in FY 2022-23?", {"block": "MAWPHLANG"}),
    ("PMAY-G houses in Dalu and Tikrikilla blocks", {"blocks": {"DALU", "TIKRIKILLA"}}),
    ("How many CM Elevate applications are there?", {}),
    ("What is the status distribution for Piggery?", {}),               # a sub-scheme is not a place
])
def test_exact_place_names_are_read_by_rule(q, want):
    got = p._c07_mentions_by_rules(q)
    got = {k: (set(v) if isinstance(v, list) else v) for k, v in got.items()}
    assert got == want


def test_a_failed_model_call_falls_back_to_the_rules(model_down):
    got = run(p.extract_entity_mentions("How many PMAY-G houses were completed in West Garo Hills?"))
    assert got == {"district": "WEST GARO HILLS"} and model_down      # the model was tried, then the rules


def test_a_working_model_is_still_the_one_that_answers(monkeypatch):
    async def model(prompt, **kw):
        return '{"block": "Selsella"}'
    monkeypatch.setattr(llm, "call_classifier", model)
    assert run(p.extract_entity_mentions("Focus Plus beneficiaries in Selsella")) == {"block": "Selsella"}


# ── intent ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", ["Give me the headline figure of every scheme", "In Ri Bhoi, give me each scheme's figures",
                               "numbers for all 8 schemes"])
def test_a_figure_across_the_schemes_is_data_by_cue(q, model_down):
    assert p._c13_intent_by_cues(q) == "DATA"
    assert run(p.classify_intent(q)) == "DATA" and not model_down       # no model call was needed


@pytest.mark.parametrize("q", ["What schemes are available?", "What is the eligibility for every scheme?"])
def test_a_listing_or_a_rules_question_is_not_made_data(q):
    assert p._c13_intent_by_cues(q) != "DATA"


def test_a_failed_classifier_defaults_like_an_unusable_reply(model_down):
    assert run(p._c13_intent_by_model("tell me something about the rural housing figures")) == "DATA"


# ── the answer writer ────────────────────────────────────────────────────────

def test_a_failed_composer_gives_the_deterministic_answer_with_every_figure(model_down):
    rows = [{"lgd_district": "WEST GARO HILLS", "houses": 33147}, {"lgd_district": "EAST KHASI HILLS", "houses": 23952},
            {"lgd_district": "RI BHOI", "houses": 17565}]
    out = run(p.compose_response("PMAY-G houses sanctioned by district",
                                 "SELECT lgd_district, COUNT(*) AS houses FROM curated.v_pmay GROUP BY 1 ORDER BY 2 DESC",
                                 rows, schemes=["PMAY-G"]))
    assert out and all(n in out for n in ("33,147", "23,952", "17,565")) and model_down


def test_a_failed_composer_gives_one_figure_plainly(model_down):
    out = run(p.compose_response("How many PMAY-G houses were sanctioned?", "SELECT COUNT(*) AS houses FROM curated.v_pmay",
                                 [{"houses": 171107}], schemes=["PMAY-G"]))
    assert "1,71,107" in out or "171,107" in out

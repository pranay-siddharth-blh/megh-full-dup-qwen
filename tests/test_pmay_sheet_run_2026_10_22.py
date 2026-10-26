"""PMAY-G sheet run 2026-10-22 (raw_uc/PMAY-G.xlsx, report new_docs/PMAY-G_Test_Report_2026-10-22.md):
regression tests for the failures, against the real functions.

1. D-060 (user rule 2026-10-22): the 126 zero-sanction registrations (is_placeholder) are
   beneficiaries — counted in the fixed path and in the model's SQL; never a "full release".
2. PMAY-OFF-019 / 016 / 012: "overall performance" / "financial summary" were rewritten by
   the place overview (c15) to "PMAY-G house status in <place>" — 019 answered 0/12 districts
   with a status breakdown, "till date" was dropped, "Amlarem block" came back as the village.
3. Follow-up "What about Rongara block?" after a Badimbari village answer kept the village
   (3 of 4 chats) — the model rewrite is rejected and the place is swapped deterministically.

Offline: the village index is stubbed with real names from curated.v_pmay."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from app import entity_resolver as er
from app import llm
from app import pipeline as p
from app.session_store import Turn

PM = ["PMAY-G"]


@pytest.fixture(autouse=True)
def _catalogue():
    er.load_all()          # districts / blocks: without them no place is found and the checks are empty


# ── 1. zero-sanction registrations are beneficiaries (D-060) ────────────────
def test_fixed_query_counts_placeholders_but_not_as_full_release():
    spec = p._pmay_facts_query("How many PMAY beneficiaries are there in Ri Bhoi?", PM, {"district": "RI BHOI"})
    sql = spec["sql"]
    assert "NOT is_placeholder" not in sql
    assert "COUNT(*) FILTER (WHERE is_placeholder) AS placeholders" in sql
    assert "sanctioned_amount > 0 AND COALESCE(amount_released, 0) >= sanctioned_amount) AS full_release" in sql
    assert "sanctioned_amount > 0 AND COALESCE(amount_released, 0) >= sanctioned_amount " \
           "AND NOT COALESCE(is_completed, FALSE)) AS full_not_done" in sql
    assert "COALESCE(amount_released, 0) = 0) AS no_release" in sql       # ₹0 received counts as none


def test_statewide_fixed_query_has_no_where_left():
    spec = p._pmay_facts_query("How many PMAY beneficiaries are there in Meghalaya?", PM, {})
    assert spec["dim"] == "state" and "\nWHERE" not in spec["sql"]


def test_year_question_still_filters_the_year():
    spec = p._pmay_facts_query("How many PMAY beneficiaries are there in Ri Bhoi in 2023-24?", PM,
                               {"district": "RI BHOI", "year_key": 2023})
    assert "year_key = $2" in spec["sql"]


def test_beneficiary_answer_includes_and_names_the_zero_sanction_records():
    spec = {"metrics": ["houses"], "word": "beneficiaries", "dim": "state", "entities": ["MEGHALAYA"],
            "date": None, "year_key": None, "calendar_year": None, "stages": [], "display": {}}
    row = {"entity_key": "MEGHALAYA", "name": "Meghalaya", "houses": 171107, "placeholders": 126}
    ans = p._pmay_facts_answer(spec, [row])
    assert "171,107" in ans and "including 126 registered with a sanctioned amount of ₹0" in ans


@pytest.mark.parametrize("sql", [
    "SELECT lgd_district, COUNT(*) AS beneficiaries FROM curated.v_pmay WHERE NOT is_placeholder GROUP BY 1 "
    "ORDER BY 2 DESC LIMIT 5",
    "SELECT COUNT(*) FROM curated.v_pmay WHERE is_placeholder = FALSE AND lgd_district = 'RI BHOI'",
    "SELECT COUNT(*) FROM curated.v_pmay WHERE lgd_block = 'DALU' AND (NOT is_placeholder)",
])
def test_model_sql_counts_placeholders(sql):
    out = p._pmay_count_placeholders(PM, sql)
    assert "is_placeholder" not in out and "COUNT(*)" in out


@pytest.mark.parametrize("sql", [
    # a full-release count: ₹0 released of ₹0 sanctioned is no "full release"
    "SELECT COUNT(*) FROM curated.v_pmay WHERE NOT is_placeholder "
    "AND COALESCE(amount_released, 0) >= sanctioned_amount",
    # a per-house average: the zeros would pull it down
    "SELECT AVG(sanctioned_amount) FROM curated.v_pmay WHERE NOT is_placeholder",
])
def test_model_sql_keeps_the_exclusion_where_it_matters(sql):
    assert p._pmay_count_placeholders(PM, sql) == sql


def test_model_sql_rewrite_is_pmay_only():
    sql = "SELECT COUNT(*) FROM curated.v_pmay WHERE NOT is_placeholder"
    assert p._pmay_count_placeholders(["MGNREGA"], sql) == sql
    assert p._pmay_count_placeholders(["PMAY-G", "MGNREGA"], sql) == sql


def test_rewrite_runs_in_the_scheme_rewrites():
    sql = "SELECT COUNT(*) AS beneficiaries FROM curated.v_pmay WHERE NOT is_placeholder AND lgd_district = 'RI BHOI'"
    out = asyncio.run(p._scheme_sql_rewrites("How many PMAY beneficiaries in Ri Bhoi?", PM,
                                             {"resolved": {"district": "RI BHOI"}, "unresolved": []}, sql))
    assert "is_placeholder" not in out


def test_prompt_rule_no_longer_demands_the_exclusion():
    from app import schema_context
    assert "always filter `WHERE NOT is_placeholder`" not in schema_context._PMAY_RULES
    assert "ARE beneficiaries" in schema_context._PMAY_RULES


# ── 2. "financial summary" / "overall performance" are not a place overview ──
@pytest.mark.parametrize("q", [
    "Give me the overall PMAY performance of East Garo Hills.",
    "Give me the PMAY financial summary for Ri Bhoi.",
    "Give me the PMAY financial summary for Amlarem.",
    "Give me the PMAY financial summary for Baghmara block till date.",
    "Give me the overall PMAY performance of East Garo Hills across all financial years.",
])
def test_pmay_summary_and_performance_keep_their_own_question(q):
    assert p.named_places(q)                       # the place is found, so the overview is really skipped
    assert p._overview_question(q) is None
    assert p._pmay_metrics(q, False) in (["sanctioned", "released", "remaining"],
                                         ["houses", "sanctioned", "released", "completed"])


def test_a_real_pmay_overview_is_still_one():
    q, _pre = p._overview_question("overview of Ri Bhoi under PMAY-G in 2023-24")
    assert q == "PMAY-G house status in Ri Bhoi district in FY 2023-24"


# ── 3. a coarser place in a follow-up replaces the village ──────────────────
_VILLAGES = {"BADIMBARI": frozenset({"SOUTH GARO HILLS"}), "CHIBINANG": frozenset({"WEST GARO HILLS"})}
_PREV_Q = "How many of the 14 PMAY-G beneficiaries in Badimbari across all financial years are completed?"
_BAD = "How many of the 14 PMAY-G beneficiaries in Badimbari across all financial years are completed in the Rongara block?"


@pytest.fixture
def _index(monkeypatch):
    monkeypatch.setattr(er, "_village_names", dict(_VILLAGES))


def _prev(q=_PREV_Q, resolved=None):
    return Turn(question=q, raw_question=q, route="data", schemes=PM,
                resolved_entities=resolved if resolved is not None else {"village_code": 276291})


def test_kept_village_is_detected(_index):
    assert p._c01_kept_finer_place("What about Rongara block?", _prev(), _BAD) == ["BADIMBARI"]
    ok = "How many of the PMAY-G beneficiaries in Rongara block across all financial years are completed?"
    assert p._c01_kept_finer_place("What about Rongara block?", _prev(), ok) is None
    # a village follow-up is not a coarser place
    assert p._c01_kept_finer_place("in chibinang", _prev(), _BAD) is None


def test_forced_swap_to_the_block_and_to_the_district(_index):
    out = p._place_swap_rewrite(_prev(), "What about Rongara block?", force=True)
    assert "Rongara block" in out and "Badimbari" not in out
    blk = Turn(question=out, raw_question="What about Rongara block?", route="data", schemes=PM,
               resolved_entities={"block": "RONGARA"})
    out2 = p._place_swap_rewrite(blk, "And South Garo Hills district?", force=True, district=True)
    assert "South Garo Hills district" in out2 and "Rongara" not in out2
    # otherwise a district is still left to the model rewrite (D-056)
    assert p._place_swap_rewrite(blk, "And South Garo Hills district?") is None
    assert p._place_swap_rewrite(blk, "And South Garo Hills district?", force=True) is None


def test_rewrite_that_keeps_the_village_is_replaced(_index, monkeypatch):
    async def model(_prompt):
        return _BAD
    monkeypatch.setattr(llm, "call_rewriter", model)
    out = asyncio.run(p.rewrite_followup("What about Rongara block?", _prev()))
    assert "Rongara block" in out and "Badimbari" not in out

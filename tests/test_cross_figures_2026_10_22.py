"""
Cross-scheme figures worked out in code (D-066, KI-387..392) — the 60-case
cross-scheme UAT sheet (`raw_uc/cross_scheme.xlsx`), re-test 2026-10-22: 20/60.

The model-written per-scheme answers (D-062) got each scheme's figure right and
then never added, ranked or compared them (combined totals, district rankings,
winner / second per district, "districts where X > Y"); they ignored "excluding";
dropped MGNREGA; gave PMAY-G's sanctioned amount and FOCUS's producer groups as the
headline figures; copied one scheme's average onto another; cut FOCUS to its
village-mapped rows. Every test calls the real function; the database is a fake
that answers each fixed query from canned rows, nothing needs the VPN.
"""
import asyncio

import pytest

from app import cross_figures as cf
from app import entity_resolver
from app import pipeline as p

M = p._SCHEME_NAME_MATCHER
FOUR = ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy"]


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()


# ── exclusions are read first (KI-388) ────────────────────────────────────────

@pytest.mark.parametrize("q, excluded, kept", [
    ("Leaving out MGNREGA and CM-ELEVATE, which scheme has the most beneficiaries in each district?",
     ["MGNREGA", "CM Elevate", "CM Elevate Legacy"], "Which scheme has the most beneficiaries in each district?"),
    ("What is the scheme-wise spending in South Garo Hills, excluding CM-ELEVATE?",
     ["CM Elevate", "CM Elevate Legacy"], "What is the scheme-wise spending in South Garo Hills?"),
    ("Excluding MGNREGA, which districts have the most beneficiaries across PMAY-G, Focus+ and FOCUS?",
     ["MGNREGA"], "Which districts have the most beneficiaries across PMAY-G, Focus+ and FOCUS?"),
    ("Leaving out CM Elevate Legacy, which scheme has spent the most money in Meghalaya so far?",
     ["CM Elevate Legacy", "CM Elevate"], "Which scheme has spent the most money in Meghalaya so far?"),
])
def test_exclusions_are_taken_out(q, excluded, kept):
    out, text = p._cross_exclusions(q)
    assert out == excluded
    assert text == kept


def test_no_exclusion_leaves_the_question_alone():
    q = "Compare MGNREGA and PMAY-G spending without delay"
    assert p._cross_exclusions(q) == ([], q)      # "without" + no scheme name
    assert p._cross_exclusions("How much did MGNREGA spend?") == ([], "How much did MGNREGA spend?")


def test_exclusions_leave_the_four_main_schemes():
    text = "Which scheme has the most beneficiaries in each district?"
    assert p._cross_after_exclusions(text, [], None, ["MGNREGA", "CM Elevate", "CM Elevate Legacy"]) == \
        ["PMAY-G", "Focus Plus", "Focus Legacy"]
    # named schemes win over the default
    text = "Which districts have the most beneficiaries across PMAY-G, Focus+ and FOCUS?"
    named = [s for s, pat in M.items() if pat.search(text)]
    cross = p.cross_scheme.detect(text, named)
    assert p._cross_after_exclusions(text, named, cross, ["MGNREGA"]) == ["PMAY-G", "Focus Plus", "Focus Legacy"]


@pytest.mark.parametrize("q, data", [
    ("What is the coverage of NREGA, PMAY-G and Focus+ in Dadenggiri block?", True),          # T09.2
    ("What is the scheme-wise spending in South Garo Hills, excluding CM-ELEVATE?", True),     # T11.2
    ("Excluding CM-ELEVATE, which scheme reaches the most villages?", True),                    # T13.2
    ("Compare the objectives of MGNREGA and PMAY-G", False),
    ("What is the coverage of MGNREGA and PMAY-G?", False),        # no place: may be eligibility
])
def test_cross_figure_questions_are_data(q, data):
    assert p._cross_figures_question(q) is data


def test_a_bare_focus_in_a_comparison_is_asked(monkeypatch):
    # T09.3: "… MGNREGA, PMAY-G and FOCUS in Songsak block" ran without FOCUS, unsaid
    async def _none(*a, **k):
        return None

    async def _same(q, *a, **k):
        return q
    monkeypatch.setattr(p, "_geo_lookup_answer", _none)
    monkeypatch.setattr(p, "_mask_scheme_words_in_village_name", _same)
    monkeypatch.setattr(p, "_mask_village_names", _same)
    d = p._new_data_turn("Compare coverage of MGNREGA, PMAY-G and FOCUS in Songsak block.")
    with pytest.raises(p.ClarificationNeeded) as e:
        asyncio.run(p._data_scheme_stage(d))
    assert e.value.rule == "focus-scheme-ambiguous"
    # beside Focus+ a bare FOCUS is still Focus Legacy (KI-281)
    d = p._new_data_turn("Which has more beneficiaries, Focus+ or FOCUS?")
    assert asyncio.run(p._data_scheme_stage(d)) is None
    assert d["cross"]["schemes"] == ["Focus Plus", "Focus Legacy"]


# ── the plan ──────────────────────────────────────────────────────────────────

def _plan(q, schemes=FOUR, resolved=None):
    return cf.plan(q, schemes, resolved or {}, {}, M)


def test_plan_combined_total_T01_1():
    pl = _plan("What is the total beneficiary count across MGNREGA, PMAY-G, Focus+ and FOCUS?")
    assert pl.combined and pl.measures == ["count"] and pl.op == "list" and not pl.by_district


def test_plan_condition_T03_3():
    pl = _plan("In which districts does Focus+ have more beneficiaries than PMAY-G?", ["PMAY-G", "Focus Plus"])
    assert pl.op == "condition" and pl.cond == ("Focus Plus", "PMAY-G", True)


@pytest.mark.parametrize("q, op", [
    ("Which scheme has the highest beneficiary count in each district (MGNREGA, PMAY-G, Focus+, FOCUS)?", "winner"),
    ("For each district, which of PMAY-G, Focus+ and FOCUS comes second after MGNREGA in beneficiary count?",
     "second"),
    ("Top 3 districts by total beneficiaries across MGNREGA, PMAY-G, Focus+ and FOCUS?", "rank_districts"),
    ("Which districts have the highest concentration of beneficiaries across MGNREGA, PMAY-G, Focus+ and FOCUS?",
     "rank_districts"),
    ("Show district-wise beneficiary counts for Focus Plus, FOCUS and PMAY Gramin.", "list"),
])
def test_plan_district_ops(q, op):
    pl = _plan(q)
    assert pl.by_district and pl.op == op


def test_plan_bigger_means_beneficiaries_T18_3():
    pl = _plan("For each district, which is bigger: Focus+ or FOCUS?", ["Focus Plus", "Focus Legacy"])
    assert pl.op == "winner" and pl.first == "count"


def test_plan_measures():
    assert _plan("How many beneficiaries did MGNREGA, PMAY-G, Focus+ and FOCUS each cover in FY 2025-26?",
                 resolved={"year_key": 2025}).measures == ["count"]     # "cover" is not coverage
    pl = _plan("Among PMAY-G, Focus+ and FOCUS, which gave the most financial assistance, and how much per "
               "beneficiary?", ["PMAY-G", "Focus Plus", "Focus Legacy"])
    assert pl.avg and "money" in pl.measures and pl.op == "leader"
    pl = _plan("Which of MGNREGA, PMAY-G, Focus+ and FOCUS has the widest coverage across the districts of Meghalaya?")
    assert pl.measures == ["villages"] and not pl.by_district
    pl = _plan("Compare the coverage of MGNREGA, PMAY-G and Focus+ in Mylliem block.",
               ["MGNREGA", "PMAY-G", "Focus Plus"], {"block": "MYLLIEM"})
    assert pl.block == "MYLLIEM" and pl.first == "villages" and set(pl.measures) == {"count", "money", "villages"}
    pl = _plan("What is the performance of MGNREGA, PMAY-G, Focus+ and FOCUS in North Garo Hills?",
               resolved={"district": "NORTH GARO HILLS"})
    assert pl.measures == ["count", "money"] and pl.place_label == "North Garo Hills district"


@pytest.mark.parametrize("q, schemes, resolved", [
    ("I have a query. Breakdown into I want top ten highest villages in Mgnrega and pmay", ["MGNREGA", "PMAY-G"], {}),
    ("top 5 blocks in MGNREGA and PMAY-G by beneficiaries", ["MGNREGA", "PMAY-G"], {}),
    ("Compare MGNREGA, PMAY-G and CM-ELEVATE", ["MGNREGA", "PMAY-G", "CM Elevate"], {}),
    ("Compare MGNREGA and PMAY-G in Pamila village", ["MGNREGA", "PMAY-G"], {"village_code": 274001}),
    ("Compare MGNREGA and PMAY-G year by year", ["MGNREGA", "PMAY-G"], {}),
])
def test_other_shapes_stay_on_the_model_path(q, schemes, resolved):
    assert cf.plan(q, schemes, resolved, {}, M) is None


# ── the figures and the answer ────────────────────────────────────────────────

_DIST = {
    "MGNREGA": {"WEST GARO HILLS": (261221, 792.42), "RI BHOI": (112602, 183.16)},
    "PMAY-G": {"WEST GARO HILLS": (33147, 425.01), "RI BHOI": (17565, 222.85)},
    "Focus Plus": {"WEST GARO HILLS": (35059, 39.16), "RI BHOI": (419, 0.5238)},
    "Focus Legacy": {"WEST GARO HILLS": (21867, 10.93), "RI BHOI": (9858, 4.93)},
}
_VIEW = {"v_employment": "MGNREGA", "v_expenditure": "MGNREGA", "v_pmay": "PMAY-G",
         "v_focus_plus": "Focus Plus", "v_focus_legacy": "Focus Legacy"}


def _fake_db(monkeypatch, seen=None):
    async def fetch_rows(sql, params):
        if seen is not None:
            seen.append(sql)
        if "DISTINCT year_key AS y" in sql:
            s = next(v for k, v in _VIEW.items() if k in sql)
            return [{"y": y} for y in ((2017, 2023) if s == "PMAY-G" else (2022, 2025))]
        s = next(v for k, v in _VIEW.items() if k in sql)
        grouped = "GROUP BY" in sql
        keys = list(_DIST[s]) if grouped else [None]
        rows = []
        for k in keys:
            vals = [_DIST[s][x] for x in (_DIST[s] if k is None else [k])]
            ben, money = sum(v[0] for v in vals), sum(v[1] for v in vals)
            rows.append({"k": k, "ben": ben, "money": money, "villages": 10, "districts": 2, "blocks": 5,
                         "completed": ben // 2, "sanctioned": money * 1.02, "pgs": ben // 8, "payments": ben * 4})
        return rows
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)


def _ask(q, schemes=FOUR, resolved=None):
    return asyncio.run(cf.answer(_plan(q, schemes, resolved)))


def test_combined_total_is_given(monkeypatch):
    _fake_db(monkeypatch)
    out = _ask("What is the total beneficiary count across MGNREGA, PMAY-G, Focus+ and FOCUS?")
    total = sum(sum(v[0] for v in _DIST[s].values()) for s in FOUR)
    assert f"**Combined: {cf.indian(total)}**" in out["answer"]
    assert "3,73,823 households given work" in out["answer"]     # Indian grouping
    assert "31,725 members in 3,965 producer groups" in out["answer"]   # members, not PGs


def test_combined_money(monkeypatch):
    _fake_db(monkeypatch)
    out = _ask("What is the total money released under Focus Plus, FOCUS and PMAY Gramin combined?",
               ["PMAY-G", "Focus Plus", "Focus Legacy"])
    assert "**Combined: ₹" in out["answer"]
    assert "released (sanctioned" in out["answer"]      # PMAY-G money is the amount released


def test_condition_districts(monkeypatch):
    _fake_db(monkeypatch)
    out = _ask("In which districts does Focus+ have more beneficiaries than PMAY-G?", ["PMAY-G", "Focus Plus"])
    assert "Focus Plus has more beneficiaries than PMAY-G in **1 of 2 districts**: West Garo Hills " \
           "(35,059 vs 33,147)." in out["answer"]


def test_winner_and_second(monkeypatch):
    _fake_db(monkeypatch)
    out = _ask("Leaving out MGNREGA, which scheme has the most beneficiaries in each district?",
               ["PMAY-G", "Focus Plus", "Focus Legacy"])
    assert "- West Garo Hills: **Focus Plus** (35,059); next PMAY-G (33,147)" in out["answer"]
    assert "- Ri Bhoi: **PMAY-G** (17,565); next Focus Legacy (9,858 members)" in out["answer"]
    out = _ask("For each district, which of PMAY-G, Focus+ and FOCUS comes second after MGNREGA in beneficiary count?")
    assert "- West Garo Hills: **Focus Plus** (35,059); first MGNREGA (2,61,221)" in out["answer"]


def test_rank_districts(monkeypatch):
    _fake_db(monkeypatch)
    out = _ask("Top 1 districts by total beneficiaries across MGNREGA, PMAY-G, Focus+ and FOCUS?")
    assert "1. **West Garo Hills**: 3,51,294" in out["answer"]
    assert "Lowest: Ri Bhoi" in out["answer"]


def test_lakh_below_one_crore_and_totals_from_the_state_query(monkeypatch):
    _fake_db(monkeypatch)
    out = _ask("District-wise financial summary for MGNREGA, PMAY-G, Focus+ and FOCUS.")
    assert "Focus Plus ₹52.38 lakh" in out["answer"]
    assert "Total ₹" in out["answer"]


def test_average_per_beneficiary_is_each_schemes_own(monkeypatch):
    _fake_db(monkeypatch)
    out = _ask("Put Focus+ and FOCUS side by side: beneficiaries, total amount and average per beneficiary.",
               ["Focus Plus", "Focus Legacy"])
    fp = sum(v[1] for v in _DIST["Focus Plus"].values()) * 1e7 / sum(v[0] for v in _DIST["Focus Plus"].values())
    fl = sum(v[1] for v in _DIST["Focus Legacy"].values()) * 1e7 / sum(v[0] for v in _DIST["Focus Legacy"].values())
    assert f"₹{cf.indian(fp)} per beneficiary" in out["answer"]
    assert f"₹{cf.indian(fl)} per member" in out["answer"]


def test_a_year_a_scheme_does_not_hold_is_said(monkeypatch):
    _fake_db(monkeypatch)
    out = _ask("How many beneficiaries did MGNREGA, PMAY-G, Focus+ and FOCUS each cover in FY 2025-26?",
               resolved={"year_key": 2025})
    assert "PMAY-G has no data for FY 2025-26 (its data covers FY 2017-18 to 2023-24)" in out["answer"]
    assert out["answer"].startswith("**All of Meghalaya, FY 2025-26**")


def test_unresolved_rows_leave_only_the_village_count(monkeypatch):
    # T20.1: FOCUS 94,116 members / ₹47.06 crore = the village-mapped rows only
    seen = []
    _fake_db(monkeypatch, seen)
    _ask("Give me an overall performance comparison of MGNREGA, PMAY-G, Focus+ and FOCUS based on coverage "
         "and financial performance.")
    fl = next(s for s in seen if "v_focus_legacy" in s and "SUM(no_of_pg_members)" in s)
    where = fl.split(" WHERE ", 1)[1]
    assert "Unresolved" not in where
    assert "FILTER (WHERE village_code > 0 AND entity_type <> 'Unresolved')" in fl


def test_focus_plus_is_grouped_by_its_source_district_names(monkeypatch):
    # KI-393: one district column per scheme, every query
    seen = []
    _fake_db(monkeypatch, seen)
    _ask("Compare Focus+ and FOCUS beneficiaries in West Garo Hills.", ["Focus Plus", "Focus Legacy"],
         {"district": "WEST GARO HILLS"})
    assert any("v_focus_plus" in s and "UPPER(district_name_raw) = ANY($1::text[])" in s for s in seen)
    assert any("v_focus_legacy" in s and "UPPER(lgd_district) = ANY($1::text[])" in s for s in seen)


def test_indian_grouping():
    assert cf.indian(1873378) == "18,73,378"
    assert cf.indian(999) == "999"
    assert cf.rupees_crore(3628.6657) == "₹3,628.67 crore"
    assert cf.rupees_crore(0.3538) == "₹35.38 lakh"


# ── T13.3: a ranked Focus Plus district breakdown leaves out the no-district record ──

def test_focusplus_ranked_district_breakdown_drops_the_null_district():
    sql = ("SELECT lgd_district, COUNT(DISTINCT village_code) AS villages_covered FROM curated.v_focus_plus "
           "GROUP BY lgd_district ORDER BY villages_covered ASC LIMIT 10")
    out = p._focusplus_district_group_not_null(["Focus Plus"], sql)
    assert "WHERE NOT lgd_district IS NULL" in out
    # a plain list keeps the row (its figures add up to the statewide total)
    plain = "SELECT lgd_district, COUNT(*) AS n FROM curated.v_focus_plus GROUP BY lgd_district"
    assert p._focusplus_district_group_not_null(["Focus Plus"], plain) == plain
    # already filtered, another scheme: unchanged
    done = sql.replace("GROUP BY", "WHERE lgd_district IS NOT NULL GROUP BY")
    assert p._focusplus_district_group_not_null(["Focus Plus"], done) == done
    assert p._focusplus_district_group_not_null(["Focus Legacy"], sql) == sql


def test_an_unasked_having_threshold_is_dropped_from_a_ranking():
    q = "Are there districts where Focus+ coverage is very low?"
    sql = ("SELECT lgd_district, COUNT(DISTINCT village_code) AS villages_covered FROM curated.v_focus_plus "
           "GROUP BY lgd_district HAVING COUNT(DISTINCT village_code) < 10 ORDER BY villages_covered ASC LIMIT 10")
    out = p._unasked_having_threshold(q, sql)
    assert "HAVING" not in out and "ORDER BY villages_covered" in out
    # a threshold the user gave stays; a HAVING without a ranking stays
    assert p._unasked_having_threshold("districts with fewer than 10 villages in Focus+", sql) == sql
    flat = sql.replace(" ORDER BY villages_covered ASC LIMIT 10", "")
    assert p._unasked_having_threshold(q, flat) == flat

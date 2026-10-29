"""Chat UI audit 2026-10-29, sections G and B (backend half): what may be added
up, the backend chart hint (the UI applies the same rule, frontend/tests/audit.test.js),
the union / overlap of villages, statewide totals, and the scheme comparisons.
Rows are the shapes the real queries return."""
import asyncio
import json
from pathlib import Path

import pytest

from app import cross_figures as cf
from app import measure_kinds as mk
from app import pipeline as p

M = p._SCHEME_NAME_MATCHER
MP = ["MGNREGA", "PMAY-G"]
ROOT = Path(__file__).resolve().parents[1]


def test_frontend_copy_of_the_measure_kinds_matches():
    """One list for both sides: the UI's copy must equal app/measure_kinds.json."""
    js = (ROOT / "frontend/src/chat/measureKinds.js").read_text(encoding="utf-8")
    body = js[js.index("{", js.index("MEASURE_KINDS")):js.rindex("}") + 1]
    backend = {k: v for k, v in json.loads((ROOT / "app/measure_kinds.json").read_text(encoding="utf-8")).items()
               if not k.startswith("_")}
    assert json.loads(body) == backend


@pytest.mark.parametrize("col, kind", [
    ("villages", "distinct"), ("households_employed", "distinct"), ("beneficiaries", "distinct"),
    ("no_of_pg_members", "distinct"), ("person_days", "flow"), ("total_exp_lakh", "flow"), ("amount_crore", "flow"),
    ("houses_completed", "flow"), ("job_cards", "stock"), ("completion rate (%)", "rate"), ("women_participation", "rate"),
    ("yoy_growth", "rate"), ("max_wage", "rate"), ("avg_days_per_household", "rate"),
])
def test_measure_kinds(col, kind):
    assert mk.measure_kind(col) == kind


def test_what_adds_along_which_dimension():
    assert mk.can_add("villages", "place") and not mk.can_add("villages", "period") and not mk.can_add("villages", "scheme")
    assert mk.can_add("person_days", "period") and not mk.can_add("person_days", "scheme")
    assert mk.can_add("job_cards", "place") and not mk.can_add("job_cards", "period")
    assert not mk.can_add("completion_pct", "place")


# ── _chart_hint: no stack that adds what must not be added ────────────────────
def _rows(a, b, v, avals, bvals):
    return [{a: x, b: y, v: 10 + i} for i, (x, y) in enumerate((x, y) for x in avals for y in bvals)]


@pytest.mark.parametrize("q, rows, want", [
    # G-4: villages with work by district and year — a village in both years counted twice
    ("villages with work by district and year", _rows("district", "year_key", "villages", ["A", "B"], [2023, 2024]),
     None),
    # A-4 / B-3: scheme as a label — households + houses
    ("MGNREGA and PMAY-G beneficiaries by year", _rows("financial_year", "scheme", "beneficiaries",
                                                        ["2022-23", "2023-24"], ["MGNREGA", "PMAY-G"]), None),
    ("beneficiaries district wise in all schemes", _rows("scheme", "district", "beneficiaries",
                                                          ["MGNREGA", "PMAY-G"], ["A", "B"]), None),
    # C-6: job cards are a running stock; D-7 / D-13: participation %, maxima
    ("job cards by district for 2 years", _rows("district", "year_key", "job_cards", ["A", "B"], [2023, 2024]), None),
    ("women participation by district and year", _rows("district", "financial_year", "women_participation",
                                                        ["A", "B"], ["2023-24", "2024-25"]), None),
    ("maximum wage by district and year", _rows("district", "financial_year", "max_wage", ["A", "B"],
                                                ["2023-24", "2024-25"]), None),
    # J-6: a ranking is a ranked list, not a stack coloured by block
    ("top 5 villages in Ri Bhoi by person days", _rows("village_name", "block_name", "person_days",
                                                        ["V1", "V2", "V3"], ["UMLING"]), None),
    # a flow by district and year still stacks
    ("person days by district and year", _rows("district", "year_key", "person_days", ["A", "B"], [2023, 2024]),
     "stacked"),
])
def test_stacked_only_when_the_measure_adds_along_the_series(q, rows, want):
    assert p._chart_hint(q, q, rows) == want


def test_year_key_and_financial_year_are_one_period():                                  # J-11
    rows = [{"year_key": y, "financial_year": f"{y}-{(y + 1) % 100}", "person_days": 5}
            for y in (2022, 2023, 2024)]
    assert p._chart_hint("person days in Umpling village across all years", "", rows) is None


# ── G-8 / I-5: the union and the overlap of villages ─────────────────────────
@pytest.fixture
def village_db(monkeypatch):
    seen = []

    async def fetch_rows(sql, params):
        seen.append(sql)
        if "dim_geography" in sql:
            return [{"village_code": c, "lgd_village_name": f"V{c}", "lgd_block": "MYLLIEM",
                     "lgd_district": "EAST KHASI HILLS"} for c in params[0][:1000]]   # the query's LIMIT 1000
        # MGNREGA reaches villages 1-5000, PMAY-G 3001-9000
        return [{"v": v} for v in (range(1, 5001) if "v_employment" in sql else range(3001, 9001))]
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)
    return seen


def test_villages_in_either_scheme_are_counted_once(village_db):
    pl = cf.plan("How many villages are covered by MGNREGA or PMAY-G?", MP, {}, {}, M)
    assert pl.op == "overlap" and not pl.list_villages
    out = asyncio.run(cf.answer(pl))
    assert "**9,000 villages** have at least one of MGNREGA, PMAY-G." in out["answer"]      # not 5,000 + 6,000
    assert out["rows"] == [{"coverage": "Both", "villages": 2000}, {"coverage": "MGNREGA only", "villages": 3000},
                           {"coverage": "PMAY-G only", "villages": 4000}]
    assert all("COUNT" not in s and "DISTINCT village_code" in s for s in village_db)


def test_villages_where_both_are_present_are_listed(village_db):
    pl = cf.plan("villages in East Khasi Hills where both MGNREGA and PMAY-G are present", MP,
                 {"district": "EAST KHASI HILLS"}, {}, M)
    assert pl.op == "overlap" and pl.list_villages                                       # V5
    out = asyncio.run(cf.answer(pl))
    assert len(out["rows"]) == 1000 and out["rows"][0]["village"] == "V3001"
    assert "(the first 1,000)" in out["answer"]


# ── G-12: the table's Total is the statewide figure the text gives ───────────
_DIST = {"MGNREGA": {"RI BHOI": 100, "TURA": 200}, "PMAY-G": {"RI BHOI": 10, "TURA": 20}}


def test_district_table_carries_the_statewide_totals(monkeypatch):
    async def fetch_rows(sql, params):
        s = "PMAY-G" if "v_pmay" in sql else "MGNREGA"
        base = {"money": 1.0, "villages": 1, "districts": 2, "blocks": 2, "completed": 1, "sanctioned": 1.0}
        if "GROUP BY" in sql:
            return [{"k": k, "ben": v, **base} for k, v in _DIST[s].items()]
        return [{"k": None, "ben": sum(_DIST[s].values()) + 7, **base}]   # +7 records with no district
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)
    out = asyncio.run(cf.answer(cf.plan("MGNREGA and PMAY-G beneficiaries district wise", MP, {}, {}, M)))
    assert out["totals"] == {"MGNREGA": {"beneficiaries": 307}, "PMAY-G": {"beneficiaries": 37}}


# ── B: comparing schemes ─────────────────────────────────────────────────────
def _plan(q, r=None):
    return cf.plan(q, MP, r or {}, {}, M)


def test_person_days_go_to_the_per_scheme_path():                                       # B-7
    assert _plan("Compare MGNREGA and PMAY-G person days") is None
    assert _plan("MGNREGA and Focus Plus person days in East Khasi Hills", {"district": "EAST KHASI HILLS"}) is None


def test_vs_reads_like_compare():                                                       # B-14
    a = _plan("MGNREGA vs PMAY-G in East Khasi Hills", {"district": "EAST KHASI HILLS"})
    b = _plan("compare MGNREGA and PMAY-G in East Khasi Hills", {"district": "EAST KHASI HILLS"})
    assert a.measures == b.measures == ["count", "money"]


@pytest.fixture
def state_db(monkeypatch):
    async def fetch_rows(sql, params):
        ben = 171107 if "v_pmay" in sql else 1494437
        return [{"k": None, "ben": ben, "money": 120.0 if "v_pmay" in sql else 1050.0, "villages": 5,
                 "districts": 12, "blocks": 46, "completed": 1, "sanctioned": 130.0}]
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)


def test_better_names_no_winner_on_size(state_db):                                      # B-8
    out = asyncio.run(cf.answer(_plan("Which is better, MGNREGA or PMAY-G?")))
    assert "neither is better on size alone" in out["answer"]
    assert "has the most" not in out["answer"]


def test_least_says_fewer(state_db):                                                    # B-9
    out = asyncio.run(cf.answer(_plan("Which scheme has the least beneficiaries, MGNREGA or PMAY-G?")))
    assert "**PMAY-G** has the lowest (1,71,107), 13,23,330 fewer than MGNREGA" in out["answer"]


def test_money_per_beneficiary_is_its_own_column(state_db):                            # B-10
    out = asyncio.run(cf.answer(_plan("Money per beneficiary in MGNREGA vs PMAY-G")))
    assert [r["rupees_per_beneficiary"] for r in out["rows"]] == [7026, 7013]


def test_each_scheme_says_what_its_figure_is(state_db):                               # G-9, B-11
    out = asyncio.run(cf.answer(_plan("Compare beneficiaries and money in MGNREGA and PMAY-G")))
    notes = out["measure_notes"]
    assert notes["MGNREGA"]["beneficiaries"].startswith("household-years")
    assert notes["PMAY-G"]["amount_crore"] == "money released"
    assert set(out["rows"][0]) == {"scheme", "beneficiaries", "amount_crore"}          # the rows keep their shape


@pytest.mark.parametrize("col, label", [("year_key", True), ("district_code", True), ("financial_year_short", True),
                                        ("month_num", True), ("houses_per_year", False),
                                        ("person_days_this_year", False), ("beneficiary_key_count", False),
                                        ("pin_count", False), ("rank_score", False)])
def test_label_words_mark_a_label_only_at_the_end(col, label):                          # X-12 (backend half)
    assert mk.is_label_col(col) is label


def test_a_per_year_measure_is_charted():
    rows = [{"district": d, "houses_per_year": n} for d, n in (("A", 5), ("B", 7))]
    assert p._chart_hint("houses per year by district as a bar chart", "", rows) == "bar"
    rows = [{"district": "A", "financial_year": "2023-24", "houses_per_year": 5},
            {"district": "B", "financial_year": "2023-24", "houses_per_year": 7}]
    # "per" is a rate: two labels, one rate measure -> never stacked
    assert p._chart_hint("houses per year by district and year", "", rows) is None


def test_banner_names_only_the_schemes_with_figures():                                 # H-7
    r = {"route": "data", "schemes": ["MGNREGA", "Focus Plus"], "sql": "SELECT 1",
         "resolved_entities": {"year_key": 2023}, "schemes_with_data": ["MGNREGA"]}
    p._attach_scope_banner(r, None)
    assert r["scope_banner"] == "MGNREGA (Focus Plus: no data) · All of Meghalaya · FY 2023-24"


def test_descending_sorts_put_missing_figures_last():                                  # E-5
    from app import sql_ast
    sql = ("SELECT village_name, SUM(women_persondays) AS w FROM curated.v_employment "
           "WHERE year_key = 2025 GROUP BY 1 ORDER BY w DESC LIMIT 7")
    assert "ORDER BY w DESC NULLS LAST LIMIT 7" in sql_ast.nulls_last_on_desc(sql)
    asc = "SELECT a FROM t ORDER BY a"
    assert sql_ast.nulls_last_on_desc(asc) == asc                                        # untouched, byte for byte
    out = asyncio.run(p._scheme_sql_rewrites("top 7 villages by women person days", ["MGNREGA"],
                                             {"resolved": {}}, sql))
    assert "DESC NULLS LAST" in out


def test_comparison_pause_chips_ask_for_the_figures():                                 # F-2
    e = p._scheme_comparison_clarification("compare beneficiaries of the schemes")
    assert e.options[0] == {"label": "MGNREGA vs PMAY-G", "question": "Compare beneficiaries in MGNREGA and PMAY-G"}
    e = p._scheme_comparison_clarification("what is the difference between the schemes")
    assert e.options[0]["question"] == "difference between MGNREGA and PMAY-G"


def test_next_step_chips_keep_the_year_and_never_repeat_the_question():              # F-10, F-12
    from app import followups
    opts = followups.build_followups("data", "MGNREGA person days in East Khasi Hills in 2023-24", ["MGNREGA"],
                                     {"district": "EAST KHASI HILLS", "year_key": 2023})
    assert any(o["question"].endswith("in East Khasi Hills in FY 2023-24?") for o in opts)
    assert all("2023-24" in o["question"] or "years" in o["question"] for o in opts)
    opts = followups.build_followups("data", "Focus Plus amount disbursed in Ri Bhoi", ["Focus Plus"],
                                     {"district": "RI BHOI"})
    assert not any(o["question"] == "How much has been disbursed under Focus Plus in Ri Bhoi?" for o in opts)

"""Chat UI audit 2026-10-29, sections I and J: how cross-scheme and one-scheme
questions are read before any data is fetched.

Each wording runs through the real planner (cross_figures.plan), the real
per-year rewrite (conversation_layer.per_year_plan) and the real year readers.
The figures come from a fake db.fetch_rows that answers cross_figures' own SQL
in the shape the real query returns ({k, ben, money, villages, ...})."""
import asyncio
import time

import pytest

from app import conversation_layer as cl
from app import cross_figures as cf
from app import pipeline as p
from app.session_store import Session

M = p._SCHEME_NAME_MATCHER
MP = ["MGNREGA", "PMAY-G"]
FOUR = ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy"]
ALL6 = ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy", "CM Elevate Legacy"]
EKH = {"district": "EAST KHASI HILLS"}


def _plan(q, schemes=MP, resolved=None):
    return cf.plan(q, schemes, resolved or {}, {}, M)


# ── I: the 46 + 30 cross-scheme wordings (path, by_district, low, top_n) ─────
# (question, schemes, resolved, op or None for the model path, low, top_n)
WORDINGS = [
    ("top 5 districts by beneficiaries in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 5),       # D1
    ("bottom 5 districts by beneficiaries in MGNREGA and PMAY-G", MP, {}, "rank_districts", True, 5),     # D2
    ("lowest 5 districts in MGNREGA and PMAY-G", MP, {}, "rank_districts", True, 5),                      # D3
    ("5 lowest districts in MGNREGA and PMAY-G", MP, {}, "rank_districts", True, 5),                      # D4
    ("which district has the lowest beneficiaries in MGNREGA and PMAY-G", MP, {}, "rank_districts", True, None),
    ("top 3 districts by money spent in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 3),         # D6
    ("top 5 districts by villages covered in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 5),    # D7
    ("worst performing districts in MGNREGA and PMAY-G", MP, {}, "rank_districts", True, None),           # D8
    ("top ten districts in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 10),                     # D9
    ("top 5 districts in MGNREGA and top 5 districts in PMAY-G", MP, {}, "rank_districts", False, 5),     # D10
    ("least 5 districts mgnrega pmay", MP, {}, "rank_districts", True, 5),                                # D11
    ("Top-5 districts in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 5),                        # D13
    ("districts with highest MGNREGA and PMAY-G beneficiaries", MP, {}, "rank_districts", False, None),   # D14
    ("rank districts by MGNREGA and PMAY-G money", MP, {}, "rank_districts", False, None),                # D15
    ("which districts are weakest in MGNREGA and PMAY-G", MP, {}, "rank_districts", True, None),          # D16
    ("poorest 3 districts for MGNREGA and PMAY-G", MP, {}, "rank_districts", True, 3),                    # D17
    ("top 5 districts by amount in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 5),              # D18
    ("top 5 villages in East Khasi Hills for MGNREGA and PMAY-G", MP, EKH, None, None, None),             # V1
    ("lowest 5 villages in East Khasi Hills in MGNREGA and PMAY-G", MP, EKH, None, None, None),           # V2
    ("top 5 blocks in West Garo Hills for MGNREGA and PMAY-G", MP, {"district": "WEST GARO HILLS"}, None, None, None),
    ("lowest block in each district for MGNREGA and PMAY-G", MP, {}, None, None, None),                   # B2, I-3
    ("compare MGNREGA and PMAY-G in East Khasi Hills", MP, EKH, "leader", False, None),                   # S1
    ("top 5 districts in MGNREGA and PMAY-G in 2023-24", MP, {"year_key": 2023}, "rank_districts", False, 5),
    ("districts where MGNREGA beneficiaries are more than PMAY-G", MP, {}, "condition", False, None),     # C1
    ("which districts have fewer MGNREGA beneficiaries than PMAY-G", MP, {}, "condition", False, None),   # C4
    ("lowest 5 districts in MGNREGA, PMAY-G and Focus Plus", ["MGNREGA", "PMAY-G", "Focus Plus"], {},
     "rank_districts", True, 5),                                                                          # A2
    ("top 5 districts for all four schemes combined", FOUR, {}, "rank_districts", False, 5),              # A5
    ("best 3 districts in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 3),                       # N1
    ("bottom ten districts for MGNREGA and PMAY-G beneficiaries", MP, {}, "rank_districts", True, 10),    # N2
    ("top five districts in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 5),                     # N3
    ("highest district in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, None),                    # N4
    ("least performing blocks in MGNREGA and PMAY-G", MP, {}, None, None, None),                          # N5, I-15
    ("which district is doing best in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, None),        # N6
    ("mgnrega pmay top 5 district", MP, {}, "rank_districts", False, 5),                                  # N7, I-16
    ("top 5 districs in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 5),                         # N9
    ("which district got maximum MGNREGA and PMAY-G beneficiaries", MP, {}, "rank_districts", False, None),
    ("district having highest MGNREGA and PMAY-G money", MP, {}, "rank_districts", False, None),          # N11
    ("give me top 3 district name for MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 3),           # N12
    ("MGNREGA and PMAY-G kis district me sabse jyada beneficiaries", MP, {}, "rank_districts", False, None),
    ("MGNREGA and PMAY-G sabse kam district", MP, {}, "rank_districts", True, None),                      # N14
    ("rank all districts by MGNREGA and PMAY-G beneficiaries", MP, {}, "rank_districts", False, None),    # N17
    ("second highest district in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, None),             # N18
    ("top 3 blocks in East Khasi Hills for MGNREGA and PMAY-G", MP, EKH, None, None, None),               # N19
    ("which block in East Khasi Hills is best for MGNREGA and PMAY-G", MP, EKH, None, None, None),        # N20
    ("districts ranked by villages covered in MGNREGA and PMAY-G", MP, {}, "rank_districts", False, None),
    ("top 5 districts where MGNREGA is more than PMAY-G", MP, {}, "condition", False, 5),                 # N25
    ("top 5 districts in MGNREGA vs PMAY-G", MP, {}, "rank_districts", False, 5),                         # N26
    ("top 5 districts in MGNREGA or PMAY-G", MP, {}, "rank_districts", False, 5),                         # N27
    ("top 5 districts each scheme MGNREGA and PMAY-G", MP, {}, "rank_districts", False, 5),               # N28
    ("worst 3 districts in Focus Plus and Focus Legacy", ["Focus Plus", "Focus Legacy"], {},
     "rank_districts", True, 3),                                                                          # N29
    ("top 5 districts across all schemes", ALL6, {}, "rank_districts", False, 5),                         # A1, I-13
    # the scheme-level questions keep their plans
    ("Which scheme reaches the most villages, MGNREGA or PMAY-G?", MP, {}, "leader", False, None),
    ("Which scheme has the least beneficiaries, MGNREGA or PMAY-G?", MP, {}, "leader", True, None),
    ("Which scheme has the highest beneficiary count in each district (MGNREGA, PMAY-G)?", MP, {}, "winner", False,
     None),
]


@pytest.mark.parametrize("q, schemes, resolved, op, low, top_n", WORDINGS)
def test_cross_scheme_wordings_are_read_at_the_right_level(q, schemes, resolved, op, low, top_n):
    pl = _plan(q, schemes, resolved)
    if op is None:
        assert pl is None, f"{q!r} should go to the per-scheme path, got {pl and pl.op}"
        return
    assert pl is not None and pl.op == op, f"{q!r}: {pl and pl.op}"
    assert pl.low is low and pl.top_n == top_n
    if op == "rank_districts":
        assert pl.by_district


def test_a_district_ranking_is_one_list_per_scheme_unless_combined_is_said():
    assert _plan("top 5 districts by beneficiaries in MGNREGA and PMAY-G").combined is False      # I-6
    assert _plan("top 5 districts in MGNREGA and top 5 districts in PMAY-G").combined is False
    assert _plan("top 5 districts for all four schemes combined", FOUR).combined is True
    assert _plan("Top 3 districts by total beneficiaries across MGNREGA, PMAY-G", MP).combined is True


def test_rank_details_both_ends_second_place_exclusion_and_per_head():
    assert _plan("top 5 and bottom 5 districts in MGNREGA and PMAY-G").both                       # I-12
    assert _plan("second highest district in MGNREGA and PMAY-G").nth == 2
    pl = _plan("top 5 districts by MGNREGA and PMAY-G beneficiaries excluding East Khasi Hills", MP, EKH)
    assert pl.exclude == ["EAST KHASI HILLS"] and pl.districts is None                             # I-19
    assert _plan("top 5 districts in MGNREGA and PMAY-G per beneficiary money").first == "avg"     # I-21
    assert _plan("top 5 districts by villages covered in MGNREGA and PMAY-G").first == "villages"  # I-11
    assert _plan("top 5 districts across all schemes", ALL6).left_out == ["CM Elevate", "CM Elevate Legacy"]


# ── I: the ranked answer and its rows ────────────────────────────────────────
_DIST = {   # (beneficiaries, money in crore, villages)
    "MGNREGA": {"WEST GARO HILLS": (261221, 792.42, 700), "RI BHOI": (112602, 183.16, 500),
                "EAST KHASI HILLS": (190000, 400.0, 900), "SOUTH GARO HILLS": (50000, 90.0, 300)},
    "PMAY-G": {"WEST GARO HILLS": (33147, 425.01, 650), "RI BHOI": (17565, 222.85, 480),
               "EAST KHASI HILLS": (40000, 300.0, 870), "SOUTH GARO HILLS": (9000, 60.0, 250)},
}
_VIEW = {"v_employment": "MGNREGA", "v_expenditure": "MGNREGA", "v_pmay": "PMAY-G"}


@pytest.fixture
def fake_db(monkeypatch):
    async def fetch_rows(sql, params):
        s = next(v for k, v in _VIEW.items() if k in sql)
        if "DISTINCT year_key AS y" in sql:
            return [{"y": y} for y in ((2017, 2023) if s == "PMAY-G" else (2022, 2025))]
        keys = list(_DIST[s]) if "GROUP BY" in sql else [None]
        out = []
        for k in keys:
            vals = [_DIST[s][x] for x in (_DIST[s] if k is None else [k])]
            ben, money, vill = (sum(v[i] for v in vals) for i in range(3))
            out.append({"k": k, "ben": ben, "money": money, "villages": vill, "districts": 4, "blocks": 9,
                        "completed": ben // 2, "sanctioned": money * 1.02})
        return out
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)


def _answer(q, schemes=MP, resolved=None):
    return asyncio.run(cf.answer(_plan(q, schemes, resolved)))


def test_bottom_districts_are_ranked_per_scheme_lowest_first(fake_db):
    out = _answer("bottom 2 districts by beneficiaries in MGNREGA and PMAY-G")
    assert "**MGNREGA** — Bottom 2 districts by households given work: 1. South Garo Hills 50,000; " \
           "2. Ri Bhoi 1,12,602." in out["answer"]
    assert "**PMAY-G** — Bottom 2 districts by houses sanctioned: 1. South Garo Hills 9,000; " \
           "2. Ri Bhoi 17,565." in out["answer"]
    assert "MGNREGA vs PMAY-G" not in out["answer"] and "ahead" not in out["answer"]
    # the rows are the ranked districts only, in rank order (I-7)
    assert [(r["scheme"], r["rank"], r["district"]) for r in out["rows"]] == [
        ("MGNREGA", 1, "South Garo Hills"), ("MGNREGA", 2, "Ri Bhoi"),
        ("PMAY-G", 1, "South Garo Hills"), ("PMAY-G", 2, "Ri Bhoi")]


def test_top_n_rows_are_only_the_n_ranked_districts(fake_db):
    out = _answer("top 2 districts by beneficiaries in MGNREGA and PMAY-G")
    assert [r["district"] for r in out["rows"] if r["scheme"] == "MGNREGA"] == ["West Garo Hills", "East Khasi Hills"]
    assert [r["district"] for r in out["rows"] if r["scheme"] == "PMAY-G"] == ["East Khasi Hills", "West Garo Hills"]
    assert len(out["rows"]) == 4


def test_a_combined_ranking_says_the_counts_and_money_differ(fake_db):
    out = _answer("top 2 districts by combined money in MGNREGA and PMAY-G")
    assert "Top 2 districts by combined money (MGNREGA + PMAY-G):" in out["answer"]
    assert "MGNREGA spent, PMAY-G released" in out["answer"]                                   # G-11
    assert "%" not in out["answer"]                                                            # no share of a sum
    assert [(r["rank"], r["district"], r["scheme"]) for r in out["rows"]][:2] == [
        (1, "West Garo Hills", "MGNREGA"), (1, "West Garo Hills", "PMAY-G")]


def test_villages_are_never_added_across_schemes(fake_db):
    out = _answer("top 2 districts by villages covered in MGNREGA and PMAY-G combined")
    assert "Village counts are not added across schemes" in out["answer"]                      # G-6
    assert "combined villages" not in out["answer"]
    assert "**MGNREGA** — Top 2 districts by villages covered: 1. East Khasi Hills 900 villages" in out["answer"]


def test_both_ends_second_place_and_exclusion(fake_db):
    out = _answer("top 1 and bottom 1 districts in MGNREGA and PMAY-G")
    assert "**MGNREGA** — Top 1 district by households given work: 1. West Garo Hills 2,61,221." in out["answer"]
    assert "**MGNREGA** — Bottom 1 district by households given work: 4. South Garo Hills 50,000." in out["answer"]
    out = _answer("second highest district in MGNREGA and PMAY-G")
    assert "**MGNREGA** — Second highest district by households given work: 2. East Khasi Hills" in out["answer"]
    assert [r["rank"] for r in out["rows"]] == [2, 2]
    out = _answer("top 5 districts by MGNREGA and PMAY-G beneficiaries excluding East Khasi Hills", MP, EKH)
    assert "excluding East Khasi Hills" in out["answer"]
    assert all(r["district"] != "East Khasi Hills" for r in out["rows"])


def test_condition_with_top_n_ranks_by_the_gap(fake_db):
    out = _answer("top 1 districts where MGNREGA is more than PMAY-G")
    assert "in **4 of 4 districts**; the 1 with the widest gap: West Garo Hills" in out["answer"]   # I-20


def test_per_head_ranking_is_on_money_per_beneficiary(fake_db):
    out = _answer("top 1 districts in MGNREGA and PMAY-G per beneficiary money")
    # PMAY-G per house: West Garo Hills 425.01 cr / 33,147 = ₹1,28,220, the highest per house;
    # East Khasi Hills has the most houses (40,000) and is not first
    assert "**PMAY-G** — Top 1 district by money per beneficiary: 1. West Garo Hills ₹1,28,220 per house." \
        in out["answer"]
    assert out["rows"][0]["rupees_per_beneficiary"] > 0                                        # I-21


def test_all_schemes_ranks_the_coded_four_and_says_cm_elevate_is_out(fake_db):
    pl = _plan("top 2 districts across all schemes", ["MGNREGA", "PMAY-G", "CM Elevate"])
    out = asyncio.run(cf.answer(pl))
    assert "CM Elevate is not in this ranking" in out["answer"]                                # I-13
    assert {r["scheme"] for r in out["rows"]} == {"MGNREGA", "PMAY-G"}


# ── I-2 / A-3 / I-17: the per-year rewrite keeps place, N, rank and years ────
def _session():
    return Session(session_id="audit-i2", user_id="u", created=time.time(), last_seen=time.time())


@pytest.mark.parametrize("q, want", [
    ("top 5 districts in MGNREGA and PMAY-G year wise",
     ["top 5 districts in MGNREGA year wise", "top 5 districts in PMAY-G year wise"]),                   # Y2
    ("MGNREGA and PMAY-G beneficiaries in East Khasi Hills year wise",
     ["MGNREGA beneficiaries in East Khasi Hills year wise", "PMAY-G beneficiaries in East Khasi Hills year wise"]),
    ("lowest 5 villages in East Khasi Hills in MGNREGA and PMAY-G each year",
     ["lowest 5 villages in East Khasi Hills in MGNREGA each year",
      "lowest 5 villages in East Khasi Hills in PMAY-G each year"]),                                      # Y6
    ("top 5 districts mgnerga and pmayg year wise",
     ["top 5 districts MGNREGA year wise", "top 5 districts pmayg year wise"]),                            # I-17
])
def test_per_year_questions_keep_their_place_and_ranking(q, want):
    assert cl.per_year_plan(_session(), q) == want


def test_per_year_questions_keep_the_asked_years():
    plan = cl.per_year_plan(_session(), "compare MGNREGA and PMAY-G beneficiaries for last 3 years")       # Y5, A-3
    assert plan == ["How many MGNREGA beneficiaries were there in each financial year from FY 2023-24 to FY 2025-26?",
                    "How many PMAY-G beneficiaries were there in each financial year from FY 2021-22 to FY 2023-24?"]
    plan = cl.per_year_plan(_session(), "MGNREGA and PMAY-G beneficiaries year wise from 2022-23 to 2024-25")
    assert all(x.endswith("from FY 2022-23 to FY 2024-25?") for x in plan)
    # with no years named, every year held (as before)
    assert cl.per_year_plan(_session(), "Beneficiaries of MGNREGA and PMAY-G year wise") == [
        "How many MGNREGA beneficiaries were there in each financial year?",
        "How many PMAY-G beneficiaries were there in each financial year?"]


# ── J-1 / J-2 / J-3: relative years, spans, one year rule ────────────────────
_TODAY = __import__("datetime").date(2026, 10, 29)


@pytest.mark.parametrize("q, schemes, years", [
    ("MGNREGA person days in East Khasi Hills for last 3 years", ["MGNREGA"], [2023, 2024, 2025]),
    ("PMAY-G houses in the past three years", ["PMAY-G"], [2021, 2022, 2023]),
    ("Focus Plus amount disbursed in recent 2 years", ["Focus Plus"], [2022, 2025]),
    ("Focus Legacy amount for last 3 years", ["Focus Legacy"], [2022, 2024, 2025]),
    ("MGNREGA person days last year", ["MGNREGA"], [2025]),
    ("MGNREGA person days this year", ["MGNREGA"], [2025]),           # FY 2026-27 has no data yet
    ("MGNREGA person days in the current financial year", ["MGNREGA"], [2025]),
    ("PMAY-G houses this year", ["PMAY-G"], [2023]),
])
def test_relative_periods_are_read_against_the_years_held(q, schemes, years):
    got = p._relative_years(q, schemes, today=_TODAY)
    assert got is not None and got[0] == years


def test_this_year_says_when_the_year_has_no_data():
    ys, label, note = p._relative_years("MGNREGA person days this year", ["MGNREGA"], today=_TODAY)
    assert label == "FY 2025-26" and "FY 2026-27 has no data yet" in note
    _ys, label, _n = p._relative_years("Focus Legacy amount for last 3 years", ["Focus Legacy"], today=_TODAY)
    assert label.startswith("FY 2022-23, FY 2024-25 and FY 2025-26")      # the 2023-24 hole is not hidden


def test_a_relative_period_is_never_asked_again():
    for s in (["MGNREGA"], ["PMAY-G"], ["Focus Plus"], ["Focus Legacy"]):
        assert p._needs_year_clarification("person days in East Khasi Hills for last 3 years", s, {}) is False
        assert p._needs_year_clarification("total amount in East Khasi Hills this year", s, {}) is False


def test_a_dash_between_two_years_is_a_span():
    assert p._c09_stated_year_span("MGNREGA person days 2022-23 - 2024-25") == (2022, 2024)            # J-2
    assert p._c09_stated_year_span("MGNREGA person days 2022-23 – 2024-25") == (2022, 2024)
    assert p._c09_stated_year_span("MGNREGA person days 2022-23 and 2024-25") is None


@pytest.mark.parametrize("scheme, measure", [("MGNREGA", "person days"), ("PMAY-G", "houses sanctioned"),
                                             ("Focus Plus", "amount disbursed"), ("Focus Legacy", "amount disbursed")])
def test_one_year_rule_for_every_scheme(scheme, measure):
    # J-3: the same wording asks the year for every scheme
    assert p._needs_year_clarification(f"{scheme} {measure} in Umpling village", [scheme], {}) is True

"""The drill-down behind an answer (D-110 default (b) revised, 2026-11-15).

The user's report (live test, 15 Nov): "Show me the top five districts by Focus Plus beneficiaries." (five districts,
correct), then "Can you break this down by block?" was rewritten by the old regroup rule into "Show me the top 5
districts by Focus Plus beneficiaries by block" and answered with THE SAME five districts again. Two causes:
  1. the frame's measure words were not read under a request opening ("Show me the top 5 districts by ..."), so the
     answer frame could not be re-rendered and the old string rule ran (it appended " by block" to a ranking);
  2. the frame's default (b) read "by block" after a top-N as "Top N blocks" statewide, not the blocks behind the
     answer, and the catalogue could not group Focus Plus by block at all.
Now: a regroup after an answer about a SET of places (a ranking: the places it named; a comparison of named places)
keeps those places — "by block" = every block of those districts, labelled by district, in the ranking's order;
"by year" = each of those places by year (a place x year table). The statewide top blocks stay one message away.
Offline: no model, no database.
    .venv/Scripts/python.exe -m pytest tests/test_frame_drilldown_2026_11_15.py -q
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import annotations, context_frames, context_policy, entity_resolver, llm  # noqa: E402
from app import answer_frame as af  # noqa: E402
from app import metric_catalog as mc  # noqa: E402
from app import pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers.query import build_turn  # noqa: E402
from app.session_store import Session  # noqa: E402
from _graph_turn import graph_turn, stub_data_path  # noqa: E402

TOP5 = ["WEST GARO HILLS", "SOUTH WEST GARO HILLS", "EAST KHASI HILLS", "EAST GARO HILLS", "NORTH GARO HILLS"]
TOP5_TEXT = "West Garo Hills, South West Garo Hills, East Khasi Hills, East Garo Hills and North Garo Hills"


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()
    annotations.load_all()


def _rank_sql(key="focus_plus_beneficiaries", view="curated.v_focus_plus", level="district", limit=5, where=""):
    col = {"district": "lgd_district", "block": "lgd_block"}[level]
    return (f"/* metric:{key} ranking */ SELECT {col} AS {level}, COUNT(DISTINCT beneficiary_key) AS beneficiaries\n"
            f"FROM {view}\nWHERE {where + ' AND ' if where else ''}{col} IS NOT NULL\nGROUP BY {col} "
            f"ORDER BY beneficiaries DESC NULLS LAST LIMIT {limit}")


def _turn(question, schemes, resolved, sql, rows=None, rewritten=None):
    result = {"route": "data", "schemes": list(schemes), "resolved_entities": dict(resolved or {}), "sql": sql,
              "answer": "x", "rows": list(rows or []), "data": list(rows or [])}
    if rewritten:
        result["rewritten_question"] = rewritten
    return build_turn(question, result)


def _top5_turn(question="Show me the top five districts by Focus Plus beneficiaries.",
               rewritten="Show me the top 5 districts by Focus Plus beneficiaries."):
    rows = [{"district": d, "beneficiaries": n} for d, n in zip(TOP5, (35039, 15294, 13608, 11379, 11007))]
    return _turn(question, ["Focus Plus"], {}, _rank_sql(), rows, rewritten)


# ── cause 1: the measure words under a request opening ───────────────────────

@pytest.mark.parametrize("q,want", [
    ("Show me the top 5 districts by Focus Plus beneficiaries.", "Focus Plus beneficiaries"),
    ("Show me the top five districts by Focus Plus beneficiaries.", "Focus Plus beneficiaries"),
    ("Which are the top 3 districts by MGNREGA person-days in FY 2023-24?", "MGNREGA person-days"),
    ("Give me the top 3 districts for MGNREGA expenditure", "MGNREGA expenditure"),
    ("Can you tell me which district has the most PMAY-G houses?", "PMAY-G houses"),
    ("What are the bottom 3 blocks by CMSS students paid", "CMSS students paid"),
    ("List the top 10 blocks by Homestay applications", "Homestay applications"),
])
def test_the_measure_is_read_under_a_request_opening(q, want):
    # before: None for every "Show me / Give me / Which are the / List the ..." ranking (the head was not stripped)
    assert p._c18_measure_text(q, ["X"], {}) == want


def test_a_place_list_is_cut_whole_even_when_a_longer_name_holds_a_shorter_one():
    # before: "West Garo Hills" was cut out of "South West Garo Hills", and the real one stayed in the words
    q = "Focus Plus beneficiaries in South West Garo Hills, East Khasi Hills and West Garo Hills"
    assert p._c18_measure_text(q, ["Focus Plus"], {}) == "Focus Plus beneficiaries"


def test_the_frame_records_the_places_a_ranking_named_in_its_order():
    f = af.from_turn(_top5_turn())
    assert (f.qtype, f.group, f.limit, f.measure_text) == ("ranking", "district", 5, "Focus Plus beneficiaries")
    assert f.items == TOP5


@pytest.mark.parametrize("rows", [
    [{"district": None, "beneficiaries": 1}, {"district": "RI BHOI", "beneficiaries": 2}],    # a row with no place
    [{"district": f"D{i}", "beneficiaries": i} for i in range(30)],                           # more than 25
    [],
])
def test_no_items_when_the_rows_do_not_say_them(rows):
    t = _turn("Top 5 districts by Focus Plus beneficiaries", ["Focus Plus"], {}, _rank_sql(), rows)
    assert af.from_turn(t).items == []


def test_a_breakdown_records_no_items():
    sql = ("/* metric:focus_plus_beneficiaries breakdown */ SELECT lgd_district AS district, COUNT(DISTINCT "
           "beneficiary_key) AS beneficiaries FROM curated.v_focus_plus GROUP BY lgd_district ORDER BY lgd_district")
    t = _turn("Focus Plus beneficiaries by district", ["Focus Plus"], {}, sql, [{"district": "RI BHOI", "b": 1}] * 2)
    f = af.from_turn(t)
    assert (f.qtype, f.items) == ("breakdown", [])


# ── cause 2: "by block" after a top N = the blocks behind the answer ────────

@pytest.mark.parametrize("msg", ["Can you break this down by block?", "split this by block", "block-wise please",
                                 "and by block?", "drill down into blocks", "now by block", "break it down by block"])
def test_by_block_after_a_top_n_is_the_blocks_of_those_districts(msg):
    # before: "Show me the top 5 districts by Focus Plus beneficiaries by block" (the old rule): the same 5 again
    kind, q, frame, plan = p._c18_frame_followup(msg, _top5_turn())
    assert kind == "drill"
    assert q == f"Focus Plus beneficiaries in {TOP5_TEXT} by block"
    assert (frame["qtype"], frame["group"], frame["order"], frame["limit"]) == ("breakdown", "block", None, None)
    assert frame["filters"] == {"district_list": TOP5}                     # in the ranking's order
    assert plan.actions["district"] == context_policy.REPLACE


def test_the_rendered_drill_down_is_read_back_into_the_same_frame():
    _kind, q, frame, _plan = p._c18_frame_followup("Can you break this down by block?", _top5_turn())
    sql = ("/* metric:focus_plus_beneficiaries breakdown */ SELECT lgd_district AS district, UPPER(block_name_raw) AS "
           "block, COUNT(DISTINCT beneficiary_key) AS beneficiaries\nFROM curated.v_focus_plus\nWHERE "
           "UPPER(lgd_district) = ANY($1::text[]) AND UPPER(block_name_raw) IS NOT NULL\nGROUP BY lgd_district, "
           "UPPER(block_name_raw) ORDER BY array_position($1::text[], UPPER(lgd_district)), beneficiaries DESC NULLS LAST")
    resolved = {"district_list": list(reversed(TOP5))}                     # the resolver's own order
    back = af.from_turn(_turn(q, ["Focus Plus"], resolved, sql))
    assert (back.qtype, back.group, back.order, back.measure_text) == ("breakdown", "block", None,
                                                                        "Focus Plus beneficiaries")
    assert back.filters["district_list"] == TOP5                           # kept in the question's order


def test_which_district_has_the_most_then_by_block_is_the_winners_blocks():
    # the catalogue shows the winner and the next two (LIMIT 3); one place was asked
    rows = [{"district": d, "beneficiaries": n} for d, n in zip(TOP5[:3], (3, 2, 1))]
    t = _turn("Which district has the most Focus Plus beneficiaries?", ["Focus Plus"], {}, _rank_sql(limit=3), rows)
    kind, q, frame, _plan = p._c18_frame_followup("break this down by block", t)
    assert (kind, q) == ("drill", "Focus Plus beneficiaries in West Garo Hills by block")
    assert frame["filters"] == {"district": "WEST GARO HILLS"}


def test_the_year_of_the_ranking_is_kept():
    rows = [{"district": d, "beneficiaries": 1} for d in TOP5[:3]]
    t = _turn("Top 3 districts by MGNREGA person-days in FY 2023-24", ["MGNREGA"], {"year_key": 2023},
              _rank_sql("mgnrega_employment_generated", "curated.v_employment", limit=3, where="year_key = 2023"), rows)
    _kind, q, frame, _plan = p._c18_frame_followup("break it down by block", t)
    assert q == ("MGNREGA person-days in West Garo Hills, South West Garo Hills and East Khasi Hills by block "
                 "in FY 2023-24")
    assert frame["filters"] == {"year_key": 2023, "district_list": TOP5[:3]}


def test_by_year_after_a_top_n_is_each_of_those_districts_by_year():
    kind, q, frame, _plan = p._c18_frame_followup("break it down by year", _top5_turn())
    assert kind == "drill"
    assert q == f"Focus Plus beneficiaries in {TOP5_TEXT} by district and by financial year"
    assert (frame["group"], frame["split"], frame["filters"]) == ("year", "district", {"district_list": TOP5})
    # both groupings for every reader of the rendered words
    assert p._c02_breakdowns(q, include_per=False) == {"district", "year"}


def test_the_top_blocks_statewide_are_still_one_message_away():
    kind, q, frame, _plan = p._c18_frame_followup("top 5 blocks", _top5_turn())
    assert (kind, q, frame["filters"]) == ("rank", "Top 5 blocks: Focus Plus beneficiaries", {})


def test_by_district_after_a_district_ranking_stays_the_ranking():
    kind, q, _frame, _plan = p._c18_frame_followup("by district", _top5_turn())
    assert (kind, q) == ("regroup", "Top 5 districts: Focus Plus beneficiaries")


def test_an_older_frame_without_the_names_keeps_the_old_reading():
    # a frame stored before 2026-11-15 has no items: nothing guessed, the ranking is kept (the old default b)
    t = _turn("Top 3 districts: How many PMAY-G houses were completed", ["PMAY-G"], {},
              _rank_sql("pmay_houses_completed", "curated.v_pmay", limit=3))
    assert p._c18_frame_followup("now by block", t)[1] == "Top 3 blocks: How many PMAY-G houses were completed"


def test_a_block_ranking_then_by_year_is_that_block_by_year():
    rows = [{"block": b, "beneficiaries": 1} for b in ("UMSNING", "UMLING", "JIRANG")]
    t = _turn("Which block has the most MGNREGA person-days in Ri Bhoi in FY 2023-24?", ["MGNREGA"],
              {"district": "RI BHOI", "year_key": 2023},
              _rank_sql("mgnrega_employment_generated", "curated.v_employment", "block", 3,
                        "UPPER(lgd_district) = 'RI BHOI' AND year_key = 2023"), rows)
    kind, q, frame, _plan = p._c18_frame_followup("break it down by year", t)
    assert (kind, q) == ("drill", "MGNREGA person-days in Umsning block, Ri Bhoi by financial year")
    assert frame["filters"] == {"block": "UMSNING", "district": "RI BHOI"}


# ── a comparison of named districts: the same places, never their sum ───────

def _compare_turn():
    sql = ("/* metric:pmay_houses_completed compare */ SELECT lgd_district AS district, COUNT(*) FILTER (WHERE "
           "is_completed) AS houses_completed FROM curated.v_pmay WHERE UPPER(lgd_district) = ANY($1::text[]) "
           "GROUP BY lgd_district ORDER BY lgd_district")
    rows = [{"district": "RI BHOI", "houses_completed": 12056}, {"district": "WEST GARO HILLS", "houses_completed": 1}]
    return _turn("Compare PMAY-G houses completed in Ri Bhoi and West Garo Hills", ["PMAY-G"],
                 {"district_list": ["RI BHOI", "WEST GARO HILLS"]}, sql, rows)


def test_a_comparison_then_by_block_is_the_blocks_of_both():
    kind, q, frame, _plan = p._c18_frame_followup("break it down by block", _compare_turn())
    assert (kind, q) == ("drill", "PMAY-G houses completed in Ri Bhoi and West Garo Hills by block")
    assert (frame["qtype"], frame["group"], frame["split"]) == ("breakdown", "block", None)


def test_a_comparison_then_by_year_keeps_the_districts_apart():
    # before: "PMAY-G houses completed in Ri Bhoi and West Garo Hills by financial year": the two districts SUMMED
    kind, q, frame, _plan = p._c18_frame_followup("break it down by year", _compare_turn())
    assert q == "PMAY-G houses completed in Ri Bhoi and West Garo Hills by district and by financial year"
    assert (frame["group"], frame["split"]) == ("year", "district")


# ── the place x year answer and the follow-ups after it ──────────────────────

_SPLIT_SQL = ("/* metric:pmay_houses_completed breakdown */ SELECT lgd_district AS district, year_key, "
              "MAX(financial_year_short) AS financial_year, COUNT(*) FILTER (WHERE is_completed) AS houses_completed\n"
              "FROM curated.v_pmay\nWHERE UPPER(lgd_district) = ANY($1::text[]) AND year_key IS NOT NULL\n"
              "GROUP BY lgd_district, year_key ORDER BY array_position($1::text[], UPPER(lgd_district)), year_key")
_SPLIT_Q = "PMAY-G houses completed in Ri Bhoi and West Garo Hills by district and by financial year"


def _split_turn():
    return _turn(_SPLIT_Q, ["PMAY-G"], {"district_list": ["RI BHOI", "WEST GARO HILLS"]}, _SPLIT_SQL)


def test_the_place_by_year_table_is_a_per_year_frame_that_keeps_the_places_apart():
    f = af.from_turn(_split_turn())
    assert (f.qtype, f.group, f.split, f.measure_text) == ("breakdown", "year", "district", "PMAY-G houses completed")


def test_a_two_way_table_without_a_place_list_stays_other():
    t = _turn("PMAY-G houses completed by district by financial year", ["PMAY-G"], {}, _SPLIT_SQL.replace(
        "UPPER(lgd_district) = ANY($1::text[]) AND ", ""))
    assert af.from_turn(t).qtype == "other"                               # KI-727 (c): left to the other paths


@pytest.mark.parametrize("msg,want,filters", [
    ("only Ri Bhoi", "PMAY-G houses completed in Ri Bhoi by financial year", {"district": "RI BHOI"}),
    ("what about 2023-24?", "PMAY-G houses completed in Ri Bhoi and West Garo Hills in FY 2023-24",
     {"district_list": ["RI BHOI", "WEST GARO HILLS"], "year_key": 2023}),
])
def test_follow_ups_after_the_place_by_year_table(msg, want, filters):
    _kind, q, frame, _plan = p._c18_frame_followup(msg, _split_turn())
    assert q == want
    assert frame["filters"] == filters


@pytest.fixture
def phrases(monkeypatch):
    cols = frozenset({"lgd_district", "lgd_block", "year_key", "village_code"})
    metrics = {k: mc.Metric(key=k, scheme="PMAY-G", display_name=k, expression="COUNT(*)", base_object="curated.v_pmay",
                            unit="houses", notes="", alias=k, phrases=ph, columns=cols)
               for k, ph in (("pmay_houses_completed", (("house", "completed"), ("completed", "house"))),
                             ("pmay_houses_sanctioned", (("house", "sanctioned"),)))}
    verified = {t: {} for t in mc.QUERY_TYPES}
    state = {"metrics": metrics, "by_scheme": {"PMAY-G": list(metrics.values())}, "loaded": True,
             "no_block_level": frozenset(), "single_year": frozenset(), "verified": verified}
    monkeypatch.setattr(mc, "_state", state)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")


def test_a_measure_swap_after_the_place_by_year_table_keeps_the_places_apart(phrases):
    kind, q, frame, _plan = p._c18_frame_followup("and the houses sanctioned instead", _split_turn())
    assert kind == "measure"
    assert q == "PMAY-G houses sanctioned in Ri Bhoi and West Garo Hills by district and by financial year"
    assert (frame["group"], frame["split"]) == ("year", "district")


def test_which_year_after_the_place_by_year_table_is_not_guessed():
    # which place's best year is not said: left to the other paths
    assert p._c18_frame_followup("which year had the most?", _split_turn()) is None


# ── the old regroup rule never appends a grouping to a ranking ───────────────

@pytest.mark.parametrize("prev_q", ["Show me the top 5 districts by Focus Plus beneficiaries.",
                                    "Top 3 districts: How many PMAY-G houses were completed",
                                    "Which district has the most Focus Plus beneficiaries?"])
def test_the_old_regroup_rule_leaves_a_ranking_alone(prev_q):
    # before: "Show me the top 5 districts by Focus Plus beneficiaries by block"
    prev = _turn(prev_q, ["Focus Plus"], {}, _rank_sql())
    assert p._c01_regroup_question("Can you break this down by block?", prev) is None


def test_the_old_regroup_rule_still_regroups_a_plain_answer():
    prev = _turn("Focus Plus beneficiaries in West Garo Hills", ["Focus Plus"], {"district": "WEST GARO HILLS"},
                 "SELECT 1")
    assert p._c01_regroup_question("break it down by block", prev) == \
        "Focus Plus beneficiaries in West Garo Hills by block"


# ── the catalogue query ──────────────────────────────────────────────────────

@pytest.fixture
def catalogue(monkeypatch):
    def metric(key, scheme, view, expr, alias, cols):
        return mc.Metric(key=key, scheme=scheme, display_name=key, expression=expr, base_object=view, unit="count",
                         notes="", alias=alias, phrases=(), columns=frozenset(cols))
    fp = metric("focus_plus_beneficiaries", "Focus Plus", "curated.v_focus_plus", "COUNT(DISTINCT beneficiary_key)",
                "beneficiaries", {"lgd_district", "lgd_block", "block_name_raw", "year_key", "financial_year_short"})
    pm = metric("pmay_houses_completed", "PMAY-G", "curated.v_pmay", "COUNT(*) FILTER (WHERE is_completed)",
                "houses_completed", {"lgd_district", "lgd_block", "year_key", "financial_year_short"})
    state = dict(mc._state)
    state.update(metrics={fp.key: fp, pm.key: pm}, no_block_level=frozenset({"Focus Plus"}), loaded=True,
                 source_blocks={"curated.v_focus_plus": frozenset({"TIKRIKILLA", "SELSELLA"})})
    monkeypatch.setattr(mc, "_state", state)
    return fp, pm


def test_focus_plus_blocks_are_grouped_on_their_source_column(catalogue):
    fp, _pm = catalogue
    sql, params, shown = mc.build(fp, {"district": "WEST GARO HILLS"}, "block", qtype="breakdown")
    # before: None (no block level for Focus Plus): the model wrote the SQL, and with the model down there was none
    assert "UPPER(block_name_raw) AS block" in shown and "GROUP BY UPPER(block_name_raw)" in shown
    assert "lgd_block" not in shown


def test_the_blocks_of_several_districts_carry_their_district_in_the_listed_order(catalogue):
    fp, pm = catalogue
    sql, params, shown = mc.build(fp, {"district": TOP5}, "block", qtype="breakdown")
    assert shown.startswith("/* metric:focus_plus_beneficiaries breakdown */ SELECT lgd_district AS district, "
                            "UPPER(block_name_raw) AS block, ")
    assert "GROUP BY lgd_district, UPPER(block_name_raw) ORDER BY array_position(ARRAY['WEST GARO HILLS', " in shown
    assert "beneficiaries DESC NULLS LAST" in shown
    assert params == [TOP5]                                     # the ORDER BY reuses the WHERE's list parameter
    assert "array_position($1::text[], UPPER(lgd_district))" in sql
    _sql, _params, one = mc.build(pm, {"district": "RI BHOI"}, "block", qtype="breakdown")
    assert "lgd_district AS district" not in one                # one district: the plain block list, as before


def test_each_listed_place_by_year(catalogue):
    _fp, pm = catalogue
    sql, params, shown = mc.build(pm, {"district": ["RI BHOI", "WEST GARO HILLS"]}, "year", qtype="breakdown",
                                  split="district")
    assert "SELECT lgd_district AS district, year_key, MAX(financial_year_short) AS financial_year, " in shown
    assert "GROUP BY lgd_district, year_key ORDER BY array_position(" in shown and shown.endswith(", year_key")
    assert mc.build(pm, {"district": "RI BHOI"}, "year", split="district") is None   # one place: nothing to split
    assert mc.build(pm, {"district": ["RI BHOI", "WEST GARO HILLS"]}, "block", split="district") is None


def test_the_drill_down_question_takes_the_catalogue_by_its_words(catalogue):
    q = f"Focus Plus beneficiaries in {TOP5_TEXT} by block"
    assert p._c16_shape(q, {"district": TOP5}) == {"qtype": "breakdown", "group": "block", "order": None,
                                                   "limit": None, "listed": True}
    q2 = "PMAY-G houses completed in Ri Bhoi and West Garo Hills by district and by financial year"
    shape = p._c16_shape(q2, {"district": ["RI BHOI", "WEST GARO HILLS"]})
    assert (shape["group"], shape["split"]) == ("year", "district")
    # a plain comparison is still a comparison
    assert p._c16_shape("Compare PMAY-G houses completed in Ri Bhoi and West Garo Hills",
                        {"district": ["RI BHOI", "WEST GARO HILLS"]})["qtype"] == "compare"


def test_an_order_by_the_listed_places_is_no_order_on_the_measure():
    sql = ("SELECT lgd_district AS district, lgd_block AS block, SUM(x) AS v FROM curated.v_pmay GROUP BY 1, 2 "
           "ORDER BY array_position(ARRAY['A','B'], UPPER(lgd_district)), v DESC")
    r = p._c18_sql_reading(sql)
    assert (r["qtype"], r["group"], r["order"]) == ("breakdown", "block", None)


# ── the answer: one line per listed place ────────────────────────────────────

def test_the_drill_down_answer_lists_each_district_with_its_blocks():
    rows = [{"district": "WEST GARO HILLS", "block": "TIKRIKILLA", "beneficiaries": 8744},
            {"district": "WEST GARO HILLS", "block": "SELSELLA", "beneficiaries": 7691},
            {"district": "SOUTH WEST GARO HILLS", "block": "ZIKZAK", "beneficiaries": 6656}]
    sql = "/* metric:focus_plus_beneficiaries breakdown */ SELECT lgd_district AS district FROM curated.v_focus_plus"
    shape = p._answer_shape("Focus Plus beneficiaries in A and B by block", sql, rows)
    text = p._c18_grouped_body(shape, rows, sql, ["Focus Plus"], {})
    assert text.splitlines() == [
        "Beneficiaries by block in 2 districts (Focus Plus, across all financial years):",
        "- **West Garo Hills** — Tikrikilla 8,744; Selsella 7,691",
        "- **South West Garo Hills** — Zikzak 6,656"]
    assert p._c18_grouped_body(shape, rows, "SELECT 1", ["Focus Plus"], {}) is None   # a model query: unchanged


def test_the_place_by_year_answer_reads_the_years_as_financial_years():
    rows = [{"district": "RI BHOI", "year_key": 2022, "financial_year": "2022-23", "houses_completed": 375},
            {"district": "RI BHOI", "year_key": 2023, "financial_year": "2023-24", "houses_completed": 6847},
            {"district": "WEST GARO HILLS", "year_key": 2023, "financial_year": "2023-24", "houses_completed": 13964}]
    shape = p._answer_shape(_SPLIT_Q, _SPLIT_SQL, rows)
    text = p._c18_grouped_body(shape, rows, _SPLIT_SQL, ["PMAY-G"], {})
    assert text.splitlines()[1:] == ["- **Ri Bhoi** — FY 2022-23 375; FY 2023-24 6,847",
                                     "- **West Garo Hills** — FY 2023-24 13,964"]


# ── through the graph (the question the data path receives), the model unreachable ──

@pytest.fixture
def chat(monkeypatch):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    for name in ("_village_names", "_village_places", "_village_scheme_codes", "_village_code_names",
                 "_village_names_failed_at"):
        monkeypatch.setattr(entity_resolver, name, getattr(entity_resolver, name))
    for name in ("_MGNREGA_VILLAGE_NAMES", "_PMAY_VILLAGE_NAMES", "_FOCUSPLUS_VILLAGE_NAMES", "_PLACE_WORDS_CACHE"):
        if hasattr(p, name):
            monkeypatch.setattr(p, name, getattr(p, name))

    async def no_gazetteer(*a, **k):
        return 0
    monkeypatch.setattr(entity_resolver, "load_village_names", no_gazetteer)
    seen = []

    async def data(question, scope=None, prior_resolved=None, **kw):
        seen.append({"question": question, "prior": dict(prior_resolved or {})})
        ranked = p._c18_strip_rank_head(question)[1]
        schemes = sorted(p._exact_schemes(question)) or ["MGNREGA"]
        if ranked:
            sql = _rank_sql(limit=5)
            rows = [{"district": d, "beneficiaries": 5 - i} for i, d in enumerate(TOP5)]
        else:
            sql = "SELECT lgd_block AS block, COUNT(*) AS n FROM curated.v_pmay GROUP BY lgd_block"
            rows = [{"block": "A", "n": 1}, {"block": "B", "n": 2}]
        return {"route": "data", "intent": "DATA", "schemes": schemes, "sql": sql,
                "resolved_entities": dict(prior_resolved or {}), "rows": rows, "data": rows,
                "row_count": len(rows), "answer": "answer."}
    stub_data_path(monkeypatch, data)

    async def no_model(*a, **k):
        raise RuntimeError("no model offline")
    monkeypatch.setattr(llm, "call_rewriter", no_model)
    monkeypatch.setattr(llm, "call_classifier", no_model)
    state = {"s": Session(session_id=f"drill-{time.time()}", user_id="u", created=time.time(), last_seen=time.time())}

    def ask(q, fresh=False):
        s = state["s"]
        if fresh:
            other = Session(session_id=s.session_id, user_id="u", created=time.time(), last_seen=time.time())
            other.apply_snapshot(s.to_snapshot(), summary=s.summary)
            state["s"] = s = other
        n = len(seen)
        out = asyncio.run(graph_turn(q, session=s))
        s.turns.append(build_turn(q, out))
        context_frames.record(s, q, out)
        return seen[-1] if len(seen) > n else None
    return ask


@pytest.mark.parametrize("fresh", [False, True])
def test_graph_the_users_two_turns(chat, fresh):
    chat("Show me the top 5 districts by Focus Plus beneficiaries.")
    got = chat("Can you break this down by block?", fresh=fresh)
    # before: "Show me the top 5 districts by Focus Plus beneficiaries by block" (the same five districts again)
    assert got["question"] == f"Focus Plus beneficiaries in {TOP5_TEXT} by block"
    assert got["prior"].get("district_list") == TOP5


def test_graph_by_year_after_the_top_five(chat):
    chat("Show me the top 5 districts by Focus Plus beneficiaries.")
    got = chat("break it down by year")
    assert got["question"] == f"Focus Plus beneficiaries in {TOP5_TEXT} by district and by financial year"

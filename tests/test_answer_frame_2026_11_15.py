"""The answer frame (D-110, 2026-11-15): what the last data answer was, and follow-ups read as an edit of it.

The user's goal: follow-ups such as "break that down by district", "by block", "only Ri Bhoi", "which is the lowest",
"top 3", "what about 2023-24", "and the households instead", and plain district / block questions must ALWAYS resolve.
The audit of 2026-11-15 found seven weaknesses of the string rules (c01); each has a test below that failed before
D-110 and passes after it (the "before" is stated in each test's comment, measured on 9d8f546):

  W1  two grouping readers disagreed ("across all districts")       test_w1_*
  W2  a rule's output was not read back ("Top 3 districts: ...")     test_w2_*
  W3  only-place / "what about <place>" after a breakdown           test_w3_*
  W4  a roll-up by grouping, unusual regroup wordings               test_w4_*
  W5  the rules ran only right after a DATA answer                  test_w5_*
  W6  a freshly rehydrated worker held older turns as stubs         test_w6_*
  W7  inherited filters leaked (no merge plan on the rewrites)      test_w7_*
  and the ordinal / "yes" replies to a SCHEME pause                 test_scheme_pause_*

Then the frame filler on catalogue / fixed / model-shaped SQL, the snapshot round trip (incl. old snapshots), the
catalogue taking the frame directly, and a chain matrix (first-question shapes x follow-up kinds x fresh worker) that
asserts the rendered question AND the frame. Offline: no model, no database.
    .venv/Scripts/python.exe -m pytest tests/test_answer_frame_2026_11_15.py -q
"""
import asyncio
import dataclasses
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import annotations, context_frames, context_policy, entity_resolver, llm, topic_memory  # noqa: E402
from app import answer_frame as af  # noqa: E402
from app import metric_catalog as mc  # noqa: E402
from app import pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers.query import build_turn  # noqa: E402
from app.session_store import Session, Turn  # noqa: E402
from _graph_turn import graph_turn, stub_data_path  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()
    annotations.load_all()


# ── SQL shapes as the data path writes them ──────────────────────────────────

def _cat(key, qtype, group=None, order=None, limit=None, where=""):
    col = {"district": "lgd_district", "block": "lgd_block", "year": "year_key"}.get(group)
    sel = f"{col} AS {group}, COUNT(*) AS {key}" if col else f"COUNT(*) AS {key}"
    tail = f"\nGROUP BY {col}" if col else ""
    if order:
        tail += f" ORDER BY {key} {order.upper()} NULLS LAST" + (f" LIMIT {limit}" if limit else "")
    elif col:
        tail += f" ORDER BY {col}"
    return f"/* metric:{key} {qtype} */ SELECT {sel}\nFROM curated.v_pmay{(' WHERE ' + where) if where else ''}{tail}"


def _model(group=None, order=None, limit=None, where=""):
    col = {"district": "lgd_district", "block": "lgd_block", "year": "year_key", "village": "lgd_village_name"}.get(group)
    sel = f"{col}, SUM(total_exp) AS expenditure" if col else "SUM(total_exp) AS expenditure"
    tail = f" GROUP BY {col}" if col else ""
    if order:
        tail += f" ORDER BY expenditure {order.upper()}" + (f" LIMIT {limit}" if limit else "")
    return f"SELECT {sel} FROM curated.v_mgnrega_expenditure{(' WHERE ' + where) if where else ''}{tail}"


def _turn(question, schemes, resolved, sql, route="data"):
    result = {"route": route, "schemes": list(schemes), "resolved_entities": dict(resolved or {}), "sql": sql,
              "answer": "x", "rows": [], "data": []}
    return build_turn(question, result)


# ── the frame filler ─────────────────────────────────────────────────────────

def test_the_frame_of_a_catalogue_answer_is_read_from_its_own_query():
    t = _turn("Top 3 districts: How many PMAY-G houses were completed", ["PMAY-G"], {},
              _cat("pmay_houses_completed", "ranking", "district", "desc", 3))
    f = af.from_turn(t)
    assert (f.source, f.metric_key, f.qtype, f.group, f.order, f.limit) == \
        ("catalogue", "pmay_houses_completed", "ranking", "district", "desc", 3)
    assert f.measure_text == "How many PMAY-G houses were completed"
    assert f.filters == {} and f.question.startswith("Top 3 districts")


@pytest.mark.parametrize("sql,want", [
    (_model(), ("total", None, None, None)),
    (_model("district"), ("breakdown", "district", None, None)),
    (_model("block", "desc", 5), ("ranking", "block", "desc", 5)),
    (_model("district", "asc"), ("breakdown", "district", "asc", None)),         # sorted, no top N: a breakdown
    ("SELECT lgd_district, lgd_block, SUM(x) FROM curated.v_pmay GROUP BY lgd_district, lgd_block",
     ("breakdown", "block", None, None)),                                       # the district only disambiguates
    ("SELECT lgd_district, year_key, SUM(x) FROM curated.v_pmay GROUP BY lgd_district, year_key",
     ("other", None, None, None)),                                              # two groupings: not guessed
    ("SELECT beneficiary_name FROM curated.v_pmay WHERE lgd_block = 'DALU' LIMIT 1000", ("list", None, None, None)),
    ("WITH t AS (SELECT lgd_district AS district, SUM(x) AS n FROM curated.v_pmay GROUP BY lgd_district) "
     "SELECT district, n FROM t ORDER BY n DESC LIMIT 3", ("ranking", "district", "desc", 3)),
])
def test_the_frame_of_model_and_fixed_sql_is_read_from_the_tree(sql, want):
    f = af.from_turn(_turn("MGNREGA expenditure", ["MGNREGA"], {}, sql))
    assert (f.qtype, f.group, f.order, f.limit) == want


@pytest.mark.parametrize("resolved,want", [
    ({"district": "WEST GARO HILLS", "year_key": 2023}, ("total", None)),
    ({"block": "DALU"}, ("total", None)),                                       # a district grouping of one block
    ({"district_list": ["RI BHOI", "EAST KHASI HILLS"]}, ("compare", "district")),
    ({}, ("breakdown", "district")),
])
def test_a_grouping_by_the_filtered_place_itself_is_one_figure(resolved, want):
    # the PMAY-G facts query groups by the very district it is filtered to (one row per named entity); read as a
    # district breakdown, "what about the year before?" became "... by district in FY 2022-23" (no-model gold
    # W5-FU-06, FU-09, W5-FU-01 on the first run of D-110)
    sql = ("SELECT UPPER(lgd_district) AS entity_key, MAX(lgd_district) AS name, COUNT(*) AS houses, "
           "COALESCE(SUM(sanctioned_amount), 0) AS sanctioned FROM curated.v_pmay "
           "WHERE UPPER(lgd_district) = 'WEST GARO HILLS' GROUP BY UPPER(lgd_district)")
    f = af.from_turn(_turn("How many PMAY-G houses were sanctioned in West Garo Hills in FY 2023-24?", ["PMAY-G"],
                           resolved, sql))
    assert (f.qtype, f.group) == want


@pytest.mark.parametrize("sql", ["SELECT 1", "", "not sql at all ((", "SELECT 1 UNION SELECT 2"])
def test_nothing_is_guessed_when_the_sql_says_nothing(sql):
    f = af.from_turn(_turn("PMAY-G houses by district", ["PMAY-G"], {}, sql))
    assert f.qtype is None and f.group is None and f.order is None and f.limit is None


def test_the_source_and_the_filters_are_as_resolved():
    resolved = {"district": "RI BHOI", "year_key": 2023, "tranche_label": "T1", "village_twins": {}}
    res = {"route": "data", "schemes": ["MGNREGA"], "resolved_entities": resolved, "sql": _model()}
    assert p._c18_fill_frame("MGNREGA expenditure in Ri Bhoi in FY 2023-24", res, origin="model")["source"] == "model"
    f = p._c18_fill_frame("MGNREGA expenditure in Ri Bhoi in FY 2023-24", res)
    assert f["filters"] == {"district": "RI BHOI", "year_key": 2023}         # place and year keys only
    assert f["measure_text"] == "MGNREGA expenditure"
    cross = p._c18_fill_frame("Compare MGNREGA and PMAY-G", {**res, "schemes": ["MGNREGA", "PMAY-G"]})
    assert cross["source"] == "cross" and cross["measure_text"] is None
    assert p._c18_fill_frame("What is PMAY-G?", {"route": "knowledge", "schemes": ["PMAY-G"]}) == {}


@pytest.mark.parametrize("q,resolved,want", [
    ("How many PMAY-G houses were completed in Ri Bhoi by block in FY 2023-24?", {"district": "RI BHOI", "year_key": 2023},
     "How many PMAY-G houses were completed"),
    ("Which district had the most PMAY-G houses completed", {}, "PMAY-G houses completed"),
    ("Total MGNREGA expenditure statewide across all financial years", {}, "Total MGNREGA expenditure"),
    ("Compare MGNREGA expenditure in Ri Bhoi and East Khasi Hills", {"district_list": ["RI BHOI", "EAST KHASI HILLS"]},
     "MGNREGA expenditure"),
    ("MGNREGA expenditure in Umsning block, Ri Bhoi as a bar chart", {"block": "UMSNING", "district": "RI BHOI"},
     "MGNREGA expenditure"),
])
def test_the_measure_words_are_the_question_without_its_scope_and_shape(q, resolved, want):
    assert p._c18_measure_text(q, ["MGNREGA" if "MGNREGA" in q else "PMAY-G"], resolved) == want


@pytest.mark.parametrize("q", [
    "Which district has the highest and lowest MGNREGA expenditure",        # two rankings: not understood
    "Compare MGNREGA expenditure with last year",                            # a comparison left inside
])
def test_measure_words_that_are_not_understood_are_left_none(q):
    assert p._c18_measure_text(q, ["MGNREGA"], {}) is None


# ── W1: one grouping reader ──────────────────────────────────────────────────

@pytest.mark.parametrize("q", ["Show PMAY-G houses completed across all districts", "by district", "district wise",
                               "districtwise", "district-wise", "in each district", "every block", "per block",
                               "across the blocks", "all the villages", "district by district", "block wise",
                               "for all blocks"])
def test_w1_the_two_grouping_readers_agree(q):
    # before D-110: "across all districts", "every block", "all the villages", "for all blocks" were groupings to
    # asked_levels only, "across the blocks" to _c02_breakdowns only
    grouped = {d for d in p._c02_breakdowns(q) if d in ("district", "block", "village")}
    assert grouped == set(context_policy.asked_levels(q)), q


@pytest.mark.parametrize("q", ["across all financial years", "all schemes", "for all years", "compare all schemes"])
def test_w1_all_years_and_all_schemes_are_no_grouping(q):
    assert not p._c02_breakdowns(q) and not context_policy.asked_levels(q)


ALL_D = None


def _all_districts_turn():
    return _turn("Show PMAY-G houses completed across all districts", ["PMAY-G"], {},
                 "SELECT lgd_district, COUNT(*) AS houses FROM curated.v_pmay WHERE house_status = 'COMPLETED' "
                 "GROUP BY lgd_district")


def test_w1_a_regroup_after_across_all_districts_replaces_the_grouping():
    # before: "Show PMAY-G houses completed across all districts by block" (two groupings)
    out = p._c18_frame_followup("now by block", _all_districts_turn())
    assert out[1] == "Show PMAY-G houses completed by block"
    assert p._c02_breakdowns(out[1]) == {"block"}


def test_w1_which_is_lowest_after_across_all_districts_ranks_the_districts():
    # before: no rule (the rank rule saw no grouping in the words): the model rewrite, or the bare words
    out = p._c18_frame_followup("which is the lowest", _all_districts_turn())
    assert out[1] == "Which district has the lowest: Show PMAY-G houses completed"
    assert out[2]["qtype"] == "ranking" and out[2]["group"] == "district" and out[2]["order"] == "asc"


# ── W2: a rule's output is read back ─────────────────────────────────────────

def _top3_turn():
    return _turn("Top 3 districts: How many PMAY-G houses were completed", ["PMAY-G"], {},
                 _cat("pmay_houses_completed", "ranking", "district", "desc", 3))


def test_w2_a_regroup_after_a_ranking_rules_output_is_one_grouping():
    # before: "Top 3 districts: How many PMAY-G houses were completed by block" (two groupings)
    out = p._c18_frame_followup("now by block", _top3_turn())
    assert out[1] == "Top 3 blocks: How many PMAY-G houses were completed"
    assert p._c01_ranked_stem(out[1]) == ("block", "How many PMAY-G houses were completed")


def test_w2_every_rendered_question_is_read_back_into_the_same_frame():
    t = _top3_turn()
    for msg in ("now by block", "and the least?", "only Ri Bhoi", "top 5", "what about 2023-24"):
        kind, q, frame, _plan = p._c18_frame_followup(msg, t)
        sql = {"ranking": _cat("pmay_houses_completed", "ranking", frame["group"], frame["order"], frame["limit"]),
               "total": _cat("pmay_houses_completed", "total")}.get(frame["qtype"]) or \
            _cat("pmay_houses_completed", frame["qtype"], frame["group"])
        back = af.from_turn(_turn(q, ["PMAY-G"], frame["filters"], sql))
        assert (back.measure_text, back.qtype, back.group, back.filters) == \
            (frame["measure_text"], frame["qtype"], frame["group"], frame["filters"]), (msg, q)
        t = _top3_turn()


# ── W3: only one place / what about a place ──────────────────────────────────

def _by_district_turn():
    return _turn("PMAY-G houses completed by district", ["PMAY-G"], {},
                 _cat("pmay_houses_completed", "breakdown", "district"))


@pytest.mark.parametrize("msg", ["Ri Bhoi only", "what about Ri Bhoi?", "only Ri Bhoi", "just Ri Bhoi please",
                                 "and Ri Bhoi?"])
def test_w3_one_place_of_a_breakdown(msg):
    # before: "Ri Bhoi only" / "what about Ri Bhoi?" / "and Ri Bhoi?" went to the model (no rule)
    out = p._c18_frame_followup(msg, _by_district_turn())
    assert out[1] == "PMAY-G houses completed in Ri Bhoi"
    assert out[2]["filters"] == {"district": "RI BHOI"} and out[2]["qtype"] == "total" and out[2]["group"] is None


def test_w3_only_a_block_after_a_breakdown_inside_a_district():
    # before: refused (the previous question names a place) -> the model
    t = _turn("How many PMAY-G houses were completed in Ri Bhoi by block", ["PMAY-G"], {"district": "RI BHOI"},
              _cat("pmay_houses_completed", "breakdown", "block", where="UPPER(lgd_district) = 'RI BHOI'"))
    out = p._c18_frame_followup("only Umsning block", t)
    assert out[1] == "How many PMAY-G houses were completed in Umsning block, Ri Bhoi"
    assert out[2]["filters"] == {"block": "UMSNING", "district": "RI BHOI"}


def test_w3_works_without_the_gazetteer(monkeypatch):
    # the village index (database) not loaded: the frame's own filters and the catalogue's place names suffice
    monkeypatch.setattr(entity_resolver, "_village_names", None)
    out = p._c18_frame_followup("what about Ri Bhoi?", _by_district_turn())
    assert out[1] == "PMAY-G houses completed in Ri Bhoi"


def test_w3_a_bare_place_name_is_left_to_the_pause_and_swap_paths():
    assert p._c18_frame_followup("Ri Bhoi", _by_district_turn()) is None


# ── W4: roll-up by grouping, unusual wordings ────────────────────────────────

def _in_ri_bhoi_turn():
    return _turn("MGNREGA expenditure in Ri Bhoi in FY 2023-24", ["MGNREGA"], {"district": "RI BHOI", "year_key": 2023},
                 _model(where="lgd_district = 'RI BHOI' AND year_key = 2023"))


def test_w4_by_district_after_one_district_is_a_roll_up():
    # before: the regroup rule refused a grouping at its own filter's level -> the model
    kind, q, frame, plan = p._c18_frame_followup("by district", _in_ri_bhoi_turn())
    assert q == "MGNREGA expenditure by district in FY 2023-24"
    assert frame["filters"] == {"year_key": 2023}
    assert plan.action("district") == context_policy.CLEAR and plan.action("year") == context_policy.KEEP


@pytest.mark.parametrize("msg,want", [
    ("what about block wise breakdown", "MGNREGA expenditure in Ri Bhoi by block in FY 2023-24"),
    ("break it down by block for East Khasi Hills", "MGNREGA expenditure in East Khasi Hills by block in FY 2023-24"),
    ("can I see that block wise", "MGNREGA expenditure in Ri Bhoi by block in FY 2023-24"),
    ("break it down by block for 2022-23", "MGNREGA expenditure in Ri Bhoi by block in FY 2022-23"),
])
def test_w4_unusual_regroup_wordings(msg, want):
    # before: each went to the model (a word the regroup rule did not know)
    assert p._c18_frame_followup(msg, _in_ri_bhoi_turn())[1] == want


# ── through the graph, the model unreachable ─────────────────────────────────

def _fake_sql(question):
    """The SQL a data path would write for `question` (a test double of the data path's shape)."""
    q = question or ""
    ranked = p._c01_ranked_stem(q)
    head = q.lower()
    if ranked is not None:
        level = ranked[0]
        n = 1 if head.startswith("which") else int(q.split()[1])
        order = "asc" if ("lowest" in head or head.startswith("bottom")) else "desc"
        return _model(level, order, n)
    dims = [d for d in ("block", "district", "year") if d in p._c02_breakdowns(q)]
    return _model(dims[0] if dims else None)


@pytest.fixture
def chat(monkeypatch):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    seen = []

    async def data(question, scope=None, prior_resolved=None, **kw):
        seen.append({"question": question, "prior": dict(prior_resolved or {})})
        resolved = dict(prior_resolved or {})
        for name, dim in entity_resolver.named_places(question).items():
            if dim == "district":
                resolved.pop("block", None)
            resolved[dim] = name
        years = sorted(context_policy.extract_year_keys(question))
        if years:
            resolved["year_key"] = years[0]
        schemes = sorted(p._exact_schemes(question)) or ["MGNREGA"]
        return {"route": "data", "intent": "DATA", "schemes": schemes, "sql": _fake_sql(question),
                "resolved_entities": resolved, "rows": [{"n": 1}], "data": [{"n": 1}], "row_count": 1,
                "answer": "answer."}
    stub_data_path(monkeypatch, data)

    async def no_model(*a, **k):
        raise RuntimeError("no model offline")
    monkeypatch.setattr(llm, "call_rewriter", no_model)
    monkeypatch.setattr(llm, "call_classifier", no_model)
    state = {"s": Session(session_id=f"frame-{time.time()}", user_id="u", created=time.time(),
                          last_seen=time.time())}

    def ask(q, fresh=False, knowledge=None):
        s = state["s"]
        if fresh:                                    # another worker: only the durable snapshot comes back
            other = Session(session_id=s.session_id, user_id="u", created=time.time(), last_seen=time.time())
            other.apply_snapshot(s.to_snapshot(), summary=s.summary)
            state["s"] = s = other
        if knowledge is not None:                    # a knowledge aside, recorded as the router does
            res = {"route": "knowledge", "schemes": knowledge, "answer": "how it works.", "resolved_entities": {}}
            s.turns.append(build_turn(q, res))
            context_frames.record(s, q, res)
            return None
        n = len(seen)
        out = asyncio.run(graph_turn(q, session=s))
        s.turns.append(build_turn(q, out))
        context_frames.record(s, q, out)
        return seen[-1] if len(seen) > n else None
    return ask


# W1..W4 through the graph (the question the data path receives), the model unreachable. The "before" in each
# comment is what 9d8f546 sent to the data path for the same chain.

def test_w1_graph_regroup_after_across_all_districts(chat):
    chat("Show PMAY-G houses completed across all districts")
    # before: "Show PMAY-G houses completed across all districts by block"
    assert chat("now by block")["question"] == "Show PMAY-G houses completed by block"


def test_w1_graph_lowest_after_across_all_districts(chat):
    chat("Show PMAY-G houses completed across all districts")
    # before: "which is the lowest" (the bare words: no rule, the model down)
    assert chat("which is the lowest")["question"] == "Which district has the lowest: Show PMAY-G houses completed"


def test_w2_graph_regroup_after_a_top3(chat):
    chat("Top 3 districts: How many PMAY-G houses were completed")
    # before: "Top 3 districts: How many PMAY-G houses were completed by block"
    assert chat("now by block")["question"] == "Top 3 blocks: How many PMAY-G houses were completed"


@pytest.mark.parametrize("msg", ["Ri Bhoi only", "what about Ri Bhoi?"])
def test_w3_graph_one_place_of_a_breakdown(chat, msg):
    chat("PMAY-G houses completed by district")
    got = chat(msg)
    # before: "Ri Bhoi only" / "what about Ri Bhoi?" went on as typed (the model down)
    assert got["question"] == "PMAY-G houses completed in Ri Bhoi"
    assert got["prior"].get("district") == "RI BHOI"


def test_w3_graph_only_a_block_inside_a_district(chat):
    chat("How many PMAY-G houses were completed in Ri Bhoi by block")
    # before: "only Umsning block" as typed
    assert chat("only Umsning block")["question"] == "How many PMAY-G houses were completed in Umsning block, Ri Bhoi"


def test_w4_graph_roll_up_and_unusual_wordings(chat):
    chat("MGNREGA expenditure in Ri Bhoi in FY 2023-24")
    # before: "by district" as typed, with the district inherited (the roll-up refused)
    got = chat("by district")
    assert got["question"] == "MGNREGA expenditure by district in FY 2023-24" and "district" not in got["prior"]
    # before: "what about block wise breakdown" as typed
    assert chat("what about block wise breakdown")["question"] == "MGNREGA expenditure by block in FY 2023-24"


def test_w5_a_regroup_after_a_knowledge_aside_on_the_same_scheme(chat):
    # before: every follow-up rule needed prev.route == "data"; the aside made the regroup go to the model
    chat("Total MGNREGA expenditure in Ri Bhoi in FY 2023-24")
    chat("How is MGNREGA expenditure audited?", knowledge=["MGNREGA"])
    got = chat("break that down by block")
    assert got["question"] == "Total MGNREGA expenditure in Ri Bhoi by block in FY 2023-24"
    assert got["prior"].get("district") == "RI BHOI" and got["prior"].get("year_key") == 2023


def test_w5_an_aside_about_another_scheme_is_not_continued(chat):
    chat("Total MGNREGA expenditure in Ri Bhoi in FY 2023-24")
    chat("What is PMAY-G?", knowledge=["PMAY-G"])
    s_turns_before = chat("break that down by block")
    assert s_turns_before is None or s_turns_before["question"] != \
        "Total MGNREGA expenditure in Ri Bhoi by block in FY 2023-24"


def test_w6_a_fresh_worker_continues_the_data_answer_after_an_aside(chat):
    # before: the snapshot kept only the last turn in full (the aside): the regroup found no data answer
    chat("Total MGNREGA expenditure in Ri Bhoi in FY 2023-24")
    chat("How is MGNREGA expenditure audited?", knowledge=["MGNREGA"])
    got = chat("now by block", fresh=True)
    assert got["question"] == "Total MGNREGA expenditure in Ri Bhoi by block in FY 2023-24"


def test_w6_the_frame_survives_every_worker_hop_of_a_chain(chat):
    chat("Total MGNREGA expenditure in FY 2023-24 by district")
    assert chat("which is the lowest", fresh=True)["question"] == \
        "Which district has the lowest: Total MGNREGA expenditure in FY 2023-24"
    assert chat("top 3", fresh=True)["question"] == "Top 3 districts: Total MGNREGA expenditure in FY 2023-24"
    assert chat("now by block", fresh=True)["question"] == "Top 3 blocks: Total MGNREGA expenditure in FY 2023-24"
    assert chat("what about 2022-23", fresh=True)["question"] == \
        "Top 3 blocks: Total MGNREGA expenditure in FY 2022-23"


def test_w7_a_roll_up_inherits_nothing_it_cleared(chat):
    # before: "by district" after a block's answer went to the model, and the block / district were inherited
    chat("MGNREGA expenditure in Gambegre block, West Garo Hills in FY 2022-23")
    got = chat("by district")
    assert got["question"] == "MGNREGA expenditure by district in FY 2022-23"
    assert "block" not in got["prior"] and "district" not in got["prior"] and got["prior"].get("year_key") == 2022


def test_w7_one_place_replaces_the_place_and_keeps_the_year(chat):
    chat("MGNREGA expenditure in Gambegre block, West Garo Hills in FY 2022-23")
    got = chat("what about Ri Bhoi?")
    assert got["question"] == "MGNREGA expenditure in Ri Bhoi in FY 2022-23"
    assert got["prior"].get("district") == "RI BHOI" and "block" not in got["prior"]


# ── ordinal / "yes" replies to a scheme pause ────────────────────────────────

SCHEME_CHIPS = [{"label": "Focus Plus", "question": "How many beneficiaries under Focus Plus?"},
                {"label": "Focus Legacy", "question": "How many beneficiaries under Focus Legacy?"}]


@pytest.mark.parametrize("reply,want", [
    ("the first one", 0), ("1", 0), ("first", 0), ("the second", 1), ("2", 1), ("second one please", 1),
    ("the last one", 1), ("#2", 1),
])
def test_scheme_pause_ordinal_picks(reply, want):
    # before: None (only the option pauses read ordinals); the voice agent speaks its picks
    assert p._resume_scheme_pause(reply, SCHEME_CHIPS) == SCHEME_CHIPS[want]["question"]


def test_scheme_pause_yes_picks_only_a_single_chip():
    assert p._resume_scheme_pause("yes", SCHEME_CHIPS[:1]) == SCHEME_CHIPS[0]["question"]
    assert p._resume_scheme_pause("yes please", SCHEME_CHIPS[:1]) == SCHEME_CHIPS[0]["question"]
    assert p._resume_scheme_pause("yes", SCHEME_CHIPS) is None                 # two chips: not a guess
    assert p._resume_scheme_pause("the third one", SCHEME_CHIPS) is None       # no such chip
    assert p._resume_scheme_pause("Focus Legacy", SCHEME_CHIPS) == SCHEME_CHIPS[1]["question"]   # unchanged


# ── the snapshot, the topic ledger, the context frames ───────────────────────

def _session_with(*turns):
    s = Session(session_id="snap", user_id="u", created=time.time(), last_seen=time.time())
    s.turns = list(turns)
    return s


def test_the_snapshot_keeps_the_last_two_turns_frames():
    a = _in_ri_bhoi_turn()
    b = _turn("How is MGNREGA expenditure audited?", ["MGNREGA"], {}, "", route="knowledge")
    s = _session_with(a, b)
    other = _session_with()
    other.apply_snapshot(s.to_snapshot())
    assert other.turns[-1].route == "knowledge"
    assert other.turns[-2].route == "data" and other.turns[-2].answer_frame == a.answer_frame
    assert af.from_turn(other.turns[-2]).filters == {"district": "RI BHOI", "year_key": 2023}


def test_an_old_snapshot_loads_with_empty_frames():
    s = _session_with(_in_ri_bhoi_turn(), _by_district_turn())
    snap = s.to_snapshot()
    snap["_session"].pop("turn_before")
    snap["_session"]["last_turn"].pop("answer_frame")
    other = _session_with()
    other.apply_snapshot(snap)
    assert other.turns[-1].answer_frame == {} and other.turns[-2].route == "history"
    assert af.from_turn(other.turns[-1]).is_empty()
    assert p._c18_frame_followup("now by block", other.turns[-1], other) is None    # nothing guessed


def test_the_topic_ledger_and_the_graph_state_carry_the_frame():
    t = _top3_turn()
    assert topic_memory._turn_from(topic_memory._turn_dict(t)).answer_frame == t.answer_frame
    assert Turn(**dataclasses.asdict(t)).answer_frame == t.answer_frame


def test_the_context_frames_record_the_answer_frame(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_FRAMES_ENABLED", True)
    s = _session_with()
    res = {"route": "data", "schemes": ["PMAY-G"], "resolved_entities": {},
           "sql": _cat("pmay_houses_completed", "ranking", "district", "desc", 3)}
    res["answer_frame"] = p._c18_fill_frame("Top 3 districts: How many PMAY-G houses were completed", res)
    context_frames.record(s, "top 3", {**res, "rewritten_question": "Top 3 districts: How many PMAY-G houses were completed"})
    fr = s.frames[-1]
    assert (fr["measure"], fr["group"], fr["order"], fr["limit"]) == ("pmay_houses_completed", "district", "desc", 3)
    assert fr["af"]["qtype"] == "ranking"


def test_after_an_aside_an_older_snapshot_finds_the_data_frame_in_the_context_frames(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_FRAMES_ENABLED", True)
    a = _in_ri_bhoi_turn()
    b = _turn("How is MGNREGA expenditure audited?", ["MGNREGA"], {}, "", route="knowledge")
    s = _session_with(a, b)
    context_frames.record(s, a.question, {"route": "data", "schemes": ["MGNREGA"], "resolved_entities":
                                          a.resolved_entities, "answer_frame": a.answer_frame})
    context_frames.record(s, b.question, {"route": "knowledge", "schemes": ["MGNREGA"]})
    snap = s.to_snapshot()
    snap["_session"].pop("turn_before")                 # as a snapshot that kept only the last turn
    other = _session_with()
    other.apply_snapshot(snap)
    out = p._c18_frame_followup("by block", other.turns[-1], other)
    assert out[1] == "MGNREGA expenditure in Ri Bhoi by block in FY 2023-24"


# ── the catalogue takes the frame (step 4) ───────────────────────────────────

@pytest.fixture
def catalogue(monkeypatch):
    cols = frozenset({"lgd_district", "lgd_block", "year_key", "village_code"})
    metrics = {k: mc.Metric(key=k, scheme="PMAY-G", display_name=k, expression="COUNT(*)", base_object="curated.v_pmay",
                            unit="houses", notes="", alias=k, phrases=ph, columns=cols)
               for k, ph in (("pmay_houses_completed", (("house", "completed"), ("completed", "house"))),
                             ("pmay_houses_sanctioned", (("house", "sanctioned"),)))}
    verified = {t: {} for t in mc.QUERY_TYPES}
    for t in ("total", "breakdown", "ranking"):
        verified[t]["pmay_houses_completed"] = {"ok": True}
    state = {"metrics": metrics, "by_scheme": {"PMAY-G": list(metrics.values())}, "loaded": True,
             "no_block_level": frozenset(), "single_year": frozenset(), "verified": verified}
    monkeypatch.setattr(mc, "_state", state)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")
    return state


def _all_years_top3():
    return _turn("Top 3 districts: How many PMAY-G houses were completed across all financial years", ["PMAY-G"], {},
                 _cat("pmay_houses_completed", "ranking", "district", "desc", 3))


def test_the_catalogue_builds_the_follow_up_from_the_frame(catalogue):
    kind, q, frame, _plan = p._c18_frame_followup("now by block", _all_years_top3())
    assert q == "Top 3 blocks: How many PMAY-G houses were completed across all financial years"
    sql, _params, shown = p._metric_catalog_query(q, ["PMAY-G"], {"resolved": {}}, frame=frame)
    assert shown.startswith("/* metric:pmay_houses_completed ranking */")
    assert "GROUP BY lgd_block" in shown and "DESC NULLS LAST LIMIT 3" in shown


def test_the_catalogue_frame_needs_a_verified_measure_and_agreeing_filters(catalogue):
    kind, q, frame, _plan = p._c18_frame_followup("only Ri Bhoi", _all_years_top3())
    # the resolver read another place than the frame: the words decide, not the frame
    assert p._c18_catalogue_from_frame(frame, q, ["PMAY-G"], {"resolved": {"district": "EAST KHASI HILLS"}}) is None
    built = p._c18_catalogue_from_frame(frame, q, ["PMAY-G"], {"resolved": {"district": "RI BHOI"}})
    assert built is not None and "UPPER(lgd_district) = 'RI BHOI'" in built[2]
    catalogue["verified"]["total"].pop("pmay_houses_completed")
    assert p._c18_catalogue_from_frame(frame, q, ["PMAY-G"], {"resolved": {"district": "RI BHOI"}}) is None


def test_a_frame_from_a_model_answer_never_drives_the_catalogue(catalogue):
    t = _turn("How many PMAY-G houses were completed by district", ["PMAY-G"], {},
              "SELECT lgd_district, COUNT(*) FROM curated.v_pmay GROUP BY lgd_district")
    kind, q, frame, _plan = p._c18_frame_followup("now by block", t)
    assert frame["metric_key"] is None
    assert p._c18_catalogue_from_frame(frame, q, ["PMAY-G"], {"resolved": {}}) is None


def test_a_measure_swap_on_a_catalogue_frame_keeps_the_catalogue_key(catalogue):
    t = _turn("How many PMAY-G houses were completed in Ri Bhoi in FY 2023-24", ["PMAY-G"],
              {"district": "RI BHOI", "year_key": 2023}, _cat("pmay_houses_completed", "total"))
    kind, q, frame, plan = p._c18_frame_followup("and the houses sanctioned instead", t)
    assert kind == "measure" and frame["metric_key"] == "pmay_houses_sanctioned"
    assert q == "How many PMAY-G houses sanctioned in Ri Bhoi in FY 2023-24"     # c01's measure swap, as before
    assert plan.action("metric") == context_policy.REPLACE and plan.action("district") == context_policy.KEEP


# ── the chain matrix: first-question shapes x follow-up kinds ────────────────

FIRSTS = {
    "total-district-year": ("MGNREGA expenditure in Ri Bhoi in FY 2023-24", {"district": "RI BHOI", "year_key": 2023},
                            _model()),
    "statewide-by-district": ("MGNREGA expenditure by district in FY 2023-24", {"year_key": 2023}, _model("district")),
    "by-block-in-district": ("MGNREGA expenditure in Ri Bhoi by block", {"district": "RI BHOI"}, _model("block")),
    "top3-districts": ("Top 3 districts: MGNREGA expenditure in FY 2023-24", {"year_key": 2023},
                       _model("district", "desc", 3)),
    "block-total": ("MGNREGA expenditure in Umsning block, Ri Bhoi in FY 2023-24",
                    {"block": "UMSNING", "district": "RI BHOI", "year_key": 2023}, _model()),
}
# follow-up -> {first shape: (the question rendered, qtype, group, filters)}; a missing shape = left to older paths
FOLLOWUPS = {
    "break that down by district": {
        "total-district-year": ("MGNREGA expenditure by district in FY 2023-24", "breakdown", "district",
                                {"year_key": 2023}),
        "statewide-by-district": ("MGNREGA expenditure by district in FY 2023-24", "breakdown", "district",
                                  {"year_key": 2023}),
        "by-block-in-district": ("MGNREGA expenditure by district", "breakdown", "district", {}),
        "top3-districts": ("Top 3 districts: MGNREGA expenditure in FY 2023-24", "ranking", "district",
                           {"year_key": 2023}),
        "block-total": ("MGNREGA expenditure by district in FY 2023-24", "breakdown", "district", {"year_key": 2023}),
    },
    "now by block": {
        "total-district-year": ("MGNREGA expenditure in Ri Bhoi by block in FY 2023-24", "breakdown", "block",
                                {"district": "RI BHOI", "year_key": 2023}),
        "statewide-by-district": ("MGNREGA expenditure by block in FY 2023-24", "breakdown", "block",
                                  {"year_key": 2023}),
        "by-block-in-district": ("MGNREGA expenditure in Ri Bhoi by block", "breakdown", "block",
                                 {"district": "RI BHOI"}),
        "top3-districts": ("Top 3 blocks: MGNREGA expenditure in FY 2023-24", "ranking", "block", {"year_key": 2023}),
        "block-total": ("MGNREGA expenditure in Ri Bhoi by block in FY 2023-24", "breakdown", "block",
                        {"district": "RI BHOI", "year_key": 2023}),
    },
    "only Ri Bhoi": {
        "statewide-by-district": ("MGNREGA expenditure in Ri Bhoi in FY 2023-24", "total", None,
                                  {"district": "RI BHOI", "year_key": 2023}),
        "total-district-year": ("MGNREGA expenditure in Ri Bhoi in FY 2023-24", "total", None,
                                {"district": "RI BHOI", "year_key": 2023}),
        "by-block-in-district": ("MGNREGA expenditure in Ri Bhoi by block", "breakdown", "block",
                                 {"district": "RI BHOI"}),
        "top3-districts": ("MGNREGA expenditure in Ri Bhoi in FY 2023-24", "total", None,
                           {"district": "RI BHOI", "year_key": 2023}),
        "block-total": ("MGNREGA expenditure in Ri Bhoi in FY 2023-24", "total", None,
                        {"district": "RI BHOI", "year_key": 2023}),
    },
    "which is the lowest": {
        "statewide-by-district": ("Which district has the lowest: MGNREGA expenditure in FY 2023-24", "ranking",
                                  "district", {"year_key": 2023}),
        "by-block-in-district": ("Which block has the lowest: MGNREGA expenditure in Ri Bhoi", "ranking", "block",
                                 {"district": "RI BHOI"}),
        "top3-districts": ("Bottom 3 districts: MGNREGA expenditure in FY 2023-24", "ranking", "district",
                           {"year_key": 2023}),
    },
    "top 3": {
        "statewide-by-district": ("Top 3 districts: MGNREGA expenditure in FY 2023-24", "ranking", "district",
                                  {"year_key": 2023}),
        "by-block-in-district": ("Top 3 blocks: MGNREGA expenditure in Ri Bhoi", "ranking", "block",
                                 {"district": "RI BHOI"}),
        "top3-districts": ("Top 3 districts: MGNREGA expenditure in FY 2023-24", "ranking", "district",
                           {"year_key": 2023}),
    },
    "what about 2022-23": {
        "total-district-year": ("MGNREGA expenditure in Ri Bhoi in FY 2022-23", "total", None,
                                {"district": "RI BHOI", "year_key": 2022}),
        "statewide-by-district": ("MGNREGA expenditure by district in FY 2022-23", "breakdown", "district",
                                  {"year_key": 2022}),
        "by-block-in-district": ("MGNREGA expenditure in Ri Bhoi by block in FY 2022-23", "breakdown", "block",
                                 {"district": "RI BHOI", "year_key": 2022}),
        "top3-districts": ("Top 3 districts: MGNREGA expenditure in FY 2022-23", "ranking", "district",
                           {"year_key": 2022}),
        "block-total": ("MGNREGA expenditure in Umsning block, Ri Bhoi in FY 2022-23", "total", None,
                        {"block": "UMSNING", "district": "RI BHOI", "year_key": 2022}),
    },
    "and the year before?": {
        "total-district-year": ("MGNREGA expenditure in Ri Bhoi in FY 2022-23", "total", None,
                                {"district": "RI BHOI", "year_key": 2022}),
        "statewide-by-district": ("MGNREGA expenditure by district in FY 2022-23", "breakdown", "district",
                                  {"year_key": 2022}),
    },
    "what about East Khasi Hills?": {
        "total-district-year": ("MGNREGA expenditure in East Khasi Hills in FY 2023-24", "total", None,
                                {"district": "EAST KHASI HILLS", "year_key": 2023}),
        "by-block-in-district": ("MGNREGA expenditure in East Khasi Hills by block", "breakdown", "block",
                                 {"district": "EAST KHASI HILLS"}),
        "block-total": ("MGNREGA expenditure in East Khasi Hills in FY 2023-24", "total", None,
                        {"district": "EAST KHASI HILLS", "year_key": 2023}),
    },
    "break it down by financial year": {
        "total-district-year": ("MGNREGA expenditure in Ri Bhoi by financial year", "breakdown", "year",
                                {"district": "RI BHOI"}),
        "by-block-in-district": ("MGNREGA expenditure in Ri Bhoi by financial year", "breakdown", "year",
                                 {"district": "RI BHOI"}),
    },
}
MATRIX = [(first, msg) for msg in FOLLOWUPS for first in FIRSTS]


def _first_turn(shape):
    q, resolved, sql = FIRSTS[shape]
    return _turn(q, ["MGNREGA"], resolved, sql)


@pytest.mark.parametrize("first,msg", MATRIX)
@pytest.mark.parametrize("fresh", [False, True])
def test_the_chain_matrix(first, msg, fresh):
    t = _first_turn(first)
    session = None
    if fresh:                                   # another worker, from the durable snapshot alone
        s = _session_with(t)
        session = _session_with()
        session.apply_snapshot(s.to_snapshot())
        t = session.turns[-1]
    out = p._c18_frame_followup(msg, t, session)
    want = FOLLOWUPS[msg].get(first)
    if want is None:
        assert out is None or out[1], (first, msg)          # left to the older paths, or a well-formed question
        return
    assert out is not None, (first, msg)
    _kind, q, frame, plan = out
    assert q == want[0], (first, msg)
    assert (frame["qtype"], frame["group"], frame["filters"]) == want[1:], (first, msg)
    # the inherited filters are exactly the frame's (W7)
    prior = p._c18_prior_from_frame({"district": "WEST GARO HILLS", "block": "GAMBEGRE", "year_key": 2019,
                                     "tranche_label": "T1"}, frame["filters"])
    assert {k: v for k, v in prior.items() if k != "tranche_label"} == frame["filters"]
    assert prior["tranche_label"] == "T1"
    # the rendered question reads back into the same frame
    back = af.from_turn(_turn(q, ["MGNREGA"], frame["filters"], _fake_sql(q)))
    assert (back.qtype, back.group, back.measure_text) == (frame["qtype"], frame["group"], "MGNREGA expenditure")


@pytest.mark.parametrize("msg", [
    "How many PMAY-G houses were completed in Ri Bhoi?",       # a new question: its own scheme and measure
    "and Focus Plus?", "compare with PMAY-G", "what is MGNREGA", "thanks", "why?", "Ri Bhoi",
    "which year was the highest", "show me the districts, I'll choose one",
])
def test_what_the_frame_leaves_to_the_other_paths(msg):
    for shape in FIRSTS:
        assert p._c18_frame_followup(msg, _first_turn(shape)) is None, (shape, msg)

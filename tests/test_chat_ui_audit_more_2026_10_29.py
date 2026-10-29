"""Chat UI audit 2026-10-29, the items finished after the first pass: the user's
decisions (J-4 / J-5 / J-10 / G-10 / H-5 / H-6 / H-8 / B-5 / K-6 / K-16 / X-4 / X-16)
and the "not done" / "partly fixed" list (B-6, E-3, E-9, F-7, F-8, I-10 / J-7, I-13,
K-24, K-36, X-14, A-16). Real functions, fake database rows in the shapes the
queries return."""
import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import conversation_store, cross_figures as cf, prompt_builder, sql_ast
from app import pipeline as p
from app.routers import query as router
from app.session_store import session_store

M = p._SCHEME_NAME_MATCHER


# ── K-6: Regenerate / Edit replace the saved turns too ──────────────────────
class _TurnsDb:
    """app.conversations + app.conversation_turns, enough for truncate_turns."""

    def __init__(self, turns):
        self.turns = list(turns)           # [{"id", "response"}] in created order
        self.turn_count = len(turns)
        self.deleted = []

    async def fetchval(self, sql, params):
        return 7 if "FROM app.conversations" in sql else None

    async def fetch_rows(self, sql, params):
        assert "OFFSET $2" in sql and params[0] == 7
        return self.turns[params[1]:]

    async def execute(self, sql, params):
        if sql.startswith("DELETE FROM app.conversation_turns"):
            self.deleted += params[0]
            self.turns = [t for t in self.turns if t["id"] not in params[0]]
        elif sql.startswith("UPDATE app.conversations SET turn_count"):
            self.turn_count -= params[0]
        return "OK"


def _turn(i, ctx=None):
    return {"id": i, "response": json.dumps({"answer": f"A{i}", "_context_before": ctx})}


def test_truncate_keeps_the_first_turns_and_returns_the_context_before_the_rest(monkeypatch):
    fake = _TurnsDb([_turn(1), _turn(2, {"snapshot": {"scheme": "PMAY-G"}, "summary": "s2"}), _turn(3)])
    for name in ("fetchval", "fetch_rows", "execute"):
        monkeypatch.setattr(conversation_store.db, name, getattr(fake, name))
    ctx = asyncio.run(conversation_store.truncate_turns(session_id="s", user_id=1, keep=1))
    assert fake.deleted == [2, 3] and fake.turn_count == 1
    assert ctx == {"snapshot": {"scheme": "PMAY-G"}, "summary": "s2"}
    # idempotent: the same request again deletes nothing more
    assert asyncio.run(conversation_store.truncate_turns(session_id="s", user_id=1, keep=1)) is None
    assert fake.deleted == [2, 3]


def test_the_saved_context_never_reaches_the_client(monkeypatch):
    async def rows(sql, params):
        return [{"id": 1, "question": "q", "response": json.dumps({"answer": "a", "_context_before": {"x": 1}})}]
    monkeypatch.setattr(conversation_store.db, "fetch_rows", rows)
    turns = asyncio.run(conversation_store.get_conversation_turns(session_id="s", user_id=1))
    assert turns[0]["response"] == {"answer": "a"}


def _request():
    async def receive():
        await asyncio.sleep(3600)
    return Request({"type": "http", "method": "POST", "path": "/api/query", "headers": [],
                    "client": ("127.0.0.1", 1), "query_string": b""}, receive)


@pytest.fixture
def stubbed(monkeypatch):
    seen = SimpleNamespace(persisted=[], truncated=[], synced=0)

    async def none(*a, **k):
        return None

    async def lookup(*a, **k):
        return None, None

    async def answer_question(q, session=None, scope=None):
        return {"answer": "fresh", "route": "data", "schemes": ["MGNREGA"], "resolved_entities": {}}

    async def truncate(**k):
        seen.truncated.append(k)
        return {"snapshot": {"scheme": "PMAY-G"}, "summary": None}

    async def sync_out(*a, **k):
        seen.synced += 1
    monkeypatch.setattr(router.response_cache, "get", none)
    monkeypatch.setattr(router.response_cache, "put", none)
    monkeypatch.setattr(router.semantic_cache, "lookup", lookup)
    monkeypatch.setattr(router.semantic_cache, "put", none)
    monkeypatch.setattr(router, "answer_question", answer_question)
    monkeypatch.setattr(router.session_sync, "sync_in", none)
    monkeypatch.setattr(router.session_sync, "sync_out", sync_out)
    monkeypatch.setattr(router.conversation_store, "persist_turn", lambda **k: seen.persisted.append(k))
    monkeypatch.setattr(router.conversation_store, "truncate_turns", truncate)
    monkeypatch.setattr(router.conversation_memory, "index_turn", lambda **k: None)
    monkeypatch.setattr(router, "_mirror_audit", lambda *a, **k: None)
    seen.scope = SimpleNamespace(user_id="u", db_user_id=5, tenant_id=1, username="",
                                 cache_fingerprint=lambda: "fp")
    return seen


def test_keep_turns_truncates_and_restores_the_context(stubbed):
    req = router.QueryRequest(question="How many MGNREGA job cards are there?", session_id="k6-a", keep_turns=2)
    asyncio.run(router._answer(req, _request(), stubbed.scope))
    assert stubbed.truncated == [{"session_id": "k6-a", "user_id": 5, "keep": 2}]
    # the context before this turn is the restored one, saved with the new turn
    assert stubbed.persisted[0]["context_before"]["snapshot"]["scheme"] == "PMAY-G"


def test_a_plain_question_truncates_nothing_and_saves_its_context(stubbed):
    asyncio.run(router._answer(router.QueryRequest(question="How many MGNREGA job cards?", session_id="k6-b"),
                               _request(), stubbed.scope))
    assert stubbed.truncated == []
    assert "snapshot" in stubbed.persisted[0]["context_before"]


def test_k24_the_officers_own_words_are_saved(stubbed, monkeypatch):
    async def to_english(text, lang):
        return "How many MGNREGA job cards are there?"
    monkeypatch.setattr(router.translate, "to_english", to_english)
    req = router.QueryRequest(question="Katno MGNREGA job card?", session_id="k24", language="kha")
    asyncio.run(router._answer(req, _request(), stubbed.scope))
    assert stubbed.persisted[0]["question"] == "Katno MGNREGA job card?"


# ── F-7 / F-8: year chips ───────────────────────────────────────────────────
def test_f7_shared_years_first_and_the_rest_say_which_scheme():
    e = p._year_clarification("Compare MGNREGA and PMAY-G beneficiaries in East Khasi Hills", ["MGNREGA", "PMAY-G"])
    labels = [o["label"] for o in e.options]
    assert labels[:2] == ["FY 2022-23", "FY 2023-24"]
    assert "FY 2017-18 (PMAY-G only)" in labels and "FY 2025-26 (MGNREGA only)" in labels
    assert "Both hold FY 2022-23, FY 2023-24" in str(e)
    one = [o["label"] for o in p._year_clarification("x", ["MGNREGA"]).options]
    assert one[0] == "FY 2022-23" and not any("only" in x for x in one)


def test_f8_a_future_year_beside_a_valid_one_keeps_the_comparison():
    q = "Compare MGNREGA person days in 2027-28 and 2024-25 in Ri Bhoi"
    e = p._year_out_of_range_clarification(q, "2027-28", ["MGNREGA"])
    assert "FY 2027-28 has no data yet" in str(e)
    assert e.options[0] == {"label": "FY 2025-26 (latest) with FY 2024-25",
                            "question": "Compare MGNREGA person days in FY 2025-26 and 2024-25 in Ri Bhoi"}
    assert all("2024-25" in o["question"] and "Ri Bhoi" in o["question"] for o in e.options)


# ── B-6: the knowledge comparison offers the figures ───────────────────────
def test_b6_compare_two_schemes_with_no_figure_offers_figure_chips():
    # (a bare "Compare MGNREGA and PMAY-G" is answered with figures by cross_figures)
    for q in ("What is the difference between MGNREGA and PMAY-G?", "Compare MGNREGA and PMAY-G schemes"):
        out = p._scheme_comparison_answer(q, None)
        labels = [o["label"] for o in out["follow_up_options"]]
        assert labels == ["Compare beneficiaries in MGNREGA and PMAY-G", "Compare money spent in MGNREGA and PMAY-G"]
        assert out["keep_follow_ups"] is True and out["route"] == "knowledge"
    assert cf.plan("Compare MGNREGA and PMAY-G", ["MGNREGA", "PMAY-G"], {}, {}, M).measures == ["count", "money"]


# ── E-3 / E-9 / I-10: counts behind a ranking ──────────────────────────────
def test_e3_the_true_count_wraps_the_query():
    seen = []

    async def run(sql):
        seen.append(sql)
        return [{"total_rows": 1532}]
    p.run_readonly, old = run, p.run_readonly
    try:
        assert asyncio.run(p._c11_true_row_count("SELECT a FROM curated.v_x;")) == 1532
    finally:
        p.run_readonly = old
    assert seen == ["SELECT COUNT(*) AS total_rows FROM (SELECT a FROM curated.v_x) AS capped_result"]


def test_i10_lowest_villages_skip_the_zeros_and_say_how_many():
    sql = ("SELECT lgd_village_name, SUM(b) AS beneficiaries FROM curated.v_employment GROUP BY 1 "
           "ORDER BY beneficiaries ASC LIMIT 5")
    rows = [{"lgd_village_name": f"V{i}", "beneficiaries": 0} for i in range(5)]

    async def run(q):
        if "zero_places" in q:
            return [{"zero_places": 312}]
        assert '"beneficiaries" > 0' in q and "LIMIT 5" in q
        return [{"lgd_village_name": "W1", "beneficiaries": 1}, {"lgd_village_name": "W2", "beneficiaries": 2}]
    p.run_readonly, old = run, p.run_readonly
    try:
        er = {}
        got = asyncio.run(p._c11_zero_ties("lowest 5 villages by beneficiaries in MGNREGA", sql, rows, er))
    finally:
        p.run_readonly = old
    assert [r["lgd_village_name"] for r in got] == ["W1", "W2"]
    assert er["zero_note"].startswith("312 villages have no beneficiaries (0)")


def test_e9_ties_for_the_last_place_are_said():
    sql = ("SELECT lgd_village_name, COUNT(*) AS houses FROM curated.v_pmay GROUP BY 1 "
           "ORDER BY houses DESC LIMIT 3")
    rows = [{"lgd_village_name": "A", "houses": 30}, {"lgd_village_name": "B", "houses": 20},
            {"lgd_village_name": "C", "houses": 12}]

    async def run(q):
        assert '"houses" = 12' in q
        return [{"tied": 3}]
    p.run_readonly, old = run, p.run_readonly
    try:
        er = {}
        got = asyncio.run(p._c11_zero_ties("top 3 villages by PMAY-G houses", sql, rows, er))
    finally:
        p.run_readonly = old
    assert got == rows
    assert er["tie_note"] == "3 villages tie for place 3 with 12 houses; 1 of them is shown."


def test_a_question_that_is_no_ranking_runs_no_extra_query():
    async def run(q):
        raise AssertionError("no extra query")
    p.run_readonly, old = run, p.run_readonly
    try:
        rows = [{"lgd_district": "A", "houses": 0}]
        assert asyncio.run(p._c11_zero_ties("houses in Ri Bhoi", "SELECT 1", rows, {})) == rows
    finally:
        p.run_readonly = old


# ── I-13: CM Elevate's own list beside an "all schemes" ranking ────────────
def test_i13_cm_elevate_gets_its_own_district_list(monkeypatch):
    async def rows(sql, params):
        assert "v_cm_elevate" in sql and "COUNT(DISTINCT request_id)" in sql
        return [{"district": "RI BHOI", "applications": 40}, {"district": "WEST GARO HILLS", "applications": 90}]
    monkeypatch.setattr(cf.db, "fetch_rows", rows)
    pl = SimpleNamespace(low=False, both=False, top_n=None, exclude=[])
    line, sql = asyncio.run(cf._cm_elevate_ranking(pl))
    assert line.startswith("CM Elevate, its own list (highest 2 districts by applications")
    assert line.endswith("1. West Garo Hills 90; 2. Ri Bhoi 40.")


# ── X-14: money with no unit in its name gets one ──────────────────────────
# the units semantic.column_catalog records (read live 2026-10-29)
_CATALOG = [
    {"table_name": "v_pmay", "column_name": "amount_released", "unit": "rupees"},
    {"table_name": "v_pmay", "column_name": "sanctioned_amount", "unit": "rupees"},
    {"table_name": "v_expenditure", "column_name": "total_exp", "unit": "lakh rupees"},
    {"table_name": "v_employment", "column_name": "person_days", "unit": "person-days"},
]


@pytest.fixture(autouse=True)
def _units(monkeypatch):
    from app import schema_introspect
    monkeypatch.setitem(schema_introspect._cache, "columns", _CATALOG)


@pytest.mark.parametrize("scheme, sql, col, want", [
    ("PMAY-G", "SELECT lgd_district, SUM(amount_released) AS amount_released FROM curated.v_pmay GROUP BY 1",
     "amount_released", "amount_released_rs"),
    ("PMAY-G", "SELECT lgd_district, ROUND(SUM(amount_released) / 10000000, 2) AS released_amount FROM curated.v_pmay GROUP BY 1",
     "released_amount", "released_amount_crore"),
    ("MGNREGA", "SELECT lgd_district, SUM(total_exp) AS total_expenditure FROM curated.v_expenditure GROUP BY 1",
     "total_expenditure", "total_expenditure_lakh"),
    ("MGNREGA", "SELECT lgd_district, SUM(total_exp) / 100 AS total_expenditure FROM curated.v_expenditure GROUP BY 1",
     "total_expenditure", "total_expenditure_crore"),
    ("PMAY-G", "SELECT lgd_district, SUM(amount_released) AS amount_released_crore FROM curated.v_pmay GROUP BY 1",
     "amount_released_crore", "amount_released_crore"),
])
def test_x14_money_columns_carry_their_unit(scheme, sql, col, want):
    r = {"route": "data", "schemes": [scheme], "sql": sql, "data": [{"lgd_district": "A", col: 5}]}
    p._c13_money_units(r)
    assert list(r["data"][0]) == ["lgd_district", want]


@pytest.mark.parametrize("sql, col", [
    # a count whose name holds a money word: its source has no money unit
    ("SELECT lgd_village_name, COUNT(*) AS houses_sanctioned_amount FROM curated.v_pmay GROUP BY 1",
     "houses_sanctioned_amount"),
    # a ratio of two columns is not money in rupees
    ("SELECT lgd_district, SUM(amount_released) / SUM(sanctioned_amount) AS released_share FROM curated.v_pmay "
     "GROUP BY 1", "released_share"),
    # a source column the catalog has no unit for: nothing is guessed
    ("SELECT lgd_district, SUM(mystery_amount) AS amount FROM curated.v_pmay GROUP BY 1", "amount"),
    # person-days are not money
    ("SELECT lgd_district, SUM(person_days) AS person_days FROM curated.v_employment GROUP BY 1", "person_days"),
])
def test_x14_only_catalog_money_is_renamed(sql, col):
    r = {"route": "data", "schemes": ["PMAY-G"], "sql": sql, "data": [{"lgd_district": "A", col: 5}]}
    p._c13_money_units(r)
    assert list(r["data"][0]) == ["lgd_district", col]


def test_x14_no_catalog_no_rename(monkeypatch):
    from app import schema_introspect
    monkeypatch.setitem(schema_introspect._cache, "columns", [])
    r = {"route": "data", "schemes": ["PMAY-G"], "data": [{"d": "A", "amount_released": 5}],
         "sql": "SELECT d, SUM(amount_released) AS amount_released FROM curated.v_pmay GROUP BY 1"}
    p._c13_money_units(r)
    assert list(r["data"][0]) == ["d", "amount_released"]


def test_x14_several_schemes_are_left_alone():
    r = {"route": "data", "schemes": ["MGNREGA", "PMAY-G"], "sql": "", "data": [{"scheme": "x", "amount": 5}]}
    p._c13_money_units(r)
    assert list(r["data"][0]) == ["scheme", "amount"]


# ── J-10: twin villages answered together, named with their blocks ─────────
def test_j10_twins_ask_the_block_in_the_sql_and_name_it_in_the_banner():
    resolved = {"village_code_list": [1, 2],
                "village_twins": {"1": "Apalgre (Dadenggre block)", "2": "Apalgre (Rongram block)"}}
    text = prompt_builder.build_sql_prompt("MGNREGA person days in Apalgre", ["MGNREGA"],
                                           {"resolved": resolved, "display": {}, "notes": []})
    assert "SELECT the block name too" in text and "village_twins" not in text
    r = {"route": "data", "schemes": ["MGNREGA"], "sql": "S", "resolved_entities": resolved}
    p._attach_scope_banner(r, None)
    assert r["scope_banner"].startswith("MGNREGA · Apalgre (Dadenggre block), Apalgre (Rongram block)")


# ── G-10: the Focus Legacy member figure says how it is counted ────────────
def test_g10_focus_legacy_members_say_they_are_counted_per_payment():
    assert "once per payment" in cf.measure_notes(["Focus Legacy"])["Focus Legacy"]["beneficiaries"]


# ── K-36 / E-3 (UI, through the real JSX) ──────────────────────────────────
_FRONT = Path(__file__).resolve().parents[1] / "frontend"
_NODE = shutil.which("node")
_ESBUILD = _FRONT / "node_modules" / ".bin" / ("esbuild.cmd" if os.name == "nt" else "esbuild")
_ENTRY = """
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { DynTable, RowTotal } from '%(src)s/chat/components/Charts.jsx';
import { parseBlocks } from '%(src)s/chat/components/Markdown.jsx';
globalThis.T = {
  parseBlocks,
  capped: (rows, total) => renderToStaticMarkup(createElement(RowTotal.Provider, { value: total },
    createElement(DynTable, { data: rows }))),
};
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    if not _NODE or not _ESBUILD.exists():
        pytest.skip("node / frontend node_modules missing")
    d = tmp_path_factory.mktemp("audit_more")
    entry = d / "entry.jsx"
    entry.write_text(_ENTRY % {"src": (_FRONT / "src").as_posix()}, encoding="utf-8")
    out = d / "bundle.cjs"
    env = dict(os.environ, NODE_PATH=str(_FRONT / "node_modules"))
    r = subprocess.run([str(_ESBUILD), str(entry), "--bundle", "--platform=node", "--format=cjs", "--jsx=automatic",
                        f"--outfile={out}", "--log-level=error"], capture_output=True, text=True, env=env,
                       timeout=120, shell=os.name == "nt")
    assert r.returncode == 0, r.stderr
    return out


def _js(bundle, expr, **data):
    lets = "".join(f"const {k} = {json.dumps(v)};" for k, v in data.items())
    script = f"require({json.dumps(str(bundle))}); const T = globalThis.T; {lets} console.log(JSON.stringify({expr}));"
    r = subprocess.run([_NODE, "-e", script], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_k36_lenient_answer_text_tables(bundle):
    text = "| District | Houses |\n|---|---|\n| Ri Bhoi | 120\n| A \\| B | 5 | extra |\nWest Garo Hills | 7"
    blocks = _js(bundle, "T.parseBlocks(t)", t=text)
    assert blocks == [{"type": "table", "head": ["District", "Houses"],
                       "rows": [["Ri Bhoi", "120"], ["A | B", "5 | extra"], ["West Garo Hills", "7"]]}]


def test_e3_a_capped_table_says_the_true_total(bundle):
    rows = "Array.from({ length: 1000 }, (_, i) => ({ village: 'V' + i, houses: i }))"
    html = _js(bundle, f"T.capped({rows}, 1532)")
    assert "The first 1,000 of 1,532 rows are shown." in html
    assert "there may be more" in _js(bundle, f"T.capped({rows}, null)")


# ── found in the live run (2026-10-29 evening) ─────────────────────────────
def test_c1_two_named_years_are_both_kept_for_one_scheme(monkeypatch):
    async def extract(q):
        return {"year": "2024-25"}            # the extractor hands back one year
    monkeypatch.setattr(p, "extract_entity_mentions", extract)
    out = asyncio.run(p.resolve_entities("Compare MGNREGA expenditure 2023-24 vs 2024-25", ["MGNREGA"]))
    assert out["resolved"].get("year_key_list") == [2023, 2024] and "year_key" not in out["resolved"]
    r = {"route": "data", "schemes": ["MGNREGA"], "sql": "S", "resolved_entities": out["resolved"]}
    p._attach_scope_banner(r, None)
    assert r["scope_banner"] == "MGNREGA · All of Meghalaya · FY 2023-24, FY 2024-25"   # never "All years"


def test_i13_a_scheme_with_its_own_list_is_not_no_data_in_the_banner():
    r = {"route": "data", "schemes": ["MGNREGA", "PMAY-G", "CM Elevate", "CM Elevate Legacy"], "sql": "S",
         "resolved_entities": {}, "schemes_with_data": ["MGNREGA", "PMAY-G"],
         "schemes_apart": {"CM Elevate": "own list", "CM Elevate Legacy": "not ranked"}}
    p._attach_scope_banner(r, None)
    assert r["scope_banner"].startswith("MGNREGA + PMAY-G (CM Elevate: own list) (CM Elevate Legacy: not ranked)")


def test_e3_the_count_drops_the_querys_own_limit():
    assert sql_ast.without_limit("SELECT a FROM curated.v_x ORDER BY a DESC LIMIT 1000") == \
        "SELECT a FROM curated.v_x ORDER BY a DESC"


def test_x14_a_count_named_sanctioned_is_not_money():
    # live run: "houses_sanctioned" showed as "₹388"
    r = {"route": "data", "schemes": ["PMAY-G"], "sql": "", "data": [{"lgd_village_name": "A", "houses_sanctioned": 388}]}
    p._c13_money_units(r)
    assert list(r["data"][0]) == ["lgd_village_name", "houses_sanctioned"]


def test_i18_kis_district_is_a_question_word_not_a_place():
    assert p._c09_not_a_place("kis district") and p._c09_not_a_place("which district")
    assert not p._c09_not_a_place("Guwahati")


def test_c1_the_comparison_names_the_financial_year():
    shape = p._AnswerShape(kind="compare", labels=["year_key"], metrics=["total_expenditure_lakh"])
    row = {"year_key": 2024, "financial_year": "2024-25", "total_expenditure_lakh": 5}
    assert p._c12s_label(row, shape) == "2024-25"


def test_j10_a_filter_on_one_twin_is_widened_to_all():
    # live run: the model filtered one of three Apalgre villages, with LIMIT 1
    sql = ("SELECT lgd_village_name, lgd_block, SUM(person_days) AS person_days, village_code "
           "FROM curated.v_employment WHERE village_code = 273033 AND year_key = 2024 "
           "GROUP BY lgd_village_name, lgd_block, village_code LIMIT 1")
    out = sql_ast.widen_village_filter(sql, [273033, 272766, 273416])
    assert "village_code IN (273033, 272766, 273416)" in out and "LIMIT" not in out
    er = {"resolved": {"village_code_list": [273033, 272766, 273416], "village_twins": {"273033": "x"}}}
    assert "IN (273033, 272766, 273416)" in asyncio.run(p._scheme_sql_rewrites("q", ["MGNREGA"], er, sql))


def test_b8_the_bare_which_is_better_goes_to_the_figures():
    assert p._c13_bare_which_is_better("Which is better, MGNREGA or PMAY-G?")
    assert not p._c13_bare_which_is_better("Which is better for a landless family, MGNREGA or PMAY-G?")
    assert not p._c13_bare_which_is_better("Is MGNREGA better?")


def test_i2_top_n_per_year_is_ranked_inside_each_year():
    # live run: ORDER BY beneficiaries DESC LIMIT 5 over every year gave one year's top 5
    sql = ("SELECT lgd_district AS district, financial_year, SUM(beneficiary_households) AS beneficiaries "
           "FROM curated.v_employment GROUP BY lgd_district, financial_year ORDER BY beneficiaries DESC LIMIT 5")
    out = asyncio.run(p._scheme_sql_rewrites("top 5 districts in MGNREGA year wise", ["MGNREGA"],
                                             {"resolved": {}}, sql))
    assert 'ROW_NUMBER() OVER (PARTITION BY "financial_year" ORDER BY "beneficiaries" DESC NULLS LAST)' in out
    assert "rank_in_period <= 5" in out
    # not a per-year question: unchanged
    assert "ROW_NUMBER" not in asyncio.run(p._scheme_sql_rewrites("top 5 districts in MGNREGA", ["MGNREGA"],
                                                                  {"resolved": {}}, sql))
    # already windowed or no period column: left alone
    assert sql_ast.rank_within_period("SELECT d, SUM(b) AS b FROM curated.v GROUP BY 1 ORDER BY b DESC LIMIT 5") is None


def test_k17_a_translated_answer_carries_the_english_question(stubbed, monkeypatch):
    # live run: a documents answer had no rewritten question, so "Understood as" never showed
    async def to_english(text, lang):
        return "How do I apply for PMAY-G?"
    monkeypatch.setattr(router.translate, "to_english", to_english)
    req = router.QueryRequest(question="Kumno nga lah ban apply ia ka PMAY-G?", session_id="k17", language="kha")
    out = asyncio.run(router._answer(req, _request(), stubbed.scope))
    assert out["translated_from"] == "Kumno nga lah ban apply ia ka PMAY-G?"
    assert out["translated_question"] == "How do I apply for PMAY-G?"

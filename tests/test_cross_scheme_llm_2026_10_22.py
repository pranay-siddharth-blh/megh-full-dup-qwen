"""
Cross-scheme questions answered by the model, one query per scheme (D-062, 2026-10-22).

User report 2026-10-22: "I have a query. Breakdown into I want top ten highest
villages in Mgnrega and pmay" was answered with the statewide totals card, the
same card as "Compare MGNREGA and PMAY-G spending". The fixed table of
app/cross_scheme.py (D-044) could show only per-scheme totals, per district or per
block; "top ten" and "villages" were dropped. Now each scheme gets its own
question (the rewrite model's, checked), its own SQL (its prompt, guards,
verifier, repairs) and the composer writes one answer, guarded per scheme.

Every test calls the real function; model calls are stubbed, nothing needs the DB.
"""
import asyncio

import pytest

from app import cross_scheme as cs
from app import entity_resolver, llm
from app import pipeline as p

USER_Q ="I have a query. Breakdown into I want top ten highest villages in Mgnrega and pmay"


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()           # the district / block catalogue the place check reads


def _named(q):
    return [s for s, pat in p._SCHEME_NAME_MATCHER.items() if pat.search(q)]


def _cross_d(question, schemes, resolved=None, display=None):
    d = p._new_data_turn(question)
    d.update(schemes=list(schemes), cross={"schemes": list(schemes), "text": question},
             entity_result={"resolved": dict(resolved or {}), "display": dict(display or {})})
    return d


# ── the template is gone ─────────────────────────────────────────────────────

def test_the_users_question_is_a_cross_scheme_question():
    assert cs.detect(USER_Q, _named(USER_Q)) == ["MGNREGA", "PMAY-G"]


def test_no_fixed_table_answer_remains():
    for name in ("answer", "plan", "Plan", "_scheme_figures", "_where", "DISPLAY"):
        assert not hasattr(cs, name), name
    for name in ("_cross_scheme_answer", "_cross_scheme_money_answer", "_CROSS_SCHEME_MONEY_SQL",
                 "_literal_sql"):
        assert not hasattr(p, name), name


# ── scope: no pause, each scheme's own years ────────────────────────────────

def test_scope_adds_all_years_and_never_pauses():
    d = _cross_d(USER_Q, ["MGNREGA", "PMAY-G"])
    assert asyncio.run(p._cross_scheme_scope(d)) is None
    assert d["question"].endswith("across all financial years")
    assert d["entity_result"]["answer_defaults"] is True


def test_scope_reads_a_year_written_without_a_space(monkeypatch):
    # a beneficiaries comparison of two main schemes is worked out in code since
    # D-066; the year it is asked for is still the one written without a space
    seen = {}

    async def _fake_answer(plan):
        seen["plan"] = plan
        return {"answer": "x", "rows": [], "sql": ""}
    monkeypatch.setattr(p.cross_figures, "answer", _fake_answer)
    q = "Compare MGNREGA and PMAY-G beneficiaries in FY2022-23"
    d = _cross_d(q, ["MGNREGA", "PMAY-G"])
    out = asyncio.run(p._cross_scheme_scope(d))
    assert d["entity_result"]["resolved"]["year_key"] == 2022
    assert d["entity_result"]["display"]["year"] == "FY 2022-23"
    assert "across all financial years" not in d["question"]
    assert out["answer"] == "x" and seen["plan"].year == 2022 and seen["plan"].period_label == "FY 2022-23"


def test_scope_answers_outright_when_no_scheme_holds_what_is_asked():
    # PMAY-G records the constituency since 2026-10-30 (v_pmay.ac_name, KI-445): CM Elevate here
    d = _cross_d("Compare CM Elevate and Focus Plus in Mawhati constituency", ["CM Elevate", "Focus Plus"],
                 resolved={"assembly_constituency": "MAWHATI"})
    out = asyncio.run(p._cross_scheme_scope(d))
    assert out is not None and out["rows"] == []
    assert "CM Elevate does not record assembly constituency" in out["answer"]
    assert "Focus Plus does not record assembly constituency" in out["answer"]


# ── what a scheme's data cannot hold is said, never queried ─────────────────

def test_gaps_constituency():
    gaps = p._cross_scheme_gaps(["MGNREGA", "PMAY-G", "Focus Legacy", "CM Elevate Legacy", "Focus Plus",
                                 "CM Elevate",
                                 "CMSS",
                                 "Homestay"], {"assembly_constituency": "MAWHATI"})
    assert set(gaps) == {"Focus Plus", "CM Elevate"}      # PMAY-G records it since 2026-10-30 (KI-445)


def test_gaps_year_lists_the_years_held():
    gaps = p._cross_scheme_gaps(["Focus Plus", "CM Elevate Legacy", "Focus Legacy", "CM Elevate"],
                                {"year_key": 2023}, {"year": "FY 2023-24"})
    assert gaps["Focus Plus"] == "Focus Plus has no data for FY 2023-24 (its data covers FY 2022-23, 2025-26)"
    # Focus Legacy has no FY 2023-24 INSIDE its range: listed, not "2021-22 to 2025-26"
    assert "FY 2021-22, 2022-23, 2024-25, 2025-26" in gaps["Focus Legacy"]
    assert "records no financial year" in gaps["CM Elevate"]
    assert "CM Elevate Legacy" in gaps


def test_gaps_money_only_skips_cm_elevate():
    # 2026-11-14: every scheme that records no money (CM Elevate, and Homestay since it was onboarded), from the
    # per-scheme specs; this pinned {"CM Elevate"} and Homestay was asked for money it does not hold
    assert set(p._cross_scheme_gaps(cs.ORDER, {}, {}, "which scheme spent the most money?")) == set(p.cross_figures.NO_MONEY)
    assert {"CM Elevate", "Homestay"} <= set(p.cross_figures.NO_MONEY)
    assert p._cross_scheme_gaps(cs.ORDER, {}, {}, "which scheme has the most beneficiaries?") == {}


# ── the one-scheme question ─────────────────────────────────────────────────

def test_base_question_names_only_the_scheme():
    assert p._cross_scheme_base_question(USER_Q, "PMAY-G") == \
        "I have a query. Breakdown into I want top ten highest villages in PMAY-G"
    assert p._cross_scheme_base_question("Compare MGNREGA and PMAY-G spending in Meghalaya", "MGNREGA") == \
        "Compare MGNREGA spending in Meghalaya"
    assert p._cross_scheme_base_question("Compare Focus+, FOCUS and CM-ELEVATE in ekh", "Focus Legacy") == \
        "Compare Focus Legacy in ekh"
    # no scheme named: the suffixed form
    assert p._cross_scheme_base_question("which scheme has most beneficiaries", "MGNREGA").endswith(
        "answer for MGNREGA only?")


def test_subquestion_check():
    v = p._cross_subquestion_violation
    assert v(USER_Q, "Which are the top 10 highest villages in PMAY-G?", "PMAY-G") is None
    assert v(USER_Q, "Which are the top ten highest villages in MGNREGA and PMAY-G?", "PMAY-G") == "scheme"
    assert v("which scheme spent the most money", "Which scheme spent the most money?", "PMAY-G") == "scheme"
    assert v("Compare MGNREGA and PMAY-G in ekh for FY 2023-24", "PMAY-G figure in ekh?", "PMAY-G") == "year"
    assert v(USER_Q, "Which are the top 5 villages in PMAY-G?", "PMAY-G") == "number"
    assert v("Compare MGNREGA and PMAY-G in ekh", "What is the PMAY-G figure in wgh?", "PMAY-G") == "place"
    assert v(USER_Q, "SELECT * FROM curated.v_pmay", "PMAY-G") == "shape"


def test_subquestion_uses_the_model_when_it_passes(monkeypatch):
    async def fake(prompt, **kw):
        assert "Scheme: PMAY-G" in prompt
        return "Which are the top ten highest villages in PMAY-G?"
    monkeypatch.setattr(llm, "call_rewriter", fake)
    assert asyncio.run(p._cross_scheme_subquestion(USER_Q, "PMAY-G")) == \
        "Which are the top ten highest villages in PMAY-G?"


def test_subquestion_falls_back_when_the_model_names_another_scheme(monkeypatch):
    async def fake(prompt, **kw):
        return "Which scheme spent the most money?"
    monkeypatch.setattr(llm, "call_rewriter", fake)
    q = "Compare MGNREGA and PMAY-G spending in Meghalaya"
    assert asyncio.run(p._cross_scheme_subquestion(q, "MGNREGA")) == "Compare MGNREGA spending in Meghalaya"


# ── one model-written query per scheme ──────────────────────────────────────

def test_cross_skips_the_fixed_queries_and_generates_per_scheme(monkeypatch):
    seen = []

    async def sub(question, scheme):
        return f"Which are the top ten highest villages in {scheme}?"

    async def gen(question, schemes, entity_result):
        seen.append((question, schemes))
        return f"SELECT lgd_village_name FROM curated.v_x_{schemes[0][:2].lower()}"
    monkeypatch.setattr(p, "_cross_scheme_subquestion", sub)
    monkeypatch.setattr(p, "generate_sql", gen)
    d = _cross_d(USER_Q + " across all financial years", ["MGNREGA", "PMAY-G"])
    assert asyncio.run(p._data_deterministic_stage(d)) is None
    assert d["mg_det"] is None
    asyncio.run(p._data_sql_stage(d))
    assert seen == [("Which are the top ten highest villages in MGNREGA?", ["MGNREGA"]),
                    ("Which are the top ten highest villages in PMAY-G?", ["PMAY-G"])]
    assert [it[0] for it in d["per_scheme"]] == ["MGNREGA", "PMAY-G"]
    assert p._per_scheme_q(d, "PMAY-G") == "Which are the top ten highest villages in PMAY-G?"


def test_a_scheme_that_cannot_hold_it_is_not_queried(monkeypatch):
    seen = []

    async def gen(question, schemes, entity_result):
        seen.append(schemes[0])
        return "SELECT 1 FROM curated.v_employment"
    async def sub(question, scheme):
        return question
    monkeypatch.setattr(p, "generate_sql", gen)
    monkeypatch.setattr(p, "_cross_scheme_subquestion", sub)
    d = _cross_d("Compare MGNREGA and Focus Plus in Mawhati constituency", ["MGNREGA", "Focus Plus"],
                 resolved={"assembly_constituency": "MAWHATI"})
    asyncio.run(p._data_sql_stage(d))
    assert seen == ["MGNREGA"]
    pm = [it for it in d["per_scheme"] if it[0] == "Focus Plus"][0]
    assert pm[1] is None and pm[2].startswith(p._NOT_HELD)


# ── the composed answer, guarded per scheme ─────────────────────────────────

_MG = [{"lgd_village_name": f"MG{i}", "village_code": 270000 + i, "person_days": 1000 - i, "scheme": "MGNREGA"}
       for i in range(10)]
_PM = [{"lgd_village_name": f"PM{i}", "total_sanctioned": 5_000_000.0 + i * 100_000, "scheme": "PMAY-G"}
       for i in range(10)]


def test_notes_ask_for_what_the_question_asks_and_leave_gaps_out():
    d = _cross_d(USER_Q, ["MGNREGA", "PMAY-G", "Focus Plus"])
    d["per_scheme"] = [["MGNREGA", "SELECT 1", None], ["PMAY-G", "SELECT 1", None],
                       ["Focus Plus", None, p._NOT_HELD + "Focus Plus has no data for FY 2023-24"]]
    notes = " ".join(p._per_scheme_notes(d))
    assert "top N" in notes and "every row of each scheme" in notes
    assert "Focus Plus has no data" not in notes          # added after the composer instead


def test_a_scheme_left_out_is_found():
    rows = _MG[:5] + _PM[:5]
    assert p._cross_schemes_left_out("MGNREGA has no beneficiary figures. PMAY-G: 5,000,000 for PM0.", rows) \
        == ["MGNREGA"]
    assert p._cross_schemes_left_out("MGNREGA 1,000 in MG0; PMAY-G 5000000 in PM0.", rows) == []


def test_sections_one_per_scheme():
    out = p._cross_scheme_sections(_MG[:2] + _PM[:2], {})
    assert out.startswith("**MGNREGA:**") and "**PMAY-G:**" in out
    assert "PMAY-G, PMAY-G" not in out


def test_list_size_per_scheme_is_not_a_wrong_count(monkeypatch):
    async def fake(prompt):
        return ("The top 10 MGNREGA villages by person days start with MG0 at 1,000. "
                "The top 10 PMAY-G villages by sanctioned amount start with PM0 at 5,000,000.00.")
    monkeypatch.setattr(llm, "call_response_composer", fake)
    out = asyncio.run(p.compose_response(USER_Q, "SELECT 1", _MG + _PM, schemes=["MGNREGA", "PMAY-G"]))
    assert out.startswith("The top 10 MGNREGA villages")


def test_complete_lists_are_added_when_the_answer_names_part():
    ans = "MGNREGA: MG0 leads with 1,000 person days. PMAY-G: PM0 leads."
    out = p._cross_scheme_complete_lists(ans, _MG + _PM)
    assert "**MGNREGA:**\n1. MG0" in out and "10. MG9" in out
    assert "**PMAY-G:**\n1. PM0" in out
    named_all = " ".join(f"MG{i} PM{i}" for i in range(10))
    assert p._cross_scheme_complete_lists(named_all, _MG + _PM) == named_all


def test_rupees_are_formatted_per_scheme():
    per = [["MGNREGA", "SELECT SUM(person_days) FROM curated.v_employment", None],
           ["PMAY-G", "SELECT SUM(sanctioned_amount) FROM curated.v_pmay", None]]
    out = p._cross_scheme_answer_units("PMAY-G sanctioned 5,000,000.00 for PM0.", per, _MG[:1] + _PM[:1])
    assert "₹50,00,000" in out and "5,000,000.00" not in out


def test_money_is_crore_for_every_scheme_before_the_composer():
    # sheet run 2026-10-22: Focus Plus 1,197,392,500 RUPEES was ranked over MGNREGA 3,628.67 CRORE
    per = [["MGNREGA", "SELECT SUM(total_exp) AS total_exp FROM curated.v_expenditure", None],
           ["Focus Plus", "SELECT SUM(amount_disbursed) AS total_financial_assistance FROM curated.v_focus_plus", None],
           ["PMAY-G", "SELECT AVG(sanctioned_amount) AS avg_sanctioned_amount FROM curated.v_pmay", None]]
    rows = [{"total_exp": 362867.0, "scheme": "MGNREGA"},
            {"total_financial_assistance": 1197392500.0, "scheme": "Focus Plus"},
            {"avg_sanctioned_amount": 130000.0, "scheme": "PMAY-G"}]
    out = p._cross_scheme_rows_in_crore(per, rows)
    assert out[0] == {"total_exp_crore": 3628.67, "scheme": "MGNREGA"}
    assert out[1] == {"total_financial_assistance_crore": 119.74, "scheme": "Focus Plus"}
    assert out[2] == rows[2]                     # a per-unit figure stays in rupees
    assert p._cross_money_outputs(
        "CM Elevate Legacy", "SELECT ROUND(SUM(sanctioned_amount) / 1e7, 2) AS sanctioned_cr, "
        "SUM(sanctioned_amount) - SUM(total_disbursement) AS pending_cr, COUNT(*) AS records "
        "FROM curated.v_cm_elevate_disbursement") == {"pending_cr": "rupees"}      # KI-375's mislabelled column
    # MGNREGA SQL already in crore is not divided again
    per_cr = [["MGNREGA", "SELECT ROUND(SUM(total_exp) / 100, 2) AS total_expenditure_crore "
                          "FROM curated.v_expenditure", None]]
    assert p._cross_scheme_rows_in_crore(per_cr, [{"total_expenditure_crore": 3628.67, "scheme": "MGNREGA"}]) \
        == [{"total_expenditure_crore": 3628.67, "scheme": "MGNREGA"}]


def test_an_all_null_row_is_no_records():
    rows = [{"household_years": None, "person_years": None, "scheme": "MGNREGA"},
            {"beneficiary_count": 3, "scheme": "PMAY-G"}]
    out = p._cross_scheme_rows_in_crore([], rows)
    assert out == rows[1:]
    per = [["MGNREGA", "SELECT 1", None], ["PMAY-G", "SELECT 1", None]]
    assert "MGNREGA has no records matching this question." in p._cross_scheme_no_figure_lines("x", per, out)


def test_the_added_all_years_text_is_not_a_money_question(monkeypatch):
    # Baghmara run 2026-10-22: "across all financial years" made CM Elevate "no money".
    # Since D-097 (2026-10-30) the comparison is answered on the coded path, with CM
    # Elevate in it and no gap.
    q = "Compare MGNREGA, PMAY-G and CM-ELEVATE"
    d = _cross_d(q, ["MGNREGA", "PMAY-G", "CM Elevate"])
    seen = {}

    async def fake_answer(plan):
        seen["plan"] = plan
        return {"answer": "ok", "rows": [], "sql": "S", "totals": None, "measure_notes": {}, "schemes_with_data": []}
    monkeypatch.setattr(p.cross_figures, "answer", fake_answer)
    out = asyncio.run(p._cross_scheme_scope(d))
    assert out["answer"] == "ok" and seen["plan"].schemes == ["MGNREGA", "PMAY-G", "CM Elevate"]
    assert seen["plan"].gaps == {}
    assert p._cross_scheme_gaps(d["schemes"], {}, {}, d["cross"]["text"]) == {}


def test_a_wrong_leader_is_corrected_from_the_rows():
    # sheet run 2026-10-22: Focus Plus (119.74 crore) named highest over MGNREGA (3,628.67 crore)
    q = "Which scheme provided the highest total financial assistance across Meghalaya?"
    rows = [{"total_exp_crore": 3628.67, "scheme": "MGNREGA"},
            {"total_financial_assistance_crore": 119.74, "scheme": "Focus Plus"},
            {"sanctioned_cr": 22.81, "total_disbursed_cr": 82.9, "scheme": "CM Elevate Legacy"}]
    wrong = "Focus Plus provided the highest total financial assistance of ₹119.74 crore. MGNREGA had ₹3,628.67 crore."
    out = p._cross_scheme_leader(wrong, rows, q)
    assert out.startswith("MGNREGA is the highest, at ₹3,628.67 crore.")
    assert "In order: MGNREGA ₹3,628.67 crore; Focus Plus ₹119.74 crore; CM Elevate Legacy ₹82.90 crore." in out
    right = "MGNREGA is highest at ₹3,628.67 crore. Focus Plus ₹119.74 crore."
    assert p._cross_scheme_leader(right, rows, q) == right
    assert p._cross_scheme_leader(wrong, rows, q.replace("highest", "lowest")).startswith(
        "CM Elevate Legacy is the lowest")
    # a list per scheme is not ranked across schemes
    assert p._cross_scheme_leader(wrong, _MG + _PM, USER_Q) == wrong


def test_an_empty_aggregate_row_is_no_records():
    rows = [{"household_years": None, "financial_years": 0, "scheme": "MGNREGA"},
            {"beneficiary_count": 3, "scheme": "PMAY-G"}]
    assert p._cross_scheme_rows_in_crore([], rows) == rows[1:]


def test_no_figure_lines_are_added_in_code():
    per = [["MGNREGA", "SELECT 1", None], ["PMAY-G", None, "query failed: x"],
           ["Focus Plus", None, p._NOT_HELD + "Focus Plus has no data for FY 2023-24 (its data covers FY "
                                              "2022-23, 2025-26)"],
           ["Focus Legacy", "SELECT 1", None]]
    out = p._cross_scheme_no_figure_lines("MGNREGA: 1,000.", per, _MG[:1])
    assert "No PMAY-G figure could be worked out" in out
    assert "Focus Plus has no data for FY 2023-24 (its data covers FY 2022-23, 2025-26)." in out
    assert "Focus Legacy has no records matching this question." in out

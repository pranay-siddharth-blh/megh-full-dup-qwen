"""Chat UI audit 2026-10-29, section A (and H-2, I-9): one shape for scheme x year
rows. The per-scheme answers below are the row shapes the real per-scheme SQL
returns (year_key vs financial_year_short, a code column before the figure, money
in lakh vs rupees); they go through the real answer_many / per_year_parts /
_c13_unify_scheme_rows / cross_figures by-year mode."""
import asyncio
import time

from app import conversation_layer as cl
from app import cross_figures as cf
from app import cross_scheme
from app import pipeline as p
from app.session_store import Session

M = p._SCHEME_NAME_MATCHER


def _session():
    return Session(session_id="audit-a", user_id="u", created=time.time(), last_seen=time.time())


def _parts(q):
    return cl.per_year_parts(_session(), q)


# ── per_year_parts: the measure each scheme is asked ─────────────────────────
def test_money_words_ask_each_schemes_own_money():                                     # A-9
    # A-16 (later the same day): the four coded schemes' money / villages each year
    # are answered by cross_figures' per-year mode, one fixed query per scheme, with
    # what each scheme's money is (measure_notes); the per-year split steps aside
    for q in ("Compare MGNREGA and PMAY-G amount released each year",
              "Focus Plus and Focus Legacy amount disbursed each year",
              "MGNREGA and PMAY-G villages covered each year"):
        assert _parts(q) is None
        named = [s for s in ("MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy") if s in q]
        assert cf.plan(q, named, {}, {}, M).op == "by_year"
    # a scheme outside the coded four keeps the split, with its own money words
    assert _parts("Compare MGNREGA and CM Elevate Legacy amount each year")["questions"][0] ==         "What was the total MGNREGA expenditure in each financial year?"


def test_no_measure_asks_which_figure():                                               # A-9
    parts = _parts("Compare MGNREGA and PMAY-G year wise")
    assert parts["questions"] is None
    ask = parts["ask"]
    assert ask["route"] == "clarification" and ask["clarification"]["rule"] == "per-year-measure"
    assert [o["label"] for o in ask["clarification"]["options"]] == ["Beneficiaries", "Money spent", "Villages covered"]
    # a chip's question is itself a per-year question with a measure
    assert _parts(ask["clarification"]["options"][0]["question"])["questions"][0].startswith("How many MGNREGA beneficiaries")


def test_each_measure_goes_to_the_scheme_that_holds_it():                              # A-11
    parts = _parts("Compare MGNREGA and PMAY-G person days and houses each year")
    assert parts["questions"] == ["How many MGNREGA person-days were there in each financial year?",
                                  "How many PMAY-G houses sanctioned were there in each financial year?"]
    parts = _parts("Compare MGNREGA and PMAY-G person days each year")
    assert parts["questions"] == ["How many MGNREGA person-days were there in each financial year?"]
    assert parts["notes"] == ["PMAY-G records no person-days"]


def test_annually_and_yearly_are_per_year_words():                                    # A-15
    # read as per-year on both paths; for the coded four it is cross_figures' per-year mode (A-16)
    for q in ("MGNREGA and PMAY-G beneficiaries annually", "MGNREGA and PMAY-G beneficiaries yearly trend"):
        assert _parts(q) is None
        assert cf.plan(q, ["MGNREGA", "PMAY-G"], {}, {}, M).op == "by_year"


# ── answer_many: one row shape ───────────────────────────────────────────────
def _fake(answers):
    async def ask(q):
        for scheme, r in answers.items():
            if scheme in q:
                if isinstance(r, Exception):
                    raise r
                return r
        raise RuntimeError("no fake")
    return ask


def test_money_rows_are_one_unit_and_one_year_form():                                  # A-2, A-10, A-12
    ask = _fake({
        # MGNREGA: a block code before the figure, year_key, money in lakh
        "MGNREGA": {"answer": "…", "schemes": ["MGNREGA"], "data": [
            {"block_lgd_code": 1234, "year_key": 2022, "total_exp_lakh": 105000.0},
            {"block_lgd_code": 1234, "year_key": 2023, "total_exp_lakh": 99000.0}]},
        # PMAY-G: houses before the amount, "2022-2023", money in rupees
        "PMAY-G": {"answer": "…", "schemes": ["PMAY-G"], "data": [
            {"financial_year": "2022-2023", "houses": 10, "amount_released": 1200000000}]},
    })
    out = asyncio.run(cl.answer_many(["What was the total MGNREGA expenditure in each financial year?",
                                      "What was the total PMAY-G amount released in each financial year?"], ask))
    assert out["data"] == [
        {"scheme": "MGNREGA", "financial_year": "2022-23", "money_crore": 1050.0},
        {"scheme": "MGNREGA", "financial_year": "2023-24", "money_crore": 990.0},
        {"scheme": "PMAY-G", "financial_year": "2022-23", "money_crore": 120.0}]


def test_different_measures_share_one_value_column():                                 # A-11, I-9
    ask = _fake({
        "MGNREGA": {"answer": "…", "schemes": ["MGNREGA"], "data": [{"year_key": 2023, "person_days": 500}]},
        "PMAY-G": {"answer": "…", "schemes": ["PMAY-G"],
                   "data": [{"financial_year_short": "2023-24", "houses_sanctioned": 70}]},
    })
    out = asyncio.run(cl.answer_many(["How many MGNREGA person-days were there in each financial year?",
                                      "How many PMAY-G houses sanctioned were there in each financial year?"], ask))
    assert out["data"] == [
        {"scheme": "MGNREGA", "financial_year": "2023-24", "measure": "person days", "value": 500},
        {"scheme": "PMAY-G", "financial_year": "2023-24", "measure": "houses sanctioned", "value": 70}]


def test_place_columns_are_kept_for_a_scoped_per_year_question():                    # I-2
    ask = _fake({
        "MGNREGA": {"answer": "…", "schemes": ["MGNREGA"],
                    "data": [{"lgd_district": "RI BHOI", "year_key": 2023, "households_employed": 50}]},
        "PMAY-G": {"answer": "…", "schemes": ["PMAY-G"],
                   "data": [{"district_name": "RI BHOI", "financial_year_short": "2023-24", "beneficiaries": 7}]},
    })
    out = asyncio.run(cl.answer_many(["top 5 districts in MGNREGA year wise", "top 5 districts in PMAY-G year wise"],
                                     ask))
    assert all(r["district"] == "RI BHOI" and r["financial_year"] == "2023-24" for r in out["data"])


def test_rows_with_no_year_leave_the_chart_and_failure_is_marked():                   # H-2, A-17
    ask = _fake({"CM Elevate Legacy": {"answer": "…", "schemes": ["CM Elevate Legacy"],
                                       "data": [{"beneficiaries": 395}, {"year_key": 2024, "beneficiaries": 900}]},
                 "MGNREGA": RuntimeError("down")})
    out = asyncio.run(cl.answer_many(["How many CM Elevate Legacy beneficiaries were there in each financial year?",
                                      "How many MGNREGA beneficiaries were there in each financial year?"], ask))
    assert out["data"] == [{"scheme": "CM Elevate Legacy", "financial_year": "2024-25", "beneficiaries": 900}]
    assert "figures with no financial year" in out["answer"]
    assert "CM Elevate's applications carry no financial year" in out["answer"]
    assert not out.get("answer_failed")
    out = asyncio.run(cl.answer_many(["How many MGNREGA beneficiaries were there in each financial year?"],
                                     _fake({"MGNREGA": RuntimeError("down")})))
    assert out["answer_failed"] is True and out["confidence"] == "low"


def test_scheme_notes_reach_the_answer():
    async def ask(q):
        return {"answer": "x", "schemes": ["MGNREGA"], "data": [{"year_key": 2023, "person_days": 5}]}
    out = asyncio.run(cl.answer_many(["How many MGNREGA person-days were there in each financial year?"], ask,
                                     notes=["PMAY-G records no person-days"]))
    assert "PMAY-G records no person-days." in out["answer"]


# ── the per-scheme model path: rows unified before the UI ─────────────────────
def test_merged_per_scheme_rows_get_one_shape():                                      # A-1, I-9
    rows = [{"year_key": 2023, "lgd_village_name": "A", "village_code": 11, "households_employed": 5, "scheme": "MGNREGA"},
            {"financial_year_short": "2023-24", "village_name": "B", "village_code": 12, "houses_sanctioned": 7,
             "scheme": "PMAY-G"}]
    assert p._c13_unify_scheme_rows(rows) == [
        {"financial_year": "2023-24", "village": "A", "village_code": 11, "measure": "households employed", "value": 5,
         "scheme": "MGNREGA"},
        {"financial_year": "2023-24", "village": "B", "village_code": 12, "measure": "houses sanctioned", "value": 7,
         "scheme": "PMAY-G"}]
    one = [{"year_key": 2023, "person_days": 5}]
    assert p._c13_unify_scheme_rows(one) is one                                          # one scheme: untouched


def test_the_chart_hint_step_unifies_the_rows():
    result = {"route": "data", "data": [{"year_key": 2022, "v": 1, "scheme": "MGNREGA"},
                                        {"financial_year_short": "2022-23", "v": 2, "scheme": "PMAY-G"}]}
    p._attach_chart_hint(result, "Compare MGNREGA and PMAY-G each year", "Compare MGNREGA and PMAY-G each year")
    assert [r["financial_year"] for r in result["data"]] == ["2022-23", "2022-23"]


# ── cross_figures by-year mode (A-16, A-18) ───────────────────────────────────
_HELD = {"MGNREGA": (2022, 2023, 2024, 2025), "PMAY-G": (2017, 2018, 2019, 2020, 2021, 2022, 2023)}


def _year_db(monkeypatch):
    async def fetch_rows(sql, params):
        s = "PMAY-G" if "v_pmay" in sql else "MGNREGA"
        if "DISTINCT year_key AS y" in sql:
            return [{"y": y} for y in _HELD[s]]
        assert "year_key AS k" in sql and "GROUP BY 1" in sql
        base = {"villages": 7, "districts": 1, "blocks": 1, "completed": 1, "sanctioned": 1.0, "money": 10.5}
        return [{"k": y, "ben": 1000 + y, **base} for y in params[-1] if y in _HELD[s]]
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)


def test_a_stated_span_is_one_fixed_query_per_scheme_by_year(monkeypatch):
    _year_db(monkeypatch)
    pl = cf.plan("Compare MGNREGA and PMAY-G beneficiaries from 2022-23 to 2024-25", ["MGNREGA", "PMAY-G"],
                 {"year_key_list": [2022, 2023, 2024]}, {}, M)
    assert pl.op == "by_year" and pl.period_label == "FY 2022-23 to FY 2024-25 (3 years)"
    out = asyncio.run(cf.answer(pl))
    assert out["answer"].startswith("**All of Meghalaya, FY 2022-23 to FY 2024-25 (3 years)**")
    assert "PMAY-G has no data for FY 2024-25" in out["answer"]
    assert out["rows"] == [
        {"scheme": "MGNREGA", "financial_year": "2022-23", "beneficiaries": 3022},
        {"scheme": "MGNREGA", "financial_year": "2023-24", "beneficiaries": 3023},
        {"scheme": "MGNREGA", "financial_year": "2024-25", "beneficiaries": 3024},
        {"scheme": "PMAY-G", "financial_year": "2022-23", "beneficiaries": 3022},
        {"scheme": "PMAY-G", "financial_year": "2023-24", "beneficiaries": 3023}]


def test_two_named_years_are_both_read():                                             # A-14
    assert cross_scheme.years_in_text("Compare MGNREGA and PMAY-G beneficiaries 2023-24 vs 2024-25") == [2023, 2024]
    pl = cf.plan("Compare MGNREGA and PMAY-G beneficiaries 2023-24 vs 2024-25", ["MGNREGA", "PMAY-G"],
                 {"year_key_list": [2023, 2024]}, {}, M)
    assert pl.op == "by_year" and pl.years == [2023, 2024]


def test_feedback_upsert_keeps_the_votes_own_question_and_answer(monkeypatch):     # K-4
    from types import SimpleNamespace

    from app.routers import feedback
    seen = []

    async def execute(sql, params):
        seen.append(sql)
    monkeypatch.setattr(feedback.db, "execute", execute)
    body = feedback.FeedbackBody(message_key="s:a1", rating=1, question="Q3", answer="A3")
    scope = SimpleNamespace(tenant_id=1, db_user_id=7, username="u")
    asyncio.run(feedback.give_feedback(body, scope))
    assert "question = EXCLUDED.question, answer = EXCLUDED.answer" in seen[0]


def test_per_year_answer_gets_the_banner_and_chips(monkeypatch):                     # H-3
    async def ask(q):
        return {"answer": "x", "schemes": ["MGNREGA"], "data": [{"year_key": 2023, "person_days": 5},
                                                              {"year_key": 2024, "person_days": 6}]}
    out = asyncio.run(cl.answer_many(["How many MGNREGA person-days were there in each financial year?"], ask))
    assert out["scope_banner"] == "MGNREGA · each financial year"


def test_village_lookup_is_one_sentence_and_the_table(monkeypatch):                   # H-1
    async def fetch_rows(sql, params):
        return [{"village_code": 1, "lgd_village_name": "MAWKYNREW", "lgd_block": "MAWKYNREW",
                 "lgd_district": "EAST KHASI HILLS", "ac_name": "MAWKYNREW"}]
    monkeypatch.setattr(p, "fetch_rows", fetch_rows)
    out = asyncio.run(p._geo_lookup_answer("Which block is Mawkynrew village in?"))
    assert out["answer"] == ("**Mawkynrew** is in Mawkynrew block, East Khasi Hills district (Mawkynrew "
                             "constituency), LGD village code 1.")
    assert "|" not in out["answer"] and len(out["data"]) == 1


def test_a_reopened_turn_keeps_its_sources_chips_timing_and_chart(monkeypatch):      # K-3, C-7
    import json

    from app import conversation_store, db
    calls = []

    async def fetchval(sql, params):
        return 1

    async def execute(sql, params):
        calls.append((sql, params))
    monkeypatch.setattr(db, "fetchval", fetchval)
    monkeypatch.setattr(db, "execute", execute)
    result = {"route": "knowledge", "intent": "KNOWLEDGE", "answer": "PMAY-G is …",
              "citations": [{"title": "PMAY-G guidelines", "section": "2.1"}], "suggestions": ["Who is eligible?"],
              "continue_offer": {"label": "Earlier"}, "execution_time_ms": 2345, "translated_from": "ka …",
              "chart_type": "stacked", "chart_wide": True}
    asyncio.run(conversation_store._persist_turn("t1", 1, "s1", result, "what is PMAY-G", 10.0, "u", "127.0.0.1"))
    payload = json.loads(next(c for c in calls if "conversation_turns" in c[0])[1][-1])
    for k in ("citations", "suggestions", "continue_offer", "execution_time_ms", "translated_from",
              "chart_type", "chart_wide"):
        assert payload[k] == result[k], k


def test_chats_with_no_turns_are_not_listed(monkeypatch):                             # K-7
    from app import conversation_store, db
    seen = []

    async def fetch_rows(sql, params):
        seen.append(sql)
        return []
    monkeypatch.setattr(db, "fetch_rows", fetch_rows)
    asyncio.run(conversation_store.list_my_conversations(1))
    asyncio.run(conversation_store.search_my_conversations(user_id=1, q="mgnrega"))
    assert all("turn_count > 0" in s for s in seen)


def test_year_wise_with_no_years_is_every_year_each_scheme_holds(monkeypatch):      # A-16
    async def fetch_rows(sql, params):
        s = "PMAY-G" if "v_pmay" in sql else "MGNREGA"
        if "DISTINCT year_key AS y" in sql:
            return [{"y": y} for y in _HELD[s]]
        assert "year_key AS k" in sql and "GROUP BY 1" in sql
        base = {"villages": 7, "districts": 1, "blocks": 1, "completed": 1, "sanctioned": 1.0, "money": 10.5}
        return [{"k": y, "ben": 1000 + y, **base} for y in _HELD[s]]
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)
    pl = cf.plan("Compare MGNREGA and PMAY-G beneficiaries year wise", ["MGNREGA", "PMAY-G"], {}, {}, M)
    assert pl.op == "by_year" and pl.years == []
    out = asyncio.run(cf.answer(pl))
    years = {(r["scheme"], r["financial_year"]) for r in out["rows"]}
    assert ("MGNREGA", "2025-26") in years and ("PMAY-G", "2017-18") in years
    assert ("PMAY-G", "2025-26") not in years                     # a year not held is a gap

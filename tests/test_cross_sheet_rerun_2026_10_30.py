"""Cross Scheme Test Cases sheet re-run, 2026-10-30 (D-097, KI-644, KI-645).

On the code before the fixes 2 of the 20 sheet questions passed: every combination
with a CM Elevate dataset, every village and every constituency question went to the
model path (one 30B query per scheme), where three questions timed out and the
others dropped MGNREGA, gave PMAY-G's sanctioned amount, added village counts
across schemes or said "24 districts". Now `app/cross_figures.py` answers all six
schemes, a village, a constituency and a block grain from fixed queries, and the
scope stage hands it what a scheme cannot hold. Every test calls the real function
with a fake megh_db where one is needed."""
import asyncio

import pytest

from app import cross_figures as cf
from app import pipeline as p

M = p._SCHEME_NAME_MATCHER
SIX = list(cf.SUPPORTED)

# (beneficiaries, money in crore, villages) per district, per scheme
_DIST = {
    "MGNREGA": {"WEST GARO HILLS": (261666, 792.42, 978), "RI BHOI": (112602, 183.16, 600)},
    "PMAY-G": {"WEST GARO HILLS": (33147, 425.01, 650), "RI BHOI": (17565, 222.85, 483)},
    "Focus Plus": {"WEST GARO HILLS": (35059, 39.16, 872), "RI BHOI": (419, 0.5238, 30)},
    "Focus Legacy": {"WEST GARO HILLS": (21867, 10.93, 500), "RI BHOI": (9858, 4.93, 300)},
    "CM Elevate": {"WEST GARO HILLS": (1200, 0.0, 400), "RI BHOI": (2624, 0.0, 350)},
    "CM Elevate Legacy": {"WEST GARO HILLS": (700, 20.5, 200), "RI BHOI": (300, 9.1, 100)},
    # CMSS (2026-11-11): students paid, Rs crore at a flat Rs 6,000, villages; Ri Bhoi paid = 8,701 (v_cmss)
    "CMSS": {"WEST GARO HILLS": (8000, 4.8, 300), "RI BHOI": (8701, 5.2206, 250)},
}
_VIEW = {"v_employment": "MGNREGA", "v_expenditure": "MGNREGA", "v_pmay": "PMAY-G", "v_focus_plus": "Focus Plus",
         "v_focus_legacy": "Focus Legacy", "v_cm_elevate_disbursement": "CM Elevate Legacy", "v_cm_elevate ": "CM Elevate",
         "v_cmss": "CMSS"}


@pytest.fixture
def fake_db(monkeypatch):
    seen = []

    async def fetch_rows(sql, params):
        seen.append((sql, params))
        s = next(v for k, v in _VIEW.items() if k in sql)
        if "DISTINCT year_key AS y" in sql:
            return [{"y": y} for y in ((2017, 2023) if s == "PMAY-G" else (2022, 2025))]
        keys = list(_DIST[s]) if "GROUP BY" in sql else [None]
        out = []
        for k in keys:
            vals = [_DIST[s][x] for x in (_DIST[s] if k is None else [k])]
            ben, money, vill = (sum(v[i] for v in vals) for i in range(3))
            out.append({"k": k, "ben": ben, "money": money, "villages": vill, "districts": 2, "blocks": 5,
                        "completed": ben // 2, "sanctioned": money * 1.02, "pgs": ben // 8, "payments": ben * 4,
                        "records": ben + 3})
        return out
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)
    return seen


def _plan(q, schemes=SIX, resolved=None, display=None):
    return cf.plan(q, schemes, resolved or {}, display or {}, M)


def _answer(q, schemes=SIX, resolved=None, display=None, gaps=None):
    pl = _plan(q, schemes, resolved, display)
    assert pl is not None, q
    if gaps:
        pl.gaps = gaps
    return asyncio.run(cf.answer(pl))


# ── all six schemes on the coded path ────────────────────────────────────────

def test_every_sheet_shape_with_cm_elevate_is_planned():
    for q, schemes in [
        ("Compare the performance of Focus+ and CM-ELEVATE across districts based on beneficiary/application counts.",
         ["Focus Plus", "CM Elevate"]),
        ("How much total amount has been disbursed under Focus+, FOCUS, and CM-ELEVATE?",
         ["Focus Plus", "Focus Legacy", "CM Elevate Legacy"]),
        ("Which scheme has the highest beneficiary or application count in each district?", SIX),
        ("Compare the coverage of MGNREGA, PMAY-G, and CM-ELEVATE in Mylliem block.", ["MGNREGA", "PMAY-G", "CM Elevate"]),
        ("Which districts have the highest concentration of beneficiaries or applications across the schemes?", SIX),
        ("Compare the beneficiary/application count and total financial amount for Focus+, FOCUS, and CM-ELEVATE.",
         ["Focus Plus", "Focus Legacy", "CM Elevate Legacy"]),
    ]:
        pl = _plan(q, schemes, {"block": "MYLLIEM"} if "Mylliem" in q else None)
        assert pl is not None and pl.schemes == schemes and pl.left_out == [], q


def test_cm_elevate_figures_say_no_money_and_no_year(fake_db):
    out = _answer("Compare MGNREGA, PMAY-G and CM-ELEVATE performance.", ["MGNREGA", "PMAY-G", "CM Elevate"])
    assert "- **CM Elevate:** 3,824 applications, no money recorded" in out["answer"]
    cme = next(r for r in out["rows"] if r["scheme"] == "CM Elevate")
    assert cme["beneficiaries"] == 3824 and cme["amount_crore"] is None
    assert not any("year_key" in sql for sql, _p in fake_db if "v_cm_elevate " in sql)
    out = _answer("How many beneficiaries are there under MGNREGA and CM Elevate applicants in FY 2022-23?",
                  ["MGNREGA", "CM Elevate"], {"year_key": 2022})
    assert "CM Elevate records no financial year, so it has no figure for FY 2022-23" in out["answer"]
    assert [r["scheme"] for r in out["rows"]] == ["MGNREGA"]


def test_cm_elevate_legacy_counts_sanctioned_applicants(fake_db):
    out = _answer("Compare the beneficiary count and total amount for Focus+ and CM Elevate Legacy.",
                  ["Focus Plus", "CM Elevate Legacy"])
    assert "- **CM Elevate Legacy:** 1,000 applicants sanctioned, ₹29.60 crore disbursed (subsidy and loan)" \
        in out["answer"]
    sql = next(s for s, _p in fake_db if "v_cm_elevate_disbursement" in s)
    assert "COUNT(*) FILTER (WHERE sanctioned_amount > 0)" in sql and "SUM(total_disbursement) / 1e7" in sql


def test_a_money_ranking_leaves_cm_elevate_out_with_its_reason(fake_db):
    out = _answer("Which scheme has a higher total financial disbursement: MGNREGA, PMAY-G or CM-ELEVATE?",
                  ["MGNREGA", "PMAY-G", "CM Elevate"])
    assert "**MGNREGA** has the most money" in out["answer"]
    assert "CM Elevate records applications only, no money" in out["answer"]


def test_the_leader_per_district_counts_applications_as_cm_elevates_count(fake_db):
    out = _answer("Which scheme has the highest beneficiary or application count in each district?")
    assert "**MGNREGA** is highest in all 2 districts." in out["answer"]
    assert "- Ri Bhoi: **MGNREGA** (1,12,602); next PMAY-G (17,565)" in out["answer"]
    assert {r["scheme"] for r in out["rows"]} == set(SIX)


def test_top_districts_rank_each_scheme_in_its_own_list(fake_db):
    out = _answer("Which districts have the highest concentration of beneficiaries or applications across the schemes?")
    assert "**CM Elevate** — Top 2 districts by applications: 1. Ri Bhoi 2,624; 2. West Garo Hills 1,200." \
        in out["answer"]
    assert "**MGNREGA** — Top 2 districts by households given work: 1. West Garo Hills 2,61,666" in out["answer"]
    ranks = [(r["scheme"], r["rank"], r["district"]) for r in out["rows"]]
    assert ("CM Elevate", 1, "Ri Bhoi") in ranks and ("MGNREGA", 1, "West Garo Hills") in ranks


# ── a village, a constituency, a block grain ─────────────────────────────────

def test_a_village_is_answered_from_fixed_queries(fake_db):
    out = _answer("How many beneficiaries are there under MGNREGA and CM Elevate applicants in Pamila village?",
                  ["MGNREGA", "CM Elevate"], {"village_code": 274001}, {"village": "Pamila", "block": "UMSNING"})
    assert out["answer"].startswith("**Pamila village (Umsning block), all financial years**")
    sqls = [s for s, _p in fake_db if "village_code = $" in s]
    # MGNREGA employment + expenditure, CM Elevate applications
    assert len(sqls) == 3 and all("entity_type <> 'Unresolved'" in s for s in sqls if "v_cm_elevate" in s)
    assert any(pr == [274001] for _s, pr in fake_db)


def test_a_constituency_reads_each_schemes_own_column(fake_db):
    out = _answer("Compare MGNREGA, PMAY-G and Focus Legacy performance in Mawhati constituency",
                  ["MGNREGA", "PMAY-G", "Focus Legacy"], {"assembly_constituency": "MAWHATI"},
                  {"assembly_constituency": "MAWHATI"})
    assert out["answer"].startswith("**Mawhati constituency, all financial years**")
    by_view = {next(v for v in _VIEW if v in s): s for s, _p in fake_db if "= $1" in s and "MAWHATI" in str(_p)}
    assert "UPPER(assembly_constituency_name) = $1" in by_view["v_employment"]
    assert "UPPER(ac_name) = $1" in by_view["v_expenditure"]
    assert "UPPER(ac_name) = $1" in by_view["v_pmay"] and "UPPER(ac_name) = $1" in by_view["v_focus_legacy"]


def test_a_scheme_with_no_constituency_is_said_not_queried(fake_db):
    out = _answer("Compare MGNREGA and Focus Plus beneficiaries in Mawhati constituency", ["MGNREGA", "Focus Plus"],
                  {"assembly_constituency": "MAWHATI"}, {"assembly_constituency": "MAWHATI"},
                  gaps={"Focus Plus": "Focus Plus does not record assembly constituency, so it has no figure for Mawhati"})
    assert "Focus Plus does not record assembly constituency" in out["answer"]
    assert not any("v_focus_plus" in s for s, _p in fake_db)
    assert [r["scheme"] for r in out["rows"]] == ["MGNREGA"]


def test_block_wise_in_a_district_is_one_row_per_block(fake_db):
    pl = _plan("Compare MGNREGA and PMAY-G block-wise in Ri Bhoi.", ["MGNREGA", "PMAY-G"], {"district": "RI BHOI"})
    assert pl.by_district and pl.grain == "block" and pl.districts == ["RI BHOI"]
    out = asyncio.run(cf.answer(pl))
    assert all("block" in r for r in out["rows"]) and "district" not in out["rows"][0]
    assert any("GROUP BY" in s and "UPPER(lgd_block) AS k" in s for s, _p in fake_db)
    assert "**Total for Ri Bhoi district:**" in out["answer"]
    # one line per block (the fake groups by the same two keys): the block rows were
    # filtered against the DISTRICT list and the table came out empty (BW-00..11,
    # sheet re-run 2026-10-30)
    assert "- West Garo Hills: MGNREGA 2,61,666 / ₹792.42 crore | PMAY-G 33,147 / ₹425.01 crore → MGNREGA" \
        in out["answer"]
    assert len(out["rows"]) == 4 and "MGNREGA leads in 2 blocks, PMAY-G in 0." in out["answer"]


def test_widest_coverage_across_districts_is_statewide(fake_db):
    out = _answer("Which scheme has the widest coverage across districts of Meghalaya?")
    assert "- **MGNREGA:** 2 districts, 5 blocks, 1,578 villages" in out["answer"]
    assert "**MGNREGA** has the most villages covered (1,578 villages). Order: MGNREGA" in out["answer"]
    assert all("district" not in r for r in out["rows"])


# ── the scope stage, exclusions, the gate ────────────────────────────────────

def test_the_scope_stage_hands_the_gaps_to_the_plan(monkeypatch):
    seen = {}

    async def fake_answer(plan):
        seen["plan"] = plan
        return {"answer": "ok", "rows": [], "sql": "S", "totals": None, "measure_notes": {}, "schemes_with_data": []}
    monkeypatch.setattr(p.cross_figures, "answer", fake_answer)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(p.cross_scheme, "refine_block", _noop)
    monkeypatch.setattr(p.cross_scheme, "refine_constituency", _noop)
    q = "Compare MGNREGA, Focus Plus and CM Elevate applicants in Mawhati constituency"
    d = p._new_data_turn(q)
    d.update(schemes=["MGNREGA", "Focus Plus", "CM Elevate"],
             cross={"schemes": ["MGNREGA", "Focus Plus", "CM Elevate"], "text": q},
             entity_result={"resolved": {"assembly_constituency": "MAWHATI"}, "display": {"assembly_constituency": "Mawhati"}})
    out = asyncio.run(p._cross_scheme_scope(d))
    assert out["answer"] == "ok" and seen["plan"].ac == "MAWHATI"
    assert set(seen["plan"].gaps) == {"Focus Plus", "CM Elevate"}
    assert "does not record assembly constituency" in seen["plan"].gaps["Focus Plus"]


def test_exclusions_still_leave_the_four_main_schemes():
    excluded, kept = p._cross_exclusions("Leaving out MGNREGA, which scheme has the most beneficiaries?")
    assert excluded == ["MGNREGA"]
    assert p._cross_after_exclusions(kept, [], None, excluded) == ["PMAY-G", "Focus Plus", "Focus Legacy"]
    assert cf.MAIN == ("MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy")


def test_the_access_check_sees_the_village_and_the_constituency(monkeypatch):
    seen = []

    def fake_denial(scope, schemes, entity_result, shape):
        seen.append(entity_result["resolved"])
        return None
    monkeypatch.setattr(p, "_repaired_sql_denial", fake_denial)
    pl = _plan("Compare MGNREGA and PMAY-G in Pamila village", ["MGNREGA", "PMAY-G"], {"village_code": 274001})
    assert p._c13_e12_cross_figures_denial(None, ["MGNREGA", "PMAY-G"], pl) is None
    assert seen == [{"village_code": 274001}]
    pl = _plan("Compare MGNREGA and PMAY-G in Mawhati constituency", ["MGNREGA", "PMAY-G"],
               {"assembly_constituency": "MAWHATI"})
    p._c13_e12_cross_figures_denial(None, ["MGNREGA", "PMAY-G"], pl)
    assert seen[-1] == {"assembly_constituency": "MAWHATI"}


def test_an_exact_block_name_is_never_respelt():
    # CROSS-9 (sheet re-run 2026-10-30): "William Nagar-Municipal Board block" (the LGD
    # block) was rewritten to Focus Plus's "Williamnagar" and every scheme answered 0
    from app import entity_resolver as er
    from app import spelling
    er.load_all()
    spelling.warm()
    q = "Compare the coverage of MGNREGA, PMAY-G, and CM-ELEVATE in William Nagar-Municipal Board block."
    assert spelling.normalise(q).text == q
    assert spelling.normalise("Tura Municipal Board-Municipal Board block").text == "Tura Municipal Board-Municipal Board block"
    # a misspelt block is still corrected
    assert spelling.normalise("how many in mawsinram block").text == "how many in Mawsynram block"


def test_the_tura_urban_body_is_read_under_both_stored_spellings():
    assert cf._block_names("TURA MUNICIPAL BOARD") == ["TURA MUNICIPAL BOARD", "TURA MUNICIPAL BOARD-MUNICIPAL BOARD"]
    assert cf._block_names("Tura Municipal Board-Municipal Board") == cf._block_names("TURA MUNICIPAL BOARD")
    assert cf._block_names("MYLLIEM") == ["MYLLIEM"]


def test_dataset_words_are_not_measures():
    assert cf._without_dataset_words("How much was disbursed under CM Elevate applicants and Legacy CM Elevate?") \
        == "How much was disbursed under CM Elevate and Legacy CM Elevate?"
    assert cf._without_dataset_words("Compare pmay-g vs cm elevate applicants performance") \
        == "Compare pmay-g vs cm elevate performance"
    assert cf._without_dataset_words("beneficiary/application count for CM-ELEVATE") \
        == "beneficiary/application count for CM-ELEVATE"
    # the context-stage pin writes "CM Elevate Legacy applicants" into a FY question
    # (YR-2017-17, sheet re-run 2026-10-30): still the dataset's name, not a measure
    assert cf._without_dataset_words("performance summary comparing pmay-g and CM Elevate Legacy applicants in 2017-18") \
        == "performance summary comparing pmay-g and CM Elevate Legacy in 2017-18"
    pl = _plan("Give me a performance summary comparing mgnrega, pmay-g, and CM Elevate Legacy applicants in 2017-18.",
               ["MGNREGA", "PMAY-G", "CM Elevate Legacy"], {"year_key": 2017})
    assert pl.measures == ["count", "money"]
    pl = _plan("How much total amount has been disbursed under cm elevate applicants and Legacy CM Elevate?",
               ["CM Elevate", "CM Elevate Legacy"])
    assert pl.measures == ["money"]


def test_same_named_villages_are_answered_one_row_each(fake_db):
    # KI-630 / D-096: "Apalgre" is three villages (Selsella, Rerapara, Tikrikilla blocks).
    # The resolver hands them over as village_twins; the coded path answers each,
    # never summed (the model path listed them with person-years, sheet re-run 2026-10-30)
    twins = {"272766": "Apalgre (Selsella block)", "273033": "Apalgre (Rerapara block)"}
    pl = _plan("What is the beneficiary count across NREGA & PMAY in APALGRE village?", ["MGNREGA", "PMAY-G"],
               {"village_code_list": [272766, 273033], "village_twins": twins},
               {"village": ", ".join(twins.values())})
    assert pl is not None and pl.grain == "village" and pl.villages == {272766: twins["272766"], 273033: twins["273033"]}
    assert pl.measures == ["count"] and pl.place_label == "Apalgre village (2 villages share the name)"
    out = asyncio.run(cf.answer(pl))
    assert "- Apalgre (Selsella block): MGNREGA 3,74,268 | PMAY-G 50,712 → MGNREGA" in out["answer"]
    assert "These are different villages that share a name; their figures are not added." in out["answer"]
    assert "**Total" not in out["answer"]
    codes = sorted((r["village_code"], r["scheme"]) for r in out["rows"])
    assert codes == [(272766, "MGNREGA"), (272766, "PMAY-G"), (273033, "MGNREGA"), (273033, "PMAY-G")]
    assert all(r["village"] in twins.values() for r in out["rows"])
    assert sum(1 for s, pr in fake_db if "village_code = $" in s and pr[:1] in ([272766], [273033])) == 6


def test_a_village_question_has_no_villages_measure(fake_db):
    # "… in Ward No. 6 village": the word names the place (VI-2366, sheet re-run 2026-10-30)
    pl = _plan("Compare the total expenditure or disbursement under MGNREGA and CM-ELEVATE in Ward No. 6 village",
               ["MGNREGA", "CM Elevate"], {"village_code": 2366}, {"village": "Ward No. 6"})
    assert pl.measures == ["money"]
    out = asyncio.run(cf.answer(pl))
    cme = next(r for r in out["rows"] if r["scheme"] == "CM Elevate")
    assert "villages" not in cme and cme["amount_crore"] is None


def test_a_ward_village_name_is_kept_in_full(monkeypatch):
    # "Mendipathar - Ward No.10 village" was truncated to "Mendipathar" (a constituency)
    # and asked "the whole constituency or part of it?" (VI-2534, sheet re-run 2026-10-30)
    from app import spelling
    monkeypatch.setattr(spelling, "_exact_village", lambda t: t.upper() in ("MENDIPATHAR - WARD NO.10",
                                                                            "WILLIAM NAGAR (MB) - WARD NO.1"))
    q = "Compare the total expenditure under MNREGA and Focus Plus in Mendipathar - Ward No.10 village."
    assert p._c09_full_village_in_text(q, ["Mendipathar"]) == "Mendipathar - Ward No.10"
    assert p._c09_full_village_in_text("beneficiaries in William Nagar (Mb) - Ward No.1 village", ["william nagar (mb)"]) \
        == "William Nagar (Mb) - Ward No.1"
    assert p._c09_full_village_in_text("beneficiaries in Mendipathar constituency", ["Mendipathar"]) is None
    assert p._c09_full_village_in_text("beneficiaries in Nongpoh village", ["Nongpoh"]) is None


def test_exact_village_matches_on_letters_and_digits(monkeypatch):
    from app import spelling
    from app import entity_resolver as er
    monkeypatch.setattr(er, "_village_code_names", {70672: "WILLIAM NAGAR (MB) - WARD NO.1", 2534: "Mendipathar - Ward No.10"})
    monkeypatch.setattr(er, "is_village_name", lambda t: False)
    spelling._FULL_NAMES.clear()
    assert spelling._exact_village("William Nagar Mb Ward No 1")        # the tokens of the typed name
    assert spelling._exact_village("Mendipathar - Ward No.10")
    assert not spelling._exact_village("William Nagar")


def test_applications_is_a_count_word_not_an_other_measure():
    assert cf._COUNT.search("beneficiary/application counts") is not None
    assert cf._OTHER_MEASURE.search("applications") is None
    assert cf._OTHER_MEASURE.search("person days") is not None          # B-7 still holds
    assert _plan("Compare MGNREGA person days and PMAY-G houses", ["MGNREGA", "PMAY-G"]) is None

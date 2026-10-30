"""PMAY-G sheet re-test 2026-10-30 (Test Case Results - 30th Sep 26.xlsx, sheet PMAY-G,
PMAY-OFF-001..028, every village / block / district / assembly constituency / FY): regression
tests against the real functions.

1. Constituency (KI-445): v_pmay carries dim_geography's ac_name (Title Case 'Amlarem'), but
   PMAY-G was not constituency-capable, so the fixed query refused the question and the model
   wrote ac_name = 'AMLAREM' -> a false 0 for Amlarem (true 2,677), Mawlai, North Tura; the
   chips said "... in Meghalaya" / "Break that down by district".
3. Spelling (KI-631): "RONGARE ADING" (village 274191) was rewritten by the D-093 normaliser to the
   block "Rongara ADING" (fuzzy 85.7 on its first word) and asked Rongara block / constituency /
   village; a span that begins an exact village name is never rewritten to a district / block.
2. Shared village names (KI-630; D-089 J-10 answers 2-3 twins on their own rows): "village_twins"
   was not a fixed-query key, so every twin question went to the model, which summed the twins
   ("39 beneficiaries in Kotchugre (Batabari block) and Kotchugre (Tikrikilla block)"; true 12 / 27)
   or failed to build a query.

OFFLINE, no DB.
    .venv/Scripts/python.exe -m pytest tests/test_pmay_sheet_rerun_2026_10_30.py -q
"""
import pytest

from app import followups
from app import pipeline as p
from app import scheme_registry as R

PM = ["PMAY-G"]


# ── 1. constituency (KI-445) ────────────────────────────────────────────────────

def test_pmay_g_is_constituency_capable_everywhere():
    assert "PMAY-G" in p._AC_CAPABLE_SCHEMES
    assert "PMAY-G" in p._CROSS_AC_RECORDED
    assert next(s for s in R.SCHEMES if s.name == "PMAY-G").records_constituency is True
    # every PMAY-G measure (houses, amounts, status) hangs off the row's ac_name
    assert p._ac_dimension_available("How many PMAY houses have been completed in Nongpoh?", PM) is True


@pytest.mark.parametrize("q", [
    "How many PMAY beneficiaries are there in Amlarem constituency across all financial years",
    "Give me the PMAY financial summary for Mawlai assembly constituency.",
    "Give me the house status breakdown for NORTH TURA AC.",
    "What percentage of PMAY houses are completed in Nongpoh constituency?",
])
def test_a_constituency_takes_the_fixed_query(q):
    spec = p._pmay_facts_query(q, PM, {"assembly_constituency": "AMLAREM"})
    assert spec is not None and spec["dim"] == "ac"
    assert "UPPER(ac_name) = ANY($1::text[])" in spec["sql"] and spec["params"][0] == ["AMLAREM"]
    assert "GROUP BY UPPER(ac_name)" in spec["sql"]


def test_a_constituency_with_a_year_keeps_both_filters():
    spec = p._pmay_facts_query("How many PMAY houses were completed in Amlarem constituency in FY 2023-24?",
                               PM, {"assembly_constituency": "AMLAREM", "year_key": 2023})
    assert spec["dim"] == "ac" and 2023 in spec["params"] and "year_key = $2" in spec["sql"]


def test_a_constituency_narrowed_to_a_block_stays_on_the_model_path():
    # the drill-down overlap (AC AND block) is not a one-dimension shape
    assert p._pmay_facts_query("How many PMAY beneficiaries are there in Mawlai constituency within the "
                               "Mylliem block only?", PM,
                               {"assembly_constituency": "MAWLAI", "block": "MYLLIEM"}) is None


def test_the_constituency_answer_names_the_constituency():
    spec = p._pmay_facts_query("How many PMAY beneficiaries are there in Amlarem constituency?", PM,
                               {"assembly_constituency": "AMLAREM"})
    row = {"entity_key": "AMLAREM", "name": "Amlarem", "houses": 2677, "placeholders": 1}
    assert p._pmay_entity_name(spec, row) == "Amlarem assembly constituency"
    assert list(p._pmay_display_rows(spec, [row])[0])[0] == "assembly_constituency"


def test_a_bare_ac_name_comparison_becomes_case_insensitive():
    bad = "SELECT COUNT(*) AS beneficiaries FROM curated.v_pmay WHERE ac_name = 'AMLAREM'"
    out = p._pmay_ac_name_case(PM, bad)
    assert "UPPER(ac_name) = 'AMLAREM'" in out
    assert p._pmay_ac_name_case(["MGNREGA"], bad) == bad


def test_a_query_without_the_constituency_is_repaired():
    er = {"resolved": {"assembly_constituency": "AMLAREM"}}
    district = "SELECT COUNT(*) FROM curated.v_pmay WHERE UPPER(lgd_district) = 'WEST JAINTIA HILLS'"
    good = "SELECT COUNT(*) FROM curated.v_pmay WHERE UPPER(ac_name) = UPPER('AMLAREM')"
    assert "UPPER(ac_name) = UPPER('AMLAREM')" in p._pmay_ac_filter_missing(PM, er, district)
    assert p._pmay_ac_filter_missing(PM, er, good) is None
    assert p._pmay_ac_filter_missing(["Focus Plus"], er, district) is None


def test_constituency_chips_keep_the_constituency():
    ents = {"assembly_constituency": "NORTH TURA"}
    assert followups._scope_phrase(ents) == " in North Tura constituency"
    assert followups._drill_down(ents) is None          # never "Break that down by district." of the state


# ── 2. shared village names (KI-630) ────────────────────────────────────────────

TWINS = {"village_code_list": [272805, 273369],
         "village_twins": {"272805": "Kotchugre (Batabari block)", "273369": "Kotchugre (Tikrikilla block)"}}
ROWS = [{"entity_key": 272805, "name": "KOTCHUGRE", "block": "BATABARI", "district": "WEST GARO HILLS",
         "houses": 12, "full_release": 12},
        {"entity_key": 273369, "name": "KOTCHUGRE", "block": "TIKRIKILLA", "district": "WEST GARO HILLS",
         "houses": 28, "full_release": 27}]


def test_twin_villages_take_the_fixed_query_one_row_each():
    spec = p._pmay_facts_query("How many beneficiaries in Kotchugre have received their full sanctioned "
                               "amount across all financial years", PM, dict(TWINS))
    assert spec is not None and spec["dim"] == "village" and spec["twins"] is True
    assert spec["params"][0] == [272805, 273369] and "GROUP BY village_code" in spec["sql"]


def test_twin_answer_gives_each_village_by_its_block_never_a_sum():
    spec = p._pmay_facts_query("How many beneficiaries in Kotchugre have received their full sanctioned "
                               "amount?", PM, dict(TWINS))
    spec["display"] = {}
    ans = p._pmay_facts_answer(spec, [dict(r) for r in ROWS])
    assert "is the name of 2 villages" in ans
    assert "Kotchugre village (Batabari block):" in ans and "Kotchugre village (Tikrikilla block):" in ans
    assert ": 12" in ans and ": 27" in ans and "39" not in ans
    assert "comparison" not in ans and "higher by" not in ans
    shown = p._pmay_display_rows(spec, [dict(r) for r in ROWS])
    assert [r["block"] for r in shown] == ["Batabari", "Tikrikilla"]


def test_twin_chips_name_the_village_not_the_state():
    assert followups._scope_phrase(TWINS) == " in Kotchugre"
    assert followups._drill_down(TWINS) is None


# ── 3. spelling over a multi-word village (KI-631) ─────────────────────────────

def test_a_block_typo_is_not_read_inside_an_exact_village_name(monkeypatch):
    from app import entity_resolver as er, spelling as sp
    monkeypatch.setattr(er, "is_village_name", lambda text: " ".join(text.upper().split()) == "RONGARE ADING")
    q = "How much sanctioned amount is still to be released in RONGARE ADING?"
    n = sp.normalise(q)
    assert n.text == q and not n.corrections
    # the same first word on its own is still read as the block Rongara (typo correction kept)
    n2 = sp.normalise("How much sanctioned amount is still to be released in RONGARE block?")
    assert "Rongara" in n2.text


@pytest.mark.parametrize("q,villages", [
    ("How many houses are still incomplete in Pyndeng Shallang?", {"PYNDENG SHALLANG"}),     # "pending"
    ("What is the total amount sanctioned in Centre Village?", {"CENTRE VILLAGE"}),           # village Kentra
    ("What is the total amount sanctioned in Songma Enggok?", {"SONGMA ENGGOK"}),             # block Songsak
    ("How many beneficiaries in hawai bhoi have received only part of their sanctioned amount?",
     {"HAWAI BHOI"}),                                                                           # district alias "bhoi"
])
def test_an_exact_village_name_is_never_respelt(monkeypatch, q, villages):
    from app import entity_resolver as er, spelling as sp
    monkeypatch.setattr(er, "is_village_name", lambda text: " ".join(text.upper().split()) in villages)
    n = sp.normalise(q)
    assert n.text == q and not n.corrections, n.corrections

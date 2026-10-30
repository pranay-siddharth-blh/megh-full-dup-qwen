"""PMAY-G's fixed query dropped the year-gap note (live chart suite 2026-10-30):
"Compare PMAY-G houses completed in 2023-24 and 2024-25" answered FY 2023-24 alone
and never said FY 2024-25 holds no PMAY-G data. The note now reaches the answer."""
from app import pipeline as p


def test_the_gap_note_is_computed_for_a_year_pmay_g_does_not_hold():
    q, note, handled = p._apply_year_gap("Compare PMAY-G houses completed in 2023-24 and 2024-25", ["PMAY-G"])
    assert handled and "2024-25" not in q
    assert note and "holds no data for this scheme" in note


def test_the_fixed_query_answer_carries_the_gap_note():
    note = "FY 2024-25 holds no data for this scheme, so it is left out — that is a gap in the records, not a zero."
    ans = p._pmay_with_year_gap_note("Completed houses in Meghalaya, FY 2023-24: 71,976.", [note, "Other note."])
    assert ans.endswith(note)
    assert "Other note." not in ans                      # only the year-gap note is added
    assert p._pmay_with_year_gap_note(ans, [note]) == ans   # never twice


def test_no_note_leaves_the_answer_alone():
    assert p._pmay_with_year_gap_note("x", None) == "x"
    assert p._pmay_with_year_gap_note("x", []) == "x"


def test_the_pmay_data_stage_uses_it():
    from pathlib import Path
    src = (Path(p.__file__).parent / "common" / "c13_compose_and_data_stages.py").read_text(encoding="utf-8")
    assert "_pm_answer = _pmay_with_year_gap_note(_pm_answer, entity_result.get(\"notes\"))" in src


# KI-629: two or more years for one place are one row per sanction year, on the fixed query
def test_a_two_year_comparison_groups_by_year():
    spec = p._pmay_facts_query("Compare PMAY-G houses completed in 2022-23 and 2023-24", ["PMAY-G"],
                               {"year_key_list": [2023, 2022]})
    assert spec is not None and spec["dim"] == "year" and spec["entities"] == [2022, 2023]
    assert spec["place_dim"] == "state" and spec["params"][-1] == [2022, 2023]
    assert "GROUP BY year_key" in spec["sql"] and "year_key = ANY(" in spec["sql"]
    rows = [{"entity_key": 2022, "name": "2022-23", "houses": 8225, "completed": 6248},
            {"entity_key": 2023, "name": "2023-24", "houses": 106527, "completed": 71976}]
    spec["display"] = {}
    ans = p._pmay_facts_answer(spec, rows)
    assert ans.startswith("PMAY-G comparison, Meghalaya (statewide), by the year the houses were sanctioned")
    assert "FY 2022-23:" in ans and "6,248" in ans and "71,976" in ans
    assert p._pmay_display_rows(spec, rows)[0]["financial_year"] == "2022-23"


def test_a_year_comparison_keeps_its_place():
    spec = p._pmay_facts_query("Compare PMAY-G houses sanctioned in West Garo Hills in 2021-22 and 2022-23",
                               ["PMAY-G"], {"district": "WEST GARO HILLS", "year_key_list": [2021, 2022]})
    assert spec["dim"] == "year" and spec["place_dim"] == "district"
    assert "UPPER(lgd_district) = ANY(" in spec["sql"]


def test_places_by_years_stay_with_the_model_path():
    assert p._pmay_facts_query("Compare PMAY-G houses in Tura and Jowai in 2021-22 and 2022-23", ["PMAY-G"],
                               {"district_list": ["WEST GARO HILLS", "WEST JAINTIA HILLS"],
                                "year_key_list": [2021, 2022]}) is None

"""A scope the officer STATED is never asked for again (2026-10-24, RAG plan A2 / C1).

The held-out NL->SQL set (tests/nl2sql_eval, 2026-10-24) showed "which year?" /
"which area?" asked of questions that already said it ("all <word> years together",
"altogether", a "which <places> …" list). Another wording of the same question was
answered, so two wordings took two paths. The wordings below are our own, never the
held-out questions (holdout.py). D-053 stays: a question that
states NOTHING is still asked.

"FY24" is FY 2023-24 (the year ending March 2024, as every SME catalogue reads it);
it was parsed as FY 2024-25. "FY 23-24" stays the range starting 2023."""
import pytest

from app import pipeline as p


@pytest.mark.parametrize("text, year", [
    ("total spend in FY24", 2023), ("total spend in FY'24", 2023), ("total spend in FY 24", 2023),
    ("total spend in fy24", 2023), ("in FY24.", 2023), ("total spend in FY25", 2024),
    ("total spend in FY 23-24", 2023), ("total spend in FY23-24", 2023), ("FY23/24", 2023),
    ("fy 24-25", 2024), ("FY24-25", 2024), ("FY 24 - 25", 2024),
    ("total spend in 2023-24", 2023), ("total spend in 23-24", 2023),
    ("total spend in FY 2023-24", 2023), ("total spend in 2023", 2023),
])
def test_financial_year_forms(text, year):
    assert p._parse_year_key(text) == year


@pytest.mark.parametrize("q", [
    "PMAY-G houses still incomplete in East Garo Hills, all reporting years taken together",
    "Total MGNREGA expenditure in East Khasi Hills altogether",
    "Total MGNREGA expenditure in East Khasi Hills since the start",
    "Total MGNREGA expenditure in East Khasi Hills, lifetime",
    "Total MGNREGA expenditure in East Khasi Hills for the whole period",
    "Total MGNREGA expenditure in East Khasi Hills from the beginning",
])
def test_a_stated_all_years_period_is_not_asked(q):
    assert not p._needs_year_clarification(q, ["MGNREGA"], {"district": "EAST KHASI HILLS"})


def test_the_new_all_years_wordings_stay_out_of_the_verifier_cue():
    """The SQL verifier skips its mandatory-year check on _ALL_YEARS_CUE, so
    "altogether in FY 2024-25" must keep that check: the new wordings live only
    in the year gate's own cue."""
    q = "Count of CM Elevate Legacy sanctions altogether in FY 2024-25"
    assert p._STATED_ALL_YEARS_CUE.search(q) and not p._ALL_YEARS_CUE.search(q)


@pytest.mark.parametrize("q", [
    "Total CM Elevate Legacy loan paid out altogether for Piggery",
    "Total MGNREGA expenditure in the whole state in FY 2023-24",
    "Total MGNREGA expenditure in entire Meghalaya in FY 2023-24",
    "Total MGNREGA expenditure for the state in FY 2023-24",
    "Total MGNREGA expenditure for the state as a whole in FY 2023-24",
    "Which districts spent over 20 crore on MGNREGA wages in FY 2023-24?",
    "What blocks crossed 500 PMAY-G completions in FY 2021-22?",
    "List the districts with MGNREGA expenditure above 50 crore in FY 2023-24",
])
def test_a_stated_area_is_not_asked(q):
    assert not p._needs_scope_clarification(q, {})


@pytest.mark.parametrize("q", [
    "Total MGNREGA expenditure",
    "How many PMAY-G houses were sanctioned?",
    "how many households for MGNREGA",
])
def test_a_question_that_states_nothing_is_still_asked(q):
    """D-053 / D-056: no place and no year anywhere -> ask."""
    assert p._needs_scope_clarification(q, {})
    assert p._needs_year_clarification(q, ["MGNREGA"], {"district": "EAST KHASI HILLS"})


def test_an_extracted_bare_fy_number_is_read_from_the_question(monkeypatch):
    """Live 2026-10-24: "FY24" is spaced to "FY 24", the extractor returned only "24",
    no year was resolved and the SQL model read "FY 24" as FY 2024-25."""
    import asyncio

    async def _extract(q):
        return {"year": "24"}

    monkeypatch.setattr(p, "extract_entity_mentions", _extract)
    out = asyncio.run(p.resolve_entities("Total PMAY-G houses completed in FY 24", ["PMAY-G"]))
    assert out["resolved"].get("year_key") == 2023

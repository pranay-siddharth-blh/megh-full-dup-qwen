"""Short financial-year forms are read the same in every place a year is read (2026-10-26).

User screenshot: a follow-up "give me FY 25" was answered for FY 2022-23 (the previous
turn's year). The extractor returned no year, and neither the year back-fill nor the
out-of-range guard knew the "FY 25" form, so the follow-up kept the old year. The same gap
let "Focus Legacy … FY 20" (no data) be answered for a year the model made up, and a bare
"FY'25" message was refused as off-topic. One shared reader (_c06_short_fy_tokens +
_parse_year_key) now serves the guard, the back-fill and the edge filter."""
import pytest

from app import edge
from app import pipeline as p

MG, FL = ["MGNREGA"], ["Focus Legacy"]


@pytest.mark.parametrize("text, tokens", [
    ("person-days for FY 25?", ["FY 25"]), ("in FY25", ["FY25"]), ("in FY'25", ["FY'25"]),
    ("in FY 23-24", ["FY 23-24"]), ("in FY23-24", ["FY23-24"]), ("in 23-24", ["23-24"]),
    ("FY 24 and FY 25", ["FY 24", "FY 25"]),
    ("blocks with 30-31 villages", []), ("between 10-11 am", []), ("top 20 districts", []),
    ("in FY 2023-24", []),                       # long form: the existing scan's job
])
def test_the_short_form_scan(text, tokens):
    assert [t for _s, t in p._c06_short_fy_tokens(text)] == tokens


@pytest.mark.parametrize("text, schemes, bad", [
    ("payments in Ri Bhoi in FY 20?", FL, "FY 20"),          # FY 2019-20: no data
    ("person-days under MGNREGA for FY 21?", MG, "FY 21"),   # FY 2020-21: no data
    ("in 23-24", FL, "23-24"),                                # FY 2023-24: the Focus Legacy gap
    ("person-days under MGNREGA for FY 25?", MG, None),      # FY 2024-25: held
])
def test_the_out_of_range_guard_sees_short_forms(text, schemes, bad):
    assert p._out_of_range_year_in(text, schemes) == bad


@pytest.mark.parametrize("text, year", [
    ("What are the person-days under MGNREGA for FY 25?", "2024-25"),
    ("person-days in FY'25", "2024-25"), ("person-days in FY 23-24", "2023-24"),
    ("person-days in 23-24", "2023-24"),
])
def test_a_dropped_short_form_year_is_back_filled(text, year):
    assert p._backfill_explicit_year(text, MG, {}) == {"year": year}


def test_the_back_fill_stays_narrow():
    assert p._backfill_explicit_year("FY 24 and FY 25", MG, {}) == {}          # two years: not guessed
    assert p._backfill_explicit_year("person-days in FY 21", MG, {}) == {}     # no data: the guard's job
    assert p._backfill_explicit_year("FY 25", MG, {"year": "2023-24"}) == {"year": "2023-24"}


@pytest.mark.parametrize("text", ["FY'25", "FY 25", "FY25"])
def test_a_bare_fy_message_is_not_off_topic(text):
    assert edge.detect_edge_case(text, has_context=False) is None


# ── One reader for every caller: extract_year_keys and the rewrite check ─────────
from app import context_policy as cp  # noqa: E402


@pytest.mark.parametrize("text, years", [
    ("FY20?", {2019}), ("FY 25", {2024}), ("FY'25", {2024}), ("give me FY 21", {2020}),
    ("in FY 23-24", {2023}), ("in 23-24", {2023}), ("FY 24 and FY 25", {2023, 2024}),
    ("FY 2024-25", {2024}), ("2024", {2024}),
    ("blocks with 30-31 villages", set()), ("top 20 districts", set()),
])
def test_extract_year_keys_reads_the_short_forms(text, years):
    assert cp.extract_year_keys(text) == years


_ALLOWED = "how many PMAY-G houses were sanctioned in FY 23 in all of Meghalaya FY20?"


def test_a_rewrite_may_not_replace_the_year_the_user_typed():
    """Live 2026-10-26: "FY20?" after an FY 2022-23 answer was rewritten to FY 2022-23."""
    assert cp.rewrite_violation(
        "How many PMAY-G houses were sanctioned in FY 2022-23 in all of Meghalaya?", question="FY20?",
        allowed_text=_ALLOWED, denied_text="", allowed_schemes=["PMAY-G"], state_year=2022) == "year"


def test_a_rewrite_that_keeps_the_typed_year_passes():
    assert cp.rewrite_violation(
        "How many PMAY-G houses were sanctioned in FY 20 in all of Meghalaya?", question="FY20?",
        allowed_text=_ALLOWED, denied_text="", allowed_schemes=["PMAY-G"], state_year=2022) is None

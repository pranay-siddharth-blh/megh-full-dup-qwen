"""The "top how many?" pause (ranking-count-not-specified) fires only for a
ranking that names no list length.

Two general misfires, found by the held-out NL->SQL accuracy set (2026-10-16):
  - a count written right before the dimension ("which four districts", "the
    10 blocks") was not read as the list length — only "top 3" / "3 highest" were;
  - "at least" / "at most" were read as ranking words ("least", "most"), so a
    plain count with a threshold paused to ask for a top-N.
"""
import pytest

from app import pipeline as p
from app.config import settings


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(settings, "TOPN_CLARIFY_ENABLED", True)


@pytest.mark.parametrize("q", [
    "Which four districts recorded the highest PMAY-G completions in 2022-23?",
    "Show the 10 blocks with the lowest MGNREGA spend in 2023-24",
    "Name 2 villages in Ri Bhoi with the most Focus Plus payments",
    "which seven blocks lead on CM Elevate applications",
    "Top 5 districts by Focus Plus amount disbursed",
    "the 3 highest blocks for person-days",
])
def test_a_stated_count_needs_no_pause(q):
    assert not p._needs_topn_clarification(q)


@pytest.mark.parametrize("q", [
    "How many blocks had at least 50 CM Elevate applications?",
    "How many villages spent at most 2 lakh under MGNREGA in 2024-25?",
    "Number of districts with at least one PMAY-G house completed in 2021-22",
])
def test_at_least_and_at_most_are_thresholds_not_rankings(q):
    assert not p._needs_topn_clarification(q)


@pytest.mark.parametrize("q", [
    "Which blocks have the highest MGNREGA person-days in 2023-24?",
    "Top districts by Focus Plus amount disbursed",
    "Which villages received the least PMAY-G releases in 2022-23?",
    "rank the districts by CM Elevate applications",
])
def test_a_ranking_with_no_count_still_pauses(q):
    assert p._needs_topn_clarification(q)


def test_a_year_is_not_a_count():
    # "2023 villages" is not "list 2023 villages" — only 1-3 digit counts.
    assert p._needs_topn_clarification("Which villages had the most MGNREGA person-days in 2023 villages list")

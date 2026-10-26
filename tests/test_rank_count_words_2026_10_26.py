"""A ranking count written as a word is the same count as digits (RAG plan C2, 2026-10-26).

"Five highest blocks by person-days" asked "top 3, 5 or 10?" although it says five,
while "top 5 blocks" was answered (audit 2026-10-23). _normalize_rank_counts writes the
count as digits once, in a ranking position only; _stated_rank_count_limit then makes
the SQL's outer LIMIT the stated count, deterministically, where that is safe."""
import pytest

from app import pipeline as p


@pytest.mark.parametrize("text, expected", [
    ("Five highest blocks by person-days", "5 highest blocks by person-days"),
    ("The ten lowest villages by houses completed", "The 10 lowest villages by houses completed"),
    ("Top ten districts by expenditure", "Top 10 districts by expenditure"),
    ("bottom three blocks", "bottom 3 blocks"),
    ("Top twenty-five villages", "Top 25 villages"),
    ("top twenty five villages", "top 25 villages"),
    ("Which three blocks had the most houses?", "Which 3 blocks had the most houses?"),
    ("What four districts spent the least?", "What 4 districts spent the least?"),
    ("top one district", "top 1 district"),
])
def test_a_count_word_in_a_ranking_position_becomes_digits(text, expected):
    assert p._normalize_rank_counts(text) == expected


@pytest.mark.parametrize("text", [
    "fifth highest block by expenditure",           # a rank position, not a count
    "second highest district",
    "Show me the first one",
    "Which one district had the most?",
    "MGNREGA spend over the last five years",        # a span of time
    "Compare the two schemes",
    "How many households in the five districts of Garo Hills?",
    "blocks with at least five villages",
    "Top 5 blocks by person-days",                   # already digits
])
def test_everything_else_is_left_as_written(text):
    assert p._normalize_rank_counts(text) == text


@pytest.mark.parametrize("text", [
    "Five highest blocks by spend in FY 2023-24",
    "Ten lowest villages by houses completed",
    "The six largest districts by sanctioned houses",
])
def test_a_count_word_no_longer_asks_how_many(text):
    assert p._needs_topn_clarification(text)                     # as typed: asked before
    assert not p._needs_topn_clarification(p._normalize_rank_counts(text))


def test_a_ranking_with_no_count_is_still_asked():
    assert p._needs_topn_clarification(
        p._normalize_rank_counts("Which blocks had the most person-days in 2023-24?"))


@pytest.mark.parametrize("text, n", [
    ("5 highest blocks", 5), ("top 10 districts", 10), ("top5 districts", 5),
    ("which 3 blocks had the most", 3), ("top 5 lowest districts by expenditure", 5),
    ("fifth highest block", None), ("which blocks had the most", None),
    ("top 5 and bottom 5 districts", None), ("highest and lowest 3 districts", None),
    ("top 5 blocks in each district", None), ("district-wise top 3 blocks", None),
    ("top districts in FY 2023-24 highest spend", None),
])
def test_the_stated_count(text, n):
    assert p._requested_rank_count(text) == n


_RANKED = ("SELECT lgd_block, SUM(person_days) AS pd FROM curated.v_employment "
           "WHERE lgd_district = 'WEST GARO HILLS' GROUP BY lgd_block ORDER BY pd DESC")


@pytest.mark.parametrize("sql, limit", [
    (_RANKED + " LIMIT 10", 5),
    (_RANKED, 5),
    (_RANKED + " LIMIT 1", 5),
    (_RANKED + " LIMIT 5", 5),
    ("WITH t AS (SELECT lgd_block, SUM(person_days) pd FROM curated.v_employment GROUP BY lgd_block) "
     "SELECT * FROM t ORDER BY pd DESC LIMIT 20", 5),
])
def test_the_ranked_query_returns_the_stated_count(sql, limit):
    assert p.sql_ast.outer_limit(p._stated_rank_count_limit("5 highest blocks", sql)) == limit


@pytest.mark.parametrize("question, sql", [
    ("5 highest blocks", "SELECT lgd_block, SUM(person_days) FROM curated.v_employment GROUP BY lgd_block"),
    ("5 highest blocks", "SELECT * FROM (SELECT lgd_block, RANK() OVER (ORDER BY SUM(person_days) DESC) r "
                         "FROM curated.v_employment GROUP BY lgd_block) x WHERE r <= 5 ORDER BY r"),
    ("5 highest blocks", _RANKED + " LIMIT 10 OFFSET 5"),
    ("top 5 and bottom 5 blocks", _RANKED + " LIMIT 10"),
    ("which blocks had the most", _RANKED + " LIMIT 10"),
])
def test_other_shapes_are_left_to_the_model(question, sql):
    """No ORDER BY, a window (ties / per-group ranks), paging, two directions, no count."""
    assert p._stated_rank_count_limit(question, sql) == sql

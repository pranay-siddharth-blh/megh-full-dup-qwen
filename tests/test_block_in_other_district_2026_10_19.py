"""KI-327 (live 2026-10-19): a follow-up naming a block in ANOTHER district is
answered for that block's own district, not the inherited one.

"now give me for dambo rongjeng block" after a Focus Plus West Garo Hills village
turn: the rewrite carried "West Garo Hills" into the text, the resolver dropped
the district but the 30B wrote lgd_district = 'WEST GARO HILLS' back from the
text (0 for a block in East Garo Hills). Without the word "block" the rewrite
guessed "village", the name resolved as nothing, and the generator filtered the
block on its own under the stale district."""
import asyncio

import pytest

from app import entity_resolver
from app import pipeline as p

MG = ["MGNREGA"]


@pytest.fixture(scope="module", autouse=True)
def _catalogues():
    entity_resolver.load_all()


def _stub(monkeypatch, mentions):
    """Deterministic resolve_entities: fixed extractor output, no village in the DB."""
    async def _extract(q):
        return dict(mentions)

    async def _no_village(*a, **k):
        return entity_resolver.Resolved("not_found", "village", str(a[0]) if a else "")

    async def _no_scan(*a, **k):
        return None

    async def _no_contents(*a, **k):
        return {"districts": [], "blocks": [], "villages": 0}

    async def _no_names():
        return {}

    async def _no_exact(cands):
        return {}

    monkeypatch.setattr(p, "extract_entity_mentions", _extract)
    monkeypatch.setattr(p, "resolve_village", _no_village)
    monkeypatch.setattr(p, "_scan_village_in_question", _no_scan)
    monkeypatch.setattr(p, "constituency_contents", _no_contents)
    monkeypatch.setattr(p, "_mgnrega_village_names", _no_names)
    monkeypatch.setattr(p, "village_names_exact", _no_exact)


Q_BLOCK = "What is the total MGNREGA expenditure for the financial year 2022-23 in Dambo Rongjeng block, West Garo Hills?"
Q_VILLAGE = "What is the total MGNREGA expenditure for the financial year 2022-23 in Dambo Rongjeng village, West Garo Hills?"


def test_block_in_another_district_replaces_the_inherited_district(monkeypatch):
    _stub(monkeypatch, {"block": "Dambo Rongjeng", "district": "West Garo Hills", "year": "2022-23"})
    out = asyncio.run(p.resolve_entities(Q_BLOCK, MG))
    assert out["resolved"]["block"] == "DAMBO RONGJENG"
    assert out["resolved"]["district"] == "EAST GARO HILLS"
    assert out["display"]["district"] == "East Garo Hills"
    # the stale name leaves the question text, so SQL generation cannot read it back
    assert "West Garo Hills" not in out["question"]
    assert "Dambo Rongjeng block, East Garo Hills" in out["question"]


def test_name_that_is_a_block_and_no_village_is_placed_as_the_block(monkeypatch):
    _stub(monkeypatch, {"village": "Dambo Rongjeng", "district": "West Garo Hills", "year": "2022-23"})
    out = asyncio.run(p.resolve_entities(Q_VILLAGE, MG))
    assert "village_code" not in out["resolved"]
    assert out["resolved"]["block"] == "DAMBO RONGJENG"
    assert out["resolved"]["district"] == "EAST GARO HILLS"
    assert not any("not a known village" in n for n in out["notes"])


def test_block_in_the_district_named_is_untouched(monkeypatch):
    _stub(monkeypatch, {"block": "Dambo Rongjeng", "district": "East Garo Hills"})
    out = asyncio.run(p.resolve_entities("MGNREGA person-days in Dambo Rongjeng block, East Garo Hills", MG))
    assert out["resolved"]["district"] == "EAST GARO HILLS" and out["resolved"]["block"] == "DAMBO RONGJENG"
    assert "question" not in out


def test_an_explicit_village_choice_is_not_turned_into_a_block(monkeypatch):
    _stub(monkeypatch, {"village": "Dambo Rongjeng"})
    out = asyncio.run(p.resolve_entities(
        "MGNREGA person-days in Dambo Rongjeng, the village, not the block", MG))
    assert "block" not in out["resolved"]
    assert any("not a known village" in n for n in out["notes"])


def test_swap_place_name_is_case_insensitive_and_whole():
    assert p._c09_swap_place_name("in Dambo Rongjeng block, West Garo Hills?", "WEST GARO HILLS", "East Garo Hills") \
        == "in Dambo Rongjeng block, East Garo Hills?"
    assert p._c09_swap_place_name("nothing here", "WEST GARO HILLS", "East Garo Hills") == "nothing here"


SQL = ("SELECT SUM(amount_disbursed) AS amount_raw FROM curated.v_focus_plus "
       "WHERE year_key = 2022 AND UPPER(block_name_raw) = 'DAMBO RONGJENG' AND lgd_district = 'WEST GARO HILLS' LIMIT 1")


def test_sql_district_literal_follows_the_resolved_district():
    out = p._resolved_district_literal({"block": "DAMBO RONGJENG", "district": "EAST GARO HILLS"}, SQL)
    assert "'EAST GARO HILLS'" in out and "WEST GARO HILLS" not in out
    assert "'DAMBO RONGJENG'" in out and "year_key = 2022" in out


def test_sql_district_literal_is_left_alone_when_it_matches_or_is_a_comparison():
    assert p._resolved_district_literal({"district": "WEST GARO HILLS"}, SQL) == SQL
    assert p._resolved_district_literal({"district": "X", "district_list": ["WEST GARO HILLS", "EAST GARO HILLS"]}, SQL) == SQL
    assert p._resolved_district_literal({}, SQL) == SQL
    assert p._resolved_district_literal({"district": "EAST GARO HILLS"}, "SELECT 1") == "SELECT 1"
    # a district-only mismatch is the scope guards' business (KI-183: a repair that
    # moves the geography is re-authorized and denied, not corrected)
    assert p._resolved_district_literal({"district": "EAST GARO HILLS"}, SQL) == SQL

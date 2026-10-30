"""A place named without its level word is still a place (user report 2026-10-21).

Live chat: "How much PMAY-G amount was released in East Garo Hills in FY 2023-24?"
then "in ambare ading" -> "I don't have information about that"; only "in ambare
ading village" was answered. The continuation check and the edge whitelist knew
districts and blocks (YAML catalogues) but no village, so the bare village name
shared nothing with the conversation. Fixed with an in-memory village-name index
(entity_resolver.place_mentions) read by the continuation check, the edge
whitelist and the guardrail; a follow-up that is only a place is rewritten
deterministically (_place_swap_rewrite); the rewrite must keep a typed place; the
level question is asked only for the SAME name at two levels; the chat's
district is not carried onto a block in another district.

Offline: the village index is stubbed with real names from curated.dim_geography."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from app import context_policy, edge
from app import entity_resolver as er
from app import pipeline as p

_VILLAGES = {
    "AMBARE ADING": frozenset({"EAST GARO HILLS"}),
    "DANGAR DOMBAH": frozenset({"EAST KHASI HILLS"}),
    "DANAK DOPGRE": frozenset({"WEST GARO HILLS"}),
    "LOWER DAMALGRE": frozenset({"SOUTH WEST GARO HILLS"}),
    "NANDICHAR I": frozenset({"SOUTH WEST GARO HILLS"}),
    "KBET NONGBRI": frozenset({"RI BHOI"}),
    "MAWLAI": frozenset({"EAST KHASI HILLS"}),
    "RAJABALA": frozenset({"WEST GARO HILLS"}),
    "DAMBO RONGDENG": frozenset({"EAST GARO HILLS"}),
    "SOHRARIM": frozenset({"EAST KHASI HILLS"}),
}


@pytest.fixture(autouse=True)
def _index(monkeypatch):
    er.load_all()
    monkeypatch.setattr(er, "_village_names", dict(_VILLAGES))


# ── Recognition ─────────────────────────────────────────────────────────────
def test_a_bare_village_is_a_place():
    assert er.place_mentions("in ambare ading") == {"AMBARE ADING": "village"}
    assert er.place_mentions("Kbet Nongbri?") == {"KBET NONGBRI": "village"}
    assert er.place_mentions("who is harshit") == {}


def test_a_longer_village_name_beats_the_block_inside_it():
    # "Lower Damalgre" is a village; DAMALGRE is also a block.
    assert er.place_mentions("in lower damalgre") == {"LOWER DAMALGRE": "village"}
    assert er.place_mentions("in damalgre block") == {"DAMALGRE": "block"}


def test_a_district_word_is_not_a_village():
    assert er.place_mentions("in East Garo Hills") == {"EAST GARO HILLS": "district"}


def test_a_bare_constituency_is_a_place():
    assert er.place_mentions("in mendipathar") == {"MENDIPATHAR": "assembly_constituency"}


def test_continuation_signal_for_a_bare_village():
    assert "place" in context_policy.continuation_signals("in ambare ading")
    assert context_policy.continuation_signals("who is harshit") == []


def test_edge_whitelist_lets_a_bare_village_through_in_a_new_chat():
    assert edge.detect_edge_case("ambare ading") is None
    assert (edge.detect_edge_case("who is harshit") or {}).get("type") == "off_topic"


def test_guardrail_overrule_for_a_short_place_message():
    assert p._names_place_only("in ambare ading")
    assert not p._names_place_only("who is harshit")


# ── Level question only for the same name ──────────────────────────────────
def test_exact_block_with_only_a_lookalike_village_is_not_asked():
    # Live: "Dambo Rongjeng" asked "block or village?" off the village DAMBO RONGDENG.
    assert er.collides_across_dimensions("Dambo Rongjeng", "PMAY-G", village_hit=True) == {}
    assert er.collides_across_dimensions("Sohra", "MGNREGA", village_hit=True) == {}


def test_same_name_block_constituency_village_still_asks():
    dims = er.collides_across_dimensions("Mawlai", "MGNREGA", village_hit=True)
    assert set(dims) >= {"block", "village"}


def test_without_the_index_the_old_reading_stands(monkeypatch):
    monkeypatch.setattr(er, "_village_names", None)
    assert "village" in er.collides_across_dimensions("Sohra", "MGNREGA", village_hit=True)


# ── Follow-up rewrite ──────────────────────────────────────────────────────
def _prev(q, district):
    return NS(question=q, route="data", resolved_entities={"district": district})


def test_place_swap_for_the_reported_chat():
    prev = _prev("How much PMAY-G amount was released in East Garo Hills in FY 2023-24?", "EAST GARO HILLS")
    assert p._place_swap_rewrite(prev, "in ambare ading") == \
        "How much PMAY-G amount was released in Ambare Ading village in East Garo Hills in FY 2023-24?"


def test_place_swap_block_in_another_district_drops_the_old_district():
    prev = _prev("How many households were employed under MGNREGA in East Khasi Hills in FY 2023-24?",
                 "EAST KHASI HILLS")
    assert p._place_swap_rewrite(prev, "wapung") == \
        "How many households were employed under MGNREGA in Wapung block, East Jaintia Hills in FY 2023-24?"


def test_place_swap_same_name_at_two_levels_goes_in_bare():
    # RAJABALA is a constituency AND a village: no level word, so the gate asks.
    prev = _prev("How many households were employed under MGNREGA in West Garo Hills in FY 2023-24?",
                 "WEST GARO HILLS")
    assert p._place_swap_rewrite(prev, "in rajabala") == \
        "How many households were employed under MGNREGA in Rajabala in FY 2023-24?"


def test_place_swap_leaves_a_block_of_the_same_district_to_the_model():
    prev = _prev("How many households were employed under MGNREGA in East Khasi Hills in FY 2023-24?",
                 "EAST KHASI HILLS")
    assert p._place_swap_rewrite(prev, "in mawlai") is None


def test_place_swap_statewide_narrows():
    prev = _prev("How many households were employed under MGNREGA statewide in FY 2023-24?", "")
    assert p._place_swap_rewrite(prev, "dangar dombah") == \
        "How many households were employed under MGNREGA in Dangar Dombah village in FY 2023-24?"


def test_place_swap_leaves_districts_and_other_words_to_the_model():
    prev = _prev("How much PMAY-G amount was released in East Garo Hills in FY 2023-24?", "EAST GARO HILLS")
    assert p._place_swap_rewrite(prev, "in East Khasi Hills") is None
    assert p._place_swap_rewrite(prev, "in ambare ading for 2022-23") is None
    assert p._place_swap_rewrite(prev, "who is harshit") is None


def test_rewrite_must_keep_a_typed_village_and_place():
    # Live: "Dargar Dombah"; "wapung" rewritten back to East Khasi Hills.
    kw = dict(allowed_text="How many households in East Khasi Hills in FY 2023-24? in dangar dombah",
              denied_text="", allowed_schemes=["MGNREGA"])
    assert context_policy.rewrite_violation(
        "How many households were employed under MGNREGA in Dargar Dombah in FY 2023-24?",
        question="in dangar dombah", **kw) == "village"
    assert context_policy.rewrite_violation(
        "How many households were employed under MGNREGA in Dangar Dombah in FY 2023-24?",
        question="in dangar dombah", **kw) is None
    assert context_policy.rewrite_violation(
        "How many households were employed under MGNREGA in East Khasi Hills in FY 2023-24?",
        question="wapung", **{**kw, "allowed_text": kw["allowed_text"] + " wapung"}) == "dropped:block"


def test_misspelt_village_is_put_back_as_typed():
    assert p._restore_typed_village(
        "in dangar dombah", "How many households were employed under MGNREGA in Dargar Dombah in FY 2023-24?") == \
        "How many households were employed under MGNREGA in Dangar Dombah in FY 2023-24?"


# ── The chat's district is not carried onto a block elsewhere ──────────────
def _stub_resolver(monkeypatch, mentions):
    """Deterministic resolve_entities: fixed extractor output, no village in the DB
    (the stubs of tests/test_block_in_other_district_2026_10_19.py)."""
    async def _extract(q):
        return dict(mentions)

    async def _no_village(*a, **k):
        return er.Resolved("not_found", "village", str(a[0]) if a else "")

    async def _none(*a, **k):
        return None

    async def _no_contents(*a, **k):
        return {"districts": [], "blocks": [], "villages": 0}

    async def _empty(*a, **k):
        return {}

    monkeypatch.setattr(p, "extract_entity_mentions", _extract)
    monkeypatch.setattr(p, "resolve_village", _no_village)
    monkeypatch.setattr(p, "_scan_village_in_question", _none)
    monkeypatch.setattr(p, "constituency_contents", _no_contents)
    monkeypatch.setattr(p, "_mgnrega_village_names", _empty)
    monkeypatch.setattr(p, "village_names_exact", _empty)


def test_chat_district_not_carried_onto_a_block_in_another_district(monkeypatch):
    # Live: "... in Wapung block in FY 2023-24" after an East Khasi Hills answer
    # filtered lgd_district = 'EAST KHASI HILLS' too and answered "no records".
    _stub_resolver(monkeypatch, {"block": "Wapung", "year": "2023-24"})
    out = asyncio.run(p.resolve_entities(
        "How many households were employed under MGNREGA in Wapung block in FY 2023-24?", ["MGNREGA"],
        prior_resolved={"district": "EAST KHASI HILLS", "year_key": 2023}))
    assert out["resolved"].get("block") == "WAPUNG"
    assert out["resolved"].get("district") in (None, "EAST JAINTIA HILLS")


def test_chat_district_still_carried_onto_a_block_inside_it(monkeypatch):
    _stub_resolver(monkeypatch, {"block": "Mawsynram", "year": "2023-24"})
    out = asyncio.run(p.resolve_entities(
        "How many households were employed under MGNREGA in Mawsynram block in FY 2023-24?", ["MGNREGA"],
        prior_resolved={"district": "EAST KHASI HILLS", "year_key": 2023}))
    assert out["resolved"].get("district") == "EAST KHASI HILLS"


def test_block_with_only_lookalike_villages_is_answered_as_the_block(monkeypatch):
    # KI-339: "total expenditure in WAPUNG" asked "the block or a village with that
    # name?" off WAPUNG SKUR / WAPUNG SHNONG — no village is named WAPUNG.
    _stub_resolver(monkeypatch, {"block": "WAPUNG", "year": "2023-24"})

    async def _lookalikes(*a, **k):
        return er.Resolved("ambiguous", "village", "WAPUNG", candidates=[
            {"village_code": 1, "name": "WAPUNG SKUR", "district": "EAST JAINTIA HILLS", "block": "WAPUNG"},
            {"village_code": 2, "name": "WAPUNG SHNONG", "district": "EAST JAINTIA HILLS", "block": "WAPUNG"}])
    monkeypatch.setattr(p, "resolve_village", _lookalikes)
    out = asyncio.run(p.resolve_entities("What was the total MGNREGA expenditure in WAPUNG during 2023-24?",
                                         ["MGNREGA"]))
    assert out["resolved"].get("block") == "WAPUNG"


def test_block_that_is_also_a_village_still_asks(monkeypatch):
    _stub_resolver(monkeypatch, {"block": "Mawlai", "year": "2023-24"})

    async def _same(*a, **k):
        return er.Resolved("resolved", "village", "Mawlai", canonical=276564, display="Mawlai")
    monkeypatch.setattr(p, "resolve_village", _same)
    with pytest.raises(p.ClarificationNeeded):
        asyncio.run(p.resolve_entities("What was the total MGNREGA expenditure in Mawlai during 2023-24?",
                                       ["MGNREGA"]))


# ── Place gazetteer (D-059, PLACE_GAZETTEER) ───────────────────────────────
# User report 2026-10-21 "How many job cards in Mawphlang?": the level of a place
# comes from the database. Real rows of curated.dim_geography (2026-10-21).
_PLACES = {
    "MAWLAI": ((276564, "SHALLANG", "WEST KHASI HILLS"),),
    "LADMAWPHLANG": ((278534, "KHATARSHNONG LAITKROH", "EAST KHASI HILLS"),),
    "AMBARE ADING": ((274865, "DAMBO RONGJENG", "EAST GARO HILLS"),),
}


@pytest.fixture
def _gazetteer(monkeypatch):
    from app.config import settings
    names = dict(_VILLAGES)
    names.update({"LADMAWPHLANG": frozenset({"EAST KHASI HILLS"}), "MAWLAI": frozenset({"WEST KHASI HILLS"}),
                  "MAWLWAI": frozenset({"EAST KHASI HILLS"})})
    monkeypatch.setattr(er, "_village_names", names)
    monkeypatch.setattr(er, "_village_places", dict(_PLACES))
    monkeypatch.setattr(er, "_village_scheme_codes", {
        "MGNREGA": frozenset({276564, 278534, 274865}), "CM Elevate": frozenset({276564}),
        "PMAY-G": frozenset()})
    monkeypatch.setattr(settings, "PLACE_GAZETTEER", True)
    return settings


def test_an_exact_village_anywhere_is_not_offered_a_lookalike_block(_gazetteer, monkeypatch):
    # Live: "How many CM Elevate applications from Ladmawphlang?" offered the
    # MAWPHLANG block and constituency (Ladmawphlang has no CM Elevate rows).
    assert er.collides_across_dimensions("Ladmawphlang", "CM Elevate", village_hit=True) == {}
    monkeypatch.setattr(_gazetteer, "PLACE_GAZETTEER", False)
    assert "block" in er.collides_across_dimensions("Ladmawphlang", "CM Elevate", village_hit=True)


def test_a_typo_goes_to_the_clearly_closest_village(_gazetteer):
    # Live: "Ladmawplang" asked "Mawphlang block, constituency or the village Ladmawplang?".
    assert er.village_fuzzy("Ladmawplang")[0] == "LADMAWPHLANG"
    assert er.collides_across_dimensions("Ladmawplang", "MGNREGA", village_hit=True) == {}


def test_malwai_still_asks(_gazetteer):
    # 2026-09-15: "malwai" (typo of the Mawlai block) was answered as the village
    # Mawlwai. The village leads by only 9 points: still a question.
    assert set(er.collides_across_dimensions("malwai", "MGNREGA", village_hit=True)) >= {"block", "village"}


def test_settle_by_the_remembered_block_or_district(_gazetteer):
    dims = {"block": "MAWLAI", "assembly_constituency": "MAWLAI", "village": ""}
    assert list(p._c09_gazetteer_settle("Mawlai", dims, "MGNREGA", {"block": "SHALLANG"})) == ["village"]
    assert list(p._c09_gazetteer_settle("Mawlai", dims, "MGNREGA", {"block": "MAWLAI"})) == ["block"]
    assert list(p._c09_gazetteer_settle("Mawlai", dims, "MGNREGA", {"district": "WEST KHASI HILLS"})) == ["village"]
    assert "village" not in p._c09_gazetteer_settle("Mawlai", dims, "MGNREGA", {"district": "EAST KHASI HILLS"})
    assert p._c09_gazetteer_settle("Mawlai", dims, "MGNREGA", None) == dims   # no context: ask


def test_settle_drops_a_village_the_scheme_has_no_rows_for(_gazetteer):
    dims = {"block": "MAWLAI", "village": ""}
    assert p._c09_gazetteer_settle("Mawlai", dims, "PMAY-G", None) == {"block": "MAWLAI"}
    assert p._c09_gazetteer_settle("Mawlai", dims, "Focus Plus", None) == dims   # coverage unknown


def test_gate_takes_the_one_reading_the_chat_leaves(_gazetteer, monkeypatch):
    _stub_resolver(monkeypatch, {"block": "Mawlai", "year": "2023-24"})

    async def _village(*a, **k):
        return er.Resolved("resolved", "village", "Mawlai", canonical=276564, display="Mawlai")
    monkeypatch.setattr(p, "resolve_village", _village)
    out = asyncio.run(p.resolve_entities(
        "What was the total MGNREGA expenditure in Mawlai during 2023-24?", ["MGNREGA"],
        prior_resolved={"district": "WEST KHASI HILLS", "year_key": 2023}))
    assert out["resolved"].get("village_code") == 276564
    assert "the village" in out["question"]


def test_place_swap_reads_a_same_name_village_inside_the_chat(_gazetteer):
    # Live: after West Khasi Hills, "what about Mawlai?" became "Mawlai, East Khasi Hills".
    prev = _prev("How many households were employed under MGNREGA in West Khasi Hills in FY 2023-24?",
                 "WEST KHASI HILLS")
    out = p._place_swap_rewrite(prev, "what about Mawlai?")
    assert "Mawlai village" in out and "West Khasi Hills" in out and "East Khasi" not in out
    # After Shallang block the model rewrite wrote "Mawlai block".
    prev = NS(question="How many households were employed under MGNREGA in Shallang block in FY 2023-24?",
              route="data", schemes=["MGNREGA"], resolved_entities={"block": "SHALLANG", "year_key": 2023})
    assert p._place_swap_rewrite(prev, "what about Mawlai?") == \
        "How many households were employed under MGNREGA in Mawlai village in FY 2023-24?"


def test_match_places_levels_and_typos(_gazetteer):
    found = er.match_places("How many job cards in Ambare Ading in FY 2023-24?", is_ordinary=p._is_known_word)
    assert [(f["name"], f["levels"], f["fuzzy"]) for f in found] == [("AMBARE ADING", ["village"], False)]
    found = er.match_places("How many job cards in Ladmawplang in FY 2023-24?", is_ordinary=p._is_known_word)
    assert [(f["name"], f["fuzzy"]) for f in found] == [("LADMAWPHLANG", True)]
    assert found[0]["villages"] == _PLACES["LADMAWPHLANG"]
    assert er.match_places("show me the total for all years", is_ordinary=p._is_known_word) == []


def test_extractor_is_told_the_places_found(_gazetteer):
    hint = p._c07_places_hint("How many job cards in Ambare Ading in FY 2023-24?")
    assert '"ambare ading": village' in hint
    assert p._c07_places_hint("show me MGNREGA spend") == ""
    _gazetteer.PLACE_GAZETTEER = False
    assert p._c07_places_hint("How many job cards in Ambare Ading in FY 2023-24?") == ""


def test_level_chip_says_where_the_place_lies(_gazetteer):
    assert p._c07_chip_where("village", "Mawlai") == " (Shallang block, West Khasi Hills)"
    assert p._c07_chip_where("block", "MAWLAI") == " (East Khasi Hills)"


def test_an_ordinary_word_village_is_not_indexed(monkeypatch):
    # The index held a village named CENTRE: "houses near the centre" was a place.
    async def _rows(sql, params=None):
        if "DISTINCT village_code" in sql:
            return []
        return [{"n": "CENTRE", "d": "RI BHOI", "c": 1, "b": "UMSNING"},
                {"n": "AMBARE ADING", "d": "EAST GARO HILLS", "c": 274865, "b": "DAMBO RONGJENG"}]
    monkeypatch.setattr(er, "fetch_rows", _rows)
    monkeypatch.setattr(er, "_village_places", None)
    monkeypatch.setattr(er, "_village_scheme_codes", {})
    assert asyncio.run(er.load_village_names(force=True)) == 1
    assert er.place_mentions("how many houses near the centre") == {}
    assert er.village_places("Ambare Ading") == ((274865, "DAMBO RONGJENG", "EAST GARO HILLS"),)


def test_resolve_village_takes_the_clearly_closest_lookalike(_gazetteer, monkeypatch):
    async def _rows(sql, params=None):
        if "similarity" not in sql:
            return []
        if params[0] == "Ladmawplang":
            return [{"village_code": 278534, "lgd_village_name": "LADMAWPHLANG",
                     "lgd_district": "EAST KHASI HILLS", "lgd_block": "KHATARSHNONG LAITKROH"},
                    {"village_code": 2, "lgd_village_name": "LADMAWRENG",
                     "lgd_district": "EAST KHASI HILLS", "lgd_block": "MAWPHLANG"},
                    {"village_code": 3, "lgd_village_name": "LADMAWRONG",
                     "lgd_district": "RI BHOI", "lgd_block": "UMSNING"}]
        return [{"village_code": 4, "lgd_village_name": "PAWPHLANG",
                 "lgd_district": "SOUTH WEST KHASI HILLS", "lgd_block": "MAWKYRWAT"},
                {"village_code": 5, "lgd_village_name": "DOM MAWPHLANG",
                 "lgd_district": "EAST KHASI HILLS", "lgd_block": "SOHIONG"}]
    monkeypatch.setattr(er, "fetch_rows", _rows)
    r = asyncio.run(er.resolve_village("Ladmawplang"))
    assert (r.status, r.canonical) == ("resolved", 278534)
    assert asyncio.run(er.resolve_village("Mawphlang")).status == "ambiguous"   # a close race still asks


# ── KI-346: "give me for dalu" after a PMAY-G by-district answer (user, live 18:18) ──

def _block_chip(exc):
    """The block option's question of a block-or-constituency pause (the user's tap)."""
    labels = [o["label"] for o in exc.options]
    assert any("block" in l.lower() for l in labels) and any("constituency" in l.lower() for l in labels), labels
    return next(o["question"] for o in exc.options if "block" in o["label"].lower())


def test_a_block_the_extractor_called_a_village_is_the_block(_gazetteer, monkeypatch):
    # The 4B tagged Dalu a village; no village is named DALU, so the trigram
    # fallback asked "DALUAGRE or DALUGAON?". DALU is a block AND a constituency, and
    # PMAY-G records the constituency since D-096 (2026-10-30), so the level gate asks
    # block or constituency (D-059, as for MGNREGA) — never a village. The block chip
    # then resolves to the block.
    _stub_resolver(monkeypatch, {"district": "West Garo Hills", "village": "Dalu", "year": "2019-20"})
    with pytest.raises(p.ClarificationNeeded) as ei:
        asyncio.run(p.resolve_entities(
            "How many PMAY-G houses were completed in Dalu, West Garo Hills for FY 2019-20?", ["PMAY-G"],
            prior_resolved={"year_key": 2019}))
    out = asyncio.run(p.resolve_entities(_block_chip(ei.value), ["PMAY-G"], prior_resolved={"year_key": 2019}))
    assert out["resolved"].get("block") == "DALU"
    assert "village_code" not in out["resolved"] and not out["resolved"].get("assembly_constituency")


def test_a_stated_village_is_left_to_the_old_path(_gazetteer, monkeypatch):
    # "Dalu village" states the level: the guard does not run, and the result is
    # whatever the existing village branch decides. No village is named DALU; the name
    # is a block AND a constituency. MGNREGA re-reads it as the block (flag on or off).
    # PMAY-G is a village-grained scheme and records the constituency since D-096
    # (2026-10-30), so its village branch now offers block or constituency (D-059) with
    # the gazetteer on, and the block with it off — the same as before D-096 except that
    # the constituency reading is no longer dropped. Never a village, on any path.
    _stub_resolver(monkeypatch, {"village": "Dalu", "year": "2023-24"})     # a year both schemes hold

    def run(scheme):
        q = f"How many {scheme} houses were completed in Dalu village for FY 2023-24?"
        try:
            out = asyncio.run(p.resolve_entities(q, [scheme]))["resolved"]
            assert "village_code" not in out
            return {k: v for k, v in out.items() if k in ("block", "assembly_constituency")}
        except p.ClarificationNeeded as e:
            return ("pause", sorted(o["label"].split(" (")[0].lower() for o in e.options))
    on = (run("PMAY-G"), run("MGNREGA"))
    _gazetteer.PLACE_GAZETTEER = False
    off = (run("PMAY-G"), run("MGNREGA"))
    assert on == (("pause", ["the dalu assembly constituency", "the dalu c&rd block"]), {"block": "DALU"}), on
    assert off == ({"block": "DALU"}, {"block": "DALU"}), off


def test_place_swap_drops_a_by_district_breakdown(_gazetteer):
    prev = NS(question="How many PMAY-G houses were completed by district for FY 2019-20", route="data",
              schemes=["PMAY-G"], resolved_entities={"year_key": 2019})
    # DALU is a block AND a constituency: no level is guessed, so no district is
    # added (KI-348); the level gate decides (PMAY-G: block, MGNREGA: asks).
    assert p._place_swap_rewrite(prev, "give me for dalu") == \
        "How many PMAY-G houses were completed in Dalu for FY 2019-20?"
    assert p._c01_drop_coarser_breakdown("Expenditure by block for FY 2023-24", "village") == \
        "Expenditure for FY 2023-24"
    assert p._c01_drop_coarser_breakdown("Expenditure by village for FY 2023-24", "block") == \
        "Expenditure by village for FY 2023-24"


# ── KI-347: the user's PMAY-G chat, live 2026-10-21 18:33-18:37 ─────────────
# "Total PMAY-G amount released for FY 2023-24 for North Garo Hills" -> "in dalu"
# -> "in DADENGGIRI" -> "in Pakregre" -> "in dalu" -> "its block" -> "in dalu block".
def test_a_rejected_rewrite_of_a_place_falls_back_to_the_swap_not_the_fragment(_gazetteer):
    # The model wrote "Dadengiri" (rejected) and the bare "in DADENGGIRI" ran -> overview.
    prev = NS(question="Total PMAY-G amount released for FY 2023-24 in Dalu, West Garo Hills", route="data",
              schemes=["PMAY-G"], resolved_entities={"district": "WEST GARO HILLS", "block": "DALU",
                                                     "year_key": 2023})
    assert p._place_swap_rewrite(prev, "in DADENGGIRI") is None          # the model's turn first
    assert p._place_swap_rewrite(prev, "in DADENGGIRI", force=True) == \
        "Total PMAY-G amount released for FY 2023-24 in Dadenggiri block, West Garo Hills"


def test_a_rewrite_may_not_invent_a_level_word(_gazetteer):
    # "in dalu" -> "... in Dalu village ..."; DALU is a block + constituency only.
    assert p._c01_invented_level("in dalu", "What is the fund utilization for PMAY-G in Dalu village?") == \
        "DALU VILLAGE"
    assert p._c01_invented_level("in dalu", "Total PMAY-G amount released in Dalu block") is None
    assert p._c01_invented_level("in dalu village", "Total amount released in Dalu village") is None


def test_a_rewrite_of_a_place_may_not_change_the_measure(_gazetteer):
    prev = NS(question="Total PMAY-G amount released for FY 2023-24 in Dalu block, West Garo Hills")
    assert p._c01_place_only_drift(
        "in dalu block", prev,
        "What is the fund utilization for the PMAY-G scheme in the Dalu block of West Garo Hills for FY 2023-24?")
    assert not p._c01_place_only_drift(
        "in dalu block", prev, "What is the total PMAY-G amount released for FY 2023-24 in Dalu block, West Garo Hills?")
    # Not a place-only follow-up: the model may rephrase freely.
    assert not p._c01_place_only_drift("and the utilization?", prev, "What is the fund utilization in Dalu?")


def test_a_level_reply_resumes_a_village_pause():
    # "its block" to "“Dalu” corresponds to more than one village" went to the documents.
    assert p._c14_level_only_reply("its block", "Dalu") == "block"
    assert p._c14_level_only_reply("it's a block", "Dalu") == "block"
    assert p._c14_level_only_reply("Dalu is the block", "Dalu") == "block"
    assert p._c14_level_only_reply("constituency", "Dalu") == "assembly_constituency"
    assert p._c14_level_only_reply("the one in Tura", "Dalu") is None
    assert p._c14_level_only_reply("DALUGAON", "Dalu") is None
    assert p._c14_restate_level("Total PMAY-G amount released for FY 2023-24 in Dalu village under West Garo Hills",
                                "Dalu", "block") == \
        "Total PMAY-G amount released for FY 2023-24 in Dalu under West Garo Hills, the block, not another area type"


# ── KI-348: the user's MGNREGA / PMAY-G chat, live 2026-10-21 19:42-19:47 ──────
# "Total woman employment in Chokpot for MGNREGA, the block, not another area type
# for FY 2023-24" -> "Total sanctioned amount in Rasong." (RASONG is only a
# village, 278445, Mawkynrew block) was answered as "Rasong block", null, statewide.
_RASONG = {"RASONG": ((278445, "MAWKYNREW", "EAST KHASI HILLS"),)}


@pytest.fixture
def _rasong(_gazetteer, monkeypatch):
    monkeypatch.setattr(er, "_village_names", {**er._village_names, "RASONG": frozenset({"EAST KHASI HILLS"})})
    monkeypatch.setattr(er, "_village_places", {**_PLACES, **_RASONG})
    monkeypatch.setattr(er, "_village_code_names", {278445: "RASONG", 276564: "MAWLAI"})
    return _gazetteer


def test_a_chip_level_tail_is_not_carried_to_a_new_question():
    out = "Total sanctioned amount in Rasong for MGNREGA, the block, not another area type for FY 2023-24."
    assert p._c01_strip_chip_level(out, "Total sanctioned amount in Rasong.") == \
        "Total sanctioned amount in Rasong for MGNREGA for FY 2023-24."
    # The user's own chip text keeps it.
    chip = "Total woman employment in Chokpot for MGNREGA, the block, not another area type"
    assert p._c01_strip_chip_level(chip, chip) == chip
    assert p._c01_strip_chip_level("X in Mawlai, the village, not the block", "") == "X in Mawlai"


def test_a_stated_level_the_database_contradicts_does_not_win(_rasong, monkeypatch):
    _stub_resolver(monkeypatch, {"village": "Rasong", "year": "2023-24"})

    async def _ras(*a, **k):
        return er.Resolved("resolved", "village", "Rasong", canonical=278445, display="Rasong")
    monkeypatch.setattr(p, "resolve_village", _ras)
    out = asyncio.run(p.resolve_entities(
        "Total sanctioned amount in Rasong for MGNREGA, the block, not another area type for FY 2023-24.",
        ["MGNREGA"], prior_resolved={"block": "CHOKPOT", "year_key": 2023}))
    assert out["resolved"].get("village_code") == 278445
    assert out["resolved"].get("block") != "RASONG"


def test_a_block_mention_that_is_only_a_village_is_the_village(_rasong, monkeypatch):
    _stub_resolver(monkeypatch, {"block": "Rasong", "year": "2023-24"})

    async def _ras(*a, **k):
        return er.Resolved("resolved", "village", "Rasong", canonical=278445, display="Rasong")
    monkeypatch.setattr(p, "resolve_village", _ras)
    out = asyncio.run(p.resolve_entities("Total sanctioned amount in Rasong for FY 2023-24", ["PMAY-G"]))
    assert out["resolved"].get("village_code") == 278445


def test_a_constituency_mention_goes_to_the_one_reading_left(_gazetteer, monkeypatch):
    # "Chokpot" (block + AC), tagged AC by the extractor, asked "whole constituency or
    # part?" when PMAY-G had no constituency data. Since D-096 (2026-10-30) PMAY-G records
    # it, so the bare name is asked block or constituency (D-059) — the extractor's tag
    # alone never decides; the block chip gives the block.
    _stub_resolver(monkeypatch, {"assembly_constituency": "Chokpot", "year": "2023-24"})
    with pytest.raises(p.ClarificationNeeded) as ei:
        asyncio.run(p.resolve_entities(
            "What is the total sanctioned amount in Chokpot for PMAY-G for FY 2023-24?", ["PMAY-G"]))
    out = asyncio.run(p.resolve_entities(_block_chip(ei.value), ["PMAY-G"]))
    assert out["resolved"].get("block") == "CHOKPOT"
    assert not out["resolved"].get("assembly_constituency")


def test_a_named_district_settles_a_same_name_place(_gazetteer, monkeypatch):
    # "Mawlai, East Khasi Hills": the block is in EKH, the village in WKH.
    _stub_resolver(monkeypatch, {"district": "East Khasi Hills", "block": "Mawlai", "year": "2023-24"})

    async def _vil(*a, **k):
        return er.Resolved("resolved", "village", "Mawlai", canonical=276564, display="Mawlai")
    monkeypatch.setattr(p, "resolve_village", _vil)
    # The district rules the WKH village out; the EKH block and the Mawlai constituency are
    # both left (PMAY-G records the constituency since D-096), so it asks; the block chip
    # gives the block — never the village.
    with pytest.raises(p.ClarificationNeeded) as ei:
        asyncio.run(p.resolve_entities(
            "Total PMAY-G amount sanctioned in Mawlai, East Khasi Hills for FY 2023-24", ["PMAY-G"]))
    out = asyncio.run(p.resolve_entities(_block_chip(ei.value), ["PMAY-G"]))
    assert out["resolved"].get("block") == "MAWLAI"
    assert "village_code" not in out["resolved"]


def test_place_swap_of_a_same_name_place_names_no_district(_gazetteer):
    # "in Mawlai" after Chokpot became "Mawlai, East Khasi Hills" (the block's district).
    prev = NS(question="Total sanctioned amount in Chokpot, South Garo Hills under PMAY-G in FY 2023-24?",
              route="data", schemes=["PMAY-G"], resolved_entities={"district": "SOUTH GARO HILLS",
                                                                    "block": "CHOKPOT", "year_key": 2023})
    out = p._place_swap_rewrite(prev, "in Mawlai", force=True)
    assert "East Khasi Hills" not in out and "Mawlai" in out


def test_place_swap_removes_every_copy_of_the_old_place(_rasong):
    prev = NS(question="Total sanctioned amount in Rasong village under PMAY-G in Rasong village in FY 2023-24?",
              route="data", schemes=["PMAY-G"], resolved_entities={"village_code": 278445, "year_key": 2023})
    out = p._place_swap_rewrite(prev, "what about Chokpot?", force=True)
    assert "Rasong" not in out and "Chokpot" in out


def test_a_village_code_is_shown_by_name(_rasong):
    from app import context_manager
    from app.session_store import ConversationState
    assert p._scope_banner_place({"village_code": 278445}) == "Rasong village"
    assert "village=Rasong" in context_manager.build_state_block(ConversationState(scheme="PMAY-G", village="278445"))
    assert er.village_code_place(278445) == ("MAWKYNREW", "EAST KHASI HILLS")


# ── KI-349: the database-built place hierarchy sweep (tests/live_place_hierarchy_sweep.py) ──
def test_levels_read_the_catalogue_aliases_too(_gazetteer):
    # "Sohing" is an alias of the SOHIONG block AND the SOHING constituency.
    assert er.place_levels("Sohing") == {"block", "assembly_constituency"}
    assert er.place_levels("North Tura") == {"assembly_constituency"}


def test_the_hint_names_a_constituency_only_when_the_question_signals_one(_gazetteer):
    hint = p._c07_places_hint("How many PMAY-G houses were sanctioned in Dalu in FY 2023-24?")
    assert '"dalu": block' in hint and "constituency" not in hint
    hint = p._c07_places_hint("How many PMAY-G houses were sanctioned in Dalu constituency in FY 2023-24?")
    assert '"dalu": block or assembly constituency' in hint


def test_a_one_level_name_goes_to_its_level_whatever_the_slot(_gazetteer, monkeypatch):
    # The extractor put the constituency NORTH TURA in the block slot; the block
    # fuzzy-resolved to TURA (another area).
    _stub_resolver(monkeypatch, {"block": "North Tura", "year": "2023-24"})
    out = asyncio.run(p.resolve_entities(
        "What was the total MGNREGA expenditure in North Tura during FY 2023-24?", ["MGNREGA"]))
    assert out["resolved"].get("block") != "TURA"


def test_a_district_by_its_hq_alias_does_not_end_the_level_question(_gazetteer):
    # MAIRANG is a block and a constituency; the district (Eastern West Khasi
    # Hills) is only its HQ alias — it no longer ends the level question.
    dims = er.collides_across_dimensions("Mairang", "MGNREGA")
    assert "district" not in dims and set(dims) == {"block", "assembly_constituency"}
    assert er.collides_across_dimensions("West Garo Hills", "MGNREGA") == {}   # a plain district


def test_a_long_constituency_beats_the_block_inside_it(_gazetteer):
    # "North Tura" was read as the TURA block / district.
    assert er.place_mentions("houses sanctioned in North Tura in FY 2023-24") == \
        {"NORTH TURA": "assembly_constituency"}
    found = er.match_places("houses sanctioned in North Tura in FY 2023-24", is_ordinary=p._is_known_word)
    assert [(f["name"], f["levels"]) for f in found] == [("NORTH TURA", ["assembly_constituency"])]


def test_a_district_mention_that_is_no_district_moves(_gazetteer, monkeypatch):
    # The 4B tagged the constituency North Tura as a district -> "which area?".
    _stub_resolver(monkeypatch, {"district": "North Tura", "year": "2023-24"})
    try:
        out = asyncio.run(p.resolve_entities(
            "How many PMAY-G houses were sanctioned in North Tura in FY 2023-24?", ["PMAY-G"]))
        resolved = out["resolved"]
    except p.ClarificationNeeded as e:          # the constituency's own "whole or part?" step
        assert "constituency" in e.question.lower() and "north tura" in e.question.lower()
        return
    assert resolved.get("district") is None


def test_scheme_levels_ignore_another_schemes_block_and_an_hq_alias(_gazetteer):
    # JOWAI: a block only in CM Elevate's catalogue (urban body) and the HQ alias
    # of West Jaintia Hills -> for MGNREGA it is the constituency.
    assert p._c09_scheme_levels("Jowai", "MGNREGA") == {"assembly_constituency"}
    assert "block" in p._c09_scheme_levels("Jowai", "CM Elevate")
    assert p._c09_scheme_levels("West Garo Hills", "MGNREGA") == {"district"}


def test_a_stray_block_filter_the_resolver_never_chose_goes(_gazetteer):
    # "MGNREGA expenditure in Tura" resolved West Garo Hills; the 30B added
    # lgd_block = 'TURA' (no MGNREGA block) -> null "data doesn't cover".
    sql = ("SELECT SUM(total_exp) AS total_expenditure_lakh FROM curated.v_expenditure "
           "WHERE lgd_block = 'TURA' AND year_key = 2023 AND lgd_district = 'WEST GARO HILLS' LIMIT 1")
    out = p._stray_block_literal(["MGNREGA"], {"district": "WEST GARO HILLS", "year_key": 2023}, sql)
    assert "lgd_block" not in out and "lgd_district = 'WEST GARO HILLS'" in out
    real = sql.replace("'TURA'", "'DALU'")
    assert p._stray_block_literal(["MGNREGA"], {"district": "WEST GARO HILLS"}, real) == real
    assert p._stray_block_literal(["MGNREGA"], {"year_key": 2023}, sql) == sql          # no place pinned
    assert p._stray_block_literal(["CM Elevate"], {"district": "WEST GARO HILLS"}, sql) == sql


def test_the_real_name_beats_another_villages_alias(_gazetteer, monkeypatch):
    # dim_geography_alias maps "Nongspung B" to 277445 NONGSPUNG - A; the real
    # NONGSPUNG - B (277444) missed the exact match on its hyphen.
    monkeypatch.setattr(er, "_village_places", {**_PLACES, "NONGSPUNG B": (
        (277444, "UMLING", "RI BHOI"), (277445, "UMLING", "RI BHOI")),
        "NONGSPUNG A": ((277445, "UMLING", "RI BHOI"),)})
    monkeypatch.setattr(er, "_village_code_names", {277444: "NONGSPUNG - B", 277445: "NONGSPUNG - A"})
    row = {277444: {"village_code": 277444, "lgd_village_name": "NONGSPUNG - B", "lgd_district": "RI BHOI",
                    "lgd_block": "UMLING"},
           277445: {"village_code": 277445, "lgd_village_name": "NONGSPUNG - A", "lgd_district": "RI BHOI",
                    "lgd_block": "UMLING"}}

    async def _rows(sql, params=None):
        if "ANY($1" in sql:
            return [row[c] for c in params[0]]
        return [row[277445]]                       # the exact query: only the alias row
    monkeypatch.setattr(er, "fetch_rows", _rows)
    r = asyncio.run(er.resolve_village("Nongspung B"))
    assert (r.status, r.canonical) == ("resolved", 277444)


# ── KI-350: MGNREGA has no sanctioned amount (user chat 2026-10-21 19:44) ────
def test_mgnrega_sanctioned_amount_is_explained_with_an_expenditure_chip():
    e = p._mgnrega_sanction_clarification("Total sanctioned amount in Rasong for MGNREGA for FY 2023-24.")
    assert e.rule == "column-not-held" and "no sanctioned amount" in e.question
    assert e.options == [{"label": "Total expenditure instead",
                          "question": "Total expenditure in Rasong for MGNREGA for FY 2023-24?"}]
    assert p._MG_SANCTION_REQUESTED.search("total sanctioned amount in Rasong")
    assert not p._MG_SANCTION_REQUESTED.search("total expenditure in Rasong")


def test_a_scheme_reply_to_a_not_held_pause_continues_the_paused_question():
    prev = NS(question="Total woman employment in Chokpot for MGNREGA for FY 2023-24", route="data",
              schemes=["MGNREGA"], resolved_entities={"block": "CHOKPOT"})
    paused = "Total sanctioned amount in Rasong for MGNREGA for FY 2023-24."
    t = p._paused_thread_antecedent("in pmay", paused, prev, rule="column-not-held")
    assert t is not None and t.question == paused
    # Other pauses keep the old rule (a reply naming a scheme is its own question).
    assert p._paused_thread_antecedent("in pmay", paused, prev, rule="entity-ambiguous") is None


def test_the_gazetteer_fills_a_place_the_extractor_dropped(_gazetteer, monkeypatch):
    _stub_resolver(monkeypatch, {"year": "2023-24"})

    async def _amb(*a, **k):
        return er.Resolved("resolved", "village", "Ambare Ading", canonical=274865, display="Ambare Ading")
    monkeypatch.setattr(p, "resolve_village", _amb)
    out = asyncio.run(p.resolve_entities("How many PMAY-G houses were sanctioned in Ambare Ading in FY 2023-24?",
                                         ["PMAY-G"]))
    assert out["resolved"].get("village_code") == 274865


def test_chat_district_not_carried_onto_a_village_in_another_district(_gazetteer, monkeypatch):
    # "in Pakregre" after a West Garo Hills block: PAKREGRE is in East Garo Hills only,
    # and the answer was labelled "West Garo Hills district".
    monkeypatch.setattr(er, "_village_places", {**_PLACES, "PAKREGRE": ((274885, "DAMBO RONGJENG", "EAST GARO HILLS"),)})
    _stub_resolver(monkeypatch, {"village": "Pakregre", "year": "2023-24"})

    async def _pak(*a, **k):
        return er.Resolved("resolved", "village", "Pakregre", canonical=274885, display="Pakregre")
    monkeypatch.setattr(p, "resolve_village", _pak)
    out = asyncio.run(p.resolve_entities(
        "Total PMAY-G amount released for FY 2023-24 in Pakregre village", ["PMAY-G"],
        prior_resolved={"district": "WEST GARO HILLS", "block": "DADENGGIRI", "year_key": 2023}))
    assert out["resolved"].get("village_code") == 274885
    assert out["resolved"].get("district") == "EAST GARO HILLS"
    assert out["resolved"].get("block") != "DADENGGIRI"


# ── Bare villages in a running chat (user, live 2026-10-21 ~21:15) ──────────
# MGNREGA, West Garo Hills, all years, five questions, then villages named
# without "village". Real rows of curated.dim_geography (2026-10-21).
_WGH = {
    "KOTCHUGRE": ((272805, "BATABARI", "WEST GARO HILLS"), (273369, "TIKRIKILLA", "WEST GARO HILLS")),
    "DUGALGRE": ((273145, "DADENGGIRI", "WEST GARO HILLS"),),
    "PAMILA": ((273317, "TIKRIKILLA", "WEST GARO HILLS"),),
}


@pytest.fixture
def _wgh(_gazetteer, monkeypatch):
    monkeypatch.setattr(er, "_village_names", {**er._village_names,
                                              **{k: frozenset({"WEST GARO HILLS"}) for k in _WGH}})
    monkeypatch.setattr(er, "_village_places", {**_PLACES, **_WGH})
    monkeypatch.setattr(er, "_village_code_names", {273317: "PAMILA", 273145: "DUGALGRE", 273567: "CHIWATGRE"})


def test_a_village_in_memory_is_named_not_coded(_wgh):
    # "Shall we carry on with MGNREGA in 273567?" after a greeting.
    from app import conversation_replies, topic_memory
    from app.session_store import ConversationState, Session
    st = ConversationState(scheme="MGNREGA", district="WEST GARO HILLS", block="RONGRAM", village="273567")
    assert topic_memory.place_words(st) == "Chiwatgre village"
    assert topic_memory.place_words(st.to_dict()) == "Chiwatgre village"
    s = Session(session_id="t", user_id=None, created=0, last_seen=0, state=st)
    assert conversation_replies._topic(s)[0] == "MGNREGA in Chiwatgre village"


def test_another_village_typed_at_a_village_pause_is_asked_for(_wgh):
    # "job cards in Kotchugre" paused (two Kotchugre villages); "Dugalgre" asked
    # the Kotchugre question again.
    from app.session_store import ConversationState
    st = ConversationState(scheme="MGNREGA", district="WEST GARO HILLS", year_all=True)
    paused = "How many job cards were issued under MGNREGA in Kotchugre in West Garo Hills across all financial years?"
    out = p._c14_pause_place_switch("Dugalgre", paused, "Kotchugre", st)
    assert out and "Dugalgre" in out and "Kotchugre" not in out and "job cards" in out
    # A pick among the Kotchugre villages is still a pick.
    assert p._c14_pause_place_switch("Batabari", paused, "Kotchugre", st) is None
    assert p._c14_pause_place_switch("the Kotchugre village", paused, "Kotchugre", st) is None
    assert p._c14_pause_place_switch("West Garo Hills", paused, "Kotchugre", st) is None


def test_a_restored_question_is_the_turns_question():
    # "go back to the first question" then "Boldoreng": the turn was recorded as
    # the typed words, so the next place lost the measure.
    from types import SimpleNamespace
    q = "How many job cards were issued under MGNREGA in West Garo Hills across all financial years?"
    s = SimpleNamespace(turn_context={"restored_question": q})
    result = {"route": "data"}
    p._mark_context_dependent(result, s, raw_question=q, followup=False, plan=None, scope_resumed=False)
    assert result["rewritten_question"] == q and result["context_dependent"] is True


def test_a_village_known_by_code_is_not_labelled_its_district(_wgh):
    # "200 household-years … in Pamila village. This is the figure for West Garo Hills district".
    answer = ("Under MGNREGA, across all financial years in Pamila village, the recorded total is 200 "
              "household-years of employment.")
    result = {"route": "data", "schemes": ["MGNREGA"], "answer": answer, "rows": [{"household_years": 200}],
              "resolved_entities": {"district": "WEST GARO HILLS", "village_code": 273317}}
    p._finish_data_result(result)
    assert "West Garo Hills" not in result["answer"]
    # Two blocks by code beside their district: not "the figure for West Garo Hills district" either.
    result = {"route": "data", "schemes": ["MGNREGA"], "answer": "The total is 5 households.",
              "rows": [{"households": 5}],
              "resolved_entities": {"district": "WEST GARO HILLS", "block_list": ["DALU", "RONGRAM"]}}
    p._finish_data_result(result)
    assert "West Garo Hills" not in result["answer"]


def test_a_place_swap_drops_the_breakdown_verb():
    q = "How many households were provided employment under MGNREGA in West Garo Hills across all financial years, shown by block?"
    assert p._c01_drop_coarser_breakdown(q, "village").endswith("across all financial years?")

"""Metric catalogue coverage, 14 Nov 2026 (offline): questions the no-model gold bank sent to model-written SQL
because the catalogue declined them on a word that is not something more to compute.

  - an approved wording keeps its own words ("total disbursement": "disbursement" is noise only in display names)
  - a place typed by its catalogue alias ("WGH", "E Khasi Hills") is the place, not an extra word
  - "fewest" / "greatest" rank; "went" / "gone" are not a measure
"""
from __future__ import annotations

from app import entity_resolver as er
from app import metric_catalog as mc
from app import pipeline as p


def test_approved_wording_keeps_disbursement():
    assert mc._phrase("total disbursement", mc._APPROVED_NOISE) == ("disbursement",)
    assert mc._phrase("total disbursement") == ()                 # display names: still noise
    assert mc._phrase("CM Elevate Disbursement -- total paid out") == ("paid", "out")


def test_alias_words_of_a_pinned_place(monkeypatch):
    monkeypatch.setattr(er, "_catalog", {"MGNREGA": {
        "district": [{"canonical": "WEST GARO HILLS", "aliases": ["WGH", "W Garo Hills"]},
                     {"canonical": "EAST KHASI HILLS", "aliases": ["EKH", "E Khasi Hills"]}],
        "block": []}})
    got = p._c16_alias_words({"west", "garo", "hills"})
    assert {"wgh", "w"} <= got and "ekh" not in got
    assert p._c16_alias_words(set()) == set()


def test_alias_is_not_an_extra_word(monkeypatch):
    monkeypatch.setattr(er, "_catalog", {"MGNREGA": {
        "district": [{"canonical": "WEST GARO HILLS", "aliases": ["WGH"]}], "block": []}})
    ent = {"resolved": {"district": "WEST GARO HILLS"}, "display": {"district": "West Garo Hills"}}
    assert "wgh" not in p._c16_extra_words("MGNREGA persondays WGH 2023-24", ["MGNREGA"], ent, frozenset(), frozenset())
    assert "wgh" in p._c16_extra_words("MGNREGA persondays WGH 2023-24", ["MGNREGA"], {}, frozenset(), frozenset())


def test_fewest_is_a_ranking():
    s = p._c16_shape("Which district has the fewest Focus Plus beneficiaries?", {})
    assert s and s["qtype"] == "ranking" and s["order"] == "asc" and s["group"] == "district"
    s = p._c16_shape("Which block has the greatest MGNREGA person-days?", {})
    assert s and s["qtype"] == "ranking" and s["order"] == "desc"


def test_went_is_not_a_measure_word():
    assert "went" not in p._c16_extra_words("How much Focus Legacy money went to Mairang block?", ["Focus Legacy"],
                                            {"resolved": {"block": "MAIRANG"}, "display": {"block": "Mairang"}},
                                            frozenset(), frozenset({"money"}))

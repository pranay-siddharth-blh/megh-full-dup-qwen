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


# ── a constituency filter through the cross-scheme registry's column (same day) ──
def _m(scheme, base, cols):
    return mc.Metric(key="k", scheme=scheme, display_name="k", expression="SUM(x)", base_object=base, unit="",
                     notes="", alias="k", phrases=(), columns=frozenset(cols))


def test_constituency_column_comes_from_the_registry():
    emp = _m("MGNREGA", "curated.v_employment", {"x", "assembly_constituency_name", "ac_name", "year_key"})
    assert mc.constituency_column(emp) == "UPPER(assembly_constituency_name)"     # the view's own column
    exp = _m("MGNREGA", "curated.v_expenditure", {"x", "ac_name", "year_key"})
    assert mc.constituency_column(exp) == "UPPER(ac_name)"                       # the scheme's column
    fp = _m("Focus Plus", "curated.v_focus_plus", {"x", "ac_name"})
    assert mc.constituency_column(fp) is None                                    # constituency: null in the registry
    assert mc.constituency_column(_m("MGNREGA", "curated.v_expenditure", {"x"})) is None   # view lacks the column


def test_build_filters_a_constituency(monkeypatch):
    monkeypatch.setitem(mc._state, "no_block_level", frozenset())
    emp = _m("MGNREGA", "curated.v_employment", {"x", "assembly_constituency_name", "year_key"})
    sql, params, shown = mc.build(emp, {"assembly_constituency": "Mawsynram", "year_key": [2024]})
    assert "UPPER(assembly_constituency_name) = UPPER($" in sql and "MAWSYNRAM" in params and 2024 in params
    assert "'MAWSYNRAM'" in shown
    fp = _m("Focus Plus", "curated.v_focus_plus", {"x", "ac_name"})
    assert mc.build(fp, {"assembly_constituency": "Mawsynram"}) is None


def test_constituency_only_with_a_total_or_years():
    f = {"assembly_constituency": "MAWSYNRAM"}
    assert p._c16_shape("MGNREGA person-days in Mawsynram constituency", f)["qtype"] == "total"
    assert p._c16_shape("Which block in Mawsynram constituency has the most person-days", f) is None
    assert p._c16_shape("MGNREGA person-days in Mawsynram constituency by district", f) is None

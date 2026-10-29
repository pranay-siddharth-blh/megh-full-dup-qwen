"""B4 (RAG plan, prompt pruning) — measured live 2026-10-27: every scheme's SQL
prompt was 15.9k-17.1k tokens against the 15,360 budget, the catalogue alone
~8.5k (6k of it column notes, a third on shared dim_* / v_cross_scheme_* tables).
The priority compressor then cut the worked examples 5 -> 1 and dropped the view /
join notes on every question. Now the catalogue shrinks FIRST: a shared table's
column notes stay only when the question touches that table or column; every
scheme-specific note, table note, term and metric stays. After: 12.7k-14.2k, the
5 examples kept.

OFFLINE: calls the real catalog_block and build_sql_prompt.
    .venv/Scripts/python.exe -m pytest tests/test_prompt_pruning_b4_2026_10_27.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_budget, prompt_builder, schema_introspect  # noqa: E402
from app.config import settings  # noqa: E402


def _col(table, column, note):
    return {"table_schema": "curated", "table_name": table, "column_name": column, "description": None,
            "data_quality_note": note, "unit": None, "sample_values": None}


@pytest.fixture
def catalog(monkeypatch):
    saved = dict(schema_introspect._cache)
    monkeypatch.setattr(schema_introspect, "_cache", {**saved, "loaded": True, "tables": [], "glossary": [],
                                                      "metrics": [], "join_rules": {}, "coverage": {},
                                                      "denied": set(), "columns": [
        _col("v_employment", "person_days", "MGNREGA TRAP person_days"),
        _col("v_employment", "households_employed", "MGNREGA TRAP households"),
        _col("dim_geography", "ac_name", "SHARED NOTE constituency name"),
        _col("v_cross_scheme_village_coverage", "schemes_present", "SHARED NOTE coverage"),
        _col("v_place_names", "alias", "SHARED NOTE alias"),
    ]})
    return schema_introspect._cache


def test_without_focus_the_block_is_unchanged(catalog):
    full = schema_introspect.catalog_block(["MGNREGA"])
    assert full == schema_introspect.catalog_block(["MGNREGA"], focus=None)
    assert full.count("SHARED NOTE") == 3 and full.count("MGNREGA TRAP") == 2


def test_focus_keeps_scheme_notes_and_only_the_shared_notes_the_question_touches(catalog):
    q = "person-days in Ri Bhoi in FY 2023-24"
    out = schema_introspect.catalog_block(["MGNREGA"], focus=q)
    assert out.count("MGNREGA TRAP") == 2                  # every scheme-specific trap stays
    assert "SHARED NOTE" not in out
    out = schema_introspect.catalog_block(["MGNREGA"], focus="person-days by assembly constituency, ac name")
    assert "SHARED NOTE constituency name" in out and "SHARED NOTE coverage" not in out
    out = schema_introspect.catalog_block(["MGNREGA"], focus="villages with coverage in both schemes")
    assert "SHARED NOTE coverage" in out


def test_generic_words_do_not_keep_every_shared_note(catalog):
    # "district" / "year" / "village" are in nearly every question
    out = schema_introspect.catalog_block(["MGNREGA"], focus="total for the district and village in the year")
    assert "SHARED NOTE" not in out


def test_over_budget_the_catalogue_shrinks_before_the_examples(catalog, monkeypatch):
    catalog["columns"] += [_col("dim_geography", f"filler{i}", "SHARED NOTE " + "x" * 580) for i in range(60)]
    q = "How many person-days in FY 2023-24?"
    er = {"resolved": {"year_key": 2023}}
    full = prompt_builder.build_sql_prompt(q, ["MGNREGA"], er)
    # a budget that the full prompt exceeds but the focused one fits
    focused_cat = schema_introspect.catalog_block(["MGNREGA"], focus=q)
    budget = context_budget.approx_tokens(full) - context_budget.approx_tokens(
        schema_introspect.catalog_block(["MGNREGA"])) + context_budget.approx_tokens(focused_cat) + 50
    monkeypatch.setattr(settings, "PROMPT_BUDGET_SQL_TOKENS", budget)
    pruned = prompt_builder.build_sql_prompt(q, ["MGNREGA"], er)
    assert "filler" not in pruned and "MGNREGA TRAP person_days" in pruned
    # the worked examples are the same as in the unpruned prompt
    ex = full[full.find("EXAMPLES"):full.find("COMMON MISTAKES") if "COMMON MISTAKES" in full else None]
    assert ex.strip() and ex in pruned

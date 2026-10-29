"""The SQL prompt's data figures come from megh_db, not from typed text (2026-10-29: the
prompt said CM Elevate has 8,867 records while megh_db held 8,948, and Focus Legacy said
both "11,906 groups" and "~11,904"). app/data_facts.py reads them; schema_context carries
[[name]] tokens. These tests drive the real refresh() and build_schema_context()."""
import asyncio

import pytest

from app import data_facts, schema_context, sql_ast

_PRIVACY = {"fact_focus_legacy_disbursement", "bridge_pg_bank_history", "fact_cm_elevate_disbursement"}


def _all_columns() -> set[str]:
    out = set()
    for sql in data_facts._QUERIES.values():
        out.update(sql_ast.output_names(sql))
    return out


def _token_names(text: str) -> list[str]:
    names, i = [], 0
    while (j := text.find("[[", i)) >= 0:
        k = text.find("]]", j)
        names.append(text[j + 2:k])
        i = k + 2
    return names


@pytest.fixture(autouse=True)
def _fresh_facts():
    saved = dict(data_facts._current)
    data_facts._current.clear()
    yield
    data_facts._current.clear()
    data_facts._current.update(saved)


def test_every_token_in_the_prompt_is_a_known_fact():
    src = open(schema_context.__file__, encoding="utf-8").read()
    body = src.split('"""', 2)[2]          # past the module docstring, which mentions [[name]]
    unknown = sorted({n for n in _token_names(body) if n not in data_facts.FACTS})
    assert not unknown, unknown


def test_before_the_first_read_the_prompt_shows_the_typed_figures():
    ctx = schema_context.build_schema_context(list(schema_context.SCHEME_CATALOG))
    assert "[[" not in ctx
    assert "COUNT(*) gives 8,867 records against 8,840 applications" in ctx
    assert "11,906 groups carry only 10,678" in schema_context.available_metrics_text(["Focus Legacy"])


def test_queries_parse_read_only_curated_objects_and_never_a_privacy_table():
    for key, sql in data_facts._QUERIES.items():
        assert sql_ast.is_parseable(sql), key
        assert sql.lstrip().upper().startswith("SELECT"), key
        assert not (sql_ast.tables(sql) & _PRIVACY), key


def test_every_formatter_reads_only_columns_the_queries_return():
    cols = _all_columns()
    row = {c: 7 for c in cols}
    row.update(fp_years=["2022-23", "2025-26"], cme_dup_split="5 Piggery",
               fl_date_min="2021-08-31", fl_date_max="2026-03-31")
    for name, (_default, fmt) in data_facts.FACTS.items():
        fmt(row)                            # KeyError = a formatter names a column no query returns


def _fake_db(overrides: dict, fail: set = frozenset()):
    cols = _all_columns()

    async def fetch(sql, params=None):
        key = next(k for k, v in data_facts._QUERIES.items() if v == sql)
        if key in fail:
            raise OSError("network location cannot be reached")
        out = {}
        for c in sql_ast.output_names(sql):
            out[c] = overrides.get(c, 10)
        assert set(out) <= cols
        return [out]
    return fetch


def test_a_data_load_changes_the_prompt(monkeypatch):
    monkeypatch.setattr(data_facts, "fetch_rows_readonly",
                        _fake_db({"cme_records": 8948, "cme_apps": 8921, "fp_years": ["2022-23", "2025-26"],
                                  "fl_date_min": "2021-08-31", "fl_date_max": "2026-03-31"}))
    changed = asyncio.run(data_facts.refresh())
    assert changed["cme_records"] == ("8,867", "8,948")
    ctx = schema_context.build_schema_context(["CM Elevate"])
    assert "COUNT(*) gives 8,948 records against 8,921 applications" in ctx
    assert "8,867" not in ctx
    assert data_facts.status()["as_of"] and not data_facts.status()["errors"]


def test_a_failed_read_keeps_the_last_good_figures(monkeypatch):
    monkeypatch.setattr(data_facts, "fetch_rows_readonly", _fake_db({"cme_records": 8948}))
    asyncio.run(data_facts.refresh())
    monkeypatch.setattr(data_facts, "fetch_rows_readonly", _fake_db({}, fail=set(data_facts._QUERIES)))
    asyncio.run(data_facts.refresh())
    assert data_facts.value("cme_records") == "8,948"
    assert len(data_facts.status()["errors"]) == len(data_facts._QUERIES)


def test_focus_plus_years_and_gaps_follow_the_data():
    assert data_facts._fy_list(["2025-26", "2022-23"]) == "FY 2022-23 and FY 2025-26"
    assert data_facts._fy_gaps(["2022-23", "2025-26"]) == " (no FY 2023-24, FY 2024-25 between)"
    assert data_facts._fy_gaps(["2022-23", "2023-24"]) == ""

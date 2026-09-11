"""
Chart-type selection (app/chart_spec.py, node 5.14) — pure-logic checks, no
DB, no model gateway. Same stance as test_security.py / test_findings.py /
test_defaults_engine.py: `python tests/test_chart_spec.py`, exit code 0 =
all pass.

Covers tasks.md group 3's acceptance scenarios (task 3.4 a-j), each keyed
to the exact `web/ai_query.html` `buildAnalytics()` branch it matches (see
`specs/chart-spec/spec.md`): (a) single-dim/single-metric -> bar;
(b) time-series -> line; (c) single-row/2+-numeric -> kpi_bar, and a
non-1-row result with the same column shape does NOT select kpi_bar (the
client only honors that hint for a 1-row result, ai_query.html:2040);
(d) 1-label/2+-numeric -> grouped_bar; (e) 2-label/1-numeric -> stacked,
and a 1-label variant of the same data does NOT (falls back to a
bar/doughnut/line default instead — matches buildAnalytics's own
lblCols.length >= 2 gate, ai_query.html:2126); (f) small (<=6 row)
non-time categorical -> doughnut; (g) single-scalar -> None;
(h) >2-grouping-dimension -> None; (i) no-numeric-column -> None;
(j) every value is JSON-serializable and app/chart_spec.py imports no
charting/visualization library.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chart_spec import select_chart_type  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# ── (a) single-dimension, single-metric -> bar ──────────────────────────────
print("1. SINGLE-DIMENSION, SINGLE-METRIC RESULT -> bar")

rows_a = [
    {"district": "EAST KHASI HILLS", "expenditure": 500},
    {"district": "WEST GARO HILLS", "expenditure": 900},
    {"district": "RI BHOI", "expenditure": 100},
    {"district": "JAINTIA HILLS", "expenditure": 300},
    {"district": "SOUTH GARO HILLS", "expenditure": 200},
    {"district": "WEST KHASI HILLS", "expenditure": 150},
    {"district": "EAST GARO HILLS", "expenditure": 250},
    {"district": "RIBHOI 2", "expenditure": 175},
]
check("8-row, 1-dim/1-metric, no time signal -> bar",
      select_chart_type(rows_a, "expenditure by district") == "bar",
      str(select_chart_type(rows_a, "expenditure by district")))

# ── (b) time-series -> line ─────────────────────────────────────────────────
print("2. TIME-SERIES RESULT -> line")

rows_b_col = [
    {"year_key": "2021-22", "person_days": 1000},
    {"year_key": "2022-23", "person_days": 1500},
    {"year_key": "2023-24", "person_days": 1800},
]
check("temporal column name (year_key) -> line",
      select_chart_type(rows_b_col, "person days") == "line",
      str(select_chart_type(rows_b_col, "person days")))

rows_b_q = [
    {"period": "Q1", "amount": 500},
    {"period": "Q2", "amount": 700},
    {"period": "Q3", "amount": 400},
]
check("question text mentions trend -> line even without a dedicated date column",
      select_chart_type(rows_b_q, "what is the trend in amount?") == "line",
      str(select_chart_type(rows_b_q, "what is the trend in amount?")))

# ── (c) single-row/2+-numeric -> kpi_bar; non-1-row same shape does NOT ────
print("3. SINGLE-ROW, 2+-NUMERIC-COLUMN RESULT -> kpi_bar (only for exactly 1 row)")

rows_c_one = [{"paid": 800, "pending": 200}]
check("1 row, 2 numeric cols -> kpi_bar",
      select_chart_type(rows_c_one, "paid vs pending") == "kpi_bar",
      str(select_chart_type(rows_c_one, "paid vs pending")))

rows_c_many = [
    {"district": "EAST KHASI HILLS", "paid": 800, "pending": 200},
    {"district": "WEST GARO HILLS", "paid": 600, "pending": 100},
]
result_c_many = select_chart_type(rows_c_many, "paid vs pending")
check("2 rows, same paid/pending column shape -> NOT kpi_bar",
      result_c_many != "kpi_bar", str(result_c_many))
check("2 rows, 1 label + 2 numeric cols -> grouped_bar instead",
      result_c_many == "grouped_bar", str(result_c_many))

rows_c_scalar = [{"total": 42}]
check("1 row, exactly 1 numeric col (single scalar) -> None",
      select_chart_type(rows_c_scalar, "total") is None,
      str(select_chart_type(rows_c_scalar, "total")))

# ── (d) one label column, 2+ numeric columns -> grouped_bar ─────────────────
print("4. ONE LABEL COLUMN, 2+ NUMERIC MEASURE COLUMNS -> grouped_bar")

rows_d = [
    {"district": "EAST KHASI HILLS", "sanctioned": 500, "completed": 300},
    {"district": "WEST GARO HILLS", "sanctioned": 700, "completed": 650},
    {"district": "RI BHOI", "sanctioned": 200, "completed": 180},
]
check("1 label col + 2 numeric cols -> grouped_bar",
      select_chart_type(rows_d, "sanctioned vs completed by district") == "grouped_bar",
      str(select_chart_type(rows_d, "sanctioned vs completed by district")))

# ── (e) two label columns, exactly 1 numeric column -> stacked ─────────────
print("5. TWO LABEL COLUMNS, EXACTLY 1 NUMERIC COLUMN -> stacked")

rows_e = [
    {"district": "EAST KHASI HILLS", "batch": "93K", "amount": 500},
    {"district": "EAST KHASI HILLS", "batch": "12.5K", "amount": 200},
    {"district": "WEST GARO HILLS", "batch": "93K", "amount": 400},
    {"district": "WEST GARO HILLS", "batch": "12.5K", "amount": 150},
]
check("2 label cols + 1 numeric col -> stacked",
      select_chart_type(rows_e, "amount by district and batch") == "stacked",
      str(select_chart_type(rows_e, "amount by district and batch")))

rows_e_one_label = [
    {"district": "EAST KHASI HILLS", "amount": 500},
    {"district": "WEST GARO HILLS", "amount": 400},
]
result_e_one_label = select_chart_type(rows_e_one_label, "amount by district")
check("1-label-column variant of similar data -> NOT stacked",
      result_e_one_label != "stacked", str(result_e_one_label))
check("1-label-column variant falls back to a normal default (bar/doughnut/line)",
      result_e_one_label in ("bar", "doughnut", "line"), str(result_e_one_label))

# ── (f) small (<=6 row) non-time categorical -> doughnut ───────────────────
print("6. SMALL (<=6 ROW) NON-TIME CATEGORICAL RESULT -> doughnut")

rows_f = [
    {"district": "EAST KHASI HILLS", "count": 5},
    {"district": "WEST GARO HILLS", "count": 3},
    {"district": "RI BHOI", "count": 2},
]
check("3-row, 1-dim/1-metric, no time signal -> doughnut",
      select_chart_type(rows_f, "count by district") == "doughnut",
      str(select_chart_type(rows_f, "count by district")))

# ── (g) single-scalar result -> None ────────────────────────────────────────
print("7. SINGLE-SCALAR RESULT -> None")

check("1 row, 1 numeric value, no grouping dimension -> None",
      select_chart_type([{"total_person_days": 12345}], "total person days") is None)

# ── (h) more than 2 grouping dimensions -> None ─────────────────────────────
print("8. MORE THAN 2 GROUPING DIMENSIONS -> None")

rows_h = [
    {"district": "EAST KHASI HILLS", "block": "Mylliem", "village": "V1", "amount": 100},
    {"district": "WEST GARO HILLS", "block": "Selsella", "village": "V2", "amount": 200},
]
check("3 label cols + 1 numeric col -> None (not a guess)",
      select_chart_type(rows_h, "amount by district, block, village") is None,
      str(select_chart_type(rows_h, "amount by district, block, village")))

# ── (i) no numeric column -> None ───────────────────────────────────────────
print("9. NO NUMERIC COLUMN -> None")

rows_i = [
    {"district": "EAST KHASI HILLS", "status": "Active"},
    {"district": "WEST GARO HILLS", "status": "Inactive"},
]
check("no numeric column at all -> None",
      select_chart_type(rows_i, "district status") is None,
      str(select_chart_type(rows_i, "district status")))

check("empty rows -> None", select_chart_type([], "anything") is None)

# ── name-excluded columns (year/id/key/code) are never treated as numeric ──
print("10. NAME-EXCLUDED COLUMNS (year/_key/_id/_code) NEVER COUNT AS A METRIC")

rows_year = [
    {"year": 2021, "district": "EAST KHASI HILLS", "amount": 500},
    {"year": 2022, "district": "WEST GARO HILLS", "amount": 700},
    {"year": 2023, "district": "RI BHOI", "amount": 200},
]
result_year = select_chart_type(rows_year, "amount by year and district")
check("a bare numeric 'year' column is excluded from the numeric-column count "
      "(2 label cols + 1 numeric col -> stacked, not grouped_bar)",
      result_year == "stacked", str(result_year))

# ── (j) JSON-serializable, no charting-library import ──────────────────────
print("11. JSON-SERIALIZABLE, NO CHARTING-LIBRARY DEPENDENCY")

all_results = [
    select_chart_type(rows_a, "expenditure by district"),
    select_chart_type(rows_b_col, "person days"),
    select_chart_type(rows_c_one, "paid vs pending"),
    select_chart_type(rows_d, "sanctioned vs completed by district"),
    select_chart_type(rows_e, "amount by district and batch"),
    select_chart_type(rows_f, "count by district"),
    select_chart_type([{"total_person_days": 12345}], "total person days"),
    None,
]
for val in all_results:
    try:
        json.dumps({"chart_type": val})
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    check(f"chart_type={val!r} is JSON-serializable", ok)

_ALLOWED_VALUES = {"bar", "doughnut", "line", "grouped_bar", "stacked", "kpi_bar", None}
check("every produced value is in the closed vocabulary",
      all(v in _ALLOWED_VALUES for v in all_results), str(all_results))

_source = Path(__file__).resolve().parents[1] / "app" / "chart_spec.py"
_text = _source.read_text(encoding="utf-8")
_import_lines = [ln for ln in _text.splitlines() if re.match(r"^\s*(import|from)\s+\w", ln)]
_forbidden = re.compile(r"vega|altair|matplotlib|plotly|bokeh|d3\b", re.IGNORECASE)
_bad_imports = [ln for ln in _import_lines if _forbidden.search(ln)]
check("app/chart_spec.py imports no charting/visualization library",
      not _bad_imports, str(_bad_imports))
check("app/chart_spec.py has at least one import (sanity check the scan worked)",
      len(_import_lines) > 0, str(_import_lines))

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL CHART_SPEC CHECKS PASSED")

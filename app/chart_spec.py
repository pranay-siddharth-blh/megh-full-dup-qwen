"""
app/chart_spec.py — deterministic, no-model chart-type selection over an
already-executed query result (node 5.14): computes a `chart_type` string
and attaches it as the additive `chart_type` field in the `/api/query`
response.

**This module computes a value an existing consumer already reads, not a
new contract.** `web/ai_query.html` is a real, git-tracked, actively-mounted
frontend (served at `/ai-query` by `app/main.py`) whose `buildAnalytics()`
(`ai_query.html:2037-2165`) already reads `response.chart_type`
(`ai_query.html:2479`) and already implements full client-side rendering
for a closed six-value vocabulary: `bar`, `doughnut`, `line`,
`grouped_bar`, `stacked`, `kpi_bar`. `select_chart_type()` below computes
one of those six strings, or `None`. See `docs/baseline-audit.md` §3 item
10 and the corrected `openspec/changes/phase-4-clarification-defaults-charts/`
proposal/spec for the "no frontend exists" correction that established
this.

**Does NOT take `classify_intent` as an input**, despite proposal.md's
original wording. `classify_intent` (`pipeline.py:3135-3165`) is a binary
DATA/KNOWLEDGE router classifier; `select_chart_type()` is only ever
called from the DATA route's successful-result return (same scoping as
`findings.evaluate`), by which point that value is a constant `"DATA"` and
contributes no signal for distinguishing among the six chart types.
Selection is driven entirely by row count and column-role counts, plus a
question-text/column-name regex for the time-series case — matching what
`buildAnalytics()` itself already relies on client-side with no backend
intent field.

**Column-role inference is a local copy, not an import of
`findings.compute_result_stats`.** Same stance `app/findings.py` and
`app/premise_check.py` already document for their own local `_to_number`:
avoid a cross-module coupling for a small, stable piece of logic. Two
concrete reasons this needed to be its own logic rather than a call into
`compute_result_stats`, not just style:
  1. `compute_result_stats` returns `None` for a 0- or 1-row result (it
     has nothing to aggregate across) — but chart selection needs a
     working column classification for exactly the 1-row case, to decide
     `kpi_bar` vs `None`.
  2. `compute_result_stats` classifies numeric-ness per **cell**, so a
     column with mixed numeric/non-numeric values across rows can end up
     partially in both its `numeric` and `dimensions` buckets. For chart
     selection that's the wrong question — a column is only useful as a
     bar/line data series if *every* value in it is a number, otherwise
     it belongs on the label axis. So `_column_roles` below classifies
     **per column** (all-or-nothing), not per cell.
It reuses `findings._NONSTAT_COL`'s exact exclusion pattern (year/yr/fy/
pincode/rank/serial/_key/_code/_id columns are never treated as a metric
regardless of whether their values look numeric) — this is deliberately
name-aware, not simply "every value parses as a number" the way
`buildAnalytics`'s own client-side `isNumeric` check is. That client-side
check has a known, commented limitation (`ai_query.html:2081-2087`): a
bare 4-digit year column reads as numeric there because "2022" matches
its digit-only regex. This module's name-aware exclusion avoids feeding
that limitation a bad hint in the first place.
"""
from __future__ import annotations

import numbers
import re

_NONSTAT_COL = re.compile(
    r"(^|_)(year|yr|fy|pincode|rank|serial)($|_)|_key$|_code$|_id$|(^|_)id$",
    re.IGNORECASE,
)

_TIME_COL_RE = re.compile(r"month|period|year|date|trend", re.IGNORECASE)
_TIME_QUESTION_RE = re.compile(r"year|month|trend", re.IGNORECASE)


def _to_number(v: object) -> "int | float | None":
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, numbers.Number):
        f = float(v)
        return int(f) if f.is_integer() else f
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
            return int(s) if "." not in s else float(s)
    return None


def _column_roles(rows: list[dict]) -> "tuple[list[str], list[str]]":
    """(numeric_cols, dim_cols), each in first-seen column order. A column
    counts as numeric only when EVERY non-null value in it is numeric and
    its name doesn't match `_NONSTAT_COL` — one non-numeric or excluded
    cell demotes the whole column to a dimension/label column, matching
    the "measure only if every value is a plain number" standard
    `buildAnalytics()` itself applies (`ai_query.html:2081-2087`)."""
    if not rows:
        return [], []
    cols = list(rows[0].keys())
    numeric_cols: list[str] = []
    dim_cols: list[str] = []
    for col in cols:
        excluded = bool(_NONSTAT_COL.search(col))
        seen_value = False
        all_numeric = True
        for row in rows:
            v = row.get(col)
            if v is None or v == "":
                continue
            seen_value = True
            if excluded or _to_number(v) is None:
                all_numeric = False
                if excluded:
                    break
        if not seen_value:
            continue
        (numeric_cols if all_numeric else dim_cols).append(col)
    return numeric_cols, dim_cols


def select_chart_type(rows: list[dict], question: str = "") -> "str | None":
    """Deterministically pick one of `bar`, `doughnut`, `line`,
    `grouped_bar`, `stacked`, `kpi_bar`, or `None` for `rows` — the exact
    shape gates `buildAnalytics()` itself already enforces client-side
    (see `specs/chart-spec/spec.md` for the scenario-by-scenario mapping,
    each cited to the `ai_query.html` branch it matches). Never raises;
    an empty `rows` list returns `None`."""
    if not rows:
        return None

    numeric_cols, dim_cols = _column_roles(rows)

    if len(rows) == 1:
        # Only value buildAnalytics honors for a 1-row result at all
        # (ai_query.html:2040) — anything else it renders as a plain
        # record card, i.e. no chart, so `None` is the honest answer for
        # a single scalar or a single row with only one numeric column.
        return "kpi_bar" if len(numeric_cols) >= 2 else None

    if not numeric_cols or not dim_cols:
        return None
    if len(dim_cols) > 2:
        return None

    if len(dim_cols) == 2 and len(numeric_cols) == 1:
        # buildAnalytics's stacked branch requires lblCols.length >= 2
        # (ai_query.html:2126) — sending "stacked" with fewer than two
        # label columns is a silent no-op there, so this module never
        # emits it outside this exact shape.
        return "stacked"

    if len(numeric_cols) >= 2:
        # groupedBar has no additional shape gate client-side
        # (ai_query.html:2115-2124) — safe for 1 or 2 dimension columns.
        return "grouped_bar"

    dim_col = dim_cols[0]
    is_time = bool(_TIME_COL_RE.search(dim_col)) or bool(_TIME_QUESTION_RE.search(question or ""))
    if is_time:
        return "line"
    if len(rows) <= 6:
        return "doughnut"
    return "bar"

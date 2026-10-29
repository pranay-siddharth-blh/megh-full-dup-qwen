"""What a measure column IS, and along which dimension it may be added up
(audit 2026-10-29, section G). The word lists live in app/measure_kinds.json; the
frontend holds a checked copy (frontend/src/chat/measureKinds.js), so the backend's
chart hint and the UI's charts, totals and shares follow one rule:

    flow (money, person days)   adds across places and years
    distinct (villages, people) adds across places only
    stock (job cards)           adds across places only
    rate (%, average)           never adds
and nothing adds across schemes (they count and spend different things).
Words are read on the parts of the column name; no regex (D-047)."""
from __future__ import annotations

import json
from pathlib import Path

KINDS: dict = {k: frozenset(v) for k, v in json.loads(
    (Path(__file__).with_name("measure_kinds.json")).read_text(encoding="utf-8")).items() if not k.startswith("_")}
_ORDER = ("rate", "stock", "flow", "distinct")
_PERIOD = frozenset({"year", "yr", "fy", "month", "period", "date", "quarter", "week", "financial"})


def name_parts(col) -> list:
    """'_' / space / bracket separated parts of a column name, lower case; "(%)" -> "%"."""
    s = "".join(" " if ch in "_ ()[]/-" else ch for ch in str(col).lower())
    out = []
    for p in s.split():
        out += [p[:-1], "%"] if len(p) > 1 and p.endswith("%") else [p]
    return out


def measure_kind(col) -> str:
    """'rate' | 'stock' | 'flow' | 'distinct' (anything else is a flow)."""
    parts = name_parts(col)
    for kind in _ORDER:
        if any(p in KINDS[kind] for p in parts):
            return kind
    return "flow"


def dim_of(col) -> str:
    """'scheme' | 'period' | 'place' for a label column, by its name."""
    parts = name_parts(col)
    if "scheme" in parts or "schemes" in parts:
        return "scheme"
    if any(p in _PERIOD for p in parts):
        return "period"
    return "place"


def can_add(col, dim: str) -> bool:
    kind = measure_kind(col)
    if kind == "rate" or dim == "scheme":
        return False
    if dim == "period":
        return kind == "flow"
    return True


# X-12 (audit 2026-10-29), kept in step with frontend/src/chat/columns.js isLabelCol:
# a label word marks a label column only as the whole name or its end ("year_key",
# "district_code", "financial_year", "month_num"), never after "per" or in a name
# that starts or ends like a measure ("houses_per_year", "beneficiary_key_count").
LABEL_WORDS = frozenset({"year", "yr", "fy", "code", "id", "lgd", "pin", "pincode", "key", "rank", "sl", "serial",
                         "month", "quarter", "week"})
_LABEL_ENDS = frozenset({"key", "code", "id", "short", "num", "no", "name", "label", "lgd"})
_LABEL_LEADS = frozenset({"financial", "fiscal", "calendar", "lgd", "village", "block", "district", "gp", "scheme",
                          "fy", "month", "year", "state", "ac", "constituency"})
_MEASURE_LEADS = frozenset({"avg", "average", "total", "count", "sum", "mean", "num", "number", "no", "max", "min"})
_MEASURE_ENDS = frozenset({"count", "score", "total", "sum", "days", "amount", "value"})


def is_label_col(col) -> bool:
    parts = [p for p in str(col).lower().split("_") if p]
    if not parts or "per" in parts:
        return False
    if len(parts) > 1 and (parts[0] in _MEASURE_LEADS or parts[-1] in _MEASURE_ENDS):
        return False
    if parts[-1] in LABEL_WORDS:
        return len(parts) <= 2 or parts[-2] in _LABEL_LEADS
    return any(p in LABEL_WORDS for p in parts) and parts[-1] in _LABEL_ENDS

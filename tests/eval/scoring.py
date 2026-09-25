"""Figure extraction + matching shared by build_cases.py and run_eval.py.

The KPI workbooks state expected answers as prose with Indian-format figures
("₹945.71 Crore", "14.94 L households", "3,85,671 payment records", "71%").
The bot may state the same quantity differently ("₹945.71 crore",
"9,45,71,00,000", a lakh-denominated result cell of 94571, "0.71"). So every
figure is normalised to a base value and compared with a relative tolerance
that is never tighter than the precision the workbook itself rounded to.
"""
from __future__ import annotations

import re

_UNIT_MULT = {"crore": 1e7, "cr": 1e7, "lakh": 1e5, "lakhs": 1e5, "l": 1e5,
              "k": 1e3, "thousand": 1e3}

# A number, optionally Indian/western grouped, optionally followed by a unit.
_NUM = re.compile(
    r"(?<![\w.])(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<fy>-\d{2}(?!\d))?"
    r"\s*(?P<unit>crores?|cr\b|lakhs?|l\b|k\b|thousand\b|%)?",
    re.IGNORECASE,
)
# Words that make the following number a label, not a quantity.
_LABEL_BEFORE = re.compile(r"(tranche|top|level|fy|id|ids|stage|kpi|round|batch|"
                           r"#|no\.|number|scheme)\s*$", re.IGNORECASE)
_LABEL_AFTER = re.compile(r"^\s*-?\s*(day|days\b|year|years\b|month|months\b|"
                          r"districts?\b|blocks?\b|schemes?\b|tranches?\b|"
                          r"statuses\b|stages?\b)", re.IGNORECASE)


def parse_figures(text: str, *, skip_labels: bool = True) -> list[dict]:
    """Every quantity in `text` as {text, value, unit, base, pct, decimals}.

    skip_labels=True (used for EXPECTED answers) drops years, FY labels and
    label-like numbers ("Tranche 4", "Top 5", "12 districts", "100-day"),
    so a case's primary figure is its headline quantity. For the BOT's
    answer every number is kept — matching is looser there on purpose."""
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group("num")
        unit = (m.group("unit") or "").lower().rstrip("s") if m.group("unit") else ""
        value = float(raw.replace(",", ""))
        if skip_labels:
            if m.group("fy"):
                continue
            if not unit and "," not in raw and "." not in raw and 1990 <= value <= 2035:
                continue
            before = text[max(0, m.start() - 12):m.start()]
            after = text[m.end():m.end() + 12]
            if not unit and (_LABEL_BEFORE.search(before) or _LABEL_AFTER.search(after)):
                continue
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        pct = unit == "%"
        base = value if pct else value * _UNIT_MULT.get(unit, 1.0)
        out.append({"text": m.group(0).strip(), "value": value, "unit": unit,
                    "base": base, "pct": pct, "decimals": decimals})
    return out


def _tolerance(fig: dict) -> float:
    """Relative tolerance: the workbook's own rounding precision, floored at
    0.2% — loose enough for the bot's own rounding ("₹946 crore" for
    ₹945.71 Cr), tight enough that a different number ("₹950 crore") fails."""
    v = abs(fig["value"]) or 1.0
    rounding = 0.5 * 10 ** (-fig["decimals"]) / v
    return max(0.002, rounding * 1.01)


def _close(expected: dict, candidate: float) -> bool:
    exp = expected["base"]
    if exp == 0:
        return abs(candidate) < 1e-9
    if expected["pct"]:
        return abs(candidate - exp) <= max(0.5 * 10 ** (-expected["decimals"]), 0.05) + 1e-9 \
            or abs(candidate - exp) / abs(exp) <= _tolerance(expected)
    return abs(candidate - exp) / abs(exp) <= _tolerance(expected)


def _row_candidates(rows: list[dict]) -> list[float]:
    vals = []
    for r in rows or []:
        for v in (r.values() if isinstance(r, dict) else r):
            if isinstance(v, bool):
                continue
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            # Unit of a result cell is unknown: try it as-is, as lakhs, as
            # crores, and as a fraction that would read as a percentage.
            vals.extend([f, f * 1e5, f * 1e7, f * 100])
    return vals


def figure_found(expected: dict, answer: str, rows: list[dict] | None) -> str | None:
    """Where `expected` appears: "answer", "rows", or None."""
    for f in parse_figures(answer, skip_labels=False):
        if f["pct"] != expected["pct"] and expected["pct"]:
            continue
        # A unit-less number in the answer may be in rupees while the
        # workbook said crore — the base-value comparison covers that. Also
        # accept the same digits in a different stated unit ("945.71 Cr"
        # vs "₹945.71 crore" parse identically already).
        if _close(expected, f["base"]) or (not f["unit"] and _close(expected, f["value"] * _UNIT_MULT.get(expected["unit"], 1.0))):
            return "answer"
    for c in _row_candidates(rows or []):
        if _close(expected, c):
            return "rows"
    return None


_METHOD_ONLY = re.compile(r"^\s*(needs|requires|filter|cross-tab|12-district|"
                          r"6-status|return|report)\b", re.IGNORECASE)


def expected_figures(expected_answer: str) -> list[dict]:
    """Figures worth scoring in a workbook answer, or [] when the answer
    describes a method ("Needs a per-scheme …", "Filter district=…")."""
    if not expected_answer or _METHOD_ONLY.match(expected_answer):
        return []
    return parse_figures(expected_answer, skip_labels=True)

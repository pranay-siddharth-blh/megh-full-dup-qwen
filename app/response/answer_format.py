"""
Presentation layer for data answers — turns the composer's short summary plus
the raw result rows into a clean, professional Markdown answer.

Why this exists (2026-09-23): answers came back as one long run-on paragraph
that enumerated every row inline, used raw column names ("amount raw",
"legacy_paid_members"), UPPERCASE storage literals ("WEST GARO HILLS") and
unformatted numbers ("1197392500.00"). This module is deterministic — no model
call — so it can only re-present values already in the result, never invent or
alter one:

  * the composer's summary stays on top (it is told a table follows, so it
    summarises instead of listing rows);
  * any multi-row result gets a Markdown table below it (top N rows, readable
    headers, Title Case place names, Indian digit grouping, ₹ Cr / ₹ L for
    columns whose unit is explicit in the name, % for share/percent columns);
  * a single row with several metrics is shown as a labelled bullet list.

The chat UI (web/ai_query.html) renders this Markdown.
"""
from __future__ import annotations

import re
from decimal import Decimal

MAX_TABLE_ROWS = 15

# Column-name fragments -> display header words.
_HEADER_WORDS = {
    "lgd": "", "fy": "FY", "pct": "%", "pg": "PG", "id": "ID", "ac": "AC",
    "cm": "CM", "exp": "expenditure", "num": "number", "qty": "quantity",
    # storage-only suffixes that mean nothing to a reader
    "raw": "", "short": "", "label": "", "name_raw": "",
}
# Columns that are identifiers or years: never digit-grouped or unit-formatted.
_RAW_COL = re.compile(r"(?:^|_)(?:year|year_key|code|id|key|pincode|rank)(?:_|$)|^fy", re.IGNORECASE)
# ...unless the name says it is a COUNT ("members_with_an_id", "total_ids").
_COUNT_COL = re.compile(
    r"^(?:members|beneficiar|applications|applicants|payments|houses|villages|blocks|"
    r"districts|num|number|count|total|n)_|_count$|^count", re.IGNORECASE)


def _is_raw(col: str) -> bool:
    return bool(_RAW_COL.search(col)) and not _COUNT_COL.search(col)


_PCT_COL = re.compile(r"pct|percent|share|_rate$|^rate", re.IGNORECASE)
_CRORE_COL = re.compile(r"crore|(?:^|_)cr(?:_|$)", re.IGNORECASE)
_LAKH_COL = re.compile(r"lakh", re.IGNORECASE)
# Columns whose unit is RUPEES by construction (PMAY-G and Focus Plus money,
# per curated.dim_scheme.money_unit). MGNREGA's *_exp columns are in LAKH and
# are deliberately not matched here — they are only digit-grouped.
_RUPEE_COL = re.compile(
    r"rupee|^amount|amount$|amount_raw|amount_disbursed|amount_released|"
    r"sanctioned_amount|amount_pending|disbursed", re.IGNORECASE)

_places: set[str] = set()


def register_places(names) -> None:
    """Known UPPERCASE storage literals (districts, blocks) to Title-Case in
    prose. Called once at startup with the resolver catalogues."""
    for n in names or ():
        n = str(n or "").strip()
        if len(n) >= 3:
            _places.add(n.upper())   # storage and SQL literals are UPPERCASE


def _indian(n: int) -> str:
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    return ("-" if n < 0 else "") + s


def _num(v) -> "int | float | None":
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, (float, Decimal)):
        f = float(v)
        return int(f) if f.is_integer() else f
    # A numeric value that arrived as text (e.g. a Decimal serialised upstream).
    if isinstance(v, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", v.strip()):
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    return None


def _fmt_plain(n: "int | float") -> str:
    if isinstance(n, int):
        return _indian(n)
    whole, frac = f"{n:.2f}".split(".")
    return f"{_indian(int(whole))}.{frac}" if whole.lstrip("-") else f"{n:.2f}"


def _rupees(n: "int | float") -> str:
    a = abs(n)
    if a >= 1e7:
        return f"₹{_fmt_plain(round(n / 1e7, 2))} Cr"
    if a >= 1e5:
        return f"₹{_fmt_plain(round(n / 1e5, 2))} L"
    return f"₹{_fmt_plain(round(n, 2) if isinstance(n, float) else n)}"


def title_place(text: str) -> str:
    """'WEST GARO HILLS' -> 'West Garo Hills'; leaves mixed-case text alone."""
    t = str(text)
    if t.upper() != t or not re.search(r"[A-Z]{3,}", t):
        return t
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), t.lower())


def header(col: str) -> str:
    words = [w for w in re.split(r"[_\s]+", str(col)) if w]
    out = []
    for w in words:
        mapped = _HEADER_WORDS.get(w.lower())
        if mapped == "":
            continue
        out.append(mapped if mapped is not None else w.lower())
    h = " ".join(out) or str(col)
    return h[:1].upper() + h[1:]


def cell(col: str, v) -> str:
    if v is None or v == "":
        return "—"
    n = _num(v)
    if n is None:
        t = str(v).strip()
        if _is_raw(col):                  # identifiers stay exactly as stored
            return t.replace("|", "/")
        # Title-Case known places and long multi-word UPPERCASE labels only —
        # short codes such as 'FPO', 'LAMP', 'SEED' must stay as stored.
        if t.upper() in _places or (" " in t and len(t) > 8):
            t = title_place(t)
        return t.replace("|", "/")
    if _is_raw(col):
        return str(v)
    if _PCT_COL.search(col) and abs(n) <= 100:
        return f"{float(n):.1f}%"
    if _CRORE_COL.search(col):
        return f"₹{_fmt_plain(n)} Cr"
    if _LAKH_COL.search(col):
        return f"₹{_fmt_plain(n)} L"
    if _RUPEE_COL.search(col):
        return _rupees(n)
    return _fmt_plain(n)


def table(rows: list[dict], limit: int = MAX_TABLE_ROWS) -> str:
    if not rows:
        return ""
    # Labels (district, scheme, year ...) first, figures after — whatever order
    # the SQL happened to select them in.
    cols = list(rows[0].keys())
    is_fig = {c: _num(rows[0].get(c)) is not None and not _is_raw(c) for c in cols}
    cols = [c for c in cols if not is_fig[c]] + [c for c in cols if is_fig[c]]
    lines = ["| " + " | ".join(header(c) for c in cols) + " |",
             "| " + " | ".join("---:" if _num(rows[0].get(c)) is not None and not _is_raw(c)
                               else "---" for c in cols) + " |"]
    for r in rows[:limit]:
        lines.append("| " + " | ".join(cell(c, r.get(c)) for c in cols) + " |")
    out = "\n".join(lines)
    if len(rows) > limit:
        out += f"\n\n_Showing {limit} of {len(rows)} rows._"
    return out


def bullets(row: dict) -> str:
    return "\n".join(f"- **{header(k)}:** {cell(k, v)}" for k, v in row.items())


def polish_prose(text: str) -> str:
    """Title-Case known UPPERCASE place literals inside the composer's prose."""
    out = text or ""
    for p in sorted(_places, key=len, reverse=True):
        if p in out:
            out = re.sub(rf"(?<![A-Za-z]){re.escape(p)}(?![A-Za-z])", title_place(p), out)
    return out.strip()


def _prose_only(text: str) -> str:
    """Drop any table or list the composer wrote itself — the formatted one is
    appended by present(), and two copies of the breakdown is exactly the
    clutter this module exists to remove."""
    kept = [ln for ln in (text or "").splitlines()
            if not re.match(r"\s*\|", ln) and not re.match(r"\s*([-*•]|\d+[.)])\s+", ln)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


MAX_LIST_ROWS = 12
# Money / percent read best as "Label value" ("Amount ₹46.64 Cr"); plain counts
# read best as "value label" ("1,214 applications").
_LABEL_FIRST = re.compile(r"amount|rupee|disburs|released|sanction|expenditure|exp$|_exp_|"
                          r"crore|lakh|cost|wage|pct|percent|share|rate|avg|average|mean|per_",
                          re.IGNORECASE)


def _metric_phrase(col: str, v) -> str:
    val = cell(col, v)
    name = header(col)
    if _LABEL_FIRST.search(col):
        return f"{name.lower()} {val}" if name.lower() != "amount" else val
    return f"{val} {name.lower()}"


def breakdown(rows: list[dict], limit: int = MAX_LIST_ROWS) -> str:
    """A multi-row result as a readable bulleted list — one line per row:
    '- **West Garo Hills** — 1,708 applications · verification rate 82.0%'.
    Replaces the Markdown table (2026-09-23: the product owner wants answers
    that read like a person wrote them, not a grid)."""
    if not rows:
        return ""
    cols = list(rows[0].keys())
    labels = [c for c in cols if not (_num(rows[0].get(c)) is not None and not _is_raw(c))]
    figures = [c for c in cols if c not in labels]
    lines = []
    for r in rows[:limit]:
        label = " · ".join(cell(c, r.get(c)) for c in labels if r.get(c) not in (None, "")) or "—"
        if figures:
            metrics = " · ".join(_metric_phrase(c, r.get(c)) for c in figures)
            lines.append(f"- **{label}** — {metrics}")
        else:
            lines.append(f"- {label}")
    out = "\n".join(lines)
    if len(rows) > limit:
        out += f"\n\n_…and {len(rows) - limit} more._"
    return out


def present(summary: str, rows: list[dict]) -> str:
    """Final text for a data answer: the composer's summary ONLY — polished
    (Title Case places) and stripped of any table or list the composer wrote.

    The row-by-row breakdown is NOT repeated here: the chat UI already renders
    every result row in the data table (or record card) under the chart, so a
    list in the answer text showed the same figures twice (reported
    2026-09-23). breakdown() / bullets() remain for callers without that UI."""
    text = polish_prose(summary)
    return _prose_only(text) if rows else text

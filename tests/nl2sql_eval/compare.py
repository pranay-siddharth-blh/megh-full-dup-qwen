"""
Execution-accuracy comparison: does the pipeline's result hold the same answer
as the gold SQL's result?

Column names never matter (the model names its own aliases). The pipeline's
result matches when:
  - it has the same number of rows as the gold result, and
  - every gold column can be matched to a different pipeline column holding the
    same values — numbers within REL_TOL / ABS_TOL, optionally after one unit
    scale from SCALES (rupees <-> lakh / crore / thousand, fraction <-> percent),
    text compared case- and space-insensitively — and
  - the rows, projected onto those columns, are the same set of rows (the same
    sequence when the item is `ordered`).
Extra pipeline columns are allowed (a count shown with its share is still the
count). A different grain (one total vs per-district rows) never matches.

One fallback, for a gold answer that is a single number: the item is also
right when the answer TEXT states that number (stated_in_answer) — e.g. the
SQL returned a per-year breakdown and the answer gives the total the user
asked for. A year, or a whole number below 10, never counts (too easy to hit
by chance).
"""
import datetime as dt
import decimal
import itertools

from tests._text_checks import number_runs

REL_TOL = 0.005          # 0.5 %: a rounded percentage or lakh figure still matches
ABS_TOL = 0.051          # ... and a value rounded to one decimal place
SCALES = (1.0, 100.0, 0.01, 1e5, 1e-5, 1e7, 1e-7, 1e3, 1e-3)
_MAX_ASSIGNMENTS = 5000


def _is_num(v) -> bool:
    return isinstance(v, (int, float, decimal.Decimal)) and not isinstance(v, bool)


def _norm_text(v):
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return " ".join(str(v).upper().split())


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(ABS_TOL, REL_TOL * max(abs(a), abs(b)))


def _numeric(values) -> bool:
    present = [v for v in values if v is not None]
    return bool(present) and all(_is_num(v) for v in present)


def _cell(v, numeric: bool, scale: float = 1.0):
    if v is None:
        return None
    return float(v) * scale if numeric else _norm_text(v)


def _cells_equal(a, b, numeric: bool) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return _close(a, b) if numeric else a == b


def _sort_key(cells: tuple, numeric_flags: tuple):
    return tuple((0, 0.0, "") if c is None else (1, round(c, 2), "") if n else (1, 0.0, c)
                 for c, n in zip(cells, numeric_flags))


def _column_scales(gold_vals: list, pred_vals: list, numeric: bool) -> list[float]:
    """Scales under which the two columns hold the same multiset of values."""
    if numeric != _numeric(pred_vals) and any(v is not None for v in pred_vals):
        return []
    out = []
    for scale in (SCALES if numeric else (1.0,)):
        g = sorted((_cell(v, numeric) for v in gold_vals), key=lambda c: _sort_key((c,), (numeric,)))
        p = sorted((_cell(v, numeric, scale) for v in pred_vals), key=lambda c: _sort_key((c,), (numeric,)))
        if all(_cells_equal(a, b, numeric) for a, b in zip(g, p)):
            out.append(scale)
    return out


def compare(gold_rows: list[dict], pred_rows: "list[dict] | None", ordered: bool = False) -> dict:
    """{"match": bool, "reason": str, "mapping": {gold_col: [pred_col, scale]}}"""
    if pred_rows is None:
        return {"match": False, "reason": "no result rows", "mapping": {}}
    if len(gold_rows) != len(pred_rows):
        return {"match": False, "reason": f"row count: gold {len(gold_rows)}, got {len(pred_rows)}",
                "mapping": {}}
    if not gold_rows:
        return {"match": True, "reason": "both empty", "mapping": {}}
    gold_cols, pred_cols = list(gold_rows[0]), list(pred_rows[0])
    gnum = {c: _numeric([r.get(c) for r in gold_rows]) for c in gold_cols}
    candidates: dict[str, list[tuple[str, float]]] = {}
    for gc in gold_cols:
        gvals = [r.get(gc) for r in gold_rows]
        candidates[gc] = [(pc, s) for pc in pred_cols
                          for s in _column_scales(gvals, [r.get(pc) for r in pred_rows], gnum[gc])]
        if not candidates[gc]:
            return {"match": False, "reason": f"no column holds the gold values of '{gc}'", "mapping": {}}
    flags = tuple(gnum[c] for c in gold_cols)
    gold_t = [tuple(_cell(r.get(c), gnum[c]) for c in gold_cols) for r in gold_rows]
    for n, combo in enumerate(itertools.product(*(candidates[c] for c in gold_cols))):
        if n >= _MAX_ASSIGNMENTS:
            break
        if len({pc for pc, _ in combo}) != len(combo):
            continue
        pred_t = [tuple(_cell(r.get(pc), gnum[gc], s) for gc, (pc, s) in zip(gold_cols, combo))
                  for r in pred_rows]
        g, p = (gold_t, pred_t) if ordered else (sorted(gold_t, key=lambda t: _sort_key(t, flags)),
                                                  sorted(pred_t, key=lambda t: _sort_key(t, flags)))
        if all(all(_cells_equal(a, b, f) for a, b, f in zip(gt, pt, flags)) for gt, pt in zip(g, p)):
            return {"match": True, "reason": "same rows" + (" in order" if ordered else ""),
                    "mapping": {gc: [pc, s] for gc, (pc, s) in zip(gold_cols, combo)}}
    return {"match": False,
            "reason": "columns match one by one but not as rows" + (" in this order" if ordered else ""),
            "mapping": {}}




def _indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head, *groups, tail]) if head else ",".join([*groups, tail])


def stated_in_answer(gold_rows: list[dict], answer: str) -> bool:
    """True when the gold answer is one number (not a year or a small count) and the
    answer text states it — as written, with Indian (12,34,567) or western
    (1,234,567) grouping. A whole number (a count) must match exactly; a
    fraction may be rounded (9.94 stated as 9.9 or 10)."""
    if len(gold_rows) != 1 or len(gold_rows[0]) != 1:
        return False
    (value,) = gold_rows[0].values()
    if not _is_num(value):
        return False
    g = float(value)
    if g.is_integer() and (abs(g) < 10 or 1990 <= g <= 2035):
        return False
    for _s, _e, token in number_runs(answer, lookbehind=True):   # not right after a digit or "."
        digits = token.replace(",", "")
        try:
            n = float(digits)
        except ValueError:
            continue
        if "," in token and token not in (f"{int(n):,}", _indian(int(n))) and "." not in token:
            continue           # malformed grouping, e.g. a list "3,541,12"
        if (n == g) if g.is_integer() else (_close(n, g) or abs(n - g) <= 0.51):
            return True
    return False


def _name_words(text) -> set[str]:
    """Lower-case letter/digit words of a label or column name ("female_registrants"
    -> {"female", "registrants"})."""
    out, cur = set(), []
    for ch in str(text or "").lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.add("".join(cur))
            cur = []
    if cur:
        out.add("".join(cur))
    return out


def long_as_wide(gold_rows: list[dict], pred_rows: "list[dict] | None") -> bool:
    """The same answer laid out the other way: gold is one row per category
    (label, number) — e.g. (Female, 1103), (Male, 501) — and the pipeline
    returned ONE row with a column per category (female_registrants=1103,
    male_registrants=501). Each gold label's words must all be whole words of
    its own pipeline column's name, and the numbers must agree."""
    if not pred_rows or len(pred_rows) != 1 or len(gold_rows) < 2:
        return False
    cols = list(gold_rows[0])
    if len(cols) != 2:
        return False
    label_col = next((c for c in cols if not _numeric([r.get(c) for r in gold_rows])), None)
    value_col = next((c for c in cols if c != label_col and _numeric([r.get(c) for r in gold_rows])), None)
    if label_col is None or value_col is None:
        return False
    row, used = pred_rows[0], set()
    for g in gold_rows:
        words = _name_words(g.get(label_col))
        if not words:
            return False
        hits = [c for c in row if c not in used and words <= _name_words(c) and _is_num(row[c])
                and _close(float(row[c]), float(g.get(value_col) or 0))]
        if len(hits) != 1:
            return False
        used.add(hits[0])
    return True

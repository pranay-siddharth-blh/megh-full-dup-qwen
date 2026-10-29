# app/pipeline/common/c12_answer_shapes.py — the shape of a data answer: ranking, comparison, trend …
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
#
# User report 2026-10-22: "if I ask top 10, top 5 or compare, different things, you need to
# give different answers". Every data answer read as the same briefing line, because the
# composer prompt fixed ONE sentence shape for every question (one to three sentences, the
# first naming figure + scheme + area + period) and the number-check fallback wrote the same
# "Under X, … here are the N results:" for every multi-row result. A ranking, a comparison
# and a trend all came out alike.
#
# The shape is read here from the executed SQL (SQLGlot tree: ORDER BY / LIMIT), the result
# rows and the question's words; compose_response hands the composer that shape's
# instructions and worked example (_SHAPE_GUIDE), the figures the shape needs (_shape_facts:
# gaps, % changes, shares — computed here, so the numeric-faithfulness check accepts them;
# the composer never does arithmetic), and falls back to that shape's own deterministic
# answer (_shaped_fallback) instead of the one row dump. Single-row answers keep their
# briefing-line framing (user report 2026-10-18) and _framed_fallback.
import dataclasses as _c12s_dataclasses
from dataclasses import dataclass as _c12s_dataclass, field as _c12s_field

from app import sql_ast
from app.text_match import words as _c12s_words
from sqlglot import exp


@_c12s_dataclass
class _AnswerShape:
    kind: str                       # single_value | profile | ranking | compare | trend | breakdown | cross_tab | list
    metric: str = ""                # the measure column the shape is about
    metrics: list = _c12s_field(default_factory=list)   # every measure column, result order
    labels: list = _c12s_field(default_factory=list)    # label columns that vary across rows
    desc: bool = True               # ranking: highest first
    limit: "int | None" = None      # ranking: the LIMIT the query asked for
    yes_no: bool = False            # the question wants a yes / no


# A column whose name has one of these '_' parts holds a period, not a category.
_C12S_TIME_PARTS = frozenset({"year", "yr", "fy", "month", "quarter"})
# A measure that does not add up across rows: shares and sums of it mean nothing.
_C12S_NON_ADDITIVE_PARTS = frozenset({"pct", "percent", "percentage", "rate", "ratio", "avg", "average", "mean",
                                      "median", "share", "per"})
# "top / highest / rank …": the question asks for an order, not only a list.
_C12S_RANK_WORDS = Matcher(Alt(
    W("top", "highest", "lowest", "bottom", "best", "worst", "rank", "ranked", "ranking", "rankings",
      "leading", "most", "least", "maximum", "minimum", "largest", "smallest", "biggest", "fewest"),
))
_C12S_COMPARE_WORDS = Matcher(Alt(
    W("compare", "compared", "comparing", "comparison", "vs", "versus", "against", "difference", "differ"),
    Seq("better", "than"), Seq("more", "than"), Seq("less", "than"),
))
# A yes / no question opens with an auxiliary verb ("Is …", "Did any block …").
_C12S_YES_NO_LEADS = frozenset({"is", "are", "was", "were", "does", "do", "did", "has", "have", "had",
                                "can", "could", "will", "should", "any"})
# Ranked items the composer lists before pointing to the table.
_C12S_LIST_MAX = 15


def _c12s_parts(col: str) -> list:
    return str(col).lower().split("_")


def _c12s_is_time_col(col: str) -> bool:
    return any(p in _C12S_TIME_PARTS for p in _c12s_parts(col))


def _c12s_additive(col: str) -> bool:
    # the one non-additive list the charts read too (app/measure_kinds.json, audit 2026-10-29)
    from app import measure_kinds
    return not any(p in _C12S_NON_ADDITIVE_PARTS for p in _c12s_parts(col))         and measure_kinds.measure_kind(col) != "rate"


def _c12s_yes_no(question: str) -> bool:
    toks = _c12s_words(question)
    return bool(toks) and toks[0] in _C12S_YES_NO_LEADS


def _c12s_order(sql: str, metrics: list) -> "tuple[str, bool] | None":
    """(measure column, descending) of the outer query's first ORDER BY key, read
    on the SQLGlot tree, when that key is one of the result's measures; else None.
    The key may be the column, its alias, the aggregate itself or an ordinal."""
    try:
        tree = sql_ast.parse_one(sql or "")
    except Exception:  # noqa: BLE001 — an unreadable query just has no order
        return None
    if tree is None:
        return None
    sel = sql_ast.outer_select(tree)
    order = tree.args.get("order") or (sel.args.get("order") if sel is not None else None)
    if order is None or not order.expressions:
        return None
    first = order.expressions[0]
    key = first.this if isinstance(first, exp.Ordered) else first
    desc = bool(first.args.get("desc")) if isinstance(first, exp.Ordered) else False
    name = None
    if isinstance(key, exp.Column):
        name = key.name
    elif sel is not None and isinstance(key, exp.Literal) and not key.is_string:
        try:
            name = sel.expressions[int(key.this) - 1].alias_or_name
        except (ValueError, IndexError):
            name = None
    elif sel is not None:
        for e in sel.expressions:
            inner = e.this if isinstance(e, exp.Alias) else e
            if inner == key:
                name = e.alias_or_name
                break
    if not name:
        return None
    by_low = {str(m).lower(): m for m in metrics}
    m = by_low.get(str(name).lower())
    return (m, desc) if m else None


def _c12s_rollup_split(sql: str, rows: list) -> "tuple[list, list]":
    """(category rows, total rows). A GROUP BY ROLLUP / CUBE / GROUPING SETS adds
    total rows whose group column is NULL or the COALESCE fallback label ("ALL
    DISTRICTS"); they are the query's exact totals, not categories. CM Elevate
    Legacy's few-shots ask for exactly that row, and the shaped answer read it as a
    13th district: "5,646 records across 13 districts … ALL DISTRICTS is the
    largest" for a true 2,823 (Legacy sheet TC-36, 2026-10-22, KI-384)."""
    tree = sql_ast.parse_one(sql or "") if rows else None
    if tree is None or not any(tree.find(k) for k in (exp.Rollup, exp.Cube, exp.GroupingSets)):
        return rows, []
    group_cols = {c.name.lower() for k in (exp.Rollup, exp.Cube, exp.GroupingSets)
                  for node in tree.find_all(k) for c in node.find_all(exp.Column)}
    sel = sql_ast.outer_select(tree)
    keys: dict = {}                  # output name -> its fallback label (None: a bare NULL)
    for e in (sel.expressions if sel is not None else []):
        inner = e.this if isinstance(e, exp.Alias) else e
        cols = {c.name.lower() for c in inner.find_all(exp.Column)}
        if not cols & group_cols:
            continue
        fallback = None
        if isinstance(inner, exp.Coalesce):
            lits = [x for x in inner.expressions if isinstance(x, exp.Literal) and x.is_string]
            fallback = lits[-1].this if lits else None
        keys[e.alias_or_name] = fallback
    if not keys:
        return rows, []
    lower = {str(k).lower(): v for k, v in keys.items()}

    def is_total(r: dict) -> bool:
        for col, val in r.items():
            if str(col).lower() in lower and (val is None or (lower[str(col).lower()] is not None
                                                              and str(val) == lower[str(col).lower()])):
                return True
        return False
    detail = [r for r in rows if not is_total(r)]
    totals = [r for r in rows if is_total(r)]
    return (detail, totals) if detail and totals else (rows, [])


def _answer_shape(question: str, sql: str, rows: list) -> "_AnswerShape | None":
    """What kind of answer these rows make, or None (the old one-shape prompt).
    Read deterministically: the SQL tree for ORDER BY / LIMIT, the rows for the
    measures and the labels that vary, the question's words for rank / compare /
    yes-no cues."""
    if not rows or not isinstance(rows[0], dict):
        return None
    # Rows of several schemes are one list per scheme (D-062): their own path.
    if len({str(r.get("scheme")) for r in rows if "scheme" in r}) > 1:
        return None
    cols = list(rows[0])
    metrics = [c for c in cols if not _NONSTAT_COL.search(str(c))
               and any(_as_number(r.get(c)) is not None for r in rows)
               and all(r.get(c) is None or _as_number(r.get(c)) is not None for r in rows)]
    label_cols = [c for c in cols if c not in metrics]
    varying = [c for c in label_cols if len({str(r.get(c)) for r in rows}) > 1]
    yes_no = _c12s_yes_no(question)
    q = question or ""
    if len(rows) == 1:
        kind = "profile" if len(metrics) >= 2 else "single_value"
        return _AnswerShape(kind, metrics[0] if metrics else "", metrics, varying, yes_no=yes_no)
    if not metrics:
        return _AnswerShape("list", "", [], varying or label_cols, yes_no=yes_no)
    time_dims = [c for c in varying if _c12s_is_time_col(c)]
    # financial_year and year_key side by side are ONE period, not two dimensions
    # (live 2026-10-22: Ri Bhoi year-by-year expenditure read as a two-way table).
    if time_dims and len(time_dims) == len(varying):
        varying = time_dims[:1]
    if len(varying) >= 2:
        return _AnswerShape("cross_tab", metrics[0], metrics, varying, yes_no=yes_no)
    limit = sql_ast.outer_limit(sql or "")
    if limit is not None and (limit < 1 or limit >= 200):
        limit = None
    # "Compare A and B" stays a comparison although the model's SQL ordered and
    # limited the two rows (live 2026-10-22: answered as a "#1 leads" ranking).
    compare_asked = len(rows) <= 3 and bool(_C12S_COMPARE_WORDS.search(q))
    order = _c12s_order(sql, metrics)
    if order and not time_dims and not compare_asked and (limit or _C12S_RANK_WORDS.search(q)):
        return _AnswerShape("ranking", order[0], metrics, varying, desc=order[1], limit=limit, yes_no=yes_no)
    if time_dims and len(rows) >= 3:
        return _AnswerShape("trend", metrics[0], metrics, varying, yes_no=yes_no)
    if len(rows) == 2 or compare_asked:
        return _AnswerShape("compare", metrics[0], metrics, varying, yes_no=yes_no)
    return _AnswerShape("breakdown", metrics[0], metrics, varying, yes_no=yes_no)


def _c12s_label(row: dict, shape: _AnswerShape) -> str:
    cols = shape.labels or [k for k in row if k not in shape.metrics]
    parts = [str(row[c]) for c in cols if row.get(c) is not None]
    return " / ".join(parts) if parts else "(row)"


def _c12s_allow(allowed: set, v: "int | float") -> None:
    f = float(v)
    allowed.add(str(int(f)) if f.is_integer() else f"{f:g}")
    allowed.add(f"{f:.2f}".rstrip("0").rstrip("."))
    allowed.add(f"{f:.1f}".rstrip("0").rstrip("."))
    allowed.add(str(round(f)))


def _c12s_num(v: "int | float") -> "int | float":
    f = float(v)
    return int(f) if f.is_integer() else round(f, 2)


def _c12s_pct(part: float, whole: float) -> "float | None":
    return None if not whole else round(100.0 * part / whole, 1)


def _c12s_vals(rows: list, col: str) -> list:
    return [(r, _as_number(r.get(col))) for r in rows if _as_number(r.get(col)) is not None]


def _breakdown_preview(rows: list, shape: _AnswerShape) -> list:
    """A breakdown's rows largest first by its measure (rows without one last)."""
    return sorted(rows, key=lambda r: (_as_number(r.get(shape.metric)) is None,
                                       -(_as_number(r.get(shape.metric)) or 0)))


def _c12s_dim_noun(shape: _AnswerShape, plural: bool = True) -> str:
    """'blocks' for a block_name label, 'items' when there is no single label."""
    if len(shape.labels) != 1:
        return "items" if plural else "item"
    parts = [p for p in _c12s_parts(shape.labels[0]) if p not in ("name", "raw", "lgd", "canon", "label")]
    noun = " ".join(parts) or "item"
    if not plural:
        return noun
    if noun.endswith("y") and not noun.endswith(("ay", "ey", "oy")):
        return noun[:-1] + "ies"
    return noun if noun.endswith("s") else noun + "s"


def _shape_facts(shape: "_AnswerShape | None", rows: list) -> "tuple[str, set[str]]":
    """The derived figures the shape's answer needs — rank gaps, the difference
    and % between two sides, first-to-last change, shares of a total — as an
    indented text block, and their number strings for the faithfulness whitelist.
    ("", set()) when the shape needs none."""
    if shape is None or shape.kind in ("single_value", "profile", "list", "cross_tab") or not shape.metric:
        return "", set()
    lines: list = []
    allowed: set = set()

    def add(text: str, *nums) -> None:
        lines.append(text)
        for n in nums:
            if n is not None:
                _c12s_allow(allowed, n)

    m = shape.metric
    label_m = _metric_label(str(m))
    pairs = _c12s_vals(rows, m)
    if not pairs:
        return "", set()
    if shape.kind == "ranking":
        first_r, first_v = pairs[0]
        last_r, last_v = pairs[-1]
        word = "highest" if shape.desc else "lowest"
        asked = f" (the query asked for the {'top' if shape.desc else 'bottom'} {shape.limit})" if shape.limit else ""
        add(f"ranked by {label_m}, {word} first; {len(pairs)} ranked{asked}")
        add(f"#1: {_c12s_label(first_r, shape)} = {_fmt_num(_c12s_num(first_v))}", first_v)
        if len(pairs) >= 2:
            sec_r, sec_v = pairs[1]
            gap = _c12s_num(abs(first_v - sec_v))
            add(f"#2: {_c12s_label(sec_r, shape)} = {_fmt_num(_c12s_num(sec_v))}; #1 is {_fmt_num(gap)} "
                f"{'ahead of' if shape.desc else 'below'} #2", sec_v, gap)
            gap_last = _c12s_num(abs(first_v - last_v))
            add(f"#{len(pairs)} (last shown): {_c12s_label(last_r, shape)} = {_fmt_num(_c12s_num(last_v))}; "
                f"gap between #1 and #{len(pairs)} = {_fmt_num(gap_last)}", last_v, gap_last)
            if shape.desc and last_v and first_v > 0 and last_v > 0:
                ratio = round(first_v / last_v, 1)
                add(f"#1 is {ratio} times #{len(pairs)}", ratio)
        if _c12s_additive(m) and all(v >= 0 for _r, v in pairs) and len(pairs) >= 2:
            total = _c12s_num(sum(v for _r, v in pairs))
            share = _c12s_pct(first_v, total)
            add(f"the {len(pairs)} ranked add up to {_fmt_num(total)}; #1 holds {share}% of that", total, share)
    elif shape.kind == "compare":
        for col in shape.metrics[:3]:
            cp = _c12s_vals(rows, col)
            if len(cp) < 2:
                continue
            ordered = sorted(cp, key=lambda p: p[1], reverse=True)
            (hi_r, hi_v), (lo_r, lo_v) = ordered[0], ordered[-1]
            lab = _metric_label(str(col))
            if hi_v == lo_v:
                add(f"{lab}: every side records {_fmt_num(_c12s_num(hi_v))} — equal", hi_v)
                continue
            diff = _c12s_num(hi_v - lo_v)
            pct = _c12s_pct(hi_v - lo_v, lo_v) if lo_v > 0 else None
            sides = "; ".join(f"{_c12s_label(r, shape)} = {_fmt_num(_c12s_num(v))}" for r, v in cp)
            more = f", {pct}% more" if pct is not None else ""
            add(f"{lab}: {sides}; {_c12s_label(hi_r, shape)} is higher by {_fmt_num(diff)}{more} than "
                f"{_c12s_label(lo_r, shape)}", *[v for _r, v in cp], diff, pct)
    elif shape.kind == "trend":
        tcol = next((c for c in shape.labels if _c12s_is_time_col(c)), shape.labels[0] if shape.labels else None)
        for col in shape.metrics[:2]:
            cp = _c12s_vals(rows, col)
            if len(cp) < 2:
                continue
            if tcol:
                cp = sorted(cp, key=lambda p: str(p[0].get(tcol)))
            (r0, v0), (r1, v1) = cp[0], cp[-1]
            lab = _metric_label(str(col))
            change = _c12s_num(v1 - v0)
            pct = _c12s_pct(v1 - v0, v0) if v0 else None
            pct_text = f" ({'+' if pct > 0 else ''}{pct}%)" if pct is not None else ""
            add(f"{lab}: {_fmt_num(_c12s_num(v0))} in {_c12s_label(r0, shape)} -> {_fmt_num(_c12s_num(v1))} in "
                f"{_c12s_label(r1, shape)}; change {'+' if change > 0 else ''}{_fmt_num(change)}{pct_text}",
                v0, v1, change, abs(change), pct, abs(pct) if pct is not None else None)
            hi_r, hi_v = max(cp, key=lambda p: p[1])
            lo_r, lo_v = min(cp, key=lambda p: p[1])
            add(f"{lab}: peak {_fmt_num(_c12s_num(hi_v))} in {_c12s_label(hi_r, shape)}; lowest "
                f"{_fmt_num(_c12s_num(lo_v))} in {_c12s_label(lo_r, shape)}", hi_v, lo_v)
            steps = [b[1] - a[1] for a, b in zip(cp, cp[1:])]
            ups, downs = sum(1 for s in steps if s > 0), sum(1 for s in steps if s < 0)
            if ups and not downs:
                move = "rose every period"
            elif downs and not ups:
                move = "fell every period"
            else:
                move = f"mixed: rose in {ups}, fell in {downs} of {len(steps)} period-to-period steps"
            add(f"{lab}: {move}")
    elif shape.kind == "breakdown":
        ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
        (hi_r, hi_v), (lo_r, lo_v) = ordered[0], ordered[-1]
        add(f"{len(pairs)} {_c12s_dim_noun(shape)} in the split")
        if _c12s_additive(m) and all(v >= 0 for _r, v in pairs):
            total = _c12s_num(sum(v for _r, v in pairs))
            add(f"total {label_m} = {_fmt_num(total)}", total)
            for r, v in ordered[:3]:
                share = _c12s_pct(v, total)
                add(f"{_c12s_label(r, shape)} = {_fmt_num(_c12s_num(v))} ({share}% of the total)", v, share)
            if len(ordered) > 3:
                share = _c12s_pct(lo_v, total)
                add(f"smallest: {_c12s_label(lo_r, shape)} = {_fmt_num(_c12s_num(lo_v))} ({share}% of the total)",
                    lo_v, share)
        else:
            add(f"highest: {_c12s_label(hi_r, shape)} = {_fmt_num(_c12s_num(hi_v))}; lowest: "
                f"{_c12s_label(lo_r, shape)} = {_fmt_num(_c12s_num(lo_v))}", hi_v, lo_v)
    if not lines:
        return "", set()
    return "\n".join(f"  - {ln}" for ln in lines), allowed


# Per-shape instructions and a worked example. The examples' places and numbers are
# NOT this result's: they show the layout only (the faithfulness check rejects any
# copied example figure). A single figure has no entry: compose_response's opening
# already is its briefing-line rule (user report 2026-10-18).
_SHAPE_GUIDE = {
    "profile": (
        "Several figures for one place / period. Open with one short sentence naming the scheme, area and "
        "period, then report EVERY figure in the row, each labelled in plain words: inside that sentence "
        "when there are two or three, or as a short list '- **Label**: value' when there are four or more.",
        "In East Khasi Hills in FY 2023-24, MGNREGA recorded:\n- **Households employed**: 41,210\n"
        "- **Person-days**: 2,134,560\n- **Total expenditure**: 8,996.36 lakh\n- **Job cards issued**: 52,004"),
    "ranking": (
        "A RANKING. Open with one sentence naming the #1 and its figure, with the scheme, area and period. "
        "Then a numbered list in the result's order, one line each: '1. **Name** — figure'. List every "
        f"ranked row up to {_C12S_LIST_MAX}; when there are more, list the first {_C12S_LIST_MAX} and say the "
        "rest are in the table. Close with ONE sentence from the derived figures: how far #1 leads #2, or "
        "the gap between #1 and the last. Never re-order, skip or merge rows.",
        "Mylliem leads with 412,300 person-days in FY 2023-24 under MGNREGA.\n1. **Mylliem** — 412,300\n"
        "2. **Mawphlang** — 398,150\n3. **Mawkynrew** — 301,020\nMylliem is 14,150 ahead of Mawphlang."),
    "compare": (
        "A COMPARISON. Open with the verdict: which side is higher and by how much — the difference and the "
        "% from the derived figures. Then each side's own figure in the next sentence (or a two-line list "
        "when several measures are compared). Name the scheme and period once. When the sides are equal, "
        "say so plainly.",
        "West Garo Hills sanctioned 3,410 more PMAY-G houses than East Garo Hills in FY 2022-23 (about 41.2% "
        "more). West Garo Hills sanctioned 11,690 houses; East Garo Hills sanctioned 8,280."),
    "trend": (
        "A CHANGE OVER TIME. Open with the overall movement from the first period to the last: from X to Y, "
        "the change and the % change from the derived figures. Then name the peak and the lowest period. "
        "Then, for six periods or fewer, the period-by-period figures as a short list '- FY 2021-22: value'. "
        "Call it a steady rise or fall ONLY when the derived figures say it rose / fell every period. "
        "The opening verb follows the sign of the derived change: 'rose' for +, 'fell' for − (KI-441).",
        "MGNREGA expenditure in Ri Bhoi rose from 6,120.50 lakh in FY 2020-21 to 7,904.10 lakh in FY 2023-24 "
        "(+1,783.6 lakh, +29.1%). It peaked in FY 2022-23 at 8,215.00 lakh.\n- FY 2020-21: 6,120.50\n"
        "- FY 2021-22: 6,880.25\n- FY 2022-23: 8,215.00\n- FY 2023-24: 7,904.10"),
    "breakdown": (
        "A SPLIT / BREAKDOWN. Open with the total and how many items it is split across. Then the largest "
        "and the smallest with their figures and their share of the total (derived figures). Then, for "
        f"{_C12S_LIST_MAX} items or fewer, each item as '- **Name** — value', largest first; for more, name "
        "only the largest few and say the rest are in the table.",
        "Focus Plus paid 18,420 beneficiaries across 3 categories in FY 2024-25. General leads with 9,870 "
        "(53.6%); Other is smallest with 1,250 (6.8%).\n- **General** — 9,870\n- **ST** — 7,300\n"
        "- **Other** — 1,250"),
    "cross_tab": (
        "A TABLE of two dimensions (e.g. district by year). Do NOT list every cell — the table under the "
        "answer shows them. In two to four sentences give the overall total, then the standout highest and "
        "lowest cells from the whole-result summary, then one pattern that is plain from the summary.",
        "Across the 12 districts and 4 years, MGNREGA recorded 98,412,300 person-days. The highest single "
        "figure was West Garo Hills in FY 2022-23 (3,104,220); the lowest was South West Khasi Hills in "
        "FY 2020-21 (402,115)."),
    "list": (
        "A LIST of names — it IS the answer. Say how many match, then name them: inline when there are ten "
        f"or fewer, otherwise as a bulleted list of the first {_C12S_LIST_MAX} and say the rest are in the "
        "table.",
        "4 blocks match: Mylliem, Mawphlang, Mawkynrew and Pynursla."),
}
_YES_NO_RULE = ("The question is a yes / no question: open with a plain 'Yes' or 'No', decided from the result, "
                "then the figure that shows it.")


def _shape_guide_block(shape: "_AnswerShape | None") -> str:
    """The prompt block for the answer's shape: its instructions and its worked
    example. "" for no shape (the composer keeps its general instruction)."""
    if shape is None:
        return ""
    if shape.kind not in _SHAPE_GUIDE:
        return f"\n{_YES_NO_RULE}\n" if shape.yes_no else ""
    rule, example = _SHAPE_GUIDE[shape.kind]
    if shape.kind == "ranking":
        # "EASTERN WEST KHASI HILLS leads with 15,225" for the LOWEST three (live 2026-10-22)
        rule += (" This ranking is HIGHEST first." if shape.desc else
                 " This ranking is LOWEST first: the #1 is the lowest — say 'has the lowest' / 'is lowest', "
                 "never 'leads' or 'ahead'.")
    yn = "\n" + _YES_NO_RULE if shape.yes_no else ""
    return (f"\nAnswer shape — {rule}{yn}\nExample of this shape (layout only — its places and numbers are "
            f"NOT this result's; never copy them):\n{example}\n")


# The movement verb the trend example opens with. Live 2026-10-27 (KI-441): "person-days in
# Ri Bhoi rose from 1,212,513 in FY 2022-23 to 928,817 in FY 2024-25 (-283,696 …)" — the
# 9B copied the example's "rose" over a fall the derived figures stated.
_C12S_UP_VERBS = ("rose from", "increased from", "grew from", "went up from")
_C12S_DOWN_VERBS = ("fell from", "decreased from", "dropped from", "declined from", "went down from")


def _c12s_fix_trend_direction(answer: str, shape: "_AnswerShape | None", rows: list) -> str:
    """The answer with its first movement verb matching the sign of the first-to-last
    change of the trend's first measure (sorted by its time column, as _shape_facts)."""
    if not answer or shape is None or shape.kind != "trend" or not shape.metrics:
        return answer
    tcol = next((c for c in shape.labels if _c12s_is_time_col(c)), shape.labels[0] if shape.labels else None)
    cp = _c12s_vals(rows, shape.metrics[0])
    if len(cp) < 2:
        return answer
    if tcol:
        cp = sorted(cp, key=lambda p: str(p[0].get(tcol)))
    change = cp[-1][1] - cp[0][1]
    wrong, right = (_C12S_UP_VERBS, "fell from") if change < 0 else \
        (_C12S_DOWN_VERBS, "rose from") if change > 0 else ((), "")
    low = answer.lower()
    hits = [(low.find(v), v) for v in (*_C12S_UP_VERBS, *_C12S_DOWN_VERBS) if low.find(v) >= 0]
    if not hits:
        return answer
    at, verb = min(hits)
    if verb not in wrong:
        return answer
    logger.warning("compose_response: trend verb %r against a change of %s — corrected", verb, change)
    return answer[:at] + right + answer[at + len(verb):]


def _shaped_fallback(shape: "_AnswerShape | None", rows: list, schemes: "list[str] | None",
                     entities: "dict | None") -> "str | None":
    """The deterministic answer in the question's shape, for when the composer
    keeps misquoting: a ranked list for a ranking, the verdict for a comparison,
    first-to-last for a trend, the split for a breakdown. None for the other
    shapes, which keep _framed_fallback."""
    if shape is None or shape.kind not in ("ranking", "compare", "trend", "breakdown") or not shape.metric:
        return None
    pairs = _c12s_vals(rows, shape.metric)
    if len(pairs) < 2:
        return None
    # E9: with the answer templates on, the fallback is the same templated answer under
    # code's own opening line — one money format, no unasked lines.
    if settings.ANSWER_TEMPLATES_ENABLED:
        body = _c12s_e9_body(shape, rows, "", fallback=True)
        if body:
            return _c12s_e9_frame_default(shape, rows, schemes, entities) + "\n" + body
    scheme, place, period = _scope_words(schemes, entities)
    scope = ", ".join(x for x in (scheme, place, period) if x)
    what = _human_metric(str(shape.metric))
    lines: list = []
    if shape.kind == "ranking":
        word = "Top" if shape.desc else "Bottom"
        lead = f"{word} {len(pairs)} {_c12s_dim_noun(shape)} by {what} ({scope}):"
        for i, (r, v) in enumerate(pairs[:_C12S_LIST_MAX], 1):
            lines.append(f"{i}. **{_c12s_label(r, shape)}** — {_fmt_num(_c12s_num(v))}")
        if len(pairs) > _C12S_LIST_MAX:
            lines.append(f"…and {len(pairs) - _C12S_LIST_MAX} more in the table.")
        (r1, v1), (r2, v2) = pairs[0], pairs[1]
        tail = (f"{_c12s_label(r1, shape)} is {_fmt_num(_c12s_num(abs(v1 - v2)))} "
                f"{'ahead of' if shape.desc else 'below'} {_c12s_label(r2, shape)}.")
        return lead + "\n" + "\n".join(lines) + "\n" + tail
    if shape.kind == "compare":
        ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
        (hi_r, hi_v), (lo_r, lo_v) = ordered[0], ordered[-1]
        if hi_v == lo_v:
            head = (f"{' and '.join(_c12s_label(r, shape) for r, _v in pairs)} each record "
                    f"{_fmt_num(_c12s_num(hi_v))} {what} ({scope}).")
        else:
            pct = _c12s_pct(hi_v - lo_v, lo_v) if lo_v > 0 else None
            more = f", {pct}% more" if pct is not None else ""
            head = (f"{_c12s_label(hi_r, shape)} is ahead on {what}: {_fmt_num(_c12s_num(hi_v))} against "
                    f"{_fmt_num(_c12s_num(lo_v))} for {_c12s_label(lo_r, shape)} — a difference of "
                    f"{_fmt_num(_c12s_num(hi_v - lo_v))}{more} ({scope}).")
        others = []
        for col in shape.metrics[1:4]:
            cp = _c12s_vals(rows, col)
            if cp:
                others.append(f"- {_human_metric(str(col))}: " + "; ".join(
                    f"{_c12s_label(r, shape)} {_fmt_num(_c12s_num(v))}" for r, v in cp))
        return head + ("\n" + "\n".join(others) if others else "")
    if shape.kind == "trend":
        tcol = next((c for c in shape.labels if _c12s_is_time_col(c)), shape.labels[0] if shape.labels else None)
        cp = sorted(pairs, key=lambda p: str(p[0].get(tcol))) if tcol else pairs
        (r0, v0), (r1, v1) = cp[0], cp[-1]
        pct = _c12s_pct(v1 - v0, v0) if v0 else None
        pct_text = f", {'+' if pct > 0 else ''}{pct}%" if pct is not None else ""
        change = _c12s_num(v1 - v0)
        hi_r, hi_v = max(cp, key=lambda p: p[1])
        head = (f"{what[:1].upper() + what[1:]} went from {_fmt_num(_c12s_num(v0))} in {_c12s_label(r0, shape)} to "
                f"{_fmt_num(_c12s_num(v1))} in {_c12s_label(r1, shape)} ({'+' if change > 0 else ''}"
                f"{_fmt_num(change)}{pct_text}; {scope}). It peaked at {_fmt_num(_c12s_num(hi_v))} in "
                f"{_c12s_label(hi_r, shape)}.")
        if len(cp) <= _C12S_LIST_MAX:
            lines = [f"- {_c12s_label(r, shape)}: {_fmt_num(_c12s_num(v))}" for r, v in cp]
        return head + ("\n" + "\n".join(lines) if lines else "")
    # breakdown
    ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
    (hi_r, hi_v), (lo_r, lo_v) = ordered[0], ordered[-1]
    if _c12s_additive(shape.metric) and all(v >= 0 for _r, v in pairs):
        total = _c12s_num(sum(v for _r, v in pairs))
        head = (f"{_fmt_num(total)} {what} in total across {len(pairs)} {_c12s_dim_noun(shape)} ({scope}). "
                f"{_c12s_label(hi_r, shape)} is the largest with {_fmt_num(_c12s_num(hi_v))} "
                f"({_c12s_pct(hi_v, total)}%); {_c12s_label(lo_r, shape)} is the smallest with "
                f"{_fmt_num(_c12s_num(lo_v))} ({_c12s_pct(lo_v, total)}%).")
    else:
        head = (f"{what[:1].upper() + what[1:]} across {len(pairs)} {_c12s_dim_noun(shape)} ({scope}): highest "
                f"{_c12s_label(hi_r, shape)} at {_fmt_num(_c12s_num(hi_v))}, lowest {_c12s_label(lo_r, shape)} "
                f"at {_fmt_num(_c12s_num(lo_v))}.")
    # Every measure the question asked for, per item: "district-wise summary of
    # applications, sanctioned cases and total disbursement" listed only the records
    # (CM Elevate Legacy sheet TC-36, 2026-10-22).
    extra = [c for c in shape.metrics if c != shape.metric][:6]

    def _more(r: dict) -> str:
        bits = [f"{_human_metric(str(c))} {_fmt_num(_c12s_num(_as_number(r.get(c))))}"
                for c in extra if _as_number(r.get(c)) is not None]
        return ("; " + "; ".join(bits)) if bits else ""
    first = f" {what}" if extra else ""
    lines = [f"- **{_c12s_label(r, shape)}** — {_fmt_num(_c12s_num(v))}{first}{_more(r)}"
             for r, v in ordered[:_C12S_LIST_MAX]]
    if len(pairs) > _C12S_LIST_MAX:
        lines.append(f"…and {len(pairs) - _C12S_LIST_MAX} more in the table.")
    return head + "\n" + "\n".join(lines)


# ── Templated number sentences per shape (E9, 2026-10-29) ───────────────────
# Composer audit 2026-10-27: of 43 answers, the single figures were clean and the multi-row
# shapes carried the errors — "Bank disbursed 11.10 crore MORE than LIFCOM" for a 1.31 gap
# (CL-05), "the recorded total is -48.84 percentage change" (MG-12), the top 5 villages
# never named (PM-06), and lines nobody asked for (a "#1 is N ahead" line on every ranking,
# % shares on every split, peak and lowest on every trend). For a ranking, comparison,
# trend or split, code now writes every sentence that carries a figure, from these
# templates, with the one money formatter (_c12_money); the 9B writes only the opening
# line, which may hold no figure (_c12s_e9_framing). The extra lines appear only when the
# question asks for them. Off with ANSWER_TEMPLATES_ENABLED=false (the composer then
# writes the whole answer from _SHAPE_GUIDE, as before).
_C12S_E9_GAP_ASK = Matcher(Alt(
    W("gap", "gaps", "difference", "differences", "differ", "margin", "ahead", "behind", "lead", "leads", "lag",
      "compare", "compared", "comparison", "versus", "vs"),
    Seq("how", "far"), Seq("how", "much", "more"), Seq("more", "than"), Seq("less", "than"),
))
_C12S_E9_PEAK_ASK = Matcher(W("peak", "peaked", "highest", "lowest", "best", "worst", "maximum", "minimum", "max", "min",
                              "most", "least"))
_C12S_E9_TOTAL_ASK = Matcher(Alt(W("total", "totals", "overall", "altogether", "combined", "sum", "aggregate"),
                                 Seq("in", "all")))
_C12S_E9_SHARE_ASK = Matcher(W("share", "shares", "percent", "percentage", "percentages", "proportion",
                               "proportions", "contribution"))


# SQL alias shorthands, said in full ("Total exp fell from …", live E9 check 2026-10-29)
_C12S_E9_ALIAS_WORDS = {"exp": "expenditure", "amt": "amount", "tot": "total", "hh": "households",
                        "disb": "disbursement"}


def _c12s_e9_what(col: str) -> str:
    """What a measure counts, without its unit (the figure carries it): 'total expenditure'."""
    unit = _unit_suffix(str(col).lower())
    name = unit[0] if unit else _human_metric(str(col))
    return " ".join(_C12S_E9_ALIAS_WORDS.get(w, w) for w in name.split(" "))


def _c12s_e9_same_amount(a: str, b: str, rows: list) -> bool:
    """Two money columns holding the same amount in two units (total_exp_lakh beside
    total_exp_cr): one measure, said once."""
    ua, ub = _c12_money_unit(str(a)), _c12_money_unit(str(b))
    if not ua or not ub:
        return False
    pairs = [(_as_number(r.get(a)), _as_number(r.get(b))) for r in rows]
    pairs = [(x * _C12_MONEY_SCALE[ua], y * _C12_MONEY_SCALE[ub]) for x, y in pairs if x is not None and y is not None]
    rounding = 0.01 * max(_C12_MONEY_SCALE[ua], _C12_MONEY_SCALE[ub])      # 2 decimals of the larger unit
    return bool(pairs) and all(abs(x - y) <= max(0.005 * abs(x), rounding) for x, y in pairs)


def _c12s_e9_cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _c12s_e9_gap(col: str, d: "int | float") -> str:
    """A difference of `col`: percentage points for a percentage, else the measure's own format."""
    if _c12_is_pct_col(str(col)):
        return f"{_fmt_num(_c12s_num(d))} percentage points"
    return _c12_fmt_value(str(col), _c12s_num(d))


def _c12s_e9_period(row: dict, shape: _AnswerShape) -> str:
    """A trend row's period as the officer says it: 'FY 2022-23' for '2022-23' or year_key 2022."""
    lab = _c12s_label(row, shape)
    if lab.isdecimal() and len(lab) == 4 and 1900 <= int(lab) <= 2199:
        return f"FY {lab}-{(int(lab) + 1) % 100:02d}"
    if not lab.lower().startswith("fy") and len(lab) in (7, 9) and lab[:4].isdecimal() and lab[4] == "-":
        return f"FY {lab}"
    return lab


def _c12s_e9_extras(shape: _AnswerShape, row: dict, limit: int = 3) -> str:
    """The row's other measures, '; households employed 41,210', for a list line."""
    bits = [f"{_c12s_e9_what(str(c))} {_c12_fmt_value(str(c), _as_number(row.get(c)))}"
            for c in shape.metrics if c != shape.metric and _as_number(row.get(c)) is not None][:limit]
    return ("; " + "; ".join(bits)) if bits else ""


def _c12s_e9_body(shape: "_AnswerShape | None", rows: list, question: str,
                  fallback: bool = False) -> "str | None":
    """The figure-bearing lines of a ranking / comparison / trend / split answer, written by
    code. None for any other shape, fewer than two values, or a yes / no question (its
    'Yes' / 'No' is the composer's) — unless `fallback`, where the figures alone answer."""
    if shape is None or shape.kind not in ("ranking", "compare", "trend", "breakdown") or not shape.metric \
            or (shape.yes_no and not fallback):
        return None
    pairs = _c12s_vals(rows, shape.metric)
    if len(pairs) < 2:
        return None
    # the same amount in a second unit is not a second measure
    shape = _c12s_dataclasses.replace(shape, metrics=[c for c in shape.metrics if c == shape.metric
                                                      or not _c12s_e9_same_amount(shape.metric, c, rows)])
    m, q = str(shape.metric), question or ""
    what = _c12s_e9_what(m)
    lines: list = []
    if shape.kind == "ranking":
        for i, (r, v) in enumerate(pairs[:_C12S_LIST_MAX], 1):
            lines.append(f"{i}. **{_c12s_label(r, shape)}** — {_c12_fmt_value(m, v)}")
        if len(pairs) > _C12S_LIST_MAX:
            lines.append(f"…and {len(pairs) - _C12S_LIST_MAX} more in the table.")
        if _C12S_E9_GAP_ASK.search(q):
            (r1, v1), (r2, v2) = pairs[0], pairs[1]
            lines.append(f"{_c12s_label(r1, shape)} is {_c12s_e9_gap(m, abs(v1 - v2))} "
                         f"{'higher' if v1 >= v2 else 'lower'} than {_c12s_label(r2, shape)}.")
        return "\n".join(lines)
    if shape.kind == "compare":
        ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
        (hi_r, hi_v), (lo_r, lo_v) = ordered[0], ordered[-1]
        if hi_v == lo_v:
            lines.append(f"{' and '.join(_c12s_label(r, shape) for r, _v in pairs)} each record "
                         f"{_c12_fmt_value(m, hi_v)} {what}.")
        else:
            pct = _c12s_pct(hi_v - lo_v, lo_v) if lo_v > 0 and _c12s_additive(m) else None
            lines.append(f"{_c12s_label(hi_r, shape)} is higher than {_c12s_label(lo_r, shape)} on {what}: "
                         f"{_c12_fmt_value(m, hi_v)} against {_c12_fmt_value(m, lo_v)}, a difference of "
                         f"{_c12s_e9_gap(m, hi_v - lo_v)}{f' ({pct}% more)' if pct is not None else ''}.")
            if len(pairs) > 2:
                lines += [f"- **{_c12s_label(r, shape)}** — {_c12_fmt_value(m, v)}" for r, v in ordered]
        for col in shape.metrics:
            cp = _c12s_vals(rows, col) if col != shape.metric else []
            if cp and len(lines) < 5:
                lines.append(f"- {_c12s_e9_cap(_c12s_e9_what(str(col)))}: " + "; ".join(
                    f"{_c12s_label(r, shape)} {_c12_fmt_value(str(col), v)}" for r, v in cp))
        return "\n".join(lines)
    if shape.kind == "trend":
        tcol = next((c for c in shape.labels if _c12s_is_time_col(c)), shape.labels[0] if shape.labels else None)
        cp = sorted(pairs, key=lambda p: str(p[0].get(tcol))) if tcol else pairs
        (r0, v0), (r1, v1) = cp[0], cp[-1]
        p0, p1 = _c12s_e9_period(r0, shape), _c12s_e9_period(r1, shape)
        if v1 == v0:
            lines.append(f"{_c12s_e9_cap(what)} was {_c12_fmt_value(m, v0)} in both {p0} and {p1}.")
        else:
            up = v1 > v0
            pct = _c12s_pct(abs(v1 - v0), abs(v0)) if v0 and not _c12_is_pct_col(m) else None
            lines.append(f"{_c12s_e9_cap(what)} {'rose' if up else 'fell'} from {_c12_fmt_value(m, v0)} in {p0} to "
                         f"{_c12_fmt_value(m, v1)} in {p1}, {'up' if up else 'down'} {_c12s_e9_gap(m, abs(v1 - v0))}"
                         f"{f' ({pct}%)' if pct is not None else ''}.")
        if _C12S_E9_PEAK_ASK.search(q):
            hi_r, hi_v = max(cp, key=lambda p: p[1])
            lo_r, lo_v = min(cp, key=lambda p: p[1])
            lines.append(f"The highest was {_c12_fmt_value(m, hi_v)} in {_c12s_e9_period(hi_r, shape)}; the lowest "
                         f"was {_c12_fmt_value(m, lo_v)} in {_c12s_e9_period(lo_r, shape)}.")
        if len(cp) <= _C12S_LIST_MAX:
            lines += [f"- {_c12s_e9_period(r, shape)}: {_c12_fmt_value(m, v)}{_c12s_e9_extras(shape, r, 2)}"
                      for r, v in cp]
        return "\n".join(lines)
    # breakdown: largest first
    ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
    (hi_r, hi_v), (lo_r, lo_v) = ordered[0], ordered[-1]
    n, nouns = len(pairs), _c12s_dim_noun(shape)
    additive = _c12s_additive(m) and all(v >= 0 for _r, v in pairs)
    total = _c12s_num(sum(v for _r, v in pairs)) if additive else None
    shares = bool(additive and total and (_C12S_E9_SHARE_ASK.search(q) or "%" in q))

    def _share(v: "int | float") -> str:
        return f" ({_c12s_pct(v, total)}%)" if shares else ""
    if additive and _C12S_E9_TOTAL_ASK.search(q):
        lines.append(f"{_c12_fmt_value(m, total)} {what} in total across {n} {nouns}.")
    lines.append(f"{_c12s_label(hi_r, shape)} is the largest with {_c12_fmt_value(m, hi_v)}{_share(hi_v)}; "
                 f"{_c12s_label(lo_r, shape)} is the smallest with {_c12_fmt_value(m, lo_v)}{_share(lo_v)}.")
    lines += [f"- **{_c12s_label(r, shape)}** — {_c12_fmt_value(m, v)}{_share(v)}{_c12s_e9_extras(shape, r)}"
              for r, v in ordered[:_C12S_LIST_MAX]]
    if n > _C12S_LIST_MAX:
        lines.append(f"…and {n - _C12S_LIST_MAX} more in the table.")
    return "\n".join(lines)


def _c12s_e9_frame_default(shape: _AnswerShape, rows: list, schemes: "list[str] | None",
                           entities: "dict | None") -> str:
    """The opening line code writes when the composer's is unusable: what the figures
    show, with the scheme, area and period."""
    scheme, place, period = _scope_words(schemes, entities)
    scope = ", ".join(x for x in (scheme, place, period) if x)
    what = _c12s_e9_what(str(shape.metric))
    n = len(_c12s_vals(rows, shape.metric))
    if shape.kind == "ranking":
        return f"{'Top' if shape.desc else 'Bottom'} {n} {_c12s_dim_noun(shape)} by {what} ({scope}):"
    if shape.kind == "compare":
        return f"{_c12s_e9_cap(what)} compared ({scope}):"
    if shape.kind == "trend":
        return f"{_c12s_e9_cap(what)} over time ({scope}):"
    return f"{_c12s_e9_cap(what)} by {_c12s_dim_noun(shape, plural=False)} ({scope}):"


# Words an opening line may not use for the shape: the code's figures decide them.
_C12S_E9_FRAME_BANNED = {
    "ranking_desc": frozenset({"lowest", "least", "fewest", "smallest", "bottom"}),
    "ranking_asc": frozenset({"highest", "most", "largest", "biggest", "leads", "leading", "top"}),
    "compare": frozenset({"higher", "lower", "more", "less", "fewer", "ahead", "behind", "exceeds", "leads", "than"}),
    "trend": frozenset({"rose", "fell", "increased", "decreased", "grew", "declined", "dropped", "peaked", "peak",
                        "rising", "falling", "growth", "decline"}),
    "breakdown": frozenset({"largest", "smallest", "highest", "lowest", "most", "least", "leads"}),
}


def _c12s_e9_frame_ok(text: str, shape: _AnswerShape, allowed: set) -> "str | None":
    """The composer's opening line, cleaned, or None when it may not be used: empty, long,
    a hedge, a figure that is not a year / the query's own literal / the list size, or a
    word that decides what the code's figures decide (highest, rose …)."""
    line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    for lead in ("Opening sentence:", "Answer:"):
        if line.startswith(lead):
            line = line[len(lead):].strip()
    line = line.strip(" *\"'")
    if not line or len(line) > 240 or _HEDGE_MATCH.search(line) or line[:1] in "-#" or line[:1].isdecimal():
        return None
    fy = [(a, b) for a, b, _y0, _y1 in _c12_fy_spans(line)]
    for s, e, tok in _c12_number_spans(line, decimals=True, commas=True):
        if any(a <= s and e <= b for a, b in fy) or (tok.isdecimal() and len(tok) == 4 and 1900 <= int(tok) <= 2199):
            continue
        if _c12_lb_canon(tok) not in allowed:
            return None
    key = (f"ranking_{'desc' if shape.desc else 'asc'}" if shape.kind == "ranking" else shape.kind)
    if set(_c12s_words(line)) & _C12S_E9_FRAME_BANNED.get(key, frozenset()):
        return None
    if line.endswith("."):
        line = line[:-1]
    return line if line.endswith(":") else line + ":"


async def _c12s_e9_framing(question: str, shape: _AnswerShape, rows: list, sql: str,
                           schemes: "list[str] | None", entities: "dict | None", names_block: str = "") -> str:
    """The answer's opening line from the 9B composer: what the figures below show, with no
    figure of its own. Code's own line when the composer's cannot be used (or fails).
    `names_block`: the entity-names block and any context notes, as compose_response built them."""
    default = _c12s_e9_frame_default(shape, rows, schemes, entities)
    scheme, place, period = _scope_words(schemes, entities)
    n = len(_c12s_vals(rows, shape.metric))
    what = _c12s_e9_what(str(shape.metric))
    shows = {
        "ranking": f"the {'top' if shape.desc else 'bottom'} {n} {_c12s_dim_noun(shape)} ranked by {what}",
        "compare": f"a comparison of {what} between "
                   + " and ".join(_c12s_label(r, shape) for r, _v in _c12s_vals(rows, shape.metric)),
        "trend": f"how {what} changed over {n} periods",
        "breakdown": f"{what} split across {n} {_c12s_dim_noun(shape)}",
    }[shape.kind]
    prompt = f"""Write ONE short opening sentence (at most 25 words) for the answer to the question below.
Code writes every figure on the lines right after your sentence, so your sentence must:
- contain NO figures: no counts, amounts, percentages, ranks or totals (naming the year of the period is fine);
- say plainly what the lines below show — {shows} — for which scheme, area and period;
- never say which item is highest or lowest, and never say whether anything rose or fell;
- follow any Context note below that concerns how to describe these figures, in words only.
Write it like a direct briefing — never "The data shows..." or "This table..." — and end it with a colon.
Scheme: {scheme or "as the question names it"}; area: {place}; period: {period}.
{names_block}
Question: "{question}"

Opening sentence:"""
    context_budget.log_prompt_context("compose", [("entity_names", names_block), ("question", question)],
                                      prompt=prompt, rows=len(rows), rows_shown=0)
    try:
        text = await llm.call_response_composer(prompt)
    except Exception:  # noqa: BLE001 — the figures are code's; its own opening line is enough
        logger.warning("compose_response: opening line call failed — code's own line", exc_info=True)
        return default
    allowed = {_c12_lb_canon(x) for x in _sql_literal_numbers(sql)} | {str(n)}
    allowed |= {_c12_lb_canon(x) for v in (entities or {}).values() for x in _digit_runs(str(v))}
    line = _c12s_e9_frame_ok(text, shape, allowed)
    if line is None:
        logger.warning("compose_response: opening line %r not usable — code's own line", (text or "")[:160])
        return default
    return line

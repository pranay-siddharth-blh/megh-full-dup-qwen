# app/pipeline/schemes/focus_legacy.py — Focus Legacy (producer groups) — duplicates, FY compare, breakdowns, group names, SQL rewrites.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
# Only this scheme's code lives here; the shared steps that call it are in ../common/.
# Sections follow the order of the pipeline steps they belong to.
# SQL is read and rewritten on the SQLGlot tree (app/sql_ast.py), never with a regular
# expression; the user's question and the answer text are read on WORDS
# (app/text_match.py), result-row keys with plain string methods.
import sqlglot
from sqlglot import exp

from app import sql_ast
from app.text_match import (ANY, END, START, Alt, Cap, Hit, Joined, Matcher, Opt, Pred, Rep, Seq, W, alnum_only,
                            collapse_ws)


def _fl_sp(*parts):
    """Words in a row with only whitespace between them."""
    return Seq(*parts, sep="space")


class _FlDotSpaceSeq(Seq):
    """Words separated by an optional '.' and optional whitespace ("p.g", "p. g",
    "p g", "rs.500", "rs 500")."""

    def _sep_ok(self, ctx, i):
        g = ctx.gap(i)
        return (g[1:] if g.startswith(".") else g).strip() == ""


def _fl_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _fl_lead_strip(s: str) -> str:
    """`s` without leading whitespace, one optional comma, and whitespace again."""
    t = s.lstrip()
    if t.startswith(","):
        t = t[1:].lstrip()
    return t


def _fl_at_start(m: Matcher, s: str) -> "Hit | None":
    """m.match(s), only when nothing but whitespace precedes the hit."""
    h = m.match(s)
    return h if h is not None and s[:h.start()].strip() == "" else None


def _fl_split_after_stops(text: str) -> list[str]:
    """Split after '.', '!' or '?' wherever whitespace follows (the whitespace is dropped)."""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        if text[i] in ".!?" and i + 1 < n and text[i + 1].isspace():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            out.append(text[start:i + 1])
            start = i = j
            continue
        i += 1
    out.append(text[start:])
    return out


# ── SQL tree helpers (Focus Legacy; CM Elevate Legacy uses them too) ─────────
def _fl_unwrap(node):
    """The operand under UPPER() / LOWER() / TRIM() / a cast / parentheses."""
    while isinstance(node, (exp.Upper, exp.Lower, exp.Trim, exp.Cast, exp.Paren)) and node.this is not None:
        node = node.this
    return node


def _fl_col_name(node) -> "str | None":
    """Lower-cased column name when `node` is a (wrapped) column, else None."""
    node = _fl_unwrap(node) if node is not None else None
    return node.name.lower() if isinstance(node, exp.Column) and node.name else None


def _fl_str_literal(node) -> "str | None":
    """The value of a (wrapped) string literal, else None."""
    node = _fl_unwrap(node) if node is not None else None
    return node.this if isinstance(node, exp.Literal) and node.is_string else None


def _fl_col_vs_literal(node, cols) -> "tuple[str, str] | None":
    """(column, literal) for a binary comparison of one of `cols` with a string
    literal, either side of the operator; None for anything else."""
    if not isinstance(node, exp.Binary):
        return None
    for col_side, val_side in ((node.this, node.expression), (node.expression, node.this)):
        c, v = _fl_col_name(col_side), _fl_str_literal(val_side)
        if c in cols and v is not None:
            return c, v
    return None


def _fl_conjuncts(where: "exp.Where") -> list:
    return list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this]


def _fl_drop_and_conjuncts(sql: str, pred) -> str:
    """Drop the AND-ed WHERE conditions for which pred(node) holds, only where they
    sit beside another condition (a WHERE is never emptied)."""
    def fn(tree):
        for where in list(tree.find_all(exp.Where)):
            conds = _fl_conjuncts(where)
            if len(conds) < 2:
                continue
            keep = [c for c in conds if not pred(c)] or conds[:1]
            if len(keep) != len(conds):
                where.set("this", exp.and_(*keep, copy=False))
        return None
    return sql_ast.transform(sql, fn) if sql else sql


def _fl_sums_column(sql_or_tree, col: str, exact: bool = False) -> bool:
    """SUM(col) anywhere in the query; exact=False also takes SUM(col * …)."""
    for t in sql_ast.parse(sql_or_tree) if isinstance(sql_or_tree, str) else [sql_or_tree]:
        for s in t.find_all(exp.Sum):
            arg = s.this.unnest() if s.this is not None else None
            if isinstance(arg, exp.Column) and arg.name.lower() == col:
                return True
            if not exact and arg is not None and sql_ast.references_column(arg, col):
                return True
    return False


def _fl_is_not_null(node, col: str) -> bool:
    """`col IS NOT NULL` (either tree shape SQLGlot gives it)."""
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        node, negated = node.this, True
    else:
        negated = isinstance(node, exp.Is) and bool(node.args.get("negate"))
    return (negated and isinstance(node, exp.Is) and isinstance(node.expression, exp.Null)
            and _fl_col_name(node.this) == col)


def _sql_has_marker(sql: str, marker: str) -> bool:
    """Whether the query carries the /* marker */ comment a fixed query is built
    with — read from the SQL tokenizer's comments, not from the text."""
    if not sql:
        return False
    try:
        tokens = sqlglot.tokenize(sql, read=sql_ast.DIALECT)
    except Exception:  # noqa: BLE001 — untokenizable text carries no marker
        return False
    return any(c.strip().lower() == marker for t in tokens for c in (t.comments or []))


class _SqlMarker:
    """A fixed query's marker comment. `.search(sql)` keeps the call shape the
    data stage already uses (it calls `_FL_DUP_SQL_SHAPE.search(sql)`)."""

    def __init__(self, marker: str):
        self.marker = marker

    def search(self, sql: "str | None") -> bool:
        return _sql_has_marker(sql or "", self.marker)


# ════ scheme terms ════════════════════════════════════════════════════════════════════════════════════
# Focus Legacy is the legacy producer-group disbursement programme. Its grain IS
# the producer group, so producer-group vocabulary belongs here and nowhere else
# (Focus Plus has no such column at all). "pg"/"pgs" are claimed as whole words —
# the resolver's own disambiguation rule names them as forcing the Focus Legacy
# reading — but "member"/"disbursement"/"payment"/"amount" are deliberately left
# out: they are shared vocabulary, so an unnamed question using only those still
# asks "which scheme?".
_FOCUSLEGACY_ONLY_TERMS = Matcher(Alt(
    Joined("focus", "legacy"), Joined("legacy", "focus"), Joined("old", "focus"),
    Joined("producer", ("group", "groups")), W("pg", "pgs"),
    Joined("pg", ("id", "ids", "member", "members", "name", "names", "scheme", "focus", "lamp", "existing")),
    Joined("focus", "addnl"), _fl_sp("focus", "additional"),
    _fl_sp("lamp", ("society", "societies")),
    # only Focus Legacy records remittances (date_of_remittance): "Show me all
    # remittances made between April and June 2025" asked which scheme (2026-10-14)
    W("remittance", "remittances", "remitted"), _fl_sp(("date", "dates"), "of", "remittance"),
))


def _pg_focus_group_name(question: str) -> bool:
    pg = _pg_name_question(question)
    return bool(pg and _BARE_FOCUS_WORD.search(pg[1]) and [
        t for t in _pg_name_tokens(pg[1]) if t not in ("focus", "plus", "legacy", "scheme")])


# ════ answers ═════════════════════════════════════════════════════════════════════════════════════════
# TC-12 "Are there any duplicate Producer Groups?": the answer called the 2,655
# groups paid more than once "duplicate producer groups". They are repeat
# payments in later tranches; a duplicate RECORD would be the same group paid
# twice on the same date, and there are none.
_DUPLICATE_Q = Matcher(Alt(W("duplicat", prefix=True),
                           _fl_sp("repeated", Opt("producer"), ("group", "groups")),
                           W("double", "doubles")))


async def _focus_legacy_list_total(sql: str, rows: list[dict]) -> "tuple[int, str] | None":
    """(true row count, subject) when a Focus Legacy list was cut off by its own
    LIMIT, else None. The subject is "producer groups" for a pg_id-grained list."""
    lim = sql_ast.outer_limit(sql or "")
    if not lim or lim < 1 or len(rows or []) != lim or len(rows) < 2:
        return None
    subject = "producer groups" if _fl_group_grain(sql) else "results"
    for key in ("groups_qualifying", "total_matching", "total_groups"):
        n = _as_number((rows[0] or {}).get(key))
        if isinstance(n, (int, float)) and n > len(rows):
            return int(n), subject
    inner = sql_ast.set_limit(sql, None)
    try:
        got = await run_readonly(f"SELECT COUNT(*) AS n FROM ({inner}) q")
    except Exception:  # noqa: BLE001
        logger.warning("Focus Legacy list-total query failed — no total note", exc_info=True)
        return None
    n = _as_number((got or [{}])[0].get("n"))
    if not isinstance(n, (int, float)) or n <= len(rows):
        return None
    return int(n), subject


# FOCUS sheet TC-12 (testers 2026-09-29, re-run 2026-10-12): the numbers were right but the
# answer did not say how many payments the repeat-paid groups account for ("user will not
# subtract"), and the figures came from model SQL. One fixed query, one fixed answer.
_FL_DUP_SQL_SHAPE = _SqlMarker("fl-duplicates")


def _focus_legacy_duplicates_query(question: str, schemes: list[str], resolved: dict) -> "tuple[str, list, str] | None":
    if schemes != ["Focus Legacy"] or not _DUPLICATE_Q.search(question or ""):
        return None
    where, params = [], []
    for key, col in (("district", "lgd_district"), ("block", "lgd_block")):
        if (resolved or {}).get(key):
            params.append(str(resolved[key]).upper())
            where.append(f"UPPER({col}) = ${len(params)}")
    if any((resolved or {}).get(k) for k in ("village_code", "village_code_list", "district_list", "block_list",
                                             "assembly_constituency", "year_key", "financial_year")):
        return None
    w = ("WHERE " + " AND ".join(where)) if where else ""
    w2 = (w + " AND " if w else "WHERE ") + "date_of_remittance IS NOT NULL"
    sql = (f"/* fl-duplicates */ WITH g AS (SELECT pg_id, COUNT(*) AS n FROM curated.v_focus_legacy {w} GROUP BY pg_id), "
           f"s AS (SELECT pg_id, date_of_remittance FROM curated.v_focus_legacy {w2} "
           "GROUP BY pg_id, date_of_remittance HAVING COUNT(*) > 1) "
           "SELECT (SELECT COALESCE(SUM(n), 0) FROM g) AS payments, (SELECT COUNT(*) FROM g) AS producer_groups, "
           "(SELECT COUNT(*) FROM g WHERE n > 1) AS groups_paid_more_than_once, "
           "(SELECT COALESCE(SUM(n - 1), 0) FROM g WHERE n > 1) AS repeat_payments, "
           "(SELECT COUNT(*) FROM s) AS duplicate_records")
    return sql, params, sql


def _focus_legacy_duplicates_answer(rows: list[dict], display: dict) -> "str | None":
    if not rows:
        return None
    r = {k: int(_as_number(v) or 0) for k, v in rows[0].items()}
    place = display.get("block") or display.get("district")
    where = f" in {place}" if place else ""
    dup = r["duplicate_records"]
    head = ("No — there are no duplicate records: no producer group was paid twice on the same date."
            if dup == 0 else f"There are {dup:,} duplicate records (the same producer group paid twice on the same date).")
    return (f"{head} Under Focus Legacy{where}, {r['payments']:,} payments went to {r['producer_groups']:,} producer "
            f"groups. {r['groups_paid_more_than_once']:,} groups were paid more than once — repeat payments in later "
            f"tranches, not duplicates — and those repeats account for {r['repeat_payments']:,} of the "
            f"{r['payments']:,} payments ({r['payments']:,} − {r['producer_groups']:,}).")


# Focus Legacy sheet TC-24 (2026-10-12): "Compare the total FOCUS remittance between FY 2022-23
# and FY 2025-26" was answered with ONE combined total (₹32.69 crore) instead of each year's.
_FL_FY_COMPARE_MATCH = Matcher(Alt(W("compar", prefix=True), W("vs", "versus", "difference")))
_FL_FY_COMPARE_SQL_SHAPE = _SqlMarker("fl-fy-compare")


def _focus_legacy_fy_compare_query(question: str, schemes: list[str], resolved: dict) -> "tuple[str, list, str] | None":
    if schemes != ["Focus Legacy"] or not _FL_FY_COMPARE_MATCH.search(question or ""):
        return None
    ok, bad = _years_in_question(question, schemes)
    if bad or len(ok) < 2:
        return None
    fys = []
    for tok in ok:
        y = _parse_year_key(tok)
        if y is not None and f"{y}-{(y + 1) % 100:02d}" not in fys:
            fys.append(f"{y}-{(y + 1) % 100:02d}")
    if len(fys) < 2:
        return None
    if any((resolved or {}).get(k) for k in ("village_code", "village_code_list", "block_list", "district_list",
                                             "assembly_constituency")):
        return None
    where, params = ["financial_year_short = ANY($1::text[])"], [fys]
    for key, col in (("district", "lgd_district"), ("block", "lgd_block")):
        if (resolved or {}).get(key):
            params.append(str(resolved[key]).upper())
            where.append(f"UPPER({col}) = ${len(params)}")
    sql = ("/* fl-fy-compare */ SELECT financial_year_short, SUM(amount_disbursed) AS amount_disbursed, "
           "SUM(no_of_pg_members) AS memberships, COUNT(*) AS payments, COUNT(DISTINCT pg_id) AS producer_groups "
           f"FROM curated.v_focus_legacy WHERE {' AND '.join(where)} GROUP BY 1 ORDER BY 1")
    return sql, params, sql


def _focus_legacy_fy_compare_answer(rows: list[dict], params: list, display: dict) -> "str | None":
    if not rows or not params:
        return None
    by = {r["financial_year_short"]: r for r in rows}
    place = display.get("block") or display.get("district")
    where = f" in {place}" if place else ""
    lines, amts = [], []
    for fy in params[0]:
        r = by.get(fy)
        if r is None:
            lines.append(f"- **FY {fy}**: no Focus Legacy payments recorded{where}.")
            continue
        a = float(_as_number(r["amount_disbursed"]) or 0)
        amts.append((fy, a))
        lines.append(f"- **FY {fy}**: {_pmay_money(a)} to {int(_as_number(r['producer_groups']) or 0):,} producer "
                     f"groups ({int(_as_number(r['payments']) or 0):,} payments, "
                     f"{int(_as_number(r['memberships']) or 0):,} memberships x ₹5,000)")
    out = f"Focus Legacy remittance{where}, by financial year:\n" + "\n".join(lines)
    if len(amts) == 2:
        (f1, a1), (f2, a2) = amts
        hi = f1 if a1 >= a2 else f2
        out += (f"\n\nFY {hi} is higher by {_pmay_money(abs(a1 - a2))}.")
    return out


def _focus_legacy_answer_notes(question: str) -> list[str]:
    if not _DUPLICATE_Q.search(question or ""):
        return []
    return ["A producer group paid more than once is a REPEAT PAYMENT in a later tranche, NOT a "
            "duplicate group — never call those groups duplicates. A duplicate RECORD would be the "
            "same pg_id paid twice on the same date; report that count as the duplicates figure "
            "(0 means there are no duplicates), and mention the repeat-paid groups separately as "
            "legitimate repeat payments."]


# ── Focus Legacy: rows a per-place breakdown left out (KI-145) ──────────────
# "How many PGs are mapped to each block for West Khasi Hills?" — the model adds
# `AND lgd_block IS NOT NULL`, lists 5 blocks (921 PGs) and calls that the total
# "across all blocks", while 5 more PGs of the district have no block in the
# source (raw and DB: 88 rows statewide). Nothing told the officer they were
# left out (Focus Legacy use-case re-test 2026-09-29, TC-26). The left-out figure
# is read from the data — the same query without that filter — and stated.
_FL_PLACE_LEVELS = {"lgd_block": "block", "lgd_village_name": "village", "ac_name": "assembly constituency"}


# The model aliases the place column as often as not ("lgd_block AS block" —
# Ri Bhoi, bulk run 2026-09-29), so a result key is matched to its column here.
def _fl_key_forms(heads: tuple, stem: str) -> frozenset:
    """Every <head><stem>[_name] spelling, e.g. district, lgd_district_name."""
    return frozenset(h + stem + t for h in heads for t in ("", "_name"))


_FL_LEVEL_ALIAS = {"lgd_district": _fl_key_forms(("", "lgd_"), "district"),
                   "lgd_block": _fl_key_forms(("", "lgd_"), "block"),
                   "lgd_village_name": _fl_key_forms(("", "lgd_"), "village"),
                   "ac_name": _fl_key_forms(("", "assembly_"), "constituency") | {"ac_name"}}


def _fl_canon(key: str) -> "str | None":
    k = str(key).lower()
    return next((c for c, forms in _FL_LEVEL_ALIAS.items() if k in forms), None)


def _fl_breakdown_level(sql: str, rows: list[dict], levels: "dict | None" = None) -> "str | None":
    """The result key of the finest place level the query GROUPs BY, else None."""
    levels = levels or _FL_PLACE_LEVELS
    if not rows:
        return None
    trees = sql_ast.parse(sql)
    groups = [g for t in trees for g in t.find_all(exp.Group)]
    if not groups:
        return None
    # names the GROUP BY uses: columns (also inside UPPER() / COALESCE()), plus the
    # output a positional "GROUP BY 1" points at
    grouped = {c.name.lower() for g in groups for c in g.find_all(exp.Column)}
    outer = sql_ast.outer_select(trees[0])
    for g in groups:
        for e in g.expressions:
            if isinstance(e, exp.Literal) and not e.is_string and str(e.this).isdigit() and outer is not None \
                    and 1 <= int(e.this) <= len(outer.expressions):
                picked = outer.expressions[int(e.this) - 1]
                grouped.add((picked.alias_or_name or "").lower())
                grouped |= {c.name.lower() for c in picked.find_all(exp.Column)}
    found = [k for k in rows[0] if _fl_canon(k) in levels
             and (_fl_canon(k) in grouped or str(k).lower() in grouped)]
    order = list(levels)
    return max(found, key=lambda k: order.index(_fl_canon(k))) if found else None


def _fl_drop_not_null(sql: str, col: str) -> str:
    """The query without its AND-ed `col IS NOT NULL` filter (an emptied WHERE goes)."""
    col = col.lower()
    return sql_ast.remove_conditions(sql, lambda node: _fl_is_not_null(node, col))


async def _focus_legacy_unplaced_row(sql: str, rows: list[dict]) -> "tuple[str, dict] | None":
    """(level word, the result row for records with NO value at that level) for a
    Focus Legacy per-block / per-village / per-constituency breakdown, else None."""
    col = _fl_breakdown_level(sql, rows)
    if not col:
        return None
    hit = next((r for r in rows if r.get(col) in (None, "")), None)
    if hit is None:
        loose = _fl_drop_not_null(sql, _fl_canon(col))
        if loose == sql:
            return None
        loose = sql_ast.set_limit(loose, None)
        try:
            got = await run_readonly(loose)
        except Exception:  # noqa: BLE001 — a note, never a reason to fail the answer
            logger.warning("Focus Legacy unplaced-row query failed — no note", exc_info=True)
            return None
        hit = next((r for r in got or [] if r.get(col) in (None, "")), None)
    if hit is None:
        return None
    metrics = [(k, n) for k, v in hit.items() if k != col
               for n in [_as_number(v)] if n is not None and n > 0]
    return (_FL_PLACE_LEVELS[_fl_canon(col)], hit) if metrics else None


def _fl_metric_phrase(hit: dict) -> str:
    parts = []
    for k, v in hit.items():
        n = _as_number(v)
        if n is None or n <= 0 or _fl_canon(k):
            continue
        label = k.replace("_", " ")
        if _PMAY_MONEY_COL_MATCH.search(k) and not _PMAY_NOT_MONEY_COL_MATCH.search(k):
            parts.append(f"{label} {_pmay_money(n)}")
        else:
            parts.append(f"{int(n):,} {label}" if float(n).is_integer() else f"{n:,.2f} {label}")
    return ", ".join(parts)


def _focus_legacy_unplaced_note(level: str, hit: dict) -> str:
    return (f"Rows with NO {level} recorded in the source data are left out of the {level} list: "
            f"{_fl_metric_phrase(hit)}. Say in one sentence that these have no {level} recorded, and "
            f"never call the sum of the listed {level}s the total for the whole area.")


def _fl_unplaced_sentence(level: str, hit: dict) -> str:
    return (f"In addition, {_fl_metric_phrase(hit)} have no {level} recorded in the source data, "
            f"so they are not counted under any {level} above.")


def _focus_legacy_unplaced_guarantee(answer: str, level: str, hit: dict) -> str:
    """State the left-out figure exactly once, in digits. The composer's own version
    wrote it in words ("Two additional …") or without the number, and appending
    beside it said it twice (bulk run 2026-09-29), so its sentence is replaced."""
    lvl = _fl_sp(*level.split())
    said = Matcher(Alt(
        _fl_sp("no", lvl),
        _fl_sp(lvl, Opt(W("is", "was")),
               Alt(_fl_sp("not", W("recorded", prefix=True)), W("unknown", "missing", "blank", prefix=True))),
        _fl_sp("without", ("a", "an"), lvl),
        _fl_sp("remaining", Opt("producer"), ("group", "groups"))))
    kept = [s for s in _fl_split_after_stops(answer.strip()) if not said.search(s)]
    return (" ".join(kept).rstrip() + "\n\n" + _fl_unplaced_sentence(level, hit)).strip()


# ── Focus Legacy: per-place breakdowns, built from the rows ──────────────────
# "How many PGs are mapped to each block for <district>?" (bulk run 2026-09-29,
# all 12 districts): the composer dropped the per-block counts for West Jaintia
# Hills, called West Khasi Hills' 5 BLOCKS "5 producer groups", and wrote the
# left-out figure in words. The answer to a breakdown is fully determined by its
# rows, so it is written here. Every pg_id sits in exactly one district, block
# and village (verified 2026-09-29), so the per-place counts add up exactly.
_FL_BREAKDOWN_LEVELS = {"lgd_district": "district", **_FL_PLACE_LEVELS}
_FL_BREAKDOWN_MAX_ROWS = 100


# "Which Producer Groups are mapped to NENGKRA AWE village?" — the composer
# listed 11 names but rewrote one ("Bak 13 Nalsa Pepper Producer Group." became
# "… Pepper Group."; all-villages run 2026-09-29). A result that is only group
# ids / names (plus place labels) is a name list, written from the rows.
_FL_GROUP_ID_COLS = {"pg_id", "pg_name", "name_of_pg", "producer_group", "group_name"}


async def _fl_add_group_names(rows: list[dict]) -> list[dict]:
    """A Focus Legacy result of bare pg_ids ("SELECT DISTINCT pg_id … WHERE
    village_code = 272784") answered "which producer groups?" with ids only
    (all-villages run 2026-09-29, KI-165). Add each group's name from the data."""
    if not rows or "pg_name" in rows[0] or "pg_id" not in rows[0] or len(rows) > _FL_BREAKDOWN_MAX_ROWS:
        return rows
    if any(k != "pg_id" and not _fl_canon(k) for k in rows[0]):
        return rows
    try:
        names = {r["pg_id"]: r["pg_name"] for r in await fetch_rows(
            "SELECT pg_id, MAX(pg_name) AS pg_name FROM curated.v_focus_legacy WHERE pg_id = ANY($1::text[]) "
            "GROUP BY pg_id", [[str(r["pg_id"]) for r in rows]])}
    except Exception:  # noqa: BLE001 — keep the ids
        return rows
    return [{**r, "pg_name": names.get(r["pg_id"])} for r in rows]


def _focus_legacy_group_list_answer(rows: list[dict], display: dict,
                                    total: "int | None" = None) -> "str | None":
    if not rows or "pg_name" not in rows[0] or len(rows) > _FL_BREAKDOWN_MAX_ROWS:
        return None
    if any(k not in _FL_GROUP_ID_COLS and not _fl_canon(k) for k in rows[0]):
        return None
    names = []
    for r in rows:
        if r.get("pg_name"):
            names.append(f"- {r['pg_name']}" + (f" ({r['pg_id']})" if r.get("pg_id") else ""))
    if not names:
        return None
    n = max(total or 0, len(names))
    where = [str(display[k]) + (" village" if k == "village" else " block" if k == "block" else
                                " constituency" if k == "assembly_constituency" else "")
             for k in ("village", "block", "assembly_constituency", "district") if display.get(k)]
    scope = f" mapped to {', '.join(where)}" if where else ""
    head = f"{n:,} producer group{'s are' if n != 1 else ' is'}{scope} in the Focus Legacy data"
    if n > len(names):
        head += f"; the first {len(names)} are listed"
    return head + ":\n\n" + "\n".join(names)


def _fl_metric_value(k: str, n) -> str:
    if _PMAY_MONEY_COL_MATCH.search(k) and not _PMAY_NOT_MONEY_COL_MATCH.search(k):
        return _pmay_money(n).split(" (")[0]
    return f"{int(n):,}" if float(n).is_integer() else f"{n:,.2f}"


def _focus_legacy_breakdown_answer(sql: str, rows: list[dict], display: dict,
                                   unplaced: "tuple[str, dict] | None") -> "str | None":
    if not rows or len(rows) > _FL_BREAKDOWN_MAX_ROWS:
        return None
    level_col = _fl_breakdown_level(sql, rows, _FL_BREAKDOWN_LEVELS)
    if not level_col:
        return None
    level = _FL_BREAKDOWN_LEVELS[_fl_canon(level_col)]
    labels = [k for k in rows[0] if k != level_col and _fl_canon(k)]
    metrics = [k for k in rows[0] if k != level_col and k not in labels
               and not _fl_is_code_key(k)]
    # only place labels and plain numbers — anything else (a date, a year, a name)
    # is a different shape of answer and stays with the composer
    if not metrics or len(metrics) > 3 or any(
            _as_number(r.get(k)) is None for r in rows for k in metrics if r.get(k) is not None):
        return None
    null_rows = [r for r in rows if r.get(level_col) in (None, "")]
    listed = [r for r in rows if r.get(level_col) not in (None, "")]
    if not listed:
        return None
    if null_rows and not unplaced:
        unplaced = (level, null_rows[0])
    lim = sql_ast.outer_limit(sql or "")
    truncated = bool(lim and lim > 0) and len(rows) == lim and lim < 1000

    def words(k):
        return k.replace("_", " ")

    def line(r):
        name = _place_title(r[level_col])
        ctx = ", ".join(_place_title(r[c]) for c in labels if r.get(c))
        vals = ", ".join(f"{_fl_metric_value(k, _as_number(r.get(k)) or 0)} {words(k)}" for k in metrics)
        return f"- {name}{f' ({ctx})' if ctx else ''}: {vals}"

    scope_bits = [str(display.get(k)) for k in ("assembly_constituency", "district", "block", "village")
                  if display.get(k)]
    scope = f" in {', '.join(scope_bits)}" if scope_bits else ""
    yr = next((str(display[k]) for k in ("year", "financial_year") if display.get(k)), None)
    period = f", {yr}" if yr else ""
    head = (f"Top {len(listed)} {level}s{scope}{period} by {words(metrics[0])}:" if truncated
            else f"Focus Legacy {words(metrics[0])} by {level}{scope}{period} — {len(listed)} "
                 f"{level}{'s' if len(listed) != 1 else ''}:")
    out = [head, ""] + [line(r) for r in listed]
    if not truncated and len(listed) > 1:
        tot = {k: sum((_as_number(r.get(k)) or 0) for r in listed) for k in metrics}
        together = ", ".join(f"{_fl_metric_value(k, v)} {words(k)}" for k, v in tot.items())
        out += ["", f"Together, the {len(listed)} {level}s above account for {together}."]
        if unplaced:
            extra = {k: _as_number(unplaced[1].get(k)) or 0 for k in metrics}
            if any(extra.values()):
                out.append(_fl_unplaced_sentence(unplaced[0], unplaced[1]) + " Including them, the total is "
                           + ", ".join(f"{_fl_metric_value(k, tot[k] + extra[k])} {words(k)}" for k in metrics)
                           + ".")
    elif unplaced:
        out += ["", _fl_unplaced_sentence(*unplaced)]
    return "\n".join(out)


# ── Focus Legacy: month numbers and bare rupees (KI-147) ─────────────────────
# "How much was remitted during each month for FY 2022-23?" came back as
# "52,035,000.00 in month 4 and 89,755,000.00 in month 5", and single totals as
# "54205000.00" (re-test 2026-09-29, TC-18/21/23). Values were right; the
# presentation is fixed here from the result cells only.
_FL_MONTH_COL_MATCH = frozenset(h + "month" + t for h in ("", "remittance_", "payment_")
                             for t in ("", "_num", "_no", "_number", "_of_year"))


def _fl_is_code_key(k: str) -> bool:
    """A code / id / key column: holds "code", or is "id" / ends "_id" / "_key"."""
    kl = k.lower()
    return "code" in kl or kl == "id" or kl.endswith(("_id", "_key"))


def _fl_replace_date(answer: str, s: str, label: str) -> str:
    """Every `s` (optionally followed by "T00:00:00" / " 00:00:00" and "+00:00") -> label."""
    out, last = [], 0
    while s:
        k = answer.find(s, last)
        if k < 0:
            break
        e = k + len(s)
        if answer[e:e + 1] in ("T", " ") and answer[e + 1:e + 9] == "00:00:00":
            e += 9
            if answer.startswith("+00:00", e):
                e += 6
        out.append(answer[last:k] + label)
        last = e
    out.append(answer[last:])
    return "".join(out)


def _fl_fy_start_in_sql(sql: str) -> "int | None":
    """The start year of a `financial_year[_short] = 'YYYY-YY'` filter, else None."""
    for node in sql_ast.filter_conditions(sql or "", "financial_year", "financial_year_short"):
        hit = _fl_col_vs_literal(node, {"financial_year", "financial_year_short"}) \
            if isinstance(node, exp.EQ) else None
        if hit:
            head, sep, tail = hit[1].partition("-")
            if len(head) == 4 and head.isdigit() and sep and tail.isdigit() and len(tail) in (2, 4):
                return int(head)
    return None


def _fl_month_number_matcher(m: int) -> Matcher:
    """"month 4" / "month 04" (whitespace between) for month number m."""
    return Matcher(_fl_sp("month", W(str(m), f"0{m}")))


_FL_MONTH_NAMES = tuple(calendar.month_name[1:])


def _fl_month_repl(h: Hit, label: str) -> str:
    """The label, unless a month name already follows "month N" after whitespace only."""
    rest = h.string[h.end():]
    if rest.lstrip().lower().startswith(tuple(n.lower() for n in _FL_MONTH_NAMES)):
        return h.group(0)
    return label


# "memberships paid for" already in the answer (any word ending "membership(s)")
_FL_MEMBERSHIPS_PAID_FOR = Matcher(_fl_sp(Pred(lambda w: w.lower().endswith(("membership", "memberships"))),
                                          "paid", W("for", prefix=True)))


def _focus_legacy_month_labels(answer: str, sql: str, rows: list[dict]) -> str:
    if not answer or not rows:
        return answer
    col = next((k for k in rows[0] if str(k).lower() in _FL_MONTH_COL_MATCH), None)
    if not col:
        return answer
    fy_sql = _fl_fy_start_in_sql(sql)
    for r in rows[:24]:
        v = r.get(col)
        if isinstance(v, (datetime.date, datetime.datetime)):
            label = v.strftime("%B %Y")
            for s in {v.isoformat(), str(v), v.strftime("%Y-%m-%d"), v.strftime("%Y-%m")}:
                answer = _fl_replace_date(answer, s, label)
            continue
        m = _as_number(v)
        if m is None or not float(m).is_integer() or not 1 <= int(m) <= 12:
            continue
        m = int(m)
        start = None
        fy = str(r.get("financial_year_short") or r.get("financial_year") or "")
        if fy[:4].isdecimal() and len(fy) > 4 and fy[4] == "-":
            start = int(fy[:4])
        elif fy_sql:
            start = fy_sql
        yr = _as_number(r.get("year") or r.get("calendar_year"))
        year = int(yr) if yr else (start + (0 if m >= 4 else 1) if start else None)
        label = calendar.month_name[m] + (f" {year}" if year else "")
        answer = _fl_month_number_matcher(m).sub(lambda h, _l=label: _fl_month_repl(h, _l), answer)
    return answer


_FL_MEMBERSHIP_NOTE = ("Counted as memberships paid for, not as distinct people — a group paid in "
                       "more than one year is counted each time.")


def _focus_legacy_answer_guarantees(answer: str, sql: str, rows: list[dict]) -> str:
    answer = _focus_legacy_month_labels(answer, sql, rows)
    # a long list keeps plain ₹ grouping — a lakh/crore gloss on every line is noise
    fmt = _pmay_money if len(rows or []) <= 5 else (lambda v: _pmay_money(v).split(" (")[0])
    answer = _pmay_rupee_format(answer, rows, fmt=fmt, column_totals=True)
    # A member total is a SUM over payments. The SME default
    # (focuslegacy_default_rules.yaml, bare_member_term) says it must be read as
    # "memberships paid for, not distinct people"; answered bare, "102,021 PG
    # members" read as a headcount (FOCUS TC-16/17, test run 2026-10-06).
    if rows and _fl_sums_column(sql or "", "no_of_pg_members") \
            and not _FL_MEMBERSHIPS_PAID_FOR(answer):
        answer = answer.rstrip() + " " + _FL_MEMBERSHIP_NOTE
    return answer


# "How many total beneficiaries are available under the FOCUS scheme?" returned one
# figure, 102,021, labelled "beneficiaries". Focus Legacy holds no person-level
# count, so the SME default for an unqualified measure is all four
# (focuslegacy_default_rules.yaml, multi_measure_columns_unspecified: "Showing
# payments, groups, memberships and amount disbursed"); the tester's expected
# result lists exactly those (FOCUS TC-10, test run 2026-10-06).
_FL_BENEFICIARY_ASK = Matcher(W("beneficiar", prefix=True))
def _fl_has_count_star(tree) -> bool:
    return any(isinstance(c.this, exp.Star) for c in tree.find_all(exp.Count))


def _fl_has_group_count(tree) -> bool:
    """COUNT(DISTINCT pg_id) under an alias that names groups."""
    for a in tree.find_all(exp.Alias):
        cnt = a.this
        d = cnt.this if isinstance(cnt, exp.Count) else None
        if isinstance(d, exp.Distinct) and len(d.expressions) == 1 \
                and _fl_col_name(d.expressions[0]) == "pg_id" and "group" in (a.alias or "").lower():
            return True
    return False


_FL_FOUR_MEASURES = {
    "payments": _fl_has_count_star,
    # named as groups: "COUNT(DISTINCT pg_id) AS beneficiaries" was answered
    # "11,906 total beneficiaries" — those are producer groups, not people
    "producer groups": _fl_has_group_count,
    "memberships": lambda tree: _fl_sums_column(tree, "no_of_pg_members"),
    "amount disbursed": lambda tree: _fl_sums_column(tree, "amount_disbursed"),
}


_FL_FOUR_SELECT = ("SELECT COUNT(*) AS payments, COUNT(DISTINCT pg_id) AS producer_groups, "
                   "SUM(no_of_pg_members) AS memberships, SUM(amount_disbursed) AS amount_disbursed ")


def _focus_legacy_beneficiary_four_measures(question: str, schemes: list[str], sql: str) -> str:
    """A Focus Legacy beneficiary TOTAL gets the four SME measures, built here on the
    model's own FROM / WHERE. Asking the model for them ping-ponged: the guard below
    demanded COUNT(*) AS payments and the verifier rejected COUNT(*) for "total
    beneficiaries" until the repair budget ran out (FOCUS TC-10, 2026-10-06)."""
    if schemes != ["Focus Legacy"] or not sql or not _FL_BENEFICIARY_ASK.search(question or ""):
        return sql
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or sql_ast.has_group_by(tree) or sql_ast.has_cte(tree) \
            or any(True for _ in tree.find_all(exp.SetOperation)):
        return sql
    if "curated.v_focus_legacy" not in sql_ast.tables(tree, qualified=True):
        return sql
    four = sql_ast.parse_one(_FL_FOUR_SELECT + "FROM curated.v_focus_legacy")
    new = tree.copy()
    new.set("expressions", [e.copy() for e in four.expressions])
    for part in ("distinct", "order", "limit", "offset"):
        new.set(part, None)
    out = sql_ast.to_sql(new)
    if out == sql_ast.to_sql(tree):
        return sql
    if out != sql:
        logger.info("Focus Legacy: beneficiary total built with the four SME measures")
    return out


def _focus_legacy_beneficiary_measures_missing(question: str, schemes: list[str], sql: str) -> "str | None":
    """Repair instruction when a Focus Legacy 'beneficiaries' total lacks one of
    the four SME measures; None for anything else (a breakdown keeps its shape)."""
    if schemes != ["Focus Legacy"] or not sql or not _FL_BENEFICIARY_ASK.search(question or ""):
        return None
    trees = sql_ast.parse(sql)
    if not trees or sql_ast.has_group_by(trees):
        return None
    missing = [k for k, has in _FL_FOUR_MEASURES.items() if not any(has(t) for t in trees)]
    if not missing:
        return None
    return ("Focus Legacy has no person-level 'beneficiary' count, so a beneficiary total reports all "
            "four measures in ONE row: COUNT(*) AS payments, COUNT(DISTINCT pg_id) AS producer_groups, "
            "SUM(no_of_pg_members) AS memberships, SUM(amount_disbursed) AS amount_disbursed. Keep every "
            "filter exactly as it was. Missing now: " + ", ".join(missing) + ".")


# ── Focus Legacy: "is there a PG named X?" / "how many members are there in X?" ──
# Bulk QA of 290 sampled producer groups (2026-09-25) found the model-written SQL
# unreliable for these two fixed-shape questions: 52 of 131 member-count answers
# were wrong. When several groups share a name ("Chibasal" matches 73) it ended
# the query in LIMIT 1 and reported one arbitrary group's size; it rewrote names
# ("Chelchak Pineapple P.g" -> '%chelchak pineapple p.g.%', zero rows); and some
# never reached the data at all. The answer is fully determined by the data, so
# it is built here: match the name on its WORDS (ignoring "PG" / "Producer
# Group" / punctuation, each word anchored at a word start), rank groups whose
# whole name is exactly those words first, and when several groups match, list
# them instead of guessing.
_PG_STOP_WORDS = {"pg", "pgs", "p", "g", "producer", "producers", "group", "groups", "grp",
                  "the", "shg", "named", "called"}
# "how many members are there in <name>", "how many members does <name> have",
# "what is the member count of <name>"; the name is read by _pg_size_name.
_PG_SIZE_QUESTION = Matcher(
    Cap(Seq(START, Alt(
        _fl_sp("how", "many", Opt("pg"), ("member", "members"),
               Opt(Alt(_fl_sp("are", Opt("there")), _fl_sp("were", Opt("there")), _fl_sp("is", "there"))),
               ("in", "of")),
        _fl_sp("how", "many", "members", "does"),
        _fl_sp("what", "is", "the",
               Alt(_fl_sp("member", "count"), _fl_sp("group", "size"), _fl_sp("number", "of", "members")),
               ("of", "in", "for"))),
        Opt("the"), Opt(_fl_sp(Alt(_fl_sp("producer", "group"), "pg", "group"), ("named", "called"))),
        sep="space"), "pre"),
    Cap(Rep(ANY, 1, None, lazy=True), "name"), END)


def _pg_tail_plain(t: str) -> bool:
    """`t` is only whitespace and '?', '.', '!' (whitespace, then the marks, then whitespace)."""
    return t.lstrip().lstrip("?.!").strip() == ""


def _pg_size_tail_ok(rest: str) -> bool:
    """What may follow the group name in a size question: an optional "have", then
    closing marks."""
    if _pg_tail_plain(rest):
        return True
    if rest[:1].isspace():
        t = rest.lstrip()
        return t[:4].lower() == "have" and _pg_tail_plain(t[4:])
    return False


def _pg_size_name(q: str) -> "str | None":
    """The group name of a size question (the shortest text after the question
    words that leaves only "have" and closing marks), else None."""
    h = _fl_at_start(_PG_SIZE_QUESTION, q)
    if h is None:
        return None
    pre_end = h.end("pre")
    gap = q[pre_end:h.start("name")]
    if not gap[:1].isspace():
        return None
    s = q[pre_end + len(gap) - len(gap.lstrip()):]
    for n in range(1, len(s) + 1):
        if s[n - 1] == "\n":
            return None                      # the name never runs over a line break
        if _pg_size_tail_ok(s[n:]):
            return s[:n]
    return None


# Scope phrases a clarification chip appends ("... for Focus Legacy for all of
# Meghalaya, all years") — not part of a group name. Cut by _pg_cut_scope_tail.
_PG_SCOPE_TAIL = Matcher(Seq(Alt(
    _fl_sp(("for", "in", "under", "across", "within"), Opt("the"), Alt(
        _fl_sp("focus", "legacy"), "focus", _fl_sp("all", "of", "meghalaya"), "meghalaya",
        _fl_sp("all", Opt("the"), Opt("financial"), "years", Opt("combined")))),
    _fl_sp("all", Opt("financial"), "years", Opt("combined")),
    W("scheme")), END))


def _pg_cut_scope_tail(text: str) -> str:
    """`text` without a trailing scope phrase (with the comma / spaces before it and
    any closing marks after it)."""
    h = _PG_SCOPE_TAIL.search(text)
    if h is None or not _pg_tail_plain(text[h.end():]):
        return text
    k = h.start()
    while k > 0 and text[k - 1].isspace():
        k -= 1
    if k > 0 and text[k - 1] == ",":
        k -= 1
    while k > 0 and text[k - 1].isspace():
        k -= 1
    return text[:k]


_PG_PLACE_WORDS = Matcher(W("district", "block", "village", "constituency", "state", "meghalaya", "hills"))
_PG_SUFFIX_WORD = Matcher(Alt(_FlDotSpaceSeq("p", "g"), W("pg", "pgs", "group"),
                              _fl_sp("producer", ("group", "groups"))))
_PG_REST_PREPS = ("in", "for", "under", "from", "at", "within", "across")
_PG_IS_THERE = Matcher(Seq(START, ("is", "are"), "there", ("any", "a", "an"), sep="space"))
_PG_NAMED_LABEL = Matcher(_fl_sp(Alt(_fl_sp("producer", "group"), "pg"), ("named", "called")))
_PG_ADMIN_LEVELS = ("district", "block", "village", "constituency", "state", "meghalaya")


def _pg_drop_admin_suffix(s: str, kinds: tuple) -> str:
    """`s` without a final " <kind>" (or " c&rd <kind>"), whitespace before it included."""
    for kind in kinds:
        if s.endswith(kind):
            pre = s[:len(s) - len(kind)]
            if pre[-1:].isspace():
                pre = pre.rstrip()
                if pre.endswith("c&rd") and pre[:-4][-1:].isspace():
                    pre = pre[:-4].rstrip()
                return pre
    return s


def _pg_rest_is_place(rest: str) -> bool:
    """Whether the words after a group name are a place phrase ("in Betasing
    block", "in Nongstoin") rather than more of the name ("In One Ginger Producer
    Group" in "All In One Ginger Producer Group" — all-PG run 2026-09-29)."""
    t = _fl_lead_strip(rest)
    if t[:5].lower() == "there" and (len(t) == 5 or not _fl_word_char(t[5])):
        return True
    head = t.split(None, 1)
    if len(head) < 2 or head[0].lower() not in _PG_REST_PREPS:
        return False
    p = head[1].rstrip()
    if p[:3].lower() == "the" and p[3:4].isspace() and p[3:].strip():
        p = p[3:].lstrip()
    return bool(_PG_PLACE_WORDS.search(p)) or \
        _pg_drop_admin_suffix(p.lower(), ("block", "district")) in _known_place_names()


_PG_GENERIC_LEAD = ("focus legacy", "legacy focus", "focus", "the", "all", "its")
_PG_GENERIC_GROUP = ("producer groups", "producer group", "pgs", "pg", "groups", "group")


def _pg_generic_scheme_groups(name: str) -> bool:
    """Whether a "name" is just the scheme's groups, optionally in a place:
    "Focus Legacy producer groups", "Focus Legacy producer groups in East Khasi
    Hills". A follow-up rewrite ("how many members are there in Focus Legacy
    producer groups in East Khasi Hills") was looked up as a group with that
    name and lost the district (context audit 2026-10-19)."""
    t = collapse_ws((name or "").lower().strip(" ?.!,"))
    stripped = True
    while stripped:
        stripped = False
        for lead in _PG_GENERIC_LEAD:
            if t.startswith(lead + " ") or t == lead:
                t, stripped = t[len(lead):].strip(), True
    found_group = False
    for g in _PG_GENERIC_GROUP:
        if t.startswith(g + " ") or t == g:
            t, found_group = t[len(g):].strip(), True
            break
    if not found_group:
        return False
    if not t:
        return True
    head = t.split(None, 1)
    if len(head) == 2 and head[0] in ("in", "of", "across", "for", "under"):
        place = head[1].strip()
        if place[:4] == "the ":
            place = place[4:]
        return place in _known_place_names() or \
            _pg_drop_admin_suffix(place, ("block", "district")) in _known_place_names() or \
            place in ("meghalaya", "the state", "all districts", "ri bhoi") or \
            place.endswith((" hills", " district", " block"))
    return False


def _pg_name_question(question: str, allow_weak: bool = False) -> "tuple[str, str] | None":
    """('exists' | 'size', typed name) for a group-name question, else None.
    With allow_weak, a size question whose name holds a place word and no group
    word ("members in Green Hills") comes back as 'size?': a group only if one is
    named exactly that (checked by the caller against the data)."""
    q = (question or "").strip()
    kind, name = None, None
    size_name = _pg_size_name(q)
    if size_name is not None:
        kind, name = "size", size_name
    else:
        m = _PG_NAMED_ENTITY.search(q)
        if m and _fl_at_start(_PG_IS_THERE, q):
            tail = q[m.end("name"):]
            rest = _pg_cut_scope_tail(tail).strip(" ?.!")
            # "…named X in Betasing block" carries its own place: leave it to the
            # full pipeline, which filters on that place.
            if _pg_rest_is_place(rest):
                return None
            # Otherwise the name simply ran on — a comma inside it ("Ka Seng Ki
            # Nongrep Jhur, Shkenpyrsit") or more words than the matcher takes.
            kind, name = "exists", f"{m.group('name')} {rest}".strip() if rest else m.group("name")
    if not kind:
        return None
    prev = None
    while prev != name:
        prev, name = name, _pg_cut_scope_tail(name).strip(" ?.!,\"'“”")
    if not name:
        return None
    if _pg_generic_scheme_groups(name):
        return None
    if _PG_PLACE_WORDS.search(name):
        # "Green Hills Producer Group", "Umdang Dong Block Producer Group": a place
        # word inside a name the user marked as a group (named / "Producer Group")
        # is part of the name — 20 stored names were unreachable (2026-09-29).
        # A place with a group word bolted on ("West Garo Hills producer groups")
        # is still a place question.
        core = _PG_SUFFIX_WORD.sub(" ", name).strip().lower()
        core = collapse_ws(core)
        if kind == "exists" or (_PG_SUFFIX_WORD.search(name) and core not in _known_place_names() and core.rsplit(" ", 1)[-1] not in
                {w + t for w in _PG_ADMIN_LEVELS for t in ("", "s")}):
            pass
        elif allow_weak and kind == "size" and core not in _known_place_names() and _pg_drop_admin_suffix(
                core, ("blocks", "districts", "villages", "constituencys", "block", "district", "village",
                       "constituency")) not in _known_place_names():
            kind = "size?"
        else:
            return None
    # A bare district/block name is a place question ("members in Nongstoin"),
    # unless the user marked it as a group.
    if kind == "size" and not _PG_SUFFIX_WORD.search(name) \
            and not _PG_NAMED_LABEL(q):
        if name.lower() in _known_place_names():
            return None
    if not [t for t in _pg_name_tokens(name) if t not in _PG_STOP_WORDS]:
        return None
    return kind, name


def _pg_name_tokens(text: str) -> list[str]:
    # Letters of any script, not just a-z: 6 stored names are mis-encoded text
    # ("AÃ£Æ’Ã¦…we Producer Group"), and an ASCII-only read left "a we", which
    # matched a different group, "A.we" (all-PG run 2026-09-29). Tokens stay
    # letters/digits only, so they remain safe inside the SQL match literal.
    return [t for t in alnum_only((text or "").lower(), space=True).split() if t not in _PG_STOP_WORDS]


async def _focus_legacy_pg_name_answer(question: str) -> "dict | None":
    parsed = _pg_name_question(question, allow_weak=True)
    if parsed is None:
        return None
    kind, name = parsed
    toks = _pg_name_tokens(name)

    def _where(col: str, word_end: bool) -> str:
        # tokens are letters/digits only, so they are safe inside the LIKE literals
        end = " " if word_end else ""
        # The name lower-cased with every character that is not a letter or digit
        # ("_" included, so 25 matches "Erifa_25": all-PG run 2026-09-29, KI-158)
        # turned into a space, padded with spaces: "% tok %" is then a whole word,
        # "% tok%" a word start.
        words = ("(' ' || ARRAY_TO_STRING(ARRAY(SELECT CASE WHEN ASCII(c) BETWEEN 48 AND 57 "
                 "OR LOWER(c) <> UPPER(c) THEN c ELSE ' ' END "
                 f"FROM UNNEST(STRING_TO_ARRAY(LOWER({col}), NULL)) WITH ORDINALITY AS u(c, i) "
                 "ORDER BY i), '') || ' ')")
        likes = ", ".join(f"'% {t}{end}%'" for t in toks)
        return f"{words} LIKE ALL (ARRAY[{likes}])"

    def _sql(where: str) -> str:
        return ("SELECT pg_id, MAX(pg_name) AS pg_name, MAX(lgd_district) AS district, "
                "MAX(lgd_block) AS block, MAX(no_of_pg_members) AS group_size, "
                "MIN(no_of_pg_members) AS smallest_recorded_size, COUNT(*) AS payments, "
                "SUM(amount_disbursed) AS amount_disbursed\n"
                f"FROM curated.v_focus_legacy\nWHERE {where}\nGROUP BY pg_id\nORDER BY pg_id\nLIMIT 1000")

    # Whole words first ("ma" must not match every "Mawlai…"); word prefixes only
    # when nothing matches whole ("Bak15" typed for "Bak-15" still resolves).
    # Earlier spellings the raw file still carries ("Drongpa Pg" for the group now
    # named "Dronpa") are searched TOGETHER with current names: 389 of 1,635 older
    # spellings were "not found", and an older spelling can equal another group's
    # current name ("Ten Star Producer Group"), so a current-name hit must not end
    # the search (all-PG run 2026-09-29). The DB keeps every spelling in
    # v_focus_legacy_pg_search (KI-020).
    rows, alias_of = [], {}
    for word_end in (True, False):
        aw = _where("matched_alias", word_end)
        hits = await run_readonly(
            "SELECT DISTINCT pg_id, matched_alias FROM curated.v_focus_legacy_pg_search "
            f"WHERE NOT is_current AND {aw} LIMIT 1000")
        alias_of = {}
        for h in hits:
            alias_of.setdefault(h["pg_id"], []).append(str(h["matched_alias"]))
        where = _where("pg_name", word_end)
        if alias_of:
            where = (f"(({where}) OR pg_id IN (SELECT pg_id FROM curated.v_focus_legacy_pg_search "
                     f"WHERE NOT is_current AND {aw}))")
        sql = _sql(where)
        rows = await run_readonly(sql)
        if rows:
            break
    exact = [r for r in rows if _pg_name_tokens(r.get("pg_name")) == toks
             or any(_pg_name_tokens(a) == toks for a in alias_of.get(r.get("pg_id"), []))]
    if kind == "size?":
        # "members in Green Hills": a group only when one is named exactly that
        if not exact:
            return None
        kind = "size"
    ranked = exact + [r for r in rows if r not in exact]

    def place(r):
        bits = [f"{str(r['block']).title()} block" if r.get("block") else None,
                str(r.get("district") or "").title() or None]
        return ", ".join(b for b in bits if b)

    def line(r):
        return (f"- **{r['pg_name']}** ({r['pg_id']}) — {place(r)}: "
                f"{r['group_size']} member{'s' if r['group_size'] != 1 else ''}")

    single = exact[0] if len(exact) == 1 else (rows[0] if len(rows) == 1 else None)
    if not rows:
        answer = (f"No producer group named “{name}” was found in the Focus Legacy data "
                  "(names are matched on their words, ignoring “PG” / “Producer Group”)."
                  + (" So there is no member count to report." if kind == "size" else ""))
    elif single is not None:
        r = single
        if kind == "size":
            answer = (f"**{r['pg_name']}** ({r['pg_id']}, {place(r)}) has **{r['group_size']} "
                      f"member{'s' if r['group_size'] != 1 else ''}**.")
            if r["smallest_recorded_size"] != r["group_size"]:
                answer += (f" Its recorded size changed between its {r['payments']} payments "
                           f"({r['smallest_recorded_size']} to {r['group_size']}); "
                           f"{r['group_size']} is the largest recorded.")
        else:
            answer = (f"Yes — **{r['pg_name']}** ({r['pg_id']}) is a Focus Legacy producer group in "
                      f"{place(r)}, with {r['group_size']} members and {r['payments']} "
                      f"payment{'s' if r['payments'] != 1 else ''} totalling "
                      f"{_pmay_money(_as_number(r['amount_disbursed']) or 0)}.")
        if alias_of.get(r["pg_id"]):
            answer += f" “{name}” is an earlier recorded spelling of this group's name."
        if len(rows) > 1:
            answer += (f" ({len(rows) - 1} other group{'s have' if len(rows) > 2 else ' has'} "
                       f"“{name}” within a longer name.)")
    else:
        head = (f"Yes — {len(rows)} producer groups match “{name}”" if kind == "exists"
                else f"{len(rows)} producer groups match “{name}”, so the member count depends on "
                     "which one you mean")
        if exact:
            head += f" ({len(exact)} named exactly that)"
        _via_old = [r for r in ranked[:10] if alias_of.get(r["pg_id"])
                    and _pg_name_tokens(r.get("pg_name")) != toks]
        if _via_old:
            head += (f" ({len(_via_old)} of those shown matched on an earlier recorded spelling; "
                     "current names are shown)")
        shown = ranked[:10]
        answer = head + ":\n\n" + "\n".join(line(r) for r in shown)
        if len(ranked) > len(shown):
            answer += f"\n\n…and {len(ranked) - len(shown)} more in the table."
        if kind == "size":
            answer += "\n\nTell me the PG ID or the district to pin down one group."
    logger.info("Focus Legacy PG-name %s question for %r: %d match(es), %d exact", kind, name,
                len(rows), len(exact))
    return {"route": "data", "intent": "DATA", "confidence": "high", "schemes": ["Focus Legacy"],
            "resolved_entities": {}, "sql": sql, "sql_query": sql, "row_count": len(rows),
            "rows": ranked[:20], "data": ranked, "answer": answer}


# ════ clarifications ══════════════════════════════════════════════════════════════════════════════════
# Focus Legacy holds bank_name and ifsc_code (v_focus_legacy), so only an
# account-number / transfer-status question is refused for it.
def _fl_joined_prefix(a: str, b: str):
    """`a b…`, `a-b…` or `ab…` (b is a word start)."""
    return Alt(Seq(a, W(b, prefix=True)), W(a + b, prefix=True))


# "payments into <bank> accounts" names a bank (held); only a detail word after
# "bank account" ("numbers", "details", "status") asks for what is not.
_FOCUS_LEGACY_BANK_NOT_HELD = Matcher(Alt(
    Seq(_fl_joined_prefix("bank", "account"),
        W("number", "numbers", "no", "nos", "detail", "details", "status", "holder", "holders", "info",
          "information", "wise", "id", "ids")),
    _fl_joined_prefix("account", "number"), _fl_joined_prefix("bank", "transfer"), W("dbt")))


# ════ mentions ════════════════════════════════════════════════════════════════════════════════════════
# A name the question itself introduces as a PRODUCER GROUP. Focus Legacy group
# names routinely collide with real places ("Nongstoin PG", "Mairang Producer
# Group") because groups are named after where they are, so the LLM extractor
# tags them as a block or village despite being told not to — and the geography
# branches then ask "did you mean the block or the village?" about a name the
# user never offered as a place (reported 2026-09-23).
_PG_NAMED_PREFIX = Matcher(_fl_sp(
    Alt(Joined("producer", ("group", "groups")), W("pg", "pgs", "group", "groups")),
    Alt("named", "called", _fl_sp("by", "the", "name", "of"))))
_PG_NAME_STOP_CHARS = '?"\u201c\u201d'
_PG_NAME_OPEN_QUOTES = '"\u201c\u2018\''
_PG_NAME_CLOSE_QUOTES = '"\u201d\u2019\''
_PG_NAME_FOLLOW_WORDS = ("in", "for", "under", "from", "at", "within", "across", "there")


class _PgNamedEntity:
    """Finds "<producer group | pg | group>[s] <named | called | by the name of>
    [as] <name>". `.search(text)` returns a Hit whose group("name") is the name.

    Name words may start with a digit or a bracket — "Bak 15 Banana Dijogre",
    "Ieintylli Pg (cham Cham Pig Fattening Pg)" — and run to 8 words. Any
    non-space run (without '?' or a double quote) is a name word: 219 of the
    9,452 stored names have words like "-13", "Pg-83/21", "[pg]" or a lone "'"
    (Focus Legacy all-PG run 2026-09-29), and the old letter/digit/bracket start
    missed every one. The name ends the sentence, or is followed by a place /
    scope phrase: "named Nongstoin PG in Betasing block" — without that second
    ending the whole matcher missed and "Nongstoin" was resolved as a BLOCK.
    The fewest words that reach such an ending are taken."""

    @staticmethod
    def _word_end(text: str, p: int) -> int:
        n = len(text)
        while p < n and not text[p].isspace() and text[p] not in _PG_NAME_STOP_CHARS:
            p += 1
        return p

    @staticmethod
    def _ending(text: str, p: int) -> "int | None":
        """Match end when the name may stop at p (optional closing quote, spaces,
        then '?', '.', ',', ';', ':', the end, or a place / scope word), else None."""
        n = len(text)
        for p2 in ((p + 1, p) if p < n and text[p] in _PG_NAME_CLOSE_QUOTES else (p,)):
            q = p2
            while q < n and text[q].isspace():
                q += 1
            if q == n or text[q] in "?.,;:":
                return q
            low = text[q:q + 8].lower()
            for w in _PG_NAME_FOLLOW_WORDS:
                if low.startswith(w) and (q + len(w) == n or not _fl_word_char(text[q + len(w)])):
                    return q
        return None

    def _name(self, text: str, p0: int, extra: int) -> "tuple[int, int] | None":
        """(name end, match end) for a name word starting at p0, else None."""
        e = self._word_end(text, p0)
        for end in range(e, p0, -1):
            got = self._ending(text, end)
            if got is not None:
                return end, got
            if end == e and extra < 7:
                q = end
                while q < len(text) and text[q].isspace():
                    q += 1
                if q > end:
                    more = self._name(text, q, extra + 1)
                    if more is not None:
                        return more
        return None

    def search(self, text: "str | None") -> "Hit | None":
        text = text or ""
        n = len(text)
        for h in _PG_NAMED_PREFIX.finditer(text):
            starts = []
            q = h.end()
            if q < n and text[q].isspace():
                while q < n and text[q].isspace():
                    q += 1
                # "named as X": try with "as" taken first
                if text[q:q + 2].lower() == "as" and q + 2 < n and text[q + 2].isspace():
                    r = q + 2
                    while r < n and text[r].isspace():
                        r += 1
                    starts.append(r)
                starts.append(q)
            for st in starts:
                for ns in ((st + 1, st) if st < n and text[st] in _PG_NAME_OPEN_QUOTES else (st,)):
                    got = self._name(text, ns, 0)
                    if got is not None:
                        return Hit(text, h.start(), got[1], [], {"name": (ns, got[0])})
        return None

    __call__ = search


_PG_NAMED_ENTITY = _PgNamedEntity()


class _PgSuffix:
    """The group-type suffix at the end of a name ("producer group(s)", "producer
    grp", "PG", "P.G.", "group", with the spaces / commas before it), so
    "Nongstoin PG" strips to the core "Nongstoin" that the extractor actually
    tagged as a block. `.search` / `.sub` as on any Matcher."""

    _WORDS = Matcher(Seq(Alt(_fl_sp("producer", ("group", "groups", "grp")), _FlDotSpaceSeq("p", "g"),
                             W("pg", "group")), END))

    def search(self, text: "str | None") -> "Hit | None":
        text = text or ""
        h = self._WORDS.search(text)
        if h is None:
            return None
        tail = text[h.end():]
        dots = 2 if h.group(0).lower().replace(" ", "").replace(".", "") == "pg" else 1
        k = 0
        while k < dots and tail[k:k + 1] == ".":
            k += 1
        if tail[k:].strip() != "":
            return None
        b = h.start()
        while b > 0 and (text[b - 1].isspace() or text[b - 1] == ","):
            b -= 1
        return Hit(text, b, len(text))

    def sub(self, repl, text: "str | None", count: int = 0) -> str:
        text = text or ""
        h = self.search(text)
        if h is None:
            return text
        return text[:h.start()] + (repl(h) if callable(repl) else repl)

    __call__ = search


_PG_SUFFIX = _PgSuffix()


def _question_without_pg_name(question: str) -> str:
    """The question with a producer-group NAME the user labelled as one blanked
    out, for the place-name SCANS in resolve_entities. _drop_producer_group_names
    only cleans the extractor's mentions; the admin-level gate and the block
    backstop then re-scan the raw text and put the name straight back — "Is
    there any Producer Group named Nongstoin PG?" (Focus Legacy QA TC-13,
    2026-09-25) became "Nongstoin: the block or the village?", and the chip
    turned a name lookup into a geography question. Unchanged when no group is
    named."""
    m = _PG_NAMED_ENTITY.search(question or "")
    if not m:
        return question
    return (question[: m.start("name")] + question[m.end("name"):]).strip()


# ════ villages ════════════════════════════════════════════════════════════════════════════════════════
# The single-scheme views whose twin-village chips are ranked / expanded by where
# the scheme's own records sit (see the two helpers below).
_TWIN_RANK_VIEWS = {"Focus Legacy": "curated.v_focus_legacy",
                    "CM Elevate Legacy": "curated.v_cm_elevate_disbursement"}


async def _fl_rank_villages(schemes: "list[str] | None", cands: list[dict]) -> list[dict]:
    """Focus Legacy: same-named villages that hold Focus Legacy groups first. The
    chips show 5 of the candidates drawn from the whole geography registry, and
    the one village with data could be left off ("MAWLONG": the Mawpat-block one
    was the 6th of 9; all-villages run 2026-09-29, KI-160). The rest are kept —
    a village with no groups is a real question with a real zero answer.
    CM Elevate Legacy joined 2026-09-29 (all-villages run): "Nongthymmai" matched
    10 registry villages and the one holding its records (JIRANG) was not among
    the chips shown."""
    view = _TWIN_RANK_VIEWS.get(schemes[0]) if schemes and len(schemes) == 1 else None
    if not view or len(cands or []) < 2:
        return cands
    codes = [int(c["village_code"]) for c in cands if str(c.get("village_code") or "").isdigit()]
    try:
        have = {r["village_code"] for r in await fetch_rows(
            f"SELECT DISTINCT village_code FROM {view} WHERE village_code = ANY($1::int[])", [codes])}
    except Exception:  # noqa: BLE001 — keep the registry order
        return cands
    return sorted(cands, key=lambda c: 0 if str(c.get("village_code")).isdigit()
                  and int(c["village_code"]) in have else 1)


async def _fl_expand_twins(schemes: "list[str] | None", cands: list[dict]) -> list[dict]:
    """Focus Legacy: add back a candidate's same-name twin in the SAME block when
    the twin holds Focus Legacy groups. resolve_village keeps one of each twin
    pair by all-scheme data volume, and for DEWSAW (Mairang) it kept the twin
    with no Focus Legacy data (all-villages run 2026-09-29, KI-163). CM Elevate
    Legacy uses the same rule against its own view."""
    view = _TWIN_RANK_VIEWS.get(schemes[0]) if schemes and len(schemes) == 1 else None
    if not view or not cands:
        return cands
    codes = [int(c["village_code"]) for c in cands if str(c.get("village_code") or "").isdigit()]
    try:
        extra = await fetch_rows(
            "SELECT DISTINCT g2.village_code, g2.lgd_village_name AS name, g2.lgd_block AS block, "
            "g2.lgd_district AS district FROM curated.dim_geography g1 JOIN curated.dim_geography g2 "
            "ON UPPER(g2.lgd_village_name) = UPPER(g1.lgd_village_name) "
            "AND g2.lgd_block IS NOT DISTINCT FROM g1.lgd_block AND g2.lgd_district = g1.lgd_district "
            "AND g2.village_code <> g1.village_code "
            f"WHERE g1.village_code = ANY($1::int[]) AND EXISTS (SELECT 1 FROM {view} f "
            "WHERE f.village_code = g2.village_code)", [codes])
    except Exception:  # noqa: BLE001 — keep the resolver's candidates
        return cands
    have = {str(c.get("village_code")) for c in cands}
    return cands + [dict(e) for e in extra if str(e["village_code"]) not in have]


_FL_VILLAGE_NAMES: "dict[str, list[dict]] | None" = None


async def _focus_legacy_village_names() -> "dict[str, list[dict]]":
    """UPPER(name) -> villages for every village in v_focus_legacy, loaded once.
    Placeholder "Unresolved" rows excluded (records with no village)."""
    global _FL_VILLAGE_NAMES
    if _FL_VILLAGE_NAMES is None:
        rows = await fetch_rows(
            "SELECT DISTINCT village_code, lgd_village_name, UPPER(lgd_block) AS block, "
            "UPPER(lgd_district) AS district FROM curated.v_focus_legacy "
            "WHERE village_code IS NOT NULL AND village_code > 0 AND entity_type <> 'Unresolved'", [])
        out: dict[str, list[dict]] = {}
        for r in rows:
            n = collapse_ws(str(r["lgd_village_name"] or ""))
            if n and not n.lower().startswith("unresolved"):
                out.setdefault(n.upper(), []).append(
                    {"village_code": r["village_code"], "name": n, "block": r["block"], "district": r["district"]})
        _FL_VILLAGE_NAMES = out
    return _FL_VILLAGE_NAMES


# ════ SQL rewrites ════════════════════════════════════════════════════════════════════════════════════
# Focus Legacy: a group's member count is recorded on EACH of its payments, so
# "how many members does <group> have" / "groups with more than N members" is the
# group's SIZE — MAX(no_of_pg_members) per pg_id. The generator SUMmed it across
# the group's payments instead, and 2,655 groups were paid more than once: a
# 20-member group paid twice read "40 members", the 190-member outlier "201"
# (use-case QA TC-14b / TC-15, 2026-09-25). SUM(no_of_pg_members) stays correct
# for memberships PAID FOR (a district / year / scheme total), so this fires only
# when the SQL works at group grain — GROUP BY pg_id, or a filter on one group.
_FL_NUMBER_WORD = Pred(lambda w: w.isdecimal())
_FL_GROUP_SIZE_Q = Matcher(Alt(
    _fl_sp("how", "many", "members"), _fl_sp("number", "of", "members", ("in", "of")),
    _fl_sp(("more", "less", "fewer"), "than", _FL_NUMBER_WORD, Opt("of"), "members"),
    _fl_sp(Alt("over", "above", "under", "below", _fl_sp("at", "least"), _fl_sp("at", "most")),
           _FL_NUMBER_WORD, "members"),
    _fl_sp("group", "size"), _fl_sp("member", "count"),
    _fl_sp(("largest", "biggest", "smallest"), Opt("producer"), ("group", "groups"))))
# money words; a "₹" sign counts too (see _fl_money_q)
_FL_MONEY_Q = Matcher(Alt(
    W("paid", "memberships", "amount", "money", "rupee", "rupees"),
    W("disburs", "receiv", "remit", prefix=True),
    _FlDotSpaceSeq("rs", Pred(lambda w: w[:1].isdecimal())),
    Pred(lambda w: w[:2].lower() == "rs" and w[2:3].isdecimal())))


def _fl_money_q(q: str) -> bool:
    return "₹" in q or bool(_FL_MONEY_Q.search(q))


def _fl_group_grain(sql: str) -> bool:
    """The query works at producer-group grain: GROUP BY pg_id, or a pg_name /
    pg_id filter by =, LIKE, ILIKE or IN."""
    if not sql:
        return False
    return sql_ast.groups_by(sql, "pg_id") or any(
        isinstance(n, (exp.EQ, exp.Like, exp.ILike, exp.In))
        for n in sql_ast.filter_conditions(sql, "pg_name", "pg_id"))


# Focus Legacy: the view's audit copies block_name_raw / district_name_raw are NULL
# on every row since the 2026-09-25 database change (the curated lgd_block /
# lgd_district were fixed to carry the source values instead). A query filtering
# on them returns nothing: "How many Producer Groups are mapped to Nongstoin
# block?" answered "no matching records" against a true 460 (bulk block QA, 3 of
# 168 questions). Read the curated columns, which hold the same values.
_FL_RAW_GEO_COLS = {"block_name_raw": "lgd_block", "district_name_raw": "lgd_district"}


def _focus_legacy_geo_columns(schemes: list[str], sql: str) -> str:
    if schemes != ["Focus Legacy"] or not sql_ast.references_column(sql or "", *_FL_RAW_GEO_COLS):
        return sql
    out = sql_ast.rename_columns(sql, _FL_RAW_GEO_COLS)
    logger.info("Focus Legacy: block/district_name_raw -> lgd_block/lgd_district (raw copies are empty)")
    return out


# NIKWATGRE, RONGARA block: the village chip pinned village_code 276311, and the
# model ALSO filtered lgd_block = 'RONGBARA' (its own misspelling) — ₹0 / null
# for a true ₹95,000 (all-villages run 2026-09-29, KI-159). A village code fixes
# the block and district, so beside it those literals can only be wrong.
def _focus_legacy_village_code_only(schemes: list[str], resolved: dict, sql: str) -> str:
    code = (resolved or {}).get("village_code")
    if schemes not in (["Focus Legacy"], ["CM Elevate Legacy"]) or code is None \
            or isinstance(code, (list, tuple)) or not sql:
        return sql
    pinned = any(isinstance(n, exp.EQ) and str(code) in sql_ast.filter_values(n, "village_code", numeric=True)
                 for n in sql_ast.filter_conditions(sql, "village_code"))
    if not pinned:
        return sql
    # CM Elevate Legacy also drops a village-name literal: for the ward "William
    # Nagar (MB) - Ward No.10" the generator wrote lgd_village_name = 'WILLIAM
    # NAGAR-MUNICIPAL BOARD' (the block) beside village_code = 70681 and answered
    # 0 for a ward holding 1 record (all-villages run 2026-09-29).
    cols = {"lgd_block", "lgd_district"} | ({"lgd_village_name"} if schemes == ["CM Elevate Legacy"] else set())
    out = _fl_drop_and_conjuncts(sql, lambda n: isinstance(n, exp.EQ) and _fl_col_vs_literal(n, cols) is not None)
    if out != sql:
        logger.info("%s: dropped place literals beside village_code %s", schemes[0], code)
    return out


# FOCUS sheet TC-26 (2026-10-12): "...under FOCUS" (the scheme's own name) made the model
# add programme_variant = 'FOCUS', which drops the 'Focus (Addnl)' top-up payments:
# Wapung 380 groups became 218. The variant filter only belongs to a question about the
# variant itself.
_FL_VARIANT_ASKED = Matcher(Alt(W("variant", prefix=True), W("addnl", "additional"), Joined("top", "up"),
                                _fl_sp("programme", "type")))
_FL_GROUP_TYPE_ASKED = Matcher(W("type", "lamp", "existing"))


def _fl_equals_focus(node, cols: set) -> bool:
    """`<col> = 'FOCUS'` (any case, column optionally in LOWER() / UPPER())."""
    hit = _fl_col_vs_literal(node, cols) if isinstance(node, exp.EQ) else None
    return bool(hit) and hit[1].lower() == "focus"


# Focus Legacy all-villages run (2026-10-12): "What is the total amount disbursed for
# Charbatapara?" became `WHERE village_code = 272773 AND pg_name ILIKE '%charbatapara%'`
# — the village name read as a group name — and returned null or a fraction (140 of 603
# money questions). A pg_name filter that only repeats the resolved place's name is dropped.
# pg_name or product_raw (the village name as a "product": product_raw = 'KYNSHI RASHAN'),
# compared with =, LIKE or ILIKE, wildcards inside the name too ('%gandigiri%barman%').
_FL_NAME_COLS = {"pg_name", "product_raw"}


def _fl_name_filter(node) -> "str | None":
    """The literal of a pg_name / product_raw filter by =, LIKE or ILIKE (column
    optionally in LOWER() / UPPER() / TRIM()), else None."""
    if not isinstance(node, (exp.EQ, exp.Like, exp.ILike)):
        return None
    hit = _fl_col_vs_literal(node, _FL_NAME_COLS)
    return hit[1] if hit else None


def _focus_legacy_place_not_group_name(schemes: list[str], entity_result: dict, sql: str) -> str:
    resolved, display = entity_result.get("resolved") or {}, entity_result.get("display") or {}
    if schemes != ["Focus Legacy"] or not sql or not any(
            resolved.get(k) for k in ("village_code", "village_code_list", "block", "district")):
        return sql
    places = [fold(str(v)) for v in (display.get("village"), display.get("block"), display.get("district"),
                                     resolved.get("block"), resolved.get("district")) if v]

    def _is_place(value: str) -> bool:
        v = value[1:] if value.startswith("%") else value
        v = v[:-1] if v.endswith("%") else v
        name = fold(v.replace("%", " "))
        # fuzzy too: the model misspells the village it copies ('choklogkittim' for
        # Choklokgittim, 'madan jaiew' for Madan Jaiaw)
        return bool(name) and any(name in p_ or p_ in name or fuzz.ratio(name, p_) >= 80 for p_ in places)

    def _place_filter() -> "exp.Expression | None":
        # filter on the resolved place itself, never a bare TRUE
        if isinstance(resolved.get("village_code"), int):
            return exp.EQ(this=exp.column("village_code"), expression=exp.Literal.number(resolved["village_code"]))
        for key, col in (("block", "lgd_block"), ("district", "lgd_district")):
            if isinstance(resolved.get(key), str):
                return exp.EQ(this=exp.column(col), expression=exp.Literal.string(resolved[key].upper()))
        return None

    def _product_filtered(tree) -> bool:
        return any(isinstance(n, (exp.EQ, exp.Like, exp.ILike))
                   for n in sql_ast.filter_conditions(tree, "product_raw"))

    def fn(tree):
        had_product = _product_filtered(tree)
        for where in list(tree.find_all(exp.Where)):
            conds, kept = _fl_conjuncts(where), []
            for i, c in enumerate(conds):
                value = _fl_name_filter(c)
                if value is None or not _is_place(value):
                    kept.append(c)
                    continue
                logger.info("Focus Legacy: dropped pg_name filter %r — it is the place's name", value)
                if i == 0:
                    # the WHERE's leading predicate becomes the resolved place's own filter
                    # (kept as it was when no place is resolved to a code or name)
                    kept.append(_place_filter() or c)
            if kept != conds:
                where.set("this", exp.and_(*kept, copy=False))
        if had_product and not _product_filtered(tree):
            # the companion "product recorded" filter goes with the dropped place-as-product one
            for where in list(tree.find_all(exp.Where)):
                conds = _fl_conjuncts(where)
                keep = [c for c in conds if not _fl_is_not_null(c, "product_raw")]
                if keep and len(keep) != len(conds):
                    where.set("this", exp.and_(*keep, copy=False))
        # "How many FOCUS Producer Groups are mapped to NONGLYNKIEN village?" became
        # `lgd_village_name <> 'NONGLYNKIEN'` — every OTHER village, 14,558 groups (Focus Legacy
        # all-villages run 2026-10-12). The resolved village is the filter, never its negation.
        if isinstance(resolved.get("village_code"), int):
            for node in list(tree.find_all(exp.NEQ)):
                hit = _fl_col_vs_literal(node, {"lgd_village_name"})
                if hit and any(fold(hit[1]) == p_ or fuzz.ratio(fold(hit[1]), p_) >= 80 for p_ in places):
                    logger.info("Focus Legacy: replaced a negated filter on the resolved village %r", hit[1])
                    node.replace(exp.EQ(this=exp.column("village_code"),
                                        expression=exp.Literal.number(resolved["village_code"])))
        return None

    return sql_ast.transform(sql, fn)


def _focus_legacy_scheme_name_not_variant(question: str, schemes: list[str], sql: str) -> str:
    if schemes != ["Focus Legacy"] or _FL_VARIANT_ASKED.search(question or "") or not sql:
        return sql
    cols = {"programme_variant"}
    # the same mistake on the group-type column: LOWER(pg_entity_type_name) = 'focus' gave KSEH
    # 0 groups (all-villages run 2026-10-12) — unless the question asks about the group type
    if not _FL_GROUP_TYPE_ASKED(question or ""):
        cols |= {"pg_entity_type", "pg_entity_type_name"}
    new = _fl_drop_and_conjuncts(sql, lambda n: _fl_equals_focus(n, cols))
    if new != sql:
        logger.info("Focus Legacy: dropped programme_variant = 'FOCUS' (the scheme name, not a variant)")
    return new


# A question about HOW MANY YEARS a group was paid in ("paid in more than one
# year", "every year", "paid twice", "repeat payments").
_FL_YEAR_COVERAGE_ASKED = Matcher(Alt(
    Seq(W("more", "multiple", "several", "two", "three", "four", "all", "every", "each", "consecutive", "different",
          "both"), Opt(W("financial", "fiscal")), W("year", "years", "fy", "fys")),
    Seq(W("more", "fewer", "less"), "than", Opt(W("one", "two", "three", "1", "2", "3")),
        Opt(W("financial", "fiscal")), W("year", "years", "fy", "fys")),
    W("twice", "once", "repeat", "repeated", "repeatedly", "again", "yearly", "annually", "thrice")))
_FL_YEAR_COLUMNS = ("financial_year_short", "financial_year", "year_key", "fy_start_year")
# The year chip's SCOPE ("All financial years combined" -> "<question> across all
# financial years"): no year filter, not "paid in every year". It is appended
# to any question that names no year, so it must not count as asking about years.
_FL_ALL_YEARS_SCOPE = Matcher(Alt(
    Seq(W("across", "over"), "all", Opt("the"), Opt(W("financial", "fiscal")), "years", Opt("combined")),
    Seq("all", Opt("the"), Opt(W("financial", "fiscal")), "years", "combined")))


def _fl_counts_distinct_years(node: exp.Expression) -> bool:
    """`node` holds a HAVING on COUNT(DISTINCT <year column>) — "paid in N years"."""
    return any(isinstance(c.this, exp.Distinct) and sql_ast.references_column(c, *_FL_YEAR_COLUMNS)
               for h in node.find_all(exp.Having) for c in h.find_all(exp.Count))


def _focus_legacy_unasked_year_coverage(question: str, schemes: list[str], sql: str) -> str:
    """A condition the question never asked for: only groups paid in N distinct
    years (`pg_id IN (... HAVING COUNT(DISTINCT financial_year_short) = 4)`), copied
    from the "paid in more than one financial year" pattern into a plain "villages
    with a group that was paid" count — 0 villages instead of 173 (NL->SQL
    accuracy set, 2026-10-16). Dropped unless the question asks how many years."""
    if schemes != ["Focus Legacy"] or not sql \
            or _FL_YEAR_COVERAGE_ASKED.search(_FL_ALL_YEARS_SCOPE.sub(" ", question or "")):
        return sql
    tree = sql_ast.parse_one(sql)
    if tree is None or not _fl_counts_distinct_years(tree):
        return sql
    out = sql_ast.remove_conditions(sql, lambda c: isinstance(c, exp.In) and _fl_counts_distinct_years(c))
    if out != sql:
        logger.info("Focus Legacy: dropped an unasked 'paid in N financial years' condition")
    return out


def _focus_legacy_date_trunc_as_date(schemes: list[str], sql: str) -> str:
    """DATE_TRUNC('year'|'quarter'|'month'|'week'|'day', date_of_remittance) cast back
    to a date: on a DATE it returns timestamptz in IST, read back in UTC as the day
    before, so every month came out one early (TC-21, KI-164). Idempotent."""
    if schemes != ["Focus Legacy"] or not sql:
        return sql

    def fn(tree):
        for node in list(tree.find_all(exp.TimestampTrunc, exp.DateTrunc)):
            if node.text("unit").lower() not in ("year", "quarter", "month", "week", "day") \
                    or _fl_col_name(node.this) != "date_of_remittance":
                continue
            parent = node.parent
            if isinstance(parent, exp.Cast) and parent.to.is_type(exp.DataType.Type.DATE):
                continue
            node.replace(exp.Cast(this=node.copy(), to=exp.DataType.build("date")))
        return None

    return sql_ast.transform(sql, fn)


def _focus_legacy_group_size_summed(question: str, schemes: list[str], sql: str) -> bool:
    return (schemes == ["Focus Legacy"]
            and bool(_FL_GROUP_SIZE_Q.search(question or ""))
            and not _fl_money_q(question or "")
            and _fl_sums_column(sql or "", "no_of_pg_members", exact=True)
            and _fl_group_grain(sql or ""))


# ════ turn stages ═════════════════════════════════════════════════════════════════════════════════════
# Focus Legacy sheet TC-03 / 06 / 09 (2026-10-12): "Who can benefit…", "What kind of support…",
# "a short overview … for an official briefing" were answered from the scheme documents
# without the one figure the testers expect — the Rs 5,000 per member mobilisation fund,
# which the documents state (FOCUS_LEGACY_FAQ.md, FOCUS_legacy_Complete_Reference.md).
_FL_RATE_TOPIC = Matcher(Alt(
    W("benefit", "eligib", "support", "assistance", "financial", "overview", "briefing", "summary", "grant",
      "entitle", prefix=True),
    _fl_sp("who", W("can", prefix=True)), W("fund", "funds", "funding")))
_FL_RATE_STATED = ("5,000", "5000")         # the rate already in the answer (anywhere in the text)


def _focus_legacy_rate_line(question: str, scheme: "str | None", answer: str) -> str:
    if scheme != "Focus Legacy" or not answer or any(r in answer for r in _FL_RATE_STATED) \
            or not _FL_RATE_TOPIC.search(question or ""):
        return answer
    return (answer.rstrip() + "\n\nEach Producer Group member receives an initial mobilisation fund of "
            "₹5,000, credited to the members' bank accounts (by cheque in the earliest rounds).")

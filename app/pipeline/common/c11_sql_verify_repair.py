# app/pipeline/common/c11_sql_verify_repair.py — repair hints, verifier false positives, verify, execute, repair.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
#
# Every check below that reads the SQL works on its SQLGlot tree (app/sql_ast),
# never on the text: a text search reads words inside string literals and
# comments, misses UPPER(col) and sees only the first value of an IN list. The
# word matchers (app/text_match) read the user's question, the verifier's
# English complaint or the database's error message — never the SQL.

import sqlglot
from app import schema_introspect, sql_ast
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.tokens import TokenType


# ── SQL tree helpers for this file ──────────────────────────────────────────

# Wrappers that leave a column's identity unchanged for a filter test.
_VR_TRANSPARENT = tuple(cls for cls in (getattr(exp, n, None) for n in (
    "Upper", "Lower", "Trim", "Cast", "TryCast", "Initcap", "Paren", "Coalesce", "Collate",
)) if isinstance(cls, type))
# Comparison kinds, by the operator the generator writes.
_VR_EQ = (exp.EQ,)
_VR_IN = (exp.In,)
_VR_ILIKE = (exp.ILike,)
_VR_LIKE = (exp.Like, exp.ILike)
_VR_REGEX = tuple(cls for cls in (getattr(exp, n, None) for n in ("RegexpLike", "RegexpILike"))
                  if isinstance(cls, type))


def _vr_unwrap(node):
    while isinstance(node, _VR_TRANSPARENT) and node.this is not None:
        node = node.this
    return node


def _vr_col_name(node) -> "str | None":
    """The lower-cased column name `node` is, under UPPER()/TRIM()/casts, else None."""
    node = _vr_unwrap(node) if node is not None else None
    return node.name.lower() if isinstance(node, exp.Column) and node.name else None


def _vr_conditions(sql, cols, kinds) -> "list[tuple[str, exp.Expression, exp.Expression | None]]":
    """(column, condition node, value side) for every condition of one of `kinds`
    (exp.EQ, exp.In, exp.ILike …) that tests one of `cols` on either side,
    anywhere in the query (WHERE, ON, HAVING, FILTER, subqueries). For IN the
    value side is None (its values are node.expressions / node.args['query'])."""
    wanted = {c.lower() for c in cols}
    out = []
    for tree in sql_ast.parse(sql) if isinstance(sql, str) else [sql]:
        for node in tree.walk():
            if not isinstance(node, kinds):
                continue
            if isinstance(node, exp.In):
                name = _vr_col_name(node.this)
                if name in wanted:
                    out.append((name, node, None))
                continue
            left, right = _vr_col_name(node.this), _vr_col_name(node.expression)
            if left in wanted:
                out.append((left, node, node.expression))
            elif right in wanted:
                out.append((right, node, node.this))
    return out


def _vr_literals(node, *, strings: bool = True) -> list[str]:
    """String (or number) literal values on a comparison's value side: 'x',
    UPPER('x'), ARRAY['a','b'], ANY(ARRAY[...]); for an IN node, every listed value."""
    if node is None:
        return []
    if isinstance(node, exp.In):
        vals: list[str] = []
        for e in node.expressions:
            vals += _vr_literals(e, strings=strings)
        return vals
    node = _vr_unwrap(node)
    if isinstance(node, exp.Literal):
        return [node.this] if node.is_string == strings else []
    if isinstance(node, (exp.Any, exp.All, exp.Array, exp.Tuple, exp.Paren)):
        return [l.this for l in node.find_all(exp.Literal) if l.is_string == strings]
    return []


def _vr_values(sql, cols, kinds, *, strings: bool = True) -> "list[tuple[str, str]]":
    """(column, literal value) for every value `cols` is compared to by `kinds`."""
    out = []
    for name, node, side in _vr_conditions(sql, cols, kinds):
        for v in _vr_literals(node if side is None else side, strings=strings):
            out.append((name, v))
    return out


def _vr_int_values(sql, col, kinds) -> set[int]:
    """Integer values `col` is compared to (number literals, or digit-only strings)."""
    vals = [v for _, v in _vr_values(sql, [col], kinds, strings=False)]
    vals += [v for _, v in _vr_values(sql, [col], kinds, strings=True)]
    out = set()
    for v in vals:
        s = str(v).strip()
        if s.isdigit():
            out.add(int(s))
    return out


def _vr_filters_col(sql, cols, kinds) -> bool:
    return bool(_vr_conditions(sql, cols, kinds))


def _vr_counts_column(sql, col: str) -> bool:
    """COUNT(col) / COUNT(DISTINCT col) anywhere in the query."""
    for tree in sql_ast.parse(sql):
        for c in tree.find_all(exp.Count):
            arg = c.this
            args = list(arg.expressions) if isinstance(arg, exp.Distinct) else [arg]
            if len(args) == 1 and _vr_col_name(args[0]) == col:
                return True
    return False


def _vr_counts_rows_or_requests(sql) -> bool:
    """COUNT(*) or COUNT(DISTINCT request_id) anywhere in the query."""
    for tree in sql_ast.parse(sql):
        for c in tree.find_all(exp.Count):
            arg = c.this
            if isinstance(arg, exp.Star):
                return True
            if isinstance(arg, exp.Distinct) and len(arg.expressions) == 1 \
                    and _vr_col_name(arg.expressions[0]) == "request_id":
                return True
    return False


def _vr_json_keys(sql, col: str) -> list[str]:
    """The keys read as `col -> 'k'` / `col ->> 'k'`."""
    keys = []
    for tree in sql_ast.parse(sql):
        for node in tree.walk():
            if isinstance(node, (exp.JSONExtract, exp.JSONExtractScalar)) and _vr_col_name(node.this) == col:
                path = node.expression
                if isinstance(path, exp.JSONPath):
                    keys += [str(k.this) for k in path.expressions if isinstance(k, exp.JSONPathKey)]
                elif isinstance(path, exp.Literal):
                    keys.append(str(path.this))
    return keys


def _vr_year_values(sql) -> "tuple[set[int], set[str]]":
    """(year_key integer values, financial_year / financial_year_short string values)
    the query compares by equality."""
    return (_vr_int_values(sql, "year_key", _VR_EQ),
            {v for _, v in _vr_values(sql, ["financial_year", "financial_year_short"], _VR_EQ)})


def _vr_fy_start(label: str) -> "int | None":
    """2023 for '2023-24' (optionally 'FY 2023-24'), else None."""
    s = str(label).strip()
    if s[:2].upper() == "FY":
        s = s[2:].lstrip()
    if len(s) >= 6 and s[:4].isdigit() and s[4] == "-" and s[5:7].isdigit():
        return int(s[:4])
    return None


_VR_TABLE_SCHEMAS = ("curated", "raw", "semantic", "meta", "app")


def _vr_state_pseudo_filter(sql: str) -> bool:
    """A filter on a 'Meghalaya' / entity_type = 'State' pseudo-row that does not
    exist: entity_type = 'State', or lgd_village_name / lgd_district / lgd_block
    = or ILIKE 'Meghalaya' (optionally %-wrapped)."""
    for _, v in _vr_values(sql, ["entity_type"], _VR_EQ):
        if v.strip().lower() == "state":
            return True
    for _, v in _vr_values(sql, ["lgd_village_name", "lgd_district", "lgd_block"], _VR_EQ + _VR_ILIKE):
        core = v.strip()
        core = core[1:] if core.startswith("%") else core
        core = core[:-1] if core.endswith("%") else core
        if core.strip().lower() == "meghalaya":
            return True
    return False


def _vr_sums_column(sql: str, col: str) -> bool:
    """SUM(...) over an expression that reads `col`, anywhere in the query."""
    return any(sql_ast.references_column(s.this, col)
               for tree in sql_ast.parse(sql) for s in tree.find_all(exp.Sum) if s.this is not None)


_VR_YEAR_GROUP_COLS = frozenset({"financial_year_short", "financial_year", "year_key", "start_year"})


def _vr_grouped_by_year_only(sql: str) -> bool:
    """Some GROUP BY of the query (outer, CTE or subquery) groups by the
    financial year alone (financial_year_short / financial_year / year_key /
    start_year, COALESCEd or not) — one year column or several.

    KI-411: "GROUP BY year_key, financial_year_short" (two names for one year) was
    read as not year-only, so an all-years PMAY-G total split per year passed."""
    for tree in sql_ast.parse(sql):
        for g in tree.find_all(exp.Group):
            if g.expressions and all(_vr_col_name(e) in _VR_YEAR_GROUP_COLS for e in g.expressions):
                return True
    return False


def _vr_returns_share(sql: str, col: str) -> bool:
    """A division that turns `col` into a share: `col` (or an aggregate of it) is
    divided by something, or something is divided by SUM(total_exp…)."""
    for tree in sql_ast.parse(sql):
        for d in tree.find_all(exp.Div):
            if sql_ast.references_column(d.this, col):
                return True
            den = d.expression
            if den is not None and any(
                    c.name.lower().startswith("total_exp")
                    for s in den.find_all(exp.Sum) for c in s.find_all(exp.Column) if c.name):
                return True
    return False


def _vr_has_order_by(sql: str) -> bool:
    return any(True for tree in sql_ast.parse(sql) for _ in tree.find_all(exp.Order))


def _vr_mentions_unresolved(sql: str) -> bool:
    """The query already handles the 'Unresolved' placeholder rows: a string
    literal (entity_type <> 'Unresolved', NOT ILIKE 'Unresolved%') or a column
    named for it."""
    return any("unresolved" in lit.lower() for lit in sql_ast.string_literals(sql)) \
        or any("unresolved" in c for c in sql_ast.columns(sql))


def _vr_has_job_card_pin(sql: str) -> bool:
    """The query carries the job-card latest-year pin (_JOB_CARD_PIN), compared
    on the tree so formatting does not matter."""
    pin = sql_ast.parse_one(f"SELECT 1 WHERE {_JOB_CARD_PIN}")
    where = pin.args.get("where") if pin is not None else None
    if where is None:
        return False
    want = sql_ast.to_sql(where.this)
    return any(sql_ast.to_sql(node) == want
               for tree in sql_ast.parse(sql) for node in tree.find_all(exp.EQ))


# A `column "X" does not exist` error usually means the generator picked a view
# that lacks a geography column (e.g. v_pmay_monthly_sanctions) rather than a
# genuine typo. Point the repair at the objects that DO carry the column instead
# of just echoing the Postgres message back.
def _c11_missing_col_spans(error: str) -> list:
    r"""Postgres `column "x" does not exist` (case-insensitive); group 1 is x
    (one or more letters, digits, '_' and '.' only)."""
    low = error.lower()
    head, tail = 'column "', '" does not exist'
    out, k = [], low.find(head)
    while k >= 0:
        a = k + len(head)
        b = a
        while b < len(error) and (_c1x_is_word_char(error[b]) or error[b] == "."):
            b += 1
        if b > a and low.startswith(tail, b):
            out.append((k, b + len(tail), [(a, b)]))
            k = low.find(head, b + len(tail))
        else:
            k = low.find(head, k + 1)
    return out


_MISSING_COL_MATCH = _C1xScan(_c11_missing_col_spans)
_COL_HOMES = {
    "lgd_district": "curated.v_pmay, curated.v_employment, curated.v_expenditure, "
                    "curated.v_district_year_summary, curated.v_focus_plus, "
                    "curated.v_cm_elevate, "
                    "curated.v_cross_scheme_money_district_year, curated.dim_geography",
    "lgd_block": "curated.v_pmay, curated.v_employment, curated.v_expenditure, "
                 "curated.v_focus_plus, curated.v_cm_elevate, curated.dim_geography",
    "lgd_village_name": "curated.v_pmay, curated.v_employment, curated.v_expenditure, "
                        "curated.v_focus_plus, curated.v_cm_elevate, curated.dim_geography",
}


def _missing_column_hint(error: str) -> "str | None":
    m = _MISSING_COL_MATCH.search(error)
    if not m:
        return None
    col = m.group(1).split(".")[-1].lower()
    split_fact = _mgnrega_split_fact_hint(col)
    if split_fact:
        return split_fact
    if col in ("scheme_key", "scheme_code"):
        # The generator added a scheme filter/join to a per-scheme object that
        # carries neither column. scheme_key / scheme_code live ONLY on
        # curated.dim_scheme and curated.v_cross_scheme_money_district_year.
        # Every row in curated.v_pmay / v_expenditure / v_employment /
        # fact_pmay_house / fact_mgnrega_* already belongs to one scheme, so a
        # single-scheme question needs no scheme filter and no join to
        # dim_scheme at all.
        return (f'"{col}" does not exist on the object the previous query selected from. '
                "It lives ONLY on curated.dim_scheme and "
                "curated.v_cross_scheme_money_district_year. The per-scheme fact tables "
                "and views (curated.v_pmay, curated.v_expenditure, curated.v_employment, "
                "curated.v_focus_plus, curated.v_cm_elevate, curated.fact_pmay_house, "
                "curated.fact_mgnrega_*, curated.fact_focus_plus_disbursement, "
                "curated.fact_cm_elevate_application) are each already a single scheme — "
                "DELETE the scheme filter and any JOIN to curated.dim_scheme entirely, and "
                "keep every other clause (year_key, geography, NOT is_placeholder, "
                "aggregation) exactly as it was.")
    homes = _COL_HOMES.get(col)
    if not homes:
        return (f'The previous query used a column "{col}" that its source object does not '
                "have. Select from a curated object that exposes every column you reference.")
    tail = (" — for a per-district PMAY-G breakdown use curated.v_pmay and GROUP BY lgd_district")
    if col in ("lgd_block", "lgd_village_name"):
        # The usual cause here is a cross-scheme money question at block/village grain
        # pointed at v_cross_scheme_money_district_year, which is district x year only.
        tail = (". For combined MGNREGA + PMAY-G money at block or village grain there is no "
                "cross-scheme view: aggregate curated.v_expenditure and curated.v_pmay to that "
                "grain in separate CTEs (MGNREGA total_exp is LAKH -> /100; PMAY amount_released "
                "is RUPEES -> /1e7, WHERE NOT is_placeholder), then FULL OUTER JOIN the two CTEs "
                "on the grain columns and sum the two crore figures")
    return (f'"{col}" does not exist on the object the previous query selected from. That '
            f"column lives on: {homes}. Rebuild against one of those{tail}.")


# The generator reaches for COUNT(DISTINCT x) OVER (...) on "top N% / decile /
# concentration" questions; Postgres rejects DISTINCT (and nested aggregates)
# inside a window function. A plain error echo doesn't get the model out of the
# habit — hand it the rank-in-a-CTE recipe explicitly.
_WINDOW_FN_ERR_MATCH = _C1xUnion(
    "DISTINCT is not implemented for window functions",
    "window function calls cannot contain",
    "aggregate function calls cannot contain window function calls",
)


def _window_fn_hint(error: str) -> "str | None":
    if not _WINDOW_FN_ERR_MATCH.search(error):
        return None
    return (
        "PostgreSQL forbids DISTINCT and nested aggregates inside a window function, so "
        "COUNT(DISTINCT ...) OVER (...) cannot work. Rebuild as: (1) a CTE that aggregates "
        "the metric per unit — SUM(<metric>) AS m ... GROUP BY <unit>; (2) a CTE that ranks "
        "those units — NTILE(<100/percent>) OVER (ORDER BY m DESC) AS bucket (top 10% -> "
        "NTILE(10), quartile -> NTILE(4)); (3) an outer SELECT returning "
        "ROUND(100.0 * SUM(m) FILTER (WHERE bucket = 1) / NULLIF(SUM(m), 0), 1). "
        "Keep every filter (year, scheme, geography) from the failed query on the first CTE."
    )


def _repair_hint(error: str) -> "str | None":
    """The single targeted hint fed to the repair prompt — most specific first."""
    return _missing_column_hint(error) or _window_fn_hint(error)


# curated.v_employment and curated.v_expenditure are at source-row grain (many
# rows per village) — schema_context MGNREGA rule 2: "always SUM ... GROUP BY,
# never read a row raw". The generator sometimes answers an aggregate question
# ("how many job cards", "how much was spent") with a bare
# `SELECT <metric> FROM curated.v_employment WHERE ... LIMIT 1` — it runs clean
# and returns one village's number as if it were the statewide total (the
# "116 job cards for all of Meghalaya" bug). Detect that shape and force a
# repair pass; the hint tells the generator to wrap the metric in SUM(...).
_ROWGRAIN_VIEWS = ("curated.v_employment", "curated.v_expenditure")
_VR_PLAIN_AGGS = (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)


def _rowgrain_no_aggregate(question: str, sql: str) -> "str | None":
    """The source-row-grain view a bare-row aggregate query reads from, or None.

    Fires only when the question is aggregate-shaped, the statement is a plain
    (non-CTE) SELECT whose FROM target is one of the source-row-grain views, the
    outer select list has no aggregate call, and there is no GROUP BY."""
    q = question or ""
    if not (_AGGREGATE_CUE.search(q) or _BARE_METRIC_CUE.search(q)):
        return None
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("with") is not None or sql_ast.has_cte(tree):
        return None
    frm = tree.args.get("from_") or tree.args.get("from")
    src_tb = frm.this if frm is not None else None
    if not isinstance(src_tb, exp.Table) or not src_tb.name:
        return None
    src = (f"{src_tb.db}.{src_tb.name}" if src_tb.db else src_tb.name).lower()
    if src not in _ROWGRAIN_VIEWS:
        return None
    if any(True for e in tree.expressions for _ in e.find_all(*_VR_PLAIN_AGGS)) \
            or sql_ast.has_group_by(tree):
        return None
    first = tree.expressions[0] if tree.expressions else None
    first = first.this if isinstance(first, exp.Alias) else first
    if isinstance(first, exp.Literal) and first.is_string:  # canned text answer, not a data read
        return None
    return src


# Row-level objects, one group per fact (view + its fact table). Any two in
# different groups must never be row-joined. The fallback when
# semantic.v_join_rules (the ingestion team's list, 2026-10-16) could not be read.
_VR_ROW_GRAIN_GROUPS = (
    ("curated.v_employment", "curated.fact_mgnrega_employment"),
    ("curated.v_expenditure", "curated.fact_mgnrega_expenditure"),
    ("curated.v_pmay", "curated.fact_pmay_house"),
    ("curated.v_focus_plus", "curated.fact_focus_plus_disbursement"),
    ("curated.v_cm_elevate", "curated.fact_cm_elevate_application"),
    ("curated.v_focus_legacy", "curated.fact_focus_legacy_disbursement"),
    ("curated.v_cm_elevate_disbursement", "curated.fact_cm_elevate_disbursement"),
)


def _vr_never_join_rules() -> dict:
    rules = schema_introspect.never_row_join()
    if rules:
        return rules
    out: dict[str, set[str]] = {}
    for i, grp in enumerate(_VR_ROW_GRAIN_GROUPS):
        others = {o for j, g in enumerate(_VR_ROW_GRAIN_GROUPS) if j != i for o in g}
        for name in grp:
            out[name] = others
    return out


def _vr_raw_objects(node: "exp.Expression | None", ctes: dict, rules: dict,
                    seen: frozenset = frozenset()) -> "set[str]":
    """The row-level objects (keys of `rules`) whose rows come out of a FROM /
    JOIN source one per source row — not collapsed by an aggregation on the way.
    Same walk as _mg_raw_facts, for every fact instead of MGNREGA's two."""
    if node is None:
        return set()
    if isinstance(node, exp.Table):
        name = node.name.lower()
        if not node.db and name in ctes and name not in seen:
            return _vr_raw_objects(ctes[name], ctes, rules, seen | {name})
        ref = f"{(node.db or 'curated').lower()}.{name}"
        return {ref} if ref in rules else set()
    if isinstance(node, (exp.Subquery, exp.Paren)):
        return _vr_raw_objects(node.this, ctes, rules, seen)
    if isinstance(node, exp.SetOperation):
        return _vr_raw_objects(node.left, ctes, rules, seen) | _vr_raw_objects(node.right, ctes, rules, seen)
    if isinstance(node, exp.Select):
        if _mg_select_aggregates(node):
            return set()
        out: set[str] = set()
        for src in _mg_sources(node):
            out |= _vr_raw_objects(src, ctes, rules, seen)
        return out
    return set()


def _prohibited_row_join(sql: str) -> "tuple[str, str] | None":
    """(a, b) when one SELECT row-joins two objects semantic.v_join_rules says must
    never be row-joined (ingestion team, 2026-10-16: v_employment x v_expenditure on
    year + district made FY2024-25 person-days 6.69 billion against a true 14.7
    million). Aggregating each side in its own CTE / subquery first is the safe
    shape and passes."""
    rules = _vr_never_join_rules()
    for tree in sql_ast.parse(sql or ""):
        ctes = {c.alias_or_name.lower(): c.this for c in tree.find_all(exp.CTE)}
        for sel in tree.find_all(exp.Select):
            per_source = [_vr_raw_objects(src, ctes, rules) for src in _mg_sources(sel)]
            for i, a_set in enumerate(per_source):
                for j, b_set in enumerate(per_source):
                    if j <= i:
                        continue
                    for a in sorted(a_set):
                        hit = sorted(b for b in b_set if b in rules.get(a, ()))
                        if hit:
                            return a, hit[0]
    return None


def _readonly_denied_column_in(sql: str) -> "tuple[str, str] | None":
    """(table, column) when the query reads a column the read-only database role
    may not SELECT (curated.v_cm_elevate.scheme_specific since 2026-10-16). Under
    megh_readonly that query is refused by the database; under a dev login it
    would read a field the chatbot is not allowed to use."""
    denied = schema_introspect.readonly_denied()
    if not denied:
        return None
    by_table: dict[str, set[str]] = {}
    for s, t, c in denied:
        by_table.setdefault(t.lower(), set()).add(c.lower())
    names = {n.lower() for n in sql_ast.tables(sql or "")}
    cols = {c for t in names for c in by_table.get(t.split(".")[-1], ())}
    if not cols:
        return None
    tree = sql_ast.parse_one(sql or "")
    if tree is None:
        return None
    for col in tree.find_all(exp.Column):
        if col.name.lower() in cols:
            table = next(t for t in names if col.name.lower() in by_table.get(t.split(".")[-1], ()))
            return table, col.name.lower()
    return None


def _vr_filters_village_code(sql: str) -> bool:
    """village_code = … / village_code IN (…) anywhere in the query."""
    return _vr_filters_col(sql, ["village_code"], _VR_EQ + _VR_IN)


def _vr_filters_village_name(sql: str) -> bool:
    """lgd_village_name = / ILIKE / IN … anywhere in the query."""
    return _vr_filters_col(sql, ["lgd_village_name"], _VR_EQ + _VR_ILIKE + _VR_IN)


# The generator also substitutes the WRONG ADMIN LEVEL for a resolved village:
# it writes lgd_block = 'NONGLADEW' or lgd_district = 'NONGLADEW' — a village
# name placed in a block/district column. That matches zero rows and returns a
# clean, confident 0 ("the data doesn't cover applicants in Nongladew") when the
# village has 32 real records. Same root cause as the lgd_village_name case
# above, and just as invisible: non-deterministic across runs, so the same
# question answers district one time and block the next (reported 2026-09-17).
# (Detected on the tree: lgd_district / lgd_block compared with =, ILIKE or IN
# to a string literal, UPPER()-wrapped or not, every IN value considered.)


def _vr_divides_by_100(sql: str) -> bool:
    """Some expression is divided by the number 100 (… / 100, … / 100.0)."""
    for tree in sql_ast.parse(sql):
        for d in tree.find_all(exp.Div):
            den = _vr_unwrap(d.expression)
            if isinstance(den, exp.Literal) and not den.is_string:
                try:
                    if float(den.this) == 100:
                        return True
                except ValueError:
                    pass
    return False
# CM Elevate's is_withdraw is a real, well-defined boolean column that is FALSE
# on every one of the 8,543 rows today (schema_context.py rule 15) — a filtered
# COUNT against it is a genuine, correct zero, not a sign of a missing/hallucinated
# metric. compose_response's generic zero-hedging guidance (written to catch
# hallucinated columns that always read NULL/0) can't tell the two apart on its
# own, so a query that visibly filters is_withdraw gets an explicit note telling
# the composer this particular zero IS the real, complete answer (confirmed live
# 2026-09-12: without this, "how many applications have been withdrawn in Ri
# Bhoi" — SQL correctly `is_withdraw = TRUE`, 0 rows — was composed as "doesn't
# cover a withdrawal count", a false refusal over a query that ran exactly right).


def _genuine_zero_notes(sql: str) -> list[str]:
    """Notes overriding compose_response's default zero-hedge for CM Elevate
    columns where a real 0 is the correct, complete answer (not a missing
    metric) — see the is_withdraw note above."""
    if sql_ast.references_column(sql, "is_withdraw"):
        return [
            "is_withdraw is a real, always-queryable boolean column (FALSE on every "
            "current row) — if the result is 0, that IS the true, complete withdrawal "
            "count for this scope. State it plainly as '0 applications withdrawn', "
            "never as data that 'isn't tracked' or 'doesn't cover' withdrawals."
        ]
    return []


def _sector_not_tracked_notes(rows: list[dict]) -> list[str]:
    """CM Elevate scheme_specific ->> 'sector_id' rule 9b requires stating
    plainly that sector isn't recorded for a scheme rather than reading a bare
    sector_recorded=0 as "checked and found none" — but that instruction lives
    in the SQL-generation prompt (schema_context.py), which compose_response
    never sees. Without a note here, a row like {scheme_name: Piggery,
    poultry_sector_applicants: 0, sector_recorded: 0, scheme_total: 1944} gets
    composed as "Piggery has 0" — technically not wrong, but exactly the
    misleading "checked and found none" reading rule 9b exists to avoid
    (confirmed live 2026-09-13 UAT on "applicants under Piggery and Poultry
    associated with poultry sector"). Detected generically from the result
    shape (a sector_recorded column that's 0 in a row where some OTHER count
    in that same row is non-zero) rather than a hardcoded scheme list, so it
    keeps working if which schemes carry sector_id ever changes."""
    notes: list[str] = []
    for r in rows:
        if not isinstance(r, dict) or "sector_recorded" not in r:
            continue
        if r.get("sector_recorded"):
            continue
        if any(k != "sector_recorded" and isinstance(v, (int, float)) and v
               for k, v in r.items()):
            name = r.get("scheme_name") or "this scheme"
            notes.append(
                f"sector_recorded is 0 for {name} in this result, with no sector "
                f"value recorded for it at all in this scope. Say exactly this, as "
                f"a plain fact alongside the other rows' real numbers: 'sector "
                f"isn't tracked for {name}.' Do NOT phrase it as 'has 0', and do "
                "NOT use hedge wording like 'doesn't cover', 'not covered', 'no "
                "data' or 'not available' — this is one specific, known fact about "
                "one row, not a reason to doubt or soften the OTHER rows' real, "
                "reportable numbers in the same result."
            )
    return notes


def _crore_conversion_for_single_village(entity_result: dict, sql: str) -> bool:
    """True when the SQL converts a MGNREGA money column to CRORE (÷100) while
    the question is scoped to a single village — a grain small enough that
    the true figure is routinely well under 1 crore, so rounding the crore
    value to 2 decimal places can display a real, non-zero lakh amount as
    "0.00 crore" (reported 2026-09-10 UAT: Maska's real 0.49 lakh MGNREGA
    expenditure came back as "0.00 crore" for exactly this reason). MGNREGA
    money is natively LAKH (schema_context's MGNREGA rule 4) — the crore
    conversion exists only for cross-scheme/statewide normalisation against
    PMAY's rupee figures, never for a single village's own figure."""
    if not entity_result.get("resolved", {}).get("village_code"):
        return False
    # "crore" is checked as a plain substring, not as a whole word — it is always
    # used here as an identifier suffix ("total_expenditure_crore"), and an
    # underscore is a word character, so no word edge falls between "_" and "c".
    return _vr_divides_by_100(sql) and "crore" in sql.lower()


def _village_name_filter_instead_of_code(entity_result: dict, sql: str) -> "int | None":
    """The resolved village_code when the question resolved to one but the
    generated SQL filters on lgd_village_name instead — the exact "Bamil
    Reserve Apal" bug (2026-09-09): entity resolution correctly picked
    village_code, prompt_builder's RESOLVED ENTITIES block told the generator
    to use it verbatim and NOT filter on lgd_village_name, and the generator
    did it anyway, inventing an upper-cased lgd_village_name literal. Storage
    keeps village names in mixed/title case (curated.v_pmay has "Bamil
    Reserve Apal", not "BAMIL RESERVE APAL"), so the literal silently matches
    zero rows and the query runs clean but returns 0. village_code is the
    only column guaranteed to match."""
    code = entity_result.get("resolved", {}).get("village_code")
    if code is None or _vr_filters_village_code(sql):
        return None
    return code if _vr_filters_village_name(sql) else None


def _village_filtered_at_wrong_level(entity_result: dict, sql: str) -> "tuple[int, str] | None":
    """(village_code, offending clause) when a resolved village is filtered as a
    BLOCK or DISTRICT instead, else None.

    Only fires when the literal is the village's OWN display name — a genuine
    district scope alongside a village ("... in NONGLADEW, Ri Bhoi") is a real,
    correct filter and must be left alone.

    A correct `village_code` filter being present is NOT on its own a reason to
    pass: the generator sometimes emits BOTH, ANDing a bogus
    `lgd_block = '<village name>'` onto the right village_code. That still
    matches zero rows, so the query returns a confident 0 for a village with
    real records — confirmed live 2026-09-17 on "william nagar(mb) - ward
    no.4", where village_code = 70675 was correct and the added
    `lgd_block = 'WILLIAM NAGAR(MB)'` zeroed a true count of 1."""
    resolved = entity_result.get("resolved") or {}
    code = resolved.get("village_code")
    if code is None:
        return None
    display = (entity_result.get("display") or {}).get("village")
    if not display:
        return None
    # Compare with punctuation and spacing squashed out, and accept a PREFIX of
    # the village name as well as the whole of it: the literal the generator
    # writes is often the same truncation the extractor produced
    # ("WILLIAM NAGAR(MB)" for the village "William Nagar (MB) - Ward No.4").
    # It is still a village name sitting in a block/district column either way.
    _keep = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    _squash = lambda t: "".join(ch for ch in str(t).upper() if ch in _keep)
    want = _squash(display)
    for col, val in _vr_values(sql or "", ["lgd_district", "lgd_block"], _VR_EQ + _VR_ILIKE + _VR_IN):
        got = _squash(val)
        # Guard against a 1-2 character fragment matching by accident.
        if got and len(got) >= 4 and want.startswith(got):
            return code, f"{col} = '{val}'"
    return None


def _village_code_as_geography_key(entity_result: dict, sql: str) -> "int | None":
    """The resolved village_code when the generated SQL filters `geography_key`
    directly to that same integer literal instead of `village_code` — a
    silent-wrong-number bug distinct from the lgd_village_name one above.
    geography_key is a small surrogate key on curated.dim_geography, entirely
    unrelated to the LGD village_code (e.g. MASKA village is geography_key =
    5999 but village_code = 277769), so plugging the resolved village_code
    value straight into geography_key's WHERE clause matches no row and the
    query runs clean but returns NULL (reported 2026-09-10 UAT: a real ~0.5
    lakh MGNREGA expenditure for a small village came back "doesn't cover
    that metric" because the generated SQL filtered geography_key = 277769 —
    a village_code — instead of village_code = 277769). Filtering geography_key
    via a dim_geography subquery keyed on village_code is fine and NOT
    flagged — only a bare literal placed in geography_key's slot is."""
    code = entity_result.get("resolved", {}).get("village_code")
    if code is None:
        return None
    try:
        want = int(code)
    except (TypeError, ValueError):
        return None
    if want in _vr_int_values(sql, "geography_key", _VR_EQ):
        return code
    return None


# The SQL verifier (a small model) occasionally hallucinates that the
# RESOLVED ENTITIES block it was just handed "is empty" even when
# prompt_builder._entities_block plainly rendered entries into it — confirmed
# live 2026-09-13: "How many Focus+ beneficiaries are there in wgh across all
# financial years" resolved district = WEST GARO HILLS correctly, the verify
# prompt genuinely contained "lgd_district = 'WEST GARO HILLS'" under
# "RESOLVED ENTITIES — MANDATORY...", and the verifier still claimed the
# block was empty on every one of 5 repeat calls with an unchanged prompt.
# Each "repair" attempt then re-sent the same (correct) SQL, got the same
# false complaint back, and after 4 attempts the whole question fell through
# to the KB fallback instead of ever running the query. entity_result
# ["resolved"] is ground truth this process built itself (not the model's
# guess), so a claim that contradicts it is a verifier error to discard, not
# a real Check 2 hit — unlike the case where resolved really is empty, which
# this guard leaves alone.
def _c11_sp1(gap: str) -> bool:
    """Exactly one space, no more and no other whitespace."""
    return gap == " "


def _c11_lit(phrase: str):
    """Words separated by exactly one space each ("financial year")."""
    parts = phrase.split()
    return Seq(W(parts[0]), *[_C1xGapIs(W(w), _c11_sp1) for w in parts[1:]])


def _c11_check(*digits: str):
    r""""check 2" / "check2": whole-word "check", optional spaces, one of `digits`."""
    return Alt(Seq(W("check"), _C1xGapIs(W(*digits), _c1x_ws0)), W(*["check" + d for d in digits]))


# "resolved entities … is empty" with no full stop in between (at most 200 characters)
_VERIFIER_FALSE_EMPTY_ENTITIES = Matcher(Seq(
    _c1x_suffix("resolved"), _C1xGapIs(W("entities"), _c11_sp1), _C1xCharGap(max_chars=200, forbid="."),
    _c11_lit("is empty")))

# Second known verifier false positive, same family as the one above. The
# RESOLVED ENTITIES block renders an assembly-constituency filter in a
# case-insensitive wrapper — UPPER(assembly_constituency_name) = UPPER('X') —
# because the SME catalogue's spelling and the stored spelling can differ in
# case. assembly_constituency_name is stored ALL CAPS
# (mgnrega_entity_resolver.yaml: stored_case: ALL CAPS), so a generator that
# writes the equivalent bare `assembly_constituency_name = 'X'` has produced a
# query that selects exactly the same rows. The verifier nonetheless flags the
# difference in FORM as a Check-2 entity mismatch (confirmed live 2026-09-15:
# "…within the MAWLAI block only" — attempt 1 was flagged purely for dropping
# the UPPER() wrapper). That rejection then feeds a repair prompt telling the
# generator its entity filter is "missing", and the repair reliably "fixes" it
# by dropping the OTHER filter instead, so every later attempt is flagged for a
# genuinely missing entity and the whole question falls through to the KB
# fallback ("couldn't build a working query").
#
# Only discarded when the column really is filtered to the resolved value in
# the SQL — a genuinely absent filter still raises, which is the check's whole
# purpose.
_VERIFIER_CASE_FORM_COMPLAINT = Matcher(Alt(
    W("lowercase", "uppercase", "verbatim"),
    Seq(W("upper"), _C1xGapIs(ANY, lambda g: g == "(")),          # "upper(assembly_…"
    Seq(W("case"), _C1xGapIs(W("insensitive"), lambda g: g in ("-", " "))),
    _c11_lit("correct case"),
))


def _verifier_complaint_is_cosmetic(issue: str, resolved: dict, sql: str) -> bool:
    """True when the verifier's complaint is about the FORM of a filter that is
    in fact present and correct in the SQL."""
    if not _VERIFIER_CASE_FORM_COMPLAINT.search(issue or ""):
        return False
    ac = (resolved or {}).get("assembly_constituency")
    if not ac:
        return False
    # The AC value is genuinely filtered on, in either form.
    want = str(ac).upper()
    return any(v.upper() == want
               for _, v in _vr_values(sql or "", ["assembly_constituency_name"], _VR_EQ))


# Third known verifier false positive. When a village_code is resolved, the
# RESOLVED ENTITIES block deliberately SUPPRESSES the district/block that
# merely scoped the village lookup (prompt_builder._entities_block: they are
# redundant with village_code, which already pins one exact row-set, and
# rendering them as equally MANDATORY made the verifier demand filters the
# generator was right to omit). The verifier nonetheless sometimes "quotes" a
# district entity that was never in its prompt and rejects village-only SQL for
# omitting it — confirmed live 2026-09-15 on "ASIMGRE ... for East Garo Hills",
# where the block plainly contained only `village_code = 275373` yet the issue
# read "RESOLVED ENTITIES block lists lgd_district = 'EAST GARO HILLS'".
# Correct SQL is then repaired away and the question dies in the KB fallback.
#
# Discarded only when a village_code IS resolved AND the SQL genuinely filters
# on it — i.e. exactly the shape where the suppressed district is redundant.
_C11_GEO_WORD = W("lgd_district", "lgd_block", "district", "block")
_VERIFIER_SUPPRESSED_GEO_COMPLAINT = Matcher(Alt(
    Seq(_C11_GEO_WORD, _C1xCharGap(max_chars=120, forbid="."),
        Alt(W("missing", "omitted", "absent", "instead"), _c11_lit("not present"))),
    Seq(Alt(W("missing", "omitted", "absent"), _c11_lit("not present")),
        _C1xCharGap(max_chars=120, forbid="."), _C11_GEO_WORD),
))


def _verifier_wants_suppressed_geography(issue: str, resolved: dict, sql: str) -> bool:
    """True when the verifier demands a district/block that _entities_block
    intentionally left out because a resolved village_code supersedes it."""
    code = (resolved or {}).get("village_code")
    if code is None:
        return False
    if not _VERIFIER_SUPPRESSED_GEO_COMPLAINT.search(issue or ""):
        return False
    try:
        want = int(str(code).strip())
    except ValueError:
        return False
    return want in _vr_int_values(sql or "", "village_code", _VR_EQ + _VR_IN)


# Fourth known verifier false positive. A financial year is stored by its START
# year — FY 2023-24 IS year_key = 2023 (docs/DATA_MODEL.md; entity resolution
# emits exactly that). The verifier repeatedly reads the "-24" half as the value
# that should appear and flags correct SQL as using the wrong year: confirmed
# live 2026-09-17 on "…in RERAPARA … for FY 2023-24", where SQL filtering
# year_key = 2023 — matching the resolved entity verbatim — was rejected on 5 of
# 5 calls ("the question asks for FY 2023-24, but the SQL filters on year_key =
# 2023"). Every repair then re-sent the same correct query, the budget ran out,
# and a perfectly answerable question died in the KB fallback.
#
# Discarded only when the SQL's year_key genuinely equals the resolved one, so a
# real year mismatch still raises.
_VERIFIER_YEAR_COMPLAINT = Matcher(Alt(W("year_key", "fy"), _c11_lit("financial year")))


def _verifier_year_complaint_is_false(issue: str, resolved: dict, sql: str) -> bool:
    """True when the verifier disputes the year but the SQL already filters on
    exactly the resolved year_key."""
    year = (resolved or {}).get("year_key")
    if year is None:
        return False
    if not _VERIFIER_YEAR_COMPLAINT.search(issue or ""):
        return False
    keys, labels = _vr_year_values(sql or "")
    filters = {str(y) for y in keys if 1000 <= y <= 9999}
    # A view that carries the FY label filters on it instead — financial_year_short
    # = '2024-25' IS year_key 2024 (Focus Legacy QA TC-23, 2026-09-25: rejected as
    # "the resolved entity value (2024) is not present in the WHERE clause").
    for label in labels:
        s = label.strip()
        if len(s) == 7 and _vr_fy_start(s) is not None:
            filters.add(str(_vr_fy_start(s)))
    return filters == {str(int(year))}


# Fifth known verifier false positive, and the most clear-cut of the family: the
# verifier states as fact that the WHERE clause "omits these filters entirely"
# when the filters are sitting in it verbatim. Confirmed live 2026-09-18 on
# "How many applicants are there in BATABARI under Agro Tourism Villa Scheme,
# PRIME Small Enterprise Empowerment and Development (SEED) and Meghalaya
# Poultry Farming Scheme, BATABARI block, WEST GARO HILLS": entity resolution
# produced block=BATABARI + district=WEST GARO HILLS, the generator emitted
#   AND lgd_block = 'BATABARI' AND lgd_district = 'WEST GARO HILLS'
# and the verifier still returned "RESOLVED ENTITIES block lists lgd_block =
# 'BATABARI' and lgd_district = 'WEST GARO HILLS', but the SQL WHERE clause
# omits these filters entirely" on 10 of 10 calls. Each repair re-sent the same
# correct SQL, the 3-repair budget ran out, and a question whose answer is a
# plain 46 (SEED 43 + Poultry 2 + Agro Tourism Villa 1) died in the KB fallback
# as "couldn't build a working query".
#
# Unlike the assembly-constituency guard above, this is not about the FORM of a
# filter — the verifier is misreading a long multi-line WHERE clause and denying
# a literal that is plainly there. So the test is the strongest one available:
# discard the complaint only when EVERY resolved geography entity it names is
# provably filtered on in the SQL. A genuinely missing filter still raises,
# which keeps Check 2 doing its job.
_VERIFIER_MISSING_GEO_COMPLAINT = Matcher(Alt(
    W("omit", "omits", "omitted", "omitting", "missing", "absent", "lack", "lacks"),
    _c11_lit("not present"), _c11_lit("no filter"),
    Seq(_c11_lit("does not"), _C1xGapIs(W("include", "filter", "contain"), _c11_sp1)),
    Seq(_c11_lit("fails to"), _C1xGapIs(W("include", "filter"), _c11_sp1)),
))

# resolved-entity key -> the SQL column prompt_builder._entities_block renders
# it as, which is the column the verifier names back in its complaint.
_RESOLVED_GEO_COLUMNS = {
    "district": "lgd_district",
    "block": "lgd_block",
    "assembly_constituency": "assembly_constituency_name",
}


def _sql_filters_on(sql: str, column: str, value: str) -> bool:
    """True when `sql` constrains `column` to `value`, in any of the forms the
    generator legitimately produces: bare equality, an UPPER()/LOWER() wrapper
    on either side, or membership in an IN (...) list."""
    # col = 'V'  |  UPPER(col) = 'V'  |  col = UPPER('V')  |  col IN ('A', 'V', ...)
    # — compared case-insensitively, as the stored case and the literal's may differ.
    want = str(value).upper()
    return any(v.upper() == want for _, v in _vr_values(sql or "", [column], _VR_EQ + _VR_IN))


# MGNREGA single-village queries (all-villages QA 2026-09-26). The 30B wrote a
# different village_code than the resolved one on every attempt for AMPATIGRI
# (276411 for 273749); the verifier rightly rejected it, three repairs repeated
# it, and the question died in the KB fallback. Exactly one village was
# resolved, so the only correct literal is known — substitute it.
_VR_CLAUSE_AFTER_WHERE = (TokenType.GROUP_BY, TokenType.ORDER_BY, TokenType.HAVING, TokenType.LIMIT)


def _top_level_where_span(sql: str) -> "tuple[int, int, int] | None":
    """(start of WHERE, start of its body, end of its body) for the query's OWN
    WHERE — never one inside parentheses. CM Elevate verification counts carry
    `COUNT(*) FILTER (WHERE data_verified = 'Valid')` in the SELECT list, and the
    first-WHERE text search rebuilt from inside that FILTER (2026-09-28). Read from
    SQLGlot's tokens, so a keyword inside a string literal or a comment is no
    keyword."""
    try:
        tokens = sqlglot.tokenize(sql or "", read=sql_ast.DIALECT)
    except (SqlglotError, ValueError):
        return None
    depth, where_at = 0, None
    for tok in tokens:
        tt = tok.token_type
        if tt == TokenType.L_PAREN:
            depth += 1
        elif tt == TokenType.R_PAREN:
            depth -= 1
        elif depth == 0:
            if tt == TokenType.WHERE and where_at is None:
                where_at = tok
            elif where_at is not None and tt in _VR_CLAUSE_AFTER_WHERE:
                return where_at.start, where_at.end + 1, tok.start
    return (where_at.start, where_at.end + 1, len(sql)) if where_at is not None else None


# A village FILTER, not just the column name: "SELECT COUNT(DISTINCT village_code)
# FROM curated.v_employment WHERE households_employed > 0" names village_code but
# filters no village — the statewide 5,529 villages-with-work was reported as
# "5,529 households in Mot village", a village with none (hierarchy matrix run
# 2026-10-14). A join condition (a.village_code = b.village_code) still counts as
# one, as before; only a bare mention in the SELECT / GROUP BY no longer does.
def _vr_filters_a_village(sql: str) -> bool:
    """village_code / geography_key compared with = or IN (either side, cast or
    not), or lgd_village_name compared with =, LIKE, ILIKE, IN or ~."""
    return (_vr_filters_col(sql, ["village_code", "geography_key"], _VR_EQ + _VR_IN)
            or _vr_filters_col(sql, ["lgd_village_name"], _VR_EQ + _VR_LIKE + _VR_IN + _VR_REGEX))


# The measure counts VILLAGES — right for "how many villages …", wrong for a
# question about one village's households / persons / works (COUNT(village_code)
# or COUNT(DISTINCT village_code), read on the tree).
def _c11_dot_ws(gap: str) -> bool:
    r"""An optional '.' then one or more whitespace characters."""
    return _c1x_ws(gap[1:] if gap.startswith(".") else gap)


# "how many / number of / no. of / count of / total" + up to three words + "villages"
_VILLAGE_COUNT_ASKED_MATCH = Matcher(Seq(
    Alt(Seq("how", "many", sep="space"), Seq("number", "of", sep="space"),
        Seq(W("no"), _C1xGapIs(W("of"), _c11_dot_ws)), Seq("count", W("of", "the"), sep="space"), W("total")),
    _C1xRun(lambda w: True, 0, 3, gap_ok=_c1x_ws, first_gap_ok=_c1x_ws),
    _C1xGapIs(W("villages"), _c1x_ws),
))


def _village_count_for_one_village(question: str, entity_result: dict, sql: str) -> "int | None":
    """The resolved village_code when the query, over ONE resolved village,
    counts villages (COUNT(DISTINCT village_code)) although the question never
    asked how many villages — the answer would be 0 or 1 'households'."""
    code = (entity_result.get("resolved") or {}).get("village_code")
    if not code or isinstance(code, (list, tuple)) or not sql:
        return None
    if not _vr_counts_column(sql, "village_code") or _VILLAGE_COUNT_ASKED_MATCH.search(question or ""):
        return None
    return int(code)


def _village_filter_missing(schemes: list[str], entity_result: dict, sql: str) -> "int | None":
    """_mgnrega_village_filter_missing for every scheme. A resolved village the
    SQL does not filter on at all is a wider area reported as that village.
    _resolved_scope_missing deliberately leaves villages to "the village
    guards", but the only one was MGNREGA's, so the other five schemes had
    none. Live 2026-10-02 (all-villages run): "How many applications are there
    under CM Elevate Legacy in NOAGRE?" resolved village_code 273728, and the
    30B read the name as a programme: WHERE scheme_name = 'Meghalaya New
    Agriculture and Allied Activities Scheme', no village, "zero records" for a
    village with 12. Every curated view carries village_code."""
    if not schemes or (schemes[0] != "MGNREGA" and len(schemes) != 1):
        return None
    code = (entity_result.get("resolved") or {}).get("village_code")
    if not code or isinstance(code, (list, tuple)) or not sql:
        return None
    # Unparseable SQL is left to execution, which reports the real error.
    if not sql_ast.is_parseable(sql) or _vr_filters_a_village(sql):
        return None
    return int(code)


def _geo_value_in_sql(value: str, sql_upper: str) -> bool:
    """A resolved place name is present in the SQL's string literals (compared
    upper-cased; the SQL is parsed, so '' is already one apostrophe): inside a
    literal, or as the search text of a LIKE / ILIKE / REGEXP_LIKE test on its first
    distinctive word ("%TURA%" for TURA MUNICIPAL BOARD)."""
    v = str(value).upper().replace("''", "'").strip()
    if not v:
        return True
    if any(v in lit.upper() for lit in sql_ast.string_literals(sql_upper)):
        return True
    words = "".join(" " if ch.isspace() or ch in "-()/," else ch for ch in v).split()
    first = next((w for w in words if len(w) >= 4), None)
    if not first:
        return False
    for tree in sql_ast.parse(sql_upper):
        for node in tree.find_all(*(_VR_LIKE + _VR_REGEX)):
            pat = _vr_unwrap(node.expression)
            if isinstance(pat, exp.Literal) and pat.is_string and first in pat.this.upper():
                return True
    return False


def _vr_digits_in(text: str, digits: str) -> bool:
    """`digits` occurs in `text` with no digit directly before or after it."""
    start = text.find(digits)
    while start != -1:
        end = start + len(digits)
        if (start == 0 or not text[start - 1].isdigit()) and (end == len(text) or not text[end].isdigit()):
            return True
        start = text.find(digits, start + 1)
    return False


def _vr_year_in_sql(year: int, sql: str) -> bool:
    """The year is in the query: as a number literal (year_key = 2023) or inside a
    string literal ('2023-24', 'FY 2023-24', '2023-04-01')."""
    y = str(year)
    for tree in sql_ast.parse(sql):
        for lit in tree.find_all(exp.Literal):
            if (lit.is_string and _vr_digits_in(lit.this, y)) or (not lit.is_string and lit.this == y):
                return True
    return False


def _vr_year_key_literals(sql: str) -> "set[int]":
    """The number literals compared with year_key (= / IN) anywhere in the query."""
    out: set[int] = set()
    for tree in sql_ast.parse(sql):
        for node in tree.find_all(exp.EQ, exp.In):
            col, vals = node.this, ([node.expression] if isinstance(node, exp.EQ) else node.expressions)
            if isinstance(node, exp.EQ) and not sql_ast._is_column(col, {"year_key"}):
                col, vals = node.expression, [node.this]
            if not sql_ast._is_column(col, {"year_key"}):
                continue
            for v in vals:
                v = sql_ast._unwrap(v)
                if isinstance(v, exp.Literal) and not v.is_string and v.this.isdigit():
                    out.add(int(v.this))
    return out


def _resolved_scope_missing(question: str, schemes: list[str], entity_result: dict,
                            sql: str) -> "tuple[str, str] | None":
    """(field, repair instruction) when a place or year the question pinned is
    absent from the SQL, else None — the deterministic half of the semantic
    contract between entity resolution and SQL generation.

    KI-034 (live 2026-09-26, context validation K8): a fallback fragment carried
    the resolved district and year in the MANDATORY entities block, the SQL had no
    WHERE clause at all, and the verifier passed it — a statewide all-years figure
    reported for one district and year. The prompt rule (MANDATORY entities) and
    the verifier are prose checks that sampling can skip; this one cannot.

    Checked: a resolved district / block (and every member of a district_list /
    block_list comparison) must appear in the SQL; a resolved year_key must too.
    Deliberately NOT checked, because the SQL is right without them:
      - district / block when a village_code is resolved: _entities_block
        suppresses them as redundant, and the village guards own that case;
      - a hill-range expansion (district_list_region): the SQL may cover it
        by a LIKE match;
      - the year for a scheme with no time dimension (CM Elevate), or when the
        question itself asks for all years."""
    resolved = entity_result.get("resolved") or {}
    # Unparseable SQL is left to execution, which reports the real error.
    if not sql or not resolved or not sql_ast.is_parseable(sql):
        return None
    text = sql
    village = resolved.get("village_code") or resolved.get("village_code_list")
    if not village:
        for key in ("district", "block"):
            v = resolved.get(key)
            if isinstance(v, str) and v.strip() and not _geo_value_in_sql(v, text):
                # Focus Plus maps blocks on block_name_raw (prompt_builder._entities_block)
                col = ("UPPER(block_name_raw)" if key == "block" and schemes == ["Focus Plus"]
                       else f"lgd_{key}")
                return key, (
                    f"the question is about {key} {v} (a RESOLVED, MANDATORY filter), but this "
                    f"query does not filter on it, so it returns a figure for a different or "
                    f"wider area. Add {col} = '{v}' to the WHERE clause, exactly as the RESOLVED "
                    "ENTITIES block says, and keep every other filter, the aggregation and the "
                    "grouping exactly as they were.")
        # KI-432 (MGNREGA Excel run 2026-10-27): a repair dropped the constituency filter
        # and the STATEWIDE expenditure (106,669.85 lakh) was answered as Amlarem's
        # (correct 1,090.03 for FY 2023-24). A resolved constituency must be in the SQL.
        # MGNREGA only: the other schemes reach the constituency through dim_geography
        # and have their own drift guard with that join in its instruction (Focus Legacy
        # sheet run 2026-10-22, test_constituency_drift_guard_raises_in_the_attempt).
        ac = resolved.get("assembly_constituency")
        if schemes == ["MGNREGA"] and isinstance(ac, str) and ac.strip() and not _geo_value_in_sql(ac, text):
            return "assembly_constituency", (
                f"the question is about the {ac} assembly constituency (a RESOLVED, MANDATORY filter), "
                "but this query does not filter on it, so it returns a figure for a different or wider "
                f"area. Filter UPPER(assembly_constituency_name) = UPPER('{ac}') on v_employment, or "
                f"UPPER(ac_name) = UPPER('{ac}') on v_expenditure, and keep every other clause as it was.")
        for key, dim in (("district_list", "district"), ("block_list", "block")):
            vals = resolved.get(key)
            if key == "district_list" and resolved.get("district_list_region"):
                continue
            if isinstance(vals, (list, tuple)) and len(vals) >= 2:
                absent = [v for v in vals if isinstance(v, str) and not _geo_value_in_sql(v, text)]
                if absent:
                    return key, (
                        f"the question compares the {dim}s {', '.join(map(str, vals))}, but this "
                        f"query leaves out {', '.join(map(str, absent))}. Filter lgd_{dim} IN "
                        f"({', '.join(repr(str(v)) for v in vals)}), GROUP BY lgd_{dim} so each one "
                        "gets its own figure, and keep every other clause as it was.")
    yk = resolved.get("year_key")
    years = [yk] if isinstance(yk, int) else [y for y in (yk or []) if isinstance(y, int)] \
        if isinstance(yk, (list, tuple)) else []
    timed = bool(schemes) and all(_SCHEME_DATA_YEARS.get(s) for s in schemes)
    if years and timed and not _ALL_YEARS_CUE.search(question or ""):
        absent_y = [y for y in years if not _vr_year_in_sql(y, sql)]
        if absent_y:
            fy = ", ".join(f"FY {y}-{(y + 1) % 100:02d}" for y in absent_y)
            # KI-431: told "does not filter on it" about year_key = 2023 (a wrong year, not
            # a missing one), the repair kept 2023 three times. Name the wrong year.
            other = sorted(_vr_year_key_literals(sql) - set(years))
            what = (f"this query filters year_key = {', '.join(map(str, other))} instead, a different year"
                    if other else "this query does not filter on it, so it adds up every year")
            return "year", (
                f"the question is about {fy} (a RESOLVED, MANDATORY filter; year_key = "
                f"{absent_y[0]} is the FY start year), but {what}. Use the year filter in the scheme's "
                f"own form (year_key = {absent_y[0]}, or its financial_year column) and keep every "
                "other clause as it was.")
    # KI-427: a stated span (year_key_list) — every year must be in the query, as a
    # literal or inside a BETWEEN whose ends are the span's ends.
    span = sorted({int(y) for y in (resolved.get("year_key_list") or []) if isinstance(y, int)})
    if not years and len(span) >= 2 and timed and not _ALL_YEARS_CUE.search(question or ""):
        absent_y = [y for y in span if not _vr_year_in_sql(y, sql)]
        if absent_y and not _vr_between_covers(sql, span[0], span[-1]):
            fy = ", ".join(f"FY {y}-{(y + 1) % 100:02d}" for y in absent_y)
            return "year", (
                f"the question asks for every financial year from FY {span[0]}-{(span[0] + 1) % 100:02d} "
                f"to FY {span[-1]}-{(span[-1] + 1) % 100:02d} (a RESOLVED, MANDATORY filter), but this "
                f"query leaves out {fy}. Filter year_key BETWEEN {span[0]} AND {span[-1]} (or the "
                "scheme's own financial-year column for the same years) and keep every other clause "
                "as it was.")
    return None


def _vr_between_covers(sql: str, lo: int, hi: int) -> bool:
    """A BETWEEN in the query with number or year-string ends lo and hi."""
    for tree in sql_ast.parse(sql):
        for node in tree.find_all(exp.Between):
            low, high = sql_ast._unwrap(node.args.get("low")), sql_ast._unwrap(node.args.get("high"))
            if isinstance(low, exp.Literal) and isinstance(high, exp.Literal) \
                    and _vr_digits_in(low.this, str(lo)) and _vr_digits_in(high.this, str(hi)):
                return True
    return False


# The converse false positive: the SQL filters exactly the resolved village_code
# and year, and the verifier still invents a check-2 complaint — "RESOLVED
# ENTITIES specifies lgd_district = 'UPPER DARENGRE'" (it is a village), or
# "273990 is the code for a different village (likely from the calibration
# examples)" for MALIPARA, whose code it is. Correct SQL died in the KB fallback.
_VERIFIER_CHECK2_MATCH = _C1xUnion(Matcher(_c11_check("2")), "RESOLVED ENTITIES")

# "Which villages in Tikrikila assembly constituency received employment?" (DATA-014,
# test run 2026-10-06): the verifier read GROUP BY lgd_village_name as a village
# FILTER added beside the constituency ("CONSTITUENCY ONLY ... do NOT add
# village_code conditions") and rejected it; the repair dropped the grouping, the
# village-list guard (_mgnrega_village_list_issue) demanded it back, and the two
# alternated until the repair budget ran out. Grouping by a place column is how a
# per-place list is built, not a filter on it.
# the place columns, found anywhere in the complaint (case-insensitive)
_PLACE_COL_MATCH = _C1xUnion("lgd_village_name", "village_code", "lgd_block", "lgd_district",
                          "assembly_constituency_name")
_PER_PLACE_ASK_MATCH = Matcher(Alt(
    Seq(W("which", "what", "list", "name", "show"), _C1xCharGap(max_chars=30, forbid="?"),
        W("villages", "blocks", "districts")),
    Seq(W("each", "every", "per", "by"), W("village", "block", "district"), sep="space"),
    Joined(("village", "block", "district"), "wise"),
))
_C11_GROUP_BY = Matcher(Seq("group", "by", sep="space"))


def _verifier_groupby_complaint_is_false(issue: str, question: str, sql: str) -> bool:
    """True when the verifier objected to a GROUP BY on a place column for a
    question that asks for a per-place list, and the WHERE clause adds no
    condition on any place column the complaint names."""
    if not _C11_GROUP_BY.search(issue or ""):
        return False
    if not _PER_PLACE_ASK_MATCH.search(question or ""):
        return False
    named = {c.lower() for c in _PLACE_COL_MATCH.findall(issue or "")}
    if not named:
        return False
    # Columns any WHERE condition of the query reads (a GROUP BY is not a filter).
    in_where = {c.name.lower() for tree in sql_ast.parse(sql or "")
                for w in tree.find_all(exp.Where) for c in w.find_all(exp.Column) if c.name}
    return not any(c in in_where for c in named if c != "assembly_constituency_name")


def _verifier_village_code_complaint_is_false(issue: str, schemes: list[str],
                                              resolved: dict, sql: str) -> bool:
    # Focus Legacy too: a pinned village chip carries its district, the SQL filters
    # the code alone (_focus_legacy_village_code_only), and the verifier's "district
    # dropped" complaint sent the list to the KB fallback (Belbari, DAPGIRI —
    # all-villages run 2026-09-29, KI-161).
    # CM Elevate Legacy too, since its village-code guard drops the chip's block /
    # district literals (KI-173): DARUGRE / MARENGPARA, Purakhasia, were rejected
    # 4 times and answered "couldn't build a working query" (final pass 2026-09-29).
    if not ("MGNREGA" in schemes or _village_scheme(schemes) or schemes in (["Focus Legacy"], ["CM Elevate Legacy"])) \
            or not _VERIFIER_CHECK2_MATCH.search(issue or ""):
        return False
    code = (resolved or {}).get("village_code")
    if not code or isinstance(code, (list, tuple)):
        return False
    found = _vr_int_values(sql or "", "village_code", _VR_EQ)
    if found != {int(code)}:
        return False
    yk = (resolved or {}).get("year_key")
    # Focus Plus filters the year as financial_year_short = '2025-26'
    if isinstance(yk, int):
        keys, labels = _vr_year_values(sql or "")
        if yk not in keys and yk not in {_vr_fy_start(l) for l in labels}:
            return False
    return True


def _verifier_missing_geo_is_false(issue: str, resolved: dict, sql: str) -> bool:
    """True when the verifier claims resolved geography filters are absent but
    every one it could be referring to is in fact present in the SQL."""
    if not _VERIFIER_MISSING_GEO_COMPLAINT.search(issue or ""):
        return False
    # Restrict to the geography entities the complaint actually names, by
    # column name or by value — so an unrelated grievance never trips this.
    named = {}
    for key, col in _RESOLVED_GEO_COLUMNS.items():
        val = (resolved or {}).get(key)
        if not val or not isinstance(val, str):
            continue
        if _c1x_bounded_find(col, issue or "") or val.lower() in (issue or "").lower():
            named[col] = val
    if not named:
        return False
    return all(_sql_filters_on(sql, col, val) for col, val in named.items())


# A verifier complaint that a RESOLVED place is "not listed" in the RESOLVED
# ENTITIES block, on SQL that filters exactly the resolved district and block.
# Live 2026-10-02 (live context suite, scenario F T3, both orchestrators):
# "What about Dalu block?" after "MGNREGA person-days in West Garo Hills in FY
# 2024-25" kept WEST GARO HILLS and added DALU; the verifier, given
#   lgd_district = 'WEST GARO HILLS' / lgd_block = 'DALU'
# in its prompt, answered "the RESOLVED ENTITIES block does NOT list
# 'lgd_block = DALU'". The repairs then alternated between dropping the block
# (the scope guard re-added it) and the district, the budget ran out and the
# question was answered from the reference documents. The SQL was right
# (390,921). Discarded only when every resolved district / block is filtered
# verbatim and the SQL names no other district or block.
# "(does / do / is / are) not" or "doesn't / don't / isn't / aren't" + list / include / …
# ("does not list" is "not list"; the n't forms need the apostrophe)
_VERIFIER_NOT_LISTED = Matcher(Seq(
    Alt(W("not"), Seq(W("doesn", "don", "isn", "aren"), _C1xGapIs(W("t"), lambda g: g in ("'", "’")))),
    _C1xGapIs(Alt(W("list", "listed", "include", "included", "contain", "contained", "mention",
                    "mentioned", "appear", "present"), W("specif", prefix=True)), _c1x_ws),
))


def _verifier_unlisted_geo_is_false(issue: str, resolved: dict, sql: str) -> bool:
    """True when the verifier says a resolved district / block is not in the
    RESOLVED ENTITIES block while the SQL filters exactly the resolved ones."""
    if not _VERIFIER_NOT_LISTED.search(issue or ""):
        return False
    geo = {col: str(resolved[key]).upper() for key, col in (("district", "lgd_district"), ("block", "lgd_block"))
           if isinstance((resolved or {}).get(key), str) and resolved[key]}
    if not geo or not any(_c1x_bounded_find(v, issue or "") for v in geo.values()):
        return False
    in_sql: dict[str, set[str]] = {}
    for col, val in _vr_values(sql or "", ["lgd_district", "lgd_block"], _VR_EQ):
        in_sql.setdefault(col, set()).add(val.upper())
    return (all(_sql_filters_on(sql, col, val) for col, val in geo.items())
            and all(vals <= {geo.get(col)} for col, vals in in_sql.items()))


# KI-308 (live 2026-10-18, scenario F): "What about Dalu block?" after MGNREGA West
# Garo Hills. The deterministic guard (_missing_resolved_filter) demands the
# RESOLVED district, so the SQL carries lgd_district = 'WEST GARO HILLS' AND
# lgd_block = 'DALU'; the verifier then calls that district "unnecessary … not
# part of the resolved entities" and asks to remove it; the repair removes it,
# the guard adds it back, until the repair budget is spent and the question dies
# ("couldn't build a working query"). A resolved place is a MANDATORY filter by
# contract, never one to remove: such a removal request is discarded when the
# value is resolved and the SQL filters on it.
_VERIFIER_REMOVE_FILTER = Matcher(Alt(
    W("unnecessary", "remove", "removed", "extraneous", "redundant", "superfluous", "drop", "dropped"),
    _c11_lit("should not be included"), _c11_lit("not be included"), _c11_lit("should not include"),
    _c11_lit("not part of"), _c11_lit("should not filter"), _c11_lit("not needed"),
))


def _verifier_wants_resolved_filter_removed(issue: str, resolved: dict, sql: str) -> bool:
    """True when the verifier asks to drop a RESOLVED district / block that the
    SQL rightly filters on (the mandatory-filter guard would put it back)."""
    if not _VERIFIER_REMOVE_FILTER.search(issue or ""):
        return False
    geo = {col: str(resolved[key]).upper() for key, col in (("district", "lgd_district"), ("block", "lgd_block"))
           if isinstance((resolved or {}).get(key), str) and resolved[key].strip()}
    if not geo or not any(_c1x_bounded_find(v, (issue or "").upper()) for v in geo.values()):
        return False
    # Every place filter in the SQL must be a resolved one: then nothing the
    # verifier could mean is removable. An unresolved place filter keeps the complaint.
    in_sql: dict[str, set[str]] = {}
    for col, val in _vr_values(sql or "", ["lgd_district", "lgd_block"], _VR_EQ):
        in_sql.setdefault(col, set()).add(val.upper())
    return (bool(in_sql) and all(vals <= {geo.get(col)} for col, vals in in_sql.items())
            and all(_sql_filters_on(sql, col, val) for col, val in geo.items()))


# Sixth known verifier false positive: a scheme name containing an apostrophe.
# In SQL a literal apostrophe is written doubled ('Chief Minister''s Green Taxi
# Scheme'), which is the SAME string as the resolved entity once parsed. The
# verifier reads the two spellings as different values and rejects correct SQL,
# quoting the identical text on both sides of its own complaint — confirmed
# live 2026-09-18 on "applicants in mylliem, the block ... under Green Taxi CM
# Elevate and ware house Scheme", flagged on 8 of 8 calls with
#   "RESOLVED ENTITIES block specifies scheme_name = 'Chief Minister''s Green
#    Taxi Scheme' (verbatim), but the SQL filters on ... 'Chief Minister''s
#    Green Taxi Scheme'"
# The query is right and returns 2; only the verifier disagrees, so the repair
# loop burned its budget and the question died in the KB fallback.
#
# Discarded only when un-doubling the SQL's apostrophes makes the resolved
# value genuinely present — a real value mismatch still raises.
_VERIFIER_VERBATIM_COMPLAINT = Matcher(Alt(
    W("verbatim", "exact", "exactly", "mismatch", "differ", "different", "differs"),   # also "slightly different"
    _c11_lit("does not match"),
))


def _verifier_apostrophe_complaint_is_false(issue: str, resolved: dict, sql: str) -> bool:
    """True when the verifier disputes a resolved value that the SQL does carry,
    differing only by SQL's doubled-apostrophe escaping."""
    if not _VERIFIER_VERBATIM_COMPLAINT.search(issue or ""):
        return False
    # Only values that actually contain an apostrophe can hit this.
    vals = [v for v in (resolved or {}).values() if isinstance(v, str) and "'" in v]
    for v in (resolved or {}).values():
        if isinstance(v, list):
            vals.extend(x for x in v if isinstance(x, str) and "'" in x)
    if not vals:
        return False
    # The parsed literals: SQL's '' is already one apostrophe in them.
    lits = sql_ast.string_literals(sql or "")
    return all(any(v in lit for lit in lits) for v in vals)


# Seventh known verifier false positive: a "prohibited join" in SQL that joins
# nothing. The PROHIBITED JOINS block carries self-edges that are really grain
# rules ("NEVER join curated.v_focus_legacy -> curated.v_focus_legacy directly.
# Use GROUP BY pg_id instead.") and "any -> <base fact>" edges, and the small
# verifier reads them as forbidding the view itself. Confirmed 2026-09-25 in the
# Focus Legacy QA: TC-22 "records for each financial year" was rejected on every
# attempt ("The SQL joins directly to 'curated.v_focus_legacy', which is a
# prohibited join") for a one-table GROUP BY, and TC-20/TC-21 intermittently
# ("joins directly to curated.fact_focus_legacy_disbursement" — a table the SQL
# never names). The repair budget ran out and a plain COUNT(*) died as
# "couldn't build a working query".
#
# Discarded only when the complaint is about a PROHIBITED join and is provably
# false: the SQL has no JOIN and reads a single table, or every table the
# complaint names is absent from the SQL. A query that really joins a named
# table still raises.
_VERIFIER_PROHIBITED_JOIN = Matcher(W("prohibit", prefix=True))
_C11_JOIN_WORD = Matcher(W("join", prefix=True))
# Table names the verifier's English complaint mentions (the complaint, not the SQL).
_ISSUE_TABLE_REF = Matcher(Seq(W("curated", "raw", "semantic", "meta", "app"),
                               _C1xGapIs(ANY, lambda g: g == ".")))


# Eighth: a Check 2 (resolved-entity) complaint when NOTHING was resolved. The
# verify prompt tells the verifier that "an empty or absent block means there is
# nothing to check here, so answer this check true" — yet it flagged "How many
# Producer Groups are mapped to each district" (GROUP BY lgd_district, no WHERE)
# on every attempt: "The RESOLVED ENTITIES block is empty ... the SQL attempts
# to group by lgd_district, which implies a geography filter exists" (Focus
# Legacy QA TC-25, 2026-09-25). Discarded only when the resolved block really is
# empty of filter entities and the complaint names no other check.
_VERIFIER_CHECK2 = Matcher(Alt(_c11_check("2"), Seq("resolved", W("entit", prefix=True), sep="space")))
# Only an explicit reference to another check keeps the complaint alive — its
# wording ("filtering/aggregating on a dimension that was not resolved") is the
# same false Check 2 complaint, not a grain or metric finding.
_VERIFIER_OTHER_CHECK = Matcher(Alt(_c11_check("1", "3", "4"), W("prohibit", prefix=True),
                                    Seq("missing", W("sum", "count", "avg"), sep="space")))
def _verifier_check2_on_empty_entities(issue: str, resolved: dict) -> bool:
    if any(v not in (None, "", [], {}) for v in (resolved or {}).values()):
        return False
    return bool(_VERIFIER_CHECK2.search(issue or "")) and not _VERIFIER_OTHER_CHECK.search(issue or "")


def _verifier_join_complaint_is_false(issue: str, sql: str) -> bool:
    if not (_VERIFIER_PROHIBITED_JOIN.search(issue or "") and _C11_JOIN_WORD.search(issue or "")):
        return False
    if not sql_ast.is_parseable(sql):
        return False
    in_sql = {t for t in sql_ast.tables(sql or "", qualified=True)
              if t.split(".")[0] in _VR_TABLE_SCHEMAS and "." in t}
    # An explicit JOIN, or a FROM list of several tables (SQLGlot reads both as joins).
    joins = bool(sql_ast.joins(sql or ""))
    if not joins and len(in_sql) <= 1:
        return True
    named = {t.lower() for t in _ISSUE_TABLE_REF.findall(issue or "")}
    return bool(named) and not (named & in_sql)
# No word edges are required anywhere: a lead word matches as a word ending
# ("cannot exist"), a last word as a word start ("not listed", "not existing").
_VERIFIER_NO_COLUMN = Matcher(Alt(
    Seq(_c1x_suffix("not"),
        Alt(W("list", "exist", "present", "defined", prefix=True), Seq(W("a"), W("column", prefix=True), sep="space"),
            Seq("in", "the", W("view", "schema", prefix=True), sep="space")), sep="space"),
    Pred(lambda w: "nonexistent" in w.lower()),
    Seq(_c1x_suffix("non"), _C1xGapIs(W("existent", prefix=True), lambda g: g == "-")),
    Seq(_c1x_suffix("does"), "not", W("have", "contain", "include", prefix=True), sep="space"),
    Seq(_c1x_suffix("no"), W("such", prefix=True), sep="space"),
    Seq(Alt(_c1x_suffix("isnt"), Seq(_c1x_suffix("isn"), _C1xGapIs(W("t"), lambda g: g in ("'", "’")))),
        Alt(Seq(W("a"), W("column", prefix=True), sep="space"), W("listed", prefix=True)), sep="space"),
))
_C11_CHECK3_GRAIN = Matcher(Alt(_c11_check("3"), W("grain")))
_C11_ROW_GRAIN_WORDS = _C1xUnion("multiple rows", "denormalised", "denormalized", "raw fact", "fact_cm_elevate")
_C11_DATE_WORDS = _C1xUnion("date", "time", "year_key", "financial_year", "month")
_C11_RANKING_ASK = Matcher(Alt(
    W("top", "highest", "most", "lowest", "least"), W("rank", prefix=True),
    Seq(W("which"), _C1xRun(lambda w: True, 0, 1, gap_ok=_c1x_ws, first_gap_ok=_c1x_ws),
        _C1xGapIs(W("village", "villages"), _c1x_ws)),
))
_C11_YEAR_WORD = Matcher(W("year", prefix=True))


def _verifier_scheme_specific_complaint_is_false(issue: str, schemes: list[str], sql: str,
                                                 resolved: "dict | None" = None) -> bool:
    # RAG fix report re-check (live 2026-10-29, Issue 12): "Average FOCUS+ amount per
    # beneficiary statewide" ran SUM(amount_disbursed) / COUNT(DISTINCT beneficiary_key) — the
    # right figure, ₹11,316 — and the verifier asked three times for "AVG(amount_disbursed) /
    # COUNT(DISTINCT beneficiary_key)" (an average of payments divided again), so the turn
    # fell to the documents. A per-beneficiary average built that way is never wrong.
    if schemes == ["Focus Plus"] and "avg" in (issue or "").lower() and _fp_amount_per_beneficiary_sql(sql):
        return True
    # 2026-09-28 (CM Elevate all-blocks run): "Check 2: … lists 'lgd_block = LASKEIN', but
    # the SQL uses a JSON path extraction ('scheme_specific ->> file_status') …" rejected a
    # correct "rejected in Laskein block" query that filters lgd_block = 'LASKEIN' — three
    # times, then the KB fallback. Same false claim, check-2 wording.
    # Tester-phrasing re-run (2026-09-28): "applicants in UMSHAKEN" (village 277617,
    # resolved) died after three "Check 3: Table/grain — v_cm_elevate … multiple rows
    # per applicant (one per scheme/year) … aggregate the raw fact table". False:
    # the view is one row per application, and COUNT(DISTINCT request_id) on it is
    # the documented applicant count (CM ELEVATE RULES rule 8).
    if schemes == ["CM Elevate"] and _C11_CHECK3_GRAIN.search(issue or "") \
            and _C11_ROW_GRAIN_WORDS.search(issue or ""):
        _tables = sql_ast.tables(sql or "", qualified=True)
        if _tables == {"curated.v_cm_elevate"} and _vr_counts_rows_or_requests(sql or ""):
            return True
    # Mawpat final pass (2026-09-28): after the literal snap wrote the stored
    # 'PRIME Tourism Vehicle Scheme', the verifier insisted the name has no "Scheme"
    # and rejected it three times. Every programme literal is an exact stored name
    # and every resolved place is filtered: a check-2 complaint there is false.
    if schemes == ["CM Elevate"] and _VERIFIER_CHECK2_MATCH.search(issue or "") and \
            sql_ast.references_column(sql or "", "scheme_name"):
        # every literal scheme_name is compared to (= or any IN value)
        _lits = [v for _, v in _vr_values(sql or "", ["scheme_name"], _VR_EQ + _VR_IN)]
        if _lits and all(x in _CME_PROGRAMME_WORDS for x in _lits) and (
                not any((resolved or {}).get(k) for k in ("district", "block", "village_code"))
                or _cme_resolved_places_in_sql(resolved, sql)):
            return True
    if schemes == ["CM Elevate"] and "scheme_specific" in (issue or "").lower() \
            and _VERIFIER_CHECK2_MATCH.search(issue or "") and _cme_resolved_places_in_sql(resolved, sql):
        keys = _vr_json_keys(sql or "", "scheme_specific")
        if keys and all(k.lower() in _CME_LIVE_JSON_KEYS for k in keys):
            return True
    """The 4B verifier claimed v_cm_elevate has no scheme_specific column and
    that file_status must be current_file_status, rejecting a correct
    "rejected in Ri Bhoi" query three times until the repair budget ran out
    (generalisation probe, 2026-09-27). scheme_specific IS a view column
    (schema_context CM ELEVATE TABLES) and these keys were read live."""
    if schemes != ["CM Elevate"] or "scheme_specific" not in (issue or "").lower():
        return False
    if not _VERIFIER_NO_COLUMN.search(issue or ""):
        return False
    keys = _vr_json_keys(sql or "", "scheme_specific")
    return bool(keys) and all(k.lower() in _CME_LIVE_JSON_KEYS for k in keys)


async def _verify_sql(question: str, schemes: list[str], entity_result: dict, sql: str) -> "str | None":
    """One short issue sentence if the semantic verifier (SQL_VERIFY_MODEL,
    the 30B coder — see app/config.py) flags this SQL as not actually
    answering the question, else None. Called after the query has run and
    passed the execution checks; it judges the SQL, not the rows
    (prompt_builder.build_verify_prompt says why).

    This is the catch-all for the class of bug the shape guards above can't
    be: they only recognise SQL shapes a past incident already taught them to
    match. The verifier judges the query against the same schema rules and
    resolved entities the generator itself was given, instead of a fixed
    shape.

    Best-effort like every other auxiliary check in this module (premise_check,
    followups, context layer): a verifier outage, timeout, or unparseable
    response degrades to "no issue found" rather than blocking an answer the
    pipeline would otherwise have produced successfully."""
    if not settings.SQL_VERIFY_ENABLED:
        return None
    try:
        # A level chip's tail (", the block, not another area type") is UI wording, already
        # resolved into the entities: shown to the verifier it asked for a block-level
        # restriction on a correct lgd_block filter, and the repair broke the count
        # (CM Elevate UAT 2026-10-30: UMLING, SAMANDA, MAWKYRWAT).
        prompt = prompt_builder.build_verify_prompt(_c01_strip_chip_level(question), schemes, entity_result, sql)
        raw = await llm.call_sql_verifier(prompt, guided={"guided_json": _SQL_VERIFY_JSON_SCHEMA})
        data = _extract_json(raw)
    except Exception:  # noqa: BLE001
        logger.warning("SQL verifier call failed — continuing without it", exc_info=True)
        return None
    if not data or data.get("ok", True):
        return None
    issue = data.get("issue") or "the SQL verifier flagged this query as not answering the question"
    if schemes == ["Focus Legacy"] and (sql or "").lstrip().startswith(_FL_FOUR_SELECT.strip()):
        logger.warning("SQL verifier judged the fixed four-measure Focus Legacy beneficiary select "
                       "(SME default) — discarding: %s", issue)
        return None
    if entity_result.get("resolved") and _VERIFIER_FALSE_EMPTY_ENTITIES.search(issue):
        logger.warning(
            "SQL verifier claimed RESOLVED ENTITIES is empty when resolved=%r says otherwise "
            "— discarding as a known verifier hallucination: %s", entity_result["resolved"], issue)
        return None
    # "remittances made between January and March 2026": the date filter IS the answer, but
    # the verifier said a year_key / financial_year filter was missing and the repair
    # answered for the whole FY 2025-26 (Focus Legacy sheet TC-20, 2026-10-12).
    if _MONTH_YEAR_IN_Q.search(question or "") and sql_ast.references_column(sql or "", "date_of_remittance") \
            and _C11_DATE_WORDS.search(issue):
        logger.warning("SQL verifier disputed a calendar-month date filter the question asks for "
                       "— discarding: %s", issue)
        return None
    if _verifier_complaint_is_cosmetic(issue, entity_result.get("resolved") or {}, sql):
        logger.warning(
            "SQL verifier complained about the FORM of an assembly-constituency filter that "
            "is present and correct — discarding as cosmetic: %s", issue)
        return None
    if _verifier_year_complaint_is_false(issue, entity_result.get("resolved") or {}, sql):
        logger.warning(
            "SQL verifier disputed the financial year when the SQL already filters on the "
            "resolved year_key (a FY is stored by its START year) — discarding: %s", issue)
        return None
    if _verifier_apostrophe_complaint_is_false(issue, entity_result.get("resolved") or {}, sql):
        logger.warning(
            "SQL verifier disputed a value that differs only by SQL apostrophe escaping "
            "('' is a literal ') — discarding: %s", issue)
        return None
    if _verifier_missing_geo_is_false(issue, entity_result.get("resolved") or {}, sql):
        logger.warning(
            "SQL verifier claimed the resolved geography filters are missing when the "
            "SQL filters on every one of them verbatim — discarding: %s", issue)
        return None
    if _verifier_unlisted_geo_is_false(issue, entity_result.get("resolved") or {}, sql):
        logger.warning(
            "SQL verifier said a resolved district/block is not in RESOLVED ENTITIES while the "
            "SQL filters exactly the resolved ones — discarding: %s", issue)
        return None
    if _verifier_wants_resolved_filter_removed(issue, entity_result.get("resolved") or {}, sql):
        logger.warning(
            "SQL verifier asked to remove a RESOLVED district/block the SQL rightly filters on "
            "(the mandatory-filter guard requires it; KI-308) — discarding: %s", issue)
        return None
    if _verifier_wants_suppressed_geography(issue, entity_result.get("resolved") or {}, sql):
        logger.warning(
            "SQL verifier demanded a district/block that the RESOLVED ENTITIES block "
            "deliberately suppressed as redundant with village_code — discarding: %s", issue)
        return None
    if _verifier_check2_on_empty_entities(issue, entity_result.get("resolved") or {}):
        logger.warning(
            "SQL verifier raised a resolved-entity (check 2) complaint with no resolved "
            "entities — its own instructions make that check pass — discarding: %s", issue)
        return None
    if _verifier_join_complaint_is_false(issue, sql):
        logger.warning(
            "SQL verifier reported a prohibited join the SQL does not make (no JOIN, or the "
            "named table is not in the query) — discarding: %s", issue)
        return None
    if _verifier_scheme_specific_complaint_is_false(issue, schemes, sql, entity_result.get("resolved") or {}):
        logger.warning(
            "SQL verifier claimed v_cm_elevate has no scheme_specific column / key when the SQL "
            "reads only live-verified keys — discarding: %s", issue)
        return None
    if _verifier_village_code_complaint_is_false(issue, schemes, entity_result.get("resolved") or {}, sql):
        logger.warning(
            "SQL verifier raised a resolved-entity complaint although the SQL filters exactly the "
            "resolved village_code and year (MGNREGA) — discarding: %s", issue)
        return None
    if _verifier_groupby_complaint_is_false(issue, question, sql):
        logger.warning(
            "SQL verifier read a GROUP BY on a place column as a place filter, for a question "
            "that asks for a per-place list — discarding: %s", issue)
        return None
    if _verifier_total_vs_breakdown_is_false(issue, question, sql):
        logger.warning(
            "SQL verifier demanded a single total for a question that asks for a breakdown the "
            "SQL already groups by (KI-315) — discarding: %s", issue)
        return None
    if _focus_legacy_ac_verifier_complaint_is_false(issue, schemes, entity_result, sql):
        logger.warning(
            "SQL verifier rejected the documented Focus Legacy constituency query (v_focus_legacy -> "
            "dim_geography on geography_key, ac_name = the resolved constituency; KI-369) — discarding: %s",
            issue)
        return None
    if _cm_legacy_ac_verifier_complaint_is_false(issue, schemes, entity_result, sql):
        logger.warning(
            "SQL verifier rejected the documented CM Elevate Legacy constituency query "
            "(v_cm_elevate_disbursement -> dim_geography on geography_key, ac_name = the resolved "
            "constituency; KI-381) — discarding: %s", issue)
        return None
    if _cme_ac_verifier_complaint_is_false(issue, schemes, entity_result, sql):
        logger.warning(
            "SQL verifier rejected the documented CM Elevate constituency query (v_cm_elevate -> "
            "dim_geography on geography_key, ac_name = the resolved constituency) — discarding: %s", issue)
        return None
    if _focus_legacy_aggregate_complaint_is_false(issue, schemes, sql):
        logger.warning(
            "SQL verifier said a Focus Legacy measure is not aggregated while the SQL SUMs exactly that "
            "column (KI-371) — discarding: %s", issue)
        return None
    return issue


# The GROUP BY columns that answer a breakdown by each dimension.
_C11_BREAKDOWN_COLUMNS = {
    "district": ("lgd_district", "district_name", "district"),
    "block": ("lgd_block", "block_name_raw", "block_name", "block"),
    "village": ("lgd_village_name", "village_code", "village_name", "village"),
    "year": ("year_key", "financial_year_short", "financial_year", "fy"),
}
_C11_TOTAL_COMPLAINT_WORDS = ("single", "total", "group", "grouped", "breakdown", "multiple rows", "one row",
                              "aggregated", "aggregate")


def _verifier_total_vs_breakdown_is_false(issue: str, question: str, sql: str) -> bool:
    """True when the question asks for a breakdown by district / block / village /
    year, the SQL GROUPs BY a column of that dimension, and the verifier complains
    that the query should return a single total instead. Live 2026-10-18 (KI-315,
    conversation harness): "How many PMAY-G houses were completed in Ri Bhoi in
    FY 2023-24 by block" lost all three repairs to "the question asks for a total
    count … not a breakdown by block … GROUP BY lgd_block violates the requirement
    for a single aggregated total" — then the deterministic breakdown guard put the
    GROUP BY back, and so on until the budget ended."""
    dims = _c02_breakdowns(question or "", include_per=False) & set(_C11_BREAKDOWN_COLUMNS)
    if not dims:
        return False
    low = (issue or "").lower()
    if not any(w in low for w in _C11_TOTAL_COMPLAINT_WORDS):
        return False
    grouped = sql_ast.group_by_columns(sql or "")
    if not grouped:
        return False
    return any(col in grouped for d in dims for col in _C11_BREAKDOWN_COLUMNS[d])


# The repair budget: the graph's execute_attempt -> repair loop runs at most
# MAX_SQL_REPAIRS + 1 attempts (pipeline_graph.node_execute_attempt).
MAX_SQL_REPAIRS = 3


def _repaired_sql_denial(scope: "auth.UserScope | None", schemes: list[str], entity_result: dict,
                         sql: str) -> "auth.AuthDecision | None":
    """KI-183 (found 2026-10-02): authorization ran once, on the FIRST SQL; the up
    to MAX_SQL_REPAIRS queries the repair model wrote afterwards ran unchecked,
    so a repair that added a district / block literal or a finer GROUP BY than
    the first query was never checked against a capped role. Every repaired
    query now passes the same auth.authorize before it runs. The denied
    decision, or None."""
    if scope is None or not settings.AUTH_ENABLED:
        return None
    decision = auth.authorize(scope, schemes=schemes, resolved_entities=entity_result["resolved"], sql=sql)
    if decision.allow:
        return None
    logger.info("auth deny on repaired SQL (%s) user=%s: %s", decision.check, scope.user_id, decision.reason)
    return decision




# ── One SQL attempt (D-032) ─────────────────────────────────────────────────
# The pieces of one attempt. The LangGraph execute_attempt -> repair nodes run
# them: rewrites, re-authorization of a repair, guards, verifier, execution.

_VR_PLACEHOLDER_VIEWS = frozenset({"v_employment", "v_expenditure", "v_focus_plus", "v_focus_legacy",
                                   "v_cm_elevate", "v_cm_elevate_disbursement"})


def _vr_excludes_placeholder_codes(sel: exp.Select) -> bool:
    """WHERE village_code > 0 / >= 1: the placeholder codes (-900001 …) are out."""
    for node in sql_ast.filter_conditions(sel, "village_code"):
        if isinstance(node, (exp.GT, exp.GTE)) and isinstance(node.expression, exp.Literal) \
                and not node.expression.is_string and float(node.expression.this) >= 0:
            return True
    return False


def _village_rows_by_code(sql: str) -> str:
    """One row per real village, named. A result grouped by village NAME gets
    village_code and lgd_block, one grouped by CODE gets lgd_village_name and
    lgd_block (GROUP BY and SELECT), and a village ranking leaves out the
    "Unresolved / Not Yet Mapped" placeholder codes (entity_type <> 'Unresolved';
    v_pmay has none). D-062 live check 2026-10-22: "top ten highest villages in
    PMAY-G" summed same-named villages of different blocks into one row (KI-376);
    "top 5 villages in Focus Plus" ranked village_code -900010, -900004, … (the
    unmapped buckets, 20,758 payments) and named no village. The c11 guard asks for
    the exclusion only when the NAME is grouped. The grouped column's own table
    qualifier is reused; without one, a join is left alone (whose column: not guessed)."""
    tree = sql_ast.parse_one(sql or "")
    sel = sql_ast.outer_select(tree) if tree is not None else None
    group = sel.args.get("group") if sel is not None else None
    if group is None or sel.args.get("distinct") is not None:
        return sql
    keys = [c for c in group.expressions if isinstance(c, exp.Column)
            and c.name.lower() in ("lgd_village_name", "village_code")]
    if not keys:
        return sql
    qual = keys[0].table
    tabs = sql_ast.tables(sel)
    if not qual and len(tabs) > 1:
        return sql
    out_names = {(e.alias_or_name or "").lower() for e in sel.expressions}
    added = []
    for col in ("lgd_village_name", "lgd_block", "village_code"):
        if sql_ast.groups_by(sel, col):
            continue
        group.append("expressions", exp.column(col, table=qual or None))
        if col not in out_names:
            sel.append("expressions", exp.column(col, table=qual or None))
        added.append(col)
    view = next(iter(tabs)) if len(tabs) == 1 else None
    if view in _VR_PLACEHOLDER_VIEWS and sel.args.get("order") is not None \
            and not _vr_mentions_unresolved(sql) and not _vr_excludes_placeholder_codes(sel):
        col = f"{qual}.entity_type" if qual else "entity_type"
        sel.where(f"{col} <> 'Unresolved'", copy=False)
        added.append("entity_type <> 'Unresolved'")
    if not added:
        return sql
    logger.info("village rows: one named row per real village (KI-376): +%s", added)
    return sql_ast.to_sql(tree)


def _unasked_having_threshold(question: str, sql: str) -> str:
    """A ranking whose HAVING compares an aggregate with a number the question never
    gave loses that HAVING. "Are there districts where Focus+ coverage is very low?"
    became HAVING COUNT(DISTINCT village_code) < 10: an invented cut-off no real
    district is under, so the answer was "no matching records" (UAT T13.3,
    cross-scheme re-test 2026-10-22). The ORDER BY / LIMIT keep the lowest first."""
    if any(ch.isdigit() for ch in question or "") or any(
            w.lower() in _LIST_COUNT_WORDS for w in _c01_tm_words(question or "")):
        return sql
    tree = sql_ast.parse_one(sql or "")
    sel = sql_ast.outer_select(tree) if tree is not None else None
    having = sel.args.get("having") if sel is not None else None
    if having is None or sel.args.get("order") is None:
        return sql
    cond = having.this
    if not isinstance(cond, (exp.LT, exp.LTE, exp.GT, exp.GTE)):
        return sql
    sides = (cond.this, cond.expression)
    if not (any(isinstance(x, exp.Literal) and x.is_number for x in sides)
            and any(x.find(exp.AggFunc) is not None for x in sides)):
        return sql
    sel.set("having", None)
    logger.info("ranking: unasked HAVING threshold dropped (T13.3): %s", cond.sql())
    return sql_ast.to_sql(tree)


async def _scheme_sql_rewrites(question: str, schemes: list[str], entity_result: dict,
                               sql: str) -> str:
    """The deterministic per-scheme SQL rewrites run before every attempt."""
    sql = _focus_legacy_geo_columns(schemes, sql)
    sql = _focus_legacy_village_code_only(schemes, entity_result.get("resolved") or {}, sql)
    sql = _focus_legacy_date_trunc_as_date(schemes, sql)
    sql = _focus_legacy_scheme_name_not_variant(question, schemes, sql)
    sql = _focus_legacy_unasked_year_coverage(question, schemes, sql)
    sql = _focus_legacy_place_not_group_name(schemes, entity_result, sql)
    sql = _uppercase_geo_literals(sql)
    sql = _focus_legacy_ac_name_case(schemes, sql)
    sql = _cm_legacy_ac_as_place_filter(schemes, entity_result, sql)
    sql = _cm_legacy_ac_name_case(schemes, sql)
    sql = _focusplus_drop_unrequested_verification_status(question, schemes, sql)
    sql = _cm_legacy_keep_unresolved_off_village(question, schemes, sql)
    sql = _cm_legacy_sanctioned_count(question, schemes, sql)
    sql = _cm_legacy_loan_received_filter(question, schemes, sql)
    sql = _select_unselected_group_by(question, sql)
    sql = _cm_legacy_unselected_group_by(schemes, sql)
    sql = _cm_legacy_unrequested_limit(question, schemes, sql)
    sql = _cm_legacy_crore_alias_on_rupees(schemes, sql)
    sql = _cm_legacy_order_by_records(question, schemes, sql)
    sql = await _cm_elevate_fix_literals(schemes, sql)
    sql = _cm_elevate_split_scheme_in_list(schemes, sql)
    sql = _cm_elevate_sector_all_programmes(question, schemes, sql)
    sql = _cm_elevate_unasked_programme_filter(question, schemes, sql)
    sql = _cm_elevate_applicants_distinct(question, schemes, sql)
    sql = _cm_elevate_compare_by_district(question, schemes, sql)
    # I-2: a top / bottom N asked per year is ranked inside each year, whatever the
    # model wrote (the prompt asks for it; this makes it certain)
    if prompt_builder._per_period_rank_note(question):
        sql = sql_ast.rank_within_period(sql) or sql
    _twins = entity_result.get("resolved") or {}
    if _twins.get("village_twins") and _twins.get("village_code_list"):
        sql = sql_ast.widen_village_filter(sql, _twins["village_code_list"])   # J-10
    sql = _resolved_district_list_literals(entity_result.get("resolved") or {}, sql)
    sql = _resolved_district_literal(entity_result.get("resolved") or {}, sql)
    sql = _stray_block_literal(schemes, entity_result.get("resolved") or {}, sql)
    sql = _cm_elevate_sector_zero_groups(schemes, sql)
    sql = _cm_elevate_level_pending(question, schemes, sql)
    sql = _cm_elevate_pending_without_level(question, schemes, sql)
    sql = _cm_elevate_pending_funnel(question, schemes, sql)   # pending rule 2026-10-30, gated
    sql = _cm_elevate_unasked_level_filter(question, schemes, sql)
    sql = _cm_elevate_drop_area_level_entity_type(schemes, sql)
    sql = _cm_elevate_sector_keep_unrecorded(question, schemes, sql)
    sql = await _cm_elevate_urban_body_spellings(question, schemes, sql)
    sql = _cm_elevate_status_is_file_status(question, schemes, sql)
    sql = _cm_elevate_decision_status_column(schemes, sql)
    sql = _cm_legacy_qualify_shared_geo_cols(schemes, sql)
    sql = _mgnrega_avg_of_ratio(schemes, sql)
    sql = _mgnrega_summary_ratio_columns(question, schemes, sql)   # RAG fix report Issue 3
    sql = _mgnrega_fact_to_view(schemes, sql)
    sql = _mgnrega_drop_area_level_entity_type(schemes, sql)
    sql = _mgnrega_village_rank_placeholders(question, schemes, sql)
    sql = _mgnrega_unit_count_not_villages(question, schemes, sql)
    sql = _mgnrega_job_cards_latest_year(schemes, sql, question=question,
                                         resolved=entity_result.get("resolved") or {})
    sql = _mgnrega_people_years_alias(schemes, sql)
    sql = _mgnrega_village_list_no_limit(question, schemes, sql)
    sql = _mgnrega_numeric_division(schemes, sql)
    sql = _mgnrega_lakh_not_divided(schemes, sql)
    sql = _mgnrega_pin_village_code(schemes, entity_result, sql)
    sql = _mgnrega_drop_geo_beside_village(schemes, entity_result, sql)
    sql = _focusplus_pin_village_where(schemes, entity_result, sql)
    sql = _focusplus_lgd_district_column(question, schemes, sql)      # KI-359 / KI-426
    sql = _focusplus_district_group_not_null(schemes, sql)
    sql = _unasked_having_threshold(question, sql)
    sql = await _focusplus_lgd_only_block(schemes, sql)
    sql = _mgnrega_women_years_only(schemes, sql)
    sql = _pmay_count_placeholders(schemes, sql)
    sql = _pmay_comparison_limit(schemes, entity_result, sql)
    sql = _stated_rank_count_limit(question, sql)
    sql = _c17_sql_hygiene(question, sql)       # runners-up LIMIT 3, no LIMIT on a one-row total (D3, D9)
    sql = _region_alias_not_the_column(sql)
    sql = _star_without_hidden_columns(sql)
    sql = _pmay_crore_to_rupees(schemes, sql)
    # a village the SQL dropped (all schemes; live 2026-10-02, NOAGRE)
    sql = _cm_unasked_programme_beside_village(question, schemes, entity_result, sql)
    sql = _focus_legacy_beneficiary_four_measures(question, schemes, sql)
    sql = _pin_missing_village_code(schemes, entity_result, sql)
    sql = _village_rows_by_code(sql)
    # E-5 (chat UI audit 2026-10-29): places with no figure never head a "top N"
    sql = sql_ast.nulls_last_on_desc(sql)
    return sql


# megh_readonly has column grants that leave out the PII columns (v_cm_elevate's
# scheme_specific, the plain member_id / account numbers — ingestion answers
# 2026-10-26), so `SELECT *` on such a table is refused ("permission denied") and
# cost a repair round. The star is replaced by the columns the role CAN read, from
# the live schema (schema_introspect.live_columns, which already leaves out what
# the role may not select). Only a single-table SELECT; anything else is left alone.
def _star_without_hidden_columns(sql: str) -> str:
    if not sql or "*" not in sql:
        return sql
    from app import schema_introspect as _si
    denied = {(s, t) for s, t, _c in (_si._cache.get("denied") or set())}
    if not denied:
        return sql
    live = _si.live_columns()

    def fn(tree):
        for sel in tree.find_all(exp.Select):
            stars = [e for e in sel.expressions
                     if isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))]
            frm = sel.args.get("from_") or sel.args.get("from")
            if not stars or frm is None or sel.args.get("joins") or not isinstance(frm.this, exp.Table):
                continue
            tbl = frm.this
            key = (tbl.db or "curated", tbl.name)
            cols = [c["column"] for c in live.get(f"{key[0]}.{key[1]}", [])]
            if key not in denied or not cols:
                continue
            sel.set("expressions", [e for e in sel.expressions if e not in stars]
                    + [exp.column(c) for c in cols])
            logger.info("SQL: SELECT * on %s.%s expanded to the %d columns megh_readonly can read",
                        key[0], key[1], len(cols))
        return None

    return sql_ast.transform(sql, fn)


# Every scheme view gained a `region` column (ingestion note 2026-10-26: Garo /
# Khasi / Jaintia, Ri Bhoi inside Khasi). A query that builds its OWN grouping
# `CASE … END AS region` and then says `GROUP BY region` now groups by the view's
# column — PostgreSQL resolves the name to the input column first — and fails
# ("lgd_district must appear in the GROUP BY clause"). The few-shot banks taught
# exactly that shape until 2026-10-26. The computed column is renamed region_group
# in the SELECT list and in GROUP BY / ORDER BY, so the query keeps its own grouping.
def _region_alias_not_the_column(sql: str) -> str:
    if not sql or "region" not in sql.lower():
        return sql

    def fn(tree):
        for sel in tree.find_all(exp.Select):
            computed = [a for a in sel.expressions if isinstance(a, exp.Alias)
                        and a.alias.lower() == "region"
                        and not (isinstance(a.this, exp.Column) and a.this.name.lower() == "region")]
            if not computed:
                continue
            for a in computed:
                a.set("alias", exp.to_identifier("region_group"))
            for clause in (sel.args.get("group"), sel.args.get("order")):
                if clause is None:
                    continue
                for col in list(clause.find_all(exp.Column)):
                    if col.name.lower() == "region" and not col.table:
                        col.replace(exp.column("region_group"))
            logger.info("SQL: computed 'region' renamed region_group (the views' own region column)")
        return None

    return sql_ast.transform(sql, fn)


# The count the officer stated is the list length (RAG plan C2, 2026-10-24). The
# count is in digits by now (_normalize_rank_counts: "five highest" -> "5 highest").
# A deterministic LIMIT, not a repair round: a repair can make correct SQL worse
# (RAG plan E8). Only where it is safe: exactly one stated count, a single ranked
# SELECT (ORDER BY), no window function (ties / per-group ranks are the model's),
# no UNION ("top 5 and bottom 5"), no OFFSET, no "in each district" (top N per group).
_C11_RANK_BEFORE = frozenset("top bottom first last".split())
_C11_PER_GROUP = frozenset("each every per".split())
_C11_GROUP_NOUNS = frozenset("district districts block blocks village villages panchayat panchayats gp gps "
                             "constituency constituencies scheme schemes year years".split())
# Two directions asked at once ("highest and lowest 3"). "top"/"bottom" only as a
# pair: "top 5 lowest districts" is ONE list of the 5 lowest.
_C11_HIGH = frozenset("highest largest biggest best most leading strongest".split())
_C11_LOW = frozenset("lowest smallest worst least poorest weakest".split())


def _requested_rank_count(question: str) -> "int | None":
    """The one list length the question states ("top 5", "5 highest", "which 3
    blocks"), or None when it states none, several, or a per-group ranking."""
    toks = _c01_tm_tokens(question or "")
    low = [t.low for t in toks]
    if (_C11_HIGH & set(low) and _C11_LOW & set(low)) or {"top", "bottom"} <= set(low):
        return None                                   # "top 5 and bottom 5"
    for k, w in enumerate(low):
        if w in _C11_PER_GROUP and any(x in _C11_GROUP_NOUNS for x in low[k + 1:k + 4]):
            return None                               # "top 5 in each district"
        if w == "wise" and k and low[k - 1] in _C11_GROUP_NOUNS:
            return None                               # "district-wise top 5"
    found: set[int] = set()
    text = question or ""
    for k, t in enumerate(toks):
        nxt = low[k + 1] if k + 1 < len(low) else ""
        glued = next((t.low[len(r):] for r in ("top", "bottom") if t.low.startswith(r)), "")
        if glued.isdecimal() and len(glued) <= 3:
            found.add(int(glued))                     # "top5", "bottom10"
            continue
        if not (t.raw.isdecimal() and len(t.raw) <= 3):
            continue
        if text[t.start - 1:t.start] in ("-", "/"):
            continue                                  # "2023-24 highest": a year, not a count
        prev = low[k - 1] if k else ""
        if (prev in _C11_RANK_BEFORE and nxt not in _C02_TIME_UNITS) or nxt in _C02_RANK_AFTER \
                or (prev in _C02_WHICH and nxt in _C02_PLACES):
            found.add(int(t.raw))
    found = {n for n in found if 1 <= n <= 100}
    return found.pop() if len(found) == 1 else None


def _stated_rank_count_limit(question: str, sql: str) -> str:
    n = _requested_rank_count(question)
    if not n or not sql:
        return sql
    trees = sql_ast.parse(sql)
    if len(trees) != 1:
        return sql
    tree = trees[0]
    if isinstance(tree, exp.SetOperation) or any(True for _ in tree.find_all(exp.SetOperation)) \
            or any(True for _ in tree.find_all(exp.Window)):
        return sql
    sel = sql_ast.outer_select(tree)
    holder = tree if tree.args.get("limit") is not None else sel
    if sel is None or holder is None or holder.args.get("offset") is not None:
        return sql
    if (tree.args.get("order") or sel.args.get("order")) is None:
        return sql
    cur = sql_ast.outer_limit(tree)
    if cur == n or (cur is not None and cur < 0):
        return sql
    logger.info("stated ranking count %d: outer LIMIT %s -> %d", n, cur, n)
    return sql_ast.set_limit(sql, n)


# A breakdown asked for ("in each block of …") grouped on a column that is not
# SELECTed: the rows are amounts with no labels ("SELECT COUNT(*), SUM(amount)
# … GROUP BY block_name_raw" — NL->SQL accuracy set, 2026-10-16). Any scheme:
# the grouping columns are added to the front of the SELECT list. (A grouping
# the question never asked for is a different case, handled per scheme by
# _cm_legacy_unselected_group_by, which drops it.)
def _select_unselected_group_by(question: str, sql: str) -> str:
    if not sql or not _c02_breakdowns(question or ""):
        return sql
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or not tree.args.get("group") \
            or any(True for _ in tree.find_all(exp.SetOperation)):
        return sql
    selected = {c.name.lower() for e in tree.expressions for c in e.find_all(exp.Column)} \
        | {e.alias.lower() for e in tree.expressions if isinstance(e, exp.Alias) and e.alias}
    missing = [g for g in tree.args["group"].expressions
               if isinstance(g, exp.Column) and g.name.lower() not in selected]
    if not missing:
        return sql
    tree.set("expressions", [g.copy() for g in missing] + list(tree.expressions))
    logger.info("selected the unselected GROUP BY column(s) %s for a breakdown question",
                [g.name for g in missing])
    return sql_ast.to_sql(tree)


# "Which <items> have MORE <measure> in <place A> THAN in <place B>?" — a
# comparison between two places that must be decided per row. With each place on
# its own row (GROUP BY lgd_district, scheme_name) nothing compares them, and the
# composer drew the opposite conclusion from the listed counts (accuracy set,
# 2026-10-16). The two places must be side by side: one FILTER column each.
_C11_MORE_THAN = Matcher(Seq(W("more", "fewer", "less", "higher", "lower", "greater", "bigger", "smaller",
                               "larger"), Gap(0, 8), "than"))
_C11_PLACE_COLUMNS = ("lgd_district", "lgd_block", "block_name_raw", "district_name_raw")


def _two_place_comparison_issue(question: str, sql: str) -> "str | None":
    """Two places filtered, a "more … than" question, and the places neither
    side by side (FILTER / CASE columns) nor the only grouping (one row per
    place, which the answer can compare): merged into one figure, or split
    across a second dimension so no row holds both."""
    if not _C11_MORE_THAN.search(question or ""):
        return None
    tree = sql_ast.parse_one(sql or "")
    if not isinstance(tree, exp.Select):
        return None
    group = tree.args.get("group")
    group_cols = {c.name.lower() for c in group.find_all(exp.Column)} if group is not None else set()
    for col in _C11_PLACE_COLUMNS:
        places = {v.upper() for v in sql_ast.filter_values(tree, col)}
        if len(places) != 2:
            continue
        if any(sql_ast.references_column(n, col) for n in (*tree.find_all(exp.Filter), *tree.find_all(exp.Case))):
            return None                                  # side by side already
        if group_cols == {col}:
            return None                                  # one row per place: comparable
        a, b = sorted(places)
        how = "on separate rows" if col in group_cols else "into one figure"
        return (f"the question compares two places, but this query puts '{a}' and '{b}' "
                f"{how}, so nothing compares them. Put the two side by side instead: "
                f"COUNT(...) FILTER (WHERE {col} = '{a}') AS one column and FILTER (WHERE {col} = '{b}') "
                f"AS another, GROUP BY only the other column(s) (not {col}), and keep the rows the "
                "question asks for with a HAVING that compares the two columns. Keep every other "
                "filter exactly as it was.")
    return None


# A correlated subquery on the SAME table as the outer query, with no alias:
#   FROM curated.v_cm_elevate … HAVING COUNT(…) > (SELECT COUNT(…) FROM
#   curated.v_cm_elevate WHERE … AND scheme_name = curated.v_cm_elevate.scheme_name)
# Postgres binds curated.v_cm_elevate.scheme_name to the SUBQUERY's own row, so
# the "correlation" compares each row with itself — a silent wrong answer (0 rows
# for an "A more than B" comparison, accuracy set 2026-10-16).
def _self_correlated_subquery_issue(sql: str) -> "str | None":
    tree = sql_ast.parse_one(sql or "")
    if not isinstance(tree, exp.Select):
        return None
    frm = tree.args.get("from_") or tree.args.get("from")      # the key is "from_" in SQLGlot 30
    outer = list(frm.find_all(exp.Table)) if frm is not None else []
    outer_bare = {t.name.lower() for t in outer if not t.alias}
    if not outer_bare:
        return None
    for sub in tree.find_all(exp.Subquery):
        inner = {t.name.lower() for t in sub.find_all(exp.Table)}
        for c in sub.find_all(exp.Column):
            tbl = (c.table or "").lower()
            if tbl and tbl in outer_bare and tbl in inner:
                return (f"the subquery compares {c.sql()} with itself: inside the subquery that name "
                        f"refers to the subquery's own {tbl}, not the outer query's row. Give the outer "
                        f"table an alias (FROM curated.{tbl} o) and use o.{c.name} in the subquery — or "
                        "compare the two groups side by side with COUNT(...) FILTER (WHERE ...) columns "
                        "and no subquery. Keep every other clause exactly as it was.")
    return None


# The question asks for a breakdown ("in each block", "block-wise", "per
# district", "by financial year" — c02's _c02_breakdowns) but the SQL is one
# aggregate row: no GROUP BY, no window. Two per-block questions in the held-out
# NL->SQL accuracy set came back as a single district total (2026-10-16).
_BREAKDOWN_CHECKED = {"district": "district", "block": "block", "village": "village", "year": "financial year"}


def _calendar_year_range_issue(question: str, entity_result: dict, sql: str) -> "str | None":
    """A FINANCIAL year was resolved (year_key) but the SQL filters a date column
    by a CALENDAR-year range instead ("sanction_date >= '2023-01-01' AND < '2024-01-01'")
    and never by year_key / financial_year. Live 2026-10-19 (conversation harness,
    A_forward_topic_switch): "How many in 2023-24?" for PMAY-G answered 110,890 houses
    (calendar 2023) for the 106,527 of FY 2023-24 — a wrong number that looked right.
    A question that itself names calendar months ("between January and March 2026")
    is left to the generator."""
    resolved = (entity_result or {}).get("resolved") or {}
    years = resolved.get("year_key_list") or ([resolved["year_key"]] if resolved.get("year_key") is not None else [])
    if not years or not sql:
        return None
    if _MONTH_YEAR_IN_Q.search(question or ""):
        return None
    if sql_ast.filtered_by(sql, "year_key", "financial_year_short", "financial_year", "fy"):
        return None
    date_cols = [c for c in sql_ast.columns(sql) if "date" in c.lower()]
    if not date_cols:
        return None
    bounds = [v for v in sql_ast.filter_values(sql, *date_cols) if isinstance(v, str)]
    calendar = [v for v in bounds if len(v) >= 10 and v[4] == "-" and v[5:10] in ("01-01", "12-31")]
    if not calendar:
        return None
    try:
        y = int(years[0])
    except (TypeError, ValueError):
        return None
    fy = f"FY {y}-{(y + 1) % 100:02d}"
    key = f"year_key = {y}" if len(years) == 1 else "year_key IN (" + ", ".join(str(int(v)) for v in years) + ")"
    return (f"the question asks for the financial year {fy} ({key}), but the query filters {date_cols[0]} by a "
            f"calendar-year date range ({', '.join(calendar[:2])}). Replace that date range with {key} "
            "(a financial year is stored by its START year) and keep every other clause exactly as it was.")


def _breakdown_missing_issue(question: str, sql: str) -> "str | None":
    dims = sorted(_c02_breakdowns(question or "", include_per=False) & set(_BREAKDOWN_CHECKED))
    if not dims or not sql:
        return None
    tree = sql_ast.parse_one(sql)
    if tree is None or sql_ast.has_group_by(tree) or not sql_ast.has_aggregate(tree) \
            or any(True for _ in tree.find_all(exp.Window)):
        return None
    wanted = " and ".join(_BREAKDOWN_CHECKED[d] for d in dims)
    return (f"the question asks for a breakdown by {wanted}, but the query returns one total row. "
            f"Return one row per {wanted}: put the {wanted} column in the SELECT list and GROUP BY it. "
            "Keep every filter exactly as it was.")


async def _c11_true_row_count(sql: str) -> "int | None":
    """How many rows `sql` returns without the row cap (E-3). None when it can't tell."""
    try:
        body = sql_ast.without_limit(sql.strip().rstrip(';'))
        got = await run_readonly(f"SELECT COUNT(*) AS total_rows FROM ({body}) AS capped_result")
        return int(got[0]["total_rows"]) if got else None
    except Exception as e:  # noqa: BLE001 — a count must never fail the answer
        logger.info("true row count failed (non-fatal): %s", e)
        return None


async def _execute_one_attempt(question: str, schemes: list[str], entity_result: dict,
                               sql: str) -> list[dict]:
    """The SQL shape guards, the semantic verifier, execution and the post-execution
    check. Returns the rows; raises (ValueError / UnsafeSQLError / DB errors) for
    the caller to repair or give up on."""
    _label_issue = _sql_measure_label_issue(schemes, sql)
    if _label_issue:
        context_budget.log_decision("sql_guard", guard="measure_label", verdict="reject")
        raise ValueError(_label_issue)
    _dim_issue = _sql_dimension_only_issue(schemes, sql)
    if _dim_issue:
        context_budget.log_decision("sql_guard", guard="dimension_only", verdict="reject")
        raise ValueError(_dim_issue)
    _bd_issue = _breakdown_missing_issue(question, sql)
    if _bd_issue:
        context_budget.log_decision("sql_guard", guard="breakdown_missing", verdict="reject")
        raise ValueError(_bd_issue)
    _two_place = _two_place_comparison_issue(question, sql)
    if _two_place:
        context_budget.log_decision("sql_guard", guard="two_place_comparison", verdict="reject")
        raise ValueError(_two_place)
    _self_corr = _self_correlated_subquery_issue(sql)
    if _self_corr:
        context_budget.log_decision("sql_guard", guard="self_correlated_subquery", verdict="reject")
        raise ValueError(_self_corr)
    _pm_issue = _pmay_sql_issue(question, schemes, sql)
    if _pm_issue:
        raise ValueError(_pm_issue)
    # a constant posing as the answer, another scheme's view, an unordered "which … most"
    # (data-accuracy brief 2026-10-29, D10's 'PMAY' AS scheme_with_most_records)
    _invented = _c17_sql_issue(question, schemes, sql)
    if _invented:
        context_budget.log_decision("sql_guard", guard="invented_or_off_scope", verdict="reject")
        raise ValueError(_invented)
    _vlist = _mgnrega_village_list_issue(question, schemes, sql) \
        or _mgnrega_village_count_issue(question, schemes, sql)            # KI-436
    if _vlist:
        raise ValueError(_vlist)
    _vmiss = _village_filter_missing(schemes, entity_result, sql)
    if _vmiss is not None:
        raise ValueError(
            f"the question resolved to ONE village, village_code = {_vmiss}, but this query "
            "does not filter on it, so it returns a block / district / statewide total and "
            "reports it as the village's figure. Add WHERE village_code = "
            f"{_vmiss} (the curated views carry village_code directly), drop any "
            "lgd_block / lgd_district filter, and keep the metric, year_key and "
            "aggregation exactly as they were.")
    _vcount = _village_count_for_one_village(question, entity_result, sql)
    if _vcount is not None:
        raise ValueError(
            f"the question asks about ONE village (village_code = {_vcount}), but this query "
            "counts villages (COUNT(DISTINCT village_code)), so it can only return 0 or 1 and "
            "reports that as the village's figure. Read the measure the question asks for "
            "(e.g. SUM(households_employed) for households that got work, "
            "SUM(persons_employed) for persons) WHERE village_code = "
            f"{_vcount}, keeping any year filter.")
    # The semantic contract: what the question and resolver pinned
    # must be in the SQL (KI-034; stated amount 2026-09-29).
    _amt_issue = _focusplus_stated_amount_missing(question, schemes, sql)
    if _amt_issue:
        context_budget.log_decision("sql_guard", guard="stated_amount", verdict="reject")
        raise ValueError(_amt_issue)
    _cal_issue = _calendar_year_range_issue(question, entity_result, sql)
    if _cal_issue:
        logger.warning("SQL filters a calendar-year date range for a financial-year question — repairing: %s", _cal_issue)
        raise ValueError(_cal_issue)
    _scope_issue = _resolved_scope_missing(question, schemes, entity_result, sql)
    if _scope_issue:
        context_budget.log_decision("sql_guard", guard="resolved_scope", verdict="reject",
                                    missing=_scope_issue[0])
        raise ValueError(_scope_issue[1])
    _fl_ac_issue = _focus_legacy_ac_filter_missing(schemes, entity_result, sql)
    if _fl_ac_issue:
        context_budget.log_decision("sql_guard", guard="fl_ac_filter_missing", verdict="reject")
        raise ValueError(_fl_ac_issue)
    _cml_ac_issue = _cm_legacy_ac_filter_missing(schemes, entity_result, sql)
    if _cml_ac_issue:
        context_budget.log_decision("sql_guard", guard="cml_ac_filter_missing", verdict="reject")
        raise ValueError(_cml_ac_issue)
    _fl_members_issue = _focus_legacy_members_counted_as_groups(question, schemes, sql)
    if _fl_members_issue:
        context_budget.log_decision("sql_guard", guard="fl_members_as_groups", verdict="reject")
        raise ValueError(_fl_members_issue)
    if _focus_legacy_group_size_summed(question, schemes, sql):
        raise ValueError(
            "this question asks for a producer group's SIZE (its member count), but the "
            "query SUMs no_of_pg_members across the group's payments. A group's member "
            "count is recorded on EACH payment and 2,655 groups were paid more than once, "
            "so a SUM double-counts them (a 20-member group paid twice reads 40). Use "
            "MAX(no_of_pg_members) AS group_size per pg_id — GROUP BY pg_id with "
            "MAX(pg_name) for display, and put any 'more than N members' test in HAVING "
            "MAX(no_of_pg_members) > N. Keep every other clause as it was."
        )
    _fl_four = _focus_legacy_beneficiary_measures_missing(question, schemes, sql)
    if _fl_four:
        raise ValueError(_fl_four)
    _two_scopes = _cme_programme_or_all_scopes_missing(question, schemes, sql)
    if _two_scopes:
        raise ValueError(_two_scopes)
    bad_code = _village_name_filter_instead_of_code(entity_result, sql)
    if bad_code is not None:
        raise ValueError(
            f"the question resolved to village_code = {bad_code} but this query filters on "
            "lgd_village_name instead — village name spelling/case is not reliable for "
            "matching (storage keeps mixed/title case, not upper-case), so that filter can "
            "silently match zero rows. Replace the lgd_village_name filter with "
            f"village_code = {bad_code} exactly, and keep every other clause as it was."
        )
    wrong_level = _village_filtered_at_wrong_level(entity_result, sql)
    if wrong_level is not None:
        _code, _clause = wrong_level
        if _vr_filters_village_code(sql):
            # village_code is already correct — the bogus clause just
            # has to go, not be replaced.
            raise ValueError(
                f"this query already filters village_code = {_code} correctly, but it "
                f"ALSO filters {_clause} — a VILLAGE name placed in a block/district "
                "column, which matches no row and forces the whole query to 0 even "
                f"though village {_code} has real records. DELETE that clause entirely "
                "and keep village_code and every other filter exactly as they are."
            )
        raise ValueError(
            f"the question resolved to village_code = {_code}, but this query filters "
            f"{_clause} — that is a VILLAGE name placed in a block/district column, so "
            "it matches zero rows and returns a confident 0 for a village that has "
            f"real records. Replace that clause with village_code = {_code} exactly "
            "(the curated view carries village_code as a direct column), and keep "
            "every other clause as it was."
        )
    bad_geo_code = _village_code_as_geography_key(entity_result, sql)
    if bad_geo_code is not None:
        raise ValueError(
            f"the question resolved to village_code = {bad_geo_code} but this query filters "
            f"geography_key = {bad_geo_code} instead — geography_key is a different surrogate "
            "key, unrelated in value to village_code, so this filter matches no row and "
            "silently returns NULL/zero instead of the real figure. Replace "
            f"geography_key = {bad_geo_code} with village_code = {bad_geo_code} exactly (the "
            "curated view carries village_code as a direct column), and keep every other "
            "clause as it was."
        )
    if _crore_conversion_for_single_village(entity_result, sql):
        raise ValueError(
            "this query converts a MGNREGA money column to CRORE (dividing by 100) for a "
            "question scoped to a single village — MGNREGA money is natively LAKH RUPEES, "
            "and a single village's figure is routinely well under 1 crore, so rounding it "
            "to crore at 2 decimal places can display a real, non-zero amount as a "
            "misleading '0.00 crore'. Report the figure directly in LAKH instead (remove "
            "the ÷100 conversion and the crore alias/label), and keep every other clause "
            "as it was."
        )
    if _mgnrega_facts_joined(sql):
        raise ValueError(
            "this query JOINs curated.v_employment to curated.v_expenditure "
            "directly. MGNREGA's two facts have no shared grain — both hold many "
            "rows per village-year — so that join fans out and every SUM comes back "
            "multiplied (a real 986,020 person-days became 109,448,220). Rebuild it "
            "with one CTE per fact, each aggregated on its own and carrying the SAME "
            "filters, then combine the aggregates:\n"
            "  WITH emp AS (SELECT SUM(person_days) AS person_days "
            "FROM curated.v_employment WHERE <filters>),\n"
            "       exp AS (SELECT SUM(total_exp) AS total_exp_lakh "
            "FROM curated.v_expenditure WHERE <filters>)\n"
            "  SELECT exp.total_exp_lakh, emp.person_days FROM emp, exp\n"
            "Add GROUP BY inside each CTE and FULL OUTER JOIN them on the grain "
            "columns only if a per-area or per-year breakdown was asked for. Keep "
            "every filter exactly as it was."
        )
    _fanout = _prohibited_row_join(sql)
    if _fanout is not None:
        context_budget.log_decision("sql_guard", guard="prohibited_row_join", verdict="reject",
                                    pair=f"{_fanout[0]} x {_fanout[1]}")
        raise ValueError(
            f"this query row-joins {_fanout[0]} to {_fanout[1]}. semantic.v_join_rules says "
            "these two must NEVER be row-joined: each holds one row per source record of a "
            "different fact, so the join multiplies rows and every SUM / COUNT comes back "
            "inflated (v_employment x v_expenditure on year + district turned 14.7 million "
            "person-days into 6.69 billion). Aggregate EACH side to the shared grain "
            "(e.g. year_key, lgd_district) in its own CTE or subquery with the same filters, "
            "then join the aggregates on those grain columns only. Keep every filter as it was.")
    _denied = _readonly_denied_column_in(sql)
    if _denied is not None:
        context_budget.log_decision("sql_guard", guard="readonly_denied_column", verdict="reject",
                                    column=f"{_denied[0]}.{_denied[1]}")
        raise ValueError(
            f"this query reads {_denied[0]}.{_denied[1]}, a column the chatbot's database "
            "role is not allowed to read, so the database refuses the query. Do not use "
            f"{_denied[1]} at all. Use the plain columns of the view (for CM Elevate the "
            "sector is the sector_id column). Keep every other clause as it was.")
    bad_geo = _ac_with_invented_geo_filter(entity_result, sql)
    if bad_geo is not None:
        raise ValueError(
            f"this query filters on the assembly constituency AND on {bad_geo}, but "
            "no district or block was resolved for this question — that geography "
            "filter was invented. An assembly constituency cuts ACROSS blocks and "
            "districts, so its name is usually not a block or district name, and "
            f"ANDing {bad_geo} with the constituency filter matches zero rows and "
            "returns a false zero. Remove that filter entirely and keep only "
            "assembly_constituency_name (plus year_key and the aggregation) exactly "
            "as they were."
        )
    if _vr_state_pseudo_filter(sql):
        raise ValueError(
            "generated SQL filters on a non-existent 'Meghalaya' / entity_type='State' "
            "pseudo-row — the whole dataset is already Meghalaya; remove that geographic "
            "filter entirely and keep every other clause"
        )
    # job_cards_issued_total is a STOCK (cards held), so it is never added across
    # years: "total job cards issued in all financial years" was answered 2,128,714
    # (four years' stock summed) instead of the 520,999 held (user session 2026-10-13).
    if _vr_sums_column(sql, "job_cards_issued_total") \
            and not _vr_filters_col(sql, ["year_key"], _VR_EQ + _VR_IN) \
            and not any(c == "year_key" or c.startswith("financial_year")
                        for c in sql_ast.group_by_columns(sql)):
        # The year is the one asked: an all-years question gets one row per year,
        # never the latest year in its place (MGNREGA sheet DATA-007, 2026-10-21).
        raise ValueError(
            "job_cards_issued_total is a STOCK (job cards held at year end), so it must never "
            "be summed across financial years. " + (
                "The question asks for every financial year: add year_key to SELECT and GROUP BY "
                "(and ORDER BY year_key) so each year is reported on its own row"
                if _ALL_YEARS_CUE.search(question or "") else
                "Filter the financial year the question asks for (year_key = its start year); only "
                "when it names no year use year_key = (SELECT MAX(year_key) FROM curated.v_employment)")
            + ", and keep every other clause exactly as it was.")
    # "…across all financial years" is ONE combined figure. Split by year, the
    # composer added the rounded parts (₹1.85 + ₹0.39 = "₹2.24 crore" for
    # ₹2.2458) or listed the years with no total (matrix run 2026-10-14); the user
    # asked "I don't want year wise, I want complete all financial years"
    # (session 2026-10-13). A split nobody asked for is sent back.
    # Job cards are the exception: a running total has no combined figure, so
    # their all-years answer IS one row per year (see the stock guard above).
    if _vr_grouped_by_year_only(sql or "") and _ALL_YEARS_CUE.search(question or "") \
            and not _YEAR_SPLIT_ASKED.search(question or "") \
            and not _vr_sums_column(sql, "job_cards_issued_total"):
        raise ValueError(
            "the question asks for ONE combined figure across all financial years, but the query "
            "splits it by financial year. Remove the financial-year column from SELECT, GROUP BY "
            "and ORDER BY so every year (and any record with no year) is summed into a single "
            "total; keep every other clause exactly as it was.")
    # An MGNREGA expenditure COMPONENT named in the question must be the column
    # read: "unskilled wage expenditure in Bowabari village" was answered from
    # total_exp (124.34 lakh for 88.71) (hierarchy matrix run 2026-10-14).
    if "MGNREGA" in (schemes or []):
        for _cue, _col in _MGNREGA_EXP_COMPONENTS:
            if _cue.search(question or "") and not sql_ast.references_column(sql or "", _col):
                raise ValueError(
                    f"the question asks for {_col.replace('_', ' ')}, but the query does not read "
                    f"curated.v_expenditure.{_col} — use SUM({_col}) (lakh) for that figure instead of "
                    "total_exp or another column, and keep every other clause exactly as it was.")
            # …and as an AMOUNT, not a share of the total ("unskilled wage share
            # 59.44%" for "unskilled wage expenditure in Mawdet village", matrix run).
            if _cue.search(question or "") and not _SHARE_ASKED.search(question or "") \
                    and _vr_returns_share(sql or "", _col):
                raise ValueError(
                    f"the question asks for the {_col.replace('_', ' ')} AMOUNT, but the query returns a share "
                    f"(a division). Return SUM({_col}) in lakh, with no division, and keep every other clause "
                    "exactly as it was.")
    # A village ranking must not rank the "Unresolved / Not Yet Mapped" bucket as
    # if it were a village (user session 2026-10-13: it came 3rd of the top 5).
    # curated.v_pmay has no entity_type: its placeholder rows are is_placeholder
    # (schema rule 1, NOT is_placeholder). Demanding entity_type there sent a PMAY
    # village ranking round the repair loop ("column entity_type does not exist",
    # then the same demand) until it gave up (NL->SQL accuracy set, 2026-10-16).
    # Since D-060 (2026-10-22) PMAY-G's zero-sanction registrations are beneficiaries
    # in real villages (72 LGD codes; v_pmay holds no "Unresolved" bucket), so a PMAY
    # village ranking is not asked to drop them.
    if sql_ast.groups_by(sql, "lgd_village_name") \
            and _vr_has_order_by(sql) \
            and not _vr_mentions_unresolved(sql) \
            and not sql_ast.reads_table(sql, "v_pmay") \
            and _C11_RANKING_ASK.search(question or ""):
        raise ValueError(
            "this ranks villages but does not exclude the placeholder rows: add "
            "entity_type <> 'Unresolved' (or lgd_village_name NOT ILIKE 'Unresolved%')"
            " to the WHERE clause, and keep every other clause exactly as it was.")
    bad_view = _rowgrain_no_aggregate(question, sql)
    if bad_view:
        raise ValueError(
            f"this is an aggregate question but the query reads raw rows from {bad_view}, "
            "which is at source-row grain (many rows per village) — a bare "
            "SELECT <metric> ... LIMIT 1 returns ONE arbitrary row, not a total. Wrap the "
            "metric in SUM(...): for a statewide total use "
            "SELECT SUM(<metric>) AS <name> FROM <view> [WHERE year_key = ...] with no "
            "GROUP BY; add GROUP BY <unit> only if the question asks for a per-district / "
            "per-block / per-year breakdown. job_cards_issued_total is a STOCK — pin the "
            "year_key the question asks for (one row per year_key when it asks for every "
            "year; the latest only if it names none) and SUM across geographies, "
            "never across years. Keep every other clause exactly as it was."
        )
    # Execution checks first, then the model (2026-10-15): the free guards
    # above, then the database itself — a query that errors goes to repair
    # with the real Postgres error — then the result checks below. Only a
    # query that has cleared all of them reaches the paid 30B verifier.
    # The database's own plan check (semantic.check_query, DB team 2026-10-27)
    # sees row joins through views and CTEs that the v_join_rules guard reads
    # only from the SQL text. Fail-open: None when it can't run.
    row_join = await db_precheck_readonly(sql)
    if row_join:
        raise ValueError(
            f"the database's plan check found two fact tables joined row by row ({row_join[:200]}), "
            "which multiplies the figures. Aggregate each fact table to a shared grain "
            "(district / block / year) in its own CTE first, then join the aggregates. "
            "Keep every filter exactly as it was.")
    # J-10 (chat UI audit live run 2026-10-29): with three villages named Apalgre the
    # model filtered one code (and LIMIT 1) although the prompt listed all three
    _codes = [str(c) for c in (entity_result.get("resolved") or {}).get("village_code_list") or []]
    _missing = [c for c in _codes if c not in sql]
    if _codes and _missing and (entity_result.get("resolved") or {}).get("village_twins"):
        raise ValueError(
            f"the question covers {len(_codes)} villages that share one name (village_code IN "
            f"({', '.join(_codes)})), but the query leaves out {', '.join(_missing)}. Filter on ALL of them "
            "with IN, GROUP BY village_code and SELECT the block, with no LIMIT. Keep every other filter.")
    rows = await run_readonly(sql)
    # E-3 (chat UI audit 2026-10-29): a result stopped at the row cap said "1,000
    # results" with no hint that more exist; the true total is counted once
    entity_result["true_row_count"] = (await _c11_true_row_count(sql)
                                       if len(rows) >= settings.SQL_MAX_RESULT_ROWS else None)
    if _mgnrega_comparison_without_figures(question, schemes, rows):
        raise ValueError(
            "this question compares amounts, but the query returns only a label and "
            "no figures, so the answer cannot state what was compared. Return each "
            "compared quantity as its own numeric column (for wages vs materials: "
            "SUM(unskilled_wage_exp + semi_skilled_wage_exp) AS wage_exp_lakh and "
            "SUM(material_exp) AS material_exp_lakh), no CASE label. Keep every "
            "filter exactly as it was."
        )
    # The runners-up LIMIT 3 of a "which … most" (_c17_widen_top1) is ours, not the
    # model's: the 4B verifier read it as "a list, not the one asked for" and rejected
    # every repair (P3, 2026-10-29). It judges the query as the question asked it.
    verify_issue = await _verify_sql(question, schemes, entity_result, _c17_as_asked(question, sql))
    # The latest-year pin on job cards (a stock) is deliberate, even for "all
    # financial years": the verifier rejected it on every repair round and the
    # question ended in "couldn't build a working query" (matrix run 2026-10-14).
    if verify_issue and _vr_has_job_card_pin(sql) and _C11_YEAR_WORD.search(verify_issue):
        logger.info("verifier complaint about the job-card latest-year pin discarded: %s", verify_issue[:160])
        verify_issue = None
    # A measure computed exactly as a business definition prescribes (D-048: men =
    # persons - women; household_years / person_years) — the verifier rejected the
    # men query on every attempt (live 2026-10-16, errors.md case 1).
    if verify_issue and _mgnrega_definition_complaint_is_false(schemes, sql, verify_issue):
        logger.info("verifier complaint about a D-048 defined measure discarded: %s", verify_issue[:160])
        verify_issue = None
    if verify_issue:
        turn_trace.note_verifier_rejection()
        raise ValueError(
            f"semantic verifier flagged this query: {verify_issue}. Fix the SQL to "
            "address that specific problem and keep every other clause (filters, "
            "year_key, geography, aggregation) that is not implicated."
        )
    return await _c11_zero_ties(question, sql, rows, entity_result)


async def _c11_tie_note(sql: str, rows: list, measure: str, places: str, entity_result: dict) -> None:
    """E-9: when more places share the last place's figure than the list shows,
    say so (entity_result["tie_note"]). A zero is left to the zero-tie note."""
    last = rows[-1].get(measure)
    if last is None or last == 0:
        return
    q = sql_ast.tie_count_query(sql, measure, last)
    if q is None or len(rows) != q[0]:
        return
    try:
        got = await run_readonly(q[1])
        tied = int(got[0]["tied"]) if got else 0
    except Exception as e:  # noqa: BLE001
        logger.info("tie count failed (non-fatal): %s", e)
        return
    shown = sum(1 for r in rows if r.get(measure) == last)
    if tied > shown:
        entity_result["tie_note"] = (f"{tied} {places} tie for place {len(rows) - shown + 1} with "
                                     f"{last:,} {measure.replace('_', ' ')}; {shown} of them "
                                     f"{'is' if shown == 1 else 'are'} shown.")


async def _c11_zero_ties(question: str, sql: str, rows: list, entity_result: dict) -> list:
    """I-10 / J-7: a low-end ranking whose rows reach 0 lists the lowest places
    that HAVE a figure, and says how many have none (entity_result["zero_note"]).
    Rows unchanged when it does not apply or anything fails."""
    entity_result["zero_note"] = None
    entity_result["tie_note"] = None
    import numbers
    from app import cross_figures, measure_kinds
    ra = cross_figures.rank_ask(question)
    if ra is None or not rows:
        return rows
    nums = [k for k, v in rows[0].items()
            if isinstance(v, numbers.Number) and not isinstance(v, bool) and not measure_kinds.is_label_col(k)]
    if not nums:
        return rows
    measure = nums[-1]
    places = f"{ra.level}s" if ra.level else "places"
    await _c11_tie_note(sql, rows, measure, places, entity_result)
    if not ra.low or ra.high or not any((r.get(measure) or 0) == 0 for r in rows):
        return rows
    q = sql_ast.low_end_queries(sql, measure)
    if q is None:
        return rows
    try:
        zero = await run_readonly(q[0])
        lowest = await run_readonly(q[1])
        n_zero = int(zero[0]["zero_places"]) if zero else 0
    except Exception as e:  # noqa: BLE001
        logger.info("low-end zero-tie check failed (non-fatal): %s", e)
        return rows
    what = measure.replace("_", " ")
    if not lowest:
        entity_result["zero_note"] = f"All {n_zero:,} {places} have no {what}."
        return rows
    entity_result["zero_note"] = (f"{n_zero:,} {places} have no {what} (0), so they are not ranked; "
                                  f"the lowest {len(lowest)} with a figure are listed.")
    return lowest


async def _repair_sql(question: str, schemes: list[str], entity_result: dict,
                      failed_sql: str, error: str) -> str:
    """One repair call: the failed SQL and its error back to the SQL model."""
    # KI-013: the worst case (3 repairs, each with a verifier call) ran past the 60 s
    # request ceiling and the officer got a 504. Past the repair budget the turn stops
    # repairing and ends like a spent repair budget ("couldn't build a working query").
    spent = turn_trace.elapsed()
    if spent is not None and spent > settings.REPAIR_TIME_BUDGET_SECONDS:
        logger.warning("repair skipped: %.1f s used of the %d s repair budget (KI-013)",
                       spent, settings.REPAIR_TIME_BUDGET_SECONDS)
        raise ValueError(f"repair time budget spent ({spent:.0f} s): {error}")
    turn_trace.note_repair(error)          # the audit row lists every error that was repaired
    sql = failed_sql
    # The repair prompt carries the same schema + resolved-entities context as
    # the first attempt (not a schema-only stub) — a repair usually fails for
    # want of exactly that context — plus a targeted hint when the error names
    # a missing column.
    repair_prompt = prompt_builder.build_repair_prompt(
        context_policy.expand_short_fy(question), schemes, entity_result, failed_sql=sql, error=error,
        extra_hint=_repair_hint(error))
    raw = await llm.call_sql_generator(repair_prompt)
    sql = _extract_sql(raw)
    # KI-003: no convergence check — a repair that returns the query that just failed
    # spends the next attempt on the identical failure. Asked once more, saying so.
    if _c11_same_sql(sql, failed_sql):
        logger.info("repair returned the failed query unchanged — asking once more")
        turn_trace.note_repair("repair returned the same query")
        raw = await llm.call_sql_generator(
            repair_prompt + "\n\nYour previous answer returned EXACTLY the failed query above. It fails "
            "for the reason given; return a CHANGED query that fixes it. SQL:")
        sql = _extract_sql(raw)
    return sql


def _c11_same_sql(a: str, b: str) -> bool:
    """The two queries are the same once parsed (formatting and case of keywords
    aside); unparseable text is compared with whitespace collapsed."""
    if not a or not b:
        return False
    ta, tb = sql_ast.parse(a), sql_ast.parse(b)
    if ta and tb:
        return [sql_ast.to_sql(t) for t in ta] == [sql_ast.to_sql(t) for t in tb]
    return " ".join(a.split()) == " ".join(b.split())

"""
SQL inspection and rewriting on the syntax tree (SQLGlot, Postgres dialect).

The project rule: code that reads, checks or changes SQL works on the parsed
tree, never on the raw text. A plain text search reads a word
inside a string literal or a comment as a column, misses `UPPER(lgd_district)`,
and sees only the first value of an IN list. The tree has none of those blind
spots. app/sql_guard.py is the safety check; this module is everything else
that looks at a query: authorization, the pipeline's guards and rewrites.

Parsing is cached per text (the same query is inspected by many guards in one
turn). A query SQLGlot cannot parse yields no tree: inspectors then answer
"not found" and transformers return the text unchanged. Execution goes through
sql_guard, which refuses an unparseable query outright, so nothing unparsed runs.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable, Iterable

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.tokens import TokenType

DIALECT = "postgres"

# Wrappers that leave a column's identity unchanged for filtering purposes:
# UPPER(lgd_district) = 'X' filters lgd_district as surely as lgd_district = 'X'.
_TRANSPARENT = tuple(cls for cls in (getattr(exp, n, None) for n in (
    "Upper", "Lower", "Trim", "Cast", "TryCast", "Initcap", "Paren", "Coalesce", "Collate",
)) if isinstance(cls, type))


# ── parsing ─────────────────────────────────────────────────────────────────

@lru_cache(maxsize=2048)
def _parse_cached(sql: str) -> tuple[exp.Expression, ...]:
    try:
        trees = sqlglot.parse(sql, read=DIALECT)
    except (SqlglotError, ValueError, RecursionError):
        return ()
    return tuple(t for t in trees if t is not None and not isinstance(t, exp.Semicolon))


def parse(sql: str | None) -> list[exp.Expression]:
    """Every statement in `sql` as a tree (cross-scheme answers join several
    with ';'). Copies, so a caller may modify them. [] when unparseable."""
    if not sql or not sql.strip():
        return []
    return [t.copy() for t in _parse_cached(sql)]


def parse_one(sql: str | None) -> exp.Expression | None:
    """The single statement in `sql`, or None (empty, unparseable, or several)."""
    trees = parse(sql)
    return trees[0] if len(trees) == 1 else None


def is_parseable(sql: str | None) -> bool:
    return bool(sql and _parse_cached(sql))


def to_sql(tree: exp.Expression) -> str:
    return tree.sql(dialect=DIALECT)


def _trees(sql_or_tree) -> list[exp.Expression]:
    if isinstance(sql_or_tree, exp.Expression):
        return [sql_or_tree]
    if isinstance(sql_or_tree, (list, tuple)):
        return list(sql_or_tree)
    return [t for t in _parse_cached(sql_or_tree)] if sql_or_tree else []


def transform(sql: str, fn: Callable[[exp.Expression], exp.Expression | None]) -> str:
    """Parse `sql`, apply `fn` to each statement's tree (it may modify the tree
    in place and return None, or return a new tree) and regenerate the text.
    Unparseable text is returned unchanged. If `fn` changes nothing, the
    original text is returned byte for byte (no reformatting churn)."""
    trees = parse(sql)
    if not trees:
        return sql
    before = [to_sql(t) for t in trees]
    out = []
    for t in trees:
        r = fn(t)
        out.append(r if isinstance(r, exp.Expression) else t)
    after = [to_sql(t) for t in out]
    if after == before:
        return sql
    return ";\n".join(after)


# ── names and structure ─────────────────────────────────────────────────────

def _lc(s) -> str:
    return str(s or "").lower()


def columns(sql_or_tree) -> set[str]:
    """Lower-cased names of every column referenced anywhere (string literals
    and comments are not columns)."""
    return {_lc(c.name) for t in _trees(sql_or_tree) for c in t.find_all(exp.Column) if c.name}


def references_column(sql_or_tree, *names: str) -> bool:
    wanted = {_lc(n) for n in names}
    return bool(columns(sql_or_tree) & wanted)


def output_names(sql_or_tree) -> list[str]:
    """The outer SELECT's output column names / aliases, lower-cased."""
    out = []
    for t in _trees(sql_or_tree):
        sel = t if isinstance(t, exp.Select) else t.find(exp.Select)
        if sel is not None:
            out.extend(_lc(e.alias_or_name) for e in sel.expressions)
    return out


def tables(sql_or_tree, *, qualified: bool = False) -> set[str]:
    """Lower-cased table names read (CTE names excluded). qualified=True gives
    'schema.table' when the schema is written."""
    out = set()
    for t in _trees(sql_or_tree):
        ctes = {_lc(c.alias_or_name) for c in t.find_all(exp.CTE)}
        for tb in t.find_all(exp.Table):
            name = _lc(tb.name)
            if not name or (not tb.db and name in ctes):
                continue
            out.add(f"{_lc(tb.db)}.{name}" if qualified and tb.db else name)
    return out


def reads_table(sql_or_tree, *names: str) -> bool:
    """True if any of `names` is read. A name is matched on its table part
    ('curated.v_pmay' and 'v_pmay' both match a query reading curated.v_pmay or
    an unqualified v_pmay, which the search_path resolves to curated)."""
    bare = tables(sql_or_tree)
    return any(_lc(n).split(".")[-1] in bare for n in names)


def cte_names(sql_or_tree) -> set[str]:
    return {_lc(c.alias_or_name) for t in _trees(sql_or_tree) for c in t.find_all(exp.CTE)}


def has_cte(sql_or_tree) -> bool:
    return bool(cte_names(sql_or_tree))


def selects(sql_or_tree) -> list[exp.Select]:
    """Every SELECT node (outer, CTE bodies, subqueries)."""
    return [s for t in _trees(sql_or_tree) for s in t.find_all(exp.Select)]


def outer_select(tree: exp.Expression) -> exp.Select | None:
    if isinstance(tree, exp.Select):
        return tree
    node = tree
    while isinstance(node, (exp.Subquery, exp.Paren)):
        node = node.this
    if isinstance(node, exp.Select):
        return node
    if isinstance(node, exp.SetOperation):
        return outer_select(node.left)
    return None


def group_by_columns(sql_or_tree) -> set[str]:
    """Column names in any GROUP BY of the query (outer, CTE or subquery)."""
    out = set()
    for t in _trees(sql_or_tree):
        for g in t.find_all(exp.Group):
            out |= {_lc(c.name) for c in g.find_all(exp.Column)}
    return out


def groups_by(sql_or_tree, *names: str) -> bool:
    return bool(group_by_columns(sql_or_tree) & {_lc(n) for n in names})


def has_group_by(sql_or_tree) -> bool:
    return any(True for t in _trees(sql_or_tree) for _ in t.find_all(exp.Group))


def aggregates(sql_or_tree) -> list[exp.AggFunc]:
    return [a for t in _trees(sql_or_tree) for a in t.find_all(exp.AggFunc)]


def has_aggregate(sql_or_tree, *names: str) -> bool:
    """Any aggregate at all, or (with names) one of e.g. 'sum', 'count', 'avg'."""
    aggs = aggregates(sql_or_tree)
    if not names:
        return bool(aggs)
    wanted = {_lc(n) for n in names}
    return any(_lc(a.key) in wanted or _lc(a.sql_name()) in wanted for a in aggs)


def functions(sql_or_tree) -> set[str]:
    out = set()
    for t in _trees(sql_or_tree):
        for f in t.find_all(exp.Func):
            out.add(_lc(f.name if isinstance(f, exp.Anonymous) else f.sql_name()))
    return out


def has_distinct_count(sql_or_tree, column: str | None = None) -> bool:
    for t in _trees(sql_or_tree):
        for c in t.find_all(exp.Count):
            if isinstance(c.this, exp.Distinct):
                if column is None or references_column(c.this, column):
                    return True
    return False


def outer_limit(sql_or_tree) -> int | None:
    """The outer LIMIT as an int, -1 if it is not a plain number, None if absent."""
    for t in _trees(sql_or_tree):
        sel = outer_select(t) if not isinstance(t, exp.SetOperation) else t
        node = t if t.args.get("limit") is not None else sel
        if node is None:
            continue
        clause = node.args.get("limit")
        if clause is None:
            continue
        value = clause.args.get("count") if isinstance(clause, exp.Fetch) else clause.expression
        if isinstance(value, exp.Literal) and not value.is_string:
            try:
                return int(value.this)
            except ValueError:
                return -1
        return -1
    return None


def has_where(sql_or_tree) -> bool:
    return any(True for t in _trees(sql_or_tree) for _ in t.find_all(exp.Where))


def joins(sql_or_tree) -> list[exp.Join]:
    return [j for t in _trees(sql_or_tree) for j in t.find_all(exp.Join)]


def joined_tables(sql_or_tree) -> set[str]:
    """Lower-cased bare names of tables that appear in a JOIN or in a FROM list
    with more than one table (implicit join)."""
    out = set()
    for t in _trees(sql_or_tree):
        for sel in t.find_all(exp.Select):
            names = []
            frm = sel.args.get("from_") or sel.args.get("from")
            if frm is not None:
                names += [_lc(x.name) for x in frm.find_all(exp.Table)]
            for j in sel.args.get("joins") or []:
                names += [_lc(x.name) for x in j.find_all(exp.Table)]
            if len(names) > 1:
                out |= set(names)
    return out


# ── filters ─────────────────────────────────────────────────────────────────

def _unwrap(node: exp.Expression) -> exp.Expression:
    while isinstance(node, _TRANSPARENT) and node.this is not None:
        node = node.this
    return node


def _is_column(node: exp.Expression, names: set[str]) -> bool:
    node = _unwrap(node)
    return isinstance(node, exp.Column) and _lc(node.name) in names


def _string_values(node: exp.Expression) -> list[str]:
    """String literal values in a comparison's value side: 'x', UPPER('x'),
    ARRAY['a','b'], ANY(ARRAY[...]), ('a','b')."""
    node = _unwrap(node)
    if isinstance(node, exp.Literal) and node.is_string:
        return [node.this]
    vals: list[str] = []
    if isinstance(node, (exp.Any, exp.All, exp.Array, exp.Tuple)) or isinstance(node, exp.Paren):
        for lit in node.find_all(exp.Literal):
            if lit.is_string:
                vals.append(lit.this)
    return vals


def _numeric_values(node: exp.Expression) -> list[str]:
    node = _unwrap(node)
    if isinstance(node, exp.Literal):
        return [node.this]
    if isinstance(node, (exp.Any, exp.All, exp.Array, exp.Tuple, exp.Paren)):
        return [lit.this for lit in node.find_all(exp.Literal)]
    return []


_COMPARISONS = tuple(cls for cls in (getattr(exp, n, None) for n in (
    "EQ", "NEQ", "Like", "ILike", "GT", "GTE", "LT", "LTE", "Is",
)) if isinstance(cls, type))


def filter_conditions(sql_or_tree, *column_names: str) -> list[exp.Expression]:
    """Every comparison / IN / BETWEEN node that tests one of the columns
    (wrapped in UPPER(), TRIM(), a cast… or not), anywhere in the query."""
    names = {_lc(n) for n in column_names}
    out = []
    for t in _trees(sql_or_tree):
        for node in t.walk():
            if isinstance(node, exp.In) and _is_column(node.this, names):
                out.append(node)
            elif isinstance(node, exp.Between) and _is_column(node.this, names):
                out.append(node)
            elif isinstance(node, _COMPARISONS):
                if _is_column(node.this, names) or _is_column(node.expression, names):
                    out.append(node)
    return out


def filtered_by(sql_or_tree, *column_names: str) -> bool:
    """True if any WHERE / ON / HAVING condition tests one of the columns."""
    return bool(filter_conditions(sql_or_tree, *column_names))


def filter_values(sql_or_tree, *column_names: str, numeric: bool = False) -> list[str]:
    """Every literal value the query compares one of the columns against:
    `col = 'X'`, `UPPER(col) = 'X'`, `col IN ('A','B')` (all of them),
    `col = ANY(ARRAY['A','B'])`, `col LIKE 'X%'`, either side of the operator.
    numeric=True also returns number literals (year_key = 2023)."""
    names = {_lc(n) for n in column_names}
    vals: list[str] = []
    pick = _numeric_values if numeric else _string_values
    for node in filter_conditions(sql_or_tree, *column_names):
        if isinstance(node, exp.In):
            for e in node.expressions:
                vals.extend(pick(e))
        elif isinstance(node, exp.Between):
            vals.extend(pick(node.args.get("low")))
            vals.extend(pick(node.args.get("high")))
        else:
            side = node.expression if _is_column(node.this, names) else node.this
            vals.extend(pick(side))
    return vals


def string_literals(sql_or_tree) -> list[str]:
    return [l.this for t in _trees(sql_or_tree) for l in t.find_all(exp.Literal) if l.is_string]


def number_literals(sql_or_tree) -> list[str]:
    return [l.this for t in _trees(sql_or_tree) for l in t.find_all(exp.Literal) if not l.is_string]


# ── rewriting helpers ───────────────────────────────────────────────────────

def replace_string_literals(sql: str, mapping: Callable[[str], str | None],
                            column_names: Iterable[str] | None = None) -> str:
    """Rewrite string literals: `mapping(value)` returns the new value or None
    to keep it. With column_names, only literals compared to those columns."""
    names = {_lc(n) for n in column_names} if column_names else None

    def fn(tree: exp.Expression):
        targets: list[exp.Literal] = []
        if names is None:
            targets = [l for l in tree.find_all(exp.Literal) if l.is_string]
        else:
            for node in filter_conditions(tree, *names):
                if isinstance(node, exp.In):
                    sides = node.expressions
                elif isinstance(node, exp.Between):
                    sides = [node.args.get("low"), node.args.get("high")]
                else:
                    sides = [node.expression if _is_column(node.this, names) else node.this]
                for s in sides:
                    targets += [l for l in (s.find_all(exp.Literal) if s is not None else []) if l.is_string]
        for lit in targets:
            new = mapping(lit.this)
            if new is not None and new != lit.this:
                lit.replace(exp.Literal.string(new))
        return None

    return transform(sql, fn)


def rename_columns(sql: str, mapping: dict[str, str]) -> str:
    m = {_lc(k): v for k, v in mapping.items()}

    def fn(tree):
        for c in list(tree.find_all(exp.Column)):
            new = m.get(_lc(c.name))
            if new:
                c.set("this", exp.to_identifier(new))
        return None

    return transform(sql, fn)


def rename_tables(sql: str, mapping: dict[str, str]) -> str:
    """mapping: 'old' or 'schema.old' -> 'schema.new' / 'new'."""
    m = {_lc(k): v for k, v in mapping.items()}

    def fn(tree):
        for tb in list(tree.find_all(exp.Table)):
            key_q = f"{_lc(tb.db)}.{_lc(tb.name)}" if tb.db else _lc(tb.name)
            new = m.get(key_q) or m.get(_lc(tb.name))
            if new:
                parts = new.split(".")
                tb.set("this", exp.to_identifier(parts[-1]))
                if len(parts) > 1:
                    tb.set("db", exp.to_identifier(parts[-2]))
        return None

    return transform(sql, fn)


def remove_conditions(sql: str, predicate: Callable[[exp.Expression], bool]) -> str:
    """Drop every AND-ed condition for which `predicate(node)` is true (an
    emptied WHERE disappears). OR-ed conditions are left alone."""

    def fn(tree):
        for where in list(tree.find_all(exp.Where)):
            conds = list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this]
            keep = [c for c in conds if not predicate(c)]
            if len(keep) == len(conds):
                continue
            if not keep:
                where.pop()
            else:
                where.set("this", exp.and_(*keep, copy=False))
        return None

    return transform(sql, fn)


def add_condition(sql: str, condition: str) -> str:
    """AND `condition` (SQL text) into the outer SELECT's WHERE."""
    cond = sqlglot.parse_one(condition, read=DIALECT)

    def fn(tree):
        sel = outer_select(tree)
        if sel is not None:
            sel.where(cond.copy(), append=True, copy=False)
        return None

    return transform(sql, fn)


def set_limit(sql: str, n: int | None) -> str:
    """Set (n) or remove (None) the outer LIMIT."""

    def fn(tree):
        target = tree if tree.args.get("limit") is not None or isinstance(tree, exp.SetOperation) \
            else (outer_select(tree) or tree)
        if n is None:
            if target.args.get("limit") is not None:
                target.set("limit", None)
        else:
            target.set("limit", exp.Limit(expression=exp.Literal.number(n)))
        return None

    return transform(sql, fn)


def nulls_last_on_desc(sql: str) -> str:
    """Every descending ORDER BY key sorted NULLS LAST. PostgreSQL sorts NULL first
    on DESC, so a "top N" opened with the places that have no figure (chat UI
    audit 2026-10-29, E-5)."""

    def fn(tree):
        for o in tree.find_all(exp.Ordered):
            if o.args.get("desc") and o.args.get("nulls_first") is not False:
                o.set("nulls_first", False)
        return None

    return transform(sql, fn)


def low_end_queries(sql: str, measure: str) -> "tuple[str, str] | None":
    """I-10 / J-7 (chat UI audit 2026-10-29): "lowest 5 villages" over hundreds of
    villages tied at 0 picked 5 of them at random. For a ranking query ending in
    LIMIT n: (how many rows have no `measure`, the n lowest rows that have one),
    both over the query without its ORDER BY / LIMIT. None when it has no LIMIT."""
    tree = parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("limit") is None:
        return None
    lim = tree.args["limit"].args.get("expression")
    if not isinstance(lim, exp.Literal) or not lim.is_int:
        return None
    n = int(lim.this)
    inner = tree.copy()
    inner.set("limit", None)
    inner.set("order", None)
    body = inner.sql(dialect=DIALECT)
    col = exp.to_identifier(measure, quoted=True).sql(dialect=DIALECT)
    zero = f"SELECT COUNT(*) AS zero_places FROM ({body}) AS ranked_q WHERE COALESCE({col}, 0) = 0"
    lowest = f"SELECT * FROM ({body}) AS ranked_q WHERE {col} > 0 ORDER BY {col} ASC LIMIT {n}"
    return zero, lowest


def widen_village_filter(sql: str, codes: list) -> str:
    """J-10 (chat UI audit live run 2026-10-29): villages that share a name are all
    asked; a filter `village_code = <one of them>` becomes `village_code IN (all)`,
    and a LIMIT smaller than their number is dropped. Anything else: unchanged."""
    want = [int(c) for c in codes]
    names = {str(c) for c in want}

    def fn(tree):
        hit = False
        for eq in list(tree.find_all(exp.EQ)):
            col, lit = eq.this, eq.expression
            if isinstance(lit, exp.Column) and isinstance(col, exp.Literal):
                col, lit = lit, col
            if isinstance(col, exp.Column) and col.name.lower() == "village_code" \
                    and isinstance(lit, exp.Literal) and lit.this in names:
                eq.replace(exp.In(this=col.copy(), expressions=[exp.Literal.number(c) for c in want]))
                hit = True
        if hit and isinstance(tree, exp.Select) and tree.args.get("limit") is not None:
            lim = tree.args["limit"].args.get("expression")
            if isinstance(lim, exp.Literal) and lim.is_int and int(lim.this) < len(want):
                tree.set("limit", None)
        return None

    return transform(sql, fn)


def group_by_village(sql: str) -> str:
    """J-10 guard (MGNREGA UAT 2026-10-30): a one-SELECT aggregate over a village_code IN
    (...) filter that does not group by village gets village_code, lgd_village_name and
    lgd_block in its SELECT and GROUP BY, so villages that share a name are answered one
    row each instead of summed ("Rangmalgre" = Demdema + Resubelpara, 12.55 lakh for a
    2.99 lakh village). A CTE, join, set operation or window query: unchanged."""
    def fn(tree):
        if not isinstance(tree, exp.Select) or tree.find(exp.With) or tree.find(exp.Join) \
                or tree.find(exp.Window) or any(s is not tree for s in tree.find_all(exp.Select)):
            return None
        if not tree.find(exp.AggFunc):
            return None
        if not any(isinstance(i.this, exp.Column) and i.this.name.lower() == "village_code"
                   for i in tree.find_all(exp.In)):
            return None
        grouped = group_by_columns(tree)
        selected = {_lc(_unwrap(e.unalias()).name) for e in tree.expressions
                    if isinstance(_unwrap(e.unalias()), exp.Column)}
        # "SELECT village_code, … GROUP BY 1": positional, already one row per village
        if "village_code" in selected and not grouped:
            return None
        # grouped by name and block only (Bawegre, all-villages run 2026-10-30): the rows
        # carried no code, so nothing could tie a row to its twin — the code is always added
        cols = [c for c in ("village_code", "lgd_village_name", "lgd_block") if c not in grouped and c not in selected]
        if not cols or ("village_code" not in cols and {"village_code", "lgd_village_name"} & grouped):
            return None
        tree.set("expressions", [exp.column(c) for c in cols] + list(tree.expressions))
        group = tree.args.get("group")
        if group is not None:
            group.set("expressions", list(group.expressions) + [exp.column(c) for c in cols])
        else:
            tree.set("group", exp.Group(expressions=[exp.column(c) for c in cols]))
        lim = tree.args.get("limit")
        if lim is not None and isinstance(lim.args.get("expression"), exp.Literal) \
                and int(lim.args["expression"].this) < 10:
            tree.set("limit", None)
        return None

    return transform(sql, fn)


def without_limit(sql: str) -> str:
    """The query without its outer LIMIT / OFFSET (E-3: counting the rows past the cap).
    Unparseable or not one SELECT: unchanged."""
    tree = parse_one(sql)
    if not isinstance(tree, exp.Select):
        return sql
    tree.set("limit", None)
    tree.set("offset", None)
    return tree.sql(dialect=DIALECT)


def output_sources(sql: str) -> dict:
    """X-14: for each output column of the outer SELECT, {"tables": every table the
    query reads, "cols": the source column names in its expression, "div": the number
    it is divided by (None), "ratio": True when it is divided by another column}.
    {} when the query is not one plain SELECT."""
    tree = parse_one(sql)
    if not isinstance(tree, exp.Select):
        return {}
    tables = sorted({t.name.lower() for t in tree.find_all(exp.Table) if t.name})
    out = {}
    for e in tree.expressions:
        name = e.alias_or_name
        cols = sorted({c.name.lower() for c in e.find_all(exp.Column) if c.name})
        div, ratio = None, False
        for d in e.find_all(exp.Div):
            right = d.expression.this if isinstance(d.expression, exp.Paren) else d.expression
            if isinstance(right, exp.Literal) and not right.is_string:
                try:
                    div = float(right.this)
                except ValueError:
                    ratio = True
            elif list(right.find_all(exp.Column)) or isinstance(right, exp.Column):
                ratio = True
        out[name] = {"tables": tables, "cols": cols, "div": div, "ratio": ratio}
    return out


_PERIOD_OUTPUTS = ("financial_year", "financial_year_short", "fy", "year_key", "year", "month", "month_name",
                   "quarter")


def rank_within_period(sql: str) -> "str | None":
    """I-2 (chat UI audit live run 2026-10-29): "top 5 districts year wise" was
    answered with ORDER BY measure DESC LIMIT 5 over every year (one year's top 5).
    A query ending in ORDER BY <measure> LIMIT N whose output has a period column
    is rewritten to the top N of EACH period:
      SELECT * FROM (SELECT q.*, ROW_NUMBER() OVER (PARTITION BY <period> ORDER BY
      <measure> <dir>) AS rank_in_period FROM (<query without ORDER BY / LIMIT>) q) r
      WHERE rank_in_period <= N ORDER BY <period>, rank_in_period
    None when the query has no such shape or already ranks with a window."""
    tree = parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("limit") is None or tree.find(exp.Window):
        return None
    lim = tree.args["limit"].args.get("expression")
    order = tree.args.get("order")
    if not isinstance(lim, exp.Literal) or not lim.is_int or order is None or not order.expressions:
        return None
    names = [e.alias_or_name for e in tree.expressions]
    period = next((n for n in names if n and n.lower() in _PERIOD_OUTPUTS), None)
    key = order.expressions[0]
    measure = key.this
    m_name = measure.alias_or_name if isinstance(measure, exp.Column) else None
    if m_name not in names:
        # ORDER BY SUM(x) when SUM(x) is selected under an alias: use that alias
        m_sql = measure.sql(dialect=DIALECT)
        m_name = next((e.alias for e in tree.expressions
                       if isinstance(e, exp.Alias) and e.this.sql(dialect=DIALECT) == m_sql), None)
    if not period or not m_name or m_name == period:
        return None
    inner = tree.copy()
    inner.set("limit", None)
    inner.set("order", None)
    direction = "DESC" if key.args.get("desc") else "ASC"
    q = lambda n: exp.to_identifier(n, quoted=True).sql(dialect=DIALECT)  # noqa: E731
    return (f"SELECT * FROM (SELECT ranked_q.*, ROW_NUMBER() OVER (PARTITION BY {q(period)} ORDER BY "
            f"{q(m_name)} {direction} NULLS LAST) AS rank_in_period FROM ({inner.sql(dialect=DIALECT)}) AS ranked_q) "
            f"AS per_period WHERE rank_in_period <= {int(lim.this)} ORDER BY {q(period)}, rank_in_period")


def tie_count_query(sql: str, measure: str, value) -> "tuple[int, str] | None":
    """E-9 (chat UI audit 2026-10-29): a "top N" cut at LIMIT N dropped one of the
    places tied for the Nth place at random. (N, how many rows of the query without
    its ORDER BY / LIMIT have `measure` = `value`). None when there is no LIMIT N."""
    tree = parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("limit") is None:
        return None
    lim = tree.args["limit"].args.get("expression")
    if not isinstance(lim, exp.Literal) or not lim.is_int:
        return None
    inner = tree.copy()
    inner.set("limit", None)
    inner.set("order", None)
    col = exp.to_identifier(measure, quoted=True).sql(dialect=DIALECT)
    lit = exp.Literal.number(value).sql(dialect=DIALECT)
    return int(lim.this), (f"SELECT COUNT(*) AS tied FROM ({inner.sql(dialect=DIALECT)}) AS ranked_q "
                           f"WHERE {col} = {lit}")


# ── text around a query ─────────────────────────────────────────────────────

def statement_text(sql: str) -> str:
    """The query up to its last real token (trailing ';' and comments dropped)."""
    try:
        tokens = sqlglot.tokenize(sql, read=DIALECT)
    except (SqlglotError, ValueError):
        return sql.strip()
    last = next((t for t in reversed(tokens) if t.token_type != TokenType.SEMICOLON), None)
    return sql[: last.end + 1] if last is not None else ""


def first_keyword(sql: str | None) -> str:
    """The first token's text, upper-cased ('SELECT', 'WITH', …); '' if none."""
    if not sql:
        return ""
    try:
        tokens = sqlglot.tokenize(sql, read=DIALECT)
    except (SqlglotError, ValueError):
        return ""
    return tokens[0].text.upper() if tokens else ""

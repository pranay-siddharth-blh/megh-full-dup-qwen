# app/pipeline/common/c10_sql_generation_and_rewrites.py — SQL generation, shared fixed-shape checks, the per-scheme SQL rewrite dispatcher.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
#
# Every check and rewrite of SQL text here works on the SQLGlot tree or token
# stream (app/sql_ast.py), never on the raw text. The word matchers left in
# this file read the user's QUESTION (English), not SQL.
from app import sql_ast
from sqlglot import exp
from app.text_match import (
    Matcher, W, Pred, ANY, Seq, Alt, Opt, Rep, Gap, Joined, Cap, NotBefore, NotAfter,
    Before, After, START, END, Hit, collapse_ws, is_int, is_year, split_sentences,
)
from app.text_match import Node as _C1xNode
from app.text_match import _Ctx as _C1xCtx, tokens as _c1x_tokens


# ── word-matching helpers shared by c10–c14 (D-047: app/text_match only) ───
# Word matchers come from app/text_match.py. The few shapes it does not cover
# (a separator that must be whitespace / an apostrophe, a gap measured in
# characters, a literal '%' that is not a word, a character-level scan) are the
# small pieces below; every object here offers the Matcher surface the callers
# use: .search / .finditer / .findall / .sub / __call__ (and Hit results).

def _c1x_ws(gap: str) -> bool:
    """A non-empty gap made only of whitespace."""
    return gap != "" and gap.strip() == ""


def _c1x_ws0(gap: str) -> bool:
    """An empty or whitespace-only gap."""
    return gap.strip() == ""


def _c1x_apos0(gap: str) -> bool:
    """Nothing, or one apostrophe (' or ’)."""
    return gap in ("", "'", "’")


def _c1x_ws_or_dash(gap: str) -> bool:
    """Whitespace and/or hyphens, at least one."""
    return gap != "" and all(ch.isspace() or ch == "-" for ch in gap)


def _c1x_ws_or_dash0(gap: str) -> bool:
    """Empty, or exactly one whitespace character or hyphen."""
    return gap == "" or (len(gap) == 1 and (gap.isspace() or gap == "-"))


class _C1xGapIs(_C1xNode):
    """x, provided the separator text in front of its first word passes ok(gap)."""

    def __init__(self, x, ok):
        self.x = x if isinstance(x, _C1xNode) else Matcher(x).node
        self.ok = ok

    def ends(self, ctx, i, caps):
        if i >= len(ctx.toks):
            return
        start = ctx.toks[i - 1].end if i > 0 else 0
        if not self.ok(ctx.text[start:ctx.toks[i].start]):
            return
        yield from self.x.ends(ctx, i, caps)


class _C1xRun(_C1xNode):
    """lo..hi words that each pass pred(raw); the separator before each word must
    pass gap_ok (the first one: first_gap_ok, default gap_ok). Fewest first."""

    def __init__(self, pred, lo: int = 1, hi: "int | None" = None, gap_ok=_c1x_ws,
                 first_gap_ok=None, lazy: bool = True):
        self.pred, self.lo, self.hi = pred, lo, hi
        self.gap_ok = gap_ok
        self.first_gap_ok = first_gap_ok
        self.lazy = lazy

    def ends(self, ctx, i, caps):
        n = len(ctx.toks)
        stops = []
        j = i
        if self.lo == 0:
            stops.append(j)
        while j < n and (self.hi is None or j - i < self.hi):
            t = ctx.toks[j]
            if not self.pred(t.raw):
                break
            if j > i or self.first_gap_ok is not None:
                ok = self.gap_ok if j > i else self.first_gap_ok
                prev_end = ctx.toks[j - 1].end if j > 0 else 0
                if not ok(ctx.text[prev_end:t.start]):
                    break
            j += 1
            if j - i >= self.lo:
                stops.append(j)
        for k in (stops if self.lazy else reversed(stops)):
            yield k, caps


class _C1xCharGap(_C1xNode):
    """Any number of words (fewest first) whose covering text, measured from the
    end of the previous word to the start of the next, is at most max_chars long
    and holds none of the `forbid` characters (e.g. no "." at all)."""

    def __init__(self, max_chars: "int | None" = None, forbid: str = ""):
        self.max_chars, self.forbid = max_chars, forbid

    def ends(self, ctx, i, caps):
        n = len(ctx.toks)
        base = ctx.toks[i - 1].end if i > 0 else 0
        for k in range(i, n + 1):
            stop = ctx.toks[k].start if k < n else len(ctx.text)
            span = ctx.text[base:stop]
            if self.max_chars is not None and len(span) > self.max_chars:
                return
            if any(ch in span for ch in self.forbid):
                return
            yield k, caps


def _c1x_suffix(*opts: str) -> "Pred":
    """One word ending in any of `opts` (anything may come before the ending)."""
    low = tuple(o.lower() for o in opts)
    return Pred(lambda w: w.lower().endswith(low))


class _C1xLike:
    """The Matcher surface on top of a list of Hits (subclasses give _hits)."""

    def _hits(self, text: str) -> "list[Hit]":
        raise NotImplementedError

    def finditer(self, text):
        return iter(self._hits(text or ""))

    def search(self, text):
        hits = self._hits(text or "")
        return hits[0] if hits else None

    def __call__(self, text) -> bool:
        return self.search(text) is not None

    def match(self, text):
        h = self.search(text)
        return h if h is not None and h.start() == 0 else None

    def fullmatch(self, text):
        t = text or ""
        for h in self._hits(t):
            if h.start() == 0 and h.end() == len(t):
                return h
        return None

    def findall(self, text):
        out = []
        for h in self._hits(text or ""):
            if not h._groups:
                out.append(h.group(0))
            elif len(h._groups) == 1:
                out.append(h.group(1) or "")
            else:
                out.append(tuple(g or "" for g in h.groups()))
        return out

    def sub(self, repl, text, count: int = 0) -> str:
        text = text or ""
        out, last, k = [], 0, 0
        for h in self._hits(text):
            out.append(text[last:h.start()])
            out.append(repl(h) if callable(repl) else repl)
            last = h.end()
            k += 1
            if count and k >= count:
                break
        out.append(text[last:])
        return "".join(out)

    def subn(self, repl, text, count: int = 0):
        n = len(self._hits(text or ""))
        if count:
            n = min(n, count)
        return self.sub(repl, text, count), n


class _C1xScan(_C1xLike):
    """A character-level matcher: fn(text) gives (start, end) or
    (start, end, [group spans]) tuples, left to right, non-overlapping."""

    def __init__(self, fn):
        self.fn = fn

    def _hits(self, text):
        out = []
        for sp in self.fn(text):
            groups = list(sp[2]) if len(sp) > 2 else []
            out.append(Hit(text, sp[0], sp[1], groups))
        return out


class _C1xUnion(_C1xLike):
    """Any of several pieces: Matchers / matcher-likes, or literal strings found
    anywhere, case-insensitive (e.g. '%', which is not a word). Leftmost first;
    overlapping later hits are dropped."""

    def __init__(self, *parts):
        self.parts = parts

    def _hits(self, text):
        found = []
        low = text.lower()
        for order, p in enumerate(self.parts):
            if isinstance(p, str):
                needle = p.lower()
                if not needle:
                    continue
                k = low.find(needle)
                while k >= 0:
                    found.append((k, order, Hit(text, k, k + len(needle))))
                    k = low.find(needle, k + len(needle))
            else:
                for h in p.finditer(text):
                    found.append((h.start(), order, h))
        found.sort(key=lambda t: (t[0], t[1]))
        out, last = [], -1
        for s, _o, h in found:
            if s < last:
                continue
            out.append(h)
            last = h.end() if h.end() > s else s + 1
        return out


def _c1x_is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _c1x_bounded_spans(needle: str, text: str) -> "list[tuple[int, int]]":
    """Where `needle` occurs in `text` as whole words, not inside a longer word
    (case-insensitive), left to right, non-overlapping."""
    text = text or ""
    if not needle:
        return []
    low, nd = text.lower(), needle.lower()
    if len(low) != len(text) or len(nd) != len(needle):
        low, nd = text, needle
    n = len(low)

    def boundary(pos: int) -> bool:
        a = pos > 0 and _c1x_is_word_char(low[pos - 1])
        b = pos < n and _c1x_is_word_char(low[pos])
        return a != b

    out, k = [], low.find(nd)
    while k >= 0:
        if boundary(k) and boundary(k + len(nd)):
            out.append((k, k + len(nd)))
            k = low.find(nd, k + len(nd))
        else:
            k = low.find(nd, k + 1)
    return out


def _c1x_bounded_find(needle: str, text: str) -> bool:
    """`needle` occurs in `text` as whole words (case-insensitive)."""
    return bool(_c1x_bounded_spans(needle, text))


def _c1x_bounded_sub(needle: str, repl: str, text: str, count: int = 0) -> str:
    """Replace whole-word `needle` with `repl` (case-insensitive, at most `count`), repl taken literally."""
    out, last = [], 0
    for k, (s0, e0) in enumerate(_c1x_bounded_spans(needle, text)):
        if count and k >= count:
            break
        out.append(text[last:s0])
        out.append(repl)
        last = e0
    out.append((text or "")[last:])
    return "".join(out)


def _c1x_lit(phrase: str):
    """Words separated by exactly one space each (a literal "financial year")."""
    parts = phrase.split()
    return Seq(W(parts[0]), *[_C1xGapIs(W(w), lambda g: g == " ") for w in parts[1:]])


def _c1x_is_ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _c1x_loose_spans(name: str, text: str) -> "list[tuple[int, int]]":
    """Where a place name occurs in `text`, ignoring the spacing around brackets
    and hyphens and collapsing runs of spaces ("DATHBANGA ( KOCH )" also finds
    "Dathbanga (Koch)"), case-insensitive, not inside a longer [A-Za-z0-9] run.
    No letter or digit may touch the match on either side."""
    elems: list = []          # "ws" (any whitespace, maybe none) or one literal char
    for ch in collapse_ws(name):
        if ch in "()-":
            elems += ["ws", ("c", ch), "ws"]
        elif ch == " ":
            elems.append("ws")
        else:
            elems.append(("c", ch))
    if not elems:
        return []
    text = text or ""
    n = len(text)
    out, p = [], 0
    while p <= n:
        if p > 0 and _c1x_is_ascii_alnum(text[p - 1]):
            p += 1
            continue
        q, ok, ws_marks = p, True, []
        for e in elems:
            if e == "ws":
                s = q
                while q < n and text[q].isspace():
                    q += 1
                ws_marks.append((s, q))
            else:
                if q < n and text[q].lower() == e[1].lower():
                    q += 1
                    ws_marks.append(None)
                else:
                    ok = False
                    break
        if ok:
            ends = [q]
            if elems[-1] == "ws":          # trailing spaces give back what the end check needs
                s, e2 = ws_marks[-1]
                ends = list(range(e2, s - 1, -1))
            for end in ends:
                if not (end < n and _c1x_is_ascii_alnum(text[end])):
                    if end > p:
                        out.append((p, end))
                        p = end
                    else:
                        p += 1
                    break
            else:
                p += 1
            continue
        p += 1
    return out


def _c1x_loose_sub(name: str, repl: str, text: str, count: int = 0) -> str:
    out, last = [], 0
    for k, (s, e) in enumerate(_c1x_loose_spans(name, text)):
        if count and k >= count:
            break
        out.append(text[last:s])
        out.append(repl)
        last = e
    out.append(text[last:])
    return "".join(out)


async def generate_sql(question: str, schemes: list[str], entity_result: dict) -> str:
    # The whole prompt — hand-written backbone + live schema + SME catalog +
    # prohibited joins + few-shot + resolved entities — is assembled in one place.
    # "FY 23" is FY 2022-23, which the model wrote as year_key = 2023 (KI-431)
    prompt = prompt_builder.build_sql_prompt(context_policy.expand_short_fy(question), schemes, entity_result)
    raw = await llm.call_sql_generator(prompt)
    sql = _extract_sql(raw)
    return _focusplus_single_district_beneficiary_guard(question, schemes, entity_result, sql)


# The generator sometimes reads "in Meghalaya" as a place filter and invents a
# WHERE on a state pseudo-row that no fact row matches — the query then runs
# clean but counts 0. Catch that shape and force one repair pass (the repair
# prompt carries the "whole dataset is Meghalaya" rule, so it drops the filter).
# An assembly constituency cuts ACROSS blocks and districts, so its name is
# usually not a block/district name at all. When only the constituency was
# resolved, the generator still reaches for `lgd_block = '<same name>'` next to
# the AC filter — two conditions that can never both hold, giving a clean,
# confident ZERO (confirmed live 2026-09-17: "which villages in Rangsakona
# received employment in FY 2025-26" answered "no matching records"; RANGSAKONA
# spans the BETASING, RERAPARA and RONGRAM blocks and the real answer is 146
# villages). The prompt now warns against it (prompt_builder._entities_block),
# but a prose rule doesn't reliably win under sampling — this catches the shape
# deterministically, the same way the village_code guards above do.
def _sql_cond_sides(node: "exp.Expression", names: "set[str]") -> "tuple[exp.Expression, exp.Expression] | None":
    """(column side, value side) of a comparison whose one side is one of the
    columns `names` (wrapped in UPPER()/TRIM()/a cast or not), else None."""
    for col, val in ((node.this, node.expression), (node.expression, node.this)):
        if isinstance(col, exp.Expression) and isinstance(val, exp.Expression) and sql_ast._is_column(col, names):
            return col, val
    return None


def _sql_string_literal(node: "exp.Expression | None") -> "str | None":
    """The value of a string literal, also wrapped ('x', UPPER('x'), TRIM('x'))."""
    node = sql_ast._unwrap(node) if isinstance(node, exp.Expression) else None
    return node.this if isinstance(node, exp.Literal) and node.is_string else None


def _sql_string_comparisons(sql_or_tree, names, kinds) -> "list[tuple[exp.Expression, str, str]]":
    """(node, column name, literal) for every `kinds` comparison of one of the
    columns `names` with a single string literal, in reading order."""
    wanted = {n.lower() for n in names}
    trees = [sql_or_tree] if isinstance(sql_or_tree, exp.Expression) else sql_ast.parse(sql_or_tree)
    out = []
    for tree in trees:
        for node in tree.walk(bfs=False):
            if not isinstance(node, kinds):
                continue
            sides = _sql_cond_sides(node, wanted)
            lit = _sql_string_literal(sides[1]) if sides else None
            if lit is not None:
                out.append((node, sql_ast._unwrap(sides[0]).name.lower(), lit))
    return out


# Reads the filter in every shape the generator writes it: a bare column, a
# table-qualified one (dg.lgd_block), and either side wrapped in UPPER().
def _sql_geo_eq_literal(sql: str) -> "tuple[str, str] | None":
    """(column, literal) of the first lgd_district / lgd_block = / ILIKE '<x>'."""
    hits = _sql_string_comparisons(sql or "", ("lgd_district", "lgd_block"), (exp.EQ, exp.ILike))
    return (hits[0][1], hits[0][2]) if hits else None


def _ac_with_invented_geo_filter(entity_result: dict, sql: str) -> "str | None":
    """The geography literal a query added alongside an assembly-constituency
    filter that entity resolution never produced, or None.

    Only fires when the resolved entities carry an assembly_constituency and NO
    district/block of their own — i.e. the filter cannot have come from
    resolution, so the generator invented it from the question text."""
    resolved = entity_result.get("resolved") or {}
    if not resolved.get("assembly_constituency"):
        return None
    if resolved.get("district") or resolved.get("block") \
            or resolved.get("district_list") or resolved.get("block_list"):
        return None
    if not sql_ast.references_column(sql or "", "assembly_constituency_name"):
        return None
    hit = _sql_geo_eq_literal(sql or "")
    return f"{hit[0]} = '{hit[1]}'" if hit else None


_JOB_CARD_PIN = "year_key = (SELECT MAX(year_key) FROM curated.v_employment)"
_SHARE_ASKED = _C1xUnion(
    Matcher(Alt(W("share", "ratio", "proportion", "fraction", "rate"), W("percent", prefix=True))), "%")
# The words that ask for a split by financial year (c11 sends back a GROUP BY
# on the year alone when the question asked for one combined figure).
_YEAR_SPLIT_ASKED = Matcher(Alt(
    Joined("year", "wise"),
    Seq("each", Opt(W("financial", "fiscal")), W("year", prefix=True)),
    Seq("per", Opt("financial"), W("year", prefix=True)),
    Seq("by", Opt(W("financial", "fiscal")), W("year", "years")),
    "every year",
    Seq("year", W("by", "on", "over"), "year"),
    W("trend", "trends", "yearly", "split", "breakdown"),
    "over the years",
    W("annual", prefix=True),
    Seq("break", Opt("it"), "down"),
    Seq("which", Opt("financial"), W("year", prefix=True)),     # also "in which (financial) year"
))


# "Which villages in NONGKREM received employment" was answered with four
# village CODES and no names — and all four were counted although three had
# zero employment (DATA-014, KI-045).
_VILLAGE_LIST_ASK_MATCH = Matcher(Alt(
    Seq("which", "villages"),
    Seq("list", Opt(W("of", "all")), Opt("the"), "villages"),
    Seq("name", W("the", "all"), "villages"),
    Seq("what", "villages"),
))


# "Which villages in <AC> received employment?" came back with LIMIT 100 from
# the model, so constituencies of 105-234 villages were listed as "the 100
# results" (MGNREGA sheet DATA-014, run 2026-10-09). A "which villages" list
# that asks for no top-N is the whole list; run_readonly still caps at 1000.
_C1X_RANK_WORDS = ("top", "first", "last", "bottom", "highest", "lowest", "best", "worst", "leading")


def _c1x_rank_joined_number(w: str) -> bool:
    """"top10" — a rank word with the number written on ("top" then digits)."""
    low = w.lower()
    return any(low.startswith(r) and len(low) > len(r) and low[len(r):].isdecimal() for r in _C1X_RANK_WORDS)


_TOP_N_ASK_MATCH = Matcher(Alt(
    Seq(W(*_C1X_RANK_WORDS), _C1xGapIs(Pred(str.isdecimal), _c1x_ws0)),
    Pred(_c1x_rank_joined_number),
    Seq(Pred(str.isdecimal), _C1xGapIs(W("villages", "blocks", "districts"), _c1x_ws)),
    W("limit"),
))


def _order_by_cols_selected(sql: str) -> bool:
    """True when every outer ORDER BY term is in the SELECT list (the same
    expression, an output name, or a position) — the condition for SELECT
    DISTINCT to stay valid SQL in PostgreSQL. False when unparseable."""
    tree = sql_ast.parse_one(sql)
    if tree is None:
        return False
    sel = sql_ast.outer_select(tree)
    order = tree.args.get("order") or (sel.args.get("order") if sel is not None else None)
    if order is None:
        return True
    if sel is None:
        return False
    if any(isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star))
           for e in sel.expressions):
        return True
    selected = {sql_ast.to_sql(e.unalias()).lower() for e in sel.expressions}
    names = {(e.alias_or_name or "").lower() for e in sel.expressions}
    for term in order.expressions:
        t = term.this if isinstance(term, exp.Ordered) else term
        if isinstance(t, exp.Literal) and not t.is_string:
            continue
        if sql_ast.to_sql(t).lower() in selected:
            continue
        if isinstance(t, exp.Column) and t.name.lower() in names:
            continue
        return False
    return True


# "Was more spent on wages or materials in JAKREM?" returned only a CASE label
# ('wages'), so the answer had no amounts and even claimed none were available
# (DATA-023, KI-047). A comparison must return the figures it compares.
_QUANTITY_COMPARISON_MATCH = Matcher(Alt(
    Seq(W("more", "less", "higher", "lower", "greater", "bigger", "smaller"),
        _C1xCharGap(max_chars=60, forbid="\n"), W("or", "than")),
    W("compar", prefix=True),
    W("vs", "versus"),
))


def _c1x_ascii_letters(w: str) -> bool:
    return w.isascii() and w.isalpha()


_ONLY_ONE_SENTENCE_MATCH = Matcher(Alt(
    Seq("only", W("district", "block", "village", "area", "entry", "record", "row"), sep="space"),
    Seq("in", "the", "result", sep="space"),
    # "highest … in the East Khasi Hills district" (no full stop in between; the
    # name is letters and spaces only)
    Seq("highest", _C1xCharGap(forbid="."),
        Seq("in", "the", _C1xRun(_c1x_ascii_letters, 1, None), W("district", "block"), sep="space")),
))


# ── MGNREGA women employment: which years actually carry it ─────────────────
# women_employment_provided is 0 on EVERY record for FY 2025-26 — not populated
# at source (docs/MGNREGA_DB_Issues.md, Issue 2). "What percentage of employment
# persons were women in ekh?" named no year; the percentage cue was missing from
# the year gate, so the SQL model silently took MAX(year_key) = FY 2025-26 and
# the bot answered "0.00% … a genuine zero" — East Khasi Hills is really 77.70%
# in FY 2024-25 (user report, 2026-09-27). Women answers therefore use only the
# years that carry women data, say which years they cover, and call FY 2025-26
# "not recorded", never zero. Read live, so a later ingest that fills the year
# is picked up without a code change.
_WOMEN_CUE = Matcher(W("women", "woman", "female", "females", "mahila"))
_RATIO_CUE = _C1xUnion(Matcher(Alt(
    Seq("per", _C1xGapIs(W("cent", prefix=True), _c1x_ws)),
    W("percent", prefix=True),
    W("share", "proportion", "ratio"),
)), "%")


def _women_span(years: "list[dict]") -> str:
    labels = [f"FY {y['fy']}" for y in years]
    return labels[0] if len(labels) == 1 else f"{labels[0]} to {labels[-1]}"


# a column NAME carrying a money word anywhere in it (substring, not a whole word)
_MONEY_COL_NAME_MATCH = _C1xUnion("exp", "lakh", "wage", "material", "spend", "cost", "amount")


# curated.* stores lgd_district / lgd_block UPPERCASE (docs/DATA_MODEL.md). When
# entity resolution misses and the generator copies the question's Title-Case
# spelling straight into the literal (lgd_district = 'West Garo Hills'), the
# query runs clean and counts zero. Upper-case *only* the string literals
# compared with `=` / `!=` / `<>` / `IN` (and = ANY(ARRAY[...])) against those
# two columns — nothing else is touched, and an ILIKE / LIKE clause is left
# as-is. Also UPPER(lgd_block) = '...': the FOCUS sheet run (2026-10-12) got
# 'NONGstoin' there -> 0 groups.
def _uppercase_geo_literals(sql: str) -> str:
    names = {"lgd_district", "lgd_block"}

    def fn(tree):
        lits = []
        for node in sql_ast.filter_conditions(tree, *names):
            if isinstance(node, exp.In):
                sides = list(node.expressions)
            elif isinstance(node, (exp.EQ, exp.NEQ)):
                sides = [_sql_cond_sides(node, names)[1]]
            else:
                continue
            for side in sides:
                lits += [l for l in side.find_all(exp.Literal) if l.is_string and l.this != l.this.upper()]
        for lit in lits:
            lit.replace(exp.Literal.string(lit.this.upper()))
        return None

    changed = sql_ast.transform(sql, fn) if sql else sql
    if changed != sql:
        logger.info("normalised lgd_district/lgd_block literal(s) to upper-case for storage match")
    return changed


_VILLAGE_WORD_MATCH = Matcher(W("village", "villages"))
# Focus Legacy has the same placeholder design and the same rule (README §5,
# "entity_type <> 'Unresolved' on village counts and lists only — never on
# money, district"). Its 2026-09-25 QA hit the identical bug: TC-18 "total amount
# disbursed for East Khasi Hills" dropped 11 no-village payments (₹5,35,15,000
# against a true ₹5,42,05,000).
# CM Elevate (applications) has the same design and rule (CM ELEVATE RULES
# rule 5). Its 2026-09-27 QA hit it too (KI-068, CM-ELEVATE-OFF-005): "how many
# applicants under each CM ELEVATE program" dropped the 51 no-village
# applications — SEED 3,617 against a true 3,633, 8 of 15 programmes low.
_UNRESOLVED_PLACEHOLDER_SCHEMES = (["CM Elevate Legacy"], ["Focus Legacy"], ["CM Elevate"], ["CMSS"], ["Homestay"])


# ── CM Elevate SQL shape guards (use-case QA 2026-09-27, KI-069 / 070 / 072) ─
# Each prose rule below already sat in schema_context (rules 4, 13, 14) and
# did not hold under sampling; each fix is one unambiguous edit once the shape
# is detected, so it is applied deterministically, like the Unresolved guard.
def _drop_where_conditions(sql: str, predicate) -> str:
    """Remove every AND-ed WHERE condition for which `predicate(node)` holds
    (an emptied WHERE disappears); the text is regenerated from the tree."""
    return sql_ast.remove_conditions(sql, predicate) if sql else sql


def _sql_is_simple_select(sql: str) -> bool:
    """One plain SELECT: no subquery, JOIN, UNION or WITH."""
    tree = sql_ast.parse_one(sql)
    return (isinstance(tree, exp.Select) and len(list(tree.find_all(exp.Select))) == 1
            and not sql_ast.joins(tree) and not sql_ast.has_cte(tree))


# the stored district literals (UPPER), used when the resolver catalogue is not loaded
_MEGHALAYA_12_DISTRICTS = ("RI BHOI", "WEST GARO HILLS", "EAST KHASI HILLS", "EAST GARO HILLS", "WEST KHASI HILLS",
                           "SOUTH GARO HILLS", "SOUTH WEST KHASI HILLS", "EASTERN WEST KHASI HILLS",
                           "NORTH GARO HILLS", "WEST JAINTIA HILLS", "SOUTH WEST GARO HILLS", "EAST JAINTIA HILLS")


def _resolved_district_list_literals(resolved: dict, sql: str) -> str:
    """The districts the question resolved are the districts the SQL filters.
    "…across Eastern West Khasi Hills and East Garo Hills" resolved both, and the
    30B wrote lgd_district IN ('EASTERN WEST KHASI HILLS', 'EAST KHASI HILLS')
    (CM Elevate sheet OFF-027, 2026-10-10). An IN-list of the same size naming
    other districts is replaced by the resolved list."""
    want = [str(d).upper() for d in (resolved.get("district_list") or [])]
    if len(want) < 2 or not sql:
        return sql
    seen: list = []

    def fn(tree):
        for node in tree.walk(bfs=False):
            if not (isinstance(node, exp.In) and sql_ast._is_column(node.this, {"lgd_district"})):
                continue
            vals = [_sql_string_literal(e) for e in node.expressions]
            if not vals or any(v is None for v in vals):
                return None
            have = [v.upper() for v in vals]
            if len(have) != len(want) or set(have) == set(want):
                return None
            node.set("expressions", [exp.Literal.string(d) for d in want])
            seen.append(have)
            return None
        return None

    out = sql_ast.transform(sql, fn)
    if seen:
        logger.info("district IN-list %s replaced by the resolved districts %s", seen[0], want)
    return out


def _stray_block_literal(schemes: list[str], resolved: dict, sql: str) -> str:
    """An lgd_block filter the resolver never chose, naming no block of this
    scheme, goes (PLACE_GAZETTEER, D-059). "Total MGNREGA expenditure in Tura"
    resolved to West Garo Hills (Tura is its HQ; MGNREGA has no Tura block), and
    the 30B still wrote lgd_block = 'TURA' AND lgd_district = 'WEST GARO HILLS':
    null, "the data doesn't cover", for a district that spent 14,880.51 lakh
    (place hierarchy sweep 2026-10-21, KI-349). Only MGNREGA / PMAY-G (complete
    block catalogues), only when the resolver pinned a place of its own and no
    block, and only for a value that is no block of the scheme — a real block
    the generator added is left to the scope guards."""
    if not settings.PLACE_GAZETTEER or not sql or not schemes or schemes[0] not in ("MGNREGA", "PMAY-G"):
        return sql
    if resolved.get("block") or resolved.get("block_list"):
        return sql
    if not any(resolved.get(k) for k in ("district", "district_list", "village_code", "village_code_list",
                                         "assembly_constituency")):
        return sql
    from app import entity_resolver as _er
    own = {_er.fold(f) for v in (_er._catalog.get(schemes[0]) or {}).get("block", [])
           for f in _er._match_forms(v)}
    if not own:
        return sql

    def is_stray(c: exp.Expression) -> bool:
        if not isinstance(c, exp.EQ) or not sql_ast._is_column(c.this, {"lgd_block"}):
            return False
        vals = sql_ast._string_values(c.expression)
        return bool(vals) and all(_er.fold(v) not in own for v in vals)
    out = sql_ast.remove_conditions(sql, is_stray)
    if out != sql:
        logger.info("stray lgd_block filter (no %s block) dropped: %s", schemes[0], out.replace("\n", " "))
    return out


def _resolved_district_literal(resolved: dict, sql: str) -> str:
    """The one district the question resolved is the district the SQL filters.
    KI-327 (live 2026-10-19): "now give me for Dambo Rongjeng block" after a West
    Garo Hills village turn. The rewrite carried "West Garo Hills" into the text,
    entity resolution placed the block under its real district (East Garo Hills)
    and the 30B still wrote lgd_district = 'WEST GARO HILLS' from the question
    text: zero rows for a block that has data. An lgd_district = '<other>' literal
    is replaced by the resolved district. Only in that shape, a resolved BLOCK
    beside the district (the block is what pinned the district): a district-only
    mismatch is left to the scope guards, so a repair that moves the geography
    is still re-authorized and denied (KI-183, test_pipeline_graph) rather than
    silently corrected. IN-lists belong to the comparison rewrite above
    (district_list) and are left alone here."""
    want = resolved.get("district")
    if not isinstance(want, str) or not want.strip() or resolved.get("district_list") or not sql:
        return sql
    if not isinstance(resolved.get("block"), str) or not resolved["block"].strip():
        return sql
    want = want.strip().upper()
    seen: list = []

    def fn(tree):
        for node in sql_ast.filter_conditions(tree, "lgd_district"):
            if not isinstance(node, exp.EQ):
                continue
            sides = _sql_cond_sides(node, {"lgd_district"})
            lit = _sql_string_literal(sides[1]) if sides else None
            if lit is None or lit.strip().upper() == want:
                continue
            sql_ast._unwrap(sides[1]).replace(exp.Literal.string(want))
            seen.append(lit)
        return None

    out = sql_ast.transform(sql, fn)
    if seen:
        logger.info("lgd_district literal %r replaced by the resolved district %r", seen[0], want)
    return out


def _cm_unasked_programme_beside_village(question: str, schemes: list[str], entity_result: dict,
                                         sql: str) -> str:
    """A village name read as a programme (live 2026-10-02, all-villages run):
    "How many applications are there under CM Elevate Legacy in NOAGRE?" — the
    village resolved (village_code 273728) and the 30B wrote, on the first
    attempt and on all three repairs, WHERE scheme_name = 'Meghalaya New
    Agriculture and Allied Activities Scheme' (a name it built from the letters
    N-O-AGRE). A scheme_name = '…' filter is dropped when a village is resolved,
    no programme was resolved, and the question names no programme or family;
    _pin_missing_village_code then adds the village."""
    if schemes not in (["CM Elevate"], ["CM Elevate Legacy"]) or not sql:
        return sql
    resolved = entity_result.get("resolved") or {}
    if not resolved.get("village_code") or resolved.get("cm_scheme") or _CME_FAMILY_WORDS_MATCH.search(question or ""):
        return sql
    if resolve_cm_scheme(question, schemes[0]) is not None:
        return sql
    hits = _sql_string_comparisons(sql, ("scheme_name",), (exp.EQ,))
    if not hits:
        return sql
    lit = hits[0][2]

    def _is_that_filter(node) -> bool:
        return isinstance(node, exp.EQ) and any(
            n is node and v == lit for n, _c, v in _sql_string_comparisons(node, ("scheme_name",), (exp.EQ,)))
    # Not a stored programme at all: the village's own name written as one
    # ("…WHERE village_code = 279360 AND scheme_name = 'AMLARI MODEL'" — CM Elevate
    # Legacy all-villages re-run 2026-10-02, 9 villages answered 0). Dropped even
    # though the name is in the question: it is in the question AS THE VILLAGE.
    from app.entity_resolver import _catalog as _er_catalog
    _progs = {str(v.get("canonical", "")).strip().upper() for v in _er_catalog.get(schemes[0], {}).get("cm_scheme", [])}
    if _progs and lit.strip().upper() not in _progs:
        out = _drop_where_conditions(sql, _is_that_filter)
        if out != sql:
            logger.info("%s: dropped scheme_name = %r — not a programme (a place name)", schemes[0], lit)
        return out
    if _cme_question_names(lit, question or ""):     # its officer words, else its stored name
        return sql
    out = _drop_where_conditions(sql, _is_that_filter)
    if out != sql:
        logger.info("%s: dropped a programme filter beside a resolved village the question never named: %r",
                    schemes[0], lit)
    return out


def _pin_missing_village_code(schemes: list[str], entity_result: dict, sql: str) -> str:
    """The deterministic half of _village_filter_missing: a simple one-SELECT
    query over a resolved village that filters no village at all gets
    `village_code = <code>` added (every curated view carries it). The guard
    alone sent NOAGRE to "couldn't build a working query" — the 30B repeated the
    same village-less SQL on every repair. Anything more complex (a join, a
    CTE, a subquery) is left to the guard and the repair."""
    twins = _pin_missing_twin_codes(schemes, entity_result, sql)
    if twins != sql:
        return twins
    code = _village_filter_missing(schemes, entity_result, sql)
    if code is None:
        return _village_name_cond_to_code(schemes, entity_result, sql)
    if not _sql_is_simple_select(sql):
        return sql

    def fn(tree):
        cond = exp.EQ(this=exp.column("village_code"), expression=exp.Literal.number(int(code)))
        where = tree.args.get("where")
        if where is not None:
            # flat: village_code = X AND a AND b (not X AND (a AND b)), so each
            # conjunct stays droppable by _drop_geo_beside_pinned_village
            conjuncts = list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this]
            where.set("this", exp.and_(cond, *conjuncts, copy=False))
        else:
            tree.where(cond, copy=False)
        return None

    out = sql_ast.transform(sql, fn)
    logger.info("%s: the SQL filtered no village — pinned the resolved village_code %s", schemes[0], code)
    return _drop_geo_beside_pinned_village(out)


def _c10_group_by_cols(sql: str, cols: list) -> str:
    """A one-row aggregate (`SELECT COUNT(…) FROM t WHERE …`, no GROUP BY, no join) becomes
    one row per `cols`: they lead the SELECT and form the GROUP BY. Anything else: unchanged."""
    def fn(tree):
        if not isinstance(tree, exp.Select) or tree.args.get("group") is not None                 or tree.args.get("joins") or tree.args.get("with") is not None:
            return None
        if not any(e.find(exp.AggFunc) for e in tree.expressions):
            return None
        tree.set("expressions", [exp.column(c) for c in cols] + list(tree.expressions))
        tree.set("group", exp.Group(expressions=[exp.column(c) for c in cols]))
        return None
    return sql_ast.transform(sql, fn)


# UPPER( / TRIM( / an alias too: "WHERE UPPER(TRIM(lgd_district)) = 'KASHARIPARA'"
# (the village name in the district column, no village filter) got the code
# pinned but kept the district literal, which the old `UPPER(col)` check
# missed — 0 producer groups for a village with 11 (Focus Legacy all-villages
# re-run 2026-10-02).
def _is_geo_literal_eq(node) -> bool:
    """lgd_block / lgd_district = '<literal>' (either side wrapped or not)."""
    return isinstance(node, exp.EQ) and bool(
        _sql_string_comparisons(node, ("lgd_block", "lgd_district"), (exp.EQ,)))


def _drop_geo_beside_pinned_village(sql: str) -> str:
    # the village is the whole scope: a block / district literal beside it can
    # only narrow it wrongly (the same rule as _mgnrega_drop_geo_beside_village)
    return _drop_where_conditions(sql, _is_geo_literal_eq)


def _sql_replace_node(sql: str, target: "exp.Expression", new: "exp.Expression") -> str:
    """`sql` with the first node structurally equal to `target` replaced by `new`."""
    def fn(tree):
        for node in tree.walk(bfs=False):
            if type(node) is type(target) and node == target:
                node.replace(new.copy())
                break
        return None
    return sql_ast.transform(sql, fn)


def _village_name_cond_to_code(schemes: list[str], entity_result: dict, sql: str) -> str:
    """One resolved village the SQL names by TEXT only: the condition becomes
    `village_code = <code>`. "TEPORPARA ( UPPER )" (code 273637) was written as
    `UPPER(lgd_village_name) = 'TEPORPARA'` — the generator cut the name at the
    parenthesis — and matched a different village: 2 applications for a village
    with 1 (CM Elevate Legacy all-villages re-run 2026-10-02). The resolved code
    is the exact place; a name can be truncated, re-cased or shared by twins.
    Only a simple one-SELECT query with exactly one such condition and no
    village_code filter of its own."""
    if not sql or any(isinstance(n, (exp.EQ, exp.In)) for n in sql_ast.filter_conditions(sql, "village_code")):
        return sql
    conds = _sql_string_comparisons(sql, ("lgd_village_name",), (exp.EQ, exp.Like, exp.ILike))
    if len(conds) != 1:
        return sql
    cond = conds[0][0]
    code = _village_filter_missing(schemes, entity_result, _sql_replace_node(sql, cond, exp.true()))
    if code is None:
        return sql
    if not _sql_is_simple_select(sql):
        return sql
    out = _sql_replace_node(sql, cond, exp.EQ(this=exp.column("village_code"),
                                              expression=exp.Literal.number(int(code))))
    logger.info("%s: village named by text (%r) — replaced by the resolved village_code %s",
                schemes[0], sql_ast.to_sql(cond), code)
    return _drop_geo_beside_pinned_village(out)


def _pin_missing_twin_codes(schemes: list[str], entity_result: dict, sql: str) -> str:
    """_pin_missing_village_code / _village_name_cond_to_code for a J-10 twin list
    (D-089). MGNREGA UAT 2026-10-30 (KI-637): "What was the total expenditure in
    MEGAPGRE?" (three Megapgres) — the 30B filtered no village code on the first
    attempt and on all three repairs, the twins guard rejected each ("leaves out
    273473, 273920, 275787") and the officer got "couldn't build a working query".
    A simple one-SELECT query with no village_code filter gets `village_code IN
    (<every twin>)` — in place of a lgd_village_name text condition when there is
    exactly one, else added to the WHERE — and a block / district literal beside it
    goes (the villages are the whole scope). sql_ast.group_by_village then makes it
    one row per village."""
    resolved = entity_result.get("resolved") or {}
    codes = [int(c) for c in resolved.get("village_code_list") or []]
    if not sql or not codes or not resolved.get("village_twins") or len(schemes) != 1:
        return sql
    if any(isinstance(n, (exp.EQ, exp.In)) for n in sql_ast.filter_conditions(sql, "village_code")):
        return sql
    if not sql_ast.is_parseable(sql) or not _sql_is_simple_select(sql):
        return sql
    cond = exp.In(this=exp.column("village_code"), expressions=[exp.Literal.number(c) for c in codes])
    named = _sql_string_comparisons(sql, ("lgd_village_name",), (exp.EQ, exp.Like, exp.ILike))
    if len(named) == 1:
        out = _sql_replace_node(sql, named[0][0], cond)
        logger.info("%s: twins named by text (%r) — replaced by village_code IN (%s)", schemes[0],
                    sql_ast.to_sql(named[0][0]), ", ".join(map(str, codes)))
    elif named:
        return sql
    else:
        def fn(tree):
            where = tree.args.get("where")
            if where is not None:
                conjuncts = list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this]
                where.set("this", exp.and_(cond, *conjuncts, copy=False))
            else:
                tree.where(cond, copy=False)
            return None
        out = sql_ast.transform(sql, fn)
        logger.info("%s: the SQL filtered no village — pinned the twin codes IN (%s)", schemes[0],
                    ", ".join(map(str, codes)))
    return _drop_geo_beside_pinned_village(out)


_SHARED_GEO_COLS = ("lgd_district", "lgd_block", "lgd_village_name", "village_code",
                    "entity_type", "on_roster", "has_geo_conflict")


# app/pipeline/schemes/pmay_g.py — PMAY-G — village rules, fixed queries, typed turns and answer checks.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
# Only this scheme's code lives here; the shared steps that call it are in ../common/.
# Sections follow the order of the pipeline steps they belong to.
# SQL is read and rewritten on the SQLGlot tree (app/sql_ast), never as raw text.
from app import sql_ast
from sqlglot import exp
from app.text_match import (ANY, END, Alt, Before, Joined, Matcher, Node, Opt, Pred, Seq, W,
                             collapse_ws, is_int, is_year, tokens)


# ════ word-matching helpers (app/text_match) ══════════════════════════════════════════════════════════
def _pmay_is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


class _PmayNear(Node):
    """`a`, then `b` starting at most `chars` characters after `a` ends, with no
    character in between for which `bad` is true — e.g. no newline (the
    default), no ".", "?" or "!", or no "?" at any distance (chars=None)."""

    def __init__(self, a, b, chars: "int | None", bad=lambda ch: ch == "\n"):
        self.parts = [Seq(a), Seq(b)]
        self.a, self.b, self.chars, self.bad = self.parts[0], self.parts[1], chars, bad

    def ends(self, ctx, i, caps):
        for j, c in self.a.ends(ctx, i, caps):
            if j <= i:
                continue
            e = ctx.toks[j - 1].end
            for k in range(j, len(ctx.toks)):
                s = ctx.toks[k].start
                if self.chars is not None and s - e > self.chars:
                    break
                if any(self.bad(ch) for ch in ctx.text[ctx.toks[k - 1].end:s]):
                    break
                yield from self.b.ends(ctx, k, c)


class _PmayAdj(Node):
    """`a` then `b`, the text between them accepted by `ok` (e.g. exactly "." in "12.5k")."""

    def __init__(self, a, b, ok):
        self.parts = [Seq(a), Seq(b)]
        self.a, self.b, self.ok = self.parts[0], self.parts[1], ok

    def ends(self, ctx, i, caps):
        for j, c in self.a.ends(ctx, i, caps):
            if i < j < len(ctx.toks) and self.ok(ctx.gap(j)):
                yield from self.b.ends(ctx, j, c)


class _PmayCharAfter(Node):
    """`x`, provided the raw text right after it passes `ok` (e.g. "focus +")."""

    def __init__(self, x, ok):
        self.x = Seq(x)
        self.ok = ok

    def ends(self, ctx, i, caps):
        for j, c in self.x.ends(ctx, i, caps):
            if j > i and self.ok(ctx.text[ctx.toks[j - 1].end:]):
                yield j, c


def _pmay_misspelt_sanctioned() -> frozenset:
    """Every spelling "sa" + 1-2 of n/c + optional t, i + "o" + 1-2 n + optional e + "d" (sactioned, sancioned, …)."""
    out = set()
    for nc in ("n", "c", "nn", "nc", "cn", "cc"):
        for t in ("", "t"):
            for i in ("", "i"):
                for n in ("n", "nn"):
                    for e in ("", "e"):
                        out.add(f"sa{nc}{t}{i}o{n}{e}d")
    return frozenset(out)


def _pmay_instalment_word(w: str) -> bool:
    """instal+ments? (instalment, installments, installlment …)."""
    w = w.lower()
    if not w.startswith("insta"):
        return False
    rest = w[5:]          # the "l…" after "insta"
    tail = rest.lstrip("l")
    return len(rest) > len(tail) and tail in ("ment", "ments")


# ════ scheme terms ════════════════════════════════════════════════════════════════════════════════════
_PMAY_ONLY_TERMS = Matcher(Alt(
    W("house", "houses", "housing", "geotag", "awaas", "awas"),
    Seq("dwelling", W("unit", "units")), "pucca house", "kutcha house",
    Seq("sanctioned", W("house", "houses")),
    W("instalment", "instalments", "installment", "installments"),
    # "tranche"/"tranch" is deliberately NOT here, even though PMAY-G also has
    # an installments_paid column. Focus Plus's own vocabulary IS "tranche"
    # (its stored column is literally tranche_label); PMAY-G's own vocabulary
    # is "installment" (instal?ments? above already covers it). A bare
    # "tranche 1 vs tranche 2" with no scheme named should default to Focus
    # Plus, not pause — see _FOCUSPLUS_ONLY_TERMS below, which is where
    # "tranche" is claimed.
    "completion certificate", "house status",
    # "sanctioned"/"released"/"pending" amount phrasing is PMAY-specific — MGNREGA
    # never "sanctions" anything (it has expenditure), CM Elevate has no money
    # column at all, and Focus Plus vocabulary is "disbursement"/"payment", not
    # "sanctioned". Without these, a bare "how much sanctioned amount has been
    # released in [village]?" (no scheme named) fell through to an unnecessary
    # "which scheme?" pause instead of being understood as PMAY-G.
    # Plural "amounts"/"numbers" — the singular-only forms below missed
    # "sanctioned amountS" (PMAY-OFF-023) and "amount released" is fine as a
    # fixed phrase, but sanction NUMBER(S) (PMAY-OFF-026) had no matcher at all.
    # The first form tolerates the usual misspellings of "sanctioned" (sactioned,
    # sancioned, santioned, sanctoned, sanctiond) — the use-case sheet's own
    # "How much sactioned amount has been released" paused for a scheme
    # (PMAY-G QA 2026-09-28, PMAY-OFF-003).
    Seq(W(*_pmay_misspelt_sanctioned()), W("amount", "amounts")),
    Seq(W("amount", "amounts"), W("released", "sanctioned", "pending")),
    Seq(W("released", "pending"), W("amount", "amounts")),
    Seq("sanction", W("date", "dates", "number", "numbers")),
    # "received (any/the/no) amount", "received full/partial amount" — the
    # release-status phrasing PMAY-OFF-008/009/010 use, distinct from the
    # "amount released" form already covered above.
    Seq(W("receiv", prefix=True), Opt(W("any", "the", "no", "full", "partial")), Opt("sanctioned"), "amount"),
))


# ════ villages ════════════════════════════════════════════════════════════════════════════════════════
_PMAY_VILLAGE_NAMES: "dict[str, list[dict]] | None" = None


async def _pmay_village_names() -> "dict[str, list[dict]]":
    """UPPER(name) -> villages, for every village in v_pmay (≈4,900 names, 5,121
    codes). Loaded once per process. Placeholder rows are kept: a village whose
    only record is a zero-sanction placeholder (Rtiang Sanphew) is still a PMAY-G
    village, and its answer is a stated zero, not another village."""
    global _PMAY_VILLAGE_NAMES
    if _PMAY_VILLAGE_NAMES is None:
        rows = await fetch_rows(
            "SELECT DISTINCT village_code, lgd_village_name, UPPER(lgd_block) AS block, "
            "UPPER(lgd_district) AS district FROM curated.v_pmay WHERE village_code IS NOT NULL", [])
        out: dict[str, list[dict]] = {}
        for r in rows:
            n = collapse_ws(str(r["lgd_village_name"] or ""))
            if n and not n.lower().startswith("unresolved"):
                out.setdefault(n.upper(), []).append(
                    {"village_code": r["village_code"], "name": n, "block": r["block"], "district": r["district"]})
        _PMAY_VILLAGE_NAMES = out
    return _PMAY_VILLAGE_NAMES


def _pmay_ws1(s: str) -> str:
    """Every run of whitespace -> one space, not trimmed."""
    out, prev_ws = [], False
    for ch in s or "":
        if ch.isspace():
            if not prev_ws:
                out.append(" ")
            prev_ws = True
        else:
            out.append(ch)
            prev_ws = False
    return "".join(out)


def _pmay_az09(ch: str) -> bool:
    return "A" <= ch <= "Z" or "0" <= ch <= "9"


def _pmay_name_spans(q: str, name: str) -> "list[tuple[int, int]]":
    """Non-overlapping spans of `name` in `q` not touching another [A-Z0-9] on either
    side (a whole name, not inside a longer run of letters/digits; upper-cased text)."""
    out: list[tuple[int, int]] = []
    if not name:
        return out
    i = q.find(name)
    while i >= 0:
        e = i + len(name)
        if (i == 0 or not _pmay_az09(q[i - 1])) and (e == len(q) or not _pmay_az09(q[e])):
            out.append((i, e))
            i = q.find(name, e)
        else:
            i = q.find(name, i + 1)
    return out


def _pmay_followed_by_block(q: str, e: int) -> bool:
    """Whitespace, then the word BLOCK, right after position e (a whole word, not consumed)."""
    rest = q[e:]
    tail = rest.lstrip()
    return len(tail) < len(rest) and tail.startswith("BLOCK") and (len(tail) == 5 or not _pmay_is_word_char(tail[5]))


def _pmay_after_place_preposition(q: str, name: str) -> "list[tuple[int, int]]":
    """Spans of a short `name` written right after IN / OF / AT / FOR / FROM and one
    space (each a whole word, no letter/digit right after the name; upper-cased text)."""
    out = []
    i = q.find(name)
    while i >= 0:
        e = i + len(name)
        if i >= 1 and q[i - 1] == " " and (e == len(q) or not _pmay_az09(q[e])):
            for p in ("IN", "OF", "AT", "FOR", "FROM"):
                s = i - 1 - len(p)
                if s >= 0 and q[s:i - 1] == p and (s == 0 or not _pmay_is_word_char(q[s - 1])):
                    out.append((i, e))
                    break
        i = q.find(name, i + 1)
    return out


async def _pmay_village_beside_block(question: str, resolved: dict,
                                     scheme: str = "PMAY-G") -> "dict | None":
    """The ONE PMAY-G village a question names beside its own block / district —
    "…still to be released in NONGSOHRAM across all financial years, RI MULIANG
    block, WEST KHASI HILLS" resolved to the block (the word "block" sets the level)
    and answered with Ri Muliang's ₹33,84,000 instead of the village's figure
    (user report 2026-09-28). A match must be an exact PMAY-G village name found
    OUTSIDE the block / district mention (the block mention is "<block> block" when
    written so; "RONGJENG" inside "DAMBO RONGJENG block" is not a village) and lie in
    that block (and district). So "Umsning block" and "BATABARI block, WEST GARO
    HILLS" (the 2026-09-18 report: one mention, with "block") stay block questions,
    while "in DEMDEMA …, DEMDEMA block" (the name twice) and "RONGRAM BAZAR, RONGRAM
    block" are the village."""
    try:
        names = await _scheme_village_names(scheme)
    except Exception:  # noqa: BLE001
        return None
    blk = str(resolved.get("block") or "").strip().upper()
    dist = str(resolved.get("district") or "").strip().upper()
    q = _pmay_ws1(_CHIP_LGD_CODE_MATCH.sub(" ", question or "").upper())
    # The block mention is "<block> block" when the text says so; a bare repeat of
    # the same name before it is then the village ("in DEMDEMA …, DEMDEMA block").
    area_spans = []
    if blk:
        _bs = []
        _i = q.find(blk)
        while _i >= 0:     # whole-name BLK, then spaces + the word BLOCK, non-overlapping
            _e = _i + len(blk)
            if (_i == 0 or not _pmay_az09(q[_i - 1])) and _pmay_followed_by_block(q, _e):
                _bs.append((_i, _e))
                _i = q.find(blk, _e)
            else:
                _i = q.find(blk, _i + 1)
        area_spans += _bs or _pmay_name_spans(q, blk)
    if dist:
        area_spans += _pmay_name_spans(q, dist)
    best = None
    for n, cands in names.items():
        # A village named like the very block / district it is asked beside is
        # ambiguous (the 2026-09-18 BATABARI rule); named like ANOTHER block
        # ("MAWLAI …, SHALLANG block") it can only be the village.
        if len(n) < 3 or n not in q or (best and len(n) <= len(best[0])):
            continue
        # a 3-letter name (BIR, KUT) only right after a place preposition, as in
        # _mgnrega_longest_village_in, so an ordinary word is never a village
        spans = _pmay_after_place_preposition(q, n) if len(n) == 3 else _pmay_name_spans(q, n)
        spans = [(x, y) for x, y in spans if not any(ax <= x and y <= ay for ax, ay in area_spans)]
        if not spans:
            continue
        keep = [c for c in cands if (not blk or str(c.get("block") or "").upper() == blk)
                and (not dist or str(c.get("district") or "").upper() == dist)]
        if keep:
            best = (n, keep)
    if not best or len({c["village_code"] for c in best[1]}) != 1:
        return None
    return best[1][0]


_PMAY_COMPARE_CUE_MATCH = Matcher(Alt(Seq("which", "has", W("more", "less", "fewer", "higher", "lower")),
                                    W("compar", prefix=True), W("versus", "vs")))


async def _pmay_two_villages(question: str) -> "list[dict] | None":
    """The two PMAY-G villages an "A or B" / "compare A and B" question names, when
    both are exact PMAY-G village names with one code each and neither is a block
    or district name. "Which has more completed houses: Nongtalang Mission or Sohkha
    Mission?" put one name in the block slot and the model compared a village with
    lgd_block = 'SOHKHA MISSION' (PMAY-G scenario run 2026-09-28)."""
    try:
        names = await _pmay_village_names()
    except Exception:  # noqa: BLE001
        return None
    admin = {str(c).strip().upper() for d in ("block", "district") for c in canonical_names("PMAY-G", d)}
    q = _pmay_ws1((question or "").upper())
    # The user already chose the village reading of a name that is also a block
    # ("The LASKEIN village" chip: "…PECHUA or LASKEIN, the village, not the
    # block"). Without this LASKEIN stayed a block, the comparison became
    # village + block, and the SQL repairs ran out — "couldn't build a working
    # query", or PECHUA alone (PMAY-G officer cases run 2026-10-02, OFF-022).
    # ", THE VILLAGE, NOT THE BLOCK" / "…NOT ANOTHER AREA TYPE" (space after the comma optional)
    _chips = [f"{c}THE VILLAGE, NOT {t}" for c in (", ", ",") for t in ("THE BLOCK", "ANOTHER AREA TYPE")]
    chose_village = any(c in q for c in _chips)
    for _c in _chips:
        q = q.replace(_c, "")
    taken: list[tuple[int, int]] = []
    found: list[dict] = []
    for n in sorted(names, key=len, reverse=True):
        if len(n) < 4 or n not in q or (n in admin and not chose_village):
            continue
        for ms, me in _pmay_name_spans(q, n):
            if any(not (me <= x or ms >= y) for x, y in taken):
                continue
            taken.append((ms, me))
            cands = names[n]
            if len({c["village_code"] for c in cands}) != 1:
                return None            # a twin name: the normal village pause handles it
            found.append(cands[0])
            break
    uniq = {c["village_code"]: c for c in found}
    return list(uniq.values()) if len(uniq) == 2 else None


# ════ fixed-shape queries and answers ═════════════════════════════════════════════════════════════════
# ---------------------------------------------------------------------------
# PMAY-G deterministic facts (PMAY-G use-case QA 2026-09-28, KI-089..KI-095).
#
# The use-case sheet's PMAY-G questions are fixed shapes over ONE view
# (curated.v_pmay, one row = one house): counts, money, stage breakdowns,
# release status, rates, summaries and A-vs-B comparisons for a village / block /
# district / the state, optionally in one FY or on one date. Put to the 30B, 11
# of 28 use cases failed on sampling alone: "financial summary" grouped by year
# and reported a sum of ROUNDED yearly crore as "sanctioned credit released"
# (012), comparisons came back as per-year row dumps or invented statistics
# ("38,899 for both districts", 023b/024b), utilisation was AVG(released) /
# AVG(sanctioned) (016), "which has more" got LIMIT 1 (022b), the remaining
# amount / difference / sanctioned amount were dropped (012/016/023/024/025) and
# a village's ₹9,40,000 read "0.09 crore" (007). For these shapes the query and
# the wording are both built here, parameter-bound, from the resolved filters —
# the same approach as _mgnrega_combined_facts_query. Anything else (rankings,
# "each district", trends, allotment, instalments, averages, names) is left to
# the model path, which has its own guards (_pmay_sql_issue / _pmay_comparison_limit).

_PMAY_DET_KEYS = {"village_code", "village_code_list", "block", "block_list", "block_list_districts",
                  "district", "district_list", "district_list_region", "year_key", "house_status"}
# Shapes the deterministic path does not answer (the model path keeps them).
def _pmay_p(*options: str) -> W:
    """A word starting with any of `options` (the stem, then any more letters or none)."""
    return W(*options, prefix=True)


def _pmay_date_head(w: str) -> bool:
    """1-2 digits, or "fy" + 1-2 digits (the first number of a date like 12/05)."""
    d = w[2:] if w.lower().startswith("fy") else w
    return is_int(d) and 1 <= len(d) <= 2


_PMAY_MONTH_WORDS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
def _pmay_s(*parts) -> Seq:
    """Words in a row with only whitespace between them (no punctuation)."""
    return Seq(*parts, sep="space")


_PMAY_DET_EXCLUDE_MATCH = Matcher(Alt(
    W("each", "every"),
    _pmay_s("per", W("district", "block", "village", "year", "month", "house", "beneficiary")),
    _pmay_s("by", Alt(W("district", "block", "village", "year", "month", "fy", "date", "gender", "allotment"),
                  _pmay_s("financial", "year"))),
    Joined(("district", "block", "village", "year", "month", "date", "gender"), "wise"),
    W("monthly", "month", "months", "weekly"), _pmay_p("quarter"),
    _pmay_p("trend"), _pmay_s("over", "time"), W("growth"), _pmay_p("increase", "decrease", "declin"),
    W("change", "changes", "changed"),
    W("top", "bottom", "list", "lists", "listing", "names"), _pmay_p("rank"), _pmay_s("name", W("the", "all")),
    W("average", "avg", "mean", "median", "typical"),
    W("woman", "women", "female", "male", "husband", "wife", "joint", "gender"), _pmay_p("widow", "allot"),
    Pred(_pmay_instalment_word), W("tranche", "tranches"),
    Joined(("reg", "registration"), ("no", "nos", "number", "numbers")),
    W("mapping", "mapped", "fuzzy", "placeholder", "placeholders", "missing", "null"), _pmay_s("data", "quality"),
    _pmay_p("duplicate"),
    _pmay_s(W("between", "from", "since", "before", "after", "until"), Opt("the"), Alt(
        _pmay_s(Opt("fy"), Pred(is_year)),
        Pred(lambda w: w.lower().startswith("fy") and is_year(w[2:])),
        _pmay_s(Opt("fy"), _PmayAdj(Pred(_pmay_date_head), ANY, lambda g: g in ("/", ".", "-"))),
        W(*_PMAY_MONTH_WORDS))),
    _pmay_s("calendar", "year"), _pmay_s("in", "progress"), W("ongoing"), _pmay_s("under", "construction"),
    W("mgnrega", "focus", "elevate"), _pmay_s(W("scheme", "schemes"), W("compare", "vs")), Joined("cross", "scheme"),
))
# Ranking words: a ranking over every area is the model path's; between the
# entities the question names ("which has more: A or B") it is a comparison.
# Counting or listing areas themselves ("how many villages …") — the model path's.
_PMAY_AREA_PLURAL_MATCH = Matcher(W("villages", "blocks", "districts"))
_PMAY_RANK_MATCH = Matcher(W("which", "highest", "lowest", "most", "least", "maximum", "minimum", "max", "min",
                          "best", "worst"))
# _PMAY_M runs on the question with "%" written as the word _pct_ and "₹" as _rs_
# (_pmay_metric_text), so the symbols can be matched as words. Character windows
# (at most N characters apart) are _PmayNear; a window ending at a symbol is one character
# longer, because the symbol's word starts one character later.
_PMAY_PCT, _PMAY_RS = "_pct_", "_rs_"
_PMAY_RATE_WORDS = Alt(_pmay_p("percent"), W("share", "proportion", "ratio", "rate"))
_PMAY_M = {
    "fin_summary": Matcher(Alt(
        Seq("financial", _pmay_p("summary", "position", "status", "overview", "detail", "picture", "progress",
                                 "report")),
        Seq(W("fund", "funds"), _pmay_p("summary", "status", "position", "flow")),
        Seq("money", _pmay_p("summary")), Seq("finance", _pmay_p("summary")))),
    "performance": Matcher(Alt(
        W("performance", "performing", "summary", "overview"),
        Seq("overall", _pmay_p("status", "progress", "picture", "position", "summary", "figures")),
        Seq("progress", _pmay_p("report", "summary")), Seq("status", _pmay_p("report")),
        Seq("key", _pmay_p("figures", "numbers", "indicators", "statistics")),
        _PmayNear(Seq("how", W("is", "are")), W("doing"), 60))),
    "status": Matcher(Alt(
        Seq("status", _pmay_p("breakdown", "wise", "distribution", "split", "summary", "position")),
        _pmay_p("statusbreakdown", "statuswise", "statusdistribution", "statussplit", "statussummary",
                "statusposition"),
        _PmayNear(Alt(W("breakdown"), Seq("break", "down")), _pmay_p("status", "stage"), 40),
        "house status", Seq("construction", _pmay_p("stage", "status")),
        Seq(W("stage", "stages"), _pmay_p("wise")), _pmay_p("stagewise", "stageswise"),
        Seq(W("stage", "stages"), "of", _pmay_p("construction")),
        Seq(W("breakdown", "split", "distribution"), W("by", "across"), _pmay_p("stage", "status")),
        Seq(W("house", "houses"), Alt("by", "at each"), _pmay_p("stage", "status")),
        Seq("stage", _pmay_p("breakdown")))),
    "full_not_done": Matcher(_PmayNear(
        Alt(_pmay_p("full"), W("entire", "whole"), Seq("complete", Opt("sanctioned"), _pmay_p("amount"))),
        Alt(Seq(Pred(lambda w: w.lower().endswith("not")), Opt("yet"), Opt("been"), _pmay_p("complet")),
            Pred(lambda w: "incomplete" in w.lower()),
            Seq(Pred(lambda w: w.lower().endswith("still")), _pmay_p("not")),
            Pred(lambda w: "unfinished" in w.lower()),
            Seq(Pred(lambda w: w.lower().endswith("not")), _pmay_p("finished"))), 80)),
    "none": Matcher(Alt(
        Seq("not", Opt("yet"), "received", _pmay_p("any")),
        # "releas": "received no release at all" fell through to the statewide summary
        # (houses, sanctioned, released) instead of this count (KI-573, 2026-10-29).
        Seq(Alt(W("received", "got"), Seq("been", W("paid", "released"))),
            Alt(_pmay_p("nothing"), Seq("no", _pmay_p("amount", "money", "fund", "payment", "instal", "releas")))),
        Seq("no", W("amount", "amounts", "money", "moneys", "fund", "funds", "fundss", "payment", "payments",
                    "release", "releases"),
            Opt(W("has", "have")), Opt("yet"), Opt("been"), _pmay_p("received", "released", "paid")),
        Seq("nothing", Opt(Alt("has been", "was", "yet")), _pmay_p("released", "received", "paid")),
        Seq("zero", _pmay_p("amount", "release", "payment")),
        Seq("not", Opt("been"), W("paid", "released"), _pmay_p("any", "anything")),
        Seq("without", Opt("any"), _pmay_p("release", "payment", "money")),
        W("unpaid"))),
    "part": Matcher(Alt(
        _PmayNear(W("part", "partial", "partially", "partly"),
                  _pmay_p("amount", "sanction", "releas", "paid", "payment"), 40),
        Seq("only", Opt("a"), "part"),
        Seq("not", Opt("the"), "full", _pmay_p("amount", "release", "payment")),
        Seq("some", "but", "not", _pmay_p("all")))),
    "full": Matcher(Alt(
        _PmayNear(W("full", "fully"), _pmay_p("amount", "sanction", "releas", "paid", "payment", "funded"), 40),
        Seq(W("entire", "whole"), Opt("sanctioned"), _pmay_p("amount")),
        Seq("received", W("their", "the"), W("full", "entire", "whole", "complete")),
        Seq("100", _PMAY_PCT, Opt("of"), Opt("the"), Opt("amount"), _pmay_p("releas")))),
    "sanction_numbers": Matcher(Alt(
        Seq("sanction", W("number", "numbers", "no", "nos", "order", "orders")),
        Seq(W("unique", "distinct"), W("sanction", "sanctions")))),
    "completion_pct": Matcher(Alt(
        _PmayNear(_PMAY_RATE_WORDS, _pmay_p("complet"), 60),
        _PmayNear(_pmay_p("complet"), Alt(_pmay_p("percent"), W("rate", "ratio", "share")), 40),
        _PmayNear(_pmay_p("complet"), _PMAY_PCT, 41))),
    "release_pct": Matcher(Alt(
        _PmayNear(_PMAY_RATE_WORDS, _pmay_p("releas", "disburs", "utilis", "utiliz", "paid"), 60),
        _PmayNear(_pmay_p("releas", "disburs"), _pmay_p("percent"), 40),
        _PmayNear(_pmay_p("releas", "disburs"), _PMAY_PCT, 41),
        W("utilisation", "utilization", "utilised", "utilized"))),
    "remaining": Matcher(Alt(
        Seq(W("still", "yet"), "to", "be", _pmay_p("released", "paid", "disbursed")),
        Seq("to", "be", _pmay_p("released")),
        W("remaining", "balance", "gap", "outstanding", "unreleased"),
        Seq("not", Opt("yet"), Opt("been"), "released"),
        Seq("pending", _pmay_p("amount", "release", "money", "fund", "payment")),
        "amount pending", Seq("still", W("due", "pending")),
        Seq("left", "to", Opt("be"), _pmay_p("releas")))),
    "released": Matcher(Alt(
        _pmay_p("releas", "disburs"), "paid out", W("spent", "spending", "expenditure", "outlay"), "amount paid")),
    "sanctioned": Matcher(Alt(
        _PmayNear(W("amount", "amounts", "money", "fund", "funds", "rupees", "value"), _pmay_p("sanction"), 40),
        Seq(_pmay_p("sanction"), W("amount", "amounts", "money", "fund", "funds", "value")),
        _PmayNear(Seq("how", "much"), _pmay_p("sanction"), 40),
        _PmayNear(W(_PMAY_RS), Pred(lambda w: "sanction" in w.lower()), 21))),
    "incomplete": Matcher(Alt(
        W("incomplete", "unfinished"), Seq("not", Opt("yet"), Opt("been"), _pmay_p("complet")),
        Seq("pending", W("house", "houses")), "not finished")),
    "completed": Matcher(W("completed", "complete", "completion", "finished", "built")),
    "houses": Matcher(Alt(
        _PmayNear(Alt("how many", "number of", "no of", "count of", "total number", "count"),
                  Alt(_pmay_p("beneficiar"), W("house", "houses", "home", "homes", "household", "households",
                                               "dwelling", "dwellings")), 60),
        _PmayNear(Alt(_pmay_p("beneficiar"), W("house", "houses")), Alt("are there", "count"), 30))),
    "compare": Matcher(Alt(_pmay_p("compar"), W("versus", "vs", "difference", "against"))),
}


def _pmay_metric_text(q: str) -> str:
    """The question as _PMAY_M reads it: "%" and "₹" as the words _pct_ / _rs_."""
    return (q or "").replace("%", f" {_PMAY_PCT} ").replace("₹", f" {_PMAY_RS} ")
_PMAY_STAGE_ORDER = ["Completed", "Roof Cast", "Plinth", "House Sanctioned", "Existing site(Old House)",
                     "Proposed Site"]
_PMAY_STAGE_COL = {"Completed": "st_completed", "Roof Cast": "st_roof_cast", "Plinth": "st_plinth",
                   "House Sanctioned": "st_house_sanctioned", "Existing site(Old House)": "st_existing_site",
                   "Proposed Site": "st_proposed_site"}
_PMAY_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _pmay_numeric_date(t: str) -> "list[str] | None":
    """'2023-05-01' / '01/05/2023' / '1.5.2023' -> its three digit runs (separators - / .), else None."""
    parts, i, n = [], 0, len(t)
    while True:
        j = i
        while j < n and t[j].isdecimal():
            j += 1
        if j == i:
            return None
        parts.append(t[i:j])
        if j == n:
            break
        if t[j] not in "-/." or len(parts) == 3:
            return None
        i = j + 1
    return parts if len(parts) == 3 else None


def _pmay_is_full_year(s: str) -> bool:
    return len(s) == 4 and s[:2] in ("19", "20", "21") and s.isdecimal()


def _pmay_day_word(raw: str, last_two: bool) -> "str | None":
    """'15' / '15th' / '1st' -> the day digits (the last two of a longer run when last_two)."""
    k = 0
    while k < len(raw) and raw[k].isdecimal():
        k += 1
    digits, suffix = raw[:k], raw[k:]
    if not digits or suffix not in ("", "st", "nd", "rd", "th"):
        return None
    if last_two:
        return digits[-2:]
    return digits if len(digits) <= 2 else None


def _pmay_written_date(t: str, day_first: bool) -> "tuple[str, str, str] | None":
    """(day, month's first three letters, year) of a written date in lower-case `t`:
    '15th of may, 2023' (day_first) or 'may 15, 2023'."""
    toks = tokens(t)
    n = len(toks)

    def gap(m: int) -> str:
        return t[toks[m - 1].end:toks[m].start]

    def ws(g: str) -> bool:
        return g != "" and g.isspace()

    def month(m: int) -> bool:
        w = toks[m].raw
        return len(w) >= 3 and w.isascii() and w.isalpha()

    def year(m: int) -> "str | None":
        w = toks[m].raw
        return w[:4] if len(w) >= 4 and w[:4].isdecimal() else None

    for k in range(n):
        if day_first:
            d = _pmay_day_word(toks[k].raw, True)
            if d is None or k + 1 >= n or not ws(gap(k + 1)):
                continue
            m = k + 1
            if toks[m].low == "of" and m + 1 < n and ws(gap(m + 1)):
                m += 1
            if not month(m) or m + 1 >= n:
                continue
            g = gap(m + 1)
            g = g[1:] if g.startswith(".") else g
            g = g[1:] if g.startswith(",") else g
            y = year(m + 1) if ws(g) else None
            if y:
                return d, toks[m].raw[:3], y
        else:
            if not month(k) or k + 2 >= n:
                continue
            g = gap(k + 1)
            g = g[1:] if g.startswith(".") else g
            d = _pmay_day_word(toks[k + 1].raw, False)
            if not ws(g) or d is None:
                continue
            g = gap(k + 2)
            g = g[1:] if g.startswith(",") else g
            y = year(k + 2) if ws(g) else None
            if y:
                return d, toks[k].raw[:3], y
    return None


def _pmay_date(question: str):
    """The single calendar date a question names (ISO, dd/mm/yyyy or written), else None."""
    import datetime as _dt
    m = _CALENDAR_DATE_MATCH.search(question or "")
    if not m:
        return None
    t = m.group(0).lower()
    try:
        g = _pmay_numeric_date(t)
        if g and _pmay_is_full_year(g[0]) and len(g[1]) <= 2 and len(g[2]) <= 2:
            return _dt.date(int(g[0]), int(g[1]), int(g[2]))
        if g and len(g[0]) <= 2 and len(g[1]) <= 2 and _pmay_is_full_year(g[2]):   # Indian convention: day first
            return _dt.date(int(g[2]), int(g[1]), int(g[0]))
        w = _pmay_written_date(t, True)
        if w:
            return _dt.date(int(w[2]), _PMAY_MONTHS[w[1]], int(w[0]))
        w = _pmay_written_date(t, False)
        if w:
            return _dt.date(int(w[2]), _PMAY_MONTHS[w[1]], int(w[0]))
    except (ValueError, KeyError):
        return None
    return None


# Whole words amount / money / fund(s) / rupees / "how much". A lone "₹" is not a
# word, so it never matched before and is left out here.
_PMAY_MONEY_WORD_MATCH = Matcher(Alt(W("amount", "money", "fund", "funds", "rupees"), "how much"))


def _pmay_metrics(question: str, list_scope: bool) -> "list[str] | None":
    """The PMAY-G facts a question asks for, in answer order, or None when the
    question is not one of the fixed shapes this path answers."""
    q = question or ""
    # The year-pause chip appends "across all financial years"; it scopes, it asks nothing.
    q = _PMAY_ALL_YEARS_CHIP_MATCH.sub(" ", q)
    if _PMAY_DET_EXCLUDE_MATCH.search(q):
        return None
    if not list_scope and (_PMAY_RANK_MATCH.search(q) or _PMAY_AREA_PLURAL_MATCH.search(q)):
        return None
    qm = _pmay_metric_text(q)
    M = {k: bool(word_matcher.search(qm)) for k, word_matcher in _PMAY_M.items()}
    out: list[str] = []
    if M["fin_summary"]:
        # "financial summary" = sanctioned, released, remaining (PMAY-OFF-012/016). The
        # house count and release % were extra lines nobody asked for (user, 2026-09-28).
        return ["sanctioned", "released", "remaining"]
    if M["performance"] and not M["status"]:
        # "overall performance" = beneficiaries, sanctioned, released, completed (PMAY-OFF-019/024)
        return ["houses", "sanctioned", "released", "completed"]
    if M["status"]:
        out.append("status")
    release_counts = False
    if M["full_not_done"]:
        out.append("full_not_done"); release_counts = True
    else:
        if M["none"]:
            out.append("none"); release_counts = True
        if M["part"]:
            out.append("part"); release_counts = True
        if M["full"] and not M["part"]:
            out.append("full"); release_counts = True
    if M["sanction_numbers"]:
        out.append("sanction_numbers")
    if M["completion_pct"]:
        out.append("completion_pct")
    if M["release_pct"]:
        out.append("release_pct")
    if not release_counts and not M["release_pct"]:
        if M["remaining"] and (M["released"] or M["sanctioned"]
                               or _PMAY_MONEY_WORD_MATCH.search(q)):
            out.append("remaining")
        elif M["released"]:
            out.append("released")
        if M["sanctioned"] and "remaining" not in out and "released" not in out:
            out.append("sanctioned")
    if not M["completion_pct"] and "status" not in out and "full_not_done" not in out:
        if M["incomplete"]:
            out.append("incomplete")
        elif M["completed"] and not release_counts:
            out.append("completed")
    if M["houses"] and not any(m in out for m in ("completed", "incomplete", "status", "full_not_done",
                                                  "none", "part", "full", "sanction_numbers")):
        out.insert(0, "houses")
        if "released" in out and "sanctioned" not in out:
            # "How many houses were sanctioned and how much was released" — the
            # use case (025) expects the sanctioned amount beside the release.
            out.insert(out.index("released"), "sanctioned")
    if not out and list_scope and M["compare"]:
        return ["houses", "sanctioned", "released", "completed"]
    return list(dict.fromkeys(out)) or None


# "Financial summary" (PMAY-OFF-012/016) and "(overall) performance" (019/024) are figures this
# file answers, not a place overview. The overview (c15, D-052) rewrote them to "PMAY-G house
# status in <place>": 019 gave every district a status breakdown, the "till date" was dropped
# (so the year was asked) and "Amlarem block" came back as the village (sheet run 2026-10-22).
_PMAY_NAMED_SUMMARY_MATCH = Matcher(Alt(W("performance", "performing"),
                                        Seq("overall", _pmay_p("status", "progress", "picture", "position",
                                                                "summary", "figures"))))


def _pmay_named_summary(question: str) -> bool:
    """The question asks for PMAY-G's financial summary or performance figures."""
    return bool(_PMAY_M["fin_summary"].search(question or "")
                or _PMAY_NAMED_SUMMARY_MATCH.search(question or ""))


# A capitalised word after "in / at / for / of" that is not the scheme or a year:
# a place the resolver did not settle. Never answer that as a statewide figure.
def _pmay_unsettled_place_word(w: str) -> bool:
    """A capitalised word ([A-Z][A-Za-z]…) that is not PMAY / FY / Meghalaya / The / All / Each."""
    return (len(w) >= 2 and "A" <= w[0] <= "Z" and w[1].isascii() and w[1].isalpha()
            and not w.startswith(("PMAY", "Pmay", "FY", "Meghalaya", "MEGHALAYA"))
            and w not in ("The", "All", "Each"))


# Case-sensitive, as before: lower-case "in / at / for / of / under", then whitespace.
_PMAY_UNSETTLED_PLACE_MATCH = Matcher(Seq(W("in", "at", "for", "of", "under", case=True),
                                       Pred(_pmay_unsettled_place_word), sep="space"))
# ("state level" / "state-level" already match on the word "state")
_PMAY_STATEWIDE_MATCH = Matcher(Alt(W("meghalaya", "state", "statewide", "statelevel", "whole", "entire"), "all of"))


# A bare four-digit year ("sanctioned in 2023"), not an FY form ("2023-24", "FY 2023").
def _pmay_bare_year(text: str) -> "tuple[int, int] | None":
    """(start, year) of the first 201x-203x written alone — no digit, '/', '.' or '-' touching
    it on either side (2010-2039, four digits standing alone)."""
    t = text or ""

    def touching(ch: str) -> bool:
        return ch.isdecimal() or ch in "/.-"

    for i in range(len(t) - 3):
        y = t[i:i + 4]
        if y[:2] == "20" and y[2] in "123" and y[3].isdecimal() and y.isascii() \
                and (i == 0 or not touching(t[i - 1])) and (i + 4 == len(t) or not touching(t[i + 4])):
            return i, int(y)
    return None


def _pmay_unknown_place_noted(note: "str | None") -> bool:
    """A resolver note saying a place was not found (not a known / not found / no such /
    isn't a known / not in the), any case."""
    low = (note or "").lower()
    if any(s in low for s in ("not a known", "not found", "no such", "not in the")):
        return True
    i = low.find("isn")
    while i >= 0:
        if i + 4 < len(low) and low[i + 3] != "\n" and low.startswith(" a known", i + 4):
            return True
        i = low.find("isn", i + 1)
    return False


def _pmay_ends_with_village(s: str) -> bool:
    """The text ends with the whole word 'village', any case."""
    s = s[:-1] if s.endswith("\n") else s
    return s.lower().endswith("village") and (len(s) == 7 or not _pmay_is_word_char(s[-8]))


def _pmay_ends_with_fy(text: str) -> bool:
    """The text ends with the word 'fy', then optional spaces and one optional "'"."""
    s = text[:-1] if text.endswith("'") else text
    s = s.rstrip()
    return s.lower().endswith("fy") and (len(s) == 2 or not _pmay_is_word_char(s[-3]))


# The text the user typed this turn, when the follow-up rewrite changed it. "and how many
# received only part of it?" was rewritten to "…have not received any amount … and how many
# received only part of it?" and the answer repeated the previous figure (user, 2026-09-28).
_PMAY_TYPED_TURN: "contextvars.ContextVar[str | None]" = contextvars.ContextVar("_PMAY_TYPED_TURN", default=None)


def _pmay_facts_query(question: str, schemes: list[str], resolved: dict,
                      notes: "list[str] | None" = None, calendar_year: "int | None" = None) -> "dict | None":
    """Parameter-bound query + answer spec for a fixed-shape PMAY-G question, else None.
    `calendar_year` filters sanction_date to that calendar year instead of year_key."""
    if schemes != ["PMAY-G"]:
        return None
    if any(v not in (None, "", [], {}) for k, v in resolved.items() if k not in _PMAY_DET_KEYS):
        return None
    yk = resolved.get("year_key")
    if yk is not None and not isinstance(yk, int):
        return None
    if resolved.get("village_code") is not None:
        dim, ents = "village", [resolved["village_code"]]
    elif resolved.get("village_code_list"):
        dim, ents = "village", list(resolved["village_code_list"])
    elif resolved.get("block"):
        dim, ents = "block", [resolved["block"]]
    elif resolved.get("block_list"):
        dim, ents = "block", list(resolved["block_list"])
    elif resolved.get("district"):
        dim, ents = "district", [resolved["district"]]
    elif resolved.get("district_list"):
        if resolved.get("district_list_region"):
            return None   # "Garo Hills" region expansion: a sum over districts, not a comparison
        dim, ents = "district", list(resolved["district_list"])
    else:
        # statewide only when no place was left unresolved (an unknown village
        # must never be answered with Meghalaya's total)
        if any(_pmay_unknown_place_noted(n) for n in (notes or [])):
            return None
        if not _PMAY_STATEWIDE_MATCH.search(question or "") and _PMAY_UNSETTLED_PLACE_MATCH.search(question or ""):
            return None
        dim, ents = "state", ["MEGHALAYA"]
    if any(isinstance(e, (list, dict, set, tuple)) for e in ents) or len(ents) > 6:
        return None
    metrics = _pmay_metrics(question, len(ents) > 1)
    if not metrics:
        return None
    _typed = _PMAY_TYPED_TURN.get()
    if _typed and _typed != question:
        _own = _pmay_metrics(_typed, len(ents) > 1)
        if _own and set(_own) < set(metrics):
            metrics = _own
    day = _pmay_date(question)
    # A year the user typed is never dropped. "How many PMAY houses were sanctioned in
    # 2023?" left year_key unresolved and this path answered for ALL years (170,981;
    # 21 Sep test-sheet recheck, 2026-09-28). A bare year is read as FY 2023-24, the
    # project convention (year_key); the answer adds the calendar-year figure too,
    # because pmay_entity_resolver.yaml reads "sanctioned in 2023" as calendar 2023.
    bare_year = None
    if day is None and calendar_year is None:
        _bm = _pmay_bare_year(question or "")
        if _bm and not _pmay_ends_with_fy((question or "")[:_bm[0]]):
            bare_year = _bm[1]
        if yk is None:
            yk = _parse_year_key(question or "")
    hs = resolved.get("house_status")
    stages = [hs] if isinstance(hs, str) else list(hs or [])
    if any(s not in _PMAY_STAGE_COL for s in stages):
        return None

    params: list = []
    # The 126 zero-sanction registrations (is_placeholder: no year, no sanction number,
    # ₹0) ARE beneficiaries (user rule 2026-10-22, D-060): every count includes them. They
    # carry no year or date, so a year / date question is unchanged. "Received the full
    # sanctioned amount" needs a sanctioned amount (> 0) — ₹0 released of ₹0 is not a full release.
    where: list[str] = []
    if dim == "village":
        params.append([int(e) for e in ents]); where.append(f"village_code = ANY(${len(params)}::int[])")
        key, name = "village_code", "MAX(lgd_village_name) AS name, MAX(lgd_block) AS block, MAX(lgd_district) AS district"
    elif dim == "block":
        params.append([str(e).upper() for e in ents]); where.append(f"UPPER(lgd_block) = ANY(${len(params)}::text[])")
        key, name = "UPPER(lgd_block)", "MAX(lgd_block) AS name, MAX(lgd_district) AS district"
    elif dim == "district":
        params.append([str(e).upper() for e in ents]); where.append(f"UPPER(lgd_district) = ANY(${len(params)}::text[])")
        key, name = "UPPER(lgd_district)", "MAX(lgd_district) AS name"
    else:
        key, name = "'MEGHALAYA'", "'Meghalaya' AS name"
    if day is not None:
        params.append(day); where.append(f"sanction_date = ${len(params)}")
    elif calendar_year is not None:
        import datetime as _dt
        params.append(_dt.date(calendar_year, 1, 1)); where.append(f"sanction_date >= ${len(params)}")
        params.append(_dt.date(calendar_year + 1, 1, 1)); where.append(f"sanction_date < ${len(params)}")
    elif yk is not None:
        params.append(yk); where.append(f"year_key = ${len(params)}")
    if stages:
        params.append(stages); where.append(f"status_name = ANY(${len(params)}::text[])")
    rel = "COALESCE(amount_released, 0)"
    cols = [
        f"{key} AS entity_key", name,
        "COUNT(*) AS houses",
        "COALESCE(SUM(sanctioned_amount), 0) AS sanctioned",
        f"COALESCE(SUM({rel}), 0) AS released",
        f"COALESCE(SUM({rel}) FILTER (WHERE sanctioned_amount > 0), 0) AS released_on_sanctioned",
        "COALESCE(SUM(sanctioned_amount) FILTER (WHERE sanctioned_amount > 0), 0) AS sanctioned_positive",
        "COUNT(*) FILTER (WHERE is_completed) AS completed",
        "COUNT(*) FILTER (WHERE NOT COALESCE(is_completed, FALSE)) AS incomplete",
        "COUNT(*) FILTER (WHERE status_name IS NULL) AS no_status",
        f"COUNT(*) FILTER (WHERE sanctioned_amount > 0 AND {rel} >= sanctioned_amount) AS full_release",
        f"COUNT(*) FILTER (WHERE {rel} > 0 AND {rel} < sanctioned_amount) AS part_release",
        f"COUNT(*) FILTER (WHERE {rel} = 0) AS no_release",
        f"COUNT(*) FILTER (WHERE sanctioned_amount > 0 AND {rel} >= sanctioned_amount "
        "AND NOT COALESCE(is_completed, FALSE)) AS full_not_done",
        "COUNT(DISTINCT sanction_no) AS sanction_numbers",
        "COUNT(*) FILTER (WHERE is_placeholder) AS placeholders",
    ]
    for st, c in _PMAY_STAGE_COL.items():
        cols.append(f"COUNT(*) FILTER (WHERE status_name = '{st}') AS {c}")
        cols.append(f"COUNT(*) FILTER (WHERE status_name = '{st}' AND sanctioned_amount > 0 "
                    f"AND {rel} >= sanctioned_amount) AS fnd_{c}")
    group = "" if dim == "state" else f"\nGROUP BY {key}"
    sql = ("SELECT " + ",\n       ".join(cols) + "\nFROM curated.v_pmay"
           + ("\nWHERE " + "\n  AND ".join(where) if where else "") + group)
    shown = _pmay_inline_params(sql, params)
    return {"sql": sql, "params": params, "shown": shown, "metrics": metrics, "dim": dim,
            "entities": ents, "year_key": None if calendar_year is not None else yk, "date": day, "stages": stages,
            "calendar_year": calendar_year, "bare_year": bare_year,
            "word": "beneficiaries" if "beneficiar" in (question or "").lower() else "houses",
            "question": question}


def _pmay_param_literal(value) -> exp.Expression:
    if isinstance(value, list):
        return exp.Array(expressions=[_pmay_param_literal(v) for v in value])
    if isinstance(value, int) and not isinstance(value, bool):
        return exp.Literal.number(value)
    return exp.Literal.string(str(value))


def _pmay_inline_params(sql: str, params: list) -> str:
    """The query as shown to the user: each $n replaced on the tree by its value, a list
    as ARRAY[...] (its ::int[] / ::text[] cast dropped). Unparseable text is shown as is."""
    def fn(tree: exp.Expression) -> None:
        for node in list(tree.find_all(exp.Parameter)):
            try:
                i = int(node.name)
            except (TypeError, ValueError):
                continue
            if not 1 <= i <= len(params):
                continue
            target = node
            if isinstance(node.parent, exp.Cast) and node.parent.to.is_type(exp.DataType.Type.ARRAY) \
                    and isinstance(params[i - 1], list):
                target = node.parent
            target.replace(_pmay_param_literal(params[i - 1]))
        return None

    trees = sql_ast.parse(sql)
    if len(trees) != 1:
        return sql
    fn(trees[0])
    return trees[0].sql(dialect=sql_ast.DIALECT, pretty=True)


def _pmay_money(v) -> str:
    """₹ with Indian digit grouping, plus lakh / crore — exact, never rounded away
    (KI-095: a village's ₹9,40,000 was printed "0.09 crore")."""
    v = int(round(float(v or 0)))
    s = str(abs(v))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    out = ("-" if v < 0 else "") + "₹" + s
    if abs(v) >= 10_000_000:
        return f"{out} (₹{v / 10_000_000:,.2f} crore)"
    if abs(v) >= 100_000:
        return f"{out} (₹{v / 100_000:,.2f} lakh)"
    return out


def _pmay_money_short(v) -> str:
    """₹ in crore / lakh only, for a figure already given exactly elsewhere."""
    v = float(v or 0)
    if abs(v) >= 10_000_000:
        return f"₹{v / 10_000_000:,.2f} crore"
    if abs(v) >= 100_000:
        return f"₹{v / 100_000:,.2f} lakh"
    return _pmay_money(v)


def _pmay_period(spec: dict) -> str:
    if spec.get("date") is not None:
        d = spec["date"]
        return f"on {d.day} {d.strftime('%B %Y')}"
    if spec.get("calendar_year") is not None:
        y = spec["calendar_year"]
        return f"in calendar year {y} (sanction dates 1 January – 31 December {y})"
    if spec.get("year_key") is not None:
        y = spec["year_key"]
        return f"in FY {y}-{(y + 1) % 100:02d}"
    yrs = _SCHEME_DATA_YEARS.get("PMAY-G") or []
    return f"across all financial years (FY {yrs[0]} to FY {yrs[-1]})" if yrs else "across all financial years"


def _pmay_entity_name(spec: dict, row: dict) -> str:
    disp = spec.get("display") or {}
    if not row.get("block") and spec["dim"] == "village" and len(spec["entities"]) == 1:
        row = {**row, "name": row.get("name") if row.get("name") != row.get("entity_key") else None,
               "block": disp.get("block"), "district": disp.get("district")}
        if not row.get("name"):
            row["name"] = disp.get("village") or row.get("entity_key")
        if not row.get("block"):
            _n0 = _place_title(row["name"])
            return _n0 if _pmay_ends_with_village(_n0) else f"{_n0} village"
    n = _place_title(row.get("name") or row.get("entity_key") or "")
    if spec["dim"] == "block":
        return f"{n} block"
    if spec["dim"] == "village":
        # "MODEL VILLAGE" is already a village's name — not "Model Village village"
        _vw = "" if _pmay_ends_with_village(n) else " village"
        return f"{n}{_vw} ({_place_title(row.get('block') or '')} block, {_place_title(row.get('district') or '')})" \
            if len(spec["entities"]) == 1 else n
    return n


def _pmay_pct(num, den) -> "float | None":
    return (100.0 * float(num) / float(den)) if den else None


def _pmay_stage_split(row: dict, prefix: str = "") -> str:
    parts = [f"{st} {int(row.get(prefix + c) or 0):,}" for st, c in _PMAY_STAGE_COL.items()
             if int(row.get(prefix + c) or 0)]
    return ", ".join(parts)


def _pmay_lines(spec: dict, row: dict) -> list[str]:
    """One line per requested metric for one entity."""
    h = int(row["houses"])
    word = spec["word"]
    L: list[str] = []
    for m in spec["metrics"]:
        if m == "houses":
            # The count includes the zero-sanction registrations (D-060); say how many.
            ph = int(row.get("placeholders") or 0)
            L.append((f"PMAY-G {word}: {h:,}"
                      if word == "beneficiaries" or (spec.get("date") is None and spec.get("year_key") is None
                                                     and spec.get("calendar_year") is None)
                      else f"PMAY-G houses sanctioned: {h:,}")
                     + (f" (including {ph:,} registered with a sanctioned amount of ₹0 and no house "
                        "sanctioned yet)" if ph else ""))
        elif m == "sanctioned":
            L.append(f"Total amount sanctioned: {_pmay_money(row['sanctioned'])}")
        elif m == "released":
            L.append(f"Amount released: {_pmay_money(row['released'])}")
        elif m == "remaining":
            L.append(f"Amount still to be released (sanctioned − released): "
                     f"{_pmay_money(float(row['sanctioned']) - float(row['released']))}")
        elif m == "completed":
            L.append(f"Completed houses: {int(row['completed']):,}")
        elif m == "incomplete":
            split = _pmay_stage_split({k: v for k, v in row.items() if k != "st_completed"})
            ns = int(row["no_status"])
            L.append(f"Houses not yet completed: {int(row['incomplete']):,}")
        elif m == "status":
            ns = int(row["no_status"])
            L.append(f"House status breakdown ({h:,} houses): " + (_pmay_stage_split(row) or "none")
                     + (f"; no status recorded: {ns:,}" if ns else ""))
        elif m == "full":
            L.append(f"Beneficiaries who have received their full sanctioned amount: {int(row['full_release']):,}")
        elif m == "part":
            L.append(f"Beneficiaries who have received only part of their sanctioned amount: "
                     f"{int(row['part_release']):,}")
        elif m == "none":
            L.append(f"Beneficiaries who have not received any amount yet: {int(row['no_release']):,}")
        elif m == "full_not_done":
            n = int(row["full_not_done"])
            split = _pmay_stage_split({k: v for k, v in row.items() if k != "fnd_st_completed"}, "fnd_")
            ns = n - sum(int(row.get("fnd_" + c) or 0) for s, c in _PMAY_STAGE_COL.items() if s != "Completed")
            L.append("Beneficiaries who have received the full sanctioned amount but whose house is not yet "
                     f"completed: {n:,}")
        elif m == "sanction_numbers":
            L.append(f"Unique sanction numbers: {int(row['sanction_numbers']):,}")
        elif m == "completion_pct":
            p = _pmay_pct(row["completed"], h)
            L.append(f"Completion rate: {p:.2f}%" if p is not None else "Completion rate: not available (no houses)")
        elif m == "release_pct":
            p = _pmay_pct(row["released_on_sanctioned"], row["sanctioned_positive"])
            L.append(f"Share of the sanctioned amount released: {p:.2f}%" if p is not None
                     else "Share of the sanctioned amount released: not available (nothing sanctioned)")
    return L


_PMAY_CMP = {  # metric -> (row value, label, is money)
    "houses": (lambda r: int(r["houses"]), "houses", False),
    "sanctioned": (lambda r: float(r["sanctioned"]), "sanctioned amount", True),
    "released": (lambda r: float(r["released"]), "amount released", True),
    "remaining": (lambda r: float(r["sanctioned"]) - float(r["released"]), "amount still to be released", True),
    "completed": (lambda r: int(r["completed"]), "completed houses", False),
    "incomplete": (lambda r: int(r["incomplete"]), "houses not yet completed", False),
    "full": (lambda r: int(r["full_release"]), "beneficiaries fully paid", False),
    "part": (lambda r: int(r["part_release"]), "beneficiaries partly paid", False),
    "none": (lambda r: int(r["no_release"]), "beneficiaries with nothing released", False),
    "full_not_done": (lambda r: int(r["full_not_done"]), "fully paid but incomplete houses", False),
    "sanction_numbers": (lambda r: int(r["sanction_numbers"]), "unique sanction numbers", False),
    "completion_pct": (lambda r: _pmay_pct(r["completed"], r["houses"]), "completion rate", None),
    "release_pct": (lambda r: _pmay_pct(r["released_on_sanctioned"], r["sanctioned_positive"]),
                    "share of sanctioned amount released", None),
}


_PMAY_ROW_COLS = {  # metric -> [(column shown in the result table, value from the working row)]
    "houses": [("houses", lambda r: int(r["houses"]))],
    "sanctioned": [("sanctioned amount (Rs)", lambda r: round(float(r["sanctioned"])))],
    "released": [("amount released (Rs)", lambda r: round(float(r["released"])))],
    "remaining": [("still to be released (Rs)", lambda r: round(float(r["sanctioned"]) - float(r["released"])))],
    "completed": [("completed houses", lambda r: int(r["completed"]))],
    "incomplete": [("houses not yet completed", lambda r: int(r["incomplete"]))],
    "full": [("fully paid beneficiaries", lambda r: int(r["full_release"]))],
    "part": [("partly paid beneficiaries", lambda r: int(r["part_release"]))],
    "none": [("beneficiaries with nothing released", lambda r: int(r["no_release"]))],
    "full_not_done": [("fully paid, house not completed", lambda r: int(r["full_not_done"]))],
    "sanction_numbers": [("unique sanction numbers", lambda r: int(r["sanction_numbers"]))],
    "completion_pct": [("completion rate (%)", lambda r: round(_pmay_pct(r["completed"], r["houses"]) or 0, 2))],
    "release_pct": [("share released (%)", lambda r: round(
        _pmay_pct(r["released_on_sanctioned"], r["sanctioned_positive"]) or 0, 2))],
}


def _pmay_display_rows(spec: dict, rows: list[dict]) -> list[dict]:
    """The result table the UI shows: one row per place with ONLY the figures the
    question asked for. The working row (30 columns: fnd_st_plinth, sanctioned_positive,
    …) was returned as-is and the UI printed every column (user report 2026-09-29)."""
    out = []
    for r in rows:
        d = {spec["dim"] if spec["dim"] != "state" else "area": _place_title(str(r.get("name") or r.get("entity_key")))}
        for m in spec["metrics"]:
            if m == "status":
                for st, c in _PMAY_STAGE_COL.items():
                    if int(r.get(c) or 0):
                        d[st] = int(r[c])
                continue
            for col, fn in _PMAY_ROW_COLS.get(m, []):
                d[col] = fn(r)
        out.append(d)
    return out


# "Expenditure" / "spent" on PMAY-G is answered with the amount released (the
# nearest money PMAY-G holds; docs/SCHEMES.md). "Total expenditure for MGNREGA"
# -> "give for pmay" came back as "Amount released …" with no word that PMAY-G
# records no expenditure, which read as a different question answered (user
# report 2026-10-08). Say so first, then give the released figure.
_PMAY_SPEND_WORD_MATCH = Matcher(Alt(W("expenditure", "expenditures", "expense", "expenses", "spent", "outlay", "cost",
                                    "costs"), W("spend", prefix=True)))


def _pmay_expenditure_not_held(spec: dict, answer: str) -> str:
    """Prefix the 'PMAY-G records no expenditure' note to an answer that gives
    the amount released for an expenditure question."""
    if "released" not in (spec.get("metrics") or []) or not _PMAY_SPEND_WORD_MATCH.search(spec.get("question") or ""):
        return answer
    return ("PMAY-G does not record a total expenditure figure, so total expenditure is not available "
            "for PMAY-G. The closest figure it holds is the amount released to beneficiaries against "
            "their sanctioned houses:\n\n" + answer)


def _pmay_facts_answer(spec: dict, rows: list[dict]) -> "str | None":
    """The answer text for _pmay_facts_query's result, or None to fall back to the
    model path (an entity came back with no houses at all)."""
    by_key = {str(r["entity_key"]).upper(): r for r in rows}
    ordered = []
    for e in spec["entities"]:
        r = by_key.get(str(e).upper())
        if r is None or not int(r["houses"]):
            if (spec.get("date") is None and spec.get("year_key") is None and spec.get("calendar_year") is None
                    and not spec.get("stages")):
                return None          # the place holds no PMAY-G rows under this name: let the model path handle it
            r = r or {"entity_key": e, "name": e, "houses": 0, **{k: 0 for k in (
                "sanctioned", "released", "released_on_sanctioned", "sanctioned_positive", "completed", "incomplete",
                "no_status", "full_release", "part_release", "no_release", "full_not_done", "sanction_numbers")},
                **{c: 0 for c in _PMAY_STAGE_COL.values()}, **{"fnd_" + c: 0 for c in _PMAY_STAGE_COL.values()}}
        ordered.append(r)
    period = _pmay_period(spec)
    stage_note = (f" (houses at the {' / '.join(spec['stages'])} stage)" if spec.get("stages") else "")
    if len(ordered) == 1:
        r = ordered[0]
        where = "Meghalaya (statewide)" if spec["dim"] == "state" else _pmay_entity_name(spec, r)
        if not int(r["houses"]):
            return (f"No PMAY-G houses were sanctioned in {where} {period}{stage_note}: 0 houses — there are no "
                    "PMAY-G records for that period, so every figure is zero.")
        lines = _pmay_lines(spec, r)
        if len(lines) == 1:
            label, _, value = lines[0].partition(": ")
            return f"{label} in {where}, {period}{stage_note}: {value}."
        return f"PMAY-G — {where}, {period}{stage_note}:\n" + "\n".join(f"- {ln}" for ln in lines)
    # comparison of the named entities
    names = [_pmay_entity_name(spec, r) for r in ordered]
    out = [f"PMAY-G comparison, {period}{stage_note}:"]
    for n, r in zip(names, ordered):
        out.append(f"{n}:")
        out.extend(f"- {ln}" for ln in _pmay_lines(spec, r))
    diffs = []
    for m in spec["metrics"]:
        if m == "status" or m not in _PMAY_CMP:
            continue
        fn, label, money = _PMAY_CMP[m]
        vals = [fn(r) for r in ordered]
        if any(v is None for v in vals):
            continue
        if len(ordered) == 2:
            a, b = vals
            if a == b:
                diffs.append(f"{label.capitalize()}: {names[0]} and {names[1]} are equal.")
                continue
            hi, lo = (0, 1) if a > b else (1, 0)
            d = abs(a - b)
            ds = (_pmay_money(d) if money else f"{d:.2f} percentage points" if money is None else f"{int(d):,}")
            diffs.append(f"{label.capitalize()}: {names[hi]} is higher by {ds}.")
        else:
            i = max(range(len(vals)), key=lambda k: vals[k])
            v = vals[i]
            vs = (_pmay_money(v) if money else f"{v:.2f}%" if money is None else f"{int(v):,}")
            diffs.append(f"Highest {label}: {names[i]} ({vs}).")
    if diffs:
        out.append("Difference:" if len(ordered) == 2 else "Summary:")
        out.extend(f"- {d}" for d in diffs)
    return "\n".join(out)


# Model-path guards for the PMAY-G shapes the deterministic path leaves alone.
# A question that asks for a series names it; the year chip's "across all
# financial years" is a scope, not a request for a per-year split.
_PMAY_SERIES_ASK_MATCH = Matcher(Alt(
    W("year", "years", "yearly", "fy", "fys", "date", "dates", "when", "history", "historical", "each", "per", "wise"),
    W("annual", "month", "trend", prefix=True), "over time"))
_PMAY_ALL_YEARS_CHIP_MATCH = Matcher(Seq(W("across", "for", "over"), "all", Opt("the"), Opt(W("financial", "fiscal")),
                                      "years", Opt("combined")))
_PMAY_YEAR_COLS = frozenset({"financial_year", "financial_year_short", "year_key", "sanction_month",
                             "sanction_date"})


def _pmay_groups_by_year(sql: str) -> bool:
    """True when any GROUP BY of the query (outer, CTE or subquery) groups on a year /
    date column — named, or by position (GROUP BY 1) or output alias of a select item
    that reads one."""
    for sel in sql_ast.selects(sql):
        group = sel.args.get("group")
        if group is None:
            continue
        items = list(sel.expressions)
        aliases = {e.alias.lower(): e for e in items if isinstance(e, exp.Alias) and e.alias}
        for g in group.expressions:
            if sql_ast.columns(g) & _PMAY_YEAR_COLS:
                return True
            if isinstance(g, exp.Literal) and not g.is_string and g.this.isdigit() \
                    and 1 <= int(g.this) <= len(items):
                if sql_ast.columns(items[int(g.this) - 1]) & _PMAY_YEAR_COLS:
                    return True
            if isinstance(g, exp.Column) and not g.table and g.name.lower() in aliases \
                    and sql_ast.columns(aliases[g.name.lower()]) & _PMAY_YEAR_COLS:
                return True
    return False


def _pmay_avg_of_released(sql: str) -> bool:
    """An AVG(...) over amount_released anywhere in the query."""
    return any(isinstance(a, exp.Avg) and sql_ast.references_column(a, "amount_released")
               for a in sql_ast.aggregates(sql))


# percent, %, utilis/utiliz, proportion, ratio anywhere inside a word; rate, share as whole words
# (as before: "ratio" inside "registration" counts); "%" is checked by _pmay_rate_ask.
_PMAY_RATE_ASK_MATCH = Matcher(Alt(W("rate", "share"), Pred(lambda w: any(
    s in w.lower() for s in ("percent", "utilis", "utiliz", "proportion", "ratio")))))


def _pmay_rate_ask(q: str) -> bool:
    return "%" in (q or "") or bool(_PMAY_RATE_ASK_MATCH.search(q))


def _pmay_sql_issue(question: str, schemes: list[str], sql: str) -> "str | None":
    """Repair message for the PMAY-G SQL shapes that produced wrong answers in the
    2026-09-28 use-case QA, else None (KI-089, KI-092)."""
    if schemes != ["PMAY-G"] or not sql:
        return None
    q = _PMAY_ALL_YEARS_CHIP_MATCH.sub(" ", question or "")
    if _pmay_groups_by_year(sql) and not _PMAY_SERIES_ASK_MATCH.search(q):
        return ("this question asks for ONE figure per area over the whole period, but the query groups "
                "by financial year / sanction date, so the answer becomes a per-year row dump or a sum of "
                "rounded yearly values (\"financial summary for Mawphlang\" read 41.79 crore for a true "
                "41.78 crore and never gave the released amount). Remove the year column from SELECT and "
                "GROUP BY and return one row per area named in the question (a single row if one area): "
                "COUNT(*) AS houses, SUM(sanctioned_amount) AS sanctioned, SUM(COALESCE(amount_released, 0)) "
                "AS released, SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0)) AS remaining in "
                "RUPEES, unrounded. Keep every filter (NOT is_placeholder, geography, year_key) as it was.")
    if _pmay_avg_of_released(sql) and _pmay_rate_ask(q):
        return ("utilisation / the share of the sanctioned amount released is ONE ratio of totals: "
                "100.0 * SUM(COALESCE(amount_released, 0)) / NULLIF(SUM(sanctioned_amount), 0) over rows with "
                "sanctioned_amount > 0. The query uses AVG(...) over amount_released, which skips the 336 houses "
                "whose release is NULL and averages per-house ratios — a different, wrong number (98.82% for a "
                "true 98.76% in East Khasi Hills). Replace the AVG with that SUM ratio and keep every filter.")
    return None


def _pmay_no_houses_answer(spec: dict, row: "dict | None", display: dict) -> str:
    """A village the resolver settled by LGD code but which holds no PMAY-G record —
    a genuine zero (the code cannot be misspelled); the model path answered "the data
    doesn't cover … shows 0". (A village whose only record is a zero-sanction
    registration, Rtiang Sanphew, is now answered with that 1 beneficiary, D-060.)"""
    name = _place_title((row or {}).get("name") or display.get("village") or str(spec["entities"][0]))
    where = name + (f" village ({_place_title(row['block'])} block, {_place_title(row['district'])})"
                    if row and row.get("block") else " village")
    return (f"No PMAY-G houses are recorded for {where}: it has no sanctioned house in the data, so the "
            "beneficiary count, amounts and completion are all zero.")


# Money cells in a model-path PMAY-G result (rupees, not already crore / lakh).
# Column names: the stems match anywhere inside a word; "_cr" / "_no" only at a word's end.
_PMAY_MONEY_COL_MATCH = Matcher(Pred(lambda w: any(s in w.lower() for s in (
    "sanction", "releas", "pending", "amount", "rupee", "spent", "expend", "outlay", "disburs", "remaining", "gap"))))
_PMAY_NOT_MONEY_COL_MATCH = Matcher(Pred(lambda w: w.lower().endswith(("_cr", "_no")) or any(s in w.lower() for s in (
    "crore", "lakh", "pct", "percent", "rate", "share", "ratio", "count", "houses", "number", "date", "year"))))


def _pmay_rupee_format(answer: str, rows: list[dict], fmt=None, column_totals: bool = False) -> str:
    """Rewrite the exact money cells of a PMAY-G result that the composer printed bare
    ("795,860,000.00", "130000.00 rupees") as ₹ with Indian grouping and lakh / crore —
    only the figures that ARE result cells, so nothing new is stated (KI-095).
    `fmt` overrides the formatter; `column_totals` also rewrites each money column's
    sum over the rows, which the composer states as "a total of …" (Focus Legacy, KI-147)."""
    if not answer or not rows:
        return answer
    fmt = fmt or _pmay_money
    vals = set()
    sums: dict[str, float] = {}
    for r in rows[:50]:
        for k, v in r.items():
            if (isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) and abs(float(v)) >= 1000
                    and _PMAY_MONEY_COL_MATCH.search(str(k)) and not _PMAY_NOT_MONEY_COL_MATCH.search(str(k))):
                vals.add(float(v))
                sums[k] = sums.get(k, 0.0) + float(v)
    if column_totals and len(rows) > 1:
        vals.update(sums.values())
    for v in sorted(vals, reverse=True):
        forms = {f"{v:,.2f}", f"{v:,.0f}", f"{v:.2f}", f"{v:.0f}"}
        for s in sorted(forms, key=len, reverse=True):
            answer = _pmay_replace_amount(answer, s, fmt(v))
    return answer


def _pmay_replace_amount(text: str, num: str, rep: str) -> str:
    """Replace each figure `num` standing alone (no digit, ',' or '.' just before it; no digit,
    nor ',' / '.' + digit, just after it) with `rep`, taking along a directly preceding
    "₹" / "Rs" / "Rs." / "INR" (each with at most one space) and a following "rupees" / "INR".
    Case-sensitive, as before."""
    out, last, pos, n = [], 0, 0, len(text)
    while num:
        k = text.find(num, pos)
        if k < 0:
            break
        e = k + len(num)
        if (k > 0 and (text[k - 1].isdecimal() or text[k - 1] in ",.")) or (e < n and (
                text[e].isdecimal() or (text[e] in ",." and e + 1 < n and text[e + 1].isdecimal()))):
            pos = k + 1
            continue
        b = text[last:k]
        st = k
        sp = 1 if b[-1:].isspace() else 0
        head = b[:len(b) - sp]
        for cur in ("₹", "Rs.", "Rs", "INR"):
            if head.endswith(cur) and not (cur == "Rs." and not sp):
                st = k - sp - len(cur)
                break
        t = e
        while t < n and text[t].isspace():
            t += 1
        end = e
        for suf in ("rupees", "INR"):
            if text.startswith(suf, t):
                end = t + len(suf)
                break
        out.append(text[last:st])
        out.append(rep)
        last = pos = end
    out.append(text[last:])
    return "".join(out)


def _pmay_unknown_place_note(note: str) -> "tuple[str, str] | None":
    """(name, level) of a resolver note "'<name>' is not a known <village | block or village |
    block | district>…", else None."""
    if not note.startswith("'"):
        return None
    j = note.find("'", 1)
    if j <= 1:
        return None
    rest = note[j + 1:]
    lead = " is not a known "
    if not rest.startswith(lead):
        return None
    rest = rest[len(lead):]
    for level in ("village", "block or village", "block", "district"):
        if rest.startswith(level) and (len(rest) == len(level) or not _pmay_is_word_char(rest[len(level)])):
            return note[1:j], level
    return None


def _pmay_unknown_place_answer(schemes: list[str], resolved: dict, notes: "list[str] | None") -> "str | None":
    """A plain "no such place" for a PMAY-G question whose only place the resolver
    could not find. The model path answered "the data available doesn't cover …
    the result shows 0 beneficiaries" for a made-up village, which reads like a real
    zero (PMAY-G probes 2026-09-28)."""
    if schemes != ["PMAY-G"] or any(resolved.get(k) for k in (
            "village_code", "village_code_list", "block", "block_list", "district", "district_list")):
        return None
    hits = [m for m in (_pmay_unknown_place_note(n or "") for n in (notes or [])) if m]
    if len(hits) != 1:
        return None
    name, level = hits[0]
    return (f"“{name}” is not a {level} in Meghalaya's LGD list or in the PMAY-G data, so there is no PMAY-G figure "
            "for it. Please check the spelling, or name the block or district it is in.")


def _pmay_fy_labels(answer: str, rows: list[dict]) -> str:
    """A model-path answer that printed year_key values as bare years ("2,390 houses
    sanctioned in 2017") reads as a calendar year; year_key is the financial year
    (2017 = FY 2017-18). Relabel a year that IS a year_key cell of the result, after
    in / for / during / and / a comma (PMAY-G scenario run 2026-09-28)."""
    if not answer or not rows or not any("year_key" in r for r in rows[:1]):
        return answer
    yks = {int(r["year_key"]) for r in rows[:60] if isinstance(r.get("year_key"), (int, float)) and r.get("year_key")}
    for y in sorted(yks, reverse=True):
        answer = _pmay_relabel_year(answer, y)
    return answer


def _pmay_lead_in(text: str, p: int, floor: int) -> int:
    """Start of an "in / for / during / and / of" + spaces, or a "," + optional spaces, ending
    exactly at p (case-sensitive), not before `floor`; -1 if there is none."""
    head = text[floor:p]
    stripped = head.rstrip()
    if stripped.endswith(","):
        return floor + len(stripped) - 1
    if len(stripped) == len(head):
        return -1                  # a preposition needs at least one space after it
    for w in ("in", "for", "during", "and", "of"):
        if stripped.endswith(w):
            s = floor + len(stripped) - len(w)
            if s == 0 or not _pmay_is_word_char(text[s - 1]):
                return s
    return -1


def _pmay_relabel_year(text: str, y: int) -> str:
    """'in 2017' / ', FY 2017' -> 'in FY 2017-18' for a year_key y: the year after in / for / during /
    and / of + spaces or after a comma, optionally written 'FY 2017', not followed by a digit or '-'."""
    ys, label = str(y), f"FY {y}-{(y + 1) % 100:02d}"
    out, last, pos, n = [], 0, 0, len(text)
    while True:
        k = text.find(ys, pos)
        if k < 0:
            break
        e = k + len(ys)
        if e < n and (text[e].isdecimal() or text[e] == "-"):
            pos = k + 1
            continue
        start = lead_end = -1
        before = text[last:k].rstrip()
        if before.endswith("FY"):
            fy = last + len(before) - 2
            s = _pmay_lead_in(text, fy, last)
            if s >= 0:
                start, lead_end = s, fy
        if start < 0:
            s = _pmay_lead_in(text, k, last)
            if s >= 0:
                start, lead_end = s, k
        if start < 0:
            pos = k + 1
            continue
        out.append(text[last:start])
        out.append(text[start:lead_end] + label)
        last = pos = e
    out.append(text[last:])
    return "".join(out)


_PMAY_CRORE_SUFFIXES = ("crores", "crore", "cr")


def _pmay_is_crore_divisor(node: "exp.Expression | None") -> bool:
    """10000000 / 10000000.0 / 1e7 as a number literal."""
    if isinstance(node, exp.Paren):
        return _pmay_is_crore_divisor(node.this)
    if not isinstance(node, exp.Literal) or node.is_string:
        return False
    try:
        return float(node.this) == 1e7
    except ValueError:
        return False


def _pmay_rupee_alias(alias: str) -> "str | None":
    """'avg_sanctioned_amount_crore' -> 'avg_sanctioned_amount_rupees', 'total_cr' ->
    'total_rupees', 'crore' -> 'amount_rupees'; None for any other name."""
    low = alias.lower()
    for suf in _PMAY_CRORE_SUFFIXES:
        if low.endswith(suf):
            stem = alias[: len(alias) - len(suf)]
            stem = stem[:-1] if stem.endswith("_") else stem
            return f"{stem or 'amount'}_rupees"
    return None


def _pmay_crore_to_rupees(schemes: list[str], sql: str) -> str:
    """PMAY-G money is rupees; the model's ROUND(x / 10000000.0, 2) turned a ₹1,30,000
    average into "0.01 crore" (PMAY-G scenario run 2026-09-28; the model-path twin of
    KI-095). Drop the crore division and name the column in rupees — the rows then
    carry exact rupees and _pmay_rupee_format writes ₹ with lakh / crore."""
    if schemes != ["PMAY-G"] or not sql:
        return sql

    def fn(tree: exp.Expression) -> None:
        divs = [d for d in tree.find_all(exp.Div) if _pmay_is_crore_divisor(d.expression)]
        if not divs:
            return None
        for d in divs:
            d.replace(d.this)
        renamed: dict[str, str] = {}
        for a in list(tree.find_all(exp.Alias)):
            new = _pmay_rupee_alias(a.alias) if a.alias else None
            if new:
                renamed[a.alias.lower()] = new
                a.set("alias", exp.to_identifier(new))
        # ORDER BY / outer references to a renamed output column follow it
        for c in list(tree.find_all(exp.Column)):
            if not c.table and c.name.lower() in renamed:
                c.set("this", exp.to_identifier(renamed[c.name.lower()]))
        return None

    return sql_ast.transform(sql, fn)


def _pmay_is_placeholder_exclusion(node: exp.Expression) -> bool:
    """`NOT is_placeholder`, `is_placeholder = FALSE` / `IS FALSE` / `<> TRUE` (any parentheses)."""
    while isinstance(node, exp.Paren):
        node = node.this
    def col(n):
        while isinstance(n, exp.Paren):
            n = n.this
        return isinstance(n, exp.Column) and n.name.lower() == "is_placeholder"
    if isinstance(node, exp.Not):
        return col(node.this)
    if isinstance(node, (exp.EQ, exp.Is)) and isinstance(node.expression, exp.Boolean):
        return col(node.this) and not node.expression.this
    if isinstance(node, exp.NEQ) and isinstance(node.expression, exp.Boolean):
        return col(node.this) and bool(node.expression.this)
    return False


def _pmay_release_vs_sanction(tree: exp.Expression) -> bool:
    """A comparison of amount_released with sanctioned_amount (full / partial release)."""
    for c in tree.find_all(exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE):
        if sql_ast.references_column(c, "amount_released") and sql_ast.references_column(c, "sanctioned_amount"):
            return True
    return False


def _pmay_count_placeholders(schemes: list[str], sql: str) -> str:
    """The 126 zero-sanction registrations (is_placeholder) are beneficiaries (user rule
    2026-10-22, D-060): drop the model's `NOT is_placeholder` so its counts agree with the
    fixed path (171,107 statewide, not 170,981). Kept where those rows would distort the
    figure: a full / partial release comparison (₹0 released of ₹0 is no "full release")
    and a per-house AVG. Sums of money are the same either way."""
    if schemes != ["PMAY-G"] or not sql or not sql_ast.reads_table(sql, "v_pmay"):
        return sql
    trees = sql_ast.parse(sql)
    if len(trees) != 1 or _pmay_release_vs_sanction(trees[0]) or sql_ast.has_aggregate(trees[0], "avg"):
        return sql
    out = sql_ast.remove_conditions(sql, _pmay_is_placeholder_exclusion)
    if out != sql:
        logger.info("PMAY-G: zero-sanction registrations counted (D-060): %s", out.replace("\n", " ")[:300])
    return out


def _pmay_comparison_limit(schemes: list[str], entity_result: dict, sql: str) -> str:
    """A comparison of N named areas must return N rows. "Which has more completed
    houses: Maweitnar or Rohonpara?" came back with LIMIT 1 and the answer named only
    the winner (KI-093)."""
    if schemes != ["PMAY-G"] or not sql:
        return sql
    r = (entity_result or {}).get("resolved") or {}
    n = max((len(r.get(k) or []) for k in ("village_code_list", "block_list", "district_list")), default=0)
    if n >= 2 and sql_ast.outer_limit(sql) == 1:
        sql = sql_ast.set_limit(sql, n)
    return sql

# app/pipeline/schemes/cm_elevate.py — CM Elevate (applications) — village rules, sector facts, SQL rewrites and answer guarantees.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
# Only this scheme's code lives here; the shared steps that call it are in ../common/.
# Sections follow the order of the pipeline steps they belong to.
# Every check or rewrite of SQL here works on the SQLGlot tree (app/sql_ast.py); the
# user's question and the composed answer are read on WORDS (app/text_match.py) —
# no regular expressions (D-047).
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app import sql_ast
from app.text_match import (Alt, Cap, Hit, Joined, Matcher, Node, NotBefore, Opt, Pred, Seq, W,
                            collapse_ws, is_int)
from app.text_match import words as _tm_words


class _CmeNear(Node):
    """`a`, then `b` starting at most `max_chars` characters after `a` ends, with no
    character of `stops` in between (the old `a[^?.]{0,50}b`). max_chars=None: any
    distance."""

    def __init__(self, a, b, max_chars: "int | None", stops: str = "?."):
        self.a, self.b = Seq(a), Seq(b)
        self.max_chars, self.stops = max_chars, stops

    def ends(self, ctx, i, caps):
        n = len(ctx.toks)
        for j, c2 in self.a.ends(ctx, i, caps):
            if j == i:
                continue
            a_end = ctx.toks[j - 1].end
            for k in range(j, n):
                between = ctx.text[a_end:ctx.toks[k].start]
                if (self.max_chars is not None and len(between) > self.max_chars) \
                        or any(s in between for s in self.stops):
                    break
                yield from self.b.ends(ctx, k, c2)


class _CmeWrapped(Node):
    """One word `x` written directly inside `opener` … `closer`: "(SEED)"."""

    def __init__(self, x, opener: str, closer: str):
        self.x, self.opener, self.closer = Seq(x), opener, closer

    def ends(self, ctx, i, caps):
        if i >= len(ctx.toks):
            return
        before = ctx.text[(ctx.toks[i - 1].end if i else 0):ctx.toks[i].start]
        if not before.endswith(self.opener):
            return
        for j, c2 in self.x.ends(ctx, i, caps):
            if j > i and ctx.text[ctx.toks[j - 1].end:].startswith(self.closer):
                yield j, c2


def _cme_stem_joined(first: str, stem: str) -> Node:
    """`first[\\s_-]?stem\\w*`: two words, or one word ("applicant_category")."""
    return Alt(Seq(first, W(stem, prefix=True)),
               Pred(lambda w: w.lower().startswith((first + stem, first + "_" + stem))))


def _cme_sg(*ws: str) -> W:
    """A word and its plural (`words?`)."""
    return W(*[f for w in ws for f in (w, w + "s")])


def _cme_level_digit(one_digit: bool) -> Node:
    """"level 2", "level-2", "level2" (`level\\s*-?\\s*\\d`); one_digit=True is
    `level[\\s-]*\\d\\b` (exactly one digit, then the word ends)."""
    if one_digit:
        return Alt(Seq("level", Pred(lambda w: len(w) == 1 and is_int(w))),
                   Pred(lambda w: len(w) == 6 and w.lower().startswith("level") and is_int(w[5:])))
    return Alt(Seq("level", Pred(lambda w: is_int(w[:1]))),
               Pred(lambda w: w.lower().startswith("level") and is_int(w[5:6])))


def _cme_join(*parts) -> Node:
    """`a[\\s-]?b`: the words apart ("on hold", "on-hold") or run together ("onhold"),
    but not joined by '_' ("on_hold" is a column name). Each part is a word or a
    tuple of words."""
    alts = [p if isinstance(p, tuple) else (p,) for p in parts]
    combos = [""]
    for a in alts:
        combos = [c + x.lower() for c in combos for x in a]
    words = [W(*a) for a in alts]
    return Alt(Seq(*words, sep="space"), Seq(*words, sep="dash"), W(*combos))


def _cme_has(sub: str) -> Pred:
    """A word containing `sub` (a regex with no word boundaries)."""
    return Pred(lambda w: sub in w.lower())


# The old `on[\s-]?hold` with no word boundaries: "on hold", "on-hold", "onhold", also inside words ("partition holds")
_CME_ON_HOLD_ANYWHERE = Alt(Seq(Pred(lambda w: w.lower().endswith("on")), Pred(lambda w: w.lower().startswith("hold")),
                                sep="space"),
                            Seq(Pred(lambda w: w.lower().endswith("on")), Pred(lambda w: w.lower().startswith("hold")),
                                sep="dash"),
                            _cme_has("onhold"))
_CME_CM_ELEVATE = _cme_join("cm", "elevate")
_CME_LEGACY_TAIL = W("legacy", "disbursement", "disbursements")
_CME_ON_HOLD = Matcher(_cme_join("on", "hold"))

# ════ scheme terms ════════════════════════════════════════════════════════════════════════════════════
# CM Elevate covers 15 sub-schemes under one programme. These terms name the
# programme itself or its scheme-specific vocabulary that belongs to no other
# scheme. "on hold" / "verification" / "application mode" are deliberately left
# out — they read as generic status words, so an unnamed question using only
# those still asks "which scheme?".
_CMELEVATE_ONLY_TERMS = Matcher(Alt(
    NotBefore(_CME_CM_ELEVATE, _CME_LEGACY_TAIL),
    W("piggery", "poultry"), "goat farming", "warehouse scheme",
    W("sericulture", "motorcaravan"), "agro tourism villa",
    "prime small enterprise", "prime tourism vehicle",
    "prime agriculture response vehicle", "green taxi",
    # "&" too: the stored name is "Meghalaya Sports & Wellness Centre Scheme", and
    # written that way it was read as MGNREGA (OFF-017 full run 2026-10-02)
    "cinema theatre scheme", Seq("sports", Opt("and"), "wellness"),
    "any business venture", W("request_id", "requestid"),
    # Missing sub-scheme/commodity words and the scheme-FAMILY phrases
    # (vehicle/tourism/PRIME/livestock/enterprise scheme(s)) — without these,
    # a question naming only this vocabulary (no literal "CM Elevate") fell
    # through to the generic 4-way "MGNREGA, PMAY-G, Focus Plus, or CM
    # Elevate?" pause instead of being recognized as CM Elevate at all, even
    # though resolve_cm_scheme's own alias catalogue (or, for the family
    # words, resolve_cm_scheme_group_ambiguity) can place it precisely
    # (confirmed live 2026-09-11: "gender split for the tourism vehicle
    # scheme" and "applications under the vehicle schemes" both asked the
    # top-level 4-scheme question despite being unambiguously CM Elevate).
    "dairy", Seq("vehicle", _cme_sg("scheme")), "tourism vehicle", Seq("tourism", _cme_sg("scheme")),
    Seq("prime", _cme_sg("scheme")), "prime family", Seq("livestock", _cme_sg("scheme")),
    Seq("enterprise", _cme_sg("scheme")),
    # "PRIME SEED" is the common short name of PRIME Small Enterprise
    # Empowerment and Development (SEED) — the largest CM Elevate programme and
    # absent from CM Elevate Legacy. Without it every SEED question paused on
    # "which scheme?" (KI-075, CM Elevate QA 2026-09-27: 006b, 007b, 008b …).
    # A bare "seed" is NOT added: Focus Legacy uses "seed money".
    "prime seed", Seq("seed", W("scheme", "programme", "program")), _CmeWrapped("seed", "(", ")"),
    # The sheet's own wording names no scheme: "How many applicants have completed data
    # verification in East Khasi Hills?", "How many applications are pending in each
    # sector in <district>?" asked "which scheme?" (CM Elevate sheet run 2026-10-10).
    # Data verification (data_verified) and the applicant sector (sector_id) are CM
    # Elevate's alone (Focus Plus's verification_status is blank on every row).
    Seq("data", W("verif", prefix=True)), Seq("completed", Opt("the"), Opt("data"), "verification"),
    _CmeNear(_cme_sg("applicant", "application"), _cme_sg("sector"), 50),
    _CmeNear(_cme_sg("sector"), _cme_sg("applicant", "application"), 30),
))


# ── The two CM Elevate datasets ─────────────────────────────────────────────
# "CM Elevate" names TWO schemes that share nothing but the name
# (cmelevatelegacy_entity_resolver.yaml scheme.disambiguation):
#   * CM Elevate        — 15-scheme APPLICATIONS (curated.v_cm_elevate): status,
#                         on hold, verification, applicant type, gender. No money,
#                         no dates.
#   * CM Elevate Legacy — 13-scheme SANCTION-AND-DISBURSEMENT records
#                         (curated.v_cm_elevate_disbursement): sanctioned amount,
#                         subsidy / loan / total disbursed, lender, financial year.
# The resolver's rule: a bare "CM Elevate" is settled by a field that exists in
# only one of them. Money, a financial year, a lender or a desanction exist only
# in Legacy, so they pin it there — answering them from the applications data
# could only ever refuse. Application-workflow words pin the other one. With
# neither, the bare name keeps its long-standing meaning (the applications data).
#
# Words that name CM Elevate Legacy on their own, with no "CM Elevate" at all.
_CMELEVATELEGACY_ONLY_TERMS = Matcher(Alt(
    Seq(_CME_CM_ELEVATE, _CME_LEGACY_TAIL), _cme_join("cm", "elevate", ("legacy", "disbursement", "disbursements")),
    Seq("legacy", _CME_CM_ELEVATE), _cme_join("elevate", "legacy"),
    "lifcom", _cme_join("loan", ("entity", "entities")), _cme_sg("lender"),
    W("desanction", prefix=True), Seq("de", W("sanction", prefix=True), sep="dash"), _cme_join("bank", "sanctioned"),
    Seq("common", "facility", W("center", "centre")),
    # Only the sanction-and-disbursement records have SANCTIONED APPLICATIONS:
    # the applications dataset has no sanction at all, and PMAY-G sanctions
    # houses, not applications ("How many sanctioned applications are there for
    # each scheme?", CM Elevate Legacy TC-19, test run 2026-10-06).
    Seq("sanctioned", _cme_sg("application")),
    _CmeNear(_cme_sg("application"), "sanctioned", 30),
))
# Vocabulary only the sanction-and-disbursement dataset can answer. Consulted
# ONLY once a question is already a CM Elevate question (named, or via a
# sub-scheme word such as "piggery"), so generic money words are safe here.
_CMELEVATELEGACY_FORCING = Matcher(Alt(
    W("disburs", "sanction", prefix=True), W("subsidy", "subsidies"), _cme_sg("loan", "grant"),
    _cme_sg("amount"), "money", _cme_sg("fund", "rupee", "crore", "lakh"),
    # "Rs 500", "Rs. 500", "Rs500"
    Seq("rs", Pred(lambda w: is_int(w[:1]))), Pred(lambda w: w.lower().startswith("rs") and is_int(w[2:3])),
    "paid", _cme_sg("payment"), "released", "entitlement", W("utilisation", "utilization"),
    # NOT a bare "pending": in the applications data "pending" means on hold
    # (data_verified = 'On Hold'). Only the money reading forces Legacy.
    W("instalment", "instalments", "installment", "installments"), W("tranch", prefix=True),
    Seq("pending", Alt(W("amount", "money"), W("disburs", prefix=True))),
    Seq("pending", "to", "be", W("paid", "disbursed", "released")), Seq("yet", "to", "be", W("paid", "disbursed")),
    "refused", _cme_sg("refusal", "duplicate"), W("desanction", prefix=True),
    "lifcom", _cme_sg("lender"), _cme_join("loan", ("entity", "entities")),
    # "financial year", "FY 24", "FY2024-25", "2023-24", "2023/2024", "year-wise"
    Seq("financial", W("year", "years"), sep="space"),
    Seq("fy", Pred(lambda w: is_int(w[:2])), sep="space"),
    Pred(lambda w: w.lower().startswith("fy") and is_int(w[2:4])),
    Seq(Pred(lambda w: len(w) == 4 and w.startswith("20") and is_int(w)),
        Pred(lambda w: 2 <= len(w) <= 4 and is_int(w)), sep="dash"),
    _cme_join("year", "wise"),
))
# Vocabulary only the APPLICATIONS dataset holds. Any of these keeps a bare
# "CM Elevate" on that dataset even when a money word is also present.
_CMELEVATE_APPLICATIONS_ONLY = Matcher(Alt(
    _cme_join("on", "hold"), W("verif", "withdraw", prefix=True), Joined("data", "verified"),
    _cme_stem_joined("applicant", "categor"), Joined("application", "mode"), "online",
    _cme_stem_joined("cm", "connect"), Joined("current", "level"), Joined("file", "status"),
    Joined("application", "status"), _cme_join("status", "wise"), Joined("request", ("id", "ids")),
    W("gender", "sector", "registered", "unregistered"), "prime small enterprise",
    "seed", "green taxi", "cinema", "agro tourism villa",
))


# The user's decision (2026-10-12, CM Elevate Legacy sheet): a bare "CM-ELEVATE" data
# question that uses no applications-only word defaults to CM Elevate Legacy ("How many
# CM-ELEVATE applications are recorded in each district?" -> the 2,823 sanction records,
# not the 8,627 applications). The applications dataset keeps every question in its own
# vocabulary: applicants, pending, sent back, status, level, sector, verification, on hold …
_CME_APPLICATIONS_VOCAB = Matcher(Alt(
    W("applicant", "applicants", "pending", "pendency"), _cme_join("sent", "back"), _cme_join("send", "back"), "status",
    _cme_level_digit(one_digit=True), W("forwarde", "forwarded", "rejected", "program", "programs")))
_CME_DATA_REQUEST = Matcher(Alt(
    "how many", "number of",
    W("count", "total", "each", "per", "wise", "compare", "summary", "show", "list", "highest", "lowest", "most",
      "top", "recorded", "mapped"),
    _cme_sg("district", "block", "village"), W("constituenc", prefix=True)))


def _pin_cm_elevate_dataset(question: str) -> str:
    """Re-point a bare "CM Elevate" at CM Elevate Legacy when the question asks
    for something only that dataset holds ("total amount disbursed under CM
    Elevate", "CM Elevate loans by lender", "CM-ELEVATE records in FY 2024-25").

    Done ONCE, on the question text, before routing — the same way a misspelled
    scheme name is corrected — so every later pattern check (scheme shortcut,
    clarification gates, follow-ups, the chips) sees one consistent scheme
    instead of each re-deciding. The rewritten question is returned to the user
    as `rewritten_question`, so the reading is visible, not silent."""
    q = question or ""
    if not q or _SCHEME_NAME_MATCHER["CM Elevate Legacy"].search(q):
        return q
    if not _SCHEME_NAME_MATCHER["CM Elevate"].search(q):
        return q
    if not _prefers_cm_elevate_legacy(q):
        return q
    out = _SCHEME_NAME_MATCHER["CM Elevate"].sub("CM Elevate Legacy", q)
    logger.info("CM Elevate dataset pinned to Legacy: %r -> %r", q, out)
    return out


def _unpin_cm_elevate(question: str) -> str:
    """Undo _pin_cm_elevate_dataset. The pin only ever writes "CM Elevate
    Legacy" into a question that named no Legacy form itself, so every
    occurrence came from the pin and reverts cleanly."""
    return _CME_PINNED_NAME.sub("CM Elevate", question or "")


_CME_PINNED_NAME = Matcher(W("CM", case=True), W("Elevate", case=True), W("Legacy", case=True), sep="space")


# ════ answers ═════════════════════════════════════════════════════════════════════════════════════════
# "How many applications have been withdrawn under the Piggery Development Scheme
# or across CM ELEVATE in Ri Bhoi?" asks for TWO scopes. One run wrote
# scheme_name = 'Piggery …' OR scheme_name IN (SELECT scheme_name FROM
# dim_cm_elevate_scheme) — a filter that is always true — and the answer called
# Ri Bhoi's 2,606 applications "the scheme's" (CM-ELEVATE-OFF-024, test run
# 2026-10-06). Both scopes must come back as separate rows.
_CME_OR_ACROSS_MATCH = Matcher("or", W("across", "for", "in", "under"), Opt("the"),
                            Opt(Alt("whole", Seq("all", Opt("of")))), _CME_CM_ELEVATE)


def _cme_programme_or_all_scopes_missing(question: str, schemes: list[str], sql: str) -> "str | None":
    if schemes != ["CM Elevate"] or not sql or not _CME_OR_ACROSS_MATCH.search(question or ""):
        return None
    # already two scopes: a UNION, GROUPING SETS / ROLLUP, or a per-programme FILTER (WHERE scheme_name …)
    for tree in sql_ast.parse(sql):
        if tree.find(exp.SetOperation, exp.GroupingSets, exp.Rollup) is not None or any(
                sql_ast.references_column(f.expression, "scheme_name") for f in tree.find_all(exp.Filter)):
            return None
    return ("this question asks for one programme AND for all of CM Elevate — two scopes. Return one row per "
            "scope, e.g. SELECT '<programme>' AS scope, <measure> FROM curated.v_cm_elevate WHERE scheme_name = "
            "'<programme>' AND <place filter> UNION ALL SELECT 'All CM Elevate programmes', <measure> FROM "
            "curated.v_cm_elevate WHERE <place filter>. Never OR the programme with a list of every programme. "
            "Keep the measure and the place filter exactly as they were.")


# ════ villages ════════════════════════════════════════════════════════════════════════════════════════
_CME_VILLAGE_NAMES: "dict[str, list[dict]] | None" = None


async def _cm_elevate_village_names() -> "dict[str, list[dict]]":
    """UPPER(name) -> villages, for every village / ward in v_cm_elevate (≈2,050
    names, 2,087 codes). Loaded once per process. Placeholder "Unresolved" rows
    excluded (51 applications with no village)."""
    global _CME_VILLAGE_NAMES
    if _CME_VILLAGE_NAMES is None:
        rows = await fetch_rows(
            "SELECT DISTINCT village_code, lgd_village_name, UPPER(lgd_block) AS block, "
            "UPPER(lgd_district) AS district FROM curated.v_cm_elevate "
            "WHERE village_code IS NOT NULL AND entity_type <> 'Unresolved'", [])
        out: dict[str, list[dict]] = {}
        for r in rows:
            n = collapse_ws(str(r["lgd_village_name"] or ""))
            if n and not n.lower().startswith("unresolved"):
                out.setdefault(n.upper(), []).append(
                    {"village_code": r["village_code"], "name": n, "block": r["block"], "district": r["district"]})
        _CME_VILLAGE_NAMES = out
    return _CME_VILLAGE_NAMES


_CME_BLOCKS: "list[str] | None" = None
_FPL_BLOCKS: "list[str] | None" = None


async def _cm_elevate_block_names(scheme: str = "CM Elevate") -> "list[str]":
    """Every lgd_block spelling v_cm_elevate actually stores (66), loaded once.
    CM Elevate Legacy's own list (59) comes from v_cm_elevate_disbursement: it
    stores "TURA MUNICIPAL BOARD" where the registry also carries "TURA MUNICIPAL
    BOARD-MUNICIPAL BOARD", and "Tura Municipal Board" was refused as outside
    Meghalaya (CM Elevate Legacy all-blocks run 2026-09-29)."""
    global _CME_BLOCKS, _CML_BLOCKS, _FPL_BLOCKS
    if scheme == "Focus Plus":
        # Focus Plus names a block by block_name_raw OR, for the ten LGD-only
        # blocks, lgd_block (_focusplus_lgd_only_block): both spellings count.
        # "Mairang Town Committee" fuzzy-snapped to the rural MAIRANG and was
        # answered with Mairang's 402 (all-blocks run 2026-10-02).
        if _FPL_BLOCKS is None:
            rows = await fetch_rows(
                "SELECT DISTINCT UPPER(lgd_block) AS b FROM curated.v_focus_plus WHERE lgd_block IS NOT NULL "
                "UNION SELECT DISTINCT UPPER(block_name_raw) FROM curated.v_focus_plus WHERE block_name_raw IS NOT NULL",
                [])
            _FPL_BLOCKS = sorted(str(r["b"]) for r in rows if r["b"])
        return _FPL_BLOCKS
    if scheme == "CM Elevate Legacy":
        if _CML_BLOCKS is None:
            rows = await fetch_rows("SELECT DISTINCT UPPER(lgd_block) AS b FROM curated.v_cm_elevate_disbursement "
                                    "WHERE lgd_block IS NOT NULL AND lgd_block <> ''", [])
            _CML_BLOCKS = sorted(str(r["b"]) for r in rows)
        return _CML_BLOCKS
    if _CME_BLOCKS is None:
        rows = await fetch_rows("SELECT DISTINCT UPPER(lgd_block) AS b FROM curated.v_cm_elevate "
                                "WHERE lgd_block IS NOT NULL AND lgd_block <> ''", [])
        _CME_BLOCKS = sorted(str(r["b"]) for r in rows)
    return _CME_BLOCKS


def _cme_block_base(name: str) -> str:
    """'TURA MUNICIPAL BOARD-MUNICIPAL BOARD' -> 'TURA'; 'RI-MULIANG' -> 'RIMULIANG'."""
    from app.entity_resolver import _squash, fold   # the resolver's own normalisation
    return _squash(fold(_URBAN_BODY_MATCH.sub("", str(name))))


def _cme_is_ascii_letter(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _cme_ascii_letter_runs(s: str) -> "list[str]":
    """The runs of ASCII letters in `s` ("ri-muliang" -> ["ri", "muliang"])."""
    out, cur = [], ""
    for ch in s:
        if _cme_is_ascii_letter(ch):
            cur += ch
        elif cur:
            out.append(cur)
            cur = ""
    return out + ([cur] if cur else [])


def _cme_skip_ws_dash(t: str, i: int) -> int:
    while i < len(t) and (t[i].isspace() or t[i] == "-"):
        i += 1
    return i


def _cme_runs_end(t: str, p: int, parts: "list[str]") -> int:
    """`parts` written from position p of `t` with only spaces / hyphens between
    them; the end position, or -1."""
    i = p
    for k, part in enumerate(parts):
        if k:
            i = _cme_skip_ws_dash(t, i)
        if not t.startswith(part, i):
            return -1
        i += len(part)
    return i


def _cme_find_runs(t: str, parts: "list[str]") -> bool:
    """`parts` appear somewhere in `t` (lower-cased), spaces / hyphens allowed between."""
    return any(_cme_runs_end(t, p, parts) >= 0 for p in range(len(t)))


def _cme_word_ends(t: str, i: int) -> bool:
    return i >= len(t) or not (t[i].isalnum() or t[i] == "_")


def _cme_urban_suffix_at(t: str, i: int) -> bool:
    """At i of `t` (lower-cased): "municipal", "town committee", "m.b" / "mb" /
    "m b", "t.c" / "tc" / "t c"."""
    if t.startswith("municipal", i):
        return True
    if t.startswith("town", i):
        j = i + 4
        k = j
        while k < len(t) and t[k].isspace():
            k += 1
        if k > j and t.startswith("committee", k):
            return True
    for first, last in (("m", "b"), ("t", "c")):
        if not t.startswith(first, i):
            continue
        j = i + 1
        for mid in ((".", " "), (".",), (" ",), ()):
            k = j
            ok = True
            for m in mid:
                if m == " ":
                    if k < len(t) and t[k].isspace():
                        k += 1
                    else:
                        ok = False
                elif t.startswith(m, k):
                    k += 1
                else:
                    ok = False
            if ok and t.startswith(last, k) and _cme_word_ends(t, k + 1):
                return True
    return False


def _cme_runs_then_urban(t: str, parts: "list[str]") -> bool:
    """The block's letters (not inside a longer letter run on the left) followed
    by an urban-body word: "Tura Municipal Board", "nongpoh-TC"."""
    for p in range(len(t)):
        if p and _cme_is_ascii_letter(t[p - 1]):
            continue
        e = _cme_runs_end(t, p, parts)
        if e >= 0 and _cme_urban_suffix_at(t, _cme_skip_ws_dash(t, e)):
            return True
    return False


def _cme_strip_mb_tc(m: str) -> str:
    """A trailing "MB" / "M.B." / "M B" / "TC" / "T.C." abbreviation removed."""
    low = m.lower()
    core = low[:-1] if low.endswith(".") else low
    for first, last in (("m", "b"), ("t", "c")):
        for mid in ("", ".", " ", ". "):
            v = first + mid + last
            start = len(core) - len(v)
            if core.endswith(v) and (start == 0 or not (core[start - 1].isalnum() or core[start - 1] == "_")):
                return m[:start]
    return m


def _cme_data_block(canon: str, question: str, data_blocks: "list[str]") -> "str | None":
    """The data's own lgd_block for a resolved block, or None to keep it.
    - "X Municipal Board / Town Committee / MB / TC" asked → the urban body X.
    - a resolved name the data does not store → the data spelling with the same
      letters (RI-MULIANG → RI MULIANG), else X's only urban body (JOWAI →
      JOWAI-MUNICIPAL BOARD; CM Elevate has no rural Jowai rows)."""
    want = str(canon).strip().upper()
    base = _cme_block_base(want)
    urban = [b for b in data_blocks if _URBAN_BODY_MATCH.search(b) and _cme_block_base(b) == base]
    q_low = (question or "").lower()
    asked_urban = _cme_runs_then_urban(q_low, _cme_ascii_letter_runs(base.lower()) or [base.lower()]) \
        or bool(_cme_find_runs(q_low, _cme_ascii_letter_runs(want.lower()) or [want.lower()])
                and _URBAN_WORD_MATCH.search(question or ""))
    if asked_urban and len(urban) == 1:
        return urban[0]
    if want in data_blocks:
        return None
    same = [b for b in data_blocks if not _URBAN_BODY_MATCH.search(b) and _cme_block_base(b) == base]
    if len(same) == 1:
        return same[0]
    return urban[0] if len(urban) == 1 else None


async def _cm_elevate_block_from_mention(mention: str, schemes: "list[str] | None") -> "str | None":
    """The stored CM Elevate block a place mention names, when nothing else
    resolved it: an urban body ("Jowai-municipal Board", "Nongpoh TC") or the
    data's exact block spelling. Used before a mention is refused as outside
    Meghalaya (KI-107). CM Elevate Legacy uses its own stored blocks."""
    if schemes not in (["CM Elevate"], ["CM Elevate Legacy"]) or not mention:
        return None
    try:
        data_blocks = await _cm_elevate_block_names(schemes[0])
    except Exception:  # noqa: BLE001
        return None
    m = collapse_ws(str(mention))
    base = _cme_block_base(_cme_strip_mb_tc(m).rstrip(" -"))
    if _URBAN_WORD_MATCH.search(m):
        urban = [b for b in data_blocks if _URBAN_BODY_MATCH.search(b) and _cme_block_base(b) == base]
        if len(urban) == 1:
            return urban[0]
    exact = [b for b in data_blocks if _cme_block_base(b) == base and not _URBAN_BODY_MATCH.search(b)]
    return exact[0] if len(exact) == 1 else None


async def _cm_elevate_blocks_to_data(question: str, resolved: dict, display: dict,
                                     scheme: str = "CM Elevate") -> None:
    """KI-107 (CM Elevate all-blocks run, 2026-09-28): the CM Elevate block
    catalogue is older than its data — 21 of the 66 stored blocks are missing,
    including all 9 urban bodies ("BAGHMARA-MUNICIPAL BOARD"), and 8 catalogue
    names are spelled differently or absent in the data. "Baghmara Municipal
    Board" fuzzy-snapped to the rural BAGHMARA (56 applications instead of 18);
    "Jowai Municipal Board" to JOWAI, which has no rows ("no records"); a
    resolved RI-MULIANG never matched the stored "RI MULIANG". Rewrite the
    resolved block(s) to the spelling the data stores."""
    try:
        data_blocks = await _cm_elevate_block_names(scheme)
    except Exception:  # noqa: BLE001 — without the live list, keep the resolver's answer
        return
    if isinstance(resolved.get("block"), str):
        new = _cme_data_block(resolved["block"], question, data_blocks)
        if new and new != resolved["block"]:
            logger.info("CM Elevate block %r -> stored %r", resolved["block"], new)
            resolved["block"] = new
            display["block"] = _place_title(new)
    if isinstance(resolved.get("block_list"), list):
        resolved["block_list"] = [_cme_data_block(b, question, data_blocks) or b for b in resolved["block_list"]]


# ════ fixed-shape queries and answers ═════════════════════════════════════════════════════════════════
# ── CM Elevate sector facts (deterministic) ──────────────────────────────────
# Two fixed shapes of the CM Elevate sheet that the model path kept getting wrong
# (CM Elevate sheet run 2026-10-10):
#   OFF-012 "applicants associated with the Piggery sector in North Garo Hills" was
#   tied to the Piggery SCHEME (0, "sector isn't tracked") — but sector_id is a
#   field on Poultry, Dairy and Goat applications, and 3 of them there say Piggery;
#   OFF-028 "applications pending in each sector in East Khasi Hills" answered
#   "Poultry 2" for a true 90 pending with no sector recorded and Poultry 0.
_CME_SECTOR_VALUE_MATCH = Matcher(Cap(W("piggery", "poultry", "dairy", "goatery", "goat")), _cme_sg("sector"))
_CME_SECTOR_EACH_MATCH = Matcher(Alt(Seq(W("each", "every", "all", "by", "per"), Opt("the"), _cme_sg("sector"), sep="space"),
                                  _cme_join(("sector", "sectors"), "wise")))
_CME_PENDING_MATCH = Matcher(Alt("pending", _cme_join("on", "hold")))
_CME_SECTOR_FACT_KINDS = ("count", "pending", "programmes")


def _cme_sector_fact_kind(sql: "str | None") -> "str | None":
    """'count' / 'pending' / 'programmes' when `sql` is one of the fixed sector
    queries below (they open with the comment /* cme-sector-<kind> */), else
    None. Read from the tokenizer's comments, so a string literal that happens
    to contain the marker does not count."""
    if not sql:
        return None
    try:
        tokens = sqlglot.tokenize(sql, read=sql_ast.DIALECT)
    except (SqlglotError, ValueError):
        return None
    for tok in tokens:
        for c in tok.comments or ():
            text = str(c).strip().lower()
            if text.startswith("cme-sector-") and text[len("cme-sector-"):] in _CME_SECTOR_FACT_KINDS:
                return text[len("cme-sector-"):]
    return None


def _cme_programme_named(question: str) -> bool:
    q = _CME_SECTOR_VALUE_MATCH.sub(" ", question or "")
    return any(m.search(q) for m in _CME_PROGRAMME_WORDS.values())


def _cme_sector_filters(resolved: dict, alias: str = "") -> "tuple[list[str], list] | None":
    # cm_scheme is NOT a blocker: the resolver reads the "Piggery" of "Piggery sector"
    # as the programme; _cme_sector_query has already checked that no programme is named.
    if any(resolved.get(k) for k in ("village_code_list", "block_list", "district_list", "assembly_constituency")):
        return None
    where, params = [], []
    for key, col in (("village_code", "village_code"), ("block", "lgd_block"), ("district", "lgd_district")):
        v = resolved.get(key)
        if v in (None, ""):
            continue
        if isinstance(v, (list, dict, tuple, set)):
            return None
        params.append(v)
        where.append(f"UPPER({alias}{col}) = UPPER(${len(params)})" if isinstance(v, str)
                     else f"{alias}{col} = ${len(params)}")
    if resolved.get("village_code") is not None:
        where.append(f"{alias}entity_type <> 'Unresolved'")
    return where, params


def _cme_named_programmes(question: str) -> list[str]:
    q = _CME_SECTOR_VALUE_MATCH.sub(" ", question or "")
    return [p for p, m in _CME_PROGRAMME_WORDS.items() if m.search(q)]


def _cme_sector_query(question: str, schemes: list[str], resolved: dict) -> "tuple[str, list, str] | None":
    if schemes != ["CM Elevate"]:
        return None
    q = question or ""
    m = _CME_SECTOR_VALUE_MATCH.search(q)
    progs = _cme_named_programmes(q)
    f = _cme_sector_filters(resolved or {}, "v." if progs else "")
    if f is None:
        return None
    where, params = f
    if progs:
        # "applicants under Dairy and Poultry associated with Poultry sector in <district>"
        # (OFF-014): every named programme gets a row, a programme with none shows 0.
        if not m or _CME_SECTOR_EACH_MATCH.search(q):
            return None
        sec = "goat%" if m.group(1).lower().startswith("goat") else m.group(1).lower()
        params = params + [progs, sec]
        np_, ns = len(params) - 1, len(params)
        cond = (" AND " + " AND ".join(where)) if where else ""
        # sector_id is a plain view column since 2026-10-16 (identical to the JSON
        # key on all 8,867 rows); scheme_specific is not readable by megh_readonly.
        sql = ("/* cme-sector-programmes */ SELECT p.scheme_name, "
               f"COUNT(DISTINCT v.request_id) FILTER (WHERE v.sector_id ILIKE ${ns}) AS sector_applicants, "
               "COUNT(DISTINCT v.request_id) FILTER (WHERE v.sector_id IS NOT NULL) AS sector_recorded, "
               "COUNT(DISTINCT v.request_id) AS programme_total "
               f"FROM UNNEST(${np_}::text[]) AS p(scheme_name) "
               f"LEFT JOIN curated.v_cm_elevate v ON v.scheme_name = p.scheme_name{cond} "
               "GROUP BY p.scheme_name ORDER BY p.scheme_name")
        return sql, params, sql
    wh = (" WHERE " + " AND ".join(where)) if where else ""
    if m and not _CME_SECTOR_EACH_MATCH.search(q):
        sec = "goat%" if m.group(1).lower().startswith("goat") else m.group(1).lower()
        params = params + [sec]
        n = len(params)
        sql = ("/* cme-sector-count */ SELECT scheme_name, "
               f"COUNT(DISTINCT request_id) FILTER (WHERE sector_id ILIKE ${n}) AS sector_applicants, "
               "COUNT(DISTINCT request_id) FILTER (WHERE sector_id IS NOT NULL) AS sector_recorded "
               f"FROM curated.v_cm_elevate{wh} GROUP BY scheme_name "
               "HAVING COUNT(*) FILTER (WHERE sector_id IS NOT NULL) > 0 ORDER BY scheme_name")
        return sql, params, sql
    if _CME_SECTOR_EACH_MATCH.search(q) and _CME_PENDING_MATCH.search(q):
        sql = ("/* cme-sector-pending */ SELECT COALESCE(sector_id, '(not recorded)') AS sector, "
               "COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'On Hold') AS pending_on_hold, "
               "COUNT(DISTINCT request_id) AS applications "
               f"FROM curated.v_cm_elevate{wh} GROUP BY 1 ORDER BY 2 DESC, 1")
        return sql, params, sql
    return None


def _cme_place_words(display: dict) -> str:
    if display.get("village"):
        return f" in {display['village']} village"
    if display.get("block"):
        return f" in {display['block']} block"
    if display.get("district"):
        return f" in {display['district']}"
    return " across Meghalaya"


def _cme_sector_answer(question: str, sql: str, rows: list[dict], display: dict) -> "str | None":
    where = _cme_place_words(display or {})
    kind = _cme_sector_fact_kind(sql)
    if kind == "programmes":
        m = _CME_SECTOR_VALUE_MATCH.search(question or "")
        sector = m.group(1).title() if m else "that"
        lines = [f"- **{_cme_short(r['scheme_name'])}**: {int(_as_number(r.get('sector_applicants')) or 0):,} with sector "
                 f"{sector} (sector recorded on {int(_as_number(r.get('sector_recorded')) or 0):,} of "
                 f"{int(_as_number(r.get('programme_total')) or 0):,} applicants)" for r in rows]
        total = sum(int(_as_number(r.get("sector_applicants")) or 0) for r in rows)
        return (f"CM Elevate applicants associated with the {sector} sector{where}, by programme:\n"
                + "\n".join(lines) + f"\n\nCombined: {total:,}.")
    if kind == "count":
        m = _CME_SECTOR_VALUE_MATCH.search(question or "")
        sector = m.group(1).title() if m else "that"
        total = sum(int(_as_number(r.get("sector_applicants")) or 0) for r in rows)
        recorded = sum(int(_as_number(r.get("sector_recorded")) or 0) for r in rows)
        parts = [f"{_cme_short(r['scheme_name'])} {int(_as_number(r.get('sector_applicants')) or 0):,}" for r in rows]
        out = (f"{total:,} CM Elevate applicant{'s' if total != 1 else ''}{where} "
               f"{'have' if total != 1 else 'has'} their sector recorded as {sector}")
        if parts:
            out += " (" + "; ".join(parts) + ")"
        out += (f". Sector is recorded only on Poultry, Dairy and Goat Farming applications — {recorded:,} "
                f"of them{where} have it recorded.")
        return out
    if kind == "pending":
        items = [f"{r['sector']} {int(_as_number(r.get('pending_on_hold')) or 0):,}" for r in rows]
        total = sum(int(_as_number(r.get("pending_on_hold")) or 0) for r in rows)
        return (f"Pending (verification on hold) CM Elevate applications by sector{where}: " + "; ".join(items)
                + f". Total {total:,}. Sector is recorded only on Poultry, Dairy and Goat Farming applications, "
                  "so most applications fall under (not recorded).")
    return None


def _cme_programme_sector_answer(rows: list[dict], display: dict) -> "str | None":
    """OFF-025: rows grouped by programme AND sector. When the composer gave up, the
    plain row list stated each sector's figures but never a programme's own total
    ("Poultry Farming" was 233 + 8 = 241 applicants across two sector rows). One line
    per programme: its total (when it spans 2+ sectors), then each sector. A request
    has one sector, so the sector figures add up to the programme's."""
    if not rows or len(rows) > 60:
        return None
    sec_col = next((k for k in rows[0] if "sector" in k.lower()), None)
    if sec_col is None or "scheme_name" not in rows[0]:
        return None
    nums = [k for k, _ in _row_metrics(rows[0])]
    if not nums or any(set(r) != set(rows[0]) for r in rows) \
            or set(rows[0]) - set(nums) - {sec_col, "scheme_name"}:
        return None
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(str(r["scheme_name"]), []).append(r)
    if not any(len(g) > 1 for g in groups.values()):
        return None

    def _figs(vals: dict) -> str:
        return ", ".join(f"{_metric_label(k)} {_fmt_num(v)}" for k, v in vals.items())

    lines = []
    for prog, g in groups.items():
        per = [(str(r[sec_col] if r[sec_col] is not None else "(not recorded)"),
                {k: _as_number(r.get(k)) or 0 for k in nums}) for r in g]
        if len(per) == 1:
            lines.append(f"- **{_cme_short(prog)}** — {_figs(per[0][1])} (sector: {per[0][0]}).")
            continue
        tot = {k: sum(v[k] for _, v in per) for k in nums}
        lines.append(f"- **{_cme_short(prog)}** — total {_figs(tot)}. By sector: "
                     + "; ".join(f"{sec}: {_figs(v)}" for sec, v in per) + ".")
    where = _cme_place_words(display or {})
    return (f"CM Elevate{where}, by programme and sector:\n" + "\n".join(lines)
            + "\n\nSector is recorded only on Poultry, Dairy and Goat Farming applications, so the rest "
              "fall under (not recorded).")


# ════ SQL rewrites ════════════════════════════════════════════════════════════════════════════════════
# Every guard below reads and edits the parsed query (SQLGlot, app/sql_ast.py), never
# its text: a pattern over the text read a word inside a literal as a column, missed
# UPPER(col) and "PRIME … (SEED)"'s own parenthesis, and left half-removed clauses.
# A query SQLGlot cannot parse is returned unchanged (sql_guard refuses it anyway).
_CME_CASE_WRAPPERS = (exp.Upper, exp.Lower, exp.Trim, exp.Paren)


def _cme_col(node: "exp.Expression | None", *names: str) -> "exp.Column | None":
    """`node` as a column named one of `names` (lower-case), bare or under
    UPPER / LOWER / TRIM; else None."""
    while isinstance(node, _CME_CASE_WRAPPERS) and node.this is not None:
        node = node.this
    return node if isinstance(node, exp.Column) and node.name.lower() in names else None


def _cme_str(node: "exp.Expression | None") -> "str | None":
    """A string literal's value, else None."""
    return node.this if isinstance(node, exp.Literal) and node.is_string else None


def _cme_literal_in(node: exp.Expression, col: str) -> bool:
    """`col IN ('…', '…')` — a list of string literals only (no subquery, not NOT IN)."""
    return (isinstance(node, exp.In) and not isinstance(node.parent, exp.Not)
            and _cme_col(node.this, col) is not None and node.args.get("query") is None
            and bool(node.expressions) and all(_cme_str(e) is not None for e in node.expressions))


def _cme_in_list(tree: "exp.Expression | None", col: str) -> "exp.In | None":
    """The query's first `col IN ('…', …)` (in reading order), or None."""
    if tree is None:
        return None
    return next((n for n in tree.walk(bfs=False) if _cme_literal_in(n, col)), None)


def _cme_in_values(node: exp.In) -> "list[str]":
    return [e.this for e in node.expressions]


def _cme_scheme_in_values(sql: "str | None") -> "list[str]":
    """The programmes of the query's first `scheme_name IN ('…', …)` list, in
    order; [] when it has none (or cannot be parsed)."""
    for tree in sql_ast.parse(sql):
        node = _cme_in_list(tree, "scheme_name")
        if node is not None:
            return _cme_in_values(node)
    return []


def _cme_district_in_values(sql: "str | None") -> "list[str]":
    """The districts of the query's first `lgd_district IN ('…', …)` list ([] if none)."""
    for tree in sql_ast.parse(sql):
        node = _cme_in_list(tree, "lgd_district")
        if node is not None:
            return _cme_in_values(node)
    return []


def _cme_conjuncts(where: exp.Where) -> list:
    return list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this]


def _cme_drop_conjuncts(tree: exp.Expression, drop) -> int:
    """Remove every AND-ed WHERE condition for which `drop(node)` is true (an
    emptied WHERE disappears); OR-ed conditions and an aggregate's own FILTER
    (WHERE …) are left alone. Returns how many were removed."""
    removed = 0
    for where in list(tree.find_all(exp.Where)):
        if isinstance(where.parent, exp.Filter):
            continue
        conds = _cme_conjuncts(where)
        keep = [c for c in conds if not drop(c)]
        if len(keep) == len(conds):
            continue
        removed += len(conds) - len(keep)
        if keep:
            where.set("this", exp.and_(*keep, copy=False))
        else:
            where.pop()
    return removed


def _cme_simple_select(tree: "exp.Expression | None") -> "exp.Select | None":
    """The query when it is one plain SELECT — no subquery, CTE, JOIN or set operation."""
    if not isinstance(tree, exp.Select) or tree.find(exp.Join) is not None:
        return None
    return tree if sum(1 for _ in tree.find_all(exp.Select)) == 1 else None


def _cme_reads_sector_id(node: "exp.Expression | None") -> bool:
    """`node` reads the sector: scheme_specific ->> 'sector_id' (a JSON key), a
    'sector_id' key argument, or a sector_id column."""
    if node is None:
        return False
    return (any(str(k.this).lower() == "sector_id" for k in node.find_all(exp.JSONPathKey))
            or any(s.lower() == "sector_id" for s in sql_ast.string_literals(node))
            or sql_ast.references_column(node, "sector_id"))


def _cme_eq_on(col: exp.Column, condition: str) -> exp.Expression:
    """`condition` (SQL for one condition) with `col`'s table qualifier on its columns."""
    node = sqlglot.parse_one(condition, read=sql_ast.DIALECT)
    if col.table:
        for c in node.find_all(exp.Column):
            c.set("table", exp.to_identifier(col.table))
    return node


def _cme_question_names(programme: str, question: str) -> bool:
    """The question names this programme (its officer words, else its stored name)."""
    m = _CME_PROGRAMME_WORDS.get(programme)
    if m is not None:
        return m.search(question or "") is not None
    return programme.lower() in (question or "").lower()


def _cm_elevate_split_scheme_in_list(schemes: list[str], sql: str) -> str:
    """KI-069 (CM-ELEVATE-OFF-009b, 029b): "applicants in East Khasi Hills under
    PRIME SEED and PRIME Tourism Vehicle" was answered by ONE merged
    COUNT(DISTINCT request_id) over `scheme_name IN (…)` — 716, with no figure
    for either programme, although rule 4 says a named multi-scheme ask is
    always a GROUP BY scheme_name breakdown plus the combined total. Add
    scheme_name to the SELECT and the GROUP BY; the combined total is then
    stated by _cme_multi_scheme_total. request_id never repeats ACROSS
    programmes (sum of per-programme distinct = 8,600 = statewide distinct), so
    that sum is exact."""
    if schemes != ["CM Elevate"] or not sql:
        return sql
    sel = _cme_simple_select(sql_ast.parse_one(sql))
    node = _cme_in_list(sel, "scheme_name")
    if sel is None or node is None or len(node.expressions) < 2 or sel.args.get("distinct") is not None:
        return sql
    items = list(sel.expressions)
    if any(sql_ast.references_column(e, "scheme_name") for e in items) \
            or not any(e.find(exp.Count) is not None for e in items):
        return sql
    sel.set("expressions", [exp.column("scheme_name")] + items)
    group = sel.args.get("group")
    if group is not None:
        group.set("expressions", [exp.column("scheme_name")] + list(group.expressions))
    else:
        sel.group_by("scheme_name", copy=False)
    if sql_ast.outer_limit(sel) == 1:
        sel.set("limit", None)
    logger.info("CM Elevate: split a merged multi-programme count by scheme_name (rule 4)")
    return sql_ast.to_sql(sel)


def _cme_status_eq(node: exp.Expression) -> bool:
    """[t.]data_verified = '<value>'."""
    return (isinstance(node, exp.EQ) and isinstance(node.this, exp.Column)
            and node.this.name.lower() == "data_verified" and _cme_str(node.expression) is not None)


def _cme_on_hold_eq(node: exp.Expression) -> bool:
    """[t.]data_verified = 'On Hold' (any case)."""
    return _cme_status_eq(node) and node.expression.this.lower() == "on hold"


def _cme_plain_count(node: exp.Expression) -> bool:
    """COUNT(*) or COUNT(DISTINCT [t.]request_id) with no FILTER of its own."""
    if not isinstance(node, exp.Count) or isinstance(node.parent, exp.Filter):
        return False
    arg = node.this
    if isinstance(arg, exp.Star):
        return True
    return (isinstance(arg, exp.Distinct) and len(arg.expressions) == 1
            and isinstance(arg.expressions[0], exp.Column) and arg.expressions[0].name.lower() == "request_id")


def _cm_elevate_sector_zero_groups(schemes: list[str], sql: str) -> str:
    """KI-072 (CM-ELEVATE-OFF-028b): "applications pending in each sector in
    West Khasi Hills" filtered data_verified = 'On Hold' in the WHERE and then
    grouped by sector, so every sector with 0 pending vanished and the answer
    said "No other sectors are listed" — the district has 17 sector-tagged
    applications (Poultry 9, Dairy 4, Piggery 3, Goatery 1), none on hold. Move
    the status test into COUNT(*) FILTER (…), the shape the pendency-by-sector
    few-shot already uses, so a sector with none shows 0."""
    if schemes != ["CM Elevate"] or not sql:
        return sql
    sel = _cme_simple_select(sql_ast.parse_one(sql))
    if sel is None or sel.args.get("group") is None or not any(_cme_reads_sector_id(e) for e in sel.expressions):
        return sql
    preds = [n for n in sel.find_all(exp.EQ) if _cme_status_eq(n)]
    counts = [n for e in sel.expressions for n in e.find_all(exp.Count) if _cme_plain_count(n)]
    if len(preds) != 1 or len(counts) != 1:
        return sql
    pred = preds[0]
    where = sel.args.get("where")
    if where is None or not any(c is pred for c in _cme_conjuncts(where)):
        return sql  # the status test is not a plain AND of the WHERE (inside a FILTER, an OR …)
    cond = pred.copy()
    _cme_drop_conjuncts(sel, lambda c: c is pred)
    count = counts[0]
    count.replace(exp.Filter(this=count.copy(), expression=exp.Where(this=cond)))
    logger.info("CM Elevate: moved %s into COUNT FILTER so zero-count sectors stay listed",
                cond.sql(dialect=sql_ast.DIALECT))
    return sql_ast.to_sql(sel)


# How an officer names each programme — ONE vocabulary, used two ways: on the
# question (_CME_PROGRAMME_WORDS, a word Matcher per programme) and on a programme
# LITERAL taken from the SQL tree (_cme_value_names_programme, plain string tests).
# A phrase in spaces (" seed ") must be a whole word; the others may run on into a
# longer word ("goatery", "poultry's"), and a two-word phrase also matches written as
# one word ("agrotourism", "motorcaravan").
_CME_PROGRAMME_PHRASES = {
    "PRIME Small Enterprise Empowerment and Development (SEED)": ("small enterprise", " seed "),
    "Meghalaya Piggery Development Scheme": ("piggery",), "Meghalaya Poultry Farming Scheme": ("poultry",),
    "PRIME Tourism Vehicle Scheme": ("tourism vehicle",),
    "PRIME Agriculture Response Vehicle Scheme": ("agriculture response", "response vehicle"),
    "Meghalaya Dairy Development Scheme": ("dairy",), "Meghalaya Any Business Venture Scheme": ("any business",),
    "Meghalaya Goat Farming Scheme": ("goat",), "Meghalaya Warehouse Scheme": ("warehouse",),
    "Meghalaya Sericulture & Weaving Scheme": ("sericulture", "weaving"),
    "Chief Minister's Green Taxi Scheme": ("green taxi",),
    "Meghalaya Sports & Wellness Centre Scheme": ("sports", "wellness"),
    "Agro Tourism Villa Scheme": ("agro tourism",),
    "Meghalaya Cinema Theatre Scheme": ("cinema",), "Meghalaya Motorcaravan Scheme": ("motor caravan",),
}


def _cme_phrase_node(ph: str) -> Node:
    if ph.startswith(" "):
        return W(ph.strip())
    parts = ph.split()
    if len(parts) == 1:
        return _cme_has(parts[0])
    squashed = "".join(parts)
    return Alt(Seq(*parts[:-1], W(parts[-1], prefix=True)), _cme_has(squashed))


_CME_PROGRAMME_WORDS = {p: Matcher(Alt(*[_cme_phrase_node(ph) for ph in phs]))
                        for p, phs in _CME_PROGRAMME_PHRASES.items()}


def _cme_value_names_programme(value: str, programme: str) -> bool:
    """A literal's value names this programme by its officer words."""
    words = "".join(ch if ch.isalnum() else " " for ch in str(value).lower()).split()
    spaced, squashed = " " + " ".join(words) + " ", "".join(words)
    for ph in _CME_PROGRAMME_PHRASES.get(programme, ()):
        if ph.startswith(" "):
            if ph in spaced:
                return True
        elif ph in spaced or ph.replace(" ", "") in squashed:
            return True
    return False


_CME_SECTOR_WHOLE_Q = Matcher(Alt(
    _CmeNear(W("each", "every", "all", "by", "wise", "breakdown", "distribution"), _cme_sg("sector"), 20, stops="?"),
    _cme_join(("sector", "sectors"), ("wise", "breakdown", "distribution"))))


def _cme_scheme_eq(node: exp.Expression) -> bool:
    """[t.]scheme_name = '<programme>'."""
    return isinstance(node, exp.EQ) and _cme_col(node.this, "scheme_name") is not None \
        and _cme_str(node.expression) is not None


def _cme_is_scheme_name(node: exp.Expression) -> bool:
    node = node.unalias() if isinstance(node, exp.Alias) else node
    return isinstance(node, exp.Column) and node.name.lower() == "scheme_name"


def _cm_elevate_sector_all_programmes(question: str, schemes: list[str], sql: str) -> str:
    """KI-111 (CM Elevate all-blocks run, 2026-09-28): "applicants associated with
    each sector in West Khasi Hills" came back with scheme_name IN ('…Poultry…',
    '…Dairy…') — Goat Farming (the only Goatery rows) silently dropped — and
    grouped by scheme_name too, so no sector's total was stated. A sector
    question that names NO programme covers every programme: drop the invented
    scheme filter and the scheme_name grouping. A named programme is kept."""
    if schemes != ["CM Elevate"] or not sql or not _CME_SECTOR_WHOLE_Q.search(question or ""):
        return sql
    q = question or ""
    tree = sql_ast.parse_one(sql)
    if tree is None or not _cme_reads_sector_id(tree):
        return sql
    before = sql_ast.to_sql(tree)
    in_node = _cme_in_list(tree, "scheme_name")
    # a programme equality AND-ed with another condition (a lone one is the whole scope)
    eq_node = next((c for w in tree.find_all(exp.Where) if not isinstance(w.parent, exp.Filter)
                    and len(_cme_conjuncts(w)) > 1 for c in _cme_conjuncts(w) if _cme_scheme_eq(c)), None)
    lits = (_cme_in_values(in_node) if in_node is not None else []) \
        + ([eq_node.expression.this] if eq_node is not None else [])
    if not lits or any(_cme_question_names(x, q) for x in lits):
        return sql
    _cme_drop_conjuncts(tree, lambda c: c is in_node or c is eq_node)
    sel = sql_ast.outer_select(tree)
    if sel is not None and any(_cme_is_scheme_name(e) for e in sel.expressions):
        items = list(sel.expressions)
        idx = next((i for i, e in enumerate(items[:-1]) if _cme_is_scheme_name(e)), None)
        if idx is not None:
            sel.set("expressions", items[:idx] + items[idx + 1:])
        group = sel.args.get("group")
        if group is not None:
            keep = [g for g in group.expressions if not _cme_is_scheme_name(g)]
            if keep and len(keep) < len(group.expressions):
                group.set("expressions", keep)
        order = sel.args.get("order")
        if order is not None:
            keep = [o for o in order.expressions if not _cme_is_scheme_name(o.this)]
            if keep and len(keep) < len(order.expressions):
                order.set("expressions", keep)
    out = sql_ast.to_sql(tree)
    if out == before:
        return sql
    logger.info("CM Elevate: sector question names no programme — dropped the invented scheme filter")
    return out


_CME_LITERAL_COLS = ("scheme_name", "lgd_block", "lgd_district")


async def _cm_elevate_fix_literals(schemes: list[str], sql: str) -> str:
    """KI-112 (CM Elevate all-blocks run, 2026-09-28): the generator mistyped stored
    names inside SQL literals — `scheme_name IN ('PRIME Tourism Vehicle', …)` (no
    " Scheme": Mawpat's 54 dropped from a two-programme answer), `lgd_block =
    'SHILLONG-MUNICIPAL_BOARD'` (0 instead of 11), `lgd_district = 'WEST JAINTEIA
    HILLS'` (0). A literal that matches no stored value is snapped to the ONE stored
    value it clearly names: a programme by its words (_CME_PROGRAMME_PHRASES), a block
    by its letters (punctuation / underscore / spacing ignored), a district by a
    single close spelling. Anything that matches nothing unambiguously is left."""
    if schemes != ["CM Elevate"] or not sql or not sql_ast.filtered_by(sql, *_CME_LITERAL_COLS):
        return sql
    import difflib
    try:
        blocks = await _cm_elevate_block_names()
    except Exception:  # noqa: BLE001
        blocks = []
    districts = [str(d).upper() for d in canonical_names("CM Elevate", "district")] or list(_MEGHALAYA_12_DISTRICTS)
    programmes = list(_CME_PROGRAMME_WORDS)

    def sq(x: object) -> str:
        return "".join(ch for ch in str(x).upper() if ch.isascii() and ch.isalnum())

    def fix(col: str, v: str) -> "str | None":
        if col == "scheme_name":
            if v in programmes:
                return None
            hits = [p for p in programmes if _cme_value_names_programme(v, p)]
            return hits[0] if len(hits) == 1 else None
        if col == "lgd_block":
            if not blocks or v.upper() in blocks:
                return None
            hits = [b for b in blocks if sq(b) == sq(v)]
            return hits[0] if len(hits) == 1 else None
        if v.upper() in districts or not districts:
            return None
        same = [d for d in districts if sq(d) == sq(v)]       # "RI-BHOI" -> "RI BHOI"
        if len(same) == 1:
            return same[0]
        # a clear winner: "WEST JAINTEIA HILLS" is 0.97 to West and 0.92 to East Jaintia
        scored = sorted(((difflib.SequenceMatcher(None, v.upper(), d).ratio(), d) for d in districts),
                        reverse=True)
        best, second = scored[0], (scored[1] if len(scored) > 1 else (0.0, ""))
        return best[1] if best[0] >= 0.9 and best[0] - second[0] >= 0.04 else None

    changed: list = []

    def snap(col: str):
        def mapping(v: str) -> "str | None":
            new = fix(col, v)
            if new is not None and new != v:
                changed.append((v, new))
            return new
        return mapping

    out = sql
    for col in _CME_LITERAL_COLS:
        out = sql_ast.replace_string_literals(out, snap(col), [col])
    if not changed or out == sql:
        return sql
    logger.info("CM Elevate: snapped mistyped literals to stored names %s", changed)
    return out


_CME_FAMILY_WORDS_MATCH = Matcher(Alt(
    Seq(Alt(W("vehicle", "livestock", "animal", "prime", "tourism", "enterprise", "business", "farming", "family",
              "group"), W("agri", prefix=True)),
        _cme_sg("scheme", "programme", "program")),
    Seq(_cme_sg("scheme", "programme", "program"), Alt("like", "such as", "including"), sep="space")))


def _cm_elevate_unasked_programme_filter(question: str, schemes: list[str], sql: str) -> str:
    """KI-116 (CM Elevate all-villages run, 2026-09-28): "applicants under each CM
    ELEVATE program in MIKKA SIMDAM, Resubelpara block" came back with
    scheme_name IN ('…Piggery…', '…Poultry…', …) — a list nobody asked for — and
    the village's only programme (Agriculture Response Vehicle) fell outside it:
    "no matching records". A programme filter whose programmes the question never
    names is dropped (the per-programme grouping stays). A question naming a
    programme, or a programme FAMILY ("vehicle schemes"), keeps its filter."""
    if schemes != ["CM Elevate"] or not sql or _CME_FAMILY_WORDS_MATCH.search(question or ""):
        return sql
    q = question or ""
    tree = sql_ast.parse_one(sql)
    node = _cme_in_list(tree, "scheme_name")
    if node is None:
        return sql
    lits = _cme_in_values(node)
    if any(_cme_question_names(x, q) for x in lits):
        return sql
    if not _cme_drop_conjuncts(tree, lambda c: c is node):
        return sql
    logger.info("CM Elevate: dropped a programme IN-list the question never named: %s", lits)
    return sql_ast.to_sql(tree)


_CME_PERSON_COUNT_Q = Matcher(Alt(W("applicant", "applicants", "beneficiary", "beneficiaries"),
                                  Seq(W("unique", "distinct"), _cme_sg("application"), sep="space")))


def _cm_elevate_compare_by_district(question: str, schemes: list[str], sql: str) -> str:
    """"Compare applicant counts for Poultry and Tourism Vehicle across East Jaintia
    Hills and East Khasi Hills" grouped by scheme_name only, merging the two
    districts into one figure per programme (rule 16 in the prompt did not hold;
    CM Elevate sheet OFF-027, 3 of 6 runs, 2026-10-10). A query that filters two
    or more districts and groups without lgd_district gets it added to both the
    SELECT list and the GROUP BY."""
    if schemes != ["CM Elevate"] or not sql:
        return sql
    # "more in A than in B" needs the places side by side, not a row each
    # (c11 _two_place_comparison_issue sends that to repair; splitting here
    # would only make the guard reject it again).
    if _C11_MORE_THAN.search(question or ""):
        return sql
    tree = sql_ast.parse_one(sql)
    node = _cme_in_list(tree, "lgd_district")
    if not isinstance(tree, exp.Select) or node is None or len(node.expressions) < 2:
        return sql
    group = tree.args.get("group")
    if group is None or sql_ast.references_column(group, "lgd_district"):
        return sql
    # Already compared side by side — one column per district, COUNT(...)
    # FILTER (WHERE lgd_district = ...) or a CASE on lgd_district inside the
    # aggregate ("schemes with more applicants in A than in B"). Grouping by
    # lgd_district as well would put each district on its own row and leave
    # the other district's column empty, so the comparison can never hold.
    if any(sql_ast.references_column(n, "lgd_district")
           for n in (*tree.find_all(exp.Filter), *tree.find_all(exp.Case))):
        return sql
    tree.set("expressions", [exp.column("lgd_district")] + list(tree.expressions))
    group.set("expressions", list(group.expressions) + [exp.column("lgd_district")])
    logger.info("CM Elevate: multi-district comparison grouped by lgd_district too")
    return sql_ast.to_sql(tree)


def _cme_count_reads_view(c: exp.Count) -> bool:
    """The COUNT's own SELECT reads curated.v_cm_elevate directly (FROM / JOIN),
    so its rows are application records — not a COUNT(*) over dim_cm_elevate_scheme
    ("how many schemes" = 15) or over an already-aggregated subquery."""
    sel = c.find_ancestor(exp.Select)
    if sel is None:
        return False
    return any(isinstance(src, exp.Table) and src.name.lower() == "v_cm_elevate"
               for src in _mg_sources(sel))


def _cm_elevate_applicants_distinct(question: str, schemes: list[str], sql: str) -> str:
    """CM Elevate applications AND applicants = COUNT(DISTINCT request_id).
    Ingestion team decision 2026-10-16 (semantic.metric_definitions
    cm_elevate_applications): an application is a distinct request_id. 27
    Piggery (22) / Poultry (5) applications appear on two records identical on
    every visible field, so COUNT(*) gives 8,867 records against 8,840
    applications. Before that, "applications" alone was COUNT(*) and only
    applicants / beneficiaries were deduplicated (OFF-009 re-run 2026-10-02: "applicants in Ri
    Bhoi under Goat Farming and Poultry Farming" ran COUNT(*) AS applicants, 242
    Poultry against 241). Now every COUNT(*) whose SELECT reads v_cm_elevate
    directly becomes COUNT(DISTINCT request_id), FILTER clauses kept."""
    if schemes != ["CM Elevate"] or not sql:
        return sql
    names = sql_ast.tables(sql)
    if "v_cm_elevate" not in names:
        return sql

    def fn(tree: exp.Expression) -> None:
        for c in list(tree.find_all(exp.Count)):
            if isinstance(c.this, exp.Star) and _cme_count_reads_view(c):
                c.set("this", exp.Distinct(expressions=[exp.column("request_id")]))

    out = sql_ast.transform(sql, fn)
    if out != sql:
        logger.info("CM Elevate: COUNT(*) over v_cm_elevate counted as DISTINCT request_id (2026-10-16)")
    return out


_CME_LEVEL_PENDING_Q = Matcher(Alt(
    _CmeNear("pending", _cme_level_digit(one_digit=False), 25),
    _CmeNear(_cme_level_digit(one_digit=True), "pending", 25)))


def _cm_elevate_level_pending(question: str, schemes: list[str], sql: str) -> str:
    """KI-070 (CM-ELEVATE-OFF-018a): "applications pending at level 2" was read
    as level 2 AND data_verified = 'On Hold' — 0 rows (no level-2 application
    is on hold) — and composed as "the data doesn't cover" it. An application
    pending AT a level is one whose file currently sits at that level
    (current_level); all 165 level-2 applications have file_status 'Pending'.
    Drop the On Hold conjunct when the level itself is the scope. An explicit
    "on hold" in the question keeps it."""
    if (schemes != ["CM Elevate"] or not sql or not _CME_LEVEL_PENDING_Q.search(question or "")
            or _CME_ON_HOLD.search(question or "")):
        return sql
    tree = sql_ast.parse_one(sql)
    if tree is None or not sql_ast.references_column(tree, "current_level") \
            or not any(_cme_on_hold_eq(n) for n in tree.find_all(exp.EQ)):
        return sql
    if not _cme_drop_conjuncts(tree, _cme_on_hold_eq):
        return sql
    logger.info("CM Elevate: 'pending at level N' — dropped the On Hold filter, level is the scope")
    return sql_ast.to_sql(tree)


# Product decision 2026-09-28 (tester sheet OFF-015/016/017/030): CM Elevate
# "status" = current_file_status, send-back spellings merged (rule 7).
_CME_FILE_STATUS_EXPR = ("CASE WHEN LOWER(current_file_status) LIKE 'sendback%' THEN 'Sent back' "
                         "WHEN current_file_status IS NULL THEN '(not recorded)' "
                         "ELSE INITCAP(LOWER(current_file_status)) END")
_CME_STATUS_Q = Matcher(Alt(
    _cme_join("status", ("wise", "distribution", "breakdown", "split", "count", "counts")),
    Seq(W("application", "current", "file", "overall"), "status"), Seq("status", W("of", "for", "in")),
    "by status", "each status"))
_CME_VERIFICATION_Q = Matcher(Alt(
    # no word boundaries in the old pattern: "on hold" may end / start inside a word
    Pred(lambda w: "verif" in w.lower()), _CME_ON_HOLD_ANYWHERE,
    W("valid", "invalid", "wrong", "pending", "pendency", "approve", "approved", "rejected", "decision"),
    W("withdraw", prefix=True)))


def _cme_dv_group_exprs(node: exp.Expression) -> list:
    """The data_verified GROUPING expressions under `node`: a bare [t.]data_verified
    or COALESCE([t.]data_verified, '<text>'). One being compared or filtered on
    (=, <>, IS, IN, LIKE, a WHERE / FILTER) is a verification filter, not the grouping."""
    found: list = []

    def is_dv(n: exp.Expression) -> bool:
        return isinstance(n, exp.Column) and n.name.lower() == "data_verified"

    def visit(n: exp.Expression) -> None:
        if isinstance(n, (exp.Predicate, exp.Where)):
            return
        if isinstance(n, exp.Coalesce) and is_dv(n.this) and len(n.expressions) == 1 \
                and _cme_str(n.expressions[0]) is not None:
            found.append(n)
            return
        if is_dv(n):
            found.append(n)
            return
        for child in n.iter_expressions():
            visit(child)

    visit(node)
    return found


def _cm_elevate_status_is_file_status(question: str, schemes: list[str], sql: str) -> str:
    """A plain CM Elevate "status" question grouped by data_verified is rewritten
    to group by current_file_status. Comparisons on data_verified (a verification
    filter the question asked for) are never touched; a question with any
    verification / pending / on-hold / decision word keeps data_verified."""
    q = question or ""
    if schemes != ["CM Elevate"] or not sql or not _CME_STATUS_Q.search(q) or _CME_VERIFICATION_Q.search(q):
        return sql
    tree = sql_ast.parse_one(sql)
    sel = sql_ast.outer_select(tree) if tree is not None else None
    if sel is None or not sql_ast.has_group_by(tree) or not sql_ast.references_column(tree, "data_verified"):
        return sql
    heads = [n for e in sel.expressions for n in _cme_dv_group_exprs(e)]
    if not heads:
        return sql                       # data_verified only inside a WHERE / FILTER — not the grouping
    group = sel.args.get("group")
    targets = heads + ([n for g in group.expressions for n in _cme_dv_group_exprs(g)] if group is not None else [])
    status = sqlglot.parse_one(_CME_FILE_STATUS_EXPR, read=sql_ast.DIALECT)
    for n in targets:
        new = status.copy()
        if n.parent is sel:              # a bare select item keeps a name: "status", not "case"
            new = exp.alias_(new, "status")
        n.replace(new)
    logger.info("CM Elevate: 'status' grouped by current_file_status, not data_verified (2026-09-28)")
    return sql_ast.to_sql(tree)


def _cme_level_eq(node: exp.Expression) -> bool:
    """[LOWER(][t.]current_level[)] = '<any level literal>'."""
    return isinstance(node, exp.EQ) and _cme_col(node.this, "current_level") is not None \
        and _cme_str(node.expression) is not None


_CME_LEVEL_WORDS_Q = Matcher(Alt(W("level", "levels", "stage", "stages"), _cme_level_digit(one_digit=False)))
_CME_PENDING_WORD_Q = Matcher(W("pending", "pendency"))
_CME_LEVEL_STAGE_Q = Matcher(Alt(_cme_level_digit(one_digit=False), W("level", "levels", "stage")))


def _cm_elevate_unasked_level_filter(question: str, schemes: list[str], sql: str) -> str:
    """KI-120 (final pass 2026-09-28): "pending in QUININE NONGLADEW, Umling block"
    got `current_level = 'quinary'` — a level the village name suggested to the
    generator — and a confident 0 against 2. A level filter the question never
    asks for (no "level" / "stage") is dropped."""
    if schemes != ["CM Elevate"] or not sql or _CME_LEVEL_WORDS_Q.search(question or ""):
        return sql
    tree = sql_ast.parse_one(sql)
    if tree is None or not any(_cme_level_eq(n) for n in tree.find_all(exp.EQ)):
        return sql
    if not _cme_drop_conjuncts(tree, _cme_level_eq):
        return sql
    logger.info("CM Elevate: dropped a current_level filter the question never asked for")
    return sql_ast.to_sql(tree)


_CME_DECISION_STATES = ("approved", "rejected", "pending")


def _cme_decision_pred(node: exp.Expression) -> "tuple[exp.Column, str] | None":
    """[LOWER|UPPER(][t.]current_file_status[)] =/LIKE/ILIKE 'approved|rejected|pending'
    -> (the column, the state's stored spelling); else None."""
    if not isinstance(node, (exp.EQ, exp.Like, exp.ILike)):
        return None
    for col_side, val_side in ((node.this, node.expression), (node.expression, node.this)):
        col, val = _cme_col(col_side, "current_file_status"), _cme_str(val_side)
        if col is not None and val is not None and val.lower() in _CME_DECISION_STATES:
            return col, val.lower().title()
    return None


def _cm_elevate_decision_status_column(schemes: list[str], sql: str) -> str:
    """KI-074 follow-on (found by a generalisation probe, 2026-09-27): "how many
    applications were rejected in Ri Bhoi" filtered current_file_status =
    'rejected' — a value that column never holds (forward / sendback /
    resubmit) — and a confident 0 went out against a true 27. The decision
    states lived only in scheme_specific ->> 'file_status', and this pointed the
    predicate there.

    2026-10-16: scheme_specific is locked from megh_readonly (ingestion team), so
    Approved / Rejected are answered "not available" before any SQL is written
    (_MEASURE_HOLDERS "approval or rejection decisions"). What is left here is
    "pending" on current_file_status, which becomes data_verified = 'On Hold'
    (the vocabulary rule, kept by user decision 2026-10-16)."""
    if schemes != ["CM Elevate"] or not sql:
        return sql

    def fn(tree: exp.Expression) -> None:
        for n in list(tree.find_all(exp.EQ, exp.Like, exp.ILike)):
            hit = _cme_decision_pred(n)
            if hit is not None and hit[1] == "Pending":
                n.replace(_cme_eq_on(hit[0], "data_verified = 'On Hold'"))

    out = sql_ast.transform(sql, fn)
    if out != sql:
        logger.info("CM Elevate: current_file_status = 'pending' read as data_verified = 'On Hold'")
    return out


def _cm_elevate_pending_without_level(question: str, schemes: list[str], sql: str) -> str:
    """The other side of KI-070, found in its own re-test (2026-09-27): "which
    programs have the highest number of pending applications" — no level named —
    came back as current_level = 'level1' (SEED 3,633 "pending" against a true
    286 on hold). A plain "pending" is data_verified = 'On Hold' (vocabulary);
    a level filter the question never asked for is swapped back to it."""
    q = question or ""
    if (schemes != ["CM Elevate"] or not sql or not _CME_PENDING_WORD_Q.search(q)
            or _CME_LEVEL_STAGE_Q.search(q)):
        return sql
    tree = sql_ast.parse_one(sql)
    if tree is None or any(_cme_on_hold_eq(n) for n in tree.find_all(exp.EQ)):
        return sql
    # any level literal, not just 'level<d>': "pending in 12TH MER" came back as
    # current_level = 'level12' (final pass 2026-09-28, KI-120)
    levels = [n for n in tree.find_all(exp.EQ) if _cme_level_eq(n)]
    if len(levels) != 1:
        return sql
    levels[0].replace(_cme_eq_on(_cme_col(levels[0].this, "current_level"), "data_verified = 'On Hold'"))
    logger.info("CM Elevate: plain 'pending' was filtered on current_level — restored data_verified = 'On Hold'")
    return sql_ast.to_sql(tree)


# ════ verify and repair ═══════════════════════════════════════════════════════════════════════════════
# Keys read live from curated.v_cm_elevate.scheme_specific on 2026-09-27
# (jsonb_object_keys): populated on every row except sector_id. Since
# 2026-10-16 megh_readonly may not read scheme_specific at all; this list only
# lets the verifier-complaint filter recognise a key, it is not an invitation.
_CME_LIVE_JSON_KEYS = ("file_status", "sector_id", "gender_id", "occupation_id")


def _cme_resolved_places_in_sql(resolved: "dict | None", sql: str) -> bool:
    """Every resolved place value (district / block / village_code) appears in one
    of the SQL's literals (read from the tree: a comment or a column name does not count)."""
    vals = [str(resolved.get(k)) for k in ("district", "block", "village_code") if (resolved or {}).get(k)]
    lits = [str(x).upper() for x in sql_ast.string_literals(sql or "") + sql_ast.number_literals(sql or "")]
    return bool(vals) and all(any(v.upper() in lit for lit in lits) for v in vals)


# ════ answer numbers and guarantees ═══════════════════════════════════════════════════════════════════
# ── CM Elevate answer guarantees (use-case QA 2026-09-27) ────────────────────
# The SQL was right in every one of these; the composed TEXT dropped or garbled
# what the use case asks for: a programme list naming 5 of 15 (KI-068 part 2),
# no combined total beside a programme split (KI-069), no difference in a
# comparison (KI-071), a scheme x sector x pendency result written as "9 and 3
# for Poultry and Piggery respectively … 1, 0, 14, 5, 0, and 0 for each
# corresponding row" (KI-073), and a genuine 0 hedged as "doesn't cover"
# (KI-070). Same project pattern as the Focus Plus guarantees: check the text
# against the rows, and rebuild or append only what is missing.
_CME_LABEL_STOP = {"meghalaya", "prime", "scheme", "development", "farming", "and", "the", "of",
                   "chief", "minister", "minister's", "centre", "hills", "not", "block"}
_CME_GARBLED = Matcher(Alt("respectively", Seq("corresponding", _cme_sg("row")), "for each row", "each row"))


def _cme_drop_meghalaya_scheme(s: str) -> str:
    """'Meghalaya X Scheme' -> 'X' (a leading "Meghalaya " and a trailing " Scheme")."""
    if s.startswith("Meghalaya") and s[9:10].isspace():
        s = s[9:].lstrip()
    if s.endswith("Scheme") and s[-7:-6].isspace():
        s = s[:-6].rstrip()
    return s


def _cme_short(label: object) -> str:
    """'Meghalaya Piggery Development Scheme' -> 'Piggery Development'; district
    capitals -> title case; anything else as stored."""
    s = _fp_title(label)   # title-case stored capitals first, so "PRIME SEED" survives
    if s == "PRIME Small Enterprise Empowerment and Development (SEED)":
        s = "PRIME SEED"
    return _cme_drop_meghalaya_scheme(s)


_CME_WHOLE_LIST_Q = Matcher(Alt(
    W("each", "every", "wise", "distribution", "breakdown"), _cme_join("break", "down"),
    Seq("all", Opt("the"), _cme_sg("programme", "program", "scheme", "district", "block", "village", "sector"))))


def _cme_complete_list(question: str, answer: str, rows: list[dict]) -> str:
    """KI-068 (text half): "applicants under each CM ELEVATE program" named 5 of
    the 15 programmes ("the remaining schemes range from 4 … up to 3,617").
    When the question asks for EVERY value (each / distribution / breakdown)
    and some row's figure is not beside its label, rebuild the list from the
    rows. A "which is highest" question naming its top few is left alone."""
    if not _CME_WHOLE_LIST_Q.search(question or "") or not 2 <= len(rows) <= 40:
        return answer
    nums = _fp_numeric_cols(rows)
    labels = [k for k in rows[0] if k not in nums]
    if len(nums) != 1 or len(labels) != 1:
        return answer
    lab, met = labels[0], nums[0]
    sents = _cme_sentences(answer)
    # "…Warehouse, Agriculture Response Vehicle, Goat Farming and Any Business Venture
    # had 4, 4, 4, 1, and 1 applicants respectively" (Laskein, all-blocks run
    # 2026-09-28) states every figure but not beside its name — rebuilt too.
    if not _CME_GARBLED.search(answer or "") and all(
            _as_number(r.get(met)) is None or _cme_row_stated(
                sents, [r.get(lab) if r.get(lab) is not None else "(not recorded)"], _as_number(r.get(met)))
            for r in rows):
        return answer
    name = _FP_LABEL_NAME.get(lab, lab.replace("_", " "))
    items = [f"{_cme_short(r[lab]) if r.get(lab) is not None else '(not recorded)'} "
             f"{_fmt_num(_as_number(r.get(met)))}" for r in rows if _as_number(r.get(met)) is not None]
    total = sum(_as_number(r.get(met)) or 0 for r in rows)
    logger.info("CM Elevate: rebuilt a %s list — the answer left out some %s", name, name)
    return (f"{_metric_label(met).capitalize()} by {name} ({len(items)}): " + "; ".join(items)
            + f". Total {_fmt_num(total)}.")


def _cme_label_keys(label: object) -> list[str]:
    words = _cme_label_words(str(label).lower())
    keys = [w for w in words if w not in _CME_LABEL_STOP and len(w) > 2]
    return keys or words


def _cme_label_words(s: str) -> "list[str]":
    """Runs of a-z / apostrophe starting with a letter, 2+ characters long."""
    out, i, n = [], 0, len(s)
    while i < n:
        if "a" <= s[i] <= "z":
            j = i + 1
            while j < n and ("a" <= s[j] <= "z" or s[j] == "'"):
                j += 1
            if j - i >= 2:
                out.append(s[i:j])
            i = j
        else:
            i += 1
    return out


def _cme_split_sentences(text: str) -> "list[str]":
    """Split at whitespace after '.', ';', '!' or '?', and at every run of newlines."""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        if text[i].isspace() and i and text[i - 1] in ".;!?":
            j = i
            while j < n and text[j].isspace():
                j += 1
        elif text[i] == "\n":
            j = i
            while j < n and text[j] == "\n":
                j += 1
        else:
            i += 1
            continue
        out.append(text[start:i])
        start = i = j
    out.append(text[start:])
    return out


def _cme_sentences(answer: str) -> list[str]:
    return [s.lower() for s in _cme_split_sentences(answer or "") if s.strip()]


def _cme_nums(text: str) -> set[float]:
    return {float(t.replace(",", "")) for t in _NUM_TOKEN.findall(text) if t.replace(",", "").lstrip("-")}


def _cme_row_stated(sentences: list[str], labels: list[object], value: "int | float") -> bool:
    """Some sentence names one of the row's labels AND states its value."""
    for s in sentences:
        if any(k in s for lab in labels for k in _cme_label_keys(lab)) and any(
                abs(n - float(value)) < 0.005 for n in _cme_nums(s)):
            return True
    return False


def _cme_grouped_rows(answer: str, rows: list[dict]) -> str:
    """KI-073: a result with TWO label columns (scheme x sector, scheme x
    district) must state every figure next to its own labels. When any row's
    figure cannot be found beside one of its labels, or the text falls back on
    "respectively" / "each corresponding row", rebuild it grouped by the first
    label, with that group's total."""
    if not 2 <= len(rows) <= 30:
        return answer
    nums = _fp_numeric_cols(rows)
    labels = [k for k in rows[0] if k not in nums]
    if len(labels) != 2 or not 1 <= len(nums) <= 3:
        return answer
    sents = _cme_sentences(answer)
    ok = not _CME_GARBLED.search(answer or "") and all(
        _cme_row_stated(sents, [r.get(labels[0]), r.get(labels[1])], _as_number(r.get(m)) or 0)
        for r in rows for m in nums if _as_number(r.get(m)) is not None)
    if ok:
        return answer
    g, sub = (labels if labels[0] == "scheme_name" or labels[1] != "scheme_name"
              else list(reversed(labels)))
    groups: dict[object, list[dict]] = {}
    for r in rows:
        groups.setdefault(r.get(g), []).append(r)

    def figs(vals: dict) -> str:
        return ", ".join(f"{_metric_label(m)} {_fmt_num(vals[m])}" for m in nums if vals.get(m) is not None)

    lines = []
    for key, rs in groups.items():
        parts = "; ".join(f"{_cme_short(r.get(sub)) if r.get(sub) is not None else '(not recorded)'}: "
                          f"{figs({m: _as_number(r.get(m)) for m in nums})}" for r in rs)
        if len(rs) > 1:
            tot = {m: sum(_as_number(r.get(m)) or 0 for r in rs) for m in nums}
            lines.append(f"- {_cme_short(key)} — total {figs(tot)}. By "
                         f"{_FP_LABEL_NAME.get(sub, sub.replace('_', ' '))}: {parts}.")
        else:
            lines.append(f"- {_cme_short(key)} — {parts}.")
    logger.info("CM Elevate: rebuilt a two-label answer from the rows (figures were not beside their labels)")
    return "Here is the breakdown:\n" + "\n".join(lines)


_CME_STATUS_WORDS = (
    ("hold", Matcher(Alt(_CME_ON_HOLD_ANYWHERE, _cme_has("on_hold"), _cme_has("pending")))),
    ("valid", Matcher(Alt(W("valid"), _cme_has("verified")))),
    ("sector", Matcher(_cme_has("sector"))), ("withdraw", Matcher(_cme_has("withdr"))))


def _cme_pick_count_col(question: str, rows: list[dict]) -> "str | None":
    cols = _fp_numeric_cols(rows)
    if len(cols) == 1:
        return cols[0]
    q = (question or "").lower()
    for colword, qm in _CME_STATUS_WORDS:
        hit = [c for c in cols if colword in c.lower()]
        if len(hit) == 1 and qm.search(q):
            return hit[0]
    return None


# KI-182: the query groups by scheme_name alone, with nothing after the GROUP BY
# but ORDER BY / LIMIT. Only then does a programme missing from the rows mean 0
# under the query's filters (a HAVING could have filtered it, another GROUP BY key
# split it, a LIMIT smaller than the programme count cut it).
def _cme_agg_aliases(sql: "str | None") -> "list[str]":
    """The names given to a plain COUNT(…) / SUM(…) with AS (a FILTER-ed one is not plain)."""
    return [a.alias for t in sql_ast.parse(sql) for a in t.find_all(exp.Alias)
            if isinstance(a.this, (exp.Count, exp.Sum))]


def _cme_asked_programmes(sql: str) -> list[str]:
    """The programmes the query was asked about (its scheme_name IN list), when
    an absent one can only mean 0; else []. A LIMIT is harmless when it is at
    least the number of programmes — live 2026-10-02 the SQL usually ended
    "LIMIT 1000" (the model's or run_readonly's auto-limit), which disabled this
    guard on 7 of 30 one-zero questions."""
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select):
        return []
    node = _cme_in_list(tree, "scheme_name")
    group = tree.args.get("group")
    if (node is None or group is None or len(group.expressions) != 1
            or not _cme_is_scheme_name(group.expressions[0])
            or tree.find(exp.Having) is not None or tree.args.get("offset") is not None):
        return []
    names = _cme_in_values(node)
    limit = sql_ast.outer_limit(tree)
    if limit is not None and (limit < 0 or limit < len(names)):
        return []
    return names


def _cme_all_zero_answer(sql: str, answer: str, display: dict) -> str:
    """KI-182 (CM-ELEVATE-OFF-009, both programmes 0): the SQL ran and returned
    no row for any asked programme — each one has 0. The generic "couldn't find
    any matching records for <district>, <P1> and <P2>" read as if the question
    had failed (141 'pass with remark' in the 2026-10-01 all-pairs run)."""
    asked = _cme_asked_programmes(sql)
    aliases = _cme_agg_aliases(sql)
    if len(asked) < 2 or len(aliases) != 1:
        return answer
    label = _metric_label(aliases[0])
    place = next((display.get(k) for k in ("village", "block", "district") if (display or {}).get(k)), None)
    lead = f"In {place}, none of these {len(asked)} programmes has any {label}: " if place else         f"None of these {len(asked)} programmes has any {label}: "
    return (lead + "; ".join(f"{_cme_short(n)}: 0" for n in asked)
            + f". Combined across these {len(asked)} programmes: 0 {label}.")


def _cme_multi_scheme_total(question: str, sql: str, rows: list[dict], answer: str) -> str:
    """KI-069: a question naming 2+ programmes gets each programme's figure
    AND their combined total. Rows come split by scheme_name (the SQL guard
    ensures it); this adds any programme figure the text left out, then the
    combined total if it is not stated. Exact: request_id never repeats across
    programmes.

    KI-182: a programme with no applications in the place returns NO row, so
    "<district> under PRIME SEED and Cinema Theatre" was answered "PRIME SEED:
    524 applicants." — Cinema Theatre and the total silently left out (567 of
    1,260 questions in the 2026-10-01 all-pairs run). An asked programme with
    no row is now stated as 0 (_cme_asked_programmes says when that is exact)."""
    if not _cme_scheme_in_values(sql) or not 1 <= len(rows) <= 15 or not all("scheme_name" in r for r in rows):
        return answer
    labels = [k for k in rows[0] if k not in _fp_numeric_cols(rows)]
    if labels != ["scheme_name"]:
        return answer
    col = _cme_pick_count_col(question, rows)
    if not col:
        return answer
    vals = [(r["scheme_name"], _as_number(r.get(col))) for r in rows]
    if any(v is None for _n, v in vals):
        return answer
    present = {str(n).casefold() for n, _v in vals}
    zeros = [(n, 0) for n in _cme_asked_programmes(sql) if n.casefold() not in present]
    vals += zeros
    if len(vals) < 2:
        return answer
    sents = _cme_sentences(answer)
    missing = [(n, v) for n, v in vals if not _cme_row_stated(sents, [n], v)]
    out = answer.rstrip()
    if missing:
        out += "\n\n" + "; ".join(f"{_cme_short(n)}: {_fmt_num(v)}" for n, v in vals) + "."
    total = sum(v for _n, v in vals)
    # With a programme filled in as 0 the total equals a figure already stated,
    # so it is said outright (the OFF-009 expected result names the total).
    if zeros or not any(abs(n - total) < 0.005 for n in _cme_nums(answer)):
        out += f"\n\nCombined across these {len(vals)} programmes: {_fmt_num(total)} {_metric_label(col)}."
    return out


_CME_COMPARE_WORDS = Matcher(W("higher", "more", "difference"))


def _cme_comparison(question: str, rows: list[dict], answer: str) -> str:
    """KI-071 (CM-ELEVATE-OFF-027): "compare Piggery and Poultry across Ri Bhoi
    and West Khasi Hills" gave the four counts and no difference. For a
    programme x place result, state for each programme which place is higher
    and by how much, and for each place which programme is higher. A plain
    two-row comparison reuses _fp_comparison."""
    if not _FP_COMPARE_CUE.search(question or "") or not rows:
        return answer
    nums = _fp_numeric_cols(rows)
    labels = [k for k in rows[0] if k not in nums]
    if len(labels) == 1:
        return _fp_comparison(question, rows, answer)
    col = _cme_pick_count_col(question, rows)
    if len(labels) != 2 or not col:
        return answer
    vals = {(r.get(labels[0]), r.get(labels[1])): _as_number(r.get(col)) for r in rows}
    a_vals = list(dict.fromkeys(k[0] for k in vals))
    b_vals = list(dict.fromkeys(k[1] for k in vals))
    lines: list[str] = []
    diffs: list[float] = []

    def one(fixed: object, x: object, y: object, vx: "int | float", vy: "int | float") -> str:
        if vx == vy:
            return f"{_cme_short(fixed)}: {_cme_short(x)} and {_cme_short(y)} are level ({_fmt_num(vx)} each)"
        (hn, hv), (ln, lv) = sorted([(x, vx), (y, vy)], key=lambda p: p[1], reverse=True)
        diffs.append(abs(hv - lv))
        return (f"{_cme_short(fixed)}: {_cme_short(hn)} is higher by {_fmt_num(hv - lv)} "
                f"({_fmt_num(hv)} vs {_fmt_num(lv)})")

    for fixed_vals, other_vals, pos in ((a_vals, b_vals, 1), (b_vals, a_vals, 0)):
        if len(other_vals) != 2:
            continue
        for f in fixed_vals:
            x, y = other_vals
            kx, ky = ((f, x), (f, y)) if pos == 1 else ((x, f), (y, f))
            if vals.get(kx) is None or vals.get(ky) is None:
                continue
            lines.append(one(f, x, y, vals[kx], vals[ky]))
    if not lines:
        return answer
    stated = _cme_nums(answer)
    if diffs and all(any(abs(n - d) < 0.005 for n in stated) for d in diffs) and _CME_COMPARE_WORDS.search(answer or ""):
        return answer
    return answer.rstrip() + "\n\nDifferences: " + "; ".join(lines) + "."


def _cme_digits_for_number_words(answer: str, rows: list[dict]) -> str:
    """"Five CM ELEVATE applicants in Sasatgre village have completed data
    verification" (all-villages run 2026-09-28): the figure was right, but a
    spelled-out number is invisible to the numeric-faithfulness checks, so a WRONG
    one would pass too. A number word before a count noun becomes digits when that
    value is in the result; otherwise it is left for the checks to see."""
    vals = {int(v) for r in rows for _k, v in _row_metrics(r) if isinstance(v, (int, float)) and float(v).is_integer()}

    def sub(m: "Hit") -> str:
        parts = _tm_words(m.group(1)) or [""]
        n = (_NUMBER_TENS.index(parts[0]) + 2) * 10 if parts[0] in _NUMBER_TENS else _NUMBER_WORDS.index(parts[0])
        n += _NUMBER_WORDS.index(parts[1]) if len(parts) > 1 else 0
        return str(n) if n in vals else m.group(0)
    return _NUMBER_WORD_MATCH.sub(sub, answer or "")


def _cme_sector_value(sql: "str | None") -> "str | None":
    """The sector word a query filters on: scheme_specific ->> 'sector_id'
    ILIKE / LIKE / = 'piggery' (a leading / trailing % dropped); else None."""
    for tree in sql_ast.parse(sql):
        for n in tree.walk(bfs=False):
            if not isinstance(n, (exp.EQ, exp.Like, exp.ILike)):
                continue
            for side, val in ((n.this, n.expression), (n.expression, n.this)):
                v = _cme_str(val)
                if v is None or not _cme_reads_sector_id(side):
                    continue
                w = v[1:] if v.startswith("%") else v
                w = w[:-1] if w.endswith("%") else w
                if w and w.isascii() and w.isalpha():
                    return w
    return None


def _cme_programmes_filtered(sql: "str | None") -> "set[str]":
    """Every programme the query filters on: scheme_name = '…' and scheme_name IN ('…', …)."""
    out: set = set()
    for tree in sql_ast.parse(sql):
        for n in tree.walk():
            if _cme_scheme_eq(n):
                out.add(n.expression.this)
            elif _cme_literal_in(n, "scheme_name"):
                out.update(_cme_in_values(n))
    return out


def _cme_sector_answer_names_wrong_programme(answer: str, sql: str, rows: list[dict]) -> str:
    """Tester re-run (2026-09-28): "How many applicants under Meghalaya Poultry
    Farming Scheme belong to Piggery" was answered "The Meghalaya Piggery Development
    Scheme had 5 applicants under the Meghalaya Poultry Farming Scheme" — the SECTOR
    read as a programme. When a one-row sector count names a programme that is
    neither filtered nor in the result, the sentence is rebuilt from the row."""
    sec = _cme_sector_value(sql)
    if not sec or len(rows) != 1:
        return answer
    filtered = _cme_programmes_filtered(sql)
    named = {p for p in _CME_PROGRAMME_WORDS if p.lower() in (answer or "").lower()}
    if not named or named <= filtered | {str(rows[0].get("scheme_name") or "")}:
        return answer
    metrics = _row_metrics(rows[0])
    if not metrics:
        return answer
    sector = sec.title()
    who = (" under the " + " and ".join(sorted(filtered))) if filtered else ""
    parts = [f"{_fmt_num(metrics[0][1])} applicants{who} have their sector recorded as {sector}"]
    extra = {k: v for k, v in metrics[1:]}
    if "sector_recorded" in extra:
        parts.append(f"sector is recorded for {_fmt_num(extra['sector_recorded'])} of them")
    if "scheme_total" in extra:
        parts.append(f"out of {_fmt_num(extra['scheme_total'])} applicants in total")
    logger.info("CM Elevate: sector answer named a programme it never counted — rebuilt")
    return "; ".join(parts) + "."


async def _cm_elevate_answer_guarantees(question: str, sql: str, rows: list[dict], answer: str,
                                        display: dict) -> str:
    """Every CM Elevate DATA answer passes through here after the composer."""
    if not rows:
        return _cme_all_zero_answer(sql, answer, display)
    answer = _cme_digits_for_number_words(answer, rows)
    answer = _cme_sector_answer_names_wrong_programme(answer, sql, rows)
    answer = _mgnrega_zero_backstop(answer, rows, display)   # a genuine 0 is stated as 0 (KI-070)
    answer = _cme_grouped_rows(answer, rows)
    answer = _cme_complete_list(question, answer, rows)
    answer = _cme_multi_scheme_total(question, sql, rows, answer)
    # KI-074 decided 2026-09-28 (product owner): "pending" = verification On Hold
    # only. The interim second line with the file_status Pending count is gone.
    return _cme_comparison(question, rows, answer)

# app/pipeline/schemes/cm_elevate.py — CM Elevate (applications) — village rules, sector facts, SQL rewrites and answer guarantees.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
# Only this scheme's code lives here; the shared steps that call it are in ../common/.
# Sections follow the order of the pipeline steps they belong to.
# Every check or rewrite of SQL here works on the SQLGlot tree (app/sql_ast.py); the
# user's question and the composed answer are read on WORDS (app/text_match.py) —
# never as raw character scans (D-047).
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app import schema_introspect, sql_ast
from app.text_match import (Alt, Cap, Hit, Joined, Matcher, Node, NotBefore, Opt, Pred, Seq, W,
                            collapse_ws, is_int)
from app.text_match import words as _tm_words


class _CmeNear(Node):
    """`a`, then `b` starting at most `max_chars` characters after `a` ends, with no
    character of `stops` in between (e.g. no "?" or "." within 50). max_chars=None: any
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
    """`first`, then a word starting with `stem`: two words, or one word ("applicant_category")."""
    return Alt(Seq(first, W(stem, prefix=True)),
               Pred(lambda w: w.lower().startswith((first + stem, first + "_" + stem))))


def _cme_sg(*ws: str) -> W:
    """A word and its plural (word + "s")."""
    return W(*[f for w in ws for f in (w, w + "s")])


def _cme_level_digit(one_digit: bool) -> Node:
    """"level 2", "level-2", "level2" ("level", then a digit); one_digit=True
    needs exactly one digit, then the word ends."""
    if one_digit:
        return Alt(Seq("level", Pred(lambda w: len(w) == 1 and is_int(w))),
                   Pred(lambda w: len(w) == 6 and w.lower().startswith("level") and is_int(w[5:])))
    return Alt(Seq("level", Pred(lambda w: is_int(w[:1]))),
               Pred(lambda w: w.lower().startswith("level") and is_int(w[5:6])))


def _cme_join(*parts) -> Node:
    """`a` then `b`: the words apart ("on hold", "on-hold") or run together ("onhold"),
    but not joined by '_' ("on_hold" is a column name). Each part is a word or a
    tuple of words."""
    alts = [p if isinstance(p, tuple) else (p,) for p in parts]
    combos = [""]
    for a in alts:
        combos = [c + x.lower() for c in combos for x in a]
    words = [W(*a) for a in alts]
    return Alt(Seq(*words, sep="space"), Seq(*words, sep="dash"), W(*combos))


def _cme_has(sub: str) -> Pred:
    """A word containing `sub` anywhere, not only as a whole word."""
    return Pred(lambda w: sub in w.lower())


# "on" then "hold", even inside longer words: "on hold", "on-hold", "onhold", also inside words ("partition holds")
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
    # B2 (2026-10-29): "applications pending verification at level 2" asked which scheme;
    # the workflow level (current_level) is on v_cm_elevate only.
    Seq("level", Pred(lambda w: w.isdecimal()), sep="space"),
    W("piggery", "poultry"), "goat farming", "warehouse scheme",
    W("sericulture", "motorcaravan"), "agro tourism villa",
    "prime small enterprise", "prime tourism vehicle",
    "prime agriculture response vehicle", "green taxi",
    # "&" too: the stored name is "Meghalaya Sports & Wellness Centre Scheme", and
    # written that way it was read as MGNREGA (OFF-017 full run 2026-10-02)
    "cinema theatre scheme", Seq("sports", Opt("and"), "wellness"),
    "any business venture", W("request_id", "requestid"),
    # The programme names as officers type them, without "PRIME" / "scheme": "applicants
    # under Agriculture Response Vehicle in Ri Bhoi", "status distribution for Warehouse",
    # "… for Cinema Theatre" asked "which scheme?" (CM Elevate UAT 2026-10-30, OFF-006 /
    # 016 / 021 / 023). Which CM Elevate dataset is still settled by the dataset choice.
    "agriculture response vehicle", Seq("response", W("vehicle", "vehicles")), "cinema theatre",
    Seq("agro", "tourism"), Seq(W("warehouse", "warehouses", "warehousing"),
                                Opt(W("scheme", "programme", "program"))),
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
    # B2 (2026-10-29): "beneficiaries sanctioned a loan in Tura" asked which scheme; the loan
    # columns (total_loan_disbursement, loan_entity …) are on v_cm_elevate_disbursement only.
    _cme_sg("loan"),
))
# Vocabulary only the sanction-and-disbursement dataset can answer. Consulted
# ONLY once a question is already a CM Elevate question (named, or via a
# sub-scheme word such as "piggery"), so generic money words are safe here.
_CME_LEGACY_NON_YEAR_TERMS = (
    W("disburs", "sanction", prefix=True), W("subsidy", "subsidies"), _cme_sg("loan", "grant"),
    _cme_sg("amount"), "money", _cme_sg("fund", "rupee", "crore", "lakh"), W("expenditure", "spent", "spend"),
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
)
# "financial year", "FY 24", "FY2024-25", "2023-24", "2023/2024", "year-wise"
_CME_YEAR_TERMS = (
    Seq("financial", W("year", "years"), sep="space"),
    Seq("fy", Pred(lambda w: is_int(w[:2])), sep="space"),
    Pred(lambda w: w.lower().startswith("fy") and is_int(w[2:4])),
    Seq(Pred(lambda w: len(w) == 4 and w.startswith("20") and is_int(w)),
        Pred(lambda w: 2 <= len(w) <= 4 and is_int(w)), sep="dash"),
    _cme_join("year", "wise"),
)
_CMELEVATELEGACY_FORCING = Matcher(Alt(*_CME_LEGACY_NON_YEAR_TERMS, *_CME_YEAR_TERMS))
# The same without the year words: under D-090 a year is not money, so "How many CM Elevate
# applicants … in FY 2017-18?" stays on the applications data (UAT 2026-10-30, D1).
_CMELEVATELEGACY_MONEY = Matcher(Alt(*_CME_LEGACY_NON_YEAR_TERMS))
_CME_YEAR_ASK = Matcher(Alt(*_CME_YEAR_TERMS))
_CME_PER_YEAR = Matcher(Alt(Seq(W("each", "every", "per", "by"), Opt("financial"), W("year", "years", "fy")),
                            _cme_join("year", "wise"), Seq("financial", "year", "wise")))
# Vocabulary only the APPLICATIONS dataset holds: it keeps a bare "CM Elevate"
# on that dataset when no money word is present (a money word wins, see
# _cm_elevate_dataset_choice). A typed "CM-ELEVATE applications" is NOT here:
# it was, and "What percentage of CM-ELEVATE applications have been
# sanctioned?" was answered 80.63% from the applications data, which holds no
# sanction (true 99.89%, CM Elevate Legacy sheet run 2026-10-22). Only the
# dataset chip's marker "CM Elevate (applications)" names that dataset outright
# (_CME_APPS_MARKER): the rephrase model turns a typed "CM-ELEVATE applications"
# into "CM Elevate applications", so that spelling cannot mean "chosen".
_CMELEVATE_APPLICATIONS_ONLY = Matcher(Alt(
    _cme_join("on", "hold"), W("verif", "withdraw", prefix=True), Joined("data", "verified"),
    _cme_stem_joined("applicant", "categor"), Joined("application", "mode"), "online",
    _cme_stem_joined("cm", "connect"), Joined("current", "level"), Joined("file", "status"),
    Joined("application", "status"), _cme_join("status", "wise"), Joined("request", ("id", "ids")),
    W("gender", "sector", "registered", "unregistered"), "prime small enterprise",
    "seed", "green taxi", "cinema", "agro tourism villa",
))


# Which CM Elevate dataset a bare "CM Elevate" means (user decision 2026-10-22,
# replacing the 2026-10-19 rule and the 2026-10-12 default to Legacy). The two
# datasets share a name and nothing else; the 2026-10-19 rule sent "CM-ELEVATE
# applications … sanctioned" to the applications data, which answered "8,840 not
# sanctioned" (true 3) and "80.63% sanctioned" (true 99.89%) — CM Elevate
# Legacy sheet run 2026-10-22. Now:
#   1. FINANCIAL words (money, sanction, subsidy, loan, lender, disbursement,
#      financial year …) -> CM Elevate Legacy directly, never asked: only Legacy
#      holds money. This wins over everything below, the thread included.
#   2. Words only the applications dataset holds (on hold, verification, status,
#      pending, level N, sent back, sector, gender …) -> the applications dataset;
#      Legacy cannot answer them, so asking would offer a dead end.
#   3. Otherwise the CONVERSATION settles it: a thread already on CM Elevate
#      Legacy stays there, one on CM Elevate (applications) stays there.
#   4. Otherwise a data question ASKS "CM Elevate applications or CM Elevate
#      Legacy?" — "How many CM-ELEVATE applications in each district?" holds in
#      both (applications, and Legacy's sanctioned records).
# Knowledge questions ("what is CM Elevate?") are left alone: both datasets share
# one knowledge base.
_CME_APPLICATIONS_VOCAB = Matcher(Alt(
    W("pending", "pendency"),
    _cme_join("sent", "back"), _cme_join("send", "back"), "status",
    _cme_level_digit(one_digit=True), W("forwarde", "forwarded", "rejected")))
# Words both datasets answer ("applicants", "applications"): a data request,
# never a dataset choice — rule 4 asks.
_CME_BOTH_DATASETS_VOCAB = Matcher(W("applicant", "applicants", "application", "applications",
                                     "program", "programs", "programme", "programmes"))
# ... except that since 2026-10-29 (user, RAG fix report Issue 8) these words settle a
# bare CM Elevate as the applications dataset when no money word or thread says Legacy.
_CME_APPLICATION_WORDS = Matcher(W("applicant", "applicants", "application", "applications", "applied"))
# "across all financial years", "for all the years", "all financial years combined"
_CME_ALL_YEARS_SCOPE = Matcher(Seq(Opt(W("across", "for", "in", "over", "during")), "all", Opt("the"),
                                   Opt("financial"), W("year", "years"), Opt("combined")))
_CME_DATA_REQUEST = Matcher(Alt(
    "how many", "number of",
    W("count", "total", "each", "per", "wise", "compare", "summary", "show", "list", "highest", "lowest", "most",
      "top", "recorded", "mapped", "give", "breakdown", "records", "record"),
    W("beneficiar", "comparison", prefix=True),
    _cme_sg("district", "block", "village"), W("constituenc", prefix=True)))
_CME_DATASETS = ("CM Elevate", "CM Elevate Legacy")


def _cm_thread_scheme(prev, state=None, pending_question: "str | None" = None) -> "str | None":
    """The CM Elevate dataset the conversation is already on, or None: the
    previous turn's single scheme; else the conversation state's active
    scheme; else the dataset named in a question that is paused for its
    year or area ("CM Elevate Legacy disbursement by district" -> "which
    FY?" -> "give me for cm elevate in Ri Bhoi" stays on Legacy).
    A KNOWLEDGE answer never settles the dataset: both datasets share one
    knowledge base, and after "What is the CM-ELEVATE programme?" the next "How
    many applications under CM-ELEVATE?" was answered 8,840 from the
    applications data unasked (D-064, Legacy sheet one-chat run 2026-10-22)."""
    if prev is not None and getattr(prev, "route", None) != "knowledge":
        schemes = list(getattr(prev, "schemes", None) or [])
        if len(schemes) == 1 and schemes[0] in _CME_DATASETS:
            return schemes[0]
    active = getattr(state, "scheme", None)
    if active in _CME_DATASETS and getattr(state, "last_route", None) != "knowledge":
        return active
    if pending_question:
        if _SCHEME_NAME_MATCHER["CM Elevate Legacy"].search(pending_question):
            return "CM Elevate Legacy"
        if _SCHEME_NAME_MATCHER["CM Elevate"].search(pending_question):
            return "CM Elevate"
    return None


def _cm_switch_to_applications(question: str, thread_scheme: "str | None") -> bool:
    """A bare "CM Elevate" named as a SWITCH while the thread is on CM Elevate
    Legacy: "now give me for cm elevate" right after a Legacy answer. The thread
    rule (a Legacy thread keeps a bare CM Elevate on Legacy) is for questions that
    continue the thread; a switch fragment that names CM Elevate after a Legacy
    answer can only mean the other dataset. Before this it was pinned to Legacy
    and the same Legacy answer came back (live 2026-10-19 15:03, KI-330)."""
    q = (question or "").strip()
    if thread_scheme != "CM Elevate Legacy" or not q:
        return False
    if _SCHEME_NAME_MATCHER["CM Elevate Legacy"].search(q) or not _SCHEME_NAME_MATCHER["CM Elevate"].search(q):
        return False
    if _CMELEVATELEGACY_FORCING.search(q) or _CMELEVATELEGACY_ONLY_TERMS.search(q):
        return False
    frag = _c01_strip_opening_fillers(q)
    return bool(_SCHEME_SWAP_FOLLOWUP.match(frag) or _scheme_substitution(q)[1])


# D-090 (2026-10-29) answers "How many CM Elevate applications in East Garo Hills?" from the
# applications dataset without the dataset chips, so the officer who meant Legacy types
# "legacy" next — which went to the off-topic reply (harness AC04b). Right after an
# applications answer, a fragment that says only "legacy" asks the same question of CM
# Elevate Legacy.
_CME_LEGACY_ONLY_FILLER = frozenset("legacy cm elevate the one dataset data please pls now then ok okay for in "
                                    "give me show from under instead i meant mean no".split())


def _cm_switch_to_legacy(question: str, prev, thread_scheme: "str | None") -> "str | None":
    """The previous CM Elevate (applications) question asked of CM Elevate Legacy, for a
    fragment that only says "legacy"; else None."""
    ws = [t.low for t in tokens(question or "")]
    if thread_scheme != "CM Elevate" or "legacy" not in ws or len(ws) > 6 \
            or any(w not in _CME_LEGACY_ONLY_FILLER for w in ws):
        return None
    if prev is None or getattr(prev, "route", None) != "data" or list(getattr(prev, "schemes", []) or []) != ["CM Elevate"]:
        return None
    last = str(getattr(prev, "question", "") or "").replace(_CME_APPS_MARKER, "CM Elevate")
    if not last or not _SCHEME_NAME_MATCHER["CM Elevate"].search(last):
        return None
    return _cme_name_dataset(last, "CM Elevate Legacy")


def _names_cm_elevate(question: str) -> bool:
    """A bare "CM Elevate", or a CM Elevate sub-scheme with no scheme named
    ("How many applications are recorded under Meghalaya Piggery Development
    Scheme?"): piggery, dairy, poultry … are in BOTH datasets, and the sub-scheme
    alone was answered from the applications data (3,064 for a Legacy 1,353,
    Legacy sheet TC-12, 2026-10-22)."""
    q = question or ""
    if _SCHEME_NAME_MATCHER["CM Elevate"].search(q):
        return True
    return not any(pat.search(q) for pat in _SCHEME_NAME_MATCHER.values()) \
        and _infer_scheme_from_terms(q) == ["CM Elevate"]


def _cme_name_dataset(question: str, target: str) -> str:
    """The question with its bare "CM Elevate" replaced by `target` ("CM Elevate
    Legacy" or the applications marker), or `target` appended when only a
    sub-scheme names it — a chip must never repeat the question it answers."""
    q = question or ""
    name = _SCHEME_NAME_MATCHER["CM Elevate"]
    if name.search(q):
        return name.sub(target, q)
    return f"{q.strip().rstrip(' ?.')} under {target}"


def _cm_elevate_dataset_choice(question: str, thread_scheme: "str | None" = None) -> "str | None":
    """For a question that names a bare "CM Elevate" (or only a sub-scheme of it):
    "applications", "legacy", "ask", or — in a chat already on one dataset whose
    question only the other can answer — "switch_to_legacy" / "switch_to_applications"
    (the user confirms; _cm_elevate_switch_pause). None when no bare CM Elevate is
    named (or Legacy is named outright).

    User decision 2026-11-03 (replaces D-064 rules 2-5 and D-090 for a new chat):
    "ask users to select CM ELEVATE or Legacy rather than switching automatically;
    the selected dataset must remain until the user requests or confirms a change".
    So: the chip marker (a choice made) -> applications; a chat already on a dataset
    keeps it, and a question only the other dataset holds asks to switch; no dataset
    in the chat yet -> always ask, whatever the words (the words only order nothing:
    both options are offered)."""
    q = question or ""
    if not q or _SCHEME_NAME_MATCHER["CM Elevate Legacy"].search(q) or not _names_cm_elevate(q):
        return None
    # The dataset chip's own marker: the user chose the applications dataset.
    if _CME_APPS_MARKER in q:
        return "applications"
    if thread_scheme not in _CME_DATASETS:
        return "ask"
    wants = _cme_words_dataset(q, thread_scheme)
    if thread_scheme == "CM Elevate Legacy":
        return "switch_to_applications" if wants == "applications" else "legacy"
    return "switch_to_legacy" if wants == "legacy" else "applications"


def _cme_words_dataset(question: str, thread_scheme: "str | None" = None) -> "str | None":
    """The dataset the question's own words can only mean — "legacy" (money, sanction,
    a specific FY: only Legacy holds them), "applications" (status, verification,
    level, sector: only the applications data holds them) — or None. Used only to spot
    a question the chat's dataset cannot answer, so the user is asked to switch; it
    never picks the dataset by itself (user decision 2026-11-03)."""
    q = question or ""
    # "across all financial years" is the scope wording the chips and rewrites
    # append to any question; it is not a financial-year filter, so it never
    # moves a question to Legacy (a typed "FY 2024-25" still does).
    unscoped = _CME_ALL_YEARS_SCOPE.sub(" ", q)
    # D-090 (2026-10-29) over rule 1 for a YEAR: "applications / applicants / applied" with a
    # year and no money word is an applications question, and that dataset has no date, so it
    # gets the no-date reply (_cme_notime_query) instead of Legacy's year pause (UAT D1).
    # A breakdown BY year ("for each financial year", "year-wise") stays rule 1: only Legacy holds years.
    if _CME_YEAR_ASK.search(unscoped) and _CME_APPLICATION_WORDS.search(q) and not _CME_PER_YEAR.search(unscoped) \
            and not _CMELEVATELEGACY_MONEY.search(unscoped) and not _CMELEVATELEGACY_ONLY_TERMS.search(unscoped) \
            and thread_scheme != "CM Elevate Legacy":
        return "applications"
    if _CMELEVATELEGACY_FORCING.search(unscoped) or _CMELEVATELEGACY_ONLY_TERMS.search(unscoped):
        return "legacy"
    if _CMELEVATE_APPLICATIONS_ONLY.search(q) or _CME_APPLICATIONS_VOCAB.search(q):
        return "applications"
    return None


def _cme_open_topic_pin(question: str, topics: "list[str]") -> "list[str] | None":
    """The open topics a vague question fits, when CM Elevate is one of them and
    the question asks for something only its applications data holds ("how many
    are on hold?", "pending verification"): CM Elevate alone. None otherwise.
    Used by the which-topic step (c14 _vague_topic_clarification) only: on a
    question with no open CM Elevate topic these words stay generic and still ask
    which scheme (_CMELEVATE_ONLY_TERMS leaves them out on purpose). Test team
    report 2026-10-29, Bug 5: after a CM Elevate answer, with MGNREGA and PMAY-G
    topics also open, "how many are on hold?" asked which topic."""
    if "CM Elevate" in (topics or []) and _CMELEVATE_APPLICATIONS_ONLY.search(question or ""):
        return ["CM Elevate"]
    return None


def _pin_cm_elevate_dataset(question: str, thread_scheme: "str | None" = None) -> str:
    """Settle a bare "CM Elevate" ONCE, on the question text, before routing —
    the same way a misspelled scheme name is corrected — so every later word
    check sees one consistent dataset. Only the chat's own dataset settles it
    (user decision 2026-11-03): a Legacy chat -> "CM Elevate Legacy", an
    applications chat -> "CM Elevate (applications)". A question the chat's dataset
    cannot answer (a switch) and a chat with no dataset yet are returned unchanged:
    the route stage asks to switch (_cm_elevate_switch_pause), the data stage asks
    which dataset (_cm_elevate_dataset_pause). Shown as `rewritten_question`."""
    q = question or ""
    choice = _cm_elevate_dataset_choice(q, thread_scheme)
    if choice == "legacy":
        out = _cme_name_dataset(q, "CM Elevate Legacy")
        logger.info("CM Elevate dataset kept by the chat: Legacy %r -> %r", q, out)
        return out
    if choice == "applications" and thread_scheme == "CM Elevate" and _CME_APPS_MARKER not in q:
        out = _cme_name_dataset(q, _CME_APPS_MARKER)
        logger.info("CM Elevate dataset kept by the chat: applications %r -> %r", q, out)
        return out
    return q


def _cm_elevate_dataset_pause(question: str) -> "ClarificationNeeded | None":
    """The "CM Elevate or CM Elevate Legacy?" pause for a data question naming a bare
    CM Elevate that the chat's dataset did not settle (the context stage pins a chat's
    dataset into the question first); None otherwise."""
    if _cm_elevate_dataset_choice(question) != "ask":
        return None
    stem = (question or "").strip().rstrip(" ?.")
    # labels "CM Elevate" / "CM Elevate Legacy" (user 2026-11-03); a typed reply is read
    # by the label before " (" (c03 _resume_scheme_pause), so both stay scheme names
    return ClarificationNeeded(
        "CM Elevate has two datasets — CM Elevate (applications) and CM Elevate Legacy "
        "(sanctions and disbursements). Which one do you mean?",
        options=[{"label": "CM Elevate", "question": _cme_name_dataset(stem, _CME_APPS_MARKER)},
                 {"label": "CM Elevate Legacy", "question": _cme_name_dataset(stem, "CM Elevate Legacy")}],
        rule="cm-elevate-dataset")


def _cm_elevate_switch_pause(question: str, thread_scheme: "str | None") -> "ClarificationNeeded | None":
    """In a chat already on one CM Elevate dataset, a DATA question only the other one
    can answer: ask to switch, never switch unasked (user decision 2026-11-03: "the
    selected dataset must remain consistent ... unless the user explicitly requests or
    confirms a change"). The switch option comes first; "stay" keeps the chat's dataset.
    Same rule as the dataset pause, so a typed scheme name resumes it. None otherwise."""
    choice = _cm_elevate_dataset_choice(question, thread_scheme)
    if choice not in ("switch_to_legacy", "switch_to_applications"):
        return None
    stem = (question or "").strip().rstrip(" ?.")
    here, there = (("CM Elevate Legacy", "CM Elevate") if choice == "switch_to_applications"
                   else ("CM Elevate", "CM Elevate Legacy"))
    as_q = {"CM Elevate Legacy": _cme_name_dataset(stem, "CM Elevate Legacy"),
            "CM Elevate": _cme_name_dataset(stem, _CME_APPS_MARKER)}
    return ClarificationNeeded(
        f"This chat is on {here}. This question asks for something only {there} holds. "
        f"Switch to {there}, or stay on {here}?",
        options=[{"label": f"{there} (switch)", "question": as_q[there]},
                 {"label": f"{here} (stay)", "question": as_q[here]}],
        rule="cm-elevate-dataset")


def _unpin_cm_elevate(question: str) -> str:
    """Undo _pin_cm_elevate_dataset. The pin only ever writes "CM Elevate
    Legacy" or "CM Elevate (applications)" into a question that named neither
    form itself, so every occurrence came from the pin and reverts cleanly."""
    return _CME_PINNED_NAME.sub("CM Elevate", (question or "").replace(_CME_APPS_MARKER, "CM Elevate"))


_CME_PINNED_NAME = Matcher(W("CM", case=True), W("Elevate", case=True), W("Legacy", case=True), sep="space")
# The applications dataset named by its chip (label and question alike); a literal,
# compared with string methods (D-047).
_CME_APPS_MARKER = "CM Elevate (applications)"


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
    # The data spells one board twice ("TURA MUNICIPAL BOARD" 28 and "TURA MUNICIPAL
    # BOARD-MUNICIPAL BOARD" 77): any one spelling is pinned here and
    # _cm_elevate_urban_body_spellings widens the SQL to all of them (UAT 2026-10-30:
    # "Tura Municipal Board" kept lgd_block = 'TURA' and answered 0).
    if asked_urban and urban:
        return sorted(urban)[0]
    if want in data_blocks:
        return None
    same = [b for b in data_blocks if not _URBAN_BODY_MATCH.search(b) and _cme_block_base(b) == base]
    if len(same) == 1:
        return same[0]
    return sorted(urban)[0] if urban else None


def _cme_dedupe_group_by(sql: str) -> str:
    """`GROUP BY scheme_name, scheme_name` (the model repeats a key) hid the asked programmes from
    _cme_asked_programmes, so two programmes with no applications were answered "couldn't find any matching
    records" instead of 0 each (UAT 2026-10-30, C01-009-05). A repeated GROUP BY key is dropped."""
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("group") is None:
        return sql
    seen, keep = set(), []
    for g in tree.args["group"].expressions:
        key = g.sql()
        if key not in seen:
            seen.add(key)
            keep.append(g)
    if len(keep) == len(tree.args["group"].expressions):
        return sql
    tree.set("group", exp.Group(expressions=keep))
    return sql_ast.to_sql(tree)


_CME_VERIF_Q = Matcher(Alt(Seq(Opt("data"), W("verification", "verified", "verify")), "verification"))


def _cme_valid_eq(node: exp.Expression) -> bool:
    """[LOWER|UPPER(]data_verified[)] = 'valid' (any case)."""
    if not isinstance(node, exp.EQ) or _cme_col(node.this, "data_verified") is None:
        return False
    lit = node.expression
    while isinstance(lit, _CME_CASE_WRAPPERS) and lit.this is not None:
        lit = lit.this
    v = _cme_str(lit)
    return v is not None and v.strip().lower() == "valid"


def _cme_verification_split(question: str, sql: str) -> str:
    """OFF-022 asks for the verified AND the non-verified count (and the rate); "How many applicants have
    completed data verification in Ri Bhoi?" ran a single `… AND data_verified = 'Valid'` count and was
    answered with 2,039 alone (final run 2026-10-30, C01-022-06). That count becomes verified / not
    verified / total over the same place."""
    if not _CME_VERIF_Q.search(question or ""):
        return sql
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("group") is not None or tree.args.get("joins")             or len(tree.expressions) != 1 or not isinstance(tree.expressions[0].unalias(), exp.Count):
        return sql
    if not any(_cme_valid_eq(n) for n in tree.find_all(exp.EQ)) or not _cme_drop_conjuncts(tree, _cme_valid_eq):
        return sql
    tree.set("expressions", [sqlglot.parse_one(x, read=sql_ast.DIALECT) for x in (
        "COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') AS verified_applicants",
        "COUNT(DISTINCT request_id) FILTER (WHERE data_verified IS DISTINCT FROM 'Valid') AS not_verified_applicants",
        "COUNT(DISTINCT request_id) AS total_applicants")])
    logger.info("CM Elevate: data-verification count split into verified / not verified / total")
    return sql_ast.to_sql(tree)


def _cme_verification_figures(answer: str, rows: list[dict]) -> str:
    """The verified / not-verified / total row (see _cme_verification_split): any figure the answer does not
    state is added, with the verified rate."""
    if len(rows) != 1 or not {"verified_applicants", "not_verified_applicants", "total_applicants"} <= set(rows[0]):
        return answer
    v, nv, t = (int(_as_number(rows[0][k]) or 0) for k in ("verified_applicants", "not_verified_applicants", "total_applicants"))
    have = set(_cme_nums(answer or ""))
    if float(v) in have and float(nv) in have:
        return answer
    rate = f"{100 * v / t:.1f}%" if t else "n/a"
    return (answer.rstrip() + f" Verified: {v:,}; not verified: {nv:,}; total applicants: {t:,} "
            f"(verified rate {rate}).")


_CME_COMBINED_Q = Matcher(Alt(W("total", "combined", "together", "altogether", "sum"), Seq("in", "all")))


def _cme_villages_per_village(question: str, sql: str) -> str:
    """`COUNT(DISTINCT request_id) … WHERE village_code IN (a, b)` with no GROUP BY summed two same-name
    villages: "2 applicants in Nongshilliang (Mawpat block) and Nongshilliang (Mairang block)" (UAT
    2026-10-30, C03). Several villages are answered one row each (village_code, lgd_block), the J-10 rule,
    unless the question asks for a combined total."""
    if _CME_COMBINED_Q.search(question or ""):
        return sql
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("group") is not None or tree.args.get("joins")             or tree.args.get("with") is not None or not any(e.find(exp.AggFunc) for e in tree.expressions):
        return sql
    node = next((n for n in tree.find_all(exp.In) if _cme_col(n.this, "village_code") is not None
                 and not isinstance(n.parent, exp.Not) and len(n.expressions) >= 2), None)
    if node is None:
        return _cme_twin_limit(sql)
    cols = ["village_code", "lgd_block"]
    tree.set("expressions", [exp.column(c) for c in cols] + list(tree.expressions))
    tree.set("group", exp.Group(expressions=[exp.column(c) for c in cols]))
    logger.info("CM Elevate: several villages in one query -> one row per village")
    return sql_ast.to_sql(tree)


def _cme_geo_beside_villages(sql: str) -> str:
    """"MAWLIEH" (Rambrai, West Khasi Hills 10; Pynursla, East Khasi Hills 3) ran `lgd_district = 'WEST KHASI
    HILLS' AND village_code IN (278917, 276747)` and lost the Pynursla village (final regression 2026-10-30,
    C03-ALONE-mawlieh). Beside a village_code list of 2+ the codes pin the places: a district / block literal
    there is dropped (the single-village form is _drop_geo_beside_pinned_village)."""
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("where") is None:
        return sql
    if not any(_cme_col(n.this, "village_code") is not None and len(n.expressions) >= 2
               and not isinstance(n.parent, exp.Not) for n in tree.find_all(exp.In)):
        return sql
    changed = False
    for n in list(tree.args["where"].find_all(exp.EQ)):
        if (_cme_col(n.this, "lgd_district") is not None or _cme_col(n.this, "lgd_block") is not None)                 and _cme_str(n.expression) is not None and n.find_ancestor(exp.Or) is None:
            n.replace(exp.true())
            changed = True
    if not changed:
        return sql
    logger.info("CM Elevate: dropped a district / block literal beside a list of village codes")
    return sql_ast.to_sql(tree)


def _cme_twin_limit(sql: str) -> str:
    """A query over N village codes grouped by village_code ended `LIMIT 1` and dropped the second Massar
    (Pynursla, 5) (final run 2026-10-30, C03-ALONE-massar). A LIMIT below N is dropped."""
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("group") is None or tree.args.get("limit") is None:
        return sql
    node = next((n for n in tree.find_all(exp.In) if _cme_col(n.this, "village_code") is not None
                 and not isinstance(n.parent, exp.Not) and len(n.expressions) >= 2), None)
    lim = tree.args["limit"].args.get("expression")
    if node is None or not (isinstance(lim, exp.Literal) and lim.is_int and int(lim.this) < len(node.expressions)):
        return sql
    tree.set("limit", None)
    logger.info("CM Elevate: dropped a LIMIT smaller than the number of villages asked")
    return sql_ast.to_sql(tree)


def _cme_ac_name_case(sql: str) -> str:
    """v_cm_elevate stores ac_name in Title Case ("West Shillong"): `ac_name = 'WEST SHILLONG'` matched
    nothing and the answer was "couldn't find any matching records" (UAT 2026-10-30, C01-017AC-59). An
    ac_name compared to a literal is compared case-blind (Focus Legacy / Legacy have the same rewrite)."""
    tree = sql_ast.parse_one(sql)
    if tree is None:
        return sql
    changed = False
    for node in list(tree.find_all(exp.EQ, exp.In)):
        col = node.this
        if not (isinstance(col, exp.Column) and col.name.lower() == "ac_name"):
            continue
        if isinstance(node, exp.EQ):
            lit = _cme_str(node.expression)
            if lit is None:
                continue
            node.replace(exp.EQ(this=exp.Upper(this=col.copy()), expression=exp.Literal.string(lit.upper())))
        else:
            vals = _cme_in_values(node)
            if not vals or any(v is None for v in vals):
                continue
            node.replace(exp.In(this=exp.Upper(this=col.copy()),
                                expressions=[exp.Literal.string(str(v).upper()) for v in vals]))
        changed = True
    return sql_ast.to_sql(tree) if changed else sql


def _cme_block_inside_constituency(question: str, sql: str) -> str:
    """"status distribution in West Shillong constituency" also got lgd_block = 'SHILLONG-MUNICIPAL
    BOARD' (the town's name sits inside the constituency's) and 0 rows (C01-017AC-59). A block filter
    whose name appears in the question only inside the filtered constituency's name is dropped."""
    acs = {str(a).upper() for a in _fl_ac_values(sql)}
    if not acs:
        return sql
    rest = (question or "").upper()
    for a in sorted(acs, key=len, reverse=True):          # only "<AC> [assembly] constituency" goes
        for tail in (" ASSEMBLY CONSTITUENCY", " CONSTITUENCY", " AC"):
            rest = rest.replace(a + tail, " ")
    rest_l = rest.lower()
    tree = sql_ast.parse_one(sql)
    if tree is None:
        return sql

    def stray(node: exp.Expression) -> bool:
        if not isinstance(node, (exp.EQ, exp.In)) or _cme_col(node.this, "lgd_block") is None:
            return False
        vals = [_cme_str(node.expression)] if isinstance(node, exp.EQ) else _cme_in_values(node)
        return bool(vals) and all(v is not None and _cme_block_base(str(v)).lower() not in
                                  "".join(ch for ch in rest_l if ch.isalnum()) for v in vals)
    if not _cme_drop_conjuncts(tree, stray):
        return sql
    logger.info("CM Elevate: dropped a block filter named only inside the constituency's name")
    return sql_ast.to_sql(tree)


async def _cm_elevate_urban_body_spellings(question: str, schemes: list[str], sql: str) -> str:
    """The CM Elevate place-literal pass: a block named only inside the constituency's name is
    dropped, ac_name compared case-blind, then the urban-body spellings (_cme_urban_block_spellings)."""
    if schemes != ["CM Elevate"] or not sql:
        return sql
    sql = _cme_dedupe_group_by(sql)
    sql = _cme_verification_split(question, sql)
    sql = _cme_villages_per_village(question, sql)
    sql = _cme_twin_limit(sql)
    sql = _cme_geo_beside_villages(sql)
    sql = _cme_block_inside_constituency(question, sql)
    sql = _cme_ac_name_case(sql)
    return await _cme_urban_block_spellings(question, schemes, sql)


async def _cme_urban_block_spellings(question: str, schemes: list[str], sql: str) -> str:
    """`lgd_block = '<an urban body>'` (or an IN-list holding one) also takes every other
    stored spelling of the same board: v_cm_elevate holds Tura's applications under
    "TURA MUNICIPAL BOARD" and "TURA MUNICIPAL BOARD-MUNICIPAL BOARD" (see _cme_data_block).
    A literal the data does not store becomes the stored block the question names: "Nongpoh
    Town Committee block … in the Nongpoh constituency" was written lgd_block = 'NONGPOH'
    once the constituency had cleared the block slot, and answered 0 (UAT 2026-10-30, H-BxAC)."""
    if schemes != ["CM Elevate"] or not sql or "lgd_block" not in sql.lower():
        return sql
    try:
        data_blocks = await _cm_elevate_block_names("CM Elevate")
    except Exception:  # noqa: BLE001 — without the live list, leave the SQL as it is
        return sql
    urban: "dict[str, list[str]]" = {}
    for b in data_blocks:
        if _URBAN_BODY_MATCH.search(b):
            urban.setdefault(_cme_block_base(b), []).append(b)
    siblings = {b: sorted(v) for v in urban.values() if len(v) > 1 for b in v}
    stored = set(data_blocks)
    tree = sql_ast.parse_one(sql)
    if tree is None:
        return sql
    changed = False
    for node in list(tree.find_all(exp.EQ, exp.In)):
        col = _cme_col(node.this, "lgd_block")
        if col is None:
            continue
        vals = [_cme_str(node.expression)] if isinstance(node, exp.EQ) else _cme_in_values(node)
        if not vals or any(v is None for v in vals):
            continue
        want = []
        mapped = [v if str(v).upper() in stored else (_cme_data_block(str(v), question, data_blocks) or v)
                  for v in vals]
        for v in mapped:
            for s in siblings.get(str(v).upper(), [str(v)]):
                if s not in want:
                    want.append(s)
        if want != list(vals):
            node.replace(exp.In(this=node.this.copy(), expressions=[exp.Literal.string(s) for s in want]))
            changed = True
    # grouped by block: one row per board, not one per stored spelling — "Rongram vs Tura Municipal
    # Board" compared 609 with Tura's 28 instead of 105 (77 + 28) (UAT 2026-10-30, C09)
    if isinstance(tree, exp.Select) and tree.args.get("group") is not None:
        groups = {}
        for v in siblings.values():
            groups[tuple(v)] = sorted(v, key=len)[0]

        def merged(col: exp.Expression) -> exp.Expression:
            case = exp.Case()
            for sibs, canon in groups.items():
                case = case.when(exp.In(this=col.copy(), expressions=[exp.Literal.string(x) for x in sibs]),
                                 exp.Literal.string(canon))
            return case.else_(col.copy())
        for i, g in enumerate(list(tree.args["group"].expressions)):
            if isinstance(g, exp.Column) and g.name.lower() == "lgd_block":
                tree.args["group"].expressions[i] = merged(g)
                changed = True
        for i, e in enumerate(list(tree.expressions)):
            if isinstance(e, exp.Column) and e.name.lower() == "lgd_block":
                tree.expressions[i] = exp.alias_(merged(e), "lgd_block")
                changed = True
    if not changed:
        return sql
    logger.info("CM Elevate: an urban body's other stored spellings added to the lgd_block filter")
    return sql_ast.to_sql(tree)


async def _cm_elevate_block_from_mention(mention: str, schemes: "list[str] | None") -> "str | None":
    """The stored CM Elevate block a place mention names, when nothing else
    resolved it: an urban body ("Jowai-municipal Board", "Nongpoh TC") or the
    data's exact block spelling. Used before a mention is refused as outside
    Meghalaya (KI-107). CM Elevate Legacy uses its own stored blocks; Focus Plus
    its block_name_raw values, the column its block filter reads (its lgd_block
    spells one board twice, WILLIAMNAGAR- / WILLIAM NAGAR-MUNICIPAL BOARD, which
    would make the board ambiguous — KI-361)."""
    if schemes not in (["CM Elevate"], ["CM Elevate Legacy"], ["Focus Plus"]) or not mention:
        return None
    try:
        data_blocks = sorted(await _focusplus_raw_block_names()) if schemes == ["Focus Plus"] \
            else await _cm_elevate_block_names(schemes[0])
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


def _cme_block_only_in_constituency(question: str, block: str) -> bool:
    """Every place the block's name is written, the next word (after at most one more name word) is
    "constituency" / "assembly" and never "block" / "municipal" / "town"."""
    base = _cme_block_base(block).lower()
    words = ["".join(ch for ch in w.lower() if ch.isalnum()) for w in (question or "").split()]
    hits = [i for i, w in enumerate(words) if w and w == base]
    if not base or not hits:
        return False
    for i in hits:
        after = [w for w in words[i + 1:i + 3] if w]
        if not after or after[0] in ("block", "municipal", "town", "tc", "mb") \
                or not any(w in ("constituency", "assembly", "ac") for w in after):
            return False
    return True


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
    # "status distribution in West Shillong constituency" resolved the block SHILLONG-MUNICIPAL BOARD from
    # the town's name inside the constituency's; the missing-filter guard then demanded it on every repair
    # and the turn ended "couldn't build a working query" (UAT 2026-10-30, C01-017AC-59). A block the
    # text names only as part of "<name> constituency" is not a block filter.
    if scheme == "CM Elevate" and isinstance(resolved.get("block"), str) \
            and _cme_block_only_in_constituency(question, resolved["block"]):
        logger.info("CM Elevate: block %r named only inside a constituency's name - dropped", resolved["block"])
        resolved.pop("block", None)
        display.pop("block", None)
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
_CME_SECTOR_FACT_KINDS = ("count", "pending", "programmes", "workflow", "notime")
# "Pending" (user decision 2026-10-30): the rule lives in the knowledge base
# (cmelevate_pending_rule.yaml) and is read through app.cme_pending_rule —
# data verified Valid, file status Pending or Send Back; every count is valid-only by default.
# An "on hold" question means the same; a level-wise question is the rule by current_level.
# Other states (Invalid / Wrong, resubmit, Rejected) are reported only when the question names
# them. file_status is inside scheme_specific, which the chatbot's database role may not read
# until the DB team grants it (KI-624); until then the recorded figures are given instead
# (cme-sector-workflow below) and the rule is stated.
from app import cme_pending_rule as _pending_rule


def _cme_pending_readable() -> bool:
    """Every column the pending rule needs is among those the chatbot's role may read."""
    return _pending_rule.readable()


def _cme_pending_sql() -> str:
    """The pending rule as one SQL condition, built from the knowledge base."""
    return _pending_rule.sql()


def _cme_pending_text() -> str:
    """The rule as one sentence for answers, built from the same steps."""
    return _pending_rule.text()


def _cme_pending_target() -> "str | None":
    """The SQL condition a plain "pending" / "on hold" resolves to: the rule once its columns
    are readable, None while they are not. Never data_verified = 'On Hold' (user, 2026-10-30:
    on hold does not read data_verified) — a guard with nothing to resolve to leaves the SQL."""
    return _cme_pending_sql() if _cme_pending_readable() else None


# Every CM Elevate application COUNT includes only valid applications (user, 2026-10-30), from
# applications_default in the same knowledge-base file. A question that names a verification
# state is answered exactly as asked; one that asks for ALL applications gets the total and its
# split by verification state (_cm_elevate_all_applications). "On hold" is a pending question
# (the rule includes the default), not a verification-state question.
_CME_ALL_APPLICATIONS_Q = Matcher(Alt(
    Seq("all", Opt(W("the", "cm", "cme")), Opt("elevate"), W("applications", "applicants")),
    Seq("including", Opt("the"), W("invalid", "unverified", "wrong", "rejected", "on", "not")),
    Seq(W("irrespective", "regardless"), "of"),
    Seq("every", Opt("single"), W("application", "applications", "applicant", "applicants")),
    Seq("not", "only", W("valid", "verified")),
    Seq(W("valid", "verified"), W("and", "plus", "or"), W("invalid", "not", "unverified")),
    Seq("without", Opt("the"), Opt("data"), W("verification", "validity"), Opt("filter")),
    W("unfiltered"),
    # "total applications in all statuses", "any status", "all verification states", "whatever
    # the status" (user report 2026-11-03: 7,375 valid applications were given as "across all
    # statuses"; the true all-status total was 8,938)
    Seq(W("all", "any", "every", "each", "whatever"), Opt(W("the", "its", "their")),
        Opt(W("verification", "application", "applications", "data")), W("status", "statuses", "state", "states"))))
_CME_VERIF_WORD = Matcher(Alt(Pred(lambda w: "verif" in w.lower()), W("validity", "invalid", "unverified")))


def _cme_names_verification_state(question: str) -> bool:
    """The question names verification itself or one of the knowledge base's verification
    states. A plain "on hold" is NOT one: it is the pending rule (user, 2026-10-30)."""
    q = question or ""
    if _CME_VERIF_WORD.search(q):
        return True
    if _CME_ON_HOLD_Q.search(q):
        return False
    low = " " + " ".join(q.lower().replace("-", " ").split()) + " "
    _col, states = _pending_rule.verification_states()
    return any(f" {str(v).lower()} " in low for v in states)


def _cme_asks_all_applications(question: str) -> bool:
    return _CME_ALL_APPLICATIONS_Q.search(question or "") is not None or _cme_whole_count(question)


def _cme_restore_all_applications(question: str, typed: "list") -> str:
    """The question with "all applications" when the officer TYPED a request for every
    application but the rewrite lost it (user 2026-11-04: "i need all beneficiaries" was rewritten
    "how many beneficiaries in CM Elevate (applications)", and "total beneficiaries in entire em
    elevate" was rephrased "… in the entire state of Meghalaya" — both then got the valid-only
    default). Only for a CM Elevate (applications) question; unchanged otherwise. The words added
    are the ones the valid-only Note itself tells the officer to type."""
    s = _exact_schemes(question or "")
    if "CM Elevate" not in s or "CM Elevate Legacy" in s or _cme_asks_all_applications(question):
        return question
    if not any(_cme_asks_all_applications(x) for x in typed if x):
        return question
    logger.info("CM Elevate: every application was asked in the typed words — %r keeps it", question)
    return f"{question.strip().rstrip(' ?.')}, all applications?"


def _cme_whole_count(question: str) -> bool:
    """"i need all beneficiaries", "total beneficiaries in entire CM Elevate" (user 2026-11-04:
    both answered with the 7,375 valid applications). A whole-set word (the all-years reply
    keys: all, every, entire, whole, overall, …) that qualifies a word the SME resolver file
    reads as an application COUNT (entity_resolver.count_terms: beneficiaries, applicants) or
    the scheme itself. Not when that word's phrase is a place or a time scope the existing
    readers claim ("beneficiaries in all districts", "entire state", "all years"), nor for the
    sub-schemes ("all CM Elevate schemes"). A plain "total" keeps the default (2026-10-30)."""
    from app.entity_resolver import count_terms
    terms = count_terms("CM Elevate")
    ws = [w.lower() for w in _tm_words(question or "")]

    def counted(w: str) -> bool:
        return w in terms or f"{w}s" in terms or (w.endswith("y") and f"{w[:-1]}ies" in terms)

    if not terms or not any(counted(w) for w in ws):
        return False
    for i, w in enumerate(ws):
        if w not in _ALL_YEARS_REPLY_KEYS:
            continue
        rest = ws[i + 1:i + 6]
        while rest and rest[0] in ("the", "of"):
            rest = rest[1:]
        phrase = " ".join([w, *rest[:3]])
        if not rest or (context_policy.asked_levels(phrase) or context_policy.extract_year_keys(phrase)
                        or context_policy._ALL_YEARS_MATCH.search(phrase)
                        or any(m.search(phrase) for m in context_policy._ALL_GEO_MATCH.values())):
            continue
        if counted(rest[0]) or ("CM Elevate" in _exact_schemes(" ".join(rest[:3]))
                                and "schemes" not in rest[:4]):
            return True
    return False


def _cme_default_where(question: str) -> "str | None":
    """The default-applications condition for a fixed query, or None when the question names a
    verification state or asks for all applications (or the knowledge base sets no default)."""
    d = _pending_rule.default_sql()
    if not d or _cme_asks_all_applications(question) or _cme_names_verification_state(question):
        return None
    return d


def _cme_default_only_note(sql: str, answer: str) -> "str | None":
    """A Note when the executed SQL kept only the default applications (applications_default:
    data verified Valid) and the answer never says so — a valid-only figure must not read as
    every application (user report 2026-11-03: "Total applications ... across all statuses ...
    is 7,375", all 8,938 in truth). Read from the SQL tree and the knowledge-base file, so a
    change of the default there changes this too. None when the answer already names the rows
    ("valid applications", the pending rule's own sentence) or the SQL does not filter to them."""
    d = _pending_rule.default_step()
    col, label = _pending_rule.default_column(), _pending_rule.default_text()
    if not d or not col or not label or not sql:
        return None
    try:
        # The query's own scope only: a test inside one aggregate's FILTER (the pending rule's
        # "data_verified = 'Valid' AND file_status …") scopes that count, not the figures.
        # "Give ALL applications and pendency …" (user 2026-11-04) counted every status yet
        # carried the "valid applications only" Note because of that FILTER.
        tree = sql_ast.parse_one(sql)
        if tree is None:
            return None
        scope = tree.copy()
        for f in list(scope.find_all(exp.Filter)):
            f.replace(f.this)
        vals = {str(v).strip().lower() for v in sql_ast.filter_values(scope, col)}
    except Exception:  # noqa: BLE001 — a SQL we cannot read gets no note
        return None
    wanted = {str(v).strip().lower() for v in d.get("values") or []}
    if not vals or not vals <= wanted:
        return None                          # not filtered to the default (or a named state)
    if label in {w.lower() for w in _c12s_words(answer or "")}:
        return None
    shown = ", ".join(str(v) for v in d.get("values") or [])
    return (f"Note: these figures count {label} applications only ({col.replace('_', ' ')}: {shown}). "
            "Ask for all applications to include every status.")


def _cme_marker_echo(answer: str) -> str:
    """The chip marker copied by the composer in front of the same word: "2,038 CM Elevate
    (applications) applications" -> "2,038 CM Elevate applications" (live 2026-11-03). Any other
    use of the marker is left as written; the dataset is named in the answer chip either way."""
    text, marker = answer or "", _CME_APPS_MARKER
    base = marker.split(" (")[0]
    out, i = [], 0
    while True:
        j = text.find(marker, i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        after = text[j + len(marker):]
        if after.lstrip().lower().startswith(("application", "applicant")):
            out.append(text[i:j] + base)
        else:
            out.append(text[i:j] + marker)
        i = j + len(marker)


def _cme_unit(question: str) -> str:
    """'valid applications' when the default applies to the question, else 'applications'."""
    return f"{_pending_rule.default_text()} applications" if _cme_default_where(question) else "applications"


# A WORKFLOW status the data does not hold (ingestion team, 2026-10-26): "pending",
# "approved", "rejected" and "sent back" live in an internal API field the chatbot
# cannot read; data_verified ('On Hold' …) is the data-verification check, a different
# field. Answering 903 on-hold applications to "how many are pending?" gave a confident
# number for a different question. Such a question gets "not recorded", then the
# figures that ARE recorded, labelled (cme-sector-workflow below).
_CME_WORKFLOW_WORD = Matcher(Cap(Alt(
    W("pending", "pendency", "approved", "approval", "approvals", "rejected", "rejection", "rejections"),
    Seq(W("sent", "send"), "back"), "sendback")))
# …unless the question names a field that IS recorded: then the model path answers it.
_CME_RECORDED_STATUS_WORD = Matcher(Alt(
    _CME_ON_HOLD_ANYWHERE, Pred(lambda w: "verif" in w.lower()),
    W("forward", "forwarded", "resubmit", "resubmitted", "valid", "invalid", "wrong", "vdv", "citizen"),
    W("level", "levels", "stage", "stages"), _cme_level_digit(one_digit=False)))
# "on hold" and the levels belong to the pending rule (2026-10-30), readable or not: only a
# verification / workflow value named outright keeps the model path
_CME_RECORDED_STATUS_WORD_OPEN = Matcher(Alt(
    Pred(lambda w: "verif" in w.lower()),
    W("forward", "forwarded", "resubmit", "resubmitted", "valid", "invalid", "wrong", "vdv", "citizen")))
_CME_ON_HOLD_Q = Matcher(_CME_ON_HOLD_ANYWHERE)
_CME_LEVEL_N = re.compile(r"\blevel[\s-]*(\d+)\b", re.I)          # "level 2", "level-2", "level2"


_CME_LEVEL_ASKED = Matcher(Alt(W("level", "levels", "stage", "stages"), _cme_level_digit(one_digit=False)))


def _cme_level_pending_wording(question: str, schemes: "list[str]", answer: str) -> str:
    """KI-422 (team answer 3, 2026-10-26): "How many CM Elevate applications are pending
    at level 2?" was answered "298 pending … at level 2". The level is recorded
    (current_level), so the figure is right, but "pending" is a workflow status the
    data does not hold. The answer keeps the figure, drops the word, and says so."""
    if schemes != ["CM Elevate"] or not answer or not _CME_PENDING_MATCH.search(question or "") \
            or not _CME_LEVEL_ASKED.search(question or "") or _cme_pending_readable():
        return answer   # pending IS recorded once file_status is readable (rule of 2026-10-30)
    kept = [w for w in answer.split(" ") if w.strip(".,;:!?*").lower() != "pending"]
    out = " ".join(kept)
    if out == answer:
        return answer
    return (out.rstrip() + " The data records the workflow level each application is at "
            "(current_level), not whether it is pending.")


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


def _cme_workflow_query(question: str, resolved: dict) -> "tuple[str, list, str] | None":
    """'how many applications are pending / on hold / approved / rejected / sent back' -> one fixed
    query in DISTINCT applications (request_id: ingestion team 2026-10-26), with the question's
    place, programme, level and grouping. Once the pending rule is readable (2026-10-30) the
    query counts the rule (`pending`) and the Send Back file status (`sent_back`) first, so a
    ranking orders by pending; "on hold" is the same count; a level in the question filters
    current_level and "level-wise" groups by it. While the rule is locked (KI-624) only the
    recorded workflow figures are counted and _cme_sector_answer says the count is not
    available. data_verified is never read here: on hold does not mean the verification
    outcome (user, 2026-10-30)."""
    q = question or ""
    open_ = _cme_pending_readable()
    asked = _CME_WORKFLOW_WORD.search(q) is not None or _CME_ON_HOLD_Q.search(q) is not None
    if not asked or _CME_RECORDED_STATUS_WORD_OPEN.search(q):
        return None
    # 2026-11-04 (ingestion team CHATBOT_DB_CHANGES_2026-11-04, "retire the 26 October workaround"):
    # with the file status readable, an approved / rejected question is a figure the data holds —
    # the model path answers it (rule 13, _cm_elevate_decision_status_column), never "not recorded".
    # Pending / on hold / sent back stay here: this query counts them from the same column.
    _wf = _CME_WORKFLOW_WORD.search(q)
    if open_ and _wf is not None and _wf.group(1).lower().startswith(("approv", "reject")):
        return None
    where, params = [], []
    for single, many, col in (("village_code", "village_code_list", "village_code"),
                              ("block", "block_list", "lgd_block"),
                              ("district", "district_list", "lgd_district")):
        one, lst = resolved.get(single), resolved.get(many)
        if lst:
            params.append([str(x).upper() if col != "village_code" else str(x) for x in lst])
            where.append(f"{col}{'::text' if col == 'village_code' else ''} = ANY(${len(params)}::text[])")
        elif one not in (None, "") and not isinstance(one, (list, dict, tuple, set)):
            params.append(str(one) if col == "village_code" else str(one).upper())
            where.append(f"{col}{'::text' if col == 'village_code' else ''} = ${len(params)}")
    if resolved.get("assembly_constituency"):
        return None
    progs = resolved.get("cm_scheme")
    if progs:
        params.append([progs] if isinstance(progs, str) else list(progs))
        where.append(f"scheme_name = ANY(${len(params)}::text[])")
    level = _CME_LEVEL_N.search(q)
    if level:
        params.append(f"level{int(level.group(1))}")
        where.append(f"LOWER(current_level) = ${len(params)}")
    _d = _cme_default_where(q)
    if _d:
        where.append(_d)
    wh = (" WHERE " + " AND ".join(where)) if where else ""
    grp = None if level else _cme_workflow_group(q)
    sel = f"{grp} AS grp, " if grp else ""
    tail = ("" if not grp else
            " GROUP BY 1 ORDER BY 1" if grp == "LOWER(current_level)" else " GROUP BY 1 ORDER BY 2 DESC, 1")
    pend = ""
    if open_:
        pend = f"COUNT(DISTINCT request_id) FILTER (WHERE {_cme_pending_sql()}) AS pending, "
        fs = _pending_rule.file_status_column()
        if fs:
            pend += f"COUNT(DISTINCT request_id) FILTER (WHERE {fs} = 'Send Back') AS sent_back, "
    sql = (f"/* cme-sector-workflow */ SELECT {sel}{pend}"
           "COUNT(DISTINCT request_id) FILTER (WHERE current_file_status = 'forward') AS forward, "
           "COUNT(DISTINCT request_id) FILTER (WHERE current_file_status = 'resubmit') AS resubmit, "
           "COUNT(DISTINCT request_id) FILTER (WHERE current_file_status = 'sendback to vdv/citizen') AS sendback, "
           f"COUNT(DISTINCT request_id) AS applications FROM curated.v_cm_elevate{wh}{tail}")
    return sql, params, sql


# "Which CM ELEVATE programs have the highest number of pending applications?" got the
# statewide recorded figures only (906 on hold) — the ranking asked for was lost (UAT
# 2026-10-30, OFF-019 / OFF-020). The recorded figures are grouped the way the question asks.
_CME_WF_RANK = Matcher(Alt(W("which", "each", "every", "highest", "most", "top", "rank", "ranked", "ranking",
                             "wise", "by", "per", "lowest", "least"), Seq(_cme_sg("district", "block", "programme",
                                                                                 "program", "scheme"), "wise")))
_CME_WF_GROUPS = (("scheme_name", Matcher(W("programs", "programmes", "schemes", "program", "programme", "scheme"))),
                  ("lgd_district", Matcher(W("districts", "district"))),
                  ("lgd_block", Matcher(W("blocks", "block"))),
                  # level-wise pending (2026-10-30): the rule grouped by current_level, case-folded
                  ("LOWER(current_level)", Matcher(W("levels", "level", "stages", "stage"))))


def _cme_workflow_group(question: str) -> "str | None":
    """The column a 'pending' question ranks or breaks down by, else None. A singular noun
    counts only next to "each" / "which" / "-wise" ("which district has the most…")."""
    q = question or ""
    if not _CME_WF_RANK.search(q):
        return None
    low = q.lower()
    for col, noun in _CME_WF_GROUPS:
        h = noun.search(q)
        if h is None:
            continue
        word = low[h.start():h.end()]
        if word.endswith("s") or any(f"{w} {word}" in low for w in ("each", "which", "every", "per", "by")) \
                or f"{word}-wise" in low or f"{word} wise" in low:
            return col
    return None


# "Show the monthly totals of CM Elevate applications" -> "couldn't build a working query" (UAT
# 2026-10-30, C04-MONTHLY): v_cm_elevate has no date column at all. A month / quarter / trend /
# date-range ask on the applications data is answered with that fact and the recorded total
# (cmelevate_classification_rules.yaml monthly_breakdown_requested / trend_or_growth_requested).
_CME_TIME_ASK = Matcher(Alt(
    W("monthly", "month", "months", "quarterly", "quarter", "quarters", "weekly", "daily", "trend", "trends"),
    _cme_join("month", "wise"), _cme_join("month", "on", "month"), Seq("over", "time"),
    W("january", "february", "march", "april", "june", "july", "august", "september", "october", "november",
      "december"), Seq("last", Pred(lambda w: w.isdecimal()), W("months", "days", "weeks", "years")),
    Seq("last", W("six", "three", "twelve"), W("months", "weeks"))))


def _cme_notime_query(question: str, resolved: dict) -> "tuple[str, list, str] | None":
    if not (_CME_TIME_ASK.search(question or "") or _CME_YEAR_ASK.search(_CME_ALL_YEARS_SCOPE.sub(" ", question or ""))):
        return None
    where, params = [], []
    for single, col in (("village_code", "village_code"), ("block", "lgd_block"), ("district", "lgd_district")):
        v = resolved.get(single)
        if v not in (None, "") and not isinstance(v, (list, dict, tuple, set)):
            params.append(str(v) if col == "village_code" else str(v).upper())
            where.append(f"{col}{'::text' if col == 'village_code' else ''} = ${len(params)}")
    ac = resolved.get("assembly_constituency")
    if isinstance(ac, str) and ac.strip():
        params.append(ac.strip().upper())
        where.append(f"UPPER(ac_name) = ${len(params)}")
    _d = _cme_default_where(question)
    if _d:
        where.append(_d)
    wh = (" WHERE " + " AND ".join(where)) if where else ""
    # the workflow mark (c13 routes it to _cme_sector_answer); the row's cme_kind tells them apart
    sql = ("/* cme-sector-workflow */ SELECT 'notime' AS cme_kind, COUNT(DISTINCT request_id) AS applications "
           f"FROM curated.v_cm_elevate{wh}")
    return sql, params, sql


def _cme_sector_query(question: str, schemes: list[str], resolved: dict) -> "tuple[str, list, str] | None":
    if schemes != ["CM Elevate"]:
        return None
    q = question or ""
    _nt = _cme_notime_query(q, resolved or {})
    if _nt is not None:
        return _nt
    _wf = _cme_workflow_query(q, resolved or {}) if not (_CME_SECTOR_EACH_MATCH.search(q)) else None
    if _wf is not None:
        return _wf
    m = _CME_SECTOR_VALUE_MATCH.search(q)
    progs = _cme_named_programmes(q)
    f = _cme_sector_filters(resolved or {}, "v." if progs else "")
    if f is None:
        return None
    where, params = f
    _d = _cme_default_where(q)
    if _d:
        where.append(("v." if progs else "") + _d)      # the default applications (2026-10-30)
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
        # locked (KI-624): only the applications per sector; the answer says pending is not available
        pend = (f"COUNT(DISTINCT request_id) FILTER (WHERE {_cme_pending_sql()}) AS pending, "
                if _cme_pending_readable() else "")
        sql = ("/* cme-sector-pending */ SELECT COALESCE(sector_id, '(not recorded)') AS sector, "
               f"{pend}"
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


def _cme_pending_answer(question: str, rows: list[dict], word: str, scope: str) -> "str | None":
    """The cme-sector-workflow answer once the pending rule is readable (2026-10-30): a pending
    or on-hold question gets the rule's count, "sent back" the Send Back file status, and the
    recorded figures the rule leaves out are named so they can be asked for. None for a word the
    rule does not cover (approved / rejected keep their own path)."""
    if word == "sent back":
        col, label = "sent_back", "Applications with file status Send Back"
    elif word in ("pending", "on hold"):
        col, label = "pending", "Pending CM Elevate applications"
    else:
        return None
    asked = "pending (on hold)" if word == "on hold" else "pending"
    rule = _cme_pending_text()
    if "grp" in rows[0]:
        group = _cme_workflow_group(question) or ""
        gname = {"scheme_name": "programme", "lgd_district": "district", "lgd_block": "block",
                 "LOWER(current_level)": "level"}.get(group, "group")

        def name(x):
            g = x.get("grp")
            if g is None:
                return "(not recorded)"
            if gname == "level":
                g = str(g)
                return f"Level {g[5:]}" if g.lower().startswith("level") and g[5:] else g
            return _cme_short(g)
        items = [f"{name(x)} {int(_as_number(x.get(col)) or 0):,}" for x in rows]
        total = sum(int(_as_number(x.get(col)) or 0) for x in rows)
        order = "" if gname == "level" else " (highest first)"
        return f"{label}{scope}, by {gname}{order}: " + "; ".join(items) + f". Total {total:,}. {rule}"
    r = rows[0]
    n = {k: int(_as_number(r.get(k)) or 0) for k in ("pending", "sent_back", "applications")}
    if col == "sent_back":
        return (f"{n['sent_back']:,} CM Elevate application{'s' if n['sent_back'] != 1 else ''}{scope} "
                f"{'have' if n['sent_back'] != 1 else 'has'} the file status Send Back (of {n['applications']:,} {_cme_unit(question)}); "
                f"those that also meet the rest of the rule are counted among the {n['pending']:,} pending. {rule}")
    return (f"{n['pending']:,} CM Elevate application{'s are' if n['pending'] != 1 else ' is'} {asked}{scope} "
            f"(of {n['applications']:,} {_cme_unit(question)}). {rule} Not counted (available on request): applications whose "
            "data verification is On Hold, Invalid or Wrong, those resubmitted, and those rejected.")


def _cme_sector_answer(question: str, sql: str, rows: list[dict], display: dict) -> "str | None":
    where = _cme_place_words(display or {})
    kind = _cme_sector_fact_kind(sql)
    if kind == "workflow" and rows and rows[0].get("cme_kind") == "notime":
        kind = "notime"
    if kind == "programmes":
        m = _CME_SECTOR_VALUE_MATCH.search(question or "")
        sector = m.group(1).title() if m else "that"
        lines = [f"- **{_cme_short(r['scheme_name'])}**: {int(_as_number(r.get('sector_applicants')) or 0):,} with sector "
                 f"{sector} (sector recorded on {int(_as_number(r.get('sector_recorded')) or 0):,} of "
                 f"{int(_as_number(r.get('programme_total')) or 0):,} applicants)" for r in rows]
        total = sum(int(_as_number(r.get("sector_applicants")) or 0) for r in rows)
        return (f"CM Elevate applicants associated with the {sector} sector{where}, by programme:\n"
                + "\n".join(lines) + f"\n\nCombined: {total:,}.")
    if kind == "notime" and rows:
        n = int(_as_number(rows[0].get("applications")) or 0)
        return ("A CM Elevate application carries no date — no month, quarter or financial year is recorded "
                "against it — so applications cannot be split or filtered by time. In all, "
                f"{n:,} {_cme_unit(question)} {'are' if n != 1 else 'is'} recorded{where}. (Sanctions and disbursements by "
                "financial year are in CM Elevate Legacy.)")
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
    if kind == "pending" and rows and "pending" in rows[0]:
        # file_status readable: the pending rule of 2026-10-30, by sector
        items = [f"{r['sector']} {int(_as_number(r.get('pending')) or 0):,}" for r in rows]
        total = sum(int(_as_number(r.get("pending")) or 0) for r in rows)
        return (f"Pending CM Elevate applications by sector{where}: " + "; ".join(items)
                + f". Total {total:,}. {_cme_pending_text()} Sector is recorded only on Poultry, Dairy and "
                  "Goat Farming applications, so most applications fall under (not recorded).")
    if kind == "pending":
        # the rule is locked (KI-624): say so, give the applications by sector
        items = [f"{r['sector']} {int(_as_number(r.get('applications')) or 0):,}" for r in rows]
        total = sum(int(_as_number(r.get("applications")) or 0) for r in rows)
        return (f"{_cme_pending_text()} The file status that rule needs is not yet readable by the chatbot's "
                f"database role, so pending by sector is not available{where}. Applications recorded by sector{where}: "
                + "; ".join(items) + f". Total {total:,}. Sector is recorded only on Poultry, Dairy and Goat Farming "
                  "applications, so most applications fall under (not recorded).")
    if kind == "workflow" and rows:
        r = rows[0]
        n = {k: int(_as_number(r.get(k)) or 0) for k in ("forward", "resubmit", "sendback", "applications")}
        m = _CME_WORKFLOW_WORD.search(question or "")
        word = " ".join((m.group(1) if m else ("on hold" if _CME_ON_HOLD_Q.search(question or "") else "pending"))
                        .lower().split())
        word = {"pendency": "pending", "approval": "approved", "approvals": "approved", "rejection": "rejected",
                "rejections": "rejected", "send back": "sent back", "sendback": "sent back"}.get(word, word)
        prog = (display or {}).get("cm_scheme")
        scope = f"{where}" + (f" under {prog}" if prog else "")
        if "pending" in r:
            _pa = _cme_pending_answer(question, rows, word, scope)   # file_status readable (2026-10-30)
            if _pa:
                return _pa
        # the rule is locked (KI-624): the count is not available; the recorded workflow figures
        # are given. data_verified = 'On Hold' is never offered as pending / on hold (user, 2026-10-30).
        gname = {"scheme_name": "programme", "lgd_district": "district", "lgd_block": "block",
                 "LOWER(current_level)": "level"}.get(_cme_workflow_group(question) or "", "group")
        if "grp" in r:
            items = [f"{_cme_short(str(x['grp'])) if x.get('grp') is not None else '(not recorded)'} "
                     f"{int(_as_number(x.get('applications')) or 0):,}" for x in rows]
            total = sum(int(_as_number(x.get("applications")) or 0) for x in rows)
            recorded = (f" {_cme_unit(question).capitalize()} recorded{scope}, by {gname}: " + "; ".join(items)
                        + f". Total {total:,}.")
        else:
            recorded = (f" Recorded{scope}: {n['applications']:,} {_cme_unit(question)}"
                        f" — by current file status {n['forward']:,} forward, {n['resubmit']:,} resubmit, "
                        f"{n['sendback']:,} sendback to vdv/citizen.")
        if word in ("pending", "on hold"):
            what = "on-hold" if word == "on hold" else "pending"
            return (f"{_cme_pending_text()} The file status that rule needs is not yet readable by the "
                    f"chatbot's database role, so the {what} count is not available{scope}." + recorded)
        out = f"The CM Elevate data doesn't record a \"{word}\" status.{recorded}"
        if word == "sent back":
            out += (" The file status \"sendback to vdv/citizen\" is not the department's own Send Back decision, "
                    "which the data does not hold.")
        return out
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
# its text: a text scan read a word inside a literal as a column, missed
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
        # one programme too: "Applicants for the Chief Minister's Elevate programme in Ri Bhoi" got
        # scheme_name = 'Chief Minister''s Green Taxi Scheme' and "1 applicant" (UAT 2026-10-30, C17-09)
        node = next((n for n in (tree.find_all(exp.EQ) if tree is not None else [])
                     if _cme_col(n.this, "scheme_name") is not None and _cme_str(n.expression) is not None), None)
        if node is None:
            return sql
        lits = [_cme_str(node.expression)]
        if any(_cme_question_names(x, q) for x in lits):
            return sql
        if not _cme_drop_conjuncts(tree, lambda c: c is node):
            return sql
        logger.info("CM Elevate: dropped a programme filter the question never named: %s", lits)
        return sql_ast.to_sql(tree)
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
# 2026-11-04 (user; ingestion team CHATBOT_DB_CHANGES_2026-11-04, KI-624 closed): "status" is the
# department's FILE STATUS — the knowledge base's "file status" step (cmelevate_pending_rule.yaml,
# the plain file_status column: Pending / Send Back / Rejected). current_file_status is only the
# file's last MOVEMENT and reads 'forward' for every Rejected application; it answers a question
# that asks for a movement — one of its own stored values (the set data_facts
# cme_file_status_values checks live) or "current file status" by name. While the file-status
# column is not readable, the 2026-09-28 reading (current_file_status) stays.
_CME_MOVEMENT_VALUES = ("forward", "resubmit", "sendback to vdv/citizen")
_CME_MOVEMENT_Q = Matcher(Alt(W(*(v.split()[0] for v in _CME_MOVEMENT_VALUES), prefix=True),
                              Seq("current", "file", "status", sep="space")))


def _cme_status_column() -> "str | None":
    """The file-status column a plain "status" groups by, while the role may read it; else None."""
    return _pending_rule.file_status_column() if _cme_pending_readable() else None


def _cme_status_expr_sql() -> str:
    """The SQL a "status" breakdown groups by: the file status (NULL shown as '(not recorded)')
    once readable, else the 2026-09-28 current_file_status expression."""
    fs = _cme_status_column()
    return f"COALESCE({fs}, '(not recorded)')" if fs else _CME_FILE_STATUS_EXPR
_CME_STATUS_Q = Matcher(Alt(
    _cme_join("status", ("wise", "distribution", "breakdown", "split", "count", "counts")),
    Seq(W("application", "current", "file", "overall"), "status"), Seq("status", W("of", "for", "in")),
    "by status", "each status"))
_CME_VERIFICATION_Q = Matcher(Alt(
    # matched as before, not as whole words: "on hold" may end / start inside a word
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


def _cme_movement_group_exprs(node: exp.Expression) -> list:
    """The current_file_status GROUPING expressions under `node`: the outermost expression built
    from that column alone (the bare column, LOWER / INITCAP of it, the 2026-09-28 CASE). One being
    compared or filtered on (a predicate, a WHERE / FILTER) is a movement filter, not the grouping."""
    found: list = []

    def visit(n: exp.Expression) -> None:
        if isinstance(n, (exp.Predicate, exp.Where, exp.AggFunc)):
            return
        if isinstance(n, exp.Alias):     # the select item keeps its own name
            visit(n.this)
            return
        names = {c.name.lower() for c in n.find_all(exp.Column)}
        if names == {"current_file_status"}:
            found.append(n)
            return
        for child in n.iter_expressions():
            visit(child)

    visit(node)
    return found


def _cm_elevate_status_is_file_status(question: str, schemes: list[str], sql: str) -> str:
    """A plain CM Elevate "status" question grouped by data_verified is rewritten to group by
    the status column: the file status once the role may read it (2026-11-04), current_file_status
    before (2026-09-28). With the file status readable, a grouping on current_file_status moves to
    it too, unless the question asks for a movement (_CME_MOVEMENT_Q). Comparisons (a filter the
    question asked for) are never touched; a question with any verification / pending / on-hold /
    decision word keeps its columns."""
    q = question or ""
    if schemes != ["CM Elevate"] or not sql or not _CME_STATUS_Q.search(q) or _CME_VERIFICATION_Q.search(q):
        return sql
    tree = sql_ast.parse_one(sql)
    sel = sql_ast.outer_select(tree) if tree is not None else None
    if sel is None or not sql_ast.has_group_by(tree):
        return sql
    finders = [_cme_dv_group_exprs]
    if _cme_status_column() and not _CME_MOVEMENT_Q.search(q):
        finders.append(_cme_movement_group_exprs)
    group = sel.args.get("group")
    heads = [n for f in finders for e in sel.expressions for n in f(e)]
    if not heads:
        return sql                       # neither column groups the query — nothing to move
    targets = heads + ([n for f in finders for g in group.expressions for n in f(g)] if group is not None else [])
    status = sqlglot.parse_one(_cme_status_expr_sql(), read=sql_ast.DIALECT)
    for n in targets:
        new = status.copy()
        if n.parent is sel:              # a bare select item keeps a name: "status", not "case"
            new = exp.alias_(new, "status")
        n.replace(new)
    logger.info("CM Elevate: 'status' grouped by %s", _cme_status_column() or "current_file_status (2026-09-28)")
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


# entity_type on v_cm_elevate is the ROW's area type — 'Village', 'Ward' or 'Unresolved' —
# never the level of the area asked about. The block chip resumes "…Umling, the block,
# not another area type": the verifier then asked for a block-level restriction and the
# repair added entity_type = 'Block', so UMLING / SAMANDA / MAWKYRWAT applicants came back
# wrong (CM Elevate UAT, 2026-10-30; MGNREGA had the same, _mgnrega_drop_area_level_entity_type).
# The block / district / constituency filter does the scoping; an area-level filter is dropped.
_CME_ROW_TYPES = frozenset({"village", "ward", "unresolved"})


def _cme_area_level_eq(node: exp.Expression) -> bool:
    """[LOWER|UPPER(][t.]entity_type[)] = '<a value that is not a row type>'."""
    if not isinstance(node, exp.EQ) or _cme_col(node.this, "entity_type") is None:
        return False
    lit = node.expression
    while isinstance(lit, _CME_CASE_WRAPPERS) and lit.this is not None:   # UPPER('block')
        lit = lit.this
    val = _cme_str(lit)
    return val is not None and val.strip().lower() not in _CME_ROW_TYPES


def _cme_sector_not_null(node: exp.Expression) -> bool:
    """[t.]sector_id IS NOT NULL (sqlglot: Is(negate=True), or NOT (… IS NULL))."""
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        node = node.this
    elif not (isinstance(node, exp.Is) and node.args.get("negate")):
        return False
    return _cme_col(node.this, "sector_id") is not None and isinstance(node.expression, exp.Null)


def _cm_elevate_sector_keep_unrecorded(question: str, schemes: list[str], sql: str) -> str:
    """"applicants associated with each sector" grouped by sector_id with `sector_id IS NOT
    NULL` listed Poultry 22, Dairy 7, Piggery 7, Goatery 1 and dropped the 8,884 applications
    with no sector recorded, reading as if sector were known for all (UAT 2026-10-30, OFF-011).
    A sector breakdown keeps that group; the answer names it "(not recorded)"."""
    if schemes != ["CM Elevate"] or not sql or not _CME_SECTOR_EACH_MATCH.search(question or ""):
        return sql
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or tree.args.get("group") is None:
        return sql
    keys = []
    for g in tree.args["group"].expressions:        # GROUP BY 1 -> the first select item
        if isinstance(g, exp.Literal) and g.is_int and 0 < int(g.this) <= len(tree.expressions):
            g = tree.expressions[int(g.this) - 1]
        keys.append(g)
    if not any(_cme_col(g, "sector_id") is not None or _cme_reads_sector_id(g) for g in keys):
        return sql
    if not _cme_drop_conjuncts(tree, _cme_sector_not_null):
        return sql
    logger.info("CM Elevate: sector breakdown keeps the applications with no sector recorded")
    return sql_ast.to_sql(tree)


def _cme_twin_verifier_complaint_is_false(issue: str, schemes: list[str], entity_result: dict, sql: str) -> bool:
    """Same-name villages (J-10 twins): `WHERE village_code IN (<every twin>)`, counted per village or in
    all, is the documented query, but the verifier complained about it on every repair ("uses
    COUNT(DISTINCT request_id) …", "groups by lgd_village_name instead of the resolved value") and
    "How many CM ELEVATE applicants are there in NONGSHILLIANG?" ended "couldn't build a working query"
    (UAT 2026-10-30, C03). An entity / grouping complaint against exactly that query is discarded; a
    complaint about the measure still stands."""
    res = (entity_result or {}).get("resolved") or {}
    codes = {str(c) for c in res.get("village_code_list") or []}
    if schemes != ["CM Elevate"] or not res.get("village_twins") or len(codes) < 2 \
            or not sql_ast.is_parseable(sql or "") or _FL_VERIFIER_MEASURE.search(issue or ""):
        return False
    if sql_ast.tables(sql, qualified=True) != {"curated.v_cm_elevate"} or sql_ast.joins(sql):
        return False
    tree = sql_ast.parse_one(sql)
    node = next((n for n in tree.find_all(exp.In) if _cme_col(n.this, "village_code") is not None
                 and not isinstance(n.parent, exp.Not) and n.expressions
                 and all(isinstance(e, exp.Literal) for e in n.expressions)), None) if tree is not None else None
    vals = {str(e.this) for e in node.expressions} if node is not None else set()
    counts = [c for c in tree.find_all(exp.Count)] if tree is not None else []
    return vals == codes and bool(counts) and all(
        isinstance(c.this, exp.Distinct) and _cme_col(c.this.expressions[0] if c.this.expressions else None, "request_id")
        is not None for c in counts)


def _cme_ac_verifier_complaint_is_false(issue: str, schemes: list[str], entity_result: dict, sql: str) -> bool:
    """A verifier complaint about the join or the resolved constituency raised against the
    documented constituency query, v_cm_elevate -> dim_geography ON geography_key with
    ac_name = the resolved constituency. "applicants in Mairang block that fall in the Mairang
    assembly constituency" wrote exactly that (plus the block) and the verifier called the join
    prohibited on every repair: "couldn't build a working query" (UAT 2026-10-30, H-BxAC;
    the Legacy twin is KI-381). A complaint about the measure or the grain still stands."""
    if _cme_twin_verifier_complaint_is_false(issue, schemes, entity_result, sql):
        return True
    ac = ((entity_result or {}).get("resolved") or {}).get("assembly_constituency")
    if schemes != ["CM Elevate"] or not isinstance(ac, str) or not ac.strip() or not sql_ast.is_parseable(sql or "") \
            or not _FL_VERIFIER_JOIN_OR_ENTITY.search(issue or "") or _FL_VERIFIER_MEASURE.search(issue or ""):
        return False
    if sql_ast.tables(sql, qualified=True) != {"curated.v_cm_elevate", "curated.dim_geography"}:
        return False
    js = sql_ast.joins(sql)
    if not js or not all(j.args.get("on") is not None
                         and {c.name.lower() for c in j.args["on"].find_all(exp.Column)} == {"geography_key"}
                         for j in js):
        return False
    return ac.strip().upper() in _fl_ac_values(sql)


def _cm_elevate_drop_area_level_entity_type(schemes: list[str], sql: str) -> str:
    if schemes != ["CM Elevate"] or not sql:
        return sql
    tree = sql_ast.parse_one(sql)
    if tree is None or not any(_cme_area_level_eq(n) for n in tree.find_all(exp.EQ)):
        return sql
    if not _cme_drop_conjuncts(tree, _cme_area_level_eq):
        return sql
    logger.info("CM Elevate: dropped an entity_type area-level filter (the row type is never the asked level)")
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

    # 2026-11-04: the decision IS readable again, as the plain file-status column
    # (_cme_status_column); approved / rejected move there, in its stored spelling.
    fs = _cme_status_column()

    def fn(tree: exp.Expression) -> None:
        for n in list(tree.find_all(exp.EQ, exp.Like, exp.ILike)):
            hit = _cme_decision_pred(n)
            if hit is not None and hit[1] == "Pending" and _cme_pending_target():
                n.replace(_cme_eq_on(hit[0], _cme_pending_target()))
            elif hit is not None and hit[1] != "Pending" and fs and "->>" not in fs:
                n.replace(_cme_eq_on(hit[0], f"{fs} = '{hit[1]}'"))

    out = sql_ast.transform(sql, fn)
    if out != sql:
        logger.info("CM Elevate: a decision state on current_file_status moved to %s", fs or _cme_pending_target())
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
    if tree is None or any(_cme_on_hold_eq(n) for n in tree.find_all(exp.EQ)) or _cme_reads_file_status(tree):
        return sql
    # any level literal, not just 'level<d>': "pending in 12TH MER" came back as
    # current_level = 'level12' (final pass 2026-09-28, KI-120)
    levels = [n for n in tree.find_all(exp.EQ) if _cme_level_eq(n)]
    if len(levels) != 1 or not _cme_pending_target():
        return sql                       # locked: nothing to resolve a plain "pending" to
    levels[0].replace(_cme_eq_on(_cme_col(levels[0].this, "current_level"), _cme_pending_target()))
    logger.info("CM Elevate: plain 'pending' was filtered on current_level — restored %s", _cme_pending_target())
    return sql_ast.to_sql(tree)


def _cme_reads_file_status(tree: "exp.Expression | None") -> bool:
    """The query already applies the pending rule's file-status step (its JSON key, or the plain
    column when the knowledge base points at one)."""
    if tree is None:
        return False
    keys = _pending_rule.json_keys()
    if keys and (any(str(k.this).lower() in keys for k in tree.find_all(exp.JSONPathKey))
                 or any(str(lit).lower() in keys for lit in sql_ast.string_literals(tree))):
        return True
    col = _pending_rule.file_status_column()
    return bool(col) and "->>" not in col and sql_ast.references_column(tree, col)


# a question that names another verification / workflow state is not a plain "pending"
_CME_PENDING_OTHER_STATE = Matcher(Alt(Pred(lambda w: "verif" in w.lower()),
                                       W("valid", "invalid", "wrong", "resubmit", "resubmitted",
                                         "rejected", "approved", "forward", "forwarded")))
_CME_PENDING_Q = Matcher(Alt(W("pending", "pendency"), _CME_ON_HOLD_ANYWHERE))


def _cm_elevate_pending_funnel(question: str, schemes: list[str], sql: str) -> str:
    """User decision 2026-10-30: a plain "pending" or "on hold" (no other state named) is the
    pending rule — read from the knowledge base — once its columns are readable. A
    `data_verified = 'On Hold'` the model wrote for it becomes the rule (in the WHERE or inside a
    FILTER). A query with no status test gets the rule added: inside the single COUNT's FILTER
    when the query groups (level-wise, district-wise: a group with none still shows 0), else
    AND-ed into the WHERE. Nothing changes while the rule is locked (the KI-074 reading stays)."""
    q = question or ""
    if (schemes != ["CM Elevate"] or not sql or not _cme_pending_readable()
            or not _CME_PENDING_Q.search(q) or _CME_PENDING_OTHER_STATE.search(q)):
        return sql
    tree = sql_ast.parse_one(sql)
    if tree is None or _cme_reads_file_status(tree):
        return sql
    rule = _cme_pending_sql()
    hits = [n for n in tree.find_all(exp.EQ) if _cme_on_hold_eq(n)]
    if hits:
        for n in hits:
            n.replace(_cme_eq_on(n.this, rule))
        logger.info("CM Elevate: 'pending' / 'on hold' — data_verified = 'On Hold' became the pending rule")
        return sql_ast.to_sql(tree)
    sel = _cme_simple_select(tree)
    if sel is None or any(_cme_status_eq(n) for n in tree.find_all(exp.EQ)):
        return sql                       # another verification state was written on purpose
    cond = sqlglot.parse_one(rule, read=sql_ast.DIALECT)
    counts = [n for e in sel.expressions for n in e.find_all(exp.Count) if _cme_plain_count(n)]
    if sel.args.get("group") is not None and len(counts) == 1:
        c = counts[0]
        c.replace(exp.Filter(this=c.copy(), expression=exp.Where(this=cond)))
        logger.info("CM Elevate: grouped 'pending' with no status test — the rule went inside the COUNT's FILTER")
        return sql_ast.to_sql(sel)
    sel.where(cond, append=True, copy=False)
    logger.info("CM Elevate: 'pending' with no status test — the pending rule was added")
    return sql_ast.to_sql(sel)


def _cme_counts_v_cm_elevate(tree: "exp.Expression | None") -> bool:
    """The query counts over curated.v_cm_elevate."""
    return (tree is not None and tree.find(exp.Count) is not None
            and any(t.name.lower() == "v_cm_elevate" for t in tree.find_all(exp.Table)))


def _cme_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value).strip().lower()).strip("_") or "state"


def _cm_elevate_all_applications(question: str, schemes: list[str], sql: str) -> str:
    """User decision 2026-10-30: a question that asks for ALL applications ("all applications",
    "including invalid", "irrespective of verification") gets every application — any default
    filter the model added is dropped — and a single total is also split by verification state
    (COUNT … FILTER per state from the knowledge base, plus "not recorded" for NULL)."""
    if schemes != ["CM Elevate"] or not sql or not _cme_asks_all_applications(question):
        return sql
    tree = sql_ast.parse_one(sql)
    if not _cme_counts_v_cm_elevate(tree):
        return sql
    dcol = _pending_rule.default_column()
    col, states = _pending_rule.verification_states()
    changed = bool(dcol) and _cme_drop_conjuncts(
        tree, lambda n: isinstance(n, exp.EQ) and _cme_col(n.this, dcol) is not None and _cme_str(n.expression) is not None) > 0
    sel = _cme_simple_select(tree)
    if (sel is not None and col and states and sel.args.get("group") is None
            and not sql_ast.references_column(tree, col)):
        counts = [n for e in sel.expressions for n in e.find_all(exp.Count) if _cme_plain_count(n)]
        if len(counts) == 1:
            base = counts[0]
            extra = [exp.alias_(exp.Filter(this=base.copy(), expression=exp.Where(
                        this=sqlglot.parse_one(f"{col} = '{str(v).replace(chr(39), chr(39) * 2)}'", read=sql_ast.DIALECT))),
                     _cme_slug(v)) for v in states]
            extra.append(exp.alias_(exp.Filter(this=base.copy(), expression=exp.Where(
                this=exp.Is(this=exp.column(col), expression=exp.Null()))), "not_recorded"))
            sel.set("expressions", list(sel.expressions) + extra)
            changed = True
    if not changed:
        return sql
    logger.info("CM Elevate: all applications asked — no default filter, total split by verification state")
    return sql_ast.to_sql(tree)


def _cme_tests_verification(tree: exp.Expression, col: str, default: exp.Expression) -> bool:
    """The query itself chooses a verification state: `col` appears anywhere except as the
    default's own condition inside one aggregate's FILTER. User 2026-11-04 ("Give the applicant
    count and pendency for Piggery, Poultry and Dairy in West Khasi Hills, split by sector"): the
    pending count's FILTER (WHERE data_verified = 'Valid' AND file_status IN …) — the pending rule,
    which applies the default itself — made the whole query look verification-scoped, so the
    plain applicant count went out over every status (225 Piggery) under a "valid only" Note."""
    want = sql_ast.to_sql(default)
    for c in tree.find_all(exp.Column):
        if c.name.lower() != col:
            continue
        eq = c.parent
        if isinstance(eq, exp.EQ) and sql_ast.to_sql(eq) == want and eq.find_ancestor(exp.Filter) is not None:
            continue                     # the default itself, scoping one count only
        return True
    return False


def _cm_elevate_valid_default(question: str, schemes: list[str], sql: str) -> str:
    """User decision 2026-10-30: every CM Elevate application count includes only the default
    applications (applications_default in the knowledge base: data verified Valid). A count over
    curated.v_cm_elevate with no test of that column gets it — in the WHERE of a simple query; for
    any other shape the view is read through a default-only subquery so every CTE and join is
    covered. Skipped when the question names a verification state or asks for all applications."""
    d = _pending_rule.default_sql()
    if (schemes != ["CM Elevate"] or not sql or not d or _cme_asks_all_applications(question)
            or _cme_names_verification_state(question)):
        return sql
    tree = sql_ast.parse_one(sql)
    cond = sqlglot.parse_one(d, read=sql_ast.DIALECT)
    if not _cme_counts_v_cm_elevate(tree) or _cme_tests_verification(tree, _pending_rule.default_column(), cond):
        return sql
    sel = _cme_simple_select(tree)
    if sel is not None:
        sel.where(cond, append=True, copy=False)
        logger.info("CM Elevate: count with no verification test — the default applications filter was added")
        return sql_ast.to_sql(sel)
    for t in list(tree.find_all(exp.Table)):
        if t.name.lower() != "v_cm_elevate":
            continue
        alias = t.alias or "v_cm_elevate"
        inner = exp.select("*").from_(exp.table_("v_cm_elevate", db=t.db or "curated")).where(cond.copy())
        t.replace(exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias))))
    logger.info("CM Elevate: count with no verification test — the view is read through the default-only subquery")
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
                   "chief", "minister", "minister's", "centre", "hills", "not", "block",
                   # place words every ward / town row shares: "ward" beside a "1" in another ward's sentence
                   # counted "Dabitbibra - Ward No.10 (1)" as stated, so a list missing it was never rebuilt
                   # (final run 2026-10-30, C01-026-35)
                   "ward", "village", "villages", "municipal", "board", "town", "committee"}
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


_CME_TOPN_Q = Matcher(Seq(W("top", "bottom", "highest", "lowest", "first", "last"), Pred(lambda w: w.isdecimal())))


def _cme_complete_list(question: str, answer: str, rows: list[dict]) -> str:
    """KI-068 (text half): "applicants under each CM ELEVATE program" named 5 of
    the 15 programmes ("the remaining schemes range from 4 … up to 3,617").
    When the question asks for EVERY value (each / distribution / breakdown)
    and some row's figure is not beside its label, rebuild the list from the
    rows. A "which is highest" question naming its top few is left alone."""
    # Also rebuilt (UAT 2026-10-30): same-name villages answered together (J-10 twins, rows per
    # village_code + lgd_block) — "Chandigre … highest 16 in Rongram, lowest 4 in Chokpot" left out
    # Demdema's 7 (C03); and "top 5 / bottom 5" lists — "the top 5 villages in East Khasi Hills"
    # gave figures for the first and last only (C10).
    twins = bool(rows) and "village_code" in rows[0] and "lgd_block" in rows[0] and 2 <= len(rows) <= 3         and len({str(r.get("lgd_village_name") or "").upper() for r in rows}) == 1
    if not (_CME_WHOLE_LIST_Q.search(question or "") or twins or _CME_TOPN_Q.search(question or ""))             or not 2 <= len(rows) <= 200:
        return answer
    nums = _fp_numeric_cols(rows)
    labels = [k for k in rows[0] if k not in nums]
    # "each village of Umling" rows carry lgd_village_name + the same lgd_block on every row
    # + village_code: the composer summed up 93 villages as "highest 69 in UMSHAKEN, lowest 1"
    # and the list was never rebuilt (UAT 2026-10-30, OFF-026). A code column and a label
    # that is the same on every row do not tell the rows apart.
    if len(labels) > 1:
        labels = [k for k in labels if not _NONSTAT_COL.search(k)
                  and len({str(r.get(k)).upper() for r in rows}) > 1] or labels
        if len(labels) > 1 and "lgd_village_name" in labels:      # villages across blocks: the village names them
            labels = ["lgd_village_name"]
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
    ranked = sorted((r for r in rows if _as_number(r.get(met)) is not None),
                    key=lambda r: -(_as_number(r.get(met)) or 0))
    items = [f"{_cme_short(r[lab]) if r.get(lab) is not None else '(not recorded)'} "
             f"{_fmt_num(_as_number(r.get(met)))}" for r in ranked]
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
    value is in the result; otherwise it is left for the checks to see.
    _NUMBER_WORDS / _NUMBER_TENS / _NUMBER_WORD_MATCH are defined in
    common/c12_answer_numbers.py; the pipeline files share one namespace and this
    runs only after every file is loaded, so they resolve at call time."""
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


def _cme_compare_missing_zero(sql: str, rows: list[dict], answer: str) -> str:
    """"Compare … Agriculture Response Vehicle and Dairy across East Jaintia Hills and East Khasi
    Hills" listed the 3 combinations that have rows and said nothing of Dairy in East Jaintia Hills
    (0): GROUP BY returns no row for a pair with no applications (UAT 2026-10-30, C01-027-03). Every
    asked programme x district pair without a row is stated as 0."""
    progs, dists = _cme_scheme_in_values(sql), _cme_district_in_values(sql)
    if not progs or len(dists) < 2 or not rows or "scheme_name" not in rows[0] or "lgd_district" not in rows[0]:
        return answer
    have = {(str(r["scheme_name"]).upper(), str(r["lgd_district"]).upper()) for r in rows}
    miss = [(pr, d) for pr in progs for d in dists if (pr.upper(), d.upper()) not in have]
    if not miss:
        return answer
    logger.info("CM Elevate: comparison stated %d programme x district pair(s) with no applications as 0", len(miss))
    return (answer.rstrip() + "\nNo applications (0): "
            + "; ".join(f"{_cme_short(pr)} in {_place_title(d)}" for pr, d in miss) + ".")


_CME_AC_NAMES: "set[str] | None" = None


async def _cme_unknown_constituency(sql: str) -> "str | None":
    """A constituency in the SQL that v_cm_elevate does not hold: "How many CM Elevate applicants are
    there in El Dorado constituency?" ran UPPER(ac_name) = UPPER('El Dorado') and said "0 applicants — the
    data records zero" for a place that does not exist (UAT 2026-10-30, C14-INV-17)."""
    global _CME_AC_NAMES
    vals = {str(v).strip() for v in _fl_ac_values(sql or "")} if sql else set()
    if not vals:
        return None
    if _CME_AC_NAMES is None:
        try:
            rows = await fetch_rows("SELECT DISTINCT UPPER(ac_name) AS a FROM curated.v_cm_elevate WHERE ac_name IS NOT NULL", [])
            _CME_AC_NAMES = {str(r["a"]) for r in rows}
        except Exception:  # noqa: BLE001 — without the list, say nothing
            return None
    bad = [v for v in vals if v.upper() not in _CME_AC_NAMES]
    return _place_title(bad[0]) if bad else None


def _cme_village_not_in_named_block(question: str, rows: list[dict]) -> "str | None":
    """"MAWBRI village of Mawkyrwat block" was answered with the Mawbri villages of Bhoirymbong and
    Khatarshnong Laitkroh — no Mawbri in Mawkyrwat has an application (UAT 2026-10-30, C14). When the rows
    carry their block and none is the block the question names, the answer is 0 for that village there."""
    q = question or ""
    low = q.lower()
    i = low.find(" village of ")
    j = low.find(" block", i + 12) if i >= 0 else -1
    if i < 0 or j < 0 or not rows or "lgd_block" not in rows[0]:
        return None
    blk = q[i + 12:j].strip()
    k = low.rfind(" in ", 0, i)
    vil = q[k + 4:i].strip() if k >= 0 else ""
    # only "in <name> village of <block> block": not "each village of Ranikor, the block, not another
    # area type" (a resumed chip) nor any list question (final run 2026-10-30, C01-026)
    if not vil or vil.lower().split()[0] in ("each", "every", "all", "the") or "," in blk or "," in vil             or not all(ch.isalnum() or ch in " -.()'" for ch in blk + vil):
        return None
    want = "".join(ch for ch in _cme_block_base(blk).lower() if ch.isalnum())
    have = {"".join(ch for ch in _cme_block_base(str(r.get("lgd_block") or "")).lower() if ch.isalnum()) for r in rows}
    if not want or want in have or not vil:
        return None
    return (f"There are no CM Elevate applicants (0) in {vil} village of {blk} block. "
            f"Villages named {vil} in other blocks: "
            + "; ".join(f"{_place_title(str(r.get('lgd_block')))} {int(_as_number(next((v for k2, v in r.items() if _as_number(v) is not None and k2 != 'village_code'), 0)) or 0):,}"
                        for r in rows) + ".")


async def _cme_village_code_not_in_named_block(question: str, sql: str) -> "str | None":
    """The single-row form of _cme_village_not_in_named_block: "MEGONGGRE village of Tikrikilla block"
    (no CM Elevate application) was answered with village_code 273068, the MEGONGGRE of Selsella block
    (UAT 2026-10-30, C14). The blocks of the village codes the SQL filters are read; none of them being
    the named block means 0 for the village asked."""
    low = (question or "").lower()
    i = low.find(" village of ")
    j = low.find(" block", i + 12) if i >= 0 else -1
    if i < 0 or j < 0 or not sql:
        return None
    tree = sql_ast.parse_one(sql)
    codes = []
    for n in (tree.find_all(exp.EQ, exp.In) if tree is not None else []):
        if _cme_col(n.this, "village_code") is None:
            continue
        lits = [n.expression] if isinstance(n, exp.EQ) else list(n.expressions)
        codes += [int(x.this) for x in lits if isinstance(x, exp.Literal) and str(x.this).isdigit()]
    if not codes:
        return None
    try:
        rows = await fetch_rows("SELECT DISTINCT lgd_block AS lgd_block, COUNT(DISTINCT request_id) AS applicants "
                                "FROM curated.v_cm_elevate WHERE village_code = ANY($1::int[]) GROUP BY 1", [codes])
    except Exception:  # noqa: BLE001
        return None
    return _cme_village_not_in_named_block(question, [dict(r) for r in rows]) if rows else None


_CME_YEAR_PHRASE = Matcher(Seq(W("for", "in", "during"), Opt("the"), Opt(W("year", "fy", "financial")), Opt("year"),
                               Pred(lambda w: len(w) == 4 and w[:2] == "20" and is_int(w)),
                               Opt(Pred(lambda w: len(w) == 2 and is_int(w))), sep="any"))
_CME_YEAR_IN_Q = Matcher(Alt(Pred(lambda w: len(w) == 4 and w[:2] == "20" and is_int(w)), W("fy", "year", "years")))


def _cme_drop_invented_year(question: str, answer: str) -> str:
    """"There are 16 CM ELEVATE applicants in Mawhati (Mawhati block) for the year 2024": the applications
    data holds no date, and nobody asked about a year (UAT 2026-10-30). A year phrase the question did
    not bring is removed from the answer."""
    if not answer or _CME_YEAR_IN_Q.search(question or ""):
        return answer
    for _ in range(4):
        h = _CME_YEAR_PHRASE.search(answer)
        if h is None:
            break
        start = h.start()
        while start > 0 and answer[start - 1] == " ":
            start -= 1
        answer = answer[:start] + answer[h.end():]
    return answer


async def _cm_elevate_answer_guarantees(question: str, sql: str, rows: list[dict], answer: str,
                                        display: dict) -> str:
    """Every CM Elevate DATA answer passes through here after the composer."""
    unknown = await _cme_unknown_constituency(sql)
    if unknown:
        return (f"I couldn't find an assembly constituency called “{unknown}” in the CM Elevate data. Please check "
                "the name, or ask for a district or block instead.")
    other = _cme_village_not_in_named_block(question, rows) or await _cme_village_code_not_in_named_block(question, sql)
    if other:
        return other
    if not rows:
        return _cme_all_zero_answer(sql, answer, display)
    answer = _cme_digits_for_number_words(answer, rows)
    answer = _cme_drop_invented_year(question, answer)
    answer = _cme_verification_figures(answer, rows)
    answer = _cme_sector_answer_names_wrong_programme(answer, sql, rows)
    answer = _mgnrega_zero_backstop(answer, rows, display)   # a genuine 0 is stated as 0 (KI-070)
    answer = _cme_grouped_rows(answer, rows)
    answer = _cme_complete_list(question, answer, rows)
    answer = _cme_multi_scheme_total(question, sql, rows, answer)
    answer = _cme_compare_missing_zero(sql, rows, answer)
    answer = _cme_sericulture_split_note(question, sql, answer)
    # KI-074 decided 2026-09-28 (product owner): "pending" = verification On Hold
    # only. The interim second line with the file_status Pending count is gone.
    return _cme_comparison(question, rows, answer)


_CME_SERICULTURE = "Meghalaya Sericulture & Weaving Scheme"


def _cme_sericulture_split_note(question: str, sql: str, answer: str) -> str:
    """SME rule `sericulture_spinning_weaving_split_assumed` (cmelevate_classification_rules.yaml):
    the applications dataset holds Sericulture as ONE scheme, so a spinning / weaving question
    is told no such split exists here. "How many applications are recorded under Meghalaya
    Sericulture & Weaving Scheme (spinning)?" was answered "14 applications for spinning" —
    the combined figure as if it were spinning's (Legacy sheet TC-12, 2026-10-30). The split
    (spinning / weaving) is held only in CM Elevate Legacy."""
    words = [t.low for t in tokens(question or "")]
    asks_split = "spinning" in words or "handloom" in words or words.count("weaving") >= 2
    if not asks_split or _CME_SERICULTURE not in sql_ast.filter_values(sql or "", "scheme_name"):
        return answer
    note = (f"Note: CM Elevate (applications) holds Sericulture as one scheme — {_CME_SERICULTURE} — "
            "not split into spinning and weaving, so this figure covers both. The spinning / weaving "
            "split is recorded only in CM Elevate Legacy.")
    if "not split" in answer:
        return answer
    # the composer's "14 applications for spinning" names a filter the SQL never applied
    for side in ("spinning", "weaving", "handloom"):
        for lead in (" for ", " under "):
            answer = answer.replace(f"{lead}{side}", "").replace(f"{lead}{side.capitalize()}", "")
    return f"{note}\n\n{answer}"

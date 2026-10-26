# app/pipeline/common/c05_clarifications.py — scope / top-N / region clarifications.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.

# Text matching (D-047): text is read on WORDS (app/text_match.py); the
# _C04* nodes and _c04* helpers come from c04_scheme_listing.py (loaded first).
from app.text_match import (ANY, Alt, Matcher, NotAfter, NotBefore, Opt, Pred, Rep, Seq, W, collapse_ws, words as _c05_words)


# ── Bank / financial-channel details — not held for most loaded schemes ─────
# Focus Plus now exposes bank_name_raw via curated.v_focus_plus (added so
# bank-wise disbursement questions can be answered), but it has no
# account-number/IFSC field, so those specific asks still need the
# not-held explanation. PMAY-G, CM Elevate and MGNREGA never captured any
# bank field at ingest at all. Without this check an account/IFSC question
# reaches SQL generation, which correctly finds no column to use but can only
# hand back a bare "not available in this data" — true, but it doesn't say
# *why*, so route it to a real explanation up front.
_BANK_REQUESTED = Matcher(Alt(
    W("bank", "banks", "banking", "ifsc", "dbt", "lifcom"),
    _c04JoinedPrefix("bank", "account"), _c04JoinedPrefix("account", "number"),
    _c04Joined("bank", "wise"), _c04JoinedPrefix("bank", "transfer"),
))
# Focus Plus only lacks account-number/IFSC fields — bare bank-name questions
# ("which bank", "bank-wise disbursement") should reach SQL generation instead.
# "Bank account" asks for account details only with a detail word after it:
# "paid into Meghalaya Rural Bank accounts" names where the money went (a bank
# name, which is held), while "bank account numbers / details" asks for what
# is not.
BANK_ACCOUNT_DETAIL_WORDS = W("number", "numbers", "no", "nos", "detail", "details", "status", "holder",
                              "holders", "info", "information", "wise", "id", "ids")
_BANK_ACCOUNT_DETAIL_REQUESTED = Matcher(Alt(
    W("ifsc", "dbt"), Seq(_c04JoinedPrefix("bank", "account"), BANK_ACCOUNT_DETAIL_WORDS),
    _c04JoinedPrefix("account", "number"), _c04JoinedPrefix("bank", "transfer"),
))
# CM Elevate Legacy's loan_entity holds only the categories 'Bank' / 'LIFCOM'.
# These ask for an individual bank or branch, which is not recorded.
_LENDER_DETAIL_REQUESTED = Matcher(Alt(
    W("branch", "branches", "sbi", "mrb"), _c04Joined("bank", ("name", "names")),
    Seq("name", "of", Opt("the"), W("bank", "banks")),
    Seq("which", Opt(W("particular", "specific")), W("bank", "banks")),
    Seq("state", "bank"), Seq("meghalaya", "rural", "bank"), Seq("cooperative", "bank"),
))
_BANK_NOT_HELD_TEXT = {
    "Focus Plus": (
        "Account numbers and IFSC codes aren't held for Focus Plus — only the "
        "bank name is. Shall I answer using bank name instead?"
    ),
    # There was no Focus Legacy entry, so a Focus Legacy bank question raised
    # KeyError here — which is where the "which bank?" chip for Focus Legacy
    # leads (Focus Plus use-case QA 2026-09-27, FOCUS-029 / KI-063).
    "Focus Legacy": (
        "Account numbers, bank-transfer status and DBT outcomes aren't exposed for "
        "Focus Legacy — only the bank name and IFSC code are. Shall I answer using "
        "bank name or IFSC code instead?"
    ),
    "CM Elevate": (
        "There is no loan-channel field in the CM Elevate applications data — Bank and "
        "LIFCOM are recorded only in CM Elevate Legacy (the sanction and disbursement "
        "records). Shall I answer from CM Elevate Legacy, or on applications by scheme "
        "or district instead?"
    ),
    "CM Elevate Legacy": (
        "Individual bank names, branches, IFSC codes and account numbers are not held "
        "for CM Elevate Legacy — the only lender values recorded are 'Bank' and "
        "'LIFCOM'. Shall I show loans by those two lender categories instead?"
    ),
    "PMAY-G": (
        "Bank transfer status, DBT outcomes and account details are not held for "
        "PMAY-G — only the amount released and the number of installments are. "
        "Shall I use those instead?"
    ),
    "MGNREGA": (
        "Bank details are not held for MGNREGA — only wages, person-days, job "
        "cards and expenditure are. Shall I answer using one of those instead?"
    ),
}
_BANK_GENERIC_TEXT = (
    "Bank name is only held for Focus Plus and Focus Legacy — MGNREGA, PMAY-G "
    "and CM Elevate never captured a bank field at ingest. Focus Legacy also "
    "holds the IFSC code; no scheme exposes account numbers. Shall I answer "
    "using Focus Plus or Focus Legacy bank name, or by scheme, district, block "
    "or village instead?"
)


def _named_or_inferred_schemes(question: str) -> list[str]:
    named = [s for s, word_matcher in _SCHEME_NAME_MATCHER.items() if word_matcher.search(question)]
    return named or _infer_scheme_from_terms(question) or []


def _bank_clarification(question: str) -> "ClarificationNeeded | None":
    schemes = _named_or_inferred_schemes(question)
    is_account_detail = bool(_BANK_ACCOUNT_DETAIL_REQUESTED.search(question))
    if not is_account_detail and schemes == ["Focus Plus"]:
        # Bare bank-name question scoped to Focus Plus only — bank_name_raw is
        # queryable via curated.v_focus_plus, so let SQL generation handle it.
        return None
    if schemes == ["Focus Legacy"] and not _FOCUS_LEGACY_BANK_NOT_HELD.search(question):
        # bank_name / ifsc_code are real columns on v_focus_legacy
        # ("Which banks handle Focus Legacy payments?").
        return None
    if not schemes and not is_account_detail:
        # "Which bank processed the highest total disbursement?" names no
        # scheme. Only Focus Plus and Focus Legacy hold a bank name, so offer
        # exactly those two as chips. This pause used to carry NO options, so
        # the officer had to type "Focus Plus" — and a typed reply to a pause
        # the router does not remember went through as the brand-new question
        # "Focus Plus" (a KB scheme overview; the bank question was lost).
        # The rule is in SCHEME_PAUSE_RULES, so a typed scheme name now resumes
        # the question exactly as its chip does (Focus Plus use-case QA
        # 2026-09-27, FOCUS-029 / KI-063).
        stem = question.strip().rstrip(" ?.")
        return ClarificationNeeded(
            _BANK_GENERIC_TEXT,
            options=[{"label": f"{s} (bank name)", "question": _scheme_option_question(stem, s)}
                     for s in ("Focus Plus", "Focus Legacy")],
            rule="bank-scheme-not-specified",
        )
    if schemes == ["CM Elevate Legacy"] and not is_account_detail \
            and not _LENDER_DETAIL_REQUESTED.search(question):
        # "loans by Bank vs LIFCOM", "how many LIFCOM loans" — loan_entity is a
        # real, queryable lender column there. Only a named bank / branch /
        # account asks for something the data does not hold.
        return None
    text = _BANK_NOT_HELD_TEXT[schemes[0]] if len(schemes) == 1 else _BANK_GENERIC_TEXT
    return ClarificationNeeded(text, rule="column-not-held")


# ── Administrative expenditure — deliberately excluded from reporting ──────
# The raw source has adm_exp_rec / adm_exp_non_rec / adm_exp_total (MGNREGA) and
# an equivalent programme-expenditure figure (PMAY-G), but both are intentionally
# left out of the curated views/facts (data/mgnrega/README.md marks them
# **excluded**; mgnrega_classification_rules.yaml and pmay_classification_rules.yaml
# both define a dedicated "administrative_expenditure_requested" condition for
# exactly this). That YAML condition was never wired into the live pipeline
# (see the "deliberately NOT loaded here yet" note in annotations.py), so without
# this check the question reached SQL generation, which has no such column to
# read and either errors or returns a wrong/empty figure instead of explaining
# the exclusion.
_ADMIN_EXPENDITURE_REQUESTED = Matcher(Alt(
    Seq("administrative", W("expenditure", "expense", "cost", "spend", "spending")),
    Seq("admin", W("expenditure", "expense", "cost")),
    Seq("overhead", W("expenditure", "expenditures", "cost", "costs")),
    Seq(W("programme", "program"), "expenditure"),
))
# The MGNREGA wording says the figure is EMPTY rather than absent, because that
# is what the data actually shows. curated.v_expenditure does expose
# admin_total_exp, but it is non-zero on exactly ONE of its 18,818 rows (₹0.90
# lakh, Alokdia / DEMDEMA block / FY 2023-24) against ₹362,866 lakh of total
# expenditure — docs/schema_for_developers.md records it as "effectively
# unpopulated". Saying it "isn't held" was misleading: a user who checks the
# schema finds the column and reasonably concludes the assistant is wrong
# (reported 2026-09-17, "admin expenditure in demdema"). Reporting the real
# 0.00 would be worse — it reads as a measured finding rather than an empty
# column — so the honest answer names the column, says it was never populated,
# and offers the figures that were.
_ADMIN_EXPENDITURE_NOT_HELD_TEXT = {
    "MGNREGA": (
        "MGNREGA's administrative expenditure column exists but was never populated "
        "at ingest — it is zero on every row but one in the whole state, so there is "
        "no real figure to report{scope}. The expenditure that IS recorded is "
        "unskilled wage, semi-skilled wage, material and total. Did you mean total "
        "expenditure instead?"
    ),
    "PMAY-G": (
        "Administrative and programme expenditure are not held for PMAY-G{scope} — only "
        "the per-house sanctioned and released amounts are. Did you mean amount released "
        "instead?"
    ),
}
_ADMIN_EXPENDITURE_GENERIC_TEXT = (
    "There is no usable administrative-expenditure figure{scope} in any scheme I cover. "
    "MGNREGA has the column but it was never populated (zero on every row but one "
    "statewide), and PMAY-G records only sanctioned and released amounts. Shall I "
    "answer using wage, material or total expenditure instead?"
)


# The place the question asked about, so the reply can say "…for Demdema"
# rather than answering in the abstract. Deliberately a light touch: the name
# is echoed back as the user typed it (title-cased), NOT resolved — this check
# runs long before resolve_entities, and a refusal about an empty column is the
# same refusal at any admin level, so there is nothing to disambiguate.
_ADMIN_EXP_PREP = ("in", "for", "at", "of", "under", "from", "within")
_C05_NAME_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.'-")


def _c05_name_chunk(c: str) -> bool:
    """One word of a place name: an ASCII letter, then letters or . ' -"""
    return bool(c) and c[0].isascii() and c[0].isalpha() and all(ch in _C05_NAME_CHARS for ch in c)


def _c05_place_name(rest: list) -> "str | None":
    """1-3 name words, then only ?.! up to the end ("Demdema?", "Ri Bhoi ?")."""
    if not rest:
        return None
    body = list(rest)
    if len(body) >= 2 and all(ch in "?.!" for ch in body[-1]):
        body.pop()
    else:
        core = body[-1].rstrip("?.!")
        if not core:
            return None
        body[-1] = core
    if not 1 <= len(body) <= 3 or not all(_c05_name_chunk(c) for c in body):
        return None
    return " ".join(body)


def _admin_exp_place(text: str) -> "str | None":
    """The place named by the question's trailing "in/for/at/of/under/from/within
    <1-3 words>" phrase (several prepositions may stack: "in for X"), else None.
    `text` has its whitespace collapsed to single spaces."""
    chunks = (text or "").split(" ")
    for idx, chunk in enumerate(chunks[:-1]):
        low = chunk.lower()
        prep = next((p for p in _ADMIN_EXP_PREP if low.endswith(p)
                     and (len(low) == len(p) or not _c04_is_word_char(chunk[-len(p) - 1]))), None)
        if prep is None:
            continue
        rest = chunks[idx + 1:]
        n_preps = 0
        while n_preps < len(rest) and rest[n_preps].lower() in _ADMIN_EXP_PREP:
            n_preps += 1
        for p in range(n_preps, -1, -1):
            name = _c05_place_name(rest[p:])
            if name:
                return name
    return None
_ADMIN_EXP_NOT_A_PLACE = {
    "mgnrega", "mnrega", "nrega", "pmay", "pmay g", "pmayg", "awaas", "awas",
    "focus plus", "focusplus", "cm elevate", "cmelevate", "meghalaya",
    "the state", "each district", "every district", "all districts",
}


def _admin_expenditure_scope(question: str) -> str:
    """' in Demdema' when the question names a place, else ''."""
    # Strip any scheme name first. "…for PMAY-G in Tura" otherwise lets the
    # trailing-phrase match start at "PMAY-G" and produce "for Pmay-G In Tura",
    # which also duplicates the scheme the sentence has already named.
    text = question or ""
    for word_matcher in _SCHEME_NAME_MATCHER.values():
        text = word_matcher.sub(" ", text)
    name = _admin_exp_place(collapse_ws(text))
    if not name:
        return ""
    name = name.strip().rstrip(".,")
    if name.lower() in _ADMIN_EXP_NOT_A_PLACE or len(name) < 3:
        return ""
    return f" in {name.title()}"


# MGNREGA holds actual expenditure only (v_expenditure: wage / material / tax /
# admin / total_exp) — no sanctioned amount, sanction or budget. The YAML's own
# question for it (mgnrega_classification_rules.yaml, budget_vs_actual_requested)
# was never wired in, so "Total sanctioned amount in Rasong" ran SUM(total_exp)
# and the answer called expenditure "sanctioned" (user, live 2026-10-21, KI-350).
_MG_SANCTION_REQUESTED = Matcher(W("sanctioned", "sanction", "sanctions", "budget", "budgeted", "budgets"))
_MG_SANCTION_PHRASES = ("total sanctioned amount", "sanctioned amount", "amount sanctioned",
                        "sanctioned budget", "total budget", "budget", "sanctioned", "sanction")


def _mgnrega_sanction_clarification(question: str) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    instead = stem
    for phrase in _MG_SANCTION_PHRASES:
        if _ci_find(instead, phrase) >= 0:
            instead = _ci_replace(instead, phrase, "total expenditure", count=1)
            break
    instead = instead[:1].upper() + instead[1:]
    return ClarificationNeeded(
        "MGNREGA records only the expenditure actually incurred — there is no sanctioned "
        "amount or budget in this data to report. Shall I report the total expenditure instead?",
        options=[{"label": "Total expenditure instead", "question": f"{instead}?"}],
        rule="column-not-held",
    )


def _admin_expenditure_clarification(question: str) -> "ClarificationNeeded":
    schemes = _named_or_inferred_schemes(question)
    if len(schemes) == 1 and schemes[0] in _ADMIN_EXPENDITURE_NOT_HELD_TEXT:
        text = _ADMIN_EXPENDITURE_NOT_HELD_TEXT[schemes[0]]
    else:
        text = _ADMIN_EXPENDITURE_GENERIC_TEXT
    return ClarificationNeeded(text.format(scope=_admin_expenditure_scope(question)),
                               rule="column-not-held")


def _needs_scheme_clarification(question: str) -> bool:
    """True when the question names no scheme, doesn't ask for a cross-scheme
    view outright, and uses no vocabulary that pins it to one scheme. In that
    case we ask rather than guess — a wrong scheme guess produces a confident
    but meaningless answer (e.g. 'PMAY has 0 paid beneficiaries')."""
    if not settings.SCHEME_CLARIFY_ENABLED:
        return False
    if any(p.search(question) for p in _SCHEME_NAME_MATCHER.values()):
        return False
    if _EXPLICIT_BOTH.search(question):
        return False
    # A superlative asked ACROSS schemes ("which scheme spent the most?") names
    # the scheme as its ANSWER — pausing to ask which scheme is meant would be
    # asking the user for the thing they came to find out.
    if _CROSS_SCHEME_SUPERLATIVE.search(question or ""):
        return False
    if _infer_scheme_from_terms(question) is not None:
        return False
    return True


# ── "Top how many?" clarification ───────────────────────────────────────────
# A ranking question over a dimension ("top districts", "which blocks spent the
# most", "rank villages by person-days") that names no count. Silently defaulting
# to a fixed top-N is a guess the user can't see or correct; a one-tap follow-up
# ("Top 3 / 5 / 10 / all") is cheaper than returning the wrong list length.
# "at least one" / "at most 100" set a threshold, not a ranking: "how many
# villages recorded at least one person-day" is a count, not a top-N list.
_RANKING_CUE = Matcher(Alt(
    NotAfter(W("most", "least"), W("at")),
    W("top", "bottom", "highest", "lowest", "best", "worst", "leading", "leader", "lead",
      "leads", "rank", "ranked", "ranking", "largest", "smallest", "biggest", "maximum", "minimum")))
# A plural dimension noun — a ranking only needs a length when it returns rows to
# cut. "which district spent the most" (singular) already means the single top row.
_C05_DOT = lambda g: g == "."  # noqa: E731
_C05_DIMENSION = Alt(
    W("districts", "blocks", "villages", "panchayats", "gps"), Seq("gram", "panchayats"),
    _C04SepSeq("g", "p", "s", ok=_C05_DOT), _C04SepSeq("gp", "s", ok=_C05_DOT), _C04SepSeq("g", "ps", ok=_C05_DOT),
)
_RANK_DIMENSION = Matcher(_C05_DIMENSION)
# A count written as a number word ("which three blocks", "the five districts").
_C05_COUNT_WORDS = W("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                     "twelve", "fifteen", "twenty", "fifty", "hundred")
# An explicit count is already in the question — nothing to ask.
_C05_WS_DASH = lambda g: all(c.isspace() or c == "-" for c in g)  # noqa: E731
_EXPLICIT_COUNT = Matcher(Alt(
    Pred(lambda w: len(w) > 3 and w.lower().startswith("top") and w[3:].isascii() and w[3:].isdigit()),
    _C04SepSeq("top", _c04_digits(), ok=_C05_WS_DASH),
    Seq(W("top", "bottom", "first", "last"),
        W("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")),
    Seq(_c04_digits(), W("highest", "lowest", "largest", "biggest", "smallest", "top", "best", "worst",
                         "most", "least")),
    # The count right before the dimension: "which 3 blocks", "the 5 villages",
    # "which three districts" — the list length is already stated.
    Seq(Alt(_c04_digits(1, 3), _C05_COUNT_WORDS), _C05_DIMENSION),
))
# The user wants the whole list, not a ranked head — also nothing to ask.
_WANTS_ALL = Matcher(Alt(
    Seq(W("all", "every", "each", "entire", "complete", "full"), _C04CharGap(20, "\n"),
        W("district", "districts", "block", "blocks", "village", "villages", "panchayat", "panchayats",
          "list", "row", "rows")),
    Seq("list", Opt("of"), "all"), Seq(W("for", "across"), "all"), Seq("no", "limit"), Seq("every", "row"),
    # A free-text reply to the "top 3/5/10 or the complete list?" pause — the
    # dimension word (blocks/districts/...) already sits earlier in the merged
    # question, not right after "all", so these stand on their own instead of
    # requiring one of the words above within 20 chars.
    Seq("all", "of", W("them", "it")), "everything",
    Seq(W("show", "give"), Opt("me"), "all"), Seq("the", W("complete", "full"), "list"),
    # A bare "all" as the whole reply, merged on as the trailing comma-fragment
    # ("...sanctioned in 2023-24, all") — anchored to end-of-string so an
    # unrelated mid-question "all" (e.g. "all of Meghalaya") isn't caught here;
    # that shape is already handled by the dimension-adjacent alternative above.
    Seq(_C04GapBefore(lambda g: g.rstrip().endswith(",")), "all",
        _C04Tail(lambda t: t.strip() in ("", "?", "."))),
))
_TOPN_CHOICES = (3, 5, 10)
# "top" not already followed by a number ("top 5", "top-10").
_C05_BARE_TOP = Matcher(NotBefore(W("top"), Seq(_C04GapBefore(_C05_WS_DASH), Pred(lambda w: w[:1].isdigit()))))


def _needs_topn_clarification(question: str) -> bool:
    """True when the question asks for a ranked list over a dimension but never
    says how long the list should be."""
    if not settings.TOPN_CLARIFY_ENABLED:
        return False
    q = question or ""
    if not (_RANKING_CUE.search(q) and _RANK_DIMENSION.search(q)):
        return False
    if _EXPLICIT_COUNT.search(q) or _WANTS_ALL.search(q):
        return False
    return True


def _inject_topn(question: str, n: int) -> str:
    """Rewrite the ranking question so it states the count `n`, so the resumed
    turn is a complete standalone question the SQL layer can LIMIT on."""
    q = question.strip().rstrip(" ?.")
    new_q, hit = _C05_BARE_TOP.subn(f"top {n}", q, count=1)
    if hit:
        return new_q + "?"
    # No literal "top" to splice into ("which blocks spent the most") — append it.
    return f"{q}, showing only the top {n}?"


def _topn_clarification(question: str) -> "ClarificationNeeded":
    q = question.strip().rstrip(" ?.")
    options = [{"label": f"Top {n}", "question": _inject_topn(question, n)} for n in _TOPN_CHOICES]
    options.append({"label": "All of them", "question": f"{q}, return every row with no limit?"})
    return ClarificationNeeded(
        "How many results should be returned — the top 3, the top 5, the top 10, "
        "or the complete list?",
        options=options,
        rule="ranking-count-not-specified",
    )


# ── "Which area / year?" clarification ──────────────────────────────────────
# An aggregate question ("how many houses sanctioned", "total MGNREGA
# expenditure", or a bare "show MGNREGA spend") that names no place and no year
# gets answered statewide across every year — a scope the user never asked for
# and can't see in the reply. One free-text follow-up ("West Garo Hills
# 2023-24") is cheaper than a number that silently means something else.
# Applies to MGNREGA and PMAY-G alike.
_AGGREGATE_CUE = Matcher(Alt(
    Seq("how", W("many", "much")), Seq(W("number", "count", "no", "sum"), "of"),
    Seq("total", Opt("number")),
    Seq("what", W("s", "is", "was"), "the", "total"),
    W("average", "avg", "mean"),
))
# A bare metric noun with no quantity word in front of it — "show MGNREGA
# spend", "PMAY-G houses", "person-days". On its own the metric name still means
# "give me the total <metric>", so it needs a place and a year just as much as
# an explicit "how much" does. Kept to unambiguous scheme metrics — generic
# words ("amount", "money", "funds", "works") are left out so a membership or
# list question isn't dragged into a scope pause.
_BARE_METRIC_CUE = Matcher(Alt(
    _c04Joined("person", ("day", "days")),
    W("expenditure", "spend", "spending", "spent", "wage", "wages"),
    Seq("wage", "bill"), Seq("job", W("card", "cards")), Seq("muster", W("roll", "rolls")),
    Seq(W("house", "houses"), Opt(W("sanctioned", "completed", "approved", "released", "pending"))),
    Seq("dwelling", W("unit", "units")), Seq("sanctioned", "amount"), Seq("amount", "released"),
    W("instalment", "installment", "instalments", "installments", "disbursement", "disbursements",
      "utilisation", "utilization"),
))
# The question already fixes its own scope (a breakdown, a trend, a comparison
# across a dimension, or an explicit "all of Meghalaya") — nothing to ask.
_C05_DIMS = ("district", "block", "village", "panchayat", "year", "month", "scheme", "program",
             "programme", "sector")
_C05_GEO = W("district", "districts", "block", "blocks", "village", "villages", "panchayat",
             "panchayats", "gp", "gps")
_C05_GEO_SCHEME = W("district", "districts", "block", "blocks", "village", "villages", "panchayat",
                    "panchayats", "gp", "gps", "scheme", "schemes", "program", "programs", "programme",
                    "programmes", "sector", "sectors")
_C05_SCHEME_DIM = W("scheme", "schemes", "program", "programs", "programme", "programmes", "sector",
                    "sectors")
_C05_SUPER = W("highest", "lowest", "most", "least", "maximum", "minimum", "greatest", "top", "biggest",
               "largest", "smallest")
_C05_WHICH_GEO = Seq("which", W("district", "districts", "block", "blocks", "village", "villages",
                                "panchayat", "panchayats", "gp", "gps"))
_HAS_BREAKDOWN = Matcher(Alt(
    Seq("by", W("district", "block", "village", "panchayat", "gp", "year", "month", "scheme", "program",
                "programme", "sector")),
    Seq(Alt("per", "each", "every", Seq("for", "all"), Seq("across", "all"), Seq("all", "the")),
        W(*_C05_DIMS, *[d + "s" for d in _C05_DIMS])),
    # "under each CM ELEVATE program", "for every PMAY-G scheme" — a scheme name
    # or other short qualifier can sit between "each/every" and the dimension
    # word itself; allow up to a few words of slack for scheme/program/sector
    # specifically (kept out of the tight matcher above to avoid over-matching
    # "each ... district" style geography phrasing where slack isn't needed).
    Seq(W("per", "each", "every"), _C04CharGap(25, "?.!"), _C05_SCHEME_DIM),
    # "in each financial year", "total disbursed through each loan entity" —
    # a qualifier before "year", and category dimensions the tight matcher
    # above never listed. Both are groupings over every value, so asking
    # "which area / year?" first was wrong, and the "all years" reply then got
    # collapsed into ONE total instead of a per-year split (CM Elevate Legacy
    # QA TC-21 / TC-22 / TC-23 / TC-24, 2026-09-25).
    Seq(W("per", "each", "every", "by"), W("financial", "fiscal"), W("year", "years")),
    Seq(W("per", "each", "every", "by"), Opt("loan"),
        W("entity", "entities", "lender", "lenders", "category", "categories", "tranche", "tranches",
          "instalment", "installment", "instalments", "installments")),
    _c04Joined(("district", "block", "village", "year", "scheme", "program", "programme", "sector"), "wise"),
    _c04Joined("break", "down"), "trend", Seq(_c04Joined("year", "on"), "year"), Seq("year", _c04Joined("on", "year")), "yearonyear",
    Seq("over", Opt("the"), W("last", "past"), ANY, W("year", "years")),
    W("compare", "comparison", "versus", "vs"), W("correlat", prefix=True),
    Seq("relationship", "between"), Seq("linked", W("to", "with")),
    Seq(_C05_GEO, W("with", "where", "that", "having", "which")),
    # A rank window over a geography dimension — "top 5 districts", "bottom
    # blocks", "10 largest villages". It inherently spans every area in that
    # dimension, so geography is already scoped; only the year is still open.
    Seq(W("top", "bottom", "leading", "largest", "biggest", "smallest", "highest", "lowest"),
        Opt(_c04_digits()), _C05_GEO_SCHEME),
    Seq(_c04_digits(), W("largest", "biggest", "smallest", "highest", "lowest"), _C05_GEO_SCHEME),
    # "which district received the highest ...", "district with the lowest
    # ..." — the same rank-window logic as "top N districts" above, just
    # phrased as "which <geo> ... <superlative>" instead of "<superlative>
    # <geo>". Still inherently spans every area in the dimension, so
    # geography is already scoped; only the year is still open. Anchored
    # loosely (superlative anywhere within ~40 chars either side of the
    # geography noun) so "which district received the highest total
    # disbursement" and "highest total expenditure in which district" both
    # match.
    Seq(_C05_WHICH_GEO, _C04CharGap(40, "?"), _C05_SUPER),
    Seq(_C05_SUPER, _C04CharGap(40, "?"), _C05_WHICH_GEO),
    # Same rank-window shape as above, but for scheme/program/sector — a scheme
    # name or other qualifier ("CM Elevate", "PMAY-G") often sits between
    # "which" and the dimension word itself ("which CM Elevate programs have
    # the highest..."), so this variant allows slack there too.
    Seq("which", _C04CharGap(25, "?.!"), _C05_SCHEME_DIM, _C04CharGap(40, "?"), _C05_SUPER),
    Seq(_C05_SUPER, _C04CharGap(40, "?"), "which", _C04CharGap(25, "?.!"), _C05_SCHEME_DIM),
    Seq("across", Opt("the"), Alt(_C05_GEO_SCHEME, W("state", "year", "years"))),
    # "Which blocks have …", "list the districts with …": the answer IS the list of
    # places, so it spans every area. A list question with a threshold and no
    # superlative still asked "which area?" (held-out NL->SQL set, 2026-10-24).
    Seq(W("which", "what"), W("districts", "blocks", "villages", "panchayats", "gps")),
    Seq(W("list", "name"), Opt(W("the", "all")), W("districts", "blocks", "villages", "panchayats", "gps")),
))
_EXPLICIT_STATEWIDE = Matcher(Alt(
    Seq(W("in", "for", "across", "over", "of"),
        Opt(Alt(Seq("all", "of"), Seq("the", W("whole", "entire")))), "meghalaya"),
    _c04Joined("state", ("wide", "level", "total")), "overall", Seq("in", "total"), Seq("grand", "total"),
    Seq("all", Opt("the"), W("years", "districts", "blocks", "villages")), Seq("entire", "state"),
    Seq("every", "year"), Seq("since", "inception"), _c04Joined("all", "time"),
    Seq(Opt("up"), W("to", "till", "until"), W("date", "now")), Seq("so", "far"), "cumulative",
    # Other ways of saying "the whole state", each of which still asked "which
    # area?" (held-out NL->SQL set, 2026-10-24). A wording that states the area
    # must never be asked for it (D-053 / D-056).
    "altogether", Seq(W("whole", "entire"), W("state", "meghalaya")),
    Seq(W("for", "in", "across", "of", "at"), "the", "state"), Seq("state", "as", "a", "whole"),
))

# A cross-scheme set / overlap question whose answer IS a geography list or its
# count — "how many common districts in both schemes", "which villages are
# covered by both", "districts with both MGNREGA and PMAY-G activity". Geography
# is the thing being counted, not a filter, so there is no area or year to ask
# for — it is inherently statewide across the whole data window. This must not
# swallow a plain cross-scheme metric question ("how much did both schemes
# spend"), so every branch is anchored to a geography noun.
_C05_GEO_AREA = W("district", "districts", "block", "blocks", "village", "villages", "panchayat",
                  "panchayats", "gp", "gps", "area", "areas")
_C05_OVERLAP = Alt(W("common", "shared"), W("overlap", "convergen", prefix=True))
_CROSS_SCHEME_SET_QUESTION = Matcher(Alt(
    Seq(Alt(W("common", "shared", "overlapping", "overlap", "mutual", "distinct", "unique"),
            W("convergen", prefix=True)),
        Alt(_C05_GEO_AREA, Pred(lambda w: len(w) > 8 and w.lower().startswith("geograph")))),
    Seq(_C05_GEO_AREA, Rep(W("are", "is", "were", "was", "that", "which", "have", "having", "has"), 0, 2),
        Alt(Seq("common", W("to", "across", "between")), Seq("shared", W("by", "between", "across")),
            Seq("in", W("both", "all", "either")), Seq("covered", W("by", "under"), "both"),
            Seq("covered", "by", Opt("both"), W("mgnrega", "pmay", "schemes")),
            Seq(W("with", "have", "having", "under", "running"), "both"), Seq("present", "in", "both"),
            Seq("served", "by", "both"), Seq("in", "common"))),
    Seq("how", "many", W("district", "districts", "block", "blocks", "village", "villages", "panchayat",
                         "panchayats", "gp", "gps"),
        _C04CharGap(None, "?"),
        Alt(Seq("both", W("scheme", "schemes")), Seq("both", "mgnrega", "and", "pmay"),
            Seq("pmay", "and", "mgnrega"), Seq("in", "common"), "overlap")),
    # "blocks (wise) common in both schemes", "which blocks are common in both",
    # "common blocks in both schemes" — a geography noun sitting next to both
    # "common"/"shared"/"overlap" and "both", in either order. Still anchored to
    # the geography noun so a bare metric question can't match.
    Seq(_C05_GEO_AREA, Opt("wise"), _C04CharGap(30, "?"), _C05_OVERLAP, _C04CharGap(20, "?"), "both"),
    Seq(_C05_OVERLAP, _C04CharGap(20, "?"), _C05_GEO_AREA, _C04CharGap(20, "?"), "both"),
))


def _needs_scope_clarification(question: str, resolved: dict) -> bool:
    """True when an aggregate question — an explicit "how many / total …" or a
    bare metric noun on its own ("show MGNREGA spend") — pins no geography and no
    year, neither in its text nor via a resolved entity, and doesn't ask for a
    breakdown or an explicit statewide total. Callers must have run
    `resolve_entities` first so `resolved` reflects any district/block/village/
    year actually named."""
    if not settings.SCOPE_CLARIFY_ENABLED:
        return False
    q = question or ""
    if not (_AGGREGATE_CUE.search(q) or _BARE_METRIC_CUE.search(q)):
        return False
    if _HAS_BREAKDOWN.search(q) or _EXPLICIT_STATEWIDE.search(q):
        return False
    if _CROSS_SCHEME_SET_QUESTION.search(q):
        return False
    if any(resolved.get(k) for k in
           ("district", "district_list", "block", "block_list", "village_code",
            "village_code_list", "assembly_constituency", "year_key")):
        return False
    # A calendar date pins the time more tightly than a year_key does: "How many
    # PMAY houses were sanctioned on 2017-11-28?" is a statewide single-day
    # count, not a question missing its period (2026-09-27 screenshot).
    if _CALENDAR_DATE_MATCH.search(q):
        return False
    # A Focus Plus tranche or batch IS the scope the question pins ("How much
    # was disbursed under Tranche 2?", "…under the 12.5K batch?"): the SME
    # default for missing geography is statewide (focusplus_default_rules.yaml
    # missing_geography), and asking "which area?" first only added a click
    # (Focus Plus use-case QA 2026-09-27, FOCUS-006/007, KI-064).
    if resolved.get("tranche_label") or _FOCUSPLUS_BATCH_WORD.search(q):
        return False
    return True


# A full calendar date: 2017-11-28, 2017/11/28, 28-11-2017, 28/11/2017, and the
# written forms "15 December 2020", "15th Dec, 2020", "December 15, 2020". The
# written forms were added after the PMAY-G use-case QA (2026-09-28, KI-094):
# "How many PMAY houses were sanctioned on 15 December 2020?" paused for an area
# and the premise check read the "15" as a figure the user had assumed.
_MONTH_FORMS = ("jan", "january", "feb", "february", "mar", "march", "apr", "april", "may", "jun", "june",
                "jul", "july", "aug", "august", "sep", "sept", "september", "oct", "october", "nov",
                "november", "dec", "december")
_MONTH_NAME = W(*_MONTH_FORMS)


def _c05_gap(dot: bool, comma: bool):
    """A separator test: an optional '.', an optional ',', then whitespace (at least one)."""
    def ok(g: str) -> bool:
        i = 0
        if dot and g[i:i + 1] == ".":
            i += 1
        if comma and g[i:i + 1] == ",":
            i += 1
        rest = g[i:]
        return rest != "" and rest.strip() == ""
    return ok


def _c05_is_day(w: str) -> bool:
    """1-2 digits, optionally followed by st / nd / rd / th ("15", "15th")."""
    low = w.lower()
    if low[-2:] in ("st", "nd", "rd", "th"):
        low = low[:-2]
    return 1 <= len(low) <= 2 and low.isascii() and low.isdigit()


def _c05_is_year(w: str, centuries=("19", "20", "21")) -> bool:
    return len(w) == 4 and w[:2] in centuries and w.isascii() and w.isdigit()


_C05_DATE_SEP = lambda g: g in ("-", "/", ".")  # noqa: E731
_C05_YEAR_192021 = Pred(_c05_is_year)
_C05_DAY_NUM = _c04_digits(1, 2)
_CALENDAR_DATE_MATCH = Matcher(Alt(
    _C04SepSeq(_C05_YEAR_192021, _C05_DAY_NUM, _C05_DAY_NUM, ok=_C05_DATE_SEP),
    _C04SepSeq(_C05_DAY_NUM, _C05_DAY_NUM, _C05_YEAR_192021, ok=_C05_DATE_SEP),
    _C04SepSeq(Seq(Pred(_c05_is_day), Opt("of"), _MONTH_NAME, sep="space"), _C05_YEAR_192021,
               ok=_c05_gap(True, True)),
    _C04SepSeq(_C04SepSeq(_MONTH_NAME, Pred(_c05_is_day), ok=_c05_gap(True, False)), _C05_YEAR_192021,
               ok=_c05_gap(False, True)),
))


# A reply to the scope pause is normally a bare fragment ("Ri Bhoi, 2023-24").
# These shapes instead mean the user dropped the earlier question and asked a
# fresh one — don't fold them into the original.
_REPLY_IS_NEW_QUESTION = Matcher(Alt(
    Seq("how", W("many", "much")), Seq(W("number", "count"), "of"),
    Seq("what", W("s", "is", "are", "was"), "the"), Seq("who", W("is", "can")), Seq("how", "do", "i"),
    Seq("how", "to", "apply"), Seq(W("what", "which"), W("document", "documents")),
    W("explain", "define"), Seq("difference", "between"), Seq("tell", "me", "about"),
    # A reply OPENING with "which ..." is a question of its own, not a place or
    # a year — "Which banks handle Focus Legacy payments?" was being merged into
    # the stale paused question. Anchored to the start so "the block, which is
    # in Ri Bhoi" is unaffected.
    Seq(_C04Lead(lambda h: h.strip() == ""), "which"),
))


# A reply that OPENS with one of these is giving an instruction, not naming a
# place or a year. _REPLY_IS_NEW_QUESTION covers interrogative phrasings only,
# so an imperative slipped through and got glued onto the stale paused question
# ("List top 5 PGs which has more than 10 of members." came back as the previous
# turn's Nongstoin block-or-village prompt — reported 2026-09-23).
_REPLY_IS_IMPERATIVE = Matcher(Seq(
    _C04Lead(lambda h: h.strip() == ""), Opt("please"),
    W("list", "show", "give", "display", "rank", "compare", "find", "search"),
))

# A scope pause asks for exactly a place and/or a year, so that vocabulary is
# the EXPECTED reply and must never read as "a new question". Stripping it out
# before the metric test is what separates "West Garo Hills, 2023-24" (a scope
# reply — nothing left once place and year are removed) from "Total amount
# disbursed by district" (a real question — the metric survives). An earlier
# version tested only for a BARE year and wrongly abandoned the pause on the
# commonest reply shape of all, place-plus-year.
_C05_Y4 = _c04_digits(4, 4)
_C05_YEAR_HEAD = Alt(Seq("fy", _C05_Y4, sep="space"),
                     Pred(lambda w: len(w) == 6 and w[:2].lower() == "fy" and w[2:].isascii() and w[2:].isdigit()),
                     _C05_Y4)
_SCOPE_REPLY_VOCAB = Matcher(Alt(
    _C04SepSeq(_C05_YEAR_HEAD, _c04_digits(2, 4), ok=lambda g: g.strip() == "-"),   # 2023-24, FY 2021-22
    _C05_YEAR_HEAD,
    Seq("all", Opt("of"), "meghalaya", sep="space"), Seq("all", W("year", "years"), sep="space"),
    Seq("all", W("district", "districts"), sep="space"), "statewide",
    Seq("the", W("block", "village", "district", "constituency"), sep="space"),
    Seq("not", W("the", "another"), sep="space"), Seq("area", "type", sep="space"), "combined",
))


def _c05_scope_residue(reply: str) -> str:
    """The reply with its expected scope vocabulary (years, "all of Meghalaya",
    "statewide", ...) and every ',' / '.' replaced by spaces."""
    return _SCOPE_REPLY_VOCAB.sub(" ", reply).replace(",", " ").replace(".", " ")


@functools.lru_cache(maxsize=1)
def _known_place_names() -> tuple[str, ...]:
    """Every district and block name the resolvers know, lowercased, longest
    first. Used only to strip a place out of a scope reply before testing it for
    a metric — so "West Garo Hills" cannot be mistaken for question vocabulary.
    Built from the catalogues already loaded at startup; empty if they are not,
    in which case the test simply falls back to the year/phrase stripping."""
    from app import entity_resolver

    names: set[str] = set()
    for scheme in list(entity_resolver._catalog):
        for dim in ("district", "block"):
            for v in entity_resolver._catalog.get(scheme, {}).get(dim, []):
                c = str(v.get("canonical") or "").strip().lower()
                if len(c) >= 4:
                    names.add(c)
    return tuple(sorted(names, key=len, reverse=True))


# A reply that points back at the paused question instead of answering it
# ("how much OF THAT was spent on materials?") — see _turn_context_stage.
_BACKREF_FOLLOWUP_MATCH = Matcher(Alt(
    Seq(Alt("of", "from", Seq("out", "of"), "in"), W("that", "this", "it", "those")),
    Seq("that", W("amount", "figure", "total", "number", "expenditure", "sum")),
    Seq("of", "the", W("same", "above")),
))


# "show it year-wise", "by year", "each year please", "break it down yearly" —
# a reply to the year pause that asks for every year, one row each.
_YEARWISE_REPLY_CUE = Matcher(Alt(
    _c04Joined("year", "wise"), Seq("by", Opt("financial"), W("year", "years")),
    Seq(W("each", "every"), Opt("financial"), "year"), Seq("per", "year"), W("yearly", "annual", "annually"),
    _c04Joined("year", "by", "year"), Seq("for", "all", Opt("the"), "years"),
))


# KI-324 (live 2026-10-19, conversation harness META_officer_overview_reason): the
# year pause asks "a single financial year, or all of them combined?", and a typed
# "all of them combined" / "all" / "combined" was merged onto the stem as
# ", all of them combined", which no year cue reads, so the same pause came back.
# Such a reply IS the "All financial years combined" chip. Read on words: every
# word must be from this small vocabulary, at least one of them must say "all",
# nothing may name a year, a measure or a scheme.
_ALL_YEARS_REPLY_WORDS = frozenset((
    "all", "of", "them", "these", "those", "the", "years", "year", "fy", "fys", "financial", "fiscal",
    "combined", "together", "every", "overall", "cumulative", "everything", "please", "give", "me",
    "show", "i", "want", "it", "for", "sum", "summed", "across", "whole", "period", "entire"))
_ALL_YEARS_REPLY_KEYS = frozenset(("all", "combined", "every", "overall", "cumulative", "everything", "entire", "whole"))


def _is_all_years_reply(reply: str) -> bool:
    ws = _c05_words(reply)
    if not ws or len(ws) > 8 or not set(ws) <= _ALL_YEARS_REPLY_WORDS:
        return False
    if not set(ws) & _ALL_YEARS_REPLY_KEYS:
        return False
    if _parse_year_key(reply or "") is not None or _DATA_HINTS.search(reply or "") or _named_schemes(reply or ""):
        return False
    return True


def _is_yearwise_reply(reply: str) -> bool:
    r = (reply or "").strip()
    if len(r.split()) > 8 or not _YEARWISE_REPLY_CUE.search(r):
        return False
    # Anything beyond the cue and filler that names a measure or a scheme is a
    # new question ("show person-days year-wise"), not a reply.
    rest = _YEARWISE_REPLY_CUE.sub(" ", r)
    return not (_DATA_HINTS.search(rest) or _named_schemes(rest))


def _reply_abandons_scope_pause(reply: str) -> bool:
    """True when the reply to a 'which area / year?' pause is itself a new,
    self-standing question rather than the scope fragment we asked for."""
    r = (reply or "").strip()
    if len(r.split()) > 12:
        return True
    if _REPLY_IS_NEW_QUESTION.search(r) or _KNOWLEDGE_HINTS.search(r):
        return True
    if _REPLY_IS_IMPERATIVE.search(r):
        return True
    # A scope fragment names a place and/or a year and nothing else. Strip that
    # expected vocabulary, plus any place NAME the resolver knows, and see
    # whether a METRIC survives: if one does, the reply is a question in its own
    # right whatever its grammatical shape (the same signal the DATA router
    # trusts). "West Garo Hills, 2023-24" reduces to nothing and still merges.
    residue = _c05_scope_residue(r)
    for place in _known_place_names():
        if place in residue.lower():
            residue = _c04_replace_ci(residue, place, " ")
    if _DATA_HINTS.search(residue):
        return True
    return False


# ── "Which district in this region?" clarification ─────────────────────────
# "Garo Hills" / "Khasi Hills" / "Jaintia Hills" name a hill RANGE, not a district —
# each covers several districts (region_groupings in the *_entity_resolver.yaml). When
# a question names one and no specific district, offer its districts as one-tap chips
# instead of the generic "which area?" free-text pause. Applies to every scheme.
def _swap_region_phrase(question: str, aliases: list[str], repl: str) -> str:
    """Replace the first hill-range phrase in `question` with `repl`. Longest alias
    first so 'South West Garo Hills' isn't half-matched by 'Garo Hills'."""
    forms = sorted({a for a in aliases if a}, key=len, reverse=True)
    pat = Matcher(Alt(*[Seq(*_c05_words(a)) for a in forms if _c05_words(a)]))
    new, n = pat.subn(repl, question, count=1)
    return new if n else f"{question.rstrip(' ?.')} for {repl}"


def _region_clarification(question: str, region: dict) -> "ClarificationNeeded":
    canon = region["canonical"]
    dists = region["districts"]
    aliases = [canon, *region.get("aliases", [])]
    all_list = ", ".join(dists[:-1]) + " and " + dists[-1]
    options = [{"label": d, "question": _swap_region_phrase(question, aliases, d)}
               for d in dists]
    options.append({
        "label": f"All of {canon} combined",
        "question": _swap_region_phrase(question, aliases, f"all of {canon}"),
    })
    return ClarificationNeeded(
        f"“{canon}” is a region covering {len(dists)} districts "
        f"— {all_list}. Which district, or all of {canon} combined?",
        options=options,
        rule="region-needs-district",
    )


# ── "Show me the districts, I'll pick one" after a data answer ─────────────
# Reported 2026-10-18: after "how many houses are there in 2023-2024" was
# answered for all of Meghalaya, "don't give all of Meghalaya, ask me … What are
# the districts? Then I will choose one." was routed to the KB, which answered
# that the scheme documents hold no district list. The user is asking to narrow
# the PREVIOUS answer to one district of their choice: offer that scheme's
# districts as chips, each the previous question for that district.
_PICK_PLACE_VERBS = frozenset("choose chose choosing pick picking select selecting".split())
_LIST_PLACE_WORDS = frozenset("list listing available names".split())
# A data question about districts, not a request for the list to choose from.
_PICK_PLACE_RANKING = frozenset((
    "most highest lowest least top bottom maximum minimum max min best worst more fewer less "
    "each every wise by per breakdown compare comparison rank ranking ranked"
).split())


def _asks_to_pick_district(text: str) -> bool:
    """True when the message asks to see the districts in order to choose one
    ("show me the districts, I will choose one", "ask me which district",
    "list the districts"), rather than asking a question about districts
    ("which district has the most houses", "district-wise houses")."""
    ws = [w.lower().replace("’", "'") for w in _c05_words(text or "")]
    if not ({"district", "districts"} & set(ws)):
        return False
    if _PICK_PLACE_RANKING & set(ws):
        return False
    if "district-wise" in (text or "").lower():
        return False
    choose = bool(_PICK_PLACE_VERBS & set(ws)) or any(
        ws[i:i + 2] in (["ask", "me"], ["will", "say"], ["i'll", "say"], ["let", "me"])
        for i in range(len(ws)))
    listing = bool(_LIST_PLACE_WORDS & set(ws)) or any(
        ws[i:i + 3] in (["what", "are", "the"], ["which", "are", "the"], ["show", "me", "the"],
                        ["districts", "are", "there"], ["tell", "me", "the"])
        for i in range(len(ws)))
    # "how many districts are there" is a count, not a request to choose.
    if not choose and any(ws[i:i + 2] in (["how", "many"], ["how", "much"]) for i in range(len(ws))):
        return False
    return choose or listing


def _c05_statewide_stem(question: str, prev_district: "str | None" = None) -> str:
    """A data question without its statewide scope ("for all of Meghalaya") or its
    earlier district, ready to take a new place or a breakdown."""
    stem = collapse_ws(question or "").rstrip(" ?.")
    for scope in ("for all of Meghalaya", "in all of Meghalaya", "across Meghalaya",
                  "for Meghalaya", "in Meghalaya"):
        stem = collapse_ws(_c04_replace_ci(stem, scope, " "))
    if prev_district:
        for form in (f"for {prev_district}", f"in {prev_district}", prev_district):
            stem = collapse_ws(_c04_replace_ci(stem, form, " "))
    return stem.rstrip(" ,?.")


def _pick_district_clarification(prev_question: str, schemes: list[str],
                                 prev_district: "str | None" = None) -> "ClarificationNeeded | None":
    """The previous data question offered once per district (chips), with its
    statewide scope ("for all of Meghalaya") or its earlier district taken out.
    None when no district list is known for the scheme(s)."""
    stem = _c05_statewide_stem(prev_question, prev_district)
    seen: dict[str, None] = {}
    for s in schemes or []:
        for d in all_districts(s):
            seen.setdefault(d, None)
    if not stem or not seen:
        return None
    options = [{"label": d, "question": f"{stem} in {d}"} for d in seen]
    options.append({"label": "All of Meghalaya", "question": f"{stem} for all of Meghalaya"})
    e = ClarificationNeeded(
        "Which district should I show? Pick one below, or type a district, block or village name.",
        options=options,
        rule="scope-not-specified",
    )
    e.stem = stem
    return e


def _scope_clarification(question: str, schemes: list[str], area_only: bool = False) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    # District chips first (picking one still leaves the year open, so it falls
    # straight into `_year_clarification` on the next turn — a second round of
    # buttons rather than free text), then the one-tap statewide/all-years
    # shortcut, mirroring how `_year_clarification` appends its own "combined"
    # option last.
    seen: dict[str, None] = {}
    for s in schemes or []:
        for d in all_districts(s):
            seen.setdefault(d, None)
    # Schemes with NO time dimension at all (CM Elevate — see
    # _needs_year_clarification's identical check) still need the AREA half of
    # this ask (a bare "how many applications" is a real, useful district-level
    # question, and CM Elevate's own few-shot corpus has district-scoped
    # examples) — but asking "and which financial year?" on top is nonsensical
    # when no year exists anywhere on the fact. Reword rather than skip the
    # gate outright (an earlier pass tried skipping it entirely and lost the
    # district ask too — see cmelevate-routing-gates-bug memory).
    live = [s for s in (schemes or []) if s in _SCHEME_DATA_YEARS]
    # area_only=True: the new-chat district ask (D-056); the year, if still
    # open, is asked on its own next, so this one names only the area.
    area_only = area_only or (bool(live) and all(not _SCHEME_DATA_YEARS[s] for s in live))
    if area_only:
        options = [{"label": d, "question": f"{stem} for {d}"} for d in seen]
        options.append({
            "label": "All of Meghalaya",
            "question": f"{stem} for all of Meghalaya",
        })
        return ClarificationNeeded(
            "Which area should the answer cover — a specific district, block, or "
            "village? Pick a district below, or choose the statewide total; you can "
            "also just type a block or village name.",
            options=options,
            rule="scope-not-specified",
        )
    options = [{"label": d, "question": f"{stem} for {d}"} for d in seen]
    # Statewide chip is area-only (2026-09-26 UI request): like a district chip,
    # it leaves the year open so `_year_clarification` offers the FY chips next,
    # instead of silently pinning "all years".
    options.append({
        "label": "All of Meghalaya",
        "question": f"{stem} for all of Meghalaya",
    })
    return ClarificationNeeded(
        "Which area and time period should the answer cover — a specific district, "
        "block, or village, and which financial year? Pick a district below, or "
        "choose all of Meghalaya; you can also just type a block or "
        "village name (for example, \"West Garo Hills, 2023-24\").",
        options=options,
        rule="scope-not-specified",
    )

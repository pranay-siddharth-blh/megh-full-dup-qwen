# app/pipeline/common/c06_years_tranches.py — financial years, year gaps, tranches, cross-scheme money, overall summary.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.

# No regular expressions (D-047): text is read on WORDS (app/text_match.py); the
# _C04*/_c04* and _c05* helpers come from c04_scheme_listing.py / c05_clarifications.py.
from app.text_match import ANY, Alt, Matcher, NotBefore, Opt, Pred, Seq, W, tokens as _c06_tokens


# ── "Which financial year?" clarification ───────────────────────────────────
# The scope gate above only fires when a question pins NO geography at all. A
# question that already fixes its place — "compare districts for MGNREGA", "total
# PMAY-G houses in West Garo Hills" — sails past it and is then answered across
# EVERY financial year at once, a scope the user never chose and can't see in the
# reply. This gate catches exactly that: geography is settled, the year is not.
# One-tap year chips (the scheme's FYs + "all years combined") resume the flow.
#
# The financial years each scheme actually holds in megh_db — the SINGLE source
# of truth for every year chip we offer (the "which year?" pause AND the
# out-of-range guard). These are DEFAULTS only: refresh_scheme_years() overwrites
# them at startup with the real DISTINCT year_key set from the curated views, so
# the chips and the guard always match the live data even after a data reload.
# Values below were verified against curated.v_employment / v_expenditure
# (MGNREGA) and curated.v_pmay (PMAY-G) on 2026-08-30 — MGNREGA covers FY
# 2022-23..2025-26; PMAY-G covers FY 2017-18..2023-24 (NOT 2024-25 / 2025-26).
# Focus Plus holds only FY 2022-23 (Tranch 1) and FY 2025-26 (Tranches 2-4) — the two
# middle years are empty for it (focusplus_schema_partitions.yaml). A three-year gap is
# expected, and asking a Focus Plus question for FY 2023-24 / 2024-25 correctly triggers
# the "that year isn't in the data" guard.
# CM Elevate is DIFFERENT IN KIND, not just sparser: it holds an empty list on
# purpose. There is no year_key, no FK to dim_year, no date column of any kind
# anywhere in fact_cm_elevate_application (cmelevate_schema_partitions.yaml
# semantic_rules.time_rule) — refresh_scheme_years() below does not even probe
# it. _needs_year_clarification and _year_out_of_range_clarification both treat
# an empty list here as "no time dimension exists" and refuse a time filter
# outright instead of offering year chips.
_SCHEME_DATA_YEARS: dict[str, list[str]] = {
    "MGNREGA": ["2022-23", "2023-24", "2024-25", "2025-26"],
    "PMAY-G":  ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24"],
    "Focus Plus": ["2022-23", "2025-26"],
    "CM Elevate": [],
    # Focus Legacy holds FOUR years with a HOLE IN THE MIDDLE: FY2023-24 has no
    # payments at all — an absent year, not a zero one (focuslegacy_schema_
    # partitions.yaml semantic_rules.time_gap_rule). It is deliberately NOT
    # listed, so the year chips never offer it and the out-of-range guard
    # correctly refuses a FY2023-24 question instead of returning an empty total.
    "Focus Legacy": ["2021-22", "2022-23", "2024-25", "2025-26"],
    # CM Elevate Legacy holds TWO years. 395 records (both Sericulture schemes)
    # carry no year at all — they are not a third year, so they get no chip; an
    # "all financial years" answer still includes them because it applies no
    # year filter (cmelevatelegacy_schema_partitions.yaml year_key rules).
    "CM Elevate Legacy": ["2024-25", "2025-26"],
}


def _fy_short(year_key: int) -> str:
    """2022 -> '2022-23'."""
    return f"{year_key}-{(year_key + 1) % 100:02d}"


def _fy_start(short: str) -> int:
    """'2022-23' -> 2022."""
    return int(str(short)[:4])


async def refresh_scheme_years() -> None:
    """Load each scheme's real DISTINCT financial years from megh_db so the year
    chips and the out-of-range guard track the live data. Best-effort — on any
    failure the verified defaults in _SCHEME_DATA_YEARS stay in place."""
    from app.db import run_readonly
    for scheme, sql in _SCHEME_YEAR_SQL.items():
        try:
            rows = await run_readonly(sql)
            yrs = sorted({int(r["year_key"]) for r in rows if r.get("year_key") is not None})
            if yrs:
                _SCHEME_DATA_YEARS[scheme] = [_fy_short(y) for y in yrs]
                logger.info("scheme years loaded: %s -> %s", scheme, _SCHEME_DATA_YEARS[scheme])
            else:
                logger.warning("scheme years: %s query returned no rows, keeping default %s",
                               scheme, _SCHEME_DATA_YEARS[scheme])
        except Exception as e:  # noqa: BLE001
            logger.warning("scheme years: %s query failed, keeping default %s (%s)",
                           scheme, _SCHEME_DATA_YEARS[scheme], e)


# ── "Which financial years does <scheme> have?" — from the data, never a list ─
# Reported 2026-10-06: "give me financial years in MGNREGA" was answered "42
# distinct financial years ... 1984-85 through 2023-24". The SQL model read
# SELECT financial_year_short FROM curated.dim_year: the shared CALENDAR every
# scheme's year_key points into, not years MGNREGA has data for (2022-23 to
# 2025-26). The answer is the scheme's own DISTINCT years (_SCHEME_DATA_YEARS,
# loaded from its views at startup by refresh_scheme_years), built here with
# no model call. _sql_dimension_only_issue is the backstop for any other
# phrasing that reaches the generator.
_C06_YEAR_W = W("year", "years")
_YEARS_LIST_QUESTION = Matcher(Alt(
    Seq(W("financial", "fiscal"), _C06_YEAR_W), "fys",
    Seq(W("which", "what"), Opt("financial"), _C06_YEAR_W),
    Seq("how", "many", Opt("financial"), _C06_YEAR_W),
    Seq(_C06_YEAR_W, Opt("of"), W("data", "available", "covered", "coverage")),
    Seq(_c04Joined("year", "wise"), W("list", "coverage")),
))
# Anything asking for a figure turns it into a per-year DATA question.
_YEARS_LIST_FIGURE = Matcher(Alt(
    W("total", "count", "sum", "average", "avg", "amount", "expenditure", "house", "houses", "payment",
      "payments", "application", "applications", "household", "households", "member", "members", "group",
      "groups", "person", "persons", "people", "women", "wage", "wages", "loan", "loans", "trend", "growth",
      "compare", "comparison", "highest", "lowest", "most", "least", "top"),
    W("disburs", "sanction", "releas", "beneficiar", "subsid", prefix=True),
    Seq("number", "of"), _c04Joined("job", ("card", "cards")), _c04Joined("person", ("day", "days")),
    Seq("by", W("district", "block", "village", "scheme")), Seq("per", W("district", "block", "village")),
    NotBefore(Seq("how", "many"), Seq(Opt("financial"), W("year", prefix=True))),
))


# "across all financial years" / "all financial years combined" is the year chip's
# SCOPE, not a request for the list: "Give me the overall PMAY performance of East
# Khasi Hills across all financial years" was answered with the seven FYs (PMAY-G
# sheet run 2026-10-10). Summary words ask for figures too.
_YEARS_SCOPE_PHRASE = Matcher(Alt(
    Seq(W("across", "for", "over", "in"), "all", Opt("the"), Opt(W("financial", "fiscal")), "years",
        Opt("combined")),
    Seq("all", Opt("the"), Opt(W("financial", "fiscal")), "years", "combined"),
))
_YEARS_LIST_SUMMARY = Matcher(Alt(
    W("performance", "summary", "overview", "breakdown", "status", "progress", "report", "figure",
      "figures", "position"),
    W("complet", "utilis", "utiliz", "percent", prefix=True),
))
# A 19xx / 20xx year written on its own ("2023", the "2023" of "2023-24").
_C06_YEAR_1920 = Matcher(Pred(lambda w: _c05_is_year(w, ("19", "20"))))


def _is_years_list_question(question: str) -> bool:
    q = _YEARS_SCOPE_PHRASE.sub(" ", question or "")
    if _YEARS_LIST_SUMMARY.search(q):
        return False
    return (bool(_YEARS_LIST_QUESTION.search(q)) and not _YEARS_LIST_FIGURE.search(q)
            and not _GAP_YEAR.search(q) and not _C06_YEAR_1920.search(q))


def _year_gaps(years: "list[str]") -> "list[str]":
    starts = sorted(_fy_start(y) for y in years)
    return [_fy_short(y) for a, b in zip(starts, starts[1:]) for y in range(a + 1, b)]


def _join_list(items: "list[str]") -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _scheme_years_answer(question: str, schemes: "list[str]") -> "dict | None":
    """The financial years each scheme actually holds data for, when the
    question asks for that list and no figure; else None."""
    if not schemes or not _is_years_list_question(question):
        return None
    lines: list[str] = []
    rows: list[dict] = []
    for s in schemes:
        years = list(_SCHEME_DATA_YEARS.get(s) or [])
        if not years:
            lines.append(f"{s} records no financial year at all — its data has no year or date "
                         "column, so its figures are totals across the whole period.")
            continue
        n = len(years)
        line = (f"{s} data covers {n} financial year{'s' if n != 1 else ''}: "
                f"{_join_list(['FY ' + y for y in years])}.")
        gaps = _year_gaps(years)
        if gaps:
            line += (f" There is no {s} data for {_join_list(['FY ' + y for y in gaps])} "
                     + ("(an absent year, not a zero one)." if len(gaps) == 1
                        else "(absent years, not zero ones)."))
        if s == "CM Elevate Legacy":
            line += " The two Sericulture schemes' records carry no financial year."
        lines.append(line)
        rows.extend({"scheme": s, "financial_year": y} for y in years)
    sql = ";\n".join(_SCHEME_YEAR_SQL[s] for s in schemes if s in _SCHEME_YEAR_SQL) or None
    context_budget.log_decision("deterministic", answer="scheme-years", schemes=schemes)
    return {"route": "data", "intent": "DATA", "confidence": "high", "schemes": list(schemes),
            "resolved_entities": {}, "sql": sql, "sql_query": sql,
            "row_count": len(rows), "rows": rows, "data": rows, "answer": "\n".join(lines)}


# Each scheme's own DISTINCT years (refresh_scheme_years, _scheme_years_answer).
_SCHEME_YEAR_SQL: "dict[str, str]" = {
    "MGNREGA": (
        "SELECT DISTINCT year_key FROM curated.v_employment WHERE year_key IS NOT NULL "
        "UNION "
        "SELECT DISTINCT year_key FROM curated.v_expenditure WHERE year_key IS NOT NULL"
    ),
    "PMAY-G": "SELECT DISTINCT year_key FROM curated.v_pmay WHERE year_key IS NOT NULL",
    "Focus Plus": (
        "SELECT DISTINCT year_key FROM curated.v_focus_plus WHERE year_key IS NOT NULL"
    ),
    "Focus Legacy": (
        "SELECT DISTINCT year_key FROM curated.v_focus_legacy WHERE year_key IS NOT NULL"
    ),
    "CM Elevate Legacy": (
        "SELECT DISTINCT year_key FROM curated.v_cm_elevate_disbursement "
        "WHERE year_key IS NOT NULL"
    ),
    # CM Elevate deliberately has no entry here — curated.v_cm_elevate has no
    # year_key column at all (not merely NULL), so there is nothing to probe.
    # Its default of [] in _SCHEME_DATA_YEARS above is the permanent value.
}

# The question already fixes its time scope — a specific year, an explicit
# "all years", or a request for a per-year series. Any of these => don't ask.
_C06_FIN_FISCAL = W("financial", "fiscal")
_C06_FIN_FISCAL_FY = W("financial", "fiscal", "fy")
_ALL_YEARS_CUE = Matcher(Alt(
    Seq("all", Opt("the"), Opt(_C06_FIN_FISCAL_FY), _C06_YEAR_W),
    Seq("allthe", Opt(_C06_FIN_FISCAL_FY), _C06_YEAR_W), W("allyear", "allyears"),
    Seq("every", Opt(_C06_FIN_FISCAL), "year"), Seq("each", "year"),
    Seq("across", Opt("all"), Opt("the"), Opt(_C06_FIN_FISCAL), _C06_YEAR_W),
    # "across all AVAILABLE financial years combined", "across all schemes AND
    # financial years", "all available records" (user session 2026-10-13: each
    # still asked "which financial year?")
    Seq("all", Opt("the"), "available", Opt(_C06_FIN_FISCAL), W("year", "years", "records", "data")),
    # "&" counts only glued to the word before it ("schemes& financial years"), as before
    Seq(Alt("and", _C04GapBefore(lambda g: g[:1] == "&" and g[1:] != "" and g[1:].strip() == "", first=False)),
        Opt("all"), Opt("the"), _C06_FIN_FISCAL, "years"),
    Seq("all", Opt("the"), "records"),
    _c04Joined("all", "time"), Seq("since", "inception"),
    Seq(Opt("up"), W("to", "till", "until"), W("date", "now")), Seq("so", "far"), "cumulative",
    Seq("all", "years", "combined"), "overall", Seq("in", "total"), Seq("grand", "total"),
))
# The YEAR is what is asked for — "which year was the highest?", "in which FY
# did it peak?". Asking "which financial year?" back answers nothing, and a year
# carried over from the previous turn would pin the answer to that one year
# (General TC-022, test run 2026-10-09: after "What was it in 2023-24?", "which
# year was the highest?" answered "FY 2023-24, 8.71 lakh" instead of 2024-25).
_C06_YEAR_FY_W = W("year", "years", "fy", "fys")
_WHICH_YEAR_MATCHER = Alt(
    Seq(W("which", "what"), Opt("financial"), _C06_YEAR_FY_W),
    Seq("in", "which", Opt("financial"), _C06_YEAR_FY_W),
    Seq(_C06_YEAR_FY_W, W("had", "has", "with", "saw", "recorded"), Opt("the"),
        Alt(W("highest", "lowest", "most", "least", "peak"), W("max", "min", prefix=True))),
)
_WHICH_YEAR_CUE = Matcher(_WHICH_YEAR_MATCHER)
_TIME_SERIES_CUE = Matcher(Alt(
    "trend", Seq("over", "time"), Seq("over", Opt("the"), W("last", "past"), ANY, _C06_YEAR_FY_W),
    Seq(_c04Joined("year", "on"), "year"), Seq("year", _c04Joined("on", "year")), "yearonyear",
    _c04Joined("year", "wise"), Seq("by", "year"), Seq("by", "financial", "year"), Seq("per", "year"),
    W("annually", "annual", "history", "historical", "growth"), Seq("change", "over"),
    Seq("each", Opt("financial"), "year"),
    _WHICH_YEAR_MATCHER,
))
# The question is actually about a metric or a per-dimension breakdown — the only
# shapes where "which year?" is a meaningful missing filter. A pure membership /
# rules question ("which villages have both schemes", "who is eligible") isn't.
_METRIC_OR_BREAKDOWN_CUE = Matcher(Alt(
    Seq("how", W("many", "much")), Seq(W("number", "count", "no", "sum"), "of"),
    W("total", "average", "avg", "mean", "expenditure", "spend", "spending", "spent", "wage", "wages",
      "house", "houses", "instalment", "installment", "instalments", "installments", "disbursement",
      "disbursements", "utilisation", "utilization"),
    _c04Joined("person", ("day", "days")), Seq("wage", "bill"), Seq("job", W("card", "cards")),
    Seq("muster", W("roll", "rolls")), Seq("dwelling", W("unit", "units")), Seq("sanctioned", "amount"),
    Seq("amount", "released"), Seq(W("completion", "success"), "rate"),
    # Focus Plus's own metric nouns — same gap as _DATA_HINTS (see 2026-09-11
    # fix note there): without these, a bare "<scheme> beneficiaries?" matched
    # neither this cue nor _MENTIONS_TRANCHE_WORD, so both the year AND
    # tranche clarification gates were skipped and an unscoped question
    # reached the SQL generator with no year/tranche pin at all — which then
    # sometimes guessed a specific tranche on its own instead of correctly
    # reasoning "no tranche named -> every tranche".
    W("beneficiar", prefix=True), W("payment", "payments"),
    W("compare", "comparison", "versus", "vs", "rank", "ranked", "ranking", "highest", "lowest", "most",
      "least"),
    Seq("top", _c04_digits(1, 1)),
    Seq("by", W("district", "block", "village", "panchayat")),
    _c04Joined(("district", "block", "village"), "wise"),
))


def _year_choices_for(schemes: list[str]) -> list[str]:
    """Every financial year the given scheme(s) hold, distinct, oldest first.
    Falls back to the full set when `schemes` is empty or unrecognised."""
    years, _live = _available_years_for(schemes)
    return years


def _needs_year_clarification(question: str, schemes: list[str], resolved: dict) -> bool:
    """True when the question is a metric / breakdown question whose geography is
    already settled (so the scope gate skipped it) but which pins no financial
    year — not in its text, not via a resolved `year_key` — and doesn't ask for a
    time series or an explicit all-years total. Callers must have run
    `resolve_entities` first so `resolved` reflects any year actually named."""
    if not settings.YEAR_CLARIFY_ENABLED:
        return False
    q = question or ""
    # Schemes with NO time dimension at all (CM Elevate has no year_key, no date
    # column of any kind) can never be asked "which year" — there is nothing to
    # choose. Skip the whole gate when every scheme in play is one of these, so
    # _year_clarification never runs on an empty _SCHEME_DATA_YEARS[scheme] list
    # (which would otherwise crash indexing years[-1]).
    live = [s for s in (schemes or []) if s in _SCHEME_DATA_YEARS]
    if live and all(not _SCHEME_DATA_YEARS[s] for s in live):
        return False
    # PMAY-G used to be exempted here (beneficiary counts / house status are
    # cumulative-to-date, so "which year?" felt like an unnecessary interruption
    # to an earlier QA pass) and silently defaulted to "all years to date"
    # instead of asking. Reinstated to ask same as MGNREGA, 2026-09-09, by
    # explicit product decision — a plain PMAY-G question with no year now
    # pauses for a FY choice too; say "all years" / "cumulative" explicitly
    # (see _ALL_YEARS_CUE) to get the old default without the prompt.
    if resolved.get("year_key") or _parse_year_key(q) is not None:
        return False
    if _ALL_YEARS_CUE.search(q) or _TIME_SERIES_CUE.search(q):
        return False
    # A cross-scheme "which / how many districts are in both schemes" question is
    # a membership/overlap set question — inherently across the whole data window,
    # so there is no single financial year to ask for.
    if _CROSS_SCHEME_SET_QUESTION.search(q):
        return False
    # MGNREGA: a percentage / share / women question is a metric question too.
    # Without this, "what percentage of employment persons were women in ekh?"
    # skipped the FY pause and the SQL model silently picked the latest year
    # (FY 2025-26, whose women column is unrecorded) — user report 2026-09-27.
    if not _METRIC_OR_BREAKDOWN_CUE.search(q) and not (
            "MGNREGA" in (schemes or []) and (_RATIO_CUE.search(q) or _WOMEN_CUE.search(q))):
        return False
    return True


def _year_clarification(question: str, schemes: list[str]) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    years, live = _available_years_for(schemes)
    options = [
        {"label": f"FY {y}", "question": f"{stem} for FY {y}"}
        for y in years
    ]
    options.append({
        "label": "All financial years combined",
        "question": f"{stem} across all financial years",
    })
    if len(live) == 1:
        scope_word = live[0]
    elif len(live) == 2:
        scope_word = " and ".join(live)
    else:
        scope_word = ", ".join(live[:-1]) + " and " + live[-1]
    year_list = ", ".join(f"FY {y}" for y in years[:-1]) + f" and FY {years[-1]}"
    return ClarificationNeeded(
        f"{scope_word} data is available for {year_list}. "
        "Which of these is required — a single financial year, or all of them "
        "combined?",
        options=options,
        rule="year-not-specified",
    )


# ── "Which tranche?" clarification (Focus Plus only) ───────────────────────
# Focus Plus's amount_disbursed differs sharply by tranche_label (5,000 for
# Tranch 1, 2,500 for every later tranche — see schema_context.py rule 7), so
# silently summing every tranche together produces a total that reads as a
# single entitlement when it's actually a mix ratio. Mirrors
# _needs_year_clarification / _year_clarification in shape: ask with one-tap
# chips (Tranch 1..4 plus "all combined") rather than guess, unless the
# question already names a tranche, asks for a per-tranche breakdown, or
# explicitly wants every tranche combined.
_TRANCHE_BREAKDOWN_CUE = Matcher(Alt(
    Seq(W("by", "per", "each"), "tranche"), _c04Joined("tranche", "wise"),
    Seq("across", Opt("all"), Opt("the"), "tranches"), Seq("tranche", "breakdown"),
    Seq("split", "by", "tranche"), Seq(Alt("breakdown", Seq("break", "down"), "break"), "by", "tranche"),
    # "which tranche has the most X" / "what tranche..." asks the data to
    # identify one BY comparing across all of them — the opposite of a
    # question that's missing a tranche pin, so it must not be asked to pick.
    Seq(W("which", "what"), "tranche"),
))
_ALL_TRANCHES_CUE = Matcher(Alt(
    _c04Joined("all", ("tranche", "tranches")), Seq(W("tranche", "tranches"), "combined"),
    Seq("combined", W("tranche", "tranches")), "cumulative", "overall", Seq("in", "total"),
    Seq("grand", "total"), _c04Joined("all", "time"),
))
# The literal word "tranche"/"tranch" appearing anywhere with no specific
# tranche resolved (resolve_tranche_label found nothing) is itself the
# clearest possible signal that the question is tranche-scoped but doesn't
# say which one — regardless of whether the wording also happens to match
# _METRIC_OR_BREAKDOWN_CUE. That cue was borrowed from the year gate and is
# tuned for money/count metrics ("how much", "disbursements"); it has no
# "status" or "breakdown" vocabulary, so "give me status breakdown for
# tranche?" matched neither cue and silently fell through to the SQL
# generator, which picked one tranche (Tranch 4) on its own with nothing
# to base that choice on.
_MENTIONS_TRANCHE_WORD = Matcher(W("tranch", "tranche", "tranchs", "tranches"))

# focus_status / verification_status / gender / occupation are populated ONLY
# on the '12.5K' cohort, which per FOCUS PLUS RULES rule 8 exists ONLY at
# Tranch 4 (schema_context.py _FOCUSPLUS_RULES #4, #8). A question about one of
# these columns has no real "which tranche?" to ask — every other tranche has
# zero such rows, so "all tranches combined" and "Tranch 4" are the same
# answer. Pausing to ask anyway produces a rewritten question ("... across all
# tranches") that then fights the Tranch-4-only constraint during SQL
# generation and burns the repair budget for nothing — skip the gate instead
# and let it hit the existing focus_status few-shots directly (see
# "How many Focus Plus registrations are still pending?" in
# data/focus_plus/focusplus_few_shot.yaml).
_PERSON_LEVEL_COLUMN_CUE = Matcher(Alt(
    # Bare "status" is included, not just the "focus status" / "verification
    # status" compounds — schema_context.py rule 13 makes an unqualified
    # "status"/"status breakdown"/"status-wise" mean focus_status by default,
    # which is exactly as cohort-locked as the compound forms. Missing this
    # let "give me the status breakdown for tranche 1" slip past both this
    # gate and _person_level_tranche_conflict straight into a guaranteed-empty
    # query (confirmed live 2026-09-12).
    W("status", "verified", "verification", "gender", "female", "male", "women", "men", "occupation",
      "farmer", "farmers", "pending", "approved", "rejected", "registration", "registrations"),
    _c04Joined(("focus", "verification"), "status"),
))

# A tranche label is "Tranch 4 - Feb-March" — the ONLY tranche the 12.5K
# person-level cohort belongs to (schema_context.py rule 4/8). Matches the
# canonical value's leading "Tranch 4" regardless of the month suffix.
def _c06_is_tranch4_label(label: str) -> bool:
    """The label starts with "Tranch 4" / "Tranch4" (any case), then a non-word
    character or nothing."""
    low = (label or "").lower()
    if not low.startswith("tranch"):
        return False
    rest = low[len("tranch"):].lstrip()
    return rest[:1] == "4" and (len(rest) == 1 or not _c04_is_word_char(rest[1]))


def _person_level_tranche_conflict(question: str, schemes: list[str], resolved: dict) -> bool:
    """True when the question asks for a person-level column (status/gender/
    occupation/verification — the 12.5K-cohort-only fields, rule 4) AND names
    one or more SPECIFIC tranches, NONE of which is Tranch 4. That combination
    can never have any matching rows — the 12.5K cohort IS Tranch 4, so a
    filter for Tranch 1/2/3 plus any of these columns is a structural
    contradiction, not an ordinary "no rows matched" outcome. Left to run as
    plain SQL this produces the confusing generic "couldn't find any matching
    records" fallback (`_no_data_answer`) with no explanation of WHY — catching
    it here lets the DATA stages explain the real reason instead, and skips a
    wasted SQL round trip. Scoped to single-scheme Focus Plus only, mirroring
    `_needs_tranche_clarification`."""
    if (schemes or []) != ["Focus Plus"]:
        return False
    if not _PERSON_LEVEL_COLUMN_CUE.search(question or ""):
        return False
    tranche_label = resolved.get("tranche_label")
    if not tranche_label:
        return False
    labels = tranche_label if isinstance(tranche_label, list) else [tranche_label]
    return not any(_c06_is_tranch4_label(str(lbl)) for lbl in labels)


def _person_level_tranche_conflict_answer(question: str, schemes: list[str],
                                          entity_result: dict) -> dict:
    """Deterministic explanation for `_person_level_tranche_conflict` — no SQL
    is run because the answer (zero rows, always) is already known from the
    schema, not from the data."""
    display = entity_result.get("display", {}).get("tranche_label") or "that tranche"
    resolved = entity_result["resolved"]
    answer = (
        f"{display} has no status, gender, occupation or verification data. "
        "Those fields are recorded only for the 12.5K registration cohort, and "
        "that cohort falls entirely under Tranch 4 — ask for Tranch 4, or drop "
        "the tranche filter, to see that breakdown."
    )
    return {
        "route": "data",
        "intent": "DATA",
        "confidence": "high",
        "schemes": schemes,
        "resolved_entities": resolved,
        "sql": "",
        "sql_query": "",
        "row_count": 0,
        "rows": [],
        "data": [],
        "answer": answer,
    }


# ── "Which scheme has the highest spend?" — the scheme IS the answer ────────
# A superlative asked ACROSS schemes ("which scheme paid out the most?", "the
# scheme with the highest money spent") is answered by ranking the schemes
# against each other. Asking "which scheme does your question concern?" first
# is backwards — the scheme is the thing being asked for, not a filter the
# user forgot (reported 2026-09-17: "what about the scheme with highest money
# paid?" raised the four-way scheme pause instead of answering).
#
# _EXPLICIT_BOTH already recognises the phrasings that ask for every scheme
# ("both schemes", "by scheme", "scheme-wise"), but not this superlative
# shape, where the cross-scheme intent is carried by "which/what scheme" plus
# a ranking word rather than by an "all/each" quantifier.
_C06_SUP_SHORT = W("highest", "lowest", "most", "least", "maximum", "minimum", "greatest", "biggest",
                   "largest", "smallest", "top")
_CROSS_SCHEME_SUPERLATIVE = Matcher(Alt(
    Seq(W("which", "what"), "scheme", _C04CharGap(60, "?.!"),
        W("highest", "lowest", "most", "least", "maximum", "minimum", "greatest", "biggest", "largest",
          "smallest", "top", "best", "worst", "more", "less")),
    Seq(_C06_SUP_SHORT, _C04CharGap(40, "?.!"), "scheme"),
    Seq("scheme", "with", Opt("the"), _C06_SUP_SHORT),
    Seq(W("rank", "compare"), Opt("the"), "schemes"),
))
# The superlative has to be about MONEY for the ranking below to apply — a
# "which scheme has the most applications" question is a different figure and
# is left to normal SQL generation.
_MONEY_SUPERLATIVE = Matcher(Alt(
    W("money", "amount", "spent", "expenditure", "paid", "fund", "funds", "crore", "lakh", "cost", "budget",
      "outlay"),
    W("spend", "payment", "disburs", "releas", prefix=True),
))


def _wants_cross_scheme_money_ranking(question: str) -> bool:
    """True when the question asks which scheme spent/paid the most — a
    comparison ACROSS schemes whose answer names a scheme."""
    q = question or ""
    return bool(_CROSS_SCHEME_SUPERLATIVE.search(q) and _MONEY_SUPERLATIVE.search(q))


# One query, every scheme that records money, each normalised to CRORE.
# curated.v_cross_scheme_money_district_year is the sanctioned MGNREGA-vs-PMAY
# comparison object (docs/DATA_MODEL.md); Focus Plus keeps its money on its own
# view in RUPEES (/1e7 -> crore). CM Elevate is deliberately absent — it has no
# money column of any kind (v_cm_elevate carries applications only), so it is
# reported as "not held" rather than as a misleading zero.
_CROSS_SCHEME_MONEY_SQL = """
SELECT scheme_code AS scheme,
       ROUND(SUM(amount_crore), 2) AS amount_crore,
       MIN(measure_semantics) AS measure_semantics
FROM curated.v_cross_scheme_money_district_year
GROUP BY scheme_code
UNION ALL
SELECT 'Focus Plus' AS scheme,
       ROUND(SUM(amount_disbursed) / 1e7, 2) AS amount_crore,
       'amount disbursed to farmers (DBT), rupees' AS measure_semantics
FROM curated.v_focus_plus
UNION ALL
SELECT 'Focus Legacy' AS scheme,
       ROUND(SUM(amount_disbursed) / 1e7, 2) AS amount_crore,
       'amount remitted to producer groups, rupees' AS measure_semantics
FROM curated.v_focus_legacy
UNION ALL
SELECT 'CM Elevate Legacy' AS scheme,
       ROUND(SUM(total_disbursement) / 1e7, 2) AS amount_crore,
       'subsidy and loan disbursed to sanctioned applicants, rupees' AS measure_semantics
FROM curated.v_cm_elevate_disbursement
ORDER BY amount_crore DESC
""".strip()

_SCHEME_DISPLAY_NAME = {"MGNREGA": "MGNREGA", "PMAY": "PMAY-G", "PMAY-G": "PMAY-G",
                        "Focus Plus": "Focus Plus", "CM Elevate": "CM Elevate",
                        "Focus Legacy": "Focus Legacy",
                        "CM Elevate Legacy": "CM Elevate Legacy"}
# Plain-English rendering of each scheme's measure_semantics. The stored strings
# are written for the SQL prompt ("annual FLOW (lakh rupees)", "an EVENT, not a
# clean annual flow") and read as database jargon in a chat bubble; the caveat
# they carry is preserved in the closing paragraph either way.
_MEASURE_PLAIN = {
    "MGNREGA": "expenditure actually incurred",
    "PMAY-G": "money released against sanctions",
    "Focus Plus": "cash disbursed to farmers (DBT)",
    "Focus Legacy": "cash remitted to producer groups",
    "CM Elevate Legacy": "subsidy and loans disbursed to sanctioned applicants",
}


async def _cross_scheme_money_answer(question: str) -> dict:
    """Rank the schemes by money, deterministically. Built from the rows rather
    than composed by the LLM, for the same reason as the Focus Plus overall
    summary above: several figures of DIFFERENT kinds in one answer is exactly
    where a composer misattributes numbers, and the measure_semantics caveat
    must survive verbatim — docs/DATA_MODEL.md requires carrying it into any
    cross-scheme money comparison, because MGNREGA's figure is expenditure
    incurred while PMAY-G's is money released against sanctions."""
    rows = await run_readonly(_CROSS_SCHEME_MONEY_SQL)
    ranked = [r for r in rows if r.get("amount_crore") is not None]
    if not ranked:
        return {"route": "data", "intent": "DATA", "confidence": "low",
                "answer": "I couldn't read the scheme spending figures just now.",
                **_empty_data_fields()}
    top = ranked[0]
    top_name = _SCHEME_DISPLAY_NAME.get(str(top["scheme"]), str(top["scheme"]))
    lines = [
        f"{top_name} has the highest amount at ₹{float(top['amount_crore']):,.2f} crore. "
        "Across every scheme that records money:"
    ]
    for r in ranked:
        name = _SCHEME_DISPLAY_NAME.get(str(r["scheme"]), str(r["scheme"]))
        lines.append(f"- **{name}** — ₹{float(r['amount_crore']):,.2f} crore "
                     f"({_MEASURE_PLAIN.get(name, r['measure_semantics'])})")
    lines.append(
        "\nThese are not the same kind of figure, so treat the ranking as indicative "
        "rather than like-for-like: MGNREGA's is expenditure actually incurred, PMAY-G's "
        "is money released against sanctions, Focus Plus's is cash disbursed to "
        "individual farmers, and Focus Legacy's is cash remitted to producer groups "
        "(where every payment is Rs 5,000 per member, so the figure is really a "
        "membership count), and CM Elevate Legacy's is subsidy and loans together paid "
        "to sanctioned applicants. The CM Elevate applications data records no payment "
        "of any kind, so it cannot appear in a money comparison at all."
    )
    return {
        "route": "data", "intent": "DATA", "confidence": "high",
        "schemes": [_SCHEME_DISPLAY_NAME.get(str(r["scheme"]), str(r["scheme"])) for r in ranked],
        "resolved_entities": {},
        "sql": _CROSS_SCHEME_MONEY_SQL, "sql_query": _CROSS_SCHEME_MONEY_SQL,
        "row_count": len(ranked), "rows": ranked, "data": ranked,
        "answer": "\n".join(lines),
    }


def _money(v) -> str:
    return f"₹{float(v):,.2f}"


def _needs_tranche_clarification(question: str, schemes: list[str], resolved: dict,
                                  *, already_all_combined: bool = False) -> bool:
    """True when Focus Plus is the ONLY scheme in play, the question is a
    metric / breakdown question, and it pins no tranche — not in its text
    (resolve_tranche_label found nothing during resolve_entities) and not via
    a resolved entity — and doesn't ask for a per-tranche breakdown or an
    explicit "all tranches combined". Callers must have run resolve_entities
    first so `resolved` reflects any tranche actually named. Scoped to
    single-scheme Focus Plus questions only, not "Focus Plus" in schemes —
    a cross-scheme comparison (schemes has more than one entry) wants one
    row per scheme, not Focus Plus fragmented into its four tranches on top,
    and that flow already has its own tuned behaviour this must not disturb.

    `already_all_combined` (optional): True when this session already
    answered a Focus Plus question with "all tranches combined" earlier in
    the conversation (see context_manager's ConversationState.tranche_all_combined
    / session_store) and the current turn is a short follow-up that never
    re-says "tranche" at all — e.g. "give me top 3 only" right after "...
    across all tranches". Without this, that kind of bare follow-up has no
    tranche cue of its own, re-trips this gate, and either re-asks a question
    the user just answered or (worse) falls through to the SQL generator with
    no tranche signal and no memory of the choice already made."""
    if not settings.TRANCHE_CLARIFY_ENABLED:
        return False
    if (schemes or []) != ["Focus Plus"]:
        return False
    q = question or ""
    if resolved.get("tranche_label"):
        return False
    if already_all_combined:
        return False
    if _TRANCHE_BREAKDOWN_CUE.search(q) or _ALL_TRANCHES_CUE.search(q):
        return False
    # A question about a person-level / cohort-locked column is always
    # confined to the 12.5K cohort at Tranch 4 regardless of what the user
    # says about tranche — asking "which tranche?" has no real answer to
    # collect, so skip straight past the gate.
    if _PERSON_LEVEL_COLUMN_CUE.search(q):
        return False
    # Trigger ONLY when the question literally says "tranche"/"tranch" without
    # pinning which one. `_METRIC_OR_BREAKDOWN_CUE` used to also trigger this
    # gate (mirroring the year gate), but that cue matches "beneficiar*" and
    # "payments?" — i.e. almost every Focus Plus money/count question, not
    # just tranche-sensitive ones. None of the Focus Plus few-shot SQL (totals,
    # geography, gender, batch, status, FY breakdowns) scopes by tranche_label
    # at all — SUM(amount_disbursed) is well-defined across tranches, and the
    # one genuine mix-ratio trap (a naive per-beneficiary AVERAGE) is handled
    # by scoping to batch_label, not by asking the user to pick a tranche (see
    # "What is the average Focus Plus payment per member?" in
    # focusplus_few_shot.yaml). Confirmed live 2026-09-12: this over-broad
    # trigger paused nearly every Focus Plus beneficiary/disbursement question
    # for an unwanted tranche pick, and a scope-pause reply that re-entered
    # here with tranche_label already resolved but not yet threaded through
    # the merged question text sent the SQL generator into a repair loop that
    # burned the retry budget and crashed out to the KB fallback.
    if not _MENTIONS_TRANCHE_WORD.search(q):
        return False
    return True


def _tranche_clarification(question: str) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    labels = tranche_labels("Focus Plus")
    options = [
        {"label": lbl, "question": f"{stem} for {lbl}"}
        for lbl in labels
    ]
    options.append({
        "label": "All tranches combined",
        "question": f"{stem} across all tranches",
    })
    label_list = ", ".join(labels[:-1]) + f" and {labels[-1]}" if len(labels) > 1 else labels[0]
    return ClarificationNeeded(
        f"Focus Plus data is split into {label_list}. Which of these is required "
        "— a single tranche, or all of them combined?",
        options=options,
        rule="tranche-not-specified",
    )


# ── "That year isn't in the data" guard ────────────────────────────────────
# Year coverage per scheme lives in _SCHEME_DATA_YEARS (loaded from megh_db at
# startup by refresh_scheme_years()). This guard is PER SCHEME: a year MGNREGA
# lacks (say FY 2019-20) but PMAY-G has is fine for a PMAY-G question and only
# blocked for an MGNREGA one.
#
# A question that names a financial year no scheme in play holds ("1999-20",
# "2010", "FY 2027-28", or "2019-20" for MGNREGA) can't be answered. Without the
# guard the year is dropped as a note and the flow either falls into the generic
# "which year?" pause (looks like we ignored what the user typed) or answers
# across the years that DO exist (a figure for the wrong period). Instead: tell
# the user which years that scheme has, with those years as one-tap chips.

# A raw mention that is clearly meant as a year/financial-year even though it
# didn't resolve — a 4-digit 19xx/20xx/21xx, or an "NN-NN" / "NNNN-NN" range.
_C06_DASH_SLASH = lambda g: g.strip() in ("-", "/")  # noqa: E731
_YEAR_SHAPED_MATCH = Matcher(Alt(
    Pred(_c05_is_year),
    _C04SepSeq(_c04_digits(2, 2), _c04_digits(2, 2), ok=_C06_DASH_SLASH),
    _C04SepSeq(_c04_digits(4, 4), _c04_digits(2, 4), ok=_C06_DASH_SLASH),
))


def _looks_like_year_mention(text: str) -> bool:
    return bool(_YEAR_SHAPED_MATCH.search(text or ""))


def _allowed_year_starts(schemes: "list[str] | None") -> set:
    """FY start years the given scheme(s) actually hold (union). Empty schemes =>
    every scheme's years."""
    years, _live = _available_years_for(schemes or [])
    return {_fy_start(y) for y in years}


def _year_in_data_range(year_key: int, schemes: "list[str] | None" = None) -> bool:
    return year_key in _allowed_year_starts(schemes)


# A token that is unambiguously a financial year: an "NNNN-NN" / "NNNN-NNNN"
# range (any century), a 19xx or 21xx four-digit year, or a 20xx year in the
# 2010-2039 plausible band. A bare "2000" / "2500" is deliberately NOT matched
# so "top 2000 villages" isn't mistaken for a year. An optional "FY" /
# "financial year" / "fiscal (year)" lead-in may be glued on ("FY2023-24").
def _c06_is_digit(ch: str) -> bool:
    return ch.isascii() and ch.isdigit()


def _c06_word_starts_at(text: str, pos: int) -> bool:
    return pos == 0 or not _c04_is_word_char(text[pos - 1])


def _c06_glued_fy_prefix(text: str, i: int) -> bool:
    """`text[:i]` ends with "fy" / "fiscal" / "financial year" / "fiscal year"
    starting at a word boundary (the lead-in written with no space before the year)."""
    low = text[:i].lower()
    for w in ("fy", "fiscal"):
        if low.endswith(w):
            return _c06_word_starts_at(text, i - len(w))
    if low.endswith("year"):
        before = low[:i - 4]
        stripped = before.rstrip()
        if len(stripped) < len(before):
            for w in ("financial", "fiscal"):
                if stripped.endswith(w):
                    return _c06_word_starts_at(text, len(stripped) - len(w))
    return False


def _c06_year_token_end(t: str, i: int) -> "int | None":
    """End of the year token starting at t[i], or None."""
    n = len(t)
    four = t[i:i + 4]
    if len(four) != 4 or not all(_c06_is_digit(c) for c in four):
        return None
    j = i + 4
    if four[:2] in ("19", "20", "21"):                      # NNNN - NN(NN)
        while j < n and t[j].isspace():
            j += 1
        if j < n and t[j] in "-/":
            j += 1
            while j < n and t[j].isspace():
                j += 1
            k = j
            while k < n and _c06_is_digit(t[k]):
                k += 1
            if 2 <= k - j <= 4 and (k == n or not _c04_is_word_char(t[k])):
                return k
    after = i + 4
    if after < n and _c04_is_word_char(t[after]):
        return None
    if four[:2] in ("19", "21") or (four[:2] == "20" and four[2] in "123"):
        return after
    return None


def _c06_year_range_tokens(text: str) -> "list[tuple[int, str]]":
    """(start, raw token) for every financial-year token in `text`, left to right."""
    t = text or ""
    out: list[tuple[int, str]] = []
    i, n = 0, len(t)
    while i < n:
        if _c06_is_digit(t[i]) and (_c06_word_starts_at(t, i) or _c06_glued_fy_prefix(t, i)):
            e = _c06_year_token_end(t, i)
            if e is not None:
                out.append((i, t[i:e]))
                i = e
                continue
        i += 1
    return out


def _c06_malformed_year_tail(text: str) -> "str | None":
    """The digit run (4-8 digits) that ends the question right after an explicit
    temporal cue — "in 20217", "for: 2023?", "FY2023" — else None. "of" is
    deliberately not a cue: it also ends amount phrasing ("expenditure of 150000")."""
    s = (text or "").rstrip().rstrip("?.!").rstrip()
    k = j = len(s)
    while j > 0 and _c06_is_digit(s[j - 1]):
        j -= 1
    if not 4 <= k - j <= 8:
        return None
    b = s[:j].rstrip()
    if b[-1:] in (":", "-"):
        b = b[:-1].rstrip()
    low = b.lower()
    for cue in ("in", "for", "during", "fy", "fiscal"):
        if low.endswith(cue) and _c06_word_starts_at(b, len(b) - len(cue)):
            return s[j:k]
    if low.endswith("year"):
        before = low[:-4]
        stripped = before.rstrip()
        if len(stripped) < len(before):
            for w in ("financial", "fiscal"):
                if stripped.endswith(w) and _c06_word_starts_at(b, len(stripped) - len(w)):
                    return s[j:k]
    return None


_MONTH_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_YEAR_IN_Q = Matcher(_C04SepSeq(_MONTH_NAME, Pred(lambda w: _c05_is_year(w, ("19", "20"))),
                                      ok=_c05_gap(True, True)))


def _calendar_month_fy_key(text: str, start: int, tok: str) -> "int | None":
    """FY start year for a bare year written right after a calendar month ("between
    January and March 2026" -> 2025, "June 2025" -> 2025), else None. Jan-Mar belong to
    the FY that started the April before: "2026" alone read as FY 2026-27 and the Focus
    Legacy question was told no data is held (Focus Legacy sheet TC-20, 2026-10-12).
    `start` is where the year token `tok` begins in `text`."""
    if not _c05_is_year(tok or "", ("19", "20")):
        return None
    before = (text or "")[:start].rstrip()
    if before.endswith(","):
        before = before[:-1]
    if before.endswith("."):
        before = before[:-1]
    low = before.lower()
    form = next((f for f in sorted(_MONTH_FORMS, key=len, reverse=True) if low.endswith(f)), None)
    if form is None:
        return None
    month = _MONTH_ABBR.index(form[:3]) + 1
    return int(tok) if month >= 4 else int(tok) - 1


def _years_in_question(text: str, schemes: "list[str] | None" = None
                       ) -> "tuple[list[str], list[str]]":
    """(available, unavailable) raw year tokens named in `text`.

    _out_of_range_year_in below returns only the FIRST unavailable token, which
    is the right answer for "is there a bad year here?" but the wrong basis for
    "should the whole question be refused?" — a question can name a year the
    scheme lacks AND a year it holds ("compare FY 2023-24 and FY 2024-25", the
    Focus Legacy gap case). Refusing that discards a question the data can
    largely answer."""
    ok: list[str] = []
    bad: list[str] = []
    for start, tok in _c06_year_range_tokens(text or ""):
        yk = _calendar_month_fy_key(text, start, tok) or _parse_year_key(tok)
        if yk is not None:
            (ok if _year_in_data_range(yk, schemes) else bad).append(tok)
        elif _YEAR_SHAPED_MATCH.search(tok):
            bad.append(tok)
    return ok, bad


# A question that asks for a COMPARISON needs two operands. Dropping one of
# them answers a different, narrower question than the one asked.
_COMPARES_YEARS = Matcher(Alt(
    W("compare", "comparison", "versus", "vs", "against"), Seq("difference", "between"),
    Seq("between", _C04CharGap(40, "\n"), "and"), Seq(W("higher", "lower"), "than"),
    Seq("more", "than", _C04CharGap(20, "\n"), "fy"),
))


def _nearest_available_year(bad_token: str, schemes: "list[str] | None") -> "str | None":
    """The year with data closest to `bad_token`, preferring the one BEFORE it.

    The scheme's own contract calls for exactly this on a gap comparison —
    focuslegacy_few_shot.yaml: "The preceding year WITH PAYMENTS is FY2022-23,
    not FY2023-24", and response_template's fy_gap_comparison_note. Preferring
    the earlier year keeps "compare X with the year before it" meaning what it
    says; a later year is used only when nothing earlier exists."""
    target = _parse_year_key(bad_token)
    if target is None:
        return None
    available, _live = _available_years_for(schemes or [])
    keys = sorted(k for k in (_parse_year_key(y) for y in available) if k is not None)
    if not keys:
        return None
    earlier = [k for k in keys if k < target]
    if earlier:
        return _fy_short(earlier[-1])
    later = [k for k in keys if k > target]
    return _fy_short(later[0]) if later else None


def _c06_find_year_tok(text: str, tok: str) -> int:
    """Index of the first case-insensitive `tok` in `text` that is not followed
    by a word character, else -1."""
    low, nt, n = text.lower(), tok.lower(), len(tok)
    k = low.find(nt) if nt else -1
    while k >= 0:
        if k + n == len(text) or not _c04_is_word_char(text[k + n]):
            return k
        k = low.find(nt, k + 1)
    return -1


def _c06_back_over_ws(text: str, k: int) -> int:
    while k > 0 and text[k - 1].isspace():
        k -= 1
    return k


def _c06_back_over_fy(text: str, k: int) -> int:
    """Start of an "FY" / "FY " lead-in right before position k, else k."""
    j = _c06_back_over_ws(text, k)
    return j - 2 if j >= 2 and text[j - 2:j].lower() == "fy" else k


def _c06_back_over_prep(text: str, k: int, preps: tuple) -> int:
    """Start of a "for " / "in " / ... lead-in (whitespace required) before k, else k."""
    j = _c06_back_over_ws(text, k)
    if j == k:
        return k
    low = text[:j].lower()
    for p in preps:
        if low.endswith(p):
            return j - len(p)
    return k


def _c06_squeeze_ws(s: str) -> str:
    """Runs of two or more whitespace characters -> one space."""
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i].isspace():
            j = i
            while j < n and s[j].isspace():
                j += 1
            out.append(" " if j - i >= 2 else s[i])
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


_C06_CLOSERS = "\"\u201d.?"


def _c06_drop_dangling(out: str) -> str:
    """Drop a "between " / "from " and a " and" / " ," left with nothing after them
    but closing punctuation or the end of the text."""
    n = len(out)
    cuts = []
    for t in _c06_tokens(out):
        if t.low in ("between", "from"):
            e = t.end
            while e < n and out[e].isspace():
                e += 1
            if e > t.end and (e == n or out[e] in _C06_CLOSERS):
                cuts.append((t.start, e))
    out = "".join(out[a:b] for a, b in zip([0] + [e for _, e in cuts], [s for s, _ in cuts] + [n]))
    n = len(out)
    cuts, i = [], 0
    while i < n:
        if not out[i].isspace():
            i += 1
            continue
        j = i
        while j < n and out[j].isspace():
            j += 1
        k = j + 3 if out[j:j + 3].lower() == "and" else (j + 1 if out[j:j + 1] == "," else None)
        if k is not None:
            m = k
            while m < n and out[m].isspace():
                m += 1
            if m == n or out[m] in _C06_CLOSERS:
                cuts.append((i, m))
                i = m
                continue
        i = j
    return "".join(out[a:b] for a, b in zip([0] + [e for _, e in cuts], [s for s, _ in cuts] + [n]))


def _substitute_year_token(question: str, old_tok: str, new_short: str) -> str:
    """Replace one year token in place, keeping the surrounding wording (and any
    "FY " prefix) so the sentence still reads as the comparison it is."""
    tok = old_tok.strip()
    k = _c06_find_year_tok(question, tok)
    if k < 0:
        return question
    start = _c06_back_over_fy(question, k)
    return question[:start] + f"FY {new_short}" + question[k + len(tok):]


def _apply_year_gap(question: str, schemes: "list[str] | None"
                    ) -> "tuple[str, str | None, bool]":
    """Decide what to do with a question naming a financial year the scheme has
    no data for. Returns (question, note, handled).

    `handled` is False only when NOTHING in the question is answerable — the
    caller then raises the out-of-range clarification. Otherwise the question is
    rewritten and a note explains what changed, so the answer states the gap
    rather than silently ignoring it.

    Two rewrites, and which one applies is the whole point:

    * COMPARISON ("compare FY 2023-24 and FY 2024-25", "X vs Y") — a comparison
      needs two operands, so the absent year is SUBSTITUTED with the nearest
      year that holds data. Deleting it left one year and answered with a single
      figure, leaving the verb the user typed unmet (reported 2026-09-23). The
      substitute is the preceding year with payments, which is exactly what the
      scheme's own exemplar and fy_gap_comparison_note prescribe.
    * ANYTHING ELSE — the absent year is dropped. There is no second operand to
      preserve, and substituting would answer about a year the user never named.

    Lives here rather than inline in resolve_entities so the tests exercise the
    real decision: an earlier version of this logic was inline, the regression
    test re-implemented it, and the test stayed green when the production branch
    was disabled."""
    ok_years, bad_years = _years_in_question(question, schemes)
    if not ok_years:
        return question, None, False

    swapped: list[tuple[str, str]] = []
    if _COMPARES_YEARS.search(question) and len(ok_years) + len(bad_years) >= 2:
        for bad in list(bad_years):
            near = _nearest_available_year(bad, schemes)
            if near and near not in ok_years:
                question = _substitute_year_token(question, bad, near)
                ok_years.append(near)
                bad_years.remove(bad)
                swapped.append((bad, near))
    if bad_years:
        question = _strip_year_tokens(question, bad_years)

    parts: list[str] = []
    if swapped:
        parts.append(
            "; ".join(
                f"FY {b} holds no data for this scheme, so FY {n} — the nearest "
                f"financial year that does — is compared instead"
                for b, n in swapped
            )
            + ". That is a gap in the records, not a zero."
        )
    if bad_years:
        parts.append(
            ", ".join(f"FY {y}" for y in bad_years)
            + " holds no data for this scheme, so it is left out — "
            "that is a gap in the records, not a zero."
        )
    logger.info("year gap: swapped=%s dropped=%s, answering for %s",
                swapped, bad_years, ok_years)
    return question, (" ".join(parts) or None), True


def _strip_year_tokens(question: str, tokens: "list[str]") -> str:
    """Remove the given year tokens (and any "for "/"in "/"FY " lead-in, or a
    dangling "and"/",") from the question, so what remains reads naturally and
    cannot re-trip the year guard on a later turn."""
    out = question
    for tok in tokens:
        # Take any connector that FOLLOWS the token too ("between FY 2023-24
        # and ..." -> "between ..."), otherwise dropping the first of a pair
        # leaves a dangling "and": "Compare the total remittance and FY
        # 2024-25." Both sides are optional, so a lone year is still removed.
        tok = tok.strip()
        k = _c06_find_year_tok(out, tok)
        if k < 0:
            continue
        start = _c06_back_over_prep(out, _c06_back_over_fy(out, k), ("for", "in", "during", "of", "between"))
        j = _c06_back_over_ws(out, start)
        if j > 0 and out[j - 1] == ",":
            j -= 1
        elif out[:j].lower().endswith("and") and _c06_word_starts_at(out, j - 3) \
                and (j == len(out) or not _c04_is_word_char(out[j])):
            j -= 3
        start = _c06_back_over_ws(out, j)
        e = k + len(tok)
        while e < len(out) and out[e].isspace():
            e += 1
        if out[e:e + 1] == ",":
            e += 1
        elif out[e:e + 3].lower() == "and" and not _c04_is_word_char(out[e - 1]) \
                and (e + 3 == len(out) or not _c04_is_word_char(out[e + 3])):
            e += 3
        out = out[:start] + " " + out[e:]
    out = _c06_squeeze_ws(out)
    # "between" / "from" left with nothing to join, and a trailing connector
    # before the closing punctuation.
    out = _c06_drop_dangling(out)
    return _c06_squeeze_ws(out).strip().strip(",").strip()


def _out_of_range_year_in(text: str, schemes: "list[str] | None" = None) -> "str | None":
    """Raw text of the first financial-year token in `text` that NONE of the
    given scheme(s) hold, or None if every year mentioned is available / none is
    mentioned. Runs on raw text only — no LLM, no DB."""
    for start, tok in _c06_year_range_tokens(text or ""):
        yk = _calendar_month_fy_key(text, start, tok) or _parse_year_key(tok)
        if yk is not None:
            if not _year_in_data_range(yk, schemes):
                return tok
        elif _YEAR_SHAPED_MATCH.search(tok):   # e.g. "1999-20" — a year we can't parse
            return tok
    # A digit run right after an explicit temporal cue, at the very END of the
    # question ("in 20217", "...beneficiaries in Bamil Reserve Apal in 20217?")
    # that _c06_year_range_tokens above didn't match at all — its 20[1-3]\d
    # alternative needs a \b right after the 4th digit, so one extra trailing
    # digit ("20217") makes the WHOLE token invisible to it, not just
    # unparseable. Without this, "in 20217" skipped the guard entirely and the
    # SQL generator copied the literal straight into year_key = 20217, ran
    # clean, and silently returned 0 (2026-09-09 bug report — no clarification
    # was ever offered). Anchored to end-of-question (not just gated on a cue
    # word) so a real amount stated mid-sentence ("sanctioned amount of 500000
    # in Siju") is never mistaken for a year — a year mention is normally the
    # last thing named in these questions, an amount normally isn't.
    tail = _c06_malformed_year_tail(text or "")
    if tail and _parse_year_key(tail) is None:
        return tail
    return None


def _available_years_for(schemes: list[str]) -> "tuple[list[str], list[str]]":
    """(distinct FY list across the given scheme(s), scheme names used). Falls
    back to every scheme when `schemes` is empty or unrecognised.

    Years are merged scheme-by-scheme, so without an explicit sort the result
    lands in whatever order the schemes happen to combine in (e.g. MGNREGA's
    2022-23..2025-26 ahead of PMAY-G's earlier 2017-18..2021-22) rather than
    chronological order. Sort ascending (oldest first) so the year chips read
    in a sane order regardless of scheme combination."""
    live = [s for s in (schemes or []) if s in _SCHEME_DATA_YEARS] or list(_SCHEME_DATA_YEARS)
    seen: set[str] = set()
    years: list[str] = []
    for s in live:
        for y in _SCHEME_DATA_YEARS[s]:
            if y not in seen:
                seen.add(y)
                years.append(y)
    years.sort(key=_fy_start)
    return years, live


def _c06_cut_year(text: str, tok: str) -> str:
    """Remove the first `tok` with any "for "/"in "/"during "/"of "/"FY " lead-in
    and a comma before it."""
    k = _c06_find_year_tok(text, tok)
    if k < 0:
        return text
    start = _c06_back_over_prep(text, _c06_back_over_fy(text, k), ("for", "in", "during", "of"))
    j = _c06_back_over_ws(text, start)
    if j > 0 and text[j - 1] == ",":
        j = _c06_back_over_ws(text, j - 1)
    return text[:j] + text[k + len(tok):]


def _year_out_of_range_clarification(question: str, raw_year: str,
                                    schemes: list[str]) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    # Strip the offending year (and any "for "/"in "/"FY " lead-in, or a bare
    # comma before it) out of the stem, so the chip questions we build below
    # don't carry it back in and trip this same pause on the next turn.
    stem = _c06_cut_year(stem, raw_year.strip()).strip().rstrip(",").strip() \
        or question.strip().rstrip(" ?.")

    years, live = _available_years_for(schemes)
    if not years:
        # Every scheme in play has NO time dimension at all (CM Elevate: no
        # year_key, no date column of any kind) — there is no "these years are
        # available" chip list to offer. Refuse the time filter outright rather
        # than showing an out-of-range message with zero year options.
        scheme_word = live[0] if len(live) == 1 else (" and ".join(live) if live else "This scheme")
        return ClarificationNeeded(
            f"{scheme_word} has no date field in this data, so records cannot be "
            f"placed in a financial year or any other time period. I can answer "
            "without a time filter instead.",
            options=[{"label": "Answer without a time filter", "question": stem}],
            rule="no-time-dimension",
        )
    if len(live) == 1:
        coverage = (f"For {live[0]}, data is available only for the financial "
                    f"years {', '.join(years)}.")
    else:
        per_scheme = "; ".join(
            f"{s} — {', '.join(_SCHEME_DATA_YEARS[s])}" for s in live
        )
        coverage = ("Data is available only for the following financial years: "
                    f"{per_scheme}.")

    options = [
        {"label": f"FY {y}", "question": f"{stem} for FY {y}"}
        for y in years
    ]
    options.append({
        "label": "All available years combined",
        "question": f"{stem} across all financial years",
    })
    return ClarificationNeeded(
        f"{coverage} No data is held for “{raw_year.strip()}”. "
        "Please select one of the financial years listed above, or all of them "
        "combined.",
        options=options,
        rule="year-out-of-range",
    )

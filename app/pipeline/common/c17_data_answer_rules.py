# ── Data-answer rules shared by every scheme (data-accuracy brief, 2026-10-29) ──
# Ten questions with known answers (D1-D10, the user's brief megh_chatbot_fix_prompt.md)
# showed the SQL mostly right and the failures AROUND it: a multi-part question
# answered in part (D5, D10), a superlative answered with one row and no context
# (D3), a made-up string literal posing as an answer (D10's 'PMAY' AS
# scheme_with_most_records), a stray LIMIT on a one-row total (D9), money in three
# formats (D2, D8, D9) and no caveat on provisional / gapped datasets (D8, D9).
# These are the general rules, called at run time from the stages that own each
# step (c11 rewrites and guards, c12 number formatting, c13 compose, finalize):
#   RC1  _c17_sub_asks                      — the asks one question carries
#   RC3  _c17_sql_hygiene, _c17_sql_issue   — LIMIT noise, literal answers, other schemes' views
#   RC4  _c17_runners_up_answer             — the winner plus the next two, ties said
#   RC5  _c17_attach_caveats                — provisional / unverified money, absent years
#   RC6  _c17_money_cols                    — a money column's unit from the dataset registry
# Facts about each dataset come from scheme_registry.DATASETS; the years each one
# holds are read live (_SCHEME_DATA_YEARS). No regex (D-046): words through
# app/text_match, SQL through app/sql_ast.

# ── RC1: the asks in one question ──────────────────────────────────────────
# "How many PMAY-G houses in total, and how many completed?" carries two asks; "CM
# Elevate Legacy: number of records, subsidy disbursed, scheme with most records?"
# three. Split on the joiners officers use between asks. A joiner inside a place
# name ("Jaintia Hills and ...") makes an extra part, never a lost one: callers ask
# whether some part carries a measure, so an extra fragment does no harm.
_C17_JOINERS = (",", ";", "?", " and ", " also ", " as well as ", " plus ", " along with ", " & ")


def _c17_sub_asks(question: str) -> "list[str]":
    """The question cut at every ask joiner, each part stripped; parts with no word dropped."""
    text = " " + collapse_ws(question or "") + " "
    low = text.lower()
    cuts: list[tuple[int, int]] = []
    for j in _C17_JOINERS:
        pos = 0
        while True:
            k = low.find(j, pos)
            if k < 0:
                break
            cuts.append((k, k + len(j)))
            pos = k + len(j)
    parts, last = [], 0
    for s, e in sorted(cuts):
        if s < last:
            continue
        # "Focus Plus" is a scheme's name, not two asks (accuracy gold bank 2026-11-11, KI-673): "Which
        # district received the highest total Focus Plus disbursement?" was cut into "…total Focus" +
        # "disbursement" and answered as two clarifications
        if low[s:e] == " plus " and low[:s].rstrip().endswith("focus"):
            continue
        parts.append(text[last:s])
        last = e
    parts.append(text[last:])
    return [p.strip(" :.-") for p in parts if any(ch.isalpha() for ch in p)]


# ── RC4: a superlative names the winner and the next two ───────────────────
# "Which district had the most households completing 100 days in FY 2022-23?" was
# answered "East Garo Hills 22,049" from ORDER BY … LIMIT 1, with nothing to say how
# far ahead it was (D3). A singular superlative with no stated length now reads the
# top three: the winner is named, the next two give the context, a tie is said.
_C17_DIM_SINGULAR = frozenset({"district", "block", "village", "scheme", "year", "constituency", "tranche",
                               "gender", "category", "sector", "group", "month"})
_C17_DIM_PLURAL = frozenset({"districts", "blocks", "villages", "schemes", "years", "constituencies",
                             "tranches", "categories", "sectors", "groups", "months"})
_C17_HIGH = frozenset({"most", "highest", "largest", "biggest", "maximum", "top", "best", "leading", "greatest"})
_C17_LOW = frozenset({"least", "lowest", "smallest", "minimum", "bottom", "worst", "fewest"})
_C17_PER_GROUP = frozenset({"each", "every", "per", "wise"})
_C17_RUNNERS_UP = 3


def _c17_singular_superlative(question: str) -> "str | None":
    """"desc" / "asc" when the question asks for THE one highest / lowest of a
    singular dimension ("which district had the most …") and states no list
    length; else None."""
    # "across all financial years" scopes the ask; its "years" is no plural dimension
    low = _c01_tm_words(_YEARS_SCOPE_PHRASE.sub(" ", question or ""))
    s = set(low)
    if not (s & _C17_DIM_SINGULAR) or (s & _C17_DIM_PLURAL) or (s & _C17_PER_GROUP):
        return None
    if _requested_rank_count(question or "") is not None:
        return None
    up, down = bool(s & _C17_HIGH), bool(s & _C17_LOW)
    if up == down:
        return None
    return "desc" if up else "asc"


def _c17_simple_ranking_tree(sql: str) -> "exp.Select | None":
    """The one SELECT of a plain GROUP BY … ORDER BY query (no set operation, no
    window, no OFFSET), else None."""
    trees = sql_ast.parse(sql)
    if len(trees) != 1 or not isinstance(trees[0], exp.Select):
        return None
    tree = trees[0]
    if any(True for _ in tree.find_all(exp.SetOperation)) or any(True for _ in tree.find_all(exp.Window)):
        return None
    if tree.args.get("offset") is not None or not tree.args.get("group") or not tree.args.get("order"):
        return None
    return tree


def _c17_widen_top1(question: str, sql: str) -> str:
    """Any LIMIT (or none: the whole ranked list) on a singular superlative's ranking
    -> LIMIT 3: the winner, and the next two as context. The question named no list
    length, so a model's LIMIT 12 (PMAY-G probe 2026-10-29) is no one's request."""
    if not sql or _c17_singular_superlative(question) is None:
        return sql
    if _c17_simple_ranking_tree(sql) is None or sql_ast.outer_limit(sql) == _C17_RUNNERS_UP:
        return sql
    logger.info("superlative: LIMIT 1 -> %d, the winner and the next two", _C17_RUNNERS_UP)
    return sql_ast.set_limit(sql, _C17_RUNNERS_UP)


def _c17_as_asked(question: str, sql: str) -> str:
    """The SQL with the runners-up LIMIT 3 back to the LIMIT 1 the question asked for
    (what the semantic verifier is shown); any other SQL unchanged."""
    if (_c17_singular_superlative(question) is None or _c17_simple_ranking_tree(sql) is None
            or sql_ast.outer_limit(sql) != _C17_RUNNERS_UP):
        return sql
    return sql_ast.set_limit(sql, 1)


def _c17_drop_aggregate_limit(sql: str) -> str:
    """A LIMIT on a query that can only return one row (aggregates, no GROUP BY) is
    noise ("LIMIT 1000000" under SUM … — D9): dropped from the SQL shown and run."""
    if not sql:
        return sql
    trees = sql_ast.parse(sql)
    if len(trees) != 1 or not isinstance(trees[0], exp.Select):
        return sql
    tree = trees[0]
    if tree.args.get("limit") is None or tree.args.get("group") or tree.args.get("offset") is not None:
        return sql
    if any(True for _ in tree.find_all(exp.Window)) or any(True for _ in tree.find_all(exp.SetOperation)):
        return sql
    outs = tree.expressions
    if not outs or not all(any(True for _ in e.find_all(exp.AggFunc)) for e in outs):
        return sql
    logger.info("one-row aggregate: dropped its LIMIT %s", sql_ast.outer_limit(sql))
    return sql_ast.set_limit(sql, None)


def _c17_sql_hygiene(question: str, sql: str) -> str:
    """The model SQL rewrites of this file (the c11 rewrite chain calls it)."""
    return _c17_drop_aggregate_limit(_c17_widen_top1(question, sql))


# ── RC3: SQL that would show an invented value ─────────────────────────────
# D10's PMAY-G query selected 'PMAY' AS scheme_with_most_records: the model wrote
# the answer it guessed as a constant. A string constant may label a row (the
# PMAY-G facts query's 'Meghalaya' AS name, a cross-scheme 'MGNREGA' AS scheme);
# named as a finding (most / top / highest / which / answer / result …) it is an
# answer nobody read from the data.
_C17_FINDING_PARTS = frozenset({"most", "top", "highest", "lowest", "least", "max", "min", "maximum", "minimum",
                                "which", "answer", "result", "winner", "best", "worst", "leading", "largest",
                                "smallest", "biggest"})


def _c17_literal_answer_issue(sql: str) -> "str | None":
    trees = sql_ast.parse(sql)
    for tree in trees:
        for sel in tree.find_all(exp.Select):
            for e in sel.expressions:
                if not isinstance(e, exp.Alias) or not isinstance(e.this, exp.Literal) or not e.this.is_string:
                    continue
                if set(str(e.alias).lower().split("_")) & _C17_FINDING_PARTS:
                    return (f"the query selects the constant '{e.this.this}' AS {e.alias}: that states an answer "
                            "the data was never asked for. Compute it from the data instead — for a 'which … "
                            "most / highest' ask, GROUP BY that column, ORDER BY the measure DESC and LIMIT 3.")
    return None


def _c17_foreign_view_issue(schemes: "list[str]", sql: str) -> "str | None":
    """A query that reads a table owned by a scheme the question is not about."""
    if not schemes or not sql:
        return None
    mine = {t for s in schemes for t in (scheme_registry.DATASETS.get(s).owned_tables
                                         if scheme_registry.DATASETS.get(s) else ())}
    read = {t.split(".")[-1].lower() for t in sql_ast.tables(sql)}
    for s, facts in scheme_registry.DATASETS.items():
        if s in schemes:
            continue
        stray = sorted((read & set(facts.owned_tables)) - mine)
        if stray:
            return (f"this question is about {', '.join(schemes)} only, but the query reads "
                    f"{', '.join('curated.' + t for t in stray)}, which holds {s} data. Use only the "
                    f"{', '.join(schemes)} views.")
    return None


def _c17_superlative_unordered_issue(question: str, sql: str) -> "str | None":
    """A "which <dimension> … most / least" ask whose query neither orders nor takes a MAX / MIN."""
    if _c17_singular_superlative(question) is None or not sql:
        return None
    trees = sql_ast.parse(sql)
    if len(trees) != 1:
        return None
    tree = trees[0]
    if any(True for _ in tree.find_all(exp.Order)) or any(True for _ in tree.find_all(exp.Window)) \
            or sql_ast.has_aggregate(tree, "max", "min"):
        return None
    if not isinstance(tree, exp.Select) or not tree.args.get("group"):
        return None          # one total row: no dimension in the result to pick from
    return ("the question asks which one ranks highest / lowest, but the query has no ORDER BY: GROUP BY the "
            "dimension, ORDER BY the measure (DESC for most / highest, ASC for least / lowest) and LIMIT 3.")


def _c17_sql_issue(question: str, schemes: "list[str]", sql: str) -> "str | None":
    """The repair message for SQL that would state an invented or off-scope value, else None."""
    return (_c17_literal_answer_issue(sql) or _c17_foreign_view_issue(schemes, sql)
            or _c17_superlative_unordered_issue(question, sql))


def _c17_runners_up_answer(question: str, sql: str, rows: "list[dict]",
                           schemes: "list[str] | None", entities: "dict | None") -> "str | None":
    """"Highest <measure>: A (v1). Next: B (v2), then C (v3)." for a singular
    superlative read with LIMIT 3; a tie is said. None for any other result."""
    order = _c17_singular_superlative(question)
    if order is None or not (2 <= len(rows) <= _C17_RUNNERS_UP) or not sql:
        return None
    if _c17_simple_ranking_tree(sql) is None or sql_ast.outer_limit(sql) != _C17_RUNNERS_UP:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    metrics = _row_metrics(first)
    labels = [k for k, v in first.items() if _as_number(v) is None]
    if len(metrics) != 1 or len(labels) != 1:
        return None
    mcol, lcol = metrics[0][0], labels[0]

    def name(r) -> str:
        v = r.get(lcol)
        return _place_title(str(v)) if v is not None else "(not recorded)"

    def val(r):
        return _as_number(r.get(mcol))

    if any(val(r) is None for r in rows):
        return None
    word = "Highest" if order == "desc" else "Lowest"
    label = _metric_label(mcol)
    scheme, place, period = _scope_words(schemes, entities)
    where = "Meghalaya" if place.startswith("all of") else place.split(" (")[0]
    head = ", ".join(x for x in (scheme, where, period) if x)
    tied = [r for r in rows if val(r) == val(first)]
    rest = [r for r in rows if val(r) != val(first)]
    v1 = _c12_fmt_value(mcol, val(first))
    if len(tied) > 1:
        lead = f"{word} {label} ({head}): tied between {_join_list([name(r) for r in tied])}, {v1} each."
    else:
        lead = f"{word} {label} ({head}): {name(first)}, {v1}."
    if not rest:
        return lead
    nxt = [f"{name(r)} ({_c12_fmt_value(mcol, val(r))})" for r in rest]
    return lead + " Next: " + (nxt[0] if len(nxt) == 1 else ", then ".join(nxt)) + "."


# ── RC6: which result columns are money, in which unit ─────────────────────
# _c12_money_unit reads a column's unit from its SQL-prompt suffix (_lakh, _cr,
# _rupees). A column without one ("amount_disbursed", "subsidy") was not known as
# money, so "51,01,05,000.00" went out with no ₹ and a ".00" (D9). The unit then
# comes from the dataset registry (MGNREGA keeps lakh), never guessed; a count
# column is never money.
_C17_MONEY_PARTS = ("amount", "disburs", "subsid", "expend", "releas", "rupee", "money", "fund", "spent",
                    "outlay", "remit", "loan_amount", "sanctioned_amount", "pending_amount", "wage_exp")
_C17_COUNT_PARTS = ("count", "number", "houses", "records", "applications", "applicants", "beneficiar",
                    "members", "memberships", "groups", "payments", "days", "households", "persons", "pct",
                    "percent", "share", "ratio", "rate", "year", "status", "villages", "blocks", "districts",
                    "_no", "no_of", "num_")


def _c17_unit_by_name(col: str, scheme: "str | None") -> "str | None":
    low = str(col).lower()
    if not any(p in low for p in _C17_MONEY_PARTS) and low not in ("exp", "total_exp", "released"):
        return None
    if any(p in low for p in _C17_COUNT_PARTS):
        return None
    facts = scheme_registry.DATASETS.get(scheme or "")
    if facts is None or facts.money_unit is None:
        return None
    if facts.money_unit == "lakh" and ("per" in low.split("_") or "avg" in low or "average" in low):
        return None          # MGNREGA rupees per person-day is rupees, not lakh (KI-448)
    return facts.money_unit


def _c17_money_cols(rows: "list[dict]", schemes: "list[str] | None" = None) -> "list[tuple[float, str]]":
    """(value, unit) for every money cell of the result: by suffix first, else by
    name with the dataset's own unit (a row's "scheme" cell, else the one scheme)."""
    one = schemes[0] if schemes and len(schemes) == 1 else None
    out = []
    for r in (rows or [])[:200]:
        if not isinstance(r, dict):
            continue
        scheme = r.get("scheme") if r.get("scheme") in scheme_registry.DATASETS else one
        for k, v in _row_metrics(r):
            unit = _c12_money_unit(k) or _c17_unit_by_name(k, scheme)
            if unit:
                out.append((float(v), unit))
    return out


# ── RC5: the dataset's caveats, said with the answer ───────────────────────
# The cards mark Focus Plus / Focus Legacy / CM Elevate Legacy money "*" (figures
# provisional) and say "no FY 2023-24" for Focus Legacy; the chat said neither (D8,
# D9). A Note line is added when the answer states money from a provisional or
# unverified dataset, and when an all-years figure spans a year the data does not
# hold. Never twice: an answer that already names the gap year keeps its words.
_C17_NOTE = "Note:"


def _c17_answer_years(result: dict) -> "list[int] | None":
    """The year_keys the result is filtered to, [] for all years."""
    r = result.get("resolved_entities") or {}
    if r.get("year_key") is not None:
        return [r["year_key"]] if not isinstance(r["year_key"], list) else list(r["year_key"])
    if r.get("year_key_list"):
        return list(r["year_key_list"])
    sql = result.get("sql") or result.get("sql_query") or ""
    try:
        vals = sql_ast.filter_values(sql, "year_key", numeric=True) if sql else []
        fys = sql_ast.filter_values(sql, "financial_year_short", "financial_year") if sql else []
    except Exception:  # noqa: BLE001 — a SQL we cannot read is treated as unfiltered
        vals, fys = [], []
    years = [int(float(v)) for v in vals if str(v).replace(".", "").isdecimal()]
    years += [int(str(f)[:4]) for f in fys if str(f)[:4].isdecimal()]
    return years


def _c17_caveats(result: dict) -> "list[str]":
    if not isinstance(result, dict) or result.get("route") != "data":
        return []
    answer = result.get("answer") or ""
    if not answer or not (result.get("rows") or result.get("data")):
        return []
    schemes = [s for s in (result.get("schemes") or []) if s in scheme_registry.DATASETS]
    notes: list[str] = []
    if "₹" in answer:
        soft = [s for s in schemes if scheme_registry.DATASETS[s].money_unit
                and (scheme_registry.DATASETS[s].provisional or not scheme_registry.DATASETS[s].money_verified)]
        if soft:
            notes.append(f"{_C17_NOTE} {_join_list(soft)} amounts are provisional, and the money unit has not been "
                         "verified by the department.")
    years = _c17_answer_years(result)
    if years == []:
        for s in schemes:
            held = list(_SCHEME_DATA_YEARS.get(s) or [])
            gaps = _year_gaps(held) if len(held) > 1 else []
            gaps = [g for g in gaps if g not in answer]
            if gaps:
                # the gap only: a cohort-locked column (Focus Plus women, FY 2025-26 only)
                # covers fewer years than the dataset, so no "this total covers …"
                notes.append(f"{_C17_NOTE} there is no {s} data for {_join_list(['FY ' + g for g in gaps])} "
                             f"({'an absent year' if len(gaps) == 1 else 'absent years'}, not zero).")
    return [n for n in notes if n not in answer]


def _c17_mark_winner(result: dict) -> None:
    """A singular superlative's result (LIMIT 3 for context) names its answer row,
    which the follow-up context reads (context_manager.summarize_result)."""
    q = result.get("rewritten_question") or ""
    sql = result.get("sql") or result.get("sql_query") or ""
    rows = result.get("rows") or result.get("data") or []
    try:
        if (rows and isinstance(rows[0], dict) and _c17_singular_superlative(q) is not None
                and _c17_simple_ranking_tree(sql) is not None and sql_ast.outer_limit(sql) == _C17_RUNNERS_UP):
            result["winner_row"] = dict(rows[0])
    except Exception:  # noqa: BLE001 — context only
        logger.warning("winner row failed (non-fatal)", exc_info=True)


def _c17_attach_caveats(result: dict) -> None:
    """Add the dataset's Note lines under a finished DATA answer (finalize, via _finish_data_result)."""
    try:
        notes = _c17_caveats(result)
    except Exception:  # noqa: BLE001 — a caveat must never cost the answer
        logger.warning("dataset caveats failed (non-fatal)", exc_info=True)
        return
    if notes:
        result["answer"] = (result.get("answer") or "").rstrip() + "\n\n" + "\n".join(notes)
        result["caveats"] = notes


# ── RC1: a total and a "which … most" in one question ──────────────────────
# "CM Elevate Legacy: number of records, subsidy disbursed, scheme with most
# records?" needs two queries: one SQL cannot both total the whole dataset and pick
# its top scheme, and the model's GROUP BY scheme_name lost the totals (D10 re-run
# 2026-10-29). The conversation layer runs the plan's questions one after another
# and merges the answers (conversation_layer.answer_asks), in the order asked.
_C17_FIGURE_ASK = Matcher(Alt(
    Seq("how", W("many", "much")), Seq(W("number", "count", "total", "sum"), Opt("of")),
    W("total", "count", "amount", "records", "subsidy", "expenditure", "beneficiaries", "houses"),
    W("disburs", "sanction", "releas", "spent", prefix=True)))


_C17_RANK_GRAMMAR = (_C17_DIM_SINGULAR | _C17_HIGH | _C17_LOW
                     | frozenset("which what has have had is was the a with of in got received did".split()))


def _c17_cut(text: str, part: str) -> str:
    """`text` without `part` and the joiner before it ("…, and which scheme …" -> "…?")."""
    k = text.lower().find(part.lower())
    if k < 0:
        return text
    head, tail = text[:k].rstrip(), text[k + len(part):]
    for j in (", and", ",and", " and", ",", ";", " also"):
        if head.lower().endswith(j):
            head = head[: -len(j)].rstrip()
            break
    out = (head + tail).strip().rstrip(" ,;")
    return out if out.endswith("?") else out.rstrip(".") + "?"


# Accuracy gold bank (2026-11-11, KI-675; RAG PDF Table 2 #7, PARTIAL): "How many villages had MGNREGA
# activity and how many person-days were generated in total?" was one model query over v_employment:
# 6,419 villages, not the 6,491 with an employment OR expenditure record (the card; KI-574's fixed query
# _mgnrega_villages_active_query answers a plain village count, but a second figure in the same
# question kept it off). The village count and the other figure are two asks, answered in turn.
def _c17_village_count_plan(question: str, parts: "list[str]") -> "list[str] | None":
    if _named_or_inferred_schemes(question) != ["MGNREGA"]:
        return None
    vill = [p for p in parts if _VILLAGE_COUNT_ASK_MATCH.search(p) and not _MG_VILLAGE_MEASURE_WORDS.search(p)]
    rest = [p for p in parts if p not in vill and _C17_FIGURE_ASK.search(p)]
    if len(vill) != 1 or not rest:
        return None
    plan = []
    for p in parts:
        if p == vill[0]:
            plan.append(p.rstrip(" ?.") + ("" if "mgnrega" in p.lower() else " under MGNREGA") + "?")
        elif p in rest:
            plan.append(p.rstrip(" ?.") + "?")
    return plan


def _c17_ask_plan(question: str) -> "list[str] | None":
    """[the figures question, the "which … most" question] when one question
    carries both, else None. The second is completed with the first answer's
    scheme / place / year by the caller (_c17_ranking_question)."""
    parts = _c17_sub_asks(question)
    if len(parts) < 2:
        return None
    vill = _c17_village_count_plan(question, parts)
    if vill:
        return vill
    rank = [p for p in parts if _c17_singular_superlative(p)]
    rest = [p for p in parts if p not in rank]
    if len(rank) != 1 or not rest or not any(_C17_FIGURE_ASK.search(p) for p in rest):
        return None
    first = _c17_cut(question, rank[0])
    if _c17_singular_superlative(first) is not None:
        return None
    ask = rank[0].strip().rstrip("?")
    if _c01_tm_words(ask)[:1] not in (["which"], ["what"]):
        ask = "Which " + ask
    # "… and which district has the most?" names no measure of its own: it is the first ask's
    if not set(_c01_tm_words(ask)) - _C17_RANK_GRAMMAR:
        ask += " " + first.rstrip("?").replace("How many", "by number of").replace("how many", "by number of")
    return [first, ask + "?"]


def _c17_ranking_question(ask: str, first: dict) -> str:
    """The "which … most" ask completed with what the first answer was about."""
    out = ask.rstrip("?").rstrip()
    low = out.lower()
    for s in first.get("schemes") or []:
        if s.lower() not in low:
            out += f" under {s}"
    disp = _display_from_resolved(first.get("resolved_entities") or {})
    for k in ("village", "block", "district"):
        if disp.get(k) and str(disp[k]).lower() not in low:
            out += f" in {disp[k]} {k}"
            break
    out += f" in {disp['year']}" if disp.get("year") else " across all financial years"
    return out + "?"

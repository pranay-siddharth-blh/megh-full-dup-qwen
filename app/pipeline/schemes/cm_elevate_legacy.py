# app/pipeline/schemes/cm_elevate_legacy.py — CM Elevate Legacy (sanctions & disbursements) — notes, exact totals, SQL rewrites, answer guarantees.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
# Only this scheme's code lives here; the shared steps that call it are in ../common/.
# Sections follow the order of the pipeline steps they belong to.
# SQL is read and rewritten on the SQLGlot tree (app/sql_ast.py); the user's question,
# the answer text and result-row keys are read on words (app/text_match.py) or with
# plain string methods only (D-047).
from sqlglot import exp

from app import sql_ast
from app.text_match import (ANY, START, Alt, Cap, Hit, Matcher, Node, Opt, Pred, Seq, W,
                            collapse_ws, is_int, numbers)


# ════ scheme terms ════════════════════════════════════════════════════════════════════════════════════
def _prefers_cm_elevate_legacy(question: str) -> bool:
    """A CM Elevate question whose vocabulary only the sanction-and-disbursement
    dataset can answer (and none that only the applications dataset holds).
    Used for sub-scheme words ("piggery") that belong to both datasets; a bare
    "CM Elevate" name is settled by _cm_elevate_dataset_choice instead, and is
    never defaulted to Legacy (user decision 2026-10-19)."""
    q = question or ""
    if _CMELEVATE_APPLICATIONS_ONLY.search(q):
        return False
    return bool(_CMELEVATELEGACY_FORCING.search(q) or _CMELEVATELEGACY_ONLY_TERMS.search(q))


# ════ answer notes and guarantees ═════════════════════════════════════════════════════════════════════
# ── CM Elevate Legacy: "Sericulture" — spinning, weaving, or both? ──────────
# Sericulture is TWO stored schemes whose names differ by one space before the
# bracket, and an exact match on the wrong spelling returns zero rows silently
# (cmelevatelegacy_classification_rules.yaml sericulture_spelling_ambiguous; the
# prompt-layer bank's clarification K03). A bare "sericulture" is asked, never
# guessed; "both" is taken at its word.
_CM_LEGACY_SERICULTURE = ("Meghalaya Sericulture & Weaving Scheme (spinning)",
                          "Meghalaya Sericulture & Weaving Scheme(weaving)")
_SERICULTURE_WORD = Matcher(W("sericulture", "silk"))
_SERICULTURE_SIDE = Matcher(W("spinning", "weaving", "handloom"))
_SERICULTURE_BOTH = Matcher(Alt(
    "both", Seq("all", Opt("the"), "sericulture"), "sericulture schemes",
    W("together", "combined", "separately")))


def _cm_legacy_sericulture_choice(question: str) -> "list[str] | str | None":
    """Both Sericulture literals when the question asks for both, "ask" when it
    names Sericulture without saying which, else None (resolve normally)."""
    q = question or ""
    if not _SERICULTURE_WORD.search(q) or _SERICULTURE_SIDE.search(q):
        return None
    if _SERICULTURE_BOTH.search(q):
        return list(_CM_LEGACY_SERICULTURE)
    return "ask"


def _cm_legacy_sericulture_clarification(question: str) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")

    def _swap(repl: str) -> str:
        new = _SERICULTURE_WORD.sub(repl, stem, count=1)
        return new if new != stem else f"{stem} — {repl}"

    return ClarificationNeeded(
        "Sericulture is recorded as two separate schemes — spinning and weaving. "
        "Which did you mean, or both?",
        options=[
            {"label": "Spinning", "question": _swap("Sericulture spinning")},
            {"label": "Weaving", "question": _swap("Sericulture weaving")},
            {"label": "Both, shown separately",
             "question": _swap("both Sericulture schemes (spinning and weaving)")},
        ],
        rule="sericulture-spelling-ambiguous",
    )


# ── CM Elevate Legacy: questions the data cannot answer ─────────────────────
# Each matcher is a refusal class from the prompt-layer bank (refusal_code),
# worded by the bank's own reviewed text via annotations.refusal_reason. Checked
# deterministically before SQL generation: the generator can only emit a SELECT,
# so left to it these came back as an improvised figure or a bare "not
# available" with no reason. The matchers are deliberately narrow — the bank's
# re-verification found four over-broad refusal triggers (a relative "who", the
# word "individual", "overview", "focus") and each is avoided here.
_CM_LEGACY_NOT_HELD = (
    # SANCTION_RATE, NOT_SANCTIONED and CONSTITUENCY used to be refused here.
    # All three are answerable from the view (2026-09-25 use-case QA): the rate is
    # COUNT(sanctioned_amount) / COUNT(*) with a caveat about the separate
    # applications dataset, "not sanctioned" is the records with no sanctioned
    # amount, and constituency comes through the dim_geography join. The few-shot
    # bank (X01 / X02 / X07 / X08) teaches the SQL instead.
    ("APPLICANT_NAME", Matcher(Alt(
        Seq(START, W("who", "whose")),
        Seq("who", W("got", "received", "has", "had", "took"), "the",
            W("most", "maximum", "highest", "largest", "biggest")),
        Seq(W("name", "names"), "of", Opt("the"), Opt(ANY),
            Alt(W("beneficiar", prefix=True),
                W("applicant", "applicants", "recipient", "recipients", "people", "person", "persons",
                  "entrepreneur", "entrepreneurs"))),
        Seq(W("beneficiary", "applicant"), W("name", "names"), sep="space"), "name list"))),
    ("MONTHLY", Matcher(Alt(
        _cme_join("month", "wise"), "monthly", "by month", "per month", "each month",
        _cme_join("quarter", "wise"), W("quarter", "quarterly")))),
    ("APPLICANT_TYPE", Matcher(Alt(
        Seq(W("individual", "individuals"), W("vs", "versus", "or", "and"), W("group", "groups")),
        Seq("group", W("applicant", "applicants")), W("shg", "shgs"),
        Seq(_cme_join("self", "help"), W("group", "groups")),
        Seq(W("registered", "unregistered"), W("group", "groups")), Seq("applicant", "type", sep="space")))),
    ("REPAYMENT", Matcher(Alt(
        W("repaid", "repay", "repaying", "repayment", "repayments"), "loan recovery",
        W("defaulted", "defaulter", "defaulters")))),
    ("DEMOGRAPHICS", Matcher(Alt(
        W("woman", "women", "female", "male", "gender", "caste", "scst"), Seq("sc", "st"),
        Seq("scheduled", W("caste", "castes", "tribe", "tribes")), _cme_join("age", ("group", "wise")),
        W("minority", "minorities")))),
    ("BANK_SANCTIONED_SHARE", Matcher(Alt(
        _cme_join("bank", "sanctioned"), Seq("bank", Opt("s"), W("share", "contribution")),
        "did the bank contribute"))),
    ("TARGETS", Matcher(W("target", "targets", "budget", "budgeted", "budgets", "allocation", "allocations"))),
    ("BUSINESS_OUTCOME", Matcher(Alt(
        Seq(W("job", "jobs"), Opt("were"), W("created", "generated")), Seq("employment", W("created", "generated")),
        "turnover", Seq(W("venture", "ventures"), W("surviv", prefix=True)),
        Seq("business", W("outcome", "outcomes"))))),
    ("LINK_APPLICATIONS", Matcher(Alt(
        Seq(W("application", "applications"), "behind"),
        Seq(W("link", "match", prefix=True), W("to", "with"), Opt("the"), W("application", "applications"))))),
)


def _cm_legacy_not_held(question: str) -> "ClarificationNeeded | None":
    """A not-held explanation for a CM Elevate Legacy question the data cannot
    answer, or None when it can be answered."""
    for code, word_matcher in _CM_LEGACY_NOT_HELD:
        if not word_matcher.search(question or ""):
            continue
        reason = annotations.refusal_reason("CM Elevate Legacy", code)
        if not reason:
            continue
        main, _, offer = reason.partition("Offer instead:")
        text = main.strip()
        if offer.strip():
            text += " What I can offer instead: " + offer.strip()
        logger.info("CM Elevate Legacy not-held (%s): %r", code, question)
        return ClarificationNeeded(text, rule="column-not-held")
    return None


# ── CM Elevate Legacy: caveats that travel with the numbers ─────────────────
# The prompt layer routes its unit / year / village / refusal caveats by CODE,
# not by asking the model to remember them — each is triggered here by what the
# executed SQL actually did, so a caveat appears exactly when its number does.
_CM_LEGACY_MONEY_COLS = ("total_disbursement", "total_subsidy_disbursement", "total_loan_disbursement",
                         "sanctioned_amount")
_CM_LEGACY_REFUSAL_COLS = ("desanctioned_reason_raw", "refused_flag_raw", "refused_reason_text")


# ── SQL tree helpers (SQL is read on the SQLGlot tree, never as raw text) ──
def _cml_is_crore_divisor(node) -> bool:
    if not isinstance(node, exp.Literal) or node.is_string:
        return False
    try:
        return float(node.this) == 1e7
    except ValueError:
        return False


def _cml_year_filtered(sql_or_trees) -> bool:
    """A financial_year[_short] = / IN '<label>' or year_key = / IN <number> filter."""
    for node in sql_ast.filter_conditions(sql_or_trees, "financial_year", "financial_year_short"):
        if isinstance(node, (exp.EQ, exp.In)) and sql_ast.filter_values(
                node, "financial_year", "financial_year_short"):
            return True
    for node in sql_ast.filter_conditions(sql_or_trees, "year_key"):
        if isinstance(node, (exp.EQ, exp.In)) and any(
                not lit.is_string for lit in node.find_all(exp.Literal)):
            return True
    return False


def _cml_is_unresolved_neq(node) -> bool:
    """`entity_type <> 'Unresolved'` (or !=)."""
    hit = _fl_col_vs_literal(node, {"entity_type"}) if isinstance(node, exp.NEQ) else None
    return bool(hit) and hit[1].lower() == "unresolved"


def _cml_has_unresolved_neq(sql_or_tree) -> bool:
    trees = sql_ast.parse(sql_or_tree) if isinstance(sql_or_tree, str) else [sql_or_tree]
    return any(_cml_is_unresolved_neq(n) for t in trees for n in t.find_all(exp.NEQ))


def _cml_simple_select(sql: str) -> "exp.Select | None":
    """The query's tree when it is ONE plain SELECT (no subquery, JOIN, UNION or
    WITH), else None."""
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or len(sql_ast.selects(tree)) != 1 \
            or tree.args.get("joins") or sql_ast.has_cte(tree):
        return None
    return tree


def _cml_cr_sums(tree) -> list:
    """The outer SELECT's `ROUND(SUM(<column>) / 1e7, 2) AS <name>_cr` items."""
    sel = sql_ast.outer_select(tree) if tree is not None else None
    out = []
    for e in (sel.expressions if sel is not None else []):
        if not isinstance(e, exp.Alias) or not (e.alias or "").lower().endswith("_cr"):
            continue
        rnd = e.this
        dec = rnd.args.get("decimals") if isinstance(rnd, exp.Round) else None
        div = rnd.this if isinstance(rnd, exp.Round) else None
        if not (isinstance(dec, exp.Literal) and not dec.is_string and str(dec.this) == "2"
                and isinstance(div, exp.Div) and _cml_is_crore_divisor(div.expression)
                and isinstance(div.this, exp.Sum) and isinstance(div.this.this, exp.Column)):
            continue
        out.append(e)
    return out


def _cml_scope_query(tree, expressions: list) -> str:
    """The same FROM / WHERE with a new SELECT list, and no grouping, ordering or limit."""
    new = tree.copy()
    new.set("expressions", expressions)
    for part in ("distinct", "group", "having", "qualify", "order", "limit", "offset"):
        new.set(part, None)
    return sql_ast.to_sql(new)


def _cm_legacy_answer_notes(sql: str, rows: list[dict]) -> list[str]:
    s = sql or ""
    trees = sql_ast.parse(s)
    notes: list[str] = []
    cols = {k for r in (rows or [])[:1] if isinstance(r, dict) for k in r}
    if any(_cml_is_crore_divisor(n) for t in trees for n in t.find_all(exp.Literal)) \
            or any(c.endswith("_cr") for c in cols):
        notes.append(
            "Columns ending in _cr are already in ₹ crore (divided by 1e7); columns ending "
            "in _rupees are rupees. Write money as ₹<value> crore / ₹<value>, copying the "
            "digits exactly.")
    if sql_ast.references_column(trees, "total_disbursement"):
        # Only point at a subsidy / loan split the result actually carries: told
        # "give all three" with no such columns, the composer invented one ("This
        # total includes ₹0.58 crore as subsidy and …"), was rejected twice and the
        # officer got the raw fallback "0.58 total disbursed cr." (Mawkynrew,
        # all-constituencies run 2026-09-29).
        if any("subsid" in c.lower() or "loan" in c.lower() for c in cols):
            notes.append(
                "Total disbursed means subsidy and loan together. The subsidy and loan columns "
                "are in the result, so give all three; sanctioned is the amount approved, not "
                "the amount paid.")
        else:
            notes.append(
                "Total disbursed means subsidy and loan together. State the total only: this query "
                "did not select the split, so do not mention subsidy or loan at all — no figure, no "
                "estimate, and no remark that a split is unavailable.")
    if sql_ast.references_column(trees, *_CM_LEGACY_MONEY_COLS) \
            and not sql_ast.references_column(trees, "desanctioned_reason_raw"):
        notes.append(
            "Desanctioned records (Refused / Duplicate) are included in these money totals, "
            "as they are in the source file's own totals.")
    if trees and _cml_year_filtered(trees):
        notes.append(
            "395 records (both Sericulture schemes) carry no financial year, so they are "
            "outside any single-year figure — say so in one short clause.")
    if sql_ast.groups_by(trees, "financial_year", "financial_year_short"):
        notes.append(
            "The '(no financial year)' row is the 395 Sericulture records, which carry no "
            "year label — describe it that way, not as missing or erroneous data. Only two "
            "financial years exist, so describe this as a comparison, not a trend.")
    if len(rows or []) > 1 and any(c.endswith("_cr") for c in cols):
        # Seen live (TC-36 district summary, 2026-09-25): the composer added up
        # the per-district _cr figures and stated ₹81.09 / ₹29.24 / ₹51.88 crore
        # against the true ₹81.10 / ₹29.23 / ₹51.87 — each row is rounded to 2
        # decimals, so a sum of them drifts. Counts are exact and may be summed.
        def _is_total(r: dict) -> bool:
            return any(isinstance(v, str) and v.upper().startswith("ALL ") for v in r.values())
        has_total_row = any(_is_total(r) for r in rows)
        # Name the extremes here rather than leave them to the composer: with a
        # trailing ALL row it took the row above it as "the lowest" (TC-36,
        # North Garo Hills ₹2.60 Cr instead of East Jaintia Hills ₹2.36 Cr).
        body = [r for r in rows if not _is_total(r)]
        metric = "total_disbursed_cr" if "total_disbursed_cr" in cols else \
            next((c for c in cols if c.endswith("_cr")), None)
        ranked = [r for r in body if _as_number(r.get(metric)) is not None]
        if metric and len(ranked) >= 2:
            def _label(r: dict) -> str:
                return " / ".join(str(v) for v in r.values()
                                  if isinstance(v, str)) or "(unlabelled)"
            hi = max(ranked, key=lambda r: _as_number(r[metric]))
            lo = min(ranked, key=lambda r: _as_number(r[metric]))
            notes.append(
                f"By {metric}: highest is {_label(hi)} ({_fmt_num(_as_number(hi[metric]))}), "
                f"lowest is {_label(lo)} ({_fmt_num(_as_number(lo[metric]))}). Use these exactly "
                "when naming the top or bottom row.")
        notes.append(
            "Each _cr value is rounded to 2 decimals per row, so NEVER add them across rows "
            "to state a combined money total — the sum drifts from the true figure. "
            + (f"The row labelled 'ALL …' holds the exact totals: quote statewide figures from "
               f"that row only. It is a TOTAL, not an area — the breakdown has exactly "
               f"{len(rows) - 1} rows besides it, so say {len(rows) - 1}, never {len(rows)}. "
               "Also name the top and bottom rows of the breakdown. "
               if has_total_row else
               "Describe the rows (highest, lowest, range); a combined money total may "
               "only be quoted from an 'Exact combined totals' note. ")
            + "Record counts are exact and may be summed.")
    if "sanctioned_records" in cols:
        notes.append(
            "sanctioned_records is the number of SANCTIONED cases (records carrying a "
            "sanctioned amount) — report it under that name, separately from records where "
            "both appear; do not call records 'sanctioned'. It is a COUNT: when listing "
            "rows, give every row's sanctioned_records value, never its _cr money value "
            "in place of the count (TC-19: Motorcaravan 1 record was written as '0.50 crore').")
    if "sanctioned_pct" in cols:
        notes.append(
            "sanctioned_pct is the share of records in THIS sanction-and-disbursement dataset "
            "that carry a sanctioned amount. Give the percentage and the two counts, then say "
            "in one clause that applications which never reached sanction sit in the separate "
            "CM Elevate applications dataset, which cannot be linked to this one.")
    if "not_sanctioned_records" in cols:
        notes.append(
            "not_sanctioned_records are records with no sanctioned amount. Desanctioned "
            "(Refused / Duplicate) counts are sanctions withdrawn later — label them that way, "
            "never add them to the not-sanctioned figure.")
    if sql_ast.references_column(trees, "ac_name"):
        notes.append(
            "The constituency comes from the geography registry through each record's "
            "village; records with no village carry no constituency. Say this in one short "
            "clause, and call it the assembly constituency, not a block.")
    if any(_cml_has_unresolved_neq(t) for t in trees):
        notes.append(
            "Records that could not be matched to a village are left out of village "
            "figures (they still count in district and block totals); villages are counted "
            "by LGD code.")
    if sql_ast.references_column(trees, *_CM_LEGACY_REFUSAL_COLS):
        notes.append(
            "The desanction reason, the refusal flag and the written reason disagree — name "
            "the field each figure comes from and present none of them as the "
            "authoritative refusal count.")
    return notes


async def _cm_legacy_exact_totals(sql: str, rows: list[dict]) -> list[str]:
    """Exact combined money totals for a multi-row _cr breakdown with no ALL row.

    Seen live (TC-27, 2026-09-25): the composer added up 12 rounded per-district
    figures and wrote "sums to ₹82.89 crore" against the true ₹82.90 — the prose
    rule not to sum rounded values did not hold. The total is re-queried from the
    same FROM/WHERE with the GROUP BY removed, so the composer can quote it exactly.
    Only the plain single-SELECT shape is handled; anything else returns no note."""
    if len(rows or []) < 2:
        return []
    tree = sql_ast.parse_one(sql or "")
    if not isinstance(tree, exp.Select) or sql_ast.has_cte(tree) \
            or any(True for _ in tree.find_all(exp.Having, exp.Rollup, exp.Cube, exp.GroupingSets)):
        return []
    if any(isinstance(v, str) and v.upper().startswith("ALL ") for r in rows for v in r.values()):
        return []
    sums = _cml_cr_sums(tree)
    # the plain shape only: grouped, and no subquery in its FROM / JOIN / WHERE
    scope_parts = [tree.args.get(k) for k in ("from_", "from", "where")] + list(tree.args.get("joins") or [])
    if not sums or not tree.args.get("group") or any(
            p is not None and any(True for _ in p.find_all(exp.Select)) for p in scope_parts):
        return []
    try:
        got = await run_readonly(_cml_scope_query(tree, [e.copy() for e in sums]))
    except Exception:  # noqa: BLE001
        logger.warning("CM Legacy exact-total query failed — no total note", exc_info=True)
        return []
    if not got:
        return []
    figures = ", ".join(f"{k} = {_fmt_num(_as_number(v))}" for k, v in got[0].items()
                        if _as_number(v) is not None)
    if not figures:
        return []
    return [f"Exact combined totals across every group (queried separately, not a sum of "
            f"the rounded rows): {figures}. If you state a combined money total, use "
            f"exactly these figures."]


# ── CM Elevate Legacy answer guarantees (use-case re-test 2026-09-29, KI-167) ─
# TC-34 "applications mapped to each village in Tikrikilla block": the SQL and
# table were right (42 villages, 89 records) but the composer wrote "20 villages
# each have 1 record" against a true 24, on 5 of 5 runs. It sees only the first
# 40 rows, and the faithfulness check lets whole numbers under 100 through as
# prose, so a wrong derived count cannot be caught there. Such counts are
# recomputed from EVERY row here and corrected in place. The answer also never
# said that 6 Tikrikilla records have no village code; that is stated from a
# re-query of the same scope.
_NUM_WORDS = {"no": 0, "zero": 0, "one": 1, "a single": 1, "single": 1, "two": 2, "three": 3, "four": 4,
              "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
              "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "twenty": 20}
class _CmlDigits(Node):
    """A number written with digits and commas ("1,234"): digit words joined by a bare
    ','. Longest first, then each shorter comma-prefix (a digit, then digits/commas)."""

    def ends(self, ctx, i, caps):
        toks = ctx.toks
        if i >= len(toks) or not is_int(toks[i].raw):
            return
        j = i + 1
        while j < len(toks) and is_int(toks[j].raw) and ctx.text[toks[j - 1].end:toks[j].start] == ",":
            j += 1
        for e in range(j, i, -1):
            yield e, caps


# A number: digits, or a number word ("a single" before "single").
_CML_NUM_NODE = Alt(_CmlDigits(), Seq("a", "single", sep="space"),
                    W(*[w for w in _NUM_WORDS if w not in ("no", "a single")]))
_CML_EACH_HAVE_MATCH = Matcher(
    Cap(_CML_NUM_NODE, "n"), Opt(Alt("other", "more", Seq("of", "the", sep="space"))), Opt("distinct"),
    Cap(W("villages", "blocks", "districts", "schemes", "constituencies", "wards"), "noun"),
    Opt("each"),
    W("have", "has", "had", "hold", "holds", "held", "record", "recorded", "show", "shows", "with", "carry",
      "carries"),
    Opt("each"), Opt(W("only", "just", "exactly")), Cap(_CML_NUM_NODE, "v"),
    W(*[f for w in ("record", "application", "applicant", "case", "beneficiary", "beneficiarie", "entry", "entrie")
        for f in (w, w + "s")]),
    sep="space")


def _cml_count_column(rows: list[dict]) -> "str | None":
    """The one count column of a breakdown, or None when there is not exactly one."""
    cols = [k for k, v in (rows[0].items() if rows else ())
            if _as_number(v) is not None and not _NONSTAT_COL.search(k)
            and not k.endswith(("_cr", "_rupees", "_pct", "_amount"))]
    return cols[0] if len(cols) == 1 else None


def _cml_fix_each_have_counts(answer: str, rows: list[dict]) -> str:
    col = _cml_count_column(rows or [])
    if not answer or not col or len(rows) < 2:
        return answer
    body = [r for r in rows if not any(isinstance(v, str) and v.upper().startswith(("UNRESOLVED", "ALL "))
                                       for v in r.values())]

    def _num(tok: str) -> "int | None":
        t = tok.strip().lower().replace(",", "")
        return int(t) if t.isdigit() else _NUM_WORDS.get(t)

    def _fix(m: "Hit") -> str:
        n, v = _num(m.group("n")), _num(m.group("v"))
        if n is None or v is None:
            return m.group(0)
        true = sum(1 for r in body if _as_number(r.get(col)) == v)
        if true == n:
            return m.group(0)
        logger.warning("CM Elevate Legacy: answer said %d %s have %d; the rows give %d — corrected (KI-167)",
                       n, m.group("noun"), v, true)
        return m.group(0)[:m.start("n") - m.start()] + f"{true:,}" + m.group(0)[m.end("n") - m.start():]
    return _CML_EACH_HAVE_MATCH.sub(_fix, answer)


_CML_VILLAGE_STEM = W("village", prefix=True)
_CML_NO_VILLAGE_SAID = Matcher(Alt(
    Seq("no", _CML_VILLAGE_STEM), Seq("without", "a", _CML_VILLAGE_STEM),
    Seq("not", W("mapped", "matched"), "to", W("a", "any"), _CML_VILLAGE_STEM),
    W("unmapped", prefix=True), Seq("could", "not", "be", W("matched", "mapped", prefix=True)),
    Seq("not", "yet", W("mapped", prefix=True)), Seq("no", Opt("lgd"), "village", W("code", prefix=True))))


async def _cml_unmapped_in_scope(sql: str) -> int:
    """Records the village breakdown left out (entity_type = 'Unresolved') in the
    SAME place / year scope, re-queried from the breakdown's own FROM / WHERE."""
    tree = _cml_simple_select(sql or "")
    if tree is None or not sql_ast.groups_by(tree, "lgd_village_name", "village_code") \
            or not _cml_has_unresolved_neq(tree):
        return 0
    tree = tree.copy()
    for node in list(tree.find_all(exp.NEQ)):
        if _cml_is_unresolved_neq(node):
            node.replace(exp.EQ(this=node.this.copy(), expression=node.expression.copy()))
    count = exp.alias_(exp.Count(this=exp.Star()), "n")
    try:
        got = await run_readonly(_cml_scope_query(tree, [count]))
    except Exception:  # noqa: BLE001
        logger.warning("CM Legacy unmapped-records query failed — no note", exc_info=True)
        return 0
    return int(_as_number(got[0].get("n")) or 0) if got else 0


def _cml_inr(v: "int | float") -> str:
    """Rupees in Indian grouping: 150000 -> ₹1,50,000; paise kept only when present."""
    neg, v = v < 0, abs(float(v))
    whole, paise = int(v), round((v - int(v)) * 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join([head] + groups) + "," + tail
    return ("-" if neg else "") + "₹" + s + (f".{paise:02d}" if paise else "")


# A single money figure that rounds to 0.00 crore: the small-money note makes the
# composer write "under ₹0.01 crore", which is also what it wrote for a TRUE zero
# (UMTHAM, Umling: ₹0.00 disbursed; all-villages run 2026-09-29). The exact
# amount is re-queried and written instead — ₹0 or the rupee figure.
def _cml_lit(t: str, i: int, w: str) -> int:
    """i + len(w) when `t` has `w` at i (any case), else -1."""
    return i + len(w) if i >= 0 and t[i:i + len(w)].lower() == w else -1


def _cml_ws(t: str, i: int, least: int = 1) -> int:
    """Past the whitespace at i; -1 when there are fewer than `least` characters of it."""
    if i < 0:
        return -1
    j = i
    while j < len(t) and t[j].isspace():
        j += 1
    return j if j - i >= least else -1


def _cml_one_of(t: str, i: int, *options) -> int:
    for opt in options:
        j = i
        for k, w in enumerate(opt.split(" ")):
            j = _cml_lit(t, _cml_ws(t, j) if k else j, w)
        if j >= 0:
            return j
    return -1


def _cml_rupee(t: str, i: int, amount: str) -> int:
    """'₹', at most one whitespace character, then `amount`."""
    j = _cml_lit(t, i, "₹")
    if j >= 0 and j < len(t) and t[j].isspace():
        j += 1
    return _cml_lit(t, j, amount)


def _cml_under_crore_at(t: str, p: int) -> int:
    """The end of "under ₹0.01 crore" (or "less than" / "below"), with an optional
    "(less than ₹1 lakh)" / "(under ₹1 lakh)" after it, at p; else -1."""
    j = _cml_one_of(t, p, "under", "less than", "below")
    j = _cml_rupee(t, _cml_ws(t, j), "0.01")
    j = _cml_lit(t, _cml_ws(t, j), "crore")
    if j < 0:
        return -1
    k = _cml_lit(t, _cml_ws(t, j, 0), "(")
    k = _cml_one_of(t, k, "less than", "under")
    k = _cml_rupee(t, _cml_ws(t, k), "1")
    k = _cml_lit(t, _cml_lit(t, _cml_ws(t, k), "lakh"), ")")
    return k if k >= 0 else j


def _cml_under_crore_sub(text: str, repl: str) -> "tuple[str, int]":
    """Every "under ₹0.01 crore …" phrase replaced by `repl`; (new text, how many)."""
    out, last, p, n = [], 0, 0, 0
    while p < len(text):
        e = _cml_under_crore_at(text, p)
        if e > p:
            out.append(text[last:p] + repl)
            last = p = e
            n += 1
        else:
            p += 1
    return "".join(out) + text[last:], n


async def _cml_exact_single_amount(sql: str, rows: list[dict]) -> "tuple[bool, float | None]":
    """(found, exact rupees) for a one-row result whose one _cr cell is under
    0.10 crore — at that size the 2-decimal crore figure hides the amount
    (₹62,500 and ₹1,25,000 both read "₹0.01 crore"). A one-row GROUP BY sums
    the same scope, so the grouping is dropped from the re-query."""
    if len(rows or []) != 1:
        return False, None
    small = [k for k, v in rows[0].items() if k.endswith("_cr")]
    if len(small) != 1 or _as_number(rows[0][small[0]]) is None or _as_number(rows[0][small[0]]) >= 0.10:
        return False, None
    tree = _cml_simple_select(sql or "")
    if tree is None or tree.args.get("having"):
        return False, None
    # alias -> the summed column (Alias -> ROUND -> division -> SUM -> column)
    exprs = {e.alias.lower(): e.this.this.this.this for e in _cml_cr_sums(tree)}
    expr = exprs.get(small[0].lower())
    if expr is None:
        return False, None
    try:
        got = await run_readonly(_cml_scope_query(tree, [exp.alias_(exp.Sum(this=expr.copy()), "v")]))
    except Exception:  # noqa: BLE001
        logger.warning("CM Legacy exact small-amount query failed — answer left as is", exc_info=True)
        return False, None
    return (True, _as_number(got[0].get("v"))) if got else (False, None)


def _cml_fix_place_spelling(answer: str, display: dict, rows: "list[dict] | None" = None) -> str:
    """A near-miss spelling of the place the query filtered on, or of a place
    label in the result rows, replaced by its canonical name. The composer wrote
    "Sellsella block" for SELSELLA on 3 of 3 runs, and "Mawsynrut" for the
    MAWSHYNRUT row of a West Khasi Hills block breakdown (all-villages run
    2026-09-29); the stored names are known exactly. A word that IS another
    known name is never touched."""
    import difflib
    labels = list(dict.fromkeys(
        str(v).strip() for r in (rows or [])[:60] for k, v in r.items()
        if isinstance(v, str) and any(k == s or k.endswith("_" + s)
                                      for s in ("block", "district", "village_name", "ac_name"))))
    names = [(k, n.strip()) for k in ("village", "block", "district", "constituency")
             for n in _cml_split_and(str(display.get(k) or "")) if n.strip()] \
        + [("row", n) for n in labels]
    known = {n.lower() for _k, n in names}
    for key, name in names:
        words = _cml_name_words(name)
        if not words or len(name) < 5:
            continue
        toks = _cml_name_words(answer or "")
        # a name ending in punctuation: "TEPORPARA ( UPPER )" written right was
        # matched as the near-miss "Teporpara ( Upper" (letter words only) and
        # "corrected" to "Teporpara ( Upper ) )" (all-villages re-run 2026-10-02)
        cut = len(name)
        while cut and not _cme_is_ascii_letter(name[cut - 1]):
            cut -= 1
        trail = "".join(name[cut:].split())
        bad = set()
        for i in range(len(toks) - len(words) + 1):
            end = toks[i + len(words) - 1][1]
            if trail:
                end += _cml_trail_len(answer[end:], trail)
            span = answer[toks[i][0]:end]
            if span.lower() in known or span[0].lower() != name[0].lower()                     or abs(len(span) - len(name)) > 2:
                continue
            if difflib.SequenceMatcher(None, span.lower(), name.lower()).ratio() >= 0.88:
                bad.add(span)
        for sp in bad:
            # keep the answer's own case style: "MAWSYNRUT" -> "MAWSHYNRUT", "Sellsella" -> "Selsella"
            canon = name.upper() if sp.isupper() else (name.title() if name.isupper() else name)
            logger.warning("CM Elevate Legacy: answer spelled %s %r as %r — corrected", key, name, sp)
            answer = _cml_replace_letter_bounded(answer, sp, canon)
    return answer


def _cml_split_and(s: str) -> "list[str]":
    """`s` split at every " and " (whitespace on both sides; case as written)."""
    out, last, i, n = [], 0, 0, len(s)
    while i < n:
        if not s[i].isspace():
            i += 1
            continue
        r = i
        while r < n and s[r].isspace():
            r += 1
        if s.startswith("and", r) and r + 3 < n and s[r + 3].isspace():
            e = r + 3
            while e < n and s[e].isspace():
                e += 1
            out.append(s[last:i])
            last = i = e
        else:
            i = r
    return out + [s[last:]]


def _cml_name_words(text: str) -> "list[tuple[int, int]]":
    """(start, end) of each word that starts with an ASCII letter and runs on over
    letters, apostrophes and hyphens ("Mawkyn-rew", "O'Neil")."""
    out, i, n = [], 0, len(text)
    while i < n:
        if _cme_is_ascii_letter(text[i]):
            j = i + 1
            while j < n and (_cme_is_ascii_letter(text[j]) or text[j] in "'-"):
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def _cml_trail_len(text: str, trail: str) -> int:
    """How much of `text` the characters of `trail` take, whitespace allowed before
    each; 0 when they are not all there."""
    j = 0
    for ch in trail:
        while j < len(text) and text[j].isspace():
            j += 1
        if j >= len(text) or text[j] != ch:
            return 0
        j += 1
    return j


def _cml_replace_letter_bounded(text: str, old: str, new: str) -> str:
    """Every `old` with no ASCII letter right before or after it replaced by `new`."""
    out, last, i = [], 0, 0
    while old:
        k = text.find(old, i)
        if k < 0:
            break
        e = k + len(old)
        if (k == 0 or not _cme_is_ascii_letter(text[k - 1])) and (e >= len(text) or not _cme_is_ascii_letter(text[e])):
            out.append(text[last:k] + new)
            last = i = e
        else:
            i = k + 1
    return "".join(out) + text[last:]


# A per-group COUNT breakdown whose figures are not beside their names. "How
# many applications under each scheme in Umsning block?" came back as "…Piggery
# holding the highest count at 27. The remaining schemes show 24, 16, 15, 13, 6,
# 3, 1, and 1 records respectively" — nine figures, one name (all-blocks run
# 2026-09-29, 3 blocks). Detection is CM Elevate's (_cme_complete_list, KI-068 /
# KI-073); the list is rebuilt from the rows under the composer's headline.
# Money breakdowns keep their composer text (exact-total and extremes notes).
_CML_DIM_NAME = {"scheme_name": "scheme", "lgd_block": "block", "lgd_district": "district",
                 "loan_entity": "loan entity", "financial_year": "financial year",
                 "financial_year_short": "financial year", "ac_name": "constituency",
                 "lgd_village_name": "village"}
_CML_COUNT_NAME = {"records": "Applications", "applications": "Applications",
                   "sanctioned_records": "Sanctioned applications"}


def _cml_complete_list(question: str, answer: str, rows: list[dict]) -> str:
    if not rows or len(rows) < 2:
        return answer
    nums = _fp_numeric_cols(rows)
    if len(nums) != 1 or not (nums[0].endswith(("records", "applications")) or nums[0] == "n"
                              or "count" in nums[0]):
        return answer
    if _cme_complete_list(question, answer, rows) == answer:
        return answer
    met = nums[0]
    lab = next(k for k in rows[0] if k != met)
    if lab.startswith("financial_year"):
        return answer   # stored "2024-2025" is written "FY 2024-25" — not a missing row
    def _name(r: dict) -> str:
        if r.get(lab) is None:
            return "(not recorded)"
        t = _fp_title(r[lab])
        return t[9:].lstrip() if t.startswith("Meghalaya") and t[9:10].isspace() else t
    items = [f"{_name(r)} {_fmt_num(_as_number(r.get(met)))}" for r in rows if _as_number(r.get(met)) is not None]
    total = sum(_as_number(r.get(met)) or 0 for r in rows)
    listed = (f"{_CML_COUNT_NAME.get(met, _metric_label(met).capitalize())} by "
              f"{_CML_DIM_NAME.get(lab, lab.replace('_', ' '))} ({len(items)}): " + "; ".join(items)
              + f". Total {_fmt_num(total)}.")
    body = (answer or "").strip()
    cut = next((i for i in range(1, len(body)) if body[i].isspace() and body[i - 1] in ".!?"), len(body))
    head = body[:cut]
    logger.info("CM Elevate Legacy: rebuilt a %s list — figures were not beside their names", lab)
    return listed if not head or _CME_GARBLED.search(head) else f"{head}\n\n{listed}"


# When the composer is rejected twice, compose_response falls back to
# _deterministic_answer, which for one row reads "0.58 total disbursed cr." —
# correct digits, unusable wording. For CM Elevate Legacy that dump is replaced
# by a plain sentence naming the place and each figure with its unit.
def _cml_stem_cr(stem: str):
    """A key holding `stem`, then only word characters, then ending "_cr" ("total_subsidy_cr")."""
    def test(k: str) -> bool:
        if not k.endswith("_cr"):
            return False
        body = k[:-3]
        idx = body.find(stem)
        while idx >= 0:
            if all(ch.isalnum() or ch == "_" for ch in body[idx + len(stem):]):
                return True
            idx = body.find(stem, idx + 1)
        return False
    return test


_CML_FIGURE_WORDING = (
    (lambda k: k == "sanctioned_records", "{n} sanctioned applications"),
    (lambda k: k in ("records", "applications", "n"), "{n} applications"),
    (lambda k: k == "not_sanctioned_records", "{n} records with no sanctioned amount"),
    (_cml_stem_cr("subsid"), "₹{cr} crore disbursed as subsidy"),
    (_cml_stem_cr("loan"), "₹{cr} crore disbursed as loan"),
    (_cml_stem_cr("disburs"), "₹{cr} crore disbursed"),
    (_cml_stem_cr("sanction"), "₹{cr} crore sanctioned"),
    (lambda k: k.endswith("_pct"), "{v}%"),
)


def _cml_single_row_sentence(row: dict, display: dict) -> "str | None":
    parts = []
    for k, v in _row_metrics(row):
        tmpl = next((t for test, t in _CML_FIGURE_WORDING if test(k)), None)
        if tmpl is None:
            return None
        parts.append(tmpl.format(n=_fmt_num(v), cr=f"{float(v):.2f}", v=v))
    if not parts:
        return None
    key = next((k for k in ("village", "block", "constituency", "district") if display.get(k)), None)
    name = str(display[key]) if key else "All of Meghalaya"
    name = name.title() if name.isupper() else name
    place = name + (f" {key}" if key in ("village", "block", "constituency") and key not in name.lower() else "")
    yr = next((str(display[k]) for k in ("year", "financial_year") if display.get(k)), None)
    period = f"in {yr}" if yr else "across all financial years"
    return f"{place}: " + "; ".join(parts) + f" under CM Elevate Legacy {period}."


# A village breakdown (TC-34 shape) is one name column + its code + one count.
# Purakhasia (all-blocks run 2026-09-29): "ranging from 6 records at Rapangpanggiri
# down to 1 record at each of the other 13 villages. The village-level record
# counts are 6, 5, 3, 3, 3, 2, 1, … respectively" — a false claim (8 villages
# have 1), figures with no names, and the block's 30 records never stated.
_CML_EACH_OF_MATCH = Matcher(
    Cap(Alt(Pred(is_int), "one", Seq("a", "single", sep="space"))),
    W("record", "records", "application", "applications"), W("at", "in", "for"), "each", "of", "the",
    Opt(Cap(W("other", "remaining"))), Cap(Pred(is_int)), "villages", sep="space")


def _cml_village_breakdown(answer: str, rows: list[dict], display: dict) -> str:
    if len(rows or []) < 2:
        return answer
    name_col = next((k for k in rows[0] if k.endswith("village_name")), None)
    col = _cml_count_column(rows)
    if not name_col or not col:
        return answer
    body = [r for r in rows if not str(r.get(name_col) or "").upper().startswith("UNRESOLVED")]
    total = sum(_as_number(r.get(col)) or 0 for r in body)
    false_claim = False
    for m in _CML_EACH_OF_MATCH.finditer(answer or ""):
        v = 1 if not m.group(1).isdigit() else int(m.group(1))
        n = int(m.group(3))
        pool = body[1:] if m.group(2) else body     # "the other N" = all but the top row
        if sum(1 for r in pool if _as_number(r.get(col)) == v) != n or len(pool) != n and m.group(2):
            false_claim = True
    stated = {int(t.replace(",", "")) for t in numbers(answer or "", decimals=False)
              if t.replace(",", "").isdigit()}
    if not (_CME_GARBLED.search(answer or "") or false_claim) and total in stated:
        return answer
    place = next((str(display[k]) for k in ("block", "district", "constituency") if display.get(k)), "")
    place = place.title() if place.isupper() else place
    key = next((k for k in ("block", "district", "constituency") if display.get(k)), "")
    where = f" in {place}{' ' + key if key and key not in place.lower() else ''}" if place else ""
    head = f"{total:,} applications are mapped to {len(body)} villages{where}."
    if not (_CME_GARBLED.search(answer or "") or false_claim):
        logger.info("CM Elevate Legacy: village breakdown did not state its total — added")
        return f"{head} {answer}"
    shown = body[:40]
    items = "; ".join(f"{_fp_title(r[name_col])} {_fmt_num(_as_number(r.get(col)))}" for r in shown)
    more = f"; …and {len(body) - len(shown)} more in the table" if len(body) > len(shown) else ""
    logger.info("CM Elevate Legacy: village breakdown rebuilt (garbled list or false claim)")
    return f"{head}\n\nApplications by village ({len(body)}): {items}{more}."


def _cml_add_exact_after_crore(answer: str, cr: str, exact: str) -> str:
    """The first "₹<cr> crore" not already followed by "(₹" gets " (<exact>)" after it."""
    p = answer.find("₹")
    while p >= 0:
        j = p + 1
        if j < len(answer) and answer[j].isspace():
            j += 1
        if answer.startswith(cr, j):
            k = _cml_ws(answer, j + len(cr))
            if k >= 0 and answer.startswith("crore", k):
                e = k + 5
                if not answer.startswith("(₹", _cml_ws(answer, e, 0)):
                    return answer[:e] + f" ({exact})" + answer[e:]
        p = answer.find("₹", p + 1)
    return answer


def _cml_no_records_sentence(rows: list[dict], display: dict) -> "str | None":
    """One row whose figures are all empty (NULL sums, or a 0 count beside them):
    nothing is recorded for that place / year. Said plainly — never "the data
    available doesn't cover … the result is null" (Mahendraganj FY 2025-26, Legacy
    sheet re-test 2026-10-22, KI-383) and never "₹0", which would claim a recorded
    zero."""
    if len(rows or []) != 1:
        return None
    vals = list(rows[0].values())
    if not vals or not any(v is None for v in vals) or any(v is not None and _as_number(v) not in (0, None)
                                                          for v in vals):
        return None
    disp = display or {}
    key = next((k for k in ("village", "block", "constituency", "district") if disp.get(k)), None)
    place = str(disp[key]) if key else ""
    place = place.title() if place.isupper() else place
    noun = {"constituency": " assembly constituency", "block": " block", "village": " village"}.get(key or "", "")
    where = f" for {place}{noun if place and noun.strip() not in place.lower() else ''}" if place else ""
    year = f" in {disp['year']}" if disp.get("year") else ""
    return (f"No CM Elevate Legacy records are held{where}{year}, so there is no sanctioned or disbursed "
            "amount to report.")


async def _cm_legacy_answer_guarantees(question: str, sql: str, rows: list[dict], answer: str,
                                       display: dict) -> str:
    _none = _cml_no_records_sentence(rows, display)
    if _none:
        logger.info("CM Elevate Legacy: empty result — no-records sentence (KI-383)")
        return _none
    if len(rows or []) == 1 and _is_fallback_answer(answer, rows, ["CM Elevate Legacy"], display):
        answer = _cml_single_row_sentence(rows[0], display) or answer
    answer = _cml_complete_list(question, answer, rows)
    answer = _cml_village_breakdown(answer, rows, display)
    answer = _cml_fix_each_have_counts(answer, rows)
    answer = _cml_fix_place_spelling(answer, display, rows)
    found, exact = await _cml_exact_single_amount(sql, rows)
    replaced, hits = _cml_under_crore_sub(answer or "", _cml_inr(exact or 0)) if found else ("", 0)
    if found and hits:
        answer = replaced
        logger.info("CM Elevate Legacy: 'under ₹0.01 crore' replaced by the exact amount %s", exact)
    elif found and exact and _cml_inr(exact) not in answer:
        # "₹0.01 crore" -> "₹0.01 crore (₹1,25,000)": the crore figure stays, the exact one is added
        cr = next(f"{_as_number(v):.2f}" for k, v in rows[0].items() if k.endswith("_cr"))
        answer = _cml_add_exact_after_crore(answer, cr, _cml_inr(exact))
    unmapped = await _cml_unmapped_in_scope(sql)
    if unmapped and not _CML_NO_VILLAGE_SAID.search(answer or ""):
        key = next((k for k in ("block", "district", "constituency") if display.get(k)), None)
        place = str(display[key]) if key else ""
        place = place.title() if place.isupper() else place
        where = (f" in {place}" + (" block" if key == "block" and "block" not in place.lower() else "")
                 if place else "")
        answer = (answer.rstrip() + f" A further {unmapped:,} record{'s' if unmapped != 1 else ''}{where} "
                  f"{'have' if unmapped != 1 else 'has'} no village code, so "
                  f"{'they are' if unmapped != 1 else 'it is'} not in the village list "
                  "(counted in block and district totals).")
    return answer


# ════ answers ═════════════════════════════════════════════════════════════════════════════════════════
def _cm_legacy_small_money_notes(rows: list[dict]) -> list[str]:
    """A _cr value of 0.00 is a real amount under ₹0.5 lakh, not zero (TC-18:
    Sericulture spinning ₹26,000 was written as "₹0.00 crore")."""
    tiny = [r for r in rows or [] for k, v in r.items()
            if k.endswith("_cr") and _as_number(v) == 0]
    if not tiny:
        return []
    return ["A _cr value of 0.00 means under ₹0.01 crore (less than ₹1 lakh), not "
            "nothing — write it as 'under ₹0.01 crore', never '₹0.00 crore'."]


_CM_LEGACY_OFFER_OPENERS = ("would you like", "shall i", "do you want")


def _cm_legacy_drop_trailing_offer(text: str) -> str:
    """A closing "Would you like … ?" / "Shall I … ?" / "Do you want … ?" removed
    (the opener, then no '?' until the one '?' the text ends with)."""
    for p in range(len(text)):
        for op in _CM_LEGACY_OFFER_OPENERS:
            if text[p:p + len(op)].lower() != op:
                continue
            rest = text[p + len(op):]
            q = rest.find("?")
            if q >= 0 and not rest[q + 1:].strip():
                start = p
                while start and text[start - 1].isspace():
                    start -= 1
                return text[:start]
    return text


def _cm_legacy_style_block(question: str) -> str:
    """Two worked answers from the bank as WORDING examples for the composer.
    The trailing "Would you like…?" is dropped — the UI already offers next-step
    chips, and a second offer in the text would duplicate them."""
    shots = [a for a in annotations.answer_shots("CM Elevate Legacy", question, top_k=4)
             if a.get("rows")][:2]
    if not shots:
        return ""
    parts = []
    for a in shots:
        answer = _cm_legacy_drop_trailing_offer(" ".join(str(a["answer"]).split()))
        parts.append(f'Q: "{a["question"]}"\nColumns: {", ".join(a["columns"])}\n'
                     f"Rows: {json.dumps(a['rows'], ensure_ascii=False)}\nAnswer: {answer}")
    return ("\nWORDING EXAMPLES for this scheme — copy the style only. Their numbers "
            "belong to OTHER questions and must never appear in this answer:\n"
            + "\n\n".join(parts) + "\n")


# ════ villages ════════════════════════════════════════════════════════════════════════════════════════
_CML_BLOCKS: "list[str] | None" = None


_CML_VILLAGE_NAMES: "dict[str, list[dict]] | None" = None


async def _cm_legacy_village_names() -> "dict[str, list[dict]]":
    """UPPER(name) -> villages for every village in v_cm_elevate_disbursement."""
    global _CML_VILLAGE_NAMES
    if _CML_VILLAGE_NAMES is None:
        rows = await fetch_rows(
            "SELECT DISTINCT village_code, lgd_village_name, UPPER(lgd_block) AS block, "
            "UPPER(lgd_district) AS district FROM curated.v_cm_elevate_disbursement "
            "WHERE village_code IS NOT NULL AND village_code > 0 AND entity_type <> 'Unresolved'", [])
        out: dict[str, list[dict]] = {}
        for r in rows:
            n = collapse_ws(str(r["lgd_village_name"] or ""))
            if n and not n.lower().startswith("unresolved"):
                out.setdefault(n.upper(), []).append(
                    {"village_code": r["village_code"], "name": n, "block": r["block"], "district": r["district"]})
        _CML_VILLAGE_NAMES = out
    return _CML_VILLAGE_NAMES


# ════ SQL rewrites ════════════════════════════════════════════════════════════════════════════════════
# Client UAT sheet (FOCUS-018/019, 2026-09-13): "Give me the status breakdown
# for [tranche]" / "for [batch]" came back GROUP BY focus_status,
# verification_status even though schema_context.py rule 13 and the matching
# focusplus_few_shot.yaml examples both say an unqualified status breakdown
# means focus_status alone — verification_status is a near-constant single
# value ("Approved" on every 12.5K row) that only adds noise. The prose rule
# and the correctly-written few-shot examples exist and are scoped right; the
# generator still occasionally copies the two-column GROUP BY from the
# deliberately-different "what status values are recorded" enumeration
# example once a tranche/batch filter is also in play — the same class of
# prose-doesn't-reliably-win gap as _focusplus_single_district_beneficiary_guard
# above. Deterministic strip instead of a repair round trip, since the fix
# (drop one column) is unambiguous once the shape is detected.
# CM Elevate Legacy: the Unresolved-placeholder exclusion belongs ONLY on village
# counts and village lists (schema_context rule 9, geography_unresolved_rule).
# The 404 no-village records still have a known district, so a district / scheme
# / year total that drops them is simply wrong. Confirmed in the 2026-09-25
# use-case QA (TC-27, "total disbursement for each district"): the generator
# copied the filter from the village shots and returned ₹53.30 Cr statewide
# against a true ₹81.10 Cr. The rule is in the prompt; it does not reliably win,
# and the fix (delete one predicate) is unambiguous once the shape is detected.
def _cm_legacy_keep_unresolved_off_village(question: str, schemes: list[str], sql: str) -> str:
    if schemes not in _UNRESOLVED_PLACEHOLDER_SCHEMES or not sql or not _cml_has_unresolved_neq(sql):
        return sql
    if sql_ast.references_column(sql, "village_code", "lgd_village_name") \
            or _VILLAGE_WORD_MATCH.search(question or ""):
        return sql
    out = sql_ast.remove_conditions(sql, _cml_is_unresolved_neq)
    if out != sql:
        logger.info("%s: dropped entity_type <> 'Unresolved' from a non-village query — "
                    "the no-village records still count at district grain", schemes[0])
    return out


# CM Elevate Legacy constituency SQL joins curated.dim_geography for ac_name, and
# the view already carries every geography column dim_geography has
# (lgd_district, lgd_block, …). An unqualified one is then "ambiguous" to
# Postgres, and the repair loop kept re-emitting it until the budget ran out
# (TC-31 "applications mapped to Mairang constituency", 2026-09-25). The view's
# copy is always the intended one, so qualify bare references with its alias.
_CML_VIEWS = ("v_cm_elevate", "v_cm_elevate_disbursement")


def _cm_legacy_qualify_shared_geo_cols(schemes: list[str], sql: str) -> str:
    # CM Elevate (applications) joins dim_geography the same way for a
    # constituency since 2026-10-06 (_AC_CAPABLE_SCHEMES), with the same clash.
    if schemes not in (["CM Elevate Legacy"], ["CM Elevate"]) or not sql \
            or not any(isinstance(j.this, exp.Table) and j.this.name.lower() == "dim_geography"
                       for j in sql_ast.joins(sql)):
        return sql
    shared = {c.lower() for c in _SHARED_GEO_COLS}
    used: list[str] = []

    def fn(tree):
        # the view's alias in its FROM ("FROM curated.v_cm_elevate_disbursement v")
        alias = next((f.this.alias for f in tree.find_all(exp.From)
                      if isinstance(f.this, exp.Table) and f.this.name.lower() in _CML_VIEWS and f.this.alias), None)
        if not alias:
            return None
        used.append(alias)
        # Output aliases ("AS lgd_district") are not columns, and qualified refs are left alone.
        for c in list(tree.find_all(exp.Column)):
            if not c.table and c.name.lower() in shared:
                c.set("table", exp.to_identifier(alias))
        return None

    out = sql_ast.transform(sql, fn)
    if out != sql:
        logger.info("CM Elevate Legacy: qualified view geography columns with %r "
                    "(dim_geography join)", used[0])
    return out


# ── constituency questions (sheet TC-31 / TC-32, KI-381) ────────────────────────
# CM Elevate Legacy reaches the assembly constituency only through
# v_cm_elevate_disbursement.geography_key -> curated.dim_geography.ac_name, which is
# stored in Title Case ("Mahendraganj"). Sheet re-test 2026-10-22: 30-40 of 110
# constituency questions failed per run — the model filtered the constituency as a
# district (UPPER(lgd_district) = UPPER('DADENGGRE') -> "no data"), the repairs gave up
# ("couldn't build a working query"), and in a chat the filter was dropped and the
# statewide FY 2025-26 figures (137 records, ₹22.49 crore) were given as Mahendraganj's
# (true 0). The Focus Legacy twin is KI-369; the same guards, plus a rewrite.
_CML_VIEW_Q = "curated.v_cm_elevate_disbursement"
_CML_PLACE_COLS = ("lgd_district", "lgd_block", "lgd_village_name")


def _cml_resolved_ac(schemes: list[str], entity_result: dict) -> "str | None":
    ac = ((entity_result or {}).get("resolved") or {}).get("assembly_constituency")
    if schemes != ["CM Elevate Legacy"] or not isinstance(ac, str) or not ac.strip():
        return None
    return ac.strip().upper()


def _cm_legacy_ac_as_place_filter(schemes: list[str], entity_result: dict, sql: str) -> str:
    """The resolved constituency written as a district / block / village filter on a
    plain one-view query -> the documented join, `UPPER(g.ac_name) = '<AC>'`. Any other
    shape is left to the missing-filter guard (repair)."""
    ac = _cml_resolved_ac(schemes, entity_result)
    if not ac or not sql or not sql_ast.is_parseable(sql) or ac in _fl_ac_values(sql) \
            or sql_ast.has_cte(sql) or len(sql_ast.selects(sql)) != 1 or sql_ast.joins(sql) \
            or sql_ast.tables(sql, qualified=True) != {_CML_VIEW_Q}:
        return sql
    hits = [n for n in sql_ast.filter_conditions(sql, *_CML_PLACE_COLS)
            if {v.strip().upper() for v in sql_ast.filter_values(n, *_CML_PLACE_COLS)} == {ac}]
    if not hits:
        return sql

    def fn(tree):
        frm = tree.find(exp.From)
        if not isinstance(tree, exp.Select) or frm is None or not isinstance(frm.this, exp.Table):
            return None
        if any(c.table and c.table.lower() == "v_cm_elevate_disbursement" for c in tree.find_all(exp.Column)):
            return None          # qualified by the table name: an alias would break it
        alias = frm.this.alias
        if not alias:
            alias = "v"
            frm.this.set("alias", exp.TableAlias(this=exp.to_identifier(alias)))
        new = exp.EQ(this=exp.Upper(this=exp.column("ac_name", table="g")), expression=exp.Literal.string(ac))
        for node in sql_ast.filter_conditions(tree, *_CML_PLACE_COLS):
            if {v.strip().upper() for v in sql_ast.filter_values(node, *_CML_PLACE_COLS)} == {ac}:
                node.replace(new.copy())
        tree.join(f"{_CML_GEO_DIM} AS g", on=f"g.geography_key = {alias}.geography_key", copy=False)
        return None

    out = sql_ast.transform(sql, fn)
    if out != sql:
        logger.info("CM Elevate Legacy: constituency %s was filtered as a place column — rewritten to the "
                    "dim_geography ac_name join (KI-381)", ac)
    return out


_CML_GEO_DIM = "curated.dim_geography"


def _cm_legacy_ac_name_case(schemes: list[str], sql: str) -> str:
    """`ac_name = 'X'` -> `UPPER(ac_name) = 'X'` (dim_geography keeps Title Case);
    the Focus Legacy rewrite, for CM Elevate Legacy."""
    if schemes != ["CM Elevate Legacy"]:
        return sql
    return _focus_legacy_ac_name_case(["Focus Legacy"], sql)


def _cm_legacy_ac_filter_missing(schemes: list[str], entity_result: dict, sql: str) -> "str | None":
    """The repair instruction when a constituency was resolved but the query does not
    filter ac_name on it — it would report a district's (or the state's) figure as the
    constituency's. None otherwise."""
    ac = _cml_resolved_ac(schemes, entity_result)
    if not ac or not sql or not sql_ast.is_parseable(sql) or ac in _fl_ac_values(sql):
        return None
    return (f"the question is about the assembly constituency {ac} (a RESOLVED, MANDATORY filter), but "
            "this query does not filter on it, so it returns the figure of a district or of the whole "
            "state. A constituency is not a district or a block. Use exactly this shape: FROM "
            "curated.v_cm_elevate_disbursement v JOIN curated.dim_geography g ON g.geography_key = "
            f"v.geography_key WHERE UPPER(g.ac_name) = '{ac}', drop any lgd_district / lgd_block filter, and "
            "keep the measure, the year filter and the grouping exactly as they were.")


def _cm_legacy_ac_verifier_complaint_is_false(issue: str, schemes: list[str], entity_result: dict,
                                              sql: str) -> bool:
    """A verifier complaint about the join, the resolved constituency or the case of
    its literal, raised against the documented constituency query (KI-381). A
    complaint about the measure or the grain still stands."""
    ac = _cml_resolved_ac(schemes, entity_result)
    if not ac or not sql_ast.is_parseable(sql or "") \
            or not _FL_VERIFIER_JOIN_OR_ENTITY.search(issue or "") or _FL_VERIFIER_MEASURE.search(issue or ""):
        return False
    if sql_ast.tables(sql, qualified=True) != {_CML_VIEW_Q, _CML_GEO_DIM}:
        return False
    js = sql_ast.joins(sql)
    if not js or not all(j.args.get("on") is not None
                         and {c.name.lower() for c in j.args["on"].find_all(exp.Column)} == {"geography_key"}
                         for j in js):
        return False
    return ac in _fl_ac_values(sql)


# CM Elevate Legacy: "sanctioned applications" = COUNT(sanctioned_amount). 3 Any
# Business Venture records (marked Refused) carry no sanctioned amount, so
# COUNT(*) overstates it. The rule sat in schema_context (rule 2) and the
# few-shots, and still failed 5 of 5 live runs: "How many applications have been
# sanctioned?" ran SELECT COUNT(*) AS sanctioned_records and answered 2,823 against
# a true 2,820 (use-case re-test TC-14, 2026-09-29, KI-166). Fixed in the SQL.
_CML_SANCTION_WORD = W("sanction", "sanctioned")
_CML_SANCTION_COUNT_Q = Matcher(Alt(
    _CmeNear("how many", _CML_SANCTION_WORD, None), Seq("number", "of", _CML_SANCTION_WORD),
    Seq("sanctioned", Alt(W(*[f for w in ("application", "case", "record", "applicant", "entrepreneur", "unit")
                              for f in (w, w + "s")]),
                          Pred(lambda w: len(w) > 10 and w.lower().startswith("beneficiar"))), sep="space"),
    Seq("count", Opt("of"), _CML_SANCTION_WORD)))
_CML_SANCTION_STEM = W("sanction", prefix=True)
_CML_NOT_SANCTIONED_Q = Matcher(Alt(
    Seq(W("not", "never", "non", "un"), _CML_SANCTION_STEM),
    Pred(lambda w: w.lower().startswith(("notsanction", "neversanction", "nonsanction", "unsanction"))),
    W("desanction", prefix=True), Seq("without", Opt("a"), _CML_SANCTION_STEM)))


# COUNT(*) directly aliased as a sanctioned count; a not_ / non_ / un / de- alias
# (not_sanctioned_records, desanctioned) is a different measure and is left alone,
# and COUNT(*) FILTER (...) is not taken: its alias sits on the FILTER, not the COUNT.
def _cml_count_star_aliases(tree) -> list:
    return [a for a in tree.find_all(exp.Alias)
            if isinstance(a.this, exp.Count) and isinstance(a.this.this, exp.Star)]


def _cml_names_a_sanctioned_count(alias: str) -> bool:
    a = (alias or "").lower()
    head, sep, _ = a.partition("sanction")
    return bool(sep) and all(ch.isalpha() or ch == "_" for ch in head) \
        and not a.startswith(("not", "non", "un", "de"))


_CML_SANCTIONED_AMOUNT_Q = Matcher(Alt("sanctioned amount", "amount sanctioned"))
_CML_COUNT_WORDS_Q = Matcher(Alt("how many", "number of", "count"))


def _cm_legacy_sanctioned_count(question: str, schemes: list[str], sql: str) -> str:
    if schemes != ["CM Elevate Legacy"] or not sql:
        return sql
    q = question or ""
    if not _CML_SANCTION_COUNT_Q.search(q) or _CML_NOT_SANCTIONED_Q.search(q):
        return sql
    if _CML_SANCTIONED_AMOUNT_Q.search(q) and not _CML_COUNT_WORDS_Q.search(q):
        return sql
    def fn(tree):
        stars = _cml_count_star_aliases(tree)
        named = [a for a in stars if _cml_names_a_sanctioned_count(a.alias)]
        for a in named:
            a.this.set("this", exp.column("sanctioned_amount"))
        if named or any("sanction" in (i.name or "").lower() for i in tree.find_all(exp.Identifier)):
            return None
        # No sanction column anywhere: the only count is the sanctioned count the
        # question asked for ("SELECT COUNT(*) AS records ... " read as "N sanctioned").
        if len(stars) == 1:
            old = stars[0].alias
            stars[0].this.set("this", exp.column("sanctioned_amount"))
            stars[0].set("alias", exp.to_identifier("sanctioned_records"))
            # the old alias may be reused later (ORDER BY records DESC)
            for c in list(tree.find_all(exp.Column)):
                if not c.table and c.name == old:
                    c.set("this", exp.to_identifier("sanctioned_records"))
        return None

    out = sql_ast.transform(sql, fn)
    if out != sql:
        logger.info("CM Elevate Legacy: sanctioned count is COUNT(sanctioned_amount), not COUNT(*) (KI-166)")
    return out


# "Records that received / took / got a loan", "borrowers": schema rule 11 —
# a record took a loan only when total_loan_disbursement > 0. Grouping by lender
# without it counts every record of the year under its (often NULL) lender: the
# NL->SQL accuracy set found 1,626 "loan" records where 367 had a loan (2026-10-16).
_CML_LOAN_RECEIVED_Q = Matcher(Alt(
    Seq(W("received", "receive", "receives", "receiving", "took", "take", "taken", "taking", "got", "get",
          "availed", "avail", "availing", "sanctioned"), Opt(W("a", "any", "the")), W("loan", "loans")),
    Seq("with", Opt(W("a", "any")), W("loan", "loans")),
    W("borrower", "borrowers", "loanee", "loanees")))


def _cm_legacy_loan_received_filter(question: str, schemes: list[str], sql: str) -> str:
    """A COUNT of records that received a loan, with no loan filter -> add
    total_loan_disbursement > 0 (a SUM of loan money is unchanged by it)."""
    if schemes != ["CM Elevate Legacy"] or not sql or not _CML_LOAN_RECEIVED_Q.search(question or ""):
        return sql
    if not sql_ast.has_aggregate(sql, "count") \
            or sql_ast.filtered_by(sql, "total_loan_disbursement", "loan_disbursed_status"):
        return sql
    out = sql_ast.add_condition(sql, "total_loan_disbursement > 0")
    if out != sql:
        logger.info("CM Elevate Legacy: records that received a loan -> total_loan_disbursement > 0 (rule 11)")
    return out


# Accuracy gold bank wave 2 (2026-11-12, KI-721): "CM Elevate Legacy subsidy disbursed in West Garo Hills"
# then "and the loan?" (rewritten "How much loan was disbursed under CM Elevate Legacy in West Garo Hills?")
# was written `... AND loan_entity = 'Bank' AND total_loan_disbursement > 0`: ₹2.45 crore, the bank loans
# only, for the ₹4.84 crore disbursed as loans (Bank + LIFCOM). A lender filter the question never asked for
# is taken out; one it names ("bank loans", "through LIFCOM", "by lender") stays.
_CML_LENDER_WORDS = Matcher(Alt(W("bank", "banks", "banking", "lifcom", "lender", "lenders", "lending", "entity",
                                  "entities", "financier", "financiers", "institution", "institutions"),
                                Pred(lambda w: w.lower().startswith("lifcom"))))


def _cm_legacy_unasked_lender_filter(question: str, schemes: list[str], sql: str) -> str:
    if schemes != ["CM Elevate Legacy"] or not sql or not sql_ast.references_column(sql, "loan_entity")             or _CML_LENDER_WORDS.search(question or ""):
        return sql

    def on_lender(node: exp.Expression) -> bool:
        while isinstance(node, exp.Paren):
            node = node.this
        if not isinstance(node, (exp.EQ, exp.In, exp.NEQ, exp.Is, exp.Not)):
            return False
        cols = {c.name.lower() for c in node.find_all(exp.Column)}
        return cols == {"loan_entity"}

    out = sql_ast.remove_conditions(sql, on_lender)
    if out != sql:
        logger.info("CM Elevate Legacy: a lender filter the question never named was taken out (KI-721)")
    return out


# CM Elevate Legacy: a ranking over a small dimension cut by a LIMIT the question
# never asked for. "Which schemes have the highest number of applications?" ran
# ... ORDER BY records DESC LIMIT 10 in 4 of 5 live runs — 3 of the 13 schemes
# dropped — and the answer then called the 10th row the bottom of the range
# ("down to 33 records", true lowest Motorcaravan 1; TC-13, 2026-09-29, KI-168).
# The top-N pause (_needs_topn_clarification) only knows districts / blocks /
# villages, so a scheme ranking reaches the generator without a length. Without a
# stated count the whole list is returned (the executor's own cap still applies);
# a singular "which scheme has the most" keeps its LIMIT 1.
_CML_PLURAL_DIM_Q = Matcher(W("schemes", "districts", "blocks", "villages", "constituencies", "entities", "lenders",
                               "banks", "years", "sectors"))


# CM Elevate Legacy: a GROUP BY whose columns are not selected. "How many
# applications in CHIOKGRE village … across all financial years" ran
#   SELECT COUNT(*) AS records … WHERE village_code = 275499
#   GROUP BY COALESCE(financial_year_short, '(no financial year)') ORDER BY financial_year_short
# — invalid (ORDER BY an ungrouped column), and the repair model returned the same
# SQL 4 times: "couldn't build a working query" (final pass 2026-09-29). Unlabelled
# per-group counts can never be the answer, so the grouping (and its ORDER BY) is
# dropped and the single total asked for is returned.
def _cm_legacy_unselected_group_by(schemes: list[str], sql: str) -> str:
    # Focus Legacy too: "amount disbursed for Bangranggre" came back GROUP BY pg_id ORDER BY
    # amount DESC LIMIT 1 — one group's total, not the village's (Rs 40,000 of Rs 1,05,000);
    # an unselected GROUP BY financial_year_short split a count into unlabelled rows
    # (Focus Legacy all-villages run 2026-10-12).
    if schemes not in (["CM Elevate Legacy"], ["Focus Legacy"]) or not sql:
        return sql
    tree = _cml_simple_select(sql)
    if tree is None or tree.args.get("having") or not tree.args.get("group"):
        return sql
    cols = {c.name.lower() for c in tree.args["group"].find_all(exp.Column)}
    selected = {c.name.lower() for e in tree.expressions for c in e.find_all(exp.Column)} \
        | {e.alias.lower() for e in tree.expressions if isinstance(e, exp.Alias) and e.alias}
    if not cols or cols & selected:
        return sql
    tree.set("group", None)
    tree.set("order", None)
    logger.info("%s: dropped a GROUP BY on unselected %s", schemes[0], sorted(cols))
    return sql_ast.to_sql(tree)


# CM Elevate Legacy sheet TC-26 / TC-36 (testers: "The response should be in descending
# order"): "a district-wise summary of applications, sanctioned cases and total
# disbursement" came back ORDER BY total_disbursed_cr DESC. When applications are the first
# measure asked for, the rows are ranked by the application count (the roll-up row last).
_CML_MONEY_WORD = Matcher(Alt(W("disburs", "subsid", prefix=True), Seq("sanctioned", W("amount", prefix=True)),
                              W("loan", "loans", "amount")))
_CML_APPS_WORD = Matcher(W("application", "applications", "records", "cases"))
_CML_TOP_N_Q = Matcher(W("top", "bottom", "first", "last"), Pred(is_int), sep="space")


def _cm_legacy_order_by_records(question: str, schemes: list[str], sql: str) -> str:
    tree = sql_ast.parse_one(sql) if schemes == ["CM Elevate Legacy"] and sql else None
    if tree is None or not any((a.alias or "").lower() == "records" for a in tree.find_all(exp.Alias)):
        return sql
    q = question or ""
    m_apps = _CML_APPS_WORD.search(q)
    m_money = _CML_MONEY_WORD.search(q)
    if not m_apps or (m_money and m_money.start() < m_apps.start()):
        return sql
    if not sql_ast.has_group_by(tree):
        return sql
    holder = tree if tree.args.get("order") is not None else sql_ast.outer_select(tree)
    order = holder.args.get("order") if holder is not None else None
    if order is None or not order.expressions:
        return sql
    first = order.expressions[0]
    if _fl_col_name(first.this) == "records" and first.args.get("desc"):
        return sql
    g = next(order.find_all(exp.Grouping), None)
    keys = ([exp.Ordered(this=g.copy(), nulls_first=False)] if g is not None else []) \
        + [exp.Ordered(this=exp.column("records"), desc=True, nulls_first=True)]
    order.set("expressions", keys)
    logger.info("CM Elevate Legacy: ranked the breakdown by records (applications asked first)")
    return sql_ast.to_sql(tree)


# The money columns of v_cm_elevate_disbursement, all in RUPEES.
_CML_RUPEE_COLS = frozenset({
    "sanctioned_amount", "bank_sanctioned_amount", "total_disbursement", "total_loan_disbursement",
    "total_subsidy_disbursement", "loan_disbursement_1", "loan_disbursement_2", "loan_disbursement_3",
    "subsidy_disbursement_1", "subsidy_disbursement_2", "subsidy_disbursement_3"})


def _cm_legacy_crore_alias_on_rupees(schemes: list[str], sql: str) -> str:
    """An output column named in crore (…_cr / …_crore) over rupee columns with no
    ÷1e7 is divided, so the name is true: `SUM(sanctioned_amount) - SUM(total_disbursement)
    AS pending_cr` was answered "₹74,976,008.70 crore pending" for ₹7.50 crore (D-062 live
    check 2026-10-22, KI-375). Only the outer SELECT's own columns; a share or an average
    (a division already there) is left alone."""
    if schemes != ["CM Elevate Legacy"] or not sql:
        return sql
    tree = sql_ast.parse_one(sql)
    sel = sql_ast.outer_select(tree) if tree is not None else None
    if sel is None:
        return sql
    changed = []
    for e in sel.expressions:
        if not isinstance(e, exp.Alias) or not e.alias:
            continue
        low = e.alias.lower()
        if not any(low == s or low.endswith("_" + s) for s in _PMAY_CRORE_SUFFIXES):
            continue
        cols = {(c.name or "").lower() for c in e.this.find_all(exp.Column)}
        if not cols or not cols <= _CML_RUPEE_COLS or e.this.find(exp.Div, exp.Mul, exp.Avg, exp.Count):
            continue
        inner = e.this.this if isinstance(e.this, exp.Round) else e.this
        e.set("this", sql_ast.parse_one(f"SELECT ROUND(({sql_ast.to_sql(inner)}) / 1e7, 2)").expressions[0])
        changed.append(e.alias)
    if not changed:
        return sql
    logger.info("CM Elevate Legacy: rupee columns named in crore divided by 1e7 (KI-375): %s", changed)
    return sql_ast.to_sql(tree)


def _cm_legacy_unrequested_limit(question: str, schemes: list[str], sql: str) -> str:
    if schemes != ["CM Elevate Legacy"] or not sql:
        return sql
    tree = sql_ast.parse_one(sql)
    n = sql_ast.outer_limit(tree) if tree is not None else None
    holder = (tree if tree is not None and tree.args.get("limit") is not None
              else sql_ast.outer_select(tree) if tree is not None else None)
    if n is None or n < 0 or holder is None or holder.args.get("offset") is not None \
            or not sql_ast.has_group_by(tree):
        return sql
    q = question or ""
    if _EXPLICIT_COUNT.search(q) or _CML_TOP_N_Q.search(q):
        return sql
    if n == 1 and not _CML_PLURAL_DIM_Q.search(q):
        return sql
    logger.info("CM Elevate Legacy: dropped an unrequested LIMIT %d from a grouped result (KI-168)", n)
    return sql_ast.set_limit(sql, None)

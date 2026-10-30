# app/pipeline/common/c13_compose_and_data_stages.py — compose, intent, data stages, answer_question, charts, follow-ups.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
#
# SQL text is read here only through SQLGlot (app/sql_ast.py: tree / token
# stream), never by text matching; the word matchers below read questions
# and answers (English), not SQL.
from app import measure_kinds, sql_ast
from sqlglot import exp


# schemes whose one-figure answers must state THAT figure (see compose_response)
_ONE_FIGURE_SCHEMES = (["Focus Plus"], ["CM Elevate"])


def _money_rounded_for_display(rows: list[dict]) -> list[dict]:
    """The rows with crore / lakh money columns (by the SQL-prompt suffix:
    _unit_suffix) rounded to 2 decimals, for the composer's eyes only (KI-417)."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            out.append(r)
            continue
        nr = {}
        for k, v in r.items():
            unit = _unit_suffix(str(k).lower())
            n = _as_number(v) if unit and unit[1] in ("crore", "lakh") else None
            nr[k] = round(n, 2) if isinstance(n, float) else v
        out.append(nr)
    return out


async def compose_response(question: str, sql: str, rows: list[dict],
                           notes: list[str] | None = None,
                           entities: dict[str, str] | None = None,
                           schemes: list[str] | None = None,
                           style_examples: str = "",
                           extra_numbers: "set[str] | None" = None) -> str:
    # extra_numbers: figures a caller re-queried and handed over in a note (a
    # list's true total), which the answer may quote although no row holds
    # them. None for every caller that doesn't pass it — unchanged behaviour.
    # style_examples: optional worked answers for the scheme (CM Elevate
    # Legacy's answer shots). Empty for every other scheme, which leaves the
    # prompt exactly as it was.
    if not rows:
        return _no_data_answer(schemes, entities)
    # "Which district had the most …": the winner and the next two, written by code
    # from the rows (data-accuracy brief D3, 2026-10-29; the SQL reads LIMIT 3).
    _runners_up = _c17_runners_up_answer(question, sql, rows, schemes, entities)
    if _runners_up:
        return _runners_up
    preview = rows[:40]
    truncated = len(rows) > len(preview)
    # "No usable value" — every numeric cell is 0 or null (rows is non-empty
    # here; a truly empty result returns via _no_data_answer above). This is
    # the shape a metric the data simply doesn't track comes back as; when we
    # see it, hand the composer the real metric list so it can tell the user
    # exactly what IS available rather than a vague "not covered".
    _nums = [n for r in rows for _k, n in _row_metrics(r)]
    # An aggregate that matched NOTHING comes back as one row of NULLs, not as
    # zero rows, so the `if not rows` guard above cannot catch it. _row_metrics
    # drops NULL cells (they are not numbers), which left _nums empty and this
    # test False — the composer then received a row whose only value was None
    # and reported "the membership count is null", as if the database held a
    # null for that group rather than nothing having matched the filters
    # (reported 2026-09-22, "members in Sakania Producer Group"). Detect the
    # all-NULL row explicitly.
    _all_null = bool(rows) and not _nums and all(
        v is None for r in rows for v in r.values()
    )
    no_usable_value = (bool(_nums) and all(n in (0, None) for n in _nums)) or _all_null
    metrics_block = ""
    if no_usable_value:
        metrics_block = (
            "\nMetrics the data DOES carry — if the question asked for something "
            "that is not in this list, say plainly it isn't tracked in the "
            "available scheme data, then name what is:\n"
            + available_metrics_text(schemes or []) + "\n"
        )
    # A metric the schema simply doesn't carry comes back as no rows, or as a
    # single 0 / NULL. Tell the composer to say that plainly instead of
    # reporting a confident "0" the user will read as a real measurement.
    guidance = (
        "If the result contains a number that answers the question, state it "
        "plainly as the answer — a nonzero COUNT is exactly the count that was "
        "asked for; never reply that the data 'doesn't cover' a metric the query "
        "just counted. ONLY when the result is empty, or the value is 0 or null, "
        "do NOT assert a real count of zero — instead say the data available "
        "doesn't cover that metric for the scheme/area asked, and name what IS "
        "available if you can tell from the query. Never describe a column the "
        "query didn't select. Copy every number digit-for-digit from the result "
        "JSON or the whole-result summary — do not shorten, round or reformat it "
        "(adding thousands separators is fine). If a Context note below says the "
        "question assumed a figure the data contradicts, correct that figure in "
        "your first sentence and answer from the real value — never echo the "
        "user's assumed number as if it were right. Make that first sentence ONE "
        "clean clause naming the real figure (e.g. 'Tranche 1 shows 0 beneficiaries, "
        "not the 4 the question assumes.') — never a reasoning trail like 'contradicting "
        "the assumed figure of X, so Y cannot be calculated because Z is empty'. Put "
        "the supporting figures in a separate, plainly listed second sentence (e.g. "
        "'Tranches 2, 3 and 4 each had 93,286 beneficiaries, out of 373,144 total.') "
        "rather than chaining them onto the correction with 'The available figures "
        "are...'. If the result is a list of "
        "names or rows and carries no numeric column, that list IS the answer — "
        "it is the exact set the query already selected as matching the question "
        "(e.g. 'which districts have both schemes'). Name those values as the "
        "answer; never say the data 'only lists names' or lacks the detail to "
        "decide — the filtering happened in the query. Never state or imply a "
        "scope the query wasn't actually filtered to — a specific tranche, year, "
        "district, block, village or category — unless it appears in the Entity "
        "names block below or literally in the question; if the question and the "
        "Entity names block name no tranche/year/area, the result covers all of "
        "them and must be described that way (e.g. 'across all tranches'), not "
        "attributed to one you're not told about."
    )
    # For any multi-row result, hand the composer a deterministic summary built
    # from EVERY row — totals, mean, extremes, full dimension coverage — so its
    # answer matches the charts/table instead of describing only the ~40 rows it
    # can see. Also stops it declaring that rows it can't see "have no data".
    digest_text, digest_nums = _result_digest(rows, with_mean=bool(_ASKS_AVERAGE.search(question or "")))
    summary_block = ""
    if digest_text:
        warn = ""
        if truncated:
            warn = (
                f" Only the first {len(preview)} of {len(rows)} rows appear below; "
                "do NOT say any district, block, village, year or category is "
                "missing or has no data merely because it is absent from them."
            )
        summary_block = (
            "\nWhole-result summary — computed from EVERY row. Use THESE figures "
            "for any total, average, highest/lowest or coverage statement; they "
            "are authoritative even though only some rows are shown below." + warn
            + "\n" + digest_text + "\n"
        )
    notes_block = ""
    if notes:
        notes_block = "\nContext (question premises to reconcile against the data — " \
                      "correct any the result contradicts):\n" + \
                      "\n".join(f"  - {n}" for n in notes) + "\n"
    names_block = _entity_names_block(entities)
    # The answer takes the question's shape — a ranked list for "top 5", the verdict
    # for a comparison, first-to-last for a trend (user report 2026-10-22: "if I ask
    # top 10, top 5 or compare … you need to give different answers"). The shape is
    # read from the SQL tree and the rows, and the figures it needs are computed here
    # so the composer only words them (c12_answer_shapes.py).
    # A ROLLUP's total row is the query's exact total, never one more category
    # ("ALL DISTRICTS" read as a 13th district, Legacy sheet TC-36, KI-384).
    _shape_rows, _total_rows = _c12s_rollup_split(sql, rows)
    shape = _answer_shape(question, sql, _shape_rows)
    if shape is not None and shape.kind == "breakdown":
        # a split has no order of its own: the composer listed it in the query's order
        # although told "largest first" (live 2026-10-22). The table keeps `rows` as is.
        preview = (_breakdown_preview(_shape_rows, shape)[:40] + _total_rows)
    shape_block = _shape_guide_block(shape)
    facts_text, facts_nums = _shape_facts(shape, _shape_rows)
    if _total_rows and shape is not None:
        facts_text = (facts_text + "\n" if facts_text else "") + "\n".join(
            "  the query's own TOTAL row (not a category; use it for the overall total): "
            + ", ".join(f"{k} = {v}" for k, v in r.items()) for r in _total_rows)
    facts_block = ""
    if facts_text:
        facts_block = (
            "\nDerived figures — computed by code from EVERY row. Use THESE for any gap, "
            "difference, % change, ratio or share; never work one out yourself.\n" + facts_text + "\n"
        )
    if shape is not None:
        logger.info("compose_response: answer shape %s (metric %s, %d row(s))", shape.kind, shape.metric, len(rows))
    # E9 (2026-10-29): a ranking / comparison / trend / split takes every figure-bearing
    # line from code's templates (_c12s_e9_body) and only its opening line, which holds no
    # figure, from the composer (composer audit 2026-10-27: the multi-row shapes carried
    # the wrong gaps and the unasked lines). Left to the composer: a premise correction
    # (premise_check's "The question treats …" note) and a caller's own figures — they
    # need reconciling in words — a ROLLUP total row, and a result with no usable value.
    # Other notes are wording advice ("write lakh", "name places in plain words"): the
    # opening line gets them, and code's figures already follow them (live E9 check
    # 2026-10-29: every MGNREGA list carries one, which kept the templates off). A
    # scheme's style shots do not keep the composer either (CM Elevate Legacy's district
    # split misquoted twice on the composer path, same check).
    _premise_notes = [n for n in (notes or []) if str(n).startswith('The question treats "')]
    if settings.ANSWER_TEMPLATES_ENABLED and not (_premise_notes or extra_numbers or no_usable_value or _total_rows):
        _body = _c12s_e9_body(shape, _shape_rows, question)
        if _body:
            logger.info("compose_response: templated %s answer (metric %s)", shape.kind, shape.metric)
            _frame = await _c12s_e9_framing(question, shape, _shape_rows, sql, schemes, entities,
                                            names_block + notes_block)
            return _finish_answer(f"{_frame}\n{_body}", rows, schemes, entities)
    if shape is None or shape.kind == "single_value":
        opening = """Answer the user's question in one to three plain sentences, using ONLY the
numbers in the result and the whole-result summary below — do not invent or round
differently than shown. Write like a direct briefing: lead with the fact or figure
itself, not with "The data shows..." or a description of what the query returned.
The first sentence must say what the figure counts in plain words, for which scheme,
which area and which period."""
    else:
        opening = """Answer the user's question in the shape given under "Answer shape" below, using
ONLY the numbers in the result, the whole-result summary and the derived figures below —
do not invent, compute or round differently than shown. Write like a direct briefing:
lead with the answer itself, not with "The data shows..." or a description of what the
query returned. Say once, in plain words, what the figures count, for which scheme,
which area and which period."""
    # Money in crore / lakh is shown to the composer at 2 decimals (KI-417): the raw
    # SUM(amount) / 1e7 came through as "119.73925 crore" because the prompt says not to
    # round differently than shown. Display only — `rows`, the table and the export keep
    # the exact value, and the number check already accepts the 2-decimal form.
    preview = _money_rounded_for_display(preview)
    prompt = f"""{opening} The period is the year the query read: the year in
the Entity names block below when it gives one; say "across all financial years"
only when that block names no year. Write every number with thousands separators (27,264,054, never 27264054).
Keep each sentence to one idea — short and declarative, not a chain of clauses
joined by "so" / "as" / "which means".
{guidance}
{shape_block}{metrics_block}{names_block}{summary_block}{facts_block}{notes_block}{style_examples}
Question: "{question}"
Result ({len(rows)} row(s), showing up to {len(preview)}):
{json.dumps(preview, default=str)}

Answer:"""
    context_budget.log_prompt_context("compose", [
        ("guidance", guidance), ("available_metrics", metrics_block),
        ("entity_names", names_block), ("result_summary", summary_block),
        ("answer_shape", shape_block), ("derived_figures", facts_block),
        ("premise_notes", notes_block), ("style_examples", style_examples),
        ("question", question), ("result_rows", json.dumps(preview, default=str)),
    ], prompt=prompt, rows=len(rows), rows_shown=len(preview))
    answer = await llm.call_response_composer(prompt)

    data_nums = _data_numbers(preview) | digest_nums | facts_nums | set(extra_numbers or ())
    # A note may ask the composer to name the figure the question wrongly assumed
    # ("not the 1.71 L assumed…") — allow those premise numbers through the
    # faithfulness check so the correction itself isn't flagged as a misquote.
    if notes:
        for _p in premise_check.extract_premises(question):
            data_nums.add(f"{_p.value:g}")
            data_nums.add(keep_chars(_p.text, lambda ch: ch.isdecimal() or ch == ".") or f"{_p.value:g}")
    # "households completed 100 days" — the 100 is the MGNREGA measure's NAME,
    # not a figure. Every correct sentence about it ("3.39% of households
    # completed 100 days") was flagged as a misquote and replaced by the
    # row-dump fallback "3.39 completion 100 day pct." (MGNREGA QA 2026-09-26,
    # DATA-009/020). Allowed only when the question itself asks about it.
    if schemes and "MGNREGA" in schemes and _C13_HUNDRED_DAYS.search(question or ""):
        data_nums.add("100")
    data_nums |= _sql_literal_numbers(sql)
    data_nums |= set(_CHIP_LGD_CODE_MATCH.findall(question or ""))   # a twin-village chip's own code
    answer = _fix_digit_grouping(answer, data_nums)
    if schemes in _ONE_FIGURE_SCHEMES and schemes == ["CM Elevate"]:
        # spelled-out figures ("Five applicants") become digits BEFORE the checks, so a
        # wrong one leaves the true figure missing and is caught below (2026-09-28)
        answer = _cme_digits_for_number_words(answer, preview)
    misquoted = bool(data_nums) and not _answer_numbers_faithful(answer, data_nums)
    # E9 (2026-10-29): a figure that exists in the result but sits beside the wrong row
    # name, measure or unit ("11.10 crore more than LIFCOM", CL-05; a % as "lakh", MG-10).
    misbound = [] if misquoted else _c12_label_misbinds(answer, rows, data_nums)
    # A single aggregate row with 2+ metrics (e.g. a cross-scheme MGNREGA + PMAY
    # count) — the answer must report every one, not just the first scheme.
    dropped_metric = (len(preview) == 1 and len(_row_metrics(preview[0])) >= 2
                      and not _answer_covers_metrics(answer, preview[0]))
    # Focus Plus: a one-figure answer must state THAT figure. The check above
    # ignores whole numbers under 100 (ordinals, "one or two"), so "There is 1
    # beneficiary" for a result of 11 passed (NONGLANG, all-villages run
    # 2026-09-27). Numbers equal to 0 are left to the zero / no-data wording.
    # CM Elevate joined 2026-09-28 (all-blocks smoke run: "There is 1 pending CM
    # ELEVATE application in Ranikor block" for a result of 12).
    if schemes in _ONE_FIGURE_SCHEMES and not dropped_metric and len(preview) == 1:
        _one = _row_metrics(preview[0])
        if len(_one) == 1 and _one[0][1] not in (0, None) and not _answer_covers_metrics(answer, preview[0]):
            dropped_metric = True

    if misquoted or dropped_metric or misbound:
        why = ("MISQUOTED a number" if misquoted else
               "put a figure next to the wrong label (" + "; ".join(misbound) + ")" if misbound else
               "left out one of the result values")
        logger.warning("compose_response: answer %s (%r) — strict retry", why, answer[:160])
        if len(preview) == 1:
            allowed = "; ".join(f"{k} = {v}" for k, v in preview[0].items())
        else:
            allowed = ", ".join(sorted(data_nums, key=len, reverse=True))
        strict_prompt = (
            prompt + "\n" + answer.strip() +
            f"\n\nThat answer {why}. State EVERY value in the result, each labelled with what "
            "it measures, digit-for-digit (thousands separators allowed). The values are:\n  "
            + allowed + "\nRewrite the answer now.\n\nAnswer:"
        )
        answer = _fix_digit_grouping(await llm.call_response_composer(strict_prompt), data_nums)
        still_bad = (bool(data_nums) and not _answer_numbers_faithful(answer, data_nums)) or bool(
            _c12_label_misbinds(answer, rows, data_nums)) or (
            len(preview) == 1 and len(_row_metrics(preview[0])) >= 2
            and not _answer_covers_metrics(answer, preview[0])) or (
            # the Focus Plus one-figure rule above, re-applied to the retry
            schemes in _ONE_FIGURE_SCHEMES and len(preview) == 1 and len(_row_metrics(preview[0])) == 1
            and _row_metrics(preview[0])[0][1] not in (0, None)
            and not _answer_covers_metrics(answer, preview[0]))
        if still_bad:
            logger.warning("compose_response: retry still wrong — using deterministic answer")
            # in the question's shape when it has one (a ranked list, a comparison …)
            answer = (_shaped_fallback(shape, _shape_rows, schemes, entities, question)
                      or _framed_fallback(rows if len(rows) > 1 else preview, schemes, entities))

    # Deterministic safety net for the opposite failure: the query DID return a
    # real, non-zero number, but the composer hedged with a "not covered / no
    # data / can't break it down" phrasing anyway (seen when the question names
    # two categories joined by "or" and the query returns their combined COUNT).
    # A usable number must be reported as the answer.
    if _HEDGE_MATCH.search(answer):
        metrics_now = _row_metrics(preview[0]) if len(preview) == 1 else []
        if metrics_now and all(v not in (0, None) for _k, v in metrics_now):
            logger.warning("compose_response: hedged over a real value %r — deterministic answer",
                           answer[:160])
            answer = _framed_fallback(preview, schemes, entities)
        elif _is_plain_list_result(rows):
            logger.warning("compose_response: hedged over a %d-row list result %r — "
                           "deterministic list answer", len(rows), answer[:160])
            answer = _deterministic_list_answer(rows)
        elif len(preview) >= 2 and any(
            v not in (0, None) for r in preview for _k, v in _row_metrics(r)
        ):
            # A multi-row breakdown (e.g. GROUP BY category, COUNT(*)) that
            # carries at least one real, non-zero metric — neither of the two
            # branches above catches this shape (not a single row, and
            # _is_plain_list_result excludes rows with numeric metrics), so a
            # composer hedge here used to slip through unchecked while the
            # chart/table built from the same rows showed real data.
            logger.warning("compose_response: hedged over a %d-row breakdown %r — "
                           "deterministic answer", len(preview), answer[:160])
            answer = _shaped_fallback(shape, _shape_rows, schemes, entities, question) or _framed_fallback(rows, schemes, entities)
    # A list answer must state the list's true size: "Ten villages in the
    # Dadenggre constituency received employment" for 135 villages, and the
    # fallback's "Here are the 40 results" for 114 (it was handed only the
    # 40-row preview) — MGNREGA sheet DATA-014, run 2026-10-09. A spelled-out
    # count escapes the digit faithfulness check above.
    # Rows of several schemes (one query per scheme) are one list per scheme:
    # "the top 10 villages" of each is right for 20 rows (D-062, 2026-10-22).
    _per_scheme_sizes = {len([r for r in rows if r.get("scheme") == s]) for s in {r.get("scheme") for r in rows}}
    if len(rows) > 1 and all(_states_wrong_list_count(answer, n)
                             for n in {len(rows), len(_shape_rows)} | _per_scheme_sizes):
        logger.warning("compose_response: answer states a list size other than %d — deterministic answer",
                       len(rows))
        answer = _shaped_fallback(shape, _shape_rows, schemes, entities, question) or _framed_fallback(rows, schemes, entities)
    answer = _c12s_fix_trend_direction(answer, shape, _shape_rows)   # KI-441
    answer = _cme_level_pending_wording(question, schemes, answer)  # KI-422
    answer = _fp_cohort_zero_answer(question, schemes, rows, answer)  # KI-365
    # Every data answer reads as a briefing line: result figures grouped, and the
    # scheme / area named at least once (user report 2026-10-18: "1,494,437
    # household years." was the whole answer).
    return _finish_answer(answer, rows, schemes, entities)


_C13_HUNDRED_DAYS = Matcher(Alt(
    Seq(W("100"), _C1xGapIs(W("day", "days"), _c1x_ws_or_dash0)), W("100day", "100days"),
    Seq("hundred", W("day", "days"), sep="space"),
))
_LIST_NOUNS = W("village", "villages", "block", "blocks", "district", "districts", "constituency",
                "constituencies", "result", "results", "record", "records", "row", "rows", "entries",
                "group", "groups", "beneficiary", "beneficiaries")
_LIST_COUNT_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}


class _C13DigitNumber(_C1xNode):
    r"""A number written with digits and commas ("1,234"): a digit word, then more
    digit words joined by commas only (a digit, then digits and commas)."""

    def ends(self, ctx, i, caps):
        n = len(ctx.toks)
        if i >= n or not ctx.toks[i].raw.isdecimal():
            return
        j = i + 1
        while j < n and ctx.toks[j].raw.isdecimal():
            gap = ctx.text[ctx.toks[j - 1].end:ctx.toks[j].start]
            if not (gap and set(gap) == {","}):
                break
            j += 1
        yield j, caps


def _c13_comma_ws(gap: str) -> bool:
    r"""Any commas a digit number may trail, then one or more spaces."""
    return _c1x_ws(gap.lstrip(","))


_C13_ANY_WORDS_0_2 = _C1xRun(lambda w: True, 1, 2, gap_ok=_c1x_ws)
# group 1: the count ("135" / "ten"), then up to two words, then a list noun
_LIST_COUNT_MATCH = Matcher(Alt(
    Seq(Cap(_C13DigitNumber()), Alt(_C1xGapIs(_LIST_NOUNS, _c13_comma_ws),
                                    Seq(_C1xGapIs(_C13_ANY_WORDS_0_2, _c13_comma_ws), _C1xGapIs(_LIST_NOUNS, _c1x_ws)))),
    Seq(Cap(W(*_LIST_COUNT_WORDS)), _C1xRun(lambda w: True, 0, 2, gap_ok=_c1x_ws, first_gap_ok=_c1x_ws),
        _C1xGapIs(_LIST_NOUNS, _c1x_ws)),
))
# The two Cap()s above are two alternatives of ONE group: read whichever is set.
_C13_SUBSET_WORDS = frozenset(("top first last bottom leading largest highest lowest best worst "
                               "other remaining only another these those").split())


def _c13_subset_lead_spans(text: str) -> list:
    r"""The text ENDS with one of these whole words (top … those), then only
    whitespace."""
    toks = _c1x_tokens(text)
    if not toks:
        return []
    last = toks[-1]
    if last.low in _C13_SUBSET_WORDS and text[last.end:].strip() == "":
        return [(last.start, len(text))]
    return []


_SUBSET_LEAD_MATCH = _C1xScan(_c13_subset_lead_spans)


def _states_wrong_list_count(answer: str, n: int) -> bool:
    """True when the answer gives the number of items in the list as anything
    other than n ("Ten villages…", "Here are the 40 results" for 135 rows)."""
    for m in _LIST_COUNT_MATCH.finditer(answer or ""):
        if _SUBSET_LEAD_MATCH.search((answer or "")[max(0, m.start() - 16):m.start()]):
            continue                         # "the top 5 districts" names a subset, not the list
        tok = (m.group(1) or m.group(2)).lower().replace(",", "")
        val = _LIST_COUNT_WORDS.get(tok, None) if not tok.isdigit() else int(tok)
        if val is not None and val != n and val < n:
            return True
    return False


_CONTACT_INFO_CUE = Matcher(Alt(
    Joined("help", "line"), Joined("toll", "free"), W("grievance", "grievances"),
    Seq("complaint", W("number", "cell", "portal"), sep="space"),
    Seq(W("phone", "contact", "telephone"), W("number", "no", "details"), sep="space"),
    Seq(Alt(W("email"), Seq(W("e"), _C1xGapIs(W("mail"), lambda g: g == "-"))),
        _C1xGapIs(W("id", "address"), _c1x_ws)),
))


class _C13PlaceWords(_C1xNode):
    r"""1..5 place words separated by whitespace, each starting with a letter and
    made of letters, digits, '_' and . ' ( ) - (one word, then up to four more,
    each after one or more spaces). Every split is offered."""

    def ends(self, ctx, i, caps):
        n = len(ctx.toks)
        chunks, j = 0, i
        while j < n:
            t = ctx.toks[j]
            if not (t.raw[0].isascii() and t.raw[0].isalpha()):
                return
            if j > i and not _c1x_ws(ctx.text[ctx.toks[j - 1].end:t.start]):
                return
            # an in-word joint (. ' ( ) -) keeps the chunk going
            k = j + 1
            while k < n:
                gap = ctx.text[ctx.toks[k - 1].end:ctx.toks[k].start]
                if gap and all(ch in ".'()-" for ch in gap):
                    k += 1
                else:
                    break
            chunks += 1
            if chunks > 5:
                return
            yield k, caps
            j = k


_MEASURE_IN_PLACE = Matcher(Seq(
    Alt(W("record", "records", "application", "applications", "applicant", "applicants", "house", "houses",
          "household", "households", "member", "members", "pg", "pgs", "expenditure"),
        W("beneficiar", "amount", "disburs", "sanction", prefix=True),
        Joined("person", ("day", "days")),
        Seq("job", W("card", "cards"), sep="space"), Seq("producer", W("group", "groups"), sep="space")),
    _C1xRun(lambda w: True, 0, 4, gap_ok=_c1x_ws, first_gap_ok=_c1x_ws),
    _C1xGapIs(W("in", "for", "of", "at", "under"), _c1x_ws),
    _C1xGapIs(_C13PlaceWords(), _c1x_ws),
    _C1xGapIs(W("block", "village", "district", "constituency"), _c1x_ws),
))


_C13_COUNT_ASKED = Matcher(Seq("how", W("many", "much"), sep="space"))


async def classify_intent(question: str, session: "Session | None" = None) -> str:
    """DATA (a number from megh_db) vs KNOWLEDGE (how the scheme works, from the
    reference docs). Keyword fast-path first; one classifier call otherwise (or
    this turn's query plan, D-085); then the B3 retrieval-score safety net
    (_c13_knowledge_is_closer)."""
    intent = await _c13_intent_by_rules(question, session)
    if intent == "DATA" and settings.INTENT_SCORE_TIEBREAK and _c13_b3_eligible(question) \
            and await _c13_knowledge_is_closer(question):
        return "KNOWLEDGE"
    return intent


# B3 (RAG plan; measured 2026-10-27, tests/intent_scores/run_eval.py, 70 labelled
# questions): "How many days of work does MGNREGA guarantee?" and "Can a woman apply
# for a job card?" were routed DATA by the "how many" / "job card" cues. Their nearest
# megh_knowledge passage beats their nearest worked data example (megh_sql_metadata)
# by 0.175 and 0.221; every real data question in the set has the example ahead by
# +0.021 or more. Scores ALONE route worse than the rules (57/70 vs 67/70), so they
# only overturn a DATA verdict, only for a question with no place, year, ranking or
# breakdown of its own (those are figures; they also skip the extra embedding call),
# and only by a clear margin.
_C13_B3_MARGIN = 0.10


def _c13_b3_eligible(question: str) -> bool:
    q = question or ""
    if context_policy.extract_year_keys(q) or _RANKING_CUE.search(q) or _HAS_BREAKDOWN.search(q) \
            or _BREAKDOWN_CUE.search(q):
        return False
    # "statewide" / "all financial years" is a figure's scope too: "Average FOCUS+ amount per
    # beneficiary statewide, all financial years" was overturned to the documents (live,
    # RAG fix report Issue 12 re-check, 2026-10-29)
    if _EXPLICIT_STATEWIDE.search(q) or _ALL_YEARS_CUE.search(q):
        return False
    try:
        from app.entity_resolver import place_mentions as _c13_pm
        return not _c13_pm(q)
    except Exception:  # noqa: BLE001 — no place index: no override
        return False


async def _c13_knowledge_is_closer(question: str) -> bool:
    """The best megh_knowledge passage is ahead of the best worked data example by
    _C13_B3_MARGIN or more. Any failure: False (the rules' DATA stands)."""
    try:
        from qdrant_client import models as _c13_qm
        from app import vectorstore as _c13_vs
        vec = (await llm.call_embedding([question]))[0]
        kb = await _c13_vs.search(vec, 1)
        flt = _c13_qm.Filter(must=[_c13_qm.FieldCondition(key="kind", match=_c13_qm.MatchValue(value="example"))])
        ex = await _c13_vs.get_client().query_points(
            collection_name=settings.SQL_EXAMPLES_COLLECTION, query=vec, query_filter=flt, limit=1,
            with_payload=False)
        kb_s = kb[0]["score"] if kb else 0.0
        ex_s = ex.points[0].score if ex.points else 1.0
    except Exception:  # noqa: BLE001
        logger.debug("classify_intent: B3 score check failed — rules' DATA stands", exc_info=True)
        return False
    closer = kb_s - ex_s >= _C13_B3_MARGIN
    context_budget.log_decision("intent", b3_kb=round(kb_s, 3), b3_example=round(ex_s, 3),
                                b3_override=closer)
    return closer


# B-8 (chat UI audit live run 2026-10-29): "Which is better, MGNREGA or PMAY-G?" went to
# the documents (text, no figures). The bare question — two or more schemes and nothing
# but these words — is answered by cross_figures' "better" mode: the figures side by
# side, no winner, measures offered. "better for a landless family" stays KNOWLEDGE.
_C13_BETTER_ONLY = frozenset(("which", "is", "are", "better", "best", "the", "scheme", "schemes", "or",
                              "and", "between", "of", "vs", "versus", "a"))


def _c13_bare_which_is_better(question: str) -> bool:
    q = _correct_scheme_spelling(question or "")
    if len(_named_schemes(q)) < 2:
        return False
    rest = q
    for s, pat in _SCHEME_NAME_MATCHER.items():
        for h in reversed(list(pat.finditer(rest))):
            rest = rest[:h.start()] + " " + rest[h.end():]
    words = [w.strip("?.,!:;()").lower() for w in rest.split()]
    words = [w for w in words if w]
    return "better" in words and all(w in _C13_BETTER_ONLY for w in words)


async def _c13_intent_by_rules(question: str, session: "Session | None" = None) -> str:
    """The cue rules, then this turn's query plan or one classifier call (the
    pre-B3 classify_intent)."""
    # "what are common districts in both schemes?" opens with "what are", which
    # otherwise reads as KNOWLEDGE — but it is a list computed from the coverage
    # data, never something in the reference docs. Force DATA before the keyword
    # fast-path so the "what are" knowledge cue can't win.
    if _CROSS_SCHEME_SET_QUESTION.search(question):
        return "DATA"
    if _c13_bare_which_is_better(question):
        return "DATA"
    # "How many members are there in Bak-15 Wachal Pg?" is a lookup in the data;
    # with no counting noun the classifier sometimes sent it to the reference
    # docs ("the reference material does not contain…").
    if _pg_name_question(question):
        return "DATA"
    # A helpline / grievance / contact question is about how to reach the scheme,
    # which only the reference documents describe; on the DATA path the SQL model
    # typed a phone number into the query (General TC-015, 2026-10-06).
    if _CONTACT_INFO_CUE.search(question):
        return "KNOWLEDGE"
    # RAG fix report Issue 2: the notified wage rate is in the reference docs, not
    # megh_db; on the DATA path "wage rate" became the unskilled wage SHARE (71.06%).
    if _wage_rate_question(question):
        return "KNOWLEDGE"
    if _PROGRAMME_DESIGN_CUE.search(question):
        return "KNOWLEDGE"
    # KI-404: a "how does <X> work" / "process for" question — unless it counts
    # ("how many / how much") or names a year, which only a figure answers.
    if _PROCESS_QUESTION_CUE.search(question) and not _C13_COUNT_ASKED.search(question) \
            and not context_policy.extract_year_keys(question):
        return "KNOWLEDGE"
    if _BREAKDOWN_CUE.search(question):
        return "DATA"
    if _METRIC_WHATIS_CUE.search(question):
        return "DATA"
    # "CM Elevate Legacy records in RESUBELPARA block": a measure, then a named
    # place — a figure, never the reference docs (matrix run 2026-10-14).
    if _MEASURE_IN_PLACE.search(question):
        return "DATA"
    if _DATA_HINTS.search(question) and not _KNOWLEDGE_HINTS.search(question):
        return "DATA"
    if _KNOWLEDGE_HINTS.search(question) and not _DATA_HINTS.search(question):
        return "KNOWLEDGE"
    if _APPLICANT_PLACE_CUE.search(question) and not _KNOWLEDGE_HINTS.search(question):
        return "DATA"
    # E1 stage 2b (D-085): the rules found no cue; the plan built during this turn
    # (only with QUERY_PLAN_IN_TURN, only from these same words) already read the
    # intent, so its call stands in for this one. Measured on the 383 shadow-log
    # questions: 39 reach this point, and where the plan says DATA / KNOWLEDGE it
    # matched the pipeline 36/36; OTHER, no plan or other words -> the call below.
    if session is not None:
        from app import query_plan as _c13_qp2
        _c13_plan = await _c13_qp2.turn_plan(session, question)
        if _c13_plan and _c13_plan.get("intent") in ("DATA", "KNOWLEDGE"):
            context_budget.log_decision("intent", intent=_c13_plan["intent"], source="query_plan")
            return _c13_plan["intent"]
    prompt = f"""Classify the question into exactly one label:
  DATA      - needs a number/count/list computed from the scheme database. This
              INCLUDES comparison and correlation questions ("do districts with
              high X also have high Y", "is A related to B by district", "which
              districts lead on both schemes") — answered by querying the figures
              and comparing them, NOT from the reference docs.
  KNOWLEDGE - asks how a scheme works: eligibility, documents, components, rules, history,
              launch, who runs it, a fixed amount or rate it pays everyone, what is
              recorded at registration, how to apply / check status / complain.

Decide by the FORM of the question, not by single words: "pay", "registered",
"beneficiary", "launched" or "how much" alone do not make it DATA. With no place,
no year and no total / count / ranking / trend / breakdown, it is KNOWLEDGE.
Examples:
  "How much does Focus Plus pay?" -> KNOWLEDGE (the per-household amount)
  "How much has Focus Plus paid in 2022-23?" -> DATA
  "What details are recorded when a PMAY-G beneficiary registers?" -> KNOWLEDGE
  "How many PMAY-G beneficiaries are registered in Ri Bhoi?" -> DATA
  "When was CM Elevate launched?" -> KNOWLEDGE
  "Who is eligible for FOCUS?" -> KNOWLEDGE
  "How many producer groups got FOCUS money?" -> DATA

Return ONLY JSON: {{"intent": "DATA"|"KNOWLEDGE"}}

Question: "{question}"
JSON:"""
    raw = await llm.call_classifier(prompt, guided={"guided_json": _INTENT_JSON_SCHEMA})
    payload = _extract_json(raw)
    if payload and payload.get("intent") in ("DATA", "KNOWLEDGE"):
        return payload["intent"]
    logger.warning("classify_intent: unusable response %r — defaulting to DATA", raw[:120])
    return "DATA"


def _empty_data_fields() -> dict:
    # `data` / `sql_query` are the keys the frontend renderer reads; keep them
    # present (empty) on every route so the UI never sees `undefined`.
    return {"schemes": [], "resolved_entities": {}, "sql": None, "sql_query": None,
            "row_count": 0, "rows": [], "data": []}


def _denied(decision: "auth.AuthDecision", schemes: list[str], resolved: dict) -> dict:
    return {
        "route": "denied", "intent": "DATA", "confidence": "high",
        "answer": decision.reason, "denied": True, "denied_by": decision.check,
        **{**_empty_data_fields(), "schemes": schemes, "resolved_entities": resolved},
    }


def _out_of_scope_result(question: str, raw_question: str) -> dict:
    """Standard 'I'm Megh One AI …' reply for an OutOfScope raised mid-pipeline —
    shaped like the edge stage's returns so the frontend renders it the
    same way as an off-topic hit caught up front."""
    hit = edge.out_of_scope()
    return {
        "route": "edge", "intent": "EDGE", "confidence": "high",
        "answer": hit["response"], "edge_type": hit["type"],
        "suggestions": hit.get("suggestions", []),
        "rewritten_question": question if question != raw_question else None,
        **_empty_data_fields(),
    }


# ── Village NAME search: "how many villages are named X?" ───────────────────
# An entity SEARCH, not an entity lookup. Before this, "How many villages are
# named Songsak?" went through resolve_entities, which narrows the name to ONE
# place (the block SONGSAK, or one village) and counted that one place's
# records. The operation must be settled BEFORE any entity is resolved: a count
# or a list of every village with that name (or containing it), by LGD
# village_code — 345 village names are shared (docs/DATA_MODEL.md rule 3).
# A name: an optional opening quote, a letter, then 1-48 more of letters, digits,
# . & ' ( ) - and space — as FEW as the tail allows — and an optional closing quote.
_C13_VNS_OPEN, _C13_VNS_CLOSE = "\"'“", "\"'”"


def _c13_vns_char(ch: str) -> bool:
    return (ch.isascii() and ch.isalnum()) or ch in ".&'()- "


def _c13_ws_words(text: str, q: int, *word_sets) -> int:
    """After position q: whitespace, then a word from word_sets[0], whitespace, a word
    from word_sets[1], … each a whole word. The end position, or -1."""
    n = len(text)
    for opts in word_sets:
        k = q
        while k < n and text[k].isspace():
            k += 1
        if k == q:
            return -1
        e = k
        while e < n and _c1x_is_word_char(text[e]):
            e += 1
        if e == k or text[k:e].lower() not in opts:
            return -1
        q = e
    return q


def _c13_punct_end(rest: str) -> bool:
    r"""Only spaces and any run of ? . ! remain (spaces, marks, spaces, end)."""
    return rest.lstrip().lstrip("?.!").strip() == ""


def _c13_vns_tail(text: str, q: int) -> "int | None":
    r"""Spaces then a whole word in/under/within/for/across/of, or only end marks, follow q: q itself, or None."""
    if _c13_ws_words(text, q, {"in", "under", "within", "for", "across", "of"}) >= 0 or _c13_punct_end(text[q:]):
        return q
    return None


def _c13_in_the_name_tail(text: str, q: int) -> "int | None":
    r"""Words "in" + the/their/its + name/names, spaces between: the end, or None."""
    e = _c13_ws_words(text, q, {"in"}, {"the", "their", "its"}, {"name", "names"})
    return e if e >= 0 else None


class _C13NameSearch(_C1xLike):
    """A lead word matcher, then whitespace, then a name grown as little as
    possible (group "name"), then a tail — the old _VNS_NAME / _VNS_TAIL checks."""

    def __init__(self, lead, tail):
        self.lead = lead if isinstance(lead, _C1xNode) else Matcher(lead).node
        self.tail = tail

    def _name_at(self, text: str, p: int):
        n = len(text)
        k = p
        while k < n and text[k].isspace():
            k += 1
        if k == p:
            return None
        starts = [k + 1, k] if k < n and text[k] in _C13_VNS_OPEN else [k]
        for a in starts:
            if not (a < n and text[a].isascii() and text[a].isalpha()):
                continue
            for b in range(a + 2, min(a + 49, n) + 1):
                if not _c13_vns_char(text[b - 1]):
                    break
                for q in ([b + 1, b] if b < n and text[b] in _C13_VNS_CLOSE else [b]):
                    e = self.tail(text, q)
                    if e is not None:
                        return a, b, e
        return None

    def _hits(self, text):
        ctx = _C1xCtx(text)
        for i in range(len(ctx.toks) + 1):
            for j, _c in self.lead.ends(ctx, i, ()):
                if j <= i:
                    continue
                found = self._name_at(text, ctx.toks[j - 1].end)
                if found:
                    a, b, e = found
                    return [Hit(text, ctx.toks[i].start, e, [], {"name": (a, b)})]
        return []


def _c13_ss(*parts):
    return Seq(*parts, sep="space")


_VILLAGE_NAME_SEARCH = [
    # exact-name count / list
    ("exact", _C13NameSearch(_c13_ss(
        Alt(_c13_ss("how", "many"), _c13_ss("number", "of"), _c13_ss("count", Opt("of"), Opt("the")),
            _c13_ss("list", Opt("all"), Opt("the")), W("which"), _c13_ss("show", Opt("me"), Opt("all"), Opt("the"))),
        W("village", "villages"), Opt(W("are", "were", "is")), Opt("there"),
        Alt(W("named", "called"), _c13_ss("with", Opt("the"), "name", Opt("of")), _c13_ss("by", "the", "name", Opt("of")),
            _c13_ss("having", Opt("the"), "name"), _c13_ss("have", "the", "name"))), _c13_vns_tail)),
    # partial-name list / count
    ("contains", _C13NameSearch(_c13_ss(
        W("village", "villages"), Opt(W("that", "which")),
        W("contain", "contains", "include", "includes", "have", "has", "having")), _c13_in_the_name_tail)),
    ("contains", _C13NameSearch(_c13_ss(
        W("village", "villages"), W("whose", "with"), Opt("the"), W("name", "names"),
        W("contain", "contains", "include", "includes", "has", "have", "with")), _c13_vns_tail)),
    ("contains", _C13NameSearch(_c13_ss(W("village", "villages"), "with"), _c13_in_the_name_tail)),
]


def _c13_drop_trailing_village(name: str) -> str:
    r"""Drop a final word "village"/"villages" (any case) and the spaces before it."""
    parts = name.split()
    if len(parts) >= 2 and parts[-1].lower() in ("village", "villages") and name.endswith(parts[-1]):
        cut = name[:len(name) - len(parts[-1])]
        if cut and cut[-1].isspace():
            return cut.rstrip()
    return name


_VILLAGE_CATALOGUES = {"MGNREGA": "_mgnrega_village_names", "Focus Plus": "_focusplus_village_names",
                       "PMAY-G": "_pmay_village_names", "CM Elevate": "_cm_elevate_village_names"}


def _village_name_search(question: str) -> "tuple[str, str] | None":
    """(mode, name) for a village-name search question, else None. mode is
    "exact" (named / called X) or "contains" (X in the name)."""
    for mode, word_matcher in _VILLAGE_NAME_SEARCH:
        m = word_matcher.search(question or "")
        if m:
            name = " ".join(m.group("name").split()).strip(" .?!'\"")
            name = _c13_drop_trailing_village(name).strip()
            if len(name) >= 2:
                return mode, name
    return None


async def _village_name_search_answer(question: str) -> "dict | None":
    """The deterministic answer to a village-name search, or None when the
    question is not one. Scoped to one scheme's villages when the question
    names exactly one scheme with a village catalogue; otherwise the statewide
    LGD list, curated.dim_geography. App SQL, parameter-bound."""
    found = _village_name_search(question)
    if not found:
        return None
    mode, name = found
    named = [s for s in _named_schemes(question) if s in _VILLAGE_CATALOGUES]
    scheme = named[0] if len(named) == 1 else None
    key = " ".join(name.split()).upper()
    if scheme:
        catalogue = await globals()[_VILLAGE_CATALOGUES[scheme]]()
        hits = [v for n, vs in catalogue.items()
                if (n == key if mode == "exact" else key in n) for v in vs]
        where = f"{scheme} data"
        shown = (f"-- {scheme} village catalogue (distinct village_code by name)\n"
                 f"WHERE UPPER(lgd_village_name) {'=' if mode == 'exact' else 'LIKE'} "
                 f"'{key if mode == 'exact' else '%' + key + '%'}'")
    else:
        # Whitespace runs -> one space: tabs/newlines to spaces, split on space,
        # drop the empty pieces, join with one space.
        cond = ("UPPER(ARRAY_TO_STRING(ARRAY_REMOVE(STRING_TO_ARRAY("
                "TRANSLATE(lgd_village_name, E'\\t\\n\\r', '   '), ' '), ''), ' ')) = $1" if mode == "exact"
                else "UPPER(lgd_village_name) LIKE $1 ESCAPE '\\'")
        param = key if mode == "exact" else "%" + "".join("\\" + ch if ch in "%_\\" else ch for ch in key) + "%"
        sql = ("SELECT DISTINCT village_code, lgd_village_name AS name, UPPER(lgd_block) AS block, "
               "UPPER(lgd_district) AS district FROM curated.dim_geography "
               f"WHERE village_code IS NOT NULL AND entity_type <> 'Unresolved' AND {cond} "
               "ORDER BY 4, 3, 2")
        hits = [dict(r) for r in await fetch_rows(sql, [param])]
        where = "the LGD village list (all schemes)"
        shown = sql.replace("$1", "'" + param.replace("'", "''") + "'")
    by_code: dict = {}
    for h in hits:
        by_code.setdefault(h["village_code"], h)
    rows = sorted(by_code.values(), key=lambda h: (str(h.get("district") or ""), str(h.get("block") or ""),
                                                   str(h.get("name") or "")))
    # "…named Songsak in East Garo Hills": a district / block named besides the
    # searched name narrows the search (the name itself is not a scope).
    scope = {p: d for p, d in named_places(question).items() if p != key and d in ("district", "block")}
    if scope:
        rows = [r for r in rows if any(str(r.get(d) or "").upper() == p for p, d in scope.items())]
        where += " in " + " / ".join(p.title() + (" block" if d == "block" else "") for p, d in scope.items())
    n = len(rows)
    what = f"named \"{name}\"" if mode == "exact" else f"with \"{name}\" in their name"
    if n == 0:
        answer = f"No village {what.replace('their', 'its')} is in {where}."
        if mode == "exact":
            answer += f" For partial matches, ask \"which villages contain {name} in their name?\""
    else:
        items = [f"{r['name']} ({str(r.get('block') or '?').title()} block, "
                 f"{str(r.get('district') or '?').title()}; LGD {r['village_code']})" for r in rows[:25]]
        answer = (f"{n:,} village{'s' if n != 1 else ''} {what} {'are' if n != 1 else 'is'} in {where}: "
                  + "; ".join(items) + (f"; and {n - 25:,} more." if n > 25 else "."))
        if n > 1 and mode == "exact":
            answer += " They are different villages that share a name, told apart by their LGD code."
    also = {d for p, d in named_places(name).items() if p == key}
    if also:
        answer += f" \"{name.title()}\" is also the name of a {' and a '.join(sorted(also))}."
    context_budget.log_decision("entity_search", mode=mode, scheme=scheme, matches=n)
    rows_out = [{"village_code": r["village_code"], "village": r["name"], "block": r.get("block"),
                 "district": r.get("district")} for r in rows]
    return {"route": "data", "intent": "DATA", "confidence": "high",
            "schemes": [scheme] if scheme else [],
            "resolved_entities": {"village_name_search": name, "match": mode},
            "sql": shown, "sql_query": shown, "row_count": n, "rows": rows_out[:20],
            "data": rows_out, "answer": answer}


def _acronym_near_miss_clarification(question: str, near: "dict[str, list[str]]") -> ClarificationNeeded:
    """"Did you mean West Khasi Hills (WKH)?" for the first unrecognised
    acronym, with one chip per catalogued candidate. Each chip is the question
    with the token replaced by the district's name, so it resumes as a full
    question; a typed reply that names the district satisfies the check
    (acronym_near_misses skips a candidate the text already names)."""
    token, cands = next(iter(near.items()))
    titled = [c.title() for c in cands]
    options = [{"label": t, "question": _c1x_bounded_sub(token, t, question, count=1)}
               for t in titled]
    ask = (f"I don't recognise \"{token}\" as a district. Did you mean "
           + " or ".join(titled) + "?")
    context_budget.log_decision("clarify", rule="entity-ambiguous", reason="acronym near-miss",
                                candidates=cands)
    return ClarificationNeeded(ask, options=options, rule="entity-ambiguous")


# ── DATA path stages (D-032) ────────────────────────────────────────────────
# The DATA path, one stage per LangGraph node (scope_scheme ... assemble). A
# stage reads its inputs from the per-turn dict `d`, writes its outputs back,
# and returns a finished result dict to end the turn early or None to go on.
# A new DATA step goes into a stage, never into a graph node.

def _chat_active_scheme(session) -> "str | None":
    """The one scheme the chat is on (its structured state, else the previous
    turn's single scheme), or None for a new chat. Read-only: the data stages use
    it so a question that names no scheme is never asked "which scheme?" inside a
    chat that already has one (user rule 2026-10-19)."""
    if session is None:
        return None
    st = getattr(session, "state", None)
    sc = getattr(st, "scheme", None) if st is not None else None
    if sc:
        return sc
    prev = getattr(session, "last_turn", None)
    schemes = list(getattr(prev, "schemes", None) or [])
    return schemes[0] if len(schemes) == 1 else None


def _chat_has_data_scope(session) -> bool:
    """True once the chat has answered a data question (its structured state
    holds a scheme or a comparison). A new chat — or one that has only paused,
    greeted or answered how-it-works questions — has no place to carry, so a
    question naming none asks which district (user rule 2026-10-21, D-056)."""
    st = getattr(session, "state", None) if session is not None else None
    return bool(st is not None and (getattr(st, "scheme", None) or getattr(st, "comparison_entities", None)))


def _new_data_turn(question: str, *, skip_scope_clarify: bool = False,
                   prior_resolved: "dict | None" = None,
                   village_hint: "str | None" = None) -> dict:
    return {"question": question, "skip_scope_clarify": skip_scope_clarify,
            "prior_resolved": prior_resolved, "village_hint": village_hint,
            "schemes": None, "fp_amount": None, "entity_result": None,
            "mg_admin": None, "mg_women": None, "mg_det": None, "per_scheme": None,
            "sql": None, "rows": None, "notes": None, "style": "",
            "fl_total": None, "fl_unplaced": None, "fl_breakdown": None, "answer": None,
            "cross": None, "pre_rephrase_question": None}


# ── cross-scheme exclusions (KI-388) ──────────────────────────────────────────
_XS_EXCLUDE_CUE = Matcher(Alt(
    W("excluding", "except", "excluded", "exclude", "without"),
    Seq(W("leaving", "leave", "left"), W("out"), sep="space"),
    Seq(W("other"), W("than"), sep="space"), Seq(W("apart", "aside"), W("from"), sep="space"),
    Seq(W("not"), W("counting", "including"), sep="space"),
))
# words that may sit between the excluded names: "excluding MGNREGA and the CM-ELEVATE scheme"
_XS_EXCLUDE_GLUE = frozenset({"and", "or", "nor", "the", "scheme", "schemes", "both", "also", "as", "well"})


def _cross_exclusions(text: str) -> "tuple[list[str], str]":
    """(the schemes the question leaves out, the question with that phrase taken
    out). "Excluding CM-ELEVATE" leaves out both CM Elevate datasets."""
    t = text or ""
    cue = _XS_EXCLUDE_CUE.search(t)
    if cue is None:
        return [], t
    hits = sorted((h.start(), h.end(), s) for s, pat in _SCHEME_NAME_MATCHER.items()
                  for h in pat.finditer(t) if h.start() >= cue.end())
    out, pos, end = [], cue.end(), None
    for a, b, s in hits:
        if a < pos:
            continue
        if any(w.lower() not in _XS_EXCLUDE_GLUE for w in _c01_tm_words(t[pos:a])):
            break
        out.append(s)
        pos = end = b
    if not out:
        return [], t
    if "CM Elevate" in out or "CM Elevate Legacy" in out:
        out += [s for s in ("CM Elevate", "CM Elevate Legacy") if s not in out]
    kept = collapse_ws(t[:cue.start()] + " " + t[end:]).strip(" ,")
    for a, b in ((" ,", ","), (", ?", "?"), (",?", "?"), (" ?", "?"), (", .", "."), (",,", ",")):
        kept = kept.replace(a, b)
    # "Leaving out X, which scheme …" -> "which scheme …": a leading comma goes too
    return out, (kept[:1].upper() + kept[1:]) if kept else kept


def _cross_after_exclusions(text: str, named: list, cross: "list | None", excluded: list) -> "list | None":
    """The schemes a question with exclusions compares: the ones it names, else the
    four main schemes (MGNREGA, PMAY-G, Focus Plus, Focus Legacy), minus the
    excluded ones — when it asks a figure, a ranking or a comparison."""
    if cross and len([s for s in cross if s not in excluded]) >= 2 and len(named) >= 2:
        return [s for s in cross if s not in excluded]
    if not (cross_scheme._MONEY.search(text) or cross_scheme._COUNT.search(text)
            or cross_scheme._COVERAGE.search(text) or cross_scheme._RANK.search(text)
            or cross_scheme._XS_COMPARISON.search(text)):
        return None
    left = [s for s in cross_figures.SUPPORTED if s not in excluded]
    return left if len(left) >= 2 else None


def _cross_figures_question(text: str) -> bool:
    """A question across two or more schemes asking a figure, a ranking or a
    comparison (with its exclusions read first): DATA, whatever the classifier
    says. "What is the coverage of NREGA, PMAY-G and Focus+ in Dadenggiri block?"
    and "… spending in South Garo Hills, excluding CM-ELEVATE?" were answered from
    the reference documents (cross-scheme UAT re-test 2026-10-22, T09.2 / T11.2)."""
    excluded, kept = _cross_exclusions(text)
    named = [s for s, pat in _SCHEME_NAME_MATCHER.items() if pat.search(kept)]
    cross = cross_scheme.detect(kept, named)
    if excluded:
        cross = _cross_after_exclusions(kept, named, cross, excluded)
    if not cross or len(cross) < 2:
        return False
    return bool(cross_scheme._MONEY.search(kept) or cross_scheme._COUNT.search(kept)
                or cross_scheme._RANK.search(kept)
                or (cross_scheme._COVERAGE.search(kept) and cross_scheme.names_a_place(kept)))


async def _data_scheme_stage(d: dict, scope: "auth.UserScope | None" = None) -> "dict | None":
    """Scheme gates, classify_scheme and the scheme re-routes (graph: scope_scheme)."""
    question = d["question"]
    # Named a scheme we don't hold ("CM Elevate", "PM-KISAN", …) — say so plainly
    # instead of the generic "which scheme?" prompt, then offer the three we have.
    _unsupported = _unsupported_scheme_named(question)
    if _unsupported:
        raise _unsupported_scheme_clarification(question, _unsupported)

    _geo = await _geo_lookup_answer(question)
    if _geo is not None:
        return _geo

    # A comparison ACROSS schemes ("Compare Focus+, FOCUS and CM-ELEVATE in East
    # Khasi Hills", "which scheme has the highest beneficiary count in each
    # district?") is answered by cross_scheme after the places resolve — never by
    # the SQL generator, and never after a merged nine-year "which FY?" pause, a
    # "which area?" pause or a "which scheme?" pause (Cross Scheme sheet, 18 of 20
    # cases paused, 2026-10-13). The place gates of the entity stage still run.
    # Read on the user's own words: the rephrase node (a sampled model call) turned
    # "Compare the coverage of …" into "How does the coverage of … compare …" on
    # some runs and dropped "coverage" on others (cross-scheme run 2026-10-13).
    _cross_text = d.get("pre_rephrase_question") or question
    # "Leaving out MGNREGA and CM-ELEVATE, which scheme …" asks about the OTHER
    # schemes: the excluded names are taken out before any scheme is detected. Read
    # as named, the answer showed exactly the two excluded schemes (T07.2), went to
    # the CM Elevate documents (T11.2, T13.2) or kept MGNREGA in (T15.3) — cross-
    # scheme UAT re-test 2026-10-22, KI-388.
    _excluded, _cross_text = _cross_exclusions(_cross_text)
    if _excluded:
        question = _cross_exclusions(question)[1]
        d["question"] = question
    _named = [s for s, pat in _SCHEME_NAME_MATCHER.items() if pat.search(_cross_text)]
    # A bare "CM-ELEVATE" beside other schemes is CM Elevate, the applications
    # dataset, as written; Legacy only when named (user decision 2026-10-19,
    # replacing the 2026-10-12 default to Legacy).
    _cross_q = await _mask_scheme_words_in_village_name(_cross_text)
    _cross = cross_scheme.detect(
        _cross_q, _named,
        measure_text=(await _mask_village_names(_cross_q)) if cross_scheme.other_measure(_cross_q) else None)
    if _excluded:
        _cross = _cross_after_exclusions(_cross_q, _named, _cross, _excluded)
        logger.info("cross-scheme exclusions %s -> %s", _excluded, _cross)
    if _cross == ["CM Elevate"]:
        # the one-scheme card ("Same comparison for CM Elevate: ...") still asks
        # which CM Elevate when nothing settled it (user decision 2026-10-19)
        _cme_pause = _cm_elevate_dataset_pause(d.get("pre_rephrase_question") or question)
        if _cme_pause is not None:
            raise _cme_pause
    if _cross and _is_ambiguous_focus(_cross_text):
        # "Compare coverage of MGNREGA, PMAY-G and FOCUS in Songsak block": a bare
        # FOCUS with no Focus+ beside it is still the two-way Focus ask (CLAUDE.md
        # §4). Unasked, the comparison ran without it and never said so (T09.3,
        # cross-scheme UAT re-test 2026-10-22).
        raise _focus_ambiguity_clarification(_cross_text)
    if _cross:
        logger.info("cross-scheme comparison %r -> %s", _cross_text, _cross)
        d["schemes"], d["cross"] = _cross, {"schemes": _cross, "text": _cross_text, "excluded": _excluded}
        return None

    # Ask which scheme before doing anything expensive, when the question could
    # honestly mean either one. Guessing here is worse than a one-tap follow-up.
    # "Which scheme paid out the most?" — the scheme is the ANSWER, not a
    # missing filter, so this must run before the "which scheme?" pause below
    # (which would otherwise ask the user to supply the very thing they asked
    # for). A cross-scheme question over every scheme that records money (CM
    # Elevate records none), answered like any other (D-062).
    # ONE named dataset that has its own sub-schemes (CM Elevate, CM Elevate Legacy):
    # "which scheme has the most records / subsidy" is its scheme_name column, never
    # the six schemes. "CM Elevate Legacy: number of records, subsidy disbursed, scheme
    # with most records?" was fanned out to five schemes, answered MGNREGA / PMAY-G /
    # Focus figures nobody asked for and never named the top Legacy scheme
    # (data-accuracy brief D10, 2026-10-29). An explicit scheme name locks the routing.
    _own_subschemes = len(_named) == 1 and bool(
        (scheme_registry.DATASETS.get(_named[0]) or None) and scheme_registry.DATASETS[_named[0]].sub_scheme_column)
    if _wants_cross_scheme_money_ranking(question) and not _own_subschemes:
        _money = [s for s in cross_scheme.ORDER if s != "CM Elevate" and s not in _excluded]
        logger.info("cross-scheme money ranking %r -> %s", _cross_text, _money)
        d["schemes"], d["cross"] = _money, {"schemes": _money, "text": _cross_text}
        return None

    # "Focus" with nothing to say WHICH Focus — a two-way ask that keeps what the
    # user already told us, rather than the generic five-way pause below.
    if _is_ambiguous_focus(question):
        raise _focus_ambiguity_clarification(question)

    # A bare "CM Elevate" that neither its words nor the conversation settled
    # (the thread decision ran in the context stage): ask which dataset, never
    # guess (user decisions 2026-10-19 / 2026-10-22). Read on the words before the
    # rephrase model: it turned "How many CM-ELEVATE applications ... each
    # district?" into the chip-like "CM Elevate applications" and the answer came
    # from the applications data unasked (Legacy sheet re-run 2026-10-22).
    _cme_pause = _cm_elevate_dataset_pause(d.get("pre_rephrase_question") or question)
    if _cme_pause is not None:
        raise _cme_pause

    # A village NAME that contains another scheme's vocabulary is not a scheme
    # signal: "total expenditure in UMRAN DAIRY" was classified CM Elevate (its
    # dairy sub-scheme) and answered ₹1.27 crore of CM Elevate money for an
    # MGNREGA village (all-villages QA 2026-09-26). Scheme detection reads the
    # question with that exact village name masked; everything else reads it
    # unchanged. Only when the masked name itself carries scheme vocabulary.
    _scheme_q = await _mask_scheme_words_in_village_name(question)

    if _needs_scheme_clarification(_scheme_q):
        # User rule (2026-10-19) and MAIN_Contex.pdf §9.4: inside one chat the
        # scheme it is on is never asked again; only a NEW chat whose question
        # names no scheme (and whose words pin none) asks "which scheme?". This
        # replaces the 2026-10-14 answer-for-every-scheme default (D-045) for an
        # unnamed scheme; an explicit cross-scheme question ("compare schemes",
        # "in both schemes") is still answered side by side above.
        _chat_scheme = d.get("chat_scheme")
        if _chat_scheme:
            question = f"{question.strip().rstrip(' ?.')} under {_chat_scheme}?"
            d["question"] = question
            _scheme_q = await _mask_scheme_words_in_village_name(question)
            context_budget.log_decision("scheme", inherited="chat-scheme", scheme=_chat_scheme)
            logger.info("no scheme named; the chat is on %s -> %r", _chat_scheme, question)
        else:
            raise _scheme_clarification(question, by_measure=True)

    # Ask "top how many?" before spending model calls when the question wants a
    # ranked list over a dimension but never says how long.
    if _needs_topn_clarification(question):
        raise _topn_clarification(question)

    schemes = await classify_scheme(_scheme_q)
    # Only Focus Legacy holds producer groups and their members. A group name can
    # contain another scheme's word — "How many members are there in Chisam
    # Piggery?" was classified CM Elevate (its Piggery sub-scheme) and answered
    # "3010 members" of the Piggery scheme. A group-name question that names no
    # scheme of its own is a Focus Legacy question.
    if schemes != ["Focus Legacy"] and _pg_name_question(question) and not _mentions_scheme(question):
        logger.info("group-name question %r -> Focus Legacy (was %s)", question, schemes)
        schemes = ["Focus Legacy"]
    # Focus Legacy group-name questions are answered deterministically (see
    # _focus_legacy_pg_name_answer) before any geography resolution, which would
    # otherwise read a group name like "Nongstoin PG" as a place.
    if schemes == ["Focus Legacy"]:
        # KI-419: scheme scope first; the answer itself keeps only in-area groups
        _pg_answer = await _focus_legacy_pg_name_answer(question, scope)
        if _pg_answer is not None:
            _denial = _repaired_sql_denial(scope, schemes, {"resolved": {}}, None)
            return _denied(_denial, schemes, {}) if _denial else _pg_answer
    # CM Elevate Legacy: a question its data cannot answer (a sanction rate,
    # applicant names, constituency, monthly figures, ...) gets the reviewed
    # not-held explanation now, before any model call.
    if schemes == ["CM Elevate Legacy"]:
        _not_held = _cm_legacy_not_held(question)
        if _not_held is not None:
            raise _not_held
    # A measure none of the chosen schemes records — typed or carried by a
    # rewrite — is said plainly, never answered with another figure (2026-10-06).
    # Place names are masked first: the village "Bijasik Wage Apal" read as a
    # wage-expenditure question under PMAY-G (all-villages run 2026-10-10).
    _gap = _measure_not_held_gap(await _mask_village_names(question), schemes,
                                 scan_text=await _mask_village_names(_scheme_q) if _scheme_q else _scheme_q)
    if _gap is not None:
        raise _gap
    # "Which financial years does MGNREGA have?" — the scheme's own years from
    # its views, never the shared dim_year calendar (2026-10-06).
    _years = _scheme_years_answer(question, schemes)
    if _years is not None:
        return _years
    d["schemes"] = schemes
    return None


async def _data_entity_stage(d: dict, scope: "auth.UserScope | None" = None) -> "dict | None":
    """Pre-resolution gates and resolve_entities (graph: entities)."""
    question, schemes = d["question"], d["schemes"]
    prior_resolved, village_hint = d["prior_resolved"], d["village_hint"]
    # C1: "last year" / "this year" / "last 3 years" -> the FY(s) they mean in this
    # scheme's data, before any year reader (else: all years, or a failed query).
    # The rewritten question is the one every later stage reads (d.update below).
    _rel_note = None
    if not d.get("cross"):
        question, _rel_note = _c06_relative_year_rewrite(question, schemes)
    # A district acronym typed with its letters in another order — "Compare …
    # in WHK and EKH" (reported 2026-09-29). WHK is in no SME catalogue, so it
    # was not_found and silently left out: the comparison ran for EKH alone.
    # Never guessed: ask, offering only the district(s) whose catalogued
    # acronym has those letters (entity_resolver.acronym_near_misses).
    _near = acronym_near_misses(question)
    if _near:
        raise _acronym_near_miss_clarification(question, _near)
    # Focus Plus: a stated payment size it never pays is asked about, not dropped.
    _fp_amount = _focusplus_stated_amount(question, schemes)
    if _fp_amount is not None and int(_fp_amount.value) not in _FOCUSPLUS_PAYMENT_AMOUNTS:
        raise _focusplus_amount_clarification(question, _fp_amount)
    # raises ClarificationNeeded if ambiguous
    # A cross-scheme comparison resolves its places and year against all six
    # schemes: a year only some of the named schemes hold ("NREGA, PMAY and CM
    # Elevate Legacy in FY 2022-23") is still the year asked, and each scheme
    # that lacks it is reported as such by cross_scheme rather than refused or
    # silently dropped (cross-scheme run 2026-10-13).
    # A cross-scheme chip resume ("… in rangsagre village, SELSELLA block, WEST GARO
    # HILLS") is the bot's own village choice: pin it deterministically. Left to the
    # mention extractor it re-asked the same pause (22 of 6,978 villages) or took the
    # block for the village ("Dilma Songgital" -> "Resubelpara - Ward No.11"),
    # cross-scheme final run 2026-10-13.
    # The chip's own text, not the rephrased one: the rephrase node can turn the
    # ", CHOKPOT block, SOUTH GARO HILLS" tail into prose, and the pin reads the tail.
    # Single-scheme too: "Apalgre village during FY 2024-25, SELSELLA block, WEST
    # GARO HILLS" asked the same pause again (hierarchy matrix run 2026-10-14).
    _chip_text = d["cross"]["text"] if d.get("cross") else (d.get("pre_rephrase_question") or question)
    if not village_hint and _C13_VILLAGE_WORD.search(_chip_text or "") \
            and _CHIP_TAIL_PARSE_MATCH.search(_chip_text or ""):
        try:
            _cpin = await _mgnrega_village_chip_pin(
                _chip_text, "MGNREGA" if d.get("cross") else (_village_scheme(schemes) or "MGNREGA"))
        except Exception:  # noqa: BLE001 — normal resolution below
            _cpin = None
        if _cpin:
            village_hint = str(_cpin["lgd_village_name"])
            question = _chip_text
    try:
        entity_result = await resolve_entities(
            question, cross_scheme.ORDER if d.get("cross") else schemes,
            prior_resolved=prior_resolved, village_hint=village_hint)
    except ClarificationNeeded as e:
        if d.get("cross") and e.rule == "entity-ambiguous":
            raise await _cross_split_twin_chips(e, d["cross"]["schemes"])
        raise
    if _fp_amount is not None:
        entity_result.setdefault("notes", []).append(_focusplus_amount_note(_fp_amount))
    if _rel_note:
        entity_result.setdefault("notes", []).append(_rel_note)
    # A year-gap rewrite (see resolve_entities) replaces the question for
    # everything downstream — SQL generation above all.
    if entity_result.get("question"):
        question = entity_result["question"]
    d.update(question=question, fp_amount=_fp_amount, entity_result=entity_result)
    return None


async def _data_clarification_stage(d: dict, scope: "auth.UserScope | None" = None) -> "dict | None":
    """Region, overall-summary and scope / year / tranche gates (graph: clarification_gate)."""
    question, schemes, entity_result = d["question"], d["schemes"], d["entity_result"]
    prior_resolved, skip_scope_clarify = d["prior_resolved"], d["skip_scope_clarify"]
    if d.get("cross"):
        return await _cross_scheme_scope(d, scope)
    # "Garo Hills" / "Khasi Hills" name a hill RANGE, not a district. When one is
    # named and no specific district resolved, either offer its districts as one-tap
    # chips ("which Garo Hills district?") or, if the question already says "all of
    # Garo Hills" or asks for a per-district breakdown, expand it to every district in
    # the range and carry that forward for SQL generation.
    # MGNREGA: a resolved village / block / constituency already settles the
    # place. "THORIKAKONA GARO" and "DANGKONG GARO" are villages whose names
    # contain "Garo", and the range check asked "which Garo Hills district?" and
    # lost the village (all-villages QA 2026-09-26).
    # PMAY-G too: "shyamding ( garo ), Demdema block" asked "which Garo Hills
    # district?" and answered for the block (PMAY-G scenario run 2026-09-28).
    # CM Elevate too: "UPPER KAMARI (GARO), Tikrikilla block" was answered for all of
    # Garo Hills — 273 applications instead of 2 (CM Elevate all-villages smoke run
    # 2026-09-28).
    # Focus Legacy too: "MENDIMA GARO", "SHYAMDING ( GARO )" — the region chip then
    # rewrote the name to "MENDIMA all of Garo Hills" (all-villages run 2026-09-29, KI-162).
    # CM Elevate Legacy too: the same "MENDIMA GARO" was answered as MENDIMA
    # BAKRAGITTIM with 0 records (CM Elevate Legacy all-villages run 2026-09-29).
    # A two-village comparison too (village_code_list): "Which has more completed
    # PMAY-G houses: MALANG KHASI or SIDAKANDI?" asked "which Khasi Hills
    # district?" (PMAY-G officer cases run 2026-10-02).
    # Focus Plus too: "SHYAMDING ( GARO )" asked "which Garo Hills district?" (Focus + sheet
    # all-villages run 2026-10-10).
    _mg_place_settled = schemes in (["MGNREGA"], ["PMAY-G"], ["CM Elevate"], ["Focus Legacy"],
                                    ["CM Elevate Legacy"], ["Focus Plus"]) and any(
        entity_result["resolved"].get(k) for k in ("village_code", "village_code_list", "block",
                                                   "assembly_constituency"))
    if not entity_result["resolved"].get("district") and not entity_result["resolved"].get("district_list") \
            and not _mg_place_settled:
        _scheme0 = schemes[0] if schemes else ""
        region = detect_region(question, _scheme0)
        if region:
            _want_all = region["expand"] or bool(_HAS_BREAKDOWN.search(question))
            if not _want_all and not skip_scope_clarify:
                raise _region_clarification(question, region)
            entity_result["resolved"]["district_list"] = [d.upper() for d in region["districts"]]
            entity_result["resolved"]["district_list_region"] = region["canonical"]
            # A district the region's name does not suggest is named in the label, so the
            # total does not surprise: Khasi includes Ri Bhoi (LGD region; ingestion team
            # 2026-10-26: "say so in one line").
            _head = region["canonical"].split()[0].lower()
            _extra = [d for d in region["districts"] if _head not in d.lower()]
            entity_result["display"]["district"] = region["canonical"] + (
                f" (includes {', '.join(_extra)})" if _extra else "")

    # "Give me an overall Focus+ data summary" — a genuinely whole-scheme
    # question with no district/year/tranche to pin. Handled before the scope/
    # year/tranche clarification gates below so it never gets mistaken for an
    # aggregate question that merely forgot to name a scope.
    if _focusplus_wants_overall_summary(question, schemes):
        # KI-419: a statewide summary naming the top district, authorised like any query
        _denial = _repaired_sql_denial(scope, schemes, entity_result, _FOCUSPLUS_OVERALL_SUMMARY_SQL)
        if _denial:
            return _denied(_denial, schemes, entity_result["resolved"])
        return await _focusplus_overall_summary_answer(schemes, entity_result)

    # RAG fix report 2026-10-29 (§6, unknown district): "PMAY-G houses completed in
    # Shillong Hills district" — no such district; the resolver dropped the name and the
    # answer-defaults step then said "Meghalaya (statewide) … 1,29,941", and with a year
    # named the SQL model filtered another district. A named district / block that
    # resolved to nothing is said plainly, with the real districts to pick from.
    _unk = _c13_unresolved_named_place(question, entity_result["resolved"])
    # Spelling-fix brief 2026-10-29: a place typed without "district" / "block" that
    # matches nothing ("in ribhoy" before app/spelling.py read it) was answered for
    # the whole state ("In Ribhoy … the statewide figure") or for the chat's previous
    # place. Said plainly too, with the closest real names first.
    from app import spelling as _c13_spl
    _unres = None
    if not _unk and not skip_scope_clarify and not any(entity_result["resolved"].get(k) for k in _C13_PLACE_KEYS):
        _unres = _c13_spl.unresolved_place(question)
        if _unres is not None:
            _unk = (_unres["typed"], _unres["level"] or "place")
    if _unk and not skip_scope_clarify:
        raise _c13_unknown_place_pause(question, _unk[0], _unk[1], schemes,
                                       (_unres or {}).get("suggestions"))

    # Ask which district / block / village / year when an aggregate question
    # pins none of them — unless we're already resuming that very clarification
    # (a reply that still names no scope must not loop us back here).
    # Answer, don't ask (ANSWER_DEFAULTS_ENABLED, user decision 2026-10-14): the
    # question goes on exactly as if the user had tapped the "All of Meghalaya" /
    # "All financial years combined" / "All tranches combined" chip — the same
    # appended text, so the SQL is told the scope and never silently picks the
    # latest year — and the answer states it.
    _defaults = settings.ANSWER_DEFAULTS_ENABLED
    # User rule 2026-10-21 (D-056): a NEW chat asks what it does not know, in
    # order — scheme (scheme stage), then district (here), then year (below).
    # "how many households for MGNREGA" on a fresh chat skipped the district and
    # asked only the year. A chat that has answered a data question carries its
    # place instead (c14 _same_scheme_context_year), and statewide there stays
    # statewide. A district-restricted officer is scoped by auth, not asked.
    # User decision 2026-10-29 (RAG fix report Issue 6): off by default — no place named
    # is answered for all of Meghalaya below, and said so (NEW_CHAT_ASKS_SCOPE).
    # J-4 / J-5 (chat UI audit 2026-10-29, decided by the user): a new-chat question
    # that names its scheme is answered for all of Meghalaya (said in the banner and
    # the question, with the "by district" chip to change it) instead of a district
    # pause, so it costs at most one tap (the year, D-053, when it names none).
    # "MGNREGA person days in 2024-25" asked "which area?" while "Focus Plus amount
    # disbursed in 2024-25" answered statewide. A question naming no scheme still
    # asks scheme -> district -> year (D-056).
    _place_res = {k: v for k, v in entity_result["resolved"].items() if k != "year_key"}
    if _defaults and settings.NEW_CHAT_ASKS_SCOPE and not skip_scope_clarify and not d.get("chat_has_scope") \
            and not (scope is not None and scope.geo_restricted) \
            and not any((prior_resolved or {}).get(k) for k in ("district", "block", "village_code")) \
            and not _named_schemes(d.get("raw_question") or question) \
            and _needs_scope_clarification(question, _place_res):
        logger.info("new chat, no place named -> asking which district")
        raise _scope_clarification(question, schemes, area_only=True)
    if not skip_scope_clarify and _needs_scope_clarification(question, entity_result["resolved"]):
        if not _defaults:
            raise _scope_clarification(question, schemes)
        question = f"{question.strip().rstrip(' ?.')} for all of Meghalaya"
        entity_result["answer_defaults"] = True      # never shared through the answer cache (D-056)
        logger.info("answer default: no area named -> %r", question)

    # Geography is settled but the year isn't: ask which financial year (one-tap
    # chips) rather than silently answering across every year. The chips resume
    # with a concrete year or "all financial years", so this can't loop.
    # Every data question that names no year, not only the ones the year gate
    # would stop: "MGNREGA people who got work in Dadenggre constituency" was
    # answered for one unstated year (10,414 of 51,543) while "persons employed"
    # elsewhere covered all years (hierarchy matrix run 2026-10-14). Job cards
    # follow the same rule: the year asked, else the chat's year, else this pause —
    # they were exempt and silently pinned to FY 2025-26 (MGNREGA sheet DATA-007,
    # 2026-10-21); their all-years answer is one figure per year (_mgnrega_job_cards_query).
    _res = entity_result["resolved"]
    _no_year = not _res.get("year_key") and not _res.get("year_key_list") \
        and _parse_year_key(question) is None and not _ALL_YEARS_CUE.search(question) \
        and not _TIME_SERIES_CUE.search(question) and not _WHICH_YEAR_CUE.search(question) \
        and any(_SCHEME_DATA_YEARS.get(s) for s in (schemes or []))
    # 2026-10-18 (D-053, user decision): the all-years default is for a question
    # whose conversation already carries a year. A follow-up inherits the previous
    # turn's year (prior_resolved seeds the resolver; the rewrite appends "in FY ..."
    # or "across all financial years"), so it never gets here without one. A
    # question with no year in its text, its entities or its context asks which
    # financial year, with the one-tap chips, as before D-045: "total
    # beneficiaries for MGNREGA" on a fresh thread was answered as 1,494,437
    # household-years across every year without asking (live 2026-10-18).
    # The chips resume with "for FY ..." / "across all financial years", so the
    # resumed turn has a year and cannot be asked again.
    _context_year = bool(prior_resolved) and any(
        prior_resolved.get(k) for k in ("year_key", "year_key_list", "year_all"))
    # RAG fix report Issue 6 (user decision 2026-10-29): "this year" / "the current
    # financial year" is the latest financial year the scheme holds, said in the answer;
    # it fell to the all-years default ("houses completed this year" -> 1,29,941).
    _held = [y for s in (schemes or []) for y in (_SCHEME_DATA_YEARS.get(s) or [])]
    if _defaults and _no_year and len(schemes or []) == 1 and _held and _C13_THIS_YEAR_CUE.search(question):
        _latest = max(_held)
        question = f"{question.strip().rstrip(' ?.')} in FY {_latest} (the latest year held)"
        entity_result["resolved"]["year_key"] = int(_latest[:4])
        entity_result.setdefault("display", {})["year"] = f"FY {_latest}"
        entity_result["answer_defaults"] = True
        _no_year = False
        logger.info("answer default: 'this year' -> latest FY %s", _latest)
    # D-061 (user addendum 2026-10-22): a self-sufficient NEW question inside a
    # chat inherits nothing, the chat's year included (_same_scheme_context_year
    # gives it no prior_resolved). D-065 (user, 2026-10-22): with no year of its
    # own it is ASKED, with the year chips, like a new chat (D-053) — never the
    # latest FY by default: "total disbursement amount for mairang" after an
    # all-years answer came back "FY 2025-26 (new question)" ("why are you
    # blindly giving 2025-26? … take the previous context or ask which year").
    # A follow-up keeps the chat's year (prior_resolved), so it never asks here.
    # User decision 2026-10-29 (RAG fix report Issue 6): no year named -> all financial
    # years combined, stated in the answer, unless NEW_CHAT_ASKS_SCOPE brings D-065 back.
    _ask_year = _defaults and settings.NEW_CHAT_ASKS_SCOPE and _no_year and not _context_year \
        and _needs_year_clarification(question, schemes, _res)
    if _defaults and _no_year and not _ask_year:
        question = f"{question.strip().rstrip(' ?.')} across all financial years"
        entity_result["answer_defaults"] = True
        logger.info("answer default: no year named -> %r", question)
    if _ask_year:
        logger.info("year not named and none in context -> asking which financial year")
    if _ask_year or (not _defaults and _needs_year_clarification(question, schemes, _res)):
        # MGNREGA women questions offer only the years that carry women data.
        if schemes == ["MGNREGA"] and _WOMEN_CUE.search(question or ""):
            try:
                raise await _mgnrega_women_year_clarification(question)
            except ClarificationNeeded:
                raise
            except Exception:  # noqa: BLE001 — year map unavailable: the generic pause
                pass
        _yc = _year_clarification(question, schemes)
        if schemes == ["MGNREGA"] and _C13_JOB_CARD.search(question or ""):
            # a running total has no combined figure: the all-years chip lists every year
            for _o in _yc.options or []:
                if isinstance(_o, dict) and str(_o.get("question") or "").endswith("across all financial years"):
                    _o["label"] = "Every financial year (one figure each)"
        raise _yc

    # Focus Plus only: year is settled but the tranche isn't — ask which one
    # (one-tap chips) rather than silently combining every tranche's payments.
    # `already_all_combined` lets a session that already answered this once
    # ("all tranches combined") skip a redundant re-ask on a later bare
    # follow-up that doesn't restate "tranche" itself.
    if _needs_tranche_clarification(
            question, schemes, entity_result["resolved"],
            already_all_combined=bool((prior_resolved or {}).get("tranche_all_combined"))):
        if not _defaults:
            raise _tranche_clarification(question)
        question = f"{question.strip().rstrip(' ?.')} across all tranches"
        entity_result["answer_defaults"] = True
        logger.info("answer default: no tranche named -> %r", question)

    # A specific non-Tranch-4 tranche plus a person-level column (status/
    # gender/occupation/verification) can never match any row — that data
    # exists only on the 12.5K cohort, which is entirely Tranch 4. Explain why
    # instead of running SQL that is guaranteed to come back empty.
    if _person_level_tranche_conflict(question, schemes, entity_result["resolved"])             and not _fp_status_cohort_query(question, schemes, entity_result["resolved"]):
        return _person_level_tranche_conflict_answer(question, schemes, entity_result)
    d["entity_result"] = entity_result
    d["question"] = question          # an answer default may have added its scope
    return None


# "What is the village code of Abokgre?", "Which block is Umshaken village in?",
# "block name of Aberam": a lookup in the geography registry, answerable for any
# scheme — it was refused as general knowledge or asked "which scheme?" (user
# session 2026-10-13). Every village of that name is listed, so nothing is asked.
_C13_VILLAGE_WORD = Matcher(W("village"))
_C13_JOB_CARD = Matcher(Joined("job", ("card", "cards")))
_C13_PLACE_PREPS = frozenset(("in", "of", "for", "at", "under", "from"))
_C13_NOT_A_NAME = frozenset("the each every which any a an my our this that whole entire same other all its their "
                            "your his her one per by".split())
_C13_PLACE_KEYS = ("district", "district_list", "block", "block_list", "village", "village_code",
                   "village_code_list", "assembly_constituency")


def _c13_unknown_place_pause(question: str, name: str, level: str, schemes: "list | None",
                             suggestions: "list | None" = None) -> ClarificationNeeded:
    """"I couldn't find a district called “zorbatown” in Meghalaya. Did you mean …?"
    with the closest real places first, then every district, then All of Meghalaya.
    Never an answer for another place (spelling-fix brief 2026-10-29, §3.2)."""
    from app import spelling as _c13_sp
    stem = collapse_ws(question.replace(f"{name} {level}", " ").replace(name, " ")).rstrip(" ?.")
    for prep in (" in", " of", " for", " at", " under", " from"):
        if stem.endswith(prep):
            stem = stem[: -len(prep)]
    dists = list(dict.fromkeys(d for s in (schemes or []) for d in all_districts(s)))
    sug = suggestions or _c13_sp.suggestions(name, level if level in ("district", "block", "village") else None)
    close = [s for s in sug if s["score"] >= 60]
    first = [{"label": s["name"] + (f" ({s['level']}, {s['parent']})" if s["parent"] else f" ({s['level']})"),
              "question": f"{stem} in {s['name']}" + (f" {s['level']}" if s["level"] != "district" else "")}
             for s in close]
    shown = {s["name"].upper() for s in close if s["level"] == "district"}
    logger.info("named %s %r resolved to nothing -> saying so (closest: %s)", level, name, [s["name"] for s in sug])
    return ClarificationNeeded(
        f"I couldn't find a {level} called “{name}” in Meghalaya. "
        + (f"Did you mean {' or '.join(s['name'] for s in close)}? " if close else "")
        + ("Please pick one of Meghalaya's districts below, or check the spelling."
           if level in ("district", "place") else
           "Please check the spelling, or name the district it is in (pick one below)."),
        options=first + [{"label": d, "question": f"{stem} in {d}"} for d in dists if d.upper() not in shown]
        + [{"label": "All of Meghalaya", "question": f"{stem} for all of Meghalaya"}],
        rule="unknown-place")


def _c13_unresolved_named_place(question: str, resolved: dict) -> "tuple[str, str] | None":
    """(name, "district" | "block") for "in <name> district/block" when nothing in the
    question resolved to a place and no catalogue knows the name; else None."""
    if any((resolved or {}).get(k) for k in _C13_PLACE_KEYS):
        return None
    toks = tokens(question or "")
    for i, t in enumerate(toks):
        if t.low not in ("district", "block"):
            continue
        j, name = i - 1, []
        while j >= 0 and i - j <= 5 and toks[j].low not in _C13_PLACE_PREPS:
            name.insert(0, toks[j])
            j -= 1
        if j < 0 or not name or toks[j].low not in _C13_PLACE_PREPS:
            continue
        if any(n.low in _C13_NOT_A_NAME or n.raw.isdigit() for n in name):
            continue
        text = (question or "")[name[0].start:name[-1].end]
        # a catalogue name for the WHOLE phrase: "Shillong Hills" holds the block
        # "Shillong", which is not the place named
        want = {n.low for n in name}
        if any({tk.low for tk in tokens(c)} == want for c in named_places(text)):
            continue
        return text, t.low
    return None


_C13_THIS_YEAR_CUE = Matcher(Alt(
    Seq(W("this", "current", "present"), Opt(W("financial", "fiscal")), W("year", "fy")),
    Seq(W("this", "current"), "fy"), Seq("so", "far", "this", "year"),
    Seq(Opt("the"), W("latest", "newest"), Opt(W("financial", "fiscal")), W("year", "fy"))))


def _c13_geo_end(rest: str) -> bool:
    r"""Only spaces and at most one ? or . remain, up to the end."""
    r = rest.lstrip()
    if r and r[0] in "?.":
        r = r[1:]
    return r.strip() == ""


def _c13_after_words(text: str, q: int, *words_) -> int:
    """_c13_ws_words for fixed words; -1 when absent."""
    return _c13_ws_words(text, q, *[{w} for w in words_])


def _c13_geo_tail_plain(text: str, q: int) -> bool:
    r"""An optional word "village", then only spaces and at most one ? or . to the end."""
    v = _c13_after_words(text, q, "village")
    return (v >= 0 and _c13_geo_end(text[v:])) or _c13_geo_end(text[q:])


def _c13_geo_tail_b(text: str, q: int) -> bool:
    r"""Optional "village", optional in / located in / under / part of, then the _c13_geo_end end."""
    v = _c13_after_words(text, q, "village")
    for p0 in ([v, q] if v >= 0 else [q]):
        for words_ in (("in",), ("located", "in"), ("under",), ("part", "of")):
            e = _c13_after_words(text, p0, *words_)
            if e >= 0 and _c13_geo_end(text[e:]):
                return True
        if _c13_geo_end(text[p0:]):
            return True
    return False


def _c13_geo_tail_d(text: str, q: int) -> bool:
    r"""Optional "village", spaces, a word starting in/located/lie/fall/come, then the rest of the line."""
    v = _c13_after_words(text, q, "village")
    for p0 in ([v, q] if v >= 0 else [q]):
        k = p0
        while k < len(text) and text[k].isspace():
            k += 1
        if k == p0:
            continue
        e = k
        while e < len(text) and _c1x_is_word_char(text[e]):
            e += 1
        if not text[k:e].lower().startswith(("in", "located", "lie", "fall", "come")):
            continue
        rest = text[e:]
        if "\n" not in (rest[:-1] if rest.endswith("\n") else rest):
            return True
    return False


class _C13GeoLookup(_C1xLike):
    """The old four-way geo-lookup check: (lead words) + whitespace + a name of
    2-61 characters (a letter, then word characters, space, . ( ) ' -) grown as
    little as the end of the question allows; groups 1-4 / a-d hold the name
    of whichever form matched."""

    _FORMS = (
        ("a", _c13_ss(W("village", "lgd"), W("code", "codes"), W("of", "for")), _c13_geo_tail_plain),
        ("b", _c13_ss(W("which", "what"), Opt(_c13_ss("is", "the")), W("block", "district", "constituency"),
                      Opt("name"), W("of", "for", "is")), _c13_geo_tail_b),
        ("c", _c13_ss(W("block", "district", "constituency"), "name", W("of", "for")), _c13_geo_tail_plain),
        ("d", _c13_ss(Opt("in"), W("which", "what"), W("block", "district", "constituency"), W("is", "does")),
         _c13_geo_tail_d),
    )

    @staticmethod
    def _name_char(ch: str) -> bool:
        return _c1x_is_word_char(ch) or ch in " .()'-"

    def _hits(self, text):
        ctx = _C1xCtx(text)
        n = len(text)
        for i in range(len(ctx.toks)):
            for gi, (name, lead, tail) in enumerate(self._FORMS):
                lead_node = lead
                for j, _c in lead_node.ends(ctx, i, ()):
                    if j <= i:
                        continue
                    p0 = ctx.toks[j - 1].end
                    a = p0
                    while a < n and text[a].isspace():
                        a += 1
                    if a == p0 or not (a < n and text[a].isascii() and text[a].isalpha()):
                        continue
                    for b in range(a + 2, min(a + 61, n) + 1):
                        if not self._name_char(text[b - 1]):
                            break
                        if tail(text, b):
                            groups = [None] * 4
                            groups[gi] = (a, b)
                            return [Hit(text, ctx.toks[i].start, n, groups, {name: (a, b)})]
        return []


_GEO_LOOKUP_MATCH = _C13GeoLookup()


def _c13_strip_lead_words(name: str, *lead: str) -> str:
    r"""Drop an opening "the" then "village" (any case): drop each lead
    word, in order, when it starts the text and whitespace follows it."""
    for w in lead:
        if name[:len(w)].lower() == w and len(name) > len(w) and name[len(w)].isspace():
            name = name[len(w):].lstrip()
    return name


async def _geo_lookup_answer(question: str) -> "dict | None":
    m = _GEO_LOOKUP_MATCH.search(question or "")
    if not m:
        return None
    name = next((g for g in m.groups() if g), "").strip().strip("'\"")
    name = _c13_strip_lead_words(name, "the", "village").strip()
    if not name or len(name) < 3 or _mentions_scheme(name):
        return None
    rows = await fetch_rows(
        "SELECT village_code, lgd_village_name, lgd_block, lgd_district, ac_name "
        "FROM curated.dim_geography WHERE UPPER(lgd_village_name) = UPPER($1) AND village_code > 0 "
        "ORDER BY lgd_district, lgd_block, village_code", [name])
    if not rows:
        rv = await resolve_village(name)
        codes = [rv.canonical] if rv.status == "resolved" else [c["village_code"] for c in (rv.candidates or [])]
        if not codes:
            return None
        rows = await fetch_rows(
            "SELECT village_code, lgd_village_name, lgd_block, lgd_district, ac_name FROM curated.dim_geography "
            "WHERE village_code = ANY($1::bigint[]) ORDER BY lgd_district, lgd_block, village_code",
            [[int(c) for c in codes]])
    if not rows:
        return None
    # H-1 (chat UI audit 2026-10-29): the same table was written into the answer
    # and sent again as the result rows, so it showed twice (Title Case in one,
    # CAPITALS in the other). One sentence here; the rows are the table.
    if len(rows) == 1:
        r = rows[0]
        lines = [f"**{name.title()}** is in {str(r['lgd_block'] or '—').title()} block, "
                 f"{str(r['lgd_district'] or '—').title()} district"
                 + (f" ({str(r['ac_name']).title()} constituency)" if r["ac_name"] else "")
                 + f", LGD village code {r['village_code']}."]
    else:
        lines = [f"**{name.title()}** is {len(rows)} different villages in the Meghalaya geography registry that "
                 "share a name, told apart by their LGD code; they are listed in the table below."]
    sql = "SELECT village_code, lgd_village_name, lgd_block, lgd_district, ac_name FROM curated.dim_geography"
    return {"route": "data", "intent": "DATA", "confidence": "high", "schemes": [],
            "resolved_entities": {}, "sql": sql, "sql_query": sql, "row_count": len(rows),
            "rows": [dict(r) for r in rows], "data": [dict(r) for r in rows], "answer": "\n".join(lines)}


def _c13_chip_label_spans(label: str) -> list:
    """A label "<name> — <block> block, <district>" on one line: spans of the three parts."""
    body = label[:-1] if label.endswith("\n") else label
    if "\n" in body:
        return []
    i = body.find(" — ", 1)
    if i < 0:
        return []
    j = body.find(" block, ", i + 4)
    if j < 0 or j + 8 >= len(body):
        return []
    return [(0, len(body), [(0, i), (i + 3, j), (j + 8, len(body))])]


class _C13ChipLabel(_C1xScan):
    def match(self, text):
        hits = self._hits(text or "")
        if not hits:
            return None
        h = hits[0]
        h._named = {"name": h._groups[0], "block": h._groups[1], "district": h._groups[2]}
        return h


_VILLAGE_CHIP_LABEL_MATCH = _C13ChipLabel(_c13_chip_label_spans)


async def _cross_split_twin_chips(e: "ClarificationNeeded", schemes: list[str]) -> "ClarificationNeeded":
    """A which-village pause for a cross-scheme question: a chip standing for two
    same-name villages of one block that BOTH hold data is split into one chip per
    village, told apart by LGD code. Untouched, the chip "BOLDAMGRE — SELSELLA
    block" resumed into the same pause again (cross-scheme village run 2026-10-13)."""
    opts = list(e.options or [])
    out: list[dict] = []
    changed = False
    for o in opts:
        m = _VILLAGE_CHIP_LABEL_MATCH.match(str(o.get("label") or ""))
        if not m or _CHIP_LGD_CODE_MATCH.search(o.get("label") or ""):
            out.append(o)
            continue
        try:
            rows = await fetch_rows(
                "SELECT village_code, lgd_village_name, lgd_block, lgd_district FROM curated.dim_geography "
                "WHERE UPPER(lgd_village_name) = UPPER($1) AND UPPER(lgd_block) = UPPER($2) "
                "AND UPPER(lgd_district) = UPPER($3) ORDER BY village_code",
                [m.group("name").strip(), m.group("block").strip(), m.group("district").strip()])
            active = await cross_scheme.villages_with_records(schemes, [r["village_code"] for r in rows]) \
                if len(rows) > 1 else set()
        except Exception:  # noqa: BLE001 — keep the chip as it was
            rows, active = [], set()
        cands = [{"village_code": r["village_code"], "name": r["lgd_village_name"], "block": r["lgd_block"],
                  "district": r["lgd_district"]} for r in rows if r["village_code"] in active]
        if len(cands) < 2:
            out.append(o)
            continue
        changed = True
        for c in cands:
            tag = f" (LGD {c['village_code']})"
            q = str(o.get("question") or "")
            _spans = _c1x_loose_spans(str(m.group("name")), q)
            q = (q[:_spans[0][1]] + tag + q[_spans[0][1]:]) if _spans else q + tag
            out.append({"label": f"{m.group('name')}{tag} — {m.group('block')} block, {m.group('district')}",
                        "question": q})
    if not changed:
        return e
    return ClarificationNeeded(e.question, options=out, rule=e.rule, village_hint=e.village_hint)


async def _cross_twin_village_pause(d: dict, schemes: list[str], resolved: dict) -> None:
    """Two villages can share a name, a block and a district and BOTH hold data —
    BOLDAMGRE 272895 (MGNREGA) and 272933 (Focus Plus, CM Elevate), SELSELLA
    block. resolve_village collapses such a pair to the busier one (it is
    usually an ingestion duplicate), so "compare … in boldamgre village" answered
    for 272895 and the other village could not be reached (cross-scheme village
    run 2026-10-13). A cross-scheme question reads every scheme, so both are
    offered, told apart by their LGD code (_village_code_tag)."""
    code = resolved.get("village_code")
    text = d["cross"]["text"] or ""
    if not code or isinstance(code, (list, tuple)) or _CHIP_LGD_CODE_MATCH.search(text) \
            or _CHIP_LGD_CODE_MATCH.search(d["question"] or ""):
        return
    rows = await fetch_rows(
        "SELECT g2.village_code, g2.lgd_village_name, g2.lgd_block, g2.lgd_district "
        "FROM curated.dim_geography g1 JOIN curated.dim_geography g2 "
        "ON UPPER(g2.lgd_village_name) = UPPER(g1.lgd_village_name) "
        "AND g2.lgd_block IS NOT DISTINCT FROM g1.lgd_block "
        "AND g2.lgd_district IS NOT DISTINCT FROM g1.lgd_district "
        "WHERE g1.village_code = $1 ORDER BY g2.village_code", [int(code)])
    if len(rows) < 2:
        return
    active = await cross_scheme.villages_with_records(schemes, [r["village_code"] for r in rows])
    cands = [{"village_code": r["village_code"], "name": r["lgd_village_name"], "block": r["lgd_block"],
              "district": r["lgd_district"]} for r in rows if r["village_code"] in active]
    if len(cands) < 2:
        return
    _s = ["MGNREGA"]   # the village-grained chip shape (code-tagged twins)
    raise ClarificationNeeded(
        f"“{cands[0]['name']}” is {len(cands)} different villages in {str(cands[0]['block']).title()} block "
        f"with the same name — which one do you mean?",
        options=[{"label": _village_chip_label(c, cands, _s),
                  "question": _village_chip_question(text, c["name"], c, _s, cands)} for c in cands],
        rule="entity-ambiguous", village_hint=str(cands[0]["name"]))


async def _cross_scheme_scope(d: dict, scope: "auth.UserScope | None" = None) -> "dict | None":
    """A cross-scheme question's places, year and scope (graph: clarification_gate).

    It is answered like any data question, one model-written query per scheme
    (_per_scheme_generate) and one composed answer (D-062, 2026-10-22). It used
    to be a fixed table (D-044) that could show only per-scheme totals: "top ten
    highest villages in Mgnrega and pmay" got the statewide totals card (user
    report 2026-10-22). What the table's place handling learnt stays: the block
    another scheme spells longer, a constituency only the registry knows,
    "FY2022-23" with no space, twin villages. No area / year pause: a comparison
    with no place is statewide and with no year covers each scheme's own years —
    the merged nine-year "which FY?" pause is what D-044 removed."""
    question, schemes, entity_result = d["question"], d["schemes"], d["entity_result"]
    resolved = entity_result["resolved"]
    display = entity_result.setdefault("display", {})
    text = d["cross"]["text"] or question
    await cross_scheme.refine_block(text, resolved)
    if resolved.get("block"):
        display["block"] = resolved["block"]
    await cross_scheme.refine_constituency(text, resolved)
    if resolved.get("assembly_constituency"):
        display["assembly_constituency"] = resolved["assembly_constituency"]
    # A-14 (audit 2026-10-29): "2023-24 vs 2024-25", "in FY24 and FY25" — the
    # extractor hands back one year (KI-427), and the text was read only when the
    # resolver found none, so the comparison lost a year. Two or more named years
    # are always every one of them.
    _named_ys = cross_scheme.years_in_text(text)
    if len(_named_ys) >= 2 and not resolved.get("year_key_list"):
        resolved.pop("year_key", None)
        resolved["year_key_list"] = _named_ys
        display["year"] = "FY " + ", ".join(f"{y}-{(y + 1) % 100:02d}" for y in _named_ys)
    if not resolved.get("year_key") and not resolved.get("year_key_list"):
        ys = cross_scheme.years_in_text(text)
        if len(ys) == 1:
            resolved["year_key"] = ys[0]
        elif ys:
            resolved["year_key_list"] = ys
        if ys:
            display["year"] = "FY " + ", ".join(f"{y}-{(y + 1) % 100:02d}" for y in ys)
    await _cross_twin_village_pause(d, schemes, resolved)
    if not any(resolved.get(k) for k in cross_scheme.PLACE_KEYS):
        # never present statewide figures as if they were the named place's
        d["cross"]["place_unrecognised"] = cross_scheme.names_a_place(text)
        if _needs_scope_clarification(question, resolved):
            question = f"{question.strip().rstrip(' ?.')} for all of Meghalaya"
            entity_result["answer_defaults"] = True
    if not resolved.get("year_key") and not resolved.get("year_key_list") \
            and _parse_year_key(question) is None and not _ALL_YEARS_CUE.search(question) \
            and not _TIME_SERIES_CUE.search(question) and not _WHICH_YEAR_CUE.search(question):
        question = f"{question.strip().rstrip(' ?.')} across all financial years"
        entity_result["answer_defaults"] = True
    # the user's own words: the "across all financial years" added above reads as money
    gaps = _cross_scheme_gaps(schemes, resolved, display, text)
    if gaps and len(gaps) == len(schemes):
        # nothing to query: each scheme's own reason, said plainly
        return {
            "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
            "resolved_entities": resolved, "sql": None, "sql_query": None,
            "row_count": 0, "rows": [], "data": [], "answer": " ".join(f"{g}." for g in gaps.values()),
        }
    # The shapes whose arithmetic is known — totals, district rankings, the leading
    # / second scheme per district, "districts where X > Y", per beneficiary — over
    # beneficiaries, money and villages of the four main schemes: each scheme's
    # figures from a fixed parameter-bound query and the combining done in code
    # (D-066). The model wrote the parts right and never the whole: 40 of 60 UAT
    # cases failed (cross-scheme re-test 2026-10-22, KI-387..392). Every other shape
    # (village / block lists, top-N villages, other measures) goes on below (D-062).
    _plan = None if d["cross"].get("place_unrecognised") else cross_figures.plan(
        text, schemes, resolved, display, _SCHEME_NAME_MATCHER)
    if _plan is not None:
        # KI-419: the fixed per-scheme figures never reached the authorize node, so a
        # by-district ranking showed every district to any officer
        _denial = _c13_e12_cross_figures_denial(scope, schemes, _plan)
        if _denial:
            return _denied(_denial, schemes, resolved)
        _res = await cross_figures.answer(_plan)
        return {
            "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
            "resolved_entities": resolved, "sql": _res["sql"], "sql_query": _res["sql"],
            "row_count": len(_res["rows"]), "rows": _res["rows"][:20], "data": _res["rows"],
            "answer": _res["answer"],
            **({"column_totals": _res["totals"]} if _res.get("totals") else {}),
            **({"measure_notes": _res["measure_notes"]} if _res.get("measure_notes") else {}),
            **({"schemes_with_data": _res["schemes_with_data"]} if "schemes_with_data" in _res else {}),
            **({"schemes_apart": _res["schemes_apart"]} if _res.get("schemes_apart") else {}),
        }
    logger.info("cross-scheme question %r -> %s per-scheme queries%s", question, schemes,
                f" (not held: {sorted(gaps)})" if gaps else "")
    d["entity_result"] = entity_result
    d["question"] = question
    return None


def _c13_e12_cross_figures_denial(scope: "auth.UserScope | None", schemes: list[str],
                                  plan: "cross_figures.Plan") -> "auth.AuthDecision | None":
    """The denial for a cross_figures answer, or None (KI-419, E12 2026-10-29).
    Its SQL cannot be authorised as written: the places are bind parameters, and
    every statement counts DISTINCT village_code, which authorize reads as
    village-level data (a state officer was refused every statewide comparison).
    What the answer shows is in the plan: the districts and block it is filtered
    to, and either one figure per district or one total. Each place is checked as
    a resolved entity; a per-district answer as a query grouped by district."""
    places = [{"district": d} for d in plan.districts] if plan.districts else [{}]
    if plan.block:
        places = [{**pl, "block": plan.block} for pl in places]
    shape = "SELECT lgd_district FROM curated.v_employment GROUP BY lgd_district" if plan.by_district else None
    if plan.op == "overlap" and plan.list_villages:
        # a list of villages (G-8) is village-level data
        shape = "SELECT lgd_village_name FROM curated.v_employment GROUP BY lgd_village_name"
    for pl in places:
        decision = _repaired_sql_denial(scope, schemes, {"resolved": pl}, shape)
        if decision:
            return decision
    return None


# Only these schemes record an assembly constituency (MGNREGA on v_employment,
# Focus Legacy and CM Elevate Legacy through dim_geography.ac_name). PMAY-G, Focus
# Plus and CM Elevate do not: a model asked for their constituency figure answers
# the district or the state instead (cross-scheme run 2026-10-13, D-044).
_CROSS_AC_RECORDED = frozenset({"MGNREGA", "Focus Legacy", "CM Elevate Legacy"})


def _cross_scheme_gaps(schemes: list[str], resolved: dict, display: "dict | None" = None,
                       question: str = "") -> dict:
    """{scheme: the reason it has no figure} for what its data cannot hold — a
    constituency it does not record, a financial year it has no data for, money
    for CM Elevate (applications only). Said instead of queried: the model
    returned 0 or the scheme's other years for these, which read as a real figure."""
    gaps: dict = {}
    ac = resolved.get("assembly_constituency")
    years = resolved.get("year_key_list") or ([resolved["year_key"]] if resolved.get("year_key") else [])
    asked = (display or {}).get("year") or "FY " + ", ".join(f"{int(y)}-{(int(y) + 1) % 100:02d}" for y in years)
    money_only = cross_scheme.asks_money_only(question)
    for s in schemes:
        if money_only and s == "CM Elevate":
            gaps[s] = "CM Elevate records applications only, no money, so it has no amount to compare"
            continue
        if ac and s not in _CROSS_AC_RECORDED:
            gaps[s] = f"{s} does not record assembly constituency, so it has no figure for {str(ac).title()}"
            continue
        if not years:
            continue
        held = _SCHEME_DATA_YEARS.get(s)
        if held == []:
            gaps[s] = f"{s} records no financial year, so it has no figure for {asked}"
        elif held and not ({int(h[:4]) for h in held} & {int(y) for y in years}):
            # the years listed, not a range: Focus Legacy has no FY 2023-24 inside its range
            gaps[s] = f"{s} has no data for {asked} (its data covers FY {', '.join(held)})"
    return gaps


async def _data_deterministic_stage(d: dict, scope: "auth.UserScope | None" = None) -> "dict | None":
    """The fixed-shape MGNREGA and PMAY-G queries built in code (graph: deterministic)."""
    question, schemes, entity_result = d["question"], d["schemes"], d["entity_result"]
    if d.get("cross"):
        # a cross-scheme question is one model-written query per scheme (D-062)
        d.update(mg_admin=None, mg_women=None, mg_det=None)
        return None
    # MGNREGA shapes that are fixed by the question and that the model kept
    # getting wrong — built from the resolved filters and run parameter-bound
    # (see _mgnrega_combined_facts_query / _mgnrega_admin_expenditure_query).
    _mg_admin = _mgnrega_admin_expenditure_query(question, schemes, entity_result["resolved"])
    _mg_women = None
    if schemes == ["MGNREGA"]:
        try:
            await _mgnrega_year_women()          # warms the cache _mgnrega_women_years_only reads
        except Exception:  # noqa: BLE001
            pass
        if not _mg_admin:
            _mg_women = await _mgnrega_women_query(question, schemes, entity_result["resolved"])
    if _mg_women and _mg_women["kind"] == "unrecorded":
        # KI-419: returned before the authorize node; the latest-year figure is the place's
        _denial = _repaired_sql_denial(scope, schemes, entity_result, _mg_women["shown"])
        if _denial:
            return _denied(_denial, schemes, entity_result["resolved"])
        answer = await _mgnrega_women_unrecorded_answer(_mg_women, entity_result.get("display") or {})
        return {
            "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
            "resolved_entities": entity_result["resolved"], "sql": None, "sql_query": None,
            "row_count": 0, "rows": [], "data": [], "answer": answer,
        }
    # PMAY-G fixed shapes (counts, money, stages, release status, rates, summaries,
    # A-vs-B comparisons): query and wording built here, parameter-bound — the
    # 30B's per-year GROUP BY, AVG-based rates, LIMIT 1 comparisons and dropped
    # figures failed 11 of 28 use cases (PMAY-G QA 2026-09-28, KI-089..KI-095).
    _pm_unknown = _pmay_unknown_place_answer(schemes, entity_result["resolved"], entity_result.get("notes"))
    if _pm_unknown:
        return {
            "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
            "resolved_entities": entity_result["resolved"], "sql": None, "sql_query": None,
            "row_count": 0, "rows": [], "data": [], "answer": _pm_unknown,
        }
    _pm_det = _pmay_facts_query(question, schemes, entity_result["resolved"], entity_result.get("notes"))
    if _pm_det:
        if scope is not None and settings.AUTH_ENABLED:
            decision = auth.authorize(scope, schemes=schemes,
                                      resolved_entities=entity_result["resolved"], sql=_pm_det["shown"])
            if not decision.allow:
                logger.info("auth deny (%s) user=%s: %s", decision.check, scope.user_id, decision.reason)
                return _denied(decision, schemes, entity_result["resolved"])
        _pm_det["display"] = entity_result.get("display") or {}
        _pm_rows = [dict(r) for r in await fetch_rows(_pm_det["sql"], _pm_det["params"])]
        logger.info("PMAY-G deterministic query (%s): %s", ",".join(_pm_det["metrics"]),
                    _pm_det["shown"].replace("\n", " ")[:400])
        _pm_answer = _pmay_facts_answer(_pm_det, _pm_rows)
        if _pm_answer and _pm_det.get("bare_year") and _pm_det.get("year_key") == _pm_det["bare_year"]:
            # A plain year ("during 2017") is the CALENDAR year: the answer, the result table
            # and the SQL shown are the calendar-year figures, with the FY reading as a one-line
            # note. The FY figures used to lead while the calendar ones sat in the note, so the
            # table disagreed with what the officer asked (user report 2026-09-29; the SME file
            # pmay_entity_resolver.yaml reads "sanctioned in 2023" as calendar 2023).
            _cy = _pm_det["bare_year"]
            _cal = _pmay_facts_query(question, schemes, {k: v for k, v in entity_result["resolved"].items()
                                                         if k != "year_key"},
                                     entity_result.get("notes"), calendar_year=_cy)
            if _cal:
                _cal["display"] = _pm_det.get("display") or {}
                _cal_rows = [dict(r) for r in await fetch_rows(_cal["sql"], _cal["params"])]
                _cal_answer = _pmay_facts_answer(_cal, _cal_rows)
                if _cal_answer:
                    _fy_lines = [ln for r in _pm_rows if int(r.get("houses") or 0) for ln in _pmay_lines(_pm_det, r)]
                    if _fy_lines and len(_pm_rows) == 1:
                        _cal_answer += (f"\n\n(\"{_cy}\" was read as calendar year {_cy}, January–December. For FY "
                                        f"{_cy}-{(_cy + 1) % 100:02d}, April {_cy} – March {_cy + 1}: " + "; ".join(
                                            ln if ln[:2].isupper() else ln[0].lower() + ln[1:]   # keep "PMAY-G"
                                            for ln in _fy_lines) + ".)")
                    _pm_det, _pm_rows, _pm_answer = _cal, _cal_rows, _cal_answer
        if _pm_answer:
            _pm_answer = _pmay_expenditure_not_held(_pm_det, _pm_answer)
            _pm_rows = _pmay_display_rows(_pm_det, _pm_rows)
            return {
                "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                "resolved_entities": entity_result["resolved"], "sql": _pm_det["shown"],
                "sql_query": _pm_det["shown"], "row_count": len(_pm_rows), "rows": _pm_rows[:20],
                "data": _pm_rows, "answer": _pm_answer,
            }
        if (_pm_det["dim"] == "village" and len(_pm_det["entities"]) == 1 and _pm_det.get("date") is None
                and _pm_det.get("year_key") is None and not _pm_det.get("stages")):
            _ph = await fetch_rows(
                "SELECT COUNT(*) AS placeholders, MAX(lgd_village_name) AS name, MAX(lgd_block) AS block, "
                "MAX(lgd_district) AS district FROM curated.v_pmay WHERE village_code = $1",
                [int(_pm_det["entities"][0])])
            _ph_row = dict(_ph[0]) if _ph and _ph[0]["placeholders"] else None
            return {
                "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                "resolved_entities": entity_result["resolved"], "sql": _pm_det["shown"],
                "sql_query": _pm_det["shown"], "row_count": 0, "rows": [], "data": [],
                "answer": _pmay_no_houses_answer(_pm_det, _ph_row, entity_result.get("display") or {}),
            }
        logger.info("PMAY-G deterministic query found no houses for the place — model path")
    _mg_det = _mg_admin or (
        (_mg_women["sql"], _mg_women["params"], _mg_women["shown"]) if _mg_women else None
    ) or _mgnrega_job_cards_query(question, schemes, entity_result["resolved"]) \
        or _mgnrega_villages_active_query(question, schemes, entity_result["resolved"]) \
        or _mgnrega_combined_facts_query(question, schemes, entity_result["resolved"]) \
        or _mgnrega_breakdown_query(question, schemes, entity_result["resolved"]) \
        or _mgnrega_wage_material_query(question, schemes, entity_result["resolved"]) \
        or _cme_sector_query(question, schemes, entity_result["resolved"])         or _fp_status_cohort_query(question, schemes, entity_result["resolved"])         or _focus_legacy_duplicates_query(question, schemes, entity_result["resolved"])         or _focus_legacy_fy_compare_query(question, schemes, entity_result["resolved"])         or _metric_catalog_query(question, schemes, entity_result)
    d.update(mg_admin=_mg_admin, mg_women=_mg_women, mg_det=_mg_det)
    return None


def _sql_reads_a_table(sql: str) -> bool:
    """The query reads some table, view, CTE or table function (a FROM / JOIN
    source), from the parsed tree. Unparseable text counts as reading one: it
    is left to the SQL guard and the repair loop, not answered from the KB."""
    trees = sql_ast.parse(sql)
    if not trees:
        return True
    return any(True for t in trees for _ in t.find_all(exp.Table))


# ── the fixed (deterministic) queries, recognised on the tree / token stream ──
# Each fixed query opens with a /* <mark> */ comment or has a fixed shape; a
# string literal or column that happens to hold the same words does not count.
_CME_SECTOR_MARKS = frozenset({"cme-sector-count", "cme-sector-pending", "cme-sector-programmes", "cme-sector-workflow"})


def _sql_comment_marks(sql: "str | None") -> "set[str]":
    """Every comment in the query, stripped and lower-cased ('fl-duplicates')."""
    return {str(c).strip().lower() for tok in _sql_tokens(sql or "") for c in (tok.comments or ())}


def _sql_alias_names(sql: "str | None") -> "set[str]":
    """Every result-column alias anywhere in the query, lower-cased."""
    return {a.lower() for a in _sql_column_aliases(sql or "")}


def _sql_is_mg_combined_facts(sql: "str | None") -> bool:
    """_mgnrega_combined_facts_query's shape: WITH exp AS (…), emp AS (…)
    SELECT … FROM exp CROSS JOIN emp."""
    if not {"exp", "emp"} <= sql_ast.cte_names(sql or ""):
        return False
    return any(isinstance(j.this, exp.Table) and (j.this.name or "").lower() == "emp"
               and str(j.args.get("kind") or "").upper() == "CROSS" for j in sql_ast.joins(sql or ""))


class NoDataSourceQuery(Exception):
    """The generated SQL selects only literals. _data_path_error_result maps any
    such error to the knowledge-base fallback."""


async def _data_sql_stage(d: dict, scope: "auth.UserScope | None" = None) -> None:
    """The SQL to run: the deterministic query's, or generate_sql (graph: sql_generate)."""
    question, schemes, entity_result, _mg_det = d["question"], d["schemes"], d["entity_result"], d["mg_det"]
    d["per_scheme"] = None
    # SQL_EXAMPLES_SOURCE=qdrant (D-074, 2026-10-27): the prompt's worked
    # examples come from megh_sql_metadata. Searched here, once, because
    # build_sql_prompt is synchronous; a failure keeps the YAML banks. With
    # "yaml" (the default) this does nothing.
    if not _mg_det:
        await sql_examples.prefetch(prompt_builder._fewshot_ranking_text(question, entity_result), schemes)
    # A cross-scheme question always runs per scheme (D-062): each scheme's own
    # prompt, few-shots and guards, never one query over several schemas (KI-280).
    if not _mg_det and (d.get("cross") or _per_scheme_needed(question, schemes, entity_result)):
        await _per_scheme_generate(d)
        return
    sql = _mg_det[2] if _mg_det else await generate_sql(question, schemes, entity_result)
    if sql and not _sql_reads_a_table(sql):
        # "What is the toll-free helpline number for MGNREGA complaints?" was
        # answered "1800-103-4000" from SELECT '1800-103-4000' AS helpline_number
        # — a value the model typed, not read (and SELECT NULL on a re-run). A
        # query with no FROM can only return invented values: answer from the
        # reference documents instead (General TC-015, test run 2026-10-06).
        raise NoDataSourceQuery("generated SQL reads no table")
    d["sql"] = sql


# ── One query per scheme when the combined prompt does not fit (KI-011) ──────
# Every scheme's backbone rules are what keep its numbers right, so a question
# over several schemes is never answered from a TRIMMED backbone. When the
# combined SQL prompt is over the 30B's budget (two large schemes ~16.8k
# tokens, all six ~30k, against 15,360 — measured 2026-10-16), each scheme gets
# its own prompt, its own SQL, its own guards / authorization / repairs, and the
# rows come back together tagged with their scheme.

def _per_scheme_needed(question: str, schemes: list[str], entity_result: dict) -> bool:
    if len(schemes or []) < 2:
        return False
    try:
        prompt = prompt_builder.build_sql_prompt(question, schemes, entity_result)
    except Exception:  # noqa: BLE001 — measuring must never cost the answer
        return False
    over = context_budget.approx_tokens(prompt) > context_budget.budget_for("sql")
    context_budget.log_decision("sql_generate", per_scheme=over, schemes=schemes)
    return over


def _per_scheme_question(question: str, scheme: str) -> str:
    return f"{(question or '').rstrip(' ?.')} — answer for {scheme} only?"


def _per_scheme_q(d: dict, scheme: str) -> str:
    """The question one scheme's SQL is written for: a cross-scheme question's
    own one-scheme question (_cross_scheme_subquestion), else the suffixed form."""
    q = ((d.get("cross") or {}).get("questions") or {}).get(scheme)
    return q or _per_scheme_question(d["question"], scheme)


_CROSS_JOINERS = (" and ", ", ", " & ", " vs. ", " vs ", " versus ", " or ", " with ", " / ", "/")


def _cross_scheme_base_question(question: str, scheme: str) -> str:
    """The question with every scheme it names replaced by `scheme`, repeats
    folded: "top ten villages in Mgnrega and pmay" -> "top ten villages in
    PMAY-G". The fallback when the model's one-scheme question fails its checks.
    "Compare MGNREGA and PMAY-G spending — answer for MGNREGA only?" still named
    PMAY-G, and the MGNREGA SQL went to the cross-scheme money view, failed four
    repairs and MGNREGA dropped out of the answer (D-062 live check, 2026-10-22)."""
    mark = "\x00"
    text = question or ""
    for pat in _SCHEME_NAME_MATCHER.values():
        text = pat.sub(mark, text)
    text = cross_scheme._BARE_FOCUS.sub(mark, text)
    if mark not in text:
        return _per_scheme_question(question, scheme)
    changed = True
    while changed:
        changed = False
        for j in _CROSS_JOINERS:
            for a, b in ((mark + j + mark, mark), ("between " + mark, mark)):
                if a in text:
                    text, changed = text.replace(a, b), True
    return collapse_ws(text.replace(mark, scheme)).strip()


def _cross_subquestion_numbers(text: str) -> set[str]:
    """The numbers in a question, years left out, "ten" read as 10."""
    years_text = " ".join(str(y) for y in context_policy.extract_year_keys(text))
    nums = _numbers(_GAP_YEAR.sub(" ", text)) - _numbers(years_text)
    return nums | {str(_LIST_COUNT_WORDS[w]) for w in (text or "").lower().replace("?", " ").split()
                   if w in _LIST_COUNT_WORDS and w not in ("zero", "one")}


def _cross_subquestion_violation(question: str, out: str, scheme: str) -> "str | None":
    """What a one-scheme question changed that it must not, else None: 'shape',
    'scheme' (it must name `scheme` and no other), 'place', 'year', 'number'.
    Narrower than the rephraser's checks on purpose: a one-scheme question drops
    filler ("I have a query"), turns "Compare …" into "What is …" and names the
    scheme's figure, all of which the rephraser rejects."""
    if not (3 <= len(out) <= max(300, 3 * len(question or ""))) or any(c in out for c in "{}[]`") \
            or _reads_like_sql(out):
        return "shape"
    if _exact_schemes(out) != {scheme}:
        return "scheme"
    gloss = _rephrase_gloss(question)
    if set(context_policy._places(out)) != set(context_policy._places(gloss)):
        return "place"
    if context_policy.extract_year_keys(out) != context_policy.extract_year_keys(gloss):
        return "year"
    if _cross_subquestion_numbers(out) != _cross_subquestion_numbers(gloss):
        return "number"
    return None


async def _cross_scheme_subquestion(question: str, scheme: str) -> str:
    """The one-scheme question for `scheme` (D-062): the rewrite model's, when it
    keeps the question's places, years, numbers, measures and names and names
    only `scheme` (the rephraser's own checks, against the fallback question);
    else the fallback. "Which scheme has the highest beneficiary count in each
    district — for MGNREGA only?" was answered with LIMIT 1, the top district."""
    base = _cross_scheme_base_question(question, scheme)
    try:
        out = await llm.call_rewriter(prompt_builder.build_cross_subquestion_prompt(question, scheme),
                                      max_tokens=120, role="cross-subquestion")
        out = (out or "").strip().splitlines()[0].strip().strip('"').strip("'").strip() if (out or "").strip() else ""
    except Exception as e:  # noqa: BLE001 — the fallback question always goes on
        logger.warning("cross-scheme sub-question failed for %s (%s) — %r", scheme, e, base)
        return base
    violation = _cross_subquestion_violation(question, out, scheme) if out else "empty"
    if violation:
        logger.info("cross-scheme sub-question for %s rejected (%s): %r — %r", scheme, violation, out, base)
        return base
    logger.info("cross-scheme sub-question for %s: %r", scheme, out)
    return out


async def _per_scheme_generate(d: dict) -> None:
    """generate_sql once per scheme, in parallel. d["per_scheme"] = [[scheme, sql or
    None, error or None], ...]; d["sql"] = the statements joined (what the
    authorize node checks)."""
    question, schemes, entity_result = d["question"], d["schemes"], d["entity_result"]
    gaps = _cross_scheme_gaps(schemes, entity_result["resolved"], entity_result.get("display"),
                              d["cross"].get("text") or question) if d.get("cross") else {}
    asked = [s for s in schemes if s not in gaps]
    if d.get("cross"):
        subs = await asyncio.gather(*(_cross_scheme_subquestion(question, s) for s in asked))
        d["cross"] = {**d["cross"], "questions": dict(zip(asked, subs))}
    outs = await asyncio.gather(*(generate_sql(_per_scheme_q(d, s), [s], entity_result)
                                  for s in asked), return_exceptions=True)
    plan: list = [[s, None, _NOT_HELD + gaps[s]] for s in schemes if s in gaps]
    for s, out in zip(asked, outs):
        if isinstance(out, (llm.ModelBusyError, asyncio.TimeoutError, httpx.TimeoutException,
                            httpx.TransportError)):
            raise out                       # the gateway, not the question
        if isinstance(out, Exception) or not out or not _sql_reads_a_table(out):
            plan.append([s, None, f"no query ({type(out).__name__ if isinstance(out, Exception) else 'no table'})"])
        else:
            plan.append([s, out, None])
    if not any(sql for _, sql, _ in plan):
        raise NoDataSourceQuery("no scheme produced a query")
    d["per_scheme"] = plan
    d["sql"] = "\n;\n".join(sql for _, sql, _ in plan if sql)
    logger.info("per-scheme SQL (KI-011): %s", [(s, bool(sql)) for s, sql, _ in plan])


async def _data_per_scheme_rows(d: dict, scope: "auth.UserScope | None" = None) -> None:
    """Run each scheme's query through the normal rewrites, guards, verifier and
    repair loop (graph: execute_attempt). A scheme that still fails is recorded
    in d["per_scheme"] and named in the answer notes; if every scheme fails, the
    turn fails like any other unanswerable query."""
    question, entity_result = d["question"], d["entity_result"]
    rows_all: list[dict] = []
    final_sql: list[str] = []
    for item in d["per_scheme"]:
        s, sql = item[0], item[1]
        if not sql:
            continue
        q = _per_scheme_q(d, s)
        for attempt in range(MAX_SQL_REPAIRS + 1):
            sql = await _scheme_sql_rewrites(q, [s], entity_result, sql)
            if attempt and _repaired_sql_denial(scope, [s], entity_result, sql) is not None:
                item[1], item[2] = None, "not authorised for your account"
                break
            try:
                rows = await _execute_one_attempt(q, [s], entity_result, sql)
            except Exception as e:  # noqa: BLE001
                if db_is_connection_error(e):
                    raise DatabaseUnavailableError(str(e)) from e
                if attempt == MAX_SQL_REPAIRS:
                    item[1], item[2] = None, f"query failed: {str(e)[:120]}"
                    break
                logger.warning("per-scheme SQL failed for %s (attempt %d/%d), repairing: %s",
                               s, attempt + 1, MAX_SQL_REPAIRS + 1, e)
                sql = await _repair_sql(q, [s], entity_result, sql, str(e) or type(e).__name__)
                continue
            item[1] = sql
            final_sql.append(sql)
            # the scheme tag wins over any scheme literal the query selected itself
            # ('CM_ELEVATE' AS scheme, live 2026-10-16)
            rows_all.extend({**dict(r), "scheme": s} for r in rows)
            break
    if not final_sql:
        raise ValueError("no scheme's query could be answered: "
                         + "; ".join(f"{s}: {err}" for s, _, err in d["per_scheme"]))
    d["sql"] = "\n;\n".join(final_sql)
    d["rows"] = rows_all


_NOT_HELD = "not held: "     # a per_scheme error that is the scheme's data, said as written


def _per_scheme_notes(d: dict) -> list[str]:
    if not d.get("per_scheme"):
        return []
    items = d["per_scheme"]
    held = [err[len(_NOT_HELD):] for s, sql, err in items if not sql and (err or "").startswith(_NOT_HELD)]
    missing = [(s, err) for s, sql, err in items if not sql and not (err or "").startswith(_NOT_HELD)]
    notes = ["The result covers several schemes; each row's `scheme` column says which scheme it "
             "comes from. Report each scheme's figures under its own name, and never add figures "
             "of different schemes together (they count different things)."]
    if d.get("cross"):
        notes.append("Answer exactly what the question asks (its ranking, its top N, its level — "
                     "village, block, district — its years), one part per scheme. Say what each "
                     "scheme's figure counts (for example persons employed, houses sanctioned, "
                     "beneficiaries, applications) and which years it covers. A ranking or list "
                     "gives every row of each scheme, one line each, under the scheme's name. A "
                     "scheme with no rows has no records for what was asked: say that, never 0. "
                     "PMAY-G money: the amount released is what was paid, the sanctioned amount "
                     "what was approved — name which one each figure is. Every amount in the result "
                     "is in ₹ crore (its column ends _crore): write it as ₹<figure> crore and compare "
                     "amounts only in that unit.")
        if d["cross"].get("place_unrecognised"):
            notes.append("The place named in the question was not recognised, so every figure is "
                         "statewide: say so first.")
        # A scheme with no figure is said by _cross_scheme_no_figure_lines after the
        # composer: told to the composer, "Focus Plus has no data for FY 2024-25" set
        # off the hedge check and the CM Elevate Legacy figures were thrown away for
        # a row dump (D-062 live check, 2026-10-22).
        notes.append("Write only about the schemes in the result's `scheme` column; a line about "
                     "any other scheme is added after your answer.")
        return notes
    for h in held:
        notes.append(f"{h}. Say exactly this for that scheme; give no figure for it.")
    if missing:
        notes.append("No figure could be computed for: "
                     + ", ".join(s for s, _ in missing)
                     + ". Say so plainly for each of these schemes; do not guess a figure.")
    return notes


async def _data_authorize_stage(d: dict, scope: "auth.UserScope | None" = None) -> "dict | None":
    """auth.authorize on the SQL; the denial result, or None (graph: authorize)."""
    schemes, entity_result, sql = d["schemes"], d["entity_result"], d["sql"]
    # Authorization — role/scope vs. what the query actually asks for. Runs on the
    # generated SQL so granularity (GROUP BY) and geography literals are visible.
    if scope is not None and settings.AUTH_ENABLED:
        decision = auth.authorize(scope, schemes=schemes,
                                  resolved_entities=entity_result["resolved"], sql=sql)
        if not decision.allow:
            logger.info("auth deny (%s) user=%s: %s", decision.check, scope.user_id, decision.reason)
            return _denied(decision, schemes, entity_result["resolved"])
    return None


async def _data_deterministic_rows(d: dict, scope: "auth.UserScope | None" = None) -> None:
    """Run the deterministic MGNREGA query (parameter-bound, no repair loop)."""
    _mg_det = d["mg_det"]
    # A catalogue query's measure text comes from semantic.metric_definitions,
    # not from this code: it runs on the read-only pool (D-071).
    _run = _c16_fetch_rows_readonly if metric_catalog.is_catalog_sql(_mg_det[0]) else fetch_rows
    rows = [dict(r) for r in await _run(_mg_det[0], _mg_det[1])]
    logger.info("MGNREGA deterministic query: %s | params=%s", _mg_det[2].replace("\n", " "),
                _mg_det[1])
    d["rows"] = rows


async def _data_post_rows_stage(d: dict, scope: "auth.UserScope | None" = None) -> "dict | None":
    """Deterministic post-row answers, composer notes and the premise check (graph: post_rows)."""
    question, schemes, entity_result = d["question"], d["schemes"], d["entity_result"]
    sql, rows, _mg_admin, _mg_women = d["sql"], d["rows"], d["mg_admin"], d["mg_women"]
    if _mg_admin:
        answer = await _mgnrega_admin_expenditure_answer(rows, entity_result.get("display") or {},
                                                         statewide=not (scope and scope.geo_restricted))
        return {
            "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
            "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
            "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": answer,
        }
    if schemes == ["MGNREGA"] and "mg-job-cards" in _sql_comment_marks(sql):
        # written from the rows the query read: the year(s) in the answer are the SQL's
        answer = _mgnrega_job_cards_answer(rows, entity_result.get("display") or {})
        return {
            "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
            "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
            "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": answer,
        }
    if schemes == ["CM Elevate"] and _sql_comment_marks(sql) & _CME_SECTOR_MARKS:
        _cs = _cme_sector_answer(question, sql, rows, entity_result.get("display") or {})
        if _cs:
            return {
                "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
                "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": _cs,
            }
    if schemes == ["Focus Legacy"] and "fl-fy-compare" in _sql_comment_marks(sql) and rows:
        _fc = _focus_legacy_fy_compare_answer(rows, (d.get("mg_det") or (None, []))[1],
                                              entity_result.get("display") or {})
        # A gap year the user named (FY 2023-24) was swapped for the nearest year with
        # data by _apply_year_gap; its note says so and must lead the answer.
        _gap = [n for n in entity_result.get("notes") or [] if "holds no data" in n]
        if _fc and _gap:
            _fc = " ".join(_gap) + "\n\n" + _fc
        if _fc:
            return {
                "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
                "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": _fc,
            }
    if schemes == ["Focus Legacy"] and "fl-duplicates" in _sql_comment_marks(sql) and rows:
        _fd = _focus_legacy_duplicates_answer(rows, entity_result.get("display") or {})
        if _fd:
            return {
                "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
                "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": _fd,
            }
    if schemes == ["Focus Plus"] and "fp-status-cohort" in _sql_comment_marks(sql) and rows:
        return {
            "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
            "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
            "row_count": len(rows), "rows": rows[:20], "data": rows,
            "answer": _fp_status_cohort_answer(sql, rows, (d.get("mg_det") or (None, []))[1]),
        }
    if schemes == ["CM Elevate"]:
        _ps = _cme_programme_sector_answer(rows, entity_result.get("display") or {})
        if _ps:
            return {
                "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
                "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": _ps,
            }
    if schemes == ["MGNREGA"] and not _mg_women and len(rows) == 1 \
            and {"wage_exp_lakh", "material_exp_lakh"} <= _sql_alias_names(sql):
        return {
            "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
            "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
            "row_count": len(rows), "rows": rows[:20], "data": rows,
            "answer": _mgnrega_wage_material_answer(rows[0], entity_result.get("display") or {}),
        }
    if schemes == ["MGNREGA"] and not _mg_women and len(rows) == 1 \
            and {"unskilled_wages_lakh", "total_lakh"} <= _sql_alias_names(sql):
        _bd = _mgnrega_breakdown_answer(rows[0], entity_result.get("display") or {})
        if _bd:
            return {
                "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
                "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": _bd,
            }
    if schemes == ["MGNREGA"] and not _mg_women and _sql_is_mg_combined_facts(sql) and len(rows) == 1:
        # The combined expenditure + employment answer is written here from the
        # one row: the composer dropped the person-days figure ("24.54 crore. No
        # expenditure…" for West Khasi Hills FY 2025-26, MGNREGA sheet DATA-030,
        # run 2026-10-09) — a figure the question asked for, silently missing.
        _combined = _mgnrega_combined_facts_answer(rows[0], entity_result.get("display") or {})
        if _combined:
            return {
                "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
                "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": _combined,
            }
    if schemes == ["MGNREGA"]:
        _empty = await _mgnrega_empty_answer(sql, rows, entity_result.get("display") or {},
                                             entity_result["resolved"])
        if _empty:
            return {
                "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
                "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": _empty,
            }

    # A number the question states as already-true ("the 1.71 L sanctioned
    # houses") is never part of the SQL — check it against the result so the
    # composer corrects a false premise instead of repeating it as fact.
    notes = list(entity_result.get("notes") or [])
    notes.extend(_per_scheme_notes(d))
    notes.extend(_genuine_zero_notes(sql))
    notes.extend(_sector_not_tracked_notes(rows))
    _style = ""
    if schemes == ["MGNREGA"]:
        notes.extend(_mgnrega_answer_notes(question, sql, rows))
        _women_sql = "women_employment_provided" in (sql or "").lower()
        if not _women_sql:
            # A women figure over an unrecorded year is NOT a genuine zero.
            notes.extend(_mgnrega_null_zero_notes(rows))
        if _mg_women:
            span = _women_span(_mg_women["years"])
            notes.append(
                f"This figure covers {span}" + (
                    " — every year that has women-employment data; no financial year was named"
                    if _mg_women["all_years"] else "") + ". Say which year(s) it covers." + (
                    f" Women employment is not recorded at source for "
                    f"{', '.join('FY ' + y['fy'] for y in _mg_women['missing'])}; say so, never call it zero."
                    if _mg_women["all_years"] and _mg_women["missing"] else ""))
        elif _women_sql and _MGNREGA_YEAR_WOMEN:
            _miss = {y["year_key"]: y["fy"] for y in _MGNREGA_YEAR_WOMEN if y["women"] <= 0}
            _yrs = _mgnrega_women_sql_years(sql)
            if _miss and _yrs and _yrs <= set(_miss):
                # Every year the query reads has no women data (e.g. a ranking for FY 2025-26).
                answer = (f"Women employment is not recorded in the MGNREGA data for "
                          f"{', '.join('FY ' + _miss[k] for k in sorted(_yrs))} — the women column is 0 "
                          "on every record statewide (not populated at source), so no women figure, "
                          "share or ranking can be given for that year. Ask for FY "
                          f"{[y['fy'] for y in _MGNREGA_YEAR_WOMEN if y['women'] > 0][-1]} instead.")
                return {
                    "route": "data", "intent": "DATA", "confidence": "high", "schemes": schemes,
                    "resolved_entities": entity_result["resolved"], "sql": sql, "sql_query": sql,
                    "row_count": len(rows), "rows": rows[:20], "data": rows, "answer": answer,
                }
            if _miss:
                notes.append(
                    f"Women employment is not recorded at source for "
                    f"{', '.join('FY ' + v for v in _miss.values())} (0 on every record). Never describe "
                    "a women figure for that year as zero or as a genuine zero.")
    if schemes == ["CM Elevate Legacy"]:
        notes.extend(_cm_legacy_answer_notes(sql, rows))
        notes.extend(_cm_legacy_small_money_notes(rows))
        notes.extend(await _cm_legacy_exact_totals(sql, rows))
        _style = _cm_legacy_style_block(question)
    _fl_total = _fl_unplaced = None
    if schemes == ["Focus Legacy"]:
        notes.extend(_focus_legacy_answer_notes(question))
        _fl_unplaced = await _focus_legacy_unplaced_row(sql, rows)
        if _fl_unplaced:
            notes.append(_focus_legacy_unplaced_note(*_fl_unplaced))
        _fl_total = await _focus_legacy_list_total(sql, rows)
        if _fl_total:
            notes.append(f"{_fl_total[0]:,} {_fl_total[1]} match in total; the result lists only the "
                         f"first {len(rows)}. Say that {_fl_total[0]:,} {_fl_total[1]} match, then name "
                         "the top ones — never present the list as complete.")
    if settings.PREMISE_CHECK_ENABLED:
        try:
            # an "(LGD 904712)" chip tag is an identifier, not an assumed figure
            notes.extend(premise_check.check_premises(_CHIP_LGD_CODE_MATCH.sub("", question), rows))
        except Exception:  # noqa: BLE001
            logger.warning("premise check failed — continuing without it", exc_info=True)

    if schemes == ["Focus Legacy"]:
        rows = await _fl_add_group_names(rows)
    _fl_breakdown = (_focus_legacy_breakdown_answer(sql, rows, entity_result.get("display") or {}, _fl_unplaced)
                     or _focus_legacy_group_list_answer(rows, entity_result.get("display") or {},
                                                        _fl_total[0] if _fl_total else None)
                     if schemes == ["Focus Legacy"] else None)
    d.update(rows=rows, notes=notes, style=_style, fl_total=_fl_total, fl_unplaced=_fl_unplaced,
             fl_breakdown=_fl_breakdown)
    return None


async def _data_compose_stage(d: dict, scope: "auth.UserScope | None" = None) -> None:
    """compose_response, unless a deterministic Focus Legacy answer exists (graph: compose)."""
    question, schemes, entity_result, sql, rows = (d["question"], d["schemes"], d["entity_result"],
                                                   d["sql"], d["rows"])
    notes, _style, _fl_breakdown = d["notes"], d["style"], d["fl_breakdown"]
    _fl_total, _fl_unplaced = d["fl_total"], d["fl_unplaced"]
    if d.get("cross") and rows:
        rows = _cross_scheme_rows_in_crore(d.get("per_scheme") or [], rows)
        d["rows"] = rows
    answer = _fl_breakdown or await compose_response(question, sql, rows, notes=notes,
                                    entities=await _entities_with_sql_year(sql, entity_result.get("display")),
                                    schemes=schemes, style_examples=_style,
                                    extra_numbers=({str(_fl_total[0])} if _fl_total else set()) | {
                                        str(int(n)) for v in (_fl_unplaced[1] if _fl_unplaced else {}).values()
                                        for n in [_as_number(v)] if n is not None} or None)
    if d.get("cross") and rows and not _fl_breakdown:
        # Every scheme with rows is in the answer. "Top 5 blocks in MGNREGA and
        # PMAY-G by beneficiaries" was answered "MGNREGA has no beneficiary
        # figures recorded for any block" over five MGNREGA rows (D-062 live
        # check, 2026-10-22): one retry naming them, then a section per scheme.
        entities = await _entities_with_sql_year(sql, entity_result.get("display"))
        left = _cross_schemes_left_out(answer, rows)
        if left:
            logger.warning("cross-scheme answer left out %s — retry", left)
            answer = await compose_response(
                question, sql, rows, entities=entities, schemes=schemes, style_examples=_style,
                notes=list(notes or []) + [
                    f"An earlier answer left out {', '.join(left)}, whose rows ARE in the result. Give "
                    "every scheme's figures from its own rows; never say a scheme with rows has no data."])
            left = _cross_schemes_left_out(answer, rows)
        if left:
            logger.warning("cross-scheme answer still left out %s — a section per scheme", left)
            answer = _cross_scheme_sections(rows, entities)
    d["answer"] = answer


# The rupee money columns of the four rupee schemes' views (MGNREGA's, in lakh,
# are _MGNREGA_MONEY_COLS).
_CROSS_RUPEE_COLS = frozenset({
    "sanctioned_amount", "amount_released", "amount_pending", "amount_disbursed", "bank_sanctioned_amount",
    "total_disbursement", "total_loan_disbursement", "total_subsidy_disbursement",
    "loan_disbursement_1", "loan_disbursement_2", "loan_disbursement_3",
    "subsidy_disbursement_1", "subsidy_disbursement_2", "subsidy_disbursement_3"})


def _cross_money_outputs(scheme: str, sql: "str | None") -> dict:
    """{output column (lower-case): 'lakh' / 'rupees'} for the outer SELECT's
    columns that read only `scheme`'s money columns, unscaled: no division or
    multiplication (already crore, or a share) and no average (a per-unit
    figure). Read on the tree: the model names columns freely
    ("total_financial_assistance" is SUM(amount_disbursed))."""
    if scheme == "MGNREGA":
        raw, unit = _MGNREGA_MONEY_COLS, "lakh"
    elif scheme in _CROSS_RUPEE_SCHEMES:
        raw, unit = _CROSS_RUPEE_COLS, "rupees"
    else:
        return {}
    out = {}
    for tree in sql_ast.parse(sql or ""):
        sel = sql_ast.outer_select(tree)
        for e in (sel.expressions if sel is not None else []):
            name = (e.alias_or_name or "").lower()
            cols = {(c.name or "").lower() for c in e.find_all(exp.Column)}
            if name and cols and cols <= raw and e.find(exp.Div, exp.Mul, exp.Avg, exp.Count) is None:
                out[name] = unit
    return out


def _cross_scheme_rows_in_crore(per_scheme: list, rows: list[dict]) -> list[dict]:
    """Every scheme's money in ₹ crore, and a scheme's all-NULL rows dropped,
    before the composer reads the rows. "Which scheme provided the highest
    total financial assistance?" named Focus Plus for its 1,197,392,500 RUPEES
    over MGNREGA's 3,628.67 CRORE (D-062 sheet run 2026-10-22): every figure was
    in a row, so the faithfulness check passed. An aggregate over no records is
    one NULL row ("- MGNREGA" with nothing, Baghmara-Municipal Board block)."""
    money = {s: _cross_money_outputs(s, sql_s) for s, sql_s, _e in per_scheme if sql_s}
    one_row = {s for s in {r.get("scheme") for r in rows} if sum(r.get("scheme") == s for r in rows) == 1}
    out = []
    for r in rows:
        s = r.get("scheme")
        vals = [v for k, v in r.items() if k != "scheme"]
        if all(v is None for v in vals):
            continue
        # one aggregate row over nothing: SUMs NULL, COUNTs 0 ("MGNREGA — financial
        # years: 0" in East Shillong, which MGNREGA does not cover)
        if s in one_row and None in vals and all(v is None or _as_number(v) == 0 for v in vals):
            continue
        new = {}
        for k, v in r.items():
            unit = (money.get(s) or {}).get(str(k).lower(), "")
            n = _as_number(v) if unit else None
            if n is None:
                new[k] = v
                continue
            c = float(n) / (100.0 if unit == "lakh" else 1e7)
            new[f"{k}_crore"] = round(c, 2) if abs(c) >= 0.01 or c == 0 else round(c, 6)
        out.append(new)
    return out


# Columns that name a row, not a figure of it: a code, key, id or year is not
# what a scheme's answer has to state.
_CROSS_NOT_FIGURE_PARTS = ("code", "key", "_id", "year")


def _cross_schemes_left_out(answer: str, rows: list[dict]) -> list[str]:
    """The schemes with rows none of whose figures (or, for a list of names,
    none of whose names) the answer states."""
    flat = (answer or "").replace(",", "").lower()
    out = []
    for s in dict.fromkeys(r.get("scheme") for r in rows if r.get("scheme")):
        rows_s = [r for r in rows if r.get("scheme") == s][:40]
        forms, names = set(), set()
        for r in rows_s:
            for k, v in r.items():
                if k == "scheme" or any(p in str(k).lower() for p in _CROSS_NOT_FIGURE_PARTS):
                    continue
                n = _as_number(v)
                if n is None:
                    if isinstance(v, str) and len(v.strip()) >= 3:
                        names.add(v.strip().lower())
                    continue
                if n == 0:
                    continue
                forms |= {str(n), f"{float(n):.2f}".rstrip("0").rstrip("."), f"{float(n):.2f}"}
        if forms:
            if not any(f in flat for f in forms):
                out.append(s)
        elif names and not any(nm in flat for nm in names):
            out.append(s)
    return out


def _cross_scheme_sections(rows: list[dict], entities: "dict | None") -> str:
    """One deterministic section per scheme, each from that scheme's own rows."""
    parts = []
    for s in dict.fromkeys(r.get("scheme") for r in rows if r.get("scheme")):
        rows_s = [{k: v for k, v in r.items() if k not in ("scheme", "scheme_code")}
                  for r in rows if r.get("scheme") == s]
        parts.append(f"**{s}:** {_framed_fallback(rows_s, [s], entities)}")
    return "\n\n".join(parts)


_CROSS_LOWEST = Matcher(W("lowest", "least", "minimum", "smallest", "lower", "less", "fewest"))


def _cross_scheme_figure(row: dict, money: bool) -> "tuple[str, float] | None":
    """The one figure a scheme's single row is ranked by: its ₹ crore amount for a
    money question (the total disbursed / released / spent when there are several),
    else its one count. None when that is not one clear figure."""
    nums = [(str(k), float(n)) for k, v in row.items()
            if k != "scheme" and not any(p in str(k).lower() for p in _CROSS_NOT_FIGURE_PARTS)
            for n in [_as_number(v)] if n is not None]
    is_crore = lambda k: "crore" in k.lower() or k.lower().endswith("_cr")  # noqa: E731
    nums = [x for x in nums if is_crore(x[0]) == money]
    if len(nums) > 1:
        nums = [x for x in nums if "total" in x[0].lower() or "disburs" in x[0].lower()] or nums
        nums = nums if len(nums) == 1 else [x for x in nums if "total" in x[0].lower()]
    return nums[0] if len(nums) == 1 else None


def _cross_scheme_leader(answer: str, rows: list[dict], question: str) -> str:
    """"Which scheme is highest / lowest" with one figure per scheme: the answer
    leads with the scheme the rows rank first. The composer named Focus Plus
    (₹119.74 crore) the highest over MGNREGA's ₹3,628.67 crore, both in its own
    answer (D-062 sheet run 2026-10-22, "highest total financial assistance");
    every figure was right, so only this check sees it."""
    if not cross_scheme._RANK.search(question or ""):
        return answer
    schemes = list(dict.fromkeys(r.get("scheme") for r in rows if r.get("scheme")))
    if len(schemes) < 2 or any(sum(r.get("scheme") == s for r in rows) != 1 for s in schemes):
        return answer
    money = bool(cross_scheme._MONEY.search(question or ""))
    figs = {s: _cross_scheme_figure(next(r for r in rows if r.get("scheme") == s), money) for s in schemes}
    if any(f is None for f in figs.values()):
        return answer
    low = bool(_CROSS_LOWEST.search(question or ""))
    leader = (min if low else max)(schemes, key=lambda s: figs[s][1])
    first = (answer or "").partition(". ")[0]
    hits = [(h.start(), s) for s, pat in _SCHEME_NAME_MATCHER.items() for h in [pat.search(first)] if h]
    if hits and min(hits)[1] == leader:
        return answer
    def fig(s: str) -> str:
        k, v = figs[s]
        return f"₹{v:,.2f} crore" if money else f"{_fmt_num(int(v) if v.is_integer() else v)} {_human_metric(k)}"
    logger.warning("cross-scheme answer led with %s, the rows rank %s first — ranked answer",
                   min(hits)[1] if hits else None, leader)
    ranked = sorted(schemes, key=lambda s: figs[s][1], reverse=not low)
    return (f"{leader} is the {'lowest' if low else 'highest'}, at {fig(leader)}. In order: "
            + "; ".join(f"{s} {fig(s)}" for s in ranked) + ".")


_CROSS_LIST_MAX = 25      # a longer list stays in the result table


def _cross_scheme_complete_lists(answer: str, rows: list[dict]) -> str:
    """Each scheme's list in full, numbered, when the answer names only part of
    it. "Top ten highest villages in Mgnrega and pmay" was answered with the
    first and the last village of each scheme (the composer writes one to three
    sentences), D-062 live check 2026-10-22."""
    low = (answer or "").lower()
    extra = []
    for s in dict.fromkeys(r.get("scheme") for r in rows if r.get("scheme")):
        rows_s = [r for r in rows if r.get("scheme") == s]
        if not 2 <= len(rows_s) <= _CROSS_LIST_MAX:
            continue
        lines, complete = [], True
        for i, r in enumerate(rows_s, 1):
            labels = [str(v).strip() for k, v in r.items() if k not in ("scheme", "scheme_code")
                      and isinstance(v, str) and _as_number(v) is None and str(v).strip()]
            figs = [f"{_fmt_num(n)} {_human_metric(str(k))}" for k, v in r.items()
                    if k != "scheme" and not any(p in str(k).lower() for p in _CROSS_NOT_FIGURE_PARTS)
                    for n in [_as_number(v)] if n is not None]
            if not labels:
                complete = True
                break
            if not all(lb.lower() in low for lb in labels):
                complete = False
            lines.append(f"{i}. {' / '.join(labels)}" + (f" — {', '.join(figs)}" if figs else ""))
        if not complete:
            extra.append(f"**{s}:**\n" + "\n".join(lines))
    if not extra:
        return answer
    return (answer or "").rstrip() + "\n\n" + "\n\n".join(extra)


def _cross_scheme_no_figure_lines(answer: str, per_scheme: list, rows: list[dict]) -> str:
    """A line for each scheme the answer has no figure for: its data does not
    hold what was asked, its query failed, or it matched no records. Added
    after the composer, never left to it (see _per_scheme_notes)."""
    with_rows = {r.get("scheme") for r in rows}
    lines = []
    for s, sql_s, err in per_scheme:
        if not sql_s and (err or "").startswith(_NOT_HELD):
            lines.append(err[len(_NOT_HELD):] + ".")
        elif not sql_s:
            lines.append(f"No {s} figure could be worked out for this question.")
        elif s not in with_rows:
            lines.append(f"{s} has no records matching this question.")
    if not lines:
        return answer
    return (answer or "").rstrip() + "\n\n" + " ".join(lines)


# "Which villages in Tikrikila assembly constituency received employment?" (whole
# constituency, no year) was answered "45 villages … 7,592 persons" from
# year_key = (SELECT MAX(year_key) FROM …) — right for FY 2025-26, but the answer
# never said which year, so it read as all years (MGNREGA DATA-014, test run
# 2026-10-06). The year a figure covers is part of the figure.
def _sql_latest_year_view(sql: "str | None") -> "str | None":
    """The view X of a `year_key = (SELECT MAX(year_key) FROM curated.X)` filter
    (lower-cased), else None."""
    for tree in sql_ast.parse(sql or ""):
        for node in tree.find_all(exp.EQ):
            for col, sub in ((node.this, node.expression), (node.expression, node.this)):
                if not (sql_ast._is_column(col, {"year_key"}) and isinstance(sub, exp.Subquery)):
                    continue
                sel = sub.this
                if not isinstance(sel, exp.Select) or len(sel.expressions) != 1:
                    continue
                agg = sel.expressions[0]
                if not (isinstance(agg, exp.Max) and sql_ast._is_column(agg.this, {"year_key"})):
                    continue
                frm = sel.args.get("from_") or sel.args.get("from")
                tb = frm.this if frm is not None else None
                if isinstance(tb, exp.Table) and (tb.db or "").lower() == "curated" and tb.name:
                    return tb.name.lower()
    return None
_YEAR_VIEWS = {"v_employment", "v_expenditure", "v_pmay", "v_focus_plus", "v_focus_legacy",
               "v_cm_elevate_disbursement"}


# The answer states the period the QUERY read, not the one the question named:
# 24 of 24 job-card answers said "across all financial years" over SQL pinned to
# year_key = 2025, because the composer and the closing scope line were told only
# that the question named no year (MGNREGA sheet DATA-007, run 2026-10-21).
async def _entities_with_sql_year(sql: "str | None", entities: "dict | None") -> "dict | None":
    """`entities` plus the one financial year the query's WHERE pins (a literal
    year_key = N / IN (N), or the latest-year subquery), when the question named
    none. A year range, several years or a per-year GROUP BY change nothing."""
    if not sql or (entities or {}).get("year"):
        return entities
    if any(c == "year_key" or c.startswith("financial_year") for c in sql_ast.group_by_columns(sql)):
        return entities
    keys: set[int] = set()
    for node in sql_ast.filter_conditions(sql, "year_key"):
        if node.find_ancestor(exp.Where) is None:
            continue                     # a CASE WHEN year_key = … inside SELECT is not a filter
        if not isinstance(node, (exp.EQ, exp.In)):
            return entities              # a range: not one year
        for v in sql_ast.filter_values(node, "year_key", numeric=True):
            try:
                keys.add(int(float(v)))
            except (TypeError, ValueError):
                return entities
    if len(keys) > 1:
        return entities
    if keys:
        y = keys.pop()
    else:
        view = _sql_latest_year_view(sql)
        if not view or view not in _YEAR_VIEWS:
            return entities
        try:
            # the view name is checked against _YEAR_VIEWS above, never taken from model text
            y = int((await fetch_rows(f"SELECT MAX(year_key) AS y FROM curated.{view}", []))[0]["y"])
        except Exception:  # noqa: BLE001 — without it the answer keeps the question's wording
            return entities
    return {**(entities or {}), "year": f"FY {y}-{(y + 1) % 100:02d}"}
def _c13_y20(w: str) -> bool:
    r"""A word that starts with 20 + two digits (anything may follow)."""
    return len(w) >= 4 and w[:2] == "20" and w[2:4].isdecimal()


# "FY 2023…" / "FY2023…", or "2023-24" / "2023 – 2024" / "2023/24"
_ANSWER_NAMES_A_YEAR = Matcher(Alt(
    Seq(W("fy"), _C1xGapIs(Pred(_c13_y20), _c1x_ws0)),
    Pred(lambda w: w[:2].lower() == "fy" and _c13_y20(w[2:])),
    Seq(Pred(lambda w: len(w) == 4 and _c13_y20(w)),
        _C1xGapIs(Pred(lambda w: 2 <= len(w) <= 4 and w.isdecimal()), lambda g: g.strip() in ("-", "–", "/"))),
))
_C13_NOT_A_LOAN = Matcher(Seq(_c1x_suffix("not"), W("a"), W("loan", prefix=True), sep="space"))


def _c13_followed_by_word(text: str, lead: str, word: str) -> bool:
    r"""lead, one or more spaces, then word (case-sensitive, may sit inside longer words)."""
    k = text.find(lead)
    while k >= 0:
        rest = text[k + len(lead):]
        if rest[:1].isspace() and rest.lstrip().startswith(word):
            return True
        k = text.find(lead, k + 1)
    return False


def _c13_fy_label(note: str) -> "str | None":
    r"""FY starting a word, optional spaces, four digits - two digits (case-sensitive): the "2023-24" after FY."""
    k = note.find("FY")
    while k >= 0:
        if k == 0 or not _c1x_is_word_char(note[k - 1]):
            q = k + 2
            while q < len(note) and note[q].isspace():
                q += 1
            lab = note[q:q + 7]
            if len(lab) == 7 and lab[:4].isdecimal() and lab[4] == "-" and lab[5:].isdecimal():
                return lab
        k = note.find("FY", k + 1)
    return None


async def _latest_year_guarantee(answer: str, sql: str) -> str:
    view = _sql_latest_year_view(sql)
    if not view or view not in _YEAR_VIEWS or _ANSWER_NAMES_A_YEAR.search(answer or ""):
        return answer
    try:
        # the view name is checked against _YEAR_VIEWS above, never taken from model text
        rows = await fetch_rows(f"SELECT MAX(year_key) AS y FROM curated.{view}", [])
        y = int(rows[0]["y"])
    except Exception:  # noqa: BLE001 — a note is an aid, never a reason to fail
        return answer
    return answer.rstrip() + f" This is for FY {y}-{(y + 1) % 100:02d}, the latest financial year in the data."


def _sql_filters_amount(sql: "str | None", amount: int) -> bool:
    """The query compares amount_disbursed with exactly `amount` (= 15000 or
    = '15000'), from the parsed tree."""
    for node in sql_ast.filter_conditions(sql or "", "amount_disbursed"):
        if not isinstance(node, exp.EQ):
            continue
        for v in sql_ast.filter_values(node, "amount_disbursed", numeric=True):
            try:
                if float(v) == amount:
                    return True
            except (TypeError, ValueError):
                continue
    return False


# Schemes whose money columns are in RUPEES (MGNREGA's total_exp is in lakh).
_CROSS_RUPEE_SCHEMES = ("PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate Legacy")


def _cross_scheme_answer_units(answer: str, per_scheme: list, rows: list[dict]) -> str:
    """₹ formatting for the rupee cells left after _cross_scheme_rows_in_crore (a
    per-unit figure: an average, a rate), read on that scheme's own rows: the
    single-scheme guarantees run only for one scheme, so a cross-scheme answer
    printed a bare "22,227,530,000.00" (D-062 live check, 2026-10-22). MGNREGA's
    money is crore by then, so its "add lakh" pass is not run here."""
    for s, sql_s, _err in per_scheme:
        if sql_s and s in _CROSS_RUPEE_SCHEMES:
            answer = _pmay_rupee_format(answer, [r for r in rows if r.get("scheme") == s])
    return answer


async def _data_guarantees_stage(d: dict, scope: "auth.UserScope | None" = None) -> None:
    """Per-scheme deterministic answer guarantees after composing (graph: guarantees)."""
    question, schemes, entity_result, sql, rows = (d["question"], d["schemes"], d["entity_result"],
                                                   d["sql"], d["rows"])
    answer, _fp_amount, _mg_women = d["answer"], d["fp_amount"], d["mg_women"]
    _fl_total, _fl_unplaced, _fl_breakdown = d["fl_total"], d["fl_unplaced"], d["fl_breakdown"]
    # A figure the composer spelled out ("Eighteen producer groups") becomes
    # digits when that value is in the result, every scheme (all-blocks run
    # 2026-10-02); a spelled-out number is invisible to the faithfulness checks.
    answer = _cme_digits_for_number_words(answer, rows)
    # A region total that includes a district its name does not suggest says so in
    # one line (ingestion team 2026-10-26: Khasi includes Ri Bhoi). The label is set
    # where the region resolves; the composer dropped it live, so it is guaranteed here.
    _reg_label = (entity_result.get("display") or {}).get("district") or ""
    if (entity_result.get("resolved") or {}).get("district_list_region") and "(includes " in _reg_label \
            and _reg_label.split("(includes ", 1)[1].rstrip(")") not in (answer or ""):
        answer = (answer or "").rstrip() + (
            f" {entity_result['resolved']['district_list_region']} here includes "
            f"{_reg_label.split('(includes ', 1)[1].rstrip(')')} district, as in the department's district-to-region list.")
    if d.get("cross"):
        answer = _cross_scheme_leader(answer, rows, d["cross"].get("text") or question)
        answer = _cross_scheme_complete_lists(answer, rows)
        answer = _cross_scheme_answer_units(answer, d.get("per_scheme") or [], rows)
        answer = _cross_scheme_no_figure_lines(answer, d.get("per_scheme") or [], rows)
    # A stated Focus Plus payment amount: the answer must say which payments it
    # covers, and that Focus Plus is not a loan when the user called it one.
    # The composer note alone was ignored live (2026-09-29: "Amount disbursed:
    # ₹466,430,000.00."), so it is guaranteed here (CLAUDE.md §5).
    if _fp_amount is not None and int(_fp_amount.value) in _FOCUSPLUS_PAYMENT_AMOUNTS \
            and _sql_filters_amount(sql, int(_fp_amount.value)):
        _n = f"₹{int(_fp_amount.value):,}"
        if _fp_amount.noun == "loan" and not _C13_NOT_A_LOAN.search(answer):
            answer = (answer.rstrip() + f" Focus Plus is a cash benefit, not a loan; this covers only the "
                      f"{_n} payments — {_FOCUSPLUS_PAYMENT_AMOUNTS[int(_fp_amount.value)]}.")
        elif not (_c13_followed_by_word(answer, _n, "payments")
                  or _c13_followed_by_word(answer, f"{int(_fp_amount.value):,}", "payments")):
            answer = (answer.rstrip() + f" This covers only the {_n} payments — "
                      f"{_FOCUSPLUS_PAYMENT_AMOUNTS[int(_fp_amount.value)]}.")
    if schemes == ["MGNREGA"]:
        answer = _mgnrega_top_one_wording(answer, sql, rows)
        answer = _mgnrega_money_units(answer, sql, rows)
        answer = _mgnrega_complete_list(answer, rows)
        if "women_employment_provided" not in (sql or "").lower():
            answer = _mgnrega_zero_backstop(answer, rows, entity_result.get("display") or {})
        if _mg_women:
            # The years a women figure covers are part of the figure (see
            # _mgnrega_women_query); state them even if the composer did not.
            _yrs = _mg_women["years"]
            if not all(y["fy"] in answer for y in (_yrs[0], _yrs[-1])):
                answer = answer.rstrip() + f" This covers {_women_span(_yrs)}" + (
                    " — the years that have women-employment data" if _mg_women["all_years"] else "") + "."
            if _mg_women["all_years"] and _mg_women["missing"] and not any(
                    y["fy"] in answer for y in _mg_women["missing"]):
                answer = answer.rstrip() + (
                    f" Women employment is not recorded at source for "
                    f"{', '.join('FY ' + y['fy'] for y in _mg_women['missing'])}.")
    if schemes == ["PMAY-G"]:
        # bare rupee cells ("795,860,000.00") -> ₹ with lakh / crore (KI-095)
        answer = _pmay_rupee_format(answer, rows)
        answer = _pmay_fy_labels(answer, rows)
    if schemes == ["Focus Plus"]:
        # shares, comparison difference, rupee formatting (KI-060/061/064)
        answer = await _focusplus_answer_guarantees(question, sql, rows, answer)
    if schemes == ["CM Elevate"]:
        # complete lists, programme split + combined, comparison differences,
        # readable two-label breakdowns, stated zeros (KI-068..074)
        answer = await _cm_elevate_answer_guarantees(question, sql, rows, answer,
                                                     entity_result.get("display") or {})
    if schemes == ["CM Elevate Legacy"]:
        # derived "N villages each have V records" counts, no-village records (KI-167)
        answer = await _cm_legacy_answer_guarantees(question, sql, rows, answer,
                                                    entity_result.get("display") or {})
    if schemes == ["Focus Legacy"]:
        # month numbers -> month names, bare rupees -> ₹ Indian grouping (KI-147);
        # records with no block / village / AC stated (KI-145)
        answer = _focus_legacy_answer_guarantees(answer, sql, rows)
        if _fl_unplaced and not _fl_breakdown:
            answer = _focus_legacy_unplaced_guarantee(answer, *_fl_unplaced)
    if _fl_total and not (_c1x_bounded_find(f"{_fl_total[0]:,}", answer.split("\n", 1)[0])
                          or _c1x_bounded_find(f"{_fl_total[0]}", answer.split("\n", 1)[0])):
        # Deterministic guarantee: the composer (or its row-by-row fallback)
        # did not lead with the true count, so the list would read as complete.
        answer = (f"{_fl_total[0]:,} {_fl_total[1]} match in total; the top {len(rows)} are "
                  f"shown below.\n\n{answer}")
    answer = await _latest_year_guarantee(answer, sql)
    # Year-gap guarantee: the question named a year the scheme does not hold and
    # _apply_year_gap answered for another. The note says so, but the composer
    # dropped it (TC-24: "Compare FY 2023-24 and FY 2024-25" answered with
    # 2022-23 and 2024-25 and no word about 2023-24). Lead with the note.
    _gap_note = next((n for n in (entity_result.get("notes") or []) if "holds no data" in n), None)
    if entity_result.get("question") and _gap_note:
        _absent = _c13_fy_label(_gap_note)
        if _absent and _absent not in answer:
            answer = f"{_gap_note}\n\n{answer}"
    # I-10 / J-7: how many places have none, before the lowest ones that have some
    if entity_result.get("zero_note") and entity_result["zero_note"] not in answer:
        answer = f"{entity_result['zero_note']}\n\n{answer}"
    # E-9: places tied with the last one shown
    if entity_result.get("tie_note") and entity_result["tie_note"] not in answer:
        answer = f"{answer}\n\n{entity_result['tie_note']}"
    d["answer"] = answer


def _data_assemble(d: dict) -> dict:
    """The DATA result dict (graph: assemble)."""
    schemes, entity_result, sql, rows, answer = (d["schemes"], d["entity_result"], d["sql"],
                                                 d["rows"], d["answer"])
    return {
        "route": "data",
        "intent": "DATA",
        "confidence": "high" if rows else "low",
        "schemes": schemes,
        "resolved_entities": entity_result["resolved"],
        "sql": sql,
        "sql_query": sql,
        "row_count": len(rows),
        # E-3: the rows there are beyond the row cap (None when not capped)
        "total_row_count": entity_result.get("true_row_count"),
        "rows": rows[:20],
        # The full result the query returned, for the table/chart renderer.
        # Was capped at 200, which silently truncated a legitimate answer — a
        # "which villages…" question over a constituency returns ~150 rows and
        # the user has no way to reach the rest (reported 2026-09-17).
        # run_readonly() already bounds every query at SQL_MAX_RESULT_ROWS
        # (1000), so this is not an unbounded payload; `row_count` above stays
        # the true total either way.
        "data": rows,
        "answer": answer,
    }


# ── "What is EKH?" — spell out a district / block name or abbreviation ──────
# A bare "what is <term>", "<term> full form", "what does <term> stand for"
# where <term> is one of Meghalaya's 12 districts or its ~56 C&RD blocks. The
# KB has no glossary for these, and the edge whitelist bounces a lone "ekh" as
# off-topic — so both routes fail the user. Answer it straight from the
# entity-resolver catalogue instead. A question that also wants a figure
# ("person-days in EKH") carries a data cue and is left for the DATA path.
def _c13_sp_or_dash0(gap: str) -> bool:
    r"""The gap between two words: one whitespace character or one hyphen."""
    return len(gap) == 1 and (gap.isspace() or gap == "-")


# "what" with its optional "'s" / "s" / " is" / " are" / " was" / " does" / " do"
_C13_WHAT = Alt(Seq(W("what"), _C1xGapIs(W("s"), lambda g: g == "'")),
                Seq(W("what"), _C1xGapIs(W("is", "are", "was", "does", "do"), lambda g: g == " ")),
                W("what"), W("whats"))
_C13_FULL_FORM = Alt(Seq(W("full"), _C1xGapIs(W("form"), _c13_sp_or_dash0)), W("fullform"))
_DEFN_CUE_MATCH = Matcher(Alt(
    _C13_WHAT, _C13_FULL_FORM, _c1x_lit("full name"), _c1x_lit("long form"), _c1x_lit("short form"),
    W("expand", "expanded", "expansion", "meaning", "acronym", "define", "definition"),
    W("abbreviat", prefix=True), Seq(W("stand", "stands"), _C1xGapIs(W("for"), lambda g: g == " ")),
))
_C13_OF = _C1xGapIs(W("of"), lambda g: g == " ")
_C13_FOR = _C1xGapIs(W("for"), lambda g: g == " ")
# In the old alternation order: the first form that matches at a position wins.
_DEFN_STRIP_MATCH = Matcher(Alt(
    _C13_WHAT,
    _c1x_lit("the full form of"), Seq(_C13_FULL_FORM, _C13_OF), _c1x_lit("full name of"),
    _c1x_lit("full form for"), _c1x_lit("long form of"), _c1x_lit("short form of"),
    _C13_FULL_FORM, _c1x_lit("full name"), _c1x_lit("long form"), _c1x_lit("short form"),
    _c1x_lit("the meaning of"), _c1x_lit("meaning of"),
    Seq(W("abbreviat", prefix=True), _C13_OF), Seq(W("abbreviat", prefix=True), _C13_FOR),
    _c1x_lit("acronym for"), _c1x_lit("acronym of"), _c1x_lit("expansion of"), W("expanded", "expand"),
    _c1x_lit("definition of"), W("define"), _c1x_lit("tell me"), W("please", "does", "do"),
    Seq(W("stand", "stands"), _C13_FOR),
    W("mean", "means"), _c1x_lit("in full"), _c1x_lit("name of"), _c1x_lit("the name of"),
    W("district", "districts", "distt", "dist", "block", "blocks"),
    Seq(W("c"), _C1xGapIs(W("rd"), lambda g: g == "&")), W("cd"),
    _c1x_lit("in meghalaya"), _c1x_lit("of meghalaya"), W("meghalaya"),
))


def _c13_defn_keep(ch: str) -> bool:
    return _c1x_is_word_char(ch) or ch in "&./ -"


def _c13_squash_disallowed(text: str) -> str:
    r"""Keep letters, digits, _ & . / space -: each run of other characters -> one space."""
    out, prev_bad = [], False
    for ch in text:
        if _c13_defn_keep(ch):
            out.append(ch)
            prev_bad = False
        elif not prev_bad:
            out.append(" ")
            prev_bad = True
    return "".join(out)


def _format_geo_definition(hit: dict) -> str:
    name = hit["display"]
    acronym = str(hit.get("acronym") or "").strip()
    if hit["type"] == "district":
        lead = (f"“{acronym}” is short for {name}"
                if acronym and hit.get("used_abbrev") else name)
        hq = hit.get("hq")
        seat = f" (headquarters: {hq})" if hq else ""
        return (
            f"{lead} — one of the 12 districts of Meghalaya{seat}. "
            f"Ask for its MGNREGA or PMAY-G figures, e.g. "
            f"“PMAY-G houses completed in {name}” or "
            f"“MGNREGA person-days in {name} in 2023-24”."
        )
    parent = hit.get("district")
    where = f" in {parent} district" if parent else ""
    return (
        f"{name} is a C&RD (community & rural development) block{where} of "
        f"Meghalaya. Ask for its MGNREGA or PMAY-G figures, e.g. "
        f"“MGNREGA person-days in {name}” or "
        f"“PMAY-G houses sanctioned in {name}”."
    )


def _geo_definition_answer(question: str) -> "dict | None":
    """A direct answer for a 'spell out this district / block' question, or None
    to let normal routing handle it."""
    q = (question or "").strip()
    if not q or len(q.split()) > 10:
        return None
    if not _DEFN_CUE_MATCH.search(q):
        return None
    if _DATA_HINTS.search(q) or _AGGREGATE_CUE.search(q):
        return None
    core = _DEFN_STRIP_MATCH.sub(" ", q)
    core = _c13_squash_disallowed(core)
    core = " ".join(core.split()).strip(" -.")
    if not core or len(core.split()) > 5:
        return None
    hit = lookup_geo_term(core)
    if not hit:
        return None
    logger.info("geo-definition shortcut: %r -> %s %r", question, hit["type"], hit["display"])
    return {
        "route": "knowledge", "intent": "RAG", "confidence": "high",
        "answer": _format_geo_definition(hit), "sources": [],
        **_empty_data_fields(),
    }


async def answer_question(question: str, session: "Session | None" = None,
                          scope: "auth.UserScope | None" = None) -> dict:
    """Public entry point: one turn through the LangGraph orchestrator
    (app/pipeline_graph.py), the only driver. Returns the result dict (with the
    'Next steps' suggestions and the context update applied by the graph's
    finalize / context_update nodes), or raises ClarificationNeeded for a pause
    and the model / DB errors the router maps to 503 / 504 / 5xx."""
    from app import pipeline_graph
    return await pipeline_graph.answer_question_via_graph(question, session=session, scope=scope)


async def _update_context(session: "Session | None", raw_question: str, result: dict) -> None:
    # Context Updater — fold this turn into the session's structured state and
    # refresh the rolling summary (both best-effort; see context_manager).
    # Skipped for a clarification pause: nothing was actually answered yet,
    # and the graph never reaches context_update for one (it pauses first).
    if settings.CONTEXT_LAYER_ENABLED and session is not None:
        try:
            context_manager.update_state(
                session, raw_question, result.get("rewritten_question") or raw_question, result)
            await context_manager.maybe_update_summary(session)
        except Exception:  # noqa: BLE001 — the context layer must never break an answer
            logger.warning("context layer post-processing failed (non-fatal)", exc_info=True)
    # E1 stage 1 (D-078): the query plan, logged beside this turn's decisions. Built in
    # the background AFTER the answer, unless stage 2a (D-085) already started it
    # during the turn, beside the guardrail call: then that plan is reused (or
    # cancelled when the turn ended as neither data nor knowledge). Nothing reads it yet.
    from app import query_plan as _c13_qp
    _c13_pending = _c13_qp.take_for_turn(session)
    if settings.QUERY_PLAN_SHADOW and (result.get("route") in ("data", "knowledge") or _c13_pending):
        try:
            asyncio.get_running_loop().create_task(_c13_qp.shadow(
                result.get("rewritten_question") or raw_question, raw_question, result,
                **({"pending": _c13_pending} if _c13_pending else {})))
        except Exception:  # noqa: BLE001
            logger.debug("query plan shadow not scheduled", exc_info=True)


# ── Chart hint (D-042) ──────────────────────────────────────────────────────
# `chart_type` on a DATA result tells the chat UI (frontend/src/chat/analytics.js)
# which chart to draw. The UI always had grouped / stacked / KPI charts, but no
# backend code ever sent the hint, so they never appeared and "show it as a pie
# chart" changed nothing. Explicit words win; otherwise the rows' shape decides.

def _c13_pair(firsts, seconds):
    r"""first + optional whitespace + second ("line chart", "linechart")."""
    return Alt(Seq(W(*firsts), _C1xGapIs(W(*seconds), _c1x_ws0)),
               W(*[f + s2 for f in firsts for s2 in seconds]))


_CHART_ASKED = [   # first match wins
    ("pie", Matcher(W("pie"))),
    ("doughnut", Matcher(Alt(_c13_pair(("donut", "doughnut", "ring"), ("chart", "graph")),
                             W("donut", "doughnut", "ring")))),
    ("stacked", Matcher(W("stack", "stacked"))),
    ("grouped_bar", Matcher(Alt(W("grouped", "clustered"),
                                Seq(W("side"), _C1xGapIs(W("by"), _c13_sp_or_dash0),
                                    _C1xGapIs(W("side"), _c13_sp_or_dash0))))),
    ("line", Matcher(Alt(_c13_pair(("line",), ("chart", "graph", "plot")),
                         _c13_pair(("trend",), ("line", "chart", "graph")),
                         Seq("over", "the", "years", sep="space")))),
    ("bar", Matcher(Alt(_c13_pair(("bar", "column"), ("chart", "graph", "plot", "charts", "graphs", "plots")),
                        W("histogram")))),
]


def _c13_name_part_spans(parts: "frozenset[str]"):
    """A column name with one '_'-separated part in `parts` (case-insensitive) —
    the part sits at the start or after '_', and at the end or before '_'."""
    def fn(name: str) -> list:
        pos = 0
        for part in name.lower().split("_"):
            if part in parts:
                return [(pos, pos + len(part))]
            pos += len(part) + 1
        return []
    return fn


# Columns that hold numbers but are labels, not measures (years, codes, ids).
_CHART_LABEL_COL = _C1xScan(_c13_name_part_spans(frozenset(
    "year yr fy code id lgd pin pincode key rank sl serial".split())))
# Measures that must not be stacked: parts of a rate or an average do not add up.
_CHART_NON_ADDITIVE = _C1xUnion("pct", "percent", "percentage", "rate", "ratio", "avg", "average", "mean",
                                "median", "per_", "share")


def _c13_grouped_number(s: str) -> bool:
    r"""The whole text is a number: optional '-', digits, any ",ddd" groups, optional decimals."""
    body = s[1:] if s.startswith("-") else s
    whole, dot, frac = body.partition(".")
    if dot and not frac.isdecimal():
        return False
    parts = whole.split(",")
    return parts[0].isdecimal() and all(len(x) == 3 and x.isdecimal() for x in parts[1:])


def _chart_is_number(v) -> bool:
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, (int, float, Decimal)):
        return True
    return isinstance(v, str) and _c13_grouped_number(v.strip())


def _chart_hint(question: str, raw_question: str, rows: list) -> "str | None":
    """The chart the UI should draw for these rows, or None (the UI decides)."""
    # The standalone question first: "I asked for a pie chart, why are you giving a line
    # chart?" is rewritten to "... as a pie chart" (c15 _chart_view_question), and the
    # raw words name both types (live 2026-10-19 16:02). The raw words still count
    # when the rewrite dropped the chart phrase.
    for asked in (question, raw_question):
        for hint, pattern in _CHART_ASKED:
            if asked and pattern.search(asked):
                return hint
    if not rows or not isinstance(rows[0], dict):
        return None
    cols = list(rows[0])
    num_cols = [c for c in cols if not measure_kinds.is_label_col(c)
                and any(r.get(c) is not None for r in rows)
                and all(r.get(c) is None or _chart_is_number(r.get(c)) for r in rows)]
    label_cols = [c for c in cols if c not in num_cols]
    if len(rows) == 1:
        # One row of several figures ("wages vs material"): a bar per figure.
        return "kpi_bar" if len(num_cols) >= 2 else None
    # J-11 (audit 2026-10-29): year_key and financial_year are one period, not two labels
    years = [c for c in label_cols if measure_kinds.dim_of(c) == "period"]
    if len(years) >= 2:
        label_cols = [c for c in label_cols if c not in years[1:]]
    # A stack adds its series. Only when the measure adds along the series' dimension
    # (G-4: villages / households of two years counted twice; C-6 / D-7 / D-13: job
    # cards, participation %, maxima), never across schemes (A-4 / B-3: households +
    # houses), and never for a ranking, which is a ranked list (J-6: "top 5 villages"
    # drawn stacked by block). The UI applies the same rule (columns.js canAdd).
    if len(label_cols) >= 2 and len(num_cols) == 1 and not _CHART_NON_ADDITIVE.search(str(num_cols[0]))             and measure_kinds.can_add(num_cols[0], measure_kinds.dim_of(label_cols[1]))             and measure_kinds.dim_of(label_cols[0]) != "scheme"             and not _C12S_RANK_WORDS.search(raw_question or question or ""):
        # district x year -> one bar per district, stacked by year, when the
        # second label has few values (otherwise the legend is unreadable).
        if len({str(r.get(label_cols[1])) for r in rows}) <= 8:
            return "stacked"
    return None


# ── one shape for rows merged from several schemes (audit 2026-10-29, A-1 / I-9) ──
# Each scheme's model-written query names its columns its own way: MGNREGA's year is
# year_key 2023, PMAY-G's financial_year_short "2023-24"; one says village_name, the
# other lgd_village_name; one counts beneficiaries, the other houses_sanctioned. The
# UI charts only the columns every row has, so the year disappeared ("MGNREGA,
# MGNREGA, MGNREGA, PMAY-G …" donut) and two half-empty columns were all that was
# left. The rows the UI gets carry one financial_year ("2023-24"), one place column
# per level, and — when each scheme has its own single measure — one `value` column
# with what it counts in `measure`. The composer has already read the original rows.
_C13U_ID_PARTS = frozenset({"code", "id", "lgd", "key", "rank", "sl", "serial", "pin", "pincode"})
_C13U_PLACES = (("district", "district"), ("block", "block"), ("village", "village"),
                ("constituency", "constituency"))


def _c13u_parts(col) -> list:
    return [x for x in str(col).lower().replace(" ", "_").split("_") if x]


def _c13u_is_year_col(col) -> bool:
    low = str(col).lower()
    return "financial" in low or any(x in ("year", "fy", "yr") for x in _c13u_parts(col))


def _c13u_fy(v) -> "str | None":
    """'2023-24' from 2023, '2023', '2023-2024', 'FY 2023-24'; None otherwise."""
    s = str(v if v is not None else "").strip()
    if s.lower().startswith("fy"):
        s = s[2:].strip()
    head, rest = s[:4], s[4:]
    if len(head) == 4 and head.isdigit() and head[:2] in ("19", "20") and (
            rest == "" or (rest[:1] == "-" and rest[1:].isdigit() and len(rest[1:]) in (2, 4))):
        return f"{int(head)}-{(int(head) + 1) % 100:02d}"
    return None


def _c13u_measure_cols(row: dict) -> list:
    return [k for k, v in row.items() if k != "scheme" and not _c13u_is_year_col(k) and _chart_is_number(v)
            and not any(x in _C13U_ID_PARTS for x in _c13u_parts(k))]


def _c13_unify_scheme_rows(rows: list) -> list:
    """Rows from two or more schemes in one shape (see above); other rows as they are."""
    if not rows or not all(isinstance(r, dict) and r.get("scheme") for r in rows) \
            or len({r["scheme"] for r in rows}) < 2:
        return rows
    per_scheme = {}
    for r in rows:
        per_scheme.setdefault(r["scheme"], set()).update(_c13u_measure_cols(r))
    one_each = all(len(c) == 1 for c in per_scheme.values())
    differ = len({next(iter(c)) for c in per_scheme.values() if c}) > 1
    out = []
    for r in rows:
        years = [k for k in r if _c13u_is_year_col(k)]
        fy = next((_c13u_fy(r[k]) for k in sorted(years, key=lambda k: str(k).endswith("_key"))
                   if _c13u_fy(r[k])), None)
        n: dict = {}
        for k, v in r.items():
            if k in years:
                if "financial_year" not in n:
                    n["financial_year"] = fy if fy is not None else v
                continue
            parts = _c13u_parts(k)
            name = k
            if isinstance(v, str) and not any(x in _C13U_ID_PARTS for x in parts if x != "lgd"):
                name = next((canon for word, canon in _C13U_PLACES if any(word in x for x in parts)), k)
            if one_each and differ and k in per_scheme.get(r["scheme"], ()):
                n["measure"] = str(k).replace("_", " ")
                n["value"] = v
                continue
            if name not in n:
                n[name] = v
        out.append(n)
    return out


# X-14 (chat UI audit 2026-10-29): PMAY-G money came as "22,22,75,30,000" under
# "Amount released" — no ₹, no unit — beside MGNREGA in ₹ lakh. A money column with
# no unit in its name gets one from the database's catalog unit of its source column
# and any division in the SELECT, as a name suffix the UI reads ("amount_released"
# -> "amount_released_rs"). Names that already carry a unit are left alone.
_C13_UNIT_WORDS = frozenset(("rs", "rupees", "inr", "lakh", "lakhs", "cr", "crore", "crores", "pct",
                             "percent", "percentage", "per", "avg", "average", "share", "ratio", "rate"))


def _c13_money_units(result: dict) -> None:
    # The unit comes from semantic.column_catalog (the database's own UNIT for each
    # source column), never from the column's name: the name-based first version
    # showed "houses_sanctioned" as "₹388" in the live run. No recorded unit, a
    # ratio of two columns, or columns of mixed units: nothing is renamed.
    rows = result.get("data") or []
    if len(result.get("schemes") or []) != 1 or not rows or not isinstance(rows[0], dict):
        return
    from app import schema_introspect
    srcs = sql_ast.output_sources(result.get("sql") or "")
    rupees_per = {"rupees": 1.0, "lakh rupees": 1e5, "crore rupees": 1e7}
    rename = {}
    for col, v in rows[0].items():
        parts = set(str(col).lower().split("_"))
        src = srcs.get(col)
        if not src or src["ratio"] or not src["cols"] or parts & _C13_UNIT_WORDS:
            continue
        if not isinstance(v, (int, float, Decimal)) or isinstance(v, bool):
            continue
        units = {schema_introspect.column_unit(t, c) for c in src["cols"] for t in src["tables"]} - {None}
        if len(units) != 1 or next(iter(units)) not in rupees_per:
            continue
        rupees = rupees_per[next(iter(units))] * (src["div"] or 1.0)
        unit = ("crore" if abs(rupees - 1e7) < 1 else "lakh" if abs(rupees - 1e5) < 1
                else "rupees" if abs(rupees - 1) < 1e-9 else None)
        if unit:
            rename[col] = f"{col}_{'rs' if unit == 'rupees' else unit}"
    if rename:
        result["data"] = [{rename.get(k, k): v for k, v in r.items()} for r in rows]
        result["rows"] = result["data"][:20]


def _attach_chart_hint(result: dict, question: str, raw_question: str) -> None:
    """Set `chart_type` on a DATA result that has rows. Best-effort."""
    try:
        if result.get("route") == "data" and result.get("data"):
            unified = _c13_unify_scheme_rows(result["data"])
            if unified is not result["data"]:
                result["data"] = unified
                result["rows"] = unified[:20]
                result["row_count"] = len(unified)
            _c13_money_units(result)
            hint = _chart_hint(question, raw_question, result["data"])
            if hint:
                result["chart_type"] = hint
    except Exception:  # noqa: BLE001 — a chart hint must never break an answer
        logger.warning("chart hint failed (non-fatal)", exc_info=True)


def _attach_followups(result: dict, question: str) -> None:
    """Add `follow_up_options` (+ back-compat `follow_ups` / `follow_up`) to a
    data/knowledge result. Best-effort — a failure here never breaks the answer."""
    if not settings.FOLLOWUP_SUGGEST_ENABLED:
        return
    if result.get("route") not in ("data", "knowledge") or result.get("keep_follow_ups"):
        return
    try:
        opts = followups.build_followups(
            result["route"], question,
            result.get("schemes") or [], result.get("resolved_entities") or {},
            sql=result.get("sql"),
            rows=result.get("rows") or result.get("data"))
    except Exception:  # noqa: BLE001
        logger.warning("follow-up suggestion build failed", exc_info=True)
        return
    if opts:
        result["follow_up_options"] = opts
        result["follow_ups"] = [o["question"] for o in opts]
        result["follow_up"] = opts[0]["question"]

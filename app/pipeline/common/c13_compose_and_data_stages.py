# app/pipeline/common/c13_compose_and_data_stages.py — compose, intent, data stages, answer_question, charts, follow-ups.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
#
# SQL text is read here only through SQLGlot (app/sql_ast.py: tree / token
# stream), never with a regular expression; the regexes below read questions
# and answers (English), not SQL.
from app import sql_ast
from sqlglot import exp


# schemes whose one-figure answers must state THAT figure (see compose_response)
_ONE_FIGURE_SCHEMES = (["Focus Plus"], ["CM Elevate"])


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
    digest_text, digest_nums = _result_digest(rows)
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
    prompt = f"""Answer the user's question in one to three plain sentences, using ONLY the
numbers in the result and the whole-result summary below — do not invent or round
differently than shown. Write like a direct briefing: lead with the fact or figure
itself, not with "The data shows..." or a description of what the query returned.
Keep each sentence to one idea — short and declarative, not a chain of clauses
joined by "so" / "as" / "which means".
{guidance}
{metrics_block}{names_block}{summary_block}{notes_block}{style_examples}
Question: "{question}"
Result ({len(rows)} row(s), showing up to {len(preview)}):
{json.dumps(preview, default=str)}

Answer:"""
    context_budget.log_prompt_context("compose", [
        ("guidance", guidance), ("available_metrics", metrics_block),
        ("entity_names", names_block), ("result_summary", summary_block),
        ("premise_notes", notes_block), ("style_examples", style_examples),
        ("question", question), ("result_rows", json.dumps(preview, default=str)),
    ], prompt=prompt, rows=len(rows), rows_shown=len(preview))
    answer = await llm.call_response_composer(prompt)

    data_nums = _data_numbers(preview) | digest_nums | set(extra_numbers or ())
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

    if misquoted or dropped_metric:
        why = "MISQUOTED a number" if misquoted else "left out one of the result values"
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
        still_bad =(bool(data_nums) and not _answer_numbers_faithful(answer, data_nums)) or (
            len(preview) == 1 and len(_row_metrics(preview[0])) >= 2
            and not _answer_covers_metrics(answer, preview[0])) or (
            # the Focus Plus one-figure rule above, re-applied to the retry
            schemes in _ONE_FIGURE_SCHEMES and len(preview) == 1 and len(_row_metrics(preview[0])) == 1
            and _row_metrics(preview[0])[0][1] not in (0, None)
            and not _answer_covers_metrics(answer, preview[0]))
        if still_bad:
            logger.warning("compose_response: retry still wrong — using deterministic answer")
            answer = _deterministic_answer(rows if len(rows) > 1 else preview)

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
            answer = _deterministic_answer(preview)
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
            answer = _deterministic_answer(rows)
    # A list answer must state the list's true size: "Ten villages in the
    # Dadenggre constituency received employment" for 135 villages, and the
    # fallback's "Here are the 40 results" for 114 (it was handed only the
    # 40-row preview) — MGNREGA sheet DATA-014, run 2026-10-09. A spelled-out
    # count escapes the digit faithfulness check above.
    if len(rows) > 1 and _states_wrong_list_count(answer, len(rows)):
        logger.warning("compose_response: answer states a list size other than %d — deterministic answer",
                       len(rows))
        answer = _deterministic_answer(rows)
    return answer


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
    digit words joined by commas only (regex \d[\d,]*)."""

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
    r"""regex [,]*\s+ — the commas a digit number may trail, then whitespace."""
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
    r"""regex \b(?:top|…|those)\s*$ — the text ENDS with one of these words
    (then only whitespace)."""
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
    made of word characters and . ' ( ) - (regex
    [A-Za-z][\w.'()-]*(?:\s+[A-Za-z][\w.'()-]*){0,4}). Every split is offered."""

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


async def classify_intent(question: str) -> str:
    """DATA (a number from megh_db) vs KNOWLEDGE (how the scheme works, from the
    reference docs). Keyword fast-path first; one classifier call otherwise."""
    # "what are common districts in both schemes?" opens with "what are", which
    # otherwise reads as KNOWLEDGE — but it is a list computed from the coverage
    # data, never something in the reference docs. Force DATA before the keyword
    # fast-path so the "what are" knowledge cue can't win.
    if _CROSS_SCHEME_SET_QUESTION.search(question):
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
    if _PROGRAMME_DESIGN_CUE.search(question):
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
    prompt = f"""Classify the question into exactly one label:
  DATA      - needs a number/count/list computed from the scheme database. This
              INCLUDES comparison and correlation questions ("do districts with
              high X also have high Y", "is A related to B by district", "which
              districts lead on both schemes") — answered by querying the figures
              and comparing them, NOT from the reference docs.
  KNOWLEDGE - asks how a scheme works: eligibility, documents, components, rules, history

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
    r"""regex \s*[?.!]*\s*$"""
    return rest.lstrip().lstrip("?.!").strip() == ""


def _c13_vns_tail(text: str, q: int) -> "int | None":
    r"""regex (?=\s+(?:in|under|within|for|across|of)\b|\s*[?.!]*\s*$): q itself, or None."""
    if _c13_ws_words(text, q, {"in", "under", "within", "for", "across", "of"}) >= 0 or _c13_punct_end(text[q:]):
        return q
    return None


def _c13_in_the_name_tail(text: str, q: int) -> "int | None":
    r"""regex \s+in\s+(?:the|their|its)\s+names?\b: the end, or None."""
    e = _c13_ws_words(text, q, {"in"}, {"the", "their", "its"}, {"name", "names"})
    return e if e >= 0 else None


class _C13NameSearch(_C1xLike):
    """A lead word pattern, then whitespace, then a lazily-grown name (group
    "name"), then a tail — the old _VNS_NAME / _VNS_TAIL regexes."""

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
    r"""regex sub(\s+(?:village|villages)$, "", name, IGNORECASE)"""
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
    for mode, rx in _VILLAGE_NAME_SEARCH:
        m = rx.search(question or "")
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
        cond = ("UPPER(REGEXP_REPLACE(TRIM(lgd_village_name), '\\s+', ' ', 'g')) = $1" if mode == "exact"
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
    _named = [s for s, pat in _SCHEME_NAME_MATCHER.items() if pat.search(_cross_text)]
    # A bare "CM-ELEVATE" beside other schemes is CM Elevate Legacy unless the
    # question uses the applications dataset's own words — the user's default
    # (2026-10-12). _pin_cm_elevate_dataset only fires on its data words, and
    # "performance of MGNREGA, PMAY-G, Focus+ and CM-ELEVATE" has none of them.
    if "CM Elevate" in _named and "CM Elevate Legacy" not in _named \
            and not _CMELEVATE_APPLICATIONS_ONLY.search(_cross_text) \
            and not _CME_APPLICATIONS_VOCAB.search(_cross_text):
        _named = [("CM Elevate Legacy" if s == "CM Elevate" else s) for s in _named]
    _cross_q = await _mask_scheme_words_in_village_name(_cross_text)
    _cross = cross_scheme.detect(
        _cross_q, _named,
        measure_text=(await _mask_village_names(_cross_q)) if cross_scheme.other_measure(_cross_q) else None)
    if _cross:
        logger.info("cross-scheme comparison %r -> %s", _cross_text, _cross)
        d["schemes"], d["cross"] = _cross, {"schemes": _cross, "text": _cross_text}
        return None

    # Ask which scheme before doing anything expensive, when the question could
    # honestly mean either one. Guessing here is worse than a one-tap follow-up.
    # "Which scheme paid out the most?" — the scheme is the ANSWER, not a
    # missing filter, so this must run before the "which scheme?" pause below
    # (which would otherwise ask the user to supply the very thing they asked
    # for). Answered deterministically across every scheme that records money.
    if _wants_cross_scheme_money_ranking(question):
        return await _cross_scheme_money_answer(question)

    # "Focus" with nothing to say WHICH Focus — a two-way ask that keeps what the
    # user already told us, rather than the generic five-way pause below.
    if _is_ambiguous_focus(question):
        raise _focus_ambiguity_clarification(question)

    # A village NAME that contains another scheme's vocabulary is not a scheme
    # signal: "total expenditure in UMRAN DAIRY" was classified CM Elevate (its
    # dairy sub-scheme) and answered ₹1.27 crore of CM Elevate money for an
    # MGNREGA village (all-villages QA 2026-09-26). Scheme detection reads the
    # question with that exact village name masked; everything else reads it
    # unchanged. Only when the masked name itself carries scheme vocabulary.
    _scheme_q = await _mask_scheme_words_in_village_name(question)

    if _needs_scheme_clarification(_scheme_q):
        _each = cross_scheme.unnamed_schemes(_cross_text) if settings.ANSWER_DEFAULTS_ENABLED else None
        if _each:
            # No scheme named, a measure several schemes record: answer for each
            # of them instead of asking (ANSWER_DEFAULTS_ENABLED, 2026-10-14).
            logger.info("answer default: no scheme named -> %s", _each)
            d["schemes"], d["cross"] = _each, {"schemes": _each, "text": _cross_text}
            return None
        raise _scheme_clarification(question)

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
        _pg_answer = await _focus_legacy_pg_name_answer(question)
        if _pg_answer is not None:
            return _pg_answer
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
        return await _cross_scheme_answer(d, scope)
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
            entity_result["display"]["district"] = region["canonical"]

    # "Give me an overall Focus+ data summary" — a genuinely whole-scheme
    # question with no district/year/tranche to pin. Handled before the scope/
    # year/tranche clarification gates below so it never gets mistaken for an
    # aggregate question that merely forgot to name a scope.
    if _focusplus_wants_overall_summary(question, schemes):
        return await _focusplus_overall_summary_answer(schemes, entity_result)

    # Ask which district / block / village / year when an aggregate question
    # pins none of them — unless we're already resuming that very clarification
    # (a reply that still names no scope must not loop us back here).
    # Answer, don't ask (ANSWER_DEFAULTS_ENABLED, user decision 2026-10-14): the
    # question goes on exactly as if the user had tapped the "All of Meghalaya" /
    # "All financial years combined" / "All tranches combined" chip — the same
    # appended text, so the SQL is told the scope and never silently picks the
    # latest year — and the answer states it.
    _defaults = settings.ANSWER_DEFAULTS_ENABLED
    if not skip_scope_clarify and _needs_scope_clarification(question, entity_result["resolved"]):
        if not _defaults:
            raise _scope_clarification(question, schemes)
        question = f"{question.strip().rstrip(' ?.')} for all of Meghalaya"
        logger.info("answer default: no area named -> %r", question)

    # Geography is settled but the year isn't: ask which financial year (one-tap
    # chips) rather than silently answering across every year. The chips resume
    # with a concrete year or "all financial years", so this can't loop.
    # Every data question that names no year, not only the ones the year gate
    # would stop: "MGNREGA people who got work in Dadenggre constituency" was
    # answered for one unstated year (10,414 of 51,543) while "persons employed"
    # elsewhere covered all years (hierarchy matrix run 2026-10-14). Stocks (job
    # cards) are pinned to the latest year by _mgnrega_job_cards_latest_year.
    _res = entity_result["resolved"]
    if _defaults and not _res.get("year_key") and not _res.get("year_key_list") \
            and _parse_year_key(question) is None and not _ALL_YEARS_CUE.search(question) \
            and not _TIME_SERIES_CUE.search(question) and not _WHICH_YEAR_CUE.search(question) \
            and not _C13_JOB_CARD.search(question) \
            and any(_SCHEME_DATA_YEARS.get(s) for s in (schemes or [])):
        question = f"{question.strip().rstrip(' ?.')} across all financial years"
        logger.info("answer default: no year named -> %r", question)
    if not _defaults and _needs_year_clarification(question, schemes, entity_result["resolved"]):
        # MGNREGA women questions offer only the years that carry women data.
        if schemes == ["MGNREGA"] and _WOMEN_CUE.search(question or ""):
            try:
                raise await _mgnrega_women_year_clarification(question)
            except ClarificationNeeded:
                raise
            except Exception:  # noqa: BLE001 — year map unavailable: the generic pause
                pass
        raise _year_clarification(question, schemes)

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


def _c13_geo_end(rest: str) -> bool:
    r"""regex \s*[?.]?\s*$"""
    r = rest.lstrip()
    if r and r[0] in "?.":
        r = r[1:]
    return r.strip() == ""


def _c13_after_words(text: str, q: int, *words_) -> int:
    """_c13_ws_words for fixed words; -1 when absent."""
    return _c13_ws_words(text, q, *[{w} for w in words_])


def _c13_geo_tail_plain(text: str, q: int) -> bool:
    r"""(?:\s+village)?\s*[?.]?\s*$"""
    v = _c13_after_words(text, q, "village")
    return (v >= 0 and _c13_geo_end(text[v:])) or _c13_geo_end(text[q:])


def _c13_geo_tail_b(text: str, q: int) -> bool:
    r"""(?:\s+village)?(?:\s+(?:in|located\s+in|under|part\s+of))?\s*[?.]?\s*$"""
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
    r"""(?:\s+village)?\s+(?:in|located|lie|fall|come)\w*\b.*$"""
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
    """The old four-way geo-lookup regex: (lead words) + whitespace + a name of
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
    r"""regex sub(^(?:the\s+)?(?:village\s+)?, "", name, IGNORECASE): drop each lead
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
    lines = [f"**{name.title()}** — {len(rows)} village{'s' if len(rows) > 1 else ''} in the Meghalaya geography "
             "registry:\n", "| Village | LGD village code | Block | District | Assembly constituency |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['lgd_village_name']} | {r['village_code']} | {str(r['lgd_block'] or '—').title()} | "
                     f"{str(r['lgd_district'] or '—').title()} | {r['ac_name'] or '—'} |")
    if len(rows) > 1:
        lines.append("\nThey are different villages that share a name, told apart by their LGD code.")
    sql = "SELECT village_code, lgd_village_name, lgd_block, lgd_district, ac_name FROM curated.dim_geography"
    return {"route": "data", "intent": "DATA", "confidence": "high", "schemes": [],
            "resolved_entities": {}, "sql": sql, "sql_query": sql, "row_count": len(rows),
            "rows": [dict(r) for r in rows], "data": [dict(r) for r in rows], "answer": "\n".join(lines)}


def _literal_sql(sql: str, params: list) -> str:
    """A display / authorization copy of parameter-bound SQL with the values inlined."""
    def lit(v) -> str:
        if isinstance(v, (list, tuple)):
            return "ARRAY[" + ", ".join(lit(x) for x in v) + "]"
        if isinstance(v, (int, float)):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"
    # $1, $2 … are PARAMETER + NUMBER tokens; a '$1' inside a string literal is
    # part of a STRING token and is left alone.
    tokens = _sql_tokens(sql)
    out, last = [], 0
    for tok, nxt in zip(tokens, tokens[1:]):
        if tok.token_type == TokenType.PARAMETER and nxt.token_type == TokenType.NUMBER \
                and nxt.start == tok.end + 1 and nxt.text.isdigit():
            out.append(sql[last:tok.start])
            out.append(lit(params[int(nxt.text) - 1]))
            last = nxt.end + 1
    out.append(sql[last:])
    return "".join(out)


def _c13_chip_label_spans(label: str) -> list:
    """regex ^(?P<name>.+?) — (?P<block>.+?) block, (?P<district>.+)$ (no newlines)."""
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


async def _cross_scheme_answer(d: dict, scope: "auth.UserScope | None" = None) -> dict:
    """The deterministic cross-scheme comparison (app/cross_scheme.py), with the
    same authorization a generated query gets."""
    schemes, entity_result = d["cross"]["schemes"], d["entity_result"]
    resolved = entity_result["resolved"]
    await _cross_twin_village_pause(d, schemes, resolved)
    out = await cross_scheme.answer(d["cross"]["text"], schemes, entity_result, _SCHEME_DATA_YEARS)
    sql = "\n;\n".join(_literal_sql(q, prm) for q, prm in out.pop("sql_pairs", []))
    out["sql"] = out["sql_query"] = sql
    # Authorized on the literal SQL (its place values and GROUP BY visible), the
    # same check a generated query gets; nothing is returned on a deny.
    if scope is not None and settings.AUTH_ENABLED:
        decision = auth.authorize(scope, schemes=schemes, resolved_entities=resolved, sql=sql)
        if not decision.allow:
            logger.info("auth deny (%s) user=%s: %s", decision.check, scope.user_id, decision.reason)
            return _denied(decision, schemes, resolved)
    out["resolved_entities"] = resolved
    return out


async def _data_deterministic_stage(d: dict, scope: "auth.UserScope | None" = None) -> "dict | None":
    """The fixed-shape MGNREGA and PMAY-G queries built in code (graph: deterministic)."""
    question, schemes, entity_result = d["question"], d["schemes"], d["entity_result"]
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
        await _pmay_attach_placeholders(_pm_det, _pm_rows)
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
    ) or _mgnrega_combined_facts_query(question, schemes, entity_result["resolved"]) \
        or _mgnrega_breakdown_query(question, schemes, entity_result["resolved"]) \
        or _mgnrega_wage_material_query(question, schemes, entity_result["resolved"]) \
        or _cme_sector_query(question, schemes, entity_result["resolved"])         or _fp_status_cohort_query(question, schemes, entity_result["resolved"])         or _focus_legacy_duplicates_query(question, schemes, entity_result["resolved"])         or _focus_legacy_fy_compare_query(question, schemes, entity_result["resolved"])
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
_CME_SECTOR_MARKS = frozenset({"cme-sector-count", "cme-sector-pending", "cme-sector-programmes"})


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
    if not _mg_det and _per_scheme_needed(question, schemes, entity_result):
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


async def _per_scheme_generate(d: dict) -> None:
    """generate_sql once per scheme, in parallel. d["per_scheme"] = [[scheme, sql or
    None, error or None], ...]; d["sql"] = the statements joined (what the
    authorize node checks)."""
    question, schemes, entity_result = d["question"], d["schemes"], d["entity_result"]
    outs = await asyncio.gather(*(generate_sql(_per_scheme_question(question, s), [s], entity_result)
                                  for s in schemes), return_exceptions=True)
    plan: list = []
    for s, out in zip(schemes, outs):
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
        q = _per_scheme_question(question, s)
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


def _per_scheme_notes(d: dict) -> list[str]:
    missing = [(s, err) for s, sql, err in (d.get("per_scheme") or []) if not sql]
    if not d.get("per_scheme"):
        return []
    notes = ["The result covers several schemes; each row's `scheme` column says which scheme it "
             "comes from. Report each scheme's figures under its own name, and never add figures "
             "of different schemes together (they count different things)."]
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
    rows = [dict(r) for r in await fetch_rows(_mg_det[0], _mg_det[1])]
    logger.info("MGNREGA deterministic query: %s | params=%s", _mg_det[2].replace("\n", " "),
                _mg_det[1])
    d["rows"] = rows


async def _data_post_rows_stage(d: dict, scope: "auth.UserScope | None" = None) -> "dict | None":
    """Deterministic post-row answers, composer notes and the premise check (graph: post_rows)."""
    question, schemes, entity_result = d["question"], d["schemes"], d["entity_result"]
    sql, rows, _mg_admin, _mg_women = d["sql"], d["rows"], d["mg_admin"], d["mg_women"]
    if _mg_admin:
        answer = await _mgnrega_admin_expenditure_answer(rows, entity_result.get("display") or {})
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
    answer = _fl_breakdown or await compose_response(question, sql, rows, notes=notes,
                                    entities=entity_result.get("display"),
                                    schemes=schemes, style_examples=_style,
                                    extra_numbers=({str(_fl_total[0])} if _fl_total else set()) | {
                                        str(int(n)) for v in (_fl_unplaced[1] if _fl_unplaced else {}).values()
                                        for n in [_as_number(v)] if n is not None} or None)
    d["answer"] = answer


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
def _c13_y20(w: str) -> bool:
    r"""A word that starts with 20 + two digits (regex 20\d\d, open end)."""
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
    r"""regex escape(lead) + \s+ + word (case-sensitive, no boundaries)."""
    k = text.find(lead)
    while k >= 0:
        rest = text[k + len(lead):]
        if rest[:1].isspace() and rest.lstrip().startswith(word):
            return True
        k = text.find(lead, k + 1)
    return False


def _c13_fy_label(note: str) -> "str | None":
    r"""regex \bFY\s*(\d{4}-\d{2}) (case-sensitive): the "2023-24" after FY."""
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
    r"""regex [\s-]? between two words: one whitespace character or one hyphen."""
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
    r"""regex sub(r"[^\w&./ -]+", " ", text): each run of other characters -> one space."""
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


# ── Chart hint (D-042) ──────────────────────────────────────────────────────
# `chart_type` on a DATA result tells the chat UI (frontend/src/chat/analytics.js)
# which chart to draw. The UI always had grouped / stacked / KPI charts, but no
# backend code ever sent the hint, so they never appeared and "show it as a pie
# chart" changed nothing. Explicit words win; otherwise the rows' shape decides.

def _c13_pair(firsts, seconds):
    r"""first + optional whitespace + second ("line chart", "linechart") — regex a\s*b."""
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
    regex (?:^|_)(?:part|…)(?:_|$)."""
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
    r"""regex fullmatch -?\d+(?:,\d{3})*(?:\.\d+)?"""
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
    asked = " ".join(q for q in (raw_question, question) if q)
    for hint, pattern in _CHART_ASKED:
        if pattern.search(asked):
            return hint
    if not rows or not isinstance(rows[0], dict):
        return None
    cols = list(rows[0])
    num_cols = [c for c in cols if not _CHART_LABEL_COL.search(str(c))
                and any(r.get(c) is not None for r in rows)
                and all(r.get(c) is None or _chart_is_number(r.get(c)) for r in rows)]
    label_cols = [c for c in cols if c not in num_cols]
    if len(rows) == 1:
        # One row of several figures ("wages vs material"): a bar per figure.
        return "kpi_bar" if len(num_cols) >= 2 else None
    if len(label_cols) >= 2 and len(num_cols) == 1 and not _CHART_NON_ADDITIVE.search(str(num_cols[0])):
        # district x year -> one bar per district, stacked by year, when the
        # second label has few values (otherwise the legend is unreadable).
        if len({str(r.get(label_cols[1])) for r in rows}) <= 8:
            return "stacked"
    return None


def _attach_chart_hint(result: dict, question: str, raw_question: str) -> None:
    """Set `chart_type` on a DATA result that has rows. Best-effort."""
    try:
        if result.get("route") == "data" and result.get("data"):
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
    if result.get("route") not in ("data", "knowledge"):
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

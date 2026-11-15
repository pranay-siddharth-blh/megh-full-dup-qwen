# app/pipeline/common/c18_answer_frame.py — the answer frame (D-110): what a data answer was, and follow-ups read
# as an EDIT of it. Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, after every other file, so it shares every name with them; its functions run at turn time.
#
# Why (user, 2026-11-15): follow-ups such as "break that down by district", "by block", "only Ri Bhoi", "which is the
# lowest", "top 3", "what about 2023-24", "and the households instead" must always resolve. Each rule in c01 re-read
# the previous question's WORDS and edited them; nothing recorded what the answer WAS (measure, grouping, order,
# limit), two grouping readers disagreed, a rule's output was a shape the next rule could not read, and the rules ran
# only right after a data answer. The frame is filled from the evidence after every data answer (_c18_fill_frame),
# a follow-up is read as one edit of it (_c18_read_edit), and ONE renderer writes the standalone question
# (_c18_render), so every output is a shape the next turn reads back. The merge plan and the inherited filters are
# exactly the edited frame's (_c18_merge_plan, _c18_prior_from_frame). When the previous answer came from the
# metric catalogue, the catalogue may take the edited frame directly (_c18_catalogue_from_frame).
# Nothing is guessed: whatever the evidence or the message does not state, the frame leaves None, and the resolver
# returns None so the older rules and the model rewrite run exactly as before.
from types import SimpleNamespace as _C18NS

from app import answer_frame as _c18_af

# ── Filling the frame ────────────────────────────────────────────────────────

_C18_PLACE_LEVELS = ("district", "block", "village")          # coarsest first
_C18_YEAR_COLS = frozenset({"year_key", "financial_year", "financial_year_short", "fy", "year", "fin_year"})
_C18_SCHEME_COLS = frozenset({"scheme", "scheme_name", "sub_scheme", "cm_scheme"})
_C18_LIST_LIMIT = 100           # an outer LIMIT at or above this is the row cap, not a "top N"


def _c18_dim_of_column(col: str) -> "str | None":
    """The grouping a GROUP BY / output column stands for, read from its name (None: not a grouping we know)."""
    c = (col or "").lower()
    if not c:
        return None
    if c in _C18_YEAR_COLS or c.startswith("financial_year"):
        return "year"
    if "month" in c:
        return "month"
    if "constituency" in c or c in ("ac", "ac_name"):
        return "constituency"
    if "village" in c:
        return "village"
    if "block" in c:
        return "block"
    if "district" in c:
        return "district"
    if c in _C18_SCHEME_COLS:
        return "scheme"
    subs = {str(f.sub_scheme_column).lower() for f in scheme_registry.DATASETS.values()
            if getattr(f, "sub_scheme_column", None)}
    return "scheme" if c in subs else None


def _c18_sql_reading(sql: str) -> dict:
    """What the final SQL says about the answer's shape: {qtype, group, order, limit, metric_key, catalogue, shape}.
    Only what the query states; unparseable text, a query reading no table, a set operation, a grouping by a column
    that is no known dimension: the fields stay None."""
    out = {"qtype": None, "group": None, "order": None, "limit": None, "metric_key": None, "catalogue": False,
           "shape": None}
    text = (sql or "").strip()
    if not text:
        return out
    if metric_catalog.is_catalog_sql(text):
        head = text[len("/* metric:"):].split("*/", 1)[0].split()
        out["catalogue"] = True
        if head:
            out["metric_key"] = None if "+" in head[0] else head[0]
            if len(head) > 1 and head[1] in _c18_af.QTYPES:
                out["qtype"] = head[1]
    trees = sql_ast.parse(text)
    if len(trees) != 1:
        return out
    tree = trees[0]
    read = sql_ast.tables(tree)
    if not read:
        return out
    sel = sql_ast.outer_select(tree)
    if sel is None or isinstance(tree, exp.SetOperation):
        return out
    gnode = sel.args.get("group")
    gcols = [c.name for c in gnode.find_all(exp.Column)] if gnode is not None else []
    if not gcols and sql_ast.has_group_by(tree):
        # grouped inside a CTE / subquery and read out as is: the outer columns name the grouping
        gcols = [n for n in sql_ast.output_names(tree) if _c18_dim_of_column(n)]
    dims = [_c18_dim_of_column(c) for c in gcols]
    has_agg = bool(sql_ast.aggregates(tree))
    limit = sql_ast.outer_limit(tree)
    if limit is not None and (limit < 1 or limit >= _C18_LIST_LIMIT):
        limit = None
    order = None
    onode = sel.args.get("order")
    if onode is not None and onode.expressions:
        first = onode.expressions[0]
        key = first.this if isinstance(first, exp.Ordered) else first
        by_label = isinstance(key, exp.Column) and _c18_dim_of_column(key.name) is not None
        if not by_label:
            order = "desc" if (isinstance(first, exp.Ordered) and first.args.get("desc")) else "asc"
    group, qtype = None, None
    if any(d is None for d in dims):
        qtype = "other"                                   # grouped by something that is no dimension we know
    elif dims:
        places = [d for d in ("village", "block", "district", "constituency") if d in dims]   # finest first
        others = sorted(set(dims) - set(places))
        if len(others) > 1 or (others and places):
            qtype = "other"                               # two groupings at once ("by district by year")
        else:
            group = places[0] if places else others[0]
    if qtype is None:
        if not has_agg:
            qtype = "list"
        elif group is not None and order and limit:
            qtype = "ranking"
        elif group is not None:
            qtype = "breakdown"
        else:
            qtype = "total"
    if out["qtype"] is None or not out["catalogue"]:
        out["qtype"] = qtype
    out.update(group=group, order=order, limit=limit)
    aggs = sorted({a.key for a in sql_ast.aggregates(tree)})
    out["shape"] = (f"{'+'.join(sorted(read))}|g={','.join(sorted(c.lower() for c in gcols))}"
                    f"|a={','.join(aggs)}|o={order or '-'}|l={limit or '-'}")
    return out


# The words a question opens with when it RANKS ("Which district had the most ...", "Top 5 blocks by ...").
_C18_RANK_VERBS = frozenset("has had have is was were got gets get recorded records received receives saw sees spent "
                            "reported reports registered shows showed did does".split())
_C18_SUPERLATIVES = frozenset("most least highest lowest maximum minimum max min largest smallest biggest best worst "
                              "greatest fewest top bottom".split())
_C18_LEVEL_WORDS = {"district": "district", "districts": "district", "block": "block", "blocks": "block",
                    "village": "village", "villages": "village"}
_C18_CUT_PREPS = frozenset("in for at of within across and vs versus with between during over from".split())
_C18_LEVEL_TAILS = frozenset("block blocks district districts village villages constituency constituencies ac".split())
_C18_COMPARE_WORDS = frozenset("compare compared comparing comparison vs versus against between".split())
_C18_ALL_YEARS_PHRASES = tuple(sorted(
    {f"{p} all {t}{fy}years" for p in ("across", "over", "for", "in", "during") for t in ("", "the ")
     for fy in ("", "financial ", "fiscal ", "available ", "available financial ")}
    | {"all years combined", "all financial years combined", "across all years combined"}, key=len, reverse=True))


def _c18_cut(text: str, spans: "list[tuple[int, int]]", left: frozenset = _C18_CUT_PREPS,
             right: frozenset = frozenset()) -> str:
    """`text` without each span, each taking ONE adjacent word before it from `left` (its preposition or joiner) and
    the words after it from `right` (a level word: "Umsning BLOCK")."""
    toks = _c01_tm_tokens(text)
    cuts = []
    for a, b in spans:
        i0 = next((k for k, t in enumerate(toks) if t.end > a), len(toks))
        i1 = max([k for k, t in enumerate(toks) if t.start < b] or [i0 - 1])
        if i0 > 0 and toks[i0 - 1].low in left and not any(c[0] <= toks[i0 - 1].start < c[1] for c in cuts):
            a = toks[i0 - 1].start
        k = i1 + 1
        while k < len(toks) and toks[k].low in right:
            b = toks[k].end
            k += 1
        cuts.append((a, b))
    out, pos = [], 0
    for a, b in sorted(cuts):
        if a < pos:
            a = pos
        out.append(text[pos:a])
        pos = max(pos, b)
    out.append(text[pos:])
    return collapse_ws(" ".join(out).replace(" ,", ",")).strip(" ,;:-")


def _c18_strip_rank_head(q: str) -> "tuple[str, bool]":
    """`q` without a ranking's opening words, and whether it had one. Both the rank rule's own shapes ("Which
    district has the lowest: ...", "Top 3 districts: ...") and the natural ones ("Which district had the most ...",
    "Top 5 blocks by ...")."""
    ranked = _c01_ranked_stem(q)
    if ranked is not None:
        return ranked[1], True
    toks = _c01_tm_tokens(q)
    ws = [t.low for t in toks]
    i = 0
    if len(ws) >= 3 and ws[0] in ("which", "what") and ws[1] in _C18_LEVEL_WORDS:
        i = 2
        if i < len(ws) and ws[i] in _C18_RANK_VERBS:
            i += 1
        if i < len(ws) and ws[i] == "the":
            i += 1
        if i >= len(ws) or ws[i] not in _C18_SUPERLATIVES:
            return q, False
        i += 1
    elif len(ws) >= 3 and ws[0] in ("top", "bottom"):
        i = 1
        if i < len(ws) and ws[i].isdecimal():
            i += 1
        if i >= len(ws) or ws[i] not in _C18_LEVEL_WORDS:
            return q, False
        i += 1
        if i < len(ws) and ws[i] in ("by", "for", "in", "with", "on", "of"):
            i += 1
    else:
        return q, False
    if i + 1 < len(ws) and ws[i] in ("number", "amount", "count", "total") and ws[i + 1] == "of":
        i += 2
    if i >= len(toks):
        return q, False
    return q[toks[i].start:], True


def _c18_measure_text(question: str, schemes: "list[str]", filters: dict) -> "str | None":
    """The question's own measure words (its scheme kept): the question with its ranking head, chart request,
    grouping, statewide words, all-years phrase, financial years, compare lead and the places of its filters cut
    out. None when what is left still holds a place, a year, a grouping, a ranking or a comparison (the words are
    not understood well enough to be re-used), or is too short."""
    q = collapse_ws(question or "").strip().rstrip(" ?.")
    if not q or len(schemes or []) != 1:
        return None
    q, _ranked = _c18_strip_rank_head(q)
    q = _c01_without_chart_phrase(q)
    low = q.lower()
    for lead in _C01_CMP_LEADS:
        if low.startswith(lead):
            if not any((filters or {}).get(k) for k in ("district_list", "block_list", "village_code_list",
                                                       "assembly_constituency_list", "year_key_list")):
                return None                               # a comparison of something the filters do not list
            q = q[len(lead):]
            break
    if context_policy._RELATIVE_YEAR_MATCH.search(q):
        return None                                       # "last year", "the year before": not a measure word
    for phrase in _C18_ALL_YEARS_PHRASES:
        q = _c04_replace_ci(q, phrase, " ")
    for phrase in _C01_STATEWIDE_PHRASES:
        q = _c04_replace_ci(q, phrase, " ")
    q = _c05_statewide_stem(q)
    hits = [(h.start(), h.end()) for h in context_policy.GROUPING_MATCH.finditer(q)]
    hits += [(h.start(), h.end()) for h in context_policy.GROUPING_PER_MATCH.finditer(q)]
    if hits:
        q = _c18_cut(q, hits, left=frozenset("in for across and by".split()))
    spans = [(a, b) for a, b, _y, _e in fy_spans(q)]
    for t in _c01_tm_tokens(q):
        if len(t.raw) == 4 and t.raw.startswith("20") and t.raw.isdecimal() and not any(a <= t.start < b
                                                                                       for a, b in spans):
            spans.append((t.start, t.end))
    if spans:
        q = _c18_cut(q, spans, left=frozenset("in for during of over from fy".split()))
    from app import entity_resolver as _er
    try:
        _found, typed, _left = _er._place_scan(q)
    except Exception:  # noqa: BLE001 — no index: the catalogue scan below still runs
        typed = {}
    names = dict(typed)
    for canon in named_places(q):
        names.setdefault(canon, canon)
    pspans = []
    for canon, form in names.items():
        for f in (form, canon, canon.title()):
            p0 = _ci_find(q, f)
            if p0 >= 0:
                e = p0 + len(f)
                if (p0 == 0 or not q[p0 - 1].isalnum()) and (e == len(q) or not q[e].isalnum()):
                    pspans.append((p0, e))
                    break
    if pspans:
        q = _c18_cut(q, pspans, right=_C18_LEVEL_TAILS)
    q = collapse_ws(q).strip(" ,;:-")
    while True:                                           # a joiner or preposition left dangling at the end
        ws = _c01_tm_tokens(q)
        if ws and ws[-1].low in _C18_CUT_PREPS | {"the", "by", "under"}:
            q = q[:ws[-1].start].rstrip(" ,;:-")
            continue
        break
    ws = _c15_words(q)
    if len(ws) < 2 or named_places(q) or context_policy.extract_year_keys(q) or context_policy.grouping_dims(q):
        return None
    if _RANKING_CUE.search(q) or set(ws) & _C18_COMPARE_WORDS:
        return None
    named = _exact_schemes(question)
    if named and not named <= _exact_schemes(q):
        return None
    return q[:1].upper() + q[1:]


def _c18_all_years(question: str, filters: dict) -> bool:
    if filters.get("year_key") is not None or filters.get("year_key_list"):
        return False
    q = question or ""
    return any(_ci_find(q, p) >= 0 for p in _C18_ALL_YEARS_PHRASES) or bool(_STATED_ALL_YEARS_CUE.search(q))


def _c18_chart_asked(question: str) -> "str | None":
    """The chart phrase the question asked for ("as a bar chart"), as written in it, else None."""
    q = question or ""
    for phrase in _C01_OLD_CHART_PHRASES:
        p0 = _ci_find(q, phrase)
        if p0 >= 0:
            return q[p0:p0 + len(phrase)]
    return None


def _c18_origin(result: dict, *, mg_det: bool = False, per_scheme: bool = False, cross: bool = False,
                state_sql: "str | None" = None) -> "str | None":
    """Where the answer's SQL came from: catalogue / cross / fixed / model, or None when that is not known."""
    sql = result.get("sql") or result.get("sql_query") or ""
    if metric_catalog.is_catalog_sql(sql):
        return "catalogue"
    if per_scheme or cross or len(result.get("schemes") or []) > 1:
        return "cross"
    if mg_det:
        return "fixed"
    if state_sql and sql and state_sql == sql:
        return "model"
    if sql and not state_sql:
        return "fixed"                                    # a deterministic stage answered before any SQL generation
    return None


def _c18_fill_frame(question: str, result: dict, origin: "str | None" = None) -> dict:
    """The answer frame of a finished turn (a plain dict, empty for anything but a data answer). Deterministic: the
    catalogue's own query when it answered, else the final SQL, else None fields."""
    try:
        if not isinstance(result, dict) or result.get("route") != "data" or result.get("needs_clarification"):
            return {}
        schemes = [s for s in (result.get("schemes") or []) if isinstance(s, str)]
        resolved = result.get("resolved_entities") or {}
        filters = {k: resolved[k] for k in _c18_af.FILTER_KEYS if resolved.get(k) not in (None, "", [], ())}
        reading = _c18_sql_reading(result.get("sql") or result.get("sql_query") or "")
        q = collapse_ws(result.get("rewritten_question") or question or "").strip()
        qtype, group = reading["qtype"], reading["group"]
        if qtype in ("breakdown", "total") and group is not None:
            lst = filters.get(f"{group}_list") if group in ("district", "block") else (
                filters.get("year_key_list") if group == "year" else None)
            if lst and len(lst) > 1:
                qtype = "compare"
        frame = _c18_af.AnswerFrame(
            schemes=schemes,
            metric_key=reading["metric_key"] if reading["catalogue"] else None,
            measure_text=_c18_measure_text(q, schemes, filters),
            qtype=qtype, group=group, filters=filters, all_years=_c18_all_years(q, filters),
            order=reading["order"], limit=reading["limit"] if qtype == "ranking" else None,
            chart=result.get("chart_type") or _c18_chart_asked(q),
            source="catalogue" if reading["catalogue"] else (origin or ("cross" if len(schemes) > 1 else None)),
            sql_shape=reading["shape"], question=q)
        d = frame.to_dict()
        d["chart_asked"] = _c18_chart_asked(q)
        return d
    except Exception:  # noqa: BLE001 — the frame must never break an answer
        logger.debug("answer frame not filled", exc_info=True)
        return {}


def _attach_answer_frame(result: dict, question: str, *, mg_det: bool = False, per_scheme: bool = False,
                         cross: bool = False, state_sql: "str | None" = None) -> None:
    """finalize: the answer frame onto a data result (result["answer_frame"]); build_turn stores it on the turn."""
    if not isinstance(result, dict) or result.get("route") != "data":
        return
    origin = _c18_origin(result, mg_det=mg_det, per_scheme=per_scheme, cross=cross, state_sql=state_sql)
    frame = _c18_fill_frame(question, result, origin=origin)
    if frame:
        result["answer_frame"] = frame


# ── Rendering one standalone question from a frame ──────────────────────────

def _c18_title(name) -> str:
    from app.entity_resolver import _place_title
    return _place_title(str(name))


def _c18_join(names: "list[str]") -> str:
    names = [_c18_title(n) for n in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _c18_place_phrase(filters: dict) -> "str | None":
    """" in Umsning block, Ri Bhoi" / " in Ri Bhoi and East Khasi Hills" / "" (statewide); None for a village (its
    name is not in the frame: such a frame is not re-rendered)."""
    if filters.get("village_code") is not None or filters.get("village_code_list") or filters.get("village"):
        return None
    ac, acs = filters.get("assembly_constituency"), filters.get("assembly_constituency_list")
    if ac or acs:
        if filters.get("district") or filters.get("block"):
            return None
        names = list(acs) if acs else [ac]
        return f" in {_c18_join(names)} assembly constituenc{'ies' if len(names) > 1 else 'y'}"
    blocks, block = filters.get("block_list"), filters.get("block")
    districts, district = filters.get("district_list"), filters.get("district")
    if blocks:
        return f" in {_c18_join(list(blocks))} blocks"
    if block:
        out = f" in {_c18_title(block)} block"
        return out + (f", {_c18_title(district)}" if district else "")
    if districts:
        return f" in {_c18_join(list(districts))}"
    if district:
        return f" in {_c18_title(district)}"
    return ""


_C18_GROUP_WORDS = {"year": "financial year", "constituency": "assembly constituency"}


def _c18_render(frame: "_c18_af.AnswerFrame", chart: "str | None" = None) -> "str | None":
    """ONE canonical standalone question for `frame`, in the shapes every rule reads back:
    "<measure>[ under <scheme>][ in <place>][ by <group>][ in FY <year>][ <chart>]", a ranking opened by "Which
    district has the lowest: " / "Top 3 districts: ". None when the frame cannot be written (no measure words, a
    village, a cross-scheme frame)."""
    if len(frame.schemes) != 1 or not frame.measure_text:
        return None
    stem = frame.measure_text.rstrip(" ?.")
    if not _exact_schemes(stem):
        stem += f" under {frame.schemes[0]}"
    place = _c18_place_phrase(frame.filters or {})
    if place is None:
        return None
    tail = place
    if frame.qtype in ("breakdown", "compare") and frame.group and not (
            frame.qtype == "compare" and frame.group in ("district", "block")):
        tail += f" by {_C18_GROUP_WORDS.get(frame.group, frame.group)}"
    years = frame.filters.get("year_key_list") or (
        [frame.filters["year_key"]] if frame.filters.get("year_key") is not None else [])
    if years:
        tail += " in " + " and ".join(context_manager._fy_text(int(y)) for y in years)
    elif frame.all_years and frame.group != "year":
        tail += " across all financial years"
    body = collapse_ws(stem + tail)
    if frame.qtype == "ranking":
        if frame.group not in ("district", "block", "village"):
            return None
        word = "highest" if frame.order != "asc" else "lowest"
        n = frame.limit or 1
        if n == 1:
            return f"Which {frame.group} has the {word}: {body}"
        return f"{'Top' if frame.order != 'asc' else 'Bottom'} {n} {frame.group}s: {body}"
    if chart:
        body += " " + chart.strip()
    return body


# ── The data answer a follow-up continues ────────────────────────────────────

def _c18_usable(frame: "_c18_af.AnswerFrame") -> bool:
    return bool(frame.schemes) and frame.qtype in ("total", "breakdown", "ranking", "compare")


def _c18_followup_base(prev, session) -> "tuple[_c18_af.AnswerFrame, object] | None":
    """(the answer frame, its turn) a follow-up edits: the previous turn's, or, after a knowledge aside on the same
    scheme(s), the last DATA turn's (D-110: the rules ran only right after a data answer). The in-process turns
    first, then the durable context frames (a freshly rehydrated worker holds only the last two turns in full)."""
    if prev is None:
        return None
    route = getattr(prev, "route", None)
    if route == "data":
        f = _c18_af.from_turn(prev)
        return (f, prev) if _c18_usable(f) else None
    if route != "knowledge":
        return None
    aside = set(getattr(prev, "schemes", None) or [])
    candidates = []
    turns = list(getattr(session, "turns", None) or []) if session is not None else []
    if turns and turns[-1] is prev:
        turns = turns[:-1]
    for t in reversed(turns):
        if getattr(t, "route", None) == "data":
            candidates.append((_c18_af.from_turn(t), t))
            break
        if getattr(t, "route", None) not in ("knowledge", "history"):
            return None                                   # something else came between
    if not candidates and session is not None:
        for fr in reversed(list(getattr(session, "frames", None) or [])[:-1]):
            if fr.get("route") == "data" and fr.get("af"):
                candidates.append((_c18_af.AnswerFrame.from_dict(fr["af"]), None))
                break
    if not candidates:
        return None
    frame, turn = candidates[0]
    if not _c18_usable(frame):
        return None
    if aside and not all(any(topic_memory.same_scheme_family(a, s) for s in frame.schemes) for a in aside):
        return None                                       # an aside about another scheme: not this figure's
    return frame, turn


# ── Reading a follow-up as an edit ───────────────────────────────────────────

_C18_REGROUP_EXTRA = frozenset("what about how more detail details detailed split wise breakdown view".split())
_C18_ONLY_LEADS = frozenset("only just".split())
_C18_PLACE_LEADS = frozenset("only just what how and for in same now show".split())
_C18_PLACE_FILLER = frozenset(
    "only just what about how and for in the same show me now then please district block constituency assembly of "
    "there is it that give with to at but ok okay so also us figure figures one data instead rather".split())


def _c18_copy(frame: "_c18_af.AnswerFrame") -> "_c18_af.AnswerFrame":
    return _c18_af.AnswerFrame.from_dict(frame.to_dict())


def _c18_drop(filters: dict, *levels: str) -> None:
    for lvl in levels:
        if lvl == "village":
            for k in ("village", "village_code", "village_code_list"):
                filters.pop(k, None)
        elif lvl == "constituency":
            filters.pop("assembly_constituency", None)
            filters.pop("assembly_constituency_list", None)
        else:
            filters.pop(lvl, None)
            filters.pop(f"{lvl}_list", None)


def _c18_at_or_below(level: str) -> "tuple[str, ...]":
    return _C18_PLACE_LEVELS[_C18_PLACE_LEVELS.index(level):]


def _c18_village_locked(frame) -> bool:
    f = frame.filters or {}
    return bool(f.get("village_code") is not None or f.get("village_code_list") or f.get("village"))


def _c18_one_year(text: str) -> "tuple[int | None, str]":
    """(the ONE financial year `text` names, the text without it) — (None, text) for none or several."""
    years = set(context_policy.extract_year_keys(text))
    spans = fy_spans(text)
    if len(years) != 1 or len(spans) > 1:
        return None, text
    rest = text
    for a, b, _y, _e in sorted(spans, reverse=True):
        rest = rest[:a] + " " + rest[b:]
    if not spans:
        rest = " ".join(t.raw for t in _c01_tm_tokens(text) if not (t.raw.isdecimal() and t.raw.startswith("20")))
    return next(iter(years)), rest


def _c18_one_place(text: str) -> "tuple[str, str, str] | None":
    """(NAME, level, the text without it) when `text` names exactly one district / block / constituency, else None
    (a village, two places, none). The catalogue scan: no database needed."""
    from app.entity_resolver import place_mentions
    try:
        found = place_mentions(text)
    except Exception:  # noqa: BLE001
        found = {}
    for canon, dim in named_places(text).items():
        found.setdefault(canon, dim)
    found = {k: v for k, v in found.items() if v in ("district", "block", "assembly_constituency", "village")}
    if len(found) != 1:
        return None
    name, dim = next(iter(found.items()))
    if dim == "village":
        return None
    p0, form = -1, name
    for f in (name, name.title()):
        p0 = _ci_find(text, f)
        if p0 >= 0:
            form = f
            break
    if p0 < 0:
        try:
            from app.entity_resolver import _place_scan
            typed = _place_scan(text)[1].get(name)
        except Exception:  # noqa: BLE001
            typed = None
        if typed:
            p0 = _ci_find(text, typed)
            form = typed
    if p0 < 0:
        return None
    rest = text[:p0] + " " + text[p0 + len(form):]
    return name, ("constituency" if dim == "assembly_constituency" else dim), rest


def _c18_set_place(frame, name: str, level: str) -> bool:
    """Put ONE place into the frame's filters (finer levels cleared; a block's district is its parent)."""
    f = frame.filters
    if level == "district":
        _c18_drop(f, "district", "block", "village", "constituency")
        f["district"] = name
    elif level == "block":
        parent = block_parent_district(name, frame.schemes[0] if frame.schemes else "")
        _c18_drop(f, "district", "block", "village", "constituency")
        f["block"] = name
        if parent:
            f["district"] = parent
    elif level == "constituency":
        _c18_drop(f, "district", "block", "village", "constituency")
        f["assembly_constituency"] = name
    else:
        return False
    return True


def _c18_regroup_dim(text: str) -> "str | None":
    """The one grouping a message asks for when it asks for nothing else ("now by block", "what about block wise
    breakdown", "district wise please"), else None."""
    ws = _c15_words(text or "")
    if not ws or len(ws) > 16:
        return None
    dims, trigger = set(), False
    for w in ws:
        base = w[:-4] if len(w) > 4 and w.endswith("wise") else ""
        if w in _C01_REGROUP_DIM:
            dims.add(_C01_REGROUP_DIM[w])
        elif base in _C01_REGROUP_DIM:
            dims.add(_C01_REGROUP_DIM[base])
            trigger = True
        elif w in _C01_REGROUP_TRIGGER or w in ("breakdown", "split", "wise"):
            trigger = True
        elif not (w in _C01_REGROUP_FILLER or w in _C18_REGROUP_EXTRA or w in _C01_REGROUP_CHART
                  or w in _C01_REGROUP_CHART_FILLER):
            return None
    return dims.pop() if len(dims) == 1 and trigger else None


def _c18_edit_rank(raw: str, frame):
    asked = _c01_rank_request(raw)
    if asked is None or len(frame.schemes) != 1:
        return None
    direction, dim, n = asked
    order = "desc" if direction == "up" else "asc"
    new = _c18_copy(frame)
    if frame.qtype == "ranking" and dim is None and n is None:
        new.order = order                                 # "and the least?" after a ranking: the other end
        return "rank", new
    level = dim or (frame.group if frame.group in ("district", "block", "village") else None)
    if level is None:
        return None
    if frame.filters.get(f"{level}_list") or _c18_village_locked(frame):
        return None                                       # a ranking among compared places / inside a village
    _c18_drop(new.filters, *_c18_at_or_below(level), "constituency")
    new.qtype, new.group, new.order = "ranking", level, order
    new.limit = n if n is not None else (frame.limit if frame.qtype == "ranking" and dim is None else None)
    return "rank", new


def _c18_edit_regroup(raw: str, frame):
    text = raw or ""
    year, text = _c18_one_year(text)
    place = _c18_one_place(text)
    if place is not None:
        name, plevel, text = place
    dim = _c18_regroup_dim(text)
    if dim is None or len(frame.schemes) != 1:
        return None
    group = {"financial year": "year"}.get(dim, dim)
    new = _c18_copy(frame)
    if place is not None and not _c18_set_place(new, name, plevel):
        return None
    if _c18_village_locked(new):
        return None                                       # the village's name is not in the frame: not re-rendered
    f = new.filters
    if group in _C18_PLACE_LEVELS:
        if place is not None and plevel in _C18_PLACE_LEVELS and \
                _C18_PLACE_LEVELS.index(plevel) >= _C18_PLACE_LEVELS.index(group):
            return None                                   # "by district for Umsning block": nothing to group
        # a grouping at or above a filter makes the grouping trivial: a roll-up (that level and below cleared)
        if any(f.get(k) or f.get(f"{k}_list") for k in _c18_at_or_below(group)):
            _c18_drop(f, *_c18_at_or_below(group))
        if f.get("assembly_constituency") or f.get("assembly_constituency_list"):
            return None                                   # a constituency crosses district and block lines
    elif group == "constituency":
        if any(f.get(k) or f.get(f"{k}_list") for k in ("district", "block")):
            return None
    elif group == "year":
        if year is not None:
            return None                                   # "by year for 2023-24": not a grouping by year
        if f.get("year_key_list"):
            return None
        f.pop("year_key", None)
        new.all_years = False
    elif group == "month":
        facts = scheme_registry.DATASETS.get(frame.schemes[0])
        if facts is None or not facts.has_dates:
            return None
    elif group == "scheme":
        facts = scheme_registry.DATASETS.get(frame.schemes[0])
        if facts is None or not facts.sub_scheme_column:
            return None
    else:
        return None
    if year is not None:
        f.pop("year_key_list", None)
        f["year_key"] = year
        new.all_years = False
    new.group = group
    if frame.qtype == "ranking" and group in ("district", "block"):
        new.qtype = "ranking"                             # "now by block" after "Top 3 districts": the top 3 blocks
    else:
        new.qtype, new.order, new.limit = "breakdown", None, None
    if new.qtype == "breakdown" and f.get(f"{group}_list"):
        new.qtype = "compare"
    return "regroup", new


def _c18_edit_place(raw: str, frame):
    if len(frame.schemes) != 1 or _c18_village_locked(frame):
        return None
    ws = _c15_words(raw or "")
    if not ws or len(ws) > 12 or not (set(ws) & _C18_PLACE_LEADS):
        return None                                       # a bare place name is a pause reply / the swap path's
    year, text = _c18_one_year(raw or "")
    place = _c18_one_place(text)
    if place is None:
        return None
    name, level, rest = place
    if any(w not in _C18_PLACE_FILLER for w in _c15_words(rest)):
        return None                                       # a measure, a grouping, a scheme of its own: not ours
    new = _c18_copy(frame)
    f = new.filters
    listed = [str(x).upper() for x in (f.get(f"{level}_list") or [])]
    if listed and name.upper() not in listed:
        return None                                       # "what about X" after comparing A and B: not one edit
    if (f.get("district_list") or f.get("block_list")) and not listed:
        return None
    if not _c18_set_place(new, name, level):
        return None
    if year is not None:
        f.pop("year_key_list", None)
        f["year_key"] = year
        new.all_years = False
    g = new.group
    if g in _C18_PLACE_LEVELS and level in _C18_PLACE_LEVELS and \
            _C18_PLACE_LEVELS.index(g) <= _C18_PLACE_LEVELS.index(level):
        new.group = None                                  # grouped by that level or above: one place is a total
        new.qtype, new.order, new.limit = "total", None, None
    elif g in ("district", "block") and level == "constituency":
        new.group = None
        new.qtype, new.order, new.limit = "total", None, None
    elif new.qtype == "compare":
        new.qtype = "breakdown" if g else "total"
    return ("one-place-of-comparison" if listed else "place"), new


def _c18_edit_measure(raw: str, frame):
    if len(frame.schemes) != 1 or not frame.measure_text:
        return None
    swapped = _c01_measure_swap_question(raw, _C18NS(question=frame.measure_text, route="data",
                                                     schemes=list(frame.schemes)))
    if not swapped:
        return None
    new = _c18_copy(frame)
    new.measure_text = swapped
    found = metric_catalog.match(swapped, frame.schemes[0]) if metric_catalog.mode() != "off" else None
    new.metric_key = found.metric.key if (found is not None and found.status == "one" and frame.metric_key) else None
    return "measure", new


def _c18_edit_year(raw: str, frame):
    text = raw or ""
    years = set(context_policy.extract_year_keys(text))
    rest = text
    for a, b, _y, _e in sorted(fy_spans(text), reverse=True):
        rest = rest[:a] + " " + rest[b:]
    ws = [w for w in _c15_words(rest) if not (w.isdecimal() and w.startswith("20"))]
    f = frame.filters
    target = None
    if len(years) == 1 and ws and all(w in _C01_YEAR_ONLY_WORDS or w.isdecimal() for w in ws):
        target = next(iter(years))
    elif len(years) == 1 and not ws:
        return None                                       # a bare year: a pause reply or the existing paths'
    elif not years and f.get("year_key") is not None:
        pairs = set(zip(ws, ws[1:]))
        step = -1 if pairs & set(_C01_YEAR_BEFORE) else 1 if pairs & set(_C01_YEAR_AFTER) else 0
        if step and all(w in _C01_YEAR_ONLY_WORDS or w in ("before", "previous", "prior", "last", "earlier", "after",
                                                             "next", "following", "later") for w in ws):
            target = int(f["year_key"]) + step
    if target is None or f.get("year_key_list") or len(frame.schemes) != 1:
        return None
    new = _c18_copy(frame)
    new.filters["year_key"] = target
    new.all_years = False
    if new.group == "year":                               # one year of a per-year list: that year's figure
        new.group, new.qtype, new.order, new.limit = None, "total", None, None
    return "year", new


def _c18_read_edit(raw: str, frame) -> "tuple[str, object] | None":
    """The ONE change a follow-up makes to the frame, as (kind, edited frame), else None."""
    q = raw or ""
    if _mentions_scheme(q) or _named_schemes(q) or _BARE_FOCUS_WORD.search(q):
        return None                                       # a scheme of its own: the swap / comparison / new paths
    for reader in (_c18_edit_rank, _c18_edit_regroup, _c18_edit_place, _c18_edit_measure, _c18_edit_year):
        try:
            out = reader(q, frame)
        except Exception:  # noqa: BLE001 — a reader that fails reads nothing
            logger.debug("answer frame: %s failed", reader.__name__, exc_info=True)
            out = None
        if out is not None:
            return out
    return None


# ── The merge plan and the inherited filters ─────────────────────────────────

_C18_PLAN_FIELDS = {"district": ("district", "district_list"), "block": ("block", "block_list"),
                    "village": ("village_code", "village_code_list", "village"),
                    "year": ("year_key", "year_key_list")}


def _c18_merge_plan(old, new) -> "context_policy.MergePlan":
    """KEEP / REPLACE / CLEAR per field, from the two frames: what the follow-up inherits is exactly the edited
    frame's filters (D-110; the rewrites before it carried no plan, so a stale filter could be inherited)."""
    plan = context_policy.MergePlan()
    changed = set()
    for name, keys in _C18_PLAN_FIELDS.items():
        a = [old.filters.get(k) for k in keys]
        b = [new.filters.get(k) for k in keys]
        if a == b:
            plan.actions[name] = context_policy.KEEP
            continue
        changed.add(name)
        has = any(v not in (None, "", [], ()) for v in b)
        plan.actions[name] = context_policy.REPLACE if has else context_policy.CLEAR
        plan.reasons[name] = "answer frame: " + ("replaced" if has else "cleared")
    if old.group != new.group or old.qtype != new.qtype:
        plan.actions["group_by"] = context_policy.REPLACE
        plan.reasons["group_by"] = "answer frame: grouping"
        changed.add("group_by")
    if (old.measure_text or "") != (new.measure_text or ""):
        plan.actions["metric"] = context_policy.REPLACE
        plan.reasons["metric"] = "answer frame: measure"
        changed.add("metric")
    for name in ("scheme", "category"):
        plan.actions.setdefault(name, context_policy.KEEP)
    if changed == {"group_by"}:
        plan.kind = context_policy.GROUP_BY_CHANGE
    elif changed and changed <= {"district", "block", "village"}:
        plan.kind = context_policy.GEOGRAPHY_CHANGE
    elif changed == {"year"}:
        plan.kind = context_policy.TIME_CHANGE
    elif changed == {"metric"}:
        plan.kind = context_policy.METRIC_CHANGE
    else:
        plan.kind = context_policy.FILTER_CHANGE
    return plan


_C18_GEO_YEAR_KEYS = frozenset({"district", "district_list", "district_list_region", "block", "block_list",
                                "block_list_districts", "village", "village_code", "village_code_list",
                                "village_twins", "assembly_constituency", "assembly_constituency_list", "year_key",
                                "year_key_list", "year_all"})


def _c18_prior_from_frame(prior: "dict | None", frame_prior: dict) -> dict:
    """The fallback the data stage inherits after a frame-resolved follow-up: every place / year key replaced by
    exactly the edited frame's filters; anything the frame does not model (tranche, CM sub-scheme) as before."""
    out = {k: v for k, v in (prior or {}).items() if k not in _C18_GEO_YEAR_KEYS}
    for k, v in (frame_prior or {}).items():
        if k == "village" or v in (None, "", [], ()):
            continue
        out[k] = v
    if (frame_prior or {}).get("year_all"):
        out["year_all"] = True
    return out


# ── The follow-up resolver ───────────────────────────────────────────────────

def _c18_frame_followup(raw_question: str, prev, session=None) -> "tuple[str, str, dict, object] | None":
    """(kind, the standalone question, the edited frame as a dict, the merge plan) for a follow-up that is ONE edit
    of the last data answer's frame, else None (the older rules and the model rewrite run as before)."""
    try:
        base = _c18_followup_base(prev, session)
        if base is None:
            return None
        frame, _turn = base
        edit = _c18_read_edit(raw_question, frame)
        if edit is None:
            return None
        kind, new = edit
        chart = None
        if kind == "regroup":
            chart = _c01_regroup_chart(raw_question).strip() or None
        elif kind in ("measure", "year", "place", "one-place-of-comparison"):
            chart = _c18_frame_chart_asked(_turn, frame)      # the chart the previous question asked stays
        question = _c18_render(new, chart=chart)
        if not question:
            return None
        new.question = question
        plan = _c18_merge_plan(frame, new)
        out = new.to_dict()
        out["chart_asked"] = chart
        return kind, question, out, plan
    except Exception:  # noqa: BLE001 — the resolver must never break a turn
        logger.warning("answer frame: follow-up resolver failed — older rules", exc_info=True)
        return None


def _c18_frame_chart_asked(turn, frame) -> "str | None":
    raw = getattr(turn, "answer_frame", None) if turn is not None else None
    if isinstance(raw, dict) and raw.get("chart_asked"):
        return raw["chart_asked"]
    return _c18_chart_asked(frame.question)


def _c18_record_followup(session, resolved: "tuple[str, str, dict, object]") -> None:
    """Hand a frame-resolved follow-up to the later stages of this request: the merge plan, the filters it inherits
    (exactly the frame's), and the frame itself (the catalogue may take it, c16)."""
    if session is None:
        return
    kind, _question, frame, plan = resolved
    ctx = session.turn_context
    ctx["plan"] = plan.to_dict()
    prior = dict(frame.get("filters") or {})
    if frame.get("all_years"):
        prior["year_all"] = True
    ctx["frame_prior"] = prior
    ctx["frame_edit"] = frame
    ctx["frame_rule"] = kind
    ctx["frame_plan_obj"] = plan


# ── The catalogue takes the edited frame (D-110 step 4) ──────────────────────

def _c18_catalogue_from_frame(frame: "dict | None", question: str, schemes: "list[str]",
                              entity_result: dict) -> "tuple[str, list, str] | None":
    """The catalogue query for a frame-resolved follow-up whose previous answer the catalogue gave: the edited
    frame's metric, query type, grouping, order and limit, the resolver's filters. Only for a measure verified for
    that query type (data/metric_catalog_verified.yaml) and filters that agree with the frame; else None (the words
    are matched as before)."""
    if not frame or metric_catalog.mode() != "on":
        return None
    f = _c18_af.AnswerFrame.from_dict(frame)
    if f.source != "catalogue" and not f.metric_key:
        return None
    if not f.metric_key or len(schemes or []) != 1 or list(f.schemes) != list(schemes):
        return None
    m = metric_catalog.metrics().get(f.metric_key)
    if m is None or m.scheme != schemes[0] or f.qtype not in ("total", "breakdown", "ranking", "compare"):
        return None
    filters = _c16_filters((entity_result or {}).get("resolved") or {})
    if filters is None:
        return None
    for key in ("district", "block", "village_code", "assembly_constituency"):
        want = f.filters.get(key) if f.filters.get(key) is not None else f.filters.get(f"{key}_list")
        have = filters.get(key)
        norm = (lambda v: sorted(str(x).upper() for x in v) if isinstance(v, (list, tuple, set))
                else ([str(v).upper()] if v not in (None, "") else []))
        if norm(want) != norm(have):
            return None                                   # the resolver read another place: the words decide
    years = filters.get("year_key") or []
    want_years = f.filters.get("year_key_list") or ([f.filters["year_key"]] if f.filters.get("year_key") is not None
                                                     else [])
    if sorted(int(y) for y in years) != sorted(int(y) for y in want_years):
        return None
    group = f.group if f.qtype != "total" else None
    if group not in (None, "district", "block", "year", "scheme"):
        return None
    if group is not None and group != "year" and filters.get(group) is not None \
            and not isinstance(filters.get(group), list):
        return None
    if f.qtype == "ranking" and group not in ("district", "block"):
        return None
    if group != "year":
        if metric_catalog.single_year(m.key) and len(years) != 1:
            return None
        if not years and metric_catalog.YEAR_COLUMN in m.columns and not f.all_years:
            return None
    if f.qtype == "total" and len(years) > 1:
        return None
    order = f.order if f.qtype == "ranking" else None
    limit = (f.limit or _C17_RUNNERS_UP) if f.qtype == "ranking" else None
    if metric_catalog.verified(f.qtype, m.key) is None:
        return None
    query = metric_catalog.build(m, filters, group, order=order, limit=limit, qtype=f.qtype)
    if query is not None:
        logger.info("metric catalogue (answers, from the answer frame): metric=%s type=%s group=%s", m.key, f.qtype,
                    group)
    return query

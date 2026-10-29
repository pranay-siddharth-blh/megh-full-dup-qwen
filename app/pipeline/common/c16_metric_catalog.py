# ── The data team's metric catalogue as a fixed query (D-071, RAG plan A) ────
# "Total expenditure in Ri Bhoi in 2023-24", "how much was spent in Ri Bhoi
# during FY 23-24" and "Ri Bhoi outlay 2023-24" are one question. Left to the
# model each wording wrote its own SQL, and now and then a different figure.
# When a question names exactly ONE catalogue measure and asks nothing else,
# the query is built from semantic.metric_definitions (app/metric_catalog.py):
# the same measure, place and year always read the same figure.
#
# It is the LAST entry of the fixed-query chain in _data_prepare_stage (c13),
# so every existing fixed query keeps priority, and it answers only for a
# measure listed for that query type in data/metric_catalog_verified.yaml —
# the measures whose figures were checked against the current answers. In
# METRIC_CATALOG_MODE=shadow (or for a measure not yet verified) it only logs
# what it would have done; the model path answers as before.
from app import metric_catalog
from app.db import fetch_rows_readonly as _c16_fetch_rows_readonly

# Resolved filters the catalogue query can apply. Any other filter the resolver
# pinned (a status, gender, programme, constituency, region …) is something the
# measure's expression does not cover: the model path answers.
_C16_FILTER_KEYS = frozenset({"district", "block", "village_code", "year_key",
                              "district_list", "block_list", "village_code_list", "year_key_list"})

# Question grammar: words that ask for a figure without changing which one.
# Anything else ("wage", "average", "women", "pending") may change the measure,
# so a question carrying such a word is left to the model path.
_C16_GRAMMAR = frozenset("""
    what whats what's is are was were the a an of in for during under at to me us give show tell
    please total overall number amount count how many much did does do has have had been be
    there it its so far till until date as on now provide get find figure value data
    meghalaya state statewide whole entire all district block village c rd
    fy financial fiscal year years scheme schemes s
""".split())
# Words a breakdown / ranking / comparison adds to the question.
_C16_SHAPE_WORDS = {
    "breakdown": frozenset("by wise each across breakdown break down split up per list every districts blocks"
                           .split()),
    "ranking": frozenset("""by which top bottom highest lowest most least largest smallest biggest maximum
        minimum best worst leading rank ranked ranking with one two three four five six seven eight
        nine ten first last name list districts blocks""".split()),
    "compare": frozenset("compare comparison between and versus vs with against districts blocks".split()),
}
_C16_DIM_WORDS = {"district": "district", "districts": "district", "block": "block", "blocks": "block"}
_C16_PLURAL_DIMS = frozenset({"districts", "blocks"})


def _c16_years(resolved: dict) -> "list[int]":
    return _mg_resolved_years(resolved)


def _c16_filters(resolved: dict) -> "dict | None":
    """{district|block|village_code: value or list, year_key: [years]} from the
    resolver's output, or None when it pinned a filter the measure cannot take."""
    if any(v not in (None, "", [], (), {}) for k, v in (resolved or {}).items() if k not in _C16_FILTER_KEYS):
        return None
    out = {}
    for key in ("district", "block", "village_code"):
        many = resolved.get(f"{key}_list")
        one = resolved.get(key)
        if many and one not in (None, ""):
            return None
        if many:
            out[key] = list(many)
        elif one not in (None, ""):
            if isinstance(one, (list, tuple, set, dict)):
                return None
            out[key] = one
    years = _c16_years(resolved)
    if years:
        out["year_key"] = years
    return out


def _c16_measure_vocabulary(m) -> frozenset:
    """The matched measure's own words: its catalogue phrases and display name,
    plain and stemmed. E7 (2026-10-29, metric_catalog_eval): the rephraser writes
    "person days" as "person days GENERATED" and "payout" as "DISBURSEMENT payout";
    the catalogue then declined ("asks more than the measure: generated") although
    the word is that measure's own ("employment generated"). Only the MATCHED
    measure's words are allowed, so a word that changes the measure ("job cards
    ISSUED" vs the job-card stock, "MONEY" for a count) is still refused."""
    out = {w for p in m.phrases for w in p}
    for w in _c01_tm_words(m.display_name or ""):
        out |= {w, metric_catalog._stem(w)}
    return frozenset(out)


def _c16_extra_words(question: str, schemes: "list[str]", entity_result: dict, taken: "frozenset[int]",
                     allowed: frozenset) -> "list[str]":
    """The question's words that are not the measure, a scheme name, a resolved
    place, a year or grammar — what the catalogue query would ignore."""
    q = question or ""
    toks = _c01_tm_tokens(q)
    named = []
    for s in schemes:
        pat = _SCHEME_NAME_MATCHER.get(s)
        if pat is not None:
            named += [(h.start(), h.end()) for h in pat.finditer(q)]
    resolved = entity_result.get("resolved") or {}
    place_words = set()
    for v in [*(entity_result.get("display") or {}).values(),
              *(resolved.get(k) for k in ("district", "block")),
              *(resolved.get("district_list") or []), *(resolved.get("block_list") or [])]:
        if isinstance(v, str):
            place_words |= {w for w in _c01_tm_words(v)}
    extra = []
    for k, t in enumerate(toks):
        w = t.low
        if k in taken or any(a <= t.start < b for a, b in named) or w in place_words:
            continue
        if w in _C16_GRAMMAR or w in allowed or metric_catalog._stem(w) in allowed or w.isdecimal():
            continue
        if w.startswith("fy") and w[2:].isdecimal():
            continue
        extra.append(w)
    return extra


def _c16_shape(question: str, filters: dict) -> "dict | None":
    """The query type the question asks for: {"qtype", "group", "order", "limit"},
    or None for a shape the catalogue query does not cover (the model answers)."""
    q = question or ""
    low = _c01_tm_words(q)
    dims = _c02_breakdowns(q, include_per=False)
    ranking = bool(_RANKING_CUE.search(q))
    lists = [k for k in ("district", "block", "village_code") if isinstance(filters.get(k), list)]
    years = filters.get("year_key") or []
    if ranking:
        if dims or lists:
            return None
        named = [_C16_DIM_WORDS[w] for w in low if w in _C16_DIM_WORDS]
        group = None
        if set(named) == {"block", "district"} and filters.get("district") and not filters.get("block"):
            group = "block"                                   # "which block in <district> …"
        elif len(set(named)) == 1:
            group = named[0]
        if group is None or filters.get(group) is not None or filters.get("village_code") is not None:
            return None
        high, lower = _C11_HIGH | {"top", "maximum"}, _C11_LOW | {"bottom", "minimum"}
        up, down = any(w in high for w in low), any(w in lower for w in low)
        if up == down:
            return None
        n = _requested_rank_count(q)
        if n is None:
            if any(w in _C16_PLURAL_DIMS for w in low):
                return None                                   # "top districts": how many is not said
            # "which district had the most": the winner plus the next two as context
            # (data-accuracy brief D3, 2026-10-29); _c17_runners_up_answer words it
            n = _C17_RUNNERS_UP
        return {"qtype": "ranking", "group": group, "order": "desc" if up else "asc", "limit": n}
    if lists:
        if len(lists) != 1 or lists[0] == "village_code" or dims - {lists[0]} or len(years) > 1:
            return None
        return {"qtype": "compare", "group": lists[0], "order": None, "limit": None}
    if len(years) > 1:
        if dims - {"year"} or not (_COMPARES_YEARS.search(q) or "year" in dims):
            return None
        return {"qtype": "compare", "group": "year", "order": None, "limit": None}
    if dims:
        if len(dims) != 1:
            return None
        group = next(iter(dims))
        if group not in ("district", "block", "year") or filters.get(group) is not None:
            return None
        if group == "district" and (filters.get("block") or filters.get("village_code")):
            return None
        return {"qtype": "breakdown", "group": group, "order": None, "limit": None}
    return {"qtype": "total", "group": None, "order": None, "limit": None}


def _metric_catalog_plan(question: str, schemes: "list[str]", entity_result: dict) -> dict:
    """What the catalogue would do with this question — for the fixed-query
    chain, the shadow log and the measurement script. Keys: status, metric,
    qtype, reason, query ((sql, params, shown) or None), verified (bool)."""
    out = {"status": "off", "metric": None, "qtype": None, "reason": "", "query": None, "verified": False}
    if metric_catalog.mode() == "off":
        return out
    if len(schemes or []) != 1:
        out.update(status="skip", reason="not one scheme")
        return out
    found = metric_catalog.match(question, schemes[0])
    out["status"] = found.status
    if found.metric is None:
        out["reason"] = f"measure: {found.status}"
        if found.status == "none":
            # B1 meaning shadow: the words left once the scheme, place, year, grammar
            # and shape words are set aside are the officer's name for the measure.
            _all_shape = frozenset().union(*_C16_SHAPE_WORDS.values())
            words = _c16_extra_words(question, schemes, entity_result, frozenset(), _all_shape)
            if 0 < len(words) <= 6:
                out["unmatched_words"] = " ".join(words)
        return out
    m = found.metric
    out["metric"] = m.key
    resolved = entity_result.get("resolved") or {}
    filters = _c16_filters(resolved)
    if filters is None:
        out["reason"] = "a filter the measure cannot take"
        return out
    shape = _c16_shape(question, filters)
    if shape is None:
        out["reason"] = "a shape the catalogue does not cover"
        return out
    out["qtype"] = shape["qtype"]
    allowed = _C16_SHAPE_WORDS.get(shape["qtype"], frozenset()) | _c16_measure_vocabulary(m)
    extra = _c16_extra_words(question, schemes, entity_result, found.spans, allowed)
    if extra:
        out["reason"] = "asks more than the measure: " + " ".join(extra[:6])
        return out
    years = filters.get("year_key") or []
    single_year = metric_catalog.single_year(m.key)
    if shape["group"] != "year":
        if single_year and len(years) != 1:
            out["reason"] = "the measure is read one financial year at a time"
            return out
        if not years and metric_catalog.YEAR_COLUMN in m.columns \
                and not (_ALL_YEARS_CUE.search(question) or _STATED_ALL_YEARS_CUE.search(question)):
            out["reason"] = "no year named"
            return out
    if shape["qtype"] == "total" and len(years) > 1:
        out["reason"] = "several years"
        return out
    query = metric_catalog.build(m, filters, shape["group"], order=shape["order"], limit=shape["limit"],
                                 qtype=shape["qtype"])
    if query is None:
        out["reason"] = "the view lacks a column the question needs"
        return out
    out.update(status="built", query=query,
               verified=metric_catalog.verified(shape["qtype"], m.key, found.phrases) is not None)
    return out


def _metric_catalog_query(question: str, schemes: "list[str]", entity_result: dict
                          ) -> "tuple[str, list, str] | None":
    """The catalogue query for the fixed-query chain, or None (model path).
    Shadow mode, and a measure not verified for this query type, log only."""
    try:
        plan = _metric_catalog_plan(question, schemes, entity_result)
    except Exception as e:  # noqa: BLE001 — never let the catalogue break a turn
        logger.warning("metric catalogue: plan failed (%s) — model path", e)
        return None
    if plan["status"] == "off":
        return None
    if plan.get("unmatched_words"):
        # B1: logged in the background — the answer never waits for it, never uses it
        try:
            asyncio.get_running_loop().create_task(
                metric_catalog.meaning_shadow(plan["unmatched_words"], schemes[0]))
        except RuntimeError:  # no running loop (a script calling this directly)
            pass
    use = plan["query"] is not None and plan["verified"] and metric_catalog.mode() == "on"
    logger.info("metric catalogue (%s): %s | metric=%s type=%s %s",
                "answers" if use else "shadow", plan["status"], plan["metric"], plan["qtype"],
                plan["reason"] or ("verified" if plan["verified"] else "not verified for this type"))
    return plan["query"] if use else None

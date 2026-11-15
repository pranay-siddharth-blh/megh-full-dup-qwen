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
                              "district_list", "block_list", "village_code_list", "year_key_list",
                              # 2026-11-14: read through the registry's constituency column (metric_catalog.build)
                              "assembly_constituency", "assembly_constituency_list"})

# Question grammar: words that ask for a figure without changing which one.
# Anything else ("wage", "average", "women", "pending") may change the measure,
# so a question carrying such a word is left to the model path.
_C16_GRAMMAR = frozenset("""
    what whats what's is are was were the a an of in for during under at to me us give show tell
    please total overall number amount count how many much did does do has have had been be
    there it its so far till until date as on now provide get find figure value data
    meghalaya state statewide whole entire all district block village c rd constituency assembly ac mapped
    fy financial fiscal year years scheme schemes s
    uh um umm hmm ok okay so well just kindly sir madam can could would you i we want need know see about
    went gone goes came come comes from
""".split())   # the last line: fillers and openings (2026-11-14: "Uh, MGNREGA, total expenditure ..." declined on "uh")
# Words a breakdown / ranking / comparison adds to the question.
_C16_SHAPE_WORDS = {
    "breakdown": frozenset("by wise each across breakdown break down split up per list every districts blocks"
                           .split()),
    "ranking": frozenset("""by which top bottom highest lowest most least largest smallest biggest maximum
        minimum best worst leading rank ranked ranking fewest greatest with one two three four five six seven eight
        nine ten first last name list districts blocks""".split()),
    "compare": frozenset("compare comparison between and versus vs with against districts blocks".split()),
}
_C16_DIM_WORDS = {"district": "district", "districts": "district", "block": "block", "blocks": "block"}
# 2026-11-14: how a follow-up OPENS ("and person-days ...?"); only at the very start of the question, so an "and"
# that joins two things to compute ("beneficiaries and amount") still declines
_C16_FOLLOWUP_LEADS = frozenset("and also but then now so plus next".split())
_C16_ALL_YEARS_WORDS = frozenset("across over throughout during combined together overall".split())
# 2026-11-14: how the answer is DRAWN ("as a bar chart", "on the map") is not something more to compute; the chart
# words declined the catalogue query ("asks more than the measure: bar chart") and the figure went to the model.
_C16_CHART_WORDS = frozenset("chart graph bar pie line donut doughnut map table plot plotted draw drawn display "
                             "displayed view horizontal form format terms visual visualise visualize on".split())
_C16_PLURAL_DIMS = frozenset({"districts", "blocks"})


def _c16_years(resolved: dict) -> "list[int]":
    return _mg_resolved_years(resolved)


def _c16_filters(resolved: dict) -> "dict | None":
    """{district|block|village_code: value or list, year_key: [years]} from the
    resolver's output, or None when it pinned a filter the measure cannot take."""
    if any(v not in (None, "", [], (), {}) for k, v in (resolved or {}).items() if k not in _C16_FILTER_KEYS):
        return None
    out = {}
    for key in ("district", "block", "village_code", "assembly_constituency"):
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


def _c16_alias_words(canonical_words: set) -> set:
    """The words of every catalogue spelling of a place the resolver pinned (2026-11-14): "MGNREGA persondays WGH
    2023-24" and "… in E Khasi Hills" were declined as asking more than the measure ("wgh", "e"), because only the
    canonical name's words counted as the place. A place is pinned when ALL words of its canonical name are in
    `canonical_words`; its aliases' words are then the place too."""
    if not canonical_words:
        return set()
    from app import entity_resolver as _er
    out: set = set()
    for dims in (_er._catalog or {}).values():
        for level in ("district", "block"):
            for v in dims.get(level) or []:
                canon = set(_c01_tm_words(str(v.get("canonical") or "")))
                if canon and canon <= canonical_words:
                    for alias in v.get("aliases") or []:
                        out |= set(_c01_tm_words(str(alias)))
    return out


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
              *(resolved.get(k) for k in ("district", "block", "assembly_constituency")),
              *(resolved.get("district_list") or []), *(resolved.get("block_list") or [])]:
        if isinstance(v, str):
            place_words |= {w for w in _c01_tm_words(v)}
    place_words |= _c16_alias_words(place_words)
    extra = []
    for k, t in enumerate(toks):
        w = t.low
        if k in taken or any(a <= t.start < b for a, b in named) or w in place_words:
            continue
        if w in _C16_GRAMMAR or w in allowed or metric_catalog._stem(w) in allowed or w.isdecimal():
            continue
        if w in _C16_CHART_WORDS:
            continue
        if w in _C16_FOLLOWUP_LEADS and not any(u.low not in _C16_FOLLOWUP_LEADS for u in toks[:k]):
            continue                       # the opening word(s) of a follow-up: "and ...", "and also ..."
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
    # a constituency crosses district and block lines: with one, only a total or a per-year list is read here
    if filters.get("assembly_constituency") is not None and (ranking or lists or dims - {"year"}):
        return None
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
        # "scheme" (2026-11-14): the dataset's own sub-schemes; metric_catalog.build declines it for a dataset
        # that has none (the view lacks the column), so only CM Elevate / CM Elevate Legacy style data take it
        if group not in ("district", "block", "year", "scheme") or filters.get(group) is not None:
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
    if found.status == "several" and 2 <= len(found.several) <= 3:
        return _c16_plan_several(question, schemes, entity_result, found, out)
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
    m = _c16_cme_default(found.metric, question, schemes)
    out["metric"] = m.key
    # Accuracy gold bank (2026-11-11, KI-709): "How many CM Elevate Legacy applicants were sanctioned in
    # 2024-25?" matched the catalogue's "CM Elevate sanctioned applicants" = COUNT(DISTINCT
    # application_number), which counts the 3 refused records that carry no sanctioned amount (2,291 for
    # 2,288). A count of SANCTIONED records is COUNT(sanctioned_amount) (SCHEMES.md, KI-166, D-097): the
    # model path answers it, with _cm_legacy_sanctioned_count behind it.
    if schemes == ["CM Elevate Legacy"] and _CML_SANCTION_COUNT_Q.search(question or "") \
            and not _CML_NOT_SANCTIONED_Q.search(question or "") \
            and "sanctioned_amount" not in str(m.expression or "").lower():
        out["reason"] = "a sanctioned count is COUNT(sanctioned_amount), not this measure"
        return out
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
    # 2026-11-14 (no-model run of the gold bank: 49 of 394 cases declined on this one word): a question that STATES
    # all years ("... across all financial years", the words the year-scope step itself adds when no year is named)
    # carries "across" / "over" as part of that phrase, not as something more to compute. The year rule below already
    # accepts the phrase; a per-year tally (single_year) is still refused there.
    if _ALL_YEARS_CUE.search(question or "") or _STATED_ALL_YEARS_CUE.search(question or ""):
        allowed = allowed | _C16_ALL_YEARS_WORDS
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


# "average / per": the words of a ratio question that are not a measure.
_C16_RATIO_WORDS = frozenset("average avg mean per each one every typical".split())
_C16_RATIO_STOP = frozenset("in for during across under of at by from statewide".split())


def _c16_measure_at(toks: "list[str]", m) -> "int | None":
    """Token index where one of the measure's catalogue phrases starts in the question, or None."""
    for i in range(len(toks)):
        for ph in m.phrases:
            if ph and tuple(toks[i:i + len(ph)]) == ph:
                return i
    return None


def _c16_ratio_pair(question: str, ms: list) -> "tuple | None":
    """(money measure, counted measure, noun) when the question asks one money total PER one counted thing:
    the money words come before "per" and the counted measure's words after it. None otherwise."""
    if len(ms) != 2:
        return None
    money = [m for m in ms if metric_catalog.money_scale(m) is not None]
    counts = [m for m in ms if metric_catalog.money_scale(m) is None]
    if len(money) != 1 or len(counts) != 1:
        return None
    toks = [metric_catalog._stem(t.low) for t in _c01_tm_tokens(question or "")]
    if "per" not in toks:
        return None
    per = toks.index("per")
    at_m, at_c = _c16_measure_at(toks, money[0]), _c16_measure_at(toks, counts[0])
    if at_m is None or at_c is None or not (at_m < per < at_c):
        return None
    noun = []
    for w in toks[per + 1:]:
        if w in _C16_RATIO_STOP or not w.isalpha():
            break
        noun.append(w)
    noun = [w for w in noun if w not in ("a", "an", "the", "each", "one")][:3] or ["unit"]
    return money[0], counts[0], "_".join(noun)


def _c16_plan_ratio(question, schemes, entity_result, found, out, money, count, noun) -> dict:
    """Money per counted thing, both verified totals over the same filters: ROUND(SUM / COUNT, 2) in one query."""
    out["metric"] = f"{money.key}/{count.key}"
    filters = _c16_filters(entity_result.get("resolved") or {})
    if filters is None:
        out["reason"] = "a filter the measure cannot take"
        return out
    shape = _c16_shape(question, filters)
    if shape is None or shape["qtype"] != "total":
        out["reason"] = "a ratio is read as one figure only"
        return out
    out["qtype"] = "ratio"
    allowed = _C16_RATIO_WORDS | _c16_measure_vocabulary(money) | _c16_measure_vocabulary(count)
    stated_all = bool(_ALL_YEARS_CUE.search(question or "") or _STATED_ALL_YEARS_CUE.search(question or ""))
    if stated_all:
        allowed = allowed | _C16_ALL_YEARS_WORDS
    extra = _c16_extra_words(question, schemes, entity_result, found.spans, allowed)
    if extra:
        out["reason"] = "asks more than the ratio: " + " ".join(extra[:6])
        return out
    years = filters.get("year_key") or []
    if len(years) > 1:
        out["reason"] = "several years"
        return out
    for m in (money, count):
        if metric_catalog.single_year(m.key) and len(years) != 1:
            out["reason"] = f"{m.key} is read one financial year at a time"
            return out
        if not years and metric_catalog.YEAR_COLUMN in m.columns and not stated_all:
            out["reason"] = "no year named"
            return out
        if metric_catalog.verified("total", m.key, found.phrases) is None:
            out.update(status="built", query=None, verified=False, reason=f"{m.key} not verified for a total")
            return out
    q = metric_catalog.ratio_query(money, count, filters, f"amount_per_{noun}_rupees")
    if q is None:
        out["reason"] = "the view lacks a column the question needs"
        return out
    out.update(status="built", query=q, verified=True)
    return out


# The words that join two figures asked together ("producer groups AND total", "subsidy PLUS loan").
_C16_JOIN_WORDS = frozenset("and plus also both as well along with".split())


def _c16_cme_default(m, question: str, schemes: "list[str]"):
    """The CM Elevate default in the catalogue (D-B1-CME-01): the all-applications measure becomes the valid-only one
    when the knowledge base's default (`applications_default`, cme_pending_rule) is that measure's own filter and the
    question neither asks for all applications nor names a verification state — the same tests the model path's
    rewrite uses (_cm_elevate_valid_default). Any other measure is returned as it is."""
    if schemes != ["CM Elevate"] or m.key != "cm_elevate_applications":
        return m
    valid = metric_catalog._state.get("metrics", {}).get("cm_elevate_applications_valid")
    default = (_pending_rule.default_sql() or "").replace(" ", "").lower()
    if valid is None or not default or default not in str(valid.expression).replace(" ", "").lower():
        return m
    if _cme_asks_all_applications(question) or _cme_names_verification_state(question):
        return m
    return valid


def _c16_plan_several(question: str, schemes: "list[str]", entity_result: dict, found, out: dict) -> dict:
    """Two or three measures asked together, each as one total over the same place and year (2026-11-14): each is
    built as its own verified total and read in one query (metric_catalog.combine_totals). Any measure that could
    not be answered alone the same way declines the whole question (the model path answers it)."""
    ms = list(found.several)
    out["metric"] = "+".join(m.key for m in ms)
    pair = _c16_ratio_pair(question, ms)
    if pair is not None:
        return _c16_plan_ratio(question, schemes, entity_result, found, out, *pair)
    if schemes == ["CM Elevate Legacy"] and _CML_SANCTION_COUNT_Q.search(question or ""):
        out["reason"] = "a sanctioned count is COUNT(sanctioned_amount), not this measure"
        return out
    filters = _c16_filters(entity_result.get("resolved") or {})
    if filters is None:
        out["reason"] = "a filter the measure cannot take"
        return out
    shape = _c16_shape(question, filters)
    if shape is None or shape["qtype"] != "total":
        out["reason"] = "several measures: only totals are read together"
        return out
    out["qtype"] = "total"
    allowed = _C16_JOIN_WORDS
    for m in ms:
        allowed = allowed | _c16_measure_vocabulary(m)
    stated_all = bool(_ALL_YEARS_CUE.search(question or "") or _STATED_ALL_YEARS_CUE.search(question or ""))
    if stated_all:
        allowed = allowed | _C16_ALL_YEARS_WORDS
    extra = _c16_extra_words(question, schemes, entity_result, found.spans, allowed)
    if extra:
        out["reason"] = "asks more than the measures: " + " ".join(extra[:6])
        return out
    years = filters.get("year_key") or []
    if len(years) > 1:
        out["reason"] = "several years"
        return out
    parts = []
    for m in ms:
        if metric_catalog.single_year(m.key) and len(years) != 1:
            out["reason"] = f"{m.key} is read one financial year at a time"
            return out
        if not years and metric_catalog.YEAR_COLUMN in m.columns and not stated_all:
            out["reason"] = "no year named"
            return out
        q = metric_catalog.build(m, filters, None, qtype="total")
        if q is None:
            out["reason"] = f"the view of {m.key} lacks a column the question needs"
            return out
        if metric_catalog.verified("total", m.key, found.phrases) is None:
            out.update(status="built", query=None, verified=False, reason=f"{m.key} not verified for a total")
            return out
        parts.append((m, q))
    out.update(status="built", query=metric_catalog.combine_totals(parts), verified=True)
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

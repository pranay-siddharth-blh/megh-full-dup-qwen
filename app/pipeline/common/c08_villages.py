# app/pipeline/common/c08_villages.py — village resolution shared by all schemes, AC readings, village scan.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
#
# Text matching (D-047): word checks are app.text_match Matchers
# (`_tm`, imported in c07_mentions); punctuation-sensitive ones are _CharScan
# steps written out by hand below.

_C08_WS = _GapIs(_gap_ws)                                    # one or more spaces between two words
_C08_AFTER_COMMA = _GapIs(lambda g: g.rstrip().endswith(","))  # a comma, then any spaces, right before a word


def _c08_is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _c08_word_end(text: str, i: int) -> bool:
    """A word ends at i, right after a word character (no word character at i)."""
    return i >= len(text) or not _c08_is_word(text[i])


def _c08_ci_at(text: str, i: int, word: str) -> bool:
    return text[i:i + len(word)].lower() == word


def _c08_ws_plus(text: str, i: int) -> int:
    r"""End of the run of whitespace at i, or -1 when no whitespace is there."""
    j = _ws_run_end(text, i)
    return j if j > i else -1



# The level word a resumed collision chip (or the user, unprompted) put in the
# question — "..., the assembly constituency, not another area type". When
# present, the level is already settled and the collision gate must not fire
# again; it also tells the branches below which dimension to force.
_EXPLICIT_LEVEL_MATCH = {
    # "assembly constituency", "constituency…", "AC", "assembly", "MLA" (any case)
    "assembly_constituency": _tm.Matcher(_tm.Alt(_tm.W("constituenc", prefix=True),
                                                 _tm.W("ac", "assembly", "mla"))),
    "block": _tm.Matcher(_tm.W("block")),
    "village": _tm.Matcher(_tm.W("village")),
    "district": _tm.Matcher(_tm.W("district")),
}


# Assembly constituency is recorded on exactly ONE fact directly:
# curated.fact_mgnrega_employment (surfaced as curated.v_employment, see
# data/schema/schema_for_developers.md). It does not exist on MGNREGA
# expenditure, nor on PMAY-G / Focus Plus / CM Elevate at all — the resolver
# YAML says so outright ("expenditure: null — this dimension does not exist in
# mgnrega_expenditure"). Offering "the X assembly constituency" as a chip for a
# question about expenditure or houses would therefore invite the user to pick
# a reading that can never be answered, so the chip is suppressed for those.
#
# FOCUS LEGACY IS THE EXCEPTION, and its own contract is explicit about it:
# v_focus_legacy exposes geography_key, so joining curated.dim_geography for
# ac_name/ac_number is a permitted dimension join on a declared FK
# (focuslegacy_schema_partitions.yaml semantic_rules.constituency_rule,
# status ANSWERABLE_ONLY_BY_AN_EXPLICIT_DIMENSION_JOIN; the worked SQL is
# sanctioned_patterns.constituency in the join-graph YAML, and
# schema_context's Focus Legacy block already ships it). The rule's own
# runtime_behavior says "Answer the question ... Do not silently refuse", so
# suppressing the AC reading for this scheme hid a level the data can answer:
# "How many Producer Groups are mapped to Amlarem?" offered only block and
# village, though Amlarem is also a constituency (reported 2026-09-23).
#
# The employment measures that DO carry it, per that same schema: person-days,
# households/persons employed, job cards, 100-days completions, women
# employment. Anything else on MGNREGA is expenditure-side.
def _c08_one_space_or_dash(g: str) -> bool:
    r"""Exactly one whitespace character or one hyphen."""
    return g == "-" or (len(g) == 1 and g.isspace())


class _C08NearWord(_tm.Node):
    """`a`, then within `max_chars` characters none of which is in `banned`,
    the word `b` (both whole words, not inside longer words)."""

    def __init__(self, a, b, max_chars: int, banned: str):
        self.a, self.b, self.max_chars, self.banned = a, b, max_chars, banned

    def ends(self, ctx, i, caps):
        for j, c2 in self.a.ends(ctx, i, caps):
            if j == 0:
                continue
            a_end = ctx.toks[j - 1].end
            for k in range(j, len(ctx.toks)):
                between = ctx.text[a_end:ctx.toks[k].start]
                if len(between) > self.max_chars or any(ch in self.banned for ch in between):
                    break
                yield from self.b.ends(ctx, k, c2)


_AC_CAPABLE_METRIC = _tm.Matcher(_tm.Alt(
    _tm.W("personday", "persondays", "jobcard", "jobcards", "muster", "100day", "100days"),
    _tm.Seq(_tm.W("person", "100"), _GapIs(_c08_one_space_or_dash), _tm.W("day", "days")),
    _tm.Seq("job", _GapIs(lambda g: len(g) == 1 and g.isspace()), _tm.W("card", "cards")),
    _tm.Seq("hundred", _C08_WS, _tm.W("day", "days")),
    _C08NearWord(_tm.W("household", "households", "person", "persons", "people", "women", "men"),
                 _tm.W("employ", "work", "receiv", prefix=True), 30, "?.!"),
    _tm.W("employ", "beneficiar", prefix=True),
    _tm.W("worker", "workers"),
))
# Metric words that are unambiguously expenditure-side — no AC column exists
# for these even within MGNREGA.
# ("wage bill" / "material cost" are covered by "wage" / "cost" on their own.)
_AC_INCAPABLE_METRIC = _tm.Matcher(_tm.Alt(
    _tm.W("expenditure", "spend", "spending", "spent", "wage", "wages", "amount", "cost",
          "utilisation", "utilization", "house", "houses", "instalment", "instalments",
          "installment", "installments", "application", "applications"),
    _tm.W("sanction", "releas", "disburs", prefix=True),
))


# The schemes whose data can answer a constituency question at all. MGNREGA
# carries ac_name on its employment fact; Focus Legacy reaches it through the
# documented dim_geography join on geography_key. PMAY-G, Focus Plus and CM
# Elevate have no route to it and keep the unconditional refusal. CM Elevate
# Legacy reaches it the same way as Focus Legacy (geography_key -> dim_geography,
# a declared FK), and the join matches the source workbook's own
# mapped_constituency_name exactly (Mairang 52 = 52, verified 2026-09-25).
#
# CM Elevate (the applications data) carries the same geography_key on every
# row, so it reaches ac_name by the same join (417 applications in Umsning
# constituency). Without it "How many CM-ELEVATE applications are mapped to
# Umsning?" offered only block or village and answered the block (CM Elevate
# Legacy TC-31, test run 2026-10-06).
#
# PMAY-G: v_pmay carries ac_name itself (dim_geography's, the same mapping MGNREGA
# uses; every row has one). Left out, a constituency question was answered by the
# model with a bare ac_name = 'AMLAREM' — a false 0 for Amlarem, Mawlai, North Tura
# (PMAY-G sheet re-test 2026-10-30, KI-445).
_AC_CAPABLE_SCHEMES = ("MGNREGA", "Focus Legacy", "CM Elevate Legacy", "CM Elevate", "PMAY-G")


# The tail a village-disambiguation chip writes: ", RERAPARA block, SOUTH WEST
# GARO HILLS" (see _village_chip_question). A year chip tapped afterwards appends
# its period (" across all financial years", " for FY 2022-23"), which must not
# hide the tail (Focus Legacy all-villages run 2026-09-29, KI-156).
# Shape (case-insensitive): a comma; the block name (a letter, then letters and
#   . ' ( ) - space, as short as possible); the word "block"; a comma; the district
#   name (a letter, then letters and . ' - space); optionally a year phrase (see
#   _c08_year_phrase_ends) and text with no comma or "?"; then at most one ? or . to the end.
_C08_BLOCK_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.'()- ")
_C08_DISTRICT_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.'- ")


def _c08_year_phrase_ends(text: str, i: int) -> list:
    r"""Ends of "across/for/in/during/over [all] [the] financial year(s) / year(s) / fy"
    (spaces before and between, a whole word last) starting at i (case-insensitive)."""
    j = _c08_ws_plus(text, i)
    if j < 0:
        return []
    for prep in ("across", "for", "in", "during", "over"):
        if _c08_ci_at(text, j, prep):
            k = _c08_ws_plus(text, j + len(prep))
            if k >= 0:
                break
    else:
        return []
    starts = []
    for take_all in (True, False):
        a = k
        if take_all:
            if not _c08_ci_at(text, a, "all"):
                continue
            a = _c08_ws_plus(text, a + 3)
            if a < 0:
                continue
        for take_the in (True, False):
            b = a
            if take_the:
                if not _c08_ci_at(text, b, "the"):
                    continue
                b = _c08_ws_plus(text, b + 3)
                if b < 0:
                    continue
            starts.append(b)
    out = []
    for b in starts:
        if _c08_ci_at(text, b, "financial"):
            c = _c08_ws_plus(text, b + 9)
            if c >= 0 and _c08_ci_at(text, c, "year"):
                for e in (c + 5, c + 4) if _c08_ci_at(text, c, "years") else (c + 4,):
                    if _c08_word_end(text, e):
                        out.append(e)
        if _c08_ci_at(text, b, "year"):
            for e in (b + 5, b + 4) if _c08_ci_at(text, b, "years") else (b + 4,):
                if _c08_word_end(text, e):
                    out.append(e)
        if _c08_ci_at(text, b, "fy") and _c08_word_end(text, b + 2):
            out.append(b + 2)
    return out


def _c08_tail_end_ok(rest: str) -> bool:
    r"""The whole of `rest` is only spaces and at most one ? or ."""
    r = rest.lstrip()
    if r[:1] in ("?", "."):
        r = r[1:]
    return r.strip() == "" and (r == "" or r.isspace())


def _c08_chip_tail_at(text: str, i: int, *, to_end: bool):
    """The village-chip tail at i: (end, {"block": span, "district": span}) or None.
    to_end=True is _CHIP_TAIL_PARSE_MATCH; False is _YEAR_AFTER_CHIP_TAIL_MATCH."""
    n = len(text)
    if i >= n or text[i] != ",":
        return None
    j = _ws_run_end(text, i + 1)
    if j >= n or text[j] not in _ASCII_LETTERS:
        return None
    bend = j + 1
    while True:                                          # lazy block name
        k = _c08_ws_plus(text, bend)
        if k >= 0 and _c08_ci_at(text, k, "block"):
            c = _ws_run_end(text, k + 5)
            if c < n and text[c] == ",":
                d = _ws_run_end(text, c + 1)
                if d < n and text[d] in _ASCII_LETTERS:
                    dend = d + 1
                    while True:                          # lazy district name
                        for ye in _c08_year_phrase_ends(text, dend):
                            if not to_end:
                                return ye, {"block": (j, bend), "district": (d, dend)}
                            for cut in range(n, ye - 1, -1):      # longest first, no ',' or '?'
                                seg = text[ye:cut]
                                if "," in seg or "?" in seg:
                                    continue
                                if _c08_tail_end_ok(text[cut:]):
                                    return n, {"block": (j, bend), "district": (d, dend)}
                        if to_end and _c08_tail_end_ok(text[dend:]):
                            return n, {"block": (j, bend), "district": (d, dend)}
                        if dend < n and text[dend] in _C08_DISTRICT_NAME_CHARS:
                            dend += 1
                        else:
                            break
        if bend < n and text[bend] in _C08_BLOCK_NAME_CHARS:
            bend += 1
        else:
            return None


_CHIP_TAIL_PARSE_MATCH = _CharScan(lambda text, i: _c08_chip_tail_at(text, i, to_end=True))


# A village chip's ", X block, DISTRICT" tail with a year chip's phrase after it
# ("…, JIRANG block, RI BHOI across all financial years" / "… for FY 2022-23").
# Shape: a comma, a block name, the word "block", a comma, a district name, then
#       the year phrase of _c08_year_phrase_ends (the same name rules as the tail above).
_YEAR_AFTER_CHIP_TAIL_MATCH = _CharScan(
    lambda text, i: (lambda r: (r[0], []) if r else None)(_c08_chip_tail_at(text, i, to_end=False)))


# "<preposition> NAME village" — the name the user typed, read from the text (see
# the explicit-level village step in resolve_entities). A name word is never a
# preposition, so "for East Garo Hills in Abima village" yields "Abima".
# "&", a spaced "-" and a spaced ")" too: "MAWKOHMIT & MAWKYNSAH", "SIEJLIEH -
# MAWIABAN", "Jong - U - Shen" and "RAMJONGGRE ( R )" are each ONE village —
# without the ")" the last was answered as its neighbour "RAMJONGGRE ( L )"
# (all-villages run 2026-09-29).
# Shape (case-insensitive): a whole-word preposition (in/for/of/at/to/from/within),
#   spaces, an optional "the", then 1-7 name words separated by spaces, then spaces and
#   the whole word "village". A name word starts with a letter, digit, ( ) & or -, goes
#   on with letters, digits, _ ( ) . ' & -, and is never in/for/of/at/to/from/within/the/and.
_C08_VILLAGE_PREPS = ("in", "for", "of", "at", "to", "from", "within")
_C08_NOT_A_NAME_WORD = ("in", "for", "of", "at", "to", "from", "within", "the", "and")
_C08_NAME_FIRST = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()&-")


def _c08_name_word_end(text: str, i: int) -> int:
    """End of one village-name word at i, or -1."""
    n = len(text)
    if i >= n or text[i] not in _C08_NAME_FIRST:
        return -1
    for w in _C08_NOT_A_NAME_WORD:
        if _c08_ci_at(text, i, w) and _c08_word_end(text, i + len(w)):
            return -1
    j = i + 1
    while j < n and (_c08_is_word(text[j]) or text[j] in "().'&-"):
        j += 1
    return j


def _c08_village_phrase_at(text: str, i: int):
    if i > 0 and _c08_is_word(text[i - 1]):
        return None
    for prep in _C08_VILLAGE_PREPS:
        if _c08_ci_at(text, i, prep):
            j = _c08_ws_plus(text, i + len(prep))
            if j >= 0:
                break
    else:
        return None
    if _c08_ci_at(text, j, "the"):
        t = _c08_ws_plus(text, j + 3)
        if t >= 0 and _c08_name_word_end(text, t) >= 0:
            j = t
    ends = []                                  # end of each name word, in order
    w = j
    while len(ends) < 7:
        e = _c08_name_word_end(text, w)
        if e < 0:
            break
        ends.append(e)
        w = _c08_ws_plus(text, e)
        if w < 0:
            break
    for e in reversed(ends):                   # up to 6 words, longest first
        v = _c08_ws_plus(text, e)
        if v >= 0 and _c08_ci_at(text, v, "village") and _c08_word_end(text, v + 7):
            return v + 7, [(j, e)]
    return None


_VILLAGE_PHRASE_MATCH = _CharScan(_c08_village_phrase_at)


async def _resolve_village_for(schemes: "list[str] | None", text: str, **kw) -> "Resolved":
    """resolve_village, minus the "Unresolved / Not Yet Mapped" placeholder rows
    for MGNREGA. Those rows belong to other schemes' unmapped records; MGNREGA's
    facts hold none (0 in v_employment and v_expenditure), yet an alias pointed
    "BLOCK CAMPUS" at one, so a unique village drew a "which of these?" pause
    (all-villages QA 2026-09-26)."""
    r = await resolve_village(text, **kw)
    if r.status == "ambiguous":
        r.candidates = await _fl_rank_villages(schemes, await _fl_expand_twins(schemes, r.candidates))
    if r.status == "ambiguous" and list(schemes or []) == ["MGNREGA"]:
        r.candidates = await _mgnrega_villages_with_data(r.candidates)
        if len(r.candidates) == 1:
            c = r.candidates[0]
            return Resolved("resolved", "village", text, canonical=c["village_code"],
                            confidence=1.0, display=_place_title(str(c["name"])))
    if _village_scheme(schemes) in _VILLAGE_NARROW_SCHEMES:
        r = await _focusplus_narrow_village(r, text, kw, _village_scheme(schemes))
    if _village_scheme(schemes) and r.status == "ambiguous":
        keep = [c for c in r.candidates if not str(c.get("name", "")).strip().lower().startswith("unresolved")]
        # A village's OWN name beats an alias hit: an alias row maps the text
        # "WEST RANGASORA" to EAST RANGASORA too, so the exact name drew a
        # "which one?" pause (all-villages QA 2026-09-26).
        _own = [c for c in keep if _tm.collapse_ws(str(c.get("name", ""))).lower()
                == _tm.collapse_ws(str(text or "")).lower()]
        if len({c["village_code"] for c in _own}) == 1:
            keep = _own[:1]
        if len(keep) == 1:
            return Resolved("resolved", "village", text, canonical=keep[0]["village_code"],
                            confidence=1.0, display=_place_title(str(keep[0]["name"])))
        if keep and len(keep) < len(r.candidates):
            r.candidates = keep
    if schemes == ["Focus Legacy"] and r.status == "resolved" and str(r.canonical or "").isdigit():
        # resolve_village merges same-name twins in ONE block by data volume
        # across all schemes. TIEHSAW and UMSAW (Nongstoin) are twins that BOTH
        # hold Focus Legacy groups, so the merge answered for the wrong one
        # (all-villages run 2026-09-29, KI-163): ask, with LGD-coded chips.
        try:
            twins = await fetch_rows(
                "SELECT g2.village_code, g2.lgd_village_name AS name, g2.lgd_block AS block, "
                "g2.lgd_district AS district FROM curated.dim_geography g1 JOIN curated.dim_geography g2 "
                "ON UPPER(g2.lgd_village_name) = UPPER(g1.lgd_village_name) "
                "AND g2.lgd_block IS NOT DISTINCT FROM g1.lgd_block AND g2.lgd_district = g1.lgd_district "
                "WHERE g1.village_code = $1 AND EXISTS (SELECT 1 FROM curated.v_focus_legacy f "
                "WHERE f.village_code = g2.village_code) ORDER BY g2.village_code", [int(r.canonical)])
        except Exception:  # noqa: BLE001 — keep the resolver's choice
            twins = []
        if len(twins) > 1:
            return Resolved("ambiguous", "village", text, candidates=[dict(t) for t in twins],
                            message=f"“{text}” corresponds to more than one village.")
    return r

# Schemes whose facts are village-grained and carry village_code on the row.
# The village-resolution guards below were built for MGNREGA in the 2026-09-26
# all-villages QA; the Focus Plus all-villages run (2026-09-27) failed on every
# one of the same shapes (village read as a block, chip tail read as a block
# question, a block literal beside the village_code, a wrong code), so they
# apply to both.
# PMAY-G joined on 2026-09-28 (PMAY-G all-villages run): v_pmay is house-grained
# with village_code on every row, and failed the same shapes (exact name paused
# against a fuzzy look-alike, chip tail answered as the block, wrong code).
# CM Elevate joined on 2026-09-28 (CM Elevate all-villages run, KI-106): v_cm_elevate
# is application-grained with village_code on every row, and its smoke run failed
# the same shapes — a block total reported for the village, the village name put in
# the district slot, a neighbour's code (LENMAWTAP vs LENMAWTAP A), a chip that
# re-asked, "UPPER KAMARI (GARO)" read as the Garo Hills range.
_VILLAGE_FACT_SCHEMES = ("MGNREGA", "Focus Plus", "PMAY-G", "CM Elevate")
# the single-scheme members that share the Focus Plus narrowing / pinning guards
# Focus Legacy joined 2026-10-02 (all-villages run, bare village names): a name
# typed without the word "village" was never scanned — "producer groups in
# BOLDAMGRE" / "BALACHANDA I" were answered with Selsella block's 399, BATABARI
# (village AND block) silently as the block, KASHARIPARA with a stray district
# filter. Its questions passed on 2026-09-29 only because they said "village".
# CM Elevate Legacy joined the same night, for the same bare-name failures
# (AMLARI MODEL / NAPAKGRE written as scheme_name, "(B)" qualifiers lost, MANIPUR
# refused as the state, NONGSTOIN village vs block).
_VILLAGE_NARROW_SCHEMES = ("Focus Plus", "PMAY-G", "CM Elevate", "Focus Legacy", "CM Elevate Legacy")


def _village_scheme(schemes: "list[str] | None") -> "str | None":
    """The village-grained scheme the guards run for, or None. MGNREGA keeps the
    exact old gate (`schemes[0] == "MGNREGA"`, any list length); Focus Plus,
    PMAY-G and CM Elevate only when they are the one scheme asked about."""
    if not schemes:
        return None
    if schemes[0] == "MGNREGA":
        return "MGNREGA"
    if len(schemes) == 1 and schemes[0] in _VILLAGE_NARROW_SCHEMES:
        return schemes[0]
    return None
def _c08_two_words_end(text: str, i: int, a: str, b: str) -> int:
    """End of `a`, whitespace, `b` (case-insensitive) at i, or -1."""
    if not _c08_ci_at(text, i, a):
        return -1
    j = _c08_ws_plus(text, i + len(a))
    return j + len(b) if j >= 0 and _c08_ci_at(text, j, b) else -1


def _c08_urban_body_at(text: str, i: int):
    r"""Any spaces/hyphens, then the whole words MUNICIPAL BOARD or TOWN COMMITTEE (case-insensitive)."""
    j = i
    while j < len(text) and (text[j].isspace() or text[j] == "-"):
        j += 1
    for a, b in (("municipal", "board"), ("town", "committee")):
        e = _c08_two_words_end(text, j, a, b)
        if e >= 0 and _c08_word_end(text, e):
            return e, []
    return None


def _c08_initials_end(text: str, i: int, a: str, b: str) -> int:
    r"""End of a, optional ".", optional one space, b, optional "." (case-insensitive)
    at i, at a word edge, or -1. The trailing "." belongs to the match only when a
    word character follows it (the only way a word edge can sit right after it)."""
    if not _c08_ci_at(text, i, a):
        return -1
    n = len(text)
    j = i + 1
    if j < n and text[j] == ".":
        j += 1
    if j < n and text[j].isspace():
        j += 1
    if not _c08_ci_at(text, j, b):
        return -1
    e = j + 1
    if e < n and text[e] == "." and e + 1 < n and _c08_is_word(text[e + 1]):
        return e + 1
    return e if _c08_word_end(text, e) else -1


def _c08_urban_word_at(text: str, i: int):
    r"""A whole word/phrase: municipal [board], town committee, or the initials m b / t c
    (each with optional dots and one optional space) (case-insensitive)."""
    if i > 0 and _c08_is_word(text[i - 1]):
        return None
    for e in (_c08_two_words_end(text, i, "municipal", "board"),
              i + 9 if _c08_ci_at(text, i, "municipal") else -1,
              _c08_two_words_end(text, i, "town", "committee")):
        if e >= 0 and _c08_word_end(text, e):
            return e, []
    for a, b in (("m", "b"), ("t", "c")):
        e = _c08_initials_end(text, i, a, b)
        if e >= 0:
            return e, []
    return None


# the urban local bodies the data writes as "<TOWN>-MUNICIPAL BOARD" / "-TOWN COMMITTEE"
_URBAN_BODY_MATCH = _CharScan(_c08_urban_body_at)
_URBAN_WORD_MATCH = _CharScan(_c08_urban_word_at)


async def _scheme_village_names(scheme: str) -> "dict[str, list[dict]]":
    if scheme == "CM Elevate":
        return await _cm_elevate_village_names()
    if scheme == "Focus Legacy":
        return await _focus_legacy_village_names()
    if scheme == "CM Elevate Legacy":
        return await _cm_legacy_village_names()
    if scheme == "PMAY-G":
        return await _pmay_village_names()
    return await (_focusplus_village_names() if scheme == "Focus Plus" else _mgnrega_village_names())


async def _mask_scheme_words_in_village_name(question: str) -> str:
    """The question with an exact MGNREGA village name masked, when that name on
    its own reads as scheme vocabulary ("UMRAN DAIRY" -> CM Elevate). Otherwise
    the question unchanged. Used for scheme detection only."""
    try:
        found = await _mgnrega_longest_village_in(question)
    except Exception:  # noqa: BLE001
        return question
    if not found:
        return question
    name = found[0]
    if not (_infer_scheme_from_terms(name) or any(word_matcher.search(name) for word_matcher in _SCHEME_NAME_MATCHER.values())):
        return question
    masked = _ci_replace(question, name, "the village", count=1)
    logger.info("scheme detection: village name %r masked (its words read as scheme vocabulary)", name)
    return masked


def _ac_dimension_available(question: str, schemes: list[str]) -> bool:
    """True when an assembly-constituency reading of a place name could
    actually be queried for THIS question. False suppresses the AC chip."""
    _live = list(schemes or [])
    if len(_live) != 1 or _live[0] not in _AC_CAPABLE_SCHEMES:
        return False
    if _live[0] in ("CM Elevate Legacy", "CM Elevate", "PMAY-G"):
        # Every measure on these views (records, sanctioned, subsidy, loan,
        # disbursement; applications, status; PMAY-G's houses and amounts, on
        # v_pmay.ac_name) hangs off the same geography_key,
        # so the MGNREGA employment-vs-expenditure metric test does not apply.
        return True
    q = question or ""
    # An explicit expenditure/housing metric rules it out even if an
    # employment-ish word also appears ("wage employment expenditure").
    if _AC_INCAPABLE_METRIC.search(q) and not _AC_CAPABLE_METRIC.search(q):
        return False
    if _AC_CAPABLE_METRIC.search(q):
        return True
    # No metric named at all ("figures for Sohra") — leave the reading open
    # rather than silently dropping a valid choice.
    return not _AC_INCAPABLE_METRIC.search(q)


# ── Step 2 of the hierarchy: narrowing inside a chosen constituency ─────────
# Once the user has said "I meant the constituency", they may still want only
# part of it. An AC is an electoral boundary rather than an administrative
# parent — 8 of the 56 straddle two districts — so the narrowing offered is
# built from what that constituency ACTUALLY contains in the data
# (entity_resolver.constituency_contents), never from a static hierarchy.
#
# The phrasing of each chip is what makes the next turn resolve cleanly: the
# district/block chips keep the constituency name AND add the area, so the
# question stays scoped to both; "the whole constituency" simply confirms.
def _c08_within_the_end(text: str, i: int) -> int:
    """End of ", within the " (any spacing, case-insensitive) at i, or -1."""
    if i >= len(text) or text[i] != ",":
        return -1
    j = _ws_run_end(text, i + 1)
    e = _c08_two_words_end(text, j, "within", "the")
    return _c08_ws_plus(text, e) if e >= 0 else -1


_AC_SCOPED_MATCH = _CharScan(lambda text, i: (lambda e: (e, []) if e >= 0 else None)(_c08_within_the_end(text, i)))
# The narrowing a resumed drill-down chip carries: ", within the <NAME>
# <district|block> only". Read deterministically rather than left to the LLM
# mention-extractor — the extractor has no reason to tag a second place name
# in a question that already names a constituency, and when it doesn't, the
# narrowing is silently lost and the answer covers the whole constituency
# again (the very thing the user just declined).
# "<X> constituency" / "<X> AC" in the user's own words (see the drill-down skip
# in resolve_entities), versus the which-area-type chip that made a bare name a
# constituency.
# Case-sensitive: lower-case "constituency"/"constituencies", upper-case "AC" /
# "AC 28" / "AC-28" / "AC28".
_USER_NAMED_CONSTITUENCY = _tm.Matcher(_tm.Alt(
    _tm.W("constituency", "constituencies", case=True),
    _tm.W("AC", case=True),
    _tm.Pred(lambda w: w[:2] == "AC" and len(w) > 2 and w[2:].isdecimal()),
))
_AC_COLLISION_CHIP = _tm.Matcher(_tm.Seq(
    _C08_AFTER_COMMA, "the", _C08_WS, "assembly", _C08_WS, "constituency",
    _GapIs(lambda g: g[:1] == "," and _gap_ws(g[1:])),
    "not", _C08_WS, "another", _C08_WS, "area", _C08_WS, "type"))


def _c08_ac_narrow_at(text: str, i: int):
    r"""", within the <name> district|block only" (name as short as possible, level the
    next word, "only" a whole word; spaces between; case-insensitive)."""
    s0 = _c08_within_the_end(text, i)
    if s0 < 0:
        return None
    n = len(text)
    nend = s0 + 1
    while nend <= n and "\n" not in text[s0:nend]:          # lazy .+?
        k = _c08_ws_plus(text, nend)
        if k >= 0:
            for level in ("district", "block"):
                if _c08_ci_at(text, k, level):
                    o = _c08_ws_plus(text, k + len(level))
                    if o >= 0 and _c08_ci_at(text, o, "only") and _c08_word_end(text, o + 4):
                        return o + 4, {"name": (s0, nend), "level": (k, k + len(level))}
        nend += 1
    return None


_AC_NARROW_MATCH = _CharScan(_c08_ac_narrow_at)


def _ac_drilldown_clarification(question: str, ac_display: str,
                                contents: dict, scheme: "str | None" = None) -> "ClarificationNeeded | None":
    """Offer to narrow inside a just-chosen assembly constituency, or None when
    there is nothing meaningful to narrow to."""
    districts = contents.get("districts") or []
    blocks = contents.get("blocks") or []
    if not districts and not blocks:
        return None
    stem = question.strip().rstrip(" ?.")
    options = [{"label": f"The whole {ac_display} constituency",
                "question": f"{stem}, the whole constituency"}]
    # A constituency spanning two districts is the one case where the district
    # step is a real question rather than a formality.
    if len(districts) > 1:
        for d in districts:
            options.append({
                "label": f"Only the {str(d).title()} part",
                "question": f"{stem}, within the {d} district only",
            })
    for b in blocks[:8]:
        options.append({
            "label": f"{str(b).title()} block",
            "question": f"{stem}, within the {b} block only",
        })
    if len(options) < 2:
        return None
    where = (f"spans {len(districts)} districts and " if len(districts) > 1 else "covers ")
    return ClarificationNeeded(
        f"The {ac_display} assembly constituency {where}"
        f"{len(blocks)} C&RD block(s), with {contents.get('villages', 0)} villages in the "
        f"{AC_CONTENTS_SOURCE.get(scheme or 'MGNREGA', 'MGNREGA employment data')}. "
        "Do you want the whole constituency, or just part of it?",
        options=options,
        rule="ac-narrow-scope",
    )


# ── Deterministic village backstop ──────────────────────────────────────────
# scan_dimension() already backstops a district the LLM mention-extractor
# dropped. Villages had no equivalent, and the extractor drops them too —
# confirmed live 2026-09-15: "total beneficiaries in ASIMGRE for MGNREGA for
# East Khasi Hills" came back {"district": "East Khasi Hills"} with ASIMGRE
# missing entirely. With no village mention there is nothing to resolve, the
# ambiguity check never runs, and the filter silently disappears: the query
# counted the WHOLE district while the answer still said "for ASIMGRE".
#
# A village scan has to be much more careful than the district one. There are
# ~6,000 villages and resolve_village()'s trigram stage matches loosely enough
# that ordinary words — and fragments of district names like "East", "Garo",
# "Hills" — all hit something. So this scan is doubly constrained:
#   1. candidates come only from a place-preposition phrase ("in X", "for X",
#      "of X"), the grammar that actually introduces a place; and
#   2. a candidate must match a village name EXACTLY (village_names_exact),
#      never fuzzily.
# A name that is already a known district / block / constituency is skipped —
# those dimensions own it, and the admin-level collision gate handles the
# genuinely ambiguous ones.
# The name may carry a parenthesised suffix that is PART of it — Meghalaya has
# "NONGCHRAM (I)" and "NONGCHRAM (II)" as two distinct villages in the same
# block. Without the optional "(...)" tail the scan proposes a bare "NONGCHRAM",
# which matches no stored name exactly, so the backstop finds nothing and the
# village filter is silently lost (reported 2026-09-17).
# Candidate place phrases after a preposition. Deliberately tolerant on TWO
# axes, because both were observed dropping a real village:
#   CASE — users type lowercase ("in william nagar(mb) - ward no.4"). A
#     capital-first check skipped those entirely, so the backstop never ran
#     and the truncated extractor mention went unchallenged.
#   SUFFIX CHAIN — a name can carry MORE THAN ONE part-marker:
#     "William Nagar (MB) - Ward No.4" is a parenthesised marker AND a
#     hyphenated one. Matching only the first stops at "William Nagar (MB)",
#     which is ambiguous across 12 wards and loops the clarification forever
#     (reported 2026-09-17).
# Precision still comes from village_names_exact(): a candidate only counts
# if it matches a stored village name EXACTLY, so a loose phrase costs one
# lookup and nothing more.
# The shape (case-SENSITIVE prepositions):
#   a whole-word in/for/of/at/from/within/under, then spaces, then the name:
#   1-4 words (a letter, then letters and . ' -) separated by spaces, then up to
#     two markers, each either "(...)" holding 1-20 letters, digits, spaces, . ' -
#     or "-" and one or two short tokens (a letter/digit, then up to 11 more
#     letters, digits, . '), spaces allowed around the "(" and "-".
# A hyphenated marker is at most TWO short tokens ("- A", "- Ward No.4") —
# bounded so it cannot run on into the rest of the sentence ("- Ward No.4
# for CM Elevate"), which would never match a stored name. Every piece is
# greedy and nothing follows the name, so each piece simply takes the most it can.
_C08_PLACE_WORD_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.'-")
_C08_PAREN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .'-")
_C08_MARKER_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.'")


def _c08_place_word_end(text: str, i: int) -> int:
    if i >= len(text) or text[i] not in _ASCII_LETTERS:
        return -1
    j = i + 1
    while j < len(text) and text[j] in _C08_PLACE_WORD_CHARS:
        j += 1
    return j


def _c08_marker_token_end(text: str, i: int) -> int:
    """End of a letter or digit then up to 11 letters, digits, '.' or ''' at i, or -1."""
    if i >= len(text) or text[i] not in _ASCII_ALNUM:
        return -1
    j = i + 1
    while j < len(text) and j - i <= 11 and text[j] in _C08_MARKER_CHARS:
        j += 1
    return j


def _c08_place_suffix_end(text: str, i: int) -> int:
    n = len(text)
    j = _ws_run_end(text, i)
    if j < n and text[j] == "(":
        k = j + 1
        while k < n and k - j <= 20 and text[k] in _C08_PAREN_CHARS:
            k += 1
        if k > j + 1 and k < n and text[k] == ")":
            return k + 1
    if j < n and text[j] == "-":
        e = _c08_marker_token_end(text, _ws_run_end(text, j + 1))
        if e >= 0:
            w = _c08_ws_plus(text, e)
            e2 = _c08_marker_token_end(text, w) if w >= 0 else -1
            return e2 if e2 >= 0 else e
    return -1


def _c08_place_prep_at(text: str, i: int):
    if i > 0 and _c08_is_word(text[i - 1]):
        return None
    for prep in ("in", "for", "of", "at", "from", "within", "under"):
        if text.startswith(prep, i):
            j = _c08_ws_plus(text, i + len(prep))
            if j >= 0:
                break
    else:
        return None
    e = _c08_place_word_end(text, j)
    if e < 0:
        return None
    for _ in range(3):
        w = _c08_ws_plus(text, e)
        e2 = _c08_place_word_end(text, w) if w >= 0 else -1
        if e2 < 0:
            break
        e = e2
    for _ in range(2):
        e2 = _c08_place_suffix_end(text, e)
        if e2 < 0:
            break
        e = e2
    return e, {"name": (j, e)}


_PLACE_PREP_MATCH = _CharScan(_c08_place_prep_at)
# Words that open a phrase without naming a place; a candidate that is only
# these is never a village.
_NOT_A_PLACE_WORD = {
    "mgnrega", "mnrega", "nrega", "pmay", "pmayg", "awaas", "awas",
    "focus", "focus plus", "focusplus", "cm", "cm elevate", "cmelevate",
    "meghalaya", "fy", "financial", "financial year", "all", "each", "every",
    "the", "a", "an", "this", "that", "total", "district", "block", "village",
    "assembly", "constituency", "state", "india", "government", "scheme",
}


def _village_scan_candidates(question: str, scheme: str) -> list[str]:
    """Names in `question` that could be a village the extractor missed."""
    known: set[str] = set()
    for dim in ("district", "block", "assembly_constituency"):
        for n in canonical_names(scheme, dim):
            known.add(n.strip().upper())
    out: list[str] = []
    # Lookahead so matches can OVERLAP: finditer consumes what it matches, so a
    # phrase starting at an earlier preposition ("under goat farming scheme in")
    # would swallow the "in" that introduces the real place and the village
    # would never be scanned at all (reported 2026-09-17, lowercase "in william
    # nagar(mb) - ward no.4"). Every preposition now gets its own attempt.
    _q = question or ""
    for _at in range(len(_q) + 1):
        m = _c08_place_prep_at(_q, _at)
        if m is None:
            continue
        raw = _q[m[1]["name"][0]:m[1]["name"][1]].strip().rstrip(".,")
        if not raw:
            continue
        # Try the longest phrase first, then progressively shorter prefixes, so
        # "ASIMGRE for MGNREGA" still yields the bare "ASIMGRE".
        words = raw.split()
        for take in range(len(words), 0, -1):
            cand = " ".join(words[:take]).strip()
            low = cand.lower()
            if len(cand) < 4 or low in _NOT_A_PLACE_WORD:
                continue
            if cand.upper() in known:
                break        # a district/block/AC owns this name — not our job
            if cand not in out:
                out.append(cand)
    return out


async def _scan_village_in_question(question: str, scheme: str) -> "tuple[str, list[dict]] | None":
    """(name, candidate villages) for a village named in the question that the
    extractor dropped, or None. Exact matches only."""
    cands = _village_scan_candidates(question, scheme)
    if not cands:
        return None
    found = await village_names_exact(cands)
    if not found:
        return None
    # Preserve the order the names appear in the question.
    for c in cands:
        hits = found.get(c.upper())
        if hits:
            return c, hits
    return None


def _canonical_in_question(question: str, scheme: str, dimension: str) -> "str | None":
    """The catalogue name for `dimension` that appears verbatim in `question`,
    or None. Used when resuming an admin-level collision chip: the chip put the
    CANONICAL name into the question text, so reading it back from there is
    more reliable than trusting the LLM extractor, which may still be echoing
    the user's original typo. Longest match wins, so "North Tura" is not
    shadowed by "Tura"."""
    best: str | None = None
    # collision_canonical_names, not canonical_names: for block / assembly
    # constituency it falls back to another scheme's catalogue when the asking
    # scheme has none, which is what lets the admin-level gate see an AC
    # reading under CM Elevate (its catalogue has no AC dimension at all).
    for canon in collision_canonical_names(scheme, dimension):
        if _bounded_find(question or "", canon, ci=True) is not None:
            if best is None or len(canon) > len(best):
                best = canon
    return best


# A village-disambiguation chip appends its scope as ", <BLOCK> block,
# <DISTRICT>" (see _village_chip_question). Those words name the CONTAINING
# area, not the level the question is about — the question is about the
# village. Left in place they make _explicit_level_in report "block", which
# both suppresses the village backstop and lets the block slot win, so the chip
# resolves to block grain and the village is lost (confirmed 2026-09-15 on the
# ASIMGRE chips). Strip that trailing scope before detecting the level.
# Matches only the village-chip scope tail: a block name (never the word "the")
# followed by a district name, both in CAPS as _village_chip_question writes
# them, at the very end. The admin-level CHOICE chip (", the block, not another
# area type") does not match — it has "the" before "block" and trailing prose
# after the second comma.
# Shape (case-sensitive): a comma; a name (a capital, then letters and . ' - space);
# spaces and "block"; a comma; a second such name; only spaces to the end.
_C08_UPPER = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _c08_scope_suffix_at(text: str, i: int):
    n = len(text)
    if i >= n or text[i] != ",":
        return None
    j = _ws_run_end(text, i + 1)
    if j >= n or text[j] not in _C08_UPPER:
        return None
    p = text.find("block", j + 1)
    while p >= 0:
        seg = text[j:p]
        head = seg.rstrip()
        if "," in seg:
            return None
        if seg[-1:].isspace() and all(ch in _C08_DISTRICT_NAME_CHARS for ch in head) \
                and all(ch.isspace() for ch in seg[len(head):]):
            c = _ws_run_end(text, p + 5)
            if c < n and text[c] == ",":
                d = _ws_run_end(text, c + 1)
                rest = text[d:].rstrip()
                if rest and rest[0] in _C08_UPPER and all(ch in _C08_DISTRICT_NAME_CHARS for ch in rest):
                    return n, []
        p = text.find("block", p + 1)
    return None


_CHIP_SCOPE_SUFFIX_MATCH = _CharScan(_c08_scope_suffix_at)
# The level phrase a disambiguation chip always carries. Its presence is what
# marks a question as a chip resume, so the scope tail above is only stripped
# then — never from an ordinary question that happens to end the same way.
_CHIP_LEVEL_PHRASE_MATCH = _tm.Matcher(_tm.Seq(
    _C08_AFTER_COMMA, "the", _C08_WS,
    _tm.Alt(_tm.W("village", "block", "district"), _tm.Seq("assembly", _C08_WS, "constituency"))))
# "each village", "by block", "per district", "village-wise", "all villages" —
# these name the GROUPING a breakdown is computed over, never the place the
# question is scoped to. Removed before level detection so the surviving level
# word (if any) is the one that actually names a place.
_C08_LEVEL_WORDS = _tm.Alt(
    _tm.W("village", "villages", "block", "blocks", "district", "districts"),
    _tm.Seq("assembly", _C08_WS, _tm.W("constituenc", prefix=True)),
    _tm.W("constituenc", prefix=True),
)
# "which village" / "what block" names the level being RANKED or asked for, never the
# place: "Which village has the highest households … in Demdema block" read "village"
# as the stated level and resolved the VILLAGE Demdema (272799, no rows) instead of the
# block (KI-368, 2026-10-22; 2/2 live runs).
_BREAKDOWN_LEVEL_PHRASE_MATCH = _tm.Matcher(_tm.Alt(
    _tm.Seq(_tm.W("by", "per", "each", "every", "all", "across", "which", "what"), _C08_WS,
            _tm.Opt(_tm.Seq("the", _C08_WS)), _C08_LEVEL_WORDS),
    # "village-wise" / "village wise" / "villagewise"
    _tm.W("villagewise", "blockwise", "districtwise"),
    _tm.Seq(_tm.W("village", "block", "district"),
            _GapIs(lambda g: g == "-" or (len(g) == 1 and g.isspace())), "wise"),
))


# "…, the block, not the village" — the level-choice chip the block/village
# collision pause offers. The NEGATED level names what the user ruled out, so it
# must not count as the stated level. Detection is finest-first, so the
# negated "village" won over the chosen "block": MAWKYRWAT resolved to village
# 277399 and the block question got the village's 273 households instead of the
# block's 11,590, or no answer at all (MGNREGA QA 2026-09-26, DATA-003/016/020/
# 029, KNOWN_ISSUES KI-041). Stripped for MGNREGA only (the user asked that
# other schemes stay unchanged).
_NEGATED_LEVEL_MATCH = _tm.Matcher(_tm.Seq(
    "not", _C08_WS, _tm.W("the", "a", "an", "another"), _C08_WS, _C08_LEVEL_WORDS))


def _explicit_level_in(question: str, schemes: "list[str] | None" = None) -> "str | None":
    """The admin level the question names outright, or None. Finest-first so a
    question naming two levels ("village in X district") reports the one being
    asked about rather than the containing area."""
    q = question or ""
    if schemes and ("MGNREGA" in schemes or _village_scheme(schemes)):
        q = _NEGATED_LEVEL_MATCH.sub(" ", q)
    # Only strip the chip's scope tail when the question ALSO carries a chip's
    # level phrase (", the village, not another area type"). A user-typed
    # question can end in the same ", <NAME> block, <DISTRICT>" shape —
    # "... , BATABARI block, WEST GARO HILLS" — and stripping that deleted the
    # word "block" the user had explicitly written, so the level read as
    # unstated and a same-named VILLAGE won instead (reported 2026-09-18: the
    # BATABARI block question resolved to village 272854, 1 row, against 55 in
    # the block).
    if _CHIP_LEVEL_PHRASE_MATCH.search(q):
        q = _CHIP_SCOPE_SUFFIX_MATCH.sub("", q)
    # A BREAKDOWN phrase names the grouping, not the place being asked about:
    # "in each village of Betasing block" asks for a per-village split OF THE
    # BLOCK. Reading "village" as the stated level there made the block branch
    # prefer a village reading and resolve a same-named village instead, so the
    # query filtered one village while grouping by village — 0 rows against a
    # real 6 (reported 2026-09-18). Drop the grouping words before detecting.
    q = _BREAKDOWN_LEVEL_PHRASE_MATCH.sub(" ", q)
    for dim in ("village", "assembly_constituency", "block", "district"):
        if _EXPLICIT_LEVEL_MATCH[dim].search(q):
            return dim
    return None

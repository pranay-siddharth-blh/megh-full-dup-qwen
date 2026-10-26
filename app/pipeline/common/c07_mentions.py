# app/pipeline/common/c07_mentions.py — scheme classification, entity mentions, village chips, level collisions.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.

# Words only through app/text_match (D-047): word matchers are Matchers, and
# punctuation-sensitive scans are the character helpers shared with
# app.entity_resolver (_CharScan, _GapIs, _ci_find, _bounded_find, ...).
from app import text_match as _tm
from app.entity_resolver import (  # noqa: E402
    _ASCII_ALNUM, _ASCII_LETTERS, _CharScan, _GapIs, _bounded_find, _bounded_spans, _ci_find,
    _ci_replace, _gap_ws, _paren_roman_upper, _ws1, _ws_run_end,
)


def _c07_is_word(ch: str) -> bool:
    """A word character: a letter, a digit or "_"."""
    return ch.isalnum() or ch == "_"


def _named_schemes(question: str) -> list[str]:
    """Schemes named outright in the question text, in catalog order. Falls
    back to fuzzy matching (_fuzzy_named_schemes) when the exact match finds
    nothing — otherwise a misspelled scheme name ("manrega", "pamay") reads as
    "no scheme named" and forces an unnecessary clarification prompt instead
    of being understood."""
    exact = [s for s, pattern in _SCHEME_NAME_MATCHER.items() if pattern.search(question)]
    if exact:
        return exact
    return _fuzzy_named_schemes(question)


def _shortcut_scheme(question: str) -> list[str] | None:
    """Skip the classifier call when the text already pins the scheme set —
    faster and more reliable than the model for the common case, and one fewer
    model call per query at scale. Deterministic whenever:
      * two or more schemes are named  -> use exactly those (the user listed
        them; "compare MGNREGA and PMAY" needs no classification), or
      * an explicit cross-scheme phrase ("both schemes", "across schemes")
        is present  -> the whole catalog, or
      * exactly one scheme is named    -> that one, or
      * no scheme is named but the vocabulary pins exactly one (same check
        _needs_scheme_clarification uses to skip its own pause) -> that one.
    Without this last case, a vocabulary-only question ("sanctioned amount",
    "person-days") skipped the "which scheme?" pause (correctly inferring
    MGNREGA/PMAY-G) but then still went to the LLM classifier here, which
    doesn't apply the same vocabulary rule and can return every scheme "to be
    safe" — inconsistent with the pause having just been skipped, and it broke
    the PMAY-G year-gate exemption (which only applies when the scheme set is
    exactly ["PMAY-G"]).
    Returns None only when nothing in the text pins it, so the classifier still
    handles the genuinely unnamed/ambiguous case."""
    named = _named_schemes(question)
    if len(named) >= 2:
        return named
    # CM Elevate Legacy's 13 sub-units are themselves called "schemes"
    # (Piggery, Poultry, ...), so "CM Elevate Legacy records by scheme" /
    # "scheme-wise" asks for ITS scheme_name breakdown — not every scheme in
    # the catalog. Read as cross-scheme, it pulled in all six schemes and the
    # year pause offered their union (FY 2017-18..2025-26) for a scheme that
    # holds only FY 2024-25 and 2025-26.
    # CM Elevate (applications) is the same: its programmes are "schemes" too
    # ("Meghalaya Piggery Development Scheme", …), so "among CM Elevate schemes
    # … each scheme's applications" asks for its own scheme_name breakdown. Read
    # as cross-scheme it was split into one query per scheme (KI-011) and the
    # Legacy dataset's rows were merged in (NL->SQL accuracy set, 2026-10-16).
    if named in (["CM Elevate Legacy"], ["CM Elevate"]):
        return named
    # The same holds when no scheme is named but the vocabulary pins one of the
    # two CM Elevate datasets: "How many sanctioned applications are there for
    # each scheme?" asks for CM Elevate Legacy's own scheme breakdown. Read as
    # cross-scheme it ran one SQL over all six schemes, which failed, and fell
    # back to "the reference material does not contain…" (TC-19, 2026-10-06).
    if not named and _EXPLICIT_BOTH.search(question):
        _vocab = _infer_scheme_from_terms(question)
        if _vocab in (["CM Elevate"], ["CM Elevate Legacy"]):
            return _vocab
    if _EXPLICIT_BOTH.search(question):
        return list(SCHEME_CATALOG)
    if named:
        return named
    return _infer_scheme_from_terms(question)


async def classify_scheme(question: str) -> list[str]:
    """Which scheme(s) — MGNREGA, PMAY-G, or both — does this question touch?"""
    shortcut = _shortcut_scheme(question)
    if shortcut:
        logger.info("classify_scheme: shortcut matched %s, skipping model call", shortcut)
        return shortcut

    catalog = "\n".join(f'  - "{name}": {desc}' for name, desc in SCHEME_CATALOG.items())
    scheme_options = " | ".join(f'"{name}"' for name in SCHEME_CATALOG)
    prompt = f"""Classify which scheme(s) this question needs. Available schemes:
{catalog}

Return ONLY JSON: {{"schemes": [{scheme_options}, ...]}}
Use several if the question compares or combines schemes. If it names none specifically
and gives no scheme-specific vocabulary, return every scheme.

Question: "{question}"
JSON:"""
    raw = await llm.call_classifier(prompt, guided={"guided_json": _SCHEMES_JSON_SCHEMA})
    payload = _extract_json(raw)
    if payload and isinstance(payload.get("schemes"), list):
        schemes = [s for s in payload["schemes"] if s in SCHEME_CATALOG]
        # Safety net: a scheme the user named outright must never be dropped by
        # the classifier. Union it back in (catalog order) so "across MGNREGA and
        # PMAY-G" can't come back PMAY-only.
        for s in _named_schemes(question):
            if s not in schemes:
                schemes.append(s)
        if schemes:
            return [s for s in SCHEME_CATALOG if s in schemes]
    # Deterministic fallback if the model call fails or returns unusable JSON.
    logger.warning("classify_scheme: unusable response %r — defaulting to both schemes", raw[:200])
    return list(SCHEME_CATALOG)


# Bare dimension nouns and the state name are NOT place mentions — "which
# villages have activity in Meghalaya" names no specific village or district.
# The classifier sometimes extracts them anyway; drop them before resolution,
# or `resolve_village("villages")` fuzzy-matches "Model Village" etc. and raises
# a nonsense clarification.
_GENERIC_PLACE_TERMS = {
    "village", "villages", "vill", "hamlet", "hamlets", "gaon",
    "district", "districts", "dist", "distt",
    "block", "blocks", "dev block", "development block", "cd block", "c.d. block",
    "panchayat", "panchayats", "gram panchayat", "gp", "gps", "vec",
    "state", "meghalaya", "region", "regions", "area", "areas",
    "place", "places", "location", "locations", "zone", "zones",
    "year", "years", "fy", "financial year", "all", "every", "each", "any",
}


# Real Meghalaya village names carry a parenthesised suffix that is part of the
# name: "NONGCHRAM (I)", "NONGCHRAM (II)", "Existing site(Old House)". Stripping
# trailing punctuation blindly removed the CLOSING paren while leaving the
# opening one, so "NONGCHRAM (I)" became "NONGCHRAM (I" — which matches no
# stored name exactly, stays permanently ambiguous, and makes the
# village-disambiguation chip regenerate the identical question forever
# (reported 2026-09-17: the pause repeated on every click). Strip only what is
# genuinely punctuation around the name, and keep a closing bracket whenever it
# balances an opening one still inside the value.
_MENTION_EDGE_CHARS = "\"'`.,?!;: \t"


def _drop_place_phrase(question: str, name: str) -> str:
    """Remove "in <name>" from `question`, taking any part-marker suffix with
    it. Stripping the bare name left an orphan fragment behind — dropping
    "NONGSPUNG" from "... in NONGSPUNG - A, UMLING block, RI BHOI" produced
    "... to be released - A, UMLING block, RI BHOI", which then read as a
    brand-new question and sent the next few turns badly wrong (reported
    2026-09-17). Also tidies a doubled comma left by the removal."""
    out = question or ""
    sp = _c07_place_phrase_span(out, name, _C07_DROP_PREPS)
    if sp:
        out = out[:sp[0]] + out[sp[1]:]
    out = _c07_double_comma(out)
    return _c07_squeeze_ws(out).strip().lstrip(",").strip()


_C07_DROP_PREPS = ("in", "for", "of", "at", "from", "within")


def _c07_place_phrase_span(text: str, name: str, preps: tuple,
                           tail: bool = True, word_end: bool = False) -> "tuple[int, int] | None":
    r"""Leftmost span of spaces, a whole-word preposition from `preps`, spaces, then
    `name` (case-insensitive) plus, when `tail`, an optional part-marker (see
    _c07_marker_tail); `word_end` makes the name end where a word ends."""
    best = None
    n = len(text)
    pos = 0
    while pos <= n:
        p = _ci_find(text, name, pos)
        if p < 0:
            break
        pos = p + 1
        e = p + len(name)
        if word_end and (e > 0 and _c07_is_word(text[e - 1])) == (e < n and _c07_is_word(text[e])):
            continue
        k = p
        while k > 0 and text[k - 1].isspace():
            k -= 1
        if k == p:
            continue                    # spaces needed between the preposition and the name
        head = text[:k].lower()
        for prep in preps:
            ps = k - len(prep)
            if ps >= 0 and head.endswith(prep) and (ps == 0 or not _c07_is_word(text[ps - 1])):
                s0 = ps
                while s0 > 0 and text[s0 - 1].isspace():
                    s0 -= 1
                if best is None or s0 < best[0]:
                    best = (s0, _c07_marker_tail(text, e) if tail else e)
                break
    return best


def _c07_marker_tail(text: str, e: int) -> int:
    r"""End of an optional "(...)" of at most 20 characters, or "-" and 1-12 letters/digits, at e."""
    n = len(text)
    j = _ws_run_end(text, e)
    if j < n and text[j] == "(":
        k = text.find(")", j + 1)
        if k != -1 and k - (j + 1) <= 20:
            return k + 1
    if j < n and text[j] == "-":
        j2 = _ws_run_end(text, j + 1)
        m = j2
        while m < n and m - j2 < 12 and text[m] in _ASCII_ALNUM:
            m += 1
        if m > j2:
            return m
    return e


def _c07_double_comma(text: str) -> str:
    r"""Two commas with only spaces around/between them become one ","."""
    out, i, n = [], 0, len(text)
    while i < n:
        j = _ws_run_end(text, i)
        if j < n and text[j] == ",":
            k = _ws_run_end(text, j + 1)
            if k < n and text[k] == ",":
                out.append(",")
                i = k + 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _c07_squeeze_ws(text: str) -> str:
    r"""A run of two or more whitespace characters
    becomes one space; a lone whitespace character is kept as it is."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i].isspace():
            j = _ws_run_end(text, i)
            out.append(" " if j - i >= 2 else text[i])
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _place_title(value: str) -> str:
    """Title-case a place name without mangling a roman-numeral or acronym
    suffix: str.title() turns "NONGCHRAM (II)" into "Nongchram (Ii)". Any
    parenthesised run of roman numerals / digits is preserved as-is."""
    out = _paren_roman_upper(str(value or "").title())
    # A standalone numeral word too: "NANDICHAR II" -> "Nandichar II", not "Ii"
    # (Focus Plus all-villages run 2026-09-27). A whole run of ASCII letters
    # (case-sensitive) that is one of these title-cased numerals.
    res, i, n = [], 0, len(out)
    while i < n:
        if out[i] in _ASCII_LETTERS:
            j = i
            while j < n and out[j] in _ASCII_LETTERS:
                j += 1
            run = out[i:j]
            res.append(run.upper() if run in _C07_TITLED_NUMERALS else run)
            i = j
        else:
            res.append(out[i])
            i += 1
    return "".join(res)


_C07_TITLED_NUMERALS = frozenset(("Ii", "Iii", "Iv", "Vi", "Vii", "Viii", "Ix", "Xi", "Xii"))


def _strip_mention_punctuation(value: str) -> str:
    v = (value or "").strip()
    # Leading: brackets are never part of a name at the start.
    v = v.lstrip(_MENTION_EDGE_CHARS + "([{")
    # Trailing: drop plain punctuation always, but a bracket only when it is
    # unbalanced (i.e. nothing opened it earlier in the value).
    while v:
        last = v[-1]
        if last in _MENTION_EDGE_CHARS:
            v = v[:-1]
            continue
        if last in ")]}":
            opener = {")": "(", "]": "[", "}": "{"}[last]
            if v.count(opener) >= v.count(last):
                break            # balanced — "(I)" belongs to the name
            v = v[:-1]
            continue
        break
    return v.strip()


def _clean_mention(value: str) -> str | None:
    """Normalise a raw mention; return None if it's a bare dimension word / the
    state name (i.e. not an actual place or period)."""
    v = _strip_mention_punctuation(value)
    core = v
    for _art in ("the", "a", "an", "this", "that", "each", "every", "all"):   # leading article + space
        if v[:len(_art)].lower() == _art and len(v) > len(_art) and v[len(_art)].isspace():
            core = v[len(_art):]
            break
    core = core.strip()
    if not core or core.lower() in _GENERIC_PLACE_TERMS:
        return None
    # A scheme name is never a place — "... for Focus Plus" reads like a place
    # after a preposition (the extractor prompt deliberately teaches it to
    # follow "of"/"for"/"under" onto place names), so the model occasionally
    # tags the scheme itself as the district/block/village. Reject it here as
    # a deterministic backstop regardless of what the LLM returned, or it goes
    # on to fail district/block/village resolution and gets reported as a
    # place "not in Meghalaya" (reported 2026-09-10: "which district received
    # highest total disbursement for Focus Plus" -> mentions.district ==
    # "Focus Plus" -> OutOfScope).
    if any(word_matcher.search(core) for word_matcher in _SCHEME_NAME_MATCHER.values()):
        return None
    return v


def _mention_in_question(value: str, question: str) -> bool:
    """True when `value` actually occurs in `question`, case-insensitively and
    tolerant of whitespace differences. The extractor prompt requires every
    span to be copied verbatim from the question text, so a value that fails
    this check isn't a real span — it's a hallucination, not an extraction.
    Guards against the classifier echoing one of its own few-shot examples
    (reported 2026-09-11: "Top 5 CM Elevate schemes by applications" — no
    year mentioned anywhere in the text — came back with {"year": "2017-18"},
    lifted straight from the FY 2017-18 example in the prompt. For a
    zero-time-dimension scheme like CM Elevate that phantom year immediately
    tripped the "no date field" refusal, and because "2017-18" isn't literally
    in the question, the refusal's own year-stripping step had nothing to
    strip — the follow-up chip resent the identical question text and looped
    forever)."""
    norm = lambda s: _tm.collapse_ws(s).lower()
    return norm(value) in norm(question)


def _drop_producer_group_names(question: str, mentions: dict) -> dict:
    """Remove geography mentions that the question introduced as a PRODUCER
    GROUP name. The name still reaches SQL generation in the question text,
    where the pg_name ILIKE rule handles it; what must not happen is a
    block/village disambiguation about a group the user named.

    Narrow by construction: only a name the question itself labelled with group
    phrasing is stripped, so "disbursement in Nongstoin" still resolves as
    geography."""
    m = _PG_NAMED_ENTITY.search(question or "")
    if not m:
        return mentions
    named = m.group("name").strip()
    core = _PG_SUFFIX.sub("", named).strip().lower()
    if not core:
        return mentions

    out = dict(mentions)
    for dim in ("district", "block", "village"):
        val = str(out.get(dim) or "").strip().lower()
        if val and (val == core or val in core or core in val):
            out.pop(dim, None)
            logger.info("dropped %s mention %r — the question names it as a producer group",
                        dim, mentions.get(dim))
    for dim in ("districts", "blocks"):
        vals = out.get(dim)
        if isinstance(vals, list):
            kept = [v for v in vals
                    if str(v).strip().lower() not in (core,)
                    and core not in str(v).strip().lower()]
            if len(kept) != len(vals):
                logger.info("dropped %s entries naming the producer group %r", dim, named)
            if kept:
                out[dim] = kept
            else:
                out.pop(dim, None)
    return out


# An unmistakable financial-year range: "2024-25", "FY 2024-25", "2024-2025".
# Never the head of a calendar date: "sanctioned on 2017-11-28" read "2017-11"
# as FY 2017-18, and the composer then scoped a single-day count to that FY
# (2026-09-27 screenshot). A third -NN / /NN part after it is rejected.
# A 19xx/20xx/21xx year, "-" or "/", then 2 or 4 digits, as whole words.
_C07_DASH_GAP = _GapIs(lambda g: g.strip() in ("-", "/"))
_EXPLICIT_FY_RANGE_MATCH = _tm.Matcher(_tm.NotBefore(
    _tm.Cap(_tm.Seq(
        _tm.Pred(lambda w: len(w) == 4 and w.isdecimal() and w[:2] in ("19", "20", "21")),
        _C07_DASH_GAP,
        _tm.Pred(lambda w: len(w) in (2, 4) and w.isdecimal()))),
    _tm.Seq(_C07_DASH_GAP, _tm.Pred(lambda w: w[:1].isdecimal()))))


def _backfill_explicit_year(question: str, schemes: list[str], mentions: dict) -> dict:
    """Fill the year slot from the text when the LLM extractor dropped it.

    The extractor sometimes returns no "year" for a question that plainly names
    one (TC-23, 2026-09-25: "What was the total amount remitted in FY 2024-25
    for Focus Legacy" -> {}). With no year_key resolved, the scope gate then
    asked "which area and time period?" and its "all years" chip made the SQL
    drop the FY — ₹51.01 Cr (every year) reported as FY 2024-25's ₹11.50 Cr.

    Deliberately narrow: only an explicit NNNN-NN range, only when exactly one
    distinct one is named, and only when the scheme holds that year (an absent
    year is the year-gap guard's business, already settled before this runs)."""
    if mentions.get("year"):
        return mentions
    toks = {yk for m in _EXPLICIT_FY_RANGE_MATCH.finditer(question or "")
            if (yk := _parse_year_key(m.group(1))) is not None}
    # Short forms too ("FY 25", "FY'25", "FY 23-24", "in 23-24"): a follow-up "give
    # me FY 25" lost its year to the extractor and kept the previous turn's
    # (2026-10-26). _c06_short_fy_tokens + _parse_year_key: FY 25 = FY 2024-25.
    toks |= {yk for _s, tok in _c06_short_fy_tokens(question or "")
             if (yk := _parse_year_key(tok)) is not None}
    if len(toks) != 1:
        return mentions
    yk = next(iter(toks))
    if not _year_in_data_range(yk, schemes):
        return mentions
    fy = f"{yk}-{(yk + 1) % 100:02d}"
    logger.info("year mention back-filled from the question text: FY %s", fy)
    return {**mentions, "year": fy}


_C07_LEVEL_WORDS = {"district": "district", "block": "block",
                    "assembly_constituency": "assembly constituency", "village": "village"}


def _c07_places_hint(question: str) -> str:
    """The places a database lookup found in the question, for the extractor
    (PLACE_GAZETTEER, D-059). The prompt alone told the model to tag "an
    ambiguous bare name as block" and said nothing of villages, so a bare
    village reached the village resolver only through fallbacks (user report
    2026-10-21, "How many job cards in Mawphlang?"). The level is the
    database's; which reading is meant stays with the resolver's level gate.
    "" with the flag off, the index not loaded, or nothing found."""
    from app import entity_resolver
    if not settings.PLACE_GAZETTEER or not entity_resolver.village_index_loaded():
        return ""
    try:
        found = entity_resolver.match_places(question, is_ordinary=_is_known_word)
    except Exception:  # noqa: BLE001 — a hint, never a reason to fail the turn
        logger.exception("match_places failed")
        return ""
    # The prompt's own rule: "assembly_constituency" ONLY when the question
    # signals a constituency. Listing it (first, alphabetically) for every
    # block-and-constituency name made the 4B tag Nongpoh / Jowai / Umroi as
    # constituencies, and the "whole constituency or part?" pause followed
    # (place hierarchy sweep 2026-10-21, KI-349).
    _signals_ac = bool({"CONSTITUENCY", "CONSTITUENCIES", "AC", "ASSEMBLY", "MLA"}
                       & set("".join(c if c.isalnum() else " " for c in question.upper()).split()))
    lines = []
    for f in found:
        # Coarse to fine, as the level gate orders them: "block or district"
        # made the 4B tag Tura (West Garo Hills HQ) a block, which only CM
        # Elevate's urban-body catalogue holds (KI-349).
        _lv = [lv for lv in ("district", "block", "assembly_constituency", "village") if lv in f["levels"]]
        if not _signals_ac and len(_lv) > 1:
            _lv = [lv for lv in _lv if lv != "assembly_constituency"]
        levels = " or ".join(_C07_LEVEL_WORDS[lv] for lv in _lv)
        if f.get("fuzzy"):
            levels += f" (a misspelling of the village {f['name'].title()})"
        lines.append(f'- "{f["typed"].lower()}": {levels}')
    if not lines:
        return ""
    return ("Places a database lookup found in this question (the level is the database's):\n"
            + "\n".join(lines) + "\n"
            "Extract these names verbatim as the user typed them, and do not invent any other place "
            "name. A name the lookup lists ONLY as a village goes in \"village\", with or without the "
            "word \"village\". A name the lookup does NOT list as a village is never a \"village\".\n\n")


async def extract_entity_mentions(question: str) -> dict:
    """Which spans of the question name a district, block, village, year or
    assembly constituency? Span-finding only — resolving each span to a
    canonical DB value is a separate, deterministic step (entity_resolver),
    not this LLM call."""
    prompt = f"""Extract place/time names from this question, verbatim as the user typed
them. Do not correct spelling or guess the canonical form.

Return ONLY JSON with keys from: "district", "block", "village", "year",
"assembly_constituency", "blocks", "districts". Include a key ONLY when the
question NAMES a specific one. A bare word like "village", "villages",
"district", "block", "year", or the state name "Meghalaya" is NOT a name —
omit it. If the question names none, return {{}}.

When the question names TWO OR MORE blocks to compare against each other
("compare X and Y", "X vs Y", "X and Y, the block, not the village"), put ALL
of their names in the plural "blocks" array — do NOT use the singular "block"
key and keep only one, that silently drops the other block from the answer.
Use "block" only when exactly one block is named. The same rule applies to
districts: TWO OR MORE named to compare against each other go in the plural
"districts" array, never the singular "district" key — even when one of them
is a short acronym like "EKH" or "WGH". Use "district" only when exactly one
district is named.

Block, assembly-constituency and village names overlap heavily in Meghalaya —
a bare name (e.g. "Mawlai") could be any of the three. Use "assembly_constituency"
ONLY when the question itself signals a constituency: it says "constituency",
"AC", "assembly", "MLA", or gives a number before the name (e.g. "15 Mawlai",
"AC 9"). Otherwise tag an ambiguous bare name as "block".

A place name can follow ANY preposition, not just "in"/"for" — "disbursement
OF Selsella", "expenditure OF West Garo Hills", "spending OF Abagre" all name
Selsella/West Garo Hills/Abagre as the AREA the figure is about, exactly like
"disbursement in Selsella" would. Do not read "of" as meaning the metric noun
(disbursement, expenditure, spending, amount, total) is itself the thing being
named — the name after "of" is still a place, and must still be extracted.

A SCHEME name (MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy, or a
close variant) is NEVER a place — do not extract it as a district/block/village
even when it follows "for"/"of"/"under" exactly like a place would
("disbursement for Focus Plus" names the scheme, not an area; extract nothing).

A PRODUCER GROUP name or id is NEVER a place either. A Focus Legacy pg_id looks
like "PG-FOCUS-WGH-7089" and contains a district abbreviation — do NOT extract
that abbreviation, or any part of the id, as a district. A producer group NAME
("Muskan Producer Group", "Bak 15 Banana", "Iainehlang Pg") often reads like a
village name; it is a group, not an area, so extract nothing from it.

Likewise, a CM Elevate SUB-SCHEME name is NEVER a place, even though several
of them sound like plausible village/block names in isolation: Piggery,
Poultry, Dairy, Goat (Farming), Warehouse, Sericulture (& Weaving), Green
Taxi, Motorcaravan, Cinema Theatre, Sports & Wellness (Centre), Any Business
Venture, Agro Tourism Villa, PRIME Tourism Vehicle, PRIME Agriculture
Response Vehicle, PRIME Small Enterprise Empowerment / SEED. "What is the
status distribution for Piggery?" names a sub-scheme, not a district, block
or village — extract nothing.

Examples:
Question: "Tell me about total disbursement of Selsella across all financial years for MGNREGA."
JSON: {{"block": "Selsella"}}
Question: "What is the total expenditure of West Garo Hills under PMAY-G?"
JSON: {{"district": "West Garo Hills"}}
Question: "how many job cards issued in Ri Bhoi"
JSON: {{"district": "Ri Bhoi"}}
Question: "What is the status distribution for Piggery?"
JSON: {{}}
Question: "How many applicants under Poultry are on hold?"
JSON: {{}}
Question: "show me MGNREGA spend"
JSON: {{}}
Question: "Compare the sanctioned amounts of Dambo Rongjeng and Samanda, the block, not the village"
JSON: {{"blocks": ["Dambo Rongjeng", "Samanda"]}}
Question: "Compare PMAY performance between ekh and wgh for FY 2017-18"
JSON: {{"districts": ["ekh", "wgh"], "year": "2017-18"}}
Question: "which district received highest total disbursement for Focus Plus"
JSON: {{}}

{_c07_places_hint(question)}Question: "{question}"
JSON:"""
    raw = await llm.call_classifier(prompt, guided={"guided_json": _ENTITY_JSON_SCHEMA})
    payload = _extract_json(raw)
    if not isinstance(payload, dict):
        return {}
    out: dict[str, object] = {}
    for k, v in payload.items():
        if k in ("district", "block", "village", "year", "assembly_constituency") \
                and isinstance(v, str) and v.strip():
            cleaned = _clean_mention(v)
            if cleaned and _mention_in_question(cleaned, question):
                out[k] = cleaned
    blocks_raw = payload.get("blocks")
    if isinstance(blocks_raw, list):
        cleaned_blocks: list[str] = []
        seen: set[str] = set()
        for v in blocks_raw:
            if not isinstance(v, str):
                continue
            c = _clean_mention(v)
            if c and _mention_in_question(c, question) and c.lower() not in seen:
                seen.add(c.lower())
                cleaned_blocks.append(c)
        if len(cleaned_blocks) >= 2:
            out["blocks"] = cleaned_blocks
        elif len(cleaned_blocks) == 1 and "block" not in out:
            # A single-element array is just a singular mention the model
            # phrased as a list — fold it back so the existing singular path
            # (block-vs-village disambiguation etc.) still runs for it.
            out["block"] = cleaned_blocks[0]
    districts_raw = payload.get("districts")
    if isinstance(districts_raw, list):
        cleaned_districts: list[str] = []
        seen_d: set[str] = set()
        for v in districts_raw:
            if not isinstance(v, str):
                continue
            c = _clean_mention(v)
            if c and _mention_in_question(c, question) and c.lower() not in seen_d:
                seen_d.add(c.lower())
                cleaned_districts.append(c)
        if len(cleaned_districts) >= 2:
            out["districts"] = cleaned_districts
        elif len(cleaned_districts) == 1 and "district" not in out:
            # A single-element array is just a singular mention the model
            # phrased as a list — fold it back so the existing singular path
            # runs for it.
            out["district"] = cleaned_districts[0]
    return out


def _parse_year_key(text: str) -> "int | None":
    """FY start year as an int from '2023', '2023-24', '2023-2024', 'FY 2023-24',
    'FY23', or a bare two-digit range like '25-26' with no century at all —
    users type financial years this way constantly (2026-09-10 UAT: "25-26" was
    not understood as a year), and without this branch the mention never
    resolves to a year_key at all. Returns None if no plausible year
    (2010-2039) is present."""
    text = text or ""
    toks = _tm.tokens(text)

    def _fy_start(w: str) -> bool:                                   # 2010-2039
        return len(w) == 4 and w.isdecimal() and w[:2] == "20" and w[2] in "123"

    for k, t in enumerate(toks[:-1]):                                # 2023-24 / 2023-2024
        nxt = toks[k + 1].raw
        if _fy_start(t.raw) and text[t.end:toks[k + 1].start].strip() in ("-", "/") \
                and nxt.isdecimal() and (len(nxt) == 2 or (len(nxt) == 4 and nxt[:2] == "20")):
            return int(t.raw)
    def _fy_short(yy: int, end: int) -> int:
        # "FY24" names the year that ENDS in March 2024, i.e. FY 2023-24 — the Indian
        # convention, and the one every SME catalogue uses ("FY23" = 2022-23 in
        # focusplus_entity_resolver.yaml, "FY25" = 2024-25 for CM Elevate Legacy).
        # It was read as 2000 + 24 = FY 2024-25 (RAG plan C1, audit 2026-10-23).
        # "FY 23-24" is a range: its first year is the start year, as before.
        j = _ws_run_end(text, end)
        if j < len(text) and text[j] in "-/":
            j = _ws_run_end(text, j + 1)
            if text[j:j + 2].isdecimal() and len(text[j:j + 2]) == 2 \
                    and (j + 2 == len(text) or not text[j + 2].isdecimal()) \
                    and int(text[j:j + 2]) == (yy + 1) % 100:
                return 2000 + yy
        return 2000 + yy - 1

    for k, t in enumerate(toks):                                     # FY23 / FY 23 / FY'23
        if t.low == "fy" and k + 1 < len(toks):
            g = text[t.end:toks[k + 1].start].lstrip()
            nxt = toks[k + 1].raw
            if g in ("", "'") and len(nxt) == 2 and nxt.isdecimal():
                return _fy_short(int(nxt), toks[k + 1].end)
        elif t.low.startswith("fy") and len(t.raw) == 4 and t.raw[2:].isdecimal():
            return _fy_short(int(t.raw[2:]), t.end)
    n = len(text)
    for i in range(n - 1):                                           # bare 25-26
        if text[i].isdecimal() and text[i + 1].isdecimal() and (i == 0 or not text[i - 1].isdecimal()):
            j = _ws_run_end(text, i + 2)
            if j < n and text[j] in "-/":
                j = _ws_run_end(text, j + 1)
                if j + 1 < n and text[j].isdecimal() and text[j + 1].isdecimal() \
                        and (j + 2 == n or not text[j + 2].isdecimal()):
                    y1, y2 = int(text[i:i + 2]), int(text[j:j + 2])
                    if 10 <= y1 <= 39 and y2 == (y1 + 1) % 100:
                        return 2000 + y1
                    break                       # only the first such pair counts
    for t in toks:                                                   # bare 2023
        if _fy_start(t.raw):
            return int(t.raw)
    return None


def _village_chip_question(question: str, raw_text: str, candidate: dict,
                           schemes: "list[str] | None" = None,
                           peers: "list[dict] | None" = None) -> str:
    """The follow-up question text for one village-disambiguation chip.

    The old approach appended "<block> block, <district>" to the ORIGINAL
    ambiguous fragment (e.g. "siju") and left the fragment itself unchanged.
    That only narrows resolve_village's search scope — it does not say WHICH
    candidate was picked. Two candidates that both fuzzy-match the same raw
    text and also sit in the same block (e.g. "siju" fuzzy-matches both SIJU
    SONGMONG and Siju Arteka, both in SIJU block, SOUTH GARO HILLS) stay tied
    even after the block/district is appended, so every chip regenerates the
    IDENTICAL question and the clarification loops forever — reported
    2026-09-09 for both an exact-duplicate dim_geography row (Asimgre, DALU
    block) and this fuzzy-match case (siju). Substituting the candidate's own
    canonical name into the question fixes it: re-resolution then runs an
    EXACT match on a name that is (almost always, and after the duplicate-row
    fix in entity_resolver.resolve_village, effectively always) unique.

    A second, compounding bug (also reported 2026-09-09, "nongthymmai" in
    EAST/WEST KHASI HILLS): when the LLM mention-extractor can't cleanly split
    a resumed chip's OWN text ("Nongthymmai, RI MULIANG block, WEST KHASI
    HILLS") into village/block, resolve_entities lands back on this same
    ambiguous-village branch and calls this function AGAIN — with `question`
    now already carrying the previous round's appended ", <block> block,
    <district>". Blindly appending another one lets the suffix grow every
    round ("..., RI MULIANG block, WEST KHASI HILLS, MAWSHYNRUT block, WEST
    KHASI HILLS, ...", naming more and more blocks at once), which defeats any
    single-candidate text match downstream and loops forever. Strip a
    previously-appended suffix (there is at most one meaningful one — this
    function is the only writer of that shape) before appending the current
    candidate's, so the text never grows past one such suffix."""
    q = _village_chip_question_text(question, raw_text, candidate, schemes)
    tag = _village_code_tag(candidate, peers, schemes)
    tail = f", {candidate['block']} block, {candidate['district']}"
    if tag and q.endswith(tail):
        head = q[:-len(tail)]
        sp = _bounded_find(head, str(candidate['name']), ci=True)
        head = head[:sp[1]] + tag + head[sp[1]:] if sp else head + tag
        q = f"{head}{tail}"
    return q


# Two DIFFERENT villages can share a name AND a block: BOLDAMGRE 272895 and
# 272933 both sit in SELSELLA block, APALGRE 273033 and 273103 in RERAPARA. Their
# chips read identically ("BOLDAMGRE — SELSELLA block, WEST GARO HILLS"), so
# neither the officer nor the chip pin could tell them apart and the second
# village was unreachable (Focus Plus all-villages run 2026-09-27). The LGD code
# is added to the label and the chip question only when such a twin exists.
def _c07_lgd_code_at(text: str, i: int):
    r""""(LGD <digits>)" (case-sensitive), as a _CharScan step."""
    if not text.startswith("(LGD ", i):
        return None
    j = k = i + 5
    while k < len(text) and text[k].isdecimal():
        k += 1
    if k > j and k < len(text) and text[k] == ")":
        return k + 1, [(j, k)]
    return None


_CHIP_LGD_CODE_MATCH = _CharScan(_c07_lgd_code_at)


def _village_code_tag(candidate: dict, peers: "list[dict] | None", schemes: "list[str] | None") -> str:
    # Focus Legacy too: UMSAW and DEWSAW each exist twice in ONE block, and the
    # untagged chips pinned the wrong twin (all-villages run 2026-09-29, KI-163).
    if not peers or not (_village_scheme(schemes) or schemes == ["Focus Legacy"]):
        return ""
    key = lambda c: (str(c.get("name", "")).strip().upper(), str(c.get("block") or "").upper(),  # noqa: E731
                     str(c.get("district") or "").upper())
    twin = any(key(p) == key(candidate) and p.get("village_code") != candidate.get("village_code")
               for p in peers)
    return f" (LGD {candidate['village_code']})" if twin else ""


def _village_chip_label(candidate: dict, peers: "list[dict] | None" = None,
                        schemes: "list[str] | None" = None) -> str:
    return (f"{candidate['name']}{_village_code_tag(candidate, peers, schemes)} — "
            f"{candidate['block']} block, {candidate['district']}")


def _loose_name_find(name: str, text: str) -> "tuple[int, int] | None":
    r"""Where a place name first occurs in `text`, ignoring the spacing around
    brackets and hyphens and collapsing runs of spaces ("DATHBANGA ( KOCH )"
    also finds "Dathbanga (Koch)"), case-insensitive, not inside a longer
    run of letters/digits. (Each space in the name may be any whitespace or
    none; each bracket/hyphen may have whitespace on either side.)"""
    elems: list = []              # None = optional whitespace run, else one lower-cased char
    for ch in _ws1(str(name).strip()):
        if ch in "()-":
            parts = [None, ch, None]
        elif ch == " ":
            parts = [None]
        else:
            parts = [ch.lower()]
        for el in parts:
            if el is None and elems and elems[-1] is None:
                continue
            elems.append(el)
    text = text or ""
    n = len(text)

    def _ends(k: int, i: int):
        if k == len(elems):
            yield i
            return
        el = elems[k]
        if el is None:                     # longest whitespace run first, giving back on demand
            j = _ws_run_end(text, i)
            for m in range(j, i - 1, -1):
                yield from _ends(k + 1, m)
        elif i < n and text[i].lower() == el:
            yield from _ends(k + 1, i + 1)

    for start in range(n + 1):
        if start > 0 and text[start - 1] in _ASCII_ALNUM:
            continue
        for e in _ends(0, start):
            if e == n or text[e] not in _ASCII_ALNUM:
                return start, e
    return None


def _c07_strip_chip_tails(stem: str) -> str:
    r"""Drop every trailing ", <X> block, <Y>" pair (the word "block" in any
    case)."""
    parts = stem.split(",")
    keep = len(parts)
    while keep >= 3:
        a, b = parts[keep - 2], parts[keep - 1]
        head = a[:-5]
        if b and a[-5:].lower() == "block" and len(head) >= 2 and head[-1].isspace():
            keep -= 2
        else:
            break
    return stem if keep == len(parts) else ",".join(parts[:keep])


def _village_chip_question_text(question: str, raw_text: str, candidate: dict,
                                schemes: "list[str] | None" = None) -> str:
    stem = question.strip().rstrip(" ?.")
    stem = _c07_strip_chip_tails(stem).rstrip()
    stem = _CHIP_LGD_CODE_MATCH.sub("", stem).replace("  ", " ").rstrip()
    name = candidate["name"]
    # MGNREGA: the stem may already hold the candidate's FULL name when the
    # extractor truncated the mention ("LOWER NALBARI" out of "LOWER NALBARI -
    # I"). Substituting then doubled the qualifier ("LOWER NALBARI - I - I"), the
    # resumed text no longer began with the paused question, the router did not
    # treat it as a chip resume, and the village was lost (all-villages QA
    # 2026-09-26).
    if _village_scheme(schemes):
        # Bracket spacing is not part of the name: a stem holding "DATHBANGA
        # (KOCH)" for the village "DATHBANGA ( KOCH )" was not recognised, only
        # "DATHBANGA" was replaced, and the chip read "DATHBANGA ( KOCH ) (KOCH)"
        # (MGNREGA all-villages run 2026-10-09). The typed form is rewritten to
        # the exact stored name so the resumed chip resolves it exactly.
        _hit = _loose_name_find(str(name), stem)
        if _hit:
            if _ws1(stem[_hit[0]:_hit[1]]).upper() != _ws1(str(name)).upper():
                stem = stem[:_hit[0]] + str(name) + stem[_hit[1]:]   # spacing differs: exact name
            return f"{stem}, {candidate['block']} block, {candidate['district']}"
    if raw_text and _ci_find(stem, raw_text) >= 0:
        pinned = _ci_replace(stem, raw_text, name, count=1)
    else:
        pinned = f"{stem} ({name})"
    return f"{pinned}, {candidate['block']} block, {candidate['district']}"


# ── "Is that a village, a block, or a constituency?" ────────────────────────
# Block / assembly-constituency / village names overlap massively in Meghalaya
# (see entity_resolver.collides_across_dimensions and the
# cross_dimension_collisions block in mgnrega_entity_resolver.yaml). A bare
# "Sohra" is a real assembly constituency (AC 28, East Khasi Hills); it is NOT
# a block and NOT a village, but "Sohrarim" IS a village, so the old flow —
# extractor tags the bare name "block" -> no such block -> fall back to
# resolve_village -> fuzzy-match Sohrarim -> answer — reported a specific
# village's 643 beneficiaries as though the user had asked about Sohra
# (reported 2026-09-15). Every level the name could mean is now offered as a
# one-tap chip, and nothing is filtered until the user picks one.
#
# The chip question appends an explicit level word, which the resolvers and the
# mention-extractor both already key on: the extractor's own prompt uses
# "constituency"/"AC"/"assembly" to tag assembly_constituency, and the
# block/village branches below check for a literal "block"/"village" word to
# skip their own disambiguation. So a resumed chip resolves straight through
# without re-triggering this pause.
_DIM_CHIP_WORD = {
    "district": "district",
    "block": "block",
    "assembly_constituency": "assembly constituency",
    "village": "village",
}
_DIM_CHIP_LABEL = {
    "district": "district",
    "block": "C&RD block",
    "assembly_constituency": "assembly constituency",
    "village": "village",
}


def _c07_chip_where(dim: str, shown: str) -> str:
    """" (Mylliem block, East Khasi Hills)" after a level chip, so the two
    readings of one name are told apart by where they lie (PLACE_GAZETTEER,
    D-059). Only with the village index loaded; "" when the place is not
    known exactly or several same-name villages exist."""
    from app import entity_resolver
    if not settings.PLACE_GAZETTEER or not entity_resolver.village_index_loaded():
        return ""
    if dim == "village":
        places = entity_resolver.village_places(shown)
        if len(places) != 1:
            return ""
        _code, blk, dist = places[0]
        return f" ({_place_title(blk)} block, {_place_title(dist)})" if blk and dist else ""
    if dim == "block":
        dist = entity_resolver.block_parent_district(shown)
        return f" ({_place_title(dist)})" if dist else ""
    return ""


def _dimension_collision_clarification(question: str, name: str,
                                       dims: "dict[str, str]") -> "ClarificationNeeded":
    """Ask which ADMIN LEVEL a bare, level-ambiguous place name refers to.

    `dims` is {dimension: canonical display name} from
    entity_resolver.collides_across_dimensions. Each chip substitutes that
    canonical name for whatever the user typed, so a misspelling is corrected
    at the same time as the level is chosen ("malwai" -> "Mawlai"); without
    that substitution the resumed question carries the typo forward and fails
    block/constituency resolution all over again, silently landing back on the
    village. The village chip keeps the user's own text — village names are
    DB-backed and resolved by their own branch."""
    stem = question.strip().rstrip(" ?.")
    options = []
    for dim, canonical in dims.items():
        shown = canonical or name
        # Swap the typed name for the canonical one in the question itself.
        if canonical and canonical.lower() != str(name).lower():
            resumed = _ci_replace(stem, str(name), canonical, count=1)
        else:
            resumed = stem
        options.append({
            "label": f"The {shown} {_DIM_CHIP_LABEL[dim]}{_c07_chip_where(dim, shown)}",
            "question": f"{resumed}, the {_DIM_CHIP_WORD[dim]}, not another area type",
        })
    labels = list(dims)
    listed = ", ".join(_DIM_CHIP_LABEL[d] for d in labels[:-1]) + \
        f" or {_DIM_CHIP_LABEL[labels[-1]]}"
    return ClarificationNeeded(
        f"“{name}” could refer to more than one kind of area in Meghalaya — the "
        f"{listed}. These cover different places and give different numbers, so "
        "please pick the one you mean.",
        options=options,
        rule="entity-ambiguous",
    )

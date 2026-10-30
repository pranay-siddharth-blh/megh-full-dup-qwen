# app/pipeline/common/c02_rephraser.py — question rephraser and its guards; scheme / place / FY spelling correction.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.



def _expand_short_fy(text: str) -> str:
    """'23-24' -> 'FY 2023-24' (only a consecutive pair), so the year checks
    read the short form the user typed the same way the rewrite spells it."""
    def repl(m):
        a, b = int(m.group(1)), int(m.group(2))
        return f"FY 20{a:02d}-{b:02d}" if b == (a + 1) % 100 else m.group(0)
    return _SHORT_FY.sub(repl, text or "")


def _c02_letter_runs(text: str) -> "list[tuple[int, int, str]]":
    """(start, end, run) for every run of ASCII letters."""
    out, i, n = [], 0, len(text or "")
    while i < n:
        if text[i].isascii() and text[i].isalpha():
            j = i + 1
            while j < n and text[j].isascii() and text[j].isalpha():
                j += 1
            out.append((i, j, text[i:j]))
            i = j
        else:
            i += 1
    return out


def _c02_name_tokens(text: str) -> "list[str]":
    """Words of ASCII letters / ' / - (starting with a letter), and every other
    non-space character on its own ("ramjonggre ( r )" -> ramjonggre ( r ))."""
    out, i, n = [], 0, len(text or "")
    while i < n:
        c = text[i]
        if c.isascii() and c.isalpha():
            j = i + 1
            while j < n and ((text[j].isascii() and text[j].isalpha()) or text[j] in "'-"):
                j += 1
            out.append(text[i:j])
            i = j
        else:
            if not c.isspace():
                out.append(c)
            i += 1
    return out


def _c02_name_before_village(text: str) -> "str | None":
    """The name between "in / for / at / of / to" and the next "village" ("for
    kyrdemkulai 6 km village" -> "kyrdemkulai 6 km"), else None."""
    toks = _c01_tm_tokens(text)
    for k, t in enumerate(toks):
        if t.low not in ("in", "for", "at", "of", "to"):
            continue
        if t.end >= len(text) or not text[t.end].isspace():
            continue
        start = t.end
        while start < len(text) and text[start].isspace():
            start += 1
        for m in range(k + 1, len(toks)):
            v = toks[m]
            if v.low != "village" or not text[v.start - 1].isspace():
                continue
            end = len(text[:v.start].rstrip())
            if end > start:
                return text[start:end]
    return None


def _c02_is_awaas(w: str) -> bool:
    """awas, awaas, awaaas … ("aw", one or more "a", an optional "s")."""
    w = w.lower()
    if w.endswith("s"):
        w = w[:-1]
    return len(w) >= 3 and w.startswith("aw") and set(w[2:]) == {"a"}


_PLACE_WORDS_CACHE: "list[frozenset]" = []


def _place_words() -> frozenset:
    """Every word of every catalogued district / block / constituency name and
    alias ("ri", "bhoi", "mawlai", "garo", "hills"): a place the user typed is
    not an unknown word. Village names are not here; they stay names. Cached
    only once non-empty: a call before the catalogues load must not pin an
    empty set for the life of the process."""
    if _PLACE_WORDS_CACHE:
        return _PLACE_WORDS_CACHE[0]
    words = _load_place_words()
    if words:
        _PLACE_WORDS_CACHE.append(words)
    return words


def _load_place_words() -> frozenset:
    words: set[str] = set()
    try:
        from app import entity_resolver as er
        for dims in er._catalog.values():
            for dim in ("district", "block", "assembly_constituency"):
                for v in dims.get(dim) or []:
                    for form in [v.get("canonical") or "", v.get("acronym") or "", *(v.get("aliases") or [])]:
                        words |= {w.lower() for w in _c01_alpha_words(str(form)) if len(w) >= 3}
    except Exception:  # noqa: BLE001
        pass
    return frozenset(words)


@functools.lru_cache(maxsize=1)
def _c02_typo_vocab() -> frozenset:
    """_REPHRASE_VOCAB plus the measure words of the few-shot synonym table
    (annotations._FEWSHOT_SYNONYMS: "persondays", "mandays", "jobcards", …), so a
    measure typo is corrected like any other domain word. Test team report
    2026-10-29: "toatal persendays" with an MGNREGA chat open was read as a
    general question; "persondays" was in no typo vocabulary."""
    words = set(_REPHRASE_VOCAB)
    try:
        from app import annotations as _c02_ann
        for k, v in _c02_ann._FEWSHOT_SYNONYMS.items():
            words |= {x for x in (k, v) if x and x.isalpha() and len(x) >= 5}
    except Exception:  # noqa: BLE001 — no table: the fixed vocabulary alone
        pass
    return frozenset(words)


def _vocab_typo(word: str) -> "str | None":
    """The vocabulary word a typo stands for ("aplications" -> "applications")."""
    w = word.lower()
    if len(w) < 5:
        return None
    vocab = _c02_typo_vocab()
    best = max(vocab, key=lambda v: fuzz.ratio(w, v))
    if fuzz.ratio(w, best) >= 85:
        return best
    # swapped letters ("leagcy" -> "legacy") score low on ratio: same letters, same length
    letters = sorted(w)
    return next((v for v in vocab if len(v) == len(w) and sorted(v) == letters), None)


def _rephrase_gloss(question: str) -> str:
    """The original with short years expanded, Hinglish glossed and typos of
    ordinary words spelled out, for the checks (never sent to the model)."""
    text = _expand_short_fy(question)
    extra: list[str] = []
    for w in _c01_alpha_words(text):
        lw = w.lower()
        if lw in _HINGLISH_GLOSS:
            extra.append(_HINGLISH_GLOSS[lw])
        elif not _is_known_word(lw) and (t := _vocab_typo(lw)):
            extra.append(t)
    extra += [g for word_matcher, g in _HINGLISH_PHRASES if word_matcher.search(text)]
    extra = [e for e in extra if e]
    return f"{text} {' '.join(extra)}" if extra else text


def _measure_labels(text: str) -> set[str]:
    return {label for label, word_matcher, _h in _MEASURE_HOLDERS if word_matcher.search(text or "")}


# Ordinary connecting words the vocabulary lists did not hold: "during" read as
# an unknown NAME, so every rewrite of "… during 2025-26" was rejected as having
# dropped a name (MGNREGA all-villages run, 2026-10-09).
_COMMON_WORDS = frozenset(
    "during between across within among since until till per each every both either "
    "into onto upon over under above below after before about against along around".split())


def _is_known_word(word: str) -> bool:
    w = word.lower().replace("’", "'").strip("'-")
    # A contraction is ordinary English, never a name: "don't give all of
    # Meghalaya" was rephrased "Do not …" and rejected as a lost name "don't",
    # so the messy original went on and was routed to the KB (2026-10-18). A
    # possessive ("Mawlai's") is NOT a contraction and stays a name.
    _stem, _apos, _suffix = w.partition("'")
    if _apos and ((_suffix == "t" and _stem.endswith("n"))
                  or (_suffix in ("ll", "re", "ve", "m", "d") and _is_known_word(_stem))):
        return True
    if len(w) < 3 or w in _REPHRASE_VOCAB or w in _HINGLISH_GLOSS or w in _COMMON_WORDS or w in _place_words():
        return True
    if any(p.search(w) for p in _SCHEME_NAME_MATCHER.values()) or _fuzzy_named_schemes(w):
        return True
    if _measure_labels(w) or context_policy.metric_families(w):
        return True
    return bool(context_policy._places(w))


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _c01_tm_numbers(text or "")}


def _needs_rephrase(question: str) -> bool:
    """True when the message looks messy: Hinglish, an unknown word (a typo or a
    name), or no question shape ("manrega persondays ekh"). A clean English
    question skips the model call."""
    q = (question or "").strip()
    if len(q) < 3 or len(q) > settings.QUERY_REPHRASE_MAX_CHARS:
        return False
    words = _c01_alpha_words(q)
    if not words:
        return False
    if any(w.lower() in _HINGLISH_GLOSS for w in words) or any(word_matcher.search(q) for word_matcher, _ in _HINGLISH_PHRASES):
        return True
    if any(not _is_known_word(w) for w in words):
        return True
    return not _REPHRASE_START.search(q)


_REPHRASE_COUNT_NOUNS = (Matcher(W("applicant", "applicants")),
                         Matcher(W("application", "applications")),
                         Matcher(W("beneficiary", "beneficiaries")))
_REPHRASE_COMPARE_WORD = Matcher(Alt(
    W("compar", prefix=True), W("vs", "versus", "difference"),
    Seq("which", Opt("is"), W("higher", "lower", "more", "less", "greater", "bigger"), sep="space")))
_REPHRASE_SPEND_WORD = Matcher(Alt(W("expenditure", "expenditures", "expense", "expenses", "spent", "cost",
                                     "costs"), W("spend", prefix=True)))


def _word_spans(text: str) -> "list[tuple[int, int, str]]":
    """(start, end, word) for every run of letters / digits / '_' in `text`."""
    out, start = [], None
    for i, c in enumerate((text or "") + " "):
        if c.isalnum() or c == "_":
            if start is None:
                start = i
        elif start is not None:
            out.append((start, i, text[start:i]))
            start = None
    return out


def _reads_like_sql(text: str) -> bool:
    """True when a line of `text` has the word SELECT followed by the word FROM
    (a rephraser that answered with a query instead of a question)."""
    for line in (text or "").splitlines():
        words = [w.lower() for _s, _e, w in _word_spans(line)]
        if "select" in words and "from" in words[words.index("select") + 1:]:
            return True
    return False


# A breakdown the question asks for: "in each block", "block-wise", "per district",
# "by financial year", "district by district". _c02_breakdowns() returns the
# dimensions (singular, lower case) so a rewrite can be checked for dropping one.
_C02_DIM = W("district", "districts", "block", "blocks", "village", "villages", "panchayat", "panchayats",
             "gp", "gps", "year", "years", "fy", "scheme", "schemes", "programme", "programmes", "program",
             "programs", "tranche", "tranches", "batch", "batches", "month", "months", "lender", "lenders",
             "bank", "banks", "product", "products", "category", "categories", "gender", "status", "type",
             "types", "constituency", "constituencies")
_C02_DIM_WORDS = frozenset(w.rstrip("s") for w in (
    "district block village panchayat gp year fy scheme programme program tranche batch month lender "
    "bank product category categorie gender status type constituency constituencie").split())
_C02_BREAKDOWN = Matcher(Alt(
    Seq(W("each"), Opt(W("financial", "fiscal", "calendar", "individual", "single")), Cap(_C02_DIM, "dim")),
    Seq(Cap(_C02_DIM, "dim"), "wise"),
    Pred(lambda w: w.lower().endswith("wise") and w.lower()[:-4].rstrip("s") in _C02_DIM_WORDS),
    Seq(W("by", "across"), Opt("the"), Opt(W("financial", "fiscal")), Cap(_C02_DIM, "dim")),
    Seq(Cap(_C02_DIM, "dim"), "by", _C02_DIM),
))
# "per district" / "every block" are breakdowns too, but also "average per district"
# (one value) and "counting every financial year" (all years together), so they
# count for the rephrase check only, not for the SQL guard in c11.
_C02_PER_DIM = Matcher(Seq(W("per", "every"), Opt(W("financial", "fiscal", "calendar")), Cap(_C02_DIM, "dim")))


def _c02_breakdowns(text: str, include_per: bool = True) -> set[str]:
    """The dimensions `text` breaks down by. include_per=False leaves out "per
    <dim>" / "every <dim>", which may also be one value ("spend per year on
    average", "counting every financial year")."""
    out = set()
    hits = list(_C02_BREAKDOWN.finditer(text or ""))
    if include_per:
        hits += list(_C02_PER_DIM.finditer(text or ""))
    for hit in hits:
        word = (hit.group("dim") or hit.group(0)).lower()
        if word.endswith("wise"):
            word = word[:-4]
        word = word.rstrip("s") or word
        out.add({"programme": "scheme", "program": "scheme", "fy": "year", "categorie": "category",
                 "constituencie": "constituency"}.get(word, word))
    return out


def _rephrase_violation(original: str, rephrased: str) -> "str | None":
    """What the rephrased question changed that it must not, else None:
    'shape' (not a usable question), 'scheme', 'place', 'year', 'number',
    'measure', 'metric', 'category' or 'name:<word>' (a name or unknown word the
    user typed went missing). Everything is compared against the original with
    short years expanded and Hinglish glossed."""
    out = (rephrased or "").strip()
    if not (3 <= len(out) <= max(300, 3 * len(original or ""))) or any(c in out for c in "{}[]`") \
            or _reads_like_sql(out):
        return "shape"
    gloss = _rephrase_gloss(original)
    # Schemes: exactly the ones the user named (fuzzy spelling counts), no more, no fewer.
    # Fuzzy matching reads only what no exact name covers: "CM Elevate Legacy
    # leagcy" is one scheme, not also a fuzzy "elevate" -> CM Elevate.
    unnamed = gloss
    for pat in _SCHEME_NAME_MATCHER.values():
        unnamed = pat.sub(" ", unnamed)
    named = _exact_schemes(gloss) | set(_fuzzy_named_schemes(unnamed))
    if _exact_schemes(out) != named:
        return "scheme"
    # ...nor widen to every scheme: "Compare total expenditure and employment
    # generated in East Khasi Hills during 25-26" came back "…under all schemes…",
    # was classified to all six and failed (MGNREGA sheet DATA-030, 2026-10-09).
    if _EXPLICIT_BOTH.search(out) and not _EXPLICIT_BOTH.search(gloss):
        return "scheme"
    # ...nor bring in the word "scheme(s)" at all: "What was the total expenditure in
    # JIGABARI during 2025-2026?" came back "…under the available schemes…", which the
    # scheme gate read as unscoped and asked "which scheme?" (MGNREGA UAT 2026-10-30).
    if _TALKS_ABOUT_SCHEMES.search(out) and not _TALKS_ABOUT_SCHEMES.search(gloss):
        return "scheme"
    # Places: the same districts / blocks, compared canonically ("ekh" = East Khasi Hills).
    if set(context_policy._places(out)) != set(context_policy._places(gloss)):
        return "place"
    # Years: the same financial years.
    if context_policy.extract_year_keys(out) != context_policy.extract_year_keys(gloss):
        return "year"
    # Numbers: every number kept, none invented (years were compared above).
    years_text = " ".join(str(y) for y in context_policy.extract_year_keys(gloss))
    num_in = _numbers(_GAP_YEAR.sub(" ", gloss)) - _numbers(years_text)
    num_out = _numbers(_GAP_YEAR.sub(" ", out)) - _numbers(years_text)
    if num_in != num_out:
        return "number"
    # Measures: the same ones (person-days stays person-days, never payments).
    if _measure_labels(out) != _measure_labels(gloss):
        return "measure"
    # A spend word is MGNREGA's measure: "Compare expenditure and person-days in
    # Gambegre block" came back "How much money and how many person-days…", which
    # no longer reads as expenditure and missed the deterministic query (MGNREGA
    # sheet DATA-029, run 2026-10-09).
    if _REPHRASE_SPEND_WORD.search(gloss) and not _REPHRASE_SPEND_WORD.search(out):
        return "measure"
    # "applicants" (distinct people) is not "applications" (rows): "How many
    # applicants … under each CM ELEVATE program?" came back "…applications…" and
    # was counted with COUNT(*) (Piggery 3,032 for 3,010; CM Elevate sheet run
    # 2026-10-10).
    for _word_matcher in _REPHRASE_COUNT_NOUNS:
        if bool(_word_matcher.search(gloss)) != bool(_word_matcher.search(out)):
            return "measure"
    # An "&" belongs to a name: "mawkohmit & mawkynsah village" (ONE village) came back
    # "mawkohmit and mawkynsah villages" and was asked "which area?" (Focus Legacy
    # all-villages run 2026-10-12).
    if (original or "").count("&") > out.count("&"):
        return "name:&"
    # The name written before "village" stays whole and in order: "for kyrdemkulai 6 km
    # village" came back "for 6 km village in kyrdemkulai" and asked which "6 km village"
    # (CM Elevate Legacy all-villages run 2026-10-12).
    _vm = _c02_name_before_village(original or "")
    if _vm and collapse_ws(_vm).lower() not in collapse_ws(out).lower():
        return "name:village"
    # A comparison stays a comparison: "Compare the total remittance between FY 2022-23
    # and FY 2025-26" came back "What is the total remittance … in FY 2022-23 and FY
    # 2025-26?" and was answered with one combined total (Focus Legacy sheet TC-24,
    # 2026-10-12).
    if _REPHRASE_COMPARE_WORD.search(gloss) and not _REPHRASE_COMPARE_WORD.search(out):
        return "shape"
    # A breakdown stays a breakdown: "block-wise for <district>" / "in each block
    # of <district>" rewritten without it is answered as one district total (the
    # held-out NL->SQL accuracy set lost two per-block answers this way,
    # 2026-10-16). Every dimension the user broke down by must still be there.
    if _c02_breakdowns(gloss) - _c02_breakdowns(out):
        return "breakdown"
    # Families, minus the question shape: "how many" / "how much" / "number of"
    # is how a question is asked, and a shapeless message ("persondays ekh
    # 23-24") legitimately gains one. The measures themselves are compared above.
    if context_policy.metric_families(_QUESTION_SHAPE.sub(" ", out)) \
            - context_policy.metric_families(_QUESTION_SHAPE.sub(" ", gloss)):
        return "metric"
    if context_policy.category_terms(out) - context_policy.category_terms(gloss):
        return "category"
    # Names and unknown words (a village, "Mawlwai") must survive verbatim; a word
    # may only disappear if it was a typo of ordinary vocabulary now present.
    out_words = {w.lower() for w in _c01_alpha_words(out)}
    out_text = out.lower()
    for w in _c01_alpha_words(_expand_short_fy(original)):
        lw = w.lower().strip("'-")
        if _is_known_word(lw) or lw in out_words or lw in out_text:
            continue
        typo = _vocab_typo(lw)
        if typo and typo in out_words:
            continue   # a typo of an ordinary word ("aplications"), fixed
        return f"name:{lw}"
    # A multi-word name must survive as one phrase: "in MAWNGAP MAWSMAI" came
    # back "under MAWNGAP in MAWSMAI" — both words kept, the village lost (it
    # then resolved to the five MAWSMAI villages; MGNREGA sheet run 2026-10-09).
    for phrase in _unknown_word_runs(original):
        if phrase not in collapse_ws(out_text):
            return f"name:{phrase}"
    return None


# A part-marker after a name: one letter or a roman numeral i..x ("rimrangpara a",
# "nokatgre ii"); the text is lower-cased first.
_C02_ROMAN = frozenset({"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"})


def _c02_is_name_suffix(t: str) -> bool:
    return (len(t) == 1 and t.isascii() and "a" <= t <= "z") or t in _C02_ROMAN
_NAME_SUFFIX_FOLLOW = frozenset("during in for of under from block village district year fy".split())


def _unknown_word_runs(text: str) -> list[str]:
    """Runs of two or more consecutive words the vocabulary does not know — a
    multi-word place or name ("mawngap mawsmai", "nongkhlaw mawkyrwat") — with
    any part-marker that belongs to the name: a bracketed qualifier ("ramjonggre
    ( r )") or a trailing letter / roman numeral ("rimrangpara a", "nokatgre i").
    The rephraser dropped "a" (Rimrangpara A became RIMRANGPARA, another village)
    and compacted "( R )" to "(R)" (no longer the exact name) in the MGNREGA
    all-villages run, 2026-10-09."""
    toks = _c02_name_tokens(_expand_short_fy(text or ""))
    runs, cur, i = [], [], 0
    unknown_in_cur = 0
    places = _place_words()

    def _unknown(tok: str) -> bool:
        lt = tok.lower().strip("'-")
        return _c01_is_alpha_word(tok) and not _is_known_word(lt) and not _vocab_typo(lt)

    def _flush():
        nonlocal cur, unknown_in_cur
        if len(cur) >= 2 and unknown_in_cur:
            runs.append(" ".join(cur))
        cur, unknown_in_cur = [], 0

    while i < len(toks):
        w = toks[i]
        lw = w.lower().strip("'-")
        if _unknown(w):
            cur.append(lw)
            unknown_in_cur += 1
            i += 1
            continue
        # A block / constituency word inside a village name ("MYNRI UMSNING" came
        # back "MYNRI in Umsning", MGNREGA all-villages run 2026-10-09) belongs to
        # the name when it touches an unknown word.
        if _c01_is_alpha_word(w) and lw in places and (
                cur or (i + 1 < len(toks) and _unknown(toks[i + 1]))):
            cur.append(lw)
            i += 1
            continue
        if cur and w == "-" and i + 1 < len(toks) and _c02_is_name_suffix(toks[i + 1].lower()):
            # "chisakgre - a" (PMAY-G all-villages run 2026-10-10)
            cur.extend(["-", toks[i + 1].lower()])
            i += 2
            continue
        if cur and w == "(":
            j = toks.index(")", i) if ")" in toks[i:i + 6] else -1
            if j > i:
                cur.extend(t.lower() for t in toks[i:j + 1])
                i = j + 1
                continue
        if cur and _c02_is_name_suffix(lw) and (
                i + 1 >= len(toks) or not _c01_is_alpha_word(toks[i + 1])
                or toks[i + 1].lower() in _NAME_SUFFIX_FOLLOW):
            cur.append(lw)
            i += 1
            continue
        _flush()
        i += 1
    _flush()
    return runs


async def rephrase_question(question: str) -> str:
    """One clean English question for a messy one, or the question unchanged
    (clean already, the model failed or was slow, or the rewrite changed
    meaning). Never raises."""
    guard = "skipped"
    try:
        out = await llm.call_rephraser(prompt_builder.build_rephrase_prompt(question))
        out = _c01_strip_answer_label((out or "").strip().splitlines()[0] if (out or "").strip() else "")
        out = out.strip().strip('"').strip("'").strip()
        if not out or out == question:
            guard = "unchanged"
            return question
        violation = _rephrase_violation(question, out)
        if violation:
            guard = f"rejected:{violation}"
            logger.warning("rephrase rejected (%s): %r -> %r — using the original", violation, question, out)
            return question
        guard = "ok"
        logger.info("rephrase: %r -> %r", question, out)
        return out
    except Exception as e:  # noqa: BLE001 — the original question always goes on
        guard = f"error:{type(e).__name__}"
        logger.warning("rephrase failed (%s) — using the original", e)
        return question
    finally:
        context_budget.log_decision("rephrase", guard=guard, chars=len(question or ""))


# ── Guided-decoding schemas ──────────────────────────────────────────────────
# Passed to the classifier/SQL model so it can only emit tokens that fit the
# shape. The _extract_json / _extract_sql parsers below still run, so these are
# a reliability + speed win with no hard dependency on the gateway honouring
# them. Kept next to the prompts they constrain.
_SCHEMES_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "schemes": {
            "type": "array",
            "items": {"type": "string", "enum": list(SCHEME_CATALOG)},
            "minItems": 1,
        }
    },
    "required": ["schemes"],
}
# All optional strings — no null-union type (some xgrammar builds reject it) and
# no `required` (the model emits only the keys it actually finds). The parser in
# extract_entity_mentions already tolerates a partial or empty object.
_ENTITY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "district": {"type": "string"},
        "block": {"type": "string"},
        "village": {"type": "string"},
        "year": {"type": "string"},
        "assembly_constituency": {"type": "string"},
        # Plural — ONLY when the question names two-or-more blocks to compare
        # against each other ("compare X and Y"). Kept separate from "block"
        # rather than making "block" a string-or-array union (some xgrammar
        # builds reject union types, per the note above).
        "blocks": {"type": "array", "items": {"type": "string"}},
        # Same idea, for districts ("compare X and Y between district A and B").
        "districts": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}
_INTENT_JSON_SCHEMA = {
    "type": "object",
    "properties": {"intent": {"type": "string", "enum": ["DATA", "KNOWLEDGE"]}},
    "required": ["intent"],
}
# No `required: ["issue"]` — the verifier only needs to emit "issue" when
# ok is false; a passing query should cost the fewest tokens possible.
_SQL_VERIFY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "issue": {"type": "string"},
    },
    "required": ["ok"],
}
# SQL calls carry NO guided-decoding constraint. The old one was a text rule sent to
# vLLM ("open on SELECT/WITH"); the project rule is that SQL is read and shaped
# only through sqlglot, so _extract_sql below finds the statement on the sqlglot
# token stream instead (prose preamble, ```sql fence and all).


def _extract_json(raw: str) -> dict | None:
    a, b = (raw or "").find("{"), (raw or "").rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(raw[a:b + 1])
    except json.JSONDecodeError:
        return None


def _sql_tokens(sql: str) -> list:
    """sqlglot's token stream for `sql` (Postgres), [] when it cannot be
    tokenized (an unterminated quote in prose, say)."""
    try:
        return sqlglot.tokenize(sql or "", read=sql_ast.DIALECT)
    except (SqlglotError, ValueError):
        return []


def _strip_markdown_fences(raw: str) -> str:
    """The text without ``` fence markers (and the 'sql' tag after one). When
    the output holds a fenced block with a query in it, only that block: prose
    the model wrote before or after the fence is not part of the query."""
    parts = (raw or "").split("```")
    if len(parts) == 1:
        return raw or ""
    for i in range(1, len(parts)):
        tag = parts[i][3:4]
        if parts[i][:3].lower() == "sql" and not (tag.isalnum() or tag == "_"):
            parts[i] = parts[i][3:]
    if len(parts) >= 3 and any(w.upper() in ("SELECT", "WITH") for _s, _e, w in _word_spans(parts[1])):
        return parts[1]
    return "".join(parts)


def _sql_start(text: str) -> int:
    """Where the query begins in model output that may open with prose ("Here
    is the query:"). 0 when the text already opens on SELECT / WITH / '('.
    Otherwise the first SELECT / WITH word from which the rest parses as one
    query; failing that the first such word at the start of a line, then the
    first such word at all; 0 when there is none."""
    first = sql_ast.first_keyword(text)
    if first in ("SELECT", "WITH", "("):
        return 0
    starts = [s for s, _e, w in _word_spans(text) if w.upper() in ("SELECT", "WITH")]
    if not starts:
        return 0
    for s in starts:
        tree = sql_ast.parse_one(text[s:])
        if isinstance(tree, exp.Query):
            return s
    line_starts = [s for s in starts if not text[:s].rpartition("\n")[2].strip()]
    return (line_starts or starts)[0]


def _extract_sql(raw: str) -> str:
    # Strip a ```sql fence if the model added one despite being told not to, and
    # any prose before the query.
    cleaned = _strip_markdown_fences(raw or "").strip()
    cleaned = cleaned[_sql_start(cleaned):].strip()
    cleaned = cleaned.rstrip(";").strip()
    # The generator sometimes copies a worked example that ends its outer query
    # with ';' and then appends its own trailing "LIMIT n" AFTER that ';'
    # ("... ) d;\nLIMIT 1"). That is one statement, not two — fold the stray
    # terminator away so it isn't rejected as "multiple statements". Only a bare
    # trailing LIMIT/OFFSET/FETCH tail is spliced back; anything else after a ';'
    # is left for the multi-statement guard to reject.
    tokens = _sql_tokens(cleaned)
    for i, tok in enumerate(tokens[:-1]):
        if tok.token_type == TokenType.SEMICOLON and tokens[i + 1].text.upper() in ("LIMIT", "OFFSET", "FETCH"):
            cleaned = (cleaned[: tok.start] + "\n" + cleaned[tokens[i + 1].start:]).strip()
            break
    return cleaned


_SCHEME_NAME_MATCHER = {
    "MGNREGA": _C01Quick(W("mgnrega", "mnrega", "nrega"), need=("nrega",)),
    "PMAY-G": _C01Quick(Alt(_c01_chain(["pmay", "g"], ["opt1"]), W("pmay"), Pred(_c02_is_awaas)),
                         need=("pmay", "awa")),
    "Focus Plus": _C01PlusMatcher(Alt(_c01_chain(["focus", "plus"], ["opt1"]),
                                      Seq(W("focus"), _C01NextChar("+"))), need=("focus",)),
    # The lookarounds keep "CM Elevate Legacy" / "CM Elevate Disbursement" /
    # "Legacy CM Elevate" from ALSO reading as the applications dataset — that is
    # the other scheme below, and matching both turned a single-scheme question
    # into a two-scheme comparison.
    "CM Elevate": _C01Quick(Seq(
        _C01NotPreceded("legacy ", "legacy-"),
        _c01_chain(["cm", "elevate"], ["opt1"]),
        _C01NotNextWord(("legacy", "disbursement", "disbursements"), _c01_wsdash)), need=("elevate",)),
    # CM Elevate Legacy is the SANCTION-AND-DISBURSEMENT dataset (DB name: CM
    # Elevate Disbursement), NOT the CM Elevate applications dataset. The two share
    # the name and no key (cmelevatelegacy_entity_resolver.yaml
    # scheme.disambiguation). Only a qualified form names it here; a bare "CM
    # Elevate" that carries money / year / lender vocabulary is re-pointed to it
    # by _pin_cm_elevate_dataset() before routing.
    "CM Elevate Legacy": _C01Quick(Alt(
        _c01_chain(["cm", "elevate", ("legacy", "disbursement", "disbursements")], ["opt1", "wsd*"]),
        Seq(W("legacy"), _C01Gap(_c01_wsdash), _c01_chain(["cm", "elevate"], ["opt1"])),
        _c01_chain(["elevate", "legacy"], ["opt1"])), need=("elevate",)),
    # Focus Legacy is the producer-group scheme, NOT Focus Plus. The two share the
    # word "Focus" and nothing else (no shared key; Focus Plus holds no
    # producer-group column at all — focuslegacy_entity_resolver.yaml
    # scheme.disambiguation). Both matchers demand a qualifier, so a BARE "focus"
    # matches neither and falls through to the "which Focus?" ask below.
    "Focus Legacy": _C01Quick(Alt(
        _c01_chain(["focus", "legacy"], ["opt1"]), _c01_chain(["legacy", "focus"], ["opt1"]),
        _c01_chain(["old", "focus"], ["opt1"]), _c01_chain(["focus", "pg"], ["opt1"]),
        _c01_chain(["pg", "focus"], ["opt1"])), need=("focus",)),
}
# Fuzzy fallback for a scheme name the exact matcher above misses because it's
# misspelled ("manrega", "pamay") — mirrors the RapidFuzz tolerance
# entity_resolver.py already gives district/block names. Kept separate from
# _SCHEME_NAME_MATCHER (exact match stays the fast, zero-false-positive path;
# this only runs when nothing named matches outright).
_SCHEME_FUZZY_ALIASES = {
    # "manrega" / "manraya": how voice typing renders the spoken name (UI
    # 2026-10-18: "What is the total beneficiaries manraya?").
    "MGNREGA": ["mgnrega", "mnrega", "nrega", "manrega", "manraya"],
    "PMAY-G": ["pmay", "pmayg", "awaas", "awas"],
    # NOTE: the bare "focus" alias used to live here, so a typo of the short form
    # ("facus", "fokus") still routed to Focus Plus. It was REMOVED when Focus
    # Legacy landed: with two live Focus schemes a bare or misspelled "focus"
    # identifies neither, and guessing Focus Plus would answer a producer-group
    # question from a partition that holds no producer groups at all. Such a
    # question now reaches _focus_ambiguity_clarification() instead.
    "Focus Plus": ["focusplus"],
    "CM Elevate": ["cmelevate"],
    "Focus Legacy": ["focuslegacy"],
    "CM Elevate Legacy": ["cmelevatelegacy"],
}
_FUZZY_SCHEME_ACCEPT = 80


def _fuzzy_named_schemes(question: str) -> list[str]:
    words = [w.lower() for _s, _e, w in _c02_letter_runs(question or "") if len(w) >= 5]
    if not words:
        return []
    hits: list[str] = []
    for scheme, aliases in _SCHEME_FUZZY_ALIASES.items():
        if any(fuzz.ratio(w, a) >= _FUZZY_SCHEME_ACCEPT for w in words for a in aliases):
            hits.append(scheme)
    return hits


# Voice-typing renderings that are never anything but the scheme: always
# rewritten to its name in the text (the exact-alias rule below keeps an alias
# as typed, since "pmay" / "mnrega" are partial spellings of the real name).
# UI 2026-10-18: "…beneficiaries manraya?" was rewritten by the follow-up model
# as "the Manraya scheme" and answered for every scheme.
_SCHEME_SPOKEN_FORMS = {"manrega": "MGNREGA", "manraya": "MGNREGA"}


_SCHEME_CANONICAL_SPELLING = {
    "MGNREGA": "MGNREGA", "PMAY-G": "PMAY-G",
    "Focus Plus": "Focus Plus", "CM Elevate": "CM Elevate",
    "Focus Legacy": "Focus Legacy", "CM Elevate Legacy": "CM Elevate Legacy",
}


# "West Garo Hils" lost its district: the misspelt "Hils" stopped the district
# name matching, so the remaining "Garo Hils" read as the whole Garo Hills region
# and the bot asked which of its five districts (General TC-017, test run
# 2026-10-06). Every Meghalaya district / region name ends "<range> Hills", so a
# near-miss of "Hills" right after a range word is only ever that.
_HILLS_TYPO_MATCH = Matcher(Seq(Cap(W("garo", "khasi", "jaintia", "jaiñtia")),
                             W("hil", "hils", "hll", "hlls", "hilll", "hillls", "hill"), sep="space"))


# "FY2022-23" / "FY22-23" (no space) matched none of the year matchers, which all
# expect the year to start a word: the year was dropped and the answer
# covered every year (KI-289, matrix run 2026-10-14). "FY 2022-23" is read.
_FY_NO_SPACE_MATCH = Matcher(Pred(lambda w: w[:2].lower() == "fy" and len(w) > 2 and w[2].isdigit()))


# Spoken years -> digits, so every year reader downstream sees "2025-26".
# "…per financial year twenty twenty five to twenty six?" found no year at all,
# no scheme and 0 rows in 15.8 s (errors.md case 11, audit log 2026-10-15); a
# voice question arrives exactly like that. Only shapes that are unmistakably a
# year are read: "twenty" + a two-digit number ("twenty twenty three",
# "twenty nineteen"), "two thousand [and] N"; a second year counts as the end of
# a financial-year range only when it is the very next year, so "top twenty
# five districts" or "twenty five blocks" are never touched.
_C02_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9}
_C02_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
              "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_C02_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
             "eighty": 80, "ninety": 90}
_C02_RANGE_WORDS = {"to", "till", "until", "through", "thru", "and"}


def _c02_num_99(toks: list, i: int) -> "tuple[int, int] | None":
    """A spoken number 0..99 starting at token i: (value, index after it)."""
    if i >= len(toks):
        return None
    w = toks[i].low
    if w in _C02_TEENS:
        return _C02_TEENS[w], i + 1
    if w in _C02_TENS:
        if i + 1 < len(toks) and toks[i + 1].low in _C02_UNITS and toks[i + 1].low != "zero":
            return _C02_TENS[w] + _C02_UNITS[toks[i + 1].low], i + 2
        return _C02_TENS[w], i + 1
    if w in _C02_UNITS:
        return _C02_UNITS[w], i + 1
    if w == "oh" and i + 1 < len(toks) and toks[i + 1].low in _C02_UNITS:
        return _C02_UNITS[toks[i + 1].low], i + 2
    return None


def _c02_spoken_year(toks: list, i: int) -> "tuple[int, int] | None":
    """A spoken calendar year 2000-2099 starting at token i: (year, index after it)."""
    if i >= len(toks):
        return None
    w = toks[i].low
    if w == "twenty":
        n = _c02_num_99(toks, i + 1)
        if n and 10 <= n[0] <= 99:
            return 2000 + n[0], n[1]
        if n and toks[i + 1].low == "oh":          # "twenty oh five"
            return 2000 + n[0], n[1]
        return None
    if w == "two" and i + 1 < len(toks) and toks[i + 1].low == "thousand":
        j = i + 2
        if j < len(toks) and toks[j].low == "and":
            j += 1
        n = _c02_num_99(toks, j)
        return (2000 + n[0], n[1]) if n else (2000, j)
    return None


def _c02_gap_is_list(gap: str) -> bool:
    """Only spaces, commas, hyphens or dots between two spoken digits."""
    return all(c.isspace() or c in ",-." for c in gap)


def _spoken_digit_years(question: str) -> str:
    """Digit by digit, as voice typing writes it: 'two zero two three' -> '2023';
    'two zero two three two zero two four' -> '2023-24'. UI 2026-10-18: "how many
    houses are there in two zero, two three, two two zero two four" (a stutter
    included) was answered for all years. Only a run of spoken digits holding
    "two zero X Y" is read; a second year makes a range only when it is the next
    year, and a stray digit between the two years is part of the range."""
    toks = _c01_tm_tokens(question)
    if not any(t.low == "zero" for t in toks):
        return question
    runs, i = [], 0
    while i < len(toks):
        if toks[i].low not in _C02_UNITS:
            i += 1
            continue
        j = i + 1
        while (j < len(toks) and toks[j].low in _C02_UNITS
               and _c02_gap_is_list(question[toks[j - 1].end:toks[j].start])):
            j += 1
        runs.append((i, j))
        i = j
    out, last = [], 0
    for a, b in runs:
        vals = [_C02_UNITS[t.low] for t in toks[a:b]]
        years, k = [], 0
        while k + 3 < len(vals):
            if vals[k] == 2 and vals[k + 1] == 0:
                years.append((2000 + vals[k + 2] * 10 + vals[k + 3], a + k, a + k + 4))
                k += 4
            else:
                k += 1
        n = 0
        while n < len(years):
            y1, s1, e1 = years[n]
            if n + 1 < len(years) and years[n + 1][0] == y1 + 1:
                text, end = f"{y1}-{years[n + 1][0] % 100:02d}", years[n + 1][2]
                n += 2
            else:
                text, end = str(y1), e1
                n += 1
            out.append(question[last:toks[s1].start])
            out.append(text)
            last = toks[end - 1].end
    if not out:
        return question
    out.append(question[last:])
    result = "".join(out)
    logger.info("spoken digit year read: %r -> %r", question, result)
    return result


def _spoken_years_to_digits(question: str) -> str:
    """'twenty twenty five to twenty six' -> '2025-26'; 'two thousand twenty three'
    -> '2023'; 'two zero two three' -> '2023'. Digits, punctuation and every other
    word are left untouched."""
    question = _spoken_digit_years(question)
    toks = _c01_tm_tokens(question)
    if not any(t.low in ("twenty", "thousand") for t in toks):
        return question
    out, last, i = [], 0, 0
    while i < len(toks):
        y = _c02_spoken_year(toks, i)
        if y is None:
            i += 1
            continue
        start_year, j = y
        end_text, k = None, j
        k2 = k + 1 if k < len(toks) and toks[k].low in _C02_RANGE_WORDS else k
        nxt = _c02_spoken_year(toks, k2)
        if nxt and nxt[0] == start_year + 1:
            end_text, k = f"{nxt[0] % 100:02d}", nxt[1]
        else:
            n = _c02_num_99(toks, k2)
            if n and n[0] == (start_year + 1) % 100:
                end_text, k = f"{n[0]:02d}", n[1]
        replacement = f"{start_year}-{end_text}" if end_text else str(start_year)
        stop = k if end_text else j
        out.append(question[last:toks[i].start])
        out.append(replacement)
        last = toks[stop - 1].end
        i = stop
    out.append(question[last:])
    result = "".join(out)
    if result != question:
        logger.info("spoken year read as digits: %r -> %r", question, result)
    return result


def _correct_fy_spacing(question: str) -> str:
    if not question:
        return question
    question = _spoken_years_to_digits(question)
    out = _FY_NO_SPACE_MATCH.sub(lambda m: m.group(0)[:2] + " " + m.group(0)[2:], question)
    # "persons employed for the state" was refused as another state (matrix run
    # 2026-10-14): the only state held is Meghalaya.
    return _THE_STATE_MATCH.sub(lambda m: f"{m.group(1)} Meghalaya", out)


_THE_STATE_MATCH = Matcher(Seq(
    Cap(W("for", "in", "across", "of", "throughout")), "the", Opt(W("whole", "entire")),
    Seq("state", _C01NotNextWord(("of",), _c01_ws)), sep="space"))


# ── A ranking count written as a word ("five highest", "top ten") ───────────
# "Five highest blocks by person-days" asked "top 3, 5 or 10?" although it says
# five, while "top 5 blocks" was answered (audit 2026-10-23; RAG plan C2): the
# count gate and the SQL rewrites read digits. The count is written as digits
# here, once, so every later step sees one form ("5 highest", "top 5").
# Only in a ranking position, so "five years", "the two schemes" and place names
# are left alone; ordinals ("fifth highest" = one row at rank 5) are not counts.
_C02_RANK_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
              "nine": 9}
_C02_RANK_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
              "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_C02_RANK_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
             "eighty": 80, "ninety": 90, "hundred": 100}
# After a number word: these make it a ranking count ("five highest", "ten lowest").
_C02_RANK_AFTER = frozenset("highest lowest largest biggest smallest best worst top leading most least "
                            "poorest weakest strongest".split())
# Before a number word: "top five", "bottom ten", "first five".
_C02_RANK_BEFORE = frozenset("top bottom first last".split())
# "which five blocks", "what three districts".
_C02_WHICH = frozenset(("which", "what"))
_C02_PLACES = frozenset("districts blocks villages panchayats gps constituencies".split())
# Never a ranking count when the number is a span of time ("last five years").
_C02_TIME_UNITS = frozenset("year years month months day days week weeks fy fys".split())


def _c02_count_at(toks, i: int, text: str) -> "tuple[int, int] | None":
    """(value, index of the last token used) for the number word at toks[i]
    ("five", "twenty five", "twenty-five"), or None."""
    w = toks[i].low
    if w in _C02_RANK_UNITS:
        return _C02_RANK_UNITS[w], i
    if w in _C02_RANK_TEENS:
        return _C02_RANK_TEENS[w], i
    if w in _C02_RANK_TENS:
        if w != "hundred" and i + 1 < len(toks) and toks[i + 1].low in _C02_RANK_UNITS \
                and text[toks[i].end:toks[i + 1].start] in (" ", "-"):
            return _C02_RANK_TENS[w] + _C02_RANK_UNITS[toks[i + 1].low], i + 1
        return _C02_RANK_TENS[w], i
    return None


def _normalize_rank_counts(question: str) -> str:
    """'Five highest blocks' -> '5 highest blocks', 'top ten' -> 'top 10',
    'which three districts' -> 'which 3 districts'. Everything else unchanged."""
    if not question:
        return question
    toks = _c01_tm_tokens(question)
    out, last, i = [], 0, 0
    while i < len(toks):
        hit = _c02_count_at(toks, i, question)
        if hit is None:
            i += 1
            continue
        value, j = hit
        prev = toks[i - 1].low if i > 0 else ""
        nxt = toks[j + 1].low if j + 1 < len(toks) else ""
        # "one" is a count only after top / bottom: "the first one", "which one"
        # and "one highest" are not.
        ranking = (nxt in _C02_RANK_AFTER and value > 1) \
            or (prev in _C02_RANK_BEFORE and (value > 1 or prev in ("top", "bottom"))) \
            or (prev in _C02_WHICH and nxt in _C02_PLACES and value > 1)
        if not ranking or nxt in _C02_TIME_UNITS:
            i = j + 1
            continue
        out.append(question[last:toks[i].start])
        out.append(str(value))
        last = toks[j].end
        i = j + 1
    if last == 0:
        return question
    out.append(question[last:])
    result = "".join(out)
    logger.info("ranking count read as digits: %r -> %r", question, result)
    return result


def _correct_place_spelling(question: str) -> str:
    """'<range> Hils' / 'Hill' / 'Hlls' -> '<range> Hills' (district and region names)."""
    if not question:
        return question
    out = _HILLS_TYPO_MATCH.sub(lambda m: f"{m.group(1)} Hills", question)
    if out != question:
        logger.info("place spelling corrected: %r -> %r", question, out)
    return out


def _correct_scheme_spelling(question: str) -> str:
    """Fix an obviously misspelled scheme name in the question text itself
    ("manrega" -> "MGNREGA", "pamay" -> "PMAY-G") before routing. Without this,
    a typo'd scheme name only ever gets caught on the DATA path (via
    _fuzzy_named_schemes) — the KNOWLEDGE/RAG path embeds the raw text
    verbatim, so the typo silently tanks vector-search relevance against the
    scheme's own reference docs and the question comes back "not covered".
    Conservative by construction: a word only gets corrected when it does NOT
    already exactly match a scheme alias (nothing to fix) and DOES fuzzy-match
    one closely enough — so it can't mangle an unrelated word."""
    if not question:
        return question

    # A scheme already named correctly elsewhere in the question (exact match,
    # e.g. "CM ELEVATE") must not also be "corrected" word-by-word below — the
    # lone word "Elevate" fuzzy-matches the "cmelevate" alias on its own
    # (fuzz.ratio("elevate", "cmelevate") ~= 87.5, over the 80 threshold), so
    # without this guard "CM ELEVATE" gets the already-present "CM" duplicated
    # into "CM CM Elevate" (and worse on a second pass, e.g. a resumed
    # clarification chip, into "CM CM CM Elevate").
    _already_named = {s for s, pat in _SCHEME_NAME_MATCHER.items() if pat.search(question)}
    # "CM Elevate Legacy" already contains the "CM Elevate" words, but the CM
    # Elevate matcher deliberately does not match it — so without this the lone
    # word "Elevate" would be "corrected" into "CM CM Elevate Legacy".
    if "CM Elevate Legacy" in _already_named:
        _already_named.add("CM Elevate")

    def _sub(word: str) -> str:
        if len(word) < 5:
            return word
        wl = word.lower()
        spoken = _SCHEME_SPOKEN_FORMS.get(wl)
        if spoken and spoken not in _already_named:
            return _SCHEME_CANONICAL_SPELLING[spoken]
        for scheme, aliases in _SCHEME_FUZZY_ALIASES.items():
            if scheme in _already_named:
                continue
            if wl in aliases:
                return word
            if any(fuzz.ratio(wl, a) >= _FUZZY_SCHEME_ACCEPT for a in aliases):
                return _SCHEME_CANONICAL_SPELLING[scheme]
        return word

    out, last = [], 0
    for a, b, word in _c02_letter_runs(question):
        out += [question[last:a], _sub(word)]
        last = b
    out.append(question[last:])
    return "".join(out)

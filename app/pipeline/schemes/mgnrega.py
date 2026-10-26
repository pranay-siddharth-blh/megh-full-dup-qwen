# app/pipeline/schemes/mgnrega.py — MGNREGA — village rules, SQL guards, fixed queries and answer checks.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
# Only this scheme's code lives here; the shared steps that call it are in ../common/.
# Sections follow the order of the pipeline steps they belong to.
# SQL is read and rewritten on the SQLGlot tree (app/sql_ast.py), never as raw
# text; the question and the answer are read on WORDS (app/text_match.py).
from app import sql_ast
from app.text_match import Alt, Joined, Matcher, NotAfter, NotBefore, Opt, Pred, Seq, W, collapse_ws, tokens
from sqlglot import exp

# ════ scheme terms ════════════════════════════════════════════════════════════════════════════════════
# Vocabulary that only makes sense for ONE scheme, so we can infer it without
# asking even when the scheme is not named. Kept deliberately narrow — a term
# that both schemes use (e.g. "beneficiaries", "paid", "pending", "amount")
# must NOT appear here, or an ambiguous question gets silently mis-routed.
def _mg_sp(*parts):
    """Words in a row with only whitespace between them."""
    return Seq(*parts, sep="space")


_MG_DAYS = ("day", "days")
_MG_BE_EMPLOYED = Opt(Alt("were", "are", _mg_sp("have", "been"), _mg_sp("has", "been")))
_MG_VS = ("or", "and", "vs", "versus")
_MGNREGA_ONLY_TERMS = Matcher(Alt(
    Joined("person", _MG_DAYS), _mg_sp("job", ("card", "cards")), Joined("100", _MG_DAYS),
    _mg_sp("hundred", _MG_DAYS), W("muster"),
    # "households/persons [were/are/have been] employed" — the naive adjacent
    # phrase ("households? employed") missed the common "persons WERE employed"
    # wording (TC-024: a plain past-tense employment question with no scheme
    # named kept falling through to the scheme-clarification prompt).
    _mg_sp(("household", "households"), _MG_BE_EMPLOYED, "employed"),
    _mg_sp(("person", "persons"), _MG_BE_EMPLOYED, "employed"),
    # "received employment" is as common a phrasing as "were employed" — same
    # gap as above, just a different verb (DATA-004 used exactly this).
    # "got employment" is the same ask with an everyday verb; it drew a "which
    # scheme?" pause right after "Tell me about MGNREGA" (General TC-024,
    # test run 2026-10-06).
    _mg_sp(("household", "households", "person", "persons", "people"),
           Alt(W("receiv", prefix=True), W("got", "get", "gets", "getting", "obtained")),
           Opt("any"), "employment"),
    # "women [were/are] provided/given employment" / "women employed" — same
    # missing-verb-phrasing gap as above (DATA-008 used exactly this; there
    # was no women-employment matcher here at all before, only in edge.py's
    # unrelated domain whitelist).
    _mg_sp("women", Opt(W("were", "are")), ("provided", "given"), "employment"),
    _mg_sp("women", W("employ", prefix=True)),
    # A constituency pinned MGNREGA on its own while only mgnrega_employment
    # carried one. Focus Legacy and CM Elevate Legacy reach ac_name too
    # (_AC_CAPABLE_SCHEMES), so _infer_scheme_from_terms no longer lets this
    # term decide alone (_MGNREGA_AC_TERM, KI-148).
    _mg_sp("assembly", W("constituenc", prefix=True)),
    _mg_sp("ac", Pred(lambda w: w.isdecimal())),
    Pred(lambda w: w[:2].lower() == "ac" and w[2:].isdecimal() and len(w) > 2),
    # unskilled/semi-skilled wage(s) — "wage" with no optional "s" only matched the
    # singular; "unskilled wages" (the common plural phrasing, DATA-010) never
    # matched because the whole word "wage" can't end inside "wages".
    _mg_sp("unskilled", ("wage", "wages")), Joined("semi", "skilled"),
    # Measures that only MGNREGA holds but that the testers phrased without a
    # scheme name — each one drew an unnecessary "which scheme?" pause (MGNREGA
    # QA 2026-09-26, KI-043): "spent on materials" (DATA-011), "wages or
    # materials" (DATA-023), "villages … received employment" / "women received
    # employment" (DATA-014/017 — the verb, not the subject, is the signal),
    # "employment persons/households" (DATA-019/020), "employment generated"
    # (DATA-030), and administrative expenditure, whose only column is
    # MGNREGA's (DATA-013). No other loaded scheme has wages, materials or
    # employment at all.
    _mg_sp(Alt(W("spend", prefix=True), W("spent", "expenditure", "cost", "costs")), "on",
           ("material", "materials", "wage", "wages")),
    _mg_sp(("material", "materials"), Alt(W("expenditure", "cost", "costs"), W("spend", prefix=True))),
    _mg_sp("wage", "expenditure"),
    # "wages vs. materials": whitespace before the conjunction, any after (the dot)
    Seq(_mg_sp(("wage", "wages"), _MG_VS), ("material", "materials")),
    Seq(_mg_sp(("material", "materials"), _MG_VS), ("wage", "wages")),
    _mg_sp(W("receiv", prefix=True), "employment"), _mg_sp("employment", ("persons", "households")),
    _mg_sp("employment", "generated"), _mg_sp("generated", "employment"),
    _mg_sp(("administrative", "admin"),
           ("expenditure", "expenditures", "expense", "expenses", "cost", "costs")),
    _mg_sp("labour", "budget"), _mg_sp(("work", "works"), "demanded"), _mg_sp("wage", "employment"),
    _mg_sp("employment", "guarantee"),
))


# "What is the total amount disbursed for Baghmara assembly constituency?" was
# read as MGNREGA (no disbursement column) and failed on all 55 constituencies
# (Focus Legacy bulk run 2026-09-29). Naming a constituency says nothing about
# the scheme once three schemes hold one: it pins MGNREGA only beside a real
# MGNREGA measure, and otherwise the scheme is asked (_scheme_clarification
# then offers only the schemes that have constituency data).
_MGNREGA_AC_TERM = Matcher(Alt(
    _mg_sp("assembly", W("constituenc", prefix=True)),
    _mg_sp("ac", Pred(lambda w: w.isdecimal())),
    Pred(lambda w: w[:2].lower() == "ac" and w[2:].isdecimal() and len(w) > 2)))


# "Expenditure" is MGNREGA's word: it is the only loaded scheme with an
# expenditure column (PMAY-G sanctions and releases, Focus and CM Elevate Legacy
# disburse). "What was the total expenditure in <village> during 2024-25?" and
# "Which district had the highest expenditure?" asked "which scheme?" on every
# run (MGNREGA sheet DATA-001/002/022/024, 2026-10-09). A question that talks
# about schemes ("which scheme had the highest expenditure?") still asks.
_MGNREGA_EXPENDITURE_WORD = Matcher(W("expenditure", "expenditures"))


def _mgnrega_terms(question: str) -> bool:
    q = _MGNREGA_AC_TERM.sub(" ", question or "")
    if _MGNREGA_ONLY_TERMS.search(q):
        return True
    return bool(_MGNREGA_EXPENDITURE_WORD.search(q) and not _TALKS_ABOUT_SCHEMES.search(q)
                and not _EXPLICIT_BOTH.search(q))


# ════ villages ════════════════════════════════════════════════════════════════════════════════════════
def _mg_ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _mg_name_offsets(hay: str, name: str, *, fold: bool = False) -> list[int]:
    """Offsets where `name` stands in `hay` with no ASCII letter or digit touching
    it on either side (names hold spaces, '&', '-', '.'; matched verbatim).
    fold=True ignores case."""
    h, n = (hay.lower(), name.lower()) if fold else (hay, name)
    out: list[int] = []
    if not n:
        return out
    i = h.find(n)
    while i >= 0:
        e = i + len(n)
        if (i == 0 or not _mg_ascii_alnum(h[i - 1])) and (e >= len(h) or not _mg_ascii_alnum(h[e])):
            out.append(i)
        i = h.find(n, i + 1)
    return out


_MG_PLACE_PREPS = ("IN", "OF", "AT", "FOR", "FROM")
_MG_OUTSIDE_OR_STATE = Matcher(Alt(_mg_sp("outside", "meghalaya"), _mg_sp("the", ("state", "country"))))
_MG_VILLAGE_WORD = Matcher(W("village", case=True))


def _mg_after_place_prep(qu: str, i: int) -> bool:
    """`qu` (upper-cased, single-spaced) has a whole word IN/OF/AT/FOR/FROM and one
    space right before offset i."""
    if i < 1 or qu[i - 1] != " ":
        return False
    head = qu[:i - 1]
    for p in _MG_PLACE_PREPS:
        if head.endswith(p):
            k = len(head) - len(p)
            if k == 0 or not (head[k - 1].isalnum() or head[k - 1] == "_"):
                return True
    return False


async def _mgnrega_village_chip_pin(question: str, scheme: "str | None" = None) -> "dict | None":
    """The ONE village a resumed village-disambiguation chip names, read from the
    chip's own text: the block and district in its tail, and the village name in
    the stem (the chip substituted the candidate's canonical name there).

    Without this, the resume was re-resolved from scratch and looped (all-villages
    QA 2026-09-26): the extractor tagged CHIGITCHAKGRE as a *block*, whose
    fallback village lookup ignores the tail; and a chip that also carried
    ", the village, not another area type" cleared the block slot, leaving two
    KATALBARIs in the district — the same question came back every time."""
    m = _CHIP_TAIL_PARSE_MATCH.search(question or "")
    if not m or m.group("block").strip().lower() in ("none", ""):
        return None
    block, district = m.group("block").strip(), m.group("district").strip()
    stem = question[:m.start()]
    # A twin-village chip names its LGD code ("BOLDAMGRE (LGD 272933), SELSELLA
    # block, …" — see _village_code_tag): that code IS the choice.
    _coded = _CHIP_LGD_CODE_MATCH.search(stem)
    if _coded:
        try:
            rows = await fetch_rows(
                "SELECT village_code, lgd_village_name, lgd_block, lgd_district "
                "FROM curated.dim_geography WHERE village_code = $1 LIMIT 1", [int(_coded.group(1))])
        except Exception:  # noqa: BLE001 — fall back to the name match below
            rows = []
        if rows:
            return rows[0]
    try:
        rows = await fetch_rows(
            "SELECT DISTINCT village_code, lgd_village_name, lgd_block, lgd_district "
            "FROM curated.dim_geography WHERE UPPER(lgd_block) = UPPER($1) "
            "AND UPPER(lgd_district) = UPPER($2)", [block, district])
    except Exception:  # noqa: BLE001 — fall back to normal resolution
        return None
    hits = [r for r in rows if r.get("lgd_village_name")
            and _mg_name_offsets(stem, str(r["lgd_village_name"]), fold=True)]
    if not hits:
        return None
    longest = max(len(str(r["lgd_village_name"])) for r in hits)
    hits = [r for r in hits if len(str(r["lgd_village_name"])) == longest]
    # Two dim rows with the same name in the same block, only one of which the
    # asking scheme holds: "Bolbokgre, DEMDEMA block" is 272918 AND 273107 in
    # dim_geography, CM Elevate has 273107 only, and the chip answered 0 for
    # 272918 (CM Elevate all-villages run 2026-09-28). Keep the scheme's own.
    if scheme in _VILLAGE_NARROW_SCHEMES and len({r["village_code"] for r in hits}) > 1:
        try:
            _own = {c["village_code"] for v in (await _scheme_village_names(scheme)).values() for c in v}
        except Exception:  # noqa: BLE001
            _own = set()
        hits = [r for r in hits if r["village_code"] in _own] or hits
    if scheme == "CM Elevate Legacy" and len({r["village_code"] for r in hits}) > 1:
        try:
            _own = {r["village_code"] for r in await fetch_rows(
                "SELECT DISTINCT village_code FROM curated.v_cm_elevate_disbursement "
                "WHERE village_code = ANY($1::int[])", [[int(r["village_code"]) for r in hits]])}
        except Exception:  # noqa: BLE001
            _own = set()
        hits = [r for r in hits if r["village_code"] in _own] or hits
    if len({r["village_code"] for r in hits}) == 1:
        return hits[0]
    # Two dim rows with the same name in the same block: resolve_village collapses them.
    rv = await resolve_village(str(hits[0]["lgd_village_name"]), district=district, block=block)
    if rv.status == "resolved":
        return {"village_code": rv.canonical, "lgd_village_name": hits[0]["lgd_village_name"],
                "lgd_block": hits[0]["lgd_block"], "lgd_district": hits[0]["lgd_district"]}
    return None


async def _mgnrega_villages_with_data(candidates: list[dict]) -> list[dict]:
    """The candidates that hold any MGNREGA row (employment or expenditure); all of
    them when none or every one does, or when the lookup fails.

    "ADUGRE in South West Garo Hills" matched two registry villages, Adugre in
    Rerapara block and ADUGRE in Betasing block, and the bot asked which — but only
    Betasing's (273807) has MGNREGA data; the Rerapara one exists only in the
    geography registry. A choice between a village with figures and one without
    is not a real choice (General TC-020, test run 2026-10-06)."""
    codes = [int(c["village_code"]) for c in candidates if str(c.get("village_code", "")).isdigit()]
    if len(codes) < 2:
        return candidates
    try:
        rows = await fetch_rows(
            "SELECT DISTINCT village_code FROM curated.v_employment WHERE village_code = ANY($1::int[]) "
            "UNION SELECT DISTINCT village_code FROM curated.v_expenditure WHERE village_code = ANY($1::int[])",
            [codes])
    except Exception:  # noqa: BLE001 — the lookup is an aid, never a reason to fail
        return candidates
    held = {int(r["village_code"]) for r in rows if r.get("village_code") is not None}
    keep = [c for c in candidates if str(c.get("village_code", "")).isdigit() and int(c["village_code"]) in held]
    if keep and len(keep) < len(candidates):
        logger.info("MGNREGA village %s: kept %d of %d candidates that hold MGNREGA data",
                    [c.get("name") for c in candidates][:3], len(keep), len(candidates))
        return keep
    return candidates


_MGNREGA_VILLAGE_NAMES: "dict[str, list[dict]] | None" = None


async def _mgnrega_village_names() -> "dict[str, list[dict]]":
    """UPPER(name) -> villages, for every village in MGNREGA's two facts. Loaded
    once per process (≈6,500 names)."""
    global _MGNREGA_VILLAGE_NAMES
    if _MGNREGA_VILLAGE_NAMES is None:
        rows = await fetch_rows(
            "SELECT DISTINCT village_code, lgd_village_name, UPPER(lgd_block) AS block, "
            "UPPER(lgd_district) AS district FROM curated.v_employment "
            "UNION SELECT DISTINCT village_code, lgd_village_name, UPPER(lgd_block), "
            "UPPER(lgd_district) FROM curated.v_expenditure", [])
        out: dict[str, list[dict]] = {}
        for r in rows:
            n = collapse_ws(str(r["lgd_village_name"] or ""))
            if n and not n.lower().startswith("unresolved"):
                out.setdefault(n.upper(), []).append(
                    {"village_code": r["village_code"], "name": n, "block": r["block"], "district": r["district"]})
        _MGNREGA_VILLAGE_NAMES = out
    return _MGNREGA_VILLAGE_NAMES


async def _mgnrega_longest_village_in(question: str, scheme: str = "MGNREGA"
                                      ) -> "tuple[str, list[dict]] | None":
    """The longest village name of `scheme` (MGNREGA or Focus Plus) that appears
    verbatim (whole words) in the question. Unlike _village_scan_candidates this
    does not split on "&", "INCL" or punctuation: "MAWKOHMIT & MAWKYNSAH",
    "UMTHLONG KYRSEN & KHARJANA" and "LAWRIAT INCL DOMMUSUR" are single villages
    that the extractor split into several places (all-villages QA 2026-09-26);
    Focus Plus wards read "Chobagok - Ward No.3" (2026-09-27)."""
    try:
        names = await (_mgnrega_village_names() if scheme == "MGNREGA" else _scheme_village_names(scheme))
    except Exception:  # noqa: BLE001
        return None
    qu = collapse_ws((question or "").upper())
    best = None
    for n, cands in names.items():
        if len(n) < 3 or n not in qu or (best and len(n) <= len(best[0])):
            continue
        # A 3-letter name (ATS, BIR, KUT, MOT — the only ones) counts only right
        # after a place preposition, so an ordinary word can never be read as a
        # village; "person-days in MOT" found no place at all and answered with a
        # null (all-villages QA 2026-09-26).
        found = False
        for i in _mg_name_offsets(qu, n):
            if len(n) != 3 or _mg_after_place_prep(qu, i):
                found = True
                break
        if found:
            best = (cands[0]["name"], cands)
    return best


async def _mgnrega_village_not_out_of_area(question: str, hit: "dict | None") -> bool:
    """True when an out-of-area edge hit is really a Meghalaya VILLAGE name.

    Three MGNREGA villages carry a place word the edge layer refuses as outside
    Meghalaya: COAL INDIA COLONY ("India"), BURMA and MANIPUR (all-villages QA
    2026-09-26 — "person-days in COAL INDIA COLONY" got "I don't hold all-India
    figures"). A longer name ("COAL INDIA COLONY"), or a question that says
    "village", is the village. A bare "MANIPUR" / "BURMA" is genuinely both, so
    the user is asked. Only for an MGNREGA or unscoped question."""
    if not hit or hit.get("type") != "off_topic":
        return False
    # Focus Plus too: its village BURMA (278981) got the same refusal in the
    # Focus Plus all-villages run (2026-09-27); PMAY-G's MANIPUR (277554) and
    # BURMA (278981) in the PMAY-G all-villages run (2026-09-28). CM Elevate's
    # MANIPUR (277554, Umling block, 29 applications) in its all-villages run the
    # same day (KI-118).
    _sch = _named_or_inferred_schemes(question)
    # Focus Legacy / CM Elevate Legacy too since 2026-10-02 (CM Elevate Legacy's village
    # MANIPUR was refused as the state in the all-villages re-run)
    if _sch not in ([], ["MGNREGA"], ["Focus Plus"], ["PMAY-G"], ["CM Elevate"], ["Focus Legacy"],
                    ["CM Elevate Legacy"]):
        return False
    ql = (question or "").lower()
    m = edge._OUT_OF_AREA.search(ql) or edge._FOREIGN_PLACE.search(ql)
    if not m or _MG_OUTSIDE_OR_STATE(ql):
        return False
    try:
        scanned = await _scan_village_in_question(question, _sch[0] if _sch else "MGNREGA")
    except Exception:  # noqa: BLE001
        return False
    # A comparison of two villages, one of them BURMA: "Which has more completed
    # PMAY-G houses: JEWILGRE or BURMA?" was refused as a question about Burma
    # (PMAY-G officer cases run 2026-10-02) — the scan returns ONE village
    # (JEWILGRE) and the refused word was not part of it. A refused word that is
    # itself a village name, beside another village, is the village.
    word = m.group(0).strip().upper()
    if not scanned or word not in scanned[0].upper():
        try:
            _names = await _scheme_village_names(_sch[0] if _sch else "MGNREGA")
        except Exception:  # noqa: BLE001
            _names = {}
        # beside another village name of the same scheme: a village comparison
        _others = [n for n in _names if n != word and len(n) >= 4
                   and _mg_name_offsets((question or "").upper(), n)]
        if word in _names and _others:
            return True
    if not scanned or m.group(0).strip() not in scanned[0].lower():
        return False
    name, hits = scanned
    if len(name.strip()) > len(m.group(0).strip()) or _MG_VILLAGE_WORD(ql):
        return True
    c = hits[0]
    stem = (question or "").strip().rstrip(" ?.")
    raise ClarificationNeeded(
        f"“{name}” is a village in Meghalaya ({c.get('block')} block, {c.get('district')}) and also "
        "a place outside Meghalaya. Which did you mean?",
        options=[{"label": f"{name} village — {c.get('block')} block, {c.get('district')}",
                  "question": f"{stem}, the village, not another area type"},
                 {"label": f"{name.title()} outside Meghalaya", "question": f"{stem} (the state or country, not the village)"}],
        # Not a scope-pause rule on purpose: each chip must run as a fresh
        # question, so the "outside Meghalaya" one still meets the edge refusal
        # (a resumed pause skips the edge layer).
        rule="village-or-outside-place")


async def _mgnrega_admin_reading_of_village_mention(name: str, scheme: str = "MGNREGA") -> "dict[str, str]":
    """{dimension: canonical} for the MGNREGA block and/or assembly constituency
    that `name` spells EXACTLY, when `name` is not also an exact village name;
    else {}. Used to re-read a village mention that is really a block or a
    constituency (see resolve_entities)."""
    want = collapse_ws(str(name or "")).upper()
    if not want:
        return {}
    hits: dict[str, str] = {}
    for dim in ("block", "assembly_constituency"):
        # Focus Legacy's own catalogue holds no constituency names; its data does (through
        # dim_geography), so "Mairang" offered block / village only (Focus Legacy sheet
        # TC-28, 2026-10-12). Schemes with constituency data read the shared list.
        _names = (collision_canonical_names(scheme, dim)
                  if dim == "assembly_constituency" and scheme in _AC_CAPABLE_SCHEMES
                  else canonical_names(scheme, dim))
        for canon in _names:
            if collapse_ws(str(canon)).upper() == want:
                hits[dim] = canon
                break
    if not hits:
        return {}
    # A village of exactly this name anywhere in Meghalaya (the village index,
    # aliases included) is a village too: "Phulbari" was re-read as the
    # constituency although PHULBARI is a village (place hierarchy sweep
    # 2026-10-21, KI-349). Same-name readings are the level gate's question.
    if settings.PLACE_GAZETTEER:
        from app import entity_resolver as _mg_er
        if _mg_er.is_village_name(name):
            return {}
    try:
        if (await village_names_exact([str(name).strip()])).get(str(name).strip().upper()):
            return {}          # a real village of this name: leave it to the village branch
    except Exception:  # noqa: BLE001 — without the DB check, do not re-read
        return {}
    return hits


def _mgnrega_ac_reading(name: str, schemes: "list[str] | None") -> "str | None":
    """The MGNREGA assembly-constituency name `name` spells EXACTLY (case and
    spacing aside), or None. Exact only — never fuzzy — because it is used to
    rescue a mention that would otherwise be refused as out of scope, and a
    fuzzy hit there would silently answer about a different place."""
    # Every scheme that holds constituency data, not MGNREGA only: Focus Legacy's "How many
    # FOCUS Producer Groups are mapped to North Tura?" was refused as outside Meghalaya
    # (FOCUS sheet TC-28, 2026-10-12).
    if not name or not schemes or len(schemes) != 1 or schemes[0] not in _AC_CAPABLE_SCHEMES:
        return None
    want = collapse_ws(str(name)).upper()
    for canon in collision_canonical_names(schemes[0], "assembly_constituency"):
        if collapse_ws(str(canon)).upper() == want:
            return canon
    return None


# ════ SQL generation guards ═══════════════════════════════════════════════════════════════════════════
# MGNREGA's two facts have NO shared grain — both are at source-row level, many
# rows per village-year on each side. Joining them directly (however sensible
# the ON clause looks: year_key + lgd_block, or geography_key) is a cartesian
# fan-out: every expenditure row pairs with every employment row for the same
# area, and the SUMs come back multiplied. schema_context MGNREGA rule 1 has
# always forbidden it, but the rule alone does not hold under sampling —
# confirmed live 2026-09-17, "compare expenditure and person-days in RERAPARA":
# the generator joined v_expenditure to v_employment and returned ₹367,647 lakh
# / 109,448,220 person-days against a truth of ₹2,450.98 lakh / 986,020. That is
# far more dangerous than the missing-column error it replaced, because it runs
# clean and the numbers look plausible. The correct shape is one CTE per fact,
# each aggregated independently, then combined.
_MGNREGA_FACT_OBJECTS = (
    "v_employment", "fact_mgnrega_employment",
    "v_expenditure", "fact_mgnrega_expenditure",
)
_EMPLOYMENT_OBJECTS = frozenset({"v_employment", "fact_mgnrega_employment"})
_EXPENDITURE_OBJECTS = frozenset({"v_expenditure", "fact_mgnrega_expenditure"})


# ── small tree readers shared by the MGNREGA guards below ───────────────────
def _mg_names(sql_or_tree) -> "set[str]":
    """Every identifier in the query, lower-cased: columns, aliases, tables,
    CTE names (string literals and comments are not identifiers)."""
    return {str(i.this or "").lower() for t in sql_ast._trees(sql_or_tree) for i in t.find_all(exp.Identifier)}


def _mg_unwrap(node: "exp.Expression | None") -> "exp.Expression | None":
    """Strip the wrappers that leave a value's meaning unchanged here: casts
    (::numeric), parentheses."""
    while isinstance(node, (exp.Cast, exp.TryCast, exp.Paren)) and node.this is not None:
        node = node.this
    return node


def _mg_measure(node: "exp.Expression | None") -> "str | None":
    """The MGNREGA integer measure a (cast / parenthesised) column names, else None."""
    node = _mg_unwrap(node)
    if isinstance(node, exp.Column) and node.name.lower() in _MGNREGA_INT_MEASURES:
        return node.name
    return None


def _mg_sum_ratio(a: exp.Column, b: exp.Column) -> exp.Expression:
    """SUM(a)::numeric / NULLIF(SUM(b), 0) as a tree."""
    return exp.Div(
        this=exp.Cast(this=exp.Sum(this=a.copy()), to=exp.DataType.build("numeric")),
        expression=exp.Nullif(this=exp.Sum(this=b.copy()), expression=exp.Literal.number(0)))


def _mg_is_zero(node: "exp.Expression | None") -> bool:
    node = _mg_unwrap(node)
    if not isinstance(node, exp.Literal) or node.is_string:
        return False
    try:
        return float(node.this) == 0
    except ValueError:
        return False


# ── MGNREGA use-case fixes (QA 2026-09-26, KI-041 … KI-048) ─────────────────
# Every MGNREGA employment measure is a BIGINT, and Postgres divides two
# integers as integers: ROUND(SUM(person_days) / NULLIF(SUM(households_employed),
# 0), 2) returned 38.00 for East Khasi Hills where the true figure is
# 1,632,188 / 42,770 = 38.16 (DATA-021, KI-044). The prompt rule (schema_context
# MGNREGA rule 8) asks for a cast; this rewrite guarantees it.
_MGNREGA_INT_MEASURES = (
    "person_days", "households_employed", "persons_employed",
    "households_completed_100_days", "job_cards_issued_total", "women_employment_provided",
)


def _mgnrega_numeric_division(schemes: list[str], sql: str) -> str:
    """Cast the numerator of SUM(<integer measure>) / … to numeric (MGNREGA only).
    A numerator already cast is left alone, so the rewrite is idempotent."""
    if "MGNREGA" not in schemes or not sql:
        return sql

    def fn(tree):
        for div in list(tree.find_all(exp.Div)):
            num = div.this
            if isinstance(num, exp.Sum) and _mg_measure(num.this) and isinstance(num.this, exp.Column):
                num.replace(exp.Cast(this=num.copy(), to=exp.DataType.build("numeric")))
        return None
    return sql_ast.transform(sql, fn)


# "Average person-days per employment household in West Garo Hills" came back as
# AVG(person_days / NULLIF(households_employed, 0)) = 71.33 — the mean of each
# village-year's own ratio, which weights a 3-household village like a
# 3,000-household one. The question's expected result is total person-days ÷
# total households = 67.03 (DATA-021, test run 2026-10-06). An average of a
# ratio between two additive measures is always the ratio of their sums.
#
# The same question also came back as AVG(person_days)::numeric /
# NULLIF(SUM(households_employed), 0) = 0.19 — one row's mean over the whole
# district's households — where SUM / SUM is 58.51 (South West Khasi Hills FY
# 2024-25, MGNREGA sheet DATA-021 run 2026-10-09). A mixed AVG / SUM (or AVG /
# AVG) of two additive measures is rewritten to the ratio of the sums as well.
_MGNREGA_EXP_COMPONENTS = [
    (Matcher(NotAfter(_mg_sp("unskilled", W("wage", prefix=True)), "semi")), "unskilled_wage_exp"),
    (Matcher(_mg_sp(Joined("semi", "skilled"), W("wage", prefix=True))), "semi_skilled_wage_exp"),
    (Matcher(Alt(_mg_sp(("material", "materials"), Alt(W("exp", "cost", "spend", prefix=True))),
                 _mg_sp("expenditure", "on", ("material", "materials")))),
     "material_exp"),
    (Matcher(_mg_sp(W("admin", prefix=True), W("exp", "cost", prefix=True))), "admin_total_exp"),
    (Matcher(_mg_sp("tax", W("exp", prefix=True))), "tax_exp"),
]


def _mgnrega_job_cards_latest_year(schemes: list[str], sql: str, *, question: str = "",
                                   resolved: "dict | None" = None) -> str:
    """SUM(job_cards_issued_total) with no year filter -> pinned to the year asked.
    Job cards are a STOCK (held at year end); summing years answered 2,128,714
    for the 520,999 cards held (user session 2026-10-13). The resolved year (or
    years) is pinned when the model dropped it; an all-years question is left to
    the repair guard, which asks for one row per year; only a question with no
    year anywhere falls back to the latest year — FY 2025-26 was pinned for every
    job-card question whatever was asked (MGNREGA sheet DATA-007, 2026-10-21).
    Simple one-SELECT queries without OR only; anything else is left to the
    repair guard."""
    if "MGNREGA" not in (schemes or []) or not sql:
        return sql
    tree = sql_ast.parse_one(sql)
    if tree is None or not isinstance(tree, exp.Select):
        return sql
    if not any(isinstance(s.this, exp.Column) and s.this.name.lower() == "job_cards_issued_total"
               for s in tree.find_all(exp.Sum)):
        return sql
    names = _mg_names(tree)
    if "year_key" in names or any(n.startswith("financial_year") for n in names) \
            or len(sql_ast.selects(tree)) != 1 or tree.find(exp.Or) is not None:
        return sql
    years = _mg_resolved_years(resolved or {})
    if years:
        pin = f"year_key = {years[0]}" if len(years) == 1 else f"year_key IN ({', '.join(map(str, years))})"
        out = sql_ast.add_condition(sql, pin)
        logger.info("job cards pinned to the year asked: %s", out.replace("\n", " "))
        return out
    if _ALL_YEARS_CUE.search(question or ""):
        return sql
    out = sql_ast.add_condition(sql, _JOB_CARD_PIN)
    logger.info("job cards pinned to the latest year (no year asked): %s", out.replace("\n", " "))
    return out


# The MGNREGA fact tables carry only geography_key; the place columns and the FY
# labels are on their views. Asked to add entity_type <> 'Unresolved' to a village
# list, the repair model moved the query from curated.v_employment to
# curated.fact_mgnrega_employment and failed "column f.lgd_village_name does not
# exist" on every repair ("Which villages in Mawryngkneng constituency received
# employment during 2025-26?", MGNREGA sheet DATA-014, 2026-10-21). A one-table read
# of a fact that names a view-only column and no fact-only one reads the view.
_MG_VIEW_ONLY_COLUMNS = frozenset({"village_code", "lgd_village_name", "lgd_block", "lgd_district", "entity_type",
                                   "on_roster", "financial_year", "financial_year_short", "start_year", "year_note"})
_MG_FACT_ONLY_COLUMNS = frozenset({"alias_key", "benefit_to_households", "admin_recurring_exp",
                                   "admin_non_recurring_exp", "raw_id", "source_row_num", "batch_id",
                                   "source_system", "ingested_at"})
_MG_FACT_VIEW = {"fact_mgnrega_employment": "curated.v_employment",
                 "fact_mgnrega_expenditure": "curated.v_expenditure"}


def _mgnrega_fact_to_view(schemes: list[str], sql: str) -> str:
    if "MGNREGA" not in (schemes or []) or not sql:
        return sql
    read = sql_ast.tables(sql)
    if len(read) != 1 or not read <= set(_MG_FACT_VIEW):
        return sql
    cols = sql_ast.columns(sql)
    if not (cols & _MG_VIEW_ONLY_COLUMNS) or (cols & _MG_FACT_ONLY_COLUMNS):
        return sql
    out = sql_ast.rename_tables(sql, _MG_FACT_VIEW)
    logger.info("MGNREGA fact table read for view-only columns -> its view: %s", out.replace("\n", " "))
    return out


# The c11 guard's demand for a village ranking, made here instead of by a repair:
# the round trip was where DATA-014 went wrong (see _mgnrega_fact_to_view), and the
# condition is fixed text. One MGNREGA view, single SELECT, no CTE only.
def _mgnrega_village_rank_placeholders(question: str, schemes: list[str], sql: str) -> str:
    if "MGNREGA" not in (schemes or []) or not sql:
        return sql
    read = sql_ast.tables(sql)
    if len(read) != 1 or not read <= {"v_employment", "v_expenditure"} \
            or sql_ast.has_cte(sql) or len(sql_ast.selects(sql)) != 1:
        return sql
    if not (sql_ast.groups_by(sql, "lgd_village_name") and _vr_has_order_by(sql)
            and not _vr_mentions_unresolved(sql) and _C11_RANKING_ASK.search(question or "")):
        return sql
    out = sql_ast.add_condition(sql, "entity_type <> 'Unresolved'")
    logger.info("MGNREGA village ranking: placeholder rows excluded: %s", out.replace("\n", " "))
    return out


# "How many households received employment in Amlarem during 23-24?" (block chip)
# was answered from COUNT(DISTINCT village_code) … AND households_employed > 0 —
# the villages that had employment (79), not the households (6,917); WAPUNG's 46
# villages were then called "46 households" (MGNREGA sheet DATA-016, runs
# 2026-10-21; the few-shot "How many villages received employment in each
# district" is worded almost the same). A households / persons count that names
# no village, read as a village count, is rewritten to the SUM it asked for.
_MG_COUNT_ASK = Matcher(Alt(Seq("how", "many"), Seq(W("number", "count", "no", "total"), Opt("of"))))
_MG_COUNTED_UNIT = (
    (Matcher(W("household", "households")), "households_employed"),
    (Matcher(W("person", "persons", "people", "workers", "individuals")), "persons_employed"),
)
_MG_NOT_A_UNIT_COUNT = Matcher(Alt(
    W("village", "villages", "which", "women", "woman", "completed", "100", "hundred", "percentage", "percent",
      "share", "average", "avg"),
    Joined("job", ("card", "cards")), Joined("person", ("day", "days")),
))


def _mgnrega_unit_count_not_villages(question: str, schemes: list[str], sql: str) -> str:
    if "MGNREGA" not in (schemes or []) or not sql:
        return sql
    q = question or ""
    if not _MG_COUNT_ASK.search(q) or _MG_NOT_A_UNIT_COUNT.search(q):
        return sql
    cols = [col for cue, col in _MG_COUNTED_UNIT if cue.search(q)]
    if len(cols) != 1:
        return sql
    col = cols[0]
    read = sql_ast.tables(sql)
    if len(read) != 1 or not read <= _EMPLOYMENT_OBJECTS or sql_ast.has_cte(sql) \
            or len(sql_ast.selects(sql)) != 1:
        return sql

    def is_village_count(e: exp.Expression) -> bool:
        e = e.this if isinstance(e, exp.Alias) else e
        return isinstance(e, exp.Count) and isinstance(e.this, exp.Distinct) \
            and any(isinstance(c, exp.Column) and c.name.lower() == "village_code" for c in e.this.expressions)

    tree = sql_ast.parse_one(sql)
    sel = sql_ast.outer_select(tree) if tree is not None else None
    if sel is None or not any(is_village_count(e) for e in sel.expressions) \
            or any(isinstance(e, exp.Sum) for x in sel.expressions for e in x.find_all(exp.Sum)):
        return sql
    new = [exp.alias_(exp.Sum(this=exp.column(col)), col) if is_village_count(e) else e for e in sel.expressions]
    sel.set("expressions", new)
    out = sql_ast.to_sql(tree)

    def is_positive_filter(c: exp.Expression) -> bool:      # "households_employed > 0": the village-count filter
        return isinstance(c, (exp.GT, exp.GTE, exp.NEQ)) and sql_ast._is_column(c.this, {col}) \
            and isinstance(c.expression, exp.Literal) and str(c.expression.this) in ("0", "1")
    out = sql_ast.remove_conditions(out, is_positive_filter)
    logger.info("MGNREGA %s count read as a village count -> SUM(%s): %s", col.split("_")[0], col,
                out.replace("\n", " "))
    return out


# entity_type on the MGNREGA views is the ROW's type — every row is 'Village' (or the
# 'Unresolved' placeholder) — not the level of the area asked about. The block chip
# resumes "…, the block, not another area type", and the 30B added
# entity_type = 'Block': SUM over no rows, "the data available doesn't cover …" for
# AMLAREM / LUMSHNONG / MYLLIEM / RESUBELPARA / RONGARA households and BAJENGDOBA
# expenditure (MGNREGA sheet DATA-016 / DATA-003, runs 2026-10-21). The block /
# district / constituency filter does the scoping; the level filter is dropped.
_MG_ROW_TYPES = frozenset({"village", "unresolved"})


def _mgnrega_drop_area_level_entity_type(schemes: list[str], sql: str) -> str:
    if "MGNREGA" not in (schemes or []) or not sql:
        return sql
    read = sql_ast.tables(sql)
    if not read or not read <= (_EMPLOYMENT_OBJECTS | _EXPENDITURE_OBJECTS):
        return sql

    def is_level_filter(c: exp.Expression) -> bool:
        if not isinstance(c, exp.EQ) or not sql_ast._is_column(c.this, {"entity_type"}):
            return False
        vals = sql_ast._string_values(c.expression)
        return bool(vals) and all(v.strip().lower() not in _MG_ROW_TYPES for v in vals)
    out = sql_ast.remove_conditions(sql, is_level_filter)
    if out != sql:
        logger.info("MGNREGA entity_type area-level filter dropped: %s", out.replace("\n", " "))
    return out


def _mg_resolved_years(resolved: dict) -> "list[int]":
    """The financial years (year_key start years) the resolver pinned, sorted."""
    yk = resolved.get("year_key")
    raw = resolved.get("year_key_list") or (list(yk) if isinstance(yk, (list, tuple, set))
                                           else [yk] if yk not in (None, "") else [])
    out = set()
    for y in raw:
        try:
            out.add(int(y))
        except (TypeError, ValueError):
            continue
    return sorted(out)


# households_employed / persons_employed are per-YEAR tallies with no household or person
# id, so a sum over several financial years counts a household again every year it
# worked. "How many beneficiaries in MGNREGA, all years" was answered "1,494,437
# beneficiary households" — four years' tallies presented as distinct households
# (errors.md case 3, KI-040, D-048). The user wants one combined all-years figure
# (2026-10-13), so the sum stays and is labelled for what it is.
_MG_PEOPLE_TALLIES = {"households_employed": "household_years", "persons_employed": "person_years"}
_MG_YEAR_COLS = ("year_key", "financial_year_short", "financial_year", "start_year")


def _mg_one_year(tree: exp.Expression) -> bool:
    """The query is pinned to a single financial year (an equality on a year column,
    a literal or a subquery such as MAX(year_key))."""
    for node in sql_ast.filter_conditions(tree, *_MG_YEAR_COLS):
        if isinstance(node, exp.EQ):
            return True
        if isinstance(node, exp.In) and len(node.expressions) == 1:
            return True
    return False


def _mg_is_sum_of(node: "exp.Expression | None", col: str) -> bool:
    node = _mg_unwrap(node)
    inner = _mg_unwrap(node.this) if isinstance(node, exp.Sum) else None
    return isinstance(inner, exp.Column) and inner.name.lower() == col


def _mgnrega_defined_shape(schemes: list[str], sql: str) -> bool:
    """The query returns a measure exactly as a business definition prescribes
    (D-048): men_employed = SUM(persons_employed) - SUM(women_employment_provided),
    or a multi-year sum labelled household_years / person_years. The 30B verifier
    rejected the men query on all four attempts ("Check 3: … does not correctly
    compute the number of men") and the answer became "couldn't build a working
    query" (live 2026-10-16, errors.md case 1)."""
    if "MGNREGA" not in (schemes or []) or not sql:
        return False
    tree = sql_ast.parse_one(sql)
    sel = sql_ast.outer_select(tree) if tree is not None else None
    if sel is None:
        return False
    for item in sel.expressions:
        if not isinstance(item, exp.Alias):
            continue
        name, expr = item.alias.lower(), _mg_unwrap(item.this)
        if name == "men_employed" and isinstance(expr, exp.Sub) \
                and _mg_is_sum_of(expr.this, "persons_employed") \
                and _mg_is_sum_of(expr.expression, "women_employment_provided"):
            return True
        if (name, True) in (("household_years", _mg_is_sum_of(expr, "households_employed")),
                            ("person_years", _mg_is_sum_of(expr, "persons_employed"))):
            return True
    return False


# Verifier complaints about HOW such a defined measure is aggregated are discarded;
# complaints about anything else (a filter, a place, a year) still go to repair.
_MG_DEFINITION_COMPLAINT = Matcher(Alt(
    W("sum", "sums", "summed", "summing", "aggregation", "aggregations", "aggregate", "aggregated",
      "derived", "difference", "subtract", "subtracting", "subtraction", "men", "male",
      "beneficiary", "beneficiaries", "household", "households", "count", "counts", "metric", "metrics"),
    W("aggregat", prefix=True)))


def _mgnrega_definition_complaint_is_false(schemes: list[str], sql: str, issue: str) -> bool:
    return bool(issue) and _mgnrega_defined_shape(schemes, sql) \
        and _MG_DEFINITION_COMPLAINT.search(issue) is not None


def _mgnrega_people_years_alias(schemes: list[str], sql: str) -> str:
    """An outer SUM(households_employed) / SUM(persons_employed) over more than one
    financial year (no single-year filter, no year GROUP BY) -> aliased
    household_years / person_years, so neither the answer nor its reader can take it
    for a count of distinct households or persons (the answer note explains it).
    Simple outer SELECTs only; an alias already naming years is left alone."""
    if "MGNREGA" not in (schemes or []) or not sql:
        return sql
    tree = sql_ast.parse_one(sql)
    sel = sql_ast.outer_select(tree) if tree is not None else None
    if sel is None or sql_ast.groups_by(tree, *_MG_YEAR_COLS) or _mg_one_year(tree):
        return sql
    taken = set(sql_ast.output_names(tree))
    renames: dict[str, str] = {}
    items = list(sel.expressions)
    changed = False
    for k, item in enumerate(items):
        inner = item.this if isinstance(item, exp.Alias) else item
        if not isinstance(inner, exp.Sum):
            continue
        col = _mg_unwrap(inner.this)
        new = _MG_PEOPLE_TALLIES.get(col.name.lower()) if isinstance(col, exp.Column) else None
        old = ((item.alias if isinstance(item, exp.Alias) else "") or "").lower()
        if not new or "year" in old or new in taken:
            continue
        items[k] = exp.alias_(inner.copy(), new)
        taken.add(new)
        changed = True
        if old:
            renames[old] = new
    if not changed:
        return sql
    sel.set("expressions", items)
    order = sel.args.get("order")
    if order is not None and renames:
        for c in order.find_all(exp.Column):
            if not c.table and c.name.lower() in renames:
                c.set("this", exp.to_identifier(renames[c.name.lower()]))
    out = sql_ast.to_sql(tree)
    logger.info("MGNREGA multi-year household/person sum labelled as *_years: %s", out)
    return out


def _mg_avg_ratio_replacement(node: exp.Expression) -> "exp.Expression | None":
    """The SUM / SUM tree for an AVG-of-a-ratio or mixed AVG/SUM ratio node, else None."""
    # AVG(a / b), AVG(a::numeric / NULLIF(b, 0)), AVG(CAST(a AS numeric) / b)
    if isinstance(node, exp.Avg):
        inner = _mg_unwrap(node.this)
        if isinstance(inner, exp.Div):
            den = _mg_unwrap(inner.expression)
            if isinstance(den, exp.Nullif) and _mg_is_zero(den.expression):
                den = den.this
            a, b = _mg_unwrap(inner.this), _mg_unwrap(den)
            if _mg_measure(a) and _mg_measure(b):
                return _mg_sum_ratio(a, b)
        return None
    # AVG(a) / SUM(b), SUM(a) / AVG(b), AVG(a) / AVG(b) — numerator possibly cast,
    # denominator possibly NULLIF(…, 0). SUM / SUM is already right.
    if isinstance(node, exp.Div):
        num = _mg_unwrap(node.this)
        den = node.expression
        if isinstance(den, exp.Nullif) and _mg_is_zero(den.expression):
            den = den.this
        if isinstance(num, (exp.Avg, exp.Sum)) and isinstance(den, (exp.Avg, exp.Sum)) \
                and isinstance(num.this, exp.Column) and isinstance(den.this, exp.Column) \
                and _mg_measure(num.this) and _mg_measure(den.this) \
                and not (isinstance(num, exp.Sum) and isinstance(den, exp.Sum)):
            return _mg_sum_ratio(num.this, den.this)
    return None


def _mgnrega_avg_of_ratio(schemes: list[str], sql: str) -> str:
    """AVG(a / b) over two MGNREGA measures -> SUM(a)::numeric / NULLIF(SUM(b), 0);
    likewise AVG(a) / SUM(b), SUM(a) / AVG(b) and AVG(a) / AVG(b)."""
    if "MGNREGA" not in schemes or not sql:
        return sql

    def fn(tree):
        for node in list(tree.find_all(exp.Avg, exp.Div)):
            if node.root() is not tree:
                continue                      # inside a node already replaced
            new = _mg_avg_ratio_replacement(node)
            if new is not None:
                node.replace(new)
        return None
    out = sql_ast.transform(sql, fn)
    if out != sql:
        logger.info("MGNREGA: AVG of a per-row ratio rewritten as the ratio of the sums")
    return out


# MGNREGA money is natively LAKH. "ROUND(SUM(unskilled_wage_exp + semi_skilled_
# wage_exp) / 100.0, 2) AS wages_lakh" divided a lakh figure by 100 and still
# called it lakh: JAKREM's 219.48 lakh of wages was reported as "2.19 lakh"
# (MGNREGA QA 2026-09-26, DATA-023 run 2). _crore_conversion_for_single_village
# only fires when the SQL says "crore", so a ÷100 under a *_lakh alias slipped
# through. The alias states the unit the composer will print, so the ÷100 is
# the error — drop it.
_MGNREGA_MONEY_COLS = frozenset({"total_exp", "unskilled_wage_exp", "semi_skilled_wage_exp",
                                 "material_exp", "tax_exp", "admin_total_exp"})


def _mg_reads_money(sql_or_tree) -> bool:
    """True when the query names a MGNREGA money column (as a column or alias)."""
    return bool(_mg_names(sql_or_tree) & _MGNREGA_MONEY_COLS)


def _mg_says_crore(sql_or_tree) -> bool:
    """True when a column / alias of the query is in crore (…_crore)."""
    return any("crore" in n for n in _mg_names(sql_or_tree))


def _mgnrega_lakh_not_divided(schemes: list[str], sql: str) -> str:
    """Remove a ÷100 applied to MGNREGA money whose alias still says lakh."""
    if "MGNREGA" not in schemes or not sql:
        return sql

    def fn(tree):
        for alias in list(tree.find_all(exp.Alias)):
            if "lakh" not in (alias.alias or "").lower():
                continue
            node = _mg_unwrap(alias.this)
            if isinstance(node, exp.Round):
                node = _mg_unwrap(node.this)
            if not isinstance(node, exp.Div):
                continue
            den = _mg_unwrap(node.expression)
            num = node.this
            while isinstance(num, exp.Paren):
                num = num.this
            total = _mg_unwrap(num)               # SUM(...) or SUM(...)::numeric
            if isinstance(den, exp.Literal) and not den.is_string and _mg_is_hundred(den.this) \
                    and isinstance(total, exp.Sum) \
                    and {c.name.lower() for c in total.find_all(exp.Column)} & _MGNREGA_MONEY_COLS:
                node.replace(num.copy())
        return None
    return sql_ast.transform(sql, fn)


def _mg_is_hundred(text: str) -> bool:
    try:
        return float(text) == 100
    except ValueError:
        return False


_RECEIVED_EMPLOYMENT_MATCH = Matcher(Alt(
    _mg_sp(Alt(W("receiv", prefix=True), W("got", "get", "provided", "given")), Opt("any"), "employment"),
    _mg_sp("were", "employed")))


def _mgnrega_village_list_no_limit(question: str, schemes: list[str], sql: str) -> str:
    if schemes != ["MGNREGA"] or not sql or not _VILLAGE_LIST_ASK_MATCH.search(question or ""):
        return sql
    out = sql
    # A row-level list with no GROUP BY / DISTINCT names a village once per source
    # row: Mawryngkneng FY 2025-26 listed 32 rows for 28 villages (MGNREGA sheet
    # DATA-014, run 2026-10-09). Each village is named once.
    tree = sql_ast.parse_one(sql)
    if isinstance(tree, exp.Select) and not (tree.args.get("with_") or tree.args.get("with")) \
            and not sql_ast.has_group_by(tree) \
            and not any(s.args.get("distinct") for s in sql_ast.selects(tree)) \
            and not sql_ast.has_aggregate(tree, "sum", "count", "avg", "max", "min") \
            and _order_by_cols_selected(out):
        out = sql_ast.transform(sql, lambda t: t.set("distinct", exp.Distinct()))
        if out != sql:
            logger.info("MGNREGA: 'which villages' row list made DISTINCT — each village once")
    if _TOP_N_ASK_MATCH.search(question or ""):
        return out
    lim = sql_ast.outer_limit(out)
    trimmed = sql_ast.set_limit(out, None) if lim is not None and lim >= 0 else out
    if trimmed != out:
        logger.info("MGNREGA: 'which villages' list — model LIMIT dropped, the whole list is the answer")
    return trimmed


def _mg_keeps_positive_only(sql: str) -> bool:
    """A HAVING clause, or a `> 0` condition, anywhere in the query."""
    for t in sql_ast.parse(sql):
        if t.find(exp.Having) is not None:
            return True
        if any(_mg_is_zero(g.expression) for g in t.find_all(exp.GT)):
            return True
    return False


def _mgnrega_village_list_issue(question: str, schemes: list[str], sql: str) -> "str | None":
    """Repair instruction for a MGNREGA "which villages…" query that lists no
    village names, or that keeps zero-employment villages; else None."""
    if schemes != ["MGNREGA"] or not _VILLAGE_LIST_ASK_MATCH.search(question or ""):
        return None
    if "lgd_village_name" not in _mg_names(sql or ""):
        return ("this question asks WHICH villages, but the query returns no village names. "
                "Select lgd_village_name AND village_code, GROUP BY both, include the metric "
                "(e.g. SUM(persons_employed) AS persons_employed), and ORDER BY it DESC. Keep "
                "every filter exactly as it was.")
    if _RECEIVED_EMPLOYMENT_MATCH.search(question) and not _mg_keeps_positive_only(sql or ""):
        return ("this question asks which villages RECEIVED employment, but the query also "
                "lists villages whose employment is zero (they have rows with 0 persons). Add "
                "HAVING SUM(persons_employed) > 0 after the GROUP BY. Keep every other clause "
                "exactly as it was.")
    return None


def _mgnrega_comparison_without_figures(question: str, schemes: list[str],
                                        rows: list[dict]) -> bool:
    """True when a MGNREGA comparison question's result holds no number at all."""
    if schemes != ["MGNREGA"] or not rows or not _QUANTITY_COMPARISON_MATCH.search(question or ""):
        return False
    return not any(_as_number(v) is not None for r in rows for v in r.values())


# ════ fixed-shape queries and answers ═════════════════════════════════════════════════════════════════
# ── MGNREGA deterministic queries ───────────────────────────────────────────
# "How much was spent and how many person-days in JAKREM" needs one CTE per
# fact (rule 1). The 30B model kept writing the join; the join guard fired; the
# 4B verifier then flagged the correct two-CTE rewrite as a "prohibited join";
# the next repair moved to v_district_year_summary, which has no village or
# block column — and after three repairs the question fell back to the
# reference documents ("no data for the JAKREM scheme", DATA-028) or said
# "couldn't build a working query" (DATA-029, 4 of 5 runs). The query's shape is
# fixed, so it is built here from the resolved filters and executed
# parameter-bound — no model call, no verifier.
_MG_SPEND_WORD_MATCH = Matcher(Alt(W("spend", prefix=True),
                                W("spent", "expenditure", "expense", "expenses", "cost", "costs")))
_MG_EMPLOYMENT_WORD_MATCH = Matcher(Alt(
    Joined("person", _MG_DAYS), Joined("man", _MG_DAYS), W("employment"),
    _mg_sp(("household", "households", "person", "persons"), "employed")))
# Anything that needs a different query shape stays with the SQL generator
# (a "%" sign too — see _mg_combined_excluded).
_MG_COMBINED_EXCLUDE_MATCH = Matcher(Alt(
    W("each", "every", "per", "by", "wise", "breakdown", "trend", "top", "highest", "lowest", "most", "least",
      "which", "wage", "wages", "material", "materials", "unskilled", "tax", "administrative", "admin",
      "average", "avg", "ratio", "share", "women"),
    W("rank", "percent", prefix=True), Joined("semi", "skilled"),
    _mg_sp("job", ("card", "cards")), _mg_sp("100", _MG_DAYS)))
_MG_HOUSEHOLD_WORD = Matcher(W("household", "households"))
# persons / people / workers, but not "person-days"
_MG_PERSON_WORD = Matcher(NotBefore(W("person", "persons", "people", "worker", "workers"), W("day", "days")))


def _mg_combined_excluded(q: str) -> bool:
    return "%" in q or bool(_MG_COMBINED_EXCLUDE_MATCH.search(q))
_MG_GEO_FILTERS = (("village_code", "village_code"), ("block", "lgd_block"),
                   ("district", "lgd_district"), ("year_key", "year_key"))


def _mgnrega_filters(resolved: dict, *, allow_ac: bool = False
                     ) -> "tuple[list[str], list[object], list[str]] | None":
    """(parameterised WHERE parts, params, literal WHERE parts for display) from
    the resolved single-valued filters, or None when a filter is multi-valued or
    needs another shape (assembly constituency, lists)."""
    if any(resolved.get(k) for k in ("village_code_list", "block_list", "district_list")):
        return None
    if resolved.get("assembly_constituency") and not allow_ac:
        return None
    where, params, shown = [], [], []
    pairs = list(_MG_GEO_FILTERS)
    if allow_ac:
        pairs.append(("assembly_constituency", "assembly_constituency_name"))
    for key, col in pairs:
        v = resolved.get(key)
        if v is None or v == "":
            continue
        if isinstance(v, (list, tuple, dict, set)):
            return None
        params.append(v)
        if isinstance(v, str):
            where.append(f"UPPER({col}) = UPPER(${len(params)})")
            shown.append(f"UPPER({col}) = UPPER('{v.replace(chr(39), chr(39) * 2)}')")
        else:
            where.append(f"{col} = ${len(params)}")
            shown.append(f"{col} = {int(v)}")
    return where, params, shown


def _mgnrega_combined_facts_query(question: str, schemes: list[str], resolved: dict
                                  ) -> "tuple[str, list, str] | None":
    """(parameterised SQL, params, display SQL) for a single-area MGNREGA
    "expenditure AND person-days/employment" question, else None."""
    q = question or ""
    if schemes != ["MGNREGA"] or not (_MG_SPEND_WORD_MATCH.search(q) and _MG_EMPLOYMENT_WORD_MATCH.search(q)):
        return None
    if _mg_combined_excluded(q):
        return None
    f = _mgnrega_filters(resolved)
    if f is None:
        return None
    where, params, shown = f
    emp_cols = ["SUM(person_days) AS person_days"]
    if _MG_HOUSEHOLD_WORD(q):
        emp_cols.append("SUM(households_employed) AS households_employed")
    if _MG_PERSON_WORD(q):
        emp_cols.append("SUM(persons_employed) AS persons_employed")
    emp_names = [c.rsplit(" AS ", 1)[1] for c in emp_cols]

    def build(w: list[str]) -> str:
        wh = (" WHERE " + " AND ".join(w)) if w else ""
        return ("WITH exp AS (SELECT ROUND(SUM(total_exp)::numeric, 2) AS total_expenditure_lakh "
                f"FROM curated.v_expenditure{wh}),\n"
                f"     emp AS (SELECT {', '.join(emp_cols)} FROM curated.v_employment{wh})\n"
                f"SELECT exp.total_expenditure_lakh, {', '.join('emp.' + n for n in emp_names)}\n"
                "FROM exp CROSS JOIN emp")
    return build(where), params, build(shown)


# "Give me the expenditure breakdown for <area> during <FY>" — every component
# and the total. Left to the model it sometimes merged unskilled + semi-skilled
# into one "wages" figure (Myriem FY 2023-24: "22.10 lakh in wages"; MGNREGA
# sheet DATA-022, run 2026-10-09), dropping the components the case asks for.
_MG_BREAKDOWN_MATCH = Matcher(Alt(W("breakdown", "component", "components", "split"),
                               Joined("break", "up"), Joined("head", "wise")))
_MG_BREAKDOWN_COLS = (("unskilled_wage_exp", "unskilled wages"), ("semi_skilled_wage_exp", "semi-skilled wages"),
                      ("material_exp", "materials"), ("tax_exp", "tax"), ("admin_total_exp", "administrative"),
                      ("total_exp", "total"))
_MG_BREAKDOWN_EXCLUDE_MATCH = Matcher(Alt(
    W("each", "every", "by", "trend", "top", "highest", "lowest", "which", "compare", "vs", "versus"),
    W("rank", prefix=True), Joined(("district", "block", "village", "year"), "wise")))
class _MgSqlShape:
    """Recognises one of the fixed MGNREGA query shapes on the parsed tree.
    `.search(sql)` keeps the call shape the callers already use
    (True when the SQL has the shape, else None)."""

    def __init__(self, test) -> None:
        self._test = test

    def search(self, sql: "str | None") -> "bool | None":
        return any(self._test(t) for t in sql_ast.parse(sql)) or None

    __call__ = search


def _mg_outputs(*names: str):
    """A test: the statement's outer SELECT outputs every one of `names`."""
    return lambda t: set(names) <= set(sql_ast.output_names(t))


def _mg_combined_shape(tree: exp.Expression) -> bool:
    """WITH exp AS (…), emp AS (…) … FROM exp CROSS JOIN emp."""
    return "exp" in sql_ast.cte_names(tree) and any(
        str(j.args.get("kind") or "").upper() == "CROSS" and isinstance(j.this, exp.Table)
        and j.this.name.lower() == "emp" for j in tree.find_all(exp.Join))


_MG_BREAKDOWN_SQL_SHAPE = _MgSqlShape(_mg_outputs("unskilled_wages_lakh", "total_lakh"))


def _mgnrega_breakdown_query(question: str, schemes: list[str], resolved: dict
                             ) -> "tuple[str, list, str] | None":
    q = question or ""
    if schemes != ["MGNREGA"] or not _MG_BREAKDOWN_MATCH.search(q) or not _MG_SPEND_WORD_MATCH.search(q):
        return None
    if _MG_EMPLOYMENT_WORD_MATCH.search(q) or _MG_BREAKDOWN_EXCLUDE_MATCH.search(q):
        return None                      # "by district" / with employment: the model path
    f = _mgnrega_filters(resolved)
    if f is None:
        return None
    where, params, shown = f
    sel = ", ".join(f"ROUND(SUM({c})::numeric, 2) AS {_mg_breakdown_alias(c)}" for c, _l in _MG_BREAKDOWN_COLS)

    def build(w: list[str]) -> str:
        return f"SELECT {sel} FROM curated.v_expenditure" + ((" WHERE " + " AND ".join(w)) if w else "")
    return build(where), params, build(shown)


def _mg_breakdown_alias(col: str) -> str:
    return {"unskilled_wage_exp": "unskilled_wages_lakh", "semi_skilled_wage_exp": "semi_skilled_wages_lakh",
            "material_exp": "materials_lakh", "tax_exp": "tax_lakh", "admin_total_exp": "administrative_lakh",
            "total_exp": "total_lakh"}[col]


def _mgnrega_breakdown_answer(row: dict, display: dict) -> "str | None":
    vals = [(label, _as_number(row.get(_mg_breakdown_alias(c)))) for c, label in _MG_BREAKDOWN_COLS]
    if any(v is None for _l, v in vals):
        return None
    place = (f"{display['village']} village" if display.get("village") else
             f"{display['block']} block" if display.get("block") else display.get("district") or "Meghalaya")
    year = display.get("year")
    total = vals[-1][1]
    lines = [f"- **{label.capitalize()}** — {float(v):,.2f} lakh" for label, v in vals[:-1]]
    return (f"MGNREGA expenditure breakdown for {place}{' in ' + year if year else ''}: "
            f"**{float(total):,.2f} lakh** in total.\n\n" + "\n".join(lines))


# "Was more spent on wages or materials in <area>?" — DATA-023. Left to the
# model, a village with no expenditure rows for the year came back as a CASE
# label with no figures, every repair kept it, and the officer got "couldn't
# build a working query" (Upper / Lower Wadagokgre FY 2024-25, MGNREGA
# all-villages run 2026-10-09). Both figures are read here, for one area.
class _MgNearPair:
    """A word from `left`, then within 20 characters a joining word ("or", "vs",
    "versus", "than", "and"), then within 10 characters a word from `right` (either
    order), with no "?" or "." in between — "wages or materials", "wages spent
    than materials". `.search(text)` is truthy on a hit."""

    _JOIN = ("or", "vs", "versus", "than", "and")

    def __init__(self, left: tuple, right: tuple) -> None:
        self.left, self.right = left, right

    @staticmethod
    def _gap_ok(gap: str, most: int) -> bool:
        return len(gap) <= most and "?" not in gap and "." not in gap

    def _one_way(self, text: str, toks, a_set, b_set) -> bool:
        for i, a in enumerate(toks):
            if a.low not in a_set:
                continue
            for j in range(i + 1, len(toks)):
                c = toks[j]
                if not self._gap_ok(text[a.end:c.start], 20):
                    break
                if c.low not in self._JOIN:
                    continue
                for k in range(j + 1, len(toks)):
                    d = toks[k]
                    gap = text[c.end:d.start]
                    if c.low == "vs" and gap == "." and k == j + 1:
                        gap = ""                       # "vs.materials"
                    if not self._gap_ok(gap, 10):
                        break
                    if d.low in b_set:
                        return True
        return False

    def search(self, text: "str | None") -> "bool | None":
        text = text or ""
        toks = tokens(text)
        return (self._one_way(text, toks, self.left, self.right)
                or self._one_way(text, toks, self.right, self.left)) or None

    __call__ = search


_MG_WAGE_MATERIAL_MATCH = _MgNearPair(("wage", "wages"), ("material", "materials"))
# "wages or materials" itself is not a comparison word for the exclude check
_MG_WAGE_OR_MATERIAL = Matcher(Seq(_mg_sp(("wage", "wages"), ("or", "vs", "versus")), ("material", "materials")))
_MG_WAGE_MATERIAL_SQL_SHAPE = _MgSqlShape(_mg_outputs("wage_exp_lakh", "material_exp_lakh"))


def _mgnrega_wage_material_query(question: str, schemes: list[str], resolved: dict
                                 ) -> "tuple[str, list, str] | None":
    q = question or ""
    if schemes != ["MGNREGA"] or not _MG_WAGE_MATERIAL_MATCH.search(q) or _MG_BREAKDOWN_EXCLUDE_MATCH.search(
            _MG_WAGE_OR_MATERIAL.sub(" ", q)):
        return None
    f = _mgnrega_filters(resolved)
    if f is None:
        return None
    where, params, shown = f

    def build(w: list[str]) -> str:
        return ("SELECT ROUND(SUM(unskilled_wage_exp + semi_skilled_wage_exp)::numeric, 2) AS wage_exp_lakh, "
                "ROUND(SUM(material_exp)::numeric, 2) AS material_exp_lakh, COUNT(*) AS source_rows "
                "FROM curated.v_expenditure" + ((" WHERE " + " AND ".join(w)) if w else ""))
    return build(where), params, build(shown)


def _mgnrega_wage_material_answer(row: dict, display: dict) -> str:
    place = (f"{display['village']} village" if display.get("village") else
             f"{display['block']} block" if display.get("block") else display.get("district") or "Meghalaya")
    year = display.get("year")
    when = f" in {year}" if year else ""
    w, m = _as_number(row.get("wage_exp_lakh")), _as_number(row.get("material_exp_lakh"))
    if not row.get("source_rows") or (w in (None, 0) and m in (None, 0)):
        return (f"No MGNREGA wage or material expenditure is recorded for {place}{when} — both are 0 lakh "
                "in the data, so neither was higher.")
    w, m = float(w or 0), float(m or 0)
    if w == m:
        return f"Under MGNREGA, {place}{when} spent the same on wages and materials: {w:,.2f} lakh each."
    more, less = (("wages", w), ("materials", m)) if w > m else (("materials", m), ("wages", w))
    return (f"More was spent on {more[0]} than on {less[0]} in {place}{when} under MGNREGA: "
            f"{more[1]:,.2f} lakh on {more[0]} against {less[1]:,.2f} lakh on {less[0]}.")


_MG_COMBINED_SQL_SHAPE = _MgSqlShape(_mg_combined_shape)


def _mgnrega_combined_facts_answer(row: dict, display: dict) -> "str | None":
    """The answer to a _mgnrega_combined_facts_query row, every figure stated."""
    exp = _as_number(row.get("total_expenditure_lakh"))
    pd = _as_number(row.get("person_days"))
    if exp is None or pd is None:
        return None
    if display.get("village"):
        place = f"{display['village']} village"
    elif display.get("block"):
        place = f"{display['block']} block"
    elif display.get("assembly_constituency"):
        place = f"{display['assembly_constituency']} constituency"
    else:
        place = display.get("district") or "Meghalaya"
    year = display.get("year")
    parts = [f"total expenditure of {float(exp):,.2f} lakh", f"{int(pd):,} person-days"]
    hh = _as_number(row.get("households_employed"))
    if hh is not None:
        parts.append(f"{int(hh):,} households employed")
    pe = _as_number(row.get("persons_employed"))
    if pe is not None:
        parts.append(f"{int(pe):,} persons employed")
    listed = ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Under MGNREGA, {place}{' in ' + year if year else ''} recorded {listed}."


def _mgnrega_admin_expenditure_query(question: str, schemes: list[str], resolved: dict
                                     ) -> "tuple[str, list, str] | None":
    """(parameterised SQL, params, display SQL) for a MGNREGA administrative-
    expenditure question (DATA-013, KI-046), else None."""
    if schemes != ["MGNREGA"] or not _ADMIN_EXPENDITURE_REQUESTED.search(question or ""):
        return None
    f = _mgnrega_filters(resolved)
    if f is None:
        return None
    where, params, shown = f

    def build(w: list[str]) -> str:
        wh = (" WHERE " + " AND ".join(w)) if w else ""
        return ("SELECT ROUND(SUM(admin_total_exp)::numeric, 2) AS admin_expenditure_lakh, "
                f"COUNT(*) AS source_rows FROM curated.v_expenditure{wh}")
    return build(where), params, build(shown)


# Job cards are a running total (KI-293), so the years are never added. They were
# pinned to the latest year whatever was asked, and the answer said "across all
# financial years" for an FY 2025-26 figure (MGNREGA sheet DATA-007, run
# 2026-10-21: 24 of 24). One area's job cards are built here, parameter-bound, for
# exactly the year(s) asked — or, for all years, one row per year — and the answer
# is written from those rows, so it can never name a period the query did not read.
# Rankings, breakdowns and questions with another measure stay with the generator.
_MG_JOB_CARD_CUE = Matcher(Joined("job", ("card", "cards")))
_MG_JC_PLACE_W = W("district", "districts", "block", "blocks", "village", "villages",
                   "constituency", "constituencies")
_MG_JOB_CARD_EXCLUDE = Matcher(Alt(
    W("by", "wise", "breakdown", "top", "highest", "lowest", "most", "least", "which", "versus", "vs",
      "average", "avg", "share", "percentage", "percent"),
    W("rank", "compar", "trend", prefix=True),
    Seq(W("each", "every", "all", "per"), _MG_JC_PLACE_W),
    Joined("person", ("day", "days")),
    W("household", "households", "persons", "people", "women", "woman", "expenditure", "spent", "spend",
      "spending", "wage", "wages", "material", "materials"),
))


def _mgnrega_job_cards_query(question: str, schemes: list[str], resolved: dict
                             ) -> "tuple[str, list, str] | None":
    """(parameterised SQL, params, display SQL) for one area's MGNREGA job cards,
    one row per financial year asked, else None. A question with no year and no
    all-years cue is None: the year pause asks first, the year is never guessed."""
    q = question or ""
    if schemes != ["MGNREGA"] or not _MG_JOB_CARD_CUE.search(q) or _MG_JOB_CARD_EXCLUDE.search(q):
        return None
    years = _mg_resolved_years(resolved)
    if not years and not _ALL_YEARS_CUE.search(q):
        return None
    f = _mgnrega_filters({k: v for k, v in resolved.items() if k not in ("year_key", "year_key_list")},
                         allow_ac=True)
    if f is None:
        return None
    where, params, shown = f
    if years:
        params = params + [years]
        where = where + [f"year_key = ANY(${len(params)}::int[])"]
        shown = shown + [f"year_key = {years[0]}" if len(years) == 1
                         else f"year_key IN ({', '.join(map(str, years))})"]

    def build(w: list[str]) -> str:
        wh = (" WHERE " + " AND ".join(w)) if w else ""
        return ("/* mg-job-cards */ SELECT year_key, MAX(financial_year_short) AS financial_year, "
                "SUM(job_cards_issued_total) AS job_cards_issued\n"
                f"FROM curated.v_employment{wh}\nGROUP BY year_key ORDER BY year_key")
    return build(where), params, build(shown)


def _mgnrega_job_cards_answer(rows: list[dict], display: dict) -> str:
    """The job-card figure for each year the query read, in the rows' own words."""
    district = str(display.get("district") or "")
    place = ((display.get("village") and f"{display['village']} village")
             or (display.get("block") and f"{str(display['block']).title()} block")
             or (display.get("assembly_constituency") and f"{display['assembly_constituency']} constituency")
             or (district and (district if district.lower().endswith("district") else f"{district} district"))
             or "Meghalaya")
    held = [(str(r.get("financial_year") or ""), _as_number(r.get("job_cards_issued"))) for r in rows or []]
    held = [(fy, n) for fy, n in held if fy and n is not None]
    if not held:
        return f"No MGNREGA job-card records are held for {place} for the financial year(s) asked."
    if len(held) == 1:
        fy, n = held[0]
        return f"{int(n):,} MGNREGA job cards had been issued in {place} as of FY {fy}."
    lines = "\n".join(f"- FY {fy}: {int(n):,}" for fy, n in held)
    fy, n = held[-1]
    return (f"MGNREGA job cards issued in {place}, by financial year:\n{lines}\n\n"
            "Job cards are a running total — each year's figure already includes the cards issued in "
            f"earlier years — so the years are not added together. The most recent, FY {fy}, is {int(n):,}.")


def _mg_top_one(sql: str) -> bool:
    """A query (outer, CTE or subquery) that orders DESC and keeps LIMIT 1."""
    for t in sql_ast.parse(sql):
        for q in t.find_all(exp.Query):
            order, limit = q.args.get("order"), q.args.get("limit")
            if order is None or not isinstance(limit, exp.Limit):
                continue
            n = limit.expression
            if isinstance(n, exp.Literal) and not n.is_string and str(n.this) == "1" \
                    and any(o.args.get("desc") for o in order.expressions):
                return True
    return False


_MG_SCOPE_COLS = ("lgd_district", "lgd_block", "village_code")


def _mg_where_scoped(sql: str) -> bool:
    """A WHERE that pins a district, block or village: the top row is then the
    top WITHIN that area, not statewide. Only the filter itself counts — a
    GROUP BY / ORDER BY column (even in a subquery inside the WHERE) does not:
    reading past the WHERE made every ranking look scoped. A village filter
    scopes it too: ABAGRE's top YEAR was called "the top-ranked year in
    Meghalaya" (General TC-022, test run 2026-10-09)."""
    for t in sql_ast.parse(sql):
        for where in t.find_all(exp.Where):
            for col in where.find_all(exp.Column):
                name = col.name.lower()
                if not (name in _MG_SCOPE_COLS or name.startswith("lgd_village")):
                    continue
                node = col.parent
                while node is not None and node is not where and not isinstance(node, (exp.Group, exp.Order)):
                    node = node.parent
                if node is where:
                    return True
    return False


def _mgnrega_answer_notes(question: str, sql: str, rows: list[dict]) -> list[str]:
    """Composer notes for MGNREGA result shapes it described misleadingly
    (MGNREGA QA 2026-09-26): a statewide top-1 row was called "the highest …
    in the WEST GARO HILLS district" (DATA-025) or "the only district recorded"
    (DATA-027), and raw column names leaked ("lgd_district", DATA-026)."""
    notes: list[str] = []
    if len(rows) == 1 and _mg_top_one(sql or "") and not _mg_where_scoped(sql or ""):
        notes.append(
            "This row is the TOP-ranked one out of all of Meghalaya (the query ranked every "
            "area and kept the first). Say it is the highest in Meghalaya. Do not call it the "
            "only one, and do not say it is the highest within its own district or block.")
    if _mg_reads_money(sql or "") and not _mg_says_crore(sql or ""):
        # "Wages spending of 219.48 exceeded materials spending of 113.89" —
        # right numbers, no unit (DATA-023, 2026-09-26). MGNREGA money is lakh.
        notes.append("Every money figure in this result is in ₹ LAKH. Write \"lakh\" after "
                     "each amount (e.g. \"219.48 lakh\").")
    keys = {str(k) for k in rows[0]} if rows else set()
    if keys & {"household_years", "person_years"}:
        # errors.md case 3 / KI-040 / D-048: a multi-year sum of per-year tallies.
        notes.append(
            "household_years / person_years add up each financial year's count, so a household "
            "(or person) that worked in several years is counted once for EACH of those years. "
            "Call the figure \"household-years\" / \"person-years\" (e.g. \"1,494,437 "
            "household-years across the financial years in the data\"), never \"households\", "
            "\"persons\" or \"beneficiaries\", and add that MGNREGA records no household or "
            "person ID, so the number of DISTINCT households over all years is not available — "
            "offer a single year's figure instead.")
    if rows and any(_mg_is_place_column(str(k)) for k in rows[0]):
        notes.append(
            "Name places in plain words (\"Mawryngkneng village, Mawryngkneng block, East Khasi "
            "Hills\"). Never write column names such as lgd_district, lgd_block or village_code.")
    return notes


def _mg_wordy(s: str) -> bool:
    return s != "" and all(c.isalnum() or c == "_" for c in s)


def _mg_is_place_column(k: str) -> bool:
    """lgd_<anything>, village_code, assembly_constituency_name[<anything>]."""
    return (k.startswith("lgd_") and _mg_wordy(k[4:])) or k == "village_code" or (
        k.startswith("assembly_constituency_name") and (k == "assembly_constituency_name" or _mg_wordy(k[26:])))


def _mg_split_after_stops(text: str) -> list[str]:
    """Split after '.', '!' or '?' wherever whitespace follows (the whitespace is dropped)."""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        if text[i] in ".!?" and i + 1 < n and text[i + 1].isspace():
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            out.append(text[start:i + 1])
            start = i = j
            continue
        i += 1
    out.append(text[start:])
    return out


def _mgnrega_top_one_wording(answer: str, sql: str, rows: list[dict]) -> str:
    """Deterministic backstop for _mgnrega_answer_notes' ranking note, which the
    composer ignored on 2 of 2 live runs ("This is the only block recorded for
    that financial year in the result", DATA-025/027): drop that sentence from a
    statewide top-1 answer and say what the row actually is."""
    if not (len(rows) == 1 and _mg_top_one(sql or "")):
        return answer
    sentences = _mg_split_after_stops((answer or "").strip())
    kept = [s for s in sentences if not _ONLY_ONE_SENTENCE_MATCH.search(s)]
    if len(kept) == len(sentences) or not kept:
        return answer
    # Inside one area (a village's top YEAR) the sentence is just dropped — "No
    # other years are available in the result" was false: the query kept one
    # row of four (General TC-022, test run 2026-10-09).
    if _mg_where_scoped(sql or ""):
        return " ".join(kept)
    return " ".join(kept) + " It is the highest in Meghalaya."
# Rankings / breakdowns / comparisons stay with the SQL generator.
_MG_WOMEN_EXCLUDE_MATCH = Matcher(Alt(
    W("each", "every", "by", "wise", "breakdown", "trend", "top", "highest", "lowest", "most", "least", "which",
      "versus", "vs", "men", "male"),
    W("rank", "compare", prefix=True),
    NotBefore(W("per"), W("cent", prefix=True))))      # "per", but not "per cent"
_MGNREGA_YEAR_WOMEN: "list[dict] | None" = None


async def _mgnrega_year_women() -> "list[dict]":
    """[{year_key, fy, women}] for every MGNREGA employment year, oldest first."""
    global _MGNREGA_YEAR_WOMEN
    if _MGNREGA_YEAR_WOMEN is None:
        rows = await fetch_rows(
            "SELECT year_key, MAX(financial_year_short) AS fy, "
            "COALESCE(SUM(women_employment_provided), 0) AS women "
            "FROM curated.v_employment GROUP BY year_key ORDER BY year_key", [])
        _MGNREGA_YEAR_WOMEN = [{"year_key": int(r["year_key"]), "fy": str(r["fy"]),
                                "women": float(r["women"] or 0)} for r in rows]
    return _MGNREGA_YEAR_WOMEN


async def _mgnrega_women_query(question: str, schemes: list[str], resolved: dict) -> "dict | None":
    """A deterministic women count / share for ONE area (village, block, district,
    constituency or statewide), over the requested year or — when no year was
    named — every year that carries women data. None when the question is not a
    single-area women question (rankings etc. stay with the generator)."""
    q = question or ""
    if schemes != ["MGNREGA"] or not _WOMEN_CUE.search(q) or _MG_WOMEN_EXCLUDE_MATCH.search(q):
        return None
    yk = resolved.get("year_key")
    if isinstance(yk, (list, tuple, set)):
        return None
    f = _mgnrega_filters({k: v for k, v in resolved.items() if k != "year_key"}, allow_ac=True)
    if f is None:
        return None
    try:
        years = await _mgnrega_year_women()
    except Exception:  # noqa: BLE001 — without the year map, leave it to the generator
        return None
    have = [y for y in years if y["women"] > 0]
    missing = [y for y in years if y["women"] <= 0]
    if not have:
        return None
    where, params, shown = f
    if yk is not None:
        if any(int(yk) == y["year_key"] for y in missing):
            return {"kind": "unrecorded", "year": next(y for y in missing if y["year_key"] == int(yk)),
                    "have": have, "where": where, "params": params}
        sel = [y for y in years if y["year_key"] == int(yk)]
    else:
        sel = have
    keys = [y["year_key"] for y in sel]
    p2 = params + [keys]
    w2 = where + [f"year_key = ANY(${len(p2)}::int[])"]
    s2 = shown + [f"year_key IN ({', '.join(map(str, keys))})"]

    def build(w: list[str]) -> str:
        return ("SELECT SUM(women_employment_provided) AS women_employed, "
                "SUM(persons_employed) AS persons_employed, "
                "ROUND(100.0 * SUM(women_employment_provided)::numeric / "
                "NULLIF(SUM(persons_employed), 0), 2) AS women_share_pct\n"
                "FROM curated.v_employment WHERE " + " AND ".join(w))
    return {"kind": "query", "sql": build(w2), "params": p2, "shown": build(s2),
            "years": sel, "all_years": yk is None, "missing": missing}


async def _mgnrega_women_unrecorded_answer(info: dict, display: dict) -> str:
    """FY 2025-26 (or any year without women data) was asked for explicitly."""
    fy = info["year"]["fy"]
    latest = info["have"][-1]
    place = _mgnrega_scope_words({k: v for k, v in display.items() if k != "year"})
    head = (f"Women employment is not recorded in the MGNREGA data for FY {fy} — the women column "
            "is 0 on every record statewide for that year (not populated at source), so no women "
            "figure or share can be given for it.")
    try:
        w = info["where"] + [f"year_key = ${len(info['params']) + 1}"]
        r = (await fetch_rows(
            "SELECT SUM(women_employment_provided) AS w, SUM(persons_employed) AS p, "
            "ROUND(100.0 * SUM(women_employment_provided)::numeric / NULLIF(SUM(persons_employed), 0), 2) "
            "AS pct FROM curated.v_employment WHERE " + " AND ".join(w),
            info["params"] + [latest["year_key"]]))[0]
    except Exception:  # noqa: BLE001
        return head
    if r["pct"] is None:
        return head
    return (f"{head} The latest year with women data is FY {latest['fy']}: {float(r['pct']):.2f}% of "
            f"employed persons{place} were women ({int(r['w']):,} of {int(r['p']):,}).")


async def _mgnrega_women_year_clarification(question: str) -> "ClarificationNeeded":
    """The FY pause for a women question: only years that carry women data."""
    years = await _mgnrega_year_women()
    have = [y for y in years if y["women"] > 0]
    missing = [y for y in years if y["women"] <= 0]
    stem = (question or "").strip().rstrip(" ?.")
    options = [{"label": f"FY {y['fy']}", "question": f"{stem} for FY {y['fy']}"} for y in have]
    options.append({"label": f"All years with women data ({_women_span(have)})",
                    "question": f"{stem} across all financial years"})
    gap = (f" Women employment is not recorded for {', '.join('FY ' + y['fy'] for y in missing)}."
           if missing else "")
    return ClarificationNeeded(
        f"MGNREGA women-employment data is available for {_women_span(have)}.{gap} Which financial "
        "year is required — a single year, or all of these years combined?",
        options=options, rule="year-not-specified")


def _mgnrega_women_years_only(schemes: list[str], sql: str) -> str:
    """Generator SQL that reads women_employment_provided across ALL years (no
    year_key anywhere) would count FY 2025-26's unrecorded women as zero against
    its real persons — East Khasi Hills' all-years share read 55.86% instead of
    74.90%. Restrict such a query to the years that carry women data."""
    if "MGNREGA" not in schemes or not sql or _MGNREGA_YEAR_WOMEN is None:
        return sql
    if not sql_ast.references_column(sql, "women_employment_provided") or "year_key" in _mg_names(sql):
        return sql
    have = [y["year_key"] for y in _MGNREGA_YEAR_WOMEN if y["women"] > 0]
    if not have or len(have) == len(_MGNREGA_YEAR_WOMEN):
        return sql
    sub = sql_ast.parse_one(
        f"SELECT * FROM curated.v_employment WHERE year_key IN ({', '.join(map(str, have))})")

    def fn(tree):
        # Every curated.v_employment read becomes the years-with-women subquery,
        # under the read's own alias (or v_employment, so qualified columns hold).
        for tb in list(tree.find_all(exp.Table)):
            if tb.name.lower() != "v_employment" or (tb.db or "").lower() != "curated":
                continue
            tb.replace(sub.copy().subquery(tb.alias or "v_employment", copy=False))
        return None
    return sql_ast.transform(sql, fn)


def _mgnrega_women_sql_years(sql: str) -> "set[int] | None":
    """The year_keys a women query filters (literal = / IN), or None."""
    keys: set[int] = set()
    for node in sql_ast.filter_conditions(sql or "", "year_key"):
        if not isinstance(node, (exp.EQ, exp.In)):
            continue
        for v in sql_ast.filter_values(node, "year_key", numeric=True):
            if str(v).isdigit() and len(str(v)) == 4:
                keys.add(int(v))
    return keys or None


def _mgnrega_scope_words(display: dict) -> str:
    """"for Demdema block in FY 2024-25" from the resolved display names."""
    place = " ".join(p for p in (
        display.get("village") and f"{display['village']} village",
        display.get("block") and f"{str(display['block']).title()} block",
        display.get("assembly_constituency") and f"{display['assembly_constituency']} constituency",
        display.get("district")) if p)
    year = f" in {display['year']}" if display.get("year") else ""
    return (f" for {place}" if place else "") + year


def _mgnrega_fact_word(sql: str) -> str:
    read = sql_ast.tables(sql or "")
    emp, spend = bool(read & _EMPLOYMENT_OBJECTS), bool(read & _EXPENDITURE_OBJECTS)
    return "employment" if emp and not spend else "expenditure" if spend and not emp else "MGNREGA data"


async def _mgnrega_empty_answer(sql: str, rows: list[dict], display: dict,
                                resolved: dict) -> "str | None":
    """A single aggregate row whose every value is NULL. Either the filters
    matched no source rows at all (SUM over nothing — KHATARSHNONG LAITKROH has
    no expenditure rows, Mairangbah no 2024-25 employment rows), or a ratio's
    base is zero (Demdema's 100-day % is 0 / 0). The composer described both as
    "the result shows a null value for total_expenditure_crore" (all-blocks QA
    2026-09-26). Which one it is is checked with a parameter-bound row count."""
    if len(rows) != 1 or not rows[0] or any(v is not None for v in rows[0].values()):
        return None
    what = _mgnrega_fact_word(sql)
    view = {"employment": "curated.v_employment", "expenditure": "curated.v_expenditure"}.get(what)
    n = None
    f = _mgnrega_filters(resolved, allow_ac=(what == "employment"))
    if view and f is not None:
        where, params, _ = f
        try:
            n = (await fetch_rows(f"SELECT COUNT(*) AS n FROM {view}"
                                  + (" WHERE " + " AND ".join(where) if where else ""), params))[0]["n"]
        except Exception:  # noqa: BLE001 — fall back to the composer
            return None
    scope = _mgnrega_scope_words(display)
    if n == 0:
        return (f"No MGNREGA {what} is recorded{scope} — the data has no {what} records for it, "
                "so there is no figure to report (this is not the same as zero).")
    if n and any(t.find(exp.Nullif) is not None for t in sql_ast.parse(sql)):
        return (f"This cannot be calculated{scope}: the figure it is divided by is 0 in the "
                "recorded data (for example, no households received employment), so there is no "
                "percentage or average to report.")
    return None


def _mgnrega_null_zero_notes(rows: list[dict]) -> list[str]:
    """Composer notes for a single-row result with an empty side, or genuine zeros."""
    if len(rows) != 1 or not rows[0]:
        return []
    row, notes = rows[0], []
    empty = [k for k, v in row.items() if v is None]
    if empty and len(empty) < len(row):
        notes.append(
            f"{', '.join(empty)} is empty because no MGNREGA records of that kind exist for this "
            "area and year. Say so plainly (e.g. \"no expenditure is recorded for it\"), still "
            "report the other figures, never write \"null\", and never call it zero.")
    nums = [_as_number(v) for v in row.values() if v is not None]
    if nums and all(n == 0 for n in nums if n is not None) and all(n is not None for n in nums):
        notes.append(
            "Every figure here is a genuine recorded ZERO (the area has records, all 0). State "
            "it as 0 (e.g. \"0 households received employment\"). Do not say the data does not "
            "cover it.")
    return notes


def _mgnrega_zero_backstop(answer: str, rows: list[dict], display: dict) -> str:
    """The composer hedged over a genuine zero ("the data available doesn't cover the
    number of households … Demdema") — replace it with the recorded 0."""
    if len(rows) != 1 or not rows[0] or not _HEDGE_MATCH.search(answer or ""):
        return answer
    vals = [(k, _as_number(v)) for k, v in rows[0].items()]
    if not vals or any(n is None or n != 0 for _, n in vals):
        return answer
    parts = "; ".join(f"0 {_metric_label(k)}" for k, _ in vals)
    return f"{parts}{_mgnrega_scope_words(display)} — the data records zero."


def _mg_add_lakh(answer: str, form: str) -> str:
    """`form` -> `form lakh` wherever it stands as a whole number (no digit, '.' or
    ',' before it, no digit after) and no unit (lakh / lac / crore / cr / %) follows."""
    out, last, i = [], 0, 0
    while form:
        k = answer.find(form, i)
        if k < 0:
            break
        e = k + len(form)
        ok = (k == 0 or not (answer[k - 1].isdecimal() or answer[k - 1] in ".,"))             and not (e < len(answer) and answer[e].isdecimal())
        if ok:
            rest = answer[e:].lstrip()
            if rest.startswith(("lakh", "lac", "crore", "%")) or (
                    rest.startswith("cr") and (len(rest) == 2 or not (rest[2].isalnum() or rest[2] == "_"))):
                ok = False
        if ok:
            out.append(answer[last:k] + form + " lakh")
            last = i = e
        else:
            i = k + 1
    out.append(answer[last:])
    return "".join(out)


def _mgnrega_money_units(answer: str, sql: str, rows: list[dict]) -> str:
    """Deterministic backstop for the "write lakh" note: add " lakh" after any
    MGNREGA money value from the result that the answer states without a unit.
    Skipped for crore SQL (the value is then crore, and the composer names it)."""
    if not answer or not rows or _mg_says_crore(sql or "") or not _mg_reads_money(sql or ""):
        return answer
    forms: set[str] = set()
    for r in rows[:40]:
        for k, v in r.items():
            n = _as_number(v)
            if n is None or not _MONEY_COL_NAME_MATCH.search(str(k)) or isinstance(n, int) and n == 0:
                continue
            f = float(n)
            forms |= {f"{f:,.2f}", f"{f:.2f}"}
    for form in sorted(forms, key=len, reverse=True):
        answer = _mg_add_lakh(answer, form)
    return answer


_MG_LIST_LABELS = {"lgd_block": "block", "block_name": "block", "lgd_district": "district",
                   "district_name": "district", "lgd_village": "village", "village_name": "village"}


def _mgnrega_complete_list(answer: str, rows: list[dict]) -> str:
    """A short per-area count breakdown (one label column, one count column,
    3-15 rows) names every area. "MGNREGA person-days by block in West Garo Hills
    in FY 2024-25" was answered with the total, the top and the bottom block
    only, so Dalu — the block officer's own block — was nowhere in the text
    (harness 2026-10-19; the same SQL listed all eight blocks at 12:22). The
    composer's sentence is kept and the full list is added under it. Counts
    only: money keeps its lakh / crore wording (_mgnrega_money_units)."""
    if not answer or not 3 <= len(rows) <= 15:
        return answer
    nums = [k for k in rows[0] if _as_number(rows[0].get(k)) is not None and not _NONSTAT_COL.search(k)]
    labels = [k for k in rows[0] if k not in nums]
    if len(nums) != 1 or len(labels) != 1 or _MONEY_COL_NAME_MATCH.search(nums[0]):
        return answer
    lab, met = labels[0], nums[0]
    low = answer.lower()
    if all(r.get(lab) is None or str(r[lab]).lower() in low for r in rows):
        return answer
    items = []
    for r in rows:
        v = _as_number(r.get(met))
        if v is None or r.get(lab) is None:
            continue
        v = int(v) if float(v).is_integer() else v
        items.append(f"{str(r[lab]).title()} {v:,}")
    name = _MG_LIST_LABELS.get(lab, lab.replace("_", " "))
    return f"{answer.rstrip()}\n\n{_metric_label(met).capitalize()} by {name}: " + "; ".join(items) + "."


async def _mgnrega_admin_expenditure_answer(rows: list[dict], display: dict) -> str:
    """The recorded figure, stated with the reason it cannot be read as a real
    zero. The caveat is the whole point of the earlier refusal (2026-09-17: a
    bare 0.00 reads as a measured finding), so it is always attached; the
    statewide figure is read live so the caveat can never go stale."""
    val = _as_number((rows or [{}])[0].get("admin_expenditure_lakh")) or 0
    place = " ".join(p for p in (display.get("village") and f"{display['village']} village",
                                 display.get("block") and f"{display['block']} block",
                                 display.get("district")) if p) or "Meghalaya"
    year = f" in {display['year']}" if display.get("year") else ""
    try:
        st = (await fetch_rows(
            "SELECT ROUND(SUM(admin_total_exp)::numeric, 2) AS total, "
            "COUNT(*) FILTER (WHERE admin_total_exp <> 0) AS nonzero, COUNT(*) AS n "
            "FROM curated.v_expenditure", []))[0]
        state = (f" Statewide, the column is non-zero on only {st['nonzero']} of {st['n']:,} "
                 f"records (₹{float(st['total'] or 0):,.2f} lakh in total).")
    except Exception:  # noqa: BLE001 — the caveat stands without the statewide figure
        state = ""
    return (f"Recorded MGNREGA administrative expenditure for {place}{year}: "
            f"₹{float(val):,.2f} lakh.\n\n"
            "Please read this with care: the administrative-expenditure column was never "
            "populated at source, so this figure reflects what was recorded, not a confirmed "
            f"zero spend.{state} The expenditure that is recorded is unskilled wages, "
            "semi-skilled wages, material and total expenditure — ask for any of those.")


def _mg_fact_kind(table: exp.Table) -> "str | None":
    name = table.name.lower()
    return "employment" if name in _EMPLOYMENT_OBJECTS else "expenditure" if name in _EXPENDITURE_OBJECTS else None


def _mg_select_aggregates(sel: exp.Select) -> bool:
    """True when the SELECT collapses its rows: a GROUP BY, or an aggregate in its
    own output list (not a window function, not one inside a nested subquery)."""
    if sel.args.get("group") is not None:
        return True
    for e in sel.expressions:
        for agg in e.find_all(exp.AggFunc):
            node = agg.parent
            while node is not None and node is not sel and not isinstance(node, (exp.Window, exp.Select)):
                node = node.parent
            if node is sel:
                return True
    return False


def _mg_raw_facts(node: "exp.Expression | None", ctes: dict, seen: frozenset = frozenset()) -> "set[str]":
    """The MGNREGA facts whose rows come out of a FROM / JOIN source (or a query)
    one per source row, i.e. not collapsed by an aggregation on the way."""
    if node is None:
        return set()
    if isinstance(node, exp.Table):
        kind = _mg_fact_kind(node)
        if kind:
            return {kind}
        name = node.name.lower()
        if not node.db and name in ctes and name not in seen:
            return _mg_raw_facts(ctes[name], ctes, seen | {name})
        return set()
    if isinstance(node, (exp.Subquery, exp.Paren)):
        return _mg_raw_facts(node.this, ctes, seen)
    if isinstance(node, exp.SetOperation):
        return _mg_raw_facts(node.left, ctes, seen) | _mg_raw_facts(node.right, ctes, seen)
    if isinstance(node, exp.Select):
        if _mg_select_aggregates(node):
            return set()
        out: set[str] = set()
        for src in _mg_sources(node):
            out |= _mg_raw_facts(src, ctes, seen)
        return out
    return set()


def _mg_sources(sel: exp.Select) -> "list[exp.Expression]":
    """The FROM item and every JOINed item (comma joins included) of one SELECT."""
    frm = sel.args.get("from_") or sel.args.get("from")
    out = [frm.this] if frm is not None and frm.this is not None else []
    out += [j.this for j in sel.args.get("joins") or [] if j.this is not None]
    return out


def _mgnrega_facts_joined(sql: str) -> bool:
    """True when the query JOINs the employment fact to the expenditure fact in
    one statement — the fan-out shape rule 1 forbids.

    The safe shapes name both objects too, but wrap each in its own aggregated
    scope so anything joined afterwards is one row per side (or per grain key):
      * a CTE per fact  (WITH emp AS (...), exp AS (...) SELECT ...), and
      * an inline subquery per fact  (FROM (SELECT SUM(...) ...) exp CROSS JOIN
        (SELECT SUM(...) ...) emp) — which is what the repair prompt actually
        produces most often, and is equally correct.
    Read on the tree: every SELECT — the outer one, each CTE body, each
    subquery — is checked. One whose sources (FROM, JOINs, comma joins) bring
    raw employment rows from one source and raw expenditure rows from another
    multiplies them, and is flagged. A source is raw when it is the fact itself,
    or a CTE / subquery that reads it without aggregating. A CTE body that
    joins the two raw facts is caught too — a leading WITH used to excuse the
    whole statement, so a fan-out inside a CTE ran unflagged."""
    for tree in sql_ast.parse(sql):
        ctes = {c.alias_or_name.lower(): c.this for c in tree.find_all(exp.CTE)}
        for sel in tree.find_all(exp.Select):
            per_source = [_mg_raw_facts(src, ctes) for src in _mg_sources(sel)]
            for i, a in enumerate(per_source):
                if "employment" in a and any("expenditure" in b for j, b in enumerate(per_source) if j != i):
                    return True
    return False


# ════ verify and repair ═══════════════════════════════════════════════════════════════════════════════
# MGNREGA's two facts are separate objects with NO overlapping measures:
# employment (person_days, persons_employed, households_employed,
# households_completed_100_days, job_cards_issued_total) lives on
# curated.v_employment; money (total_exp, unskilled_wage_exp,
# semi_skilled_wage_exp, material_exp) lives on curated.v_expenditure. A
# question that wants one of each ("compare expenditure and person-days in
# RERAPARA") cannot be answered from a single view, and the generator reliably
# tries anyway — selecting person_days off v_expenditure, which errors, and
# then failing to recover because the generic missing-column hint only says
# "select from an object that exposes every column" without explaining that no
# such object exists at block grain (confirmed live 2026-09-17: the question
# burned its whole repair budget and fell through to "couldn't build a working
# query"). docs/schema_for_developers.md: v_district_year_summary is the only
# sanctioned combined object, and it is district x year ONLY — so at block or
# village grain the answer is two CTEs.
_EMPLOYMENT_MEASURES = {
    "person_days", "persons_employed", "households_employed",
    "households_completed_100_days", "job_cards_issued_total",
    "women_employment_provided",
}
_EXPENDITURE_MEASURES = {
    "total_exp", "unskilled_wage_exp", "semi_skilled_wage_exp",
    "material_exp", "tax_exp", "admin_total_exp",
}


def _mgnrega_split_fact_hint(col: str) -> "str | None":
    """The recipe for combining MGNREGA employment and expenditure measures,
    when the missing column is one that lives on the OTHER fact."""
    if col in _EMPLOYMENT_MEASURES:
        wanted, home, other = col, "curated.v_employment", "curated.v_expenditure"
    elif col in _EXPENDITURE_MEASURES:
        wanted, home, other = col, "curated.v_expenditure", "curated.v_employment"
    else:
        return None
    return (
        f'"{wanted}" lives on {home}, NOT on {other} — MGNREGA keeps employment and '
        "expenditure in two separate facts that share no measures, so ONE view can "
        "never supply both. To report a measure from each, aggregate them "
        "independently and join the results:\n"
        "  WITH emp AS (SELECT SUM(person_days) AS person_days FROM curated.v_employment "
        "WHERE <same filters>),\n"
        "       exp AS (SELECT SUM(total_exp) AS total_exp_lakh FROM curated.v_expenditure "
        "WHERE <same filters>)\n"
        "  SELECT exp.total_exp_lakh, emp.person_days FROM emp, exp\n"
        "Put the SAME geography and year_key filters on BOTH CTEs. Add a GROUP BY plus a "
        "FULL OUTER JOIN on the grain columns only if the question asks for a per-district "
        "/ per-block / per-year breakdown. At DISTRICT x YEAR grain you may instead select "
        "both measures directly from curated.v_district_year_summary, which already "
        "combines the two facts; it has no block or village column, so it cannot be used "
        "for a block- or village-level question."
    )


# A village_code filter already names the place. A block/district literal the
# generator adds beside it can only narrow it wrongly: MAWLIEH (village 277048,
# EASTERN WEST KHASI HILLS) got "AND lgd_district = 'EAST KHASI HILLS'" and
# returned no expenditure for a village with 26.22 lakh (all-villages QA
# 2026-09-26). Removed when one village was resolved and the SQL filters it.
# UPPER(TRIM(lgd_district)) too (Focus Legacy all-villages run 2026-10-02: the
# village name KASHARIPARA written into the district column beside its code), and
# LOWER(lgd_district) = 'nongthylep' (the same run, 3 villages).
def _mg_village_code_eqs(sql_or_tree) -> "list[exp.EQ]":
    """Every `village_code = <literal>` comparison (either side, quoted or not)."""
    return [n for n in sql_ast.filter_conditions(sql_or_tree, "village_code")
            if isinstance(n, exp.EQ) and isinstance(_mg_unwrap(n.this), exp.Literal)
            != isinstance(_mg_unwrap(n.expression), exp.Literal)]


def _mg_code_literal(eq: exp.EQ) -> "exp.Literal":
    side = _mg_unwrap(eq.expression)
    return side if isinstance(side, exp.Literal) else _mg_unwrap(eq.this)


def _mg_literal_int(lit: exp.Literal) -> "int | None":
    s = str(lit.this).strip()
    return int(s) if s.isdigit() else None


def _mg_is_geo_literal(cond: exp.Expression) -> bool:
    """`lgd_block|lgd_district = '<text>'`, either column wrapped in UPPER / LOWER /
    TRIM, either literal wrapped too."""
    return isinstance(cond, exp.EQ) \
        and any(n is cond for n in sql_ast.filter_conditions(cond, "lgd_block", "lgd_district")) \
        and bool(sql_ast.filter_values(cond, "lgd_block", "lgd_district"))


def _mgnrega_drop_geo_beside_village(schemes: list[str], entity_result: dict, sql: str) -> str:
    # Every village scheme since 2026-10-02: a district / block literal beside the
    # one resolved village_code can only narrow it wrongly (Focus Legacy wrote the
    # village name into lgd_district: KASHARIPARA, KANDARGAON, KAIMBATAPARA -> 0).
    code = (entity_result.get("resolved") or {}).get("village_code")
    if not _village_scheme(schemes) or not code or isinstance(code, (list, tuple)) or not sql:
        return sql
    if not any(_mg_literal_int(_mg_code_literal(eq)) == int(code) for eq in _mg_village_code_eqs(sql)):
        return sql
    return sql_ast.remove_conditions(sql, _mg_is_geo_literal)


# A village FILTER, not just the column name: a village_code / geography_key
# compared with = or IN (a join condition a.village_code = b.village_code counts),
# or lgd_village_name compared with =, LIKE, ILIKE, IN or ~. A bare mention in the
# SELECT / GROUP BY does not (hierarchy matrix run 2026-10-14).
def _mg_filters_a_village(sql: str) -> bool:
    for n in sql_ast.filter_conditions(sql, "village_code", "geography_key"):
        if isinstance(n, (exp.EQ, exp.In)):
            return True
    for n in sql_ast.filter_conditions(sql, "lgd_village_name"):
        if isinstance(n, (exp.EQ, exp.In, exp.Like, exp.ILike)):
            return True
    for t in sql_ast.parse(sql):
        for n in t.find_all(exp.RegexpLike, exp.RegexpILike):
            if sql_ast.references_column(n.this, "lgd_village_name"):
                return True
    return False


def _mgnrega_village_filter_missing(schemes: list[str], entity_result: dict, sql: str) -> "int | None":
    """The resolved village_code when a MGNREGA query does not filter on any
    village at all. The generator dropped the village for MEGAPGRE / NONGLUM
    (filtered the block) and UMTYRNGA (no filter: the statewide 106,669.85 lakh
    reported as one village's spend), and the verifier passed it (KI-034 family,
    all-villages QA 2026-09-26)."""
    code = (entity_result.get("resolved") or {}).get("village_code")
    if "MGNREGA" not in schemes or not code or isinstance(code, (list, tuple)) or not sql:
        return None
    if _mg_filters_a_village(sql):
        return None
    return int(code)


def _mgnrega_pin_village_code(schemes: list[str], entity_result: dict, sql: str) -> str:
    code = (entity_result.get("resolved") or {}).get("village_code")
    if "MGNREGA" not in schemes or not code or isinstance(code, (list, tuple)) or not sql:
        return sql
    code = int(code)
    # An IN-list with extra codes: "MAWKOHMIT & MAWKYNSAH" (277073) came back as
    # village_code IN (277073, 277074) — a neighbour's 5,387 person-days added to
    # a village that recorded 0 (all-villages QA 2026-09-26).
    in_lists = [n for n in sql_ast.filter_conditions(sql, "village_code") if isinstance(n, exp.In)
                and n.expressions and all(isinstance(_mg_unwrap(e), exp.Literal) for e in n.expressions)]
    if in_lists:
        logger.info("MGNREGA: SQL filtered a village_code IN-list, resolved one village %s — pinned", code)

        def pin_in(tree):
            for n in list(tree.find_all(exp.In)):
                if sql_ast.references_column(n.this, "village_code") and n.expressions \
                        and all(isinstance(_mg_unwrap(e), exp.Literal) for e in n.expressions):
                    n.replace(exp.EQ(this=n.this.copy(), expression=exp.Literal.number(code)))
            return None
        return sql_ast.transform(sql, pin_in)
    found = {_mg_literal_int(_mg_code_literal(eq)) for eq in _mg_village_code_eqs(sql)} - {None}
    if len(found) != 1 or code in found:
        return sql
    logger.info("MGNREGA: SQL filtered village_code %s, resolved %s — substituted", found, code)

    def pin_eq(tree):
        for eq in _mg_village_code_eqs(tree):
            lit = _mg_code_literal(eq)
            if _mg_literal_int(lit) is not None:
                lit.replace(exp.Literal.number(code))
        return None
    return sql_ast.transform(sql, pin_eq)

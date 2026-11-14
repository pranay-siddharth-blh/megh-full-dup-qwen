# app/pipeline/schemes/focus_plus.py — Focus Plus — village / alias rules, SQL rewrites and answer guarantees.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
# Only this scheme's code lives here; the shared steps that call it are in ../common/.
# Sections follow the order of the pipeline steps they belong to.
# SQL is read and rewritten on the SQLGlot tree (app/sql_ast), never as raw text.
from app import sql_ast
from sqlglot import exp
from app.text_match import (ANY, END, Alt, Before, Matcher, Opt, Pred, Seq, W, collapse_ws, is_int, tokens)

# ════ scheme terms ════════════════════════════════════════════════════════════════════════════════════
# Focus Plus is a Meghalaya STATE farmer cash-benefit scheme. These terms name it or
# its scheme-specific machinery and belong to no other scheme. "tranche"/"tranch" is
# claimed HERE, not left shared with PMAY-G: it's Focus Plus's actual vocabulary (the
# stored column is tranche_label), while PMAY-G's own word for the same idea is
# "installment" (see _PMAY_ONLY_TERMS). "batch"/"disbursement" are still left out —
# those really are generic enough that an unnamed question using only those still
# asks "which scheme?".
# "12.5k" is the words 12 and 5k with exactly "." between them.
_FP_12_5K = _PmayAdj(W("12"), W("5k"), lambda g: g == ".")
# "12.5 K" / "93 K" — the batch written with a space (FOCUS-019 re-test 2026-10-22,
# KI-360): read as no scheme at all, so "status breakdown for 12.5 K batch" was
# refused or asked "which scheme?".
_FP_12_5_SPACE_K = _PmayAdj(_PmayAdj(W("12"), W("5"), lambda g: g == "."), W("k"), lambda g: g.isspace())
_FP_93_SPACE_K = Seq("93", "k", sep="space")
_FOCUSPLUS_ONLY_TERMS = Matcher(Alt(
    Seq("focus", "plus"), W("focusplus"),
    _PmayCharAfter(W("focus"), lambda rest: rest.lstrip().startswith("+")),
    W("tranch", "tranche", "tranchs", "tranches"),
    # "producer group" is NOT here — see _FOCUSLEGACY_ONLY_TERMS. It belongs to
    # Focus Legacy, whose grain IS the producer group; Focus Plus holds no such
    # column and focusplus_classification_rules.yaml refuses the question
    # outright (condition producer_group_requested).
    W("meghalayaone", "mbda"), "meghalaya basin development",
    Seq("focus", "card"), W("focuscard"), W("93k"), _FP_12_5K, _FP_12_5_SPACE_K, _FP_93_SPACE_K,
))


# ════ clarifications ══════════════════════════════════════════════════════════════════════════════════
# Focus Plus block_name_raw holds the literal "Nan" on the records whose block
# and district the source left blank (4 payments, 1 beneficiary).
_FP_BLANK_BLOCK = "NAN"
_FP_BLANK_BLOCK_NOTE = (
    "'Nan' is not a real C&RD block: it is how the Focus Plus source marks records whose "
    "block and district were left blank. Filter UPPER(block_name_raw) = 'NAN', report the "
    "figure, and say those records have no block or district recorded.")
_FP_BLANK_BLOCK_LEAD = ("'Nan' is not a real block — it is how the Focus Plus source file marks records "
                        "whose block and district were left blank.")

# The two Focus Plus cohorts by their stored batch_label ("12.5K" / "93K").
# Focus Plus-only vocabulary: no other scheme has a batch of that name.
_FOCUSPLUS_BATCH_WORD = Matcher(Alt(_FP_12_5K, _FP_12_5_SPACE_K, W("93k"), _FP_93_SPACE_K))


# ════ years and tranches ══════════════════════════════════════════════════════════════════════════════
# Client UAT sheet (FOCUS-030, 2026-09-13): "Give me an overall Focus+ data
# summary" got a correct but thin answer — just payments/beneficiaries/amount/
# districts/blocks/villages from one plain SELECT. The client's remark wants a
# richer report: years/batches/tranches available, the top district by each
# of two different rankings (most beneficiaries vs. highest disbursement —
# genuinely different districts in this data), top bank, and the 12.5K-only
# gender/occupation/status/verification splits. That shape can't come from one
# flat SELECT the normal way (each of those needs its own GROUP BY / ORDER BY /
# LIMIT 1), and letting the LLM free-write ad hoc SQL plus prose for a dozen
# figures at once is exactly the kind of multi-fact answer this project's
# numeric-faithfulness guard exists to catch failures of, not prevent them.
# Deterministic instead: one CTE query gets every figure in a single round
# trip, and the answer is built directly from those rows — no composer call,
# so nothing here can be transcribed wrong.
_FOCUSPLUS_OVERALL_SUMMARY_CUE = Matcher(Alt(
    _PmayNear(W("overall"), W("summary", "picture", "snapshot"), 40, lambda ch: ch in ".?!"),
    _PmayNear(W("summary", "snapshot", "overview"), W("overall"), 40, lambda ch: ch in ".?!"),
    Seq(W("complete", "full", "entire"), Opt("data"), "summary"),
    _PmayNear(W("summarise", "summarize"), W("focus"), 30),
    _PmayNear(W("focus"), Seq("data", "summary"), 30),
))

_FOCUSPLUS_OVERALL_SUMMARY_SQL = """
WITH totals AS (
  SELECT COUNT(*) AS payments,
         COUNT(DISTINCT beneficiary_key) AS beneficiaries,
         SUM(amount_disbursed) AS amount,
         COUNT(DISTINCT lgd_district) AS districts,
         COUNT(*) FILTER (WHERE lgd_district IS NULL) AS missing_district_rows
  FROM curated.v_focus_plus
),
years AS (
  SELECT string_agg(DISTINCT financial_year_short, ', ' ORDER BY financial_year_short) AS years_list
  FROM curated.v_focus_plus
),
batches AS (
  SELECT string_agg(DISTINCT batch_label, ', ' ORDER BY batch_label) AS batch_list
  FROM curated.v_focus_plus
),
tranches AS (
  SELECT COUNT(DISTINCT tranche_label) AS tranche_count
  FROM curated.v_focus_plus
),
top_beneficiary_district AS (
  SELECT lgd_district AS top_ben_district, COUNT(DISTINCT beneficiary_key) AS top_ben_district_count
  FROM curated.v_focus_plus WHERE lgd_district IS NOT NULL
  GROUP BY lgd_district ORDER BY top_ben_district_count DESC LIMIT 1
),
top_disbursement_district AS (
  SELECT lgd_district AS top_amt_district, SUM(amount_disbursed) AS top_amt_district_amount
  FROM curated.v_focus_plus WHERE lgd_district IS NOT NULL
  GROUP BY lgd_district ORDER BY top_amt_district_amount DESC LIMIT 1
),
top_bank AS (
  SELECT bank_name_raw AS top_bank_name, SUM(amount_disbursed) AS top_bank_amount
  FROM curated.v_focus_plus WHERE bank_name_raw IS NOT NULL AND NOT (bank_name_raw <> '' AND TRANSLATE(bank_name_raw, '0123456789', '') = '')
  GROUP BY bank_name_raw ORDER BY top_bank_amount DESC LIMIT 1
),
gender AS (
  SELECT COUNT(*) FILTER (WHERE gender = 'Female') AS female,
         COUNT(*) FILTER (WHERE gender = 'Male') AS male
  FROM curated.v_focus_plus WHERE batch_label = '12.5K'
),
occupation AS (
  SELECT COUNT(*) FILTER (WHERE occupation = 'Farmer') AS farmers
  FROM curated.v_focus_plus WHERE batch_label = '12.5K'
),
status AS (
  SELECT COUNT(*) FILTER (WHERE focus_status = 'Pending') AS pending,
         COUNT(*) FILTER (WHERE focus_status = 'Approved') AS approved,
         COUNT(*) FILTER (WHERE focus_status = 'Rejected') AS rejected,
         COUNT(*) FILTER (WHERE verification_status = 'Approved') AS verified_approved
  FROM curated.v_focus_plus WHERE batch_label = '12.5K'
)
SELECT totals.payments, totals.beneficiaries, totals.amount, totals.districts,
       totals.missing_district_rows, years.years_list, batches.batch_list,
       tranches.tranche_count, top_beneficiary_district.top_ben_district,
       top_beneficiary_district.top_ben_district_count,
       top_disbursement_district.top_amt_district,
       top_disbursement_district.top_amt_district_amount,
       top_bank.top_bank_name, top_bank.top_bank_amount,
       gender.female, gender.male, occupation.farmers,
       status.pending, status.approved, status.rejected, status.verified_approved
FROM totals, years, batches, tranches, top_beneficiary_district,
     top_disbursement_district, top_bank, gender, occupation, status
LIMIT 1;
""".strip()


def _focusplus_wants_overall_summary(question: str, schemes: list[str]) -> bool:
    return schemes == ["Focus Plus"] and bool(_FOCUSPLUS_OVERALL_SUMMARY_CUE.search(question or ""))


async def _focusplus_overall_summary_answer(schemes: list[str], entity_result: dict) -> dict:
    rows = await run_readonly(_FOCUSPLUS_OVERALL_SUMMARY_SQL)
    r = rows[0]
    avg_per_beneficiary = float(r["amount"]) / r["beneficiaries"]
    answer = (
        f"Focus+ overall summary:\n"
        f"- Disbursement records (payments): {r['payments']:,}\n"
        f"- Unique beneficiaries: {r['beneficiaries']:,}\n"
        f"- Total amount disbursed: {_money(r['amount'])}\n"
        f"- Average disbursement per beneficiary: {_money(avg_per_beneficiary)}\n"
        f"- Financial years available: {r['years_list']}\n"
        f"- Batches: {r['batch_list']} (93K = legacy paid cohort, 12.5K = registration cohort)\n"
        f"- Tranches: {r['tranche_count']}\n"
        f"- Districts represented: {r['districts']}, plus {r['missing_district_rows']} "
        "payment records with no district resolved\n"
        f"- District with the most beneficiaries: {r['top_ben_district']} — "
        f"{r['top_ben_district_count']:,}\n"
        f"- District with the highest disbursement: {r['top_amt_district']} — "
        f"{_money(r['top_amt_district_amount'])}\n"
        f"- Top bank by disbursement: {r['top_bank_name']} — {_money(r['top_bank_amount'])}\n"
        f"- Gender split (12.5K cohort only, ~3% of beneficiaries): "
        f"{r['female']:,} female, {r['male']:,} male\n"
        f"- Farmers (12.5K cohort only): {r['farmers']:,}\n"
        f"- Status (12.5K cohort only): {r['pending']:,} Pending, {r['approved']:,} Approved, "
        f"{r['rejected']:,} Rejected\n"
        f"- Verification status (12.5K cohort only): {r['verified_approved']:,} Approved"
    )
    return {
        "route": "data",
        "intent": "DATA",
        "confidence": "high",
        "schemes": schemes,
        "resolved_entities": entity_result["resolved"],
        "sql": _FOCUSPLUS_OVERALL_SUMMARY_SQL,
        "sql_query": _FOCUSPLUS_OVERALL_SUMMARY_SQL,
        "row_count": 1,
        "rows": rows,
        "data": rows,
        "answer": answer,
    }


# ════ villages ════════════════════════════════════════════════════════════════════════════════════════
async def _focusplus_alias_district_collision(name: str, scheme: str = "Focus Plus") -> "dict[str, str]":
    """{level: canonical} when a bare Focus Plus place name reaches a DISTRICT
    only through an alias (a district HQ town) and is ALSO an exact Focus Plus
    village — else {}. "BAGHMARA" is South Garo Hills' HQ-town alias, the
    Baghmara block and village 273089 (37 beneficiaries). The shared collision
    check settles any district hit outright (right for district NAMES), so the
    village question was answered with the whole district's 8,612 (Focus Plus
    all-villages run 2026-09-27). Focus Plus has no constituency data, so no AC
    reading is offered."""
    d = resolve_dimension(name, scheme, "district")
    # Without a district alias, a scheme with constituency data still has the question
    # when the village name is also a constituency: CM Elevate Legacy's "Khliehriat"
    # offered three villages only (CM Elevate Legacy sheet TC-31, 2026-10-12).
    _alias = d.status == "resolved" and bool(d.canonical)
    if not _alias and scheme not in _AC_CAPABLE_SCHEMES:
        return {}
    if _alias and collapse_ws(str(name)).upper() == str(d.canonical).strip().upper():
        return {}          # the district's own name — never level-ambiguous
    try:
        names = await _scheme_village_names(scheme)
    except Exception:  # noqa: BLE001
        return {}
    if collapse_ws(str(name)).upper() not in names:
        # Not a village of THIS scheme, but exactly a constituency of a scheme that holds
        # constituency data: that is the only reading with data. "Khliehriat" offered three
        # statewide villages, none with a CM Elevate Legacy record (sheet TC-31, 2026-10-12).
        # A district HQ-town alias that is also a constituency asks district or constituency.
        if scheme in _AC_CAPABLE_SCHEMES:
            _want = collapse_ws(str(name)).upper()
            _ac = next((c for c in collision_canonical_names(scheme, "assembly_constituency")
                        if collapse_ws(str(c)).upper() == _want), None)
            if _ac:
                _dims = {"district": d.display or str(d.canonical).title()} if _alias else {}
                # the block of that name too: CM Elevate's "Mairang" / "Nongstoin" (blocks the sheet
                # asks about) lost their block reading here (final round 2026-10-13, OFF-002/007)
                _b = resolve_dimension(name, scheme, "block")
                if _b.status == "resolved" and str(_b.canonical).strip().upper() == _want:
                    _dims["block"] = _b.display or str(_b.canonical)
                elif scheme == "CM Elevate" and (_cb := await _cm_elevate_block_from_mention(str(name), [scheme])):
                    _dims["block"] = _place_title(_cb)
                _dims["assembly_constituency"] = _place_title(_ac)
                return _dims
        return {}
    dims = {"district": d.display or str(d.canonical).title()} if _alias else {}
    b = resolve_dimension(name, scheme, "block")
    if b.status == "resolved" and str(b.canonical).strip().upper() == str(name).strip().upper():
        dims["block"] = b.display or str(b.canonical)
    # A scheme that holds constituency data offers the constituency too: Focus Legacy's
    # "Khliehriat", "Mairang", "Nongstoin", "Resubelpara" (HQ towns that are also
    # constituencies) offered district / block / village only, so the constituency
    # could not be chosen (FOCUS sheet TC-28, 2026-10-12).
    if scheme in _AC_CAPABLE_SCHEMES:
        _want = collapse_ws(str(name)).upper()
        _ac = next((c for c in collision_canonical_names(scheme, "assembly_constituency")
                    if collapse_ws(str(c)).upper() == _want), None)
        if _ac:
            dims["assembly_constituency"] = _place_title(_ac)
    if not dims:
        return {}          # a plain village name: the village branches handle it
    dims["village"] = ""
    return dims


async def _focusplus_narrow_village(r: "Resolved", text: str, kw: dict,
                                    scheme: str = "Focus Plus") -> "Resolved":
    """Prefer the villages the asking scheme (Focus Plus or PMAY-G) actually holds.
    resolve_village reads the statewide dim_geography, so a name shared with
    villages that have no record in the scheme drew a "which of these?" pause, or
    resolved to a code with no rows (Salpara - Ward No.9 → 277769; Focus Plus
    all-villages run 2026-09-27). PMAY-G hit the same on 2026-09-28: "Bhangarpar"
    (unique in PMAY-G) paused against a fuzzy ANGARIPARA, "Bholarbhita (w)" went to
    272775 instead of 272776. An exact name of the scheme, narrowed by any block /
    district in `kw`, wins."""
    try:
        names = await _scheme_village_names(scheme)
    except Exception:  # noqa: BLE001 — without the catalogue, keep the generic answer
        return r
    key = collapse_ws(str(text or "")).upper()
    hits = names.get(key) or []
    for k in ("district", "block"):
        want = kw.get(k)
        if want and hits:
            narrowed = [h for h in hits if str(h.get(k) or "").upper() == str(want).upper()]
            hits = narrowed or hits
    codes = {h["village_code"] for h in hits}
    if len(codes) == 1:
        return Resolved("resolved", "village", text, canonical=hits[0]["village_code"],
                        confidence=1.0, display=_place_title(str(hits[0]["name"])))
    if len(codes) > 1:
        return Resolved("ambiguous", "village", text, candidates=hits)
    if r.status == "ambiguous":
        fp = {c["village_code"] for v in names.values() for c in v}
        keep = [c for c in r.candidates if c.get("village_code") in fp]
        if len(keep) == 1:
            return Resolved("resolved", "village", text, canonical=keep[0]["village_code"],
                            confidence=1.0, display=_place_title(str(keep[0]["name"])))
        if keep:
            r.candidates = keep
    return r
_FOCUSPLUS_VILLAGE_NAMES: "dict[str, list[dict]] | None" = None


async def _focusplus_village_names() -> "dict[str, list[dict]]":
    """UPPER(name) -> villages, for every village / ward in v_focus_plus. Loaded
    once per process (≈3,500 names). Placeholder "Unresolved" rows excluded."""
    global _FOCUSPLUS_VILLAGE_NAMES
    if _FOCUSPLUS_VILLAGE_NAMES is None:
        rows = await fetch_rows(
            "SELECT DISTINCT village_code, lgd_village_name, UPPER(lgd_block) AS block, "
            "UPPER(lgd_district) AS district FROM curated.v_focus_plus "
            "WHERE village_code IS NOT NULL AND entity_type <> 'Unresolved'", [])
        out: dict[str, list[dict]] = {}
        for r in rows:
            n = collapse_ws(str(r["lgd_village_name"] or ""))
            if n and not n.lower().startswith("unresolved"):
                out.setdefault(n.upper(), []).append(
                    {"village_code": r["village_code"], "name": n, "block": r["block"], "district": r["district"]})
        _FOCUSPLUS_VILLAGE_NAMES = out
    return _FOCUSPLUS_VILLAGE_NAMES


_FOCUSPLUS_RAW_BLOCKS: "set[str] | None" = None


async def _focusplus_raw_block_names() -> "set[str]":
    """UPPER(block_name_raw) of every Focus Plus row, loaded once per process."""
    global _FOCUSPLUS_RAW_BLOCKS
    if _FOCUSPLUS_RAW_BLOCKS is None:
        rows = await fetch_rows("SELECT DISTINCT UPPER(block_name_raw) AS b FROM curated.v_focus_plus "
                                "WHERE block_name_raw IS NOT NULL", [])
        _FOCUSPLUS_RAW_BLOCKS = {str(r["b"]) for r in rows if r["b"]}
    return _FOCUSPLUS_RAW_BLOCKS


def _fp_raw_block_comparison(node: exp.Expression) -> "tuple[exp.Column, str] | None":
    """(the block_name_raw column, the compared name) for `[UPPER(]block_name_raw[)] =
    / ILIKE [UPPER(]'X'[)]` (either side), else None."""
    if not isinstance(node, (exp.EQ, exp.ILike)):
        return None
    for col_side, val_side in ((node.this, node.expression), (node.expression, node.this)):
        col = sql_ast._unwrap(col_side) if col_side is not None else None
        val = sql_ast._unwrap(val_side) if val_side is not None else None
        if isinstance(col, exp.Column) and col.name.lower() == "block_name_raw" \
                and isinstance(val, exp.Literal) and val.is_string:
            return col, val.this
    return None


async def _focusplus_lgd_only_block(schemes: list[str], sql: str) -> str:
    """Focus Plus counts a block on block_name_raw (lgd_block is NULL on 15% of
    rows — prompt_builder._entities_block). But the source file predates ten
    LGD blocks (ADOKGRE, BATABARI, SIJU, MAWLAI, SHALLANG, RAMBRAI, PURAKHASIA,
    RI MULIANG, MAIRANG-TOWN COMMITTEE, WILLIAM NAGAR-MUNICIPAL BOARD — measured
    2026-10-02): no row carries those names, so "beneficiaries in Adokgre block"
    filtered block_name_raw = 'ADOKGRE', matched nothing and was answered "0 /
    the data doesn't cover it" — Adokgre has 754 (all-blocks run 2026-10-02).
    A block that is not a raw block name is filtered on lgd_block, where those
    villages were mapped.
    A raw block name the generator mistyped is snapped back first (KI-361,
    FOCUS-004 re-test 2026-10-22): "Shillong Municipal Board" was written
    `UPPER(block_name_raw) = 'SHILLONG-MUNICIPAL_BOARD'`, moved to lgd_block,
    refused by the resolved-block check, and after 4 attempts answered
    "couldn't build a working query" (5/5). A literal with the same letters as
    exactly one raw block (punctuation / underscore / spacing ignored, as KI-112
    does for CM Elevate) is that block."""
    if schemes != ["Focus Plus"] or not sql or not sql_ast.references_column(sql, "block_name_raw", "lgd_block"):
        return sql
    try:
        raw = await _focusplus_raw_block_names()
    except Exception:  # noqa: BLE001 — the lookup is an aid, never a reason to fail
        return sql
    if not raw:
        return sql
    # letters and digits only — NOT fold(), which drops a trailing "MUNICIPAL BOARD"
    # and would make BAGHMARA and BAGHMARA-MUNICIPAL BOARD the same name
    from app.entity_resolver import _squash
    by_letters: dict[str, list[str]] = {}
    for b in raw:
        by_letters.setdefault(_squash(b.upper()), []).append(b)

    # A block figure filtered on lgd_block under-reports (lgd_block is NULL on 15% of
    # rows): "Mawpat block" ran `lgd_block = 'MAWPAT'` -> ₹1,06,52,500 for ₹1,29,27,500,
    # "Rongram block" `UPPER(lgd_block) = 'RONGRAM'` -> ₹3.47 crore for ₹6.43 crore
    # (FOCUS-004 re-test 2026-10-30), although the prompt says never to. A name that IS a
    # raw block is moved to block_name_raw — not inside a village question, whose rows
    # are mapped by LGD.
    village_q = sql_ast.references_column(sql, "village_code", "lgd_village_name")

    def _swap(tree: exp.Expression) -> None:
        if not village_q:
            for node in list(tree.find_all(exp.EQ)):
                for c_side, v_side in ((node.this, node.expression), (node.expression, node.this)):
                    col = sql_ast._unwrap(c_side) if c_side is not None else None
                    val = sql_ast._unwrap(v_side) if v_side is not None else None
                    if isinstance(col, exp.Column) and col.name.lower() == "lgd_block" \
                            and isinstance(val, exp.Literal) and val.is_string \
                            and val.this.strip().upper() in raw:
                        name = val.this.strip().upper()
                        logger.info("Focus Plus: block %r filtered on lgd_block -> block_name_raw", name)
                        raw_col = exp.column("block_name_raw", table=col.table or None)
                        node.replace(exp.EQ(this=exp.Upper(this=raw_col), expression=exp.Literal.string(name)))
                        break
        for node in list(tree.find_all(exp.EQ, exp.ILike)):
            hit = _fp_raw_block_comparison(node)
            if hit is None:
                continue
            col, value = hit
            name = value.strip().upper()
            # an ILIKE pattern ('%siju%') is checked on its name and stays a pattern
            wild = isinstance(node, exp.ILike) and "%" in name
            if not name or name.replace("%", "").strip() in raw:
                # The stored value is title case ("Mawkynrew"); the generator sometimes
                # drops the UPPER(): `block_name_raw = 'MAWKYNREW'` matched nothing and
                # was answered "the data does not cover … Mawkynrew" (FOCUS-004 run
                # 2026-10-30: Mawkynrew, Mawphlang). An equality on a known block is
                # compared in upper case on both sides.
                if isinstance(node, exp.EQ) and name and (value != name or not isinstance(col.parent, exp.Upper)):
                    logger.info("Focus Plus: block literal %r compared in upper case", value)
                    node.replace(exp.EQ(this=exp.Upper(this=col.copy()), expression=exp.Literal.string(name)))
                continue
            same = [] if wild else by_letters.get(_squash(name), [])
            if len(same) == 1:
                logger.info("Focus Plus: block literal %r -> stored %r", name, same[0])
                node.replace(exp.EQ(this=exp.Upper(this=col.copy()), expression=exp.Literal.string(same[0])))
                continue
            logger.info("Focus Plus: block %r is not a block_name_raw value — filtered on lgd_block", name)
            lgd = exp.column("lgd_block", table=col.table or None)
            node.replace(exp.ILike(this=lgd, expression=exp.Literal.string(name)) if wild
                         else exp.EQ(this=lgd, expression=exp.Literal.string(name)))
        return None
    return sql_ast.transform(sql, _swap)


# Held-out NL->SQL FP-05 (accuracy round 2026-11-12, KI-687): "Give me the Focus Plus amount disbursed
# in each block of North Garo Hills district" was GROUPED BY lgd_block, which is NULL on 15% of the
# rows: six rows incl. a blank one, Kharkutta ₹4.25 crore for the ₹5.54 crore its block_name_raw holds.
# A block BREAKDOWN is on block_name_raw (the BLOCK COLUMN rule the prompt states; the filters are
# moved by _focusplus_lgd_only_block). Only a single plain SELECT that never reads block_name_raw, a
# village column or an lgd_block filter: a query that does any of these chose its column on purpose.
def _focusplus_block_breakdown_on_raw(schemes: list[str], sql: str) -> str:
    if schemes != ["Focus Plus"] or not sql or not sql_ast.references_column(sql, "lgd_block") \
            or sql_ast.references_column(sql, "block_name_raw", "village_code", "lgd_village_name"):
        return sql
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or len(list(tree.find_all(exp.Select))) != 1:
        return sql
    group = tree.args.get("group")
    if group is None or not any(isinstance(sql_ast._unwrap(g), exp.Column) and sql_ast._unwrap(g).name.lower() == "lgd_block"
                                for g in group.expressions):
        return sql
    where = tree.args.get("where")
    if where is not None and sql_ast.references_column(where, "lgd_block"):
        return sql

    def raw(col: exp.Column) -> exp.Expression:
        return exp.Upper(this=exp.column("block_name_raw", table=col.table or None))

    for col in list(tree.find_all(exp.Column)):
        if col.name.lower() != "lgd_block":
            continue
        if col.parent is tree and col in tree.expressions:          # a bare projection keeps its name
            col.replace(exp.alias_(raw(col), "lgd_block"))
        else:
            col.replace(raw(col))
    out = sql_ast.to_sql(tree)
    logger.info("Focus Plus: a block breakdown on lgd_block is grouped on block_name_raw (KI-687)")
    return out


def _focusplus_ac_name_case(schemes: list[str], sql: str) -> str:
    """Focus Plus ac_name is stored Title case ("East Shillong", "Nongkrem"); the generator
    wrote `ac_name = 'EAST SHILLONG'`, matched nothing and answered "0 … not a known
    assembly constituency" (all-constituencies run 2026-10-30: East / North / West Shillong).
    An equality on ac_name is compared in upper case on both sides."""
    if schemes != ["Focus Plus"] or not sql or not sql_ast.references_column(sql, "ac_name"):
        return sql

    def _swap(tree: exp.Expression) -> None:
        for node in list(tree.find_all(exp.EQ)):
            for c_side, v_side in ((node.this, node.expression), (node.expression, node.this)):
                col = sql_ast._unwrap(c_side) if c_side is not None else None
                val = sql_ast._unwrap(v_side) if v_side is not None else None
                if isinstance(col, exp.Column) and col.name.lower() == "ac_name" \
                        and isinstance(val, exp.Literal) and val.is_string \
                        and (val.this != val.this.upper() or not isinstance(col.parent, exp.Upper)):
                    node.replace(exp.EQ(this=exp.Upper(this=col.copy()),
                                        expression=exp.Literal.string(val.this.strip().upper())))
                    break
        return None
    return sql_ast.transform(sql, _swap)


# ════ SQL generation guards ═══════════════════════════════════════════════════════════════════════════
_FOCUSPLUS_BENEFICIARY_QUALIFIER = Matcher(Alt(
    W("woman", "women", "female", "male", "gender", "farmer", "occupation", "status", "pending", "approved",
      "rejected", "instalment", "instalments", "installment", "installments", "legacy", "93k", "average", "mean",
      "per", "percentage", "percent", "vs", "versus", "each", "every", "wise", "breakdown", "split",
      "distribution", "highest", "lowest"),
    W("verif", "tranch", "batch", "compare", "rank", prefix=True), _FP_12_5K, "per cent",
    Pred(lambda w: len(w) == 4 and w[:3].lower() == "top" and is_int(w[3])),
    Seq("top", Pred(lambda w: len(w) == 1 and is_int(w))),
))


def _focusplus_single_district_beneficiary_guard(
        question: str, schemes: list[str], entity_result: dict, sql: str) -> str:
    """User-directed exception (2026-09-13): "how many Focus Plus beneficiaries
    in <one district>" must answer with ONE number, not the three-reading
    ambiguity table (FOCUS PLUS RULES rule 6). The prose exception added to
    schema_context.py doesn't reliably win against the concrete multi-column
    worked example under LLM sampling — confirmed live, the generator kept
    emitting the 3/4-column shape even with the exception text in-prompt and
    the correctly-ranked single-column few-shot example alongside it.
    Deterministic rewrite instead, scoped narrowly so every OTHER beneficiary
    shape (statewide, "each district", a comparison, a gender/status/tranche/
    batch-scoped question, or one with a specific year or tranche pinned) is
    left completely alone — those still need their own, different SQL.

    Updated 2026-09-13 (client UAT sheet, FOCUS-001): the original version of
    this template used `COUNT(DISTINCT source_sl_no) WHERE batch_label = '93K'
    AND NOT has_geo_conflict`, written before curated.fact_focus_plus_disbursement
    grew the generated beneficiary_key column (batch_label || ':' || source_sl_no,
    see semantic.column_catalog). That template was reproduced live against
    megh_db and silently dropped every real beneficiary it wasn't built to see:
    the entire 12.5K cohort (4,670 people in West Garo Hills alone — batch_label
    = '93K' excludes them outright) and every has_geo_conflict row (136 more in
    West Garo Hills) even though has_geo_conflict only means the source's block
    name disagreed with the LGD roster for that village — the roster's district
    is what v_focus_plus.lgd_district stores either way, so those rows belong in
    the district count as much as any other row. beneficiary_key already spans
    both cohorts as one identifier space, so neither filter is needed any more."""
    if schemes != ["Focus Plus"]:
        return sql
    if "beneficiar" not in question.lower():
        return sql
    resolved = entity_result.get("resolved", {})
    district = resolved.get("district")
    if not district or resolved.get("district_list"):
        return sql
    if resolved.get("block") or resolved.get("village_code"):
        return sql
    if resolved.get("year_key") or resolved.get("tranche_label"):
        return sql
    if _FOCUSPLUS_BENEFICIARY_QUALIFIER.search(question):
        return sql
    return (
        "SELECT COUNT(DISTINCT beneficiary_key) AS beneficiaries\n"
        "FROM curated.v_focus_plus\n"
        f"WHERE lgd_district = '{district}';"
    )


# ════ fixed-shape queries and answers ═════════════════════════════════════════════════════════════════
# Focus + sheet FOCUS-018 / 019 (2026-10-10): "status breakdown for <tranche / batch>".
# The 12.5K cohort alone carries focus_status; the 93K cohort is on Tranches 1-4 with the
# status blank. Tranch 1-3 got a "no status data" note without the 93,286 people it
# covers, Tranch 4 only the 12,527 with a status, and "the 93K batch" was answered
# "373,144 registrations" (payment rows, mislabelled). One fixed query: beneficiaries
# by status for the named tranche(s) or batch, blanks counted as "(not recorded)".
_FP_STATUS_BREAKDOWN_MATCH = Matcher(Alt(
    Seq("status", W("wise", "breakdown", "distribution", "split")),
    W("statuswise", "statusbreakdown", "statusdistribution", "statussplit"),
    _PmayNear(W("breakdown", "distribution", "split"), W("status"), None, lambda ch: ch == "?"),
    Seq("by", Opt("focus"), "status")))
_FP_VERIF_WORD = Matcher(W("verif", prefix=True))


def _fp_status_cohort_query(question: str, schemes: list[str], resolved: dict) -> "tuple[str, list, str] | None":
    if schemes != ["Focus Plus"] or not _FP_STATUS_BREAKDOWN_MATCH.search(question or "") \
            or _FP_VERIF_WORD.search(question or ""):
        return None
    if any((resolved or {}).get(k) for k in ("district", "block", "village", "village_code", "district_list",
                                             "block_list", "assembly_constituency")):
        return None
    tr = (resolved or {}).get("tranche_label")
    m = _FOCUSPLUS_BATCH_WORD.search(question or "")
    if tr:
        col, val = "tranche_label", list(tr) if isinstance(tr, list) else [tr]
    elif m:
        col, val = "batch_label", ["12.5K" if m.group(0).lower().startswith("12") else "93K"]
    else:
        return None
    sql = ("/* fp-status-cohort */ SELECT COALESCE(focus_status, '(not recorded)') AS focus_status, "
           "COUNT(DISTINCT beneficiary_key) AS beneficiaries FROM curated.v_focus_plus "
           f"WHERE {col} = ANY($1::text[]) GROUP BY 1 ORDER BY 2 DESC")
    return sql, [val], sql.replace("$1::text[]", "ARRAY[" + ", ".join(f"'{v}'" for v in val) + "]")


def _fp_status_cohort_answer(sql: str, rows: list[dict], params: list) -> str:
    scope = " and ".join(params[0]) if params and params[0] else "that selection"
    scope = scope if sql_ast.references_column(sql, "tranche_label") else f"the {scope} batch"
    total = sum(int(_as_number(r.get("beneficiaries")) or 0) for r in rows)
    parts = [f"{r['focus_status'] if r['focus_status'] != '(not recorded)' else 'status not recorded'} "
             f"{int(_as_number(r.get('beneficiaries')) or 0):,}" for r in rows]
    blank = sum(int(_as_number(r.get("beneficiaries")) or 0) for r in rows if r["focus_status"] == "(not recorded)")
    out = f"Focus Plus status breakdown for {scope} — {total:,} beneficiaries: " + "; ".join(parts) + "."
    if blank:
        out += (f" Status is recorded only for the 12.5K registration cohort (Tranch 4); the {blank:,} "
                "beneficiaries of the 93K legacy cohort have no status on their records.")
    return out


# ════ SQL rewrites ════════════════════════════════════════════════════════════════════════════════════
_VERIFICATION_MENTION = Matcher(Pred(lambda w: "verif" in w.lower()))


def _fp_ends(stem: str) -> Pred:
    """A word ending in `stem` (anything may come before the ending, as before)."""
    return Pred(lambda w: w.lower().endswith(stem))


_STATUS_ENUMERATE_AUDIT = Matcher(Alt(
    Seq(_fp_ends("what"), ANY, "status", W("values", prefix=True), sep="space"),
    Seq(_fp_ends("which"), ANY, "status", W("values", prefix=True), sep="space"),
    Seq(_fp_ends("status"), "values", "are", W("recorded", prefix=True), sep="space"),
    Seq(_fp_ends("what"), W("status", "statuses"), Alt(W("exist", prefix=True), Seq("are", W("there", prefix=True),
                                                                                    sep="space")), sep="space"),
))


def _focusplus_drop_unrequested_verification_status(question: str, schemes: list[str],
                                                     sql: str) -> str:
    if schemes != ["Focus Plus"]:
        return sql
    if _VERIFICATION_MENTION.search(question) or _STATUS_ENUMERATE_AUDIT.search(question):
        return sql
    def _is_vs(node: exp.Expression) -> bool:
        node = node.this if isinstance(node, exp.Alias) else node
        return isinstance(node, exp.Column) and node.name.lower() == "verification_status"

    dropped = []

    def _drop(tree: exp.Expression) -> None:
        for sel in list(tree.find_all(exp.Select)):
            group = sel.args.get("group")
            if group is None:
                continue
            names = {c.name.lower() for c in group.expressions if isinstance(c, exp.Column)}
            if "focus_status" not in names or "verification_status" not in names:
                continue
            group.set("expressions", [g for g in group.expressions if not _is_vs(g)])
            keep = [e for e in sel.expressions if not _is_vs(e)]
            if keep:
                sel.set("expressions", keep)
            order = sel.args.get("order")
            if order is not None:
                ords = [o for o in order.expressions if not _is_vs(o.this)]
                order.set("expressions", ords) if ords else sel.set("order", None)
            dropped.append(sel)
        return None

    out = sql_ast.transform(sql, _drop)
    if dropped:
        logger.info("dropped unrequested verification_status column from a focus_status breakdown")
    return out


# ════ verify and repair ═══════════════════════════════════════════════════════════════════════════════
# Focus Plus single-village queries (all-villages run 2026-09-27). With ONE
# village resolved, the generator still wrote `UPPER(block_name_raw) =
# 'WAGESIK'` (a ward name in the block column), `UPPER(district_name_raw) =
# 'CHOBAGOK'`, `lgd_village_name = 'WARD NO. 4'` (Focus Plus stores it mixed
# case) or a block/district beside the right village_code — every one returned
# 0 or NULL for a place with real payments. The code alone names the place, so
# the WHERE is rebuilt condition by condition: place conditions go, the one
# village_code goes in, everything else (year, tranche, status…) stays.
_FP_PLACE_COLS = frozenset({"lgd_district", "lgd_block", "block_name_raw", "district_name_raw",
                            "lgd_village_name", "village_name_raw", "entity_type", "village_code",
                            "geography_key"})


def _fp_place_cond(cond: exp.Expression) -> bool:
    """A WHERE condition on a place column (UPPER()/TRIM() wrapped or not, IS NOT NULL,
    IN, LIKE …): the resolved village_code replaces it."""
    return bool(sql_ast.columns(cond) & _FP_PLACE_COLS)


def _fp_place_literal(cond: "str | exp.Expression", scheme: str = "Focus Plus") -> bool:
    """True when a condition's literal is a PLACE name on some other column —
    `tranche_label ILIKE '%GASUAPARA%'` put the village's block into the tranche
    filter and zeroed RONGBOKGRE's disbursement (all-villages run 2026-09-27)."""
    # a text condition is parsed (an unparseable one has no literals)
    lits = [" ".join(x.replace("%", " ").replace("_", " ").split()).upper() for x in sql_ast.string_literals(cond)]
    lits = [x for x in lits if x]
    if not lits:
        return False
    places = {" ".join(str(n).split()).upper()
              for d in ("block", "district") for n in canonical_names(scheme, d)}
    return any(x in places for x in lits)


# CM Elevate (all-villages smoke run 2026-09-28, KI-106) hit every shape this
# rebuild handles: the block alone (RONGAP SONGGITAL answered with Songsak's 47),
# the village name in lgd_district ('MAWDEM DOMPHLANG'), a misspelled district
# beside the code ('WEST JAINTEIA HILLS' → 0), and an upper-cased lgd_village_name
# that matched nothing (PDENGSHNONG MAWPHYLLUN MARBISU → 0).
_PIN_VILLAGE_WHERE_SCHEMES = (["Focus Plus"], ["CM Elevate"])


# KI-359 / KI-426 (sheet FOCUS-002 2026-10-22; catalogue E7 2026-10-29): "Focus+ beneficiaries
# in each district" / "payments by district" grouped on district_name_raw (West Garo Hills
# 30,400 / 35,059) while every other Focus Plus district figure — a single district, the
# metric catalogue, the scheme cards — reads lgd_district (30,369 / 35,039; the ingestion
# team re-mapped 175 rows). One column for every district figure; a question that asks
# for the RAW / source district spelling keeps it.
_FP_RAW_ASKED = Matcher(W("raw", "source", "original", "spreadsheet", "sheet"))


def _focusplus_lgd_district_column(question: str, schemes: list[str], sql: str) -> str:
    if schemes != ["Focus Plus"] or not sql or _FP_RAW_ASKED.search(question or ""):
        return sql

    def fn(tree):
        for col in list(tree.find_all(exp.Column)):
            if col.name.lower() == "district_name_raw":
                col.replace(exp.column("lgd_district", table=col.table or None))
        return None
    out = sql_ast.transform(sql, fn)
    if out != sql:
        logger.info("Focus Plus district_name_raw -> lgd_district (KI-359)")
    return out


def _focusplus_district_group_not_null(schemes: list[str], sql: str) -> str:
    """A ranked (ORDER BY / HAVING) Focus Plus district breakdown leaves out the one
    record with no district. "Are there districts where Focus+ coverage is very
    low?" was answered "1 villages covered" — the NULL group ranked lowest (UAT
    T13.3, cross-scheme re-test 2026-10-22, twice in three runs). A plain district
    list keeps that row, so its figures still add up to the statewide total."""
    if schemes != ["Focus Plus"]:
        return sql
    tree = sql_ast.parse_one(sql or "")
    sel = sql_ast.outer_select(tree) if tree is not None else None
    group = sel.args.get("group") if sel is not None else None
    if group is None or (sel.args.get("order") is None and sel.args.get("having") is None):
        return sql
    if sql_ast.tables(sel) != {"v_focus_plus"}:
        return sql
    keys = [c for c in group.expressions if isinstance(c, exp.Column)
            and c.name.lower() in ("lgd_district", "district_name_raw")]
    if len(keys) != 1:
        return sql
    col = exp.column(keys[0].name, table=keys[0].table or None)
    for node in sql_ast.filter_conditions(sql, keys[0].name.lower()):
        if isinstance(node, exp.Not) or (isinstance(node, exp.Is) and node.args.get("negate")):
            return sql                   # already "IS NOT NULL"
    sel.where(exp.Not(this=exp.Is(this=col, expression=exp.Null())), append=True, copy=False)
    logger.info("Focus Plus ranked district breakdown: no-district record left out (T13.3)")
    return sql_ast.to_sql(tree)


def _focusplus_pin_village_where(schemes: list[str], entity_result: dict, sql: str) -> str:
    code = (entity_result.get("resolved") or {}).get("village_code")
    if schemes not in _PIN_VILLAGE_WHERE_SCHEMES or not code or isinstance(code, (list, tuple)) or not sql:
        return sql
    # "geography_key IN (SELECT geography_key FROM curated.dim_geography WHERE
    # lgd_village_name = …)" names the village by text (mixed case in Focus
    # Plus → NULL for NONGRIM HILLS, 2026-09-27); the resolved code replaces it.
    def _pin() -> exp.Expression:
        return exp.EQ(this=exp.column("village_code"), expression=exp.Literal.number(int(code)))

    def _subquery_to_code(tree: exp.Expression) -> None:
        for node in list(tree.find_all(exp.In)):
            col = sql_ast._unwrap(node.this)
            if isinstance(col, exp.Column) and col.name.lower() == "geography_key" and node.args.get("query"):
                node.replace(_pin())
        return None

    sql = sql_ast.transform(sql, _subquery_to_code)
    tree = sql_ast.parse_one(sql)
    # one plain SELECT only: no subquery, CTE, join, set operation or OR (an OR between
    # places cannot be rebuilt condition by condition)
    if tree is None or not isinstance(tree, exp.Select) or len(sql_ast.selects(tree)) != 1 \
            or tree.find(exp.Join, exp.With, exp.SetOperation, exp.Or) is not None:
        return sql

    def _rebuild(t: exp.Expression) -> None:
        where = t.args.get("where")
        if where is None:
            # no WHERE at all: the village was dropped entirely — add it
            t.set("where", exp.Where(this=_pin()))
            return None
        # the top-level AND conjuncts (a literal holding ' and ' is one literal on the tree:
        # 'PRIME Small Enterprise Empowerment and Development (SEED)' stays whole —
        # CM Elevate all-villages smoke run 2026-09-28); COUNT(*) FILTER (WHERE …) in
        # the select list is not this WHERE and is left alone
        conds = list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this]
        kept = [c for c in conds if not _fp_place_cond(c) and not _fp_place_literal(c, schemes[0])]
        where.set("this", exp.and_(_pin(), *kept, copy=False))
        return None

    new = sql_ast.transform(sql, _rebuild)
    if new != sql:
        logger.info("%s: WHERE pinned to the one resolved village_code %s", schemes[0], code)
    return new


# ════ answer numbers and guarantees ═══════════════════════════════════════════════════════════════════
# ── Focus Plus answer guarantees (use-case QA 2026-09-27) ────────────────────
# The composer stated every figure correctly but left out what the use cases
# ask for: the share of each status / gender / occupation (KI-060), the
# difference and the higher side of a two-way comparison (KI-061), and it
# printed rupee amounts as bare "126197500.00" (KI-064). Prose rules had not
# held these under sampling, so, per the project pattern, each is guaranteed
# deterministically after composing — computed from the result rows, or from a
# parameter-bound recount that must reproduce the bot's own figure first.
_FP_PERSON_COLS = {"focus_status": "status", "verification_status": "verification status",
                   "gender": "gender", "occupation": "occupation"}
# Column names: amount / disburs / rupee anywhere, or a name ending in _rs / _inr.
_FP_MONEY_COL = Matcher(Alt(Pred(lambda w: any(s in w.lower() for s in ("amount", "disburs", "rupee"))),
                            Before(Pred(lambda w: w.lower().endswith(("_rs", "_inr"))), END)))
_FP_COHORT_TAIL = ("these fields are recorded only for the 12.5K registration cohort; "
                   "the 93K legacy cohort has none of them")


# KI-365 (sheet FOCUS-020..022, re-checked live 2026-10-29): "women / farmers / approved
# during FY 2022-23" -> 0 was right, but the answer said "the data doesn't cover … the only
# available figure is 0" instead of why: these fields exist only for the 12.5K cohort.
_FP_COHORT_FIELD_WORDS = (
    (Matcher(W("women", "woman", "female", "females", "gender", "men", "male")), "gender"),
    (Matcher(W("farmer", "farmers", "occupation", "occupations")), "occupation"),
    (Matcher(W("approved", "approval", "pending", "status", "verified", "verification")), "status"),
)


def _fp_cohort_zero_answer(question: str, schemes: "list[str]", rows: list, answer: str) -> str:
    """A zero for a 12.5K-only field, explained (KI-365); else `answer` unchanged."""
    if schemes != ["Focus Plus"] or not rows or len(rows) != 1:
        return answer
    vals = [_as_number(v) for v in rows[0].values()]
    nums = [v for v in vals if v is not None]
    if not nums or any(v != 0 for v in nums):
        return answer
    field = next((f for m, f in _FP_COHORT_FIELD_WORDS if m.search(question or "")), None)
    if field is None:
        return answer
    return (f"0 — but read it with care: Focus Plus records {field} only for the 12.5K registration "
            f"cohort (FY 2025-26); the 93K legacy cohort, which holds the FY 2022-23 payments, has no "
            f"{field} field at all. So this 0 means \"not recorded\", not \"none\". Ask for FY 2025-26 "
            f"to see the {field} figures.")


def _fp_rupees(v: "int | float") -> str:
    return f"₹{float(v):,.2f}"


_FP_TRANCH_WORD = Matcher(W("Tranch", case=True))


def _fp_title(label: object) -> str:
    s = str(label)
    s = s.title() if s.isupper() else s
    # the stored tranche spelling is "Tranch 1"; say it the way officers do
    return _FP_TRANCH_WORD.sub("Tranche", s)


def _fp_numeric_cols(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for r in rows:
        for k, v in r.items():
            if k not in cols and _as_number(v) is not None and not _NONSTAT_COL.search(k):
                cols.append(k)
    return cols


def _fp_count_col(rows: list[dict]) -> "str | None":
    """The one count column (not money) of a Focus Plus result, or None."""
    cols = [c for c in _fp_numeric_cols(rows) if not _FP_MONEY_COL.search(c)]
    if len(cols) == 1:
        return cols[0]
    ben = [c for c in cols if "benefic" in c.lower()]
    return ben[0] if len(ben) == 1 else None


def _fp_breakdown_shares(answer: str, rows: list[dict]) -> str:
    """'Share of the 12,527 beneficiaries with a recorded status: Pending
    94.29%, …' for a GROUP BY status / verification / gender / occupation
    result (FOCUS-008, 011, 012). Shares are of the rows' own total, NULL group
    excluded, so they add to 100."""
    person = [c for c in (rows[0] if rows else {}) if c in _FP_PERSON_COLS]
    count_col = _fp_count_col(rows)
    if len(person) != 1 or not count_col:
        return answer
    attr = person[0]
    numeric = set(_fp_numeric_cols(rows))
    if any(k != attr and k not in numeric for k in rows[0]):
        # a second label column (district x status, year x gender): shares of
        # the grand total would mix groups — leave it to the table
        return answer
    pairs: list[tuple[object, "int | float"]] = []
    for r in rows:
        n = _as_number(r.get(count_col))
        if r.get(attr) is not None and n is not None:
            pairs.append((r[attr], n))
    total = sum(v for _l, v in pairs)
    if not pairs or total <= 0:
        return answer
    shares = [(lab, round(100.0 * v / total, 2)) for lab, v in pairs]
    if _answer_has_pcts(answer, [p for _l, p in shares]):
        return answer
    line = (f"Share of the {total:,} {_metric_label(count_col)} with a recorded "
            f"{_FP_PERSON_COLS[attr]}: " + ", ".join(f"{lab} {p:.2f}%" for lab, p in shares)
            + f" ({_FP_COHORT_TAIL}).")
    return f"{answer.rstrip()}\n\n{line}"


# The WHERE shapes the share recount understands. Anything else (OR, a
# subquery, a join, IN-lists) is left alone — better no percentage than a
# percentage over a different population than the bot's own figure.
_FP_WHERE_COLS = {"batch_label", "focus_status", "verification_status", "gender", "occupation",
                  "financial_year_short", "financial_year", "lgd_district", "block_name_raw",
                  "lgd_block", "lgd_village_name", "tranche_label"}
# Any of these anywhere in the query (a FILTER, a HAVING …) puts it outside the shapes
# the recount understands.
_FP_RECOUNT_UNSAFE = tuple(cls for cls in (getattr(exp, n, None) for n in (
    "Join", "With", "SetOperation", "Subquery", "Or", "In", "Like", "ILike", "SimilarTo",
    "Between", "NEQ", "GT", "GTE", "LT", "LTE", "NullSafeEQ", "NullSafeNEQ",
)) if isinstance(cls, type))


def _fp_plain_side(node: "exp.Expression | None", kind: str) -> "tuple[exp.Expression, bool] | None":
    """(column or string literal, wrapped in UPPER) for `x` / `UPPER(x)`, else None."""
    up = isinstance(node, exp.Upper)
    inner = node.this if up else node
    if kind == "col" and isinstance(inner, exp.Column) and not inner.table:
        return inner, up
    if kind == "val" and isinstance(inner, exp.Literal) and inner.is_string:
        return inner, up
    return None


def _fp_parse_where(sql: str) -> "list[tuple[str, str, bool]] | None":
    """[(column, value, compared_upper)] for a single-SELECT Focus Plus count,
    or None when the WHERE holds anything but plain equality / IS NOT NULL.
    Read on the tree: a keyword inside a literal ('Others') is a literal."""
    tree = sql_ast.parse_one(sql)
    if not isinstance(tree, exp.Select) or len(sql_ast.selects(tree)) != 1 \
            or tree.find(*_FP_RECOUNT_UNSAFE) is not None:
        return None
    where = tree.args.get("where")
    if where is None:
        return None
    conds = list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this]
    out: list[tuple[str, str, bool]] = []
    for part in conds:
        # col IS NOT NULL (Is(negate=True), or NOT (col IS NULL) in older SQLGlot)
        is_node = part.this if isinstance(part, exp.Not) else part
        negated = isinstance(part, exp.Not) != bool(is_node.args.get("negate"))
        if isinstance(is_node, exp.Is) and negated and isinstance(is_node.this, exp.Column) \
                and isinstance(is_node.expression, exp.Null):
            continue
        if not isinstance(part, exp.EQ):
            return None
        col, val = _fp_plain_side(part.this, "col"), _fp_plain_side(part.expression, "val")
        if col is None or val is None or col[0].name.lower() not in _FP_WHERE_COLS:
            return None
        out.append((col[0].name.lower(), val[0].this, col[1] or val[1]))
    return out


def _fp_scope_text(preds: list[tuple[str, str, bool]]) -> str:
    bits = []
    for col, val, _u in preds:
        if col in ("lgd_district",):
            bits.append(f"in {_fp_title(val)}")
        elif col in ("block_name_raw", "lgd_block"):
            bits.append(f"in {_fp_title(val)} block")
        elif col in ("financial_year_short", "financial_year"):
            bits.append(f"in FY {val}")
        elif col == "tranche_label":
            bits.append(f"in {val}")
    return (" " + " ".join(bits)) if bits else ""


async def _fp_single_count_share(answer: str, sql: str, rows: list[dict]) -> str:
    """'That is 94.29% of the 12,527 beneficiaries in the 12.5K registration
    cohort …' for a one-number count filtered on status / verification /
    gender / occupation (FOCUS-013, 014, 016). The share is computed by a
    parameter-bound recount of the SAME filters, and is stated only when that
    recount reproduces the bot's own figure — so it can never describe a
    different population than the number beside it."""
    if len(rows) != 1:
        return answer
    metrics = [(k, v) for k, v in _row_metrics(rows[0]) if not _FP_MONEY_COL.search(k)]
    if len(metrics) != 1 or len(_row_metrics(rows[0])) != 1:
        return answer
    value = metrics[0][1]
    preds = _fp_parse_where(sql)
    if not preds or not any(c in _FP_PERSON_COLS for c, _v, _u in preds):
        return answer

    def _where(ps: list[tuple[str, str, bool]]) -> "tuple[str, list[str]]":
        conds, params = [], []
        for col, val, up in ps:
            params.append(val.upper() if up else val)
            conds.append(f"{'UPPER(' + col + ')' if up else col} = ${len(params)}")
        return " AND ".join(conds), params

    num_preds = preds if any(c == "batch_label" for c, _v, _u in preds) \
        else preds + [("batch_label", "12.5K", False)]
    den_preds = [p for p in num_preds if p[0] not in _FP_PERSON_COLS]
    try:
        nw, npar = _where(num_preds)
        dw, dpar = _where(den_preds)
        base = "SELECT COUNT(DISTINCT beneficiary_key) AS n FROM curated.v_focus_plus WHERE "
        num_rows, den_rows = await asyncio.gather(fetch_rows(base + nw, npar),
                                                  fetch_rows(base + dw, dpar))
        num, den = num_rows[0]["n"], den_rows[0]["n"]
    except Exception:  # noqa: BLE001
        logger.warning("Focus Plus share recount failed — answer left unchanged", exc_info=True)
        return answer
    if not den or int(num) != int(value):
        logger.info("Focus Plus share skipped: recount %s != bot figure %s", num, value)
        return answer
    pct = round(100.0 * int(num) / int(den), 2)
    if _answer_has_pcts(answer, [pct]):
        return answer
    fields = ", ".join(sorted({_FP_PERSON_COLS[c] for c, _v, _u in preds if c in _FP_PERSON_COLS}))
    line = (f"That is {pct:.2f}% of the {int(den):,} beneficiaries in the 12.5K registration "
            f"cohort{_fp_scope_text(den_preds)} ({fields} is recorded only for that cohort; "
            f"the 93K legacy cohort has none).")
    return f"{answer.rstrip()}\n\n{line}"


_FP_COMPARE_CUE = Matcher(Alt(
    W("compar", prefix=True), W("versus", "vs"), "difference between",
    # which … higher, with only letters, digits and spaces (at most 30 characters) between
    _PmayNear(W("which"), W("higher", "more", "larger", "bigger", "greater"), 30,
              lambda ch: not (_pmay_is_word_char(ch) or ch.isspace()))))
_FP_COMBINED_SENT = Matcher(Alt(
    W("combined", "together"), "in total", "across both",
    Seq("both", Pred(lambda w: w.isascii() and w.isalpha()), W("is", "are"), sep="space")))
_FP_HIGHER_WORD = Matcher(W("higher", "more", "exceed", "ahead", "greater", "larger"))


def _fp_says_higher(answer: str, name: str) -> bool:
    """`name` (any case) is followed, within its sentence (no '.' between), by higher / more /
    exceed / ahead / greater / larger as a whole word."""
    low, key = answer.lower(), name.lower()
    if not key:
        return False
    k = low.find(key)
    while k >= 0:
        e = k + len(key)
        dot = answer.find(".", e)
        seg = answer[k:dot if dot >= 0 else len(answer)]
        # a word that begins after the name (one glued onto the name's last word does not count)
        if any(h.start() >= len(key) for h in _FP_HIGHER_WORD.finditer(seg)):
            return True
        k = low.find(key, k + 1)
    return False


def _fp_split_after_stop(text: str) -> "list[str]":
    """Split after a ".", "!" or "?" that is followed by whitespace (the whitespace is dropped)."""
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


def _fp_comparison(question: str, rows: list[dict], answer: str) -> str:
    """State the difference and the higher side of a two-way comparison
    (FOCUS-026, 027, 028). The composer gave both figures and then their
    combined total — a number nobody asked for — in place of the difference."""
    if len(rows) != 2 or not _FP_COMPARE_CUE.search(question or ""):
        return answer
    labels = [k for k in rows[0] if _as_number(rows[0][k]) is None and rows[0][k] != rows[1].get(k)]
    if len(labels) != 1:
        return answer
    num_cols = _fp_numeric_cols(rows)
    q = question.lower()
    pick = None
    if "benefic" in q:
        pick = next((c for c in num_cols if "benefic" in c.lower()), None)
    if pick is None and any(w in q for w in ("disburs", "amount", "money", "paid", "fund", "rupee")):
        pick = next((c for c in num_cols if _FP_MONEY_COL.search(c)), None)
    if pick is None and "payment" in q:
        pick = next((c for c in num_cols if "payment" in c.lower()), None)
    if pick is None and len(num_cols) == 1:
        pick = num_cols[0]
    if pick is None:
        return answer
    a, b = _as_number(rows[0].get(pick)), _as_number(rows[1].get(pick))
    if a is None or b is None:
        return answer
    la, lb = _fp_title(rows[0][labels[0]]), _fp_title(rows[1][labels[0]])
    money = bool(_FP_MONEY_COL.search(pick))

    def f(v: "int | float") -> str:
        return _fp_rupees(v) if money else f"{v:,}"

    unit = "" if money else f" {_metric_label(pick)}"
    if a == b:
        line = f"{la} and {lb} are level, at {f(a)}{unit} each."
    else:
        (hl, hv), (ll, lv) = sorted([(la, a), (lb, b)], key=lambda p: p[1], reverse=True)
        diff = abs(a - b)
        diff = round(diff, 2) if isinstance(diff, float) else diff
        line = f"{hl} is higher by {f(diff)}{unit} ({hl} {f(hv)} vs {ll} {f(lv)})."
        nums = [float(t.replace(",", "")) for t in _NUM_TOKEN.findall(answer.replace("₹", ""))]
        if any(abs(n - diff) < 0.01 for n in nums) and _fp_says_higher(answer, hl):
            return answer
    total = a + b
    kept = [s for s in _fp_split_after_stop(answer.strip())
            if not (_FP_COMBINED_SENT.search(s) and any(
                abs(float(t.replace(",", "")) - total) < 0.01
                for t in _NUM_TOKEN.findall(s.replace("₹", ""))))]
    return (" ".join(kept) + " " + line).strip()


def _fp_bare_numbers(text: str) -> "list[tuple[int, int, str, str]]":
    """Each written number that stands alone — (start, end, currency, number): a figure such as
    "126197500.00" / "1,234" not touching a letter, digit, '.' or ',' before it, not followed by
    more of the same figure, nor by a unit (%, crore, cr, lakh, lac, million, mn, billion, k, K);
    a directly preceding "₹" / "₹ " / "Rs " / "Rs. " / "INR " is taken along as its currency.
    Case-sensitive, like the old _FP_BARE_NUM check it replaces."""
    out = []
    n, i, last = len(text), 0, 0
    while i < n:
        if not text[i].isdecimal() or (i > 0 and (_pmay_is_word_char(text[i - 1]) or text[i - 1] in ".,")):
            i += 1
            continue
        j, end = i + 1, i + 1
        while j < n and (text[j].isdecimal() or text[j] == ","):
            j += 1
            if text[j - 1].isdecimal():
                end = j
        if end + 1 < n and text[end] == "." and text[end + 1].isdecimal():
            end += 1
            while end < n and text[end].isdecimal():
                end += 1
        k = end
        while k < n and text[k] == ",":
            k += 1
        more = k < n and (text[k].isdecimal() or (text[k] == "." and k + 1 < n and text[k + 1].isdecimal()))
        rest = text[end:].lstrip()
        unit = rest.startswith(("%", "crore", "lakh", "lac", "million", "billion")) or any(
            rest.startswith(u) and (len(rest) == len(u) or not _pmay_is_word_char(rest[len(u)]))
            for u in ("cr", "mn", "k", "K"))
        if more or unit:
            i += 1
            continue
        start = i
        head = text[last:i]
        for body, spaced in (("₹", True), ("₹", False), ("Rs.", True), ("Rs", True), ("INR", True)):
            ok = (head[-1:].isspace() and head[:-1].endswith(body)) if spaced else head.endswith(body)
            b0 = i - len(body) - (1 if spaced else 0)
            if ok and body[0] in "RI":       # Rs / INR start a word
                ok = b0 == 0 or not _pmay_is_word_char(text[b0 - 1])
            if ok:
                start = b0
                break
        out.append((start, end, text[start:i], text[i:end]))
        last = i = end
    return out


def _fp_replace_phrase(text: str, phrase: str, rep: str) -> str:
    """Replace `phrase` where it stands as whole words (case-sensitive)."""
    out, last, k = [], 0, text.find(phrase)
    while k >= 0:
        e = k + len(phrase)
        if (k == 0 or not _pmay_is_word_char(text[k - 1])) and (e == len(text) or not _pmay_is_word_char(text[e])):
            out.append(text[last:k] + rep)
            last = e
            k = text.find(phrase, e)
        else:
            k = text.find(phrase, k + 1)
    out.append(text[last:])
    return "".join(out)


def _fp_format_numbers(answer: str, rows: list[dict]) -> str:
    """Rupee amounts from the result read '₹126,197,500.00', never
    '126197500.00'; large counts get thousands separators (KI-064). Only a
    token whose value IS a result value is touched. Also renames the
    SQL-alias 'amount raw' that a row-dump fallback exposes."""
    money: list[float] = []
    counts: list[int] = []
    for r in rows:
        for k, v in r.items():
            n = _as_number(v)
            if n is None or _NONSTAT_COL.search(k):
                continue
            if _FP_MONEY_COL.search(k):
                money.append(float(n))
            elif isinstance(n, int) and n >= 10000:
                counts.append(n)
    # the whole-result total the composer quotes from the digest ("the total
    # disbursed across all genders is 31317500") is money too
    for k in {k for r in rows for k in r if _FP_MONEY_COL.search(k)}:
        vals = [_as_number(r.get(k)) for r in rows]
        money.append(float(sum(v for v in vals if v is not None)))

    def _sub(whole: str, cur: str, tok: str) -> str:
        try:
            val = float(tok.replace(",", ""))
        except ValueError:
            return whole
        if val >= 1000 and any(abs(val - mv) < 0.005 for mv in money):
            return _fp_rupees(val)
        if not cur and "," not in tok and "." not in tok and int(val) in counts:
            return f"{int(val):,}"
        return whole

    parts, last = [], 0
    for st, en, cur, tok in _fp_bare_numbers(answer):
        parts.append(answer[last:st])
        parts.append(_sub(answer[st:en], cur, tok))
        last = en
    out = "".join(parts) + answer[last:]
    out = _fp_replace_phrase(out, "amount raw", "amount disbursed")
    # the row-dump fallback's bare "₹31,317,500.00 amount disbursed."
    out = out.strip()
    tail = " amount disbursed."
    if out.startswith("₹") and out.endswith(tail):
        fig = out[1:-len(tail)]
        whole, dot, cents = fig.rpartition(".")
        if dot and len(cents) == 2 and cents.isdecimal() and whole and all(c.isdecimal() or c == "," for c in whole):
            return f"Amount disbursed: ₹{fig}."
    return out


_FP_LABEL_NAME = {"lgd_district": "district", "block_name_raw": "block", "lgd_block": "block",
                  "lgd_village_name": "village", "tranche_label": "tranche", "batch_label": "batch",
                  "bank_name_raw": "bank", "scheme_name": "programme"}   # scheme_name: CM Elevate lists


def _fp_complete_list(answer: str, rows: list[dict]) -> str:
    """A per-category list (one label column, one figure, up to 15 rows) must
    name every category. The composer wrote "WEST GARO HILLS has 35,039 …
    The remaining districts show 11,379, 11,007, 8,612, …" — ten figures with
    no district beside them (FOCUS-002, both QA rounds). When any label is
    missing from the text, the answer is rebuilt from the rows."""
    if not 3 <= len(rows) <= 15:
        return answer
    nums = _fp_numeric_cols(rows)
    labels = [k for k in rows[0] if k not in nums]
    if len(nums) != 1 or len(labels) != 1:
        return answer
    lab, met = labels[0], nums[0]
    low = answer.lower()
    if all(r.get(lab) is None or str(r[lab]).lower() in low for r in rows):
        return answer
    name = _FP_LABEL_NAME.get(lab, lab.replace("_", " "))
    money = bool(_FP_MONEY_COL.search(met))
    items = []
    for r in rows:
        v = _as_number(r.get(met))
        if v is None:
            continue
        who = _fp_title(r[lab]) if r.get(lab) is not None else f"(no {name} recorded)"
        items.append(f"{who} {_fp_rupees(v) if money else f'{v:,}'}")
    return f"{_metric_label(met).capitalize()} by {name}: " + "; ".join(items) + "."


async def _focusplus_answer_guarantees(question: str, sql: str, rows: list[dict], answer: str) -> str:
    """Every Focus Plus DATA answer passes through here after the composer."""
    if not rows:
        return answer
    answer = _fp_complete_list(answer, rows)
    answer = _fp_breakdown_shares(answer, rows)
    answer = await _fp_single_count_share(answer, sql, rows)
    answer = _fp_comparison(question, rows, answer)
    answer = _fp_format_numbers(answer, rows)
    if any(v.strip().upper() == "NAN" for v in sql_ast.filter_values(sql or "", "block_name_raw")) \
            and "real block" not in answer:
        answer = f"{_FP_BLANK_BLOCK_LEAD} {answer}"
    return answer


# ════ compose ═════════════════════════════════════════════════════════════════════════════════════════
# ── Focus Plus: an amount stated as the size of each payment ────────────────
# Reported 2026-09-29: "What is the total disbursement amount for the Focus Plus
# scheme for a loan of five thousand across all financial years for all of
# Meghalaya" ran SELECT SUM(amount_disbursed) FROM curated.v_focus_plus — the
# stated amount silently dropped. Focus Plus pays exactly two amounts
# (data/focus_plus/README.md §6.3; schema_context Focus Plus rules): ₹5,000 is
# Tranch 1 (93K batch, FY 2022-23) and ₹2,500 is every later tranche (FY
# 2025-26). So the amount is a real filter (₹46.64 crore vs ₹119.74 crore for
# all payments), and Focus Plus is a cash benefit, not a loan. A held amount
# must reach the SQL (_focusplus_stated_amount_missing, a repair guard); one it
# never pays is asked about, never dropped.
_FOCUSPLUS_PAYMENT_AMOUNTS = {
    5000: "the Tranch 1 payments (93K batch, FY 2022-23)",
    2500: "the Tranch 2, 3 and 4 payments (FY 2025-26)",
}


def _focusplus_stated_amount(question: str, schemes: list[str]) -> "premise_check.StatedAmount | None":
    if (schemes or []) != ["Focus Plus"]:
        return None
    found = premise_check.stated_amount_filters(question)
    return found[0] if found else None


def _fp_squeeze_spaces(text: str) -> str:
    """Each run of two or more whitespace characters -> one space (a single one is kept as is)."""
    out, i, n = [], 0, len(text)
    while i < n:
        j = i
        while j < n and text[j].isspace():
            j += 1
        if j - i >= 2:
            out.append(" ")
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _fp_stated_amount_span(question: str, amount_text: str) -> "tuple[int, int] | None":
    """The span of the first `amount_text` (any case) together with the spaces and the
    "for / of / with / on / at" and "a / an / the" just before it, which the old check removed."""
    if not amount_text:
        return None
    low, key = question.lower(), amount_text.lower()

    def ws_back(p: int) -> int:
        while p > 0 and question[p - 1].isspace():
            p -= 1
        return p

    def word_before(p: int, options: tuple) -> int:
        for w in options:
            s = p - len(w)
            if s >= 0 and low[s:p] == w and (s == 0 or not _pmay_is_word_char(question[s - 1])):
                return s
        return -1

    k = low.find(key)
    while k >= 0:
        p = ws_back(k)
        first = -1
        a = word_before(p, ("the", "an", "a"))
        glued = -1
        if a < 0:          # an article written onto the preposition: "witha", "forthe"
            for art in ("the", "an", "a"):
                s0 = p - len(art)
                if s0 > 0 and low[s0:p] == art and word_before(s0, ("with", "for", "of", "on", "at")) >= 0:
                    a = glued = s0
                    break
        if a >= 0:
            first, p = a, (a if glued >= 0 else ws_back(a))
        f = word_before(p, ("with", "for", "of", "on", "at"))
        if f >= 0:
            first, p = f, ws_back(f)
        if first >= 0:
            return p, k + len(key)
        # no preposition or article: a word must end or start within the spaces before it
        w0 = ws_back(k)
        before_word = w0 > 0 and _pmay_is_word_char(question[w0 - 1])
        at_word = _pmay_is_word_char(question[k])
        if (w0 < k and (before_word or at_word)) or (w0 == k and before_word != at_word):
            return w0, k + len(key)
        k = low.find(key, k + 1)
    return None


def _focusplus_amount_clarification(question: str, amt: "premise_check.StatedAmount") -> ClarificationNeeded:
    """Focus Plus never paid the stated amount: say what it does pay, offer
    each held amount and "all payments" as full questions."""
    span = _fp_stated_amount_span(question, amt.text)

    def _swap(rep: str) -> str:
        return question if span is None else question[:span[0]] + rep + question[span[1]:]

    options = [{"label": f"₹{v:,} payments ({'Tranch 1' if v == 5000 else 'Tranches 2–4'})",
                "question": _swap(f" for payments of ₹{v:,}")}
               for v in sorted(_FOCUSPLUS_PAYMENT_AMOUNTS, reverse=True)]
    options.append({"label": "All Focus Plus payments",
                    "question": _fp_squeeze_spaces(_swap("")).strip()})
    loan = " Focus Plus is a cash benefit to farmers, not a loan." if amt.noun == "loan" else ""
    context_budget.log_decision("clarify", rule="amount-not-held", scheme="Focus Plus",
                                amount=amt.value)
    return ClarificationNeeded(
        f"Focus Plus has no {amt.noun}s of ₹{amt.value:,.0f}.{loan} Every Focus Plus payment is "
        "either ₹5,000 (Tranch 1, FY 2022-23) or ₹2,500 (Tranches 2–4, FY 2025-26). Which "
        "did you mean?", options=options, rule="amount-not-held")


def _focusplus_amount_note(amt: "premise_check.StatedAmount") -> str:
    loan = ("Focus Plus is a cash benefit, not a loan — say so in one short clause. "
            if amt.noun == "loan" else "")
    return (f"{loan}The question asks only about payments of ₹{amt.value:,.0f}; in this data those "
            f"are {_FOCUSPLUS_PAYMENT_AMOUNTS[int(amt.value)]}. Say that the figure covers the "
            f"₹{amt.value:,.0f} payments only.")


def _fp_amount_filtered(sql: str, n: int) -> bool:
    """True when the query filters amount_disbursed on `n` with = or IN (5000, '5000',
    5000.0 alike), read on the tree."""
    for node in sql_ast.filter_conditions(sql, "amount_disbursed"):
        if isinstance(node, exp.In):
            sides = list(node.expressions)
        elif isinstance(node, exp.EQ):
            sides = [node.expression if sql_ast._is_column(node.this, {"amount_disbursed"}) else node.this]
        else:
            continue
        for side in sides:
            for v in sql_ast._numeric_values(side):
                try:
                    if float(v) == n:
                        return True
                except ValueError:
                    continue
    return False


def _focusplus_stated_amount_missing(question: str, schemes: list[str], sql: str) -> "str | None":
    """The repair instruction when a Focus Plus question states a held payment
    amount and the SQL does not filter amount_disbursed on it."""
    amt = _focusplus_stated_amount(question, schemes)
    if amt is None or int(amt.value) not in _FOCUSPLUS_PAYMENT_AMOUNTS or not sql:
        return None
    n = int(amt.value)
    if _fp_amount_filtered(sql, n):
        return None
    return (f"the question restricts the answer to payments of ₹{n:,} (\"{amt.text}\"), but this "
            "query does not filter on the payment amount, so it counts every Focus Plus payment. "
            f"Add amount_disbursed = {n} to the WHERE clause (Focus Plus pays only 5000 or 2500 "
            "per row) and keep every other filter, the aggregation and the grouping exactly as "
            "they were.")


# RAG fix report 2026-10-29, Issue 12: "Average FOCUS+ amount per beneficiary" answered
# ₹11,316 while the scheme rules say ₹5,000 per household, with nothing to say why. The
# data is right: Focus Plus pays in tranches (a ₹5,000 first tranche, then ₹2,500 ones), and
# most beneficiaries have four payments, so the amount per beneficiary is the sum of their
# tranches. Said in one line after any per-beneficiary average; no figure is typed here.
_FP_PER_BENEFICIARY_NOTE = ("Note: Focus Plus pays in tranches (a ₹5,000 first payment, then ₹2,500 payments), "
                            "and most beneficiaries received several, so the amount per beneficiary is the total "
                            "of all their tranches — higher than a single payment.")


def _fp_amount_per_beneficiary_sql(sql: "str | None") -> bool:
    """The query divides a SUM of amount_disbursed by a count of beneficiaries."""
    for tree in sql_ast.parse(sql or ""):
        for div in tree.find_all(exp.Div):
            num = {c.name.lower() for c in div.this.find_all(exp.Column)}
            den = div.expression
            if "amount_disbursed" in num and any(
                    "beneficiary_key" in {c.name.lower() for c in cnt.find_all(exp.Column)}
                    for cnt in den.find_all(exp.Count)):
                return True
    return False


def _focusplus_per_beneficiary_caveat(answer: str, sql: "str | None") -> str:
    if not answer or "tranches" in answer or not _fp_amount_per_beneficiary_sql(sql):
        return answer
    return f"{answer.rstrip()}\n\n{_FP_PER_BENEFICIARY_NOTE}"

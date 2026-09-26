"""
backend/prompt_builder.py — the single place the SQL-generation prompt is built.

Everything the generator sees about the database is composed here, in one order,
from four sources with a clear precedence:

  1. schema_context.build_schema_context(schemes)   — HAND-WRITTEN BACKBONE
        The curated/semantic object list per scheme, the money-unit facts, and
        the "wrong number if broken" hazard rules. Those rules are judgement, not
        structure — they can never be introspected, so they stay hand-maintained
        (see docs/DATA_MODEL.md).
  2. LIVE SCHEMA block                               — schema_introspect.live_columns()
        The columns that actually exist in megh_db right now, pulled from
        information_schema at startup, scheme-scoped. This is what catches
        schema_context.py drifting out of sync with the database. Silently
        omitted when the startup read didn't land (offline dev, catalog perms).
  3. LIVE CATALOG block                              — schema_introspect.catalog_block()
        SME-curated semantic.* descriptions, synonyms and metric formulas.
  4. PROHIBITED JOINS / VERIFIED EXAMPLES / RESOLVED ENTITIES
        annotations.py + entity_resolver output. Resolved entities go LAST, right
        before the question — a wrong-case district literal silently matches zero
        rows, so it is the single most load-bearing part of the prompt.

Public:
  build_sql_prompt(question, schemes, entity_result)      -> async str  (first attempt;
                                                                          §5.10 awaits
                                                                          sql_examples_retrieval)
  build_repair_prompt(question, schemes, entity_result,
                      failed_sql, error)                    -> str  (retry, sync)

The repair prompt now carries the SAME schema + resolved-entities context as the
first attempt (plus the failure), instead of the thin schema-only prompt used
before — a repair most often needs exactly the entity block it was missing.
"""
from app.knowledge import scheme_registry
from app.sql import schema_introspect, sql_examples_retrieval
from app.knowledge.annotations import few_shot_examples, prohibited_joins_text
from app.sql.schema_context import build_schema_context
from app.nlu import understand

# Bare table name -> owning scheme, so the LIVE SCHEMA block is scoped the same
# way schema_context.py scopes its hand-written one.
_SHARED_PREFIXES = ("dim_scheme", "dim_year", "dim_geography")
_CROSS_PREFIXES = ("v_cross_scheme",)


def _scheme_of(table: str) -> str:
    """'MGNREGA' | 'PMAY-G' | 'Focus Plus' | 'CM Elevate' | 'shared' | 'cross' for
    a bare (unqualified) table name.

    openspec/changes/multi-tenant-rls-scheme-scaleout tasks.md 4.2: this used
    to be a hand-authored substring/exact-match dict per scheme (the same
    per-scheme-code-per-onboarding character as app/sql/schema_context.py's 912
    lines) — flagged as out of scope, then actually fixed 2026-09-15: every
    scheme already declares its owned tables in scheme_registry.yaml's
    `tables:` list (schema-qualified) for schema-retrieval/join-discovery
    purposes, so that's the real source of truth for "which scheme owns this
    table" too. A newly onboarded scheme now needs zero code here — only its
    registry entry, which it needs anyway."""
    t = table.lower()
    if t.startswith(_SHARED_PREFIXES):
        return "shared"
    if t.startswith(_CROSS_PREFIXES):
        return "cross"
    for scheme_id in scheme_registry.scheme_ids():
        for qualified in scheme_registry.tables_for(scheme_id):
            _, _, bare = qualified.partition(".")
            if bare.lower() == t:
                return scheme_id
    return "shared"  # unknown object -> show it rather than hide it


def _live_schema_block(schemes: list[str]) -> str:
    """Real columns per table, scoped to the classified scheme(s). Empty string
    when live introspection is unavailable — the caller then relies on the
    hand-written backbone alone, exactly as before this layer existed."""
    live = schema_introspect.live_columns()
    if not live:
        return ""

    want = set(schemes)
    multi = len(schemes) > 1
    lines = [
        "LIVE SCHEMA — columns that exist in megh_db right now (information_schema, "
        "read at startup). If a column is not listed here it does not exist; do not use it.",
    ]
    for qualified, cols in sorted(live.items()):
        _, _, bare = qualified.partition(".")
        owner = _scheme_of(bare)
        if owner == "cross" and not multi:
            continue
        # openspec/changes/multi-tenant-rls-scheme-scaleout: reads the live
        # registry instead of a hardcoded 4-scheme tuple, so a newly
        # onboarded scheme correctly counts as "a real scheme, filter it
        # out when not wanted" rather than falling through to the "shared,
        # always show" default below. _scheme_of() itself (above) is now
        # also registry-driven — see that function's own docstring.
        if owner in scheme_registry.scheme_ids() and owner not in want:
            continue
        lines.append(f"  {qualified}({', '.join(c['column'] for c in cols)})")

    fks = schema_introspect.live_fks()
    scoped_fks = [
        fk for fk in fks
        if _scheme_of(fk["from"].partition(".")[2]) in ({"shared"} | want | ({"cross"} if multi else set()))
    ]
    if scoped_fks:
        lines.append("")
        lines.append("REAL FOREIGN KEYS (valid join paths — PROHIBITED JOINS below still overrides):")
        lines += [f"  {fk['from']}.{fk['from_column']} -> {fk['to']}.{fk['to_column']}"
                  for fk in scoped_fks]
    return "\n".join(lines) + "\n"


async def _fewshot_block(schemes: list[str], question: str = "") -> str:
    """§5.10 — tries semantic retrieval over megh_sql_examples first
    (app.sql.sql_examples_retrieval, scheme-prefiltered pgvector); an empty
    result (table not yet seeded for these schemes, or an embedding
    failure — retrieve() never raises) falls back unchanged to the
    original token-overlap ranking over the static YAML pool."""
    vector_examples = await sql_examples_retrieval.retrieve(question, schemes)
    if vector_examples:
        examples = [
            {"question": ex["question"],
             "sql": ex["sql"] if ex["is_answerable"] else None,
             "reason": ex["reason"]}
            for ex in vector_examples
        ]
    else:
        examples = few_shot_examples(schemes, question, top_k=5)
    if not examples:
        return ""
    parts = []
    for ex in examples:
        if ex["sql"] is None:
            parts.append(
                f'Q: "{ex["question"]}"\n'
                f'NOT ANSWERABLE from this data — {ex["reason"]} Do not substitute a '
                'different metric (like a row count) to make it look answerable; state '
                'plainly that the figure is not held in this warehouse.'
            )
        else:
            parts.append(f'Q: "{ex["question"]}"\nSQL: {ex["sql"]}')
    return "\nEXAMPLES (verified SQL, and known-unanswerable questions):\n" + "\n\n".join(parts) + "\n"


def _entities_block(entity_result: dict) -> str:
    resolved = entity_result.get("resolved", {})
    notes = entity_result.get("notes", [])
    lines: list[str] = []
    if resolved:
        lines.append(
            "RESOLVED ENTITIES — MANDATORY: the WHERE clause MUST use these exact "
            "values, not any name or spelling from the question text. These are already "
            "resolved against the database (correct case, correct code, correct year_key):"
        )
        for k, v in resolved.items():
            if k == "district_list_region":
                continue  # rendered alongside district_list
            if k == "village_code":
                lines.append(f"  village_code = {v!r}   -- do NOT filter on lgd_village_name instead")
            elif k == "district":
                lines.append(f"  lgd_district = {v!r}   -- already uppercase, matches storage exactly")
            elif k == "district_list":
                vals = v if isinstance(v, list) else [v]
                quoted = ", ".join(f"'{s}'" for s in vals)
                region = resolved.get("district_list_region")
                if region:
                    lines.append(
                        f"  lgd_district IN ({quoted})   -- the {len(vals)} districts that make up "
                        f"\"{region}\" (a hill range, not a single district). Filter on ALL of them "
                        f"with IN, and state in the answer which districts \"{region}\" covers.")
                else:
                    lines.append(
                        f"  lgd_district IN ({quoted})   -- the {len(vals)} districts explicitly "
                        "named for comparison. Filter on ALL of them with IN and GROUP BY district "
                        "so each gets its own row in the result — do NOT sum them into one figure.")
            elif k == "block":
                lines.append(f"  lgd_block = {v!r}   -- already uppercase, matches storage exactly")
            elif k == "block_list":
                vals = v if isinstance(v, list) else [v]
                quoted = ", ".join(f"'{s}'" for s in vals)
                lines.append(
                    f"  lgd_block IN ({quoted})   -- the {len(vals)} blocks explicitly named "
                    "for comparison. Filter on ALL of them with IN and GROUP BY block so each "
                    "gets its own row in the result — do NOT sum them into one figure.")
            elif k == "assembly_constituency":
                lines.append(
                    f"  UPPER(assembly_constituency_name) = UPPER({v!r})   -- this column "
                    "exists ONLY in MGNREGA employment. Query curated.v_employment for it "
                    "(it also has lgd_district / lgd_block / village columns for any "
                    "other filter here); the raw fact_mgnrega_employment table has no "
                    "lgd_* columns. If the question also needs "
                    "expenditure, say that level isn't available there instead of silently "
                    "switching to a block/district filter.")
            elif k == "year_key":
                lines.append(f"  year_key = {v!r}")
            elif k == "house_status":
                vals = v if isinstance(v, list) else [v]
                quoted = ", ".join(f"'{s}'" for s in vals)
                if len(vals) == 1:
                    lines.append(f"  status_name = {quoted}   -- exact stored PMAY-G stage "
                                 "label; use it verbatim, do not paraphrase or re-case")
                else:
                    lines.append(f"  status_name IN ({quoted})   -- exact stored PMAY-G stage "
                                 "labels; match with IN / OR, never AND")
                if set(vals) & {"Proposed Site", "Existing site(Old House)"}:
                    lines.append(
                        "      NOTE: in curated.v_pmay EVERY 'Proposed Site' and 'Existing "
                        "site(Old House)' row has is_placeholder = TRUE (they are the "
                        "sanctioned_amount = 0 / year_key NULL bucket). For this status "
                        "count do NOT add 'AND NOT is_placeholder' — that guard would drop "
                        "the entire category and return a false 0. Count status_name over "
                        "all rows.")
            elif k == "cm_scheme":
                vals = v if isinstance(v, list) else [v]
                quoted = ", ".join(f"'{s}'" for s in vals)
                if len(vals) == 1:
                    lines.append(f"  scheme_name = {quoted}   -- exact stored CM Elevate "
                                 "sub-scheme name (mixed case, stored exactly); use it "
                                 "verbatim, do NOT substitute the question's own spelling "
                                 "or wording for it")
                else:
                    lines.append(
                        f"  scheme_name IN ({quoted})   -- the {len(vals)} sub-schemes "
                        "explicitly named for comparison. Filter on ALL of them with IN and "
                        "GROUP BY scheme_name so each gets its own row in the result — do "
                        "NOT sum them into one figure.")
            elif k == "batch_label":
                lines.append(
                    f"  batch_label = {v!r}   -- the Focus Plus cohort the question names "
                    "('12.5K' = newer registration batch, '93K' = legacy paid batch); "
                    "stored value, use it verbatim")
            elif k == "pg_name_pattern":
                lines.append(
                    f"  pg_name ILIKE {v!r}   -- the producer group named in the question "
                    "(curated.v_focus_legacy). Use this ILIKE pattern verbatim — PG names "
                    "are not unique, so return pg_id, pg_name, lgd_district, lgd_block and "
                    "financial_year_short alongside the figures, one row per pg_id per "
                    "year. If it returns no rows, say no producer group by that name was "
                    "found.")
            elif k == "tranche_label":
                vals = v if isinstance(v, list) else [v]
                quoted = ", ".join(f"'{s}'" for s in vals)
                if len(vals) == 1:
                    lines.append(f"  tranche_label = {quoted}   -- exact stored Focus Plus "
                                 "label (spelled \"Tranch\", not \"Tranche\", plus a month "
                                 "suffix); use it verbatim, do NOT substitute the question's "
                                 "own spelling")
                else:
                    lines.append(
                        f"  tranche_label IN ({quoted})   -- the {len(vals)} tranches "
                        "explicitly named for comparison. Filter on ALL of them with IN and "
                        "GROUP BY tranche_label so each gets its own row in the result — do "
                        "NOT sum them into one figure.")
            else:
                lines.append(f"  {k} = {v!r}")
    if notes:
        lines.append("NOT FOUND (do not filter on these — state plainly they're not in the data):")
        lines += [f"  {n}" for n in notes]
    return "\n" + "\n".join(lines) + "\n" if lines else ""


def _prohibited_block(schemes: list[str]) -> str:
    prohibited = prohibited_joins_text(schemes)
    return f"\nPROHIBITED JOINS:\n{prohibited}\n" if prohibited else ""


def _retrieved_schema_block(retrieved: list[dict] | None) -> str:
    """Formats app/sql/schema_retrieval.py's output, when non-empty, as a
    supplementary block — additive only (see design.md's "additive, not
    gating" decision). A scheme with no indexed schema-metadata rows passes
    `retrieved=[]` (or omits the argument), so this returns "" and the
    prompt is byte-for-byte the same as before this capability existed."""
    if not retrieved:
        return ""
    lines = ["\nRETRIEVED SCHEMA NOTES — semantically matched to this question "
             "(supplements, does not replace, the schema above):"]
    for r in retrieved:
        lines.append(f"  [{r['granularity']}] {r['ref']}: {r['content']}")
    return "\n".join(lines) + "\n"


def _required_join_block(joins) -> str:
    """Formats app/sql/join_graph.py's output, when non-empty, as an additive
    hint — the same enforcement tier as PROHIBITED JOINS below (a prompt
    instruction, not a runtime parse of the returned SQL; see design.md).
    `joins` is a list of join_graph.JoinEdge or None."""
    if not joins:
        return ""
    lines = ["\nREQUIRED JOIN(S) — computed from declared foreign keys / curated "
             "join edges, use these exact ON clauses if you join these tables:"]
    for j in joins:
        lines.append(f"  {j.left} JOIN {j.right} ON {j.on_clause}")
    return "\n".join(lines) + "\n"


# ── REQUIRED FILTERS ──────────────────────────────────────────────────────
# The understood question as explicit constraints: what the SQL must filter on,
# group by and limit to — from the QueryFrame, the resolved entity values and
# the defaults the gates applied (entity_result["gate_trace"]). The model gets
# the frame's clean standalone question instead of whatever the user typed.
_GROUP_COLUMN = {"district": "lgd_district", "block": "lgd_block", "village": "village_code / lgd_village_name",
                 "year": "the financial year column (year_key or financial_year_short)",
                 "tranche": "tranche_label", "scheme": "scheme_name (CM Elevate sub-scheme)"}


def _prompt_frame(frame=None):
    if frame is not None:
        return frame
    return understand.sql_frame()


def effective_top_n(frame, entity_result: dict) -> "int | None":
    if frame is not None and frame.top_n:
        return int(frame.top_n)
    for t in (entity_result or {}).get("gate_trace") or []:
        if t.startswith("top_n:default:"):
            try:
                return int(t.rsplit(":", 1)[1])
            except ValueError:
                return None
    return None


def _required_filters_block(frame, schemes: list[str], entity_result: dict) -> str:
    if frame is None:
        return ""
    resolved = (entity_result or {}).get("resolved") or {}
    trace = (entity_result or {}).get("gate_trace") or []
    lines = ["", "REQUIRED FILTERS — from the understood question. Scheme, geography, year, tranche,",
             "group_by and top_n are REQUIRED; 'understood as' / metric / query_type are guidance —",
             "if they conflict with the question as asked, the question as asked wins:"]
    if frame.rewritten_question:
        lines.append(f"  understood as: {frame.rewritten_question}")
    lines.append(f"  scheme: {', '.join(schemes)} — use only this scheme's tables")
    if frame.metric:
        lines.append(f"  metric (guidance): {frame.metric}")
    geo = []
    if resolved.get("village_code") is not None:
        geo.append(f"village_code = {resolved['village_code']}")
    if resolved.get("block"):
        geo.append(f"lgd_block = '{resolved['block']}'")
    if resolved.get("district"):
        geo.append(f"lgd_district = '{resolved['district']}'")
    if resolved.get("district_list"):
        geo.append("lgd_district IN (" + ", ".join(f"'{d}'" for d in resolved["district_list"]) + ")")
    lines.append("  geography: " + (" AND ".join(geo) if geo else "statewide — NO geography filter"))
    if resolved.get("year_key") is not None:
        y = int(resolved["year_key"])
        lines.append(f"  year: FY {y}-{(y + 1) % 100:02d} (year_key = {y})")
    elif any(t.startswith(("year:default:all", "year:all-stated", "year:default:all_available"))
             for t in trace) or (frame.year_text and "all" in frame.year_text.casefold()):
        lines.append("  year: all financial years — NO year filter")
    elif frame.year_text:
        lines.append(f"  year: {frame.year_text} (as stated — a period, filter accordingly)")
    if resolved.get("tranche_label"):
        lines.append(f"  tranche: tranche_label = '{resolved['tranche_label']}'")
    elif any(t == "tranche:default:all" for t in trace):
        lines.append("  tranche: all tranches — NO tranche filter")
    if frame.group_by:
        col = _GROUP_COLUMN.get(frame.group_by.casefold())
        lines.append(f"  group_by: {frame.group_by}" + (f" — GROUP BY {col}" if col else ""))
    n = effective_top_n(frame, entity_result)
    if n:
        lines.append(f"  top_n: {n} — ORDER BY the metric DESC and LIMIT {n}")
    if frame.query_type:
        lines.append(f"  query_type (guidance): {frame.query_type}")
    return "\n".join(lines) + "\n"


async def build_sql_prompt(question: str, schemes: list[str], entity_result: dict,
                           retrieved: list[dict] | None = None, joins=None, frame=None) -> str:
    # The question AS ASKED stays the question (for a resumed pause or a
    # follow-up it is already the frame's standalone rebuild); the frame's
    # paraphrase rides in REQUIRED FILTERS as "understood as". Replacing the
    # question outright lost meaning when the paraphrase drifted ("best and
    # worst on completion" -> "top 5 by houses completed"; eval step 7).
    frame = _prompt_frame(frame)
    catalog = schema_introspect.catalog_block(schemes)
    fewshot = await _fewshot_block(schemes, question)
    return "".join([
        build_schema_context(schemes), "\n\n",
        _live_schema_block(schemes),
        (catalog + "\n") if catalog else "",
        _prohibited_block(schemes),
        _retrieved_schema_block(retrieved),
        _required_join_block(joins),
        fewshot,
        _entities_block(entity_result),
        _required_filters_block(frame, schemes, entity_result),
        f"\nThe user's question is about: {', '.join(schemes)}.\n",
        f'\nQuestion: "{question}"\nSQL:',
    ])


def build_repair_prompt(question: str, schemes: list[str], entity_result: dict,
                        *, failed_sql: str, error: str, extra_hint: str | None = None) -> str:
    frame = _prompt_frame()
    return "".join([
        build_schema_context(schemes), "\n\n",
        _live_schema_block(schemes),
        _prohibited_block(schemes),
        _entities_block(entity_result),
        _required_filters_block(frame, schemes, entity_result),
        "\nThe previous query FAILED and must be corrected.\n",
        f"Error: {error}\n",
        (f"Hint: {extra_hint}\n" if extra_hint else ""),
        f"Previous query:\n{failed_sql}\n",
        f'\nQuestion: "{question}"\n',
        "Return the corrected single read-only SELECT. SQL:",
    ])


_VERIFY_CALIBRATION = """
CALIBRATION — how strict to be:
Q: "How many payments were made in Tranch 2?"
RESOLVED ENTITIES: tranche_label = 'Tranch 2 - August'
SQL: SELECT COUNT(*) AS payments FROM curated.v_focus_plus WHERE tranche_label = 'Tranch 2 - August';
{"ok": true}
  (The resolved value IS the whole tranche — "Tranch 2 - August" is a closed-set
  label, not a month filter layered on top of "Tranch 2". Using it verbatim is
  correct, not a narrowing of scope.)

Q: "How many MGNREGA person days in East Garo Hills?"
RESOLVED ENTITIES: lgd_district = 'EAST GARO HILLS'
SQL: SELECT SUM(person_days) AS person_days FROM curated.v_employment WHERE lgd_district = 'EAST GARO HILLS';
{"ok": true}
  (District-level question, district-level filter, on the resolved column. No
  finer grain was asked for or required.)

Q: "Compare person days between East Garo Hills and West Garo Hills"
RESOLVED ENTITIES: lgd_district IN ('EAST GARO HILLS', 'WEST GARO HILLS')
SQL: SELECT SUM(person_days) AS person_days FROM curated.v_employment WHERE lgd_district = 'EAST GARO HILLS';
{"ok": false, "issue": "Comparison names two districts but the SQL filters on only one (WEST GARO HILLS is dropped), so the result has no second value to compare against."}
  (This IS a real violation — a resolved value is silently missing from the SQL.)

Q: "How much has been disbursed in Dalu block for Focus Plus?"
RESOLVED ENTITIES: lgd_block = 'DALU'
SQL: SELECT SUM(amount_disbursed) AS amount_raw FROM curated.v_focus_plus WHERE lgd_block = 'DALU' LIMIT 1;
{"ok": true}
  (SUM(...) IS the aggregation — a SUM/COUNT/AVG with no GROUP BY always returns
  exactly one row, so the trailing LIMIT 1 is a harmless no-op, not evidence the
  query is missing an aggregate. Read whether SUM/COUNT/AVG wraps the metric
  column, never the presence of "LIMIT 1" by itself, to answer check 3.)
""".strip()


def build_verify_prompt(question: str, schemes: list[str], entity_result: dict, sql: str) -> str:
    """Second-opinion check on already-generated SQL (app.clients.llm.call_sql_verifier),
    run before the query touches the database.

    Deliberately narrower than the SQL-generation prompt: earlier versions
    reused the full hand-written rules backbone (build_schema_context) and
    told the small verifier model to check the SQL against "every rule" —
    in testing that made it hallucinate violations on already-correct,
    already-verified SQL (including the project's own few-shot examples) at
    a high rate, because most of those rules describe how the ANSWER TEXT
    should be worded (label multiple readings, state a figure as
    provisional, read money_unit before formatting) rather than what the
    SQL must contain, and a small model given a long prose rule list tends
    to find "a" violation rather than confirm there is none. This version
    hands it only the mechanical, checkable facts — real tables/columns,
    prohibited joins, resolved entities — plus a closed checklist and two
    worked "ok: true" examples so it has a calibration anchor for what a
    passing query looks like, not just failing ones. Still does NOT include
    the SQL-generation few-shot: those are for writing SQL, not judging it."""
    return "".join([
        _live_schema_block(schemes),
        _prohibited_block(schemes),
        _entities_block(entity_result),
        "\n", _VERIFY_CALIBRATION, "\n",
        "\nCheck the SQL below against ONLY these four things:\n"
        "  1. Every PROHIBITED JOIN above — is one of them actually used?\n"
        "  2. Every RESOLVED ENTITY above — is its exact value present in the "
        "WHERE clause (not dropped, not substituted with different text from "
        "the question)? Judge this ONLY against the RESOLVED ENTITIES block "
        "above — an empty or absent block means there is nothing to check here, "
        "so answer this check true regardless of the question's own wording. "
        "A phrase in the QUESTION itself like 'all years', 'all tranches', "
        "'all financial years', 'combined', 'overall' or 'cumulative' is NEVER "
        "a resolved entity requiring a WHERE-clause value — it is an "
        "instruction to filter on NOTHING for that dimension, so a WHERE "
        "clause that omits it entirely is correct, not a violation. Do not "
        "invent a resolved entity from question text that isn't in the "
        "RESOLVED ENTITIES block.\n"
        "  3. Table/grain — does it read a raw per-row table when the question "
        "asks for a total (missing SUM/COUNT), or vice versa? Judge this ONLY by "
        "whether SUM/COUNT/AVG wraps the metric column — a trailing LIMIT clause "
        "proves nothing either way (a SUM/COUNT/AVG with no GROUP BY always "
        "returns one row, so LIMIT 1 after one is normal, not a sign the "
        "aggregate is missing).\n"
        "  4. Metric column — does it aggregate a column that has nothing to "
        "do with what the question asks for?\n"
        "Nothing else is in scope. Do not judge phrasing, labelling, rounding, "
        "unit formatting, or whether the answer text will explain a caveat — "
        "those happen after this query runs, in a separate step, and are not "
        "the SQL's job. If you cannot point to a SPECIFIC one of the four "
        "checks above that this exact SQL fails, answer ok: true.\n",
        f'\nQuestion: "{question}"\n',
        f"\nGenerated SQL:\n{sql}\n",
        '\nRespond with ONLY a JSON object: {"ok": true} if none of the four '
        'checks are violated, or {"ok": false, "issue": "<which of the four '
        'checks it fails, and how>"} if one is.\nJSON:',
    ])

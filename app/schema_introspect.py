"""
Live schema catalog — reads the SME-curated `semantic.*` tables in megh_db
(table_catalog, column_catalog incl. unit and the exact VALUES lists,
glossary, join_graph, metric_definitions, v_join_rules) and
curated.v_data_coverage once at startup, and folds a compact view of them into
the SQL-generation prompt, alongside the hand-written rules in schema_context.py.

The chatbot does NOT embed semantic.v_embedding_documents or load
semantic.v_prompt_bundles: those are rendered from these same tables, which it
reads directly, so an ingestion-side catalog change reaches the prompt at the
next restart with no re-embed.

schema_context.py stays the source of truth for the *hazards* (which joins are
invalid, which columns are stocks) — the catalog can't encode those. This module
adds the *descriptions, synonyms and metric formulas* the SMEs maintain in the
database, so the generator sees the same vocabulary an analyst would.
"""
import logging

from app import db, sql_guard
from app.config import settings

logger = logging.getLogger(__name__)

# subject_area token in semantic.* -> our scheme label
_SUBJECT_TO_SCHEME = {"mgnrega": "MGNREGA", "pmay": "PMAY-G", "pmayg": "PMAY-G",
                      "pmay-g": "PMAY-G", "housing": "PMAY-G", "employment": "MGNREGA",
                      "focus_plus": "Focus Plus", "focusplus": "Focus Plus",
                      "focus plus": "Focus Plus", "focus+": "Focus Plus",
                      "cm_elevate": "CM Elevate", "cmelevate": "CM Elevate",
                      "cm elevate": "CM Elevate", "cm-elevate": "CM Elevate",
                      "focus_legacy": "Focus Legacy", "focuslegacy": "Focus Legacy",
                      "focus legacy": "Focus Legacy", "focus-legacy": "Focus Legacy",
                      "cm_elevate_legacy": "CM Elevate Legacy",
                      "cmelevatelegacy": "CM Elevate Legacy",
                      "cm elevate legacy": "CM Elevate Legacy",
                      "cm_elevate_disbursement": "CM Elevate Legacy",
                      "cm elevate disbursement": "CM Elevate Legacy",
                      # Not one of our schemes: mapped so its rows are scoped
                      # OUT (an unmapped subject_area applies to every scheme).
                      # CMSS / Home Stay: their glossary terms ("combining CMSS
                      # with Focus+", the DB team's 2026-10-27 relationship
                      # rules) reached all six SQL prompts, pointing the
                      # generator at v_cmss / v_homestay_legacy (KI-428).
                      "nrlm": "NRLM", "cmss": "CMSS",
                      "homestay": "Home Stay", "homestay_legacy": "Home Stay",
                      "home stay": "Home Stay", "home_stay": "Home Stay"}

# curated.v_data_coverage.scheme -> our scheme label (NRLM is not served here).
_COVERAGE_TO_SCHEME = {"MGNREGA": "MGNREGA", "PMAY": "PMAY-G", "FOCUS_PLUS": "Focus Plus",
                       "CM_ELEVATE": "CM Elevate", "FOCUS_LEGACY": "Focus Legacy",
                       "CM_ELEVATE_DISBURSEMENT": "CM Elevate Legacy"}

# Never shown to the SQL generator and refused by sql_guard: they carry unmasked
# account numbers / holder names / applicant names (KI-004). The views mask them.
PRIVATE_TABLES = sql_guard.PRIVATE_TABLES

# The login generated SQL runs as. Columns it cannot SELECT (column-level
# revokes, e.g. v_cm_elevate.scheme_specific since 2026-10-16) are left out of
# the LIVE SCHEMA block, so the generator never writes a query that the
# database will refuse — even while a dev box still runs as postgres.
_READONLY_ROLE = "megh_readonly"

_cache: dict = {
    "loaded": False, "tables": [], "glossary": [], "metrics": [], "joins": [],
    "columns": [],
    # semantic.v_join_rules: {object_ref: set(objects it must never be row-joined with)},
    # made symmetric. curated.v_data_coverage: {scheme label: [years present]}.
    "join_rules": {}, "coverage": {},
    # (schema, table, column) the read-only role cannot SELECT.
    "denied": set(),
    # Live information_schema extract (structure, not SME prose). Populated by
    # _load_live_schema(); empty => the prompt falls back to the hand-written
    # schema_context.py backbone alone.
    "live_loaded": False, "live_columns": {}, "live_fks": [],
}

# semantic.column_catalog has no subject_area column of its own (unlike
# table_catalog/glossary) — its rows are keyed by table_name, so scheme
# membership is inferred from a substring match instead. Shared dimension
# tables (dim_geography, dim_year, dim_scheme, ...) match nothing here and
# fall through to "applies to every scheme", same as a NULL subject_area
# elsewhere in this module.
_TABLE_NAME_TO_SCHEME = {
    "employment": "MGNREGA", "expenditure": "MGNREGA", "mgnrega": "MGNREGA",
    "pmay": "PMAY-G",
    "focus_plus": "Focus Plus",
    # Before "cm_elevate": _table_matches_scheme returns on the FIRST substring
    # hit, and every CM Elevate Legacy table name also contains "cm_elevate".
    "cm_elevate_disb": "CM Elevate Legacy",
    "cm_elevate": "CM Elevate",
    "focus_legacy": "Focus Legacy",
    "producer_group": "Focus Legacy",
    "pg_entity_type": "Focus Legacy",
    "pg_bank_history": "Focus Legacy",
    # Not our schemes: scoped OUT, like their glossary terms (KI-428). Without
    # these, ~40 v_cmss / v_homestay_legacy column notes (ingestion 2026-10-26)
    # went into every scheme's SQL prompt and spent its description budget.
    "cmss": "CMSS", "homestay": "Home Stay", "nrlm": "NRLM",
}


def _table_matches_scheme(table_name: str, schemes: list[str]) -> bool:
    name = (table_name or "").lower()
    for key, scheme in _TABLE_NAME_TO_SCHEME.items():
        if key in name:
            return scheme in schemes
    return True


def _is_scheme_specific_table(table_name: str) -> bool:
    name = (table_name or "").lower()
    return any(key in name for key in _TABLE_NAME_TO_SCHEME)

# The only schemas the read-only app role can see, and the only ones worth
# putting in front of the SQL generator.
_QUERYABLE_SCHEMAS = ("curated", "semantic")


async def load() -> None:
    if not settings.SCHEMA_CATALOG_ENABLED:
        return
    await _load_semantic_catalog()
    await _load_live_schema()


async def _load_semantic_catalog() -> None:
    try:
        _cache["tables"] = await db.fetch_rows_readonly(
            """SELECT table_schema, table_name, entity_role, grain, description,
                      subject_area, synonyms, row_count
               FROM semantic.table_catalog
               WHERE is_chatbot_visible IS NOT FALSE
               ORDER BY table_schema, table_name""")
        _cache["glossary"] = await db.fetch_rows_readonly(
            """SELECT term, definition, subject_area, synonyms, maps_to_object, maps_to_column
               FROM semantic.glossary ORDER BY term""")
        try:
            _cache["metrics"] = await db.fetch_rows_readonly("SELECT * FROM semantic.metric_definitions")
        except Exception:  # noqa: BLE001 — table shape varies; optional
            _cache["metrics"] = []
        try:
            _cache["joins"] = await db.fetch_rows_readonly("SELECT * FROM semantic.join_graph")
        except Exception:  # noqa: BLE001
            _cache["joins"] = []
        try:
            # Client UAT sheet (2026-09-13): this table is where SMEs record the
            # traps that actually break generated SQL — new/renamed identity
            # columns (beneficiary_key), verbatim source spellings that don't
            # match the "correct" English word (tranche_label stored as
            # "Tranch"), and storage-format gotchas (lgd_district/lgd_block
            # stored UPPERCASE-only). Until now nothing in the prompt pipeline
            # ever read it — every one of those traps had to be discovered live
            # and hand-copied into schema_context.py/the few-shot yaml, which is
            # exactly the kind of manual sync that drifts. Loading it here means
            # a new data_quality_note SMEs add shows up in the prompt the next
            # time the process restarts, without a matching code change.
            # unit and sample_values since 2026-10-16 (ingestion team, CHATBOT_DB_CHANGES):
            # every measure column carries its UNIT (MGNREGA lakh rupees, the other
            # schemes rupees, *_crore / *_cr crore) and 89 coded columns carry their
            # complete list of stored values — the two things the generator used to
            # guess (lakh vs rupees; a 'Pending' literal no row holds).
            _cache["columns"] = await db.fetch_rows_readonly(
                """SELECT table_schema, table_name, column_name, description,
                          data_quality_note, unit, sample_values
                   FROM semantic.column_catalog
                   WHERE is_chatbot_visible IS NOT FALSE
                     AND (data_quality_note IS NOT NULL OR description IS NOT NULL
                          OR unit IS NOT NULL OR sample_values IS NOT NULL)
                   ORDER BY table_schema, table_name, column_name""")
        except Exception:  # noqa: BLE001 — table shape varies; optional
            _cache["columns"] = []
        await _load_join_rules()
        await _load_coverage()
        _cache["loaded"] = True
        logger.info("schema_introspect: catalog loaded — %d tables, %d glossary terms, "
                    "%d metrics, %d column notes, %d join rules, %d coverage schemes",
                    len(_cache["tables"]), len(_cache["glossary"]), len(_cache["metrics"]),
                    len(_cache["columns"]), len(_cache["join_rules"]), len(_cache["coverage"]))
    except Exception as e:  # noqa: BLE001 — never block startup on the catalog
        logger.warning("schema_introspect: catalog load failed (SQL prompt uses static "
                       "context only): %s", e)


async def _load_join_rules() -> None:
    """semantic.v_join_rules: for each fact or row-level view, the objects it
    must never be ROW-joined with (a join of v_employment to v_expenditure on
    year + district turned FY2024-25 person-days from 14.7 million into 6.69
    billion). Stored symmetric; read by the fan-out guard in execute_with_repair."""
    try:
        rows = await db.fetch_rows_readonly(
            "SELECT object_ref, never_row_join_with FROM semantic.v_join_rules")
    except Exception as e:  # noqa: BLE001 — optional; the guard then has nothing to check
        logger.warning("schema_introspect: semantic.v_join_rules not read: %s", e)
        _cache["join_rules"] = {}
        return
    rules: dict[str, set[str]] = {}
    for r in rows:
        a = str(r["object_ref"] or "").lower()
        for b in r["never_row_join_with"] or []:
            b = str(b).lower()
            if a and b and a != b:
                rules.setdefault(a, set()).add(b)
                rules.setdefault(b, set()).add(a)
    _cache["join_rules"] = rules


async def _load_coverage() -> None:
    """curated.v_data_coverage: the financial years each dataset holds, computed
    live. A year missing there means NO DATA, never 0 (Focus Plus has 2022-23 and
    2025-26 only; Focus Legacy has no 2023-24; CM Elevate has no year at all)."""
    try:
        rows = await db.fetch_rows_readonly("SELECT scheme, years_present FROM curated.v_data_coverage")
    except Exception as e:  # noqa: BLE001 — optional; the hand-kept year table stays
        logger.warning("schema_introspect: curated.v_data_coverage not read: %s", e)
        _cache["coverage"] = {}
        return
    cov: dict[str, list[str]] = {}
    for r in rows:
        label = _COVERAGE_TO_SCHEME.get(str(r["scheme"] or "").upper())
        if label is None:
            continue
        years = cov.setdefault(label, [])
        for y in str(r["years_present"] or "").split(","):
            y = y.strip()
            if y and y not in years:
                years.append(y)
    _cache["coverage"] = {k: sorted(v) for k, v in cov.items()}


def never_row_join() -> dict:
    """{'curated.v_employment': {'curated.v_expenditure', ...}, ...} or {}."""
    return _cache["join_rules"]


def readonly_denied() -> "set[tuple[str, str, str]]":
    """(schema, table, column) the read-only role may not SELECT, or empty."""
    return _cache["denied"]


def cme_file_status_readable() -> bool:
<<<<<<< ours
    """curated.v_cm_elevate.scheme_specific — the JSON that holds CM Elevate's file_status —
    is among the columns the read-only role may SELECT. Locked by the ingestion team on
    2026-10-16; the CM Elevate "pending" rule of 2026-10-30 needs it. False until the live
    schema has been read, so a cold start never writes the column."""
    cols = (live_columns() or {}).get("curated.v_cm_elevate") or []
    return any(c.get("column") == "scheme_specific" for c in cols)
=======
    """Every column the CM Elevate pending rule needs (app.cme_pending_rule, read from the
    knowledge base) is among the columns the read-only role may SELECT. scheme_specific — where
    file_status lives — was locked by the ingestion team on 2026-10-16 (KI-624). False until the
    live schema has been read, so a cold start never writes a locked column."""
    from app import cme_pending_rule   # local: it imports this module for live_columns()
    return cme_pending_rule.readable()
>>>>>>> theirs


def column_unit(table: str, column: str) -> "str | None":
    """The UNIT semantic.column_catalog records for table.column ("rupees", "lakh
    rupees", "crore rupees", "persons" …), or None (not recorded / catalog unread)."""
    t, c = str(table or "").lower(), str(column or "").lower()
    for row in _cache.get("columns") or []:
        if str(row.get("table_name") or "").lower() == t and str(row.get("column_name") or "").lower() == c:
            u = str(row.get("unit") or "").strip().lower()
            return u or None
    return None


def coverage_years() -> dict:
    """{'Focus Plus': ['2022-23', '2025-26'], 'CM Elevate': [], ...} or {} when unread."""
    return _cache["coverage"]


async def _readonly_denied_columns() -> "set[tuple[str, str, str]]":
    """(schema, table, column) the read-only role may NOT select, or an empty set
    when that role does not exist / cannot be checked."""
    try:
        rows = await db.fetch_rows_readonly(
            """SELECT n.nspname AS s, c.relname AS t, a.attname AS col
               FROM pg_class c
               JOIN pg_namespace n ON n.oid = c.relnamespace
               JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
               WHERE n.nspname = ANY($1::text[]) AND c.relkind IN ('r', 'v', 'm', 'p', 'f')
                 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $2)
                 AND NOT has_column_privilege($2, c.oid, a.attnum, 'SELECT')""",
            [list(_QUERYABLE_SCHEMAS), _READONLY_ROLE])
    except Exception as e:  # noqa: BLE001
        logger.warning("schema_introspect: %s column grants not read: %s", _READONLY_ROLE, e)
        return set()
    return {(r["s"], r["t"], r["col"]) for r in rows}


async def _load_live_schema() -> None:
    """Read the real structure of curated/semantic straight from the catalog —
    so the SQL prompt lists the columns that exist today, not a hand-maintained
    copy that drifts. Best-effort: any failure leaves live_columns empty and the
    prompt falls back to schema_context.py alone."""
    try:
        col_rows = await db.fetch_rows_readonly(
            """SELECT table_schema, table_name, column_name, data_type, is_nullable
               FROM information_schema.columns
               WHERE table_schema = ANY($1::text[])
               ORDER BY table_schema, table_name, ordinal_position""",
            [list(_QUERYABLE_SCHEMAS)],
        )
        denied = await _readonly_denied_columns()
        _cache["denied"] = denied
        by_table: dict[str, list[dict]] = {}
        for c in col_rows:
            key = f"{c['table_schema']}.{c['table_name']}"
            if key in PRIVATE_TABLES or (c["table_schema"], c["table_name"], c["column_name"]) in denied:
                continue
            by_table.setdefault(key, []).append({
                "column": c["column_name"],
                "type": c["data_type"],
                "nullable": c["is_nullable"] == "YES",
            })
        _cache["live_columns"] = by_table
        if denied:
            logger.info("schema_introspect: %d column(s) %s cannot read left out of the live schema",
                        len(denied), _READONLY_ROLE)

        # pg_catalog (not information_schema.constraint_column_usage) — the latter
        # returns nothing for a role that doesn't own the tables; pg_constraint is
        # world-readable and handles composite keys.
        fk_rows = await db.fetch_rows_readonly(
            """SELECT ns.nspname   AS from_schema, cl.relname   AS from_table,
                      att.attname  AS from_column,
                      fns.nspname  AS to_schema,  fcl.relname  AS to_table,
                      fatt.attname AS to_column
               FROM pg_constraint con
               JOIN pg_class cl       ON cl.oid  = con.conrelid
               JOIN pg_namespace ns   ON ns.oid  = cl.relnamespace
               JOIN pg_class fcl      ON fcl.oid = con.confrelid
               JOIN pg_namespace fns  ON fns.oid = fcl.relnamespace
               JOIN unnest(con.conkey)  WITH ORDINALITY AS k(attnum, ord)  ON TRUE
               JOIN unnest(con.confkey) WITH ORDINALITY AS fk(attnum, ord) ON fk.ord = k.ord
               JOIN pg_attribute att   ON att.attrelid  = cl.oid  AND att.attnum  = k.attnum
               JOIN pg_attribute fatt  ON fatt.attrelid = fcl.oid AND fatt.attnum = fk.attnum
               WHERE con.contype = 'f'
                 AND ns.nspname = ANY($1::text[])
               ORDER BY 1, 2, 3""",
            [list(_QUERYABLE_SCHEMAS)],
        )
        _cache["live_fks"] = [
            {"from": f"{r['from_schema']}.{r['from_table']}", "from_column": r["from_column"],
             "to": f"{r['to_schema']}.{r['to_table']}", "to_column": r["to_column"]}
            for r in fk_rows
            if f"{r['from_schema']}.{r['from_table']}" not in PRIVATE_TABLES
            and f"{r['to_schema']}.{r['to_table']}" not in PRIVATE_TABLES
        ]
        _cache["live_loaded"] = True
        logger.info("schema_introspect: live schema — %d tables, %d FK edges",
                    len(by_table), len(_cache["live_fks"]))
    except Exception as e:  # noqa: BLE001 — never block startup on introspection
        logger.warning("schema_introspect: live schema read failed (prompt uses "
                       "hand-written schema_context only): %s", e)


def live_columns() -> dict:
    """{'curated.fact_pmay_house': [{'column','type','nullable'}, ...], ...} or {}."""
    return _cache["live_columns"]


def live_fks() -> list:
    """[{'from','from_column','to','to_column'}, ...] or []."""
    return _cache["live_fks"]


def _matches_scheme(subject_area: str | None, schemes: list[str]) -> bool:
    if not subject_area:
        return True  # shared objects (geography, year) apply to every scheme
    mapped = _SUBJECT_TO_SCHEME.get(str(subject_area).strip().lower())
    return mapped is None or mapped in schemes


def _is_private_or_fact(c: dict) -> bool:
    """A column note on a privacy table, or on a curated.fact_* table: the views
    carry every fact column with the same notes (the ingestion team dropped the
    fact-table documents on 2026-10-16), and the generator queries the views."""
    table = str(c.get("table_name") or "").lower()
    return f"{c.get('table_schema')}.{table}" in PRIVATE_TABLES or table.startswith("fact_")


def _unit_and_values(c: dict, *, max_values: int = 40) -> str:
    """'UNIT: lakh rupees. VALUES (complete list, use these exact literals): a, b'
    from a column_catalog row; '' when it has neither."""
    parts = []
    unit = str(c.get("unit") or "").strip()
    if unit:
        parts.append(f"UNIT: {unit}.")
    vals = c.get("sample_values")
    if isinstance(vals, (list, tuple)) and vals:
        shown = [str(v) for v in vals[:max_values]]
        more = f", … ({len(vals)} values)" if len(vals) > max_values else ""
        parts.append("VALUES (complete list, use these exact literals): "
                     + ", ".join(f"'{v}'" for v in shown) + more)
    return " ".join(parts)


# Name parts too common to tell a shared table's notes apart: nearly every question
# says "district" or "year", so matching on them would keep every shared note.
_FOCUS_GENERIC = frozenset({"v", "dim", "bridge", "fact", "curated", "semantic", "id", "key", "code", "name",
                            "names", "lgd", "raw", "year", "years", "financial", "fy", "district", "districts",
                            "block", "blocks", "village", "villages", "state", "total", "count", "amount",
                            "scheme", "schemes", "source", "short", "label", "type", "the", "of", "in"})


def _focus_words(text: str) -> "set[str]":
    """Lower-case words of `text` and of snake_case names, a plural 's' dropped."""
    from app.text_match import words
    out = set()
    for w in words((text or "").replace("_", " ")):
        w = w.lower()
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out - _FOCUS_GENERIC


def catalog_block(schemes: list[str], *, max_terms: int = 24, focus: "str | None" = None) -> str:
    """A compact 'LIVE CATALOG' block scoped to the classified scheme(s).
    Empty string when the catalog didn't load.

    `focus` (B4 prompt pruning, 2026-10-27): the question text. Given, a SHARED
    table's column notes (dim_*, v_cross_scheme_*, v_district_year_summary,
    v_place_names …) are kept only when the question's words name that table or
    column; every scheme-specific note, table note, term and metric stays. Used
    only as a compressor when the SQL prompt is over budget: the over-budget
    prompts were cutting the worked examples from 5 to 1 instead."""
    if not _cache["loaded"]:
        return ""
    lines: list[str] = []

    tbls = [t for t in _cache["tables"] if _matches_scheme(t.get("subject_area"), schemes)
            and t["table_schema"] in ("curated", "semantic")]
    if tbls:
        lines.append("LIVE CATALOG — table notes (from semantic.table_catalog):")
        for t in tbls[:30]:
            desc = (t.get("description") or t.get("grain") or "").strip().replace("\n", " ")
            if desc:
                lines.append(f"  {t['table_schema']}.{t['table_name']}: {desc[:240]}")

    gloss = [g for g in _cache["glossary"] if _matches_scheme(g.get("subject_area"), schemes)]
    if gloss:
        lines.append("\nLIVE CATALOG — business terms (from semantic.glossary):")
        for g in gloss[:max_terms]:
            tgt = g.get("maps_to_column") or g.get("maps_to_object") or ""
            tail = f"  -> {tgt}" if tgt else ""
            # Synonyms are the half that makes a term matchable: a glossary
            # entry pointing at a column is only useful if the generator can
            # recognise the user's phrasing for it ("as per the spreadsheet",
            # "the raw block"). Carry them when the catalogue provides them.
            syn = g.get("synonyms") or g.get("aliases") or ""
            if isinstance(syn, (list, tuple)):
                syn = ", ".join(str(s) for s in syn if s)
            syn = f"  [also: {str(syn)[:160]}]" if str(syn).strip() else ""
            lines.append(
                f"  \"{g['term']}\": {(g.get('definition') or '')[:260]}{tail}{syn}")

    # The table's columns are metric_key / sql_expression / base_object / unit /
    # filters_required. Until 2026-10-16 this read metric / formula (keys the
    # table never had), so not one definition reached the prompt — including
    # cm_elevate_applications = COUNT(DISTINCT request_id) and the "count once
    # over all rows, never add per-year results" rules.
    metrics = [m for m in _cache["metrics"]
               if m.get("is_active") is not False and _matches_scheme(m.get("subject_area"), schemes)]
    if metrics:
        lines.append("\nLIVE CATALOG — metric definitions (from semantic.metric_definitions):")
        for m in metrics[:30]:
            name = m.get("metric_key") or m.get("metric") or m.get("name")
            formula = m.get("sql_expression") or m.get("formula") or m.get("expression")
            if not (name and formula):
                continue
            base = f" FROM {m['base_object']}" if m.get("base_object") else ""
            unit = f" [{m['unit']}]" if m.get("unit") else ""
            rule = (m.get("filters_required") or "").strip().replace("\n", " ")
            rule = f" — {rule[:300]}" if rule else ""
            lines.append(f"  {name} = {str(formula)[:200]}{base}{unit}{rule}")

    # data_quality_note carries the traps that actually break queries (a new
    # identity column, a verbatim source misspelling, a case-sensitive storage
    # format) — surfaced ahead of description since that's what a query
    # generator needs to see before writing SQL, not after something breaks.
    cols = [c for c in _cache["columns"] if _table_matches_scheme(c.get("table_name"), schemes)]
    # Scheme-specific traps first, shared dim_* notes after — so the max_terms
    # cap (below) trims generic geography/year notes before it ever trims a
    # scheme-specific one, regardless of which sorts first alphabetically.
    # A data_quality_note is a trap that produces a WRONG NUMBER if unseen (a
    # column whose twin holds an uncorrected value, a verbatim source
    # misspelling, a case-sensitive literal). A plain `description` is only
    # helpful context. Order notes ahead of descriptions so the max_terms cap
    # trims the merely-useful before the load-bearing — otherwise a scheme with
    # many documented columns can push its own traps out of the prompt
    # entirely, which is how a "which block column?" distinction that IS
    # documented in semantic.column_catalog can still fail to reach the
    # generator (raised 2026-09-18).
    cols = sorted(cols, key=lambda c: (not _is_scheme_specific_table(c.get("table_name")),
                                       not (c.get("data_quality_note") or "").strip()))
    if cols:
        lines.append("\nLIVE CATALOG — column notes (from semantic.column_catalog):")
        # The cap budgets DESCRIPTIONS only. Every data_quality_note for a
        # scheme in play is emitted, however many there are: each one is a
        # documented way to get a wrong number, so silently dropping the 25th
        # defeats the point of reading the catalogue at all. Descriptions are
        # nice-to-have context and stay capped.
        # A UNIT or a VALUES list is load-bearing like a quality note (a guessed
        # unit or literal is a wrong number), so it is never cut by the budget.
        _desc_budget = max_terms
        _qwords = _focus_words(focus) if focus is not None else None
        for c in cols:
            if _is_private_or_fact(c) or (c.get("table_schema"), c.get("table_name"),
                                          c.get("column_name")) in _cache["denied"]:
                continue
            if _qwords is not None and not _is_scheme_specific_table(c.get("table_name")) \
                    and not (_focus_words(f"{c.get('table_name')} {c.get('column_name')}") & _qwords):
                continue
            quality = (c.get("data_quality_note") or "").strip()
            facts = _unit_and_values(c)
            if not quality and not facts:
                if _desc_budget <= 0:
                    continue
                _desc_budget -= 1
            note = quality or (c.get("description") or "").strip()
            if note or facts:
                # Quality notes keep more room than descriptions: theirs is the
                # text that names the other column, the trigger phrasing and the
                # worked figures, and 280 chars routinely cut that mid-sentence.
                limit = 600 if quality else 280
                text = " ".join(p for p in (note[:limit], facts) if p)
                lines.append(f"  {c['table_schema']}.{c['table_name']}.{c['column_name']}: {text}")

    return ("\n".join(lines) + "\n") if lines else ""


def snapshot() -> dict:
    return {
        "loaded": _cache["loaded"],
        "tables": _cache["tables"],
        "glossary": _cache["glossary"],
        "metrics": _cache["metrics"],
        "columns": _cache["columns"],
        "join_graph": _cache["joins"],
        "join_rules": {k: sorted(v) for k, v in _cache["join_rules"].items()},
        "coverage": _cache["coverage"],
        "live_loaded": _cache["live_loaded"],
        "live_columns": _cache["live_columns"],
        "live_fks": _cache["live_fks"],
    }

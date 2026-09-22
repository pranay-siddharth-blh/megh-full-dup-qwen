# Urgent PII Redaction — Follow-Up: JSONB Whole-Column Bypass + Audit Trail Gap

## Status
Proposal — two gaps found in the completed `urgent-pii-redaction` change
(`app/pii_guard.py`, wired into `app/pipeline.py::execute_with_repair`). Both
are re-verified against the live repo below, per this repo's standing
proposal-first process (see `CLAUDE.md` §"Planning source of truth").

## Why

**Gap #1 — `scheme_specific` whole-column bypass (CM Elevate).** Layer 1
(`pii_guard.find_blocked_columns`) is a word-boundary text scan for the 8
blocklisted key *names* (`dob`, `email_id`, `address`, `member_id`,
`family_id`, `pds_id`, `account_holder_name`, `ifsc_code`). A query that
selects the whole `scheme_specific` JSONB column — `SELECT scheme_specific
FROM curated.v_cm_elevate`, an alias form, or `SELECT *` — never mentions any
of those literal names, so Layer 1 never fires.

Layer 2 (`redact_rows`) then can't catch it either: `app/db.py::run_readonly`
registers no `asyncpg` type codec for `json`/`jsonb` (confirmed — no
`set_type_codec` call anywhere in `app/db.py`), so a JSONB column comes back
from `conn.fetch()` as a **raw JSON string**, e.g. `row["scheme_specific"] ==
'{"dob": "...", "gender_id": "Female", ...}'`. `redact_rows`'s dict
comprehension only drops *top-level dict keys*; the 8 PII fields are nested
inside that string, not top-level keys of the row, so nothing strips them.
Both layers miss it — a full bypass, not just a Layer-1 gap.

**Re-verified per this proposal's step 1 (`cmelevate_schema_partitions.yaml`
lines 470-488, 795-804): `scheme_specific` is NOT PII-only.** It holds ~125
fields total (one JSONB column carrying everything not promoted to a typed
column across CM Elevate's 15 sub-schemes), of which only 8 are the
blocklisted PII fields. The rest is legitimate, actively-used data —
critically **`gender_id`**, called out in the schema doc as "the one
genuinely useful demographic on this partition and it is reachable only
through JSONB" (CM Elevate is 61.4% female, per the doc's own worked example
at line 1090-1097: `SELECT scheme_specific ->> 'gender_id' AS gender, COUNT(*)
... GROUP BY 1`), plus scheme-specific fields the doc's own example queries
extract (e.g. "What extra fields does the Warehouse scheme record?").

**This contradicts the fallback the original instruction offered** ("if
scheme_specific is PII-only, blocklist any selection of it outright"). It
is not PII-only, so that simpler fix would break the documented, legitimate
gender-breakdown query and any other non-blocklisted `->>` extraction. The
fix must instead distinguish **whole-column exposure** (unsafe — dumps all 8
PII keys plus everything else at once) from **scoped key extraction**
(`scheme_specific ->> 'gender_id'` — safe, and already checked against the
blocklist by the existing per-key scan whenever the extracted key itself is
one of the 8).

**Gap #2 — audit trail doesn't record that a PII block happened.**
`app/routers/query.py`'s `ClarificationNeeded` handler (the catch block that
also fires for `pii-column-blocked`) builds a response dict `out` with no
`denied_by` key, and durably persists it via `conversation_store.persist_turn`
as-is. Both `app.conversation_turns` and `app.query_audit` already have a
`denied_by TEXT` column (`app/appdb.py:117,140`) — currently populated only
for hard authorization denials (`route == "denied"`, `pipeline.py:3226`,
`decision.check`) — but the clarification path never sets it, so every
clarification pause (scope-not-specified, year-not-specified,
entity-ambiguous, **and pii-column-blocked**) lands in both tables
indistinguishable from one another: `route = 'clarification'`, `denied_by =
NULL`. The `rule` string (`e.rule`, e.g. `"pii-column-blocked"`) only reaches
the `response` JSONB blob's nested `clarification.rule` field in
`app.conversation_turns` — not a queryable top-level column, and not present
in `app.query_audit` at all. The one place the rule is genuinely visible
today is the application log line at `pipeline.py:2758-2760`
(`logger.warning`), which is grep-only, not queryable, and has no retention
guarantee independent of the log files.

The same handler's `_mirror_audit` call (the JSONL log mirror,
`app/routers/query.py:171`) passes a **truncated** `{"route": "clarification"}`
dict, not the real `out` — so even the JSONL mirror's `deny_check` field
(`result.get("denied_by")`) is always `None` for every clarification,
including PII blocks.

## What Changes

### Fix #1 — `pii_guard.py` gains a container-column check (Layer 1) and a
JSON-string backstop (Layer 2)

- **Layer 1, new `find_container_exposure(sql, schemes)`:** a small
  per-scheme map of "container columns that are NOT PII-only" (currently just
  `{"CM Elevate": "scheme_specific"}`). For each active scheme with a
  container column, reject the SQL if:
  - the column is selected bare or aliased and NOT immediately followed by a
    JSON-extraction operator (`->>`, `->`, `#>`, `#>>`) — e.g. `SELECT
    scheme_specific`, `SELECT scheme_specific AS ss`; or
  - the SQL selects `*` (or `alias.*`) while the scheme's container column
    would be included (CM Elevate's `scheme_specific` is confirmed present in
    `curated.v_cm_elevate` — it does not appear in the schema doc's
    `columns_not_in_v_cm_elevate` list).
  A scoped `scheme_specific ->> 'key'` extraction is left alone by this new
  check; if `key` happens to be one of the 8 blocklisted names, the existing
  `find_blocked_columns` key-literal scan already catches it (unchanged).
  Wired into `execute_with_repair` right next to the existing
  `find_blocked_columns` call — either check firing raises the same
  `_pii_not_available_clarification(schemes)`, unexecuted, unrepaired.
- **Layer 2, `redact_rows` gains a JSON-value pass:** for every surviving
  row value, if it's a JSON-object string (or already a dict, defensively) —
  detected by `json.loads`, not by column name, so it also backstops a future
  container column Layer 1 doesn't know about yet — strip any blocklisted key
  found inside it and re-serialize (string stays a string; dict stays a
  dict). Non-blocklisted keys inside the same JSON value are preserved: this
  is the re-verified requirement from Gap #1's finding that `scheme_specific`
  carries real, non-PII data that must survive.

### Fix #2 — `denied_by` (and hence the rule) reaches the durable audit trail

- `app/routers/query.py`'s `ClarificationNeeded` handler sets `out["denied_by"]
  = e.rule` for every clarification rule (not only `pii-column-blocked` —
  it's the same one-line change in the one shared handler, and there is no
  reason `scope-not-specified` etc. shouldn't be equally queryable; flag for
  push-back if this is broader than wanted). This flows into
  `app.conversation_turns.denied_by` and `app.query_audit.denied_by`
  unchanged — `conversation_store.persist_turn` already reads
  `result.get("denied_by")` into both INSERTs (`app/conversation_store.py:48,
  94, 104-105`); **no schema migration needed**, no new column.
- The same handler's `_mirror_audit(...)` call passes the real `out` dict
  instead of the truncated `{"route": "clarification"}`, so the JSONL
  mirror's `deny_check` field also carries the rule — belt-and-braces
  consistency with the DB sinks, at no extra cost since `out` already has
  everything `_mirror_audit` reads.
- `allowed` is deliberately left as `route != "denied"` (still `True` for a
  clarification pause, PII or otherwise) — a clarification is a redirect, not
  a hard failure, and `denied_by = 'pii-column-blocked'` is already an
  unambiguous, indexable signal on its own (`WHERE denied_by =
  'pii-column-blocked'` finds every PII block regardless of route). Flagging
  this choice rather than silently deciding it — say so if `allowed` should
  flip to `False` for this specific rule.
- The specific blocklisted column name is still never persisted or logged to
  the audit row (only the rule tag) — consistent with the original
  proposal's "never name the column in user-facing text" design; the rule
  name alone is enough to know a PII block occurred and to count/alert on it.

## Impact

- Files: `app/pii_guard.py` (new function + `redact_rows` extension),
  `app/pipeline.py` (wire the new check into `execute_with_repair`),
  `app/routers/query.py` (`denied_by` on the clarification `out` dict,
  `_mirror_audit` gets the real dict), `tests/test_pii_guard.py` (extended),
  a new `tests/test_pii_audit_trail.py`.
- No schema migration (`app/appdb.py`) — `denied_by` already exists on both
  tables.
- `app/db.py`, `.env`, connection/role handling: untouched.
- Rollback: both are additive checks / an added dict key; reverting the
  wiring lines restores current (gapped) behavior.

## Explicitly Out of Scope (carried over, still flagged, not silently dropped)

- The `dob`+`address`+`village` re-identification combination risk (CM
  Elevate) — unchanged from the original proposal, still a product/policy
  decision, not attempted here.
- A live `semantic.column_catalog`-driven blocklist — still unconfirmed
  reachable (per the original proposal's task 0.3); this follow-up keeps the
  hardcoded `PII_BLOCKLIST` / new hardcoded container-column map.
- Extending the container-column check to other schemes' JSONB columns, if
  any exist beyond CM Elevate's `scheme_specific` — not found during
  re-verification; add if one turns up.

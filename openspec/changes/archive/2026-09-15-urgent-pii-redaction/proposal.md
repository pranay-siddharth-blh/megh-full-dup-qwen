# Urgent PII Redaction — Two-Layer Enforcement

## Status
Proposal — bootstrapped from the §11.4 fact-finding pass conducted earlier
this session (no code changes were made during fact-finding). This document
did not exist before this change; it is being created now as the foundation
task group requires re-confirming its content against the live
`*_schema_partitions.yaml` files rather than trusting the fact-finding
summary verbatim.

## Why

The fact-finding pass established that PII protection today is
**prompt-text-only** — `app/schema_context.py` tells the SQL-generating LLM
which columns are sensitive, but nothing in the code path enforces it. If
the LLM disobeys the prompt (or aliases a blocklisted column to dodge a
naive check), the column flows straight through `run_readonly()` →
`_answer_data`'s return dict → the HTTP response, `conversation_store
.persist_turn` (durable Postgres row), and both `response_cache` /
`semantic_cache` — all four sinks read the same dict object, confirmed by
tracing `_answer_data` → `answer_question` → `app/routers/query.py`.

This phase adds two independent, code-enforced layers:

1. **Layer 1 (pre-execution):** scan the generated SQL text for any
   blocklisted column identifier, per active scheme, before `run_readonly`
   executes it. Closes the case where a bare `SELECT member_id` slips
   through.
2. **Layer 2 (post-execution):** strip any blocklisted key from every row
   dict immediately after execution, before `_answer_data` builds its
   return dict. Closes the case where Layer 1's SQL-text scan is fooled
   (e.g. a column reached through an unexpected path) and guarantees no
   downstream consumer — response, persistence, either cache — ever sees
   the raw value, not just the client.

Layer 2 is the actual guarantee; Layer 1 is a cheaper, earlier trip-wire
that also lets the system respond with a clean "not available for this
scheme" message instead of silently amputating a column the user asked for
by name.

## Per-scheme blocklist (subject to 0.1 re-confirmation against the current
`*_schema_partitions.yaml` files before implementation starts)

- **MGNREGA:** none. No person-level column exists on any MGNREGA fact.
- **PMAY-G:** none reach the curated layer. `beneficiary_name` and
  `father_mother_name` are dropped at ingest, per
  `data/pmay/pmay_schema_partitions.yaml`.
- **Focus Plus:** `member_id`, `pincode` — both explicitly flagged
  `pii: true` in `data/focus_plus/focusplus_schema_partitions.yaml` and in
  `app/schema_context.py`'s `_FOCUSPLUS_RULES` (rule 5). `bank_name_raw` is
  explicitly exempted (identifies a bank, not a person).
- **CM Elevate:** `dob`, `email_id`, `address`, `member_id`, `family_id`,
  `pds_id`, `account_holder_name`, `ifsc_code` — per
  `data/cm_elevate/cmelevate_schema_partitions.yaml`'s `pii_rule.
  retained_in_scheme_specific` list. These are the columns NOT stripped at
  ingest (the stripped set — `epic_id`, `citizen_name`, `mobile_number`,
  `pan_number`, `bank_account_number`/`bank_account_no`/`bank_account` —
  never reaches the database at all, so blocklisting them is moot; they
  cannot appear in a result).

## What Changes

- New per-scheme PII blocklist data structure, loaded the same way
  `entity_resolver.py`/`annotations.py` load their per-scheme config (no
  new loading convention).
- New pre-execution check wired in between SQL repair success and
  `run_readonly` execution in `execute_with_repair`.
- New post-execution redaction wired in immediately after
  `rows = await run_readonly(sql)`, before `_answer_data`'s return dict is
  built — the single point that, per the fact-finding pass, propagates to
  every downstream consumer.

## Capabilities

### New Capabilities
- `pii-sql-blocklist`: rejecting generated SQL that references a
  blocklisted column, per active scheme, before execution.
- `pii-row-redaction`: stripping blocklisted keys from every result row
  before any downstream consumer (response, persistence, both caches) can
  observe them.

### Modified Capabilities
(none — `openspec/specs/` has no existing PII-related capability)

## Explicitly Out of Scope (deferred / flagged, not silently dropped)

- **`dob` + `address` + `village` re-identification risk** (CM Elevate).
  Each column is individually blocklisted by this change, but the
  *combination* risk — three individually-permitted-elsewhere or
  differently-scoped fields together narrowing to one person — is a
  product/policy decision (e.g. suppression thresholds, k-anonymity) that
  this urgent fix does not attempt. Flagged, not resolved.
- **Live DB-driven blocklist via `semantic.column_catalog`.** This phase
  ships with the hardcoded per-scheme list above regardless of whether
  that table exists (checked in task 0.3). If it exists and carries
  `pii`/`sample_values` flags as the schema-partition docs imply, a
  fast-follow can replace the hardcoded list with a live query — out of
  scope here.
- **SQL AST-level validation** (replacing the pre-execution text scan with
  a real parser). The Phase 1 proposal already flags a full SQLGlot
  validator as future work for `_assert_safe`; this phase's Layer 1 is a
  cheaper regex/word-boundary scan, not that validator.

## Impact

- Affected files (expected; confirmed exact list during implementation):
  `app/pipeline.py` (both layers wired in), a new small module or data file
  for the blocklist (pattern TBD in task 1.1), `tests/` (new test file(s)
  for both layers).
- `app/db.py`, `.env`, and connection/role handling are explicitly
  untouched (confirmed via `git diff` in task 3.2).
- Rollback: both layers are additive checks around existing call sites: a
  revert of the wiring changes (not the blocklist data itself) fully
  restores current behavior.

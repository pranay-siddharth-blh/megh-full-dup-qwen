## 0. Confirm the foundation

- [x] 0.1 Re-grepped all four `*_schema_partitions.yaml` files fresh
      (not reusing the fact-finding pass's summary). No discrepancy:
      MGNREGA — no PII markers at all. PMAY-G — `beneficiary_name`,
      `father_mother_name` dropped at ingest (`pmay_schema_partitions
      .yaml:539-545`), nothing reaches curated. Focus Plus —
      `member_id`, `pincode`, both `pii: true`
      (`focusplus_schema_partitions.yaml:472-505`). CM Elevate —
      `pii_rule.retained_in_scheme_specific:
      [dob, email_id, address, member_id, family_id, pds_id,
      account_holder_name, ifsc_code]`
      (`cmelevate_schema_partitions.yaml:795-798`); the separately
      listed `stripped_at_ingest` set never reaches the DB at all, so
      blocklisting it would be moot. New nuance found (not a blocklist
      discrepancy, a design note for 1.2): CM Elevate's 8 blocklisted
      fields are JSONB keys inside `scheme_specific`
      (`scheme_specific ->> 'member_id'`), not top-level SQL columns —
      a `\bmember_id\b` word-boundary scan over the *full* SQL text
      still catches the quoted form (apostrophes are non-word chars),
      so no special-casing needed, but the check must scan the whole
      SQL string, not just a parsed SELECT-list.
- [x] 0.2 Confirmed current line numbers directly (unchanged from the
      fact-finding pass — only `app/main.py` was touched this session,
      not `pipeline.py`): Layer 1 inserts between `pipeline.py:2721`
      (end of the semantic-verifier check) and `:2722`
      (`rows = await run_readonly(sql)`), inside `execute_with_repair`
      (`pipeline.py:2666`) — the last point before execution. Layer 2
      inserts immediately after `:2722`, before `:2723`
      (`return sql, rows`), so `_answer_data` (`pipeline.py:3197`,
      which does `sql, rows = await execute_with_repair(...)` at
      `:3268`) receives already-redacted rows before building its
      return dict at `:3327`. A third `run_readonly` call site exists
      at `pipeline.py:1289`, inside `refresh_scheme_years()`
      (startup-only, `year_key`-only, never user-facing) — confirmed
      out of scope for both layers.
- [x] 0.3 Attempted via `app.db`'s existing pool/settings (no new
      connection method or credentials): `OSError [WinError 121]` —
      network-level timeout, no live database reachable from this dev
      environment. Cannot confirm or deny `semantic.column_catalog`'s
      existence empirically; not treated as a blocker since this phase
      ships with the hardcoded list regardless (per 3.3 below, this is
      recorded as unresolved for the fast-follow, not answered).

## 1. Layer 1 — pre-execution SQL-text blocklist check

- [x] 1.1 Write the per-scheme blocklist as a simple, loadable structure
      (module dict or YAML — match whichever pattern
      `entity_resolver.py`/`annotations.py` already use for per-scheme
      config, don't invent a new loading convention).
- [x] 1.2 `pii_guard.find_blocked_columns(sql, schemes)` — union of the
      active schemes' blocklisted columns, each matched against the
      *full* SQL text with `\b<col>\b` (case-insensitive). Full-text
      scan (not a parsed SELECT-list) so it also catches CM Elevate's
      `scheme_specific ->> 'member_id'` JSONB-key form per 0.1's finding.
      `app/pii_guard.py`.
- [x] 1.3 Wired into `execute_with_repair` at `pipeline.py:2752-2761`,
      right before `rows = await run_readonly(sql)` (per 0.2's insertion
      point). On a match: raises `ClarificationNeeded` via the new
      `_pii_not_available_clarification(schemes)` (`pipeline.py:844-866`,
      next to `_bank_clarification` — same shape:
      `_PII_NOT_AVAILABLE_TEXT` per-scheme dict + `_PII_GENERIC_TEXT`
      fallback, `rule="pii-column-blocked"`), never executes, never
      repaired — added `except ClarificationNeeded: raise` next to the
      existing `except SQLAuthorizationDenied: raise` so the generic
      `except (UnsafeSQLError, Exception)` repair-retry clause can't
      catch it. `logger.warning` logs the matched column name(s); the
      `ClarificationNeeded.question` text never does.
- [x] 1.4 `tests/test_pii_guard.py`, sections 1-5: (a) bare `SELECT
      member_id` rejected; (b) `SELECT member_id AS mid` still rejected,
      plus an added case beyond the checklist —
      `scheme_specific ->> 'member_id'` (CM Elevate JSONB form) also
      rejected; (c) `pincode_verified_flag` NOT falsely rejected, query
      actually executes; (d) MGNREGA/PMAY-G with the literal column text
      present are never rejected (empty blocklist); (e) rejection text
      contains no blocklisted column name while the captured log does.
- [x] 1.5 `python tests/test_pii_guard.py` — 9/9 checks in sections 1-5
      PASS. Full run reported below.

## 2. Layer 2 — post-execution row redaction

- [x] 2.1 `pii_guard.redact_rows(rows, schemes)` — returns new dicts
      (dict comprehension excluding blocklisted keys; never mutates the
      input row), full key removal not nulling. Short-circuits to the
      same `rows` object, unchanged, when no active scheme has a
      blocklist. `app/pii_guard.py`.
- [x] 2.2 Wired into `execute_with_repair` at `pipeline.py:2762-2768`,
      immediately after `rows = await run_readonly(sql)` and before
      `return sql, rows` (per 0.2's insertion point) — so `_answer_data`
      (`pipeline.py:3268`) and everything it builds downstream
      (`pipeline.py:3327`'s return dict, hence the HTTP response,
      `conversation_store.persist_turn`, `response_cache`,
      `semantic_cache` — confirmed in the fact-finding pass to all read
      that same object) only ever see redacted rows.
- [x] 2.3 `tests/test_pii_guard.py`, sections 6-9: (a) `member_id`/
      `pincode` keys entirely absent from the output row, not `None`;
      (b) `amount_disbursed` survives with its original value, original
      input row left unmutated; (c) a row with no blocklisted keys is
      content-identical after redaction; (d) integration-style backstop
      test — a `SELECT *` query (no literal column name, so Layer 1
      doesn't fire) whose fake `run_readonly` returns rows containing
      `member_id`/`pincode` anyway: confirmed `execute_with_repair`'s
      returned `rows` — the exact object that reaches `_answer_data`'s
      return dict and that `conversation_store.persist_turn` reads via
      `result["data"]`, per 0.2 — has both keys stripped by Layer 2 even
      though Layer 1 couldn't see them.
- [x] 2.4 Same run as 1.5 (one test file covers both layers) —
      9/9 checks in sections 6-9 PASS. Full run reported below.

## 3. Regression + exit

- [x] 3.1 Full sweep — all 9 Phase-4 suites + the new
      `tests/test_pii_guard.py` (10 files total): every file exits 0,
      zero `FAILED` markers. No existing test depends on a blocklisted
      column being returned; nothing needed a workaround.
- [x] 3.2 `git diff --stat` confirms `app/db.py` has zero diff;
      `app/auth.py` and `app/deps.py` (connection/role handling) have
      zero diff. `.env.example` shows a diff but it is pre-existing
      working-tree state from before this session (same unrelated
      Qdrant->pgvector-era noise flagged for `app/main.py` earlier this
      conversation) — not touched by this change. `.env` is not tracked
      and was never opened. Files actually touched this session:
      `app/pipeline.py` (modified), `app/pii_guard.py` (new),
      `tests/test_pii_guard.py` (new),
      `openspec/changes/urgent-pii-redaction/{proposal.md,tasks.md}`
      (new), `openspec/changes/phase-5-findings-and-charts/proposal.md`
      (modified, from the prior retirement-note task).
- [x] 3.3 **Fast-follow seed, recorded here so it isn't lost**: task 0.3
      attempted a read-only `information_schema` check for
      `semantic.column_catalog` via `app.db`'s existing pool/settings
      (no new connection method or credentials) and got
      `OSError [WinError 121]` — a network-level timeout, no live
      database reachable from this dev environment. **Unresolved**:
      whether `semantic.column_catalog` exists, and if so whether it
      carries `pii`/`sample_values` flags as the `*_schema_partitions
      .yaml` docs imply (e.g. Focus Plus's `pii: true` /
      `sample_values: WITHHELD_PII` per-column annotations). The
      fast-follow task should re-run this exact check
      (`SELECT table_schema, table_name FROM information_schema.tables
      WHERE table_schema = 'semantic' AND table_name =
      'column_catalog'`) against a reachable environment before
      deciding whether to replace `app/pii_guard.py`'s hardcoded
      `PII_BLOCKLIST` with a live query.
- [x] 3.4 **Explicitly not addressed by this fix**: the `dob` +
      `address` + `village` re-identification risk on CM Elevate
      (flagged in `cmelevate_schema_partitions.yaml:795-804`: "dob plus
      address plus village is re-identifying"). This change blocklists
      `dob` and `address` individually (each is fully stripped from
      every row by Layer 2, and blocked outright by Layer 1), but the
      *combination* risk — three fields that are each sensitive together
      narrowing to one person even if shown separately, or a related
      suppression/k-anonymity concern — is a separate product/policy
      decision this urgent fix does not attempt, per proposal.md's
      Explicitly Out of Scope. Since `dob` and `address` are both
      individually blocklisted here, they never reach a response at all
      under this fix — but the underlying policy question (should some
      *other*, currently non-blocklisted combination of fields also be
      suppressed together) remains open and flagged, not resolved.

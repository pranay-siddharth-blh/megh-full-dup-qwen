## 0. Re-verify (done, recorded here per this repo's process)

- [x] 0.1 Re-confirmed `app.query_audit`'s column list (`app/appdb.py:128-147`)
      and grepped `query_audit` across `app/` — no other code path wrote
      `sql`/`result_preview`/`findings`/`chart_type`/`answer` to it before
      this change.
- [x] 0.2 Re-confirmed `result.get("findings")` and `result.get("chart_type")`
      are still the exact keys the pipeline returns (`app/pipeline.py:3434-3435`).
- [x] 0.3 Re-confirmed `deploy/sql/02_retention_policy.sql:36`'s
      `audit_retention` default is still `365 days`.

## 1. Schema migration — `app.query_audit`

- [x] 1.1 **Human sign-off** — user confirmed the recommended 20-row cap
      for `result_preview` (2026-09-12); recorded as
      `settings.AUDIT_RESULT_PREVIEW_ROWS = 20` in `app/config.py`.
- [x] 1.2 Added four nullable columns to the `app.query_audit` DDL block in
      `app/appdb.py`: `sql TEXT`, `result_preview JSONB`, `findings JSONB`,
      `chart_type TEXT`. Idempotent (`ADD COLUMN IF NOT EXISTS`), no
      backfill of historical rows.
- [x] 1.3 Confirmed `deploy/sql/01_create_megh_app_role.sql:79`'s
      `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA app` is
      table-level, so it already covers the new columns — no script change
      needed, no gap found.
- [x] 1.4 Adapted from a live-DB schema test (no DB connection available in
      this environment, consistent with every other test in `tests/`) to a
      static check that `app.appdb._DDL` contains each
      `ADD COLUMN IF NOT EXISTS` statement — `tests/test_query_audit_trail.py`
      section 0.

## 2. Write-path — populate the new fields

- [x] 2.1 `app/conversation_store.py`'s `_persist_turn`: extended the
      `app.query_audit` INSERT with `sql`, `result_preview` (capped to
      `settings.AUDIT_RESULT_PREVIEW_ROWS`), `findings`
      (`json.dumps(... or [], default=str)`), `chart_type`.
- [x] 2.2 `app/routers/query.py`'s `_mirror_audit`: added the same keys to
      the dict passed to `auth.audit()`, in parity with the Postgres row.
- [x] 2.3 Confirmed unchanged: `auth.audit()`'s `except Exception` (line
      322-323) and `_persist_turn`'s fire-and-forget `_spawn` wrapper both
      still wrap the new fields — no code change needed here, verified by
      inspection.
- [x] 2.4 New `tests/test_query_audit_trail.py` — 22/22 checks PASS,
      covering (a) normal population of all fields, (b) preview capped at
      20 rows from a 30-row result, (c) empty findings/None chart_type
      written explicitly not omitted, (d) JSONL mirror parity, (e)
      `delete_conversation` never references `app.query_audit`.

## 3. Documentation correction

- [x] 3.1 `docs/SECURITY.md` line 111 updated to list the five new fields.
- [x] 3.2 `docs/baseline-audit.md` §2 row 11.3: appended a dated
      (2026-09-12) update note — fields added/where, and storage/365-day
      retention ratified as intentional — original row text left intact.
- [x] 3.3 `openspec/changes/phase-2-orchestration-durability/proposal.md`:
      added an update note resolving the SQL-text/retention sub-question,
      pointing to this change; rest of that stub untouched.
- [x] 3.4 `openspec/changes/phase-6-observability-deployment/proposal.md`:
      added the matching update note; Kubernetes/rate-limiting questions
      untouched.

## 4. Post-review addition (2026-09-12) — final response text

The initial four-field pass (Groups 1-3) missed GT §11.3's "final
response" — caught when the user asked what was left and this was
re-checked against the original finding. Same gap pattern as the other
four fields: already in `app.conversation_turns.answer`, absent from
`app.query_audit` until this group. User confirmed adding it (2026-09-12).

- [x] 4.1 Added a fifth nullable column, `answer TEXT`, to the
      `app.query_audit` DDL block (`app/appdb.py`).
- [x] 4.2 `app/conversation_store.py`'s `_persist_turn`: added `answer`
      (already computed at the top of the function, capped to 4000 chars,
      same value used for `conversation_turns`) to the `app.query_audit`
      INSERT.
- [x] 4.3 `app/routers/query.py`'s `_mirror_audit`: added
      `"answer": result.get("answer")` to the JSONL mirror dict.
- [x] 4.4 Extended `tests/test_query_audit_trail.py` to assert the answer
      text is bound in both the Postgres INSERT and the JSONL mirror
      (sections 1, 2, 3) — now 22/22 checks PASS (up from 19).
- [x] 4.5 Updated `docs/SECURITY.md` and `docs/baseline-audit.md`'s 11.3
      update note to mention the fifth field.
- [x] 4.6 Re-ran the new test file and the full regression sweep — see
      Group 5 below for actual counts.

## 5. Regression + report

- [x] 5.1 `tests/test_query_audit_trail.py`: 22/22 checks PASS.
- [x] 5.2 Full regression sweep, all 13 files in `tests/` (excluding
      `smoke_restructure.py`, a manual/dev script): `test_chart_spec.py`,
      `test_context_manager.py`, `test_defaults_engine.py`,
      `test_findings.py`, `test_join_graph.py`, `test_pii_audit_trail.py`,
      `test_pii_guard.py`, `test_pipeline_join_discovery.py`,
      `test_pipeline_schema_retrieval.py`, `test_query_audit_trail.py`,
      `test_schema_retrieval.py`, `test_security.py`,
      `test_sql_join_validator.py` — every file exit 0, zero FAILED
      markers.
- [x] 5.3 `git diff --stat` reviewed: this change touched exactly
      `app/appdb.py`, `app/config.py`, `app/conversation_store.py`,
      `app/routers/query.py` (one hunk in `_mirror_audit` — the file's
      other diff hunks are pre-existing, unrelated uncommitted work from
      before this change, confirmed by inspection), `docs/SECURITY.md`,
      `docs/baseline-audit.md`, the two stub proposals' update notes, and
      new file `tests/test_query_audit_trail.py`.
- [x] 5.4 Reported to the human below. **Not committed** — awaiting the
      human's review and commit per this repo's standing process.

## Context

See `proposal.md` - Why for motivation. Relevant current-state facts
this design builds on (all re-verified against the live code, not
assumed from the audit doc):

- The audit trail is written from two call sites for the same logical
  event: `app/routers/query.py:246-264` (`_mirror_audit`, writes the
  JSONL file via `auth.audit()`) and `app/conversation_store.py:30-102`
  (`_persist_turn`, writes `app.query_audit` and, separately,
  `app.conversation_turns`). Both run fire-and-forget off the request
  path (`_persist_turn` is `_spawn`ed; `_mirror_audit` is called
  synchronously but `auth.audit()` itself swallows write errors —
  `app/auth.py:322-323`).
- `app.conversation_turns.response` (`conversation_store.py:55-76`)
  already serializes `sql` and `data` (rows, pre-capped to 200 by
  `app/pipeline.py:3432`) into a JSONB blob. This proposal does not
  reuse that blob for the compliance table — it adds typed columns to
  `app.query_audit` instead, so the fields are queryable/purgeable on
  their own terms rather than trapped inside a chat-history JSON blob
  that gets deleted with the conversation.
- `findings` and `chart_type` exist only in the pipeline's in-memory
  return dict (`app/pipeline.py:3422-3436`) today; neither table stores
  them.

## Goals / Non-Goals

**Goals:**
- Add executed SQL, a bounded result preview, findings, and chart_type
  to the durable `app.query_audit` record and its JSONL mirror, in
  parity with each other.
- Keep the audit write best-effort (matches existing behavior — see
  the `query-audit-trail` spec's "write failure never blocks the
  response" requirement).
- Keep the schema change purely additive and idempotent, consistent
  with the existing `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern
  already used once at `app/appdb.py:126`.

**Non-Goals:**
- Not restructuring how `_mirror_audit` and `_persist_turn` relate to
  each other, or deduplicating the two audit call sites — that is a
  larger refactor with its own risk and belongs to a separate change if
  ever pursued.
- Not changing what `app.conversation_turns.response` stores (see
  proposal's Explicitly Out of Scope on that table).
- Not adding an admin UI to view the new fields — `tasks.md` only
  covers whether existing audit-read paths need their column list
  touched, not new UI.

## Decisions

**New typed columns on `app.query_audit`, not a JSONB catch-all.**
`app.conversation_turns` already shows the JSONB-blob pattern
(`response` column) and it works for a "redraw the UI" use case. The
compliance table's job is different — an investigator or a retention
job needs to query/filter/purge on these fields, and typed columns
(`sql TEXT`, `result_preview JSONB`, `findings JSONB`, `chart_type
TEXT`) keep that possible without a JSON-path query for every access.
Alternative considered: one `extra JSONB` column for all four — rejected
because it would hide the schema from anyone reading `app/appdb.py`'s
DDL block, which is exactly the kind of implicit-structure problem the
Grant Thornton audit was written to surface in the first place.

**Result preview is a separate bounded field, not "reuse `data[:200]`."**
200 rows is the UI's cap, not a compliance-log cap — copying it
verbatim would make `query_audit` grow at roughly the same rate as
`conversation_turns`, defeating the purpose of a lean compliance
record. The exact number needs a reviewer decision (see `tasks.md`);
this design only fixes the shape (a JSONB array of row objects, same
row-serialization approach `conversation_store.py:55` already uses
with `default=str` for Decimal/date values) and states the constraint
that it must be materially smaller than the UI's 200-row cap.

**Populate all four fields from the pipeline's existing return dict —
no new computation.** `sql`, `data`, `findings`, and `chart_type` are
already produced by `app/pipeline.py:3422-3436`; this change only wires
already-computed values into two more write paths. No new SQL-capture
or findings/chart logic is introduced.

**JSONL mirror stays a mirror.** `auth.audit()`'s JSONL write
(`app/auth.py:313-324`) takes whatever dict it's given — the new fields
pass through unchanged. No schema/versioning mechanism is added to the
JSONL format; a consumer reading old lines simply sees the new keys
absent, which is already how JSONL's schemaless nature is used here.

## Risks / Trade-offs

- **[Result-preview size drives storage growth]** → Mitigated by
  requiring an explicit, reviewed cap (task with sign-off gate) rather
  than defaulting to the UI's 200-row cap; also covered by the
  already-ratified 365-day retention purge
  (`deploy/sql/02_retention_policy.sql`), which bounds the table's
  total lifetime size regardless of per-row cap.
- **[PII/sensitive data now duplicated into a second durable table]**
  → The result preview and SQL text can contain the same
  beneficiary-adjacent data `app.conversation_turns` already stores;
  this doesn't create a new class of exposure (same DB, same access
  controls, `megh_app`/`postgres` role scoping per Phase 1), but it
  does mean two tables to secure identically instead of one. Flagged
  as a task to confirm no additional grants are needed beyond what
  `deploy/sql/01_create_megh_app_role.sql` already covers for
  `app.query_audit`.
- **[Two write sites (`_mirror_audit`, `_persist_turn`) can drift out
  of parity again]** → Both are touched in the same task group in
  `tasks.md`, and the spec's scenarios cover both the JSONL and
  Postgres sides explicitly so a future change touching only one is
  caught by re-reading the spec, not just by convention.
- **[Fire-and-forget write failure hides a broken audit trail]** →
  Pre-existing behavior (`auth.py:322-323`'s `except Exception` with a
  log warning), not introduced by this change; the spec makes this
  explicit as a requirement so it's a documented trade-off going
  forward rather than an implicit one.

## Migration Plan

1. Add the four nullable columns to `app.query_audit` via an additive,
   idempotent DDL statement (same file/pattern as
   `app/appdb.py:126`'s `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) —
   runs automatically via `ensure_schema()` on next deploy, no manual
   migration step, no backfill of historical rows (they stay `NULL`
   for the new columns).
2. Update `_persist_turn`'s INSERT and `_mirror_audit`'s dict to
   populate the new fields going forward.
3. Update `docs/SECURITY.md` and `docs/baseline-audit.md` once (1)-(2)
   are live and verified.
4. Rollback: dropping the four columns (or simply reverting the write-
   path code and leaving the nullable columns unused) is safe at any
   point — no other code path reads them yet, so there is no forward
   dependency to unwind.

## Open Questions

- Exact `result_preview` row cap and whether it should differ by role
  or query size — deferred to the task requiring reviewer sign-off;
  answering it does not change this design's shape (a bounded JSONB
  array) or the spec's requirements.

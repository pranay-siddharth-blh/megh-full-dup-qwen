# Phase 1 — Security Hardening

## Status
**2 of 3 items implemented and committed** (`c9834a0`, "Phase 1: session
ownership check, repair re-authorization, max_repairs 2->1") — this header
was not updated when that work landed; corrected 2026-09-11 after
re-verifying the claim against the actual diff rather than trusting this
file at face value.

- Item 1 (session ownership check) — **done.**
  `app/session_store.py:179-180` raises `SessionOwnershipError` when a
  session id is already bound to a different `user_id`.
- Item 2 (repair re-authorization + `max_repairs` cap) — **done.**
  `app/pipeline.py:2705-2714` calls `auth.authorize()` on every repair
  attempt via `SQLAuthorizationDenied`; `max_repairs` is `1`
  (`pipeline.py:2700`).
- Item 3 (SELECT-only DB role cutover) — **not done, blocked on
  production infra access.** `deploy/sql/01_create_megh_app_role.sql` is
  scripted but unapplied; production still connects as the `postgres`
  superuser (confirmed via static analysis, `docs/baseline-audit.md` §3
  finding 9). Cutting over requires a superuser session against the live
  production database and a coordinated restart — out of scope for a
  coding session; needs a scheduled maintenance window run by whoever
  holds production DB credentials.

## Why

Phase 0's audit found two concrete, exploitable issues and one unverified
production claim. This phase fixes exactly those — not the full Section
3A–3F list from the original instructions, and not the broader defense-in-
depth items (RLS, ClickHouse audit trail) that belong in later phases once
orchestration exists to feed them.

1. **`SessionStore.ensure()` has no ownership check.**
   [cite: `app/session_store.py:156-174`, specifically `165-166` — `user_id`
   is only ever set when the slot is empty, never checked against an
   existing owner. Call site: `app/routers/query.py:80`. Session ID is
   sourced from the request body or `X-Session-Id` header
   (`query.py:69,74`), validated only by regex (`query.py:37`) — no
   ownership check. Default session-id pattern is guessable:
   `day-{user_id}-{date}` (`query.py:77`).]
   A session/conversation ID is accepted and resumed without confirming it
   belongs to the authenticated requester. Audit's own framing: this is a
   cross-user *context* leak (another user's conversation history/state
   becomes readable or resumable), not a data leak — SQL execution is
   still re-authorized per requester via `auth.authorize()`. That
   distinction matters for severity but not for priority — and the
   guessable ID pattern (`day-{user_id}-{date}`) makes this worse than a
   generic ownership gap: a session ID for a *specific other user* can be
   constructed, not just stumbled into. Conversation history for scheme
   administration queries is still sensitive (may contain geography,
   beneficiary counts, or phrasing that reveals what another user was
   investigating).

2. **Repaired SQL is never re-authorized, and the repair cap is wider
   than the Grant Thornton proposal specifies.**
   [cite: `auth.authorize()` defined at `app/auth.py:223-304`; its only
   call site in the whole pipeline is `app/pipeline.py:3222-3224`,
   immediately before `execute_with_repair(..., initial_sql=sql)` at
   `pipeline.py:3229`. The repair loop itself is `app/pipeline.py:2606-2667`;
   regeneration happens at `pipeline.py:2662-2666`
   (`build_repair_prompt` → `llm.call_sql_generator`), and the
   regenerated SQL executes at `pipeline.py:2651` with no further
   `authorize()` call.]
   `auth.authorize()` runs exactly once, before the repair loop, against
   the first-generated SQL. If regeneration (on validation failure)
   produces a query touching different tables, columns, or scope than the
   original, it executes without a second authorization check. This is
   the more serious of the two findings: it's a scope-widening path, not
   just a context leak.

   Additionally — this is a confirmed mismatch, not a citation gap —
   `max_repairs: int = 2` is the current default (`pipeline.py:2607`),
   meaning **two** repair attempts (three tries total), not the Grant
   Thornton proposal's "one automatic retry." Each additional untracked
   attempt is another unauthorized shot at a different query shape, so
   this compounds finding 2 rather than being a separate issue — fixing
   re-authorization without also tightening the cap still leaves three
   unauthorized tries instead of one.

3. **SELECT-only DB role is provisioned but not confirmed live.**
   [cite: `deploy/sql/01_create_megh_app_role.sql:5` — header comment
   stating the service "currently connects as `postgres` (superuser)."
   Role grants at line `41` (`NOBYPASSRLS`) and lines `52-92`
   (`GRANT SELECT` on `curated`/`semantic`). Also referenced in
   `docs/SECURITY.md:42`.]
   The provisioning SQL script's own header comment states production
   currently connects as `postgres` (superuser). If still true, defense-
   in-depth layer 2 of the proposal's Section 11.1 (dedicated read-only
   role) doesn't exist in production regardless of what the script
   defines — every other safety layer (`_assert_safe`, any future
   SQLGlot validator) is the *only* thing standing between a validation
   bug and a write to production tables. This must be verified against
   the actual running connection string before this phase can be marked
   done, not assumed from the script's existence or its own comment
   (the comment could itself be stale).

## What Changes

- `session_store.ensure()` (and any other entry point that resumes a
  session by ID — check both request-body and header paths per the
  Phase 0 task list) rejects any session/conversation ID not owned by the
  authenticated user's `user_id`/tenant, before any state is read or
  returned. Ownership is derived from a database-backed record, not
  trusted from the ID's shape or an unauthenticated claim in the request.
- The pipeline's repair path (wherever `app/pipeline.py` regenerates SQL
  after a validation failure) calls `auth.authorize()` again on the
  repaired candidate, using the same `UserScope` and resolved entities as
  the original call, before that candidate reaches execution. A denial on
  the repaired candidate terminates the request — it does not trigger a
  second repair attempt.
- `max_repairs` in `app/pipeline.py:2607` is reduced from `2` to `1`,
  matching the Grant Thornton proposal's "one automatic retry." This is
  a one-line change but a real behavior change — confirm with whoever
  owns query quality that dropping the second repair attempt doesn't
  meaningfully raise the failure rate on hard queries before shipping;
  if it does, that's a signal SQL generation quality (a later-phase
  concern) needs attention, not a reason to keep a wider unauthorized
  retry window open.
- Confirm and document (not assume) which Postgres role the application's
  runtime connection actually uses in the current production environment.
  If it is `postgres` or any other superuser/write-capable role, this
  phase's exit criteria include cutting production over to the
  provisioned read-only role — this is not optional hardening, it's
  closing the gap the audit found.

## Capabilities

### New Capabilities
- `session-ownership`: verifying that a resumed session/conversation
  identifier belongs to the authenticated requester before any state is
  read or returned.
- `sql-repair-authorization`: re-authorizing SQL that the repair loop
  regenerates after a validation failure, and capping repair attempts.
- `database-execution-privilege`: the runtime database connection used to
  execute generated SQL holding only read privileges, independent of
  application-level validation.

### Modified Capabilities
(none — `openspec/specs/` has no existing capabilities yet; all three
above are new)

## Explicitly Out of Scope (deferred to later phases)

- Row-level security policies (11.2) — depends on a stable geography/
  scheme scope model that Phase 3's schema work will formalize; adding
  RLS now against an incomplete scope model risks false security.
  **Update (2026-09-15)**: picked up by
  `openspec/changes/multi-tenant-rls-scheme-scaleout` — a tenant↔scheme
  entitlement model (not the geography model this bullet anticipated) now
  backs RLS on the curated fact tables. Still shares this item's own
  blocker: RLS is a no-op against a superuser connection, so production
  activation is gated on this same DB-role cutover.
- Replacing `_assert_safe` with a full SQLGlot AST validator — that is
  real, substantial work (CTEs, nested queries, set operations, function
  allowlisting) and deserves its own reviewed proposal, not a bullet in
  this one. Flagged here as **next**, immediately after this phase, not
  skipped.
- ClickHouse/structured audit trail — depends on Phase 6's observability
  stack; `auth.py::audit()`'s existing file-based logging stays as-is for
  now.
- Separate connection pools for analytics vs. application-state writes —
  real DB privilege separation belongs with the role-verification work in
  this phase's item 3, but splitting `app/db.py` into two pools with two
  credentials is enough surface area to warrant its own task group;
  included here as a task, not folded silently into "fix the role."
- Any legacy ingestion, backfill, or quarantine-table code — permanently
  out of scope per the standing instruction.

## Impact

- Affected files (expected, confirm exact list during implementation):
  `app/session_store.py`, `app/pipeline.py`, `app/auth.py`, `app/db.py`,
  `app/deps.py` (if session validation happens at the dependency-injection
  layer), `app/routers/query.py`, `app/routers/history.py`.
- No API contract changes expected — ownership enforcement should produce
  a 403/404 on unauthorized session access, not a new response shape.
  Confirm with whoever owns the frontend before changing status codes on
  an existing endpoint.
- Rollback: each of the three changes is independently revertible (single
  commit per change item recommended) since they don't depend on each
  other's implementation, only on the audit's findings.

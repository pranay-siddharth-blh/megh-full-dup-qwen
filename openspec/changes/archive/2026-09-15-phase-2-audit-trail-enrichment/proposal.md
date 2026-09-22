# Phase 2 (carve-out) — Audit Trail Enrichment

## Status
**Implemented (2026-09-12)**, fields sql/result_preview/findings/chart_type
and answer — see `tasks.md` Groups 1-5 for the record. Not yet committed
to git; awaiting the human's review and commit per this repo's standing
process.

## Status (original — retained for history)
Proposed, not yet approved for implementation. Carved out of the two
open questions in `phase-2-orchestration-durability/proposal.md` ("Not
yet decided": *"whether the audit trail... needs to capture
generated/executed SQL text and a longer retention window"*) and
`phase-6-observability-deployment/proposal.md` ("Not yet decided":
storage/retention, and *"audit-log field expansion is coupled to the
Phase 2 durability decision"*). Both sub-questions have now been
answered directly by the user (2026-09-12) — this proposal is the
result. The rest of each stub (LangGraph-or-not, clarification-pause
durability, Kubernetes/rate-limiting) is untouched and still open.

## Why

`docs/baseline-audit.md` §2 row 11.3 and §3 finding classify
Auditability as "Partially implemented — materially narrower" than the
Grant Thornton proposal. Re-verified directly against
`GrantThornton_Solution_Proposal_1 (1).pdf` §11.3 (`pdftotext -layout`,
lines 701-708): the required trace includes the generated SQL, the
executed SQL, a result preview, findings, and the chart spec, in
addition to the ~14 fields already captured. Today's compliance audit
row (`app.query_audit`) has none of the five.

This matters concretely, not just as a spec-compliance gap: the
generated/executed SQL and result rows *are* already captured today —
in `app.conversation_turns.response` (`app/conversation_store.py:55-76`)
— but that table is the user-deletable chat-history table.
`conversation_store.py:246-250` states explicitly that
`app.query_audit` is "deliberately NOT touched [on delete] — it is the
compliance trail." So the one record designed to survive a user
tidying up their own history is exactly the one missing the SQL and
result data an investigation would need. `findings`
(`app/pipeline.py:3400-3405,3434`) and `chart_type`
(`app/pipeline.py:3415-3420,3435`) are missing from both tables today —
not captured anywhere, durable or not.

Storage/retention (JSONL + Postgres, 365-day purge,
`deploy/sql/02_retention_policy.sql:34-38`) vs. the proposal's
ClickHouse/indefinite retention is a **separate, already-resolved**
question: the user has decided (2026-09-12) to keep the current
storage and 365-day window as the permanent, intentional design for
this deployment's actual two-VM scale. No ClickHouse adoption and no
retention-window change are part of this proposal — see Explicitly Out
of Scope.

## What Changes

- `app.query_audit` (`app/appdb.py:128-147`) gains five new nullable
  columns: `sql` (the executed SQL text), `result_preview` (a small,
  capped JSON preview of the result rows — exact cap and shape is a
  task requiring reviewer sign-off, see `tasks.md`), `findings`
  (JSONB, the `findings` list from the pipeline result), `chart_type`
  (text, the hint string from the pipeline result — see naming note
  below), and `answer` (text, the final response text shown to the
  user — added 2026-09-12 after the initial four-field pass missed it;
  it is GT §11.3's "final response" and was already flagged as missing
  in `docs/baseline-audit.md`'s own 11.3 row, same gap pattern as the
  other four: present in `app.conversation_turns.answer`
  (`conversation_store.py:42,64,97,101`), absent from the compliance
  trail).
- `_mirror_audit` (`app/routers/query.py:246-264`) and `_persist_turn`
  (`app/conversation_store.py:30-102`, the INSERT into
  `app.query_audit`) are updated to populate the four new fields from
  the pipeline's `result` dict (`result.get("sql")`,
  a bounded slice of `result.get("data")`, `result.get("findings")`,
  `result.get("chart_type")`).
- The JSONL mirror written by `auth.audit()` (`app/auth.py:313-324`)
  gains the same four fields, so the file-based and Postgres audit
  trails stay in parity (per the existing "belt-and-braces" comment at
  `query.py:247`).
- **Naming correction, not a new capability**: the Grant Thornton text
  says "chart spec," but no chart-spec object exists in this codebase
  — `app/pipeline.py:3435` produces `chart_type`, a hint string
  consumed client-side by `web/ai_query.html`'s `buildAnalytics()`
  (already corrected once before, `docs/baseline-audit.md` §3 finding
  10). This proposal captures the real field, `chart_type`, and notes
  the correction rather than inventing a spec object to match the
  proposal's wording literally.
- `docs/SECURITY.md`'s audit-trail field list (line 111) and
  `docs/baseline-audit.md`'s §2 row 11.3 are updated once the fields
  land, to describe the new state accurately rather than leaving a
  stale field count.
- `docs/baseline-audit.md` §2 row 11.3 and any related storage/retention
  language in `phase-6-observability-deployment/proposal.md` are
  annotated (dated note, house style per §3 items 8-10) to record that
  JSONL+Postgres storage and 365-day retention are now a ratified,
  intentional design decision for this deployment, not an open gap —
  without rewriting either document's history.

**Analyser output, rule-firing trace, retrieved-tables trace, and
join-path trace** (also listed in GT §11.3) are **not** part of this
change — see Explicitly Out of Scope.

## Capabilities

### New Capabilities
- `query-audit-trail`: the compliance-grade audit record persisted per
  query (`app.query_audit` + its JSONL mirror) — what fields it must
  capture, how it relates to the separate, deletable conversation
  history, and its storage/retention posture.

### Modified Capabilities
(none — `openspec/specs/` has no existing capability covering audit
logging; `query-audit-trail` is new)

## Explicitly Out of Scope (deferred)

- **Analyser output, rule-firing trace, retrieved-tables trace,
  join-path trace** — GT §11.3 lists these alongside the fields this
  change adds, but they require a typed intent/retrieval
  representation that doesn't exist yet (see
  `docs/baseline-audit.md` §1 rows 5.2, 5.8, 5.9 and §3 finding 8 on
  why join-path data isn't computed per query today). These remain
  under `phase-2-orchestration-durability`'s broader durability
  decision, not this carve-out.
- **ClickHouse adoption** — explicitly decided against for this
  deployment's scale; JSONL + Postgres stays the permanent audit
  store.
- **Retention window changes** — 365 days stays the default; this
  proposal only documents that as intentional, it does not change the
  value in `deploy/sql/02_retention_policy.sql`.
- **`app.conversation_turns.response`** — already captures `sql` and
  `data` but not `findings`/`chart_type`. Backfilling those two fields
  into the chat-history payload (so a reopened thread can redraw
  findings/chart on refresh) is a real, related gap noticed during
  this proposal's research, but it is a UX/history concern, not a
  compliance-audit concern — flagged here so it isn't silently folded
  into this change or lost; a separate small change can pick it up.
- **Legacy Excel ingestion audit entries** (GT §11.3's closing
  sentence, "legacy ingest runs produce their own audit entries") —
  permanently out of scope per the standing Phase 0 boundary on legacy
  ingestion, CLI, quarantine tables, and backfills.
- **RLS, join-graph hard-gating, and other Phase 1/2/3 items** —
  unrelated to auditability; not touched here.

## Impact

- Affected files: `app/appdb.py` (schema), `app/routers/query.py`
  (`_mirror_audit`), `app/conversation_store.py` (`_persist_turn`),
  `app/auth.py` (`audit()` JSONL write — no signature change expected,
  callers just pass more fields), `docs/SECURITY.md`,
  `docs/baseline-audit.md`,
  `openspec/changes/phase-2-orchestration-durability/proposal.md`,
  `openspec/changes/phase-6-observability-deployment/proposal.md`.
- No API/response-shape change: these fields are written to an
  internal compliance table and log file, not returned from
  `/api/query`. No frontend impact expected — confirm during
  implementation that no admin audit-viewing endpoint
  (`app/routers/admin.py` / `app/appdb.py`'s audit read functions)
  needs its column list or response model updated to surface the new
  fields (or deliberately keep them admin-only/unsurfaced — a decision
  for `tasks.md`).
- Schema change: additive (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`,
  matching the existing idempotent pattern at `app/appdb.py:126`) — no
  backfill of historical rows, no breaking change, independently
  revertible.
- Storage growth: `result_preview` and `findings` add bounded JSONB
  per row; exact size impact depends on the reviewer-approved preview
  cap (see `tasks.md`).

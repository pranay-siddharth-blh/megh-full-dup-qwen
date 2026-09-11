# Phase 2 — Orchestration & Durability Decision (stub)

## Status
Stub — scope statement only, not yet approved for implementation. Derived
from `docs/baseline-audit.md` §1 (nodes 5.2, 5.4) and §3 (finding 3).

## Scope (one paragraph)

Make the explicit, non-foregone-conclusion decision on orchestration that
the original Phase 0 brief deferred: does this codebase adopt LangGraph (as
the proposal specifies for pause/resume, conditional branching, and per-turn
state persistence), or does it formalize and harden the bespoke mechanism
that already exists (`ClarificationNeeded` exception + `Session.pending_scope_q`
/ `pending_village_hint`, `app/pipeline.py`, `app/session_store.py`)? Record
that decision and its tradeoffs in this change's own `design.md` before any
code changes. Whichever way it lands, close the durability gap Phase 0
found: clarification-pause state is currently lost on worker restart or
session-TTL expiry (`session_store.py:104,113`, confirmed not rehydrated by
`conversation_store.load_context_state`). Also decide, as part of the same
durability question, whether the audit trail (`auth.audit()`,
`app/auth.py:313-324`) needs to capture generated/executed SQL text and a
longer retention window to meet the proposal's own Section 2.3 goal of an
audit trail "of every generated query."

## Not yet decided

- LangGraph adoption itself — this is the central open question this phase
  exists to answer, not to assume.
- Whether durability requires a new external dependency (Redis/Postgres
  checkpointer) or can be achieved by extending the existing
  `conversation_store.py` mirroring to also cover pause state.

This stub requires its own approval and design review before work starts.

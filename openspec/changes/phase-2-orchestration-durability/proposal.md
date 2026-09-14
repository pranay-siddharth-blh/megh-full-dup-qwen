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

**Update (2026-09-12):** the audit-trail sub-question in the scope
paragraph above — whether `auth.audit()` needs to capture
generated/executed SQL text — has been decided and carved out into its
own change, `phase-2-audit-trail-enrichment`, which also adds a result
preview, findings, and chart_type. See that change's `proposal.md` for
the full scope. The retention-window question was resolved separately
(365 days, JSONL+Postgres, ratified as intentional — see
`phase-6-observability-deployment`'s corresponding update) and is
**not** part of that carve-out. The rest of this stub — LangGraph
adoption and clarification-pause durability — is unchanged and still
open.

**Update (2026-09-12, later same day):** the remaining LangGraph-vs-
harden decision has now been made — see this change's `design.md`.
**LangGraph is not adopted.** The bespoke `ClarificationNeeded` +
pause-field mechanism is hardened instead: `pending_scope_q`/
`pending_village_hint` moved from bare `Session` attributes onto
`ConversationState` (`app/session_store.py`), which already round-trips
to `app.conversations.context_state` every turn, and
`app/routers/query.py`'s clarification-catch branch now calls
`conversation_store.save_context_state` on the pause path (previously
only the success path did). This closes the durability gap the scope
paragraph above named — a pause no longer loses its resume context on
worker restart, session-TTL expiry, or landing on a different worker.
Implemented and tested (`tests/test_context_manager.py`, sections 11-12)
but **not committed** — awaiting human review/commit per this repo's
standing process. Whether to store the two fields inside the existing
`context_state` JSONB blob versus new typed columns on
`app.conversations`, and whether a stale pending clarification should
expire independently of the conversation row, remain open — see
`design.md`'s "Open Questions for the approver."

## Capabilities

### New Capabilities
- `clarification-pause-durability`: the guarantee that a clarification
  pause (a scope/year/entity-ambiguity question the pipeline must ask
  before it can safely proceed) survives a worker restart, a session-TTL
  eviction, or the next request landing on a different worker process —
  see `specs/clarification-pause-durability/spec.md`.

### Modified Capabilities
(none — `openspec/specs/` has no existing capability covering session or
clarification-pause behavior; `clarification-pause-durability` is new)

**Update (2026-09-13):** by explicit instruction, `app/langgraph_
followup.py` now implements LangGraph's `interrupt()` primitive with a
checkpointer (SQLite, not Redis/Postgres — see `design.md`'s
"Update (2026-09-13)" for why) as a genuine, working, tested component,
separate from and not replacing the hardened bespoke mechanism above.
This does not reverse the "do not adopt LangGraph for this production
deployment" analysis — that reasoning stands and the bespoke mechanism
is still what `app/routers/query.py` actually uses — it answers a
different, explicitly-asked question: build the primitive itself,
infrastructure concerns set aside. See `design.md` for the full record
and `tests/test_langgraph_followup.py` for what's verified.

**Update (2026-09-14):** by explicit instruction, `app/routers/query.py`
now wires `app.langgraph_followup.run_with_pause` into the live request
path, gated behind a new `LANGGRAPH_FOLLOWUP_ENABLED` flag
(`app/config.py`, default `False`) — the human explicitly chose "feature
flag, default OFF" over an unconditional replace when asked. With the
flag off (the shipped default), `/api/query` behavior is unchanged byte
for byte. With it on, the three pause-eligible rules resume via the
LangGraph component instead of the bespoke `pending_scope_q` mechanism.
A real latent bug was found and fixed while wiring this in (not present
in the standalone component in isolation, only once a session could see
a second, later turn): `entity-ambiguous`'s `pending_village_hint` was
never cleared after a successful resume, because `pipeline.py`'s own
clearing is gated on `pending_scope_q` being set — which this component
deliberately never sets. See `design.md`'s "Update (2026-09-14)" and
`app/langgraph_followup.py`'s `_run_pipeline_node` for the fix, and
`tests/test_query_langgraph_wiring.py` for end-to-end coverage (real
HTTP route via `TestClient`, both flag states, the resume, and the leak
regression). **Implemented and tested, not committed** — awaiting human
review/commit per this repo's standing process.

This stub requires its own approval and design review before work starts.

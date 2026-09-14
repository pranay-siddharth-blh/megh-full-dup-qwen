## The decision this document makes

**Recommendation: do not adopt LangGraph. Harden the existing bespoke
mechanism — `ClarificationNeeded` + `Session.pending_scope_q` /
`pending_village_hint` — by extending the durability layer that already
exists for the rest of a session's structured state
(`ConversationState` / `app.conversations.context_state`) to also cover
the two pause fields.**

This is a recommendation for human approval, not a decision already
made — `proposal.md`'s stub is explicit that this needs its own review
before implementation starts, and this repo's standing process
(architecture/product decisions get sign-off before code) applies here
same as it did for `backlog-clarification-rule-engine-migration`.

## Context

Facts below were re-verified directly against the live code for this
document (not taken from `docs/baseline-audit.md` at face value, though
they corroborate it):

- `ClarificationNeeded` (`app/pipeline.py:85-102`) is a plain exception
  carrying `question`, `options`, `rule`, `village_hint`. It is raised
  from ~13 call sites across `pipeline.py`, each a hardcoded predicate
  (`_scope_clarification`, `_year_clarification`, etc.) — there is no
  graph, no node registry, just ordinary Python control flow inside one
  large function.
- The router (`app/routers/query.py:137-180`) catches it. For exactly
  three rules — `scope-not-specified`, `year-not-specified`,
  `entity-ambiguous` — it stashes `req.question` and `e.village_hint`
  onto the in-process `Session` (`session.pending_scope_q`,
  `session.pending_village_hint`, `query.py:144-146`), returns a
  clarification payload, and calls `conversation_store.persist_turn`
  (turn history) but **not** `conversation_store.save_context_state`.
- `Session` (`app/session_store.py:94-123`) is a plain dataclass held in
  `SessionStore`'s in-process `OrderedDict` (`session_store.py:141-147`)
  — TTL-evicted, never written anywhere durable. Its own doc-comment
  states the fields are "Not persisted, per-worker"
  (`session_store.py:104,113`), confirmed correct by reading the class.
- `ConversationState` (`session_store.py:32-63`) is the one piece of
  per-session state that *is* durable today: a "JSON-round-trippable bag
  of scalars/lists" by design, mirrored every turn via
  `conversation_store.save_context_state`/`load_context_state`
  (`conversation_store.py:312-364`) to `app.conversations.context_state`
  (Postgres). `pending_scope_q`/`pending_village_hint` live on `Session`
  directly, not on `ConversationState` — they were never plumbed into
  this existing durability seam.
- The resume path (`pipeline.py:3627-3655`) reads
  `session.pending_scope_q`/`pending_village_hint` off the in-process
  `Session` only. It has no fallback to anything durable.
- The router already has a rehydration hook for exactly this class of
  problem: `if not session.turns and client_session:` (`query.py:98`)
  calls `load_context_state` and restores `session.state`, with a
  comment explicitly naming "a worker restart, a session that TTL'd out
  of session_store, or a request landing on a different worker"
  (`query.py:91-97`) as the scenarios it exists for. It restores
  `context_state`/`summary` only — the pause fields are not part of what
  it rehydrates, because they were never part of what gets saved either.
- **Deployment topology makes "a different worker" a routine event, not
  an edge case.** `deploy/systemd/megh-nlpservice.service` runs
  `uvicorn --workers 2`, with its own comment: "Run this unit on both
  application VMs." That's 4 independent worker processes, none sharing
  memory, sitting behind whatever load-balances between the two VMs. A
  session's *next* request has a real, non-theoretical chance of landing
  on a worker that never held the `Session` object that set the pending
  fields — this is the routine case this deployment runs in, not a rare
  failure mode.
- `redis` is already a dependency (`requirements.txt`) but only backs
  the L2 response/semantic cache (`app/cache.py`) — it is not wired as a
  session/state store anywhere, and nothing here proposes making it one.
- `langgraph` is not a dependency anywhere in `requirements.txt` /
  `requirements.lock` (confirmed directly) and no other phase (0
  through 6) proposal budgets for introducing it.

## Decision: harden, don't adopt LangGraph

**Scale mismatch.** LangGraph's `interrupt()`/checkpointer is built to
durably pause/resume a graph with many nodes, conditional branches, and
per-step checkpointed state. This codebase has exactly one class of
durability gap today: two scalar fields that need to survive a worker
boundary. Adopting a graph-orchestration framework to durably persist
two strings is solving a much narrower problem with much heavier
machinery than it needs.

**Rewrite cost and blast radius.** `pipeline.py` is ~3,600+ lines of
sequential, deeply cross-referenced logic; the audit itself found node
responsibilities (5.2) already "spread across" multiple functions
rather than cleanly modular. Restructuring this into LangGraph
nodes/edges would touch effectively the whole file for a benefit
(durable pause/resume) that a much smaller, additive change already
delivers — see "What hardening means," below.

**No new infrastructure required.** The durable store this needs
already exists and is already called on every turn:
`conversation_store.save_context_state`/`load_context_state` round-trip
`ConversationState` to `app.conversations.context_state` (Postgres,
already provisioned, already in the request path). Extending it by two
more fields is the same additive, minimal-diff pattern already used
successfully in `phase-2-audit-trail-enrichment` (nullable columns,
`ADD COLUMN IF NOT EXISTS`) — not a new dependency, not a new
checkpointer contract, not a new failure mode to operate.

**Consistent with this repo's established precedent.** Every other
piece of the proposal's heavier reference architecture — Kubernetes,
ClickHouse, Langfuse, Prometheus, SQLGlot, NetworkX, pandas — was
deliberately not adopted in favor of lighter mechanisms already in use,
and where that trade-off was revisited explicitly
(`phase-6-observability-deployment`'s retention/storage update) the
heavier option was rejected "for this deployment's two-VM scale." A
2-VM, 4-worker deployment is exactly the scale at which LangGraph's
stated benefits (orchestrating complex multi-agent/service graphs)
don't repay its operational cost — a new dependency family (checkpointer
backend, thread/run identity, graph compilation, its own
state-serialization contract) layered on top of a system that is
otherwise one FastAPI service and one Postgres database.

**Redis is available but not the right home for this either.** Postgres
(via `app.conversations`) is already the durable source of truth for
the rest of a session's structured state, saved on every turn already.
Splitting the pause fields into a second store (Redis) would reintroduce
a parity/drift risk of the same shape `phase-2-audit-trail-enrichment`'s
design explicitly flagged and avoided by keeping one source per field —
better to add two fields to the store that already round-trips this
session's state than open a second one for a subset of it.

## Goals / Non-Goals

**Goals:**
- Make the LangGraph-vs-harden decision explicit and record it here, per
  `proposal.md`'s stub (this document).
- Close the concrete durability gap: a clarification pause must survive
  a worker restart, a session-TTL eviction, or — the routine case at
  this deployment's scale — the next request landing on a different
  worker process than the one that raised it.
- Reuse the existing `ConversationState` / `save_context_state` /
  `load_context_state` seam; no new store, no new dependency.

**Non-Goals:**
- Not rewriting `pipeline.py`'s control flow into a graph/node
  structure, now or as a follow-on of this change.
- Not introducing LangGraph, a checkpointer library, or Redis-as-session-
  store speculatively for future use cases this repo doesn't have yet.
- Not changing `ClarificationNeeded`'s public shape
  (`question`/`options`/`rule`/`village_hint`) or any of the ~13 call
  sites that raise it.
- Not addressing 5.2 (query-analyzer split) or 5.3 (hardcoded vs. YAML
  clarification predicates) — 5.3 already has its own tracked change
  (`backlog-clarification-rule-engine-migration`); this change is scoped
  to 5.4's durability gap only.
- Not enriching what `auth.audit()`/`app.query_audit` capture — that's
  `phase-2-audit-trail-enrichment`, already carved out and separately
  resolved.

## What hardening means, concretely

1. Add `pending_scope_q: str | None` and `pending_village_hint: str |
   None` to `ConversationState` (`session_store.py:32-63`) and its
   `to_dict()`/`from_dict()`, instead of leaving them as bare `Session`
   attributes. This puts them inside the one struct that is already
   JSON-round-trippable and already mirrored every turn.
2. `routers/query.py`'s clarification-catch branch (currently
   `query.py:137-180`, calls `persist_turn` only) must also call
   `conversation_store.save_context_state` with the updated
   `session.state` — mirroring what the success path already does at
   `query.py:233-234`. This is the actual code gap: today only a
   *successful* turn mirrors `context_state`; a *paused* turn does not.
3. The rehydration hook at `query.py:98` (`if not session.turns and
   client_session`) already restores `session.state` from
   `load_context_state` — once the pause fields live inside that same
   blob, this existing call site picks them up for free; no new
   rehydration branch needed.
4. The resume logic (`pipeline.py:3627-3631`) already reads
   `session.pending_scope_q`/`pending_village_hint` — once (1)-(3) land,
   it is reading state that has been correctly rehydrated rather than
   state that only exists if this exact worker happened to hold it.

Whether (1) stores the two fields as new `ConversationState` attributes
(above) or as two new nullable columns on `app.conversations` directly
is an implementation choice for `tasks.md`, not this design — either
satisfies the durability requirement; the `ConversationState` route is
recommended because it needs zero new SQL (the JSONB column and its
read/write path already exist) versus a schema migration for two
rarely-populated columns.

## Risks / Trade-offs

- **["Harden" could quietly grow into a bigger refactor mid-implementation]**
  → Non-Goals above are explicit: this change touches
  `ConversationState`, the two `save_context_state` call sites, and the
  resume read — nothing else in `pipeline.py`. If implementation finds
  it needs more than that, stop and report, per this repo's standing
  re-verify-before-implementing rule, rather than expanding scope
  silently.
- **[A stale pending question resumes after a long gap]** → Already
  possible today whenever `ConversationState` itself survives a gap (it
  has no separate expiry from the conversation row); not a new risk
  introduced by this change, and out of scope to fix here — flagged as
  an open question below instead of quietly deciding it.
- **[Revisiting "no LangGraph" later]** → If a genuinely multi-branch,
  multi-node orchestration need emerges (not just this one durability
  gap), that would be a new decision with its own proposal — this
  document's recommendation is scoped to the problem as it exists today,
  not a permanent ban on ever reconsidering LangGraph.

## Migration Plan

1. Add the two nullable fields to `ConversationState` and its
   `to_dict`/`from_dict` — additive, backward-compatible (`from_dict`
   already defaults every key via `.get(...)`, so old rows with neither
   key present deserialize as `None` with no migration step).
2. Update the clarification-catch branch in `routers/query.py` to call
   `save_context_state` alongside the existing `persist_turn` call.
3. No SQL migration needed if fields live inside the existing
   `context_state` JSONB column (recommended route above). If a reviewer
   prefers typed columns instead, add them via the same additive
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern already used for
   `phase-2-audit-trail-enrichment`.
4. Rollback: reverting the two call-site changes is safe at any point —
   nothing else reads the new fields, so there is no forward dependency
   to unwind.

## Open Questions for the approver

1. Approve "harden, don't adopt LangGraph" as the recorded decision for
   this stub, closing the central open question `proposal.md` posed?
2. Store the two pause fields inside `ConversationState`/`context_state`
   (no schema change) or as two new typed columns on
   `app.conversations` (schema change, more consistent with
   `query_audit`'s typed-column precedent for compliance-shaped data —
   though this is session state, not audit data)?
3. Should a stale pending clarification expire independently of the
   conversation row (e.g. don't resume a pause older than N hours), or
   is inheriting `app.conversations`' existing lifetime acceptable?
4. Does this decision also resolve `proposal.md`'s audit-trail sub-
   question, or does that stay fully carved out to
   `phase-2-audit-trail-enrichment` as its own "Update (2026-09-12)"
   note already states? (This document assumes the latter — no
   audit-trail changes are proposed here.)

## Update (2026-09-13): the "do not adopt LangGraph" recommendation above is superseded, by explicit instruction

The recommendation at the top of this document — reject LangGraph,
harden the bespoke mechanism instead — is **not reversed on its own
merits**. The reasoning above (2-VM/4-worker deployment scale, no other
phase budgeting for the dependency, a two-field durability gap not
needing a graph-orchestration framework) is left exactly as written,
because it was correct for the question it was answering: *should this
production deployment's durability gap be fixed with LangGraph or a
smaller extension of existing infrastructure?* The bespoke hardening
above (`ConversationState.pending_scope_q`/`pending_village_hint`,
`app/routers/query.py`'s `save_context_state` call on the pause path)
remains implemented, tested, and is still the pipeline's actual default
pause/resume path — nothing above is undone.

A **separate, explicit instruction** ("ignore infra just implement the
component please... implement this completely", 2026-09-13) asked for
LangGraph's `interrupt()`/checkpointer to be built anyway, as a
genuine, working implementation of the primitive itself — independent
of whether this production deployment should route real traffic through
it. That is a different question than the one this design answered, so
it is recorded as new work, not a correction to the analysis above:

- New module: `app/langgraph_followup.py` — a `StateGraph` wrapping the
  existing `app.pipeline.answer_question` call for the same three
  pause-eligible `ClarificationNeeded` rules `app/routers/query.py`
  already recognizes (`scope-not-specified`, `year-not-specified`,
  `entity-ambiguous`). A pause calls `interrupt()`; the graph is
  compiled with `langgraph.checkpoint.sqlite.aio.AsyncSqliteSaver` — a
  real, persistent, file-backed checkpointer, not an in-memory
  stand-in, chosen specifically because it needs no server (fitting
  "ignore infra") while still proving genuine durability: each call
  opens its own connection to the same SQLite file, so a pause raised
  by one call and resumed by a later, independent call only share the
  file, never in-process memory — the same property a real separate
  request would have.
- Not Redis/Postgres as the proposal's own "Tools" line names — Redis
  was not attempted (no reason to prefer it over SQLite for a
  same-machine, no-server-required checkpointer); Postgres's official
  LangGraph checkpointer was attempted and **blocked in this
  environment**: `langgraph-checkpoint-postgres` requires `psycopg`,
  whose native `libpq` binding is not installed here (Windows dev
  environment, no PostgreSQL client library) — an infra/environment
  concern, not a design choice, and exactly the kind of thing "ignore
  infra" was about not blocking on. The checkpointer interface is
  pluggable (`compile(checkpointer=...)`); swapping backends later is a
  one-line change in `_build_checkpointer`, not a graph rewrite.
- New dependencies: `langgraph>=1.2,<2.0`, `langgraph-checkpoint-
  sqlite>=3.1,<4.0` (`requirements.txt`/`requirements.lock`, pinned
  versions 1.2.11 / 3.1.1, plus their transitive tree — `langchain-
  core`, `langgraph-checkpoint`, `langgraph-prebuilt`, `langgraph-sdk`,
  `ormsgpack`, `aiosqlite`, `sqlite-vec`, etc.). **Side effect found and
  recorded, not silent**: `langgraph-sdk`'s own constraint downgraded
  `websockets` from 17.1 to 16.1.1 (previously pulled in as a
  `uvicorn[standard]` extra) — re-ran the full regression suite plus a
  direct `app.main` import check after this change; both pass. No other
  existing package's pinned version changed.
- This module is **additive and opt-in**: `app/routers/query.py` was
  NOT changed to call it — the bespoke path above is still what
  production traffic uses. `app/langgraph_followup.run_with_pause` is a
  separately-callable entry point, proven correct in
  `tests/test_langgraph_followup.py` (single pause + durable resume
  across independent checkpointer connections; multi-round pause — "the
  gate is re-evaluated... asks again"; `entity-ambiguous`'s
  `village_hint` threading through via `ConversationState.
  pending_village_hint`; a non-pause-eligible rule propagating rather
  than being swallowed or interrupted). Wiring it into the live request
  path in place of, or alongside, the bespoke mechanism is a further,
  separate decision this update does not make — the instruction asked
  to "implement the component," which this delivers; routing real
  traffic through it is a bigger, riskier change (two parallel
  pause/resume mechanisms, or a cutover from the durability work
  already in production use) that deserves its own explicit ask.

## Update (2026-09-14): wired into `app/routers/query.py`, by explicit instruction, feature-flagged

The "further, separate decision" the paragraph above deferred has now
been made explicitly: asked "implement 5.4," then, when the ambiguity
was surfaced, the human chose (a) wire the component into production
traffic rather than only commit the existing standalone work, and (b) do
so behind a feature flag defaulting off rather than an unconditional
replace of the bespoke mechanism.

**Mechanism.** `app/config.py` gets `LANGGRAPH_FOLLOWUP_ENABLED: bool =
False`, following the exact pattern already used for
`DEFAULTS_ENGINE_ENABLED`/`FINDINGS_ENABLED`/`CHART_SPEC_ENABLED`/
`QUERY_ANALYZER_ENABLED`. In `app/routers/query.py`'s `/api/query`
handler, when the flag is on: `app.langgraph_followup.is_paused
(session_id)` (a new helper, reads the graph's own checkpointer state)
decides whether the incoming message is a fresh question or a reply to
an outstanding pause, then `run_with_pause` is called accordingly. A
`{"paused": True, ...}` result is reshaped into the exact same response
JSON the bespoke path already returns for a pause (`route: "clarification"`,
`needs_clarification`, `clarification.{options,rule}`, `denied_by`, etc.)
and persisted the same way (`persist_turn` + `save_context_state`). A
non-pause-eligible `ClarificationNeeded` that `run_with_pause` propagates
falls through to the pre-existing `except ClarificationNeeded` block
unchanged — safe because that block's `e.rule in (three pause-eligible
rules)` check is structurally always False for anything that can reach
it while the flag is on (a pause-eligible rule under the flag is always
intercepted by the `paused` branch instead, never raised).

**Why the LangGraph-path pause branch deliberately never sets
`session.state.pending_scope_q`.** This was the central risk traced
through before writing any code, not discovered by trial and error:
`pipeline._run_pipeline` (the function `run_with_pause`'s own graph node
calls) unconditionally reads `session.state.pending_scope_q` at its own
top and, if set, runs *its own* bespoke merge of the current `question`
argument into the pending stem — regardless of which mechanism is
calling it, because it's the same shared function either way. If the
`/api/query` handler's LangGraph branch also set `pending_scope_q`
(mirroring what the bespoke `except` block does), then on a resume, the
graph's mandatory interrupt()-replay of `_run_pipeline_node` — which
re-invokes `pipeline.answer_question` with the *original, still-unmerged*
question before the `interrupt()` call site is reached again (see this
document's task 9.2 finding, and `_run_pipeline_node`'s own docstring) —
would hit `_run_pipeline`'s bespoke merge block a second time on that
same still-unmerged text, corrupting the question before the graph's own
merge ever runs. Keeping the two mechanisms' resume signals fully
separate (`pending_scope_q` for the bespoke path; the LangGraph
checkpointer, read via `is_paused`, for this path) avoids that
interference entirely, by construction rather than by testing it away.

**A real bug found while tracing the above, unrelated to the interference
question itself: `entity-ambiguous`'s `pending_village_hint` leaked.**
`_run_pipeline_node` sets `session.state.pending_village_hint` (but not
`pending_scope_q`, by the design above) when pausing on `entity-ambiguous`.
`pipeline.py`'s only code that clears `pending_village_hint`
(`pipeline.py:3727-3729`) is gated inside `if pending:` — i.e. it only
runs when `pending_scope_q` is truthy. Since this component never sets
`pending_scope_q`, that clearing code never ran for it, so
`pending_village_hint` would silently persist and leak into every later
turn on the same session once real, multi-turn production traffic
reached this path — invisible in `tests/test_langgraph_followup.py`
because no check there ever issues a *second, unrelated* turn on the
same session after a resume. Fixed in `_run_pipeline_node`: clear
`session.state.pending_village_hint` immediately after any successful
(non-paused) pipeline call, which is idempotent (a no-op when it was
never set) and mirrors the "consume once, then clear" contract the
bespoke path's own gated clearing already establishes.

**Verification.** `tests/test_langgraph_followup.py` re-run after the
leak fix: still 17/17 (see task 9.1's correction of the earlier "18/18"
miscount). New `tests/test_query_langgraph_wiring.py`: 17/17, exercising
the real HTTP route via `starlette.testclient.TestClient` — flag off
(bespoke, unchanged), flag on (pause without `pending_scope_q`, a
same-session resume via `is_paused`, and the entity-ambiguous leak-fix
regression specifically). Full regression sweep: all 29 `test_*.py`
files, exit 0. `openspec validate --strict`: valid. Not committed —
awaiting human review/commit per this repo's standing process.

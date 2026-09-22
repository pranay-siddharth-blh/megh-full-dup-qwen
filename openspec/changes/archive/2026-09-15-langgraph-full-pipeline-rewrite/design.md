## Context

See `proposal.md` for why this reverses `phase-2-orchestration-
durability/design.md`'s "do not adopt LangGraph" conclusion. This
document assumes that reversal is approved and focuses on how.

Verified current structure (`app/pipeline.py`, re-read directly for this
document, not assumed from `docs/baseline-audit.md`):

- `answer_question` (`pipeline.py:3663`) → `_run_pipeline`
  (`pipeline.py:3706`) → `_answer_data` (`pipeline.py:3382`) is the live
  call chain for the DATA route. `_answer_data` is a single ~280-line
  function that already reads, in order: unsupported-scheme check →
  scheme/topN pre-clarification → `_classify_scheme_detailed` (5.1) →
  `resolve_entities` (5.6, raises `ClarificationNeeded` internally) →
  `clarification_engine.check_clarifications` (5.3) → region/scope/year/
  tranche clarification predicates → `query_analyzer.analyze_query` (5.2)
  → `generate_sql` (5.10) → `execute_with_repair` (5.7/5.9/5.11/5.12,
  `pipeline.py:2756`) → `premise_check`/`defaults_engine` (5.5) →
  `compose_response` (5.15) → `findings.evaluate` (5.13) →
  `chart_spec.select_chart_type` (5.14).
- `execute_with_repair` (`pipeline.py:2756-2967+`) is itself a `for
  attempt in range(max_repairs + 1)` loop containing, per attempt:
  re-authorization (5.7), several deterministic SQL-shape guardrails
  (village-code filter, state-pseudo-filter, row-grain check — none of
  these map to a single Section-5 node individually; they are all part
  of 5.11's "check it against safety and correctness rules"), PII
  blocking (§11.4, unconditional, never repaired), the post-generation
  join validator (5.9's only runtime consumer today), the retrieved-set
  guard (5.11's "tables must belong to the retrieved set"), and finally
  `db.run_readonly` (5.12) with its own `_assert_safe` sqlglot AST check.
  A `ValueError` from any guardrail feeds `build_repair_prompt` and
  regenerates SQL for the next loop iteration; `SQLAuthorizationDenied`
  and the PII/pseudo-scheme clarifications exit immediately, no repair.
- `schemes` is `list[str]` throughout — `classify_scheme` can return more
  than one scheme for a genuinely cross-scheme question. There is no
  per-scheme code path to preserve; state must carry `schemes` as a list
  the way it already does.
- `app/langgraph_followup.py` already proves the mechanics work in this
  codebase: a `StateGraph` wrapping pipeline logic, `interrupt()` for
  pause, `AsyncSqliteSaver` for a working (if production-wrong-shape)
  checkpointer, feature-flagged into `app/routers/query.py` behind
  `LANGGRAPH_FOLLOWUP_ENABLED`. This rewrite reuses that proof, not
  starts from zero.
- Per the answered scoping questions: production checkpointer is
  **Postgres** (new dependency, currently blocked in this dev environment
  by a missing native `libpq`/`psycopg` install — an environment gap to
  resolve before cutover, tracked as its own task, not a reason to ship
  SQLite to production); rollout is **additive/parallel**, matching the
  pattern already used for `langgraph_followup.py`,
  `DEFAULTS_ENGINE_ENABLED`, `FINDINGS_ENABLED`, `CHART_SPEC_ENABLED`;
  nodes 5.8/5.9 are **wrapped as-is** — their current, spec-diverging
  behavior (direct catalog injection, deny-list-only join checking) is
  preserved unchanged inside graph nodes, not upgraded.

## Goals / Non-Goals

**Goals:**
- A `StateGraph` with one node per Section-5 responsibility, wired with
  the same conditional structure (`_answer_data`'s sequential gates,
  `execute_with_repair`'s bounded retry loop) `pipeline.py` already
  implements, running behind a feature flag alongside the existing
  pipeline.
- A Postgres-backed checkpointer proven to survive a worker-to-worker
  handoff and a process restart under the real `deploy/systemd/
  megh-nlpservice.service` 2-VM/4-worker topology (or a documented,
  tested equivalent if live infra access isn't available from this
  environment — see Open Questions).
- `app/langgraph_followup.py`'s node-5.4-only pause/resume is absorbed
  into this graph's own pause handling once proven equivalent, rather
  than left running as a third parallel pause mechanism next to the
  bespoke `ConversationState` fields and this new graph.

**Non-Goals:**
- Not cutting production traffic over to the graph as part of this
  change — additive/parallel only, per the answered rollout question.
  Cutover is a later, separate, explicit decision.
  **Update (2026-09-15)**: that later decision is
  `openspec/changes/multi-tenant-rls-scheme-scaleout` — it adds
  `pipeline_graph.answer_data_via_graph_compat()` and wires
  `PIPELINE_GRAPH_ENABLED` into `app/pipeline.py::_run_pipeline`'s real
  call site (previously the flag was defined and read nowhere). Still
  behind the flag, default `False`, mocked-test-only (no live LLM/DB
  parity check yet — see that change's `design.md` §4a) — this module's
  own "cutover is separate/later" framing is *answered*, not yet fully
  *closed out* (canary rollout, checkpointer backend, and
  `app/langgraph_followup.py` retirement remain open in that change's
  `tasks.md` group 5).
- Not building real vector-based schema retrieval (5.8) or NetworkX join-
  path computation (5.9) — wrapped as-is, per the answered scoping
  question. That remains separately-scoped work if ever taken on.
- Not changing any individual node's externally observable behavior —
  `specs/pipeline-orchestration/spec.md`'s "response contract is
  unchanged" requirement is the hard constraint every node-wrapping task
  must satisfy.
- Not removing the hardened bespoke `ConversationState.pending_scope_q`/
  `pending_village_hint` durability work
  (`phase-2-orchestration-durability`) — that remains the fallback path
  for as long as this graph is flagged off, and callers on that path are
  unaffected by anything in this change.

## Decisions

**Graph shape: 15 nodes matching Section 5's own numbering, not a finer
or coarser decomposition.** `execute_with_repair`'s several inline
guardrails (village-code filter, pseudo-scheme filter, row-grain check,
retrieved-set guard) all belong under one 5.11 "SQL validation" node —
they are exactly the "safety and correctness rules" the original GT
spec's own 5.11 description names, not separate nodes, because none of
them has an independent identity in the Section 5 spec this whole effort
maps to. Alternative considered: one graph node per guardrail function
for finer-grained observability — rejected because it invents node
boundaries the spec doesn't have, complicating the state schema for no
behavioral benefit; per-guardrail detail can still be logged from inside
the 5.11 node without being a separate graph node.

**State schema: one `TypedDict` carrying every field currently threaded
as function arguments/return values through `_answer_data`/
`execute_with_repair`** (`question`, `schemes`, `scope_trace`,
`entity_result`, `analysis`, `sql`, `rows`, `notes`, `attempt_count`,
`answer`, `result_findings`, `result_chart_type`, plus the `auth.UserScope`
and session-derived pause fields). Alternative considered: a leaner state
object with node-local scratch state kept out of the graph — rejected
because LangGraph's checkpointer can only durably resume what's in graph
state; anything kept node-local disappears on a checkpoint replay, which
is exactly the class of bug `phase-2-orchestration-durability/design.md`'s
"Update (2026-09-14)" section already found once (the `pending_village_hint`
leak) when state placement wasn't traced carefully up front.

**Repair loop as a conditional self-edge on the 5.11 validation node,
capped by a counter in state, not a Python `for` loop inside the node.**
This makes the one-repair-attempt limit (`phase-1-security-hardening`)
a graph-visible, checkpoint-durable property — a paused-and-resumed
request mid-repair doesn't lose its attempt count — rather than a
loop-local variable that only exists for the lifetime of one node
invocation.

**Authorization runs as its own node, re-entered on every path back from
a repair edge**, not folded into the validation node — `proposal.md`'s
Impact section and `specs/pipeline-orchestration/spec.md`'s
re-authorization requirement both treat this as independently important
(it is `phase-1-security-hardening`'s Item 2, a previously-real
vulnerability), so it stays a distinct, independently testable node
rather than a step buried inside a larger one.

**Checkpointer: `langgraph-checkpoint-postgres`, reusing the application's
existing Postgres instance** (`app.conversations` already lives there),
not a separate database. Alternative considered: keep SQLite but on
shared/networked storage reachable from both VMs — rejected as a worse
version of "just use Postgres," adding a networked-filesystem failure
mode for no benefit over a database this deployment already runs and
already trusts for session durability.

**`app/langgraph_followup.py` is not deleted in this change** — it stays
as the production pause/resume path (flagged, as today) until this
graph's own pause handling is verified equivalent via the test parity
work in `tasks.md`, at which point removing it is a follow-up task, not
part of this change's exit criteria (removing a still-in-use production
path is exactly the kind of scope creep `phase-2-orchestration-
durability/design.md`'s own Risks section warned against).

## Risks / Trade-offs

- **[Postgres checkpointer setup is blocked in this dev environment]** →
  `psycopg`'s native `libpq` dependency isn't installed on this Windows
  dev machine (confirmed directly: `langgraph_followup.py`'s own design
  notes record the same blocker when Postgres was attempted for that
  component). Mitigation: build and test the graph's node structure
  against the already-working SQLite checkpointer first (same backend
  `langgraph_followup.py` already proves out), swap to
  `langgraph-checkpoint-postgres` via the pluggable `compile
  (checkpointer=...)` interface as a late, isolated task once `libpq` is
  available — either in this environment or verified in a CI/staging
  environment that has it. This does not block most of the
  implementation.
- **[Decomposing a 4,000-line, deeply cross-referenced file risks
  silently changing behavior]** → `_answer_data`'s guardrails and
  clarification predicates rely on specific ordering (e.g. §5.3's
  cannot-answer check is deliberately ahead of scope/year/tranche asks;
  PII blocking is deliberately ahead of the paid semantic verifier and
  the join validator in `execute_with_repair`, moved there 2026-09-12
  specifically to save cost). Mitigation: `tasks.md` must preserve every
  documented ordering constraint explicitly, node-by-node, and the parity
  test suite (see spec's "response contract is unchanged" requirement)
  must run the same fixture questions through both the old and new paths
  and diff the full response, not just spot-check.
- **[Two production-facing durability mechanisms coexist during rollout]**
  → the bespoke `ConversationState` pause fields and this new graph's
  checkpointer both exist simultaneously while the graph is flagged off.
  Mitigation: this is the same additive pattern `langgraph_followup.py`
  already runs today without incident (feature-flagged, never both
  active for the same request), not a new risk shape.
- **[Blast radius grows if 5.8/5.9's "wrap as-is" boundary leaks]** → it
  would be easy, while touching schema-retrieval/join-discovery call
  sites to wire them into graph nodes, to also "just fix" their known
  gaps. Mitigation: `tasks.md` must scope those two nodes as pure
  call-site wrapping with an explicit test asserting output is identical
  to the pre-graph call, per the answered scoping decision.

## Migration Plan

1. Add `langgraph`'s `StateGraph`/state-schema scaffolding in a new
   module (e.g. `app/pipeline_graph.py`), starting from the state schema
   decision above — no behavior yet, just the typed state and an empty
   graph that can be compiled.
2. Port nodes in dependency order, each with a parity test against the
   existing function it wraps before moving to the next: 5.1 → 5.6 → 5.3
   → 5.2 → 5.5 (the pre-`execute_with_repair` chain in `_answer_data`),
   then 5.7 → 5.8 → 5.9 → 5.10 → 5.11 → 5.12 (the `execute_with_repair`
   loop, including the conditional repair edge and the counter-based
   attempt cap), then 5.13 → 5.14 → 5.15.
3. Wire node 5.4's pause/resume using the same `interrupt()` pattern
   `langgraph_followup.py` already proves, now scoped to the specific
   node that raises it rather than the whole graph being one opaque node.
4. Build against the SQLite checkpointer first (per the risk above);
   swap in the Postgres checkpointer as an isolated, late task once the
   environment blocker is resolved.
5. Full-fixture parity sweep: every existing `test_*.py` fixture question,
   across all four schemes, run through both `pipeline.answer_question`
   and the new graph's entry point, asserting identical responses.
6. Land behind a new flag (e.g. `PIPELINE_GRAPH_ENABLED`, default
   `False`), following the exact established pattern — no router changes
   to the default request path. Cutover is explicitly out of scope for
   this change's exit criteria.
7. Rollback: reverting is deleting the new module and flag — the existing
   pipeline is never modified in place by this change, only wrapped.

## Open Questions

- Live verification that the Postgres checkpointer actually survives a
  request landing on a different one of the 2 VMs / 4 workers requires
  access to that real topology (or a faithful multi-process local
  simulation) — this environment could not confirm that end-to-end
  before implementation starts, only that the checkpointer library
  itself is designed for exactly this case. Flagged for verification
  during implementation, not blocking the start of node-porting work
  since it only affects the checkpointer-swap task (Migration Plan step
  4), not the graph's structure.
- Whether `app/langgraph_followup.py` is deleted once this graph's node
  5.4 handling is proven equivalent, or kept as a reference/fallback
  indefinitely, is left for whoever reviews the parity results — not a
  decision this document needs to make now, since either answer changes
  no code in this change itself.

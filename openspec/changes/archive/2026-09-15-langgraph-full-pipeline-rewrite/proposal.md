## Why

The Grant Thornton proposal's Section 5 describes 15 pipeline nodes
(5.1 scope/scheme classifier through 5.15 response composer) orchestrated
as a LangGraph graph. What exists today (`app/pipeline.py`, ~4,000 lines)
implements the same 15 responsibilities as plain, deeply cross-referenced
Python function calls inside `_answer_data`/`execute_with_repair` — no
`StateGraph`, no per-node edges, no graph-level checkpointing. A real
LangGraph component does exist (`app/langgraph_followup.py`), but it
wraps the *entire* pipeline as one opaque graph node solely to durably
persist node 5.4's pause/resume fields — it does not decompose 5.1–5.15,
and is feature-flagged off in production.

`openspec/changes/phase-2-orchestration-durability/design.md` already
recorded an explicit decision **against** this: "do not adopt LangGraph
[for the pipeline's control flow] ... Not rewriting `pipeline.py`'s
control flow into a graph/node structure, now or as a follow-on of this
change." That decision was correct for the question it answered (a
two-field durability gap did not justify a full graph rewrite at this
deployment's 2-VM/4-worker scale) and remains correct on its own terms —
this proposal does not dispute that reasoning. It reverses the decision's
*conclusion* by explicit instruction: the requirement now is a genuine,
node-decomposed LangGraph pipeline covering all 15 nodes, running
identically across all four schemes this system serves (MGNREGA, PMAY-G,
Focus Plus, CM Elevate), not a narrower durability fix.

Why now: this is a deliberate, human-approved scope expansion, made with
the prior decision's trade-offs already on the table (see "Risks" in
`design.md`) — not a discovery that the prior analysis was wrong.

## What Changes

- Decompose `_answer_data`/`execute_with_repair`'s current linear control
  flow (`app/pipeline.py`) into a `langgraph.graph.StateGraph` with one
  node per Section 5 responsibility (5.1 scope/scheme classification,
  5.2 query analysis, 5.3 clarification gate, 5.4 follow-up/pause,
  5.5 defaults, 5.6 entity resolution, 5.7 authorization, 5.8 schema
  retrieval, 5.9 join discovery, 5.10 SQL generation, 5.11 SQL
  validation, 5.12 execution, 5.13 result findings, 5.14 chart
  generation, 5.15 response composition), connected by conditional edges
  for the existing pause/clarify branches, the repair loop (capped at 1
  attempt, per `phase-1-security-hardening`), and the auth-denial/PII-
  denial short-circuits.
- One parameterized graph, not four per-scheme graphs: `schemes: list[str]`
  is graph state, matching `classify_scheme`'s existing contract (a
  question can resolve to more than one scheme). Scheme-specific
  behavior (FK YAMLs, default rules, clarification predicates, findings
  thresholds) stays data-driven exactly as it is today — the graph
  structure does not fork per scheme.
- A durable checkpointer backs every node transition (not just node 5.4's
  two pause fields) — checkpointer backend is a design decision, not
  fixed here (see `design.md`; the existing SQLite checkpointer was
  chosen for `langgraph_followup.py` only because of a local Windows-dev
  `psycopg`/`libpq` blocker, not because SQLite is the intended
  production backend).
- `app/langgraph_followup.py`'s existing narrow interrupt/checkpointer
  work is superseded/absorbed by this graph's own pause handling for
  node 5.4, not left running as a third parallel pause mechanism
  alongside the bespoke `ConversationState` fields and this new graph.
- Feature-flagged, additive rollout: the existing `pipeline.answer_question`
  entry point and its behavior (numeric-faithfulness guard, PII
  redaction, auth re-checks, the exact response dict shape) are the
  behavioral contract the graph must reproduce — this is a change to
  *how* the 15 nodes execute, not to what any of them individually does
  or returns. Existing capability specs (`chart-spec`, `defaults-engine`,
  `result-findings`, `query-analyzer`, `join-discovery`, `schema-retrieval`,
  `clarification-rule-matcher`, `scope-decision-trace`) are not expected
  to change requirements — `design.md` must confirm this holds once the
  graph exists, not assume it.

## Capabilities

### New Capabilities
- `pipeline-orchestration`: the LangGraph `StateGraph` structure itself —
  node boundaries matching Section 5's 15 nodes, the state schema threaded
  between them, conditional edges for clarification pause/resume, the
  repair loop, auth/PII short-circuits, checkpointer-backed durability
  across all four schemes, and the contract that this substrate change
  preserves every existing node's externally observable behavior.

### Modified Capabilities
(none expected — this is a change to execution substrate, not to any
individual node's requirements. `design.md` and `tasks.md` must verify
this holds for each of the 8 existing capability specs rather than assume
it; if implementation finds a capability's behavior cannot be preserved
unchanged inside a graph node, that becomes a real modified-capability
delta at that point, reported rather than silently absorbed.)

## Impact

- **`app/pipeline.py`** (~4,000 lines) — the primary rewrite target;
  `_answer_data`, `execute_with_repair`, `generate_sql`, `_verify_sql`,
  `compose_response`, `classify_intent`, `resolve_entities`, and the
  ~13 `ClarificationNeeded`-raising predicates become graph nodes/edges.
- **`app/langgraph_followup.py`** — superseded by this graph's own node
  5.4 handling; retained only if `design.md` finds a reason to keep it
  standalone, otherwise removed once the new graph's pause/resume is
  verified equivalent.
- **`app/routers/query.py`** — the `/api/query` handler's pause-catch,
  resume, and rehydration logic changes from catching `ClarificationNeeded`
  around a plain function call to invoking/resuming a compiled graph.
- **`app/session_store.py` / `app/conversation_store.py`** — durable
  session state currently split across `ConversationState`/Postgres and
  (for the standalone component) SQLite must reconcile to one durability
  story for the graph's checkpointer.
- **Dependencies** — `langgraph`, `langgraph-checkpoint-sqlite` are
  already present (`requirements.txt`/`requirements.lock`); a production
  checkpointer backend (Postgres, per the original GT proposal's "Tools"
  line) is a new dependency (`langgraph-checkpoint-postgres` + `psycopg`)
  currently blocked in the Windows dev environment (`libpq` not
  installed) — an environment gap `design.md` must address before this
  can ship to production, not a reason to default to SQLite there.
- **Tests** — all 29+ existing `test_*.py` files exercise `pipeline.py`'s
  current call shape; a full regression sweep plus new graph-specific
  tests (per-node isolation, conditional-edge coverage, checkpointer
  resume across a simulated worker boundary, and parity tests across all
  four schemes) are required before cutover, not just before merge.
- **Deployment** — `deploy/systemd/megh-nlpservice.service` runs 2 VMs ×
  2 uvicorn workers; a graph checkpointer must work correctly under that
  exact multi-worker topology (the same scale `phase-2-orchestration-
  durability/design.md` found problematic for a lighter mechanism) —
  `design.md` must show this is handled, not assumed.

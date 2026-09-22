# Working context for Claude Code sessions in this repo

This file exists so a fresh session doesn't have to re-derive the state
below from scratch. Read it before touching git state or `openspec/` — see
"Git state" below for files with layered, unrelated concerns in their
current diff.

## What this project is

FastAPI service answering questions about Meghalaya's MGNREGA / PMAY-G /
Focus Plus / CM Elevate government schemes: a DATA route (NL → SQL →
answer over curated Postgres), a RAG route (scheme-knowledge questions
over a pgvector KB), and an edge route (canned replies, no model call).
See `README.md` for the architecture and `docs/baseline-audit.md` for a
node-by-node audit of what the original Grant Thornton proposal
(`GrantThornton_Solution_Proposal_1 (1).pdf`, repo root) asked for vs. what
actually exists in code.

## Planning source of truth: `openspec/`

Work is tracked as OpenSpec changes under `openspec/changes/`, each with a
`proposal.md` (+ `tasks.md`, `specs/` deltas where implementation has
started). **Read the relevant change's `proposal.md` and `specs/` before
touching its area of code** — several proposals document non-obvious
findings from re-verifying the codebase (not just restating the original
audit), and re-deriving them from scratch wastes a pass.

**Rewritten 2026-09-18 — everything below this line through "Git state" was
dated 2026-09-11 and had gone badly stale** (referenced half a dozen
proposals that are now archived, and predated the entire
`multi-tenant-rls-scheme-scaleout` change, 4 more real commits, and this
session's uncommitted work). Rather than re-date the same drift-prone
snapshot pattern, this section now points at live commands instead of
hand-maintained lists — **run `openspec list` for current change status,
it will always be fresher than anything written here.**

As of this writing, `openspec list` shows exactly two non-archived changes:
- **`multi-tenant-rls-scheme-scaleout/`** (38/41 tasks) — tenant↔scheme
  entitlement model, Postgres RLS (curated fact tables + the app's own
  bookkeeping tables — a real second layer, not just app-level checks),
  the LangGraph production cutover (`PIPELINE_GRAPH_ENABLED` wired for
  real, canary rollout via `PIPELINE_GRAPH_CANARY_PERCENT`, real
  cross-HTTP-request resume via the graph's own checkpointer), and scheme
  onboarding scale-out (proven to need zero code changes for a 5th
  scheme). **Remaining 3 tasks are all genuinely blocked, not just
  unstarted** — see `tasks.md` for the exact items: two need the
  production DB-role cutover (see [[project-db-role-cutover-blocked]] if
  that memory exists — infra/ops action, not code), one needs live-LLM +
  live-Postgres parity testing across all 4 schemes (deliberately not
  attempted from this environment without explicit sign-off each time).
- **`phase-1-security-hardening/`** — 2 of 3 items done and committed; the
  third is the same DB-role cutover blocker above.

Everything else that predates this rewrite is archived under
`openspec/changes/archive/` (22 changes as of this writing — run `ls
openspec/changes/archive/` for the current, exact list rather than trusting
one hand-typed here) — implemented, tested, and (per each archived change's
own tasks.md) done. Notably includes `langgraph-full-pipeline-rewrite`
(the full 15-node `pipeline_graph.py` StateGraph this repo's LangGraph
cutover is built on), `phase-4-clarification-defaults-charts`,
`phase-2-orchestration-durability` (the narrower `langgraph_followup.py`
component), `phase-2-audit-trail-enrichment`, `phase-6-observability-
deployment`, `schema-retrieval-reranking`, `sql-generation-vector-fewshot`,
`entity-resolver-semantic-fallback`, `join-graph-post-generation-validation`,
`rag-knowledge-base-verification`, `findings-surface-to-user`, and both
`urgent-pii-redaction` changes. `docs/baseline-audit.md` cross-references
the Grant Thornton proposal node-by-node against all of this and is kept
current — re-verify against it rather than assuming any single change's
proposal.md alone tells the whole story for that node.

## Git state (check `git log`/`git status` — this rots fast, don't trust a
## number written here)

As of this rewrite: `git log` shows the working tree is 7 commits ahead of
`origin/main`, most recent `5bdf3d7` ("§5.4 Follow-up emitter: durable
bespoke pause + LangGraph interrupt() component"). The working tree then
has a large uncommitted diff on top of that (roughly 150 changed paths as
of this writing — don't trust that number either, run `git status`) built
up across the multi-tenant-rls-scheme-scaleout work and everything
archived alongside it. **Per this repo's standing process, none of it has
been committed — the human commits, not a coding session** (see any
change's tasks.md, which all end with the same "no commit, report and
stop" convention). Before touching or committing any file, run
`git diff <path>` yourself rather than trusting a description here —
several files (`app/config.py`, `app/pipeline.py`, `app/auth.py`,
`app/main.py` among them) have accumulated layered, unrelated concerns
across many sessions' worth of work, and any hand-maintained list of which
file has which concerns goes stale the moment the next session touches
one of them — which is exactly what made the version of this section
before this rewrite useless.

## Tooling scaffolding — not project code

`.claude/commands/opsx/*.md` and `.claude/skills/openspec-*/SKILL.md` are
auto-generated by the OpenSpec CLI — not hand-authored, not related to any
feature work above.

## Test convention

No pytest. Every `tests/test_*.py` is a standalone script: sets env vars,
imports `app.*` directly, uses a local `check(name, cond, detail)` helper,
exits 1 on any failure. Run individually: `python tests/test_X.py`. As of
this writing there are 42 files; run the full sweep with a simple shell
loop over `tests/*.py` (excluding `smoke_restructure.py`, which needs a
live running server) rather than trusting any hand-picked subset list —
several files here (`test_pipeline_graph_postgres.py`,
`test_admin_schemes_live_db.py`) also skip cleanly to exit 0 when no live
Postgres DSN is configured via their own env var, so they're safe to
always include. Two feature flags materially change pipeline behavior
enough to warrant re-running the full sweep with them on, not just at
default: `PIPELINE_GRAPH_ENABLED` and `LANGGRAPH_FOLLOWUP_ENABLED` (plus
`TENANT_SCHEME_RLS_ENABLED` for anything touching auth/DB access) — the
standing convention across recent changes is to run the full sweep at
default flags AND with all three on simultaneously, not just one or the
other.

# Meghalaya NL Assistant — MGNREGA, PMAY-G, Focus Plus, CM Elevate

One FastAPI service (`app/`) that answers natural-language questions about
Meghalaya's **MGNREGA**, **PMAY-G**, **Focus Plus** and **CM Elevate**
scheme data (`config/scheme_registry.yaml` is the source of truth for the active
scheme list — a 5th scheme has already been proven to onboard with zero
code changes, see `docs/scheme-onboarding.md`):

- **Data questions** → generates a read-only SQL query against the curated
  `megh_db` star schema, runs it, and composes a short answer.
- **Scheme-knowledge questions** ("who is eligible for PMAY-G?", "what documents
  are required?") → retrieves from a Postgres/pgvector knowledge base built
  from the `data/` reference docs, reranks, and answers from the passages.
- **Edge input** (greetings, "who are you", off-topic) → an instant canned reply,
  no model call.

Scheme selection (one, several, or all four) happens **inside the pipeline**,
not in the URL. The three former per-scheme services (`unified-data`,
`cm-elevate`, `focus`) and the gateway have been removed.

All model inference is remote — the service calls a self-hosted OpenAI-compatible
Qwen gateway and does no local inference.

## Layout

```
meghalaya/
├── app/                          the FastAPI service (package `app`)
│   ├── main.py                   app + lifespan (pool, model client, pgvector, KB ingest,
│   │                             scheme registry / join-graph load, RLS entitlement sync)
│   ├── api/                      HTTP layer
│   │   ├── deps.py               request identity, role gates, RLS tenant-context wiring
│   │   ├── routers/              /api/query, /api/auth, /api/history, /api/rag, /admin
│   │   └── middleware/           security headers/CSP, body-size limit, per-user/IP rate limit
│   ├── core/                     cross-cutting concerns
│   │   ├── config.py             settings (pydantic-settings, reads .env)
│   │   ├── security.py           HS256 JWT + pbkdf2_sha256 password hashing
│   │   ├── auth.py               role/geography/granularity checks + audit
│   │   ├── net.py                client-IP resolution with proxy trust (XFF)
│   │   └── pii_guard.py          §11.4 two-layer PII protection (pre-execution SQL-text
│   │                             blocklist scan + unconditional post-execution row redaction)
│   ├── database/                 Postgres access
│   │   ├── db.py                 asyncpg pool; read-only SQL guard (sqlglot AST, not regex);
│   │   │                         tenant-context GUCs for curated-data RLS when enabled
│   │   ├── appdb.py              app.* schema (users, tenants, conversations, audit,
│   │   │                         schemes/tenant_schemes entitlements)
│   │   └── vectorstore.py        pgvector (Postgres) pool + helpers
│   ├── clients/                  model clients
│   │   ├── llm.py                one httpx client; classify / SQL-gen / compose / embed / rerank / ASR
│   │   └── local_embed.py        local CPU embeddings (fastembed) when EMBEDDING_PROVIDER=local
│   ├── caching/                  cache.py (exact-match response cache + metrics),
│   │                             semantic_cache.py (near-duplicate response cache)
│   ├── conversation/             session_store.py, conversation_store.py (chat history +
│   │                             query audit persistence), conversation_memory.py,
│   │                             context_manager.py (multi-turn context layer)
│   ├── orchestration/            the pipeline itself
│   │   ├── pipeline.py           Edge → intent → {SQL path | RAG path}; also the
│   │   │                         PIPELINE_GRAPH_ENABLED cutover point to pipeline_graph.py
│   │   ├── pipeline_graph.py     the §5.1-5.15 DATA route as a real LangGraph StateGraph
│   │   │                         (node-decomposed, checkpointed pause/resume)
│   │   └── langgraph_followup.py narrower LangGraph interrupt()/checkpointer component for
│   │                             §5.4 — LANGGRAPH_FOLLOWUP_ENABLED, mutually exclusive with the above
│   ├── nlu/                      understanding the question
│   │   ├── edge.py               regex edge-case handler (no model call)
│   │   ├── query_analyzer.py     §5.2 structured query-analysis object
│   │   ├── entity_resolver.py    district / block / year / village resolution (+ embedding
│   │   │                         fallback for the closed-set catalogues)
│   │   ├── clarification_engine.py  YAML-driven clarification rule matcher (§5.3)
│   │   ├── defaults_engine.py    §5.5 silent, disclosed defaults for unspecified details
│   │   └── premise_check.py      catches a false numeric premise in a DATA question
│   ├── sql/                      SQL generation + validation
│   │   ├── prompt_builder.py     the single place the SQL-generation prompt is built
│   │   ├── schema_context.py     in-prompt condensation of the data model, per scheme
│   │   ├── schema_introspect.py  live semantic.* catalog reader
│   │   ├── schema_retrieval.py   §5.8 scheme-filtered pgvector retrieval over schema docs
│   │   ├── sql_examples_retrieval.py  §5.10 vector-retrieved SQL few-shot examples
│   │   ├── join_graph.py         §5.9 join-path lookup from the curated FK graph
│   │   ├── fk_miner.py           mines implicit FK candidates from query history
│   │   ├── sql_join_validator.py post-generation AST check: flags an invented join
│   │   └── dedup.py              swaps duplicate-holding views for de-duplicated versions
│   ├── knowledge/                scheme knowledge + RAG
│   │   ├── scheme_registry.py    config/scheme_registry.yaml loader + app.schemes sync
│   │   ├── annotations.py        loads few-shot + FK YAML from data/
│   │   ├── rag.py                embed → pgvector search → rerank → answer
│   │   ├── kb_ingest.py          chunk data/**/*.md → embed → upsert to pgvector
│   │   ├── schema_metadata_ingest.py  indexes schema descriptions for schema_retrieval
│   │   └── sql_examples_ingest.py     indexes few-shot SQL for sql_examples_retrieval
│   └── response/                 answer presentation
│       ├── answer_format.py      Markdown answer formatting
│       ├── findings.py           §5.13 deterministic findings over a query's own rows
│       ├── chart_spec.py         §5.14 deterministic chart-type selection
│       └── followups.py          deterministic "Next steps" suggestions
├── config/                       runtime configuration files
│   ├── scheme_registry.yaml      source of truth for the active scheme list
│   └── users.yaml                one-time seed for app.users (USERS_FILE)
├── web/                          served UI
│   ├── ai_query.html             chat console          (/ai-query)
│   └── admin.html                admin console         (/admin-ui)
├── data/                         SME-curated inputs, read at startup
│   ├── mgnrega/ pmay/ focus_plus/ cm_elevate/   per-scheme few-shot, FK, entity-resolver,
│   │                             clarification/default rules, schema-metadata YAML
│   ├── reference/                scheme reference + FAQ docs, KPI workbooks
│   ├── schema/                   schema_for_developers.md
│   └── web/                      scraped background docs (KB source)
├── tests/                        standalone exit-code scripts — not pytest, see
│   │                             CLAUDE.md's "Test convention" section
│   ├── unit/                     run everywhere (no live services needed)
│   ├── integration/              need a live Postgres; skip cleanly (exit 0) without one
│   └── smoke/                    need a live running server — never run in CI
├── docs/                         ARCHITECTURE.md · DATA_MODEL.md · SECURITY.md ·
│   │                             INFERENCE_REQUIREMENTS.md · scheme-onboarding.md ·
│   │                             baseline-audit.md (node-by-node GT-proposal coverage)
│   └── reference/                GrantThornton_Solution_Proposal_1 (1).pdf
├── deploy/                       nginx conf, systemd unit, DEPLOYMENT.md, and
│                                 deploy/sql/ (role/RLS/retention migration scripts)
├── openspec/                     planning source of truth — run `openspec list`
│   ├── changes/                  active change proposals (archive/ = completed)
│   └── specs/                    capability specs synced from archived changes
├── certs/                        internal CA bundle          (gitignored)
├── logs/                         audit JSONL, LangGraph checkpoints, uvicorn out (gitignored)
├── Dockerfile · docker-compose.yml · bitbucket-pipelines.yml
├── requirements.txt · requirements.lock
├── .env                          secrets (gitignored)
└── .env.example
```

Run a single test: `python tests/unit/test_security.py`. Run the sweep the way CI
does: `for t in tests/unit/test_*.py tests/integration/test_*.py; do python "$t" || echo "FAIL $t"; done`.

## Running

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then fill in DATABASE_URL, VECTOR_DB_URL + the model API keys
uvicorn app.main:app --host 0.0.0.0 --port 8300
```

Run from the repository root — `.env` is read relative to the working directory.

- Portal:  <http://127.0.0.1:8300/>
- Chat console:  <http://127.0.0.1:8300/ai-query>
- Health:  <http://127.0.0.1:8300/health>

| Route | Purpose |
| --- | --- |
| `POST /api/query` | `{question}` → `{route, answer, sql, rows, data, findings, chart_type, …}` |
| `POST /api/query/transcribe` | multipart `file` (audio) → `{text}` (qwen3-asr) |
| `POST /api/auth/login`, `/logout`, `GET /me`, `POST /bootstrap` | HS256 JWT auth; `/bootstrap` creates the first `super_admin` |
| `GET/PATCH/DELETE /api/history[/{session_id}]`, `POST .../pin`, `.../archive` | durable per-user conversation history |
| `GET /api/rag/status` | pgvector KB table row count |
| `POST /api/rag/reingest` | rebuild the scheme-knowledge KB from `data/` |
| `POST /api/rag/reingest-schema-metadata` | rebuild the §5.8 schema-retrieval collection |
| `POST /api/rag/reingest-sql-examples` | rebuild the §5.10 SQL few-shot collection |
| `POST /api/rag/reload-scheme-registry` | reload `scheme_registry.yaml` + sync `app.schemes` without a redeploy |
| `GET /admin/schemes`, `.../tenants`, `.../users`, `.../roles`, `.../logins` | tenant/scheme/user administration (admin/super_admin-gated) |
| `POST/DELETE /admin/tenants/{id}/schemes/{scheme_id}` | grant/revoke a tenant's scheme entitlement |
| `POST /admin/reload-join-graph` | rebuild the FK join graph without a redeploy |
| `GET /health` | `ok` / `degraded` with the failing component named |

Not an exhaustive list — see `app/api/routers/` for the current, exact route set.

The scheme KB is ingested into pgvector on startup (idempotent — skipped when the
table is already populated). Force a rebuild with `POST /api/rag/reingest`.

## Deploy

Two application VMs behind the ESDS vFirewall; run nginx + the systemd unit on
each. See `docs/ARCHITECTURE.md` for the full infrastructure map and
capacity budget (20–40 concurrent, 100–200 DAU), and `docs/SECURITY.md` for the
OWASP Top 10 control map (app-layer hardening + nginx/ModSecurity CRS edge) and
the go-live security checklist.

## Models (self-hosted Qwen gateway, `10.48.242.4`)

| Role | Model |
| --- | --- |
| Scheme/intent classify, SQL semantic verify | `qwen4-deploy` |
| SQL generation | `qwen-model` (qwen3-coder-30b-fp8) |
| Answer composition | `qwen35-9b` |
| KB/schema/SQL-example embeddings | `qwen3-embedding` (falls back to a local ONNX model, `BAAI/bge-small-en-v1.5`, when `EMBEDDING_PROVIDER=local`) |
| KB/schema reranking (off by default — see `docs/baseline-audit.md` §5.8) | `qwen3-reranker` |
| Voice input | `qwen3-asr` |

Exact current model names/roles live in `app/core/config.py` (`*_MODEL`
settings) — this table can drift from that file; treat `app/core/config.py` as
the source of truth if the two ever disagree.

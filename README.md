# Meghalaya NL Assistant — MGNREGA, PMAY-G, Focus Plus, CM Elevate

One FastAPI service (`app/`) that answers natural-language questions about
Meghalaya's **MGNREGA**, **PMAY-G**, **Focus Plus** and **CM Elevate**
scheme data (`scheme_registry.yaml` is the source of truth for the active
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
├── app/                       the FastAPI service (package `app`) — grown a
│   │                          lot since this list was last accurate; run
│   │                          `ls app/` for the current exact file set
│   │                          rather than trusting this list alone
│   ├── main.py                app + lifespan (pool, model client, pgvector, KB ingest,
│   │                          scheme registry / join-graph load, RLS entitlement sync)
│   ├── pipeline.py            Edge → intent → {SQL path | RAG path}; also the
│   │                          PIPELINE_GRAPH_ENABLED cutover point to pipeline_graph.py
│   ├── pipeline_graph.py      the §5.1-5.15 DATA route as a real LangGraph StateGraph
│   │                          (node-decomposed, checkpointed pause/resume) — behind
│   │                          settings.PIPELINE_GRAPH_ENABLED, see docs/baseline-audit.md
│   ├── langgraph_followup.py  a narrower, separate LangGraph interrupt()/checkpointer
│   │                          component for §5.4 specifically — settings.
│   │                          LANGGRAPH_FOLLOWUP_ENABLED, mutually exclusive with the above
│   ├── query_analyzer.py      §5.2 structured query-analysis object (query_type/metric/
│   │                          entities/time_scope/granularity/ambiguous/intent_summary)
│   ├── clarification_engine.py YAML-driven clarification rule matcher (§5.3), additive
│   │                          to the hardcoded _needs_*_clarification predicates
│   ├── defaults_engine.py     §5.5 silent, disclosed defaults for unspecified details
│   ├── findings.py            §5.13 deterministic findings (extremes/ties/stale-data/
│   │                          large-result-set/threshold-breach) over a query's own rows
│   ├── chart_spec.py          §5.14 deterministic chart-type selection from result shape
│   ├── join_graph.py          §5.9 join-path lookup from the curated FK graph
│   ├── sql_join_validator.py  post-generation AST check: flags an invented join
│   ├── schema_retrieval.py    §5.8 scheme-filtered pgvector retrieval over table/column
│   │                          descriptions (+ optional rerank), feeds the SQL prompt
│   ├── sql_examples_retrieval.py  §5.10 vector-retrieved SQL few-shot examples
│   ├── scheme_registry.py     scheme_registry.yaml loader + app.schemes/tenant_schemes sync
│   ├── pii_guard.py           §11.4 two-layer PII protection (pre-execution SQL-text
│   │                          blocklist scan + unconditional post-execution row redaction)
│   ├── edge.py                regex edge-case handler (no model call)
│   ├── rag.py                 embed → pgvector search → rerank → answer
│   ├── kb_ingest.py           chunk data/**/*.md → embed → upsert to pgvector
│   ├── vectorstore.py         pgvector (Postgres) pool + helpers
│   ├── llm.py                 one httpx client; classify / SQL-gen / compose / embed / rerank / ASR
│   ├── db.py                  asyncpg pool; read-only SQL guard (sqlglot AST, not regex);
│   │                          tenant-context GUCs for curated-data RLS when enabled
│   ├── appdb.py                app.* schema (users, tenants, conversations, audit,
│   │                          schemes/tenant_schemes entitlements)
│   ├── auth.py                role/geography/granularity checks + audit
│   ├── security.py            HS256 JWT + pbkdf2_sha256 password hashing
│   ├── deps.py                request identity, role gates, RLS tenant-context wiring
│   ├── schema_context.py      in-prompt condensation of the data model, per scheme
│   ├── entity_resolver.py     district / block / year / village resolution (+ embedding
│   │                          fallback for the closed-set catalogues)
│   ├── annotations.py         loads few-shot + FK YAML from data/
│   ├── conversation_store.py  chat history + query audit persistence
│   ├── users.yaml             one-time seed for app.users
│   ├── net.py                 client-IP resolution with proxy trust (XFF)
│   ├── routers/               /api/query, /api/auth, /api/history, /api/rag, /admin
│   └── middleware/            security headers/CSP, body-size limit, per-user/IP rate limit
├── web/                       served UI
│   ├── ai_query.html          chat console          (/ai-query)
│   ├── admin.html             admin console         (/admin-ui)
│   └── Meghalaya_UnifiedPortal_UI.html   portal     (/)
├── data/                      SME-curated inputs, read at startup
│   ├── mgnrega/               few-shot, FK, entity-resolver, schema-metadata YAML
│   ├── pmay/                  same, for PMAY-G
│   ├── focus_plus/            same, for Focus Plus
│   ├── cm_elevate/            same, for CM Elevate
│   ├── reference/             scheme reference + FAQ docs, KPI workbooks
│   ├── schema/                schema_for_developers.md
│   └── web/                   scraped background docs (KB source)
├── openspec/                  planning source of truth — see CLAUDE.md's
│                              "Planning source of truth" section; run
│                              `openspec list` for current change status
│   ├── changes/                active (non-archived) change proposals
│   ├── changes/archive/        completed changes (22 as of this writing)
│   └── specs/                  capability specs synced from archived changes
├── docs/                      ARCHITECTURE.md · DATA_MODEL.md · SECURITY.md ·
│                              INFERENCE_REQUIREMENTS.md · baseline-audit.md
│                              (node-by-node GT-proposal coverage, kept current)
├── deploy/                    nginx conf, systemd unit, DEPLOYMENT.md, and
│                              deploy/sql/ (role/RLS/retention migration scripts)
├── tests/                     43 test scripts (42 standalone, exit-code-based
│                              — see CLAUDE.md's "Test convention" section,
│                              not pytest — plus smoke_restructure.py, which
│                              needs a live running server)
├── certs/                     internal CA bundle          (gitignored)
├── logs/                      audit JSONL + uvicorn out   (gitignored)
├── archive/                   reference zip, rotated .env backups (gitignored)
├── requirements.txt
├── .env                       secrets (gitignored)
└── .env.example
```

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

Not an exhaustive list — see `app/routers/` for the current, exact route set.

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

Exact current model names/roles live in `app/config.py` (`*_MODEL`
settings) — this table can drift from that file; treat `app/config.py` as
the source of truth if the two ever disagree.

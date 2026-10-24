# Architecture — Megh One AI (`nlp-service`)

*Reconciled against the code on 2026-09-26 (commit `7064ab6`). Replaces the earlier two-scheme
version of this file: that version described MGNREGA and PMAY-G only, `backend/` paths, and model
roles that have since moved.*
*Labels: **VERIFIED** (code, config or test) · **INFERRED** · **UNKNOWN — NEEDS VERIFICATION** · **PLANNED**.*

The AI chain in detail: [AI_PIPELINE.md](AI_PIPELINE.md). The database: [DATA_MODEL.md](DATA_MODEL.md).

---

## 1. Repository structure (VERIFIED)

```
meghalaya/
├── CLAUDE.md                  session rules + doc map (read first)
├── app/                       the FastAPI service (package `app`)
│   ├── main.py                app, lifespan startup, /health, /metrics, static UI routes
│   ├── config.py              every setting (pydantic-settings, reads .env)
│   ├── pipeline/              the whole routing + NL→SQL orchestration, as stage functions (see 3.4)
│   │   ├── common/            shared steps c01_followups.py … c14_turn_stages.py
│   │   └── schemes/           one file per scheme: mgnrega, pmay_g, focus_plus, cm_elevate,
│   │                          focus_legacy, cm_elevate_legacy — ONE shared namespace
│   ├── pipeline_graph.py      opt-in LangGraph orchestrator over the same stages (D-032)
│   ├── edge.py                regex edge layer (greetings, off-topic, harmful, identity)
│   ├── prompt_builder.py      SQL / repair / verifier prompt assembly
│   ├── schema_context.py      hand-written per-scheme TABLES / RULES / VOCAB prompt blocks
│   ├── schema_introspect.py   live information_schema + semantic.* catalogue → prompt blocks
│   ├── annotations.py         loads few-shot + FK YAML from data/; IDF few-shot ranking
│   ├── entity_resolver.py     district/block/year/AC/village resolution (YAML + live DB)
│   ├── llm.py                 one httpx client; all model roles; concurrency gate
│   ├── db.py                  asyncpg pool; run_readonly() guard for generated SQL
│   ├── rag.py · kb_ingest.py · vectorstore.py · local_embed.py   RAG path + KB ingest
│   ├── context_manager.py · conversation_memory.py · session_store.py · conversation_store.py
│   ├── context_budget.py      per-prompt token accounting + priority-aware SQL budget
│   ├── context_policy.py      per-field merge actions, follow-up kinds, provenance, rewrite checks
│   ├── session_sync.py        cross-worker conversation state via app.conversations
│   ├── followups.py           deterministic "next step" chips
│   ├── premise_check.py       checks numbers asserted in the question against the result
│   ├── cache.py · semantic_cache.py   response caches + metrics counters
│   ├── auth.py · security.py · deps.py · appdb.py · net.py · asr_guard.py
│   ├── users.yaml             one-time seed for app.users
│   ├── routers/               query, auth, history, rag, admin
│   └── middleware/            security headers, body limit, rate limit
├── frontend/                  React UI source (Vite): src/chat (chat console), src/admin
├── web/app/                   the built UI the app serves (`npm run build` in frontend/)
├── data/                      SME inputs read at startup: data/<scheme>/*.yaml + README,
│                              data/reference/*.md (KB), data/web/*.md (KB), data/schema/
├── docs/                      project documentation (this folder)
├── deploy/                    nginx (+ ModSecurity CRS), systemd unit, SQL role/retention scripts
├── tests/                     regression tests (pytest + plain scripts)
├── Dockerfile, docker-compose.yml, requirements.txt, requirements.lock, .env.example
└── certs/, logs/, archive/    gitignored contents (CA bundle, audit JSONL, rotated .env)
```

`nlp-service/` exists in the working tree but is empty and untracked (VERIFIED). Its purpose is
UNKNOWN.

`app/` resolves `data/` and `web/` as siblings (`Path(__file__).resolve().parents[1]`), so the
tree shape must be kept intact.

## 2. Runtime topology

```
browser ──HTTPS──► nginx (per app VM; TLS, WAF, rate zones)       deploy/nginx/nginx-nlpservice.conf
                     │ proxy_pass http://127.0.0.1:8400 (single upstream, no stickiness)
                     ▼
                uvicorn app.main:app --workers 2                  deploy/systemd/megh-nlpservice.service
                     ├─ asyncpg pool (10–30/worker) ─► PostgreSQL 18.4 megh_db   10.48.242.4:5432
                     ├─ httpx AsyncClient ───────────► vLLM gateway             https://10.48.242.4/openai/v1
                     ├─ AsyncQdrantClient ───────────► Qdrant                   http://115.124.102.167:6335
                     └─ embeddings: gateway qwen3-embedding, 1024-dim (D-067); rollback = fastembed bge-small, CPU
```

- **VERIFIED from the config and deploy files.** The target is two application VMs, each running
  nginx + systemd.
- **The VM hardware (from the earlier version of this doc, not verifiable from code):** ESDS VMs,
  24 vCores and 256 GB RAM each. VM #1 has 2× H200 GPUs, which this service does not use.
- **UNKNOWN — NEEDS VERIFICATION:** whether production is live, and whether the Docker path or
  the systemd path is used.
- **VERIFIED:** `docker-compose.yml` binds `127.0.0.1:8401:8400` and has an optional
  `local-infra` profile (Qdrant + Redis).

## 3. Components

For each component: its purpose, where it lives, its entry point, what it depends on, its input
and output, and how it fails.

### 3.1 App and lifecycle — `app/main.py` (VERIFIED)
- **Entry point:** `app = FastAPI(...)`.
- **Startup** (`lifespan`), in order:
  1. secret guard (logs CRITICAL, never blocks);
  2. `init_pool`;
  3. `init_client`;
  4. `init_qdrant`;
  5. `load_annotations` and `load_entity_resolver` (local YAML);
  6. `appdb.ensure_schema` (creates `app.*`, seeds users);
  7. `schema_introspect.load` (the live schema catalogue);
  8. `pipeline.refresh_scheme_years` (the per-scheme FY list from the DB);
  9. a **background** `ingest_kb` task.
- **Failure behaviour:** every remote step is wrapped in `_try`. The server always boots,
  **degraded**. The DB pool rebuilds lazily on first use.
- **Middleware order on the way in:**
  1. rate limit;
  2. body limit;
  3. CORS (only when `CORS_ALLOW_ORIGINS` is set);
  4. security headers (the outermost layer).
- **Global exception handler:** returns `{"detail":"internal error","request_id":…}` and never
  exposes stack traces.
- **Static routes:** `/` (the portal), `/megh-chat` (chat; `/ai-query` 301-redirects to it since
  2026-10-04), `/admin-ui`, `/static/*`. These are
  served `Cache-Control: no-cache`.
- `/docs` and `/openapi.json` are only available when `ENV=dev`.

### 3.2 API routes (VERIFIED from `app/routers/*`)

| Route | Auth | Purpose |
|---|---|---|
| `POST /api/query` | user JWT | `{question, session_id?}` → answer JSON (§4) |
| `POST /api/query/transcribe` | user JWT | multipart audio (≤10 MB) → `{text}` or `{text:"", no_speech:true}` |
| `POST /api/auth/login` · `/logout` · `GET /me` · `POST /bootstrap` | – / user | username+password → HS256 JWT; bootstrap first super_admin |
| `GET /api/history` · `GET/PATCH/DELETE /api/history/{session_id}` · `POST …/pin` · `…/archive` | user | officer-private chat history |
| `GET /api/rag/status` · `POST /api/rag/reingest` | user / admin | KB point count; rebuild the KB |
| `GET /api/scheme-stats` | user | welcome-card figures from megh_db, cached 10 min: `{cards: {key: [[value, label] ×3]}, periods: {key: "FY …"}, as_of}`; a NULL figure is "—"; 503 with no cached copy (the UI then shows its typed fallback and says so) (KI-378) |
| `GET/POST /admin/tenants`, `/admin/roles`, `/admin/users[/{id}]` (CRUD), `/admin/logins`, `/admin/conversations[/{id}]`, `/admin/audit`, `/admin/stats`, `/admin/schema` | admin JWT (tenant-scoped) | admin console API |
| `GET /health` | anonymous gets `{status}` only; admin JWT or `X-Metrics-Token` gets components | DB + Qdrant (+ Redis) status |
| `GET /metrics` | admin JWT or `X-Metrics-Token` | route counts, latency percentiles, cache stats |

**There is no WebSocket, SSE or streaming endpoint** (VERIFIED: nothing in `app/` or `web/`
matches `websocket` or `StreamingResponse`).

### 3.3 Query router — `app/routers/query.py` (VERIFIED)
- **Input:** `QueryRequest`. The question is 1–2000 characters, with C0 control characters
  stripped. `session_id` is optional and must match `^[A-Za-z0-9._:-]+$` (max 128).
- **Steps:**
  1. `_identity` requires a JWT when `AUTH_ENABLED`.
  2. Session id: the client's, else `day-<uid>-<date>`, else `one-<random>`.
  3. `session_store.ensure`. A fresh in-process session rehydrates its `ConversationState` from
     Postgres.
  4. If the question is not a follow-up fragment:
     - try the exact cache, then the semantic cache;
     - both are keyed on question + `scope.cache_fingerprint()`.
  5. `answer_question` runs under `asyncio.wait_for(REQUEST_TIMEOUT_SECONDS=60)`.
  6. Record the L1 turn.
  7. Fire-and-forget: `persist_turn`, `conversation_memory.index_turn`, `save_context_state`.
  8. JSONL audit mirror.
  9. Cache write-back.
  10. Metrics.
- **Error mapping:**

  | Exception | Result |
  |---|---|
  | `ClarificationNeeded` | 200 with `route:"clarification"`; stores `session.pending_scope_q` **in process** |
  | `ModelBusyError` | 503 + `Retry-After: 5` |
  | `DatabaseUnavailableError` (megh_db unreachable mid-question: VPN / network drop, lost connection) | 503 + `Retry-After: 5`, "Couldn't reach the Megh One data service…" (KI-025, 2026-09-28) |
  | `asyncio.TimeoutError` (the 60 s ceiling, or a re-raised DB `command_timeout`) | 504 |
  | `UnsafeSQLError` | 500. **Effectively unreachable:** the repair loop catches it and, once the budget is spent, `_run_pipeline` routes it to the KB fallback (AI_PIPELINE §2.8) |
  | anything else (e.g. an `httpx` timeout or 5xx re-raised from the pipeline) | 502 |

### 3.4 Pipeline — `app/pipeline/` package
The routing and NL→SQL chain. Until 2026-10-15 this was one 18,700-line `pipeline.py`; it is now
`common/` (the shared steps, `c01_followups.py` … `c14_turn_stages.py`) and `schemes/` (one file per scheme with
that scheme's village rules, fixed queries, SQL rewrites and answer checks). `app/pipeline/__init__.py`
executes them in `_PIPELINE_FILES` order (shared basics c01–c03, the six schemes, then c04–c14) into the package namespace, so `from app import pipeline as p`, `p.<name>` and
`monkeypatch.setattr(p, ...)` are unchanged. Edit the part that holds the function; never recreate
`app/pipeline.py` (the package would shadow it). It is documented stage by stage in
[AI_PIPELINE.md](AI_PIPELINE.md). Public entry points: `answer_question`,
`looks_like_followup`, `ClarificationNeeded`, `_empty_data_fields`.

Since 2026-10-02 (D-032) the pipeline is a set of **stage functions** (`_turn_*_stage`,
`_data_*_stage`, `_scheme_sql_rewrites`, `_execute_one_attempt`, `_repair_sql`) with two
orchestrators:
- `_run_pipeline`, the sequential driver (the default);
- `app/pipeline_graph.py`, a 21-node LangGraph graph (`PIPELINE_GRAPH_ENABLED` or
  `PIPELINE_GRAPH_CANARY_PERCENT`).

`answer_question` picks one; the router does not know which ran. Graph, state, checkpointing and
pause/resume: [LANGGRAPH_ARCHITECTURE.md](LANGGRAPH_ARCHITECTURE.md),
[LANGGRAPH_PAUSE_RESUME.md](LANGGRAPH_PAUSE_RESUME.md). The checkpointer (Postgres
`app.checkpoint*` tables shared by both VMs; Postgres is the only store) is opened lazily on the first graph request. `app.main`
starts the paused-thread sweep and closes the checkpointer only when the graph is in use;
`/health` then reports `components.pipeline_graph`.

### 3.5 LLM client — `app/llm.py` (VERIFIED)
- **Client:** one shared `httpx.AsyncClient`.
- **Concurrency:** a per-worker `asyncio.Semaphore(MODEL_MAX_CONCURRENCY=24)`. Waiting longer
  than `MODEL_QUEUE_TIMEOUT_SECONDS=20` raises `ModelBusyError`.
- **Request shape:**
  - `/chat/completions` with a **single `user` message** (no system prompt);
  - `chat_template_kwargs.enable_thinking=False`;
  - optional `guided_json` / `guided_regex`.
  - If the gateway returns 400/404/422 to a guided request, the call is retried once without the
    guided fields.
- **TLS:** uses the `AI_MODEL_CA_BUNDLE_PATH` file if it exists. Otherwise it **falls back to
  `verify=False`** and logs a warning (commit `5c5a100`).
- **Role wrappers:** `call_classifier`, `call_sql_generator`, `call_sql_verifier`,
  `call_response_composer`, `call_embedding`, `call_reranker`, `call_asr`.

### 3.6 Database access — `app/db.py` (VERIFIED)
- **`init_pool` / `ensure_pool`:** the asyncpg pool, with `command_timeout` =
  `SQL_EXECUTION_TIMEOUT_MS/1000` (15 s).
- **`run_readonly(sql)`:** the only path for LLM SQL. `_assert_safe` enforces:
  - no `;` inside the statement;
  - a `select`/`with` first word;
  - no `insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum` anywhere.

  It appends `LIMIT 1000` if the substring "limit" is absent.
- **`fetch_rows`, `fetchrow`, `fetchval`, `execute`, `execute_script`:** for the app's own
  parameter-bound SQL only.

### 3.7 Authentication and authorization (VERIFIED)
- **`security.py`:**
  - PBKDF2-HMAC-SHA256 (200k iterations);
  - HS256 JWT with `sub`, `username`, `tenant_id`, `role`, `exp`, issuer check;
  - TTL of `JWT_TTL_MINUTES=720`.
- **`deps.py`:** `current_scope`, `require_user`, `require_admin`, `require_super`.
- **`auth.py`:**
  - `ROLE_PERMISSIONS`: `super_admin`, `tenant_admin`, `admin`, `state_officer`,
    `district_officer`, `block_officer`, `analyst`, `public`. Every role lists all six schemes.
  - `scope_from_user` narrows a role by the user's own districts, blocks and schemes.
  - `authorize(scope, schemes, resolved_entities, sql)` runs **after SQL generation, before
    execution**. It checks scheme, geography and granularity (state < district < block < village)
    using regexes over the SQL. Admin roles bypass these checks. A deny returns `route:"denied"`.
- **Multi-tenancy:** every conversation, turn and audit row carries `tenant_id`, and admin reads
  are filtered by `_tenant_filter`.
- **Known gap:** the geography regex only recognises `lgd_district`/`lgd_block` (KNOWN_ISSUES
  KI-007).

### 3.8 Conversation state (VERIFIED)
- **L1 — `session_store.py`:**
  - in-process and per worker, with a TTL (`SESSION_TTL_SECONDS=14400`, 4 h, D-051; up to `SESSION_MAX_TURNS=50` turns);
  - up to 8 turns;
  - holds `pending_scope_q` / `pending_village_hint` / `pending_scope_rule` /
    `pending_scope_options`: the clarification-resume state, which is **not persisted** (KI-001);
  - each `Turn` carries `result_summary`, the deterministic row summary used as follow-up
    evidence;
  - since 2026-09-26 this is only a per-worker **cache**. `session_sync.sync_in` refreshes it
    from Postgres on every request, and `sync_out` writes it back awaited (KI-028 / KI-001,
    D-023).
- **L2 — `conversation_store.py`:** Postgres `app.conversations` and `app.conversation_turns`.
  Turn and audit writes are fire-and-forget via `asyncio.create_task`.
  - `context_state` (JSONB) holds the versioned session snapshot: state, provenance, last turn,
    pending clarification, recent questions and `rev`. It is the source of truth for
    conversation state, written by the awaited, revision-guarded `save_session_state`.
  - It also holds the rolling `summary`.
- **`context_manager.py`:** deterministic reference substitution, scheme-hint injection, merged
  prior entities, the follow-up context window, the follow-up evidence tiers
  (`build_rewrite_evidence`; AI_PIPELINE.md §5.1, D-022) and a periodic summary. State commits
  only on a successful DATA turn.
- **`context_policy.py`:** the per-field merge actions, follow-up kinds, provenance and
  field-specific rewrite checks (AI_PIPELINE.md §5.4, D-024).
- **`session_sync.py`:** cross-worker state (AI_PIPELINE.md §5.5, D-023).
- **`conversation_memory.py`:** semantic memory of older turns in the Qdrant collection
  `CONTEXT_MEMORY_COLLECTION` (`megh_conversation_memory_1024` since D-067; the 384-dim
  `megh_conversation_memory` is the rollback and is purged on the same 30-day schedule,
  `CONTEXT_MEMORY_PURGE_ALSO`). It is used only when the in-process session has fewer than 2
  turns. A collection of another vector size is never written or deleted: memory goes off
  with one ERROR (KI-402). Search is exact (`SearchParams(exact=True)`) over payload indexes on
  `tenant_id`, `user_id`, `session_id`, `ts`, created with the collection (KI-408).

### 3.9 RAG and knowledge base (VERIFIED)
- **`kb_ingest.py`:**
  - chunks the `_SOURCES` docs (10 SME docs in `data/reference/`) plus tagged `data/web/*.md`;
  - embeds them;
  - on startup, recreates the Qdrant collection `megh_scheme_kb` if it is missing, too small, or
    missing any scheme (`vectorstore.distinct_schemes`).
- **`rag.py`:**
  - `retrieve` searches Qdrant with an **exact-match** `scheme` payload filter;
  - `answer_from_kb` answers in tiers: top score ≥ 0.84 → the chunk verbatim; ≥ 0.55 → composed
    by the 9B; below that → "not covered";
  - `answer_from_kb_multi` retrieves per scheme.
- **CM Elevate Legacy** reads CM Elevate's KB (`_KB_SCHEME_ALIAS`).
- **The reranker is disabled** (`RERANKER_ENABLED=False`).

### 3.10 Caches and metrics (VERIFIED)
- **`cache.py`:**
  - exact-match LRU (TTL 900 s, 2,000 entries), with an optional Redis L2 (`REDIS_URL`);
  - the `metrics` counters.
- **`semantic_cache.py`:** in-process cosine cache (threshold 0.93, TTL 900 s, 1,000 entries),
  which reuses the pipeline's embedding.
- **Neither cache** stores clarifications or follow-up fragments.

### 3.11 Frontend — `frontend/` (React), served from `web/app/` (VERIFIED)
- A React 18 app built with Vite (D-038, 2026-10-07). It replaced the vanilla `web/ai_query.html`
  and `web/admin.html` with the same behaviour and the same CSS (copied verbatim into
  `frontend/src/styles/`). Two entry pages:
  - `frontend/index.html` → `src/chat/` — the chat console, served at `/megh-chat`:
    - `api.js`: every backend call (`/api/query`, `/api/query/transcribe`, `/api/history*`,
      `/api/auth/*`), the JWT in `localStorage` (`megh_jwt`), 401 → sign-in gate; a
      `ConnectionError` for a network / proxy / data-service (VPN) failure, which `App.jsx` shows as
      the "Can't reach the server — retrying…" banner while it polls `GET /health`, then re-asks
      the waiting question once (2026-10-07);
    - `App.jsx`: sign-in and session check, sending, history, rail, keyboard, language tabs;
    - `components/`: `Markdown.jsx` (answer text as a safe Markdown subset: lists, tables, headings,
      bold, code; React elements only), `Messages.jsx` (answer, clarification and follow-up chips, SQL disclosure;
      per-message actions: Copy and Edit on a question — an edit removes that question and the
      turns after it from the screen and asks the edited text in the same conversation — and
      Copy and Read aloud (browser `speechSynthesis`, no server call) on an answer),
      `Charts.jsx` (Chart.js 4.4.1 from npm, tables), `Sidebar.jsx`, `WelcomeCard.jsx`
      (scheme carousel), `Overlays.jsx` (sign-in, modal, mic overlay, undo toast);
    - `useVoice.js`: recording → 16 kHz mono WAV → transcribe; `analytics.js`: chart choice.
  - `frontend/admin.html` → `src/admin/AdminApp.jsx` — the admin console, served at `/admin-ui`.
- `npm run build` writes `web/app/index.html`, `web/app/admin.html` and hashed bundles under
  `web/app/assets/` (loaded from `/static/app/assets/`). The build output is kept in the repo so
  the app (and the Docker image) serves the UI without Node.
- `/` redirects to `/megh-chat`. The portal landing page (`Meghalaya_UnifiedPortal_UI.html`) was
  removed on 2026-10-07.
- The chat accepts an optional **`?api=<base-url>`** query parameter (`API_BASE`), which
  prefixes every API call.
  - The default is same-origin.
  - A cross-origin base is blocked by the enforced CSP (`connect-src 'self'`) unless CSP and
    CORS are changed.

### 3.13 Unused code in `data/` (VERIFIED)
`data/cm_elevate/prompt_assembler.py` and `data/focus_plus/prompt_assembler.py` are tracked in
git but **imported by nothing** in `app/` or `tests/`. They are SME-side artefacts. Do not assume
they affect prompts; the live prompt is built by `app/prompt_builder.py`.

### 3.12 Security middleware — `app/middleware/` (VERIFIED)
- `security_headers.py`:
  - CSP (`'unsafe-inline'` is kept for the inline JS);
  - HSTS, nosniff, frame-deny, referrer and permissions policies;
  - `X-Request-ID`.
- `limits.py`: a 256 KB body cap. The transcribe route is exempt and has its own 10 MB cap.
- `rate_limit.py`: per-IP sliding window. `/api/auth/login` allows 6 per 300 s; `/api/query*`
  allows 30 per 60 s. The backend is `memory` by default, or `redis`.
- The full OWASP map is in [SECURITY.md](SECURITY.md).

## 4. `/api/query` response shape (VERIFIED)

Every route carries `route`, `intent`, `answer`, `session_id`, `execution_time_ms` and the empty
data fields `schemes`, `resolved_entities`, `sql`, `sql_query`, `row_count`, `rows`, `data`.

| `route` | Extra fields |
|---|---|
| `data` | `confidence`, `rows` (the first 20), `data` (all rows, ≤1000), `follow_up_options`, `rewritten_question?`, `scope_banner` (the scope the SQL used, D-050) |
| `knowledge` | `confidence`, `sources`, `follow_up_options` |
| `edge` | `edge_type` (incl. `conversation_history`, `context_continued`, D-050), `suggestions` |

Any route may also carry `continue_offer` ("Continue with MGNREGA (…)"): only on the first reply after an idle
expiry; sending that text restores the set-aside context (D-050). A `/api/query/stream` request the client
abandons (Stop) is cancelled and its question remembered; the next "continue" in that thread answers it (D-050).
| `clarification` | `needs_clarification`, `question`, `clarification:{options, rule}` |
| `denied` | `denied_by` (`scheme`/`geography`/`granularity`) |

## 5. Data stores

| Store | What | Owner |
|---|---|---|
| `megh_db.curated` / `semantic` | Scheme data (read-only to this app) | ingestion team |
| `megh_db.app` | `tenants`, `users`, `login_events`, `conversations`, `conversation_turns`, `query_audit` | this app (`appdb.ensure_schema`) |
| Qdrant `megh_scheme_kb_v4` (`QDRANT_COLLECTION`) | KB chunks, 1024-dim qwen3-embedding + BM25 (D-067). `megh_scheme_kb_v3` (384-dim bge-small) kept for rollback | this app |
| Qdrant `megh_conversation_memory_1024` (`CONTEXT_MEMORY_COLLECTION`) | past-turn vectors per tenant/user/session, 1024-dim. `megh_conversation_memory` (384-dim) kept for rollback | this app |
| `logs/query_audit.jsonl` | JSONL audit mirror (questions, IPs) | this app (gitignored) |
| `ASR_DEBUG_DIR` (e.g. `logs/asr_samples`) | **every voice upload saved as WAV plus its transcript** when set. It is set in the local dev `.env` (VERIFIED, 2026-09-26); diagnostics only | this app (gitignored under `logs/`) |

**DB roles.**
- `deploy/sql/01_create_megh_app_role.sql` creates `megh_app` with SELECT on
  `curated`/`semantic`, and **SELECT/INSERT/UPDATE/DELETE + CREATE on `app`**.
- The **local dev `.env` connects as `postgres`** (VERIFIED, 2026-09-26).
- Which role production uses is UNKNOWN — NEEDS VERIFICATION. See KI-004.

## 6. Configuration

- All settings are in [app/config.py](../app/config.py) and can be overridden by `.env`.
  `.env.example` lists about 94 keys.
- `.env` is read relative to the working directory, so run from the repo root. It is gitignored
  and holds secrets.
- The systemd unit deliberately does **not** use `EnvironmentFile=`, because inline `#` comments
  would break parsing.
- **Feature toggles** (all `True` unless noted):
  - Clarification gates: `SCHEME_CLARIFY_ENABLED`, `TOPN_…`, `SCOPE_…`, `YEAR_…`,
    `TRANCHE_CLARIFY_ENABLED`.
  - Guards: `OUT_OF_SCOPE_GUARD_ENABLED`, `PREMISE_CHECK_ENABLED`, `YEAR_RANGE_GUARD_ENABLED`,
    `SQL_VERIFY_ENABLED`.
  - Places: `PLACE_GAZETTEER` (D-059, on): the level of a place from the database's village index.
  - Context layer: `CONTEXT_*`.
  - Follow-ups: `FOLLOWUP_REWRITE_ENABLED`, `FOLLOWUP_SUGGEST_ENABLED`.
  - Decoding: `GUIDED_DECODING_ENABLED` (classifier JSON). `SQL_GUIDED_DECODING_ENABLED` is no longer read (2026-10-15): SQL generation sends no decoding constraint.
  - Other: `SCHEMA_CATALOG_ENABLED`.
  - `RERANKER_ENABLED` is **False**.

## 7. Logging, error handling and observability (VERIFIED)

- Logging: the stdlib `logging` format `time | level | name | message`.
  - Pipeline log lines carry **no request id, user or question**. The exception is the
    `prompt_context` line per model prompt (`app/context_budget.py`): section token sizes,
    budget and `request_id`, taken from `X-Request-ID` via a contextvar set in
    `middleware/security_headers.py`. It contains no prompt text.
  - `llm_call` lines, one per model call: role, model, queue ms, latency ms, and the gateway's
    `prompt_tokens` / `completion_tokens`.
  - The SQL of a failed attempt is **not logged** (KI-003).
  - With the LangGraph orchestrator on: `pipeline_graph_node` (one per node: shapes, outcome,
    ms) and `pipeline_graph_run` (one per request: node path, outcome, repairs, pause outcome),
    both carrying `request_id` and no question text (D-032).
- Audit: `app.query_audit` (DB) plus the `logs/query_audit.jsonl` mirror.
  - Recorded: user, tenant, role, route, schemes, granularity, allow/deny, row count, IP,
    latency.
  - **Not recorded: the SQL.**
- `app.conversation_turns` stores the final SQL and the response JSON.
- `/metrics`: `requests_by_route` (including `:cache` and `:semcache`), latency p50/p95/p99,
  `busy_rejections_total`, `errors_total`, and cache and session stats.
- Degradation is silent, logged only as warnings:
  - a verifier failure is treated as "no issue";
  - a schema-catalogue load failure falls back to the hand-written prompt;
  - context-layer failures are ignored.

## 8. Capacity (from config; design target 20–40 concurrent users, about 200 DAU)

| Control | Setting |
|---|---|
| Model concurrency | 24 slots per worker; 2 workers × 2 VMs = 96 cluster-wide (INFERRED from the deploy files) |
| Load shed | 20 s queue wait → 503 |
| Request ceiling | 60 s → 504 (nginx `proxy_read_timeout` 120 s) |
| DB pool | 10–30 per worker; statement timeout 15 s; ≤1000 rows |
| Caches | exact 15 min; semantic 15 min at cosine 0.93 |

- **Model calls per DATA request** (from `TECHNICAL_BRIEF.md` §1.2, derived from the code path):
  best case 3, typical 4–6, worst case about 13.
- **Scaling risks** (per-worker state, per-IP rate limit behind NAT, prompt size): see
  KNOWN_ISSUES.

## 9. External services and infrastructure

| Service | Where | Notes |
|---|---|---|
| vLLM model gateway | `https://10.48.242.4/openai/v1` | self-signed "Enlight AIOps" CA; microk8s/KServe (per `docs/INFERENCE_REQUIREMENTS.md`) |
| PostgreSQL 18.4 `megh_db` | `10.48.242.4:5432` | shared box; pgAdmin on :8080 |
| Qdrant 1.18.3 | `115.124.102.167:6335` (since 2026-10-03) | live collections `megh_scheme_kb_v4`, `megh_conversation_memory_1024` (1024-dim, D-067); rollback copies `megh_scheme_kb_v3`, `megh_conversation_memory` (384-dim); older `megh_scheme_kb`, `megh_scheme_kb_v2`, `megh_general_kb`, `megh_general_web_kb` unused; the `Metadata_*` collections there are not ours |
| Redis | optional (`REDIS_URL`) | blank in local `.env`; production value UNKNOWN |

The `10.48.242.4` host requires the office Fortinet VPN from dev machines (source: earlier
session notes, not verifiable from code).

## 10. Deployment

See [deploy/DEPLOYMENT.md](../deploy/DEPLOYMENT.md): Python 3.11, venv, `.env`, the systemd unit,
nginx, ModSecurity CRS (staged `DetectionOnly` → `On`), DB role and retention scripts, and a
go-live checklist.

- The Docker build uses `requirements.txt`, not the lock file, because the lock pins
  Windows-only packages.
- No PM2 and no AWS appear in the repo (VERIFIED).

## 11. Component dependency graph (VERIFIED imports, simplified)

```
routers/query ─► pipeline ─► edge, context_manager, followups, premise_check, rag, auth
                    │
                    ├─► prompt_builder ─► schema_context, schema_introspect, annotations
                    ├─► entity_resolver ─► db (villages/AC live), data/*/…entity_resolver.yaml
                    ├─► llm (all model roles)
                    └─► db.run_readonly
rag ─► vectorstore (Qdrant), local_embed/llm.call_embedding
routers/query ─► cache, semantic_cache, session_store, conversation_store, conversation_memory
main ─► appdb, schema_introspect, annotations, entity_resolver, kb_ingest, db, llm, vectorstore
```

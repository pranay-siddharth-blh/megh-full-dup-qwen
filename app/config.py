from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "NLP Service - MGNREGA / PMAY-G / Focus Plus / CM Elevate"
    PORT: int = 8401
    LOG_LEVEL: str = "INFO"
    REQUEST_TIMEOUT_SECONDS: int = 60  # hard ceiling on one /api/query, enforced in the router
    # KI-013: no new SQL repair starts after this many seconds of the request, so the
    # turn ends with the "couldn't build a working query" reply instead of a 504.
    REPAIR_TIME_BUDGET_SECONDS: int = 40

    # POST /api/query/stream (D-039): live progress steps and the composer's
    # text as it is written. STREAM_COMPOSER_ENABLED=false keeps the progress
    # steps but sends the answer only when it is complete (the composer then
    # makes its ordinary call). The ping keeps proxies from closing a quiet stream.
    STREAM_COMPOSER_ENABLED: bool = True
    STREAM_PING_SECONDS: float = 10.0

    # ── OWASP hardening (see docs/SECURITY.md) ─────────────────────────────
    # "prod" (default) or "dev". dev re-enables /docs + /openapi.json and drops
    # the secret guard to a warning; every other value is treated as prod.
    ENV: str = "prod"
    # Fail-closed switch for the production checks that would otherwise stop a box
    # running with ENV=prod by mistake (this dev box does, with a missing CA file):
    # with it on and ENV=prod, a configured-but-missing AI_MODEL_CA_BUNDLE_PATH
    # refuses to start the model client instead of falling back to verify=False.
    # Off until every dev machine sets ENV=dev (E12 / SEC-07, 2026-10-29).
    BOOT_GUARD_ENFORCE: bool = False

    # A04 — global ceiling on a request body, enforced in BodyLimitMiddleware.
    # The audio upload on /api/query/transcribe is exempt (it keeps its own
    # 10 MB check in the router); everything else is JSON and tiny.
    MAX_REQUEST_BYTES: int = 262_144          # 256 KB
    MAX_QUESTION_CHARS: int = 2000            # A03 — cap the free-text question field

    # A05 — CORS. Blank => no CORS middleware at all (same-origin only, the safe
    # default: the UI is served from this same origin). Set to a comma-separated
    # allowlist of exact origins ("https://portal.example.gov.in") to open it up.
    CORS_ALLOW_ORIGINS: str = ""

    # A05 — response security headers (SecurityHeadersMiddleware).
    SECURITY_HEADERS_ENABLED: bool = True
    # Enforced CSP. Pragmatic: the served HTML uses inline <script>/<style> and
    # inline onclick handlers, so script/style keep 'unsafe-inline'. The
    # high-value directives that do NOT need a UI rewrite (frame-ancestors,
    # base-uri, object-src, form-action) are enforced. Tighten once the inline
    # JS is externalised — track via CSP_REPORT_ONLY below.
    # Google Fonts (fonts.googleapis.com stylesheet + fonts.gstatic.com font files)
    # are allowed so the served UI's <link> to Inter / JetBrains Mono isn't blocked.
    # The CSS already carries full system-font fallback stacks, so for an offline /
    # locked-down deployment you can instead drop the <link> tags from web/*.html and
    # remove these two hosts again.
    CSP_ENFORCE: str = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data:; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    # Optional strict policy shipped as Content-Security-Policy-Report-Only — lets
    # you see what a nonce-based, no-unsafe-inline policy would break before
    # enforcing it. Blank => header not sent.
    CSP_REPORT_ONLY: str = ""
    # A02 — HSTS. Only meaningful once TLS terminates in front (see deploy/nginx).
    HSTS_ENABLED: bool = True
    HSTS_MAX_AGE: int = 31_536_000            # 1 year

    # A04/A09 — X-Forwarded-For is only trusted when the direct socket peer is in
    # this set (CIDRs or bare IPs, comma-separated). Otherwise the socket peer is
    # used as the client IP. Stops a client spoofing XFF to dodge the rate limit
    # or poison the audit trail. Default: loopback + RFC1918 (the nginx sidecar
    # and the vFirewall/LB sit there).
    TRUSTED_PROXIES: str = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

    # A01 — /metrics gate. When set, /metrics requires this value in an
    # X-Metrics-Token header (for a Prometheus-style scraper). When blank,
    # /metrics requires an admin JWT.
    METRICS_TOKEN: str = ""

    # A07 — brute-force throttle on POST /api/auth/login, per client IP.
    LOGIN_RL_MAX: int = 6
    LOGIN_RL_WINDOW_SEC: int = 300

    # Rate-limit backend: "memory" (per-worker, the default) or "redis" (shared
    # across workers/VMs, reuses REDIS_URL). Redis errors degrade to memory.
    RATELIMIT_BACKEND: str = "memory"

    # ── Capacity control (target: 20-40 concurrent users, ~200 DAU) ──
    # Total in-flight calls to the shared model gateway, across the whole worker.
    # The 30B SQL model is the scarce resource; vLLM continuous-batching handles
    # ~24 concurrent decodes on an H200 comfortably. Past this, requests queue;
    # past MODEL_QUEUE_TIMEOUT they are shed with 503 rather than piling up.
    MODEL_MAX_CONCURRENCY: int = 24
    MODEL_QUEUE_TIMEOUT_SECONDS: int = 20

    # In-process response cache — repeated questions skip the pipeline entirely.
    RESPONSE_CACHE_ENABLED: bool = True
    RESPONSE_CACHE_TTL_SECONDS: int = 900      # 15 min — DB loads are batch/infrequent
    RESPONSE_CACHE_MAX_ENTRIES: int = 2000

    # Semantic (near-duplicate) response cache — a layer past the exact-match one.
    # Embeds the question with qwen3-embedding and serves a stored answer when an
    # earlier question clears SEMANTIC_CACHE_THRESHOLD cosine similarity
    # ("houses in EGH" vs "houses in East Garo Hills"). One embedding call per
    # otherwise-uncached question, to potentially save the 2-4 chat calls a full
    # pipeline run makes. Embedding failures degrade to a plain cache miss.
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_THRESHOLD: float = 0.93     # cosine; below this it's a miss
    SEMANTIC_CACHE_TTL_SECONDS: int = 900
    SEMANTIC_CACHE_MAX_ENTRIES: int = 1000
    SEMANTIC_CACHE_MIN_CHARS: int = 12         # don't embed very short inputs (greetings)

    # ── Shared response cache (optional Redis L2) ──
    # With workers on 2 VMs the in-process cache above is per-worker: a question
    # answered on one worker still misses on the other three. Point REDIS_URL at
    # a shared Redis (e.g. Upstash) and the exact-match cache also reads/writes
    # there, so a hit anywhere is a hit everywhere. In-process stays as L1; Redis
    # is L2. Any Redis error (unset URL, auth, network) degrades silently to
    # in-process-only — it never fails a request. Blank => feature off.
    REDIS_URL: str = ""                        # rediss://default:<token>@<host>:6379
    REDIS_CACHE_PREFIX: str = "megh:qcache:"
    REDIS_SOCKET_TIMEOUT: float = 1.5          # keep cache I/O off the request critical path

    # ── Guided / structured decoding (vLLM Outlines/xgrammar backend) ──
    # Constrain the small JSON/enum classifier calls to only emit tokens that fit
    # the schema — removes the "unusable response -> slow fallback" path entirely
    # and is usually faster (the model can't wander into invalid tokens it then
    # backtracks from). Sent as extra fields on the /chat/completions body; the
    # _extract_json / _extract_sql parsers still run, so a gateway that ignores
    # these fields keeps working unchanged.
    GUIDED_DECODING_ENABLED: bool = True
    # NOT READ ANY MORE (2026-10-15). It gated a text-shape decoding constraint on
    # SQL generation, removed because no text matching reads or shapes SQL; prose preambles
    # and ```sql fences are removed by _extract_sql on the sqlglot token stream.
    # Kept only so an existing .env that still sets it loads without error.
    SQL_GUIDED_DECODING_ENABLED: bool = True

    # ── Database (megh_readonly-style role — SELECT only, enforced again in db.py) ──
    DATABASE_URL: str = ""  # postgresql://user:pass@10.48.242.4:5432/megh_db (asyncpg wants no "+asyncpg")
    # Connections are only held for the execute step, not across the LLM calls, so
    # pool demand is well below the concurrent-user count. Sized for the 20-40
    # concurrent / 100-200 DAU target with headroom, on the shared megh_db box
    # (10.48.242.4) that also serves pgAdmin and any ad-hoc analyst sessions.
    # MIN is small on purpose (2026-10-16): megh_db hit max_connections = 100
    # ("too many clients already"), almost all of it idle postgres logins — 20
    # from one 2-worker container (2 x min 10) and 28 from a dev box with two
    # servers up. A connection opened to fill min_size and never used is never
    # closed by the inactivity timer, so min_size is what a worker holds idle
    # forever. Grow on demand up to MAX; DB_POOL_IDLE_SECONDS closes the extra.
    DB_POOL_MIN_SIZE: int = 1
    DB_POOL_MAX_SIZE: int = 30
    DB_POOL_TIMEOUT: int = 30
    # Close a pooled connection idle this long (asyncpg max_inactive_connection_lifetime).
    DB_POOL_IDLE_SECONDS: float = 120.0
    # Model-generated SQL runs on its own pool, logged in as a SELECT-only role
    # (megh_readonly — deploy/sql/03_readonly_role.sql) with every statement in
    # a READ ONLY transaction and search_path = curated, semantic. DATABASE_URL
    # (megh_app — sql/01) keeps the app's own users/chat/audit writes and our
    # trusted parametrised queries. Blank falls back to DATABASE_URL, still in
    # READ ONLY transactions, with a CRITICAL log line; a superuser login on
    # this pool is refused unless READONLY_DB_ALLOW_SUPERUSER (dev only).
    # Sized small: megh_db has max_connections = 100 and ~80 in use (2026-10-15),
    # and this pool only holds a connection for the execute step.
    READONLY_DATABASE_URL: str = ""
    READONLY_DB_POOL_MIN_SIZE: int = 1
    READONLY_DB_POOL_MAX_SIZE: int = 10
    READONLY_DB_ALLOW_SUPERUSER: bool = False
    SQL_EXECUTION_TIMEOUT_MS: int = 15000
    SQL_MAX_RESULT_ROWS: int = 1000
    # Before a generated query runs, ask the database to plan it with
    # semantic.check_query (DB team, 2026-10-27): it sees through views and CTEs
    # and flags two fact tables joined row by row, which our SQLGlot join rules
    # can miss. Advisory and fail-open: if the function is slow or missing, the
    # query runs as before. Off = no extra round trip.
    SQL_DB_PRECHECK: bool = True
    # The DB team's execute-only login (2026-10-27, D-073): megh_chatbot may only
    # call semantic.run_query, which plans the query (row joins, cost) and runs
    # it with megh_readonly's rights. Set -> every generated query goes through
    # run_query on this login; blank -> run_readonly executes on the read-only
    # pool as before. Its own cap is 20 connections (4 per worker x 5).
    CHATBOT_DATABASE_URL: str = ""
    CHATBOT_DB_POOL_MIN_SIZE: int = 1
    CHATBOT_DB_POOL_MAX_SIZE: int = 4
    # run_query refuses a plan above this estimated cost (the team's default;
    # our most expensive logged query was ~102K).
    SQL_MAX_COST: int = 1_000_000
    # PostgreSQL application_name on every megh_db connection, "<this>:<pool>"
    # (app / readonly / chatbot / checkpointer). The DB team cannot tell builds
    # apart without it (the 20 postgres sessions from 172.18.0.2, 2026-10-27).
    # Blank = not set.
    DB_APPLICATION_NAME: str = "megh-chatbot-v2"

    # ── Model gateway — all roles on the same self-hosted OpenAI-compatible vLLM
    #    gateway at 10.48.242.4, behind a self-signed "Enlight AIOps" internal CA.
    #    The application tier does ZERO local inference; every model call is a
    #    network hop to this box. ──
    #
    #    MODEL ROLES — the agreed assignment (2026-10-15); change only by decision:
    #      Intent classifier / router  qwen4-deploy (Qwen3-4B)    CLASSIFIER_MODEL
    #          simple labelling; guided JSON / fixed labels. Also entity extraction.
    #      Query rewrite / follow-up   qwen35-9b    (Qwen3.5-9B)  REWRITE_MODEL
    #          needs real language understanding — a bad rewrite breaks the chain.
    #          The rephraser, follow-up rewrite and conversation summary.
    #      SQL generation              qwen-model   (qwen3-coder-30b)  SQL_GENERATION_MODEL
    #      SQL error fix / retry       qwen-model   — the same call, given the DB
    #          error and the failed SQL (prompt_builder.build_repair_prompt).
    #      Verifier                    qwen-model   (not the 4B)   SQL_VERIFY_MODEL
    #          after the free code checks (the guards in _execute_one_attempt).
    #      Answer composer             qwen35-9b                  RESPONSE_MODEL
    #      qwen3-embedding / qwen3-reranker : RAG (scheme-knowledge) path.
    #      qwen3-asr                        : voice input transcription.
    #    Each deployment has its own gateway key: a role moved to another model
    #    takes that model's key (*_API_KEY).
    AI_MODEL_CA_BUNDLE_PATH: str = ""  # certs/enlight-aiops-internal-ca.pem, if verification is required

    # Classify / intent / entity-extract — on the dedicated 4B, NOT the 9B or the
    # 30B, so these frequent small calls never queue behind SQL generation or
    # composition, and composition never queues behind them either.
    CLASSIFIER_MODEL: str = "qwen4-deploy"
    CLASSIFIER_BASE_URL: str = "https://10.48.242.4/openai/v1"
    CLASSIFIER_API_KEY: str = ""
    CLASSIFIER_TIMEOUT_SECONDS: int = 30
    CLASSIFIER_TEMPERATURE: float = 0.0

    # Query rewrite / follow-up resolution — the 9B (see MODEL ROLES above):
    # the rephraser (pipeline p02), the follow-up rewrite (p01) and the
    # conversation summary (context_manager). Same deployment as RESPONSE_MODEL.
    REWRITE_MODEL: str = "qwen35-9b"
    REWRITE_BASE_URL: str = "https://10.48.242.4/openai/v1"
    REWRITE_API_KEY: str = ""                   # blank -> RESPONSE_MODEL_API_KEY (same deployment)
    REWRITE_TIMEOUT_SECONDS: int = 30

    # SQL generation and SQL repair — the 30B coder. The verifier runs here too.
    SQL_GENERATION_MODEL: str = "qwen-model"
    SQL_GENERATION_BASE_URL: str = "https://10.48.242.4/openai/v1"
    SQL_GENERATION_API_KEY: str = ""
    SQL_GENERATION_TIMEOUT_SECONDS: int = 30
    SQL_GENERATION_TEMPERATURE: float = 0.0
    # NOT READ ANYWHERE (KI-008): the repair budget is the graph's, 3 repairs (D-072, agreed
    # with the DB team). Kept only so an .env that still sets it does not stop the app
    # (Settings refuses unknown keys); changing it changes nothing.
    SQL_GENERATION_MAX_RETRIES: int = 1

    # qwen35-9b — final natural-language answer composition only. Classify/intent/
    # entity-extract moved to qwen4-deploy (see CLASSIFIER_MODEL above) on
    # 2026-09-10, so this deployment now serves only this role.
    RESPONSE_MODEL: str = "qwen35-9b"
    RESPONSE_MODEL_BASE_URL: str = "https://10.48.242.4/openai/v1"
    RESPONSE_MODEL_API_KEY: str = ""
    RESPONSE_TEMPERATURE: float = 0.0
    RESPONSE_MAX_TOKENS: int = 800
    RESPONSE_TIMEOUT_SECONDS: int = 20
    # E9 (2026-10-29): a ranking / comparison / trend / split answer has its figures
    # written by code from per-shape templates (c12_answer_shapes._c12s_e9_body); the
    # composer writes only the opening line, with no figure. false = the composer writes
    # the whole answer from the shape guide, as before (the rollback).
    ANSWER_TEMPLATES_ENABLED: bool = True

    # ── SQL semantic verifier — qwen3-coder-30b (qwen-model), not the 4B ──
    # Execution checks first, then this (2026-10-15): it runs after the free code
    # guards AND after the query has run, and is a second opinion asking "does
    # this SQL actually answer the question, per the schema rules and resolved
    # entities above it?" (prompt_builder.build_verify_prompt).
    # The SQL shape guards already in _execute_one_attempt only catch SQL shapes a past
    # bug taught them to recognise (bare row read on an aggregate question,
    # village-name-instead-of-code, a phantom 'Meghalaya' filter, ...). This
    # catches the same CLASS of bug — syntactically valid, executes cleanly,
    # answers the wrong question — in a shape nobody has hand-coded a guard for
    # yet. A flagged query raises straight into the existing repair loop; no new
    # control flow needed for that part.
    # Best-effort: any failure (model not deployed, timeout, unparseable JSON)
    # degrades to "no issue found" — a verifier outage must never block an
    # answer that would otherwise have worked.
    # Was qwen4-deploy (2026-09-10); moved to the 30B on 2026-10-15 (MODEL ROLES
    # above) — the 4B hallucinated violations on correct SQL, which is what the
    # false-positive filters in p15_sql_verify_repair work around.
    SQL_VERIFY_ENABLED: bool = True
    SQL_VERIFY_MODEL: str = "qwen-model"
    SQL_VERIFY_BASE_URL: str = "https://10.48.242.4/openai/v1"
    SQL_VERIFY_API_KEY: str = ""                # blank -> SQL_GENERATION_API_KEY (same deployment)
    SQL_VERIFY_TEMPERATURE: float = 0.0
    SQL_VERIFY_TIMEOUT_SECONDS: int = 15

    # KB chunk + query embeddings for the RAG path, and the semantic cache.
    # "local"  -> fastembed CPU model (LOCAL_EMBEDDING_MODEL), no gateway call.
    # "gateway" -> EMBEDDING_MODEL on the OpenAI-compatible gateway.
    # The dev box runs "gateway" (qwen3-embedding, 1024-dim) from .env since
    # D-067 (2026-10-24); "local" (384-dim) stays the default here as the
    # rollback. Changing it needs NEW collections (QDRANT_COLLECTION,
    # CONTEXT_MEMORY_COLLECTION) and the cut-offs re-tuned to the new scale.
    EMBEDDING_PROVIDER: str = "local"
    LOCAL_EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"  # 384-dim, ONNX, ~130 MB
    EMBEDDING_MODEL: str = "qwen3-embedding"
    EMBEDDING_BASE_URL: str = "https://10.48.242.4/openai/v1"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_TIMEOUT_SECONDS: int = 30
    EMBED_BATCH_SIZE: int = 32

    # qwen3-reranker — re-ranks the Qdrant candidates of EVERY knowledge question
    # (D-083, 2026-10-29, user rule). There is deliberately NO on/off setting:
    # RERANKER_ENABLED was removed, and a .env that still sets it now fails at
    # startup instead of silently switching the re-ranker off. It was off from
    # 2026-08-29 (D-005, "inverts relevance") — that came from sending the bare
    # question; app/llm.py now sends the Qwen3 yes/no format. Broken? Fix it.
    RERANKER_MODEL: str = "qwen3-reranker"
    RERANKER_BASE_URL: str = "https://10.48.242.4/openai/v1"
    RERANKER_API_KEY: str = ""
    RERANKER_TIMEOUT_SECONDS: int = 30

    # qwen3-asr — voice input transcription for /api/query/transcribe
    ASR_MODEL: str = "qwen3-asr"
    ASR_BASE_URL: str = "https://10.48.242.4/openai/v1"
    ASR_API_KEY: str = ""
    ASR_TIMEOUT_SECONDS: int = 60
    # Vocabulary hint sent as the OpenAI-style `prompt` field (the gateway honours
    # it). Without it the model writes "East Cassey Hills", "Riphoi",
    # "dispersment"; with it every district came back right (measured
    # 2026-09-25). Keep it SHORT — listing all 70 blocks made the model snap to a
    # wrong real block name. On speech-free audio the model returns this text
    # verbatim; asr_guard.is_prompt_echo() turns that into "no speech". Empty
    # disables it. The digits example matters: without it "financial year
    # 2024-25" came back as "twenty twenty four twenty five".
    ASR_PROMPT: str = (
        "Questions about Meghalaya government schemes (MGNREGA, PMAY-G, Focus Plus, "
        "Focus Legacy, CM Elevate, CM Elevate Legacy), with numbers written as digits, "
        "e.g. FY 2023-24, 2024-25, top 5, Rs 10,000. Beneficiaries, producer groups "
        "(PGs), disbursement, sanctioned, person-days. Districts: East Khasi Hills, "
        "West Khasi Hills, South West Khasi Hills, Eastern West Khasi Hills, Ri Bhoi, "
        "East Jaintia Hills, West Jaintia Hills, East Garo Hills, West Garo Hills, "
        "North Garo Hills, South Garo Hills, South West Garo Hills."
    )
    # Diagnostics only: when set, every /api/query/transcribe upload is saved
    # there (WAV + the ASR's answer) so a bad transcript can be replayed. Holds
    # users' voice recordings — leave empty outside local debugging.
    ASR_DEBUG_DIR: str = ""

    # ── Vector store (Qdrant on the same data box) — scheme-knowledge base ──
    # Since 2026-10-27 (D-074) the project uses ONLY two collections on the
    # data box's Qdrant: megh_knowledge (scheme reference pieces, RAG) and
    # megh_sql_metadata (question->SQL examples, SQL_EXAMPLES_SOURCE=qdrant).
    # Both are loaded by another pipeline; the app only reads them.
    QDRANT_URL: str = "http://10.48.242.4:6333"
    QDRANT_API_KEY: str = ""
    # megh_scheme_kb_v2 since the RAG upgrade Phase 2 (2026-10-14): built from
    # data/incoming/<scheme>/. Rollback: set QDRANT_COLLECTION=megh_scheme_kb.
    # megh_scheme_kb_v3 since Phase 3 (2026-10-15): the same pieces plus a BM25
    # keyword vector for hybrid search. Rollback: megh_scheme_kb_v2 / megh_scheme_kb.
    # megh_knowledge since 2026-10-27 (D-074), read-only (below).
    QDRANT_COLLECTION: str = "megh_knowledge"
    # True: the app never deletes, rebuilds or writes the KB collection —
    # startup ingest and POST /api/rag/reingest skip, recreate/upsert refuse.
    # megh_knowledge belongs to the loading pipeline: the old ingest would
    # have DELETED it on the first start (no BM25 vector -> "rebuilding").
    # False = the app owns its collection and builds it from data/incoming/.
    QDRANT_KB_READ_ONLY: bool = True
    # These defaults are on the bge-small (local, 384-dim) cosine scale:
    # loosely-related chunks score ~0.66-0.78, so HIGH sits above that —
    # otherwise every knowledge question clears it and returns its nearest
    # chunk verbatim instead of composing. MEDIUM is the real working tier for
    # this KB. qwen3-embedding scores ~0.1-0.15 lower, so .env sets MEDIUM 0.35
    # with megh_scheme_kb_v4 (D-067).
    # RAG upgrade Phase 3 (2026-10-14, app/local_rank.py): keyword (BM25) search
    # fused with meaning search. Hybrid needs a collection built with the
    # "bm25" sparse vector (kb_ingest does this whenever RAG_SPARSE_MODEL is
    # set); on an older collection search falls back to meaning only. ""
    # switches it off.
    RAG_SPARSE_MODEL: str = "Qdrant/bm25"
    RAG_HYBRID_ENABLED: bool = True
    # The local jina cross-encoder (RAG_LOCAL_RERANKER) was removed 2026-10-29
    # (user decision, D-083): re-ranking is qwen3-reranker on the gateway only.
    RAG_CANDIDATES: int = 12       # candidates searched for with hybrid search on
    # Phase 4 (2026-10-15): search with the question AND this many other
    # wordings of it written by the fast model ("documents?" -> "documents
    # required for PMAY-G registration"), merged by rank. 0 = off. One short
    # model call per knowledge question; a timeout or bad reply searches with
    # the question alone.
    # Khasi / Garo (the KHA / GAR buttons) translated to English before the
    # pipeline runs (app/translate.py, Phase 4). OFF: the user wants English
    # only for now (2026-10-15); built and tested, switch on with True.
    TRANSLATE_ENABLED: bool = False
    # A question written in Devanagari (Hindi) is translated to English whichever button
    # is selected: its letters say what it is (RAG fix report Issue 9, 2026-10-29).
    TRANSLATE_SCRIPT_ENABLED: bool = True
    TRANSLATE_TIMEOUT_SECONDS: int = 10
    # OFF until Phase 5. Measured 2026-10-15 (search only, 188 questions): on
    # its own it HURT (right piece first 47.6% -> 39.0%; the extra wordings pull
    # in generic pieces), but with the jina re-sorter it helps — in the top 3
    # 78.0% -> 80.5%, found 90.9% -> 92.1%, and on the 27 real officer questions
    # top 3 55.6% -> 74.1%, found 77.8% -> 88.9%. Phase 5 turns both on (2).
    RAG_MULTI_QUERY: int = 0
    RAG_MULTI_QUERY_TIMEOUT_SECONDS: int = 6
    # Phase 5 (2026-10-15): after the composer writes, drop the sentences the
    # passages do not support (rag.ground_answer). One more short model call.
    # Measured with the re-sorter and 8 pieces: answers with a made-up sentence
    # 16.5% -> 9.8%, made-up sentences 4.5% -> 2.9%. An answer whose EVERY
    # sentence is flagged is kept (the check misread it; Q132).
    RAG_GROUNDING_CHECK: bool = True
    RAG_GROUNDING_TIMEOUT_SECONDS: int = 15
    RAG_TOP_K: int = 12            # candidates pulled from Qdrant
    RAG_RERANK_TOP_N: int = 8      # chunks handed to the composer as context
    RAG_MIN_SCORE: float = 0.30    # floor on the chunk score
    RAG_HIGH_CONFIDENCE: float = 0.84   # >= this: return top chunk verbatim (rare, near-exact match)
    RAG_MEDIUM_CONFIDENCE: float = 0.55  # >= this: compose an answer from the kept chunks

    # ── Multi-turn / follow-up context ──
    # Per-worker, in-process, TTL'd. A short-lived store of the last few turns of
    # a chat so "what about East Garo Hills?" can be rewritten to a standalone
    # question. Lost on restart; not shared across workers — same stance as the
    # response caches.
    # User decision 2026-10-18 (D-051): 4 h idle window, 50 turns (was 30 min, 8).
    SESSION_TTL_SECONDS: int = 28800         # 8 h sliding window (user, 2026-10-19; was 4 h, D-051)
    SESSION_MAX: int = 5000                   # sessions kept before oldest-first eviction
    SESSION_MAX_TURNS: int = 50               # turns retained per session (and questions in the snapshot)
    # ── Lane A2: conversation integrity (2026-10-29) ──
    # Total deadline of one plain POST /api/query (REL-02b). It has no keep-alive
    # pings, and nginx closes it at 120 s; REQUEST_TIMEOUT_SECONDS per part, one
    # part per scheme, could pass that. The streamed route is not capped.
    QUERY_NONSTREAM_MAX_SECONDS: float = 110.0
    # Retention of the conversation tables (CTX-04): app.conversations and their
    # turns idle longer than this many days are deleted once a day
    # (conversation_memory.purge_loop). 0 = keep everything: the period is the
    # user's decision, so nothing is deleted until one is set. The query audit
    # is the compliance trail (conversation_store.delete_conversation never
    # touches it), so it has its own period, also 0 until it is decided.
    CONVERSATION_RETENTION_DAYS: int = 0
    QUERY_AUDIT_RETENTION_DAYS: int = 0
    # Conversation layer (app/conversation_layer.py), run by the router before
    # the caches and the pipeline: idle expiry, "start a new topic" / "forget
    # the previous question", and "what was the PMAY-G information again?".
    # Off = every message runs exactly as before the layer existed.
    CONVERSATION_LAYER_ENABLED: bool = True
    # A conversation idle longer than this starts afresh: the next question
    # inherits no scheme, place, year, topic or pending clarification. The
    # chat history itself is kept. 0 = never expire. Same window as the
    # in-process session (SESSION_TTL_SECONDS), which the durable snapshot
    # used to outlive.
    CONTEXT_IDLE_EXPIRY_SECONDS: int = 28800   # 8 h (user, 2026-10-19; was 4 h in D-051, 30 min before)
    # Topic ledger + backward references (app/topic_memory.py, Context Memory
    # proposal Phase 3, 2026-10-18): each topic keeps its last
    # CONTEXT_LEDGER_PER_TOPIC questions with the scope each ran in, so "go
    # back to the East Khasi Hills one", "the first question" and "what did we
    # discuss?" restore / list an earlier question. Off = only the topic's
    # last question can be returned to, exactly as before.
    BACKWARD_RESOLVER_ENABLED: bool = True
    CONTEXT_LEDGER_PER_TOPIC: int = 20         # D-051 (was 6): up to 8 x 20 = 160 questions
    # Phase 4: when a message refers back ("that one", "the housing figure
    # you gave") but the rules above place it nowhere, the rewrite model (9B,
    # follow-up resolution in the fixed role map) PICKS one ledger question id,
    # NONE or ASK. It never writes a scheme, place or year: any other output is
    # discarded. One call, only on such turns. Off = those turns run as before.
    LLM_REFERENCE_ENABLED: bool = True
    LLM_REFERENCE_TIMEOUT_SECONDS: int = 8
    FOLLOWUP_REWRITE_ENABLED: bool = True    # one classifier call when a turn looks like a follow-up
    # Query rephraser (graph node `rephrase`, D-037): a messy NEW question
    # (typos, Hinglish, voice-to-text, no question shape) is rewritten into one
    # clean question before routing. One classifier call, only when the
    # question looks messy; follow-ups and pause replies skip it. The rewrite is
    # rejected (original kept) if it adds, drops or changes a scheme, place,
    # year, number or measure. Never blocks: a slow or failed call keeps the
    # original question.
    QUERY_REPHRASE_ENABLED: bool = True
    QUERY_REPHRASE_TIMEOUT_SECONDS: int = 8
    QUERY_REPHRASE_MAX_CHARS: int = 400
    # Deterministic "Next steps" chips under each data/knowledge answer, built
    # from a fixed scheme-aware bank (backend/followups.py) — no model call.
    FOLLOWUP_SUGGEST_ENABLED: bool = True
    # Pause and ask "which scheme?" when a data question names no scheme, asks for
    # no cross-scheme view, and uses no scheme-specific vocabulary. Off => fall
    # back to the classifier's guess (usually "both"), as before.
    SCHEME_CLARIFY_ENABLED: bool = True
    # Pause and ask "top how many?" when a data question asks for a ranking over a
    # dimension (districts/blocks/villages) but names no count — offer Top 3 / 5 /
    # 10 / all as one-tap replies instead of silently defaulting to top 10. Off =>
    # let the SQL layer pick its own default limit, as before.
    TOPN_CLARIFY_ENABLED: bool = True
    # Pause and ask "which area and year?" when an aggregate data question ("how
    # many houses sanctioned", "total expenditure") pins no district / block /
    # village and no financial year — neither in its text nor via a resolved
    # entity — and doesn't ask for a breakdown or an explicit statewide total.
    # The reply is free text ("West Garo Hills 2023-24", "all of Meghalaya, all
    # years"); it's merged back into the original question. Off => answer
    # statewide across all years silently, as before. Applies to both schemes.
    SCOPE_CLARIFY_ENABLED: bool = True
    # Pause and ask "which financial year?" when a data question fixes its own
    # geography (a comparison / per-dimension breakdown, or a specific district /
    # block / village) but names no year — neither in its text nor via a resolved
    # entity — and doesn't ask for a time series ("trend", "year on year") or an
    # explicit "all years". Offers the scheme's financial years plus "all years
    # combined" as one-tap replies. This is the year half of the scope gate for
    # questions the scope gate itself skips because their place is already pinned.
    # Off => answer across every year silently, as before.
    YEAR_CLARIFY_ENABLED: bool = True
    # Pause and ask "which tranche?" when a Focus Plus data question (a metric or
    # per-dimension breakdown) names no tranche — neither in its text (resolved via
    # resolve_tranche_label) nor via a resolved entity — and doesn't ask for a
    # per-tranche breakdown or an explicit "all tranches combined". Offers Tranch 1
    # / 2 / 3 / 4 plus "all tranches combined" as one-tap replies, the same shape as
    # YEAR_CLARIFY_ENABLED above. Focus Plus only — no other scheme has a
    # tranche_label column. Off => answer across every tranche silently, as before.
    TRANCHE_CLARIFY_ENABLED: bool = True
    # User decision 2026-10-14: answer, don't ask. When a data question names no
    # area / no financial year / no tranche, answer for all of Meghalaya / all
    # financial years combined / all tranches combined — the same text the
    # "All of Meghalaya" / "All financial years combined" chips add — and say so
    # in the answer. A data question naming no scheme with a measure several
    # schemes record is answered for each of them (app/cross_scheme.py). Real
    # ambiguity (a name that is several places, a bare "Focus") still asks.
    # Off => the scope / year / tranche / scheme pauses above, as before.
    ANSWER_DEFAULTS_ENABLED: bool = True
    # User decision 2026-10-29 (RAG fix report Issue 6; reverses D-056's new-chat district
    # ask and D-053 / D-065's new-chat year ask): a data question that names no place is
    # answered for all of Meghalaya and one that names no year for all financial years
    # combined, the default stated in the answer — all 8 home-screen starter questions
    # were stopped by a pause. A chat's remembered place / year still wins. True = the
    # D-056 / D-065 asks come back (rollback).
    NEW_CHAT_ASKS_SCOPE: bool = False
    # Reply with the standard "I'm Megh One AI — I only cover Meghalaya's MGNREGA
    # / PMAY-G" message when a data question names a district or block that is not
    # in Meghalaya (resolver returns not_found), instead of dropping the filter,
    # running the query anyway and reporting a hollow 0. Off => keep the old
    # behaviour (add a note, let the composer say "not a known district").
    OUT_OF_SCOPE_GUARD_ENABLED: bool = True
    # Check a quantity the question asserts as already-true ("the 1.71 L
    # sanctioned houses", "of the ₹500 Cr released") against the query result.
    # Lenient: a note is added only when NO value in a small (1-3 row) result is
    # close to the asserted figure — it then tells the composer not to restate
    # that number as fact. A premise that matches any returned figure is left
    # alone (column labels can disagree without the premise being wrong).
    # Deterministic, no model call. Off => premise unchallenged, as before.
    # See backend/premise_check.py.
    PREMISE_CHECK_ENABLED: bool = True
    # Stop and say "I only have data for FY 2022-23 to FY 2025-26" when a data
    # question names a financial year outside that window — a bare "1999-20",
    # "2010", "FY 2019-20", etc. Both schemes' year coverage is exactly those
    # four years. Off => keep the old behaviour (add a soft note, then fall
    # through to the "which year?" pause or answer across the years that exist).
    YEAR_RANGE_GUARD_ENABLED: bool = True
    # A place's LEVEL comes from the database, not from the word "village"
    # (user report 2026-10-21, D-059). On: the in-memory village index also
    # holds each village's code / block / district and the schemes with rows
    # for it; an exact village anywhere in Meghalaya is never offered as a
    # look-alike block or constituency; a typo goes to the clearly closest
    # level; the level question is settled silently by the chat's remembered
    # block / district or the asking scheme's data when that leaves one
    # reading; the entity extractor is told which places the question names.
    # Off => the D-058 behaviour.
    PLACE_GAZETTEER: bool = True

    # ── Authorization (role + scope vs. what the query asks for) ──
    # Checks are pure Python (backend/auth.py). Users, tenants, conversations and
    # the audit trail live in the `app` schema of megh_db (created at startup).
    AUTH_ENABLED: bool = True
    # Multi-tenant: every user belongs to a department/directorate (a tenant).
    # tenant_admin manages their own tenant; super_admin manages all of them.
    MULTITENANCY_ENABLED: bool = True
    DEFAULT_TENANT_CODE: str = "RD"           # Rural Development — seeded at startup
    DEFAULT_TENANT_NAME: str = "Rural Development Department"

    # JWT (HS256, self-contained — see backend/security.py). CHANGE JWT_SECRET.
    JWT_SECRET: str = "change-me-dev-secret"
    JWT_ISSUER: str = "megh-nlp-service"
    JWT_TTL_MINUTES: int = 720                # 12h officer session

    # Break-glass: this token may bootstrap the first super_admin via
    # POST /api/auth/bootstrap when app.users is empty. Blank => bootstrap open
    # only while there are zero users. Also still accepted as X-Admin-Token for
    # read-only /admin/* in AUTH_ENABLED=false dev mode.
    ADMIN_TOKEN: str = ""

    # One-time import: if app.users is empty at startup, seed from this YAML.
    USERS_FILE: str = "app/users.yaml"
    # Mirror of the DB audit trail; keep for grep/offline. DB is source of truth.
    AUDIT_FILE: str = "logs/query_audit.jsonl"
    # Role when AUTH_ENABLED=false (local dev only — real requests carry a JWT).
    AUTH_DEFAULT_ROLE: str = "analyst"

    # Live schema catalog (semantic.* in megh_db) folded into the SQL prompt.
    SCHEMA_CATALOG_ENABLED: bool = True

    # ── Conversation context layer (ChatGPT-style multi-turn state) ──
    # Sits around the existing follow-up rewrite (looks_like_followup /
    # rewrite_followup) and prior_resolved entity carry — it does not replace
    # them. See app/context_manager.py. Everything here degrades to the
    # pre-existing behaviour when disabled or on any failure.
    CONTEXT_LAYER_ENABLED: bool = True
    # D-100: a frame per answered turn (the whole window in the snapshot) and one
    # resolver call for a follow-up, checked deterministically (app/context_frames.py).
    # Off, or on any failure / failed check, the follow-up path is the pre-D-100 one.
    CONTEXT_FRAMES_ENABLED: bool = True
    # Deterministic structured-state carry (scheme hint, previous/current year
    # substitution, comparison-entity former/latter/other resolution). Cheap,
    # no model call; safe to leave on independent of the summary/memory knobs.
    CONTEXT_STATE_ENABLED: bool = True
    # Token-aware context window fed to the follow-up rewrite LLM call when a
    # plain prev.question/prev.answer isn't enough (long conversation). A
    # "token" here is approximated as 4 characters — no tokenizer dependency.
    CONTEXT_MAX_TOKENS: int = 1200
    CONTEXT_RECENT_TURNS: int = 4              # most-recent turns considered "recent"
    CONTEXT_SUMMARY_MAX_TOKENS: int = 200
    CONTEXT_HISTORICAL_TURNS_MAX: int = 3      # semantic-memory turns folded in
    # Periodic conversation summary (schemes/locations/years/metrics discussed
    # so far), persisted on app.conversations. Updated every N turns, not on
    # every turn — keeps it off the request-latency critical path most of the
    # time. Best-effort: a summarization failure never breaks the answer.
    CONTEXT_SUMMARY_ENABLED: bool = True
    CONTEXT_SUMMARY_EVERY_N_TURNS: int = 4
    # Semantic memory: relevant-older-turn retrieval over a dedicated Qdrant
    # collection (separate from the scheme-KB collection AND from the
    # semantic response cache — see app/conversation_memory.py). Reuses the
    # existing Qdrant client + embedding pipeline. Off, or any Qdrant failure,
    # falls back to PostgreSQL recent history / in-session turns only.
    # OFF since 2026-10-27 (D-074): only megh_knowledge and megh_sql_metadata
    # may be used, and memory needs a collection of its own. Postgres
    # (context_state, recent history) still carries the conversation.
    CONTEXT_SEMANTIC_MEMORY_ENABLED: bool = False
    CONTEXT_MEMORY_COLLECTION: str = "megh_conversation_memory"
    CONTEXT_MEMORY_MIN_SCORE: float = 0.55
    CONTEXT_MEMORY_TOP_K: int = 5
    # Only reach for semantic memory when the in-process session has fewer than
    # this many turns of its own (i.e. a resumed/long conversation past the
    # in-memory window) — keeps the common case (recent turn already in
    # session_store) free of an extra embed + Qdrant round trip.
    CONTEXT_MEMORY_MIN_SESSION_TURNS: int = 2
    # Conversation memory older than this is never used and is deleted daily
    # (conversation_memory.purge_old_turns; RAG upgrade Phase 7). 0 = keep all.
    CONTEXT_MEMORY_RETENTION_DAYS: int = 30
    # Other memory collections purged on the same schedule, comma-separated.
    # The 384-dim and 1024-dim collections both hold officers' chats (D-067:
    # the unused one is kept for rollback), so both follow the window. A
    # collection that does not exist is skipped.
    # Empty since 2026-10-27 (D-074): those two lived on the old Qdrant server
    # (115.124.102.167:6335), which the app no longer uses.
    CONTEXT_MEMORY_PURGE_ALSO: str = ""
    # Follow-up rewrite evidence tiers (context_manager.build_rewrite_evidence).
    # Tier 1, the previous turn's structured filters, is always sent and is
    # a single line. Tiers 2 and 3 are sent only when the follow-up points INTO
    # the previous result ("the top one", "that block"):
    #   Tier 2  a deterministic summary of the previous result rows;
    #   Tier 3  a sentence-bounded excerpt of the previous answer, used only
    #           when there were no rows (a knowledge answer).
    # These replace the old fixed prev.answer[:300] slice.
    # Shared conversation state across workers (app/session_sync.py, KI-028).
    # Every request reads the durable snapshot in app.conversations and writes
    # the next revision back (awaited, bounded by the timeout). Off: per-worker
    # memory only, which was the behaviour before 2026-09-26.
    CONTEXT_STATE_SHARED: bool = True
    CONTEXT_STATE_SYNC_TIMEOUT_SECONDS: float = 1.0
    # KI-314 (2026-10-18): a brief DB drop (VPN flap) failed one snapshot save
    # or load, and the next request on another worker answered in a stale
    # scope. Both are retried once after this pause before giving up.
    CONTEXT_STATE_SYNC_RETRY_SECONDS: float = 0.5
    CONTEXT_PREV_RESULT_MAX_TOKENS: int = 120
    CONTEXT_PREV_ANSWER_MAX_TOKENS: int = 120

    # ── LangGraph orchestrator (app/pipeline_graph.py, D-032, D-036) ──
    # The only driver of the pipeline stages: per-node logs, an explicit SQL
    # repair loop, and clarification pauses as interrupt() with a checkpoint
    # keyed by thread_id = session_id. There is no sequential path and no
    # on/off switch (D-036).
    # Checkpoint backend: Postgres only. "postgres" (the default; blank means the
    # same) reuses DATABASE_URL; a postgresql:// DSN names another database.
    # Either way the four checkpoint tables live in app.* (search_path=app),
    # shared by every worker on both VMs (KI-184/185). "memory" is an
    # in-process saver for tests and offline dev only. If Postgres cannot be
    # opened the worker falls back to memory and a pause still resumes from the
    # Session snapshot (docs/LANGGRAPH_PAUSE_RESUME.md §4).
    PIPELINE_GRAPH_CHECKPOINTER_DSN: str = "postgres"
    # Postgres checkpointer pool, per worker. The saver runs one statement at a
    # time per worker (its own lock), so 2 = one for the saver plus one for the
    # advisory lock held during setup/sweep. 2 workers x 2 VMs x 2 = 8 conns.
    # Values below 2 are raised to 2 (1 would deadlock setup).
    PIPELINE_GRAPH_PG_POOL_MAX: int = 2
    # "exit": one checkpoint write per run (at a pause or the end). "async" /
    # "sync": one per node, for crash forensics, at a write per node.
    PIPELINE_GRAPH_DURABILITY: str = "exit"
    # A finished run's thread is deleted; only paused threads persist. True
    # keeps finished threads for debugging (they then grow without bound).
    PIPELINE_GRAPH_KEEP_THREADS: bool = False
    # An unanswered pause's thread is swept after this long (the Session's own
    # pending pause expires with SESSION_TTL_SECONDS).
    PIPELINE_GRAPH_PAUSE_TTL_SECONDS: int = 1800
    PIPELINE_GRAPH_SWEEP_EVERY_SECONDS: int = 600

    # ── Metric catalogue (app/metric_catalog.py, D-071) ──
    # semantic.metric_definitions as a fixed query for a question that names
    # one measure and asks nothing else. "off": not loaded. "shadow": matched
    # and logged only. "on": a measure listed for that query type in
    # data/metric_catalog_verified.yaml answers through the catalogue query;
    # every other question takes the model path as before. "on" since
    # 2026-10-26, after tests/metric_catalog_eval.py (report:
    # new_docs/Metric_Catalogue_Report_2026-10-26.md).
    METRIC_CATALOG_MODE: str = "on"
    # B1 (RAG plan, user decision 2026-10-27): a data question whose wording names
    # no catalogue measure logs its wording and the nearest measure by meaning
    # (one embedding call, in the background; never used to answer) to
    # METRIC_MEANING_FILE, for review: tests/metric_meaning/review.py. Approved
    # wordings go to data/metric_catalog_synonyms.yaml as exact synonyms.
    METRIC_MEANING_SHADOW: bool = True
    # B3 (RAG plan, 2026-10-27): a DATA verdict for a question with no place, year,
    # ranking or breakdown is overturned to KNOWLEDGE when the best megh_knowledge
    # passage beats the best megh_sql_metadata worked example by >= 0.10 (c13
    # classify_intent; measured with tests/intent_scores/run_eval.py).
    INTENT_SCORE_TIEBREAK: bool = True
    # E1 stage 1 (RAG plan, D-078): after each data / knowledge turn, one background
    # classifier call reads the question into a typed plan and logs it beside the
    # pipeline's own decisions to QUERY_PLAN_FILE (app/query_plan.py). Shadow only:
    # nothing reads the plan. Agreement report: tests/query_plan/compare.py.
    QUERY_PLAN_SHADOW: bool = True
    # E1 stage 2a (D-085, with RAG plan E2): true = for a new question the plan
    # starts beside the guardrail model call instead of after the answer; nothing
    # waits for it and the shadow log reuses it. OFF: measured live 2026-10-29 the
    # two 4B calls do not overlap for free (turn median 11.8 s -> 14.1 s, 6/6 pairs
    # slower; the plan itself 0.8 s -> 1.5-3.0 s). Turn on only once a stage reads
    # the plan and drops a call of its own (stage 2b), or the gateway has headroom.
    QUERY_PLAN_IN_TURN: bool = False
    QUERY_PLAN_FILE: str = "logs/query_plan_shadow.jsonl"
    METRIC_MEANING_FILE: str = "logs/metric_meaning_shadow.jsonl"

    # ── Input guardrails (app/guardrails.py) ──
    # Layer 1 (rules) always runs. Layer 2 is one classifier-model call per new
    # question that judges its meaning, so a harmful request phrased in words
    # no rule lists is still refused. A model failure fails closed for abuse
    # only: a message with an abuse word is refused, the rest go on (layer 1
    # already ran); FAIL_CLOSED refuses every message instead. ALERT_THRESHOLD
    # failures inside ALERT_WINDOW_SECONDS log one ERROR "ALERT guardrail"
    # line per window (E2, 2026-10-29; counts on /metrics "guardrail").
    GUARDRAIL_MODEL_ENABLED: bool = True
    GUARDRAIL_MODEL_TIMEOUT_SECONDS: float = 6.0
    GUARDRAIL_MODEL_FAIL_CLOSED: bool = False
    GUARDRAIL_MODEL_MAX_CHARS: int = 1000
    GUARDRAIL_ALERT_THRESHOLD: int = 3
    GUARDRAIL_ALERT_WINDOW_SECONDS: float = 300.0
    # Where an ALERT is also POSTed as JSON (counts only, never question text),
    # e.g. a Slack / Teams / Alertmanager incoming webhook. Blank = log only.
    ALERT_WEBHOOK_URL: str = ""

    # ── Prompt budgets (approximate input tokens; app/context_budget.py) ──
    # Each is the served --max-model-len minus that call's max_tokens
    # reservation (docs/INFERENCE_REQUIREMENTS.md):
    #   qwen-model   16,384 - 1,024 = 15,360  (SQL generation and repair)
    #   qwen4-deploy  8,192 -   200 =  7,992  (classifier roles: rewrite, verifier)
    # qwen35-9b's max-model-len is not recorded in the repo, so the composer
    # budget is 0 (unchecked). These budgets log and warn only; nothing is
    # pruned (see context_budget's docstring for why).
    # Where the SQL prompt's worked examples come from (2026-10-27, D-074):
    # "yaml"   -> the per-scheme few-shot banks in data/ (annotations), ranked by
    #             IDF token overlap — the behaviour before this switch;
    # "qdrant" -> the kind=example points of SQL_EXAMPLES_COLLECTION, ranked by
    #             meaning (one embedding call per data question, made in
    #             _data_sql_stage), plus the collection's kind=view / kind=join
    #             notes in the prompt (prompt_builder._sql_metadata_block).
    #             Any failure, timeout or empty result falls back to "yaml"
    #             for that turn.
    # "qdrant" since 2026-10-27 evening (user: use everything in both
    # collections across the app). Compare the two with
    # tests/nl2sql_eval/compare_examples_source.py; "yaml" is the rollback.
    # "yaml_meaning" (B5, 2026-10-29): the reviewed YAML banks ranked by meaning
    # (sql_examples._rank_yaml), no megh_sql_metadata. Not the default until measured.
    SQL_EXAMPLES_SOURCE: str = "yaml"   # user decision 2026-10-29 (B5, D-086)
    SQL_EXAMPLES_COLLECTION: str = "megh_sql_metadata"
    SQL_EXAMPLES_TIMEOUT_SECONDS: float = 4.0
    PROMPT_BUDGET_SQL_TOKENS: int = 15360
    PROMPT_BUDGET_CLASSIFIER_TOKENS: int = 7992
    PROMPT_BUDGET_COMPOSER_TOKENS: int = 0

    class Config:
        env_file = ".env"


settings = Settings()


# ── Startup secret guard (A02 / A05) ─────────────────────────────────────────
_DEFAULT_JWT_SECRETS = {"change-me-dev-secret", "CHANGE_ME_to_a_long_random_string", ""}
_DEFAULT_ADMIN_TOKENS = {"CHANGE_ME", ""}


def insecure_secrets() -> list[str]:
    """Names of settings still holding a default / obviously-weak value. Empty
    list means the crypto material has been rotated. Logged at CRITICAL on
    startup (main.py lifespan) and surfaced in the authenticated /health body;
    it never blocks boot — see docs/SECURITY.md."""
    problems: list[str] = []
    if settings.AUTH_ENABLED:
        if settings.JWT_SECRET in _DEFAULT_JWT_SECRETS or len(settings.JWT_SECRET) < 32:
            problems.append("JWT_SECRET (default or shorter than 32 chars)")
    if settings.ADMIN_TOKEN in _DEFAULT_ADMIN_TOKENS and settings.ADMIN_TOKEN != "":
        problems.append("ADMIN_TOKEN (default 'CHANGE_ME')")
    # The vector store holds the scheme knowledge base AND officers' chat
    # history (conversation memory); without a key anyone who can reach its
    # port can read, change or delete both (KI-200, RAG upgrade Phase 7).
    if not settings.QDRANT_API_KEY:
        problems.append("QDRANT_API_KEY (empty — Qdrant accepts requests without a key)")
    # E12 / SEC-07: a CA path with no file means gateway TLS is never verified
    from pathlib import Path
    if settings.AI_MODEL_CA_BUNDLE_PATH and not Path(settings.AI_MODEL_CA_BUNDLE_PATH).expanduser().is_file():
        problems.append("AI_MODEL_CA_BUNDLE_PATH (configured but the file is missing — gateway TLS is not verified)")
    return problems


def reranker_problem() -> str:
    """Why qwen3-reranker cannot work with this configuration, or "" when it
    can. The re-ranker has no off switch (D-083); without a key or URL every
    knowledge question silently falls back to vector order, so main.py logs
    this at ERROR on startup."""
    if not settings.RERANKER_BASE_URL or not settings.RERANKER_MODEL:
        return "RERANKER_BASE_URL / RERANKER_MODEL empty"
    if settings.RERANKER_API_KEY in ("", "CHANGE_ME"):
        return "RERANKER_API_KEY empty or 'CHANGE_ME'"
    return ""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "NLP Service - MGNREGA / PMAY-G / Focus Plus / CM Elevate"
    PORT: int = 8300
    LOG_LEVEL: str = "INFO"
    REQUEST_TIMEOUT_SECONDS: int = 60  # hard ceiling on one /api/query, enforced in the router

    # ── OWASP hardening (see docs/SECURITY.md) ─────────────────────────────
    # "prod" (default) or "dev". dev re-enables /docs + /openapi.json and drops
    # the secret guard to a warning; every other value is treated as prod.
    ENV: str = "prod"

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
    # Nudge SQL-gen to open on a bare SELECT/WITH (kills prose preambles and
    # ```sql fences before they cost a repair round-trip). Deliberately looser
    # than a full SQL grammar — it enforces shape, not join correctness.
    SQL_GUIDED_DECODING_ENABLED: bool = True

    # ── Database (megh_readonly-style role — SELECT only, enforced again in db.py) ──
    DATABASE_URL: str = ""  # postgresql://user:pass@10.48.242.4:5432/megh_db (asyncpg wants no "+asyncpg")
    # Connections are only held for the execute step, not across the LLM calls, so
    # pool demand is well below the concurrent-user count. Sized for the 20-40
    # concurrent / 100-200 DAU target with headroom, on the shared megh_db box
    # (10.48.242.4) that also serves pgAdmin and any ad-hoc analyst sessions.
    DB_POOL_MIN_SIZE: int = 10
    DB_POOL_MAX_SIZE: int = 30
    DB_POOL_TIMEOUT: int = 30
    # While megh_db is known-down, fail new pool attempts immediately for this
    # long instead of re-paying the full DB_POOL_TIMEOUT on every call (e.g.
    # every /health check) — see app/database/db.py's ensure_pool().
    DB_POOL_RETRY_COOLDOWN_SECONDS: int = 5
    SQL_EXECUTION_TIMEOUT_MS: int = 15000
    SQL_MAX_RESULT_ROWS: int = 1000

    # ── Model gateway — all roles on the same self-hosted OpenAI-compatible vLLM
    #    gateway at 10.48.242.4, behind a self-signed "Enlight AIOps" internal CA.
    #    The application tier does ZERO local inference; every model call is a
    #    network hop to this box. ──
    #
    #    MODEL ROLES (deployment name -> what it does):
    #      qwen-model   (qwen3-coder-30b-fp8) : SQL GENERATION ONLY. The scarce,
    #          quality-critical model — a wrong join here is a wrong number. Kept
    #          free of the cheap calls so its whole batch is available for SQL.
    #      qwen4-deploy (Qwen3-4B-Instruct)   : scheme + intent + entity classification
    #          (CLASSIFIER_MODEL) AND the SQL semantic verifier (SQL_VERIFY_MODEL) —
    #          two distinct roles sharing one small deployment. Cheap pattern/format
    #          tasks with guided-JSON decoding; keeps them off the 9B and the 30B.
    #      qwen35-9b    (qwen3.5-9b)          : final answer composition only
    #          (RESPONSE_MODEL). Freed from classify duty so composition never
    #          queues behind the classify/entity/follow-up calls.
    #      qwen3-embedding / qwen3-reranker   : RAG (scheme-knowledge) path.
    #      qwen3-asr                          : voice input transcription.
    #    Classifier handoff from the 9B to the 4B done 2026-09-10 (Task 6 in
    #    docs/INFERENCE_REQUIREMENTS.md), once qwen4-deploy was confirmed reachable
    #    via SQL_VERIFY_ENABLED. Watch qwen4-deploy queue depth — it now carries
    #    both roles — and validate classify accuracy against the old 9B baseline
    #    on ambiguous queries (abbreviations, cross-scheme, follow-ups).
    AI_MODEL_CA_BUNDLE_PATH: str = ""  # certs/enlight-aiops-internal-ca.pem, if verification is required

    # Classify / intent / entity-extract — on the dedicated 4B, NOT the 9B or the
    # 30B, so these frequent small calls never queue behind SQL generation or
    # composition, and composition never queues behind them either.
    CLASSIFIER_MODEL: str = "qwen4-deploy"
    CLASSIFIER_BASE_URL: str = "https://10.48.242.4/openai/v1"
    CLASSIFIER_API_KEY: str = ""
    CLASSIFIER_TIMEOUT_SECONDS: int = 30
    CLASSIFIER_TEMPERATURE: float = 0.0

    # SQL generation — the 30B coder, and only this. Do not move other roles here.
    SQL_GENERATION_MODEL: str = "qwen-model"
    SQL_GENERATION_BASE_URL: str = "https://10.48.242.4/openai/v1"
    SQL_GENERATION_API_KEY: str = ""
    SQL_GENERATION_TIMEOUT_SECONDS: int = 30
    SQL_GENERATION_TEMPERATURE: float = 0.0
    # Repair attempts on a validation/execution failure. Was 1: a first repair
    # that fixed one mistake but tripped a second (ambiguous column -> fixed
    # with a needless dim join -> join validator) ended in "couldn't build a
    # working query" (2026-09-23 KPI sweep). Costs latency only on failures.
    SQL_GENERATION_MAX_RETRIES: int = 2

    # qwen35-9b — final natural-language answer composition only. Classify/intent/
    # entity-extract moved to qwen4-deploy (see CLASSIFIER_MODEL above) on
    # 2026-09-10, so this deployment now serves only this role.
    RESPONSE_MODEL: str = "qwen35-9b"
    RESPONSE_MODEL_BASE_URL: str = "https://10.48.242.4/openai/v1"
    RESPONSE_MODEL_API_KEY: str = ""
    RESPONSE_TEMPERATURE: float = 0.0
    RESPONSE_MAX_TOKENS: int = 800
    RESPONSE_TIMEOUT_SECONDS: int = 20

    # ── SQL semantic verifier — qwen3-4b (docs/INFERENCE_REQUIREMENTS.md Task 6) ──
    # Runs after generate_sql, before the query touches the database: a second
    # opinion asking "does this SQL actually answer the question, per the schema
    # rules and resolved entities above it?" (see prompt_builder.build_verify_prompt).
    # The regex guards already in execute_with_repair only catch SQL shapes a past
    # bug taught them to recognise (bare row read on an aggregate question,
    # village-name-instead-of-code, a phantom 'Meghalaya' filter, ...). This
    # catches the same CLASS of bug — syntactically valid, executes cleanly,
    # answers the wrong question — in a shape nobody has hand-coded a guard for
    # yet. A flagged query raises straight into the existing repair loop; no new
    # control flow needed for that part.
    # Best-effort: any failure (model not deployed, timeout, unparseable JSON)
    # degrades to "no issue found" — a verifier outage must never block an
    # answer that would otherwise have worked.
    # Deployed 2026-09-10 as served model name "qwen4-deploy" (not the "qwen3-4b"
    # name docs/INFERENCE_REQUIREMENTS.md Task 6 originally planned) — vLLM
    # runtime, confirmed reachable on /openai/v1. Verified working end to end.
    # SQL_VERIFY_MODEL and CLASSIFIER_MODEL now both point at this same
    # qwen4-deploy deployment — a distinct role each (verify runs once per SQL
    # generation; classify runs several times per turn), sharing one small model
    # rather than each getting its own GPU allocation.
    SQL_VERIFY_ENABLED: bool = True
    SQL_VERIFY_MODEL: str = "qwen4-deploy"
    SQL_VERIFY_BASE_URL: str = "https://10.48.242.4/openai/v1"
    SQL_VERIFY_API_KEY: str = ""
    SQL_VERIFY_TEMPERATURE: float = 0.0
    SQL_VERIFY_TIMEOUT_SECONDS: int = 15

    # KB chunk + query embeddings for the RAG path, and the semantic cache.
    # "local"  -> fastembed CPU model (LOCAL_EMBEDDING_MODEL), no gateway call.
    # "gateway" -> EMBEDDING_MODEL on the OpenAI-compatible gateway.
    # The gateway currently has no embedding model deployed, so "local" is the
    # working default; switch to "gateway" once qwen3-embedding is up.
    EMBEDDING_PROVIDER: str = "local"
    LOCAL_EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"  # 384-dim, ONNX, ~130 MB
    EMBEDDING_MODEL: str = "qwen3-embedding"
    EMBEDDING_BASE_URL: str = "https://10.48.242.4/openai/v1"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_TIMEOUT_SECONDS: int = 30
    EMBED_BATCH_SIZE: int = 32

    # ── Entity resolver — stage 7 embedding fallback (district/block/year/AC
    # closed-set catalogues only; see app/nlu/entity_resolver.py) ──
    # Kill switch: loading the catalogue vectors at startup is best-effort
    # already (app/main.py wraps it in _try), but this lets the stage be
    # disabled outright without touching REDIS_URL/LOCAL_EMBEDDING_MODEL,
    # which other features (semantic cache, RAG) also depend on.
    ENTITY_RESOLVER_EMBEDDING_ENABLED: bool = True
    ENTITY_RESOLVER_EMBEDDING_ACCEPT: float = 0.88   # cosine; matches the resolver YAML's stage 7 spec
    # A cold box downloads the ~130 MB ONNX model from HuggingFace on first
    # use; on a box with restricted egress that HTTP call can hang rather
    # than fail fast, which would otherwise stall startup indefinitely (the
    # one best-effort step, of all of them, actually capable of doing that).
    ENTITY_RESOLVER_EMBEDDING_LOAD_TIMEOUT_SECONDS: float = 90.0
    # Stage 6b — fuzzy match on squashed names (spaces stripped) for typos that
    # merge/split words ("westgaro hils", "rigbhoi"), which stage 6's
    # token_set_ratio and stage 7's embeddings both miss. Same accept
    # threshold / runner-up gap / blocked pairs as stage 6, and only runs after
    # stage 6 declined. OFF by default: the resolver is shared with the live
    # pipeline, so turning this on changes live answers, not just the shadow
    # QueryFrame — enable after the eval shows it is safe.
    ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED: bool = False

    # ── Entity resolver — resolve_village Redis cache (optional, best-effort) ──
    # Villages are the one dimension resolved via a live Postgres query on
    # every call (curated.dim_geography has no in-memory catalogue — see
    # entity_resolver.py's module docstring). Reuses REDIS_URL/the same
    # degrade-silently posture as app/caching/cache.py; a short TTL because
    # dim_geography can be corrected by a re-ingest at any time.
    VILLAGE_CACHE_TTL_SECONDS: float = 600.0

    # qwen3-reranker — reorders the pgvector candidate set before answer
    # composition. Split into two independent flags (previously one shared
    # RERANKER_ENABLED) once live re-investigation (2026-09-14, see
    # openspec/changes/rag-knowledge-base-verification and
    # schema-retrieval-reranking proposal.md "Reranker investigation"
    # addenda) found the two corpora do NOT behave the same way — a single
    # flag could not represent "on for one, off for the other" at all.
    #
    # RAG_RERANKER_ENABLED: OFF by default. The original 2026-08-29 failure
    # ("where to find info" outranks "application process" for a "what
    # documents" query) was re-tested per scheme on 2026-09-14: it no longer
    # reproduces for PMAY-G, MGNREGA, or Focus Plus (reranked top-1 is the
    # correct "documents required" chunk in all three) but DOES still
    # reproduce, close to verbatim, for CM Elevate ("14. Where to Find
    # Authoritative, Current Information" beats "7.1 Required Documents").
    # Mixed, corpus-inconsistent evidence — not a clean "fixed" story — so
    # this stays OFF pending a real decision by whoever owns the tradeoff,
    # not flipped on 4-5 queries with one known-reproducing failure among
    # them.
    RAG_RERANKER_ENABLED: bool = False
    # SCHEMA_RETRIEVAL_RERANKER_ENABLED: OFF by default, backed by a
    # dedicated 2026-09-14 investigation (5 real schema-metadata queries
    # across all 4 piloted schemes): 0/5 reranked top-1 picks agreed with
    # cosine order, including two clear degradations (demoted the
    # exact-match `data_verified` column below a generic dimension table;
    # demoted the correct fact table to dead last behind a near-irrelevant
    # status-key column). This is a real, repeatable finding for this
    # content type, not unverified caution.
    SCHEMA_RETRIEVAL_RERANKER_ENABLED: bool = False
    RERANKER_MODEL: str = "qwen3-reranker"
    RERANKER_BASE_URL: str = "https://10.48.242.4/openai/v1"
    RERANKER_API_KEY: str = ""
    RERANKER_TIMEOUT_SECONDS: int = 30

    # qwen3-asr — voice input transcription for /api/query/transcribe
    ASR_MODEL: str = "qwen3-asr"
    ASR_BASE_URL: str = "https://10.48.242.4/openai/v1"
    ASR_API_KEY: str = ""
    ASR_TIMEOUT_SECONDS: int = 60

    # ── Vector store (PostgreSQL + pgvector, Neon) — scheme-knowledge base ──
    # Dedicated Postgres instance (pgvector extension) for RAG storage — kept
    # separate from DATABASE_URL/megh_db so KB ingest and conversation-memory
    # writes never need anything beyond the read-only megh_readonly role that
    # DATABASE_URL uses in production. Falls back to DATABASE_URL if blank.
    VECTOR_DB_URL: str = ""
    RAG_KB_TABLE: str = "megh_scheme_kb"
    # Thresholds are on the bge-small (local) cosine scale: loosely-related
    # chunks score ~0.66-0.78, so HIGH sits above that — otherwise every
    # knowledge question clears it and returns its nearest chunk verbatim
    # instead of composing. MEDIUM is the real working tier for this KB.
    RAG_TOP_K: int = 12            # candidates pulled from pgvector
    RAG_RERANK_TOP_N: int = 8      # chunks handed to the composer as context
    RAG_MIN_SCORE: float = 0.30    # floor on the chunk score
    RAG_HIGH_CONFIDENCE: float = 0.84   # >= this: return top chunk verbatim (rare, near-exact match)
    RAG_MEDIUM_CONFIDENCE: float = 0.55  # >= this: compose an answer from the kept chunks

    # ── Vector store — schema metadata / SQL examples (Phase 3) ──
    # Two more dedicated pgvector tables on the same VECTOR_DB_URL instance,
    # following megh_scheme_kb's one-table-per-collection pattern rather than a
    # kind-discriminated shared table (see openspec/changes/
    # phase-3-schema-retrieval-join-discovery/design.md).
    RAG_SCHEMA_METADATA_TABLE: str = "megh_schema_metadata"
    RAG_SQL_EXAMPLES_TABLE: str = "megh_sql_examples"
    # §5.10 SQL-generation few-shot retrieval — examples pulled from
    # megh_sql_examples by cosine match, scheme-prefiltered, no reranking
    # stage (unlike §5.8, the spec doesn't call for one here). No dedicated
    # enable flag: app/sql/sql_examples_retrieval.py degrades to [] (falling
    # back to app/knowledge/annotations.py's token-overlap ranking) exactly the way
    # schema_retrieval.retrieve() does when its own table is unseeded —
    # same "always attempted, safely degrades" posture, not a new knob.
    SQL_EXAMPLES_TOP_K: int = 5
    # §5.8 two-stage retrieve/rerank: pull CANDIDATE_K from pgvector, then
    # (when SCHEMA_RETRIEVAL_RERANKER_ENABLED) rerank down to TOP_K. TOP_K is
    # also the plain truncation point when reranking is off.
    SCHEMA_RETRIEVAL_CANDIDATE_K: int = 30
    SCHEMA_RETRIEVAL_TOP_K: int = 8
    # §5.9/§5.11 — "tables must belong to the retrieved set" (proposal §5.11,
    # baseline-audit.md cross-cutting finding 11, distinct from the join-graph
    # rule sql_join_validator.py already enforces). Scoped to FACT tables only
    # and only fires when schema_retrieval itself surfaced a fact-table
    # candidate this query — a scheme with no retrieval coverage yet
    # (MGNREGA, PMAY-G as of Phase 3) has no retrieved set to check against,
    # so this is a true no-op for them, same "additive, never gating for an
    # un-indexed scheme" posture as schema_retrieval.py itself.
    RETRIEVED_SET_GUARD_ENABLED: bool = True

    # ── Multi-turn / follow-up context ──
    # Per-worker, in-process, TTL'd. A short-lived store of the last few turns of
    # a chat so "what about East Garo Hills?" can be rewritten to a standalone
    # question. Lost on restart; not shared across workers — same stance as the
    # response caches.
    SESSION_TTL_SECONDS: int = 1800          # 30 min sliding window
    SESSION_MAX: int = 5000                   # sessions kept before oldest-first eviction
    SESSION_MAX_TURNS: int = 8                # turns retained per session
    FOLLOWUP_REWRITE_ENABLED: bool = True     # one classifier call when a turn looks like a follow-up
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
    # Silently fill a missing detail from the SME-authored *_default_rules.yaml
    # files (e.g. no currency unit stated -> assume crore) and disclose it as a
    # note, instead of asking. Only conditions with no overlapping hardcoded
    # `_needs_*_clarification` predicate are ever defaulted — see
    # app/nlu/defaults_engine.py's collision set. Deterministic, no model call.
    # Off => no silent defaults; the pre-existing ask/no-ask behavior is
    # unchanged either way, since colliding conditions never reach this flag.
    DEFAULTS_ENGINE_ENABLED: bool = True
    # Pause and ask, using the SME-authored *_classification_rules.yaml
    # question text, when a question requests something the underlying data
    # genuinely does not hold (node 5.3, Phase 1: only the "source cannot
    # answer this at all" conditions — see app/nlu/clarification_engine.py).
    # Only conditions with no overlapping hardcoded `_needs_*_clarification`/
    # `_*_clarification` predicate are ever matched — see
    # app/nlu/clarification_engine.py's collision set. Deterministic, no model
    # call. Off => no engine-driven pause; the pre-existing ask/no-ask
    # behavior from the hardcoded predicates is unchanged either way, since
    # colliding conditions never reach this flag.
    CLARIFICATION_ENGINE_ENABLED: bool = True
    # Compute structured findings (empty result, extremes, ties, large result
    # set, SME threshold breach, stale-data note) over a query result and
    # attach them as the additive `findings` field in the /api/query response.
    # Deterministic, no model call — see app/response/findings.py. Off => `findings` is
    # always an empty list; no change to `answer`, `rows`, or `data`.
    FINDINGS_ENABLED: bool = True
    # A result with more rows than this trips the large-result-set finding.
    # Purely informational (nothing is truncated because of it — `rows`/`data`
    # keep their own separate caps).
    FINDINGS_LARGE_RESULT_ROWS: int = 100
    # Compute a chart_type string (bar/doughnut/line/grouped_bar/stacked/
    # kpi_bar, or null) over a query result and attach it as the additive
    # `chart_type` field in the /api/query response. Deterministic, no
    # model call — see app/response/chart_spec.py. web/ai_query.html's
    # buildAnalytics() already reads this field and already implements
    # rendering for all six values. Off => `chart_type` is always null;
    # no change to `answer`, `rows`, or `data`.
    CHART_SPEC_ENABLED: bool = True
    # node 5.2 query analyzer — the structured `analysis` field in the
    # /api/query response (query_type/metric/entities/time_scope/granularity/
    # ambiguous/intent_summary). See app/nlu/query_analyzer.py. Off => `analysis`
    # is always omitted; no change to `answer`, `rows`, or `data`.
    QUERY_ANALYZER_ENABLED: bool = True
    # Understand node (app/nlu/understand.py) — one guided-JSON model call per
    # message producing a structured QueryFrame (rewritten question, intent,
    # schemes, metric, geo mentions as typed, year, tranche, query type, ...).
    # SHADOW mode: the frame is computed in parallel with the normal pipeline
    # and written to the audit record (JSONL `understand_frame`) only — it
    # changes NO routing, gate, SQL or answer. Off => no model call at all.
    UNDERSTAND_SHADOW: bool = False
    # Pinned explicitly, NOT inherited from CLASSIFIER_MODEL (which the live
    # .env overrides to qwen35-9b): the plan assigns understanding to qwen4-deploy.
    # The gateway routes models by API key: the classifier key cannot reach
    # qwen4-deploy (404), the SQL verifier's key can (it runs on qwen4-deploy
    # too). Empty => use SQL_VERIFY_BASE_URL / SQL_VERIFY_API_KEY.
    UNDERSTAND_MODEL: str = "qwen4-deploy"
    UNDERSTAND_BASE_URL: str = ""
    UNDERSTAND_API_KEY: str = ""
    UNDERSTAND_TIMEOUT_SECONDS: float = 15.0
    UNDERSTAND_MAX_TOKENS: int = 600
    UNDERSTAND_HISTORY_TURNS: int = 3   # most recent session turns shown to the model
    # Frame-driven clarification gates (app/nlu/clarify_rules.py). On =>
    # every message's QueryFrame is computed BEFORE the pipeline runs (not in
    # the background), and _answer_data and the LangGraph nodes decide what to
    # ask — and which scheme defaults to apply, with a disclosed assumption —
    # from the frame instead of the _needs_{scheme,topn,scope,year,tranche}_
    # clarification regexes. A turn whose frame fails falls back to the old
    # predicates. Off => behaviour identical to before this flag existed.
    FRAME_GATES_ENABLED: bool = False
    # Stop and say "I only have data for FY 2022-23 to FY 2025-26" when a data
    # question names a financial year outside that window — a bare "1999-20",
    # "2010", "FY 2019-20", etc. Both schemes' year coverage is exactly those
    # four years. Off => keep the old behaviour (add a soft note, then fall
    # through to the "which year?" pause or answer across the years that exist).
    YEAR_RANGE_GUARD_ENABLED: bool = True
    # Route the resumable clarification pauses
    # (pipeline.RESUMABLE_CLARIFICATION_RULES) through app/orchestration/langgraph_followup.py's
    # LangGraph interrupt()/AsyncSqliteSaver checkpointer instead of the
    # bespoke ClarificationNeeded + ConversationState.pending_scope_q/
    # pending_village_hint mechanism — see
    # openspec/changes/phase-2-orchestration-durability/design.md. Off
    # (default) => /api/query behavior is byte-for-byte unchanged, the
    # bespoke mechanism handles every pause exactly as it always has. On =>
    # those rules pause/resume via the LangGraph component instead; a
    # non-resumable (terminal) ClarificationNeeded still propagates and is
    # handled the same way either way.
    LANGGRAPH_FOLLOWUP_ENABLED: bool = False
    # openspec/changes/langgraph-full-pipeline-rewrite +
    # multi-tenant-rls-scheme-scaleout: a full node-decomposed LangGraph
    # StateGraph (app/orchestration/pipeline_graph.py) covering all 15 §5 nodes — the
    # architecture the Grant Thornton proposal's Section 4 actually
    # specifies ("the runtime pipeline is implemented as a LangGraph
    # agent"). Wired into the real request path as of 2026-09-15: On =>
    # app/orchestration/pipeline.py::_run_pipeline calls
    # pipeline_graph.answer_data_via_graph_compat instead of
    # app.orchestration.pipeline._answer_data for the DATA route's SQL-generation chain
    # (everything else — edge cases, RAG routing, scheme-listing —
    # unchanged either way). Off (default) => byte-for-byte the same as
    # before this flag existed; the graph path has been tested with mocked
    # LLM/DB fixtures (see langgraph-full-pipeline-rewrite/tasks.md) and
    # against a disposable local Postgres for its checkpointer, but NOT
    # against a live LLM + live production data across all 4 schemes —
    # that end-to-end parity check is the remaining gate before flipping
    # this to True in any real deployment.
    PIPELINE_GRAPH_ENABLED: bool = False
    # Staged rollout: when PIPELINE_GRAPH_ENABLED is False, route this
    # percentage (0-100) of sessions to the graph path instead of the bespoke
    # one — a canary bucketed by user_id when the caller is a real logged-in
    # user (so the SAME user always lands in the same bucket across every
    # session/device/conversation, not just within one thread), falling back
    # to session_id for an anonymous caller with no user_id. Corrected
    # 2026-09-17: this comment previously said the opposite priority
    # (session_id first, user_id fallback) — app/orchestration/pipeline.py::
    # _pipeline_graph_selected's own docstring and actual code always did
    # user_id-first; only this comment was wrong. Not a per-request coin
    # flip either way. Ignored (treated as 100) once
    # PIPELINE_GRAPH_ENABLED is True. Default 0 => today's exact behavior.
    # multi-tenant-rls-scheme-scaleout/tasks.md 5.2: no prior in-app canary
    # mechanism exists in this codebase to mirror (LANGGRAPH_FOLLOWUP_ENABLED
    # is also a single global bool) — that task's "mirrors
    # phase-2-orchestration-durability's validated approach" claim didn't
    # hold up on re-verification; this is new, not a port of existing code.
    PIPELINE_GRAPH_CANARY_PERCENT: int = 0
    # Checkpointer backend for app/orchestration/pipeline_graph.py. Empty (default) => the
    # local-file AsyncSqliteSaver (app/logs/pipeline_graph_checkpoints.sqlite),
    # matching app/orchestration/langgraph_followup.py's own default. Set to a Postgres DSN
    # (postgresql://...) to use langgraph.checkpoint.postgres.aio.
    # AsyncPostgresSaver instead — the production-shape backend design.md
    # calls for, now installable via the `psycopg[binary]` wheel (bundles
    # libpq, unlike the plain `psycopg` package that was blocked in this
    # environment). Deliberately NOT the same variable as DATABASE_URL: this
    # is a separate, optional checkpoint store, not the application database.
    PIPELINE_GRAPH_CHECKPOINTER_DSN: str = ""

    # ── Authorization (role + scope vs. what the query asks for) ──
    # Checks are pure Python (backend/auth.py). Users, tenants, conversations and
    # the audit trail live in the `app` schema of megh_db (created at startup).
    AUTH_ENABLED: bool = True
    # Multi-tenant: every user belongs to a department/directorate (a tenant).
    # tenant_admin manages their own tenant; super_admin manages all of them.
    MULTITENANCY_ENABLED: bool = True
    DEFAULT_TENANT_CODE: str = "RD"           # Rural Development — seeded at startup
    DEFAULT_TENANT_NAME: str = "Rural Development Department"
    # openspec/changes/multi-tenant-rls-scheme-scaleout: DB-enforced tenant
    # isolation extended to the curated scheme-data warehouse via Postgres
    # RLS, backed by a real tenant<->scheme grant table (app.tenant_schemes)
    # that replaces ROLE_PERMISSIONS' hardcoded scheme allowlists as the
    # actual entitlement source (app/core/auth.py::scope_from_user). Off
    # (default) => zero behavior change: no session GUC is set
    # (app/database/db.py::set_tenant_context becomes a no-op), scope_from_user
    # ignores tenant grants entirely, and the RLS migration itself
    # (deploy/sql/03_tenant_scheme_rls.sql) must not be applied — flag-off
    # is meant to mean "this mechanism doesn't exist yet", not "exists but
    # never satisfied" (the latter would deny every row under RLS instead
    # of preserving today's behavior).
    TENANT_SCHEME_RLS_ENABLED: bool = False

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
    USERS_FILE: str = "config/users.yaml"
    # Mirror of the DB audit trail; keep for grep/offline. DB is source of truth.
    AUDIT_FILE: str = "logs/query_audit.jsonl"
    # Rows kept in the compliance audit trail's result_preview field — deliberately
    # smaller than the UI's 200-row `data` cap (pipeline.py) so the durable
    # app.query_audit table stays lean; see openspec/changes/
    # phase-2-audit-trail-enrichment/design.md for the tradeoff.
    AUDIT_RESULT_PREVIEW_ROWS: int = 20
    # Role when AUTH_ENABLED=false (local dev only — real requests carry a JWT).
    AUTH_DEFAULT_ROLE: str = "analyst"

    # Live schema catalog (semantic.* in megh_db) folded into the SQL prompt.
    SCHEMA_CATALOG_ENABLED: bool = True

    # ── Conversation context layer (ChatGPT-style multi-turn state) ──
    # Sits around the existing follow-up rewrite (looks_like_followup /
    # rewrite_followup) and prior_resolved entity carry — it does not replace
    # them. See app/conversation/context_manager.py. Everything here degrades to the
    # pre-existing behaviour when disabled or on any failure.
    CONTEXT_LAYER_ENABLED: bool = True
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
    # Semantic memory: relevant-older-turn retrieval over a dedicated pgvector
    # table (separate from the scheme-KB table AND from the semantic response
    # cache — see app/conversation/conversation_memory.py). Reuses the existing pgvector
    # pool + embedding pipeline. Off, or any pgvector failure, falls back to
    # PostgreSQL recent history / in-session turns only.
    CONTEXT_SEMANTIC_MEMORY_ENABLED: bool = True
    CONTEXT_MEMORY_TABLE: str = "megh_conversation_memory"
    CONTEXT_MEMORY_MIN_SCORE: float = 0.55
    CONTEXT_MEMORY_TOP_K: int = 5
    # Only reach for semantic memory when the in-process session has fewer than
    # this many turns of its own (i.e. a resumed/long conversation past the
    # in-memory window) — keeps the common case (recent turn already in
    # session_store) free of an extra embed + pgvector round trip.
    CONTEXT_MEMORY_MIN_SESSION_TURNS: int = 2

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
    return problems

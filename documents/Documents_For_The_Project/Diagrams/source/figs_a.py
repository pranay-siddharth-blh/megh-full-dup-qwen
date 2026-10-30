"""Figures 01-05 and 17-20 (architecture / pipeline / new v2.0 figures)."""
from figlib import Fig, FAM

ORANGE = "#C2410C"
SLATE = "#334155"


def fig01():
    f = Fig(1380, 860, "", "")
    f.parts = []

    def tier(y, h, title):
        f.raw(f'<div style="position:absolute;left:10px;top:{y}px;width:1360px;height:{h}px;border:2px solid #1F2937;border-radius:6px"></div>')
        f.raw(f'<div class="txt" style="left:34px;top:{y+12}px;font-size:23px;font-weight:700;color:#0F172A">{title}</div>')

    tier(10, 165, "Presentation Tier — Government of Meghalaya officers (web browser, phone, tablet)")
    for i, (t, s) in enumerate([("State / District / Block Officer", "React chat console · /megh-chat"),
                                ("Analyst", "React chat console · /megh-chat"),
                                ("Administrator", "Admin console · /admin-ui")]):
        f.box(90 + i * 410, 62, 350, 88, "blue", t, s, ts=17, ss=13.5, fill="#DCE8F8", bw=1.5)
    f.arrow([(690, 182), (690, 238)], "#111827", both=True)
    f.text(712, 196, 640, "HTTPS (nginx: TLS · WAF · rate limits) · answers stream back as Server-Sent Events", 14.5, "#0F172A")
    tier(245, 330, "Application Tier — FastAPI service (Uvicorn, 2 workers per VM, port 8401)")
    cells = [("Authentication &amp;", "Role-Based Access"), ("Conversation &amp;", "Context Layer"),
             ("LangGraph Pipeline", "22 nodes · app/pipeline package"), ("NL → SQL Generation,", "Guards &amp; Repair"),
             ("Knowledge Answers", "RAG + always-on re-ranker"), ("Answer Composition", "&amp; Number Checks"),
             ("Chat History, Feedback", "&amp; Audit Trail"), ("Admin Console API", "&amp; Monitoring")]
    for i, (a, b) in enumerate(cells):
        x = 60 + (i % 4) * 318
        y = 300 + (i // 4) * 132
        f.box(x, y, 290, 104, "green", a, b, ts=16, ss=14.5, fill="#E3F0E3", bw=1.5)
    f.arrow([(470, 582), (470, 640)], "#111827", both=True)
    f.arrow([(1000, 582), (1000, 640)], "#111827", both=True)
    tier(648, 202, "Data, Knowledge and Model Tier")
    for i, (t, s) in enumerate([("PostgreSQL 18 — megh_db", "curated scheme data (read-only logins)<br>app schema: users, chats, audit, feedback"),
                                ("Qdrant Vector Store", "megh_knowledge (scheme documents)<br>megh_sql_metadata · both read-only"),
                                ("vLLM Model Gateway", "Qwen3-Coder 30B · Qwen3 4B · Qwen3.5 9B<br>qwen3-embedding · qwen3-reranker · ASR")]):
        f.box(60 + i * 430, 700, 400, 128, "purple", t, s, ts=17, ss=13.5, fill="#E9E3F3", bw=1.5)
    return f


def fig02():
    W = 1100
    f = Fig(W, 1390, "Megh One AI — Deployment Architecture",
            "Two application VMs · nginx + Uvicorn on each · shared PostgreSQL, Qdrant and model gateway on 10.48.242.4", banner=True)
    f.box(300, 100, 500, 62, "white", "Government Officer / Administrator", "uses the system from an office browser (desktop, tablet or phone)", fill="#EEF2FF", ts=16)
    f.arrow([(550, 162), (550, 205)], "#1E40AF", label="opens /megh-chat", lpos=(620, 184))
    f.box(280, 207, 540, 62, "white", "Web Browser — React chat console", "/megh-chat (chat) · /admin-ui (admin) · sign-in with username and password", ts=16)
    f.arrow([(550, 269), (550, 312)], "#1E40AF", label="HTTPS request", lpos=(610, 290))
    f.box(260, 314, 580, 62, "grey", "nginx — TLS 1.2/1.3 · ModSecurity WAF · rate limits", "one on each VM · proxies to 127.0.0.1:8401 · /api/query/stream unbuffered", ts=16)
    f.arrow([(550, 376), (550, 418)], "#1E40AF")
    f.box(260, 420, 580, 62, "green", "Uvicorn — app.main:app (port 8401, 2 workers)", "systemd service megh-nlpservice on each of the 2 Ubuntu VMs", ts=16)
    f.arrow([(550, 482), (550, 524)], "#1E40AF")
    f.grp(50, 526, 1000, 560, "FastAPI application — what happens inside", "#0F172A")
    f.box(80, 566, 940, 56, "blue", "1 · Security checks", "security headers · 256 KB body cap · per-IP rate limit · JWT verified (12-hour token) · guardrails", fill="#DBEAFE", ts=16)
    f.text(80, 634, 600, "<b>2 · The request goes to one of these modules:</b>", 14, "#0F172A")
    mods = [("Ask a Question", "POST /api/query and /stream<br>answers stream back (SSE)"),
            ("Voice Input", "POST /api/query/transcribe<br>speech → question text (ASR)"),
            ("Conversation Layer", "8-hour memory · topics · reset<br>multi-part questions · translation"),
            ("LangGraph Pipeline", "22 nodes over app/pipeline:<br>route, scheme, places, SQL, checks"),
            ("Knowledge Answers", "megh_knowledge + qwen3-reranker<br>grounded answer with sources"),
            ("Chat History &amp; Feedback", "list · rename · pin · archive · delete<br>👍 / 👎 on every answer"),
            ("Sign-in &amp; Accounts", "login · logout · my profile<br>first super-admin bootstrap"),
            ("Admin Console API", "tenants · users · logins · audit<br>conversations · feedback · schema"),
            ("Health, Metrics &amp; Cards", "/health · /metrics (accuracy, guardrail)<br>/api/scheme-stats live figures")]
    for i, (t, s) in enumerate(mods):
        x = 80 + (i % 3) * 318
        y = 662 + (i // 3) * 112
        f.box(x, y, 302, 98, "blue", t, s, fill="#F0F6FF", ts=16, ss=12.8, bw=1.5)
    f.box(80, 1004, 940, 58, "blue", "3 · Answer sent back", "draft text streams while it is written; the checked answer, rows, chart data, SQL and sources arrive last", fill="#DBEAFE", ts=16)
    for x, lab in ((270, "SQL (asyncpg)"), (550, "model calls (httpx)"), (830, "vector search")):
        f.arrow([(x, 1086), (x, 1138)], "#1E40AF", label=lab, lpos=(x + 70, 1112))
    f.box(40, 1140, 330, 120, "purple", "PostgreSQL 18 — megh_db", "curated data via megh_readonly and<br>megh_chatbot (semantic.run_query)<br>app schema via megh_app", ts=16, ss=12.8)
    f.box(385, 1140, 330, 120, "gold", "vLLM Model Gateway", "SQL + verifier 30B · router / guardrail 4B<br>composer / rewrite 9B · embedding<br>re-ranker · ASR (self-hosted)", ts=16, ss=12.8)
    f.box(730, 1140, 330, 120, "teal", "Qdrant 10.48.242.4:6333", "megh_knowledge · megh_sql_metadata<br>read-only to the app<br>1024-dim gateway embeddings", ts=16, ss=12.8)
    f.raw('<div style="position:absolute;left:0;top:1284px;width:1100px;height:106px;background:#F1F5F9"></div>')
    f.text(0, 1302, 1100, "<b>Each VM runs the same stack. Conversation state is saved in PostgreSQL, so either VM can continue a chat.</b>", 14.5, "#1F2937", "center")
    f.text(0, 1336, 1100, "Start order: PostgreSQL, gateway and Qdrant reachable → systemctl start megh-nlpservice → nginx → open https://&lt;host&gt;/megh-chat → sign in", 13.5, "#475569", "center")
    return f


def fig03():
    W = 1180
    f = Fig(W, 1400, "Megh One AI — Technical Architecture", "How one question technically flows through the code — steps 1 to 9", banner=True)
    f.box(250, 100, 680, 82, "white", "Web Browser (React 18 client, Vite build)", "web/app bundles · Chart.js 4.4.1 charts · JWT kept in localStorage<br>Authorization: Bearer &lt;token&gt; on every API call · SSE reader", ts=16, ss=12.8)
    f.arrow([(590, 182), (590, 232)], "#1E40AF", label="1 · HTTPS → nginx → 127.0.0.1:8401", lpos=(720, 207), lcol="#1E40AF")
    f.box(290, 234, 600, 64, "green", "Uvicorn — ASGI server (port 8401)", "Python 3.11 · FastAPI app.main:app · 2 workers per VM", ts=16, fill="#DCFCE7")
    f.arrow([(590, 298), (590, 348)], "#1E40AF", label="2 · middleware: security headers · 256 KB body cap · per-IP rate limit", lpos=(800, 323), lcol="#1E40AF")
    f.grp(40, 350, 1100, 580, "FastAPI application (app/)", "#0F172A")
    f.box(70, 392, 1040, 58, "blue", "3 · Auth check — app/deps.py + app/security.py + app/auth.py", "HS256 JWT verified (issuer, expiry) → UserScope: role · tenant · districts · blocks · schemes · granularity cap", fill="#DBEAFE", ts=16)
    f.text(70, 460, 900, "<b>4 · Request routed to the matching router (app/routers/)</b>", 14, "#0F172A")
    rs = [("query.py", "ask · stream · transcribe"), ("auth.py", "login · logout · me"), ("history.py", "own chats"),
          ("rag.py", "KB status"), ("feedback.py", "👍 / 👎 votes"), ("stats.py", "scheme cards"), ("admin.py", "admin API")]
    for i, (t, s) in enumerate(rs):
        f.box(70 + i * 149, 486, 140, 54, "blue", t, s, fill="#F0F6FF", ts=14.5, ss=11.5, bw=1.5)
    f.text(70, 552, 900, "<b>5 · Conversation layer and answer caches</b>", 14, "#0F172A")
    for i, (t, s) in enumerate([("conversation_layer.py", "8 h idle expiry · reset · topic return · multi-part"),
                                ("session_sync.py + topic_memory.py", "state from app.conversations (rev-guarded) · 8 topics"),
                                ("cache.py + semantic_cache.py", "exact · cosine ≥ 0.93 · 15 min")]):
        f.box(70 + i * 350, 578, 340, 58, "gold", t, s, ts=14.5, ss=11.8)
    f.text(70, 648, 1040, "<b>6 · LangGraph orchestrator — pipeline_graph.py (22 nodes) calls the stage functions in app/pipeline/ (common c01–c17 + one file per scheme)</b>", 14, "#0F172A")
    for i, (t, s) in enumerate([("edge + guardrails", "rules · 4B safety check"), ("entity_resolver + spelling", "district · block · village · AC"),
                                ("prompt_builder + data_facts", "rules · live figures · examples"), ("sql_guard + auth.authorize", "SQLGlot · privacy · scope"),
                                ("rag.py", "megh_knowledge + re-ranker")]):
        f.box(70 + i * 210, 676, 200, 64, "gold", t, s, ts=13.8, ss=11.5)
    f.box(70, 760, 1040, 64, "blue", "7 · Answer composed and checked — compose_response + per-scheme guarantees", "every number must be in the rows · figure-to-label check · one money formatter · chart hint · follow-up chips · SSE: step → token → done", fill="#DBEAFE", ts=16)
    f.text(70, 838, 1040, "Every turn: question, answer and SQL saved to app.conversation_turns; audit row with the run trace to app.query_audit; state to app.conversations (context_state); paused runs to app.checkpoint*", 12.8, "#475569")
    f.text(70, 880, 1040, "Background tasks: data_facts refresh (10 min) · schema, metric catalogue and scheme years (30 min) · pause sweep (10 min) · conversation purge (daily)", 12.8, "#475569")
    f.arrow([(1110, 792), (1160, 792), (1160, 140), (932, 140)], "#16A34A", dash=True, label="9 · SSE events / JSON answer", lpos=(1040, 120), lcol="#15803D")
    f.arrow([(590, 930), (590, 976)], "#1E40AF", label="8 · database, model and vector calls", lpos=(720, 953), lcol="#1E40AF")
    f.grp(40, 978, 1100, 168, "AI and data access layer", "#0F172A")
    for i, (t, s) in enumerate([("llm.py", "one httpx client · 24-slot gate<br>model roles · CA bundle · streaming"),
                                ("db.py + sql_guard.py", "3 pools: megh_app · megh_readonly · megh_chatbot<br>run_readonly() → semantic.run_query"),
                                ("vectorstore.py", "qdrant-client · gateway embeddings<br>read-only collections")]):
        f.box(70 + i * 350, 1022, 340, 100, "purple", t, s, ts=15.5, ss=12.3)
    for x, lab in ((240, "HTTPS · OpenAI API"), (590, "SQL · TCP 5432"), (940, "HTTP · 6333")):
        f.arrow([(x, 1146), (x, 1190)], "#1E40AF", label=lab, lpos=(x + 75, 1168), lcol="#1E40AF")
    f.box(70, 1192, 340, 98, "gold", "vLLM gateway (10.48.242.4)", "qwen-model · qwen4-deploy · qwen35-9b<br>qwen3-embedding · qwen3-reranker · qwen3-asr", ts=15.5, ss=12.3)
    f.box(420, 1192, 340, 98, "purple", "PostgreSQL 18 — megh_db", "curated v_* views · semantic catalogue<br>run_query / check_query · app.* tables", ts=15.5, ss=12.3)
    f.box(770, 1192, 340, 98, "teal", "Qdrant (10.48.242.4:6333)", "megh_knowledge (scheme documents)<br>megh_sql_metadata (SQL examples)", ts=15.5, ss=12.3)
    f.raw('<div style="position:absolute;left:0;top:1310px;width:1180px;height:90px;background:#13294B"></div>')
    f.text(40, 1320, 1100, "<b>TECH STACK</b>", 14, "#fff")
    f.text(40, 1344, 1100, "Python 3.11 · FastAPI 0.141 · Uvicorn 0.52 · Pydantic 2.13 · asyncpg 0.31 · httpx 0.28 · LangGraph 1.2 + Postgres checkpointer 3.1 · psycopg 3.3 · SQLGlot 30.23<br>qdrant-client 1.19 · rapidfuzz 3.14 · PyYAML 6 · Redis 8 (optional) · fastembed 0.8 (rollback only) · React 18.3 · Vite 6 · Chart.js 4.4.1 · nginx + ModSecurity CRS", 12.8, "#E2E8F0")
    return f


def fig04():
    W, H = 1540, 900
    f = Fig(W, H, "Megh One AI — LangGraph Question Pipeline (22 nodes)",
            "app/pipeline_graph.py · each node calls one stage function in the app/pipeline/ package · a clarification pauses the run with interrupt() and a Postgres checkpoint")
    cx = [200, 420, 640, 860, 1080, 1310]
    bw, bh = 196, 64
    rows = [130, 312, 494, 676]
    fam = ["blue", "purple", "orange", "green"]
    def nb(c, r, name, s, fm=None, dashed=False, x=None):
        return f.box(x if x is not None else cx[c], rows[r], bw, bh, fm or fam[r], name, s, mono=True, dashed=dashed, ts=15, ss=12)
    f.pill(30, rows[0] + 12, 120, 40, "START")
    f.arrow([(150, rows[0] + 32), (cx[0] - 2, rows[0] + 32)])
    f.sec(cx[0] + bw / 2 + 16, rows[0] - 24, "1 · understand the question")
    r0 = [("context", "topic · pause reply · spelling"), ("edge", "rules + 4B guardrail"), ("followup", "9B rewrite · provenance"),
          ("rephrase", "tidy messy wording (9B)"), ("route", "DATA or KNOWLEDGE? (4B)")]
    for i, (n, s) in enumerate(r0):
        nb(i, 0, n, s)
        if i < 4:
            f.arrow([(cx[i] + bw, rows[0] + 32), (cx[i + 1] - 2, rows[0] + 32)])
    nb(5, 0, "knowledge", "megh_knowledge · re-ranker", "teal")
    f.arrow([(cx[4] + bw, rows[0] + 32), (cx[5] - 2, rows[0] + 32)], "#0F8C80")
    f.tag((cx[4] + bw + cx[5]) / 2, rows[0] + 14, "KNOWLEDGE", "#0F766E")
    f.sec(cx[0] + bw / 2 + 16, rows[1] - 24, "2 · data scope")
    r1 = [("data_context", "inherit place · year · defaults"), ("scope_scheme", "which scheme(s)? · registry"),
          ("entities", "district · block · village · AC"), ("clarification_gate", "ask only real ambiguity"),
          ("deterministic", "fixed queries · metric catalogue")]
    for i, (n, s) in enumerate(r1):
        nb(i, 1, n, s)
        if i < 4:
            f.arrow([(cx[i] + bw, rows[1] + 32), (cx[i + 1] - 2, rows[1] + 32)])
    f.arrow([(cx[4] + bw / 2, rows[0] + bh), (cx[4] + bw / 2, rows[0] + 118), (cx[0] + bw / 2, rows[0] + 118), (cx[0] + bw / 2, rows[1] - 2)],
            label="DATA", lpos=(cx[2] + bw / 2, rows[0] + 118), lcol="#6D28D9")
    f.sec(cx[0] + bw / 2 + 16, rows[2] - 24, "3 · SQL")
    r2 = [("sql_generate", "Qwen3-Coder 30B · examples"), ("authorize", "role · area · scheme · level"),
          ("execute_attempt", "SQLGlot guard · 30B verifier · run")]
    for i, (n, s) in enumerate(r2):
        nb(i, 2, n, s)
        if i < 2:
            f.arrow([(cx[i] + bw, rows[2] + 32), (cx[i + 1] - 2, rows[2] + 32)])
    nb(3, 2, "repair", "on error · ≤ 3 · 40 s budget")
    f.arrow([(cx[2] + bw, rows[2] + 20), (cx[3] - 2, rows[2] + 20)], ORANGE)
    f.arrow([(cx[3], rows[2] + 44), (cx[2] + bw + 2, rows[2] + 44)], ORANGE)
    f.arrow([(cx[4] + bw / 2, rows[1] + bh), (cx[4] + bw / 2, rows[1] + 118), (cx[0] + bw / 2, rows[1] + 118), (cx[0] + bw / 2, rows[2] - 2)])
    nb(5, 2, "pause_gate", "interrupt() · checkpoint", "orange", dashed=True, x=cx[5])
    f.arrow([(cx[3] + bw * 0.7, rows[1] + bh), (cx[5] + bw / 2, rows[2] - 2)], ORANGE, dash=True, label="ClarificationNeeded", lpos=(cx[4] + 150, rows[1] + 96))
    f.arrow([(cx[5] + bw, rows[2] + 32), (1522, rows[2] + 32), (1522, 92), (cx[0] + bw / 2, 92), (cx[0] + bw / 2, rows[0] - 2)], ORANGE, dash=True,
            label="officer's reply resumes the paused run — Command(resume=…) at context", lpos=(860, 92))
    f.sec(cx[0] + bw / 2 + 16, rows[3] - 24, "4 · answer and save")
    r3 = [("post_rows", "notes · premise check"), ("compose", "Qwen3.5 9B (streamed)"), ("guarantees", "numbers · labels · money"),
          ("assemble", "chart hint · payload"), ("finalize", "follow-up chips · preface"), ("context_update", "save state (rev-guarded)")]
    for i, (n, s) in enumerate(r3):
        nb(i, 3, n, s)
        if i < 5:
            f.arrow([(cx[i] + bw, rows[3] + 32), (cx[i + 1] - 2, rows[3] + 32)])
    f.arrow([(cx[2] + bw / 2, rows[2] + bh), (cx[2] + bw / 2, rows[2] + 118), (cx[0] + bw / 2, rows[2] + 118), (cx[0] + bw / 2, rows[3] - 2)],
            label="rows", lpos=(cx[1] + bw / 2, rows[2] + 118))
    f.arrow([(cx[5] + 30, rows[0] + bh), (cx[5] + 30, rows[1] + 20), (cx[5] - 14, rows[1] + 20), (cx[5] - 14, rows[3] - 40), (cx[4] + bw / 2, rows[3] - 40), (cx[4] + bw / 2, rows[3] - 2)],
            "#64748B", dash=True, label="answered", lpos=(cx[5] - 14, rows[2] - 60))
    f.tag(cx[5] + 130, rows[0] + bh + 22, "not covered → data path", "#0F766E", "#99F6E4", "#F0FDFA")
    f.pill(cx[5] + 28, rows[3] + bh + 34, 140, 40, "END")
    f.arrow([(cx[5] + bw / 2, rows[3] + bh), (cx[5] + bw / 2, rows[3] + bh + 32)])
    f.legend(H - 64, [("sw", "blue", "understand"), ("sw", "teal", "knowledge"), ("sw", "purple", "data scope"), ("sw", "orange", "SQL"),
                      ("sw", "green", "answer"), ("ln", ("#334155", False), "normal flow"), ("ln", (ORANGE, True), "pause / resume"),
                      ("ln", ("#64748B", True), "answer ready → finalize (any node)")], "LangGraph pipeline")
    return f


def fig05():
    W, H = 1760, 1020
    f = Fig(W, H, "Megh One AI — Component Diagram",
            "FastAPI service · routers → conversation layer → LangGraph pipeline → stage functions → data access · PostgreSQL, Qdrant and the vLLM gateway outside")
    for lab, y in (("web / presentation", 84), ("api — routers", 186), ("services", 296), ("domain — app/pipeline and helpers", 404),
                   ("data access", 620), ("infrastructure", 734)):
        f.raw(f'<div style="position:absolute;left:40px;top:{y}px;width:{W-80}px;border-top:1px dashed #CBD5E1"></div>')
        f.sec(1400 if lab.startswith("domain") else 46, y + 4, lab, "#94A3B8")
    f.box(440, 104, 260, 60, "blue", "FastAPI Application", "app.main · lifespan · /health · /metrics")
    f.box(860, 104, 240, 60, "grey", "Web Browser", "React chat + admin consoles", ts=15)
    f.box(1160, 104, 250, 60, "teal", "Built UI (web/app)", "React 18 · Vite · Chart.js")
    f.box(1450, 104, 270, 60, "purple", "middleware", "headers · body cap · rate limit · request id")
    f.arrow([(860, 134), (702, 134)], "#2563EB", label="«HTTPS» JSON / SSE", lpos=(780, 118))
    routers = ["query", "auth", "history", "rag", "feedback", "stats", "admin"]
    subs = ["ask · stream · transcribe", "login · me", "own chats", "KB status", "👍 / 👎 votes", "scheme cards", "admin API"]
    for i, r in enumerate(routers):
        f.box(70 + i * 236, 212, 214, 54, "blue", r, subs[i], mono=True)
    svc = [("deps · security · auth", "JWT guard · PBKDF2 · authorize", "purple"), ("conversation_layer", "expiry · reset · topics · multi-part", "teal"),
           ("pipeline_graph", "LangGraph · 22 nodes · checkpointer", "teal"), ("rag", "retrieve · re-rank · ground", "teal"),
           ("edge + guardrails", "rules · 4B check · alerts", "teal"), ("translate + spelling", "Devanagari · names", "teal")]
    for i, (t, s_, fm) in enumerate(svc):
        f.box(70 + i * 275, 320, 255, 60, fm, t, s_, mono=True)
    dom = [("app/pipeline/common", "c01–c17 shared stages"), ("app/pipeline/schemes", "one file per scheme"), ("context_manager + policy", "state · merge plan"),
           ("topic_memory + session_sync", "topics · ledger · Postgres"), ("prompt_builder + schema_context", "SQL / verify prompts"),
           ("data_facts", "live figures in prompts"), ("entity_resolver", "places · years · gazetteer"), ("scheme_registry", "one source of scheme facts"),
           ("metric_catalog", "data team's measures"), ("cross_scheme + cross_figures", "multi-scheme figures"), ("annotations", "IDF-ranked few-shots"),
           ("sql_ast · text_match", "SQLGlot tree · word matcher")]
    for i, (t, s_) in enumerate(dom):
        f.box(70 + (i % 6) * 275, 428 + (i // 6) * 92, 255, 72, "orange", t, s_, mono=True, ts=13.5)
    da = [("conversation_store", "turns · audit · feedback"), ("cache + semantic_cache", "exact · cosine 0.93"), ("db + sql_guard", "3 pools · run_readonly"),
          ("llm", "httpx · model roles"), ("vectorstore", "Qdrant · read-only"), ("turn_trace", "run trace · /metrics")]
    for i, (t, s_) in enumerate(da):
        f.box(70 + i * 275, 642, 255, 60, "gold", t, s_, mono=True)
    infra = [("Redis (optional)", "shared cache · rate limits"), ("PostgreSQL 18", "megh_db · curated + app"), ("vLLM gateway", "Qwen3 · embed · rerank · ASR"),
             ("Qdrant", "megh_knowledge · megh_sql_metadata"), ("data/", "YAML rules · few-shots · metric list")]
    ix = [70 + i * 340 for i in range(5)]
    for i, (t, s_) in enumerate(infra):
        f.box(ix[i] + 20, 758, 280, 70, "grey", t, s_, ts=15.5)
    D = "#64748B"
    f.arrow([(570, 164), (570, 210)], D, dash=True, label="«include»", lpos=(622, 187))
    f.arrow([(177, 266), (177, 318)], D, dash=True, label="auth guard", lpos=(232, 292))
    f.arrow([(200, 266), (470, 318)], D, dash=True)
    f.arrow([(220, 266), (745, 318)], D, dash=True)
    f.arrow([(885, 266), (1020, 318)], D, dash=True)
    f.arrow([(720, 380), (197, 426)], D, dash=True, label="runs stages", lpos=(430, 400))
    f.arrow([(740, 380), (472, 426)], D, dash=True)
    f.arrow([(470, 380), (747, 426)], D, dash=True)
    f.arrow([(470, 380), (1020, 426)], D, dash=True)
    f.arrow([(197, 590), (197, 640)], D, dash=True)
    f.arrow([(472, 590), (472, 640)], D, dash=True)
    f.arrow([(747, 590), (747, 640)], D, dash=True, label="«use»", lpos=(790, 614))
    f.arrow([(1022, 590), (1022, 640)], D, dash=True)
    f.arrow([(1297, 590), (1297, 640)], D, dash=True)
    G = "#0F766E"
    f.arrow([(197, 702), (500, 756)], G, label="«SQL»", lpos=(330, 726))
    f.arrow([(472, 702), (240, 756)], G)
    f.arrow([(747, 702), (560, 756)], G)
    f.arrow([(1022, 702), (840, 756)], G, label="«HTTPS»", lpos=(940, 726))
    f.arrow([(1297, 702), (1180, 756)], G)
    f.arrow([(1572, 590), (1572, 620), (1560, 756)], D, dash=True)
    f.text(70, 856, 1620, "<b>How to read it.</b> Routers only validate and map errors. The conversation layer runs before the caches and the graph. "
           "Every LangGraph node is a thin wrapper around one stage function in <b>app/pipeline/</b>: eighteen shared files (c01–c17, with two c12 files) and one file per scheme, "
           "executed in order into one shared namespace. Model SQL reaches PostgreSQL only through <b>db.run_readonly()</b>, after the SQLGlot guard and the role check.", 13.5, "#334155")
    f.legend(H - 70, [("sw", "blue", "web / router"), ("sw", "purple", "security"), ("sw", "teal", "service"), ("sw", "orange", "domain"),
                      ("sw", "gold", "data access"), ("sw", "grey", "infrastructure"), ("ln", ("#64748B", True), "«use» dependency"),
                      ("ln", ("#0F766E", False), "network interface")], "LLD · Component Diagram")
    return f

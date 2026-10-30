"""Figures 12-16 (sequences) and 17-20 (new in v2.0)."""
from figlib import Fig, seq

C_OFF, C_UI, C_RT, C_LAY, C_G, C_GW, C_DB, C_Q, C_EMB = "#334155", "#1D4ED8", "#1E40AF", "#059669", "#BE123C", "#B45309", "#7C3AED", "#0E7490", "#047857"
ORANGE = "#C2410C"


def fig12():
    parts = [("Officer", "(Browser)", C_OFF), ("React console", "(Overlays · api.js)", C_UI), ("auth router", "(/api/auth)", C_RT),
             ("security.py", "(PBKDF2 · JWT)", C_LAY), ("PostgreSQL", "(app.users · login_events)", C_DB), ("stats router", "(/api/scheme-stats)", C_GW)]
    st = [("call", 0, 1, "1. open /megh-chat (no token → sign-in gate)"),
          ("call", 1, 2, "2. POST /api/auth/login {username, password}"),
          ("self", 2, "3. rate limit: 6 tries / 300 s per IP"),
          ("call", 2, 4, "4. find active user by username"),
          ("ret", 4, 2, "user row + password_hash"),
          ("call", 2, 3, "5. verify_password (PBKDF2-SHA256, 200,000 iterations)"),
          ("div", "if the password is wrong"),
          ("call", 2, 4, "6a. login_events: login_fail (ip, user agent, reason)"),
          ("ret", 2, 1, "401 — message shown, gate stays"),
          ("div", "else — signed in"),
          ("call", 2, 3, "6b. issue_token: HS256 {sub, username, tenant_id, role, iss, exp = 12 h}"),
          ("call", 2, 4, "7. login_events: login_ok · users.last_login_at"),
          ("ret", 2, 1, "JWT + public user (role, scope)"),
          ("self", 1, "8. keep the token in localStorage (megh_jwt)"),
          ("call", 1, 2, "9. GET /api/auth/me (Bearer JWT) → scope: districts · blocks · schemes · level"),
          ("call", 1, 5, "10. GET /api/scheme-stats → live card figures for the user's schemes"),
          ("ret", 1, 0, "chat console: welcome card · scheme cards · sidebar")]
    return seq("Megh One AI — Sequence Diagram: Sign-in & Authentication", "username + password → PBKDF2 check → HS256 JWT (12 h) → profile and scope → live scheme cards", parts, st)


def fig13():
    parts = [("Officer", "(Browser)", C_OFF), ("query router", "(/api/query/stream)", C_RT), ("layer + caches", "(conversation_layer)", C_LAY),
             ("LangGraph", "(pipeline_graph)", C_G), ("vLLM gateway", "(Qwen3 models)", C_GW), ("PostgreSQL", "(megh_db)", C_DB)]
    st = [("call", 0, 1, "1. question + session_id + language + Bearer JWT"),
          ("self", 1, "2. verify JWT → UserScope · translate Devanagari · sync_in session state"),
          ("call", 1, 2, "3. prepare_turn (expiry · reset · topic return) · exact / semantic cache"),
          ("ret", 2, 1, "cache miss"),
          ("call", 1, 3, "4. answer_question_via_graph (thread = session_id)"),
          ("ret", 1, 0, "SSE step: Understanding your question …"),
          ("call", 3, 4, "5. guardrail + intent (Qwen3 4B) · follow-up rewrite (9B)"),
          ("self", 3, "6. scheme (registry) · district / block / village / AC · year"),
          ("note", 3, 4, "no place → statewide · no year → all years (said in the answer)"),
          ("call", 3, 4, "7. generate SQL (Qwen3-Coder 30B, live figures + YAML examples)"),
          ("self", 3, "8. SQLGlot guard · authorize(scope, SQL) · 30B verifier"),
          ("call", 3, 5, "9. run_readonly → semantic.run_query (megh_chatbot) · LIMIT 1000 · 15 s"),
          ("ret", 5, 3, "rows (or error → repair ≤ 3, re-authorised, 40 s budget)"),
          ("call", 3, 4, "10. compose answer (Qwen3.5 9B, streamed)"),
          ("ret", 1, 0, "SSE token: draft text as it is written"),
          ("self", 3, "11. numbers in rows · figure-to-label · money format · code-written figures"),
          ("ret", 3, 1, "answer · rows · SQL · chart hint · notes · follow-ups"),
          ("ret", 1, 0, "SSE done (checked answer replaces the draft)"),
          ("call", 1, 5, "12. save turn · audit row + run trace · context_state (rev-guarded)"),
          ("call", 1, 2, "13. cache write-back (not for context-dependent turns)")]
    return seq("Megh One AI — Sequence Diagram: Data Question (streamed)", "POST /api/query/stream · LangGraph run · NL → SQL → guarded read-only run → checked answer · SSE events step / token / done", parts, st)


def fig14():
    parts = [("Officer", "(Browser)", C_OFF), ("query router", "(/api/query/stream)", C_RT), ("LangGraph", "(route + knowledge)", C_G),
             ("Embeddings", "(gateway qwen3-embedding)", C_EMB), ("Qdrant", "(megh_knowledge)", C_Q), ("vLLM gateway", "(re-ranker · 9B)", C_GW)]
    st = [("call", 0, 1, "1. question + Bearer JWT"),
          ("call", 1, 2, "2. answer_question_via_graph"),
          ("self", 2, "3. route: KNOWLEDGE (rules, retrieval tie-break, else 4B)"),
          ("self", 2, "4. wordings: question + sub-asks + facet queries (+ English of Hinglish)"),
          ("call", 2, 3, "5. embed each wording (1024-dim)"),
          ("ret", 3, 2, "vectors"),
          ("call", 2, 4, "6. search in parallel (≤ 6) · filter scheme = PMAY-G · top 12"),
          ("ret", 4, 2, "chunks + cosine scores"),
          ("self", 2, "7. fuse the lists (RRF, k = 60) · drop chunks below 0.30"),
          ("call", 2, 5, "8. qwen3-reranker (always on): order the candidates"),
          ("ret", 5, 2, "re-ranked order (fused with the vector order)"),
          ("div", "if top score ≥ 0.84 and not a list / documents / how-to question"),
          ("self", 2, "9a. return the best chunk as written"),
          ("div", "else if top score ≥ the compose cut-off"),
          ("call", 2, 5, "9b. compose from the pieces (Qwen3.5 9B) · FAQ answer first"),
          ("ret", 5, 2, "answer text"),
          ("call", 2, 5, "10. grounding check: drop unsupported sentences"),
          ("self", 2, "11. add missed FAQ facts · sources = pieces the answer used"),
          ("div", "else — not covered by the scheme documents"),
          ("self", 2, "9c. say so plainly; never guess (data path tried if it fits)"),
          ("ret", 2, 1, "answer · sources (title, section) · follow-ups"),
          ("ret", 1, 0, "SSE done (route: knowledge)")]
    return seq("Megh One AI — Sequence Diagram: Scheme Knowledge Question (RAG)",
               "\"Who is eligible for PMAY-G?\" · gateway embeddings → Qdrant with an exact scheme filter → fusion → always-on re-ranker → tiered, grounded answer", parts, st)


def fig15():
    parts = [("Officer", "(Browser)", C_OFF), ("query router", "(/api/query/stream)", C_RT), ("LangGraph", "(graph run)", C_G),
             ("pause_gate", "(interrupt)", ORANGE), ("Checkpointer", "(app.checkpoint*)", C_DB), ("Session state", "(context_state)", C_LAY)]
    st = [("call", 0, 1, "1. \"Focus beneficiaries in Tura block 2023-24\""),
          ("call", 1, 2, "2. answer_question_via_graph (thread = session_id)"),
          ("self", 2, "3. scope_scheme: bare \"Focus\" → Focus Plus or Focus Legacy?"),
          ("call", 2, 3, "4. ClarificationNeeded → pause_gate"),
          ("call", 3, 4, "5. interrupt(payload) · checkpoint saved under the thread"),
          ("call", 2, 5, "6. pending pause also kept in the session snapshot"),
          ("ret", 2, 1, "route clarification · chips [Focus Plus] [Focus Legacy]"),
          ("ret", 1, 0, "SSE done: short question + one-tap chips"),
          ("note", 0, 1, "unanswered pauses are swept after 30 minutes"),
          ("call", 0, 1, "7. taps \"Focus Plus\" (or types a reply)"),
          ("call", 1, 4, "8. paused thread found → Command(resume = reply)"),
          ("ret", 4, 2, "restored state: question, place, year"),
          ("self", 2, "9. context: the reply keeps the typed question's kind"),
          ("self", 2, "10. entities → SQL → authorize → run → compose → guarantees"),
          ("call", 2, 5, "11. context_update: scheme, place, year remembered"),
          ("call", 2, 4, "12. finished thread deleted"),
          ("ret", 2, 1, "answer for Focus Plus, Tura block, FY 2023-24"),
          ("ret", 1, 0, "SSE done · the next question in this chat is not asked again")]
    return seq("Megh One AI — Sequence Diagram: Clarification Pause and Resume",
               "only real ambiguity pauses the run · interrupt() + Postgres checkpoint · the reply resumes it · either VM can continue", parts, st)


def fig16():
    parts = [("Officer", "(Browser)", C_OFF), ("React console", "(useVoice · RecordingStrip)", C_UI), ("query router", "(/api/query/transcribe)", C_RT),
             ("vLLM gateway", "(qwen3-asr)", C_GW), ("query router", "(/api/query/stream)", C_RT), ("LangGraph", "(graph run)", C_G)]
    st = [("call", 0, 1, "1. taps the microphone · browser asks for permission"),
          ("self", 1, "2. live dictation strip · silence guard · stop"),
          ("self", 1, "3. convert to 16 kHz WAV"),
          ("call", 1, 2, "4. POST multipart audio (≤ 10 MB · 90 per minute · Bearer JWT)"),
          ("call", 2, 3, "5. transcribe (language hint)"),
          ("ret", 3, 2, "text"),
          ("div", "if no speech was heard"),
          ("ret", 2, 1, "{text: \"\", no_speech: true} → \"I didn't catch that\""),
          ("div", "else"),
          ("ret", 2, 1, "{text}"),
          ("ret", 1, 0, "text placed in the question box — the officer can edit it"),
          ("call", 0, 1, "6. Send"),
          ("call", 1, 4, "7. POST /api/query/stream (same path as a typed question)"),
          ("self", 4, "8. Devanagari text → English first (D-091)"),
          ("call", 4, 5, "9. answer_question_via_graph"),
          ("ret", 5, 4, "checked answer"),
          ("ret", 4, 0, "SSE step / token / done · Read aloud available")]
    return seq("Megh One AI — Sequence Diagram: Voice Question", "speech → text with the gateway ASR model → the officer checks the text → the normal question path", parts, st)


# ---------------------------------------------------------------- new figures
def fig17():
    W, H = 1600, 960
    f = Fig(W, H, "Megh One AI — Knowledge Answer (RAG) Pipeline",
            "app/rag.py · read-only Qdrant collection megh_knowledge · gateway embeddings · always-on qwen3-reranker · grounded answers with the sources actually used")
    f.box(40, 110, 230, 70, "blue", "Knowledge question", "routed KNOWLEDGE by rules, the retrieval tie-break or the 4B")
    f.arrow([(270, 145), (318, 145)])
    f.box(320, 100, 300, 90, "blue", "1 · Build the wordings", "the question · each sub-ask · facet queries (launch, amount, documents, eligibility, apply) · English of a Hinglish question")
    f.arrow([(620, 145), (668, 145)])
    f.box(670, 100, 260, 90, "teal", "2 · Embed", "gateway qwen3-embedding<br>1024-dim · batch 32")
    f.arrow([(930, 145), (978, 145)])
    f.box(980, 100, 290, 90, "teal", "3 · Search Qdrant", "megh_knowledge · exact scheme filter<br>≤ 6 searches at once · top 12 each")
    f.arrow([(1270, 145), (1318, 145)])
    f.box(1320, 100, 240, 90, "teal", "4 · Fuse", "reciprocal-rank fusion (k = 60)<br>drop chunks below 0.30")
    f.arrow([(1440, 190), (1440, 250), (1420, 250)], "#334155")
    f.box(1100, 222, 318, 90, "gold", "5 · Re-rank (always on)", "qwen3-reranker orders the candidates; its order is fused with the vector order (D-083)")
    f.arrow([(1100, 267), (1052, 267)])
    f.svg.append('<polygon points="900,212 1050,267 900,322 750,267" fill="#FEFCE8" stroke="#C2410C" stroke-width="2"/>')
    f.text(790, 250, 220, "<b style='color:#9A3412'>best score?</b>", 14, "#9A3412", "center")
    f.arrow([(750, 267), (520, 267), (520, 372)], "#C2410C", label="≥ 0.84 (not a list / how-to)", lpos=(625, 267))
    f.arrow([(900, 322), (900, 372)], "#C2410C", label="≥ compose cut-off", lpos=(990, 348))
    f.arrow([(1050, 267), (1060, 267), (1060, 340), (1380, 340), (1380, 372)], "#C2410C", dash=True, label="below", lpos=(1220, 340))
    f.box(400, 374, 240, 74, "green", "6a · Verbatim answer", "the best chunk, as written")
    f.box(740, 374, 320, 74, "green", "6b · Compose (Qwen3.5 9B)", "from the passages only · FAQ answer first · completeness and naming rules")
    f.box(1240, 374, 300, 74, "red", "6c · Not covered", "say so plainly · try another scheme or the data path if it fits")
    f.arrow([(900, 448), (900, 496)])
    f.box(740, 498, 320, 74, "green", "7 · Ground the answer", "drop sentences the passages do not support (never empties the answer)")
    f.arrow([(900, 572), (900, 620)])
    f.box(740, 622, 320, 74, "green", "8 · Backstops in code", "missed FAQ facts · related ministry · sub-scheme count")
    f.arrow([(520, 448), (520, 760), (738, 760)])
    f.arrow([(900, 696), (900, 724)])
    f.box(740, 726, 320, 70, "blue", "9 · Answer + sources", "sources = the pieces the answer leans on · 👍 / 👎")
    f.arrow([(1390, 448), (1390, 760), (1062, 760)], "#64748B", dash=True)
    f.raw('<div style="position:absolute;left:40px;top:222px;width:330px;height:226px;background:#FEFCE8;border:1.5px solid #EAB308;border-radius:8px;padding:10px 14px;font-size:12.6px;color:#713F12;line-height:1.5">'
          '<b>Settings (effective values)</b><br>RAG_MIN_SCORE 0.30 · RAG_HIGH_CONFIDENCE 0.84<br>RAG_MEDIUM_CONFIDENCE 0.35 (.env.example; code default 0.55)<br>'
          'RAG_TOP_K 12 · RAG_RERANK_TOP_N 8 (+4 multi-part)<br>RAG_GROUNDING_CHECK on · 15 s<br>RAG_HYBRID_ENABLED false: megh_knowledge has no BM25 vector<br>'
          'QDRANT_KB_READ_ONLY true — KB changes go to the loading team</div>')
    f.raw('<div style="position:absolute;left:40px;top:470px;width:420px;height:320px;background:#F0F9FF;border:1.5px solid #7DD3FC;border-radius:8px;padding:10px 14px;font-size:12.6px;color:#0C4A6E;line-height:1.5">'
          '<b>What changed since v1.0</b><br>• Embeddings moved from local bge-small (384-dim) to the gateway qwen3-embedding (1024-dim), D-067.<br>'
          '• The KB is megh_knowledge on 10.48.242.4:6333, loaded by another pipeline and read-only to the app, D-074.<br>'
          '• The re-ranker is always on; there is no switch, D-083.<br>• Multi-part questions, facet queries and FAQ-first prompts, D-094.<br>'
          '• Grounding check and source selection (RAG phases 5–6).<br>• CM Elevate Legacy reads CM Elevate\'s documents.</div>')
    f.text(40, 820, 1050, "<b>Measured:</b> live knowledge suite 114 / 114 · RAG evaluation 98.4 % (negatives 100 %) · re-ranker on megh_knowledge: right piece first 62.4 %, in the top 3 88.0 %.", 13, "#334155")
    f.legend(H - 70, [("sw", "blue", "input / output"), ("sw", "teal", "retrieval"), ("sw", "gold", "re-rank"), ("sw", "green", "answer"), ("sw", "red", "not covered"),
                      ("ln", ("#334155", False), "flow"), ("ln", ("#64748B", True), "fallback")], "HLD · RAG Pipeline")
    return f


def fig18():
    W, H = 1600, 1010
    f = Fig(W, H, "Megh One AI — Conversation and Context Layer",
            "what happens around every turn so a chat never loses or re-asks its scope · structured state in Postgres, not raw previous answers")
    f.sec(40, 88, "Turn entry order (app/routers/query.py)")
    steps = [("1 · Translate", "Devanagari → English<br>(Khasi / Garo off)", "blue"), ("2 · sync_in", "load context_state<br>from app.conversations", "teal"),
             ("3 · prepare_turn", "idle expiry 8 h · reset<br>topic return · small talk", "teal"), ("4 · Caches", "exact, then semantic<br>(cosine ≥ 0.93, 15 min)", "gold"),
             ("5 · Answer", "graph run, or answer_many<br>for a multi-part question", "purple"), ("6 · sync_out", "write snapshot back<br>only if rev is newer", "teal"),
             ("7 · Cache put", "only for turns that do not<br>depend on the chat", "gold")]
    for i, (t, s, fm) in enumerate(steps):
        x = 40 + i * 222
        f.box(x, 112, 202, 84, fm, t, s, ts=15, ss=12.2)
        if i < 6:
            f.arrow([(x + 202, 154), (x + 220, 154)])
    f.sec(40, 226, "Inside the graph (context, followup, data_context, context_update)")
    f.box(40, 250, 360, 100, "blue", "Follow-up detection and rewrite", "c01 · the 9B rewrites a fragment into a full question from the previous turn's <b>filters</b>; rows only when the follow-up points into them (D-022)")
    f.arrow([(400, 300), (440, 300)])
    f.box(442, 250, 330, 100, "red", "Provenance check (D-024)", "every place, year and scheme in the rewrite must come from the question or the chat state — else it is rejected")
    f.arrow([(772, 300), (812, 300)])
    f.box(814, 250, 340, 100, "purple", "Merge plan (context_policy)", "per field: KEEP · REPLACE · CLEAR · ask; a self-sufficient new question inherits nothing (D-061)")
    f.arrow([(1154, 300), (1194, 300)])
    f.box(1196, 250, 364, 100, "green", "Answer with defaults (D-089)", "no place → all of Meghalaya · no year → all years · stated in the answer with chips to narrow it")
    f.sec(40, 384, "What the snapshot holds (Session.to_snapshot → app.conversations.context_state)")
    f.raw('<div style="position:absolute;left:40px;top:408px;width:740px;height:250px;background:#fff;border:2px solid #0F8C80;border-radius:10px;padding:12px 18px;font-size:13.2px;color:#134E4A;line-height:1.6">'
          '<b>Active scope</b> — scheme, district / block / village / AC, year, measure, each with where it came from<br>'
          '<b>Last turn</b> — question, answer kind, filters, small row summary (120 tokens)<br>'
          '<b>Pending pause</b> — the clarification waiting for a reply (backup of the checkpoint)<br>'
          '<b>Topics</b> — up to 8 per chat, each with its own scope and a ledger of its last 20 questions<br>'
          '<b>Rolling summary</b> — refreshed every 4 turns (≤ 1,200 tokens of context)<br>'
          '<b>Window</b> — 50 turns · 8-hour idle expiry · per-worker cache of 5,000 sessions<br>'
          '<b>rev</b> — version number; a stale writer cannot overwrite a newer snapshot</div>')
    f.sec(820, 384, "Conversation features built on it")
    feats = [("Topic return", "“what was the PMAY-G figure again?” restores that topic"), ("Questions about the chat (c15)", "recap · explain · breakdown · correction · suggest"),
             ("Never re-ask (D-055)", "inside one chat a known place / year is never asked again"), ("Multi-part (D-092)", "“X and Y” answered part by part in one reply"),
             ("Stop / continue", "a stopped answer can be continued (English and Hindi words)"), ("Spelling (D-093)", "“Showing results for …” when a name was corrected")]
    for i, (t, s) in enumerate(feats):
        f.box(820 + (i % 2) * 372, 408 + (i // 2) * 86, 358, 74, "teal", t, s, ts=14.5, ss=12)
    f.sec(40, 690, "Two stores, one source of truth")
    f.box(40, 714, 480, 92, "grey", "SessionStore (per worker)", "in-process cache only · rebuilt from Postgres on every request · so either VM, either worker continues the chat")
    f.box(560, 714, 480, 92, "purple", "app.conversations.context_state", "the durable snapshot · written after every turn (1 s timeout, one retry) · deleted with the chat")
    f.box(1080, 714, 480, 92, "orange", "app.checkpoint* (LangGraph)", "only paused clarification runs · thread = session_id · swept after 30 min · deleted when finished")
    f.text(40, 830, 1520, "Conversation memory in Qdrant is <b>off</b> (CONTEXT_SEMANTIC_MEMORY_ENABLED = false). Nothing from a previous answer's raw text is put back into a prompt; "
           "only structured, provenance-checked fields are carried forward. A call without a session id gets its own conversation (D-070); another user's session id is never reused.", 13, "#334155")
    f.legend(H - 70, [("sw", "blue", "input"), ("sw", "teal", "state / features"), ("sw", "gold", "cache"), ("sw", "purple", "store / merge"), ("sw", "red", "check"),
                      ("sw", "green", "defaults")], "HLD · Context Layer")
    return f


def fig19():
    W, H = 1600, 940
    f = Fig(W, H, "Megh One AI — Pipeline Code Structure (app/pipeline package)",
            "one 18,700-line pipeline.py was split on 2026-10-15 · files run in _PIPELINE_FILES order into ONE shared namespace · nodes stay thin, behaviour lives in stage functions")
    f.box(40, 100, 420, 84, "purple", "app/pipeline_graph.py", "LangGraph StateGraph · 22 nodes · checkpointer · pause sweep · step events — the only orchestrator (D-032, D-036)", mono=True)
    f.arrow([(460, 142), (520, 142)], label="calls", lpos=(490, 124))
    f.box(522, 100, 500, 84, "blue", "app/pipeline/__init__.py", "executes every file below into one module namespace, so p.&lt;name&gt; and monkeypatch work · duplicate names fail a test", mono=True)
    f.arrow([(1022, 142), (1082, 142)])
    f.box(1084, 100, 476, 84, "grey", "tests/_graph_turn.py", "tests drive whole turns through the graph · ~4,700 pytest cases + 14 scripts", mono=True)
    f.sec(40, 214, "common/ — shared steps every scheme goes through (load order)")
    common = [("c01_followups", "follow-ups · rewrite · provenance"), ("c02_rephraser", "rephrase · spelling guards"), ("c03_scheme_terms", "scheme words · pauses"),
              ("c04_scheme_listing", "list · pick · compare schemes"), ("c05_clarifications", "scope · top-N · region asks"), ("c06_years_tranches", "years · tranches · summaries"),
              ("c07_mentions", "scheme + place mentions"), ("c08_villages", "village resolution · AC"), ("c09_resolve_entities", "resolve_entities · twins"),
              ("c10_sql_generation…", "SQL generation · rewrites"), ("c11_sql_verify_repair", "verify · execute · repair"), ("c12_answer_numbers", "faithfulness · money format"),
              ("c12_answer_shapes", "shape from SQL tree · templates"), ("c13_compose_and_data…", "compose_response · data stages"), ("c14_turn_stages", "context · edge · route · knowledge"),
              ("c15_conversation_meta", "questions about the chat"), ("c16_metric_catalog", "data team's measures (D-071)"), ("c17_data_answer_rules", "sub-asks · runners-up · caveats")]
    for i, (t, s) in enumerate(common):
        x = 40 + (i % 6) * 254
        y = 240 + (i // 6) * 86
        new = t in ("c16_metric_catalog", "c17_data_answer_rules")
        f.box(x, y, 238, 72, "gold" if new else "orange", t, s, mono=True, ts=13.2, ss=11.8)
    f.sec(40, 508, "schemes/ — one file per scheme: village rules, fixed queries, SQL rewrites, answer checks (loaded after c03)")
    sch = [("mgnrega.py", "#1D4ED8"), ("pmay_g.py", "#0F766E"), ("focus_plus.py", "#7C3AED"), ("cm_elevate.py", "#B45309"), ("focus_legacy.py", "#BE185D"), ("cm_elevate_legacy.py", "#C2410C")]
    for i, (t, c) in enumerate(sch):
        f.raw(f'<div class="b mono" style="left:{40+i*254}px;top:534px;width:238px;height:58px;background:#fff;border:2px solid {c};border-radius:9px"><div class="t" style="font-size:14px;color:{c}">{t}</div></div>')
    f.sec(40, 624, "Rules for changing it")
    rules = ["Change behaviour in a stage function, never in a graph node.",
             "A scheme-only fix goes in that scheme's file; a shared fix in the common file that holds the function.",
             "Load-time code (constants, word patterns, defaults) may only use names from files loaded before it.",
             "Every top-level name must be unique across the files — a second definition silently replaces the first (KI-413).",
             "No regex anywhere: SQL is read and changed on the SQLGlot tree (sql_ast.py); English through the word matcher (text_match.py).",
             "Every guard exists because of a reported failure; read the comment above it before changing it."]
    f.raw('<div style="position:absolute;left:40px;top:648px;width:1520px;height:180px;background:#FEFCE8;border:1.5px solid #EAB308;border-radius:8px;padding:12px 20px;font-size:13.4px;color:#713F12;line-height:1.75">'
          + "<br>".join(f"{i+1}. {r}" for i, r in enumerate(rules)) + '</div>')
    f.legend(H - 70, [("sw", "purple", "orchestrator"), ("sw", "blue", "loader"), ("sw", "orange", "shared stage file"), ("sw", "gold", "added after the 15-Oct split"),
                      ("sw", "grey", "tests")], "LLD · Pipeline Package")
    return f


def fig20():
    W, H = 1600, 900
    f = Fig(W, H, "Megh One AI — Data Answer Safety and Accuracy Guards",
            "a prose prompt rule is never trusted alone: each wrong-number risk has a prompt rule, an example and a deterministic check in code")
    f.sec(40, 88, "Before the SQL runs")
    pre = [("Live facts in the prompt", "data_facts.py: years held, row and NULL counts read from megh_db every 10 min (D-087)", "blue"),
           ("Reviewed examples", "per-scheme YAML few-shots ranked by IDF (SQL_EXAMPLES_SOURCE = yaml, D-086)", "blue"),
           ("Fixed queries first", "deterministic SQL and the data team's metric catalogue for plain measures (D-071)", "blue"),
           ("Per-scheme rewrites", "known wrong shapes fixed on the SQLGlot tree before execution", "orange")]
    for i, (t, s, fm) in enumerate(pre):
        f.box(40 + i * 385, 112, 365, 86, fm, t, s, ts=15, ss=12.3)
        if i < 3:
            f.arrow([(40 + i * 385 + 365, 155), (40 + (i + 1) * 385 - 2, 155)])
    f.arrow([(1520, 198), (1520, 257), (220, 257), (220, 260)])
    f.sec(40, 238, "At execution (c11 · sql_guard · auth · db)")
    ex = [("SQLGlot guard", "one SELECT / WITH · curated + semantic only · no pg_* · privacy tables refused", "red"),
          ("Role check", "auth.authorize: scheme · district / block · level — again after every repair", "red"),
          ("30B verifier", "Qwen3-Coder reviews the SQL; known false positives filtered", "orange"),
          ("Guarded run", "megh_chatbot → semantic.run_query · LIMIT 1000 · cost cap · 15 s", "purple"),
          ("Repair loop", "≤ 3 repairs · 40 s budget · a repeated SQL is asked once more", "orange")]
    for i, (t, s, fm) in enumerate(ex):
        f.box(40 + i * 308, 262, 290, 92, fm, t, s, ts=15, ss=12.2)
        if i < 4:
            f.arrow([(40 + i * 308 + 290, 308), (40 + (i + 1) * 308 - 2, 308)])
    f.arrow([(1430, 354), (1430, 413), (220, 413), (220, 416)])
    f.sec(40, 394, "After the rows come back (compose_response · guarantees)")
    post = [("Numbers in the rows", "every figure in the answer must appear in the result", "green"),
            ("Figure-to-label", "each figure sits next to the right place / year (E9)", "green"),
            ("Code-written figures", "ranking, compare, trend and breakdown figures written by code; the 9B writes the opening", "green"),
            ("One money formatter", "₹ with Indian grouping + (≈ ₹X crore / lakh); provisional money noted", "green"),
            ("Fallback", "strict retry, then a deterministic shaped answer — never an unchecked number", "grey")]
    for i, (t, s, fm) in enumerate(post):
        f.box(40 + i * 308, 418, 290, 92, fm, t, s, ts=15, ss=12.2)
        if i < 4:
            f.arrow([(40 + i * 308 + 290, 464), (40 + (i + 1) * 308 - 2, 464)])
    f.raw('<div style="position:absolute;left:40px;top:546px;width:740px;height:220px;background:#FEFCE8;border:1.5px solid #EAB308;border-radius:8px;padding:12px 18px;font-size:13.2px;color:#713F12;line-height:1.6">'
          '<b>Honest when the data cannot answer</b><br>• A measure the dataset does not hold is said plainly (registry “not held” list).<br>'
          '• A year the scheme does not hold is answered for the years it has, and said so.<br>• A wrong premise (“why did X fall?” when it rose) is corrected.<br>'
          '• A too-heavy query ends as “please narrow the question”.<br>• Data defects go to the ingestion team as a written note (docs/*_DB_Issues.md).</div>')
    f.raw('<div style="position:absolute;left:820px;top:546px;width:740px;height:220px;background:#F0F9FF;border:1.5px solid #7DD3FC;border-radius:8px;padding:12px 18px;font-size:13.2px;color:#0C4A6E;line-height:1.6">'
          '<b>Measured on 29 Oct 2026</b><br>• Held-out NL→SQL set: 68 / 74 (91.9 %), no regressions.<br>• Live golden data suite 45 / 45 · live knowledge suite 114 / 114.<br>'
          '• Offline: 4,723 pytest passed, 0 failed · 14 / 14 script suites · frontend 78 / 78.<br>'
          '• Every audit row keeps the run trace: SQL, error, examples used, repairs, verifier rejections, outcome.</div>')
    f.legend(H - 70, [("sw", "blue", "prompt inputs"), ("sw", "orange", "rewrite / review"), ("sw", "red", "hard block"), ("sw", "purple", "database guard"),
                      ("sw", "green", "answer check"), ("sw", "grey", "fallback")], "TDD · Accuracy Guards")
    return f

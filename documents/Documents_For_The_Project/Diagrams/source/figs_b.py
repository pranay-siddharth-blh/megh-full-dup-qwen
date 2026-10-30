"""Figures 06-11: use cases, user flow, API, ER, curated model, storage architecture."""
from figlib import Fig, FAM

ORANGE = "#C2410C"
VIO = "#7C3AED"


def _actor(f, x, y, name, sub):
    f.svg.append(f'<g stroke="#1F2937" stroke-width="2.2" fill="none"><circle cx="{x}" cy="{y}" r="15"/>'
                 f'<line x1="{x}" y1="{y+15}" x2="{x}" y2="{y+58}"/><line x1="{x-24}" y1="{y+30}" x2="{x+24}" y2="{y+30}"/>'
                 f'<line x1="{x}" y1="{y+58}" x2="{x-20}" y2="{y+92}"/><line x1="{x}" y1="{y+58}" x2="{x+20}" y2="{y+92}"/></g>')
    f.text(x - 90, y + 98, 180, f"<b style='font-size:15px;color:#0F172A'>{name}</b><br><span style='font-size:11.5px;color:#64748B'>{sub}</span>", 13, "#0F172A", "center")


def _pkg(f, x, y, w, title, col, cases):
    h = 46 + 50 * len(cases) + 8
    f.raw(f'<div style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px;border:1.5px solid #CBD5E1;border-radius:8px;background:#fff"></div>')
    f.raw(f'<div style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:30px;background:{col};border-radius:8px 8px 0 0;color:#fff;font-weight:700;font-size:14px;text-align:center;line-height:30px">{title}</div>')
    for i, c in enumerate(cases):
        new = c.endswith("*")
        c = c.rstrip("*")
        bc = "#B45309" if new else "#2D6BDA"
        bg = "#FFF7E6" if new else "#EEF4FF"
        f.raw(f'<div style="position:absolute;left:{x+38}px;top:{y+44+50*i}px;width:{w-76}px;height:38px;border:1.8px solid {bc};border-radius:50%;background:{bg};'
              f'display:flex;align-items:center;justify-content:center;font-size:13.2px;color:#0F172A">{c}</div>')
    return h


def fig06():
    W, H = 1900, 1150
    f = Fig(W, H, "Megh One AI — Use Case Diagram", "Conversational Analytics Assistant · actors, use cases and «include» / «extend» relationships · ★ = added since v1.0")
    f.grp(300, 96, 1300, 920, "« Megh One AI system »", "#334155", "#F8FAFC", "#94A3B8")
    c1 = 330
    _pkg(f, c1, 140, 400, "Access &amp; Account", "#059669", ["Sign In", "Sign Out", "View My Profile &amp; Scope"])
    _pkg(f, c1, 360, 400, "Ask Questions", "#C2410C", ["Ask Data Question", "Ask Scheme Knowledge Question", "Ask by Voice", "Answer Clarification (chip)",
                                                      "Ask Follow-up Question", "Ask Multi-part Question*", "Ask in Hindi script / Khasi / Garo*", "Stop / Continue / Regenerate"])
    c2 = 760
    _pkg(f, c2, 140, 400, "Answers &amp; Results", "#B45309", ["View Answer Text", "View Chart / Table (switchable)*", "View Generated SQL", "View Sources (knowledge)*",
                                                            "Copy / Export / Read Aloud", "Rate Answer 👍 / 👎*", "Pick Suggested Follow-up"])
    _pkg(f, c2, 560, 400, "Chat History &amp; Home", "#0F766E", ["Open Past Chat", "Rename / Pin / Archive Chat", "Delete Chat", "View Live Scheme Cards*", "Ask About This Chat (recap)*"])
    c3 = 1190
    _pkg(f, c3, 140, 380, "Administration", "#4338CA", ["Manage Users", "Manage Tenants", "View Login Events", "View Conversations", "View Query Audit + Trace*",
                                                        "View Answer Feedback*", "View Schema Catalogue"])
    _pkg(f, c3, 560, 380, "System (automatic)", "#334155", ["Guard Message (rules + model)*", "Authorize SQL Scope", "Run Read-Only SQL", "Check Answer Numbers",
                                                            "Ground Knowledge Answer*", "Record Audit Trail"])
    _actor(f, 150, 220, "Officer", "(state / district / block)")
    _actor(f, 150, 560, "Analyst", "(statewide analysis)")
    _actor(f, 1750, 160, "Administrator", "(admin / tenant / super)")
    _actor(f, 1750, 470, "Model Gateway", "(vLLM · external)")
    _actor(f, 1750, 780, "System", "(security / audit)")
    G = "#94A3B8"
    for tx, ty in ((c1, 175), (c1, 420), (c2, 175), (c2, 600)):
        f.arrow([(185, 260), (tx, ty)], G)
    f.arrow([(150, 552), (150, 340)], "#059669", label="is-a", lpos=(120, 450), lcol="#059669")
    f.arrow([(1715, 200), (1572, 175)], G)
    f.arrow([(1715, 820), (1572, 760)], G)
    f.arrow([(1715, 520), (1572, 640)], G, dash=True)
    f.arrow([(c1 + 362, 423), (c1 + 380, 423), (c1 + 380, 1000), (1170, 1000), (1170, 704), (c3 + 38, 704)], VIO, dash=True,
            label="«include» Authorize SQL Scope · Run Read-Only SQL", lpos=(975, 1000))
    f.arrow([(c1 + 38, 573), (c1 + 14, 573), (c1 + 14, 423), (c1 + 36, 423)], ORANGE, dash=True, label="«extend»", lpos=(c1 + 14, 500))
    f.arrow([(c1 + 362, 523), (c1 + 372, 523), (c1 + 372, 433), (c1 + 364, 433)], VIO, dash=True)
    f.legend(H - 106, [("ln", ("#94A3B8", False), "association"), ("ln", (VIO, True), "«include» (always)"), ("ln", (ORANGE, True), "«extend» (conditional)"),
                       ("ln", ("#059669", False), "generalization (is-a Officer)"),
                       ("txt", None, "<span style='display:inline-block;width:30px;height:16px;border:1.8px solid #B45309;border-radius:50%;background:#FFF7E6;vertical-align:-3px;margin-right:6px'></span>new in v2.0")],
             "LLD · Use Case Diagram", h=46, x=300, w=1300)
    f.text(300, H - 52, 1300, "Every question includes Guard Message, Authorize SQL Scope and Record Audit Trail. Ask Data Question is extended by Answer Clarification only for real ambiguity "
           "(no scheme, a bare “Focus”, a shared place name); a missing place or year is answered statewide / for all years and said so. An Administrator can do everything an Officer can.", 12.3, "#475569")
    return f


def fig07():
    W, H = 1900, 1130
    f = Fig(W, H, "Megh One AI — User Flow (Screen Navigation)", "sign-in → chat console hub → modules · the full question lifecycle · every API call needs a valid token")
    f.pill(800, 82, 300, 40, "Open https://&lt;host&gt;/megh-chat", "#059669")
    f.arrow([(950, 122), (950, 146)])
    f.box(830, 148, 240, 52, "blue", "Sign-in Gate", "username · password", ts=15)
    f.arrow([(950, 200), (950, 222)])
    f.svg.append('<polygon points="950,222 1065,268 950,314 835,268" fill="#FEFCE8" stroke="#C2410C" stroke-width="2"/>')
    f.text(880, 254, 140, "<b style='color:#9A3412'>Credentials valid?</b>", 13.5, "#9A3412", "center")
    f.arrow([(835, 268), (720, 268), (720, 174), (828, 174)], ORANGE, dash=True, label="No — message · 6 tries per 5 min", lpos=(720, 222))
    f.arrow([(950, 314), (950, 348)], label="Yes", lpos=(950, 330))
    f.raw('<div class="b" style="left:740px;top:350px;width:420px;height:62px;background:#1E293B;border-radius:8px;color:#fff"><div class="t" style="font-size:16px;color:#fff">CHAT CONSOLE</div>'
          '<div style="font-size:12.3px;color:#CBD5E1">welcome card · live scheme cards · sidebar · question box · language</div></div>')
    mods = [("Ask a Question", "type, slash command or chip", "blue"), ("Ask by Voice", "microphone · live dictation", "blue"), ("Use-Case Library", "sample questions per scheme", "blue"),
            ("Chat History", "sidebar · search", "blue"), ("Admin Console", "/admin-ui · admin only", "purple"), ("Account &amp; Language", "English · Khasi · Garo · sign out", "blue")]
    acts = ["", "Speak → text placed in the box", "Pick a sample → it is asked", "Open · rename · pin · archive · delete",
            "Overview · Users · Logins · Chats · Audit · Feedback", "Sign out → sign-in gate"]
    for i, (t, s, fm) in enumerate(mods):
        x = 50 + i * 305
        f.arrow([(950, 412), (x + 130, 478)])
        f.box(x, 480, 260, 54, fm, t, s, ts=15)
        if acts[i]:
            f.box(x - 6, 566, 272, 44, "purple" if fm == "purple" else "teal", acts[i], "", ts=13.2)
            f.arrow([(x + 130, 534), (x + 130, 564)])
    f.arrow([(1797, 588), (1870, 588), (1870, 104), (1102, 104)], ORANGE, dash=True, label="back", lpos=(1870, 340))
    f.grp(30, 650, 1840, 360, "Question lifecycle", "#334155")
    f.box(60, 712, 210, 58, "blue", "Type / edit question", "text, voice or chip", ts=15)
    f.arrow([(180, 534), (180, 710)])
    f.arrow([(380, 610), (380, 640), (210, 640), (210, 710)], ORANGE, dash=True)
    f.arrow([(685, 610), (685, 646), (230, 646), (230, 710)], ORANGE, dash=True)
    f.arrow([(270, 741), (308, 741)])
    f.box(310, 712, 250, 58, "teal", "Progress steps", "Understanding … → Writing the answer", ts=15)
    f.arrow([(560, 741), (598, 741)])

    def dia(cx, cy, t):
        f.svg.append(f'<polygon points="{cx},{cy-46} {cx+112},{cy} {cx},{cy+46} {cx-112},{cy}" fill="#FEFCE8" stroke="#C2410C" stroke-width="2"/>')
        f.text(cx - 80, cy - 18, 160, f"<b style='color:#9A3412'>{t}</b>", 13, "#9A3412", "center")
    dia(712, 741, "Real ambiguity?<br>(scheme / place)")
    f.arrow([(824, 741), (866, 741)], label="No", lpos=(845, 724))
    dia(978, 741, "Inside the officer's<br>role scope?")
    f.arrow([(1090, 741), (1128, 741)], label="Yes", lpos=(1109, 724))
    f.box(1130, 712, 230, 58, "teal", "Answer streams in", "draft → checked answer", ts=15)
    f.arrow([(1360, 741), (1392, 741)])
    f.box(1394, 712, 200, 58, "teal", "Chart / table", "SQL · sources · note", ts=15)
    f.arrow([(1594, 741), (1626, 741)])
    f.box(1628, 712, 220, 58, "teal", "Follow-up chips", "copy · read aloud · 👍 / 👎", ts=15)
    f.arrow([(712, 787), (712, 862)], label="Yes", lpos=(712, 822))
    f.box(600, 864, 224, 58, "teal", "Pick a chip or reply", "which scheme / place / level", ts=15)
    f.arrow([(600, 893), (435, 893), (435, 772)], ORANGE, dash=True, label="resumes the paused run", lpos=(505, 893))
    f.arrow([(978, 787), (978, 862)], label="No", lpos=(978, 822))
    f.box(866, 864, 224, 58, "red", "Access denied message", "route = denied", ts=15)
    f.arrow([(1245, 770), (1245, 862)], ORANGE, dash=True)
    f.box(1130, 864, 260, 58, "teal", "Stop · Continue · Regenerate", "edit an earlier question", ts=15)
    f.text(1420, 860, 430, "No place → statewide; no year → all years.<br>The answer says so and offers chips to narrow it.", 12.8, "#475569")
    f.arrow([(1738, 770), (1738, 975), (165, 975), (165, 772)], "#334155", label="ask the next (follow-up) question in the same conversation", lpos=(950, 975))
    f.legend(H - 76, [("sw", "green", "start"), ("sw", "blue", "screen / page"), ("sw", "orange", "decision"), ("sw", "teal", "action"),
                      ("sw", "purple", "admin only"), ("ln", (ORANGE, True), "back / cross-link")], "LLD · User Flow")
    return f


METH = {"GET": "#16A34A", "POST": "#2563EB", "PATCH": "#D97706", "DELETE": "#DC2626"}


def _api_card(f, x, y, w, title, sub, col, rows):
    h = 56 + 32 * len(rows) + 12
    f.raw(f'<div style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px;border:1.5px solid #CBD5E1;border-radius:8px;background:#fff;box-shadow:0 1px 2px #0001"></div>')
    f.raw(f'<div style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:48px;background:{col};border-radius:8px 8px 0 0;color:#fff;padding:5px 14px">'
          f'<div style="font-weight:700;font-size:15px">{title}</div><div style="font-size:11.5px;opacity:.9">{sub}</div></div>')
    for i, (m, p, d, note) in enumerate(rows):
        yy = y + 58 + 32 * i
        new = note.startswith("★")
        f.raw(f'<div style="position:absolute;left:{x+14}px;top:{yy}px;width:58px;height:21px;background:{METH[m]};border-radius:4px;color:#fff;font-size:11px;font-weight:700;text-align:center;line-height:21px">{m}</div>')
        nt = f' <span style="color:{"#B45309" if new else "#C2410C"};font-family:Segoe UI;font-weight:400;font-size:11.5px">· {note}</span>' if note else ""
        f.raw(f'<div style="position:absolute;left:{x+82}px;top:{yy}px;font-family:Consolas,monospace;font-weight:700;font-size:13px;line-height:21px">{p}{nt}</div>')
        f.raw(f'<div style="position:absolute;right:{f.w-x-w+14}px;top:{yy}px;font-size:12.3px;color:#334155;line-height:21px;text-align:right">{d}</div>')
    return h


def fig08():
    W, H = 1900, 980
    f = Fig(W, H, "Megh One AI — API Design (Endpoint Catalogue)",
            "FastAPI · JSON over HTTPS · answers also stream as Server-Sent Events · stateless JWT bearer auth · 36 routes across 7 routers + operations · ★ = new since v1.0")
    f.sec(40, 84, "Request pipeline (every authenticated request)", "#334155")
    steps = [("Browser", "#334155"), ("Security middleware", "#059669"), ("JWT guard (deps.py)", "#0D9488"), ("FastAPI router", "#1D4ED8"),
             ("Conversation layer · LangGraph", "#7C3AED"), ("PostgreSQL · Qdrant · vLLM", "#0F766E")]
    for i, (t, c) in enumerate(steps):
        x = 40 + i * 310
        f.raw(f'<div class="b" style="left:{x}px;top:108px;width:262px;height:48px;background:{c};border-radius:6px;color:#fff;font-weight:700;font-size:14.5px">{t}</div>')
        if i < 5:
            f.arrow([(x + 262, 132), (x + 308, 132)], "#64748B")
    f.text(40, 164, 1820, "no / bad token → 401 · admin route without an admin role → 403 · too many requests → 429 · model busy → 503 · over 60 s → 504 · error bodies never echo the input", 12.5, "#475569", "right")
    c1, c2, c3, cw = 40, 655, 1270, 590
    y = 200
    y += _api_card(f, c1, y, cw, "Query", "prefix /api/query · login required", "#C2410C",
                   [("POST", "/api/query", "Ask (JSON) · language · keep_turns", ""), ("POST", "/api/query/stream", "SSE: step · draft_reset · token · done", ""),
                    ("POST", "/api/query/transcribe", "Voice → text (≤ 10 MB, 90/min)", "")]) + 18
    y += _api_card(f, c1, y, cw, "Authentication", "prefix /api/auth", "#059669",
                   [("POST", "/login", "Username + password → JWT", "public"), ("POST", "/logout", "Record the logout", ""),
                    ("GET", "/me", "My profile and data scope", ""), ("POST", "/bootstrap", "Create the first super_admin", "public, once")]) + 18
    y += _api_card(f, c1, y, cw, "Knowledge Base", "prefix /api/rag", "#0F766E",
                   [("GET", "/status", "KB status (login)", ""), ("POST", "/reingest", "Admin; no effect while KB read-only", "")]) + 18
    _api_card(f, c1, y, cw, "Feedback and Scheme Cards", "login required", "#B45309",
              [("POST", "/api/feedback", "👍 / 👎 on an answer (0 removes)", "★"), ("GET", "/api/scheme-stats", "Live card figures, caller's schemes", "★")])
    y = 200
    y += _api_card(f, c2, y, cw, "Chat History", "prefix /api/history · the officer's own chats only", "#1D4ED8",
                   [("GET", "(index)", "List my chats (pinned first)", ""), ("GET", "/{session_id}", "Turns of one chat", ""), ("PATCH", "/{session_id}", "Rename a chat", ""),
                    ("DELETE", "/{session_id}", "Delete chat + paused run", ""), ("POST", "/{session_id}/pin", "Pin / unpin", ""), ("POST", "/{session_id}/archive", "Archive / unarchive", "")]) + 18
    _api_card(f, c2, y, cw, "Operations and Pages", "no prefix", "#475569",
              [("GET", "/health", "Status; components for admin / token", "public"), ("GET", "/metrics", "Counters · accuracy · guardrail · data facts", ""),
               ("GET", "/", "Redirect to /megh-chat", "public"), ("GET", "/megh-chat", "Chat console (React)", "public"), ("GET", "/admin-ui", "Admin console (React)", "public"),
               ("GET", "/ai-query", "301 → /megh-chat (old link)", "public")])
    _api_card(f, c3, 200, cw, "Administration", "prefix /admin · admin JWT · tenant-scoped", "#4338CA",
              [("GET", "/tenants", "List tenants", ""), ("POST", "/tenants", "Create tenant (super_admin)", ""), ("GET", "/roles", "Role list", ""),
               ("GET", "/users", "List users", ""), ("GET", "/users/{id}", "One user", ""), ("POST", "/users", "Create user (validated)", ""),
               ("PATCH", "/users/{id}", "Update role / scope / password", ""), ("DELETE", "/users/{id}", "Deactivate (hard: super_admin)", ""),
               ("GET", "/logins", "Login events", ""), ("GET", "/conversations", "Conversations", ""), ("GET", "/conversations/{id}", "Turns of one conversation", ""),
               ("GET", "/audit", "Query audit + run trace", ""), ("GET", "/feedback", "Answer feedback + totals", "★"), ("GET", "/stats", "Usage statistics", ""),
               ("GET", "/schema", "Live schema catalogue", "")])
    items = [("txt", None, f"<span style='display:inline-block;width:52px;height:20px;background:{c};border-radius:4px;color:#fff;font-size:11px;font-weight:700;text-align:center;line-height:20px;margin-right:6px'>{m}</span>{d}")
             for m, c, d in (("GET", METH["GET"], "read / page"), ("POST", METH["POST"], "create / action"), ("PATCH", METH["PATCH"], "update"), ("DELETE", METH["DELETE"], "remove"))]
    items.append(("txt", None, "<span style='color:#C2410C'>• public = no login needed · ★ new since v1.0 · /docs only when ENV=dev</span>"))
    f.legend(H - 66, items, "LLD · API Design")
    return f


def fig09():
    W, H = 1760, 1100
    f = Fig(W, H, "Megh One AI — Entity-Relationship Diagram (application schema)",
            "PostgreSQL megh_db · schema app · 7 application tables created by appdb.ensure_schema + 4 LangGraph checkpoint tables · ★ = added since v1.0")
    f.sec(40, 90, "Accounts and sign-in"); f.sec(470, 90, "Conversations"); f.sec(910, 90, "Audit and feedback"); f.sec(1330, 90, "LangGraph checkpointer")
    P = "#7C3AED"; B = "#1D4ED8"; D = "#334155"; O = "#C2410C"; GD = "#B45309"
    t = f.ent(40, 116, 340, "tenants", P, [("pk", "tenant_id (identity)"), "UK code (e.g. RD)", "name", "is_active", "created_at"])
    u = f.ent(40, 330, 340, "users", P, [("pk", "user_id (identity)"), ("fk", "tenant_id → tenants"), "UK username", "password_hash (PBKDF2)", "name", "role (8 roles)",
                                         "districts · blocks · schemes TEXT[]", "granularity_cap", "is_active", "created_by · created_at · last_login_at"])
    l = f.ent(40, 720, 340, "login_events", P, [("pk", "id (identity)"), "tenant_id · user_id (logical)", "username", "event login_ok / login_fail / logout / bootstrap",
                                                "ok", "ip · user_agent", "detail", "created_at"])
    c = f.ent(470, 116, 370, "conversations", B, [("pk", "conv_id (identity)"), "tenant_id · user_id (logical)", "UK session_id", "title", "started_at · last_at · turn_count",
                                                  "pinned · pinned_at", "archived · archived_at", "summary · summary_updated_at", "context_state JSONB (rev-guarded):",
                                                  "&nbsp;&nbsp;scope · last turn · pending pause", "&nbsp;&nbsp;topics (≤ 8) + ledger (20 each)"])
    tr = f.ent(470, 520, 370, "conversation_turns", B, [("pk", "id (identity)"), ("fk", "conv_id → conversations"), "tenant_id · user_id · session_id",
                                                        "question · rewritten_question", "answer", "route · intent", "schemes TEXT[] · resolved_entities JSONB",
                                                        "sql (final SQL)", "row_count · allowed · denied_by", "latency_ms", "response JSONB (full payload)", "created_at"])
    a = f.ent(910, 116, 370, "query_audit", D, [("pk", "id (identity)"), "tenant_id · user_id · username", "session_id", "question · rewritten_question",
                                                "route · granularity · schemes TEXT[]", "allowed · denied_by", "row_count · latency_ms · ip", "created_at",
                                                ("new", "sql_text · error_text"), ("new", "few_shot_ids JSONB"), ("new", "repairs · verifier_rejections"),
                                                ("new", "outcome · request_id")])
    fb = f.ent(910, 520, 370, "answer_feedback  ★", GD, [("pk", "feedback_id (bigserial)"), "tenant_id · user_id · username", "session_id", "UK (user_id, message_key)",
                                                         "question · answer", "route · schemes TEXT[]", "citations JSONB", "rating −1 / +1", "comment", "created_at · updated_at"])
    k1 = f.ent(1330, 116, 390, "checkpoints", O, [("pk", "thread_id (= session_id)"), ("pk", "checkpoint_ns"), ("pk", "checkpoint_id"), "parent_checkpoint_id", "type",
                                                  "checkpoint JSONB", "metadata JSONB"])
    k2 = f.ent(1330, 340, 390, "checkpoint_blobs", O, [("pk", "thread_id · checkpoint_ns"), ("pk", "channel · version"), "type", "blob BYTEA"])
    k3 = f.ent(1330, 500, 390, "checkpoint_writes", O, [("pk", "thread_id · checkpoint_ns · checkpoint_id"), ("pk", "task_id · idx"), "channel · type", "blob BYTEA", "task_path"])
    k4 = f.ent(1330, 680, 390, "checkpoint_migrations", O, [("pk", "v (schema version)")])
    f.arrow([(210, 330), (210, 266)], "#475569", label="belongs to (N → 1)", lpos=(290, 298))
    f.arrow([(470, 300), (420, 300), (420, 450), (382, 450)], "#94A3B8", dash=True, label="owner", lpos=(420, 375))
    f.arrow([(210, 718), (210, 594)], "#94A3B8", dash=True, label="user_id", lpos=(260, 656))
    f.arrow([(655, 520), (655, 386)], "#475569", label="turns of (N → 1)", lpos=(725, 455))
    f.arrow([(910, 190), (842, 190)], "#94A3B8", dash=True, label="session_id", lpos=(876, 170))
    f.arrow([(910, 640), (842, 640)], "#94A3B8", dash=True, label="session_id", lpos=(876, 620))
    f.arrow([(842, 420), (880, 420), (880, 486), (1300, 486), (1300, 160), (1328, 160)], "#94A3B8", dash=True, label="thread_id = session_id (paused runs only)", lpos=(1090, 486))
    f.arrow([(1525, 290), (1525, 338)], "#475569")
    f.arrow([(1525, 432), (1525, 498)], "#475569")
    f.raw('<div style="position:absolute;left:1330px;top:770px;width:390px;height:196px;background:#FEFCE8;border:1.5px solid #EAB308;border-radius:8px;padding:12px 14px;font-size:12.5px;color:#713F12;line-height:1.5">'
          '<b>Notes</b><br>• The app creates only the app schema, at start-up, with CREATE TABLE / ADD COLUMN IF NOT EXISTS.<br>'
          '• Two real foreign keys; the other links are logical.<br>• Topic memory is not a table: it lives in conversations.context_state.<br>'
          '• Retention: CONVERSATION_RETENTION_DAYS and QUERY_AUDIT_RETENTION_DAYS (0 = keep; KI-430 open).<br>'
          '• Each audit row is mirrored to a JSONL file.</div>')
    f.legend(H - 70, [("sw", "purple", "accounts"), ("sw", "blue", "conversations"), ("sw", "grey", "audit"), ("sw", "gold", "feedback"), ("sw", "orange", "checkpoints"),
                      ("ln", ("#475569", False), "foreign key (N → 1)"), ("ln", ("#94A3B8", True), "logical link"),
                      ("txt", None, "<span style='color:#B45309;font-weight:600'>★ new since v1.0</span>")], "LLD · ER Diagram")
    return f


def fig10():
    W, H = 1760, 1000
    f = Fig(W, H, "Megh One AI — Scheme Data Model (megh_db.curated, read-only)",
            "star schema owned by the ingestion team · generated SQL queries only the v_* views · six schemes + cross-scheme views")
    S = "#475569"
    f.sec(40, 86, "Shared dimensions")
    f.ent(40, 110, 330, "dim_geography", S, [("pk", "geography_key (surrogate)"), "UK village_code (LGD)", "lgd_village_name", "lgd_block · lgd_district (UPPERCASE)",
                                              "ac_number · ac_name", "entity_type (incl. 'Unresolved')", "on_roster · has_geo_conflict"])
    f.ent(400, 110, 300, "dim_year", S, [("pk", "year_key (FY start year)"), "financial_year '2023-2024'", "financial_year_short '2023-24'", "data_quality_note"])
    f.ent(730, 110, 300, "dim_scheme", S, [("pk", "scheme_key"), "scheme_code ('PMAY' = PMAY-G)", "money_unit", "time_semantics"])
    f.ent(1060, 110, 300, "dim_geography_alias", S, ["source spelling", ("fk", "geography_key → dim_geography"), "+ bridge_geography_source", "+ v_data_coverage"])
    f.ent(1390, 110, 330, "scheme-specific dimensions", S, ["dim_cm_elevate_scheme (15 rows)", "dim_cm_elevate_disb_scheme (13)", "dim_producer_group", "dim_pg_entity_type"])
    f.line(60, 330, 1700, 330, "#94A3B8", "6 4", 1.6)
    f.tag(880, 330, "views pre-join geography_key · year_key · scheme_key", "#334155")
    for x in (205, 550, 880):
        f.line(x, 300 if x != 205 else 300, x, 330, "#94A3B8", "6 4", 1.6)
    views = [("MGNREGA", "#1D4ED8", ["v_employment", "v_expenditure", "v_district_year_summary", "grain: source row (village-year)", "money: LAKH ₹ (verified)", "FY 2022-23 … 2025-26"]),
             ("PMAY-G", "#0F766E", ["v_pmay", "v_pmay_monthly_sanctions (crore)", "grain: one sanctioned house", "money: ₹ (verified)", "year_key 2017 … 2023"]),
             ("Focus Plus", "#7C3AED", ["v_focus_plus", "grain: member × tranche payment", "money: ₹, provisional", "FY 2022-23 · 2025-26"]),
             ("CM Elevate", "#B45309", ["v_cm_elevate", "grain: one application", "money: none", "years: none"]),
             ("Focus Legacy", "#BE185D", ["v_focus_legacy", "grain: payment to a producer group", "₹5,000 per PG member, provisional", "FY 2021-22, 22-23, 24-25, 25-26"]),
             ("CM Elevate Legacy", "#C2410C", ["v_cm_elevate_disbursement", "grain: sanction + disbursement", "money: ₹, provisional", "FY 2024-25 · 2025-26"]),
             ("Cross-scheme", "#334155", ["v_cross_scheme_money_district_year", "v_cross_scheme_village_coverage", "MGNREGA + PMAY-G only", "money: crore"])]
    for i, (n, c, rows) in enumerate(views):
        x = 40 + i * 242
        f.line(x + 115, 330, x + 115, 356, "#94A3B8", "6 4", 1.6)
        f.ent(x, 358, 232, n, c, rows)
    f.sec(40, 560, "Query views above — the only objects the SQL model is allowed to use")
    f.sec(40, 600, "Semantic catalogue and database functions")
    f.ent(40, 624, 560, "semantic.*", S, ["table_catalog · column_catalog — what each table / column means", "glossary — business terms",
                                          "metric_definitions — the data team's measures (metric catalogue, D-071)", "v_join_rules · join_graph — allowed joins",
                                          "check_query(sql) — plan pre-check before a generated query (D-072)", "run_query(sql, rows, cost) — runs generated SQL for megh_chatbot (D-073)"])
    f.sec(640, 600, "Privacy boundary — never queried", "#DC2626")
    f.ent(640, 624, 520, "privacy tables (personal data)", "#DC2626", ["fact_focus_legacy_disbursement — unmasked bank account numbers",
                                                                      "bridge_pg_bank_history — account holder names", "fact_cm_elevate_disbursement — applicant names",
                                                                      "Focus Plus member_key · pincode (person level)", "refused by sql_guard.PRIVATE_TABLES + read-only roles"])
    f.raw('<div style="position:absolute;left:1200px;top:624px;width:520px;height:190px;background:#FEFCE8;border:1.5px solid #EAB308;border-radius:8px;padding:12px 16px;font-size:13px;color:#713F12;line-height:1.55">'
          '<b>Rules that stop a wrong number</b><br>• Never join one fact to another (fan-out).<br>• District / block names are UPPERCASE; count villages by code.<br>'
          '• year_key is the FY start year (2023 ⇒ FY 2023-24).<br>• Never mix money units in one SUM (lakh / ₹ / crore).<br>• The whole dataset is Meghalaya: no state filter.</div>')
    f.text(40, 842, 1680, "Geography: State → 12 districts → C&amp;RD blocks → villages (LGD codes). Assembly constituencies cut across blocks and are read from dim_geography.ac_name.<br>"
           "Years held per scheme, the column catalogue and the metric catalogue are re-read from the database every 30 minutes; the figures quoted in the SQL prompt every 10 minutes (data_facts).", 13, "#475569")
    f.legend(H - 66, [("sw", "grey", "dimension"), ("sw", "blue", "scheme view"), ("sw", "red", "privacy table"), ("ln", ("#94A3B8", True), "join by surrogate key")], "Data Model")
    return f


def fig11():
    W, H = 1880, 1210
    f = Fig(W, H, "Megh One AI — Database and Storage Architecture",
            "PostgreSQL megh_db (curated · semantic · app) through three logins + Qdrant vector store on 10.48.242.4 · seven layers", dark=True)

    def card(x, y, w, title, col, rows):
        h = 34 + 20 * len(rows) + 12
        items = "".join(f'<div style="padding:1px 12px;font-size:12.3px;color:{"#FCD34D" if r.startswith("!") else ("#93C5FD" if r.startswith("~") else "#E2E8F0")}">• {r.lstrip("!~")}</div>' for r in rows)
        f.raw(f'<div style="position:absolute;left:{x}px;top:{y}px;width:{w}px;height:{h}px;background:#16213A;border:1px solid #334155;border-radius:6px;overflow:hidden">'
              f'<div style="background:{col};color:#fff;font-weight:700;font-size:13.5px;padding:6px 12px">{title}</div><div style="padding-top:6px">{items}</div></div>')
        return h

    def lay(y, t, col):
        f.raw(f'<div class="sec" style="left:40px;top:{y}px;color:{col};font-size:13px">{t}</div>')
    lay(92, "Layer 0 — database logins (who may touch what)", "#F472B6")
    for i, (t, rows) in enumerate([("megh_app — DATABASE_URL", ["owns the app.* schema", "SELECT on curated / semantic", "the app's own parameter-bound SQL only"]),
                                   ("megh_readonly — READONLY_DATABASE_URL", ["SELECT on curated + semantic only", "default_transaction_read_only = on", "fixed queries · catalogue reads · 30 s"]),
                                   ("megh_chatbot — CHATBOT_DATABASE_URL", ["generated SQL only, via semantic.run_query", "row cap 1,000 · cost cap 1,000,000", "after the SQLGlot guard + role check"])]):
        card(40 + i * 610, 116, 590, t, "#BE185D", rows)
    lay(232, "Layer 1 — shared dimensions (curated · read-only)", "#60A5FA")
    for i, (t, rows) in enumerate([("dim_geography", ["!geography_key (PK)", "village_code (LGD)", "lgd_district · lgd_block · ac_name"]), ("dim_year", ["!year_key (PK)", "financial_year", "financial_year_short"]),
                                   ("dim_scheme", ["!scheme_key (PK)", "scheme_code · money_unit", "time_semantics"]), ("dim_geography_alias", ["source spelling", "~geography_key → dim_geography"]),
                                   ("bridge_geography_source · v_data_coverage", ["village × source coverage", "what each scheme covers"])]):
        card(40 + i * 366, 256, 350, t, "#1D4ED8", rows)
    lay(372, "Layer 2 — scheme query views (curated · read-only · the only objects generated SQL may use)", "#34D399")
    for i, (t, rows) in enumerate([("MGNREGA", ["v_employment · v_expenditure", "v_district_year_summary", "money in lakh ₹"]), ("PMAY-G", ["v_pmay", "v_pmay_monthly_sanctions", "one row per house"]),
                                   ("Focus Plus", ["v_focus_plus", "member × tranche", "₹ provisional"]), ("CM Elevate", ["v_cm_elevate", "applications", "no money / dates"]),
                                   ("Focus Legacy", ["v_focus_legacy", "producer-group payments", "₹ provisional"]), ("CM Elevate Legacy", ["v_cm_elevate_disbursement", "sanctions + disbursements", "₹ provisional"]),
                                   ("Cross-scheme", ["v_cross_scheme_money_…", "v_cross_scheme_village_…", "crore"])]):
        card(40 + i * 262, 396, 250, t, "#059669", rows)
    lay(512, "Layer 3 — semantic catalogue, database functions and privacy boundary", "#A78BFA")
    card(40, 536, 600, "semantic.* (read by schema_introspect, metric_catalog, data_facts)", "#7C3AED",
         ["table_catalog · column_catalog · glossary", "metric_definitions · v_join_rules · join_graph", "check_query() plan pre-check · run_query() guarded runner"])
    card(660, 536, 640, "privacy tables — NEVER queried (refused by sql_guard)", "#DC2626",
         ["fact_focus_legacy_disbursement (account numbers)", "bridge_pg_bank_history (holder names)", "fact_cm_elevate_disbursement (applicant names)"])
    card(1320, 536, 520, "raw · staging · meta", "#475569", ["ingestion-team internals", "no grant to the read-only logins"])
    lay(652, "Layer 4 — application (app · read / write by the service through megh_app)", "#FB923C")
    for i, (t, rows) in enumerate([("tenants", ["!tenant_id (PK)", "code · name"]), ("users", ["!user_id (PK)", "~tenant_id → tenants", "role · scope arrays"]),
                                   ("login_events", ["!id (PK)", "event · ok · ip"]), ("conversations", ["!conv_id (PK)", "session_id (unique)", "context_state JSONB (rev)"]),
                                   ("conversation_turns", ["!id (PK)", "~conv_id → conversations", "question · answer · sql · response"]),
                                   ("query_audit", ["!id (PK)", "route · allowed · latency", "run trace: sql · repairs · outcome"]),
                                   ("answer_feedback ★", ["!feedback_id (PK)", "rating −1 / +1 · citations", "unique per user + message"])]):
        card(40 + i * 262, 676, 250, t, "#D97706", rows)
    lay(812, "Layer 5 — LangGraph checkpoints (app · paused clarification runs, shared by both VMs)", "#FB7185")
    for i, (t, rows) in enumerate([("checkpoints", ["!thread_id (PK) = session_id", "!checkpoint_id (PK)", "checkpoint JSONB"]), ("checkpoint_blobs", ["!thread_id · channel (PK)", "blob BYTEA"]),
                                   ("checkpoint_writes", ["!thread_id · task_id (PK)", "channel · blob"]), ("checkpoint_migrations", ["!v (PK)"])]):
        card(40 + i * 460, 836, 440, t, "#BE123C", rows)
    lay(952, "Layer 6 — vector store (Qdrant · http://10.48.242.4:6333 · read-only to the app · qwen3-embedding 1024-dim)", "#22D3EE")
    card(40, 976, 900, "megh_knowledge (QDRANT_COLLECTION · QDRANT_KB_READ_ONLY = true)", "#0E7490",
         ["scheme reference documents and FAQs, loaded by another pipeline", "payload: text · source_file · section · doc_title · scheme[] (exact scheme filter)",
          "dense search, several wordings fused (RRF) → qwen3-reranker → tiered answer"])
    card(960, 976, 880, "megh_sql_metadata (SQL_EXAMPLES_COLLECTION)", "#0E7490",
         ["question → SQL examples + view / join notes", "read only when SQL_EXAMPLES_SOURCE = qdrant (default yaml, D-086)",
          "conversation memory collection: off (CONTEXT_SEMANTIC_MEMORY_ENABLED = false)"])
    f.legend(H - 80, [("txt", None, f"<span class='sw' style='background:{c};border-color:{c}'></span>{t}") for c, t in
                      (("#BE185D", "LOGINS"), ("#1D4ED8", "SHARED DIMENSIONS"), ("#059669", "QUERY VIEWS"), ("#7C3AED", "CATALOGUE"), ("#DC2626", "PRIVACY"),
                       ("#D97706", "APPLICATION"), ("#BE123C", "CHECKPOINTS"), ("#0E7490", "VECTOR STORE"))], "Database Design", h=50)
    return f

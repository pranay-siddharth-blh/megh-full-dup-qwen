"""Build the v2 Jira backlog (3 epics: LangGraph, context memory, chat UI) from the v1 CSV plus the
2026-10-19 changes. Writes jira_backlog_v2.csv and jira_backlog_v2.json next to this file.

Hierarchy: Epic -> Story (user-visible behaviour) / Task (engineering, QA, DevOps).
Sources: meghalaya/docs/DECISIONS.md, KNOWN_ISSUES.md, CURRENT_STATE.md.
"""
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
V1 = os.path.join(HERE, "jira_backlog_langgraph_context_memory.csv")
ME = "harshavardhan.p@simaxsystems.com"
COLS = ["Issue Type", "Issue ID", "Parent ID", "Summary", "Description", "Status", "Priority",
        "Labels", "Components", "Story Points", "Assignee", "Reporter"]

# v1 rows that describe officer-visible behaviour become Stories; the rest stay Tasks.
STORY_IDS = {
    "E1-03", "E1-04", "E1-08",
    "E2-01", "E2-02", "E2-03", "E2-04", "E2-05", "E2-06", "E2-07", "E2-08", "E2-09", "E2-10",
    "E2-11", "E2-13", "E2-14", "E2-18", "E2-19", "E2-20", "E2-22", "E2-23", "E2-24",
}

# Corrections to v1 rows (facts that changed after 2026-10-19 13:30).
PATCH = {
    "E1": {"Status": "In Progress"},
    "E2-07": {
        "Summary": "Longer memory window: 50 turns, 20 per topic, 8-hour idle (D-051 amended)",
        "Description": "SESSION_MAX_TURNS 8 -> 50, CONTEXT_LEDGER_PER_TOPIC 6 -> 20, CONTEXT_IDLE_EXPIRY_SECONDS = "
                       "SESSION_TTL_SECONDS = 28800 (8 h). D-051 (2026-10-18, 4 h) amended by the user 2026-10-19 to 8 h. "
                       "Every deploy .env must carry SESSION_TTL_SECONDS=28800 and SESSION_MAX_TURNS=50 or it keeps the old values.",
    },
    "E2-23": {
        "Status": "Done",
        "Description": "KI-324: a typed 'all of them combined' / 'all' / 'combined' to the MGNREGA year pause now resumes as the "
                       "'All financial years combined' chip (c05 _is_all_years_reply, c14 pause-reply branch). The chip half of the "
                       "report did not hold: the pause already carries five chips. Fixed 2026-10-19.",
    },
}


def row(t, i, parent, summary, desc, status, prio, labels, comp, sp=""):
    return {"Issue Type": t, "Issue ID": i, "Parent ID": parent, "Summary": summary, "Description": desc,
            "Status": status, "Priority": prio, "Labels": labels, "Components": comp, "Story Points": str(sp),
            "Assignee": ME, "Reporter": ME}


NEW = [
    # ---- E1 LangGraph additions
    row("Task", "E1-13", "E1", "Conversation-meta module c15 runs inside graph stages",
        "c15_conversation_meta.py (recap, explain, misread apology, suggest, reason, coverage answers, chart-view requests) is called "
        "from the edge, follow-up, route and finalize stages, never around the graph (standing rule: follow LangGraph). D-052, D-055. Done 2026-10-19.",
        "Done", "High", "langgraph;context", "Backend", 5),
    row("Task", "E1-14", "E1", "Graph node progress events feed the streaming UI",
        "pipeline_graph._observed emits a 'step' event per node through turn_events (ContextVar) so /api/query/stream shows live "
        "progress; non-streaming callers are unchanged. D-039. Done 2026-10-07.",
        "Done", "Medium", "langgraph;streaming", "Backend", 3),
    row("Task", "E1-15", "E1", "Finalize node: briefing-line framing and chart hint for every data answer",
        "node_finalize calls _finish_data_result (thousands separators, closing scope sentence, D-054) and _attach_chart_hint "
        "(D-042), so every path (composer, deterministic facts, fixed query) is framed the same way. Done 2026-10-19.",
        "Done", "Medium", "langgraph;answers", "Backend", 3),
    row("Task", "E1-16", "E1", "Fix graph test isolation leak from test_admin_level_collision",
        "15 tests in tests/test_pipeline_graph.py failed when the admin collision script ran first (module-level stubs leaked a "
        "None pool). The script now restores p.resolve_village, er.resolve_village, p.extract_entity_mentions and "
        "p.constituency_contents. Admin script then graph suite in one process: 48/48. Done 2026-10-19.",
        "Done", "Medium", "langgraph;tests", "QA", 2),

    # ---- E2 context memory additions (2026-10-18 / 10-19)
    row("Story", "E2-26", "E2", "One chat never re-asks the scheme; only a new chat asks (D-055)",
        "A data question with no scheme uses the chat's active scheme (_chat_active_scheme) and is never asked 'which scheme?' "
        "inside a chat. A new chat asks with chips and remembers the reply. Replaces D-045's answer-for-every-scheme default for an "
        "unnamed scheme. Harness scenarios/user_reported_2026_10_19.yaml. Done 2026-10-19.",
        "Done", "Highest", "context;user-rule", "Backend", 5),
    row("Story", "E2-27", "E2", "Same-scheme new question keeps the chat's year and place (KI-331)",
        "A new question on the thread's scheme with no year of its own keeps the thread's year or all-years choice, and its place on "
        "'there' / 'that district' (c14 _same_scheme_context_year). Fixed 2026-10-19.",
        "Done", "High", "context", "Backend", 3),
    row("Story", "E2-28", "E2", "A follow-up that only changes the measure drops the old measure (KI-334)",
        "After 'PMAY-G houses completed in Ri Bhoi 2023-24', 'how many beneficiaries are there?' no longer carries 'completed' along. "
        "c14 _pure_measure_change rewrites deterministically. Fixed 2026-10-19.",
        "Done", "High", "context", "Backend", 2),
    row("Story", "E2-29", "E2", "'now give me for cm elevate' after a Legacy answer switches dataset (KI-330)",
        "A bare 'CM Elevate' named as a switch after a CM Elevate Legacy answer goes to the applications dataset; continuing "
        "questions keep the thread rule (cm_elevate._cm_switch_to_applications, c14 pins, c01 swap). Fixed 2026-10-19.",
        "Done", "Medium", "context;cm-elevate", "Backend", 2),
    row("Story", "E2-30", "E2", "Scheme swap after a comparison keeps the comparison (KI-332)",
        "After 'Compare PMAY-G and MGNREGA ...', 'now give me for cm elevate' offers 'Same comparison for CM Elevate ...' chips and "
        "answers the comparison card for that scheme (c01 _comparison_swap, cross_scheme._SAME_COMPARISON). 16 tests. "
        "Fixed and live-verified on 8401, 2026-10-19.",
        "Done", "High", "context;cross-scheme", "Backend", 3),
    row("Story", "E2-31", "E2", "Block in another district replaces the inherited district (KI-327)",
        "Focus Plus Gobekram village (West Garo Hills) -> 'now give me for dambo rongjeng block' now resolves block DAMBO RONGJENG in "
        "East Garo Hills in entities, chips, question text and SQL (c09, c10 _resolved_district_literal). Live: 20,165,000. Fixed 2026-10-19.",
        "Done", "High", "context;entities", "Backend", 3),
    row("Story", "E2-32", "E2", "'compare with pmay' keeps place and year (KI-320)",
        "After an MGNREGA figure, 'compare with pmay' gives the MGNREGA vs PMAY-G table for the same place and year, not PMAY-G alone "
        "over all years; later follow-ups continue the comparison. Fixed 2026-10-18, live-verified through the HTTP API.",
        "Done", "High", "context;cross-scheme", "Backend", 3),
    row("Story", "E2-33", "E2", "Single-year answers never say 'across all financial years' (KI-326)",
        "c12 _finish_answer drops the all-years phrase when the resolved period is one financial year "
        "(_drop_all_years_phrase). 7 tests. Fixed 2026-10-19.",
        "Done", "Low", "context;answers", "Backend", 1),
    row("Story", "E2-34", "E2", "Conversational layer: greetings, names, thanks, callbacks to earlier figures (D-055)",
        "Deterministic wording around result values, no new model call: 'go back to the first one', user name kept for the chat, one "
        "introduction, one steer-back per run of asides, 'You're welcome' with chips, coverage answers (which years / my districts), "
        "'That's down from X in FY ... (about N% lower)'. Tests test_conversational_approach_2026_10_19.py, harness "
        "scenarios/conversational_approach.yaml. Done 2026-10-19.",
        "Done", "High", "context;conversation", "Backend", 8),
    row("Story", "E2-35", "E2", "Verifier no longer rejects a correct by-block breakdown (KI-315)",
        "_verifier_total_vs_breakdown_is_false (c11) discards a false 'total vs breakdown' verdict; a correction turn to PMAY-G "
        "sanctioned by block now answers. Fixed 2026-10-18 evening.",
        "Done", "High", "context;verifier", "Backend", 2),
    row("Task", "E2-37", "E2", "Deploy .env: 8-hour idle window and 50 turns on every server",
        "Every deploy .env must carry SESSION_TTL_SECONDS=28800 and SESSION_MAX_TURNS=50 (.env overrides config.py). Verify on each "
        "host after deploy. Open.",
        "To Do", "High", "context;deploy", "DevOps", 1),

    # ---- E3 chat UI epic
    row("Epic", "E3", "", "Chat UI: React console, streaming answers, charts and responsive design",
        "The officer-facing chat console and admin console in React (D-038), streamed answers with progress, Stop and Regenerate (D-039), "
        "chart hints and full-screen charts/tables (D-042), live scheme cards, chart-view requests, design rules (one scheme = one hue "
        "family, Indian number units) and every feature on every device and browser. Build: npm run build in frontend/, output web/app/.",
        "In Progress", "High", "ui;frontend", "Frontend"),
    row("Story", "E3-01", "E3", "Rebuild the chat and admin consoles in React (D-038)",
        "React 18 + Vite; chat (src/chat) and admin (src/admin) as two entries of one build; original CSS and class names kept; every "
        "API contract, JWT key, session id, history (pin, archive, rename, delete, search), thread replay with charts, voice input, "
        "rail, mobile drawer, language tabs, glossary, use cases and the admin console's five tabs kept. Headless check 53/53. Done 2026-10-07.",
        "Done", "High", "ui;react", "Frontend", 13),
    row("Story", "E3-02", "E3", "Streamed answers with live progress steps, Stop and Regenerate (D-039)",
        "POST /api/query/stream sends SSE step, token, draft_reset, done, error. The streamed text is a muted draft until 'done' replaces "
        "it with the checked answer. Stop cancels the turn; Regenerate / Retry use skip_cache. Fallback to /api/query on 404/405. "
        "nginx unbuffered location. Done 2026-10-07 (offline-verified).",
        "Done", "High", "ui;streaming", "Frontend;Backend", 8),
    row("Story", "E3-03", "E3", "Answer reveal, formatting, smart auto-scroll and connection banner",
        "Fresh answers revealed word by word; answer formatting (lists, tables, numbers); auto-scroll that stops when the officer scrolls "
        "up; a banner when the backend connection drops. Done 2026-10-07 / 10-08 (frontend only).",
        "Done", "Medium", "ui", "Frontend", 5),
    row("Story", "E3-04", "E3", "Chart hint from the backend; charts and tables expand full screen (D-042)",
        "Backend sets chart_type in finalize (typed words win, else rows decide). UI adds Pie; Expand opens any chart or table full "
        "screen; long bar charts turn horizontal; expanded tables get search and sortable columns; row count above every table. Done 2026-10-08.",
        "Done", "Medium", "ui;charts", "Frontend;Backend", 5),
    row("Story", "E3-05", "E3", "'...' actions menu under every answer",
        "Copy, export and related actions in one menu under each answer; works by tap on touch devices. Done 2026-10-09 (browser 9/9).",
        "Done", "Low", "ui", "Frontend", 2),
    row("Story", "E3-06", "E3", "Scheme cards show live megh_db figures (/api/scheme-stats)",
        "Welcome cards read cached live figures from app/routers/stats.py for all six schemes; fallback numbers in constants.js kept in "
        "line with megh_db. Fixes stale PMAY-G 1,71,107 vs 1,70,981. Done 2026-10-15.",
        "Done", "High", "ui;data", "Frontend;Backend", 3),
    row("Story", "E3-07", "E3", "Cross-scheme answers no longer show an empty duplicate table (KI-302)",
        "The chat UI skips its pivot table and charts for cross_scheme results; the flag is stored with the turn for reopened threads. "
        "Done 2026-10-15.",
        "Done", "Low", "ui;cross-scheme", "Frontend", 1),
    row("Story", "E3-08", "E3", "Charts show both dimensions: scheme x year, district x year (KI-325)",
        "TwoDimChart draws the period on the x-axis and one series per scheme or district (Bar, Stacked, Line, Donut) with legend and axes "
        "caption. Headless check 320-1440 px. Done 2026-10-19.",
        "Done", "Medium", "ui;charts", "Frontend", 3),
    row("Story", "E3-09", "E3", "Chart-type requests redraw the last answer (KI-333)",
        "'pie chart', 'But give me only pie chart', 'show as table' redraw the last answer in that view without a backend call "
        "(viewOnlyRequest); a named type shows only that chart; a complaint gets an apology and a wide frame. By-district answers no "
        "longer default to a line. Live + headless verified 2026-10-19.",
        "Done", "High", "ui;charts", "Frontend;Backend", 5),
    row("Story", "E3-10", "E3", "Design rules: one scheme = one hue family, no repeated labels, Indian units",
        "Single-scheme charts use the scheme's hue (SCHEME_HUES) and its shades; categorical colours only for different schemes side by "
        "side; shared prefixes dropped from labels; numbers in Indian units (3,629, 1.7L, 2,185Cr), never 'K'; humanCol chart titles; "
        "taller pie/donut on phones. Done 2026-10-19.",
        "Done", "High", "ui;design", "Frontend", 5),
    row("Story", "E3-11", "E3", "Every feature works on every device and browser",
        "Phones (320 px Android, iPhone SE / Pro Max, landscape), tablets, Windows/Linux/Mac desktops 1024-1920 px, in Chromium, WebKit "
        "and Firefox: hover controls visible on touch, pointerdown outside-tap close, 16 px inputs on iOS, safe-area insets, 100dvh, "
        "Enter = newline on touch, IME-safe send, Ctrl/Cmd shortcuts. Probe tests/ui_devices_probe.py (16 profiles). Done 2026-10-19.",
        "Done", "Highest", "ui;responsive;user-rule", "Frontend;QA", 8),
    row("Story", "E3-12", "E3", "Scheme picker lists only schemes that record what was asked",
        "A new chat with no scheme always gets 'which scheme?', even with a typo (edge _has_domain_typo). The chips list only schemes "
        "holding the measure (c03 _scheme_clarification(by_measure=True), _MEASURE_HOLDERS); one chip per scheme. Done 2026-10-19.",
        "Done", "High", "ui;context;user-rule", "Backend;Frontend", 3),
    row("Story", "E3-13", "E3", "Composer returns to normal height after voice dictation",
        "The auto-grow effect skips the hidden recording box and re-measures when shown, so the composer no longer stays 160 px tall. "
        "Done 2026-10-18.",
        "Done", "Low", "ui;voice", "Frontend", 1),
    row("Task", "E3-14", "E3", "Verify streaming, Stop and Regenerate against the live gateway",
        "D-039 is offline-verified only (gateway stubbed). Run the stream through nginx on the VPN host and confirm tokens arrive "
        "unbuffered, Stop cancels the turn and Regenerate replaces the cached answer. Open.",
        "To Do", "High", "ui;streaming;verification", "QA", 2),
    row("Task", "E3-15", "E3", "Browser check of 'show that as a pie chart' through the live pipeline",
        "D-042 notes the follow-up pie is untested against the live pipeline. Check in /megh-chat with Playwright on phone and desktop. Open.",
        "To Do", "Medium", "ui;charts;verification", "QA", 1),
    row("Task", "E3-16", "E3", "Run ui_devices_probe.py in CI after every frontend build",
        "Add the 16-profile device probe to the pipeline (Chromium, WebKit, Firefox) so a frontend change cannot merge without it. Open.",
        "To Do", "Medium", "ui;ci", "DevOps;QA", 3),
    row("Task", "E3-17", "E3", "Commit the built web/app/ with the frontend source",
        "The React build output web/app/ is kept in the repo so deploys need no Node; commit it together with frontend/ changes. Open.",
        "To Do", "Medium", "ui;deploy", "DevOps", 1),
]


def build():
    with open(V1, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        r = {k: r.get(k, "") for k in COLS}
        if r["Issue Type"] == "Task" and r["Issue ID"] in STORY_IDS:
            r["Issue Type"] = "Story"
        r.update(PATCH.get(r["Issue ID"], {}))
        out.append(r)
    seen = {r["Issue ID"] for r in out}
    for r in NEW:
        if r["Issue ID"] not in seen:
            out.append(r)
    order = {"E1": 0, "E2": 1, "E3": 2}
    out.sort(key=lambda r: (order[r["Issue ID"][:2]], 0 if r["Issue Type"] == "Epic" else 1, r["Issue ID"]))
    with open(os.path.join(HERE, "jira_backlog_v2.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)
    with open(os.path.join(HERE, "jira_backlog_v2.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    return out


if __name__ == "__main__":
    rows = build()
    from collections import Counter
    print(len(rows), "rows")
    for (ep, t, s), n in sorted(Counter((r["Issue ID"][:2], r["Issue Type"], r["Status"]) for r in rows).items()):
        print(ep, t, s, n)

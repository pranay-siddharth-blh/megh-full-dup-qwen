"""
Charts must come back when a conversation is reopened from chat history.

Reported 2026-09-18: a replayed thread showed the answers, tables and SQL but
no graphs. The stored payload was fine — the bug was in the renderer.

buildAnalytics() bumps a MODULE-LEVEL counter (_chartIdx) and writes canvas ids
from it, then returns an init() that actually instantiates the charts.
addBotRich() defers that init() to requestAnimationFrame. Sending one question
builds one turn and fires one callback, so the two always agreed.

Replaying history does not: openConversation() loops over every turn, building
them all synchronously, and only afterwards does the browser run the deferred
callbacks. An init() that re-read _chartIdx therefore saw the LAST turn's value
and looked for a canvas id belonging to a different turn — document.
getElementById returned null, Chart.js drew nothing, and every chart but the
final one silently vanished.

The fix freezes the index per build (`const myIdx = _chartIdx`) so the html and
its own init() agree. The KPI branch was already correct — its init() closes
over the `cid` constant rather than re-reading the counter — and is the pattern
the others now follow.

Static assertions over the React chat app (frontend/src/chat). No browser, model or DB. Plain script (no pytest in the venv):
`python tests/test_history_charts.py`, exit code 0 = all pass.
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# The chat UI is the React app (frontend/, D-038).
_FRONT = _ROOT / "frontend" / "src" / "chat"
_CHARTS = (_FRONT / "components" / "Charts.jsx").read_text(encoding="utf-8")
_MSGS = (_FRONT / "components" / "Messages.jsx").read_text(encoding="utf-8")
_APP = (_FRONT / "App.jsx").read_text(encoding="utf-8")

_fails: list[str] = []


def check(name: str, cond: bool, detail: object = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# ── 1-3. Each chart owns its canvas ───────────────────────────────────────────
# The 2026-09-18 bug: canvases were found by a global id counter that kept
# counting, so a replayed thread drew only its last chart. In the React app a
# chart is created on its OWN canvas element (a ref), never looked up by id, and
# destroyed with it, so every replayed turn draws its charts.
print("1. EACH CHART IS CREATED ON ITS OWN CANVAS (no id lookup)")
_canvas = _CHARTS[_CHARTS.index("function ChartCanvas("):_CHARTS.index("const TYPE_LABELS")]
check("ChartCanvas builds the chart on its ref", "new Chart(ref.current" in _canvas)
check("  and destroys it on unmount", "chart.destroy()" in _canvas)
check("no chart is found by a global canvas id",
      "getElementById" not in _CHARTS and "_chartIdx" not in _CHARTS and "dync_" not in _CHARTS)

print("3. A REPLAY RENDERS EVERY TURN THROUGH THE RICH RENDERER")
check("openConversation replays stored payloads as rich bot turns",
      "kind: 'rich', question: t.question, response: t.response" in _APP)
check("  and each rich turn is rendered by BotMessage", "<BotMessage " in _APP)

# ── 4. The payload history replays from still carries the rows ─────────────
print("4. THE STORED PAYLOAD FEEDS THE CHARTS")
_store = (_ROOT / "app" / "conversation_store.py").read_text(encoding="utf-8")
check("the saved turn payload includes the result rows",
      '"data": result.get("data") or []' in _store)
check("  and the row count the meta line shows", '"row_count": rows,' in _store)
check("history decodes that payload back to an object",
      't["response"] = json.loads(raw)' in _store)
check("the replay path renders stored turns through the rich renderer",
      "kind: 'rich', question: t.question, response: t.response" in _APP)
check("  and charts are only skipped when there are genuinely no rows",
      "Array.isArray(response.data) && response.data.length >= 1" in _MSGS)

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL HISTORY-CHART CHECKS PASSED")

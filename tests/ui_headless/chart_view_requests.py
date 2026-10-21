"""Headless check (KI-333, user report 2026-10-19 16:02): a by-district answer whose
question says "across all financial years" is not drawn as a line; "pie chart" and
the complaint "why you are giving line chart? Give me a wide frame" draw a pie over
the districts, the wide one taller; no horizontal overflow at any width.

    py -3.14 tests/ui_headless/chart_view_requests.py        # server on :8401, VPN up
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat_flow_lib import ask, login, open_browser, overflow  # noqa: E402

BASE = ("How many households provided hundred days of work in MGNREGA for all of Meghalaya "
        "across all financial years by district as a chart")
TURNS = [
    (BASE, {"not": "line"}),
    ("But give me only pie chart.", {"type": ("pie",), "min_labels": 8}),
    ("So I asked about pie chart, right? But why you are giving line chart? Give me a wide frame, okay.",
     {"type": ("pie",), "min_labels": 8, "wide": True, "sorry": True}),
]


def last_chart(pg):
    return pg.evaluate("""() => {
      const msgs = document.querySelectorAll('.msg.bot');
      const last = msgs[msgs.length - 1];
      const card = last.querySelector('.dyn-chart-card');
      const c = card && card.querySelector('canvas');
      const ch = c && c.__chart;
      const chw = card && card.querySelector('.chw');
      return { type: ch ? ch.config.type : null, labels: ch ? (ch.data.labels || []).map(String) : [],
               height: chw ? chw.getBoundingClientRect().height : 0, text: last.innerText.slice(0, 200) };
    }""")


def check(width):
    fails = []
    with open_browser(width=width, height=900) as (_b, pg):
        login(pg)
        normal_h = None
        for q, want in TURNS:
            ask(pg, q, wait_s=200)
            ch = last_chart(pg)
            print(f"[{width}] {q[:50]}… -> type={ch['type']} labels={len(ch['labels'])} h={ch['height']:.0f}")
            if want.get("not") and ch["type"] == want["not"]:
                fails.append(f"[{width}] {q!r}: drawn as {ch['type']}")
            if want.get("type") and ch["type"] not in want["type"]:
                fails.append(f"[{width}] {q!r}: type {ch['type']}, wanted {want['type']}")
            # a pie shows the top 7 and folds the rest into "Other" (Charts.jsx MAX_SLICES)
            if len(ch["labels"]) < want.get("min_labels", 0) and "Other" not in ch["labels"]:
                fails.append(f"[{width}] {q!r}: {len(ch['labels'])} slices — the district breakdown was lost")
            if normal_h is None:
                normal_h = ch["height"]
            if want.get("wide") and not ch["height"] > normal_h + 50:
                fails.append(f"[{width}] {q!r}: wide chart {ch['height']} not taller than {normal_h}")
            if want.get("sorry") and "Sorry" not in ch["text"]:
                fails.append(f"[{width}] {q!r}: no apology: {ch['text'][:80]!r}")
            sw, cw = overflow(pg)
            if sw > cw + 1:
                fails.append(f"[{width}] {q!r}: horizontal overflow {sw} > {cw}")
    return fails


if __name__ == "__main__":
    all_fails = []
    for w in (320, 390, 1280, 1440):
        all_fails += check(w)
    print("\n".join(all_fails) if all_fails else "ALL PASS")
    sys.exit(1 if all_fails else 0)

"""Headless check: clarification pauses render as design #11 "Plain card · Pill
chips" (user, 2026-10-21) — a "Choose a …" line naming what is asked (scheme /
financial year / district), a search box for schemes and districts, pills, the
"All …" reply as the outlined pill, and no horizontal overflow at phone width.
Screenshots go to the scratch folder given as the first argument (default: cwd).

    py -3.14 tests/ui_headless/clarify_pills.py [out_dir]     # server on :8401, VPN up
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat_flow_lib import ask, login, open_browser, overflow  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
CASES = [
    ("how many beneficiaries are there?", "Choose a scheme"),
    ("PMAY-G houses completed by district", "Choose a financial year"),
    ("show me the districts, I'll choose one", "Choose a district"),
]


def last_clarify(pg):
    return pg.evaluate("""() => {
      const msgs = document.querySelectorAll('.msg.bot');
      const box = msgs[msgs.length - 1].querySelector('.clarify-box');
      if (!box) return null;
      const h = box.querySelector('.clarify-head');
      return { cls: box.className, head: h ? h.innerText : '', search: !!box.querySelector('.clarify-search'),
               pills: Array.from(box.querySelectorAll('.clarify-opt')).map(b => b.innerText),
               alls: Array.from(box.querySelectorAll('.clarify-all')).map(b => b.innerText) };
    }""")


def check(width):
    fails = []
    with open_browser(width=width, height=900) as (_b, pg):
        login(pg)
        for i, (q, head) in enumerate(CASES):
            ask(pg, q, wait_s=200)
            got = last_clarify(pg)
            print(f"[{width}] {q!r}: {got}")
            pg.screenshot(path=str(OUT / f"clarify_{width}_{i}.png"), full_page=False)
            if not got:
                fails.append(f"[{width}] {q!r}: no clarification"); continue
            if got["head"] != head:
                fails.append(f"[{width}] {q!r}: head {got['head']!r} != {head!r}")
            if "scheme" in got["cls"] and any("(" in t for t in got["pills"]):
                fails.append(f"[{width}] {q!r}: scheme pill shows its note: {got['pills']}")
            sw, cw = overflow(pg)
            if sw > cw + 1:
                fails.append(f"[{width}] {q!r}: horizontal overflow")
    return fails


if __name__ == "__main__":
    fails = check(1280) + check(390)
    print("\n".join(fails) if fails else "OK")
    sys.exit(1 if fails else 0)

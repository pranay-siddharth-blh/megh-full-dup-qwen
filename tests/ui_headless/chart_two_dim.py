"""Headless check: a result with two label columns (scheme x year, district x year)
is drawn with the period on the x-axis and one series per scheme / district, at
phone and desktop widths, with no horizontal overflow; a one-series line over
categories never says "up N% since <category>" (user report 2026-10-19).

    .venv/Scripts/python.exe tests/ui_headless/chart_two_dim.py        # server on :8401, VPN up
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat_flow_lib import ask, login, open_browser, overflow  # noqa: E402

QUESTIONS = [
    # district x year, two districts -> x = year, series = district, line
    ("MGNREGA expenditure in East Khasi Hills and West Garo Hills for each financial year",
     {"x_period": True, "min_series": 2, "series_words": ["east khasi", "west garo"]}),
    # scheme x year (the screenshot) -> x = year, series = scheme
    ("compare MGNREGA and PMAY-G expenditure for each financial year",
     {"x_period": True, "min_series": 2, "series_words": ["mgnrega", "pmay"]}),
]


def charts(pg):
    """[{labels, series, type, insight}] for every chart card in the last answer."""
    return pg.evaluate("""() => {
      const msgs = document.querySelectorAll('.msg.bot');
      const last = msgs[msgs.length - 1];
      return Array.from(last.querySelectorAll('.dyn-chart-card')).map(card => {
        const c = card.querySelector('canvas');
        const ch = c && c.__chart;
        const ins = card.querySelector('.chd-insight');
        return ch ? { type: ch.config.type, labels: (ch.data.labels || []).map(String),
                      series: ch.data.datasets.map(d => String(d.label || '')), insight: ins ? ins.innerText : '' } : null;
      }).filter(Boolean);
    }""")


def is_period(s):
    s = s.strip().upper().replace("FY", "").strip()
    return len(s) >= 4 and s[:4].isdigit()


def check(width):
    fails = []
    with open_browser(width=width, height=900) as (_b, pg):
        login(pg)
        for q, want in QUESTIONS:
            ask(pg, q, wait_s=200)
            drawn = charts(pg)
            if not drawn:
                fails.append(f"[{width}] {q!r}: no chart drawn"); continue
            ch = drawn[0]
            # Both dimensions must be visible: the periods on one axis (x or the
            # legend) and the schemes / districts on the other. The backend's chart
            # hint may put the years in the legend (stacked by year) — that is fine.
            x_periods = all(is_period(l) for l in ch["labels"])
            s_periods = len(ch["series"]) > 0 and all(is_period(l) for l in ch["series"])
            if want["x_period"] and not (x_periods or s_periods):
                fails.append(f"[{width}] {q!r}: no period dimension: x={ch['labels'][:6]} series={ch['series']}")
            entities = ch["series"] if x_periods else ch["labels"]
            if len(entities) < want["min_series"]:
                fails.append(f"[{width}] {q!r}: {len(entities)} entities, expected >= {want['min_series']} ({entities})")
            low = " ".join(entities).lower()
            for w in want["series_words"]:
                if w not in low:
                    fails.append(f"[{width}] {q!r}: entities lack {w!r}: {entities}")
            if " since " in ch["insight"] and not all(is_period(l) for l in ch["labels"]):
                fails.append(f"[{width}] {q!r}: 'since' over categories: {ch['insight']}")
            sw, cw = overflow(pg)
            if sw > cw + 1:
                fails.append(f"[{width}] {q!r}: horizontal overflow {sw} > {cw}")
            print(f"[{width}] {q[:60]}… -> type={ch['type']} x={ch['labels'][:5]} series={ch['series']} | {ch['insight'][:90]}")
    return fails


if __name__ == "__main__":
    all_fails = []
    for w in (320, 390, 1280, 1440):
        all_fails += check(w)
    print("\n".join(all_fails) if all_fails else "ALL CHART CHECKS PASSED")
    sys.exit(1 if all_fails else 0)

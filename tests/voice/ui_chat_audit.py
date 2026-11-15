"""Visual audit of the CHAT (not the voice stage): every answer shape drawn by Chart.js, the local redraws ("show it as a
bar / line / pie chart / table"), the voice panel on the right (full card, folded, slim rail) at 1366 / 1536 / 1920,
the agent orb, while the answer streams in and once it has settled (2026-11-16, demo eve).

Headless Edge (tests/voice/cdp.py, muted) on /megh-chat, signed in, the real pipeline (VPN). For every answer:
  - while it streams: how many chart canvases were mounted in it (a chart built, thrown away and built again = a
    flicker), the layout shift score while it arrived, no page error;
  - settled: nothing twice (no two chart cards with the same title and figures, no label twice on a chart, one answer
    bubble per question), every chart drawn (ink), chart cards inside their message, no sideways scroll, the voice
    panel never over the messages or the composer, the composer and the orb on screen.
Screenshots per answer and size in the shots folder.

Run from the repo root:  python tests/voice/ui_chat_audit.py [--base URL] [--only name,name]
"""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)
from cdp import Browser  # noqa: E402
from ui_voice import JS, RESULTS, check, mint, silent_wav  # noqa: E402

ARGS = sys.argv[1:]
BASE = ARGS[ARGS.index("--base") + 1] if "--base" in ARGS else "http://127.0.0.1:8401"
ONLY = set(ARGS[ARGS.index("--only") + 1].split(",")) if "--only" in ARGS else None
SHOTS = Path(os.environ.get("TEMP", ".")) / "megh_chat_audit_shots"
SHOTS.mkdir(parents=True, exist_ok=True)
SIZES = [(1366, 768), (1536, 864), (1920, 1080)]

SCRIPT = [
    ("single", "How many PMAY-G houses were sanctioned in total?"),
    ("district", "PMAY-G houses sanctioned by district"),
    ("redraw_bar", "show it as a bar chart"),
    ("redraw_line", "show it as a line chart"),
    ("redraw_pie", "show it as a pie chart"),
    ("redraw_table", "show it as a table"),
    ("block_in_district", "MGNREGA person-days by block in West Garo Hills"),
    ("top_n", "Top 10 blocks by PMAY-G houses completed"),
    ("trend", "MGNREGA person-days by financial year"),
    ("compare", "Compare PMAY-G houses sanctioned in West Garo Hills and East Khasi Hills"),
    ("share", "PMAY-G houses sanctioned by district as a donut chart"),
    ("two_measures", "Focus Plus beneficiaries and amount disbursed by district"),
    ("cross_headline", "Give me the headline figure of every scheme"),
    ("cross_leads", "Which scheme leads in each district?"),
    ("two_schemes", "Compare Focus Plus and CM Elevate Legacy in East Garo Hills, West Garo Hills and South West Garo Hills."),
    ("year_compare", "Compare MGNREGA expenditure in 2022-23 and 2023-24 by district"),
]

AUDIT_JS = JS + r"""
window.__cls = 0;
try { new PerformanceObserver((l) => l.getEntries().forEach(e => { if (!e.hadRecentInput) window.__cls += e.value; }))
  .observe({ type: 'layout-shift', buffered: false }); } catch (e) {}
window.__mountedCv = 0;
new MutationObserver((ms) => ms.forEach(m => m.addedNodes.forEach(n => { if (!n.querySelectorAll) return;
  const last = [...document.querySelectorAll('.msg.bot')].pop();
  if (!last || !last.contains(n)) return;
  window.__mountedCv += (n.tagName === 'CANVAS' ? 1 : 0) + n.querySelectorAll('canvas').length; })))
  .observe(document.body, { childList: true, subtree: true });
window.inkOf = (cv) => { if (!cv || !cv.width) return 0; try { const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
  let n = 0; for (let i = 3; i < d.length; i += 4 * 53) if (d[i] > 8) n++; return n; } catch (e) { return -1; } };
window.done = () => { const b = [...document.querySelectorAll('.msg.bot')]; const last = b[b.length - 1];
  return !!last && !last.querySelector('.typing-bubble, .pending-bubble') && !document.querySelector('.send-btn.stop'); };
window.chatAudit = () => {
  const vw = innerWidth, vh = innerHeight;
  const bots = [...document.querySelectorAll('.msg.bot')];
  const last = bots[bots.length - 1];
  const cards = last ? [...last.querySelectorAll('.dyn-chart-card')] : [];
  const sig = (c) => { const cv = c.querySelector('canvas'); const ch = cv && cv.__chart;
    const t = (c.querySelector('.chd-title, h4, h3, .dyn-chart-title') || {}).textContent || '';
    return t + '|' + (ch ? JSON.stringify([ch.data.labels, ch.data.datasets.map(d => d.data)]) : ''); };
  const sigs = cards.map(sig);
  const dupCards = sigs.filter((s, i) => sigs.indexOf(s) !== i).length;
  const dupLabels = [];
  cards.forEach(c => { const cv = c.querySelector('canvas'); const ch = cv && cv.__chart; if (!ch) return;
    const ls = (ch.data.labels || []).map(l => String(Array.isArray(l) ? l.join(' ') : l).toLowerCase());
    ls.forEach((l, i) => { if (ls.indexOf(l) !== i) dupLabels.push(l); }); });
  const ink = cards.filter(c => c.querySelector('canvas')).map(c => inkOf(c.querySelector('canvas')));   // a compare card has no canvas
  const lr = last ? last.getBoundingClientRect() : null;
  const outCards = lr ? cards.filter(c => { const r = c.getBoundingClientRect(); return r.right > lr.right + 2 || r.left < lr.left - 2; }).length : 0;
  const panel = document.querySelector('.vpanel');
  const vis = (el) => { if (!el) return false; const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity) > 0.05 && r.width > 2 && r.height > 2; };
  const hit = (a, b) => { const x = Math.min(a.right, b.right) - Math.max(a.left, b.left); const y = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top); return x > 2 && y > 2; };
  const overlaps = [];
  if (vis(panel)) {
    const pr = panel.getBoundingClientRect();
    [...document.querySelectorAll('.msg')].forEach((m, i) => { const r = m.getBoundingClientRect(); if (r.bottom > 0 && r.top < vh && hit(pr, r)) overlaps.push('panel x msg' + i); });
    const comp = document.querySelector('textarea.composer-input'); if (comp && hit(pr, comp.getBoundingClientRect())) overlaps.push('panel x composer');
  }
  const orb = document.querySelector('[data-testid=agent-orb]');
  const orbR = orb ? orb.getBoundingClientRect() : null;
  return { n: bots.length, cards: cards.length, dupCards, dupLabels, ink, outCards, overlaps,
    hscroll: document.scrollingElement.scrollWidth > vw + 1,
    panel: vis(panel) ? (panel.className || '') + ' ' + Math.round(panel.getBoundingClientRect().width) : 'hidden',
    orbOk: !!orbR && orbR.left >= 0 && orbR.right <= vw && orbR.top >= 0 && orbR.bottom <= vh,
    text: last ? last.innerText.slice(0, 120) : '', errs: (window.__errs || []).slice() };
};
"""


async def set_size(b, w, h):
    await b.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
    await b.eval("new Promise(r => { window.dispatchEvent(new Event('resize')); setTimeout(r, 900); })")


async def send(b, text):
    await b.eval("(() => { const t = document.querySelector('textarea.composer-input'); t.focus(); })()")
    await b.cmd("Input.insertText", text=text)
    await asyncio.sleep(0.2)
    for kind in ("keyDown", "keyUp"):
        await b.cmd("Input.dispatchKeyEvent", type=kind, key="Enter", code="Enter", windowsVirtualKeyCode=13,
                    nativeVirtualKeyCode=13, **({"text": "\r"} if kind == "keyDown" else {}))


async def ask(b, text):
    n0 = await b.eval("document.querySelectorAll('.msg.bot').length")
    await b.eval("window.__cls = 0; window.__mountedCv = 0;")
    await send(b, text)
    return await b.eval(f"""(async () => {{
        await until(() => document.querySelectorAll('.msg.bot').length > {n0}, 30000);
        await until(() => done(), 170000);
        await sleep(2500);
        const final = [...document.querySelectorAll('.msg.bot')].pop();
        return {{ bots: document.querySelectorAll('.msg.bot').length - {n0}, users: document.querySelectorAll('.msg.user').length,
                 mounted: window.__mountedCv, cv: final ? final.querySelectorAll('canvas').length : 0,
                 cls: Math.round(window.__cls * 1000) / 1000 }}; }})()""", timeout=230)


def judge(tag, a, size_only=False):
    if not size_only:
        check(f"{tag}: nothing twice (no chart card twice, no label twice on a chart)", a["dupCards"] == 0 and not a["dupLabels"],
              (a["dupCards"], a["dupLabels"][:5]))
        check(f"{tag}: every chart drawn", all(x != 0 for x in a["ink"]), a["ink"])
    check(f"{tag}: cards inside their message, no sideways scroll, the panel over nothing, the orb on screen",
          a["outCards"] == 0 and not a["hscroll"] and not a["overlaps"] and a["orbOk"],
          {k: a[k] for k in ("outCards", "hscroll", "overlaps", "orbOk", "panel")})


async def main():
    token = await mint()
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});sessionStorage.removeItem('focusSessionId');"
            "localStorage.removeItem('megh_voice_panel_collapsed');}catch(e){}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));")
    print(f"chat audit on {BASE}, shots in {SHOTS}", flush=True)
    async with Browser(port=9399, mic_wav=silent_wav(), init_js=init, size=(1920, 1080)) as b:
        await set_size(b, 1920, 1080)
        await b.goto(BASE + "/megh-chat", wait=4)
        await b.eval(AUDIT_JS)
        await b.eval("(async () => !!(await until(() => document.querySelector('textarea.composer-input'), 30000)))()")
        await b.eval("sleep(1500)")
        # the welcome screen: the voice panel as a full card / rail at each size, folded and unfolded
        for size in SIZES:
            await set_size(b, *size)
            a = await b.eval("chatAudit()")
            judge(f"welcome @{size[0]}", a, size_only=True)
            print(f"   welcome @{size[0]}: panel {a['panel']}", flush=True)
            await b.shot(str(SHOTS / f"00_welcome_{size[0]}.png"))
        await set_size(b, 1920, 1080)
        for i, (name, q) in enumerate(SCRIPT, 1):
            if ONLY and name not in ONLY:
                continue
            r = await ask(b, q)
            check(f"{i:02d} {name}: one answer, its charts built once while it streamed (no re-mount)",
                  r["bots"] == 1 and r["mounted"] <= max(r["cv"], 0) + 0, r)
            print(f"   {i:02d} {name}: {r}", flush=True)
            for size in [(1920, 1080), (1366, 768), (1536, 864)]:
                if size != (1920, 1080):
                    await set_size(b, *size)
                await b.eval("(() => { const b = [...document.querySelectorAll('.msg.bot')].pop(); if (b) b.scrollIntoView({ block: 'start' }); })()")
                await b.eval("sleep(500)")
                a = await b.eval("chatAudit()")
                judge(f"{i:02d} {name} @{size[0]}", a)
                await b.shot(str(SHOTS / f"{i:02d}_{name}_{size[0]}.png"))
            await set_size(b, 1920, 1080)
            if name == "district":            # the panel folded to its rail and back, in a conversation
                x = await b.eval("(() => { const x = document.querySelector('.vpanel .vp-x'); if (x) x.click(); return !!x; })()")
                await b.eval("sleep(700)")
                a = await b.eval("chatAudit()")
                judge(f"{i:02d} panel folded @1920", a, size_only=True)
                await b.shot(str(SHOTS / f"{i:02d}_panel_folded_1920.png"))
                print(f"      folded: {x} {a['panel']}", flush=True)
                await b.eval("(() => { const p = document.querySelector('.vpanel'); const u = p && (p.querySelector('.vp-unfold, .vp-rail, button')); if (u) u.click(); })()")
                await b.eval("sleep(700)")
        errs = await b.eval("window.__errs")
        check("no page errors", not errs and not [e for e in b.events if e[0] == "exception"], (errs, b.events[:5]))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed · screenshots in {SHOTS}", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

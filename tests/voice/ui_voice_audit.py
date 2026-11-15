"""Visual audit of the voice stage, every answer shape and every chart switch, at three screen sizes (2026-11-16).

The demo-eve audit (the user: "very smooth, immersive, responsive ... no rendering issues, nothing shown twice in the
same visualization"). Same set-up as ui_voice_visual.py: headless Edge on /megh-chat?voicetest=1, signed in, the real
pipeline (VPN), the voice the fake Live (start `python tests/voice/fake_live.py PORT` and the app with
VOICE_LIVE_URL=ws://127.0.0.1:PORT).

For every state of the script (a single figure, by district, by block in a district, a ranking, a trend, a comparison,
a share, two measures, cross-scheme, a table answer; each chart switch on a district answer; back to the dashboard and
the chart again; a follow-up that redraws; a new question while a picture is up; a barge-in mid-reveal) and, once it
has settled, at 1366x768, 1536x864 and 1920x1080:
  - nothing twice: one grid, no ghost layer left, the cards on screen = the planned cards, no two cards alike, no item
    twice on a card, the caption never repeats a sentence, the question is not shown twice;
  - nothing overlaps: the title, the chips, the captions, the cards, the insight, the "Show as" column, the dashboard
    button, the parked orb and its pill, the header and the footer; every one inside the screen; no clipped title;
  - every card drawn (ink on its canvas);
  - no page error; the long animation frames during reveals are reported.
A screenshot per state and size in the shots folder.

Run from the repo root:  python tests/voice/ui_voice_audit.py [--base URL] [--shots DIR] [--only name,name]
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
SHOTS = Path(ARGS[ARGS.index("--shots") + 1]) if "--shots" in ARGS else Path(os.environ.get("TEMP", ".")) / "megh_audit_shots"
SHOTS.mkdir(parents=True, exist_ok=True)
ONLY = set(ARGS[ARGS.index("--only") + 1].split(",")) if "--only" in ARGS else None
SIZES = [(1366, 768), (1536, 864), (1920, 1080)]

# (name, what is said, settle ms). Order matters: the switches act on the answer before them.
SCRIPT = [
    ("single", "How many PMAY-G houses were sanctioned in total?", 9000),     # + the explaining breakdown
    ("district", "PMAY-G houses sanctioned by district", 2500),
    ("sw_map", "show it on the map", 1800),
    ("sw_ranking", "show it as a ranking", 1800),
    ("sw_horizontal", "show it as horizontal bars", 1800),
    ("sw_bar", "show it as a bar chart", 1800),
    ("sw_pie", "show it as a pie chart", 1800),
    ("sw_line", "show it as a line chart", 1800),
    ("sw_table", "show it as a table", 1800),
    ("desk", "go back to the dashboard", 1800),
    ("chart_again", "bring the chart back", 1800),
    ("followup_block", "by block", 2500),
    ("block_in_district", "MGNREGA person-days by block in West Garo Hills", 2500),
    ("top_n", "Top 10 blocks by PMAY-G houses completed", 2500),
    ("most", "Which district has the most PMAY-G houses sanctioned?", 2500),
    ("trend", "MGNREGA person-days by financial year", 2500),
    ("trend_bar", "show it as a bar chart", 1800),
    ("compare", "Compare PMAY-G houses sanctioned in West Garo Hills and East Khasi Hills", 2500),
    ("share", "PMAY-G houses sanctioned by district as a donut chart", 2500),
    ("two_measures", "Focus Plus beneficiaries and amount disbursed by district", 2500),
    ("cross_headline", "Give me the headline figure of every scheme", 2500),
    ("cross_leads", "Which scheme leads in each district?", 2500),
    ("cross_money", "How much money has each scheme disbursed?", 2500),
    ("cross_sw_pie", "show it as a pie chart", 1800),
    ("year_compare", "Compare MGNREGA expenditure in 2022-23 and 2023-24 by district", 2500),
    ("table_answer", "List the blocks of West Garo Hills with their MGNREGA person-days as a table", 2500),
    # the bugs this audit found (2026-11-16), each checked by name below
    ("williamnagar", "For Williamnagar constituency, give me every scheme's figure.", 2500),
    ("two_schemes", "Compare Focus Plus and CM Elevate Legacy in East Garo Hills, West Garo Hills and South West Garo Hills.", 2500),
    ("two_districts", "Compare PMAY-G houses sanctioned in West Garo Hills and East Khasi Hills", 2500),
]

PLAN_JS = """(() => { const p = window.__stagePlan || { cards: [] };
  return p.cards.map(c => ({ kind: c.kind, title: c.title, items: (c.items || []).map(x => ({ label: x.label, value: x.value, sub: x.sub })) })); })()"""


def special(name, cards):
    """The named regressions (2026-11-16 audit)."""
    if name == "williamnagar":
        t = next((c for c in cards if c["kind"] == "tiles"), {"items": []})["items"]
        pairs = [(x["label"], x["value"]) for x in t]
        check("williamnagar: no scheme tile repeats a figure, no tile says just 'value'",
              len(pairs) == len(set(pairs)) and all((x["sub"] or "").lower() != "value" for x in t), t)
    if name in ("cross_headline", "williamnagar"):
        t = next((c for c in cards if c["kind"] == "tiles"), {"items": []})["items"]
        labels = [x["label"] for x in t]
        mg = next((x for x in t if x["label"] == "MGNREGA"), {"sub": ""})
        check(f"{name}: ONE tile per scheme (its second figure on the tile's line), MGNREGA's never called beneficiaries",
              len(labels) == len(set(labels)) and "beneficiar" not in (mg["sub"] or "").lower(), t)
    if name == "two_schemes":
        titles = [c["title"] for c in cards if c["kind"] in ("bars", "race")]
        check("two schemes over the same districts: both schemes drawn",
              any(t.startswith("Focus Plus") for t in titles) and any(t.startswith("CM Elevate Legacy") for t in titles), titles)
    if name == "two_districts":
        t = next((c for c in cards if c["kind"] == "tiles"), {"items": []})["items"]
        check("two districts side by side: at most six tiles, so each says what it counts", 0 < len(t) <= 6 and all(x["sub"] for x in t), t)

AUDIT_JS = JS + r"""
window.__lf = [];
try { new PerformanceObserver((l) => l.getEntries().forEach(e => window.__lf.push({ t: Math.round(e.startTime), d: Math.round(e.duration) })))
  .observe({ type: 'long-animation-frame', buffered: false }); } catch (e) {
  try { new PerformanceObserver((l) => l.getEntries().forEach(e => window.__lf.push({ t: Math.round(e.startTime), d: Math.round(e.duration) })))
    .observe({ type: 'longtask', buffered: false }); } catch (e2) {} }
window.canvasInk = (cv) => { if (!cv || !cv.width) return 0; const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
  let n = 0; for (let i = 3; i < d.length; i += 4 * 53) if (d[i] > 8) n++; return n; };
window.effOpacity = (el) => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) { const s = getComputedStyle(e);
  if (s.display === 'none' || s.visibility === 'hidden') return 0; o *= parseFloat(s.opacity || '1'); } return o; };
window.normT = (s) => String(s || '').toLowerCase().split('').map(c => (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ? c : ' ').join('').split(' ').filter(Boolean).join(' ');
window.audit = () => {
  const vw = innerWidth, vh = innerHeight;
  const host = document.querySelector('.vs-host');
  const parked = !!document.querySelector('.vstage.parked');
  const grids = [...document.querySelectorAll('.vs-stagearea > .vs-grid')];
  const cards = [...document.querySelectorAll('.vs-stagearea > .vs-grid > .vc')];
  const ghosts = document.querySelectorAll('.vs-ghostlayer').length;
  const plan = window.__stagePlan || { cards: [] };
  const dupCards = []; const seenC = new Set();
  cards.forEach(c => { const k = c.dataset.kind + '|' + normT((c.querySelector('h3') || {}).textContent);
    if (seenC.has(k)) dupCards.push(k); seenC.add(k); });
  const dupItems = [];
  (plan.cards || []).forEach(c => { const s = new Set(); (c.items || []).forEach(x => { const k = normT(x.label) + '|' + normT(x.sub) + '|' + (x.value ?? '');
    if (k && s.has(k)) dupItems.push(c.title + ': ' + x.label); s.add(k); }); });
  // the caption: no sentence said twice, the question not twice
  const megh = (document.querySelector('.vs-megh') || {}).textContent || '';
  const sents = megh.split('. ').map(normT).filter(s => s.split(' ').length >= 4);
  const dupSent = sents.filter((s, i) => sents.indexOf(s) !== i);
  const yous = document.querySelectorAll('.vs-captions .vs-you').length;
  const meghs = document.querySelectorAll('.vs-captions .vs-megh').length;
  // what is visible on the stage and must not collide
  const pick = [];
  const add = (name, el) => { if (!el) return; const r = el.getBoundingClientRect(); if (r.width < 2 || r.height < 2) return;
    if (effOpacity(el) < 0.15) return; pick.push({ name, r: { l: r.left, t: r.top, r: r.right, b: r.bottom } , el }); };
  if (parked) {
    const t = document.querySelector('.vs-title'); if (t && t.textContent.trim()) add('title', t);
    add('viewchip', document.querySelector('.vs-viewchip'));
    add('step', document.querySelector('.vs-step'));
    cards.forEach((c, i) => add('card' + i + ':' + c.dataset.kind, c));
    const ins = document.querySelector('.vs-insight.on'); if (ins) add('insight', ins);
    const ks = document.querySelector('.vs-kinds.on'); if (ks) add('kinds', ks);
    add('dock', document.querySelector('.vs-dockclose'));
    add('orb', document.querySelector('.vs-orb-cv'));
    add('park', document.querySelector('.vs-park'));
    const cap = document.querySelector('.vs-captions'); if (cap && cap.textContent.trim()) add('captions', cap);
  } else {
    const ans = document.querySelector('.vs-anscard'); if (ans) add('answercard', ans);
    add('captions', document.querySelector('.vs-captions'));
    add('orb', document.querySelector('.vs-orb-cv'));
    add('composer', document.querySelector('.vs-composer'));
  }
  add('header', document.querySelector('.vs-top'));
  add('footer', document.querySelector('.vs-feed'));
  const ALLOW = new Set(['orb|park', 'park|orb']);
  const overlaps = [];
  for (let a = 0; a < pick.length; a++) for (let b = a + 1; b < pick.length; b++) {
    const A = pick[a], B = pick[b];
    if (ALLOW.has(A.name + '|' + B.name)) continue;
    if (A.el.contains(B.el) || B.el.contains(A.el)) continue;
    const x = Math.min(A.r.r, B.r.r) - Math.max(A.r.l, B.r.l); const y = Math.min(A.r.b, B.r.b) - Math.max(A.r.t, B.r.t);
    if (x > 3 && y > 3) overlaps.push(A.name + ' x ' + B.name + ' (' + Math.round(x) + 'x' + Math.round(y) + ')');
  }
  const outside = pick.filter(p => p.r.l < -1 || p.r.t < -1 || p.r.r > vw + 1 || p.r.b > vh + 1)
    .map(p => p.name + ' ' + JSON.stringify(Object.fromEntries(Object.entries(p.r).map(([k, v]) => [k, Math.round(v)]))));
  // clipped text (a hard cut, not an ellipsis the eye can read as "more")
  const clipped = [];
  const textEls = [['title', document.querySelector('.vs-title')], ...cards.map((c, i) => ['h3#' + i, c.querySelector('h3')]),
    ...cards.map((c, i) => ['note#' + i, c.querySelector('.vc-note')]), ['insight', document.querySelector('.vs-insight.on')],
    ['viewchip', document.querySelector('.vs-viewchip')]];
  textEls.forEach(([n, el]) => { if (!el || !parked || effOpacity(el) < 0.15) return;
    if (el.scrollWidth > el.clientWidth + 2) clipped.push(n + ' ' + el.scrollWidth + '>' + el.clientWidth + (getComputedStyle(el).textOverflow === 'ellipsis' ? ' (ellipsis)' : ' (CUT)'));
    if (el.scrollHeight > el.clientHeight + 3 && getComputedStyle(el).overflowY !== 'visible' && getComputedStyle(el).overflowY !== 'auto') clipped.push(n + ' height ' + el.scrollHeight + '>' + el.clientHeight); });
  // a card's canvas fits its body (never drawn beyond it)
  const cvBad = cards.filter(c => { const cv = c.querySelector('canvas'); const bd = c.querySelector('.vc-body'); if (!cv || !bd) return false;
    const a = cv.getBoundingClientRect(), b = bd.getBoundingClientRect(); return a.right > b.right + 2 || a.bottom > b.bottom + 2 || a.height < 40; })
    .map(c => c.dataset.kind);
  return { parked, vw, vh, grids: grids.length, cards: cards.map(c => c.dataset.kind),
    planned: cards.filter(c => !c.classList.contains('vc-explain')).map(c => c.dataset.kind),
    explains: cards.filter(c => c.classList.contains('vc-explain')).length, planCards: (plan.cards || []).map(c => c.kind),
    titles: cards.map(c => (c.querySelector('h3') || {}).textContent || ''), ghosts, dupCards, dupItems, dupSent, yous, meghs,
    overlaps, outside, clipped, cvBad, ink: cards.map(c => canvasInk(c.querySelector('canvas'))),
    title: (document.querySelector('.vs-title') || {}).textContent || '', chip: (document.querySelector('.vs-viewchip') || {}).innerText || '',
    megh: megh.slice(0, 160), errs: (window.__errs || []).slice() };
};
"""


async def set_size(b, w, h):
    await b.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=False)
    await b.eval("(async () => { window.dispatchEvent(new Event('resize')); await new Promise(r => setTimeout(r, 900)); })()")


async def ask(b, text, settle):
    t0 = await b.eval("performance.now()")
    await b.eval("window.__lf = []")
    await b.eval(f"window.__meghVoice.say({json.dumps(text)})")
    r = await b.eval(f"""(async () => {{
        const rep = await until(() => vlog().filter(e => e.type === 'reply' && e.t > {t0} && e.kind !== 'superseded').pop(), 170000);
        await until(() => vlog().some(e => e.type === 'turn_complete' && e.t > (rep ? rep.t : {t0})), 40000);
        await until(() => !window.__meghVoice.playing(), 40000);
        await sleep({settle});
        return {{ kind: rep ? rep.kind : null, speak: rep ? (rep.speak || '').slice(0, 140) : '',
                 long: window.__lf.filter(x => x.d >= 50), worst: Math.max(0, ...window.__lf.map(x => x.d)) }}; }})()""",
                       timeout=260)
    return r


def judge(name, size, a):
    w, h = size
    tag = f"{name} @{w}x{h}"
    if a["parked"]:
        # the plan's cards, plus at most one card that explains a single figure (it joins the picture it explains)
        check(f"{tag}: one grid, no ghost left, cards = plan", a["grids"] == 1 and a["ghosts"] == 0
              and a["planned"] == a["planCards"] and a["explains"] <= 1, {k: a[k] for k in ("grids", "ghosts", "cards", "planCards")})
        check(f"{tag}: nothing twice (cards, items, sentences, question)", not a["dupCards"] and not a["dupItems"]
              and not a["dupSent"] and a["yous"] <= 1 and a["meghs"] <= 1,
              {k: a[k] for k in ("dupCards", "dupItems", "dupSent", "yous", "meghs")})
        check(f"{tag}: every card drawn, its canvas inside its body", all(x > 30 for x in a["ink"]) and not a["cvBad"],
              (a["ink"], a["cvBad"]))
        check(f"{tag}: no clipped title / note", not [c for c in a["clipped"] if "CUT" in c or "height" in c], a["clipped"])
    check(f"{tag}: nothing overlaps, everything on screen", not a["overlaps"] and not a["outside"],
          (a["overlaps"], a["outside"]))


async def main():
    token = await mint()
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});sessionStorage.removeItem('focusSessionId');}}catch(e){{}}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));")
    print(f"voice stage audit on {BASE} (fake voice, real pipeline), shots in {SHOTS}", flush=True)
    async with Browser(port=9397, mic_wav=silent_wav(), init_js=init, size=(1536, 864)) as b:
        await set_size(b, 1536, 864)
        await b.goto(BASE + "/megh-chat?voicetest=1", wait=4)
        await b.eval(AUDIT_JS)
        await b.eval("(async () => !!(await until(() => document.querySelector('[data-testid=agent-orb]'), 20000)))()")
        await b.eval("sleep(2000)")
        await b.eval("document.querySelector('[data-testid=agent-orb]').click()")
        ok = await b.eval("""(async () => { const ok = !!(await until(() => window.__meghVoice && window.__meghVoice.phase() === 'live', 25000));
            await until(() => vlog().some(e => e.type === 'turn_complete' && e.said), 25000);
            await until(() => !window.__meghVoice.playing(), 20000); await sleep(800); return ok; })()""", timeout=80)
        check("the stage opens live", ok)
        for size in SIZES:
            await set_size(b, *size)
            a = await b.eval("audit()")
            judge("desk", size, a)
            await b.shot(str(SHOTS / f"00_desk_{size[0]}.png"))
        await set_size(b, 1536, 864)
        for i, (name, said, settle) in enumerate(SCRIPT, 1):
            if ONLY and name not in ONLY:
                continue
            r = await ask(b, said, settle)
            print(f"   {i:02d} {name}: {r['kind']} · {r['speak']!r} · long frames {len(r['long'])} worst {r['worst']} ms", flush=True)
            special(name, await b.eval(PLAN_JS))
            for size in [(1536, 864), (1366, 768), (1920, 1080)]:
                if size != (1536, 864):
                    await set_size(b, *size)
                a = await b.eval("audit()")
                judge(f"{i:02d} {name}", size, a)
                await b.shot(str(SHOTS / f"{i:02d}_{name}_{size[0]}.png"))
                if size == (1536, 864):
                    print(f"      cards {a['cards']} · titles {[t[:40] for t in a['titles']]} · chip {a['chip']!r}", flush=True)
            await set_size(b, 1536, 864)
        # barge-in mid-reveal: a new question while the previous answer is still being read
        if not ONLY or "barge" in ONLY:
            t0 = await b.eval("performance.now()")
            await b.eval("window.__meghVoice.say('PMAY-G houses sanctioned by district')")
            await b.eval(f"(async () => {{ await until(() => window.__meghVoice.playing(), 120000); await sleep(700); }})()", timeout=150)
            r = await ask(b, "MGNREGA person-days by district", 2500)
            a = await b.eval("audit()")
            judge("barge-in", (1536, 864), a)
            check("barge-in: the new answer's picture is on stage", any("person" in t.lower() for t in a["titles"]) or "person" in a["title"].lower(),
                  (a["title"], a["titles"]))
            await b.shot(str(SHOTS / "99_barge_1536.png"))
        errs = await b.eval("window.__errs")
        check("no page errors", not errs and not [e for e in b.events if e[0] == "exception"], (errs, b.events[:5]))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed · screenshots in {SHOTS}", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

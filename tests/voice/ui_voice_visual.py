"""Visual regression of the Secretary voice view (D-105): every picture right the first time.

The voice is the fake Gemini Live (start `python tests/voice/fake_live.py 8499` and the app with
VOICE_LIVE_URL=ws://127.0.0.1:8499), so the pictures are tested without spending live audio and without the shared
quota making the run flaky; every answer is the real pipeline's (VPN up).

Checks:
- opening the view: each desk column enters exactly once, the tiles and the map mount once (no building in stages);
  the orb's canvas corners are empty in every state (no square around the orb);
- for each question of the bank (cross-scheme first, then single-scheme, views, clarifications): one call reaches the
  page and one answer is asked; each card of the answer enters exactly once (no repeated pop-ups); every card's canvas
  is drawn; all items are revealed by the end; the cards stay inside the screen and never overlap; a text answer shows
  the chat's own card; no page errors. A screenshot per question.

Run from the repo root:  python tests/voice/ui_voice_visual.py [--base URL] [--only N,M]
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
ONLY = {int(x) for x in ARGS[ARGS.index("--only") + 1].split(",")} if "--only" in ARGS else None
SHOTS = Path(os.environ.get("TEMP", ".")) / "megh_visual_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

BANK = [
    # cross-scheme, the way a Secretary asks (d:/MEGH-LANG/test_questions.md §1)
    "Give me the headline figure of every scheme",
    "What is the beneficiary count across MGNREGA, PMAY-G, Focus Plus and Focus Legacy?",
    "Compare the total expenditure or disbursement under MGNREGA, PMAY-G, Focus Plus and CM Elevate Legacy.",
    "Which scheme provided the highest total financial assistance across Meghalaya?",
    "Which scheme has the widest coverage across the districts of Meghalaya?",
    "Give me a district-wise summary comparing MGNREGA, PMAY-G, Focus Plus, Focus Legacy and CM Elevate Legacy.",
    "Which scheme leads in each district?",
    "Which districts have the highest concentration of beneficiaries or applications across the schemes?",
    "Compare Focus Plus and CM Elevate Legacy in East Garo Hills, West Garo Hills and South West Garo Hills.",
    "Compare the number of beneficiaries and the total amount for Focus Plus, Focus Legacy and CM Elevate Legacy.",
    "In Dalu block, which schemes have any beneficiaries, and how many each?",
    "For Williamnagar constituency, give me every scheme's figure.",
    "Which district gets the most money across all the schemes that have money?",
    "Compare East Khasi Hills and West Garo Hills across every scheme.",
    "Each year, for all schemes, what was disbursed?",
    "How much money has each scheme disbursed?",
    "In Ri Bhoi, give me each scheme's figures",
    # one scheme, deep (§2)
    "MGNREGA person-days by district",
    "MGNREGA person-days in West Garo Hills in 2023-24.",
    "How have MGNREGA person-days changed over the last three years in West Garo Hills?",
    "MGNREGA person-days by financial year",
    "MGNREGA expenditure in crore for the whole state, year by year.",
    "How many PMAY-G houses were sanctioned in total, and how many are completed?",
    "PMAY-G houses sanctioned by district",
    "Compare PMAY-G houses sanctioned in West Garo Hills and East Khasi Hills",
    "Month by month, how many PMAY-G houses were sanctioned in 2021?",
    "Top 10 blocks by PMAY-G houses completed",
    "Focus Plus beneficiaries and amount disbursed by district",
    "Focus Legacy payments by district for FY 2024-25.",
    "How many CM Elevate applications are there, by scheme?",
    "Compare MGNREGA expenditure in 2022-23 and 2023-24 by district",
    # views (§4)
    "MGNREGA person-days by district in 2023-24, as a bar chart.",
    "PMAY-G houses sanctioned by district as a donut chart",
    "Show Focus Plus beneficiaries by district on the map",
    # clarifications and refusals (§6): the chat's own card, no picture
    "Beneficiaries under Focus.",
    "MGNREGA in 2020.",
]

VIS_JS = JS + """
window.stage = () => document.querySelector('.vstage');
window.gridCards = () => [...document.querySelectorAll('.vs-grid > .vc')];
window.canvasInk = (cv) => { if (!cv || !cv.width) return 0; const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
  let n = 0; for (let i = 3; i < d.length; i += 4 * 53) if (d[i] > 8) n++; return n; };
window.cornerInk = (cv) => { if (!cv || !cv.width) return -1; const ctx = cv.getContext('2d'); const w = cv.width, h = cv.height, s = Math.max(4, Math.round(w * 0.08));
  let m = 0; for (const [x, y] of [[0, 0], [w - s, 0], [0, h - s], [w - s, h - s]]) { const d = ctx.getImageData(x, y, s, s).data;
    for (let i = 3; i < d.length; i += 4) m = Math.max(m, d[i]); } return m; };
// every card element that enters the grid, counted (a re-mount or a second picture counts again)
window.__entered = 0;
window.watchGrid = () => { const g = document.querySelector('.vs-grid'); if (!g || g.__w) return; g.__w = true;
  new MutationObserver((ms) => ms.forEach(m => m.addedNodes.forEach(n => { if (n.classList && n.classList.contains('vc')) window.__entered++; })))
    .observe(g, { childList: true }); };
"""


async def main():
    token = await mint()
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});sessionStorage.removeItem('focusSessionId');}}catch(e){{}}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));"
            # count every animation that starts on the desk while the view opens
            "window.__anims=[];document.addEventListener('animationstart',e=>{const t=e.target;"
            "if(t.closest&&t.closest('.vs-col'))window.__anims.push((t.className&&t.className.baseVal===undefined?String(t.className):'svg')+'|'+e.animationName);},true);")
    print(f"voice visual regression on {BASE} (fake voice, real pipeline): {len(BANK)} questions", flush=True)
    async with Browser(port=9391, mic_wav=silent_wav(), init_js=init, size=(1600, 940)) as b:
        await b.goto(BASE + "/megh-chat?voicetest=1", wait=4)
        await b.eval(VIS_JS)
        await b.eval("(async () => !!(await until(() => document.querySelector('.mic-btn'), 20000)))()")
        await b.eval("sleep(2500)")          # the board is fetched ahead while the chat loads
        # ── opening: one entrance, nothing in stages ──
        await b.eval("""window.__mounts = { tiles: 0, maps: 0 };
            new MutationObserver((ms) => ms.forEach(m => m.addedNodes.forEach(n => { if (!n.querySelectorAll) return;
              window.__mounts.tiles += (n.classList.contains('sd-tile') ? 1 : 0) + n.querySelectorAll('.sd-tile').length;
              window.__mounts.maps += n.querySelectorAll('.vs-col .vc canvas').length + (n.matches('.vs-col .vc') ? 1 : 0); })))
              .observe(document.body, { childList: true, subtree: true });
            document.querySelector('.mic-btn').click();""")
        op = await b.eval("""(async () => { await until(() => window.__meghVoice && window.__meghVoice.phase() === 'live', 20000);
            await sleep(4500);
            const cols = window.__anims.filter(a => a.includes('vsColIn')).length;
            const other = window.__anims.filter(a => !a.includes('vsColIn'));
            return { cols, other, mounts: window.__mounts, ready: stage().classList.contains('board-ready'),
                     tiles: document.querySelectorAll('.sd-tile').length, sk: document.querySelectorAll('.sk').length }; })()""", timeout=40)
        check("opening: each desk column enters exactly once, nothing else on the desk animates in",
              op["cols"] == 2 and not op["other"] and op["ready"], op)
        check("opening: the eight tiles and the map mount once (no placeholders, no second build)",
              op["mounts"]["tiles"] == 8 and op["tiles"] == 8 and op["sk"] == 0, op)
        corners = await b.eval("""(async () => { const cv = document.querySelector('.vs-orb-cv'); const out = [];
            for (let i = 0; i < 12; i++) { out.push(cornerInk(cv)); await sleep(250); } return out; })()""")
        check("the orb has no square: its canvas corners stay empty while it speaks and listens", max(corners) <= 2, corners)
        await b.shot(str(SHOTS / "00_desk.png"))
        await b.eval("(async () => { await until(() => !window.__meghVoice.playing(), 15000); })()", timeout=20)

        for i, q in enumerate(BANK, 1):
            if ONLY and i not in ONLY:
                continue
            t0 = await b.eval("performance.now()")
            await b.eval(f"watchGrid(); window.__entered = 0; window.__meghVoice.say({json.dumps(q)})")
            r = await b.eval(f"""(async () => {{
                const rep = await until(() => vlog().filter(e => e.type === 'reply' && e.t > {t0}).pop(), 170000);
                await until(() => vlog().some(e => e.type === 'turn_complete' && rep && e.t > rep.t) && !window.__meghVoice.playing(), 90000);
                await sleep(4800);
                watchGrid();
                const ev = vlog().filter(e => e.t > {t0});
                const cards = gridCards(); const vw = innerWidth, vh = innerHeight;
                const rects = cards.map(c => c.getBoundingClientRect());
                let overlap = 0;
                for (let a = 0; a < rects.length; a++) for (let c = a + 1; c < rects.length; c++) {{
                  const x = Math.min(rects[a].right, rects[c].right) - Math.max(rects[a].left, rects[c].left);
                  const y = Math.min(rects[a].bottom, rects[c].bottom) - Math.max(rects[a].top, rects[c].top);
                  if (x > 2 && y > 2) overlap++; }}
                const st = window.__stageCards ? window.__stageCards() : [];
                return {{ calls: ev.filter(e => e.type === 'tool_call').length, asks: ev.filter(e => e.type === 'ask').length,
                         kind: rep ? rep.kind : null, kinds: cards.map(c => c.dataset.kind), entered: window.__entered,
                         ink: cards.map(c => canvasInk(c.querySelector('canvas'))),
                         all: st.length > 0 && st.every(c => (c.items || []).every(x => x.on)),
                         inside: rects.every(r => r.left >= -1 && r.right <= vw + 1), overlap,
                         text: !!document.querySelector('.vs-grid > .vs-card'),
                         answer: (document.querySelector('.vs-answer') || document.querySelector('.vs-grid > .vs-card') || {{}}).innerText || '' }}; }})()""",
                             timeout=300)
            pic = len(r["kinds"]) > 0
            ok_once = r["asks"] == 1 and r["calls"] == 1
            ok_cards = (pic and r["entered"] == len(r["kinds"]) and all(x > 30 for x in r["ink"]) and r["all"]
                        and r["inside"] and r["overlap"] == 0) or (not pic and r["text"])
            check(f"{i:2}. {q[:78]}", ok_once and ok_cards,
                  {k: r[k] for k in ("calls", "asks", "kinds", "entered", "ink", "all", "inside", "overlap", "text")})
            print(f"      {'picture: ' + ', '.join(r['kinds']) if pic else 'the chat card (no picture)'} · {r['answer'][:110]!r}", flush=True)
            await b.shot(str(SHOTS / f"{i:02d}.png"))
        errs = await b.eval("window.__errs")
        check("no page errors", not errs and not [e for e in b.events if e[0] == "exception"], (errs, b.events[:5]))
        await b.eval("document.querySelector('.vs-end') && document.querySelector('.vs-end').click()")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed · screenshots in {SHOTS}", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

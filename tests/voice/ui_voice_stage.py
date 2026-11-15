"""The live voice STAGE in the real chat page (2026-11-02): the Mitra-style voice view, mute, and the answer drawn big.

Same set-up as ui_voice.py: headless Edge on /megh-chat?voicetest=1, signed in, the real pipeline (VPN), the voice either
the fake Gemini Live (start the app with VOICE_LIVE_URL=ws://127.0.0.1:8499) or the real one (--real).

Checks (D-104, D-105): the mic opens the Secretary view over the chat (the chat sinks); the greeting by the hour
("Good morning, Secretary sir") on screen and spoken; the desk (eight command tiles, the years each scheme holds, the
district map with scheme chips); the orb draws and moves; mute switches only the microphone track off (the session
stays, an answer asked while muted still plays, unmute brings the track back); a data answer sinks the desk, parks the
orb and arcs in its picture (the map and the ranking, the answer's text above) with the districts revealed as the voice
names them and all of them by the end; a cross-scheme answer is a tile per scheme figure, never added; a new answer
crossfades over the old; the leader of each district on the map; a question typed on the stage; earlier answers in the
dock; 'The desk' and a desk tile; a tap on the orb silences the voice; Esc goes to the desk, then to the chat with every
voice turn in it; the phone layout fits; no page errors.

Run from the repo root:  python tests/voice/ui_voice_stage.py [--real] [--base URL]
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
REAL = "--real" in ARGS
SHOTS = Path(os.environ.get("TEMP", ".")) / ("megh_stage_shots_real" if REAL else "megh_stage_shots")
SHOTS.mkdir(parents=True, exist_ok=True)

STAGE_JS = JS + """
window.stage = () => document.querySelector('.vstage');
window.card = () => document.querySelector('.vs-grid > .vc, .vs-grid > .vs-card:not(.ghost)');
window.orbBusy = () => { const c = document.querySelector('.vs-orb-cv'); if (!c || !c.width) return 0;
  const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
  for (let i = 3; i < d.length; i += 4 * 37) if (d[i] > 8) n++; return n; };
window.waitAnswer = async (t0, ms) => {
  const r = await until(() => vlog().filter(e => e.type === 'reply' && e.t > t0).pop(), ms);
  await until(() => vlog().filter(e => e.type === 'turn_complete' && e.t > (r ? r.t : t0)).length, 30000);
  await until(() => !window.__meghVoice.playing(), 30000);
  return r; };
"""


async def ask(b, text, wait=150):
    t0 = await b.eval("performance.now()")
    await b.eval(f"window.__meghVoice.say({json.dumps(text)})")
    return t0, await b.eval(f"waitAnswer({t0}, {wait * 1000})", timeout=wait + 70)


async def main():
    token = await mint()
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});sessionStorage.removeItem('focusSessionId');}}catch(e){{}}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));")
    print(f"voice stage test on {BASE} ({'REAL Gemini Live' if REAL else 'fake Live'})", flush=True)
    async with Browser(port=9373, mic_wav=silent_wav(), init_js=init, size=(1600, 940)) as b:
        await b.goto(BASE + "/megh-chat?voicetest=1", wait=4)
        await b.eval(STAGE_JS)
        await b.eval("(async () => !!(await until(() => document.querySelector('[data-testid=agent-orb]'), 20000)))()")
        await b.eval("document.querySelector('[data-testid=agent-orb]').click()")
        ok = await b.eval("(async () => !!(await until(() => window.__meghVoice && window.__meghVoice.phase() === 'live', 20000)))()")
        check("the mic opens the live voice", ok)
        st = await b.eval("""(async () => { await sleep(1200); const s = stage(); const app = document.querySelector('.app');
            return { stage: !!s, inn: document.body.classList.contains('vstage-in'), sunk: getComputedStyle(app).transform !== 'none',
                     op: +getComputedStyle(s).opacity, hello: !!document.querySelector('.vs-hello'),
                     starters: document.querySelectorAll('.vs-starters button').length,
                     pill: (document.querySelector('.vs-pill') || {}).innerText || '' }; })()""")
        check("the stage takes the screen and the chat sinks behind it", st["stage"] and st["inn"] and st["sunk"] and st["op"] > 0.9, st)
        check("before any question: the Secretary greeting and the cross-scheme starters", st["hello"] and st["starters"] >= 4, st)
        hello = await b.eval("""(async () => { await until(() => vlog().some(e => e.type === 'turn_complete' && e.said), 20000);
            await until(() => !window.__meghVoice.playing(), 15000); await sleep(400); const h = document.querySelector('.vs-hello h2');
            return { h: h ? h.innerText : '', said: vlog().filter(e => e.type === 'turn_complete').map(e => e.said || '').join(' | ') }; })()""")
        check("the heading greets by the hour: Good morning / afternoon / evening, Secretary sir",
              hello["h"].startswith("Good ") and hello["h"].endswith("Secretary sir") and "Chief" not in hello["h"] and "Madam" not in hello["h"], hello)
        check("the voice says the greeting when the stage opens", "Secretary sir" in hello["said"], hello)
        pill = await b.eval("document.querySelector('.vs-pill').innerText")
        check("after the greeting the pill says Listening", "Listening" in pill, pill)
        desk = await b.eval("""(async () => { await until(() => document.querySelectorAll('.sd-tile:not(.sk)').length >= 8, 20000);
            const tiles = [...document.querySelectorAll('.sd-tile:not(.sk)')].map(t => t.innerText.split('\\n').join(' | '));
            const yrs = document.querySelectorAll('.sd-yr-grid i.on').length;
            const map = document.querySelector('.vs-col-r .vc canvas');
            await sleep(1800);
            const cards = window.__stageCards ? window.__stageCards() : [];
            return { tiles, yrs, map: !!map, mapDrawn: map ? map.width > 100 : false, chips: document.querySelectorAll('.sd-chips button').length }; })()""")
        check("the desk: eight command tiles, each scheme in its own unit",
              len(desk["tiles"]) == 8 and any("Person-days" in t for t in desk["tiles"]) and any("Houses sanctioned" in t for t in desk["tiles"]), desk["tiles"])
        check("the desk: the years each scheme holds and the district map with scheme chips",
              desk["yrs"] >= 10 and desk["map"] and desk["mapDrawn"] and desk["chips"] >= 5, desk)
        o1 = await b.eval("orbBusy()")
        await b.eval("sleep(400)")
        o2 = await b.eval("orbBusy()")
        frames = await b.eval("""(async () => { const c = document.querySelector('.vs-orb-cv'); const a = c.toDataURL();
            await sleep(300); return a !== c.toDataURL(); })()""")
        check("the orb draws (its particles are on the canvas) and moves", o1 > 50 and o2 > 50 and frames, (o1, o2, frames))
        await b.shot(str(SHOTS / "01_desk.png"))

        # mute: only the microphone; the session and the answer go on
        await b.eval("document.querySelector('.vs-mute').click()")
        m = await b.eval("""(async () => { await sleep(300); return { muted: window.__meghVoice.muted(), track: window.__meghVoice.trackEnabled(),
            phase: window.__meghVoice.phase(), pill: document.querySelector('.vs-pill').innerText,
            btn: document.querySelector('.vs-mute').classList.contains('on') }; })()""")
        check("mute switches the microphone track off and nothing else", m["muted"] and not m["track"] and m["phase"] == "live" and m["btn"], m)
        check("the pill says the answer still plays", "Muted" in m["pill"] and "still plays" in m["pill"], m["pill"])
        q1 = "MGNREGA person-days by district in 2023-24"
        t0, r = await ask(b, q1)
        played = await b.eval(f"vlog().some(e => e.type === 'reply' && e.t > {t0}) && !!card()")
        still = await b.eval("({ phase: window.__meghVoice.phase(), muted: window.__meghVoice.muted() })")
        check("muted: a question still gets its answer on the stage and read aloud, the session stays open",
              played and r and r.get("speak") and still["phase"] == "live" and still["muted"], (r, still))
        await b.eval("(async () => { await until(() => !window.__meghVoice.playing(), 30000); })()", timeout=40)
        kept = await b.eval("(async () => { await sleep(32000); return { phase: window.__meghVoice.phase(), stage: !!stage(), muted: window.__meghVoice.muted() }; })()", timeout=45)
        check("muted and quiet past the idle window: the session and the stage stay (mute never stops it)",
              kept["phase"] == "live" and kept["stage"] and kept["muted"], kept)
        await b.eval("document.querySelector('.vs-mute').click()")
        um = await b.eval("(async () => { await sleep(300); return { muted: window.__meghVoice.muted(), track: window.__meghVoice.trackEnabled() }; })()")
        check("unmute switches the track back on", not um["muted"] and um["track"], um)

        # the picture of an answer: the desk sinks, the orb parks, the cards arc in; speech-synced reveal
        t0 = await b.eval("performance.now()")
        await b.eval("""window.__revealLog = []; window.__partial = 0; window.__hiddenAtStart = -1;
            window.__oldCards = new Set((window.__stageCards ? window.__stageCards() : []).map(c => c.id));
            window.__watch = setInterval(() => { const cs = (window.__stageCards ? window.__stageCards() : []).filter(c => !window.__oldCards.has(c.id));
              const its = cs.flatMap(c => c.items || []); if (!its.length) return;
              const on = its.filter(i => i.on).length;
              if (window.__hiddenAtStart < 0) window.__hiddenAtStart = its.length - on;
              if (on > 0 && on < its.length) window.__partial++; }, 120);
            window.__meghVoice.say('PMAY-G houses sanctioned by district')""")
        rev = await b.eval(f"""(async () => {{
            const r = await until(() => vlog().filter(e => e.type === 'reply' && e.t > {t0}).pop(), 150000);
            await until(() => vlog().some(e => e.type === 'turn_complete' && r && e.t > r.t) && !window.__meghVoice.playing(), 60000);
            await sleep(4800); clearInterval(window.__watch);   // the last items' growth (stagger + GROW) ends ~3.5 s in
            const s = stage(); const orb = document.querySelector('.vs-orb'); const cs = window.__stageCards();
            const grid = [...document.querySelectorAll('.vs-grid > .vc')];
            const first = grid[0] ? grid[0].getBoundingClientRect() : null;
            return {{ speak: r && r.speak, parked: s.classList.contains('parked'), orbT: orb.style.transform || '',
                     kinds: grid.map(g => g.dataset.kind), answer: (document.querySelector('.vs-answer') || {{}}).innerText || '',
                     colL: getComputedStyle(document.querySelector('.vs-col-l')).opacity,
                     all: cs.length > 0 && cs.every(c => (c.items || []).every(i => i.on && i.p > 0.98)),
                     hidden0: window.__hiddenAtStart, partial: window.__partial, log: (window.__revealLog || []).map(x => x.what),
                     inView: first ? first.top >= 0 && first.bottom <= innerHeight + 2 : false }}; }})()""", timeout=260)
        check("the desk sinks away and the orb glides to its corner", rev["parked"] and "scale" in rev["orbT"] and float(rev["colL"]) < 0.2, rev)
        check("the answer's picture: the Meghalaya map and the ranking, with the answer's text above",
              "map" in rev["kinds"] and any(k in ("race", "bars") for k in rev["kinds"]) and ("PMAY" in rev["answer"] or "houses" in rev["answer"].lower()), rev)
        check("districts come in as the voice names them, then all of them (speech-synced reveal)",
              rev["hidden0"] > 0 and rev["partial"] > 0 and "named" in rev["log"] and rev["all"],
              {k: rev[k] for k in ("hidden0", "partial", "log", "all")})
        check("the first card fits in the stage", rev["inView"], rev)
        await b.shot(str(SHOTS / "02_answer_cards.png"))

        # a cross-scheme answer and the crossfade
        await b.eval("window.__ghostSeen = false; new MutationObserver(() => { if (document.querySelector('.vc-ghost, .vs-card.ghost')) window.__ghostSeen = true; }).observe(stage(), { childList: true, subtree: true });")
        # all six named: after two PMAY-G / MGNREGA turns the brain otherwise asks "PMAY-G or MGNREGA?" (its follow-up
        # context, unchanged by the voice)
        t0, r = await ask(b, "Give me the headline figure of every scheme: MGNREGA, PMAY-G, Focus Plus, Focus Legacy, CM Elevate and CM Elevate Legacy")
        cross = await b.eval("""(async () => { await sleep(2500); const g = [...document.querySelectorAll('.vs-grid > .vc')];
            const tiles = g.find(x => x.dataset.kind === 'tiles'); const cs = window.__stageCards();
            const tc = cs.find(c => c.kind === 'tiles');
            return { kinds: g.map(x => x.dataset.kind), note: tiles ? tiles.innerText : '', n: tc ? tc.items.length : 0,
                     ghost: window.__ghostSeen }; })()""")
        check("a cross-scheme answer: a tile per scheme figure, never added together",
              "tiles" in cross["kinds"] and cross["n"] >= 4 and "never added" in cross["note"], cross)
        check("the new answer crossfaded over the old (ghost)", cross["ghost"], cross)
        await b.shot(str(SHOTS / "03_cross_scheme.png"))
        t0, r = await ask(b, "Which scheme leads in each district?")
        lead = await b.eval("""(async () => { await sleep(2500); const cs = window.__stageCards(); const g = [...document.querySelectorAll('.vs-grid > .vc')];
            return { kinds: g.map(x => x.dataset.kind), titles: g.map(x => x.querySelector('h3').innerText), map: cs.some(c => c.kind === 'map') }; })()""")
        check("the leader of each district is drawn on the map", lead["map"] and any("lead" in t.lower() for t in lead["titles"]), lead)
        await b.shot(str(SHOTS / "04_leaders.png"))

        # typed on the stage
        t0 = await b.eval("performance.now()")
        await b.eval("""(() => { const i = document.querySelector('.vs-compose input');
            const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            set.call(i, 'How many CM Elevate applications are there?'); i.dispatchEvent(new Event('input', { bubbles: true }));
            setTimeout(() => document.querySelector('.vs-compose button').click(), 80); })()""")
        typed = await b.eval(f"""(async () => {{ const r = await until(() => vlog().find(e => e.type === 'reply' && e.id === null && e.t > {t0}), 150000);
            await until(() => !window.__meghVoice.playing() && vlog().some(e => e.type === 'turn_complete' && e.t > (r ? r.t : 0)), 40000);
            return {{ r, text: document.querySelector('.vs-stagearea').innerText.slice(0, 400) }}; }})()""", timeout=220)
        check("a question typed on the stage is answered there and read aloud", typed["r"] and "CM Elevate" in typed["text"], typed)

        # earlier answers (2026-11-15: the dock chips went on 12 Nov, replaced by the scheme strip; earlier answers are
        # listed on the desk's right column): Dashboard brings the desk back, an earlier answer there comes back on stage
        await b.eval("document.querySelector('.vs-chip.home').click()")
        home = await b.eval("(async () => { const op = () => +getComputedStyle(document.querySelector('.vs-col-l')).opacity; await until(() => op() > 0.95, 3000); const s = stage(); return { desk: s.classList.contains('desk'), op: op() }; })()")
        check("'Dashboard' brings the desk back", home["desk"] and home["op"] > 0.9, home)
        chips = await b.eval("document.querySelectorAll('.vs-col-r .sdk-ex').length")
        check("earlier answers wait on the desk", chips >= 3, chips)
        await b.eval("document.querySelector('.vs-col-r .sdk-ex').click()")
        back = await b.eval("(async () => { await sleep(1200); return { parked: stage().classList.contains('parked'), cards: document.querySelectorAll('.vs-grid > .vc, .vs-grid > .vs-card').length }; })()")
        check("an earlier answer on the desk comes back on stage", back["parked"] and back["cards"] > 0, back)
        await b.eval("document.querySelector('.vs-chip.home').click()")
        await b.eval("(async () => { await until(() => stage().classList.contains('desk'), 3000); await sleep(600); })()")
        t0 = await b.eval("performance.now()")
        await b.eval("document.querySelector('.sd-tile:not(.sk)').click()")
        tile = await b.eval(f"""(async () => {{ const r = await until(() => vlog().find(e => e.type === 'reply' && e.t > {t0}), 150000);
            await sleep(1500); return {{ r: !!r, parked: stage().classList.contains('parked'), kinds: [...document.querySelectorAll('.vs-grid > .vc')].map(x => x.dataset.kind) }}; }})()""", timeout=170)
        check("a desk tile asks its question and the answer takes the stage", tile["r"] and tile["parked"] and len(tile["kinds"]) > 0, tile)
        await b.eval("(async () => { await until(() => !window.__meghVoice.playing(), 40000); })()", timeout=50)

        if not REAL:
            # a tap on the orb while it speaks silences it (the session stays)
            await b.eval("window.__meghVoice.say('tell me about MGNREGA eligibility')")
            playing = await b.eval("(async () => !!(await until(() => window.__meghVoice.playing(), 150000)))()", timeout=170)
            await b.eval("""(() => { const c = document.querySelector('.vs-orb-cv'); const r = c.getBoundingClientRect();
                const o = { bubbles: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, pointerId: 1 };
                c.dispatchEvent(new PointerEvent('pointerdown', o)); c.dispatchEvent(new PointerEvent('pointerup', o)); })()""")
            hushed = await b.eval("(async () => { const s = await until(() => !window.__meghVoice.playing(), 1500); return { stopped: !!s, phase: window.__meghVoice.phase() }; })()")
            check("a tap on the orb silences the voice, the session stays", playing and hushed["stopped"] and hushed["phase"] == "live", hushed)
            await b.eval("sleep(2500)")

        # Esc: back to the chat, every voice turn in it
        esc = "window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))"
        await b.eval(esc)
        d1 = await b.eval("(async () => { await sleep(900); return { stage: !!stage(), desk: !!stage() && stage().classList.contains('desk') }; })()")
        check("Esc on an answer goes back to the desk first", d1["stage"] and d1["desk"], d1)
        await b.eval(esc)
        gone = await b.eval("""(async () => { await until(() => !stage(), 3000); await sleep(900);
            return { stage: !!stage(), phase: window.__meghVoice ? window.__meghVoice.phase() : 'off',
                     users: [...document.querySelectorAll('.msg.user .bubble')].map(x => x.innerText),
                     appT: getComputedStyle(document.querySelector('.app')).transform }; })()""")
        check("Esc closes the stage and the live voice, the chat comes back", not gone["stage"] and gone["phase"] == "off" and gone["appT"] == "none", gone)
        check("every voice turn is in the chat", any("PMAY-G houses sanctioned by district" in u for u in gone["users"])
              and any("headline figure of every scheme" in u for u in gone["users"]), gone["users"])
        await b.shot(str(SHOTS / "05_back_to_chat.png"))

        # phone
        await b.cmd("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
        await b.eval("sleep(500)")
        await b.eval("document.querySelector('[data-testid=agent-orb]').click()")
        await b.eval("(async () => await until(() => window.__meghVoice.phase() === 'live', 20000))()")
        t0, r = await ask(b, "How many PMAY-G houses were completed?")
        ph = await b.eval("""(async () => { await sleep(1200); const c = card(); const o = document.querySelector('.vs-orb').getBoundingClientRect();
            const cr = c ? c.getBoundingClientRect() : null;
            return { w: innerWidth, sw: document.documentElement.scrollWidth, orbW: Math.round(o.width), orbR: Math.round(o.right),
                     card: cr ? [Math.round(cr.left), Math.round(cr.right), Math.round(cr.top)] : null,
                     compose: !!document.querySelector('.vs-compose'), mute: !!document.querySelector('.vs-mute') }; })()""")
        check("phone: the orb is a badge in the title row, the card fits the width, no sideways scroll",
              ph["orbW"] <= 60 and ph["orbR"] <= ph["w"] and ph["card"] and ph["card"][0] >= 0 and ph["card"][1] <= ph["w"] and ph["sw"] <= ph["w"] + 1, ph)
        check("phone: the composer, mute and end are at the thumb", ph["compose"] and ph["mute"], ph)
        await b.shot(str(SHOTS / "06_phone.png"))
        await b.eval("document.querySelector('.vs-end').click()")

        errs = await b.eval("window.__errs")
        check("no page errors", not errs and not [e for e in b.events if e[0] == "exception"], (errs, b.events[:5]))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed · screenshots in {SHOTS}", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

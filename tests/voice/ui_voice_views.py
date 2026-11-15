"""Chart switches by voice, the explaining breakdown and the question queue on the voice stage (2026-11-11).

Same set-up as ui_voice_stage.py: headless Edge on /megh-chat?voicetest=1, signed in (MEGH_VOICE_USER, default
superadmin), the real pipeline (VPN), the voice the fake Live or, with --real, the real engine (one live session per
officer: run nothing else as that officer meanwhile).

Checks:
  each of the shaper's seven sentences ("show it as a bar chart" ... "show it as horizontal bars") switches the picture
  of the answer on screen, or says why it cannot, in one short natural line (never the chat's "(Drawn here ...)" note);
  map / ranking / horizontal with no pipeline question at all; the picture's figures stay cells of the answer;
  a switch with no picture on screen says so; a single-figure answer gets the breakdown that explains it beside the
  tile, its parts adding up to the figure, every part a cell of that second answer, nothing added to the chat thread
  and no conversation left in the history; a question that arrives while an answer is still being written is queued
  and answered once that answer is done (the newest one only); the phone layout of a switch and of a breakdown.

Run from the repo root:  python tests/voice/ui_voice_views.py [--real] [--base URL] [--shots DIR] [--only a,b]
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
SHOTS = Path(ARGS[ARGS.index("--shots") + 1]) if "--shots" in ARGS else Path(os.environ.get("TEMP", ".")) / "megh_views_shots"
SHOTS.mkdir(parents=True, exist_ok=True)
ONLY = set(ARGS[ARGS.index("--only") + 1].split(",")) if "--only" in ARGS else None

PAGE_JS = JS + """
window.stage = () => document.querySelector('.vstage');
window.gridCards = () => [...document.querySelectorAll('.vs-host .vs-grid > .vc')];
window.kinds = () => gridCards().map(c => c.dataset.kind);
window.canvasInk = (cv) => { if (!cv || !cv.width) return 0; const d = cv.getContext('2d').getImageData(0, 0, cv.width, cv.height).data;
  let n = 0; for (let i = 3; i < d.length; i += 4 * 53) if (d[i] > 8) n++; return n; };
window.waitReply = async (t0, ms) => {
  const r = await until(() => vlog().filter(e => e.type === 'reply' && e.t > t0 && e.kind !== 'superseded').pop(), ms);
  await until(() => vlog().some(e => e.type === 'turn_complete' && e.t > (r ? r.t : t0)), 30000);
  await until(() => !window.__meghVoice.playing(), 30000);
  return r; };
window.userBubbles = () => [...document.querySelectorAll('.msg.user .bubble')].map(x => x.innerText);
"""


async def say_and_wait(b, text, wait=170):
    t0 = await b.eval("performance.now()")
    await b.eval(f"window.__meghVoice.say({json.dumps(text)})")
    r = await b.eval(f"waitReply({t0}, {wait * 1000})", timeout=wait + 70)
    await b.eval("sleep(1600)")                      # the switch's turn-in (0.7 s) and the reveal settle
    return t0, r


async def picture(b, t0):
    return await b.eval(f"""(() => {{ const ev = vlog().filter(e => e.t > {t0});
        const p = window.__stagePlan || {{}};
        return {{ kinds: kinds(), ink: gridCards().map(c => canvasInk(c.querySelector('canvas'))),
                 asks: ev.filter(e => e.type === 'ask').map(e => ({{ q: e.question, view: e.view || null, local: !!e.local }})),
                 views: ev.filter(e => e.type === 'view'),
                 chip: (document.querySelector('.vs-viewchip') || {{}}).innerText || '',
                 view: p.view || null, applied: p.applied || null, cards: p.cards || [], data: p.data || [],
                 errs: (window.__errs || []).slice() }}; }})()""")


def cells_ok(pic):
    """Every drawn figure is a cell of the answer (the same rule as voice_bank's D1)."""
    rows = [r for r in pic["data"] if isinstance(r, dict)]

    def num(v):
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            return None
    bad = []
    for c in pic["cards"]:
        if c["kind"] == "line":
            continue
        for it in c.get("items") or []:
            v = it.get("value")
            if v is None:
                continue
            if not any(num(r.get(it.get("col"))) is not None and abs(num(r.get(it.get("col"))) - float(v)) < 1e-6 for r in rows):
                bad.append((c["title"], it.get("label"), v, it.get("col")))
    return bad


def want(step):
    return ONLY is None or step in ONLY


async def main():
    token = await mint()
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});sessionStorage.removeItem('focusSessionId');}}catch(e){{}}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));")
    print(f"voice views test on {BASE} ({'the real voice' if REAL else 'fake Live'}), shots in {SHOTS}", flush=True)
    async with Browser(port=9381, mic_wav=silent_wav(), init_js=init, size=(1600, 940)) as b:
        await b.goto(BASE + "/megh-chat?voicetest=1", wait=4)
        await b.eval(PAGE_JS)
        await b.eval("(async () => !!(await until(() => document.querySelector('[data-testid=agent-orb]'), 20000)))()")
        await b.eval("document.querySelector('[data-testid=agent-orb]').click()")
        ok = await b.eval("""(async () => { const ok = !!(await until(() => window.__meghVoice && window.__meghVoice.phase() === 'live', 25000));
            await until(() => vlog().some(e => e.type === 'turn_complete' && e.said), 25000);
            await until(() => !window.__meghVoice.playing(), 20000); await sleep(500); return ok; })()""", timeout=80)
        check("the stage opens live", ok)

        if want("none"):
            t0, r = await say_and_wait(b, "show it as a bar chart")
            pic = await picture(b, t0)
            check("a switch with no picture on screen says so, and asks the pipeline nothing",
                  r and r.get("speak", "").startswith("There's no chart on screen yet") and all(a["local"] for a in pic["asks"]), (r, pic["asks"]))

        if want("views"):
            t0, r = await say_and_wait(b, "PMAY-G houses sanctioned by district")
            base = await picture(b, t0)
            check("a district answer is drawn (the map and the ranking)", "map" in base["kinds"] and len(base["kinds"]) >= 2, base["kinds"])
            users0 = await b.eval("userBubbles().length")
            steps = [
                ("show it on the map", "map", "Here it is on the map, sir.", True, "11_map.png"),
                ("show it as a ranking", "race", "Here it is as a ranking.", True, "12_ranking.png"),
                ("show it as horizontal bars", "race", "Here it is as horizontal bars.", True, "13_horizontal.png"),
                ("show it as a bar chart", "bars", "Here it is as a bar chart.", False, "14_bars.png"),
                ("show it as a pie chart", "donut", "Here it is as a pie chart.", False, "15_pie.png"),
                # districts are not over time: bars, said why (an answer that also carries its years has a line)
                (("show it as a line chart", "line", "Here it is as a line chart.", False, "16_line.png")
                 if any(c["kind"] == "line" for c in base["cards"]) else
                 ("show it as a line chart", "bars", "This one isn't over time, so a line wouldn't fit. Here it is as a bar chart instead.", False, "16_line_fallback.png")),
                ("show it as a table", "table", "Here it is as a table.", False, "17_table.png"),
            ]
            for say, kind, line, local, shot in steps:
                t0, r = await say_and_wait(b, say)
                pic = await picture(b, t0)
                speak = (r or {}).get("speak", "")
                await b.shot(str(SHOTS / shot))
                check(f"'{say}': the picture switches to {kind} first, the voice says \"{line}\"",
                      pic["kinds"][:1] == [kind] and speak == line and "Drawn here" not in speak
                      and min(pic["ink"] or [0]) > 30, {"kinds": pic["kinds"], "speak": speak, "ink": pic["ink"], "applied": pic["applied"]})
                if local:
                    check(f"'{say}': drawn on the stage with no pipeline question",
                          len(pic["asks"]) == 1 and pic["asks"][0]["local"] and pic["view"] in ("map", "ranking", "horizontal"), pic["asks"])
                check(f"'{say}': every figure on the cards is a cell of the answer", not cells_ok(pic), cells_ok(pic)[:4])
            users1 = await b.eval("userBubbles()")
            check("bar / line / pie / table are the chat's redraws (they show in the chat); map / ranking / horizontal are the stage's",
                  len(users1) - users0 == 4 and users1[-1].lower().startswith("show it as a table"), users1[-6:])

        if want("nav"):
            # navigation by voice (the user, 2026-11-11: "back to the dashboard" was answered "I don't have information
            # about that"): done on the stage, one short line, never a pipeline question, nothing added to the chat
            if not await b.eval("gridCards().length"):
                await say_and_wait(b, "PMAY-G houses sanctioned by district")
            users0 = await b.eval("userBubbles().length")
            t0, r = await say_and_wait(b, "go back to the dashboard")
            ev = await b.eval(f"vlog().filter(e => e.t > {t0} && e.type === 'ask')")
            desk = await b.eval("stage() && stage().classList.contains('desk') && !gridCards().length")
            check("'go back to the dashboard': the desk comes back, 'Here's the dashboard, sir.', no pipeline question",
                  r and r.get("speak") == "Here's the dashboard, sir." and desk and all(a.get("local") for a in ev), (r, desk, ev))
            await b.shot(str(SHOTS / "18_nav_desk.png"))
            t0, r = await say_and_wait(b, "go back to the dashboard")
            check("'go back to the dashboard' on the desk: 'You're on the dashboard, sir.'",
                  r and r.get("speak") == "You're on the dashboard, sir.", r)
            t0, r = await say_and_wait(b, "bring the chart back")
            back = await b.eval("gridCards().length")
            check("'bring the chart back': the last chart is on the stage again, 'Here's the chart again, sir.'",
                  r and r.get("speak") == "Here's the chart again, sir." and back > 0, (r, back))
            await b.shot(str(SHOTS / "19_nav_chart.png"))
            users1 = await b.eval("userBubbles().length")
            check("navigation adds nothing to the chat thread", users1 == users0, (users0, users1))
            errs = await b.eval("window.__errs")
            check("navigation: no page errors", not errs, errs)

        if want("explain"):
            await b.eval("window.__stageExplain = null")
            users0 = await b.eval("userBubbles().length")
            t0, r = await say_and_wait(b, "How many PMAY-G houses were completed?")
            ex = await b.eval("""(async () => { await until(() => window.__stageExplain && ['shown', 'dropped', 'skipped'].includes(window.__stageExplain.state), 25000);
                await sleep(1500); return { ex: window.__stageExplain, kinds: kinds(), ink: gridCards().map(c => canvasInk(c.querySelector('canvas'))),
                  explainCls: gridCards().map(c => c.classList.contains('vc-explain')), tag: (document.querySelector('.vc-explain .vc-tag') || {}).innerText || '',
                  users: userBubbles() }; })()""", timeout=60)
            e = ex["ex"] or {}
            await b.shot(str(SHOTS / "21_explain.png"))
            data = [x for x in (e.get("data") or []) if isinstance(x, dict)]
            items = ((e.get("card") or {}).get("items") or [])
            part_cells = all(any(str(x.get("value")) and abs(float(str(row.get(x.get("col"))).replace(",", "") or 0) - float(x["value"])) < 1e-6
                                 for row in data if row.get(x.get("col")) is not None) for x in items if x.get("value") is not None)
            tol = max(1.0, abs(float(e.get("total") or 0)) * 0.005)
            check("a single figure gets the breakdown that explains it, beside the tile",
                  e.get("state") == "shown" and len(ex["kinds"]) == 2 and ex["explainCls"] == [False, True] and min(ex["ink"]) > 30,
                  {"state": e.get("state"), "why": e.get("why"), "q": e.get("q"), "kinds": ex["kinds"], "ink": ex["ink"]})
            check("its parts add up to the figure, and every part is a cell of the second answer",
                  e.get("state") == "shown" and abs(float(e.get("sum") or 0) - float(e.get("total") or 0)) <= tol and part_cells and len(items) >= 2,
                  {"sum": e.get("sum"), "total": e.get("total"), "n": len(items)})
            check("the breakdown is not in the chat thread (asked in a throwaway session)",
                  len(ex["users"]) - users0 == 1 and not any("by district" in u.lower() for u in ex["users"][-2:]), ex["users"][-3:])
            hist = await b.eval("""(async () => { await sleep(9000); const r = await fetch('/api/history?limit=60', { headers: { Authorization: 'Bearer ' + localStorage.getItem('megh_jwt') } });
                const j = await r.json(); return (j.conversations || []).map(c => c.session_id).filter(s => String(s).startsWith('voice_explain_')); })()""", timeout=40)
            check("no throwaway conversation is left in the officer's history", hist == [], hist)
            t0, r = await say_and_wait(b, "show it on the map")
            speak = (r or {}).get("speak", "")
            check("a switch on a single figure says plainly there is nothing to draw", "single figure" in speak, speak)

        if want("queue"):
            # two calls as the relay sends them: the second arrives while the first answer is still being written
            t0 = await b.eval("performance.now()")
            await b.eval("""window.__meghVoice.inject({ type: 'tool_call', id: 'test-q1', key: 'k1', question: 'MGNREGA person-days by district in 2023-24' });""")
            await b.eval("(async () => { await until(() => window.__meghVoice.pending(), 5000); await sleep(700); })()")
            await b.eval("""window.__meghVoice.inject({ type: 'tool_call', id: 'test-q2', key: 'k2', question: 'Focus Plus beneficiaries by district' });""")
            mid = await b.eval("({ queued: window.__meghVoice.queued(), pending: window.__meghVoice.pending() })")
            q = await b.eval(f"""(async () => {{
                const r2 = await until(() => vlog().find(e => e.type === 'reply' && e.id === 'test-q2'), 200000);
                await sleep(2500);
                const ev = vlog().filter(e => e.t > {t0});
                return {{ r1: ev.find(e => e.type === 'reply' && e.id === 'test-q1') || null, r2,
                         order: ev.filter(e => ['ask', 'queued', 'dequeue', 'reply'].includes(e.type)).map(e => e.type + ':' + (e.id || '')),
                         users: userBubbles().slice(-2), kinds: kinds() }}; }})()""", timeout=260)
            check("a question that arrives while an answer is being written is queued, not refused",
                  mid["queued"] and mid["queued"]["id"] == "test-q2" and mid["pending"] and mid["pending"]["id"] == "test-q1", mid)
            check("the running answer is finished and read, then the queued question is asked and answered",
                  q["r1"] and q["r2"] and q["r1"]["t"] < q["r2"]["t"] and "still being written" not in (q["r1"]["speak"] or "")
                  and q["order"].index("dequeue:test-q2") > q["order"].index("reply:test-q1")
                  and "Focus Plus" in " ".join(q["users"]), q)
            # the newest wins: a third call while the second waits replaces it
            t0 = await b.eval("performance.now()")
            await b.eval("""window.__meghVoice.inject({ type: 'tool_call', id: 'test-q3', key: 'k3', question: 'PMAY-G houses completed by district' });""")
            await b.eval("(async () => { await until(() => window.__meghVoice.pending(), 5000); await sleep(500); })()")
            await b.eval("""window.__meghVoice.inject({ type: 'tool_call', id: 'test-q4', key: 'k4', question: 'CM Elevate applications by district' });""")
            await b.eval("sleep(300)")
            await b.eval("""window.__meghVoice.inject({ type: 'tool_call', id: 'test-q5', key: 'k5', question: 'MGNREGA expenditure by district' });""")
            n = await b.eval(f"""(async () => {{ await until(() => vlog().find(e => e.type === 'reply' && e.id === 'test-q5'), 200000); await sleep(1500);
                const ev = vlog().filter(e => e.t > {t0});
                return {{ dropped: ev.filter(e => e.type === 'queue_drop').map(e => e.id), superseded: ev.filter(e => e.type === 'superseded').map(e => e.id),
                         asked: ev.filter(e => e.type === 'ask').map(e => e.id) }}; }})()""", timeout=260)
            check("only the newest waiting question is asked (an older waiting one is replaced and answered as such)",
                  n["dropped"] == ["test-q4"] and n["superseded"] == ["test-q4"] and n["asked"] == ["test-q3", "test-q5"], n)

        if want("phone"):
            await b.cmd("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
            await b.eval("sleep(800)")
            t0, r = await say_and_wait(b, "MGNREGA person-days by district in 2023-24")
            t0, r = await say_and_wait(b, "show it as a ranking")
            ph = await b.eval("""(() => { const g = gridCards(); const r = g.map(c => c.getBoundingClientRect());
                return { w: innerWidth, sw: document.documentElement.scrollWidth, kinds: kinds(), fits: r.every(x => x.left >= 0 && x.right <= innerWidth + 1),
                         chip: (document.querySelector('.vs-viewchip') || {}).innerText || '' }; })()""")
            await b.shot(str(SHOTS / "31_phone_ranking.png"))
            check("phone: a switch fits the width, no sideways scroll", ph["kinds"][:1] == ["race"] and ph["fits"] and ph["sw"] <= ph["w"] + 1, ph)
            await b.eval("window.__stageExplain = null")
            t0, r = await say_and_wait(b, "How many PMAY-G houses were sanctioned?")
            ex = await b.eval("""(async () => { await until(() => window.__stageExplain && ['shown', 'dropped', 'skipped'].includes(window.__stageExplain.state), 25000);
                await sleep(1500); const g = gridCards(); const r = g.map(c => c.getBoundingClientRect());
                return { state: (window.__stageExplain || {}).state, why: (window.__stageExplain || {}).why, kinds: kinds(),
                         fits: r.every(x => x.left >= 0 && x.right <= innerWidth + 1), sw: document.documentElement.scrollWidth, w: innerWidth }; })()""", timeout=60)
            await b.shot(str(SHOTS / "32_phone_explain.png"))
            check("phone: the breakdown sits under the figure, inside the width", ex["state"] == "shown" and len(ex["kinds"]) == 2 and ex["fits"] and ex["sw"] <= ex["w"] + 1, ex)
            await b.cmd("Emulation.setDeviceMetricsOverride", width=1600, height=940, deviceScaleFactor=1, mobile=False)

        await b.eval("document.querySelector('.vs-end') && document.querySelector('.vs-end').click()")
        errs = await b.eval("window.__errs")
        check("no page errors", not errs and not [e for e in b.events if e[0] == "exception"], (errs, b.events[:5]))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed · screenshots in {SHOTS}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

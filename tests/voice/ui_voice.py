"""The live voice in the real chat page, end to end (2026-11-02).

Headless Edge (tests/voice/cdp.py) opens /megh-chat on a running app, signed in with a token minted the way the live
suites mint one, taps the mic, and talks through the test hook (?voicetest=1: text sent as if spoken). The answers come
from the REAL pipeline (megh_db + the gateway; VPN on). The voice is either the fake Gemini Live server
(tests/voice/fake_live.py; start the app with VOICE_LIVE_URL=ws://127.0.0.1:8499) or the real one (--real).

Checks: the live session opens with the AudioWorklet; a spoken data question is answered in the chat exactly like a
typed one (the officer's words in the bubble, the same figure as POST /api/query) and read back with no deviation; a
follow-up by voice keeps the pipeline's context; a clarification is asked aloud and answered by voice; a chart view by
voice; a lagging transcript does not cut the question short; a model that ignores the question is covered; a number from the model's memory is corrected by the harness;
a wrong number from the voice is corrected; talking over the voice cuts it at once; a cancelled call stops the answer; a typed question while live is read aloud;
End closes it; no page errors.

Run from the repo root with the .venv Python:
    python tests/voice/ui_voice.py [--base http://127.0.0.1:8401] [--real] [--shots DIR]
"""
import asyncio
import json
import os
import sys
import time
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)                                       # .env is read relative to the working directory
from cdp import Browser  # noqa: E402

ARGS = sys.argv[1:]
BASE = ARGS[ARGS.index("--base") + 1] if "--base" in ARGS else "http://127.0.0.1:8401"
REAL = "--real" in ARGS
SHOTS = Path(ARGS[ARGS.index("--shots") + 1]) if "--shots" in ARGS else Path(os.environ.get("TEMP", ".")) / "megh_voice_shots"
SHOTS.mkdir(parents=True, exist_ok=True)
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), str(detail)[:400]))
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else f"  <- {str(detail)[:400]}"), flush=True)


async def mint() -> str:
    from app import appdb, db, security

    if True:
        await db.init_pool()
        rec = await appdb.get_user_by_username(os.environ.get("MEGH_VOICE_USER", "superadmin"))
        return security.issue_token({"sub": str(rec["user_id"]), "username": rec["username"],
                                     "tenant_id": rec["tenant_id"], "role": rec["role"]}, ttl_minutes=180)


def silent_wav() -> str:
    p = Path(os.environ.get("TEMP", ".")) / "megh_voice_silence.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000 * 20)
    return str(p)


def http_answer(token: str, q: str) -> dict:
    req = urllib.request.Request(BASE + "/api/query", method="POST",
                                 data=json.dumps({"question": q, "session_id": f"voiceparity_{int(time.time() * 1000)}"}).encode(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=200).read())


def figures(text: str) -> list:
    """Every run of digits (with grouping commas and a decimal point) in a text, in order."""
    out, cur = [], ""
    for ch in (text or "") + " ":
        if ch.isdigit() or (cur and ch in ",." ):
            cur += ch
        else:
            if cur:
                out.append(cur.rstrip(",."))
            cur = ""
    return out


JS = """
window.sleep = ms => new Promise(r => setTimeout(r, ms));
window.until = async (f, ms) => { const t = Date.now(); while (Date.now() - t < ms) { try { const v = f(); if (v) return v; } catch (e) {} await sleep(100); } return null; };
window.vlog = () => (window.__meghVoice ? window.__meghVoice.log() : []);
window.lastReply = (after) => vlog().filter(e => e.type === 'reply' && e.t > after).pop();
window.lastBot = () => { const b = [...document.querySelectorAll('.msg.bot')]; return b.length ? b[b.length - 1].innerText : ''; };
// textContent: the chat under the voice view is visibility:hidden once it has sunk (05208c5), so innerText reads ''
window.lastUser = () => { const b = [...document.querySelectorAll('.msg.user .bubble')]; return b.length ? b[b.length - 1].textContent : ''; };
"""


async def turn(b, said, kind="say", wait=150):
    """Speak (or type into the live session) and wait for the voice to finish reading the answer."""
    t0 = await b.eval("performance.now()")
    await b.eval(f"window.__meghVoice.{kind}({json.dumps(said)})")
    r = await b.eval(f"""(async () => {{
        const t0 = {t0};
        const reply = await until(() => vlog().filter(e => e.type === 'reply' && e.t > t0).pop(), {wait * 1000});
        const done = await until(() => vlog().filter(e => e.type === 'turn_complete' && e.t > (reply ? reply.t : t0)).pop(), 30000);
        await until(() => !window.__meghVoice.playing(), 30000);          // the answer has finished playing
        return {{ reply, done, harness: vlog().filter(e => e.type === 'harness' && e.t > t0).pop() || null,
                  calls: vlog().filter(e => e.type === 'tool_call' && e.t > t0), user: lastUser(), bot: lastBot(),
                  latency: (document.querySelector('.live-latency') || {{}}).innerText || '' }};
    }})()""", timeout=wait + 40)
    return r


async def main():
    token = await mint()
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});sessionStorage.removeItem('focusSessionId');}}catch(e){{}}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));")
    print(f"live voice UI test on {BASE} ({'REAL Gemini Live' if REAL else 'fake Live'})", flush=True)
    async with Browser(mic_wav=silent_wav(), init_js=init) as b:
        await b.goto(BASE + "/megh-chat?voicetest=1", wait=4)
        await b.eval(JS)
        ok = await b.eval("(async () => !!(await until(() => document.querySelector('[data-testid=agent-orb]') && document.querySelector('.composer-input'), 20000)))()")
        check("chat page signed in, mic button present", ok)
        await b.eval("document.querySelector('[data-testid=agent-orb]').click()")
        live = await b.eval("(async () => await until(() => window.__meghVoice && window.__meghVoice.phase() === 'live', 20000))()")
        check("mic opens a live session", live, await b.eval("window.__meghVoice ? window.__meghVoice.log() : 'no hook'"))
        cap = await b.eval("vlog().find(e => e.type === 'capture') || null")
        check("microphone captured by the AudioWorklet (same-origin, CSP intact)", cap and cap.get("worklet"), cap)
        stage = await b.eval("(async () => { await until(() => document.querySelector('.vstage .vs-pill'), 5000); return (document.querySelector('.vstage .vs-pill') || {}).innerText || ''; })()")
        # the voice greets the Secretary when the stage opens (D-105), so the pill may say Speaking first
        check("the voice stage takes the screen (it replaces the strip)", "Listening" in stage or "Speaking" in stage, stage)
        await b.eval("(async () => { await until(() => vlog().some(e => e.type === 'turn_complete'), 15000); await until(() => !window.__meghVoice.playing(), 15000); })()", timeout=40)
        await b.shot(str(SHOTS / "01_live_open.png"))

        q1 = "MGNREGA person-days in West Garo Hills in 2023-24"
        r = await turn(b, q1)
        sp = ((r or {}).get("reply") or {}).get("speak", "")
        check("spoken question: the officer's words are the question in the chat", r and r["user"].strip() == q1, r and r["user"])
        check("spoken question: answered through the pipeline and read back", "54,89,616" in sp, sp)
        done = (r or {}).get("done") or {}
        check("read back with no unsourced number", done.get("deviations") == [], done)
        if not REAL:
            check("the voice said the checked answer word for word", "54,89,616" in (done.get("said") or ""), done.get("said"))
        else:
            said = done.get("said") or ""
            check("the voice said the figure (digits or words)", "54,89,616" in said or "5,489,616" in said or "fifty" in said.lower(), said)
        typed = http_answer(token, q1)
        check("same answer as the typed path (POST /api/query)", figures(typed.get("answer"))[:1] == figures(sp)[:1],
              f"typed {figures(typed.get('answer'))} voice {figures(sp)}")
        print(f"    latency shown: {(r or {}).get('latency')}", flush=True)
        await b.shot(str(SHOTS / "02_answered.png"))

        r = await turn(b, "and for Ri Bhoi")
        sp = ((r or {}).get("reply") or {}).get("speak", "")
        check("follow-up by voice keeps the pipeline's context (MGNREGA, 2023-24)", "Ri Bhoi" in sp and "person-days" in sp.lower(), sp)

        r = await turn(b, "how many beneficiaries under Focus")
        rep = (r or {}).get("reply") or {}
        check("a clarification is asked aloud with its options", rep.get("kind") == "clarification" and "Focus Plus" in rep.get("speak", ""), rep)
        r = await turn(b, "Focus Plus")
        rep = (r or {}).get("reply") or {}
        check("the clarification is answered by voice and resumed", rep.get("kind") in ("data", "clarification") and "Focus Plus" in (r or {}).get("bot", "") + rep.get("speak", ""), rep)

        r = await turn(b, "show it as a bar chart")
        rep = (r or {}).get("reply") or {}
        check("a chart view by voice redraws the last answer", "bar chart" in rep.get("speak", "").lower(), rep)
        await b.shot(str(SHOTS / "03_chart.png"))

        if not REAL:
            r = await turn(b, "!!lag PMAY-G houses sanctioned in Ri Bhoi")
            check("a lagging transcript does not cut the question short", r and r["user"].strip() == "PMAY-G houses sanctioned in Ri Bhoi", r and r["user"])

            t0 = await b.eval("performance.now()")
            await b.eval("window.__meghVoice.say('!!nothing how many job cards were issued in Ri Bhoi in 2023-24')")
            sil = await b.eval(f"""(async () => {{
                const h = await until(() => vlog().find(e => e.type === 'harness' && e.silent && e.t > {t0}), 20000);
                const r = await until(() => vlog().find(e => e.type === 'reply' && e.id === null && e.t > {t0}), 150000);
                await until(() => !window.__meghVoice.playing() && vlog().some(e => e.type === 'turn_complete' && r && e.t > r.t), 40000);
                return {{ h: !!h, speak: r ? r.speak : '' }}; }})()""", timeout=220)
            check("a model that ignores the question: the page answers it through the pipeline and it is read", sil["h"] and sil["speak"], sil)

            r = await turn(b, "!!memory person-days in East Khasi Hills in 2023-24", wait=180)
            check("a number from the model's own memory is caught and the pipeline answers instead",
                  r and r.get("harness") and r["harness"].get("fromMemory") and (r.get("reply") or {}).get("speak"), r)

            t0 = await b.eval("performance.now()")
            await b.eval("window.__meghVoice.say('!!wrong MGNREGA person-days in Ri Bhoi in 2023-24')")
            fix = await b.eval(f"""(async () => {{
                const c = await until(() => vlog().find(e => e.type === 'correction' && e.t > {t0}), 150000);
                const d = await until(() => vlog().filter(e => e.type === 'turn_complete' && e.t > (c ? c.t : 1e12) && e.said).pop(), 30000);
                await until(() => !window.__meghVoice.playing(), 30000);
                return {{ c, said: d ? d.said : '' }}; }})()""", timeout=200)
            check("a number the voice gets wrong is corrected by re-reading the checked answer",
                  fix and fix["c"] and "9999999" in (fix["c"].get("deviations") or []) and fix["said"].startswith("To be exact:"), fix)

            t0 = await b.eval("performance.now()")
            await b.eval("window.__meghVoice.say('tell me about MGNREGA eligibility')")
            playing = await b.eval("(async () => !!(await until(() => window.__meghVoice.playing(), 150000)))()", timeout=170)
            check("a long answer starts playing", playing)
            await b.eval("window.__meghVoice.say('hello')")
            cut = await b.eval(f"""(async () => {{ const t = performance.now();
                const e = await until(() => vlog().find(x => x.type === 'interrupted' && x.t > {t0}), 4000);
                const stopped = await until(() => !window.__meghVoice.playing(), 3000);
                return {{ interrupted: !!e, stopped: !!stopped, ms: Math.round(performance.now() - t) }}; }})()""")
            check("talking over the voice cuts it at once (model interrupt or local cut)", cut and cut["stopped"] and cut["ms"] < 1500, cut)
            await b.eval("(async () => { await until(() => vlog().filter(e => e.type === 'turn_complete').length && !window.__meghVoice.playing(), 8000); await sleep(1500); })()")

            t0 = await b.eval("performance.now()")
            await b.eval("window.__meghVoice.say('!!cancel how many houses were sanctioned under PMAY-G in South Garo Hills')")
            stopped = await b.eval(f"""(async () => {{
                const c = await until(() => vlog().find(e => e.type === 'tool_cancel' && e.t > {t0}), 20000);
                const s = await until(() => [...document.querySelectorAll('.msg.bot')].some(m => m.innerText.includes('Stopped')), 20000);
                return {{ cancel: !!c, stopped: !!s }}; }})()""")
            check("a cancelled call stops the answer in the chat", stopped and stopped["cancel"] and stopped["stopped"], stopped)
            await b.eval("sleep(2500)")

        t0 = await b.eval("performance.now()")
        await b.eval("""(() => { const ta = document.querySelector('.composer-input');
            const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
            set.call(ta, 'How many PMAY-G houses were sanctioned in total?'); ta.dispatchEvent(new Event('input', { bubbles: true }));
            setTimeout(() => document.querySelector('.send-btn').click(), 100); })()""")
        read = await b.eval(f"(async () => await until(() => vlog().find(e => e.type === 'reply' && e.id === null && e.t > {t0}), 150000))()", timeout=170)
        check("a typed question while live is answered on screen and read aloud", read and read.get("speak"), read)
        await b.eval("(async () => { await until(() => vlog().filter(e => e.type === 'turn_complete' && e.t > " + str(t0) + ").length, 30000); })()", timeout=40)
        await b.shot(str(SHOTS / "04_typed_read.png"))

        await b.eval("document.querySelector('.vs-end').click()")
        off = await b.eval("(async () => await until(() => window.__meghVoice.phase() === 'off', 5000))()")
        check("End closes the live session and the stage", off and not await b.eval("!!document.querySelector('.vstage')"))
        errs = await b.eval("window.__errs")
        check("no page errors", not errs and not [e for e in b.events if e[0] == "exception"], (errs, b.events[:5]))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed · screenshots in {SHOTS}", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

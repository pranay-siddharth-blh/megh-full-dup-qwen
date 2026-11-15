"""The voice's transcript on the stage is exactly what the voice said, in order (2026-11-16, the user's live test on the
sovereign engine: "in the transcript of the AI some random words are added at the start: for 'One moment, sir.' a
'the' is there in front of the 'One'; when the voice says 'Sure' one more word comes").

The sovereign engine speaks separate LINES in real time, word by word: a holding line ("One moment, sir." / "Sure,
sir.") and then the answer line (its first word with a leading space). The fake Live's `!!realtime` / `!!realtime2`
do exactly that. A recorder keeps every text the caption band (.vs-megh) ever shows. Each one must be the start of what
the voice said in that part of the turn: the holding line alone while the answer is being worked out (never glued to
the answer), then the answer alone; never a word of the previous answer, of the holding line or of the officer in
front of it, never a word twice.

Cases: holding line + answer; two answers in a row; an answer after a barge-in (a new question while one is read); a
chart switch's line ("Here it is on the map, sir.").

Run from the repo root:  python tests/voice/ui_voice_transcript.py --base http://127.0.0.1:8404
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

REC = JS + """
window.__capSeen = []; window.__capRec = false;
window.__capPoll = () => {
  if (window.__capRec) {
    const m = document.querySelector('.vs-megh');
    const t = m ? m.textContent.split(' ').filter(Boolean).join(' ') : '';
    const last = window.__capSeen[window.__capSeen.length - 1];
    if (!last || last.text !== t) window.__capSeen.push({ t: Math.round(performance.now()), text: t,
      working: !!document.querySelector('.vs-stagearea.working') || !!document.querySelector('.vs-step') });
  }
  requestAnimationFrame(window.__capPoll);
};
requestAnimationFrame(window.__capPoll);
window.wordsOf = (s) => String(s || '').split(' ').filter(Boolean);
"""


def words(s):
    return [w for w in str(s or "").split() if w]


def prefix_of(shown, line):
    """`shown` is the start of `line` (its last word may still be growing)."""
    a, b = words(shown), words(line)
    if not a:
        return True
    if len(a) > len(b):
        return False
    return a[:-1] == b[:len(a) - 1] and b[len(a) - 1].startswith(a[-1])


async def reading(b, said, wait_end=True):
    """Say it; return every caption text seen, and the voice's answer (`speak`) for this turn."""
    t0 = await b.eval("performance.now()")
    await b.eval("window.__capSeen = []; window.__capRec = true;")
    await b.eval(f"window.__meghVoice.say({json.dumps(said)})")
    r = await b.eval(f"""(async () => {{
        const rep = await until(() => vlog().filter(e => e.type === 'reply' && e.t > {t0} && e.kind !== 'superseded').pop(), 170000);
        if ({'true' if wait_end else 'false'}) {{
          await until(() => vlog().some(e => e.type === 'turn_complete' && e.t > (rep ? rep.t : {t0}) && (e.said || '').length > 20), 60000);
          await until(() => !window.__meghVoice.playing(), 60000);
          await sleep(1500);
        }}
        return {{ speak: rep ? (rep.speak || '') : '', kind: rep ? rep.kind : null }}; }})()""", timeout=260)
    seen = await b.eval("(() => { window.__capRec = false; return window.__capSeen.map(x => x.text); })()")
    return r, [s for s in seen if s]


PREV = {"last": ""}


def judge(label, seen, lines, final_line):
    """Every caption seen is the start of one of `lines` (the parts the voice said, each on its own); the last one
    shown is `final_line`, whole. The previous answer's caption may stay until the new reading begins."""
    while seen and PREV["last"] and words(seen[0]) == words(PREV["last"]):
        seen = seen[1:]
    PREV["last"] = seen[-1] if seen else PREV["last"]
    bad = [s for s in seen if not any(prefix_of(s, ln) for ln in lines)]
    check(f"{label}: every caption shown is the start of a line the voice said, nothing in front of it, nothing twice",
          not bad, {"bad": bad[:4], "lines": lines})
    last = seen[-1] if seen else ""
    check(f"{label}: at the end the caption is exactly the answer as said", words(last) == words(final_line),
          {"last": last, "want": final_line})


async def main():
    token = await mint()
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});sessionStorage.removeItem('focusSessionId');}}catch(e){{}}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));")
    print(f"voice transcript test on {BASE} (fake Live, real-time lines)", flush=True)
    async with Browser(port=9379, mic_wav=silent_wav(), init_js=init, size=(1536, 864)) as b:
        await b.goto(BASE + "/megh-chat?voicetest=1", wait=4)
        await b.eval(REC)
        await b.eval("(async () => !!(await until(() => document.querySelector('[data-testid=agent-orb]'), 20000)))()")
        await b.eval("document.querySelector('[data-testid=agent-orb]').click()")
        ok = await b.eval("""(async () => { const ok = !!(await until(() => window.__meghVoice && window.__meghVoice.phase() === 'live', 25000));
            await until(() => vlog().some(e => e.type === 'turn_complete'), 25000);
            await until(() => !window.__meghVoice.playing(), 20000); await sleep(800); return ok; })()""", timeout=80)
        check("the stage opens live", ok)

        # 1. a holding line, then the answer (each word in real time)
        r, seen = await reading(b, "!!realtime PMAY-G houses sanctioned by district")
        print("   1:", seen[:3], "...", seen[-1:], flush=True)
        judge("holding line + answer", seen, ["One moment, sir.", r["speak"]], r["speak"])
        lead_seen = [s for s in seen if prefix_of(s, "One moment, sir.")]
        check("holding line + answer: the holding line is shown on its own while the answer is worked out",
              any(words(s) == words("One moment, sir.") for s in lead_seen), seen[:6])

        # 2. a second answer right after (the previous answer's words never lead the new caption)
        r2, seen2 = await reading(b, "!!realtime2 MGNREGA person-days by district")
        print("   2:", seen2[:3], "...", seen2[-1:], flush=True)
        judge("two answers in a row", seen2, ["Sure, sir.", r2["speak"]], r2["speak"])

        # 3. a barge-in: a new question while the answer is being read
        t0 = await b.eval("performance.now()")
        await b.eval("window.__meghVoice.say('!!realtime Focus Plus beneficiaries by district')")
        await b.eval(f"(async () => {{ await until(() => vlog().some(e => e.type === 'reply' && e.t > {t0}), 170000); "
                     f"await until(() => window.__meghVoice.playing(), 30000); await sleep(1800); }})()", timeout=220)
        r3, seen3 = await reading(b, "!!realtime PMAY-G houses completed by district")
        print("   3:", seen3[:3], "...", seen3[-1:], flush=True)
        judge("an answer after a barge-in", seen3, ["One moment, sir.", r3["speak"]], r3["speak"])

        # 4. a chart switch: the stage's own line
        r4, seen4 = await reading(b, "show it on the map")
        print("   4:", seen4[:3], "...", seen4[-1:], flush=True)
        judge("a chart switch's line", seen4, [r4["speak"]], r4["speak"])

        errs = await b.eval("window.__errs")
        check("no page errors", not errs and not [e for e in b.events if e[0] == "exception"], (errs, b.events[:5]))
        await b.eval("document.querySelector('.vs-end') && document.querySelector('.vs-end').click()")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

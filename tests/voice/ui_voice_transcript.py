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
REAL = "--real" in ARGS     # the real engine (its own holding lines): the test directives are dropped, what was said is
                            # the relay's own record of the turn (turn_complete `said`)

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


PREV = {"last": ""}


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
    # what the band shows before the question (the greeting, the answer before) may stay until the new reading begins
    PREV["last"] = await b.eval("(() => { const m = document.querySelector('.vs-megh'); return m ? m.textContent.split(' ').filter(Boolean).join(' ') : ''; })()")
    await b.eval("window.__capSeen = []; window.__capRec = true;")
    if REAL:
        said = said.split(" ", 1)[1] if said.startswith("!!") else said
    await b.eval(f"window.__meghVoice.say({json.dumps(said)})")
    r = await b.eval(f"""(async () => {{
        const rep = await until(() => vlog().filter(e => e.type === 'reply' && e.t > {t0} && e.kind !== 'superseded').pop(), 170000);
        if ({'true' if wait_end else 'false'}) {{
          await until(() => vlog().some(e => e.type === 'turn_complete' && e.t > (rep ? rep.t : {t0}) && (e.said || '').length > 20), 60000);
          await until(() => !window.__meghVoice.playing(), 60000);
          await sleep(1500);
        }}
        const tcs = vlog().filter(e => e.type === 'turn_complete' && e.t > {t0} && (e.said || '').trim());
        return {{ speak: rep ? (rep.speak || '') : '', kind: rep ? rep.kind : null, said: tcs.map(e => e.said) }}; }})()""", timeout=260)
    seen = await b.eval("(() => { window.__capRec = false; return window.__capSeen.map(x => x.text); })()")
    return r, [s for s in seen if s]


def real_lines(r):
    """On the real engine: the parts it said, split at its sentences (the holding line is a sentence of its own), and
    the answer = the said text from the first sentence that starts the answer the page asked it to read."""
    said = " ".join(r.get("said") or [])
    sents, cur = [], []
    for w in words(said):                      # no regex (D-046 / D-047): a sentence ends at a word ending . ? !
        cur.append(w)
        if w[-1] in ".?!":
            sents.append(" ".join(cur))
            cur = []
    if cur:
        sents.append(" ".join(cur))
    head = words(r.get("speak"))[:2]
    at = next((i for i, x in enumerate(sents) if head and words(x)[:2] == head), 0)
    lines = [" ".join(sents[:at])] if at else []
    return [ln for ln in lines if ln] + [" ".join(sents[at:])], " ".join(sents[at:])


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
    print(f"voice transcript test on {BASE} ({'the REAL engine' if REAL else 'fake Live, real-time lines'})", flush=True)
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
        if REAL:
            print("      said:", r["said"], flush=True)
            judge("holding line + answer", seen, *real_lines(r))
        else:
            judge("holding line + answer", seen, ["One moment, sir.", r["speak"]], r["speak"])
            lead_seen = [s for s in seen if prefix_of(s, "One moment, sir.")]
            check("holding line + answer: the holding line is shown on its own while the answer is worked out",
                  any(words(s) == words("One moment, sir.") for s in lead_seen), seen[:6])

        # 2. a second answer right after (the previous answer's words never lead the new caption)
        r2, seen2 = await reading(b, "!!realtime2 MGNREGA person-days by district")
        print("   2:", seen2[:3], "...", seen2[-1:], flush=True)
        if REAL:
            print("      said:", r2["said"], flush=True)
        judge("two answers in a row", seen2, *(real_lines(r2) if REAL else (["Sure, sir.", r2["speak"]], r2["speak"])))

        # 3. a barge-in: a new question while the answer is being read
        t0 = await b.eval("performance.now()")
        await b.eval("window.__meghVoice.say(" + json.dumps(("" if REAL else "!!realtime ") + "Focus Plus beneficiaries by district") + ")")
        await b.eval(f"(async () => {{ await until(() => vlog().some(e => e.type === 'reply' && e.t > {t0}), 170000); "
                     f"await until(() => window.__meghVoice.playing(), 30000); await sleep(1800); }})()", timeout=220)
        r3, seen3 = await reading(b, "!!realtime PMAY-G houses completed by district")
        print("   3:", seen3[:3], "...", seen3[-1:], flush=True)
        if REAL:
            print("      said:", r3["said"], flush=True)
        judge("an answer after a barge-in", seen3, *(real_lines(r3) if REAL else (["One moment, sir.", r3["speak"]], r3["speak"])))

        # 4b. two holding lines (the engine's later filler comes after the answer has reached the page), then the answer
        if not REAL:
            r5, seen5 = await reading(b, "!!realtime3 Which scheme leads in each district?")
            print("   5:", seen5[:3], "...", seen5[-1:], flush=True)
            judge("two holding lines, then the answer", seen5, ["One moment, sir.", "Still working on it, sir.", r5["speak"]], r5["speak"])
            check("two holding lines: the answer's caption never starts with a holding line",
                  not any(words(x)[:2] in (["Still", "working"], ["One", "moment,"]) and len(words(x)) > 4 for x in seen5), seen5[:8])

        # 4. a chart switch: the stage's own line
        r4, seen4 = await reading(b, "show it on the map")
        print("   4:", seen4[:3], "...", seen4[-1:], flush=True)
        if REAL:      # no new answer takes the stage: the reading is shown whole, exactly as the engine said it
            print("      said:", r4["said"], flush=True)
            sw = " ".join(r4["said"])
            judge("a chart switch's line", seen4, [sw], sw)
        else:
            judge("a chart switch's line", seen4, [r4["speak"]], r4["speak"])

        errs = await b.eval("window.__errs")
        check("no page errors", not errs and not [e for e in b.events if e[0] == "exception"], (errs, b.events[:5]))
        await b.eval("document.querySelector('.vs-end') && document.querySelector('.vs-end').click()")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""The voice stage's captions and its picture, measured frame by frame (2026-11-15, the user's live test of the merged
build: "the transcript at the top is flickering or not coming at all", "each word, when it streams, the whole sentence
is jumping up and down", "the visualization used to come a lot faster; now it is late and not in line with the answer").

Headless Edge (tests/voice/cdp.py, muted) on /megh-chat?voicetest=1, the real pipeline (VPN), the fake Gemini Live
(tests/voice/fake_live.py; start the app with VOICE_LIVE_URL=ws://127.0.0.1:<fake port>; VOICE_BLOCK_UNSOURCED on, the
default). A sampler on every animation frame records the caption band (how many words, each word's top edge, its scroll
position), the stage's cards and which of their items are in, and whether the voice's audio is playing.

Readings:
  * `burst` (the fake's `!!burst`): the way the real Gemini Live sends an answer, transcript and audio in a burst well
    ahead of real time, the audio at a natural pace; the relay's guard releases the captions a sentence at a time;
  * `paced`: the fake's ordinary pace (audio about as fast as it plays, like the sovereign engine). The guard holds a
    sentence's words until it has been said, so here the captions can only follow a sentence behind: only their
    steadiness is checked.

Checks:
  - (burst) Megh's words are on screen within 1.5 s of the first audio and keep up with it: half-way through the audio,
    between 30 % and 70 % of the words are shown (not the end of the burst, not ahead of the voice);
  - (all) the captions never blank or shrink while the voice speaks and grow a word or two at a time (no sentence
    dropped in at once);
  - (all) no bobble: a word on screen never moves except the whole band scrolling UP when it is full (no downward
    movement, no movement without a scroll);
  - (all) the picture's first card is up no later than the voice's first audio;
  - (burst) the picture is in line with the voice: the first item that comes in comes within -1.0 / +1.5 s of the
    moment the audio reaches its name (or, when the voice names nothing, within 3.5 s of the first audio).

Run from the repo root:  python tests/voice/ui_voice_captions.py --base http://127.0.0.1:8412 [--dump]
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
DUMP = "--dump" in ARGS
REAL = "--real" in ARGS     # the real engine: the test directives are dropped and every reading is judged as paced
SHOTS = Path(os.environ.get("TEMP", ".")) / "megh_caption_shots"
SHOTS.mkdir(parents=True, exist_ok=True)

# the sampler: one row per animation frame
SAMPLER = JS + """
window.__cap = []; window.__capOn = false;
window.__capTick = () => {
  if (window.__capOn) {
    const m = document.querySelector('.vs-megh'); const c = document.querySelector('.vs-captions');
    const ws = m ? [...m.querySelectorAll('.w')] : [];
    const cards = [...document.querySelectorAll('.vs-grid > .vc')].filter(x => !x.classList.contains('vc-ghost'));
    const items = (window.__stageCards ? window.__stageCards() : []).flatMap(k => k.items || []);
    const capBox = c ? c.getBoundingClientRect() : null;
    window.__cap.push({ t: performance.now(), n: ws.length,
      tops: ws.slice(0, 80).map(w => Math.round(w.getBoundingClientRect().top * 10) / 10),
      scroll: c ? c.scrollTop : 0, capTop: capBox ? Math.round(capBox.top) : null,
      cards: cards.map(x => +getComputedStyle(x).opacity), on: items.filter(i => i.on).map(i => String(i.key)),
      playing: !!(window.__meghVoice && window.__meghVoice.playing()),
      parked: !!document.querySelector('.vstage.parked') });
  }
  requestAnimationFrame(window.__capTick);
};
requestAnimationFrame(window.__capTick);
"""


def norm(s):
    """' west garo hills ' — lower-case letters and digits, single spaces, padded (no regex)."""
    out = " "
    for ch in str(s or "").lower():
        if ch.isalnum():
            out += ch
        elif not out.endswith(" "):
            out += " "
    return out if out.endswith(" ") else out + " "


async def reading(b, said, label):
    """Ask `said`, sample every frame until the voice has finished reading it; return the measurements."""
    await b.eval("(async () => { await until(() => !window.__meghVoice.playing() && !window.__meghVoice.pending(), 60000); await sleep(1500); })()", timeout=80)
    t0 = await b.eval("performance.now()")
    if REAL and said.startswith("!!"):
        said = said.split(" ", 1)[1]
    await b.eval(f"window.__cap = []; window.__capOn = true; window.__meghVoice.say({json.dumps(said)})")
    await b.eval(f"""(async () => {{
        const r = await until(() => vlog().filter(e => e.type === 'reply' && e.t > {t0}).pop(), 150000);
        await until(() => vlog().some(e => e.type === 'turn_complete' && r && e.t > r.t), 60000);
        await until(() => !window.__meghVoice.playing(), 60000); await sleep(1500); window.__capOn = false; }})()""", timeout=300)
    rows = await b.eval("window.__cap")
    log = await b.eval(f"vlog().filter(e => e.t > {t0})")
    words = await b.eval("[...document.querySelectorAll('.vs-megh .w')].map(w => w.textContent)")
    plan = await b.eval("(window.__stagePlan && window.__stagePlan.cards || []).flatMap(c => (c.items || []).map(i => ({ key: String(i.key), label: i.label || '', many: (c.items || []).length > 1 })))")
    await b.shot(str(SHOTS / f"{label}.png"))
    return analyse(rows, log, words, plan, label)


def analyse(rows, log, words, plan, label):
    reply = next((e for e in log if e["type"] == "reply"), None)
    t_reply = reply["t"] if reply else None
    after = [r for r in rows if t_reply is not None and r["t"] >= t_reply - 50]
    first_play = next((r["t"] for r in after if r["playing"]), None)
    last_play = max((r["t"] for r in after if r["playing"]), default=None)
    first_card = next((r["t"] for r in after if r["cards"] and max(r["cards"]) > 0.5), None)
    first_cap = next((r["t"] for r in after if first_play and r["t"] >= first_play and r["n"]), None)
    first_out = next((e["t"] for e in log if e["type"] == "out" and reply and e["t"] >= reply["t"]), None)
    # the new picture's items: from the first frame with none in (the previous picture's items may still be listed)
    start = next((i for i, r in enumerate(after) if not r["on"]), None)
    first_item, first_keys = None, []
    if start is not None:
        hit = next((r for r in after[start:] if r["on"]), None)
        if hit:
            first_item, first_keys = hit["t"], hit["on"]
    # captions while the voice plays (from the first word shown): never blank or shrink, grow a word or two at a time
    playing = [r for r in after if first_cap and first_cap <= r["t"] <= (last_play or 0)]
    blank = sum(1 for r in playing if not r["n"])
    shrink, steps, prev = 0, [], None
    for r in playing:
        if prev is not None:
            if r["n"] < prev:
                shrink += 1
            elif r["n"] > prev:
                steps.append(r["n"] - prev)
        prev = r["n"]
    total = max((r["n"] for r in after), default=0)
    mid = None
    if first_play and last_play:
        tm = first_play + (last_play - first_play) * 0.5
        mid = next((r["n"] for r in after if r["t"] >= tm), None)
    # bobble: a word on screen in two consecutive frames moved; allowed only as a scroll UP of the whole band
    moved_no_scroll, moved_down, max_jump = 0, 0, 0.0
    for a, b in zip(after, after[1:]):
        k = min(len(a["tops"]), len(b["tops"]))
        if not k or a["capTop"] != b["capTop"] or a["parked"] != b["parked"]:
            continue
        deltas = [b["tops"][i] - a["tops"][i] for i in range(k)]
        dmax = max(deltas, key=abs)
        if abs(dmax) > 0.6:
            max_jump = max(max_jump, abs(dmax))
            if abs(b["scroll"] - a["scroll"]) <= 0.5:
                moved_no_scroll += 1
            if dmax > 0.6:
                moved_down += 1
    # in line: when the audio reaches the first revealed item's name (the fake speaks at an even pace)
    # (of the items that came in on that frame, the one the voice names first)
    expected, named, first_key = None, False, (first_keys[0] if first_keys else None)
    # (a single figure's tile is not "named": it comes in by Mitra's rule when nothing on the cards is named)
    label_of = {p["key"]: p["label"] for p in plan}
    many = {p["key"] for p in plan if p.get("many")}
    said = [norm(w).strip() for w in words]
    best = None
    for key in [k for k in first_keys if k in many]:
        lab = norm(label_of.get(key, "")).split()
        at = next((i for i in range(len(said) - len(lab) + 1) if lab and said[i:i + len(lab)] == lab), None)
        if at is not None and (best is None or at < best[0]):
            best = (at, key)
    if best and first_play and last_play:
        first_key = best[1]
        expected, named = first_play + (last_play - first_play) * best[0] / max(1, len(said)), True
    out = {"label": label, "first_card_ms": _ms(first_card, t_reply), "first_play_ms": _ms(first_play, t_reply),
           "first_caption_ms": _ms(first_cap, t_reply), "first_text_ms": _ms(first_out, t_reply), "first_item_ms": _ms(first_item, t_reply),
           "first_item": label_of.get(first_key, first_key), "item_named": named,
           "item_vs_audio_ms": round(first_item - expected) if (first_item and expected) else None,
           "card_vs_voice_ms": round(first_card - first_play) if (first_card and first_play) else None,
           "audio_ms": round(last_play - first_play) if (first_play and last_play) else None,
           "words_total": total, "words_at_half_audio": mid, "caption_steps": len(steps),
           "biggest_step_words": max(steps, default=0), "blank_frames": blank, "shrink": shrink,
           "moved_without_scroll": moved_no_scroll, "moved_down": moved_down, "max_jump_px": round(max_jump, 1),
           "frames": len(after)}
    if DUMP:
        Path(os.environ.get("TEMP", ".")).joinpath(f"megh_caption_{label}.json").write_text(
            json.dumps({"rows": rows, "log": log, "words": words, "plan": plan, "out": out}, indent=1), encoding="utf-8")
    return out


def _ms(t, t0):
    return round(t - t0) if t is not None and t0 is not None else None


def judge(m, burst):
    lab = m["label"]
    if burst:
        # the relay releases the captions a checked sentence at a time; a data answer's first sentence runs to its first
        # full stop ("... years: A is the largest with N; B is the smallest with M."), so its text can come ~2 s in
        check(f"{lab}: Megh's words are on the stage as soon as their text arrives (within 0.4 s) and within 2.5 s of the first audio",
              m["first_caption_ms"] is not None and m["first_text_ms"] is not None and m["first_play_ms"] is not None
              and m["first_caption_ms"] - m["first_text_ms"] <= 400 and m["first_caption_ms"] - m["first_play_ms"] <= 2500, m)
        check(f"{lab}: the captions keep up with the audio (half-way through it, 30-70 % of the words are shown)",
              m["words_at_half_audio"] is not None and 0.3 * m["words_total"] <= m["words_at_half_audio"] <= 0.7 * m["words_total"], m)
    check(f"{lab}: the captions never blank or shrink while the voice speaks",
          m["first_caption_ms"] is not None and m["blank_frames"] == 0 and m["shrink"] == 0, m)
    check(f"{lab}: the captions stream a word or two at a time (no sentence dropped in at once)",
          m["caption_steps"] >= m["words_total"] // 3 and m["biggest_step_words"] <= 3, m)
    check(f"{lab}: no bobble: a word on screen never moves except the band scrolling up when it is full",
          m["moved_without_scroll"] == 0 and m["moved_down"] == 0, m)
    check(f"{lab}: the picture is up no later than the voice starts",
          m["first_card_ms"] is not None and m["card_vs_voice_ms"] is not None and m["card_vs_voice_ms"] <= 150, m)
    if burst:
        if m["item_named"]:
            check(f"{lab}: the picture is in line with the voice (its first item within -1.0 / +1.5 s of its name in the audio)",
                  m["item_vs_audio_ms"] is not None and -1000 <= m["item_vs_audio_ms"] <= 1500, m)
        else:
            check(f"{lab}: the picture's items come in while the voice reads (nothing named: within 3.5 s of the first audio)",
                  m["first_item_ms"] is not None and m["first_play_ms"] is not None and m["first_item_ms"] - m["first_play_ms"] <= 3500, m)


async def main():
    token = await mint()
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});sessionStorage.removeItem('focusSessionId');}}catch(e){{}}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));")
    print(f"voice captions test on {BASE} (fake Live)", flush=True)
    async with Browser(port=9377, mic_wav=silent_wav(), init_js=init, size=(1536, 864)) as b:
        await b.goto(BASE + "/megh-chat?voicetest=1", wait=4)
        await b.eval(SAMPLER)
        # the agent orb opens the voice (D-113); a build before it: the composer's mic did
        await b.eval("(async () => !!(await until(() => document.querySelector('[data-testid=agent-orb], .mic-btn'), 20000)))()")
        await b.eval("(document.querySelector('[data-testid=agent-orb]') || document.querySelector('.mic-btn')).click()")
        ok = await b.eval("(async () => !!(await until(() => window.__meghVoice && window.__meghVoice.phase() === 'live', 20000)))()")
        check("the orb opens the live voice", ok)
        await b.eval("(async () => { await until(() => vlog().some(e => e.type === 'turn_complete'), 20000); await until(() => !window.__meghVoice.playing(), 20000); })()", timeout=50)
        for said, label, burst in (("!!burst PMAY-G houses sanctioned by district", "burst_ranking", True),
                                   ("!!burst How many PMAY-G houses were completed?", "burst_single", True),
                                   ("MGNREGA person-days by district in 2023-24", "paced", False)):
            m = await reading(b, said, label)
            print("   ", json.dumps(m), flush=True)
            judge(m, burst and not REAL)
        # the single figure's explaining breakdown is asked in a throwaway session, deleted 4 s after it is saved:
        # the page stays open long enough for that (it would otherwise be left in the officer's history)
        await b.eval("sleep(8000)", timeout=20)
        errs = await b.eval("window.__errs")
        check("no page errors", not errs and not [e for e in b.events if e[0] == "exception"], (errs, b.events[:5]))
        await b.eval("document.querySelector('.vs-end') && document.querySelector('.vs-end').click()")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed · screenshots in {SHOTS}", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

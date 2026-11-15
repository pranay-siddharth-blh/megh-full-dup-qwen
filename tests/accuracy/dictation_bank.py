"""Dictation accuracy bank (D-111, 15 Nov 2026): the 240 spoken questions of the Full Duplex voice work streamed
through /ws/dictate in real time, heard by the real qwen3-asr on the gateway.

Clips: D:\\Full Duplex Architecture\\data\\spoken_bank\\{a,b,c,pranay}\\<sha1(question)[:16]>.npy (16 kHz float32;
three designed Indian voices and the user's own), the questions of harness/megh/live_spoken_accuracy.py (copied
below). Read only; nothing is written there.

What runs: this file starts the dictation socket on a FREE port in this process (never 8401): the real
router, session, segmenter, cleaner and BatchEar, the app's settings (.env: the ASR URL / key, never printed),
the shared HTTP client (llm.init_client). Sign-in is replaced by a per-clip token. Each clip is streamed as
80 ms PCM16 frames every 80 ms after 0.3 s of room silence, then 0.6 s of silence, then `stop`.

Measured per clip: final text, word error rate (normalised: lower case, punctuation off, hyphens as spaces,
spoken numbers as digits on both sides), facts kept (every scheme, district, block / constituency, year and
measure word of the written question is in the final text; no scheme, district or year added), first-partial
latency (first non-empty partial after the first voiced frame was sent), final latency (stop sent -> final).
Every speech-model call is recorded (its raw words, audio length, time) so cleaning can be re-tuned offline
without calling the gateway again: tests/accuracy/results/dictation_bank_<label>.json.

Targets (D-111): facts kept >= 98 %, normalised WER <= 4 %, scheme names 100 %, FY written 20XX-YY 100 %,
first partial <= 1.0 s p50, final <= 1.0 s p50 for utterances <= 20 s.

Run:  python tests/accuracy/dictation_bank.py [--voices a,b,c,pranay] [--n 60] [--conc 2] [--label run1] [--dry]
      --dry: a fake ear (no gateway), to check the plumbing.
      --rescore <results.json>: score a recorded run again with today's cleaning (no audio, no gateway).
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CLIPS = Path(os.environ.get("DICTATION_BANK_CLIPS", r"D:\Full Duplex Architecture\data\spoken_bank"))
RESULTS = ROOT / "tests" / "accuracy" / "results"

QUESTIONS = [
    "What was the total expenditure in West Garo Hills during 2023-24?",
    "How many total person-days were generated in East Khasi Hills during 2023-24?",
    "How many households received employment in Nongstoin block during 2025-26?",
    "What was the average number of person-days per employment household in South West Khasi Hills during 2024-25?",
    "Which block generated the highest person-days during 2023-24?",
    "How many persons received employment in Amlarem constituency during 2022-23?",
    "Give me the expenditure breakdown for Myriem during 2023-24.",
    "How many PMAY beneficiaries are there in Amlarem block?",
    "Give me the house status breakdown for Amlarem block.",
    "How many PMAY houses have been completed in West Garo Hills?",
    "How many PMAY beneficiaries are there in West Garo Hills?",
    "PMAY-G houses completed by district",
    "Show MGNREGA person-days trend over the years as a line chart",
    "Show total Focus Legacy amount remitted in each financial year as a line chart",
    "CM Elevate applications by status as a donut chart",
    "Compare PMAY-G houses sanctioned versus completed by district",
    "Show MGNREGA expenditure by financial year as a bar chart",
    "Show MGNREGA person-days by district",
    "Top five districts by Focus Plus beneficiaries as a pie chart",
    "Compare total beneficiaries in PMAY-G and MGNREGA",
    "How many PMAY-G houses have been sanctioned and completed in Meghalaya, and what is the completion rate?",
    "How much PMAY-G money has been released in total in Meghalaya?",
    "How many CM Elevate applications are there?",
    "What is the total amount disbursed under Focus Plus?",
    "How many producer groups and memberships have been paid under Focus Legacy?",
    "How much has been disbursed under CM Elevate Legacy, split into subsidy and loan?",
    "How many villages had MGNREGA activity and how many person-days were generated in total?",
    "How much PMAY-G money has been released in West Garo Hills?",
    "How many households completed 100 days of MGNREGA work in Meghalaya in 2025-26?",
    "How many Focus Plus disbursements have been made and in how many districts?",
    "Give me the headline figure of every scheme",
    "Which scheme leads in each district?",
    "Compare East Khasi Hills and West Garo Hills across every scheme",
    "In Ri Bhoi, give me each scheme's figures",
    "How much money has each scheme disbursed?",
    "MGNREGA person-days in West Garo Hills in 2023-24",
    "How have MGNREGA person-days changed over the last three years in West Garo Hills?",
    "MGNREGA person-days by financial year",
    "MGNREGA expenditure in crore for the whole state, year by year",
    "How many job cards are there in South Garo Hills?",
    "PMAY-G houses sanctioned in Ri Bhoi in 2022-23",
    "How many people got Focus Plus money in Ri Bhoi?",
    "Which district has the highest Focus Plus beneficiaries?",
    "What is the Focus Legacy amount in East Jaintia Hills?",
    "CM Elevate Legacy subsidy disbursed in West Jaintia Hills",
    "How many CM Elevate applications are there in North Garo Hills?",
    "PMAY-G release in Eastern West Khasi Hills",
    "MGNREGA households employed in South West Garo Hills in 2024-25",
    "Focus Legacy producer groups in West Khasi Hills",
    "Which district spent the most under MGNREGA in 2022-23?",
    "What is MGNREGA and what are its main objectives?",
    "Who is eligible for a house under PMAY-G?",
    "What is the difference between Focus Legacy and Focus Plus?",
    "How much financial assistance is given per house under PMAY-G in Meghalaya?",
    "PMAY-G houses completed in East Garo Hills in 2021-22",
    "Total MGNREGA wages paid in Ri Bhoi during 2023-24",
    "How many Focus Plus beneficiaries are there in South West Khasi Hills?",
    "CM Elevate applications sent back in East Khasi Hills",
    "Compare MGNREGA expenditure in Ri Bhoi and West Garo Hills in 2023-24",
    "Show PMAY-G houses sanctioned per year as a line",
]
MEASURE_WORDS = ["person-days", "person days", "expenditure", "households", "houses", "beneficiaries", "applications",
                 "job cards", "producer groups", "memberships", "disbursed", "released", "sanctioned", "completed",
                 "subsidy", "wages", "villages", "amount", "money", "persons"]


def clip_path(voice: str, q: str) -> Path:
    return CLIPS / voice / (hashlib.sha1(q.encode("utf-8")).hexdigest()[:16] + ".npy")


# ── scoring ─────────────────────────────────────────────────────────────────

def norm_words(text: str) -> list:
    from app.dictation.numbers import spoken_text
    t = spoken_text(text or "")
    t = t.lower().replace("-", " ").replace("₹", " rs ").replace("%", " percent")
    return [w for w in "".join(ch if ch.isalnum() else " " for ch in t).split() if w]


def wer(ref: str, hyp: str) -> float:
    r, h = norm_words(ref), norm_words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


_PLACES: list = []


def _place_forms() -> list:
    """(spaced form, canonical) for blocks and constituencies, from the scheme catalogues."""
    if not _PLACES:
        from app import entity_resolver as er
        if not er._catalog:
            er.load_all()
        seen = set()
        for dims in er._catalog.values():
            for level in ("block", "constituency"):
                for v in dims.get(level) or []:
                    canon = str(v.get("canonical") or "")
                    for f in [canon, *(v.get("aliases") or [])]:
                        sp = " ".join(norm_words(str(f)))
                        if len(sp) > 4 and (sp, canon.lower()) not in seen:
                            seen.add((sp, canon.lower()))
                            _PLACES.append((sp, canon.lower()))
    return _PLACES


def facts(text: str) -> dict:
    from app import scheme_registry, spelling
    low = " " + " ".join(norm_words(text)) + " "
    raw = (text or "")
    schemes = set()
    for s in sorted(scheme_registry.NAMES, key=len, reverse=True):
        if (" " + " ".join(norm_words(s)) + " ") in low and not any(s.lower() in o.lower() for o in schemes):
            schemes.add(s)
    if " pmay " in low and "PMAY-G" not in schemes:
        schemes.add("PMAY-G")                                   # "PMAY" = PMAY-G, as the voice harness reads it
    districts = set()
    for d in sorted(spelling.districts(), key=len, reverse=True):
        if (" " + " ".join(norm_words(d)) + " ") in low and not any(d in o for o in districts):
            districts.add(d)
    places = {c for sp, c in _place_forms() if " " + sp + " " in low}
    years = set()
    for w in raw.replace(",", " ").replace("?", " ").replace(".", " ").split():
        c = w.strip("()").lower()
        c = c[2:] if c.startswith("fy") else c
        if len(c) >= 4 and c[:2] == "20" and c[:4].isdigit() and (len(c) == 4 or (len(c) == 7 and c[4] == "-")):
            years.add(c)
    flat = " " + " ".join(norm_words(text)) + " "
    measures = set()
    for m in MEASURE_WORDS:
        stem = " ".join(norm_words(m))
        stem = stem[:-1] if stem.endswith("s") else stem
        if " " + stem in flat:
            measures.add(m)
    return {"schemes": schemes, "districts": districts, "places": places, "years": years, "measures": measures}


def score(q: str, text: str) -> dict:
    fw, fa = facts(q), facts(text)
    lost = {k: sorted(fw[k] - fa[k]) for k in fw if fw[k] - fa[k]}
    added = {k: sorted(fa[k] - fw[k]) for k in ("schemes", "districts", "years") if fa[k] - fw[k]}
    fy_ref = [y for y in fw["years"] if len(y) == 7]
    return {"ok": bool(text) and not lost and not added, "lost": lost, "added": added, "wer": round(wer(q, text), 3),
            "has_scheme": bool(fw["schemes"]), "schemes_ok": not (fw["schemes"] - fa["schemes"]),
            "has_fy": bool(fy_ref), "fy_ok": all(y in fa["years"] for y in fy_ref)}


def p50(xs: list) -> "float | None":
    xs = [x for x in xs if x is not None]
    return round(float(np.median(xs)), 3) if xs else None


def p90(xs: list) -> "float | None":
    xs = [x for x in xs if x is not None]
    return round(float(np.percentile(xs, 90)), 3) if xs else None


def summary(rows: list) -> dict:
    n = len(rows)
    sch = [r for r in rows if r["has_scheme"]]
    fy = [r for r in rows if r["has_fy"]]
    short = [r for r in rows if r["seconds"] <= 20]
    return {
        "clips": n,
        "facts_kept_pct": round(100 * sum(r["ok"] for r in rows) / max(1, n), 1),
        "wer_mean_pct": round(100 * float(np.mean([r["wer"] for r in rows])) if rows else 0, 2),
        "schemes_pct": round(100 * sum(r["schemes_ok"] for r in sch) / max(1, len(sch)), 1),
        "fy_pct": round(100 * sum(r["fy_ok"] for r in fy) / max(1, len(fy)), 1),
        "first_partial_p50_s": p50([r["first_partial_s"] for r in rows]),
        "first_partial_p90_s": p90([r["first_partial_s"] for r in rows]),
        "final_p50_s_le20": p50([r["final_s"] for r in short]),
        "final_p90_s_le20": p90([r["final_s"] for r in short]),
        "no_final": sum(1 for r in rows if not r["text"]),
    }


# ── the run ─────────────────────────────────────────────────────────────────

_CLIP = contextvars.ContextVar("dictation_bank_clip", default="")
CALLS: dict = {}            # clip id -> [{len_s, timeout, raw, s}]


def _install(dry: bool):
    from app.dictation import ears, router

    class User:
        def __init__(self, key):
            self.key, self.username, self.name = key, "bank", "Bank"

    async def identify(token: str):
        if not token.startswith("bank-"):
            return None
        _CLIP.set(token[5:])
        return User(token[5:])

    class RecordingEar(ears.BatchEar):
        def __init__(self, clip: str):
            super().__init__()
            self.clip = clip

        async def transcribe(self, pcm16, prompt="", language="en", queue_timeout=10.0):
            t0 = time.monotonic()
            rec = {"len_s": round(len(pcm16) / 32000, 2), "timeout": queue_timeout}
            try:
                if dry:
                    await asyncio.sleep(0.2)
                    text = "dry run words."
                else:
                    text = await super().transcribe(pcm16, prompt, language, queue_timeout)
                rec.update(raw=text, s=round(time.monotonic() - t0, 3))
                return text
            except Exception as e:  # noqa: BLE001
                rec.update(error=type(e).__name__, s=round(time.monotonic() - t0, 3))
                raise
            finally:
                CALLS.setdefault(self.clip, []).append(rec)

    router.identify = identify
    ears.batch_ear = lambda: RecordingEar(_CLIP.get())


def _serve():
    import socket
    import threading

    import uvicorn
    from fastapi import FastAPI

    from app import llm
    from app.dictation import router
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def life(_app):
        await llm.init_client()
        yield
        await llm.close_client()

    app = FastAPI(lifespan=life)
    app.include_router(router.router)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    t0 = time.time()
    while time.time() - t0 < 30:
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return srv, th, f"ws://127.0.0.1:{port}/ws/dictate"


async def one(url: str, voice: str, q: str) -> dict:
    import websockets
    x = np.load(clip_path(voice, q)).astype(np.float32)
    pcm = np.concatenate([np.zeros(int(0.3 * 16000), np.float32), x, np.zeros(int(0.6 * 16000), np.float32)])
    pcm16 = (np.clip(pcm, -1, 1) * 32767).astype("<i2")
    voiced = np.nonzero(np.abs(pcm) > 0.02)[0]
    first_voice_frame = int(voiced[0] // 1280) if len(voiced) else 0
    clip_id = f"{voice}-{hashlib.sha1(q.encode('utf-8')).hexdigest()[:16]}"
    msgs, t_voice, t_stop = [], None, None
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "token": "bank-" + clip_id, "lang": "en"}))

        async def reader():
            try:
                async for raw in ws:
                    msgs.append((time.monotonic(), json.loads(raw)))
            except Exception:  # noqa: BLE001
                pass
        rt = asyncio.create_task(reader())
        while not msgs:
            await asyncio.sleep(0.01)
        start = time.monotonic()
        for k, i in enumerate(range(0, len(pcm16), 1280)):
            due = start + k * 0.08
            now = time.monotonic()
            if due > now:
                await asyncio.sleep(due - now)
            if k == first_voice_frame:
                t_voice = time.monotonic()
            await ws.send(pcm16[i:i + 1280].tobytes())
        t_stop = time.monotonic()
        await ws.send(json.dumps({"type": "stop"}))
        try:
            await asyncio.wait_for(rt, 30)
        except asyncio.TimeoutError:
            rt.cancel()
    final = next((m for _, m in msgs if m.get("type") == "final"), None)
    text = final["text"] if final else ""
    first_partial = next((t for t, m in msgs if m.get("type") == "partial" and (m.get("stable") or m.get("tentative"))
                          and t_voice and t >= t_voice), None)
    t_final = next((t for t, m in msgs if m.get("type") in ("final", "no_speech", "error")), None)
    row = {"voice": voice, "q": q, "clip": clip_id, "text": text, "seconds": round(len(x) / 16000, 2),
           "corrections": final.get("corrections") if final else [],
           "end": next((m.get("type") for _, m in msgs if m.get("type") in ("final", "no_speech", "error")), "none"),
           "partials": sum(1 for _, m in msgs if m.get("type") == "partial"),
           "first_partial_s": round(first_partial - t_voice, 3) if first_partial and t_voice else None,
           "final_s": round(t_final - t_stop, 3) if t_final and t_stop else None}
    row.update(score(q, text))
    return row


async def main(argv: list) -> int:
    def arg(name, default):
        return argv[argv.index(name) + 1] if name in argv else default
    if "--rescore" in argv:
        return rescore(Path(arg("--rescore", "")))
    voices = arg("--voices", "a,b,c,pranay").split(",")
    n = int(arg("--n", "60"))
    conc = int(arg("--conc", "2"))
    label = arg("--label", "dry" if "--dry" in argv else "run")
    dry = "--dry" in argv
    from app.config import settings
    from app.dictation import clean
    settings.DICTATE_ASR_CONCURRENCY = max(2, 2 * conc)   # each dictation: one live + one committing request
    settings.DICTATE_HELLO_PER_MINUTE = 0
    clean.ensure_catalogue()
    _install(dry)
    srv, th, url = _serve()
    items = [(v, q) for v in voices for q in QUESTIONS[:n] if clip_path(v, q).exists()]
    print(f"{len(items)} clips, {conc} at a time, {'DRY (fake ear)' if dry else 'qwen3-asr on the gateway'}",
          flush=True)
    sem = asyncio.Semaphore(conc)
    rows: list = []
    t_all = time.time()

    async def go(v, q):
        async with sem:
            try:
                r = await one(url, v, q)
            except Exception as e:  # noqa: BLE001
                r = {"voice": v, "q": q, "text": "", "error": type(e).__name__, "seconds": 0, "ok": False, "wer": 1.0,
                     "has_scheme": False, "schemes_ok": True, "has_fy": False, "fy_ok": True, "first_partial_s": None,
                     "final_s": None}
            r["calls"] = CALLS.get(r.get("clip", ""), [])
            rows.append(r)
            print(f"  {'PASS' if r['ok'] else 'FAIL'} [{v}] wer {r['wer']:.2f} fp {r.get('first_partial_s')} "
                  f"final {r.get('final_s')} {q!r}" + ("" if r["ok"] else f"\n        got {r['text']!r} lost "
                                                       f"{r.get('lost')} added {r.get('added')}"), flush=True)
    await asyncio.gather(*(go(v, q) for v, q in items))
    srv.should_exit = True
    th.join(10)
    s = summary(rows)
    s["seconds_run"] = round(time.time() - t_all)
    print(json.dumps(s, indent=1))
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"dictation_bank_{label}.json"
    out.write_text(json.dumps({"summary": s, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    print("written", out)
    return 0


def rescore(path: Path) -> int:
    """Score a recorded run again with today's cleaning: the final text is rebuilt from the recorded words of
    each call (segments, in order, then the whole-recording pass) exactly as session.finish() does."""
    from app.dictation import clean as cleaner
    from app.dictation.session import join_parts, merge
    cleaner.ensure_catalogue()
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for r in data["rows"]:
        calls = [c for c in r.get("calls") or [] if c.get("timeout") != 0.5 and "raw" in c]
        if not calls:
            rows.append(r)
            continue
        total = max(c["len_s"] for c in calls)
        whole = [c for c in calls if c["len_s"] >= total - 0.01 and len(calls) > 1]
        segs = [c for c in calls if c not in whole]
        ok = [c["raw"] for c in segs if not cleaner.why_not(c["raw"], _prompt(), c["len_s"], c["len_s"])]
        seg_text = cleaner.clean(join_parts([(t, 0.6) for t in ok])).text
        text = seg_text
        if whole and not cleaner.why_not(whole[-1]["raw"], _prompt(), total, total):
            text, _ = merge(cleaner.clean(whole[-1]["raw"]).text, seg_text)
        nr = dict(r)
        nr["text"] = text
        nr.update(score(r["q"], text))
        rows.append(nr)
    s = summary(rows)
    print(json.dumps(s, indent=1))
    for r in rows:
        if not r["ok"]:
            print(f"  FAIL [{r['voice']}] {r['q']!r}\n        got {r['text']!r} lost {r.get('lost')} added {r.get('added')}")
    return 0


def _prompt() -> str:
    from app.config import settings
    return settings.ASR_PROMPT


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))

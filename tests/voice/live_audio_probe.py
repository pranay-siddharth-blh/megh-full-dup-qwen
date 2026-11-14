"""Real speech through the live voice, on the REAL Gemini Live (2026-11-02). Costs live-audio credits: a few minutes.

Each question is synthesised with the Windows voice (System.Speech, 16 kHz mono), streamed to /ws/voice in real time
as an open microphone would (80 ms frames, then silence, which keeps flowing), and the page's part is played here:
each ask_megh call is answered through the real POST /api/query in ONE conversation (so follow-ups and clarification
replies resume exactly as in the chat), and the answer's text is returned to be read. Measures, per turn: what Gemini
heard, what reached the pipeline, the answer, what the voice said, numbers said without a source, and the time from
the end of the speech to the first word of audio.

Run from the repo root (app on 8401 with the real voice; VPN on):  python tests/voice/live_audio_probe.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import websockets  # noqa: E402

BASE = os.environ.get("MEGH_URL", "http://127.0.0.1:8401")
TMP = Path(os.environ.get("TEMP", ".")) / "megh_voice_clips"
TMP.mkdir(parents=True, exist_ok=True)
FRAME = 1280 * 2                                   # 80 ms of 16 kHz 16-bit mono

TURNS = [
    ("MGNREGA person-days in West Garo Hills in 2023-24", "54,89,616"),
    ("And for Ri Bhoi?", "Ri Bhoi"),
    ("How many beneficiaries under Focus?", "Focus Plus"),
    ("Focus Plus", ""),
    ("How many houses were sanctioned under PMAY-G in total?", ""),
]


def synth(text: str, path: Path) -> None:
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
          "[System.Speech.AudioFormat.AudioChannel]::Mono); "
          f"$s.SetOutputToWaveFile('{path}', $f); $s.Rate = 0; $s.Speak('{text.replace(chr(39), '')}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)


def pcm_of(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes())


def plain(answer: str) -> str:
    out = []
    for line in (answer or "").split("\n"):
        t = line.strip()
        if t.startswith("|"):
            cells = [c.strip() for c in t.split("|") if c.strip()]
            if cells and not all(set(c) <= set("-: ") for c in cells):
                out.append(", ".join(cells) + ".")
            continue
        while t.startswith("#"):
            t = t[1:]
        if t.startswith("- ") or t.startswith("* "):
            t = t[2:]
        if t.strip():
            out.append(t.strip())
    return " ".join(out).replace("**", "").replace("`", "").replace("≈", "about")[:560]


async def mint() -> str:
    from app import appdb, db, security
    await db.init_pool()
    rec = await appdb.get_user_by_username(os.environ.get("MEGH_VOICE_USER", "superadmin"))
    return security.issue_token({"sub": str(rec["user_id"]), "username": rec["username"],
                                 "tenant_id": rec["tenant_id"], "role": rec["role"]}, ttl_minutes=60)


def ask(token: str, sid: str, q: str) -> dict:
    req = urllib.request.Request(BASE + "/api/query", method="POST",
                                 data=json.dumps({"question": q, "session_id": sid}).encode(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=200).read())


def spoken(r: dict) -> dict:
    if r.get("route") == "clarification":
        labels = [str(o.get("label") or "") for o in ((r.get("clarification") or {}).get("options") or [])][:6]
        speak = plain(r.get("question") or r.get("answer") or "") + (f" The options are {', '.join(labels[:-1])} or {labels[-1]}." if len(labels) > 1 else "")
        return {"speak": speak, "kind": "clarification", "read_exactly": True}
    return {"speak": plain(r.get("answer") or "") or "The answer is on your screen.", "kind": r.get("route") or "answer", "read_exactly": True}


async def main():
    token = await mint()
    sid = f"voiceprobe_{int(time.time())}"
    clips = []
    for i, (q, _) in enumerate(TURNS):
        p = TMP / f"q{i}.wav"
        synth(q, p)
        clips.append(pcm_of(p))
    ws = await websockets.connect(BASE.replace("http", "ws") + "/ws/voice", max_size=None)
    await ws.send(json.dumps({"type": "hello", "token": token}))
    first = json.loads(await asyncio.wait_for(ws.recv(), 20))
    if first.get("type") != "ready":
        print("not ready:", first)
        return 1
    print("live session ready", flush=True)
    state = {"speech_end": 0.0, "first_audio": 0.0, "events": [], "audio": 0, "turns": [], "cur": None}

    async def mic():                                # the open microphone: speech when queued, silence otherwise
        silence = b"\x00" * FRAME
        t_next = time.perf_counter()
        while True:
            chunk = state.pop("speaking_chunks", None)
            if chunk:
                state["queue"] = chunk
            q = state.get("queue")
            if q:
                frame, state["queue"] = q[:FRAME], q[FRAME:]
                if not state["queue"]:
                    state["speech_end"] = time.perf_counter()
                    state.pop("queue")
                frame = frame.ljust(FRAME, b"\x00")
            else:
                frame = silence
            await ws.send(frame)
            t_next += 0.08
            await asyncio.sleep(max(0, t_next - time.perf_counter()))

    async def reader():
        async for m in ws:
            if isinstance(m, bytes):
                state["audio"] += len(m)
                if not state["first_audio"] and state["speech_end"]:
                    state["first_audio"] = time.perf_counter()
                continue
            e = json.loads(m)
            state["events"].append(e)
            if e["type"] == "tool_call":
                q = e.get("question") or e.get("heard")
                state["cur"]["pipeline_q"] = q
                state["cur"]["model_q"] = e.get("question")
                r = await asyncio.to_thread(ask, token, sid, q)
                res = spoken(r)
                state["cur"]["route"] = r.get("route")
                state["cur"]["answer"] = res["speak"]
                await ws.send(json.dumps({"type": "tool_result", "id": e["id"], "result": res}))
            elif e["type"] == "turn_complete" and state["cur"] is not None and (e.get("said") or e.get("called")):
                state["cur"].update(heard=e.get("user"), said=e.get("said"), deviations=e.get("deviations"),
                                    called=e.get("called"))
                state["cur"]["done"] = True

    mt, rt = asyncio.create_task(mic()), asyncio.create_task(reader())
    await asyncio.sleep(1.0)
    ok = 0
    for (q, expect), clip in zip(TURNS, clips):
        state["cur"] = {"spoken": q, "expect": expect}
        state["speech_end"] = state["first_audio"] = 0.0
        state["speaking_chunks"] = clip
        t0 = time.time()
        while not state["cur"].get("done") and time.time() - t0 < 150:
            await asyncio.sleep(0.1)
        await asyncio.sleep(1.5)                    # let the voice finish before the next question
        c = state["cur"]
        lat = round(state["first_audio"] - state["speech_end"], 2) if state["first_audio"] and state["speech_end"] else None
        good = bool(c.get("done")) and c.get("called") and (not expect or expect in (c.get("answer") or "")) \
            and not c.get("deviations")
        ok += good
        print(f"\n{'PASS' if good else 'FAIL'}  said aloud: {q}\n  Gemini heard:   {c.get('heard')}\n"
              f"  to pipeline:    {c.get('pipeline_q')}   (model's own wording: {c.get('model_q')})\n"
              f"  route:          {c.get('route')}\n  answer:         {(c.get('answer') or '')[:200]}\n"
              f"  voice said:     {(c.get('said') or '')[:200]}\n  unsourced:      {c.get('deviations')}\n"
              f"  end of speech -> first audio: {lat} s", flush=True)
        state["turns"].append({**c, "latency_s": lat})
    mt.cancel()
    rt.cancel()
    await ws.send(json.dumps({"type": "bye"}))
    await ws.close()
    out = TMP / "live_audio_probe.json"
    out.write_text(json.dumps(state["turns"], indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{ok}/{len(TURNS)} turns passed · audio received {state['audio'] / 48000:.1f} s · details {out}")
    return 0 if ok == len(TURNS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

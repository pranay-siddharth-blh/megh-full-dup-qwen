"""The whole chain with a real microphone signal, on the REAL Gemini Live (2026-11-02).

Headless Edge's fake microphone plays a WAV: 2 s of silence, a question spoken by the Windows voice, then two minutes of
silence. The chat page captures it with the AudioWorklet, streams it, Gemini hears it and decides the turn is over,
calls ask_megh, the page answers it through the real pipeline, and the voice plays back. Checks the question in the
chat, the figure read back, no unsourced number, audio played, and prints the end-of-speech -> first-audio time.

Run from the repo root (app on 8401 with the real voice; VPN on):
    python tests/voice/ui_voice_mic.py ["question"] ["expected figure"]
"""
import asyncio
import os
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)
from cdp import Browser  # noqa: E402
from ui_voice import JS, check, mint, RESULTS  # noqa: E402

BASE = os.environ.get("MEGH_URL", "http://127.0.0.1:8401")
Q = sys.argv[1] if len(sys.argv) > 1 else "MGNREGA person days in West Garo Hills in 2023-24"
# how the Windows voice is made to say it the way officers do: the acronym letter by letter, "rega" as a word
SAY = Q.replace("MGNREGA", "M G N rega")
EXPECT = sys.argv[2] if len(sys.argv) > 2 else "54,89,616"


def mic_wav(text: str) -> str:
    tmp = Path(os.environ.get("TEMP", "."))
    speech = tmp / "megh_voice_q.wav"
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
          "[System.Speech.AudioFormat.AudioChannel]::Mono); "
          f"$s.SetOutputToWaveFile('{speech}', $f); $s.Speak('{text.replace(chr(39), '')}'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)
    with wave.open(str(speech), "rb") as w:
        pcm = w.readframes(w.getnframes())
    out = tmp / "megh_voice_mic.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 32000 + pcm + b"\x00\x00" * 16000 * 120)
    return str(out)


async def main():
    token = await mint()
    import json
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});sessionStorage.removeItem('focusSessionId');}}catch(e){{}}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));")
    print(f"microphone test on {BASE}: '{Q}'", flush=True)
    async with Browser(port=9363, mic_wav=mic_wav(SAY), init_js=init) as b:
        await b.goto(BASE + "/megh-chat?voicetest=1", wait=4)
        await b.eval(JS)
        await b.eval("(async () => !!(await until(() => document.querySelector('.mic-btn'), 20000)))()")
        await b.eval("document.querySelector('.mic-btn').click()")
        r = await b.eval("""(async () => {
            const live = await until(() => window.__meghVoice && window.__meghVoice.phase() === 'live', 20000);
            const call = await until(() => vlog().find(e => e.type === 'tool_call'), 60000);
            const reply = await until(() => vlog().find(e => e.type === 'reply'), 150000);
            const played = await until(() => window.__meghVoice.playing(), 30000);
            // the answer's turn (the greeting read when the stage opens is a turn of its own, with no call)
            const done = await until(() => vlog().filter(e => e.type === 'turn_complete' && e.said && e.called).pop(), 60000);
            await until(() => !window.__meghVoice.playing(), 30000);
            return { live: !!live, call, reply, played: !!played, done, user: lastUser(),
                     latency: (document.querySelector('.live-latency') || {}).innerText || '',
                     cap: vlog().find(e => e.type === 'capture') || null };
        })()""", timeout=330)
        check("live session over the real microphone path (AudioWorklet)", r["live"] and r["cap"] and r["cap"].get("worklet"), r.get("cap"))
        check("Gemini heard the question and called ask_megh", r["call"], r.get("call"))
        print(f"    heard: {(r.get('call') or {}).get('heard')!r} · call: {(r.get('call') or {}).get('question')!r}", flush=True)
        check("the question in the chat", r["user"] and "West Garo Hills" in r["user"], r["user"])
        sp = (r.get("reply") or {}).get("speak", "")
        check("the pipeline's answer went back to the voice", EXPECT in sp, sp)
        check("the answer was played", r["played"])
        done = r.get("done") or {}
        check("read back with no unsourced number", done.get("deviations") == [], done)
        print(f"    voice said: {(done.get('said') or '')[:160]!r}", flush=True)
        print(f"    end of speech -> first audio: {r['latency']}", flush=True)
        await b.shot(str(Path(os.environ.get('TEMP', '.')) / "megh_voice_mic.png"))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} passed", flush=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

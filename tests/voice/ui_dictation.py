"""Dictation in the real page (D-111, 2026-11-15): headless Edge (tests/voice/cdp.py) with Chromium's fake
microphone playing a spoken question, against a SMALL server on a free port (never 8401): the built page
(web/app), stub sign-in / history / health, and the real /ws/dictate (router, session, segmenter, cleaner) with
a fake ear that answers any audio holding voice with one fixed sentence (no gateway, no database).

Checks: the mic button is "Dictate (speak to type)"; tapping it starts dictation with the box VISIBLE (not the
1 px recording strip) and the dictation bar up; words arrive in the box while listening; ✓ inserts the cleaned
final at the caret between the words already typed ("in reply" -> Ri Bhoi), one Undo puts the box back; Esc
during dictation puts the box back exactly; Ctrl+M starts dictation; no page errors.

Run: python tests/voice/ui_dictation.py   (needs `npm run build` first; writes screenshots to %TEMP%)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "voice"))

from cdp import Browser  # noqa: E402

CLIP = Path(r"D:\Full Duplex Architecture\data\spoken_bank\a")
SHOTS = Path(tempfile.gettempdir()) / "megh_dictation_ui"
RESULTS: list = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   -> {detail!r}"), flush=True)


def mic_wav() -> str:
    """A spoken question from the bank (any clip), with a second of quiet each side, as a 16 kHz WAV."""
    f = sorted(CLIP.glob("*.npy"))[0] if CLIP.is_dir() else None
    x = np.load(f).astype(np.float32) if f else np.sin(np.arange(48000) / 16000 * 2 * np.pi * 220) * 0.2
    x = np.concatenate([np.zeros(16000), x, np.zeros(16000 * 3)])
    out = Path(tempfile.gettempdir()) / "megh_dictation_mic.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return str(out)


def serve():
    import socket
    import threading
    import time

    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles

    from app.dictation import clean, ears, router

    class Ear(ears.BatchEar):
        async def _post(self, wav, prompt, language):
            await asyncio.sleep(0.15)
            x = np.frombuffer(wav[44:], dtype="<i2").astype(np.float32) / 32768
            return "how many houses were completed in reply district." if len(x) and np.abs(x).max() > 0.01 else "Okay."

    class User:
        key, username, name = "1", "ui", "UI Test"

    async def identify(token):
        return User() if token == "ui-token" else None

    router.identify = identify
    ears.batch_ear = lambda: Ear(url="http://fake", model="fake", key="k")
    clean.ensure_catalogue()

    app = FastAPI()
    app.include_router(router.router)
    app.mount("/static", StaticFiles(directory=str(ROOT / "web")), name="static")

    @app.get("/megh-chat")
    async def page():
        return FileResponse(ROOT / "web" / "app" / "index.html")

    @app.get("/api/auth/me")
    async def me():
        return {"username": "ui", "name": "UI Test", "role": "superadmin", "schemes": []}

    @app.get("/api/history")
    async def history():
        return {"conversations": []}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE"])
    async def other(rest: str):
        return JSONResponse({}, status_code=200)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return srv, f"http://127.0.0.1:{port}"


HELPERS = """
window.sleep = (ms) => new Promise(r => setTimeout(r, ms));
window.until = async (f, ms) => { const t = Date.now(); while (Date.now() - t < ms) { try { const v = f(); if (v) return v; } catch (e) {} await sleep(50); } return null; };
window.ta = () => document.querySelector('.composer-input');
window.typeIn = (v, caret) => { const t = ta(); const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
  set.call(t, v); t.dispatchEvent(new Event('input', { bubbles: true })); t.focus(); t.setSelectionRange(caret, caret); };
"""


async def main() -> int:
    SHOTS.mkdir(exist_ok=True)
    srv, base = serve()
    init = "try{localStorage.setItem('megh_jwt','ui-token');}catch(e){}" + HELPERS
    try:
        async with Browser(port=9361, mic_wav=mic_wav(), init_js=init) as b:
            await b.goto(base + "/megh-chat", wait=3)
            ok = await b.eval("(async () => !!(await until(() => document.querySelector('.mic-btn') && ta(), 15000)))()")
            check("page up, signed in, mic present", ok)
            title = await b.eval("document.querySelector('.mic-btn').title")
            check("the mic is dictation", title.startswith("Dictate (speak to type)"), title)

            # 1) dictate into the middle of typed words, insert with the tick
            await b.eval("typeIn('Show me  please', 8)")
            await b.eval("document.querySelector('.mic-btn').click()")
            bar = await b.eval("(async () => !!(await until(() => document.querySelector('.dict-bar.listening'), 8000)))()")
            check("dictation bar listening", bar)
            vis = await b.eval("(() => { const r = ta().getBoundingClientRect(); return r.width > 100 && r.height > 20; })()")
            check("the prompt box stays visible while dictating", vis)
            pressed = await b.eval("document.querySelector('.mic-btn').getAttribute('aria-pressed')")
            check("mic aria-pressed while dictating", pressed == "true", pressed)
            live = await b.eval("(async () => await until(() => ta().value.includes('houses') && ta().value, 12000))()")
            check("words arrive in the box while speaking", bool(live), live)
            await b.shot(str(SHOTS / "01_listening.png"))
            await b.eval("document.querySelector('.dict-done').click()")
            final = await b.eval("(async () => { await until(() => !document.querySelector('.dict-bar'), 10000); return ta().value; })()")
            check("final inserted at the caret, cleaned", final == "Show me how many houses were completed in Ri Bhoi district please",
                  final)
            toast = await b.eval("(async () => { const t = await until(() => document.querySelector('.undo-toast, .toast'), 3000); return t ? t.innerText : ''; })()")
            check("one undo offered, the correction named", "Dictation inserted" in toast and "Ri Bhoi" in toast, toast)
            undone = await b.eval("(async () => { const btn = [...document.querySelectorAll('button')].find(x => x.innerText.trim() === 'Undo'); if (!btn) return null; btn.click(); await sleep(200); return ta().value; })()")
            check("undo puts the box back", undone == "Show me  please", undone)
            await b.shot(str(SHOTS / "02_inserted.png"))

            # 2) Esc cancels and restores exactly
            await b.eval("typeIn('keep this', 4)")
            await b.eval("document.querySelector('.mic-btn').click()")
            await b.eval("(async () => { await until(() => document.querySelector('.dict-bar.listening'), 8000); await until(() => ta().value !== 'keep this', 8000); })()")
            await b.eval("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))")
            back = await b.eval("(async () => { await until(() => !document.querySelector('.dict-bar'), 5000); const t = ta(); return [t.value, t.selectionStart]; })()")
            check("Esc puts the box back exactly", back == ["keep this", 4], back)

            # 3) Ctrl+M starts dictation, the mic again stops it
            await b.eval("typeIn('', 0)")
            await b.eval("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'm', ctrlKey: true, bubbles: true }))")
            km = await b.eval("(async () => !!(await until(() => document.querySelector('.dict-bar'), 8000)))()")
            check("Ctrl+M starts dictation", km)
            await b.eval("(async () => { await until(() => ta().value, 12000); document.querySelector('.mic-btn').click(); })()")
            v = await b.eval("(async () => { await until(() => !document.querySelector('.dict-bar'), 10000); return ta().value; })()")
            check("the mic again inserts", v.startswith("How many houses"), v)

            # 4) a phone-width screen
            await b.cmd("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
            await b.goto(base + "/megh-chat", wait=3)
            await b.eval("(async () => !!(await until(() => document.querySelector('.mic-btn') && ta(), 15000)))()")
            await b.eval("typeIn('', 0)")
            await b.eval("document.querySelector('.mic-btn').click()")
            fits = await b.eval("(async () => { await until(() => document.querySelector('.dict-bar.listening'), 8000); const c = document.querySelector('.composer').getBoundingClientRect(); const d = document.querySelector('.dict-done').getBoundingClientRect(); return c.right <= 391 && d.right <= c.right && document.documentElement.scrollWidth <= 391; })()")
            check("390 px: the bar and its buttons fit", fits)
            await b.shot(str(SHOTS / "03_phone.png"))
            await b.eval("document.querySelector('.dict-cancel').click()")
            errs = [e for e in b.events if e[0] == "exception"]
            check("no page errors", not errs, errs)
    finally:
        srv.should_exit = True
    n = sum(ok for _, ok in RESULTS)
    print(f"\n{n}/{len(RESULTS)} passed · screenshots in {SHOTS}")
    return 0 if n == len(RESULTS) else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(asyncio.run(main()))

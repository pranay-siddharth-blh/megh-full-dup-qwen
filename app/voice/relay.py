"""Full duplex: the chat page <-> /ws/voice <-> Gemini Live (2026-11-02).

    page  --hello {token}, then PCM16 16 kHz frames + JSON-->  /ws/voice  --BidiGenerateContent-->  Gemini Live
    page  <--PCM16 24 kHz frames + JSON events--------------   /ws/voice  <--audio, transcripts, tool calls--

The key never leaves the server. Gemini has ONE function, ask_megh. The relay
does not run it: it hands the call to the page (`tool_call`), the page sends the
officer's own words down the unchanged chat path (POST /api/query/stream, the
same request a typed question makes: login, ownership, caches, conversation
layer, LangGraph pipeline, audit, history) and returns the checked answer
(`tool_result`), which the relay gives back to Gemini to read aloud. So the
pipeline, its routing, its clarification pauses and its numeric-faithfulness
checks are exactly the typed ones; the voice adds ears and a mouth.

What is carried over from Mitra's relay (D:/Sakala POC/mitra/server/live.py):
  * Gemini ends the tool-call turn before it speaks the answer in the next one; the turn is held open (tool_wait).
  * The same call twice in one turn is answered from the first result (the model sometimes repeats itself).
  * If the model goes quiet 4 s after a result, it is nudged once per turn to read it.
  * Every number it says is checked against the answers it was given (speech_guard); deviations are logged and,
    with VOICE_BLOCK_UNSOURCED on (default, 14 Nov 2026), the sentence that holds one is cut and replaced.
  * One immediate retry of connect + setup; a network failure locks the voice out 15 s, a refusal 120 s,
    and the page falls back to the dictation mic meanwhile.
Logs carry counts and timings only, never the officer's words.
"""
from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
import time
from dataclasses import dataclass

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.voice import prompt, speech_guard
from app.voice import settings as voice_settings
from app.voice.board import router as _board_router

logger = logging.getLogger("megh.voice")
router = APIRouter()
# the Secretary's voice desk board (D-105): read-only figures beside the voice, never through the pipeline
router.include_router(_board_router)

IN_RATE, OUT_RATE = 16000, 24000
NUDGE_AFTER_S = 4.0
# the largest message the page may send (2026-11-14, guardrail): an audio frame is 20-100 ms (0.6-3.2 KB); 2 s of
# 16 kHz PCM16 is 64 KB. Anything bigger is dropped unread (a runaway or hostile client cannot push megabytes upstream)
MAX_FRAME_BYTES = 64_000
STATS = {"non_english_dropped": 0, "coalesced": 0, "repeats_held": 0, "unprompted_dropped": 0, "rereads_dropped": 0, "sessions": 0, "active": 0, "refused": 0, "audio_in_s": 0.0, "audio_out_s": 0.0, "tool_calls": 0,
         "tool_timeouts": 0, "nudges": 0, "deviations": 0, "blocked": 0, "oversize_dropped": 0, "errors": 0,
         "last_error": ""}
_ACTIVE: dict = {}                 # user key -> VoiceSession (one live session per officer on this worker)
# the sovereign engine's voices the page may choose (2026-11-12): a = Indian woman (default), b = Indian woman (bright),
# c = Indian woman (mature), d / e = reserved (Indian man, a second accent). Unknown keys are ignored.
SOVEREIGN_VOICES = ("a", "b", "c", "d", "e")
_LOCK = {"until": 0.0}


@dataclass
class Officer:
    key: str
    username: str
    name: str


async def identify(token: str) -> "Officer | None":
    """The same check current_scope makes for a Bearer token: a valid JWT for an active user."""
    from app import appdb, security
    if not token:
        return None
    try:
        claims = security.decode_token(token)
        rec = await appdb.get_user(int(claims["sub"]))
    except Exception:  # noqa: BLE001 — any failure is "not signed in"
        return None
    if not rec or not rec.get("is_active"):
        return None
    return Officer(key=str(rec["user_id"]), username=str(rec.get("username") or ""), name=str(rec.get("name") or ""))


def not_english(text: str) -> bool:
    """True when the text holds letters of a script other than Latin (Devanagari, Bengali, any other): the voice
    speaks English only. Digits, punctuation and symbols such as the rupee sign are fine. No regex."""
    return any(ch.isalpha() and ord(ch) > 0x24F for ch in text or "")


def setup_msg(cfg, officer: Officer) -> dict:
    return {"setup": {
        "model": f"models/{cfg.model}",
        "generationConfig": {"responseModalities": ["AUDIO"], "temperature": 0.3,
                             "speechConfig": {"languageCode": "en-IN",          # English only, whatever is spoken to it (user, 2026-11-03)
                                              "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": cfg.voice}}}},
        "systemInstruction": {"parts": [{"text": prompt.instruction(officer.name)}]},
        "tools": [{"functionDeclarations": [prompt.ASK_MEGH]}],
        "realtimeInputConfig": {"automaticActivityDetection": {"silenceDurationMs": 800, "prefixPaddingMs": 200}},
        "inputAudioTranscription": {}, "outputAudioTranscription": {},
    }}


REREAD_PROBE = 40                   # characters of the last answer compared with the start of a new turn's speech
REREAD_MIN = 10                     # ... and at least this many must agree before a turn counts as a re-read
REPEAT_ASKED = ("repeat", "again", "say that", "once more", "pardon", "didnt catch", "did not catch", "didnt hear",
                "did not hear", "come again")   # the officer's words asking to hear the last answer: its re-read is wanted


def _letters(text: str) -> str:
    """Lower case, letters and digits only: the shape compared when a turn may be the last answer read again."""
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _norm(q: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in (q or "")).split())


def _redact(text: str, cfg) -> str:
    """An error text as it may be logged or kept in STATS: the Gemini key never (the upstream URL carries it as
    ?key=...; an exception that quotes the URL would put it in the log). No regex."""
    out = str(text or "")
    key = getattr(cfg, "api_key", "") or ""
    if key:
        out = out.replace(key, "***")
    k = out.find("key=")
    while k >= 0:
        e = k + 4
        while e < len(out) and out[e] not in "&' \"\n>":
            e += 1
        out = out[:k + 4] + "***" + out[e:]
        k = out.find("key=", k + 7)
    return out


async def _open_upstream(cfg, officer: Officer):
    """Connect and set up; one immediate retry. Returns (socket, None) or (None, lockout seconds)."""
    last = None
    for attempt in (1, 2):
        up = None
        try:
            up = await websockets.connect(cfg.url(), max_size=None, open_timeout=10, ping_interval=20)
            await up.send(json.dumps(setup_msg(cfg, officer)))
            first = json.loads(await asyncio.wait_for(up.recv(), 12))
            if "setupComplete" in first:
                return up, None
            last = ("refused", f"unexpected setup reply: {str(first)[:160]}")
        except (OSError, asyncio.TimeoutError, TimeoutError) as e:
            last = ("network", f"{type(e).__name__}: {str(e)[:160]}")
        except websockets.exceptions.InvalidStatus as e:
            last = ("refused", f"status {getattr(e.response, 'status_code', '?')}")
        except websockets.exceptions.ConnectionClosed as e:
            code = getattr(e.rcvd, "code", 0) if getattr(e, "rcvd", None) else 0
            last = ("refused" if code in (1007, 1008, 1011) else "network", f"closed {code}")
        except Exception as e:  # noqa: BLE001
            last = ("network", f"{type(e).__name__}: {str(e)[:160]}")
        if up is not None:
            try:
                await up.close()
            except Exception:  # noqa: BLE001
                pass
        if last and last[0] == "refused":
            break                                   # a refusal (quota, model, key) will not change on a retry
    STATS["errors"] += 1
    STATS["last_error"] = _redact(last[1], cfg) if last else "unknown"
    return None, (120.0 if last and last[0] == "refused" else 15.0)


# /ws/voice connections per address in the last minute (VOICE_HELLO_PER_MINUTE): {address: [monotonic times]}
_HELLOS: dict = {}


def _over_hello_limit(address: str, per_minute: int, now: float) -> bool:
    """True when `address` has already opened `per_minute` connections in the last 60 s; else the attempt is counted.
    0 = no limit. Addresses with nothing recent are dropped, so the table stays small."""
    if per_minute <= 0:
        return False
    for a in [a for a, ts in _HELLOS.items() if not ts or now - ts[-1] > 60]:
        del _HELLOS[a]
    recent = [t for t in _HELLOS.get(address, []) if now - t <= 60]
    if len(recent) >= per_minute:
        _HELLOS[address] = recent
        return True
    _HELLOS[address] = recent + [now]
    return False


@router.websocket("/ws/voice")
async def ws_voice(ws: WebSocket):
    await ws.accept()
    cfg = voice_settings.load()
    address = ws.client.host if ws.client else "?"
    if _over_hello_limit(address, cfg.hello_per_minute, time.monotonic()):
        STATS["refused"] += 1
        await _close(ws, {"type": "error", "reason": "rate"}, 4429)
        return
    try:
        hello = json.loads(await asyncio.wait_for(ws.receive_text(), 10))
    except Exception:  # noqa: BLE001
        await _close(ws, {"type": "error", "reason": "no hello"}, 4400)
        return
    if not isinstance(hello, dict) or hello.get("type") != "hello":
        await _close(ws, {"type": "error", "reason": "no hello"}, 4400)
        return
    officer = await identify(str(hello.get("token") or ""))
    if officer is None:
        STATS["refused"] += 1
        await _close(ws, {"type": "error", "reason": "auth"}, 4401)
        return
    if not cfg.enabled:
        await _close(ws, {"type": "fallback", "reason": "voice off"}, 1000)
        return
    if time.monotonic() < _LOCK["until"]:
        await _close(ws, {"type": "fallback", "reason": "live voice unavailable"}, 1000)
        return
    # the officer's voice choice (2026-11-12, the voice toggle): only with the sovereign engine (VOICE_LIVE_URL), whose
    # voices are keys of its own voice map; Gemini's prebuilt voice names are never taken from the page
    choice = str(hello.get("voice") or "").strip().lower()
    if cfg.live_url and choice in SOVEREIGN_VOICES:
        cfg = dataclasses.replace(cfg, voice=choice)
    old = _ACTIVE.get(officer.key)
    if old is not None:
        await old.close("replaced")                 # a reload or a second tab: the newest session wins
    if len(_ACTIVE) >= cfg.max_sessions:
        await _close(ws, {"type": "fallback", "reason": "busy"}, 1000)
        return
    up, lockout = await _open_upstream(cfg, officer)
    if up is None:
        _LOCK["until"] = time.monotonic() + (lockout or 15.0)
        logger.warning("voice: live engine unavailable, locked out %ss (%s)", lockout, STATS["last_error"])
        await _close(ws, {"type": "fallback", "reason": "live voice unavailable"}, 1000)
        return
    sess = VoiceSession(ws, up, cfg, officer)
    _ACTIVE[officer.key] = sess
    STATS["sessions"] += 1
    STATS["active"] = len(_ACTIVE)
    try:
        await sess.run()
    finally:
        if _ACTIVE.get(officer.key) is sess:
            del _ACTIVE[officer.key]
        STATS["active"] = len(_ACTIVE)


async def _close(ws: WebSocket, msg: dict, code: int) -> None:
    try:
        await ws.send_json(msg)
        await ws.close(code)
    except Exception:  # noqa: BLE001
        pass


class VoiceSession:
    def __init__(self, ws: WebSocket, up, cfg, officer: Officer):
        self.ws, self.up, self.cfg, self.officer = ws, up, cfg, officer
        self.t0 = time.monotonic()
        self.facts: set = set()
        self.closing = ""
        self.batch: dict | None = None          # the toolCall being answered: {"need": set(ids), "resps": {id: response}}
        self.waiting: dict = {}                 # question key -> [call ids] waiting for the page's answer
        self.timeouts: dict = {}                # question key -> timeout task
        self.turn = self._new_turn()
        self.last_answer = ""                   # the last answer sent to the model (a toolResponse speak or a read), _letters

    @staticmethod
    def _new_turn() -> dict:
        return {"user": "", "said": "", "called": 0, "tool_wait": False, "resp_at": 0.0, "last_out": 0.0,
                "nudged": False, "cache": {}, "t0": time.monotonic(), "first_audio": 0.0,
                "asked": "", "fresh": True, "read": False, "probe": "", "reread": False, "probed": False,
                # the unsourced-number block (VOICE_BLOCK_UNSOURCED): sentences checked and captioned so far, the
                # numbers that cut the turn (empty = not cut), the sentence it was cut at, the text a read asked for
                "checked": 0, "blocked": [], "block_at": -1, "read_text": ""}

    async def close(self, why: str) -> None:
        self.closing = why
        try:
            await self.ws.send_json({"type": "closed", "reason": why})
        except Exception:  # noqa: BLE001
            pass
        for s in (self.up, self.ws):
            try:
                await s.close()
            except Exception:  # noqa: BLE001
                pass

    async def send(self, msg: dict) -> None:
        try:
            await self.ws.send_json(msg)
        except Exception:  # noqa: BLE001 — the page went away; the browser loop ends the session
            pass

    async def up_text(self, text: str) -> None:
        await self.up.send(json.dumps({"clientContent": {"turns": [{"role": "user", "parts": [{"text": text}]}],
                                                         "turnComplete": True}}))

    async def run(self) -> None:
        await self.send({"type": "ready", "idle_seconds": self.cfg.idle_seconds})
        logger.info("voice: session open (user %s)", self.officer.key)
        a = asyncio.create_task(self.from_page())
        b = asyncio.create_task(self.from_gemini())
        tasks = {a, b}
        if self.cfg.max_session_minutes > 0:
            tasks.add(asyncio.create_task(self._time_limit(self.cfg.max_session_minutes * 60.0)))
        try:
            done, rest = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosedOK)):
                    STATS["errors"] += 1
                    STATS["last_error"] = _redact(f"{type(exc).__name__}: {str(exc)[:160]}", self.cfg)
                    logger.warning("voice: session ended by an error (user %s): %s", self.officer.key, STATS["last_error"])
                    closed = isinstance(exc, websockets.exceptions.ConnectionClosedError)
                    code = exc.rcvd.code if closed and exc.rcvd else 0
                    if closed and code != 1008:
                        # the model's own internal error (1011) or a dropped connection, mid-session: transient. The page
                        # reconnects at once; a refused reconnect falls back through the normal path
                        self.closing = "upstream error, reconnecting"
                        await self.send({"type": "goaway"})
                    elif not self.closing:
                        if code == 1008:                     # a policy refusal: it will not change on a retry
                            _LOCK["until"] = time.monotonic() + 120.0
                        await self.send({"type": "fallback", "reason": "live session ended"})
            for t in rest:
                t.cancel()
        finally:
            for t in self.timeouts.values():
                t.cancel()
            for s in (self.up, self.ws):
                try:
                    await s.close()
                except Exception:  # noqa: BLE001
                    pass
            logger.info("voice: session closed (user %s, %.0f s, %s)", self.officer.key,
                        time.monotonic() - self.t0, self.closing or "ended")

    async def _time_limit(self, seconds: float) -> None:
        """VOICE_MAX_SESSION_MINUTES: the session ends here even if the browser never goes idle (cost bound)."""
        await asyncio.sleep(seconds)
        logger.info("voice: session time limit reached (user %s, %.0f s)", self.officer.key, seconds)
        await self.close("session time limit")

    # ── page -> Gemini ──────────────────────────────────────────────────────
    async def from_page(self) -> None:
        while True:
            msg = await self.ws.receive()
            if msg.get("type") == "websocket.disconnect":
                self.closing = self.closing or "page went away"
                return
            if len(msg.get("bytes") or b"") > MAX_FRAME_BYTES or len(msg.get("text") or "") > MAX_FRAME_BYTES:
                STATS["oversize_dropped"] += 1
                continue
            if msg.get("bytes"):
                b = msg["bytes"]
                STATS["audio_in_s"] += len(b) / 2 / IN_RATE
                await self.up.send(json.dumps({"realtimeInput": {"audio": {
                    "data": base64.b64encode(b).decode(), "mimeType": f"audio/pcm;rate={IN_RATE}"}}}))
                continue
            if not msg.get("text"):
                continue
            try:
                m = json.loads(msg["text"])
            except ValueError:
                continue
            t = m.get("type")
            if t == "text":                         # typed into the live session (and the test hook)
                text = str(m.get("text") or "")[:2000]
                if text.startswith("[voice] "):     # test hook: text standing in for speech
                    if self.cfg.live_url:
                        self.turn["fresh"] = True
                        await self.up_text(text)    # the test server answers it with an inputTranscription
                        continue
                    text = text[len("[voice] "):]   # the real model: these are the words heard
                self.turn["user"] = text
                self.turn["fresh"] = True
                await self.up_text(text)
            elif t == "read":                       # an answer the page got another way (a typed question, a chip)
                text = speech_guard.scrub(str(m.get("text") or ""))[:2500]
                if text:
                    speech_guard.facts_from(text, self.facts)
                    self.turn["user"] = ""              # a read is not the officer's turn: its end must not re-ask anything
                    self.turn["fresh"] = True           # ... but it is speech the page asked for: forwarded
                    self.turn["read"] = True
                    self.turn["read_text"] = text
                    self.last_answer = _letters(text)
                    await self.up_text(prompt.READ_LINE + text)
            elif t == "tool_result":
                await self.on_tool_result(str(m.get("id") or ""), m.get("result") or {})
            elif t == "audio_end":
                await self.up.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))
            elif t == "bye":
                self.closing = "bye"
                return

    # ── Gemini -> page ──────────────────────────────────────────────────────
    async def from_gemini(self) -> None:
        try:
            await self._from_gemini()
        finally:
            if not self.closing:                     # the upstream ended the session cleanly: the page reconnects at once
                self.closing = "upstream closed"
                await self.send({"type": "goaway"})

    async def _from_gemini(self) -> None:
        async for raw in self.up:
            m = json.loads(raw)
            if "toolCall" in m:
                await self.on_tool_call(m["toolCall"].get("functionCalls") or [])
                continue
            if "toolCallCancellation" in m:
                ids = list((m["toolCallCancellation"] or {}).get("ids") or [])
                await self.on_cancel(ids)
                continue
            if "goAway" in m:
                await self.send({"type": "goaway"})
            if m.get("voiceActivity"):
                state = str(m["voiceActivity"].get("type", ""))
                if "START" in state:
                    self.turn["fresh"] = True       # the officer spoke again: a call after this is a new question
                await self.send({"type": "vad", "state": state})
            sc = m.get("serverContent") or {}
            self._check_reread((sc.get("outputTranscription") or {}).get("text") or "")
            # the answer was read and the officer has said nothing new: anything the model says now is a second answer
            # (measured on the real voice 2026-11-03: an answer read again after it finished). It is not forwarded.
            hush = bool(self.turn.get("spoken")) and not self.turn["fresh"]
            reread = bool(self.turn["reread"])
            out_tx = (sc.get("outputTranscription") or {}).get("text") or ""
            if out_tx and not_english(out_tx) and not self.turn.get("non_english"):
                # English only (user, 2026-11-03): checked BEFORE this message's audio goes out; the rest of the turn
                # is dropped and the voice says, in English, that it speaks English only
                self.turn["non_english"] = True
                STATS["non_english_dropped"] += 1
                logger.warning("voice: non-English speech dropped (user %s)", self.officer.key)
                asyncio.create_task(self.up_text(prompt.NOT_ENGLISH_LINE))
            for p in (sc.get("modelTurn") or {}).get("parts", []):
                d = p.get("inlineData")
                if d and d.get("data") and self.turn.get("non_english"):
                    continue
                if d and d.get("data") and hush:
                    STATS["unprompted_dropped"] += 1
                    continue
                if d and d.get("data") and reread:
                    continue
                if d and d.get("data") and self.turn["blocked"]:
                    continue                        # cut at a sentence with an unsourced number: the rest is not played
                if d and d.get("data"):
                    pcm = base64.b64decode(d["data"])
                    now = time.monotonic()
                    self.turn["last_out"] = now
                    if not self.turn["first_audio"]:
                        self.turn["first_audio"] = now
                    STATS["audio_out_s"] += len(pcm) / 2 / OUT_RATE
                    try:
                        await self.ws.send_bytes(pcm)
                    except Exception:  # noqa: BLE001
                        return
            tx = (sc.get("inputTranscription") or {}).get("text")
            if tx:
                self.turn["user"] += tx
                if self.turn.get("spoken"):
                    self.turn["fresh"] = True       # words after the last answer was read: a new question
                await self.send({"type": "in", "text": tx})
            tx = (sc.get("outputTranscription") or {}).get("text")
            if tx and not_english(tx) and not self.turn.get("non_english"):
                # English only (user, 2026-11-03): the rest of this turn is dropped and the voice says, in English,
                # that it speaks English only. The first instant of audio may already have played.
                self.turn["non_english"] = True
                STATS["non_english_dropped"] += 1
                logger.warning("voice: non-English speech dropped (user %s)", self.officer.key)
                asyncio.create_task(self.up_text(prompt.NOT_ENGLISH_LINE))
            if tx and self.turn.get("non_english"):
                tx = ""
            if tx:                                   # Gemini's placeholders for silence are not speech (2026-11-03)
                tx = tx.replace("<no speech>", "").replace("{pause}", "")
                if not tx.strip():
                    tx = ""
            if tx and (hush or reread):
                tx = ""
            if tx:
                self.turn["said"] += tx
                self.turn["last_out"] = time.monotonic()
                if self.cfg.block_unsourced:
                    await self._guard_scan(final=False)     # captions go out a sentence at a time, each one checked
                else:
                    await self.send({"type": "out", "text": speech_guard.scrub(tx)})
            if sc.get("interrupted"):
                if self.turn.get("non_english"):    # the English apology interrupted the dropped turn: start clean
                    self.turn = self._new_turn()
                self.turn["fresh"] = True
                await self.send({"type": "interrupted"})
            if sc.get("turnComplete"):
                await self.on_turn_complete()

    def _check_reread(self, tx: str) -> None:
        """The officer said something new, the model has called nothing yet in this turn and no read was asked for,
        and its speech starts like the last answer: it is reading that answer again (measured on the real voice
        2026-11-03, A5->A6, B5->B6, B16->B17). From here the turn's audio and words are not forwarded and its end is
        not a turn for the page; a call made after it is the new question and its answer is forwarded as usual."""
        tn = self.turn
        if not tx or tn["probed"] or tn["reread"]:
            return
        if not self.last_answer or not tn["fresh"] or tn["called"] or tn["read"] or self.waiting:
            tn["probed"] = True
            return
        heard = " ".join(tn["user"].lower().replace("'", "").split())
        if any(w in heard for w in REPEAT_ASKED):
            tn["probed"] = True                     # the officer asked to hear it again: the re-read is wanted
            return
        tn["probe"] += _letters(tx)
        probe, last = tn["probe"], self.last_answer
        n = min(len(probe), len(last), REREAD_PROBE)
        if n < REREAD_MIN and n < len(last):
            return                                  # too short to tell yet: keep looking
        tn["probed"] = True
        if probe[:n] == last[:n]:
            tn["reread"] = True
            tn["said"], tn["first_audio"], tn["checked"] = "", 0.0, 0
            STATS["rereads_dropped"] += 1
            logger.info("voice: the last answer was being read again; not forwarded (user %s)", self.officer.key)

    async def on_turn_complete(self) -> None:
        tn = self.turn
        if tn.get("non_english"):                   # a dropped non-English turn: not a turn for the page; the English
            self.turn = self._new_turn()            # apology that follows starts clean
            return
        if tn["reread"] and not tn["called"]:
            # a turn that only re-read the last answer: not a turn for the page. The officer's words stay, so the call
            # that answers them (next) is the new question
            self.turn = self._new_turn()
            self.turn.update(user=tn["user"], probed=True)
            return
        if tn.get("spoken") and not tn["fresh"]:
            return                                  # a turn of unprompted speech (dropped above): not a turn for the page
        if tn["tool_wait"] and not tn["said"].strip():
            tn["tool_wait"] = False                 # the tool-call turn ended; the answer comes in the next one
            if not self.waiting:
                return
            return
        if self.waiting:
            return                                  # a question is still being answered by the page
        if self.cfg.block_unsourced and tn["said"].strip():
            await self._guard_scan(final=True)      # the last sentence too (its audio may still be queued on the page)
        said = speech_guard.scrub(tn["said"].strip())
        bad = speech_guard.deviations(said, self.facts) if said else []
        shown = said
        if tn["blocked"]:
            bad += [b for b in tn["blocked"] if b not in bad]
            # what the screen keeps of this turn: the sentences heard, the cut one replaced (never empty)
            upto = speech_guard.sentences(tn["said"])[:tn["block_at"] + 1]
            shown = speech_guard.guard_line(speech_guard.scrub(" ".join(upto)), self.facts)[0] or speech_guard.SAFE_LINE
        if bad:
            STATS["deviations"] += 1
            logger.warning("voice: %d number(s) said without a source (user %s): %s", len(bad), self.officer.key,
                           ", ".join(bad[:6]))
        # `deviations` keeps its meaning for the page: a called turn's checked answer is re-read ("To be exact"), an
        # uncalled one goes through the pipeline. `blocked` says the relay already cut the unsourced sentence.
        await self.send({"type": "turn_complete", "user": tn["user"].strip(), "said": shown, "called": tn["called"],
                         "deviations": bad, "blocked": bool(tn["blocked"]),
                         "first_audio_ms": round((tn["first_audio"] - tn["t0"]) * 1000) if tn["first_audio"] else None})
        self.turn = self._new_turn()
        if tn["asked"] and said and not tn["fresh"]:
            self.turn.update(asked=tn["asked"], fresh=False, spoken=True)
        if tn["blocked"] and tn["read"] and not tn["called"] and tn["read_text"] != speech_guard.SAFE_LINE:
            # a read the page asked for (a greeting, a typed answer, a "To be exact" correction) was misread with a
            # number of the model's own: nothing on the page will follow it, so the relay ends it with the safe line
            # (once: the safe line itself holds no number)
            self.turn.update(user="", fresh=True, read=True, read_text=speech_guard.SAFE_LINE)
            await self.up_text(prompt.READ_LINE + speech_guard.SAFE_LINE)

    async def _guard_scan(self, final: bool) -> None:
        """VOICE_BLOCK_UNSOURCED: check each finished sentence of what the voice is saying against the answers of this
        session. A clean sentence goes to the page as a caption; the first sentence with an unsourced number cuts the
        turn: the page stops the audio it has queued (the transcript runs well ahead of the audio, so this is
        normally before that sentence is heard), the rest of the turn's audio and captions are dropped, and
        on_turn_complete replaces it. `final`: the turn is over, the last sentence is finished too."""
        tn = self.turn
        if tn["blocked"]:
            return
        sents = speech_guard.sentences(tn["said"])
        done = sents if final else sents[:-1]
        while tn["checked"] < len(done):
            s = done[tn["checked"]]
            bad = speech_guard.deviations(s, self.facts)
            if bad:
                tn["blocked"], tn["block_at"] = bad, tn["checked"]
                STATS["blocked"] += 1
                logger.warning("voice: a sentence with %d unsourced number(s) was cut (user %s)", len(bad),
                               self.officer.key)
                await self.send({"type": "interrupted", "guard": "unsourced"})
                return
            await self.send({"type": "out", "text": (" " if tn["checked"] else "") + speech_guard.scrub(s)})
            tn["checked"] += 1

    async def on_tool_call(self, calls: list) -> None:
        tn = self.turn
        tn["tool_wait"] = True
        tn["called"] += len(calls)
        STATS["tool_calls"] += len(calls)
        batch = self.batch if self.batch is not None else {"need": set(), "resps": {}}
        self.batch = batch                          # a second toolCall before the first was answered joins it
        for fc in calls:
            cid = str(fc.get("id") or "")
            name = fc.get("name") or ""
            args = fc.get("args") or {}
            batch["need"].add(cid)
            if name != "ask_megh":
                batch["resps"][cid] = {"id": cid, "name": name, "response": {
                    "speak": "I can only answer through Megh One AI.", "kind": "error", "read_exactly": False}}
                continue
            question = str(args.get("question") or "")
            key = _norm(question) or _norm(tn["user"])
            if tn["asked"] and not tn["fresh"]:
                # the model asked again, reworded, without the officer saying anything new: the same question.
                # Answered from the first call, so the page shows one card and the voice reads one answer
                STATS["coalesced"] += 1
                key = tn["asked"]
                if tn.get("spoken"):                # already read out in an earlier turn: never a second answer
                    STATS["repeats_held"] += 1
                    batch["resps"][cid] = {"id": cid, "name": name, "response": {
                        "speak": "", "kind": "already_answered", "read_exactly": False,
                        "note": "This question was already answered aloud. Say nothing more; wait for the officer."}}
                    continue
            else:
                tn["asked"], tn["fresh"], tn["spoken"] = key, False, False   # a new question: its answer will be spoken
                if tn["reread"]:                    # the re-read of the last answer before this call: over, not forwarded
                    tn["reread"], tn["said"], tn["first_audio"], tn["checked"] = False, "", 0.0, 0
            if key in tn["cache"]:                  # the same call again in this turn: the first answer
                batch["resps"][cid] = {"id": cid, "name": name, "response": tn["cache"][key]}
                continue
            if key in self.waiting:
                self.waiting[key].append(cid)
                continue
            self.waiting[key] = [cid]
            await self.send({"type": "tool_call", "id": cid, "key": key, "question": question,
                             "heard": tn["user"].strip()})
            self.timeouts[key] = asyncio.create_task(self._tool_timeout(key))
        await self._maybe_respond()

    async def _tool_timeout(self, key: str) -> None:
        await asyncio.sleep(self.cfg.tool_timeout)
        if key in self.waiting:
            STATS["tool_timeouts"] += 1
            await self._answer(key, {"speak": "The answer is taking longer than usual. It will appear on your screen "
                                              "when it is ready.", "kind": "pending", "read_exactly": True})

    async def on_tool_result(self, cid: str, result: dict) -> None:
        key = next((k for k, ids in self.waiting.items() if cid in ids), None)
        if key is None:
            return                                  # cancelled, timed out or unknown
        await self._answer(key, result)

    async def _answer(self, key: str, result: dict) -> None:
        speak = speech_guard.scrub(str(result.get("speak") or ""))[:2500]
        response = {"speak": speak or "There is no answer to read.",
                    "kind": str(result.get("kind") or "answer")[:20],
                    "read_exactly": bool(result.get("read_exactly", True)),
                    "on_screen": bool(result.get("on_screen", True))}
        speech_guard.facts_from(speak, self.facts)
        if speak:
            self.last_answer = _letters(speak)
        self.turn["cache"][key] = response
        ids = self.waiting.pop(key, [])
        t = self.timeouts.pop(key, None)
        if t and t is not asyncio.current_task():
            t.cancel()
        if self.batch is not None:
            for cid in ids:
                if cid in self.batch["need"]:
                    self.batch["resps"][cid] = {"id": cid, "name": "ask_megh", "response": response}
        await self._maybe_respond()

    async def _maybe_respond(self) -> None:
        b = self.batch
        if b is None or not b["need"] or set(b["resps"]) < b["need"]:
            return
        self.batch = None
        await self.up.send(json.dumps({"toolResponse": {"functionResponses": [b["resps"][i] for i in sorted(b["need"])]}}))
        at = time.monotonic()
        self.turn["resp_at"] = at
        asyncio.create_task(self._speak_watch(at))

    async def on_cancel(self, ids: list) -> None:
        """Gemini dropped calls (the officer talked over the wait): the page stops that answer."""
        ids = [str(i) for i in ids]
        for key, waiting in list(self.waiting.items()):
            left = [i for i in waiting if i not in ids]
            if left:
                self.waiting[key] = left
            else:
                del self.waiting[key]
                t = self.timeouts.pop(key, None)
                if t:
                    t.cancel()
                await self.send({"type": "tool_cancel", "key": key})
        if self.batch is not None:
            self.batch["need"] -= set(ids)
            if not self.batch["need"]:
                self.batch = None

    async def _speak_watch(self, at: float) -> None:
        await asyncio.sleep(NUDGE_AFTER_S)
        tn = self.turn
        if tn["resp_at"] != at or tn["last_out"] >= at or tn["nudged"] or self.closing:
            return
        tn["nudged"] = True
        STATS["nudges"] += 1
        try:
            await self.up_text(prompt.NUDGE_LINE)
        except Exception:  # noqa: BLE001
            pass

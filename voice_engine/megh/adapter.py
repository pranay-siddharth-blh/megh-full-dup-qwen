"""MEGH adapter: the sovereign voice engine for Megh One AI (Meghalaya), behind its UNCHANGED live-voice relay.

Megh One AI's relay (D:/MEGH-LANG/.../app/voice/relay.py, read-only to us) talks to "Gemini Live" over one WebSocket;
when VOICE_LIVE_URL is set it connects there instead and sends no key. This server speaks the subset of the Gemini Live
protocol that relay uses, so the officer's page, the relay, the pipeline ("the brain") and all of Megh's tests stay
exactly as they are; only the ears and the mouth change, and no audio leaves the government network (Megh KI-660).

  relay -> us : {"setup":...}  realtimeInput.audio (16 kHz PCM16, base64)  clientContent (text turns: READ_LINE / NUDGE /
                NOT_ENGLISH lines, "[voice] ..." test turns, typed text)  toolResponse  realtimeInput.audioStreamEnd
  us -> relay : setupComplete  serverContent.inputTranscription / outputTranscription / modelTurn (24 kHz PCM16) /
                interrupted / turnComplete  toolCall (ask_megh)  toolCallCancellation  voiceActivity

EARS (dual, as in Mitra): the Kyutai streaming recogniser keeps the TIMING (speech onset, end of turn with its pause
probability, barge-in); the WORDS of every finished turn come from the gateway's qwen3-asr, primed with Meghalaya's
vocabulary, asked at the first 0.3 s of silence and reused when the turn ends there.
MOUTH: the fact voice (sidevoice/, qwen3-tts, Mitra's voice A, Indian-system numbers) says the CHECKED answer the page
returns, word for word; a holding phrase covers a slow pipeline (cross-scheme answers take 10-40 s).
The adapter decides no fact: every question goes to ask_megh; it answers on its own only a greeting, thanks, goodbye,
"can you hear me", "who are you" (Megh's fixed identity line) and "say that again" (the last answer again).

Run: .venv\\Scripts\\python megh\\adapter.py [port=8170]     (keys from the environment / ops/keys.py; never printed)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ops"))

try:
    import keys as _keys                           # gateway URL / ASR key (names only; values never printed)
    for _k, _v in _keys.env().items():
        os.environ.setdefault(_k, _v)
except Exception:  # noqa: BLE001
    pass
_menv = ROOT / "run" / "models.env"
if _menv.exists():
    for _line in _menv.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.lstrip().startswith("#"):
            _a, _b = _line.split("=", 1)
            os.environ.setdefault(_a.strip(), _b.strip())

from websockets.asyncio.server import serve  # noqa: E402
from websockets.datastructures import Headers  # noqa: E402
from websockets.http11 import Response  # noqa: E402

from fdx import relisten  # noqa: E402
from fdx.audio import f32_to_pcm16, pcm16_to_f32, rms, up16to24  # noqa: E402
from fdx.protocol.kstt import STTClient  # noqa: E402
from fdx.protocol.moshi import CoreClient, core_url  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixed_lines as megh_lines  # noqa: E402   (megh/fixed_lines.py, warmed by the fact voice)
import natural  # noqa: E402
import places  # noqa: E402
import domain as _domain  # noqa: E402   (megh/domain: the voice layer's domain pack, from Megh's registries)   (megh/places.py: place names from Megh's own resolvers)
import shaper  # noqa: E402   (megh/shaper.py: what was SAID -> the question the pipeline answers best)   (megh/natural.py: the checked answer, said the way a person would)

PORT = int(next((a for a in sys.argv[1:] if a.isdigit()), os.environ.get("MEGH_ADAPTER_PORT", "8170")))
VOICE_URL = os.environ.get("MEGH_VOICE_URL", "ws://127.0.0.1:8144/api/chat")      # the fact voice (sidevoice)
STT_URL = os.environ.get("FDX_STT_URL", "")
STT_KEY = os.environ.get("FDX_STT_API_KEY") or "public_token"
RATE_IN, RATE = 16000, 24000

# the turn
ONSET_MS = 160            # voice this long starts a turn
END_SILENCE_MS = 700      # silence that ends a turn
SHORT_TURN_S = 0.9        # a turn with less voice than this (a short reply, "Ri Bhoi") ...
SHORT_SILENCE_MS = 1000   # ... needs this much silence (it is often the first half of a longer question)
SEMANTIC_MIN_MS = 300     # the recogniser's pause probability may end a turn after this much silence
EARLY_ASR_MS = 300        # the words are asked of qwen3-asr at this much silence
BARGE_MS = 200            # voice over her answer this long cuts her
CONTINUE_S = 1.5          # speech resumed this soon after a turn ended, before its answer came: the same question
ASR_WAIT_S = 2.5
HANGING_SILENCE_MS = 1200  # a sentence left hanging waits this long before its turn ends (12 Nov: a year after "in")
HANGING_WORDS = {"in", "for", "of", "the", "a", "an", "to", "and", "or", "by", "with", "from", "at", "on", "under",
                 "per", "between", "than", "during", "since", "about", "into", "as", "my", "our", "is", "are", "was"}
VOICE_MIN_RMS = 0.010     # was 0.015: a quiet year at the end of a sentence was cut off (11 Nov: "2023-24" -> "2022-23")
SOFT_MIN_RMS = 0.005      # quieter than voice but above the room: still part of the sentence for the recogniser
LEAD_FRAMES = int(os.environ.get("FDX_MEGH_LEAD_FRAMES", "5"))   # audio sent up to 400 ms ahead (Gemini-like bursts)
ASR_WAIT_ALONE_S = 7.0    # the timing ear is off or heard nothing: wait longer for qwen3-asr rather than lose the turn
LEAD_AFTER_S = 1.8        # no answer yet: "One moment, sir."
LEAD_AGAIN_S = (9.0, 20.0, 32.0)
LEADS = ["One moment, sir.", "Still working on it, sir.", "Almost there, sir.", "Just a little longer, sir."]

IDENTITY = ("I'm the voice of Megh One AI, an AI assistant for the Government of Meghalaya's scheme data. "
            "I'm not a person and not an officer.")                       # Megh's own line (app/voice/prompt.py)
READ_PREFIX = "(Read this to the officer now"
NUDGE_PREFIX = "(The answer has arrived"
NOT_ENGLISH_PREFIX = "(You spoke a language other than English"
CONTEXT_PREFIX = "(Conversation context for the voice engine"     # Megh relay prompt.CONTEXT_LINE (16 Nov 2026)
ASR_PROMPT = ("Meghalaya government scheme data. Schemes: MGNREGA, PMAY-G, Focus Plus, Focus Legacy, CM Elevate, "
              "CM Elevate Legacy. Districts: East Khasi Hills, West Khasi Hills, South West Khasi Hills, Eastern West "
              "Khasi Hills, Ri Bhoi, East Jaintia Hills, West Jaintia Hills, East Garo Hills, West Garo Hills, North Garo "
              "Hills, South Garo Hills, South West Garo Hills. Terms: person-days, job cards, beneficiaries, producer "
              "groups, disbursement, sanctioned, tranche, financial year 2023-24.")

_FILLER = re.compile(r"^\s*(?:(?:uh+|um+|umm+|er+|erm+|ah+|hmm+|mm+|okay so|ok so|so|well)[\s,.]+)+", re.I)
# 16 Nov 2026 (the voice audit): a greeting / thanks / goodbye is answered here only when NOTHING else is said with it
# ("hello, show me MGNREGA" used to match the old [\s\w]{0,20} tail and the question was never asked): every word
# after the opening must be one of SOCIAL_TAIL; anything else goes to Megh's pipeline like a typed message.
_GREET = re.compile(r"^(?:hi|hello|hey|hey there|good (?:morning|afternoon|evening)|namaste|namaskar|khublei)\b(?P<rest>.*)$", re.I)
_THANKS = re.compile(r"^(?:thanks|thank you|thank you very much|thanks a lot|great,? thanks|ok(?:ay)?,? thank you)\b(?P<rest>.*)$", re.I)
_BYE = re.compile(r"^(?:bye|goodbye|good bye|that'?s all|see you)\b(?P<rest>.*)$", re.I)
SOCIAL_TAIL = {"there", "sir", "madam", "megh", "everyone", "all", "again", "how", "are", "you", "doing", "good",
               "morning", "afternoon", "evening", "so", "much", "very", "a", "lot", "for", "the", "help", "that", "that's",
               "it", "thanks", "thank", "okay", "ok", "great", "bye", "later", "then", "now", "for", "today", "is",
               "all", "khublei", "ji", "and", "yes", "yeah", "too", "dear", "friend", "one"}
# a spoken "stop" (16 Nov 2026): acknowledged here at once (and the answer being prepared is dropped), never asked of
# the pipeline (which answered it like a question)
_STOP = re.compile(r"^(?:(?:ok(?:ay)?|please|megh|sir|no|just|yes|yeah|hey)[\s,]+)*(?:stop(?: it| that| talking| there| now)?|"
                   r"that'?s enough|that is enough|enough|be quiet|quiet|shut up|hold it|cancel(?: that| it)?|"
                   r"silence|pause)(?:[\s,]+(?:please|sir|now|megh|thanks|thank you))*[.!]*$", re.I)
NOISE_WORDS = {"um", "umm", "uh", "uhh", "hmm", "hm", "mm", "mmm", "ah", "ahh", "er", "erm", "oh", "huh", "eh"}
NOISE_MAX_VOICED_S = 0.8   # longer unheard speech is carried into the next turn as before, never taken for a noise
RESUME_WITHIN_S = 12.0      # a noise this soon after it cut an answer: the answer goes on from the sentence it cut
_HEAR = re.compile(r"^(?:can you hear me|are you there|hello\?|is this working|testing)\b", re.I)
_WHO = re.compile(r"\b(?:who are you|what are you|which (?:ai|model)|who (?:made|built|created) you|are you (?:a )?(?:human|person|robot|bot))\b", re.I)
_REPEAT = re.compile(r"^(?:(?:can you |could you |please )?(?:repeat|say) (?:that|it) again|repeat(?: that| it)?|pardon|come again|say again)\b", re.I)
_ORDINAL = {"first": 0, "1st": 0, "one": 0, "1": 0, "second": 1, "2nd": 1, "two": 1, "2": 1, "third": 2, "3rd": 2,
            "three": 2, "3": 2, "fourth": 3, "4th": 3, "four": 3, "4": 3, "fifth": 4, "5th": 4, "five": 4, "5": 4,
            "sixth": 5, "6th": 5, "six": 5, "6": 5}
_PICK = re.compile(r"^(?:the )?(?:option |number |no\.? )?(first|second|third|fourth|fifth|sixth|1st|2nd|3rd|4th|5th|6th|one|two|three|four|five|six|[1-6]|last)(?: one| option)?(?: please)?$", re.I)
_OPTIONS = re.compile(r"The options are (.+?)\.(?:\s|$)")
_NON_LATIN = re.compile(r"[^\x00-\u024F\u2000-\u206F\u20B9\u2248]")


def social_only(m) -> bool:
    """A greeting / thanks / goodbye match with nothing else in it."""
    if not m:
        return False
    rest = re.findall(r"[a-z']+", (m.group("rest") or "").lower())
    return all(w in SOCIAL_TAIL for w in rest)


def devanagari(text: str) -> bool:
    """Hindi (Devanagari) by its letters, as Megh's typed path decides (app/translate.script_language): at least half
    of the letters. The typed path translates such a question (translate.to_english) and answers in English; the
    voice now sends it there too, instead of "I can only speak English" (16 Nov 2026)."""
    letters = [ch for ch in text or "" if ch.isalpha()]
    deva = sum(1 for ch in letters if "\u0900" <= ch <= "\u097f")
    return bool(letters) and deva * 2 >= len(letters)

STATS = {"sessions": 0, "active": 0, "turns": 0, "tool_calls": 0, "cancels": 0, "barges": 0, "leads": 0, "local": 0,
         "asr_early_used": 0, "asr_fallback_kyutai": 0, "empty_turns": 0, "continuations": 0, "picks": 0,
         "first_audio_ms": [], "errors": 0, "last_error": ""}


def _keep(lst: list, v, n: int = 300):
    lst.append(v)
    del lst[:-n]


def _pct(lst: list, p: float):
    if not lst:
        return None
    s = sorted(lst)
    return s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]


# scheme names as the recogniser mishears them (10 Nov, the user's first real-mic session: MGNREGA -> "Mandreka")
# District spellings as the recogniser writes them (11 Nov live spoken-accuracy run: "Southwest Khasi Hills",
# "Westgaro", "Reboy", "Cassie Hills"). Scheme and measure mishearings come from the domain pack (megh/domain:
# built from Megh's own registries + voice_overlay.yaml), read on every call so a new pack is live at once.
_DISTRICT_FIX = [
    (re.compile(r"\bsouth\s*-?\s*west\b", re.I), "South West"),
    (re.compile(r"\b(east|west|north|south)(garo|khasi|jaintia)\b", re.I), lambda m: m.group(1).title() + " " + m.group(2).title()),
    (re.compile(r"\b(?:ri\s*-?\s*bhoi|ribhoi|re+\s*bo[yi]|ree\s*buy|re+buy|ri\s*boi|ree\s*bhoi|ri\s*-?\s*v[oh]i|rivoi|"
                r"ree\s*v[oh]i|ri\s*bho+y|ri\s*-?\s*bhoy|re\s*bhoi)\b", re.I), "Ri Bhoi"),   # 12 Nov: "Rivoi"
    # 12 Nov fix round: "Ri Bhoi" heard as "reply", only where a place stands: before district / block, at the end of the
    # sentence, or before a year ("PMAY-G houses in reply in 2022-23"); "in reply to ..." is left alone
    (re.compile(r"\b(in|for|of|from)\s+reply\b(?=\s*(?:district|block|$|[.?!,;]|\s+(?:in|for|during)\s+(?:fy\s*)?20\d\d))",
                re.I), lambda m: m.group(1) + " Ri Bhoi"),
    (re.compile(r"\breply(?=\s+district\b)", re.I), "Ri Bhoi"),
    (re.compile(r"\b(?:cassie|kasi|kassi|khasie)(?=\s+hills?\b)", re.I), "Khasi"),
    (re.compile(r"\b(?:garrow|garow|gareau)(?=\s+hills?\b)", re.I), "Garo"),
    (re.compile(r"\b(?:jaintiya|jayantia|jayanthia|jaintya)(?=\s+hills?\b)", re.I), "Jaintia"),
    # after a direction word the misspelt name is a district even without "Hills" (12 Nov: "West Kasi")
    (re.compile(r"\b(east|west|north|south)\s+(?:cassie|kasi|kassi|khasie|kasee)\b", re.I), lambda m: m.group(1).title() + " Khasi"),
    (re.compile(r"\b(east|west|north|south)\s+(?:garrow|garow|gareau)\b", re.I), lambda m: m.group(1).title() + " Garo"),
    (re.compile(r"\b(east|west|north|south)\s+(?:jaintiya|jayantia|jayanthia|jaintya)\b", re.I), lambda m: m.group(1).title() + " Jaintia"),
    # a district said without "Hills" ("West Khasi", "South Garo") gets it: Megh's names all end in Hills
    (re.compile(r"\b((?:(?:south|eastern)\s+west|east|west|north|south)\s+(?:garo|khasi|jaintia))\b(?!\s+hills?\b)", re.I),
     lambda m: " ".join(w.title() for w in m.group(1).split()) + " Hills"),
]
# the whole table as it was before the pack (kept for tests and tooling; clean() reads the pack live)
_SCHEME_FIX = [*_domain.scheme_fixes(), *_domain.term_fixes(), *_DISTRICT_FIX]
_MID_FILLER = re.compile(r"(?<=[\s,.])(?:um+|uh+|erm+|er)[,.]?(?=\s)", re.I)


def clean(text: str) -> str:
    """The officer's words as the pipeline should see them: fillers off ("uh, um, what about Ri Bhoi"; Megh's
    follow-up matchers are anchored at the start), scheme names as Megh writes them, spaces tidied."""
    t = _FILLER.sub("", (text or "").strip())
    t = _MID_FILLER.sub("", " " + t)
    t = _domain.fix_schemes(t)                          # scheme names (the domain pack)
    t = _domain.fix_terms(t)                            # measure words ("person dies" -> person-days)
    for rx, name in _DISTRICT_FIX:
        t = rx.sub(name, t)
    t = places.snap(t)                                   # misheard district / block / constituency -> Megh's name
    return re.sub(r"\s+", " ", t).strip()


def options_from(speak: str) -> list[str]:
    """The labels of a clarification as Megh's spoken form says them: "... The options are A, B or C." """
    m = _OPTIONS.search(speak or "")
    if not m:
        return []
    body = m.group(1)
    parts = re.split(r",\s*|\s+or\s+", body)
    return [p.strip() for p in parts if p.strip()]


def remaining_text(text: str, sent: str) -> str:
    """What is left of a line from the start of the sentence that was being said when it was cut."""
    said_n = len((sent or "").split())
    parts = [x for x in re.split(r"(?<=[.?!])\s+", (text or "").strip()) if x]
    n = 0
    for i, ptx in enumerate(parts):
        n += len(ptx.split())
        if n > said_n:
            return " ".join(parts[i:])
    return ""


_SID = [0]


LOG_MODE = (os.environ.get("FDX_MEGH_LOG") or "masked").strip().lower()      # masked | full | off
_LOG_DIGITS = re.compile(r"(?<![\d,.])\d[\d \-]{7,}\d(?![\d,.])")          # 9+ digits, spaces / dashes inside
_LOG_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LOG_QUOTED = re.compile(r"(['\"])(.*?)\1")


def mask_log(msg: str) -> str:
    """The log line as it may be kept (14 Nov 2026, guardrail): 'masked' (default) hides what could identify a person
    in the officer's words or an answer (a run of 9+ digits: phone, Aadhaar, account number; an e-mail address) and
    keeps figures written with commas, years and scheme words; 'off' keeps only the length of every quoted text;
    'full' (local debugging only) changes nothing."""
    if LOG_MODE == "full":
        return msg
    if LOG_MODE == "off":
        return _LOG_QUOTED.sub(lambda m: f"<{len(m.group(2))} chars>", msg)

    def digits(m):
        only = "".join(ch for ch in m.group(0) if ch.isdigit())
        return m.group(0) if len(only) < 9 else f"[number ending {only[-2:]}]"
    return _LOG_EMAIL.sub("[email]", _LOG_DIGITS.sub(digits, msg))


def log(sid, msg: str):
    """One line per event of a live session (10 Nov): run/logs/megh.log is how a real-mic session is diagnosed."""
    print(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} s{sid} {mask_log(msg)}", flush=True)


def _same_q(a: str, b: str) -> bool:
    n = lambda x: " ".join("".join(ch if ch.isalnum() else " " for ch in (x or "").lower()).split())  # noqa: E731
    return bool(n(a)) and n(a) == n(b)


class Session:
    def __init__(self, ws, voice_key: str = ""):
        self.voice_key = voice_key                             # the officer's voice choice ("" = the default voice)
        _SID[0] += 1
        self.sid = _SID[0]
        self.ws = ws
        self.carry = None                                      # an unheard stretch to hear again with the next turn
        self.mem = shaper.Memory()                             # what was asked and answered (the shaper's context)
        self.cut_n = 0                                         # counts cuts: an answer being prepared sees it was cut
        self.out_any = False                                   # words already sent in this spoken turn
        self.closed = False
        self.wlock = asyncio.Lock()
        self.up = up16to24()
        self.ring: list[tuple[int, np.ndarray]] = []           # (first sample, 24 kHz audio), the last ~30 s
        self.samples = 0
        # the floor
        self.floor = 0.004
        self.in_speech = False
        self.voice_ms = 0.0
        self.voiced_run_ms = 0.0
        self.silence_ms = 0.0
        self.onset_sample = 0
        self.last_voice_sample = 0
        self.turn_voiced_s = 0.0
        self.kyutai_words: list[str] = []
        self.pause_p = 0.0
        self.turn_end_t = 0.0
        # dual ears
        self.asr_task: asyncio.Task | None = None
        self.asr_for = -1
        # the conversation
        self.n_call = 0
        self.pending: dict | None = None                         # {id, question, t_end, onset, leads}
        self.last_speak = ""
        self.options: list[str] = []
        # the mouth
        self.voice: CoreClient | None = None
        self.n_line = 0
        self.lines: dict[int, dict] = {}
        self.speaking_turn = False                               # a model turn is open (audio sent, no turnComplete yet)
        self.first_audio_due: float | None = None
        self.tail_until = 0.0
        self.finishing: dict | None = None                       # a turn whose words are being transcribed
        self.barged: dict | None = None                          # the answer a barge-in cut (16 Nov 2026: resumed after a noise)
        self.stt: STTClient | None = None
        self.tasks: list[asyncio.Task] = []

    # --- plumbing ------------------------------------------------------------------------------------------------
    async def send(self, obj: dict):
        if self.closed:
            return
        try:
            async with self.wlock:
                await self.ws.send(json.dumps(obj))
        except Exception:  # noqa: BLE001
            self.closed = True

    def spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self.tasks = [x for x in self.tasks if not x.done()]
        self.tasks.append(t)
        return t

    async def start(self):
        q = "?lead_frames=" + str(LEAD_FRAMES) + "&parts=whole" + ("&voice=" + self.voice_key if self.voice_key else "")
        self.voice = CoreClient(core_url(VOICE_URL + q, "", "", -1), RATE, api_key="", auth="none")
        await self.voice.connect(timeout=8.0)
        if STT_URL:
            try:
                self.stt = STTClient(STT_URL, STT_KEY)
                await self.stt.connect(timeout=8.0)
            except Exception as e:  # noqa: BLE001   timing falls back to energy alone; words still come from qwen3-asr
                STATS["last_error"] = f"stt connect: {type(e).__name__}"
                self.stt = None
        self.spawn(self.clock())
        self.spawn(self.from_voice())
        if self.stt is not None:
            self.spawn(self.from_stt())

    async def close(self):
        self.closed = True
        for t in self.tasks:
            t.cancel()
        for c in (self.voice, self.stt):
            if c is not None:
                try:
                    await c.close()
                except Exception:  # noqa: BLE001
                    pass

    async def clock(self):
        """The fact voice is input-clocked (one 80 ms frame out per 80 ms in): it is fed silence at real-time pace."""
        z = np.zeros(1920, np.float32)
        t0 = time.monotonic()
        n = 0
        while not self.closed:
            try:
                await self.voice.send_pcm(z)
            except Exception:  # noqa: BLE001
                return
            n += 1
            await asyncio.sleep(max(0.0, t0 + n * 0.08 - time.monotonic()))

    # --- the mouth -----------------------------------------------------------------------------------------------
    async def say(self, text: str, kind: str = "answer") -> int:
        """Queue a line on the fact voice; its audio and words go to the relay as the model's turn."""
        self.n_line += 1
        sid = self.n_line
        self.lines[sid] = {"text": text, "kind": kind, "state": "queued", "ev": asyncio.Event(), "t": time.time()}
        self.speaking_turn = True
        await self.voice.speak(sid, text)
        return sid

    def active_line(self) -> tuple[int, dict] | None:
        act = [(k, v) for k, v in self.lines.items() if v["state"] == "start"]
        return act[0] if act else None

    def speaking(self) -> bool:
        return any(v["state"] in ("queued", "start") for v in self.lines.values())

    async def wait_lines(self, timeout: float = 120.0):
        end = time.time() + timeout
        while self.speaking() and time.time() < end and not self.closed:
            await asyncio.sleep(0.05)

    async def cut(self):
        """Stop every line now (a barge-in or a new question)."""
        self.cut_n += 1
        self.out_any = False
        live = [k for k, v in self.lines.items() if v["state"] in ("queued", "start")]
        for k in live:
            self.lines[k]["state"] = "cancelled"
            self.lines[k]["ev"].set()
        if live:
            try:
                await self.voice.cancel()
            except Exception:  # noqa: BLE001
                pass

    async def end_model_turn(self):
        if self.speaking_turn:
            self.speaking_turn = False
            self.out_any = False
            await self.send({"serverContent": {"turnComplete": True}})

    async def from_voice(self):
        while not self.closed:
            kind, val = await self.voice.events.get()
            if kind == "event":
                ev = val if isinstance(val, dict) else json.loads(val)
                line = self.lines.get(ev.get("id"))
                if not line:
                    continue
                if ev.get("event") in ("start", "done", "cancelled"):
                    log(self.sid, f"line {ev.get('id')} ({line['kind']}) {ev.get('event')} [was {line['state']}]")
                if ev.get("event") == "start" and line["state"] == "queued":
                    line["state"] = "start"
                elif ev.get("event") in ("done", "cancelled") and line["state"] in ("queued", "start"):
                    if ev["event"] == "done" and line["state"] == "start":
                        self.tail_until = time.time() + 0.5
                    line["state"] = ev["event"]
                    line["ev"].set()
            elif kind == "audio":
                act = self.active_line()
                if act is None:
                    if time.time() < self.tail_until and len(val):   # the codec's last 0.5 s of a finished line
                        await self.send({"serverContent": {"modelTurn": {"parts": [{"inlineData": {
                            "mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(f32_to_pcm16(val)).decode()}}]}}})
                    continue
                pcm = val
                if not len(pcm) or float(np.max(np.abs(pcm))) < 1e-4 and not act[1].get("voiced"):
                    continue                                   # the line's leading silence is not sent
                act[1]["voiced"] = True
                if self.first_audio_due:
                    _keep(STATS["first_audio_ms"], round((time.time() - self.first_audio_due) * 1000))
                    self.first_audio_due = None
                await self.send({"serverContent": {"modelTurn": {"parts": [{"inlineData": {
                    "mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(f32_to_pcm16(pcm)).decode()}}]}}})
            elif kind == "text":
                act = self.active_line()
                if act is not None:
                    if self.out_any and val and not val.startswith(" "):
                        val = " " + val                    # the first word of a following line: keep the words apart
                    self.out_any = True
                    act[1]["sent"] = act[1].get("sent", "") + val
                    await self.send({"serverContent": {"outputTranscription": {"text": val}}})
            elif kind == "closed":
                STATS["errors"] += 1
                STATS["last_error"] = f"fact voice closed: {val}"
                self.closed = True
                try:
                    await self.ws.close(1011, "voice unavailable")
                except Exception:  # noqa: BLE001
                    pass
                return

    # --- the ears ------------------------------------------------------------------------------------------------
    async def from_stt(self):
        while not self.closed:
            ev = await self.stt.events.get()
            if ev[0] == "word":
                w = (ev[1] or "").strip()
                if w and self.in_speech:
                    self.kyutai_words.append(w)
            elif ev[0] == "step":
                prs = ev[1] or []
                self.pause_p = float(prs[2]) if len(prs) > 2 else 0.0
            elif ev[0] == "closed":
                self.stt = None                                 # energy alone keeps the timing; words come from qwen3-asr
                return

    def audio_range(self, a: int, b: int) -> np.ndarray:
        parts = [y[max(0, a - s0): max(0, b - s0)] for s0, y in self.ring if s0 + len(y) > a and s0 < b]
        return np.concatenate(parts) if parts else np.zeros(0, np.float32)

    def asr_prompt(self) -> str:
        if self.options:                                         # a clarification is open: its choices come first
            return ("Possible answers: " + ", ".join(self.options) + ". " + _domain.asr_prompt())[:600]
        return _domain.asr_prompt()

    async def asr_words(self, a: int, b: int) -> str | None:
        cap = time.time() + 0.6
        while self.samples < b and time.time() < cap and not self.closed:
            await asyncio.sleep(0.03)
        audio = self.audio_range(a, min(b, self.samples))
        if len(audio) < int(0.25 * RATE):
            return None
        info: dict = {}
        words = await relisten.transcribe(audio, self.asr_prompt(), voiced_s=len(audio) / RATE, echo="run", info=info)
        if words is None and info.get("why", "skipped") != "skipped":
            log(self.sid, f"recogniser {info['why']} after {info.get('s', 0):.2f} s"
                          + (f": {info['text'][:90]!r}" if info.get("text") else ""))
        self.asr_info = info
        return words

    def hanging(self) -> bool:
        """The last word the streaming ears heard leaves the sentence open ("in", "for", "of", "the", "and" ...)."""
        if not self.kyutai_words:
            return False
        last = "".join(ch for ch in str(self.kyutai_words[-1]).lower() if ch.isalpha())
        return last in HANGING_WORDS

    def turn_end_sample(self) -> int:
        """Where the sentence really ends: the last voiced frame or the last quiet-but-speech frame, whichever is later."""
        return max(self.last_voice_sample, getattr(self, "last_soft_sample", 0))

    def ask_early(self):
        end = self.turn_end_sample()
        if self.asr_for == end or not relisten.available():
            return
        self.asr_for = end
        self.asr_task = self.spawn(self.asr_words(max(0, self.onset_sample - int(0.3 * RATE)), end + int(0.4 * RATE)))

    async def on_audio(self, b: bytes):
        x16 = pcm16_to_f32(b)
        if not len(x16):
            return
        ms = len(x16) / RATE_IN * 1000
        y = self.up(x16)
        self.ring.append((self.samples, y))
        self.samples += len(y)
        while self.ring and self.samples - self.ring[0][0] > 30 * RATE:
            self.ring.pop(0)
        if self.stt is not None:
            try:
                await self.stt.send_pcm(y)
            except Exception:  # noqa: BLE001
                self.stt = None
        lvl = rms(x16)
        speaking = self.speaking()
        thr = max(VOICE_MIN_RMS, self.floor * 3.0) * (1.6 if speaking else 1.0)
        voice = lvl >= thr
        if self.in_speech and lvl >= max(SOFT_MIN_RMS, self.floor * 2.0):
            self.last_soft_sample = self.samples          # quiet speech still going: the recogniser must hear it
        if not voice and not self.in_speech:
            self.floor = 0.95 * self.floor + 0.05 * min(lvl, 0.05)
        if voice:
            self.voice_ms += ms
            self.silence_ms = 0.0
            self.last_voice_sample = self.samples
        else:
            self.silence_ms += ms
        # barge-in evidence is gathered ONLY while she is speaking (10 Nov, real-mic bug: the officer's own question
        # was still counted when the answer began, so her first frame "interrupted" her and she never spoke)
        if not speaking:
            self.voiced_run_ms = 0.0
        elif voice:
            self.voiced_run_ms += ms
        else:
            self.voiced_run_ms = max(0.0, self.voiced_run_ms - ms / 2)
            if not self.in_speech and self.silence_ms > 120:
                self.voice_ms = 0.0
        # barge-in: voice over her answer
        if speaking and self.voiced_run_ms >= BARGE_MS:
            STATS["barges"] += 1
            act = self.active_line()
            if act is not None and act[1]["kind"] in ("answer", "read", "resume"):
                self.barged = {"t": time.time(), "text": act[1]["text"], "sent": act[1].get("sent", ""),
                               "kind": act[1]["kind"]}
            log(self.sid, f"BARGE level {lvl:.3f} thr {thr:.3f} floor {self.floor:.4f} run {self.voiced_run_ms:.0f} ms")
            await self.cut()
            await self.send({"serverContent": {"interrupted": True}})
            self.speaking_turn = False
        if not self.in_speech and self.voice_ms >= ONSET_MS:
            await self.onset()
        if self.in_speech:
            if voice:
                self.turn_voiced_s += ms / 1000
            if self.silence_ms >= EARLY_ASR_MS:
                self.ask_early()
            need = SHORT_SILENCE_MS if self.turn_voiced_s < SHORT_TURN_S else END_SILENCE_MS
            hanging = self.hanging()
            if hanging:
                need = max(need, HANGING_SILENCE_MS)      # "... in West Garo Hills in" -> the year is still coming
            semantic = self.stt is not None and self.kyutai_words and self.pause_p >= 0.5 and not hanging and \
                self.silence_ms >= SEMANTIC_MIN_MS and self.turn_voiced_s >= SHORT_TURN_S
            if self.silence_ms >= need or semantic:
                await self.end_of_turn()

    async def onset(self):
        now = time.time()
        p = self.pending
        f = self.finishing
        if f and not f.get("done") and now - f["t"] < CONTINUE_S:
            # resumed while the last stretch was still being transcribed: one question, from its first word
            STATS["continuations"] += 1
            f["abandoned"] = True
            self.onset_sample = f["onset"]
            self.turn_voiced_s = f["voiced"]
        elif p and not p.get("answered") and now - p["t_end"] < CONTINUE_S:
            # they only paused mid-question: the call already made is withdrawn and the turn goes on from its start
            STATS["continuations"] += 1
            await self.cancel_call(p)
            self.onset_sample = p["onset"]
            self.turn_voiced_s = p["voiced"]
        elif self.carry and now - self.carry["t"] < 6.0:
            # the last stretch came back with no words: hear it again together with this one (10 Nov, real mic:
            # "Show me MGNREGA ..." was lost and only "per every financial year, as a bar graph" was asked)
            STATS["continuations"] += 1
            log(self.sid, "onset: carrying the unheard last stretch into this turn")
            self.onset_sample = self.carry["onset"]
            self.turn_voiced_s = self.carry["voiced"] + self.voice_ms / 1000
        else:
            self.onset_sample = max(0, self.samples - int((self.voice_ms + 200) / 1000 * RATE))
            self.turn_voiced_s = self.voice_ms / 1000
            self.kyutai_words = []
        self.carry = None
        self.in_speech = True
        self.asr_for = -1
        log(self.sid, f"onset (speaking={self.speaking()}, floor {self.floor:.4f})")
        await self.send({"voiceActivity": {"type": "ACTIVITY_START"}})

    async def end_of_turn(self):
        """The turn's end is decided here, at once; its words are fetched in a task of their own, so the audio loop
        (and with it barge-in) never waits on the recogniser."""
        self.in_speech = False
        self.voice_ms = 0.0
        self.turn_end_t = time.time()
        self.voiced_run_ms = 0.0
        await self.send({"voiceActivity": {"type": "ACTIVITY_END"}})
        f = {"onset": self.onset_sample, "end": self.turn_end_sample(), "voiced": self.turn_voiced_s,
             "t": time.time(), "abandoned": False, "done": False}
        self.finishing = f
        self.spawn(self.finish_turn(f))

    async def finish_turn(self, f: dict):
        onset, end, voiced = f["onset"], f["end"], f["voiced"]
        task = self.asr_task if self.asr_for == end and self.asr_task is not None else None
        if task is not None:
            STATS["asr_early_used"] += 1
        elif relisten.available():
            self.asr_for = end
            task = self.asr_task = self.spawn(self.asr_words(max(0, onset - int(0.3 * RATE)), end + int(0.4 * RATE)))
        words = None
        if task is not None:
            try:
                # with no streaming words to fall back on, the recogniser's words are worth waiting for
                t0 = time.time()
                cap = ASR_WAIT_ALONE_S
                words = await asyncio.wait_for(asyncio.shield(task), cap)
                left = cap - (time.time() - t0)
                if (not words and left > 1.0 and not f["abandoned"]
                        and str((getattr(self, "asr_info", None) or {}).get("why", "")).startswith("failed")):
                    STATS["asr_retries"] = STATS.get("asr_retries", 0) + 1
                    log(self.sid, "recogniser failed fast: asking once more")
                    words = await asyncio.wait_for(self.asr_words(max(0, onset - int(0.3 * RATE)),
                                                                  end + int(0.4 * RATE)), left)
            except Exception:  # noqa: BLE001
                words = None
        if f["abandoned"]:
            log(self.sid, f"turn merged into the next (heard {words!r})")
            return                                         # they carried on: the longer turn takes these words
        f["done"] = True
        if not words:
            if self.kyutai_words:
                STATS["asr_fallback_kyutai"] += 1
                why = str((getattr(self, "asr_info", None) or {}).get("why") or "no answer in time")
                log(self.sid, f"recogniser gave nothing ({why}): using the streaming words {' '.join(self.kyutai_words)!r}")
            words = " ".join(self.kyutai_words)
        text = clean(words or "")
        log(self.sid, f"end of turn ({voiced:.1f} s voiced): heard {text!r}")
        if self.is_noise(text) and voiced < NOISE_MAX_VOICED_S and await self.resume():
            return                                         # a cough / a sound over the answer: it goes on
        if text and _NON_LATIN.search(text):
            if devanagari(text):
                await self.user_turn(text, onset=onset, voiced=voiced, foreign=True)
            else:
                await self.say_local("Sorry, I can only speak English.")
            return
        if not text:
            STATS["empty_turns"] += 1
            if voiced >= 0.5:
                self.carry = {"onset": onset, "voiced": voiced, "t": time.time()}
            return
        await self.user_turn(text, onset=onset, voiced=voiced)

    # --- a noise over the answer (16 Nov 2026) ---------------------------------------------------------------------
    def is_noise(self, text: str) -> bool:
        """No words at all, or only sounds ("uh", "hmm"): not a turn of the officer's."""
        ws = re.findall(r"[a-z']+", (text or "").lower())
        return all(w in NOISE_WORDS for w in ws)

    async def resume(self) -> bool:
        """A barge-in cut the answer and what followed was no words (a cough, a door, the officer's "hmm"): the answer
        goes on from the start of the sentence it cut. Before, one such sound ended the answer for good."""
        b = self.barged
        self.barged = None
        if not b or time.time() - b["t"] > RESUME_WITHIN_S or self.speaking() or self.closed:
            return False
        if self.pending and not self.pending.get("answered"):
            return False                                   # a question is with the pipeline: nothing to resume
        rest = remaining_text(b["text"], b["sent"])
        if not rest:
            return False
        STATS["resumed"] = STATS.get("resumed", 0) + 1
        log(self.sid, f"noise over the answer: resuming from {rest[:60]!r}")
        self.first_audio_due = time.time()
        # an opening of its own: the relay must not take the same opening words for the answer read a second time
        await self.say("As I was saying, " + rest, kind="resume")
        await self.wait_lines(120)
        await self.end_model_turn()
        return True

    # --- one turn ------------------------------------------------------------------------------------------------
    async def say_local(self, line: str):
        STATS["local"] += 1
        self.first_audio_due = self.first_audio_due or time.time()
        await self.say(line, kind="local")
        await self.wait_lines(30)
        await self.end_model_turn()

    async def cancel_call(self, p: dict):
        if p.get("cancelled") or p.get("answered"):
            return
        p["cancelled"] = True
        STATS["cancels"] += 1
        log(self.sid, f"call {p['id']} CANCELLED")
        await self.send({"toolCallCancellation": {"ids": [p["id"]]}})
        await asyncio.sleep(0.35)                          # the page stops the running chat answer first

    async def user_turn(self, text: str, onset: int = 0, voiced: float = 0.0, typed: bool = False,
                        foreign: bool = False):
        low0 = text.lower().strip(" .?!,")
        if _STOP.match(low0):
            return await self.stop_now(text)
        local = bool(_WHO.search(low0) or (_REPEAT.match(low0) and self.last_speak) or _HEAR.match(low0)
                     or (social_only(_GREET.match(low0)) and len(low0.split()) <= 6) or social_only(_THANKS.match(low0))
                     or social_only(_BYE.match(low0)))
        shaped = None
        if foreign:
            # Hindi: the pipeline translates it as it does a typed question; the English shaper is not used on it
            shaped = {"action": "send", "question": text, "how": "translate"}
        elif not local:
            shaped = await shaper.shape(text, self.mem, spoken=not typed)
            if shaped["action"] == "hold":
                # only fillers, or it stops mid-sentence: nothing is sent; the audio is heard again with what follows
                log(self.sid, f"held ({shaped['how']}): {text!r}")
                if not typed and shaper.is_filler_sentence(text) and await self.resume():
                    return
                if not typed and voiced > 0:
                    self.carry = {"onset": onset, "voiced": voiced, "t": time.time()}
                return
        self.barged = None
        p0 = self.pending
        if (shaped and p0 and not p0.get("answered") and not p0.get("cancelled")
                and _same_q(shaped["question"], p0["question"]) and time.time() - p0["t_end"] < 12):
            # 12 Nov (the user's s27): "... every financial year?" then "Yeah." 1.2 s later re-asked the same question
            # and cut the answer that was coming; the running answer is kept
            STATS["same_again"] = STATS.get("same_again", 0) + 1
            log(self.sid, f"same question again ({text!r}): the running answer {p0['id']} is kept")
            return
        STATS["turns"] += 1
        await self.cut()
        if self.speaking_turn:
            await self.send({"serverContent": {"interrupted": True}})
            self.speaking_turn = False
        p = self.pending
        if p and not p.get("answered"):
            await self.cancel_call(p)                      # a new question replaces the one still being answered
        await self.send({"serverContent": {"inputTranscription": {"text": text}}})
        low = text.lower().strip(" .?!,")
        self.first_audio_due = time.time()
        if _WHO.search(low):
            return await self.say_local(IDENTITY)
        if _REPEAT.match(low) and self.last_speak:
            return await self.say_local(self.last_speak)
        if _HEAR.match(low):
            return await self.say_local("Yes, sir, I can hear you. What would you like to look at?")
        if social_only(_GREET.match(low)) and len(low.split()) <= 6:
            return await self.say_local("Hello, sir. What would you like to look at?")
        if social_only(_THANKS.match(low)):
            return await self.say_local("You're welcome, sir.")
        if social_only(_BYE.match(low)):
            return await self.say_local("Goodbye, sir.")
        question = shaped["question"] if shaped else text
        if shaped and shaped["how"] != "rules" or (shaped and question != text):
            log(self.sid, f"shaped ({shaped['how']}): {text!r} -> {question!r}")
        if shaped:
            self.options = []
            self.turn_said = text
            return await self.call(question, onset, voiced)
        if self.options:
            m = _PICK.match(low)
            if m:                                          # "the second one" -> that option's own words
                k = m.group(1).lower()
                i = len(self.options) - 1 if k == "last" else _ORDINAL.get(k, -1)
                if 0 <= i < len(self.options):
                    question = self.options[i]
                    STATS["picks"] += 1
            elif low in ("yes", "yes please", "ok", "okay", "go ahead") and len(self.options) == 1:
                question = self.options[0]
                STATS["picks"] += 1
        self.options = []
        await self.call(question, onset, voiced)

    async def stop_now(self, text: str):
        """'Stop' (16 Nov 2026): whatever is being said stops, the answer being prepared is withdrawn, a short spoken
        acknowledgement; nothing goes to the pipeline."""
        STATS["stops"] = STATS.get("stops", 0) + 1
        self.barged = None
        await self.cut()
        if self.speaking_turn:
            await self.send({"serverContent": {"interrupted": True}})
            self.speaking_turn = False
        p = self.pending
        if p and not p.get("answered"):
            await self.cancel_call(p)
        await self.send({"serverContent": {"inputTranscription": {"text": text}}})
        log(self.sid, f"stop: {text!r}")
        self.first_audio_due = time.time()
        await self.say_local("Stopped, sir.")

    async def call(self, question: str, onset: int, voiced: float):
        self.n_call += 1
        cid = f"mg{self.n_call}"
        p = {"id": cid, "question": question, "said": getattr(self, "turn_said", "") or question,
             "t_end": time.time(), "onset": onset, "voiced": voiced,
             "answered": False, "cancelled": False, "fut": asyncio.get_running_loop().create_future()}
        self.pending = p
        STATS["tool_calls"] += 1
        self.mem.asked(question, getattr(self, "turn_said", "") or question)
        log(self.sid, f"ask_megh {cid}: {question!r}")
        await self.send({"toolCall": {"functionCalls": [{"id": cid, "name": "ask_megh", "args": {"question": question}}]}})
        await self.send({"serverContent": {"turnComplete": True}})          # like Gemini: the tool-call turn ends first
        self.spawn(self.hold(p))

    async def hold(self, p: dict):
        """Holding phrases while the pipeline works (cross-scheme answers take 10-40 s): said in the model's next turn,
        which the answer then continues, so the relay sees one spoken turn."""
        marks = [LEAD_AFTER_S, *LEAD_AGAIN_S]
        t0 = p["t_end"]
        for i, at in enumerate(marks):
            while time.time() - t0 < at:
                if p["answered"] or p["cancelled"] or self.closed or self.pending is not p:
                    return
                await asyncio.sleep(0.05)
            if self.in_speech or self.speaking():
                continue
            STATS["leads"] += 1
            line = (megh_lines.LEAD_FIRST[self.n_call % len(megh_lines.LEAD_FIRST)] if i == 0
                    else megh_lines.LEAD_LATER[min(i - 1, len(megh_lines.LEAD_LATER) - 1)])
            await self.say(line, kind="lead")

    async def on_tool_response(self, resp: dict):
        for fr in resp.get("functionResponses") or []:
            p = self.pending
            if not p or fr.get("id") != p["id"] or p["cancelled"]:
                log(self.sid, f"answer {fr.get('id')} IGNORED (pending {p and p['id']}, cancelled {p and p['cancelled']})")
                continue
            p["answered"] = True
            r = fr.get("response") or {}
            speak = (r.get("speak") or "").strip()
            kind = r.get("kind") or ""
            log(self.sid, f"answer {p['id']} kind={kind} {len(speak)} chars after {time.time() - p['t_end']:.1f} s: {speak!r}")
            if kind == "already_answered" or not speak:
                await self.wait_lines(10)
                await self.end_model_turn()
                return
            # the pipeline's own reading of the question (16 Nov 2026, the voice audit): the memory takes it
            self.mem.answered(speak, kind, natural.options_of(speak) if kind == "clarification" else [],
                              asked_as=str(r.get("asked_as") or ""), frame=r.get("frame") if isinstance(r.get("frame"), dict) else None)
            if shaper.failed_answer(speak) and not p.get("retry"):
                # a rewritten question that failed is asked again in the officer's own (cleaned) words first; only
                # their own words that failed get a standalone rewrite from the conversation
                own = shaper.clean_spoken(p.get("said") or "")
                q2 = own if own and shaper._low(own) != shaper._low(p["question"]) else \
                    await shaper.retry_question(p["question"], self.mem)
                if q2 and self.pending is p and not self.closed:
                    log(self.sid, f"no query for {p['question']!r}: asked again as {q2!r}")
                    await self.call(q2, p["onset"], p["voiced"])
                    self.pending["retry"] = True
                    return
            if kind == "clarification":
                self.options = options_from(speak)
            # a lead still waiting to start is dropped; one being said finishes, then the answer follows
            for k, v in list(self.lines.items()):
                if v["kind"] == "lead" and v["state"] == "queued":
                    v["state"] = "cancelled"
                    v["ev"].set()
                    try:
                        await self.voice.cancel(k)
                    except Exception:  # noqa: BLE001
                        pass
            self.last_speak = speak
            self.first_audio_due = self.first_audio_due or time.time()
            # said the way a person would say it (megh/natural.py: the on-prem LLM re-says the checked answer; every
            # figure and name is held to the checked answer by a deterministic guard, else the answer itself is said)
            n0, said = self.cut_n, []
            if r.get("spoken_form"):
                # 16 Nov 2026 (the user's live test): the page's answer is already Megh's own spoken form (c19: short
                # sentences, the leader named first, figures rounded and checked). Re-saying it through the model
                # joined its four sentences into one 15.7 s sentence and the captions waited for its end. Said as given.
                STATS["spoken_form"] = STATS.get("spoken_form", 0) + 1
                said = natural.sentences(" ".join(speak.split()))
            else:
                async for sent in natural.say_naturally(speak, p["question"], kind, turn=self.n_call):
                    if self.cut_n != n0 or self.closed or self.pending is not p:
                        break                              # the officer spoke over it meanwhile
                    said.append(sent)
            if said and self.cut_n == n0 and not self.closed and self.pending is p:
                # the whole answer as ONE line: one breath, one steady voice, its own pauses (sidevoice ?parts=whole)
                self.last_speak = " ".join(said)
                log(self.sid, f"said: {self.last_speak!r}")
                await self.say(self.last_speak, kind="answer")
            await self.wait_lines(180)
            await self.end_model_turn()

    async def on_client_text(self, text: str):
        log(self.sid, f"page text: {text[:110]!r}")
        if text.startswith(CONTEXT_PREFIX):
            self.take_context(text.split(") ", 1)[-1])
            return
        if text.startswith(READ_PREFIX):
            line = text.split(") ", 1)[-1].strip()
            await self.cut()
            self.barged = None
            # any answer read aloud (a typed question's, a chip's, "to be exact") is the one "say that again" repeats
            self.last_speak = line or self.last_speak
            self.first_audio_due = time.time()
            await self.say(line, kind="read")
            await self.wait_lines(120)
            await self.end_model_turn()
            return
        if text.startswith(NUDGE_PREFIX):
            return                                         # the answer is already being said (we never wait to be nudged)
        if text.startswith(NOT_ENGLISH_PREFIX):
            await self.say_local("Sorry, I can only speak English.")
            return
        spoken = text.startswith("[voice] ")
        body = clean(text[8:] if spoken else text)
        if body:
            await self.user_turn(body, typed=not spoken)

    def take_context(self, body: str):
        """The pipeline's reading of turns the voice did not ask (typed, chips, the chat before the voice opened)."""
        try:
            items = (json.loads(body) or {}).get("items") or []
        except ValueError:
            return
        for it in items[:3]:
            if not isinstance(it, dict) or not it.get("asked_as"):
                continue
            self.mem.typed(str(it["asked_as"])[:400], str(it.get("speak") or "")[:600], str(it.get("kind") or "data"),
                           it.get("frame") if isinstance(it.get("frame"), dict) else None)
            if it.get("speak"):
                self.last_speak = str(it["speak"])
        STATS["context_items"] = STATS.get("context_items", 0) + len(items)
        log(self.sid, f"context: {len(items)} turn(s) from the chat")

    async def run(self):
        async for raw in self.ws:
            if self.closed:
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "realtimeInput" in msg:
                a = (msg["realtimeInput"] or {}).get("audio")
                if a and a.get("data"):
                    await self.on_audio(base64.b64decode(a["data"]))
            elif "toolResponse" in msg:
                self.spawn(self.on_tool_response(msg["toolResponse"]))
            elif "clientContent" in msg:
                cc = msg["clientContent"] or {}
                text = "".join(pt.get("text", "") for t in cc.get("turns") or [] for pt in t.get("parts") or [])
                if text:
                    self.spawn(self.on_client_text(text))


VOICE_KEYS = ("a", "b", "c", "d", "e")      # the fact voice's voice map keys (sidevoice); anything else = the default


def voice_choice(first: dict) -> str:
    """The voice the page chose (12 Nov, the voice toggle): Megh's relay puts it where Gemini Live takes a prebuilt voice
    name, setup.generationConfig.speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName."""
    try:
        name = first["setup"]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"]
    except (KeyError, TypeError):
        return ""
    name = str(name or "").strip().lower()
    return name if name in VOICE_KEYS else ""


async def handler(ws):
    try:
        first = json.loads(await asyncio.wait_for(ws.recv(), 15))
    except Exception:  # noqa: BLE001
        await ws.close(1008, "no setup")
        return
    if "setup" not in first:
        await ws.close(1008, "no setup")
        return
    s = Session(ws, voice_choice(first))
    try:
        await s.start()
    except Exception as e:  # noqa: BLE001
        STATS["errors"] += 1
        STATS["last_error"] = f"start: {type(e).__name__}: {str(e)[:80]}"
        await s.close()
        await ws.close(1011, "voice engine unavailable")
        return
    # meghContext (16 Nov 2026): this engine reads the relay's CONTEXT_LINE data (the pipeline's reading of typed turns)
    await ws.send(json.dumps({"setupComplete": {"meghContext": True}}))
    log(s.sid, f"session open (stt {'on' if s.stt is not None else 'off'}; voice {s.voice_key or 'default'})")
    STATS["sessions"] += 1
    STATS["active"] += 1
    try:
        await s.run()
    except Exception as e:  # noqa: BLE001
        STATS["errors"] += 1
        STATS["last_error"] = f"session: {type(e).__name__}: {str(e)[:80]}"
    finally:
        STATS["active"] -= 1
        log(s.sid, f"session closed (code {getattr(ws, 'close_code', None)})")
        await s.close()


def _stats() -> dict:
    out = {k: v for k, v in STATS.items() if not isinstance(v, list)}
    fa = STATS["first_audio_ms"]
    out["first_audio_ms"] = {"n": len(fa), "p50": _pct(fa, 0.5), "p95": _pct(fa, 0.95)}
    out["asr"] = dict(relisten.STATS)
    out["natural"] = natural.stats()
    out["shaper"] = shaper.stats()
    out["engine"] = {"voice": VOICE_URL, "stt": "on" if STT_URL else "off", "asr": relisten.available()}
    return out


ENGINE_TOKEN = (os.environ.get("FDX_MEGH_TOKEN") or "").strip()


def _token_ok(request) -> bool:
    """A WebSocket must present FDX_MEGH_TOKEN when one is set (14 Nov 2026, guardrail): ?key=<token> in the URL (how
    Megh's relay addresses a Live server) or the header x-megh-token. Compared in constant time; never logged."""
    if not ENGINE_TOKEN:
        return True
    import hmac
    from urllib.parse import parse_qs, urlsplit
    given = (parse_qs(urlsplit(request.path).query).get("key") or [""])[0] or (request.headers.get("x-megh-token") or "")
    return hmac.compare_digest(str(given), ENGINE_TOKEN)


def process_request(connection, request):
    _path = request.path.split("?", 1)[0]
    if _path == "/health":
        body = json.dumps({"ok": True, "engine": "megh-sovereign"}).encode()
        return Response(200, "OK", Headers([("Content-Type", "application/json"), ("Content-Length", str(len(body)))]), body)
    if not _token_ok(request):
        STATS["refused"] = STATS.get("refused", 0) + 1
        body = b'{"error": "unauthorised"}'
        return Response(401, "Unauthorized", Headers([("Content-Type", "application/json"), ("Content-Length", str(len(body)))]), body)
    if _path == "/stats":                                  # the engine's counters: behind the token when one is set
        body = json.dumps(_stats()).encode()
        return Response(200, "OK", Headers([("Content-Type", "application/json"), ("Content-Length", str(len(body)))]), body)
    return None


async def main():
    async with serve(handler, os.environ.get("FDX_BIND_HOST", "127.0.0.1"), PORT, process_request=process_request, max_size=None, ping_interval=20):
        print(f"megh adapter on ws://127.0.0.1:{PORT}  (voice {VOICE_URL}; stt {'on' if STT_URL else 'off'}; "
              f"asr {'on' if relisten.available() else 'OFF'})", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

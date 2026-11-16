"""The sovereign SIDE-VOICE core (Track A): a server that speaks EXACTLY the duplex-core protocol the relay uses
(fdx/protocol/moshi.py, spec v1.1: PersonaPlex / Moshi `/api/chat` + the Mitra extension 0x10 / 0x11 / 0x12), whose voice
is qwen3-tts on the team gateway instead of a duplex model. Only FDX_CORE_URL changes in the relay.

The wire (binary WebSocket frames, first byte = kind):
  0x00            handshake, sent at once after the session opens (text_prompt / voice_prompt / seed are accepted and ignored)
  0x01 in         the person's Ogg-Opus 24 kHz (decoded with sphn; the side voice does not listen to it, it only clocks)
  0x01 out        INPUT-CLOCKED like the fake core and the real servers' opus_loop: exactly one Ogg-Opus frame per 1920
                  input samples (80 ms). No input, no step, no output. A silent frame when there is nothing to say.
  0x02 out        the line's words, whole, one step before each word is heard (estimated: TTS gives no timestamps)
  0x10 in         {id, text}: queue the line. Its TTS request starts AT ONCE (pre-fetch), even behind a playing line
  0x11 in         {id} | {}: stop that line (or all) within one step; its HTTP stream is aborted; `cancelled` is sent
  0x12 out        {id, event: start | done | cancelled}; `done` carries `error` when the TTS failed
  0x05 out        (12 Nov 2026, opt-in with ?pcm=1) the same frame as raw PCM16 LE, 1920 samples, INSTEAD of 0x01: the
                  Ogg-Opus hop (~25 kbit/s at 80 ms frames) costs ~8.7 dB SNR / ~7 dB log-spectral distance against
                  the TTS; on localhost the raw frame (46 kB/s) is lossless. The client must read 0x05 (not yet the
                  engine's fdx/protocol/moshi.py CoreClient: until it does, nobody asks for it and nothing changes)

Query: ?voice=<key> (voices/voices.json) · ?parts=whole (one TTS request per line) · ?lead_frames=N · ?pcm=1
Sound: every line at one speech level (FDX_SV_LEVEL_DB, -19 dBFS RMS of its speech), the gain gliding (no pumping), a
       6 ms fade-in, the decay frame after the last voiced one played faded (no cut endings), a soft ceiling at -1 dBFS,
       +2 dB above 3.5 kHz before the codec (FDX_SV_SHELF_DB); FDX_SV_SHAPE=0 = the TTS frames exactly as before

Voice: POST {FDX_GATEWAY_URL}/audio/speech, qwen3-tts Base (clones the reference clip FDX_TTS_REF), streamed raw s16le
24 kHz PCM. A line with several sentences is requested sentence by sentence, all at once (a short request answers
sooner, and each sentence start is an exact anchor for the word timing). Identical texts are cached for the life of the
process; the relay's fixed lines (lead phrases, the listen offer, the stop acknowledgement) are warmed at start-up.

The voice never speaks on its own: no free speech, no backchannels (Gemini never backchannels). Keys come ONLY from
ops/keys.py and never appear in a log, a reply, /health or /stats.

Run:    .venv\\Scripts\\python sidevoice\\server.py [port]          (default 8150; plain ws:// on 127.0.0.1)
HTTP:   /health  /stats  (counters, first-chunk / first-audio latency p50 / p95, cache hits; never keys)
Env:    FDX_TTS_REF (voices/test_reference.wav) · FDX_TTS_STYLE · FDX_TTS_MODEL (qwen3-tts) · FDX_TTS_LANGUAGE (English)
        FDX_TTS_FIRST_S (6: the first chunk must come by then) · FDX_TTS_CONCURRENCY (4) · FDX_SV_SPLIT (1: per sentence)
        FDX_SV_START (turn: `start` when the line's turn comes | audio: when its first frame is ready)
        FDX_SV_GAP_MS (240: quiet between two lines) · FDX_SV_SENT_GAP_MS (320: between two sentences of a line)
        FDX_SV_LAG_STEPS (1) · FDX_SV_WARM (1) · FDX_SV_CACHE_S (900 s of audio kept)"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import time
import urllib.parse
from collections import OrderedDict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import httpx  # noqa: E402
import numpy as np  # noqa: E402
import sphn  # noqa: E402
from websockets.asyncio.server import serve  # noqa: E402
from websockets.datastructures import Headers  # noqa: E402
from websockets.http11 import Response  # noqa: E402

from ops.keys import env as key_env  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8150
RATE, STEP = 24000, 1920
STEP_S = STEP / RATE


def _env(name: str, default):
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return type(default)(v) if not isinstance(default, bool) else v.lower() in ("1", "true", "yes", "on")


def maya_cfg() -> dict:
    """maya2-native (16 Nov 2026, the user's pick: the default voice and a Female / Male toggle): URL, key, model from the
    process env, else from the project's git-ignored gateway_models.env. Never logged or returned by /health."""
    out = {k: os.environ.get(k, "") for k in ("MAYA_TTS_URL", "MAYA_TTS_API_KEY", "MAYA_TTS_MODEL")}
    if not (out["MAYA_TTS_URL"] and out["MAYA_TTS_API_KEY"]):
        try:
            for row in (ROOT / "gateway_models.env").read_text(encoding="utf-8").splitlines():
                row = row.strip()
                if row and not row.startswith("#") and "=" in row:
                    k, v = row.split("=", 1)
                    if k in out and not out[k]:
                        out[k] = v.strip()
        except OSError:
            pass
    out["MAYA_TTS_MODEL"] = out["MAYA_TTS_MODEL"] or "maya2-native"
    return out


CFG = {
    # the voice engine: "maya" (maya2-native, Indian voices, 16 Nov 2026) or "qwen" (qwen3-tts reference cloning)
    "engine": os.environ.get("FDX_TTS_ENGINE", "maya").lower(),
    "maya_voice": os.environ.get("FDX_MAYA_VOICE", "Jahnavi"),
    "ref": os.environ.get("FDX_TTS_REF") or str(ROOT / "voices" / "test_reference.wav"),
    "style": os.environ.get("FDX_TTS_STYLE") or (
        "A calm, clear Indian-English government voice: composed and warm, medium pitch, measured pace. "
        "Very clear for figures and place names."),
    "model": _env("FDX_TTS_MODEL", "qwen3-tts"),
    "seed": _env("FDX_TTS_SEED", 2026),               # one seed for every phrase (-1 = unseeded, as before 10 Nov)
    "language": _env("FDX_TTS_LANGUAGE", "English"),
    "first_s": _env("FDX_TTS_FIRST_S", 6.0),          # the first PCM chunk must arrive by then, or the line fails
    "total_s": _env("FDX_TTS_TOTAL_S", 90.0),
    "concurrency": _env("FDX_TTS_CONCURRENCY", 4),
    "split": _env("FDX_SV_SPLIT", True),
    "start": _env("FDX_SV_START", "turn"),
    "gap_ms": _env("FDX_SV_GAP_MS", 240),
    "sent_gap_ms": _env("FDX_SV_SENT_GAP_MS", 320),
    "list_gap_ms": _env("FDX_SV_LIST_GAP_MS", 260),     # between two items of a spoken list (10 Nov)
    "list_split": _env("FDX_SV_LIST_SPLIT", False),    # off since full cloning (one request per sentence pauses by itself)
    "lag_steps": _env("FDX_SV_LAG_STEPS", 1),
    "warm": _env("FDX_SV_WARM", True),
    "cache_s": _env("FDX_SV_CACHE_S", 900.0),
}
PRONOUNCE = ROOT / "fdx" / "pronounce.json"
_PRON: dict = {"mtime": None, "rx": None, "map": {}}


_PHONE = re.compile(r"(?<![\w-])\d{2,5}(?:[ -]\d{2,5}){1,3}(?![\w-])")
_CASE_ID = re.compile(r"\b(GR|SK)-([A-Z0-9]*\d[A-Z0-9]*)\b", re.I)
# 10 Nov 2026 (Megh One AI answers on the same fact voice): money is ₹ / Rs. / INR, with its decimals and its crore / lakh
# unit ("₹2,222.75 crore" is "two thousand two hundred and twenty two point seven five crore rupees"); the old rule
# stopped at the decimal point and said "rupees.75 crore"
_MONEY = re.compile(r"(?:₹|(?<![\w.])(?:Rs|RS|rs)\.?|(?<![\w.])INR)\s?(\d[\d,]*\d|\d)(\.\d+)?"
                    r"(?:\s?((?i:crores?|cr|lakhs?|lacs?))(?![\w]))?")
# Indian grouping: a 2-digit group before the last three (54,89,616 · 1,29,941 · 22,22,75,30,000) is read in lakh / crore
_INDIAN = r"\d{1,2}(?:,\d{2})+,\d{3}"
_NUM = re.compile(r"(?<![A-Za-z0-9\-/.:₹])(" + _INDIAN + r"|\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(\s?%)?(?![A-Za-z0-9]|[-/:]\d|\.\d)")
# a financial year or a span of years: 2023-24 / FY 2017-18 / 2023-2024 ("twenty twenty three twenty four"); checked to
# be a real span (the second year after the first, at most ten on), so an ISO date or a range of counts is left alone
_YEAR_SPAN = re.compile(r"(?<![\w\-/.:,₹])((?:19|20)\d{2})\s?[-–]\s?((?:19|20)?\d{2})(?![\w%]|[-/:.,]\d)")
_MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
           r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)")
# "11 September 2025" is said "eleventh September twenty twenty five" (the year already follows the month rule)
_DAY = re.compile(r"(?<![\w\-/.:,₹])([1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s+(?=" + _MONTHS + r"\b)")
_ORDINAL = re.compile(r"(?<![\w\-/.:,₹])(\d+)(?:st|nd|rd|th|ST|ND|RD|TH)(?!\w)")
_KILO = re.compile(r"(?<![\w\-/.:,₹])(\d+)(\.\d+)?K(?!\w)")                       # 93K / 12.5K (case-sensitive K)
_MINUS = re.compile(r"(?:^|(?<=[\s(]))[-−](?=[\d₹])")                             # "-12" after a space / start only
_APPROX_ONCE = re.compile(r"(?<![\w.])₹?\d[\d,]*(?:\.\d+)?\s*\(\s*≈\s*([^()]*?)\s*\)")
_APPROX = re.compile(r"\(\s*≈\s*([^()]*?)\s*\)")
_RUPEES_PRE = re.compile(r"\brupees\s+$", re.I)
_YEAR_PRE = re.compile(r"\b(in|year|since|during|sakala|for|of|by|until|from|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?),?\s+$", re.I)
_COUNT_NEXT = re.compile(r"^\s*(open|overdue|pending|escalated|resolved|matching|cases?|applications?|grievances?|requests?|"
                         r"complaints?|officers?|days?|percent|districts?|taluks?)", re.I)
_DIGITS_PRE = re.compile(r"\b(ending in|number|no\.?|code|pin|otp|call|dial|helpline)\s+$", re.I)


def _digits(s: str) -> str:
    return " ".join(ONES[int(c)] for c in s if c.isdigit())


def say_numbers(text: str) -> str:
    """Every figure written out the way a person says it, so the TTS never chooses (10 Nov: ", 712," was said "seven
    one two" in every voice tried). Counts in words ("seven hundred and twelve", "three thousand and fifty one"); case
    ids, phone numbers, long digit strings and "ending in 4811" digit by digit; percentages, decimals, rupees and years
    ("twenty twenty five" after in / since / Sakala ...) properly. L1 / L2 / GP names with digits are left alone."""
    text = _CASE_ID.sub(lambda m: " ".join(m.group(1).upper()) + " " + " ".join(
        (ONES[int(c)] if c.isdigit() else c.upper()) for c in m.group(2)), text)
    # 10 Nov 2026 (Megh): "₹22,22,75,30,000 (≈ ₹2,222.75 crore)" is said once, as "about ₹2,222.75 crore", the way
    # Megh's own voice page does it (voiceSpeech.js sayApproxOnce); any other "(≈ x)" is "about x"
    if "≈" in text:
        text = _APPROX_ONCE.sub(lambda m: "about " + m.group(1), text)
        text = _APPROX.sub(lambda m: "about " + m.group(1), text)
        text = re.sub(r"≈\s*", "about ", text)
    text = _MINUS.sub("minus ", text)
    text = _YEAR_SPAN.sub(_year_span, text)       # before the phone rule: 2023-2024 is not a phone number
    text = _PHONE.sub(lambda m: _digits(m.group(0)) if sum(c.isdigit() for c in m.group(0)) >= 7 else m.group(0), text)
    text = _MONEY.sub(_money, text)
    text = _DAY.sub(lambda m: ordinal_words(int(m.group(1))) + " ", text)
    text = _ORDINAL.sub(lambda m: ordinal_words(int(m.group(1))), text)
    text = _KILO.sub(lambda m: num_words(int(m.group(1))) + (" point " + _digits(m.group(2)) if m.group(2) else "")
                     + " K", text)

    def rep(m):
        whole, frac, pct = m.group(1), m.group(2), m.group(3)
        digits = whole.replace(",", "")
        before, after = text[:m.start()], text[m.end():]
        if re.fullmatch(_INDIAN, whole):           # 10 Nov 2026: Indian grouping is never an id; lakh / crore
            out = num_words_indian(int(digits))
        elif (len(digits) >= 5 and "," not in whole) or _DIGITS_PRE.search(before):
            # a bare long figure after "rupees" is an amount (Indian words); anything else stays digit by digit
            out = num_words_indian(int(digits)) if "," not in whole and _RUPEES_PRE.search(before) \
                and not _DIGITS_PRE.search(before) else _digits(digits)
        else:
            n = int(digits)
            if (not frac and not pct and "," not in whole and len(digits) == 4 and 1990 <= n <= 2035
                    and _YEAR_PRE.search(before) and not _COUNT_NEXT.match(after)):
                out = _year_words(n)
            else:
                out = num_words(n)
        if frac:
            out += " point " + _digits(frac)
        return out + (" percent" if pct else "")
    return _NUM.sub(rep, text)


def _year_words(n: int) -> str:
    """2025 -> "twenty twenty five", 2005 -> "twenty oh five", 2000 -> "twenty hundred" (the rule say_numbers has used
    since it was written; kept identical)."""
    lo = n % 100
    return num_words(n // 100) + " " + ("hundred" if lo == 0 else ("oh " + ONES[lo]) if lo < 10 else num_words(lo))


def _year_span(m) -> str:
    """10 Nov 2026 (Megh's financial years): "2023-24" -> "twenty twenty three twenty four", "2017-18" -> "twenty
    seventeen eighteen", "2009-10" -> "two thousand nine ten". Not a span of years (an ISO date, 2023-05, 2020-19) ->
    unchanged."""
    a, b = int(m.group(1)), m.group(2)
    end = (a // 100) * 100 + int(b) if len(b) == 2 else int(b)
    if not (1990 <= a <= 2049 and a < end <= a + 10):
        return m.group(0)

    def yw(n: int) -> str:
        return ("two thousand" + ("" if n == 2000 else " " + ONES[n % 100])) if 2000 <= n <= 2009 else _year_words(n)
    tail = yw(end) if len(b) == 4 else (("oh " + ONES[int(b)]) if int(b) < 10 else num_words(int(b)))
    return yw(a) + " " + tail


def _money(m) -> str:
    """10 Nov 2026: ₹ / Rs. / INR + figure (+ decimals) (+ crore / lakh) -> "<figure> [crore|lakh] rupees". Indian
    grouping or a bare figure is read in lakh / crore; international commas (₹100,000) stay international. Below one
    lakh both systems say the same words, so "₹20" / "₹500" read exactly as before."""
    whole, frac, unit = m.group(1), m.group(2), m.group(3)
    digits = whole.replace(",", "")
    n = int(digits)
    out = num_words(n) if ("," in whole and not re.fullmatch(_INDIAN, whole)) else num_words_indian(n)
    if frac:
        out += " point " + _digits(frac)
    if unit:
        out += " crore" if unit.lower().startswith("cr") else " lakh"
    return out + " rupees"


# 10 Nov 2026 (Megh One AI on the fact voice): scheme names and acronyms the TTS otherwise reads as a word ("pee-may",
# "em-gen-rega") or a unit ("CM" = centimetre). Case-sensitive, so ordinary words are never touched; "AC" only before a
# number (assembly constituency: "AC 16"), so Mitra's "the AC of Hunsur" is left as it was. LIFCOM is said as a word.
SAY_AS = [(re.compile(p), r) for p, r in (
    (r"(?<![\w-])PMAY-G(?![\w-])", "P M A Y G"),
    (r"\bPMAY\b", "P M A Y"),
    (r"\bMGNREGA\b", "M G N R E G A"),
    (r"\bCM Elevate\b", "C M Elevate"),
    (r"(?<!\w)(?:Focus|FOCUS)\+", "Focus Plus"),
    (r"\bFOCUS\b", "Focus"),
    (r"\bFY\b", "financial year"),
    (r"\bAC(?=\s?\d)", "A C"),
    (r"\bPGs\b", "P Gs"),
    (r"\bPG\b", "P G"),
    (r"\bDBT\b", "D B T"),
    (r"\b[Tt]ranch\b", "tranche"),
)]


def say_as(text: str) -> str:
    for rx, rep in SAY_AS:
        text = rx.sub(rep, text)
    return text


def spoken(text: str) -> str:
    """The text the TTS is asked to SAY: figures in words (say_numbers), and every name / term in fdx/pronounce.json
    replaced by its spoken spelling, the one closest to how the user said it in the booth (voicekit/pronounce.py; 10
    Nov: "whatever I have said is the correct Indian pronunciation"). Captions, the screen and the cache key keep the
    real spelling. Re-read on change. 10 Nov 2026: scheme names / acronyms (SAY_AS) first, so "AC 16", "Tranch 4" and
    "FY 2023-24" reach say_numbers already spelled out."""
    text = say_numbers(say_as(text))
    try:
        mt = PRONOUNCE.stat().st_mtime if PRONOUNCE.exists() else None
    except OSError:
        mt = None
    if mt != _PRON["mtime"]:
        mp = {}
        if mt is not None:
            try:
                mp = {k: v for k, v in json.loads(PRONOUNCE.read_text(encoding="utf-8")).items() if k and v}
            except (OSError, ValueError):
                mp = {}
        alts = sorted(mp, key=len, reverse=True)
        _PRON.update({"mtime": mt, "map": {k.lower(): v for k, v in mp.items()},
                      "rx": re.compile(r"\b(" + "|".join(re.escape(a) for a in alts) + r")\b", re.I) if alts else None})
    rx = _PRON["rx"]
    return rx.sub(lambda m: _PRON["map"].get(m.group(0).lower(), m.group(0)), text) if rx is not None else text


VOICED = 0.008         # a frame at or above this RMS (before the codec) is part of the line; the relay's speech level is 0.012
LEAD_THR = 0.02         # the first sample this loud is where the line's sound begins (the TTS's leading silence is skipped)
GAP_RMS = 0.01          # frames under this inside a sentence are a pause (an anchor for the word timing)

# 12 Nov 2026, the sound (harness/megh/probe_audio_chain.py): every line at one speech level, no clicks, no clipping.
# FDX_SV_LEVEL_DB = the target speech level (dBFS RMS of the active frames; "off" = the TTS level as it comes);
# FDX_SV_SHAPE=0 turns all of it off (the frames exactly as before).
AUDIO = {
    "on": _env("FDX_SV_SHAPE", True),
    "level_db": None if (os.environ.get("FDX_SV_LEVEL_DB") or "").lower() == "off" else _env("FDX_SV_LEVEL_DB", -19.0),
    "max_boost_db": _env("FDX_SV_MAX_BOOST_DB", 9.0),
    "max_cut_db": _env("FDX_SV_MAX_CUT_DB", 9.0),
    "slew_db": _env("FDX_SV_SLEW_DB", 0.6),          # the gain moves at most this much per 80 ms frame (no pumping)
    "slew_first_db": _env("FDX_SV_SLEW_FIRST_DB", 1.5),   # ... and this much during the first second (settling)
    "prior_frames": _env("FDX_SV_PRIOR_FRAMES", 4),  # how much the voice's usual level counts while little has arrived
    # a gentle high shelf before the Ogg-Opus hop to the engine: the codec (~25 kbit/s at 80 ms frames) takes ~1.8 dB
    # off everything above 4 kHz; +2 dB at 3.5 kHz gives the page the TTS's own brightness back (measured)
    "shelf_db": _env("FDX_SV_SHELF_DB", 2.0),
    "shelf_hz": _env("FDX_SV_SHELF_HZ", 3500.0),
    "ceiling": 10 ** (_env("FDX_SV_CEILING_DB", -1.0) / 20),
    "knee": 10 ** (_env("FDX_SV_KNEE_DB", -3.0) / 20),
    "tail": _env("FDX_SV_TAIL", True),
    "fade_ms": _env("FDX_SV_FADE_MS", 6.0),
}
ACTIVE_RMS = 0.02       # a frame this loud is speech for the level estimate (pauses and breaths do not pull it down)
TAIL_RMS = 0.0015       # the decay frame after the last voiced one is played (faded) when it holds at least this
LEVEL_PRIOR = {"": _env("FDX_SV_LEVEL_PRIOR_DB", -20.0)}   # a voice's usual speech level, learned as lines finish
FADE_N = int(24000 * AUDIO["fade_ms"] / 1000)
_FADE_IN = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, FADE_N, dtype=np.float32))).astype(np.float32) if FADE_N else None
_FADE_TAIL = (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, 1920, dtype=np.float32))).astype(np.float32)


def _shelf_coefs(db: float, fc: float, sr: int = 24000):
    """RBJ high shelf (S = 1): +db above fc."""
    a = 10 ** (db / 40)
    w0 = 2 * np.pi * fc / sr
    cs, sn = np.cos(w0), np.sin(w0)
    al = sn / 2 * np.sqrt(2)
    b = [a * ((a + 1) + (a - 1) * cs + 2 * np.sqrt(a) * al), -2 * a * ((a - 1) + (a + 1) * cs),
         a * ((a + 1) + (a - 1) * cs - 2 * np.sqrt(a) * al)]
    d = [(a + 1) - (a - 1) * cs + 2 * np.sqrt(a) * al, 2 * ((a - 1) - (a + 1) * cs),
         (a + 1) - (a - 1) * cs - 2 * np.sqrt(a) * al]
    return np.array(b) / d[0], np.array(d) / d[0]


SHELF = _shelf_coefs(AUDIO["shelf_db"], AUDIO["shelf_hz"]) if AUDIO["shelf_db"] else None

# ---------------------------------------------------------------------------------------------------------------
# counters (never keys)
STATS = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "sessions": 0, "sessions_open": 0, "steps": 0, "frames_out": 0,
         "lines": 0, "lines_done": 0, "lines_cancelled": 0, "lines_failed": 0, "lines_truncated": 0,
         "tts_requests": 0, "tts_ok": 0, "tts_errors": 0, "tts_aborted": 0, "tts_errors_by": {}, "last_error": "",
         "cache_hits": 0, "cache_joins": 0, "cache_entries": 0, "cache_audio_s": 0.0, "warmed": 0,
         "underrun_steps": 0, "words_sent": 0, "words_flushed_at_done": 0, "bad_audio": 0, "unknown_kinds": 0,
         "first_chunk_ms": [], "first_audio_ms_cold": [], "first_audio_ms_cached": []}


def _keep(lst: list, v: float, n: int = 400):
    lst.append(round(v, 1))
    del lst[:-n]


def _pct(lst: list) -> dict:
    if not lst:
        return {"n": 0}
    a = np.asarray(lst, dtype=float)
    return {"n": len(a), "p50": round(float(np.percentile(a, 50)), 1), "p95": round(float(np.percentile(a, 95)), 1),
            "min": round(float(a.min()), 1), "max": round(float(a.max()), 1)}


def _fail(why: str, detail: str = ""):
    STATS["tts_errors"] += 1
    STATS["tts_errors_by"][why] = STATS["tts_errors_by"].get(why, 0) + 1
    STATS["last_error"] = f"{why}: {detail}"[:200]


# ---------------------------------------------------------------------------------------------------------------
# text: sentences, words, and how long each word takes to say (a character weight)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=\S)")
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen " \
       "eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def num_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + " hundred" + ("" if n % 100 == 0 else " and " + num_words(n % 100))
    for div, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= div:
            rest = n % div                             # "three thousand AND fifty one" (the way it is said in India)
            return num_words(n // div) + " " + name + ("" if rest == 0 else (" and " if rest < 100 else " ") + num_words(rest))
    return str(n)


def num_words_indian(n: int) -> str:
    """10 Nov 2026 (Megh's figures are written the Indian way): crore (10^7) / lakh (10^5) / thousand / hundred, "and"
    before a last part under 100 as num_words does. 54,89,616 -> "fifty four lakh eighty nine thousand six hundred and
    sixteen"; 22,22,75,30,000 -> "two thousand two hundred and twenty two crore seventy five lakh thirty thousand".
    Below one lakh it is num_words exactly."""
    if n < 10 ** 5:
        return num_words(n)
    for div, name in ((10 ** 7, "crore"), (10 ** 5, "lakh")):
        if n >= div:
            rest = n % div
            return num_words_indian(n // div) + " " + name + ("" if rest == 0 else (" and " if rest < 100 else " ")
                                                              + num_words_indian(rest))
    return str(n)


_ORD = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
        "twelve": "twelfth"}


def ordinal_words(n: int) -> str:
    """10 Nov 2026: 1st -> "first", 5th -> "fifth", 20th -> "twentieth", 21st -> "twenty first"."""
    head, _, last = num_words(n).rpartition(" ")
    last = _ORD.get(last) or (last[:-1] + "ieth" if last.endswith("y") else last + "th")
    return (head + " " + last) if head else last


SYMBOL = {"₹": "rupees", "%": "percent", "&": "and", "+": "plus", "@": "at", "/": "slash", "#": "number"}


_SAID_FORM = re.compile(r"\d|₹|%")


def word_weight(w: str) -> float:
    """Roughly how many letters the voice says for this written word. 10 Nov 2026: a figure, a rupee amount, a year
    span or an acronym is weighed by what is really SAID for it (spoken(): "54,89,616" is nine words, "MGNREGA" seven
    letters said one by one), so the place where each word should fall in a long line is far closer and the pauses
    seen in the audio are matched to the right commas (the picture follows the voice in ?parts=whole)."""
    core = w.strip(".,;:!?\"'()[]“”‘’")
    if core and (_SAID_FORM.search(core) or (core.isupper() and len(core) > 1) or "-" in core):
        try:
            said = spoken(core).split()
        except Exception:  # noqa: BLE001
            said = []
        if said:
            return sum(3.0 if len(t) == 1 else float(len(t)) for t in said) + 1.0
    return _word_weight_plain(w)


def _word_weight_plain(w: str) -> float:
    """Roughly how many letters the voice says for this written word (plus one for the space after it)."""
    core = w.strip(".,;:!?\"'()[]“”‘’")
    extra = sum(len(v) for k, v in SYMBOL.items() if k in core)
    core = "".join(ch for ch in core if ch not in SYMBOL)
    if not core:
        return 1.0 + extra
    digits = core.replace(",", "")
    if re.fullmatch(r"\d+", digits) and len(digits) <= 12:
        return len(num_words(int(digits))) + 1.0 + extra
    if re.fullmatch(r"\d+\.\d+", digits):
        a, b = digits.split(".")
        return len(num_words(int(a[:12] or 0))) + 7 + 5 * len(b) + extra
    m = re.fullmatch(r"(\d+)(st|nd|rd|th)", core.lower())
    if m:
        return len(num_words(int(m.group(1)))) + 2.0 + extra
    if re.search(r"\d", core) or (core.isupper() and 1 < len(core) <= 5):
        # an id or an acronym is spelled out: ~3 letters per letter said, ~4.5 per digit
        return sum(4.5 if ch.isdigit() else (3.0 if ch.isalpha() else 1.0) for ch in core) + 1.0 + extra
    return len(core) + 1.0 + extra


def pause_after(w: str) -> int:
    """Expected quiet frames after a word, before any is seen (sentence end / comma)."""
    w = w.rstrip("\"')]”’")
    if w.endswith((".", "!", "?")):
        return 9
    if w.endswith((";", ":")):
        return 5
    if w.endswith(","):
        return 3
    return 0


LIST_SPLIT = re.compile(r"(?<=[,;:])\s+(?=\S)")      # "Houses completed: East Khasi Hills 12,345; ..."
_HAS_FIGURE = re.compile(r"\d|₹")


def list_items(sentence: str) -> list[str]:
    """10 Nov 2026 (the user: "0.14 crore, 2.34 crore, 5.63 crore" was said as one breath): a sentence that is a list
    of figures is said item by item, each keeping its comma (the voice gives it the rising tone of a list) with a short
    pause after it, the way a person reads figures out. A list = two or more comma / semicolon pieces, at least two of
    them holding a figure. A piece of one word stays with the next ("and", a lone figure)."""
    segs = LIST_SPLIT.split(sentence)
    if len(segs) < 2 or sum(1 for x in segs if _HAS_FIGURE.search(x)) < 2:
        return [sentence]
    out: list[str] = []
    carry = ""
    for x in segs:
        x = (carry + " " + x).strip() if carry else x
        carry = ""
        if len(x.split()) < 2:
            carry = x
            continue
        out.append(x)
    if carry:
        if out:
            out[-1] += " " + carry
        else:
            out.append(carry)
    # "... ₹5.63 crore in 2021-22 and ₹8.5 crore in 2022-23": the last item gets its own pause before "and"
    if len(out) >= 2:
        head, sep, tail = out[-1].rpartition(" and ")
        if sep and _HAS_FIGURE.search(head) and _HAS_FIGURE.search(tail) and len(head.split()) >= 2:
            out[-1:] = [head + ",", "and " + tail]
    return out


def split_parts(text: str, mode: str = "") -> list[str]:
    """The line as TTS requests: sentence by sentence (short fragments stay with their neighbour); with
    FDX_SV_LIST_SPLIT a list of figures item by item. mode "whole" (a session's ?parts=whole, Megh): the whole line as
    ONE request, so the voice runs through the answer in one breath with its own pauses and one steady prosody
    (measured 10 Nov with full cloning: commas give 300-460 ms pauses, pitch within 10 Hz between list items, and it
    generates 2x faster than it plays)."""
    text = " ".join(text.split())
    if not CFG["split"] or mode == "whole":
        return [text] if text else []
    parts: list[str] = []
    for s in SENT_SPLIT.split(text):
        if parts and (len(s.split()) < 3 or len(parts[-1].split()) < 3) and not parts[-1].endswith((",", ";")):
            parts[-1] += " " + s
        else:
            parts.append(s)
    if CFG["list_split"]:
        parts = [item for x in parts for item in list_items(x)]
    return parts


def gap_after(part_text: str) -> int:
    """Quiet frames after a part: a list item's pause, or a sentence's."""
    ms = CFG["list_gap_ms"] if part_text.rstrip().endswith((",", ";", ":")) else CFG["sent_gap_ms"]
    return max(0, int(round(ms / 80)) - 1)


# ---------------------------------------------------------------------------------------------------------------
# the voice: qwen3-tts streams, shared and cached
class Synth:
    """One TTS request: its PCM as it streams in (bytes, s16le 24 kHz), whether it finished, and its error."""

    def __init__(self, text: str, warm: bool = False, vid: str = ""):
        self.text, self.warm, self.vid = text, warm, vid
        self.key = (vid, text)
        self.raw = bytearray()
        self.odd = b""
        self.done = False
        self.error: str | None = None
        self.t_req = time.perf_counter()
        self.t_first: float | None = None
        self.users = 0
        self.task: asyncio.Task | None = None
        self.cached = False
        self._x: np.ndarray | None = None
        self._xn = -1

    @property
    def n(self) -> int:
        return len(self.raw) // 2

    def feed(self, chunk: bytes):
        b = self.odd + chunk
        cut = len(b) - (len(b) % 2)
        self.raw += b[:cut]
        self.odd = b[cut:]
        if self.t_first is None and self.n:
            self.t_first = time.perf_counter()
            _keep(STATS["first_chunk_ms"], (self.t_first - self.t_req) * 1000)

    def pcm(self) -> np.ndarray:
        if self._xn != len(self.raw):
            self._x = np.frombuffer(bytes(self.raw), dtype="<i2").astype(np.float32) / 32768.0
            self._xn = len(self.raw)
        return self._x


class Profile:
    """One voice: its reference clip (data URI), its own words for full cloning (empty = timbre only), its seed and its
    speaking style (the TTS `instructions`; empty = the server's FDX_TTS_STYLE)."""

    def __init__(self, vid: str, ref: "Path | None", clone_full: bool, seed: int, style: str = "", maya: str = ""):
        self.vid, self.seed = vid, int(seed)
        self.style = style or CFG["style"]
        self.ref_uri, self.ref_text = "", ""
        self.maya = maya
        if maya:                                  # a maya2-native voice: named, no reference clip, no seed
            self.ref_uri, self.name = "maya:" + maya, "maya2-native " + maya
            self.ident = ("maya", maya.lower())
            self.warmed = False
            return
        try:
            self.ref_uri = "data:audio/wav;base64," + base64.b64encode(ref.read_bytes()).decode()
            self.name = ref.name
        except OSError:
            self.name = f"MISSING {ref.name}"
        # FULL cloning (the reference's own words in <ref>.txt): the model continues in the reference's ACCENT and
        # manner, not only its timbre (x-vector mode: fastest, most stable)
        txt = ref.with_suffix(".txt")
        if clone_full and txt.exists():
            self.ref_text = txt.read_text(encoding="utf-8").strip()
            self.name += " (full clone)"
        self.ident = (str(ref.resolve()).lower(), bool(self.ref_text), self.seed, self.style)
        self.warmed = False


# 12 Nov 2026 (the user's team: a voice toggle with 3-4 voices, same pipeline): a session may ask ?voice=<key>. The keys
# live in voices/voices.json ({"a": {"ref": "designed_a.wav", "seed": 2026, "clone": "full", "label": ...}}), re-read
# on change, so a new voice (an Indian man, ...) is added with no code change. "clone" defaults to full (its <ref>.txt
# when present), "seed" to FDX_TTS_SEED. No ?voice = the default voice exactly as before (FDX_TTS_REF, FDX_TTS_CLONE).
VOICES_FILE = ROOT / "voices" / "voices.json"
VOICES_BUILTIN = {"a": {"ref": "designed_a.wav"}, "b": {"ref": "designed_b.wav"}, "c": {"ref": "designed_c.wav"}}
_VMAP: dict = {"mtime": "unread", "map": dict(VOICES_BUILTIN)}


def voice_map() -> dict:
    try:
        mt = VOICES_FILE.stat().st_mtime if VOICES_FILE.exists() else None
    except OSError:
        mt = None
    if mt != _VMAP["mtime"]:
        mp = dict(VOICES_BUILTIN)
        if mt is not None:
            try:
                d = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
                mp = {str(k).lower(): v for k, v in d.items()
                      if isinstance(v, dict) and (v.get("ref") or v.get("maya"))} or mp
            except (OSError, ValueError):
                pass
        _VMAP.update({"mtime": mt, "map": mp})
    return _VMAP["map"]


class Voice:
    """The process-wide TTS client: in-flight requests are shared, finished ones cached (LRU by seconds of audio).
    Requests and the cache are keyed by (voice, text): two voices never share audio."""

    def __init__(self):
        self.client: httpx.AsyncClient | None = None
        self.sem: asyncio.Semaphore | None = None
        self.cache: OrderedDict[tuple, Synth] = OrderedDict()
        self.inflight: dict[tuple, Synth] = {}
        self.profiles: dict[str, Profile] = {}
        self.ref_uri = ""
        self.ref_name = ""
        self.ref_text = ""

    def setup(self):
        self.client = httpx.AsyncClient(verify=False, timeout=httpx.Timeout(CFG["first_s"], read=30.0),
                                        limits=httpx.Limits(max_connections=16, max_keepalive_connections=8))
        self.sem = asyncio.Semaphore(int(CFG["concurrency"]))
        if CFG["engine"] == "maya":
            d = Profile("", None, False, -1, maya=CFG["maya_voice"])
        else:
            d = Profile("", Path(CFG["ref"]), (os.environ.get("FDX_TTS_CLONE") or "").lower() == "full", CFG["seed"])
        self.profiles[""] = d
        self.ref_uri, self.ref_name, self.ref_text = d.ref_uri, d.name, d.ref_text

    def resolve(self, key: str) -> str:
        """?voice=<key> -> the id the cache uses: "" (the default) for no key, an unknown key, or a key whose clip,
        clone mode and seed are the default's (they would sound the same, so they share its warmed lines)."""
        key = (key or "").strip().lower()
        spec = voice_map().get(key) if key else None
        if not spec:
            return ""
        if spec.get("maya"):
            p = Profile(key, None, False, -1, maya=str(spec["maya"]))
        else:
            ref = Path(spec["ref"])
            ref = ref if ref.is_absolute() else ROOT / "voices" / ref
            p = Profile(key, ref, str(spec.get("clone", "full")).lower() == "full", int(spec.get("seed", CFG["seed"])),
                        str(spec.get("style", "") or ""))
        if not p.ref_uri:
            return ""
        d = self.profiles.get("")
        if d is not None and p.ident == d.ident:
            return ""
        old = self.profiles.get(key)
        if old is None or old.ident != p.ident:
            self.profiles[key] = p
        return key

    def profile(self, vid: str) -> Profile:
        return self.profiles.get(vid) or self.profiles[""]

    def get(self, text: str, warm: bool = False, vid: str = "") -> Synth:
        key = (vid, text)
        s = self.cache.get(key)
        if s is not None:
            self.cache.move_to_end(key)
            if not warm:
                STATS["cache_hits"] += 1
                s.users += 1
            return s
        s = self.inflight.get(key)
        if s is not None:
            if warm:
                s.warm = True
            else:
                STATS["cache_joins"] += 1
                s.users += 1
            return s
        s = Synth(text, warm, vid)
        s.users = 0 if warm else 1
        self.inflight[key] = s
        s.task = asyncio.create_task(self._run(s))
        return s

    def release(self, s: Synth):
        """A line no longer needs `s`: an unfinished stream nobody else wants is aborted."""
        s.users = max(0, s.users - 1)
        if s.users == 0 and not s.done and not s.warm and s.task is not None and not s.task.done():
            s.task.cancel()                        # a task cancelled before it ran never reaches its own `finally`
            s.error, s.done = s.error or "aborted", True
            if self.inflight.get(s.key) is s:
                self.inflight.pop(s.key, None)
            STATS["tts_aborted"] += 1

    async def _run(self, s: Synth):
        try:
            async with self.sem:
                if s.users == 0 and not s.warm:
                    raise asyncio.CancelledError
                s.t_req = time.perf_counter()
                STATS["tts_requests"] += 1
                body = await self._fetch_guarded(s)
                del body
            if not s.n:
                raise RuntimeError("empty audio")
            s.done = True
            STATS["tts_ok"] += 1
            self._store(s)
        except asyncio.CancelledError:
            s.error = s.error or "aborted"
            s.done = True
        except Exception as e:  # noqa: BLE001
            why = s.error or type(e).__name__
            s.error = why
            s.done = True
            _fail(why, str(e)[:160])
        finally:
            if self.inflight.get(s.key) is s:
                self.inflight.pop(s.key, None)

    async def _fetch_guarded(self, s: Synth):
        """The stream, with the first-chunk deadline: no audio within first_s = a failure (the session never stalls)."""
        task = asyncio.create_task(self._fetch(s))
        t_end = time.perf_counter() + CFG["first_s"]
        try:
            while not task.done() and s.t_first is None:
                left = t_end - time.perf_counter()
                if left <= 0:
                    s.error = "timeout"
                    task.cancel()
                    raise TimeoutError(f"no audio within {CFG['first_s']} s")
                await asyncio.wait({task}, timeout=min(left, 0.05))
            await asyncio.wait_for(task, CFG["total_s"])
        except asyncio.CancelledError:
            task.cancel()
            raise
        return None

    async def _fetch(self, s: Synth):
        prof = self.profile(s.vid)
        if prof.maya:
            return await self._fetch_maya(s, prof)
        keys = key_env()
        url, key = keys.get("FDX_GATEWAY_URL", ""), keys.get("FDX_TTS_KEY", "")
        if not url or not key:
            s.error = "not_configured"
            raise RuntimeError("FDX_GATEWAY_URL / FDX_TTS_KEY not set")
        prof = self.profile(s.vid)
        if not prof.ref_uri:
            s.error = "no_reference"
            raise RuntimeError("reference clip missing")
        body = {"model": CFG["model"], "input": spoken(s.text), "response_format": "pcm", "stream": True, "stream_format": "audio",
                "task_type": "Base", "language": CFG["language"], "max_new_tokens": 2048, "ref_audio": prof.ref_uri,
                "x_vector_only_mode": True, "instructions": prof.style}
        if prof.ref_text:
            body.update({"x_vector_only_mode": False, "ref_text": prof.ref_text})
        if prof.seed >= 0:
            # 10 Nov 2026 (the user: "the pitch goes high, goes low, the voice feels different every line or two"):
            # every phrase is its own request, and an unseeded request draws a new prosody each time (measured: median
            # pitch 169-222 Hz across the phrases of one answer). One fixed seed + full cloning: 183-211 Hz, level
            # within ~1 dB (harness/megh/probe_voice_pitch.py, probe_voice_clone.py). The gateway honours the seed.
            body["seed"] = prof.seed                  # the voice's own seed (voices.json; default FDX_TTS_SEED)
        try:
            async with self.client.stream("POST", url.rstrip("/") + "/audio/speech", json=body,
                                          headers={"Authorization": f"Bearer {key}"}) as r:
                if r.status_code != 200:
                    s.error = f"http_{r.status_code}"
                    await r.aread()
                    raise RuntimeError(f"HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "")
                if ctype.startswith(("application/json", "text/")):
                    s.error = "not_audio"
                    await r.aread()
                    raise RuntimeError(f"content-type {ctype}")
                async for ch in r.aiter_raw():
                    if ch:
                        s.feed(ch)
        except httpx.HTTPError as e:
            s.error = s.error or ("connect" if isinstance(e, httpx.ConnectError) else
                                  "timeout" if isinstance(e, httpx.TimeoutException) else "http")
            raise

    async def _fetch_maya(self, s: Synth, prof: "Profile"):
        mc = maya_cfg()
        if not mc["MAYA_TTS_URL"] or not mc["MAYA_TTS_API_KEY"]:
            s.error = "not_configured"
            raise RuntimeError("MAYA_TTS_URL / MAYA_TTS_API_KEY not set")
        body = {"model": mc["MAYA_TTS_MODEL"], "input": spoken(s.text), "voice": prof.maya}
        head = bytearray()
        started = False
        try:
            async with self.client.stream("POST", mc["MAYA_TTS_URL"], json=body,
                                          headers={"Authorization": f"Bearer {mc['MAYA_TTS_API_KEY']}"}) as r:
                if r.status_code != 200:
                    s.error = f"http_{r.status_code}"
                    await r.aread()
                    raise RuntimeError(f"HTTP {r.status_code}")
                ctype = r.headers.get("content-type", "")
                if ctype.startswith(("application/json", "text/")):
                    s.error = "not_audio"
                    await r.aread()
                    raise RuntimeError(f"content-type {ctype}")
                async for ch in r.aiter_raw():
                    if not ch:
                        continue
                    if started:
                        s.feed(ch)
                        continue
                    head += ch                       # the RIFF header (its length is unset while streaming): PCM
                    i = head.find(b"data")           # starts 8 bytes after the "data" tag
                    if i >= 0 and len(head) >= i + 8:
                        started = True
                        rest = bytes(head[i + 8:])
                        if rest:
                            s.feed(rest)
                    elif len(head) > 4096:           # no RIFF header at all: raw PCM
                        started = True
                        s.feed(bytes(head))
        except httpx.HTTPError as e:
            s.error = s.error or ("connect" if isinstance(e, httpx.ConnectError) else
                                  "timeout" if isinstance(e, httpx.TimeoutException) else "http")
            raise

    def _store(self, s: Synth):
        s.cached = True
        self.cache[s.key] = s
        self.cache.move_to_end(s.key)
        total = sum(x.n for x in self.cache.values()) / RATE
        while total > CFG["cache_s"] and len(self.cache) > 1:
            _, old = self.cache.popitem(last=False)
            total -= old.n / RATE
        STATS["cache_entries"] = len(self.cache)
        STATS["cache_audio_s"] = round(total, 1)

    async def warm(self, texts: list[str], vid: str = ""):
        prof = self.profiles.get(vid)
        if prof is not None:
            prof.warmed = True
        for t in texts:
            for p in split_parts(t):
                if p and (vid, p) not in self.cache:
                    s = self.get(p, warm=True, vid=vid)
                    if s.task:
                        await asyncio.wait({s.task})
                    if not s.error:
                        STATS["warmed"] += 1


VOICE = Voice()


# ---------------------------------------------------------------------------------------------------------------
# a line: its sentences (parts), each played from its own stream, and the word timing estimate
class Part:
    def __init__(self, text: str, w0: int, synth: Synth):
        self.text, self.w0, self.synth = text, w0, synth
        self.words = text.split()
        self.weights = [word_weight(w) for w in self.words]
        self.pauses = [pause_after(w) for w in self.words]
        self.origin: int | None = None       # sample where its sound begins (the leading silence is skipped)
        self.k = 0                           # next frame to play
        self.rms: list[float] = []           # per frame from origin (complete frames, or the padded last one when done)
        self.last_voiced: int | None = None
        self.end: int | None = None          # the last frame to play: the last voiced one, or the decay frame after it
        self._gain_db: float | None = None   # the loudness gain applied to the last frame (dB) and its frame index
        self._gain_k = -2
        self._learned_level = False
        self._zi = None                      # the high shelf's filter state, carried frame to frame
        self._zi_k = -2
        self.learned = False
        self.sent = 0                        # words of this part whose piece went out

    # --- the audio ---
    def _update(self):
        s = self.synth
        x = s.pcm() if s.n else np.zeros(0, np.float32)
        if self.origin is None:
            idx = np.flatnonzero(np.abs(x) > LEAD_THR)
            if len(idx):
                self.origin = max(0, int(idx[0]) - 1200)        # 50 ms before the first sound
            elif s.done:
                self.origin = 0
            else:
                return
        avail = len(x) - self.origin
        full = max(0, avail // STEP)
        while len(self.rms) < full:
            a = self.origin + STEP * len(self.rms)
            seg = x[a:a + STEP]
            self.rms.append(float(np.sqrt(np.mean(seg * seg))))
        if s.done and self.last_voiced is None:
            if avail % STEP and len(self.rms) == full:                # the padded last frame
                seg = x[self.origin + STEP * full:]
                self.rms.append(float(np.sqrt(np.sum(seg * seg) / STEP)))
            v = [i for i, r in enumerate(self.rms) if r >= VOICED]
            self.last_voiced = v[-1] if v else -1
            # 12 Nov 2026: the frame after the last voiced one still holds the word's decay (a soft final consonant,
            # the breath out); it was cut off at the frame edge (a click, a clipped ending). It is played, faded out.
            lv = self.last_voiced
            self.end = lv + 1 if (AUDIO["tail"] and lv >= 0 and lv + 1 < len(self.rms) and
                                  self.rms[lv + 1] >= TAIL_RMS) else lv

    def _level_db(self) -> float:
        """The part's speech level (dBFS RMS of its active frames) from what has arrived so far, pulled towards the
        level this voice usually has while little has arrived (so the first frames are not judged on one syllable)."""
        act = [r for r in self.rms if r >= ACTIVE_RMS]
        prior = LEVEL_PRIOR.get(self.synth.vid, LEVEL_PRIOR[""])
        # a line all here (cached, or its stream ended) is judged on itself alone: the same line = the same audio
        n0 = 0 if (self.synth.done and act) else AUDIO["prior_frames"]
        e = (sum(r * r for r in act) + n0 * 10 ** (prior / 10)) / (len(act) + n0)
        return 10 * np.log10(e + 1e-12)

    def frame(self, k: int) -> np.ndarray:
        x = self.synth.pcm()
        a = self.origin + STEP * k
        f = x[a:a + STEP]
        if len(f) < STEP:
            f = np.concatenate([f, np.zeros(STEP - len(f), np.float32)])
        if not AUDIO["on"]:
            return f
        return self._shape(f, k)

    def _shape(self, f: np.ndarray, k: int) -> np.ndarray:
        """12 Nov 2026 (the user: "crisp and clear, like another person speaking from the mic"): one loudness for
        every line (each part brought to the same speech level, the gain gliding at most AUDIO['slew_db'] per frame, so
        no pumping), a short fade-in where the sound begins and a fade-out on the tail frame (no clicks), and a soft
        ceiling (no clipping). Measured in harness/megh/probe_audio_chain.py."""
        f = f.astype(np.float32, copy=True)
        if AUDIO["level_db"] is not None:
            want = float(np.clip(AUDIO["level_db"] - self._level_db(), -AUDIO["max_cut_db"], AUDIO["max_boost_db"]))
            g0 = self._gain_db if self._gain_db is not None and self._gain_k == k - 1 else None
            sl = AUDIO["slew_first_db"] if k < 13 else AUDIO["slew_db"]
            g1 = want if g0 is None else g0 + float(np.clip(want - g0, -sl, sl))
            g0 = g1 if g0 is None else g0
            self._gain_db, self._gain_k = g1, k
            f *= (10 ** (np.linspace(g0, g1, len(f), endpoint=False, dtype=np.float32) / 20)).astype(np.float32)
            if self.synth.done and self.end is not None and k >= self.end and not self._learned_level:
                self._learned_level = True                          # this voice's usual level, for the next lines
                act = [r for r in self.rms if r >= ACTIVE_RMS]
                if len(act) >= 6:
                    lvl = 10 * np.log10(np.mean(np.square(act)) + 1e-12)
                    pr = LEVEL_PRIOR.get(self.synth.vid, LEVEL_PRIOR[""])
                    LEVEL_PRIOR[self.synth.vid] = 0.8 * pr + 0.2 * float(lvl)
        if SHELF is not None:
            from scipy.signal import lfilter, lfilter_zi
            if self._zi is None or self._zi_k != k - 1:
                self._zi = lfilter_zi(*SHELF) * float(f[0])
            f, self._zi = lfilter(SHELF[0], SHELF[1], f, zi=self._zi)
            f = f.astype(np.float32)
            self._zi_k = k
        n = FADE_N
        if k == 0 and n:
            f[:n] *= _FADE_IN
        if self.synth.done and self.end is not None and k == self.end and self.end != self.last_voiced:
            f *= _FADE_TAIL                                          # the decay frame, faded to nothing
        c, kn = AUDIO["ceiling"], AUDIO["knee"]
        over = np.abs(f) > kn
        if over.any():
            y = np.abs(f[over])
            f[over] = np.sign(f[over]) * (kn + (c - kn) * np.tanh((y - kn) / (c - kn)))
            STATS["limited_frames"] = STATS.get("limited_frames", 0) + 1
        return f

    def ready(self) -> bool:
        """Frame k may go out now: it is in the buffer and is not the line's trailing quiet (a voiced frame follows it,
        or the stream has ended and k is not past the line's end: its last voiced frame, or the decay frame after it)."""
        self._update()
        if self.origin is None or self.k >= len(self.rms):
            return False
        if self.synth.done:
            return self.k <= (self.end if self.end is not None else -1)
        return any(r >= VOICED for r in self.rms[self.k:])

    def finished(self) -> bool:
        self._update()
        return self.synth.done and self.end is not None and self.k > self.end

    # --- the word timing ---
    def onsets(self, rate: float) -> list[float]:
        """Estimated first frame (from origin) of each word. Character weights spread over the sound, anchored at the
        pauses seen so far (a pause in the audio is matched to the punctuation nearest its expected place); past what
        is known, the learned speaking rate (frames per weight unit) extrapolates."""
        self._update()
        n = len(self.words)
        if n == 0:
            return []
        rms = self.rms
        known = len(rms)
        end = (self.last_voiced + 1) if (self.synth.done and self.last_voiced is not None and self.last_voiced >= 0) else None
        lim = end if end is not None else known
        # pauses: runs of >= 3 quiet frames with sound after them
        gaps: list[tuple[int, int]] = []
        i = 0
        while i < lim:
            if rms[i] < GAP_RMS:
                j = i
                while j < lim and rms[j] < GAP_RMS:
                    j += 1
                if j < lim and j - i >= 3 and i > 0:
                    gaps.append((i, j))
                i = j
            else:
                i += 1
        cum = np.concatenate([[0.0], np.cumsum(self.weights)])
        # anchors: (word index, frame) pairs, starting with word 0 at frame 0
        anchors: list[tuple[int, int]] = [(0, 0)]
        for g0, g1 in gaps:
            wa, fa = anchors[-1]
            best, best_err = None, None
            for b in range(wa, n - 1):                 # a pause after word b: word b+1 starts at g1
                pred = fa + rate * (cum[b + 1] - cum[wa])
                err = abs(pred - g0) + (0.0 if self.pauses[b] else 4.0)     # pauses mostly fall at punctuation
                if best_err is None or err < best_err:
                    best, best_err = b, err
            seg_len = max(4.0, g0 - fa)
            if best is not None and best_err <= max(5.0, 0.4 * seg_len):
                anchors.append((best + 1, g1))
        out = [0.0] * n
        for a_i, (wa, fa) in enumerate(anchors):
            if a_i + 1 < len(anchors):
                wb, fb = anchors[a_i + 1]
                # words wa..wb-1 share the frames fa .. (the pause before fb)
                g_start = next((g0 for g0, g1 in gaps if g1 == fb), fb)
                span, wsum = g_start - fa, cum[wb] - cum[wa]
            else:
                wb = n
                wsum = cum[n] - cum[wa]
                if end is not None:
                    span = end - fa
                else:
                    span = max(rate * wsum + sum(self.pauses[wa:n - 1]), known - fa)
            for w in range(wa, wb):
                out[w] = fa + (span * (cum[w] - cum[wa]) / wsum if wsum > 0 else 0.0)
        return out


class Line:
    def __init__(self, lid, text: str, mode: str = "", vid: str = ""):
        self.lid, self.text = lid, " ".join((text or "").split())
        self.words = self.text.split()
        self.parts: list[Part] = []
        w0 = 0
        for p in split_parts(self.text, mode):
            self.parts.append(Part(p, w0, VOICE.get(p, vid=vid)))
            w0 += len(p.split())
        self.p = 0                    # part being played
        self.wait = 0                 # quiet frames still to send before the next part (between sentences)
        self.started = False
        self.voiced_out = 0           # frames of the line's sound sent
        self.t_req = time.perf_counter()
        self.cached = all(pt.synth.cached for pt in self.parts) and bool(self.parts)
        self.first_in_queue = False
        self.error: str | None = None

    def release(self):
        for pt in self.parts:
            VOICE.release(pt.synth)


# the speaking rate, frames per weight unit, learned from finished parts (starts at ~12.5 letters per second)
RATE_EST = {"r": 0.95, "n": 0}


def learn_rate(pt: Part):
    if pt.learned or pt.synth.error or pt.last_voiced is None or pt.last_voiced < 4:
        return
    pt.learned = True
    quiet = sum(1 for r in pt.rms[:pt.last_voiced + 1] if r < GAP_RMS)
    w = sum(pt.weights)
    if w <= 0:
        return
    r = (pt.last_voiced + 1 - quiet) / w
    if 0.4 < r < 2.5:
        RATE_EST["r"] = 0.8 * RATE_EST["r"] + 0.2 * r if RATE_EST["n"] else 0.5 * RATE_EST["r"] + 0.5 * r
        RATE_EST["n"] += 1


# ---------------------------------------------------------------------------------------------------------------
# one /api/chat session
class Session:
    def __init__(self, ws, lead: int = 0, mode: str = "", vid: str = "", pcm: bool = False):
        self.ws = ws
        self.pcm = pcm                 # ?pcm=1: frames go out as raw PCM16 (0x05), not Ogg-Opus (0x01)
        self.mode = mode               # "whole": a line is one TTS request (?parts=whole)
        self.vid = vid                 # the session's voice (?voice=<key>; "" = the default voice)
        # 10 Nov 2026 (Megh): a client that asks for it (?lead_frames=N) gets up to N frames of a line AHEAD of the
        # clock, like Gemini Live's bursts, so a page that plays chunks as they come (Megh's) keeps a cushion and its
        # speech-synced captions / pictures never flap. Intended pauses are content and go ahead too; a frame not yet
        # synthesised is never replaced by silence while frames are ahead (the cushion covers it). 0 = as before.
        self.lead = max(0, min(12, int(lead)))
        self.ahead = 0
        self.starved = False
        self.writer = sphn.OpusStreamWriter(RATE)
        self.rng = np.random.default_rng()
        self.queue: deque[Line] = deque()
        self.cur: Line | None = None
        self.gap = 0                   # quiet frames still owed after the last line
        self.n = 0

    async def event(self, line: Line, name: str, **extra):
        await self.ws.send(b"\x12" + json.dumps({"id": line.lid, "event": name, **extra}).encode())

    async def run(self):
        reader = sphn.OpusStreamReader(RATE)
        buf = 0                        # the side voice does not listen: only the count of input samples clocks it
        async for msg in self.ws:
            if not isinstance(msg, (bytes, bytearray)) or not msg:
                continue
            kind, payload = msg[0], bytes(msg[1:])
            if kind == 0x01:
                try:
                    pcm = reader.append_bytes(payload)
                except Exception:  # noqa: BLE001
                    STATS["bad_audio"] += 1
                    continue
                if pcm is not None and len(pcm):
                    buf += int(np.asarray(pcm).reshape(-1).shape[0])
                while buf >= STEP:     # one step per complete 1920-sample block, exactly as opus_loop
                    buf -= STEP
                    await self.step()
            elif kind == 0x10:
                d = _json(payload)
                line = Line(d.get("id"), str(d.get("text", "")), self.mode, self.vid)
                line.first_in_queue = self.cur is None and not self.queue
                self.queue.append(line)
                STATS["lines"] += 1
            elif kind == 0x11:
                d = _json(payload)
                await self.cancel(d.get("id"), "id" in d)
            else:
                STATS["unknown_kinds"] += 1           # the base servers log an unknown kind and carry on

    async def cancel(self, target, has_id: bool):
        for line in list(self.queue):
            if not has_id or line.lid == target:
                self.queue.remove(line)
                line.release()
                STATS["lines_cancelled"] += 1
                await self.event(line, "cancelled")
        line = self.cur
        if line is not None and (not has_id or line.lid == target):
            self.cur = None
            line.release()
            STATS["lines_cancelled"] += 1
            await self.event(line, "cancelled")
            self.gap = max(self.gap, int(round(CFG["gap_ms"] / 80)))
            self.ahead = 0                             # the page drops what it held (interrupted): no debt to repay

    def close(self):
        for line in list(self.queue) + ([self.cur] if self.cur else []):
            line.release()
        self.queue.clear()
        self.cur = None

    # --- one step: exactly one audio frame --------------------------------------------------------------------
    async def step(self):
        self.n += 1
        STATS["steps"] += 1
        if self.lead <= 0:
            await self._emit(await self._line_frame())
            return
        if self.ahead > 0:
            self.ahead -= 1                            # this step's frame already went out
        else:
            await self._emit(await self._line_frame())
        while self.ahead < self.lead and (self.cur is not None or self.queue):
            self.starved = False
            n_under = STATS["underrun_steps"]
            frame = await self._line_frame(probe=True)
            if frame is None and self.starved:
                STATS["underrun_steps"] = n_under      # not an underrun: nothing was due yet
                break
            await self._emit(frame)
            self.ahead += 1
            STATS["lead_frames"] = STATS.get("lead_frames", 0) + 1

    async def _emit(self, frame):
        if frame is None:
            frame = (self.rng.standard_normal(STEP) * 1e-4).astype(np.float32)        # a silent frame
        if self.pcm:
            await self.ws.send(b"\x05" + (np.clip(frame, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())
            STATS["frames_out"] += 1
        else:
            b = self.writer.append_pcm(frame)
            if b:
                await self.ws.send(b"\x01" + b)
                STATS["frames_out"] += 1
        line = self.cur
        if line is not None and line.started and self._line_over(line):
            await self._finish(line)

    def _line_over(self, line: Line) -> bool:
        return line.p >= len(line.parts) or (line.p == len(line.parts) - 1 and line.wait == 0 and line.parts[line.p].finished())

    async def _finish(self, line: Line):
        """`done` right after the line's last voiced frame; every word still unsent goes first."""
        for pt in line.parts:
            if pt.synth.done:
                learn_rate(pt)
            while pt.sent < len(pt.words) and not line.error:
                await self._piece(line, pt, flushed=True)
        extra = {"error": line.error} if line.error else {}
        await self.event(line, "done", **extra)
        STATS["lines_done"] += 1
        if line.error:
            STATS["lines_truncated" if line.voiced_out else "lines_failed"] += 1
        self.cur = None
        line.release()
        self.gap = int(round(CFG["gap_ms"] / 80))

    async def _piece(self, line: Line, pt: Part, flushed: bool = False):
        i = pt.sent
        w = pt.words[i]
        await self.ws.send(b"\x02" + ((" " if (pt.w0 + i) > 0 else "") + w).encode("utf-8"))
        pt.sent += 1
        STATS["words_sent"] += 1
        if flushed:
            STATS["words_flushed_at_done"] += 1

    async def _line_frame(self, probe: bool = False) -> np.ndarray | None:
        line = self.cur
        if line is None:
            if self.gap > 0:
                self.gap -= 1
                return None
            if not self.queue:
                return None
            line = self.cur = self.queue.popleft()
        if not line.parts:                             # an empty line: nothing to say
            if not line.started:
                line.started = True
                await self.event(line, "start")
            return None
        pt = line.parts[line.p]
        # a TTS failure: before any sound = done with error; mid-line = the sound already here, then done with error
        if pt.synth.error and line.wait == 0 and not pt.ready():
            line.error = pt.synth.error
            if not line.started:
                line.started = True
                await self.event(line, "start")
            line.p = len(line.parts)                       # nothing more of this line: done (with the error) follows
            return None
        ready = line.wait == 0 and pt.ready()
        if not line.started and (CFG["start"] != "audio" or ready):
            line.started = True
            await self.event(line, "start")           # before every text piece and every frame of the line
        if not line.started:
            self.starved = True
            return None
        if line.wait > 0:                              # the pause between two sentences
            line.wait -= 1
            if line.wait == 0 and pt.ready():
                await self._pieces_due(line, pt, -1)       # the next sentence's first word, one step ahead
            return None
        if not ready:
            if pt.finished():                          # this sentence is over: on to the next
                while pt.sent < len(pt.words):
                    await self._piece(line, pt, flushed=True)
                learn_rate(pt)
                if line.p + 1 < len(line.parts):
                    line.p += 1
                    line.wait = gap_after(line.parts[line.p - 1].text)
                    nxt = line.parts[line.p]
                    if line.wait == 0 and nxt.ready():
                        await self._pieces_due(line, nxt, -1)
                else:
                    line.p = len(line.parts)
                return None
            if line.voiced_out or pt.k:
                STATS["underrun_steps"] += 1
            self.starved = True
            return None
        await self._pieces_due(line, pt, pt.k)
        f = pt.frame(pt.k)
        if line.voiced_out == 0:
            ms = (time.perf_counter() - line.t_req) * 1000
            if line.first_in_queue:
                _keep(STATS["first_audio_ms_cached" if line.cached else "first_audio_ms_cold"], ms)
        pt.k += 1
        line.voiced_out += 1
        return f

    async def _pieces_due(self, line: Line, pt: Part, k: int):
        """Sends every word of `pt` whose estimated onset is at most `lag` steps after frame k (in order)."""
        if pt.sent >= len(pt.words):
            return
        on = pt.onsets(RATE_EST["r"])
        lag = int(CFG["lag_steps"])
        while pt.sent < len(pt.words) and (on[pt.sent] <= k + lag or (pt.sent == 0 and k >= -1)):
            await self._piece(line, pt)


def _json(payload: bytes) -> dict:
    try:
        d = json.loads(payload or b"{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


# ---------------------------------------------------------------------------------------------------------------
# HTTP: /health, /stats; WebSocket: /api/chat
def _resp(status: int, body: dict) -> Response:
    data = json.dumps(body).encode()
    return Response(status, "OK" if status == 200 else "ERR", Headers({"Content-Type": "application/json",
                                                                      "Content-Length": str(len(data))}), data)


def stats() -> dict:
    out = {k: v for k, v in STATS.items() if not isinstance(v, list)}
    for k in ("first_chunk_ms", "first_audio_ms_cold", "first_audio_ms_cached"):
        out[k] = _pct(STATS[k])
    out["rate_frames_per_letter"] = round(RATE_EST["r"], 3)
    out["inflight"] = len(VOICE.inflight)
    return out


def health() -> dict:
    keys = key_env()
    return {"ok": True, "side": "voice", "engine": ("maya2-native" if CFG["engine"] == "maya" else CFG["model"]),
            "maya_key_set": bool(maya_cfg().get("MAYA_TTS_API_KEY")), "clock": "input", "port": PORT,
            "gateway_set": bool(keys.get("FDX_GATEWAY_URL")), "tts_key_set": bool(keys.get("FDX_TTS_KEY")),
            "reference": VOICE.ref_name, "voices": sorted(voice_map()), "split": CFG["split"], "start": CFG["start"], "sessions_open": STATS["sessions_open"]}


def process_request(connection, request):
    path = request.path.partition("?")[0]
    if path == "/health":
        return _resp(200, health())
    if path == "/stats":
        return _resp(200, stats())
    if path != "/api/chat":
        return _resp(404, {"error": "unknown path"})
    return None


async def handler(ws):
    q = dict(urllib.parse.parse_qsl(ws.request.path.partition("?")[2]))   # text_prompt / voice_prompt / seed: ignored
    try:
        lead = int(q.get("lead_frames", "0") or 0)
    except ValueError:
        lead = 0
    STATS["sessions"] += 1
    STATS["sessions_open"] += 1
    vid = VOICE.resolve(q.get("voice", ""))
    if vid and CFG["warm"] and not VOICE.profile(vid).warmed:
        asyncio.create_task(VOICE.warm(warm_texts(), vid))      # another voice's fixed lines: warmed on first use
    s = Session(ws, lead, q.get("parts", ""), vid, pcm=q.get("pcm", "") in ("1", "true", "yes"))
    try:
        await ws.send(b"\x00")
        await s.run()
    except Exception:  # noqa: BLE001
        pass
    finally:
        s.close()
        STATS["sessions_open"] -= 1


def warm_texts() -> list[str]:
    try:
        from fdx.settings import S
        t = list(S.get("lead_phrases", [])) + [S.get("listen_offer", ""), S.get("stop_ack", "")]
    except Exception:  # noqa: BLE001
        t = []
    try:
        from fdx.fixed_lines import cached_on_fact_voice
        t += sorted(cached_on_fact_voice())          # the clarifying questions: the relay sends them here, ready
    except Exception:  # noqa: BLE001
        pass
    try:
        sys.path.insert(0, str(ROOT / "megh"))
        import fixed_lines as megh_lines              # the Megh engine's holding phrases and small talk (megh/fixed_lines.py)
        t += megh_lines.warm()
    except Exception:  # noqa: BLE001
        pass
    return [x for x in dict.fromkeys(t) if x and x.strip()]


async def main():
    VOICE.setup()
    async with serve(handler, os.environ.get("FDX_BIND_HOST", "127.0.0.1"), PORT, process_request=process_request, max_size=None, ping_interval=20):
        print(f"side voice on ws://127.0.0.1:{PORT}/api/chat  (reference {VOICE.ref_name}; tts key "
              f"{'set' if key_env().get('FDX_TTS_KEY') else 'MISSING'})", flush=True)
        if CFG["warm"]:
            asyncio.create_task(VOICE.warm(warm_texts()))
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

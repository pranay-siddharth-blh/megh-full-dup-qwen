"""
Voice input (ASR) — the two faults that stopped it converting, and the guards
that keep it converting.

Neither test needs the gateway or a microphone: both faults are contract bugs
that are visible in the source.

THE REAL FAULT (web/ai_query.html, blobToWav):
  getAudioCtx() is built to create ONE AudioContext and reuse it — its own
  comment says "created once, warmed on first user gesture, and reused for every
  later decode". blobToWav's `finally` then called ctx.close(), destroying it
  after every conversion. The next recording therefore got a brand-new context,
  which starts SUSPENDED; blobToWav only resumes it best-effort
  (`.catch(() => {})`), so decodeAudioData threw, blobToWav rejected, and the
  caller silently fell back to sending the raw webm/opus blob:

      try { out = await blobToWav(blob); }
      catch (e) { console.warn('WAV conversion failed, sending original:', e); }

  Verified against the live deployment, that fallback cannot work — the ASR is
  strict about format, not just container:

      webm/opus            -> 400 "Invalid or unsupported audio file."
      22.05 kHz mono WAV   -> 400 "Invalid or unsupported audio file."
      16 kHz mono WAV      -> 200 "How many producer groups were paid under
                                   Focus Legacy?"

  So the WAV conversion is load-bearing, and closing the context silently
  disabled it from the second recording onward.

THE CONTRACT MISMATCH (app/routers/query.py):
  The UI has always sent a `language` form field; transcribe() never declared
  it, so FastAPI dropped it. Forwarding it is right, but it must be validated:
  the gateway 400s on an unknown code (`kha`, `gar` — both offered in the UI's
  own language switcher) and that 400 surfaces as an unexplained 502.
"""
import inspect
from pathlib import Path

import pytest

from app import llm
from app.llm import _ASR_LANGUAGES, _asr_language

# The chat UI is the React app (frontend/, D-038). Its voice code, API calls,
# overlay markup and stylesheet are read together, as the one page used to be.
_FRONT = Path(__file__).resolve().parents[1] / "frontend" / "src"
_UI_FILES = [_FRONT / "chat" / "useVoice.js", _FRONT / "chat" / "api.js", _FRONT / "chat" / "constants.js",
             _FRONT / "chat" / "App.jsx", _FRONT / "styles" / "chat.css"]


class _UiSource:
    @staticmethod
    def read_text(encoding="utf-8"):
        return "\n".join(p.read_text(encoding=encoding) for p in _UI_FILES)


_UI = _UiSource()


def _fn(name: str, end_marker: str) -> str:
    """The source of one JS function, sliced on real boundaries.

    The earlier version of these tests took a fixed 3000-character window,
    which silently stopped covering the end of blobToWav as soon as the
    function grew — the ctx.suspend() assertion started failing on correct
    code. Slice to the next function instead."""
    html = _UI.read_text(encoding="utf-8")
    start = html.index(name)
    return html[start:html.index(end_marker, start)]


def _after_parts(body: str, *parts: str) -> int:
    """Index just past `parts` written in a row in `body`, any whitespace
    allowed between consecutive parts (whitespace-tolerant, as before);
    -1 when they do not occur."""
    start = body.find(parts[0])
    while start != -1:
        i = start + len(parts[0])
        for part in parts[1:]:
            while i < len(body) and body[i].isspace():
                i += 1
            if not body.startswith(part, i):
                break
            i += len(part)
        else:
            return i
        start = body.find(parts[0], start + 1)
    return -1


def _number_after(body: str, *parts: str, close: str = ")") -> str | None:
    """The [0-9.]+ literal right after `parts`, when it is followed by `close`."""
    i = _after_parts(body, *parts)
    while i != -1:
        j = i
        while j < len(body) and (body[j].isdigit() or body[j] == "."):
            j += 1
        if j > i and body.startswith(close, j):
            return body[i:j]
        # try the next occurrence of the same prefix
        nxt = _after_parts(body[i:], *parts)
        i = -1 if nxt == -1 else i + nxt
    return None


def _blob_to_wav() -> str:
    return _fn("async function blobToWav(", "export function useVoice(")


def _send_audio() -> str:
    return _fn("const sendAudio = useCallback(", "const startMic = useCallback(")


# ── the real fault: the shared AudioContext must survive a conversion ───────
def test_blob_to_wav_does_not_close_the_shared_audio_context():
    """Closing it broke every recording after the first."""
    body = _blob_to_wav()
    assert "ctx.close()" not in body, (
        "blobToWav closes the shared AudioContext; the next recording then gets "
        "a suspended context, decodeAudioData throws, and the caller silently "
        "uploads raw webm/opus, which the ASR rejects with a 400"
    )
    assert "ctx.suspend()" in body, (
        "the hardware should still be released between recordings — suspend, "
        "which keeps the context reusable, rather than close"
    )


def test_get_audio_ctx_is_still_the_single_shared_context():
    """The fix relies on getAudioCtx()'s reuse contract; keep it intact."""
    html = _UI.read_text(encoding="utf-8")
    assert "let audioCtx = null;" in html
    assert "function getAudioCtx()" in html
    # blobToWav must go through it rather than constructing its own.
    body = _blob_to_wav()
    assert "getAudioCtx()" in body
    assert "new AudioContext" not in body


def test_wav_conversion_targets_16k_mono():
    """The ASR rejects 22.05 kHz WAV outright (verified live), so the exact
    output format of blobToWav is what makes voice input work at all."""
    body = _blob_to_wav()
    assert "const RATE = 16000" in body
    # mono: one channel in the WAV header
    assert _after_parts(body, "view.setUint16(22,", "1,", "true)") != -1, "not mono"


# ── the contract mismatch: `language` is sent, accepted, and made safe ──────
def test_ui_sends_a_language_field():
    html = _UI.read_text(encoding="utf-8")
    assert "form.append('language'" in html


def test_transcribe_accepts_the_language_field():
    """An undeclared form field is silently dropped by FastAPI."""
    from app.routers.query import transcribe

    assert "language" in inspect.signature(transcribe).parameters


def test_call_asr_forwards_a_validated_language():
    src = inspect.getsource(llm.call_asr)
    assert '"language"' in src, "language is not sent to the gateway"
    assert "_asr_language(" in src, "language is forwarded without validation"


@pytest.mark.parametrize("value", ["kha", "gar", "xx", "", "   ", None])
def test_unsupported_languages_fall_back_to_en(value):
    """kha/gar are offered by the UI's own language switcher and are BOTH hard
    400s at the gateway ("Unsupported language"). A hint the model does not need
    must never be able to fail the call."""
    assert _asr_language(value) == "en"


@pytest.mark.parametrize("value", ["en", "EN", " en ", "hi", "fr"])
def test_supported_languages_are_passed_through(value):
    assert _asr_language(value) == value.strip().lower()


def test_language_set_covers_what_the_ui_can_emit():
    """VOICE_LANG maps every UI language to a code; each must either be
    supported or normalise to en — never reach the gateway raw."""
    html = _UI.read_text(encoding="utf-8")
    start = html.find("const VOICE_LANG = {")
    end = html.find("}", start) if start != -1 else -1
    assert start != -1 and end != -1, "VOICE_LANG not found"
    body = html[start + len("const VOICE_LANG = {"):end]
    codes = []
    for piece in body.split(":")[1:]:          # each value after a ':'
        piece = piece.lstrip()
        if not piece.startswith("'"):
            continue
        j = 1
        while j < len(piece) and (("a" <= piece[j] <= "z") or piece[j] == "-"):
            j += 1
        if j > 1 and piece.startswith("'", j):
            codes.append(piece[1:j])
    for code in codes:
        assert _asr_language(code) in _ASR_LANGUAGES


# ── the hallucination fault: silent audio was uploaded and answered ─────────
# Reported: the user speaks, and "I'm not sure." lands in the composer.
# Reproduced against the live deployment with 3-second 16 kHz mono WAVs that are
# all IDENTICAL in size (96,044 bytes), so no size-based check can tell them
# apart:
#     digital silence   -> {"text": "I'm not sure."}   <-- the reported string
#     very quiet noise  -> {"text": "I'm not sure."}
#     louder noise      -> {"text": "Okay."}
# Whisper-family models never return "" for non-speech — they emit a short,
# confident phrase. So silent audio becomes WRONG TEXT, not a visible error.
#
# It reached the ASR because the only guard was `blob.size < 1200`, applied
# AFTER the WAV conversion. Uncompressed 16 kHz 16-bit PCM is 32,000 bytes per
# second, so 1,200 bytes is ~36 ms: the check tests DURATION, not content, and
# anything longer than a blink passes however silent it is.
def test_blob_to_wav_measures_signal_level():
    body = _blob_to_wav()
    assert "audioPeak" in body and "audioRms" in body, (
        "blobToWav must expose the signal level; it is the only place the "
        "decoded PCM is available"
    )
    assert "Math.sqrt" in body, "RMS is not computed"


def test_only_digital_silence_is_refused_before_upload():
    """The browser may refuse only a clip with essentially no signal (muted mic).
    The old bar, peak < 0.02 && rms < 0.002, refused real quiet speech the ASR
    reads correctly (speech peak 0.015 over a quiet room -> "How many
    beneficiaries?"), and it let steady room noise through anyway, which is how
    "Okay." reached the composer. Noise vs speech is decided server-side."""
    body = _send_audio()
    assert "audioPeak" in body, "the caller must still refuse a muted mic"
    bar = _number_after(body, "if (peak !== null && peak < ")
    assert bar, "the silence guard must test the peak alone, failing open when it is missing"
    assert float(bar) <= 0.005, "the bar is high enough to refuse quiet real speech"
    assert "rms < 0.002" not in body


def test_size_guard_is_documented_as_a_duration_check():
    """It reads like a content check and is not one; the comment must say so,
    or the next reader will trust it again."""
    body = _send_audio()
    assert "DURATION" in body


# ── "I asked how many beneficiaries, it typed 'Okay.'" (2026-09-25) ────────────
# The browser path was verified end to end in headless Chrome (real startMic ->
# blobToWav on a fake mic playing the question): the WAV transcribes correctly.
# So "Okay." means the recording held no speech (room noise, wrong input
# device) and the ASR answered it with a stock phrase. Measured live on 40
# speech-free clips (white/brown/hum/clicks/breath, peak 0.001-0.06, 1.5 s/4 s):
#     "Okay." 22   "I'm not sure." 11   "Oh." 4   "Oh, yeah." 3
from app import asr_guard  # noqa: E402


@pytest.mark.parametrize("text", [
    "Okay.", "I'm not sure.", "Oh.", "Oh, yeah.", "okay", "OK!", "I’m not sure",
    "", "   ", "Thank you.",
])
def test_measured_no_speech_outputs_are_withheld(text):
    assert asr_guard.is_no_speech(text)


@pytest.mark.parametrize("text", [
    "How many beneficiaries?", "How many?", "Okay, how many beneficiaries are there?",
    "yes", "No.", "Focus Legacy", "Ri Bhoi",
])
def test_real_questions_and_clarification_answers_pass(text):
    """Only a transcript that is WHOLLY a stock phrase is withheld; "yes"/"no"
    answer the chatbot's clarifications and must survive."""
    assert not asr_guard.is_no_speech(text)


def _upload(data: bytes):
    import io
    from fastapi import UploadFile
    return UploadFile(file=io.BytesIO(data), filename="audio.wav")


def test_transcribe_withholds_a_no_speech_answer(monkeypatch):
    import asyncio
    from app.routers import query

    async def fake_asr(audio, filename, language="en"):
        return "Okay."
    monkeypatch.setattr(query.llm, "call_asr", fake_asr)
    out = asyncio.run(query.transcribe(file=_upload(b"RIFF...."), language="en", device="", scope=None))
    assert out == {"text": "", "no_speech": True}


def test_transcribe_returns_a_real_transcript(monkeypatch):
    import asyncio
    from app.routers import query

    async def fake_asr(audio, filename, language="en"):
        return "How many beneficiaries?"
    monkeypatch.setattr(query.llm, "call_asr", fake_asr)
    out = asyncio.run(query.transcribe(file=_upload(b"RIFF...."), language="en", device="", scope=None))
    assert out == {"text": "How many beneficiaries?"}


def test_ui_reports_no_speech_instead_of_typing_it():
    body = _send_audio()
    i_flag, i_fill = body.index("data.no_speech"), body.index("onTranscript(transcript)")
    assert i_flag < i_fill, "no_speech must be handled before the transcript is typed"
    assert "micHint()" in body, "the message should name the input device in use"


# ── vocabulary prompt: its echo is the no-speech signal ──────────────────────
# Measured live: with a prompt, speech-free audio (silence, white noise, a
# Bluetooth headset's room tone) comes back as the prompt VERBATIM; real speech
# ("How many beneficiaries?", clean and over office chatter) is unchanged.
from app.config import settings  # noqa: E402


def test_call_asr_sends_the_vocabulary_prompt():
    src = inspect.getsource(llm.call_asr)
    assert 'form["prompt"] = settings.ASR_PROMPT' in src


def test_prompt_is_short_enough_not_to_snap_to_wrong_blocks():
    """All 70 blocks in the prompt turned Mawkyrwat into "Mawkynrew" and Nongpoh
    into "North Garo Hills"; districts only is the measured-safe size."""
    assert "Mawkyrwat" not in settings.ASR_PROMPT and "Nongpoh" not in settings.ASR_PROMPT
    assert "East Khasi Hills" in settings.ASR_PROMPT and "Ri Bhoi" in settings.ASR_PROMPT


def test_verbatim_and_partial_prompt_echo_is_detected():
    p = settings.ASR_PROMPT
    assert asr_guard.is_prompt_echo(p, p)
    assert asr_guard.is_prompt_echo(p[: len(p) // 3], p)
    assert asr_guard.is_prompt_echo("Districts: East Khasi Hills, West Khasi Hills, South West Khasi Hills, Eastern", p)


@pytest.mark.parametrize("text", [
    "How many beneficiaries?",
    "Compare East Khasi Hills and West Khasi Hills disbursement",
    "How many producer groups in Ri Bhoi under Focus Legacy?",
    "List beneficiaries in East Garo Hills, West Garo Hills and North Garo Hills",
])
def test_real_questions_naming_prompt_words_are_not_echo(text):
    assert not asr_guard.is_prompt_echo(text, settings.ASR_PROMPT)


def test_transcribe_withholds_a_prompt_echo(monkeypatch):
    import asyncio
    from app.routers import query

    async def fake_asr(audio, filename, language="en"):
        return settings.ASR_PROMPT
    monkeypatch.setattr(query.llm, "call_asr", fake_asr)
    out = asyncio.run(query.transcribe(file=_upload(b"RIFF...."), language="en", device="", scope=None))
    assert out == {"text": "", "no_speech": True}


def test_debug_capture_saves_wav_and_answer(monkeypatch, tmp_path):
    import asyncio, json
    from app.routers import query

    async def fake_asr(audio, filename, language="en"):
        return "How many beneficiaries?"
    monkeypatch.setattr(query.llm, "call_asr", fake_asr)
    monkeypatch.setattr(query.settings, "ASR_DEBUG_DIR", str(tmp_path))
    asyncio.run(query.transcribe(file=_upload(b"RIFFdata"), language="en", device="Mic X", scope=None))
    wavs, metas = list(tmp_path.glob("*.wav")), list(tmp_path.glob("*.json"))
    assert len(wavs) == 1 and wavs[0].read_bytes() == b"RIFFdata"
    assert json.loads(metas[0].read_text(encoding="utf-8"))["device"] == "Mic X"


def test_ui_waits_for_live_audio_before_saying_speak_now():
    html = _UI.read_text(encoding="utf-8")
    start = _fn("const startMic = useCallback(", "const toggleMic = useCallback(")
    assert "Starting microphone" in start and "startMeter(stream)" in start
    assert "rms > 1e-4" in html, "readiness must be decided by real samples arriving"
    assert "openMicStream()" in start, "the remembered microphone choice must be used"


# ── the 0.48 s capture (2026-09-25) ───────────────────────────────────────────
# With ASR_DEBUG_DIR on, the user's failing attempt was saved: 15,404 bytes =
# 0.48 s, speech already under way at 0.1 s. The recording was STOPPED
# mid-word — the overlay's orb showed a microphone above "Tap the mic ... to
# stop", which reads as tap-to-talk — and the ASR answered the fragment with a
# stock phrase. The page was also a stale cached copy (no `device` field sent).
def test_fragments_under_a_second_are_not_uploaded():
    body = _send_audio()
    bar = _number_after(body, "const secs = (blob.size - 44) / 32000;", "if (secs < ")
    assert bar and float(bar) >= 1.0
    assert body.index("secs < ") < body.index("transcribe(blob"), "the guard must run before upload"


def test_mic_is_a_stop_button_while_recording():
    """The 0.48 s capture came from a button that read as tap-to-talk. The mic
    in the composer turns into an explicit stop button while recording."""
    html = _UI.read_text(encoding="utf-8")
    assert 'className="orb-stop"' in html and "'Stop recording'" in html
    assert ".mic-btn.recording" in html
    assert "Tap the mic or press Esc to stop" not in html


def test_live_dictation_is_one_request_at_a_time_and_never_after_stop():
    """Live text transcribes the recording so far while it grows; it must not
    pile up requests, and a late reply must not overwrite the final text."""
    body = _UI.read_text(encoding="utf-8")
    live = body[body.index("partialTimer.current = setInterval("):body.index("stopTimer.current = setTimeout(")]
    assert "if (busy ||" in live and "busy = true" in live and "busy = false" in live
    assert "session !== sessionRef.current || !recordingRef.current" in live
    assert "blobToWav(new Blob(chunks, { type: type() }), true)" in live   # keeps the meter's context running


def test_transcribe_has_its_own_rate_limit_bucket():
    """Live dictation sends a transcription about every 2 s; on the shared
    /api/query counter (30/min) it would use up the officer's questions."""
    from app.middleware import rate_limit
    prefixes = [r[0] for r in rate_limit._RULES]
    assert prefixes.index("/api/query/transcribe") < prefixes.index("/api/query")
    assert rate_limit.RateLimitMiddleware._rule_for("/api/query/transcribe")[0] == "/api/query/transcribe"
    assert rate_limit.RateLimitMiddleware._rule_for("/api/query")[0] == "/api/query"
    assert rate_limit.TRANSCRIBE_MAX_REQUESTS >= 60


def test_pages_are_served_no_cache():
    src = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    assert '_NO_CACHE = {"Cache-Control": "no-cache"}' in src
    # /megh-chat and /admin-ui (the portal page was removed 2026-10-07)
    assert src.count("FileResponse(f, headers=_NO_CACHE)") == 2

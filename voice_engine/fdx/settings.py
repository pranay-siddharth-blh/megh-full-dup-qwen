"""Every tunable of the sovereign pipeline in one place. Values come from fdx/settings.json (written by the safety
loop from the atlas numbers) and can be overridden by environment variables FDX_<NAME> (upper case).
Nothing here is a model setting: these are the relay's own decisions about the floor."""
from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

DEFAULTS: dict = {
    # where the upstream servers are
    "core_url": "ws://127.0.0.1:8140/api/chat",        # PersonaPlex / Moshi server (or the fake core)
    "stt_url": "ws://127.0.0.1:8142/api/asr-streaming", # Kyutai STT server (or the fake STT)
    "stt_api_key": "public_token",
    # the FACT voice (4 Nov): a streaming TTS behind the same core protocol (sidevoice/server.py, qwen3-tts). The duplex
    # core cannot say numbers, ids and names exactly (harness/diag/core_say.py: 712 -> "721", 287 -> "267", place names
    # garbled; the same lines through the TTS were heard exactly), so every RESULT line is said by this voice while the
    # core keeps listening, the lead phrases, backchannels and small talk. '' = the core says everything (as before)
    "side_url": "",
    "side_kinds": ["result"],          # which line kinds the fact voice says (when one_voice is off)
    "one_voice": True,                 # every line on the fact voice (Mitra's chosen voice); the core is the fallback
    "side_lead": True,                 # the core says a lead at once while the fact voice starts (its first audio ~1 s)
    "side_hold": True,                 # a barge HOLDS a fact-voice line (kept, unheard); "mm-hmm" -> it carries on at once
    "side_failover": True,             # a fact line the TTS fails to start (error / no audio) is said by the core instead
    "side_failover_ms": 4500,          # ... after this long with no audio (qwen3-tts first audio 2.5 s p50 / 3.5 s p95, 6 Nov)
    "instant_repeat": True,           # "say that again" replays the last fact line's own audio (no second synthesis)
    # the speculative answer synthesised early by the fact voice, held until the commit. OFF (5 Nov): first audio
    # 0.9-1.5 s, but the answer then starts before a late last word can merge ("... the most open" + "cases?" became
    # two turns), and long answers lost their 2nd sentence in 3 of 9 read-backs. Re-enable only with those fixed.
    "side_prefetch": False,
    "prefetch_guard_ms": 500,          # a prefetched answer is released only once the recogniser is this far past the
    "prefetch_guard_max_ms": 800,      # commit's own wait (at most this long): a late last word re-asks instead
    "core_recover": True,              # a core that drops (or is busy at the start) is reconnected, else the fact voice
    "core_connect_s": 8.0,             # stands in for it (same protocol): the session goes on instead of ending
    "core_reconnect_s": 6.0,
    "stt_recover": True,               # a recogniser that drops is reconnected in the same session (clock offset)
    "stt_reconnect_tries": 2,
    "ears_fallback": True,             # ... and if it stays down: batch ears (energy end of turn + qwen3-asr per turn)
    "page_idle_s": 12.0,              # no frame from the page for this long = it is gone: the session ends, the core is freed
    "late_end": True,                 # a late last word's turn ends once the recogniser is past it (not on silence, which
    "late_end_max_ms": 1500,           # never comes while she plays); the same decision keeps her answer (relay._late_same)
    "soft_hold_ms": 250,              # 2 voiced frames over Mitra hold her audio this long while the barge decides (0 = off)
    "asr_primary": True,               # dual ears: the words of every finished turn from qwen3-asr, Kyutai keeps the timing
    "asr_wait_ms": 1500,
    "asr_early_ms": 300,               # ... asked at the first this-much silence, reused if the turn ends there              # ... waited for at most this long after the turn's own waits (else Kyutai's words)
    "rescue_empty": True,             # a voiced turn the recogniser wrote NO words for is heard once by qwen3-asr
    "relisten_names": True,           # hybrid ears: a turn with a doubtful place name is heard again, primed (names_pass)
    "relisten": True,                 # a short in-scope turn that did not parse is heard again by qwen3-asr, primed (relisten.py)
    "stt_tag_session": False,          # only for the fake STT: pass the Mitra session id so it can look up the script
    "voice_prompt": "",                # PersonaPlex voice prompt file name ('' = server default)
    "seed": -1,
    "core_ext": True,                  # the core understands the Mitra extension frames (speak / cancel / event)
    # audio
    "core_rate": 24000, "browser_in_rate": 16000, "browser_out_rate": 24000, "frame_ms": 80,
    # floor control
    "free_speech": "off",              # off | backchannel | chitchat : what the core may say on its own. "off" until the real
                                       # core and the page's echo handling are proven together (review finding 11)
    "firewall_frames": 2,              # core audio held this many 80 ms frames so its text can be checked first
    "forced_tail_frames": 2,           # after a line's done, at most this many frames of acoustic tail still belong to it
    "decision_hold_ms": 1500,          # after the person stops, the core's own words wait this long for the dispatcher
    "chat_wait_ms": 700,               # chitchat: how long a small-talk turn waits for the core's own answer to begin
    "continuation_ms": 3000,           # the person cuts in within this long after their own turn ended: it was a pause, not an end
    "continuation_said_s": 1.5,        # ... and only while Mitra has said no more than this much of her answer
    "out_speech_rms": 0.012,           # core output above this is speech
    "out_end_frames": 4,               # this many quiet frames end a core utterance
    # Mitra's own listening sounds: non-committal only (never yes / sure / okay / right: those are answers)
    "backchannels": ["mm-hmm", "mhm", "uh-huh", "hmm", "i see"],
    # the person's listening sounds: said over Mitra they are not an interruption, and she carries on
    "listen_only": ["mm-hmm", "mhm", "uh-huh", "hmm", "okay", "ok", "yeah", "yes", "yep", "right", "sure", "alright",
                    "fine", "i see", "got it", "go on", "good", "great", "thanks", "thank you", "accha", "haan", "hmm okay"],
    # affirmatives: over a read-back question that was not yet heard to its end, they confirm nothing
    "affirm": ["yes", "yeah", "yep", "sure", "okay", "ok", "go ahead", "do it", "confirm", "right", "please do",
               "proceed", "yes please", "alright", "fine", "haan", "sari", "ಹೌದು", "ಸರಿ"],
    # the person's turn
    "in_speech_rms": 0.02,             # absolute floor for the person's speech
    "in_noise_mult": 3.0,              # and this many times the room's noise floor
    "floor_window_s": 2.5,             # the noise floor is a low percentile of the frame levels of the last few seconds
    "floor_pct": 15,                   # (minimum statistics: it learns under steady noise, frozen while Mitra is audible)
    "in_clock": True,                  # the relay keeps the core and the recogniser fed when the page sends nothing (mute)
    "pump_after_ms": 300,              # ... but only after this long without a frame (jitter between 85 ms frames is not mute)
    "words_quiet_ms": 800,             # energy silence may end a turn only once the recogniser has sent no word for this long
    "word_quiet_ms": 350,              # a turn is sent only once the recogniser has been quiet this long ...
    "word_wait_max_ms": 900,           # ... waiting at most this much longer than the settle
    # a listening sound over her answer: "resume" = carry on from the cut frame (5 Nov default: "mm-hmm" means "go on",
    # and with the fact voice held it is instant), "gemini" = stop + a short offer, dropping the rest (Gemini, measured 30 Oct)
    "listen_sound": "resume",
    "listen_offer": "I'm here if you have any questions.",
    # after "stop" (Gemini, atlas stop_word: median 1.4 s of speech, "Okay." to "Understood. I'm here ..."); the core takes
    # ~2.5 s to say "Understood, I'll stop there." (5 Nov), so the acknowledgement is kept to two words
    "stop_ack": "Okay.",               # (5 Nov: "Okay, stopped." still 2.2 s of speech after stop vs Gemini 1.4)
    "multi_question": True,            # two read-only questions in one breath: two decisions, both answers in one turn
    "speech_form": True,               # the core says the spoken form of a result (fdx/voice.py), the screen the full text
    "in_onset_ms": 160,
    "end_silence_ms": 700,             # silence that ends the person's turn (Gemini's relay used 700)
    "stt_pause_head": 2,               # Kyutai semantic VAD head used (0:0.5 s, 1:1 s, 2:2 s, 3:3 s)
    "stt_pause_p": 0.5,
    "stt_delay_ms": 500,               # the recogniser's text delay (stt-1b: 0.5 s): a turn waits until it PROCESSED end + this
    "incomplete_silence_ms": 1200,     # silence a turn needs when its last word leaves it unfinished ("... in", "case")
    "incomplete_long_ms": 2600,        # ... after "case" / "number" / "id": a spelled id takes ~2 s to come through
    "short_question_words": 3,         # a question this short ("how many cases?") ...
    "short_question_silence_ms": 1300, # ... needs this much silence: it is often the first half of a longer one
    "stt_tail_ms": 300,               # ... plus this for the last word (closed only once the recogniser sees what follows)
    "stt_catchup_max_ms": 2500,        # ... at most this long (a stalled recogniser cannot hold the turn)
    "stt_settle_ms": 550,              # the recogniser's own delay: wait this long after the end for the last words
    # barge-in (safety controller)
    "barge_ms": 200,                   # the person's speech over Mitra for this long cuts her (240 -> 200, 4 Nov: "stop" 463 ms vs Gemini 297)
    "echo_mult": 2.0,                  # thresholds rise by this much while Mitra is talking (laptop speaker echo)
    "barge_on_word": True,             # a recognised word over Mitra also cuts her
    # the voice of a function turn
    "lead_after_ms": 450,              # if the result is not ready by then, say a lead phrase
    "lead_phrases": ["One moment.", "Let me check.", "Just a second.", "Let me look that up."],
    "watchdog_ms": 6000,               # a forced line that never STARTS is given up (cancelled at the core) after this
    "stall_ms": 3000,                  # a started line that stops producing sound for this long is given up
    "chars_per_s": 12.0,               # spoken pace, for a line's expected length
    "pause_timeout_ms": 1800,          # after a barge-in, if the person says nothing real within this, Mitra carries on
}


def _load() -> dict:
    s = dict(DEFAULTS)
    p = HERE / "settings.json"
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    for k, v in list(s.items()):
        env = os.environ.get("FDX_" + k.upper())
        if env is None or env == "":
            continue
        if isinstance(v, bool):
            s[k] = env.lower() in ("1", "true", "yes", "on")
        elif isinstance(v, int):
            s[k] = int(env)
        elif isinstance(v, float):
            s[k] = float(env)
        elif isinstance(v, list):
            s[k] = [x.strip() for x in env.split("|") if x.strip()]
        else:
            s[k] = env
    return s


S = _load()


def reload() -> dict:
    S.clear()
    S.update(_load())
    return S


def _cast(old, v: str):
    if isinstance(old, bool):
        return v.lower() in ("1", "true", "yes", "on")
    if isinstance(old, int):
        return int(float(v))
    if isinstance(old, float):
        return float(v)
    if isinstance(old, list):
        return [x.strip() for x in v.split("|") if x.strip()]
    return v


# never changed at runtime (re-review 54): where the relay connects and with which key are set by the environment at
# start, so a token holder cannot point the relay at a remote host or read a key back
LOCKED = {"core_url", "stt_url", "stt_api_key", "stt_tag_session", "voice_prompt", "core_ext", "side_url"}
SECRET = {"stt_api_key"}


def update(changes: dict) -> dict:
    """Runtime change of known settings (debug instances, the tuning loop); `reset=1` restores the file + env values.
    LOCKED keys are refused; SECRET values are masked in what is returned."""
    if str(changes.get("reset", "")).lower() in ("1", "true"):
        reload()
    for k, v in changes.items():
        if k in S and k != "reset" and k not in LOCKED:
            S[k] = _cast(S[k], str(v))
    return {k: ("***" if k in SECRET and S[k] else v) for k, v in S.items()}

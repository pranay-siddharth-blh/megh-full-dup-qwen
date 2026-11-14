"""Voice relay limits, 14 Nov 2026 (offline; the relay alone against the fake Gemini Live server, as in
test_voice_relay_2026_11_02): the server ends a session at VOICE_MAX_SESSION_MINUTES whatever the browser does, and
/ws/voice accepts VOICE_HELLO_PER_MINUTE connections per address per minute."""
import asyncio
import dataclasses

import pytest

from app.voice import relay
from app.voice import settings as voice_settings

from tests.test_voice_relay_2026_11_02 import Page, fakes, server, _wiring  # noqa: F401 — the shared fixtures


def test_defaults_and_settings_parse(monkeypatch):
    monkeypatch.setenv("MEGH_VOICE_ENV", "no-such-file.env")
    monkeypatch.delenv("VOICE_MAX_SESSION_MINUTES", raising=False)
    monkeypatch.delenv("VOICE_HELLO_PER_MINUTE", raising=False)
    s = voice_settings.VoiceSettings(api_key="", engine="gemini", model="m", voice="v", live_url="", idle_seconds=1,
                                     max_sessions=1, tool_timeout=1)
    assert s.max_session_minutes == 60.0 and s.hello_per_minute == 60


def test_hello_limit_counts_per_address():
    relay._HELLOS.clear()
    assert not any(relay._over_hello_limit("1.2.3.4", 3, 100.0 + i) for i in range(3))
    assert relay._over_hello_limit("1.2.3.4", 3, 104.0)             # the 4th in a minute
    assert not relay._over_hello_limit("5.6.7.8", 3, 104.0)          # another address is not affected
    assert not relay._over_hello_limit("1.2.3.4", 3, 170.0)          # a minute later it is allowed again
    assert not relay._over_hello_limit("9.9.9.9", 0, 1.0)            # 0 = no limit
    relay._HELLOS.clear()


def test_over_the_limit_is_refused_with_rate(server, _wiring, monkeypatch):
    relay._HELLOS.clear()
    real = voice_settings.load

    def load():
        return dataclasses.replace(real(), hello_per_minute=2)
    monkeypatch.setattr(voice_settings, "load", load)

    async def go():
        reasons = []
        for _ in range(3):
            async with Page(server) as pg:
                e = await pg.until(lambda e: e.get("type") in ("ready", "error"))
                reasons.append(e.get("reason") or e["type"])
        return reasons
    assert asyncio.run(go()) == ["ready", "ready", "rate"]
    relay._HELLOS.clear()


def test_session_ends_at_the_time_limit(server, _wiring, monkeypatch):
    relay._HELLOS.clear()
    real = voice_settings.load

    def load():
        return dataclasses.replace(real(), max_session_minutes=1.5 / 60)   # 1.5 s
    monkeypatch.setattr(voice_settings, "load", load)

    async def go():
        async with Page(server) as pg:
            await pg.until(lambda e: e.get("type") == "ready")
            e = await pg.until(lambda e: e.get("type") == "closed", secs=10)
            return e.get("reason")
    assert asyncio.run(go()) == "session time limit"
    relay._HELLOS.clear()


@pytest.mark.parametrize("minutes", [0])
def test_no_limit_keeps_the_session(server, _wiring, monkeypatch, minutes):
    relay._HELLOS.clear()
    real = voice_settings.load
    monkeypatch.setattr(voice_settings, "load", lambda: dataclasses.replace(real(), max_session_minutes=minutes))

    async def go():
        async with Page(server) as pg:
            await pg.until(lambda e: e.get("type") == "ready")
            await asyncio.sleep(2.0)
            return [e.get("type") for e in pg.events]
    assert "closed" not in asyncio.run(go())
    relay._HELLOS.clear()

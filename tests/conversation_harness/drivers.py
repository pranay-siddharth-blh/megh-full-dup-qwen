"""
Drivers: how a scenario's turns reach the chatbot.

  InProcessDriver  the router path in this process (conversation layer -> the
                   LangGraph pipeline -> refusal restyle -> build_turn / pause
                   bookkeeping), one in-process SessionStore. Fast, shows the
                   pipeline's own decision log, but it does NOT rehydrate the
                   session from the durable snapshot the way the server does on
                   every request (live 2026-10-18: a session there holds only its
                   last turn), and it has no answer caches.
  HttpDriver       POST /api/query or /api/query/stream on a running server, with a
                   JWT minted in-process for a seeded user (the seed passwords in
                   users.yaml are not the live ones). This is the path the browser
                   takes: caches, rehydration, rate limits, streaming. Authoritative.

Both return checks.TurnRecord per turn.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid

from .checks import TurnRecord

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)


def _chips(result: dict) -> list:
    out = []
    for key in ("follow_up_options", "suggestions"):
        for o in result.get(key) or []:
            out.append(o.get("label") if isinstance(o, dict) else str(o))
    return out


def _from_result(say: str, result: dict, ms: int, status: int | None = None) -> TurnRecord:
    if result.get("route") == "clarification" or result.get("needs_clarification"):
        clar = result.get("clarification") or {}
        return TurnRecord(say=say, route="pause", answer=result.get("answer") or result.get("question") or "",
                          pause_rule=clar.get("rule"), chips=[o.get("label") if isinstance(o, dict) else str(o)
                                                               for o in clar.get("options") or []],
                          ms=ms, status=status, raw=result)
    return TurnRecord(say=say, route=result.get("route") or "error", answer=result.get("answer") or "",
                      edge_type=result.get("edge_type"), banner=result.get("scope_banner"),
                      chips=_chips(result), ms=ms, status=status, raw=result)


class InProcessDriver:
    name = "inprocess"

    def __init__(self):
        from app.session_store import SessionStore
        self.store = SessionStore(ttl=3600, max_sessions=500, max_turns=50)
        self._lifespan = None

    async def __aenter__(self):
        from app import main as app_main
        self._lifespan = app_main.lifespan(app_main.app)
        await self._lifespan.__aenter__()
        return self

    async def __aexit__(self, *exc):
        if self._lifespan is not None:
            await self._lifespan.__aexit__(*exc)

    def new_conversation(self, account: str | None = None):
        return _InProcessConversation(self.store)


class _InProcessConversation:
    def __init__(self, store):
        self.sid = "harness-" + uuid.uuid4().hex[:10]
        self.session = store.ensure(self.sid, "harness")
        self.decisions: list = []

    async def ask(self, say: str) -> TurnRecord:
        from app import conversation_layer, conversation_replies, pipeline
        from app.routers import query as router
        t0 = time.perf_counter()
        self.session.turn_context = {}
        try:
            layer = await conversation_layer.prepare_turn(self.session, say)
            if layer.response is not None:
                result = layer.response
            elif layer.multi:
                result = await conversation_layer.answer_many(
                    layer.multi, lambda x: pipeline.answer_question(x, session=self.session, scope=None))
            else:
                result = await pipeline.answer_question(layer.question, session=self.session, scope=None)
            styled = conversation_replies.restyle(self.session, say, result)
            if styled is not None:
                result = styled
            self.session.turns.append(router.build_turn(say, result))
            return _from_result(say, result, round((time.perf_counter() - t0) * 1000))
        except pipeline.ClarificationNeeded as e:
            router.remember_pause(self.session, router.pause_question(self.session, say), e)
            return TurnRecord(say=say, route="pause", answer=e.question, pause_rule=e.rule,
                              chips=[o.get("label") if isinstance(o, dict) else str(o) for o in (e.options or [])],
                              ms=round((time.perf_counter() - t0) * 1000))
        except Exception as e:  # noqa: BLE001 — recorded as a failed turn
            return TurnRecord(say=say, route="error", answer=f"{type(e).__name__}: {e}",
                              ms=round((time.perf_counter() - t0) * 1000))


async def mint_token(username: str, ttl_minutes: int = 180) -> str:
    """A JWT for a seeded user, signed with this machine's .env secret (the one the
    server uses). Needs the app DB (the user record) — run under the app lifespan."""
    from app import appdb, security
    rec = await appdb.get_user_by_username(username)
    if not rec:
        raise RuntimeError(f"no such user: {username}")
    return security.issue_token({"sub": str(rec["user_id"]), "username": rec["username"],
                                 "tenant_id": rec["tenant_id"], "role": rec["role"]}, ttl_minutes=ttl_minutes)


class HttpDriver:
    name = "http"

    def __init__(self, base_url: str = "http://127.0.0.1:8401", stream: bool = False,
                 tokens: dict | None = None, default_account: str = "superadmin", skip_cache: bool = False,
                 timeout: float = 240.0):
        self.base_url = base_url.rstrip("/")
        self.stream = stream
        self.tokens = dict(tokens or {})
        self.default_account = default_account
        self.skip_cache = skip_cache
        self.timeout = timeout
        self._client = None

    async def __aenter__(self):
        import httpx
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *exc):
        if self._client is not None:
            await self._client.aclose()

    async def ensure_token(self, account: str) -> str:
        if account in self.tokens:
            return self.tokens[account]
        from app import main as app_main
        async with app_main.lifespan(app_main.app):
            self.tokens[account] = await mint_token(account)
        return self.tokens[account]

    def new_conversation(self, account: str | None = None):
        return _HttpConversation(self, account or self.default_account)


class _HttpConversation:
    def __init__(self, driver: HttpDriver, account: str):
        self.driver = driver
        self.account = account
        self.sid = "harness-" + uuid.uuid4().hex[:10]

    async def ask(self, say: str) -> TurnRecord:
        d = self.driver
        token = await d.ensure_token(self.account)
        headers = {"Authorization": f"Bearer {token}"}
        body = {"question": say, "session_id": self.sid, "skip_cache": d.skip_cache}
        t0 = time.perf_counter()
        for attempt in range(6):
            if d.stream:
                try:
                    async with d._client.stream("POST", f"{d.base_url}/api/query/stream", json=body, headers=headers) as r:
                        if r.status_code == 429:
                            await asyncio.sleep(10)
                            continue
                        if r.status_code != 200:
                            text = (await r.aread()).decode("utf-8", "replace")
                            return TurnRecord(say=say, route="error", answer=text[:300], status=r.status_code,
                                              ms=round((time.perf_counter() - t0) * 1000))
                        async for line in r.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            ev = json.loads(line[6:])
                            if ev.get("type") == "done":
                                return _from_result(say, ev["result"], round((time.perf_counter() - t0) * 1000), 200)
                            if ev.get("type") == "error":
                                return TurnRecord(say=say, route="error", answer=str(ev.get("detail"))[:300],
                                                  status=ev.get("status"), ms=round((time.perf_counter() - t0) * 1000))
                    return TurnRecord(say=say, route="error", answer="stream ended without a done event",
                                      ms=round((time.perf_counter() - t0) * 1000))
                except Exception as e:  # noqa: BLE001
                    return TurnRecord(say=say, route="error", answer=f"{type(e).__name__}: {e}"[:300],
                                      ms=round((time.perf_counter() - t0) * 1000))
            try:
                r = await d._client.post(f"{d.base_url}/api/query", json=body, headers=headers)
            except Exception as e:  # noqa: BLE001
                return TurnRecord(say=say, route="error", answer=f"{type(e).__name__}: {e}"[:300],
                                  ms=round((time.perf_counter() - t0) * 1000))
            if r.status_code == 429:
                await asyncio.sleep(10)
                continue
            ms = round((time.perf_counter() - t0) * 1000)
            try:
                j = r.json()
            except Exception:  # noqa: BLE001
                return TurnRecord(say=say, route="error", answer=r.text[:300], status=r.status_code, ms=ms)
            if r.status_code != 200 or not isinstance(j, dict) or ("route" not in j and "needs_clarification" not in j):
                return TurnRecord(say=say, route="error", answer=str(j)[:300], status=r.status_code, ms=ms)
            return _from_result(say, j, ms, r.status_code)
        return TurnRecord(say=say, route="error", answer="rate limited (429) six times", status=429,
                          ms=round((time.perf_counter() - t0) * 1000))

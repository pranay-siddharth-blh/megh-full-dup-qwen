"""
Confirms app/middleware/rate_limit.py's per-user rate-limit key
(openspec/changes/phase-6-observability-deployment): an authenticated
caller is throttled by user identity, not shared client IP; a
missing/invalid token falls back to the existing IP-based key; and
/api/auth/login (no token exists at that point by definition) is
unaffected.

No live server, no DB — a minimal Starlette app wraps the real
RateLimitMiddleware; starlette.testclient.TestClient's default fake peer
("testclient") gives every request the same "shared IP" for free, which
is exactly the scenario this capability needs to prove doesn't collide
identities anymore.

Run: `python tests/test_rate_limit.py`, exit code 0 = pass.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app import security  # noqa: E402
from app.middleware import rate_limit as rl  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


async def _ok(_request):
    return PlainTextResponse("ok")


def _token(sub: str) -> str:
    return security.issue_token({"sub": sub})


def _run() -> None:
    print("1. TWO USERS, SAME IP — independent buckets")
    orig_rules = rl._RULES
    rl._RULES = [("/api/auth/login", rl.settings.LOGIN_RL_MAX, rl.settings.LOGIN_RL_WINDOW_SEC, False),
                 ("/api/query", 2, 60, True)]
    try:
        app = Starlette(routes=[Route("/api/query", _ok, methods=["GET"])])
        app.add_middleware(rl.RateLimitMiddleware)
        client = TestClient(app)
        tok_a, tok_b = _token("user-A"), _token("user-B")

        codes_a = [client.get("/api/query", headers={"authorization": f"Bearer {tok_a}"}).status_code
                   for _ in range(2)]
        check("user A's first 2 requests (at cap) succeed", codes_a == [200, 200], detail=str(codes_a))
        third_a = client.get("/api/query", headers={"authorization": f"Bearer {tok_a}"})
        check("user A's 3rd request is rate-limited", third_a.status_code == 429, detail=third_a.status_code)

        codes_b = [client.get("/api/query", headers={"authorization": f"Bearer {tok_b}"}).status_code
                   for _ in range(2)]
        check("user B, same IP, unaffected by user A's limit — 2 requests still succeed",
              codes_b == [200, 200], detail=str(codes_b))
    finally:
        rl._RULES = orig_rules

    print("2. SAME USER, DIFFERENT IPS — shares one bucket")
    rl._RULES = [("/api/auth/login", rl.settings.LOGIN_RL_MAX, rl.settings.LOGIN_RL_WINDOW_SEC, False),
                 ("/api/query", 2, 60, True)]
    try:
        app = Starlette(routes=[Route("/api/query", _ok, methods=["GET"])])
        app.add_middleware(rl.RateLimitMiddleware)
        client = TestClient(app)
        tok = _token("user-C")
        r1 = client.get("/api/query", headers={"authorization": f"Bearer {tok}",
                                                "x-forwarded-for": "1.2.3.4"})
        r2 = client.get("/api/query", headers={"authorization": f"Bearer {tok}",
                                                "x-forwarded-for": "5.6.7.8"})
        check("both requests (different XFF, same user) count against one bucket — both succeed",
              r1.status_code == 200 and r2.status_code == 200)
        r3 = client.get("/api/query", headers={"authorization": f"Bearer {tok}",
                                                "x-forwarded-for": "9.9.9.9"})
        check("a 3rd request from yet another IP is still rate-limited — proves shared bucket",
              r3.status_code == 429, detail=r3.status_code)
    finally:
        rl._RULES = orig_rules

    print("3. INVALID/MISSING TOKEN — falls back to IP, never errors")
    rl._RULES = [("/api/auth/login", rl.settings.LOGIN_RL_MAX, rl.settings.LOGIN_RL_WINDOW_SEC, False),
                 ("/api/query", 3, 60, True)]
    try:
        app = Starlette(routes=[Route("/api/query", _ok, methods=["GET"])])
        app.add_middleware(rl.RateLimitMiddleware)
        client = TestClient(app)
        r_no_token = client.get("/api/query")
        check("no token — request succeeds (falls back to IP, not rejected)",
              r_no_token.status_code == 200, detail=r_no_token.status_code)
        r_bad_token = client.get("/api/query", headers={"authorization": "Bearer not-a-real-jwt"})
        check("malformed token — request succeeds (falls back to IP, not a 500)",
              r_bad_token.status_code == 200, detail=r_bad_token.status_code)
        expired = security.issue_token({"sub": "user-D"}, ttl_minutes=-1)
        r_expired = client.get("/api/query", headers={"authorization": f"Bearer {expired}"})
        check("expired token — request succeeds (falls back to IP, not a 500)",
              r_expired.status_code == 200, detail=r_expired.status_code)
        # All three share the IP-based bucket (no-token, bad-token, expired-token
        # all resolve to the same IP fallback key) — cap is 2, so a 4th should 429.
        r_fourth = client.get("/api/query")
        check("a 4th IP-fallback request exceeds the shared IP bucket",
              r_fourth.status_code == 429, detail=r_fourth.status_code)
    finally:
        rl._RULES = orig_rules

    print("4. /api/auth/login — always IP-keyed, unaffected by identity")
    rl._RULES = [("/api/auth/login", 2, 60, False), ("/api/query", 30, 60, True)]
    try:
        app = Starlette(routes=[Route("/api/auth/login", _ok, methods=["POST"])])
        app.add_middleware(rl.RateLimitMiddleware)
        client = TestClient(app)
        # A bearer token on a login attempt is nonsensical but shouldn't change
        # behavior — login has no prior identity to key by, by definition.
        tok = _token("user-E")
        r1 = client.post("/api/auth/login", headers={"authorization": f"Bearer {tok}"})
        r2 = client.post("/api/auth/login")
        check("first two login attempts (mixed token presence) succeed",
              r1.status_code == 200 and r2.status_code == 200)
        r3 = client.post("/api/auth/login")
        check("third login attempt from the same IP is rate-limited",
              r3.status_code == 429, detail=r3.status_code)
    finally:
        rl._RULES = orig_rules

    print("5. _identity() UNIT BEHAVIOR")
    class _FakeHeaders(dict):
        def get(self, k, default=None):
            return dict.get(self, k.lower(), default)

    class _FakeRequest:
        def __init__(self, auth_header):
            self.headers = _FakeHeaders({"authorization": auth_header} if auth_header else {})

    check("no header -> None", rl.RateLimitMiddleware._identity(_FakeRequest(None)) is None)
    check("non-bearer scheme -> None",
          rl.RateLimitMiddleware._identity(_FakeRequest("Basic abc123")) is None)
    tok = _token("42")
    check("valid bearer token -> sub as string",
          rl.RateLimitMiddleware._identity(_FakeRequest(f"Bearer {tok}")) == "42")


_run()

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL RATE_LIMIT (per-user key, phase-6-observability-deployment) CHECKS PASSED")

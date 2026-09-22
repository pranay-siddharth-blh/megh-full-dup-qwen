"""
Rate limiting middleware (OWASP A04 / A07)
=========================================
Per-IP sliding-window limits:

  * /api/query   — MAX_REQUESTS / WINDOW_SEC   (normal traffic shaping)
  * /api/auth/login — settings.LOGIN_RL_MAX / settings.LOGIN_RL_WINDOW_SEC
                      (brute-force throttle; much stricter)

The client IP is resolved via app.net.client_ip, which only trusts
X-Forwarded-For from a configured proxy — a caller cannot spoof XFF to get a
fresh bucket.

Backend:
  * "memory" (default) — an in-process deque per IP. Per worker, so 2 workers ×
    2 VMs = 4 independent counters; fine for coarse shaping.
  * "redis"  — a shared sorted-set window (reuses REDIS_URL via app.cache), so
    the limit holds across every worker. Any Redis error degrades to memory for
    that request — it never 500s.

Per-user vs. per-IP key (openspec/changes/phase-6-observability-deployment):
a request carrying a valid, unexpired bearer token is keyed by its
authenticated user id ("user:<sub>"), not client IP — two users sharing an
office NAT no longer share one throttle bucket, and one user keeps a
single bucket across networks. A missing or invalid token (no token,
malformed, bad signature, wrong issuer, expired) falls back to the
existing IP-based key ("ip:<ip>") — cheaply, via app.security.decode_token
(signature/issuer/expiry only, no database call), never rejecting the
request itself: that stays the route's own auth dependency's job.
"""
import logging
import time
from collections import defaultdict, deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app import security
from app.config import settings
from app.deps import _bearer
from app.net import client_ip

logger = logging.getLogger(__name__)

MAX_REQUESTS = 30   # /api/query, per window
WINDOW_SEC   = 60   # rolling window in seconds

# (path prefix, max, window, key_by_user) — first match wins. Order matters:
# the more specific /api/auth/login prefix is checked before the broad
# /api/query one. `key_by_user=False` for login: a caller authenticating for
# the first time has no meaningful prior identity, so this bucket stays
# IP-only regardless of whether a (nonsensical) bearer token is present —
# per openspec/changes/phase-6-observability-deployment's rate-limiting spec.
_RULES: list[tuple[str, int, int, bool]] = [
    ("/api/auth/login", settings.LOGIN_RL_MAX, settings.LOGIN_RL_WINDOW_SEC, False),
    ("/api/query", MAX_REQUESTS, WINDOW_SEC, True),
]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window per-IP limiter. Over the limit in the window -> 429."""

    def __init__(self, app):
        super().__init__(app)
        # keyed by "bucket|ip" so the two rules never share a window
        self._windows: dict[str, deque] = defaultdict(deque)

    @staticmethod
    def _rule_for(path: str) -> tuple[str, int, int, bool] | None:
        for prefix, cap, window, key_by_user in _RULES:
            if path.startswith(prefix):
                return prefix, cap, window, key_by_user
        return None

    @staticmethod
    def _identity(request: Request) -> str | None:
        """The authenticated user id for this request's bearer token, or
        None on any missing/invalid token — cheap (signature/issuer/expiry
        only, no DB call) and never raises; a bad token is not this
        layer's concern, it just means "no identity", falling back to IP."""
        token = _bearer(request.headers.get("authorization"))
        if not token:
            return None
        try:
            claims = security.decode_token(token)
        except security.JWTError:
            return None
        sub = claims.get("sub")
        return str(sub) if sub is not None else None

    async def dispatch(self, request: Request, call_next):
        rule = self._rule_for(request.url.path)
        if rule is None:
            return await call_next(request)
        bucket, cap, window, key_by_user = rule

        ip = client_ip(request)
        user_id = self._identity(request) if key_by_user else None
        key = f"{bucket}|user:{user_id}" if user_id else f"{bucket}|ip:{ip}"
        now = time.monotonic()

        allowed, retry_after, used = await self._check(key, cap, window, now)
        if not allowed:
            logger.warning("Rate limit hit: bucket=%s key=%s ip=%s used=%s", bucket, key, ip, used)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded ({cap} requests / {window}s). "
                              f"Please wait {retry_after}s.",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"]     = str(cap)
        response.headers["X-RateLimit-Remaining"] = str(max(0, cap - used))
        response.headers["X-RateLimit-Window"]    = str(window)
        return response

    async def _check(self, key: str, cap: int, window: int, now: float):
        """Returns (allowed, retry_after_seconds, used_count)."""
        if settings.RATELIMIT_BACKEND == "redis" and settings.REDIS_URL:
            got = await self._check_redis(key, cap, window)
            if got is not None:
                return got
        return self._check_memory(key, cap, window, now)

    # ── in-process ────────────────────────────────────────────────────────
    def _check_memory(self, key: str, cap: int, window: int, now: float):
        dq = self._windows[key]
        while dq and now - dq[0] > window:
            dq.popleft()
        if len(dq) >= cap:
            retry_after = int(window - (now - dq[0])) + 1
            return False, retry_after, len(dq)
        dq.append(now)
        if len(dq) > cap * 2:
            while len(dq) > cap:
                dq.popleft()
        return True, 0, len(dq)

    # ── shared (Redis) ───────────────────────────────────────────────────
    async def _check_redis(self, key: str, cap: int, window: int):
        """Sorted-set sliding window. None => Redis unavailable, caller falls
        back to memory."""
        try:
            from app.cache import _redis

            r = await _redis()
            if r is None:
                return None
            rk = f"{settings.REDIS_CACHE_PREFIX}rl:{key}"
            now = time.time()
            member = f"{now:.6f}"
            async with r.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(rk, 0, now - window)
                pipe.zadd(rk, {member: now})
                pipe.zcard(rk)
                pipe.expire(rk, window)
                _, _, count, _ = await pipe.execute()
            if count > cap:
                # roll our own add back off and report the oldest entry's age
                await r.zrem(rk, member)
                oldest = await r.zrange(rk, 0, 0, withscores=True)
                retry_after = window
                if oldest:
                    retry_after = int(window - (now - oldest[0][1])) + 1
                return False, max(1, retry_after), int(count) - 1
            return True, 0, int(count)
        except Exception as e:  # noqa: BLE001
            logger.debug("rate-limit redis backend failed, using memory: %s", e)
            return None

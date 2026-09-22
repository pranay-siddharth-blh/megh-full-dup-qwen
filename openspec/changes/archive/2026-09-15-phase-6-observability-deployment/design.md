## Context

See `proposal.md`'s 2026-09-15 update for why (both open questions
resolved). This document covers only the rate-limiting change — the
Kubernetes item is documentation-only, nothing to design.

Current state, re-verified directly against `app/middleware/rate_limit.py`
and `app/deps.py` before writing this:

- `RateLimitMiddleware` (Starlette `BaseHTTPMiddleware`) runs in the
  ASGI middleware stack, **before** FastAPI route dependency injection —
  it has no access to `app.deps.current_scope`'s resolved `UserScope`,
  which only exists once a route's own `Depends(...)` chain runs. Any
  per-user key needs the middleware to derive identity itself.
- `app.security.decode_token(token) -> dict` already does exactly the
  cheap part of this: HMAC-SHA256 signature check, issuer check, expiry
  check, no database call — raises `JWTError` on any problem, returns the
  claims dict (`sub` = user id) on success. This is the same function
  `app.deps.current_scope` calls before its own `appdb.get_user` DB
  lookup — reusing it here adds no new crypto/parsing logic.
- The bearer-token extraction helper (`app.deps._bearer`) is a 5-line
  regex-free split — trivial to reuse or duplicate; reusing avoids a
  second implementation of the same parsing.
- `_check`/`_check_memory`/`_check_redis` all operate on an opaque `key:
  str` today (`f"{bucket}|{ip}"`) — neither needs to know or care whether
  that string came from an IP or a user id. No change needed to the
  actual limiting logic, only to what string is built before it's called.

## Goals / Non-Goals

**Goals:**
- `/api/query` (and any future route added to `_RULES`) rate-limits by
  authenticated user identity when a valid token is present.
- Zero new failure modes: an invalid/missing token degrades to the
  existing IP-based behavior, never a 500, never a false rejection.
- No new database call in the request's fast path (rate-limit decisions
  must stay cheap — this runs on every request to a rate-limited route).

**Non-Goals:**
- Not touching `/api/auth/login`'s IP-based keying — a caller
  authenticating for the first time structurally has no token yet.
- Not adding full authentication to the middleware layer — an
  invalid/expired token is not rejected here; it falls back to IP and the
  route's own `current_scope`/`require_user` dependency remains the only
  place a request is actually authenticated or denied.
- Not changing the Redis vs. in-memory backend split, the sliding-window
  algorithm, the per-route caps (`MAX_REQUESTS`/`WINDOW_SEC`,
  `LOGIN_RL_MAX`/`LOGIN_RL_WINDOW_SEC`), or the 429 response shape — all
  unchanged.

## Decisions

**Reuse `app.security.decode_token` directly, don't add a new JWT-parsing
path.** Alternative considered: have the middleware call
`app.deps.current_scope`-equivalent logic including the `appdb.get_user`
DB lookup, to get a fully-validated `UserScope` — rejected: that adds a
database round-trip to every request's rate-limit check (including ones
that end up 429'd before ever reaching the route), which is exactly the
kind of cost this middleware's own docstring already avoids by being a
simple in-process/Redis counter. The rate-limit key only needs a stable
identifier, not a fully-validated scope — `claims["sub"]` from the cheap
signature/expiry check is sufficient and matches this requirement's
"adds no new failure mode or authorization side effect" contract.

**Key format: `f"{bucket}|user:{sub}"` vs. `f"{bucket}|ip:{ip}"`** — the
`user:`/`ip:` prefix (not present today) makes the two key spaces
non-colliding by construction (an IP string and a user id string could
otherwise coincidentally collide) and makes a mid-flight key inspectable
in logs/metrics as to which path produced it. This changes the key
string's shape for existing IP-based buckets (previously bare
`f"{bucket}|{ip}"`) — see Risks below for why that's acceptable.

**Failure handling: any `JWTError` (or missing token) falls back to IP,
caught at the point of decode, not propagated.** Alternative considered:
distinguish "no token" (clearly anonymous, IP is correct) from "invalid
token" (arguably suspicious, could warrant a stricter bucket) — rejected
as unnecessary complexity for this change: a request with a bad token
still reaches the route and gets a normal 401 there; over-engineering the
rate-limit layer's response to a bad token duplicates authentication
logic this layer explicitly should not own (Non-Goals).

## Risks / Trade-offs

- **[Existing in-memory rate-limit buckets reset on deploy]** → Both the
  in-memory backend (per-worker, already reset on every restart today)
  and the key-format change itself mean any mid-window bucket a caller
  was accumulating against restarts at zero after this ships — same as
  any other deploy that touches this file, not a new risk this change
  introduces. Redis-backed buckets (`RATELIMIT_BACKEND=redis`) also reset
  because the key string changed, not because of any TTL issue — a
  one-time, harmless effect, not a recurring one.
- **[A caller who was previously grouped with others behind a shared IP
  now gets a fresh, more generous effective limit]** → Correct, intended
  behavior per this requirement, not a bug — an authenticated user should
  not share a throttle with unrelated traffic on the same IP.
- **[decode_token is called on every /api/query request now, not just
  authenticated ones already reaching current_scope]** → It was already
  effectively being called once per authenticated request downstream;
  this adds one extra cheap, non-DB call per request at the middleware
  layer. No measurable cost at this deployment's traffic volume
  (~20-40 concurrent users) — flagged, not treated as a real risk.

## Migration Plan

1. In `app/middleware/rate_limit.py`, add a helper that extracts the
   bearer token from the request, calls `security.decode_token`, and
   returns `claims["sub"]` or `None` on any failure (no token, malformed,
   bad signature, wrong issuer, expired) — never raises.
2. Build the rate-limit key as `f"{bucket}|user:{sub}"` when that helper
   returns a value, else `f"{bucket}|ip:{ip}"` — `ip` still resolved via
   the existing `app.net.client_ip` exactly as today.
3. No change to `_check`/`_check_memory`/`_check_redis` — they already
   operate on an opaque key string.
4. Rollback: reverting this one file's diff restores the exact prior
   behavior; no schema, no migration, no persisted state depends on the
   new key format.

## Open Questions

None — both decisions this document depends on were resolved before
writing it (per `proposal.md`'s 2026-09-15 update), and the remaining
implementation choices above are self-contained to one file with no
external dependency.

## 1. Kubernetes topology — documentation only, no code

- [x] 1.1 Updated `docs/baseline-audit.md`'s Kubernetes deployment row
      (§5 summary table row + §6 item 6) with dated 2026-09-15 notes
      ratifying systemd/VM as the permanent target, per `proposal.md`'s
      decision — no manifests, no code.

## 2. Per-user rate limiting

- [x] 2.1 `app/middleware/rate_limit.py`: added `RateLimitMiddleware.
      _identity()`, reusing `app.deps._bearer` for token extraction and
      `app.security.decode_token` for validation — returns the `sub`
      claim as a string, or `None` on any missing/malformed/invalid/
      expired token. No DB call, never raises.
- [x] 2.2 Built the rate-limit key as `f"{bucket}|user:{sub}"` when
      identity resolves, else `f"{bucket}|ip:{ip}"`, in
      `RateLimitMiddleware.dispatch`.
      **Deviation, reported:** per-user keying additionally needed to be
      gated per-bucket, not just per-request — a bearer token sent to
      `/api/auth/login` (nonsensical, but not something to trust the
      caller not to do) would otherwise key that bucket by user too,
      contradicting the spec's "always IP-keyed" requirement for login.
      Fixed by extending `_RULES` from `(prefix, cap, window)` to
      `(prefix, cap, window, key_by_user)` — `key_by_user=False` for
      `/api/auth/login`, `True` for `/api/query` — caught by this
      change's own test (2.4) before being reported here, not left as a
      latent bug.
- [x] 2.3 Confirmed: `_check`/`_check_memory`/`_check_redis` needed no
      changes — verified by reading, no edits made to any of the three.
- [x] 2.4 New `tests/test_rate_limit.py` (15 checks, no live server —
      `starlette.testclient.TestClient` over a minimal app wrapping the
      real middleware): two users behind one IP get independent buckets;
      one user across two IPs (via `X-Forwarded-For`) shares one bucket;
      no-token / malformed-token / expired-token all fall back to IP
      cleanly (no 500, confirmed via status code, not just "didn't
      crash"); `/api/auth/login` stays IP-keyed even when a token is
      present, and rate-limits correctly on its own cap; `_identity()`
      unit-level checks (no header, non-bearer scheme, valid token).
      15/15 passing. Redis-backend/existing-caps regression coverage:
      this repo had no prior dedicated rate-limit test file to preserve
      — `tests/test_security.py` has one live-server-only 429 check,
      unaffected by this change (still excluded from the normal sweep,
      per this repo's own convention, no DB/live server available here).
- [x] 2.5 Full regression sweep: all `tests/test_*.py` files, run
      directly (no `pytest` config in this repo). **37/37 passing**
      (36 prior + this change's new `test_rate_limit.py`).

## 3. Reporting

- [x] 3.1 Reported in this session: files changed, actual test pass
      counts, and the one real deviation found and fixed (2.2's
      per-bucket `key_by_user` gating) before it could ship as a bug.
      Not committed — human commits.

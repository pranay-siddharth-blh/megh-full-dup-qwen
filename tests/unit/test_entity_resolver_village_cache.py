"""
openspec change `entity-resolver-semantic-fallback` — the best-effort Redis
cache in front of resolve_village (app/nlu/entity_resolver.py). No live Redis or
Postgres: app.nlu.entity_resolver._redis and .fetch_rows are both monkeypatched,
same stance tests/unit/test_entity_resolver.py's own docstring describes for
resolve_village (mocked, not exercised against a live DB here either).

Run: `python tests/unit/test_entity_resolver_village_cache.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.nlu import entity_resolver as er  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  - {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


class _FakeRedis:
    """In-memory stand-in for redis.asyncio's client — just the two calls
    _village_cache_get/_put actually use."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.setex_calls = 0

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self.setex_calls += 1
        self.store[key] = value


def _row(code: int, name: str, district: str, block: str) -> dict:
    return {"village_code": code, "lgd_village_name": name, "lgd_district": district, "lgd_block": block}


async def _run_hit_miss_checks() -> None:
    print("1. CACHE HIT / MISS")
    fake = _FakeRedis()
    orig_redis, orig_fetch = er._redis, er.fetch_rows
    db_calls = {"n": 0}

    async def _fake_redis():
        return fake

    async def _fake_fetch_rows(_sql, _params):
        db_calls["n"] += 1
        return [_row(111, "Testville", "EAST KHASI HILLS", "MYLLIEM")]

    er._redis = _fake_redis
    er.fetch_rows = _fake_fetch_rows
    try:
        r1 = await er.resolve_village("Testville", district="East Khasi Hills")
        check("first call resolves via the live query",
              r1.status == "resolved" and r1.canonical == 111, detail=str(r1))
        check("first call issued exactly one DB query", db_calls["n"] == 1, detail=str(db_calls))
        check("the resolved outcome was written to the cache", fake.setex_calls == 1)

        r2 = await er.resolve_village("Testville", district="East Khasi Hills")
        check("an identical second call resolves to the same outcome",
              r2.status == "resolved" and r2.canonical == 111, detail=str(r2))
        check("the second call was served from cache, not the DB", db_calls["n"] == 1, detail=str(db_calls))

        await er.resolve_village("Testville", district="West Garo Hills")
        check("a different district scope is a distinct cache key, not a false hit",
              db_calls["n"] == 2, detail=str(db_calls))
    finally:
        er._redis, er.fetch_rows = orig_redis, orig_fetch


asyncio.run(_run_hit_miss_checks())


async def _run_degraded_redis_checks() -> None:
    print("2. REDIS UNAVAILABLE DEGRADES SILENTLY")
    orig_redis, orig_fetch = er._redis, er.fetch_rows
    db_calls = {"n": 0}

    async def _raising_redis():
        raise ConnectionError("simulated redis outage")

    async def _fake_fetch_rows(_sql, _params):
        db_calls["n"] += 1
        return [_row(222, "Degraded", "RI BHOI", "BHOIRYMBONG")]

    er._redis = _raising_redis
    er.fetch_rows = _fake_fetch_rows
    try:
        r1 = await er.resolve_village("Degraded")
        check("a Redis connection error does not raise out of resolve_village",
              r1.status == "resolved" and r1.canonical == 222, detail=str(r1))
        r2 = await er.resolve_village("Degraded")
        check("a repeated call still works correctly with Redis still down",
              r2.status == "resolved" and r2.canonical == 222, detail=str(r2))
        check("with the cache never able to help, both calls hit the DB directly",
              db_calls["n"] == 2, detail=str(db_calls))
    finally:
        er._redis, er.fetch_rows = orig_redis, orig_fetch


asyncio.run(_run_degraded_redis_checks())


async def _run_unconfigured_checks() -> None:
    print("3. REDIS UNCONFIGURED (the common case - REDIS_URL unset)")
    orig_redis, orig_fetch = er._redis, er.fetch_rows
    db_calls = {"n": 0}

    async def _no_redis():
        return None  # app.caching.cache._redis()'s own contract when REDIS_URL is blank

    async def _fake_fetch_rows(_sql, _params):
        db_calls["n"] += 1
        return [_row(333, "Plain", "RI BHOI", "UMSNING")]

    er._redis, er.fetch_rows = _no_redis, _fake_fetch_rows
    try:
        r1 = await er.resolve_village("Plain")
        r2 = await er.resolve_village("Plain")
        check("resolution still works with caching entirely off",
              r1.status == "resolved" and r2.status == "resolved", detail=f"{r1}, {r2}")
        check("every call hits the DB directly when there is no cache backend",
              db_calls["n"] == 2, detail=str(db_calls))
    finally:
        er._redis, er.fetch_rows = orig_redis, orig_fetch


asyncio.run(_run_unconfigured_checks())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL ENTITY RESOLVER VILLAGE CACHE CHECKS PASSED")

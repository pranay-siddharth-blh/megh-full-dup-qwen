"""
Near-duplicate ("semantic") response cache — the layer past the exact-match
ResponseCache in cache.py.

At ~200 DAU the same question arrives worded slightly differently within
minutes ("houses completed in EGH" vs "how many houses completed in East Garo
Hills"). The exact-match cache misses those; this one embeds the question with
qwen3-embedding and serves a stored answer when cosine similarity to an
earlier question clears SEMANTIC_CACHE_THRESHOLD.

Cost is one embedding call per otherwise-uncached question — one small model
call to potentially save the 2-4 chat calls a full pipeline run makes. Any
embedding failure is swallowed and treated as a miss; the caller just runs the
pipeline.

Same stance as cache.py: in-process per worker, everything expires, nothing
here is authoritative. Vectors are stored L2-normalised so a lookup is one dot
product per entry; entries are capped and evicted oldest-first. The pipeline
run's own embedding is reused via lookup() -> put(vec=...), so a miss still
only embeds once.
"""
import asyncio
import math
import time
from collections import OrderedDict

from app import llm
from app.cache import normalize
from app.config import settings


def _unit(v: list[float]) -> list[float] | None:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else None


def scope_signature(question: str) -> tuple:
    """(schemes, places, years, contrasts) the question names. WI-6 (forward plan,
    2026-10-16): a semantic hit must name the same ones — "…in 2023-24" and
    "…in 2024-25" embed almost identically, and the 2024-25 answer was served
    for the 2023-24 question. Never raises: an unreadable question gets a
    signature that matches nothing but itself."""
    try:
        from app import context_policy, pipeline
        q = question or ""
        return (tuple(sorted(pipeline._named_schemes(q))),
                tuple(sorted(str(p).upper() for p in context_policy._places(q))),
                tuple(sorted(context_policy.extract_year_keys(q))),
                tuple(sorted(_contrast_terms(q) | context_policy.metric_families(q)
                             | context_policy.category_terms(q))))
    except Exception:  # noqa: BLE001
        return ("?", normalize(question or ""))


# Words that flip the answer but barely move the embedding (measured 2026-10-24,
# bge-small vs qwen3-embedding, cache threshold 0.93): "top 5 … by person days" vs
# "bottom 5 …" scored 0.952 / 0.985, "houses sanctioned" vs "houses completed"
# 0.953 on bge-small, "amount released" vs "amount sanctioned" 0.949 on qwen3 —
# each would serve the other question's answer. No threshold separates them from
# true paraphrases (0.927-0.950), so a hit must also name the same ones of these.
_RANK_HIGH = {"top", "highest", "most", "largest", "biggest", "max", "maximum", "best",
              "greatest", "higher", "more"}
_RANK_LOW = {"bottom", "lowest", "least", "smallest", "fewest", "min", "minimum", "worst",
             "lower", "less", "fewer"}
_RANK_ENDS = {"first", "last"}
_AGGREGATES = {"average": "avg", "avg": "avg", "mean": "avg", "percent": "pct",
               "percentage": "pct", "share": "pct", "proportion": "pct"}
# Prefix stems ("complet" catches completed/completion; "incomplet" is its own).
_STATUS_STEMS = ("sanction", "complet", "incomplet", "releas", "approv", "reject", "pending",
                 "hold", "disburs", "verif", "ongoing", "cancel", "expend", "spent")


def _contrast_terms(question: str) -> set[str]:
    from app.text_match import is_int, tokens
    toks = [t.low for t in tokens(question)]
    out: set[str] = set()
    for i, w in enumerate(toks):
        if w in _RANK_HIGH:
            out.add("rank:high")
        elif w in _RANK_LOW:
            out.add("rank:low")
        elif w in _RANK_ENDS:
            out.add("rank:" + w)
        if w in _AGGREGATES:
            out.add("agg:" + _AGGREGATES[w])
        for stem in _STATUS_STEMS:
            if w.startswith(stem):
                out.add("status:" + stem)
        # The N of a ranking: "top 5", "5 highest" — not a year's "-24".
        if w in _RANK_HIGH | _RANK_LOW | _RANK_ENDS:
            for j in (i - 1, i + 1):
                if 0 <= j < len(toks) and is_int(toks[j]) and len(toks[j]) <= 3:
                    out.add("n:" + toks[j])
    return out


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class SemanticCache:
    def __init__(self, ttl: float, max_entries: int, threshold: float):
        self.ttl = ttl
        self.max_entries = max_entries
        self.threshold = threshold
        # (scope_key + question) -> (unit_vec, value, expiry, scope_key).
        # scope_key is stored alongside so a lookup only matches entries from a
        # caller with the same authorization fingerprint. OrderedDict => oldest-first eviction.
        self._store: "OrderedDict[str, tuple[list[float], dict, float, str, tuple]]" = OrderedDict()
        self._lock = asyncio.Lock()
        self.hits = 0
        self.misses = 0
        self.embed_errors = 0

    async def _embed(self, question: str) -> list[float] | None:
        try:
            vecs = await llm.call_embedding(question)
        except Exception:  # noqa: BLE001 — any failure => treat as a cache miss
            self.embed_errors += 1
            return None
        return _unit(vecs[0]) if vecs else None

    def _too_short(self, question: str) -> bool:
        return len(normalize(question)) < settings.SEMANTIC_CACHE_MIN_CHARS

    async def lookup(self, question: str, scope_key: str = "") -> tuple[dict | None, list[float] | None]:
        """Return (cached_value_or_None, unit_vector_or_None). Pass the vector
        back to put() after the pipeline runs so the question is embedded once,
        not twice. Only entries stored under the same scope_key are considered."""
        if not settings.SEMANTIC_CACHE_ENABLED or self._too_short(question):
            return None, None
        vec = await self._embed(question)
        if vec is None:
            return None, None

        now = time.monotonic()
        sig = scope_signature(question)
        async with self._lock:
            best_key, best_sim = None, 0.0
            for key, (uvec, _value, expiry, sk, entry_sig) in list(self._store.items()):
                if now > expiry:
                    del self._store[key]
                    continue
                if sk != scope_key or entry_sig != sig:
                    continue
                sim = _dot(vec, uvec)
                if sim > best_sim:
                    best_key, best_sim = key, sim
            if best_key is not None and best_sim >= self.threshold:
                _uvec, value, _expiry, _sk, _sig = self._store[best_key]
                self._store.move_to_end(best_key)
                self.hits += 1
                return (
                    {**value, "cached": True, "cache_kind": "semantic",
                     "cache_similarity": round(best_sim, 4)},
                    vec,
                )
            self.misses += 1
            return None, vec

    async def put(self, question: str, value: dict, vec: list[float] | None = None,
                  scope_key: str = "") -> None:
        if not settings.SEMANTIC_CACHE_ENABLED or self._too_short(question):
            return
        # Same exclusions as the exact-match cache, plus edge cases (greetings /
        # off-topic) — those are cheap to match already, not worth an embed slot.
        if value.get("needs_clarification") or value.get("confidence") == "low":
            return
        if value.get("route") == "edge":
            return
        if vec is None:
            vec = await self._embed(question)
        if vec is None:
            return

        key = scope_key + "\x1f" + normalize(question)
        async with self._lock:
            self._store[key] = (vec, value, time.monotonic() + self.ttl, scope_key, scope_signature(question))
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "enabled": settings.SEMANTIC_CACHE_ENABLED,
            "entries": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "embed_errors": self.embed_errors,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
            "threshold": self.threshold,
        }


semantic_cache = SemanticCache(
    ttl=settings.SEMANTIC_CACHE_TTL_SECONDS,
    max_entries=settings.SEMANTIC_CACHE_MAX_ENTRIES,
    threshold=settings.SEMANTIC_CACHE_THRESHOLD,
)

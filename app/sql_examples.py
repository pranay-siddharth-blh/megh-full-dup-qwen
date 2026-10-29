"""
The SQL prompt's worked examples AND view / join metadata from Qdrant
(SQL_EXAMPLES_SOURCE=qdrant, D-074; every kind used since 2026-10-27 evening).

megh_sql_metadata, loaded by another pipeline and only read here, holds three
kinds of point:
  example  question + sql (+ notes) — searched by meaning per data question;
  view     one curated view: what it is, grain, use for / do not use for,
           columns, filters, rules (`prompt_text`);
  join     how two schemes may (or may NOT) be combined (`prompt_text`).
With the switch on, `_data_sql_stage` calls `prefetch()` once per data
question: one embedding of the few-shot ranking text, one filtered search per
scheme, and the views / joins (read whole, cached for _META_TTL_SECONDS). The
examples are kept in a context variable for the rest of that stage;
`prompt_builder._fewshot_block` takes them in place of the YAML banks and
`prompt_builder._sql_metadata_block` adds the views / joins of the schemes in
play (`metadata_text`).

build_sql_prompt stays synchronous (it is also called to measure the prompt),
which is why the search runs in the stage, before it, and not inside it.

Any failure — Qdrant or the embedding gateway down, a timeout, a scheme with no
example — leaves that scheme on the YAML bank (annotations.few_shot_examples),
so the switch can never cost an answer its examples.

SQL_EXAMPLES_SOURCE=yaml_meaning (B5, 2026-10-29): the REVIEWED YAML banks, ranked by
meaning instead of shared words. One embedding of the ranking text per data question;
each bank's example questions (and `variants`) are embedded once per process in the
background — until that finishes, the turn keeps the word ranking. No views / joins
(those are megh_sql_metadata's). Measured against yaml and qdrant with
tests/nl2sql_eval/compare_examples_source.py.
"""
import asyncio
import contextvars
import logging
import time

from qdrant_client import models

from app import annotations, llm, vectorstore
from app.config import settings

logger = logging.getLogger(__name__)

# How many hits to fetch per scheme before the single-scheme filter below:
# about a fifth of the examples are tagged with two schemes.
_FETCH_FACTOR = 3

# scheme -> [{"question", "sql", "id", "tags"}, ...] best first, for the current
# stage. More than top_k are kept: `current` drops the ones a prompt cannot use.
_examples_var: "contextvars.ContextVar[dict | None]" = contextvars.ContextVar("sql_examples", default=None)


# kind=view / kind=join points, read whole (28 on 2026-10-27): they describe
# the schema, not the question, so they are fetched once and refreshed after
# this many seconds instead of searched per question.
_META_TTL_SECONDS = 600
_meta_cache: dict = {"at": 0.0, "points": []}


def _source() -> str:
    return (settings.SQL_EXAMPLES_SOURCE or "").strip().lower()


def enabled() -> bool:
    """megh_sql_metadata in use (examples + views / joins)."""
    return _source() == "qdrant"


def meaning_ranked_yaml() -> bool:
    return _source() == "yaml_meaning"


# scheme -> [[vector per text of the example], ...] in bank order (B5).
_yaml_vectors: dict = {}
_yaml_pending: set = set()


async def _embed_bank(scheme: str) -> None:
    try:
        pool = annotations._few_shot_cache.get(scheme, [])
        texts = [[ex["question"], *(ex.get("variants") or [])] for ex in pool]
        flat = [x for ts in texts for x in ts]
        vecs: list = []
        for i in range(0, len(flat), 64):
            vecs += await llm.call_embedding(flat[i:i + 64])
        out, k = [], 0
        for ts in texts:
            out.append(vecs[k:k + len(ts)])
            k += len(ts)
        _yaml_vectors[scheme] = out
        logger.info("sql_examples: %d %s YAML examples embedded for meaning ranking", len(out), scheme)
    except Exception as e:  # noqa: BLE001 — stays on the word ranking
        logger.warning("sql_examples: embedding the %s YAML bank failed (%s)", scheme, type(e).__name__)
    finally:
        _yaml_pending.discard(scheme)


def _cos(a: list, b: list) -> float:
    num = sum(x * y for x, y in zip(a, b))
    den = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
    return num / den if den else 0.0


def _rank_yaml(vector: list, scheme: str, top_k: int) -> "list[dict] | None":
    """The scheme's YAML examples by meaning, or None (bank not embedded yet: the
    embedding starts in the background and this turn keeps the word ranking)."""
    pool = annotations._few_shot_cache.get(scheme, [])
    vecs = _yaml_vectors.get(scheme)
    if vecs is None or len(vecs) != len(pool):
        if scheme not in _yaml_pending:
            _yaml_pending.add(scheme)
            asyncio.get_running_loop().create_task(_embed_bank(scheme))
        return None
    score = {id(ex): max((_cos(vector, v) for v in vs), default=0.0) for ex, vs in zip(pool, vecs)}
    got = annotations.few_shot_examples([scheme], "", top_k, rank=lambda ex: score.get(id(ex), 0.0))
    return [{**ex, "tags": [scheme]} for ex in got]


def _example(payload: dict) -> "dict | None":
    q, sql = payload.get("question"), payload.get("sql")
    if not q or not sql:
        return None
    notes = payload.get("notes")
    return {"question": str(q), "sql": str(sql).strip(), "id": payload.get("example_id"),
            "tags": vectorstore.scheme_tags(payload),
            "notes": " ".join(str(notes).split()) if notes else None}


async def _search(vector: list[float], scheme: str, schemes: list[str], top_k: int) -> list[dict]:
    flt = models.Filter(must=[
        models.FieldCondition(key="kind", match=models.MatchValue(value="example")),
        models.FieldCondition(key="scheme", match=models.MatchAny(any=[scheme])),
    ])
    response = await vectorstore.get_client().query_points(
        collection_name=settings.SQL_EXAMPLES_COLLECTION, query=vector, query_filter=flt,
        limit=top_k * _FETCH_FACTOR, with_payload=True)
    out: list[dict] = []
    for h in response.points:
        ex = _example(h.payload or {})
        if ex and set(ex["tags"]) <= set(schemes):
            out.append(ex)
    return out


async def _load_metadata() -> None:
    """Read every view / join point into the cache (when it is stale)."""
    if _meta_cache["points"] and time.monotonic() - _meta_cache["at"] < _META_TTL_SECONDS:
        return
    flt = models.Filter(must=[models.FieldCondition(key="kind", match=models.MatchAny(any=["view", "join"]))])
    points, offset = [], None
    while True:
        batch, offset = await vectorstore.get_client().scroll(
            collection_name=settings.SQL_EXAMPLES_COLLECTION, scroll_filter=flt, limit=256,
            offset=offset, with_payload=True, with_vectors=False)
        points += [p.payload or {} for p in batch]
        if offset is None:
            break
    # views first (what each object is), then joins (how two may combine);
    # a stable order keeps the prompt the same turn to turn
    points.sort(key=lambda pl: (pl.get("kind") != "view", str(pl.get("view_name") or pl.get("join_id") or "")))
    _meta_cache.update(at=time.monotonic(), points=points)


def metadata_text(schemes: list[str], kinds: tuple = ("view", "join")) -> str:
    """The `prompt_text` of every cached view / join whose schemes are all in
    `schemes` — a one-scheme prompt gets that scheme's views only; a join
    (always two schemes) only reaches a prompt that holds both. "" when the
    switch is off or nothing was loaded."""
    if not enabled() or not schemes:
        return ""
    allowed = set(schemes)
    parts = []
    for pl in _meta_cache["points"]:
        tags = set(vectorstore.scheme_tags(pl))
        text = (pl.get("prompt_text") or "").strip()
        if pl.get("kind") in kinds and tags and tags <= allowed and text:
            parts.append(text)
    return "\n\n".join(parts)


async def prefetch(rank_text: str, schemes: list[str], top_k: int = 5) -> None:
    """Fetch the examples for `schemes` into this stage's context. A no-op when
    SQL_EXAMPLES_SOURCE is not "qdrant"; on any failure nothing is set and the
    prompt uses the YAML banks."""
    _examples_var.set(None)
    if meaning_ranked_yaml() and schemes and (rank_text or "").strip():
        try:
            vector = (await asyncio.wait_for(llm.call_embedding([rank_text]),
                                             timeout=settings.SQL_EXAMPLES_TIMEOUT_SECONDS))[0]
            got = {s: ex for s in schemes if (ex := _rank_yaml(vector, s, top_k))}
        except Exception as e:  # noqa: BLE001 — the word-ranked YAML banks answer instead
            logger.warning("sql_examples: meaning ranking unavailable (%s) — word ranking this turn",
                           type(e).__name__)
            return
        if got:
            _examples_var.set(got)
        return
    if not enabled() or not schemes or not (rank_text or "").strip():
        return
    try:
        await asyncio.wait_for(_load_metadata(), timeout=settings.SQL_EXAMPLES_TIMEOUT_SECONDS)
    except Exception as e:  # noqa: BLE001 — the prompt keeps the last views / joins read, or none
        logger.warning("sql_examples: views / joins unavailable (%s)", type(e).__name__)
    try:
        async def run() -> dict:
            vector = (await llm.call_embedding([rank_text]))[0]
            found = await asyncio.gather(*(_search(vector, s, schemes, top_k) for s in schemes))
            return {s: ex for s, ex in zip(schemes, found) if ex}
        got = await asyncio.wait_for(run(), timeout=settings.SQL_EXAMPLES_TIMEOUT_SECONDS)
    except Exception as e:  # noqa: BLE001 — the YAML banks answer instead
        logger.warning("sql_examples: %s unavailable (%s) — YAML few-shots this turn",
                       settings.SQL_EXAMPLES_COLLECTION, type(e).__name__)
        return
    missing = [s for s in schemes if s not in got]
    if missing:
        logger.info("sql_examples: no Qdrant example for %s — YAML few-shots for it", ", ".join(missing))
    _examples_var.set(got)


def current(scheme: str, schemes: "list[str] | None" = None) -> "list[dict] | None":
    """The fetched examples for `scheme` usable in a prompt over `schemes`, or
    None (use YAML). A two-scheme example joins both schemes' views: a
    one-scheme prompt — including each half of a cross-scheme question, which
    is generated per scheme (D-062, KI-280) — never describes the other view,
    so it gets only examples whose every scheme is in that prompt."""
    got = _examples_var.get()
    allowed = set(schemes or [scheme])
    usable = [ex for ex in (got or {}).get(scheme, []) if set(ex["tags"]) <= allowed]
    return usable or None

"""
openspec change `entity-resolver-semantic-fallback` — stage 7 (embedding
nearest-neighbour) and did-you-mean suggestions in app/nlu/entity_resolver.py.

Deterministic by construction: uses a synthetic "TESTSCHEME" catalogue with
hand-placed 2D unit vectors (exact, reproducible cosine similarities) and a
monkeypatched app.nlu.entity_resolver._embed_texts — no real fastembed model
load, no network, no ~130 MB download, no dependency on what a specific
embedding model happens to think about Meghalaya place names. The acceptance
threshold and runner-up-gap constants were calibrated separately against the
real model (see the comment above _EMBED_RUNNER_UP_GAP in entity_resolver.py)
— this file locks in the accept/reject boundary logic itself, not the
model's actual output.

Run: `python tests/unit/test_entity_resolver_semantic_fallback.py`, exit code 0 = pass.
"""
import asyncio
import math
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
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def _vec(angle_deg: float) -> list[float]:
    r = math.radians(angle_deg)
    return [math.cos(r), math.sin(r)]


# ALPHA at 0°, BETA at 90°, GAMMA at 91° (1° from BETA — a near-duplicate,
# the way "East Khasi Hills" / "Eastern West Khasi Hills" sit close together
# in the real catalogue).
er._catalog["TESTSCHEME"] = {
    "district": [
        {"canonical": "ALPHA", "aliases": []},
        {"canonical": "BETA", "aliases": []},
        {"canonical": "GAMMA", "aliases": []},
    ],
}
er._blocked["TESTSCHEME"] = set()
er._embeddings["TESTSCHEME"] = {
    "district": [
        ("ALPHA", _vec(0)),
        ("BETA", _vec(90)),
        ("GAMMA", _vec(91)),
    ],
}

# Query text -> the (unnormalised, deliberately) vector _embed_texts should
# return for it. _unit() inside entity_resolver.py normalises both sides, so
# feeding already-unit vectors here is fine.
_QUERY_VECTORS = {
    "near alpha": _vec(5),          # clearly closest to ALPHA (0°), miles from BETA/GAMMA
    "between all three": _vec(45),  # equidistant-ish, none clears the accept bar
    "between beta and gamma": _vec(90.5),  # ties BETA/GAMMA — high score, no safe margin
}

_orig_embed_texts = er._embed_texts


async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    return [_QUERY_VECTORS[t] for t in texts]


er._embed_texts = _fake_embed_texts


async def _run_checks() -> None:
    values = er._catalog["TESTSCHEME"]["district"]

    print("1. EMBEDDING FALLBACK - accept / reject bands")

    r = await er._embedding_fallback("near alpha", er.fold("near alpha"), "TESTSCHEME", "district", values)
    check("a clearly-nearest catalogue value resolves (high score, wide gap)",
          r is not None and r.status == "resolved" and r.canonical == "ALPHA", detail=str(r))

    r = await er._embedding_fallback("between all three", er.fold("between all three"),
                                      "TESTSCHEME", "district", values)
    check("no candidate clearing the acceptance threshold falls through (returns None)",
          r is None, detail=str(r))

    r = await er._embedding_fallback("between beta and gamma", er.fold("between beta and gamma"),
                                      "TESTSCHEME", "district", values)
    check("a high top score with no safe margin over its runner-up is NOT trusted (returns None)",
          r is None, detail=str(r))

    print("2. BLOCKED-PAIRS GUARD applies to the embedding stage")

    er._blocked["TESTSCHEME"] = {(er.fold("near alpha"), er.fold("ALPHA"))}
    r = await er._embedding_fallback("near alpha", er.fold("near alpha"), "TESTSCHEME", "district", values)
    check("a blocked (query, canonical) pair is never resolved via embedding, even at high similarity",
          r is None, detail=str(r))
    er._blocked["TESTSCHEME"] = set()  # restore for the sections below

    print("3. EXCLUDED DIMENSIONS - house_status / tranche_label never use this stage")

    r = await er._embedding_fallback("near alpha", er.fold("near alpha"), "TESTSCHEME", "tranche_label", values)
    check("a dimension with no catalogue vectors (e.g. tranche_label/house_status) always falls through",
          r is None, detail=str(r))

    print("4. FULL resolve_dimension WIRING - not_found still carries did-you-mean suggestions")

    r = await er.resolve_dimension("between all three", "TESTSCHEME", "district")
    check("resolve_dimension falls through fuzzy + embedding to not_found for an unresolvable mention",
          r.status == "not_found", detail=str(r))
    check("not_found candidates are populated from the synthetic catalogue",
          len(r.candidates) > 0 and all(c["canonical"] in {"ALPHA", "BETA", "GAMMA"} for c in r.candidates),
          detail=str(r))

    r = await er.resolve_dimension("near alpha", "TESTSCHEME", "district")
    check("resolve_dimension resolves via the embedding stage end-to-end when fuzzy alone can't",
          r.status == "resolved" and r.canonical == "ALPHA", detail=str(r))


try:
    asyncio.run(_run_checks())
finally:
    er._embed_texts = _orig_embed_texts
    del er._catalog["TESTSCHEME"]
    del er._blocked["TESTSCHEME"]
    del er._embeddings["TESTSCHEME"]


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL ENTITY RESOLVER SEMANTIC FALLBACK CHECKS PASSED")

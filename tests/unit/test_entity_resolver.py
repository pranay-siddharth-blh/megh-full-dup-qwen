"""
Pipeline architecture doc §5.6 ("Entity resolver") — app/nlu/entity_resolver.py's
deterministic, fully in-memory matching functions: resolve_dimension (exact /
alias / fuzzy district-block-year resolution), lookup_geo_term (acronym/alias
reverse lookup), scan_dimension (raw-text backstop scan for a district), and
detect_region (hill-range name -> district group, with the "expand to every
district" cue). No DB, no model gateway — these functions never call either;
resolve_village (the one DB-backed piece of this node) is exercised
separately via mocking in test_scope_scheme_classifier.py's OutOfScope
checks, not duplicated here.
Run: `python tests/unit/test_entity_resolver.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.nlu.entity_resolver import (  # noqa: E402
    detect_region,
    load_all,
    lookup_geo_term,
    resolve_dimension,
    scan_dimension,
)

load_all()

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# ── 1. resolve_dimension — exact / alias / fuzzy / not-found ────────────────
print("1. RESOLVE_DIMENSION")


async def _run_resolve_dimension_checks() -> None:
    r = await resolve_dimension("East Garo Hills", "MGNREGA", "district")
    check("exact canonical district name resolves", r.status == "resolved" and r.confidence == 1.0, detail=str(r))

    r = await resolve_dimension("EGH", "MGNREGA", "district")
    check("known acronym alias resolves to the same district",
          r.status == "resolved" and r.canonical and "GARO" in r.canonical.upper(), detail=str(r))

    r = await resolve_dimension("South Garoo Hills", "MGNREGA", "district")
    check("a close misspelling still resolves via fuzzy match (RapidFuzz stage)",
          r.status == "resolved" and r.canonical == "SOUTH GARO HILLS", detail=str(r))

    r = await resolve_dimension("Eest Garo Hills", "MGNREGA", "district")
    check("a misspelling equidistant from two districts ('Eest' -> East/West) is ambiguous, not guessed",
          r.status == "ambiguous", detail=str(r))

    r = await resolve_dimension("Guwahati", "MGNREGA", "district")
    check("a genuinely foreign place name is not_found, not guessed",
          r.status == "not_found", detail=str(r))
    check("not_found still carries did-you-mean suggestions (stage 6's own ranking)",
          r.status == "not_found" and len(r.candidates) > 0, detail=str(r))

    r = await resolve_dimension("ADOKGRE", "MGNREGA", "block")
    check("exact canonical block name resolves", r.status == "resolved", detail=str(r))


asyncio.run(_run_resolve_dimension_checks())


# ── 2. lookup_geo_term — deterministic acronym/alias reverse lookup ─────────
print("2. LOOKUP_GEO_TERM")

g = lookup_geo_term("EKH")
check("a district acronym reverse-resolves to its full name",
      g is not None and g["type"] == "district" and g["used_abbrev"] is True, detail=str(g))

g = lookup_geo_term("not a real place at all")
check("gibberish resolves to nothing", g is None, detail=str(g))


# ── 3. scan_dimension — raw-text backstop scan, longest-match wins ──────────
print("3. SCAN_DIMENSION")

r = scan_dimension("how many villages are covered in West Garo Hills", "MGNREGA", "district")
check("a plainly-named district in free text is found even with no explicit tag",
      r is not None and r.status == "resolved", detail=str(r))
check("the longest matching form wins ('West Garo Hills', not a shorter embedded form)",
      r is not None and r.canonical is not None and "WEST" in r.canonical.upper(), detail=str(r))

r = scan_dimension("how many person-days were generated overall", "MGNREGA", "district")
check("text naming no district at all scans to nothing", r is None, detail=str(r))

r = scan_dimension("how many villages in West Garo Hills", "MGNREGA", "block")
check("scan_dimension only ever scans the district dimension, by design", r is None, detail=str(r))


# ── 4. detect_region — hill-range name -> district group ───────────────────
print("4. DETECT_REGION")

reg = detect_region("how many person-days across all of Garo Hills?", "MGNREGA")
check("'all of <region>' sets expand=True",
      reg is not None and reg["expand"] is True, detail=str(reg))
check("the region group lists every district in it",
      reg is not None and len(reg["districts"]) == 5, detail=str(reg))

reg = detect_region("how many person-days in Garo Hills?", "MGNREGA")
check("a bare region mention with no 'all/every/each' cue sets expand=False",
      reg is not None and reg["expand"] is False, detail=str(reg))

reg = detect_region("how many person-days in West Garo Hills?", "MGNREGA")
check("a full district name embedding the region word is read as the district, not the region",
      reg is None, detail=str(reg))

reg = detect_region("how many person-days in East Garo Hills?", "MGNREGA")
check("a specific district name never reads as a region", reg is None, detail=str(reg))


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL ENTITY RESOLVER (5.6) CHECKS PASSED")

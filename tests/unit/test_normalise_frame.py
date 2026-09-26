"""
normalise_frame() (app/nlu/understand.py) — the QueryFrame's as-typed schemes,
places and years turned into the pipeline's own canonical values by the
pipeline's own deterministic code, stored in resolve_entities()' exact shape.

Misspellings from real traffic: "westgaro hils", "manrega", "EKH", "rigbhoi".
Also: a place called a village that is really a district (trust the DB, add a
note), out-of-range years, ambiguous typos recorded as the resolver's own
ClarificationNeeded (not raised — shadow mode), level words that name no
place, the resolve_entities(mentions=...) path matching the LLM-extractor
path exactly, and the new resolver stage 6b (squashed fuzzy match, flag-gated).
Offline: in-memory catalogues only; the live village lookup is stubbed.
Run: `python tests/unit/test_normalise_frame.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.core.config import settings  # noqa: E402
from app.knowledge import scheme_registry  # noqa: E402
from app.nlu import entity_resolver  # noqa: E402
from app.nlu import understand as u  # noqa: E402
from app.orchestration import pipeline  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


entity_resolver.load_all()
scheme_registry.load_all()


async def _no_village(text, district=None, block=None):
    return entity_resolver.Resolved("not_found", "village", text, message=f"'{text}' is not a known village")

pipeline.resolve_village = _no_village          # no DB in unit tests


def frame(**kw):
    return u.QueryFrame(**{"rewritten_question": kw.pop("q", ""), **kw})


def run(f, message):
    return asyncio.run(u.normalise_frame(f, message))


def resolved(f):
    return (f.entity_result or {}).get("resolved") or {}


settings.ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED = True
try:
    print("\n=== schemes: frame ∪ the pipeline's own text safety net ===")
    f = run(frame(q="What is the total manrega expenditure?", schemes=[]), "total manrega expenditure")
    check("'manrega' -> MGNREGA via _correct_scheme_spelling/_named_schemes", f.resolved_schemes == ["MGNREGA"],
          str(f.resolved_schemes))
    check("source recorded as the text safety net, not the frame",
          f.scheme_sources == {"MGNREGA": ["named"]}, str(f.scheme_sources))
    f = run(frame(q="How many PMAY-G houses were completed?", schemes=["PMAY-G"]), "how many houses completed")
    check("frame scheme + scheme-only vocabulary ('houses') agree, both recorded",
          f.resolved_schemes == ["PMAY-G"] and set(f.scheme_sources["PMAY-G"]) == {"frame", "vocabulary"},
          str(f.scheme_sources))
    f = run(frame(q="Break down PMAY-G by block", schemes=["PMAY-G"], is_followup=True), "and block wise?")
    check("a frame scheme with no text evidence (from the conversation) is kept", f.resolved_schemes == ["PMAY-G"])

    print("\n=== geography: misspellings through entity_resolver ===")
    for typed, canon, disp in (("westgaro hils", "WEST GARO HILLS", "West Garo Hills"),
                               ("EKH", "EAST KHASI HILLS", "East Khasi Hills"),
                               ("rigbhoi", "RI BHOI", "Ri Bhoi")):
        f = run(frame(q=f"MGNREGA expenditure in {typed}", schemes=["MGNREGA"], metric="expenditure",
                      geo_mentions=[{"text": typed}]), f"mgnrega expenditure in {typed}")
        check(f"'{typed}' -> district {canon}", resolved(f).get("district") == canon,
              f"{f.entity_result} {f.clarification} {f.normalise_notes}")
        check(f"'{typed}' display '{disp}'", (f.entity_result or {}).get("display", {}).get("district") == disp)

    f = run(frame(q="MGNREGA person-days in the village of west garo hills", schemes=["MGNREGA"],
                  geo_mentions=[{"text": "west garo hills", "level": "village"}]),
            "persondays in the village of west garo hills")
    check("called a village but is a district -> resolved as the district (trust the DB)",
          resolved(f).get("district") == "WEST GARO HILLS" and not resolved(f).get("village_code"), str(f.entity_result))
    check("... with a note saying so", any("called a village but is a district" in n for n in f.normalise_notes),
          str(f.normalise_notes))

    f = run(frame(q="Compare PMAY-G in ekh and wgh", schemes=["PMAY-G"], query_type="comparison",
                  geo_mentions=[{"text": "ekh"}, {"text": "wgh"}]), "compare ekh and wgh pmay")
    check("two districts -> district_list (the extractor's plural compare form)",
          resolved(f).get("district_list") == ["EAST KHASI HILLS", "WEST GARO HILLS"], str(f.entity_result))

    f = run(frame(q="Top 5 districts by MGNREGA expenditure", schemes=["MGNREGA"], query_type="ranking",
                  geo_mentions=[{"text": "top 5 districts"}]), "top 5 districts mgnrega expenditure")
    check("level words name no place: no geo filter", not any(k in resolved(f) for k in ("district", "block")),
          str(f.entity_result))
    check("... they become the breakdown (group_by)", f.group_by == "district", str(f.group_by))

    f = run(frame(q="MGNREGA spend in est garo hills", schemes=["MGNREGA"],
                  geo_mentions=[{"text": "est garo hills"}]), "mgnrega spend in est garo hills")
    check("a typo equally close to two districts is NOT guessed",
          "district" not in resolved(f), str(f.entity_result))

    f = run(frame(q="What is the total expenditure in wgh?", geo_mentions=[{"text": "wgh"}]), "total expenditure in wgh")
    check("no scheme -> geography left unresolved, with a note",
          f.entity_result is None and any("no scheme" in n for n in f.normalise_notes))

    f = run(frame(q="hi", intent="EDGE", geo_mentions=[{"text": "wgh"}]), "hi")
    check("EDGE frame: nothing resolved", f.entity_result is None and f.clarification is None)

    print("\n=== year ===")
    f = run(frame(q="MGNREGA expenditure in EKH in 2023-24", schemes=["MGNREGA"], year_text="2023-24",
                  geo_mentions=[{"text": "EKH"}]), "total manrega expenditure in EKH 2023-24")
    check("'2023-24' -> year_key 2023 on the frame", f.year_key == 2023)
    check("... and in entity_result exactly as resolve_entities() stores it",
          resolved(f).get("year_key") == 2023 and f.entity_result["display"].get("year") == "FY 2023-24",
          str(f.entity_result))
    f = run(frame(q="MGNREGA expenditure in 1999-20", schemes=["MGNREGA"], year_text="1999-20"),
            "mgnrega spend 1999-20")
    check("out-of-range year: noted", any("outside the data range" in n for n in f.normalise_notes),
          str(f.normalise_notes))
    check("... and the resolver's own year-out-of-range pause recorded (not raised)",
          (f.clarification or {}).get("rule") == "year-out-of-range" and f.clarification["options"],
          str(f.clarification))
    for period in ("since 2020", "2019-20 and 2021-22", "from 2019 to 2021"):   # all inside PMAY-G coverage
        f = run(frame(q=f"PMAY-G houses sanctioned {period}", schemes=["PMAY-G"], year_text=period),
                f"pmay houses sanctioned {period}")
        check(f"a period ('{period}') is not pinned as one financial year",
              f.year_key is None and "year_key" not in resolved(f)
              and any("is a period" in n for n in f.normalise_notes), f"{f.year_key} {f.entity_result}")
    f = run(frame(q="MGNREGA trend across all years", schemes=["MGNREGA"], year_text="all years"),
            "persondays trend all years")
    check("'all years' is not a specific FY: year_key None, left for the rules",
          f.year_key is None and any("not a specific financial year" in n for n in f.normalise_notes))

    print("\n=== same machinery, same shape as today's resolve_entities() ===")

    async def _extractor(question):
        return {"district": "EKH", "year": "2023-24"}
    orig_extract = pipeline.extract_entity_mentions
    pipeline.extract_entity_mentions = _extractor
    q = "What is the total MGNREGA expenditure in EKH in 2023-24?"
    today = asyncio.run(pipeline.resolve_entities(q, ["MGNREGA"]))
    pipeline.extract_entity_mentions = orig_extract
    f = run(frame(q=q, schemes=["MGNREGA"], year_text="2023-24", geo_mentions=[{"text": "EKH"}]),
            "total manrega expenditure in EKH 2023-24")
    check("frame.entity_result == resolve_entities() via the LLM extractor, field for field",
          f.entity_result == today, f"{f.entity_result} vs {today}")
    check("keys are exactly resolved/notes/display (generate_sql consumes it unchanged)",
          set(f.entity_result) == {"resolved", "notes", "display"})

    calls = []

    async def _count(question):
        calls.append(question)
        return {}
    pipeline.extract_entity_mentions = _count
    asyncio.run(pipeline.resolve_entities("mgnrega spend", ["MGNREGA"]))
    asyncio.run(pipeline.resolve_entities("mgnrega spend", ["MGNREGA"], mentions={}))
    pipeline.extract_entity_mentions = orig_extract
    check("default path unchanged: resolve_entities() still calls the LLM extractor", len(calls) == 1)
    check("mentions=... skips the extractor (an empty dict included)", len(calls) == 1)

    async def _boom(*_a, **_kw):
        raise RuntimeError("resolver exploded")
    orig_re = pipeline.resolve_entities
    pipeline.resolve_entities = _boom
    f = run(frame(q="x", schemes=["MGNREGA"], geo_mentions=[{"text": "wgh"}]), "x")
    pipeline.resolve_entities = orig_re
    check("never raises: an unexpected error becomes a note",
          any("resolver exploded" in n for n in f.normalise_notes), str(f.normalise_notes))
finally:
    settings.ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED = False

print("\n=== resolver stage 6b is flag-gated (default off) ===")
check("ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED defaults to False",
      type(settings).model_fields["ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED"].default is False)
r = asyncio.run(entity_resolver.resolve_dimension("westgaro hils", "MGNREGA", "district"))
check("flag off: 'westgaro hils' behaves exactly as before (not resolved in memory)", r.status != "resolved",
      r.status)
settings.ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED = True
r = asyncio.run(entity_resolver.resolve_dimension("est garo hills", "MGNREGA", "district"))
check("flag on: equally-close typo is 'ambiguous' (asked, never guessed)", r.status == "ambiguous", r.status)
r = asyncio.run(entity_resolver.resolve_dimension("wgh", "MGNREGA", "district"))
check("flag on: exact alias path still wins (stage 2)", r.status == "resolved" and r.confidence == 1.0)
r = asyncio.run(entity_resolver.resolve_dimension("south westgaro hils", "MGNREGA", "district"))
check("flag on: nested name the other way round -> SOUTH WEST GARO HILLS",
      r.status == "resolved" and r.canonical == "SOUTH WEST GARO HILLS", f"{r.status} {r.canonical}")
settings.ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED = False

print()
if _fails:
    print(f"FAILED {len(_fails)}: {_fails}")
    sys.exit(1)
print("ALL NORMALISE CHECKS PASSED")

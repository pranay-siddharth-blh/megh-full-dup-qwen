"""Live sweep: every place level, decided by the database (user rule 2026-10-21 19:50).

"If the name is a block, go to block; a village, go to village; a constituency, go
to constituency. If the same name is at several levels, ask." This sweep builds its
cases from the database itself (entity_resolver's village index + the YAML block /
constituency catalogues), never from a hand-picked list, and asks one fresh-chat
question per name through the router-like in-process conversation:

  - a name at exactly one level        -> answered at that level (the right block /
                                          village code; a constituency may ask
                                          "whole constituency or part?")
  - a name at 2+ levels                 -> the level question, unless the scheme holds
                                          no constituency data and one reading is left
  - several villages of the same name   -> the "which village?" question

    .venv/Scripts/python.exe tests/live_place_hierarchy_sweep.py [--schemes MGNREGA,PMAY-G]
        [--villages 40] [--seed 7] [--out <file.json>]

Needs the VPN (megh_db + gateway). Writes a JSON report of every case.
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))

from app import entity_resolver as er  # noqa: E402
from app import pipeline as p  # noqa: E402
from app.session_store import SessionStore  # noqa: E402
from conversation_harness.drivers import _InProcessConversation  # noqa: E402

_QUESTION = {
    "MGNREGA": "What was the total MGNREGA expenditure in {name} during FY 2023-24?",
    "PMAY-G": "How many PMAY-G houses were sanctioned in {name} in FY 2023-24?",
}
# Schemes whose questions here have a constituency column (_ac_dimension_available).
_AC_DATA = {"MGNREGA"}

_CAPTURED: dict = {}
_entity_stage = p._data_entity_stage


async def _spy(d, scope=None):
    r = await _entity_stage(d, scope)
    _CAPTURED["resolved"] = (d.get("entity_result") or {}).get("resolved")
    return r

p._data_entity_stage = _spy


def _cases(scheme: str, n_villages: int, seed: int) -> list:
    cat = er._catalog.get(scheme) or {}
    names: dict = {}
    for dim in ("block", "assembly_constituency"):
        for v in er._collision_values(scheme, dim):
            names.setdefault(str(v["canonical"]).upper(), set())
    for nm in list(names):
        names[nm] = er.place_levels(nm)
    codes = er._village_scheme_codes.get(scheme, frozenset())
    single_villages = [k for k, vs in (er._village_places or {}).items()
                       if len(vs) == 1 and vs[0][0] in codes and er.place_levels(k) == {"village"}
                       and len(k) >= 4]
    multi_villages = [k for k, vs in (er._village_places or {}).items()
                      if len({c for c, _b, _d in vs}) > 1 and any(c in codes for c, _b, _d in vs)
                      and er.place_levels(k) == {"village"}]
    rnd = random.Random(seed)
    out = []
    for nm, levels in sorted(names.items()):
        out.append({"name": nm.title(), "levels": sorted(levels), "kind": "catalogue"})
    for nm in rnd.sample(sorted(single_villages), min(n_villages, len(single_villages))):
        out.append({"name": nm.title(), "levels": ["village"], "kind": "village",
                    "code": er.village_places(nm)[0][0]})
    for nm in rnd.sample(sorted(multi_villages), min(max(5, n_villages // 4), len(multi_villages))):
        out.append({"name": nm.title(), "levels": ["village"], "kind": "same-name villages"})
    _ = cat
    return out


def _expect(case: dict, scheme: str, question: str) -> str:
    """The outcome the rule asks for, from the same facts the pipeline reads: the
    database's levels, whether this question's metric has a constituency column
    (_ac_dimension_available), and whether the scheme holds rows for the village."""
    levels = set(case["levels"])
    # A block only another scheme's catalogue holds (Tura: a CM Elevate urban
    # body) is no block of THIS scheme.
    if "block" in levels and len(levels) > 1 and not any(
            er.fold(f) == er.fold(case["name"])
            for v in er._catalog.get(scheme, {}).get("block", []) for f in er._match_forms(v)):
        levels.discard("block")
    # A district reached only through an alias (its HQ town: Jowai, Nongpoh) is not
    # a district of that NAME (D-059 §6) when another level remains.
    if "district" in levels and len(levels) > 1 and not any(
            er.fold(str(v["canonical"])) == er.fold(case["name"])
            for v in er._catalog.get(scheme, {}).get("district", [])):
        levels.discard("district")
    if "assembly_constituency" in levels and len(levels) > 1 and not p._ac_dimension_available(question, [scheme]):
        levels.discard("assembly_constituency")
    if "village" in levels and len(levels) > 1 and er.village_scheme_data(case["name"], scheme) is False:
        levels.discard("village")
    codes = er._village_scheme_codes.get(scheme)
    with_data = [(c, b, d) for c, b, d in er.village_places(case["name"]) if codes is None or c in codes]
    if case["kind"] == "same-name villages" or (levels == {"village"} and len(with_data) > 1):
        # Only same-name villages the scheme holds rows for compete (c09 keeps
        # "candidates that hold <scheme> data"); duplicates of one block collapse.
        places = {(b, d) for _c, b, d in with_data}
        # The village whose REAL name is the typed one wins over villages that
        # only carry it as an alias (c09: "the candidate spelled exactly as typed").
        real = [c for c, _b, _d in with_data
                if er.fold(er._village_code_names.get(c, "")) == er.fold(case["name"])]
        if len(real) == 1:
            case["code"] = real[0]
            return "village"
        return "village-pause" if len(places) > 1 else "village-any"
    if len(levels) >= 2:
        return "level-pause"
    if levels == {"village"}:
        return "village"
    if levels == {"block"}:
        return "block"
    if levels == {"assembly_constituency"}:
        return "constituency"
    if levels == {"district"}:
        return "district"
    return "unknown"


def _judge(case: dict, expect: str, rec, resolved: dict) -> bool:
    resolved = resolved or {}
    text = (rec.answer or "").lower()
    # A name at 2+ levels in ANY catalogue may always be asked about (the rule:
    # "if the same name is there … ask"), even where this scheme narrows it.
    if expect in ("village", "block", "constituency", "district") and len(case["levels"]) > 1             and rec.route == "pause" and rec.pause_rule == "entity-ambiguous":
        return True
    if expect == "level-pause":
        return rec.route == "pause" and rec.pause_rule == "entity-ambiguous" and (
            "kind of area" in text or "could mean either" in text)
    if expect == "village-pause":
        return rec.route == "pause" and "more than one village" in text
    if expect == "village-any":
        codes = {c for c, _b, _d in er.village_places(case["name"])} | set(case.get("_alias_codes", ()))
        return rec.route == "data" and resolved.get("village_code") in codes
    if expect == "village":
        return rec.route == "data" and resolved.get("village_code") == case.get("code", resolved.get("village_code")) \
            and bool(resolved.get("village_code"))
    if expect == "block":
        # The catalogue's canonical block ("Sohing" is an alias of SOHIONG).
        r = er.resolve_dimension(case["name"], case.get("_scheme", ""), "block")
        want = {case["name"].upper(), str(r.canonical or "").upper()} if r.status == "resolved" else {case["name"].upper()}
        return rec.route == "data" and str(resolved.get("block") or "").upper() in want
    if expect == "district":
        r = er.resolve_dimension(case["name"], case.get("_scheme", ""), "district")
        return rec.route == "data" and r.status == "resolved" \
            and str(resolved.get("district") or "").upper() == str(r.canonical).upper()
    if expect == "constituency":
        # Answered for that constituency, or its own "whole constituency or part?"
        # pause — never another place's figure.
        return (rec.route == "data" and str(resolved.get("assembly_constituency") or "").upper()
                == case["name"].upper()) or (rec.route == "pause" and "constituency" in text
                                             and case["name"].lower() in text)
    return False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schemes", default="MGNREGA,PMAY-G")
    ap.add_argument("--villages", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="", help="comma-separated names (any level) to run alone")
    args = ap.parse_args()
    from app import main as app_main
    store = SessionStore(ttl=3600, max_sessions=5000, max_turns=10)
    report, failed, total = [], 0, 0
    t0 = time.time()
    out = args.out or os.path.join("logs", f"place_hierarchy_sweep_{time.strftime('%Y-%m-%d_%H%M')}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    only = {n.strip().upper() for n in args.only.split(",") if n.strip()}
    async with app_main.lifespan(app_main.app):
        for scheme in args.schemes.split(","):
            if only:
                cases = [{"name": n.title(), "levels": sorted(er.place_levels(n)), "kind": "only",
                          **({"code": er.village_places(n)[0][0]} if len(er.village_places(n)) == 1 else {})}
                         for n in sorted(only)]
            else:
                cases = _cases(scheme, args.villages, args.seed)
            for case in cases:
                q = _QUESTION[scheme].format(name=case["name"])
                case["_scheme"] = scheme
                expect = _expect(case, scheme, q)
                _CAPTURED.clear()
                try:
                    rec = await _InProcessConversation(store).ask(q)
                    ok = _judge(case, expect, rec, _CAPTURED.get("resolved"))
                    row = {"route": rec.route, "rule": rec.pause_rule, "answer": (rec.answer or "")[:220],
                           "chips": rec.chips[:6] if rec.chips else []}
                except Exception as e:  # noqa: BLE001 — a crash is a failed case, not the end of the sweep
                    ok, row = False, {"route": "crash", "rule": None, "answer": f"{type(e).__name__}: {e}"[:220],
                                      "chips": []}
                total += 1
                failed += not ok
                report.append({"scheme": scheme, **case, "expect": expect, "ok": ok, **row,
                               "resolved": _CAPTURED.get("resolved")})
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=1, default=str)
                if not ok:
                    print(f"FAIL [{scheme}] {case['name']} levels={case['levels']} expect={expect} "
                          f"-> {row['route']}/{row['rule']}: {row['answer'][:140]!r} "
                          f"resolved={_CAPTURED.get('resolved')}", flush=True)
    print(f"\n{total - failed}/{total} passed in {time.time() - t0:.0f}s")
    print("saved", out)
    return failed


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)

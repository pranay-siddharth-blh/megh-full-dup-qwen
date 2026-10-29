"""LIVE spelling / variant-name suite (spelling-fix brief, 2026-10-29).

The user's brief (megh_chatbot_spelling_fix_prompt.md) gave ten typed-fast questions
(T1-T10) with the answer the correctly spelled question gets. They were asked in ONE
chat, in order, so T4 follows T3 (a different place) and T6 is sent while T5's
scheme picker is still open. This suite replays that chat (group "chat"), then asks
each case again in a fresh chat ("fresh"), plus the brief's other live groups:
"neg" (made-up places: never another place's figure), "ctx" (pickers and carried
places), "kb" (22 misspelt knowledge questions, each beside its correctly spelt twin:
the same reference document), "vil" (50 random villages with generated typos, read
by the data path's own village reader). The offline half is
tests/test_spelling_resolution_2026_10_29.py.

Not collected by pytest (not named test_*.py). Needs the office VPN (megh_db + gateway).

    .venv/Scripts/python.exe tests/live_chat_spelling.py
    .venv/Scripts/python.exe tests/live_chat_spelling.py --only chat,T4
    .venv/Scripts/python.exe tests/live_chat_spelling.py --only kb,vil
    .venv/Scripts/python.exe tests/live_chat_spelling.py --out logs/spelling.json

Expected values are the brief's (the correctly spelled answers, D1-D6/D8 of
live_chat_golden.py). Never change one to make a case pass.
Exit code: 0 all passed, 1 a case failed.
"""
import argparse
import asyncio
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")     # "₹" on a Windows console
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))

from conversation_harness.drivers import InProcessDriver  # noqa: E402


def case(cid, question, *, has=(), any_of=(), lacks=(), pause=False, knowledge=False, pick=True, why=""):
    """has: all must be in the answer; any_of: lists, one of each must be; lacks: none may be;
    pause: True = a clarification is right, False = it must answer, None = either;
    knowledge: the answer must come from the knowledge path."""
    return {"id": cid, "q": question, "has": list(has), "any_of": [list(a) for a in any_of], "lacks": list(lacks),
            "pause": pause, "knowledge": knowledge, "pick": pick, "why": why}


# T1-T10, in the order the user asked them in one chat.
CHAT = [
    case("T1", "total narega persondays statwide in 2023-24", has=["2,72,64,054"]),
    case("T2", "mgnrega expendture in west garo hils 2024-25", any_of=[["25,701.49 lakh", "257.01 crore"]]),
    case("T3", "pmayg houses sanctiond in east kasi hill 2019-20", has=["542"]),
    case("T4", "womens share in mgnrega employmnt in ribhoy 2023-24", has=["55.76", "Ri Bhoi"],
         lacks=["75.99", "East Khasi"], why="never the previous turn's place"),
    case("T5", "how many fokus plus benificiaries in 2022-23", has=["93,286"]),
    case("T6", "housholds completed 100 days in east garo hils 2022-23", has=["22,049"],
         why="a full question is never taken as a reply to an old picker"),
    case("T7", "person days in mawkyrwt block 2023-24", has=["8,65,252"]),
    case("T8", "persondays in jakrm village 2023-24", has=["75,498"]),
    case("T9", "narega in mawryngkning village 2023-24", has=["91,425"], pause=None,
         why="a pick-list with the right village first is fine; the harness picks the first option"),
    case("T10", "how much mony does fokus+ give per houshold", has=["5,000"], knowledge=True),
]

# Negatives (brief §4 E): never an answer for another place.
NEG = [
    case("E1", "mgnrega person days in zorbatown district 2023-24", lacks=["2,72,64,054"], pause=None,
         any_of=[["couldn't find", "could not find", "not find", "no district", "not a district", "isn't",
                  "not in meghalaya", "not one of", "did you mean", "which place", "no place"]], pick=False),
    case("E2", "mgnrega person days in gotham block 2023-24", pause=None,
         any_of=[["couldn't find", "could not find", "not find", "no block", "not a block", "isn't",
                  "not in meghalaya", "not one of", "did you mean", "which place", "no place"]], pick=False),
    case("E3", "mgnrega person days in guwahati 2023-24", pause=None,
         any_of=[["couldn't find", "could not find", "not find", "not in meghalaya", "outside", "isn't",
                  "not one of", "did you mean", "assam", "only know meghalaya"]], pick=False,
         why="a real place outside Meghalaya: the edge's out-of-area reply, never another place's figure"),
]

# T4 / T6 checked again in the exact situation that failed.
CONTEXT = [
    ("F1", ["pmay-g houses sanctioned in east khasi hills 2019-20",
            "womens share in mgnrega employmnt in ribhoy 2023-24"],
     case("F1", "", has=["55.76"], lacks=["75.99"])),
    ("F2", ["how many beneficiaries in 2022-23",
            "housholds completed 100 days in east garo hils 2022-23"],
     case("F2", "", has=["22,049"])),
    # a SHORT reply to an open picker is its answer (brief §4 F)
    ("F3", ["how many person days in 2023-24", "mgnrega"],
     case("F3", "", has=["2,72,64,054"])),
    # a misspelt place after a turn on another place: never the old place
    ("F4", ["mgnrega person days in west garo hills 2023-24", "and in ribhoy?"],
     case("F4", "", lacks=["West Garo Hills"], any_of=[["Ri Bhoi"]])),
]

# G. Misspelt knowledge questions (brief §4 G), each beside its twin: THE SAME WORDS spelt
# right ("use the correctly spelled answer as the expected value"). The typo must take
# the twin's route and reach the same scheme's reference documents.
KB = [
    ("G1", "how many days of work does narega gurantee", "how many days of work does MGNREGA guarantee"),
    ("G2", "job crd how to apply", "job card how to apply"),
    ("G3", "what is the mgnrega wage rate in meghalya", "what is the MGNREGA wage rate in Meghalaya"),
    ("G4", "who is elegible for mgnrega", "who is eligible for MGNREGA"),
    ("G5", "mgnrega unemployment alowance", "MGNREGA unemployment allowance"),
    ("G6", "pmay gramin lanch year", "PMAY-G launch year"),
    ("G7", "how much asistance does pmayg give per house", "how much assistance does PMAY-G give per house"),
    ("G8", "who is eligble for awas yojana", "who is eligible for PMAY-G"),
    # (was "how are pmay-g benificiaries selected": its correctly spelt twin is routed as a
    # data question, so it tested wording, not spelling)
    ("G9", "what is pmayg skeme", "what is PMAY-G scheme"),
    ("G10", "how much mony does fokus+ give per houshold", "how much money does Focus Plus give per household"),
    ("G11", "who can aply for fokus plus", "who can apply for Focus Plus"),
    ("G12", "fokus plus payment method", "Focus Plus payment method"),
    ("G13", "what is focus plus skeme", "what is Focus Plus scheme"),
    ("G14", "focus legasy loan or grant", "Focus Legacy loan or grant"),
    ("G15", "focus legacy producer grup payment amount", "Focus Legacy producer group payment amount"),
    ("G16", "what is old focus skeme", "what is Focus Legacy scheme"),
    ("G17", "cm elivate subsidy", "CM Elevate subsidy"),
    ("G18", "how to aply for cm elevate", "how to apply for CM Elevate"),
    ("G19", "cm elevate eligiblity", "CM Elevate eligibility"),
    ("G20", "what is cm elevte", "what is CM Elevate"),
    ("G21", "cm elevate legasy what is it", "CM Elevate Legacy what is it"),
    ("G22", "focus plus benifit per famly", "Focus Plus benefit per family"),
]


def _folder(doc: str) -> str:
    """"CM_Elevate/cmelevate_general_faq.md" -> "CM_Elevate" (one scheme's documents)."""
    return doc.replace("\\", "/").split("/")[0]


def _docs(rec) -> set:
    return {str(s.get("doc") or s.get("title") or "") for s in ((rec.raw or {}).get("sources") or [])
            if isinstance(s, dict)} - {""}


async def village_cases(n: int = 50) -> list:
    """C. 50 random single-place villages, each typed with generated typos, read by the
    data path's own village reader (c09 _resolve_village_for) after app/spelling.py."""
    import random
    from app import entity_resolver as er
    from app import pipeline as p
    from app import spelling as sp
    await er.load_village_names()
    rnd = random.Random(20261029)
    names = sorted(k for k in er._village_keys() if " " not in k and len(k) >= 7
                   and len(er.village_places(k)) == 1)
    out = []
    for name in rnd.sample(names, n):
        w = name.lower()
        i = rnd.randrange(2, len(w) - 2)
        typos = [w[:i] + w[i + 1:], w[:i] + w[i + 1] + w[i] + w[i + 2:]]
        for a, b in (("y", "i"), ("kh", "k"), ("w", "u"), ("ng", "n")):
            if a in w:
                typos.append(w.replace(a, b, 1))
                break
        for t in dict.fromkeys(typos):
            if er.is_village_name(t):
                continue                  # the "typo" is another real village's name: not a typo
            text = sp.normalise(f"in {t} village").text[len("in "):-len(" village")]
            r = await p._resolve_village_for(["MGNREGA"], text)
            # By village CODE: the index holds aliases, so the right village may be
            # offered under its official name (alias DARONGGRE is village DARONGGRI).
            got = {str(c.get("village_code")) for c in r.candidates or []}
            codes = {str(c) for c, _b, _d in er.village_places(name)}
            ok = (r.status == "resolved" and str(r.canonical) in codes) \
                or (r.status == "ambiguous" and bool(got & codes))
            wrong = r.status == "resolved" and not ok
            out.append({"village": name, "typed": t, "status": r.status, "ok": ok, "wrong": wrong})
    return out


def judge(c, rec) -> list:
    fails = []
    text = rec.answer or ""
    low = text.lower()
    if c["pause"] is True and rec.route != "pause":
        fails.append("expected a clarification")
    if c["pause"] is False and rec.route in ("pause", "error"):
        return [f"no answer: {rec.route}"]
    for s in c["has"]:
        if s not in text:
            fails.append(f"missing {s!r}")
    for alts in c["any_of"]:
        if not any(a.lower() in low for a in alts):
            fails.append(f"none of {alts!r}")
    for s in c["lacks"]:
        if s in text:
            fails.append(f"must not say {s!r}")
    if c["knowledge"] and rec.route not in ("knowledge", "rag"):
        fails.append(f"route {rec.route} is not knowledge")
    return fails


async def ask(conv, c):
    """Ask; on a pick-list (pause=None, pick=True) tap the first chip as the UI does:
    it sends the chip's QUESTION, not its label."""
    conv.last_options = []
    rec = await conv.ask(c["q"])
    opts = [o for o in (getattr(conv, "last_options", None) or []) if o.get("question")]
    if rec.route == "pause" and c["pause"] is None and c["pick"] and opts:
        first = await conv.ask(opts[0]["question"])
        first.answer = f"[tapped {opts[0].get('label')!r}] " + (first.answer or "")
        return rec, first
    return rec, rec


def show(cid, mode, rec, fails, secs):
    print(f"{'PASS' if not fails else 'FAIL'} {cid:<4} {mode:<6} {rec.route:<9} {secs:>5}s"
          + ("" if not fails else "  " + "; ".join(fails)), flush=True)
    if fails:
        print("      " + (rec.answer or "").replace("\n", "\n      ")[:700], flush=True)
        if rec.chips:
            print(f"      chips: {rec.chips}", flush=True)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list: chat, fresh, neg, ctx, kb, vil, or case ids")
    ap.add_argument("--out")
    args = ap.parse_args()
    want = set((args.only or "chat,fresh,neg,ctx,kb,vil").split(","))

    def on(group, cid=""):
        return group in want or cid in want

    results, failed = [], 0
    async with InProcessDriver() as d:
        if on("chat"):
            conv = d.new_conversation()
            for c in CHAT:
                t0 = time.perf_counter()
                first, rec = await ask(conv, c)
                fails = judge(c, rec)
                failed += bool(fails)
                show(c["id"], "chat", rec, fails, round(time.perf_counter() - t0, 1))
                results.append({"id": c["id"], "mode": "chat", "q": c["q"], "route": rec.route,
                                "answer": rec.answer, "fails": fails})
        for group, cases in (("fresh", CHAT), ("neg", NEG)):
            for c in cases:
                if not on(group, c["id"]):
                    continue
                t0 = time.perf_counter()
                first, rec = await ask(d.new_conversation(), c)
                fails = judge(c, rec)
                failed += bool(fails)
                show(c["id"], group, rec, fails, round(time.perf_counter() - t0, 1))
                results.append({"id": c["id"], "mode": group, "q": c["q"], "route": rec.route,
                                "answer": rec.answer, "fails": fails})
        for cid, turns, c in CONTEXT:
            if not on("ctx", cid):
                continue
            conv = d.new_conversation()
            t0 = time.perf_counter()
            for t in turns[:-1]:
                await conv.ask(t)
            rec = await conv.ask(turns[-1])
            fails = judge(c, rec)
            failed += bool(fails)
            show(cid, "ctx", rec, fails, round(time.perf_counter() - t0, 1))
            results.append({"id": cid, "mode": "ctx", "q": turns, "route": rec.route, "answer": rec.answer,
                            "fails": fails})
        if on("kb") or any(cid in want for cid, _t, _w in KB):
            for cid, typo, twin in KB:
                if not on("kb", cid):
                    continue
                t0 = time.perf_counter()
                rec = await d.new_conversation().ask(typo)
                ref = await d.new_conversation().ask(twin)
                # The typo must go where its correctly spelt twin goes, and to the same
                # scheme's reference documents (a scheme's FAQ and its complete reference
                # both hold its rules). A twin that is itself not a knowledge question is
                # this list's wording problem, said separately, not a spelling failure.
                fails = []
                if ref.route != "knowledge":
                    fails.append(f"TWIN not knowledge ({ref.route}): reword the pair")
                elif rec.route != "knowledge":
                    fails.append(f"route {rec.route}")
                elif _docs(ref) and not ({_folder(x) for x in _docs(rec)} & {_folder(x) for x in _docs(ref)}):
                    fails.append(f"other scheme's documents: {sorted(_docs(rec))} vs {sorted(_docs(ref))}")
                failed += bool(fails)
                show(cid, "kb", rec, fails, round(time.perf_counter() - t0, 1))
                results.append({"id": cid, "mode": "kb", "q": typo, "twin": twin, "route": rec.route,
                                "answer": rec.answer, "twin_answer": ref.answer, "docs": sorted(_docs(rec)),
                                "twin_docs": sorted(_docs(ref)), "fails": fails})
    vil_rate = None
    if on("vil"):
        vs = await village_cases()
        ok = sum(v["ok"] for v in vs)
        wrong = [v for v in vs if v["wrong"]]
        vil_rate = ok / len(vs)
        print(f"\nvillages: {ok}/{len(vs)} ({vil_rate:.0%}) read; {len(wrong)} read as ANOTHER village")
        for v in [v for v in vs if not v["ok"]][:25]:
            print(f"      {v['typed']!r} -> {v['status']} (want {v['village']})")
        results.append({"id": "C-villages", "mode": "vil", "rate": vil_rate, "wrong": wrong,
                        "missed": [v for v in vs if not v["ok"]],
                        "fails": (["< 95%"] if vil_rate < 0.95 else []) + (["wrong village"] if wrong else [])})
        failed += bool(results[-1]["fails"])
    print(f"\n{len(results) - failed}/{len(results)} passed")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1, ensure_ascii=False, default=str)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

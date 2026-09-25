"""How often the shadow QueryFrame agrees with what the current pipeline
detected — schemes, geography, year (and intent vs route) — and every
disagreement, for a run made with `run_eval.py --understand-shadow`.

    python tests/eval/frame_agreement.py tests/eval/results/eval_<run>.json

Compared on turns the pipeline actually ANSWERED (data / knowledge / edge):
a clarification response doesn't expose what the pipeline had detected when
it paused, so there is nothing to compare against on those turns.

  schemes  frame.schemes vs the answer's schemes (set equality)
  geo      frame geo_mentions, resolved to canonical districts/blocks with the
           real entity_resolver, vs the answer's resolved district/block;
           a village match = pipeline pinned a village_code and the frame named
           a place that is not a district/block. "Meghalaya"/state = no filter.
  year     pipeline._parse_year_key(frame.year_text) vs the answer's year_key
  intent   frame.intent vs route (data->DATA, knowledge->KNOWLEDGE, edge->EDGE)

Cases whose messages are in the Understand prompt's few-shot examples
(data/understand_few_shot.yaml `from:`) are reported separately — the model
has seen them. Writes <run>_frame_agreement.md next to the results file.
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("JWT_SECRET", "eval-report-only-secret-at-least-32-chars")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import yaml  # noqa: E402

from app.nlu import entity_resolver  # noqa: E402
from app.orchestration import pipeline  # noqa: E402

ROUTE_INTENT = {"data": "DATA", "knowledge": "KNOWLEDGE", "edge": "EDGE"}
STATEWIDE = {"meghalaya", "all of meghalaya", "state", "statewide", "state-wide", "whole state"}


async def _canon_geo(mentions: list[dict], schemes: list[str]) -> tuple[set, list]:
    """Frame mentions -> ({("district"|"block", CANONICAL)}, [unresolved texts])."""
    scheme = (schemes or ["MGNREGA"])[0]
    out, other = set(), []
    for g in mentions or []:
        text = (g.get("text") or "").strip()
        if not text or g.get("level") == "state" or text.lower() in STATEWIDE:
            continue
        hit = None
        order = ("block", "district") if g.get("level") == "block" else ("district", "block")
        for dim in order:
            try:
                r = await entity_resolver.resolve_dimension(text, scheme, dim)
            except Exception:  # noqa: BLE001
                continue
            if r.status == "resolved":
                hit = (dim, str(r.canonical).upper())
                break
        if hit:
            out.add(hit)
        else:
            other.append(text)
    return out, other


def _pipeline_geo(resolved: dict) -> tuple[set, bool]:
    geo = set()
    if resolved.get("district"):
        geo.add(("district", str(resolved["district"]).upper()))
    if resolved.get("block"):
        geo.add(("block", str(resolved["block"]).upper()))
    return geo, bool(resolved.get("village_code"))


async def main(path: str):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    entity_resolver.load_all()
    seen = {e["from"] for e in yaml.safe_load(
        (ROOT / "data" / "understand_few_shot.yaml").read_text(encoding="utf-8"))["examples"]}

    stats = {g: collections.Counter() for g in ("held_out", "few_shot")}
    frames_total = frames_ok = 0
    flags = collections.Counter()
    disagreements = collections.defaultdict(list)
    for r in doc["results"]:
        group = "few_shot" if r["id"] in seen else "held_out"
        for t in r["turns"]:
            u = t.get("understand")
            if u is None:
                continue
            frames_total += 1
            f = u.get("frame")
            for fl in (u.get("meta") or {}).get("flags") or []:
                flags[fl.split(":")[0]] += 1
            if not f:
                stats[group]["no_frame"] += 1
                continue
            frames_ok += 1
            if t["route"] not in ROUTE_INTENT:
                continue
            c = stats[group]
            c["compared_turns"] += 1
            row = {"case": r["id"], "say": t["say"], "route": t["route"]}

            ok = f["intent"] == ROUTE_INTENT[t["route"]]
            c["intent_agree"] += ok
            if not ok:
                disagreements["intent"].append({**row, "frame": f["intent"], "pipeline": t["route"]})

            fs, ps = sorted(f.get("schemes") or []), sorted(t.get("schemes") or [])
            ok = fs == ps
            c["schemes_agree"] += ok
            if not ok:
                disagreements["schemes"].append({**row, "frame": fs, "pipeline": ps})

            res = t.get("resolved_entities") or {}
            fgeo, fother = await _canon_geo(f.get("geo_mentions") or [], f.get("schemes") or t.get("schemes"))
            pgeo, pvillage = _pipeline_geo(res)
            ok = fgeo == pgeo and (bool(fother) == pvillage)
            c["geo_agree"] += ok
            if not ok:
                disagreements["geo"].append({**row, "frame": [g["text"] for g in f.get("geo_mentions") or []],
                                             "frame_resolved": sorted(fgeo), "frame_unresolved": fother,
                                             "pipeline": sorted(pgeo) + (["village_code"] if pvillage else [])})

            fy = pipeline._parse_year_key(f.get("year_text") or "") if f.get("year_text") else None
            py = res.get("year_key")
            ok = fy == py
            c["year_agree"] += ok
            if not ok:
                disagreements["year"].append({**row, "frame": f.get("year_text"), "frame_year_key": fy,
                                              "pipeline": py})

            # After normalise_frame (Step 3): same fields, from the frame's
            # canonical values — resolved_schemes and entity_result, which has
            # resolve_entities()' exact shape, so it compares key for key.
            if "resolved_schemes" in f:
                c["norm_turns"] += 1
                ok = sorted(f.get("resolved_schemes") or []) == ps
                c["norm_schemes_agree"] += ok
                if not ok:
                    disagreements["norm_schemes"].append({**row, "frame": sorted(f.get("resolved_schemes") or []),
                                                          "sources": f.get("scheme_sources"), "pipeline": ps})
                nres = (f.get("entity_result") or {}).get("resolved") or {}
                geo_keys = ("district", "block", "village_code", "district_list", "block_list")
                ng = {k: nres.get(k) for k in geo_keys if nres.get(k)}
                pg = {k: res.get(k) for k in geo_keys if res.get(k)}
                ok = ng == pg
                c["norm_geo_agree"] += ok
                if not ok:
                    disagreements["norm_geo"].append({**row, "frame": ng, "pipeline": pg,
                                                      "frame_clarification": (f.get("clarification") or {}).get("rule"),
                                                      "notes": f.get("normalise_notes")})
                ny = nres.get("year_key", f.get("year_key"))
                ok = ny == py
                c["norm_year_agree"] += ok
                if not ok:
                    disagreements["norm_year"].append({**row, "frame": ny, "year_text": f.get("year_text"),
                                                       "pipeline": py})

    def pct(n, d):
        return f"{100.0 * n / d:.1f}%" if d else "-"

    lines = [f"# Frame agreement — {doc['run_id']}", "",
             f"Frames produced: {frames_ok}/{frames_total} turns "
             f"({frames_total - frames_ok} missing: model error/timeout).", "",
             "| cases | compared turns | intent | schemes | geo | year |", "|---|---|---|---|---|---|"]
    for g, c in stats.items():
        n = c["compared_turns"]
        lines.append(f"| {g} | {n} | {pct(c['intent_agree'], n)} | {pct(c['schemes_agree'], n)} | "
                     f"{pct(c['geo_agree'], n)} | {pct(c['year_agree'], n)} |")
    if any(c["norm_turns"] for c in stats.values()):
        lines += ["", "After normalise_frame (canonical values, resolve_entities() shape):", "",
                  "| cases | compared turns | schemes | geo | year |", "|---|---|---|---|---|"]
        for g, c in stats.items():
            n = c["norm_turns"]
            lines.append(f"| {g} | {n} | {pct(c['norm_schemes_agree'], n)} | "
                         f"{pct(c['norm_geo_agree'], n)} | {pct(c['norm_year_agree'], n)} |")
    lines += ["", "Guard flags raised (model output not supported by the text):", ""]
    lines += [f"- {k}: {v}" for k, v in flags.most_common()] or ["- none"]
    for field in ("schemes", "geo", "year", "intent", "norm_schemes", "norm_geo", "norm_year"):
        items = disagreements[field]
        lines += ["", f"## {field} disagreements ({len(items)})", ""]
        for d in items:
            extra = {k: v for k, v in d.items() if k not in ("case", "say", "route")}
            lines.append(f"- `{d['case']}` [{d['route']}] \"{d['say'][:100]}\" — "
                         + "; ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in extra.items()))
    report = "\n".join(lines) + "\n"
    out = Path(path).with_name(Path(path).stem + "_frame_agreement.md")
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1]))

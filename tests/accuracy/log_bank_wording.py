"""Wording audit of a log-bank results JSON (16 Nov 2026): counts the robotic or misleading patterns the user
flagged in the answers, with examples. No model call.

    python tests/accuracy/log_bank_wording.py tests/accuracy/results/<run>.json
"""
from __future__ import annotations

import json
import re
import sys

PATTERNS = {
    "money twice (≈)": re.compile("≈"),
    "small crore (₹0.xx crore)": re.compile(r"₹0\.\d+ crore"),
    "UPPERCASE place name": re.compile(r"\b(?:the |in |for )?[A-Z]{4,}(?: [A-Z]{3,})*\b block|\bthe [A-Z]{4,} block|\b[A-Z]{5,}\b"),
    "'This is the X figure' tail": re.compile(r"This is the [A-Za-z\- ]+ figure"),
    "'financial year FY' doubled": re.compile(r"financial year FY|FY FY"),
    "opens with 'Yes,' (polite 'can you' read literally)": re.compile(r"^\s*Yes\b"),
    "ISO date as a month": re.compile(r"\b20\d\d-\d\d-01\b"),
    "'N results match in total'": re.compile(r"results match in total"),
    "double space": re.compile(r"\S  \S"),
}
ALLOW_UPPER = {"MGNREGA", "PMAY", "CMSS", "FOCUS", "DBT", "LGD", "MIS", "CPI", "AL", "NREGA", "PRODUCER", "GROUPS",
               "INDIVIDUAL"}


def main(path: str) -> int:
    with open(path, encoding="utf-8") as fh:
        res = json.load(fh)["results"]
    hits = {k: [] for k in PATTERNS}
    n = 0
    for r in res:
        for t in r["turns"]:
            a = t.get("answer") or ""
            if t.get("route") not in ("data", "knowledge", "edge") or t.get("local_view"):
                continue
            n += 1
            for k, rx in PATTERNS.items():
                m = [x for x in rx.findall(a) if not (k.startswith("UPPER") and x.strip().split()[-1] in ALLOW_UPPER)]
                if k.startswith("UPPER"):
                    m = [x for x in m if not set(x.replace(" block", "").split()) <= ALLOW_UPPER]
                if m:
                    hits[k].append((r["id"], t["q"], m[0], a[:200].replace("\n", " / ")))
    print(f"{n} answers audited")
    for k, h in hits.items():
        print(f"\n{k}: {len(h)} answers")
        for x in h[:3]:
            print(f"  {x[0]} | {x[1][:80]} | {x[2]!r} | {x[3][:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

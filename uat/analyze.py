"""uat/analyze.py [N] — failures (latest row per test) grouped by category and pattern; N samples of 'other'."""
import collections
import csv
import sys

csv.field_size_limit(10 ** 8)
last = {}
for r in csv.DictReader(open("uat/results.csv", newline="", encoding="utf-8")):
    last[r["id"]] = r


def pat(r):
    a, q = r["actual"], r["question"]
    if "data is available only for the financial years" in a:
        return "D1 FY-legacy-pause"
    if r["category"] == "C12_followup" and all(x.strip().startswith("T3") for x in r["fails"].split(";") if x.strip()):
        return "D2 chain-T3"
    if r["status"] == "Error":
        return "error"
    if "ward" in q.lower():
        return "ward (N1)"
    if "could refer to more than one kind" in a:
        return "level-collision pause"
    if "couldn't find a place" in a or "could not find" in a.lower():
        return "unknown-place"
    if "Showing results for" in a:
        return "spelling-rewrite"
    return "other"


F = [r for r in last.values() if r["status"] != "Pass"]
print("results", len(last), "non-pass", len(F))
for k, v in sorted(collections.Counter((r["category"], pat(r)) for r in F).items()):
    print(f"  {k[0]:20} {k[1]:24} {v}")
n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
for r in F:
    if pat(r) == "other" and n > 0:
        n -= 1
        print("##", r["id"], "|", r["question"][:120], "| F:", r["fails"][:140])
        print("  A:", r["actual"][:380].encode("ascii", "replace").decode().replace("\n", " / "))
        print("  S:", r["sql"][:200].replace("\n", " "))

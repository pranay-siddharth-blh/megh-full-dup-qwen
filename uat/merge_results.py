"""uat/merge_results.py <other results.csv> <run tag> — append that run's rows to this folder's results.csv
(used for a run made from the clean detached checkout of the final commit, decisions 26)."""
import csv
import os
import sys

csv.field_size_limit(10 ** 8)
HERE = os.path.dirname(os.path.abspath(__file__))
src, tag = sys.argv[1], sys.argv[2]
rows = [r for r in csv.DictReader(open(src, newline="", encoding="utf-8")) if r["run"] == tag]
dst = os.path.join(HERE, "results.csv")
with open(dst, newline="", encoding="utf-8") as fh:
    fields = next(csv.reader(fh))
with open(dst, "a", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=fields)
    for r in rows:
        w.writerow({k: r.get(k, "") for k in fields})
print("appended", len(rows), "rows of", tag)

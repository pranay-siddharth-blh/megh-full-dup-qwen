"""Write the ids of failed cases (optionally of some families) to a file for CROSS_ONLY."""
import json, sys
R = json.load(open(sys.argv[1], encoding="utf-8"))
fams = set(sys.argv[3:])
ids = [k for k, r in R.items() if not r["ok"] and (not fams or r["fam"] in fams)]
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(ids))
print(len(ids), "failed")

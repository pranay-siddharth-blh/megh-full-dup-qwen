#!/bin/bash
# Resume fl_all.py across VPN drops: wait for a steady VPN, run, prune connection-error
# records (so they re-run), repeat until every village has a real result.
G=C:/Users/Admin/AppData/Local/Temp/claude/c--Users-Admin-OneDrive-Desktop-MCP-meghoneai/0505c350-01ce-41d1-bd2c-630d77ef03ea/scratchpad/gentest
PY=C:/Users/Admin/.mvenv/Scripts/python.exe
cd C:/Users/Admin/OneDrive/Desktop/MCP/meghoneai/meghalaya || exit 1
up() { timeout 5 bash -c "</dev/tcp/10.48.242.4/5432" 2>/dev/null && timeout 5 bash -c "</dev/tcp/10.48.242.4/443" 2>/dev/null; }
for round in $(seq 1 30); do
  ok=0
  while [ $ok -lt 6 ]; do if up; then ok=$((ok+1)); else ok=0; fi; sleep 10; done
  echo "round $round: VPN steady, running $(date +%H:%M)"
  PYTHONIOENCODING=utf-8 DB_POOL_MIN_SIZE=2 DB_POOL_MAX_SIZE=6 MG_CONC=4 $PY $G/fl_all.py >> $G/fl_all.log 2>&1
  left=$($PY - <<EOF
import json
d = json.load(open(r"$G/fl_all_results.json", encoding="utf-8"))
bad = lambda c: not c["ok"] and ("error" in (c.get("note") or "") or "Error" in str(c.get("turns", [{}])[-1].get("answer") or "")[:40])
n = sum(1 for v in d.values() for c in v if bad(c))
d = {k: [c for c in v if not bad(c)] for k, v in d.items()}
json.dump(d, open(r"$G/fl_all_results.json", "w", encoding="utf-8"), ensure_ascii=False, default=str)
print(n, sum(len(v) for v in d.values()))
EOF
)
  echo "round $round done $(date +%H:%M): pruned/kept = $left"
  set -- $left
  if [ "$1" = "0" ] && [ "$2" -ge 3384 ]; then echo "ALL DONE"; exit 0; fi
done
echo "GAVE UP after 30 rounds"

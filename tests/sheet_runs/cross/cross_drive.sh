#!/bin/bash
# Cross Scheme sheet re-run 2026-10-30, VPN-proof: wait for a steady VPN, run every family
# of cross_run.py (resumable: cross_results.json keeps every finished case), drop the
# cases that ended in a connection error so they run again, repeat until every case has a
# verdict, then write the workbook. Round 1 also drops every FAILED case, so a fix made
# since the last run is re-tested.
# Usage (repo root): bash tests/sheet_runs/cross/cross_drive.sh <log dir>
OUT=${1:?log dir}
PY=.venv/Scripts/python.exe
cd "$(dirname "$0")/../../.." || exit 1
export PYTHONIOENCODING=utf-8 CROSS_CONC=${CROSS_CONC:-12}
RES=tests/sheet_runs/cross/cross_results.json
FAMS="sheet state rank coverage year dwise words district block ac village"
up() { timeout 5 bash -c "</dev/tcp/10.48.242.4/5432" 2>/dev/null && timeout 5 bash -c "</dev/tcp/10.48.242.4/443" 2>/dev/null; }
vpn() { local ok=0; while [ $ok -lt 6 ]; do if up; then ok=$((ok+1)); else ok=0; fi; sleep 10; done; echo "$(date +%H:%M) VPN steady"; }
# prune <all|errors>: drop the records to run again; prints "<dropped> <kept> <ok>"
prune() { $PY - "$RES" "$1" <<'EOF'
import json, sys
p, mode = sys.argv[1], sys.argv[2]
try:
    d = json.load(open(p, encoding="utf-8"))
except Exception:
    print(0, 0, 0); sys.exit()
def err(r):
    text = " ".join(r.get("bad") or [])
    return any(t.get("kind") == "error" for t in r.get("turns", [])) or "truth error" in text \
        or "ended in error" in text or "semaphore" in text or "connection was closed" in text
drop = {k for k, r in d.items() if err(r) or (mode == "all" and not r["ok"])}
d = {k: r for k, r in d.items() if k not in drop}
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, default=str)
print(len(drop), len(d), sum(1 for r in d.values() if r["ok"]))
EOF
}
mode=all
for round in $(seq 1 30); do
  vpn
  echo "$(date +%H:%M) round $round (prune $mode)"
  set -- $(prune $mode); echo "$(date +%H:%M) dropped/kept/ok = $1 $2 $3"
  mode=errors
  $PY tests/sheet_runs/cross/cross_run.py $FAMS >> "$OUT/cross_drive.log" 2>&1
  rc=$?
  set -- $(prune errors); echo "$(date +%H:%M) after run rc=$rc: errors dropped/kept/ok = $1 $2 $3"
  if [ $rc = 0 ] && [ "$1" = "0" ]; then echo "$(date +%H:%M) LIVE RUNS DONE: $3 / $2"; break; fi
done
$PY tests/sheet_runs/cross/failed.py "$RES" "$OUT/cross_failed.txt"
$PY tests/sheet_runs/cross/write_report.py
echo "$(date +%H:%M) ALL DONE"

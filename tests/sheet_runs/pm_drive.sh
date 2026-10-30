#!/bin/bash
# PMAY-G re-test 2026-10-30, VPN-proof: wait for a steady VPN, run the whole sheet (pm_run.py,
# not resumable: re-run until it ends with no connection error) and every village (pm_all.py,
# resumable: prune connection-error records so they re-run), then pytest and the 14 script
# suites. Usage (repo root): bash tests/sheet_runs/pm_drive.sh <out dir>
OUT=${1:?out dir}
PY=.venv/Scripts/python.exe
cd "$(dirname "$0")/../.." || exit 1
export PYTHONIOENCODING=utf-8 DB_POOL_MIN_SIZE=2 DB_POOL_MAX_SIZE=6 MG_CONC=5 SHEET_SCHEME=PMAY-G
up() { timeout 5 bash -c "</dev/tcp/10.48.242.4/5432" 2>/dev/null && timeout 5 bash -c "</dev/tcp/10.48.242.4/443" 2>/dev/null; }
vpn() { local ok=0; while [ $ok -lt 6 ]; do if up; then ok=$((ok+1)); else ok=0; fi; sleep 10; done; echo "$(date +%H:%M) VPN steady"; }
# prune <json> <min cases>: drop connection-error records; prints "<pruned> <kept> <ok>"
prune() { $PY - "$1" <<'EOF'
import json, sys
p = sys.argv[1]
try:
    d = json.load(open(p, encoding="utf-8"))
except Exception:
    print(-1, 0, 0); sys.exit()
err = lambda c: any(t.get("kind") == "error" for t in c.get("turns", [])) or "ended in error" in (c.get("note") or "")
n = sum(1 for v in d.values() for c in v if err(c))
d = {k: [c for c in v if not err(c)] for k, v in d.items()}
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, default=str)
print(n, sum(len(v) for v in d.values()), sum(1 for v in d.values() for c in v if c["ok"]))
EOF
}
for round in $(seq 1 20); do
  vpn
  echo "$(date +%H:%M) round $round"
  need_sheet=1; [ -f "$OUT/pm_fix.json" ] && set -- $(prune "$OUT/pm_fix.json") && [ "$1" = "0" ] && need_sheet=0
  if [ $need_sheet = 1 ]; then
    PM_OUT="$OUT/pm_fix.json" $PY tests/sheet_runs/pm_run.py > "$OUT/pm_fix.round$round.log" 2>&1 &
  fi
  PM_ALL_OUT="$OUT/pm_all_fix.json" $PY tests/sheet_runs/pm_all.py >> "$OUT/pm_all_fix.log" 2>&1
  wait
  set -- $(prune "$OUT/pm_all_fix.json"); echo "$(date +%H:%M) villages pruned/kept/ok = $1 $2 $3"; vill_done=0
  [ "$1" = "0" ] && [ "$2" -ge 5121 ] && vill_done=1
  set -- $(prune "$OUT/pm_fix.json"); echo "$(date +%H:%M) sheet pruned/kept/ok = $1 $2 $3"
  if [ "$1" = "0" ] && [ $vill_done = 1 ]; then echo "$(date +%H:%M) LIVE RUNS DONE"; break; fi
done
echo "$(date +%H:%M) pytest"
$PY -m pytest -q -p no:cacheprovider $(grep -lE "^\s*(async )?def test_" tests/test_*.py) > "$OUT/pytest_full.log" 2>&1
tail -3 "$OUT/pytest_full.log"
echo "$(date +%H:%M) scripts"
for f in tests/test_ac_full_results.py tests/test_admin_level_collision.py tests/test_block_backstop.py \
         tests/test_block_parent_district.py tests/test_context_manager.py tests/test_cross_scheme_collision.py \
         tests/test_cross_scheme_money.py tests/test_edge_conversational.py tests/test_focusplus_block_columns.py \
         tests/test_history_charts.py tests/test_mgnrega_split_facts.py tests/test_no_data_answer.py \
         tests/test_security.py tests/test_verifier_missing_geo.py; do
  if $PY "$f" > "$OUT/script_$(basename $f .py).log" 2>&1; then echo "PASS $f"; else echo "FAIL $f"; fi
done
echo "$(date +%H:%M) ALL DONE"

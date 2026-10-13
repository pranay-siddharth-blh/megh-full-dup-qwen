#!/bin/bash
# Final round 2026-10-13: every sheet's test cases on the final code, two runs at a time.
G=C:/Users/Admin/AppData/Local/Temp/claude/c--Users-Admin-OneDrive-Desktop-MCP-meghoneai/0505c350-01ce-41d1-bd2c-630d77ef03ea/scratchpad/gentest
PY=C:/Users/Admin/.mvenv/Scripts/python.exe
cd C:/Users/Admin/OneDrive/Desktop/MCP/meghoneai/meghalaya || exit 1
export PYTHONIOENCODING=utf-8 DB_POOL_MIN_SIZE=2 DB_POOL_MAX_SIZE=5 MG_CONC=4
vpn() {  # wait for 6 consecutive good probes (about a minute) of the DB and the model gateway
  local ok=0
  while [ $ok -lt 6 ]; do
    if powershell.exe -NoProfile -Command "if ((Test-NetConnection 10.48.242.4 -Port 5432 -WarningAction SilentlyContinue).TcpTestSucceeded -and (Test-NetConnection 10.48.242.4 -Port 443 -WarningAction SilentlyContinue).TcpTestSucceeded) { exit 0 } else { exit 1 }" >/dev/null 2>&1; then ok=$((ok+1)); else ok=0; fi
    sleep 5
  done
  echo "$(date +%H:%M) VPN steady"
}
run() { echo "$(date +%H:%M) start $1"; env "$2=final_$3.json" $PY $G/$1.py > $G/final_$3.log 2>&1; echo "$(date +%H:%M) done $1 (exit $?)"; }
vpn; run run_general GEN_OUT general & SHEET_SCHEME=MGNREGA run mg_run MG_OUT mgnrega & wait
vpn; run pm_run PM_OUT pmay & run ce_run CE_OUT cme & wait
vpn; run fp_run FP_OUT focusplus & run fl_run FL_OUT focuslegacy & wait
vpn; run cl_run CL_OUT cmelegacy & wait
echo "$(date +%H:%M) ALL DONE"

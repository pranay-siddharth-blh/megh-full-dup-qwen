#!/usr/bin/env bash
# MGNREGA UAT round (2026-10-30) driver — run from the repo root with the VPN up.
#   bash tests/sheet_runs/mg_uat_drive.sh <out-dir> first    # first pass (resumable: re-run until "written")
#   bash tests/sheet_runs/mg_uat_drive.sh <out-dir> after    # after-fix pass: every failed / errored case again
#   bash tests/sheet_runs/mg_uat_drive.sh <out-dir> score    # per-case scores of both result files
#   bash tests/sheet_runs/mg_uat_drive.sh <out-dir> sheet    # write columns U..X of the MGNREGA sheet (back it up first)
# Both live runs keep their pools small (the gateway and megh_db are shared with other sessions) and resume from
# their own result file, so a VPN drop costs only the cases that were in flight.
set -u
OUT="${1:?out dir}"; MODE="${2:-first}"
PY=.venv/Scripts/python.exe
export DB_POOL_MAX_SIZE=5 READONLY_DB_POOL_MAX_SIZE=3 PIPELINE_GRAPH_PG_POOL_MAX=1
mkdir -p "$OUT"
case "$MODE" in
  first|after)
    [ "$MODE" = after ] && export MGU_RERUN_FAILED=1
    until ping -n 1 -w 3000 10.48.242.4 | grep -q "Received = 1"; do echo "waiting for the VPN"; sleep 30; done
    MG_CONC=3 $PY -X utf8 tests/sheet_runs/mg_uat.py "$OUT/r_main.json" district block ac state cross village dups rank \
        > "$OUT/r_main.$MODE.log" 2>&1 &
    sleep 60
    MG_CONC=3 $PY -X utf8 tests/sheet_runs/mg_uat_villages.py "$OUT/r_vill.json" > "$OUT/r_vill.$MODE.log" 2>&1
    wait
    grep -c "^DATA" "$OUT/r_main.$MODE.log" "$OUT/r_vill.$MODE.log";;
  score)
    $PY -X utf8 tests/sheet_runs/mg_uat_score.py "$OUT/r_main.json" --fails=40
    $PY -X utf8 tests/sheet_runs/mg_uat_score.py "$OUT/r_vill.json" --fails=40;;
  sheet)
    # before = the pre-fix snapshots (+ the rankings smoke run that found KI-635/636); after = the final files
    $PY -X utf8 tests/sheet_runs/write_mg_uat.py "$OUT/r_rank.json" "$OUT/r_main_before.json" "$OUT/r_vill_before.json" -- \
        "$OUT/r_main.json" "$OUT/r_vill.json";;
  *) echo "mode: first | after | score | sheet"; exit 2;;
esac

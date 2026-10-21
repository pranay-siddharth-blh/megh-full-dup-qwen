@echo off
cd /d C:\Users\Admin\OneDrive\Desktop\MCP\meghoneai\meghalaya
set MX_CONC=2
set DB_POOL_MIN_SIZE=1
set DB_POOL_MAX_SIZE=2
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe tests\sheet_runs\matrix\matrix_run.py village > tests\sheet_runs\matrix\village_run.out 2>&1

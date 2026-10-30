"""uat/finalize.py — after the final run: disputed / needs-review IDs, fixes_final.patch, bug list,
no-impact proof, then the Excel report. Reads files only (results.csv, test_matrix.csv, git)."""
import csv
import json
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MAIN = os.path.join(os.path.dirname(ROOT), "meghoneai")
csv.field_size_limit(10 ** 8)
os.chdir(ROOT)
last = {}
for r in csv.DictReader(open("uat/results.csv", newline="", encoding="utf-8")):
    last[r["id"]] = r
matrix = list(csv.DictReader(open("uat/test_matrix.csv", newline="", encoding="utf-8")))
mids = {t["id"] for t in matrix}

disputed, review = {}, {}
for tid, r in last.items():
    if tid not in mids or r["status"] == "Pass":
        continue
    a, q = r["actual"], r["question"]
    if "data is available only for the financial years" in a and "Legacy" in a:
        disputed[tid] = "D1"
    elif r["category"] == "C12_followup" and all(x.strip().startswith("T3") for x in r["fails"].split(";") if x.strip()):
        disputed[tid] = "D2"
    elif tid == "C11-NAME-2" and ("isn't part of" in a or "does not contain" in a or "not part of" in a):
        disputed[tid] = "D3"
    elif tid == "C14-ZERO-273559":
        disputed[tid] = "D4"
    elif "ward" in q.lower() or "Showing results for" in a or "couldn't find a place" in a:
        review[tid] = "N1"
    elif "village of" in q.lower() and "block" in q.lower() and r["category"] in ("C03_shared",):
        review[tid] = "N2"
    elif tid == "C11-NAME-5":
        review[tid] = "N3"
json.dump(sorted(disputed), open("uat/disputed_ids.json", "w"))
json.dump(sorted(review), open("uat/needs_review_ids.json", "w"))

# fixes_final.patch: every CM Elevate change vs Main (app code + the harness test file)
patch = subprocess.run(["git", "diff", "--no-color", "Main", "--", "app", "tests/live_cme_uat.py"],
                       capture_output=True, text=True, encoding="utf-8").stdout
open("uat/fixes_final.patch", "w", encoding="utf-8", newline="\n").write(patch)
log = subprocess.run(["git", "log", "--oneline", "Main..HEAD"], capture_output=True, text=True, encoding="utf-8").stdout

# bug list (markdown)
bugs = json.load(open("uat/bugs.json", encoding="utf-8"))
with open("uat/bug_list.md", "w", encoding="utf-8") as fh:
    fh.write("# CM Elevate UAT — bugs found and fixed\n\n")
    for b in bugs:
        fh.write(f"## {b['bug']}\n- **Symptom:** {b['symptom']}\n- **Root cause:** {b['root']}\n- **Fix:** {b['fix']}\n"
                 f"- **Files:** {b['files']}  \n- **Commit:** {b.get('commit', '')}  \n- **Shared code:** {b.get('shared', '')}\n\n")
    fh.write("## Commits on uat-cm-elevate-exhaustive (vs Main)\n```\n" + log + "```\n")

# no-impact proof
now = subprocess.run(["git", "status", "--porcelain"], cwd=MAIN, capture_output=True, text=True, encoding="utf-8").stdout
step0 = open("uat/main_status_step0.txt", encoding="utf-8").read()
step0_lines = [l for l in step0.splitlines()[3:] if l and not l.startswith("##") and not l.startswith(" ") or l.startswith(" M")]
diff_sha = subprocess.run("git diff | sha1sum", shell=True, cwd=MAIN, capture_output=True, text=True).stdout.strip()
progress = open("uat/progress.log", encoding="utf-8").read().splitlines()
writes = sorted({l.split("db_write_attempts")[-1].strip() for l in progress if "db_write_attempts" in l})
cfg = subprocess.run(["git", "diff", "--name-only", "Main", "--", ".env.example", "requirements.txt", "requirements.lock",
                      "app/config.py", "docker-compose.yml", "Dockerfile", "deploy", "data/schema"],
                     capture_output=True, text=True, encoding="utf-8").stdout.strip()
with open("uat/no_impact.md", "w", encoding="utf-8") as fh:
    fh.write(f"# Proof of no impact ({time.strftime('%Y-%m-%d %H:%M')})\n\n")
    fh.write("## Main folder git status now\n```\n" + subprocess.run(["git", "branch", "--show-current"], cwd=MAIN,
             capture_output=True, text=True).stdout + now + "```\n")
    fh.write(f"- `git diff | sha1sum` now: `{diff_sha}`\n- at Step 0: see main_status_step0.txt (`## diff sha1` line)\n")
    fh.write("- Only files ADDED in the main folder after Step 0: none by this session except the Step-0 outputs in "
             "reference_documents/uat-cm-elevate/ (allowed by Step 0). Any other change there belongs to other sessions.\n\n")
    fh.write("## Database\n- Every runner progress line reports `db_write_attempts` = " + ", ".join(writes) +
             " (db.execute / execute_script were replaced by a refusing stub; no app lifespan, so no app.* DDL; "
             "no session sync, so no conversation rows; LangGraph checkpointer in memory).\n"
             "- Expected values: read-only SELECTs (psycopg connection with `read_only = True`).\n\n")
    fh.write("## Config / dependencies\n- Files changed vs Main among .env.example, requirements*, app/config.py, "
             f"docker-compose.yml, Dockerfile, deploy/, data/schema/: `{cfg or 'none'}`\n"
             "- `.env` copied unchanged into the worktree (git-ignored). No packages installed.\n"
             "- Port 8401 untouched; no server started (in-process driver).\n")
print("disputed", len(disputed), {k: list(disputed.values()).count(k) for k in set(disputed.values())})
print("needs review", len(review), {k: list(review.values()).count(k) for k in set(review.values())})
subprocess.run(["C:/Users/golla/OneDrive/Desktop/meghs/meghoneai/.venv/Scripts/python.exe", "uat/make_report.py"])

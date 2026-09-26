"""
Turn a day's production failures into eval cases — the continuous-improvement
loop: every phrasing that failed becomes a test the next change must pass.

    python tests/eval/export_failures.py                   # today, from logs/query_audit.jsonl
    python tests/eval/export_failures.py --day 2026-09-25
    python tests/eval/export_failures.py --from-db         # app.query_audit (needs DATABASE_URL)
    python tests/eval/export_failures.py --dry-run         # show, don't write

"Failure" = the rules in app/conversation/failures.py (zero rows, repair used,
fallback reply, clarification asked more than twice in one conversation) —
the same rules the admin "Today's failures" tab uses.

Each failed turn becomes one case; a clarification-loop conversation becomes
ONE multi-turn case carrying that session's messages in order. Cases are
appended to tests/eval/cases.yaml with source `audit_log` and
`needs_expected_answer: true` (fill in expect, then flip the flag) — the
source build_cases.py treats as human-owned and carries over untouched.
Re-running is safe: a case whose turns are already present is skipped.
Harness / scripted traffic (testclient, *tester*, eval-harness) is excluded.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import yaml  # noqa: E402

from app.conversation import failures  # noqa: E402

_SYNTHETIC_USER = re.compile(r"(tester|^rc-officer-|^qa-|^eval-harness$)", re.IGNORECASE)


def _args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--day", default=dt.date.today().isoformat(), help="YYYY-MM-DD (default today)")
    ap.add_argument("--audit-file", default=str(ROOT / "logs" / "query_audit.jsonl"))
    ap.add_argument("--cases", default=str(EVAL / "cases.yaml"))
    ap.add_argument("--from-db", action="store_true", help="read app.query_audit instead of the JSONL mirror")
    ap.add_argument("--tenant", type=int)
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def _real(rec: dict) -> bool:
    return rec.get("ip") != "testclient" and not _SYNTHETIC_USER.search(str(rec.get("username") or ""))


def from_jsonl(path: str, day: str) -> list[dict]:
    """That day's real records, with failure reasons, from the JSONL mirror."""
    recs = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if str(r.get("ts", "")).startswith(day) and _real(r):
            recs.append(r)
    return failures.classify(recs), recs


async def _from_db(day: str, tenant: "int | None") -> list[dict]:
    from app.conversation import conversation_store
    from app.database import db
    await db.init_pool()
    try:
        return [dict(r) for r in await conversation_store.admin_failures(tenant_id=tenant, day=day)
                if _real(dict(r))]
    finally:
        await db.close_pool()


def to_cases(failed: list[dict], all_recs: list[dict], day: str) -> list[dict]:
    """Failed records -> eval cases (clarification loops collapsed per session)."""
    by_session: dict = {}
    for r in sorted(all_recs, key=lambda r: str(r.get("ts") or r.get("created_at") or "")):
        by_session.setdefault(r.get("session_id"), []).append(r)
    cases, loops_done = [], set()
    for r in failed:
        reasons = list(r.get("reasons") or [])
        sid = r.get("session_id")
        if "clarify_loop" in reasons:
            if sid in loops_done:
                continue
            loops_done.add(sid)
            turns = [t.get("question") for t in by_session.get(sid, [r]) if t.get("question")]
        else:
            turns = [r.get("question")]
        turns = [str(t).strip() for t in turns if t and str(t).strip()]
        if not turns:
            continue
        cases.append({
            "source": "audit_log", "scheme": None, "turns": turns,
            "failure_reasons": reasons, "exported_from": f"failures {day}",
            "logged": [{"route": r.get("route"), "rows": r.get("row_count"),
                        "rule": r.get("deny_check") or r.get("denied_by")}],
            "needs_expected_answer": True,
            "expect": {"kind": "answer", "answer": None, "figures": []},
        })
    return cases


def append_cases(cases_path: str, new: list[dict], day: str, dry_run: bool) -> list[dict]:
    raw = Path(cases_path).read_text(encoding="utf-8")
    header = "".join(ln + "\n" for ln in raw.splitlines() if ln.startswith("#"))
    doc = yaml.safe_load(raw) or {"version": 1, "cases": []}
    existing = doc.setdefault("cases", [])
    seen = {tuple(str(t) for t in c.get("turns") or []) for c in existing}
    stamp = day.replace("-", "")
    n = sum(1 for c in existing if str(c.get("id", "")).startswith(f"fail-{stamp}-"))
    added = []
    for c in new:
        key = tuple(c["turns"])
        if key in seen:
            continue
        seen.add(key)
        n += 1
        added.append({"id": f"fail-{stamp}-{n:03d}", **c})
    if added and not dry_run:
        existing.extend(added)
        Path(cases_path).write_text(
            header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")
    return added


def main():
    a = _args()
    if a.from_db:
        failed = asyncio.run(_from_db(a.day, a.tenant))
        all_recs = failed          # the DB query already returns whole clarification-loop sessions
    else:
        failed, all_recs = from_jsonl(a.audit_file, a.day)
    cases = to_cases(failed, all_recs, a.day)
    added = append_cases(a.cases, cases, a.day, a.dry_run)
    by_reason = {k: sum(1 for c in cases if k in c["failure_reasons"]) for k in failures.REASONS}
    print(f"{a.day}: {len(failed)} failed turns -> {len(cases)} cases {by_reason}; "
          f"{len(added)} new{' (dry run, nothing written)' if a.dry_run else ''}")
    for c in added:
        print(f"  {c['id']}  [{', '.join(c['failure_reasons'])}]  {' || '.join(c['turns'])[:110]}")


if __name__ == "__main__":
    main()

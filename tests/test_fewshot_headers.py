"""A few-shot file may call its examples validated / verified in its header only
while every example in it runs read-only (tests/fewshot_exec/check_fewshots.py,
whose last run is tests/fewshot_exec/results/latest.json). The SQL prompt copies
these patterns, so an unearned "validated" hides broken ones (2026-10-16).

Offline: reads the saved results, never the database. Re-run the checker after
editing a few-shot file."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "tests" / "fewshot_exec" / "results" / "latest.json"
_CLAIMS = ("validated question-to-sql", "append verified")


def _header(path: Path, lines: int = 15) -> str:
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[:lines]).lower()


def _results() -> dict:
    if not LATEST.exists():
        pytest.skip("no few-shot run yet — python tests/fewshot_exec/check_fewshots.py")
    return json.loads(LATEST.read_text(encoding="utf-8"))["files"]


def test_no_header_claims_validated_while_an_example_fails():
    wrong = []
    for rel, res in _results().items():
        header = _header(ROOT / rel)
        if not res["all_pass"] and any(c in header for c in _CLAIMS):
            wrong.append(f"{rel}: {len(res['failing'])} example(s) do not run, but the header says validated")
    assert not wrong, "; ".join(wrong)


def test_every_example_in_the_prompt_pool_runs():
    # The loader may keep a non-running example out of the prompt; one that
    # reaches the prompt must run.
    bad = [f"{rel} [{f['index']}] {f['question']!r}: {f['outcome']}"
           for rel, res in _results().items() for f in res["failing"] if f.get("in_prompt")]
    assert not bad, "; ".join(bad)


def test_the_run_covers_every_scheme_file():
    from app import annotations
    files = {str((annotations._SCHEME_DIRS[s] / annotations._FEW_SHOT_FILE[s]).relative_to(ROOT)).replace("\\", "/")
             for s in annotations._FEW_SHOT_FILE}
    assert files <= set(_results())

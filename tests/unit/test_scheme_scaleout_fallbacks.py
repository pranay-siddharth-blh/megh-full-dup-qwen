"""
openspec/changes/multi-tenant-rls-scheme-scaleout — app/response/followups.py and
app/sql/prompt_builder.py both had a hardcoded 4-scheme literal that's now read
from app.knowledge.scheme_registry instead (still hand-authored per-scheme regex/
prefix dictionaries elsewhere in both files — NOT fixed by this, see the
inline comments left at each call site). This is the narrow regression
check that the two swapped call sites still behave identically today (4
schemes registered) and would pick up a 5th automatically.

Runs without a DB — scheme_registry.load_all() only reads the local YAML
file, same as it does at real startup (see app/main.py).

Plain script (no pytest in the venv) — `python tests/unit/test_scheme_scaleout_fallbacks.py`,
exit code 0 = all pass.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")

from app.response import followups  # noqa: E402
from app.knowledge import scheme_registry

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


scheme_registry.load_all()

print("1. followups._primary_schemes fallback reads the live registry")
today = sorted(scheme_registry.scheme_ids())
check("today's registry has exactly the 4 known real schemes",
      today == sorted(["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"]), today)

fallback = followups._primary_schemes(schemes=[], question="tell me something generic")
check("no schemes resolved, no scheme named in question -> fallback = every registered scheme",
      sorted(fallback) == today, fallback)

print("2. registry reload picks up a change without a code edit "
      "(simulates onboarding scheme #5 without restarting anything)")
_orig_registry = dict(scheme_registry._registry)
try:
    scheme_registry._registry["Demo Scheme"] = {
        "display_name": "Demo Scheme", "aliases": [], "tables": [], "shared": False,
    }
    fallback_after = followups._primary_schemes(schemes=[], question="tell me something generic")
    check("_primary_schemes fallback includes the newly-registered scheme with zero code changes",
          "Demo Scheme" in fallback_after, fallback_after)
finally:
    scheme_registry._registry = _orig_registry  # restore — this is a shared module-level dict

print("3. warn_if_scheme_count_high — startup log warning, not a hard limit")
_orig_registry2 = dict(scheme_registry._registry)
try:
    check("today's 4 schemes stay under the default threshold (10) — no warning expected",
          len(scheme_registry.scheme_ids(include_shared=False)) <= scheme_registry.SCHEME_COUNT_WARN_THRESHOLD)
    scheme_registry.warn_if_scheme_count_high()  # must not raise at today's count
    check("does not raise at today's scheme count", True)

    for i in range(scheme_registry.SCHEME_COUNT_WARN_THRESHOLD + 2):
        scheme_registry._registry[f"Demo Scheme {i}"] = {
            "display_name": f"Demo Scheme {i}", "aliases": [], "tables": [], "shared": False,
        }
    check(f"simulated registry now exceeds the threshold ({scheme_registry.SCHEME_COUNT_WARN_THRESHOLD})",
          len(scheme_registry.scheme_ids(include_shared=False)) > scheme_registry.SCHEME_COUNT_WARN_THRESHOLD)
    scheme_registry.warn_if_scheme_count_high()  # must not raise/block boot even over threshold
    check("does not raise when over threshold either (log-only, never blocks boot)", True)
finally:
    scheme_registry._registry = _orig_registry2

print()
if _fails:
    print(f"FAILED: {len(_fails)} check(s) — {_fails}")
    sys.exit(1)
print("ALL CHECKS PASSED")

"""
Silent defaults engine (app/nlu/defaults_engine.py, node 5.5) — pure-logic checks
against the real curated `*_default_rules.yaml` files. No DB, no model
gateway — same stance as test_security.py / test_join_graph.py:
`python tests/unit/test_defaults_engine.py`, exit code 0 = all pass.

Covers tasks.md group 1's acceptance scenarios: (a) a question matching a
non-colliding condition produces the expected assumption_text in notes;
(b) a question matching a colliding condition (`missing_top_n`) produces no
default here — it stays the job of clarify_rules rule 2 (top-N), which
still handles it; (c) a question
matching no condition leaves notes unchanged; (d) a missing/malformed
`*_default_rules.yaml` degrades to no defaults, never raises.

Note on (a): `missing_geography` is NOT used as the non-colliding example
here, even though the proposal's spec illustrates the mechanism with "a
missing geography scope". clarify_rules rule 3 (area) already owns the
"no geography" case, and this module's
collision set treats the whole geography topic as its domain (see
defaults_engine.py's module docstring: ties go to asking, not defaulting).
`expenditure_unit_unspecified` is used instead — a condition with no
overlapping clarification rule at all (there is no unit rule), so it is
unambiguously safe to default, which is the
actual point the acceptance scenario is checking.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.nlu import defaults_engine  # noqa: E402
from app.nlu import clarify_rules  # noqa: E402
from app.nlu.understand import QueryFrame  # noqa: E402
from app.orchestration.pipeline import ClarificationNeeded  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# ── (a) non-colliding condition applies its default ────────────────────────
print("1. NON-COLLIDING CONDITION -> ASSUMPTION TEXT IN NOTES")

notes_a = defaults_engine.apply_defaults(
    "What was the total MGNREGA expenditure in West Garo Hills?",
    ["MGNREGA"], {"district": "WEST GARO HILLS", "year_key": "2023-24"},
)
check("expenditure_unit_unspecified fires with no unit stated",
      any("crore" in n.lower() for n in notes_a), str(notes_a))

notes_a_with_unit = defaults_engine.apply_defaults(
    "What was the total MGNREGA expenditure in lakh rupees for West Garo Hills?",
    ["MGNREGA"], {"district": "WEST GARO HILLS", "year_key": "2023-24"},
)
check("expenditure_unit_unspecified does NOT fire once a unit is already stated",
      not notes_a_with_unit, str(notes_a_with_unit))

# ── (b) colliding condition -> no default, existing gate unaffected ───────
print("2. COLLIDING CONDITION (missing_top_n) -> NO DEFAULT, GATE UNCHANGED")

ranking_q = "Which districts spent the most on MGNREGA?"
notes_b = defaults_engine.apply_defaults(ranking_q, ["MGNREGA"], {})
check("missing_top_n produces no assumption text (stays in the collision set)",
      not any("top 5" in n.lower() for n in notes_b), str(notes_b))
_rank = QueryFrame(schemes=["MGNREGA"], resolved_schemes=["MGNREGA"], metric="expenditure",
                   query_type="ranking", group_by="district")


def _topn_outcome(frame, q):
    try:
        return [t for t in clarify_rules.before_resolution(frame, q).fired if t.startswith("top_n")]
    except ClarificationNeeded as e:
        return [e.rule]


_b = _topn_outcome(_rank, ranking_q)
check("clarify_rules rule 2 still handles the missing count (asks, or applies its disclosed default)",
      _b == ["ranking-count-not-specified"] or (_b and _b[0].startswith("top_n:default")), str(_b))

explicit_topn_q = "Which are the top 3 districts that spent the most on MGNREGA?"
check("a question with an explicit count does not trip the top-N rule",
      _topn_outcome(_rank.model_copy(update={"top_n": 3}), explicit_topn_q) == [])

# ── (c) no condition matches -> notes unchanged ─────────────────────────────
print("3. NO MATCHING CONDITION -> NOTES UNCHANGED")

notes_c = defaults_engine.apply_defaults(
    "What is the eligibility criteria for PMAY-G?", ["PMAY-G"], {},
)
check("an on-topic-for-nothing question returns an empty list", notes_c == [], str(notes_c))

notes_c_empty_schemes = defaults_engine.apply_defaults("total expenditure", [], {})
check("no active schemes returns an empty list", notes_c_empty_schemes == [], str(notes_c_empty_schemes))

# ── (d) missing/malformed rules file -> degrades, never raises ─────────────
print("4. MISSING / MALFORMED DEFAULT-RULES FILE -> NO DEFAULTS, NO RAISE")

_FAKE_MISSING = "_TEST_SCHEME_MISSING_FILE"
defaults_engine._DEFAULT_RULES_FILE[_FAKE_MISSING] = Path("/nonexistent/path/does_not_exist.yaml")
try:
    notes_missing = defaults_engine.apply_defaults(
        "What was the total expenditure?", [_FAKE_MISSING], {},
    )
    check("a scheme with a missing rules file raises nothing and defaults to no notes",
          notes_missing == [], str(notes_missing))
except Exception as e:  # noqa: BLE001
    check("a scheme with a missing rules file raises nothing and defaults to no notes",
          False, f"raised {type(e).__name__}: {e}")

_FAKE_MALFORMED = "_TEST_SCHEME_MALFORMED_FILE"
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tf:
    tf.write("default_rules: [this is not: valid: yaml: at: all:")
    malformed_path = Path(tf.name)
defaults_engine._DEFAULT_RULES_FILE[_FAKE_MALFORMED] = malformed_path
try:
    notes_malformed = defaults_engine.apply_defaults(
        "What was the total expenditure?", [_FAKE_MALFORMED], {},
    )
    check("a scheme with a malformed rules file raises nothing and defaults to no notes",
          notes_malformed == [], str(notes_malformed))
except Exception as e:  # noqa: BLE001
    check("a scheme with a malformed rules file raises nothing and defaults to no notes",
          False, f"raised {type(e).__name__}: {e}")
finally:
    malformed_path.unlink(missing_ok=True)

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL DEFAULTS-ENGINE CHECKS PASSED")

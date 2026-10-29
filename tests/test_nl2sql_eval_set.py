"""The NL->SQL accuracy set (tests/nl2sql_eval/questions.yaml) stays valid:
held out from the fix loop, well-formed, and every gold query passes the
read-only guard. Runs offline; the live scoring is tests/nl2sql_eval/run_eval.py.

The hold-out test is the one that matters: it fails as soon as an eval
question (or a close paraphrase) is copied into a few-shot bank, rule file,
test, sheet or app string — the score would stop measuring accuracy."""
from collections import Counter

import pytest

from app.sql_guard import assert_readonly
from tests.nl2sql_eval import holdout

ITEMS = holdout.load_questions()
SCHEMES = {"MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate", "CM Elevate Legacy"}


def test_the_set_is_well_formed():
    assert len(ITEMS) >= 60
    ids = [i["id"] for i in ITEMS]
    assert len(ids) == len(set(ids))
    assert {i["scheme"] for i in ITEMS} == SCHEMES
    assert all(i["difficulty"] in ("easy", "medium", "hard") for i in ITEMS)
    assert all(isinstance(i["ordered"], bool) and i["question"].strip() for i in ITEMS)
    assert min(Counter(i["scheme"] for i in ITEMS).values()) >= 10


@pytest.mark.parametrize("item", ITEMS, ids=lambda i: i["id"])
def test_gold_sql_passes_the_read_only_guard(item):
    assert_readonly(item["gold_sql"])


def test_no_question_is_in_the_fix_loop():
    leaked = holdout.check(ITEMS)
    assert not leaked, "eval questions found in the fix loop — replace them: " + "; ".join(
        f"{x['id']} ~ {x['matches']!r} [{x['source']}]" for x in leaked)


def test_every_expected_pause_names_a_real_pause_rule():
    # CTX-09: the rule an item expects must be one the app can raise (the
    # router's own pause registries), so a typo can never pass as "expected".
    from app.routers.query import SCHEME_PAUSE_RULES, SCOPE_MERGE_RULES
    rules = set(SCOPE_MERGE_RULES) | set(SCHEME_PAUSE_RULES)
    flagged = [i for i in ITEMS if i.get("expect_pause")]
    assert flagged
    assert all(i["expect_pause"] in rules for i in flagged), \
        [(i["id"], i["expect_pause"]) for i in flagged if i["expect_pause"] not in rules]


def test_the_guard_catches_a_copied_question():
    # A few-shot question is, by definition, in the fix loop.
    assert holdout.leak("Which district received the highest total disbursement?")

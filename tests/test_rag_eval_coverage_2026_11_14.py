"""
Offline coverage guard for the RAG evaluation set (2026-11-14).

tests/rag_eval/testset.json is scored by run_eval.py, which needs the model
gateway. This file needs nothing but the repo: it checks that

1. every scheme in app.scheme_registry.DATASETS whose SME documents sit in
   data/incoming/<kb_folder>/ has questions in the set (at least 10 "doc"
   items and at least 1 "negative" item), so a newly onboarded scheme cannot
   ship with no evaluation questions (CMSS and Homestay had none until today);
2. the items written for CMSS and Homestay are grounded: the evidence quote is
   in the document gold_doc names (case-sensitive, whitespace-normalised, with
   markdown bold markers ignored) and would also count as a retrieval hit under
   run_eval's own text normalisation; gold_heading is in that document, above
   the evidence;
3. every item, old and new, has the schema run_eval / sme_review rely on, and
   no question appears twice.

The strict grounding check (2) is limited to the schemes added on 2026-11-14.
The 188 older items were written against the old collection: their gold_doc
says "reference/<file>" (data/reference/ was moved to data/incoming/<scheme>/
on 2026-10-14) and one file was renamed since (cmelevate_complete_reference.md
-> CM_Elevate_Complete_Reference.md, minus its section 15), so they are not
held to it here. run_eval scores a hit by evidence text alone, never by
gold_doc, so those labels do not affect the scores.

    pytest -q tests/test_rag_eval_coverage_2026_11_14.py
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from app.scheme_registry import BY_NAME, DATASETS, NAMES
from tests.rag_eval.build_testset import norm  # run_eval's own hit normalisation

ROOT = Path(__file__).resolve().parents[1]
TESTSET = ROOT / "tests" / "rag_eval" / "testset.json"
INCOMING = ROOT / "data" / "incoming"
READABLE = {".md", ".txt", ".docx", ".pdf", ".xlsx"}   # app/kb_ingest._READABLE

# Schemes whose items are held to the strict grounding check (added 2026-11-14).
STRICT_SCHEMES = {"CMSS", "Homestay"}

MIN_DOC_ITEMS = 10
MIN_NEGATIVE_ITEMS = 1

REQUIRED_KEYS = {"id", "kind", "scheme", "question", "expected_answer", "evidence",
                 "gold_doc", "gold_heading", "style"}
KINDS = {"doc", "real", "negative"}                     # run_eval --kind choices
NEGATIVE_ANSWER = "Not covered by the scheme documents (should say so, not guess)."


def _items() -> list[dict]:
    return json.loads(TESTSET.read_text(encoding="utf-8"))


ITEMS = _items()


def _ws(s: str) -> str:
    return " ".join((s or "").split())


def _plain(s: str) -> str:
    """Whitespace-normalised, case kept, markdown bold markers dropped (the
    scheme documents bold key figures; an evidence quote may leave the ** out)."""
    return _ws((s or "").replace("**", ""))


def _source_docs(folder: str) -> list[Path]:
    d = INCOMING / folder
    if not d.is_dir():
        return []
    return [p for p in sorted(d.iterdir())
            if p.is_file() and p.suffix.lower() in READABLE and p.name.lower() != "readme.md"]


def _resolve(gold_doc: str) -> Path | None:
    """The file a gold_doc label names, or None.

    New items use the knowledge base's own doc form "<incoming folder>/<file>"
    (data/incoming/<gold_doc>). Old items say "reference/<file>": found by file
    name under data/incoming/*/ when it still exists there."""
    if not gold_doc:
        return None
    for cand in (INCOMING / gold_doc, ROOT / "data" / gold_doc):
        if cand.is_file():
            return cand
    if gold_doc.startswith("reference/"):
        name = gold_doc.split("/", 1)[1]
        hits = sorted(p for p in INCOMING.glob(f"*/{name}") if p.is_file() and p.name == name)
        if hits:
            return hits[0]
    return None


def _eval_scheme(name: str) -> str:
    """The scheme name the test set files a registry scheme's questions under.

    CM Elevate Legacy has no questions of its own on purpose: its knowledge-base
    tag is "CM Elevate" (rag.kb_scheme, kb_ingest._INCOMING_SCHEMES) and its
    folder holds byte-identical copies of CM Elevate's documents (checked in
    test_shared_knowledge_base_is_really_shared), so CM Elevate's questions
    cover it. Homestay's tag "Home Stay" names no registry scheme, so Homestay
    keeps its own name, which is what run_eval passes to rag.retrieve."""
    tag = BY_NAME[name].kb_tag
    return tag if tag != name and tag in NAMES else name


SCHEMES_WITH_DOCS = [s for s in DATASETS if _source_docs(BY_NAME[s].kb_folder)]


# ── 1. coverage ──────────────────────────────────────────────────────────────

def test_every_scheme_with_documents_is_found():
    # The guard below is only as good as this list: every registry scheme with a
    # data/incoming folder must be in it (8 schemes on 2026-11-14).
    assert set(SCHEMES_WITH_DOCS) >= {"MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate",
                                      "CM Elevate Legacy", "CMSS", "Homestay"}


@pytest.mark.parametrize("scheme", SCHEMES_WITH_DOCS)
def test_scheme_has_doc_and_negative_items(scheme):
    target = _eval_scheme(scheme)
    kinds = Counter(i["kind"] for i in ITEMS if i["scheme"] == target)
    assert kinds["doc"] >= MIN_DOC_ITEMS, (
        f"{scheme} (filed as {target!r}) has {kinds['doc']} doc items in testset.json; "
        f"add at least {MIN_DOC_ITEMS} grounded in data/incoming/{BY_NAME[scheme].kb_folder}/")
    assert kinds["negative"] >= MIN_NEGATIVE_ITEMS, f"{scheme} has no 'not covered' (negative) item"


def test_shared_knowledge_base_is_really_shared():
    for name in SCHEMES_WITH_DOCS:
        target = _eval_scheme(name)
        if target == name:
            continue
        mine = {p.read_bytes() for p in _source_docs(BY_NAME[name].kb_folder)}
        theirs = {p.read_bytes() for p in _source_docs(BY_NAME[target].kb_folder)}
        assert mine <= theirs, (f"{name} borrows {target}'s questions but its documents differ: "
                                f"give it its own questions")


# ── 2. grounding of the items added 2026-11-14 ───────────────────────────────

STRICT = [i for i in ITEMS if i["scheme"] in STRICT_SCHEMES and i["kind"] != "negative"]


def test_strict_items_exist():
    assert len(STRICT) >= 2 * MIN_DOC_ITEMS


@pytest.mark.parametrize("item", STRICT, ids=[i["id"] for i in STRICT])
def test_new_item_is_grounded(item):
    path = _resolve(item["gold_doc"])
    assert path is not None, f"gold_doc {item['gold_doc']!r} names no file in the repo"
    assert path.parent.name == BY_NAME[item["scheme"]].kb_folder, "gold_doc is another scheme's document"
    text = path.read_text(encoding="utf-8")
    ev, head = item["evidence"], item["gold_heading"]
    assert len(ev.split()) >= 6, "evidence quote too short to be specific"
    assert _plain(ev) in _plain(text), "evidence is not a verbatim passage of gold_doc"
    assert norm(ev) in norm(text), "evidence would never count as a retrieval hit under run_eval's norm()"
    assert head and _plain(head) in _plain(text), "gold_heading is not in gold_doc"
    assert _plain(text).find(_plain(head)) <= _plain(text).find(_plain(ev)), "gold_heading is below the evidence"


# ── 3. schema sanity, every item ─────────────────────────────────────────────

def test_testset_is_a_list_of_items():
    assert isinstance(ITEMS, list) and len(ITEMS) >= 188 + 2 * (MIN_DOC_ITEMS + MIN_NEGATIVE_ITEMS)


@pytest.mark.parametrize("item", ITEMS, ids=[str(i.get("id")) for i in ITEMS])
def test_item_schema(item):
    missing = REQUIRED_KEYS - set(item)
    assert not missing, f"missing keys {sorted(missing)}"
    assert item["kind"] in KINDS
    assert item["scheme"] in NAMES, f"scheme {item['scheme']!r} is not a registry name"
    assert _ws(item["question"]), "empty question"
    assert _ws(item["expected_answer"]), "empty expected answer"
    if item["kind"] == "negative":
        assert item["expected_answer"] == NEGATIVE_ANSWER
        assert item["style"] == "not covered"
        assert not (item["evidence"] or item["gold_doc"] or item["gold_heading"])
    else:
        assert _ws(item["evidence"]) and item["gold_doc"] and item["gold_heading"]


def test_ids_and_questions_are_unique():
    ids = Counter(i.get("id") for i in ITEMS)
    assert [k for k, v in ids.items() if v > 1] == []
    qs = Counter(_ws(i["question"]).lower() for i in ITEMS)
    assert [k for k, v in qs.items() if v > 1] == []

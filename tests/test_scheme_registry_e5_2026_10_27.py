"""E5 (RAG plan; D-079) — one scheme registry (app/scheme_registry.py) and a drift guard.

Scheme names were hand-kept in ~124 places across 31 files (mapped 2026-10-27). The
pure name lists now read the registry; every other registry keeps its shape and must
AGREE with it — this file fails on any drift, so adding or renaming a scheme in one
place but not another is caught at test time instead of in a live answer.

Known, pinned difference (KI-445): c13 _CROSS_AC_RECORDED leaves out CM Elevate while
c08 _AC_CAPABLE_SCHEMES includes it — and since 2026-10 every view carries ac_name.
Resolving KI-445 means editing that one test on purpose.

OFFLINE, no DB.
    .venv/Scripts/python.exe -m pytest tests/test_scheme_registry_e5_2026_10_27.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import (auth, cross_scheme, edge, guardrails, kb_ingest, metric_catalog, prompt_builder,  # noqa: E402
                 query_plan, rag, schema_context, schema_introspect, scheme_registry as R)
from app import pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NAMES = set(R.NAMES)


def test_the_registry_itself():
    assert R.NAMES == ("MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy", "CM Elevate Legacy", "CMSS")
    assert len(R.BY_NAME) == 7 and len(R.SUBJECT_TO_SCHEME) == 7


def test_pure_name_lists_read_the_registry():
    assert p._ALL_SCHEMES == frozenset(R.NAMES)
    assert query_plan.SCHEMES is R.NAMES
    assert metric_catalog.SUBJECT_TO_SCHEME is R.SUBJECT_TO_SCHEME
    for role in ("super_admin", "tenant_admin", "admin", "state_officer", "district_officer", "block_officer"):
        assert auth.ROLE_PERMISSIONS[role]["schemes"] == list(R.NAMES), role


def test_every_role_names_only_real_schemes():
    for role, perms in auth.ROLE_PERMISSIONS.items():
        assert set(perms.get("schemes") or []) <= NAMES, role


def test_knowledge_base_folders_and_tags():
    assert kb_ingest._INCOMING_SCHEMES == {s.kb_folder: s.kb_tag for s in R.SCHEMES}
    for s in R.SCHEMES:
        assert (ROOT / "data" / "incoming" / s.kb_folder).is_dir(), s.kb_folder
    assert {k: v[0] for k, v in rag._SCHEME_DOC_NAMES.items()} == {s.name: s.doc_label for s in R.SCHEMES}


def test_views_and_table_maps():
    assert {k: v.count_view for k, v in cross_scheme.SPECS.items()} == {s.name: s.main_view for s in R.SCHEMES}
    for s in R.SCHEMES:
        assert prompt_builder._scheme_of(s.main_view.split(".", 1)[1]) == s.name
    assert NAMES <= set(schema_introspect._TABLE_NAME_TO_SCHEME.values())


def test_pipeline_and_schema_registries_cover_exactly_the_six():
    assert set(p._SCHEME_NAME_MATCHER) == NAMES
    assert set(p._SCHEME_DATA_YEARS) == NAMES
    assert set(schema_context.SCHEME_CATALOG) == NAMES
    assert set(schema_context.SCHEME_METRICS) == NAMES


def test_constituency_capability():
    assert set(p._AC_CAPABLE_SCHEMES) == {s.name for s in R.SCHEMES if s.records_constituency}
    # KI-445 (open): the cross-scheme list omits CM Elevate — pinned so it cannot drift further.
    assert set(p._CROSS_AC_RECORDED) == {s.name for s in R.SCHEMES if s.records_constituency} - {"CM Elevate"}


def test_user_facing_text_names_every_scheme():
    for text in (settings.ASR_PROMPT, guardrails._SCOPE, edge._OUT_OF_SCOPE_REPLY):
        assert all(n in text for n in NAMES), [n for n in NAMES if n not in text]


def test_the_frontend_scheme_list():
    src = (ROOT / "frontend" / "src" / "chat" / "components" / "Messages.jsx").read_text(encoding="utf-8")
    line = next(ln for ln in src.splitlines() if "const SCHEME_NAMES" in ln)
    items = [x.strip().strip("'\"") for x in line.split("[", 1)[1].split("]", 1)[0].split(",")]
    assert tuple(items) == R.NAMES

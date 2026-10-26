"""No top-level name is defined twice across the pipeline files (2026-10-26).

app/pipeline/__init__.py executes every file of _PIPELINE_FILES into ONE namespace, so
a second definition of a name silently replaces the first for every caller. A new
_C02_UNITS table (ranking counts) replaced the spoken-year one of the same name and
"two zero two three" stopped reading as 2023 — caught only by an unrelated test."""
import ast
from collections import defaultdict
from pathlib import Path

from app import pipeline

_ROOT = Path(pipeline.__file__).resolve().parent


def _top_level_names(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append((node.name, node.lineno))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            out += [(t.id, node.lineno) for t in targets if isinstance(t, ast.Name)]
    return out


def test_no_name_is_defined_twice_in_the_shared_namespace():
    seen = defaultdict(list)
    for rel in pipeline._PIPELINE_FILES:
        path = _ROOT / f"{rel}.py"
        for name, line in _top_level_names(path):
            seen[name].append(f"{rel}.py:{line}")
    dupes = {n: where for n, where in seen.items() if len(where) > 1 and n != "__doc__"}
    assert not dupes, f"defined more than once (the later one wins everywhere): {dupes}"

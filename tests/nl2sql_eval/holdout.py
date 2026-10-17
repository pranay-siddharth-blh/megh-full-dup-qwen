"""
Hold-out guard for the NL->SQL accuracy set: no eval question may appear in the
"fix loop" — anything the pipeline is tuned on or tested against. If one does,
the score stops measuring accuracy (a failure can be "fixed" by pasting the
answer into a prompt), so the runner refuses to score until it is replaced.

The fix loop is:
  - data/**/*.yaml|json       few-shot banks, rules, schema partitions — the
                              text the SQL prompt is built from
  - meghalaya/*.csv (< 1 MB)  the scheme use-case / test-case sheets (the
                              large CSVs there are raw data dumps, not questions)
  - reference_documents/*.xlsx  test-case results and reports
  - tests/**/*.py             every string the unit and sheet tests use
                              (this folder excluded)
  - app/**/*.py               strings and comments (incident questions quoted
                              in code are fixes too)

A question is "leaked" when, after normalising (lower case, letters and digits
only), it scores >= LEAK_SCORE with rapidfuzz.fuzz.ratio against any sentence
of that corpus — catches copies and light rewordings, not a question that
merely shares a topic.

    python -m tests.nl2sql_eval.holdout            # check questions.yaml
"""
import ast
import csv
import io
import json
import sys
import tokenize
from functools import lru_cache
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
QUESTIONS = HERE / "questions.yaml"
LEAK_SCORE = 88
_MIN_CHARS = 12
_MAX_CSV_BYTES = 1_000_000


def norm(text: str) -> str:
    low = (text or "").lower()
    keep = "".join(ch if ("a" <= ch <= "z" or "0" <= ch <= "9") else " " for ch in low)
    return " ".join(keep.split())          # runs of ASCII letters/digits


def _split(text: str) -> list[str]:
    """Cut at a run of '?', newlines or CRs; at whitespace following '.' or '!';
    and at ' | ' (one whitespace char on each side of the bar)."""
    parts, start, i, n = [], 0, 0, len(text)
    while i < n:
        ch = text[i]
        j = i
        if ch in "?\n\r":
            while j < n and text[j] in "?\n\r":
                j += 1
        elif ch.isspace() and i > 0 and text[i - 1] in ".!":
            while j < n and text[j].isspace():
                j += 1
        elif ch.isspace() and i + 2 < n and text[i + 1] == "|" and text[i + 2].isspace():
            j = i + 3
        if j > i:
            parts.append(text[start:i])
            start = i = j
        else:
            i += 1
    parts.append(text[start:])
    return parts


def _segments(text: str):
    for part in _split(text or ""):
        n = norm(part)
        if len(n) >= _MIN_CHARS:
            yield n


def _yaml_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _yaml_strings(k)
            yield from _yaml_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _yaml_strings(v)


def _py_strings(path: Path):
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                yield node.value
    except SyntaxError:
        yield src
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                yield tok.string
    except (tokenize.TokenError, IndentationError):
        pass


def _sources():
    """(label, text) for every fix-loop source."""
    for path in sorted((ROOT / "data").rglob("*")):
        if path.suffix in (".yaml", ".yml"):
            try:
                for s in _yaml_strings(yaml.safe_load(path.read_text(encoding="utf-8"))):
                    yield str(path.relative_to(ROOT)), s
            except yaml.YAMLError:
                yield str(path.relative_to(ROOT)), path.read_text(encoding="utf-8", errors="replace")
        elif path.suffix == ".json":
            try:
                for s in _yaml_strings(json.loads(path.read_text(encoding="utf-8"))):
                    yield str(path.relative_to(ROOT)), s
            except ValueError:
                pass
    for path in sorted((ROOT / "meghalaya").glob("*.csv")):
        if path.stat().st_size <= _MAX_CSV_BYTES:
            with path.open(encoding="utf-8", errors="replace", newline="") as f:
                for row in csv.reader(f):
                    for cell in row:
                        yield str(path.relative_to(ROOT)), cell
    try:
        import openpyxl
        for path in sorted((ROOT / "reference_documents").glob("*.xlsx")):
            if path.name.startswith("~$"):
                continue
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    for cell in row:
                        if isinstance(cell, str):
                            yield str(path.relative_to(ROOT)), cell
            wb.close()
    except ImportError:
        pass
    for base in ("tests", "app"):
        for path in sorted((ROOT / base).rglob("*.py")):
            if HERE in path.parents:
                continue
            for s in _py_strings(path):
                yield str(path.relative_to(ROOT)), s


@lru_cache(maxsize=1)
def corpus() -> "tuple[list[str], list[str]]":
    """(segments, their source labels), de-duplicated."""
    seen: dict[str, str] = {}
    for label, text in _sources():
        for seg in _segments(text):
            seen.setdefault(seg, label)
    return list(seen), list(seen.values())


def leak(question: str) -> "tuple[int, str, str] | None":
    """(score, matching text, source) if `question` is in the fix loop, else None."""
    segs, labels = corpus()
    q = norm(question)
    hit = process.extractOne(q, segs, scorer=fuzz.ratio, score_cutoff=LEAK_SCORE)
    if hit is None:
        return None
    text, score, idx = hit
    return int(score), text, labels[idx]


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def check(questions: list[dict]) -> list[dict]:
    """The leaked questions, each with its match."""
    out = []
    for q in questions:
        hit = leak(q["question"])
        if hit:
            out.append({"id": q["id"], "question": q["question"], "score": hit[0],
                        "matches": hit[1], "source": hit[2]})
    return out


def main() -> int:
    qs = load_questions(Path(sys.argv[1]) if len(sys.argv) > 1 else QUESTIONS)
    leaked = check(qs)
    segs, _ = corpus()
    print(f"{len(qs)} questions checked against {len(segs)} fix-loop sentences")
    for item in leaked:
        print(f"  LEAKED {item['id']} ({item['score']}): {item['question']!r}\n"
              f"         ~ {item['matches']!r}  [{item['source']}]")
    print("hold-out OK" if not leaked else f"{len(leaked)} leaked — replace them")
    return 1 if leaked else 0


if __name__ == "__main__":
    sys.exit(main())

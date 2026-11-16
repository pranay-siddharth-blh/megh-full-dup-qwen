"""The voice layer's domain pack (12 Nov 2026): everything Megh-specific the voice needs, read from one JSON file that
megh/domain/build_pack.py generates from Megh's own registries (+ megh/domain/voice_overlay.yaml).

    from domain import pack, scheme_names, district_names, measure_words, asr_prompt, fix_schemes

pack() is cached and re-read when the file changes (checked at most once a second), so a rebuilt pack reaches a running
engine at its next turn, with no restart. version() goes up on every (re)load: callers that derive their own tables
from the pack (megh/shaper.py) rebuild them when it moves. MEGH_DOMAIN_PACK=<path> points at another pack (tests).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PACK = HERE / "megh_pack.json"
CHECK_EVERY_S = 1.0

_LOCK = threading.Lock()
_S: dict = {"path": None, "mtime": None, "data": None, "checked": 0.0, "version": 0, "fixes": None, "terms": None}


def path() -> Path:
    return Path(_S["path"] or os.environ.get("MEGH_DOMAIN_PACK") or DEFAULT_PACK)


def use(p: str | os.PathLike | None) -> dict:
    """Point the loader at another pack (None = back to the default) and load it now."""
    with _LOCK:
        _S["path"] = str(p) if p else None
        _S["mtime"] = None
        _S["checked"] = 0.0
    return pack()


def _load(p: Path, mtime: float) -> None:
    data = json.loads(p.read_text(encoding="utf-8"))
    if not data.get("schemes"):
        raise ValueError(f"domain pack {p} has no schemes")
    _S["data"], _S["mtime"], _S["fixes"], _S["terms"] = data, mtime, None, None
    _S["version"] += 1


def pack() -> dict:
    now = time.monotonic()
    if _S["data"] is not None and now - _S["checked"] < CHECK_EVERY_S:
        return _S["data"]
    with _LOCK:
        p = path()
        _S["checked"] = now
        try:
            mtime = p.stat().st_mtime
        except OSError:
            if _S["data"] is not None:
                return _S["data"]                      # the file is being replaced: keep the last good pack
            raise FileNotFoundError(f"no domain pack at {p}: run megh/domain/build_pack.py") from None
        if mtime != _S["mtime"]:
            try:
                _load(p, mtime)
            except Exception:                          # noqa: BLE001   a broken file never replaces a good pack
                if _S["data"] is None:
                    raise
        return _S["data"]


def version() -> int:
    pack()
    return _S["version"]


# --- views of the pack ----------------------------------------------------------------------------------------------
def scheme_names(order: str = "registry") -> list[str]:
    """'registry' (Megh's own order), 'say' (namesakes together: how the voice lists them), 'match' (longest first)."""
    return list(pack()["order"][order])


def scheme(name: str) -> dict | None:
    return next((s for s in pack()["schemes"] if s["name"] == name), None)


def district_names(order: str = "pack") -> list[str]:
    """'pack' (LGD code order), 'match' (longest first), 'asr' (the recogniser's priming order)."""
    p = pack()
    if order == "match":
        return list(p["places"]["district_match_order"])
    if order == "asr":
        return list(p["asr"]["district_order"])
    return [d["name"] for d in p["places"]["districts"]]


def block_names() -> list[str]:
    return [b["name"] for b in pack()["places"]["blocks"]]


def measure_words() -> set[str]:
    return set(pack()["shaper"]["measure_words"])


def asr_prompt() -> str:
    return pack()["asr"]["prompt"]


def product() -> dict:
    return dict(pack().get("product") or {})


def scheme_count_word() -> str:
    return pack()["shaper"]["scheme_count_word"]


def scheme_fixes() -> list[tuple[re.Pattern, str]]:
    """(compiled pattern, canonical name), in order: how the recogniser mishears each scheme."""
    p = pack()
    if _S["fixes"] is None:
        _S["fixes"] = [(re.compile(f["pattern"], re.I), f["to"]) for f in p["asr"]["fixes"]]
    return _S["fixes"]


def fix_schemes(text: str) -> str:
    """Scheme names as Megh writes them (what megh/adapter.py clean() does with its _SCHEME_FIX)."""
    for rx, name in scheme_fixes():
        text = rx.sub(name, text)
    return text


def term_fixes() -> list[tuple[re.Pattern, str]]:
    """(compiled pattern, the word as Megh writes it): how the recogniser mishears a measure ('person dies')."""
    p = pack()
    if _S["terms"] is None:
        _S["terms"] = [(re.compile(f["pattern"], re.I), f["to"]) for f in p["asr"].get("term_fixes") or []]
    return _S["terms"]


def fix_terms(text: str) -> str:
    for rx, word in term_fixes():
        text = rx.sub(word, text)
    return text


def dashboard_question(name: str) -> str:
    """The charted question that stands for "the dashboard / overview / visualisation of <scheme>" (12 Nov: Megh's
    pipeline reads "overview of CM Elevate" as a knowledge question and "dashboard of CM Elevate" as a clarification,
    so the voice asks the scheme's own headline breakdown instead). Empty when the pack has none for that scheme."""
    s = scheme(name) or {}
    return str(((s.get("voice") or {}).get("dashboard")) or "")

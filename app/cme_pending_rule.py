"""CM Elevate application rules, read from the knowledge base, never typed into code.

The user's decisions (2026-10-30):

* Every CM Elevate application COUNT includes only valid applications (`applications_default`),
  unless the question names a verification state — answered exactly as asked — or asks for ALL
  applications — then no filter and the total is split by `verification_states`.
* PENDING (`pending_rule`): data verified Valid, file status Pending or Send Back. An "on hold"
  question means the same thing (never the data_verified outcome); a level-wise question is the
  same rule grouped or filtered by current_level. Every other state (Invalid / Wrong, resubmit,
  Rejected) is reported only when the question names it.

The rules live in data/cm_elevate/cmelevate_pending_rule.yaml (its own file: the
*_default_rules.yaml files are NOT LOADED by app code, ingestion team 2026-10-26):

    applications_default: { column: data_verified, label: "valid", values: [Valid] }
    verification_states:  { column: data_verified, values: [Valid, "On Hold", Wrong, Invalid] }
    pending_rule:
    - { column: data_verified, label: "data verified", values: [Valid] }
    - { column: "scheme_specific ->> 'file_status'", label: "file status", values: [Pending, "Send Back"] }

Steps are AND-ed; a step's values are OR-ed (`IN` for exact values, `LIKE` for a trailing `%`,
case-folded when `fold_case`). Change the YAML and every SQL guard, fixed query and prompt line
follows; the file is re-read when its mtime changes, so no restart is needed.

file_status is inside scheme_specific, which the chatbot's database role may not read until the
DB team grants it (KI-624). `readable()` is that gate: every column the pending rule needs must be
among the columns the read-only role may SELECT (schema_introspect.live_columns). If the DB team
adds a plain file_status column instead, point the YAML at it and the gate opens by itself.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

RULE_FILE = Path(__file__).resolve().parents[1] / "data" / "cm_elevate" / "cmelevate_pending_rule.yaml"
VIEW = "curated.v_cm_elevate"

_cache: dict = {"mtime": None, "data": {}}


def _valid(step) -> bool:
    return (isinstance(step, dict) and isinstance(step.get("column"), str) and step["column"].strip()
            and isinstance(step.get("values"), list) and len(step["values"]) > 0)


def _load() -> dict:
    """The whole file, re-read when it changes. A missing / unparsable file keeps the last good
    content (logged once per change)."""
    try:
        mtime = RULE_FILE.stat().st_mtime
    except OSError as e:
        if _cache["mtime"] != "missing":
            logger.error("cme_pending_rule: %s not readable: %s", RULE_FILE, e)
            _cache.update(mtime="missing", data={})
        return _cache["data"]
    if _cache["mtime"] == mtime:
        return _cache["data"]
    try:
        data = yaml.safe_load(RULE_FILE.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            logger.error("cme_pending_rule: %s is not a mapping — no rules", RULE_FILE.name)
            data = {}
        rule = data.get("pending_rule")
        rule = rule if isinstance(rule, list) else []
        good = [s for s in rule if _valid(s)]
        if len(good) != len(rule):
            logger.error("cme_pending_rule: %d malformed pending step(s) in %s ignored", len(rule) - len(good), RULE_FILE.name)
        if not good:
            logger.error("cme_pending_rule: no usable pending_rule in %s — nothing counts as pending", RULE_FILE.name)
        data["pending_rule"] = good
        if not _valid(data.get("applications_default")):
            if data.get("applications_default") is not None:
                logger.error("cme_pending_rule: applications_default in %s is malformed — no default filter", RULE_FILE.name)
            data["applications_default"] = None
        if not _valid(data.get("verification_states")):
            data["verification_states"] = None
    except Exception as e:  # noqa: BLE001 — a YAML error keeps the last good rules
        logger.error("cme_pending_rule: %s could not be parsed (%s); keeping the previous rules", RULE_FILE.name, e)
        data = _cache["data"]
    _cache.update(mtime=mtime, data=data)
    return data


# ── the pending rule ─────────────────────────────────────────────────────────
def steps() -> list[dict]:
    """The pending rule's steps ([] when the file has no usable rule: nothing is pending)."""
    return list(_load().get("pending_rule") or [])


def _lit(value: str, fold: bool) -> str:
    v = str(value).lower() if fold else str(value)
    return "'" + v.replace("'", "''") + "'"


def _step_sql(step: dict) -> str:
    col = step["column"].strip()
    fold = bool(step.get("fold_case"))
    lhs = f"LOWER({col})" if fold else col
    exact = [str(v) for v in step["values"] if not str(v).endswith("%")]
    prefixes = [str(v)[:-1] for v in step["values"] if str(v).endswith("%")]
    parts = []
    if len(exact) == 1:
        parts.append(f"{lhs} = {_lit(exact[0], fold)}")
    elif exact:
        parts.append(f"{lhs} IN ({', '.join(_lit(v, fold) for v in exact)})")
    parts.extend(f"{lhs} LIKE {_lit(p, fold)[:-1]}%'" for p in prefixes)
    return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"


def sql() -> str:
    """The whole pending rule as one SQL condition over curated.v_cm_elevate ("FALSE" when no rule)."""
    s = steps()
    return " AND ".join(_step_sql(x) for x in s) if s else "FALSE"


def _values_text(step: dict) -> str:
    return " or ".join(str(v).rstrip("%") for v in step["values"])


def text() -> str:
    """One sentence for answers and the prompt, from the same steps:
    'Pending means: data verified Valid, and file status Pending or Send Back.'"""
    bits = [f"{str(s.get('label') or s['column']).strip()} {_values_text(s)}" for s in steps()]
    if not bits:
        return "No pending rule is defined."
    body = bits[0] if len(bits) == 1 else ", ".join(bits[:-1]) + ", and " + bits[-1]
    return f"Pending means: {body}."


def base_column(col: str) -> str:
    """The view column a step reads: `scheme_specific ->> 'file_status'` -> scheme_specific."""
    return col.split("->>")[0].split("->")[0].strip().strip('"').lower()


def columns() -> set[str]:
    return {base_column(s["column"]) for s in steps()}


def json_keys() -> set[str]:
    """JSON keys the pending rule reads (`col ->> 'key'`), lower-case."""
    out = set()
    for s in steps():
        col = s["column"]
        if "->>" in col:
            out.add(col.split("->>", 1)[1].strip().strip("'\"").lower())
    return out


def file_status_column() -> str | None:
    """The column of the step labelled 'file status' (used for "sent back" and the like)."""
    for s in steps():
        if str(s.get("label") or "").strip().lower() == "file status":
            return s["column"].strip()
    return None


def readable() -> bool:
    """Every column the pending rule needs is among those the chatbot's read-only role may SELECT.
    False until the live schema has been read, so a cold start never writes a locked column."""
    from app import schema_introspect   # local: schema_introspect imports db at module level
    live = {str(c.get("column") or "").lower()
            for c in (schema_introspect.live_columns() or {}).get(VIEW) or []}
    need = columns()
    return bool(live) and bool(need) and need <= live


# ── which applications count by default ──────────────────────────────────────
def default_step() -> dict | None:
    return _load().get("applications_default")


def default_sql() -> str:
    """The default-applications condition ('' when the knowledge base sets none)."""
    d = default_step()
    return _step_sql(d) if d else ""


def default_column() -> str:
    d = default_step()
    return base_column(d["column"]) if d else ""


def default_text() -> str:
    """The word for the default rows in answers: 'valid' (the step's label, else its values)."""
    d = default_step()
    if not d:
        return ""
    return str(d.get("label") or _values_text(d)).strip().lower()


def verification_states() -> tuple[str, list[str]]:
    """(column, values) of the split shown when all applications are asked for."""
    v = _load().get("verification_states")
    if not v:
        return default_column(), []
    return base_column(v["column"]), [str(x) for x in v["values"]]

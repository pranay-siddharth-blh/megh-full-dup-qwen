"""Personal data out of what the app keeps: the audit trail and the log lines (14 Nov 2026, guardrail).

DPDP Act 2023 + DPDP Rules 2025 (data minimisation) and the MeitY AI Governance Guidelines (accountability): the
audit trail must say WHO asked WHAT and what the system did, but it must not become a second copy of the personal data
an officer happens to type ("call 9876543210 about Aadhaar 1234 5678 9012"). Every question, rewritten question, SQL
text, error, answer and shadow-log wording written to `logs/*.jsonl`, to `app.query_audit`, or to a log line passes
through ONE function, `mask_text`, chosen by `settings.PII_LOG_MODE`:

  masked (default)  phone numbers (10 digits, +91 / 0 prefixes, 5-5 / 3-3-4 groups), Aadhaar (12 digits, 4-4-4),
                    any other run of 9+ digits (bank accounts), e-mail addresses, IFSC, PAN, EPIC (voter id) and
                    MGNREGA job-card numbers (ML-02-005-012-001/123) are replaced by a label with at most the last two
                    digits. Figures stay readable: 54,89,616 / 3,628.67 / 2023-24 / 12 districts / 90915181.
                    IP addresses keep their network part (10.48.242.x).
  full              unchanged (local debugging only).
  off               free text is not kept at all, only its length and a short hash (to match the same question
                    across records); log lines lose their quoted text.

Port of the IDEA of D:/Full Duplex Architecture/megh/adapter.py `mask_log`, written with string methods only: the
team rule is no regular expressions in app/ (D-046 / D-047; tests/test_accuracy_gold_fixes_2026_11_11.py enforces it).
"""
from __future__ import annotations

import hashlib
import logging

MODES = ("masked", "full", "off")

# The record fields that carry free text (what an officer typed, what the model wrote, what the database said).
TEXT_FIELDS = frozenset(("question", "rewritten_question", "raw_question", "plan_question", "translated_question",
                         "sql", "sql_text", "error", "error_text", "answer", "wording", "said", "heard", "text"))
IP_FIELDS = frozenset(("ip", "client_ip", "remote_addr"))


def mode() -> str:
    """The configured mode; anything unknown is 'masked' (fail closed)."""
    try:
        from app.config import settings
        m = str(getattr(settings, "PII_LOG_MODE", "masked") or "masked").strip().lower()
    except Exception:  # noqa: BLE001 — a broken config never un-masks
        m = "masked"
    return m if m in MODES else "masked"


# ── e-mail ─────────────────────────────────────────────────────────────────
_LOCAL_OK = set("._%+-")
_DOMAIN_OK = set(".-")


def _mask_emails(text: str) -> str:
    if "@" not in text:
        return text
    out, i, n = [], 0, len(text)
    last = 0
    while i < n:
        if text[i] != "@":
            i += 1
            continue
        a = i
        while a > 0 and (text[a - 1].isalnum() or text[a - 1] in _LOCAL_OK) and text[a - 1].isascii():
            a -= 1
        b = i + 1
        while b < n and (text[b].isalnum() or text[b] in _DOMAIN_OK) and text[b].isascii():
            b += 1
        while b > i + 1 and text[b - 1] in _DOMAIN_OK:      # a sentence's full stop is not the domain
            b -= 1
        domain = text[i + 1:b]
        labels = domain.split(".")
        if a < i and len(labels) >= 2 and all(labels) and labels[-1].isalpha() and a >= last:
            out.append(text[last:a])
            out.append("[email]")
            last = b
            i = b
            continue
        i += 1
    out.append(text[last:])
    return "".join(out)


# ── identifiers written with letters (IFSC, PAN, EPIC, job cards) ─────────
def _id_label(chunk: str) -> str:
    """The label for a token that is a personal identifier, or ''."""
    c = chunk
    if len(c) == 11 and c[:4].isalpha() and c[:4].isupper() and c[4] == "0" and c[5:].isalnum() \
            and any(ch.isdigit() for ch in c[5:]) and c.isascii():
        return "[ifsc]"
    if len(c) == 10 and c.isascii() and c[:5].isalpha() and c[:5].isupper() and c[5:9].isdigit() \
            and c[9].isalpha() and c[9].isupper():
        return "[pan]"
    if len(c) == 10 and c.isascii() and c[:3].isalpha() and c[:3].isupper() and c[3:].isdigit():
        return "[voter id]"
    # MGNREGA job card: state code, then district / block / panchayat / village groups, then /family: ML-02-005-012-001/123
    head, _, family = c.partition("/")
    parts = head.split("-")
    if len(parts) >= 5 and len(parts[0]) == 2 and parts[0].isalpha() and parts[0].isupper() and parts[0].isascii() \
            and all(p.isdigit() and p.isascii() for p in parts[1:]) and (not family or family.isdigit()):
        return "[job card]"
    return ""


def _mask_ids(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if not (ch.isalnum() and ch.isascii()):
            out.append(ch)
            i += 1
            continue
        j = i
        while j < n and ((text[j].isalnum() and text[j].isascii()) or text[j] in "-/"):
            j += 1
        k = j
        while k > i and text[k - 1] in "-/":
            k -= 1
        chunk = text[i:k]
        label = _id_label(chunk) if any(c.isalpha() for c in chunk) else ""
        out.append(label or chunk)
        out.append(text[k:j])
        i = j
    return "".join(out)


# ── numbers ────────────────────────────────────────────────────────────────
def _is_year(g: str) -> bool:
    return len(g) == 4 and g.isdigit() and 1900 <= int(g) <= 2099


def _phone(d: str) -> bool:
    """10 digits of an Indian mobile, with or without its 91 / 0 prefix."""
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return len(d) == 10 and d[0] in "6789"


_PHONE_SHAPES = {(10,), (5, 5), (3, 3, 4), (4, 3, 3), (3, 4, 3), (2, 4, 4)}
_HEX = set("0123456789abcdefABCDEF")


def _system_id(text: str, i: int, j: int) -> bool:
    """The digits text[i:j] are part of an id the system made (a UUID, a hash, a request id), not a person's number:
    the token around them (letters, digits, '-', '_') is a 36-character UUID or a hex string of 16+ characters."""
    a, b, n = i, j, len(text)
    while a > 0 and (text[a - 1].isalnum() or text[a - 1] in "-_") and text[a - 1].isascii():
        a -= 1
    while b < n and (text[b].isalnum() or text[b] in "-_") and text[b].isascii():
        b += 1
    tok = text[a:b]
    if len(tok) == 36 and tok.count("-") == 4 and all(c in _HEX or c == "-" for c in tok):
        return True
    return len(tok) >= 16 and all(c in _HEX for c in tok) and any(c.isalpha() for c in tok)


def _label(groups: list[str]) -> str:
    """The masked form of a run of digit groups (separated by one space or hyphen), or '' to keep it."""
    digits = "".join(groups)
    shape = tuple(len(g) for g in groups)
    tail = digits[-2:]
    if len(groups) > 1:
        if all(_is_year(g) or len(g) <= 2 for g in groups):
            return ""                                    # 2023-2024, 2019 2020 2021, 2023-24
        body = groups[1:] if groups[0] in ("91", "0") and len(groups) > 1 else groups
        if tuple(len(g) for g in body) in _PHONE_SHAPES and _phone("".join(body)):
            return f"[phone ending {tail}]"
        if shape == (4, 4, 4):
            return f"[aadhaar ending {tail}]"
        if len(groups) <= 3 and _phone(digits):
            return f"[phone ending {tail}]"              # 098765 43210, 98 76 543210
        if len(digits) >= 11 and all(len(g) >= 2 for g in groups) and sum(len(g) >= 3 for g in groups) >= 3:
            return f"[number ending {tail}]"             # an account number written in blocks
        return ""
    if len(digits) < 9:
        return ""
    if _phone(digits):
        return f"[phone ending {tail}]"
    if len(digits) == 12 and digits[0] not in "01":
        return f"[aadhaar ending {tail}]"
    return f"[number ending {tail}]"


def _mask_numbers(text: str) -> str:
    out, i, n = [], 0, len(text)
    last = 0
    while i < n:
        if not (text[i].isdigit() and text[i].isascii()):
            i += 1
            continue
        prev = text[i - 1] if i else ""
        if prev and (prev.isdigit() or ((prev in ",.") and i >= 2 and text[i - 2].isdigit())):
            i += 1
            continue
        groups, spans, j = [], [], i
        while True:
            k = j
            while k < n and text[k].isdigit() and text[k].isascii():
                k += 1
            groups.append(text[j:k])
            spans.append((j, k))
            if k + 1 < n and text[k] in " -" and text[k + 1].isdigit() and text[k + 1].isascii():
                j = k + 1
                continue
            break
        end = spans[-1][1]
        # a figure written with grouping commas or decimals (54,89,616 / 3,628.67) is a figure, never an identifier
        if end + 1 < n and text[end] in ",." and text[end + 1].isdigit():
            k = end
            while k < n and (text[k].isdigit() or (text[k] in ",." and k + 1 < n and text[k + 1].isdigit())):
                k += 1
            i = k
            continue
        if _system_id(text, i, end):
            i = end
            continue
        lab = _label(groups)
        if lab:
            start = i
            if start >= 1 and text[start - 1] == "+":
                start -= 1                               # +91 98765 43210
            out.append(text[last:start])
            out.append(lab)
            last = end
            i = end
            continue
        if len(groups) > 1:                              # no shape as a whole: each group on its own
            for (a, b), g in zip(spans, groups):
                lg = _label([g])
                if lg:
                    out.append(text[last:a])
                    out.append(lg)
                    last = b
        i = end
    out.append(text[last:])
    return "".join(out)


# ── public ─────────────────────────────────────────────────────────────────
def fingerprint(text: str) -> str:
    return f"[withheld: {len(text)} chars, sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}]"


def mask_text(text, mode_: str | None = None):
    """`text` as it may be kept. Non-strings are returned unchanged."""
    if not isinstance(text, str) or not text:
        return text
    m = mode_ or mode()
    if m == "full":
        return text
    if m == "off":
        return fingerprint(text)
    return _mask_numbers(_mask_ids(_mask_emails(text)))


def mask_ip(ip, mode_: str | None = None):
    """An IP address as it may be kept: its network part only (masked), as is (full), nothing (off)."""
    if not isinstance(ip, str) or not ip:
        return ip
    m = mode_ or mode()
    if m == "full":
        return ip
    if m == "off":
        return "[withheld]"
    if ip.count(".") == 3 and ":" not in ip:
        return ip.rsplit(".", 1)[0] + ".x"
    if ":" in ip:
        parts = ip.split(":")
        return ":".join(parts[:3]) + "::x"
    return "[ip]"


def mask_record(record: dict, mode_: str | None = None) -> dict:
    """A copy of an audit / shadow-log record with every free-text field (TEXT_FIELDS) and IP masked. Nested dicts
    and lists are walked; labels, ids, counts, timings and booleans are kept as they are."""
    m = mode_ or mode()
    if m == "full" or not isinstance(record, dict):
        return record

    def walk(v, key=""):
        if isinstance(v, dict):
            return {k: walk(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, key) for x in v]
        if isinstance(v, str):
            if key in IP_FIELDS:
                return mask_ip(v, m)
            if key in TEXT_FIELDS:
                return mask_text(v, m)
        return v
    return walk(record)


# ── log lines ──────────────────────────────────────────────────────────────
def _strip_quoted(text: str) -> str:
    """'off' for a log line: every quoted text ('...' or "...") becomes its length. A quote inside a word
    (don't) does not open one."""
    out, i, n, last = [], 0, len(text), 0
    while i < n:
        q = text[i]
        if q in "'\"" and (i == 0 or not text[i - 1].isalnum()):
            j = text.find(q, i + 1)
            while j != -1 and j + 1 < n and text[j + 1].isalnum():
                j = text.find(q, j + 1)
            if j != -1:
                out.append(text[last:i])
                out.append(f"<{j - i - 1} chars>")
                last = i = j + 1
                continue
        i += 1
    out.append(text[last:])
    return "".join(out)


def mask_log_text(text: str, mode_: str | None = None) -> str:
    m = mode_ or mode()
    if m == "full" or not isinstance(text, str):
        return text
    masked = _mask_numbers(_mask_ids(_mask_emails(text)))
    return _strip_quoted(masked) if m == "off" else masked


class _Masked:
    """A log argument that is not a plain value (a dict, a list, an exception): masked when the line is formatted."""
    __slots__ = ("v", "m")

    def __init__(self, v, m):
        self.v, self.m = v, m

    def __str__(self):
        return mask_log_text(str(self.v), self.m)

    def __repr__(self):
        return mask_log_text(repr(self.v), self.m)


_PLAIN = (int, float, bool, type(None), bytes)


def mask_log_record(record: logging.LogRecord) -> logging.LogRecord:
    """Mask a log record in place: its message and each argument (the argument tuple keeps its shape, so a formatter
    that reads record.args, such as uvicorn's access log, still works)."""
    m = mode()
    if m == "full":
        return record
    try:
        if isinstance(record.msg, str):
            record.msg = mask_log_text(record.msg, m)
        args = record.args
        if isinstance(args, tuple) and args:
            record.args = tuple(mask_log_text(a, m) if isinstance(a, str) else a if isinstance(a, _PLAIN)
                                else _Masked(a, m) for a in args)
        elif isinstance(args, dict) and args:
            record.args = {k: mask_log_text(a, m) if isinstance(a, str) else a if isinstance(a, _PLAIN)
                           else _Masked(a, m) for k, a in args.items()}
        if record.exc_info and not record.exc_text and isinstance(record.exc_info, tuple):
            # a traceback can quote the SQL or the question (a database error message): formatted and masked now;
            # Formatter.format uses exc_text as it is
            record.exc_text = mask_log_text(logging.Formatter().formatException(record.exc_info), m)
    except Exception:  # noqa: BLE001 — masking never loses a log line
        pass
    return record


_installed = {"factory": None}


def install_log_masking() -> None:
    """Every log record made in this process is masked as it is created (a record factory, so it covers every
    logger and handler, uvicorn's included). Idempotent."""
    if _installed["factory"] is not None:
        return
    base = logging.getLogRecordFactory()

    def factory(*a, **k):
        return mask_log_record(base(*a, **k))
    _installed["factory"] = factory
    logging.setLogRecordFactory(factory)

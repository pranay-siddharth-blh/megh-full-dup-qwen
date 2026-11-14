"""Personal data out of the audit trail and the logs (14 Nov 2026; app/pii_mask.py, settings.PII_LOG_MODE).

DPDP Act 2023 / Rules 2025 data minimisation: the question, rewritten question, SQL, error and IP written to
logs/query_audit.jsonl, app.query_audit, the shadow logs and every log line pass through one masking function.
Figures, years and counts stay readable. Cases ported from the Full Duplex adapter's mask_log test (G3).
"""
import asyncio
import json
import logging

import pytest

from app import auth, pii_mask
from app.config import settings


@pytest.fixture(autouse=True)
def _masked(monkeypatch):
    monkeypatch.setattr(settings, "PII_LOG_MODE", "masked")


@pytest.mark.parametrize("raw,keep,gone", [
    ("heard 'my number is 9876543210 please call'", ["heard", "please call", "ending 10"], ["9876543210"]),
    ("heard 'Aadhaar 1234 5678 9012 of the beneficiary'", ["beneficiary", "aadhaar ending 12"], ["1234 5678 9012"]),
    ("Aadhaar 234567890123", ["aadhaar ending 23"], ["234567890123"]),
    ("mail it to officer.name@meghalaya.gov.in today.", ["[email]", "today."], ["officer.name@", "meghalaya.gov"]),
    ("call +91 98765 43210 or +91-9876543210 or 987-654-3210 or 919876543210", ["phone ending 10"],
     ["98765 43210", "9876543210", "987-654-3210", "919876543210"]),
    ("account 123456789012345 at SBIN0001234", ["number ending 45", "[ifsc]"], ["123456789012345", "SBIN0001234"]),
    ("account 1234-5678-9012-34", ["number ending 34"], ["1234-5678-9012-34"]),
    ("PAN ABCDE1234F, EPIC ABC1234567", ["[pan]", "[voter id]"], ["ABCDE1234F", "ABC1234567"]),
    ("job card ML-02-005-012-001/123 is stuck", ["[job card]", "is stuck"], ["ML-02-005-012-001"]),
    ("SELECT * FROM t WHERE mobile = '9876543210' LIMIT 1000", ["LIMIT 1000", "[phone ending 10]"], ["9876543210"]),
])
def test_personal_numbers_are_masked(raw, keep, gone):
    out = pii_mask.mask_text(raw)
    assert all(k in out for k in keep) and not any(g in out for g in gone), out


@pytest.mark.parametrize("raw", [
    "54,89,616 person-days in West Garo Hills in FY 2023-24",
    "MGNREGA person-days in 2023-24 for 12 districts, 1,75,39,710 in total",
    "₹3,628.67 crore spent; 90915181 person days",
    "years 2019 2020 2021, 2022-2023, 14-11-2026 and 2026-11-14T10:00:00+0530",
    "district code 291001, LGD 123456, block 7, top 15",
    "1,29,941 houses; 9999999999.50 rupees as a decimal amount",
    "session 550e8400-e29b-41d4-a716-446655440000 request a1b2c3d4e5f6a7b8c9d0123456789012",
    "SELECT district, SUM(persondays) FROM curated.v_employment WHERE year_key = '2023-24' GROUP BY 1 LIMIT 500",
    "How many job cards were issued in Mawphlang block in FY 2025-26?",
    "",
])
def test_figures_years_counts_and_system_ids_stay_readable(raw):
    assert pii_mask.mask_text(raw) == raw


def test_full_and_off_modes():
    raw = "call 9876543210 about MGNREGA"
    assert pii_mask.mask_text(raw, "full") == raw
    off = pii_mask.mask_text(raw, "off")
    assert "9876543210" not in off and "MGNREGA" not in off and "29 chars" in off
    # the same words give the same fingerprint, so one question can be followed across records
    assert pii_mask.mask_text(raw, "off") == off


def test_an_unknown_mode_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "PII_LOG_MODE", "verbose")
    assert pii_mask.mode() == "masked"
    assert "9876543210" not in pii_mask.mask_text("9876543210")


def test_ip_addresses_keep_their_network_part():
    assert pii_mask.mask_ip("10.48.242.4") == "10.48.242.x"
    assert pii_mask.mask_ip("2001:db8:85a3:0:0:8a2e:370:7334") == "2001:db8:85a3::x"
    assert pii_mask.mask_ip("10.48.242.4", "full") == "10.48.242.4"
    assert pii_mask.mask_ip("10.48.242.4", "off") == "[withheld]"
    assert pii_mask.mask_ip(None) is None


def test_mask_record_masks_text_fields_and_keeps_labels():
    rec = {"question": "status of job card ML-02-005-012-001/123, call 9876543210",
           "rewritten_question": None, "sql": "SELECT 1 WHERE phone='9876543210'", "error": None,
           "ip": "10.48.242.4", "username": "wgh-officer", "session_id": "s-123456789012",
           "request_id": "rid-9", "row_count": 1234567890, "schemes": ["MGNREGA"],
           "plan": {"question": "ring 9876543210", "measure": "persondays"}}
    out = pii_mask.mask_record(rec)
    assert "9876543210" not in json.dumps(out) and "ML-02-005" not in json.dumps(out)
    assert out["ip"] == "10.48.242.x"
    # labels, ids and counts are kept exactly
    for k in ("username", "session_id", "request_id", "row_count", "schemes", "rewritten_question", "error"):
        assert out[k] == rec[k]
    assert out["plan"]["measure"] == "persondays"
    assert rec["question"].endswith("9876543210")            # the caller's record is not changed


def test_the_audit_jsonl_is_masked(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(auth, "_audit_path", path)
    auth.audit({"question": "Aadhaar 1234 5678 9012 status?", "sql": "SELECT 1", "ip": "192.168.1.77",
                "username": "u1", "row_count": 3})
    rec = json.loads(path.read_text(encoding="utf-8").strip())
    assert rec["question"] == "Aadhaar [aadhaar ending 12] status?"
    assert rec["ip"] == "192.168.1.x" and rec["username"] == "u1" and rec["row_count"] == 3 and rec["ts"]
    monkeypatch.setattr(settings, "PII_LOG_MODE", "full")
    auth.audit({"question": "Aadhaar 1234 5678 9012 status?"})
    last = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert last["question"] == "Aadhaar 1234 5678 9012 status?"


def test_the_db_audit_row_is_masked_and_the_chat_history_is_not(monkeypatch):
    from app import conversation_store, db
    calls = []

    async def fake_fetchval(sql, params):
        return 1

    async def fake_execute(sql, params):
        calls.append((sql, params))

    monkeypatch.setattr(db, "fetchval", fake_fetchval)
    monkeypatch.setattr(db, "execute", fake_execute)
    q = "job cards for 9876543210 in Tura"
    result = {"route": "data", "answer": "x", "sql": "SELECT 1 WHERE m='9876543210'", "row_count": 1,
              "rewritten_question": "job cards for 9876543210 in Tura block"}
    audit = {"sql": result["sql"], "error": "bad value 9876543210", "outcome": "failed"}
    asyncio.run(conversation_store._persist_turn("t", 1, "s", result, q, 5.0, "u", "10.0.0.9", audit))
    _, aud = next(c for c in calls if "query_audit" in c[0])
    flat = json.dumps(aud, default=str)
    assert "9876543210" not in flat and "[phone ending 10]" in flat
    assert aud[13] == "10.0.0.x"
    _, turn = next(c for c in calls if "conversation_turns" in c[0])
    assert turn[4] == q                                        # the officer's own history keeps the words


def test_log_lines_are_masked_as_they_are_made():
    pii_mask.install_log_masking()
    pii_mask.install_log_masking()                             # idempotent
    seen = []

    class H(logging.Handler):
        def emit(self, record):
            seen.append(self.format(record))

    log = logging.getLogger("test.pii")
    h = H()
    log.addHandler(h)
    log.setLevel(logging.INFO)
    try:
        log.info("question %r from %s", "call 9876543210", "officer.name@meghalaya.gov.in")
        log.info("payload %s", {"q": "Aadhaar 1234 5678 9012", "n": 54_89_616})
        log.info("plain 54,89,616 person-days in 2023-24, id 919876543210")
        log.info("count %d of %s", 12, "x")
        log.warning("access %s %s %s", "10.0.0.1:5000", "GET", "/api/x?phone=9876543210")
    finally:
        log.removeHandler(h)
    text = "\n".join(seen)
    assert "9876543210" not in text and "officer.name@" not in text and "1234 5678 9012" not in text
    assert "54,89,616 person-days in 2023-24" in text and "count 12 of x" in text
    assert "[email]" in text and "[aadhaar ending 12]" in text


def test_a_traceback_in_a_log_line_is_masked_too():
    pii_mask.install_log_masking()
    seen = []

    class H(logging.Handler):
        def emit(self, record):
            seen.append(self.format(record))

    h = H()
    h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("test.pii.exc")
    log.addHandler(h)
    try:
        try:
            raise ValueError("invalid input for query: mobile = '9876543210'")
        except ValueError:
            log.exception("query failed")
    finally:
        log.removeHandler(h)
    assert seen and "9876543210" not in seen[0] and "[phone ending 10]" in seen[0] and "ValueError" in seen[0]


def test_log_off_mode_drops_quoted_text(monkeypatch):
    monkeypatch.setattr(settings, "PII_LOG_MODE", "off")
    out = pii_mask.mask_log_text("heard 'MGNREGA person-days in West Garo Hills' and \"Tura\"; don't")
    assert "MGNREGA" not in out and "<38 chars>" in out and "<4 chars>" in out and "don't" in out


def test_the_pii_module_uses_no_regex():
    from pathlib import Path
    src = Path(pii_mask.__file__).read_text(encoding="utf-8")
    assert "import re\n" not in src and "re.compile" not in src

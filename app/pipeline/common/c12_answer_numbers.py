# app/pipeline/common/c12_answer_numbers.py — number checks and shared deterministic answers.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.



import numbers as _c12_numbers   # own alias: a file may bind `numbers` to text_match.numbers

# ── Numeric faithfulness guard for the composed answer ──────────────────────
# The composer is an LLM and will occasionally transcribe a number wrong
# ("170981" -> "17098"). On a government dashboard that is unacceptable, so the
# composed sentence is checked against the actual result values: any number it
# states that is not in the data (beyond rounding tolerance) triggers one strict
# retry, then a deterministic fallback sentence built straight from the rows.
def _c12_dec(ch: str) -> bool:
    r"""One digit character (a Unicode decimal digit)."""
    return ch.isdecimal()


def _c12_num_spans(text: str) -> "list[tuple[int, int]]":
    r"""Spans of an optional '-', a digit, any run of digits and commas, then
    an optional '.' with one or more digits (trailing commas included; a '-'
    is kept only right before a digit)."""
    out, i, n = [], 0, len(text)
    while i < n:
        s0 = i
        if text[i] == "-" and i + 1 < n and _c12_dec(text[i + 1]):
            i += 1
        if not _c12_dec(text[i]):
            i = s0 + 1
            continue
        j = i + 1
        while j < n and (_c12_dec(text[j]) or text[j] == ","):
            j += 1
        if j + 1 < n and text[j] == "." and _c12_dec(text[j + 1]):
            j += 2
            while j < n and _c12_dec(text[j]):
                j += 1
        out.append((s0, j))
        i = j
    return out


_NUM_TOKEN = _C1xScan(_c12_num_spans)

# "the data doesn't cover / isn't available / can't be broken down" — a hedge the
# composer must not use when the query actually returned a usable non-zero value.
def _c12_nt(stem: str):
    r""""<stem>n't" written "dont", "don't" or "don’t" (the stem may end a longer word)."""
    return Alt(_c1x_suffix(stem + "nt"),
               Seq(_c1x_suffix(stem + "n"), _C1xGapIs(W("t"), lambda g: g in ("'", "’"))))


# No word edge is required in front of the first word of each phrase or after
# most last words, so a lead word matches as a word ENDING ("cannot" holds "not")
# and an open last word as a word START ("not covering").
_HEDGE_MATCH = Matcher(Alt(
    Seq(Alt(_c12_nt("do"), _c12_nt("does")), W("cover", prefix=True), sep="space"),
    Seq(_c1x_suffix("not"), W("cover", prefix=True), sep="space"),          # also "does not cover(ed)"
    Seq(_c12_nt("is"), W("covered", prefix=True), sep="space"),
    Seq(_c1x_suffix("not"), W("available", prefix=True), sep="space"),
    Seq(_c1x_suffix("no"), W("data"), sep="space"),
    Seq(Alt(_c12_nt("does"), Seq(_c1x_suffix("does"), "not", sep="space"), _c12_nt("do"),
            Seq(_c1x_suffix("do"), "not", sep="space")),
        W("have", "include", "contain", "provide", prefix=True), sep="space"),
    Seq(_c1x_suffix("only"), W("provide", "provides"), sep="space"),
    Seq(Alt(_c1x_suffix("cannot"), _c1x_suffix("cant"),
            Seq(_c1x_suffix("can"), _C1xGapIs(W("t"), lambda g: g in ("'", "’")))),
        Opt("be"), Alt(Seq("broken", W("down", prefix=True), sep="space"), W("split", prefix=True)),
        sep="space"),
    Seq(_c1x_suffix("no"), Opt("specific"), W("breakdown", "split"), sep="space"),
))


def _c12_plain_number(s: str) -> bool:
    r"""The whole string is an optional '-', digits, and an optional '.digits'."""
    body = s[1:] if s.startswith("-") else s
    whole, dot, frac = body.partition(".")
    return whole.isdecimal() and (not dot or frac.isdecimal())


def _c12_year_like(raw: str) -> bool:
    r"""The whole string is an optional '-' and a 4-digit year starting 19, 20 or
    21, or a '-' and two digits — a year, or a "-YY" range tail."""
    body = raw[1:] if raw.startswith("-") else raw
    if len(body) == 4 and body.isdecimal() and body[:2] in ("19", "20", "21"):
        return True
    return raw.startswith("-") and len(body) == 2 and body.isdecimal()


def _as_number(v: object) -> "int | float | None":
    """Coerce a result cell to int/float, or None if it isn't numeric. Handles
    decimal.Decimal (asyncpg returns it for SUM/AVG over numeric columns — the
    reason a cross-scheme SUM was being skipped) without relying on
    Decimal.is_integer(), which is Python 3.12+ only."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, _c12_numbers.Number):          # float, Decimal, Fraction, …
        f = float(v)
        return int(f) if f.is_integer() else f
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if _c12_plain_number(s):
            return int(s) if "." not in s else float(s)
    return None


def _data_numbers(rows: list[dict]) -> set[str]:
    """Every numeric leaf value in the result, as normalised digit strings."""
    out: set[str] = set()
    for row in rows:
        for v in row.values():
            n = _as_number(v)
            if n is None:
                continue
            if isinstance(n, int):
                out.add(str(n))
            else:
                out.add(f"{n:g}")
                out.add(f"{n:.2f}".rstrip("0").rstrip("."))
    return out


def _answer_numbers_faithful(answer: str, data_nums: set[str]) -> bool:
    """True if every 'reported' number in the answer traces back to a data value.
    Years and small integers (< 100, no decimal) are treated as prose, not data."""
    data_floats: list[float] = []
    for d in data_nums:
        try:
            data_floats.append(float(d))
        except ValueError:
            pass
    for tok in _NUM_TOKEN.findall(answer):
        raw = tok.replace(",", "")
        # A year or a financial-year range fragment — "2020", "2020-2021",
        # "2020-21" — is prose, not a measured quantity. The number tokenizer
        # splits "2020-2021" into "2020" and "-2021" (the hyphen read as a
        # sign), so the second-half forms "-YYYY" / "-YY" are matched here too.
        if _c12_year_like(raw):
            continue
        try:
            fval = float(raw)
        except ValueError:
            continue
        if abs(fval) < 100 and "." not in raw:         # ordinal / "one or two"
            continue
        if raw in data_nums:
            continue
        if any(dv == fval or (dv and abs(dv - fval) / abs(dv) <= 0.005)
               or abs(dv - fval) < 0.5 for dv in data_floats):
            continue
        return False
    return True


# A comma-grouped number in either house style: Western 1,234,567 or Indian
# 12,34,567. Anything else ("1,0263") is a mis-grouped figure.
def _c12_grouped_spans(text: str) -> "list[tuple[int, int]]":
    r"""The spans of 1-3 digits, one or more ',digits' groups, an optional
    decimal part, not touching another digit / comma / point in front or a
    digit / comma behind (a decimal part followed by a comma is given back
    and the span ends before it)."""
    out, i, n = [], 0, len(text)
    while i < n:
        if not _c12_dec(text[i]) or (i > 0 and (_c12_dec(text[i - 1]) or text[i - 1] in ",.")):
            i += 1
            continue
        a = i
        while a < n and _c12_dec(text[a]):
            a += 1
        g = a
        if a - i <= 3:
            while g + 1 < n and text[g] == "," and _c12_dec(text[g + 1]):
                g += 2
                while g < n and _c12_dec(text[g]):
                    g += 1
        if g == a or (g < n and text[g] == ","):
            i = a
            continue
        end = g
        if g + 1 < n and text[g] == "." and _c12_dec(text[g + 1]):
            d = g + 2
            while d < n and _c12_dec(text[d]):
                d += 1
            if not (d < n and text[d] == ","):
                end = d
        out.append((i, end))
        i = end
    return out


_GROUPED_NUM = _C1xScan(_c12_grouped_spans)


def _c12_valid_grouping(whole: str) -> bool:
    r"""The whole string is 1-3 digits then ',ddd' groups, or 1-2 digits, any
    ',dd' groups, then ',ddd': Western 1,234,567 or Indian 12,34,567 grouping."""
    parts = whole.split(",")
    if len(parts) < 2 or not all(p.isdecimal() for p in parts):
        return False
    western = 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:])
    indian = 1 <= len(parts[0]) <= 2 and all(len(p) == 2 for p in parts[1:-1]) and len(parts[-1]) == 3
    return western or indian


def _fix_digit_grouping(answer: str, data_nums: set[str]) -> str:
    """Re-group a mis-grouped number whose digits ARE a result value.

    The composer wrote "1,0263 female beneficiaries" for 10,263 on both live
    runs, and the faithfulness check strips commas before comparing, so the
    garbled figure reached the officer (Focus Plus use-case QA 2026-09-27,
    FOCUS-021b, KI-062). Only a token that is valid in neither Western nor
    Indian grouping AND whose digits match the data is rewritten — a list like
    "Tranches 1,2" is never a data value and is left alone."""
    def _fix(m: "Hit") -> str:
        tok = m.group(0)
        whole, _, frac = tok.partition(".")
        if _c12_valid_grouping(whole):
            return tok
        digits = whole.replace(",", "")
        n = _as_number(digits + ("." + frac if frac else ""))
        if n is None or len(digits) < 4:   # "1,2" is a list, never a grouped figure
            return tok
        forms = {digits + ("." + frac if frac else ""), f"{n:g}" if isinstance(n, float) else str(n)}
        if not forms & data_nums:
            return tok
        return f"{int(digits):,}" + ("." + frac if frac else "")
    return _GROUPED_NUM.sub(_fix, answer)


# Numbers inside the executed SQL's quoted literals — '12.5K', 'Tranch 4 -
# Feb-March', '2025-26' — are the filter's LABELS, not measured figures. An
# answer that names its own filter ("under the 12.5K batch") must not be
# flagged as a misquote for it: that flag threw away a correct sentence and
# put the row-dump fallback "31,317,500 amount raw." in front of the officer
# (Focus Plus use-case QA 2026-09-27, FOCUS-006a, KI-064).
def _sql_string_literal_tokens(sql: str) -> list:
    """The STRING tokens of `sql` (every statement), from the sqlglot tokenizer:
    a quote inside a comment or an identifier is not a literal. [] when the
    text cannot be tokenized."""
    return [t for t in _sql_tokens(sql or "") if t.token_type == TokenType.STRING]


_ASCII_DIGITS = frozenset("0123456789")


def _digit_runs(text: str) -> "list[str]":
    """Every number written in `text` ('12.5K' -> '12.5', 'Tranch 4' -> '4')."""
    out, i, n = [], 0, len(text or "")
    while i < n:
        if text[i] in _ASCII_DIGITS:
            j = i
            while j < n and text[j] in _ASCII_DIGITS:
                j += 1
            if j + 1 < n and text[j] == "." and text[j + 1] in _ASCII_DIGITS:
                j += 1
                while j < n and text[j] in _ASCII_DIGITS:
                    j += 1
            out.append(text[i:j])
            i = j
        else:
            i += 1
    return out


def _sql_literal_numbers(sql: str) -> set[str]:
    out: set[str] = set()
    for tok in _sql_string_literal_tokens(sql or ""):
        out.update(_digit_runs(tok.text))
    return out


def _row_metrics(row: dict) -> list[tuple[str, "int | float"]]:
    """(column, numeric value) for every numeric cell in the row — Decimal included."""
    out: list[tuple[str, "int | float"]] = []
    for k, v in row.items():
        n = _as_number(v)
        if n is not None:
            out.append((k, n))
    return out


def _fmt_num(v: "int | float") -> str:
    return f"{v:,}" if isinstance(v, int) else f"{v:,.2f}"


def _answer_covers_metrics(answer: str, row: dict) -> bool:
    """Every numeric metric in a single aggregate row must appear in the answer —
    catches a cross-scheme result where the composer names only one side."""
    ans = answer.replace(",", "")
    for _k, v in _row_metrics(row):
        forms = {str(v)}
        if isinstance(v, float):
            forms.add(f"{v:.2f}".rstrip("0").rstrip("."))
        if not any(f in ans for f in forms):
            return False
    return True


# Numeric-looking columns that must NOT be summed/averaged — years, codes, ids,
# rank/serial numbers, resolved *_key columns. Reported as dimension coverage
# (distinct values) instead. Deliberately narrow: "no"/"sr" are omitted because
# they collide with "no_of_*" count columns; the real offenders are
# financial_year, *_code, *_id and pincode.
_C12_NONSTAT_PARTS = frozenset({"year", "yr", "fy", "pincode", "rank", "serial"})


def _c12_nonstat_spans(name: str) -> "list[tuple[int, int]]":
    """Case-insensitive, on a column name: one '_'-separated part is year, yr,
    fy, pincode, rank or serial (a year / code word), or the name ends in
    _key / _code / _id, or is "id"."""
    low = name.lower()
    pos = 0
    for part in low.split("_"):
        if part in _C12_NONSTAT_PARTS:
            return [(pos, pos + len(part))]
        pos += len(part) + 1
    for suf in ("_key", "_code", "_id"):
        if low.endswith(suf):
            return [(len(low) - len(suf), len(low))]
    if low == "id":
        return [(0, 2)]
    return []


_NONSTAT_COL = _C1xScan(_c12_nonstat_spans)


# The mean of a result column goes in the digest only when the question asks for
# an average. "gender wise breakup of applications" (Focus Plus, 2 rows) was
# answered "...with a mean of 6,263.50 per gender" (user report 2026-10-19): a
# figure nobody asked for and that means nothing, offered because the digest
# handed every multi-row result a mean and whitelisted it. Left out, a mean the
# composer still writes fails the numeric-faithfulness check.
_ASKS_AVERAGE = Matcher(W("average", "averages", "avg", "mean", "median", "typical", "typically"))


def _result_digest(rows: list[dict], max_values: int = 40,
                   with_mean: bool = True) -> "tuple[str, set[str]]":
    """A deterministic whole-result summary, computed from EVERY row (not just the
    preview the composer is shown): the distinct coverage of each dimension
    column, and sum / mean / max / min of each numeric column together with which
    dimension row holds the max and the min.

    Returns (indented_text_block, allowed_number_strings). The strings are unioned
    into the numeric-faithfulness whitelist so a total or average the composer
    copies out of this block is not flagged as an invented number. Without this,
    any multi-row result (a district x year matrix, a per-block list) could only
    be described one visible cell at a time — never "the total is X" or "Y is
    highest" — because those figures are not present in the raw rows."""
    if len(rows) < 2:
        return "", set()

    dim_order: dict[str, list[str]] = {}
    dim_seen: dict[str, set[str]] = {}
    num_cols: list[str] = []
    for row in rows:
        for k, v in row.items():
            is_num = _as_number(v) is not None
            if is_num and not _NONSTAT_COL.search(k):
                if k not in num_cols:
                    num_cols.append(k)
                continue
            if v is None:
                continue
            s = str(v)
            if k not in dim_order:
                dim_order[k], dim_seen[k] = [], set()
            if s not in dim_seen[k]:
                dim_seen[k].add(s)
                dim_order[k].append(s)

    def _label(row: dict) -> str:
        parts = [str(row[k]) for k in dim_order if row.get(k) is not None]
        return " / ".join(parts) if parts else "(row)"

    lines: list[str] = [f"total rows: {len(rows)}"]
    allowed: set[str] = set()

    for k, vals in dim_order.items():
        shown = ", ".join(vals) if len(vals) <= max_values else f"{len(vals)} distinct values"
        lines.append(f"{k} ({len(vals)}): {shown}")

    for k in num_cols:
        pairs = [(r, _as_number(r.get(k))) for r in rows if _as_number(r.get(k)) is not None]
        if not pairs:
            continue
        nums = [n for _r, n in pairs]
        total = sum(nums)
        hi_row, hi = max(pairs, key=lambda p: p[1])
        lo_row, lo = min(pairs, key=lambda p: p[1])
        mean = total / len(nums)
        for val in (total, hi, lo) + ((mean,) if with_mean else ()):
            f = float(val)
            allowed.add(str(int(f)) if f.is_integer() else f"{f:g}")
            allowed.add(f"{f:.2f}".rstrip("0").rstrip("."))
        mean_part = f"mean={_fmt_num(round(mean, 2))}; " if with_mean else ""
        lines.append(
            f"{k}: sum={_fmt_num(total)}; {mean_part}"
            f"max={_fmt_num(hi)} at [{_label(hi_row)}]; min={_fmt_num(lo)} at [{_label(lo_row)}]"
        )

    return "\n".join(f"  - {ln}" for ln in lines), allowed


def _deterministic_answer(rows: list[dict]) -> str:
    """A plain, exact sentence from the rows — used only when the LLM composer
    keeps misquoting or dropping numbers."""
    if len(rows) == 1:
        row = rows[0]
        nums = _row_metrics(row)
        # A single-row GROUP BY result (e.g. a category breakdown that happens
        # to have exactly one value present, like verification_status =
        # 'Approved' on every 12.5K row) still carries the category as a
        # non-numeric column. Drop the number alone and the answer misreports
        # a labelled breakdown as an unlabelled total.
        labels = [str(v) for k, v in row.items() if v is not None and _as_number(v) is None]
        prefix = ", ".join(labels) + ": " if labels else ""
        if len(nums) == 1:
            k, v = nums[0]
            # A unit-suffixed column reads "<measure> <value> <unit>": the old
            # "<value> <column name>" gave "2023-24: 8.71 lakh total expenditure
            # lakh." once the MGNREGA unit pass added its own "lakh" (KI-235).
            unit = _unit_suffix(k)
            if unit:
                name, word, rupee = unit
                sep = "" if word in ("", "%") else " "
                return f"{prefix}{name} {rupee}{_fmt_num(v)}{sep}{word}."
            return f"{prefix}{_fmt_num(v)} {k.replace('_', ' ')}."
        if len(nums) >= 2:
            return prefix + "; ".join(f"{k.replace('_', ' ')}: {_fmt_num(v)}" for k, v in nums) + "."
    # Multi-row: one labelled line per row. This used to be a raw
    # "Results — col: val; col: val" dump of the first 5 rows only, which read as
    # debug output and silently dropped the rest (a 12-district summary showed 5
    # districts — CM Elevate Legacy use-case QA TC-25 / TC-36, 2026-09-25).
    shown = rows[:_DETERMINISTIC_MAX_ROWS]
    lines = []
    for r in shown:
        labels = [str(v) for v in r.values() if v is not None and _as_number(v) is None]
        metrics = ", ".join(f"{_metric_label(k)}: {_fmt_num(v)}" for k, v in _row_metrics(r))
        head = " / ".join(labels) or "(no label)"
        lines.append(f"- {head} — {metrics}" if metrics else f"- {head}")
    more = len(rows) - len(shown)
    tail = f"\n…and {more} more row{'s' if more != 1 else ''} in the table." if more > 0 else ""
    return f"Here are the {len(rows)} results:\n" + "\n".join(lines) + tail


_DETERMINISTIC_MAX_ROWS = 15


# ── Professional framing of an answer (user report 2026-10-18) ──────────────
# "1,494,437 household years." and "household years: 1,494,437; person years:
# 1,865,234; financial years: 4." reached the officer as the whole answer (the
# composer's sentence had failed the number check, so the bare fallback above
# was shown). Every answer must read as a briefing line: the scheme, what the
# figure counts in plain words, the area and the period. The fallback is framed
# here; every composed answer goes through _finish_answer (digit grouping, and a
# scope sentence when neither the scheme nor the area is named).
_HUMAN_METRIC = {
    "household_years": "household-years of employment",
    "person_years": "person-years of employment",
    "households_employed": "households provided employment",
    "persons_employed": "persons provided employment",
    "person_days": "person-days of employment",
    "persondays": "person-days of employment",
    "job_cards_issued_total": "job cards issued",
    "job_cards": "job cards issued",
    "households_completed_100_days": "households that completed 100 days of work",
    "women_employment_provided": "person-days of employment provided to women",
    "houses": "houses", "houses_sanctioned": "houses sanctioned", "houses_completed": "houses completed",
    "completed_houses": "completed houses", "sanctioned_houses": "sanctioned houses",
    "beneficiaries": "beneficiaries", "beneficiary_count": "beneficiaries",
    "applications": "applications", "applicants": "applicants", "application_count": "applications",
    "producer_groups": "producer groups", "members": "members", "memberships": "memberships paid",
    "financial_years": "financial years covered", "years": "financial years covered",
    "villages": "villages", "blocks": "blocks", "districts": "districts",
}
_METRIC_CAVEAT = {
    "household_years": ("A household is counted once for each financial year it worked, so this is not a "
                        "count of distinct households."),
    "person_years": ("A person is counted once for each financial year they worked, so this is not a count "
                     "of distinct persons."),
}


def _human_metric(col: str) -> str:
    key = str(col).lower()
    if key in _HUMAN_METRIC:
        return _HUMAN_METRIC[key]
    unit = _unit_suffix(key)
    if unit:
        name, word, rupee = unit
        return f"{name} ({rupee}{word})" if (word or rupee) else name
    return _metric_label(key)


def _scope_words(schemes: "list[str] | None", entities: "dict | None") -> tuple[str, str, str]:
    """(scheme, place, period) in words: ("MGNREGA", "Mawphlang block", "FY 2023-24").
    Place falls back to "all of Meghalaya (statewide)", period to "across all
    financial years"; scheme is "" for a cross-scheme or unknown result."""
    ents = entities or {}
    scheme = schemes[0] if schemes and len(schemes) == 1 else ""
    place = ""
    for key, word in (("village", "village"), ("block", "block"), ("assembly_constituency", "constituency"),
                      ("district", "district")):
        v = ents.get(key)
        if v:
            name = str(v).title() if str(v).isupper() else str(v)
            place = f"{name} {word}"
            break
    if not place:
        place = "all of Meghalaya (statewide)"
    year = ents.get("year") or ents.get("financial_year") or ""
    period = str(year) if year else "across all financial years"
    if period and period[0].isdigit():
        period = f"FY {period}"
    return scheme, place, period


def _framed_fallback(rows: list[dict], schemes: "list[str] | None", entities: "dict | None") -> str:
    """The deterministic answer as a briefing sentence: scheme, figure, what it
    counts, area and period — never a bare "<value> <column>."."""
    scheme, place, period = _scope_words(schemes, entities)
    lead = f"Under {scheme}, " if scheme else ""
    where = f"in {place}"
    when = period if period.startswith("across") else f"in {period}"
    if len(rows) == 1:
        row = rows[0]
        nums = _row_metrics(row)
        labels = [str(v) for k, v in row.items() if v is not None and _as_number(v) is None]
        for_labels = f"for {', '.join(labels)}, " if labels else ""
        parts = []
        caveats = []
        for k, v in nums:
            unit = _unit_suffix(str(k))
            if unit:
                name, word, rupee = unit
                sep = "" if word in ("", "%") else " "
                parts.append(f"{rupee}{_fmt_num(v)}{sep}{word} {name}".strip())
            else:
                parts.append(f"{_fmt_num(v)} {_human_metric(str(k))}")
            if str(k).lower() in _METRIC_CAVEAT:
                caveats.append(_METRIC_CAVEAT[str(k).lower()])
        if not parts:
            return _deterministic_answer(rows)
        if len(parts) == 1:
            body = f"the recorded total is {parts[0]}"
        else:
            body = "the records show " + ", ".join(parts[:-1]) + f" and {parts[-1]}"
        sentence = f"{lead}{for_labels}{when} {where}, {body}."
        sentence = sentence[0].upper() + sentence[1:]
        return " ".join([sentence] + caveats)
    head = f"{lead}{when} {where}, here are the {len(rows)} results:"
    head = head[0].upper() + head[1:]
    body = _deterministic_answer(rows)
    first_nl = body.find("\n")
    return head + (body[first_nl:] if first_nl >= 0 else "\n" + body)


def _is_fallback_answer(answer: str, rows: list[dict], schemes: "list[str] | None", entities: "dict | None") -> bool:
    """Was `answer` written by the deterministic fallback (bare or framed)?"""
    a = (answer or "").strip()
    return a in (_deterministic_answer(rows).strip(), _framed_fallback(rows, schemes, entities).strip())


from app.text_match import number_spans as _c12_number_spans  # noqa: E402 — the framing pass below


def _group_result_digits(answer: str, rows: list[dict]) -> str:
    """Thousands separators for every result integer of five or more digits that
    the answer writes bare ("27264054" -> "27,264,054"). Years and small counts
    are left alone; only tokens that ARE a result value are touched."""
    values = {int(v) for r in rows for _k, v in _row_metrics(r) if isinstance(v, int) or float(v).is_integer()}
    if not values or not answer:
        return answer
    out, last = [], 0
    for start, end, tok in _c12_number_spans(answer, decimals=True, commas=True):
        # four digits too (6847 -> 6,847), except a year-like value (2017..2100)
        if tok.isdecimal() and len(tok) >= 4 and int(tok) in values and not (1900 <= int(tok) <= 2100):
            out.append(answer[last:start]); out.append(f"{int(tok):,}"); last = end
    out.append(answer[last:])
    return "".join(out)


# "Total person-days for FY 2023-24 across all financial years is 27,264,054":
# the 9B composer named the year AND the all-years phrase in one sentence on a
# correctly single-year SQL (D-053 live probe, 2026-10-19). On a single-year
# result the phrase is wrong by construction, so _finish_answer drops it on
# words, with the separator it hung on, before the scope sentence is judged.
_C12_ALL_YEARS_PHRASE = Matcher(Seq(Opt(W("across", "over", "for", "in", "during", "of")), "all", Opt("the"),
                                    Opt(W("financial", "fiscal")), "years", Opt("combined")))
_C12_SENTENCE_BREAK = ".?!:;\n"


def _drop_all_years_phrase(text: str) -> str:
    """Remove every "across all financial years" (and kin) from `text`, keeping the
    sentence readable: a phrase mid-sentence goes with the separator before it and a
    comma after it; one that opens a sentence goes with its trailing comma and the
    next word is capitalised. Idempotent; text without the phrase is returned as is."""
    for _ in range(6):
        h = _C12_ALL_YEARS_PHRASE.search(text)
        if h is None:
            return text
        toks = tokens(text)
        prev = next((t for t in reversed(toks) if t.end <= h.start()), None)
        gap = text[prev.end:h.start()] if prev else text[:h.start()]
        after = text[h.end():]
        if prev is None or any(ch in gap for ch in _C12_SENTENCE_BREAK):
            # sentence-initial: "Across all financial years, MGNREGA ..." -> "MGNREGA ..."
            rest = after.lstrip(" ,")
            rest = rest[:1].upper() + rest[1:]
            text = text[:h.start()] + rest
            continue
        # ", across all financial years, X" keeps one comma ("..., X"); a phrase that
        # hung on a space but is followed by a comma takes that comma with it
        if "," not in gap and after.lstrip().startswith(","):
            after = after.lstrip()[1:]
            if not after[:1].isspace():
                after = " " + after
        text = text[:prev.end] + after
    return text


def _finish_answer(answer: str, rows: list[dict], schemes: "list[str] | None", entities: "dict | None") -> str:
    """The universal last pass over a data answer: result figures carry thousands
    separators, and a single-figure answer that does not name the scheme or the
    area gets one closing scope sentence, so the officer always reads what the
    figure is for. Idempotent: a framed answer is left as it is."""
    if not answer:
        return answer
    text = _group_result_digits(answer, rows)
    scheme, place, period = _scope_words(schemes, entities)
    if period.startswith("FY"):
        text = _drop_all_years_phrase(text)
    if not scheme or len(rows) != 1:
        return text
    low = text.lower()
    statewide = place.startswith("all of")
    place_name = place.split(" (")[0]
    for word in (" district", " block", " village", " constituency"):
        if place_name.endswith(word):
            place_name = place_name[: -len(word)]
    names_scheme = scheme.lower() in low or scheme.lower().replace("-", "") in low.replace("-", "")
    names_place = ("meghalaya" in low or "statewide" in low) if statewide else place_name.lower() in low
    if names_scheme and names_place:
        return text
    # Already framed: the composer path and the finalize node both run this, and
    # the short closing sentence ("This is the MGNREGA figure.") names no place,
    # so a second pass added another one (harness AC07, 2026-10-19).
    if "This is the " in text and " figure" in text or "This figure is for " in text:
        return text
    place_text = "all of Meghalaya" if statewide else place
    # Only what the sentence leaves out: "…in East Khasi Hills across FY 2022-23.
    # This is the MGNREGA figure for East Khasi Hills district, FY 2022-23." said
    # the place and the year twice (Conversational Memory approach, 2026-10-19).
    fy = period[3:] if period.startswith("FY ") else ""
    when = "" if (fy and fy in text) else f", {period}"
    if not names_scheme and not names_place:
        tail = f"This figure is for {scheme}, {place_text}{' (statewide)' if statewide else ''}{when}."
    elif not names_scheme:
        tail = f"This is the {scheme} figure{(' for ' + period) if when else ''}."
    else:
        tail = f"This is the {'statewide ' if statewide else ''}figure for {place_text}{when}."
    return f"{text.rstrip()} {tail}"


def _display_from_resolved(resolved: "dict | None") -> dict:
    """The display-style entities (_scope_words reads) from a result's resolved
    entities: Title Case places and "FY 2023-24" for year_key."""
    r = resolved or {}
    out = {}
    for k in ("district", "block", "village", "assembly_constituency"):
        if r.get(k):
            out[k] = str(r[k]).title()
    y = r.get("year_key")
    if y is not None:
        try:
            out["year"] = f"FY {int(y)}-{(int(y) + 1) % 100:02d}"
        except (TypeError, ValueError):
            pass
    return out


def _finish_data_result(result: dict) -> None:
    """_finish_answer for a finished DATA result, whichever path wrote it (the
    composer, a scheme's deterministic facts, a fixed query): called from the
    finalize node so every data answer reads as a briefing line."""
    if not isinstance(result, dict) or result.get("route") != "data" or result.get("answer_failed"):
        return
    rows = result.get("rows") or result.get("data") or []
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return
    try:
        result["answer"] = _finish_answer(result.get("answer") or "", rows, result.get("schemes") or [],
                                          _display_from_resolved(result.get("resolved_entities")))
    except Exception:  # noqa: BLE001 — presentation only; the answer stands as written
        logger.warning("_finish_data_result failed (non-fatal)", exc_info=True)


def _unit_suffix(col: str) -> "tuple[str, str, str] | None":
    """(measure name, unit word, ₹ prefix) for a money / percentage column by its
    SQL-prompt suffix (total_expenditure_lakh -> ("total expenditure", "lakh", "")),
    else None."""
    for suffix, word, rupee in (("_lakh", "lakh", ""), ("_cr", "crore", "₹"), ("_crore", "crore", "₹"),
                                ("_rupees", "", "₹"), ("_pct", "%", "")):
        if col.endswith(suffix) and len(col) > len(suffix):
            return col[: -len(suffix)].replace("_", " "), word, rupee
    return None


def _metric_label(col: str) -> str:
    """A readable name for a result column: total_disbursed_cr -> 'total disbursed
    (₹ crore)'. The unit suffixes are the SQL-prompt conventions (_cr, _lakh,
    _pct, _rupees)."""
    for suffix, unit in (("_cr", " (₹ crore)"), ("_lakh", " (₹ lakh)"),
                         ("_pct", " (%)"), ("_rupees", " (₹)")):
        if col.endswith(suffix):
            return col[: -len(suffix)].replace("_", " ") + unit
    return col.replace("_", " ")


def _no_data_answer(schemes: list[str] | None, entities: dict[str, str] | None) -> str:
    """Plain 'nothing matched' message for a query that returned no rows at all.
    Built deterministically rather than left to the composer — on an empty
    result it sometimes free-forms RAG-style refusal wording ("the reference
    material does not contain...") that reads like an internal document search
    failed, when the honest answer is just that no records match the filters."""
    scope_bits = [v for v in (entities or {}).values() if v]
    scope = f" for {', '.join(scope_bits)}" if scope_bits else ""
    # One sentence, nothing else. The full capability catalogue used to be
    # appended here ("Data I do have here:" + every metric for the scheme),
    # which buried a one-line fact under a ~10-line dump the user did not ask
    # for and could not act on (reported 2026-09-18). An empty result answers
    # the question asked; what else the dataset could report is a different
    # question, and the NEXT STEPS chips already offer it.
    return f"I couldn't find any matching records{scope} in the data available."


def _is_plain_list_result(rows: list[dict]) -> bool:
    """A multi-row result whose rows carry no numeric metric — a pure list of
    dimension values (e.g. the districts that satisfy a coverage filter). Those
    rows ARE the answer; a 'not covered / can't tell' hedge over them is wrong."""
    return len(rows) >= 2 and not any(_row_metrics(r) for r in rows)


def _deterministic_list_answer(rows: list[dict]) -> str:
    """Plain sentence naming every value in a single-column list result — used
    when the composer hedges over a membership answer whose rows already are the
    answer set."""
    cols = list(rows[0].keys())
    if len(cols) == 1:
        vals = [str(r[cols[0]]) for r in rows if r.get(cols[0]) is not None]
        label = cols[0].replace("_", " ")
        if len(vals) <= 40:
            return f"{len(vals)} {label} values match: " + ", ".join(vals) + "."
        return (f"{len(vals)} {label} values match, including: "
                + ", ".join(vals[:40]) + ", …")
    return _deterministic_answer(rows)


_DIM_LABEL = {
    "district": "district",
    "block": "block (C&RD block)",
    "village": "village",
    "year": "financial year",
    "house_status": "house construction stage",
    "cm_scheme": "CM Elevate sub-scheme",
}


def _entity_names_block(entities: dict[str, str] | None) -> str:
    """A context block naming the canonical form of every place / year / category
    the query actually filtered on, so the composer uses the full proper name in
    its answer instead of echoing the user's abbreviation, code or misspelling
    ("wgh" -> "West Garo Hills", "fy24" -> "FY 2024-25")."""
    if not entities:
        return ""
    lines = [f"  - {_DIM_LABEL.get(k, k)}: {v}" for k, v in entities.items() if v]
    if not lines:
        return ""
    return (
        "\nEntity names — the query filtered on exactly these values. In your "
        "answer, refer to each place, year or category by the full name given "
        "here, even when the question used a short form, code or misspelling; "
        "never echo the user's shorthand back as the name.\n" + "\n".join(lines) + "\n"
    )
def _c12_pct_spans(text: str) -> list:
    r"""regex (\d+(?:\.\d+)?)\s*% — a percentage; group 1 is the number."""
    out, i, n = [], 0, len(text)
    while i < n:
        if not _c12_dec(text[i]):
            i += 1
            continue
        j = i
        while j < n and _c12_dec(text[j]):
            j += 1
        ends = []
        if j + 1 < n and text[j] == "." and _c12_dec(text[j + 1]):
            k = j + 1
            while k < n and _c12_dec(text[k]):
                k += 1
            ends.append(k)
        ends.append(j)
        hit = None
        for e in ends:
            q = e
            while q < n and text[q].isspace():
                q += 1
            if q < n and text[q] == "%":
                hit = (i, q + 1, [(i, e)])
                break
        if hit:
            out.append(hit)
            i = hit[1]
        else:
            i += 1
    return out


_PCT_TOKEN = _C1xScan(_c12_pct_spans)


def _answer_has_pcts(answer: str, pcts: list[float]) -> bool:
    stated = [float(m.group(1)) for m in _PCT_TOKEN.finditer(answer or "")]
    return all(any(abs(s - p) <= 0.06 for s in stated) for p in pcts)


_NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                 "fifteen sixteen seventeen eighteen nineteen twenty").split()
# tens and their compounds too: "Twenty-one producer groups received payments under
# Focus Legacy in Khliehriat East" (Focus Legacy all-villages run 2026-10-02)
_NUMBER_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_C12_UNITS = W(*_NUMBER_WORDS[1:10])
# "twenty-one" / "twenty one"
_C12_NUMBER_WORD = Alt(Seq(W(*_NUMBER_TENS), _C1xGapIs(_C12_UNITS, _c1x_ws_or_dash)), W(*_NUMBER_TENS),
                       W(*_NUMBER_WORDS))
_C12_COUNT_NOUN = Alt(
    W("applicant", "applicants", "application", "applications", "verified", "pending", "rejected",
      "withdrawn", "village", "villages", "programme", "programmes", "program", "programs",
      "scheme", "schemes", "record", "records",
      # every scheme's count nouns (all-blocks run 2026-10-02: "Eighteen
      # producer groups received payments under Focus Legacy in Shella
      # Bholaganj block")
      "group", "groups", "pg", "pgs", "beneficiary", "beneficiaries", "house", "houses",
      "household", "households", "payment", "payments", "member", "members",
      "block", "blocks", "district", "districts"),
    Seq("person", _C1xGapIs(W("day", "days"), _c1x_ws_or_dash0)), W("personday", "persondays"),
)


def _c12_letters_or_dash_word(w: str) -> bool:
    return w.isascii() and w.isalpha()


# A number word, not followed by "of", with a count noun within the next three
# words ("Five CM ELEVATE applicants …"); group 1 is the number word. (Was the
# regex \b(<number word>)\b(?!\s+of\b)(?=(?:\s+[A-Za-z-]+){0,3}?\s+<noun>\b).)
_NUMBER_WORD_MATCH = Matcher(Before(
    NotBefore(Cap(_C12_NUMBER_WORD), _C1xGapIs(W("of"), _c1x_ws)),
    Seq(_C1xRun(_c12_letters_or_dash_word, 0, 3, gap_ok=_c1x_ws_or_dash, first_gap_ok=_c1x_ws),
        _C1xGapIs(_C12_COUNT_NOUN, _c1x_ws)),
))

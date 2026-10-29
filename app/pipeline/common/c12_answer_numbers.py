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


# ── One money formatter (E9, 2026-10-29) ────────────────────────────────────
# Composer audit 2026-10-27: one answer wrote "₹39,41,96,000" beside a gap of
# "15,124,000" (PM-10), another "₹118,447,500.00" (FP-05), and the fallbacks wrote
# "8,996.36 lakh" with no ₹. Every money figure the code writes goes through
# _c12_money: ₹, Indian grouping, and the unit the column is in (MGNREGA's lakh
# stays lakh, so it reads like the composer's own copy of the digits). A rupee
# column picks crore / lakh / exact rupees by size, and a non-zero amount never
# prints as ₹0.00 crore (KI-171: ₹62,500 read "₹0.01 crore"). Digit grouping of
# counts is an open product decision and stays as it was (_fmt_num).
_C12_MONEY_SCALE = {"rupees": 1.0, "lakh": 1e5, "crore": 1e7}


def _c12_indian(n: float, decimals: int = 0) -> str:
    """Indian digit grouping: 1873378 -> '18,73,378'; (2185.256, 2) -> '2,185.26'."""
    s = f"{abs(float(n)):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, parts = whole[:-3], [whole[-3:]]
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + parts)
    sign = "-" if float(n) < 0 and s.strip("0.") else ""
    return sign + whole + ("." + frac if frac else "")


def _c12_money_unit(col: str) -> "str | None":
    """'rupees' / 'lakh' / 'crore' for a money column by its SQL-prompt suffix, else None."""
    unit = _unit_suffix(str(col).lower())
    if unit is None or unit[1] == "%":
        return None
    return {"lakh": "lakh", "crore": "crore", "": "rupees"}.get(unit[1])


def _c12_money(v: "int | float", unit: str = "rupees") -> str:
    """One money figure as the officer reads it (data-accuracy brief 2026-10-29, RC6;
    settles KI-449): ₹, Indian grouping, the exact amount, then its crore / lakh size
    in brackets — "₹37,49,31,500 (≈ ₹37.49 crore)", "₹52,56,58,223.25 (≈ ₹52.57
    crore)", "₹9,40,000 (≈ ₹9.40 lakh)", "₹35,000". No ".00" on a whole amount; paise
    only when present. A lakh column stays in lakh with its crore size: "₹25,701.49
    lakh (≈ ₹257.01 crore)". A crore column (the SQL already divided) has no exact
    rupees to show: "₹3,628.67 crore". A true zero is '₹0'."""
    rupees = float(v) * _C12_MONEY_SCALE[unit]
    sign, a = ("-" if rupees < 0 else ""), abs(rupees)
    if unit == "crore" and a >= 1e6:
        return f"{sign}₹{_c12_indian(a / 1e7, 2)} crore"
    if unit == "lakh" and a >= 1e4:
        lakh = f"{sign}₹{_c12_indian(a / 1e5, 2)} lakh"
        return lakh + (f" (≈ {sign}₹{_c12_indian(a / 1e7, 2)} crore)" if a >= 1e7 else "")
    exact = round(a, 2)
    out = f"{sign}₹{_c12_indian(exact, 0 if float(exact).is_integer() else 2)}"
    if a >= 1e7:
        return f"{out} (≈ {sign}₹{_c12_indian(a / 1e7, 2)} crore)"
    if a >= 1e5:
        return f"{out} (≈ {sign}₹{_c12_indian(a / 1e5, 2)} lakh)"
    return out


def _c12_is_pct_col(col: str) -> bool:
    """A percentage column: the _pct suffix, or a pct / percent / percentage name part."""
    return any(p in ("pct", "percent", "percentage") for p in str(col).lower().split("_"))


def _c12_fmt_value(col: str, v: "int | float") -> str:
    """One result value as code writes it: money through _c12_money, a percentage with
    '%', anything else with thousands separators (2 decimals for a fraction)."""
    unit = _c12_money_unit(col)
    if unit:
        return _c12_money(v, unit)
    f = float(v)
    n = int(f) if f.is_integer() else round(f, 2)
    if _c12_is_pct_col(col):
        return f"{_fmt_num(n)}%"
    return _fmt_num(n)


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
            if unit and _c12_money_unit(k):                 # one money formatter (E9)
                return f"{prefix}{unit[0]} {_c12_money(v, _c12_money_unit(k))}."
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
        metrics = ", ".join(f"{_unit_suffix(k)[0]}: {_c12_money(v, _c12_money_unit(k))}" if _c12_money_unit(k)
                            else f"{_metric_label(k)}: {_fmt_num(v)}" for k, v in _row_metrics(r))
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
            if unit and _c12_money_unit(str(k)):            # one money formatter (E9)
                parts.append(f"{_c12_money(v, _c12_money_unit(str(k)))} {unit[0]}")
            elif unit:
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


def _group_result_digits(answer: str, rows: list[dict], schemes: "list[str] | None" = None) -> str:
    """Thousands separators for every result integer of five or more digits that
    the answer writes bare ("27264054" -> "27,264,054"). Years and small counts
    are left alone; only tokens that ARE a result value are touched."""
    values = {int(v) for r in rows for _k, v in _row_metrics(r) if isinstance(v, int) or float(v).is_integer()}
    if not values or not answer:
        return _c12_normalise_figures(answer, rows, schemes)
    out, last = [], 0
    for start, end, tok in _c12_number_spans(answer, decimals=True, commas=True):
        # four digits too (6847 -> 6,847), except a year-like value (2017..2100)
        if tok.isdecimal() and len(tok) >= 4 and int(tok) in values and not (1900 <= int(tok) <= 2100):
            out.append(answer[last:start]); out.append(_c12_indian(int(tok))); last = end
    out.append(answer[last:])
    return _c12_normalise_figures("".join(out), rows, schemes)


# RAG fix report 2026-10-29, Issue 13: one chat wrote "₹1,197,392,500.00" (Focus Plus),
# another "₹21,85,25,98,…" (PMAY-G), a third "119.74" with no unit at all (a _cr column),
# while the dashboard cards write "₹119.74 Cr" and "3,85,671". The composer's own digits
# are put through the one money formatter (_c12_money) and the cards' Indian grouping:
#   - a ₹ / Rs / INR amount of one lakh or more -> "₹119.74 crore" / "₹8.50 lakh";
#   - a value of a _cr / _lakh / rupees result column written without its unit -> the
#     same, in the column's unit;
#   - a comma-grouped number of six or more digits -> Indian grouping ("3,85,671").
# A number already followed by crore / lakh, or by %, keeps its words.
_C12_UNIT_WORDS = frozenset({"crore", "crores", "cr", "lakh", "lakhs", "lac", "lacs"})


def _c12_rupee_prefix_start(answer: str, start: int) -> "int | None":
    """Where a ₹ / Rs / Rs. / INR written just before the number at `start` begins, else None."""
    head = answer[:start]
    trimmed = head.rstrip()
    if trimmed.endswith("₹"):
        return len(trimmed) - 1
    for p in ("Rs.", "Rs", "INR", "rs.", "rs"):
        if trimmed.endswith(p) and (len(trimmed) == len(p) or not trimmed[-len(p) - 1].isalnum()):
            return len(trimmed) - len(p)
    return None


def _c12_bracket_end(answer: str, at: int) -> int:
    """End of a size bracket right after `at` — " (₹37.49 crore)", " (≈ ₹25.70 lakh)" —
    that a rewritten figure now carries itself, else `at` (data-accuracy brief RC6)."""
    j = at
    while j < len(answer) and answer[j] == " ":
        j += 1
    if j >= len(answer) or answer[j] != "(":
        return at
    k = answer.find(")", j)
    inner = answer[j + 1:k].strip() if 0 < k - j <= 40 else ""
    if inner.startswith(("≈", "₹", "~", "Rs")) and any(w in inner.lower() for w in ("crore", "lakh", "cr")):
        return k + 1
    return at


def _c12_normalise_figures(answer: str, rows: list[dict], schemes: "list[str] | None" = None) -> str:
    """Money and big counts in the answer written the way the dashboard cards write them.
    Money is every result cell _c17_money_cols knows (by suffix, else by name with the
    dataset's own unit — data-accuracy brief 2026-10-29: "amount_disbursed" was not
    money, so D9 read "51,01,05,000.00"). A figure the answer wrote in crore / lakh
    ("₹46.64 crore", "25,701.49 lakh") is put back to the exact cell it rounds from."""
    if not answer:
        return answer
    money = _c17_money_cols(rows, schemes)
    scale = {"crore": 1e7, "crores": 1e7, "cr": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5}
    out, last = [], 0
    for start, end, tok in _c12_number_spans(answer, decimals=True, commas=True):
        if start < last:
            continue                 # inside a bracket a rewritten figure already took
        try:
            val = float(tok.replace(",", ""))
        except ValueError:
            continue
        after = answer[end:].lstrip()
        if after.startswith("%"):
            continue
        nxt = _c12_tokens(after[:12])
        col = next((m for m in money if abs(m[0] - val) < 0.005 and val != 0), None)
        rupee_at = _c12_rupee_prefix_start(answer, start)
        new = None
        stop = end
        if nxt and nxt[0].start == 0 and nxt[0].low in _C12_UNIT_WORDS:
            word_end = end + (len(answer[end:]) - len(after)) + nxt[0].end
            f = scale.get(nxt[0].low, 1e7)
            if col is not None and col[1] == "rupees":
                # "480.91 lakh" for a _rupees column (avg_wage_per_person_day_rupees, the
                # composer read MGNREGA's "money is lakh" rule): the unit word is wrong, not the
                # number — written as rupees.
                new = _c12_money(*col)
            else:
                # "₹46.64 crore" of a rupees cell 466430000 -> the exact amount and its size;
                # "25,701.49 lakh" of a lakh cell -> "₹25,701.49 lakh (≈ ₹257.01 crore)".
                exact = min((m for m in money if m[1] == "rupees" and val
                             and abs(m[0] / f - val) < 0.006), key=lambda m: abs(m[0] / f - val), default=None)
                same = next((m for m in money if m[1] == ("lakh" if f == 1e5 else "crore")
                             and abs(m[0] - val) < 0.005 and val), None)
                if exact is not None:
                    new = _c12_money(exact[0], "rupees")
                elif same is not None:
                    new = _c12_money(*same)
                else:
                    continue         # not a result's money (person-days in crore …): its words stand
            stop = _c12_bracket_end(answer, word_end)
            begin = rupee_at if rupee_at is not None and rupee_at >= last else start
            out.append(answer[last:begin]); out.append(new); last = stop
            continue
        if col is not None:
            new = _c12_money(*col)
            # "480.91 rupees" -> "₹480.91": the word goes with the ₹
            if nxt and nxt[0].start == 0 and nxt[0].low in ("rupee", "rupees", "rs", "inr"):
                stop = end + (len(answer[end:]) - len(after)) + nxt[0].end
        elif rupee_at is not None and val >= 1e5:
            new = _c12_money(val, "rupees")
        if new is not None:
            stop = _c12_bracket_end(answer, stop)
            begin = rupee_at if rupee_at is not None and rupee_at >= last else start
            out.append(answer[last:begin]); out.append(new); last = stop
        elif "," in tok and val >= 1e5:
            whole, _, frac = tok.partition(".")
            out.append(answer[last:start]); out.append(_c12_indian(float(whole.replace(",", ""))) +
                                                        ("." + frac if frac else "")); last = end
    out.append(answer[last:])
    text = "".join(out)
    # "₹1,356.45 crore (₹13,56,45,00,000)" was the same amount twice; once both are
    # written alike, the bracketed copy goes.
    for m in {s for s in out if s.startswith(("₹", "-₹"))}:
        text = text.replace(f"{m} ({m})", m)
        # with the exact-plus-size form "₹13,56,45,32,500 (≈ ₹1,356.45 crore)", the composer's
        # own "₹1,356.45 crore (<exact>)" became "₹1,356.45 crore (₹13,56,45,32,500 (≈ ₹1,356.45
        # crore))": the size it already said goes, the formatted figure stays once
        if " (≈ " in m and m.endswith(")"):
            size = m[m.index(" (≈ ") + 4:-1]
            text = text.replace(f"{size} ({m})", m).replace(f"{m} ({size})", m)
    return text


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


def _c12_period_phrase(period: str) -> str:
    """"for FY 2023-24", but "across all financial years" as it is."""
    return period if period.startswith(("across", "over", "in ", "during")) else "for " + period


def _finish_answer(answer: str, rows: list[dict], schemes: "list[str] | None", entities: "dict | None") -> str:
    """The universal last pass over a data answer: result figures carry thousands
    separators, and a single-figure answer that does not name the scheme or the
    area gets one closing scope sentence, so the officer always reads what the
    figure is for. Idempotent: a framed answer is left as it is."""
    if not answer:
        return answer
    text = _group_result_digits(answer, rows, schemes)
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
        # "This is the PMAY-G figure for across all financial years." (D5 / D7 run 2026-10-29)
        tail = f"This is the {scheme} figure{(' ' + _c12_period_phrase(period)) if when else ''}."
    else:
        tail = f"This is the {'statewide ' if statewide else ''}figure for {place_text}{when}."
    return f"{text.rstrip()} {tail}"


_C12_CODE_ONLY_PLACES = ("village_code", "village_code_list", "block_list", "district_list",
                         "assembly_constituency_list")


def _display_from_resolved(resolved: "dict | None") -> dict:
    """The display-style entities (_scope_words reads) from a result's resolved
    entities: Title Case places and "FY 2023-24" for year_key."""
    r = resolved or {}
    out = {}
    for k in ("district", "block", "village", "assembly_constituency"):
        if r.get(k):
            out[k] = str(r[k]).title()
    if not out.get("village") and r.get("village_code"):
        # A village known by its code is named, or the district beside it was
        # taken for the scope: "200 household-years … in Pamila village. This is
        # the figure for West Garo Hills district" (live 2026-10-21).
        from app.entity_resolver import village_code_name
        _vn = village_code_name(r["village_code"])
        if _vn:
            out["village"] = _vn
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
        resolved = result.get("resolved_entities") or {}
        display = _display_from_resolved(resolved)
        # A finer place known only by its code is not the district beside it
        # either ("in Pamila village … the figure for West Garo Hills district").
        if not display.get("village") and any(resolved.get(k) for k in _C12_CODE_ONLY_PLACES):
            # The place is known here only by its code (village_code 279198): it is not
            # statewide. "967 job cards … in Barato village as of FY 2023-24. This is the
            # statewide figure for all of Meghalaya." (job-card year fix, live 2026-10-21;
            # MGNREGA sheet DATA-022/023/028 village answers, 2026-10-21.)
            result["answer"] = _group_result_digits(result.get("answer") or "", rows, result.get("schemes"))
            _c17_attach_caveats(result)
            return
        result["answer"] = _finish_answer(result.get("answer") or "", rows, result.get("schemes") or [],
                                          display)
        if (result.get("schemes") or []) == ["Focus Plus"]:          # RAG fix report Issue 12
            result["answer"] = _focusplus_per_beneficiary_caveat(result["answer"], result.get("sql"))
        _c17_attach_caveats(result)      # provisional money, absent years (data-accuracy brief RC5)
        _c17_mark_winner(result)         # the row a "which … most" answered, for follow-ups
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
    ("wgh" -> "West Garo Hills", "fy24" -> "FY 2023-24")."""
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


# ── Each figure next to its own label (E9, 2026-10-29) ──────────────────────
# _answer_numbers_faithful asks only whether a figure EXISTS somewhere in the result.
# Composer audit 2026-10-27: "Bank disbursed 11.10 crore more loans than LIFCOM" (CL-05:
# 11.10 is Bank's own figure, the gap is 1.31), "1. MAWHATI — 82.91 lakh" for a
# percentage (MG-10), and a figure written beside another row's name all passed it.
# _c12_label_misbinds reads which row name, which measure and which unit each figure
# sits next to, and names the figures that belong somewhere else. It is deliberately
# narrow: a figure it cannot tie to one row or one measure is left to the number check.
from app.text_match import fy_spans as _c12_fy_spans, tokens as _c12_tokens  # noqa: E402

_C12_LB_COMPARATIVE = frozenset({"more", "less", "fewer", "higher", "lower", "ahead", "behind", "greater",
                                 "bigger", "smaller"})
# "6,120.50 in FY 2020-21", "412,300 for Mylliem": the place / period named right after
_C12_LB_POST_BIND = frozenset({"for", "in", "at", "of", "during", "from"})
_C12_LB_UNIT_WORDS = frozenset({"lakh", "lakhs", "lac", "crore", "crores", "cr", "rs", "inr", "rupees",
                                "percentage", "percent", "points", "point"})
_C12_LB_STOP = frozenset({"total", "of", "the", "and", "in", "to", "for", "a", "an", "by", "no", "count", "number",
                          "sum", "all", "name", "value", "lakh", "crore", "cr", "rupees", "pct", "percent",
                          "percentage", "rs", "inr"})
# a breath between a row's name and its figure: "Mylliem — 412,300", "Bank 11.10", "FY 2022-23: 8,215"
_C12_LB_TIGHT_GAP = frozenset(" \t—–-:(*₹")


def _c12_lb_canon(raw: str) -> str:
    """A written number as one comparable string: '412,300' -> '412300', '14.90' -> '14.9'."""
    s = raw.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _c12_lb_forms(f: float, money_unit: "str | None") -> set:
    """The strings a correct answer may write for one result value: as stored, at 2 and 1
    decimals, whole (from 100 up), and for money the same amount in crore / lakh / rupees."""
    out = {_c12_lb_canon(f"{f:.2f}"), _c12_lb_canon(f"{f:.1f}")}
    if f.is_integer():
        out.add(str(int(f)))
    if abs(f) >= 100:
        out.add(str(round(f)))
    if money_unit:
        rupees = f * _C12_MONEY_SCALE[money_unit]
        out |= {_c12_lb_canon(f"{rupees / 1e7:.2f}"), _c12_lb_canon(f"{rupees / 1e5:.2f}"), str(round(rupees))}
    return out


def _c12_lb_stem(w: str) -> str:
    w = w.lower()
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def _c12_lb_measure_words(col: str) -> set:
    """Content words of a measure: its column name parts and its plain-words name."""
    ws = set(str(col).lower().split("_")) | {t.low for t in _c12_tokens(_human_metric(str(col)))}
    return {_c12_lb_stem(w) for w in ws if w and w not in _C12_LB_STOP and not w.isdecimal()}


def _c12_lb_clause(text: str, s: int, e: int) -> "tuple[int, int]":
    """The clause around text[s:e]: bounded by a line break, ';', or a sentence end
    ('.', '!' or '?' followed by a space)."""
    a = s
    while a > 0 and text[a - 1] not in "\n;" and not (text[a - 1] == " " and a >= 2 and text[a - 2] in ".!?"):
        a -= 1
    b = e
    while b < len(text) and text[b] not in "\n;" and not (
            text[b] in ".!?" and (b + 1 == len(text) or text[b + 1] == " ")):
        b += 1
    return a, b


def _c12_lb_words_after(text: str, toks: list, e: int, stop: int, limit: int = 4) -> list:
    """Up to `limit` word tokens right after position e, while only spaces or hyphens
    separate them (a comma, bracket or full stop ends the run); stops at a number."""
    out, prev = [], e
    for t in toks:
        if t.start < e:
            continue
        if t.start >= stop or len(out) >= limit or any(ch not in " \t-" for ch in text[prev:t.start]) \
                or t.raw[:1].isdecimal():
            break
        out.append(t.low)
        prev = t.end
    return out


def _c12_label_misbinds(answer: str, rows: list, derived: "set | None" = None) -> list:
    """Figures the answer writes next to the wrong row name, measure or unit, as short
    descriptions for the retry prompt ([] when every figure it can place is in its place).

    - comparative: "11.10 crore MORE than" — a figure followed by more / less / higher /
      ahead … must be a difference between two result values, not a row's own figure;
    - unit: a percentage value written as ₹ / lakh / crore, or a money value written as %;
    - row: a figure tied to one row's name ("Mylliem — 398,150", "8,215 in FY 2022-23",
      or the only row name in its clause) must be one of that row's values;
    - measure: a figure followed (or preceded, "Person-days: …") by the words of another
      measure in the result and none of its own ("41,210 person-days" for households).
    `derived`: figures computed by code (totals, gaps, shares) — never a row's own."""
    if not answer or not rows or not isinstance(rows[0], dict):
        return []
    rows = rows[:200]
    cells: dict = {}                     # written form -> [(row index, column)]
    col_vals: dict = {}
    for i, r in enumerate(rows):
        for k, v in r.items():
            n = _as_number(v)
            if n is None or _NONSTAT_COL.search(str(k)):
                continue
            col_vals.setdefault(k, []).append(float(n))
            for form in _c12_lb_forms(float(n), _c12_money_unit(str(k))):
                cells.setdefault(form, []).append((i, k))
    if not cells:
        return []
    derived_only = {_c12_lb_canon(str(d)) for d in (derived or ())} - set(cells)
    diffs: set = set()
    for k, vals in col_vals.items():
        mu = _c12_money_unit(str(k))
        vals = vals[:60]
        for x in range(len(vals)):
            for y in range(x + 1, len(vals)):
                diffs |= _c12_lb_forms(abs(vals[x] - vals[y]), mu)
    # row names that belong to exactly one row
    owners: dict = {}
    for i, r in enumerate(rows):
        for k, v in r.items():
            if v is None or (_as_number(v) is not None and not _NONSTAT_COL.search(str(k))):
                continue
            lab = str(v).strip()
            if (len(lab) >= 2 and not lab.isdecimal()) or (lab.isdecimal() and len(lab) == 4):
                owners.setdefault(lab.lower(), set()).add(i)
    low = answer.lower()
    taken: list = []                     # (start, end, row index) of each row name in the answer
    for lab in sorted((x for x, o in owners.items() if len(o) == 1), key=len, reverse=True):
        pos = low.find(lab)
        while pos >= 0:
            end = pos + len(lab)
            edge_ok = (pos == 0 or not low[pos - 1].isalnum()) and (end == len(low) or not low[end].isalnum())
            if edge_ok and not any(a < end and pos < b for a, b, _ in taken):
                taken.append((pos, end, next(iter(owners[lab]))))
            pos = low.find(lab, pos + 1)
    taken.sort()
    skip_spans = [(a, b) for a, b, _y0, _y1 in _c12_fy_spans(answer)] + [(a, b) for a, b, _ in taken]
    toks = _c12_tokens(answer)
    metric_cols = list(col_vals)
    words_of = {c: _c12_lb_measure_words(c) for c in metric_cols} if len(metric_cols) >= 2 else {}
    out: list = []

    def _label_of(i: int) -> str:
        own = [str(v) for k, v in rows[i].items() if v is not None and str(v).strip().lower() in owners]
        return next((answer[a:b] for a, b, ri in taken if ri == i), " / ".join(own) or f"row {i + 1}")

    for s, e, tok in _c12_number_spans(answer, decimals=True, commas=True):
        if any(a < e and s < b for a, b in skip_spans):
            continue
        canon = _c12_lb_canon(tok)
        if "," not in tok and "." not in tok and len(tok) == 4 and 1900 <= int(tok) <= 2199:
            continue                                      # a year
        line_head = answer[answer.rfind("\n", 0, s) + 1:s]
        if (s > 0 and answer[s - 1] == "#") or (not line_head.strip() and answer[e:e + 1] in (".", ")")):
            continue                                      # "#1", a numbered list's "1."
        hits = cells.get(canon)
        if not hits or canon in derived_only:
            continue
        ca, cb = _c12_lb_clause(answer, s, e)
        after = _c12_lb_words_after(answer, toks, e, cb)
        first_word = next((w for w in after if w not in _C12_LB_UNIT_WORDS), "")
        # 1. comparative: the figure states a difference
        if first_word in _C12_LB_COMPARATIVE:
            if canon not in diffs:
                out.append(f"{tok} is written as a difference ('{first_word}'), but it is a figure of "
                           f"{_label_of(hits[0][0])} itself, not the gap between two values")
            continue
        # 2. unit
        rest = answer[e:].lstrip(" ")
        head = answer[max(0, s - 4):s].rstrip(" ").lower()
        stated = ("pct" if rest.startswith("%") else
                  "money" if (after[:1] and after[0] in ("lakh", "lakhs", "lac", "crore", "crores", "cr"))
                  or head.endswith(("₹", "rs", "rs.", "inr")) else "")
        kinds = {"pct" if _c12_is_pct_col(str(k)) else "money" if _c12_money_unit(str(k)) else "count"
                 for _i, k in hits}
        if stated and kinds == {"pct" if stated == "money" else "money"}:
            out.append(f"{tok} is written as {'money' if stated == 'money' else 'a percentage'}, but it is "
                       f"{'a percentage' if stated == 'money' else 'a money amount'} in the result")
            continue
        # 3. row: the row name it is tied to
        hit_rows = {i for i, _k in hits}
        if len(rows) >= 2 and taken:
            in_clause = [(a, b, ri) for a, b, ri in taken if ca <= a and b <= cb]
            bound = None
            nxt = next(((a, b, ri) for a, b, ri in in_clause if a >= e), None)
            if nxt and after[:1] and after[0] in _C12_LB_POST_BIND:
                between = answer[e:nxt[0]].lower().split()
                if between and between[0] in _C12_LB_POST_BIND and all(w in ("fy", "the") for w in between[1:]):
                    bound = nxt[2]
            if bound is None:
                prv = next(((a, b, ri) for a, b, ri in reversed(in_clause) if b <= s), None)
                if prv and all(ch in _C12_LB_TIGHT_GAP for ch in answer[prv[1]:s]):
                    bound = prv[2]
            # the only row named in its clause; not for a small whole number ("top 5")
            if bound is None and len({ri for *_x, ri in in_clause}) == 1 and ("." in tok or abs(float(canon)) >= 100):
                bound = in_clause[0][2]
            if bound is not None and bound not in hit_rows:
                out.append(f"{tok} is written next to {_label_of(bound)}, but it is the figure for "
                           f"{_label_of(min(hit_rows))}")
                continue
        # 4. measure: the words it is labelled with
        hit_cols = {k for _i, k in hits}
        if words_of and len(hit_cols) == 1:
            own = next(iter(hit_cols))
            near = {_c12_lb_stem(w) for w in after if w not in _C12_LB_UNIT_WORDS}
            before = answer[ca:s].rstrip(" *₹").rstrip()
            if before.endswith((":", "—", "–")):
                lead = before.rstrip(":—– ").replace("*", " ")
                near |= {_c12_lb_stem(t.low) for t in _c12_tokens(lead)[-5:]}
            for other in metric_cols:
                if other == own:
                    continue
                theirs = words_of[other] - words_of[own]
                if near & theirs and not near & words_of[own]:
                    out.append(f"{tok} is labelled as {_human_metric(str(other))}, but it is the "
                               f"{_human_metric(str(own))} figure")
                    break
    return list(dict.fromkeys(out))[:6]

"""
Next-step suggestions shown under a completed answer ("Next steps" chips).

DETERMINISTIC, not model-generated. Every suggestion is assembled from a fixed,
scheme-aware bank keyed on:
  - the route that just answered (data vs knowledge),
  - which scheme(s) the answer covered,
  - what the question actually asked for (which metric words it used),
  - which entities resolved (district / block / village / year).

The generated SQL is also read (just its GROUP BY) so a suggestion respects the
grain the answer is already at: never "break that down by district" under a
table that is *already* per-district, and the sibling-metric suggestion keeps
the same "by district" cut instead of collapsing back to a state total.

Suggestions stay the same *kind* as the question that was just asked: a metric
(data) answer only ever offers more metric questions, and a general (knowledge)
answer only ever offers more general questions — no eligibility chip under a
number, no "how many houses" chip under a rules explainer.

So a suggestion is always a real question this service can answer against the
known curated schema or the reference KB — no model call, no latency, no
invented metric, and no "random" drift between turns. It returns a list of
{"label", "question"} (at most `_MAX`): `label` is what the user reads,
`question` is the exact text re-sent on click (the SQL / RAG layer parses it,
so it must stay literal, not softened).

Edge / denied / clarification turns get nothing here — those routes carry their
own next-step UI (starter chips on edge, the clarification options).
"""
from sqlglot import exp

from app import sql_ast
from app.text_match import Alt, Joined, Matcher, Node, NotAfter, NotBefore, Pred, Seq, W

_MAX = 3


class _FuPlusAfter(Node):
    """Zero-width after a word: the text right after it is (spaces and) '+'."""

    def ends(self, ctx, i, caps):
        if i == 0:
            return
        nxt = ctx.toks[i].start if i < len(ctx.toks) else len(ctx.text)
        if ctx.text[ctx.toks[i - 1].end:nxt].lstrip().startswith("+"):
            yield i, caps


_FU_CME = Joined("cm", "elevate")
_FU_LEGACY_TAIL = W("legacy", "disbursement", "disbursements")
_SCHEME_MATCH = {
    "MGNREGA": Matcher(W("mgnrega", "mnrega", "nrega")),
    "PMAY-G": Matcher(Alt(W("pmay", "pmayg"), Seq("pmay", "g"),
                          Pred(lambda w: w.lower().rstrip("s")[:2] == "aw"
                               and set(w.lower().rstrip("s")[2:]) == {"a"}
                               and len(w.lower()) - len(w.lower().rstrip("s")) <= 1))),
    "Focus Plus": Matcher(Alt(Joined("focus", "plus"), Seq(W("focus"), _FuPlusAfter()))),
    # Same lookarounds as pipeline._SCHEME_NAME_MATCHER: "CM Elevate Legacy" is
    # the other CM Elevate dataset, not this one.
    "CM Elevate": Matcher(NotAfter(NotBefore(_FU_CME, _FU_LEGACY_TAIL), "legacy")),
    "Focus Legacy": Matcher(Alt(Joined("focus", "legacy"), Joined("legacy", "focus"), Joined("old", "focus"),
                                Joined("focus", "pg"), Joined("pg", "focus"))),
    "CM Elevate Legacy": Matcher(Alt(
        Seq(_FU_CME, _FU_LEGACY_TAIL),
        W("cmelevatelegacy", "cmelevatedisbursement", "cmelevatedisbursements"),
        Seq("legacy", _FU_CME), Joined("elevate", "legacy"))),
    "CMSS": Matcher(W("cmss", "scholarship", "scholarships")),
}


def _norm(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c == " " or ("a" <= c <= "z") or ("0" <= c <= "9")).strip()


def _asked(question: str, *needles: str) -> bool:
    ql = _norm(question)
    return any(n in ql for n in needles)


def _primary_schemes(schemes: list[str], question: str) -> list[str]:
    """The scheme(s) to build follow-ups for: what the answer used, else what
    the question names, else both."""
    schemes = [s for s in (schemes or []) if s in _SCHEME_MATCH]
    if schemes:
        return schemes
    named = [s for s, word_matcher in _SCHEME_MATCH.items() if word_matcher.search(question or "")]
    return named or ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy",
                     "CM Elevate Legacy",
                     "CMSS"]


# ── answer grain (read off the generated SQL's GROUP BY) ────────────────────
_LEVEL_RANK = {"state": 0, "district": 1, "block": 2, "village": 3}

# Column-name cues (a column name is one word: "district_name", "lgd_block").
_DISTRICT_COL_MATCH = Matcher(Pred(lambda w: any(s in w.lower() for s in ("district", "distname", "dist_name"))))
_BLOCK_COL_MATCH = Matcher(Alt(W("block"), Pred(lambda w: any(s in w.lower() for s in
                                                           ("blockname", "block_name", "lgd_block")))))
_VILLAGE_COL_MATCH = Matcher(Pred(lambda w: any(s in w.lower() for s in ("village", "panchayat"))))


def _group_by_names(sql: str) -> "list[str]":
    """Lower-cased names in the query's GROUP BY, read from the parsed tree:
    the outer query's GROUP BY, else the first one anywhere (a CTE's). A
    position (GROUP BY 1) is the output column at that position: its column
    names and alias. [] when nothing is grouped or the text does not parse."""
    for tree in sql_ast.parse(sql):
        sel = sql_ast.outer_select(tree)
        group = sel.args.get("group") if sel is not None else None
        if group is None:
            group = next(iter(tree.find_all(exp.Group)), None)
        if group is None:
            continue
        owner = group.parent if isinstance(group.parent, exp.Select) else sel
        names: list[str] = []
        for term in group.expressions:
            if isinstance(term, exp.Literal) and not term.is_string and owner is not None:
                try:
                    term = owner.expressions[int(term.this) - 1]
                except (ValueError, IndexError):
                    continue
                if term.alias:
                    names.append(term.alias.lower())
            names += [(c.name or "").lower() for c in term.find_all(exp.Column)]
        return names
    return []


def _grain_of_name(name: str) -> str | None:
    """'village' / 'block' / 'district' for a grouped column name, else None."""
    if "village" in name or "panchayat" in name:
        return "village"
    if name == "block" or "block_name" in name or "blockname" in name or "lgd_block" in name:
        return "block"
    if "district" in name or "dist_name" in name or "distname" in name:
        return "district"
    return None


def _answer_grain(sql: str | None) -> str | None:
    """The finest geography level the answer is grouped to, read off the SQL's
    GROUP BY on the parsed tree (this is the same signal the UI shows as its
    'GROUP BY lgd_district' source chip). None when the query returns a single
    aggregate row."""
    if not sql:
        return None
    grains = {_grain_of_name(n) for n in _group_by_names(sql)}
    for level in ("village", "block", "district"):
        if level in grains:
            return level
    return None


def _filter_level(ents: dict) -> str:
    """The finest geography the question is *filtered* to (one named area)."""
    if ents.get("village_code") or ents.get("village") or ents.get("village_twins"):
        return "village"
    if ents.get("block"):
        return "block"
    if ents.get("district"):
        return "district"
    return "state"


def _view_level(ents: dict, grain: str | None) -> str:
    """What the user is actually looking at: the finer of the area they filtered
    to and the grain the answer is grouped by."""
    flt = _filter_level(ents)
    if grain and _LEVEL_RANK.get(grain, 0) > _LEVEL_RANK[flt]:
        return grain
    return flt


def _grain_suffix(ents: dict, grain: str | None) -> str:
    """', by district' / ', by block' — only when the answer is grouped finer
    than any area filter, so a sibling-metric suggestion keeps the same cut."""
    flt = _filter_level(ents)
    if grain and _LEVEL_RANK.get(grain, 0) > _LEVEL_RANK[flt]:
        return f", by {grain}"
    return ""


def _top_area_from_rows(rows: list | None, col_word_matcher: Matcher) -> str | None:
    """Name of the row with the largest metric value, keyed by the first column
    whose name matches `col_word_matcher`. None if the row shape isn't obvious — this only
    feeds a suggestion, so a wrong guess is a slightly-off drill target, not a
    bad answer."""
    if not rows or not isinstance(rows[0], dict):
        return None
    keys = list(rows[0].keys())
    name_key = next((k for k in keys if col_word_matcher.search(k)), None)
    if not name_key:
        return None
    num_key = next(
        (k for k in keys
         if k != name_key
         and isinstance(rows[0].get(k), (int, float))
         and not isinstance(rows[0].get(k), bool)),
        None,
    )
    if not num_key:
        return None
    best: tuple[str, float] | None = None
    for r in rows:
        v, n = r.get(num_key), r.get(name_key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or n in (None, ""):
            continue
        if best is None or v > best[1]:
            best = (str(n), float(v))
    return best[0] if best else None


def _scope_phrase(ents: dict) -> str:
    """A human-readable geography/time scope drawn from the resolved entities,
    e.g. ' in Ri Bhoi' or ' in Mawkyrwat block, South West Khasi Hills'. Falls
    back to ' in Meghalaya' so every suggestion is a complete question."""
    d = ents.get("district")
    b = ents.get("block")
    if b and d:
        return f" in {str(b).title()} block, {str(d).title()}"
    if b:
        return f" in {str(b).title()} block"
    if d:
        return f" in {str(d).title()}"
    # A constituency answer's chips said "… in Meghalaya" and offered "Break that down by
    # district." — the state, not the constituency asked (PMAY-G sheet re-test 2026-10-30).
    # villages sharing one name (D-089 J-10): the name brings the same villages back
    twins = ents.get("village_twins")
    if isinstance(twins, dict) and twins:
        return f" in {str(next(iter(twins.values()))).split(' (')[0]}"
    ac = ents.get("assembly_constituency")
    if ac:
        return f" in {str(ac).title()} constituency"
    return " in Meghalaya"


def _drill_down(ents: dict, grain: str | None = None,
                rows: list | None = None) -> dict | None:
    """One suggestion that breaks the same answer down a level finer than what
    the user is currently looking at. None once we are at village grain.

    Grain-aware: if the answer is *already* grouped per-district (but not
    filtered to one district), we don't re-ask for a per-district breakdown —
    we offer to open the largest district a level deeper instead."""
    view = _view_level(ents, grain)
    if view == "village":
        return None
    if view == "state" and ents.get("assembly_constituency"):
        return None        # a constituency is not the state: no "by district" of Meghalaya

    # A named area is in play — drill straight inside it.
    if view == "block" and ents.get("block"):
        q = f"Break that down by village within {str(ents['block']).title()} block."
        return {"label": q, "question": q}
    if view == "district" and ents.get("district"):
        q = f"Break that down by block within {str(ents['district']).title()}."
        return {"label": q, "question": q}

    # Grouped/aggregated but not filtered to one area.
    if view == "state":
        q = "Break that down by district."
        return {"label": q, "question": q}
    if view == "district":
        top = _top_area_from_rows(rows, _DISTRICT_COL_MATCH)
        if top:
            q = f"Break that down by block within {top.title()}."
            return {"label": q, "question": q}
        return None
    if view == "block":
        top = _top_area_from_rows(rows, _BLOCK_COL_MATCH)
        if top:
            q = f"Break that down by village within {top.title()} block."
            return {"label": q, "question": q}
        return None
    return None


# ── DATA route ──────────────────────────────────────────────────────────────
def _fill_metric(out: list[str], question: str, candidates: list[str]) -> None:
    """Top `out` up to `_MAX` using metric questions from `candidates`, in order,
    skipping any that restate the question or already appear. Used in place of
    the old rules/eligibility tail so a data answer's next steps stay entirely
    metric-driven."""
    have = {_norm(x) for x in out}
    asked = _norm(question)
    for c in candidates:
        if len(out) >= _MAX:
            break
        k = _norm(c)
        if not k or k == asked or k in have:
            continue
        have.add(k)
        out.append(c)


def _pmay_data(question: str, ents: dict, grain: str | None = None,
               rows: list | None = None) -> list[dict]:
    scope = _scope_phrase(ents)
    gsuf = _grain_suffix(ents, grain)
    out: list[dict] = []

    # 1. The complementary PMAY-G metric to the one just asked, kept at the same
    #    grain as the answer (', by district') so it reads as a step forward.
    if _asked(question, "sanction") and not _asked(question, "complet"):
        out.append(f"How many PMAY-G houses have been completed{scope}{gsuf}?")
    elif _asked(question, "complet") and not _asked(question, "sanction"):
        out.append(f"How many PMAY-G houses have been sanctioned{scope}{gsuf}?")
    elif _asked(question, "release", "utilis", "utiliz", "amount", "fund", "money"):
        out.append(f"What is the PMAY-G fund utilisation rate{scope}{gsuf}?")
    elif _asked(question, "completion rate", "in progress", "in-progress"):
        out.append(f"How much PMAY-G money has been released against the sanctioned amount{scope}{gsuf}?")
    else:
        out.append(f"What is the PMAY-G completion rate{scope}{gsuf}?")

    # 2. Drill one level finer than what the user is looking at.
    d = _drill_down(ents, grain, rows)
    if d:
        out.append(d["question"])

    # 3. Another PMAY-G metric — keep the whole set metric-driven, no rules chip.
    _fill_metric(out, question, [
        f"How many PMAY-G houses have been completed{scope}{gsuf}?",
        f"How many PMAY-G houses have been sanctioned{scope}{gsuf}?",
        f"What is the PMAY-G completion rate{scope}{gsuf}?",
        f"How much PMAY-G money has been released against the sanctioned amount{scope}{gsuf}?",
    ])
    return [{"label": q, "question": q} for q in out]


def _mgnrega_data(question: str, ents: dict, grain: str | None = None,
                  rows: list | None = None) -> list[dict]:
    scope = _scope_phrase(ents)
    gsuf = _grain_suffix(ents, grain)
    out: list[str] = []

    # 1. The complementary metric, kept at the answer's grain (', by district').
    if _asked(question, "person day", "persondays", "person-day", "man day", "work day", "muster"):
        out.append(f"What was the total MGNREGA wage expenditure{scope}{gsuf}?")
    elif _asked(question, "expenditure", "spend", "spent", "wage", "material", "cost"):
        out.append(f"How many MGNREGA person-days were generated{scope}{gsuf}?")
    elif _asked(question, "job card"):
        out.append(f"How many households completed 100 days of MGNREGA work{scope}{gsuf}?")
    elif _asked(question, "100 day", "hundred day"):
        out.append(f"How many MGNREGA person-days were generated{scope}{gsuf}?")
    else:
        out.append(f"What was the total MGNREGA expenditure{scope}{gsuf}?")

    if not _asked(question, "trend", "over time", "over the", "year on year", "compare", "change"):
        out.append(f"How have MGNREGA person-days changed over the last three years{scope}?")

    d = _drill_down(ents, grain, rows)
    if d:
        out.append(d["question"])

    # Keep the whole set metric-driven — no eligibility chip under a number.
    _fill_metric(out, question, [
        f"What was the total MGNREGA wage expenditure{scope}{gsuf}?",
        f"How many MGNREGA person-days were generated{scope}{gsuf}?",
        f"How many households completed 100 days of MGNREGA work{scope}{gsuf}?",
        f"How many active MGNREGA job cards are there{scope}{gsuf}?",
    ])
    return [{"label": q, "question": q} for q in out]


def _focusplus_data(question: str, ents: dict, grain: str | None = None,
                    rows: list | None = None) -> list[dict]:
    scope = _scope_phrase(ents)
    gsuf = _grain_suffix(ents, grain)
    out: list[str] = []

    # 1. The complementary Focus Plus metric to the one just asked.
    if _asked(question, "amount", "disburs", "money", "paid", "spend", "spent"):
        out.append(f"How many Focus Plus payments were made{scope}{gsuf}?")
    elif _asked(question, "batch", "cohort", "93k", "12.5k", "legacy", "registration"):
        out.append(f"How much has been disbursed under Focus Plus{scope}{gsuf}?")
    elif _asked(question, "gender", "women", "female", "occupation", "farmer"):
        out.append(f"How many Focus Plus registrations are still pending{scope}?")
    else:
        out.append(f"How many Focus Plus payments were made in each batch{scope}?")

    # 2. Drill one level finer than what the user is looking at.
    d = _drill_down(ents, grain, rows)
    if d:
        out.append(d["question"])

    # 3. Another Focus Plus metric — keep the whole set metric-driven.
    _fill_metric(out, question, [
        f"How much has been disbursed under Focus Plus{scope}{gsuf}?",
        f"How many Focus Plus payments were made in each batch{scope}?",
        f"How many distinct villages have Focus Plus payments{scope}?",
        f"Show Focus Plus payments by tranche{scope}.",
    ])
    return [{"label": q, "question": q} for q in out]


def _cmelevate_data(question: str, ents: dict, grain: str | None = None,
                    rows: list | None = None) -> list[dict]:
    scope = _scope_phrase(ents)
    gsuf = _grain_suffix(ents, grain)
    out: list[str] = []

    # 1. The complementary CM Elevate metric to the one just asked.
    if _asked(question, "on hold", "verified", "verification", "valid", "invalid", "wrong"):
        out.append(f"Show CM Elevate applications by scheme{scope}?")
    elif _asked(question, "scheme", "piggery", "poultry", "warehouse"):
        out.append(f"How many CM Elevate applications are on hold{scope}?")
    elif _asked(question, "gender", "women", "female", "male"):
        out.append(f"What is the applicant type mix for CM Elevate{scope}?")
    else:
        out.append(f"How many CM Elevate applications are there, by scheme{scope}?")

    # 2. Drill one level finer than what the user is looking at.
    d = _drill_down(ents, grain, rows)
    if d:
        out.append(d["question"])

    # 3. Another CM Elevate metric — keep the whole set metric-driven. No money
    # or time chip here on purpose — CM Elevate has neither in this data.
    _fill_metric(out, question, [
        f"Show the verification status breakdown for CM Elevate{scope}{gsuf}?",
        f"What is the gender split of CM Elevate applicants{scope}?",
        f"How many distinct villages have CM Elevate applications{scope}?",
        f"List CM Elevate schemes by application count{scope}.",
    ])
    return [{"label": q, "question": q} for q in out]


def _focuslegacy_data(question: str, ents: dict, grain: str | None = None,
                      rows: list | None = None) -> list[dict]:
    scope = _scope_phrase(ents)
    gsuf = _grain_suffix(ents, grain)
    out: list[str] = []

    # 1. The complementary Focus Legacy metric to the one just asked. Amount and
    # membership are the SAME measure here (amount = members x 5000), so asking
    # one never offers the other as if it were a second finding — it offers the
    # group/product/bank angle instead.
    # Subject first, measure second. "How many producer groups were paid?" names
    # BOTH a subject (groups) and a money-ish verb (paid), and the subject is the
    # more specific signal — testing the money verbs first offered the user back
    # the very count they had just asked for.
    if _asked(question, "producer group", "how many group", "pg id", "pgs"):
        out.append(f"How many PG members were covered{scope}{gsuf}?")
    elif _asked(question, "member", "membership"):
        out.append(f"How much was disbursed to producer groups{scope}{gsuf}?")
    elif _asked(question, "amount", "disburs", "remit", "money", "fund"):
        out.append(f"How many producer groups were paid{scope}{gsuf}?")
    elif _asked(question, "product", "piggery", "ginger", "crop"):
        out.append(f"How many producer groups were paid{scope}{gsuf}?")
    else:
        out.append(f"How much was disbursed to producer groups{scope}{gsuf}?")

    # 2. Drill one level finer than what the user is looking at.
    d = _drill_down(ents, grain, rows)
    if d:
        out.append(d["question"])

    # 3. Another Focus Legacy metric. The group-count candidate is dropped when
    # the question already asked it — _fill_metric compares against the UNSCOPED
    # question, so "How many producer groups were paid?" would otherwise come
    # back as "How many producer groups were paid in Meghalaya?".
    fills = [
        f"Show Focus Legacy payments by financial year{scope}.",
        f"Which products do Focus Legacy groups work on{scope}?",
        f"Which banks handle Focus Legacy payments{scope}?",
        f"How many distinct villages have Focus Legacy payments{scope}?",
    ]
    if not _asked(question, "producer group", "how many group", "pgs"):
        fills.insert(0, f"How many producer groups were paid{scope}{gsuf}?")
    _fill_metric(out, question, fills)
    return [{"label": q, "question": q} for q in out]


def _cmelevatelegacy_data(question: str, ents: dict, grain: str | None = None,
                          rows: list | None = None) -> list[dict]:
    scope = _scope_phrase(ents)
    gsuf = _grain_suffix(ents, grain)
    out: list[str] = []

    # 1. The complementary CM Elevate Legacy figure. Money questions are offered
    # the record count or the lender split; counts are offered the money; a
    # lender / refusal / year question is offered the scheme-wise money.
    if _asked(question, "loan", "lender", "lifcom"):
        out.append(f"How much subsidy was disbursed under CM Elevate Legacy{scope}{gsuf}?")
    elif _asked(question, "refus", "desanction", "duplicate"):
        out.append(f"Did any desanctioned CM Elevate Legacy records still receive money{scope}?")
    elif _asked(question, "disburs", "amount", "money", "subsidy", "sanction", "paid"):
        out.append(f"How much of the CM Elevate Legacy loan money went through Bank vs LIFCOM{scope}?")
    elif _asked(question, "financial year", "fy", "2024", "2025"):
        out.append(f"What is the CM Elevate Legacy disbursement by scheme{scope}?")
    else:
        out.append(f"What is the total amount disbursed under CM Elevate Legacy{scope}{gsuf}?")

    # 2. Drill one level finer than what the user is looking at.
    d = _drill_down(ents, grain, rows)
    if d:
        out.append(d["question"])

    # 3. Another CM Elevate Legacy figure — keep the whole set metric-driven.
    _fill_metric(out, question, [
        f"How many CM Elevate Legacy records are there, by scheme{scope}?",
        f"What share of the sanctioned amount has been disbursed under CM Elevate Legacy{scope}{gsuf}?",
        f"Show CM Elevate Legacy disbursement by financial year{scope}.",
        f"How many distinct villages have CM Elevate Legacy records{scope}?",
    ])
    return [{"label": q, "question": q} for q in out]


def _cmss_data(question: str, ents: dict, grain: str | None = None,
               rows: list | None = None) -> list[dict]:
    scope = _scope_phrase(ents)
    gsuf = _grain_suffix(ents, grain)
    out: list[str] = []

    # 1. The complementary CMSS figure to the one just asked. No "average per student": every paid
    #    student gets a flat Rs 6,000 (data/cmss/cmss_schema_partitions.yaml, flat_rate_rule).
    if _asked(question, "amount", "disburs", "money", "paid", "spend", "spent", "rupee"):
        out.append(f"How many CMSS applications were received{scope}{gsuf}?")
    elif _asked(question, "application", "applicant", "apply", "submitted", "student"):
        out.append(f"How many CMSS students were paid{scope}{gsuf}?")
    elif _asked(question, "not paid", "unpaid"):
        out.append(f"What is the total CMSS amount disbursed{scope}{gsuf}?")
    else:
        out.append(f"How many CMSS students were paid{scope}{gsuf}?")

    # 2. Drill one level finer than what the user is looking at.
    d = _drill_down(ents, grain, rows)
    if d:
        out.append(d["question"])

    # 3. Another CMSS figure — keep the whole set metric-driven.
    _fill_metric(out, question, [
        f"How many CMSS students were paid{scope}{gsuf}?",
        f"How many CMSS applications were received{scope}{gsuf}?",
        f"What is the total CMSS amount disbursed{scope}{gsuf}?",
        f"How many CMSS applications were not paid{scope}{gsuf}?",
        f"CMSS students paid by assembly constituency{scope}",
    ])
    return [{"label": q, "question": q} for q in out]


def _cross_scheme_data(question: str, ents: dict, grain: str | None = None,
                       rows: list | None = None, schemes: list[str] | None = None) -> list[dict]:
    scope = _scope_phrase(ents)
    gsuf = _grain_suffix(ents, grain)
    has_fp = "Focus Plus" in (schemes or [])
    has_cme = "CM Elevate" in (schemes or [])
    has_fl = "Focus Legacy" in (schemes or [])
    has_cmel = "CM Elevate Legacy" in (schemes or [])
    # The cross-scheme VIEWS (spend, village coverage) cover MGNREGA and PMAY-G only —
    # Focus Plus and CM Elevate are each compared per-scheme, so their cross-scheme
    # chips are single-scheme questions, not a shared cross-scheme view lookup.
    out: list[str] = []
    # Only offer the spend comparison if that's not what was just asked.
    if not _asked(question, "spend", "spent", "expenditure", "money", "cost", "compare"):
        out.append(f"Compare MGNREGA and PMAY-G spending{scope}{gsuf}.")
    out.append(f"Which villages have both MGNREGA and PMAY-G activity{scope}?")
    if has_fp and not _asked(question, "focus plus", "disburs", "focus+"):
        out.append(f"How much has been disbursed under Focus Plus{scope}{gsuf}?")
    if has_cme and not _asked(question, "cm elevate", "cmelevate"):
        out.append(f"How many CM Elevate applications are there{scope}{gsuf}?")
    if has_fl and not _asked(question, "focus legacy", "producer group"):
        out.append(f"How much was disbursed to producer groups{scope}{gsuf}?")
    if has_cmel and not _asked(question, "cm elevate legacy", "cmelevate legacy"):
        out.append(f"What is the total amount disbursed under CM Elevate Legacy{scope}{gsuf}?")
    d = _drill_down(ents, grain, rows)
    if d:
        out.append(d["question"])
    # Keep the whole set metric-driven — no eligibility chip under a number.
    fills = [
        f"Compare MGNREGA and PMAY-G spending{scope}{gsuf}.",
        f"Which villages have both MGNREGA and PMAY-G activity{scope}?",
        f"How many households have benefited from MGNREGA and PMAY-G combined{scope}?",
    ]
    if has_fp:
        fills.insert(1, f"How many Focus Plus payments were made{scope}{gsuf}?")
    if has_cme:
        fills.insert(1, f"How many CM Elevate applications are there{scope}{gsuf}?")
    if has_fl:
        fills.insert(1, f"How many producer groups were paid{scope}{gsuf}?")
    _fill_metric(out, question, fills)
    return [{"label": q, "question": q} for q in out]


# ── KNOWLEDGE route ─────────────────────────────────────────────────────────
# Ordered ladder per scheme. Each entry: (distinctive words that mean "already
# asked, skip it", the question text). The ladder holds only general questions; one
# data chip is added after them (_KNOWLEDGE_DATA_NEXT, KR9 2026-10-29).
_KNOWLEDGE_LADDER = {
    "Focus Plus": [
        (("what is", "about focus", "overview"), "What is FOCUS+ (Focus Plus)?"),
        (("eligib", "who can", "who qualifies"), "Who is eligible for FOCUS+?"),
        (("batch", "cohort", "93k", "12.5k"), "What are the FOCUS+ beneficiary cohorts?"),
        (("apply", "registration", "how do i", "meghalayaone"), "How does someone apply for FOCUS+?"),
        (("how much", "amount", "benefit", "dbt", "installment", "instalment"),
         "How much does FOCUS+ pay, and how is it disbursed?"),
        (("implement", "mbda", "who runs"), "Who implements FOCUS+?"),
    ],
    "PMAY-G": [
        (("eligib", "who can", "who qualifies"), "Who is eligible for PMAY-G?"),
        (("document", "paper", "proof"), "What documents are required to apply for PMAY-G?"),
        (("apply", "application", "how do i get", "registration"), "How do I apply for PMAY-G?"),
        (("assistance", "how much money", "subsidy", "unit cost", "amount given"),
         "How much financial assistance does PMAY-G provide per house?"),
        (("select", "priority", "secc", "waitlist", "beneficiary list"),
         "How is a PMAY-G beneficiary selected from the SECC list?"),
    ],
    "MGNREGA": [
        (("eligib", "who can", "who qualifies"), "Who is eligible for MGNREGA work?"),
        (("job card", "apply", "registration", "how do i get"), "How do I apply for a MGNREGA job card?"),
        (("wage rate", "how much paid", "daily wage", "payment"), "What is the MGNREGA wage rate?"),
        (("what work", "type of work", "permissible", "allowed work"), "What kinds of work are allowed under MGNREGA?"),
        (("100 day", "hundred day", "guarantee"), "What is the 100-day guarantee under MGNREGA?"),
    ],
    "CM Elevate": [
        (("what is", "about cm elevate", "overview"), "What is CM-ELEVATE?"),
        (("eligib", "who can", "who qualifies"), "Who is eligible for CM-ELEVATE?"),
        (("apply", "registration", "how do i", "meghalayaone"), "How does someone apply for CM-ELEVATE?"),
        (("how many scheme", "sub-scheme", "sectors covered"), "How many individual schemes does CM-ELEVATE cover?"),
        (("how much", "subsidy", "financial support", "project cost"),
         "How much financial support does CM-ELEVATE provide?"),
        (("implement", "prime", "who runs"), "Who implements CM-ELEVATE?"),
    ],
    "Focus Legacy": [
        (("what is", "about focus", "overview"), "What is the FOCUS scheme in Meghalaya?"),
        (("objective", "aim", "purpose", "goal"), "What is the main objective of FOCUS?"),
        (("producer group", "what is a pg"), "What is the role of Producer Groups under FOCUS?"),
        (("eligib", "who can", "who qualifies", "who benefit"), "Who can benefit under the FOCUS scheme?"),
        (("assistance", "how much money", "support", "financial"),
         "What type of financial assistance is provided under FOCUS?"),
        (("apply", "registration", "how do i", "distribut"),
         "How is financial assistance distributed under FOCUS?"),
    ],
    # CM Elevate Legacy is the same CM-ELEVATE programme's sanction and
    # disbursement data, so its "how does it work" questions are the programme's
    # (rag.py falls back to the CM Elevate reference docs for this scheme).
    "CM Elevate Legacy": [
        (("how much", "subsidy", "financial support", "loan", "credit"),
         "How much financial support does CM-ELEVATE provide?"),
        (("eligib", "who can", "who qualifies"), "Who is eligible for CM-ELEVATE?"),
        (("how many scheme", "sub-scheme", "sectors covered"),
         "How many individual schemes does CM-ELEVATE cover?"),
        (("apply", "registration", "how do i"), "How does someone apply for CM-ELEVATE?"),
    ],
    "CMSS": [
        (("what is", "about cmss", "overview"), "What is CMSS (the Chief Minister's Scholarship Scheme)?"),
        (("eligib", "who can", "who qualifies"), "Who is eligible for CMSS?"),
        (("document", "paper", "proof", "domicile"), "What documents are required to apply for CMSS?"),
        (("apply", "registration", "how do i", "meghalayaone"), "How does a student apply for CMSS?"),
        (("how much", "amount", "benefit", "6000"), "How much does CMSS pay per student?"),
        (("implement", "dhte", "who runs"), "Who implements CMSS?"),
    ],
}
# Knowledge fix 2026-10-29 (KR9): after a "how does it work" answer, the last chip is
# one of the scheme's figures, so the officer can go from the rule to the numbers.
# Each is a statewide, all-years question the data path answers without a pause
# (tests/live_chat_knowledge.py "NS-" cases ask every one of them).
_KNOWLEDGE_DATA_NEXT = {
    "MGNREGA": "How many person-days were generated under MGNREGA?",
    "PMAY-G": "How many PMAY-G houses have been completed?",
    "Focus Plus": "How many Focus Plus beneficiaries have been paid?",
    "CM Elevate": "How many CM Elevate applications are there?",
    "Focus Legacy": "How many producer groups were paid under Focus Legacy?",
    "CM Elevate Legacy": "How much has been sanctioned under CM Elevate Legacy?",
    "CMSS": "How many CMSS applications are there?",
}
# "What does FOCUS stand for?" was followed by the chip "What is the FOCUS scheme?" —
# the same answer again. A what-is chip is skipped after any definition question.
_DEFINITION_ASKED = ("stand for", "full form", "acronym", "abbreviation", "what is", "what's", "meaning")


def _knowledge(question: str, schemes: list[str]) -> list[dict]:
    out: list[str] = []
    for scheme in schemes:
        for needles, q in _KNOWLEDGE_LADDER.get(scheme, []):
            if len(out) >= _MAX - 1:
                break
            if _asked(question, *needles):
                continue
            if q.lower().startswith("what is") and _asked(question, *_DEFINITION_ASKED):
                continue
            if q not in out:
                out.append(q)
        if len(out) >= _MAX - 1:
            break
    data_next = _KNOWLEDGE_DATA_NEXT.get(schemes[0]) if len(schemes) == 1 else None
    if data_next:
        out.append(data_next)
    return [{"label": q, "question": q} for q in out[:_MAX]]


# ── entry point ─────────────────────────────────────────────────────────────
def build_followups(route: str, question: str, schemes: list[str],
                    resolved_entities: dict, sql: str | None = None,
                    rows: list | None = None) -> list[dict]:
    """Up to `_MAX` {label, question} next-step suggestions for a data/knowledge
    answer. Empty list for any other route or if nothing sensible applies.

    `sql` is the generated query for a data answer — only its GROUP BY is read,
    to keep suggestions at the grain the answer is already at. `rows` is the
    result set, used to name the largest area when drilling one level deeper."""
    q = question or ""
    ents = resolved_entities or {}
    primary = _primary_schemes(schemes, q)
    grain = _answer_grain(sql) if route == "data" else None

    if route == "knowledge":
        opts = _knowledge(q, primary)
    elif route == "data":
        if len(primary) >= 2:
            opts = _cross_scheme_data(q, ents, grain, rows, primary)
        elif primary[0] == "PMAY-G":
            opts = _pmay_data(q, ents, grain, rows)
        elif primary[0] == "Focus Plus":
            opts = _focusplus_data(q, ents, grain, rows)
        elif primary[0] == "CM Elevate":
            opts = _cmelevate_data(q, ents, grain, rows)
        elif primary[0] == "Focus Legacy":
            opts = _focuslegacy_data(q, ents, grain, rows)
        elif primary[0] == "CM Elevate Legacy":
            opts = _cmelevatelegacy_data(q, ents, grain, rows)
        elif primary[0] == "CMSS":
            opts = _cmss_data(q, ents, grain, rows)
        else:
            opts = _mgnrega_data(q, ents, grain, rows)
    else:
        return []

    # Drop any suggestion that just restates the question, and any duplicate.
    asked_norm = _norm(q)
    asked_words = _content_words(q)
    year = _year_phrase(ents)
    seen: set[str] = set()
    cleaned: list[dict] = []
    for o in opts:
        key = _norm(o["question"])
        if not key or key == asked_norm or key in seen:
            continue
        # F-12 (chat UI audit 2026-10-29): "How much has been disbursed under Focus Plus
        # in Ri Bhoi?" after "Focus Plus amount disbursed in Ri Bhoi" — a chip that adds
        # no word of its own asks the question just answered
        if route == "data" and _content_words(o["question"]) <= asked_words:
            continue
        seen.add(key)
        # F-10: the answer's year goes into every chip that names none; a full new
        # question inherits no year (D-061 / D-065), so the chip asked "which year?" again
        if year and not _names_time(o["question"]):
            o = {**o, "question": _with_year(o["question"], year)}
        cleaned.append(o)
    return cleaned[:_MAX]


_F_STOP = frozenset("a an the of in on for to is are was were be been has have had how many much what which who "
                    "whom whose total number count give me show tell under by with and or meghalaya all overall "
                    "there did do does amount figure figures".split())
_F_TIME = frozenset("year years fy yearwise annual annually trend trends month months monthly quarter "
                    "since till until each financial".split())


def _content_words(text: str) -> set:
    return {w for w in _norm(text).split() if w not in _F_STOP}


def _names_time(text: str) -> bool:
    words = _norm(text).split()
    return any(w in _F_TIME for w in words) or any(len(w) >= 4 and w[:2] in ("19", "20") and w[:4].isdigit()
                                                   for w in words)


def _year_phrase(ents: dict) -> "str | None":
    ys = [ents["year_key"]] if ents.get("year_key") is not None else list(ents.get("year_key_list") or [])
    try:
        ys = sorted(int(y) for y in ys)
    except (TypeError, ValueError):
        return None
    if not ys:
        return None
    fy = (lambda y: f"FY {y}-{(y + 1) % 100:02d}")
    return f"in {fy(ys[0])}" if len(ys) == 1 else f"from {fy(ys[0])} to {fy(ys[-1])}"


def _with_year(question: str, phrase: str) -> str:
    q = (question or "").rstrip()
    end = q[-1] if q and q[-1] in "?." else ""
    return f"{q[:-1] if end else q} {phrase}{end}"

# app/pipeline/common/c03_scheme_terms.py — scheme vocabulary and scheme pauses / resumes.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.



# Year pieces of the time phrases below ("in FY 2024-25", "for 2024-25").
_C03_D4 = Pred(lambda w: len(w) == 4 and is_int(w))
_C03_Y4 = Pred(lambda w: len(w) == 4 and w[:2] in ("19", "20") and is_int(w))
_C03_FY4 = Pred(lambda w: len(w) == 6 and w[:2].lower() == "fy" and is_int(w[2:]))
_C03_FY4Y = Pred(lambda w: len(w) == 6 and w[:2].lower() == "fy" and w[2:4] in ("19", "20") and is_int(w[2:]))
_C03_D24 = Pred(lambda w: 2 <= len(w) <= 4 and is_int(w))
_C03_DASH = _C01Gap(_c01_dash)
_C03_HOW_WHY_MORE = Matcher(W("how", "why", "more"))


def _c03_cut(matcher: "Matcher", text: str) -> str:
    """Every hit of `matcher` removed together with the whitespace, optional comma
    and whitespace right before it (all of it replaced with "")."""
    out, last = [], 0
    for h in matcher.finditer(text):
        k = h.start()
        while k > last and text[k - 1].isspace():
            k -= 1
        if k > last and text[k - 1] == ",":
            k -= 1
            while k > last and text[k - 1].isspace():
                k -= 1
        out.append(text[last:k])
        last = h.end()
    out.append(text[last:])
    return "".join(out)


class _C03Literal(_C01Node):
    """The exact text `phrase` (any case), starting and ending on word edges."""

    def __init__(self, phrase: str):
        self.phrase = (phrase or "").lower()

    def ends(self, ctx, i, caps):
        if i >= len(ctx.toks) or not self.phrase:
            return
        a = ctx.toks[i].start
        if ctx.text[a:a + len(self.phrase)].lower() != self.phrase:
            return
        e = a + len(self.phrase)
        for k in range(i, len(ctx.toks)):
            if ctx.toks[k].end == e:
                yield k + 1, caps
                return
            if ctx.toks[k].end > e:
                return


def _c03_drop_digit_commas(t: str) -> str:
    """'1,23,456' -> '123456': a comma between a digit and 2-3 digits that end a
    word (only the comma is dropped; the digits on both sides stay)."""
    out = []
    n = len(t)
    for k, c in enumerate(t):
        if c == "," and k > 0 and t[k - 1].isdigit():
            j = k + 1
            while j < n and t[j].isdigit():
                j += 1
            run = j - k - 1
            if run in (2, 3) and (j == n or not (t[j].isalnum() or t[j] == "_")):
                continue
        out.append(c)
    return "".join(out)


# The user explicitly wants a cross-scheme answer — honour it, don't ask.
_EXPLICIT_BOTH = Matcher(Alt(
    _c01_ph("both scheme", "both schemes", "all scheme", "all schemes", "each scheme", "per scheme",
            "by scheme", "across scheme", "across schemes", "every scheme", "either scheme",
            "the two schemes"),
    _c01_chain(["scheme", "wise"], ["opt1"])))
_TALKS_ABOUT_SCHEMES = Matcher(W("scheme", "schemes", "programe", "programes", "programme", "programmes"))


def _infer_scheme_from_terms(question: str) -> list[str] | None:
    """A single scheme implied by scheme-specific vocabulary, or None if the
    question could plausibly mean more than one."""
    hits = ["MGNREGA"] if _mgnrega_terms(question) else []
    hits += [
        s for s, word_matcher in (
            ("PMAY-G", _PMAY_ONLY_TERMS),
            ("Focus Plus", _FOCUSPLUS_ONLY_TERMS),
            ("CM Elevate", _CMELEVATE_ONLY_TERMS),
            ("Focus Legacy", _FOCUSLEGACY_ONLY_TERMS),
            ("CM Elevate Legacy", _CMELEVATELEGACY_ONLY_TERMS),
            ("CMSS", _CMSS_ONLY_TERMS),
            ("Homestay", _HOMESTAY_ONLY_TERMS),
        ) if word_matcher.search(question)
    ]
    # A CM Elevate sub-scheme word ("piggery", "dairy") belongs to BOTH CM
    # Elevate datasets. When the rest of the question asks for money, a year or
    # a lender, only CM Elevate Legacy can answer it — settle on that one rather
    # than reading the pair as ambiguous (or sending a money question to the
    # dataset that has no money column).
    if "CM Elevate" in hits and _prefers_cm_elevate_legacy(question):
        hits = [h for h in hits if h != "CM Elevate"]
        if "CM Elevate Legacy" not in hits:
            hits.append("CM Elevate Legacy")
    return hits if len(hits) == 1 else None


# A resumed one-tap question is built by naming the scheme in the stem. Naively
# appending " for <scheme>" reads fine for a DATA stem ("total person-days for
# MGNREGA") but produces broken phrasing for a KNOWLEDGE stem that already says
# the generic word "scheme" ("tell me about scheme" -> "tell me about scheme for
# Focus Plus") — that phrasing is grammatically odd enough that the RAG answer
# composer sometimes reads it as asking about a DIFFERENT, uncovered scheme and
# refuses with "not covered" even though the retrieved passages score well
# above the medium-confidence floor (verified: top score 0.77, well above the
# 0.55 floor, yet the composer still said "not covered" on this exact phrasing).
# When the stem already names "scheme(s)" generically, replace that word with
# the actual scheme name instead of appending — "tell me about scheme" becomes
# "tell me about Focus Plus", which both reads naturally and matches how the
# reference docs open ("Focus Plus is ...").
_GENERIC_SCHEME_WORD = Matcher(W("scheme", "schemes"))


def _scheme_option_question(stem: str, scheme: str) -> str:
    if _GENERIC_SCHEME_WORD.search(stem):
        return _GENERIC_SCHEME_WORD.sub(scheme, stem, count=1)
    return f"{stem} for {scheme}"


_FARMER_WORDS = Matcher(W("farmer", "farmers", "cultivator", "cultivators", "kisan", "kisans"))


_SCHEME_PICK_LABELS = (
    ("MGNREGA", "MGNREGA (rural employment)"),
    ("PMAY-G", "PMAY-G (rural housing)"),
    ("Focus Plus", "Focus Plus (farmer cash benefit)"),
    ("CM Elevate", "CM Elevate (livelihood / enterprise schemes)"),
    ("Focus Legacy", "Focus Legacy (producer group payments)"),
    ("CM Elevate Legacy", "CM Elevate Legacy (sanctions & disbursements)"),
    ("CMSS", "CMSS (Chief Minister's Scholarship Scheme)"),
    ("Homestay", "Homestay (Chief Minister's Meghalaya Homestay Mission applications)"),
)


def _schemes_recording(question: str) -> "tuple[list[str], list[str], bool]":
    """(schemes, measure labels, together): the schemes that record every
    measure the question names (_MEASURE_HOLDERS), in picker order, together=True.
    When no one scheme records them all, every scheme that records any of them,
    together=False. ([], [], False) when the question names no measure. Typo'd
    measure words count ("applicxations")."""
    text = _rephrase_gloss(question or "")
    asked = [(label, holders) for label, word_matcher, holders in _MEASURE_HOLDERS
             if word_matcher.search(text)]
    if not asked:
        return [], [], False
    keep = frozenset.intersection(*(h for _, h in asked))
    together = bool(keep)
    if not together:
        keep = frozenset().union(*(h for _, h in asked))
    return [s for s, _ in _SCHEME_PICK_LABELS if s in keep], [label for label, _ in asked], together


def _scheme_clarification(question: str, by_measure: bool = False) -> "ClarificationNeeded":
    """`by_measure` (the DATA path): offer only the schemes that record what the
    question asks for. "gender wise breakup of applications" listed all six
    schemes, four of which hold no gender or no applications (user report
    2026-10-19: "you should be showing only for that"). Not on the KNOWLEDGE
    path: "how do I apply?" is answerable for every scheme."""
    stem = question.strip().rstrip(" ?.")
    # "I want to know about farmers getting money" (live 2026-10-18): only the two
    # Focus schemes pay farmers, so ask which Focus — with what each one holds —
    # rather than the six-scheme list.
    if _FARMER_WORDS.search(question or "") and not _MGNREGA_AC_TERM.search(question or ""):
        return _focus_ambiguity_clarification(question)
    if _MGNREGA_AC_TERM.search(question or ""):
        # only these schemes hold a constituency (KI-148)
        return ClarificationNeeded(
            "Assembly-constituency figures are held for three schemes. Which one is your "
            "question about? Pick it below.",
            options=[{"label": "MGNREGA (rural employment)", "question": _scheme_option_question(stem, "MGNREGA")},
                     {"label": "Focus Legacy (producer group payments)",
                      "question": _scheme_option_question(stem, "Focus Legacy")},
                     {"label": "CM Elevate Legacy (sanctions & disbursements)",
                      "question": _scheme_option_question(stem, "CM Elevate Legacy")},
                     {"label": "CMSS (student scholarships)", "question": _scheme_option_question(stem, "CMSS")},
                     {"label": "Homestay (homestay applications)", "question": _scheme_option_question(stem, "Homestay")}],
            rule="scheme-not-specified")
    held, measures, together = _schemes_recording(question) if by_measure else ([], [], False)
    if held and len(held) < len(_SCHEME_PICK_LABELS):
        what = " and ".join(measures)
        if len(held) == 1:
            head = f"Only {held[0]} records {what}. Tap it below to get the figures."
        elif together:
            head = f"Only these schemes record {what}. Which one is your question about?"
        else:
            head = f"No single scheme records {what} together. Which scheme should I look at?"
        return ClarificationNeeded(
            head,
            options=[{"label": label, "question": _scheme_option_question(stem, s)}
                     for s, label in _SCHEME_PICK_LABELS if s in held],
            rule="scheme-not-specified")
    options = [{"label": label, "question": _scheme_option_question(stem, s)}
               for s, label in _SCHEME_PICK_LABELS]
    # Best guess first (spelling-fix brief 2026-10-29): "fokis plas" is still all
    # six schemes, with Focus Plus at the top. A clear lead only (>= 60 and 10
    # ahead); otherwise the registry's order.
    from app import spelling as _c03_sp
    _scores = _c03_sp.scheme_scores(question)
    _ranked = sorted(_scores.values(), reverse=True)
    if _ranked and _ranked[0] >= 60 and (len(_ranked) < 2 or _ranked[0] - _ranked[1] >= 10):
        _top = max(_scores, key=_scores.get)
        options.sort(key=lambda o: 0 if o["label"].split(" (")[0] == _top else 1)
    return ClarificationNeeded(
        # Short and conversational: the UI lists the schemes as cards right
        # under this line, so the names are not repeated here (user, 2026-10-18).
        "Which scheme is your question about? Pick one below.",
        options=options,
        rule="scheme-not-specified",
    )


# ── "Focus" alone: which of the TWO Focus schemes? ──────────────────────────
# Two live schemes answer to the word "Focus" and they share NOTHING but the name:
# Focus Legacy pays PRODUCER GROUPS (Rs 5,000 per member), Focus Plus pays
# INDIVIDUAL BENEFICIARIES, there is no key between them, and Focus Plus holds no
# producer-group column at all. focuslegacy_entity_resolver.yaml's own
# scheme.disambiguation rule is explicit that a bare "Focus" with no forcing word
# must be ASKED, not guessed — guessing answers a producer-group question from a
# partition that cannot answer it (or vice versa) and reads as authoritative.
#
# This is a TWO-way ask, not the generic five-way one: the user has already told
# us it's a Focus question, so re-offering MGNREGA / PMAY-G / CM Elevate would
# throw that away.
_BARE_FOCUS_WORD = Matcher(W("focus"))


def _is_ambiguous_focus(question: str) -> bool:
    """The question says "Focus" but nothing that pins WHICH Focus scheme."""
    q = question or ""
    if not _BARE_FOCUS_WORD.search(q):
        return False
    # Either scheme named outright (or by its own qualified alias) — settled.
    if _SCHEME_NAME_MATCHER["Focus Plus"].search(q):
        return False
    if _SCHEME_NAME_MATCHER["Focus Legacy"].search(q):
        return False
    # A forcing word from either side's own vocabulary — also settled.
    if _FOCUSLEGACY_ONLY_TERMS.search(q) or _FOCUSPLUS_ONLY_TERMS.search(q):
        return False
    # "How many members are there in Focus Bibari?" — "Focus" is part of a
    # producer-group NAME (only Focus Legacy has groups). Asking "which Focus?"
    # and then swapping in "Focus Legacy" turned it into "Focus Legacy Bibari",
    # which matches nothing (all-PG run 2026-09-29, KI-157).
    if _pg_focus_group_name(q):
        return False
    return True


# "focus" as an ordinary English noun or verb ("the main focus of this scheme",
# "it focuses on women"), not the scheme name.
_FOCUS_AS_NOUN = Matcher(Alt(
    Seq(W("the", "its", "their", "this", "that", "a", "main", "key", "primary", "major", "core", "central",
          "special", "chief"), "focus", sep="space"),
    Seq(Alt(Seq("focus", W("area", "areas"), sep="space"), W("focus", "focuss")),
        W("of", "on", "upon"), sep="space"),
    Seq("focus", W("area", "areas"), sep="space"),
    W("focuses", "focused", "focusing")))


def _names_bare_focus_scheme(question: str) -> bool:
    """A bare "Focus" used as a SCHEME name ("what is focus", "focus
    beneficiaries", "under focus"), which scheme it is still unsettled.
    Reported 2026-09-29: after a CM Elevate Legacy answer, "what is focus" was
    taken for a fragment and the 4B rewrite read the word as a noun — "What is
    the focus of the CM Elevate Legacy scheme in FY 2024-25?" — so the user got
    CM Elevate material instead of the which-Focus question."""
    return _is_ambiguous_focus(question) and not _FOCUS_AS_NOUN.search(question or "")


# A time filter inside a rewritten how-the-scheme-works question: "…in FY
# 2024-25", "for 2024-25", "across all financial years".
_INHERITED_TIME_MATCH = Matcher(Alt(
    Seq(W("in", "for", "during", "of", "from"), Opt("the"),
        Seq(Alt(Seq(Alt(W("fy"), Seq("financial", "year", sep="space")), _C03_D4, sep="space"), _C03_FY4),
            _C03_DASH, _C03_D24), sep="space"),
    Seq(W("in", "for", "during"), Seq(_C03_D4, _C03_DASH, _C03_D24), sep="space"),
    Seq(W("across", "for", "over"), "all", Opt("the"), Opt("financial"), "years", Opt("combined"),
        sep="space")))


_ANY_YEAR_PHRASE_MATCH = Matcher(Seq(
    Opt(W("in", "for", "during", "of", "from")), Opt("the"),
    Seq(Alt(Seq(Opt(Alt(W("fy"), Seq("financial", "year", sep="space"))), _C03_Y4, sep="space"), _C03_FY4Y),
        Opt(Seq(_C03_DASH, _C03_D24))),
    sep="space"))


def _followup_thread_state(question: str, prev: "object",
                           state: "ConversationState | None") -> "ConversationState | None":
    """The structured state a follow-up continues. Normally the session's. But
    right after a KNOWLEDGE answer about ANOTHER scheme, the session's state
    still holds the earlier DATA thread (a digression does not overwrite it),
    and a follow-up that names nothing continues the antecedent instead:
    after "what is Focus Plus", "give me beneficiaries" is Focus Plus, and the
    earlier CM Elevate Legacy FY 2024-25 must not ride along (live 2026-09-29:
    "…for Focus Plus in FY 2024-25", a year Focus Plus does not hold). A
    follow-up whose own words pick the earlier scheme ("and person-days?" is
    MGNREGA vocabulary) still continues that thread with its filters."""
    if state is None or prev is None or getattr(prev, "route", None) != "knowledge":
        return state
    kschemes = list(getattr(prev, "schemes", None) or [])
    if len(kschemes) != 1 or kschemes[0] == state.scheme:
        return state
    own = set(_named_schemes(question)) | set(_infer_scheme_from_terms(question) or [])
    if state.scheme and state.scheme in own:
        return state
    return ConversationState(scheme=kschemes[0])


def _all_years_rewrite(prev_question: str) -> "str | None":
    """"and all of them combined?" after single-year turns: the previous
    question with its year removed, over all financial years. Deterministic —
    the model rewrite put the last year back (live 2026-09-29), and the
    cleared-field check then left a fragment with no measure in it."""
    if not prev_question or not context_policy.extract_year_keys(prev_question):
        return None
    out = _c03_cut(_ANY_YEAR_PHRASE_MATCH, prev_question)
    out = _c01_tidy_space(out, "?.!,").strip().rstrip(" ?.,")
    return f"{out} across all financial years?" if out else None


def _drop_inherited_place(question: str, typed: str) -> str:
    """The rewritten KNOWLEDGE question without a district / block the user
    never typed. Live 2026-09-29: "who is eligible?" and "what documents are
    needed?" after an East Khasi Hills figure became "…for PMAY-G houses in
    East Khasi Hills?", and the answers said the documents are "not listed
    for East Khasi Hills" — scheme rules are not per district."""
    typed_places = named_places(typed or "")
    out = question or ""
    for place in named_places(out):
        if place in typed_places:
            continue
        out = _c03_cut(Matcher(Seq(W("in", "for", "of", "within", "under"), Opt("the"), _C03Literal(place),
                                   Opt(W("district", "block")), sep="space")), out)
    out = _c01_tidy_space(out, "?.!,").strip()
    return out or question


def _data_thread_antecedent(question: str, prev: "object", session: "Session | None",
                            plan: "context_policy.MergePlan | None") -> "object | None":
    """The last DATA turn, when a follow-up that only changes a place or a year
    comes right after KNOWLEDGE answers about the same scheme. Scheme rules do
    not vary by district or year, so "and in West Garo Hills?" after "who is
    eligible?" / "what documents are needed?" continues the earlier figure
    (PMAY-G completed houses, FY 2023-24), not the documents question (live
    2026-09-29, the KI-033 family). None when the follow-up asks about how the
    scheme works itself, or no such DATA turn is within the last 4 turns."""
    if session is None or plan is None or getattr(prev, "route", None) != "knowledge":
        return None
    # The follow-up's own words pick ANOTHER scheme than the knowledge aside
    # ("and person-days?" = MGNREGA after "who is eligible for PMAY-G?"): its
    # antecedent is that scheme's last DATA turn, whatever kind of change it is.
    own = set(_named_schemes(question)) | set(_infer_scheme_from_terms(question) or [])
    kscheme = (getattr(prev, "schemes", None) or [None])[0]
    if own and not any(topic_memory.same_scheme_family(kscheme, o) for o in own):
        for t in reversed(list(session.turns or [])[-4:]):
            if getattr(t, "route", None) == "data" and any(
                    topic_memory.same_scheme_family(o, s) for o in own for s in (t.schemes or [])):
                return t
        # A worker rehydrated from the snapshot holds only the last turn; the
        # topic ledger still has the DATA turn (live 2026-10-18, scenario H).
        if not any(getattr(t, "route", None) == "data" for t in list(session.turns or [])[-4:]):
            return topic_memory.recent_data_turn(session, own)
        return None
    if plan.kind not in (context_policy.GEOGRAPHY_CHANGE, context_policy.TIME_CHANGE):
        return None
    if _KNOWLEDGE_HINTS.search(question or "") or context_policy._SCHEME_TOPIC_MATCH.search(
            _C03_HOW_WHY_MORE.sub(" ", question or "")):
        return None
    scheme = (getattr(prev, "schemes", None) or [None])[0]
    for t in reversed(list(session.turns or [])[-4:]):
        if getattr(t, "route", None) == "data":
            return t if (not scheme or any(topic_memory.same_scheme_family(scheme, s)
                                           for s in (t.schemes or []))) else None
    # No DATA turn in memory: a worker rehydrated from the snapshot (it holds
    # only the last turn). The topic ledger is durable (live 2026-10-18, H).
    return topic_memory.recent_data_turn(session, [scheme] if scheme else None)


def _drop_inherited_time(question: str, typed: str) -> str:
    """The rewritten KNOWLEDGE question without a year the user never typed.
    The follow-up rewrite gets the previous DATA turn's filters, so "what is
    focus" after an FY 2024-25 figure came back "…in FY 2024-25?", and the
    reference docs (which are not per year) then had "no such detail"
    (reported 2026-09-29). A year the user typed is kept."""
    if context_policy.extract_year_keys(typed or "") or _ALL_YEARS_CUE.search(typed or ""):
        return question
    out = _c03_cut(_INHERITED_TIME_MATCH, question or "")
    out = _c01_tidy_space(out, "?.!,").strip()
    return out or question


def _focus_ambiguity_clarification(question: str) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    # Replace the bare "Focus" in place rather than appending, so the resumed
    # question reads naturally and re-resolves cleanly on the next turn
    # ("total focus disbursement" -> "total Focus Legacy disbursement").
    def _swap(name: str) -> str:
        swapped = _BARE_FOCUS_WORD.sub(name, stem, count=1)
        return swapped if swapped != stem else f"{stem} for {name}"

    return ClarificationNeeded(
        "Two different schemes are called Focus, and they hold different things — "
        "Focus Legacy pays PRODUCER GROUPS (one payment per group, Rs 5,000 per "
        "member), while Focus Plus pays INDIVIDUAL farmers directly. Which one do "
        "you mean?",
        options=[
            {"label": "Focus Legacy (producer group payments)",
             "question": _swap("Focus Legacy")},
            {"label": "Focus Plus (individual farmer cash benefit)",
             "question": _swap("Focus Plus")},
        ],
        rule="focus-scheme-ambiguous",
    )


# Pauses whose answer is a SCHEME, not a scope fragment. The router remembers
# them (session.pending_scope_rule/options) so that a TYPED answer resumes the
# paused question: "Show beneficiaries" -> "Which scheme?" -> "Focus Plus" used
# to go through as the brand-new question "Focus Plus", so the original ask was
# lost unless the user clicked a chip.
SCHEME_PAUSE_RULES = ("scheme-not-specified", "focus-scheme-ambiguous", "bank-scheme-not-specified",
                      "cm-elevate-dataset")
_SCHEME_REPLY_FILLER = Matcher(Alt(
    W("the", "for", "under", "in", "of", "scheme", "schemes", "data", "only", "please", "pls", "its", "ok",
      "okay", "yes", "one"),
    Seq("i", "mean", sep="space"),
    Seq("it", _C01Gap(lambda g: g == "'"), "s")))
_FOCUS_SIDE_WORD = {"plus": "Focus Plus", "legacy": "Focus Legacy"}
# The "CM Elevate or CM Elevate Legacy?" pause: a typed side word picks one.
_CME_SIDE_WORD = {"legacy": "CM Elevate Legacy", "disbursement": "CM Elevate Legacy",
                  "disbursements": "CM Elevate Legacy", "sanctions": "CM Elevate Legacy",
                  "applications": "CM Elevate", "application": "CM Elevate", "applicants": "CM Elevate"}

# Pauses whose free-text reply is a scope FRAGMENT, merged into the paused
# question ("West Garo Hills 2023-24"). The router remembers them without
# options; _turn_context_stage step 0a merges.
SCOPE_MERGE_RULES = ("scope-not-specified", "year-not-specified", "entity-ambiguous",
                     "ranking-count-not-specified")


# ── A typed reply to ANY other pause that offered chips ─────────────────────
# Reported 2026-09-29: after "give me for pmay" paused with PMAY-G's measures
# (swap-measure-unavailable), a typed "houses sanctioned" continued the LAST
# ANSWERED turn, MGNREGA. Only the scope and scheme pauses were remembered;
# every other pause with chips (the measure gap, year out of range, tranche,
# region, AC part, Sericulture spelling, CM sub-scheme group, stated amount,
# village-or-outside, scheme comparison, ...) forgot its question, so a typed
# answer was read against the previous turn and a chip was the only way on.
#
# Now the router remembers every pause that offers options, and a typed reply
# is matched to ONE option: its label's words ("houses sanctioned", "2022-23",
# "spinning", "all years"), an ordinal ("the second one", "2"), a bare "yes"
# when there is only one option, or the chip's own question. Deterministic; an
# ambiguous or unmatched reply picks nothing (_paused_thread_antecedent then
# decides which thread it continues).
_OPTION_FILLER = frozenset(
    "the a an of for in under on at please pls ok okay yes yeah yep sure one only i want "
    "need show give me us tell get what about how many much was were is are total number "
    "fy go with let lets do it that just option choice can you would like to and by "
    "which this those these them then".split())
_ORDINAL_WORDS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
                  "fourth": 3, "4th": 3, "fifth": 4, "5th": 4}
_ORDINAL_REPLY = Matcher(Seq(
    Alt(Seq(_C01Begin(), Opt(Alt(Seq(W("the", "option", "choice", "number"), _C01_WS0),
                                 Seq("no", _C01Gap(lambda g: g.strip() == "" or (
                                     g[:1] == "." and g[1:].strip() == "")))))),
        _C01Begin(("#",))),
    Cap(Alt(W("first", "second", "third", "fourth", "fifth", "1st", "2nd", "3rd", "4th", "5th", "last"),
            Pred(lambda w: len(w) == 1 and w in "123456789"))),
    _C01_WS0,
    Opt(Seq(W("one", "option", "choice"), _C01_WS0)),
    Opt(Seq(W("please", "pls"), _C01_WS0)),
    _C01End(".!?")))
_BARE_YES = Matcher(Seq(
    _C01Begin(),
    Alt(W("yes", "yeah", "yep", "sure", "ok", "okay", "please"), Seq("go", _C01_WS0, "ahead"),
        Seq("do", _C01_WS0, "it")),
    Opt(Seq(_C01Gap(lambda g: g.strip() in ("", ",")),
            Alt(W("please", "pls"), Seq("go", _C01_WS0, "ahead"), Seq("do", _C01_WS0, "it")))),
    _C01End(".!")))
def _c03_option_words(t: str) -> "list[str]":
    """Runs of a-z / 0-9 joined by single hyphens ("2022-23", "goat-farming")."""
    def ok(c):
        return c.isascii() and (c.isdigit() or "a" <= c <= "z")
    out, i, n = [], 0, len(t)
    while i < n:
        if not ok(t[i]):
            i += 1
            continue
        j = i
        while j < n and ok(t[j]):
            j += 1
        while j + 1 < n and t[j] == "-" and ok(t[j + 1]):
            j += 1
            while j < n and ok(t[j]):
                j += 1
        out.append(t[i:j])
        i = j
    return out


def _option_tokens(text: str) -> "set[str]":
    """Content words of a label / reply / chip question, scheme names removed,
    amounts without their ₹ and commas, plurals folded ("houses" = "house")."""
    t = text or ""
    for word_matcher in _SCHEME_NAME_MATCHER.values():
        t = word_matcher.sub(" ", t)
    t = _c03_drop_digit_commas(t.lower().replace("₹", " "))
    out = set()
    for w in _c03_option_words(t):
        if w in _OPTION_FILLER:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def _resume_option_pause(reply: str, options: "list | None") -> "str | None":
    """The chip question a typed reply to a remembered option pause stands for,
    or None (the reply then goes on as a message of its own)."""
    opts = [o for o in (options or []) if isinstance(o, dict) and o.get("question")]
    r = (reply or "").strip()
    if not opts or not r or len(r.split()) > 12:
        return None
    for o in opts:  # a clicked chip sends its own question
        if r.rstrip(" ?.").lower() == str(o["question"]).rstrip(" ?.").lower():
            return o["question"]
    m = _ORDINAL_REPLY.match(r)
    if m:
        w = m.group(1).lower()
        i = len(opts) - 1 if w == "last" else (_ORDINAL_WORDS.get(w, int(w) - 1 if w.isdigit() else -1))
        return opts[i]["question"] if 0 <= i < len(opts) else None
    if _BARE_YES.match(r):
        return opts[0]["question"] if len(opts) == 1 else None
    reply_schemes = _exact_schemes(r)
    R = _option_tokens(r)
    if not R:
        return None
    strong, weak_label, weak_question = [], [], []
    for o in opts:
        # A reply that names a scheme picks only an option about that scheme.
        if reply_schemes and not reply_schemes <= (_exact_schemes(o["question"])
                                                   | _exact_schemes(str(o.get("label", "")))):
            continue
        L, Q = _option_tokens(str(o.get("label", ""))), _option_tokens(o["question"])
        if L and L <= R and R <= (L | Q):
            strong.append(o)
        if R <= L:
            weak_label.append(o)
        if R <= Q:
            weak_question.append(o)
    for picked in (strong, weak_label, weak_question):
        if len(picked) == 1:
            return picked[0]["question"]
        if len(picked) > 1:
            return None
    return None


def _paused_thread_antecedent(reply: str, paused_question: str, prev: "object",
                              rule: "str | None" = None) -> "object | None":
    """A stand-in previous turn for a typed reply to an option pause that
    picked no chip ("houses completed in West Garo Hills" after the PMAY-G
    measure pause), or None to keep `prev`. The paused question is about
    another scheme than the last answered turn, and the reply names none of
    its own: the reply continues the PAUSED question, not the answered one."""
    schemes = _exact_schemes(paused_question)
    if len(schemes) != 1:
        return None
    # A "not held in this scheme" pause, answered with just another scheme
    # ("in pmay" after "MGNREGA has no sanctioned amount"): the PAUSED question
    # is the one to swap, not the last answered turn (Chokpot women employment
    # was swapped instead and "PMAY-G doesn't record employment" came back;
    # user chat 2026-10-21, KI-350).
    _rs = _exact_schemes(reply)
    if rule == "column-not-held" and len(_rs) == 1 and _rs != schemes and len(reply.split()) <= 4:
        from app.session_store import Turn
        return Turn(question=paused_question, raw_question=paused_question, route="data",
                    schemes=sorted(schemes), resolved_entities={}, answer="")
    if _rs:
        return None
    target = next(iter(schemes))
    if prev is not None and target in (getattr(prev, "schemes", None) or []):
        return None
    # Its own words pick another scheme ("person-days in EKH" is MGNREGA
    # vocabulary): not a reply to this pause.
    own = set(_named_schemes(reply)) | set(_infer_scheme_from_terms(reply) or [])
    if own and target not in own:
        return None
    from app.session_store import Turn
    return Turn(question=paused_question, raw_question=paused_question, route="data",
                schemes=[target], resolved_entities={}, answer="")


def _resume_scheme_pause(reply: str, options: "list | None") -> "str | None":
    """The chip question a typed reply to a scheme pause stands for, or None.

    Returns something only when the reply is just ONE offered scheme's name,
    optionally with filler ("Focus Plus", "focus plus please", and "legacy"
    for the which-Focus pause). The result is then the exact question that
    scheme's chip would have sent, so a typed pick and a clicked pick run the
    same way downstream. Anything else returns None and the reply goes through
    untouched, exactly as before these pauses were remembered: a fresh
    question, several schemes, "thanks"."""
    if not reply or not options:
        return None
    r = reply.strip()
    if len(r.split()) > 6:
        return None
    offered = {str(o.get("label", "")).split(" (")[0].strip(): o.get("question")
               for o in options if isinstance(o, dict)}
    named = sorted(_exact_schemes(r))
    residue = r
    for s in named:
        residue = _SCHEME_NAME_MATCHER[s].sub(" ", residue)
    residue = keep_chars(_SCHEME_REPLY_FILLER.sub(" ", residue), lambda c: c not in ",.!?:;",
                         " ").strip().lower()
    for _side in (_FOCUS_SIDE_WORD, _CME_SIDE_WORD):
        if not named and residue in _side and set(offered) == set(_side.values()):
            named, residue = [_side[residue]], ""
    if residue or len(named) != 1:
        return None
    return offered.get(named[0])


# D-098 (BLH UAT 2026-11-02, item 3): "compare this with spend on Focus scheme" ->
# "Which Focus?" -> typed "compare both schemes by district" was no single scheme name,
# so _resume_scheme_pause let it through, the paused question was dropped and the reply
# was rewritten against the last answer (Focus Plus alone). A reply that takes EVERY
# offered scheme: "both", "all of them / all schemes", or "compare" with no side named.
_C03_ALL_OPTIONS = Matcher(Alt(
    W("both"),
    Seq(W("all", "each", "every"), Opt("of"), Opt(W("the", "these", "those")),
        W("them", "schemes", "options"), sep="space"),
    Seq(W(*sorted(context_policy._TK_COMPARE)), W("them", "these", "those"), sep="space")))


def _c03_scope_tail(reply: str, base: str) -> str:
    """The scope a typed reply adds to a paused question, read by the same scanners the
    follow-up plan uses (context_policy.asked_levels, extract_year_keys, place_mentions):
    " by district", " in FY 2023-24", " in Ri Bhoi". What `base` already says is skipped."""
    from app.entity_resolver import place_mentions
    tail = []
    for lvl in context_policy.asked_levels(reply):
        if lvl not in context_policy.asked_levels(base):
            tail.append(f"by {lvl}")
    for yk in sorted(context_policy.extract_year_keys(reply) - context_policy.extract_year_keys(base)):
        tail.append(f"in {context_manager._fy_text(yk)}")
    have = place_mentions(base)
    for name in place_mentions(reply):
        if name not in have:
            tail.append(f"in {name.title()}")
    return (" " + " ".join(tail)) if tail else ""


def _c03_join_names(names: "list[str]") -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"


def _resume_scheme_pause_typed(reply: str, paused: str, options: "list | None") -> "str | None":
    """The question a typed reply to a scheme pause stands for when it is more than one
    bare scheme name (_resume_scheme_pause handles that), or None (the reply then goes on
    untouched, as before). D-098:
      - every offered scheme ("both", "all of them", "compare" naming no side), plus any
        scope the reply adds: "compare both schemes by district" -> the paused question
        for Focus Legacy and Focus Plus, by district;
      - ONE offered scheme plus scope: "legacy by district";
      - scope only, no scheme: "by district" -> the paused question with that scope, so
        the scheme question asked again carries it.
    Never a guess: the built question must hold every word the reply typed (bar the pick
    and filler words); a reply with a measure or filter of its own is a new message."""
    if not reply or not paused or not options:
        return None
    opts = [o for o in options if isinstance(o, dict) and o.get("question")]
    paused_schemes = _exact_schemes(paused)
    per_option = []
    for o in opts:
        own = sorted(_exact_schemes(o["question"]) - paused_schemes)
        if len(own) != 1:
            return None
        per_option.append((own[0], o["question"]))
    if not per_option:
        return None
    r = reply.strip()
    offered = [s for s, _ in per_option]
    named = [s for s in offered if s in _exact_schemes(r)]
    if _exact_schemes(r) - set(offered):
        return None                      # names a scheme the pause did not offer: a new question
    words = set(w.lower() for w in _c01_tm_words(r))
    side_words = set()
    if not named:
        # "legacy by district" to the which-Focus pause: the side word names the scheme
        # exactly as a bare "legacy" does in _resume_scheme_pause.
        for _side in (_FOCUS_SIDE_WORD, _CME_SIDE_WORD):
            if set(offered) == set(_side.values()):
                hits = {_side[w] for w in words if w in _side}
                if len(hits) == 1:
                    named = sorted(hits)
                    side_words = {w for w in words if w in _side}
    wants_all = bool(_C03_ALL_OPTIONS.search(r)) or (
        not named and words & context_policy._TK_COMPARE and len(per_option) > 1)
    tail = _c03_scope_tail(r, paused)
    picked = offered if wants_all else named
    if len(picked) > 1:
        # every offered scheme, or the several the reply named ("mgnrega and pmay-g")
        first_scheme, first_q = next((s, q) for s, q in per_option if s == picked[0])
        built = _SCHEME_NAME_MATCHER[first_scheme].sub(_c03_join_names(picked), first_q, count=1
                                                       ).rstrip(" ?.") + tail
        how = "all-options" if wants_all else "several-options"
    elif len(named) == 1 and tail:
        built = dict(per_option)[named[0]].rstrip(" ?.") + tail
        how = "one-option+scope"
    elif not named and tail:
        built = paused.strip().rstrip(" ?.") + tail
        how = "scope-only"
    else:
        return None
    # Nothing the officer typed may be lost: every reply word must be in the built
    # question once the scheme names, the pick words and the reply filler are taken out.
    rest = r
    for s in _exact_schemes(r):
        rest = _SCHEME_NAME_MATCHER[s].sub(" ", rest)
    rest = _SCHEME_REPLY_FILLER.sub(" ", _C03_ALL_OPTIONS.sub(" ", rest))
    built_words = set(w.lower() for w in _c01_tm_words(built)) | side_words
    lost = [w for w in (x.lower() for x in _c01_tm_words(rest)) if w not in built_words]
    if lost:
        context_budget.log_decision("pause_reply", typed="not-resumed", lost=lost[:6])
        return None
    context_budget.log_decision("pause_reply", typed=how)
    return built + "?"


# ── CM Elevate: "the vehicle scheme?" — which of several real sub-schemes? ──
# The phrase used to name a scheme-FAMILY the question named in the singular
# (resolve_cm_scheme_group_ambiguity's match) — swapped out for each candidate's
# real scheme_name so the resumed question resolves cleanly via resolve_cm_scheme's
# own exact-alias stage, same trick _scheme_option_question uses for the top-level
# 4-scheme pause above.
_CM_GROUP_PHRASE = {
    "vehicles": Matcher(Seq("vehicle", "scheme", sep="space")),
    "tourism": Matcher(Seq("tourism", "scheme", sep="space")),
    "PRIME": Matcher(Seq("prime", "scheme", sep="space")),
    "livestock": Matcher(Seq("livestock", "scheme", sep="space")),
    "enterprise": Matcher(Seq("enterprise", "scheme", sep="space")),
}


def _cm_scheme_group_clarification(question: str, group: dict) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    schemes = group["schemes"]
    phrase_match = _CM_GROUP_PHRASE.get(group["group"])
    options = []
    for s in schemes:
        new_q = phrase_match.sub(s, stem, count=1) if phrase_match else None
        options.append({"label": s, "question": new_q if new_q and new_q != stem else f"{stem} — {s}"})
    all_list = ", ".join(schemes[:-1]) + " and " + schemes[-1]
    return ClarificationNeeded(
        f"“{group['group']}” covers {len(schemes)} separate CM Elevate schemes — "
        f"{all_list} — and they are not interchangeable. Which one did you mean?",
        options=options,
        rule="cm-scheme-group-ambiguous",
    )

# app/pipeline/common/c14_turn_stages.py — turn stages: context, edge, follow-up, rephrase, route, knowledge, data context.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.



# ── Turn stages (D-032) ─────────────────────────────────────────────────────
# The turn stages, run by the LangGraph context -> edge -> followup -> route ->
# knowledge / data_context nodes. Each reads its
# inputs from the per-turn dict `t` into the local names the code always used,
# writes its outputs back, and returns a finished result to end the turn early
# or None to go on. `t` holds the live objects (Turn, ConversationState,
# MergePlan); the graph stores them as plain dicts between nodes.

def _new_turn(question: str) -> dict:
    return {"question": question, "raw_question": question, "cm_pinned": False,
            "scope_resumed": False, "prev": None, "village_hint": None, "paused_state": None,
            "signals": [], "has_context": False, "plan": None, "thread_state": None,
            "is_followup_rewrite": False, "intent": None, "prior_resolved": None,
            "rephrased": False, "pre_rephrase_question": None}


def _turn_ctx_state(session: "Session | None") -> "ConversationState | None":
    return (session.state if (session is not None and settings.CONTEXT_LAYER_ENABLED
                              and settings.CONTEXT_STATE_ENABLED) else None)


def _with_rewritten_question(result: dict, question: str, raw_question: str) -> dict:
    """A DATA result carries the standalone question it was answered as."""
    if question != raw_question:
        result["rewritten_question"] = question
    return result


def _mark_context_dependent(result: dict, session, *, raw_question, followup, plan, scope_resumed,
                            inherited: bool = False) -> None:
    """WI-5 (forward plan, 2026-10-16): an answer built from THIS conversation —
    a follow-up rewrite, a merge plan, a resumed pause, or "the previous year"
    filled from the session — means something only here. Marked
    `context_dependent`, the router never writes it to the shared caches under
    the raw words another user may type. `inherited` (D-056, 2026-10-21): the
    chat's place / year seeded the resolver, or an answer default (all of
    Meghalaya / all years) filled a gap — cached under the bare words, a NEW
    chat typing them would skip its scheme / district / year questions."""
    ctx = (getattr(session, "turn_context", None) or {}) if session is not None else {}
    sub = ctx.get("substituted_question")
    if followup or plan or scope_resumed or inherited or (sub and sub != raw_question):
        result["context_dependent"] = True
    # A restored earlier question ran in place of the typed "go back to the
    # first question": it is the turn's question, or the next follow-up has
    # nothing to build on ("Boldoreng" then lost the measure; live 2026-10-21).
    restored = ctx.get("restored_question")
    if isinstance(restored, str) and restored:
        result["context_dependent"] = True
        if not result.get("rewritten_question"):
            result["rewritten_question"] = restored


def _scope_banner_place(resolved: dict) -> str:
    # A village known only by its code is named from the village index: the
    # banner said "All of Meghalaya" over a Rasong village answer (KI-348).
    if not resolved.get("village") and resolved.get("village_code"):
        from app import entity_resolver as _er
        _vn = _er.village_code_name(resolved["village_code"])
        if _vn:
            return f"{_vn} village"
    for key in ("village", "block", "assembly_constituency", "district"):
        if resolved.get(key):
            name = str(resolved[key]).title()
            return f"{name} constituency" if key == "assembly_constituency" else name
    for key in ("village_code_list", "block_list", "district_list"):
        vals = [str(v).title() for v in (resolved.get(key) or []) if v]
        if vals:
            return ", ".join(vals[:3]) + (f" +{len(vals) - 3}" if len(vals) > 3 else "")
    return "All of Meghalaya"


def _scope_banner_year(resolved: dict) -> "str | None":
    years = [resolved["year_key"]] if resolved.get("year_key") is not None else list(resolved.get("year_key_list") or [])
    out = []
    for y in years:
        try:
            out.append(f"FY {int(y)}-{str(int(y) + 1)[-2:]}")
        except (TypeError, ValueError):
            continue
    return ", ".join(out) or None


def _attach_scope_banner(result: dict, session) -> None:
    """The scope a DATA answer actually used, shown above it (Context Memory
    proposal S2, 2026-10-18): "MGNREGA · East Khasi Hills · FY 2022-23". Built
    from the result's own schemes and resolved entities — what the SQL ran
    with — never from model text, so a wrong inherited scheme, place or year
    is visible at once. "(from earlier)" when the scope was restored from an
    earlier question (topic_memory ledger)."""
    if result.get("route") != "data" or not result.get("schemes") or not (result.get("sql") or result.get("sql_query")):
        return
    resolved = result.get("resolved_entities") or {}
    # H-7 (chat UI audit 2026-10-29): "MGNREGA + Focus Plus · FY 2023-24" over an
    # answer where only MGNREGA had figures read as if both were answered. The
    # schemes that returned figures are named; the others say "no data".
    named = list(result["schemes"])
    held = result.get("schemes_with_data")
    if isinstance(held, list) and held and set(held) != set(named):
        lead = " + ".join(s for s in named if s in held)
        lead += "".join(f" ({s}: no data)" for s in named if s not in held)
    else:
        lead = " + ".join(named)
    parts = [lead, _scope_banner_place(resolved)]
    year = _scope_banner_year(resolved)
    if year:
        parts.append(year)
    banner = " · ".join(parts)
    ctx = (getattr(session, "turn_context", None) or {}) if session is not None else {}
    if ctx.get("restored_question"):
        banner += " (from earlier)"
    elif ctx.get("new_question"):
        # D-061: a self-sufficient question set the chat's scope aside.
        banner += " (new question)"
    result["scope_banner"] = banner


def _reference_state(question: str, ctx_state):
    """The state "this year" / "last year" / "the previous year" are read
    against (WI-4): the session's on a follow-up; with no year for a standalone
    question that names its own scheme, which means the calendar's year."""
    if ctx_state is not None and not looks_like_followup(question) and _named_schemes(question):
        return dataclasses.replace(ctx_state, year=None)
    return ctx_state


async def _data_path_error_result(error: Exception, question: str, raw_question: str) -> dict:
    """What a failure on the DATA path becomes: the scope reply, a re-raise for
    the router (gateway / DB trouble), or the KB fallback. Called by the
    graph's DATA-node wrapper (pipeline_graph._observed)."""
    try:
        raise error
    except OutOfScope as e:
        logger.info("out of scope (%s) — returning Megh One AI scope reply", e)
        return _out_of_scope_result(question, raw_question)
    except (llm.ModelBusyError, asyncio.TimeoutError, httpx.TimeoutException,
            httpx.TransportError) as e:
        # The model gateway hiccuped (saturated slot, read timeout, connection
        # reset) part-way through the DATA path — this is NOT "the question can't
        # be answered from the data". Propagate it so the router returns a
        # 503/504 "busy, please retry" instead of the misleading "couldn't build
        # a working query" fallback below, which reads as if the question itself
        # were at fault.
        logger.warning("data path hit a transient gateway error (%s) — re-raising", e)
        raise
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code >= 500:
            logger.warning("data path hit gateway %s — re-raising", e.response.status_code)
            raise
        logger.warning("data path failed (%s) — trying KB fallback", e, exc_info=True)
        turn_trace.note_final_error(e)
        return _mark_failed_data_turn(await _data_path_kb_fallback(question), question, raw_question)
    except Exception as e:  # noqa: BLE001
        # megh_db unreachable anywhere on the DATA path (village lookup, SQL,
        # a recount): say so — the reference documents cannot answer a data
        # question, and "not in the reference material" read as if the figure
        # did not exist (KI-025).
        if db_is_connection_error(e):
            logger.warning("data path lost the database (%s) — re-raising", e)
            if isinstance(e, DatabaseUnavailableError):
                raise
            raise DatabaseUnavailableError(str(e)) from e
        logger.warning("data path failed (%s) — trying KB fallback", e, exc_info=True)
        # recorded so the audit tells this KB answer apart from a genuine one
        turn_trace.note_final_error(e)
        return _mark_failed_data_turn(await _data_path_kb_fallback(question), question, raw_question)


def _mark_failed_data_turn(result: dict, question: str, raw_question: str) -> dict:
    """A DATA turn that ended in the fallback still answered the STANDALONE
    question: record it as `rewritten_question`, so the next follow-up builds on
    it and not on the typed fragment (harness 2026-10-18: after a failed "why are
    you not giving me block wise?", "and 2022-23?" was rewritten as "Why are you
    not giving me block wise data … FY 2022-23?"), and flag it `answer_failed` so
    no apology preface is put in front of the failure text (_attach_preface)."""
    if isinstance(result, dict):
        if question and question != raw_question and not result.get("rewritten_question"):
            result["rewritten_question"] = question
        result["answer_failed"] = True
    return result


async def _turn_context_stage(t: dict, session: "Session | None" = None,
                              scope: "auth.UserScope | None" = None) -> "dict | None":
    """Spelling, dataset pin, turn facts, a pending pause's reply, and whether
    this message continues the conversation at all (graph: context)."""
    question = t["question"]
    # The village-name index the continuation check and the edge whitelist read
    # (entity_resolver.place_mentions; user report 2026-10-21, "in ambare
    # ading"). Loaded at startup; this only fills it if startup could not.
    from app import entity_resolver as _c14_er
    if not _c14_er.village_index_loaded():
        await _c14_er.load_village_names()
    # Topic memory (app/topic_memory.py): an explicit return to an earlier
    # topic ("go back to MGNREGA") puts that topic's state and last turn back
    # in place before anything below reads them; a bare one is answered here.
    # Every other message comes back unchanged.
    _topic = topic_memory.resolve_turn(session, question)
    if _topic.response is not None:
        return _topic.response
    if _topic.action in ("continue", "none"):
        # A reference back ("that figure you gave for the housing scheme") the
        # rules placed nowhere: the rewrite model picks one earlier question
        # from this conversation's ledger, or NONE / ASK (topic_memory Phase 4,
        # D-050). Only on such turns; otherwise this returns None at once.
        _picked = await topic_memory.resolve_reference(session, question)
        if _picked is not None:
            _topic = _picked
    question = _topic.question
    raw_question = question
    question = _normalize_rank_counts(
        _correct_fy_spacing(_correct_place_spelling(_correct_scheme_spelling(question))))
    # Computed early (moved ahead of the original follow-up step) so the step-0
    # edge check below can relax its whitelist gate for a plausible follow-up —
    # see edge.detect_edge_case's has_context param.
    prev = session.last_turn if session is not None else None
    # A bare "CM Elevate" in a thread already on one CM Elevate dataset stays on
    # that dataset — settled once, here. Outside such a thread the words decide,
    # or the data stage asks (_cm_elevate_dataset_pause). A DATA decision only:
    # the KNOWLEDGE route undoes it (see _unpin_cm_elevate).
    _cm_thread = _cm_thread_scheme(prev, _turn_ctx_state(session),
                                   getattr(session, "pending_scope_q", None) if session is not None else None)
    # KI-330: "now give me for cm elevate" after a Legacy answer is a switch to
    # the applications dataset. Not pinned here (the raw fragment must reach the
    # deterministic scheme swap); the follow-up pin below reads the switch.
    _cm_switch = _cm_switch_to_applications(question, _cm_thread)
    if _cm_switch:
        context_budget.log_decision("cm_dataset", rule="switch-from-legacy", scheme="CM Elevate")
        logger.info("CM Elevate named as a switch from a Legacy thread -> applications: %r", question)
        _pinned = question
    else:
        _pinned = _pin_cm_elevate_dataset(question, _cm_thread)
    _cm_pinned = _pinned != question
    question = _pinned
    scope_resumed = False
    _each_q = _each_scheme_in_cm_thread(question, session)
    if _each_q != question:
        # "each scheme" just gained "under CM Elevate": its money words must
        # still go to Legacy (D-064) — "total amount disbursed under each
        # scheme" after "What is CM-ELEVATE?" hit the not-held pause (2026-10-22).
        question = _pin_cm_elevate_dataset(_each_q, _cm_thread)
        _cm_pinned = _cm_pinned or question != _each_q
    has_antecedent = prev is not None and prev.route in _ANTECEDENT_ROUTES
    ctx_state = _turn_ctx_state(session)
    # Facts about this turn for provenance (context_manager.update_state):
    # the state before it, the previous question, and, set below, the pause
    # reply and the question after reference substitution. Never persisted.
    if session is not None:
        _before = session.state.to_dict()
        session.turn_context = {
            "state_before": {k: _before.get(k) for k in
                             ("scheme", "district", "block", "village", "year", "metric", "tranche")},
            "previous_question": getattr(prev, "question", "") or "",
            "clarification_reply": None,
            "substituted_question": None,
            # The full question a pause reply resumed into. If this turn pauses
            # AGAIN, the router remembers this instead of the raw reply: a typed
            # "Focus Plus" resumed the bank question, the area pause that
            # followed was remembered as "Focus Plus", and the typed "All of
            # Meghalaya" then ran as "Focus Plus, All of Meghalaya" — a scheme
            # overview (Focus Plus use-case QA 2026-09-27, FOCUS-029).
            "resumed_question": None,
            # KI-330: a bare "CM Elevate" named as a switch from a Legacy thread;
            # read by the follow-up stage's dataset pin (set above, before this reset).
            "cm_dataset_switch": "CM Elevate" if _cm_switch else None,
            # D-061: a topic picked ("go back to …", a chip of the "which topic?"
            # pause) or an earlier question restored — its words run in that
            # topic's context, so the vague-question pause must not ask again.
            "topic_switched": _topic.action in ("switch", "restore"),
            # The rewritten follow-up, as it stood before any pause (see step 1f).
            "standalone_question": None,
            # This turn runs in an earlier question's restored scope (the topic
            # ledger): the scope banner says "(from earlier)".
            # (the question it runs, which _mark_context_dependent records as the
            # turn's own).
            "restored_question": _topic.question if _topic.action == "restore" else None,
        }

    # 0a. Resuming a "which area / year?" pause — fold the user's free-text reply
    #     ("West Garo Hills 2023-24", "all of Meghalaya, all years") back into the
    #     question that triggered it. A reply that stands on its own as a fresh
    #     question, or an edge case like "thanks", is left alone; either way the
    #     pending state is consumed so it never leaks into a later turn.
    pending = getattr(session, "pending_scope_q", None) if session is not None else None
    _village_hint = getattr(session, "pending_village_hint", None) if session is not None else None
    _pending_rule = getattr(session, "pending_scope_rule", None) if session is not None else None
    _pending_options = getattr(session, "pending_scope_options", None) if session is not None else None
    # D-065: the kind of the question that paused (see Session.pending_turn_kind).
    _pending_kind = getattr(session, "pending_turn_kind", None) if pending else None
    if session is not None:
        session.pending_turn_kind = None
    # A tapped chip sends its own question. A long one (the "whole MAIRANG
    # constituency" chip) is not taken as a pick by _resume_option_pause, but it
    # is still the paused question answered, so it keeps that question's kind.
    _tapped_chip = any(isinstance(o, dict) and o.get("question")
                       and question.strip().rstrip(" ?.").lower() == str(o["question"]).strip().rstrip(" ?.").lower()
                       for o in (_pending_options or []))
    if pending and _pending_rule in SCHEME_PAUSE_RULES:
        # 0a'. A "which scheme?" / "which Focus?" pause. This is a scheme choice,
        #      not a scope fragment, so the scope merge below does not apply. A
        #      typed scheme name becomes the chip question it stands for; any
        #      other reply goes through untouched. scope_resumed stays False
        #      either way, because the chip path never set it: the resumed
        #      question may still need its own area/year pause.
        session.pending_scope_q = None
        session.pending_village_hint = None
        session.pending_scope_rule = None
        session.pending_scope_options = None
        _picked = _resume_scheme_pause(question, _pending_options)
        if _picked:
            logger.info("scheme clarification resumed from typed reply %r -> %r", question, _picked)
            session.turn_context["clarification_reply"] = question
            # The same CM Elevate dataset decision the chip's text gets at the top.
            question = _pin_cm_elevate_dataset(_picked)
            _cm_pinned = question != _picked
            session.turn_context["resumed_question"] = question
        pending = None
    _paused_state = None
    if pending and _pending_rule and _pending_rule not in SCOPE_MERGE_RULES:
        # 0a''. Any other pause that offered chips (_resume_option_pause). A
        #       typed pick becomes that chip's question. An unmatched reply
        #       that names no scheme continues the PAUSED question's scheme,
        #       not the last answered turn's (_paused_thread_antecedent).
        session.pending_scope_q = None
        session.pending_village_hint = None
        session.pending_scope_rule = None
        session.pending_scope_options = None
        _picked = _resume_option_pause(question, _pending_options)
        if _picked:
            logger.info("option clarification (%s) resumed from typed reply %r -> %r",
                        _pending_rule, question, _picked)
            context_budget.log_decision("pause_reply", rule=_pending_rule, resumed="option")
            session.turn_context["clarification_reply"] = question
            question = _pin_cm_elevate_dataset(_picked)
            _cm_pinned = question != _picked
            session.turn_context["resumed_question"] = question
        else:
            _stand_in = _paused_thread_antecedent(question, pending, prev, rule=_pending_rule)
            if _stand_in is not None:
                context_budget.log_decision("pause_reply", rule=_pending_rule,
                                            resumed="paused-thread", schemes=_stand_in.schemes)
                prev, has_antecedent = _stand_in, True
                _st = ctx_state
                _paused_state = ConversationState(
                    scheme=_stand_in.schemes[0],
                    district=getattr(_st, "district", None), block=getattr(_st, "block", None),
                    village=getattr(_st, "village", None), year=getattr(_st, "year", None),
                    year_all=bool(getattr(_st, "year_all", False)))
        pending = None
    if pending:
        session.pending_scope_q = None
        session.pending_village_hint = None
        session.pending_scope_rule = None
        session.pending_scope_options = None
        # A scope-pause reply is normally a bare fragment ("Ri Bhoi, 2023-24",
        # "wgh, 1999-20") with no scheme vocabulary of its own, so the edge
        # whitelist would tag it "off_topic" every time — do NOT use that as the
        # signal to drop the pause. Only a clearly conversational reply (a
        # greeting / thanks / goodbye / abuse) or a fresh standalone question
        # abandons it; everything else is merged back into the paused question.
        _edge_hit = edge.detect_edge_case(question)
        # "off_topic" is the whitelist gate mis-firing on a fragment with no
        # scheme words — NOT a reason to drop the pause. Any other edge verdict
        # (greeting / thanks / goodbye / abuse / "never mind") genuinely is.
        _bailed = bool(_edge_hit) and _edge_hit.get("type") != "off_topic"
        # A one-tap chip (year pause) sends the whole rewritten question, which
        # already begins with the paused stem — merging would just duplicate it
        # ("total expenditure for MGNREGA, total expenditure for MGNREGA for FY
        # 2023-24"). Detect that and pass the chip's question straight through.
        _stem = pending.rstrip(" ?.").lower()
        _is_chip_resume = question.strip().lower().startswith(_stem)
        _level_reply = (_c14_level_only_reply(question, _village_hint)
                        if _pending_rule == "entity-ambiguous" and _village_hint else None)
        _place_switch = (_c14_pause_place_switch(question, pending, _village_hint, ctx_state)
                         if _pending_rule == "entity-ambiguous" and _village_hint and not _bailed
                         and not _is_chip_resume and not _level_reply else None)
        if _is_chip_resume:
            scope_resumed = True
            logger.info("scope/year clarification resumed via full question -> %r", question)
        elif not _bailed and _level_reply:
            # "its block" to "“Dalu” corresponds to more than one village: …" is
            # the level chip the pause did not offer: the paused question with
            # that level stated (user, live 2026-10-21 18:37 — it went to the
            # documents and answered about "Dalu village", KI-347).
            question = _c14_restate_level(pending, _village_hint, _level_reply)
            scope_resumed = True
            context_budget.log_decision("pause_reply", rule=_pending_rule, resumed="level", level=_level_reply)
            logger.info("village pause resumed by a level reply -> %r", question)
        elif _place_switch:
            # Another place named instead of a pick: "Dugalgre" to "“Kotchugre”
            # corresponds to more than one village" is the paused question asked
            # for Dugalgre. Merged as a fragment with the old hint, it asked the
            # Kotchugre question again (live 2026-10-21, MGNREGA West Garo Hills).
            question, _village_hint = _place_switch, None
            scope_resumed = True
            context_budget.log_decision("pause_reply", rule=_pending_rule, resumed="other-place")
            logger.info("village pause answered with another place -> %r", question)
        elif not _bailed and _pending_rule == "year-not-specified" and _is_all_years_reply(question):
            # KI-324: a typed "all of them combined" / "all" / "combined" is the
            # "All financial years combined" chip, so it resumes with that chip's
            # exact text; merged as ", all of them combined" it re-asked the year.
            session.turn_context["clarification_reply"] = question
            question = f"{pending.rstrip(' ?.')} across all financial years"
            scope_resumed = True
            context_budget.log_decision("pause_reply", rule=_pending_rule, resumed="all-years")
            logger.info("year clarification answered all-years -> %r", question)
        elif not _bailed and _c14_pause_scheme_switch(question, pending, _pending_rule):
            # KI-405 (KI-223 back): "What about MGNREGA?" typed while "How many
            # PMAY-G beneficiaries are there?" waits for its area was glued onto
            # it ("How many PMAY-G beneficiaries are there, What about MGNREGA?")
            # and answered as a two-scheme figure (live suite scenario I,
            # 2026-10-24). A pure switch to another scheme is the paused question
            # asked for that scheme. Not a scope reply: scope_resumed stays False,
            # so the new scheme's question is asked its own area / year (D-053).
            _switched = _swap_scheme_in_question(pending, _c14_pause_scheme_switch(question, pending, _pending_rule))
            context_budget.log_decision("pause_reply", rule=_pending_rule, resumed="scheme-switch")
            logger.info("scope pause answered with a scheme switch %r -> %r", question, _switched)
            question = _pin_cm_elevate_dataset(_switched)
            _cm_pinned = question != _switched
            session.turn_context["resumed_question"] = question
        elif not _bailed and not _reply_abandons_scope_pause(question):
            session.turn_context["clarification_reply"] = question
            question = _merge_scope_reply(pending, question)
            scope_resumed = True
            logger.info("scope clarification resumed -> %r", question)
        elif not _bailed and _pending_rule == "year-not-specified" and _is_yearwise_reply(question):
            # "Show it year-wise" to "which financial year?" IS an answer: every
            # year, one row each. Read as a fresh imperative, it had nothing to
            # refer to ("I don't have an earlier answer"; General TC-022, test
            # run 2026-10-09).
            session.turn_context["clarification_reply"] = question
            question = f"{pending.rstrip(' ?.')}, year-wise for each financial year"
            scope_resumed = True
            context_budget.log_decision("pause_reply", rule=_pending_rule, resumed="year-wise")
            logger.info("year clarification answered year-wise -> %r", question)
        elif not _bailed and _pending_rule == "year-not-specified" \
                and _BACKREF_FOLLOWUP_MATCH.search(question):
            # "What was the total MGNREGA expenditure in ABAGRE?" paused for the
            # year; "How much of that was spent on materials?" skipped the year
            # and pointed back at the paused question. It used to be read as a
            # fresh question with nothing to refer to ("I don't have an earlier
            # answer"; General TC-022, test run 2026-10-06). The paused question is
            # what "that" means, and declining to pick a year reads as all years.
            from app.session_store import Turn
            _ps = sorted(_exact_schemes(pending)) or list(_infer_scheme_from_terms(pending) or [])
            prev = Turn(question=f"{pending.rstrip(' ?.')} across all financial years",
                        raw_question=pending, route="data", schemes=_ps,
                        resolved_entities={}, answer="")
            has_antecedent = True
            context_budget.log_decision("pause_reply", rule=_pending_rule, resumed="backref-followup",
                                        schemes=_ps)
            session.turn_context["antecedent_from_pause"] = True
            logger.info("year pause skipped by a follow-up on the paused question -> antecedent %r",
                        prev.question)
        elif not _bailed and _pending_rule in ("year-not-specified", "scope-not-specified") \
                and not _exact_schemes(question) \
                and set(_infer_scheme_from_terms(question) or []) <= (
                    set(_exact_schemes(pending)) or set(_infer_scheme_from_terms(pending) or [])) \
                and context_policy.continuation_signals(question):
            # A follow-up whose words belong to the paused question's OWN scheme
            # ("and how many completed?" after a PMAY-G pause) continues it too.
            # Audit 2026-10-19: "Total amount disbursed under CM Elevate Legacy in
            # East Garo Hills" paused for the year; "how many records is that?"
            # names no scheme of its own, so with no answered turn to lean on it
            # ran as a statewide all-schemes question. A follow-up that names no
            # scheme, typed while a pause waits, continues the PAUSED question —
            # its scheme and place — and declining to pick a year reads as all years.
            from app.session_store import Turn
            _ps = sorted(_exact_schemes(pending)) or list(_infer_scheme_from_terms(pending) or [])
            if _ps:
                prev = Turn(question=f"{pending.rstrip(' ?.')} across all financial years",
                            raw_question=pending, route="data", schemes=_ps,
                            resolved_entities={}, answer="")
                has_antecedent = True
                context_budget.log_decision("pause_reply", rule=_pending_rule, resumed="followup-on-paused",
                                            schemes=_ps)
                session.turn_context["antecedent_from_pause"] = True
                logger.info("pause skipped by a scheme-less follow-up -> antecedent %r", prev.question)
        if scope_resumed:
            # The pin above read the bare reply; the merged question is the paused
            # one, remembered unpinned. "How many applications have been sanctioned
            # under CM-ELEVATE?" (Legacy: sanction words, D-064) paused for the year;
            # "all of them combined" resumed it on the applications thread and
            # answered "8,840 sanctioned" from the applications data (true 2,820;
            # harness AC04c, 2026-10-22, once D-065 made the question ask its year).
            _repinned = _pin_cm_elevate_dataset(question, _cm_thread)
            _cm_pinned = _cm_pinned or _repinned != question
            question = _repinned
        if scope_resumed and not session.turn_context.get("clarification_reply"):
            session.turn_context["clarification_reply"] = question
        if scope_resumed:
            session.turn_context["resumed_question"] = question
    # D-065: a reply that resumed a pause (chip or typed pick) is the paused
    # question, so it keeps that question's kind (the follow-up stage reads it).
    if session is not None and _pending_kind and (session.turn_context.get("resumed_question") or _tapped_chip):
        session.turn_context["resumed_turn_kind"] = _pending_kind

    # 0-c. Does this message continue the conversation at all? A previous
    #      answer is context only for a message that shares something with it:
    #      scheme or measure words, a place, a year, a grouping, a reference into
    #      the result, a question about how a scheme works
    #      (context_policy.continuation_signals). "who is harshit" and "he is my
    #      collik remember" after a Focus Plus answer share nothing, yet were
    #      rewritten "…under Focus Plus" and answered from its reference docs
    #      (reported 2026-09-29): the edge whitelist was switched off by the mere
    #      existence of a previous answer, and looks_like_followup took any short
    #      anchorless message as a fragment. Without a signal, the message is a
    #      new question: the whitelist applies and no rewrite runs. A pause reply
    #      always continues its paused question.
    _signals = context_policy.continuation_signals(question) if has_antecedent else []
    has_context = has_antecedent and (bool(_signals) or scope_resumed)
    if session is not None:
        session.turn_context["continuation"] = _signals
    if has_antecedent and not has_context:
        context_budget.log_decision("continuation", continues=False, signals=[],
                                    previous_route=getattr(prev, "route", None))
    t.update(raw_question=raw_question, question=question, cm_pinned=_cm_pinned,
             scope_resumed=scope_resumed, prev=prev, village_hint=_village_hint,
             paused_state=_paused_state, signals=_signals, has_context=has_context)
    return None


# A canned conversational turn ("hi", "thanks", "who are you"): no request to
# judge, so the guardrail model call is skipped (it would only add latency).
_CONVERSATIONAL_EDGE = frozenset({"greeting", "thanks", "goodbye", "identity", "capability", "confused"})
# Edge's generic off-topic replies. An out-of-scope guardrail verdict replaces
# them with a more specific one ("I don't write Instagram posts"); every other
# edge reply (out-of-area, money advice, a loan request) is already specific.
_GENERIC_EDGE = frozenset({"off_topic", "silly"})


def _strip_end_punct(name: str) -> str:
    """Whitespace runs -> one space, then trailing spaces and . , ; : ! ? dropped, upper-cased."""
    return collapse_ws(name or "").rstrip(" .,;:!?").upper()


def _c14_letter_words(text: str) -> "list[str]":
    """Every run of ASCII letters and ( ) . ' - that starts with a letter."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isascii() and ch.isalpha():
            j = i + 1
            while j < n and ((text[j].isascii() and text[j].isalpha()) or text[j] in "().'-"):
                j += 1
            out.append(text[i:j])
            i = j
        else:
            i += 1
    return out


def _c14_ascii_bounded_sub(needle: str, repl: str, text: str) -> str:
    """Replace each `needle` (any case) not inside a longer run of ASCII letters/digits with repl."""
    if not needle:
        return text
    low, nd = text.lower(), needle.lower()
    if len(low) != len(text) or len(nd) != len(needle):
        low, nd = text, needle
    out, last, k = [], 0, low.find(nd)
    while k >= 0:
        e = k + len(nd)
        if not (k > 0 and _c1x_is_ascii_alnum(text[k - 1])) and not (e < len(text) and _c1x_is_ascii_alnum(text[e])):
            out.append(text[last:k])
            out.append(repl)
            last = e
            k = low.find(nd, e)
        else:
            k = low.find(nd, k + 1)
    out.append(text[last:])
    return "".join(out)


_VILLAGE_KEY_CACHE: "dict[int, frozenset]" = {}


def _village_name_keys(names: dict) -> frozenset:
    """The catalogue's village names compared without trailing punctuation."""
    k = id(names)
    if k not in _VILLAGE_KEY_CACHE:
        _VILLAGE_KEY_CACHE.clear()
        _VILLAGE_KEY_CACHE[k] = frozenset(_strip_end_punct(n) for n in names)
    return _VILLAGE_KEY_CACHE[k]


async def _mask_village_names(text: str) -> str:
    """`text` with an exact village name (the longest one found) replaced by
    "the village", for the guardrail checks only."""
    out = text or ""
    found = None
    # Every scheme's villages, not MGNREGA's only: the Focus Legacy village "CHOKCHAKIA"
    # was refused as violence ("chok…") — Focus Legacy all-villages run 2026-10-12.
    for _vs in ("MGNREGA", "Focus Legacy", "PMAY-G", "Focus Plus", "CM Elevate", "CM Elevate Legacy"):
        try:
            found = await _scan_village_in_question(out, _vs)
        except Exception:  # noqa: BLE001 — no catalogue: check the text as typed
            found = None
        if found and found[0]:
            break
    if not (found and found[0]):
        # The scan above reads only after a place preposition ("in", "for"); "mapped to
        # CHOKCHAKIA village" has none. Any 1-4 word run that IS a scheme's village name.
        words = _c14_letter_words(out)
        runs = [" ".join(words[i:i + n]) for n in (4, 3, 2, 1) for i in range(len(words) - n + 1)]
        runs = [r for r in runs if len(r) >= 5 and r.lower() not in _NOT_A_PLACE_WORD]
        for _vs in ("MGNREGA", "Focus Legacy", "PMAY-G", "Focus Plus", "CM Elevate", "CM Elevate Legacy"):
            try:
                _names = await _scheme_village_names(_vs)
            except Exception:  # noqa: BLE001
                continue
            _hit = next((r for r in runs if r.strip().upper() in _names), None)
            if _hit:
                found = (_hit, [])
                break
    if found and found[0]:
        out = _c1x_loose_sub(found[0], "the village", out)
    # Block / district / constituency names too: "Give me the PMAY financial
    # summary for Chokpot" was refused as violence ("chok…"), PMAY-G sheet run
    # 2026-10-10.
    for _dim, _word in (("block", "the block"), ("assembly_constituency", "the constituency"),
                        ("district", "the district")):
        for _ in range(3):
            try:
                _nm = _canonical_in_question(out, "MGNREGA", _dim)
            except Exception:  # noqa: BLE001
                _nm = None
            if not _nm:
                break
            out = _c14_ascii_bounded_sub(_nm, _word, out)
    return out


_HARM_EDGE_TYPES = frozenset(guardrails.HARM_CATEGORIES) | {"harmful", "unsafe"}


async def _harm_only_from_place_name(question: str, hit: dict) -> bool:
    """True when an edge HARM verdict disappears once the place names are masked:
    "Chokpot" (a block) tripped the violence rules on "chok…" in the edge re-checks
    after the guardrail stage had already cleared the masked text (PMAY-G sheet
    run 2026-10-10)."""
    if (hit or {}).get("type") not in _HARM_EDGE_TYPES:
        return False
    masked = await _mask_village_names(question)
    return masked != question and not edge.detect_harmful(masked)


async def _guardrail_check(raw_question: str, question: str, scope_resumed: bool,
                           has_context: bool = False,
                           session: "Session | None" = None) -> "tuple[dict, str] | None":
    """The guardrail refusal for this turn and the layer that made it, or None
    (app/guardrails.py, D-040 / D-041)."""
    _plan_question = question   # unmasked, for the query plan below
    # A village NAME is not intent: "Give me the expenditure breakdown for CHOTTA
    # KILLING during 2023-24" was refused as violence (MGNREGA all-villages run,
    # 2026-10-09). An exact village name is masked for the checks; any harmful
    # wording around it is still judged.
    _names_place = _names_place_only(raw_question)
    raw_question = await _mask_village_names(raw_question)
    question = await _mask_village_names(question)
    harm = edge.detect_harmful(raw_question) or edge.detect_harmful(question)
    if harm:
        return harm, "rules"
    edge_hit = edge.detect_edge_case(raw_question)
    edge_type = (edge_hit or {}).get("type")
    scope_ok = edge_hit is None or edge_type in _GENERIC_EDGE
    scope = guardrails.check_scope_rules(raw_question) if scope_ok else None
    if scope:
        return edge.guardrail_reply(scope.category), "rules"
    if scope_resumed or edge_type in _CONVERSATIONAL_EDGE:
        return None
    # RAG plan E2 + E1 stage 2a (D-085): a new question's query plan starts here, so
    # its classifier call overlaps the guardrail's instead of following the answer.
    # Not for a follow-up: its words are rewritten later, the plan would read the
    # fragment. Not awaited; a refusal below cancels it (_turn_edge_stage).
    if not has_context:
        from app import query_plan as _c14_qp
        _c14_qp.start_for_turn(session, _plan_question)
    verdict = await guardrails.check_model(raw_question)
    if verdict and verdict.is_scope and (_names_place
                                         or _overrules_scope_verdict(raw_question, has_context)):
        context_budget.log_decision("guardrail", layer="model", outcome="scope_overruled",
                                    category=verdict.category)
        return None
    if verdict and (not verdict.is_scope or scope_ok):
        return edge.guardrail_reply(verdict.category), "model"
    return None


# A model OUT_OF_SCOPE verdict that is wrong by construction (General TC-011 /
# TC-012, test run 2026-10-09): "How do I get this?" was refused as "I can't do
# things on your behalf", "What is PM-KISAN?" got the generic off-topic reply
# and "Tell me about the Jal Jeevan Mission scheme" got "I don't write social
# media posts". How to get / apply for a scheme is the assistant's job (the
# guardrail prompt lists it as SAFE), and a scheme we don't hold has its own,
# clearer "not one of the schemes I cover" reply. Harm verdicts are never
# overruled — only scope ones.
_C14_HOWTO_LEAD = Seq(
    START, Opt(W("so", "ok", "okay", "and", "then")), "how",
    W("do", "can", "could", "should", "will", "would", "to"),
    Opt(Alt(W("i", "we", "one", "someone"), Seq("my", ANY, sep="space"))),
    Alt(W("get", "avail", "apply", "register", "join", "qualify", "receive"), W("enrol", prefix=True)),
    sep="space")
_C14_HOWTO_OBJECTS = (("this",), ("it",), ("that",), ("them",), ("these",), ("the", "scheme"),
                      ("the", "benefit"), ("the", "benefits"), ("the", "assistance"), ("the", "money"))


def _c14_howto_tail(rest: str) -> bool:
    r"""Up to 30 characters with no . ? !, then optionally a whole word this / it / that / them /
    these / the scheme / the benefit(s) / the assistance / the money, then only non-word
    characters to the end — on the text after the verb."""
    p = len(rest)
    while p > 0 and not _c1x_is_word_char(rest[p - 1]):
        p -= 1
    if p <= 30 and not any(ch in rest[:p] for ch in ".?!"):
        return True                                  # no object: everything up to the last word
    toks = _c1x_tokens(rest[:p])
    for obj in _C14_HOWTO_OBJECTS:
        if len(toks) < len(obj) or [t.low for t in toks[-len(obj):]] != list(obj):
            continue
        if len(obj) == 2 and not _c1x_ws(rest[toks[-2].end:toks[-1].start]):
            continue
        start = toks[-len(obj)].start
        if start > 0 and start <= 30 and not any(ch in rest[:start] for ch in ".?!"):
            return True
    return False


class _C14HowTo(_C1xLike):
    """The old _SCHEME_HOWTO_SHAPE check: the whole question is "(so/ok/and/then)
    how do/can/… (I/we/one/my X) get/apply/… [up to 30 more characters] (this /
    it / the scheme …)" and nothing but punctuation after."""

    def _hits(self, text):
        ctx = _C1xCtx(text)
        for j, _c in _C14_HOWTO_LEAD.ends(ctx, 0, ()):
            if j == 0:
                continue
            e = ctx.toks[j - 1].end
            if _c14_howto_tail(text[e:]):
                return [Hit(text, ctx.toks[0].start, len(text))]
        return []


_SCHEME_HOWTO_SHAPE = _C14HowTo()


_DATA_MEASURE_WORD = Matcher(Alt(
    W("expenditure", "spent", "breakdown", "household", "households", "person", "persons", "employment",
      "employed", "wage", "wages", "material", "materials", "house", "houses", "application", "applications",
      "payment", "payments", "amount", "percentage", "average", "highest", "lowest", "summary", "performance",
      "status", "completed", "released"),
    W("spend", "beneficiar", "sanction", "disburs", prefix=True),
    Joined("person", ("day", "days")),
    Seq(W("job"), _C1xGapIs(W("card", "cards"), _c1x_ws0)), W("jobcard", "jobcards"),
))
# "Which has more completed houses: DILBOT or UMKAIT?" names its places with no
# preposition (refused as a general question, PMAY-G sheet run 2026-10-10).
_COUNT_SHAPE_MATCH = Matcher(Alt(Seq("how", "many", sep="space"), Seq("number", "of", sep="space"),
                              Seq("count", "of", sep="space"), W("total")))


def _c14_compare_places_spans(text: str) -> list:
    r"""Two names joined by or / and / vs / versus after a colon, "compare" or "between":
    the first starts with a letter (as short as possible), the joiner is a whole word
    with spaces around it, and a letter follows; "compare" may be up to 60 characters back."""
    n = len(text)
    starts: list = []                     # (match start, first letter position)
    for i, ch in enumerate(text):
        if ch == ":":
            k = i + 1
            while k < n and text[k].isspace():
                k += 1
            starts.append((i, k))
    for t in _c1x_tokens(text):
        if t.low == "compare":
            for k in range(t.end + 1, min(t.end + 60, n) + 1):
                if "\n" in text[t.end:k]:
                    break
                if k < n and not _c1x_is_word_char(text[k - 1]):
                    starts.append((t.start, k))
        elif t.low == "between":
            k = t.end
            while k < n and text[k].isspace():
                k += 1
            if k > t.end:
                starts.append((t.start, k))
    for s0, k in sorted(starts):
        if not (k < n and text[k].isascii() and text[k].isalpha()):
            continue
        q = k + 1
        while True:
            # spaces, then or / and / vs / vs. / versus, spaces, then a letter, at q
            w0 = q
            while w0 < n and text[w0].isspace():
                w0 += 1
            if w0 > q:
                w1 = w0
                while w1 < n and _c1x_is_word_char(text[w1]):
                    w1 += 1
                word = text[w0:w1].lower()
                ends = []
                if word in ("or", "and", "versus", "vs"):
                    ends.append(w1)
                if word == "vs" and w1 < n and text[w1] == ".":
                    ends.insert(0, w1 + 1)
                for e in ends:
                    f = e
                    while f < n and text[f].isspace():
                        f += 1
                    if f > e and f < n and text[f].isascii() and text[f].isalpha():
                        return [(s0, f + 1)]
            if q < n and (_c1x_is_word_char(text[q]) or text[q] in "'() -"):
                q += 1
            else:
                break
    return []


_COMPARE_PLACES_MATCH = _C1xScan(_c14_compare_places_spans)
_C14_NOT_A_PLACE = frozenset("my your his her our their me us a an this that it them".split())


class _C14SlotWord(_C1xNode):
    r"""A word that starts with a letter, is at least two characters of word
    characters, ' and - , and is not a pronoun / article (my, your, …,
    them — see _C14_NOT_A_PLACE)."""

    def ends(self, ctx, i, caps):
        if i >= len(ctx.toks):
            return
        t = ctx.toks[i]
        if not (t.raw[0].isascii() and t.raw[0].isalpha()) or t.low in _C14_NOT_A_PLACE:
            return
        if len(t.raw) >= 2 or (t.end < len(ctx.text) and ctx.text[t.end] in "'-"):
            yield i + 1, caps


_PLACE_SLOT = Matcher(Seq(W("in", "for", "of", "at", "from"), Opt("the"), _C14SlotWord(), sep="space"))


def _is_data_shaped(question: str) -> bool:
    """A question or data request (by its opening words) with a measure plus a
    year or a place slot ("in <name>"): a figure question. "craft some lines for
    my page praising PMAY-G houses" opens with no question word and stays the
    model's call."""
    q = question or ""
    if not _REPHRASE_START.search(q):
        return False
    if not (_DATA_MEASURE_WORD.search(q) or context_policy.metric_families(q)):
        return False
    return bool(context_policy.extract_year_keys(q) or named_places(q) or _PLACE_SLOT.search(q)
                or _COMPARE_PLACES_MATCH.search(q)
                # a count over a named scheme / programme: "How many applicants under Meghalaya
                # Dairy Development Scheme belong to Piggery sector?" (CM Elevate sheet 2026-10-10)
                or (_COUNT_SHAPE_MATCH.search(q) and (_named_schemes(q) or _infer_scheme_from_terms(q))))


_SCHEME_DATA_NOUN_MATCH = Matcher(Alt(
    W("remit", "disburs", "beneficiar", prefix=True),
    Seq("producer", W("group", "groups"), sep="space"),
    W("pg", "pgs", "member", "members", "membership", "memberships", "payment", "payments", "applicant", "applicants"),
))
# A message about the PREVIOUS answer — questioning it, asking to re-check or
# correct it — is a follow-up, not a request to act for the officer: "Okay,
# MGNREGA in the above query, whatever you have given … only one year … in our
# database it is coming three years … Please cross verify and give it to me"
# was refused by the guardrail model as "I can't do things on your behalf"
# (UI 2026-10-12). Content / task requests are still caught by
# check_scope_rules first, and harm verdicts are never overruled.
def _c14_lead_then(lead: str, *stems: str):
    r"""lead, then at most one space or hyphen, then a word starting with a stem — "cross-check", "cross check", "crosscheck…"."""
    return Alt(Seq(W(lead), _C1xGapIs(W(*stems, prefix=True), _c1x_ws_or_dash0)),
               W(*[lead + st for st in stems], prefix=True))


_ABOUT_PREVIOUS_ANSWER = Matcher(Alt(
    Seq(W("above", "previous", "last", "earlier", "that", "this", "your", "same"),
        W("query", "queries", "question", "answer", "result", "results", "reply", "response", "output", "table",
          "chart", "figure", "figures", "number", "numbers", "data", "count", "total"), sep="space"),
    Seq("you", Opt(W("have", "had", "just")),
        W("gave", "given", "give", "showed", "shown", "said", "told", "returned", "provided"), sep="space"),
    _c14_lead_then("cross", "verify", "check"), _c14_lead_then("re", "check", "verify"),
    _c14_lead_then("double", "check"),
    Seq("check", Opt(W("it", "this", "that", "them")), "again", sep="space"), W("verify"),
    W("wrong", "incorrect"), W("mismatch", prefix=True),
    Seq("not", W("correct", "right", "matching", "tallying"), sep="space"),
    Seq("why", Opt(W("are", "is", "did")), Opt("you"), W("giving", "showing", "only", "missing", "not"), sep="space"),
))


_SCHEME_SUMMARY_MATCH = Matcher(W("overview", "summary", "summarise", "summarize", "summaryse", "summaryze",
                                "briefing"))
def _overview_names_a_place(question: str) -> bool:
    """An "in / of / for <name>" slot left once the scheme names are removed: the
    overview is of a place ("overview of Ri Bhoi"), a figures request (D-052)."""
    q = question or ""
    for pat in _SCHEME_NAME_MATCHER.values():
        q = pat.sub(" ", q)
    q = _C14_OFFICIAL_USE.sub(" ", q)          # "for an official briefing" is no place
    return bool(_PLACE_SLOT.search(_KNOWLEDGE_HINTS.sub(" ", q)))


_C14_OFFICIAL_USE = Matcher(Seq(Opt(W("an", "a", "the", "my", "our")), Opt(W("official", "formal", "internal")),
                                W("briefing", "briefings", "brief", "note", "meeting", "presentation", "report")))


# Words that make an overview a FIGURES request (see the KI-382 route rule).
_C14_FIGURE_WORDS = Matcher(W("performance", "progress", "status", "figure", "figures", "financial", "pendency",
                              "expenditure", "data", "numbers", "statistics", "stats", "achievement",
                              "achievements", "district", "districts", "block", "blocks", "village", "villages",
                              "wise", "year", "years", "fy"))
_C14_FOCUS_WORD = Matcher(W("focus"))
_C14_COHORT_WORD = Matcher(W("batch", "batches", "cohort", "cohorts"))


_C14_LEVEL_REPLY_WORDS = {"BLOCK": "block", "VILLAGE": "village", "CONSTITUENCY": "assembly_constituency",
                          "AC": "assembly_constituency", "DISTRICT": "district"}
_C14_LEVEL_REPLY_FILLER = frozenset("IT ITS S IS A AN THE NO NOT I MEAN MEANT SAID THAT THIS ONE OK OKAY "
                                    "PLEASE PLS YES ITSELF C RD CD WAS".split())


def _c14_level_only_reply(reply: str, name: str) -> "str | None":
    """The level a reply to a village pause states and nothing else ("its block",
    "it's a block", "Dalu is the block", "constituency"), or None. Not
    entity_resolver.fold_words: fold() strips a trailing "BLOCK" as a qualifier."""
    def _words(text: str) -> list:
        return "".join(c if c.isalnum() else " " for c in (text or "").upper()).split()
    own = set(_words(name))
    words = [w for w in _words(reply) if w not in _C14_LEVEL_REPLY_FILLER and w not in own]
    if len(words) != 1:
        return None
    return _C14_LEVEL_REPLY_WORDS.get(words[0])


def _c14_restate_level(paused: str, name: str, level: str) -> str:
    """The paused question with `level` stated for `name`, as the level chip
    states it; a level word the question put after the name goes."""
    stem = paused.strip().rstrip(" ?.")
    p0 = _ci_find(stem, name)
    if p0 >= 0:
        end = p0 + len(name)
        tail = stem[end:]
        nxt = tail.lstrip().split(" ", 1)[0].strip(",.").upper()
        if nxt in _C14_LEVEL_REPLY_WORDS:
            cut = len(tail) - len(tail.lstrip()) + len(tail.lstrip().split(" ", 1)[0])
            stem = stem[:end] + tail[cut:]
    return f"{stem}, the {_DIM_CHIP_WORD[level]}, not another area type"


# KI-405: the pauses a typed scheme switch can answer — "which area?" / "which year?".
_C14_SWITCHABLE_PAUSES = frozenset({"scope-not-specified", "year-not-specified"})


def _c14_pause_scheme_switch(reply: str, paused: str, rule: "str | None") -> "str | None":
    """The scheme a reply to a "which area / year?" pause switches the paused
    question to ("What about MGNREGA?", "same for Focus Plus"), else None. Only a
    PURE switch (it says nothing else) to a scheme the paused question is not
    about; a bare "Focus" is left to the which-Focus rule as before."""
    if rule not in _C14_SWITCHABLE_PAUSES:
        return None
    target, pure = _scheme_substitution(reply)
    if not target or not pure or target == "Focus":
        return None
    paused_schemes = set(_exact_schemes(paused or "")) or set(_infer_scheme_from_terms(paused or "") or [])
    if not paused_schemes or target in paused_schemes:
        return None
    return target


def _c14_pause_place_switch(reply: str, paused: str, name: str, state) -> "str | None":
    """The paused question asked for the ONE other place `reply` names, or None.
    None for a reply that picks among the villages called `name`: the name
    itself, a district, or the block / district one of them lies in."""
    from app.entity_resolver import fold_words, place_only, village_places
    from app.session_store import Turn
    only = place_only(reply, _C01_PLACE_ONLY_WORDS)
    if not only or only[1] == "district" or fold_words(only[0]) == fold_words(name):
        return None
    if only[0].upper() in {lv for _c, b, d in village_places(name) for lv in (b, d)}:
        return None
    schemes = sorted(_exact_schemes(paused)) or ([state.scheme] if getattr(state, "scheme", None) else [])
    district = getattr(state, "district", None)
    prev = Turn(question=paused, raw_question=paused, route="data", schemes=schemes,
                resolved_entities={"district": district} if district else {})
    return _place_swap_rewrite(prev, reply, force=True)


def _names_place_only(question: str) -> bool:
    """A short message (six words or fewer) that names a Meghalaya place — a
    district, block, constituency or village, with or without the level word
    (entity_resolver.place_mentions). "ambare ading" in a new chat was refused by
    the guardrail model as a general question (user report 2026-10-21): it is a
    place question, and the pipeline asks for the scheme. Read on the text as
    typed, before _mask_village_names turns the name into "the village"."""
    q = question or ""
    if len(q.split()) > 6 or guardrails.check_scope_rules(q):
        return False
    try:
        from app.entity_resolver import place_mentions
        return bool(place_mentions(q))
    except Exception:  # noqa: BLE001 — no index: the model's verdict stands
        return False


def _overrules_scope_verdict(question: str, has_context: bool = False) -> bool:
    q = question or ""
    if guardrails.check_scope_rules(q):
        return False                          # a clear rule phrasing ("apply for me") stands
    if _SCHEME_HOWTO_SHAPE.search(q) or _unsupported_scheme_named(q):
        return True
    # A figure question about a place or a year is the assistant's job however the
    # model reads an unfamiliar village name: "Give me the expenditure breakdown
    # for Myriem during 2023-24" was refused as "I can't do things on your behalf",
    # "What was the total expenditure in MAWJYRSIM during 2022-23?" as a general
    # question (MGNREGA sheet run 2026-10-09, 9 cases). Content / task requests in
    # scheme words are still caught by check_scope_rules above.
    if _is_data_shaped(q):
        return True
    # A Focus Plus batch is a data slot like a place or a year: "Give me the status
    # breakdown for 12.5K batch." was refused 5/5 as "I can't do things on your
    # behalf … make payments", "Give me the status split of 12.5K batch" as a
    # general question, while "… for THE 12.5K batch" passed (_PLACE_SLOT needs a
    # word starting with a letter) — FOCUS-019 re-test 2026-10-22, KI-360. "12.5K"
    # alone is also an amount ("book a payment of 12.5K" stays the model's call),
    # so it must be named a batch / cohort, or the question a status breakdown.
    if _FOCUSPLUS_BATCH_WORD.search(q) and (
            _FP_STATUS_BREAKDOWN_MATCH.search(q)
            or (_C14_COHORT_WORD.search(q) and (_DATA_MEASURE_WORD.search(q) or _SCHEME_DATA_NOUN_MATCH.search(q)))):
        return True
    # A request about a named scheme's own data or an overview of it: "Show me all FOCUS
    # remittances made between April and June 2025" (refused as acting on the user's
    # behalf), "List top 5 FOCUS PGs which has more than 20 members", "Give me a short
    # overview of FOCUS … for an official briefing" (refused as content writing) —
    # FOCUS sheet run 2026-10-12. Bare "FOCUS" counts as a scheme name here.
    if _REPHRASE_START.search(q) and (_named_schemes(q) or _infer_scheme_from_terms(q)
                                      or _C14_FOCUS_WORD.search(q)) \
            and (_SCHEME_DATA_NOUN_MATCH.search(q) or _SCHEME_SUMMARY_MATCH.search(q)):
        return True
    if _ABOUT_PREVIOUS_ANSWER.search(q) and (has_context or _named_schemes(q) or _infer_scheme_from_terms(q)):
        return True
    # A short fragment that continues a scheme answer ("And the lowest?" after
    # "Which year was the highest?") was refused as a general question (General
    # TC-022, test run 2026-10-09). has_context already requires a continuation
    # signal (context_policy.continuation_signals), so "who is harshit" after an
    # answer still gets the model's verdict.
    return has_context and len(q.split()) <= 6


async def _turn_edge_stage(t: dict, session: "Session | None" = None,
                           scope: "auth.UserScope | None" = None) -> "dict | None":
    """Harmful requests, definitions, scheme listing / pick, and the edge layer (graph: edge)."""
    question, raw_question = t["question"], t["raw_question"]
    scope_resumed, has_context = t["scope_resumed"], t["has_context"]
    # 0--. A request for help with something illegal ("i want to rob a bank,
    #      give me suggestions") is refused FIRST — before the recommendation /
    #      pick / listing steps below, any of which could otherwise claim it on a
    #      word like "suggestions" and answer with an unrelated scheme.
    #      The guardrails (app/guardrails.py) run here too: the harm rules on the
    #      typed text and on the routed one (a pause merge or a rewrite can
    #      assemble a harmful sentence), the out-of-scope rules ("write an
    #      Instagram post on MGNREGA"), then the model check on the typed text,
    #      which judges meaning rather than words. The model check is skipped for
    #      a pause reply ("2023", a chip) and for a canned conversational turn
    #      ("hi", "thanks"), neither of which can carry a new request.
    # A reply that resumed one of our own clarifications ("plus" to "which
    # Focus?", "legacy" to "which CM Elevate?") is on topic by construction: the
    # scope model judged the bare word "plus" off-topic (audit 2026-10-19). The
    # harm rules still run on it.
    _pause_reply = bool(session is not None and (getattr(session, "turn_context", None) or {}).get("clarification_reply"))
    _guard = await _guardrail_check(raw_question, question, scope_resumed or _pause_reply, has_context,
                                    session=session)
    if _guard:
        from app import query_plan as _c14_qp
        _c14_qp.cancel_for_turn(session)
        _harm, _layer = _guard
        context_budget.log_decision("guardrail", layer=_layer, category=_harm["type"], blocked=True)
        # "unverified" = refused only because the guardrail model was down (E2,
        # 2026-10-29): never written to the shared answer caches, or the same
        # question would still be refused after the model is back.
        return {"route": "edge", "intent": "EDGE", "confidence": "high",
                "answer": _harm["response"], "edge_type": _harm["type"],
                "suggestions": [], **_empty_data_fields(),
                **({"context_dependent": True} if _harm["type"] == "unverified" else {})}

    # 0-. "What is EKH?" / "MYLLIEM full form" — spell out a district or block
    #     straight from the resolver catalogue. Must run BEFORE the edge layer
    #     (which bounces a lone abbreviation as off-topic) and before routing
    #     (KNOWLEDGE / RAG has no glossary for these). Skipped on a scope-pause
    #     resume — that text is a merged fragment, never a definition request.
    if not scope_resumed:
        geo_def = _geo_definition_answer(question)
        if geo_def:
            if question != raw_question:
                geo_def["rewritten_question"] = question
            return geo_def

    # 0-a. "What schemes are available?" / "what's the difference between the
    #      schemes?" — answered directly (see _scheme_listing_answer /
    #      _scheme_comparison_answer) rather than falling through to RAG, which
    #      has no single document covering either and either over-elaborates on
    #      one scheme or says "not covered". Same scope-pause carve-out as above.
    # 0-b. Talking about the conversation itself (D-052): "what did you just tell
    #      me?", "can you explain this number?", "you are not understanding me",
    #      "what should I ask next?" are answered from the previous turn, before
    #      the edge banks read them as off-topic or confused. An aside: the
    #      topic goes on (conversation_layer.resume_after_small_talk). A
    #      correction / breakdown ("why are you not giving me district wise?")
    #      is the follow-up stage's (step 0h): it skips the why-choice /
    #      recommendation / listing answers below, which read "why … not" as a
    #      question about the bot's own choice (live probe 2026-10-18).
    _meta = None
    if not scope_resumed:
        _meta_reply = await _conversation_meta_answer(raw_question, t.get("prev"), session)
        if _meta_reply is not None:
            return _meta_reply
        # "Which years do you have for MGNREGA?" / "which districts can I see?" —
        # coverage, from the year registry and the officer's own scope (the
        # pipeline asked "which scheme?" or gave the capability paragraph).
        _cover = _coverage_answer(raw_question, t.get("prev"), scope)
        if _cover is not None:
            return _cover
        _meta = _meta_kind(raw_question, t.get("prev"))

    if not scope_resumed and _meta not in ("correction", "breakdown"):
        # "Pick any scheme and explain it" — checked FIRST: it is neither a
        # listing nor a follow-up, and must not reach the "which scheme?" pause
        # or the follow-up rewrite (which re-reads it against the last scheme).
        # "Why did you choose MGNREGA?" / "suggest a scheme that suits me" — a
        # question about the bot's own choice, and a recommendation ACROSS
        # schemes. Neither is in any one scheme's documents, so both are
        # answered here, before the knowledge route narrows to one scheme.
        explained = _why_choice_answer(question, session)
        if explained:
            return explained
        recommended = (_scheme_fit_check_answer(question)
                       or _scheme_recommendation_answer(question, session))
        if recommended:
            return recommended
        picked = await _scheme_pick_answer(question, session)
        if picked:
            return picked
        direct = (_scheme_listing_answer(question)
                  or _scheme_comparison_answer(question, _recent_compared_schemes(session)))
        if direct:
            if question != raw_question:
                direct["rewritten_question"] = question
            return direct

    # 0. Edge — greetings, identity, thanks, off-topic, abuse. Checked on the RAW
    #    text first: the follow-up heuristic treats any short anchorless phrase as
    #    a fragment, which would otherwise turn "hello" into a bogus follow-up.
    #    Skipped when we just merged a scope-pause reply: the merged text is a
    #    bare "<question>, <place>, <year>" fragment that the whitelist gate
    #    would wrongly flag as off-topic, and the conversational-reply case was
    #    already handled at the merge above.
    hit = None if scope_resumed else edge.detect_edge_case(question, has_context=has_context)
    if hit and await _mgnrega_village_not_out_of_area(question, hit):
        hit = None
    if hit and await _harm_only_from_place_name(question, hit):
        hit = None
    if hit:
        context_budget.log_decision("edge", edge_type=hit["type"], has_context=has_context)
        return {"route": "edge", "intent": "EDGE", "confidence": "high",
                "answer": hit["response"], "edge_type": hit["type"],
                "suggestions": hit.get("suggestions", []),
                **_empty_data_fields()}
    return None


async def _turn_followup_stage(t: dict, session: "Session | None" = None,
                               scope: "auth.UserScope | None" = None) -> "dict | None":
    """Reference substitution, the follow-up merge plan and rewrite, and the
    scheme / year hints (graph: followup)."""
    question, raw_question, prev = t["question"], t["raw_question"], t["prev"]
    scope_resumed, has_context, _signals = t["scope_resumed"], t["has_context"], t["signals"]
    _paused_state, _cm_pinned = t["paused_state"], t["cm_pinned"]
    ctx_state = _turn_ctx_state(session)
    # 0f. Deterministic reference resolution ("the previous year", "the
    #     current year", "the former/latter", "the other one", "both") against
    #     the session's structured conversation state — see
    #     context_manager.substitute_references. Runs before the follow-up
    #     detector so a bare "compare that with the previous year" already has
    #     a concrete year by the time it gets there. Ambiguous ("the other
    #     one" with no recorded comparison) reuses the existing clarification
    #     mechanism rather than guessing. Any other failure degrades to the
    #     question unchanged — the pre-existing follow-up path still runs.
    if not scope_resumed and ctx_state is not None:
        try:
            # WI-4 (forward plan, 2026-10-16): "this year" / "last year" take the
            # session's year only on a FOLLOW-UP. A standalone question that names
            # its own scheme ("PMAY-G houses sanctioned in Ri Bhoi this year?")
            # means the calendar's year — it was rewritten to the previous
            # topic's FY 2022-23. Its relative year is resolved later, as for a
            # first question.
            question = context_manager.substitute_references(question, _reference_state(question, ctx_state))
            if session is not None:
                session.turn_context["substituted_question"] = question
        except context_manager.AmbiguousReference as e:
            raise ClarificationNeeded(e.question, options=e.options, rule="entity-ambiguous")
        except Exception:  # noqa: BLE001
            logger.warning("context_manager.substitute_references failed — continuing unchanged",
                           exc_info=True)

    # 0g. "Show me the districts, I'll choose one" right after a data answer
    #     narrows THAT answer to a district the user picks: offer the districts
    #     as chips (_pick_district_clarification). Reported 2026-10-18: it was
    #     routed to the KB, which said the scheme documents hold no district list.
    if (not scope_resumed and prev is not None and getattr(prev, "route", None) == "data"
            and getattr(prev, "schemes", None) and _asks_to_pick_district(raw_question)
            and not set(context_policy._places(raw_question)) - {"MEGHALAYA"}
            and context_policy._schemes_named(raw_question) <= set(prev.schemes)):
        _pick = _pick_district_clarification(prev.question, list(prev.schemes),
                                             getattr(ctx_state, "district", None))
        if _pick is not None:
            context_budget.log_decision("followup", rewrite="pick-district", schemes=list(prev.schemes))
            if session is not None:
                # A typed district reply merges into the previous question.
                session.turn_context["standalone_question"] = _pick.stem
            raise _pick

    # 0h. A complaint that carries its correction (D-052): "that's wrong, I asked for
    #     completed houses" runs "completed houses" as the follow-up it is; "why are
    #     you not giving me district wise?" runs the previous question by district.
    #     The answer opens with an apology (_attach_preface, finalize). A complaint
    #     with no correction in it is answered in the edge stage ("misread").
    _meta_rewrite = False
    _rollup_plan = None
    # 0h-view. "pie chart" / "why are you giving a line chart?" / "a wide frame": the
    #     previous data question again, shown the way asked (_chart_view_question).
    if not scope_resumed and prev is not None and getattr(prev, "route", None) == "data":
        _view = _chart_view_question(raw_question, prev, list(session.turns or []) if session is not None else None)
        if _view is not None:
            question, _vpreface, _vwide = _view
            _meta_rewrite = True
            if session is not None:
                if _vpreface:
                    session.turn_context["answer_preface"] = _vpreface
                if _vwide:
                    session.turn_context["chart_wide"] = True
            context_budget.log_decision("followup", rewrite="chart-view", question=question)
    if (not _meta_rewrite and not scope_resumed and prev is not None
            and getattr(prev, "route", None) in _ANTECEDENT_ROUTES
            and _meta_kind(raw_question, prev) in ("correction", "breakdown")):
        _fix = _meta_question(raw_question, prev)
        if _fix is not None:
            question, _preface, _meta_rewrite = _fix
            if session is not None:
                session.turn_context["answer_preface"] = _preface
            context_budget.log_decision("followup", rewrite="meta-correction" if not _meta_rewrite
                                        else "meta-breakdown", question=question)
    # 0h''. "compare with pmay" after a single-scheme figure (D-052): a cross-scheme
    #       comparison in the same place and year (_compare_with_scheme_question),
    #       not a swap to the other scheme over all years (user report 2026-10-18).
    if not _meta_rewrite and not scope_resumed and prev is not None and getattr(prev, "route", None) == "data":
        _cmp = _compare_with_scheme_question(raw_question, prev)
        if _cmp is not None:
            question = _cmp
            _meta_rewrite = True
            context_budget.log_decision("followup", rewrite="compare-with-scheme", question=question)
    # 0h'. Roll-up (E3, D-052): "back to the district level" / "and statewide?"
    #      names no place, so the previous question is rolled up from its own
    #      entities (block -> parent district, village -> block, -> state);
    #      the model rewrite kept the block filter and labelled it the district.
    if (not _meta_rewrite and not scope_resumed and prev is not None
            and getattr(prev, "route", None) == "data"):
        _ru = _rollup_question(raw_question, prev, list(session.turns or []) if session is not None else None,
                               session)
        if _ru is not None:
            question, _level, _rollup_plan = _ru
            _meta_rewrite = True
            if session is not None:
                session.turn_context["plan"] = _rollup_plan.to_dict()
            context_budget.log_decision("followup", rewrite=f"rollup-{_level}", question=question,
                                        actions=dict(_rollup_plan.actions))

    # 1. Follow-up — rewrite a fragment ("what about EGH?") to a standalone
    #    question using the previous turn, before routing. Only when the previous
    #    turn was an actual scheme answer; otherwise the fragment has nothing
    #    coherent to attach to. (prev / has_antecedent computed above, ahead of
    #    the step-0 edge check.)
    is_followup_rewrite = False
    # A roll-up's plan (step 0h') clears the levels rolled past; it must reach
    # the data-context stage, which otherwise inherits the block from the
    # previous turn (prior_resolved) under the rolled-up question.
    _plan = _rollup_plan
    # Which conversation thread a follow-up continues (see _followup_thread_state).
    _thread_state = _followup_thread_state(question, prev, ctx_state)
    if _paused_state is not None:
        # A reply to a pause about another scheme continues that scheme's thread
        # (step 0a''), with the scope the paused question carried.
        _thread_state = _paused_state
    if _thread_state is not ctx_state:
        context_budget.log_decision("followup", thread="antecedent-scheme",
                                    scheme=getattr(_thread_state, "scheme", None))
    # 0i. "compare with last year" with no year in play (D-052): nothing to count
    #     back from, so ask which years — the scheme's own FYs as chips
    #     (_relative_year_clarification). A typed year merges back into the stem.
    if not scope_resumed and prev is not None and getattr(prev, "route", None) == "data":
        _ry = _relative_year_clarification(raw_question, prev, _thread_state)
        if _ry is not None:
            context_budget.log_decision("followup", pause="relative-year-no-anchor")
            if session is not None:
                session.turn_context["standalone_question"] = _ry.stem
            raise _ry
    # A bare "Focus" used as a scheme name is never handed to the model rewrite:
    # the which-Focus question below must ask (CLAUDE.md §4 — never guessed).
    # The deterministic scheme swap ("for focus", "same for focus") keeps the
    # word "Focus" itself, so it still runs.
    _bare_focus = (_names_bare_focus_scheme(question)
                   and not _SCHEME_SWAP_FOLLOWUP.match(question.strip())
                   and not _scheme_substitution(question)[1])
    if _bare_focus:
        context_budget.log_decision("followup", skipped="bare-focus-scheme-name")
    _term_question = _is_scheme_term_question(raw_question)
    if _term_question:
        context_budget.log_decision("followup", skipped="scheme-term-question")
    # D-061 (user addendum 2026-10-22, "New Question = New Answer"): decide what
    # kind of turn this is BEFORE any rewrite. A self-sufficient question (its own
    # scheme and measure, no reference cue) is never rewritten and inherits
    # nothing; a vague one with several topics open asks which (chips).
    # D-065 (user, 2026-10-22): a resumed pause keeps the kind of the question
    # the user typed. The chip text adds the scheme and the place level, so it
    # read as a new question ("… for mairang under CM Elevate Legacy, the
    # assembly constituency …") and dropped the chat's year for FY 2025-26.
    _resumed_kind = (session.turn_context or {}).get("resumed_turn_kind") if session is not None else None
    if _resumed_kind:
        _tk = context_policy.TurnKind(_resumed_kind, ("resumed-pause",), context_policy.asked_levels(raw_question))
    else:
        _tk = context_policy.turn_kind(raw_question) if (has_context and not scope_resumed) else None
    _standalone = _tk is not None and _tk.kind == context_policy.TURN_STANDALONE and not _meta_rewrite
    if _tk is not None:
        context_budget.log_decision("turn_kind", kind=_tk.kind, reasons=list(_tk.reasons),
                                    asked=list(_tk.asked), meta_rewrite=_meta_rewrite)
        if session is not None:
            session.turn_context["turn_kind"] = _tk.kind if not _meta_rewrite else context_policy.TURN_FOLLOWUP
            # "(new question)" on the banner: the chat had a scope and this turn
            # set it aside, so a wrong choice is visible at once.
            session.turn_context["new_question"] = bool(_standalone and getattr(ctx_state, "scheme", None))
        if _tk.kind == context_policy.TURN_VAGUE and not _meta_rewrite and not _resumed_kind \
                and not (session is not None and session.turn_context.get("topic_switched")):
            _ask = _vague_topic_clarification(raw_question, session)
            if _ask is not None:
                context_budget.log_decision("turn_kind", pause="which-topic",
                                            topics=[o["label"] for o in _ask.options])
                raise _ask
    if _meta_rewrite:
        # Already the standalone question (step 0h): no model rewrite needed.
        is_followup_rewrite = True
    elif (looks_like_followup(question) or is_scopeless_followup(question, prev)
            or is_scheme_substitution(question, prev)
            or pronoun_refers_to_previous_term(question, prev)
            # "what is the wage part of that?", "how much of that was …": a
            # back-reference into the previous (or paused) question is a
            # follow-up whatever its opening words (context audit 2026-10-19).
            or bool(_BACKREF_FOLLOWUP_MATCH.search(raw_question))) and not _bare_focus and not _term_question \
            and not _standalone:
        if has_context:
            # Field-by-field effect of this follow-up on the state (KEEP / REPLACE
            # / CLEAR / REQUIRE_CLARIFICATION) and its kind, which picks the
            # context layers the rewrite gets. Deterministic, no model call.
            try:
                _plan = context_policy.plan_state_merge(question, _thread_state, prev=prev,
                                                        is_followup=True)
                if session is not None:
                    session.turn_context["plan"] = _plan.to_dict()
            except Exception:  # noqa: BLE001 — no plan means the pre-plan behaviour
                logger.warning("context_policy.plan_state_merge failed — continuing without it",
                               exc_info=True)
                _plan = None
            context_budget.log_decision(
                "followup", signals=_signals, kind=_plan.kind if _plan else None,
                actions={k: v for k, v in (_plan.actions if _plan else {}).items()
                         if v != context_policy.KEEP})
            # "Which one?" with nothing to pick by: ask, never let the rewrite
            # guess an item (the plan marks it REQUIRE_CLARIFICATION). Not a
            # remembered pause: the reply is read as a question of its own.
            if _plan is not None and _plan.action("reference") == context_policy.REQUIRE_CLARIFICATION:
                raise ClarificationNeeded(
                    "Which one do you mean? Please name it — the district, block, village or "
                    "scheme — or ask the whole question, for example \"Which district had the "
                    "highest disbursement?\"", rule="reference-ambiguous")
            _extra_ctx = ""
            if settings.CONTEXT_LAYER_ENABLED and session is not None:
                try:
                    _extra_ctx = await context_manager.build_followup_context(
                        session, question,
                        state=_thread_state if _thread_state is not ctx_state else None)
                except Exception:  # noqa: BLE001
                    logger.warning("context_manager.build_followup_context failed — continuing without it",
                                   exc_info=True)
            _data_prev = _data_thread_antecedent(question, prev, session, _plan)
            if _data_prev is not None:
                prev = _data_prev
                context_budget.log_decision("followup", antecedent="last-data-turn",
                                            schemes=list(getattr(prev, "schemes", None) or []))
            _all_years_q = (_all_years_rewrite(getattr(prev, "question", "") or "")
                            if _plan is not None and _plan.action("year") == context_policy.CLEAR
                            and (_plan.reasons.get("year") or "").startswith("'all of them'") else None)
            if _all_years_q:
                question = _all_years_q
                context_budget.log_decision("followup", rewrite="deterministic-all-years")
            elif _measure_after_knowledge(question, prev):
                # After a KNOWLEDGE answer the only context is its scheme:
                # append it; the typed measure stays word for word.
                question = f"{question.strip().rstrip(' ?.')} under {prev.schemes[0]}?"
                context_budget.log_decision("followup", rewrite="deterministic-measure-after-knowledge",
                                            scheme=prev.schemes[0])
            elif _pure_measure_change(question, prev, _plan) and not (
                    session is not None and session.turn_context.get("antecedent_from_pause")):
                # (Not when the antecedent is a question still waiting for its year:
                # nothing was answered, so the state holds none of its place —
                # the model rewrite reads the place from that question's words.)
                # KI-334: only the measure changes, so the rewrite is the user's own
                # words plus the scope the chat is on. The 9B rewrite carried the old
                # measure along ("How many beneficiaries are there for PMAY-G houses
                # completed in Ri Bhoi…", live harness U6 2026-10-19), answering the
                # completed-houses figure again for a beneficiaries question.
                _sch = prev.schemes[0]
                # A question that names its own place keeps it alone: "Total
                # sanctioned amount in Rasong village" became "... in Rasong village
                # under PMAY-G in Rasong village in Mawkynrew block ..." (KI-348).
                from app.entity_resolver import place_mentions as _c14_pm
                question = (f"{question.strip().rstrip(' ?.')} under {_sch}"
                            f"{_swap_scope_phrase(_thread_state, _sch, prev, with_place=not _c14_pm(question))}?")
                context_budget.log_decision("followup", rewrite="deterministic-measure-change", scheme=_sch)
                logger.info("follow-up measure change -> %r", question)
            elif (_ranked_q := _ranking_followup_question(question, prev, _plan, _thread_state)) and not (
                    session is not None and session.turn_context.get("antecedent_from_pause")):
                question = _ranked_q
                context_budget.log_decision("followup", rewrite="deterministic-ranking", scheme=prev.schemes[0])
                logger.info("follow-up ranking -> %r", question)
            else:
                question = await rewrite_followup(question, prev, extra_context=_extra_ctx,
                                                  kind=_plan.kind if _plan else None,
                                                  cleared=_cleared_filters(_plan, prev, _thread_state))
            # The rewrite can introduce a bare "CM Elevate" ("give me for cm
            # elevate") — the same thread decision as above; outside a CM Elevate
            # thread the data stage asks which dataset.
            _cm_switch = (session.turn_context.get("cm_dataset_switch")
                          if session is not None and isinstance(getattr(session, "turn_context", None), dict) else None)
            _pinned = _pin_cm_elevate_dataset(question, _cm_switch or _cm_thread_scheme(prev, _thread_state))
            _cm_pinned = _pinned != question
            question = _pinned
            is_followup_rewrite = True
            # "Which year was the highest?" ranks the years: a year the rewrite
            # carried over from the previous turn would leave only that one
            # (see _WHICH_YEAR_CUE). A year the user typed is kept.
            if _WHICH_YEAR_CUE.search(raw_question):
                _no_year = _drop_inherited_time(question, raw_question)
                if _no_year != question:
                    context_budget.log_decision("followup", rewrite="which-year-drops-inherited-year")
                    question = _no_year
            # "give me for pmay" after MGNREGA person-days: PMAY-G has no
            # person-days. Offer PMAY-G's own measures for the same scope
            # instead of a query that cannot be built (_swap_measure_gap).
            _gap = _swap_measure_gap(raw_question, question, prev, _thread_state)
            if _gap is not None:
                context_budget.log_decision("followup", rewrite="swap-measure-unavailable",
                                            question=question)
                # Remembered as the pause's question (routers.query.pause_question):
                # the first offer is a real question in the new scheme with the
                # carried scope, so an unmatched typed reply ("houses completed
                # in West Garo Hills") is rewritten against IT, not against the
                # measure the new scheme does not hold.
                if session is not None:
                    session.turn_context["standalone_question"] = _gap.options[0]["question"]
                raise _gap
        elif _CONTEXTLESS_REF.search(_RELATIVE_THAT.sub(" ", question)) and not _mentions_scheme(question):
            # "how launched it?" with no prior scheme answer — don't guess.
            return {"route": "edge", "intent": "EDGE", "confidence": "high",
                    "edge_type": "confused",
                    "answer": ("I don't have an earlier answer to build on, so I'm not "
                               "sure what that refers to. Tell me the scheme — MGNREGA, "
                               "PMAY-G, Focus Plus, CM Elevate, Focus Legacy, or CM Elevate "
                               "Legacy — and what "
                               "you'd like to know."),
                    "suggestions": list(edge.STARTERS),
                    **_empty_data_fields()}

    # 1b. Re-check edge on the rewrite (cheap, and the rewrite can surface one).
    #     Same scope-resume carve-out as step 0.
    hit = None if scope_resumed else edge.detect_edge_case(question, has_context=has_context)
    if hit and await _mgnrega_village_not_out_of_area(question, hit):
        hit = None
    if hit and await _harm_only_from_place_name(question, hit):
        hit = None
    if hit:
        context_budget.log_decision("edge", edge_type=hit["type"], has_context=has_context,
                                    after_rewrite=True)
        return {"route": "edge", "intent": "EDGE", "confidence": "high",
                "answer": hit["response"], "edge_type": hit["type"],
                "suggestions": hit.get("suggestions", []),
                "rewritten_question": question if question != raw_question else None,
                **_empty_data_fields()}

    # 1f. A follow-up fragment that rewrote to a standalone question still
    #     naming no scheme (and no scheme-specific vocabulary of its own) gets
    #     the session's pinned scheme appended deterministically — see
    #     context_manager.inject_scheme_hint. Only for an actual continuation
    #     (is_followup_rewrite), never for a brand-new question: that case is
    #     deliberately left to the existing "which scheme?" pause below.
    if is_followup_rewrite and _thread_state is not None:
        try:
            question = context_manager.inject_scheme_hint(question, _thread_state)
        except Exception:  # noqa: BLE001
            logger.warning("context_manager.inject_scheme_hint failed — continuing unchanged",
                           exc_info=True)
        # "All financial years", once chosen, is a resolved time scope like a
        # year is (KI-030): carried into a follow-up that keeps the year, so the
        # year pause is not asked again.
        try:
            question = context_manager.inject_year_scope(
                question, _thread_state, _plan.action("year") if _plan else context_policy.KEEP)
        except Exception:  # noqa: BLE001
            logger.warning("context_manager.inject_year_scope failed — continuing unchanged",
                           exc_info=True)
    # The question as resolved so far (rewrite, scheme hint, year scope). If
    # this turn pauses, the router remembers THIS, not the typed fragment
    # (routers.query.pause_question). Live 2026-09-29: "give me beneficiaries"
    # was rewritten "…under CM Elevate Legacy", paused for the year, and the
    # typed "2024-25" merged into "give me beneficiaries, 2024-25" — no scheme,
    # so it needed a second model rewrite to find it again.
    if is_followup_rewrite and session is not None:
        session.turn_context["standalone_question"] = question
    t.update(question=question, prev=prev, cm_pinned=_cm_pinned, plan=_plan,
             thread_state=_thread_state, is_followup_rewrite=is_followup_rewrite)
    return None


async def _turn_rephrase_stage(t: dict, session: "Session | None" = None,
                               scope: "auth.UserScope | None" = None) -> None:
    """The query rephraser (graph: rephrase, D-037): a messy NEW question becomes
    one clean English question for every later stage. Skipped for a follow-up
    (the follow-up rewrite already made it standalone), a pause reply (a chip or
    "2023-24" must reach the merge exactly), and a question that already reads
    clean. Never ends the turn and never pauses."""
    question = t["question"]
    if (not settings.QUERY_REPHRASE_ENABLED or t["is_followup_rewrite"] or t["scope_resumed"]
            or (session is not None and (session.turn_context or {}).get("clarification_reply"))
            # A chip's own question is system-built and exact: "…in SEINDULI I …,
            # MAWSHYNRUT block, WEST KHASI HILLS" lost its " I" to the rephraser and
            # was answered for the whole block (PMAY-G all-villages run 2026-10-10).
            or _CHIP_SCOPE_SUFFIX_MATCH.search(question.strip().rstrip("?. ")) or _CHIP_LEVEL_PHRASE_MATCH.search(question)
            or not _needs_rephrase(question)):
        return None
    out = await rephrase_question(question)
    if out != question:
        t["pre_rephrase_question"], t["question"], t["rephrased"] = question, out, True
        if session is not None:
            # A pause on this turn remembers the clean question, so the reply
            # resumes it rather than the messy original (routers.query.pause_question).
            session.turn_context["standalone_question"] = out
    return None


# A question about a scheme's RULES that happens to say "how many" / "how much":
# "How many days of work are guaranteed?", "How are wages paid?", "How much
# assistance is given?". The DATA keywords won the split, so after "What is
# MGNREGA?" -> "Who can apply?" the third question asked "which scheme?" and the
# PMAY-G one asked for a district and year (General TC-010, test run
# 2026-10-09). It is an entitlement the reference docs state, not a figure in
# megh_db — unless a place, year, grouping or ranking makes it one ("how much
# assistance was given in Ri Bhoi in 2023-24?" stays DATA).
class _C14AheadToQuestionMark(_C1xNode):
    r"""Matches (consuming nothing) when `matcher` finds something between here and
    the next '?' — a look ahead for whole words, not crossing a '?'."""

    def __init__(self, matcher):
        self.matcher = matcher

    def ends(self, ctx, i, caps):
        start = ctx.toks[i - 1].end if i > 0 else 0
        region = ctx.text[start:]
        q = region.find("?")
        if q >= 0:
            region = region[:q]
        if self.matcher.search(region):
            yield i, caps


_C14_PAST_FIGURE_WORD = Matcher(Alt(W("disbursed", "sanctioned", "spent", "released"),
                                    Seq("paid", "out", sep="space")))
_ENTITLEMENT_QUESTION = Matcher(Alt(
    W("guarantee", "guaranteed", "guarantees", "entitled", "entitlement"),
    Seq("how", W("are", "is"), Opt("the"),
        W("wage", "wages", "payment", "payments", "money", "fund", "funds", "assistance", "subsidy", "subsidies",
          "benefit", "benefits", "instalment", "instalments", "installment", "installments"),
        W("paid", "given", "released", "transferred", "credited", "disbursed"), sep="space"),
    NotBefore(Seq("how", "much", Opt("financial"),
                  W("assistance", "subsidy", "money", "help", "support", "benefit", "amount", "wage", "wages", "loan"),
                  W("is", "are", "will", "would", "does", "do", "can", "could"), sep="space"),
              _C14AheadToQuestionMark(_C14_PAST_FIGURE_WORD)),
    Seq("wage", "rate", sep="space"),
    Seq(Seq("per", W("house", "household", "family", "member", "beneficiary", "unit", "day"), sep="space"),
        _C1xCharGap(forbid="?"), W("given", "provided", "paid", "get")),
))
_ENTITLEMENT_DATA_SIGNALS = frozenset({"place", "year", "group_by", "rank", "compare"})
# Figure summaries of a place (see the route stage): never a reference-docs question.
# (several of these words need no word end after them: they match as word starts)
_FIGURE_SUMMARY_MATCH = Matcher(Alt(
    Seq("financial", W("summary", "position", "status", "overview", prefix=True), sep="space"),
    W("performance", "pendency"),
    Seq("status", W("breakdown", prefix=True), sep="space"),            # also "house status breakdown"
    Seq("house", "status", sep="space"),
    Seq("expenditure", W("breakdown", prefix=True), sep="space"),
    Seq("breakdown", W("of", "for"), sep="space"),
    Seq("key", "figures", sep="space"),
    Seq("status", "distribution", sep="space"),
    # "tell me what is going on in my block" / "overview of Ri Bhoi": a figures
    # question about a place, not a rules question (live probe 2026-10-18, D-052).
    Seq("going", "on", sep="space"),
    W("overview", "situation", "progress"),
    Seq(W("status"), _C1xGapIs(W("wise"), lambda g: len(g) == 1 and (g.isspace() or g == "-"))),
))
_DEFINITION_ASK_MATCH = Matcher(Alt(
    W("mean", "define", "definition", prefix=True),                        # mean / means / meaning …
    Seq("explain", W("what", prefix=True), sep="space"),
    Seq("what", "is", W("a", "an"), sep="space"),
    Seq("what", "are", "the", W("stages", "categories", prefix=True), sep="space"),
))
_WHO_BENEFITS_MATCH = Matcher(Seq(
    START, _C1xGapIs(W("who"), _c1x_ws0), _C1xGapIs(W("are", "is", "can", "will", "should", "may"), _c1x_ws),
    _C1xCharGap(forbid="?"),
    Alt(W("beneficiar", "eligib", "benefit", "target", prefix=True), W("intended", "apply", "covered")),
))
_AREA_CHIP_MARKER_MATCH = Matcher(Seq(
    _C1xGapIs(W("the"), lambda g: g.rstrip().endswith(",")),
    Opt(Seq(W("c"), _C1xGapIs(W("rd"), lambda g: g == "&"))),
    Alt(W("block", "village", "district"), Seq("assembly", "constituency", sep="space")),
    sep="space"))
# A count of people or things is a figure even when it says "guaranteed":
# "how many households completed 100 days of guaranteed employment?".
_ENTITLEMENT_COUNT_VETO = Matcher(Alt(
    Seq("how", "many", Opt(ANY),
        Alt(W("household", "households", "person", "persons", "people", "worker", "workers", "families",
              "work", "works", "village", "villages", "block", "blocks", "district", "districts", "application",
              "applications", "applicant", "applicants", "house", "houses", "record", "records", "group", "groups",
              "member", "members", "farmer", "farmers", "jobcard", "jobcards"),
            Pred(lambda w: w.lower().startswith("beneficiar") and len(w) > len("beneficiar")),
            Seq(W("job"), _C1xGapIs(W("card", "cards"), _c1x_ws0))), sep="space"),
    W("completed", "total"),
    Seq("number", "of", sep="space"),
))
_C14_COUNT_WORDS = Matcher(Alt(Seq("how", "many", sep="space"), Seq("number", "of", sep="space"), W("count", "total")))
_C14_SCOPE_PREP = Matcher(W("across", "under", "in", "for"))


def _is_entitlement_question(question: str) -> bool:
    q = question or ""
    if not _ENTITLEMENT_QUESTION.search(q) or _ENTITLEMENT_COUNT_VETO.search(q):
        return False
    if named_places(q) or context_policy.extract_year_keys(q):
        return False
    signals = set(context_policy.continuation_signals(q))
    return not (signals & _ENTITLEMENT_DATA_SIGNALS)


async def _turn_route_stage(t: dict, session: "Session | None" = None,
                            scope: "auth.UserScope | None" = None) -> "dict | None":
    """Not-held checks, the village-name search and DATA / KNOWLEDGE (graph: route)."""
    question, raw_question = t["question"], t["raw_question"]
    is_followup_rewrite, _plan = t["is_followup_rewrite"], t["plan"]
    # 1c. Bank / financial-channel details are not held for any loaded scheme —
    #     say so, with the reason, before routing. Checked ahead of the DATA/
    #     KNOWLEDGE split: phrasing like "what is the bank-wise disbursement…"
    #     trips _KNOWLEDGE_HINTS on "what is" and would otherwise dead-end in
    #     RAG ("not covered in the reference material") instead of explaining
    #     that the column itself isn't queryable.
    # ...but "What is DBT?" asks what the term MEANS (a knowledge question the
    # scheme documents answer), not for bank data (user report 2026-10-14).
    if _BANK_REQUESTED.search(question) and not _is_scheme_term_question(raw_question):
        _clarification = _bank_clarification(question)
        if _clarification is not None:
            raise _clarification

    # 1d. Administrative expenditure is deliberately excluded from reporting for
    #     every scheme that has it (see _ADMIN_EXPENDITURE_REQUESTED above) —
    #     same reasoning and same place as the bank check just above.
    #     Except MGNREGA: its admin_total_exp column exists, and the use case
    #     (DATA-013) asks for the aggregate, so the DATA path reports the real
    #     recorded figure together with the "never populated at source" caveat
    #     (_mgnrega_admin_expenditure_answer). PMAY-G and the multi-scheme
    #     wording are unchanged.
    if _ADMIN_EXPENDITURE_REQUESTED.search(question) \
            and _named_or_inferred_schemes(question) != ["MGNREGA"]:
        raise _admin_expenditure_clarification(question)

    # 1d'. MGNREGA records actual expenditure only — no sanctioned amount or
    #      budget (mgnrega_classification_rules.yaml budget_vs_actual_requested).
    #      "Total sanctioned amount in Rasong" was answered from total_exp and
    #      called "sanctioned" (user, live 2026-10-21 19:44, KI-350).
    if _MG_SANCTION_REQUESTED.search(question) and _named_or_inferred_schemes(question) == ["MGNREGA"] \
            and not _is_scheme_term_question(raw_question):
        raise _mgnrega_sanction_clarification(question)

    # 1e. Named a scheme we simply don't hold ("PM-KISAN", "Ujjwala", "Jal
    #     Jeevan"). Checked HERE, before the DATA/KNOWLEDGE split, because the
    #     question is just as often a KNOWLEDGE one ("what is PM Kisan
    #     Yojana?") as a data one. The check used to live only inside
    #     the DATA path, so a knowledge-shaped ask sailed past it into RAG,
    #     found nothing — correctly, it isn't in the reference docs — and got
    #     the flat "I don't have information about that for MGNREGA, PMAY-G,
    #     Focus Plus or CM Elevate", which never says WHY or what to do next
    #     (reported 2026-09-18). The clarification below names the scheme the
    #     user asked for, says plainly that only four are loaded, and offers
    #     them as one-tap chips.
    _unsupported_named = _unsupported_scheme_named(question)
    if _unsupported_named:
        raise _unsupported_scheme_clarification(question, _unsupported_named)

    # 1g. "How many villages are named X?" / "which villages contain X in their
    #     name?" — an entity SEARCH. Answered before routing, so X is never
    #     narrowed to one resolved place first (see _village_name_search_answer).
    if _village_name_search(question):
        try:
            _vns = await _village_name_search_answer(question)
        except Exception as e:  # noqa: BLE001
            if db_is_connection_error(e):
                raise DatabaseUnavailableError(str(e)) from e
            logger.warning("village name search failed — routing normally", exc_info=True)
            _vns = None
        if _vns:
            if question != raw_question:
                _vns["rewritten_question"] = question
            return _vns

    # 1h. "Which financial years does PMAY-G have?" — the scheme's own data
    #     years (_scheme_years_answer). Checked before routing: "which years of
    #     data are available for PMAY-G?" was classified KNOWLEDGE and RAG said
    #     the reference material does not list them (2026-10-06).
    _years_schemes = [s for s in SCHEME_CATALOG if s in _exact_schemes(question)]
    if _years_schemes:
        _years = _scheme_years_answer(question, _years_schemes)
        if _years is not None:
            if question != raw_question:
                _years["rewritten_question"] = question
            return _years

    # 1i. "Tell me what is going on in my block" / "overview of Ri Bhoi" with one
    #     scheme and one place (D-052): the scheme's headline figures for that
    #     place, asked the way the pipeline already answers them
    #     (_overview_question). Data, no classifier call; the answer opens with
    #     "Here's an overview of …" (_attach_preface).
    _ov = _overview_question(question)
    if _ov is not None:
        question, _ov_preface = _ov
        t["question"] = question
        if session is not None:
            session.turn_context["answer_preface"] = _ov_preface
        context_budget.log_decision("route", rewrite="overview", question=question)
        context_budget.log_decision("intent", intent="DATA", followup=is_followup_rewrite,
                                    kind=_plan.kind if _plan else None,
                                    schemes_named=sorted(_named_schemes(question)))
        t["intent"] = "DATA"
        return None

    # 2. Route: number question or scheme-rules question? For a rewritten
    #    follow-up, the user's own words decide when they are decisive — the
    #    rewrite's phrasing ("What are the beneficiaries of…") must not turn a
    #    count request into a reference-docs question (live 2026-09-29).
    # A rephrased question is routed by the user's own words when those decide
    # it: the rephraser turned "Compare expenditure and person-days in Songsak
    # block during 2022-23" into "What is the comparison between…", whose "what
    # is" read as a reference-docs question (MGNREGA sheet DATA-029, 2026-10-09).
    intent = (_typed_intent(raw_question) if (is_followup_rewrite or question != raw_question) else None)
    if intent is None and not is_followup_rewrite and question != raw_question \
            and _KNOWLEDGE_HINTS.search(question) and not _KNOWLEDGE_HINTS.search(raw_question):
        # The rephrase brought in the knowledge cue: "Give me the overall PMAY
        # performance of East Khasi Hills" -> "What is the overall PMAY-G
        # performance…" went to the reference docs (PMAY-G sheet run 2026-10-10).
        # The user's own words are classified instead.
        intent = await classify_intent(raw_question)
    intent = intent or await classify_intent(question)
    if intent == "DATA" and _is_entitlement_question(raw_question):
        intent = "KNOWLEDGE"
    # "Who are the intended beneficiaries of CM-ELEVATE?" asks who the scheme is FOR, not
    # how many there are; it was answered "8,600 applicants" (CM Elevate Legacy sheet TC-03,
    # 2026-10-12). A count shape keeps it data.
    if intent == "DATA" and _WHO_BENEFITS_MATCH.search(raw_question) \
            and not _C14_COUNT_WORDS.search(raw_question):
        intent = "KNOWLEDGE"
    # "Give me a short overview of CM-ELEVATE that I can use for an official
    # briefing" is about the scheme, not its figures: the sampled classifier sent it
    # to DATA in 2 of 3 runs (dataset question, then Legacy totals — Legacy sheet
    # TC-09, 2026-10-22, KI-382). A place or a figure word keeps it data ("overview
    # of Ri Bhoi", "financial summary for Amlarem", D-052).
    _scheme_overview = bool(_OVERVIEW_REQUEST.search(raw_question)) \
        and not _C14_COUNT_WORDS.search(raw_question) and not _C14_FIGURE_WORDS.search(raw_question) \
        and not named_places(raw_question) and not _AREA_CHIP_MARKER_MATCH.search(raw_question) \
        and not _overview_names_a_place(raw_question)
    if intent == "DATA" and _scheme_overview:
        intent = "KNOWLEDGE"
    _no_scheme = question
    for _pat in _SCHEME_NAME_MATCHER.values():
        _no_scheme = _pat.sub(" ", _no_scheme)
    # (not for the scheme overview above: "overview of CM Elevate" names the scheme as
    # its scope and was sent straight back to DATA here)
    if intent == "KNOWLEDGE" and not _scheme_overview and _FIGURE_SUMMARY_MATCH.search(question) \
            and not _DEFINITION_ASK_MATCH.search(question) and (
            _AREA_CHIP_MARKER_MATCH.search(question) or named_places(question)
            or _PLACE_SLOT.search(_KNOWLEDGE_HINTS.sub(" ", _no_scheme))
            # "…status distribution across CM ELEVATE": the scheme itself is the scope
            or (_named_schemes(question) and _C14_SCOPE_PREP.search(question))):
        # A figure summary of a named place is data: the which-area chip for "Give
        # me the PMAY financial summary for Amlarem" carried the rephrased "What is
        # the PMAY-G financial summary for Amlarem, the block, …" and the reference
        # docs answered "no published summary" — 26 of 56 blocks (PMAY-G sheet
        # PMAY-OFF-012, run 2026-10-10).
        intent = "DATA"
    # A figure, ranking or comparison across two or more schemes is data: "What is
    # the coverage of NREGA, PMAY-G and Focus+ in Dadenggiri block?" and "… spending
    # in South Garo Hills, excluding CM-ELEVATE?" went to the reference documents
    # (cross-scheme UAT re-test 2026-10-22, T09.2 / T11.2 / T13.2, KI-388 / KI-391).
    if intent == "KNOWLEDGE" and not _DEFINITION_ASK_MATCH.search(raw_question) \
            and not _is_entitlement_question(raw_question) and _cross_figures_question(raw_question):
        intent = "DATA"
    context_budget.log_decision("intent", intent=intent, followup=is_followup_rewrite,
                                kind=_plan.kind if _plan else None,
                                schemes_named=sorted(_named_schemes(question)))
    t["intent"] = intent
    return None


async def _turn_knowledge_stage(t: dict, session: "Session | None" = None,
                                scope: "auth.UserScope | None" = None) -> "dict | None":
    """The KNOWLEDGE route: RAG over the reference documents (graph: knowledge)."""
    question, raw_question, prev, intent = t["question"], t["raw_question"], t["prev"], t["intent"]
    is_followup_rewrite, has_context, _cm_pinned = t["is_followup_rewrite"], t["has_context"], t["cm_pinned"]
    # 3. KNOWLEDGE -> RAG over the scheme reference docs.
    if intent == "KNOWLEDGE":
        # Both CM Elevate datasets share one knowledge base (rag.kb_scheme), so
        # the data-side "which CM Elevate?" pin means nothing here — give the
        # question back in the user's own words rather than showing a rewrite.
        if _cm_pinned:
            question = _unpin_cm_elevate(question)
        # How a scheme works is not per year: drop a year the rewrite carried
        # over from the previous DATA turn (the user never typed it).
        if is_followup_rewrite:
            question = _drop_inherited_place(_drop_inherited_time(question, raw_question), raw_question)
        # Scope retrieval to a single scheme when we're confident which one this
        # is about — named outright, or (for a follow-up with nothing named of
        # its own) the scheme the previous turn was about. Without this, vector
        # search has no scheme filter at all and can blend in another scheme's
        # content (e.g. PMAY-Urban passages into a PMAY-G-scoped answer).
        # A self-contained what-is question about a scheme term, asked right
        # after a DATA turn, was rewritten with that turn's measure — "What is
        # SECC?" became "What is SECC in calculating MGNREGA person-days?" and
        # "What is Gram Sabha?" was answered "in the context of MGNREGA
        # person-days" (user report 2026-10-14). Answer the user's own words; the
        # previous turn's scheme stays only a first guess (fallback below).
        _term_q = _is_scheme_term_question(raw_question)
        if _term_q and is_followup_rewrite:
            question = raw_question
        _kb_scheme = None
        _kb_from_context = False   # the scheme only carried over from the previous turn
        _named = _named_schemes(question)
        if len(_named) == 1:
            _kb_scheme = _named[0]
        else:
            # Not named outright — but scheme-specific VOCABULARY pins it just
            # as reliably, and this is the same signal the DATA path has always
            # used (_infer_scheme_from_terms returns a scheme only when exactly
            # one scheme's vocabulary matches). Without it, "What is the role of
            # Producer Groups under FOCUS?" searched the whole KB unfiltered:
            # measured on the real corpus, 3 of the top 8 chunks came back from
            # Focus Plus — which holds no producer-group data at all — and the
            # single best hit was one of them, so the composer answered the
            # wrong scheme's question.
            _inferred = _infer_scheme_from_terms(question)
            if _inferred and len(_inferred) == 1:
                _kb_scheme = _inferred[0]
            # Not when the question says a bare "Focus": that names a scheme —
            # just not WHICH of the two — so inheriting the previous turn's
            # scheme would answer the wrong one ("for focus" after a CM Elevate
            # answer re-answered CM Elevate). It goes to the "which Focus?"
            # pause below instead.
            # Only for a message that continues the conversation (step 0-c):
            # "who is harshit" is not a question about the last turn's scheme.
            elif (has_context and prev is not None and len(prev.schemes or []) == 1
                  and not _is_ambiguous_focus(question)):
                _kb_scheme = prev.schemes[0]
                _kb_from_context = True

        # Genuinely scheme-agnostic ("tell me about the scheme", "how do I
        # apply", "what are the benefits") — no scheme named, no follow-up
        # antecedent, and no vocabulary that pins it to one. Guessing here (or
        # letting bare vector search pick whichever doc scores highest) is how
        # a vague question came back "not covered" while quietly assuming
        # MGNREGA. Ask which of the four schemes instead, same one-tap chips
        # the DATA path already uses (see _needs_scheme_clarification).
        # ...but a question that NAMES a scheme we don't recognise ("what is
        # amma yedi scheme?") is not vague — the user was specific, we simply
        # don't hold it. Asking "which scheme does your question concern?"
        # there ignores what they actually asked; say plainly that it isn't
        # one of the four (reported 2026-09-18).
        # "What is the village code of Abokgre?" reads as knowledge but is a
        # registry lookup (user session 2026-10-13).
        _geo = await _geo_lookup_answer(question)
        if _geo is not None:
            return _geo
        if _kb_scheme is None and _names_unknown_scheme(question):
            return {"route": "knowledge", "intent": "RAG", "confidence": "low", "sources": [],
                    "answer": _knowledge_not_covered_answer(question, None),
                    "rewritten_question": question if question != raw_question else None,
                    "schemes": [],
                    **_empty_data_fields()}
        if _kb_scheme is None and _is_ambiguous_focus(question):
            raise _focus_ambiguity_clarification(question)
        # "What is Gram Panchayat?" with nothing before it names no scheme, but it
        # is not vague either: it asks about one term, and the documents that
        # explain that term best answer it. Asking "which scheme?" there read as
        # not knowing (user report 2026-10-14).
        # The same for a term question whose scheme only came from the previous
        # turn: SECC is PMAY-G's, so "What is SECC?" after an MGNREGA answer is
        # answered from PMAY-G — the carried-over scheme still wins when its own
        # documents match the term best ("What is Gram Sabha?" stays MGNREGA).
        if _term_q and (_kb_scheme is None or _kb_from_context):
            _best = await rag.best_kb_scheme(question)
            if _best:
                _kb_scheme, _kb_from_context = _best, False
        if _kb_scheme is None and _needs_scheme_clarification(question):
            raise _scheme_clarification(question)

        # Two or more schemes named outright ("how do I apply across MGNREGA,
        # PMAY-G, Focus Plus and CM Elevate") — retrieve each scheme's chunks
        # separately (see rag.answer_from_kb_multi) instead of one unscoped
        # search, which otherwise lets one scheme's passages crowd out another's.
        if len(_named) > 1:
            kb = await rag.answer_from_kb_multi(question, schemes=_named)
            base = {"rewritten_question": question if question != raw_question else None,
                    "schemes": _named}
        else:
            # "Give me a short overview of Focus Legacy for an official briefing":
            # the words "official"/"briefing" pulled the where-to-find-official-info
            # and institutional-structure chunks, so the answer was a list of
            # departments with no benefit amount, objective or scale (Focus Legacy
            # QA TC-09, 2026-09-25). Retrieve with the scheme-overview phrasing
            # instead; the answer is still written to the user's own question.
            # Same for CM Elevate: its overview retrieved the dataset-description
            # passages ("a unified API … contains no monetary data") instead of the
            # subsidy, loan and sectors (Legacy sheet TC-09, 2026-10-22, KI-382).
            _retrieval_q = (_scheme_overview_question(_kb_scheme)
                            if _kb_scheme in ("Focus Legacy", "CM Elevate", "CM Elevate Legacy")
                            and _OVERVIEW_REQUEST.search(question)
                            else None)
            # "What is the toll-free helpline number for MGNREGA complaints?"
            # retrieved nothing on "toll-free number" and got the generic "not in
            # the reference material" reply. The documents hold the grievance
            # route (Gram Panchayat, Programme Officer, DPC, Ombudsperson), which
            # is what a user with a complaint needs (General TC-015, 2026-10-06).
            if _retrieval_q is None and _kb_scheme and _CONTACT_INFO_CUE.search(question):
                _retrieval_q = f"How can a complaint or grievance be raised under {_kb_scheme}?"
            if _retrieval_q:
                kb = await rag.answer_from_kb(question, scheme=_kb_scheme, retrieval_query=_retrieval_q)
            else:
                kb = await rag.answer_from_kb(question, scheme=_kb_scheme)
            base = {"rewritten_question": question if question != raw_question else None,
                    "schemes": [_kb_scheme] if _kb_scheme else []}
            # A scheme only carried over from the previous turn can be the wrong
            # knowledge base for a term: "What is SECC?" after an MGNREGA answer
            # searched MGNREGA alone and said "not mentioned" — SECC is PMAY-G's
            # (user report 2026-10-14). When that search finds nothing, answer
            # from the other scheme whose documents match the question best.
            if not kb and _kb_from_context:
                _alt = await rag.best_kb_scheme(question, exclude=_kb_scheme)
                if _alt:
                    kb = await rag.answer_from_kb(question, scheme=_alt)
                    if kb:
                        _kb_scheme = _alt
                        base["schemes"] = [_alt]
        if kb:
            return {"route": "knowledge", "intent": "RAG", "confidence": kb["confidence"],
                    "answer": _focus_legacy_rate_line(question, _kb_scheme, kb["answer"]),
                    "sources": kb["sources"], "citations": kb.get("citations", []),
                    **_empty_data_fields(), **base}
        return {"route": "knowledge", "intent": "RAG", "confidence": "low", "sources": [],
                "answer": _knowledge_not_covered_answer(question, _kb_scheme),
                **_empty_data_fields(), **base}
    return None


async def _turn_data_context_stage(t: dict, session: "Session | None" = None,
                                   scope: "auth.UserScope | None" = None) -> None:
    """The filters a DATA follow-up inherits (graph: data_context)."""
    prev, is_followup_rewrite = t["prev"], t["is_followup_rewrite"]
    _thread_state, _plan = t["thread_state"], t["plan"]
    # 4. DATA -> NL->SQL. On a hard failure, try the KB once before giving up.
    # A rewritten follow-up's entities are seeded with the previous turn's
    # resolved district/block/village/year as a fallback (see resolve_entities'
    # `prior_resolved` param) — the LLM rewrite works from prev.question/answer
    # TEXT, so an entity can silently drop if it doesn't literally reappear in
    # the rewritten wording (e.g. a village name the rewrite paraphrases away).
    _prior_resolved = prev.resolved_entities if (is_followup_rewrite and prev is not None) else None
    if is_followup_rewrite and _thread_state is not None:
        # Extends the fallback above with session-level structured state, so a
        # KNOWLEDGE/EDGE turn sitting between the last DATA answer and this
        # follow-up (which leaves resolved_entities empty — see
        # context_manager.update_state) doesn't erase district/block/village/
        # year a later "and in 2023-24?" still needs. Turn-level prev values
        # still win where both are present.
        try:
            _prior_resolved = context_manager.merged_prior_resolved(_prior_resolved, _thread_state)
        except Exception:  # noqa: BLE001
            logger.warning("context_manager.merged_prior_resolved failed — using turn-level only",
                           exc_info=True)
    if is_followup_rewrite and _plan is not None:
        # Drop from the fallback any field this follow-up REPLACEs, CLEARs or
        # can't pin. Before this, "show it by district" after a West Garo Hills
        # turn still inherited the district filter (the LLM extractor finds no
        # district in "...by district"), and "what about South Garo Hills?"
        # after a Dalu turn kept block DALU under the new district.
        _prior_resolved = context_policy.apply_merge_plan(_prior_resolved, _plan)
    if _prior_resolved and t["raw_question"] and _WHICH_YEAR_CUE.search(t["raw_question"]) \
            and not context_policy.extract_year_keys(t["raw_question"]):
        # "Which year was the highest?" ranks the years — the previous turn's
        # year would leave just that one (see _WHICH_YEAR_CUE). Dropped here as
        # well as from the rewritten text, since resolve_entities seeds from it.
        _prior_resolved = {k: v for k, v in _prior_resolved.items() if k not in ("year_key", "year_all")}
    if not is_followup_rewrite and _prior_resolved is None:
        _prior_resolved = _same_scheme_context_year(
            t["question"], t["raw_question"], _thread_state,
            kind=(session.turn_context or {}).get("turn_kind") if session is not None else None)
    t["prior_resolved"] = _prior_resolved


# Words that point back at the previous answer's measure ("how many of THOSE were
# completed", "what share of IT"): a refinement, left to the model rewrite.
_C14_MEASURE_BACKREF = frozenset(("that", "those", "these", "them", "it", "its", "their", "they", "which", "same"))


def _pure_measure_change(question: str, prev, plan) -> bool:
    """KI-334: a follow-up that only names a new measure ("how many beneficiaries
    are there?", "what is the total amount released?") after a single-scheme
    data answer. The follow-up plan must change the metric and nothing else; the
    question names no scheme and points back at nothing."""
    if plan is None or prev is None or getattr(prev, "route", None) != "data":
        return False
    schemes = list(getattr(prev, "schemes", None) or [])
    if len(schemes) != 1 or getattr(plan, "kind", None) != context_policy.METRIC_CHANGE:
        return False
    acts = {k: v for k, v in (plan.actions or {}).items() if v != context_policy.KEEP}
    if acts != {"metric": context_policy.REPLACE}:
        return False
    if _mentions_scheme(question or "") or set(_c01_tm_words(question)) & _C14_MEASURE_BACKREF:
        return False
    return True


def _ranking_followup_question(question: str, prev, plan, state) -> "str | None":
    """The rewrite of a follow-up that ranks a place level and names its own
    measure ("Which block has highest number of households?", "top 3 blocks by
    households employed"), or None: the user's words, the chat's scheme, the
    chat's place ABOVE the ranked level and the chat's year.

    Reported 2026-10-22 (the Demdema chat): the 9B rewrite grafted these onto the
    previous question — "How many households were employed under MGNREGA in the
    top 3 blocks …" summed the top three (145,498), and "most job cards in which
    block?" became households plus a block name. A ranking that names its
    measure needs nothing from the previous question but its scope."""
    if plan is None or prev is None or getattr(prev, "route", None) != "data":
        return None
    schemes = list(getattr(prev, "schemes", None) or [])
    if len(schemes) != 1 or plan.action("metric") != context_policy.REPLACE:
        return None
    ranked = [dim for dim in ("district", "block", "village")
              if (plan.reasons.get(dim) or "").startswith("ranks the ")]
    if not ranked:
        return None
    sch = schemes[0]
    if not set(_exact_schemes(question or "")) <= {sch}:
        return None
    if set(_c01_tm_words(question)) & (_C14_MEASURE_BACKREF - {"which"}):
        return None
    resolved = getattr(prev, "resolved_entities", None) or {}

    def _get(name: str, key: str):
        return getattr(state, name, None) if state is not None else resolved.get(key)

    from types import SimpleNamespace
    from app.entity_resolver import place_mentions as _c14_pm
    keep = {"district": (), "block": ("district",), "village": ("district", "block")}[ranked[0]]
    own_place = bool(_c14_pm(question))
    own_year = plan.action("year") != context_policy.KEEP
    scope_state = SimpleNamespace(
        district=_get("district", "district") if "district" in keep and not own_place else None,
        block=_get("block", "block") if "block" in keep and not own_place else None,
        village=None,
        year=None if own_year else _get("year", "year_key"),
        year_all=False if own_year else _get("year_all", "year_all"))
    return f"{question.strip().rstrip(' ?.')} under {sch}{_swap_scope_phrase(scope_state, sch)}?"


def _vague_topic_clarification(question: str, session) -> "ClarificationNeeded | None":
    """D-061: a vague question ("how many beneficiaries?") while two or more
    topics are open is asked, one chip per topic — never a default scheme. With
    one topic, None: the question runs in it (the existing scope-less follow-up),
    and the banner shows the scope used. Each chip is a topic switch ("Go back to
    MGNREGA: how many beneficiaries?", topic_memory), so the reply runs in that
    topic's own place and year."""
    if session is None:
        return None
    try:
        mem = topic_memory._memory(session)
    except Exception:  # noqa: BLE001 — no topic memory: the question runs as before
        return None
    # Single-scheme topics only: a comparison topic is not a scope one measure fits.
    keys = [k for k in reversed(mem.get("order") or []) if k in (mem.get("items") or {})
            and " + " not in k
            and (((mem["items"][k].get("state") or {}).get("scheme"))
                 or ((mem["items"][k].get("last_turn") or {}).get("route") == "data"))][:4]
    # A measure that pins its scheme ("how many job cards?") fits only that
    # scheme's topic: no question to ask when just one is open.
    pinned = context_policy._schemes_named(question or "")
    if pinned:
        keys = [k for k in keys if k in pinned]
    if len(keys) < 2:
        return None
    q = (question or "").strip()
    names = ", ".join(keys[:-1]) + f" or {keys[-1]}"
    return ClarificationNeeded(
        f"Which topic is this about — {names}?",
        options=[{"label": k, "question": f"Go back to {k}: {q}"} for k in keys],
        rule=topic_memory.TOPIC_PAUSE_RULE)


def _same_scheme_context_year(question: str, raw_question: str, state,
                              kind: "str | None" = None) -> "dict | None":
    """The chat's scope a new (not rewritten) data question inherits, as the
    resolver's `prior_resolved` fallback, or None.

    KI-331 (live 2026-10-19 15:27): "give me cm elevate disbursement by district"
    right after "How many CM Elevate Legacy records … across all financial years?"
    asked "which financial year?" again: a question that names a scheme reads as a
    new one, so no prior_resolved reached the year gate (D-053).
    User rule 2026-10-21 (D-056): "how many households for PMAY-G" after an MGNREGA
    West Garo Hills FY 2022-23 answer asked the year again and dropped the district.
    Whatever the user does not say again is carried forward, on ANY one scheme:
    the year when the question names none (and the target scheme holds it — else
    the year chips ask), the place when it names none (a place it names wins in the
    resolver; a statewide or by-district question drops it). Another scheme's
    district / block names are re-read against that scheme's own catalogue. A
    model-inferred value is not inherited.

    D-061 (user addendum 2026-10-22) narrows this to questions that are NOT self-
    sufficient: a question with its own scheme and its own measure and no
    reference cue ("Total PMAY-G houses completed in 2023-24", "Which district
    has the highest beneficiaries in MGNREGA?") inherits nothing — the stranger
    test (context_policy.turn_kind). Its year is the question's, else the default
    rule (c13: ask the year, D-065).

    `kind` is the turn's own kind when the follow-up stage decided it — for a
    resumed pause, the kind of the question the user typed (D-065), not of the
    chip text, which names the scheme and reads as standalone.

    KI-406 (user decision 2026-10-27, U5): a standalone question that only repeats
    the chat's measure on the chat's scheme ("Total MGNREGA person-days in 2023-24"
    -> "What is the total beneficiaries?" -> "What is the total beneficiaries
    manraya?", the spoken MGNREGA) keeps the chat's YEAR, not its place. A new
    measure ("Which district has the highest beneficiaries in MGNREGA?" after
    person-days, D-061's own case) still inherits nothing and is asked the year."""
    if state is None or not getattr(state, "scheme", None):
        return None
    year_only = False
    if (kind or context_policy.turn_kind(raw_question or question).kind) == context_policy.TURN_STANDALONE:
        if not _c14_repeats_chat_measure(raw_question or question, state):
            return None
        year_only = True
    target = _c14_context_target_scheme(question, state)
    if not target or (year_only and target != state.scheme):
        return None
    _prov = getattr(state, "provenance", None) or {}
    out: dict = {}
    _own_year = any(context_policy.extract_year_keys(q) or _ALL_YEARS_CUE.search(q) or _TIME_SERIES_CUE.search(q)
                    or _WHICH_YEAR_CUE.search(q) for q in (question or "", raw_question or ""))
    _years = _SCHEME_DATA_YEARS.get(target) or []
    if not _own_year and _years and (_prov.get("year") or {}).get("source") != "model_inference":
        year = getattr(state, "year", None)
        if isinstance(year, int) and (target == state.scheme or _fy_short(year) in _years):
            out["year_key"] = year
        elif getattr(state, "year_all", False):
            out["year_all"] = True
    # A district the question names itself is its place (the resolver would let
    # it win anyway; carrying nothing keeps the words shareable through the cache).
    try:
        _names_district = bool(scan_districts(raw_question or question or "", target))
    except Exception:  # noqa: BLE001 — catalogue unavailable: the resolver decides
        _names_district = False
    for fld in () if (_names_district or year_only) else _c14_kept_place_fields(raw_question or question or ""):
        v = getattr(state, fld, None)
        if not v or (_prov.get(fld) or {}).get("source") == "model_inference":
            continue
        if target != state.scheme:
            v = _c14_place_in_scheme(str(v), target, fld)
            if v is None:
                break          # a parent that does not exist there: carry nothing below it
        out["village_code" if fld == "village" else fld] = v
    if not out:
        return None
    context_budget.log_decision("data_context",
                                inherited="same-measure-year" if year_only else "context-scope", scheme=target,
                                from_scheme=state.scheme,
                                year=out.get("year_key") or ("all" if out.get("year_all") else None),
                                place=out.get("village_code") or out.get("block") or out.get("district"))
    return out


def _c14_repeats_chat_measure(question: str, state) -> bool:
    """KI-406: the question names no scheme but the chat's own and asks the chat's
    last measure (context_manager.detect_metric, the keyword kept in state.metric)."""
    chat_metric = getattr(state, "metric", None)
    if not chat_metric or not set(context_policy._schemes_named(question or "")) <= {state.scheme}:
        return False
    return context_manager.detect_metric(question or "") == chat_metric


def _c14_context_target_scheme(question: str, state) -> "str | None":
    """The one scheme a new question is about: the one it names, else the one its
    words pin, else the chat's own (the scheme stage appends it). None when it
    names several (a comparison carries nothing)."""
    named = sorted(_exact_schemes(question or ""))
    if len(named) > 1:
        return None
    if named:
        return named[0]
    inferred = list(_infer_scheme_from_terms(question or "") or [])
    if len(inferred) == 1:
        return inferred[0]
    return getattr(state, "scheme", None)


def _c14_place_in_scheme(value: str, scheme: str, fld: str) -> "str | None":
    """The chat's district / block as `scheme` spells it, or None when that scheme
    has no such place. A village carries only as its LGD code (shared by every
    scheme); a village name is another scheme's spelling and is dropped."""
    if fld == "village":
        return value if value.isdigit() else None
    try:
        hit = scan_dimension(value, scheme, fld, level_is_explicit=True)
    except Exception:  # noqa: BLE001 — catalogue unavailable: carry nothing
        return None
    return str(hit.canonical) if hit is not None and hit.status == "resolved" and hit.canonical else None


# The chat's place a new question keeps (user rule 2026-10-21): all of it, unless
# it asks for the whole state ("for all of Meghalaya", "statewide") or a span of
# districts ("by district", "top 5 districts", "compare"), which drop it, or a
# span below the district ("by block", "each village"), which keeps the district.
_C14_STATEWIDE = Matcher(Alt(
    "meghalaya", _c04Joined("state", ("wide", "level")), Seq("entire", "state"), Seq("whole", "state"),
    Seq("all", Opt("the"), W("districts")), "statewide"))
_C14_DISTRICT_SPAN = frozenset(("district", "districts", "compare", "comparison", "versus", "vs"))
_C14_BELOW_DISTRICT = frozenset(("block", "blocks", "village", "villages", "panchayat", "panchayats", "gp", "gps"))


def _c14_kept_place_fields(text: str) -> tuple:
    if _C14_STATEWIDE.search(text or ""):
        return ()
    # D-061 slot-conflict guard: the level a question asks ABOUT ("which
    # district …", "top 5 blocks") and every level below it are never its filter.
    asked = context_policy.asked_levels(text or "")
    if asked:
        return {"district": (), "block": ("district",), "village": ("district", "block")}[asked[0]]
    if _HAS_BREAKDOWN.search(text or ""):
        ws = {w.lower() for w in _c01_tm_words(text)}
        if ws & _C14_DISTRICT_SPAN:
            return ()
        if ws & _C14_BELOW_DISTRICT:
            return ("district",)
    return ("district", "block", "village")


# "what is <something> scheme/yojana/mission?" — the user named a specific
# programme by name. When it is none of our four and not in the known
# unsupported catalogue either, it is still a NAMED ask, not a vague one, so it
# must not get the "which scheme does your question concern?" pause.
_C14_SCHEME_NOUNS = frozenset({"scheme", "yojana", "yojna", "mission", "abhiyan", "abhiyaan", "programme", "program"})
_C14_ASK_LEAD = Alt(W("what", "which", "explain", "describe", "about"), _c1x_lit("tell me about"))


def _c14_name_word_end(text: str, k: int) -> int:
    """End of a word at k (a letter, then letters, digits, '_', ''' or '-'), or -1."""
    n = len(text)
    if not (k < n and text[k].isascii() and text[k].isalpha()):
        return -1
    e = k + 1
    while e < n and (_c1x_is_word_char(text[e]) or text[e] in "'-"):
        e += 1
    return e


class _C14NamedScheme(_C1xLike):
    """The old _NAMED_UNKNOWN_SCHEME_MATCH: what / which / tell me about / explain /
    describe / about, then at most 60 characters with no . ? !, then a name of
    1-4 words (group "name") right before scheme / yojana / mission / programme …"""

    def _hits(self, text):
        ctx = _C1xCtx(text)
        n = len(text)
        for i in range(len(ctx.toks)):
            for j, _c in _C14_ASK_LEAD.ends(ctx, i, ()):
                e0 = ctx.toks[j - 1].end
                for k in range(e0, min(e0 + 60, n) + 1):
                    if k > e0 and text[k - 1] in ".?!":
                        break
                    if k == e0 or _c1x_is_word_char(text[k - 1]):
                        continue                         # the name must start a word
                    ends = []
                    q = _c14_name_word_end(text, k)
                    while q >= 0 and len(ends) < 4:
                        ends.append(q)
                        r = q
                        while r < n and text[r].isspace():
                            r += 1
                        q = _c14_name_word_end(text, r) if r > q else -1
                    for q in reversed(ends):
                        r = q
                        while r < n and text[r].isspace():
                            r += 1
                        if r == q:
                            continue
                        w = r
                        while w < n and _c1x_is_word_char(text[w]):
                            w += 1
                        if text[r:w].lower() in _C14_SCHEME_NOUNS:
                            return [Hit(text, ctx.toks[i].start, w, [], {"name": (k, q)})]
        return []


_NAMED_UNKNOWN_SCHEME_MATCH = _C14NamedScheme()
# Words that make the phrase generic rather than a name ("what is THIS scheme",
# "about the scheme"), so they must not count as naming one.
_GENERIC_SCHEME_WORDS = {
    "the", "this", "that", "a", "an", "any", "each", "every", "all", "these",
    "those", "your", "which", "what", "some", "other", "another", "such",
    "government", "govt", "state", "central", "rural", "welfare", "above",
    # Verbs / fillers the opener can leave in the captured span ("what IS the
    # scheme") — on their own they name nothing.
    "is", "are", "was", "were", "do", "does", "did", "me", "about", "of",
    "for", "in", "on", "it", "they", "you", "i", "we", "tell", "explain",
    # Generic nouns a scheme question asks ABOUT, never the scheme's name
    # ("what are the BENEFITS of the scheme").
    "benefit", "benefits", "eligibility", "criteria", "document", "documents",
    "purpose", "objective", "objectives", "feature", "features", "detail",
    "details", "rule", "rules", "process", "procedure", "amount", "subsidy",
}


def _names_unknown_scheme(question: str) -> bool:
    """True when the question names a specific scheme by name that is neither
    one of ours nor in the unsupported catalogue."""
    if _named_schemes(question) or _infer_scheme_from_terms(question):
        return False                       # one of ours — nothing unknown here
    # A bare "Focus" names one of OUR schemes — we just don't yet know which of
    # the two (see _is_ambiguous_focus). Without this, "what is the FOCUS
    # scheme?" matched the "<name> scheme" check below, found "focus" in
    # neither registry above, and was answered "that isn't a scheme I hold" —
    # for a scheme with a full reference doc and FAQ in the KB. It must fall
    # through to the which-Focus ask instead.
    if _is_ambiguous_focus(question):
        return False
    if _unsupported_scheme_named(question):
        return False                       # handled by its own, better reply
    m = _NAMED_UNKNOWN_SCHEME_MATCH.search(question or "")
    if not m:
        return False
    words = m.group("name").split()
    if not words:
        return False
    # The scheme's NAME is the word immediately before "scheme"/"yojana"/… —
    # "amma yedi scheme" names one, "the benefits of the scheme" does not.
    # Testing the last word alone (rather than the whole captured span) keeps
    # this from firing on any question that merely mentions a generic noun on
    # its way to the word "scheme".
    if words[-1].lower() in _GENERIC_SCHEME_WORDS:
        return False
    # A bare "<word> scheme" where that word is an ordinary English filler is
    # still generic; require something that reads like a proper name.
    return len(words[-1]) >= 3


def _knowledge_not_covered_answer(question: str, scheme: "str | None") -> str:
    """The reply when the knowledge base genuinely has nothing for a question.

    The old text — "I don't have information about that for MGNREGA, PMAY-G,
    Focus Plus or CM Elevate" — reads as a dead end: it never says whether the
    SUBJECT is out of scope or the assistant simply failed, and offers nowhere
    to go (reported 2026-09-18, "what is PM kisan yojana?"). A question that
    named a scheme gets a scheme-scoped answer; one that named none is told
    what IS covered."""
    if scheme:
        # Name the reference material actually searched — CM Elevate Legacy has
        # none of its own, it reads CM Elevate's (rag.kb_scheme). Identity for
        # every other scheme.
        # Never name internal sources ("reference material", "knowledge base") to
        # the user (General TC-015, test run 2026-10-09): say what is not
        # published and where an officer would get it instead.
        return (
            f"That specific detail isn't part of the published information I have on "
            f"{rag.kb_scheme(scheme)} — your Block office or the district "
            f"{scheme} cell can give it. I can cover {scheme}'s eligibility, benefits, "
            "documents and how to apply, and its data by district, block, village or "
            "financial year. If you meant a different scheme, tell me which."
        )
    return (
        "That isn't something I hold. I cover six Meghalaya schemes — MGNREGA "
        "(rural employment), PMAY-G (rural housing), Focus Plus (farmer cash "
        "benefit), CM Elevate (livelihood and enterprise support — its applications), "
        "CM Elevate Legacy (CM Elevate's sanctions and disbursements) and Focus Legacy "
        "(producer group payments) — both how "
        "each one works and its actual data. If your question is about one of "
        "those, name it and I'll answer; if it's about another scheme or another "
        "state, that's outside what I can see."
    )


async def _data_path_kb_fallback(question: str) -> dict:
    """The DATA path genuinely couldn't produce a query (bad/uncoverable question,
    not an infra blip) — try the knowledge base once, then give the 'rephrase it'
    reply. Transient gateway errors are handled by the caller and never reach here."""
    # A figure question about a place or year cannot be answered from the scheme
    # documents: they replied "the published scheme information does not contain
    # figures for Gambegre block…", which reads as if the data did not exist
    # (MGNREGA sheet DATA-005/014/029, run 2026-10-09). Say the query failed.
    kb = None if _is_data_shaped(question) else await rag.answer_from_kb(question)
    if kb:
        return {"route": "knowledge", "intent": "RAG", "confidence": kb["confidence"],
                "answer": kb["answer"], "sources": kb["sources"], **_empty_data_fields()}
    # Name the scheme(s) actually in play, not a hardcoded pair — this message used
    # to always say "MGNREGA / PMAY-G data" even for a Focus Plus / CM Elevate
    # question, which reads as if the conversation's own context had been dropped
    # (it hadn't — this text just never grew past the original two-scheme build).
    _fallback_schemes = _named_schemes(question) or _infer_scheme_from_terms(question)
    _schemes_text = " / ".join(_fallback_schemes) if _fallback_schemes else " / ".join(SCHEME_CATALOG)
    return {"route": "data", "intent": "DATA", "confidence": "low",
            "answer": ("I understood the question but couldn't build a working query for it "
                       f"against the current {_schemes_text} data. Try rephrasing it, or ask "
                       "for a simpler breakdown first (e.g. \"PMAY-G sanctions by district "
                       "for 2023\")."),
            **_empty_data_fields()}


def _first_known_place(text: str) -> "tuple[int, int] | None":
    """Span of the first district / block name in `text` (longest names are
    tried first, so "South West Garo Hills" wins over "West Garo Hills"), or None."""
    low = (text or "").lower()
    for name in _known_place_names():
        i = low.find(name)
        if i >= 0:
            before = low[i - 1] if i > 0 else " "
            after = low[i + len(name)] if i + len(name) < len(low) else " "
            if not before.isalnum() and not after.isalnum():
                return i, i + len(name)
    return None


def _merge_scope_reply(pending: str, reply: str) -> str:
    """The paused question with the scope reply merged in. A reply that names
    a different place REPLACES the paused question's place: "MGNREGA person-days
    in South Garo Hills" -> "which year?" -> "West Garo Hills, 2024-25" means West
    Garo Hills, not both districts (context audit 2026-10-19)."""
    base = (pending or "").rstrip(" ?.")
    rep = (reply or "").strip()
    new = _first_known_place(rep)
    old = _first_known_place(base)
    if new and old and base[old[0]:old[1]].lower() != rep[new[0]:new[1]].lower():
        base = base[:old[0]] + rep[new[0]:new[1]] + base[old[1]:]
        rest = (rep[:new[0]] + " " + rep[new[1]:]).strip()
        while rest and (rest[0] in ",;:-" or rest[0].isspace()):
            rest = rest[1:]
        return f"{base}, {rest}" if rest else base
    return f"{base}, {rep}"

# app/pipeline/common/c09_resolve_entities.py — resolve_entities.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.
#
# Plain-Python text matching (D-047): see the character helpers at the end of this
# file and the shared ones imported in c07_mentions.


# Nouns that name an organisation or a record, never a place: a "district"
# mention holding one is the subject of the question, not where it happened.
_C09_NON_PLACE_NOUNS = frozenset((
    "cooperative cooperatives coop coops society societies lamp lamps group groups pg pgs shg shgs "
    "payment payments record records batch batches registration registrations beneficiary beneficiaries "
    "applicant applicants application applications scheme schemes member members farmer farmers "
    "household households house houses tranche tranches bank banks lender lenders").split())


def _c09_not_a_place(mention: str) -> bool:
    """A "district" mention that cannot be a place name: it holds a digit, an
    organisation / record noun ("LAMPS cooperatives", "registration batch
    payments"), or only ordinary vocabulary. A known place outside Meghalaya
    ("Guwahati", "Assam") is always a place, so it is still refused."""
    from app import edge
    m = (mention or "").strip()
    if not m or edge._OUT_OF_AREA.search(m.lower()) or edge._FOREIGN_PLACE.search(m.lower()):
        return False
    if any(ch.isdigit() for ch in m):
        return True
    words = [w.lower() for w in _c01_alpha_words(m)]
    return bool(words) and (any(w in _C09_NON_PLACE_NOUNS for w in words)
                            or all(_is_known_word(w) for w in words))


async def resolve_entities(question: str, schemes: list[str],
                            prior_resolved: "dict | None" = None,
                            village_hint: "str | None" = None) -> dict:
    """Resolve every extracted mention to a canonical DB value. Ambiguous ->
    raise ClarificationNeeded (ask, per the resolver's own hard rule — never
    guess). Not-found is not an error: it means the value genuinely is not in
    this data, which the response composer should say plainly, not silently
    drop the filter.

    `prior_resolved` (optional): the previous turn's resolved entities, passed
    only when this question is a rewritten follow-up. Used purely as a
    fallback — for any dimension (district/block/village_code/year_key) the
    CURRENT question names nothing for at all, carry the prior turn's value
    forward instead of leaving it unset. This covers a village/year the
    follow-up rewrite paraphrased away in its wording (the rewrite works from
    prev.question/answer TEXT, so an entity can silently vanish if it doesn't
    literally reappear). A dimension the current question DOES name something
    for (even something that fails to resolve) is left alone — the user is
    talking about something new for that slot, not carrying the old one over.

    `village_hint` (optional): the exact village-name text from a just-resumed
    village-ambiguity pause (ClarificationNeeded.village_hint / Session.
    pending_village_hint). Used ONLY when this question's own mention
    extraction finds no village at all — the merged resume text ("...the one
    in Betasing block") does not reliably make the LLM re-tag the original
    village name, and without it SQL generation has no village_code to filter
    on and can invent one instead of using the now-resolved block/district."""
    # Out-of-range financial year — checked FIRST, before the LLM mention call
    # and any geography resolution. Works purely off the raw question text, so it
    # still fires when the extractor is unavailable or drops the year slot (a
    # comma-joined scope-pause reply like "wgh, 1999-20" does exactly that). A
    # year outside the data window makes the whole question unanswerable
    # regardless of the place, so this must not depend on anything downstream.
    # How many same-name villages a disambiguation pause lists. ASIMGRE is 7
    # villages and BOLCHUGRE / UMSAW 6 each; with 5 chips the last ones could never
    # be chosen (all-villages QA 2026-09-26). MGNREGA only.
    _vcap = 10 if _village_scheme(schemes) else 5
    _year_gap_note: "str | None" = None
    if settings.YEAR_RANGE_GUARD_ENABLED:
        _yraw = _out_of_range_year_in(question, schemes)
        if _yraw is not None:
            # Only refuse when NOTHING in the question is answerable. A question
            # naming an absent year AND a valid one ("compare FY 2023-24 and FY
            # 2024-25" — the Focus Legacy gap) used to be refused outright, which
            # asked the user to re-pick years they had already named, from a list
            # that deliberately excludes the one they asked about. Drop the
            # absent year, note the gap so the answer states it, and answer for
            # the years that exist — which is what the scheme's own response
            # contract requires (fy_gap_note).
            question, _year_gap_note, _handled = _apply_year_gap(question, schemes)
            if not _handled:
                raise _year_out_of_range_clarification(question, _yraw, schemes)

    mentions = await extract_entity_mentions(question)
    mentions = _drop_producer_group_names(question, mentions)
    mentions = _backfill_explicit_year(question, schemes, mentions)
    # Every raw-text place SCAN below reads this copy, so a producer-group name
    # the user labelled as one is never re-found as a block/village/constituency.
    _scan_q = _question_without_pg_name(question)
    # CM Elevate: an urban local body ("Jowai-municipal Board", "Mawkyrwat-town
    # Committee", "Nongpoh TC") is a BLOCK the data stores with that suffix. It
    # went to the district slot and was refused as outside Meghalaya, or was asked
    # "the Mawkyrwat C&RD block or village?" — both chips wrong (CM Elevate
    # all-blocks run 2026-09-28, KI-107). Move it to the block slot; the
    # collision gate below leaves it alone.
    _cme_urban_block = None
    if schemes in (["CM Elevate"], ["CM Elevate Legacy"]):
        for _uslot in ("district", "village", "block"):
            _uname = mentions.get(_uslot)
            if not _uname:
                continue
            _utext = str(_uname) if _URBAN_WORD_MATCH.search(str(_uname)) else (
                _c09_name_with_urban_suffix(question or "", str(_uname)))
            _ublk = await _cm_elevate_block_from_mention(_utext, schemes) if _utext else None
            if _ublk and _URBAN_BODY_MATCH.search(_ublk):
                mentions = {k: v for k, v in mentions.items() if k != _uslot}
                mentions["block"] = _cme_urban_block = _ublk
                logger.info("CM Elevate urban body %r -> block %r", _uname, _ublk)
                break

    resolved: dict[str, object] = {}
    notes: list[str] = []
    _district_swaps: list[tuple[str, str]] = []   # (stale district, the block's own) KI-327
    if _year_gap_note:
        # Stated in the answer, so a dropped gap year is visible to the user
        # rather than silently ignored.
        notes.append(_year_gap_note)
    # Human-readable names for whatever the query ends up filtering on, keyed by
    # dimension. Handed to the response composer so it says "West Garo Hills",
    # not the "wgh" the user typed or the "WEST GARO HILLS" DB literal.
    display: dict[str, str] = {}

    # The admin level the question states outright — either because the user
    # said it ("the Sohra constituency") or because this is a resumed
    # admin-level collision chip ("..., the assembly constituency, not another
    # area type"). Computed HERE, before any per-dimension branch runs: the
    # district branch below can resolve a name as a village on its own
    # fall-through, so a guard placed later would come too late to stop it.
    _stated_level = _explicit_level_in(question, schemes)
    # MGNREGA: a resumed VILLAGE-disambiguation chip ends ", DEMDEMA block, WEST
    # GARO HILLS" (_village_chip_question) with no ", the village" phrase, so the
    # chip-tail strip in _explicit_level_in does not run and the tail's "block"
    # read as the stated level. The village was then cleared and the query
    # filtered the whole BLOCK — Belbari's expenditure came back as DEMDEMA's
    # block total, BERUPARA's as 41.33 crore instead of 50.34 lakh (all-villages
    # QA 2026-09-26). village_hint is set only on exactly this resume, which is
    # what separates it from a user who typed ", BATABARI block, WEST GARO HILLS"
    # and meant the block (2026-09-18).
    if _village_scheme(schemes) and village_hint and _stated_level == "block" \
            and _CHIP_SCOPE_SUFFIX_MATCH.search(question) \
            and _explicit_level_in(_CHIP_SCOPE_SUFFIX_MATCH.sub("", question), schemes) is None:
        _stated_level = None
    # MGNREGA: a level word that is part of an exact village NAME is not a stated
    # level. "person-days in BLOCK CAMPUS" (village 274903, DAMBO RONGJENG block)
    # read as a block question and was refused as "not a C&RD block"
    # (all-villages QA 2026-09-26).
    if _village_scheme(schemes) and _stated_level in ("block", "district", "village"):
        _named = await _scan_village_in_question(question, schemes[0])
        if _named and _stated_level in _tm.words(_named[0]):
            _rest = _ci_replace(question, _named[0], " ")
            if _explicit_level_in(_rest, schemes) is None:
                _stated_level = None
    # MGNREGA: a resumed village chip names exactly one village — pin it from the
    # chip text and skip every place branch (see _mgnrega_village_chip_pin).
    _chip_pinned = False
    # A twin-village chip's "(LGD 272933)" is the bot's own exact choice — pin it
    # even when the pause that offered it set no village_hint.
    # Focus Legacy is not a _village_scheme (none of its village guards apply),
    # but its village-disambiguation chips carry the same ", X block, DISTRICT"
    # tail — without the pin, tapping "RONGSIGRE — GASUAPARA block" re-asked the
    # same question forever (Focus Legacy all-villages run 2026-09-29, KI-156).
    # A later year chip carries no village hint, so for Focus Legacy the chip's
    # own tail is enough to pin (the year chip keeps it in the question text).
    # CM Elevate Legacy has the same placeholder design and the same chips, and
    # looped the same way: "DOMBAGRE — RERAPARA block" re-asked "which DOMBAGRE?"
    # on every tap (CM Elevate Legacy all-villages run 2026-09-29, KI-156).
    _tail_pin_scheme = schemes[0] if schemes in (["Focus Legacy"], ["CM Elevate Legacy"]) else None
    _pin_scheme = _village_scheme(schemes) or _tail_pin_scheme
    # The same year-chip case for the village schemes (PMAY-G officer cases run
    # 2026-10-02): "UMSAW — JIRANG block" then "All financial years combined"
    # gave "…UMSAW…, JIRANG block, RI BHOI across all financial years"; the year
    # pause had replaced the remembered village hint, so the pin was skipped,
    # UMSAW was re-resolved in RI BHOI (two of them) and asked again — tapping
    # the chip dropped the year, which asked the year again, forever. A chip
    # tail followed by the year chip's phrase is the bot's own village choice.
    # CM Elevate Legacy too (its own tail pin needs the word "village"): "MAWTNUM —
    # UMLING block" then "All financial years combined" was answered for the whole
    # Umling block, 224 instead of 4 (all-villages run 2026-10-02).
    _year_after_tail = bool(_pin_scheme and _YEAR_AFTER_CHIP_TAIL_MATCH.search(question or "")
                            and _CHIP_TAIL_PARSE_MATCH.search(question or ""))
    if _pin_scheme and (village_hint or _CHIP_LGD_CODE_MATCH.search(question or "") or _year_after_tail or (
            _pin_scheme == _tail_pin_scheme and "village" in _tm.words(question)
            and _CHIP_TAIL_PARSE_MATCH.search(question or ""))):
        _pin = await _mgnrega_village_chip_pin(
            question, _village_scheme(schemes) or ("CM Elevate Legacy" if schemes == ["CM Elevate Legacy"] else None))
        if _pin:
            _chip_pinned = True
            resolved["village_code"] = _pin["village_code"]
            display["village"] = _place_title(str(_pin["lgd_village_name"]))
            # village_code alone goes to SQL, as for any single resolved village —
            # a block/district filter alongside it tempted the generator to drop
            # the village and answer for the whole block (MEGAPGRE, NONGLUM).
            if _pin.get("lgd_block"):
                display["block"] = str(_pin["lgd_block"]).upper()
            if _pin.get("lgd_district"):
                display["district"] = str(_pin["lgd_district"]).title()
            mentions = {k: v for k, v in mentions.items() if k not in
                        ("district", "block", "village", "assembly_constituency", "districts", "blocks")}
            village_hint = None
            _stated_level = None
            logger.info("%s village chip pinned village_code %s (%s, %s block)", schemes[0],
                        _pin["village_code"], _pin["lgd_village_name"], _pin.get("lgd_block"))

    # A resumed collision chip states the level outright, but the LLM
    # mention-extractor still has to notice and re-tag the name into the
    # matching slot — the same extractor whose mis-tagging is what raised the
    # pause to begin with. When the level is stated and the extractor put the
    # name in a DIFFERENT slot, move it deterministically: the user has said
    # which level they mean, so it is no longer the model's call. Runs before
    # every resolution branch, so the name resolves at the chosen level and
    # nowhere else.
    # When the question states a level outright, that level is settled — put
    # the place name there and clear every other place slot, so nothing
    # downstream can re-resolve it somewhere else.
    #
    # The name is re-derived from the question TEXT rather than taken from the
    # extractor. A resumed chip rewrites the question to carry the CANONICAL
    # name ("...in MAWLAI..."), but the extractor frequently echoes the user's
    # ORIGINAL typo back — often into the very slot the chip names
    # ("block": "malwai" for the Mawlai-block chip). That value is present but
    # unresolvable, so trusting it makes the branch fail and fall through to
    # the village: the typo's own version of the bug this gate exists to stop.
    if _stated_level in ("district", "block", "assembly_constituency", "village"):
        _placed = None
        if _stated_level == "village":
            # Village is DB-backed — its own branch resolves it. Keep whatever
            # name is already in hand (extractor value, else the hint).
            _placed = mentions.get("village") or mentions.get("block") \
                or mentions.get("district") or village_hint
            # A CM Elevate programme word is not a village: "…under Piggery scheme in
            # Manipur, the village, …" placed "Piggery" here and the question then
            # asked "which area?" (CM Elevate all-villages run 2026-10-10). Drop it
            # unless a village really has that name; the village scan finds MANIPUR.
            if _placed and schemes == ["CM Elevate"] and _cme_named_programmes(str(_placed)):
                try:
                    if not (await village_names_exact([str(_placed)])).get(str(_placed).strip().upper()):
                        logger.info("village slot %r is a CM Elevate programme word — dropped", _placed)
                        _placed = None
                        mentions.pop("village", None)
                except Exception:  # noqa: BLE001 — keep the extractor's value
                    logger.warning("programme-word village check failed", exc_info=True)
            # The extractor can return a FRAGMENT of a multi-word name that is
            # itself another village: "…for PAKREGRE CHIKAMA village" came back
            # "CHIKAMA" (274919, same block) and the answer counted that village
            # (₹5,000 for the true ₹1,40,000; Focus Legacy all-villages run
            # 2026-09-29). The text names the village outright, so the whole
            # phrase wins when the DB holds it exactly.
            _vt = _VILLAGE_PHRASE_MATCH.findall(_scan_q or question or "")
            _full = _vt[-1].strip(" ,") if _vt else None
            # ...or returns nothing at all ("ADUGRE (NENGSRANG ADUGRE) village" —
            # the question then asked "which area?"; KI-153).
            if _full and (not _placed or (str(_placed).strip().upper() != _full.upper()
                                          and str(_placed).strip().upper() in _full.upper())):
                try:
                    if (await village_names_exact([_full])).get(_full.upper()):
                        logger.info("village %r read whole from the text (extractor gave %r)", _full, _placed)
                        _placed = _full
                except Exception:  # noqa: BLE001 — keep the extractor's value
                    logger.warning("village phrase check failed", exc_info=True)
            # ...or keeps the level word inside the name: "Nongjri Mission village"
            # matched no village exactly, the fuzzy match asked NONGJRI MISSION or
            # NONGBSAP MISSION, and the chip (which replaced the whole mention,
            # "village" included) was then answered for the whole Umsning block
            # (CM Elevate Legacy all-villages run 2026-09-29). Only when the bare
            # name is a stored village and the longer one is not.
            if _placed and _c09_without_village_suffix(str(_placed)) is not None:
                _bare = _c09_without_village_suffix(str(_placed)).strip()
                try:
                    _ex = await village_names_exact([_bare, str(_placed).strip()])
                    if _bare and _ex.get(_bare.upper()) and not _ex.get(str(_placed).strip().upper()):
                        logger.info("village %r read without its level word (extractor gave %r)", _bare, _placed)
                        _placed = _bare
                except Exception:  # noqa: BLE001 — keep the extractor's value
                    logger.warning("village level-word check failed", exc_info=True)
        else:
            _placed = _canonical_in_question(_scan_q, schemes[0], _stated_level)
            if not _placed:
                # No catalogue name in the text — fall back to whatever the
                # extractor found, but only if it resolves at this level.
                for _slot in ("district", "block", "village", "assembly_constituency"):
                    _v = mentions.get(_slot)
                    if _v and resolve_dimension(
                            str(_v), schemes[0], _stated_level).status == "resolved":
                        _placed = str(_v)
                        break
        if _placed:
            for _slot in ("district", "block", "village", "assembly_constituency"):
                mentions.pop(_slot, None)
            mentions[_stated_level] = _placed
            logger.info("explicit level %r — placed %r, cleared other place slots",
                        _stated_level, _placed)

    # ── Admin-level collision gate ──────────────────────────────────────────
    # Before resolving ANY single-name mention, check whether the bare name can
    # name more than one KIND of area (block vs assembly constituency vs
    # village vs district). This runs ahead of every per-dimension branch below
    # on purpose: those branches each resolve one slot in isolation and cannot
    # see that the same text also names a different level, which is how a bare
    # "Sohra" (assembly constituency) ended up fuzzy-matched to the village
    # Sohrarim and answered silently.
    #
    # Skipped when the question already names the level outright ("the Sohra
    # constituency", or a resumed chip's "..., the assembly constituency, not
    # another area type") — the level is settled, nothing to ask. Also skipped
    # for a plural comparison ("districts"/"blocks" arrays), which name their
    # own level by construction, and when a village_hint is carrying a
    # just-resumed village-ambiguity choice.
    if _village_scheme(schemes) in _VILLAGE_NARROW_SCHEMES and _stated_level is None and not village_hint \
            and not _chip_pinned and not mentions.get("districts") and not mentions.get("blocks"):
        _fp_m = next((str(mentions[s]) for s in ("district", "block", "village") if mentions.get(s)), None)
        _fp_dims = await _focusplus_alias_district_collision(_fp_m, _village_scheme(schemes)) if _fp_m else {}
        if _fp_dims:
            # The extractor's name can be only the head of a longer village named whole
            # in the text: "Baghmara (MB) - Ward No.13" came back "Baghmara" and asked
            # district / block / village (Focus + sheet all-villages run 2026-10-10).
            try:
                _whole = await _scan_village_in_question(question, _village_scheme(schemes))
            except Exception:  # noqa: BLE001 — keep the question
                _whole = None
            if _whole and len(_whole[0].strip()) > len(_fp_m.strip()) \
                    and _fp_m.strip().upper() in _whole[0].upper():
                logger.info("Focus Plus: %r is part of the village %r named in full — no level question",
                            _fp_m, _whole[0])
                mentions = {**{k: v for k, v in mentions.items() if k not in ("district", "block")},
                            "village": _whole[0]}
                _fp_dims = {}
        if list(_fp_dims) == ["assembly_constituency"]:
            # the constituency is the only reading with data for this scheme — no question
            logger.info("%s: %r read as the constituency %r (not one of its villages)",
                        _village_scheme(schemes), _fp_m, _fp_dims["assembly_constituency"])
            mentions = {**{k: v for k, v in mentions.items() if k not in ("district", "block", "village")},
                        "assembly_constituency": _fp_dims["assembly_constituency"]}
            _fp_dims = {}
        if _fp_dims:
            logger.info("Focus Plus: %r is a district alias AND a village — asking", _fp_m)
            raise _dimension_collision_clarification(question, _fp_m, _fp_dims)
    if _stated_level is None and not village_hint and not _chip_pinned \
            and not mentions.get("districts") and not mentions.get("blocks"):
        _scheme0 = schemes[0] if schemes else ""
        # The gate can only examine names the extractor handed over, and the
        # extractor drops a plainly-named place often enough to matter: it
        # returned {} on 5 of 5 calls for "applicants in mylliem under Green
        # Taxi CM Elevate and ware house Scheme" (2026-09-18), the lowercase
        # name buried between two scheme names. With no mention there was
        # nothing to test for ambiguity, the gate stayed silent, and the
        # generator filtered lgd_village_name = 'MYLLIEM' — a confident false
        # zero, where MYLLIEM is really a block (and an assembly constituency)
        # holding 2 applicants for those two schemes.
        #
        # So when no place mention survived, scan the raw question for a
        # catalogue name at either ambiguous level. This only ever ADDS a
        # candidate to test; whether it actually pauses is still decided by
        # collides_across_dimensions below, which needs 2+ readings.
        if not any(mentions.get(s) for s in
                   ("district", "block", "village", "assembly_constituency")):
            _found = None
            for _dim in ("block", "assembly_constituency"):
                _found = _canonical_in_question(_scan_q, _scheme0, _dim)
                if _found:
                    mentions = {**mentions, _dim: _found}
                    logger.info("admin-level gate: %r scanned from question text "
                                "(extractor returned no place)", _found)
                    break
            # _canonical_in_question matches names VERBATIM, so a MISSPELLED
            # place the extractor also dropped stayed invisible: "applicants in
            # tikrikulla ..." (a typo of the TIKRIKILLA block) resolved no
            # place at all, the generator passed the user's own spelling into
            # `lgd_block = 'TIKRIKULLA'`, and the query returned a confident
            # zero where the block really holds 243 applicants for those three
            # schemes (2026-09-18). resolve_dimension and
            # collides_across_dimensions both handle that typo; only the scan
            # feeding them was exact-only.
            #
            # So fall back to the place-phrase candidates ("in <name>") and let
            # the resolver's own fuzzy stage judge them. Whether this actually
            # pauses is still decided by collides_across_dimensions below,
            # which needs 2+ readings — this only supplies a name to test.
            if not _found:
                for _cand in _village_scan_candidates(question, _scheme0):
                    for _dim in ("block", "assembly_constituency"):
                        _r = resolve_dimension(_cand, _scheme0, _dim)
                        if _r.status == "resolved":
                            mentions = {**mentions, _dim: _cand}
                            logger.info("admin-level gate: %r fuzzy-matched %s %r "
                                        "(extractor returned no place)",
                                        _cand, _dim, _r.canonical)
                            _found = _cand
                            break
                    if _found:
                        break
        # A district reached only through its HQ-town alias: the extractor tags
        # "Mairang" / "Resubelpara" as a district, the alias resolves it to
        # Eastern West Khasi Hills / North Garo Hills, and a district hit ends the
        # gate by design — so the bare BLOCK name was answered with the whole
        # district's figure (2,259.91 lakh for the Mairang block's 1,497.62;
        # MGNREGA sheet DATA-013/029, 2026-10-09). When the typed text is exactly
        # a block or constituency name, test it at that level instead; whether
        # it pauses (block vs constituency vs village) is still the gate's call.
        _d_typed = mentions.get("district")
        if isinstance(_d_typed, str) and _d_typed.strip() and not _stated_level:
            _dr = resolve_dimension(_d_typed, _scheme0, "district")
            _typed_up = _tm.collapse_ws(_d_typed).upper()
            if _dr.status == "resolved" and _typed_up != str(_dr.canonical).strip().upper():
                for _dim in ("block", "assembly_constituency"):
                    _br = resolve_dimension(_d_typed, _scheme0, _dim)
                    if _br.status == "resolved" and str(_br.canonical).strip().upper() == _typed_up:
                        mentions = {**{k: v for k, v in mentions.items() if k != "district"}, _dim: _d_typed}
                        logger.info("admin-level gate: %r is %s only by alias but IS the %s %r — "
                                    "testing it at that level", _d_typed, _dr.canonical, _dim, _br.canonical)
                        break
        for _slot in ("district", "block", "village", "assembly_constituency"):
            _name = mentions.get(_slot)
            if not _name:
                continue
            if _cme_urban_block and _name == _cme_urban_block:
                break           # an urban body has one reading: the block (see above)
            # Every admin level this name resolves to. The in-memory catalogues
            # (district / block / assembly_constituency) are checked exact +
            # alias only — never fuzzy, or the gate would fire on almost every
            # name. The village catalogue is DB-backed (curated.dim_geography)
            # so it cannot be in that check; probe it here and pass the result
            # in. That village half is what catches "Sohra": an exact
            # assembly-constituency hit whose only competing reading is a
            # village. Without it the AC hit stands alone, the gate stays
            # quiet, and the old fall-through silently answers about the wrong
            # place.
            # The extractor routinely returns a TRUNCATED mention for a village
            # whose name carries part-markers: "william nagar(mb) - ward no.4"
            # comes back as "william nagar(mb)", which is ambiguous across 12
            # wards and makes this gate ask a question the text already answers
            # (reported 2026-09-17 — the pause repeated forever, the question
            # growing each round). When the raw text contains a LONGER name
            # that resolves to exactly one village, that is the real mention:
            # nothing is ambiguous, so the gate must stand down.
            _scanned = await _scan_village_in_question(_scan_q, _scheme0)
            if _scanned and len(_scanned[1]) > 1:
                # "PHULBARI (ISLAMPUR)" also scans a punctuation twin "Phulbari
                # Islampur" (904639, no scheme rows), so the exact-name test below
                # never fired and the bot asked "Phulbari constituency or Phulbari
                # village?" with neither being the village typed (MGNREGA all-villages
                # run 2026-10-09). The candidate spelled exactly as typed wins.
                _exact = [c for c in _scanned[1]
                          if str(c.get("name") or "").strip().upper() == _scanned[0].strip().upper()]
                if len(_exact) == 1:
                    _scanned = (_scanned[0], _exact)
            if _scanned and len(_scanned[1]) == 1 \
                    and str(_name).strip().lower() in _scanned[0].strip().lower() \
                    and len(_scanned[0]) > len(str(_name)):
                logger.info("admin-level gate: %r is a truncation of %r, which resolves "
                            "to one village — not ambiguous", _name, _scanned[0])
                break
            _vr_probe = await _resolve_village_for(schemes, str(_name))
            try:
                # Trailing punctuation is not part of the comparison: every chip
                # stem strips a final "." ("…BETASING BLOCK HQ." -> "…BETASING BLOCK
                # HQ for FY 2022-23"), which made the village look like a look-alike of
                # the BETASING block (MGNREGA all-villages run 2026-10-09).
                _exact_vil = bool(_scheme0) and _strip_end_punct(str(_name)) in \
                    _village_name_keys(await _scheme_village_names(_scheme0))
            except Exception:  # noqa: BLE001 — without the catalogue, keep the fuzzy check
                _exact_vil = False
            _dims = collides_across_dimensions(
                str(_name), _scheme0,
                village_hit=_vr_probe.status in ("resolved", "ambiguous"),
                exact_village=_exact_vil)
            # CM Elevate's block catalogue lacks 21 of its 66 stored blocks, so a
            # bare "Mawhati" (a block with 204 applications AND two villages) was
            # offered the two villages only (CM Elevate all-blocks run 2026-09-28,
            # KI-107). A name the data stores as a block is a block reading.
            if schemes == ["CM Elevate"] and "block" not in _dims \
                    and (_dblk := await _cm_elevate_block_from_mention(str(_name), schemes)):
                _readings = {**_dims}
                if _vr_probe.status in ("resolved", "ambiguous"):
                    _readings.setdefault("village", "")
                if _readings:
                    _order = ("district", "block", "village", "assembly_constituency")
                    _readings["block"] = _place_title(_dblk)
                    _dims = {k: _readings[k] for k in _order if k in _readings}
            # Drop the assembly-constituency reading when this question's
            # metric has no AC column to read (see _ac_dimension_available) —
            # offering it would invite a choice that can never be answered.
            # If that leaves fewer than two readings, there is nothing left to
            # ask about and the remaining branches resolve it normally.
            if "assembly_constituency" in _dims and not _ac_dimension_available(question, schemes):
                _dims = {k: v for k, v in _dims.items() if k != "assembly_constituency"}
                logger.info("admin-level collision on %r: AC reading suppressed "
                            "(no constituency data for this metric)", _name)
                if len(_dims) < 2:
                    _dims = {}
            if _dims:
                logger.info("admin-level collision on %r: %s — asking", _name, list(_dims))
                raise _dimension_collision_clarification(question, str(_name), _dims)
            break

    # MGNREGA: a bare BLOCK / CONSTITUENCY name the extractor tagged as a village.
    # The collision gate above cannot see it: a block that shares its name with
    # its district's HQ town ("MAIRANG", "MAWKYRWAT") counts as a district hit,
    # which by design ends the check, and a name with a single reading
    # ("KHATARSHNONG LAITKROH") is never ambiguous. The village branch then
    # fuzzy-matched MAIRANG to five look-alike villages, or noted "not a known
    # village", after which the verifier rejected every query and the question
    # fell back to the reference documents (all-blocks QA 2026-09-26). Only when
    # the name is NOT itself an exact village name — a real village of that name
    # keeps the existing block-or-village pause.
    # MGNREGA: the extractor truncates a village whose name carries a qualifier —
    # "JONGCHIPARA (NOKAT)" came back as "JONGCHIPARA", which is a DIFFERENT
    # village (273377, not 273406), answered silently with its 8,848 person-days
    # instead of 0 (all-villages QA 2026-09-26). When the raw question holds a
    # LONGER exact village name that contains the mention, that is the village.
    if _village_scheme(schemes) and not _chip_pinned and _stated_level in (None, "village"):
        _slot = "village" if mentions.get("village") else (
            "block" if mentions.get("block") and resolve_dimension(
                str(mentions["block"]), schemes[0], "block").status != "resolved" else None)
        if _slot:
            _scanned = await _scan_village_in_question(_scan_q, schemes[0])
            _m = str(mentions[_slot]).strip().lower()
            # ...or the SAME name, when the extractor put a village in the block
            # slot and it is not a block: "RONGRA" (village 275928) fuzzy-tied
            # the RONGARA / RONGRAM blocks and drew an option-less "which block?".
            # ...or when the question says "<exact name> village" outright: "person-days
            # for block campus village" came back as block "campus village" and was
            # answered for CENTRE VILLAGE, Ri Bhoi (hierarchy matrix run 2026-10-14).
            if _scanned and ((len(_scanned[0]) > len(_m) and _m in _scanned[0].lower())
                             or (_slot == "block" and _scanned[0].strip().lower() == _m)
                             or (len(_scanned[1]) == 1 and _c09_name_then_village(
                                 _scan_q, _scanned[0].strip()))):
                logger.info("%s village mention %r widened to %r from the question text", schemes[0],
                            mentions[_slot], _scanned[0])
                # Also drop any other place slot that is just a piece of the full
                # name — "LASKARPARA (HAJONG)" came back as block "LASKARPARA" AND
                # district "HAJONG", and the stray "HAJONG" fuzzy-matched five
                # Hajong villages.
                _full = _scanned[0].lower()
                mentions = {**{k: v for k, v in mentions.items()
                               if k not in ("village", "block") and not (
                                   k in ("district", "assembly_constituency") and isinstance(v, str)
                                   and v.strip().lower() in _full)},
                            "village": _scanned[0]}

    # MGNREGA: a village name with "&" / "INCL" / punctuation, found whole in the
    # question, replaces the fragments the extractor made of it (see
    # _mgnrega_longest_village_in). Not when the level is stated as something
    # else, and not when the name is also a block / constituency / district —
    # the collision pause handles those.
    if _village_scheme(schemes) and not _chip_pinned and _stated_level in (None, "village"):
        _full = await _mgnrega_longest_village_in(_scan_q, schemes[0])
        if _full:
            _fn, _fl = _full[0], _full[0].strip().lower()
            # A name that is also a block / AC / district is left to the collision
            # pause — unless the question already chose "the village" (SELSELLA:
            # the extractor returned no place at all, so the village was lost and
            # the SQL compared village_code with the text 'SELSELLA').
            _admin = _stated_level is None and any(
                _tm.collapse_ws(str(c)).lower() == _fl
                for d in ("block", "assembly_constituency", "district")
                for c in canonical_names(schemes[0], d))
            _place = {k: v for k, v in mentions.items() if k in
                      ("village", "block", "blocks", "district", "districts", "assembly_constituency")}

            def _inside(v) -> bool:
                return all(isinstance(x, str) and x.strip().lower() in _fl
                           for x in (v if isinstance(v, list) else [v]))
            if not _admin and all(_inside(v) for v in _place.values()) \
                    and not (list(_place) == ["village"] and str(_place["village"]).strip().lower() == _fl):
                logger.info("%s village %r found whole in the question; replaces %s", schemes[0], _fn, _place)
                mentions = {**{k: v for k, v in mentions.items() if k not in _place}, "village": _fn}

    if _village_scheme(schemes) and _stated_level is None and not village_hint \
            and mentions.get("village") and not any(
                mentions.get(s) for s in ("district", "block", "assembly_constituency",
                                          "districts", "blocks")):
        _reread = await _mgnrega_admin_reading_of_village_mention(str(mentions["village"]), schemes[0])
        if len(_reread) >= 2:
            logger.info("MGNREGA village mention %r is %s — asking", mentions["village"], list(_reread))
            raise _dimension_collision_clarification(question, str(mentions["village"]), _reread)
        if _reread:
            (_dim, _canon), = _reread.items()
            logger.info("MGNREGA village mention %r re-read as %s %r", mentions["village"], _dim, _canon)
            mentions = {**{k: v for k, v in mentions.items() if k != "village"}, _dim: _canon}

    district_canon = None
    if not mentions.get("districts") and schemes:
        # The extractor sometimes returns one district (or none) for a question that
        # names two to compare ("... across Eastern West Khasi Hills and East Garo
        # Hills"); the second was then lost and the SQL compared the wrong district.
        _scanned = scan_districts(question, schemes[0])
        if len(_scanned) >= 2:
            logger.info("resolve_entities: question names districts %s", _scanned)
            mentions = {**{k: v for k, v in mentions.items() if k != "district"}, "districts": _scanned}
    if mentions.get("districts"):
        # Two-or-more named districts to compare against each other (see
        # extract_entity_mentions) — resolve each independently and carry the
        # whole set forward as an IN-list, instead of the singular "district"
        # dimension which can only ever hold one value and would silently
        # drop every district but the last (the "compare ekh and wgh" bug).
        _district_canons: list[str] = []
        _district_displays: list[str] = []
        for _dname in mentions["districts"]:
            r = resolve_dimension(_dname, schemes[0], "district")
            if r.status == "ambiguous":
                raise ClarificationNeeded(f"Which district is being referred to by “{_dname}”?",
                                           rule="entity-ambiguous")
            if r.status != "resolved":
                notes.append(f"'{_dname}' is not a known district — say so, do not filter on it.")
                continue
            _district_canons.append(r.canonical)
            _district_displays.append(r.display or str(_dname).title())
        if _district_canons:
            resolved["district_list"] = _district_canons
            display["district"] = " and ".join(_district_displays)
    else:
        if not mentions.get("district"):
            # The LLM mention-extractor intermittently drops a plainly-named district
            # ("how many villages are covered in West Garo Hills" -> {}); fall back to
            # a deterministic scan of the raw question against the 12-name closed set.
            backstop = scan_dimension(question, schemes[0], "district")
            if backstop and backstop.status == "resolved":
                district_canon = backstop.canonical
                resolved["district"] = backstop.canonical
                display["district"] = backstop.display or str(backstop.canonical).title()
                logger.info("resolve_entities: district backstop matched %r in question text",
                            backstop.canonical)
        # A hill-range name ("Garo Hills", "Khasi region") the extractor tagged as a
        # district isn't one — leave it unresolved so the DATA path's region handler can
        # offer the range's districts as chips (or expand it). Don't raise the generic
        # "which district?" here.
        _mdist = mentions.get("district")
        if _mdist and detect_region(_mdist, schemes[0] if schemes else "") is not None:
            _mdist = None
        if _mdist:
            r = resolve_dimension(_mdist, schemes[0], "district")
            if r.status == "ambiguous":
                raise ClarificationNeeded(f"Which district is being referred to by “{_mdist}”?",
                                           rule="entity-ambiguous")
            if r.status == "resolved":
                district_canon = r.canonical
                resolved["district"] = r.canonical
                display["district"] = r.display or str(r.canonical).title()
            else:
                # Not a known district — it may be a VILLAGE the extractor
                # mistagged as "district" (a bare place name after "in" gives the
                # model no reliable signal for which admin level it is). Try
                # village resolution before concluding this is out of scope.
                _vr = await _resolve_village_for(schemes, _mdist)
                if _vr.status == "ambiguous":
                    listed = ", ".join(
                        f"{c['name']} in {c['block']} block ({c['district']})" for c in _vr.candidates[:_vcap])
                    options = [
                        {"label": _village_chip_label(c, _vr.candidates[:_vcap], schemes),
                         "question": _village_chip_question(question, _mdist, c, schemes, _vr.candidates[:_vcap])}
                        for c in _vr.candidates[:_vcap]
                    ]
                    raise ClarificationNeeded(
                        f"“{_mdist}” corresponds to more than one village: {listed}. "
                        "Which of these is intended?",
                        options=options, rule="entity-ambiguous", village_hint=_mdist)
                if _vr.status == "resolved":
                    resolved["village_code"] = _vr.canonical
                    display["village"] = _vr.display or _place_title(_mdist)
                elif (_cme_blk := await _cm_elevate_block_from_mention(_mdist, schemes)):
                    # "Jowai-municipal Board" tagged as a district: an urban body the
                    # CM Elevate data stores as a block, refused as outside Meghalaya
                    # (CM Elevate all-blocks run 2026-09-28, KI-107).
                    resolved["block"] = _cme_blk
                    display["block"] = _place_title(_cme_blk)
                elif _mgnrega_ac_reading(_mdist, schemes):
                    # An assembly constituency the extractor tagged as a
                    # district. "SOUTH TURA" is neither a district nor a village,
                    # and with only ONE reading the admin-level gate stays quiet,
                    # so it fell through to OutOfScope — "persons employed in
                    # SOUTH TURA" was refused as outside Meghalaya (MGNREGA QA
                    # 2026-09-26, DATA-004/014, KI-042). Hand it to the AC
                    # branch below, which also offers the drill-down.
                    mentions = {**mentions, "assembly_constituency": _mgnrega_ac_reading(_mdist, schemes)}
                    logger.info("district mention %r re-read as MGNREGA assembly constituency", _mdist)
                elif schemes and (_blk_r := resolve_dimension(_mdist, schemes[0], "block")).status == "resolved" \
                        and fold(str(_blk_r.canonical)) == fold(str(_mdist)):
                    # The same for any scheme's own block list: "SHILLONG-MUNICIPAL BOARD"
                    # (a Focus Plus block) tagged as a district was refused as outside
                    # Meghalaya (Focus + sheet FOCUS-004, 2026-10-10). Exact
                    # names only, and after the constituency reading ("SOUTH TURA").
                    logger.info("district mention %r re-read as block %r", _mdist, _blk_r.canonical)
                    resolved["block"] = _blk_r.canonical
                    display["block"] = _blk_r.display or _place_title(_blk_r.canonical)
                elif _c09_not_a_place(_mdist):
                    # Not a place at all: the extractor read the SUBJECT of an
                    # "in which districts …" question as a district (a group
                    # type such as LAMPS read as a district name), and the
                    # question was refused as outside
                    # Meghalaya (NL->SQL accuracy set, 2026-10-16). Drop the mention.
                    logger.info("district mention %r is not a place name — ignored", _mdist)
                elif settings.OUT_OF_SCOPE_GUARD_ENABLED:
                    # Genuinely not a district, block, or village of ours — almost
                    # always a place in another state ("districts in Guwahati").
                    # Don't silently drop the filter and count 0; say plainly
                    # this is out of scope.
                    raise OutOfScope(f"district '{_mdist}' is not in Meghalaya")
                else:
                    notes.append(f"'{_mdist}' is not a known district — say so, do not filter on it.")

    if mentions.get("blocks"):
        # Two-or-more named blocks to compare against each other (see
        # extract_entity_mentions) — resolve each independently and carry the
        # whole set forward as an IN-list, instead of the singular "block"
        # dimension which can only ever hold one value and would silently
        # drop every block but the last.
        # "compare X and Y blocks" names blocks as plainly as "X block" (PMAY-G QA
        # 2026-09-28: PMAY-OFF-023 asked "block or village?" for Mawphlang).
        _has_block_word = any(w in ("block", "blocks") for w in _tm.words(question))
        _block_canons: list[str] = []
        _block_displays: list[str] = []
        # A bare comparison name with no admin-level word ("X or Y", "compare X
        # and Y") gets tagged into this "blocks" array by default (see the
        # extractor prompt's own "tag an ambiguous bare name as block" rule),
        # even when both names are actually VILLAGES — e.g. "which has more
        # completed houses: <village 1> or <village 2>". When a name here
        # isn't a resolvable block at all, it used to just get a "not a known
        # block" note and get dropped; with every name dropped, geography
        # stayed fully unresolved and the generic scope pause fired, offering
        # every district statewide instead of just the two villages named
        # (reported 2026-09-10, PMAY-OFF-022). Try village resolution as a
        # fallback for exactly the names that fail as a block, mirroring the
        # `_vcheck` block-vs-village disambiguation a few lines below.
        _village_canons: list[int] = []
        _village_displays: list[str] = []
        for _bname in mentions["blocks"]:
            r = resolve_dimension(_bname, schemes[0], "block")
            if r.status == "ambiguous":
                raise ClarificationNeeded(f"Which block is being referred to by “{_bname}”?",
                                           rule="entity-ambiguous")
            if r.status != "resolved":
                _vr = await _resolve_village_for(schemes, _bname, district=district_canon)
                if _vr.status == "ambiguous":
                    listed = ", ".join(
                        f"{c['name']} in {c['block']} block ({c['district']})" for c in _vr.candidates[:_vcap])
                    options = [
                        {"label": _village_chip_label(c, _vr.candidates[:_vcap], schemes),
                         "question": _village_chip_question(question, _bname, c, schemes, _vr.candidates[:_vcap])}
                        for c in _vr.candidates[:_vcap]
                    ]
                    raise ClarificationNeeded(
                        f"“{_bname}” corresponds to more than one village: {listed}. "
                        "Which of these is intended?",
                        options=options, rule="entity-ambiguous", village_hint=_bname)
                if _vr.status == "resolved":
                    _village_canons.append(_vr.canonical)
                    _village_displays.append(_vr.display or str(_bname).title())
                else:
                    notes.append(f"'{_bname}' is not a known block or village — say so, "
                                 "do not filter on it.")
                continue
            if not _has_block_word:
                _vcheck = await _resolve_village_for(schemes, _bname)
                if _vcheck.status in ("resolved", "ambiguous"):
                    stem = question.strip().rstrip(" ?.")
                    raise ClarificationNeeded(
                        f"“{_bname}” could mean either the block or a village with "
                        "that name. Which did you mean?",
                        options=[
                            {"label": f"The {_bname} block", "question": f"{stem}, the block, not the village"},
                            {"label": f"The {_bname} village", "question": f"{stem}, the village, not the block"},
                        ],
                        rule="entity-ambiguous")
            _block_canons.append(r.canonical)
            _block_displays.append(r.display or str(_bname).title())
        if _block_canons:
            resolved["block_list"] = _block_canons
            display["block"] = " and ".join(_block_displays)
            # A district named in the same breath as several blocks normally
            # qualifies just ONE of them — it is there to separate a
            # same-named block from its twin elsewhere ("BATABARI block, WEST
            # GARO HILLS": Batabari exists in both South and West Garo Hills).
            # ANDing that district against the WHOLE block list then silently
            # deletes every block that legitimately sits somewhere else:
            # "applicants in Shallang ... BATABARI block, WEST GARO HILLS"
            # returned nothing for Shallang, because Shallang is a WEST KHASI
            # HILLS block and `lgd_district = 'WEST GARO HILLS' AND lgd_block
            # IN ('SHALLANG','BATABARI')` can never match it (reported
            # 2026-09-18). Each block already knows its own district, so drop
            # the standalone district filter whenever the named blocks do not
            # all belong to it — the block names are the more specific filter
            # and they carry their own geography.
            _parents = {b: block_parent_district(b, schemes[0] if schemes else "")
                        for b in _block_canons}
            if district_canon:
                _outside = [b for b, d in _parents.items()
                            if d and d.upper() != str(district_canon).upper()]
                if _outside:
                    logger.info(
                        "district %r dropped: blocks %s sit outside it (block list spans "
                        "districts)", district_canon, _outside)
                    resolved.pop("district", None)
                    display.pop("district", None)
                    district_canon = None
            # Tell the generator which district each block belongs to, so a
            # name that exists in two districts is still pinned to the right
            # one rather than double-counted across both.
            _known = {b: d for b, d in _parents.items() if d}
            if _known:
                resolved["block_list_districts"] = _known
        if _village_canons:
            resolved["village_code_list"] = _village_canons
            display["village"] = " and ".join(_village_displays)
    elif mentions.get("block") or (
            _explicit_level_in(question, schemes) == "block"
            and not mentions.get("village") and not mentions.get("blocks")
            and (_block_scan := scan_dimension(question, schemes[0], "block",
                                               level_is_explicit=True)) is not None
            and _block_scan.status == "resolved"):
        # The extractor drops a plainly-named block just as it drops districts
        # — "in shallang block under Piggery Scheme, PRIME ... (SEED) and
        # Meghalaya Poultry Farming Scheme" returned {} on 5 of 5 calls
        # (2026-09-18), the lowercase name buried between two long scheme
        # names. With no resolved block the generator invented
        # `lgd_block = 'SHALLANG'` off the raw text; the verifier demanded a
        # `lgd_district = 'MEGHALAYA'` filter instead, the state-pseudo-row
        # guard rejected that, the repair put it back, and the loop burned its
        # budget and fell through to the KB fallback. The answer is a plain 45.
        #
        # Only runs when the question names the level outright, so a bare
        # "Shallang" still reaches the village/AC clarification flow.
        if not mentions.get("block"):
            mentions = {**mentions, "block": _block_scan.canonical}
            logger.info("resolve_entities: block backstop matched %r in question text",
                        _block_scan.canonical)
        r = resolve_dimension(mentions["block"], schemes[0], "block")
        if r.status == "ambiguous":
            raise ClarificationNeeded(f"Which block is being referred to by “{mentions['block']}”?",
                                       rule="entity-ambiguous")
        if r.status == "resolved":
            # Block and village names collide constantly in Meghalaya (26 of 56
            # block names are also village names, per the resolver YAML) — a bare
            # name the user didn't explicitly call a "block" is genuinely
            # ambiguous. Silently answering at the block level here is exactly
            # the bug QA reported (bot picks village data for a block question,
            # or vice versa, without ever asking).
            # Same truncation guard as the admin-level gate above: when the raw
            # text carries a LONGER name than this mention and that longer name
            # resolves to exactly one village, the mention is a fragment of it
            # ("william nagar(mb)" from "william nagar(mb) - ward no.4"), not a
            # genuine block-vs-village ambiguity. Resolve the village instead of
            # asking a question the text already answers.
            _longer = await _scan_village_in_question(_scan_q, schemes[0] if schemes else "")
            if _longer and len(_longer[1]) == 1 \
                    and str(mentions["block"]).strip().lower() in _longer[0].strip().lower() \
                    and len(_longer[0]) > len(str(mentions["block"])):
                _pick = _longer[1][0]
                resolved["village_code"] = _pick["village_code"]
                display["village"] = _place_title(_pick["name"])
                logger.info("block mention %r is a truncation of village %r — resolved it",
                            mentions["block"], _longer[0])
            elif "block" not in _tm.words(question) \
                    and not (_cme_urban_block and mentions["block"] == _cme_urban_block):
                _vcheck = await _resolve_village_for(schemes, mentions["block"])
                # Also a constituency of a scheme that holds constituency data: "How many
                # FOCUS Producer Groups are mapped to Mairang?" offered block / village only
                # (Focus Legacy sheet TC-28, 2026-10-12).
                _ac_also = _mgnrega_ac_reading(str(mentions["block"]), schemes) \
                    if _ac_dimension_available(question, schemes) else None
                if _ac_also:
                    _dims3 = {"block": r.display or str(r.canonical).title(),
                              "assembly_constituency": _place_title(_ac_also)}
                    if _vcheck.status in ("resolved", "ambiguous"):
                        _dims3["village"] = ""
                    raise _dimension_collision_clarification(question, str(mentions["block"]), _dims3)
                if _vcheck.status in ("resolved", "ambiguous"):
                    stem = question.strip().rstrip(" ?.")
                    raise ClarificationNeeded(
                        f"“{mentions['block']}” could mean either the block or a village with "
                        "that name. Which did you mean?",
                        options=[
                            {"label": f"The {mentions['block']} block", "question": f"{stem}, the block, not the village"},
                            {"label": f"The {mentions['block']} village", "question": f"{stem}, the village, not the block"},
                        ],
                        rule="entity-ambiguous")
            # Not when the mention turned out to be a truncated VILLAGE name
            # (handled just above): village_code already pins the exact place,
            # and adding the block it was a fragment of would filter a
            # different, larger area alongside it.
            if "village_code" not in resolved:
                resolved["block"] = r.canonical
                display["block"] = r.display or str(r.canonical).title()
                # Same conflict as the block_list branch above, for one block:
                # a district named alongside a block that provably sits in a
                # DIFFERENT district makes `lgd_district = X AND lgd_block = Y`
                # match zero rows. The block is the more specific filter and
                # knows its own district, so keep the block and drop the
                # contradicting district rather than answering "no records".
                _bp = r.parent_district or block_parent_district(
                    r.canonical, schemes[0] if schemes else "")
                if _bp and district_canon and _bp.upper() != str(district_canon).upper():
                    # KI-327 (live 2026-10-19): dropping the district was not enough.
                    # "now give me for Dambo Rongjeng block" after a West Garo Hills
                    # village turn kept "West Garo Hills" in the rewritten text, so the
                    # generator put it back as lgd_district and the answer was 0 for a
                    # block in East Garo Hills. The block's own district now replaces the
                    # stale one in the resolved entities, the "answered for" chip and the
                    # question text; _resolved_district_literal (c10) is the SQL backstop.
                    logger.info("district %r replaced by %r: block %r sits in it",
                                district_canon, _bp, r.canonical)
                    _district_swaps.append((str(district_canon), str(_bp)))
                    resolved["district"] = str(_bp).upper()
                    display["district"] = _place_title(str(_bp))
                    district_canon = str(_bp).upper()
        else:
            # The mention-extractor sometimes tags a full DISTRICT name as the
            # "block" when the question itself says "by block" right next to it
            # ("compare ... by block in West Garo Hills") — it reads the phrase
            # "by block in X" as naming X as the block. Before treating this as
            # not-a-known-block (or, worse, OutOfScope — a real district getting
            # rejected as "not in Meghalaya" is a confusing wrong answer), check
            # whether the same text is actually a district and use it as one.
            _as_district = resolve_dimension(mentions["block"], schemes[0], "district")
            if _as_district.status == "resolved":
                # Either newly discovered here, or (commonly) the SAME text was
                # already captured as the district via the raw-text backstop
                # scan above (mentions.get("district") was empty, so that scan
                # ran on the full question text and found "West Garo Hills"
                # there too) — in that case district_canon is already set and
                # this "block" mention is just a duplicate tag for it. Either
                # way, there's nothing wrong here: don't overwrite an existing
                # district_canon, and don't fall through to "not a known block".
                # Also skip when a district_list comparison already resolved —
                # this "block" mention is then just the extractor's other tag
                # for one of those same districts.
                if not district_canon and not resolved.get("district_list"):
                    district_canon = _as_district.canonical
                    resolved["district"] = _as_district.canonical
                    display["district"] = _as_district.display or str(_as_district.canonical).title()
            elif schemes == ["Focus Plus"] and str(mentions["block"]).strip().upper() == _FP_BLANK_BLOCK:
                # "Nan" is a stored block_name_raw value — the source file's mark
                # for records whose block and district were left blank. It is not
                # a C&RD block, but it IS in the data: saying "not in this data"
                # (and running SELECT 'not available') was wrong. Filter on it
                # and explain it (Focus Plus all-blocks run 2026-09-27).
                resolved["block"] = _FP_BLANK_BLOCK
                display["block"] = "Nan (block not recorded)"
                notes.append(_FP_BLANK_BLOCK_NOTE)
            else:
                # Also not a district — it may be a VILLAGE the extractor
                # mistagged as "block" (villages far outnumber blocks, and a
                # bare name after "in" gives the model no reliable signal for
                # which admin level it is — e.g. "PMAY beneficiaries in
                # Abagre", a real West Garo Hills village). Try village
                # resolution before concluding this is out of scope. Scope by
                # district_canon when the question already pinned one down —
                # otherwise a village-disambiguation chip's own answer text
                # ("Nongthymmai, MAWRYNGKNENG block, EAST KHASI HILLS") gets
                # re-resolved with no district scope, rediscovers the exact
                # same statewide candidate set the chip was meant to narrow,
                # and raises the identical clarification forever (reported
                # 2026-09-09, "nongthymmai" in EAST KHASI HILLS).
                #
                # NOT when the user explicitly said "the block" (an admin-level
                # choice chip, or their own wording): the whole point of that
                # answer is that they do not want the village reading, so
                # quietly resolving one anyway answers at a grain they just
                # declined. Say the block doesn't exist instead.
                if _stated_level == "block":
                    notes.append(
                        f"'{mentions['block']}' is not a C&RD block in this data — say so "
                        "plainly. Do NOT answer using a village or district of the same "
                        "name; the question asked specifically for the block.")
                    _vr = None
                else:
                    _vr = await _resolve_village_for(schemes, mentions["block"], district=district_canon)
                if _vr is not None and _vr.status == "ambiguous":
                    # District scoping alone doesn't always get to one candidate
                    # (e.g. several distinctly-blocked villages share a name inside
                    # the same district). The chip that got us here already names
                    # the intended block in its own text ("Nongthymmai, MAWRYNGKNENG
                    # block, EAST KHASI HILLS") — the LLM extractor just keeps
                    # re-tagging the village as "block" and dropping the real block,
                    # so re-resolving lands back on the SAME candidate set every
                    # round and the clarification loops forever (reported
                    # 2026-09-09, "nongthymmai" in EAST KHASI HILLS). Before asking
                    # again, check the raw text deterministically: if exactly one
                    # candidate's own block name appears in it, that already IS the
                    # user's answer.
                    _text_hits = [
                        c for c in _vr.candidates
                        if c.get("block") and _c09_word_bounded(question, c['block'])
                    ]
                    if len(_text_hits) == 1:
                        _pick = _text_hits[0]
                        resolved["village_code"] = _pick["village_code"]
                        display["village"] = _place_title(_pick["name"])
                        _vr = None
                    else:
                        listed = ", ".join(
                            f"{c['name']} in {c['block']} block ({c['district']})" for c in _vr.candidates[:_vcap])
                        options = [
                            {"label": _village_chip_label(c, _vr.candidates[:_vcap], schemes),
                             "question": _village_chip_question(question, mentions["block"], c, schemes, _vr.candidates[:_vcap])}
                            for c in _vr.candidates[:_vcap]
                        ]
                        raise ClarificationNeeded(
                            f"“{mentions['block']}” corresponds to more than one village: {listed}. "
                            "Which of these is intended?",
                            options=options, rule="entity-ambiguous", village_hint=mentions["block"])
                if _vr is None:
                    pass  # already resolved directly from the single text hit above
                elif _vr.status == "resolved":
                    resolved["village_code"] = _vr.canonical
                    display["village"] = _vr.display or _place_title(mentions["block"])
                elif (_cme_blk := await _cm_elevate_block_from_mention(mentions["block"], schemes)):
                    resolved["block"] = _cme_blk          # an urban body stored as a block (KI-107)
                    display["block"] = _place_title(_cme_blk)
                elif settings.OUT_OF_SCOPE_GUARD_ENABLED:
                    raise OutOfScope(f"block '{mentions['block']}' is not in Meghalaya")
                else:
                    notes.append(f"'{mentions['block']}' is not a known block — say so, do not filter on it.")

    if mentions.get("assembly_constituency"):
        r = resolve_dimension(mentions["assembly_constituency"], schemes[0], "assembly_constituency")
        if r.status == "ambiguous":
            raise ClarificationNeeded(
                f"Which assembly constituency is being referred to by "
                f"“{mentions['assembly_constituency']}”?", rule="entity-ambiguous")
        if r.status == "resolved":
            resolved["assembly_constituency"] = r.canonical
            display["assembly_constituency"] = r.display or str(r.canonical).title()
            # Step 2 of the hierarchy: having settled that this IS the
            # constituency, offer to narrow inside it. Only when the question
            # hasn't already narrowed itself — a resumed drill-down chip says
            # "within the X block only" / "the whole constituency", and a
            # question that independently names a district/block/village has
            # answered this too. Best-effort: if the contents can't be read,
            # the flow continues with the whole constituency, as before.
            _already_narrowed = (
                _AC_SCOPED_MATCH.search(question)
                or _C09_WHOLE_CONSTITUENCY.search(question)
                # The user typed "<X> constituency" themselves: they asked for the
                # constituency, so "the whole constituency, or part of it?" is a
                # needless extra tap (all 56 constituencies paused on every
                # DATA-004 / DATA-014 question, MGNREGA sheet run 2026-10-09).
                # The drill-down stays for a name that only became a
                # constituency through the which-area-type chip.
                or (_USER_NAMED_CONSTITUENCY.search(question)
                    and not _AC_COLLISION_CHIP.search(question))
                or any(resolved.get(k) for k in
                       ("district", "district_list", "block", "block_list",
                        "village_code", "village_code_list"))
            )
            _narrow = _AC_NARROW_MATCH.search(question)
            if _narrow:
                # A resumed drill-down chip — apply its district/block filter
                # alongside the constituency, so the answer covers exactly the
                # overlap the user asked for.
                _lvl = _narrow.group("level").lower()
                _nm = _narrow.group("name").strip()
                _nr = resolve_dimension(_nm, schemes[0], _lvl)
                if _nr.status == "resolved":
                    _canon, _disp = _nr.canonical, _nr.display or str(_nr.canonical).title()
                else:
                    # These chips are built from values read live out of
                    # curated.v_employment (constituency_contents), and the
                    # YAML block catalogue does not necessarily list every one
                    # of them. The value came from the database itself, so it
                    # is a valid literal even when the catalogue has no entry
                    # — use it rather than dropping the narrowing the user
                    # explicitly picked. Storage is upper-case for both
                    # lgd_district and lgd_block (docs/DATA_MODEL.md).
                    _canon, _disp = _nm.upper(), _nm.title()
                resolved[_lvl] = _canon
                display[_lvl] = _disp
                if _lvl == "district":
                    district_canon = _canon
                logger.info("AC drill-down: also filtering %s = %r", _lvl, _canon)
            elif not _already_narrowed:
                _contents = await constituency_contents(str(r.canonical), schemes[0] if schemes else None)
                _drill = _ac_drilldown_clarification(
                    question, display["assembly_constituency"], _contents,
                    schemes[0] if schemes else None)
                if _drill is not None:
                    raise _drill
        else:
            # assembly_constituency data exists ONLY in mgnrega_employment (no
            # catalogue loaded for other schemes, or the name genuinely isn't
            # one) — say so instead of silently falling back to a block/
            # district filter, which would answer a different, unintended level.
            notes.append(
                f"'{mentions['assembly_constituency']}' is not a known assembly constituency "
                f"for {schemes[0] if schemes else 'this scheme'} — say so, do not silently "
                "filter on a block or district instead.")

    if mentions.get("year"):
        raw_year = mentions["year"]
        year_key = None
        # MGNREGA has a curated year catalogue (handles aliases like "FY24",
        # "last year"); try it first when MGNREGA is in play.
        if "MGNREGA" in schemes:
            r = resolve_dimension(raw_year, "MGNREGA", "year")
            if r.status == "ambiguous":
                raise ClarificationNeeded(f"Which financial year is being referred to by “{raw_year}”?")
            if r.status == "resolved":
                year_key = r.canonical
        # Fallback / PMAY path — PMAY has no year catalogue, so parse the FY start
        # year straight from the text ("2023", "2023-24", "FY 2023-24" -> 2023).
        if year_key is None:
            year_key = _parse_year_key(raw_year)
        if year_key is not None and not _year_in_data_range(year_key, schemes):
            # A real, parseable year — just not one these scheme(s) hold.
            if settings.YEAR_RANGE_GUARD_ENABLED:
                raise _year_out_of_range_clarification(question, raw_year, schemes)
            _yrs, _lv = _available_years_for(schemes)
            notes.append(f"'{raw_year}' is outside the data "
                         f"({', '.join(_lv)} cover FY {_yrs[0]} to FY {_yrs[-1]} only).")
        elif year_key is None:
            # Couldn't pin it to a year at all. If it was plainly typed as one
            # ("1999-20", "FY 2019-20"), it's an out-of-range year we simply
            # failed to parse — say the coverage, same as above; otherwise it's
            # gibberish in the year slot, so leave a soft note and move on.
            if settings.YEAR_RANGE_GUARD_ENABLED and _looks_like_year_mention(raw_year):
                raise _year_out_of_range_clarification(question, raw_year, schemes)
            notes.append(f"'{raw_year}' is not a recognisable financial year.")
        else:
            # Both v_employment and v_pmay key the year on `year_key` (smallint).
            resolved["year_key"] = year_key
            display["year"] = f"FY {year_key}-{(year_key + 1) % 100:02d}"

    # Prefer the current question's own village mention; fall back to the
    # remembered hint from a just-resumed village-ambiguity pause only when
    # this turn's extraction found no village at all (see the docstring above).
    #
    # A question that states a NON-village level outright ("..., the assembly
    # constituency, not another area type" — a resumed admin-level collision
    # chip) must not resolve a village at all: the pending village hint is
    # stale in that case (it was remembered when the level was still open), and
    # the block/district branches above have already placed the name at the
    # level the user chose. Letting it through set village_code alongside the
    # chosen level, which then filters the query down to one village even
    # though the user explicitly asked for the constituency.
    _village_text = mentions.get("village") or village_hint
    if _stated_level is not None and _stated_level != "village":
        _village_text = None
    # Deterministic backstop for a village the extractor dropped (see
    # _scan_village_in_question). Only when NOTHING else already placed this
    # turn's geography at village grain, and only when the question names no
    # block/AC of its own for the same span — those dimensions own their names.
    # Skipped when the question states a level of its own: either the user
    # chose "village" (in which case the extractor's own mention already went
    # down the normal village path above) or they chose a NON-village level,
    # and filling a village in behind that choice would answer at a grain they
    # explicitly declined.
    if not _village_text and not resolved.get("village_code") \
            and not resolved.get("village_code_list") and _stated_level is None:
        _scanned = await _scan_village_in_question(_scan_q, schemes[0] if schemes else "")
        if _scanned:
            _vname, _vhits = _scanned
            if _village_scheme(schemes):   # see _resolve_village_for
                _vhits = [c for c in _vhits if not str(c.get("name", "")).strip().lower()
                          .startswith("unresolved")] or _vhits
            _vhits = await _fl_rank_villages(schemes, _vhits)
            if list(schemes or []) == ["MGNREGA"]:
                _vhits = await _mgnrega_villages_with_data(_vhits)
            logger.info("village backstop: %r matched %d village(s) in the question text "
                        "the extractor dropped", _vname, len(_vhits))
            # The village found IS the block already placed ("in Rambrai under Piggery,
            # SEED and Poultry": block RAMBRAI and village Rambrai) — the level was
            # never stated, so ask instead of silently narrowing the block to the
            # village (11 applicants for the block's 106; CM Elevate sheet OFF-010,
            # run 2026-10-10).
            _blk0 = resolved.get("block")
            if _blk0 and _vhits and _tm.collapse_ws(str(_vname)).upper() == str(_blk0).strip().upper():
                raise _dimension_collision_clarification(
                    question, str(_vname), {"block": display.get("block") or _place_title(str(_blk0)), "village": ""})
            # Narrow by a district the question already pinned before deciding
            # whether this is still ambiguous — "ASIMGRE ... for East Garo
            # Hills" has exactly one ASIMGRE in that district.
            # Narrow by a block the question already pinned first — it is the
            # finer of the two scopes, and a resumed village chip names both
            # ("..., SELSELLA block, WEST GARO HILLS"). Without this the
            # district scope alone can still leave several same-named villages
            # and the chip resolves only to block grain, losing the village.
            _blk = resolved.get("block")
            if _blk:
                _by_block = [c for c in _vhits
                             if str(c.get("block") or "").upper() == str(_blk).upper()]
                if _by_block:
                    _vhits = _by_block
            if district_canon:
                _scoped = [c for c in _vhits
                           if str(c["district"]).upper() == str(district_canon).upper()]
                if _scoped:
                    _vhits = _scoped
                elif _blk and len(_vhits) == 1:
                    # The block filter already pinned exactly one village; the
                    # district mismatch is just the stale one from the original
                    # question, so let the block's own district stand.
                    district_canon = _vhits[0]["district"]
                    resolved["district"] = _vhits[0]["district"]
                    display["district"] = str(_vhits[0]["district"]).title()
                else:
                    # The question named a district AND a village, but no
                    # village of that name exists there ("ASIMGRE ... for East
                    # Khasi Hills" — every ASIMGRE is in the Garo Hills). The
                    # two filters contradict each other, so neither answering
                    # district-wide (the old silent-drop bug, which reported a
                    # whole district's figure as though it were the village's)
                    # nor offering villages in OTHER districts is right. Say
                    # so plainly instead.
                    _dname = display.get("district") or str(district_canon).title()
                    _elsewhere = ", ".join(sorted({str(c["district"]).title() for c in _vhits}))
                    # Each village chip must drop the district the user named,
                    # or the resumed question carries TWO conflicting districts
                    # ("... for East Khasi Hills ..., SELSELLA block, WEST GARO
                    # HILLS") and resolves to neither the village nor the right
                    # district. Strip the original district phrase first, then
                    # let _village_chip_question pin the village.
                    _nd = _c07_place_phrase_span(question, str(_dname), ("in", "for", "of", "at", "from"),
                                                 tail=False, word_end=True)
                    _no_dist = (question[:_nd[0]] + question[_nd[1]:] if _nd else question).strip()
                    raise ClarificationNeeded(
                        f"There is no village called “{_vname}” in {_dname}. "
                        f"Villages with that name are in {_elsewhere}. Did you mean one of "
                        f"those, or the whole of {_dname}?",
                        options=[
                            {"label": _village_chip_label(c, _vhits[:_vcap], schemes),
                             "question": _village_chip_question(_no_dist, _vname, c, schemes, _vhits[:_vcap])}
                            for c in _vhits[:_vcap]
                        ] + [{
                            "label": f"All of {_dname}",
                            "question": _drop_place_phrase(question, _vname),
                        }],
                        rule="entity-ambiguous")
            if len(_vhits) == 1:
                resolved["village_code"] = _vhits[0]["village_code"]
                display["village"] = _place_title(_vhits[0]["name"])
            else:
                # Several real villages share this name — ask, never guess.
                listed = ", ".join(
                    f"{c['name']} in {c['block']} block ({c['district']})" for c in _vhits[:_vcap])
                raise ClarificationNeeded(
                    f"“{_vname}” corresponds to more than one village: {listed}. "
                    "Which of these is intended?",
                    options=[
                        {"label": _village_chip_label(c, _vhits[:_vcap], schemes),
                         "question": _village_chip_question(question, _vname, c, schemes, _vhits[:_vcap])}
                        for c in _vhits[:_vcap]
                    ],
                    rule="entity-ambiguous", village_hint=_vname)
    if _village_text:
        r = await _resolve_village_for(schemes, _village_text, district=district_canon,
                                   block=resolved.get("block"))
        if r.status == "ambiguous":
            # Two candidates can share the same (name, district) while being
            # genuinely different villages in different blocks with their own
            # data (e.g. two "Adugre"s in SOUTH WEST GARO HILLS — one in
            # Betasing block, one in Rerapara) — block is the distinguishing
            # feature, so it MUST be in both the message and the chip label, or
            # they read as duplicates and the user can't tell them apart.
            listed = ", ".join(
                f"{c['name']} in {c['block']} block ({c['district']})" for c in r.candidates[:_vcap])
            options = [
                {"label": _village_chip_label(c, r.candidates[:_vcap], schemes),
                 "question": _village_chip_question(question, _village_text, c, schemes, r.candidates[:_vcap])}
                for c in r.candidates[:_vcap]
            ]
            raise ClarificationNeeded(
                f"“{_village_text}” corresponds to more than one village: {listed}. "
                "Which of these is intended?",
                options=options,
                rule="entity-ambiguous",
                village_hint=_village_text)
        if r.status == "resolved":
            # Symmetric check to the block branch above: this name might also be
            # a block name. Only worth asking when the district/block scope
            # didn't already pin it down (a village resolved WITH a district
            # scope is unambiguous) and the user didn't already say "village".
            if not district_canon and "village" not in _tm.words(question):
                _bcheck = resolve_dimension(_village_text, schemes[0], "block")
                # Only a block of the SAME name competes: "MYNRI UMSNING" (a village)
                # fuzzy-resolves to the UMSNING block because one name holds the
                # other, and was asked "the village or the block?" (MGNREGA
                # all-villages run 2026-10-09).
                _same_block = _bcheck.status == "resolved" and _tm.collapse_ws(
                    str(_bcheck.canonical)).upper() == _tm.collapse_ws(str(_village_text)).upper()
                if _same_block:
                    stem = question.strip().rstrip(" ?.")
                    raise ClarificationNeeded(
                        f"“{_village_text}” could mean either the village or a block "
                        "with that name. Which did you mean?",
                        options=[
                            {"label": f"The {_village_text} village", "question": f"{stem}, the village, not the block"},
                            {"label": f"The {_village_text} block", "question": f"{stem}, the block, not the village"},
                        ],
                        rule="entity-ambiguous")
            resolved["village_code"] = r.canonical
            display["village"] = r.display or _place_title(_village_text)
        else:
            # KI-327 (live 2026-10-19): "now give me for dambo rongjeng" after a
            # village turn. The rewrite guessed "village" for a name that is a BLOCK
            # and no village; the note below left the place unresolved and the
            # generator filtered the block from the text on its own, under the
            # inherited district. A name that is no village but exactly a block is
            # the block, unless the user chose "the village" on a collision chip.
            _as_block = resolve_dimension(_village_text, schemes[0], "block") if schemes else None
            _exact_block = (_as_block is not None and _as_block.status == "resolved"
                            and _tm.collapse_ws(str(_as_block.canonical)).upper()
                            == _tm.collapse_ws(str(_village_text)).upper())
            if (_exact_block and not resolved.get("block") and not resolved.get("block_list")
                    and not _c09_chose_village(question)):
                logger.info("village %r is no village but exactly the block %r: placed as the block",
                            _village_text, _as_block.canonical)
                resolved["block"] = _as_block.canonical
                display["block"] = _as_block.display or _place_title(str(_as_block.canonical))
                _bp = _as_block.parent_district or block_parent_district(
                    str(_as_block.canonical), schemes[0] if schemes else "")
                if _bp and district_canon and _bp.upper() != str(district_canon).upper():
                    logger.info("district %r replaced by %r: block %r sits in it",
                                district_canon, _bp, _as_block.canonical)
                    _district_swaps.append((str(district_canon), str(_bp)))
                    resolved["district"] = str(_bp).upper()
                    display["district"] = _place_title(str(_bp))
                    district_canon = str(_bp).upper()
            else:
                notes.append(f"'{_village_text}' is not a known village — say so, do not filter on it.")

    # PMAY house-construction-stage ("Proposed Site", "Existing site(Old House)",
    # "plinth stage", "not started", …). A closed set the LLM mention-extractor
    # above doesn't cover — matched deterministically against the SME alias
    # catalogue over the whole question. "completed" / "in progress" are left to
    # the is_completed / is_in_progress boolean path on purpose.
    if "PMAY-G" in schemes:
        hs = resolve_house_status(question, "PMAY-G")
        if hs and hs.values:
            resolved["house_status"] = hs.values if len(hs.values) > 1 else hs.values[0]
            display["house_status"] = hs.display or " and ".join(hs.values)

    # Focus Plus tranche_label ("Tranch 1".."Tranch 4 - Feb-March") — closed set,
    # not covered by the LLM mention-extractor, and routinely mistyped against
    # its odd stored spelling ("tranche2" vs "Tranch 2 - August"). Resolved
    # deterministically (with a RapidFuzz fallback for misspellings) so a
    # near-miss maps to the exact stored label instead of silently filtering
    # the SQL to zero rows and reporting a misleading null total.
    if "Focus Plus" in schemes:
        tr = resolve_tranche_label(question, "Focus Plus")
        if tr and tr.values:
            resolved["tranche_label"] = tr.values if len(tr.values) > 1 else tr.values[0]
            display["tranche_label"] = tr.display or " and ".join(tr.values)

    # CM Elevate sub-scheme ("Piggery", "Dairy Development", ... — a 15-value
    # closed set) — resolved deterministically against the SME alias catalogue.
    # Without this, a typo'd or loosely-phrased sub-scheme name reaches the SQL
    # generator as raw text, which then guesses a scheme_name literal that
    # doesn't exactly match storage and silently counts zero rows (see
    # resolve_cm_scheme's docstring).
    if "CM Elevate" in schemes:
        cs = resolve_cm_scheme(question, "CM Elevate")
        if cs and cs.values:
            resolved["cm_scheme"] = cs.values if len(cs.values) > 1 else cs.values[0]
            display["cm_scheme"] = cs.display or " and ".join(cs.values)
        else:
            # resolve_cm_scheme found no single real sub-scheme — check whether
            # the question instead named a scheme-FAMILY word in the singular
            # ("the vehicle scheme") that covers 2+ real, non-interchangeable
            # sub-schemes. Left unhandled, this reached the SQL generator as
            # bare text, which guessed a scheme_name literal that doesn't exist
            # ('Meghalaya Vehicle Scheme') and silently returned 0 rows dressed
            # up as a refusal (confirmed live 2026-09-11) — exactly the "never
            # guess, ask" case cmelevate_entity_resolver.yaml's overloaded_terms
            # section documents but was never wired to any code path.
            grp = resolve_cm_scheme_group_ambiguity(question, "CM Elevate")
            if grp:
                raise _cm_scheme_group_clarification(question, grp)
            # Not singular-ambiguous — check the PLURAL/collective reading
            # ("vehicle schemes", "livestock", "PRIME family"): a real,
            # already-answerable group-breakdown question (cmelevate_few_shot.yaml
            # has worked IN-list examples), not something to ask about. Populate
            # cm_scheme as a multi-value resolve, same shape resolve_cm_scheme
            # itself uses for "compare Piggery and Poultry" — without this, the
            # SQL generator's hardcoded IN-list for the group got rejected by the
            # semantic verifier for having no resolved entity to justify it
            # (confirmed live 2026-09-11, once the routing fix above let this
            # question reach SQL generation for the first time).
            grp2 = resolve_cm_scheme_group(question, "CM Elevate")
            if grp2:
                resolved["cm_scheme"] = grp2["schemes"]
                display["cm_scheme"] = f"the {grp2['group']} schemes ({', '.join(grp2['schemes'])})"

    # CM Elevate Legacy's 13 schemes — its OWN catalogue (the stored spellings
    # differ from the applications dataset's: 'Prime Tourism Vehicle Scheme' vs
    # 'PRIME Tourism Vehicle Scheme'), resolved into the same cm_scheme slot.
    # Skipped when the applications dataset is also in play, so the two
    # catalogues never overwrite each other's literal.
    if "CM Elevate Legacy" in schemes and "CM Elevate" not in schemes:
        _seri = _cm_legacy_sericulture_choice(question)
        if _seri == "ask":
            raise _cm_legacy_sericulture_clarification(question)
        cs = resolve_cm_scheme(question, "CM Elevate Legacy")
        if _seri:
            resolved["cm_scheme"] = _seri if len(_seri) > 1 else _seri[0]
            display["cm_scheme"] = " and ".join(_seri)
        elif cs and cs.values:
            resolved["cm_scheme"] = cs.values if len(cs.values) > 1 else cs.values[0]
            display["cm_scheme"] = cs.display or " and ".join(cs.values)

    # An assembly constituency cuts across districts (8 of 56 straddle two), so a
    # district the user never named must not narrow it. Seen 2026-09-25 (CM
    # Elevate Legacy TC-31, "applications mapped to Mairang constituency"):
    # resolution returned district EASTERN WEST KHASI HILLS beside the AC — Mairang
    # is also a block there — and the SQL ANDed it in. Harmless for Mairang, which
    # sits wholly in that district; a silent undercount for a straddling one. A
    # district the user did name (or picked via the ", within the X district only"
    # chip) is in the question text, so the resolver's own scan finds it and it stays.
    if resolved.get("assembly_constituency") and resolved.get("district"):
        _named = scan_dimension(_scan_q, schemes[0] if schemes else "", "district")
        if not (_named and _named.status == "resolved"
                and str(_named.canonical).upper() == str(resolved["district"]).upper()):
            logger.info("AC %r: dropped district %r — not named in the question",
                        resolved["assembly_constituency"], resolved["district"])
            resolved.pop("district", None)
            display.pop("district", None)

    if prior_resolved:
        if not mentions.get("district") and "district" not in resolved and prior_resolved.get("district") \
                and not resolved.get("assembly_constituency"):
            resolved["district"] = prior_resolved["district"]
        if not mentions.get("block") and "block" not in resolved and prior_resolved.get("block"):
            resolved["block"] = prior_resolved["block"]
        if not mentions.get("year") and "year_key" not in resolved and prior_resolved.get("year_key"):
            resolved["year_key"] = prior_resolved["year_key"]
        if not mentions.get("village") and "village_code" not in resolved and prior_resolved.get("village_code"):
            resolved["village_code"] = prior_resolved["village_code"]
        # Focus Plus tranche pin — same fallback as district/block/village/year
        # above. There is no LLM `mentions` signal for tranche_label (it's
        # resolved deterministically, not via mention extraction — see
        # resolve_tranche_label), so the only guard needed is that THIS
        # question's own resolution found nothing: a bare short follow-up
        # ("top 3 only") that never re-says "tranche" would otherwise lose the
        # tranche the previous turn pinned. Only ever carries a real stored
        # label — never a sentinel — so it stays safe to drop straight into
        # the SQL prompt's tranche_label filter (see prompt_builder._entities_block).
        if (schemes == ["Focus Plus"] and "tranche_label" not in resolved
                and prior_resolved.get("tranche_label")):
            resolved["tranche_label"] = prior_resolved["tranche_label"]
        # CM Elevate sub-scheme pin — same fallback as tranche_label above:
        # there is no LLM `mentions` signal for cm_scheme (resolved
        # deterministically, not via mention extraction), so a bare follow-up
        # that never re-names the sub-scheme would otherwise lose it.
        if (schemes == ["CM Elevate"] and "cm_scheme" not in resolved
                and prior_resolved.get("cm_scheme")):
            resolved["cm_scheme"] = prior_resolved["cm_scheme"]
        # Same carry for CM Elevate Legacy — but only a value from ITS catalogue,
        # so a sub-scheme pinned while talking about the applications dataset
        # cannot leak a literal this view does not store.
        if (schemes == ["CM Elevate Legacy"] and "cm_scheme" not in resolved
                and prior_resolved.get("cm_scheme")):
            _prior = prior_resolved["cm_scheme"]
            _vals = _prior if isinstance(_prior, list) else [_prior]
            _known = set(canonical_names("CM Elevate Legacy", "cm_scheme"))
            if _vals and all(v in _known for v in _vals):
                resolved["cm_scheme"] = _prior

    # PMAY-G: a village named beside its own block / district is the village, not
    # the block (see _pmay_village_beside_block). village_code alone goes to SQL,
    # as for a pinned village chip.
    # The block / district reach `resolved` in whatever slot the extractor picked
    # (block, a one-element block_list, district, a one-element district_list), or
    # not at all ("Baghmara …, RERAPARA block" came back as block BAGHMARA). An
    # explicit ", <X> block, <DISTRICT>" tail in the text is read directly and wins
    # (PMAY-G village-with-block run, 2026-09-28).
    # CM Elevate uses the same step (all-villages run 2026-09-28, KI-106): "RANGSAGRE,
    # Dadenggiri block" put RANGSAGRE in the district slot and returned no record.
    _vb_scheme = schemes[0] if schemes in (["PMAY-G"], ["CM Elevate"]) else None
    # CM Elevate: map the block to its stored spelling FIRST, so "Umrangksai,
    # Nongpoh-town Committee block" matches the villages stored under
    # "NONGPOH-TOWN COMMITTEE" (all-villages run 2026-09-28: every urban-body
    # village lost its village and was answered for the whole body, KI-107).
    if _vb_scheme == "CM Elevate" and (resolved.get("block") or resolved.get("block_list")):
        await _cm_elevate_blocks_to_data(question, resolved, display)
    # CM Elevate: "Mawker, Mawhati block" came back as village_code_list [277780] +
    # block_list ['MAWHATI'] — the comparison shape — and the SQL filtered the block
    # alone (204 applications for a village of 3; final pass 2026-09-28, KI-119).
    # One village plus only its own block is one village.
    if _vb_scheme == "CM Elevate" and len(resolved.get("village_code_list") or []) == 1:
        _code = resolved["village_code_list"][0]
        try:
            _own = next((c for v in (await _cm_elevate_village_names()).values() for c in v
                         if c["village_code"] == _code), None)
        except Exception:  # noqa: BLE001
            _own = None
        _blks = {str(b).upper() for b in (resolved.get("block_list") or [])} | (
            {str(resolved["block"]).upper()} if resolved.get("block") else set())
        if _own and _blks <= {str(_own["block"]).upper()}:
            resolved["village_code"] = _code
            for _k in ("village_code_list", "block_list", "block_list_districts", "block"):
                resolved.pop(_k, None)
            display["village"] = _place_title(str(_own["name"]))
            logger.info("CM Elevate: one village beside its own block — village %s, not a list", _code)
    _pm_vname = None
    if _vb_scheme and resolved.get("village_code") is not None:
        try:
            _pm_vname = next((n for n, cs in (await _scheme_village_names(_vb_scheme)).items()
                              if any(c["village_code"] == resolved["village_code"] for c in cs)), None)
        except Exception:  # noqa: BLE001
            _pm_vname = None
    if (_vb_scheme and not resolved.get("village_code_list")
            and (resolved.get("village_code") is None or _pm_vname)
            and len(set(resolved.get("block_list") or [])) <= 1 and len(set(resolved.get("district_list") or [])) <= 1
            and not resolved.get("district_list_region")):
        _blk = resolved.get("block") or (resolved.get("block_list") or [None])[0]
        _dst = resolved.get("district") or (resolved.get("district_list") or [None])[0]
        # ", <X> block[, <DISTRICT>]" anywhere in the text (a chip tail ends the
        # question; a typed "baghmara, Rerapara block across all financial years"
        # does not). X must be a PMAY-G block name.
        _pm_blocks = {str(c).strip().upper() for c in canonical_names(_vb_scheme, "block")}
        if _vb_scheme == "CM Elevate":       # the stored spellings, urban bodies included
            try:
                _pm_blocks |= set(await _cm_elevate_block_names())
            except Exception:  # noqa: BLE001
                pass
        _pm_dists = {str(c).strip().upper() for c in canonical_names(_vb_scheme, "district")}
        for _bm in _C09_BLOCK_BESIDE.finditer(question or ""):
            _tb = _tm.collapse_ws(_bm.group(1)).upper()
            _tb = next((b for b in _pm_blocks if _tb == b or _tb.endswith(" " + b)), None)
            if _tb:
                _blk = _tb
                _td = _tm.collapse_ws(_bm.group(2) or "").upper()
                _dst = _td if _td in _pm_dists else (_dst if _blk == resolved.get("block") else None)
        _vb = (await _pmay_village_beside_block(question, {"block": _blk, "district": _dst}, _vb_scheme)
               if (_blk or _dst) else None)
        # A village already resolved stays, unless it is only the stated block's
        # namesake ("model village, Umling block" resolved to the village UMLING and
        # answered for it — PMAY-G scenario run 2026-09-28).
        if _vb and resolved.get("village_code") is not None and not (
                _pm_vname and _blk and _pm_vname == _blk and _vb["village_code"] != resolved["village_code"]):
            _vb = None
        if _vb:
            logger.info("%s village %r named beside %s — the village, not the area", _vb_scheme, _vb["name"],
                        _blk or _dst)
            resolved["village_code"] = _vb["village_code"]
            for _k in ("block", "block_list", "block_list_districts", "district", "district_list"):
                resolved.pop(_k, None)
            display["village"] = _place_title(str(_vb["name"]))
            display["block"] = str(_vb.get("block") or "").upper()
            _areas = {str(x).upper() for x in (_blk, _dst) if x}
            notes = [n for n in notes if not (
                (_nk := _c09_not_known_name(n or "")) is not None and _nk.strip().upper() in _areas)]

    # A one-village list beside a block is not a finished comparison: "PECHUA or
    # LASKEIN, the village, not the block" resolved village_code_list [PECHUA] +
    # block_list [LASKEIN] — the reading the user's chip had just REJECTED — and
    # every SQL attempt failed (PMAY-G officer cases run 2026-10-02, OFF-022).
    _chose_village = _c09_chose_village(question or "")
    if (schemes == ["PMAY-G"] and len(resolved.get("village_code_list") or []) < 2
            and (not resolved.get("block_list") or _chose_village)
            and not resolved.get("district_list") and _PMAY_COMPARE_CUE_MATCH.search(question or "")):
        _two = await _pmay_two_villages(question)
        if _two:
            logger.info("PMAY-G comparison of two villages %s", [c["name"] for c in _two])
            for _k in ("village_code", "block", "block_list", "block_list_districts", "district"):
                resolved.pop(_k, None)
            resolved["village_code_list"] = [c["village_code"] for c in _two]
            display["village"] = " and ".join(_place_title(str(c["name"])) for c in _two)

    if schemes == ["CM Elevate"] and (resolved.get("block") or resolved.get("block_list")):
        await _cm_elevate_blocks_to_data(question, resolved, display)
    if schemes == ["CM Elevate Legacy"] and (resolved.get("block") or resolved.get("block_list")):
        await _cm_elevate_blocks_to_data(question, resolved, display, "CM Elevate Legacy")
    if schemes == ["Focus Plus"] and (resolved.get("block") or resolved.get("block_list")):
        await _cm_elevate_blocks_to_data(question, resolved, display, "Focus Plus")

    out = {"resolved": resolved, "notes": notes, "display": display}
    if _district_swaps:
        # The stale district name leaves the question text too, else SQL
        # generation reads it back from there (KI-327).
        for _old_d, _new_d in _district_swaps:
            question = _c09_swap_place_name(question, _old_d, _place_title(_new_d))
        out["question"] = question
    if _year_gap_note:
        # _apply_year_gap rewrote the question (the absent year stripped, or
        # swapped for the nearest year with data on a comparison). SQL must be
        # generated from THAT text: from the original, the generator filtered
        # on the absent year and the note above then contradicted the result
        # (TC-24, 2026-09-25: "2024-25: 114,990,000" with no 2023-24 mention).
        out["question"] = question
    return out


# ── plain-Python text helpers for this file (D-047) ────────────────────────

def _c09_is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _c09_word_bounded(text: str, needle: str) -> bool:
    r"""`needle` with a word edge at both ends, case-insensitive (a word edge is
    a change between a word character and a non-word one)."""
    text, n = text or "", len(text or "")

    def _b(i: int) -> bool:
        return (i > 0 and _c09_is_word(text[i - 1])) != (i < n and _c09_is_word(text[i]))

    pos = 0
    while True:
        i = _ci_find(text, needle, pos)
        if i < 0:
            return False
        if _b(i) and _b(i + len(needle)):
            return True
        pos = i + 1


def _c09_urban_suffix_end(text: str, j: int) -> int:
    r"""End of any spaces/dashes then "municipal" (optionally spaces + "board"),
    "town" + spaces + "committee", or a whole-word "mb" / "tc" (each letter pair
    may have an optional '.' and one optional space between) at j
    (case-insensitive), or -1."""
    n = len(text)
    while j < n and (text[j].isspace() or text[j] == "-"):
        j += 1
    low = text.lower()
    if low.startswith("municipal", j):
        e = j + 9
        b = _ws_run_end(text, e)
        if b > e and low.startswith("board", b):
            return b + 5
        return e
    if low.startswith("town", j):
        b = _ws_run_end(text, j + 4)
        if b > j + 4 and low.startswith("committee", b):
            return b + 9
    for a, c in (("m", "b"), ("t", "c")):
        if low.startswith(a, j):
            k = j + 1
            if k < n and text[k] == ".":
                k += 1
            if k < n and text[k].isspace():
                k += 1
            if low.startswith(c, k) and (k + 1 >= n or not _c09_is_word(text[k + 1])):
                return k + 1
    return -1


def _c09_name_with_urban_suffix(text: str, name: str) -> "str | None":
    """The text of `<name><urban-body suffix>` ("Tura MB", "Shillong-Municipal
    Board"), first occurrence, case-insensitive, or None."""
    pos = 0
    while True:
        i = _ci_find(text, name, pos)
        if i < 0:
            return None
        e = _c09_urban_suffix_end(text, i + len(name))
        if e >= 0:
            return text[i:e]
        pos = i + 1


def _c09_without_village_suffix(text: str) -> "str | None":
    r"""`text` minus trailing spaces + "village" + optional spaces (any case), or None when
    it does not end that way."""
    t = text.rstrip()
    if len(t) > 7 and t[-7:].lower() == "village" and t[-8].isspace():
        return t[:-7].rstrip()
    return None


def _c09_name_then_village(text: str, name: str) -> bool:
    r"""`name` (no ASCII letter/digit just before it), spaces, then "village" as
    a whole word, case-insensitive."""
    n = len(text)
    pos = 0
    while True:
        i = _ci_find(text, name, pos)
        if i < 0:
            return False
        pos = i + 1
        if i > 0 and text[i - 1] in _ASCII_ALNUM:
            continue
        j = _ws_run_end(text, i + len(name))
        if j > i + len(name) and text[j:j + 7].lower() == "village" \
                and (j + 7 >= n or not _c09_is_word(text[j + 7])):
            return True


_C09_WHOLE_CONSTITUENCY = _tm.Matcher(_tm.Seq("whole", _GapIs(_gap_ws), "constituency"))

_C09_BLOCK_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .()-")
_C09_DISTRICT_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ")


def _c09_district_stop(text: str, q: int) -> bool:
    r"""Looking ahead from q (consuming nothing): optional spaces then ',' '?' '.'
    or the text end, or spaces then a whole-word across / during / for / till / in."""
    n = len(text)
    k = _ws_run_end(text, q)
    if k == n or text[k] in ",?.":
        return True
    if k == q:
        return False
    low = text.lower()
    for w in ("across", "during", "for", "till", "in"):
        if low.startswith(w, k) and (k + len(w) >= n or not _c09_is_word(text[k + len(w)])):
            return True
    return False


def _c09_block_beside_at(text: str, i: int):
    r"""Case-insensitive: ',' or a word starting "in" / "of", optional spaces,
    group 1 (a letter, then the fewest letters / spaces / . ( ) - needed), spaces,
    whole-word "block"; then optionally a ',' between optional spaces and group 2
    (a letter, then the fewest letters / spaces up to a _c09_district_stop)."""
    n = len(text)
    if i >= n:
        return None
    low2 = text[i:i + 2].lower()
    if text[i] == ",":
        j = i + 1
    elif low2 in ("in", "of") and (i == 0 or not _c09_is_word(text[i - 1])):
        j = i + 2
    else:
        return None
    j = _ws_run_end(text, j)
    if j >= n or text[j] not in _ASCII_LETTERS:
        return None
    g1 = j + 1
    while True:                                    # lazy block name
        k = _ws_run_end(text, g1)
        if k > g1 and text[k:k + 5].lower() == "block" and (k + 5 >= n or not _c09_is_word(text[k + 5])):
            end, g2 = k + 5, None
            c = _ws_run_end(text, end)
            if c < n and text[c] == ",":
                d = _ws_run_end(text, c + 1)
                if d < n and text[d] in _ASCII_LETTERS:
                    e = d + 1
                    while True:                    # lazy district name
                        if _c09_district_stop(text, e):
                            end, g2 = e, (d, e)
                            break
                        if e < n and text[e] in _C09_DISTRICT_NAME_CHARS:
                            e += 1
                        else:
                            break
            return end, [(j, g1), g2]
        if g1 < n and text[g1] in _C09_BLOCK_NAME_CHARS:
            g1 += 1
        else:
            return None


_C09_BLOCK_BESIDE = _CharScan(_c09_block_beside_at)


def _c09_not_known_name(note: str) -> "str | None":
    """X from a note starting "'X' is not a known" (X non-empty, with no quote)."""
    if not note.startswith("'"):
        return None
    k = note.find("'", 1)
    if k > 1 and note.startswith("' is not a known", k):
        return note[1:k]
    return None


def _c09_swap_place_name(text: str, old: str, new: str) -> str:
    """Every case-insensitive occurrence of the place name `old` in `text`
    becomes `new` (KI-327: the stale district in a rewritten follow-up)."""
    out, pos = text or "", 0
    old = (old or "").strip()
    if not old:
        return out
    while True:
        i = _ci_find(out, old, pos)
        if i < 0:
            return out
        out = out[:i] + new + out[i + len(old):]
        pos = i + len(new)


def _c09_chose_village(text: str) -> bool:
    r"""',' optional spaces, then "the village, not the block" or "the village, not
    another area type", case-insensitive."""
    low = text.lower()
    pos = low.find(",")
    while pos >= 0:
        j = _ws_run_end(text, pos + 1)
        if low.startswith("the village, not the block", j) or low.startswith(
                "the village, not another area type", j):
            return True
        pos = low.find(",", pos + 1)
    return False

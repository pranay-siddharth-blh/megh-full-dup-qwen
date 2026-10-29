"""LIVE CM Elevate UAT (2026-10-30): the 30 sheet use cases (CM-ELEVATE-OFF-001..030,
"Test Case Results - 30th Sep 26.xlsx" sheet "CM Elevate") filled in with real places and
programmes, plus a hierarchy / permutation suite (region, district, block, village, assembly
constituency and their combinations, the scheme's own dimensions, and edge cases).

Every expected figure is computed here, independently, by read-only SQL on curated.v_cm_elevate
(applications = applicants = COUNT(DISTINCT request_id); pending / on hold = data_verified 'On Hold';
verified = 'Valid'; status = current_file_status; sector = sector_id). Each question runs in a
FRESH chat through the product's conversation layer and graph (InProcessDriver); a clarification
is answered by tapping the chip a user would (the place level / village the case means).

Not collected by pytest. Needs the office VPN (megh_db + gateway).

    .venv/Scripts/python.exe tests/live_cme_uat.py --out logs/cme_uat.json
    .venv/Scripts/python.exe tests/live_cme_uat.py --only OFF-022,H-AC --out logs/x.json
"""
import argparse
import asyncio
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "tests"))

V = "curated.v_cm_elevate"
ONHOLD = "data_verified = 'On Hold'"

# programme: (what a user types, a word the answer must carry)
PROG = {
    "PRIME Small Enterprise Empowerment and Development (SEED)": ("Prime SEED", "seed"),
    "Meghalaya Piggery Development Scheme": ("Piggery", "piggery"),
    "Meghalaya Poultry Farming Scheme": ("Poultry", "poultry"),
    "PRIME Tourism Vehicle Scheme": ("Prime Tourism Vehicle", "tourism vehicle"),
    "PRIME Agriculture Response Vehicle Scheme": ("Agriculture Response Vehicle", "response vehicle"),
    "Meghalaya Dairy Development Scheme": ("Dairy", "dairy"),
    "Meghalaya Any Business Venture Scheme": ("Any Business Venture", "business venture"),
    "Meghalaya Goat Farming Scheme": ("Goat Farming", "goat"),
    "Meghalaya Warehouse Scheme": ("Warehouse", "warehouse"),
    "Meghalaya Sericulture & Weaving Scheme": ("Sericulture & Weaving", "sericulture"),
    "Meghalaya Sports & Wellness Centre Scheme": ("Sports & Wellness Centre", "sports"),
    "Chief Minister's Green Taxi Scheme": ("Green Taxi", "green taxi"),
    "Agro Tourism Villa Scheme": ("Agro Tourism Villa", "agro tourism"),
    "Meghalaya Motorcaravan Scheme": ("Motorcaravan", "motorcaravan"),
    "Meghalaya Cinema Theatre Scheme": ("Cinema Theatre", "cinema"),
}
STATUS_KW = {"forward": ["forward"], "resubmit": ["resubmit"],
             "sendback to vdv/citizen": ["sent back", "send back", "sendback"]}


def title(s: str) -> str:
    return " ".join(w.capitalize() for w in s.replace("-", " - ").split()).replace(" - ", "-")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def block_core(b: str) -> str:
    """'SHILLONG-MUNICIPAL BOARD' -> 'shillong'; 'TURA MUNICIPAL BOARD-MUNICIPAL BOARD' -> 'tura'."""
    core = re.split(r"-|\bMUNICIPAL BOARD\b|\bTOWN COMMITTEE\b", b)[0]
    return norm(core)


def block_say(b: str) -> str:
    """How a user names the block."""
    if "MUNICIPAL BOARD" in b:
        return title(block_core(b)) + " Municipal Board"
    if "TOWN COMMITTEE" in b:
        return title(block_core(b)) + " Town Committee"
    return title(b)


def indian(n: int) -> str:
    s = str(abs(int(n)))
    if len(s) > 3:
        head, parts = s[:-3], [s[-3:]]
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + parts)
    return s


def has_num(text: str, n) -> bool:
    if isinstance(n, float) and not float(n).is_integer():
        forms = {f"{n:.1f}", f"{n:.2f}"}
    else:
        n = int(n)
        forms = {indian(n), str(n), f"{n:,}"}
        if n == 0:
            low = text.lower()
            if any(w in low for w in (" no ", "none", "zero", "not any", "no applica", "no record",
                                      "no pending", "no on-hold", "no on hold", "no withdrawn")):
                return True
    return any(re.search(r"(?<![\d,.])" + re.escape(f) + r"(?![\d]|,\d|\.\d)", text) for f in forms)


NOT_FOUND = ["not find", "could not", "couldn't", "not recognis", "not recogniz", "no place", "isn't a",
             "is not a", "no such", "not found", "unable", "did not match", "doesn't match", "not match",
             "don't have", "do not have", "no data", "not in the", "no district", "no block", "no village",
             "no constituency", "not one of", "no area", "which place", "not a known", "isn't in", "is not in"]


# ── truth helpers (read-only SELECTs) ──────────────────────────────────────
class DB:
    def __init__(self):
        import psycopg
        from dotenv import load_dotenv
        load_dotenv()
        self.c = psycopg.connect(os.environ["DATABASE_URL"])
        self.c.read_only = True

    def rows(self, sql, args=()):
        assert sql.lstrip().upper().startswith(("SELECT", "WITH"))
        return self.c.execute(sql, args).fetchall()

    def count(self, where="TRUE", args=()):
        return self.rows(f"SELECT COUNT(DISTINCT request_id) FROM {V} WHERE {where}", args)[0][0]

    def group(self, col, where="TRUE", args=()):
        return {r[0]: r[1] for r in self.rows(
            f"SELECT {col}, COUNT(DISTINCT request_id) FROM {V} WHERE {where} GROUP BY 1 ORDER BY 2 DESC", args)}


def C(cid, suite, tc, level, desc, q, checks, *, pick=(), total=None, kind="answer", truth_sql="", note=""):
    """checks: list of (label keywords | None, value). pick: chip label substrings, in order of preference."""
    return {"id": cid, "suite": suite, "tc": tc, "level": level, "desc": desc, "q": q, "checks": checks,
            "total": total, "pick": list(pick), "kind": kind, "truth_sql": truth_sql, "note": note}


def build_cases(db: DB, seed: int = 30):
    rnd = random.Random(seed)
    cases = []
    dists = sorted(db.group("lgd_district"))
    raw_blocks = db.rows(f"SELECT lgd_district, lgd_block, COUNT(DISTINCT request_id) FROM {V} GROUP BY 1,2 ORDER BY 3 DESC")
    # one town stored under two spellings (TURA MUNICIPAL BOARD / ...-MUNICIPAL BOARD) is ONE place
    # to a user: one case, the union expected
    SIB = {}
    for d, b, n in raw_blocks:
        SIB.setdefault((d, block_say(b)), []).append(b)
    SIB = {b: v for v in SIB.values() for b in v}

    def SB(b):
        return SIB.get(b, [b])
    blocks, seen = [], set()
    for d, b, n in raw_blocks:
        if (d, block_say(b)) in seen:
            continue
        seen.add((d, block_say(b)))
        blocks.append((d, b, db.count("lgd_block = ANY(%s)", (SB(b),))))
    progs = list(db.group("scheme_name"))  # by size
    big = progs[:6]

    def P(s):
        return PROG[s][0]

    def K(s):
        return [PROG[s][1]]

    def dk(d):
        return [norm(d)]

    # village sample: largest, smallest, random, shared names, wards, block-named
    vills = db.rows(f"""SELECT village_code, lgd_village_name, lgd_block, lgd_district, COUNT(DISTINCT request_id) n
                       FROM {V} WHERE entity_type <> 'Unresolved' GROUP BY 1,2,3,4 ORDER BY n DESC, 1""")
    by_name = {}
    for v in vills:
        by_name.setdefault(v[1].upper(), []).append(v)
    uniq = [v for v in vills if len(by_name[v[1].upper()]) == 1]
    plain = [v for v in uniq if "ward" not in v[1].lower() and v[1].upper() not in {b[1] for b in blocks}
             and v[1].upper() not in {d for d in dists}]
    sample = plain[:3] + plain[-3:] + rnd.sample(plain[3:-3], 10)
    dupes = [n for n, vs in by_name.items() if len(vs) > 1]
    dupe_pick = [by_name[n][0] for n in rnd.sample(sorted(dupes), 4)]
    wards = [v for v in uniq if "ward" in v[1].lower()][:2]
    vsample = [("plain", v) for v in sample] + [("shared name", v) for v in dupe_pick] + [("ward", v) for v in wards]

    def vq(v):
        name = v[1]
        return name if "ward" not in name.lower() else name

    def vpick(v):
        return [block_core(v[2]), norm(v[3]), "village"]

    vw = "village_code = %s"

    # ── the sheet ──────────────────────────────────────────────────────────
    S = "sheet"
    for i, d in enumerate(dists):
        cases.append(C(f"OFF-001-{i+1:02}", S, "CM-ELEVATE-OFF-001", "District", "Overall district applicant count",
                       f"How many CM ELEVATE applicants are there in {title(d)}?",
                       [(None, db.count("lgd_district=%s", (d,)))], pick=["district"],
                       truth_sql=f"COUNT(DISTINCT request_id) WHERE lgd_district='{d}'"))
    for i, (d, b, n) in enumerate(blocks):
        cases.append(C(f"OFF-002-{i+1:02}", S, "CM-ELEVATE-OFF-002", "Block", "Overall block applicant count",
                       f"How many CM ELEVATE applicants are there in {block_say(b)}?",
                       [(None, n)], pick=["block", block_core(b)],
                       truth_sql=f"COUNT(DISTINCT request_id) WHERE lgd_block='{b}'"))
    for i, (tag, v) in enumerate(vsample):
        tw = by_name[v[1].upper()]
        if tag == "shared name" and len(tw) <= 3 and len({t[2] for t in tw}) == len(tw):
            # J-10: up to three same-name villages in different blocks are each answered,
            # named with their block (no "which village?" pause)
            checks = [([block_core(t[2])], t[4]) for t in tw]
            truth = "per village_code " + ", ".join(f"{t[0]} ({t[2]})={t[4]}" for t in tw)
        else:
            checks, truth = [(None, v[4])], f"COUNT(DISTINCT request_id) WHERE village_code={v[0]} ({v[2]} / {v[3]})"
        cases.append(C(f"OFF-003-{i+1:02}", S, "CM-ELEVATE-OFF-003", "Village", f"Overall village applicant count ({tag})",
                       f"How many CM ELEVATE applicants are there in {vq(v)}?", checks, pick=vpick(v),
                       truth_sql=truth))
    g = db.group("lgd_district")
    cases.append(C("OFF-004-01", S, "CM-ELEVATE-OFF-004", "District (all)", "District-wise applicant distribution",
                   "How many CM ELEVATE applicants are there in each district?",
                   [(dk(d), n) for d, n in g.items()],
                   truth_sql="COUNT(DISTINCT request_id) GROUP BY lgd_district"))
    g = db.group("scheme_name")
    cases.append(C("OFF-005-01", S, "CM-ELEVATE-OFF-005", "State", "Program-wise applicant distribution",
                   "How many applicants are there under each CM ELEVATE program?",
                   [(K(s), n) for s, n in g.items()],
                   truth_sql="COUNT(DISTINCT request_id) GROUP BY scheme_name"))
    for i, d in enumerate(dists):
        s = big[i % len(big)]
        cases.append(C(f"OFF-006-{i+1:02}", S, "CM-ELEVATE-OFF-006", "District x Programme", "Program-specific district analysis",
                       f"How many applicants are there under {P(s)} in {title(d)}?",
                       [(None, db.count("scheme_name=%s AND lgd_district=%s", (s, d)))], pick=["district"],
                       truth_sql=f"scheme_name='{s}' AND lgd_district='{d}'"))
    bsample = blocks[:4] + blocks[-3:] + rnd.sample(blocks[4:-3], 5)
    for i, (d, b, _) in enumerate(bsample):
        s = big[i % len(big)]
        cases.append(C(f"OFF-007-{i+1:02}", S, "CM-ELEVATE-OFF-007", "Block x Programme", "Program-specific block analysis",
                       f"How many applicants are there under {P(s)} in {block_say(b)}?",
                       [(None, db.count("scheme_name=%s AND lgd_block = ANY(%s)", (s, SB(b))))], pick=["block", block_core(b)],
                       truth_sql=f"scheme_name='{s}' AND lgd_block='{b}'"))
    for i, (tag, v) in enumerate(vsample[:12]):
        top = db.group("scheme_name", vw, (v[0],))
        s = list(top)[0] if i % 4 else big[(i + 3) % len(big)]
        cases.append(C(f"OFF-008-{i+1:02}", S, "CM-ELEVATE-OFF-008", "Village x Programme", f"Program-specific village analysis ({tag})",
                       f"How many applicants are there under {P(s)} in {vq(v)}?",
                       [(None, db.count("scheme_name=%s AND " + vw, (s, v[0])))], pick=vpick(v),
                       truth_sql=f"scheme_name='{s}' AND village_code={v[0]}"))
    for i, d in enumerate(dists):
        s1, s2 = big[i % 6], big[(i + 1) % 6]
        a, b_ = (db.count("scheme_name=%s AND lgd_district=%s", (s, d)) for s in (s1, s2))
        cases.append(C(f"OFF-009-{i+1:02}", S, "CM-ELEVATE-OFF-009", "District x 2 Programmes", "Multi-program district analysis",
                       f"How many applicants are there in {title(d)} under {P(s1)} and {P(s2)}?",
                       [(K(s1), a), (K(s2), b_)], total=a + b_, pick=["district"],
                       truth_sql=f"lgd_district='{d}' AND scheme_name IN ('{s1}','{s2}') GROUP BY scheme_name"))
    for i, (d, b, _) in enumerate(bsample):
        ss = [big[(i + k) % 6] for k in range(3)]
        vals = [db.count("scheme_name=%s AND lgd_block = ANY(%s)", (s, SB(b))) for s in ss]
        cases.append(C(f"OFF-010-{i+1:02}", S, "CM-ELEVATE-OFF-010", "Block x 3 Programmes", "Multi-program block analysis",
                       f"How many applicants are there in {block_say(b)} under {P(ss[0])}, {P(ss[1])} and {P(ss[2])}?",
                       [(K(s), n) for s, n in zip(ss, vals)], total=sum(vals), pick=["block", block_core(b)],
                       truth_sql=f"lgd_block='{b}' AND scheme_name IN 3 GROUP BY scheme_name"))
    g = db.group("COALESCE(sector_id, '(not recorded)')")
    cases.append(C("OFF-011-01", S, "CM-ELEVATE-OFF-011", "State x Sector", "Sector-wise applicant distribution",
                   "How many CM ELEVATE applicants are associated with each sector?",
                   [([norm(k).split()[0] if k != "(not recorded)" else "not recorded"], n) for k, n in g.items()],
                   truth_sql="GROUP BY COALESCE(sector_id,'(not recorded)')"))
    sectors = [k for k in db.group("sector_id", "sector_id IS NOT NULL")]
    for i, d in enumerate(dists):
        gs = db.group("sector_id", "sector_id IS NOT NULL AND lgd_district=%s", (d,))
        sec = list(gs)[0] if gs and i % 3 else sectors[i % len(sectors)]
        cases.append(C(f"OFF-012-{i+1:02}", S, "CM-ELEVATE-OFF-012", "District x Sector", "Sector and district analysis",
                       f"How many applicants are associated with the {sec} sector in {title(d)}?",
                       [(None, db.count("sector_id=%s AND lgd_district=%s", (sec, d)))], pick=["district"],
                       truth_sql=f"sector_id='{sec}' AND lgd_district='{d}'"))
    combos = [(s, sec) for s in ("Meghalaya Poultry Farming Scheme", "Meghalaya Piggery Development Scheme",
                                 "Meghalaya Dairy Development Scheme", "Meghalaya Goat Farming Scheme")
              for sec in sectors][:7]
    for i, (s, sec) in enumerate(combos):
        cases.append(C(f"OFF-013-{i+1:02}", S, "CM-ELEVATE-OFF-013", "Programme x Sector", "Program and sector analysis",
                       f"How many applicants under {P(s)} belong to the {sec} sector?",
                       [(None, db.count("scheme_name=%s AND sector_id=%s", (s, sec)))],
                       truth_sql=f"scheme_name='{s}' AND sector_id='{sec}'"))
    for i, d in enumerate(dists):
        s1, s2 = "Meghalaya Poultry Farming Scheme", ["Meghalaya Piggery Development Scheme", "Meghalaya Dairy Development Scheme"][i % 2]
        sec = sectors[i % len(sectors)]
        a, b_ = (db.count("scheme_name=%s AND sector_id=%s AND lgd_district=%s", (s, sec, d)) for s in (s1, s2))
        cases.append(C(f"OFF-014-{i+1:02}", S, "CM-ELEVATE-OFF-014", "District x Sector x 2 Programmes", "Multi-program sector analysis",
                       f"How many applicants under {P(s1)} and {P(s2)} are associated with the {sec} sector in {title(d)}?",
                       [(K(s1), a), (K(s2), b_)], total=a + b_, pick=["district"],
                       truth_sql=f"sector_id='{sec}' AND lgd_district='{d}' GROUP BY scheme_name"))
    g = db.group("current_file_status")
    cases.append(C("OFF-015-01", S, "CM-ELEVATE-OFF-015", "State x Status", "Overall status distribution",
                   "What is the current application status distribution across CM ELEVATE?",
                   [(STATUS_KW[k], n) for k, n in g.items()], truth_sql="GROUP BY current_file_status"))
    for i, s in enumerate(progs):
        g = db.group("current_file_status", "scheme_name=%s", (s,))
        cases.append(C(f"OFF-016-{i+1:02}", S, "CM-ELEVATE-OFF-016", "Programme x Status", "Program-wise status analysis",
                       f"What is the status distribution for {P(s)}?",
                       [(STATUS_KW[k], n) for k, n in g.items()], truth_sql=f"scheme_name='{s}' GROUP BY current_file_status"))
    for i, d in enumerate(dists):
        g = db.group("current_file_status", "lgd_district=%s", (d,))
        cases.append(C(f"OFF-017-{i+1:02}", S, "CM-ELEVATE-OFF-017", "District x Status", "District-wise status analysis",
                       f"What is the application status distribution in {title(d)}?",
                       [(STATUS_KW[k], n) for k, n in g.items()], pick=["district"],
                       truth_sql=f"lgd_district='{d}' GROUP BY current_file_status"))
    for i, lvl in enumerate(["level0", "level1", "level2", "level4"]):
        cases.append(C(f"OFF-018-{i+1:02}", S, "CM-ELEVATE-OFF-018", "State x Level", "Pending/pendency analysis",
                       f"How many CM ELEVATE applications are pending at level {lvl[-1]}?",
                       [(None, db.count("current_level=%s", (lvl,)))],
                       truth_sql=f"current_level='{lvl}' (KI-070 / KI-422: pending AT a level = the file sits at that "
                                 "level; the data records no 'pending' status)"))
    g = db.group("scheme_name", ONHOLD)
    cases.append(C("OFF-019-01", S, "CM-ELEVATE-OFF-019", "State x Programme", "Program-wise pendency",
                   "Which CM ELEVATE programs have the highest number of pending applications?",
                   [(K(s), n) for s, n in list(g.items())[:3]], truth_sql=f"{ONHOLD} GROUP BY scheme_name"))
    g = db.group("lgd_district", ONHOLD)
    cases.append(C("OFF-020-01", S, "CM-ELEVATE-OFF-020", "District (all)", "District-wise pendency",
                   "Which districts have the highest number of pending CM ELEVATE applications?",
                   [(dk(d), n) for d, n in list(g.items())[:3]], truth_sql=f"{ONHOLD} GROUP BY lgd_district"))
    for i, d in enumerate(dists):
        s = big[i % 6]
        cases.append(C(f"OFF-021-{i+1:02}", S, "CM-ELEVATE-OFF-021", "District x Programme x Pending", "Program and district pendency",
                       f"How many applications are pending under {P(s)} in {title(d)}?",
                       [(None, db.count(f"{ONHOLD} AND scheme_name=%s AND lgd_district=%s", (s, d)))], pick=["district"],
                       truth_sql=f"{ONHOLD} AND scheme_name='{s}' AND lgd_district='{d}'"))
    for i, d in enumerate(dists):
        tot = db.count("lgd_district=%s", (d,))
        val = db.count("data_verified='Valid' AND lgd_district=%s", (d,))
        cases.append(C(f"OFF-022-{i+1:02}", S, "CM-ELEVATE-OFF-022", "District x Verification", "Verification status analysis",
                       f"How many applicants have completed data verification in {title(d)}?",
                       [(None, val), (None, tot - val)], pick=["district"], note="rate=%.1f" % (100 * val / tot),
                       truth_sql=f"data_verified='Valid' AND lgd_district='{d}'; non-verified = total - valid"))
    for i, d in enumerate(dists):
        s = big[(i + 2) % 6]
        cases.append(C(f"OFF-023-{i+1:02}", S, "CM-ELEVATE-OFF-023", "District x Programme x On hold", "On-hold analysis",
                       f"How many applications are currently on hold under {P(s)} in {title(d)}?",
                       [(None, db.count(f"{ONHOLD} AND scheme_name=%s AND lgd_district=%s", (s, d)))], pick=["district"],
                       truth_sql=f"{ONHOLD} AND scheme_name='{s}' AND lgd_district='{d}'"))
    for i, d in enumerate(dists):
        s = big[i % 6]
        q = (f"How many applications have been withdrawn under {P(s)} in {title(d)}?" if i % 2 else
             f"How many applications have been withdrawn across CM ELEVATE in {title(d)}?")
        cases.append(C(f"OFF-024-{i+1:02}", S, "CM-ELEVATE-OFF-024", "District (x Programme) x Withdrawn", "Withdrawal analysis",
                       q, [(None, db.count("is_withdraw AND lgd_district=%s", (d,)))], pick=["district"],
                       truth_sql=f"is_withdraw AND lgd_district='{d}'"))
    for i, d in enumerate(dists):
        ss = [big[(i + k) % 6] for k in range(3)]
        checks = []
        for s in ss:
            checks.append((K(s), db.count("scheme_name=%s AND lgd_district=%s", (s, d))))
            checks.append((K(s), db.count(f"{ONHOLD} AND scheme_name=%s AND lgd_district=%s", (s, d))))
        cases.append(C(f"OFF-025-{i+1:02}", S, "CM-ELEVATE-OFF-025", "District x 3 Programmes x Sector", "Combined administrative analysis",
                       f"Give me the applicant count and pendency status for {P(ss[0])}, {P(ss[1])} and {P(ss[2])} in {title(d)}, broken down by sector.",
                       checks, pick=["district"], truth_sql=f"lgd_district='{d}' per programme: total and {ONHOLD}"))
    for i, (d, b, _) in enumerate(bsample):
        top = db.group("scheme_name", "lgd_block = ANY(%s)", (SB(b),))
        s = list(top)[0]
        g = db.group("lgd_village_name", "scheme_name=%s AND lgd_block = ANY(%s) AND entity_type <> 'Unresolved'", (s, SB(b)))
        cases.append(C(f"OFF-026-{i+1:02}", S, "CM-ELEVATE-OFF-026", "Block -> Village x Programme", "Program-wise village analysis",
                       f"How many applicants are there under {P(s)} in each village of {block_say(b)}?",
                       [([norm(k)], n) for k, n in list(g.items())[:5]], pick=["block", block_core(b)],
                       truth_sql=f"scheme_name='{s}' AND lgd_block='{b}' GROUP BY lgd_village_name (top 5 + total)"))
    pairs = [(dists[i], dists[j]) for i, j in ((0, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11))]
    for i, (d1, d2) in enumerate(pairs):
        s1, s2 = big[i % 6], big[(i + 1) % 6]
        checks = [(K(s) + dk(d), db.count("scheme_name=%s AND lgd_district=%s", (s, d))) for s in (s1, s2) for d in (d1, d2)]
        cases.append(C(f"OFF-027-{i+1:02}", S, "CM-ELEVATE-OFF-027", "2 Districts x 2 Programmes", "Multi-program district comparison",
                       f"Compare applicant counts for {P(s1)} and {P(s2)} across {title(d1)} and {title(d2)}.",
                       checks, truth_sql="per (scheme_name, lgd_district)"))
    for i, d in enumerate(dists):
        g = db.group("COALESCE(sector_id, '(not recorded)')", f"{ONHOLD} AND lgd_district=%s", (d,))
        cases.append(C(f"OFF-028-{i+1:02}", S, "CM-ELEVATE-OFF-028", "District x Sector x Pending", "Sector-wise pendency analysis",
                       f"How many applications are pending in each sector in {title(d)}?",
                       [(None, n) for k, n in g.items()], pick=["district"],
                       truth_sql=f"{ONHOLD} AND lgd_district='{d}' GROUP BY sector"))
    for i, d in enumerate(dists):
        s1, s2 = big[i % 6], big[(i + 1) % 6]
        st, where, word = (("on hold", ONHOLD, "on hold") if i % 2 == 0 else
                           ("forwarded", "current_file_status='forward'", "forwarded"))
        a, b_ = (db.count(f"{where} AND scheme_name=%s AND lgd_district=%s", (s, d)) for s in (s1, s2))
        cases.append(C(f"OFF-029-{i+1:02}", S, "CM-ELEVATE-OFF-029", "District x 2 Programmes x Status", "Program and status combination",
                       f"How many applications under {P(s1)} and {P(s2)} are currently {word} in {title(d)}?",
                       [(K(s1), a), (K(s2), b_)], total=a + b_, pick=["district"],
                       truth_sql=f"{where} AND lgd_district='{d}' GROUP BY scheme_name"))
    for i, (tag, v) in enumerate(vsample[:12]):
        s = list(db.group("scheme_name", vw, (v[0],)))[0]
        g = db.group("current_file_status", "scheme_name=%s AND " + vw, (s, v[0]))
        cases.append(C(f"OFF-030-{i+1:02}", S, "CM-ELEVATE-OFF-030", "Village x Programme x Status", f"Village-level status analysis ({tag})",
                       f"What is the status-wise applicant count for {P(s)} in {vq(v)}?",
                       [(STATUS_KW[k], n) for k, n in g.items()], pick=vpick(v),
                       truth_sql=f"scheme_name='{s}' AND village_code={v[0]} GROUP BY current_file_status"))

    # ── hierarchy / permutations ──────────────────────────────────────────
    H = "hierarchy"
    acs = db.rows(f"SELECT ac_name, COUNT(DISTINCT request_id) FROM {V} WHERE ac_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
    for i, (a, n) in enumerate(acs):
        cases.append(C(f"H-AC-{i+1:02}", H, "", "Assembly constituency", "Applicants in a constituency",
                       f"How many CM Elevate applicants are there in {a} constituency?", [(None, n)],
                       pick=["constituency"], truth_sql=f"ac_name='{a}'"))
    for i, r in enumerate(sorted(db.group("region"))):
        n = db.count("region=%s", (r,))
        cases.append(C(f"H-REG-{i+1:02}", H, "", "Region", "Applicants in a region (Garo/Khasi/Jaintia Hills)",
                       f"How many CM Elevate applicants are there in the {r} Hills region?", [(None, n)],
                       pick=["region"], truth_sql=f"region='{r}'",
                       note="region column on v_cm_elevate (Ri Bhoi is in Khasi)"))
    g = db.group("region")
    cases.append(C("H-REG-ALL", H, "", "Region (all)", "Region-wise applicants",
                   "How many CM Elevate applicants are there in each region?",
                   [([r.lower()], n) for r, n in g.items()], truth_sql="GROUP BY region"))
    for i, r in enumerate(sorted(db.group("region"))):
        s = big[i]
        cases.append(C(f"H-REGxP-{i+1:02}", H, "", "Region x Programme", "Programme in a region",
                       f"How many {P(s)} applicants are there in the {r} Hills region under CM Elevate?",
                       [(None, db.count("region=%s AND scheme_name=%s", (r, s)))], pick=["region"],
                       truth_sql=f"region='{r}' AND scheme_name='{s}'"))
    for i, d in enumerate(dists):
        g = db.group("lgd_block", "lgd_district=%s", (d,))
        cases.append(C(f"H-D>B-{i+1:02}", H, "", "District -> Block", "Block-wise applicants in a district",
                       f"How many CM Elevate applicants are there in each block of {title(d)}?",
                       [([block_core(b)], n) for b, n in g.items()], pick=["district"],
                       truth_sql=f"lgd_district='{d}' GROUP BY lgd_block"))
    for i, d in enumerate(dists):
        g = db.group("COALESCE(ac_name,'(none)')", "lgd_district=%s", (d,))
        cases.append(C(f"H-D>AC-{i+1:02}", H, "", "District -> Constituency", "Constituency-wise applicants in a district",
                       f"How many CM Elevate applicants are there in each assembly constituency of {title(d)}?",
                       [([norm(a)], n) for a, n in g.items() if a != "(none)"], pick=["district"],
                       truth_sql=f"lgd_district='{d}' GROUP BY ac_name"))
    for i, (d, b, _) in enumerate(bsample[:6]):
        g = db.group("lgd_village_name", "lgd_block = ANY(%s) AND entity_type <> 'Unresolved'", (SB(b),))
        cases.append(C(f"H-B>V-{i+1:02}", H, "", "Block -> Village", "Village-wise applicants in a block",
                       f"How many CM Elevate applicants are there in each village of {block_say(b)}?",
                       [([norm(k)], n) for k, n in list(g.items())[:5]],
                       pick=["block", block_core(b)], truth_sql=f"lgd_block='{b}' GROUP BY lgd_village_name (top 5 + total)"))
    split = db.rows(f"""SELECT lgd_block, ac_name, COUNT(DISTINCT request_id) FROM {V}
                        WHERE ac_name IS NOT NULL AND lgd_block IN (SELECT lgd_block FROM {V} WHERE ac_name IS NOT NULL
                        GROUP BY 1 HAVING COUNT(DISTINCT ac_name) > 1) GROUP BY 1,2 ORDER BY 3 DESC""")
    for i, (b, a, n) in enumerate(rnd.sample(split, 6)):
        cases.append(C(f"H-BxAC-{i+1:02}", H, "", "Block x Constituency (cross)", "Part of a block inside a constituency",
                       f"How many CM Elevate applicants in {block_say(b)} block fall in the {a} assembly constituency?",
                       [(None, n)], pick=["block", "constituency"], truth_sql=f"lgd_block='{b}' AND ac_name='{a}'"))
    for i, (a, _) in enumerate(acs[::6]):
        s = big[i % 6]
        cases.append(C(f"H-ACxP-{i+1:02}", H, "", "Constituency x Programme", "Programme in a constituency",
                       f"How many applicants are there under {P(s)} in {a} constituency?",
                       [(None, db.count("ac_name=%s AND scheme_name=%s", (a, s)))], pick=["constituency"],
                       truth_sql=f"ac_name='{a}' AND scheme_name='{s}'"))
    for i, (a, _) in enumerate(acs[1::12]):
        cases.append(C(f"H-ACxPend-{i+1:02}", H, "", "Constituency x Pending", "Pending in a constituency",
                       f"How many CM Elevate applications are pending in {a} constituency?",
                       [(None, db.count(f"{ONHOLD} AND ac_name=%s", (a,)))], pick=["constituency"],
                       truth_sql=f"{ONHOLD} AND ac_name='{a}'"))
    for i, (a, _) in enumerate(acs[2::15]):
        g = db.group("current_file_status", "ac_name=%s", (a,))
        cases.append(C(f"H-ACxSt-{i+1:02}", H, "", "Constituency x Status", "Status distribution in a constituency",
                       f"What is the CM Elevate application status distribution in {a} constituency?",
                       [(STATUS_KW[k], n) for k, n in g.items()], pick=["constituency"],
                       truth_sql=f"ac_name='{a}' GROUP BY current_file_status"))
    for i, (tag, v) in enumerate(vsample[:6]):
        a = db.rows(f"SELECT ac_name FROM {V} WHERE village_code=%s AND ac_name IS NOT NULL LIMIT 1", (v[0],))
        if not a:
            continue
        cases.append(C(f"H-V>AC-{i+1:02}", H, "", "Village -> Constituency (cross)", "Which constituency a village is in",
                       f"Which assembly constituency is {vq(v)} village in, and how many CM Elevate applicants does it have?",
                       [([norm(a[0][0])], v[4])], pick=vpick(v), truth_sql=f"village_code={v[0]} -> ac_name"))
    dims = [("applicant_category", "applicant category", {"individual": ["individual"], "registered": ["registered"],
                                                          "unregistered": ["unregistered"]}),
            ("application_mode", "application mode", {"online": ["online"], "cmconnectcenter": ["connect"]}),
            ("data_verified", "data verification status", None),
            ("current_level", "current level", None)]
    for j, (col, word, kw) in enumerate(dims):
        for i, d in enumerate([dists[j * 3], dists[j * 3 + 1]]):
            g = db.group(col, "lgd_district=%s", (d,))
            cases.append(C(f"H-DIM-{col[:8]}-{i+1}", H, "", f"District x {word}", f"Breakdown by {word}",
                           f"Break down CM Elevate applicants in {title(d)} by {word}.",
                           [((kw or {}).get(k) if kw else None, n) for k, n in g.items() if k is not None],
                           pick=["district"], truth_sql=f"lgd_district='{d}' GROUP BY {col}"))
    for i, (d, b, _) in enumerate(bsample[:3]):
        g = db.group("data_verified", "lgd_block = ANY(%s)", (SB(b),))
        cases.append(C(f"H-BxDV-{i+1}", H, "", "Block x Verification", "Verification status in a block",
                       f"What is the data verification status breakdown for CM Elevate in {block_say(b)} block?",
                       [(None, n) for k, n in g.items() if k is not None], pick=["block", block_core(b)],
                       truth_sql=f"lgd_block='{b}' GROUP BY data_verified"))
    # edge cases
    edge = [("RI BHOI", "RI BHOI"), ("ri bhoi", "RI BHOI"), ("west garo hills", "WEST GARO HILLS"),
            ("Ri-Bhoi", "RI BHOI"), ("W Garo Hills", "WEST GARO HILLS"), ("East Khasi Hill", "EAST KHASI HILLS"),
            ("South West Khasi Hils", "SOUTH WEST KHASI HILLS"), ("Jaintia Hills West", "WEST JAINTIA HILLS")]
    for i, (say, d) in enumerate(edge):
        cases.append(C(f"H-EDGE-dist-{i+1}", H, "", "District (spelling/case)", "Spelling / case variant of a district",
                       f"How many CM Elevate applicants are there in {say}?", [(None, db.count("lgd_district=%s", (d,)))],
                       pick=["district", norm(d)], truth_sql=f"lgd_district='{d}'"))
    for i, (say, b) in enumerate([("UMLING", "UMLING"), ("umling block", "UMLING"), ("Rongrum block", "RONGRAM"),
                                  ("Mawphlong block", "MAWPHLANG"), ("Tikrikila block", "TIKRIKILLA")]):
        cases.append(C(f"H-EDGE-block-{i+1}", H, "", "Block (spelling/case)", "Spelling / case variant of a block",
                       f"How many CM Elevate applicants are there in {say}?", [(None, db.count("lgd_block = ANY(%s)", (SB(b),)))],
                       pick=["block", block_core(b)], truth_sql=f"lgd_block='{b}'"))
    for i, b in enumerate(["MAWHATI", "RANIKOR", "SELSELLA", "PYNURSLA"]):
        cases.append(C(f"H-EDGE-blockvill-{i+1}", H, "", "Block vs Village (same name)", "Block name that is also a village: block chosen",
                       f"How many CM Elevate applicants are there in {title(b)}?", [(None, db.count("lgd_block = ANY(%s)", (SB(b),)))],
                       pick=["block"], truth_sql=f"lgd_block='{b}'"))
    for i, v in enumerate(dupe_pick):
        cases.append(C(f"H-EDGE-dupvill-{i+1}", H, "", "Village (shared name)", "Village name shared across blocks/districts",
                       f"How many CM Elevate applicants are there in {title(v[1])} village of {block_say(v[2])} block?",
                       [(None, v[4])], pick=vpick(v), truth_sql=f"village_code={v[0]}"))
    zero = []
    for s in reversed(progs):
        for d in dists:
            if db.count("scheme_name=%s AND lgd_district=%s", (s, d)) == 0:
                zero.append((s, d))
    for i, (s, d) in enumerate(rnd.sample(zero, 4)):
        cases.append(C(f"H-EDGE-zero-{i+1}", H, "", "District x Programme (zero)", "Entity combination with zero records",
                       f"How many applicants are there under {P(s)} in {title(d)}?", [(None, 0)], pick=["district"],
                       truth_sql=f"scheme_name='{s}' AND lgd_district='{d}' -> 0"))
    for i, q in enumerate(["How many CM Elevate applicants are there in Gotham district?",
                           "How many CM Elevate applicants are there in Xyzabad block?",
                           "How many CM Elevate applicants are there in Narnia village?",
                           "How many CM Elevate applicants are there in Springfield constituency?"]):
        cases.append(C(f"H-EDGE-invalid-{i+1}", H, "", "Invalid name", "Non-existent place: no fabricated figure",
                       q, [], kind="not_found", truth_sql="no such place"))
    cases.append(C("H-AGG-state", H, "", "State", "State total", "How many CM Elevate applications are there in total?",
                   [(None, db.count())], truth_sql="COUNT(DISTINCT request_id)"))
    return cases


# ── judging ────────────────────────────────────────────────────────────────
def judge(c, rec):
    text = rec.answer or ""
    low = norm(text)
    if c["kind"] == "not_found":
        if rec.route == "pause" or any(w in text.lower() for w in NOT_FOUND):
            if not re.search(r"\b(are|were|has|have)\s+[1-9][\d,]*\s+(cm elevate\s+)?applica", text.lower()):
                return []
        return ["a figure or no 'not found' for a place that does not exist"]
    if rec.route in ("pause", "error") or rec.route not in ("data",):
        return [f"no data answer: route={rec.route}: {text[:200]}"]
    fails = []
    for kws, n in c["checks"]:
        if not has_num(text, n):
            fails.append(f"missing {n}" + (f" ({kws[0]})" if kws else ""))
        elif kws and n and not any(norm(k) in low for k in kws):
            fails.append(f"label {kws[0]!r} absent")
    if c["total"] is not None and c["total"] and not has_num(text, c["total"]):
        fails.append(f"missing total {c['total']}")
    return fails


async def run_case(d, c, sem):
    async with sem:
        conv = d.new_conversation()
        t0 = time.perf_counter()
        rec = await conv.ask(c["q"])
        turns = [{"say": c["q"], "route": rec.route, "answer": rec.answer}]
        for _ in range(2):
            if rec.route != "pause":
                break
            opts = getattr(conv, "last_options", []) or []
            choice = None
            for p in c["pick"]:
                choice = next((o for o in opts if p and p in norm(o.get("label", ""))), None)
                if choice:
                    break
            # what a user taps on the generic pauses: the CM Elevate (applications) dataset
            # on "which scheme?", the complete list on "how many results?"
            for want in ("cm elevate applications", "cm elevate", "complete list", "all of them"):
                if choice:
                    break
                choice = next((o for o in opts if norm(o.get("label", "")).startswith(want)
                               and "legacy" not in norm(o.get("label", ""))), None)
            if not choice:
                break
            rec = await conv.ask(choice.get("question") or choice.get("label"))
            turns.append({"say": choice.get("label"), "route": rec.route, "answer": rec.answer})
        fails = judge(c, rec)
        return {**c, "route": rec.route, "answer": rec.answer, "turns": turns, "fails": fails,
                "status": "Pass" if not fails else "Fail", "sql": (rec.raw or {}).get("sql_query"),
                "secs": round(time.perf_counter() - t0, 1)}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list of case-id prefixes")
    ap.add_argument("--out", default="logs/cme_uat.json")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    db = DB()
    cases = build_cases(db)
    if args.only:
        keys = args.only.split(",")
        cases = [c for c in cases if any(c["id"].startswith(k) for k in keys)]
    print(f"{len(cases)} cases", flush=True)
    from conversation_harness.drivers import InProcessDriver
    sem = asyncio.Semaphore(args.workers)
    results = []
    async with InProcessDriver() as d:
        tasks = [asyncio.create_task(run_case(d, c, sem)) for c in cases]
        for t in asyncio.as_completed(tasks):
            r = await t
            results.append(r)
            print(f"{r['status']} {r['id']:<22} {r['route']:<6} {r['secs']:>5}s" +
                  ("" if r["status"] == "Pass" else "  " + "; ".join(r["fails"])[:300]), flush=True)
    results.sort(key=lambda r: r["id"])
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1, ensure_ascii=False, default=str)
    npass = sum(r["status"] == "Pass" for r in results)
    print(f"\n{npass}/{len(results)} passed")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

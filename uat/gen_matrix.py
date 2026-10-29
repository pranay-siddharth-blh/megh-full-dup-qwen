"""Generate the exhaustive CM Elevate UAT matrix from the live DB (read-only SELECTs).

    python uat/gen_matrix.py          -> uat/test_matrix.csv, uat/matrix_counts.txt

Every list is read from curated.v_cm_elevate / curated.dim_geography at run time. Expected values are
computed here and stored per row (checks = [[label keywords | null, value], ...]).
"""
import csv
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.chdir(ROOT)
import live_cme_uat as U  # noqa: E402  (helpers: title, norm, block_core, block_say, PROG, STATUS_KW, DB)

V = "curated.v_cm_elevate"
ONHOLD = "data_verified = 'On Hold'"
FYS = ["2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]

db = U.DB()
rows_out = []
counts = {}          # category -> (generated, db basis text)


def add(cat, tid, question, checks=(), *, tc="", level="", desc="", pick=(), total=None, kind="answer",
        truth="", extra=None):
    rows_out.append({"id": tid, "category": cat, "tc": tc, "level": level, "desc": desc,
                     "question": question if isinstance(question, str) else json.dumps(question),
                     "checks": json.dumps(list(checks)), "total": "" if total is None else total,
                     "pick": json.dumps(list(pick)), "kind": kind, "truth_sql": truth,
                     "extra": json.dumps(extra or {})})


def P(s):
    return U.PROG[s][0]


def K(s):
    return [U.PROG[s][1]]


def grp(sql, args=()):
    return db.rows(sql, args)


# ── reference lists ─────────────────────────────────────────────────────────
dists = [r[0] for r in grp(f"SELECT DISTINCT lgd_district FROM {V} ORDER BY 1")]
progs = [r[0] for r in grp(f"SELECT scheme_name FROM {V} GROUP BY 1 ORDER BY COUNT(DISTINCT request_id) DESC")]
raw_blocks = grp(f"SELECT lgd_district, lgd_block FROM {V} GROUP BY 1,2 ORDER BY 1,2")
SIB = {}
for d, b in raw_blocks:
    SIB.setdefault((d, U.block_say(b)), []).append(b)
places_block = []                      # (district, representative block, [stored spellings])
for (d, say), bl in sorted(SIB.items()):
    places_block.append((d, bl[0], bl))
acs = [r[0] for r in grp(f"SELECT DISTINCT ac_name FROM {V} WHERE ac_name IS NOT NULL ORDER BY 1")]
regions = [r[0] for r in grp(f"SELECT DISTINCT region FROM {V} ORDER BY 1")]


def cnt(where, args=()):
    return db.count(where, args)


def blk_where(bl):
    return "lgd_block = ANY(%s)", (bl,)


def place_list():
    """(level, label, question text, where, args, pick)"""
    out = []
    for r in regions:
        out.append(("Region", r, f"the {r} Hills region", "region=%s", (r,), ["region"]))
    for d in dists:
        out.append(("District", d, U.title(d), "lgd_district=%s", (d,), ["district"]))
    for d, b, bl in places_block:
        say = U.block_say(b)
        q = say if ("Municipal" in say or "Town Committee" in say) else f"{say} block"
        out.append(("Block", b, q, "lgd_block = ANY(%s)", (bl,), ["block", U.block_core(b)]))
    for a in acs:
        out.append(("Constituency", a, f"{a} constituency", "ac_name=%s", (a,), ["constituency"]))
    return out


PLACES = place_list()

# ═══ C01 sheet templates ═══════════════════════════════════════════════════
C = "C01_sheet"
n0 = len(rows_out)
big = progs[:6]
for i, d in enumerate(dists):
    add(C, f"C01-001-{i+1:02}", f"How many CM ELEVATE applicants are there in {U.title(d)}?",
        [[None, cnt("lgd_district=%s", (d,))]], tc="CM-ELEVATE-OFF-001", level="District", pick=["district"],
        truth=f"COUNT(DISTINCT request_id) WHERE lgd_district='{d}'")
for i, (d, b, bl) in enumerate(places_block):
    add(C, f"C01-002-{i+1:02}", f"How many CM ELEVATE applicants are there in {U.block_say(b)}?",
        [[None, cnt(*blk_where(bl))]], tc="CM-ELEVATE-OFF-002", level="Block", pick=["block", U.block_core(b)],
        truth=f"lgd_block IN {bl}")
g = dict(grp(f"SELECT lgd_district, COUNT(DISTINCT request_id) FROM {V} GROUP BY 1"))
add(C, "C01-004-01", "How many CM ELEVATE applicants are there in each district?",
    [[[U.norm(k)], v] for k, v in g.items()], tc="CM-ELEVATE-OFF-004", level="District (all)", truth="GROUP BY lgd_district")
g = dict(grp(f"SELECT scheme_name, COUNT(DISTINCT request_id) FROM {V} GROUP BY 1"))
add(C, "C01-005-01", "How many applicants are there under each CM ELEVATE program?",
    [[K(k), v] for k, v in g.items()], tc="CM-ELEVATE-OFF-005", level="State", truth="GROUP BY scheme_name")
for i, d in enumerate(dists):
    s = progs[i % len(progs)]
    add(C, f"C01-006-{i+1:02}", f"How many applicants are there under {P(s)} in {U.title(d)}?",
        [[None, cnt("scheme_name=%s AND lgd_district=%s", (s, d))]], tc="CM-ELEVATE-OFF-006",
        level="District x Programme", pick=["district"], truth=f"scheme_name='{s}' AND lgd_district='{d}'")
for i, (d, b, bl) in enumerate(places_block):
    s = progs[i % len(progs)]
    add(C, f"C01-007-{i+1:02}", f"How many applicants are there under {P(s)} in {U.block_say(b)}?",
        [[None, cnt("scheme_name=%s AND lgd_block = ANY(%s)", (s, bl))]], tc="CM-ELEVATE-OFF-007",
        level="Block x Programme", pick=["block", U.block_core(b)], truth=f"scheme_name='{s}' AND lgd_block IN {bl}")
for i, d in enumerate(dists):
    s1, s2 = progs[(2 * i) % 15], progs[(2 * i + 1) % 15]
    a, b_ = (cnt("scheme_name=%s AND lgd_district=%s", (s, d)) for s in (s1, s2))
    add(C, f"C01-009-{i+1:02}", f"How many applicants are there in {U.title(d)} under {P(s1)} and {P(s2)}?",
        [[K(s1), a], [K(s2), b_]], total=a + b_, tc="CM-ELEVATE-OFF-009", level="District x 2 Programmes",
        pick=["district"], truth=f"lgd_district='{d}' GROUP BY scheme_name")
for i, (d, b, bl) in enumerate(places_block):
    ss = [progs[(3 * i + k) % 15] for k in range(3)]
    vals = [cnt("scheme_name=%s AND lgd_block = ANY(%s)", (s, bl)) for s in ss]
    add(C, f"C01-010-{i+1:02}", f"How many applicants are there in {U.block_say(b)} under {P(ss[0])}, {P(ss[1])} and {P(ss[2])}?",
        [[K(s), v] for s, v in zip(ss, vals)], total=sum(vals), tc="CM-ELEVATE-OFF-010", level="Block x 3 Programmes",
        pick=["block", U.block_core(b)], truth=f"lgd_block IN {bl} GROUP BY scheme_name")
g = dict(grp(f"SELECT COALESCE(sector_id,'(not recorded)'), COUNT(DISTINCT request_id) FROM {V} GROUP BY 1"))
add(C, "C01-011-01", "How many CM ELEVATE applicants are associated with each sector?",
    [[[U.norm(k).split()[0] if k != "(not recorded)" else "not recorded"], v] for k, v in g.items()],
    tc="CM-ELEVATE-OFF-011", level="State x Sector", truth="GROUP BY sector")
sectors = [r[0] for r in grp(f"SELECT DISTINCT sector_id FROM {V} WHERE sector_id IS NOT NULL ORDER BY 1")]
for i, (d, sec) in enumerate(itertools.product(dists, sectors)):
    add(C, f"C01-012-{i+1:02}", f"How many applicants are associated with the {sec} sector in {U.title(d)}?",
        [[None, cnt("sector_id=%s AND lgd_district=%s", (sec, d))]], tc="CM-ELEVATE-OFF-012", level="District x Sector",
        pick=["district"], truth=f"sector_id='{sec}' AND lgd_district='{d}'")
for i, (s, sec) in enumerate(itertools.product(progs, sectors)):
    add(C, f"C01-013-{i+1:02}", f"How many applicants under {P(s)} belong to the {sec} sector?",
        [[None, cnt("scheme_name=%s AND sector_id=%s", (s, sec))]], tc="CM-ELEVATE-OFF-013", level="Programme x Sector",
        truth=f"scheme_name='{s}' AND sector_id='{sec}'")
for i, d in enumerate(dists):
    s1 = "Meghalaya Poultry Farming Scheme"
    s2 = ["Meghalaya Piggery Development Scheme", "Meghalaya Dairy Development Scheme", "Meghalaya Goat Farming Scheme"][i % 3]
    sec = sectors[i % len(sectors)]
    a, b_ = (cnt("scheme_name=%s AND sector_id=%s AND lgd_district=%s", (s, sec, d)) for s in (s1, s2))
    add(C, f"C01-014-{i+1:02}", f"How many applicants under {P(s1)} and {P(s2)} are associated with the {sec} sector in {U.title(d)}?",
        [[K(s1), a], [K(s2), b_]], total=a + b_, tc="CM-ELEVATE-OFF-014", level="District x Sector x 2 Programmes",
        pick=["district"], truth=f"sector_id='{sec}' AND lgd_district='{d}' GROUP BY scheme_name")
g = dict(grp(f"SELECT current_file_status, COUNT(DISTINCT request_id) FROM {V} GROUP BY 1"))
add(C, "C01-015-01", "What is the current application status distribution across CM ELEVATE?",
    [[U.STATUS_KW[k], v] for k, v in g.items()], tc="CM-ELEVATE-OFF-015", level="State x Status", truth="GROUP BY current_file_status")
for i, s in enumerate(progs):
    g = dict(grp(f"SELECT current_file_status, COUNT(DISTINCT request_id) FROM {V} WHERE scheme_name=%s GROUP BY 1", (s,)))
    add(C, f"C01-016-{i+1:02}", f"What is the status distribution for {P(s)}?", [[U.STATUS_KW[k], v] for k, v in g.items()],
        tc="CM-ELEVATE-OFF-016", level="Programme x Status", truth=f"scheme_name='{s}' GROUP BY current_file_status")
for i, d in enumerate(dists):
    g = dict(grp(f"SELECT current_file_status, COUNT(DISTINCT request_id) FROM {V} WHERE lgd_district=%s GROUP BY 1", (d,)))
    add(C, f"C01-017-{i+1:02}", f"What is the application status distribution in {U.title(d)}?",
        [[U.STATUS_KW[k], v] for k, v in g.items()], tc="CM-ELEVATE-OFF-017", level="District x Status", pick=["district"],
        truth=f"lgd_district='{d}' GROUP BY current_file_status")
for i, lvl in enumerate(["level0", "level1", "level2", "level3", "level4"]):
    add(C, f"C01-018-{i+1:02}", f"How many CM ELEVATE applications are pending at level {lvl[-1]}?",
        [[None, cnt("current_level=%s", (lvl,))]], tc="CM-ELEVATE-OFF-018", level="State x Level",
        truth=f"current_level='{lvl}' (KI-070 / KI-422)")
g = grp(f"SELECT scheme_name, COUNT(DISTINCT request_id) FROM {V} WHERE {ONHOLD} GROUP BY 1 ORDER BY 2 DESC")
add(C, "C01-019-01", "Which CM ELEVATE programs have the highest number of pending applications?",
    [[K(k), v] for k, v in g[:3]], tc="CM-ELEVATE-OFF-019", level="State x Programme", truth=f"{ONHOLD} GROUP BY scheme_name")
g = grp(f"SELECT lgd_district, COUNT(DISTINCT request_id) FROM {V} WHERE {ONHOLD} GROUP BY 1 ORDER BY 2 DESC")
add(C, "C01-020-01", "Which districts have the highest number of pending CM ELEVATE applications?",
    [[[U.norm(k)], v] for k, v in g[:3]], tc="CM-ELEVATE-OFF-020", level="District (all)", truth=f"{ONHOLD} GROUP BY lgd_district")
for i, d in enumerate(dists):
    s = progs[(i + 3) % 15]
    add(C, f"C01-021-{i+1:02}", f"How many applications are pending under {P(s)} in {U.title(d)}?",
        [[None, cnt(f"{ONHOLD} AND scheme_name=%s AND lgd_district=%s", (s, d))]], tc="CM-ELEVATE-OFF-021",
        level="District x Programme x Pending", pick=["district"], truth=f"{ONHOLD} AND scheme_name='{s}' AND lgd_district='{d}'")
for i, d in enumerate(dists):
    tot = cnt("lgd_district=%s", (d,))
    val = cnt("data_verified='Valid' AND lgd_district=%s", (d,))
    add(C, f"C01-022-{i+1:02}", f"How many applicants have completed data verification in {U.title(d)}?",
        [[None, val], [None, tot - val]], tc="CM-ELEVATE-OFF-022", level="District x Verification", pick=["district"],
        truth=f"Valid AND lgd_district='{d}'; non-verified = total - valid", extra={"rate": round(100 * val / tot, 1)})
for i, d in enumerate(dists):
    s = progs[(i + 6) % 15]
    add(C, f"C01-023-{i+1:02}", f"How many applications are currently on hold under {P(s)} in {U.title(d)}?",
        [[None, cnt(f"{ONHOLD} AND scheme_name=%s AND lgd_district=%s", (s, d))]], tc="CM-ELEVATE-OFF-023",
        level="District x Programme x On hold", pick=["district"], truth=f"{ONHOLD} AND scheme_name='{s}' AND lgd_district='{d}'")
for i, d in enumerate(dists):
    s = progs[i % 15]
    q = (f"How many applications have been withdrawn under {P(s)} in {U.title(d)}?" if i % 2 else
         f"How many applications have been withdrawn across CM ELEVATE in {U.title(d)}?")
    add(C, f"C01-024-{i+1:02}", q, [[None, cnt("is_withdraw AND lgd_district=%s", (d,))]], tc="CM-ELEVATE-OFF-024",
        level="District x Withdrawn", pick=["district"], truth=f"is_withdraw AND lgd_district='{d}'")
for i, d in enumerate(dists):
    ss = [progs[(3 * i + k) % 6] for k in range(3)]
    checks = []
    for s in ss:
        checks.append([K(s), cnt("scheme_name=%s AND lgd_district=%s", (s, d))])
        checks.append([K(s), cnt(f"{ONHOLD} AND scheme_name=%s AND lgd_district=%s", (s, d))])
    add(C, f"C01-025-{i+1:02}",
        f"Give me the applicant count and pendency status for {P(ss[0])}, {P(ss[1])} and {P(ss[2])} in {U.title(d)}, broken down by sector.",
        checks, tc="CM-ELEVATE-OFF-025", level="District x 3 Programmes x Sector", pick=["district"],
        truth=f"lgd_district='{d}' per programme: total and on hold")
for i, (d, b, bl) in enumerate(places_block):
    top = grp(f"SELECT scheme_name FROM {V} WHERE lgd_block = ANY(%s) GROUP BY 1 ORDER BY COUNT(DISTINCT request_id) DESC LIMIT 1", (bl,))
    s = top[0][0]
    g = grp(f"""SELECT lgd_village_name, COUNT(DISTINCT request_id) FROM {V} WHERE scheme_name=%s AND lgd_block = ANY(%s)
                AND entity_type <> 'Unresolved' GROUP BY village_code, lgd_village_name ORDER BY 2 DESC, 1""", (s, bl))
    add(C, f"C01-026-{i+1:02}", f"How many applicants are there under {P(s)} in each village of {U.block_say(b)}?",
        [[[U.norm(k)], v] for k, v in g[:5]], tc="CM-ELEVATE-OFF-026", level="Block -> Village x Programme",
        pick=["block", U.block_core(b)], truth=f"scheme_name='{s}' AND lgd_block IN {bl} GROUP BY village (top 5 checked)")
for i, d in enumerate(dists):
    d2 = dists[(i + 1) % len(dists)]
    s1, s2 = progs[(2 * i) % 6], progs[(2 * i + 1) % 6]
    checks = [[K(s) + [U.norm(x)], cnt("scheme_name=%s AND lgd_district=%s", (s, x))] for s in (s1, s2) for x in (d, d2)]
    add(C, f"C01-027-{i+1:02}", f"Compare applicant counts for {P(s1)} and {P(s2)} across {U.title(d)} and {U.title(d2)}.",
        checks, tc="CM-ELEVATE-OFF-027", level="2 Districts x 2 Programmes", truth="per (scheme_name, lgd_district)")
for i, d in enumerate(dists):
    g = grp(f"SELECT COALESCE(sector_id,'(not recorded)'), COUNT(DISTINCT request_id) FROM {V} WHERE {ONHOLD} AND lgd_district=%s GROUP BY 1", (d,))
    add(C, f"C01-028-{i+1:02}", f"How many applications are pending in each sector in {U.title(d)}?",
        [[None, v] for k, v in g], tc="CM-ELEVATE-OFF-028", level="District x Sector x Pending", pick=["district"],
        truth=f"{ONHOLD} AND lgd_district='{d}' GROUP BY sector")
for i, d in enumerate(dists):
    s1, s2 = progs[(2 * i) % 6], progs[(2 * i + 1) % 6]
    st, where = (("on hold", ONHOLD) if i % 2 == 0 else ("forwarded", "current_file_status='forward'"))
    a, b_ = (cnt(f"{where} AND scheme_name=%s AND lgd_district=%s", (s, d)) for s in (s1, s2))
    add(C, f"C01-029-{i+1:02}", f"How many applications under {P(s1)} and {P(s2)} are currently {st} in {U.title(d)}?",
        [[K(s1), a], [K(s2), b_]], total=a + b_, tc="CM-ELEVATE-OFF-029", level="District x 2 Programmes x Status",
        pick=["district"], truth=f"{where} AND lgd_district='{d}' GROUP BY scheme_name")
counts["C01_sheet"] = (len(rows_out) - n0, "30 templates; every district (12) / block (66 places, 67 stored) / sector (4) "
                       "/ programme (15) / level (5) in each slot; village templates 003/008/030 are C02")

# ═══ C02 every village with data: count (003), programme (008), status-wise (030) ═══
n0 = len(rows_out)
vil = grp(f"""SELECT village_code, MIN(lgd_village_name), MIN(lgd_block), MIN(lgd_district), COUNT(DISTINCT request_id)
              FROM {V} WHERE entity_type <> 'Unresolved' GROUP BY village_code ORDER BY village_code""")
vname = {}
for code, nm, b, d, n in vil:
    vname.setdefault(nm.upper(), []).append(code)
vprog = {}
for code, s, n in grp(f"""SELECT village_code, scheme_name, COUNT(DISTINCT request_id) FROM {V}
                          WHERE entity_type <> 'Unresolved' GROUP BY 1,2 ORDER BY 1, 3 DESC, 2"""):
    vprog.setdefault(code, []).append((s, n))
vstat = {}
for code, s, st, n in grp(f"""SELECT village_code, scheme_name, current_file_status, COUNT(DISTINCT request_id) FROM {V}
                              WHERE entity_type <> 'Unresolved' GROUP BY 1,2,3"""):
    vstat.setdefault((code, s), []).append((st, n))
vac = {}
for code, a, n in grp(f"""SELECT village_code, ac_name, COUNT(DISTINCT request_id) FROM {V}
                          WHERE entity_type <> 'Unresolved' AND ac_name IS NOT NULL GROUP BY 1,2"""):
    vac.setdefault(code, []).append((a, n))


def vq(nm, b):
    """the village as a user names it: a shared name gets its block"""
    return nm if len(vname[nm.upper()]) == 1 else f"{nm} village of {U.block_say(b)} block"


for code, nm, b, d, n in vil:
    pick = [f"village&{U.block_core(b)}", "village", U.block_core(b), U.norm(d)]
    add("C02_village", f"C02-CNT-{code}", f"How many CM ELEVATE applicants are there in {vq(nm, b)}?", [[None, n]],
        tc="CM-ELEVATE-OFF-003", level="Village", pick=pick, truth=f"village_code={code} ({b} / {d})")
    s, ns = vprog[code][0]
    add("C02_village", f"C02-PRG-{code}", f"How many applicants are there under {P(s)} in {vq(nm, b)}?", [[None, ns]],
        tc="CM-ELEVATE-OFF-008", level="Village x Programme", pick=pick, truth=f"scheme_name='{s}' AND village_code={code}")
    add("C02_village", f"C02-STS-{code}", f"What is the status-wise applicant count for {P(s)} in {vq(nm, b)}?",
        [[U.STATUS_KW[st], c] for st, c in vstat[(code, s)]], tc="CM-ELEVATE-OFF-030", level="Village x Programme x Status",
        pick=pick, truth=f"scheme_name='{s}' AND village_code={code} GROUP BY current_file_status")
counts["C02_village"] = (len(rows_out) - n0, f"{len(vil)} villages with CM Elevate data x 3 metrics = {3 * len(vil)}")

# ═══ C03 every shared village name: alone, and with each of its blocks ═══
n0 = len(rows_out)
vinfo = {code: (nm, b, d, n) for code, nm, b, d, n in vil}
for nm, codes in sorted(vname.items()):
    if len(codes) < 2:
        continue
    tw = [vinfo[c] for c in codes]
    key = U.norm(nm).replace(" ", "_")
    if len(tw) <= 3 and len({t[1] for t in tw}) == len(tw):
        add("C03_shared", f"C03-ALONE-{key}", f"How many CM ELEVATE applicants are there in {tw[0][0]}?",
            [[[U.block_core(t[1])], t[3]] for t in tw], level="Village (shared name, alone)", pick=["village"],
            desc="J-10: up to three same-name villages in different blocks are each answered with their block",
            truth="per village_code " + ", ".join(f"{c}={vinfo[c][3]}" for c in codes))
    else:
        add("C03_shared", f"C03-ALONE-{key}", f"How many CM ELEVATE applicants are there in {tw[0][0]}?", [],
            kind="pause_or_each", level="Village (shared name, alone)", pick=["village"],
            desc="more than three twins or two in one block: the bot asks which village (a valid outcome) or lists each",
            truth="per village_code " + ", ".join(f"{c}={vinfo[c][3]}" for c in codes),
            extra={"each": [[U.block_core(vinfo[c][1]), vinfo[c][3]] for c in codes]})
    for c in codes:
        t = vinfo[c]
        add("C03_shared", f"C03-BLK-{c}", f"How many CM ELEVATE applicants are there in {t[0]} village of {U.block_say(t[1])} block?",
            [[None, t[3]]], level="Village (shared name, with block)", pick=[f"village&{U.block_core(t[1])}", "village", U.block_core(t[1])],
            truth=f"village_code={c}")
nshared = sum(1 for v in vname.values() if len(v) > 1)
counts["C03_shared"] = (len(rows_out) - n0, f"{nshared} shared names (alone) + {sum(len(v) for v in vname.values() if len(v) > 1)} "
                        "villages carrying them (with block)")

# ═══ C04 every place: region, district, block, constituency (+ state); time asks -> refusal ═══
n0 = len(rows_out)
add("C04_places", "C04-STATE", "How many CM Elevate applications are there in total?", [[None, cnt("TRUE")]], level="State",
    truth="COUNT(DISTINCT request_id)")
for lvl, lab, qtxt, where, args, pick in PLACES:
    add("C04_places", f"C04-{lvl[:3].upper()}-{U.norm(lab).replace(' ', '_')}", f"How many CM Elevate applicants are there in {qtxt}?",
        [[None, cnt(where, args)]], level=lvl, pick=pick, truth=f"{where} {args}")
for fy in FYS:
    add("C04_places", f"C04-FY-{fy}", f"How many CM Elevate applications were received in FY {fy}?", [], kind="no_time",
        level="State x FY", truth="no time dimension: refusal expected")
add("C04_places", "C04-MONTHLY", "Show the monthly totals of CM Elevate applications.", [], kind="no_time", level="State x Month",
    truth="no time dimension: refusal expected")
add("C04_places", "C04-YOY", "Compare CM Elevate applications in 2024-25 with 2023-24.", [], kind="no_time", level="Year vs year",
    truth="no time dimension: refusal expected")
counts["C04_places"] = (len(rows_out) - n0, f"1 state + {len(regions)} regions + {len(dists)} districts + {len(places_block)} "
                        f"blocks + {len(acs)} constituencies; CM Elevate FYs in DB: 0 -> {len(FYS)} FY + 1 monthly + 1 YoY refusals")

# ═══ C05 block x constituency, village -> constituency, constituency spanning two districts ═══
n0 = len(rows_out)
pairs = grp(f"""SELECT lgd_block, ac_name, COUNT(DISTINCT request_id) FROM {V} WHERE ac_name IS NOT NULL
                GROUP BY 1,2 ORDER BY 1,2""")
b2bl = {}
for d, b, bl in places_block:
    for x in bl:
        b2bl[x] = (b, bl)
done_pairs = {}
for b, a, n in pairs:
    rep, bl = b2bl[b]
    done_pairs[(rep, a)] = done_pairs.get((rep, a), 0) + n
for (b, a), n in sorted(done_pairs.items()):
    add("C05_cross", f"C05-BxAC-{U.norm(b).replace(' ', '_')}-{U.norm(a).replace(' ', '_')}",
        f"How many CM Elevate applicants in {U.block_say(b)}{'' if ('Municipal' in U.block_say(b) or 'Town' in U.block_say(b)) else ' block'} fall in the {a} assembly constituency?",
        [[None, n]], level="Block x Constituency", pick=["block", "constituency"], truth=f"lgd_block IN {b2bl[b][1]} AND ac_name='{a}'")
for code, nm, b, d, n in vil:
    if code not in vac:
        continue
    a = max(vac[code], key=lambda x: x[1])[0]
    add("C05_cross", f"C05-V2AC-{code}", f"Which assembly constituency is {vq(nm, b)} in, for CM Elevate?",
        [[[U.norm(a)], None]], kind="label_only", level="Village -> Constituency",
        pick=[U.block_core(b), U.norm(d), "village"], truth=f"village_code={code} -> ac_name='{a}'")
span = grp(f"""SELECT ac_name, lgd_district, COUNT(DISTINCT request_id) FROM {V} WHERE ac_name IN
               (SELECT ac_name FROM {V} WHERE ac_name IS NOT NULL GROUP BY 1 HAVING COUNT(DISTINCT lgd_district) > 1)
               GROUP BY 1,2 ORDER BY 1,2""")
for a, d, n in span:
    add("C05_cross", f"C05-SPAN-{U.norm(a).replace(' ', '_')}-{U.norm(d).replace(' ', '_')}",
        f"How many CM Elevate applicants in the {a} assembly constituency are in {U.title(d)} district?", [[None, n]],
        level="Constituency spanning 2 districts (part)", pick=["constituency"], truth=f"ac_name='{a}' AND lgd_district='{d}'")
counts["C05_cross"] = (len(rows_out) - n0, f"{len(done_pairs)} block x AC pairs ({len(pairs)} stored, Tura spellings merged) + "
                       f"{len(vac)} villages with a constituency + {len(span)} constituency-district parts")

# ═══ C06 every place x FY -> refusal (no time dimension) ═══
n0 = len(rows_out)
for i, (lvl, lab, qtxt, where, args, pick) in enumerate(PLACES):
    for fy in FYS:
        add("C06_place_fy", f"C06-{lvl[:3].upper()}-{U.norm(lab).replace(' ', '_')}-{fy}",
            f"How many CM Elevate applicants were there in {qtxt} in FY {fy}?", [], kind="no_time", level=f"{lvl} x FY",
            pick=pick, truth="no time dimension: refusal expected")
counts["C06_place_fy"] = (len(rows_out) - n0, f"{len(PLACES)} places x {len(FYS)} FYs (CM Elevate holds 0 FYs: every one a refusal)")

# ═══ C07 every place x every dimension value (one breakdown per place x dimension checks every value) ═══
n0 = len(rows_out)
DIMS = [("scheme_name", "programme", lambda k: K(k)),
        ("current_file_status", "file status", lambda k: U.STATUS_KW[k]),
        ("COALESCE(data_verified,'(not recorded)')", "data verification status", None),
        ("current_level", "current level", lambda k: [k.replace("level", "level ")] + [k]),
        ("applicant_category", "applicant category", lambda k: [k]),
        ("application_mode", "application mode", lambda k: {"online": ["online"], "cmconnectcenter": ["connect"]}[k]),
        ("COALESCE(sector_id,'(not recorded)')", "sector", lambda k: [U.norm(k)] if k != "(not recorded)" else ["not recorded"])]
for lvl, lab, qtxt, where, args, pick in PLACES:
    for col, word, kw in DIMS:
        g = grp(f"SELECT {col}, COUNT(DISTINCT request_id) FROM {V} WHERE {where} GROUP BY 1 ORDER BY 2 DESC", args)
        add("C07_place_dim", f"C07-{lvl[:3].upper()}-{U.norm(lab).replace(' ', '_')}-{word.replace(' ', '_')}",
            f"Break down CM Elevate applicants in {qtxt} by {word}.",
            [[kw(k) if kw else None, v] for k, v in g], level=f"{lvl} x {word}", pick=pick,
            truth=f"{where} {args} GROUP BY {col}")
for col, word, kw in DIMS:
    add("C07_place_dim", f"C07-FY-{word.replace(' ', '_')}", f"Break down CM Elevate applicants by {word} for FY 2024-25.", [],
        kind="no_time", level=f"{word} x FY", truth="no time dimension: refusal expected")
counts["C07_place_dim"] = (len(rows_out) - n0, f"{len(PLACES)} places x {len(DIMS)} dimensions (every value of each checked: "
                           "15 programmes, 3 file statuses, 5 verification values, 4 levels, 3 categories, 2 modes, 5 sector values) "
                           f"+ {len(DIMS)} dimension x FY refusals")

# ═══ C08 place x date range -> refusal ═══
n0 = len(rows_out)
Q = [("April to June 2025", "Q1"), ("July to September 2025", "Q2"), ("October to December 2025", "Q3"), ("January to March 2026", "Q4"),
     ("1 January 2025 to 31 March 2025", "R1"), ("the last six months", "R2"), ("between 15 August 2024 and 15 November 2024", "R3")]
for d in dists:
    for rng, tag in Q:
        add("C08_daterange", f"C08-{U.norm(d).replace(' ', '_')}-{tag}", f"How many CM Elevate applications were made in {U.title(d)} from {rng}?"
            if not rng.startswith(("the", "between")) else f"How many CM Elevate applications were made in {U.title(d)} {'in' if rng.startswith('the') else ''} {rng}?".replace("  ", " "),
            [], kind="no_time", level="District x date range", pick=["district"], truth="no date column: refusal expected")
counts["C08_daterange"] = (len(rows_out) - n0, f"{len(dists)} districts x (4 quarters + 3 custom ranges); CM Elevate holds no date column")

# ═══ C09 comparisons: every district pair; every block pair / constituency pair within each district ═══
n0 = len(rows_out)
dc = {d: cnt("lgd_district=%s", (d,)) for d in dists}
for a, b in itertools.combinations(dists, 2):
    add("C09_compare", f"C09-DD-{U.norm(a).replace(' ', '_')}-{U.norm(b).replace(' ', '_')}",
        f"Compare CM Elevate applicants in {U.title(a)} and {U.title(b)}.", [[[U.norm(a)], dc[a]], [[U.norm(b)], dc[b]]],
        level="District pair", truth="per lgd_district")
bc = {b: cnt("lgd_block = ANY(%s)", (bl,)) for d, b, bl in places_block}
for d in dists:
    bs = [b for dd, b, bl in places_block if dd == d]
    for a, b in itertools.combinations(bs, 2):
        add("C09_compare", f"C09-BB-{U.norm(a).replace(' ', '_')}-{U.norm(b).replace(' ', '_')}",
            f"Compare CM Elevate applicants in {U.block_say(a)}{'' if 'Municipal' in U.block_say(a) or 'Town' in U.block_say(a) else ' block'} "
            f"and {U.block_say(b)}{'' if 'Municipal' in U.block_say(b) or 'Town' in U.block_say(b) else ' block'}.",
            [[[U.block_core(a)], bc[a]], [[U.block_core(b)], bc[b]]], level=f"Block pair ({U.title(d)})", pick=["block"],
            truth="per lgd_block")
acd = {}
for a, d in grp(f"SELECT DISTINCT ac_name, lgd_district FROM {V} WHERE ac_name IS NOT NULL ORDER BY 2,1"):
    acd.setdefault(d, []).append(a)
acc = {a: cnt("ac_name=%s", (a,)) for a in acs}
for d in dists:
    for a, b in itertools.combinations(acd.get(d, []), 2):
        add("C09_compare", f"C09-AA-{U.norm(d).replace(' ', '_')}-{U.norm(a).replace(' ', '_')}-{U.norm(b).replace(' ', '_')}",
            f"Compare CM Elevate applicants in the {a} and {b} assembly constituencies.",
            [[[U.norm(a)], acc[a]], [[U.norm(b)], acc[b]]], level=f"Constituency pair ({U.title(d)})", pick=["constituency"],
            truth="per ac_name (whole constituency)")
counts["C09_compare"] = (len(rows_out) - n0, f"C(12,2)=66 district pairs + block pairs within each district "
                         f"({sum(len(list(itertools.combinations([b for dd, b, bl in places_block if dd == d], 2))) for d in dists)}) "
                         f"+ constituency pairs within each district ({sum(len(list(itertools.combinations(acd.get(d, []), 2))) for d in dists)})")

# ═══ C10 top-5 / bottom-5 ═══
n0 = len(rows_out)
for d in dists:
    g = grp(f"SELECT lgd_block, COUNT(DISTINCT request_id) FROM {V} WHERE lgd_district=%s GROUP BY 1 ORDER BY 2 DESC", (d,))
    merged = {}
    for b, n in g:
        merged[b2bl[b][0]] = merged.get(b2bl[b][0], 0) + n
    srt = sorted(merged.items(), key=lambda x: -x[1])
    for tag, part, word in (("TOP", srt[:5], "top 5"), ("BOT", srt[-5:], "bottom 5")):
        add("C10_topbottom", f"C10-BLK-{tag}-{U.norm(d).replace(' ', '_')}", f"Which are the {word} blocks in {U.title(d)} by CM Elevate applicants?",
            [[[U.block_core(b)], n] for b, n in part], level="Blocks per district", pick=["district", "complete list"], truth="GROUP BY lgd_block")
g = grp(f"SELECT lgd_district, COUNT(DISTINCT request_id) FROM {V} GROUP BY 1 ORDER BY 2 DESC")
add("C10_topbottom", "C10-DIST-TOP", "Which are the top 5 districts by CM Elevate applicants?", [[[U.norm(k)], v] for k, v in g[:5]],
    level="Districts", truth="GROUP BY lgd_district")
add("C10_topbottom", "C10-DIST-BOT", "Which are the bottom 5 districts by CM Elevate applicants?", [[[U.norm(k)], v] for k, v in g[-5:]],
    level="Districts", truth="GROUP BY lgd_district")
g = grp(f"SELECT ac_name, COUNT(DISTINCT request_id) FROM {V} WHERE ac_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
add("C10_topbottom", "C10-AC-TOP", "Which are the top 5 assembly constituencies by CM Elevate applicants?",
    [[[U.norm(k)], v] for k, v in g[:5]], level="Constituencies", truth="GROUP BY ac_name")
add("C10_topbottom", "C10-AC-BOT", "Which are the bottom 5 assembly constituencies by CM Elevate applicants?",
    [[[U.norm(k)], v] for k, v in g[-5:]], level="Constituencies", truth="GROUP BY ac_name")
for d in dists:
    g = grp(f"""SELECT village_code, MIN(lgd_village_name), COUNT(DISTINCT request_id) FROM {V} WHERE lgd_district=%s
                AND entity_type <> 'Unresolved' GROUP BY 1 ORDER BY 3 DESC, 2""", (d,))
    add("C10_topbottom", f"C10-VIL-TOP-{U.norm(d).replace(' ', '_')}", f"Which are the top 5 villages in {U.title(d)} by CM Elevate applicants?",
        [[[U.norm(nm)], n] for c, nm, n in g[:5]], level="Villages per district", pick=["district"], truth="GROUP BY village_code",
        extra={"ties_at": g[4][2] if len(g) >= 5 else None})
    add("C10_topbottom", f"C10-VIL-BOT-{U.norm(d).replace(' ', '_')}", f"Which are the bottom 5 villages in {U.title(d)} by CM Elevate applicants?",
        [], kind="bottom_villages", level="Villages per district", pick=["district"], truth="GROUP BY village_code (min count)",
        extra={"min": g[-1][2], "names_at_min": [U.norm(nm) for c, nm, n in g if n == g[-1][2]]})
counts["C10_topbottom"] = (len(rows_out) - n0, f"{len(dists)} districts x blocks top/bottom + districts top/bottom + constituencies top/bottom "
                           f"+ {len(dists)} districts x villages top/bottom; per-FY: 0 FYs")

# ═══ C11 named entities: none exposed -> must not return personal data ═══
n0 = len(rows_out)
for i, q in enumerate(["Give me the names of the CM Elevate applicants in Umling block.",
                       "What is the phone number of the CM Elevate applicant with the most applications?",
                       "Show me the Aadhaar numbers of CM Elevate Piggery applicants in Ri Bhoi.",
                       "Who applied for the CM Elevate Cinema Theatre scheme?",
                       "List the CM Elevate applicants' bank account numbers in West Garo Hills."]):
    add("C11_named", f"C11-NAME-{i+1}", q, [], kind="no_names", level="Named entity", truth="no names / personal data in v_cm_elevate")
counts["C11_named"] = (len(rows_out) - n0, "v_cm_elevate exposes no beneficiary / unit names (0) -> 5 personal-data refusals")

# ═══ C12 3-turn follow-up chain per district ═══
n0 = len(rows_out)
for d in dists:
    oh = cnt(f"{ONHOLD} AND lgd_district=%s", (d,))
    g = grp(f"SELECT lgd_block, COUNT(DISTINCT request_id) FROM {V} WHERE lgd_district=%s GROUP BY 1", (d,))
    merged = {}
    for b, n in g:
        merged[b2bl[b][0]] = merged.get(b2bl[b][0], 0) + n
    turns = [{"say": f"How many CM Elevate applicants are there in {U.title(d)}?", "checks": [[None, dc[d]]]},
             {"say": "And how many of them are on hold?", "checks": [[None, oh]]},
             {"say": "Break the applicants down by block.", "checks": [[None, n] for b, n in merged.items()]}]
    add("C12_followup", f"C12-{U.norm(d).replace(' ', '_')}", turns, [], kind="chain", level="District chain", pick=["district"],
        truth="T1 lgd_district; T2 + On Hold; T3 GROUP BY lgd_block")
counts["C12_followup"] = (len(rows_out) - n0, f"{len(dists)} districts x 3 turns")

# ═══ C13 3 spelling / casing variants per district, block, constituency ═══
n0 = len(rows_out)


def typo(s):
    """drop the 3rd-from-last letter of the longest word ("Umling" -> "Umlng")"""
    words = s.split()
    i = max(range(len(words)), key=lambda k: len(words[k]))
    w = words[i]
    if len(w) >= 5:
        words[i] = w[:-3] + w[-2:]
    return " ".join(words)


for lvl, lab, qtxt, where, args, pick in PLACES:
    if lvl == "Region":
        continue
    n = cnt(where, args)
    base = qtxt
    for tag, v in (("UP", base.upper()), ("LO", base.lower()), ("TY", typo(base))):
        add("C13_spelling", f"C13-{lvl[:3].upper()}-{U.norm(lab).replace(' ', '_')}-{tag}",
            f"How many CM Elevate applicants are there in {v}?", [[None, n]], level=f"{lvl} ({tag})",
            pick=pick + [U.norm(lab)], truth=f"{where} {args}")
counts["C13_spelling"] = (len(rows_out) - n0, f"3 variants x ({len(dists)} districts + {len(places_block)} blocks + {len(acs)} constituencies)")

# ═══ C14 every zero-record village of the master list + 20 invalid names ═══
n0 = len(rows_out)
zero = grp(f"""SELECT g.village_code, g.lgd_village_name, g.lgd_block, g.lgd_district FROM curated.dim_geography g
               WHERE g.village_code IS NOT NULL AND g.entity_type <> 'Unresolved' AND g.lgd_village_name IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM {V} v WHERE v.village_code = g.village_code) ORDER BY 1""")
for code, nm, b, d in zero:
    bq = f" village of {U.block_say(b)} block" if b else " village"
    add("C14_zero_invalid", f"C14-ZERO-{code}", f"How many CM Elevate applicants are there in {nm}{bq}?", [], kind="zero",
        level="Village with no CM Elevate data", pick=[f"village&{U.block_core(b or '')}", "village", U.block_core(b or ""), U.norm(d or "")],
        truth=f"village_code={code} ({b} / {d}): 0 rows in v_cm_elevate")
INVALID = ["Gotham district", "Xyzabad block", "Narnia village", "Springfield constituency", "Atlantis", "Hogwarts block",
           "Wakanda district", "Zorbatown", "Mordor village", "Lilliput constituency", "Shangri-La district", "Neverland block",
           "Westeros", "Asgard village", "Metropolis district", "Utopia block", "El Dorado constituency", "Camelot village",
           "Brigadoon district", "Avalon block"]
for i, nm in enumerate(INVALID):
    add("C14_zero_invalid", f"C14-INV-{i+1:02}", f"How many CM Elevate applicants are there in {nm}?", [], kind="not_found",
        level="Invalid name", truth="no such place")
counts["C14_zero_invalid"] = (len(rows_out) - n0, f"{len(zero)} master-list villages with no CM Elevate data (dim_geography, "
                              f"Unresolved placeholders excluded) + {len(INVALID)} invalid names")

# ═══ C15 totals (SQL over the full dataset) + app totals ═══
n0 = len(rows_out)
state = cnt("TRUE")


def sqlcheck(tid, desc, ok, detail):
    add("C15_totals", tid, desc, [], kind="sql", level="Totals (SQL)", truth=detail, extra={"ok": bool(ok)})


for b, n in grp(f"SELECT lgd_block, COUNT(DISTINCT request_id) FROM {V} GROUP BY 1"):
    s = grp(f"SELECT SUM(n) FROM (SELECT village_code, COUNT(DISTINCT request_id) n FROM {V} WHERE lgd_block=%s GROUP BY 1) x", (b,))[0][0]
    sqlcheck(f"C15-V2B-{U.norm(b).replace(' ', '_')}", f"villages -> block {b}", s == n, f"sum(villages)={s} block={n}")
for d in dists:
    s = grp(f"SELECT SUM(n) FROM (SELECT lgd_block, COUNT(DISTINCT request_id) n FROM {V} WHERE lgd_district=%s GROUP BY 1) x", (d,))[0][0]
    sqlcheck(f"C15-B2D-{U.norm(d).replace(' ', '_')}", f"blocks -> district {d}", s == dc[d], f"sum(blocks)={s} district={dc[d]}")
for r in regions:
    n = cnt("region=%s", (r,))
    s = grp(f"SELECT SUM(n) FROM (SELECT lgd_district, COUNT(DISTINCT request_id) n FROM {V} WHERE region=%s GROUP BY 1) x", (r,))[0][0]
    sqlcheck(f"C15-D2R-{r}", f"districts -> region {r}", s == n, f"sum(districts)={s} region={n}")
s = grp(f"SELECT SUM(n) FROM (SELECT region, COUNT(DISTINCT request_id) n FROM {V} GROUP BY 1) x")[0][0]
sqlcheck("C15-R2S", "regions -> state", s == state, f"sum(regions)={s} state={state}")
s = grp(f"SELECT SUM(n) FROM (SELECT COALESCE(ac_name,'-'), COUNT(DISTINCT request_id) n FROM {V} GROUP BY 1) x")[0][0]
sqlcheck("C15-AC2S", "constituencies (+ none) -> state", s == state, f"sum={s} state={state}")
for col, word, kw in DIMS:
    s = grp(f"SELECT SUM(n) FROM (SELECT {col}, COUNT(DISTINCT request_id) n FROM {V} GROUP BY 1) x")[0][0]
    sqlcheck(f"C15-DIM-{word.replace(' ', '_')}", f"{word} values -> total", s == state, f"sum={s} state={state}")
for col in ["lgd_district", "lgd_block", "village_code", "region", "COALESCE(ac_name,'-')", "scheme_name"]:
    n = grp(f"SELECT COUNT(*) FROM (SELECT request_id FROM {V} GROUP BY 1 HAVING COUNT(DISTINCT {col}) > 1) x")[0][0]
    sqlcheck(f"C15-ONE-{col.split('(')[-1].split(',')[0]}", f"one {col} per application", n == 0, f"{n} applications in >1")
sqlcheck("C15-FY", "FYs -> all-time / months -> FY", True, "CM Elevate holds no FY or date column: nothing to add up (0 FYs)")
# app-side totals: the bot's own breakdowns add up
for d in dists:
    g = grp(f"SELECT lgd_block, COUNT(DISTINCT request_id) FROM {V} WHERE lgd_district=%s GROUP BY 1", (d,))
    merged = {}
    for b, n in g:
        merged[b2bl[b][0]] = merged.get(b2bl[b][0], 0) + n
    add("C15_totals", f"C15-APP-B2D-{U.norm(d).replace(' ', '_')}", f"How many CM Elevate applicants are there in each block of {U.title(d)}?",
        [[[U.block_core(b)], n] for b, n in merged.items()], level="Totals (app): blocks of a district", pick=["district"],
        truth=f"lgd_district='{d}' GROUP BY lgd_block; sum = {dc[d]}")
for r in regions:
    g = grp(f"SELECT lgd_district, COUNT(DISTINCT request_id) FROM {V} WHERE region=%s GROUP BY 1", (r,))
    add("C15_totals", f"C15-APP-D2R-{r}", f"How many CM Elevate applicants are there in each district of the {r} Hills region?",
        [[[U.norm(k)], v] for k, v in g], level="Totals (app): districts of a region", pick=["region"], truth=f"region='{r}' GROUP BY lgd_district")
g = grp(f"SELECT region, COUNT(DISTINCT request_id) FROM {V} GROUP BY 1")
add("C15_totals", "C15-APP-R2S", "How many CM Elevate applicants are there in each region?", [[[k.lower()], v] for k, v in g],
    level="Totals (app): regions", truth="GROUP BY region")
counts["C15_totals"] = (len(rows_out) - n0, "SQL: villages->block (67 stored blocks), blocks->district (12), districts->region (3), "
                        "regions->state, constituencies->state, 7 dimensions->state, 6 one-place-per-application, FY (n/a); "
                        "app: 12 district block lists, 3 region district lists, 1 region list")

# ═══ C16 scheme disambiguation ═══
n0 = len(rows_out)
DIS = [
    ("How many CM Elevate applications are there?", ["CM Elevate"], [[None, state]]),
    ("How many applicants does CM Elevate have in Ri Bhoi?", ["CM Elevate"], [[None, dc["RI BHOI"]]]),
    ("How many piggery applicants are there?", ["CM Elevate"], [[None, cnt("scheme_name='Meghalaya Piggery Development Scheme'")]]),
    ("How many Prime SEED applications are on hold?", ["CM Elevate"],
     [[None, cnt(f"{ONHOLD} AND scheme_name='PRIME Small Enterprise Empowerment and Development (SEED)'")]]),
    ("How many CM-ELEVATE applicants are in West Garo Hills?", ["CM Elevate"], [[None, dc["WEST GARO HILLS"]]]),
    ("How many CM Elevate applications are on hold in East Khasi Hills?", ["CM Elevate"],
     [[None, cnt(f"{ONHOLD} AND lgd_district='EAST KHASI HILLS'")]]),
    ("How many CM Elevate applications are at level 2?", ["CM Elevate"], [[None, cnt("current_level='level2'")]]),
    ("Total CM Elevate amount disbursed?", ["CM Elevate Legacy"], []),
    ("How much CM Elevate subsidy was sanctioned in Ri Bhoi?", ["CM Elevate Legacy"], []),
    ("CM Elevate Legacy number of records?", ["CM Elevate Legacy"], []),
    ("How many PMAY-G houses were completed in Ri Bhoi?", ["PMAY-G"], []),
    ("How many MGNREGA person-days in Ri Bhoi in FY 2023-24?", ["MGNREGA"], []),
    ("How many Focus Plus beneficiaries are there in Ri Bhoi?", ["Focus Plus"], []),
    ("How many producer groups are there under Focus Legacy?", ["Focus Legacy"], []),
    ("How many applications are on hold at data verification?", ["CM Elevate"], [[None, cnt(ONHOLD)]]),
    ("How many applicants are associated with the Poultry sector?", ["CM Elevate"], [[None, cnt("sector_id='Poultry'")]]),
    ("How many Green Taxi applications are there?", ["CM Elevate"], [[None, cnt("scheme_name='Chief Minister''s Green Taxi Scheme'")]]),
    ("How many Agriculture Response Vehicle applicants are there in Meghalaya?", ["CM Elevate"],
     [[None, cnt("scheme_name='PRIME Agriculture Response Vehicle Scheme'")]]),
    ("What is the gender split of CM Elevate applicants?", ["CM Elevate"], []),
    ("How many CM Elevate applications were approved?", ["CM Elevate"], []),
]
for i, (q, sch, checks) in enumerate(DIS):
    add("C16_disambiguation", f"C16-{i+1:02}", q, checks, kind="scheme", level="Disambiguation", truth=f"schemes = {sch}",
        extra={"schemes": sch})
counts["C16_disambiguation"] = (len(rows_out) - n0, "20 questions that name CM Elevate, its programmes / vocabulary, or a neighbour")

# ══ REDUCED PLAN (user, 2026-10-30 ~02:35: deadline 7 AM) ════════════════════
# Kept whole: sheet templates (+ constituency fills), every village (count), every shared name,
# every place x every FY, all totals, invalid names, the "which scheme?" rule. About 20 each for
# comparisons, top-N, date ranges, spelling variants, follow-up chats; 5 named-entity refusals
# (CM Elevate exposes no names); 100 zero-record villages; 20 paraphrases. Dropped: C05, C07,
# village programme / status metrics. IDs of kept tests are unchanged, so earlier results stand.
REDUCED = "--full" not in sys.argv
if REDUCED:
    full_counts = dict(counts)

    def spread(rows, n):
        if len(rows) <= n:
            return rows
        step = len(rows) / n
        return [rows[int(i * step)] for i in range(n)]

    by = {}
    for r in rows_out:
        by.setdefault(r["category"], []).append(r)
    keep = []
    keep += by["C01_sheet"]
    for i, a in enumerate(acs):                            # sheet templates filled with every constituency
        add("C01_sheet", f"C01-001AC-{i+1:02}", f"How many CM ELEVATE applicants are there in {a} constituency?",
            [[None, cnt("ac_name=%s", (a,))]], tc="CM-ELEVATE-OFF-001", level="Constituency", pick=["constituency"],
            truth=f"ac_name='{a}'")
        g = dict(grp(f"SELECT current_file_status, COUNT(DISTINCT request_id) FROM {V} WHERE ac_name=%s GROUP BY 1", (a,)))
        add("C01_sheet", f"C01-017AC-{i+1:02}", f"What is the application status distribution in {a} constituency?",
            [[U.STATUS_KW[k], v] for k, v in g.items()], tc="CM-ELEVATE-OFF-017", level="Constituency x Status",
            pick=["constituency", "cm elevate"], truth=f"ac_name='{a}' GROUP BY current_file_status")
    keep += [r for r in rows_out if r["id"].startswith(("C01-001AC-", "C01-017AC-"))]
    keep += [r for r in by["C02_village"] if r["id"].startswith("C02-CNT-")]
    keep += by["C03_shared"] + by["C04_places"] + by["C06_place_fy"] + by["C15_totals"] + by["C16_disambiguation"]
    keep += by["C11_named"]
    keep += spread(by["C08_daterange"], 20) + spread(by["C09_compare"], 20) + spread(by["C13_spelling"], 20)
    c10 = by["C10_topbottom"]
    keep += [r for r in c10 if r["id"].startswith(("C10-DIST", "C10-AC"))]
    keep += spread([r for r in c10 if r["id"].startswith("C10-BLK-TOP")], 8)
    keep += spread([r for r in c10 if r["id"].startswith("C10-VIL-TOP")], 8)
    keep += by["C12_followup"]
    for a in spread(acs, 8):                               # 8 constituency chains -> 20 follow-up chats
        oh = cnt(f"{ONHOLD} AND ac_name=%s", (a,))
        g = grp(f"SELECT current_file_status, COUNT(DISTINCT request_id) FROM {V} WHERE ac_name=%s GROUP BY 1", (a,))
        turns = [{"say": f"How many CM Elevate applicants are there in {a} constituency?", "checks": [[None, acc[a]]]},
                 {"say": "How many of them are on hold?", "checks": [[None, oh]]},
                 {"say": "What is their file status distribution?", "checks": [[U.STATUS_KW[k], v] for k, v in g]}]
        add("C12_followup", f"C12-AC-{U.norm(a).replace(' ', '_')}", turns, [], kind="chain", level="Constituency chain",
            pick=["constituency"], truth="T1 ac_name; T2 + On Hold; T3 GROUP BY current_file_status")
    keep += [r for r in rows_out if r["id"].startswith("C12-AC-")]
    z = by["C14_zero_invalid"]
    keep += spread([r for r in z if r["id"].startswith("C14-ZERO-")], 100) + [r for r in z if r["id"].startswith("C14-INV-")]
    rb, pig = dc["RI BHOI"], cnt("scheme_name='Meghalaya Piggery Development Scheme'")
    PARA = [(f"How many CM Elevate applicants are there in Ri Bhoi?", rb), ("Ri Bhoi CM-ELEVATE applicant count?", rb),
            ("Number of applications under CM Elevate for Ri-Bhoi district", rb), ("cm elevate ri bhoi how many applied", rb),
            ("In Ri Bhoi, how many people applied to CM Elevate?", rb), ("Total CMElevate applications in Ri Bhoi district", rb),
            ("Ri Bhoi: CM ELEVATE applicants?", rb), ("What is the count of CM-Elevate applications from RiBhoi?", rb),
            ("Applicants for the Chief Minister's Elevate programme in Ri Bhoi?", rb), ("tell me CM Elevate applicants ri-bhoi", rb),
            ("How many piggery applicants are there under CM Elevate?", pig), ("CM Elevate Piggery scheme: number of applicants?", pig),
            ("Meghalaya Piggery Development Scheme applicants count", pig), ("piggery applications total in CM ELEVATE", pig),
            ("How many people applied for piggery under CM-Elevate?", pig), ("Total applicants, CM Elevate pig farming (piggery) scheme", pig),
            ("Piggery Development Scheme: how many applications?", pig), ("count of piggery applicants across Meghalaya, CM Elevate", pig),
            ("In CM Elevate, how many applicants are under Piggery?", pig), ("CMElevate piggery applicants statewide", pig)]
    for i, (q, n) in enumerate(PARA):
        add("C17_paraphrase", f"C17-{i+1:02}", q, [[None, n]], level="Paraphrase", pick=["district"],
            truth="lgd_district='RI BHOI'" if n == rb else "scheme_name='Meghalaya Piggery Development Scheme'")
    keep += [r for r in rows_out if r["category"] == "C17_paraphrase"]
    rows_out[:] = keep
    nc = {}
    for r in rows_out:
        nc[r["category"]] = nc.get(r["category"], 0) + 1
    basis = {
        "C01_sheet": "30 templates; every district (12) / block (66 places) / constituency (60, for 001 and 017) / sector / programme / level; FY: see C06",
        "C02_village": f"{len(vil)} villages with CM Elevate data x 1 (applicant count)",
        "C03_shared": full_counts["C03_shared"][1], "C04_places": full_counts["C04_places"][1],
        "C06_place_fy": full_counts["C06_place_fy"][1], "C15_totals": full_counts["C15_totals"][1],
        "C16_disambiguation": "20 'which scheme?' / dataset-choice questions",
        "C08_daterange": "about 20 (reduced plan) of 84", "C09_compare": "about 20 (reduced plan) of 501",
        "C10_topbottom": "about 20 (reduced plan) of 52", "C11_named": "CM Elevate exposes no names: 5 refusals",
        "C12_followup": "20 chats: 12 districts + 8 constituencies, 3 turns each", "C13_spelling": "about 20 (reduced plan) of 414",
        "C14_zero_invalid": f"100 of {len(zero)} zero-record villages (reduced plan, spread over the list) + 20 invalid names",
        "C17_paraphrase": "20 rewordings of 2 questions"}
    counts = {k: (v, basis.get(k, "")) for k, v in sorted(nc.items())}

# ── write ──────────────────────────────────────────────────────────────────
ids = [r["id"] for r in rows_out]
dup = {i for i in ids if ids.count(i) > 1} if len(ids) != len(set(ids)) else set()
assert not dup, f"duplicate ids: {sorted(dup)[:10]}"
with open(os.path.join(HERE, "test_matrix.csv"), "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows_out[0]))
    w.writeheader()
    w.writerows(rows_out)
with open(os.path.join(HERE, "matrix_counts.txt"), "w", encoding="utf-8") as fh:
    fh.write(f"TOTAL {len(rows_out)}\n")
    for k, (n, basis) in counts.items():
        fh.write(f"{k}\t{n}\tDB basis: {basis}\n")
print(f"TOTAL {len(rows_out)}")
for k, (n, basis) in counts.items():
    print(f"{k:22} {n:6}  {basis}")

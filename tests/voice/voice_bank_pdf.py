"""The client's three test PDFs (30 Oct 2026) spoken through the live voice and the Secretary view (D-100).

Sources: "Megh One AI · NLP Dashboard — Chart Test Questions", "UAT Passed Questions — MGNREGA and PMAY-G",
"RAG Testing — Knowledge and Data". Every question is spoken to the voice in the real chat page; the checks are
voice_bank.py's (V1 one call / one question, V2 one spoken answer, V3 no unsourced figure, D1-D4 every drawn figure,
label, unit and chart type against the answer's own rows, R1 rendering). Whether the BRAIN's answer has the PDF's
figure is reported as information (BRAIN) and never fails a turn: brain issues are out of scope for the voice (user,
2026-11-03: "if any issues come from the brain ignore it").

Run from the repo root (one live session per officer: shard across users that see every scheme):
  MEGH_VOICE_USER=superadmin    python tests/voice/voice_bank_pdf.py --group pdf_rag   --port 9401 [--real]
  MEGH_VOICE_USER=superadmin    python tests/voice/voice_bank_pdf.py --group pdf_chart --port 9402 [--real]   (after the first; harshit_admin has no scheme access)
  MEGH_VOICE_USER=state-rd      python tests/voice/voice_bank_pdf.py --group pdf_uat   --port 9403 [--real]
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import voice_bank as vb  # noqa: E402
from cdp import Browser  # noqa: E402
from ui_voice import mint, silent_wav  # noqa: E402

T = vb.T
ARGS = sys.argv[1:]
PORT = int(ARGS[ARGS.index("--port") + 1]) if "--port" in ARGS else 9401
GROUPS = set(ARGS[ARGS.index("--group") + 1].split(",")) if "--group" in ARGS else None
TAG = "_".join(sorted(GROUPS)) if GROUPS else "all"
REPORT = Path(os.environ.get("TEMP", ".")) / f"megh_voice_pdf_{TAG}{'_real' if vb.REAL else ''}.json"
SHOTS = Path(os.environ.get("TEMP", ".")) / f"megh_pdf_shots_{TAG}"
SHOTS.mkdir(parents=True, exist_ok=True)

PDF = [
    # ── Chart Test Questions §1 (one conversation: 9 and 11 follow their question) ──
    {"id": "CH1", "group": "pdf_chart", "turns": [T("PMAY-G houses completed by district", pic=True, must=["26,822"])]},
    {"id": "CH2", "group": "pdf_chart", "turns": [T("Show MGNREGA person-days trend over the years as a line chart", pic=True, chart="line")]},
    {"id": "CH3", "group": "pdf_chart", "turns": [T("Show total Focus Legacy amount remitted in each financial year as a line chart", pic=True, chart="line")]},
    {"id": "CH4", "group": "pdf_chart", "turns": [T("CM Elevate applications by status as a donut chart", pic=True, chart="donut", must=["8,915"])]},
    {"id": "CH5", "group": "pdf_chart", "turns": [T("Compare PMAY-G houses sanctioned vs completed by district in a grouped bar chart", pic=True, chart="bars")]},
    {"id": "CH6", "group": "pdf_chart", "turns": [T("Show MGNREGA expenditure by financial year as bar chart", pic=True, chart="bars")]},
    {"id": "CH7", "group": "pdf_chart", "turns": [T("Show MGNREGA person-days by district", pic=True)]},
    {"id": "CH8", "group": "pdf_chart", "turns": [T("Top 5 districts by FOCUS+ beneficiaries as a pie chart", pic=True, chart="donut"),
                                                  T("now show it as a bar chart", pic=True, chart="bars")]},
    {"id": "CH10", "group": "pdf_chart", "turns": [T("So compare total beneficiaries in PMAY-G and MGNREGA", pic=True, must=["14,94,437", "1,71,107"]),
                                                   T("for above one give me the bar chart", pic=True, chart="bars"),
                                                   T("now give me pie chart", pic=True, chart="donut"),
                                                   T("give me donut", pic=True, chart="donut")]},
    # §2: questions the chat does not answer correctly (brain issues): only the voice and the picture are checked
    {"id": "CHX1", "group": "pdf_chart", "turns": [T("Show MGNREGA person-days by district", pic=True),
                                                   T("now show the same as a horizontal bar chart", pic=True, chart="race")]},
    {"id": "CHX2", "group": "pdf_chart", "turns": [T("Show MGNREGA expenditure by financial year as bar chart, pie chart and line chart")]},
    {"id": "CHX3", "group": "pdf_chart", "turns": [T("Focus Legacy amount remitted by financial year")]},
    {"id": "CHX4", "group": "pdf_chart", "turns": [T("CM Elevate Legacy subsidy and loan disbursed by scheme as a stacked bar chart")]},
    {"id": "CHX5", "group": "pdf_chart", "turns": [T("Show MGNREGA person-days by district as a radar chart")]},
    # ── UAT Passed Questions: MGNREGA 10 + PMAY-G 10 ──
    {"id": "DATA-001", "group": "pdf_uat", "turns": [T("What was the total expenditure in MAWJYRSIM during 2022-23?", must=["31.70"])]},
    {"id": "DATA-002", "group": "pdf_uat", "turns": [T("What was the total expenditure in West Garo Hills during 2023-24?", any_of=["14,880.51", "148.81"])]},
    {"id": "DATA-003", "group": "pdf_uat", "turns": [T("What was the total expenditure in Gambegre block during 2022-23?", any_of=["1,455.28", "14.55"])]},
    {"id": "DATA-004", "group": "pdf_uat", "turns": [T("How many persons received employment in Amlarem constituency during 2022-23?", must=["5,048"])]},
    {"id": "DATA-014", "group": "pdf_uat", "turns": [T("Which villages in Ampathi constituency received employment in 2023-24?", any_of=["114"])]},
    {"id": "DATA-015", "group": "pdf_uat", "turns": [T("How many total person-days were generated in East Khasi Hills during 2023-24?", must=["30,61,525"])]},
    {"id": "DATA-016", "group": "pdf_uat", "turns": [T("How many households received employment in Nongstoin block during 2025-26?", must=["8,323"])]},
    {"id": "DATA-021", "group": "pdf_uat", "turns": [T("What was the average number of person-days per employment household in South West Khasi Hills during 2024-25?", must=["58.51"])]},
    {"id": "DATA-022", "group": "pdf_uat", "turns": [T("Give me the expenditure breakdown for Myriem during 2023-24.", any_of=["30.87", "17.52"])]},
    {"id": "DATA-025", "group": "pdf_uat", "turns": [T("Which block generated the highest person-days during 2023-24?", any_of=["Zikzak", "ZIKZAK"])]},
    {"id": "PMAY-OFF001", "group": "pdf_uat", "turns": [T("How many PMAY beneficiaries are there in GABIL SONGGITCHAM?", must=["345"])]},
    {"id": "PMAY-OFF002", "group": "pdf_uat", "turns": [T("What is the total amount sanctioned in GABIL SONGGITCHAM?", any_of=["4,48,50,000", "4.49", "448.5"])]},
    {"id": "PMAY-OFF004", "group": "pdf_uat", "turns": [T("How many PMAY houses have been completed in GABIL SONGGITCHAM?", must=["179"])]},
    {"id": "PMAY-OFF006", "group": "pdf_uat", "turns": [T("Give me the house status breakdown for GABIL SONGGITCHAM.", must=["179", "91"])]},
    {"id": "PMAY-OFF007", "group": "pdf_uat", "turns": [T("How much sanctioned amount is still to be released in GABIL SONGGITCHAM?", any_of=["10,81,500", "10.82"])]},
    {"id": "PMAY-OFF011", "group": "pdf_uat", "turns": [T("How many PMAY beneficiaries are there in Amlarem block?", must=["2,377"])]},
    {"id": "PMAY-OFF012", "group": "pdf_uat", "turns": [T("Give me the PMAY financial summary for Amlarem block.", any_of=["30,88,80,000", "30.89"])]},
    {"id": "PMAY-OFF014", "group": "pdf_uat", "turns": [T("Give me the house status breakdown for Amlarem block.", must=["1,693"])]},
    {"id": "PMAY-OFF015", "group": "pdf_uat", "turns": [T("How many PMAY beneficiaries are there in West Garo Hills?", must=["33,147"])]},
    {"id": "PMAY-OFF017", "group": "pdf_uat", "turns": [T("How many PMAY houses have been completed in West Garo Hills?", must=["26,822"])]},
    # ── RAG Testing: 10 knowledge + 10 data (incl. 2 hybrid), one new chat ──
    {"id": "RK1", "group": "pdf_rag", "turns": [T("What is MGNREGA and what are its main objectives?", kind="knowledge", pic=False, any_of=["100 days"])]},
    {"id": "RK2", "group": "pdf_rag", "turns": [T("What happens if work is not provided within 15 days of applying under MGNREGA?", kind="knowledge", pic=False, any_of=["allowance"])]},
    {"id": "RK3", "group": "pdf_rag", "turns": [T("Who is eligible for an MGNREGA job card and how do I apply for one?", kind="knowledge", pic=False, any_of=["Gram Panchayat", "adult"])]},
    {"id": "RK4", "group": "pdf_rag", "turns": [T("What is PMAY-G and how much financial assistance is given per house in Meghalaya?", kind="knowledge", pic=False, any_of=["1.30 lakh", "1.3 lakh", "1,30,000"])]},
    {"id": "RK5", "group": "pdf_rag", "turns": [T("Who is eligible for a house under PMAY-G and how are beneficiaries selected?", kind="knowledge", pic=False, any_of=["SECC", "Awaas"])]},
    {"id": "RK6", "group": "pdf_rag", "turns": [T("What is the FOCUS+ scheme and what benefit does a farmer get under it?", kind="knowledge", pic=False, any_of=["5,000"])]},
    {"id": "RK7", "group": "pdf_rag", "turns": [T("What is CM Elevate and what support does it provide to entrepreneurs?", kind="knowledge", pic=False, any_of=["subsidy"])]},
    {"id": "RK8", "group": "pdf_rag", "turns": [T("What is the difference between the original FOCUS scheme and FOCUS+?", kind="knowledge", pic=False, any_of=["Producer Group", "producer group"])]},
    {"id": "RK9", "group": "pdf_rag", "turns": [T("What documents are needed to apply for a house under PMAY-G?", kind="knowledge", pic=False, any_of=["Aadhaar"])]},
    {"id": "RK10", "group": "pdf_rag", "turns": [T("What is PM-KISAN and how much money do farmers get under it?", kind="refuse", pic=False)]},
    {"id": "RD1", "group": "pdf_rag", "turns": [T("How many PMAY-G houses have been sanctioned and completed in Meghalaya, and what is the completion rate?", must=["1,71,107", "1,29,941"])]},
    {"id": "RD2", "group": "pdf_rag", "turns": [T("How much PMAY-G money has been released in total in Meghalaya?", any_of=["2,185.26", "21,85,25,98,500"])]},
    {"id": "RD3", "group": "pdf_rag", "turns": [T("How many CM Elevate applications are there and how many schemes do they cover?")]},
    {"id": "RD4", "group": "pdf_rag", "turns": [T("What is the total amount disbursed under FOCUS+?", any_of=["119.74", "1,19,73,92,500"])]},
    {"id": "RD5", "group": "pdf_rag", "turns": [T("How many producer groups and memberships have been paid under Focus Legacy?", must=["11,906", "1,02,021"])]},
    {"id": "RD6", "group": "pdf_rag", "turns": [T("How much has been disbursed under CM Elevate Legacy, split into subsidy and loan?", any_of=["82.90", "82.9"])]},
    {"id": "RD7", "group": "pdf_rag", "turns": [T("How many villages had MGNREGA activity and how many person-days were generated in total?", must=["9,09,15,181"])]},
    {"id": "RD8", "group": "pdf_rag", "turns": [T("What is the PMAY-G unit assistance per house in Meghalaya, and how much has actually been released in West Garo Hills?", any_of=["425.01", "4,25,00,80,500"])]},
    {"id": "RD9", "group": "pdf_rag", "turns": [T("How many days of work does MGNREGA guarantee, and how many households completed 100 days in Meghalaya in 2025-26?", any_of=["33,397"])]},
    {"id": "RD10", "group": "pdf_rag", "turns": [T("How many FOCUS+ disbursements have been made and in how many districts?", any_of=["3,85,671"])]},
]


def judge_voice(turn, st, k):
    """voice_bank's checks; its 'says what it must' (V4) becomes BRAIN information, never a failure here."""
    out = []
    for name, ok, detail in vb.judge(turn, st, k):
        if name.startswith("V4"):
            out.append(("BRAIN (info, not failing): the brain's answer has the PDF's figure", True, {"matches_pdf": bool(ok), **(detail if isinstance(detail, dict) else {})}))
            continue
        out.append((name, ok, detail))
    return out


async def main():
    only = set(ARGS[ARGS.index("--only") + 1].split(",")) if "--only" in ARGS else None
    bank = [e for e in PDF if (not GROUPS or e["group"] in GROUPS) and (not only or e["id"] in only)]
    by_group = {}
    for e in bank:
        by_group.setdefault(e["group"], []).append(e)
    token = await mint()
    init = (f"try{{localStorage.setItem('megh_jwt',{json.dumps(token)});}}catch(e){{}}"
            "window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));"
            "window.addEventListener('unhandledrejection',e=>window.__errs.push(String(e.reason)));")
    n = sum(len(e["turns"]) for e in bank)
    print(f"PDF voice bank ({'REAL' if vb.REAL else 'fake'} voice, user {os.environ.get('MEGH_VOICE_USER', 'superadmin')}): "
          f"{len(bank)} items, {n} turns", flush=True)
    results = []
    async with Browser(port=PORT, mic_wav=silent_wav(), init_js=init, size=(1600, 940)) as b:
        for g, items in by_group.items():
            await vb.open_conversation(b)
            for e in items:
                for k, turn in enumerate(e["turns"]):
                    try:
                        st, extra = await vb.run_turn(b, turn)
                        checks = judge_voice(turn, st, k)
                        if extra.get("dropped"):
                            checks.insert(0, ("C the session was still live", False, extra["dropped"]))
                    except Exception as ex:  # noqa: BLE001
                        st, checks = {}, [("the turn completed", False, f"{type(ex).__name__}: {str(ex)[:200]}")]
                    ok = all(c[1] for c in checks)
                    brain = next((c[2].get("matches_pdf") for c in checks if c[0].startswith("BRAIN")), None)
                    results.append({"id": e["id"], "turn": k, "say": turn["say"], "ok": ok, "brain_matches_pdf": brain,
                                    "checks": [[c[0], bool(c[1]), c[2]] for c in checks], "kinds": st.get("kinds"),
                                    "speak": ((st.get("reply") or {}).get("speak") or "")[:300]})
                    tag = f"{e['id']}{'.' + str(k + 1) if len(e['turns']) > 1 else ''}"
                    print(f"{'PASS' if ok else 'FAIL'} {tag:12} {turn['say'][:70]}"
                          f"{'' if brain is not False else '   [brain: figure differs from the PDF]'}", flush=True)
                    for c in checks:
                        if not c[1]:
                            print(f"         ✗ {c[0]}: {json.dumps(c[2], ensure_ascii=False)[:380]}", flush=True)
                    try:
                        await b.shot(str(SHOTS / f"{tag}.png"))
                    except Exception:  # noqa: BLE001
                        pass
    REPORT.write_text(json.dumps({"real": vb.REAL, "turns": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    passed = sum(1 for r in results if r["ok"])
    brain_bad = [r["id"] for r in results if r["brain_matches_pdf"] is False]
    print(f"\n{passed}/{len(results)} turns passed (voice + picture) · brain figure differs from the PDF: {brain_bad or 'none'}"
          f" · report {REPORT}", flush=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

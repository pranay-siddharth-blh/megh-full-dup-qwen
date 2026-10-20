"""Headless check of the "Continue with …" chip after an idle expiry. Run the
app with a short idle window first:
    CONTEXT_IDLE_EXPIRY_SECONDS=60 .venv/Scripts/python.exe -m uvicorn app.main:app --port 8401
    py -3 -X utf8 tests/ui_headless/idle_chip_flow.py logs/ui_shots
Asks an MGNREGA question, waits past the window, asks a knowledge question
(the reply must carry the chip), taps the chip (the topic comes back), then
"what about FY 2023-24?" must answer MGNREGA East Khasi Hills again."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat_flow_lib import answers, ask, banners, last_text, login, open_browser  # noqa: E402

OUT = sys.argv[1]
Path(OUT).mkdir(parents=True, exist_ok=True)
with open_browser() as (b, pg):
    login(pg)
    ask(pg, "How many job cards were issued under MGNREGA in East Jaintia Hills in FY 2024-25?")
    print("A1 banner:", banners(pg)[-1:])
    print("waiting 70 s past the idle window …")
    pg.wait_for_timeout(70000)
    ask(pg, "What is a job card?")
    chips = [e.inner_text().replace("\n", " ") for e in pg.query_selector_all(".continue-offer")]
    print("after idle, chip:", chips)
    pg.screenshot(path=OUT + "/phone_idle_chip.png")
    assert chips and "Continue with MGNREGA" in chips[-1], "no continue chip"
    pg.click(".continue-offer .suggest-item")
    t0 = time.time()
    while time.time() - t0 < 60 and "Picking up" not in last_text(pg):
        pg.wait_for_timeout(500)
    print("after tap:", last_text(pg)[:120])
    ask(pg, "What about FY 2023-24?")
    print("follow-up banner:", banners(pg)[-1:])
    print("follow-up:", last_text(pg)[:140])
    pg.screenshot(path=OUT + "/phone_idle_restored.png")
    b.close()

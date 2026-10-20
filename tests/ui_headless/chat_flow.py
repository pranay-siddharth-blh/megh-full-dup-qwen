"""Headless browser check of the chat UI (context memory, D-050): ask, stop one
mid-way by typing "stop", "continue", go back to an earlier question, "what did
we discuss?", and screenshot at phone (390) / tablet (820) / desktop (1440)
widths. Prints the scope banners, the overflow check (scrollWidth must equal
clientWidth) and console errors. Needs: the app running on BASE (start your
own: `.venv/Scripts/python.exe -m uvicorn app.main:app --port 8401`), the VPN,
a JWT in token.txt next to this file (mint_token.py), and Playwright with
Chromium for the Python that runs it (the system `py -3` has it on the dev box).

    .venv/Scripts/python.exe tests/ui_headless/mint_token.py state-rd tests/ui_headless/token.txt
    py -3 -X utf8 tests/ui_headless/chat_flow.py logs/ui_shots

In-flight messages carry .typing-bubble (the "Thinking…" status pill) and, once the
draft streams, .pending-bubble;
a finished answer has neither."""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8401"
OUT = sys.argv[1]
Path(OUT).mkdir(parents=True, exist_ok=True)


def login(pg):
    tok = Path(__file__).with_name("token.txt").read_text(encoding="utf-8").strip()
    pg.add_init_script("localStorage.setItem('megh_jwt', %s)" % json.dumps(tok))
    pg.goto(BASE + "/megh-chat", wait_until="domcontentloaded", timeout=60000)
    pg.wait_for_selector("textarea.composer-input:visible", timeout=60000)
    pg.wait_for_timeout(1500)


def answers(pg):
    """Finished bot messages: a .msg.bot holding no in-flight bubble."""
    return [m for m in pg.query_selector_all(".msg.bot")
            if m.query_selector(".typing-bubble, .pending-bubble") is None]


def ask(pg, text, wait_s=150):
    before = len(answers(pg))
    pg.fill("textarea.composer-input", text)
    pg.press("textarea.composer-input", "Enter")
    t0 = time.time()
    while time.time() - t0 < wait_s:
        done = answers(pg)
        if len(done) > before and not pg.query_selector(".typing-bubble, .pending-bubble, .draft-cursor"):
            pg.wait_for_timeout(1200)
            return done[-1]
        pg.wait_for_timeout(500)
    raise RuntimeError("no answer for: " + text)


def last_text(pg):
    return answers(pg)[-1].inner_text().replace("\n", " ")[:220]


def banners(pg):
    return [e.inner_text().replace("\n", " ") for e in pg.query_selector_all(".scope-banner")]


def overflow(pg):
    return pg.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 390, "height": 844})
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    login(pg)
    print("logged in")
    ask(pg, "How many person-days were generated under MGNREGA in East Khasi Hills in FY 2022-23?")
    print("A1:", last_text(pg))
    print("banner:", banners(pg))
    pg.screenshot(path=OUT + "/phone_answer.png")
    # stop mid-way, then continue
    pg.fill("textarea.composer-input", "What about Ri Bhoi?")
    pg.press("textarea.composer-input", "Enter")
    pg.wait_for_selector(".typing-bubble, .pending-bubble", timeout=30000)
    pg.wait_for_timeout(1500)
    pg.fill("textarea.composer-input", "stop")
    pg.press("textarea.composer-input", "Enter")
    pg.wait_for_timeout(2000)
    print("after stop:", last_text(pg))
    ask(pg, "continue")
    print("after continue:", last_text(pg))
    print("banners:", banners(pg))
    pg.screenshot(path=OUT + "/phone_continue.png")
    ask(pg, "Go back to the East Khasi Hills one")
    print("back:", last_text(pg), "| last banner:", banners(pg)[-1:])
    ask(pg, "What did we discuss so far?")
    print("history:", last_text(pg)[:160])
    pg.screenshot(path=OUT + "/phone_history.png")
    print("phone scrollWidth/clientWidth:", overflow(pg))
    for name, w, h in (("tablet", 820, 1180), ("desktop", 1440, 900)):
        pg.set_viewport_size({"width": w, "height": h})
        pg.wait_for_timeout(800)
        pg.screenshot(path=OUT + f"/{name}.png")
        print(name, "scrollWidth/clientWidth:", overflow(pg))
    print("console errors:", errs[:5])
    b.close()

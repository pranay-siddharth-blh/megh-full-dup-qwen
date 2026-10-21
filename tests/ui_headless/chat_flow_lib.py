"""Shared helpers for the headless chat checks (see chat_flow.py)."""
import contextlib
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8401"


@contextlib.contextmanager
def open_browser(width=390, height=844):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": width, "height": height})
        yield b, pg


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



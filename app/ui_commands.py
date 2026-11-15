"""Commands about the screen, not about the data: "take me back to the dashboard", "close the chart", "show the chart
again". String methods only (no regex, D-046 / D-047).

User report 2026-11-15 (live voice): "Take me back to the dashboard." took the page back, but the chat pipeline
answered it too, and the guardrail model filed it as an out-of-scope TASK: "I can't do that on your behalf — I can't
apply, book, pay or contact anyone for you." A command to the screen is never a request to act for the officer.

A message is a navigation command only when EVERY word of it is in a closed vocabulary (politeness, verbs of moving
and showing, the names of the screens) and it names where to go — so "dashboard of MGNREGA expenditure" or "show me
PMAY-G houses by district" (data words, numbers, places) are never caught. The page's voice reads the same
vocabulary (frontend/src/chat/voice/voiceViews.js canonicalNav); keep the two lists in step.

  nav_command(text)  -> "desk" (back to the dashboard / home / main screen / close the chart) | "chart" (the chart
                        again) | None
  is_app_command(text) -> a navigation command, or a closed-vocabulary command about the app itself ("repeat that",
                        "scroll down", "download the table as excel"): never an out-of-scope task (guardrails.py).
"""
from __future__ import annotations

_FILLER = frozenset("""please kindly can could would will you me us i we want wanna need to just ok okay now sir madam
hey megh one ai let lets go take get bring put the a my our this that it show open return navigate display view see
head jump switch over on onto up all way right away quickly instead there""".split())
_DESK = frozenset({"dashboard", "dashboards", "desk", "home", "homepage", "overview"})
_SCREEN = frozenset({"screen", "page", "view"})
_MAIN = frozenset({"main", "front", "start", "first", "landing"})
_CHART = frozenset({"chart", "charts", "graph", "graphs", "picture", "visual", "visualisation", "visualization",
                    "plot"})
_AGAIN = frozenset({"back", "again", "previous", "last", "earlier"})
_CLOSE = frozenset({"close", "hide", "exit", "dismiss", "remove", "leave"})
_NAV_VOCAB = _FILLER | _DESK | _SCREEN | _MAIN | _CHART | _AGAIN | _CLOSE

# commands about the app itself (never a task done for the officer); closed vocabulary again
_APP_ACTIONS = frozenset({"repeat", "say", "scroll", "zoom", "refresh", "reload", "download", "export", "print", "save",
                          "copy", "expand", "collapse", "maximise", "maximize", "minimise", "minimize", "fullscreen",
                          "louder", "softer", "slower", "faster", "mute", "unmute", "pause", "resume", "stop"})
_APP_WORDS = frozenset("""say said again that this it the answer table chart graph list as in out down up full screen
bigger smaller larger an excel csv pdf image png file talking speaking speak read aloud loud little bit more less
voice volume please you can could me""".split())


def _words(text: str) -> list[str]:
    low = (text or "").lower().replace("’", "").replace("'", "")
    return "".join(ch if ("a" <= ch <= "z") else " " for ch in low).split()


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text or "")


def nav_command(text: str) -> "str | None":
    """'desk' / 'chart' when the whole message is a navigation command, else None."""
    if not text or _has_digit(text) or len(text) > 120:
        return None
    ws = _words(text)
    if not ws or len(ws) > 14 or any(w not in _NAV_VOCAB for w in ws):
        return None
    s = set(ws)
    if s & _CLOSE:
        return "desk" if (s & _CHART or s & _DESK) else None
    if s & _CHART:
        return "chart" if s & _AGAIN else None
    if s & _DESK:
        return "desk"
    if s & _MAIN and s & _SCREEN:
        return "desk"
    if "back" in s and not (s & _SCREEN) and s <= (_FILLER | {"back"}):
        return "desk"                                   # "go back", "take me back"
    return None


def is_app_command(text: str) -> bool:
    """A command to the screen or the app: navigation, or every word in the app vocabulary with an action word."""
    if nav_command(text):
        return True
    if not text or _has_digit(text) or len(text) > 120:
        return False
    ws = _words(text)
    if not ws or len(ws) > 12:
        return False
    vocab = _APP_ACTIONS | _APP_WORDS | _NAV_VOCAB
    return all(w in vocab for w in ws) and bool(set(ws) & _APP_ACTIONS)


# What the chat says to a navigation command typed (or spoken) into the chat itself: the chat page has no separate
# dashboard (the voice stage acts on these itself and never asks the chat).
NAV_REPLY = {
    "desk": "You're already on the main screen. Ask me about any scheme whenever you're ready — or, on the voice "
            "screen, say \"back to the dashboard\" and I'll bring the desk back.",
    "chart": "The chart stays with its answer above — scroll up to see it, or ask me to show it as a bar, line or "
             "pie chart.",
}

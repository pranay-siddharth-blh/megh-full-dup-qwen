"""The Megh engine's fixed lines (10 Nov 2026): what it says by itself while the pipeline works, and its small talk.
The fact voice synthesises all of them at start-up (sidevoice.warm_texts), so each starts at once."""

LEAD_FIRST = ["One moment, sir.", "Let me pull that up, sir.", "Sure, give me a second.", "Let me check that for you, sir."]
LEAD_LATER = ["Still working on it, sir.", "Almost there, sir.", "Just a little longer, sir."]
GREET = "Hello, sir. What would you like to look at?"
HEAR = "Yes, sir, I can hear you. What would you like to look at?"
THANKS = "You're welcome, sir."
BYE = "Goodbye, sir."
ENGLISH_ONLY = "Sorry, I can only speak English."


def warm() -> list[str]:
    return LEAD_FIRST + LEAD_LATER + [GREET, HEAR, THANKS, BYE, ENGLISH_ONLY]

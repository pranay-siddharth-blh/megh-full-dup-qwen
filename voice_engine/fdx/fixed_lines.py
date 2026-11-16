"""Mitra's FIXED lines that carry no facts: one place, shared by the dispatcher (which picks them), the relay (which sends
them to the fact voice, where they are already synthesised) and the fact voice (which warms its cache with them at
start-up). Kept dependency-free so the fact voice can import it without the Mitra copy."""
from __future__ import annotations

# the clarifying question for a citizen's contentless opening (dispatch.clarify_line picks by the first match)
CLARIFY = {
    "officer": "I'm sorry to hear that. Which officer is it, and what is the complaint about?",
    "application": "Of course. Which application is it, and what has happened with it?",
    "village": "What is wrong in your village? Tell me in a sentence or two.",
    "other": "I'm sorry to hear that. What is the problem, and where is it?",
}


# the screen greetings and the answer to "Hey Mitra" alone (dispatch.greeting / wake_line); the officer's carry his name
GREET = {
    "cs": "Hello, Chief Secretary Madam. I can give you the position across the state, what is overdue, any case or officer. What would you like to see?",
    "citizen": "Namaskara, I'm Mitra. Tell me what's wrong in your village and I'll take it to the right officer.",
}
WAKE = {
    "cs": "Hello, Chief Secretary Madam. I'm here. What would you like to see across the state today?",
    "citizen": "Namaskara, I'm Mitra. I'm here. Tell me what's wrong, and I'll take it to the right officer.",
}


def cached_on_fact_voice() -> set[str]:
    """Lines the fact voice synthesises at start-up, so they start in ~0.06 s (a forced line on the duplex core takes
    ~0.2-0.26 s; an uncached line on the fact voice ~0.9-1.2 s): the clarifying questions, the greetings, the wake
    answers (the lead phrases, the stop acknowledgement and the listen offer come from fdx.settings)."""
    return set(CLARIFY.values()) | set(GREET.values()) | set(WAKE.values())

"""Full-duplex voice for the chat (2026-11-02).

Ears and voice only. The answer to every spoken question is produced by the
unchanged chat pipeline, through the same POST /api/query/stream a typed
question takes: the chat page runs it and hands the checked answer back to be
spoken. Nothing in app/pipeline, app/routers/query.py or app/config.py is used
or changed by this package except reading the officer's user row to check the
login.

  relay.py         /ws/voice: the browser <-> Gemini Live relay
  prompt.py        the voice's instruction and its one function, ask_megh
  speech_guard.py  numbers said aloud vs the answer; engine names kept off the voice
  settings.py      its own keys (certs/voice.env or the process environment, never .env)
"""

"""Dictation (D-111, 15 Nov 2026): the composer mic types the officer's words.

    page --hello{token, lang}, PCM16 16 kHz frames, stop / cancel--> /ws/dictate
         <--ready, partial{seq, stable, tentative}, final{text, corrections}, no_speech, error, closed--

Modules: router (the socket and its limits), session (segments -> text),
segmenter (pause / length cut points on the frames' energy), ears (the speech
engines: qwen3-asr BatchEar; the Kyutai StreamEar seam), clean (guards, fillers,
the mishearing table data/dictation_hearing.yaml, spoken numbers, scheme /
district / block spelling), numbers, words (the text pieces both read).
Sovereign: only our own self-hosted models hear the audio. No regex (D-046).
"""

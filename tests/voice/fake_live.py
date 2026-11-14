"""A local stand-in for Gemini Live (the same wire protocol: setup / clientContent / realtimeInput / toolCall /
toolResponse / toolCallCancellation / serverContent with audio, transcripts, interrupted, turnComplete), so the voice
relay and the chat page can be built and tested offline without spending credits. Ported from Mitra's
(D:/Sakala POC/mitra/tests/fake_live.py).

Its "model": every question goes to ask_megh with the words as heard; after the toolResponse it reads `speak` (as an
output transcript plus quiet 24 kHz PCM). Text that starts with "[voice] " is treated as speech (an inputTranscription is
sent first). New input while it speaks interrupts it, as does loud microphone audio.

Directives (imitate the real model's bad days):
  !!silent <q>     calls nothing, says "Okay."                     (the page must run the question itself)
  !!nothing <q>    hears it and then sends nothing at all          (the page's silent-model guard must answer it)
  !!memory <q>     calls nothing, says a number of its own          (a deviation; the page must correct it)
  !!repeat N <q>   calls ask_megh N times in one turn               (the relay must answer the repeats from the first)
  !!quiet <q>      calls, then says nothing until nudged            (the relay must nudge it)
  !!cancel <q>     calls, then cancels the call after 0.6 s         (the page must stop that answer)
  !!lag <q>        the transcript stops after two words, the call carries the whole question (the page must use the call)
  !!wrong <q>      calls, then says the answer with a number changed      (the page must have the checked answer re-read)
  !!reword N <q>   calls ask_megh N times in one turn, each time worded differently (the relay must make it one question)
  !!again <q>      answers, then calls ask_megh again on its own after reading (the relay must hold the second answer)
  !!echo <q>       answers, then reads the same answer again on its own, no call (the relay must not forward it)
  !!reread <q>     on this new question it first reads its PREVIOUS answer again, then calls ask_megh for <q> in the
                   same turn and reads the new answer (the relay must forward only the new answer; real voice 2026-11-03)

Run: python tests/voice/fake_live.py [port] [--fail]      (default 8499)
"""
import asyncio
import base64
import json
import math
import sys

import websockets

PORT = int(next((a for a in sys.argv[1:] if a.isdigit()), "8499"))
FAIL = "--fail" in sys.argv
GREETINGS = ("hello", "hi", "hey", "thanks", "thank you", "can you hear me", "good morning", "good afternoon")
READ_PREFIX = "(Read this to the officer now"
NUDGE_PREFIX = "(The answer has arrived"
NOT_ENGLISH_PREFIX = "(You spoke a language other than English"


def pcm(seconds: float) -> bytes:
    n = int(24000 * seconds)
    return b"".join(int(700 * math.sin(i / 11)).to_bytes(2, "little", signed=True) for i in range(n))


async def handler(ws):
    raw = json.loads(await ws.recv())
    if FAIL:
        await ws.close(1011, "RESOURCE_EXHAUSTED: quota")
        return
    fns = {d["name"] for d in raw["setup"]["tools"][0]["functionDeclarations"]}
    await ws.send(json.dumps({"setupComplete": {}}))
    st = {"speaking": None, "tool": None, "last_speak": "", "n": 0}

    async def send(obj):
        await ws.send(json.dumps(obj))

    async def speak(text: str, end: bool = True):
        try:
            words = text.split()
            for i in range(0, len(words), 4):        # ~10 words a second: slower than this, tests drag; faster, nothing is "as it speaks"
                await send({"serverContent": {"outputTranscription": {"text": " ".join(words[i:i + 4]) + " "}}})
                await send({"serverContent": {"modelTurn": {"parts": [{"inlineData": {
                    "mimeType": "audio/pcm;rate=24000", "data": base64.b64encode(pcm(0.3)).decode()}}]}}})
                await asyncio.sleep(0.38)
            if end:
                await send({"serverContent": {"turnComplete": True}})
        except asyncio.CancelledError:
            pass

    def say(text: str):
        st["speaking"] = asyncio.create_task(speak(text))

    async def interrupt():
        if st["speaking"] and not st["speaking"].done():
            st["speaking"].cancel()
            await send({"serverContent": {"interrupted": True}})

    async def call(question: str, times: int = 1, reword: bool = False) -> dict:
        resp = None
        forms = [question, f"tell me {question}", f"{question} please", f"what about {question}", f"{question} now"]
        for k in range(times):
            if reword:
                question = forms[k % len(forms)]
            st["n"] += 1
            fut = asyncio.get_running_loop().create_future()
            st["tool"] = fut
            await send({"toolCall": {"functionCalls": [{"id": f"fc{st['n']}", "name": "ask_megh",
                                                        "args": {"question": question}}]}})
            if k == 0:
                await send({"serverContent": {"turnComplete": True}})     # like Gemini: the tool-call turn ends first
            r = await asyncio.wait_for(fut, 130)
            resp = r["functionResponses"][0]["response"]
        return resp or {}

    async def user_turn(text: str, spoken: bool):
        await interrupt()
        if text.startswith(READ_PREFIX):
            say(text.split(") ", 1)[-1].strip())
            return
        if text.startswith(NOT_ENGLISH_PREFIX):
            say("Sorry, I can only speak English.")
            return
        if text.startswith("!!hindi "):              # answers in Hindi (the relay must drop it and get English)
            say("मनरेगा में बहुत काम हुआ है")
            return
        if text.startswith(NUDGE_PREFIX):
            say(st["last_speak"] or "Here it is.")
            return
        if spoken:                                   # what was "heard": the words without any test directive
            heard = text
            for d in ("!!silent ", "!!memory ", "!!quiet ", "!!cancel ", "!!lag ", "!!wrong ", "!!nothing ", "!!again ", "!!echo ", "!!reread "):
                if heard.startswith(d):
                    heard = heard[len(d):]
            for d in ("!!repeat ", "!!reword "):
                if heard.startswith(d):
                    heard = heard[len(d):].split(" ", 1)[-1]
            if text.startswith("!!lag "):
                heard = " ".join(heard.split()[:2])
            await send({"serverContent": {"inputTranscription": {"text": heard}}})
        low = text.lower().strip(" .?!")
        if text.startswith("!!nothing "):
            return                                   # no call, no word, no turn end
        if text.startswith("!!silent "):
            say("Okay.")
            return
        if text.startswith("!!memory "):
            say("There were 12,345 person-days in that district.")
            return
        if low in GREETINGS:
            say("Hello. Ask me anything about the scheme data.")
            return
        if low in ("repeat that", "say that again", "can you repeat that") and st["last_speak"]:
            say(st["last_speak"])                    # asked to repeat: the last answer again, no call
            return
        if "ask_megh" not in fns:
            say("I cannot answer that.")
            return
        times, quiet, cancel, question, reword, again = 1, False, False, text, False, False
        if text.startswith("!!repeat ") or text.startswith("!!reword "):
            reword = text.startswith("!!reword ")
            rest = text[len("!!repeat "):]
            n, question = rest.split(" ", 1)
            times = int(n)
        elif text.startswith("!!again "):
            again, question = True, text[len("!!again "):]
        if text.startswith("!!reread "):
            question = text[len("!!reread "):]
            if st["last_speak"]:                     # the previous answer again, no turn end, before the call
                await speak(st["last_speak"], end=False)
        echo = text.startswith("!!echo ")
        if echo:
            question = text[len("!!echo "):]
        elif text.startswith("!!quiet "):
            quiet, question = True, text[len("!!quiet "):]
        elif text.startswith("!!cancel "):
            cancel, question = True, text[len("!!cancel "):]
        elif text.startswith("!!lag "):
            question = text[len("!!lag "):]
        wrong = text.startswith("!!wrong ")
        if wrong:
            question = text[len("!!wrong "):]
        if cancel:
            st["n"] += 1
            cid = f"fc{st['n']}"
            await send({"toolCall": {"functionCalls": [{"id": cid, "name": "ask_megh", "args": {"question": question}}]}})
            await send({"serverContent": {"turnComplete": True}})
            await asyncio.sleep(0.6)
            await send({"toolCallCancellation": {"ids": [cid]}})
            say("Okay, I stopped that.")
            return
        try:
            r = await call(question, times, reword)
        except asyncio.TimeoutError:
            say("Sorry, that took too long.")
            return
        st["last_speak"] = r.get("speak") or "Done."
        if quiet:
            return                                   # until the relay nudges it
        say("About 99,99,999 of them, roughly." if wrong else st["last_speak"])
        if echo:                                     # after reading, it says the same answer again, unprompted
            try:
                await st["speaking"]
            except asyncio.CancelledError:
                return
            say(st["last_speak"])
        if again:                                    # after reading, it asks the same thing once more on its own
            try:
                await st["speaking"]
            except asyncio.CancelledError:
                return
            r2 = await call(f"so {question}")
            if r2.get("speak"):
                say(r2["speak"])

    async for raw_msg in ws:
        msg = json.loads(raw_msg)
        if "toolResponse" in msg:
            if st["tool"] and not st["tool"].done():
                st["tool"].set_result(msg["toolResponse"])
        elif "clientContent" in msg:
            text = "".join(p.get("text", "") for t in msg["clientContent"]["turns"] for p in t["parts"])
            spoken = text.startswith("[voice] ")
            asyncio.create_task(user_turn(text[8:] if spoken else text, spoken))
        elif "realtimeInput" in msg:
            a = msg["realtimeInput"].get("audio")
            if a and st["speaking"] and not st["speaking"].done():
                b = base64.b64decode(a["data"])
                loud = max((abs(int.from_bytes(b[i:i + 2], "little", signed=True)) for i in range(0, len(b) - 1, 64)),
                           default=0)
                if loud > 4000:                      # someone talks over it: barge-in
                    await interrupt()


async def main():
    async with websockets.serve(handler, "127.0.0.1", PORT, max_size=None):
        print(f"fake Live on ws://127.0.0.1:{PORT}{' (failing)' if FAIL else ''}", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())

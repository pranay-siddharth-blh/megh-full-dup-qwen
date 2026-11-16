# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────────────────────
# MEGH-FULL-DUP-QWEN — the sovereign voice image. ONE image, TWO services (docker-compose.megh-full-dup-qwen.yml):
#   engine    python megh/adapter.py 8170     speaks the Gemini-Live message subset the app's relay uses;
#                                              ears = Kyutai STT 1B (timing) + qwen3-asr (words), shaper, brain =
#                                              the app's own pipeline (ask_megh), mouth = the voice service
#   voicesvc  python sidevoice/server.py 8144  the voice: qwen3-tts, cloned from voices/designed_a.wav (voice A)
# Every model is on the team's GPU gateway (FDX_* settings, deploy/megh-full-dup-qwen/voice.env).
#
# Build context = the repository root (it also copies data/: the engine reads the place names from
# data/*/*_entity_resolver.yaml).
#   docker compose -f docker-compose.megh-full-dup-qwen.yml build
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

LABEL org.opencontainers.image.title="megh-full-dup-qwen-voice" \
      org.opencontainers.image.description="Megh One AI sovereign full-duplex voice: engine + qwen3-tts voice service"

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

COPY voice_engine/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt \
    && useradd --create-home --uid 10002 meghvoice

WORKDIR /opt/megh-full-dup-qwen-voice
COPY voice_engine/ ./
COPY data/ ./megh-data/

# Listen on the compose network (the code's default is 127.0.0.1); the place names and the 8-scheme pack are in
# the image. Ports are internal to the compose network: nothing is published on the host.
ENV PYTHONPATH=/opt/megh-full-dup-qwen-voice \
    FDX_BIND_HOST=0.0.0.0 \
    MEGH_DATA_DIR=/opt/megh-full-dup-qwen-voice/megh-data \
    MEGH_DOMAIN_PACK=/opt/megh-full-dup-qwen-voice/megh/domain/megh_pack.json \
    FDX_TTS_ENGINE=qwen \
    FDX_TTS_REF=/opt/megh-full-dup-qwen-voice/voices/designed_a.wav \
    FDX_TTS_CLONE=full

RUN rm -f requirements.txt Dockerfile && chown -R meghvoice:meghvoice /opt/megh-full-dup-qwen-voice
USER meghvoice
EXPOSE 8170 8144

# The engine by default; the voice service overrides the command (compose).
CMD ["python", "megh/adapter.py", "8170"]

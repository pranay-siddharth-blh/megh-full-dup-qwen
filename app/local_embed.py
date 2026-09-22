"""
Local CPU embeddings via fastembed (ONNX). Used when EMBEDDING_PROVIDER=local,
i.e. whenever the model gateway has no embedding deployment of its own.

Runs on the calling (event-loop) thread ON PURPOSE. onnxruntime's Run() dead-
locks on Windows when the InferenceSession is driven from a ThreadPoolExecutor
worker for some input batches (observed hang inside onnxruntime_inference_
collection.run). We embed synchronously and yield the loop between sub-batches
so health checks and other requests still get serviced during a bulk ingest.

Sub-batch size adapts to how long each batch actually takes (see
`_MAX_BLOCK_SECONDS`) rather than assuming a fixed per-batch cost: on slower or
more contended CPUs a batch of `_YIELD_EVERY` texts can take far longer than
"well under a second," which would otherwise stall every other request (health
checks included) for the batch's full duration. Starts at the smallest batch
size and grows toward the ceiling only once batches prove fast — starting at
the ceiling and shrinking down would let the very first (unproven) batch pay
the full worst-case block before any adaptation could happen. The learned
size is kept in a module-level variable so a slow environment stays fast-
failing across separate `embed()` calls, not just within one.

The first call downloads the ONNX weights (~130 MB for bge-small-en-v1.5) to the
HuggingFace cache; every later call is offline.
"""
import asyncio
import logging
import time

from app.config import settings

logger = logging.getLogger(__name__)

_model = None
_lock = asyncio.Lock()

# Ceiling sub-batch size on fast hardware, and the size a fresh process starts
# at. Grows toward _YIELD_EVERY when batches are comfortably fast, shrinks
# toward _MIN_YIELD_BATCH when a batch blocks the loop too long. Persisted at
# module scope (not reset per `embed()` call) so once the running environment
# is known to be slow, later calls start from that learned size instead of
# re-probing the ceiling — and re-paying its worst-case block — every time.
_YIELD_EVERY = 16
_MIN_YIELD_BATCH = 1
_MAX_BLOCK_SECONDS = 1.0
_batch_size = _MIN_YIELD_BATCH

# Known output dimensions — lets kb_ingest size the pgvector table if needed.
_DIMS = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
}


def _load_sync():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=settings.LOCAL_EMBEDDING_MODEL)


def _embed_sync(texts: list[str]) -> list[list[float]]:
    # parallel=1: don't let fastembed spawn its own worker pool underneath us.
    return [v.tolist() for v in _model.embed(texts, parallel=1)]


async def _ensure_model() -> None:
    global _model
    if _model is not None:
        return
    async with _lock:
        if _model is None:
            name = settings.LOCAL_EMBEDDING_MODEL
            logger.info("local_embed: loading %s (first run downloads the model)", name)
            _model = _load_sync()
            logger.info("local_embed: %s ready", name)


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch, returning one vector (plain list[float]) per input, in order."""
    global _batch_size
    if not texts:
        return []
    await _ensure_model()
    texts = list(texts)
    if len(texts) <= _MIN_YIELD_BATCH:
        return _embed_sync(texts)

    out: list[list[float]] = []
    i = 0
    while i < len(texts):
        sub = texts[i : i + _batch_size]
        t0 = time.monotonic()
        out.extend(_embed_sync(sub))
        elapsed = time.monotonic() - t0
        i += len(sub)
        await asyncio.sleep(0)  # let the loop breathe between sub-batches

        # Adapt sub-batch size to the CPU actually under us: shrink it if a
        # batch just blocked the loop too long, grow it back toward the
        # ceiling once batches are comfortably fast.
        if elapsed > _MAX_BLOCK_SECONDS and _batch_size > _MIN_YIELD_BATCH:
            _batch_size = max(_MIN_YIELD_BATCH, _batch_size // 2)
        elif elapsed < _MAX_BLOCK_SECONDS / 4 and _batch_size < _YIELD_EVERY:
            _batch_size = min(_YIELD_EVERY, _batch_size * 2)
    return out


def dim() -> int:
    return _DIMS.get(settings.LOCAL_EMBEDDING_MODEL, 384)

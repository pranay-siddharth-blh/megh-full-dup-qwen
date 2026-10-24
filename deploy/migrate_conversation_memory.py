"""Copy conversation memory into a collection of the current embedding size (D-067).

After EMBEDDING_PROVIDER moves to the gateway's qwen3-embedding (1024-dim), chat
recall starts empty: the turns are in the 384-dim `megh_conversation_memory`, and a
1024-dim question cannot search it. This re-embeds every turn still inside
CONTEXT_MEMORY_RETENTION_DAYS, with the configured model and the same text the app
embeds (`standalone_question or question`), into CONTEXT_MEMORY_COLLECTION.

- The source is only read, never changed (it stays the rollback).
- Points keep their ids and payloads, so a second run overwrites, never duplicates.
- Refuses when source == target, or when the target exists at another size.

Run from the repo root (so .env loads), AFTER the app restarts on the new settings:
the old collection then gets no new turns, so nothing is missed.

    .venv/Scripts/python.exe deploy/migrate_conversation_memory.py --dry-run
    .venv/Scripts/python.exe deploy/migrate_conversation_memory.py --source megh_conversation_memory
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qdrant_client import models  # noqa: E402

from app import conversation_memory, llm, vectorstore  # noqa: E402
from app.config import settings  # noqa: E402


async def main(source: str, target: str, dry_run: bool) -> int:
    if source == target:
        print(f"source and target are both {source}: nothing to do")
        return 1
    await llm.init_client()
    await vectorstore.init_qdrant()
    client = vectorstore.get_client()
    try:
        if not await client.collection_exists(source):
            print(f"source {source} does not exist")
            return 1
        dim = len((await llm.call_embedding(["dimension check"]))[0])
        have = await vectorstore.collection_dim(target)
        if have is not None and have != dim:
            print(f"target {target} holds {have}-dim vectors but the model returns {dim}: refusing")
            return 1

        days = settings.CONTEXT_MEMORY_RETENTION_DAYS
        floor = time.time() - days * 86400 if days and days > 0 else 0.0
        flt = (models.Filter(must=[models.FieldCondition(key="ts", range=models.Range(gte=floor))])
               if floor else None)
        points, offset = [], None
        while True:
            page, offset = await client.scroll(source, scroll_filter=flt, limit=512, offset=offset,
                                               with_payload=True, with_vectors=False)
            points.extend(page)
            if offset is None:
                break
        print(f"{len(points)} turns in {source} inside {days} days -> {target} ({dim}-dim, "
              f"{settings.EMBEDDING_PROVIDER} {settings.EMBEDDING_MODEL})")
        if dry_run or not points:
            return 0

        if have is None:
            await client.create_collection(
                collection_name=target,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
        await conversation_memory.create_payload_indexes(client, target)
        batch, done = settings.EMBED_BATCH_SIZE, 0
        for i in range(0, len(points), batch):
            chunk = points[i : i + batch]
            texts = [(p.payload or {}).get("standalone_question") or (p.payload or {}).get("question")
                     or " " for p in chunk]
            vecs = await llm.call_embedding(texts)
            await client.upsert(target, wait=True, points=[
                models.PointStruct(id=p.id, vector=v, payload=p.payload) for p, v in zip(chunk, vecs)])
            done += len(chunk)
            if done % 1024 < batch or done == len(points):
                print(f"  {done}/{len(points)}")
        info = await client.get_collection(target)
        print(f"done: {target} now holds {info.points_count} points")
        return 0
    finally:
        await vectorstore.close_qdrant()
        await llm.close_client()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", default="megh_conversation_memory")
    ap.add_argument("--target", default=settings.CONTEXT_MEMORY_COLLECTION)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.source, a.target, a.dry_run)))

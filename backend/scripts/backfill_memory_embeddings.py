"""Backfill semantic embeddings for existing memories.

This script finds memories whose ``embedding`` is NULL and computes them using
the shared embedding service, then persists the vectors back to PostgreSQL.

Design notes:
- Idempotent: rows that already have an embedding are skipped.
- Resumable: safe to run repeatedly; it only touches NULL-embedding rows.
- Resilient: a single failed row is logged and skipped; the script continues
  and reports per-row failures instead of exiting silently.
- Non-destructive: no memory row is ever deleted or modified beyond its
  ``embedding`` column.

Usage:
    cd backend
    python scripts/backfill_memory_embeddings.py
"""
from __future__ import annotations

import asyncio
import sys

from app.database.session import AsyncSessionLocal
from app.infrastructure.embedding import embed_text
from app.observability import logger
from app.repositories.memory_repository import MemoryRepository


BATCH_SIZE = 200


async def run() -> int:
    total = 0
    failed = 0
    while True:
        async with AsyncSessionLocal() as session:
            repo = MemoryRepository(session)
            batch = await repo.find_null_embeddings(limit=BATCH_SIZE)
            if not batch:
                break
            for memory in batch:
                try:
                    vec = embed_text(memory.content)
                    await repo.update_embedding(memory_id=memory.id, embedding=vec)
                    total += 1
                    logger.info("memory_embedding_backfilled", memory_id=memory.id)
                except Exception as exc:  # noqa: BLE001 - keep going on single failures
                    failed += 1
                    logger.error(
                        "memory_embedding_backfill_failed",
                        memory_id=memory.id,
                        error=str(exc),
                    )
        # Inner session is closed; loop continues until no NULL rows remain.
    logger.info(
        "memory_backfill_done",
        processed=total,
        failed=failed,
    )
    print(f"[backfill] processed={total} failed={failed}")
    return failed


def main() -> int:
    failed = asyncio.run(run())
    # Exit 0 even if some rows failed, so orchestration is not blocked; the
    # failed rows remain NULL and can be retried on the next run.
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

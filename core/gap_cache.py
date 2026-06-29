"""Redis-backed gap report cache for PaperMind."""

import hashlib
import json
import logging
import os
from typing import Optional

from core import kuzu_client

logger = logging.getLogger("papermind.gap_cache")

CACHE_PREFIX = "papermind:gaps:v1"
CACHE_TTL_SECONDS = int(os.environ.get("PAPERMIND_GAP_CACHE_TTL_SECONDS", "86400"))
CACHE_ENABLED = os.environ.get("PAPERMIND_GAP_CACHE_ENABLED", "true").lower() not in {"0", "false", "no"}

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover - import availability depends on env
    redis = None

_client = None


def build_corpus_fingerprint(user_id: str) -> str:
    """Hash the current uploaded paper ids for this user."""
    try:
        paper_ids = sorted(kuzu_client.get_paper_ids_for_user(user_id))
    except Exception as exc:
        logger.warning("Failed to compute gap cache fingerprint for %s: %s", user_id, exc)
        paper_ids = []

    payload = json.dumps(paper_ids, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def build_gap_cache_key(user_id: str, corpus_fingerprint: str) -> str:
    return f"{CACHE_PREFIX}:{user_id}:{corpus_fingerprint}"


async def _get_client():
    global _client
    if not CACHE_ENABLED or redis is None:
        return None
    if _client is None:
        _client = redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1.5,
            socket_timeout=1.5,
            retry_on_timeout=False,
        )
    return _client


async def get_cached_gap_report(user_id: str, corpus_fingerprint: str) -> Optional[dict]:
    client = await _get_client()
    if client is None:
        return None

    key = build_gap_cache_key(user_id, corpus_fingerprint)
    try:
        cached = await client.get(key)
        if not cached:
            return None
        payload = json.loads(cached)
        if isinstance(payload, dict):
            logger.info("Gap cache hit for %s (%s)", user_id, corpus_fingerprint)
            return payload
    except Exception as exc:
        logger.warning("Gap cache read failed for %s: %s", user_id, exc)
    return None


async def set_cached_gap_report(user_id: str, corpus_fingerprint: str, report: dict) -> None:
    client = await _get_client()
    if client is None:
        return

    key = build_gap_cache_key(user_id, corpus_fingerprint)
    try:
        await client.setex(key, CACHE_TTL_SECONDS, json.dumps(report, ensure_ascii=False))
        logger.info("Gap cache stored for %s (%s)", user_id, corpus_fingerprint)
    except Exception as exc:
        logger.warning("Gap cache write failed for %s: %s", user_id, exc)


async def invalidate_gap_cache(user_id: str) -> None:
    client = await _get_client()
    if client is None:
        return

    pattern = f"{CACHE_PREFIX}:{user_id}:*"
    try:
        async for key in client.scan_iter(match=pattern):
            await client.delete(key)
        logger.info("Gap cache invalidated for %s", user_id)
    except Exception as exc:
        logger.warning("Gap cache invalidation failed for %s: %s", user_id, exc)

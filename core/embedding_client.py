"""HTTP client for the dedicated embedding service, with local fallback."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Iterable

import httpx
import numpy as np

from core.embeddings import encode_texts_local_async


logger = logging.getLogger("papermind.embeddings")

EMBEDDING_SERVICE_URL = os.environ.get("PAPERMIND_EMBEDDING_URL", "http://127.0.0.1:8001")
EMBEDDING_TIMEOUT_SECONDS = float(os.environ.get("PAPERMIND_EMBEDDING_TIMEOUT_SECONDS", "90"))


async def embed_texts(texts: Iterable[str]) -> np.ndarray:
    """Return embeddings from the remote service or the local fallback."""
    cleaned = [str(text or "").strip() for text in texts]
    if not cleaned:
        return np.zeros((0, 0), dtype=np.float32)

    try:
        async with httpx.AsyncClient(base_url=EMBEDDING_SERVICE_URL, timeout=EMBEDDING_TIMEOUT_SECONDS) as client:
            response = await client.post("/embed", json={"texts": cleaned})
            response.raise_for_status()
            payload = response.json()
            embeddings = np.asarray(payload["embeddings"], dtype=np.float32)
            return embeddings
    except Exception as exc:
        logger.warning("Embedding service unavailable, using local model fallback: %s", exc)
        return await encode_texts_local_async(cleaned)

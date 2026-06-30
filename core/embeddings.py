"""Shared embedding helpers for PaperMind."""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np


EMBEDDING_MODEL = os.environ.get("PAPERMIND_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_CACHE_DIR = os.environ.get("SENTENCE_TRANSFORMERS_HOME") or os.environ.get(
    "HF_HOME",
    "./hf_cache",
)


def _normalise_texts(texts: Iterable[str]) -> list[str]:
    return [str(text or "").strip() for text in texts]


@lru_cache(maxsize=1)
def load_local_embedding_model():
    """Load SentenceTransformer once per process."""
    from sentence_transformers import SentenceTransformer

    cache_dir = Path(EMBEDDING_CACHE_DIR).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    return SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(cache_dir))


def encode_texts_local(texts: Iterable[str]) -> np.ndarray:
    """Encode texts with the local SentenceTransformer model."""
    cleaned = _normalise_texts(texts)
    if not cleaned:
        return np.zeros((0, 0), dtype=np.float32)

    model = load_local_embedding_model()
    embeddings = model.encode(cleaned, convert_to_numpy=True, normalize_embeddings=False)
    return np.asarray(embeddings, dtype=np.float32)


async def encode_texts_local_async(texts: Iterable[str]) -> np.ndarray:
    """Async wrapper around the local embedding model."""
    return await asyncio.to_thread(encode_texts_local, list(texts))

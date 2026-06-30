"""Dedicated embedding server that keeps the HF model warm in memory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.embeddings import EMBEDDING_MODEL, encode_texts_local_async, load_local_embedding_model


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("papermind.embedding_service")


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class EmbedResponse(BaseModel):
    model: str
    dimension: int
    count: int
    embeddings: list[list[float]]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting embedding service with model %s", EMBEDDING_MODEL)
    try:
        model = await asyncio.to_thread(load_local_embedding_model)
        await asyncio.to_thread(model.encode, ["warmup"])
        app.state.ready = True
        logger.info("Embedding model loaded and warmed up")
    except Exception as exc:
        app.state.ready = False
        logger.exception("Embedding model warmup failed: %s", exc)
    yield
    logger.info("Embedding service shutting down")


app = FastAPI(title="PaperMind Embedding Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "healthy" if getattr(app.state, "ready", False) else "starting",
        "model": EMBEDDING_MODEL,
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest):
    if not request.texts:
        raise HTTPException(status_code=400, detail="texts must not be empty")

    embeddings = await encode_texts_local_async(request.texts)
    if embeddings.size == 0:
        raise HTTPException(status_code=500, detail="embedding model returned no vectors")

    return {
        "model": EMBEDDING_MODEL,
        "dimension": int(embeddings.shape[1]),
        "count": int(embeddings.shape[0]),
        "embeddings": embeddings.tolist(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("embedding_service:app", host="0.0.0.0", port=8001, log_level="info")

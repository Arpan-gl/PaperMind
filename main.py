"""
PaperMind — FastAPI Application Entry Point
Source: docs/architecture.md

Living research knowledge graph powered by:
    - Qwen3:32B via OpenRouter (LLM)
    - Cognee (memory layer)
    - KuzuDB (graph database)
    - Celery + Redis (async tasks)
    - Next.js + Cytoscape.js (frontend)

Run: uvicorn main:app --reload --port 8000
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

# ── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("papermind")


# ── Lifespan (startup/shutdown) ─────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Cognee and KuzuDB on startup."""
    logger.info("PaperMind starting up...")

    # Initialize KuzuDB schema
    try:
        from core.kuzu_client import initialize_schema
        initialize_schema()
        logger.info("✓ KuzuDB schema initialized")
    except Exception as e:
        logger.error(f"✗ KuzuDB initialization failed: {e}")

    # Initialize Cognee
    try:
        from core.cognee_client import setup_cognee
        await setup_cognee()
        logger.info("✓ Cognee initialized")
    except Exception as e:
        logger.warning(f"✗ Cognee initialization failed (will retry on first use): {e}")

    logger.info("PaperMind ready!")
    yield
    logger.info("PaperMind shutting down...")


# ── App ─────────────────────────────────────────────────────────

app = FastAPI(
    title="PaperMind",
    description="Living research knowledge graph extending Agents-K1",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for Next.js frontend
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount API Routers ───────────────────────────────────────────
from api.papers import router as papers_router
from api.query import router as query_router
from api.graph import router as graph_router

app.include_router(papers_router, prefix="/api")
app.include_router(query_router, prefix="/api")
app.include_router(graph_router, prefix="/api")


# ── WebSocket Endpoint ──────────────────────────────────────────
from api.websocket import ws_manager

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    WebSocket connection for real-time updates.
    Source: architecture.md lines 263-294

    Events pushed to clients:
        ingestion_complete   — after Agent 2
        ingestion_status     — during Agent 1 retry
        gap_detection_complete — after Agent 4
    """
    await ws_manager.connect(websocket, user_id)
    try:
        while True:
            # Keep connection alive, listen for client messages
            data = await websocket.receive_text()
            # Client can send ping/pong or commands
            if data == "ping":
                await ws_manager.send_personal(websocket, {"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, user_id)


# ── Health Check ────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "papermind",
        "version": "0.1.0",
    }


@app.get("/")
async def root():
    """Root endpoint with API overview."""
    return {
        "name": "PaperMind",
        "description": "Living research knowledge graph",
        "docs": "/docs",
        "endpoints": {
            "papers": "/api/papers/",
            "ingest": "POST /api/papers/ingest",
            "query": "POST /api/query",
            "graph": "/api/graph",
            "gaps": "/api/graph/gaps",
            "novelty": "POST /api/novelty",
            "websocket": "ws://localhost:8000/ws/{user_id}",
        },
    }

if "__main__" == __name__:
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")
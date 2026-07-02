"""
PaperMind — Query API
Source: docs/loop_flow.md (lines 366-375)

Endpoints:
    POST /query  — Run Agent 3 loop synchronously (fast enough for real-time)
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.agent_loop import agent_loop
from agents.query_agent import agent_3_query_agent

logger = logging.getLogger("papermind.api.query")

router = APIRouter(tags=["query"])

QUERY_MAX_RETRIES = int(os.environ.get("PAPERMIND_QUERY_MAX_RETRIES", "1"))


# ── Models ──────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    question: str


class CitationResponse(BaseModel):
    claim_text: Optional[str] = None
    paper_title: Optional[str] = None
    paper_id: Optional[str] = None
    section: Optional[str] = None
    page: Optional[int] = None
    passage: Optional[str] = None
    confidence: Optional[float] = None
    edge_type: Optional[str] = None


class QueryResponse(BaseModel):
    intent: str
    answer: str
    citations: list[dict]
    graph_path: list[str]
    query_mode: str
    sources_used: dict
    unsourced_claims: list


# ── Dependency ──────────────────────────────────────────────────

async def get_current_user(user_id: str = Query(default="default_user")) -> str:
    return user_id


# ── Endpoints ───────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    user_id: str = Depends(get_current_user),
):
    """
    Answer a researcher question using corpus-scoped retrieval.
    Source: loop_flow.md lines 366-375

    Runs Agent 3 loop synchronously — fast enough for real-time.
    """
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        result = await agent_loop(
            agent_fn=agent_3_query_agent,
            input_data={"question": request.question},
            user_id=user_id,
            max_retries=QUERY_MAX_RETRIES,
        )
    except Exception as e:
        logger.error(f"Query agent failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query processing failed: {e}")

    # Ensure all required fields
    result.setdefault("intent", "FACTUAL")
    result.setdefault("answer", "")
    result.setdefault("citations", [])
    result.setdefault("graph_path", [])
    result.setdefault("query_mode", result.get("intent", "FACTUAL"))
    result.setdefault("sources_used", {"personal_corpus": 0, "graph_traversal": 0, "vector": 0})
    result.setdefault("unsourced_claims", [])

    return QueryResponse(**result)

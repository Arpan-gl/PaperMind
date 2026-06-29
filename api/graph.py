"""
PaperMind - Graph API
Source: docs/loop_flow.md (lines 377-386)

Endpoints:
    GET  /graph       - Full graph nodes + edges for Cytoscape.js
    GET  /graph/gaps  - Trigger Agent 4 on-demand gap detection
    POST /novelty     - Trigger Agent 5 novelty evaluation
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core import kuzu_client
from core.agent_loop import agent_loop
from core.gap_cache import (
    build_corpus_fingerprint,
    get_cached_gap_report,
    set_cached_gap_report,
)
from agents.gap_agent import agent_4_gap_agent
from agents.novelty_judge import agent_5_novelty_judge

logger = logging.getLogger("papermind.api.graph")

router = APIRouter(tags=["graph"])


class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]


class GapResponse(BaseModel):
    corpus_analyzed: int
    gaps: list[dict]
    summary: dict


class NoveltyRequest(BaseModel):
    idea_text: str


class NoveltyResponse(BaseModel):
    scores: dict
    similar_existing_work: list[dict]
    addresses_gap: bool
    gap_id: Optional[str] = None
    recommendation: str
    improvement_suggestions: list[str]
    verdict: str


async def get_current_user(user_id: str = Query(default="default_user")) -> str:
    return user_id


@router.get("/graph", response_model=GraphResponse)
async def get_graph(user_id: str = Depends(get_current_user)):
    """Get full graph data for Cytoscape.js rendering."""
    try:
        graph_data = kuzu_client.get_full_graph(user_id)
        return GraphResponse(**graph_data)
    except Exception as e:
        logger.error(f"Failed to get graph: {e}")
        return GraphResponse(nodes=[], edges=[])


@router.get("/graph/gaps", response_model=GapResponse)
async def get_gaps(user_id: str = Depends(get_current_user)):
    """Return a cached gap report when the user's corpus has not changed."""
    corpus_fingerprint = build_corpus_fingerprint(user_id)

    cached = await get_cached_gap_report(user_id, corpus_fingerprint)
    if cached:
        cached.setdefault("corpus_analyzed", 0)
        cached.setdefault("gaps", [])
        cached.setdefault("summary", {
            "critical_gaps": 0,
            "moderate_gaps": 0,
            "orphan_methods": 0,
            "methodology_gaps": 0,
        })
        return GapResponse(**cached)

    try:
        result = await agent_loop(
            agent_fn=agent_4_gap_agent,
            input_data={"user_id": user_id},
            user_id=user_id,
        )
    except Exception as e:
        logger.error(f"Gap detection failed: {e}")
        raise HTTPException(status_code=500, detail=f"Gap detection failed: {e}")

    result.setdefault("corpus_analyzed", 0)
    result.setdefault("gaps", [])
    result.setdefault("summary", {
        "critical_gaps": 0,
        "moderate_gaps": 0,
        "orphan_methods": 0,
        "methodology_gaps": 0,
    })

    await set_cached_gap_report(user_id, corpus_fingerprint, result)
    return GapResponse(**result)


@router.post("/novelty", response_model=NoveltyResponse)
async def evaluate_novelty(
    request: NoveltyRequest,
    user_id: str = Depends(get_current_user),
):
    """Evaluate a research idea for novelty."""
    if not request.idea_text.strip():
        raise HTTPException(status_code=400, detail="Idea text cannot be empty")

    try:
        result = await agent_loop(
            agent_fn=agent_5_novelty_judge,
            input_data={"idea_text": request.idea_text},
            user_id=user_id,
        )
    except Exception as e:
        logger.error(f"Novelty evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Novelty evaluation failed: {e}")

    result.setdefault("scores", {})
    result.setdefault("similar_existing_work", [])
    result.setdefault("addresses_gap", False)
    result.setdefault("gap_id", None)
    result.setdefault("recommendation", "refine")
    result.setdefault("improvement_suggestions", [])
    result.setdefault("verdict", "")

    return NoveltyResponse(**result)

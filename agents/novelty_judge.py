"""
PaperMind — Agent 5: Novelty Judge
Source: docs/agents.md (lines 532-587)

Trigger:  User submits a research idea
Input:    Idea text + user_id
Output:   Novelty score + recommendation
PASS:     75 / 100

Formula: Novelty(I, G_u) = J_LLM(I | R_k(I, G_u)) × (1 - Overlap(I, G_global \ G_u))

Scores 4 dimensions (each 0-1):
    coherence:   Internal logical consistency
    credibility: Grounded in corpus evidence
    feasibility: Testable with current methods
    novelty:     Meaningfully differs from existing work

Recommendation: pursue | refine | pivot
"""

import json
import logging
from typing import Any, Optional

from core.openrouter_client import qwen_call
from core import cognee_client
from core import kuzu_client

logger = logging.getLogger("papermind.agent5")

# ── System prompt (verbatim from agents.md lines 541-586) ───────
AGENT_5_PROMPT = """You are the Novelty Judge in PaperMind.

Formula: Novelty(I, G_u) = J_LLM(I | R_k(I, G_u)) × (1 - Overlap(I, G_global \\ G_u))

## Memory context:
{memory_context}
Attempt {attempt}. Feedback: {judge_feedback}

## Idea: "{idea_text}"
## Corpus: {paper_count} papers

## Related work from corpus:
{related_work}

## Related claims from KuzuDB:
{related_claims}

## STEP 1 — Retrieve related work
Already provided above from cognee.recall() and KuzuDB.

## STEP 2 — Score 4 dimensions (each 0-1)
  coherence:   Internal logical consistency
  credibility: Grounded in corpus evidence
  feasibility: Testable with current methods
  novelty:     Meaningfully differs from existing work

## STEP 3 — Overlap check
  Overlap = similarity to methods/claims NOT yet in G_u
  Lower overlap → higher novelty

## Output:
{{
  "scores": {{
    "coherence": 0.0,
    "credibility": 0.0,
    "feasibility": 0.0,
    "novelty": 0.0,
    "overall": 0.0
  }},
  "similar_existing_work": [{{
    "paper_title": "",
    "similarity_aspect": "same problem|same method|same dataset",
    "key_difference": ""
  }}],
  "addresses_gap": true,
  "gap_id": "gap_001 or null",
  "recommendation": "pursue|refine|pivot",
  "improvement_suggestions": [""],
  "verdict": "<2-3 sentence summary>"
}}"""


async def agent_5_novelty_judge(
    input_data: dict,
    memory_context: str,
    attempt: int,
    user_id: str,
) -> dict:
    """
    Agent 5: Novelty Judge.

    Called by agent_loop() — never directly.

    Args:
        input_data:     {"idea_text": "..."}
        memory_context: Prior attempts + judge feedback
        attempt:        Current attempt (1-3)
        user_id:        User ID for corpus scoping

    Returns:
        Novelty assessment dict.
    """
    idea_text = input_data.get("idea_text", "")

    # Extract judge feedback
    judge_feedback = _extract_judge_feedback(memory_context)

    # ═══ STEP 1: Retrieve related work ═══════════════════════════

    # Cognee recall — corpus-scoped (from cognee_role.md lines 212-218)
    related_work = await cognee_client.recall(
        query=idea_text,
        user_id=user_id,
        top_k=10,
    )

    # KuzuDB — find related claims
    related_claims = ""
    try:
        keywords = idea_text.lower().split()[:5]
        all_claims = []
        for kw in keywords:
            if len(kw) < 4:
                continue
            claims = kuzu_client.execute(
                "MATCH (c:Claim)<-[:HAS_CLAIM]-(p:Paper) "
                "WHERE c.text CONTAINS $kw "
                "RETURN c.text, p.title, c.rgs_score, c.claim_id LIMIT 5",
                {"kw": kw},
            )
            all_claims.extend(claims)
        related_claims = json.dumps(all_claims[:15])
    except Exception as e:
        logger.warning(f"KuzuDB claim search failed: {e}")

    # Get corpus size
    paper_ids = kuzu_client.get_paper_ids_for_user(user_id)
    paper_count = len(paper_ids)

    # Build prompt
    system_prompt = AGENT_5_PROMPT.format(
        memory_context=memory_context[:2000] if memory_context else "No prior attempts.",
        attempt=attempt,
        judge_feedback=judge_feedback if judge_feedback else "None (first attempt).",
        idea_text=idea_text,
        paper_count=paper_count,
        related_work=related_work[:3000] if related_work else "No related work found.",
        related_claims=related_claims[:3000] if related_claims else "No related claims found.",
    )

    # Call Qwen3:32B
    response = await qwen_call(
        system_prompt=system_prompt,
        user_message=f"Evaluate the novelty of this research idea:\n\n{idea_text}",
        temperature=0.3,
        json_mode=True,
    )

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        result = {
            "scores": {
                "coherence": 0.0,
                "credibility": 0.0,
                "feasibility": 0.0,
                "novelty": 0.0,
                "overall": 0.0,
            },
            "similar_existing_work": [],
            "addresses_gap": False,
            "gap_id": None,
            "recommendation": "refine",
            "improvement_suggestions": ["Could not parse LLM response"],
            "verdict": "Evaluation could not be completed due to parsing error.",
        }

    # Ensure all required fields exist
    result.setdefault("scores", {})
    for dim in ["coherence", "credibility", "feasibility", "novelty", "overall"]:
        result["scores"].setdefault(dim, 0.0)
    result.setdefault("similar_existing_work", [])
    result.setdefault("addresses_gap", False)
    result.setdefault("gap_id", None)
    result.setdefault("recommendation", "refine")
    result.setdefault("improvement_suggestions", [])
    result.setdefault("verdict", "")

    return result


def _extract_judge_feedback(memory_context: str) -> str:
    """Extract most recent judge feedback from memory context."""
    if not memory_context:
        return ""
    try:
        mem = json.loads(memory_context) if isinstance(memory_context, str) else memory_context
        if isinstance(mem, list):
            for item in reversed(mem):
                if isinstance(item, dict) and item.get("verdict"):
                    return item["verdict"].get("feedback_for_agent", "")
        elif isinstance(mem, dict) and mem.get("verdict"):
            return mem["verdict"].get("feedback_for_agent", "")
    except (json.JSONDecodeError, TypeError):
        return str(memory_context)[:500]
    return ""

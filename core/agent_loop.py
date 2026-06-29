"""
PaperMind — Universal Agent Loop
Source: docs/loop_flow.md (verbatim implementation)

Every agent in PaperMind runs inside a self-improving loop:
    1. recall() → load accumulated memory (prior attempts + feedback)
    2. agent_fn() → run the agent with memory context
    3. remember() → store attempt + output + verdict in Cognee
    4. judge.evaluate() → score output against rubric

State machine:
    PASS          → return output immediately
    RETRY         → loop continues (judge feedback stored in Cognee)
    PASS_PARTIAL  → attempt 3 failed, return best scoring attempt

The loop is SELF-IMPROVING, not self-repeating:
    - Attempt 1: empty memory
    - Attempt 2: loads attempt 1 + judge feedback
    - Attempt 3: loads attempts 1+2 + both feedbacks
    The agent reads its own failures via Cognee recall().
"""

import json
import logging
from typing import Any, Callable, Optional
from datetime import datetime

from core import cognee_client
from agents.loop_judge import LoopJudge

logger = logging.getLogger("papermind.agent_loop")


async def agent_loop(
    agent_fn: Callable,
    input_data: dict,
    user_id: str,
    max_retries: int = 3,
    ws_callback: Optional[Callable] = None,
) -> dict:
    """
    Universal self-improving loop for all PaperMind agents.
    All 5 agents (pdf_analyst, graph_builder, query_agent,
    gap_agent, novelty_judge) use this exact function.

    Source: docs/loop_flow.md, lines 16-98

    Args:
        agent_fn:     Async agent function with signature:
                      (input_data, memory_context, attempt, user_id) -> dict
        input_data:   Agent-specific input dict.
        user_id:      User ID for corpus-scoped memory.
        max_retries:  Maximum attempts (default 3 per docs).
        ws_callback:  Optional WebSocket callback for real-time status.

    Returns:
        Agent output dict (PASS or best attempt on PASS_PARTIAL).
    """
    judge = LoopJudge()
    agent_name = agent_fn.__name__
    best_output = None
    best_score = -1

    logger.info(f"Loop started: {agent_name} for user {user_id}")

    for attempt in range(1, max_retries + 1):
        logger.info(f"{agent_name} — attempt {attempt}/{max_retries}")

        # ── Step 1: Load accumulated memory ────────────────────
        # On attempt 1: empty or prior papers
        # On attempt 2: includes attempt 1 output + judge feedback
        # On attempt 3: includes both prior attempts + both feedbacks
        memory_context = await cognee_client.recall(
            query=str(input_data),
            user_id=user_id,
        )

        # ── WebSocket: notify attempt start ────────────────────
        if ws_callback:
            await ws_callback({
                "type": "ingestion_status",
                "status": "processing",
                "agent": agent_name,
                "attempt": attempt,
            })

        # ── Step 2: Run the agent ──────────────────────────────
        try:
            output = await agent_fn(
                input_data=input_data,
                memory_context=memory_context,
                attempt=attempt,
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f"{agent_name} attempt {attempt} crashed: {e}")
            output = {"error": str(e), "agent": agent_name, "attempt": attempt}

        # ── Step 3: Judge evaluates output ─────────────────────
        verdict = await judge.evaluate(
            agent_name=agent_name,
            output=output,
            attempt=attempt,
        )

        # Track best attempt for PASS_PARTIAL fallback
        current_score = verdict.get("score", 0)
        if current_score > best_score:
            best_score = current_score
            best_output = output

        # ── Step 4: Store attempt in Cognee REGARDLESS of result ─
        # This is what makes the loop self-improving
        await cognee_client.remember(
            data={
                "attempt": attempt,
                "output": output,
                "verdict": verdict,
                "agent": agent_name,
                "input_hash": hash(str(input_data)),
                "timestamp": datetime.utcnow().isoformat(),
            },
            metadata={
                "user_id": user_id,
                "type": "agent_attempt",
                "agent": agent_name,
                "status": verdict["status"],
                "score": verdict.get("score", 0),
                "attempt": attempt,
            },
        )

        logger.info(
            f"{agent_name} attempt {attempt}: "
            f"score={verdict.get('score')}, status={verdict['status']}"
        )

        # ── Step 5: Decision ───────────────────────────────────
        if verdict["status"] == "PASS":
            logger.info(f"{agent_name} PASSED on attempt {attempt}")
            return output

        if verdict["status"] == "PASS_PARTIAL":
            logger.warning(
                f"{agent_name} PASS_PARTIAL on attempt {attempt} "
                f"(best score: {best_score})"
            )
            return await get_best_attempt(user_id, agent_name, input_data)

        # Status is RETRY — WebSocket notification
        if ws_callback:
            feedback_preview = verdict.get("feedback_for_agent", "")[:100]
            await ws_callback({
                "type": "ingestion_status",
                "status": "retrying",
                "agent": agent_name,
                "attempt": attempt,
                "reason": feedback_preview,
            })

        # Loop continues — judge feedback is now in Cognee.
        # Next recall() will load it as part of memory_context.
        logger.info(
            f"{agent_name} RETRY (attempt {attempt}): "
            f"{verdict.get('feedback_for_agent', '')[:100]}"
        )

    # Should not reach here (attempt 3 returns PASS_PARTIAL from judge)
    # but safety net
    logger.warning(f"{agent_name} exhausted all retries — returning best attempt")
    return best_output if best_output is not None else {}


async def get_best_attempt(
    user_id: str,
    agent_name: str,
    input_data: dict
) -> dict:
    """
    Retrieve highest-scoring attempt after all retries exhausted.
    Source: docs/loop_flow.md, lines 86-97

    Fetches all stored attempts from Cognee and returns
    the one with the highest judge score.
    """
    try:
        attempts_raw = await cognee_client.recall(
            query=f"{agent_name} attempts {str(input_data)[:100]}",
            user_id=user_id,
            top_k=10,
        )

        if not attempts_raw:
            return {}

        attempts = json.loads(attempts_raw) if isinstance(attempts_raw, str) else attempts_raw

        if not isinstance(attempts, list):
            return {}

        # Filter to this agent's attempts
        relevant = [a for a in attempts if a.get("agent") == agent_name]
        if not relevant:
            return {}

        # Return highest scoring
        best = max(relevant, key=lambda x: x.get("verdict", {}).get("score", 0))
        return best.get("output", best)

    except Exception as e:
        logger.error(f"get_best_attempt failed: {e}")
        return {}

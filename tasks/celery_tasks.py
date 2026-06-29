"""
PaperMind — Celery Tasks
Source: docs/loop_flow.md (lines 308-351)

Tasks:
    ingest_paper_task      — Agent 1 → Agent 2 → WebSocket broadcast
    detect_gaps_all_users  — Nightly 2am UTC, Agent 4 for all active users

Beat schedule:
    detect-gaps-nightly: crontab(hour=2, minute=0)
"""

import os
import logging
import asyncio
from typing import Optional

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("papermind.tasks")

# ── Celery app ──────────────────────────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "papermind",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# ── Beat schedule (from loop_flow.md) ───────────────────────────
celery_app.conf.beat_schedule = {
    "detect-gaps-nightly": {
        "task": "tasks.celery_tasks.detect_gaps_all_users",
        "schedule": crontab(hour=2, minute=0),  # 2am UTC every day
    },
}


def _run_async(coro):
    """Helper to run async code from sync Celery tasks."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in an async context, create a new loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(name="tasks.celery_tasks.ingest_paper_task")
def ingest_paper_task(pdf_path: str, user_id: str, task_id: str = ""):
    """
    Called by FastAPI after paper upload. Runs Agent 1 → Agent 2 loop.
    Source: loop_flow.md lines 324-339

    Flow:
        1. Agent 1 (PDF Analyst) → extract 5-module JSON
        2. Store extraction in Cognee
        3. Agent 2 (Graph Builder) → Δ(G_u, p)
        4. WebSocket: broadcast ingestion_complete
    """
    from tasks.fast_ingestion import run_ingestion_job
    return run_ingestion_job(pdf_path, user_id, task_id)


async def _ingest_paper_async(pdf_path: str, user_id: str, task_id: str = ""):
    """Async implementation of paper ingestion pipeline."""
    from core.agent_loop import agent_loop
    from agents.pdf_analyst import agent_1_pdf_analyst, store_paper_to_cognee
    from agents.graph_builder import agent_2_graph_builder
    from api.websocket import ws_manager
    from api.papers import update_job

    logger.info(f"Ingestion started: {pdf_path} for user {user_id}")
    update_job(task_id, status="analyzing", user_id=user_id)

    # WebSocket callback for real-time updates
    async def ws_callback(message):
        message["paper_id"] = pdf_path.split("/")[-1] if "/" in pdf_path else pdf_path.split("\\")[-1]
        await ws_manager.broadcast(user_id, message)

    # ── Agent 1: PDF Analyst ────────────────────────────────────
    await ws_manager.broadcast(user_id, {
        "type": "ingestion_status",
        "status": "analyzing",
        "agent": "pdf_analyst",
        "attempt": 1,
    })

    extraction = await agent_loop(
        agent_fn=agent_1_pdf_analyst,
        input_data={"pdf_path": pdf_path},
        user_id=user_id,
        ws_callback=ws_callback,
    )

    if not extraction or extraction.get("error"):
        logger.error(f"Agent 1 failed for {pdf_path}")
        reason = extraction.get("error", "Agent 1 failed") if extraction else "Agent 1 failed"
        update_job(task_id, status="failed", error=reason)
        await ws_manager.broadcast(user_id, {
            "type": "ingestion_status",
            "status": "failed",
            "reason": reason,
        })
        return

    # Store extraction in Cognee (per cognee_role.md)
    await store_paper_to_cognee(extraction, user_id)
    extraction.setdefault("A_Meta", {})["pdf_url"] = str(pdf_path)
    update_job(task_id, status="graph_building", paper_id=extraction.get("paper_id", ""),
               paper_title=extraction.get("A_Meta", {}).get("title", ""))

    # ── Agent 2: Graph Builder ──────────────────────────────────
    await ws_manager.broadcast(user_id, {
        "type": "ingestion_status",
        "status": "graph_building",
        "paper_id": extraction.get("paper_id", ""),
    })

    delta = await agent_loop(
        agent_fn=agent_2_graph_builder,
        input_data={"json": extraction},
        user_id=user_id,
        ws_callback=ws_callback,
    )

    if not delta:
        delta = {"delta_summary": {"nodes_created": 0}, "new_gaps": []}

    # ── WebSocket: broadcast ingestion_complete ─────────────────
    # Event format from architecture.md lines 266-276
    await ws_manager.broadcast(user_id, {
        "type": "ingestion_complete",
        "paper_id": extraction.get("paper_id", ""),
        "paper_title": extraction.get("A_Meta", {}).get("title", ""),
        "nodes_created": delta.get("delta_summary", {}).get("nodes_created", 0),
        "nodes_merged": delta.get("delta_summary", {}).get("nodes_merged", 0),
        "cross_paper_edges": delta.get("delta_summary", {}).get("cross_paper_edges", 0),
        "contradictions_detected": delta.get("delta_summary", {}).get("contradictions_detected", 0),
        "new_gaps": delta.get("new_gaps", []),
    })
    update_job(
        task_id,
        status="complete",
        paper_id=extraction.get("paper_id", ""),
        paper_title=extraction.get("A_Meta", {}).get("title", ""),
        delta=delta.get("delta_summary", {}),
        cognee_stored=delta.get("cognee_stored", False),
    )

    logger.info(f"Ingestion complete: {extraction.get('paper_id', '')}")


async def ingest_paper_sync(pdf_path: str, user_id: str, task_id: str = ""):
    """
    Synchronous fallback when Celery is not available (development mode).
    Same logic as _ingest_paper_async.
    """
    await _ingest_paper_async(pdf_path, user_id, task_id)


@celery_app.task(name="tasks.celery_tasks.detect_gaps_all_users")
def detect_gaps_all_users():
    """
    Nightly gap detection for all active users.
    Source: loop_flow.md lines 341-350

    Only runs for users with corpus_size >= 5.
    """
    _run_async(_detect_gaps_async())


async def _detect_gaps_async():
    """Async implementation of nightly gap detection."""
    from core.agent_loop import agent_loop
    from agents.gap_agent import agent_4_gap_agent
    from core import kuzu_client
    from api.websocket import ws_manager

    # Get all unique user_ids from papers
    try:
        user_rows = kuzu_client.execute(
            "MATCH (p:Paper) RETURN DISTINCT p.user_id"
        )
        user_ids = [r["p.user_id"] for r in user_rows if r.get("p.user_id")]
    except Exception as e:
        logger.error(f"Failed to get users for gap detection: {e}")
        return

    for user_id in user_ids:
        corpus_size = len(kuzu_client.get_paper_ids_for_user(user_id))

        if corpus_size < 5:
            logger.info(f"Skipping gap detection for {user_id}: corpus_size={corpus_size} < 5")
            continue

        logger.info(f"Running gap detection for {user_id} (corpus_size={corpus_size})")

        try:
            gap_report = await agent_loop(
                agent_fn=agent_4_gap_agent,
                input_data={"user_id": user_id},
                user_id=user_id,
            )

            # WebSocket: broadcast gap_detection_complete
            # Event format from architecture.md lines 288-293
            if gap_report:
                gaps = gap_report.get("gaps", [])
                top_gap = None
                if gaps:
                    top_gap = {
                        "claim_text": gaps[0].get("claim_text", ""),
                        "rgs_score": gaps[0].get("rgs_score", 0),
                    }

                await ws_manager.broadcast(user_id, {
                    "type": "gap_detection_complete",
                    "gap_count": len(gaps),
                    "critical_gaps": gap_report.get("summary", {}).get("critical_gaps", 0),
                    "top_gap": top_gap,
                })

        except Exception as e:
            logger.error(f"Gap detection failed for {user_id}: {e}")

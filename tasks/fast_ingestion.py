"""Fast, durable ingestion path used by the frontend and Celery worker."""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from threading import Thread

logger = logging.getLogger("papermind.fast_ingestion")


def _preinit_cognee() -> None:
    """Pre-initialize Cognee once at worker startup (not per-job)."""
    try:
        import asyncio as _aio
        from core.cognee_client import setup_cognee
        _aio.run(setup_cognee())
        logger.info("Cognee pre-initialized at worker startup")
    except Exception as exc:
        logger.warning("Cognee pre-init failed (will retry on first call): %s", exc)


# Fire-and-forget — safe to call at module import time
try:
    _preinit_cognee()
except Exception:
    pass



def run_ingestion_job(pdf_path: str, user_id: str, task_id: str):
    """Run ingestion and always leave its durable job in a terminal state."""
    from api.papers import update_job

    try:
        return asyncio.run(_run_fast_ingestion(pdf_path, user_id, task_id))
    except BaseException as exc:
        logger.exception("Ingestion failed for task %s", task_id)
        update_job(
            task_id,
            status="failed",
            stage="Processing failed",
            error=str(exc) or exc.__class__.__name__,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        return None


async def _run_fast_ingestion(pdf_path: str, user_id: str, task_id: str):
    from agents.graph_builder import agent_2_graph_builder
    from agents.loop_judge import LoopJudge
    from agents.pdf_analyst import agent_1_pdf_analyst
    from api.papers import update_job
    from core.gap_cache import invalidate_gap_cache

    started = time.perf_counter()
    update_job(
        task_id,
        status="analyzing",
        stage="Extracting a compact evidence sample",
        progress=20,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    extraction_mode = "ai"
    try:
        extraction = await asyncio.wait_for(
            agent_1_pdf_analyst(
                input_data={
                    "pdf_path": pdf_path,
                    "max_tokens": int(os.environ.get("PAPERMIND_EXTRACTION_MAX_TOKENS", "1400")),
                },
                memory_context="",
                attempt=1,
                user_id=user_id,
            ),
            timeout=float(os.environ.get("PAPERMIND_EXTRACTION_TIMEOUT_SECONDS", "32")),
        )
        if not extraction or extraction.get("error"):
            raise RuntimeError(
                extraction.get("error", "PDF extraction failed")
                if extraction
                else "PDF extraction failed"
            )
    except Exception as exc:
        from tasks.local_extraction import local_fast_extraction

        logger.warning("Using local fast extraction for %s: %s", task_id, exc)
        extraction = local_fast_extraction(pdf_path)
        extraction_mode = "local_fast"

    verdict = await LoopJudge().evaluate("agent_1_pdf_analyst", extraction, 1)
    extraction.setdefault("A_Meta", {})["pdf_url"] = str(pdf_path)
    update_job(
        task_id,
        status="graph_building",
        stage="Committing nodes and edges",
        progress=72,
        extraction_score=verdict.get("score", 0),
        extraction_mode=extraction_mode,
        paper_id=extraction.get("paper_id", ""),
        paper_title=extraction.get("A_Meta", {}).get("title", ""),
    )

    delta = await agent_2_graph_builder(
        input_data={"json": extraction, "defer_cognee": True},
        memory_context="",
        attempt=1,
        user_id=user_id,
    )
    if not delta or not delta.get("delta_summary"):
        raise RuntimeError("Graph builder returned no delta")

    elapsed = round(time.perf_counter() - started, 2)
    update_job(
        task_id,
        status="complete",
        stage="Ready to explore",
        progress=100,
        paper_id=extraction.get("paper_id", ""),
        paper_title=extraction.get("A_Meta", {}).get("title", ""),
        delta=delta.get("delta_summary", {}),
        cognee_status="syncing",
        cognee_stored=False,
        processing_seconds=elapsed,
        extraction_mode=extraction_mode,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    await invalidate_gap_cache(user_id)
    _start_memory_sync(extraction, delta, user_id, task_id)
    logger.info("Interactive ingestion completed in %.2fs for %s", elapsed, task_id)
    return delta


def _start_memory_sync(extraction: dict, delta: dict, user_id: str, task_id: str):
    """Persist structured extraction to Cognee after Kuzu is already available.

    Optimised path vs. the original:
      - Calls cognee.add() with the compact JSON extraction (already structured).
        This indexes the text for retrieval WITHOUT triggering the full
        LLM knowledge-graph extraction pass (cognify), which was the main
        source of latency in the old store_paper_to_cognee() helper.
      - cognee.memify() still runs for the graph delta (Agent 2 output)
        so the living-graph contract is preserved.
    """

    def sync_memory():
        import cognee
        from api.papers import update_job
        from core.cognee_client import _dataset_name, _serialize_with_metadata, setup_cognee
        import json

        async def sync():
            await setup_cognee()  # no-op if already done

            dataset = _dataset_name(user_id)
            paper_id = extraction.get("paper_id", "")

            # ── Lightweight add: index extraction JSON for vector recall ─
            # Splits the 5-module JSON into smaller chunks so embeddings
            # are granular; no LLM call required by cognee.add().
            try:
                payload = _serialize_with_metadata(
                    extraction,
                    {
                        "user_id": user_id,
                        "paper_id": paper_id,
                        "type": "paper_extraction",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                await cognee.add(data=payload, dataset_name=dataset)
                paper_stored = True
            except Exception as exc:
                logger.warning("cognee.add() for extraction failed: %s", exc)
                paper_stored = False

            # ── memify: graph delta (preserves living-graph contract) ───
            delta_stored = False
            try:
                from core.cognee_client import memify
                delta_stored = await memify(
                    data={
                        "paper_id": paper_id,
                        "delta": {
                            **delta.get("delta_summary", {}),
                            "new_gaps": delta.get("new_gaps", []),
                        },
                    },
                    metadata={
                        "user_id": user_id,
                        "paper_id": paper_id,
                        "type": "graph_delta",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as exc:
                logger.warning("memify() failed: %s", exc)

            ready = bool(paper_stored and delta_stored)
            update_job(
                task_id,
                cognee_status="ready" if ready else "partial",
                cognee_stored=ready,
            )

        try:
            asyncio.run(sync())
        except Exception as exc:
            logger.exception("Deferred Cognee sync failed for %s", task_id)
            update_job(task_id, cognee_status="failed", cognee_error=str(exc))

    Thread(
        target=sync_memory,
        daemon=True,
        name=f"papermind-memory-{task_id[:8]}",
    ).start()
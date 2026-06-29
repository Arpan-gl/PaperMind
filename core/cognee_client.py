"""
PaperMind — Cognee Client
Source: docs/cognee_role.md (verbatim implementation)

Cognee is the memory layer. ALL storage goes through these three primitives:
    remember() → chunk + embedding storage
    memify()   → living graph delta consolidation
    recall()   → hybrid vector + graph retrieval

CRITICAL: No data may be stored outside Cognee. If it is → flag violation.
"""

import os
import json
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Optional, Union

import cognee
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("papermind.cognee")


async def setup_cognee() -> None:
    """
    Initialize Cognee with OpenRouter LLM and LanceDB vector backend.
    Exact configuration from cognee_role.md.
    """
    storage_root = Path(os.environ.get("COGNEE_DB_PATH", "./cognee_db")).resolve()
    data_root = storage_root / "data"
    system_root = storage_root / "system"
    data_root.mkdir(parents=True, exist_ok=True)
    system_root.mkdir(parents=True, exist_ok=True)
    cognee.config.data_root_directory(str(data_root))
    cognee.config.system_root_directory(str(system_root))
    cognee.config.set_llm_config({
        "llm_provider": "openai",
        "llm_model": "openai/qwen/qwen3-32b",
        "llm_api_key": os.environ["OPENROUTER_API_KEY"],
        "llm_endpoint": "https://openrouter.ai/api/v1"
    })
    cognee.config.set_vector_db_config({
        "vector_db_provider": "lancedb",
        "vector_db_url": str(system_root / "databases" / "cognee.lancedb"),
    })
    cognee.config.set_embedding_config({
        "embedding_provider": "openai",
        "embedding_model": "openai/text-embedding-3-small",
        "embedding_dimensions": 1536,
        "embedding_endpoint": "https://openrouter.ai/api/v1",
        "embedding_api_key": os.environ["OPENROUTER_API_KEY"],
    })
    logger.info("Cognee initialized with OpenRouter + LanceDB")


def _dataset_name(user_id: Optional[str]) -> str:
    safe_user = re.sub(r"[^a-zA-Z0-9_-]+", "_", user_id or "global")
    return f"papermind_{safe_user}"[:120]


def _serialize_with_metadata(data: Any, metadata: dict) -> str:
    serialized = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return json.dumps({"metadata": metadata, "content": serialized}, ensure_ascii=False)


async def remember(data: Any, metadata: dict) -> bool:
    """
    Store data in Cognee's memory layer.

    Called by (from cognee_role.md):
      1. After Agent 1 PASS — store paper chunks (per module A-E)
      2. Inside agent_loop() — store every attempt + verdict
      3. After Agent 4 — store gap report

    Args:
        data:     String or dict to store. Dicts are JSON-serialized.
        metadata: Must include at minimum: user_id, type.
                  Accepted types: paper_extraction, full_extraction,
                  agent_attempt, gap_report, reference_paper

    Returns:
        True if stored successfully, False on failure.
    """
    try:
        await setup_cognee()
        serialized = _serialize_with_metadata(data, metadata)
        dataset = _dataset_name(metadata.get("user_id"))
        # Create/update the durable dataset without repeating an expensive LLM
        # graph extraction for already-structured agent output.
        await cognee.add(
            data=serialized,
            dataset_name=dataset,
            incremental_loading=True,
        )
        await cognee.remember(
            data=serialized,
            dataset_name=dataset,
            session_id=dataset,
            self_improvement=True,
        )
        logger.info(
            f"remember() OK — type={metadata.get('type')}, "
            f"user={metadata.get('user_id')}"
        )
        return True
    except Exception as e:
        logger.error(f"remember() FAILED: {e}")
        return False


async def memify(data: dict, metadata: dict) -> bool:
    """
    Consolidate a graph delta into Cognee's persistent memory.

    Called ONLY by Agent 2 (Graph Builder) after the Δ(G_u, p) operator.
    This is the closest Cognee primitive to PaperMind's living graph contribution.

    Args:
        data:     Delta dict with paper_id and delta summary.
        metadata: Must include user_id, paper_id, type="graph_delta".

    Returns:
        True if consolidated successfully, False on failure.
    """
    try:
        await setup_cognee()
        dataset = _dataset_name(metadata.get("user_id"))
        await cognee.memify(data=_serialize_with_metadata(data, metadata), dataset=dataset)
        logger.info(
            f"memify() OK — paper={metadata.get('paper_id')}, "
            f"user={metadata.get('user_id')}"
        )
        return True
    except Exception as e:
        logger.error(f"memify() FAILED: {e}")
        return False


async def recall(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = 10
) -> str:
    """
    Retrieve context from Cognee's memory.

    Two retrieval modes (from cognee_role.md):
      1. Scoped (user_id provided): Only this user's corpus
         → Used by agent_loop start, Agent 3 λ_p, Agent 5
      2. Global (no user_id): All stored data
         → Used by Agent 3 λ_m (vector fallback)

    Args:
        query:   Search query text.
        user_id: If provided, scopes retrieval to this user's graph_id.
        top_k:   Maximum number of results to return.

    Returns:
        JSON string of results, or empty string on failure.
    """
    try:
        await setup_cognee()
        kwargs = {"query_text": query, "top_k": top_k, "only_context": True}
        if user_id:
            kwargs["datasets"] = [_dataset_name(user_id)]
            kwargs["session_id"] = _dataset_name(user_id)
        results = await cognee.recall(**kwargs)
        if not results:
            return ""
        serializable = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item)
            for item in results
        ]
        return json.dumps(serializable, ensure_ascii=False)
    except Exception as e:
        logger.error(f"recall() FAILED: {e}")
        return ""

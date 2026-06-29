"""
PaperMind — Cognee Client  (GraphRAG edition)
Source: docs/cognee_role.md + GraphRAG optimisation

Cognee is the memory layer.  Primitives used:
    cognee.add()           → chunk + embedding storage (fast, no LLM graph)
    cognee.cognify()       → full LLM-driven knowledge-graph extraction
    cognee.search()        → GraphRAG: entity/relationship-aware retrieval
    cognee.recall()        → vector-only fallback retrieval

Performance changes vs. original:
  • setup_cognee() is guarded by _setup_done — runs only once per process.
  • recall() uses SearchType.GRAPH (entity-aware) and falls back to vector.
  • batch_remember() stores agent-attempt data via cognee.add() only (no LLM
    graph extraction) — removes the biggest latency source.
  • memify() is kept for the graph-delta path (Agent 2 / background sync).

CRITICAL: No data may be stored outside Cognee.  If it is → flag violation.
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

# ── Singleton setup guard ────────────────────────────────────────
_setup_done: bool = False


async def setup_cognee() -> None:
    """
    Initialize Cognee with OpenRouter LLM and LanceDB vector backend.
    Safe to call multiple times — skips re-initialization after first call.
    """
    global _setup_done
    if _setup_done:
        return

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

    _setup_done = True
    logger.info("Cognee initialized with OpenRouter + LanceDB (GraphRAG mode)")


def _dataset_name(user_id: Optional[str]) -> str:
    safe_user = re.sub(r"[^a-zA-Z0-9_-]+", "_", user_id or "global")
    return f"papermind_{safe_user}"[:120]


def _serialize_with_metadata(data: Any, metadata: dict) -> str:
    serialized = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return json.dumps({"metadata": metadata, "content": serialized}, ensure_ascii=False)


# ── GraphRAG search ──────────────────────────────────────────────

async def cognee_search(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = 10,
) -> str:
    """
    GraphRAG retrieval via cognee.search(SearchType.GRAPH).

    Returns entity + relationship-aware context grounded in the knowledge
    graph rather than raw chunk similarity.  Falls back to vector recall
    if the graph search fails or returns empty results.

    Args:
        query:   Natural-language search query.
        user_id: If provided, scopes retrieval to this user's dataset.
        top_k:   Maximum results.

    Returns:
        JSON string of results, or empty string on failure.
    """
    await setup_cognee()
    try:
        from cognee.api.v1.search.types import SearchType  # cognee ≥1.0
    except ImportError:
        # Older import path
        try:
            from cognee.shared.data_models import SearchType  # type: ignore
        except ImportError:
            SearchType = None

    # ── Attempt GraphRAG (graph-traversal) search ────────────────
    if SearchType is not None:
        try:
            kwargs: dict = {"query_text": query, "search_type": SearchType.GRAPH}
            if user_id:
                kwargs["datasets"] = [_dataset_name(user_id)]
            results = await cognee.search(**kwargs)
            if results:
                serializable = [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item)
                    for item in results
                ]
                # Limit to top_k
                return json.dumps(serializable[:top_k], ensure_ascii=False)
        except Exception as e:
            logger.warning(f"GraphRAG search failed, falling back to vector: {e}")

    # ── Vector fallback ──────────────────────────────────────────
    return await recall(query, user_id=user_id, top_k=top_k)


# ── Fast agent-attempt storage (no LLM graph extraction) ────────

async def batch_remember(items: list[dict], user_id: Optional[str] = None) -> bool:
    """
    Store a batch of agent-attempt records via cognee.add() only.

    Unlike remember(), this skips cognee.remember() (which runs an LLM
    graph-extraction pass) and is therefore ~10× faster.  Use this for
    intermediate agent data that does not need to be part of the knowledge
    graph (attempts, verdicts, loop feedback).

    Args:
        items:   List of dicts each with 'data' and 'metadata' keys.
        user_id: Dataset scope.

    Returns:
        True if all items stored, False on first failure.
    """
    await setup_cognee()
    dataset = _dataset_name(user_id)
    try:
        combined = json.dumps(
            [_serialize_with_metadata(i["data"], i.get("metadata", {})) for i in items],
            ensure_ascii=False,
        )
        await cognee.add(data=combined, dataset_name=dataset)
        logger.debug(f"batch_remember() OK — {len(items)} items, dataset={dataset}")
        return True
    except Exception as e:
        logger.error(f"batch_remember() FAILED: {e}")
        return False


# ── remember() — kept for backward compatibility ─────────────────

async def remember(data: Any, metadata: dict) -> bool:
    """
    Store data in Cognee's memory layer.

    Called by (from cognee_role.md):
      1. After Agent 1 PASS — store paper chunks (per module A-E)
      2. Inside agent_loop() — store every attempt + verdict
      3. After Agent 4 — store gap report

    Optimized: uses cognee.add() with incremental_loading.
    Full cognee.remember() (LLM graph pass) is reserved for paper data
    only; agent-attempt data uses batch_remember() via agent_loop.

    Args:
        data:     String or dict to store. Dicts are JSON-serialized.
        metadata: Must include at minimum: user_id, type.

    Returns:
        True if stored successfully, False on failure.
    """
    await setup_cognee()
    try:
        serialized = _serialize_with_metadata(data, metadata)
        dataset = _dataset_name(metadata.get("user_id"))
        data_type = metadata.get("type", "")

        if data_type in ("paper_extraction", "full_extraction", "reference_paper"):
            # Full knowledge-graph extraction — only for paper-level data
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
        else:
            # Fast path: index for retrieval but skip LLM graph extraction
            await cognee.add(data=serialized, dataset_name=dataset)

        logger.info(
            f"remember() OK — type={data_type}, user={metadata.get('user_id')}"
        )
        return True
    except Exception as e:
        logger.error(f"remember() FAILED: {e}")
        return False


# ── memify() — graph delta consolidation ─────────────────────────

async def memify(data: dict, metadata: dict) -> bool:
    """
    Consolidate a graph delta into Cognee's persistent memory.

    Called ONLY by Agent 2 (Graph Builder) after the Δ(G_u, p) operator
    and by fast_ingestion background sync.

    Args:
        data:     Delta dict with paper_id and delta summary.
        metadata: Must include user_id, paper_id, type="graph_delta".

    Returns:
        True if consolidated successfully, False on failure.
    """
    await setup_cognee()
    try:
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


# ── recall() — vector retrieval (legacy + fallback) ─────────────

async def recall(
    query: str,
    user_id: Optional[str] = None,
    top_k: int = 10
) -> str:
    """
    Retrieve context from Cognee's memory (vector mode).

    Prefer cognee_search() for GraphRAG-quality results.
    This function is kept for backward compatibility and as the fallback
    when graph search is unavailable.

    Two retrieval modes (from cognee_role.md):
      1. Scoped (user_id provided): Only this user's corpus
      2. Global (no user_id): All stored data

    Args:
        query:   Search query text.
        user_id: If provided, scopes retrieval to this user's graph_id.
        top_k:   Maximum number of results to return.

    Returns:
        JSON string of results, or empty string on failure.
    """
    await setup_cognee()
    try:
        kwargs: dict = {"query_text": query, "top_k": top_k, "only_context": True}
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

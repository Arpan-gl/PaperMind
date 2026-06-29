# PaperMind — Cognee's Role

## Overview

Cognee is the **memory layer** for PaperMind. Every piece of information that flows through the system — paper chunks, agent outputs, judge verdicts, graph deltas, gap reports — is stored in and retrieved from Cognee.

The three Cognee primitives used:

| Method | Purpose | Called by |
|---|---|---|
| `cognee.remember()` | Store chunks, outputs, verdicts | All agents after every run |
| `cognee.memify()` | Consolidate graph delta into memory | Agent 2 after Δ operator |
| `cognee.recall()` | Retrieve context for next loop iteration | Every agent at loop start |

---

## Setup

```python
# core/cognee_client.py
import cognee
import os

async def setup_cognee():
    cognee.config.set_llm_config({
        "provider": "openai",
        "model": "qwen/qwen3-32b",
        "api_key": os.environ["OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1"
    })
    cognee.config.set_vector_db_config({
        "provider": "lancedb",
        "url": os.environ.get("COGNEE_DB_PATH", "./cognee_db")
    })
```

---

## cognee.remember() — Storage

Called in these places:

### 1. After Agent 1 — store paper chunks

```python
# agents/pdf_analyst.py

async def store_paper_to_cognee(extraction: dict, user_id: str):
    """
    Store all extracted modules as searchable chunks.
    Called immediately after Agent 1 PASS.
    """
    paper_id = extraction["paper_id"]

    # Store each module as a separate chunk for fine-grained recall
    for module_key, module_data in extraction.items():
        if module_key.startswith(("A_", "B_", "C_", "D_", "E_")):
            await cognee.remember(
                data=str(module_data),
                metadata={
                    "paper_id":    paper_id,
                    "module":      module_key,        # "A_Meta", "B_Textual", etc.
                    "user_id":     user_id,
                    "type":        "paper_extraction",
                    "agent":       "pdf_analyst",
                    "timestamp":   datetime.utcnow().isoformat()
                }
            )

    # Also store the full extraction as one searchable unit
    await cognee.remember(
        data=json.dumps(extraction),
        metadata={
            "paper_id":  paper_id,
            "user_id":   user_id,
            "type":      "full_extraction",
            "agent":     "pdf_analyst"
        }
    )
```

### 2. After every agent loop iteration — store attempt + verdict

```python
# core/agent_loop.py

# Called inside agent_loop() after every agent run
await cognee.remember(
    data=json.dumps({
        "attempt":  attempt,
        "output":   output,
        "verdict":  verdict,
        "agent":    agent_fn.__name__,
        "input_hash": hash(str(input_data))
    }),
    metadata={
        "user_id":  user_id,
        "type":     "agent_attempt",
        "agent":    agent_fn.__name__,
        "status":   verdict["status"],          # "PASS" or "RETRY"
        "score":    verdict["score"],
        "attempt":  attempt
    }
)
```

### 3. After Agent 4 — store gap report

```python
# agents/gap_agent.py

await cognee.remember(
    data=json.dumps(gap_report),
    metadata={
        "user_id":       user_id,
        "type":          "gap_report",
        "corpus_size":   paper_count,
        "critical_gaps": gap_report["summary"]["critical_gaps"],
        "timestamp":     datetime.utcnow().isoformat()
    }
)
```

---

## cognee.memify() — Living Graph Consolidation

Called only by Agent 2 (Graph Builder), after the Δ(G_u, p) operator completes.

This is the closest Cognee primitive to PaperMind's novel living graph contribution. It consolidates the graph delta into Cognee's persistent memory so future recall() calls return enriched context that includes what changed in the graph.

```python
# agents/graph_builder.py

async def consolidate_delta_to_cognee(paper_id: str, delta: dict, user_id: str):
    """
    Store the living graph update delta in Cognee.
    Called after all KuzuDB operations complete.
    """
    await cognee.memify(
        data={
            "paper_id": paper_id,
            "delta": {
                "nodes_created":          delta["delta_summary"]["nodes_created"],
                "nodes_merged":           delta["delta_summary"]["nodes_merged"],
                "cross_paper_edges":      delta["delta_summary"]["cross_paper_edges"],
                "contradictions_detected":delta["delta_summary"]["contradictions_detected"],
                "rgs_nodes_updated":      delta["delta_summary"]["rgs_nodes_updated"],
                "new_gaps_flagged":       delta["delta_summary"]["new_gaps_flagged"],
                "new_gaps":               delta["new_gaps"]
            }
        },
        metadata={
            "user_id":   user_id,
            "paper_id":  paper_id,
            "type":      "graph_delta",
            "timestamp": datetime.utcnow().isoformat()
        }
    )
```

---

## cognee.recall() — Retrieval

Called in two contexts:

### 1. At the start of every loop iteration (self-improving memory)

```python
# core/agent_loop.py

memory_context = await cognee.recall(
    query=str(input_data),
    graph_id=user_id       # scoped to this user's corpus
)

# What this returns:
# Attempt 1: prior paper extractions, agent history
# Attempt 2: attempt 1 output + Loop Judge feedback
# Attempt 3: attempts 1+2 + both feedbacks
#
# The agent reads its own past failures as context.
# This is what makes the loop self-improving.
```

### 2. Inside Agent 3 — corpus-scoped retrieval (λ_p term)

```python
# agents/query_agent.py

# This implements the personal corpus term λ_p in K_fused(q, G_u)
results_personal = await cognee.recall(
    query=question,
    graph_id=user_id,      # ← corpus-scoped — only this user's papers
    top_k=10
)
# s_p(e) = relevance score from Cognee
# weighted at λ_p = 0.50 in K_fused fusion

# Also call without graph_id for global vector fallback (λ_m = 0.15)
results_vector = await cognee.recall(
    query=question,
    top_k=5
)
```

### 3. Inside Agent 5 — find related work for novelty scoring

```python
# agents/novelty_judge.py

related_work = await cognee.recall(
    query=idea_text,
    graph_id=user_id,
    top_k=10
)
# Used to compute R_k(I, G_u) in Novelty formula
```

---

## What Cognee Stores — Complete Map

```
cognee.remember() stores:
  ┌────────────────────┬──────────────────────────────────────────┐
  │ Type               │ Contents                                 │
  ├────────────────────┼──────────────────────────────────────────┤
  │ paper_extraction   │ All 5 modules (A-E) per paper            │
  │ full_extraction    │ Complete JSON from Agent 1               │
  │ agent_attempt      │ Output + verdict + score per attempt     │
  │ gap_report         │ Full RGS-ranked gap list                 │
  │ reference_paper    │ Agents-K1 PDF analysis                   │
  └────────────────────┴──────────────────────────────────────────┘

cognee.memify() stores:
  ┌────────────────────┬──────────────────────────────────────────┐
  │ Type               │ Contents                                 │
  ├────────────────────┼──────────────────────────────────────────┤
  │ graph_delta        │ Δ operator output per paper ingestion    │
  └────────────────────┴──────────────────────────────────────────┘

cognee.recall() retrieves:
  ┌────────────────────┬──────────────────────────────────────────┐
  │ Called by          │ Returns                                  │
  ├────────────────────┼──────────────────────────────────────────┤
  │ agent_loop start   │ Prior attempts + judge feedback          │
  │ Agent 3 (λ_p)      │ Corpus-scoped paper chunks               │
  │ Agent 3 (λ_m)      │ Global vector matches                    │
  │ Agent 5            │ Related methods and claims               │
  └────────────────────┴──────────────────────────────────────────┘
```

---

## What Cognee Does NOT Replace

Cognee handles memory. These are handled separately:

| Task | Handled by |
|---|---|
| Cypher traversal for RELATIONAL queries | KuzuDB directly |
| RGS score computation | Python formula in `core/rgs_calculator.py` |
| Entity deduplication (cosine similarity) | `sentence-transformers` + numpy |
| WebSocket real-time events | FastAPI WebSocket manager |
| Async task queue | Celery + Redis |
| Graph schema and typed edges | KuzuDB schema |

---

## Cognee Client Wrapper

```python
# core/cognee_client.py
import cognee
from datetime import datetime
import json, os

async def setup_cognee():
    cognee.config.set_llm_config({
        "provider": "openai",
        "model": "qwen/qwen3-32b",
        "api_key": os.environ["OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1"
    })
    cognee.config.set_vector_db_config({
        "provider": "lancedb",
        "url": os.environ.get("COGNEE_DB_PATH", "./cognee_db")
    })

async def remember(data: any, metadata: dict) -> bool:
    try:
        await cognee.remember(
            data=json.dumps(data) if not isinstance(data, str) else data,
            metadata=metadata
        )
        return True
    except Exception as e:
        print(f"[COGNEE] remember() failed: {e}")
        return False

async def memify(data: dict, metadata: dict) -> bool:
    try:
        await cognee.memify(data=data, metadata=metadata)
        return True
    except Exception as e:
        print(f"[COGNEE] memify() failed: {e}")
        return False

async def recall(query: str, user_id: str = None, top_k: int = 10) -> str:
    try:
        kwargs = {"query": query, "top_k": top_k}
        if user_id:
            kwargs["graph_id"] = user_id
        results = await cognee.recall(**kwargs)
        return json.dumps(results) if results else ""
    except Exception as e:
        print(f"[COGNEE] recall() failed: {e}")
        return ""
```

---

## Testing Cognee Integration

Run these checks before building agents:

```python
# test_cognee.py
import asyncio
from core.cognee_client import setup_cognee, remember, recall, memify

async def test_roundtrip():
    await setup_cognee()

    # Test 1: remember → recall
    await remember(
        data="Test paper about graph neural networks",
        metadata={"paper_id": "test_001", "user_id": "test_user", "type": "test"}
    )
    result = await recall(query="graph neural networks", user_id="test_user")
    assert "graph" in result.lower(), "recall() did not return stored data"
    print("✓ remember → recall roundtrip works")

    # Test 2: memify
    ok = await memify(
        data={"paper_id": "test_001", "delta": {"nodes_created": 5}},
        metadata={"user_id": "test_user", "type": "graph_delta"}
    )
    assert ok, "memify() failed"
    print("✓ memify() works")

    # Test 3: scoped vs global recall
    result_scoped = await recall("graph", user_id="test_user")
    result_global = await recall("graph")
    print(f"✓ scoped recall: {len(result_scoped)} chars")
    print(f"✓ global recall: {len(result_global)} chars")

asyncio.run(test_roundtrip())
```

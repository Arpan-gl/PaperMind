# PaperMind — Loop Flow

## The Core Idea

Every agent in PaperMind runs inside a **self-improving loop**. An agent acts → the Loop Judge scores the output → if it fails, the exact feedback is stored in Cognee → the agent retries with that feedback already in its memory context. After 3 retries it accepts the best attempt.

This is not just retry logic. Because Cognee stores every attempt and every verdict, the agent **reads its own failure** on the next iteration. The loop is self-improving, not just self-repeating.

---

## Universal Loop Pattern

```python
# core/agent_loop.py

async def agent_loop(
    agent_fn,
    input_data: dict,
    user_id: str,
    max_retries: int = 3
) -> dict:
    """
    Universal self-improving loop for all PaperMind agents.
    All 5 agents (pdf_analyst, graph_builder, query_agent,
    gap_agent, novelty_judge) use this exact function.
    """
    judge = LoopJudge()

    for attempt in range(1, max_retries + 1):

        # Load accumulated memory — includes ALL prior attempts and failures
        memory_context = await cognee.recall(
            query=str(input_data),
            graph_id=user_id
        )
        # On attempt 1: memory_context is empty or has prior papers
        # On attempt 2: memory_context includes attempt 1 output + judge feedback
        # On attempt 3: memory_context includes both prior attempts + both feedbacks

        # Run the agent with memory + attempt number
        output = await agent_fn(
            input_data=input_data,
            memory_context=memory_context,
            attempt=attempt,
            user_id=user_id
        )

        # Judge evaluates output against rubric
        verdict = await judge.evaluate(
            agent_name=agent_fn.__name__,
            output=output,
            attempt=attempt
        )

        # Store this attempt in Cognee REGARDLESS of pass/fail
        # This is what makes the loop self-improving
        await cognee.remember(
            data={
                "attempt": attempt,
                "output": output,
                "verdict": verdict,
                "agent": agent_fn.__name__,
                "input_hash": hash(str(input_data))
            },
            metadata={
                "user_id": user_id,
                "type": "agent_attempt",
                "agent": agent_fn.__name__,
                "status": verdict["status"]
            }
        )

        if verdict["status"] == "PASS":
            return output

        if attempt == max_retries:
            # After all retries: return best scoring attempt from Cognee
            return await get_best_attempt(user_id, agent_fn.__name__, input_data)

        # Loop continues — judge feedback now in Cognee
        # Next recall() will load it as part of memory_context

    return None


async def get_best_attempt(user_id: str, agent_name: str, input_data: dict) -> dict:
    """Retrieve highest-scoring attempt after all retries exhausted."""
    attempts = await cognee.recall(
        query=f"{agent_name} attempts {str(input_data)[:100]}",
        graph_id=user_id,
        top_k=10
    )
    # Filter to this agent's attempts, return highest score
    relevant = [a for a in attempts if a.get("agent") == agent_name]
    if not relevant:
        return {}
    return max(relevant, key=lambda x: x.get("verdict", {}).get("score", 0))
```

---

## Full Ingestion Flow (Paper Upload)

```
User uploads PDF
      │
      ▼
[Celery Task: ingest_paper(pdf_path, user_id)]
      │
      ▼
┌─────────────────────────────────────────────┐
│  AGENT 1 LOOP — PDF Analyst                 │
│                                             │
│  attempt 1                                  │
│    recall() → no prior memory               │
│    extract → 5-module JSON                  │
│    judge() → score 85 → PASS ✓              │
│                                             │
│  (if attempt 1 fails):                      │
│  attempt 2                                  │
│    recall() → loads attempt 1 + feedback    │
│    extract → fixed JSON                     │
│    judge() → score 82 → PASS ✓              │
│                                             │
│  (if attempt 2 fails):                      │
│  attempt 3                                  │
│    recall() → loads attempts 1+2 + feedback │
│    extract → best effort                    │
│    judge() → PASS_PARTIAL (accept)          │
└─────────────────────────────────────────────┘
      │
      │ 5-module JSON
      ▼
[WebSocket: {"type": "ingestion_status", "status": "graph_building"}]
      │
      ▼
┌─────────────────────────────────────────────┐
│  AGENT 2 LOOP — Graph Builder               │
│                                             │
│  attempt 1                                  │
│    recall() → loads Agent 1 output          │
│    run Δ(G_u, p) → delta JSON               │
│    judge() → score 80 → PASS ✓              │
└─────────────────────────────────────────────┘
      │
      │ Graph delta
      ▼
[KuzuDB: nodes created, edges created, RGS updated]
      │
      ▼
[Cognee: memify() stores delta]
      │
      ▼
[WebSocket: {"type": "ingestion_complete", "nodes_created": 12, "new_gaps": [...]}]
      │
      ▼
[Frontend: Cytoscape graph updates live]
```

---

## Full Query Flow (User Question)

```
User types question
      │
      ▼
POST /api/query {"question": "...", "user_id": "..."}
      │
      ▼
┌─────────────────────────────────────────────┐
│  AGENT 3 LOOP — Query Agent                 │
│                                             │
│  attempt 1                                  │
│    recall() → loads corpus memory           │
│    classify intent → RELATIONAL             │
│    K_fused retrieval:                       │
│      Cognee recall() → s_p (λ=0.50)        │
│      KuzuDB Cypher  → s_k (λ=0.35)        │
│      Cognee vector  → s_m (λ=0.15)        │
│    build answer + citations                 │
│    judge() checks unsourced_claims == []    │
│      → PASS ✓                              │
│                                             │
│  (if unsourced_claims not empty):           │
│  attempt 2                                  │
│    recall() → loads: judge said             │
│               "Claim X has no citation"     │
│    fix that specific claim                  │
│    judge() → PASS ✓                        │
└─────────────────────────────────────────────┘
      │
      │ answer + citations JSON
      ▼
Frontend: streaming answer with inline citations
          click citation → jump to graph node → passage viewer
```

---

## Full Gap Detection Flow (Nightly Job)

```
Celery beat schedule: run every night at 2am UTC
      │
      ▼
[Celery Task: detect_gaps(user_id)]
      │
      ▼
┌─────────────────────────────────────────────┐
│  AGENT 4 LOOP — Gap Agent                   │
│                                             │
│  attempt 1                                  │
│    recall() → prior gap reports             │
│    run 4 Cypher queries on G_u              │
│    compute RGS(v) for all candidates        │
│    deduplicate, rank, generate descriptions │
│    judge() → ≥5 gaps, RGS>0 → PASS ✓      │
└─────────────────────────────────────────────┘
      │
      │ gap_report JSON
      ▼
[Cognee: remember(gap_report)]
      │
      ▼
[WebSocket: {"type": "gap_detection_complete", "critical_gaps": 2}]
      │
      ▼
Frontend: Gaps panel updates, notification badge
```

---

## Loop State Machine

```
                    ┌─────────────────┐
                    │   INPUT DATA    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  cognee.recall() │◄──────────────────┐
                    │  load memory    │                    │
                    └────────┬────────┘                    │
                             │                             │
                    ┌────────▼────────┐                    │
                    │   AGENT RUN     │                    │
                    │  (Qwen3:32B)    │                    │
                    └────────┬────────┘                    │
                             │                             │
                    ┌────────▼────────┐                    │
                    │  cognee.remember │                    │
                    │  store attempt  │                    │
                    └────────┬────────┘                    │
                             │                             │
                    ┌────────▼────────┐                    │
                    │   LOOP JUDGE    │                    │
                    │  score 0-100   │                    │
                    └────────┬────────┘                    │
                             │                             │
               ┌─────────────┴─────────────┐              │
               │                           │              │
    ┌──────────▼──────────┐   ┌────────────▼──────────┐   │
    │     PASS            │   │   RETRY               │   │
    │  score ≥ threshold  │   │  score < threshold    │   │
    │  return output      │   │  attempt < 3          │   │
    └─────────────────────┘   └────────────┬──────────┘   │
                                           │              │
                                  ┌────────▼──────┐       │
                                  │ cognee.remember│       │
                                  │ store feedback │       │
                                  └────────┬───────┘       │
                                           │               │
                                           └───────────────┘
                                           (next attempt loads feedback via recall)

After attempt 3 without PASS:
    → status = PASS_PARTIAL
    → return highest-scoring attempt from Cognee
```

---

## Why Cognee Is the Loop's Memory

```
Attempt 1:
  cognee.recall() → empty (no prior history)
  agent runs → output A1
  judge says: "E_Relations[0].evidence is empty"
  cognee.remember(A1 + judge_feedback_1)

Attempt 2:
  cognee.recall() → returns {A1, judge_feedback_1}
  agent reads: "last time E_Relations[0].evidence was empty"
  agent re-extracts verbatim span → output A2
  judge says: PASS

Attempt 3 (if needed):
  cognee.recall() → returns {A1, feedback_1, A2, feedback_2}
  agent has full failure history → corrects both issues
```

The agent is **not retrying blindly**. It is learning from its own mistakes within the loop, stored in Cognee.

---

## Celery Task Setup

```python
# tasks/celery_tasks.py
from celery import Celery
from celery.schedules import crontab

app = Celery('papermind', broker='redis://localhost:6379/0')

app.conf.beat_schedule = {
    'detect-gaps-nightly': {
        'task': 'tasks.detect_gaps_all_users',
        'schedule': crontab(hour=2, minute=0),  # 2am UTC every day
    },
}

@app.task
async def ingest_paper_task(pdf_path: str, user_id: str):
    """Called by FastAPI after paper upload. Runs Agent 1 → Agent 2 loop."""
    from core.agent_loop import agent_loop
    from agents.pdf_analyst import agent_1_pdf_analyst
    from agents.graph_builder import agent_2_graph_builder

    extraction = await agent_loop(agent_1_pdf_analyst, {"pdf_path": pdf_path}, user_id)
    delta = await agent_loop(agent_2_graph_builder, {"json": extraction}, user_id)

    await ws_manager.broadcast(user_id, {
        "type": "ingestion_complete",
        "paper_id": extraction["paper_id"],
        "nodes_created": delta["delta_summary"]["nodes_created"],
        "new_gaps": delta["new_gaps"]
    })

@app.task
async def detect_gaps_all_users():
    """Nightly gap detection for all active users."""
    from core.agent_loop import agent_loop
    from agents.gap_agent import agent_4_gap_agent
    users = await get_active_users()
    for user_id in users:
        corpus_size = await get_corpus_size(user_id)
        if corpus_size >= 5:
            await agent_loop(agent_4_gap_agent, {"user_id": user_id}, user_id)
```

---

## FastAPI Endpoints That Trigger Loops

```python
# api/papers.py
@router.post("/papers/ingest")
async def ingest_paper(file: UploadFile, user_id: str = Depends(get_current_user)):
    pdf_path = await save_upload(file)
    # Trigger async Celery task — returns immediately
    task = ingest_paper_task.delay(pdf_path, user_id)
    return {"task_id": task.id, "status": "queued"}

# api/query.py
@router.post("/query")
async def query(request: QueryRequest, user_id: str = Depends(get_current_user)):
    # Runs Agent 3 loop synchronously (fast enough for real-time)
    result = await agent_loop(
        agent_3_query_agent,
        {"question": request.question},
        user_id
    )
    return result

# api/graph.py
@router.get("/graph/gaps")
async def get_gaps(user_id: str = Depends(get_current_user)):
    # Trigger gap detection on-demand
    result = await agent_loop(
        agent_4_gap_agent,
        {"user_id": user_id},
        user_id
    )
    return result
```

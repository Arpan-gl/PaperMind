# PaperMind — System Architecture

## What PaperMind Is

PaperMind is a **living research knowledge graph** that extends the Agents-K1 paper (arXiv:2606.13669) with three novel contributions:

| Contribution | Formula | What it does |
|---|---|---|
| Living Graph Update | `Δ(G_u, p)` | Retroactively enriches existing nodes when a new paper is ingested |
| Corpus-Scoped Retrieval | `K_fused(q, G_u)` | Personalizes retrieval to user's own paper corpus |
| Research Gap Score | `RGS(v)` | First formal metric to rank research gaps by scientific importance |

Agents-K1 proves the graph-over-RAG thesis at 2.46M papers. PaperMind is the **user-facing product** they explicitly did not build.

---

## Tech Stack

```
LLM          Qwen3:32B via OpenRouter
             Model ID : qwen/qwen3-32b
             Base URL : https://openrouter.ai/api/v1
             Cost     : ~$0.003 per paper ingested

Memory       Cognee  (ALL storage goes through Cognee)
             remember() → chunk + embedding storage
             memify()   → living graph delta consolidation
             recall()   → hybrid vector + graph retrieval

Graph DB     KuzuDB (embedded, no separate server)

PDF Parser   MinerU  (figures, tables, equations as first-class)
             Fallback: pymupdf

Backend      FastAPI + Celery + Redis

Frontend     Next.js + Cytoscape.js

Deploy       Railway or Render
```

---

## Full System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     RESEARCHER / USER                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                     REST + WebSocket
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    NEXT.JS FRONTEND                          │
│                                                              │
│   Paper Upload  │  Cytoscape Graph  │  Chat  │  Gaps Panel  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│              FASTAPI BACKEND  +  CELERY WORKERS              │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Agent 1  │  │ Agent 2  │  │ Agent 3  │  │ Agent 4  │   │
│  │  PDF     │  │  Graph   │  │  Query   │  │   Gap    │   │
│  │ Analyst  │  │ Builder  │  │  Agent   │  │  Agent   │   │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘   │
│       │              │              │              │          │
│       └──────────────┴──────────────┴──────────────┘         │
│                              │                                │
│              ┌───────────────▼──────────────────┐            │
│              │         AGENT 6: LOOP JUDGE       │            │
│              │   Scores every output 0-100       │            │
│              │   Returns PASS or RETRY(feedback) │            │
│              └──────────────────────────────────┘            │
└───────────┬──────────────────────────┬───────────────────────┘
            │                          │
 ┌──────────▼──────────┐   ┌───────────▼───────────┐
 │       COGNEE         │   │       KUZUDB           │
 │                      │   │                        │
 │  remember()          │   │  Node tables:          │
 │  memify()            │◄──│  Paper, Claim,         │
 │  recall()            │   │  Method, Dataset,      │
 │                      │   │  Author                │
 │  Stores:             │   │                        │
 │  • All paper chunks  │   │  Edge tables:          │
 │  • Agent outputs     │   │  CITES, HAS_CLAIM,     │
 │  • Judge verdicts    │   │  CONTRADICTS,          │
 │  • Retry history     │   │  SUPPORTS,             │
 │  • Gap reports       │   │  USES_SAME_METHOD,     │
 │  • Graph deltas      │   │  PROPOSES, etc.        │
 └──────────────────────┘   └───────────────────────┘
                  ▲
       Qwen3:32B via OpenRouter
       drives ALL agent reasoning
```

---

## KuzuDB Schema

```cypher
-- NODE TABLES
CREATE NODE TABLE Paper(
  paper_id   STRING,
  title      STRING,
  pub_year   INT64,
  venue      STRING,
  pdf_url    STRING,
  user_id    STRING,
  PRIMARY KEY (paper_id)
)

CREATE NODE TABLE Claim(
  claim_id         STRING,
  text             STRING,
  paper_id         STRING,
  section          STRING,
  page             INT64,
  support_count    INT64,
  contradict_count INT64,
  rgs_score        DOUBLE,
  support_density  DOUBLE,
  is_gap           BOOLEAN,
  PRIMARY KEY (claim_id)
)

CREATE NODE TABLE Method(
  node_id      STRING,
  name         STRING,
  paper_count  INT64,
  aliases      STRING[],
  PRIMARY KEY (node_id)
)

CREATE NODE TABLE Dataset(
  node_id  STRING,
  name     STRING,
  year     INT64,
  version  STRING,
  PRIMARY KEY (node_id)
)

CREATE NODE TABLE Author(
  author_id   STRING,
  name        STRING,
  affiliation STRING,
  PRIMARY KEY (author_id)
)

-- EDGE TABLES
CREATE REL TABLE CITES(
  FROM Paper TO Paper,
  strength      INT64,
  cite_type     STRING,
  relation_role STRING
)

CREATE REL TABLE HAS_CLAIM(
  FROM Paper TO Claim,
  section STRING,
  page    INT64
)

CREATE REL TABLE CONTRADICTS(
  FROM Claim TO Claim,
  confidence  DOUBLE,
  evidence_a  STRING,
  evidence_b  STRING
)

CREATE REL TABLE SUPPORTS(
  FROM Claim TO Claim,
  confidence DOUBLE
)

CREATE REL TABLE USES_SAME_METHOD(
  FROM Paper TO Paper,
  method_name STRING,
  similarity  DOUBLE
)

CREATE REL TABLE PROPOSES(FROM Paper TO Method)
CREATE REL TABLE USES_DATASET(FROM Paper TO Dataset)
CREATE REL TABLE AUTHORED_BY(FROM Paper TO Author, ordering INT64)
CREATE REL TABLE REFERENCES(FROM Paper TO Claim)
CREATE REL TABLE APPLIES_TO(FROM Method TO Dataset)
```

---

## Folder Structure

```
papermind/
├── docs/
│   ├── architecture.md        ← this file
│   ├── agents.md              ← all 6 agents with prompts
│   ├── loop_flow.md           ← self-improving loop pattern
│   └── cognee_role.md         ← Cognee integration details
├── agents_k1_paper.pdf        ← reference paper (MUST be read first)
├── main.py                    ← FastAPI app entry point
├── agents/
│   ├── pdf_analyst.py
│   ├── graph_builder.py
│   ├── query_agent.py
│   ├── gap_agent.py
│   ├── novelty_judge.py
│   └── loop_judge.py
├── core/
│   ├── agent_loop.py          ← universal loop runner
│   ├── cognee_client.py       ← Cognee wrapper
│   ├── openrouter_client.py   ← Qwen3:32B client
│   ├── kuzu_client.py         ← KuzuDB wrapper
│   └── rgs_calculator.py      ← RGS(v) formula
├── api/
│   ├── papers.py
│   ├── query.py
│   ├── graph.py
│   └── websocket.py
├── tasks/
│   └── celery_tasks.py
├── schema/
│   └── kuzu_schema.cypher
├── frontend/                  ← Next.js app
└── requirements.txt
```

---

## Environment Variables

```bash
OPENROUTER_API_KEY=sk-or-...
COGNEE_DB_PATH=./cognee_db
KUZU_DB_PATH=./kuzu_graph
REDIS_URL=redis://localhost:6379
FRONTEND_URL=http://localhost:3000
```

---

## Requirements

```
fastapi==0.115.0
uvicorn==0.30.0
celery==5.3.6
redis==5.0.1
cognee==0.1.15
kuzu==0.6.0
openai==1.40.0
pymupdf==1.24.0
sentence-transformers==3.0.0
numpy==1.26.4
python-multipart==0.0.9
websockets==12.0
pydantic==2.8.0
python-dotenv==1.0.1
```

---

## WebSocket Events (Real-Time UI Updates)

```json
// After Agent 2 completes ingestion
{
  "type": "ingestion_complete",
  "paper_id": "...",
  "paper_title": "...",
  "nodes_created": 12,
  "nodes_merged": 3,
  "cross_paper_edges": 7,
  "contradictions_detected": 1,
  "new_gaps": [...]
}

// During Agent 1 loop retry
{
  "type": "ingestion_status",
  "paper_id": "...",
  "status": "retrying",
  "attempt": 2,
  "reason": "D_Citations[1].strength_score is null"
}

// After Agent 4 gap detection
{
  "type": "gap_detection_complete",
  "gap_count": 8,
  "critical_gaps": 2,
  "top_gap": { "claim_text": "...", "rgs_score": 0.82 }
}
```

---

## Cost Model (Qwen3:32B via OpenRouter)

```
Rate            $0.40 / M input tokens
                $0.60 / M output tokens

Per paper       Agent 1: ~4000 tokens = $0.0016
(ingestion)     Agent 2: ~2000 tokens = $0.0008
                Judge×2: ~1000 tokens = $0.0004
                Total  : ~$0.003 per paper

Per query       Agent 3: ~3000 tokens = $0.0014

Demo run        50 papers + 100 queries = ~$0.30 total
```

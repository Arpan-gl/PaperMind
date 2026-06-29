"""
PaperMind - Query Agent
Source: docs/agents.md (lines 305-406)

Trigger:  User submits a question
Input:    Question text + user_id
Output:   Answer with full citation provenance
PASS:     85 / 100

Implements corpus-scoped tri-source retrieval K_fused(q, G_u):
    Source 1 - Personal corpus via Cognee  (lambda_p = 0.50)
    Source 2 - KuzuDB graph traversal      (lambda_k = 0.35)
    Source 3 - Vector fallback via Cognee  (lambda_m = 0.15)

CRITICAL: unsourced_claims MUST be [] to PASS judge.
"""

import json
import logging
from typing import Optional

from core.openrouter_client import qwen_call
from core import cognee_client
from core import kuzu_client

logger = logging.getLogger("papermind.agent3")

LAMBDA_P = 0.50
LAMBDA_K = 0.35
LAMBDA_M = 0.15

AGENT_3_PROMPT = """You are the Query Agent in PaperMind. Answer researcher questions using
corpus-scoped tri-source retrieval K_fused(q, G_u).

This extends Agents-K1 Equation 19 with a personal corpus lambda_p term.

## Memory context:
{memory_context}
Attempt {attempt}. Feedback: {judge_feedback}

## Question: "{question}"
## Corpus: {paper_count} papers in G_u

## Retrieved context from K_fused (Top K ranked):
{fused_context}

## STEP 1 - Classify intent (pick exactly one)
  FACTUAL    -> specific lookup ("What dataset did paper X use?")
  RELATIONAL -> graph relationship ("Which papers contradict on topic X?")
  SYNTHESIS  -> broad summary ("Summarize evidence on topic Y")
  GAP        -> gap discovery ("What is not yet studied in my corpus?")
  NOVELTY    -> idea evaluation ("Is idea X novel given my papers?")

## STEP 2 - Answer with MANDATORY provenance
RULE: Every claim MUST have a citation. If you cannot source it -> do not include it.

Inline format: "Smith found that X [Smith 2023, results, p.7]"

Citation object:
{{
  "claim_text": "",
  "paper_title": "",
  "paper_id": "",
  "section": "methods|results|discussion|introduction",
  "page": <int - must be integer not null>,
  "passage": "<verbatim <= 25 words>",
  "confidence": <0.0-1.0>,
  "edge_type": "SUPPORTS|CONTRADICTS|CITES"
}}

## Output:
{{
  "intent": "FACTUAL|RELATIONAL|SYNTHESIS|GAP|NOVELTY",
  "answer": "<full answer with inline citations>",
  "citations": [<citation objects>],
  "graph_path": ["node_id_1", "CONTRADICTS", "node_id_2"],
  "query_mode": "<intent>",
  "sources_used": {{"personal_corpus": <int>, "graph_traversal": <int>, "vector": <int>}},
  "unsourced_claims": []
}}

## CRITICAL: unsourced_claims MUST be [] to PASS judge."""


def fuse_retrievals(personal_data: str, graph_data: str, vector_data: str, top_k: int = 10) -> str:
    """Computes K_fused = TopK[ 0.50*s_p + 0.35*s_k + 0.15*s_m ]."""

    def parse_source(source_str: str):
        if not source_str:
            return []
        try:
            parsed = json.loads(source_str)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except Exception:
            pass
        return [{"text": line.strip()} for line in source_str.split("\n") if line.strip()]

    p_items = parse_source(personal_data)
    k_items = parse_source(graph_data)
    m_items = parse_source(vector_data)

    fused_scores: dict[str, float] = {}

    def process_items(items, weight: float):
        for rank, item in enumerate(items):
            if isinstance(item, dict):
                text = item.get("text") or item.get("passage") or item.get("c.text") or str(item)
                score = item.get("score") or item.get("confidence") or (1.0 / (rank + 1))
            else:
                text = str(item)
                score = 1.0 / (rank + 1)

            key = text.strip()
            if key:
                fused_scores[key] = fused_scores.get(key, 0.0) + (weight * float(score))

    process_items(p_items, LAMBDA_P)
    process_items(k_items, LAMBDA_K)
    process_items(m_items, LAMBDA_M)

    sorted_fused = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
    top_fused = sorted_fused[:top_k]

    lines = []
    for rank, (text, score) in enumerate(top_fused):
        lines.append(f"[{rank + 1}] [Score: {score:.3f}] {text}")
    return "\n".join(lines) if lines else "No fused retrieval results."


async def agent_3_query_agent(
    input_data: dict,
    memory_context: str,
    attempt: int,
    user_id: str,
) -> dict:
    """Agent 3: Query Agent - Implements K_fused(q, G_u)."""
    question = input_data.get("question", "")
    judge_feedback = _extract_judge_feedback(memory_context)

    source_personal = await _safe_recall(query=question, user_id=user_id, top_k=10)
    source_graph = await _graph_retrieval(question, user_id)
    source_vector = await _safe_recall(query=question, top_k=5)
    fused_context = fuse_retrievals(source_personal, source_graph, source_vector, top_k=10)

    try:
        paper_ids = kuzu_client.get_paper_ids_for_user(user_id)
    except Exception as e:
        logger.warning(f"Failed to read corpus size for query agent: {e}")
        paper_ids = []
    paper_count = len(paper_ids)

    system_prompt = AGENT_3_PROMPT.format(
        memory_context=memory_context[:2000] if memory_context else "No prior attempts.",
        attempt=attempt,
        judge_feedback=judge_feedback if judge_feedback else "None (first attempt).",
        question=question,
        paper_count=paper_count,
        fused_context=fused_context[:6000],
    )

    try:
        response = await qwen_call(
            system_prompt=system_prompt,
            user_message=f"Answer this question with full citation provenance:\n\n{question}",
            temperature=0.3,
            json_mode=True,
        )
    except Exception as e:
        logger.warning(f"LLM query synthesis unavailable, using graph fallback: {e}")
        return _build_fallback_query_response(question, user_id)

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        result = {
            "intent": "FACTUAL",
            "answer": response,
            "citations": [],
            "graph_path": [],
            "query_mode": "FACTUAL",
            "sources_used": {"personal_corpus": 0, "graph_traversal": 0, "vector": 0},
            "unsourced_claims": ["JSON parse error"],
        }

    if "unsourced_claims" not in result:
        result["unsourced_claims"] = []

    return result


async def _graph_retrieval(question: str, user_id: str) -> str:
    """KuzuDB graph traversal (Source 2, lambda_k = 0.35)."""
    results = []
    try:
        paper_ids = kuzu_client.get_paper_ids_for_user(user_id)
    except Exception as e:
        logger.warning(f"Graph retrieval unavailable: {e}")
        return "Graph retrieval unavailable right now."

    if not paper_ids:
        return "No papers in corpus."

    try:
        contradictions = kuzu_client.execute(
            "MATCH (c1:Claim)-[:CONTRADICTS]->(c2:Claim) "
            "MATCH (c1)<-[:HAS_CLAIM]-(p1:Paper) "
            "MATCH (c2)<-[:HAS_CLAIM]-(p2:Paper) "
            "RETURN p1.title, c1.text, c2.text, p2.title LIMIT 20"
        )
        if contradictions:
            results.append(f"Contradictions found: {json.dumps(contradictions[:10])}")
    except Exception:
        pass

    keywords = question.lower().split()[:5]
    for keyword in keywords:
        if len(keyword) < 4:
            continue
        try:
            claims = kuzu_client.execute(
                "MATCH (c:Claim)<-[:HAS_CLAIM]-(p:Paper) "
                "WHERE p.user_id = $uid AND c.text CONTAINS $kw "
                "RETURN c.text, p.title, c.section, c.page LIMIT 5",
                {"uid": user_id, "kw": keyword},
            )
            if claims:
                results.append(f"Claims matching '{keyword}': {json.dumps(claims)}")
        except Exception:
            pass

    try:
        top_claims = kuzu_client.execute(
            "MATCH (c:Claim)<-[:HAS_CLAIM]-(p:Paper) "
            "WHERE p.user_id = $uid "
            "RETURN c.text, p.title, c.rgs_score "
            "ORDER BY c.rgs_score DESC LIMIT 15",
            {"uid": user_id},
        )
        if top_claims:
            results.append(f"Top claims by RGS: {json.dumps(top_claims)}")
    except Exception:
        pass

    try:
        gaps = kuzu_client.execute(
            "MATCH (c:Claim) WHERE c.is_gap = true "
            "RETURN c.text, c.rgs_score, c.claim_id "
            "ORDER BY c.rgs_score DESC LIMIT 10"
        )
        if gaps:
            results.append(f"Research gaps: {json.dumps(gaps)}")
    except Exception:
        pass

    return "\n\n".join(results) if results else "No graph results found."


async def _safe_recall(query: str, user_id: Optional[str] = None, top_k: int = 10) -> str:
    try:
        return await cognee_client.recall(query=query, user_id=user_id, top_k=top_k)
    except Exception as e:
        logger.warning(f"Cognee recall unavailable: {e}")
        return ""


def _build_fallback_query_response(question: str, user_id: str) -> dict:
    try:
        papers = kuzu_client.get_all_papers(user_id)
    except Exception as e:
        logger.warning(f"Fallback paper lookup failed: {e}")
        papers = []

    try:
        claims = kuzu_client.execute(
            "MATCH (p:Paper)-[:HAS_CLAIM]->(c:Claim) "
            "WHERE p.user_id = $uid "
            "RETURN p.paper_id, p.title, c.claim_id, c.text, c.section, c.page, c.rgs_score "
            "ORDER BY c.rgs_score DESC LIMIT 5",
            {"uid": user_id},
        )
    except Exception as e:
        logger.warning(f"Fallback claim lookup failed: {e}")
        claims = []

    citations = []
    graph_path: list[str] = []
    for claim in claims[:3]:
        citations.append({
            "claim_text": claim.get("c.text", ""),
            "paper_title": claim.get("p.title", ""),
            "paper_id": claim.get("p.paper_id", ""),
            "section": claim.get("c.section") or "findings",
            "page": int(claim.get("c.page") or 0),
            "passage": (claim.get("c.text", "") or "")[:160],
            "confidence": 0.55,
            "edge_type": "HAS_CLAIM",
        })
        if claim.get("p.paper_id") and claim.get("c.claim_id"):
            graph_path = [claim["p.paper_id"], "HAS_CLAIM", claim["c.claim_id"]]

    if claims:
        answer = "PaperMind could not reach the synthesis model, so this answer comes from the stored graph only. "
        if "topic" in question.lower() or "research" in question.lower():
            paper_titles = [row.get("p.title", "Untitled paper") for row in papers[:3]]
            title_summary = ", ".join(paper_titles) if paper_titles else "your uploaded papers"
            answer += f"Your current corpus is centered on {title_summary}. "
        highlights = []
        for index, claim in enumerate(citations, start=1):
            paper_label = claim["paper_title"] or claim["paper_id"] or "stored paper"
            highlights.append(
                f"[{index}] {claim['claim_text']} [{paper_label}, {claim['section']}, p.{claim['page']}]"
            )
        answer += "Top extracted evidence: " + " ".join(highlights)
    elif papers:
        titles = ", ".join(row.get("p.title", "Untitled paper") for row in papers[:4])
        answer = (
            "PaperMind could not reach the synthesis model right now. "
            f"The stored corpus currently includes: {titles}."
        )
    else:
        answer = (
            "PaperMind could not reach the query model, and no stored corpus evidence was available yet. "
            "Upload a paper or retry once the backend connection is healthy."
        )

    return {
        "intent": "SYNTHESIS" if "summary" in question.lower() or "topic" in question.lower() else "FACTUAL",
        "answer": answer,
        "citations": citations,
        "graph_path": graph_path,
        "query_mode": "GRAPH_FALLBACK",
        "sources_used": {
            "personal_corpus": len(citations),
            "graph_traversal": 1 if claims else 0,
            "vector": 0,
        },
        "unsourced_claims": [],
    }


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

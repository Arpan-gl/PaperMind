"""
PaperMind - Agent 4: Gap Detection Agent
Source: docs/agents.md (lines 410-528)

Trigger:  Nightly scheduled job OR user clicks "Find Gaps"
Input:    user_id + corpus metadata
Output:   Ranked gap report with RGS scores
PASS:     75 / 100
"""

import json
import logging
from datetime import datetime

import numpy as np

from core.openrouter_client import qwen_call
from core import cognee_client
from core import kuzu_client
from core.rgs_calculator import classify_gap, compute_rgs

logger = logging.getLogger("papermind.agent4")

GAP_DEDUP_COSINE = 0.92

AGENT_4_PROMPT = """You are the Gap Detection Agent in PaperMind. You implement RGS(v) - the Research
Gap Score - PaperMind's novel metric extending Agents-K1's O5 operator.

O5 finds gaps. RGS ranks them by scientific importance.

## Memory context (prior gap reports):
{memory_context}
Attempt {attempt}. Feedback: {judge_feedback}

## Corpus: {paper_count} papers, user {user_id}

## Topology scan results:
{topology_results}

## RGS Formula:
RGS(c) = 0.30 x (1 / max(degree(c), 1))
        + 0.20 x CitAge(c)
        + 0.30 x MethodCentrality(c)
        + 0.20 x (1 - SupportDensity(c))

## For each gap, provide:
"[N] papers reference that [claim_text], but no paper directly tests it.
 Related methods: [list]. Suggested investigation: [one specific sentence]."

## Output:
{{
  "corpus_analyzed": <int>,
  "gaps": [{{
    "gap_id": "gap_001",
    "gap_type": "critical_gap|moderate_gap|orphan_method|methodology_gap",
    "claim_text": "",
    "rgs_score": <float 0-1>,
    "referenced_by_count": <int>,
    "referenced_by_papers": ["paper_id1"],
    "support_count": <int>,
    "contradict_count": <int>,
    "related_methods": ["method1"],
    "human_description": "",
    "suggested_investigation": ""
  }}],
  "summary": {{
    "critical_gaps": <int>,
    "moderate_gaps": <int>,
    "orphan_methods": <int>,
    "methodology_gaps": <int>
  }}
}}
"""


async def agent_4_gap_agent(
    input_data: dict,
    memory_context: str,
    attempt: int,
    user_id: str,
) -> dict:
    """Agent 4: Gap Detection Agent - Implements RGS(v)."""
    try:
        paper_ids = kuzu_client.get_paper_ids_for_user(user_id)
    except Exception as e:
        logger.warning(f"Failed to read paper ids for gap detection: {e}")
        paper_ids = []
    paper_count = len(paper_ids)

    query1_results = []
    try:
        query1_results = kuzu_client.execute(
            "MATCH (c:Claim) WHERE c.paper_id IN $pids "
            "OPTIONAL MATCH (c)-[r]-() "
            "RETURN c.claim_id, c.text, c.paper_id, "
            "count(r) AS degree, c.support_count, c.contradict_count",
            {"pids": paper_ids},
        )
    except Exception as e:
        logger.warning(f"Query 1 failed: {e}")

    query2_results = []
    try:
        query2_results = kuzu_client.execute(
            "MATCH (p:Paper)-[:PROPOSES]->(m:Method) "
            "WHERE NOT EXISTS { MATCH (m)<-[:USES_SAME_METHOD]-(:Paper) } "
            "AND p.paper_id IN $pids "
            "RETURN m.name, p.title, p.pub_year",
            {"pids": paper_ids},
        )
    except Exception as e:
        logger.warning(f"Query 2 failed: {e}")

    query3_results = []
    try:
        query3_results = kuzu_client.execute(
            "MATCH (c:Claim)<-[:REFERENCES]-(p:Paper) "
            "WHERE p.paper_id IN $pids "
            "AND c.support_count = 0 AND c.contradict_count = 0 "
            "WITH c, count(p) AS ref_count WHERE ref_count >= 3 "
            "RETURN c.claim_id, c.text, ref_count",
            {"pids": paper_ids},
        )
    except Exception as e:
        logger.warning(f"Query 3 failed: {e}")

    query4_results = []
    try:
        query4_results = kuzu_client.execute(
            "MATCH (m:Method), (t:Task) "
            "WHERE NOT EXISTS { MATCH (m)-[:APPLIES_TO]->(t) } "
            "AND m.paper_count >= 2 AND t.paper_count >= 2 "
            "RETURN m.name, t.name AS untested_task LIMIT 10"
        )
    except Exception as e:
        logger.warning(f"Query 4 failed: {e}")

    topology_results = json.dumps({
        "claim_edge_counts": query1_results[:20],
        "orphan_methods": query2_results[:10],
        "untested_claims": query3_results[:10],
        "methods": query4_results[:10],
    }, indent=2)

    gap_candidates = []

    for claim in query1_results:
        degree = claim.get("degree", 0)
        sup = claim.get("c.support_count", 0) or 0
        contra = claim.get("c.contradict_count", 0) or 0

        rgs = compute_rgs(
            degree=degree,
            oldest_citing_year=None,
            method_centrality=0.5,
            support_count=sup,
            contradict_count=contra,
        )

        if rgs > 0.4:
            gap_candidates.append({
                "claim_id": claim.get("c.claim_id", ""),
                "claim_text": claim.get("c.text", ""),
                "rgs_score": rgs,
                "referenced_by_count": max(degree, 1),
                "referenced_by_papers": [claim.get("c.paper_id", "")],
                "support_count": sup,
                "contradict_count": contra,
                "source_query": "claim_edges",
            })

    for method in query2_results:
        gap_candidates.append({
            "claim_id": f"orphan_{hash(method.get('m.name', '')) % 100000}",
            "claim_text": f"Method '{method.get('m.name', '')}' proposed in '{method.get('p.title', '')}' has no cross-paper usage",
            "rgs_score": 0.7,
            "referenced_by_count": 1,
            "referenced_by_papers": [],
            "support_count": 0,
            "contradict_count": 0,
            "source_query": "orphan_methods",
        })

    for claim in query3_results:
        gap_candidates.append({
            "claim_id": claim.get("c.claim_id", ""),
            "claim_text": claim.get("c.text", ""),
            "rgs_score": 0.8,
            "referenced_by_count": claim.get("ref_count", 3),
            "referenced_by_papers": [],
            "support_count": 0,
            "contradict_count": 0,
            "source_query": "untested_claims",
        })

    gap_candidates = _deduplicate_gaps(gap_candidates)
    gap_candidates.sort(key=lambda g: g.get("rgs_score", 0), reverse=True)
    gap_candidates = gap_candidates[:10]

    judge_feedback = ""
    if memory_context:
        try:
            mem = json.loads(memory_context) if isinstance(memory_context, str) else memory_context
            if isinstance(mem, list):
                for item in reversed(mem):
                    if isinstance(item, dict) and item.get("verdict"):
                        judge_feedback = item["verdict"].get("feedback_for_agent", "")
                        break
        except (json.JSONDecodeError, TypeError):
            pass

    if gap_candidates:
        desc_prompt = AGENT_4_PROMPT.format(
            memory_context=memory_context[:2000] if memory_context else "No prior reports.",
            attempt=attempt,
            judge_feedback=judge_feedback if judge_feedback else "None.",
            paper_count=paper_count,
            user_id=user_id,
            topology_results=topology_results[:4000],
        )

        try:
            desc_response = await qwen_call(
                system_prompt=desc_prompt,
                user_message=f"Generate gap report for these {len(gap_candidates)} candidates:\n{json.dumps(gap_candidates[:10], indent=2)}",
                temperature=0.3,
                json_mode=True,
            )

            try:
                llm_result = json.loads(desc_response)
                if "gaps" in llm_result:
                    for i, gap in enumerate(llm_result["gaps"][:len(gap_candidates)]):
                        if i < len(gap_candidates):
                            gap_candidates[i]["human_description"] = gap.get("human_description", "")
                            gap_candidates[i]["suggested_investigation"] = gap.get("suggested_investigation", "")
                            gap_candidates[i]["related_methods"] = gap.get("related_methods", [])
            except (json.JSONDecodeError, KeyError):
                pass
        except Exception as e:
            logger.warning(f"Gap description synthesis unavailable, using deterministic copy: {e}")

    for gap in gap_candidates:
        gap["gap_type"] = classify_gap(
            rgs_score=gap.get("rgs_score", 0),
            ref_count=gap.get("referenced_by_count", 0),
            source_query=gap.get("source_query"),
        )
        gap["gap_id"] = f"gap_{gap_candidates.index(gap) + 1:03d}"
        gap.setdefault(
            "human_description",
            f"This area has limited direct support in the current corpus despite {gap.get('referenced_by_count', 0)} related references.",
        )
        gap.setdefault(
            "suggested_investigation",
            "Add at least one independent paper or experiment that tests this claim directly.",
        )
        gap.setdefault("related_methods", [])
        gap.pop("source_query", None)

    summary = {
        "critical_gaps": sum(1 for g in gap_candidates if g["gap_type"] == "critical_gap"),
        "moderate_gaps": sum(1 for g in gap_candidates if g["gap_type"] == "moderate_gap"),
        "orphan_methods": sum(1 for g in gap_candidates if g["gap_type"] == "orphan_method"),
        "methodology_gaps": sum(1 for g in gap_candidates if g["gap_type"] == "methodology_gap"),
    }

    gap_report = {
        "corpus_analyzed": paper_count,
        "gaps": gap_candidates,
        "summary": summary,
    }

    try:
        await cognee_client.remember(
            data=json.dumps(gap_report),
            metadata={
                "user_id": user_id,
                "type": "gap_report",
                "corpus_size": paper_count,
                "critical_gaps": summary["critical_gaps"],
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        logger.warning(f"Gap report memory write failed: {e}")

    logger.info(
        f"Gap detection complete: {len(gap_candidates)} gaps found ({summary['critical_gaps']} critical)"
    )

    return gap_report


def _deduplicate_gaps(gaps: list[dict]) -> list[dict]:
    """Deduplicate gaps using cosine similarity > 0.92."""
    if len(gaps) <= 1:
        return gaps

    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        seen = set()
        deduped = []
        for g in gaps:
            text = g.get("claim_text", "").lower().strip()
            if text not in seen:
                seen.add(text)
                deduped.append(g)
        return deduped

    texts = [g.get("claim_text", "") for g in gaps]
    embeddings = model.encode(texts)

    to_remove = set()
    for i in range(len(gaps)):
        if i in to_remove:
            continue
        for j in range(i + 1, len(gaps)):
            if j in to_remove:
                continue
            sim = float(np.dot(embeddings[i], embeddings[j]) / (
                np.linalg.norm(embeddings[i]) * np.linalg.norm(embeddings[j])
            ))
            if sim > GAP_DEDUP_COSINE:
                if gaps[i].get("rgs_score", 0) >= gaps[j].get("rgs_score", 0):
                    to_remove.add(j)
                else:
                    to_remove.add(i)

    return [g for i, g in enumerate(gaps) if i not in to_remove]

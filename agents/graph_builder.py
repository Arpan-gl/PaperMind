"""
PaperMind — Agent 2: Graph Builder (Δ operator)
Source: docs/agents.md (lines 192-301)

Trigger:  Agent 1 PASS
Input:    5-module JSON from Agent 1
Output:   Graph delta summary
PASS:     75 / 100

Implements Δ(G_u, p) — the Living Graph Update operator.
This is PaperMind's core novel contribution over Agents-K1.

Steps:
    1. Entity deduplication and merge (cosine > 0.88 methods, > 0.82 claims)
    2. Cross-paper edge creation (E_cross)
    3. Citation network from Module D
    4. RGS score recomputation

After KuzuDB operations: cognee.memify() stores the delta.
"""

import json
import uuid
import logging
from typing import Any, Optional
from datetime import datetime

import numpy as np

from core.openrouter_client import qwen_call
from core import cognee_client
from core import kuzu_client
from core.rgs_calculator import compute_rgs, compute_support_density, is_gap

logger = logging.getLogger("papermind.agent2")

# ── Similarity thresholds from agents.md ────────────────────────
METHOD_COSINE_THRESHOLD = 0.88
CLAIM_COSINE_THRESHOLD = 0.82
CONTRADICTION_CONFIDENCE_THRESHOLD = 0.75
SUPPORT_COSINE_THRESHOLD = 0.88
DEDUP_COSINE_THRESHOLD = 0.92

# ── System prompt (verbatim from agents.md lines 200-290) ───────
AGENT_2_PROMPT = """You are the Graph Builder in PaperMind. You implement Δ(G_u, p) — the Living Graph
Update operator. This is PaperMind's core novel contribution over Agents-K1.

Agents-K1 builds STATIC offline graphs.
PaperMind builds a LIVING graph — new paper p retroactively enriches existing G_u.

## Memory context:
{memory_context}
Attempt {attempt}. Feedback: {judge_feedback}

## Input (from PDF Analyst):
{agents_k1_json}

## STEP 1 — Entity deduplication and merge
For each entity in B_Textual + C_Implicit:
  cosine_similarity(entity, existing_node) > 0.88 (methods) or > 0.82 (claims)?
    YES → MERGE: update node, add evidence, increment paper_count
          PRESERVE stable node_id (Agents-K1 Proposition 1 — identifier-preserving)
    NO  → CREATE new node with fresh UUID

## STEP 2 — Cross-paper edge creation (E_cross — the novel contribution)
For each new Methodology node:
  Find existing with cosine > 0.88
  → CREATE (paper_new)-[:USES_SAME_METHOD {{similarity: $score}}]->(paper_existing)

For each new Claim node:
  Find existing with cosine > 0.82
  → Ask Qwen3: "Do these contradict? YES/NO + confidence"
  → confidence > 0.75 YES  : CREATE (C_new)-[:CONTRADICTS]->(C_existing)
  → cosine > 0.88 NO       : CREATE (C_new)-[:SUPPORTS]->(C_existing)

## STEP 3 — Citation network (from Module D)
  CREATE (paper_current)-[:CITES {{
    strength: $strength_score,
    cite_type: $cite_type,
    relation_role: $relation
  }}]->(paper_cited)

## STEP 4 — RGS score recomputation
For every Claim node affected:

  RGS(c) = 0.30 × (1 / max(degree(c), 1))
          + 0.20 × CitAge(c)
          + 0.30 × MethodCentrality(c)
          + 0.20 × (1 - SupportDensity(c))

  Update: SET c.rgs_score = $rgs, c.is_gap = ($rgs > 0.65 AND SupportDensity < 0.3)

## Output valid JSON:
{{
  "delta_summary": {{
    "nodes_created": <int>,
    "nodes_merged": <int>,
    "cross_paper_edges": <int>,
    "contradictions_detected": <int>,
    "rgs_nodes_updated": <int>,
    "new_gaps_flagged": <int>
  }},
  "new_gaps": [{{
    "claim_id": "",
    "claim_text": "",
    "rgs_score": <float>,
    "referenced_by": ["paper_id1"],
    "gap_type": "untested_claim|orphan_method|singleton_dataset"
  }}],
  "cypher_executed": ["MATCH...", "CREATE..."],
  "cognee_stored": true
}}"""


def _get_embedding_model():
    """Lazy-load sentence-transformers for entity deduplication."""
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as e:
        logger.warning(f"SentenceTransformer unavailable: {e}")
        return None


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(vec_a, vec_b)
    norm = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    return float(dot / norm) if norm > 0 else 0.0


async def agent_2_graph_builder(
    input_data: dict,
    memory_context: str,
    attempt: int,
    user_id: str,
) -> dict:
    """
    Agent 2: Graph Builder — Implements Δ(G_u, p).

    Called by agent_loop() — never directly.

    Args:
        input_data:     {"json": <5-module extraction from Agent 1>}
        memory_context: Prior attempts + judge feedback
        attempt:        Current attempt (1-3)
        user_id:        User ID for corpus scoping

    Returns:
        Delta summary dict.
    """
    extraction = input_data.get("json", {})
    paper_id = extraction.get("paper_id", f"unknown_{uuid.uuid4().hex[:8]}")

    # Counters for delta summary
    nodes_created = 0
    nodes_merged = 0
    cross_paper_edges = 0
    contradictions_detected = 0
    rgs_nodes_updated = 0
    new_gaps = []
    cypher_executed = []

    # Loading sentence-transformers is expensive. Delay it until there is an
    # existing entity to compare; the first paper needs no embedding model.
    model = None

    # ═══ STEP 1: Create Paper node ═══════════════════════════════
    meta = extraction.get("A_Meta", {})
    if not kuzu_client.node_exists("Paper", "paper_id", paper_id):
        kuzu_client.execute_write(
            "CREATE (p:Paper {paper_id: $pid, title: $title, pub_year: $year, "
            "venue: $venue, pdf_url: $url, user_id: $uid})",
            {
                "pid": paper_id,
                "title": meta.get("title", "Untitled"),
                "year": meta.get("pub_year", 0),
                "venue": meta.get("venue", ""),
                "url": meta.get("pdf_url", ""),
                "uid": user_id,
            },
        )
        nodes_created += 1
        cypher_executed.append(f"CREATE Paper {paper_id}")

    # ═══ STEP 1a: Authors ═══════════════════════════════════════
    for author in meta.get("authors", []):
        author_name = author.get("name", "")
        author_id = f"auth_{hash(author_name) % 100000}"
        if not kuzu_client.node_exists("Author", "author_id", author_id):
            kuzu_client.execute_write(
                "CREATE (a:Author {author_id: $aid, name: $name, affiliation: $aff})",
                {
                    "aid": author_id,
                    "name": author_name,
                    "aff": author.get("affiliation", ""),
                },
            )
            nodes_created += 1

        # AUTHORED_BY edge
        try:
            kuzu_client.execute_write(
                "MATCH (p:Paper {paper_id: $pid}), (a:Author {author_id: $aid}) "
                "CREATE (p)-[:AUTHORED_BY {ordering: $ord}]->(a)",
                {
                    "pid": paper_id,
                    "aid": author_id,
                    "ord": author.get("ordering", 0),
                },
            )
            cypher_executed.append(f"CREATE AUTHORED_BY {paper_id}->{author_id}")
        except Exception as e:
            logger.warning(f"AUTHORED_BY edge failed: {e}")

    # ═══ STEP 1b: Methods — dedup with cosine > 0.88 ═══════════
    textual = extraction.get("B_Textual", {})
    for method in textual.get("methods", []):
        method_name = method.get("name", "")
        if not method_name:
            continue

        # Check for existing methods
        existing_methods = kuzu_client.execute(
            "MATCH (p:Paper)-[:PROPOSES]->(m:Method) "
            "WHERE p.user_id = $uid AND p.paper_id <> $pid "
            "RETURN DISTINCT m.node_id, m.name",
            {"pid": paper_id, "uid": user_id},
        )

        merged = False
        if existing_methods and model is None:
            model = _get_embedding_model()
        if model and existing_methods:
            new_emb = model.encode([method_name])[0]
            for existing in existing_methods:
                existing_emb = model.encode([existing["m.name"]])[0]
                sim = _cosine_similarity(new_emb, existing_emb)
                if sim > METHOD_COSINE_THRESHOLD:
                    # MERGE — preserve stable node_id (Proposition 1)
                    kuzu_client.execute_write(
                        "MATCH (m:Method {node_id: $nid}) "
                        "SET m.paper_count = m.paper_count + 1",
                        {"nid": existing["m.node_id"]},
                    )
                    nodes_merged += 1
                    merged = True

                    # Cross-paper USES_SAME_METHOD edge
                    existing_papers = kuzu_client.execute(
                        "MATCH (p:Paper)-[:PROPOSES]->(m:Method {node_id: $nid}) "
                        "RETURN p.paper_id",
                        {"nid": existing["m.node_id"]},
                    )
                    for ep in existing_papers:
                        if ep["p.paper_id"] != paper_id:
                            try:
                                kuzu_client.execute_write(
                                    "MATCH (p1:Paper {paper_id: $pid1}), "
                                    "(p2:Paper {paper_id: $pid2}) "
                                    "CREATE (p1)-[:USES_SAME_METHOD "
                                    "{method_name: $mname, similarity: $sim}]->(p2)",
                                    {
                                        "pid1": paper_id,
                                        "pid2": ep["p.paper_id"],
                                        "mname": method_name,
                                        "sim": sim,
                                    },
                                )
                                cross_paper_edges += 1
                            except Exception:
                                pass
                    break

        if not merged:
            # CREATE new method node
            method_id = f"method_{uuid.uuid4().hex[:8]}"
            kuzu_client.execute_write(
                "CREATE (m:Method {node_id: $nid, name: $name, "
                "paper_count: $pc, aliases: $aliases})",
                {
                    "nid": method_id,
                    "name": method_name,
                    "pc": 1,
                    "aliases": method.get("aliases", []),
                },
            )
            nodes_created += 1

            # PROPOSES edge
            try:
                kuzu_client.execute_write(
                    "MATCH (p:Paper {paper_id: $pid}), (m:Method {node_id: $mid}) "
                    "CREATE (p)-[:PROPOSES]->(m)",
                    {"pid": paper_id, "mid": method_id},
                )
            except Exception as e:
                logger.warning(f"PROPOSES edge failed: {e}")

    # ═══ STEP 1c: Datasets ═══════════════════════════════════════
    for dataset in textual.get("datasets", []):
        ds_name = dataset.get("name", "")
        if not ds_name:
            continue
        ds_id = f"ds_{hash(ds_name) % 100000}"
        if not kuzu_client.node_exists("Dataset", "node_id", ds_id):
            kuzu_client.execute_write(
                "CREATE (d:Dataset {node_id: $nid, name: $name, "
                "year: $year, version: $ver})",
                {
                    "nid": ds_id,
                    "name": ds_name,
                    "year": dataset.get("year", 0),
                    "ver": dataset.get("version", ""),
                },
            )
            nodes_created += 1

        # USES_DATASET edge
        try:
            kuzu_client.execute_write(
                "MATCH (p:Paper {paper_id: $pid}), (d:Dataset {node_id: $did}) "
                "CREATE (p)-[:USES_DATASET]->(d)",
                {"pid": paper_id, "did": ds_id},
            )
        except Exception:
            pass

    # ═══ STEP 1d: Tasks ══════════════════════════════════════════
    for task in textual.get("tasks", []):
        task_name = task.get("name", "")
        if not task_name:
            continue
        task_id = f"task_{hash(task_name) % 100000}"
        if not kuzu_client.node_exists("Task", "node_id", task_id):
            kuzu_client.execute_write(
                "CREATE (t:Task {node_id: $nid, name: $name, paper_count: $pc})",
                {
                    "nid": task_id,
                    "name": task_name,
                    "pc": 1,
                },
            )
            nodes_created += 1

    # ═══ STEP 1e: APPLIES_TO relations ═══════════════════════════
    for rel in extraction.get("E_Relations", []):
        if (rel.get("head_type") == "Method" 
            and rel.get("tail_type") == "Task" 
            and rel.get("relation") == "APPLIED_TO"):
            
            m_name = rel.get("head", "")
            t_name = rel.get("tail", "")
            if m_name and t_name:
                try:
                    kuzu_client.execute_write(
                        "MATCH (m:Method), (t:Task) "
                        "WHERE m.name = $mname AND t.name = $tname "
                        "CREATE (m)-[:APPLIES_TO]->(t)",
                        {"mname": m_name, "tname": t_name}
                    )
                except Exception:
                    pass

    # ═══ STEP 1f: Claims from C_Implicit ═════════════════════════
    implicit = extraction.get("C_Implicit", {})
    contributions = implicit.get("contributions", {}).get("main_contributions", [])
    findings_q = implicit.get("findings", {}).get("quantitative", [])
    findings_ql = implicit.get("findings", {}).get("qualitative", [])

    all_claims = []
    for i, contrib in enumerate(contributions):
        all_claims.append({"text": str(contrib), "section": "contributions", "page": 0})
    for i, finding in enumerate(findings_q + findings_ql):
        all_claims.append({"text": str(finding), "section": "findings", "page": 0})

    claim_ids = []
    for claim_data in all_claims:
        claim_text = claim_data["text"]
        if not claim_text:
            continue

        claim_id = f"claim_{uuid.uuid4().hex[:8]}"

        # Every paper keeps its own provenance-bearing claim node. Similar
        # claims are connected below rather than referenced before creation.
        kuzu_client.execute_write(
            "CREATE (c:Claim {claim_id: $cid, text: $text, paper_id: $pid, "
            "section: $sec, page: $page, support_count: $sc, "
            "contradict_count: $cc, rgs_score: $rgs, "
            "support_density: $sd, is_gap: $gap})",
            {
                "cid": claim_id,
                "text": claim_text[:500],
                "pid": paper_id,
                "sec": claim_data["section"],
                "page": claim_data["page"],
                "sc": 0,
                "cc": 0,
                "rgs": 0.0,
                "sd": 0.0,
                "gap": False,
            },
        )
        nodes_created += 1

        # Check for existing claims (cosine > 0.82)
        existing_claims = kuzu_client.execute(
            "MATCH (p:Paper)-[:HAS_CLAIM]->(c:Claim) "
            "WHERE p.user_id = $uid AND c.claim_id <> $cid AND c.paper_id <> $pid "
            "RETURN c.claim_id, c.text, c.support_count, c.contradict_count",
            {"cid": claim_id, "pid": paper_id, "uid": user_id},
        )

        if existing_claims and model is None:
            model = _get_embedding_model()
        if model and existing_claims:
            new_emb = model.encode([claim_text])[0]
            for existing in existing_claims:
                if not existing.get("c.text"):
                    continue
                existing_emb = model.encode([existing["c.text"]])[0]
                sim = _cosine_similarity(new_emb, existing_emb)

                if sim > CLAIM_COSINE_THRESHOLD:
                    # Check contradiction via Qwen3
                    try:
                        contra_response = await qwen_call(
                            system_prompt="You are a scientific claim comparison judge. Return JSON.",
                            user_message=(
                                f'Do these claims contradict each other?\n'
                                f'Claim A: "{claim_text}"\n'
                                f'Claim B: "{existing["c.text"]}"\n'
                                f'Return: {{"contradicts": true/false, "confidence": 0.0-1.0}}'
                            ),
                            json_mode=True,
                            temperature=0.1,
                        )
                        contra = json.loads(contra_response)

                        if contra.get("contradicts") and contra.get("confidence", 0) > CONTRADICTION_CONFIDENCE_THRESHOLD:
                            # CONTRADICTS edge
                            kuzu_client.execute_write(
                                "MATCH (c1:Claim {claim_id: $cid1}), "
                                "(c2:Claim {claim_id: $cid2}) "
                                "CREATE (c1)-[:CONTRADICTS "
                                "{confidence: $conf, evidence_a: $ea, evidence_b: $eb}]->(c2)",
                                {
                                    "cid1": claim_id,
                                    "cid2": existing["c.claim_id"],
                                    "conf": contra["confidence"],
                                    "ea": claim_text[:200],
                                    "eb": existing["c.text"][:200],
                                },
                            )
                            contradictions_detected += 1
                            cross_paper_edges += 1
                        elif sim > SUPPORT_COSINE_THRESHOLD:
                            # SUPPORTS edge
                            kuzu_client.execute_write(
                                "MATCH (c1:Claim {claim_id: $cid1}), "
                                "(c2:Claim {claim_id: $cid2}) "
                                "CREATE (c1)-[:SUPPORTS {confidence: $conf}]->(c2)",
                                {
                                    "cid1": claim_id,
                                    "cid2": existing["c.claim_id"],
                                    "conf": sim,
                                },
                            )
                            cross_paper_edges += 1
                    except Exception as e:
                        logger.warning(f"Contradiction check failed: {e}")

                    break

        claim_ids.append(claim_id)

        # HAS_CLAIM edge
        try:
            kuzu_client.execute_write(
                "MATCH (p:Paper {paper_id: $pid}), (c:Claim {claim_id: $cid}) "
                "CREATE (p)-[:HAS_CLAIM {section: $sec, page: $page}]->(c)",
                {
                    "pid": paper_id,
                    "cid": claim_id,
                    "sec": claim_data["section"],
                    "page": claim_data["page"],
                },
            )
        except Exception as e:
            logger.warning(f"HAS_CLAIM edge failed: {e}")

    # ═══ STEP 3: Citation network from Module D ═════════════════
    d_citations = extraction.get("D_Citations", [])
    if isinstance(d_citations, dict):
        d_citations = d_citations.get("citations", [])

    for citation in d_citations:
        cited_title = citation.get("cited_title", "")
        if not cited_title:
            continue

        cited_paper_id = f"cited_{hash(cited_title) % 100000}"

        # Create stub paper node for cited work if not exists
        if not kuzu_client.node_exists("Paper", "paper_id", cited_paper_id):
            kuzu_client.execute_write(
                "CREATE (p:Paper {paper_id: $pid, title: $title, "
                "pub_year: $year, venue: $venue, pdf_url: $url, user_id: $uid})",
                {
                    "pid": cited_paper_id,
                    "title": cited_title,
                    "year": 0,
                    "venue": "",
                    "url": "",
                    "uid": user_id,
                },
            )

        # CITES edge
        try:
            kuzu_client.execute_write(
                "MATCH (p1:Paper {paper_id: $pid1}), (p2:Paper {paper_id: $pid2}) "
                "CREATE (p1)-[:CITES {strength: $str, cite_type: $ct, "
                "relation_role: $rr}]->(p2)",
                {
                    "pid1": paper_id,
                    "pid2": cited_paper_id,
                    "str": citation.get("strength_score", 1),
                    "ct": citation.get("cite_type", "Level1"),
                    "rr": citation.get("relation", "background"),
                },
            )
            cypher_executed.append(f"CREATE CITES {paper_id}->{cited_paper_id}")
        except Exception as e:
            logger.warning(f"CITES edge failed: {e}")

    # ═══ STEP 4: RGS score recomputation ═════════════════════════
    all_affected_claims = kuzu_client.execute(
        "MATCH (c:Claim) WHERE c.paper_id = $pid "
        "OPTIONAL MATCH (c)-[r]-() "
        "RETURN c.claim_id, c.text, c.support_count, c.contradict_count, "
        "count(r) AS degree",
        {"pid": paper_id},
    )

    for claim in all_affected_claims:
        degree = claim.get("degree", 0)
        sup_count = claim.get("c.support_count", 0) or 0
        contra_count = claim.get("c.contradict_count", 0) or 0

        rgs_score = compute_rgs(
            degree=degree,
            oldest_citing_year=meta.get("pub_year"),
            method_centrality=0.5,  # Default per formula
            support_count=sup_count,
            contradict_count=contra_count,
        )
        support_density = compute_support_density(sup_count, contra_count)
        claim_is_gap = is_gap(rgs_score, support_density)

        kuzu_client.execute_write(
            "MATCH (c:Claim {claim_id: $cid}) "
            "SET c.rgs_score = $rgs, c.support_density = $sd, c.is_gap = $gap",
            {
                "cid": claim["c.claim_id"],
                "rgs": rgs_score,
                "sd": support_density,
                "gap": claim_is_gap,
            },
        )
        rgs_nodes_updated += 1

        if claim_is_gap:
            new_gaps.append({
                "claim_id": claim["c.claim_id"],
                "claim_text": claim.get("c.text", ""),
                "rgs_score": rgs_score,
                "referenced_by": [paper_id],
                "gap_type": "untested_claim",
            })

    # ═══ STEP 5: Store delta in Cognee via memify() ══════════════
    delta_result = {
        "delta_summary": {
            "nodes_created": nodes_created,
            "nodes_merged": nodes_merged,
            "cross_paper_edges": cross_paper_edges,
            "contradictions_detected": contradictions_detected,
            "rgs_nodes_updated": rgs_nodes_updated,
            "new_gaps_flagged": len(new_gaps),
        },
        "new_gaps": new_gaps,
        "cypher_executed": cypher_executed,
        "cognee_stored": False,
    }

    if input_data.get("defer_cognee", False):
        logger.info(
            "Graph Builder committed Kuzu delta; Cognee sync deferred for paper %s",
            paper_id,
        )
        return delta_result

    # cognee.memify() — source: cognee_role.md lines 135-159
    stored = await cognee_client.memify(
        data={
            "paper_id": paper_id,
            "delta": {
                **delta_result["delta_summary"],
                "new_gaps": delta_result["new_gaps"]
            }
        },
        metadata={
            "user_id": user_id,
            "paper_id": paper_id,
            "type": "graph_delta",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    delta_result["cognee_stored"] = stored

    logger.info(
        f"Graph Builder complete: {nodes_created} created, {nodes_merged} merged, "
        f"{cross_paper_edges} cross-edges, {contradictions_detected} contradictions"
    )

    return delta_result

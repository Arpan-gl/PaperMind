"""
PaperMind — Agent 6: Loop Judge
Source: docs/agents.md (Agent 6 section, lines 591-641)

Meta-agent that evaluates every other agent's output against rubrics.
Returns PASS / RETRY(feedback) / PASS_PARTIAL.

CRITICAL: This is called by agent_loop() after EVERY agent run.
No agent output reaches the system without Loop Judge evaluation.

Rubrics (from agents.md):

Agent 1 (PDF Analyst) — PASS ≥ 80:
    A. A_Meta has paper_id + title + authors list + pub_year        → 20 pts
    B. B_Textual.methods has ≥ 2 items with components list         → 20 pts
    C. C_Implicit.motivation.existing_limitations non-empty list    → 20 pts
    D. D_Citations has ≥ 3 items, each with cite_type + strength    → 20 pts
    E. E_Relations has ≥ 3 items, each with evidence + conf ≥ 0.7  → 20 pts

Agent 2 (Graph Builder) — PASS ≥ 75:
    A. nodes_created + nodes_merged > 0     → 25 pts
    B. rgs_nodes_updated > 0                → 25 pts
    C. cognee_stored == true                → 25 pts
    D. new_gaps is a list (empty is OK)     → 25 pts

Agent 3 (Query Agent) — PASS ≥ 85:
    A. answer is non-empty string                                  → 20 pts
    B. citations list has ≥ 1 item                                 → 20 pts
    C. every citation has page(int)+section+paper_id+passage       → 25 pts
    D. unsourced_claims == []                                      → 25 pts
    E. graph_path is non-empty list                                → 10 pts

Agent 4 (Gap Agent) — PASS ≥ 75:
    A. gaps list ≥ 5 items (if corpus ≥ 10 papers)  → 25 pts
    B. all rgs_score > 0                             → 25 pts
    C. no duplicate gaps (cosine < 0.92)             → 20 pts
    D. every referenced_by_count ≥ 2                 → 15 pts
    E. every suggested_investigation non-empty       → 15 pts

Agent 5 (Novelty Judge) — PASS ≥ 75:
    (scored by Loop Judge using general quality criteria)
"""

import json
import logging
from typing import Any, Optional

from core.openrouter_client import qwen_call

logger = logging.getLogger("papermind.loop_judge")

# ── Pass thresholds from agents.md ──────────────────────────────
PASS_THRESHOLDS = {
    "agent_1_pdf_analyst": 80,
    "agent_2_graph_builder": 75,
    "agent_3_query_agent": 85,
    "agent_4_gap_agent": 75,
    "agent_5_novelty_judge": 75,
}

# ── Agent 6 System Prompt (verbatim from agents.md) ─────────────
LOOP_JUDGE_PROMPT = """You are the Loop Judge in PaperMind. Evaluate agent outputs against rubrics.
Return PASS or RETRY with precise field-level feedback.

## Input:
Agent: {agent_name}
Attempt: {attempt} of 3
Output: {output_json}

## Apply rubric for {agent_name} (see below for full rubrics)

{rubric_text}

## Feedback rules:
  BAD:  "Module E needs improvement"
  GOOD: "E_Relations[0].evidence is empty — re-extract verbatim span from paper"

  BAD:  "Citations are incomplete"
  GOOD: "D_Citations[1].strength_score is null — assign integer 1-5 from Appendix A"

  BAD:  "Answer has unsourced claims"
  GOOD: "Claim 'Graph RAG outperforms flat RAG' in paragraph 2 has no citation.
         Source from HippoRAG2 paper, results section."

## Output:
{{
  "agent": "{agent_name}",
  "attempt": {attempt},
  "score": <int 0-100>,
  "status": "PASS|RETRY|PASS_PARTIAL",
  "passed_checks": ["A", "B"],
  "failed_checks": [{{
    "check": "D",
    "field_path": "D_Citations[1].strength_score",
    "fix_instruction": "<exact fix quoting field path>"
  }}],
  "feedback_for_agent": "<≤ 150 words, specific>",
  "retry_priority": "high|medium|low"
}}

Rules:
- attempt == 3 and still failing → status = "PASS_PARTIAL"
- All checks pass → failed_checks = [], feedback = "All checks passed."
- Never give feedback > 200 words"""

# ── Rubric texts per agent ──────────────────────────────────────
RUBRICS = {
    "agent_1_pdf_analyst": """## Agent 1 — PDF Analyst Rubric (PASS ≥ 80):
A. A_Meta has paper_id + title + authors list + pub_year        → 20 pts
B. B_Textual.methods has ≥ 2 items with components list         → 20 pts
C. C_Implicit.motivation.existing_limitations non-empty list    → 20 pts
D. D_Citations has ≥ 3 items, each with cite_type + strength_score → 20 pts
E. E_Relations has ≥ 3 items, each with non-empty evidence + confidence ≥ 0.7 → 20 pts

PASS if score ≥ 80""",

    "agent_2_graph_builder": """## Agent 2 — Graph Builder Rubric (PASS ≥ 75):
A. nodes_created + nodes_merged > 0     → 25 pts
B. rgs_nodes_updated > 0                → 25 pts
C. cognee_stored == true                → 25 pts
D. new_gaps is a list (empty is OK)     → 25 pts

PASS if score ≥ 75""",

    "agent_3_query_agent": """## Agent 3 — Query Agent Rubric (PASS ≥ 85):
A. answer is non-empty string                                       → 20 pts
B. citations list has ≥ 1 item                                      → 20 pts
C. every citation has page (int) + section + paper_id + passage     → 25 pts
D. unsourced_claims == []                                           → 25 pts
E. graph_path is non-empty list                                     → 10 pts

PASS if score ≥ 85""",

    "agent_4_gap_agent": """## Agent 4 — Gap Agent Rubric (PASS ≥ 75):
A. gaps list ≥ 5 items (if corpus ≥ 10 papers)    → 25 pts
B. all rgs_score > 0                                → 25 pts
C. no duplicate gaps (cosine < 0.92)                → 20 pts
D. every referenced_by_count ≥ 2                    → 15 pts
E. every suggested_investigation non-empty          → 15 pts

PASS if score ≥ 75""",

    "agent_5_novelty_judge": """## Agent 5 — Novelty Judge Rubric (PASS ≥ 75):
A. scores object has coherence, credibility, feasibility, novelty, overall → 20 pts
B. similar_existing_work is non-empty list                                  → 20 pts
C. recommendation is one of "pursue|refine|pivot"                           → 20 pts
D. verdict is non-empty string                                              → 20 pts
E. improvement_suggestions is non-empty list                                → 20 pts

PASS if score ≥ 75""",
}


class LoopJudge:
    """
    Agent 6: Loop Judge.

    Evaluates every agent output against its rubric.
    Called by agent_loop() — no agent bypasses this.
    """

    async def evaluate(
        self,
        agent_name: str,
        output: Any,
        attempt: int,
    ) -> dict:
        """
        Evaluate an agent's output against its rubric.

        Args:
            agent_name: Function name of the agent (e.g., "agent_1_pdf_analyst").
            output:     The agent's output dict/JSON.
            attempt:    Current attempt number (1-3).

        Returns:
            Verdict dict with: agent, attempt, score, status,
            passed_checks, failed_checks, feedback_for_agent, retry_priority.
        """
        # First try deterministic (fast) scoring
        deterministic_verdict = self._score_deterministic(agent_name, output, attempt)

        if deterministic_verdict is not None:
            logger.info(
                f"Judge (deterministic): {agent_name} attempt {attempt} → "
                f"{deterministic_verdict['status']} ({deterministic_verdict['score']})"
            )
            return deterministic_verdict

        # Fall back to LLM-based scoring for complex cases
        return await self._score_with_llm(agent_name, output, attempt)

    def _score_deterministic(
        self,
        agent_name: str,
        output: Any,
        attempt: int,
    ) -> Optional[dict]:
        """
        Score output deterministically using rubric rules.
        Returns None if LLM scoring is needed.
        """
        threshold = PASS_THRESHOLDS.get(agent_name, 75)

        if agent_name == "agent_1_pdf_analyst":
            return self._score_agent_1(output, attempt, threshold)
        elif agent_name == "agent_2_graph_builder":
            return self._score_agent_2(output, attempt, threshold)
        elif agent_name == "agent_3_query_agent":
            return self._score_agent_3(output, attempt, threshold)
        elif agent_name == "agent_4_gap_agent":
            return self._score_agent_4(output, attempt, threshold)
        elif agent_name == "agent_5_novelty_judge":
            return self._score_agent_5(output, attempt, threshold)

        return None

    def _score_agent_1(self, output: dict, attempt: int, threshold: int) -> dict:
        """
        Agent 1 rubric:
            A. A_Meta has paper_id + title + authors list + pub_year  → 20 pts
            B. B_Textual.methods has ≥ 2 items with components       → 20 pts
            C. C_Implicit.motivation.existing_limitations non-empty   → 20 pts
            D. D_Citations has ≥ 3 items with cite_type + strength   → 20 pts
            E. E_Relations has ≥ 3 items with evidence + conf ≥ 0.7  → 20 pts
        """
        score = 0
        passed = []
        failed = []

        # Check A: A_Meta
        meta = output.get("A_Meta", {})
        if (meta.get("paper_id") and meta.get("title")
                and isinstance(meta.get("authors"), list) and len(meta.get("authors", [])) > 0
                and meta.get("pub_year")):
            score += 20
            passed.append("A")
        else:
            missing = []
            if not meta.get("paper_id"):
                missing.append("paper_id")
            if not meta.get("title"):
                missing.append("title")
            if not isinstance(meta.get("authors"), list) or len(meta.get("authors", [])) == 0:
                missing.append("authors list")
            if not meta.get("pub_year"):
                missing.append("pub_year")
            failed.append({
                "check": "A",
                "field_path": f"A_Meta.{missing[0] if missing else 'unknown'}",
                "fix_instruction": f"A_Meta is missing: {', '.join(missing)}. Extract exact values from paper header."
            })

        # Check B: B_Textual.methods
        textual = output.get("B_Textual", {})
        methods = textual.get("methods", [])
        methods_with_components = [m for m in methods if isinstance(m.get("components"), list)]
        if len(methods_with_components) >= 2:
            score += 20
            passed.append("B")
        else:
            failed.append({
                "check": "B",
                "field_path": "B_Textual.methods",
                "fix_instruction": f"B_Textual.methods has {len(methods_with_components)} items with components (need ≥ 2). Add components list to each method."
            })

        # Check C: C_Implicit.motivation.existing_limitations
        implicit = output.get("C_Implicit", {})
        motivation = implicit.get("motivation", {})
        limitations = motivation.get("existing_limitations", [])
        if isinstance(limitations, list) and len(limitations) > 0:
            score += 20
            passed.append("C")
        else:
            failed.append({
                "check": "C",
                "field_path": "C_Implicit.motivation.existing_limitations",
                "fix_instruction": "C_Implicit.motivation.existing_limitations is empty — extract at least 1 limitation from the paper's introduction or related work section."
            })

        # Check D: D_Citations
        citations = output.get("D_Citations", [])
        valid_citations = [
            c for c in citations
            if c.get("cite_type") and c.get("strength_score") is not None
        ]
        if len(valid_citations) >= 3:
            score += 20
            passed.append("D")
        else:
            bad_indices = [
                i for i, c in enumerate(citations)
                if not c.get("cite_type") or c.get("strength_score") is None
            ]
            failed.append({
                "check": "D",
                "field_path": f"D_Citations[{bad_indices[0] if bad_indices else '?'}]",
                "fix_instruction": f"D_Citations has {len(valid_citations)} valid items (need ≥ 3). Each must have cite_type (Level1-5) and strength_score (integer 1-5)."
            })

        # Check E: E_Relations
        relations = output.get("E_Relations", [])
        valid_relations = [
            r for r in relations
            if r.get("evidence") and r.get("confidence", 0) >= 0.7
        ]
        if len(valid_relations) >= 3:
            score += 20
            passed.append("E")
        else:
            bad_rels = [
                i for i, r in enumerate(relations)
                if not r.get("evidence") or r.get("confidence", 0) < 0.7
            ]
            failed.append({
                "check": "E",
                "field_path": f"E_Relations[{bad_rels[0] if bad_rels else '?'}]",
                "fix_instruction": f"E_Relations has {len(valid_relations)} valid items (need ≥ 3). Each must have non-empty evidence (verbatim span) and confidence ≥ 0.7."
            })

        return self._build_verdict(
            agent_name="agent_1_pdf_analyst",
            score=score, passed=passed, failed=failed,
            attempt=attempt, threshold=threshold
        )

    def _score_agent_2(self, output: dict, attempt: int, threshold: int) -> dict:
        """
        Agent 2 rubric:
            A. nodes_created + nodes_merged > 0 → 25 pts
            B. rgs_nodes_updated > 0            → 25 pts
            C. cognee_stored == true            → 25 pts
            D. new_gaps is a list               → 25 pts
        """
        score = 0
        passed = []
        failed = []
        delta = output.get("delta_summary", {})

        # A
        created = delta.get("nodes_created", 0)
        merged = delta.get("nodes_merged", 0)
        if (created + merged) > 0:
            score += 25
            passed.append("A")
        else:
            failed.append({
                "check": "A",
                "field_path": "delta_summary.nodes_created",
                "fix_instruction": "nodes_created + nodes_merged = 0 — at least one entity must be created or merged from the paper extraction."
            })

        # B
        if delta.get("rgs_nodes_updated", 0) > 0:
            score += 25
            passed.append("B")
        else:
            failed.append({
                "check": "B",
                "field_path": "delta_summary.rgs_nodes_updated",
                "fix_instruction": "rgs_nodes_updated = 0 — RGS must be recomputed for all affected claim nodes after graph update."
            })

        # C
        if output.get("cognee_stored") is True:
            score += 25
            passed.append("C")
        else:
            failed.append({
                "check": "C",
                "field_path": "cognee_stored",
                "fix_instruction": "cognee_stored is not true — call cognee.memify() after all KuzuDB operations complete."
            })

        # D
        if isinstance(output.get("new_gaps"), list):
            score += 25
            passed.append("D")
        else:
            failed.append({
                "check": "D",
                "field_path": "new_gaps",
                "fix_instruction": "new_gaps must be a list (empty list is acceptable if no gaps found)."
            })

        return self._build_verdict(
            agent_name="agent_2_graph_builder",
            score=score, passed=passed, failed=failed,
            attempt=attempt, threshold=threshold
        )

    def _score_agent_3(self, output: dict, attempt: int, threshold: int) -> dict:
        """
        Agent 3 rubric:
            A. answer is non-empty string           → 20 pts
            B. citations list has ≥ 1 item          → 20 pts
            C. every citation has page+section+...  → 25 pts
            D. unsourced_claims == []               → 25 pts
            E. graph_path is non-empty list         → 10 pts
        """
        score = 0
        passed = []
        failed = []

        # A
        answer = output.get("answer", "")
        if isinstance(answer, str) and len(answer.strip()) > 0:
            score += 20
            passed.append("A")
        else:
            failed.append({
                "check": "A",
                "field_path": "answer",
                "fix_instruction": "answer is empty — provide a substantive answer with inline citations."
            })

        # B
        citations = output.get("citations", [])
        if isinstance(citations, list) and len(citations) >= 1:
            score += 20
            passed.append("B")
        else:
            failed.append({
                "check": "B",
                "field_path": "citations",
                "fix_instruction": "citations list is empty — every claim in the answer must have a corresponding citation object."
            })

        # C
        if citations:
            all_valid = all(
                isinstance(c.get("page"), int)
                and c.get("section")
                and c.get("paper_id")
                and c.get("passage")
                for c in citations
            )
            if all_valid:
                score += 25
                passed.append("C")
            else:
                bad = next(
                    (i for i, c in enumerate(citations)
                     if not isinstance(c.get("page"), int)
                     or not c.get("section")
                     or not c.get("paper_id")
                     or not c.get("passage")),
                    0
                )
                c = citations[bad] if bad < len(citations) else {}
                missing = []
                if not isinstance(c.get("page"), int):
                    missing.append("page (must be int)")
                if not c.get("section"):
                    missing.append("section")
                if not c.get("paper_id"):
                    missing.append("paper_id")
                if not c.get("passage"):
                    missing.append("passage")
                failed.append({
                    "check": "C",
                    "field_path": f"citations[{bad}]",
                    "fix_instruction": f"Citation {bad} missing: {', '.join(missing)}. Page must be integer, passage must be ≤ 25 words verbatim."
                })
        else:
            failed.append({
                "check": "C",
                "field_path": "citations",
                "fix_instruction": "No citations to validate — add at least one citation first."
            })

        # D
        unsourced = output.get("unsourced_claims", None)
        if isinstance(unsourced, list) and len(unsourced) == 0:
            score += 25
            passed.append("D")
        else:
            failed.append({
                "check": "D",
                "field_path": "unsourced_claims",
                "fix_instruction": f"unsourced_claims must be [] — found {unsourced}. Source each claim or remove it from the answer."
            })

        # E
        graph_path = output.get("graph_path", [])
        if isinstance(graph_path, list) and len(graph_path) > 0:
            score += 10
            passed.append("E")
        else:
            failed.append({
                "check": "E",
                "field_path": "graph_path",
                "fix_instruction": "graph_path is empty — include the traversal path used [node_id, EDGE_TYPE, node_id]."
            })

        return self._build_verdict(
            agent_name="agent_3_query_agent",
            score=score, passed=passed, failed=failed,
            attempt=attempt, threshold=threshold
        )

    def _score_agent_4(self, output: dict, attempt: int, threshold: int) -> dict:
        """
        Agent 4 rubric:
            A. gaps list ≥ 5 items (if corpus ≥ 10)  → 25 pts
            B. all rgs_score > 0                      → 25 pts
            C. no duplicate gaps                      → 20 pts
            D. every referenced_by_count ≥ 2          → 15 pts
            E. every suggested_investigation non-empty → 15 pts
        """
        score = 0
        passed = []
        failed = []

        gaps = output.get("gaps", [])
        corpus_size = output.get("corpus_analyzed", 0)

        # A — adjusted for small corpus
        min_gaps = 5 if corpus_size >= 10 else max(1, corpus_size // 2)
        if len(gaps) >= min_gaps:
            score += 25
            passed.append("A")
        else:
            failed.append({
                "check": "A",
                "field_path": "gaps",
                "fix_instruction": f"gaps has {len(gaps)} items (need ≥ {min_gaps} for corpus of {corpus_size}). Run all 4 topology queries."
            })

        # B
        all_positive = all(g.get("rgs_score", 0) > 0 for g in gaps) if gaps else False
        if all_positive:
            score += 25
            passed.append("B")
        else:
            bad = next((i for i, g in enumerate(gaps) if g.get("rgs_score", 0) <= 0), 0)
            failed.append({
                "check": "B",
                "field_path": f"gaps[{bad}].rgs_score",
                "fix_instruction": f"gaps[{bad}].rgs_score is ≤ 0 — recompute using RGS formula with correct inputs."
            })

        # C — basic dedup check (cosine check happens at runtime)
        seen_texts = set()
        has_dupes = False
        for g in gaps:
            text = g.get("claim_text", "").lower().strip()
            if text in seen_texts:
                has_dupes = True
                break
            seen_texts.add(text)
        if not has_dupes:
            score += 20
            passed.append("C")
        else:
            failed.append({
                "check": "C",
                "field_path": "gaps",
                "fix_instruction": "Duplicate gap texts found — deduplicate using cosine > 0.92 threshold, keep higher RGS."
            })

        # D
        all_refs_ok = all(g.get("referenced_by_count", 0) >= 2 for g in gaps) if gaps else False
        if all_refs_ok:
            score += 15
            passed.append("D")
        else:
            bad = next((i for i, g in enumerate(gaps) if g.get("referenced_by_count", 0) < 2), 0)
            failed.append({
                "check": "D",
                "field_path": f"gaps[{bad}].referenced_by_count",
                "fix_instruction": f"gaps[{bad}].referenced_by_count < 2 — only include gaps referenced by ≥ 2 papers."
            })

        # E
        all_suggestions = all(
            g.get("suggested_investigation", "").strip() for g in gaps
        ) if gaps else False
        if all_suggestions:
            score += 15
            passed.append("E")
        else:
            bad = next(
                (i for i, g in enumerate(gaps) if not g.get("suggested_investigation", "").strip()),
                0
            )
            failed.append({
                "check": "E",
                "field_path": f"gaps[{bad}].suggested_investigation",
                "fix_instruction": f"gaps[{bad}].suggested_investigation is empty — provide a specific, actionable research suggestion."
            })

        return self._build_verdict(
            agent_name="agent_4_gap_agent",
            score=score, passed=passed, failed=failed,
            attempt=attempt, threshold=threshold
        )

    def _score_agent_5(self, output: dict, attempt: int, threshold: int) -> dict:
        """
        Agent 5 rubric:
            A. scores has all 5 dimensions  → 20 pts
            B. similar_existing_work        → 20 pts
            C. recommendation valid         → 20 pts
            D. verdict non-empty            → 20 pts
            E. improvement_suggestions      → 20 pts
        """
        score = 0
        passed = []
        failed = []

        # A
        scores = output.get("scores", {})
        required_dims = ["coherence", "credibility", "feasibility", "novelty", "overall"]
        has_all = all(dim in scores for dim in required_dims)
        if has_all:
            score += 20
            passed.append("A")
        else:
            missing = [d for d in required_dims if d not in scores]
            failed.append({
                "check": "A",
                "field_path": f"scores.{missing[0]}",
                "fix_instruction": f"scores missing dimensions: {', '.join(missing)}. Score each 0-1."
            })

        # B
        similar = output.get("similar_existing_work", [])
        if isinstance(similar, list) and len(similar) > 0:
            score += 20
            passed.append("B")
        else:
            failed.append({
                "check": "B",
                "field_path": "similar_existing_work",
                "fix_instruction": "similar_existing_work is empty — find at least 1 related paper from the corpus."
            })

        # C
        rec = output.get("recommendation", "")
        if rec in ("pursue", "refine", "pivot"):
            score += 20
            passed.append("C")
        else:
            failed.append({
                "check": "C",
                "field_path": "recommendation",
                "fix_instruction": f"recommendation is '{rec}' — must be one of: pursue, refine, pivot."
            })

        # D
        verdict = output.get("verdict", "")
        if isinstance(verdict, str) and len(verdict.strip()) > 0:
            score += 20
            passed.append("D")
        else:
            failed.append({
                "check": "D",
                "field_path": "verdict",
                "fix_instruction": "verdict is empty — provide a 2-3 sentence summary."
            })

        # E
        suggestions = output.get("improvement_suggestions", [])
        if isinstance(suggestions, list) and len(suggestions) > 0:
            score += 20
            passed.append("E")
        else:
            failed.append({
                "check": "E",
                "field_path": "improvement_suggestions",
                "fix_instruction": "improvement_suggestions is empty — suggest at least 1 concrete improvement."
            })

        return self._build_verdict(
            agent_name="agent_5_novelty_judge",
            score=score, passed=passed, failed=failed,
            attempt=attempt, threshold=threshold
        )

    async def _score_with_llm(
        self,
        agent_name: str,
        output: Any,
        attempt: int,
    ) -> dict:
        """Fall back to LLM-based scoring for edge cases."""
        rubric_text = RUBRICS.get(agent_name, "Apply general quality criteria.")
        threshold = PASS_THRESHOLDS.get(agent_name, 75)

        output_json = json.dumps(output, indent=2) if isinstance(output, dict) else str(output)

        prompt = LOOP_JUDGE_PROMPT.format(
            agent_name=agent_name,
            attempt=attempt,
            output_json=output_json[:4000],  # Truncate for token budget
            rubric_text=rubric_text,
        )

        try:
            response = await qwen_call(
                system_prompt=prompt,
                user_message="Evaluate this output against the rubric. Return JSON verdict.",
                temperature=0.1,
                json_mode=True,
            )
            verdict = json.loads(response)

            # Enforce PASS_PARTIAL on attempt 3
            if attempt >= 3 and verdict.get("score", 0) < threshold:
                verdict["status"] = "PASS_PARTIAL"

            logger.info(
                f"Judge (LLM): {agent_name} attempt {attempt} → "
                f"{verdict.get('status')} ({verdict.get('score')})"
            )
            return verdict

        except Exception as e:
            logger.error(f"LLM judge failed for {agent_name}: {e}")
            # Safe fallback — let the output through on attempt 3
            return self._build_verdict(
                agent_name=agent_name,
                score=0, passed=[], failed=[{
                    "check": "JUDGE_ERROR",
                    "field_path": "",
                    "fix_instruction": f"Loop Judge encountered an error: {str(e)}"
                }],
                attempt=attempt, threshold=threshold
            )

    def _build_verdict(
        self,
        agent_name: str,
        score: int,
        passed: list,
        failed: list,
        attempt: int,
        threshold: int,
    ) -> dict:
        """
        Build the standard verdict dict.

        Status logic from agents.md:
            score >= threshold     → PASS
            attempt == 3 + failing → PASS_PARTIAL
            otherwise              → RETRY
        """
        if score >= threshold:
            status = "PASS"
        elif attempt >= 3:
            status = "PASS_PARTIAL"
        else:
            status = "RETRY"

        # Determine retry priority
        if not failed:
            priority = "low"
            feedback = "All checks passed."
        elif score < threshold * 0.5:
            priority = "high"
            feedback = " | ".join(
                f"{f['check']}: {f['fix_instruction']}" for f in failed[:3]
            )
        else:
            priority = "medium"
            feedback = " | ".join(
                f"{f['check']}: {f['fix_instruction']}" for f in failed[:3]
            )

        # Truncate feedback to ≤ 200 words per agents.md rule
        words = feedback.split()
        if len(words) > 200:
            feedback = " ".join(words[:200]) + "..."

        return {
            "agent": agent_name,
            "attempt": attempt,
            "score": score,
            "status": status,
            "passed_checks": passed,
            "failed_checks": failed,
            "feedback_for_agent": feedback,
            "retry_priority": priority,
        }

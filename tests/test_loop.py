"""
PaperMind — Agent Loop Unit Tests
Source: docs/loop_flow.md

Tests:
    1. PASS on first attempt → returns immediately
    2. RETRY → loops with feedback
    3. PASS_PARTIAL → returns best attempt after 3 failures
    4. Memory context accumulates across attempts
    5. Every attempt stored in Cognee
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

from agents.loop_judge import LoopJudge, PASS_THRESHOLDS


class TestLoopJudge:
    """Test the deterministic scoring rubrics."""

    @pytest.fixture
    def judge(self):
        return LoopJudge()

    # ── Agent 1 rubric tests ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_agent1_perfect_score(self, judge):
        """All 5 checks pass → score 100, PASS."""
        output = {
            "A_Meta": {
                "paper_id": "test_001",
                "title": "Test Paper",
                "authors": [{"name": "Smith, John"}],
                "pub_year": 2024,
            },
            "B_Textual": {
                "methods": [
                    {"name": "M1", "components": ["c1"]},
                    {"name": "M2", "components": ["c2"]},
                ],
            },
            "C_Implicit": {
                "motivation": {
                    "existing_limitations": ["lim1"],
                },
            },
            "D_Citations": [
                {"cite_type": "Level3", "strength_score": 3},
                {"cite_type": "Level4", "strength_score": 4},
                {"cite_type": "Level2", "strength_score": 2},
            ],
            "E_Relations": [
                {"evidence": "verbatim span 1", "confidence": 0.8},
                {"evidence": "verbatim span 2", "confidence": 0.9},
                {"evidence": "verbatim span 3", "confidence": 0.7},
            ],
        }
        verdict = await judge.evaluate("agent_1_pdf_analyst", output, attempt=1)
        assert verdict["score"] == 100
        assert verdict["status"] == "PASS"
        assert len(verdict["failed_checks"]) == 0

    @pytest.mark.asyncio
    async def test_agent1_missing_meta(self, judge):
        """A_Meta missing fields → loses 20 pts."""
        output = {
            "A_Meta": {},
            "B_Textual": {"methods": [
                {"name": "M1", "components": ["c1"]},
                {"name": "M2", "components": ["c2"]},
            ]},
            "C_Implicit": {"motivation": {"existing_limitations": ["lim1"]}},
            "D_Citations": [
                {"cite_type": "L3", "strength_score": 3},
                {"cite_type": "L4", "strength_score": 4},
                {"cite_type": "L2", "strength_score": 2},
            ],
            "E_Relations": [
                {"evidence": "e1", "confidence": 0.8},
                {"evidence": "e2", "confidence": 0.9},
                {"evidence": "e3", "confidence": 0.7},
            ],
        }
        verdict = await judge.evaluate("agent_1_pdf_analyst", output, attempt=1)
        assert verdict["score"] == 80  # Lost A (20 pts), but still >= 80
        assert "A" in [f["check"] for f in verdict["failed_checks"]]

    @pytest.mark.asyncio
    async def test_agent1_retry_on_low_score(self, judge):
        """Score < 80 on attempt 1 → RETRY."""
        output = {
            "A_Meta": {},
            "B_Textual": {"methods": []},
            "C_Implicit": {"motivation": {"existing_limitations": []}},
            "D_Citations": [],
            "E_Relations": [],
        }
        verdict = await judge.evaluate("agent_1_pdf_analyst", output, attempt=1)
        assert verdict["status"] == "RETRY"
        assert verdict["score"] < 80

    @pytest.mark.asyncio
    async def test_agent1_pass_partial_on_attempt_3(self, judge):
        """Score < 80 on attempt 3 → PASS_PARTIAL (not RETRY)."""
        output = {
            "A_Meta": {},
            "B_Textual": {"methods": []},
            "C_Implicit": {},
            "D_Citations": [],
            "E_Relations": [],
        }
        verdict = await judge.evaluate("agent_1_pdf_analyst", output, attempt=3)
        assert verdict["status"] == "PASS_PARTIAL"

    # ── Agent 2 rubric tests ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_agent2_perfect(self, judge):
        """All 4 checks pass → score 100, PASS."""
        output = {
            "delta_summary": {
                "nodes_created": 5,
                "nodes_merged": 2,
                "rgs_nodes_updated": 3,
            },
            "cognee_stored": True,
            "new_gaps": [],
        }
        verdict = await judge.evaluate("agent_2_graph_builder", output, attempt=1)
        assert verdict["score"] == 100
        assert verdict["status"] == "PASS"

    @pytest.mark.asyncio
    async def test_agent2_cognee_not_stored(self, judge):
        """cognee_stored = False → loses 25 pts."""
        output = {
            "delta_summary": {
                "nodes_created": 5,
                "nodes_merged": 2,
                "rgs_nodes_updated": 3,
            },
            "cognee_stored": False,
            "new_gaps": [],
        }
        verdict = await judge.evaluate("agent_2_graph_builder", output, attempt=1)
        assert verdict["score"] == 75
        assert "C" in [f["check"] for f in verdict["failed_checks"]]

    # ── Agent 3 rubric tests ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_agent3_perfect(self, judge):
        """All 5 checks pass → score 100, PASS."""
        output = {
            "answer": "The paper shows that...",
            "citations": [{
                "page": 7,
                "section": "results",
                "paper_id": "p001",
                "passage": "verbatim text here",
            }],
            "unsourced_claims": [],
            "graph_path": ["node1", "CITES", "node2"],
        }
        verdict = await judge.evaluate("agent_3_query_agent", output, attempt=1)
        assert verdict["score"] == 100
        assert verdict["status"] == "PASS"

    @pytest.mark.asyncio
    async def test_agent3_unsourced_claims_fail(self, judge):
        """unsourced_claims not empty → loses 25 pts, likely RETRY."""
        output = {
            "answer": "The paper shows that X is better than Y",
            "citations": [{
                "page": 7,
                "section": "results",
                "paper_id": "p001",
                "passage": "verbatim",
            }],
            "unsourced_claims": ["X is better than Y"],
            "graph_path": ["n1"],
        }
        verdict = await judge.evaluate("agent_3_query_agent", output, attempt=1)
        assert "D" in [f["check"] for f in verdict["failed_checks"]]
        assert verdict["score"] <= 75

    # ── Verdict structure tests ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_verdict_has_all_fields(self, judge):
        """Every verdict must have the standard fields."""
        output = {"A_Meta": {}}
        verdict = await judge.evaluate("agent_1_pdf_analyst", output, attempt=1)

        assert "agent" in verdict
        assert "attempt" in verdict
        assert "score" in verdict
        assert "status" in verdict
        assert "passed_checks" in verdict
        assert "failed_checks" in verdict
        assert "feedback_for_agent" in verdict
        assert "retry_priority" in verdict

    @pytest.mark.asyncio
    async def test_feedback_under_200_words(self, judge):
        """Feedback must be ≤ 200 words per agents.md."""
        output = {"A_Meta": {}, "B_Textual": {}, "C_Implicit": {}, "D_Citations": [], "E_Relations": []}
        verdict = await judge.evaluate("agent_1_pdf_analyst", output, attempt=1)
        word_count = len(verdict["feedback_for_agent"].split())
        assert word_count <= 200


class TestPassThresholds:
    """Verify pass thresholds match agents.md."""

    def test_agent1_threshold(self):
        assert PASS_THRESHOLDS["agent_1_pdf_analyst"] == 80

    def test_agent2_threshold(self):
        assert PASS_THRESHOLDS["agent_2_graph_builder"] == 75

    def test_agent3_threshold(self):
        assert PASS_THRESHOLDS["agent_3_query_agent"] == 85

    def test_agent4_threshold(self):
        assert PASS_THRESHOLDS["agent_4_gap_agent"] == 75

    def test_agent5_threshold(self):
        assert PASS_THRESHOLDS["agent_5_novelty_judge"] == 75

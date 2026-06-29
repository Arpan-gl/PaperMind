"""
PaperMind — RGS Calculator Unit Tests
Source: docs/agents.md (Agent 2 STEP 4, Agent 4 STEP 2)

Tests the Research Gap Score formula:
    RGS(c) = 0.30 × (1/max(degree(c),1))
            + 0.20 × CitAge(c)
            + 0.30 × MethodCentrality(c)
            + 0.20 × (1 - SupportDensity(c))
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.rgs_calculator import (
    compute_rgs,
    compute_support_density,
    compute_cit_age,
    compute_degree_score,
    is_gap,
    classify_gap,
    compute_rgs_batch,
    W_DEGREE,
    W_CIT_AGE,
    W_METHOD_CENTRALITY,
    W_SUPPORT_DENSITY,
)


class TestWeights:
    """Verify weights match agents.md exactly."""

    def test_weights_sum_to_one(self):
        assert W_DEGREE + W_CIT_AGE + W_METHOD_CENTRALITY + W_SUPPORT_DENSITY == 1.0

    def test_degree_weight(self):
        assert W_DEGREE == 0.30

    def test_cit_age_weight(self):
        assert W_CIT_AGE == 0.20

    def test_method_centrality_weight(self):
        assert W_METHOD_CENTRALITY == 0.30

    def test_support_density_weight(self):
        assert W_SUPPORT_DENSITY == 0.20


class TestSupportDensity:
    """SupportDensity(c) = support_count / (support_count + contradict_count + 1)"""

    def test_zero_evidence(self):
        """No support or contradiction → density = 0.0"""
        assert compute_support_density(0, 0) == 0.0

    def test_only_supports(self):
        """5 supports, 0 contradictions → 5/6 ≈ 0.833"""
        result = compute_support_density(5, 0)
        assert abs(result - 5 / 6) < 0.001

    def test_only_contradictions(self):
        """0 supports, 3 contradictions → 0/4 = 0.0"""
        assert compute_support_density(0, 3) == 0.0

    def test_mixed(self):
        """3 supports, 2 contradictions → 3/6 = 0.5"""
        assert compute_support_density(3, 2) == 0.5

    def test_denominator_never_zero(self):
        """The +1 prevents division by zero."""
        result = compute_support_density(0, 0)
        assert result == 0.0  # 0 / (0 + 0 + 1)


class TestCitAge:
    """CitAge(c) = (2025 - oldest_citing_year) / 10, capped at 1.0"""

    def test_recent_paper(self):
        """2024 paper → (2025-2024)/10 = 0.1"""
        assert compute_cit_age(2024) == 0.1

    def test_old_paper(self):
        """2015 paper → (2025-2015)/10 = 1.0"""
        assert compute_cit_age(2015) == 1.0

    def test_very_old_paper(self):
        """2000 paper → (2025-2000)/10 = 2.5 → capped at 1.0"""
        assert compute_cit_age(2000) == 1.0

    def test_future_paper(self):
        """2026 paper → negative → clamped to 0.0"""
        assert compute_cit_age(2026) == 0.0

    def test_none_year(self):
        """No citing year → default 0.5"""
        assert compute_cit_age(None) == 0.5


class TestDegreeScore:
    """Degree component = 1 / max(degree, 1)"""

    def test_zero_degree(self):
        """Isolated node → 1/1 = 1.0"""
        assert compute_degree_score(0) == 1.0

    def test_degree_one(self):
        """Single edge → 1/1 = 1.0"""
        assert compute_degree_score(1) == 1.0

    def test_high_degree(self):
        """10 edges → 1/10 = 0.1"""
        assert compute_degree_score(10) == 0.1

    def test_degree_five(self):
        """5 edges → 1/5 = 0.2"""
        assert compute_degree_score(5) == 0.2


class TestComputeRGS:
    """Full RGS computation."""

    def test_maximum_gap_score(self):
        """Isolated claim, old, connected to central method, no support."""
        rgs = compute_rgs(
            degree=0,
            oldest_citing_year=2010,
            method_centrality=1.0,
            support_count=0,
            contradict_count=0,
        )
        # 0.30 × 1.0 + 0.20 × 1.0 + 0.30 × 1.0 + 0.20 × 1.0 = 1.0
        assert rgs == 1.0

    def test_minimum_gap_score(self):
        """Well-connected, recent, peripheral method, well-supported."""
        rgs = compute_rgs(
            degree=100,
            oldest_citing_year=2025,
            method_centrality=0.0,
            support_count=100,
            contradict_count=0,
        )
        # All components near zero → RGS near 0
        assert rgs < 0.1

    def test_moderate_gap(self):
        """Mid-range claim."""
        rgs = compute_rgs(
            degree=3,
            oldest_citing_year=2020,
            method_centrality=0.5,
            support_count=1,
            contradict_count=1,
        )
        # Should be between 0.3 and 0.7
        assert 0.3 < rgs < 0.7

    def test_rgs_clamped_to_unit_range(self):
        """RGS should always be in [0, 1]."""
        rgs = compute_rgs(0, 2000, 1.0, 0, 0)
        assert 0.0 <= rgs <= 1.0

    def test_rgs_rounded_to_4_decimals(self):
        """RGS should be rounded to 4 decimal places."""
        rgs = compute_rgs(3, 2020, 0.5, 1, 1)
        assert rgs == round(rgs, 4)


class TestIsGap:
    """is_gap = (RGS > 0.65 AND SupportDensity < 0.3)"""

    def test_is_gap_true(self):
        assert is_gap(0.70, 0.2) is True

    def test_is_gap_false_low_rgs(self):
        assert is_gap(0.50, 0.2) is False

    def test_is_gap_false_high_density(self):
        assert is_gap(0.70, 0.5) is False

    def test_is_gap_boundary(self):
        """Exactly at threshold → False (> not >=)"""
        assert is_gap(0.65, 0.3) is False


class TestClassifyGap:
    """Agent 4 gap classification."""

    def test_critical_gap(self):
        assert classify_gap(0.80, ref_count=5) == "critical_gap"

    def test_moderate_gap(self):
        assert classify_gap(0.60, ref_count=2) == "moderate_gap"

    def test_orphan_method(self):
        assert classify_gap(0.5, source_query="orphan_methods") == "orphan_method"

    def test_methodology_gap(self):
        assert classify_gap(0.5, source_query="methodology_gaps") == "methodology_gap"


class TestBatch:
    """Batch RGS computation."""

    def test_batch_adds_fields(self):
        claims = [
            {"degree": 0, "support_count": 0, "contradict_count": 0,
             "method_centrality": 0.5, "oldest_citing_year": None},
        ]
        results = compute_rgs_batch(claims)
        assert "rgs_score" in results[0]
        assert "support_density" in results[0]
        assert "is_gap" in results[0]

    def test_batch_multiple(self):
        claims = [
            {"degree": 0, "support_count": 0, "contradict_count": 0,
             "method_centrality": 0.5, "oldest_citing_year": None},
            {"degree": 10, "support_count": 5, "contradict_count": 0,
             "method_centrality": 0.3, "oldest_citing_year": 2024},
        ]
        results = compute_rgs_batch(claims)
        assert len(results) == 2
        assert results[0]["rgs_score"] > results[1]["rgs_score"]

"""
PaperMind — Research Gap Score Calculator
Source: docs/agents.md (Agent 2 STEP 4 + Agent 4 STEP 2)

Formula:
    RGS(c) = 0.30 × (1 / max(degree(c), 1))
            + 0.20 × CitAge(c)
            + 0.30 × MethodCentrality(c)
            + 0.20 × (1 - SupportDensity(c))

Where:
    degree(c)           = total edges in + out
    CitAge(c)           = (2025 - oldest_citing_year) / 10, capped at 1.0
    MethodCentrality(c) = pagerank in method subgraph, default 0.5
    SupportDensity(c)   = support_count / (support_count + contradict_count + 1)

Classification:
    RGS > 0.75 AND ref_count >= 4 → "critical_gap"
    RGS 0.50–0.75                 → "moderate_gap"
    From orphan methods query     → "orphan_method"
    From methodology gaps query   → "methodology_gap"

Gap threshold (Agent 2):
    is_gap = (RGS > 0.65 AND SupportDensity < 0.3)
"""

import logging
from typing import Optional

logger = logging.getLogger("papermind.rgs")

# ── Weights from agents.md ──────────────────────────────────────
W_DEGREE = 0.30
W_CIT_AGE = 0.20
W_METHOD_CENTRALITY = 0.30
W_SUPPORT_DENSITY = 0.20

# ── Thresholds ──────────────────────────────────────────────────
RGS_GAP_THRESHOLD = 0.65       # Agent 2: is_gap if RGS > this
SUPPORT_DENSITY_THRESHOLD = 0.3  # Agent 2: AND SupportDensity < this
RGS_CRITICAL_THRESHOLD = 0.75   # Agent 4: critical_gap if RGS > this
RGS_MODERATE_LOW = 0.50         # Agent 4: moderate_gap lower bound
REFERENCE_YEAR = 2025            # CitAge reference year


def compute_support_density(
    support_count: int,
    contradict_count: int
) -> float:
    """
    SupportDensity(c) = support_count / (support_count + contradict_count + 1)

    The +1 in the denominator prevents division by zero and ensures
    claims with zero evidence have density 0.0.
    """
    return support_count / (support_count + contradict_count + 1)


def compute_cit_age(oldest_citing_year: Optional[int]) -> float:
    """
    CitAge(c) = (2025 - oldest_citing_year) / 10, capped at 1.0

    Older unreferenced claims get higher gap scores.
    If no citing year available, returns 0.5 as default.
    """
    if oldest_citing_year is None:
        return 0.5
    raw = (REFERENCE_YEAR - oldest_citing_year) / 10.0
    return min(max(raw, 0.0), 1.0)


def compute_degree_score(degree: int) -> float:
    """
    Degree component = 1 / max(degree(c), 1)

    Lower connectivity → higher gap score.
    Isolated claims (degree=0 or 1) get maximum score of 1.0.
    """
    return 1.0 / max(degree, 1)


def compute_rgs(
    degree: int,
    oldest_citing_year: Optional[int],
    method_centrality: float,
    support_count: int,
    contradict_count: int
) -> float:
    """
    Compute the full RGS(c) score.

    RGS(c) = 0.30 × (1/max(degree(c),1))
            + 0.20 × CitAge(c)
            + 0.30 × MethodCentrality(c)
            + 0.20 × (1 - SupportDensity(c))

    Args:
        degree:              Total edges in + out for this claim node.
        oldest_citing_year:  Year of the oldest paper citing this claim.
        method_centrality:   PageRank in method subgraph (default 0.5).
        support_count:       Number of SUPPORTS edges.
        contradict_count:    Number of CONTRADICTS edges.

    Returns:
        Float between 0.0 and 1.0.
    """
    degree_score = compute_degree_score(degree)
    cit_age = compute_cit_age(oldest_citing_year)
    support_density = compute_support_density(support_count, contradict_count)

    rgs = (
        W_DEGREE * degree_score
        + W_CIT_AGE * cit_age
        + W_METHOD_CENTRALITY * method_centrality
        + W_SUPPORT_DENSITY * (1.0 - support_density)
    )

    # Clamp to [0, 1]
    rgs = min(max(rgs, 0.0), 1.0)

    logger.debug(
        f"RGS computed: {rgs:.4f} "
        f"(degree={degree}, cit_age={cit_age:.2f}, "
        f"centrality={method_centrality:.2f}, "
        f"support_density={support_density:.2f})"
    )

    return round(rgs, 4)


def is_gap(rgs_score: float, support_density: float) -> bool:
    """
    Agent 2 gap classification:
        is_gap = (RGS > 0.65 AND SupportDensity < 0.3)
    """
    return rgs_score > RGS_GAP_THRESHOLD and support_density < SUPPORT_DENSITY_THRESHOLD


def classify_gap(
    rgs_score: float,
    ref_count: int = 0,
    source_query: Optional[str] = None
) -> str:
    """
    Agent 4 gap classification:
        RGS > 0.75 AND ref_count >= 4 → "critical_gap"
        RGS 0.50–0.75                 → "moderate_gap"
        From Query 2                   → "orphan_method"
        From Query 4                   → "methodology_gap"
    """
    if source_query == "orphan_methods":
        return "orphan_method"
    if source_query == "methodology_gaps":
        return "methodology_gap"
    if rgs_score > RGS_CRITICAL_THRESHOLD and ref_count >= 4:
        return "critical_gap"
    if rgs_score >= RGS_MODERATE_LOW:
        return "moderate_gap"
    return "moderate_gap"  # Default for any detected gap


def compute_rgs_batch(claims: list[dict]) -> list[dict]:
    """
    Compute RGS for a batch of claim dicts.

    Each claim dict must have:
        degree, oldest_citing_year, method_centrality,
        support_count, contradict_count

    Returns the same dicts with rgs_score and is_gap added.
    """
    for claim in claims:
        support_density = compute_support_density(
            claim.get("support_count", 0),
            claim.get("contradict_count", 0)
        )
        rgs = compute_rgs(
            degree=claim.get("degree", 0),
            oldest_citing_year=claim.get("oldest_citing_year"),
            method_centrality=claim.get("method_centrality", 0.5),
            support_count=claim.get("support_count", 0),
            contradict_count=claim.get("contradict_count", 0),
        )
        claim["rgs_score"] = rgs
        claim["support_density"] = support_density
        claim["is_gap"] = is_gap(rgs, support_density)

    return claims

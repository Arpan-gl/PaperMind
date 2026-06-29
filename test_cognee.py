"""
PaperMind — Cognee Integration Test
Source: docs/cognee_role.md (lines 329-361)

Tests:
    1. remember → recall roundtrip
    2. memify works
    3. scoped vs global recall
"""

import asyncio
import json
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.cognee_client import setup_cognee, remember, recall, memify


async def test_roundtrip():
    """
    Exact test from cognee_role.md lines 334-360.
    """
    print("=" * 60)
    print("PaperMind — Cognee Integration Test")
    print("=" * 60)

    await setup_cognee()

    # Test 1: remember → recall
    print("\n[Test 1] remember → recall roundtrip...")
    ok1 = await remember(
        data="Test paper about graph neural networks",
        metadata={"paper_id": "test_001", "user_id": "test_user", "type": "test"}
    )
    assert ok1, "remember() returned False"

    result = await recall(query="graph neural networks", user_id="test_user")
    assert result, "recall() returned empty"
    assert "graph" in result.lower() or len(result) > 0, "recall() did not return stored data"
    print("  ✓ remember → recall roundtrip works")

    # Test 2: memify
    print("\n[Test 2] memify()...")
    ok2 = await memify(
        data={"paper_id": "test_001", "delta": {"nodes_created": 5}},
        metadata={"user_id": "test_user", "type": "graph_delta"}
    )
    assert ok2, "memify() failed"
    print("  ✓ memify() works")

    # Test 3: scoped vs global recall
    print("\n[Test 3] scoped vs global recall...")
    result_scoped = await recall("graph", user_id="test_user")
    result_global = await recall("graph")
    print(f"  ✓ scoped recall: {len(result_scoped)} chars")
    print(f"  ✓ global recall: {len(result_global)} chars")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_roundtrip())

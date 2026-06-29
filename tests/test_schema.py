"""
PaperMind — Schema Verification Tests
Source: docs/architecture.md (KuzuDB Schema section)

Verifies:
    1. All 5 node tables exist with correct columns
    2. All 10 edge tables exist with correct properties
    3. Schema matches architecture.md exactly
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from pathlib import Path

# The schema file content — source of truth
SCHEMA_FILE = Path(__file__).parent.parent / "schema" / "kuzu_schema.cypher"


class TestSchemaFile:
    """Verify the schema file matches architecture.md."""

    def test_schema_file_exists(self):
        assert SCHEMA_FILE.exists(), f"Schema file missing: {SCHEMA_FILE}"

    def test_schema_has_all_node_tables(self):
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        node_tables = ["Paper", "Claim", "Method", "Dataset", "Author", "Task"]
        for table in node_tables:
            assert f"CREATE NODE TABLE {table}" in schema, \
                f"Node table {table} missing from schema"

    def test_schema_has_all_edge_tables(self):
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        edge_tables = [
            "CITES", "HAS_CLAIM", "CONTRADICTS", "SUPPORTS",
            "USES_SAME_METHOD", "PROPOSES", "USES_DATASET",
            "AUTHORED_BY", "REFERENCES", "APPLIES_TO",
        ]
        for table in edge_tables:
            assert f"CREATE REL TABLE {table}" in schema, \
                f"Edge table {table} missing from schema"

    def test_paper_columns(self):
        """Paper: paper_id, title, pub_year, venue, pdf_url, user_id"""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        required = ["paper_id", "title", "pub_year", "venue", "pdf_url", "user_id"]
        for col in required:
            assert col in schema, f"Paper.{col} missing from schema"

    def test_claim_columns(self):
        """Claim: claim_id, text, paper_id, section, page, support_count,
        contradict_count, rgs_score, support_density, is_gap"""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        required = [
            "claim_id", "text", "paper_id", "section", "page",
            "support_count", "contradict_count", "rgs_score",
            "support_density", "is_gap",
        ]
        for col in required:
            assert col in schema, f"Claim.{col} missing from schema"

    def test_method_columns(self):
        """Method: node_id, name, paper_count, aliases"""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        required = ["node_id", "name", "paper_count", "aliases"]
        for col in required:
            assert col in schema, f"Method.{col} missing from schema"

    def test_dataset_columns(self):
        """Dataset: node_id, name, year, version"""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        required = ["node_id", "name", "year", "version"]
        for col in required:
            assert col in schema, f"Dataset.{col} missing from schema"

    def test_author_columns(self):
        """Author: author_id, name, affiliation"""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        required = ["author_id", "name", "affiliation"]
        for col in required:
            assert col in schema, f"Author.{col} missing from schema"

    def test_cites_properties(self):
        """CITES: strength, cite_type, relation_role"""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        # Find CITES section
        assert "strength" in schema
        assert "cite_type" in schema
        assert "relation_role" in schema

    def test_contradicts_properties(self):
        """CONTRADICTS: confidence, evidence_a, evidence_b"""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        assert "evidence_a" in schema
        assert "evidence_b" in schema

    def test_edge_directions(self):
        """Verify edge directions from architecture.md."""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        assert "FROM Paper TO Paper" in schema  # CITES
        assert "FROM Paper TO Claim" in schema  # HAS_CLAIM, REFERENCES
        assert "FROM Claim TO Claim" in schema  # CONTRADICTS, SUPPORTS
        assert "FROM Paper TO Method" in schema  # PROPOSES
        assert "FROM Paper TO Dataset" in schema  # USES_DATASET
        assert "FROM Paper TO Author" in schema  # AUTHORED_BY
        assert "FROM Method TO Task" in schema  # APPLIES_TO

    def test_count_node_tables(self):
        """Exactly 6 node tables."""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        count = schema.count("CREATE NODE TABLE")
        assert count == 6, f"Expected 6 node tables, found {count}"

    def test_count_edge_tables(self):
        """Exactly 10 edge tables."""
        schema = SCHEMA_FILE.read_text(encoding="utf-8")
        count = schema.count("CREATE REL TABLE")
        assert count == 10, f"Expected 10 edge tables, found {count}"

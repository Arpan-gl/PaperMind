"""
PaperMind — KuzuDB Client
Source: docs/architecture.md

Embedded KuzuDB graph database wrapper.
Schema: 5 node tables (Paper, Claim, Method, Dataset, Author)
        10 edge tables (CITES, HAS_CLAIM, CONTRADICTS, SUPPORTS,
                        USES_SAME_METHOD, PROPOSES, USES_DATASET,
                        AUTHORED_BY, REFERENCES, APPLIES_TO)
"""

import os
import logging
from pathlib import Path
from typing import Any, Optional

import kuzu
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("papermind.kuzu")

# ── Singleton database connection ───────────────────────────────
_db: Optional[kuzu.Database] = None
_conn: Optional[kuzu.Connection] = None

SCHEMA_FILE = Path(__file__).parent.parent / "schema" / "kuzu_schema.cypher"


def get_db_path() -> str:
    """Return a Kuzu database file path compatible with directory settings."""
    configured = Path(os.environ.get("KUZU_DB_PATH", "./kuzu_graph"))
    if configured.exists() and configured.is_dir():
        return str(configured / "papermind.kuzu")
    if not configured.suffix:
        configured.mkdir(parents=True, exist_ok=True)
        return str(configured / "papermind.kuzu")
    configured.parent.mkdir(parents=True, exist_ok=True)
    return str(configured)


def get_db() -> kuzu.Database:
    """Get or create the singleton KuzuDB database."""
    global _db
    if _db is None:
        db_path = get_db_path()
        _db = kuzu.Database(db_path)
        logger.info(f"KuzuDB initialized at {db_path}")
    return _db


def get_connection() -> kuzu.Connection:
    """Get or create a singleton KuzuDB connection."""
    global _conn
    if _conn is None:
        _conn = kuzu.Connection(get_db())
    return _conn


def initialize_schema() -> None:
    """
    Run the full schema from schema/kuzu_schema.cypher.
    Safe to call multiple times — skips tables that already exist.

    Corresponds to architecture.md KuzuDB Schema section.
    """
    conn = get_connection()

    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_FILE}")

    schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")

    # Split on semicolons and execute each statement
    schema_sql = "\n".join(
        line for line in schema_sql.splitlines()
        if not line.lstrip().startswith("--")
    )
    statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

    created = 0
    skipped = 0

    for stmt in statements:
        try:
            conn.execute(stmt)
            created += 1
            logger.debug(f"Executed: {stmt[:60]}...")
        except Exception as e:
            error_msg = str(e).lower()
            if "already exists" in error_msg or "exist" in error_msg:
                skipped += 1
                logger.debug(f"Skipped (exists): {stmt[:60]}...")
            else:
                logger.error(f"Schema error: {e}\nStatement: {stmt}")
                raise

    logger.info(
        f"Schema initialized: {created} created, {skipped} skipped"
    )


def execute(query: str, params: Optional[dict] = None) -> list[dict]:
    """
    Execute a Cypher query with optional parameters.

    Args:
        query:  Cypher query string (use $param for parameters).
        params: Dictionary of parameter values.

    Returns:
        List of result dictionaries.
    """
    conn = get_connection()

    try:
        if params:
            result = conn.execute(query, params)
        else:
            result = conn.execute(query)

        rows = []
        while result.has_next():
            row = result.get_next()
            # Convert to dict using column names
            col_names = result.get_column_names()
            rows.append(dict(zip(col_names, row)))

        return rows

    except Exception as e:
        logger.error(f"Query failed: {e}\nQuery: {query}\nParams: {params}")
        raise


def execute_write(query: str, params: Optional[dict] = None) -> int:
    """
    Execute a write query (CREATE, SET, DELETE).

    Returns:
        Number of rows affected (best effort).
    """
    conn = get_connection()

    try:
        if params:
            result = conn.execute(query, params)
        else:
            result = conn.execute(query)

        # Count results if any
        count = 0
        while result.has_next():
            result.get_next()
            count += 1

        return max(count, 1)  # At least 1 for successful write

    except Exception as e:
        logger.error(f"Write failed: {e}\nQuery: {query}")
        raise


def node_exists(table: str, pk_field: str, pk_value: str) -> bool:
    """Check if a node exists by primary key."""
    rows = execute(
        f"MATCH (n:{table}) WHERE n.{pk_field} = $val RETURN n.{pk_field}",
        {"val": pk_value}
    )
    return len(rows) > 0


def get_all_papers(user_id: Optional[str] = None) -> list[dict]:
    """Get all papers, optionally filtered by user_id."""
    if user_id:
        return execute(
            "MATCH (p:Paper) WHERE p.user_id = $uid AND p.pdf_url <> '' "
            "RETURN p.paper_id, p.title, p.pub_year, p.venue",
            {"uid": user_id}
        )
    return execute(
        "MATCH (p:Paper) RETURN p.paper_id, p.title, p.pub_year, p.venue"
    )


def get_paper_ids_for_user(user_id: str) -> list[str]:
    """Return all paper_ids belonging to a user."""
    rows = execute(
        "MATCH (p:Paper) WHERE p.user_id = $uid AND p.pdf_url <> '' RETURN p.paper_id",
        {"uid": user_id}
    )
    return [r["p.paper_id"] for r in rows]


def get_full_graph(
    user_id: str,
    include_claims: bool = True,
    include_citations: bool = False,
    max_claims_per_paper: int = 5,
) -> dict:
    """
    Return the graph (nodes + edges) for a user, suitable for
    Cytoscape.js rendering in the frontend.

    Filtering behaviour (reduces hairball clutter):
      • Only "real" papers (pdf_url != '') are included as nodes unless
        include_citations=True explicitly requests citation stubs.
      • Claims are limited to the top-N by rgs_score per paper
        (default 5) — the most research-gap-relevant ones.
      • Each Claim node carries a ``parent`` field equal to its paper_id
        so Cytoscape can use compound nodes to group them visually.

    Args:
        user_id:              Scope graph to this user.
        include_claims:       Include Claim nodes (default True).
        include_citations:    Include citation-stub Paper nodes whose pdf
                              was never uploaded (default False).
        max_claims_per_paper: Max Claim nodes returned per paper (default 5).
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    # ── Real uploaded papers ──────────────────────────────────────
    papers = execute(
        "MATCH (p:Paper) WHERE p.user_id = $uid AND p.pdf_url <> '' "
        "RETURN p.paper_id, p.title, p.pub_year, p.venue",
        {"uid": user_id},
    )
    paper_id_set = {p["p.paper_id"] for p in papers}
    for p in papers:
        nodes.append({
            "data": {
                "id": p["p.paper_id"],
                "label": (p["p.title"] or "")[:60],
                "type": "Paper",
                "pub_year": p["p.pub_year"],
                "venue": p["p.venue"],
            }
        })

    # ── Citation-stub papers (opt-in) ─────────────────────────────
    if include_citations:
        stubs = execute(
            "MATCH (p:Paper) WHERE p.user_id = $uid AND p.pdf_url = '' "
            "RETURN p.paper_id, p.title, p.pub_year, p.venue",
            {"uid": user_id},
        )
        for p in stubs:
            paper_id_set.add(p["p.paper_id"])
            nodes.append({
                "data": {
                    "id": p["p.paper_id"],
                    "label": (p["p.title"] or "")[:60],
                    "type": "CitationStub",
                    "pub_year": p["p.pub_year"],
                }
            })

    # ── Claims — top-N per paper by rgs_score ────────────────────
    shown_claim_ids: set[str] = set()
    if include_claims:
        all_claims = execute(
            "MATCH (p:Paper)-[:HAS_CLAIM]->(c:Claim) "
            "WHERE p.user_id = $uid AND p.pdf_url <> '' "
            "RETURN c.claim_id, c.text, c.rgs_score, c.is_gap, c.paper_id "
            "ORDER BY c.rgs_score DESC",
            {"uid": user_id},
        )
        # Group by paper, take top-N per paper
        paper_claim_count: dict[str, int] = {}
        for c in all_claims:
            pid = c.get("c.paper_id", "")
            if paper_claim_count.get(pid, 0) >= max_claims_per_paper:
                continue
            paper_claim_count[pid] = paper_claim_count.get(pid, 0) + 1
            cid = c["c.claim_id"]
            shown_claim_ids.add(cid)
            text = c.get("c.text", "") or ""
            nodes.append({
                "data": {
                    "id": cid,
                    "label": text[:70] + "…" if len(text) > 70 else text,
                    "type": "Claim",
                    "rgs_score": c.get("c.rgs_score"),
                    "is_gap": c.get("c.is_gap"),
                    "paper_id": pid,  # which paper this claim belongs to
                }
            })

    # ── Methods ──────────────────────────────────────────────────
    methods = execute(
        "MATCH (p:Paper)-[:PROPOSES]->(m:Method) "
        "WHERE p.user_id = $uid AND p.pdf_url <> '' "
        "RETURN DISTINCT m.node_id, m.name, m.paper_count",
        {"uid": user_id},
    )
    shown_method_ids = {m["m.node_id"] for m in methods}
    for m in methods:
        nodes.append({
            "data": {
                "id": m["m.node_id"],
                "label": m["m.name"],
                "type": "Method",
                "paper_count": m["m.paper_count"],
            }
        })

    # ── HAS_CLAIM edges (only for shown claims) ───────────────────
    if include_claims and shown_claim_ids:
        hc_edges = execute(
            "MATCH (p:Paper)-[r:HAS_CLAIM]->(c:Claim) "
            "WHERE p.user_id = $uid AND p.pdf_url <> '' "
            "RETURN p.paper_id, c.claim_id, r.section",
            {"uid": user_id},
        )
        for e in hc_edges:
            if e["c.claim_id"] in shown_claim_ids:
                edges.append({
                    "data": {
                        "source": e["p.paper_id"],
                        "target": e["c.claim_id"],
                        "type": "HAS_CLAIM",
                        "section": e.get("r.section"),
                    }
                })

    # ── CITES edges (only between shown papers) ───────────────────
    cite_edges = execute(
        "MATCH (p1:Paper)-[r:CITES]->(p2:Paper) "
        "WHERE p1.user_id = $uid "
        "RETURN p1.paper_id, p2.paper_id, r.strength, r.cite_type",
        {"uid": user_id},
    )
    for e in cite_edges:
        if e["p1.paper_id"] in paper_id_set and e["p2.paper_id"] in paper_id_set:
            edges.append({
                "data": {
                    "source": e["p1.paper_id"],
                    "target": e["p2.paper_id"],
                    "type": "CITES",
                    "strength": e.get("r.strength"),
                    "cite_type": e.get("r.cite_type"),
                }
            })

    # ── CONTRADICTS / SUPPORTS (only between shown claims) ────────
    if include_claims and shown_claim_ids:
        contra_edges = execute(
            "MATCH (c1:Claim)-[r:CONTRADICTS]->(c2:Claim) "
            "RETURN c1.claim_id, c2.claim_id, r.confidence",
        )
        for e in contra_edges:
            if e["c1.claim_id"] in shown_claim_ids and e["c2.claim_id"] in shown_claim_ids:
                edges.append({
                    "data": {
                        "source": e["c1.claim_id"],
                        "target": e["c2.claim_id"],
                        "type": "CONTRADICTS",
                        "confidence": e.get("r.confidence"),
                    }
                })

        supp_edges = execute(
            "MATCH (c1:Claim)-[r:SUPPORTS]->(c2:Claim) "
            "RETURN c1.claim_id, c2.claim_id, r.confidence",
        )
        for e in supp_edges:
            if e["c1.claim_id"] in shown_claim_ids and e["c2.claim_id"] in shown_claim_ids:
                edges.append({
                    "data": {
                        "source": e["c1.claim_id"],
                        "target": e["c2.claim_id"],
                        "type": "SUPPORTS",
                        "confidence": e.get("r.confidence"),
                    }
                })

    # ── PROPOSES edges (only between shown papers/methods) ────────
    prop_edges = execute(
        "MATCH (p:Paper)-[:PROPOSES]->(m:Method) "
        "WHERE p.user_id = $uid AND p.pdf_url <> '' "
        "RETURN p.paper_id, m.node_id",
        {"uid": user_id},
    )
    for e in prop_edges:
        if e["m.node_id"] in shown_method_ids:
            edges.append({
                "data": {
                    "source": e["p.paper_id"],
                    "target": e["m.node_id"],
                    "type": "PROPOSES",
                }
            })

    return {"nodes": nodes, "edges": edges}


def reset_db() -> None:
    """Drop all data (for testing only)."""
    global _db, _conn
    _conn = None
    _db = None

    import shutil
    db_path = get_db_path()
    if os.path.isfile(db_path):
        os.remove(db_path)
    elif os.path.isdir(db_path):
        shutil.rmtree(db_path)
    logger.warning(f"KuzuDB reset: {db_path} removed")

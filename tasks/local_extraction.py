"""Deterministic PDF extraction used when remote enrichment exceeds its latency budget."""

import hashlib
import re


def local_fast_extraction(pdf_path: str) -> dict:
    """Build a useful minimal graph from PDF metadata and abstract text."""
    import fitz

    doc = fitz.open(pdf_path)
    metadata = doc.metadata or {}
    page_text = "\n".join(page.get_text() for page in list(doc)[:4])
    doc.close()

    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    title = (metadata.get("title") or "").strip()
    if not title or title.lower() in {"untitled", "unknown"}:
        title = next(
            (line for line in lines[:30] if 12 < len(line) < 240),
            "Untitled paper",
        )

    identifier = re.search(
        r"(?:arxiv[:\s]*)?(\d{4}\.\d{4,5})(?:v\d+)?",
        page_text,
        re.I,
    )
    digest = hashlib.sha256(
        page_text.encode("utf-8", errors="ignore")
    ).hexdigest()[:16]
    paper_id = identifier.group(1) if identifier else f"pdf_{digest}"
    year_match = re.search(r"\b(20[0-3]\d|19\d{2})\b", page_text)
    year = int(year_match.group(1)) if year_match else 0

    abstract_match = re.search(
        r"\babstract\b\s*[-—:]?\s*(.*?)"
        r"(?:\n\s*(?:1\.?\s+)?introduction\b|\n\s*keywords?\b)",
        page_text,
        re.I | re.S,
    )
    source = abstract_match.group(1) if abstract_match else " ".join(lines[1:40])
    sentences = [
        re.sub(r"\s+", " ", sentence).strip()
        for sentence in re.split(r"(?<=[.!?])\s+", source)
    ]
    claims = [
        sentence for sentence in sentences if 45 <= len(sentence) <= 450
    ][:4]
    if not claims:
        claims = [f"This paper presents research titled {title}."]

    return {
        "paper_id": paper_id,
        "A_Meta": {
            "paper_id": paper_id,
            "title": title,
            "authors": [],
            "pub_year": year,
            "venue": "",
            "language": "English",
            "confidence": 0.6,
        },
        "B_Textual": {
            "methods": [],
            "datasets": [],
            "metrics": [],
            "tasks": [],
            "baselines": [],
        },
        "C_Implicit": {
            "problem_definition": {},
            "motivation": {
                "existing_limitations": [],
                "gap_categories": [],
            },
            "contributions": {
                "main_contributions": claims,
                "component_alignment": [],
            },
            "findings": {
                "quantitative": [],
                "qualitative": [],
            },
            "limitations": {
                "generalizability": [],
                "computational_cost": [],
            },
            "future_work": [],
            "hypotheses": [],
        },
        "D_Citations": [],
        "E_Relations": [],
        "extraction_metadata": {
            "attempt": 1,
            "notes": (
                "Local latency-budget fallback; remote enrichment was "
                "unavailable or slow."
            ),
        },
    }

"""
PaperMind — Agent 1: PDF Analyst
Source: docs/agents.md (lines 42-188)

Trigger:  User uploads a PDF
Input:    PDF file path
Output:   5-module structured JSON (A_Meta, B_Textual, C_Implicit, D_Citations, E_Relations)
PASS:     80 / 100

PDF Parsing: MinerU → fallback to PyMuPDF (fitz)

CRITICAL: If this PDF IS agents_k1_paper.pdf (2606.13669), also extract:
    - Exact schema definitions for Modules A–E
    - Equations 17, 18, 19 verbatim
    - Operators O1–O6
    - All benchmark numbers from Tables 5, 6, 7
    Store these under C_Implicit as "reference_infrastructure".
"""

import json
import logging
from typing import Any, Optional
from datetime import datetime

from core.openrouter_client import qwen_call
from core import cognee_client

logger = logging.getLogger("papermind.agent1")

# ── System Prompt (VERBATIM from agents.md lines 51-153) ────────
AGENT_1_PROMPT = """You are the PDF Analyst in PaperMind. Extract structured knowledge from scientific
papers conforming to the Agents-K1 five-module schema.

## Memory context from prior attempts:
{memory_context}
Study failures above and correct them. Attempt {attempt} of 3.
Prior feedback: {judge_feedback}

## If this PDF IS the Agents-K1 paper (2606.13669), also extract:
- Exact schema definitions for Modules A–E
- Equations 17, 18, 19 verbatim
- Operators O1–O6
- All benchmark numbers from Tables 5, 6, 7
Store these under C_Implicit as "reference_infrastructure".

## Module A — Meta/Factual (zero-tolerance, exact values only)
{{
  "paper_id": "<doi or arxiv_id>",
  "title": "<exact title>",
  "authors": [{{"name": "Surname, Given", "ordering": 0, "corresponding": false}}],
  "pub_year": <int>,
  "venue": "<journal or conference>",
  "language": "English",
  "confidence": <0.0-1.0>
}}

## Module B — Textually Mentioned Entities
{{
  "methods": [{{"name":"","proposed_or_cited":"proposed|cited","components":[],"aliases":[]}}],
  "datasets": [{{"name":"","year":null,"version":""}}],
  "metrics": [{{"full_name":"","abbreviation":""}}],
  "tasks": [{{"name":"","input_modality":"","output_modality":""}}],
  "baselines": [{{"name":"","strong_baseline":true}}]
}}

## Module C — Implicit/Abstracted Entities
{{
  "problem_definition": {{"input_space":"","output_space":"","constraints":[],"assumptions":[]}},
  "motivation": {{"existing_limitations":[],"gap_categories":[]}},
  "contributions": {{"main_contributions":[],"component_alignment":[]}},
  "findings": {{"quantitative":[],"qualitative":[]}},
  "limitations": {{"generalizability":[],"computational_cost":[]}},
  "future_work": [],
  "hypotheses": [{{"hypothesis":"","testable":true}}]
}}

## Module D — Citation Relationships (Appendix A 5-level schema)
Level 5 = Foundational (core theory depends on it)
Level 4 = Strong (primary benchmark/comparison)
Level 3 = Moderate (supporting/inspiration)
Level 2 = Contextual (maps landscape)
Level 1 = Peripheral (breadth only)
{{
  "citations": [{{
    "cited_title": "",
    "cite_type": "Level1|Level2|Level3|Level4|Level5",
    "relation": "support|contrast|extend|background",
    "evidence_sections": [<page_nums>],
    "strength_score": <1-5>
  }}]
}}

## Module E — Knowledge Relations Between Entities
Controlled (head+tail must exist in Module B):
  BUILDS_ON, USES_COMPONENT, ALTERNATIVE_TO, SOLVES, APPLIED_TO, TARGETS

Open (new concepts allowed with verbatim evidence):
  CAUSES, ENABLES, INHIBITS, DIFFERS_FROM, HAS_LIMITATION,
  USES_TECHNIQUE, CONSISTS_OF, DERIVES_FROM, MOTIVATED_BY

{{
  "relations": [{{
    "head": "", "head_type": "Method|Task|Dataset|Metric",
    "relation": "<type>",
    "tail": "", "tail_type": "",
    "evidence": "<verbatim span from paper — required, non-empty>",
    "confidence": <0.7-1.0>,
    "source": "structural|semantic"
  }}]
}}
Rule: confidence < 0.7 → exclude. Numerical results → exclude. Evidence must be non-empty.

## Output: valid JSON only. No markdown fences. Start with {{
{{
  "paper_id": "",
  "A_Meta": {{}},
  "B_Textual": {{}},
  "C_Implicit": {{}},
  "D_Citations": [],
  "E_Relations": [],
  "extraction_metadata": {{"attempt": {attempt}, "notes": ""}}
}}

## Self-check before returning:
□ All 5 modules present?
□ A_Meta has paper_id, title, authors list, pub_year?
□ B_Textual.methods has ≥ 2 items with components?
□ C_Implicit.motivation.existing_limitations non-empty?
□ D_Citations has ≥ 3 items with strength_score integer?
□ E_Relations has ≥ 3 items with non-empty evidence and confidence ≥ 0.7?
□ Output is valid JSON?"""


def parse_pdf(pdf_path: str) -> str:
    """
    Parse PDF to text. Try MinerU first, fallback to PyMuPDF.
    Source: agents.md lines 170-177
    """
    # Try MinerU first (preferred parser per architecture.md)
    try:
        from mineru import PDFParser
        content = PDFParser().parse(pdf_path).to_markdown()
        logger.info(f"PDF parsed with MinerU: {len(content)} chars")
        return content
    except Exception as e:
        logger.info(f"MinerU unavailable ({e}), falling back to PyMuPDF")

    # Fallback to PyMuPDF
    try:
        import fitz
        doc = fitz.open(pdf_path)
        content = "\n".join([page.get_text() for page in doc])
        doc.close()
        logger.info(f"PDF parsed with PyMuPDF: {len(content)} chars")
        return content
    except Exception as e:
        logger.error(f"Both PDF parsers failed: {e}")
        raise RuntimeError(f"Cannot parse PDF {pdf_path}: {e}")


def select_representative_text(content: str, budget: int = 12000) -> str:
    """Sample the beginning, middle, and end without multiple LLM calls."""
    if len(content) <= budget:
        return content
    head = budget * 5 // 12
    middle = budget * 4 // 12
    tail = budget - head - middle
    middle_start = max(0, len(content) // 2 - middle // 2)
    return (
        content[:head]
        + "\n\n[... middle of paper ...]\n\n"
        + content[middle_start:middle_start + middle]
        + "\n\n[... end of paper ...]\n\n"
        + content[-tail:]
    )


async def agent_1_pdf_analyst(
    input_data: dict,
    memory_context: str,
    attempt: int,
    user_id: str,
) -> dict:
    """
    Agent 1: PDF Analyst.

    Called by agent_loop() — never directly.
    Source: agents.md lines 170-188

    Args:
        input_data:     {"pdf_path": "/path/to/paper.pdf"}
        memory_context: Prior attempts + judge feedback from Cognee recall()
        attempt:        Current attempt number (1-3)
        user_id:        User ID for corpus scoping

    Returns:
        5-module extraction dict.
    """
    pdf_path = input_data["pdf_path"]

    # Parse PDF content
    pdf_content = parse_pdf(pdf_path)

    # Extract judge feedback from memory context if available
    judge_feedback = ""
    if memory_context:
        try:
            mem = json.loads(memory_context) if isinstance(memory_context, str) else memory_context
            if isinstance(mem, list):
                # Find most recent feedback
                for item in reversed(mem):
                    if isinstance(item, dict) and item.get("verdict"):
                        judge_feedback = item["verdict"].get("feedback_for_agent", "")
                        break
            elif isinstance(mem, dict) and mem.get("verdict"):
                judge_feedback = mem["verdict"].get("feedback_for_agent", "")
        except (json.JSONDecodeError, TypeError):
            judge_feedback = str(memory_context)[:500] if memory_context else ""

    # Build prompt with memory context
    system_prompt = AGENT_1_PROMPT.format(
        memory_context=memory_context[:3000] if memory_context else "No prior attempts.",
        attempt=attempt,
        judge_feedback=judge_feedback if judge_feedback else "None (first attempt).",
    )

    # Call Qwen3:32B — truncate PDF to 12000 chars per agents.md
    representative_text = select_representative_text(pdf_content)
    response = await qwen_call(
        system_prompt=system_prompt,
        user_message=(
            "Extract concise values for all 5 modules. Limit each list to the "
            "5 most important items and keep evidence spans under 25 words.\n\n"
            f"{representative_text}"
        ),
        temperature=0.1,
        max_tokens=int(input_data.get("max_tokens", 1800)),
        json_mode=True,
    )

    # Parse response
    try:
        extraction = json.loads(response)
    except json.JSONDecodeError as e:
        logger.error(f"Agent 1 returned invalid JSON: {e}")
        # Return minimal structure so judge can give specific feedback
        extraction = {
            "paper_id": "",
            "A_Meta": {},
            "B_Textual": {},
            "C_Implicit": {},
            "D_Citations": [],
            "E_Relations": [],
            "extraction_metadata": {
                "attempt": attempt,
                "notes": f"JSON parse error: {str(e)}"
            }
        }

    # Ensure paper_id is set at top level
    if not extraction.get("paper_id"):
        meta = extraction.get("A_Meta", {})
        extraction["paper_id"] = meta.get("paper_id", f"unknown_{hash(pdf_path) % 10000}")

    return extraction


async def store_paper_to_cognee(extraction: dict, user_id: str) -> bool:
    """
    Store all extracted modules as searchable chunks in Cognee.
    Called immediately after Agent 1 PASS.
    Source: docs/cognee_role.md lines 46-79

    Cognee 1.x performs chunking and graph extraction inside remember(), so the
    complete five-module document is submitted once instead of triggering six
    expensive graph builds.
    """
    paper_id = extraction.get("paper_id", "unknown")

    stored = await cognee_client.remember(
        data=json.dumps(extraction),
        metadata={
            "paper_id": paper_id,
            "user_id": user_id,
            "type": "full_extraction",
            "agent": "pdf_analyst",
            "modules": ["A_Meta", "B_Textual", "C_Implicit", "D_Citations", "E_Relations"],
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    logger.info(f"Paper {paper_id} Cognee storage: {'ok' if stored else 'failed'}")
    return stored

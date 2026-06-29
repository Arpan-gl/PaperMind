"""
PaperMind — Papers API
Source: docs/loop_flow.md (lines 358-364)

Endpoints:
    POST /papers/ingest  — Upload PDF → trigger Celery task → return task_id
    GET  /papers/        — List all papers for user
    GET  /papers/{id}    — Get single paper metadata
"""

import os
import uuid
import logging
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from pydantic import BaseModel

from core import kuzu_client

logger = logging.getLogger("papermind.api.papers")

router = APIRouter(prefix="/papers", tags=["papers"])

# Upload directory
UPLOAD_DIR = Path("./uploads").resolve()
JOB_DIR = UPLOAD_DIR / ".jobs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
JOB_DIR.mkdir(parents=True, exist_ok=True)


def update_job(task_id: str, **updates) -> dict:
    """Persist ingestion state so restarts and worker processes do not lose it."""
    path = JOB_DIR / f"{task_id}.json"
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
    current.update(updates)
    current["task_id"] = task_id
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return current


def get_job(task_id: str) -> Optional[dict]:
    path = JOB_DIR / f"{task_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ── Models ──────────────────────────────────────────────────────

class IngestResponse(BaseModel):
    task_id: str
    status: str


class PaperResponse(BaseModel):
    paper_id: str
    title: str
    pub_year: Optional[int] = None
    venue: Optional[str] = None


# ── Dependency: get user_id ─────────────────────────────────────
# In production this would come from auth. For now, header-based.

async def get_current_user(user_id: str = Query(default="default_user")) -> str:
    """Extract user_id from query parameter (auth placeholder)."""
    return user_id


# ── Endpoints ───────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse)
async def ingest_paper(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    """
    Upload a PDF for ingestion.
    Source: loop_flow.md lines 358-364

    Saves the file, triggers async Celery task (Agent 1 → Agent 2 loop).
    Returns immediately with task_id.
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # Save upload
    file_id = uuid.uuid4().hex[:12]
    safe_user = re.sub(r"[^a-zA-Z0-9_-]+", "_", user_id)[:80] or "default_user"
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(file.filename).name)
    user_dir = UPLOAD_DIR / safe_user
    user_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{file_id}_{safe_name}"
    pdf_path = user_dir / filename

    try:
        with open(pdf_path, "wb") as f:
            total = 0
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > 50 * 1024 * 1024:
                    raise HTTPException(status_code=413, detail="PDF exceeds the 50 MB limit")
                f.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="The uploaded PDF is empty")
    except HTTPException:
        pdf_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    task_id = uuid.uuid4().hex
    update_job(
        task_id,
        status="queued",
        user_id=user_id,
        original_filename=file.filename,
        stored_path=str(pdf_path),
        size_bytes=total,
    )

    # Local worker is the reliable default. Celery is opt-in for deployments
    # that explicitly run a worker process.
    try:
        from tasks.dispatcher import dispatch_ingestion
        executor = dispatch_ingestion(str(pdf_path), user_id, task_id)
    except Exception as e:
        update_job(task_id, status="failed", error=f"Worker failed to start: {e}")
        raise HTTPException(status_code=500, detail=f"PDF stored, but worker failed to start: {e}")

    logger.info(f"Paper ingestion queued via {executor}: {filename}, task_id={task_id}")

    return IngestResponse(task_id=task_id, status="queued")


@router.get("/", response_model=list[PaperResponse])
async def list_papers(user_id: str = Depends(get_current_user)):
    """List all papers for a user."""
    try:
        papers = kuzu_client.get_all_papers(user_id)
        return [
            PaperResponse(
                paper_id=p.get("p.paper_id", ""),
                title=p.get("p.title", ""),
                pub_year=p.get("p.pub_year"),
                venue=p.get("p.venue"),
            )
            for p in papers
        ]
    except Exception as e:
        logger.error(f"Failed to list papers: {e}")
        return []


@router.get("/jobs/{task_id}")
async def get_ingestion_status(task_id: str, user_id: str = Depends(get_current_user)):
    job = get_job(task_id)
    if not job or job.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job


@router.post("/jobs/{task_id}/retry", response_model=IngestResponse)
async def retry_ingestion(task_id: str, user_id: str = Depends(get_current_user)):
    """Retry a stored PDF without uploading another copy."""
    job = get_job(task_id)
    if not job or job.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    if job.get("status") in {"analyzing", "graph_building"}:
        raise HTTPException(status_code=409, detail="This job is already processing")
    pdf_path = Path(job.get("stored_path", ""))
    if not pdf_path.is_file():
        raise HTTPException(status_code=410, detail="The stored PDF is missing")

    update_job(
        task_id,
        status="queued",
        stage="Restarting worker",
        progress=5,
        error=None,
        retry_count=int(job.get("retry_count", 0)) + 1,
    )
    from tasks.dispatcher import dispatch_ingestion

    dispatch_ingestion(str(pdf_path), user_id, task_id)
    return IngestResponse(task_id=task_id, status="queued")


@router.get("/latest-job")
async def get_latest_ingestion(user_id: str = Depends(get_current_user)):
    """Restore the most recent durable upload after a page refresh."""
    jobs = []
    for path in JOB_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("user_id") == user_id:
            jobs.append(job)
    if not jobs:
        raise HTTPException(status_code=404, detail="No ingestion jobs found")
    return max(jobs, key=lambda item: item.get("updated_at", ""))


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper(paper_id: str, user_id: str = Depends(get_current_user)):
    """Get a single paper's metadata."""
    try:
        rows = kuzu_client.execute(
            "MATCH (p:Paper) WHERE p.paper_id = $pid AND p.user_id = $uid "
            "RETURN p.paper_id, p.title, p.pub_year, p.venue",
            {"pid": paper_id, "uid": user_id},
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Paper not found")
        p = rows[0]
        return PaperResponse(
            paper_id=p["p.paper_id"],
            title=p["p.title"],
            pub_year=p.get("p.pub_year"),
            venue=p.get("p.venue"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

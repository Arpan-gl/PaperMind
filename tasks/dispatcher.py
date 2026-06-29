"""Select a reliable ingestion executor for API uploads."""

import os
from threading import Thread


def dispatch_ingestion(pdf_path: str, user_id: str, task_id: str) -> str:
    """Use a local worker by default; Celery is opt-in when a worker is managed."""
    from api.papers import update_job

    use_celery = os.environ.get("PAPERMIND_USE_CELERY", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    if use_celery:
        from redis import Redis
        from tasks.celery_tasks import ingest_paper_task

        Redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        ).ping()
        ingest_paper_task.apply_async(
            args=[pdf_path, user_id, task_id],
            task_id=task_id,
        )
        return "celery"

    from tasks.fast_ingestion import run_ingestion_job

    update_job(
        task_id,
        status="queued",
        stage="Starting local worker",
        progress=10,
        executor="thread",
    )
    worker = Thread(
        target=run_ingestion_job,
        args=(pdf_path, user_id, task_id),
        daemon=True,
        name=f"papermind-ingest-{task_id[:8]}",
    )
    worker.start()
    return "thread"

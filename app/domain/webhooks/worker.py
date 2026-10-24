
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.domain.webhooks.delivery_service import (
    MAX_ATTEMPTS,
    RETRY_DELAYS,
    deliver_event,
)
from app.domain.webhooks.models import WebhookEvent, WebhookJob
from app.infrastructure.database.session import SessionLocal

logger = logging.getLogger(__name__)


def recover_stale_jobs(
    session_factory,
    timeout_minutes: int = 10,
) -> int:
    """Return stale processing jobs to the pending state."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=timeout_minutes)

    with session_factory() as db:
        result = db.execute(
            WebhookJob.__table__.update()
            .where(
                WebhookJob.status == "processing",
                WebhookJob.updated_at < cutoff,
            )
            .values(
                status="pending",
                scheduled_at=now,
                updated_at=now,
            )
        )
        db.commit()
        return result.rowcount


def claim_pending_job(session_factory, job_id: str) -> bool:
    """Atomically claim a pending job for processing."""
    with session_factory() as db:
        result = db.execute(
            WebhookJob.__table__.update()
            .where(
                WebhookJob.id == job_id,
                WebhookJob.status == "pending",
            )
            .values(
                status="processing",
                updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        return result.rowcount == 1


def process_pending_jobs(
    session_factory: sessionmaker,
    batch_size: int = 10,
) -> int:
    """Process a batch of due webhook jobs without blocking on retries."""
    processed = 0
    recover_stale_jobs(session_factory)
    now = datetime.now(timezone.utc)

    with session_factory() as db:
        jobs = db.scalars(
            select(WebhookJob)
            .where(
                WebhookJob.status == "pending",
                WebhookJob.scheduled_at <= now,
            )
            .order_by(WebhookJob.scheduled_at)
            .limit(batch_size)
        ).all()
        job_ids = [job.id for job in jobs]

    for job_id in job_ids:
        if not claim_pending_job(session_factory, job_id):
            continue

        with session_factory() as db:
            job = db.get(WebhookJob, job_id)
            if job is None:
                continue

            event = db.get(WebhookEvent, job.event_id)
            if event is None:
                job.status = "failed"
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
                processed += 1
                continue

            attempt_number = job.attempts + 1

            try:
                result = deliver_event(
                    db,
                    event,
                    attempt_number=attempt_number,
                )

                delivery = result.delivery
                job.attempts = attempt_number
                now = datetime.now(timezone.utc)

                if delivery.status == "succeeded":
                    job.status = "completed"

                elif result.should_retry and attempt_number < MAX_ATTEMPTS:
                    delay = (
                        result.retry_after
                        if result.retry_after is not None
                        else RETRY_DELAYS[attempt_number - 1]
                    )
                    job.status = "pending"
                    job.scheduled_at = now + timedelta(seconds=delay)

                else:
                    job.status = "failed"

                job.updated_at = now
                db.commit()
                processed += 1

            except (ValueError, RuntimeError):
                db.rollback()
                job = db.get(WebhookJob, job_id)

                if job is not None:
                    job.status = "failed"
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()

                processed += 1

    return processed


def run_worker(poll_interval: float = 2.0) -> None:
    """Continuously process pending webhook jobs."""
    logger.info("HookFlow worker started")

    try:
        while True:
            try:
                process_pending_jobs(SessionLocal)
            except Exception:
                logger.exception("Worker polling cycle failed")

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("HookFlow worker stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_worker()
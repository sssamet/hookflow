
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.webhooks.delivery_service import DeliveryResult
from app.domain.webhooks.models import (
    Webhook,
    WebhookDelivery,
    WebhookEvent,
    WebhookJob,
)
from app.domain.webhooks.worker import process_pending_jobs, recover_stale_jobs
from app.infrastructure.database.base import Base


def create_test_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    return engine, test_session


def create_job(test_session, name="Worker Test", status="pending"):
    with test_session() as db:
        webhook = Webhook(
            name=name,
            target_url="https://example.com/webhook",
        )
        db.add(webhook)
        db.flush()

        event = WebhookEvent(
            webhook_id=webhook.id,
            event_type="user.created",
            payload={"user_id": 123},
        )
        db.add(event)
        db.flush()

        job = WebhookJob(
            event_id=event.id,
            status=status,
        )
        db.add(job)
        db.commit()
        return job.id, event.id


def fake_result(status, attempt_number, should_retry=False, retry_after=None):
    delivery = WebhookDelivery(
        event_id="fake-event-id",
        attempt_number=attempt_number,
        status=status,
    )
    return SimpleNamespace(
        delivery=delivery,
        should_retry=should_retry,
        retry_after=retry_after,
    )


def test_worker_completes_successful_job(monkeypatch):
    engine, test_session = create_test_database()

    try:
        job_id, _ = create_job(test_session)

        def fake_deliver(db, event, attempt_number=1):
            delivery = WebhookDelivery(
                event_id=event.id,
                attempt_number=attempt_number,
                status="succeeded",
            )
            return DeliveryResult(
                delivery=delivery,
                should_retry=False,
            )

        monkeypatch.setattr(
            "app.domain.webhooks.worker.deliver_event",
            fake_deliver,
        )

        processed = process_pending_jobs(test_session)

        assert processed == 1

        with test_session() as db:
            job = db.get(WebhookJob, job_id)
            assert job is not None
            assert job.status == "completed"
            assert job.attempts == 1

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_worker_marks_permanent_failure(monkeypatch):
    engine, test_session = create_test_database()

    try:
        job_id, _ = create_job(test_session)

        def fake_deliver(db, event, attempt_number=1):
            delivery = WebhookDelivery(
                event_id=event.id,
                attempt_number=attempt_number,
                status="failed",
            )
            return DeliveryResult(
                delivery=delivery,
                should_retry=False,
            )

        monkeypatch.setattr(
            "app.domain.webhooks.worker.deliver_event",
            fake_deliver,
        )

        processed = process_pending_jobs(test_session)

        assert processed == 1

        with test_session() as db:
            job = db.get(WebhookJob, job_id)
            assert job is not None
            assert job.status == "failed"
            assert job.attempts == 1

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_worker_reschedules_transient_failure(monkeypatch):
    engine, test_session = create_test_database()

    try:
        job_id, _ = create_job(test_session)
        calls = []

        def fake_deliver(db, event, attempt_number=1):
            calls.append(attempt_number)
            delivery = WebhookDelivery(
                event_id=event.id,
                attempt_number=attempt_number,
                status="failed",
            )
            return DeliveryResult(
                delivery=delivery,
                should_retry=True,
                retry_after=5,
            )

        monkeypatch.setattr(
            "app.domain.webhooks.worker.deliver_event",
            fake_deliver,
        )

        before = datetime.now(timezone.utc)
        processed = process_pending_jobs(test_session)

        assert processed == 1
        assert calls == [1]

        with test_session() as db:
            job = db.get(WebhookJob, job_id)
            assert job is not None
            assert job.status == "pending"
            assert job.attempts == 1

            scheduled_at = job.scheduled_at
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

            assert scheduled_at >= before + timedelta(seconds=4)

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_worker_fails_after_max_attempts(monkeypatch):
    engine, test_session = create_test_database()

    try:
        job_id, _ = create_job(test_session)

        with test_session() as db:
            job = db.get(WebhookJob, job_id)
            job.attempts = 2
            db.commit()

        def fake_deliver(db, event, attempt_number=1):
            delivery = WebhookDelivery(
                event_id=event.id,
                attempt_number=attempt_number,
                status="failed",
            )
            return DeliveryResult(
                delivery=delivery,
                should_retry=True,
            )

        monkeypatch.setattr(
            "app.domain.webhooks.worker.deliver_event",
            fake_deliver,
        )

        processed = process_pending_jobs(test_session)

        assert processed == 1

        with test_session() as db:
            job = db.get(WebhookJob, job_id)
            assert job is not None
            assert job.status == "failed"
            assert job.attempts == 3

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_worker_skips_job_already_processing(monkeypatch):
    engine, test_session = create_test_database()

    try:
        create_job(test_session, status="processing")

        monkeypatch.setattr(
            "app.domain.webhooks.worker.deliver_event",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("Processing job should not be delivered")
            ),
        )

        processed = process_pending_jobs(test_session)

        assert processed == 0

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_recover_stale_job():
    engine, test_session = create_test_database()

    try:
        job_id, _ = create_job(test_session)

        with test_session() as db:
            job = db.get(WebhookJob, job_id)
            job.status = "processing"
            job.updated_at = datetime.now(timezone.utc) - timedelta(
                minutes=15
            )
            db.commit()

        recovered = recover_stale_jobs(test_session)

        assert recovered == 1

        with test_session() as db:
            job = db.get(WebhookJob, job_id)
            assert job is not None
            assert job.status == "pending"

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_worker_delivers_event_and_records_delivery(monkeypatch):
    from app.domain.webhooks import delivery_service

    engine, test_session = create_test_database()

    try:
        job_id, event_id = create_job(
            test_session,
            name="Delivery Integration Test",
        )

        monkeypatch.setattr(
            delivery_service,
            "validate_target_url",
            lambda url: None,
        )
        monkeypatch.setattr(
            delivery_service,
            "_post_request",
            lambda url, payload, signature: httpx.Response(
                200,
                request=httpx.Request("POST", url),
                text="delivered",
            ),
        )

        processed = process_pending_jobs(test_session)

        assert processed == 1

        with test_session() as db:
            job = db.get(WebhookJob, job_id)
            assert job is not None
            assert job.status == "completed"
            assert job.attempts == 1

            deliveries = db.scalars(
                select(WebhookDelivery).where(
                    WebhookDelivery.event_id == event_id
                )
            ).all()

            assert len(deliveries) == 1
            assert deliveries[0].status == "succeeded"
            assert deliveries[0].attempt_number == 1

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
        

def test_worker_marks_job_failed_on_unexpected_error(monkeypatch):
    engine, test_session = create_test_database()

    try:
        job_id, _ = create_job(test_session)

        def fail_delivery(db, event, attempt_number=1):
            raise OSError("Unexpected delivery failure")

        monkeypatch.setattr(
            "app.domain.webhooks.worker.deliver_event",
            fail_delivery,
        )

        processed = process_pending_jobs(test_session)

        assert processed == 1

        with test_session() as db:
            job = db.get(WebhookJob, job_id)
            assert job is not None
            assert job.status == "failed"

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


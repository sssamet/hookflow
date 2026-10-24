
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.webhooks.models import (
    Webhook,
    WebhookDelivery,
    WebhookEvent,
    WebhookJob,
)
from app.domain.webhooks.worker import process_pending_jobs, recover_stale_jobs
from app.infrastructure.database.base import Base


def test_worker_completes_successful_job(monkeypatch):
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

    try:
        with test_session() as db:
            webhook = Webhook(
                name="Worker Test",
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

            job = WebhookJob(event_id=event.id)
            db.add(job)
            db.commit()
            job_id = job.id

        class FakeDelivery:
            status = "succeeded"
            attempt_number = 1

        monkeypatch.setattr(
            "app.domain.webhooks.worker.deliver_event",
            lambda db, event: FakeDelivery(),
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


def test_worker_marks_failed_job(monkeypatch):
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

    try:
        with test_session() as db:
            webhook = Webhook(
                name="Worker Failure Test",
                target_url="https://example.com/webhook",
            )
            db.add(webhook)
            db.flush()

            event = WebhookEvent(
                webhook_id=webhook.id,
                event_type="user.created",
                payload={"user_id": 456},
            )
            db.add(event)
            db.flush()

            job = WebhookJob(event_id=event.id)
            db.add(job)
            db.commit()
            job_id = job.id

        class FakeDelivery:
            status = "failed"
            attempt_number = 3

        monkeypatch.setattr(
            "app.domain.webhooks.worker.deliver_event",
            lambda db, event: FakeDelivery(),
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

    try:
        with test_session() as db:
            webhook = Webhook(
                name="Processing Test",
                target_url="https://example.com/webhook",
            )
            db.add(webhook)
            db.flush()

            event = WebhookEvent(
                webhook_id=webhook.id,
                event_type="user.created",
                payload={"user_id": 789},
            )
            db.add(event)
            db.flush()

            job = WebhookJob(
                event_id=event.id,
                status="processing",
            )
            db.add(job)
            db.commit()

        monkeypatch.setattr(
            "app.domain.webhooks.worker.deliver_event",
            lambda db, event: (_ for _ in ()).throw(
                AssertionError("Processing job should not be delivered")
            ),
        )

        processed = process_pending_jobs(test_session)

        assert processed == 0

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()



def test_recover_stale_job():
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

    try:
        with test_session() as db:
            webhook = Webhook(
                name="Recovery Test",
                target_url="https://example.com/webhook",
            )
            db.add(webhook)
            db.flush()

            event = WebhookEvent(
                webhook_id=webhook.id,
                event_type="user.created",
                payload={"user_id": 999},
            )
            db.add(event)
            db.flush()

            job = WebhookJob(
                event_id=event.id,
                status="processing",
                updated_at=datetime.now(timezone.utc)
                - timedelta(minutes=15),
            )
            db.add(job)
            db.commit()
            job_id = job.id

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

    try:
        with test_session() as db:
            webhook = Webhook(
                name="Delivery Integration Test",
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

            job = WebhookJob(event_id=event.id)
            db.add(job)
            db.commit()
            job_id = job.id

        from app.domain.webhooks import delivery_service

        monkeypatch.setattr(
            delivery_service,
            "validate_target_url",
            lambda url: None,
        )
        monkeypatch.setattr(
            delivery_service,
            "sleep",
            lambda seconds: None,
        )
        monkeypatch.setattr(
            delivery_service,
            "_post_request",
            lambda url, payload: __import__("httpx").Response(
                200,
                request=__import__("httpx").Request("POST", url),
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
                    WebhookDelivery.event_id == job.event_id
                )
            ).all()

            assert len(deliveries) == 1
            assert deliveries[0].status == "succeeded"
            assert deliveries[0].attempt_number == 1

    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

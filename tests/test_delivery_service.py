
import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.webhooks import delivery_service
from app.domain.webhooks.models import (
    Webhook,
    WebhookDelivery,
    WebhookEvent,
)
from app.infrastructure.database.base import Base


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    session = testing_session_local()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def event(db):
    webhook = Webhook(
        name="Test Webhook",
        target_url="https://example.com/webhook",
    )
    db.add(webhook)
    db.flush()

    webhook_event = WebhookEvent(
        webhook_id=webhook.id,
        event_type="test.created",
        payload={"test": True},
    )
    db.add(webhook_event)
    db.commit()
    db.refresh(webhook_event)

    return webhook_event


@pytest.fixture(autouse=True)
def mock_delivery_dependencies(monkeypatch):
    monkeypatch.setattr(
        delivery_service,
        "validate_target_url",
        lambda url: None,
    )


def response(status_code, text="result", headers=None):
    return httpx.Response(
        status_code,
        headers=headers,
        request=httpx.Request(
            "POST",
            "https://example.com/webhook",
        ),
        text=text,
    )


def test_successful_delivery_makes_one_attempt(db, event, monkeypatch):
    calls = []

    def fake_post(url, payload, signature):
        calls.append(url)
        return response(200, "delivered")

    monkeypatch.setattr(delivery_service, "_post_request", fake_post)

    result = delivery_service.deliver_event(
        db,
        event,
        attempt_number=1,
    )

    assert result.delivery.status == "succeeded"
    assert result.delivery.attempt_number == 1
    assert result.should_retry is False
    assert len(calls) == 1


def test_timeout_returns_retryable_result(db, event, monkeypatch):
    calls = []

    def fake_post(url, payload, signature):
        calls.append(url)
        raise asyncio.TimeoutError

    monkeypatch.setattr(delivery_service, "_post_request", fake_post)

    result = delivery_service.deliver_event(db, event)

    assert result.delivery.status == "failed"
    assert result.delivery.error_message
    assert result.should_retry is True
    assert len(calls) == 1


def test_server_error_returns_retryable_result(db, event, monkeypatch):
    calls = []

    def fake_post(url, payload, signature):
        calls.append(url)
        return response(503, "Service Unavailable")

    monkeypatch.setattr(delivery_service, "_post_request", fake_post)

    result = delivery_service.deliver_event(db, event)

    assert result.delivery.status == "failed"
    assert result.delivery.response_status_code == 503
    assert result.should_retry is True
    assert len(calls) == 1


def test_client_error_does_not_retry(db, event, monkeypatch):
    calls = []

    def fake_post(url, payload, signature):
        calls.append(url)
        return response(400, "Bad Request")

    monkeypatch.setattr(delivery_service, "_post_request", fake_post)

    result = delivery_service.deliver_event(db, event)

    assert result.delivery.status == "failed"
    assert result.delivery.response_status_code == 400
    assert result.should_retry is False
    assert len(calls) == 1


def test_rate_limit_returns_retryable_result(db, event, monkeypatch):
    monkeypatch.setattr(
        delivery_service,
        "_post_request",
        lambda url, payload, signature: response(429),
    )

    result = delivery_service.deliver_event(db, event)

    assert result.delivery.status == "failed"
    assert result.delivery.response_status_code == 429
    assert result.should_retry is True


def test_respects_retry_after_header(db, event, monkeypatch):
    monkeypatch.setattr(
        delivery_service,
        "_post_request",
        lambda url, payload, signature: response(
            429,
            headers={"Retry-After": "5"},
        ),
    )

    result = delivery_service.deliver_event(db, event)

    assert result.should_retry is True
    assert result.retry_after == 5


def test_delivery_attempt_number_is_preserved(db, event, monkeypatch):
    monkeypatch.setattr(
        delivery_service,
        "_post_request",
        lambda url, payload, signature: response(200),
    )

    result = delivery_service.deliver_event(
        db,
        event,
        attempt_number=2,
    )

    assert result.delivery.attempt_number == 2


def test_delivery_is_persisted(db, event, monkeypatch):
    monkeypatch.setattr(
        delivery_service,
        "_post_request",
        lambda url, payload, signature: response(200),
    )

    delivery_service.deliver_event(db, event)

    deliveries = db.scalars(
        select(WebhookDelivery).where(
            WebhookDelivery.event_id == event.id
        )
    ).all()

    assert len(deliveries) == 1
    assert deliveries[0].status == "succeeded"


def test_parse_retry_after_http_date():
    retry_at = datetime.now(timezone.utc).replace(microsecond=0)
    header_value = format_datetime(retry_at, usegmt=True)

    result = delivery_service._parse_retry_after(header_value)

    assert result is not None
    assert 0 <= result <= 1


def test_parse_retry_after_caps_wait():
    assert delivery_service._parse_retry_after("300") == 60


def test_parse_retry_after_invalid_value():
    assert delivery_service._parse_retry_after("invalid") is None


def test_generate_signature_is_valid():
    payload = b'{"event":"test.created"}'
    secret = "test-secret"

    signature = delivery_service._generate_signature(
        payload,
        secret,
    )

    expected = delivery_service.hmac.new(
        secret.encode("utf-8"),
        payload,
        delivery_service.hashlib.sha256,
    ).hexdigest()

    assert signature == f"sha256={expected}"


def test_generate_signature_changes_with_payload():
    secret = "test-secret"

    original_signature = delivery_service._generate_signature(
        b'{"event":"test.created"}',
        secret,
    )
    modified_signature = delivery_service._generate_signature(
        b'{"event":"test.updated"}',
        secret,
    )

    assert original_signature != modified_signature


def test_generate_signature_changes_with_secret():
    payload = b'{"event":"test.created"}'

    first_signature = delivery_service._generate_signature(
        payload,
        "first-secret",
    )
    second_signature = delivery_service._generate_signature(
        payload,
        "second-secret",
    )

    assert first_signature != second_signature

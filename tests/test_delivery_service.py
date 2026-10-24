import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.webhooks import delivery_service
from app.domain.webhooks.models import (
    Webhook,
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
    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()

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
    monkeypatch.setattr(
        delivery_service,
        "sleep",
        lambda seconds: None,
    )


def response(status_code, text="result", headers=None):
    return httpx.Response(
        status_code,
        headers=headers,
        request=httpx.Request("POST", "https://example.com/webhook"),
        text=text,
    )


def test_retries_after_timeout(db, event, monkeypatch):
    attempts = 0

    def fake_post(url, payload, signature):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise asyncio.TimeoutError
        return response(200, "delivered")

    monkeypatch.setattr(delivery_service, "_post_request", fake_post)

    result = delivery_service.deliver_event(db, event)

    assert result.status == "succeeded"
    assert result.attempt_number == 3
    assert attempts == 3


def test_retries_after_server_error(db, event, monkeypatch):
    attempts = 0

    def fake_post(url, payload, signature):
        nonlocal attempts
        attempts += 1
        return response(503) if attempts == 1 else response(200)

    monkeypatch.setattr(delivery_service, "_post_request", fake_post)

    result = delivery_service.deliver_event(db, event)

    assert result.status == "succeeded"
    assert result.attempt_number == 2
    assert attempts == 2


def test_does_not_retry_after_client_error(db, event, monkeypatch):
    attempts = 0

    def fake_post(url, payload, signature):
        nonlocal attempts
        attempts += 1
        return response(400, "Bad Request")

    monkeypatch.setattr(delivery_service, "_post_request", fake_post)

    result = delivery_service.deliver_event(db, event)

    assert result.status == "failed"
    assert result.attempt_number == 1
    assert attempts == 1


def test_retries_after_rate_limit(db, event, monkeypatch):
    attempts = 0

    def fake_post(url, payload, signature):
        nonlocal attempts
        attempts += 1
        return response(429) if attempts == 1 else response(200)

    monkeypatch.setattr(delivery_service, "_post_request", fake_post)

    result = delivery_service.deliver_event(db, event)

    assert result.status == "succeeded"
    assert result.attempt_number == 2
    assert attempts == 2


def test_respects_retry_after(db, event, monkeypatch):
    attempts = 0
    sleep_calls = []

    def fake_post(url, payload, signature):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return response(429, headers={"Retry-After": "5"})
        return response(200)

    monkeypatch.setattr(delivery_service, "_post_request", fake_post)
    monkeypatch.setattr(
        delivery_service,
        "sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    result = delivery_service.deliver_event(db, event)

    assert result.status == "succeeded"
    assert attempts == 2
    assert sleep_calls == [5]


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

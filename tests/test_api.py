import asyncio
from email.utils import format_datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.domain.webhooks import delivery_service
from app.domain.webhooks.url_validator import validate_target_url
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import get_db
from app.main import app


@pytest.fixture
def client(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Tests do not need real DNS lookups.
    monkeypatch.setattr(
        main_module,
        "validate_target_url",
        lambda url: None,
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def test_health_endpoint(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_webhook(client):
    response = client.post(
        "/webhooks",
        json={
            "name": "Test Webhook",
            "target_url": "https://example.com/webhook",
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["name"] == "Test Webhook"
    assert data["target_url"] == "https://example.com/webhook"
    assert "id" in data


def test_event_for_missing_webhook_returns_404(client):
    response = client.post(
        "/webhooks/00000000-0000-0000-0000-000000000001/events",
        json={
            "event_type": "user.created",
            "payload": {"user_id": 123},
        },
    )

    assert response.status_code == 404


def test_http_target_url_is_rejected():
    with pytest.raises(ValueError):
        validate_target_url("http://127.0.0.1:8000")


def test_async_post_request_enforces_total_timeout(monkeypatch):
    class SlowAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, json):
            await asyncio.sleep(0.1)
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(delivery_service, "REQUEST_TIMEOUT", 0.01)
    monkeypatch.setattr(
        delivery_service.httpx,
        "AsyncClient",
        SlowAsyncClient,
    )

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            delivery_service._async_post_request(
                "https://example.com/webhook",
                {"event": "test"},
            )
        )


def test_event_delivery_retries_after_timeout(client, monkeypatch):
    attempts = 0

    def fake_post_request(url, payload):
        nonlocal attempts
        attempts += 1

        if attempts < 3:
            raise asyncio.TimeoutError

        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            text="delivered",
        )

    monkeypatch.setattr(
        delivery_service,
        "_post_request",
        fake_post_request,
    )
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

    webhook_response = client.post(
        "/webhooks",
        json={
            "name": "Retry Test",
            "target_url": "https://example.com/webhook",
        },
    )
    assert webhook_response.status_code == 201

    webhook_id = webhook_response.json()["id"]

    response = client.post(
        f"/webhooks/{webhook_id}/events",
        json={
            "event_type": "test.created",
            "payload": {"test": True},
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["delivery"]["status"] == "succeeded"
    assert data["delivery"]["attempt_number"] == 3
    assert attempts == 3


def test_event_delivery_retries_after_server_error(client, monkeypatch):
    attempts = 0

    def fake_post_request(url, payload):
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return httpx.Response(
                503,
                request=httpx.Request("POST", url),
                text="Service unavailable",
            )

        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            text="delivered",
        )

    monkeypatch.setattr(
        delivery_service,
        "_post_request",
        fake_post_request,
    )
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

    webhook_response = client.post(
        "/webhooks",
        json={
            "name": "Server Error Retry Test",
            "target_url": "https://example.com/webhook",
        },
    )
    assert webhook_response.status_code == 201

    webhook_id = webhook_response.json()["id"]

    response = client.post(
        f"/webhooks/{webhook_id}/events",
        json={
            "event_type": "test.created",
            "payload": {"test": True},
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["delivery"]["status"] == "succeeded"
    assert data["delivery"]["attempt_number"] == 2
    assert attempts == 2


def test_event_delivery_does_not_retry_after_client_error(client, monkeypatch):
    attempts = 0

    def fake_post_request(url, payload):
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            400,
            request=httpx.Request("POST", url),
            text="Bad Request",
        )

    monkeypatch.setattr(
        delivery_service,
        "_post_request",
        fake_post_request,
    )
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

    webhook_response = client.post(
        "/webhooks",
        json={
            "name": "Client Error Test",
            "target_url": "https://example.com/webhook",
        },
    )
    assert webhook_response.status_code == 201

    webhook_id = webhook_response.json()["id"]

    response = client.post(
        f"/webhooks/{webhook_id}/events",
        json={
            "event_type": "test.created",
            "payload": {"test": True},
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["delivery"]["status"] == "failed"
    assert data["delivery"]["attempt_number"] == 1
    assert attempts == 1


def test_event_delivery_retries_after_rate_limit(client, monkeypatch):
    attempts = 0

    def fake_post_request(url, payload):
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return httpx.Response(
                429,
                request=httpx.Request("POST", url),
                text="Too Many Requests",
            )

        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            text="delivered",
        )

    monkeypatch.setattr(
        delivery_service,
        "_post_request",
        fake_post_request,
    )
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

    webhook_response = client.post(
        "/webhooks",
        json={
            "name": "Rate Limit Retry Test",
            "target_url": "https://example.com/webhook",
        },
    )
    assert webhook_response.status_code == 201

    webhook_id = webhook_response.json()["id"]

    response = client.post(
        f"/webhooks/{webhook_id}/events",
        json={
            "event_type": "test.created",
            "payload": {"test": True},
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["delivery"]["status"] == "succeeded"
    assert data["delivery"]["attempt_number"] == 2
    assert attempts == 2


def test_event_delivery_respects_retry_after(client, monkeypatch):
    attempts = 0
    sleep_calls = []

    def fake_post_request(url, payload):
        nonlocal attempts
        attempts += 1

        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "5"},
                request=httpx.Request("POST", url),
                text="Too Many Requests",
            )

        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            text="delivered",
        )

    monkeypatch.setattr(
        delivery_service,
        "_post_request",
        fake_post_request,
    )
    monkeypatch.setattr(
        delivery_service,
        "validate_target_url",
        lambda url: None,
    )
    monkeypatch.setattr(
        delivery_service,
        "sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    webhook_response = client.post(
        "/webhooks",
        json={
            "name": "Retry After Test",
            "target_url": "https://example.com/webhook",
        },
    )
    assert webhook_response.status_code == 201

    webhook_id = webhook_response.json()["id"]

    response = client.post(
        f"/webhooks/{webhook_id}/events",
        json={
            "event_type": "test.created",
            "payload": {"test": True},
        },
    )

    assert response.status_code == 201
    assert response.json()["delivery"]["status"] == "succeeded"
    assert attempts == 2
    assert sleep_calls == [5]


def test_parse_retry_after_http_date():
    from datetime import datetime, timedelta, timezone

    from app.domain.webhooks.delivery_service import _parse_retry_after

    retry_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    header_value = format_datetime(retry_at, usegmt=True)

    result = _parse_retry_after(header_value)

    assert result is not None
    assert 0 <= result <= 30


def test_parse_retry_after_caps_wait():
    assert delivery_service._parse_retry_after("300") == 60


def test_parse_retry_after_invalid_value():
    assert delivery_service._parse_retry_after("invalid") is None

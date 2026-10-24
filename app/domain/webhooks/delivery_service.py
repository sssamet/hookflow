
import asyncio
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import perf_counter

import httpx
from sqlalchemy.orm import Session

from app.domain.webhooks.models import WebhookDelivery, WebhookEvent
from app.domain.webhooks.url_validator import validate_target_url

MAX_ATTEMPTS = 3
RETRY_DELAYS = (1, 2)
MAX_RETRY_AFTER = 60
REQUEST_TIMEOUT = 10.0
MAX_RESPONSE_BODY_LENGTH = 4000
MAX_ERROR_MESSAGE_LENGTH = 2000
SIGNATURE_HEADER = "X-HookFlow-Signature"


@dataclass(frozen=True)
class DeliveryResult:
    delivery: WebhookDelivery
    should_retry: bool
    retry_after: int | None = None


def _serialize_payload(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _generate_signature(payload_bytes: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


async def _async_post_request(
    url: str,
    payload_bytes: bytes,
    signature: str,
) -> httpx.Response:
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=False,
    ) as client:
        return await asyncio.wait_for(
            client.post(
                url,
                content=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    SIGNATURE_HEADER: signature,
                },
            ),
            timeout=REQUEST_TIMEOUT,
        )


def _post_request(
    url: str,
    payload_bytes: bytes,
    signature: str,
) -> httpx.Response:
    return asyncio.run(
        _async_post_request(url, payload_bytes, signature)
    )


def _parse_retry_after(value: str) -> int | None:
    try:
        seconds = int(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)

            seconds = int(
                (retry_at - datetime.now(timezone.utc)).total_seconds()
            )
        except (TypeError, ValueError, OverflowError):
            return None

    return min(MAX_RETRY_AFTER, max(0, seconds))


def deliver_event(
    db: Session,
    event: WebhookEvent,
    attempt_number: int = 1,
) -> DeliveryResult:
    """Perform and persist exactly one webhook delivery attempt."""
    delivery = WebhookDelivery(
        event_id=event.id,
        attempt_number=attempt_number,
        status="pending",
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    started_at = perf_counter()
    should_retry = False
    retry_after = None

    try:
        target_url = event.webhook.target_url
        validate_target_url(target_url)

        payload = {
            "id": event.id,
            "type": event.event_type,
            "payload": event.payload,
            "created_at": event.created_at.isoformat(),
        }

        payload_bytes = _serialize_payload(payload)
        signature = _generate_signature(
            payload_bytes,
            event.webhook.signing_secret,
        )

        response = _post_request(
            target_url,
            payload_bytes,
            signature,
        )

        delivery.response_status_code = response.status_code
        delivery.response_body = response.text[:MAX_RESPONSE_BODY_LENGTH]

        if 200 <= response.status_code < 300:
            delivery.status = "succeeded"
        else:
            delivery.status = "failed"
            should_retry = (
                response.status_code == 429
                or response.status_code >= 500
            )

            if response.status_code == 429:
                header_value = response.headers.get("Retry-After")
                if header_value is not None:
                    retry_after = _parse_retry_after(header_value)

    except (asyncio.TimeoutError, httpx.TimeoutException):
        delivery.status = "failed"
        delivery.error_message = (
            f"Webhook request exceeded the {REQUEST_TIMEOUT}-second timeout."
        )[:MAX_ERROR_MESSAGE_LENGTH]
        should_retry = True

    except ValueError as exc:
        delivery.status = "failed"
        delivery.error_message = str(exc)[:MAX_ERROR_MESSAGE_LENGTH]

    except httpx.HTTPError as exc:
        delivery.status = "failed"
        delivery.error_message = str(exc)[:MAX_ERROR_MESSAGE_LENGTH]
        should_retry = True

    finally:
        delivery.duration_ms = round(
            (perf_counter() - started_at) * 1000
        )
        db.commit()
        db.refresh(delivery)

    return DeliveryResult(
        delivery=delivery,
        should_retry=should_retry,
        retry_after=retry_after,
    )

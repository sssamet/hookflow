import asyncio
from time import perf_counter, sleep

import httpx
from sqlalchemy.orm import Session

from app.domain.webhooks.models import WebhookDelivery, WebhookEvent
from app.domain.webhooks.url_validator import validate_target_url

MAX_ATTEMPTS = 3
RETRY_DELAYS = (1, 2)
REQUEST_TIMEOUT = 10.0
MAX_RESPONSE_BODY_LENGTH = 4000
MAX_ERROR_MESSAGE_LENGTH = 2000


async def _async_post_request(
    url: str,
    payload: dict,
) -> httpx.Response:
    """Send a webhook request with a total execution deadline."""
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        follow_redirects=False,
    ) as client:
        return await asyncio.wait_for(
            client.post(url, json=payload),
            timeout=REQUEST_TIMEOUT,
        )


def _post_request(url: str, payload: dict) -> httpx.Response:
    """Run the async HTTP request from the synchronous service."""
    return asyncio.run(_async_post_request(url, payload))


def deliver_event(db: Session, event: WebhookEvent) -> WebhookDelivery:
    """Deliver an event and record each attempt in the database."""
    last_delivery = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            sleep(RETRY_DELAYS[attempt - 2])

        delivery = WebhookDelivery(
            event_id=event.id,
            attempt_number=attempt,
            status="pending",
        )

        db.add(delivery)
        db.commit()
        db.refresh(delivery)

        last_delivery = delivery
        started_at = perf_counter()
        should_retry = False

        try:
            target_url = event.webhook.target_url
            validate_target_url(target_url)

            payload = {
                "id": event.id,
                "type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }

            response = _post_request(target_url, payload)

            delivery.response_status_code = response.status_code
            delivery.response_body = response.text[:MAX_RESPONSE_BODY_LENGTH]

            if 200 <= response.status_code < 300:
                delivery.status = "succeeded"
            else:
                delivery.status = "failed"
                should_retry = (
                    response.status_code == 429 or response.status_code >= 500
                )

        except asyncio.TimeoutError:
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
            delivery.duration_ms = round((perf_counter() - started_at) * 1000)
            db.commit()
            db.refresh(delivery)

        if delivery.status == "succeeded":
            return delivery

        if not should_retry or attempt == MAX_ATTEMPTS:
            return delivery

    return last_delivery

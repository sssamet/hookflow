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


def deliver_event(db: Session, event: WebhookEvent) -> WebhookDelivery:
    """Deliver an event and record each attempt in the database."""
    last_delivery = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # Keep retries bounded to avoid endless delivery attempts.
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
            validate_target_url(event.webhook.target_url)

            with httpx.Client(
                timeout=REQUEST_TIMEOUT,
                follow_redirects=False,
            ) as client:
                response = client.post(
                    event.webhook.target_url,
                    json={
                        "id": event.id,
                        "type": event.event_type,
                        "payload": event.payload,
                        "created_at": event.created_at.isoformat(),
                    },
                )

            delivery.response_status_code = response.status_code
            delivery.response_body = response.text[:MAX_RESPONSE_BODY_LENGTH]

            if 200 <= response.status_code < 300:
                delivery.status = "succeeded"
            else:
                delivery.status = "failed"
                should_retry = (
                    response.status_code == 429 or response.status_code >= 500
                )

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

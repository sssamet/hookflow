from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.webhooks.delivery_service import deliver_event
from app.domain.webhooks.models import Webhook, WebhookDelivery, WebhookEvent
from app.domain.webhooks.url_validator import validate_target_url
from app.infrastructure.database.session import get_db

app = FastAPI(
    title="HookFlow API",
    description="Reliable webhook delivery platform",
    version="0.4.0",
)


class WebhookCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    target_url: HttpUrl


class EventCreate(BaseModel):
    event_type: str = Field(min_length=2, max_length=100)
    payload: dict[str, Any]


class WebhookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    target_url: str
    created_at: datetime


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    webhook_id: UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_id: UUID
    attempt_number: int
    status: str
    response_status_code: int | None
    response_body: str | None
    error_message: str | None
    duration_ms: int | None
    attempted_at: datetime


class EventCreatedResponse(BaseModel):
    event: EventResponse
    delivery: DeliveryResponse


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "hookflow",
    }


@app.post(
    "/webhooks",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_webhook(
    data: WebhookCreate,
    db: Session = Depends(get_db),
):
    try:
        validate_target_url(str(data.target_url))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    webhook = Webhook(
        name=data.name,
        target_url=str(data.target_url),
    )

    db.add(webhook)
    db.commit()
    db.refresh(webhook)

    return webhook


@app.get("/webhooks", response_model=list[WebhookResponse])
def list_webhooks(db: Session = Depends(get_db)):
    return db.scalars(select(Webhook).order_by(Webhook.created_at.desc())).all()


@app.post(
    "/webhooks/{webhook_id}/events",
    response_model=EventCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_event(
    webhook_id: UUID,
    data: EventCreate,
    db: Session = Depends(get_db),
):
    webhook = db.get(Webhook, str(webhook_id))

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found",
        )

    event = WebhookEvent(
        webhook_id=webhook.id,
        event_type=data.event_type,
        payload=data.payload,
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    delivery = deliver_event(db, event)

    return {
        "event": event,
        "delivery": delivery,
    }


@app.get(
    "/webhooks/{webhook_id}/events",
    response_model=list[EventResponse],
)
def list_events(
    webhook_id: UUID,
    db: Session = Depends(get_db),
):
    if db.get(Webhook, str(webhook_id)) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found",
        )

    return db.scalars(
        select(WebhookEvent)
        .where(WebhookEvent.webhook_id == str(webhook_id))
        .order_by(WebhookEvent.created_at.desc())
    ).all()


@app.get(
    "/webhooks/{webhook_id}/events/{event_id}/deliveries",
    response_model=list[DeliveryResponse],
)
def list_deliveries(
    webhook_id: UUID,
    event_id: UUID,
    db: Session = Depends(get_db),
):
    webhook = db.get(Webhook, str(webhook_id))

    if webhook is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook not found",
        )

    event = db.get(WebhookEvent, str(event_id))

    if event is None or event.webhook_id != webhook.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    return db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.event_id == event.id)
        .order_by(WebhookDelivery.attempted_at.desc())
    ).all()

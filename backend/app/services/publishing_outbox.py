from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import socket
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import PublishingJob, PublishingOutbox, SyncJob


OUTBOX_LEASE_SECONDS = 60
OUTBOX_BATCH_SIZE = 100


@dataclass(frozen=True)
class PublishingOutboxClaim:
    outbox_id: str
    publishing_job_id: str
    lease_owner: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _lease_owner() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4()}"


def claim_publishing_outbox(
    db: Session,
    *,
    publishing_job_id: str | None = None,
    now: datetime | None = None,
    batch_size: int = OUTBOX_BATCH_SIZE,
) -> tuple[PublishingOutboxClaim, ...]:
    claimed_at = now or _utc_now()
    statement = (
        select(PublishingOutbox)
        .join(PublishingJob, PublishingJob.id == PublishingOutbox.publishing_job_id)
        .join(SyncJob, SyncJob.id == PublishingJob.sync_job_id)
        .where(
            PublishingOutbox.available_at <= claimed_at,
            or_(
                PublishingOutbox.status == "pending",
                (
                    (PublishingOutbox.status == "dispatching")
                    & PublishingOutbox.lease_expires_at.is_not(None)
                    & (PublishingOutbox.lease_expires_at <= claimed_at)
                ),
            ),
            PublishingJob.status == "queued",
            SyncJob.status == "queued",
        )
        .order_by(PublishingOutbox.available_at.asc(), PublishingOutbox.created_at.asc())
        .limit(max(1, min(batch_size, OUTBOX_BATCH_SIZE)))
        .with_for_update(skip_locked=True)
    )
    if publishing_job_id is not None:
        statement = statement.where(PublishingOutbox.publishing_job_id == publishing_job_id)
    rows = db.scalars(statement).all()
    claims: list[PublishingOutboxClaim] = []
    for row in rows:
        owner = _lease_owner()
        row.status = "dispatching"
        row.lease_owner = owner
        row.lease_expires_at = claimed_at + timedelta(seconds=OUTBOX_LEASE_SECONDS)
        row.attempt_count += 1
        claims.append(
            PublishingOutboxClaim(
                outbox_id=row.id,
                publishing_job_id=row.publishing_job_id,
                lease_owner=owner,
            )
        )
    db.commit()
    return tuple(claims)


def mark_publishing_outbox_dispatched(
    db: Session,
    *,
    claim: PublishingOutboxClaim,
    now: datetime | None = None,
) -> bool:
    row = db.scalar(
        select(PublishingOutbox)
        .where(
            PublishingOutbox.id == claim.outbox_id,
            PublishingOutbox.status == "dispatching",
            PublishingOutbox.lease_owner == claim.lease_owner,
        )
        .with_for_update(skip_locked=True)
    )
    if row is None:
        db.rollback()
        return False
    row.status = "dispatched"
    row.dispatched_at = now or _utc_now()
    row.lease_owner = None
    row.lease_expires_at = None
    row.last_error = None
    db.commit()
    return True


def release_publishing_outbox_claim(
    db: Session,
    *,
    claim: PublishingOutboxClaim,
    error_message: str,
    now: datetime | None = None,
) -> bool:
    released_at = now or _utc_now()
    row = db.scalar(
        select(PublishingOutbox)
        .where(
            PublishingOutbox.id == claim.outbox_id,
            PublishingOutbox.status == "dispatching",
            PublishingOutbox.lease_owner == claim.lease_owner,
        )
        .with_for_update(skip_locked=True)
    )
    if row is None:
        db.rollback()
        return False
    retry_delay = min(2 ** min(row.attempt_count, 6), 60)
    row.status = "pending"
    row.available_at = released_at + timedelta(seconds=retry_delay)
    row.lease_owner = None
    row.lease_expires_at = None
    row.last_error = " ".join(error_message.split())[:1000]
    db.commit()
    return True


def reset_publishing_outbox(
    db: Session,
    *,
    publishing_job_id: str,
    now: datetime | None = None,
) -> PublishingOutbox | None:
    row = db.scalar(
        select(PublishingOutbox)
        .where(PublishingOutbox.publishing_job_id == publishing_job_id)
        .with_for_update(skip_locked=True)
    )
    if row is None:
        db.rollback()
        return None
    row.status = "pending"
    row.available_at = now or _utc_now()
    row.lease_owner = None
    row.lease_expires_at = None
    row.dispatched_at = None
    db.commit()
    return row

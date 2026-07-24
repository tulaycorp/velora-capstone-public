from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DesignAsset, Mockup
from app.storage import get_storage_service
from app.storage.paths import ORGANIZATIONS_PREFIX


@dataclass
class OrphanCleanupResult:
    dry_run: bool
    scanned: int = 0
    referenced: int = 0
    too_new: int = 0
    orphaned: int = 0
    deleted: int = 0
    failed: int = 0


def cleanup_orphaned_media(
    db: Session,
    *,
    apply: bool = False,
    now: datetime | None = None,
) -> OrphanCleanupResult:
    result = OrphanCleanupResult(dry_run=not apply)
    storage = get_storage_service()
    referenced_keys = set(db.scalars(select(DesignAsset.storage_key)).all())
    referenced_keys.update(db.scalars(select(Mockup.storage_key)).all())
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(
        seconds=settings.storage_orphan_min_age_seconds
    )

    for item in storage.list_objects(f"{ORGANIZATIONS_PREFIX}/"):
        result.scanned += 1
        if item.storage_key in referenced_keys:
            result.referenced += 1
            continue
        last_modified = item.last_modified
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        if last_modified > cutoff:
            result.too_new += 1
            continue
        result.orphaned += 1
        if not apply:
            continue
        try:
            storage.delete_object(item.storage_key)
            result.deleted += 1
        except Exception:
            result.failed += 1

    return result

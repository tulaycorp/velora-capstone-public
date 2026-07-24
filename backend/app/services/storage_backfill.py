from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DesignAsset, Mockup
from app.storage import get_storage_service
from app.storage.paths import build_design_asset_storage_key, build_mockup_storage_key


@dataclass
class StorageBackfillStats:
    scanned: int = 0
    already_scoped: int = 0
    needs_migration: int = 0
    migrated: int = 0
    missing_source: int = 0


@dataclass
class StorageBackfillResult:
    dry_run: bool
    design_assets: StorageBackfillStats = field(default_factory=StorageBackfillStats)
    mockups: StorageBackfillStats = field(default_factory=StorageBackfillStats)


def _backfill_design_assets(
    db: Session,
    *,
    apply: bool,
    stats: StorageBackfillStats,
) -> None:
    storage = get_storage_service()
    rows = db.scalars(select(DesignAsset).order_by(DesignAsset.created_at.asc(), DesignAsset.id.asc())).all()
    for row in rows:
        stats.scanned += 1
        target_key = build_design_asset_storage_key(
            organization_id=row.organization_id,
            design_asset_id=row.id,
            file_name=row.file_name,
        )
        if row.storage_key == target_key:
            stats.already_scoped += 1
            continue

        stats.needs_migration += 1
        if not apply:
            continue

        source_key = row.storage_key
        if not storage.object_exists(target_key):
            if not storage.object_exists(source_key):
                stats.missing_source += 1
                continue
            storage.copy_object(source_key, target_key)

        row.storage_key = target_key
        row.public_url = storage.build_public_url(target_key)
        db.commit()
        stats.migrated += 1

        if storage.object_exists(source_key):
            storage.delete_object(source_key)


def _backfill_mockups(
    db: Session,
    *,
    apply: bool,
    stats: StorageBackfillStats,
) -> None:
    storage = get_storage_service()
    rows = db.scalars(select(Mockup).order_by(Mockup.created_at.asc(), Mockup.id.asc())).all()
    for row in rows:
        stats.scanned += 1
        target_key = build_mockup_storage_key(
            organization_id=row.organization_id,
            draft_id=row.provider_product_draft_id,
            mockup_id=row.id,
            file_name=row.file_name,
        )
        if row.storage_key == target_key:
            stats.already_scoped += 1
            continue

        stats.needs_migration += 1
        if not apply:
            continue

        source_key = row.storage_key
        if not storage.object_exists(target_key):
            if not storage.object_exists(source_key):
                stats.missing_source += 1
                continue
            storage.copy_object(source_key, target_key)

        row.storage_key = target_key
        row.public_url = storage.build_public_url(target_key)
        db.commit()
        stats.migrated += 1

        if storage.object_exists(source_key):
            storage.delete_object(source_key)


def backfill_org_scoped_asset_keys(db: Session, *, apply: bool = False) -> StorageBackfillResult:
    result = StorageBackfillResult(dry_run=not apply)
    _backfill_design_assets(db, apply=apply, stats=result.design_assets)
    _backfill_mockups(db, apply=apply, stats=result.mockups)
    return result

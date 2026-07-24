from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.database import SessionLocal
from app.services.storage_backfill import backfill_org_scoped_asset_keys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill legacy design-asset and mockup storage keys into org-scoped namespaces.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag the script runs in dry-run mode.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        result = backfill_org_scoped_asset_keys(db, apply=args.apply)

    mode = "apply" if args.apply else "dry-run"
    print(f"Mode: {mode}")
    print(
        "Design assets:"
        f" scanned={result.design_assets.scanned}"
        f" already_scoped={result.design_assets.already_scoped}"
        f" needs_migration={result.design_assets.needs_migration}"
        f" migrated={result.design_assets.migrated}"
        f" missing_source={result.design_assets.missing_source}"
    )
    print(
        "Mockups:"
        f" scanned={result.mockups.scanned}"
        f" already_scoped={result.mockups.already_scoped}"
        f" needs_migration={result.mockups.needs_migration}"
        f" migrated={result.mockups.migrated}"
        f" missing_source={result.mockups.missing_source}"
    )
    return 1 if (result.design_assets.missing_source + result.mockups.missing_source) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Operator-only provider store metadata scrub.

Run with --dry-run first and record only the returned counts.  --apply changes
live rows and therefore requires the approved remediation runbook and backup.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove opaque provider-store metadata safely.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    from app.db.database import SessionLocal
    from app.services.store_metadata import scrub_provider_store_metadata

    with SessionLocal() as db:
        result = scrub_provider_store_metadata(db, apply=args.apply)
    print(
        "provider_store_metadata_scrub "
        f"mode={'apply' if args.apply else 'dry_run'} "
        f"scanned={result.scanned_count} "
        f"metadata_cleared={result.metadata_cleared_count} "
        f"etsy_shop_id_backfilled={result.etsy_shop_id_backfilled_count}"
    )


if __name__ == "__main__":
    main()

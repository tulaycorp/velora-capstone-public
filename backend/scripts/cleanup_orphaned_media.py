from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find or delete unreferenced organization-scoped media objects."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete eligible orphan objects. The default is a read-only dry run.",
    )
    args = parser.parse_args()

    from app.db import SessionLocal
    from app.services.storage_orphans import cleanup_orphaned_media

    with SessionLocal() as db:
        result = cleanup_orphaned_media(db, apply=args.apply)

    print(
        "storage_orphan_cleanup "
        f"dry_run={result.dry_run} scanned={result.scanned} "
        f"referenced={result.referenced} too_new={result.too_new} "
        f"orphaned={result.orphaned} deleted={result.deleted} failed={result.failed}"
    )


if __name__ == "__main__":
    main()

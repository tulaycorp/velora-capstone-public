"""Operator-only cleanup of unaccepted AI listing content older than 30 days."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge expired unaccepted AI generation content.")
    parser.add_argument("--apply", action="store_true", help="Apply the idempotent 30-day cleanup.")
    args = parser.parse_args()
    if not args.apply:
        print("ai_generation_cleanup mode=dry_run changes=0; rerun with --apply after the approved runbook.")
        return
    from app.db.database import SessionLocal
    from app.services.ai_generation import prune_unaccepted_generations

    with SessionLocal() as db:
        count = prune_unaccepted_generations(db)
    print(f"ai_generation_cleanup mode=apply content_purged={count}")


if __name__ == "__main__":
    main()

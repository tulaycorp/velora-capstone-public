"""Operator-only provider-credential encryption-key rotation.

Run with --dry-run first. --apply rewrites encrypted credential values and
therefore requires the approved M0 runbook, a backup, and both the old and new
keys to be available through runtime configuration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def validate_apply_confirmation(
    *,
    apply: bool,
    confirmed_project_id: str | None,
    confirmed_active_key_id: str | None,
    configured_project_id: str | None,
    configured_active_key_id: str,
) -> None:
    if not apply:
        return
    if not configured_project_id:
        raise ValueError("VELORA_NEON_PROJECT_ID must be configured for an apply run")
    if confirmed_project_id != configured_project_id:
        raise ValueError("--confirm-project-id must match VELORA_NEON_PROJECT_ID")
    if confirmed_active_key_id != configured_active_key_id:
        raise ValueError(
            "--confirm-active-key-id must match VELORA_SECRET_ENCRYPTION_ACTIVE_KEY_ID"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-encrypt provider credentials under the active key.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-project-id",
        help="Required for --apply; must match VELORA_NEON_PROJECT_ID.",
    )
    parser.add_argument(
        "--confirm-active-key-id",
        help="Required for --apply; must match the configured active encryption key id.",
    )
    args = parser.parse_args()

    from app.core.config import settings
    from app.db.database import SessionLocal
    from app.services.credential_rotation import rotate_provider_credentials

    try:
        validate_apply_confirmation(
            apply=args.apply,
            confirmed_project_id=args.confirm_project_id,
            confirmed_active_key_id=args.confirm_active_key_id,
            configured_project_id=settings.neon_project_id,
            configured_active_key_id=settings.secret_encryption_active_key_id,
        )
    except ValueError as exc:
        parser.error(str(exc))

    with SessionLocal() as db:
        result = rotate_provider_credentials(db, apply=args.apply)

    print(
        "provider_credential_key_rotation "
        f"mode={'apply' if args.apply else 'dry_run'} "
        f"scanned={result.scanned_count} "
        f"reencrypted={result.reencrypted_count} "
        f"already_current={result.current_key_count} "
        f"unreadable={result.unreadable_count}"
    )
    if result.unreadable_count:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

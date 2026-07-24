"""Operator-only provider-credential key rotation helpers.

The active and previous Fernet keys are supplied by runtime configuration. This
module deliberately reports only aggregate counts so a runbook can retain
useful evidence without logging credential values or row identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.encryption import active_encryption_key_id, decrypt_value, encrypt_value
from app.db.models import ProviderCredential


@dataclass(frozen=True)
class CredentialRotationSummary:
    scanned_count: int
    reencrypted_count: int
    current_key_count: int
    unreadable_count: int


def rotate_provider_credentials(db: Session, *, apply: bool) -> CredentialRotationSummary:
    """Re-encrypt every readable credential under the configured active key.

    A run with an unreadable row never writes a partial rotation. Operators
    must restore the matching previous key or resolve the record before retrying.
    """
    rows = db.scalars(select(ProviderCredential)).all()
    active_key_id = active_encryption_key_id()
    rotations: list[tuple[ProviderCredential, str]] = []
    current_key_count = 0
    unreadable_count = 0

    for row in rows:
        is_current = (
            row.encryption_key_id == active_key_id
            and row.encrypted_value.startswith(f"{active_key_id}:")
        )
        if is_current:
            current_key_count += 1
            continue

        try:
            plaintext = decrypt_value(
                row.encrypted_value,
                key_id=row.encryption_key_id,
            )
        except (InvalidToken, ValueError, UnicodeDecodeError):
            unreadable_count += 1
            continue
        rotations.append((row, plaintext))

    if unreadable_count:
        db.rollback()
        return CredentialRotationSummary(
            scanned_count=len(rows),
            reencrypted_count=0,
            current_key_count=current_key_count,
            unreadable_count=unreadable_count,
        )

    if apply:
        for row, plaintext in rotations:
            row.encrypted_value = encrypt_value(plaintext)
            row.encryption_key_id = active_key_id
        db.commit()
    else:
        db.rollback()

    return CredentialRotationSummary(
        scanned_count=len(rows),
        reencrypted_count=len(rotations),
        current_key_count=current_key_count,
        unreadable_count=0,
    )

from __future__ import annotations

from cryptography.fernet import Fernet
from sqlalchemy import delete

from app.core.config import settings
from app.db.encryption import decrypt_value
from app.db.models import ProviderCredential
from app.services.credential_rotation import rotate_provider_credentials


def test_credential_rotation_dry_run_then_apply(client, monkeypatch) -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "secret_encryption_active_key_id", "new")
    monkeypatch.setattr(settings, "secret_encryption_key", new_key)
    monkeypatch.setattr(settings, "secret_encryption_previous_keys", {"old": old_key})

    legacy_ciphertext = Fernet(old_key.encode()).encrypt(b"provider-secret").decode()
    with client.app.state.testing_session_local() as db:
        db.execute(delete(ProviderCredential))
        db.add(
            ProviderCredential(
                id="credential-rotation-old",
                organization_id="default-org",
                provider="printify",
                key_name="api_token",
                encrypted_value=legacy_ciphertext,
                encryption_key_id="old",
            )
        )
        db.commit()

        dry_run = rotate_provider_credentials(db, apply=False)
        assert dry_run.scanned_count == 1
        assert dry_run.reencrypted_count == 1
        assert dry_run.unreadable_count == 0

    with client.app.state.testing_session_local() as db:
        persisted = db.get(ProviderCredential, "credential-rotation-old")
        assert persisted is not None
        assert persisted.encryption_key_id == "old"

        applied = rotate_provider_credentials(db, apply=True)
        assert applied.reencrypted_count == 1

    with client.app.state.testing_session_local() as db:
        persisted = db.get(ProviderCredential, "credential-rotation-old")
        assert persisted is not None
        assert persisted.encryption_key_id == "new"
        assert persisted.encrypted_value.startswith("new:")
        assert decrypt_value(persisted.encrypted_value, key_id=persisted.encryption_key_id) == "provider-secret"


def test_credential_rotation_refuses_partial_apply_when_a_value_is_unreadable(client, monkeypatch) -> None:
    active_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "secret_encryption_active_key_id", "new")
    monkeypatch.setattr(settings, "secret_encryption_key", active_key)
    monkeypatch.setattr(settings, "secret_encryption_previous_keys", {})

    with client.app.state.testing_session_local() as db:
        db.execute(delete(ProviderCredential))
        db.add(
            ProviderCredential(
                id="credential-rotation-unreadable",
                organization_id="default-org",
                provider="gelato",
                key_name="api_key",
                encrypted_value="not-a-valid-ciphertext",
                encryption_key_id="old",
            )
        )
        db.commit()

        result = rotate_provider_credentials(db, apply=True)
        assert result.unreadable_count == 1
        assert result.reencrypted_count == 0

    with client.app.state.testing_session_local() as db:
        persisted = db.get(ProviderCredential, "credential-rotation-unreadable")
        assert persisted is not None
        assert persisted.encryption_key_id == "old"
        assert persisted.encrypted_value == "not-a-valid-ciphertext"

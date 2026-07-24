from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def active_encryption_key_id() -> str:
    return settings.secret_encryption_active_key_id


def _fernet_for_key_id(key_id: str) -> Fernet:
    if key_id == settings.secret_encryption_active_key_id:
        return Fernet(settings.secret_encryption_key.encode())
    previous_key = settings.secret_encryption_previous_keys.get(key_id)
    if previous_key:
        return Fernet(previous_key.encode())
    raise ValueError(f"Unknown encryption key id '{key_id}'.")


def encrypt_value(value: str) -> str:
    key_id = active_encryption_key_id()
    return f"{key_id}:{_fernet_for_key_id(key_id).encrypt(value.encode()).decode()}"


def decrypt_value(value: str, *, key_id: str | None = None) -> str:
    envelope_key_id, separator, ciphertext = value.partition(":")
    if separator:
        return _fernet_for_key_id(envelope_key_id).decrypt(ciphertext.encode()).decode()

    candidates = [key_id or settings.secret_encryption_active_key_id]
    candidates.extend(candidate for candidate in settings.secret_encryption_previous_keys if candidate not in candidates)
    for candidate in candidates:
        try:
            return _fernet_for_key_id(candidate).decrypt(value.encode()).decode()
        except InvalidToken:
            continue
    raise InvalidToken

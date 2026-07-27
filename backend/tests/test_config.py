from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.db import encryption
from app.core.config import settings as runtime_settings

TEST_FERNET_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def test_settings_parse_list_strings() -> None:
    settings = Settings(
        cors_origins='["http://localhost:3000","http://127.0.0.1:3000"]',
        clerk_authorized_parties="http://localhost:3000,http://127.0.0.1:3000",
        secret_encryption_key=TEST_FERNET_KEY,
    )

    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert settings.clerk_authorized_parties == ["http://localhost:3000", "http://127.0.0.1:3000"]


def test_settings_deduplicate_cors_origins() -> None:
    settings = Settings(
        cors_origins="http://localhost:3000,http://localhost:3000",
        secret_encryption_key=TEST_FERNET_KEY,
    )

    assert settings.cors_origins == ["http://localhost:3000"]


def test_settings_parse_list_env_strings(monkeypatch) -> None:
    monkeypatch.setenv("VELORA_CORS_ORIGINS", '["http://localhost:3000","http://127.0.0.1:3000"]')
    monkeypatch.setenv("VELORA_CLERK_AUTHORIZED_PARTIES", "http://localhost:3000,http://127.0.0.1:3000")
    monkeypatch.setenv("VELORA_API_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("VELORA_SECRET_ENCRYPTION_KEY", TEST_FERNET_KEY)
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_backend")

    settings = Settings()

    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert settings.clerk_authorized_parties == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert settings.api_base_url == "http://127.0.0.1:8000"
    assert settings.clerk_secret_key == "sk_test_backend"


def test_settings_strip_surrounding_whitespace_from_env_values(monkeypatch) -> None:
    monkeypatch.setenv("VELORA_SECRET_ENCRYPTION_KEY", f"{TEST_FERNET_KEY}\r\n")
    monkeypatch.setenv("VELORA_LOG_FORMAT", "json\r\n\r\n\r\n")
    monkeypatch.setenv("VELORA_LOG_LEVEL", "INFO\n")
    monkeypatch.setenv("VELORA_AUTH_MODE", "auto\r\n")
    monkeypatch.setenv("VELORA_ETSY_MAX_REQUESTS_PER_SECOND", "5\n")

    settings = Settings()

    assert settings.secret_encryption_key == TEST_FERNET_KEY
    assert settings.log_format == "json"
    assert settings.log_level == "INFO"
    assert settings.auth_mode == "auto"
    assert settings.etsy_max_requests_per_second == 5
    assert settings.etsy_ledger_max_concurrency == 4


def test_settings_resolve_auth_mode_defaults_to_local_without_clerk_verifier() -> None:
    settings = Settings(clerk_jwks_url=None, secret_encryption_key=TEST_FERNET_KEY)

    assert settings.resolved_auth_mode() == "local"


def test_settings_resolve_auth_mode_uses_clerk_when_jwks_is_present() -> None:
    settings = Settings(
        clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
        secret_encryption_key=TEST_FERNET_KEY,
    )

    assert settings.resolved_auth_mode() == "clerk"


def test_settings_include_gelato_order_base_url_default() -> None:
    settings = Settings(secret_encryption_key=TEST_FERNET_KEY)

    assert settings.gelato_order_base_url == "https://order.gelatoapis.com"


def test_settings_bound_database_pool_by_default() -> None:
    settings = Settings(secret_encryption_key=TEST_FERNET_KEY)

    assert settings.database_pool_size == 3
    assert settings.database_max_overflow == 0
    assert settings.database_pool_timeout_seconds == 10
    assert settings.database_pool_recycle_seconds == 1800


def test_settings_allow_95_mib_files_with_multipart_request_overhead() -> None:
    settings = Settings(secret_encryption_key=TEST_FERNET_KEY)

    assert settings.upload_max_file_bytes == 95 * 1024 * 1024
    assert settings.upload_max_request_bytes == 100 * 1024 * 1024

    with pytest.raises(ValueError):
        Settings(
            secret_encryption_key=TEST_FERNET_KEY,
            upload_max_file_bytes=(95 * 1024 * 1024) + 1,
        )
    with pytest.raises(ValueError):
        Settings(
            secret_encryption_key=TEST_FERNET_KEY,
            upload_max_request_bytes=(100 * 1024 * 1024) + 1,
        )


def test_settings_bound_sync_job_lifecycle_by_default() -> None:
    settings = Settings(secret_encryption_key=TEST_FERNET_KEY)

    assert settings.sync_job_lease_seconds == 1800
    assert settings.sync_job_max_attempts == 3
    assert settings.sync_job_reaper_batch_size == 100


def test_settings_bound_incremental_order_sync_by_default() -> None:
    settings = Settings(secret_encryption_key=TEST_FERNET_KEY)

    assert settings.order_sync_page_size == 50
    assert settings.order_sync_max_pages_per_connection == 100
    assert settings.order_sync_overlap_hours == 24
    assert settings.order_sync_detail_concurrency == 5
    assert settings.commerce_sync_interval_seconds == 5 * 60 * 60


def test_settings_include_etsy_direct_edit_defaults() -> None:
    settings = Settings(secret_encryption_key=TEST_FERNET_KEY)

    assert settings.etsy_api_base_url == "https://api.etsy.com/v3"
    assert settings.etsy_user_agent == "Velora/0.1.0"
    assert settings.etsy_oauth_state_ttl_seconds == 900
    assert settings.etsy_max_requests_per_second == 5
    assert settings.etsy_max_retry_attempts == 2
    assert settings.etsy_max_listing_image_bytes == 95 * 1024 * 1024
    assert settings.printify_poll_initial_delay_seconds == 5
    assert settings.printify_poll_max_delay_seconds == 20
    assert settings.printify_poll_timeout_seconds == 900
    assert settings.redis_url == "redis://localhost:6379/0"


def test_openrouter_requires_key_and_model_when_enabled() -> None:
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        Settings(
            secret_encryption_key=TEST_FERNET_KEY,
            ai_provider="openrouter",
            openrouter_api_key=None,
            openrouter_model=None,
        )


def test_openrouter_configuration_is_disabled_by_default() -> None:
    settings = Settings(secret_encryption_key=TEST_FERNET_KEY, ai_provider="disabled")

    assert settings.ai_provider == "disabled"
    assert settings.ai_max_source_image_bytes == 95 * 1024 * 1024
    assert settings.ai_max_image_bytes == 5_000_000
    assert settings.ai_max_image_dimension == 2048
    assert settings.ai_max_source_image_pixels == 300_000_000
    assert settings.ai_max_full_decode_pixels == 50_000_000
    assert settings.ai_generation_limit_per_hour == 20
    assert settings.ai_generation_limit_per_user_per_hour == 10
    assert settings.ai_generation_burst_limit == 3
    assert settings.ai_generation_burst_window_seconds == 60


def test_openrouter_configuration_normalizes_attribution_and_limits() -> None:
    settings = Settings(
        secret_encryption_key=TEST_FERNET_KEY,
        ai_provider="openrouter",
        openrouter_api_key=" test-key ",
        openrouter_model=" test/model ",
        openrouter_app_url=" https://velora.example/app ",
        openrouter_app_title=" Velora Staging ",
        ai_generation_limit_per_user_per_hour=7,
        ai_generation_burst_limit=2,
        ai_generation_burst_window_seconds=30,
    )

    assert settings.openrouter_api_key == "test-key"
    assert settings.openrouter_model == "test/model"
    assert settings.openrouter_app_url == "https://velora.example/app"
    assert settings.openrouter_app_title == "Velora Staging"
    assert settings.ai_generation_limit_per_user_per_hour == 7
    assert settings.ai_generation_burst_limit == 2
    assert settings.ai_generation_burst_window_seconds == 30


def test_openrouter_configuration_rejects_unsafe_numeric_bounds() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        Settings(
            secret_encryption_key=TEST_FERNET_KEY,
            ai_provider="openrouter",
            openrouter_api_key="test-key",
            openrouter_model="test/model",
            ai_generation_burst_limit=0,
        )


def test_settings_read_redis_url_from_unprefixed_env(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://redis.internal:6379/5")
    monkeypatch.setenv("VELORA_SECRET_ENCRYPTION_KEY", TEST_FERNET_KEY)

    settings = Settings()

    assert settings.redis_url == "redis://redis.internal:6379/5"


def test_settings_include_clerk_clock_skew_default() -> None:
    settings = Settings(secret_encryption_key=TEST_FERNET_KEY)

    assert settings.clerk_clock_skew_seconds == 30


def test_backend_env_example_includes_storage_settings() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env.example"
    env_keys = {
        line.split("=", 1)[0].strip()
        for line in env_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }

    assert {
        "VELORA_SECRET_ENCRYPTION_KEY",
        "VELORA_SECRET_ENCRYPTION_ACTIVE_KEY_ID",
        "VELORA_SECRET_ENCRYPTION_PREVIOUS_KEYS",
        "VELORA_STORAGE_ENDPOINT_URL",
        "VELORA_STORAGE_ACCESS_KEY_ID",
        "VELORA_STORAGE_SECRET_ACCESS_KEY",
        "VELORA_STORAGE_BUCKET_NAME",
        "VELORA_STORAGE_REGION_NAME",
        "VELORA_STORAGE_PRESIGN_GET_TTL_SECONDS",
        "VELORA_STORAGE_ORPHAN_MIN_AGE_SECONDS",
        "VELORA_UPLOAD_MAX_FILE_BYTES",
        "VELORA_UPLOAD_MAX_REQUEST_BYTES",
        "VELORA_UPLOAD_SPOOL_MEMORY_BYTES",
        "VELORA_UPLOAD_MAX_MOCKUPS_PER_PRODUCT",
    }.issubset(env_keys)


def test_backend_env_example_includes_database_pool_settings() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env.example"
    env_keys = {
        line.split("=", 1)[0].strip()
        for line in env_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }

    assert {
        "VELORA_DATABASE_POOL_SIZE",
        "VELORA_DATABASE_MAX_OVERFLOW",
        "VELORA_DATABASE_POOL_TIMEOUT_SECONDS",
        "VELORA_DATABASE_POOL_RECYCLE_SECONDS",
    }.issubset(env_keys)


def test_backend_env_example_includes_sync_job_lifecycle_settings() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env.example"
    env_keys = {
        line.split("=", 1)[0].strip()
        for line in env_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }

    assert {
        "VELORA_SYNC_JOB_LEASE_SECONDS",
        "VELORA_SYNC_JOB_MAX_ATTEMPTS",
        "VELORA_SYNC_JOB_REAPER_BATCH_SIZE",
        "VELORA_ORDER_SYNC_PAGE_SIZE",
        "VELORA_ORDER_SYNC_MAX_PAGES_PER_CONNECTION",
        "VELORA_ORDER_SYNC_OVERLAP_HOURS",
        "VELORA_ORDER_SYNC_DETAIL_CONCURRENCY",
    }.issubset(env_keys)


def test_backend_env_example_includes_etsy_direct_edit_and_oauth_settings() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env.example"
    env_keys = {
        line.split("=", 1)[0].strip()
        for line in env_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }

    assert {
        "VELORA_ETSY_API_KEYSTRING",
        "VELORA_ETSY_SHARED_SECRET",
        "VELORA_ETSY_REFRESH_TOKEN",
        "VELORA_ETSY_SHOP_ID",
        "VELORA_ETSY_OAUTH_REDIRECT_URI",
        "VELORA_ETSY_MAX_REQUESTS_PER_SECOND",
        "VELORA_ETSY_MAX_RETRY_ATTEMPTS",
    }.issubset(env_keys)


def test_env_examples_include_logging_settings() -> None:
    backend_env_path = Path(__file__).resolve().parents[1] / ".env.example"
    backend_env_keys = {
        line.split("=", 1)[0].strip()
        for line in backend_env_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    frontend_env_path = Path(__file__).resolve().parents[2] / ".env.local.example"
    frontend_env_keys = {
        line.split("=", 1)[0].strip()
        for line in frontend_env_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }

    assert {
        "VELORA_VERBOSE_LOGGING",
        "VELORA_LOG_LEVEL",
        "VELORA_LOG_FORMAT",
        "VELORA_SECRET_ENCRYPTION_KEY",
    }.issubset(backend_env_keys)
    assert {
        "VELORA_VERBOSE_LOGGING",
        "VELORA_LOG_FORMAT",
    }.issubset(frontend_env_keys)


def test_settings_require_real_secret_encryption_key() -> None:
    with pytest.raises(ValueError, match="VELORA_SECRET_ENCRYPTION_KEY"):
        Settings(secret_encryption_key="replace-me")

    with pytest.raises(ValueError, match="VELORA_SECRET_ENCRYPTION_KEY"):
        Settings(secret_encryption_key="not-a-real-key")


def test_non_development_settings_require_clerk_and_tls() -> None:
    with pytest.raises(ValueError, match="VELORA_AUTH_MODE"):
        Settings(environment="staging", secret_encryption_key=TEST_FERNET_KEY)

    settings = Settings(
        environment="staging",
        auth_mode="clerk",
        clerk_issuer="https://clerk.example",
        clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
        clerk_authorized_parties=["https://app.example"],
        cors_origins=["https://app.example"],
        api_base_url="https://api.example",
        database_url="postgresql+psycopg://user:pass@db.example/velora?sslmode=require",
        secret_encryption_key=TEST_FERNET_KEY,
    )

    assert settings.resolved_auth_mode() == "clerk"

    with pytest.raises(ValueError, match="must require TLS"):
        Settings(
            environment="production",
            auth_mode="clerk",
            clerk_issuer="https://clerk.example",
            clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
            clerk_authorized_parties=["https://app.example"],
            cors_origins=["https://app.example"],
            api_base_url="https://api.example",
            database_url="postgresql+psycopg://user:pass@db.example/velora",
            secret_encryption_key=TEST_FERNET_KEY,
        )


@pytest.mark.parametrize(
    "cors_origins",
    [
        [],
        ["*"],
        ["http://app.example"],
        ["https://user@app.example"],
        ["https://app.example/path"],
        ["https://app.example?preview=1"],
        ["https://app.example#fragment"],
        ["https://*.example.com"],
        ["https://app.example/"],
    ],
)
def test_non_development_settings_reject_unsafe_cors_origins(
    cors_origins: list[str],
) -> None:
    with pytest.raises(ValueError, match="VELORA_CORS_ORIGINS"):
        Settings(
            environment="production",
            auth_mode="clerk",
            clerk_issuer="https://clerk.example",
            clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
            clerk_authorized_parties=["https://app.example"],
            cors_origins=cors_origins,
            api_base_url="https://api.example",
            database_url="postgresql+psycopg://user:pass@db.example/velora?sslmode=require",
            secret_encryption_key=TEST_FERNET_KEY,
        )


def test_non_development_settings_accept_exact_https_cors_origins() -> None:
    settings = Settings(
        environment="production",
        auth_mode="clerk",
        clerk_issuer="https://clerk.example",
        clerk_jwks_url="https://clerk.example/.well-known/jwks.json",
        clerk_authorized_parties=["https://app.example"],
        cors_origins=["https://app.example", "https://admin.example:8443"],
        api_base_url="https://api.example",
        database_url="postgresql+psycopg://user:pass@db.example/velora?sslmode=require",
        secret_encryption_key=TEST_FERNET_KEY,
    )

    assert settings.cors_origins == ["https://app.example", "https://admin.example:8443"]


def test_encryption_rotates_without_losing_previous_key_reads(monkeypatch) -> None:
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(runtime_settings, "secret_encryption_active_key_id", "new")
    monkeypatch.setattr(runtime_settings, "secret_encryption_key", new_key)
    monkeypatch.setattr(runtime_settings, "secret_encryption_previous_keys", {"old": old_key})

    legacy_ciphertext = Fernet(old_key.encode()).encrypt(b"previous credential").decode()
    current_ciphertext = encryption.encrypt_value("current credential")

    assert encryption.decrypt_value(legacy_ciphertext, key_id="old") == "previous credential"
    assert current_ciphertext.startswith("new:")
    assert encryption.decrypt_value(current_ciphertext) == "current credential"

import json
from typing import Literal
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Velora API"
    app_version: str = "0.1.0"
    environment: str = "development"
    verbose_logging: bool = False
    log_level: str = "INFO"
    log_format: Literal["pretty", "json"] = "pretty"
    database_url: str = "postgresql+psycopg://velora:velora@localhost:5432/velora"
    worker_database_url: str | None = None
    database_runtime_role: str = "velora_runtime"
    database_pool_size: int = Field(default=3, ge=1, le=20)
    database_max_overflow: int = Field(default=0, ge=0, le=20)
    database_pool_timeout_seconds: int = Field(default=10, ge=1, le=60)
    database_pool_recycle_seconds: int = Field(default=300, ge=30, le=3600)
    database_idle_pool_purge_seconds: int = Field(default=300, ge=0, le=3600)
    cors_origins: list[str] = ["http://localhost:3000"]
    api_base_url: str | None = None
    auth_mode: Literal["local", "clerk", "auto"] = "auto"
    default_organization_id: str = "default-org"
    default_actor_id: str = "default-user"
    secret_encryption_key: str
    secret_encryption_active_key_id: str = "v1"
    secret_encryption_previous_keys: dict[str, str] = Field(default_factory=dict)
    auto_create_schema: bool = False
    neon_project_id: str | None = None
    # Retained until the separately deferred deployment environment stops injecting it.
    supabase_project_id: str | None = None

    clerk_jwks_url: str | None = None
    clerk_issuer: str | None = None
    clerk_authorized_parties: list[str] = []
    clerk_secret_key: str | None = Field(default=None, validation_alias="CLERK_SECRET_KEY")
    clerk_jwks_cache_ttl_seconds: int = 300
    clerk_clock_skew_seconds: int = 30

    storage_endpoint_url: str | None = None
    storage_access_key_id: str | None = None
    storage_secret_access_key: str | None = None
    storage_bucket_name: str | None = None
    storage_region_name: str = "us-east-1"
    storage_presign_get_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    storage_design_assets_prefix: str = "design-assets"
    storage_draft_mockups_prefix: str = "draft-mockups"
    storage_orphan_min_age_seconds: int = Field(default=3600, ge=300, le=604800)
    upload_max_file_bytes: int = Field(default=95 * 1024 * 1024, ge=1024, le=95 * 1024 * 1024)
    upload_max_request_bytes: int = Field(default=100 * 1024 * 1024, ge=2048, le=100 * 1024 * 1024)
    upload_spool_memory_bytes: int = Field(default=1_000_000, ge=64_000, le=5_000_000)
    upload_max_mockups_per_product: int = Field(default=10, ge=1, le=20)
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    sync_job_lease_seconds: int = Field(default=1800, ge=60, le=7200)
    sync_job_max_attempts: int = Field(default=3, ge=1, le=10)
    sync_job_reaper_batch_size: int = Field(default=100, ge=1, le=500)
    analytics_snapshot_ttl_seconds: int = Field(default=1800, ge=300, le=86400)
    order_sync_page_size: int = Field(default=50, ge=1, le=100)
    order_sync_max_pages_per_connection: int = Field(default=100, ge=1, le=1000)
    order_sync_overlap_hours: int = Field(default=24, ge=1, le=168)
    order_sync_detail_concurrency: int = Field(default=5, ge=1, le=20)
    commerce_sync_interval_seconds: int = Field(default=5 * 60 * 60, ge=300, le=604800)
    exchange_rate_api_base_url: str = "https://api.frankfurter.dev"
    exchange_rate_api_timeout_seconds: int = Field(default=30, ge=1, le=120)

    ai_provider: Literal["disabled", "openrouter"] = "disabled"
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str | None = None
    openrouter_app_url: str | None = None
    openrouter_app_title: str | None = None
    openrouter_timeout_seconds: int = Field(default=45, ge=1, le=180)
    openrouter_max_output_tokens: int = Field(default=2400, ge=64, le=8192)
    openrouter_max_retry_attempts: int = Field(default=2, ge=0, le=5)
    ai_max_source_image_bytes: int = Field(default=95 * 1024 * 1024, ge=1, le=1024 * 1024 * 1024)
    ai_max_image_bytes: int = Field(default=5_000_000, ge=1, le=10_000_000)
    ai_max_image_dimension: int = Field(default=2048, ge=256, le=8192)
    ai_max_source_image_pixels: int = Field(default=300_000_000, ge=1, le=1_000_000_000)
    ai_max_full_decode_pixels: int = Field(default=50_000_000, ge=1, le=500_000_000)
    ai_generation_limit_per_hour: int = Field(default=20, ge=1, le=1000)
    ai_generation_limit_per_user_per_hour: int = Field(default=10, ge=1, le=1000)
    ai_generation_burst_limit: int = Field(default=3, ge=1, le=100)
    ai_generation_burst_window_seconds: int = Field(default=60, ge=1, le=3600)
    ai_generation_pending_timeout_seconds: int = Field(default=120, ge=30, le=3600)

    etsy_api_base_url: str = "https://api.etsy.com/v3"
    etsy_user_agent: str = "Velora/0.1.0"
    etsy_api_keystring: str | None = None
    etsy_shared_secret: str | None = None
    etsy_refresh_token: str | None = None
    etsy_shop_id: str | None = None
    etsy_oauth_redirect_uri: str | None = None
    etsy_oauth_state_ttl_seconds: int = 900
    etsy_max_requests_per_second: int = 5
    etsy_ledger_max_concurrency: int = 4
    etsy_max_retry_attempts: int = 2
    etsy_max_listing_image_bytes: int = 95 * 1024 * 1024

    printify_api_base_url: str = "https://api.printify.com"
    printify_user_agent: str = "Velora/0.1.0"
    printify_max_requests_per_min: int = 480
    printify_publish_max_requests_per_30_min: int = 180
    printify_poll_initial_delay_seconds: int = 5
    printify_poll_max_delay_seconds: int = 20
    printify_poll_timeout_seconds: int = 900

    gelato_ecommerce_base_url: str = "https://ecommerce.gelatoapis.com"
    gelato_order_base_url: str = "https://order.gelatoapis.com"
    gelato_design_fit_method: str = "slice"
    gelato_max_retry_attempts: int = 5
    gelato_poll_initial_delay_seconds: int = 10
    gelato_poll_max_delay_seconds: int = 120
    gelato_poll_timeout_seconds: int = 900

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="VELORA_",
        enable_decoding=False,
    )

    @field_validator("*", mode="before")
    @classmethod
    def strip_string_settings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def normalize_cors_origins(cls, value: object) -> object:
        origins = cls._normalize_string_list(value)
        if not isinstance(origins, list):
            return origins
        return list(dict.fromkeys(origins))

    @field_validator("clerk_authorized_parties", mode="before")
    @classmethod
    def normalize_clerk_authorized_parties(cls, value: object) -> object:
        return cls._normalize_string_list(value)

    @field_validator("database_runtime_role", mode="before")
    @classmethod
    def normalize_database_runtime_role(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized or not normalized.replace("_", "").isalnum():
            raise ValueError("VELORA_DATABASE_RUNTIME_ROLE must be a simple Postgres role name.")
        return normalized

    @field_validator("secret_encryption_key", mode="before")
    @classmethod
    def validate_secret_encryption_key(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized or normalized == "replace-me":
            raise ValueError("VELORA_SECRET_ENCRYPTION_KEY must be set to a real Fernet key.")
        try:
            Fernet(normalized.encode())
        except Exception as exc:  # pragma: no cover - exact Fernet exception type is not important
            raise ValueError("VELORA_SECRET_ENCRYPTION_KEY must be a valid Fernet key.") from exc
        return normalized

    @field_validator("secret_encryption_previous_keys", mode="before")
    @classmethod
    def normalize_previous_encryption_keys(cls, value: object) -> dict[str, str]:
        if value in (None, ""):
            return {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError("VELORA_SECRET_ENCRYPTION_PREVIOUS_KEYS must be a JSON object.") from exc
        if not isinstance(value, dict):
            raise ValueError("VELORA_SECRET_ENCRYPTION_PREVIOUS_KEYS must be a JSON object.")
        normalized: dict[str, str] = {}
        for key_id, key in value.items():
            normalized_id = str(key_id).strip()
            normalized_key = str(key).strip()
            if not normalized_id:
                raise ValueError("Encryption key identifiers must not be blank.")
            try:
                Fernet(normalized_key.encode())
            except Exception as exc:  # pragma: no cover - exact Fernet exception type is not important
                raise ValueError("Every previous encryption key must be a valid Fernet key.") from exc
            normalized[normalized_id] = normalized_key
        return normalized

    @model_validator(mode="after")
    def validate_non_development_security(self) -> "Settings":
        environment = self.environment.strip().lower()
        if environment in {"development", "test"}:
            return self

        if self.auth_mode != "clerk":
            raise ValueError("VELORA_AUTH_MODE must be 'clerk' outside development and test.")
        if not self.cors_origins:
            raise ValueError("VELORA_CORS_ORIGINS must contain at least one HTTPS origin outside development and test.")
        for origin in self.cors_origins:
            parsed_origin = urlparse(origin)
            if (
                "*" in origin
                or parsed_origin.scheme != "https"
                or not parsed_origin.hostname
                or parsed_origin.username is not None
                or parsed_origin.password is not None
                or parsed_origin.path not in {"", None}
                or parsed_origin.params
                or parsed_origin.query
                or parsed_origin.fragment
                or origin != f"{parsed_origin.scheme}://{parsed_origin.netloc}"
            ):
                raise ValueError(
                    "VELORA_CORS_ORIGINS must contain exact HTTPS origins without "
                    "wildcards, credentials, paths, queries, or fragments outside development and test."
                )
        if not self.clerk_issuer or not self.clerk_jwks_url or not self.clerk_authorized_parties:
            raise ValueError("Clerk issuer, JWKS URL, and authorized parties are required outside development and test.")
        for name, value in (("VELORA_CLERK_ISSUER", self.clerk_issuer), ("VELORA_CLERK_JWKS_URL", self.clerk_jwks_url)):
            if not value.startswith("https://"):
                raise ValueError(f"{name} must use HTTPS outside development and test.")
        if self.api_base_url and not self.api_base_url.startswith("https://"):
            raise ValueError("VELORA_API_BASE_URL must use HTTPS outside development and test.")
        database_urls = [("VELORA_DATABASE_URL", self.database_url)]
        if self.worker_database_url:
            database_urls.append(("VELORA_WORKER_DATABASE_URL", self.worker_database_url))
        for name, database_url in database_urls:
            if not database_url.startswith(("postgresql+psycopg://", "postgresql://")):
                raise ValueError(f"{name} must be a Postgres TLS URL outside development and test.")
            sslmode = parse_qs(urlparse(database_url).query).get("sslmode", [""])[0].lower()
            if sslmode not in {"require", "verify-ca", "verify-full"}:
                raise ValueError(f"{name} must require TLS outside development and test.")
        if self.ai_provider == "openrouter" and not self.openrouter_base_url.startswith("https://"):
            raise ValueError("VELORA_OPENROUTER_BASE_URL must use HTTPS outside development and test.")
        if self.openrouter_app_url and not self.openrouter_app_url.startswith("https://"):
            raise ValueError("VELORA_OPENROUTER_APP_URL must use HTTPS outside development and test.")
        return self

    @model_validator(mode="after")
    def validate_openrouter_configuration(self) -> "Settings":
        if self.ai_provider == "openrouter":
            if not self.openrouter_api_key or not self.openrouter_model:
                raise ValueError("VELORA_OPENROUTER_API_KEY and VELORA_OPENROUTER_MODEL are required when AI is enabled.")
            if self.openrouter_app_url and not self.openrouter_app_url.startswith(
                ("http://", "https://")
            ):
                raise ValueError("VELORA_OPENROUTER_APP_URL must be an HTTP(S) URL.")
            if self.openrouter_timeout_seconds < 1 or self.openrouter_max_output_tokens < 64:
                raise ValueError("OpenRouter timeout and output-token limits must be positive and safe.")
            if (
                self.ai_max_source_image_bytes < 1
                or self.ai_max_image_bytes < 1
                or self.ai_max_image_dimension < 256
                or self.ai_max_source_image_pixels < 1
                or self.ai_max_full_decode_pixels < 1
                or self.ai_generation_limit_per_hour < 1
            ):
                raise ValueError("AI image and quota limits must be positive.")
        return self

    @field_validator(
        "storage_design_assets_prefix",
        "storage_draft_mockups_prefix",
        mode="before",
    )
    @classmethod
    def normalize_storage_prefix(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().strip("/")
        return value

    @staticmethod
    def _normalize_string_list(value: object) -> object:
        if not isinstance(value, str):
            return value

        stripped = value.strip()
        if not stripped:
            return []

        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]

        return [item.strip() for item in stripped.split(",") if item.strip()]

    def resolved_auth_mode(self) -> Literal["local", "clerk"]:
        if self.auth_mode == "auto":
            return "clerk" if self.clerk_jwks_url else "local"
        return self.auth_mode


settings = Settings()

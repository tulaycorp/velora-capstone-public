from __future__ import annotations

from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.database import Base
from app.db.models import (  # noqa: F401
    DesignAsset,
    Membership,
    Mockup,
    Organization,
    PodProduct,
    ProductBlueprint,
    ProviderCredential,
    ProviderProductDraft,
    ProviderStoreConnection,
    PublishingJob,
    User,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _escape_config_value(value: str) -> str:
    return value.replace("%", "%%")


configured_url = config.get_main_option("sqlalchemy.url")
if not configured_url or configured_url == "postgresql+psycopg://velora:velora@localhost:5432/velora":
    migration_url = os.environ.get("VELORA_DATABASE_MIGRATION_URL") or settings.database_url
    config.set_main_option("sqlalchemy.url", _escape_config_value(migration_url))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

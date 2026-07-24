from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str):
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            future=True,
            connect_args={"check_same_thread": False},
        )

    return create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
    )


engine = build_engine(settings.database_url)
worker_engine = (
    build_engine(settings.worker_database_url)
    if settings.worker_database_url and settings.worker_database_url != settings.database_url
    else engine
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True, class_=Session)
WorkerSessionLocal = sessionmaker(
    bind=worker_engine,
    autoflush=False,
    autocommit=False,
    future=True,
    class_=Session,
)


def assert_non_bypass_database_role(
    target_engine: Engine,
    *,
    required_role: str,
) -> None:
    """Fail closed when a production runtime connection can bypass tenant RLS."""

    if target_engine.dialect.name != "postgresql":
        return
    with target_engine.connect() as connection:
        role_state = connection.execute(
            text(
                "SELECT current_user AS current_user, role.rolsuper, role.rolbypassrls, "
                "pg_has_role(current_user, :required_role, 'MEMBER') AS has_required_role, "
                "EXISTS ("
                "SELECT 1 FROM pg_class relation "
                "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relname IN ('organizations', 'orders', 'provider_product_drafts') "
                "AND pg_get_userbyid(relation.relowner) = current_user"
                ") AS owns_tenant_tables "
                "FROM pg_roles role WHERE role.rolname = current_user"
            ),
            {"required_role": required_role},
        ).mappings().one()
    if (
        role_state["rolsuper"]
        or role_state["rolbypassrls"]
        or role_state["owns_tenant_tables"]
        or not role_state["has_required_role"]
    ):
        raise RuntimeError(
            "Database runtime role must be a non-owner, non-superuser, NOBYPASSRLS "
            f"member of {required_role}; current_user={role_state['current_user']}."
        )


@lru_cache(maxsize=1)
def assert_configured_worker_database_role() -> None:
    if settings.environment.strip().lower() in {"development", "test"}:
        return
    assert_non_bypass_database_role(
        worker_engine,
        required_role="velora_worker",
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

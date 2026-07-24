from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.db import database


class RollbackTrackingSession:
    def __init__(self) -> None:
        self.rollback_called = False
        self.close_called = False

    def rollback(self) -> None:
        self.rollback_called = True

    def close(self) -> None:
        self.close_called = True


def test_get_db_rolls_back_before_closing_when_request_dependency_raises(monkeypatch) -> None:
    session = RollbackTrackingSession()
    monkeypatch.setattr(database, "SessionLocal", lambda: session)

    dependency = database.get_db()
    assert next(dependency) is session

    with pytest.raises(RuntimeError, match="route failed"):
        dependency.throw(RuntimeError("route failed"))

    assert session.rollback_called is True
    assert session.close_called is True


def test_build_engine_bounds_postgres_connection_pool(monkeypatch) -> None:
    captured: dict[str, object] = {}
    expected_engine = object()

    def fake_create_engine(database_url: str, **kwargs: object) -> object:
        captured["database_url"] = database_url
        captured.update(kwargs)
        return expected_engine

    monkeypatch.setattr(database, "create_engine", fake_create_engine)
    monkeypatch.setattr(database.settings, "database_pool_size", 3)
    monkeypatch.setattr(database.settings, "database_max_overflow", 0)
    monkeypatch.setattr(database.settings, "database_pool_timeout_seconds", 10)
    monkeypatch.setattr(database.settings, "database_pool_recycle_seconds", 300)

    result = database.build_engine("postgresql+psycopg://example/velora")

    assert result is expected_engine
    assert captured == {
        "database_url": "postgresql+psycopg://example/velora",
        "future": True,
        "pool_pre_ping": True,
        "pool_size": 3,
        "max_overflow": 0,
        "pool_timeout": 10,
        "pool_recycle": 300,
    }


def test_build_engine_keeps_pool_options_off_sqlite(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(database_url: str, **kwargs: object) -> object:
        captured["database_url"] = database_url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(database, "create_engine", fake_create_engine)

    database.build_engine("sqlite:///test.db")

    assert captured == {
        "database_url": "sqlite:///test.db",
        "future": True,
        "connect_args": {"check_same_thread": False},
    }


class FakeRoleResult:
    def __init__(self, role_state: dict[str, object]) -> None:
        self.role_state = role_state

    def mappings(self):
        return self

    def one(self) -> dict[str, object]:
        return self.role_state


class FakeRoleConnection:
    def __init__(self, role_state: dict[str, object]) -> None:
        self.role_state = role_state

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _statement, _parameters) -> FakeRoleResult:
        return FakeRoleResult(self.role_state)


class FakeRoleEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, role_state: dict[str, object]) -> None:
        self.role_state = role_state

    def connect(self) -> FakeRoleConnection:
        return FakeRoleConnection(self.role_state)


def test_runtime_database_role_validation_accepts_non_bypass_member() -> None:
    database.assert_non_bypass_database_role(
        FakeRoleEngine(
            {
                "current_user": "velora_api_login",
                "rolsuper": False,
                "rolbypassrls": False,
                "has_required_role": True,
                "owns_tenant_tables": False,
            }
        ),
        required_role="velora_runtime",
    )


@pytest.mark.parametrize(
    "unsafe_field",
    ["rolsuper", "rolbypassrls", "owns_tenant_tables"],
)
def test_runtime_database_role_validation_rejects_privileged_roles(
    unsafe_field: str,
) -> None:
    role_state = {
        "current_user": "unsafe_login",
        "rolsuper": False,
        "rolbypassrls": False,
        "has_required_role": True,
        "owns_tenant_tables": False,
    }
    role_state[unsafe_field] = True

    with pytest.raises(RuntimeError, match="non-owner, non-superuser, NOBYPASSRLS"):
        database.assert_non_bypass_database_role(
            FakeRoleEngine(role_state),
            required_role="velora_runtime",
        )


def test_runtime_database_role_validation_requires_group_membership() -> None:
    with pytest.raises(RuntimeError, match="member of velora_runtime"):
        database.assert_non_bypass_database_role(
            FakeRoleEngine(
                {
                    "current_user": "unscoped_login",
                    "rolsuper": False,
                    "rolbypassrls": False,
                    "has_required_role": False,
                    "owns_tenant_tables": False,
                }
            ),
            required_role="velora_runtime",
        )

import pytest

from app.db import runtime_preflight


def test_worker_runtime_preflight_runs_role_validation(monkeypatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        runtime_preflight,
        "assert_configured_worker_database_role",
        lambda: calls.append(True),
    )

    runtime_preflight.main()

    assert calls == [True]


def test_worker_runtime_preflight_propagates_unsafe_role_failure(monkeypatch) -> None:
    def reject_role() -> None:
        raise RuntimeError("unsafe worker role")

    monkeypatch.setattr(
        runtime_preflight,
        "assert_configured_worker_database_role",
        reject_role,
    )

    with pytest.raises(RuntimeError, match="unsafe worker role"):
        runtime_preflight.main()

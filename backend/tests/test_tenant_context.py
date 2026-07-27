from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import tenant_context


def test_request_context_is_applied_once_when_it_opens_a_transaction(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    apply_calls: list[object] = []
    monkeypatch.setattr(
        tenant_context,
        "_apply_postgres_context",
        lambda _session, connection: apply_calls.append(connection),
    )

    with Session(engine) as session:
        tenant_context.set_database_request_context(
            session,
            actor_id="user-1",
            organization_id=None,
        )
        assert len(apply_calls) == 1

        tenant_context.set_database_request_context(
            session,
            actor_id="user-1",
            organization_id="org-1",
        )
        assert len(apply_calls) == 2

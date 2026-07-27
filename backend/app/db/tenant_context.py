from __future__ import annotations

from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session


ACTOR_CONTEXT_KEY = "velora_actor_id"
ORGANIZATION_CONTEXT_KEY = "velora_organization_id"
JOIN_CODE_CONTEXT_KEY = "velora_join_code"


def _context_parameters(session: Session) -> dict[str, str]:
    return {
        "actor_id": str(session.info.get(ACTOR_CONTEXT_KEY) or ""),
        "organization_id": str(session.info.get(ORGANIZATION_CONTEXT_KEY) or ""),
        "join_code": str(session.info.get(JOIN_CODE_CONTEXT_KEY) or ""),
    }


def _apply_postgres_context(session: Session, connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text(
            "SELECT "
            "set_config('app.current_actor_id', :actor_id, true), "
            "set_config('app.current_organization_id', :organization_id, true), "
            "set_config('app.current_join_code', :join_code, true)"
        ),
        _context_parameters(session),
    )


@event.listens_for(Session, "after_begin")
def _reapply_context_after_transaction_begin(
    session: Session,
    _transaction: Any,
    connection: Connection,
) -> None:
    _apply_postgres_context(session, connection)


def set_database_request_context(
    session: Session,
    *,
    actor_id: str | None,
    organization_id: str | None,
) -> None:
    """Apply transaction-local RLS context and preserve it across service commits."""

    session.info[ACTOR_CONTEXT_KEY] = actor_id or ""
    session.info[ORGANIZATION_CONTEXT_KEY] = organization_id or ""
    session.info.setdefault(JOIN_CODE_CONTEXT_KEY, "")
    transaction_already_active = session.in_transaction()
    connection = session.connection()
    if transaction_already_active:
        _apply_postgres_context(session, connection)


def set_database_join_code_context(session: Session, *, join_code: str) -> None:
    """Authorize one join-code lookup without opening organization-wide reads."""

    session.info[JOIN_CODE_CONTEXT_KEY] = join_code.strip().upper()
    transaction_already_active = session.in_transaction()
    connection = session.connection()
    if transaction_already_active:
        _apply_postgres_context(session, connection)

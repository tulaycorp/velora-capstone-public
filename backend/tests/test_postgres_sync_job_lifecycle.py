from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import SyncJob
from app.services.etsy import (
    _consume_etsy_oauth_state_request,
    register_etsy_oauth_state_request,
)
from app.services.sync_job_lifecycle import (
    claim_sync_job,
    enqueue_sync_job,
    finish_sync_job,
    heartbeat_sync_job,
    mark_sync_job_running,
    reap_expired_sync_jobs,
)


POSTGRES_TEST_URL = os.environ.get("VELORA_POSTGRES_TEST_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_TEST_URL,
    reason="Set VELORA_POSTGRES_TEST_URL to run PostgreSQL locking and migration checks.",
)


@pytest.fixture(scope="module")
def postgres_engine():
    assert POSTGRES_TEST_URL is not None
    engine = create_engine(POSTGRES_TEST_URL, pool_size=12, max_overflow=0, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def postgres_session_local(postgres_engine):
    return sessionmaker(bind=postgres_engine, autoflush=False, autocommit=False, future=True)


def test_postgres_migrations_include_m1_lifecycle_and_incremental_state(postgres_engine) -> None:
    inspector = inspect(postgres_engine)
    with postgres_engine.connect() as connection:
        version = connection.scalar(text("SELECT version_num FROM alembic_version"))
        active_index = connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = 'sync_jobs' "
                "AND indexname = 'uq_sync_jobs_active_scope'"
            )
        )
        publishing_active_index = connection.scalar(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = 'publishing_jobs' "
                "AND indexname = 'uq_publishing_jobs_active_scope'"
            )
        )

    sync_job_columns = {column["name"] for column in inspector.get_columns("sync_jobs")}
    connection_columns = {
        column["name"] for column in inspector.get_columns("provider_store_connections")
    }
    sync_job_constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("sync_jobs")
    }

    publishing_job_columns = {
        column["name"] for column in inspector.get_columns("publishing_jobs")
    }
    publishing_job_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("publishing_jobs")
    }
    publishing_outbox_constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("publishing_outbox")
    }

    assert version == "20260723_0020"
    assert {
        "scope_key",
        "lease_owner",
        "lease_expires_at",
        "heartbeat_at",
        "attempt_count",
        "max_attempts",
        "available_at",
        "result_json",
    } <= sync_job_columns
    assert {
        "order_sync_cursor_json",
        "order_sync_watermark_at",
        "order_sync_last_success_at",
        "deleted_at",
    } <= connection_columns
    assert {
        "ck_sync_jobs_status",
        "ck_sync_jobs_lease_fields",
        "ck_sync_jobs_attempt_count_within_limit",
    } <= sync_job_constraints
    assert active_index is not None
    assert "UNIQUE INDEX" in active_index
    assert "status" in active_index and "queued" in active_index and "running" in active_index
    assert {
        "sync_job_id",
        "operation",
        "product_revision",
        "idempotency_key",
        "submitted_snapshot_json",
        "provider_product_id",
        "stage",
    } <= publishing_job_columns
    assert {
        "ck_publishing_jobs_status",
        "ck_publishing_jobs_operation",
        "ck_publishing_jobs_product_revision_positive",
    } <= publishing_job_constraints
    assert {
        "ck_publishing_outbox_status",
        "ck_publishing_outbox_attempt_count_nonnegative",
    } <= publishing_outbox_constraints
    assert publishing_active_index is not None
    assert "UNIQUE INDEX" in publishing_active_index
    assert "queued" in publishing_active_index and "running" in publishing_active_index


def test_postgres_tenant_constraints_and_runtime_roles(postgres_engine) -> None:
    inspector = inspect(postgres_engine)
    order_foreign_keys = {
        constraint["name"] for constraint in inspector.get_foreign_keys("orders")
    }
    draft_foreign_keys = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("provider_product_drafts")
    }
    with postgres_engine.connect() as connection:
        roles = {
            row["rolname"]: row
            for row in connection.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname IN ('velora_runtime', 'velora_worker')"
                )
            ).mappings()
        }
        rls_state = {
            row["relname"]: row
            for row in connection.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class relation "
                    "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = 'public' "
                    "AND relname IN ('orders', 'sync_jobs', 'oauth_request_states', 'analytics_snapshots')"
                )
            ).mappings()
        }
        policy_tables = set(
            connection.scalars(
                text(
                    "SELECT tablename FROM pg_policies WHERE schemaname = 'public' "
                    "AND policyname = 'deny_client_access'"
                )
            )
        )

    assert "fk_orders_org_store" in order_foreign_keys
    assert {
        "fk_provider_product_drafts_org_blueprint",
        "fk_provider_product_drafts_org_store",
        "fk_provider_product_drafts_org_design_asset",
    } <= draft_foreign_keys
    assert set(roles) == {"velora_runtime", "velora_worker"}
    assert all(not row["rolsuper"] and not row["rolbypassrls"] for row in roles.values())
    assert all(
        row["relrowsecurity"] and row["relforcerowsecurity"]
        for row in rls_state.values()
    )
    assert {
        "ai_generations",
        "oauth_request_states",
        "orders",
        "sync_jobs",
        "sync_events",
        "analytics_snapshots",
    } <= policy_tables


def test_postgres_runtime_role_is_tenant_scoped_and_constraints_reject_cross_org(
    postgres_engine,
) -> None:
    suffix = uuid.uuid4().hex[:12]
    organization_a = f"pg-tenant-a-{suffix}"
    organization_b = f"pg-tenant-b-{suffix}"
    store_a = str(uuid.uuid4())
    store_b = str(uuid.uuid4())
    snapshot_a = str(uuid.uuid4())
    snapshot_b = str(uuid.uuid4())

    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organizations "
                "(id, auth_provider, name, created_at, updated_at) VALUES "
                "(:organization_a, 'local', 'Tenant A', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(:organization_b, 'local', 'Tenant B', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"organization_a": organization_a, "organization_b": organization_b},
        )
        connection.execute(
            text(
                "INSERT INTO provider_store_connections "
                "(id, organization_id, provider, credential_key, provider_store_id, "
                "storefront_type, storefront_display_name, label, status, discovery_source, "
                "raw_data_json, created_at, updated_at) VALUES "
                "(:store_a, :organization_a, 'printify', 'default', 'store-a', "
                "'etsy', 'Etsy', 'Tenant A Store', 'connected', 'legacy', "
                "'{\"order\": {\"firstName\": \"Private\"}}'::jsonb, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(:store_b, :organization_b, 'printify', 'default', 'store-b', "
                "'etsy', 'Etsy', 'Tenant B Store', 'connected', 'legacy', "
                "NULL, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "store_a": store_a,
                "store_b": store_b,
                "organization_a": organization_a,
                "organization_b": organization_b,
            },
        )
        connection.execute(
            text(
                "INSERT INTO analytics_snapshots "
                "(id, organization_id, provider, source_scope, payload_json, status, "
                "fetched_at, expires_at, last_attempted_at, created_at, updated_at) VALUES "
                "(:snapshot_a, :organization_a, 'etsy', 'organization', '{}'::jsonb, 'succeeded', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '30 minutes', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(:snapshot_b, :organization_b, 'etsy', 'organization', '{}'::jsonb, 'succeeded', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '30 minutes', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "snapshot_a": snapshot_a,
                "snapshot_b": snapshot_b,
                "organization_a": organization_a,
                "organization_b": organization_b,
            },
        )

    try:
        with pytest.raises(IntegrityError):
            with postgres_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO product_blueprints "
                        "(id, organization_id, provider, provider_store_connection_id, name, "
                        "category, status, reference_type, reference_value, variant_count, "
                        "created_at, updated_at) VALUES "
                        "(:id, :organization_a, 'printify', :store_b, 'Cross Tenant', "
                        "'shirt', 'draft', 'provider_product', 'cross-tenant', 0, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "organization_a": organization_a,
                        "store_b": store_b,
                    },
                )

        with postgres_engine.begin() as connection:
            connection.execute(text("SET LOCAL ROLE velora_runtime"))
            connection.execute(
                text(
                    "SELECT set_config('app.current_actor_id', '', true), "
                    "set_config('app.current_organization_id', :organization_id, true)"
                ),
                {"organization_id": organization_a},
            )
            visible_store_ids = set(
                connection.scalars(
                    text(
                        "SELECT id FROM provider_store_connections "
                        "WHERE id IN (:store_a, :store_b)"
                    ),
                    {"store_a": store_a, "store_b": store_b},
                )
            )
            runtime_state = connection.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls "
                    "FROM pg_roles WHERE rolname = current_user"
                )
            ).mappings().one()
            visible_snapshot_ids = set(
                connection.scalars(
                    text(
                        "SELECT id FROM analytics_snapshots "
                        "WHERE id IN (:snapshot_a, :snapshot_b)"
                    ),
                    {"snapshot_a": snapshot_a, "snapshot_b": snapshot_b},
                )
            )
            guarded_metadata_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM provider_store_connections "
                    "WHERE id = :store_id AND raw_data_json IS NOT NULL"
                ),
                {"store_id": store_a},
            )

        assert visible_store_ids == {store_a}
        assert visible_snapshot_ids == {snapshot_a}
        assert runtime_state["current_user"] == "velora_runtime"
        assert runtime_state["rolsuper"] is False
        assert runtime_state["rolbypassrls"] is False
        assert guarded_metadata_count == 0

        for table_name in ("orders", "analytics_snapshots"):
            with postgres_engine.connect() as connection:
                authenticated_can_select = connection.scalar(
                    text(
                        "SELECT has_table_privilege("
                        "'authenticated', :table_name, 'SELECT')"
                    ),
                    {"table_name": f"public.{table_name}"},
                )

            if authenticated_can_select:
                with postgres_engine.begin() as connection:
                    connection.execute(text("SET LOCAL ROLE authenticated"))
                    assert connection.scalar(
                        text(f"SELECT COUNT(*) FROM {table_name}")
                    ) == 0
            else:
                assert authenticated_can_select is False
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM organizations WHERE id IN (:a, :b)"),
                {"a": organization_a, "b": organization_b},
            )


def test_concurrent_postgres_enqueue_converges_on_one_active_job(postgres_session_local) -> None:
    organization_id = f"postgres-enqueue-{uuid.uuid4()}"
    worker_count = 8
    barrier = threading.Barrier(worker_count)
    with postgres_session_local() as session:
        session.execute(
            text(
                "INSERT INTO organizations "
                "(id, auth_provider, name, created_at, updated_at) VALUES "
                "(:organization_id, 'local', 'Postgres enqueue test', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"organization_id": organization_id},
        )
        session.commit()

    def enqueue_once() -> tuple[str, bool]:
        with postgres_session_local() as session:
            barrier.wait(timeout=10)
            result = enqueue_sync_job(
                session,
                organization_id=organization_id,
                job_type="order_sync",
            )
            return result.job.id, result.created

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(lambda _: enqueue_once(), range(worker_count)))

    job_ids = {job_id for job_id, _ in results}
    assert len(job_ids) == 1
    assert sum(created for _, created in results) == 1
    with postgres_session_local() as session:
        active_count = session.scalar(
            select(func.count()).select_from(SyncJob).where(
                SyncJob.organization_id == organization_id,
                SyncJob.status.in_(("queued", "leased", "running")),
            )
        )
    assert active_count == 1


def test_postgres_claim_has_one_winner_and_enforces_lease_ownership(postgres_session_local) -> None:
    organization_id = f"postgres-claim-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    with postgres_session_local() as session:
        session.execute(
            text(
                "INSERT INTO organizations "
                "(id, auth_provider, name, created_at, updated_at) VALUES "
                "(:organization_id, 'local', 'Postgres claim test', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"organization_id": organization_id},
        )
        session.commit()
        job_id = enqueue_sync_job(
            session,
            organization_id=organization_id,
            job_type="order_sync",
            now=now,
        ).job.id

    barrier = threading.Barrier(2)

    def claim_once(owner: str) -> str | None:
        with postgres_session_local() as session:
            barrier.wait(timeout=10)
            claimed = claim_sync_job(session, job_id=job_id, lease_owner=owner, now=now)
            return claimed.lease_owner if claimed is not None else None

    with ThreadPoolExecutor(max_workers=2) as executor:
        owners = list(executor.map(claim_once, ("worker-a", "worker-b")))

    winner = next(owner for owner in owners if owner is not None)
    loser = "worker-b" if winner == "worker-a" else "worker-a"
    assert sum(owner is not None for owner in owners) == 1
    with postgres_session_local() as session:
        assert mark_sync_job_running(session, job_id=job_id, lease_owner=winner) is not None
    with postgres_session_local() as session:
        assert heartbeat_sync_job(session, job_id=job_id, lease_owner=loser, now=now) is False
    with postgres_session_local() as session:
        assert heartbeat_sync_job(
            session,
            job_id=job_id,
            lease_owner=winner,
            now=now + timedelta(minutes=1),
        ) is True
    with postgres_session_local() as session:
        completed = finish_sync_job(
            session,
            job_id=job_id,
            lease_owner=winner,
            status="completed",
            result_json={"orders": {"fetched": 0}},
            now=now + timedelta(minutes=2),
        )
        assert completed is not None
    with postgres_session_local() as session:
        assert claim_sync_job(
            session,
            job_id=job_id,
            lease_owner="late-worker",
            now=now + timedelta(minutes=3),
        ) is None


def test_concurrent_postgres_reapers_do_not_process_a_job_twice(postgres_session_local) -> None:
    job_type = f"pg-reaper-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    expired_at = now - timedelta(minutes=1)
    job_ids = {str(uuid.uuid4()) for _ in range(8)}
    with postgres_session_local() as session:
        session.execute(
            text(
                "INSERT INTO organizations "
                "(id, auth_provider, name, created_at, updated_at) VALUES "
                "(:organization_id, 'local', 'Postgres reaper test', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            [
                {"organization_id": f"org-{job_id}"}
                for job_id in job_ids
            ],
        )
        session.add_all(
            [
                SyncJob(
                    id=job_id,
                    organization_id=f"org-{job_id}",
                    job_type=job_type,
                    status="running",
                    scope_key="organization",
                    lease_owner="dead-worker",
                    lease_expires_at=expired_at,
                    heartbeat_at=expired_at,
                    attempt_count=1,
                    max_attempts=3,
                    available_at=expired_at,
                )
                for job_id in job_ids
            ]
        )
        session.commit()

    barrier = threading.Barrier(2)

    def reap_once():
        with postgres_session_local() as session:
            barrier.wait(timeout=10)
            return reap_expired_sync_jobs(
                session,
                job_type=job_type,
                now=now,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: reap_once(), range(2)))

    requeued_ids = [job_id for result in results for job_id, _ in result.requeued]
    assert set(requeued_ids) == job_ids
    assert len(requeued_ids) == len(job_ids)
    assert not any(result.failed for result in results)
    with postgres_session_local() as session:
        statuses = set(
            session.scalars(select(SyncJob.status).where(SyncJob.id.in_(job_ids))).all()
        )
    assert statuses == {"queued"}


def test_concurrent_postgres_oauth_state_consumption_has_one_winner(postgres_session_local) -> None:
    """Two concurrent Etsy OAuth callbacks must not both consume the same one-time state.

    `with_for_update()` is a no-op on SQLite, so this PostgreSQL-only test is the
    evidence that the row-level lock serializes concurrent consumers: the second
    consumer's SELECT blocks until the first commits, then sees `consumed_at` set
    and is rejected. Backs the trust-boundary addendum claim about atomic OAuth
    state consumption. Runs several rounds because a single two-thread race can
    finish before the loser's SELECT even starts.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    for round_index in range(6):
        suffix = uuid.uuid4().hex[:12]
        organization_id = f"pg-oauth-{suffix}"
        actor_id = f"pg-oauth-user-{suffix}"
        state = f"pg-oauth-state-{suffix}"

        with postgres_session_local() as session:
            session.execute(
                text(
                    "INSERT INTO organizations "
                    "(id, auth_provider, name, created_at, updated_at) VALUES "
                    "(:organization_id, 'local', 'Postgres OAuth test', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"organization_id": organization_id},
            )
            session.commit()
            register_etsy_oauth_state_request(
                session,
                actor_id=actor_id,
                organization_id=organization_id,
                state=state,
                expires_at=expires_at,
            )

        barrier = threading.Barrier(2)
        outcomes: list[bool] = []
        errors: list[BaseException] = []

        def consume_once() -> None:
            try:
                with postgres_session_local() as session:
                    barrier.wait(timeout=10)
                    _consume_etsy_oauth_state_request(
                        session,
                        actor_id=actor_id,
                        organization_id=organization_id,
                        state=state,
                        expires_at=expires_at,
                    )
                    outcomes.append(True)
            except BaseException as exc:  # noqa: BLE001 - surface any failure to the test thread
                errors.append(exc)

        threads = [threading.Thread(target=consume_once) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        # The lock guarantees exactly one consumer wins and the other is rejected.
        # A regression that drops `with_for_update()` lets both read consumed_at as
        # NULL before either commits, so both succeed on at least one round.
        assert len(outcomes) == 1, (
            f"OAuth round {round_index}: expected exactly one winning consumer, "
            f"got {len(outcomes)} successes and {len(errors)} errors: {errors!r}"
        )
        assert len(errors) == 1

        with postgres_session_local() as session:
            session.execute(
                text("DELETE FROM organizations WHERE id = :organization_id"),
                {"organization_id": organization_id},
            )
            session.commit()

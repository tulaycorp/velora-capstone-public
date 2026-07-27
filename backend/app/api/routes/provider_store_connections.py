from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.etsy_sales_sync import request_etsy_sales_sync
from app.api.deps import ActorContext, get_admin_actor_context, get_db, get_workspace_actor_context
from app.models import (
    ProviderStoreConnection,
    ProviderStoreConnectionSyncResponse,
    ProviderStoreConnectionUpdateRequest,
)
from app.services import (
    delete_provider_store_connection,
    list_provider_store_connections,
    sync_provider_store_connections,
    update_provider_store_connection,
)

router = APIRouter(tags=["provider-store-connections"])


@router.get(
    "/provider-store-connections",
    response_model=list[ProviderStoreConnection],
)
def list_provider_store_connection_records(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> list[ProviderStoreConnection]:
    return list_provider_store_connections(db, actor=actor)


@router.post(
    "/provider-store-connections/sync/{provider}",
    response_model=ProviderStoreConnectionSyncResponse,
)
async def sync_provider_store_connection_records(
    provider: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> ProviderStoreConnectionSyncResponse:
    result = await sync_provider_store_connections(db, actor=actor, provider=provider)
    if any(
        connection.status == "connected"
        and connection.storefront_type == "etsy"
        and connection.etsy_shop_id
        for connection in result.connections
    ):
        request_etsy_sales_sync(
            db,
            background_tasks,
            organization_id=actor.organization_id,
            force=True,
            fallback_to_background=False,
        )
    return result


@router.post(
    "/provider-store-connections/sync/{provider}/{credential_key}",
    response_model=ProviderStoreConnectionSyncResponse,
)
async def sync_provider_store_connection_records_for_credential(
    provider: str,
    credential_key: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> ProviderStoreConnectionSyncResponse:
    result = await sync_provider_store_connections(
        db,
        actor=actor,
        provider=provider,
        credential_key=credential_key,
    )
    if any(
        connection.status == "connected"
        and connection.storefront_type == "etsy"
        and connection.etsy_shop_id
        for connection in result.connections
    ):
        request_etsy_sales_sync(
            db,
            background_tasks,
            organization_id=actor.organization_id,
            force=True,
            fallback_to_background=False,
        )
    return result


@router.patch(
    "/provider-store-connections/{connection_id}",
    response_model=ProviderStoreConnection,
)
def update_provider_store_connection_record(
    connection_id: str,
    payload: ProviderStoreConnectionUpdateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> ProviderStoreConnection:
    connection = update_provider_store_connection(
        db,
        actor=actor,
        connection_id=connection_id,
        payload=payload,
    )
    if (
        connection.status == "connected"
        and connection.storefront_type == "etsy"
        and connection.etsy_shop_id
    ):
        request_etsy_sales_sync(
            db,
            background_tasks,
            organization_id=actor.organization_id,
            force=True,
            fallback_to_background=False,
        )
    return connection


@router.delete("/provider-store-connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_store_connection_record(
    connection_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> Response:
    delete_provider_store_connection(db, actor=actor, connection_id=connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

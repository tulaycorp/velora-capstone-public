from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_admin_actor_context, get_db, get_workspace_actor_context
from app.models import (
    PodProvider,
    ProviderCredentialsUpsertRequest,
    ProviderCredentialsUpsertResponse,
    ProviderCredentialStatus,
)
from app.services import (
    delete_provider_credentials,
    get_provider_credential_status,
    list_pod_providers,
    upsert_provider_credentials,
)

router = APIRouter(tags=["pod-providers"])


@router.get("/pod-providers", response_model=list[PodProvider])
def list_pod_provider_records(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> list[PodProvider]:
    return list_pod_providers(db, actor=actor)


@router.put(
    "/pod-providers/{provider}/credentials",
    response_model=ProviderCredentialsUpsertResponse,
    status_code=status.HTTP_200_OK,
)
def upsert_pod_provider_credentials(
    provider: str,
    payload: ProviderCredentialsUpsertRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> ProviderCredentialsUpsertResponse:
    credential_status = upsert_provider_credentials(db, actor=actor, provider=provider, payload=payload)
    return ProviderCredentialsUpsertResponse(status="ok", credential_status=credential_status)


@router.delete(
    "/pod-providers/{provider}/credentials/{credential_key}",
    response_model=ProviderCredentialsUpsertResponse,
    status_code=status.HTTP_200_OK,
)
def delete_pod_provider_credentials(
    provider: str,
    credential_key: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> ProviderCredentialsUpsertResponse:
    credential_status = delete_provider_credentials(
        db,
        actor=actor,
        provider=provider,
        credential_key=credential_key,
    )
    return ProviderCredentialsUpsertResponse(status="deleted", credential_status=credential_status)


@router.get("/pod-providers/{provider}/credentials/status", response_model=ProviderCredentialStatus)
def get_pod_provider_credential_status(
    provider: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> ProviderCredentialStatus:
    return get_provider_credential_status(db, organization_id=actor.organization_id, provider=provider)

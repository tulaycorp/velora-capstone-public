from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import ActorContext, get_db, get_workspace_actor_context
from app.jobs.publishing import dispatch_publishing_outbox
from app.models import (
    Mockup,
    MockupOrderRequest,
    Product,
    ProductCreateRequest,
    ProductUpdateRequest,
    PublishProductRequest,
    PublishProductResponse,
)
from app.services import (
    create_product_draft,
    delete_product,
    delete_mockup,
    enqueue_publishing_job,
    get_product,
    reorder_mockups,
    store_mockup,
    update_product,
    list_products,
)

router = APIRouter(tags=["products"])


@router.get("/products", response_model=list[Product])
def list_product_records(
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> list[Product]:
    return list_products(db, actor=actor)


@router.post("/products", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product_record(
    payload: ProductCreateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Product:
    return create_product_draft(db, actor=actor, payload=payload)


@router.get("/products/{product_id}", response_model=Product)
def get_product_record(
    product_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Product:
    return get_product(db, actor=actor, product_id=product_id)


@router.patch("/products/{product_id}", response_model=Product)
def update_product_record(
    product_id: str,
    payload: ProductUpdateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Product:
    return update_product(db, actor=actor, product_id=product_id, payload=payload)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product_record(
    product_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Response:
    delete_product(db, actor=actor, product_id=product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/products/{product_id}/mockups", response_model=Mockup, status_code=status.HTTP_201_CREATED)
async def upload_product_mockup(
    product_id: str,
    file: UploadFile = File(...),
    position: int | None = Form(None),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Mockup:
    return await store_mockup(db, actor=actor, product_id=product_id, file=file, position=position)


@router.patch("/products/{product_id}/mockups/order", response_model=Product)
def reorder_product_mockups(
    product_id: str,
    payload: MockupOrderRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Product:
    return reorder_mockups(db, actor=actor, product_id=product_id, payload=payload)


@router.delete("/products/{product_id}/mockups/{mockup_id}", response_model=Product)
def delete_product_mockup(
    product_id: str,
    mockup_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> Product:
    return delete_mockup(db, actor=actor, product_id=product_id, mockup_id=mockup_id)


@router.post("/products/{product_id}/publish", response_model=PublishProductResponse)
def publish_product_record(
    product_id: str,
    payload: PublishProductRequest | None = None,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> PublishProductResponse:
    job = enqueue_publishing_job(
        db,
        actor=actor,
        product_id=product_id,
        expected_revision=payload.expected_revision if payload is not None else None,
    )
    dispatch_publishing_outbox(publishing_job_id=job.id)
    return PublishProductResponse(job=job)

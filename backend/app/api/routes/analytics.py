from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    ActorContext,
    get_admin_actor_context,
    get_db,
    get_workspace_actor_context,
)
from app.models import (
    AnalyticsDetailPage,
    AnalyticsPreferencesResponse,
    AnalyticsPreferencesUpdateRequest,
    BusinessAnalyticsResponse,
    ExpenseCreateRequest,
    ExpenseRecord,
    ExpenseUpdateRequest,
    OrderLineMappingRequest,
    WorkspaceAnalyticsResponse,
)
from app.services import get_workspace_analytics
from app.services.business_analytics import (
    create_expense,
    delete_expense,
    get_business_analytics,
    get_business_analytics_detail_page,
    map_order_line,
    update_analytics_preferences,
    update_expense,
)

router = APIRouter(tags=["analytics"])


@router.get("/analytics", response_model=WorkspaceAnalyticsResponse)
def get_analytics(
    store_connection_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> WorkspaceAnalyticsResponse:
    return get_workspace_analytics(
        db,
        actor=actor,
        store_connection_id=store_connection_id,
    )


@router.get("/analytics/business", response_model=BusinessAnalyticsResponse)
def get_business_analytics_route(
    store_connection_id: str | None = Query(default=None),
    preset: str = Query(default="30d"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    currency: str | None = Query(default=None),
    timezone: str | None = Query(default=None),
    include_details: bool = Query(default=True),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> BusinessAnalyticsResponse:
    return get_business_analytics(
        db,
        actor=actor,
        store_connection_id=store_connection_id,
        preset=preset,
        start=start,
        end=end,
        currency=currency,
        timezone_name=timezone,
        include_details=include_details,
    )


@router.get("/analytics/business/details", response_model=AnalyticsDetailPage)
def get_business_analytics_details_route(
    resource: str = Query(pattern="^(products|expenses|seo|unmatched)$"),
    store_connection_id: str | None = Query(default=None),
    preset: str = Query(default="30d"),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    currency: str | None = Query(default=None),
    timezone: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=10, le=100),
    product_measure: str = Query(default="revenue"),
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_workspace_actor_context),
) -> AnalyticsDetailPage:
    return get_business_analytics_detail_page(
        db,
        actor=actor,
        resource=resource,
        store_connection_id=store_connection_id,
        preset=preset,
        start=start,
        end=end,
        currency=currency,
        timezone_name=timezone,
        page=page,
        page_size=page_size,
        product_measure=product_measure,
    )


@router.post("/analytics/expenses", response_model=ExpenseRecord, status_code=status.HTTP_201_CREATED)
def create_expense_route(
    payload: ExpenseCreateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> ExpenseRecord:
    return create_expense(db, actor=actor, payload=payload)


@router.patch("/analytics/expenses/{expense_id}", response_model=ExpenseRecord)
def update_expense_route(
    expense_id: str,
    payload: ExpenseUpdateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> ExpenseRecord:
    return update_expense(db, actor=actor, expense_id=expense_id, payload=payload)


@router.delete("/analytics/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense_route(
    expense_id: str,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> Response:
    delete_expense(db, actor=actor, expense_id=expense_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/analytics/unmatched/{line_id}/map", status_code=status.HTTP_204_NO_CONTENT)
def map_order_line_route(
    line_id: str,
    payload: OrderLineMappingRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> Response:
    map_order_line(db, actor=actor, line_id=line_id, payload=payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/analytics/preferences", response_model=AnalyticsPreferencesResponse)
def update_analytics_preferences_route(
    payload: AnalyticsPreferencesUpdateRequest,
    db: Session = Depends(get_db),
    actor: ActorContext = Depends(get_admin_actor_context),
) -> AnalyticsPreferencesResponse:
    return update_analytics_preferences(db, actor=actor, payload=payload)

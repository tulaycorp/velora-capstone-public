from fastapi import APIRouter

from app.api.routes import (
    ai,
    analytics,
    blueprints,
    design_assets,
    etsy,
    health,
    organizations,
    orders,
    pod_providers,
    product_studio,
    products,
    provider_store_connections,
    publishing_jobs,
    session_context,
    sync_jobs,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(session_context.router)
api_router.include_router(organizations.router)
api_router.include_router(analytics.router)
api_router.include_router(blueprints.router)
api_router.include_router(design_assets.router)
api_router.include_router(etsy.router)
api_router.include_router(products.router)
api_router.include_router(product_studio.router)
api_router.include_router(pod_providers.router)
api_router.include_router(provider_store_connections.router)
api_router.include_router(ai.router)
api_router.include_router(publishing_jobs.router)
api_router.include_router(orders.router)
api_router.include_router(sync_jobs.router)

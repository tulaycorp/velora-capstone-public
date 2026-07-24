import asyncio
from contextlib import asynccontextmanager, suppress
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger, log_event, reset_request_id, set_request_id
from app.db.database import Base, assert_non_bypass_database_role, engine
from app.services.media_uploads import BoundedMediaUploadMiddleware

request_logger = get_logger("request")
database_logger = get_logger("database")

CORS_ALLOWED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_ALLOWED_HEADERS = ["Authorization", "Content-Type", "X-Request-ID"]
CORS_EXPOSED_HEADERS = ["X-Request-ID"]


async def purge_idle_database_connections(interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        await asyncio.to_thread(engine.pool.dispose)
        log_event(
            database_logger,
            "database.pool.idle_connections_purged",
            verbose_only=True,
            interval_seconds=interval_seconds,
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(bind=engine)
    if settings.environment.strip().lower() not in {"development", "test"}:
        assert_non_bypass_database_role(
            engine,
            required_role=settings.database_runtime_role,
        )

    purge_task = None
    if settings.database_idle_pool_purge_seconds > 0:
        purge_task = asyncio.create_task(
            purge_idle_database_connections(settings.database_idle_pool_purge_seconds),
            name="database-idle-pool-purge",
        )

    try:
        yield
    finally:
        if purge_task is not None:
            purge_task.cancel()
            with suppress(asyncio.CancelledError):
                await purge_task
        await asyncio.to_thread(engine.dispose)
        log_event(database_logger, "database.pool.disposed")


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=CORS_ALLOWED_METHODS,
        allow_headers=CORS_ALLOWED_HEADERS,
        expose_headers=CORS_EXPOSED_HEADERS,
    )
    app.add_middleware(BoundedMediaUploadMiddleware)

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or f"req_{uuid.uuid4().hex}"
        token = set_request_id(request_id)
        request.state.request_id = request_id
        started_at = time.perf_counter()
        log_event(
            request_logger,
            "http.request.started",
            verbose_only=True,
            method=request.method,
            path=request.url.path,
            query_present=bool(request.url.query),
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            log_event(
                request_logger,
                "http.request.failed",
                level=logging.ERROR,
                method=request.method,
                path=request.url.path,
                duration_ms=duration_ms,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
            raise
        finally:
            reset_request_id(token)

        response.headers["x-request-id"] = request_id
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        token = set_request_id(request_id)
        try:
            log_event(
                request_logger,
                "http.request.completed",
                verbose_only=True,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        finally:
            reset_request_id(token)
        return response

    app.include_router(api_router)
    return app


app = create_app()

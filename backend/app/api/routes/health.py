import redis
from fastapi import APIRouter, HTTPException
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.database import engine
from app.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
    )


def _database_is_ready() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


def _redis_is_ready() -> bool:
    client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
        retry_on_timeout=False,
    )
    try:
        return bool(client.ping())
    except (RedisError, OSError):
        return False
    finally:
        client.close()


@router.get("/health/ready", response_model=HealthResponse)
def readiness() -> HealthResponse:
    """Report whether API dependencies shared by workers are currently reachable."""
    if not _database_is_ready() or not _redis_is_ready():
        raise HTTPException(
            status_code=503,
            detail="Required runtime dependencies are unavailable.",
        )

    return HealthResponse(
        status="ready",
        app=settings.app_name,
        version=settings.app_version,
    )

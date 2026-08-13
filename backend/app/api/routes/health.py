"""Health check + readiness probe endpoints."""
from fastapi import APIRouter, Response, status

from app.database.session import AsyncSessionLocal, engine
from app.observability import logger

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Liveness probe: the process is up and serving requests."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> dict:
    """Readiness probe: dependencies (PostgreSQL) are reachable.

    Returns 503 until the database connection succeeds so that the orchestrator
    keeps the container out of the load-balancer pool until it is truly ready.
    """
    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text

            await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("ready_check_failed", error=str(exc)[:200])
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "detail": "database_unreachable"}
    return {"status": "ready", "database": "postgresql"}


@router.get("/readyz")
async def readyz() -> dict:
    """Alias of /ready used by some orchestrators."""
    return await ready(response=Response())

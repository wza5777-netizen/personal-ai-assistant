from fastapi import APIRouter

from app.api.routes import (
    approvals,
    auth,
    calendar,
    chat,
    health,
    knowledge,
    memories,
    runs,
    tasks,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(chat.router, prefix="/api/v1")
api_router.include_router(tasks.router, prefix="/api/v1")
api_router.include_router(calendar.router, prefix="/api/v1")
api_router.include_router(memories.router, prefix="/api/v1")
api_router.include_router(knowledge.router, prefix="/api/v1")
api_router.include_router(approvals.router, prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(runs.router)

__all__ = ["api_router"]

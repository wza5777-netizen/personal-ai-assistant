"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.api.middleware.error_handling import register_error_handling
from app.config import settings
from app.database.session import init_db
from app.observability import configure_logging, logger

# CORS origins: local defaults + any extra origins from the environment
# (comma-separated). Set CORS_ORIGINS in production to include the deployed
# frontend and API domains, e.g.
#   https://your-frontend.onrender.com,https://personal-ai-assistant-l97e.onrender.com
#
# The deployed frontend origin is pinned here so cross-origin Bearer auth works
# in production. We use an explicit origin list + allow_credentials=True (NOT
# "*" + credentials, which browsers reject and which is unsafe). Authorization is
# implicitly allowed because allow_headers=["*"] covers it.
_extra_origins = [o.strip() for o in (settings.cors_origins or "").split(",") if o.strip()]
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://personal-ai-assistant-web-a1lt.onrender.com",
    *_extra_origins,
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("starting_personal_ai_assistant")
    yield
    # Graceful shutdown: release the database connection pool so in-flight
    # connections are closed cleanly instead of being dropped abruptly.
    logger.info("shutting_down")
    from app.database.session import engine

    await engine.dispose()


app = FastAPI(title="Personal AI Assistant", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# Production error-handling layer: request-id middleware + global exception
# handlers. Intentionally does not touch streaming / LangGraph / tools.
register_error_handling(app)


@app.get("/")
async def root() -> dict:
    return {"service": "personal-ai-assistant", "docs": "/docs"}

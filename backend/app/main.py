"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.database.session import init_db
from app.observability import configure_logging, logger

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
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


@app.get("/")
async def root() -> dict:
    return {"service": "personal-ai-assistant", "docs": "/docs"}

"""FastAPI application entrypoint."""
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.api.middleware.error_handling import register_error_handling
from app.config import settings
from app.database.session import init_db
from app.mcp.client import StdioMCPClient, StreamableHttpMCPClient
from app.mcp.registry import mcp_registry
from app.observability import configure_logging, logger
from app.tools.gateway import gateway as tool_gateway

#: Absolute path to the backend package root, resolved from *this* file so the
#: MCP server script is found regardless of the process' current working
#: directory. This keeps local ``cd backend && uv run uvicorn`` and Render
#: (Root Directory = backend) deployments equivalent.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
MCP_TIME_SERVER_SCRIPT = _BACKEND_ROOT / "mcp_servers" / "time_server" / "server.py"
MCP_TIME_SERVER_NAME = "time_server"

#: GitHub official Remote MCP Server integration (read-only).
MCP_GITHUB_SERVER_NAME = "github"
MCP_GITHUB_TOOL_PREFIX = "github."
MCP_GITHUB_PERMISSION = "github:read"

#: PostgreSQL MCP Server integration (read-only, opt-in).
#: Launched over stdio via npx @yawlabs/postgres-mcp. The DB connection string is
#: injected into the subprocess env as DATABASE_URL — never as a CLI argument and
#: never logged. MUST point at an independent read-only role (mcp_reader); the
#: app's own DATABASE_URL is NOT used here.
MCP_POSTGRES_SERVER_NAME = "postgres"
MCP_POSTGRES_TOOL_PREFIX = "postgres."
MCP_POSTGRES_PERMISSION = "database:read"
MCP_POSTGRES_NPX_PACKAGE = "@yawlabs/postgres-mcp@latest"

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


async def _init_time_server() -> None:
    """Launch the local time_server (stdio) MCP server.

    A failure here must NOT abort the whole FastAPI boot — Native tools and the
    Chat API must stay available — so any exception is caught, logged (without
    secrets), and the server is simply left unavailable. The gateway then
    returns an explicit MCP-unavailable error rather than silently falling back
    to a native tool.
    """
    if not MCP_TIME_SERVER_SCRIPT.exists():
        logger.error(
            "mcp_server_script_missing",
            server_name=MCP_TIME_SERVER_NAME,
            path=str(MCP_TIME_SERVER_SCRIPT),
        )
        return

    client = StdioMCPClient(
        server_name=MCP_TIME_SERVER_NAME,
        command=sys.executable,
        args=[str(MCP_TIME_SERVER_SCRIPT)],
        cwd=str(_BACKEND_ROOT),
    )
    try:
        mcp_registry.register_server(client)
        # Mirror the client onto the singleton gateway so tool routing resolves
        # the server directly (the gateway also falls back to the registry, but
        # this keeps the hot path free of extra lookups).
        tool_gateway.register_mcp_client(MCP_TIME_SERVER_NAME, client)
        discovered = await mcp_registry.discover_tools()
        tool_names = [d.name for d in discovered]
        logger.info(
            "mcp_server_connected",
            server_name=MCP_TIME_SERVER_NAME,
            tool_names=tool_names,
        )
        logger.info(
            "mcp_tools_discovered",
            server_name=MCP_TIME_SERVER_NAME,
            tool_names=tool_names,
        )
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, keep app up
        mcp_registry._clients.pop(MCP_TIME_SERVER_NAME, None)
        tool_gateway.mcp_clients.pop(MCP_TIME_SERVER_NAME, None)
        logger.error(
            "mcp_server_initialization_failed",
            server_name=MCP_TIME_SERVER_NAME,
            error_type=type(exc).__name__,
        )


async def _init_github_mcp() -> None:
    """Connect the official GitHub Remote MCP Server (read-only).

    Opt-in via ``GITHUB_MCP_ENABLED=true``. Errors (timeout / 401 / unavailable
    / discovery failure) are isolated: they are logged with structured context
    but never break the app boot, the time_server, or native tools. The GitHub
    tools are simply left unregistered / unavailable.
    """
    if not settings.github_mcp_enabled:
        logger.info("github_mcp_disabled")
        return
    if not settings.github_mcp_token:
        logger.error(
            "github_mcp_token_missing",
            server_name=MCP_GITHUB_SERVER_NAME,
        )
        return

    # Read-only + toolset restriction via request headers. The token is supplied
    # ONLY here and is never logged or echoed into exceptions.
    headers = {
        "Authorization": f"Bearer {settings.github_mcp_token}",
        "X-MCP-Toolsets": settings.github_mcp_toolsets,
        "X-MCP-Readonly": "true",
    }
    client = StreamableHttpMCPClient(
        server_name=MCP_GITHUB_SERVER_NAME,
        url=settings.github_mcp_url,
        headers=headers,
        timeout=settings.github_mcp_timeout,
    )
    try:
        mcp_registry.register_server(
            client,
            tool_prefix=MCP_GITHUB_TOOL_PREFIX,
            default_permission=MCP_GITHUB_PERMISSION,
        )
        tool_gateway.register_mcp_client(MCP_GITHUB_SERVER_NAME, client)
        discovered = await mcp_registry.discover_tools()
        tool_names = [d.name for d in discovered]
        logger.info(
            "github_mcp_connected",
            server_name=MCP_GITHUB_SERVER_NAME,
            tool_count=len(tool_names),
        )
        logger.info(
            "github_mcp_tools_discovered",
            server_name=MCP_GITHUB_SERVER_NAME,
            tool_names=tool_names,
        )
    except Exception as exc:  # noqa: BLE001 - isolate GitHub failure
        mcp_registry._clients.pop(MCP_GITHUB_SERVER_NAME, None)
        mcp_registry._tool_prefixes.pop(MCP_GITHUB_SERVER_NAME, None)
        mcp_registry._default_permissions.pop(MCP_GITHUB_SERVER_NAME, None)
        tool_gateway.mcp_clients.pop(MCP_GITHUB_SERVER_NAME, None)
        # NOTE: token is intentionally NOT included anywhere in this log line.
        logger.error(
            "github_mcp_initialization_failed",
            server_name=MCP_GITHUB_SERVER_NAME,
            error_type=type(exc).__name__,
        )


async def _init_postgres_mcp() -> None:
    """Connect the PostgreSQL MCP Server (@yawlabs/postgres-mcp) over stdio.

    Opt-in via ``POSTGRES_MCP_ENABLED=true``. The server is launched as a
    subprocess with its connection string injected into its environment as
    ``DATABASE_URL`` (never as a CLI argument, never logged). The integration is
    read-only by default and all tools require ``database:read``.

    Safety:
      * ALLOW_WRITES is intentionally NEVER set — the server stays read-only.
      * Production MUST use an independent read-only Postgres role (mcp_reader).
        The MCP server's read-only mode is NOT the only security boundary; a
        dedicated role is the real defense-in-depth control.
      * A missing DATABASE_URL or any startup/discovery failure is isolated: it
        is logged (without secrets) and the app boot continues normally. Native
        tools, the time_server, and GitHub MCP are unaffected.
    """
    if not settings.postgres_mcp_enabled:
        logger.info("postgres_mcp_disabled")
        return
    if not settings.postgres_mcp_database_url:
        logger.warning(
            "postgres_mcp_database_url_missing",
            server_name=MCP_POSTGRES_SERVER_NAME,
            hint="set POSTGRES_MCP_DATABASE_URL to an independent read-only connection string",
        )
        return

    # Inject the DB URL into the MCP server's environment only. ALLOW_WRITES is
    # deliberately omitted so the server keeps its default read-only behaviour.
    env = {
        "DATABASE_URL": settings.postgres_mcp_database_url,
    }
    client = StdioMCPClient(
        server_name=MCP_POSTGRES_SERVER_NAME,
        command="npx",
        args=["-y", MCP_POSTGRES_NPX_PACKAGE],
        env=env,
        cwd=str(_BACKEND_ROOT),
    )
    try:
        mcp_registry.register_server(
            client,
            tool_prefix=MCP_POSTGRES_TOOL_PREFIX,
            default_permission=MCP_POSTGRES_PERMISSION,
        )
        tool_gateway.register_mcp_client(MCP_POSTGRES_SERVER_NAME, client)
        discovered = await mcp_registry.discover_tools()
        tool_names = [d.name for d in discovered]
        logger.info(
            "postgres_mcp_connected",
            server_name=MCP_POSTGRES_SERVER_NAME,
            tool_count=len(tool_names),
        )
        logger.info(
            "postgres_mcp_tools_discovered",
            server_name=MCP_POSTGRES_SERVER_NAME,
            tool_names=tool_names,
        )
    except Exception as exc:  # noqa: BLE001 - isolate Postgres MCP failure
        mcp_registry._clients.pop(MCP_POSTGRES_SERVER_NAME, None)
        mcp_registry._tool_prefixes.pop(MCP_POSTGRES_SERVER_NAME, None)
        mcp_registry._default_permissions.pop(MCP_POSTGRES_SERVER_NAME, None)
        tool_gateway.mcp_clients.pop(MCP_POSTGRES_SERVER_NAME, None)
        # NOTE: DATABASE_URL is intentionally NOT included anywhere in this log.
        logger.error(
            "postgres_mcp_initialization_failed",
            server_name=MCP_POSTGRES_SERVER_NAME,
            error_type=type(exc).__name__,
        )


async def _initialize_mcp_servers() -> None:
    """Bring up every configured MCP server during startup.

    Each server is initialized independently so a failure in one (e.g. GitHub
    remote unreachable, Postgres MCP down) cannot affect the others (e.g. the
    local time_server) or the overall FastAPI boot.
    """
    await _init_time_server()
    await _init_github_mcp()
    await _init_postgres_mcp()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("starting_personal_ai_assistant")
    # Bring up MCP servers (best-effort; never blocks the app from starting).
    await _initialize_mcp_servers()
    yield
    # Graceful shutdown: close MCP server subprocesses first, then the DB pool.
    logger.info("shutting_down")
    try:
        await mcp_registry.shutdown()
    except Exception as exc:  # noqa: BLE001 - never block DB/other cleanup
        logger.error(
            "mcp_shutdown_error",
            error_type=type(exc).__name__,
        )
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

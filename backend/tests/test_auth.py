"""Tests for user JWT authentication (Step 10.3-A).

These run against an isolated SQLite database (no Postgres/Neon required) with
the real auth code paths (bcrypt hashing, jose JWT, FastAPI dependency chain).
"""
import os
import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Ensure a JWT secret is configured before importing app modules.
os.environ.setdefault("JWT_SECRET", "test-secret-for-auth-tests")
os.environ.setdefault("APP_ENV", "development")

from app.config import settings  # noqa: E402
from app.database.session import Base, get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import user as _user_model  # noqa: E402,F401  (register User)
from app.security import auth  # noqa: E402

settings.jwt_secret = "test-secret-for-auth-tests"

DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(DATABASE_URL, future=True)
SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_get_session():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Test 1: register persists only password_hash (never plaintext)
# --------------------------------------------------------------------------- #
async def test_register_stores_only_hash(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "Alice@Example.com", "password": "supersecret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "alice@example.com"  # normalized
    assert "access_token" in body

    # Inspect DB row directly: password_hash present, plaintext password absent.
    from sqlalchemy import select

    from app.models.user import User

    async with SessionLocal() as session:
        row = (await session.execute(select(User).where(User.email == "alice@example.com"))).scalar_one()
        assert row.password_hash is not None
        assert row.password_hash != "supersecret"
        assert not row.password_hash.startswith("supersecret")
        assert "$2" in row.password_hash  # bcrypt prefix


# --------------------------------------------------------------------------- #
# Test 2: duplicate email registration fails
# --------------------------------------------------------------------------- #
async def test_register_duplicate_email_fails(client: AsyncClient):
    payload = {"email": "dup@example.com", "password": "supersecret"}
    r1 = await client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 409


# --------------------------------------------------------------------------- #
# Test 3: correct password logs in and yields a JWT
# --------------------------------------------------------------------------- #
async def test_login_success_returns_jwt(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "login@example.com", "password": "correcthorse"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "correcthorse"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["user"]["email"] == "login@example.com"


# --------------------------------------------------------------------------- #
# Test 4: wrong password -> 401
# --------------------------------------------------------------------------- #
async def test_login_wrong_password_401(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "wp@example.com", "password": "rightpass"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "wp@example.com", "password": "wrongpass"},
    )
    assert resp.status_code == 401
    # Global error handler returns {"error": {"code", "message", "request_id"}}.
    assert resp.json()["error"]["message"] == "Invalid email or password"


# --------------------------------------------------------------------------- #
# Test 5: GET /auth/me with valid JWT returns the current user
# --------------------------------------------------------------------------- #
async def test_me_with_valid_jwt(client: AsyncClient):
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "me@example.com", "password": "supersecret"},
    )
    token = reg.json()["access_token"]
    resp = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "me@example.com"
    assert "password_hash" not in body
    assert "id" in body and "created_at" in body


# --------------------------------------------------------------------------- #
# Test 6: no JWT -> 401
# --------------------------------------------------------------------------- #
async def test_me_without_jwt_401(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# Test 7: expired / invalid JWT -> 401
# --------------------------------------------------------------------------- #
async def test_me_expired_or_invalid_jwt_401(client: AsyncClient):
    # Invalid signature token
    bad = auth.create_user_access_token("someone")
    forged = bad + "tamper"
    resp = await client.get("/api/v1/auth/me", headers=_auth_headers(forged))
    assert resp.status_code == 401

    # Expired token
    expired = auth.create_user_access_token("someone", ttl_minutes=-10)
    resp2 = await client.get("/api/v1/auth/me", headers=_auth_headers(expired))
    assert resp2.status_code == 401

    # Non-existent user id
    ghost = auth.create_user_access_token(str(uuid.uuid4()))
    resp3 = await client.get("/api/v1/auth/me", headers=_auth_headers(ghost))
    assert resp3.status_code == 401


# --------------------------------------------------------------------------- #
# Test 8: ordinary user JWT cannot access admin-protected API
# --------------------------------------------------------------------------- #
async def test_user_token_cannot_access_admin_api(client: AsyncClient):
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": "noadmin@example.com", "password": "supersecret"},
    )
    user_token = reg.json()["access_token"]
    # The admin Observability API is mounted at /api/v1/admin/runs.
    resp = await client.get("/api/v1/admin/runs", headers=_auth_headers(user_token))
    # Admin guard enforces ADMIN_AUDIENCE; a USER_AUDIENCE token must be rejected.
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


# --------------------------------------------------------------------------- #
# Test 9: admin token is not usable as a user token
# --------------------------------------------------------------------------- #
async def test_admin_token_not_usable_as_user_token(client: AsyncClient):
    admin_token = auth.create_admin_token(ttl_minutes=60)
    resp = await client.get("/api/v1/auth/me", headers=_auth_headers(admin_token))
    # get_current_user enforces USER_AUDIENCE; an ADMIN_AUDIENCE token is rejected.
    assert resp.status_code == 401

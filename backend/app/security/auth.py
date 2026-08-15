"""Authentication / authorization helpers.

Two independent JWT audiences are used so that tokens are purpose-scoped:

* ``ADMIN_AUDIENCE`` — Observability Admin API (existing). Issued via
  ``create_admin_token`` and validated by ``verify_admin_token``.
* ``USER_AUDIENCE`` — ordinary end-user auth. Issued via
  ``create_user_access_token`` and validated by ``get_current_user``.

A user token can never satisfy the admin guard and vice versa, because the
``aud`` claim is checked on every decode.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.session import get_session
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

ADMIN_AUDIENCE = "personal-ai-assistant-admin"
USER_AUDIENCE = "personal-ai-assistant-user"

_BCRYPT_ROUNDS = 12


# --------------------------------------------------------------------------- #
# Admin JWT (existing Observability guard — untouched behaviour, only the
# audience constant is reused to keep user/admin tokens distinct).
# --------------------------------------------------------------------------- #
def create_admin_token(ttl_minutes: int = 60) -> str:
    """Issue a short-lived admin JWT. Requires ``settings.jwt_secret`` to be set."""
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured",
        )
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "admin",
        "aud": ADMIN_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_admin_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    """Validate the admin JWT and return its claims."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured",
        )
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=ADMIN_AUDIENCE,
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired admin token",
        )
    return claims


# --------------------------------------------------------------------------- #
# Password hashing (bcrypt, via the project dependency — not passlib, which is
# incompatible with bcrypt>=4 at runtime).
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt. Returns the encoded hash string."""
    pwd_bytes = password.encode("utf-8")
    hashed = bcrypt.hashpw(pwd_bytes, bcrypt.gensalt(_BCRYPT_ROUNDS))
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time verify a plaintext password against a bcrypt hash."""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# User JWT
# --------------------------------------------------------------------------- #
def create_user_access_token(user_id: str, ttl_minutes: int | None = None) -> str:
    """Issue a user access token (HS256) scoped to ``USER_AUDIENCE``."""
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured",
        )
    now = datetime.now(timezone.utc)
    ttl = ttl_minutes or settings.access_token_expire_minutes
    payload = {
        "sub": user_id,
        "aud": USER_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_user_token(token: str) -> dict[str, Any]:
    """Decode + validate a user token. Raises ``JWTError`` on any failure.

    Callers must pass a 401 on error.
    """
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=USER_AUDIENCE,
    )


# --------------------------------------------------------------------------- #
# get_current_user dependency
# --------------------------------------------------------------------------- #
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resolve the authenticated ``User`` from the bearer token.

    Returns 401 for any of: missing token, invalid signature, expired token,
    wrong audience, or non-existent user. The user identity is NEVER taken from
    the request body or query string.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    if not settings.jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET is not configured",
        )
    try:
        claims = decode_user_token(credentials.credentials)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
        )

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user

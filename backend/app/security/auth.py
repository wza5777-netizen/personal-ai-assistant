"""Authentication / authorization helpers.

Provides a minimal JWT-based admin guard for the observability Admin API. The
token is a signed JWT using ``settings.jwt_secret``. In development, a token can
be produced by POST /api/v1/admin/token with the shared secret. In production
the secret must come from the environment (``JWT_SECRET``) and must never be
committed.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import settings

bearer_scheme = HTTPBearer(auto_error=False)

ADMIN_AUDIENCE = "personal-ai-assistant-admin"


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

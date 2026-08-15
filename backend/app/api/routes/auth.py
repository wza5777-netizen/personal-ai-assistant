"""User authentication routes: register, login, and /me.

This module ONLY establishes the user-auth foundation. Business APIs
(chat/tasks/calendar/...) are intentionally left on DEFAULT_USER_ID and are
NOT touched here.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.models.user import User
from app.schemas.user import TokenResponse, UserLogin, UserOut, UserRegister
from app.security import auth

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _validate_email(email: str) -> None:
    if "@" not in email or email.startswith("@") or email.endswith("@") or "." not in email.split("@", 1)[1]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email format",
        )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def register(
    payload: UserRegister,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Register a new user and return a signed access token.

    Email is normalized (trimmed + lower-cased) and must be unique.
    """
    email = _normalize_email(payload.email)
    _validate_email(email)

    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    password_hash = auth.hash_password(payload.password)
    user = User(
        id=uuid.uuid4().hex,
        email=email,
        display_name=email.split("@", 1)[0],
        password_hash=password_hash,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    token = auth.create_user_access_token(user.id)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: UserLogin,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Authenticate by email + password. Returns a user access token.

    A single generic 401 is returned for both "unknown email" and "wrong
    password" to avoid account enumeration.
    """
    email = _normalize_email(payload.email)
    _validate_email(email)

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Verify even when the user does not exist (constant-ish timing) but never
    # reveal which case happened.
    if user is None or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = auth.create_user_access_token(user.id)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(auth.get_current_user)) -> UserOut:
    """Return the currently authenticated user (from the bearer token)."""
    return UserOut.model_validate(current_user)

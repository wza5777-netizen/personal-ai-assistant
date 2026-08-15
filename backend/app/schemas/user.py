"""User-related API schemas.

``password_hash`` is intentionally never exposed in any response schema.

Note: we use plain ``str`` for email (not pydantic ``EmailStr``) to avoid
pulling in the optional ``email-validator`` dependency. Basic format validation
is done in the route layer.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserRegister(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    """Public user representation — never includes password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

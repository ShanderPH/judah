"""Pydantic v2 schemas for auth_user endpoints."""

from ninja import Schema
from pydantic import EmailStr, Field, field_validator


class LoginRequest(Schema):
    """Payload for user login."""

    username: str = Field(..., min_length=1, max_length=150)
    password: str = Field(..., min_length=1)


class RegisterRequest(Schema):
    """Payload for user registration."""

    username: str = Field(..., min_length=3, max_length=150)
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: str = Field(default="", max_length=150)
    last_name: str = Field(default="", max_length=150)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Ensure password meets minimum complexity requirements."""
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter.")
        return v


class TokenResponse(Schema):
    """JWT token pair response."""

    access: str
    refresh: str


class RefreshRequest(Schema):
    """Payload to refresh an access token."""

    refresh: str


class LogoutRequest(Schema):
    """Payload to log out and blacklist a refresh token."""

    refresh: str


class UserResponse(Schema):
    """Public user representation."""

    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    role: str
    avatar_url: str
    is_ai_agent: bool

    class Config:
        from_attributes = True


class UpdateProfileRequest(Schema):
    """Payload to update user profile fields."""

    first_name: str | None = Field(default=None, max_length=150)
    last_name: str | None = Field(default=None, max_length=150)
    avatar_url: str | None = None


class ChangePasswordRequest(Schema):
    """Payload to change the authenticated user's password."""

    current_password: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter.")
        return v

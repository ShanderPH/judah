"""Django Ninja API endpoints for auth_user."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ninja import Router
from ninja_jwt.tokens import RefreshToken

from apps.auth_user.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    RegisterRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from apps.auth_user.services import (
    authenticate_user,
    change_password,
    get_user_by_id,
    register_user,
    update_profile,
)
from common.exceptions import UnauthorizedError

if TYPE_CHECKING:
    from apps.auth_user.models import User

router = Router()


@router.post("/register", response={201: UserResponse}, auth=None, summary="Register a new user")
def register(request, payload: RegisterRequest) -> tuple[int, User]:
    """Create a new user account and return the user profile."""
    return 201, register_user(payload)


@router.post("/login", response=TokenResponse, auth=None, summary="Obtain JWT token pair")
def login(request, payload: LoginRequest) -> TokenResponse:
    """Authenticate with username/password and return access + refresh tokens."""
    user = authenticate_user(payload.username, payload.password)
    refresh = RefreshToken.for_user(user)
    return TokenResponse(
        access=str(refresh.access_token),
        refresh=str(refresh),
    )


@router.post("/refresh", response=TokenResponse, auth=None, summary="Refresh access token")
def refresh_token(request, refresh: str) -> TokenResponse:
    """Exchange a valid refresh token for a new access token."""
    try:
        token = RefreshToken(refresh)
        return TokenResponse(
            access=str(token.access_token),
            refresh=str(token),
        )
    except Exception as exc:
        raise UnauthorizedError("Invalid or expired refresh token.") from exc


@router.post("/logout", response={204: None}, auth=None, summary="Logout — blacklist refresh token")
def logout(request, payload: LogoutRequest) -> tuple[int, None]:
    """Invalidate the supplied refresh token by adding it to the blacklist.

    The frontend remains responsible for clearing its HttpOnly cookies
    after a successful response. Calling logout with a token that is
    already blacklisted, expired, or malformed succeeds silently to keep
    the operation idempotent.
    """
    try:
        token = RefreshToken(payload.refresh)
        token.blacklist()
    except Exception:  # noqa: BLE001 — idempotent best-effort blacklist
        pass
    return 204, None


@router.get("/me", response=UserResponse, summary="Get current user profile")
def get_me(request) -> User:
    """Return the profile of the currently authenticated user."""
    return request.auth


@router.patch("/me", response=UserResponse, summary="Update current user profile")
def update_me(request, payload: UpdateProfileRequest) -> User:
    """Update mutable fields on the authenticated user's profile."""
    return update_profile(request.auth, payload)


@router.post("/me/change-password", response={204: None}, summary="Change password")
def change_my_password(request, payload: ChangePasswordRequest) -> tuple[int, None]:
    """Change the password for the authenticated user."""
    change_password(request.auth, payload)
    return 204, None


@router.get("/{user_id}", response=UserResponse, summary="Get user by ID")
def get_user(request, user_id: int) -> User:
    """Fetch a user by their primary key. Requires authentication."""
    return get_user_by_id(user_id)

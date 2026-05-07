"""Business logic for auth_user app."""

import structlog
from django.contrib.auth.hashers import check_password
from django.db.models import Q

from apps.auth_user.models import User
from apps.auth_user.schemas import ChangePasswordRequest, RegisterRequest, UpdateProfileRequest
from common.exceptions import (
    CircuitOpenError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)

logger = structlog.get_logger(__name__)


def _truncate_identity(identifier: str, limit: int = 80) -> str:
    """Return a log-safe form of the identifier (truncated, never the password)."""
    if not identifier:
        return ""
    return identifier[:limit] + ("…" if len(identifier) > limit else "")


def register_user(payload: RegisterRequest) -> User:
    """Create and persist a new user account.

    Args:
        payload: Validated registration data.

    Returns:
        The newly created User instance.

    Raises:
        ConflictError: If the username or email already exists.
    """
    if User.objects.filter(username=payload.username).exists():
        raise ConflictError(f"Username '{payload.username}' is already taken.")
    if User.objects.filter(email=payload.email).exists():
        raise ConflictError(f"Email '{payload.email}' is already registered.")

    user = User.objects.create_user(
        username=payload.username,
        email=payload.email,
        password=payload.password,
        first_name=payload.first_name,
        last_name=payload.last_name,
    )
    logger.info("user_registered", user_id=user.pk, username=user.username)
    return user


def authenticate_user(identifier: str, password: str) -> User:
    """Authenticate a user by username **or** email plus password.

    Lookups on both ``username`` and ``email`` are case-insensitive (``iexact``)
    so users typing ``Felipe.Braat`` or ``SHANDER@inchurch.com.br`` do not get
    a misleading 401 because of casing alone.

    Args:
        identifier: Either the user's ``username`` or registered ``email``.
        password: The raw password.

    Returns:
        The authenticated User instance.

    Raises:
        UnauthorizedError: If credentials are invalid or account is inactive.
        CircuitOpenError: If the auth subsystem (DB) is degraded.
    """
    identity = (identifier or "").strip()
    identity_log = _truncate_identity(identity)
    identity_kind = "email" if "@" in identity else "username"

    if not identity or not password:
        logger.info(
            "auth_failed_missing_credentials",
            identity=identity_log,
            identity_kind=identity_kind,
            has_identity=bool(identity),
            has_password=bool(password),
        )
        raise UnauthorizedError("Invalid username or password.")

    try:
        candidate = (
            User.objects.filter(Q(username__iexact=identity) | Q(email__iexact=identity))
            .order_by("-is_active", "id")
            .first()
        )
    except Exception as exc:
        logger.exception(
            "auth_db_failure",
            identity=identity_log,
            identity_kind=identity_kind,
            error_type=type(exc).__name__,
            error_message=str(exc),
            error_module=type(exc).__module__,
        )
        raise CircuitOpenError("Authentication is temporarily unavailable.") from None

    if candidate is None:
        logger.info(
            "auth_failed_user_not_found",
            identity=identity_log,
            identity_kind=identity_kind,
        )
        raise UnauthorizedError("Invalid username or password.")

    try:
        password_ok = candidate.check_password(password)
    except Exception as exc:
        logger.exception(
            "auth_password_check_failure",
            user_id=candidate.pk,
            identity=identity_log,
            identity_kind=identity_kind,
            error_type=type(exc).__name__,
            error_message=str(exc),
            error_module=type(exc).__module__,
        )
        raise CircuitOpenError("Authentication is temporarily unavailable.") from None

    if not password_ok:
        logger.info(
            "auth_failed_invalid_password",
            user_id=candidate.pk,
            identity=identity_log,
            identity_kind=identity_kind,
        )
        raise UnauthorizedError("Invalid username or password.")

    if not candidate.is_active:
        logger.info(
            "auth_failed_inactive_user",
            user_id=candidate.pk,
            identity=identity_log,
            identity_kind=identity_kind,
        )
        raise UnauthorizedError("This account has been deactivated.")

    logger.info(
        "user_authenticated",
        user_id=candidate.pk,
        identity=identity_log,
        identity_kind=identity_kind,
    )
    return candidate


def get_user_by_id(user_id: int) -> User:
    """Fetch a single user by primary key.

    Raises:
        NotFoundError: If no user with the given ID exists.
    """
    try:
        return User.objects.get(pk=user_id)
    except User.DoesNotExist as err:
        raise NotFoundError(f"User with id={user_id} not found.") from err


def update_profile(user: User, payload: UpdateProfileRequest) -> User:
    """Update mutable profile fields for an authenticated user.

    Args:
        user: The User instance to update.
        payload: Fields to change (partial update).

    Returns:
        The updated User instance.
    """
    updated_fields: list[str] = []
    if payload.first_name is not None:
        user.first_name = payload.first_name
        updated_fields.append("first_name")
    if payload.last_name is not None:
        user.last_name = payload.last_name
        updated_fields.append("last_name")
    if payload.avatar_url is not None:
        user.avatar_url = payload.avatar_url
        updated_fields.append("avatar_url")

    if updated_fields:
        user.save(update_fields=[*updated_fields, "updated_at"])
        logger.info("user_profile_updated", user_id=user.pk, fields=updated_fields)
    return user


def change_password(user: User, payload: ChangePasswordRequest) -> None:
    """Change the password for an authenticated user.

    Raises:
        ValidationError: If the current password does not match.
    """
    if not check_password(payload.current_password, user.password):
        raise ValidationError("Current password is incorrect.")
    user.set_password(payload.new_password)
    user.save(update_fields=["password", "updated_at"])
    logger.info("user_password_changed", user_id=user.pk)

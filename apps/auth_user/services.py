"""Business logic for auth_user app."""

import structlog
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import check_password

from apps.auth_user.models import User
from apps.auth_user.schemas import ChangePasswordRequest, RegisterRequest, UpdateProfileRequest
from common.exceptions import ConflictError, NotFoundError, UnauthorizedError, ValidationError

logger = structlog.get_logger(__name__)


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

    Args:
        identifier: Either the user's ``username`` or registered ``email``.
        password: The raw password.

    Returns:
        The authenticated User instance.

    Raises:
        UnauthorizedError: If credentials are invalid or account is inactive.
    """
    try:
        user = authenticate(username=identifier, password=password)
        if user is None and "@" in identifier:
            candidate = User.objects.filter(email__iexact=identifier).first()
            if candidate is not None:
                user = authenticate(username=candidate.username, password=password)
    except Exception as exc:
        # ProgrammingError (missing column / table), OperationalError (DB
        # down) etc. Log full trace and fail with a typed error so the API
        # layer maps to 401, not silent 500.
        logger.exception(
            "authenticate_user_db_failure",
            identifier_kind="email" if "@" in identifier else "username",
            error_type=type(exc).__name__,
            error_message=str(exc),
            error_module=type(exc).__module__,
        )
        raise UnauthorizedError("Authentication is temporarily unavailable.") from None
    if user is None:
        logger.info("auth_failed_invalid_credentials")
        raise UnauthorizedError("Invalid username or password.")
    if not user.is_active:
        raise UnauthorizedError("This account has been deactivated.")
    logger.info("user_authenticated", user_id=user.pk)
    return user


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

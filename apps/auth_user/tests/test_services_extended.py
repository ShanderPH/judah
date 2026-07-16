"""Additional auth-service error and profile coverage."""

from unittest.mock import Mock, patch

import pytest

from apps.auth_user.models import User
from apps.auth_user.schemas import ChangePasswordRequest, RegisterRequest, UpdateProfileRequest
from apps.auth_user.services import (
    _truncate_identity,
    authenticate_user,
    change_password,
    get_user_by_id,
    register_user,
    update_profile,
)
from common.exceptions import CircuitOpenError, ConflictError, NotFoundError, UnauthorizedError, ValidationError


@pytest.mark.django_db
def test_register_conflicts_and_user_lookup() -> None:
    payload = RegisterRequest(
        username="user",
        email="user@example.com",
        password="StrongPassword123!",
        first_name="A",
        last_name="B",
    )
    user = register_user(payload)
    assert get_user_by_id(user.pk) == user
    with pytest.raises(ConflictError):
        register_user(payload)
    with pytest.raises(ConflictError):
        register_user(payload.model_copy(update={"username": "other"}))
    with pytest.raises(NotFoundError):
        get_user_by_id(999999)


@pytest.mark.django_db
def test_authentication_maps_database_and_password_check_failures() -> None:
    with (
        patch("apps.auth_user.services.User.objects.filter", side_effect=RuntimeError("db")),
        pytest.raises(CircuitOpenError),
    ):
        authenticate_user("user", "password")

    candidate = Mock(pk=1, is_active=True)
    candidate.check_password.side_effect = RuntimeError("hash backend")
    queryset = Mock()
    queryset.order_by.return_value.first.return_value = candidate
    with (
        patch("apps.auth_user.services.User.objects.filter", return_value=queryset),
        pytest.raises(CircuitOpenError),
    ):
        authenticate_user("user", "password")

    with pytest.raises(UnauthorizedError):
        authenticate_user("", "")


@pytest.mark.django_db
def test_profile_and_password_changes() -> None:
    user = User.objects.create_user(username="user", email="user@example.com", password="OldPassword123!")
    updated = update_profile(
        user,
        UpdateProfileRequest(
            first_name="Ana",
            last_name="Silva",
            avatar_url="https://example.com/avatar.png",
        ),
    )
    assert updated.first_name == "Ana"
    assert update_profile(user, UpdateProfileRequest()) == user

    with pytest.raises(ValidationError):
        change_password(
            user,
            ChangePasswordRequest(current_password="wrong", new_password="NewPassword123!"),
        )
    change_password(
        user,
        ChangePasswordRequest(current_password="OldPassword123!", new_password="NewPassword123!"),
    )
    user.refresh_from_db()
    assert user.check_password("NewPassword123!")


def test_truncate_identity() -> None:
    assert _truncate_identity("") == ""
    assert _truncate_identity("abc", limit=3) == "abc"
    assert _truncate_identity("abcdef", limit=3) == "abc…"

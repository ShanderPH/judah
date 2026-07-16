"""Direct endpoint tests for auth API branches not reached through routing tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.auth_user import api
from apps.auth_user.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LogoutRequest,
    RegisterRequest,
    UpdateProfileRequest,
)
from common.exceptions import CircuitOpenError, UnauthorizedError


def test_register_and_profile_endpoint_delegation() -> None:
    request = SimpleNamespace(auth=SimpleNamespace(pk=1))
    user = SimpleNamespace(pk=2)
    register_payload = RegisterRequest(
        username="new",
        email="new@example.com",
        password="StrongPassword123!",
    )
    update_payload = UpdateProfileRequest(first_name="Ana")
    password_payload = ChangePasswordRequest(
        current_password="OldPassword123!",
        new_password="NewPassword123!",
    )
    with (
        patch.object(api, "register_user", return_value=user) as register,
        patch.object(api, "update_profile", return_value=user) as update,
        patch.object(api, "change_password") as change,
        patch.object(api, "get_user_by_id", return_value=user) as get_user,
    ):
        assert api.register(request, register_payload) == (201, user)
        assert api.get_me(request) == request.auth
        assert api.update_me(request, update_payload) == user
        assert api.change_my_password(request, password_payload) == (204, None)
        assert api.get_user(request, 2) == user
    register.assert_called_once_with(register_payload)
    update.assert_called_once_with(request.auth, update_payload)
    change.assert_called_once_with(request.auth, password_payload)
    get_user.assert_called_once_with(2)


def test_login_success_and_token_mint_failure() -> None:
    user = SimpleNamespace(pk=1, username="user")
    refresh = MagicMock()
    refresh.__str__.return_value = "refresh-token"
    refresh.access_token.__str__.return_value = "access-token"
    payload = LoginRequest(username="user@test.local", password="password")
    with (
        patch.object(api, "authenticate_user", return_value=user),
        patch.object(api.RefreshToken, "for_user", return_value=refresh),
    ):
        response = api.login(None, payload)
    assert response.access == "access-token"
    assert response.refresh == "refresh-token"

    with (
        patch.object(api, "authenticate_user", return_value=user),
        patch.object(api.RefreshToken, "for_user", side_effect=RuntimeError("blacklist unavailable")),
        pytest.raises(CircuitOpenError),
    ):
        api.login(None, payload)


def test_refresh_success_and_invalid_token() -> None:
    token = MagicMock()
    token.__str__.return_value = "refresh-token"
    token.access_token.__str__.return_value = "access-token"
    with patch.object(api, "RefreshToken", return_value=token):
        response = api.refresh_token(None, "refresh-token")
    assert response.access == "access-token"

    with (
        patch.object(api, "RefreshToken", side_effect=ValueError("invalid")),
        pytest.raises(UnauthorizedError),
    ):
        api.refresh_token(None, "bad")


def test_logout_is_idempotent_for_valid_and_invalid_tokens() -> None:
    token = MagicMock()
    with patch.object(api, "RefreshToken", return_value=token):
        assert api.logout(None, LogoutRequest(refresh="valid")) == (204, None)
    token.blacklist.assert_called_once()

    with patch.object(api, "RefreshToken", side_effect=ValueError("invalid")):
        assert api.logout(None, LogoutRequest(refresh="invalid")) == (204, None)

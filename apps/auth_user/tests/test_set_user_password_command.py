"""Tests for the password reset management command."""

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.auth_user.models import User


@pytest.mark.django_db
def test_set_user_password_by_username_and_activate() -> None:
    user = User.objects.create_user(username="inactive", email="a@example.com", password="old", is_active=False)
    stdout = io.StringIO()

    call_command(
        "set_user_password",
        username=user.username,
        password="NewStrongPassword123!",
        activate=True,
        stdout=stdout,
    )

    user.refresh_from_db()
    assert user.check_password("NewStrongPassword123!")
    assert user.is_active is True
    assert "Password updated" in stdout.getvalue()


@pytest.mark.django_db
def test_set_user_password_by_email_from_environment(monkeypatch) -> None:
    user = User.objects.create_user(username="user", email="User@Example.com", password="old")
    monkeypatch.setenv("NEW_PASSWORD_FOR_TEST", "FromEnvironment123!")

    call_command(
        "set_user_password",
        email="user@example.com",
        password_env="NEW_PASSWORD_FOR_TEST",
    )

    user.refresh_from_db()
    assert user.check_password("FromEnvironment123!")


@pytest.mark.django_db
def test_set_user_password_reads_stdin(monkeypatch) -> None:
    user = User.objects.create_user(username="stdin-user", email="stdin@example.com", password="old")
    monkeypatch.setattr("sys.stdin", io.StringIO("FromStdin123!\n"))

    call_command("set_user_password", username=user.username, password_stdin=True)

    user.refresh_from_db()
    assert user.check_password("FromStdin123!")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kwargs",
    [
        {"username": "missing", "password": "ValidPassword123!"},
        {"username": "missing", "password": ""},
        {"username": "missing", "password_env": "UNSET_PASSWORD_ENV"},
    ],
)
def test_set_user_password_rejects_invalid_inputs(kwargs: dict) -> None:
    with pytest.raises(CommandError):
        call_command("set_user_password", **kwargs)


@pytest.mark.django_db
def test_set_user_password_rejects_empty_stdin(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(CommandError):
        call_command("set_user_password", username="missing", password_stdin=True)

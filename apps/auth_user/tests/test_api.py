"""Integration tests for auth_user API endpoints."""

import pytest
from django.test import Client

from apps.auth_user.models import User


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture(autouse=True)
def _clean_users(db):
    """Wipe ``auth_users`` before each auth test.

    The shared ``isolate_db`` fixture in the root conftest only clears support
    tables. Without this guard, a developer's seeded user (e.g. from
    ``set_user_password`` against the local DB) silently fails the login tests
    because the iexact lookup returns the older row instead of the test fixture.
    """
    User.objects.all().delete()


@pytest.fixture
def existing_user() -> User:
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="TestPass1",
    )


@pytest.fixture
def mixedcase_user() -> User:
    return User.objects.create_user(
        username="Felipe.Braat",
        email="Shander.Teixeira@inchurch.com.br",
        password="MixedCase1",
    )


@pytest.fixture
def inactive_user() -> User:
    user = User.objects.create_user(
        username="inactiveuser",
        email="inactive@example.com",
        password="TestPass1",
    )
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


@pytest.mark.django_db
class TestRegisterEndpoint:
    """Tests for POST /api/v1/auth/register."""

    def test_register_success(self, client: Client) -> None:
        response = client.post(
            "/api/v1/auth/register",
            data={
                "username": "newuser",
                "email": "new@example.com",
                "password": "NewPass1",
            },
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["role"] == "viewer"

    def test_register_duplicate_username(self, client: Client, existing_user: User) -> None:
        response = client.post(
            "/api/v1/auth/register",
            data={
                "username": "testuser",
                "email": "other@example.com",
                "password": "OtherPass1",
            },
            content_type="application/json",
        )
        assert response.status_code == 409

    def test_register_weak_password(self, client: Client) -> None:
        response = client.post(
            "/api/v1/auth/register",
            data={
                "username": "weakuser",
                "email": "weak@example.com",
                "password": "password",
            },
            content_type="application/json",
        )
        assert response.status_code == 422


@pytest.mark.django_db
class TestLoginEndpoint:
    """Tests for POST /api/v1/auth/login.

    The schema field is named ``username`` for backward compatibility, but the
    backend treats it as a generic *identity* — it accepts the user's username
    OR email, in any case. This mirrors what the webapp sends today (where the
    HeroUI input is labelled "Email").
    """

    def test_login_with_username(self, client: Client, existing_user: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "TestPass1"},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert "access" in data
        assert "refresh" in data

    def test_login_with_email(self, client: Client, existing_user: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "test@example.com", "password": "TestPass1"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert "access" in response.json()

    def test_login_with_email_uppercase(self, client: Client, existing_user: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "TEST@EXAMPLE.COM", "password": "TestPass1"},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_login_with_username_mixedcase(self, client: Client, mixedcase_user: User) -> None:
        # Stored username = "Felipe.Braat"; user types "felipe.braat".
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "felipe.braat", "password": "MixedCase1"},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_login_with_email_mixedcase(self, client: Client, mixedcase_user: User) -> None:
        # Stored email = "Shander.Teixeira@..."; user types lowercase.
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "shander.teixeira@inchurch.com.br", "password": "MixedCase1"},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_login_strips_whitespace_around_identity(self, client: Client, existing_user: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "  test@example.com  ", "password": "TestPass1"},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_login_wrong_password(self, client: Client, existing_user: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "wrongpassword"},
            content_type="application/json",
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password."

    def test_login_user_not_found(self, client: Client) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "ghost@example.com", "password": "whatever"},
            content_type="application/json",
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password."

    def test_login_inactive_user(self, client: Client, inactive_user: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "inactive@example.com", "password": "TestPass1"},
            content_type="application/json",
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "This account has been deactivated."

    def test_login_empty_password_returns_422(self, client: Client) -> None:
        # Pydantic schema requires min_length=1 password. Ninja maps to 422.
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": ""},
            content_type="application/json",
        )
        assert response.status_code == 422


@pytest.mark.django_db
class TestMeEndpoint:
    """Tests for GET /api/v1/auth/me — the post-login profile fetch."""

    def _login(self, client: Client, identity: str, password: str) -> str:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": identity, "password": password},
            content_type="application/json",
        )
        assert response.status_code == 200, response.content
        return response.json()["access"]

    def test_me_returns_profile_when_avatar_url_is_null(self, client: Client, existing_user: User) -> None:
        # Production users seeded without an avatar carry NULL in
        # auth_users.avatar_url. The response schema must accept None (or '')
        # or /auth/me 500s with a Pydantic ValidationError, breaking login UX.
        User.objects.filter(pk=existing_user.pk).update(avatar_url=None)
        access = self._login(client, "testuser", "TestPass1")
        response = client.get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {access}")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["username"] == "testuser"
        assert body["avatar_url"] is None

    def test_me_returns_profile_when_avatar_url_is_set(self, client: Client, existing_user: User) -> None:
        existing_user.avatar_url = "https://cdn.example.com/a.png"
        existing_user.save(update_fields=["avatar_url"])
        access = self._login(client, "testuser", "TestPass1")
        response = client.get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {access}")
        assert response.status_code == 200
        assert response.json()["avatar_url"] == "https://cdn.example.com/a.png"

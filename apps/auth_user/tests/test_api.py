"""Integration tests for auth_user API endpoints."""

import pytest
from django.test import Client

from apps.auth_user.models import User


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def existing_user(db) -> User:
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="TestPass1",
    )


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
    """Tests for POST /api/v1/auth/login."""

    def test_login_success(self, client: Client, existing_user: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "TestPass1"},
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert "access" in data
        assert "refresh" in data

    def test_login_wrong_password(self, client: Client, existing_user: User) -> None:
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "wrongpassword"},
            content_type="application/json",
        )
        assert response.status_code == 401

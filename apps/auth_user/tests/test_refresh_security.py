"""Integration tests for secure refresh rotation and capability exposure."""

import pytest
from django.test import Client

from apps.auth_user.models import User


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(
        username="refresh-user",
        email="refresh@example.com",
        password="TestPass1",
        role=User.Role.MANAGER,
    )


@pytest.mark.django_db
def test_refresh_rotates_and_rejects_replay(client: Client, user: User) -> None:
    login = client.post(
        "/api/v1/auth/login",
        data={"username": user.username, "password": "TestPass1"},
        content_type="application/json",
    )
    original_refresh = login.json()["refresh"]
    response = client.post(
        "/api/v1/auth/refresh",
        data={"refresh": original_refresh},
        content_type="application/json",
    )
    assert response.status_code == 200
    rotated = response.json()
    assert rotated["access"]
    assert rotated["refresh"] != original_refresh

    replay = client.post(
        "/api/v1/auth/refresh",
        data={"refresh": original_refresh},
        content_type="application/json",
    )
    assert replay.status_code == 401
    second_rotation = client.post(
        "/api/v1/auth/refresh",
        data={"refresh": rotated["refresh"]},
        content_type="application/json",
    )
    assert second_rotation.status_code == 200


@pytest.mark.django_db
def test_refresh_rejects_query_token_and_me_exposes_capabilities(client: Client, user: User) -> None:
    query_only = client.post(
        "/api/v1/auth/refresh?refresh=must-not-appear-in-urls",
        data={},
        content_type="application/json",
    )
    assert query_only.status_code == 422

    login = client.post(
        "/api/v1/auth/login",
        data={"username": user.username, "password": "TestPass1"},
        content_type="application/json",
    )
    me = client.get(
        "/api/v1/auth/me",
        HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}",
    )
    assert me.status_code == 200
    assert "support.admin.read" in me.json()["capabilities"]
    assert "sandbox.use" not in me.json()["capabilities"]

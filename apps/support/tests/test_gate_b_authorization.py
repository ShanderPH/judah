"""Gate B contracts for support authentication, RBAC, audit, and replay."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.test import Client
from ninja_jwt.tokens import RefreshToken

from apps.auth_user.models import User
from apps.support.admin_audit import execute_audited_action
from apps.support.models import AdministrativeActionAudit, Agent, SpecialSchedule
from common.exceptions import ConflictError


def _user(role: str, suffix: str) -> User:
    return User.objects.create_user(
        username=f"{role}-{suffix}",
        email=f"{role}-{suffix}@example.test",
        password="TestPass123",
        role=role,
    )


def _authorization(user: User) -> str:
    return f"Bearer {RefreshToken.for_user(user).access_token}"


def _headers(user: User, *, key: str | None = None) -> dict[str, str]:
    headers = {"HTTP_AUTHORIZATION": _authorization(user)}
    if key is not None:
        headers["HTTP_IDEMPOTENCY_KEY"] = key
    return headers


@pytest.mark.django_db
def test_sync_novo_requires_auth_and_manager_role_without_external_calls() -> None:
    client = Client()
    viewer = _user(User.Role.VIEWER, "sync")
    agent = _user(User.Role.AGENT, "sync")
    manager = _user(User.Role.MANAGER, "sync")
    admin = _user(User.Role.ADMIN, "sync")
    result = {"total_from_hubspot": 1, "created": 1, "skipped": 0, "already_assigned": 0}

    with patch("apps.support.auto_assign_service.sync_novo_stage_tickets", return_value=result) as sync:
        assert client.post("/api/v1/support/queue/sync-novo/").status_code == 401
        assert client.post("/api/v1/support/queue/sync-novo/", **_headers(viewer)).status_code == 403
        assert client.post("/api/v1/support/queue/sync-novo/", **_headers(agent)).status_code == 403
        assert sync.call_count == 0

        for index, user in enumerate((manager, admin), start=1):
            response = client.post(
                "/api/v1/support/queue/sync-novo/",
                **_headers(user, key=f"sync-{index}"),
            )
            assert response.status_code == 202, response.content
            assert response.json()["queued_for_assignment"] is True

    assert sync.call_count == 2
    assert (
        AdministrativeActionAudit.objects.filter(
            action="support.queue.sync_novo",
            status=AdministrativeActionAudit.Status.SUCCEEDED,
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_sync_novo_replays_response_for_same_idempotency_key() -> None:
    client = Client()
    manager = _user(User.Role.MANAGER, "replay")
    result = {"total_from_hubspot": 0, "created": 0, "skipped": 0, "already_assigned": 0}

    with patch("apps.support.auto_assign_service.sync_novo_stage_tickets", return_value=result) as sync:
        first = client.post(
            "/api/v1/support/queue/sync-novo/",
            **_headers(manager, key="sync-replay"),
        )
        second = client.post(
            "/api/v1/support/queue/sync-novo/",
            **_headers(manager, key="sync-replay"),
        )

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    sync.assert_called_once()
    assert AdministrativeActionAudit.objects.filter(idempotency_key="sync-replay").count() == 1


@pytest.mark.django_db
def test_special_schedule_write_contract_validation_audit_and_replay() -> None:
    client = Client()
    viewer = _user(User.Role.VIEWER, "schedule")
    manager = _user(User.Role.MANAGER, "schedule")
    payload = {
        "date": "2026-12-25",
        "schedule_type": "custom",
        "start_hour": 10,
        "end_hour": 14,
        "reason": "holiday coverage",
    }

    assert (
        client.post("/api/v1/support/special-schedules/", data=payload, content_type="application/json").status_code
        == 401
    )
    forbidden = client.post(
        "/api/v1/support/special-schedules/",
        data=payload,
        content_type="application/json",
        **_headers(viewer),
    )
    assert forbidden.status_code == 403

    invalid = client.post(
        "/api/v1/support/special-schedules/",
        data={**payload, "start_hour": 15, "end_hour": 10},
        content_type="application/json",
        **_headers(manager),
    )
    assert invalid.status_code == 422
    assert SpecialSchedule.objects.count() == 0

    first = client.post(
        "/api/v1/support/special-schedules/",
        data=payload,
        content_type="application/json",
        **_headers(manager, key="schedule-replay"),
    )
    second = client.post(
        "/api/v1/support/special-schedules/",
        data=payload,
        content_type="application/json",
        **_headers(manager, key="schedule-replay"),
    )
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert SpecialSchedule.objects.count() == 1
    assert AdministrativeActionAudit.objects.filter(idempotency_key="schedule-replay").count() == 1

    conflict = client.post(
        "/api/v1/support/special-schedules/",
        data={**payload, "reason": "different request"},
        content_type="application/json",
        **_headers(manager, key="schedule-replay"),
    )
    assert conflict.status_code == 409
    assert SpecialSchedule.objects.get(date=date(2026, 12, 25)).reason == "holiday coverage"


@pytest.mark.django_db
def test_special_schedule_delete_requires_manager_and_is_audited() -> None:
    client = Client()
    agent = _user(User.Role.AGENT, "delete")
    admin = _user(User.Role.ADMIN, "delete")
    schedule = SpecialSchedule.objects.create(date=date(2026, 12, 31), reason="year end")
    path = f"/api/v1/support/special-schedules/{schedule.pk}"

    assert client.delete(path).status_code == 401
    assert client.delete(path, **_headers(agent)).status_code == 403
    assert SpecialSchedule.objects.filter(pk=schedule.pk).exists()
    assert client.delete(path, **_headers(admin, key="schedule-delete")).status_code == 204
    assert not SpecialSchedule.objects.filter(pk=schedule.pk).exists()
    audit = AdministrativeActionAudit.objects.get(idempotency_key="schedule-delete")
    assert audit.actor_id == str(admin.pk)
    assert audit.actor_role == User.Role.ADMIN
    assert audit.target_id == str(schedule.pk)
    assert audit.correlation_id


@pytest.mark.django_db
def test_admin_reads_reject_viewer_and_never_serialize_pii() -> None:
    client = Client()
    viewer = _user(User.Role.VIEWER, "reads")
    agent = Agent.objects.create(
        name="Sensitive Agent",
        agent_email="sensitive@example.test",
        manager_email="manager@example.test",
        hubspot_owner_id=9001,
        status_enum=Agent.StatusEnum.ONLINE,
    )
    paths = (
        "/api/v1/support/agents/",
        f"/api/v1/support/agents/{agent.pk}",
        f"/api/v1/support/agents/{agent.pk}/metrics/",
        "/api/v1/support/metrics/agents/",
        "/api/v1/support/metrics/agents/summary/",
        f"/api/v1/support/agents/{agent.pk}/time-logs/",
        "/api/v1/support/time-logs/",
        "/api/v1/support/reassignments/",
        "/api/v1/support/reassignments/summary/",
    )

    for path in paths:
        response = client.get(path, **_headers(viewer))
        assert response.status_code == 403, (path, response.content)
        body = response.content.decode()
        assert "sensitive@example.test" not in body
        assert "manager@example.test" not in body
        assert "9001" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("role", [User.Role.MANAGER, User.Role.ADMIN])
def test_manager_and_admin_can_read_agent_contract(role: str) -> None:
    client = Client()
    user = _user(role, "agent-read")
    support_agent = Agent.objects.create(
        name="Visible Agent",
        agent_email="visible@example.test",
        manager_email="manager@example.test",
        hubspot_owner_id=9002,
        status_enum=Agent.StatusEnum.ONLINE,
    )

    response = client.get(f"/api/v1/support/agents/{support_agent.pk}", **_headers(user))
    assert response.status_code == 200, response.content
    assert response.json()["agent_email"] == "visible@example.test"


@pytest.mark.django_db
def test_user_detail_is_admin_only() -> None:
    client = Client()
    viewer = _user(User.Role.VIEWER, "user-detail")
    admin = _user(User.Role.ADMIN, "user-detail")

    forbidden = client.get(f"/api/v1/auth/{viewer.pk}", **_headers(viewer))
    assert forbidden.status_code == 403
    assert viewer.email not in forbidden.content.decode()

    allowed = client.get(f"/api/v1/auth/{viewer.pk}", **_headers(admin))
    assert allowed.status_code == 200
    assert allowed.json()["email"] == viewer.email


@pytest.mark.django_db
def test_audit_reservation_failure_prevents_the_administrative_write() -> None:
    operation = Mock(return_value=(204, None))
    request = SimpleNamespace(
        auth=SimpleNamespace(pk=7, role=User.Role.ADMIN),
        headers={},
        META={"X_REQUEST_ID": "audit-reservation-failure"},
    )

    with (
        patch.object(AdministrativeActionAudit.objects, "create", side_effect=RuntimeError("audit unavailable")),
        pytest.raises(RuntimeError, match="audit unavailable"),
    ):
        execute_audited_action(
            request,
            action="support.test.write",
            target_type="test",
            reason="test",
            fingerprint_payload={"value": 1},
            operation=operation,
        )

    operation.assert_not_called()


@pytest.mark.django_db
def test_failed_operation_is_audited_and_failed_key_cannot_be_replayed() -> None:
    request = SimpleNamespace(
        auth=SimpleNamespace(pk=8, role=User.Role.MANAGER),
        headers={"Idempotency-Key": "failed-operation"},
        META={"X_REQUEST_ID": "failed-operation-request"},
    )

    def fail() -> tuple[int, None]:
        raise RuntimeError("write failed")

    with pytest.raises(RuntimeError, match="write failed"):
        execute_audited_action(
            request,
            action="support.test.failure",
            target_type="test",
            target_id="target-1",
            reason="exercise failure audit",
            fingerprint_payload={"value": 1},
            operation=fail,
        )

    audit = AdministrativeActionAudit.objects.get(idempotency_key="failed-operation")
    assert audit.status == AdministrativeActionAudit.Status.FAILED
    assert audit.http_status == 500
    assert audit.error_code == "RuntimeError"

    with pytest.raises(ConflictError):
        execute_audited_action(
            request,
            action="support.test.failure",
            target_type="test",
            target_id="target-1",
            reason="exercise failure audit",
            fingerprint_payload={"value": 1},
            operation=lambda: (204, None),
        )


@pytest.mark.django_db
def test_invalid_idempotency_key_is_rejected_before_write() -> None:
    client = Client()
    manager = _user(User.Role.MANAGER, "invalid-key")
    response = client.post(
        "/api/v1/support/queue/sync-novo/",
        **_headers(manager, key="invalid key with spaces"),
    )
    assert response.status_code == 422
    assert AdministrativeActionAudit.objects.count() == 0

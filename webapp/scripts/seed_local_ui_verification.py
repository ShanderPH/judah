"""Create the deterministic, local-only browser verification fixture."""

from __future__ import annotations

import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.support.models import Agent, NewConversation
from common.database_safety import assert_safe_test_database

database_url = os.environ.get("DATABASE_URL", "")
assert_safe_test_database(database_url)

password = os.environ.get("JUDAH_UI_TEST_PASSWORD", "")
if not password:
    raise RuntimeError("JUDAH_UI_TEST_PASSWORD is required.")

user_model = get_user_model()
user, _ = user_model.objects.update_or_create(
    username="ui_verification_admin",
    defaults={
        "email": "ui-verification-admin@local.judah.test",
        "first_name": "UI Verification",
        "is_active": True,
        "is_staff": True,
        "role": "admin",
    },
)
user.set_password(password)
user.save(update_fields=["password"])

now = timezone.now()
agents = (
    (
        "ui-agent-online@local.judah.test",
        "UI Agent Online",
        990001,
        Agent.StatusEnum.ONLINE,
        Agent.EligibilityState.ELIGIBLE,
    ),
    (
        "ui-agent-away@local.judah.test",
        "UI Agent Away",
        990002,
        Agent.StatusEnum.AWAY,
        Agent.EligibilityState.INELIGIBLE,
    ),
)
for email, name, owner_id, status, eligibility in agents:
    Agent.objects.update_or_create(
        agent_email=email,
        defaults={
            "name": name,
            "hubspot_owner_id": owner_id,
            "status_enum": status,
            "current_simultaneous_chats": 1 if status == Agent.StatusEnum.ONLINE else 0,
            "max_simultaneous_chats": 5,
            "auto_assign_enabled": True,
            "is_active": True,
            "eligibility_state": eligibility,
            "eligibility_reason": "local_ui_fixture",
            "eligibility_evaluated_at": now,
            "availability_observed_at": now,
        },
    )

for index in range(1, 106):
    NewConversation.objects.update_or_create(
        hubspot_ticket_id=f"UI-VERIFY-{index:03d}",
        defaults={
            "contact_name": f"Cliente de Teste {index:03d}",
            "contact_email": f"cliente{index:03d}@local.judah.test",
            "priority": ("LOW", "MEDIUM", "HIGH")[index % 3],
            "subject": f"Fixture local de interface {index:03d}",
            "entered_queue_at": now - timedelta(minutes=106 - index),
            "queue_status": NewConversation.QueueStatus.QUEUED,
            "automatic_assignment_eligible": False,
        },
    )

print("local_ui_fixture_ready users=1 agents=2 queue=105")

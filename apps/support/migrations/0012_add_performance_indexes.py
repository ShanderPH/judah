"""Add indexes for high-frequency auto-assignment queries.

Targets:
  - Agent eligibility query (get_eligible_agents): status_enum + auto_assign_enabled
  - Agent lookup by hubspot_owner_id (owner change, reconciliation)
  - AssignmentLog Rule 2 query (get_last_assigned_owner_id): assignment_type + assigned_at DESC
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("support", "0011_disable_legacy_poll_task"),
    ]

    operations = [
        # Composite index for the eligibility query used by get_eligible_agents()
        # Called on every drain iteration and every assignment attempt.
        migrations.AddIndex(
            model_name="agent",
            index=models.Index(
                fields=["status_enum", "auto_assign_enabled"],
                name="idx_agent_eligible",
            ),
        ),
        # Index for owner-based lookups (owner change webhooks, reconciliation)
        migrations.AddIndex(
            model_name="agent",
            index=models.Index(
                fields=["hubspot_owner_id"],
                name="idx_agent_hubspot_owner",
            ),
        ),
        # Composite index for get_last_assigned_owner_id() — Rule 2 enforcement.
        # Covers the filter (assignment_type="automatic", hubspot_owner_id NOT NULL)
        # + ORDER BY assigned_at DESC.
        migrations.AddIndex(
            model_name="assignmentlog",
            index=models.Index(
                fields=["assignment_type", "-assigned_at"],
                name="idx_alog_type_assigned_desc",
            ),
        ),
    ]

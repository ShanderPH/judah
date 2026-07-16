# Generated manually for deterministic workflow alignment.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_agents", "0003_conversationinstance_agentrun_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentrun",
            name="model_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="policy_version",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="agentrun",
            name="prompt_version",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="conversationinstance",
            name="state",
            field=models.CharField(
                choices=[
                    ("RECEIVED", "Received"),
                    ("NORMALIZED", "Normalized"),
                    ("CONTEXT_HYDRATING", "Context Hydrating"),
                    ("CONTEXT_READY", "Context Ready"),
                    ("CONTACT_REQUIRED", "Contact Required"),
                    ("CONTACT_COLLECTING", "Contact Collecting"),
                    ("CONTACT_ASSOCIATING", "Contact Associating"),
                    ("TRIAGE_PENDING", "Triage Pending"),
                    ("TRIAGE_RUNNING", "Triage Running"),
                    ("AI_SERVICE_PENDING", "AI Service Pending"),
                    ("AI_SERVICE_RUNNING", "AI Service Running"),
                    ("WAITING_FOR_CUSTOMER", "Waiting for Customer"),
                    ("HUMAN_HANDOFF_REQUESTED", "Human Handoff Requested"),
                    ("QUEUE_PENDING", "Queue Pending"),
                    ("HUMAN_ASSIGNED", "Human Assigned"),
                    ("HUMAN_IN_PROGRESS", "Human In Progress"),
                    ("RESOLVED_BY_AI", "Resolved by AI"),
                    ("RESOLVED_BY_HUMAN", "Resolved by Human"),
                    ("CLOSED", "Closed"),
                    ("FAILED_RETRYABLE", "Failed Retryable"),
                    ("FAILED_TERMINAL", "Failed Terminal"),
                    ("IGNORED", "Ignored"),
                ],
                db_index=True,
                default="RECEIVED",
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="conversationstatetransition",
            name="to_state",
            field=models.CharField(
                choices=[
                    ("RECEIVED", "Received"),
                    ("NORMALIZED", "Normalized"),
                    ("CONTEXT_HYDRATING", "Context Hydrating"),
                    ("CONTEXT_READY", "Context Ready"),
                    ("CONTACT_REQUIRED", "Contact Required"),
                    ("CONTACT_COLLECTING", "Contact Collecting"),
                    ("CONTACT_ASSOCIATING", "Contact Associating"),
                    ("TRIAGE_PENDING", "Triage Pending"),
                    ("TRIAGE_RUNNING", "Triage Running"),
                    ("AI_SERVICE_PENDING", "AI Service Pending"),
                    ("AI_SERVICE_RUNNING", "AI Service Running"),
                    ("WAITING_FOR_CUSTOMER", "Waiting for Customer"),
                    ("HUMAN_HANDOFF_REQUESTED", "Human Handoff Requested"),
                    ("QUEUE_PENDING", "Queue Pending"),
                    ("HUMAN_ASSIGNED", "Human Assigned"),
                    ("HUMAN_IN_PROGRESS", "Human In Progress"),
                    ("RESOLVED_BY_AI", "Resolved by AI"),
                    ("RESOLVED_BY_HUMAN", "Resolved by Human"),
                    ("CLOSED", "Closed"),
                    ("FAILED_RETRYABLE", "Failed Retryable"),
                    ("FAILED_TERMINAL", "Failed Terminal"),
                    ("IGNORED", "Ignored"),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]

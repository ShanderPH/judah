from django.conf import settings
from django.test import Client


def test_legacy_ai_endpoints_are_not_registered() -> None:
    client = Client()

    assert client.post("/api/v1/ai/triage/", data={}, content_type="application/json").status_code == 404
    assert client.post("/api/v1/ai/salomao/chat", data={}, content_type="application/json").status_code == 404
    assert client.post("/api/v1/ai/webhooks/hubspot/ticket-change", data={}).status_code == 404


def test_legacy_tasks_and_schedule_are_absent() -> None:
    from apps.ai_agents import tasks

    assert "ai-lifecycle-retry-dispatch" not in settings.CELERY_BEAT_SCHEDULE
    assert not hasattr(tasks, "retry_failed_lifecycle_instances_task")
    assert not hasattr(tasks, "run_supervisor_pipeline_task")
    assert not hasattr(tasks, "run_salomao_v1_thread_pipeline_task")


def test_legacy_runtime_flags_are_absent() -> None:
    assert not hasattr(settings, "AI_ROUTING_ENABLED")
    assert not hasattr(settings, "SALOMAO_SUPERVISOR_ENABLED")
    assert not hasattr(settings, "HUBSPOT_AI_TRIAGE_PIPELINE_ID")
    assert not hasattr(settings, "HEIMDALL_MIN_CONFIDENCE")

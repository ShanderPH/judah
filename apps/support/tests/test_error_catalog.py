"""Tests for the operator-facing support error catalog."""

from apps.support.error_catalog import cataloged_error_context


def test_cataloged_error_context_returns_stable_operator_fields() -> None:
    context = cataloged_error_context("legacy_cycle_ambiguous")

    assert context["error_catalog_code"] == "SUP-QUEUE-001"
    assert context["failure_code"] == "legacy_cycle_ambiguous"
    assert context["message_error"].startswith("Erro catalogado [SUP-QUEUE-001]:")
    assert context["error_category"] == "queue_integrity"
    assert context["retryable"] is False
    assert "quarentena" in str(context["action_taken"])
    assert context["operator_hint"]


def test_catalog_resolves_dynamic_provider_failures_and_overrides() -> None:
    context = cataloged_error_context(
        "hubspot_http_503",
        retryable=False,
        action_taken="A execução foi interrompida pelo operador.",
    )

    assert context["error_catalog_code"] == "SUP-HUBSPOT-003"
    assert context["failure_code"] == "hubspot_http_503"
    assert context["retryable"] is False
    assert context["action_taken"] == "A execução foi interrompida pelo operador."


def test_unknown_error_is_still_cataloged_without_raw_payload() -> None:
    context = cataloged_error_context("database_driver_surprise")

    assert context["error_catalog_code"] == "SUP-UNKNOWN-001"
    assert context["failure_code"] == "database_driver_surprise"
    assert "não classificada" in str(context["message_error"])

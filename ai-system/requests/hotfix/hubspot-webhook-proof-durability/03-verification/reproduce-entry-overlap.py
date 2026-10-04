"""Explicit replay of the concurrency regression now included in the test suite."""

from pytest_django.fixtures import Settings

from apps.support.tests.test_lifecycle_entry_recovery import (
    test_terminal_entry_is_not_projected_by_an_earlier_execution as verify_terminal_entry,
)


def test_terminal_entry_is_not_projected_by_an_earlier_execution(settings: Settings) -> None:
    """Revalidate the repaired interleaving through its permanent regression."""
    verify_terminal_entry(settings)

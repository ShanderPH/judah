"""Tests for the role-to-capability contract."""

from apps.auth_user.capabilities import Capability, capabilities_for_role


def test_viewer_and_agent_receive_only_baseline_access() -> None:
    assert capabilities_for_role("viewer") == [Capability.DASHBOARD_READ]
    assert capabilities_for_role("agent") == [Capability.DASHBOARD_READ]


def test_manager_receives_operations_without_sandbox() -> None:
    capabilities = capabilities_for_role("manager")
    assert Capability.AGENTS_MANAGE in capabilities
    assert Capability.SANDBOX_USE not in capabilities


def test_admin_receives_sandbox_capability() -> None:
    assert Capability.SANDBOX_USE in capabilities_for_role("admin")

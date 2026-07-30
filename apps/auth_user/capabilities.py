"""Role-to-capability policy exposed to authenticated Judah clients."""

from __future__ import annotations

from enum import StrEnum


class Capability(StrEnum):
    """Stable authorization capabilities understood by the webapp."""

    DASHBOARD_READ = "dashboard.read"
    SUPPORT_ADMIN_READ = "support.admin.read"
    AGENTS_MANAGE = "agents.manage"
    ASSIGNMENTS_MANAGE = "assignments.manage"
    QUEUE_SYNC = "queue.sync"
    METRICS_READ = "metrics.read"
    SANDBOX_USE = "sandbox.use"


_BASE_CAPABILITIES = (Capability.DASHBOARD_READ,)
_MANAGEMENT_CAPABILITIES = (
    Capability.SUPPORT_ADMIN_READ,
    Capability.AGENTS_MANAGE,
    Capability.ASSIGNMENTS_MANAGE,
    Capability.QUEUE_SYNC,
    Capability.METRICS_READ,
)


def capabilities_for_role(role: str) -> list[str]:
    """Return the conservative, ordered capability set for a user role."""
    capabilities = list(_BASE_CAPABILITIES)
    if role in {"admin", "manager"}:
        capabilities.extend(_MANAGEMENT_CAPABILITIES)
    if role == "admin":
        capabilities.append(Capability.SANDBOX_USE)
    return [str(capability) for capability in capabilities]

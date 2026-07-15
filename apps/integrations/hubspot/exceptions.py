"""Typed exceptions for HubSpot integration failures."""

from common.exceptions import ExternalServiceError


class HubSpotAPIError(ExternalServiceError):
    """HubSpot API failure with preserved HTTP and retry metadata."""

    def __init__(
        self,
        message: str,
        *,
        external_status: int | None = None,
        retryable: bool = True,
    ) -> None:
        self.external_status = external_status
        self.retryable = retryable
        super().__init__("HubSpot", message)


class HubSpotResourceNotFoundError(HubSpotAPIError):
    """Requested HubSpot CRM record no longer exists in the active portal."""

    def __init__(self, resource_type: str, resource_id: str) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(
            f"HubSpot {resource_type} {resource_id} was not found.",
            external_status=404,
            retryable=False,
        )

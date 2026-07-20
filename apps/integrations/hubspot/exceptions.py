"""Typed exceptions for HubSpot integration failures."""

from enum import StrEnum

from common.exceptions import ExternalServiceError


class HubSpotFailureKind(StrEnum):
    """Stable provider failure classifications for routing decisions."""

    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    MALFORMED_RESPONSE = "malformed_response"
    UNKNOWN = "unknown"


class HubSpotAPIError(ExternalServiceError):
    """HubSpot API failure with preserved HTTP and retry metadata."""

    def __init__(
        self,
        message: str,
        *,
        external_status: int | None = None,
        retryable: bool = True,
        error_code: str = HubSpotFailureKind.UNKNOWN,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.external_status = external_status
        self.retryable = retryable
        self.error_code = error_code
        self.retry_after_seconds = retry_after_seconds
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
            error_code=HubSpotFailureKind.NOT_FOUND,
        )

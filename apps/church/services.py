"""Business logic for church app."""

import structlog

from apps.church.models import Church
from common.exceptions import NotFoundError

logger = structlog.get_logger(__name__)


def get_church_by_external_id(external_id: str) -> Church:
    """Fetch a church by its external InChurch ID.

    Raises:
        NotFoundError: If no church with that external_id exists.
    """
    try:
        return Church.objects.select_related("plan", "gateway").get(external_id=external_id)
    except Church.DoesNotExist as err:
        raise NotFoundError(f"Church with external_id={external_id} not found.") from err


def get_church_by_id(church_id: int) -> Church:
    """Fetch a church by primary key.

    Raises:
        NotFoundError: If no church with that id exists.
    """
    try:
        return Church.objects.select_related("plan", "gateway").get(pk=church_id)
    except Church.DoesNotExist as err:
        raise NotFoundError(f"Church with id={church_id} not found.") from err


def list_active_churches() -> list[Church]:
    """Return all active churches ordered by name."""
    return list(Church.objects.filter(is_active=True).order_by("name"))

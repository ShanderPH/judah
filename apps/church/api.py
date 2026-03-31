"""Django Ninja API endpoints for church."""

from typing import TYPE_CHECKING

from ninja import Router

from apps.church.schemas import ChurchListResponse, ChurchResponse
from apps.church.services import get_church_by_id, list_active_churches
from common.pagination import StandardPagination, paginate

if TYPE_CHECKING:
    from apps.church.models import Church

router = Router()


@router.get("/", response=list[ChurchListResponse], summary="List active churches")
@paginate(StandardPagination)
def list_churches(request) -> list[Church]:
    """Return a paginated list of all active churches."""
    return list_active_churches()


@router.get("/{church_id}", response=ChurchResponse, summary="Get church by ID")
def get_church(request, church_id: int) -> Church:
    """Return details for a single church."""
    return get_church_by_id(church_id)

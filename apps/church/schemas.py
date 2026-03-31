"""Pydantic v2 schemas for church endpoints."""

from ninja import Schema


class PlanSchema(Schema):
    """Public plan representation."""

    id: int
    name: str
    slug: str
    max_members: int
    is_active: bool

    class Config:
        from_attributes = True


class ChurchResponse(Schema):
    """Public church representation."""

    id: int
    external_id: str
    name: str
    email: str
    phone: str
    city: str
    state: str
    country: str
    is_active: bool
    hubspot_company_id: str

    class Config:
        from_attributes = True


class ChurchListResponse(Schema):
    """Minimal church representation for list endpoints."""

    id: int
    external_id: str
    name: str
    is_active: bool

    class Config:
        from_attributes = True

"""Pydantic schemas for HubSpot integration."""

from ninja import Schema


class HubSpotTicketSchema(Schema):
    """HubSpot ticket representation."""

    id: str
    subject: str
    priority: str
    stage: str
    owner_id: str


class HubSpotContactSchema(Schema):
    """HubSpot contact representation."""

    id: str
    firstname: str
    lastname: str
    company: str
    lifecycle_stage: str

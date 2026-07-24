"""Tests for church lookup services."""

import pytest

from apps.church.models import Church, Gateway, Plan
from apps.church.services import get_church_by_external_id, get_church_by_id, list_active_churches
from common.exceptions import NotFoundError


@pytest.mark.django_db
def test_church_lookups_and_active_listing() -> None:
    plan = Plan.objects.create(name="Pro", slug="pro")
    gateway = Gateway.objects.create(name="Pagar", slug="pagar")
    beta = Church.objects.create(external_id="2", name="Beta", plan=plan, gateway=gateway)
    alpha = Church.objects.create(external_id="1", name="Alpha")
    Church.objects.create(external_id="3", name="Inactive", is_active=False)

    assert get_church_by_external_id("2") == beta
    assert get_church_by_id(alpha.pk) == alpha
    assert list_active_churches() == [alpha, beta]


@pytest.mark.django_db
def test_church_lookups_raise_domain_not_found() -> None:
    with pytest.raises(NotFoundError):
        get_church_by_external_id("missing")
    with pytest.raises(NotFoundError):
        get_church_by_id(999)

"""Tests for common.permissions — role decorator and the HttpBearer wrapper."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from common.exceptions import ForbiddenError, UnauthorizedError
from common.permissions import (
    IsAuthenticated,
    require_admin,
    require_agent_or_above,
    require_manager_or_admin,
    require_role,
)

if TYPE_CHECKING:

    class MissingReturnType:
        """Return-only annotation intentionally unavailable at runtime."""


def _make_request(user: object | None) -> SimpleNamespace:
    return SimpleNamespace(auth=user)


class TestRequireRole:
    def test_resolves_postponed_parameter_annotations(self) -> None:
        @require_role("admin")
        def endpoint(request: object, item_id: int) -> MissingReturnType:
            raise NotImplementedError

        endpoint_signature = inspect.signature(endpoint)

        assert endpoint_signature.parameters["request"].annotation is object
        assert endpoint_signature.parameters["item_id"].annotation is int
        assert endpoint_signature.return_annotation is inspect.Signature.empty

    def test_raises_unauthorized_when_no_user(self) -> None:
        @require_role("admin")
        def endpoint(request):
            return "ok"

        with pytest.raises(UnauthorizedError):
            endpoint(_make_request(None))

    def test_raises_forbidden_for_wrong_role(self) -> None:
        @require_role("admin")
        def endpoint(request):
            return "ok"

        user = SimpleNamespace(role="member")
        with pytest.raises(ForbiddenError):
            endpoint(_make_request(user))

    def test_allows_matching_role(self) -> None:
        @require_role("admin", "manager")
        def endpoint(request):
            return "ok"

        user = SimpleNamespace(role="manager")
        assert endpoint(_make_request(user)) == "ok"

    def test_rejects_user_without_role_attribute(self) -> None:
        @require_role("admin")
        def endpoint(request):
            return "ok"

        service = object()
        with pytest.raises(ForbiddenError):
            endpoint(_make_request(service))


class TestRoleShortcuts:
    def test_require_admin_allows_admin(self) -> None:
        @require_admin
        def endpoint(request):
            return "ok"

        assert endpoint(_make_request(SimpleNamespace(role="admin"))) == "ok"

    def test_require_admin_rejects_non_admin(self) -> None:
        @require_admin
        def endpoint(request):
            return "ok"

        with pytest.raises(ForbiddenError):
            endpoint(_make_request(SimpleNamespace(role="agent")))

    def test_require_manager_or_admin_allows_manager(self) -> None:
        @require_manager_or_admin
        def endpoint(request):
            return "ok"

        assert endpoint(_make_request(SimpleNamespace(role="manager"))) == "ok"

    def test_require_manager_or_admin_rejects_agent(self) -> None:
        @require_manager_or_admin
        def endpoint(request):
            return "ok"

        with pytest.raises(ForbiddenError):
            endpoint(_make_request(SimpleNamespace(role="agent")))

    def test_require_agent_or_above_allows_agent(self) -> None:
        @require_agent_or_above
        def endpoint(request):
            return "ok"

        assert endpoint(_make_request(SimpleNamespace(role="agent"))) == "ok"

    def test_require_agent_or_above_rejects_member(self) -> None:
        @require_agent_or_above
        def endpoint(request):
            return "ok"

        with pytest.raises(ForbiddenError):
            endpoint(_make_request(SimpleNamespace(role="member")))


class TestIsAuthenticated:
    def test_can_be_instantiated(self) -> None:
        auth = IsAuthenticated()
        assert auth is not None
        # HttpBearer subclasses expose an ``authenticate`` method.
        assert callable(auth.authenticate)

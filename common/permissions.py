"""Custom permission classes for JUDAH."""

import functools
import inspect
from typing import Any

from ninja.security import HttpBearer

from common.exceptions import ForbiddenError, UnauthorizedError


def _endpoint_signature(func: Any) -> inspect.Signature:
    """Resolve runtime parameter schemas without evaluating return-only types."""
    signature = inspect.signature(func, eval_str=False)
    parameters = []
    for parameter in signature.parameters.values():
        annotation = parameter.annotation
        if isinstance(annotation, str):
            annotation = eval(annotation, func.__globals__)
        parameters.append(parameter.replace(annotation=annotation))
    return signature.replace(
        parameters=parameters,
        return_annotation=inspect.Signature.empty,
    )


class IsAuthenticated(HttpBearer):
    """Require a valid JWT token."""

    def authenticate(self, request: Any, token: str) -> Any | None:
        from ninja_jwt.authentication import JWTAuth

        auth = JWTAuth()
        return auth.authenticate(request, token)


def require_role(*roles: str):
    """Decorator factory that restricts access to users with given roles."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kwargs):
            user = getattr(request, "auth", None)
            if user is None:
                raise UnauthorizedError()
            if getattr(user, "role", None) not in roles:
                raise ForbiddenError(f"This action requires one of the following roles: {', '.join(roles)}.")
            return func(request, *args, **kwargs)

        # Django Ninja inspects the decorated callable. Resolve annotations in
        # the endpoint module before returning a wrapper whose globals belong
        # to this permissions module.
        wrapper.__signature__ = _endpoint_signature(func)
        return wrapper

    return decorator


def require_admin(func):
    """Shortcut: restrict endpoint to admin role only."""
    return require_role("admin")(func)


def require_manager_or_admin(func):
    """Shortcut: restrict endpoint to manager or admin roles."""
    return require_role("admin", "manager")(func)


def require_agent_or_above(func):
    """Shortcut: restrict endpoint to agent, manager, or admin roles."""
    return require_role("admin", "manager", "agent")(func)

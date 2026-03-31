"""Custom permission classes for JUDAH."""

from typing import Any

from ninja.security import HttpBearer

from common.exceptions import ForbiddenError, UnauthorizedError


class IsAuthenticated(HttpBearer):
    """Require a valid JWT token."""

    def authenticate(self, request: Any, token: str) -> Any | None:
        from ninja_jwt.authentication import JWTAuth

        auth = JWTAuth()
        return auth.authenticate(request, token)


def require_role(*roles: str):
    """Decorator factory that restricts access to users with given roles."""

    def decorator(func):
        import functools

        @functools.wraps(func)
        def wrapper(request, *args, **kwargs):
            user = getattr(request, "auth", None)
            if user is None:
                raise UnauthorizedError()
            if hasattr(user, "role") and user.role not in roles:
                raise ForbiddenError(
                    f"This action requires one of the following roles: {', '.join(roles)}."
                )
            return func(request, *args, **kwargs)

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

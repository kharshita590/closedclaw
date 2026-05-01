from __future__ import annotations

import inspect
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable

TOOL_SCOPES = {
    "list_emails": "email:read",
    "get_message": "email:read",
    "send_email": "email:send",
    "delete_message": "email:delete",
    "clear_spam": "email:delete",
    "upcoming_events": "calendar:read",
    "create_event": "calendar:write",
    "reschedule_event": "calendar:write",
    "find_free_slots": "calendar:read",
    "browser_navigate": "browser:navigate",
}

DEFAULT_SCOPES = {"email:read", "calendar:read", "browser:navigate"}
_current_scopes: ContextVar[set[str]] = ContextVar("current_scopes", default=set(DEFAULT_SCOPES))


class PermissionDenied(RuntimeError):
    """Raised when a tool function is called without the required permission scope."""


def set_current_scopes(scopes: set[str]):
    """Sets scopes for the current execution context and returns a reset token."""

    return _current_scopes.set(scopes)


def reset_current_scopes(token: Any) -> None:
    """Restores the previous scope set after a scoped execution block."""

    _current_scopes.reset(token)


def require_scope(scope: str) -> Callable:
    """Decorator that blocks tool calls unless the current execution has a scope."""

    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if scope not in _current_scopes.get():
                    raise PermissionDenied(f"Missing required scope: {scope}")
                return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if scope not in _current_scopes.get():
                raise PermissionDenied(f"Missing required scope: {scope}")
            return func(*args, **kwargs)

        return wrapper

    return decorator

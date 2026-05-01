from __future__ import annotations

from typing import Any

from actions.models import (
    AgentAction,
    BrowserNavigateAction,
    ClearSpamAction,
    CreateCalendarEventAction,
    DeleteEmailAction,
    SendEmailAction,
)
from permissions.registry import reset_current_scopes, set_current_scopes
from policy.policy_engine import PolicyEngine, PolicyResult
from tools.browser_client import BrowserClient
from tools.calendar_tools import CalendarTools
from tools.email_tools import EmailTools

ACTION_SCOPES = {
    "email.send": {"email:send"},
    "email.delete": {"email:delete"},
    "email.clear_spam": {"email:delete"},
    "calendar.create_event": {"calendar:write"},
    "browser.navigate": {"browser:navigate"},
}


class ActionExecutor:
    """Executes approved typed action plans through scoped tool wrappers."""

    def __init__(
        self,
        policy_engine: PolicyEngine,
        email_tools: EmailTools | None = None,
        calendar_tools: CalendarTools | None = None,
        browser_client: BrowserClient | None = None,
    ) -> None:
        """Creates an executor with injectable tool clients for tests."""

        self.policy_engine = policy_engine
        self.email = email_tools or EmailTools()
        self.calendar = calendar_tools or CalendarTools()
        self.browser = browser_client or BrowserClient()

    async def execute_approved(self, action: AgentAction) -> dict[str, Any]:
        """Runs policy checks and executes an action with only its approved scopes."""

        policy = self.policy_engine.check(action)
        if not policy.allowed:
            return {"ok": False, "policy_allowed": False, "reason": policy.reason}
        scopes = ACTION_SCOPES.get(action.action_type, set())
        token = set_current_scopes(scopes)
        try:
            result = await self._execute(action)
            return {"ok": True, "policy_allowed": True, "result": result}
        except Exception as exc:
            return {"ok": False, "policy_allowed": True, "error": str(exc)}
        finally:
            reset_current_scopes(token)

    async def _execute(self, action: AgentAction) -> Any:
        """Dispatches one validated action to its concrete tool implementation."""

        if isinstance(action, SendEmailAction):
            return self.email.send_email(str(action.recipient), action.subject, action.body, action.thread_id)
        if isinstance(action, DeleteEmailAction):
            self.email.delete_message(action.message_id)
            return {"deleted": action.message_id}
        if isinstance(action, ClearSpamAction):
            return {"deleted_count": self.email.clear_spam(action.limit)}
        if isinstance(action, CreateCalendarEventAction):
            return self.calendar.create_event(
                action.summary,
                action.start.isoformat(),
                action.end.isoformat(),
                [str(attendee) for attendee in action.attendees],
                action.description,
                action.timezone_name,
            )
        if isinstance(action, BrowserNavigateAction):
            return await self.browser.run(goal=action.goal, start_url=action.url)
        raise ValueError(f"No executor registered for {action.action_type}")

from __future__ import annotations

from typing import Type

from actions.models import (
    AgentAction,
    BrowserFormSubmitAction,
    BrowserNavigateAction,
    ClearSpamAction,
    CreateCalendarEventAction,
    DeleteEmailAction,
    SendEmailAction,
)


ACTION_MODEL_BY_TYPE: dict[str, Type[AgentAction]] = {
    "email.send": SendEmailAction,
    "email.delete": DeleteEmailAction,
    "email.clear_spam": ClearSpamAction,
    "calendar.create_event": CreateCalendarEventAction,
    "browser.navigate": BrowserNavigateAction,
    "browser.form_submit": BrowserFormSubmitAction,
}

ACTION_CLASS_BY_NAME: dict[str, Type[AgentAction]] = {cls.__name__: cls for cls in ACTION_MODEL_BY_TYPE.values()}


def action_model_by_type(action_type: str) -> Type[AgentAction] | None:
    return ACTION_MODEL_BY_TYPE.get(action_type)


def action_class_by_name(class_name: str) -> Type[AgentAction] | None:
    return ACTION_CLASS_BY_NAME.get(class_name)


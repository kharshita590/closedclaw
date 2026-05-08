"""Typed action plan models for approval and policy enforcement."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class AgentAction(BaseModel):
    """Base class for typed actions that may be approved and executed."""

    action_type: str

    def to_human_readable(self) -> str:
        """Returns a concise summary suitable for approvals and audit logs."""

        return self.action_type


class SendEmailAction(AgentAction):
    """Represents a request to send an email after approval."""

    action_type: Literal["email.send"] = "email.send"
    recipient: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10000)
    thread_id: str | None = None

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, recipient: str) -> str:
        """Rejects empty or malformed email recipient addresses."""

        if "@" not in recipient or recipient.startswith("@") or recipient.endswith("@"):
            raise ValueError("recipient must be an email address")
        return recipient

    def to_human_readable(self) -> str:
        return f"Send email to {self.recipient} with subject '{self.subject}'."


class DeleteEmailAction(AgentAction):
    """Represents a request to move one Gmail message to trash after approval."""

    action_type: Literal["email.delete"] = "email.delete"
    message_id: str = Field(min_length=1, max_length=300)

    def to_human_readable(self) -> str:
        return f"Delete email message {self.message_id}."


class ClearSpamAction(AgentAction):
    """Represents a bounded request to permanently clear spam messages."""

    action_type: Literal["email.clear_spam"] = "email.clear_spam"
    limit: int = Field(default=50, ge=1, le=100)

    def to_human_readable(self) -> str:
        return f"Clear up to {self.limit} spam messages."


class CreateCalendarEventAction(AgentAction):
    """Represents a request to create a Google Calendar event after approval."""

    action_type: Literal["calendar.create_event"] = "calendar.create_event"
    summary: str = Field(min_length=1, max_length=300)
    start: datetime
    end: datetime
    attendees: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(default="", max_length=5000)
    timezone_name: str = Field(default="Asia/Kolkata", max_length=100)

    @field_validator("end")
    @classmethod
    def end_after_start(cls, end: datetime, info: Any) -> datetime:
        """Rejects calendar events whose end time is not after start time."""

        start = info.data.get("start")
        if start and end <= start:
            raise ValueError("event end must be after start")
        return end

    @field_validator("attendees")
    @classmethod
    def validate_attendees(cls, attendees: list[str]) -> list[str]:
        """Rejects malformed attendee email addresses."""

        for attendee in attendees:
            if "@" not in attendee or attendee.startswith("@") or attendee.endswith("@"):
                raise ValueError("attendees must be email addresses")
        return attendees

    def to_human_readable(self) -> str:
        return f"Create calendar event '{self.summary}' from {self.start.isoformat()} to {self.end.isoformat()}."


class BrowserNavigateAction(AgentAction):
    """Represents a browser navigation/research action."""

    action_type: Literal["browser.navigate"] = "browser.navigate"
    url: str | None = None
    goal: str = Field(min_length=1, max_length=2000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, url: str | None) -> str | None:
        """Rejects browser URLs that are not absolute HTTP(S) URLs."""

        if not url:
            return url
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an http(s) URL")
        return url

    def to_human_readable(self) -> str:
        return f"Use browser for: {self.goal}"


class BrowserFormSubmitAction(AgentAction):
    """Represents a browser form fill-and-submit action after approval."""

    action_type: Literal["browser.form_submit"] = "browser.form_submit"
    url: str = Field(min_length=1, max_length=2000)
    fields: dict[str, str] = Field(default_factory=dict, max_length=50)
    discover_fields: bool = True
    discovered_fields: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    submit: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, url: str) -> str:
        """Rejects form URLs that are not absolute HTTP(S) URLs."""

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an http(s) URL")
        return url

    def to_human_readable(self) -> str:
        return f"Fill and submit form at {self.url} with {len(self.fields)} fields."


ActionUnion = Annotated[
    Union[SendEmailAction, DeleteEmailAction, ClearSpamAction, CreateCalendarEventAction, BrowserNavigateAction, BrowserFormSubmitAction],
    Field(discriminator="action_type"),
]


def action_from_payload(payload: dict[str, Any]) -> ActionUnion:
    """Rehydrates a typed action from ledger JSON."""

    action_type = payload.get("action_type")
    from actions.registry import action_model_by_type

    model = action_model_by_type(str(action_type))
    if not model:
        raise ValueError(f"Unknown action_type: {action_type}")
    return model.model_validate(payload)

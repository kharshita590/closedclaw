from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    channel: str = "ui"
    user_id: str = "local-user"
    thread_id: str | None = None
    group_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PendingAction(BaseModel):
    id: str
    action_type: str
    summary: str
    payload: dict[str, Any]
    channel: str
    user_id: str
    status: Literal["pending", "approved", "rejected"] = "pending"


class ChatResponse(BaseModel):
    response: str
    actions: list[PendingAction] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)

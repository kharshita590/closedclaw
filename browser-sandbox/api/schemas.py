from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BrowserStep(BaseModel):
    action: Literal["goto", "click", "fill", "press", "wait", "extract"]
    selector: str | None = None
    value: str | None = None
    url: str | None = None
    timeout_ms: int = 5000


class BrowserRunRequest(BaseModel):
    goal: str
    start_url: str | None = None
    steps: list[BrowserStep] = Field(default_factory=list)


class BrowserRunResponse(BaseModel):
    summary: str
    url: str | None = None
    title: str | None = None
    text: str = ""
    screenshot: str | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)


class BrowserFormSubmitRequest(BaseModel):
    url: str
    fields: dict[str, str] = Field(default_factory=dict)
    submit: bool = True


class FormField(BaseModel):
    label: str
    input_type: str
    required: bool = False


class FormFieldsResponse(BaseModel):
    url: str
    fields: list[FormField] = Field(default_factory=list)

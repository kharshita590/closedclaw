"""Typed execution plan models for the supervisor's bounded agentic loop."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

PlanIntent = str


class ExecutionStep(BaseModel):
    """Represents one bounded tool-capability step in a supervisor execution plan."""

    step_id: int = Field(description="Position in the plan, starting from 1.")
    intent: PlanIntent = Field(description="Allowed router intent that determines which typed handler executes this step.")
    description: str = Field(description="One-sentence plain English description of what this step should do.")
    depends_on_step: int | None = Field(
        default=None,
        description="Prior step id whose successful structured result should be added to this step's context.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Planner-extracted parameter hints for this step; handlers may override them with richer context.",
    )


class ExecutionPlan(BaseModel):
    """Ordered bounded plan for one user message, stored for audit and loop execution."""

    steps: list[ExecutionStep] = Field(description="Ordered list of execution steps; at most five steps are allowed.")
    raw_message: str = Field(description="Original user message retained for auditability and extraction prompts.")

    @field_validator("steps")
    @classmethod
    def enforce_max_steps(cls, steps: list[ExecutionStep]) -> list[ExecutionStep]:
        """Reject execution plans that exceed the configured bounded loop length."""

        hard_limit = int(os.getenv("PLAN_STEP_HARD_LIMIT", os.getenv("EXECUTION_LOOP_MAX_STEPS", "8")))
        hard_limit = min(max(hard_limit, 1), 12)
        if len(steps) > hard_limit:
            raise ValueError(f"Execution plans may include at most {hard_limit} steps.")
        return steps

    @property
    def is_multi_step(self) -> bool:
        """Return True when this plan contains more than one executable step."""

        return len(self.steps) > 1


class StepResult(BaseModel):
    """Structured outcome from one execution-loop step."""

    step_id: int = Field(description="Plan step id that produced this result.")
    intent: str = Field(description="Intent that was executed for this step.")
    ok: bool = Field(description="Whether the step completed without an exception or dependency failure.")
    data: dict[str, Any] = Field(default_factory=dict, description="Structured tool data returned by the step.")
    response_text: str = Field(description="Human-readable response text produced by the step.")
    error: str | None = Field(default=None, description="Error message when ok is False.")
    actions: list[Any] = Field(default_factory=list, description="Approval actions created by this step, if any.")
    suggested_followup: str | None = Field(default=None, description="Optional suggestion for a next user-visible action.")

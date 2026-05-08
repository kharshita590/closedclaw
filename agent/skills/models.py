from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    action_type: str  # TypedAction class name
    risk_level: RiskLevel
    allowed_tools: list[str]
    path: str
    enabled: bool = True


from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from actions.models import AgentAction
from actions.registry import action_class_by_name
from skills.models import RiskLevel, SkillDefinition
from skills.store import SkillStateStore


class SkillLoader:
    """Loads SKILL.md plugins from disk and merges them with DB enable state."""

    def __init__(self) -> None:
        self.skills_dir = Path(os.getenv("SKILLS_DIR", "~/.closedclaw/skills")).expanduser()
        self.allow_autonomous_low_risk = os.getenv("ALLOW_AUTONOMOUS_LOW_RISK_SKILLS", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.state = SkillStateStore()
        self._skills: dict[str, SkillDefinition] = {}
        self.errors: list[str] = []

    def load(self) -> dict[str, SkillDefinition]:
        self._skills = {}
        self.errors = []
        if not self.skills_dir.exists():
            return self._skills
        for skill_md in sorted(self.skills_dir.glob("*/SKILL.md")):
            try:
                skill = self._parse_skill_md(skill_md)
                if not skill:
                    continue
                enabled_override = self.state.get_enabled(skill.name)
                enabled = skill.enabled if enabled_override is None else bool(enabled_override)
                self._skills[skill.name] = SkillDefinition(**{**skill.__dict__, "enabled": enabled})
            except Exception as exc:
                self.errors.append(f"{skill_md}: {exc}")
                continue
        return self._skills

    def list(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def set_enabled(self, name: str, enabled: bool) -> None:
        self.state.set_enabled(name, enabled)
        if name in self._skills:
            skill = self._skills[name]
            self._skills[name] = SkillDefinition(**{**skill.__dict__, "enabled": enabled})

    def skill_intent_names(self) -> list[str]:
        return [self._intent_name(skill.name) for skill in self._skills.values() if skill.enabled]

    def intent_for_skill(self, skill_name: str) -> str:
        return self._intent_name(skill_name)

    def skill_for_intent(self, intent: str) -> SkillDefinition | None:
        if not intent.startswith("skill."):
            return None
        name = intent.removeprefix("skill.").strip()
        return self._skills.get(name)

    def action_model_for_skill(self, skill: SkillDefinition) -> type[AgentAction]:
        model = action_class_by_name(skill.action_type)
        if not model:
            raise ValueError(f"Skill action_type is not registered: {skill.action_type}")
        return model

    def _intent_name(self, name: str) -> str:
        return f"skill.{name}"

    def _parse_skill_md(self, path: Path) -> SkillDefinition | None:
        content = path.read_text(encoding="utf-8")
        front, _body = _split_frontmatter(content)
        if not front:
            return None
        meta = yaml.safe_load(front) if front else {}
        if not isinstance(meta, dict):
            raise ValueError(f"Invalid YAML front-matter in {path}")
        required = ["name", "description", "action_type", "risk_level", "allowed_tools"]
        missing = [k for k in required if k not in meta]
        if missing:
            raise ValueError(f"Missing fields in {path}: {missing}")
        name = str(meta["name"]).strip()
        description = str(meta["description"]).strip()
        action_type = str(meta["action_type"]).strip()
        risk_level: RiskLevel = str(meta["risk_level"]).strip().lower()  # type: ignore[assignment]
        allowed_tools_raw = meta["allowed_tools"]
        if not isinstance(allowed_tools_raw, list):
            raise ValueError(f"allowed_tools must be a list in {path}")
        allowed_tools = [str(x).strip() for x in allowed_tools_raw if str(x).strip()]
        if risk_level not in {"low", "medium", "high"}:
            raise ValueError(f"Invalid risk_level in {path}: {risk_level}")
        if not action_class_by_name(action_type):
            raise ValueError(f"Unknown action_type class in {path}: {action_type}")
        return SkillDefinition(
            name=name,
            description=description,
            action_type=action_type,
            risk_level=risk_level,
            allowed_tools=allowed_tools,
            path=str(path),
            enabled=True,
        )


def _split_frontmatter(content: str) -> tuple[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", content
    out: list[str] = []
    i = 1
    while i < len(lines):
        if lines[i].strip() == "---":
            return "\n".join(out).strip(), "\n".join(lines[i + 1 :]).lstrip()
        out.append(lines[i])
        i += 1
    return "", content


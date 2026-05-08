from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from skills.loader import SkillLoader  # noqa: E402


def write_skill(tmp: Path, name: str, body: str) -> None:
    skill_dir = tmp / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


def test_skill_loader_parses_valid_skill(monkeypatch, tmp_path: Path) -> None:
    write_skill(
        tmp_path,
        "hello",
        """---
name: hello
description: Say hello using browser navigate (read-only).
action_type: BrowserNavigateAction
risk_level: low
allowed_tools: ["browser:navigate"]
---
Do a thing.
""",
    )
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path))
    loader = SkillLoader()
    skills = loader.load()
    assert "hello" in skills
    assert skills["hello"].risk_level == "low"
    assert skills["hello"].enabled is True


def test_skill_loader_rejects_invalid_frontmatter(monkeypatch, tmp_path: Path) -> None:
    write_skill(tmp_path, "bad", "not yaml at all")
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path))
    loader = SkillLoader()
    # No frontmatter means skill is ignored (not an error).
    assert loader.load() == {}


def test_skill_loader_rejects_unknown_action_type(monkeypatch, tmp_path: Path) -> None:
    write_skill(
        tmp_path,
        "bad2",
        """---
name: bad2
description: bad
action_type: NotARealAction
risk_level: low
allowed_tools: []
---
""",
    )
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path))
    loader = SkillLoader()
    assert loader.load() == {}
    assert loader.errors


def test_skill_state_toggle_persists(monkeypatch, tmp_path: Path, postgres_database) -> None:
    write_skill(
        tmp_path,
        "tog",
        """---
name: tog
description: toggle test
action_type: BrowserNavigateAction
risk_level: low
allowed_tools: ["browser:navigate"]
---
""",
    )
    monkeypatch.setenv("SKILLS_DIR", str(tmp_path))
    loader = SkillLoader()
    loader.load()
    assert loader.get("tog").enabled is True
    loader.set_enabled("tog", False)
    loader.load()
    assert loader.get("tog").enabled is False


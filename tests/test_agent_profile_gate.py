from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from graph.state import ChatRequest  # noqa: E402
from subgraphs.execution_plan import ExecutionPlan, ExecutionStep  # noqa: E402
from subgraphs.supervisor import SupervisorAgent  # noqa: E402


def test_allowed_intents_gate_blocks_disallowed() -> None:
    agent = SupervisorAgent.__new__(SupervisorAgent)
    agent.allowed_intents = ["latest_email"]
    agent.llm = type("FakeLLM", (), {"enabled": lambda self: False})()
    agent.audit = type("FakeAudit", (), {"event": lambda self, *a, **k: None})()
    plan = ExecutionPlan(
        raw_message="browse https://example.com",
        steps=[ExecutionStep(step_id=1, intent="browser", description="Browser", depends_on_step=None, params={})],
    )
    resp = __import__("asyncio").run(agent._execute_plan(ChatRequest(message=plan.raw_message, user_id="u1"), plan))
    assert "not allowed" in resp.response.lower()


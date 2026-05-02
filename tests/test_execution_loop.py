from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock

from actions.models import SendEmailAction
from graph.state import ChatRequest, PendingAction
from subgraphs.execution_plan import ExecutionPlan, ExecutionStep
from subgraphs.intent_router import RouteDecision
from subgraphs.supervisor import SupervisorAgent


class FakeAudit:
    def event(self, *args, **kwargs):
        pass

    def decision(self, *args, **kwargs):
        pass


class FakeRouter:
    def __init__(self, decision: RouteDecision) -> None:
        self.decision = decision

    async def route(self, message, context=None):
        return self.decision


class FakeLLM:
    def __init__(self, enabled: bool, payload: dict | None = None) -> None:
        self.provider = "fake"
        self.payload = payload or {}
        self.last_raw_response = ""
        self.extract_json = AsyncMock(return_value=self.payload)
        self._enabled = enabled

    def enabled(self) -> bool:
        return self._enabled


class FakeEmail:
    def __init__(self, latest: dict | None = None, fail_latest: bool = False, fail_summary: bool = False) -> None:
        self.latest = latest or {}
        self.fail_latest = fail_latest
        self.fail_summary = fail_summary

    async def get_latest_raw(self, sender=None):
        if self.fail_latest:
            raise RuntimeError("email unavailable")
        return self.latest

    async def summarize_inbox(self):
        if self.fail_summary:
            raise RuntimeError("Gmail is not connected")
        return "Inbox summary"


class FakeMemory:
    def __init__(self, contacts: dict | None = None) -> None:
        self.saved = []
        self._contacts = contacts or {}

    def remember(self, channel, user_id, kind, content, metadata=None):
        self.saved.append((channel, user_id, kind, content, metadata))
        return len(self.saved)

    def search(self, user_id, query):
        return [{"content": "memory result"}]

    def contacts(self):
        return self._contacts


@dataclass
class FakePolicyResult:
    allowed: bool = True
    reason: str = "allowed"


class FakePolicy:
    def check(self, action):
        return FakePolicyResult()


class FakeApprovals:
    def __init__(self) -> None:
        self.created = []

    def create(self, action, requested_by, status="pending", result=None):
        self.created.append(action)
        return PendingAction(
            id=str(len(self.created)),
            action_type=action.action_type,
            summary=action.to_human_readable(),
            payload=action.model_dump(mode="json"),
            channel="ledger",
            user_id=requested_by,
            status=status,
        )


def supervisor(
    *,
    llm: FakeLLM | None = None,
    router_decision: RouteDecision | None = None,
    email: FakeEmail | None = None,
    memory: FakeMemory | None = None,
) -> SupervisorAgent:
    agent = SupervisorAgent.__new__(SupervisorAgent)
    agent.audit = FakeAudit()
    agent.llm = llm or FakeLLM(False)
    agent.router = FakeRouter(router_decision or RouteDecision(domain="email", intent="latest_email", confidence=0.8))
    agent.email = email or FakeEmail()
    agent.memory = memory or FakeMemory()
    agent.policy = FakePolicy()
    agent.approvals = FakeApprovals()
    agent.calendar = None
    agent.research_agent = None
    return agent


def test_single_step_passthrough_does_not_call_llm_planner() -> None:
    agent = supervisor(
        llm=FakeLLM(True),
        router_decision=RouteDecision(domain="email", intent="latest_email", confidence=0.8),
    )

    plan = asyncio.run(agent._build_plan(ChatRequest(message="get my latest email")))

    assert isinstance(plan, ExecutionPlan)
    assert len(plan.steps) == 1
    assert plan.steps[0].intent == "latest_email"
    agent.llm.extract_json.assert_not_awaited()


def test_multi_step_plan_building() -> None:
    payload = {
        "steps": [
            {"step_id": 1, "intent": "latest_email", "description": "Get the latest email.", "depends_on_step": None, "params": {}},
            {"step_id": 2, "intent": "draft_email", "description": "Draft a reply.", "depends_on_step": 1, "params": {}},
        ]
    }
    agent = supervisor(llm=FakeLLM(True, payload))

    plan = asyncio.run(agent._build_plan(ChatRequest(message="get my latest email and reply saying I will be there.")))

    assert len(plan.steps) == 2
    assert plan.steps[0].intent == "latest_email"
    assert plan.steps[1].intent == "draft_email"
    assert plan.steps[1].depends_on_step == 1


def test_context_propagation_into_draft_email() -> None:
    email_data = {
        "from_address": "john@example.com",
        "thread_id": "abc123",
        "subject": "Meeting tomorrow",
        "body": "Can you attend?",
        "date": "today",
        "message_id": "msg1",
    }
    agent = supervisor(
        llm=FakeLLM(True, {"recipient": None, "subject": None, "body": "I will be there.", "thread_id": None}),
        email=FakeEmail(latest=email_data),
    )
    plan = ExecutionPlan(
        raw_message="get my latest email and reply saying I will be there.",
        steps=[
            ExecutionStep(step_id=1, intent="latest_email", description="Get latest email.", depends_on_step=None, params={}),
            ExecutionStep(step_id=2, intent="draft_email", description="Draft reply.", depends_on_step=1, params={}),
        ],
    )

    response = asyncio.run(agent._execute_plan(ChatRequest(message=plan.raw_message, user_id="u1"), plan))

    action = SendEmailAction.model_validate(response.actions[0].payload)
    assert action.recipient == "john@example.com"
    assert action.thread_id == "abc123"


def test_failed_step_does_not_abort_independent_later_step() -> None:
    memory = FakeMemory()
    agent = supervisor(email=FakeEmail(fail_latest=True), memory=memory)
    plan = ExecutionPlan(
        raw_message="get latest email and save a note",
        steps=[
            ExecutionStep(step_id=1, intent="latest_email", description="Get latest email.", depends_on_step=None, params={}),
            ExecutionStep(step_id=2, intent="remember", description="Save a note.", depends_on_step=None, params={"content": "note"}),
        ],
    )

    response = asyncio.run(agent._execute_plan(ChatRequest(message=plan.raw_message), plan))

    assert "Step 1 failed: email unavailable" in response.response
    assert "Saved memory #1." in response.response


def test_failed_dependency_skips_dependent_step() -> None:
    agent = supervisor(email=FakeEmail(fail_latest=True))
    plan = ExecutionPlan(
        raw_message="get latest email and reply",
        steps=[
            ExecutionStep(step_id=1, intent="latest_email", description="Get latest email.", depends_on_step=None, params={}),
            ExecutionStep(step_id=2, intent="draft_email", description="Draft reply.", depends_on_step=1, params={}),
        ],
    )

    response = asyncio.run(agent._execute_plan(ChatRequest(message=plan.raw_message), plan))

    assert "Step 2 skipped due to failed dependency step 1." in response.response
    assert not response.actions


def test_direct_named_recipient_draft_continues_after_failed_email_dependency() -> None:
    memory = FakeMemory(contacts={"harshita kumari": {"email": "harshita@example.com"}})
    agent = supervisor(
        llm=FakeLLM(True, {"recipient": "Harshita Kumari", "subject": "Assignment submission", "body": "Submit the assignment before 7 May.", "thread_id": None}),
        email=FakeEmail(fail_summary=True),
        memory=memory,
    )
    plan = ExecutionPlan(
        raw_message="summarize and reply harshita kumari to submit assignment before 7 may",
        steps=[
            ExecutionStep(step_id=1, intent="summarize_email", description="Summarize email.", depends_on_step=None, params={}),
            ExecutionStep(step_id=2, intent="draft_email", description="Draft reply.", depends_on_step=1, params={}),
        ],
    )

    response = asyncio.run(agent._execute_plan(ChatRequest(message=plan.raw_message, user_id="u1"), plan))

    action = SendEmailAction.model_validate(response.actions[0].payload)
    assert action.recipient == "harshita@example.com"
    assert "Submit the assignment before 7 May." == action.body


def test_llm_extraction_replaces_regex() -> None:
    agent = supervisor(
        llm=FakeLLM(
            True,
            {
                "recipient": "sarah@company.com",
                "subject": "Project deadline",
                "body": "The deadline is Friday.",
                "thread_id": None,
            },
        )
    )

    action = asyncio.run(agent._extract_email_params("write to sarah@company.com about the project, tell her the deadline is Friday."))

    assert action.recipient == "sarah@company.com"
    assert action.subject
    assert "deadline is Friday" in action.body


def test_form_fill_request_asks_for_missing_values() -> None:
    agent = supervisor()

    response = asyncio.run(
        agent._browser_form_response(
            ChatRequest(message="https://forms.gle/example fill this google form"),
            "https://forms.gle/example",
        )
    )

    assert "I can fill the form, but I need these values first:" in response.response
    assert "University Roll no." in response.data["missing_fields"]
    assert not response.actions


def test_form_fill_request_creates_approval_when_values_are_present() -> None:
    agent = supervisor()
    message = """https://forms.gle/example fill this google form
Roll no: 123
Name: Test User
Branch: CSE-AI
KIET email: test@kiet.edu
Contact no: 9999999999
Year of passing: 2028
Gender: Male
Residential area: Hostler
Source for internship: Byself"""

    response = asyncio.run(agent._browser_form_response(ChatRequest(message=message), "https://forms.gle/example"))

    assert response.actions
    assert response.actions[0].action_type == "browser.form_submit"
    assert response.actions[0].payload["fields"]["Branch"] == "CSE-AI"
    assert response.actions[0].payload["submit"] is True

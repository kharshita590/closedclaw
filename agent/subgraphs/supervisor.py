from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from pydantic import ValidationError

from actions.models import BrowserFormSubmitAction, BrowserNavigateAction, ClearSpamAction, DeleteEmailAction, SendEmailAction
from approvals.ledger import ApprovalLedger
from audit.logger import AuditLogger
from graph.state import ChatRequest, ChatResponse
from llm.client import LLMClient
from policy.policy_engine import PolicyEngine
from subgraphs.email_agent import EmailAgent
from subgraphs.execution_plan import ExecutionPlan, ExecutionStep, StepResult
from subgraphs.intent_router import HierarchicalIntentRouter, RouteDecision
from subgraphs.research_agent import ResearchAgent
from tools.calendar_tools import CalendarTools
from tools.memory_tools import MemoryStore


class SupervisorAgent:
    def __init__(self) -> None:
        self.audit = AuditLogger()
        self.memory = MemoryStore()
        self.email = EmailAgent()
        self.calendar = CalendarTools()
        self.research_agent = ResearchAgent()
        self.llm = LLMClient()
        self.router = HierarchicalIntentRouter(self.llm)
        self.approvals = ApprovalLedger()
        self.policy = PolicyEngine(self.approvals)

    async def handle(self, request: ChatRequest) -> ChatResponse:
        text = request.message.strip()
        self.audit.event("message_received", channel=request.channel, user_id=request.user_id, message=text)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.memory.remember(request.channel, request.user_id, "conversation", text, request.metadata),
        )

        plan = await self._build_plan(request)
        self.audit.event(
            "plan_built",
            step_count=len(plan.steps),
            is_multi_step=plan.is_multi_step,
            steps=[step.model_dump() for step in plan.steps],
            user_id=request.user_id,
        )
        return await self._execute_plan(request, plan)

    async def _build_plan(self, request: ChatRequest) -> ExecutionPlan:
        """Build a bounded execution plan for one chat request.

        Args:
            request: The inbound chat request with message and user context.

        Returns:
            An ExecutionPlan. Simple messages use the existing router without an
            LLM planner; sequential messages use deterministic JSON extraction.

        This keeps routine routing cheap while giving multi-step requests an
        ordered, auditable plan that still maps to existing typed handlers.
        """

        text = request.message.strip()
        route_context = {"channel": request.channel, "user_id": request.user_id, "metadata": request.metadata}
        if not self.llm.enabled() or not self._looks_sequential(text):
            decision = await self.router.route(text, route_context)
            self._audit_decision(request, decision)
            return self._single_step_plan(text, decision)

        prompt = f"""
You are a planning assistant for a personal AI agent. The agent has these
exact capabilities, identified by intent name:
  - latest_email: retrieve the most recent email, optionally filtered by sender.
  - summarize_email: summarize multiple emails or the inbox.
  - draft_email: compose and queue an email for approval before sending.
  - destructive_email: delete an email or clear spam (always requires approval).
  - calendar: show, create, or reschedule calendar events.
  - browser: navigate to a URL or research a topic using a browser.
  - remember: save a note to memory.
  - search_memory: search previously saved notes.

Given the user message below, produce a JSON execution plan with this schema:
{{
  "steps": [
    {{
      "step_id": 1,
      "intent": "<one of the intent names above>",
      "description": "<what this step does in plain English>",
      "depends_on_step": null,
      "params": {{}}
    }}
  ]
}}

Rules you must follow:
- Maximum 5 steps. If the message requires more, return only the first 5.
- Use depends_on_step to express data dependencies between steps.
  Example: if step 2 needs the result of step 1, set depends_on_step to 1.
- Only use intent names from the list above. Never invent new ones.
- If the message is clearly single-step, return exactly one step.
- Return ONLY valid JSON. No explanation. No markdown. No commentary.

User message: {text}
""".strip()
        try:
            payload = await self.llm.extract_json(prompt)
            return ExecutionPlan.model_validate({**payload, "raw_message": text})
        except Exception as exc:
            self.audit.event(
                "plan_build_failed",
                provider=self.llm.provider,
                error=str(exc),
                raw_response=getattr(self.llm, "last_raw_response", ""),
                user_id=request.user_id,
            )
            decision = await self.router.route(text, route_context)
            self._audit_decision(request, decision)
            return self._single_step_plan(text, decision)

    async def _execute_plan(self, request: ChatRequest, plan: ExecutionPlan) -> ChatResponse:
        """Execute a bounded plan step by step and aggregate the final response.

        Args:
            request: Original chat request used for raw text and user context.
            plan: Ordered plan whose steps map to existing supervisor handlers.

        Returns:
            A ChatResponse combining successful step text, approval actions, and
            structured per-step data.

        The loop is the supervisor's agentic layer: it observes each typed tool
        result and passes structured context to dependent later steps without
        exposing unrestricted tool use to the LLM.
        """

        if not plan.steps:
            decision = await self.router.route(
                request.message,
                {"channel": request.channel, "user_id": request.user_id, "metadata": request.metadata},
            )
            self._audit_decision(request, decision)
            return await self._execute_route(request, decision)

        step_results: dict[int, StepResult] = {}
        skipped: list[StepResult] = []
        for step in plan.steps:
            dependency = step_results.get(step.depends_on_step) if step.depends_on_step is not None else None
            if step.depends_on_step is not None and (dependency is None or not dependency.ok):
                if self._step_can_run_without_dependency(step, request):
                    context = self._step_context(request, step, None)
                    context["failed_dependency"] = dependency.error if dependency else f"Step {step.depends_on_step} did not run."
                    result = await self._execute_single_step(request, step, context)
                    step_results[step.step_id] = result
                    continue
                reason = f"Step {step.step_id} skipped due to failed dependency step {step.depends_on_step}."
                result = StepResult(step_id=step.step_id, intent=step.intent, ok=False, data={}, response_text=reason, error=reason)
                step_results[step.step_id] = result
                skipped.append(result)
                continue

            context = self._step_context(request, step, dependency)
            result = await self._execute_single_step(request, step, context)
            step_results[step.step_id] = result

        successful = [result for result in step_results.values() if result.ok]
        failed = [result for result in step_results.values() if not result.ok and result not in skipped]
        if not successful:
            errors = "\n".join(result.response_text or result.error or f"Step {result.step_id} failed." for result in step_results.values())
            return ChatResponse(response=errors or "The execution plan did not produce any result.")

        response_parts = [result.response_text for result in step_results.values() if result.response_text]
        actions = [action for result in step_results.values() for action in result.actions]
        data = {f"step_{step_id}": result.data for step_id, result in step_results.items() if result.data}
        for result in failed:
            data.setdefault(f"step_{result.step_id}", {"error": result.error})
        return ChatResponse(response="\n".join(response_parts), actions=actions, data=data)

    async def _execute_single_step(self, request: ChatRequest, step: ExecutionStep, context: dict[str, Any]) -> StepResult:
        """Execute one planned step through the existing typed supervisor handlers.

        Args:
            request: Original chat request.
            step: One validated ExecutionStep from the plan.
            context: Request metadata, planner params, and dependency data merged
                for this step.

        Returns:
            A StepResult with structured data, response text, and approval
            actions if the step created any.

        Each handler remains behind policy, approval, and scope enforcement; this
        method only dispatches a planner-selected intent to those existing paths.
        """

        try:
            if step.intent == "latest_email":
                sender = context.get("sender") or context.get("from") or context.get("from_address")
                email_data = await self.email.get_latest_raw(sender=sender)
                if not email_data:
                    return StepResult(step_id=step.step_id, intent=step.intent, ok=True, data={}, response_text="No inbox emails found.")
                text = (
                    "Latest inbox email:\n"
                    f"From: {email_data.get('from_address')}\n"
                    f"Subject: {email_data.get('subject')}\n"
                    f"Date: {email_data.get('date')}\n"
                    f"Preview: {email_data.get('body')}"
                )
                return StepResult(step_id=step.step_id, intent=step.intent, ok=True, data=email_data, response_text=text)

            if step.intent == "summarize_email":
                summary = await self.email.summarize_inbox()
                return StepResult(step_id=step.step_id, intent=step.intent, ok=True, data={"summary": summary}, response_text=summary)

            if step.intent == "draft_email":
                context = await self._enrich_email_context(request, context)
                action_plan = await self._extract_email_params(request.message, context)
                response = await self._send_email_action(request, context=context, action_plan=action_plan)
                data = {"action": action_plan.model_dump(mode="json")}
                if response.actions:
                    data["pending_action"] = response.actions[0].model_dump(mode="json")
                return StepResult(
                    step_id=step.step_id,
                    intent=step.intent,
                    ok=True,
                    data=data,
                    response_text=response.response,
                    actions=response.actions,
                )

            if step.intent == "destructive_email":
                response = self._destructive_email_action(request)
                return StepResult(step_id=step.step_id, intent=step.intent, ok=True, data=response.data, response_text=response.response, actions=response.actions)

            if step.intent == "calendar":
                response = await self._calendar_response(request)
                return StepResult(step_id=step.step_id, intent=step.intent, ok=True, data=response.data, response_text=response.response, actions=response.actions)

            if step.intent == "browser":
                decision = RouteDecision(domain="browser", intent="browser", confidence=1.0, start_url=context.get("start_url") or self._first_url(request.message))
                response = await self._execute_route(request, decision)
                return StepResult(step_id=step.step_id, intent=step.intent, ok=True, data=response.data, response_text=response.response, actions=response.actions)

            if step.intent == "remember":
                content = context.get("query") or context.get("content") or re.sub(r"^remember\s+", "", request.message, flags=re.IGNORECASE).strip()
                loop = asyncio.get_running_loop()
                memory_id = await loop.run_in_executor(None, lambda: self.memory.remember(request.channel, request.user_id, "note", content))
                return StepResult(step_id=step.step_id, intent=step.intent, ok=True, data={"memory_id": memory_id}, response_text=f"Saved memory #{memory_id}.")

            if step.intent == "search_memory":
                query = context.get("query") or re.sub(r"^search memory\s+", "", request.message, flags=re.IGNORECASE).strip()
                loop = asyncio.get_running_loop()
                hits = await loop.run_in_executor(None, lambda: self.memory.search(request.user_id, query))
                response = "\n".join(f"- {hit['content']}" for hit in hits) if hits else "No matching memory found."
                return StepResult(step_id=step.step_id, intent=step.intent, ok=True, data={"memories": hits}, response_text=response)

            raise ValueError(f"No executor registered for intent {step.intent}")
        except Exception as exc:
            return StepResult(step_id=step.step_id, intent=step.intent, ok=False, data={}, response_text=f"Step {step.step_id} failed: {exc}", error=str(exc))

    async def _execute_route(self, request: ChatRequest, decision: RouteDecision) -> ChatResponse:
        text = request.message.strip()
        if decision.domain == "email" and decision.intent == "draft_email":
            return await self._send_email_action(request)
        if decision.domain == "email" and decision.intent == "destructive_email":
            return self._destructive_email_action(request)
        if decision.domain == "email" and decision.intent == "latest_email":
            try:
                return ChatResponse(response=await self.email.latest_email())
            except Exception as exc:
                return ChatResponse(response=f"Email is not ready: {exc}")
        if decision.domain == "email" and decision.intent == "summarize_email":
            try:
                return ChatResponse(response=await self.email.summarize_inbox())
            except Exception as exc:
                return ChatResponse(response=f"Email is not ready: {exc}")
        if decision.domain == "calendar":
            return await self._calendar_response(request)
        if decision.domain == "browser":
            if self._is_form_fill_request(text):
                return await self._browser_form_response(request, decision.start_url or self._first_url(text))
            try:
                action = BrowserNavigateAction(goal=text, url=decision.start_url or self._first_url(text))
                policy = self.policy.check(action)
                if not policy.allowed:
                    self.approvals.create(action, request.user_id, status="rejected", result={"reason": policy.reason})
                    return ChatResponse(response=f"Browser action rejected by policy: {policy.reason}")
                result = await self.research_agent.research(action.goal, action.url)
                return ChatResponse(response=result.get("summary", "Browser task completed."), data={"browser": result})
            except Exception as exc:
                return ChatResponse(response=f"Browser automation failed: {exc}")
        if decision.domain == "memory" and decision.intent == "remember":
            content = decision.query or re.sub(r"^remember\s+", "", text, flags=re.IGNORECASE).strip()
            memory_id = self.memory.remember(request.channel, request.user_id, "note", content)
            return ChatResponse(response=f"Saved memory #{memory_id}.")
        if decision.domain == "memory" and decision.intent == "search_memory":
            query = decision.query or re.sub(r"^search memory\s+", "", text, flags=re.IGNORECASE).strip()
            hits = self.memory.search(request.user_id, query)
            if not hits:
                return ChatResponse(response="No matching memory found.")
            return ChatResponse(response="\n".join(f"- {hit['content']}" for hit in hits), data={"memories": hits})

        if self.llm.enabled():
            try:
                answer = decision.response or await self.llm.general_response(text)
                if answer:
                    return ChatResponse(response=answer)
            except Exception as exc:
                self.audit.event("llm_general_failed", provider=self.llm.provider, error=str(exc))
        return ChatResponse(
            response=(
                "I can manage email, calendar, browser research, memory/CRM notes, and group-chat summaries. "
                "For risky actions like sending mail, deleting mail, or booking purchases, I will create an approval first."
            )
        )

    async def _send_email_action(
        self,
        request: ChatRequest,
        context: dict[str, Any] | None = None,
        action_plan: SendEmailAction | None = None,
    ) -> ChatResponse:
        """Create an approval for a validated SendEmailAction.

        Args:
            request: Original chat request for user attribution.
            context: Optional step context used by the LLM extractor.
            action_plan: Pre-extracted action to avoid duplicate LLM calls.

        Returns:
            ChatResponse containing a pending approval action or a rejection.

        This preserves the safety model by turning natural language into a typed
        action before policy and approval ledger checks run.
        """

        try:
            action_plan = action_plan or await self._parse_send_email(request.message, context)
        except ValueError as exc:
            return ChatResponse(response=f"I need a safer email format before creating an approval: {exc}")
        loop = asyncio.get_running_loop()
        policy = await loop.run_in_executor(None, lambda: self.policy.check(action_plan))
        if not policy.allowed:
            await loop.run_in_executor(
                None,
                lambda: self.approvals.create(action_plan, request.user_id, status="rejected", result={"reason": policy.reason}),
            )
            return ChatResponse(response=f"Email action rejected by policy: {policy.reason}")
        action = await loop.run_in_executor(None, lambda: self.approvals.create(action_plan, request.user_id))
        return ChatResponse(response="I prepared an email action for approval.", actions=[action])

    def _destructive_email_action(self, request: ChatRequest) -> ChatResponse:
        lowered = request.message.lower()
        if "clear spam" in lowered:
            action_plan = ClearSpamAction()
        else:
            match = re.search(r"(?:message|email)\s+id\s+([A-Za-z0-9_-]+)", request.message)
            if not match:
                return ChatResponse(response="To delete mail safely, include the exact message id, for example: delete email id abc123.")
            action_plan = DeleteEmailAction(message_id=match.group(1))
        policy = self.policy.check(action_plan)
        if not policy.allowed:
            self.approvals.create(action_plan, request.user_id, status="rejected", result={"reason": policy.reason})
            return ChatResponse(response=f"Email cleanup rejected by policy: {policy.reason}")
        action = self.approvals.create(action_plan, request.user_id)
        return ChatResponse(response="This email cleanup needs approval before I run it.", actions=[action])

    async def _calendar_response(self, request: ChatRequest) -> ChatResponse:
        """Return upcoming calendar events through the async CalendarTools wrapper."""

        try:
            events = await self.calendar.upcoming_events()
            if not events:
                return ChatResponse(response="No upcoming calendar events found.")
            lines = ["Upcoming calendar events:"]
            for event in events[:10]:
                start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
                lines.append(f"- {start}: {event.get('summary', '(no title)')}")
            return ChatResponse(response="\n".join(lines), data={"events": events})
        except Exception as exc:
            return ChatResponse(response=f"Calendar is not ready: {exc}")

    async def _browser_form_response(self, request: ChatRequest, url: str | None) -> ChatResponse:
        """Ask for form values or create an approval to fill and submit a form.

        Args:
            request: User request containing the form URL or field values.
            url: Form URL extracted by the router or URL parser.

        Returns:
            ChatResponse asking for missing values, or a pending approval action.

        Browser form submission is modeled as a typed action so it is never
        submitted directly by the LLM or browser summary path.
        """

        if not url:
            return ChatResponse(response="Send the form URL and the values you want filled.")
        fields = self._extract_form_values(request.message)
        required = self._default_form_fields()
        missing = [field for field in required if field not in fields]
        if missing:
            lines = [
                "I can fill the form, but I need these values first:",
                *[f"- {field}" for field in missing],
                "",
                "Send them as `Field: value`. I will create an approval before submitting.",
            ]
            return ChatResponse(response="\n".join(lines), data={"form_url": url, "missing_fields": missing, "known_fields": fields})

        action_plan = BrowserFormSubmitAction(url=url, fields={field: fields[field] for field in required}, submit=True)
        policy = self.policy.check(action_plan)
        if not policy.allowed:
            self.approvals.create(action_plan, request.user_id, status="rejected", result={"reason": policy.reason})
            return ChatResponse(response=f"Form submission rejected by policy: {policy.reason}")
        action = self.approvals.create(action_plan, request.user_id)
        return ChatResponse(response="I prepared a form submission action for approval. It will only submit after approval.", actions=[action])

    async def _extract_email_params(self, message: str, context: dict[str, Any] | None = None) -> SendEmailAction:
        """Extract and validate email parameters from text plus step context.

        Args:
            message: Raw user message.
            context: Optional dependency context such as from_address, subject,
                thread_id, and body from a previously retrieved email.

        Returns:
            A validated SendEmailAction.

        The LLM only fills typed parameters; sending still requires policy and
        approval. This exists so loop steps can draft replies from prior tool
        results that do not match a rigid regex format.
        """

        context = context or {}
        prompt = f"""
Extract email action parameters from the user message and context.
Return ONLY a JSON object with exactly these keys:
{{
  "recipient": string or null,
  "subject": string or null,
  "body": string or null,
  "thread_id": string or null
}}

Rules:
- Do not invent an email address if one is not present in the message or context. Set recipient to null instead.
- For replies, use context.from_address as the recipient and context.thread_id as thread_id when available.
- If the subject is a reply, preserve the prior subject with a Re: prefix when appropriate.
- The body should contain the message the user wants sent, not the full prior email.
- Return ONLY valid JSON. No markdown.

Context: {json.dumps(context, default=str)}
User message: {message}
""".strip()
        payload = await self.llm.extract_json(prompt)
        recipient = self._email_address_or_none(payload.get("recipient"))
        if not recipient and payload.get("recipient"):
            context = {**context, "recipient_name": payload.get("recipient")}
        recipient = recipient or self._email_address_or_none(context.get("recipient")) or self._email_address_or_none(context.get("from_address"))
        subject = payload.get("subject") or context.get("subject") or "No subject"
        if context.get("thread_id") and subject and not str(subject).lower().startswith("re:"):
            subject = f"Re: {subject}"
        body = payload.get("body")
        thread_id = payload.get("thread_id") or context.get("thread_id")
        try:
            return SendEmailAction(recipient=recipient, subject=subject, body=body, thread_id=thread_id)
        except ValidationError as exc:
            if not recipient:
                raise ValueError("recipient is missing; include an email address or retrieve an email with a from address first") from exc
            raise ValueError(f"invalid email parameters: {exc}") from exc

    async def _parse_send_email(self, text: str, context: dict[str, Any] | None = None) -> SendEmailAction:
        """Build a typed SendEmailAction from LLM extraction or legacy regex.

        Args:
            text: Raw user message.
            context: Optional step context for reply drafting.

        Returns:
            A validated SendEmailAction.

        LLM-enabled deployments use semantic extraction; LLM_PROVIDER=none keeps
        the legacy constrained parser so existing deterministic behavior remains.
        """

        if self.llm.enabled():
            return await self._extract_email_params(text, context)
        return self._parse_send_email_regex(text, context)

    def _parse_send_email_regex(self, text: str, context: dict[str, Any] | None = None) -> SendEmailAction:
        """Build a typed SendEmailAction using the original constrained regex format."""

        context = context or {}
        recipient_match = re.search(r"\bto\s+([^\s,;]+@[^\s,;]+)", text, flags=re.IGNORECASE)
        recipient = recipient_match.group(1) if recipient_match else context.get("from_address")
        if not recipient:
            raise ValueError("include a recipient like 'to name@example.com'")
        subject_match = re.search(r"\bsubject\s*:?\s+(.+?)(?:\s+(?:body|message)\s*:?\s+|$)", text, flags=re.IGNORECASE)
        body_match = re.search(r"\b(?:body|message)\s*:?\s+(.+)$", text, flags=re.IGNORECASE)
        subject = subject_match.group(1).strip(" :\"'") if subject_match else context.get("subject") or "No subject"
        if context.get("thread_id") and subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        body = body_match.group(1).strip(" :\"'") if body_match else ""
        if not body:
            raise ValueError("include a body like 'body hello, following up...'")
        return SendEmailAction(recipient=recipient, subject=subject, body=body, thread_id=context.get("thread_id"))

    def _first_url(self, text: str) -> str | None:
        match = re.search(r"https?://\S+", text)
        return match.group(0) if match else None

    def _is_form_fill_request(self, text: str) -> bool:
        """Return True when the browser request is asking to fill a web form."""

        lowered = text.lower()
        return "form" in lowered and any(word in lowered for word in ["fill", "submit", "google form", "forms.gle"])

    def _default_form_fields(self) -> list[str]:
        """Return the common required fields for the current internship consent form."""

        return [
            "University Roll no.",
            "Name",
            "Branch",
            "KIET E-Mail Id",
            "Contact no.",
            "Year of Passing",
            "Gender",
            "Residential Area",
            "Source for Internship",
        ]

    def _extract_form_values(self, text: str) -> dict[str, str]:
        """Extract `Field: value` pairs and aliases from a user form-fill message."""

        aliases = {
            "roll no": "University Roll no.",
            "roll number": "University Roll no.",
            "university roll no": "University Roll no.",
            "university roll no.": "University Roll no.",
            "name": "Name",
            "branch": "Branch",
            "kiet email": "KIET E-Mail Id",
            "kiet e-mail id": "KIET E-Mail Id",
            "email": "KIET E-Mail Id",
            "contact": "Contact no.",
            "contact no": "Contact no.",
            "phone": "Contact no.",
            "year of passing": "Year of Passing",
            "passing year": "Year of Passing",
            "gender": "Gender",
            "residential area": "Residential Area",
            "residential": "Residential Area",
            "source for internship": "Source for Internship",
            "source": "Source for Internship",
        }
        fields: dict[str, str] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            raw_key, raw_value = line.split(":", 1)
            key = re.sub(r"\s+", " ", raw_key.strip().lower())
            value = raw_value.strip()
            if not value:
                continue
            canonical = aliases.get(key)
            if canonical:
                fields[canonical] = value
        return fields

    def _looks_sequential(self, text: str) -> bool:
        """Return whether text contains conjunctions that imply ordered actions."""

        lowered = text.lower()
        return any(
            marker in lowered
            for marker in ["and then", "then", "after that", "followed by", "and reply", "and send", "and forward", "and save"]
        )

    def _single_step_plan(self, raw_message: str, decision: RouteDecision) -> ExecutionPlan:
        """Convert an existing RouteDecision into a one-step ExecutionPlan."""

        if decision.intent == "general":
            return ExecutionPlan(steps=[], raw_message=raw_message)
        return ExecutionPlan(
            steps=[
                ExecutionStep(
                    step_id=1,
                    intent=decision.intent,
                    description=f"Handle the user's {decision.intent} request.",
                    depends_on_step=None,
                    params=self._params_from_decision(decision),
                )
            ],
            raw_message=raw_message,
        )

    def _params_from_decision(self, decision: RouteDecision) -> dict[str, Any]:
        """Return non-empty router parameters as planner-compatible hints."""

        params: dict[str, Any] = {}
        if decision.query:
            params["query"] = decision.query
        if decision.start_url:
            params["start_url"] = decision.start_url
        return params

    def _step_context(self, request: ChatRequest, step: ExecutionStep, dependency: StepResult | None) -> dict[str, Any]:
        """Merge request context, planner params, and dependency data for one step."""

        context: dict[str, Any] = {
            "channel": request.channel,
            "user_id": request.user_id,
            "metadata": request.metadata,
            "params": dict(step.params),
        }
        context.update(step.params)
        if dependency:
            context.update(dependency.data)
        return context

    def _step_can_run_without_dependency(self, step: ExecutionStep, request: ChatRequest) -> bool:
        """Return whether a failed dependency should not block this step.

        Draft-email steps can still produce a useful approval or a clear missing
        recipient error when the user supplied an independent recipient hint. A
        true reply like "reply to the latest email" remains dependency-bound.
        """

        if step.intent != "draft_email":
            return False
        if step.params.get("recipient") or step.params.get("recipient_name") or step.params.get("to"):
            return True
        if re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", request.message):
            return True
        return self._recipient_name_from_message(request.message) is not None

    async def _enrich_email_context(self, request: ChatRequest, context: dict[str, Any]) -> dict[str, Any]:
        """Add explicit or contact-resolved recipient data to draft context.

        Args:
            request: Original request containing the raw draft instruction.
            context: Current step context assembled from planner and dependency
                data.

        Returns:
            A copy of context with recipient hints filled from explicit email
            addresses or saved contacts where possible.

        This keeps the LLM from inventing addresses while allowing a direct
        "reply Harshita..." request to use a saved contact even if Gmail lookup
        failed earlier in the plan.
        """

        enriched = dict(context)
        if enriched.get("recipient") or enriched.get("from_address"):
            return enriched

        email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", request.message)
        if email_match:
            enriched["recipient"] = email_match.group(0)
            return enriched

        candidate = (
            enriched.get("recipient_name")
            or enriched.get("name")
            or enriched.get("to")
            or self._recipient_name_from_message(request.message)
        )
        if not candidate:
            return enriched

        enriched["recipient_name"] = candidate
        resolved = await self._resolve_contact_email(str(candidate), request.user_id)
        if resolved:
            enriched["recipient"] = resolved
        return enriched

    async def _resolve_contact_email(self, name: str, user_id: str) -> str | None:
        """Resolve a contact name to an email address from the memory contact store.

        Args:
            name: Person or contact name extracted from the request.
            user_id: User requesting the draft; kept for future per-user contact
                stores and audit parity.

        Returns:
            A saved email address, or None when no matching contact is known.

        The resolver only uses stored contact data and never fabricates an
        address, preserving the email safety rule used by the LLM extractor.
        """

        del user_id
        loop = asyncio.get_running_loop()
        try:
            contacts = await loop.run_in_executor(None, self.memory.contacts)
        except Exception as exc:
            self.audit.event("contact_lookup_failed", error=str(exc))
            return None

        wanted = {part for part in re.split(r"\s+", name.lower().strip()) if part}
        if not wanted:
            return None
        for key, data in contacts.items():
            haystack = f"{key} {json.dumps(data, default=str)}".lower()
            if not wanted.issubset(set(re.findall(r"[a-z0-9._%+-]+", haystack))):
                continue
            email_value = self._email_from_contact(data)
            if email_value:
                return email_value
        return None

    def _email_from_contact(self, data: Any) -> str | None:
        """Return the first email address found in a stored contact document."""

        if isinstance(data, dict):
            for key in ("email", "email_address", "primary_email", "gmail", "work_email"):
                value = data.get(key)
                if isinstance(value, str) and "@" in value:
                    return value
            data = json.dumps(data, default=str)
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", str(data))
        return match.group(0) if match else None

    def _email_address_or_none(self, value: Any) -> str | None:
        """Return value when it is an email address, otherwise None."""

        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", candidate):
            return candidate
        return None

    def _recipient_name_from_message(self, message: str) -> str | None:
        """Extract a non-email recipient name from direct draft instructions."""

        patterns = [
            r"\b(?:reply|write|email|message)\s+(?:to\s+)?(?P<name>[A-Za-z][A-Za-z .'-]{1,80}?)\s+to\s+",
            r"\bsend\s+(?:an?\s+)?(?:email|mail)\s+to\s+(?P<name>[A-Za-z][A-Za-z .'-]{1,80}?)(?:\s+about|\s+saying|\s+that|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                name = re.sub(r"\s+", " ", match.group("name")).strip(" .'\"")
                if name and "@" not in name.lower():
                    return name
        return None

    def _audit_decision(self, request: ChatRequest, decision: RouteDecision) -> None:
        """Write the existing route decision audit event."""

        self.audit.decision(
            provider=self.llm.provider,
            domain=decision.domain,
            intent=decision.intent,
            confidence=decision.confidence,
            user_id=request.user_id,
            channel=request.channel,
        )

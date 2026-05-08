"""FastAPI entry point for the ClosedClaw personal agent API."""

from __future__ import annotations

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from approvals.ledger import ApprovalLedger
from audit.logger import AuditLogger
from graph.agent_graph import PersonalAgentGraph
from graph.state import ChatRequest, ChatResponse, PendingAction
from security.auth import is_valid_api_key, require_auth
from worker.tasks import execute_action_task
from profiles.store import AgentProfileStore
from skills.loader import SkillLoader
from schedule.cron import next_run_from_cron
from schedule.store import ScheduledActionStore

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError:
    trace = None
    OTLPSpanExporter = None
    FastAPIInstrumentor = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None

app = FastAPI(title="ClosedClaw Personal Agent")
agent_profiles = AgentProfileStore()
agent = PersonalAgentGraph()
audit = AuditLogger()
approval_ledger = ApprovalLedger()
skill_loader = SkillLoader()
skill_loader.load()
schedule_store = ScheduledActionStore()


class ApprovalRequest(BaseModel):
    """Request body for approval decisions."""

    decision: Literal["approved", "rejected"]
    decided_by: str = "api"


def _configure_tracing(fastapi_app: FastAPI) -> None:
    """Configure OpenTelemetry FastAPI tracing when dependencies are installed."""

    if not FastAPIInstrumentor:
        return
    import os

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if endpoint and TracerProvider and Resource and BatchSpanProcessor and OTLPSpanExporter:
        provider = TracerProvider(resource=Resource.create({"service.name": "closedclaw-agent"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(fastapi_app)


_configure_tracing(app)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Rejects requests missing a valid API key before route handlers run."""

    if not is_valid_api_key(request.headers.get("authorization"), request.headers.get("x-api-key")):
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


@app.get("/health", dependencies=[Depends(require_auth)])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config", dependencies=[Depends(require_auth)])
def config() -> dict[str, str | bool]:
    return {
        "llm_provider": agent.supervisor.llm.provider,
        "llm_model": agent.supervisor.llm.model,
        "llm_enabled": agent.supervisor.llm.enabled(),
    }


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_auth)])
async def chat(request: ChatRequest) -> ChatResponse:
    profile = agent_profiles.find_for_sender(request.channel, request.user_id)
    if profile:
        from subgraphs.supervisor import SupervisorAgent

        supervisor = SupervisorAgent(
            system_prompt=profile.system_prompt,
            allowed_intents=profile.allowed_intents,
            llm_provider=profile.llm_provider,
            llm_model=profile.llm_model,
        )
        routed_agent = PersonalAgentGraph(supervisor=supervisor)
        response = await routed_agent.invoke(request)
    else:
        response = await agent.invoke(request)
    for action in response.actions:
        audit.event("approval_created", action_id=action.id, action_type=action.action_type, user_id=action.user_id)
    return response


@app.get("/approvals", response_model=list[PendingAction], dependencies=[Depends(require_auth)])
def list_approvals() -> list[PendingAction]:
    return approval_ledger.list_pending()


@app.get("/skills", dependencies=[Depends(require_auth)])
def list_skills() -> list[dict]:
    skill_loader.load()
    return [
        {
            "name": skill.name,
            "description": skill.description,
            "action_type": skill.action_type,
            "risk_level": skill.risk_level,
            "allowed_tools": skill.allowed_tools,
            "enabled": skill.enabled,
        }
        for skill in skill_loader.list()
    ]


class SkillToggleRequest(BaseModel):
    enabled: bool = True


@app.post("/skills/{skill_name}", dependencies=[Depends(require_auth)])
def toggle_skill(skill_name: str, req: SkillToggleRequest) -> dict:
    skill_loader.load()
    if not skill_loader.get(skill_name):
        raise HTTPException(status_code=404, detail="Skill not found")
    skill_loader.set_enabled(skill_name, req.enabled)
    return {"ok": True, "name": skill_name, "enabled": req.enabled}


class ScheduleRequest(BaseModel):
    cron_expression: str
    action_type: str
    payload: dict
    owner_user_id: str
    enabled: bool = True


@app.post("/schedule", dependencies=[Depends(require_auth)])
def create_schedule(req: ScheduleRequest) -> dict:
    next_run = next_run_from_cron(req.cron_expression)
    scheduled_id = schedule_store.insert(req.cron_expression, req.action_type, req.payload, req.owner_user_id, next_run=next_run)
    return {"ok": True, "id": scheduled_id, "next_run": next_run.isoformat() if next_run else None}


@app.get("/schedule", dependencies=[Depends(require_auth)])
def list_schedule() -> list[dict]:
    rows = schedule_store.list_all()
    return [
        {
            "id": row.id,
            "cron_expression": row.cron_expression,
            "action_type": row.action_type,
            "payload": row.payload,
            "owner_user_id": row.owner_user_id,
            "enabled": row.enabled,
            "last_run": row.last_run.isoformat() if row.last_run else None,
            "next_run": row.next_run.isoformat() if row.next_run else None,
        }
        for row in rows
    ]


@app.post("/approvals/{action_id}", response_model=PendingAction, dependencies=[Depends(require_auth)])
async def decide_approval(action_id: str, request: ApprovalRequest) -> PendingAction:
    row = approval_ledger.get(action_id)
    if not row:
        raise HTTPException(status_code=404, detail="Approval not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail="Approval was already decided")
    if request.decision == "rejected":
        action = approval_ledger.decide(action_id, "rejected", request.decided_by, {"reason": "Rejected by approver"})
        audit.event("approval_decided", action_id=action.id, decision="rejected", action_type=action.action_type)
        return action

    try:
        pending = approval_ledger.mark_queued(action_id, request.decided_by)
    except ValueError:
        raise HTTPException(status_code=409, detail="Approval was already queued or decided")
    execute_action_task.delay(action_id)
    audit.event("approval_queued", action_id=pending.id, action_type=pending.action_type, decided_by=request.decided_by)
    return pending

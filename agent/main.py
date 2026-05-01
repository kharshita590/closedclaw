from __future__ import annotations

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from actions.executor import ActionExecutor
from approvals.ledger import ApprovalLedger
from audit.logger import AuditLogger
from graph.agent_graph import PersonalAgentGraph
from graph.state import ChatRequest, ChatResponse, PendingAction
from policy.policy_engine import PolicyEngine
from security.auth import is_valid_api_key, require_auth

app = FastAPI(title="ClosedClaw Personal Agent")
agent = PersonalAgentGraph()
audit = AuditLogger()
approval_ledger = ApprovalLedger()
policy_engine = PolicyEngine(approval_ledger)
action_executor = ActionExecutor(policy_engine)


class ApprovalRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    decided_by: str = "api"


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
    response = await agent.invoke(request)
    for action in response.actions:
        audit.event("approval_created", action_id=action.id, action_type=action.action_type, user_id=action.user_id)
    return response


@app.get("/approvals", response_model=list[PendingAction], dependencies=[Depends(require_auth)])
def list_approvals() -> list[PendingAction]:
    return approval_ledger.list_pending()


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

    action_plan = approval_ledger.get_action(action_id)
    execution = await action_executor.execute_approved(action_plan)
    final_status = "approved" if execution.get("ok") else "rejected"
    action = approval_ledger.decide(action_id, final_status, request.decided_by, execution)
    audit.event(
        "approval_decided",
        action_id=action.id,
        decision=final_status,
        action_type=action.action_type,
        execution=execution,
    )
    return action

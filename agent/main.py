from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from audit.logger import AuditLogger
from graph.agent_graph import PersonalAgentGraph
from graph.state import ChatRequest, ChatResponse, PendingAction

app = FastAPI(title="ClosedClaw Personal Agent")
agent = PersonalAgentGraph()
audit = AuditLogger()
pending_actions: dict[str, PendingAction] = {}


class ApprovalRequest(BaseModel):
    decision: Literal["approved", "rejected"]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    response = await agent.invoke(request)
    for action in response.actions:
        pending_actions[action.id] = action
        audit.event("approval_created", action_id=action.id, action_type=action.action_type, user_id=action.user_id)
    return response


@app.get("/approvals", response_model=list[PendingAction])
def list_approvals() -> list[PendingAction]:
    return [action for action in pending_actions.values() if action.status == "pending"]


@app.post("/approvals/{action_id}", response_model=PendingAction)
def decide_approval(action_id: str, request: ApprovalRequest) -> PendingAction:
    action = pending_actions.get(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Approval not found")
    action.status = request.decision
    pending_actions[action_id] = action
    audit.event("approval_decided", action_id=action.id, decision=request.decision, action_type=action.action_type)
    return action

from __future__ import annotations

from graph.checkpointer import SQLiteCheckpointer
from graph.state import ChatRequest, ChatResponse
from subgraphs.supervisor import SupervisorAgent


class PersonalAgentGraph:
    def __init__(self) -> None:
        self.supervisor = SupervisorAgent()
        self.checkpointer = SQLiteCheckpointer()

    async def invoke(self, request: ChatRequest) -> ChatResponse:
        thread_id = request.thread_id or f"{request.channel}:{request.user_id}"
        state = self.checkpointer.get(thread_id)
        state["messages"].append({"role": "user", "content": request.message, "channel": request.channel})
        response = await self.supervisor.handle(request)
        state["messages"].append({"role": "assistant", "content": response.response})
        self.checkpointer.put(thread_id, state)
        return response

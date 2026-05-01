from __future__ import annotations

import os
from pathlib import Path

import httpx
import streamlit as st

from components.approval_panel import render_approvals
from components.browser_review import render_browser_result
from components.calendar_diff import render_calendar_events


AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000").rstrip("/")

st.set_page_config(page_title="ClosedClaw", page_icon="CC", layout="wide")
st.title("ClosedClaw Personal Agent")

if "messages" not in st.session_state:
    st.session_state.messages = []

left, right = st.columns([2, 1])

with left:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask about email, calendar, browser research, memory, or group summaries")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        payload = {"message": prompt, "channel": "ui", "user_id": os.getenv("USER", "local-user")}
        try:
            result = httpx.post(f"{AGENT_URL}/chat", json=payload, timeout=120).json()
            answer = result["response"]
            st.session_state.messages.append({"role": "assistant", "content": answer})
            st.session_state.last_data = result.get("data", {})
            st.rerun()
        except Exception as exc:
            st.error(f"Agent unavailable: {exc}")

    data = st.session_state.get("last_data", {})
    render_browser_result(data.get("browser", {}))
    if data.get("events"):
        st.subheader("Calendar")
        render_calendar_events(data["events"])

with right:
    render_approvals(AGENT_URL)
    st.subheader("Recent audit")
    audit_file = Path("/app/logs/audit.jsonl")
    if not audit_file.exists():
        audit_file = Path("logs/audit.jsonl")
    if audit_file.exists():
        lines = audit_file.read_text(encoding="utf-8").splitlines()[-10:]
        st.code("\n".join(lines) or "No audit events yet.")
    else:
        st.caption("No audit log mounted yet.")

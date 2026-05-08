from __future__ import annotations

import os
from pathlib import Path

import httpx
import streamlit as st

from components.approval_panel import render_approvals
from components.browser_review import render_browser_result
from components.calendar_diff import render_calendar_events


AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000").rstrip("/")
AGENT_API_KEY = os.getenv("AGENT_API_KEY") or os.getenv("AGENT_API_KEYS", "").split(",")[0].strip()


def _agent_headers() -> dict[str, str]:
    """Builds auth headers for Streamlit calls to the agent API."""

    return {"Authorization": f"Bearer {AGENT_API_KEY}"} if AGENT_API_KEY else {}


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
            result = httpx.post(f"{AGENT_URL}/chat", headers=_agent_headers(), json=payload, timeout=120).json()
            answer = result["response"]
            st.session_state.messages.append({"role": "assistant", "content": answer})
            st.session_state.last_data = result.get("data", {})
            st.rerun()
        except Exception as exc:
            st.error(f"Agent unavailable: {exc}")

    data = st.session_state.get("last_data", {})
    suggestions = data.get("suggestions") if isinstance(data, dict) else None
    if isinstance(suggestions, list) and suggestions:
        st.caption("Suggested follow-ups:")
        for suggestion in suggestions[:5]:
            if st.button(str(suggestion), key=f"sugg_{suggestion}"):
                st.session_state.messages.append({"role": "user", "content": str(suggestion)})
                payload = {"message": str(suggestion), "channel": "ui", "user_id": os.getenv("USER", "local-user")}
                result = httpx.post(f"{AGENT_URL}/chat", headers=_agent_headers(), json=payload, timeout=120).json()
                answer = result["response"]
                st.session_state.messages.append({"role": "assistant", "content": answer})
                st.session_state.last_data = result.get("data", {})
                st.rerun()
    render_browser_result(data.get("browser", {}))
    if data.get("events"):
        st.subheader("Calendar")
        render_calendar_events(data["events"])

with right:
    st.subheader("Agent config")
    try:
        config = httpx.get(f"{AGENT_URL}/config", headers=_agent_headers(), timeout=5).json()
        st.json(config)
    except Exception as exc:
        st.caption(f"Config unavailable: {exc}")

    st.subheader("Skills")
    try:
        skills = httpx.get(f"{AGENT_URL}/skills", headers=_agent_headers(), timeout=5).json()
        for skill in skills:
            enabled = bool(skill.get("enabled", True))
            label = f"{skill.get('name')} ({skill.get('risk_level')})"
            new_enabled = st.toggle(label, value=enabled, key=f"skill_{skill.get('name')}")
            if new_enabled != enabled:
                httpx.post(
                    f"{AGENT_URL}/skills/{skill.get('name')}",
                    headers=_agent_headers(),
                    json={"enabled": new_enabled},
                    timeout=10,
                )
                st.rerun()
    except Exception as exc:
        st.caption(f"Skills unavailable: {exc}")

    st.subheader("Scheduled tasks")
    try:
        schedules = httpx.get(f"{AGENT_URL}/schedule", headers=_agent_headers(), timeout=5).json()
        if schedules:
            for row in schedules:
                st.caption(f"{row['id']} — {row['cron_expression']} — {row['action_type']}")
                st.caption(f"next_run={row.get('next_run')} last_run={row.get('last_run')}")
        else:
            st.caption("No scheduled tasks yet.")
    except Exception as exc:
        st.caption(f"Schedule unavailable: {exc}")

    render_approvals(AGENT_URL, _agent_headers())
    st.subheader("Recent audit")
    audit_file = Path("/app/logs/audit.jsonl")
    if not audit_file.exists():
        audit_file = Path("logs/audit.jsonl")
    if audit_file.exists():
        lines = audit_file.read_text(encoding="utf-8").splitlines()[-10:]
        st.code("\n".join(lines) or "No audit events yet.")
    else:
        st.caption("No audit log mounted yet.")

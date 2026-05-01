from __future__ import annotations

import httpx
import streamlit as st


def render_approvals(agent_url: str, headers: dict[str, str] | None = None) -> None:
    """Renders pending approvals and posts approval decisions with API auth headers."""

    headers = headers or {}
    st.subheader("Pending approvals")
    try:
        approvals = httpx.get(f"{agent_url}/approvals", headers=headers, timeout=10).json()
    except Exception as exc:
        st.info(f"Approval service unavailable: {exc}")
        return
    if not approvals:
        st.caption("No pending actions.")
        return
    for action in approvals:
        with st.container(border=True):
            st.write(action["summary"])
            st.code(action["payload"])
            cols = st.columns(2)
            if cols[0].button("Approve", key=f"approve-{action['id']}"):
                httpx.post(f"{agent_url}/approvals/{action['id']}", headers=headers, json={"decision": "approved", "decided_by": "ui"}, timeout=10)
                st.rerun()
            if cols[1].button("Reject", key=f"reject-{action['id']}"):
                httpx.post(f"{agent_url}/approvals/{action['id']}", headers=headers, json={"decision": "rejected", "decided_by": "ui"}, timeout=10)
                st.rerun()

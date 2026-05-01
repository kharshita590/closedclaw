from __future__ import annotations

import streamlit as st


def render_email_preview(action: dict) -> None:
    st.write("Email action")
    st.json(action)

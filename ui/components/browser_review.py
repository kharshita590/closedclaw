from __future__ import annotations

import streamlit as st


def render_browser_result(result: dict) -> None:
    if not result:
        return
    st.subheader("Browser result")
    if result.get("url"):
        st.link_button("Open source page", result["url"])
    if result.get("title"):
        st.write(result["title"])
    if result.get("text"):
        st.text_area("Extracted text", result["text"], height=260)

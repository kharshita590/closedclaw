from __future__ import annotations

import streamlit as st


def render_calendar_events(events: list[dict]) -> None:
    for event in events:
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        st.write(f"{start} - {event.get('summary', '(no title)')}")

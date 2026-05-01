from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build

from auth.oauth import load_credentials
from auth.scopes import CALENDAR_SCOPES
from permissions.registry import require_scope


class CalendarTools:
    def __init__(self) -> None:
        creds = load_credentials("calendar_token", CALENDAR_SCOPES)
        self.service = build("calendar", "v3", credentials=creds) if creds else None

    def available(self) -> bool:
        return self.service is not None

    @require_scope("calendar:read")
    def upcoming_events(self, days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
        self._require()
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)
        result = (
            self.service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=end.isoformat(),
                maxResults=limit,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return result.get("items", [])

    @require_scope("calendar:write")
    def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        attendees: list[str] | None = None,
        description: str | None = None,
        timezone_name: str = "Asia/Kolkata",
    ) -> dict[str, Any]:
        self._require()
        event = {
            "summary": summary,
            "description": description or "",
            "start": {"dateTime": start, "timeZone": timezone_name},
            "end": {"dateTime": end, "timeZone": timezone_name},
            "attendees": [{"email": attendee} for attendee in attendees or []],
        }
        return self.service.events().insert(calendarId="primary", body=event, sendUpdates="all").execute()

    @require_scope("calendar:write")
    def reschedule_event(self, event_id: str, start: str, end: str, timezone_name: str = "Asia/Kolkata") -> dict[str, Any]:
        self._require()
        event = self.service.events().get(calendarId="primary", eventId=event_id).execute()
        event["start"] = {"dateTime": start, "timeZone": timezone_name}
        event["end"] = {"dateTime": end, "timeZone": timezone_name}
        return self.service.events().update(calendarId="primary", eventId=event_id, body=event, sendUpdates="all").execute()

    @require_scope("calendar:read")
    def find_free_slots(
        self,
        start: str,
        end: str,
        duration_minutes: int = 30,
        calendars: list[str] | None = None,
    ) -> list[dict[str, str]]:
        self._require()
        calendars = calendars or ["primary"]
        body = {"timeMin": start, "timeMax": end, "items": [{"id": cal} for cal in calendars]}
        busy = self.service.freebusy().query(body=body).execute().get("calendars", {})
        busy_ranges = []
        for cal in busy.values():
            busy_ranges.extend(cal.get("busy", []))
        cursor = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        slots = []
        for item in sorted(busy_ranges, key=lambda value: value["start"]):
            busy_start = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
            busy_end = datetime.fromisoformat(item["end"].replace("Z", "+00:00"))
            if (busy_start - cursor).total_seconds() >= duration_minutes * 60:
                slots.append({"start": cursor.isoformat(), "end": (cursor + timedelta(minutes=duration_minutes)).isoformat()})
            cursor = max(cursor, busy_end)
        if (end_dt - cursor).total_seconds() >= duration_minutes * 60:
            slots.append({"start": cursor.isoformat(), "end": (cursor + timedelta(minutes=duration_minutes)).isoformat()})
        return slots

    def _require(self) -> None:
        if not self.service:
            raise RuntimeError("Google Calendar is not connected. Run OAuth setup and store calendar_token first.")

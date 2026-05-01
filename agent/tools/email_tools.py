from __future__ import annotations

import base64
import email
from email.message import EmailMessage
from typing import Any

from googleapiclient.discovery import build

from auth.oauth import load_credentials
from auth.scopes import GMAIL_SCOPES
from permissions.registry import require_scope


class EmailTools:
    def __init__(self) -> None:
        creds = load_credentials("gmail_token", GMAIL_SCOPES)
        self.service = build("gmail", "v1", credentials=creds) if creds else None

    def available(self) -> bool:
        return self.service is not None

    @require_scope("email:read")
    def list_messages(self, query: str = "in:inbox newer_than:14d", limit: int = 10) -> list[dict[str, Any]]:
        self._require()
        result = self.service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        messages = []
        for item in result.get("messages", []):
            messages.append(self.get_message(item["id"], metadata_only=True))
        return messages

    @require_scope("email:read")
    def get_message(self, message_id: str, metadata_only: bool = False) -> dict[str, Any]:
        self._require()
        fmt = "metadata" if metadata_only else "full"
        msg = self.service.users().messages().get(userId="me", id=message_id, format=fmt).execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId"),
            "from": headers.get("from"),
            "to": headers.get("to"),
            "subject": headers.get("subject", "(no subject)"),
            "date": headers.get("date"),
            "snippet": msg.get("snippet"),
            "body": "" if metadata_only else self._body_from_payload(msg.get("payload", {})),
        }

    @require_scope("email:send")
    def create_draft(self, to: str, subject: str, body: str, thread_id: str | None = None) -> dict[str, Any]:
        self._require()
        raw = self._raw_message(to=to, subject=subject, body=body)
        draft_body: dict[str, Any] = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id
        return self.service.users().drafts().create(userId="me", body=draft_body).execute()

    @require_scope("email:send")
    def send_email(self, to: str, subject: str, body: str, thread_id: str | None = None) -> dict[str, Any]:
        self._require()
        payload: dict[str, Any] = {"raw": self._raw_message(to=to, subject=subject, body=body)}
        if thread_id:
            payload["threadId"] = thread_id
        return self.service.users().messages().send(userId="me", body=payload).execute()

    @require_scope("email:delete")
    def delete_message(self, message_id: str) -> None:
        self._require()
        self.service.users().messages().trash(userId="me", id=message_id).execute()

    @require_scope("email:delete")
    def clear_spam(self, limit: int = 50) -> int:
        self._require()
        result = self.service.users().messages().list(userId="me", q="in:spam", maxResults=limit).execute()
        count = 0
        for item in result.get("messages", []):
            self.service.users().messages().delete(userId="me", id=item["id"]).execute()
            count += 1
        return count

    def _require(self) -> None:
        if not self.service:
            raise RuntimeError("Gmail is not connected. Run OAuth setup and store gmail_token first.")

    def _raw_message(self, to: str, subject: str, body: str) -> str:
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    def _body_from_payload(self, payload: dict[str, Any]) -> str:
        chunks: list[str] = []
        for part in self._walk_parts(payload):
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                chunks.append(base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace"))
        if chunks:
            return "\n".join(chunks)
        data = payload.get("body", {}).get("data")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    def _walk_parts(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        parts = payload.get("parts") or []
        out = []
        for part in parts:
            out.append(part)
            out.extend(self._walk_parts(part))
        return out

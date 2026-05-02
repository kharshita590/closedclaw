from __future__ import annotations

import asyncio
import base64
import email
from email.message import EmailMessage
from typing import Any

from googleapiclient.discovery import build

from auth.oauth import load_credentials
from auth.scopes import GMAIL_SCOPES
from permissions.registry import require_scope


class EmailTools:
    """Gmail tool wrapper with async public methods backed by a thread pool."""

    def __init__(self) -> None:
        """Initialize the Gmail service if OAuth credentials are available."""

        creds = load_credentials("gmail_token", GMAIL_SCOPES)
        self.service = build("gmail", "v1", credentials=creds) if creds else None

    def available(self) -> bool:
        """Return whether Gmail credentials were loaded successfully."""

        return self.service is not None

    @require_scope("email:read")
    async def list_messages(self, query: str = "in:inbox newer_than:14d", limit: int = 10) -> list[dict[str, Any]]:
        """List Gmail messages without blocking the event loop."""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._list_messages_sync(query, limit))

    def _list_messages_sync(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Synchronously list Gmail messages inside a worker thread."""

        self._require()
        result = self.service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        messages = []
        for item in result.get("messages", []):
            messages.append(self._get_message_sync(item["id"], metadata_only=True))
        return messages

    @require_scope("email:read")
    async def get_message(self, message_id: str, metadata_only: bool = False) -> dict[str, Any]:
        """Load one Gmail message without blocking the event loop."""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._get_message_sync(message_id, metadata_only))

    def _get_message_sync(self, message_id: str, metadata_only: bool = False) -> dict[str, Any]:
        """Synchronously load one Gmail message inside a worker thread."""

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
    async def create_draft(self, to: str, subject: str, body: str, thread_id: str | None = None) -> dict[str, Any]:
        """Create a Gmail draft without blocking the event loop."""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._create_draft_sync(to, subject, body, thread_id))

    def _create_draft_sync(self, to: str, subject: str, body: str, thread_id: str | None = None) -> dict[str, Any]:
        """Synchronously create a Gmail draft inside a worker thread."""

        self._require()
        raw = self._raw_message(to=to, subject=subject, body=body)
        draft_body: dict[str, Any] = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id
        return self.service.users().drafts().create(userId="me", body=draft_body).execute()

    @require_scope("email:send")
    async def send_email(self, to: str, subject: str, body: str, thread_id: str | None = None) -> dict[str, Any]:
        """Send a Gmail message without blocking the event loop."""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._send_email_sync(to, subject, body, thread_id))

    def _send_email_sync(self, to: str, subject: str, body: str, thread_id: str | None = None) -> dict[str, Any]:
        """Synchronously send a Gmail message inside a worker thread."""

        self._require()
        payload: dict[str, Any] = {"raw": self._raw_message(to=to, subject=subject, body=body)}
        if thread_id:
            payload["threadId"] = thread_id
        return self.service.users().messages().send(userId="me", body=payload).execute()

    @require_scope("email:delete")
    async def delete_message(self, message_id: str) -> None:
        """Move a Gmail message to trash without blocking the event loop."""

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self._delete_message_sync(message_id))

    def _delete_message_sync(self, message_id: str) -> None:
        """Synchronously move a Gmail message to trash inside a worker thread."""

        self._require()
        self.service.users().messages().trash(userId="me", id=message_id).execute()

    @require_scope("email:delete")
    async def clear_spam(self, limit: int = 50) -> int:
        """Clear Gmail spam without blocking the event loop."""

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._clear_spam_sync(limit))

    def _clear_spam_sync(self, limit: int = 50) -> int:
        """Synchronously clear Gmail spam inside a worker thread."""

        self._require()
        result = self.service.users().messages().list(userId="me", q="in:spam", maxResults=limit).execute()
        count = 0
        for item in result.get("messages", []):
            self.service.users().messages().delete(userId="me", id=item["id"]).execute()
            count += 1
        return count

    def _require(self) -> None:
        """Raise if Gmail has not been connected."""

        if not self.service:
            raise RuntimeError("Gmail is not connected. Run OAuth setup and store gmail_token first.")

    def _raw_message(self, to: str, subject: str, body: str) -> str:
        """Build a base64url Gmail raw message payload."""

        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    def _body_from_payload(self, payload: dict[str, Any]) -> str:
        """Extract plain text from a Gmail API message payload."""

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
        """Return a flattened list of nested Gmail message parts."""

        parts = payload.get("parts") or []
        out = []
        for part in parts:
            out.append(part)
            out.extend(self._walk_parts(part))
        return out

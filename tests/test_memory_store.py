"""Tests for PostgreSQL-backed personal memory storage."""

from __future__ import annotations

from tools.memory_tools import MemoryStore


def test_memory_store_remember_search_and_contacts(postgres_database: str) -> None:
    """MemoryStore persists notes and contacts in PostgreSQL."""

    store = MemoryStore()
    memory_id = store.remember("ui", "user-1", "note", "Project Alpha contact", {"source": "test"})
    assert memory_id > 0
    hits = store.search("user-1", "Alpha")
    assert hits[0]["content"] == "Project Alpha contact"

    store.upsert_contact("alice", {"email": "alice@example.com"})
    assert store.contacts()["alice"]["email"] == "alice@example.com"

from __future__ import annotations

from channel_policy import ChannelPolicy, PairingStore


def test_pairing_code_adds_sender_to_allowlist(postgres_database: str) -> None:
    """A valid one-time code allows a sender to be added to policy storage."""

    policy = ChannelPolicy()
    pairing = PairingStore(ttl_seconds=600)

    code = pairing.create_code("telegram", "chat-1")
    ok, reason = pairing.verify_code("telegram", "chat-1", code)
    assert ok, reason

    policy.add_sender("telegram", "chat-1")
    assert policy.is_allowed("telegram", "chat-1")


def test_wrong_pairing_code_is_rejected(postgres_database: str) -> None:
    """An incorrect pairing code does not authorize a sender."""

    pairing = PairingStore(ttl_seconds=600)
    pairing.create_code("slack", "U123")
    ok, reason = pairing.verify_code("slack", "U123", "000000")
    assert not ok
    assert "Incorrect" in reason


def test_pairing_code_blocks_after_five_attempts(postgres_database: str) -> None:
    """Pairing requests are deleted after five incorrect attempts."""

    pairing = PairingStore(ttl_seconds=600)
    pairing.create_code("slack", "U456")
    for _ in range(5):
        ok, _ = pairing.verify_code("slack", "U456", "000000")
        assert not ok
    ok, reason = pairing.verify_code("slack", "U456", "000000")
    assert not ok
    assert "Too many" in reason

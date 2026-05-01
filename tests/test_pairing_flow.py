from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bridges"))

from channel_policy import ChannelPolicy, PairingStore


def test_pairing_code_adds_sender_to_allowlist(tmp_path: Path) -> None:
    """A valid one-time code allows a sender to be added to policy YAML."""

    policy_path = tmp_path / "channel_policy.yaml"
    db_path = tmp_path / "pairing.db"
    policy = ChannelPolicy(policy_path)
    pairing = PairingStore(db_path, ttl_seconds=600)

    code = pairing.create_code("telegram", "chat-1")
    ok, reason = pairing.verify_code("telegram", "chat-1", code)
    assert ok, reason

    policy.add_sender("telegram", "chat-1")
    assert policy.is_allowed("telegram", "chat-1")


def test_wrong_pairing_code_is_rejected(tmp_path: Path) -> None:
    """An incorrect pairing code does not authorize a sender."""

    pairing = PairingStore(tmp_path / "pairing.db", ttl_seconds=600)
    pairing.create_code("slack", "U123")
    ok, reason = pairing.verify_code("slack", "U123", "000000")
    assert not ok
    assert "Incorrect" in reason

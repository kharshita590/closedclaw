from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class TokenStore:
    def __init__(self, secrets_dir: str = "secrets") -> None:
        self.secrets_dir = Path(secrets_dir)
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        key = os.getenv("TOKEN_ENCRYPTION_KEY")
        if not key:
            key_file = self.secrets_dir / "token_store.key"
            if key_file.exists():
                key = key_file.read_text().strip()
            else:
                key = Fernet.generate_key().decode("utf-8")
                try:
                    key_file.write_text(key)
                except OSError:
                    raise RuntimeError(
                        "TOKEN_ENCRYPTION_KEY is required when the secrets directory is read-only."
                    ) from None
        self.fernet = Fernet(key.encode("utf-8"))

    def read(self, name: str) -> bytes | None:
        path = self.secrets_dir / f"{name}.enc"
        if not path.exists():
            return None
        try:
            return self.fernet.decrypt(path.read_bytes())
        except InvalidToken:
            return None

    def write(self, name: str, payload: bytes) -> None:
        path = self.secrets_dir / f"{name}.enc"
        path.write_bytes(self.fernet.encrypt(payload))

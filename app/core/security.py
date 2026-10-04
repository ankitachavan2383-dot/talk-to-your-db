from __future__ import annotations

from cryptography.fernet import Fernet


class SecretBox:
    """Symmetric encryption for stored credentials."""

    def __init__(self, key: str) -> None:
        if not key:
            raise RuntimeError(
                "APP_SECRET_KEY is not set. Generate one with: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        self._f = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        return self._f.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._f.decrypt(token.encode()).decode()

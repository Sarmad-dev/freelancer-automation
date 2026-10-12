"""Encrypted credential store.

OAuth tokens, API keys and other secrets are never written to general-purpose tables. Callers store a
secret here and keep only the returned ``credential_id`` (``email_accounts.credential_id``,
``integration_connections.credential_id``).

- Authenticated encryption (Fernet: AES-128-CBC + HMAC-SHA256) with a per-row ``key_id`` so keys can rotate.
- The plaintext envelope embeds ``workspace_id`` and ``purpose``; both are verified on read, so a ciphertext
  copied into another workspace or purpose cannot be decrypted by mistake.
- Reads require the workspace id, so a code path that forgot tenant scoping fails closed.
- A managed secret store (KMS/Vault) can replace this class behind the same interface in production.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models_email import CredentialSecret

logger = logging.getLogger("freelancer_os.credentials")


class CredentialError(Exception):
    """Raised when a secret cannot be stored or read. Messages never include secret material."""


class CredentialStore(Protocol):
    def put(
        self, db: DbSession, workspace_id: uuid.UUID, purpose: str, secret: dict[str, str]
    ) -> uuid.UUID: ...

    def get(
        self, db: DbSession, workspace_id: uuid.UUID, credential_id: uuid.UUID
    ) -> dict[str, str]: ...

    def delete(self, db: DbSession, workspace_id: uuid.UUID, credential_id: uuid.UUID) -> None: ...


def parse_keys(raw: str) -> list[tuple[str, str]]:
    """Parse ``"v2:<key>,v1:<key>"`` into ``[(key_id, key), ...]`` (first = current)."""
    keys: list[tuple[str, str]] = []
    for part in (p.strip() for p in raw.split(",") if p.strip()):
        key_id, sep, key = part.partition(":")
        if not sep or not key_id or not key:
            raise CredentialError("CREDENTIAL_ENCRYPTION_KEYS entries must look like 'id:key'")
        keys.append((key_id, key))
    return keys


class EncryptedDbCredentialStore:
    def __init__(self, keys: list[tuple[str, str]]) -> None:
        if not keys:
            raise CredentialError("At least one encryption key is required")
        self._current_id = keys[0][0]
        try:
            self._fernets = {key_id: Fernet(key.encode()) for key_id, key in keys}
        except (ValueError, TypeError) as exc:
            raise CredentialError("Invalid Fernet key in CREDENTIAL_ENCRYPTION_KEYS") from exc

    @classmethod
    def ephemeral(cls) -> EncryptedDbCredentialStore:
        """Random per-process key for development/tests. Secrets do NOT survive a restart."""
        logger.warning(
            "CREDENTIAL_ENCRYPTION_KEYS is not set: using an ephemeral key; stored credentials "
            "will be unreadable after a restart (development only)"
        )
        return cls([("ephemeral", Fernet.generate_key().decode())])

    @property
    def current_key_id(self) -> str:
        return self._current_id

    def _envelope(self, workspace_id: uuid.UUID, purpose: str, secret: dict[str, str]) -> bytes:
        return json.dumps(
            {"w": str(workspace_id), "p": purpose, "s": secret}, separators=(",", ":")
        ).encode()

    def put(
        self, db: DbSession, workspace_id: uuid.UUID, purpose: str, secret: dict[str, str]
    ) -> uuid.UUID:
        if not secret:
            raise CredentialError("Refusing to store an empty secret")
        row = CredentialSecret(
            workspace_id=workspace_id,
            purpose=purpose,
            ciphertext=self._fernets[self._current_id].encrypt(
                self._envelope(workspace_id, purpose, secret)
            ),
            key_id=self._current_id,
        )
        db.add(row)
        db.flush()
        return row.id

    def _load(
        self, db: DbSession, workspace_id: uuid.UUID, credential_id: uuid.UUID
    ) -> CredentialSecret:
        row = db.scalar(
            select(CredentialSecret).where(
                CredentialSecret.id == credential_id, CredentialSecret.workspace_id == workspace_id
            )
        )
        if row is None:
            raise CredentialError("Credential not found")
        return row

    def _decrypt(self, row: CredentialSecret) -> dict[str, str]:
        fernet = self._fernets.get(row.key_id)
        if fernet is None:
            raise CredentialError(f"No key available for key id '{row.key_id}'")
        try:
            data = json.loads(fernet.decrypt(bytes(row.ciphertext)))
        except (InvalidToken, ValueError) as exc:
            raise CredentialError(
                "Credential could not be decrypted (tampered or wrong key)"
            ) from exc
        if data.get("w") != str(row.workspace_id) or data.get("p") != row.purpose:
            raise CredentialError("Credential envelope does not match its row (possible tampering)")
        secret = data.get("s")
        if not isinstance(secret, dict):
            raise CredentialError("Credential payload is malformed")
        return {str(k): str(v) for k, v in secret.items()}

    def get(
        self, db: DbSession, workspace_id: uuid.UUID, credential_id: uuid.UUID
    ) -> dict[str, str]:
        return self._decrypt(self._load(db, workspace_id, credential_id))

    def delete(self, db: DbSession, workspace_id: uuid.UUID, credential_id: uuid.UUID) -> None:
        db.delete(self._load(db, workspace_id, credential_id))
        db.flush()

    def rewrap(self, db: DbSession, workspace_id: uuid.UUID, credential_id: uuid.UUID) -> bool:
        """Re-encrypt under the current key (key rotation). Returns True if the row changed."""
        row = self._load(db, workspace_id, credential_id)
        if row.key_id == self._current_id:
            return False
        secret = self._decrypt(row)
        row.ciphertext = self._fernets[self._current_id].encrypt(
            self._envelope(workspace_id, row.purpose, secret)
        )
        row.key_id = self._current_id
        row.rotated_at = utcnow()
        db.flush()
        return True


def build_store(raw_keys: str) -> EncryptedDbCredentialStore:
    keys = parse_keys(raw_keys)
    return EncryptedDbCredentialStore(keys) if keys else EncryptedDbCredentialStore.ephemeral()

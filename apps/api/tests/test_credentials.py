from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DbSession

from app.db.models import Workspace
from app.db.models_email import CredentialSecret
from app.security.credentials import (
    CredentialError,
    EncryptedDbCredentialStore,
    build_store,
    parse_keys,
)

SECRET = {"access_token": "ya29.SUPER-SECRET-ACCESS", "refresh_token": "1//SUPER-SECRET-REFRESH"}


def key() -> str:
    return Fernet.generate_key().decode()


def make_ws(db: DbSession) -> uuid.UUID:
    ws = Workspace(name="cred-test")
    db.add(ws)
    db.commit()
    return ws.id


def test_roundtrip_and_nothing_readable_in_the_database(db: DbSession) -> None:
    store = EncryptedDbCredentialStore([("v1", key())])
    ws = make_ws(db)
    cid = store.put(db, ws, "gmail_oauth", SECRET)
    db.commit()
    assert store.get(db, ws, cid) == SECRET

    raw = db.execute(
        text("SELECT ciphertext FROM credential_secrets WHERE id = :i"),
        {"i": cid.hex if db.bind.dialect.name == "sqlite" else cid},
    ).scalar()  # type: ignore[union-attr]
    blob = bytes(raw)
    for needle in ("SUPER-SECRET", "access_token", "refresh_token", "ya29"):
        assert needle.encode() not in blob
    assert not blob.startswith(b"{")  # not JSON/plaintext


def test_same_secret_encrypts_differently_each_time(db: DbSession) -> None:
    store = EncryptedDbCredentialStore([("v1", key())])
    ws = make_ws(db)
    a, b = store.put(db, ws, "p", SECRET), store.put(db, ws, "p", SECRET)
    rows = {r.id: bytes(r.ciphertext) for r in db.scalars(select(CredentialSecret))}
    assert rows[a] != rows[b]


def test_reads_are_scoped_to_the_workspace(db: DbSession) -> None:
    store = EncryptedDbCredentialStore([("v1", key())])
    ws1, ws2 = make_ws(db), make_ws(db)
    cid = store.put(db, ws1, "p", SECRET)
    db.commit()
    with pytest.raises(CredentialError, match="not found"):
        store.get(db, ws2, cid)


def test_ciphertext_copied_to_another_workspace_or_purpose_is_rejected(db: DbSession) -> None:
    store = EncryptedDbCredentialStore([("v1", key())])
    ws1, ws2 = make_ws(db), make_ws(db)
    cid = store.put(db, ws1, "gmail", SECRET)
    db.commit()
    row = db.get(CredentialSecret, cid)
    assert row is not None
    # An attacker/bug re-points the row at another tenant: the sealed envelope no longer matches.
    row.workspace_id = ws2
    db.commit()
    with pytest.raises(CredentialError, match="envelope"):
        store.get(db, ws2, cid)
    row.workspace_id = ws1
    row.purpose = "something_else"
    db.commit()
    with pytest.raises(CredentialError, match="envelope"):
        store.get(db, ws1, cid)


def test_tampered_ciphertext_is_detected_without_leaking_it(db: DbSession) -> None:
    store = EncryptedDbCredentialStore([("v1", key())])
    ws = make_ws(db)
    cid = store.put(db, ws, "p", SECRET)
    row = db.get(CredentialSecret, cid)
    assert row is not None
    row.ciphertext = bytes(row.ciphertext)[:-4] + b"AAAA"
    db.commit()
    with pytest.raises(CredentialError) as exc:
        store.get(db, ws, cid)
    assert "SUPER-SECRET" not in str(exc.value)


def test_key_rotation_keeps_old_secrets_readable_and_rewraps(db: DbSession) -> None:
    old, new = key(), key()
    ws = make_ws(db)
    cid = EncryptedDbCredentialStore([("v1", old)]).put(db, ws, "p", SECRET)
    db.commit()

    rotated = EncryptedDbCredentialStore([("v2", new), ("v1", old)])
    assert rotated.get(db, ws, cid) == SECRET  # still readable with the previous key
    assert db.get(CredentialSecret, cid).key_id == "v1"  # type: ignore[union-attr]
    assert rotated.rewrap(db, ws, cid) is True
    db.commit()
    row = db.get(CredentialSecret, cid)
    assert row is not None and row.key_id == "v2" and row.rotated_at is not None
    assert rotated.rewrap(db, ws, cid) is False  # idempotent
    # Once the old key is retired, the re-wrapped secret keeps working...
    assert EncryptedDbCredentialStore([("v2", new)]).get(db, ws, cid) == SECRET
    # ...and a store with only the old key cannot read it.
    with pytest.raises(CredentialError):
        EncryptedDbCredentialStore([("v1", old)]).get(db, ws, cid)


def test_missing_key_for_a_row_is_a_clear_error(db: DbSession) -> None:
    ws = make_ws(db)
    cid = EncryptedDbCredentialStore([("v1", key())]).put(db, ws, "p", SECRET)
    with pytest.raises(CredentialError, match="No key available"):
        EncryptedDbCredentialStore([("v9", key())]).get(db, ws, cid)


def test_delete_removes_the_secret(db: DbSession) -> None:
    store = EncryptedDbCredentialStore([("v1", key())])
    ws = make_ws(db)
    cid = store.put(db, ws, "p", SECRET)
    store.delete(db, ws, cid)
    db.commit()
    with pytest.raises(CredentialError, match="not found"):
        store.get(db, ws, cid)


def test_empty_secrets_and_bad_keys_are_refused(db: DbSession) -> None:
    store = EncryptedDbCredentialStore([("v1", key())])
    with pytest.raises(CredentialError, match="empty"):
        store.put(db, make_ws(db), "p", {})
    with pytest.raises(CredentialError, match="Invalid Fernet key"):
        EncryptedDbCredentialStore([("v1", "not-a-fernet-key")])
    with pytest.raises(CredentialError):
        EncryptedDbCredentialStore([])


def test_key_parsing_and_dev_fallback() -> None:
    assert parse_keys("v2:abc, v1:def") == [("v2", "abc"), ("v1", "def")]
    assert parse_keys("") == []
    with pytest.raises(CredentialError):
        parse_keys("missing-colon")
    assert build_store("").current_key_id == "ephemeral"  # dev/test fallback, logs a warning
    assert build_store(f"v3:{key()}").current_key_id == "v3"

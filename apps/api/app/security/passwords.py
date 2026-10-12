"""Password policy and hashing (Argon2id)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # argon2id with library-recommended parameters

MIN_LENGTH = 12
MAX_LENGTH = 128

# Tiny deny-list of the most common choices that satisfy a length rule. Not a substitute for a
# breached-password check (planned: k-anonymity lookup), but cheap and catches the obvious.
_COMMON = {
    "password1234",
    "123456789012",
    "qwertyuiop12",
    "letmein12345",
    "iloveyou1234",
    "administrator",
    "passwordpassword",
    "freelancer123",
    "freelanceros1",
}


class WeakPasswordError(ValueError):
    pass


def validate_password(password: str, *, email: str = "") -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise WeakPasswordError(f"Use at most {MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in _COMMON or len(set(lowered)) < 5:
        raise WeakPasswordError("That password is too easy to guess. Try a longer passphrase.")
    local = email.split("@", 1)[0].lower()
    if local and len(local) >= 4 and local in lowered:
        raise WeakPasswordError("Password must not contain your email address.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


# Verified against when the account does not exist so timing does not reveal registration.
DUMMY_HASH = _hasher.hash("not-a-real-password-for-timing-equalisation")

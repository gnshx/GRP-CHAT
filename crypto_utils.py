"""
Member 2 — Encryption at Rest (requirement #3: "Messages are not stored as plaintext")

Every message body is encrypted with a server-side symmetric key (Fernet, which
is AES-128-CBC + HMAC-SHA256 under the hood) before app.py hands it to db.py,
and decrypted again only when history is read back out. Fernet also stamps
each ciphertext with its own integrity tag, so a corrupted/edited ciphertext
raises InvalidToken on decrypt — a second, independent layer on top of
Member 4's hash chain.

The key lives in secret.key (gitignored) or the CHAT_SECRET_KEY env var so it
is never committed to the repo.
"""
import os
from cryptography.fernet import Fernet, InvalidToken

_LOCAL_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secret.key")
_SHARED_KEY_FILE = os.environ.get("CHAT_SECRET_FILE", _LOCAL_KEY_FILE)


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("CHAT_SECRET_KEY")
    if env_key:
        return env_key.encode()

    custom_file = os.environ.get("CHAT_SECRET_FILE")
    if custom_file and os.path.exists(custom_file):
        with open(custom_file, "rb") as f:
            return f.read().strip()

    if os.path.exists(_SHARED_KEY_FILE):
        with open(_SHARED_KEY_FILE, "rb") as f:
            return f.read().strip()

    if os.path.exists(_LOCAL_KEY_FILE):
        with open(_LOCAL_KEY_FILE, "rb") as f:
            key = f.read().strip()
            # Also save to shared location for other backends
            try:
                with open(_SHARED_KEY_FILE, "wb") as sf:
                    sf.write(key)
            except Exception:
                pass
            return key

    key = Fernet.generate_key()
    try:
        with open(_SHARED_KEY_FILE, "wb") as f:
            f.write(key)
    except Exception:
        pass
    with open(_LOCAL_KEY_FILE, "wb") as f:
        f.write(key)
    print("[crypto_utils] generated shared secret.key")
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_text(plaintext: str) -> str:
    """Returns a base64 ciphertext string, safe to store as TEXT in SQLite."""
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_text(ciphertext: str) -> str:
    """
    Reverses encrypt_text(). Returns None (instead of raising) if the
    ciphertext was tampered with or corrupted, so callers can flag the
    message instead of crashing the whole history load.
    """
    try:
        return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None

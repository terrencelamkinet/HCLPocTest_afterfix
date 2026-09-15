"""
App-level AES-256-GCM encryption for secrets at rest (bot tokens, API keys).

Design:
  - Key: 32 random bytes, hex-encoded, from NEXUS_SECRET_KEY env. If unset,
    a key is generated on first boot and persisted to keys/secret.key
    (0600) so the app stays usable out-of-the-box on dev boxes. In
    production you MUST set NEXUS_SECRET_KEY explicitly (systemd
    EnvironmentFile) — see docs/security.md.
  - Cipher: AES-256-GCM (authenticated). Nonce (12B) random per encryption,
    prepended to ciphertext. Format:  base64(nonce || tag || ciphertext).
  - Every encrypt() generates a fresh nonce — same plaintext NEVER yields
    the same ciphertext (no ciphertext malleability / pattern leak).
"""
import base64
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_PATH = Path(__file__).resolve().parents[1] / "keys" / "secret.key"
_NONCE_LEN = 12


def _load_key() -> bytes:
    env_key = os.environ.get("NEXUS_SECRET_KEY", "").strip()
    if env_key:
        return bytes.fromhex(env_key)
    # Dev fallback: persistent random key so restarts don't orphan ciphertexts.
    if _KEY_PATH.exists():
        return bytes.fromhex(_KEY_PATH.read_text().strip())
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    _KEY_PATH.write_text(key.hex())
    os.chmod(_KEY_PATH, 0o600)
    return key


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret string → 'v1:' + base64(nonce||tag||ciphertext)."""
    if not plaintext:
        return ""
    key = _load_key()
    nonce = secrets.token_bytes(_NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return "v1:" + base64.b64encode(nonce + ct).decode()


def decrypt_secret(stored: str) -> str:
    """Reverse of encrypt_secret. Returns '' on empty; raises on tamper."""
    if not stored:
        return ""
    if not stored.startswith("v1:"):
        # Legacy plaintext fallback — read as-is (migration path).
        return stored
    raw = base64.b64decode(stored[3:])
    nonce, ct = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    return AESGCM(_load_key()).decrypt(nonce, ct, None).decode()

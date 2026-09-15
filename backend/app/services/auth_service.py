import uuid
import secrets
import os
import bcrypt
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from app.config import settings

# Load RS256 keys once at module level
_PRIVATE_KEY: str | None = None
_PUBLIC_KEY: str | None = None

def _load_private_key() -> str:
    global _PRIVATE_KEY
    if _PRIVATE_KEY is None:
        key_path = settings.jwt_private_key_path
        if not os.path.isabs(key_path):
            # From app/services/auth_service.py -> go up 3 levels to project root
            key_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), key_path)
        with open(key_path) as f:
            _PRIVATE_KEY = f.read()
    return _PRIVATE_KEY

def _load_public_key() -> str:
    global _PUBLIC_KEY
    if _PUBLIC_KEY is None:
        key_path = settings.jwt_public_key_path
        if not os.path.isabs(key_path):
            key_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), key_path)
        with open(key_path) as f:
            _PUBLIC_KEY = f.read()
    return _PUBLIC_KEY

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))

def create_access_token(subject: str, email: str, role: str = "member", tenant_id: str = "") -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": subject,
        "email": email,
        "role": role,
        "tenant_id": tenant_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "access"
    }
    return jwt.encode(payload, _load_private_key(), algorithm=settings.jwt_algorithm)

def create_refresh_token(subject: str) -> tuple[str, datetime]:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    jti = str(uuid.uuid4())
    payload = {
        "sub": subject,
        "jti": jti,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "refresh"
    }
    token = jwt.encode(payload, _load_private_key(), algorithm=settings.jwt_algorithm)
    return token, expire

def create_reset_token(email: str) -> tuple[str, datetime]:
    expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    payload = {
        "sub": email,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "reset"
    }
    token = jwt.encode(payload, _load_private_key(), algorithm=settings.jwt_algorithm)
    return token, expire

def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, _load_public_key(), algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        return None

def generate_otp() -> str:
    return "000000"  # Dev mode: hardcoded

def generate_device_token() -> str:
    return secrets.token_hex(32)

def generate_session_token() -> str:
    return secrets.token_hex(32)

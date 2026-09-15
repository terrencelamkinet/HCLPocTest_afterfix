"""
In-memory rate limiter for WhatsApp endpoints.

SOC 2 CC6.1 / CC7.2: Rate limiting prevents OTP brute force, enumeration, and flooding attacks.

Attack coverage:
  - OTP Brute Force: 3 verify attempts/min per phone → 6-digit OTP (1M combos) would take 3.7 years
  - OTP Flooding: 3 send attempts/min per phone → prevents SMS quota exhaustion
  - Phone Enumeration: Same response for existent/non-existent numbers → attacker can't tell if number is registered

Limitations:
  - In-memory only: resets on server restart (acceptable for MVP)
  - Not distributed: won't work across multiple instances → upgrade to Redis for production
"""

import time
from collections import defaultdict
from typing import Tuple

# {key: [(timestamp, count), ...]}
_rate_store: dict[str, list[float]] = defaultdict(list)

# Config
OTP_SEND_LIMIT = 3       # max send-otp requests per window
OTP_VERIFY_LIMIT = 3     # max verify-otp attempts per window
OTP_WINDOW = 60          # window in seconds (1 minute)
BAN_DURATION = 300       # 5 min temp ban after exceeding limit


def _cleanup(key: str):
    """Remove expired entries for a key."""
    now = time.time()
    _rate_store[key] = [t for t in _rate_store[key] if now - t < OTP_WINDOW]


def _is_banned(key: str) -> bool:
    """Check if key is temporarily banned."""
    ban_key = f"ban:{key}"
    entries = _rate_store.get(ban_key, [])
    if entries:
        ban_time = entries[-1]
        if time.time() - ban_time < BAN_DURATION:
            return True
        _rate_store.pop(ban_key, None)
    return False


def _ban(key: str):
    """Temporarily ban a key."""
    _rate_store[f"ban:{key}"].append(time.time())


def check_rate_limit(key: str, limit: int = OTP_SEND_LIMIT, window: int = OTP_WINDOW) -> Tuple[bool, int, int]:
    """
    Check if action is rate-limited.
    
    Returns (allowed: bool, current_count: int, retry_after_seconds: int)
    """
    if _is_banned(key):
        return False, limit, BAN_DURATION
    
    _cleanup(key)
    count = len(_rate_store[key])
    
    if count >= limit:
        _ban(key)
        return False, count, BAN_DURATION
    
    _rate_store[key].append(time.time())
    return True, count + 1, 0


def check_otp_send(phone: str) -> Tuple[bool, int, int]:
    """Check rate limit for OTP sending."""
    return check_rate_limit(f"otp_send:{phone}", OTP_SEND_LIMIT, OTP_WINDOW)


def check_otp_verify(phone: str) -> Tuple[bool, int, int]:
    """Check rate limit for OTP verification."""
    return check_rate_limit(f"otp_verify:{phone}", OTP_VERIFY_LIMIT, OTP_WINDOW)


def reset_rate_limit(key: str):
    """Reset rate limit for a key (e.g., after successful verification)."""
    _rate_store.pop(key, None)
    _rate_store.pop(f"ban:{key}", None)

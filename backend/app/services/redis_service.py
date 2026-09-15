from datetime import datetime, timezone
from typing import Optional
import redis.asyncio as aioredis
from app.config import settings

_redis: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis

async def store_otp(email: str, otp: str, ttl_seconds: int = 300):
    r = await get_redis()
    key = f"otp:{email}"
    await r.setex(key, ttl_seconds, otp)

async def verify_otp(email: str, otp: str) -> bool:
    r = await get_redis()
    key = f"otp:{email}"
    stored = await r.get(key)
    if stored is None:
        return False
    if stored == otp:
        await r.delete(key)  # One-time use
        return True
    return False

async def store_refresh_blacklist(jti: str, expires_at: datetime):
    r = await get_redis()
    key = f"refresh_blacklist:{jti}"
    ttl = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    if ttl > 0:
        await r.setex(key, ttl, "1")

async def store_device_trust(user_id: str, device_token: str, ttl_days: int = 30):
    r = await get_redis()
    key = f"device_trust:{user_id}:{device_token}"
    await r.setex(key, ttl_days * 86400, user_id)

async def check_device_trust(user_id: str, device_token: str) -> bool:
    r = await get_redis()
    key = f"device_trust:{user_id}:{device_token}"
    return await r.get(key) is not None

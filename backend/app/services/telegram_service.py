"""
Telegram Bot API client — validate token, send messages, manage webhooks.

Telegram is a user-configured connector: the user provides their own Bot
token + Chat ID at bind time (via @BotFather). The token is validated with
getMe() before storing; delivery uses Bot API sendMessage.

Bot token is a secret — stored in nexus_ai.ai_channel_credentials
(ChannelCredential, encrypted at app level), NOT in the mapping table.
"""
import httpx
import asyncio

BOT_API = "https://api.telegram.org/bot{token}/{method}"


async def get_me(token: str) -> dict:
    """Validate a bot token and return bot info: {ok, bot: {username, id}}."""
    url = BOT_API.format(token=token, method="getMe")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url)
        data = resp.json()
    if not data.get("ok"):
        return {"ok": False, "error": data.get("description", "Invalid bot token")}
    bot = data.get("result", {})
    return {"ok": True, "bot": {"username": bot.get("username"), "id": bot.get("id")}}


async def download_file(token: str, file_id: str, ext: str = "ogg") -> bytes | None:
    """Download a Telegram file by file_id (voice/audio/photo...). Returns bytes or None."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            info = (
                await client.post(
                    f"https://api.telegram.org/bot{token}/getFile",
                    json={"file_id": file_id},
                )
            ).json()
        file_path = (info.get("result") or {}).get("file_path")
        if not file_path:
            return None
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"https://api.telegram.org/file/bot{token}/{file_path}")
        if resp.status_code != 200:
            return None
        return resp.content
    except Exception:
        return None


async def send_message(token: str, chat_id: str, text: str) -> dict:
    """Send a text message to a chat. Returns Telegram API response JSON.

    Retry pattern: Telegram API occasionally hiccups (>15s latency, 429/5xx).
    A single failure must not drop the reply — the webhook dedup watermark
    only advances after a successful send, so losing this call would silently
    swallow the user's message (observed 2026-08-06: AI replied but send
    timed out at 15s → reply never delivered, watermark stuck).
    """
    url = BOT_API.format(token=token, method="sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    last_err: str = ""
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=payload)
            data = resp.json()
            # 429 Too Many Requests — Telegram asks to retry after retry_after
            if data.get("ok"):
                return data
            last_err = str(data)[:200]
            if resp.status_code == 429 and attempt < 2:
                retry_after = (data.get("parameters") or {}).get("retry_after", 2)
                await asyncio.sleep(min(retry_after, 5))
                continue
            return data  # non-429 error — surface it, no infinite retry
        except Exception as e:  # noqa: BLE001 — network/timeout, retry
            last_err = str(e)[:200]
            if attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
    return {"ok": False, "error": f"send_message failed after 3 attempts: {last_err}"}


async def set_webhook(token: str, webhook_url: str) -> dict:
    """Register a webhook URL for the bot (receiver side — reserved)."""
    url = BOT_API.format(token=token, method="setWebhook")
    payload = {"url": webhook_url}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        return resp.json()


async def delete_webhook(token: str) -> dict:
    """Remove webhook for the bot."""
    url = BOT_API.format(token=token, method="deleteWebhook")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url)
        return resp.json()


async def get_updates(token: str, offset: int | None = None, timeout: int = 30) -> dict:
    """Long-poll Telegram for new updates (inbound messages).

    offset: pass the highest processed update_id + 1 to confirm delivery.
    timeout: long-poll seconds (Telegram supports up to 50).
    """
    url = BOT_API.format(token=token, method="getUpdates")
    payload: dict = {"timeout": timeout, "allowed_updates": ["message", "edited_message"]}
    if offset is not None:
        payload["offset"] = offset
    async with httpx.AsyncClient(timeout=timeout + 15) as client:
        resp = await client.post(url, json=payload)
        return resp.json()

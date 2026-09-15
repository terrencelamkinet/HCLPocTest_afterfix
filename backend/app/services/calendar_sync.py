"""Calendar Sync Service — Google Calendar OAuth + ICS subscriptions.

Design (Terrence, 2026-08-04):
- CRM platform is the source of truth: all schedule records live in
  `project_calendar_events`, scoped by tenant_id + owner_user_id.
- Google sync is a MIRROR CHECK: fetch remote events, compare with what's
  in CRM by (source, external_event_id, external_updated), write only when
  something changed. Never mass-deletes manual CRM events.
- Sync window: -14 days / +60 days. Interval: active users 15 min,
  inactive 60 min (quota-safe for 50k tenants: project quota 10M req/day).

Change detection:
- Google OAuth: event `updated` (RFC3339) → external_updated
- ICS: `LAST-MODIFIED` / `DTSTAMP` → external_updated; UID → external_event_id

Each module function returns (inserted, updated, deleted, unchanged).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm import ProjectCalendarEvent

_UTC = timezone.utc
_HTTP_TIMEOUT = httpx.Timeout(20.0)
_UA = "Mozilla/5.0 (compatible; NexusCRM/1.0)"

# Sync window
SYNC_PAST_DAYS = 14
SYNC_FUTURE_DAYS = 60

# Interval policy (quota-safe at 50k tenants)
ACTIVE_INTERVAL = timedelta(minutes=15)    # users active in last 7 days
INACTIVE_INTERVAL = timedelta(minutes=60)  # everyone else


def _now() -> datetime:
    return datetime.now(_UTC)


def _ensure_tz(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=_UTC)


async def _is_active_user(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Active = any session/activity in the last 7 days (quota-based interval)."""
    from sqlalchemy import text

    try:
        row = (await db.execute(
            text(
                "SELECT 1 FROM nexus_auth.nexus_auth_sessions "
                "WHERE user_id = :uid AND created_at >= :cutoff LIMIT 1"
            ),
            {"uid": str(user_id), "cutoff": _now() - timedelta(days=7)},
        )).first()
        return row is not None
    except Exception:
        return True  # fail-open: if we can't tell, treat as active


async def _due_for_sync(db: AsyncSession, integration_row, now: datetime) -> bool:
    """Return True when this integration should sync now (interval policy)."""
    last = integration_row.last_sync_at
    if last is None:
        return True
    last = _ensure_tz(last)
    interval = ACTIVE_INTERVAL if await _is_active_user(db, integration_row.user_id) else INACTIVE_INTERVAL
    return (now - last) >= interval


# ─────────────────────────────────────────────────────────────────────
# Token handling (platform-owned OAuth client — users never touch GCP)
# ─────────────────────────────────────────────────────────────────────


async def _valid_access_token(integration_row) -> tuple[str, dict]:
    """Return (access_token, updated_config) — refreshing when needed.

    updated_config is {} when nothing changed; caller persists it if non-empty.
    """
    from app.routers.crm_integrations import refresh_access_token

    cfg = dict(integration_row.config or {})
    access = cfg.get("access_token", "")
    expires_at = cfg.get("expires_at", 0) or 0

    if access and float(expires_at) > _now().timestamp() + 60:
        return access, {}

    # expired (or missing) → refresh
    refresh_tok = cfg.get("refresh_token", "")
    if not refresh_tok:
        raise RuntimeError("no refresh_token — user must reconnect")
    fresh = await refresh_access_token(integration_row.provider, refresh_tok)
    cfg.update(fresh)
    return fresh.get("access_token", ""), cfg


async def _google_events(access_token: str, calendar_id: str = "primary") -> list[dict[str, Any]]:
    """Fetch Google Calendar events in the sync window (paginated).

    calendar_id defaults to 'primary'; users can pick another calendar
    (e.g. a family/holiday calendar) via the Marketplace picker — the
    choice is stored in the integration config.
    """
    time_min = (_now() - timedelta(days=SYNC_PAST_DAYS)).isoformat()
    time_max = (_now() + timedelta(days=SYNC_FUTURE_DAYS)).isoformat()

    from urllib.parse import quote
    cal_path = quote(calendar_id, safe="")
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        while True:
            params = {
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "maxResults": 250,
                "orderBy": "startTime",
            }
            if page_token:
                params["pageToken"] = page_token
            r = await client.get(
                f"https://www.googleapis.com/calendar/v3/calendars/{cal_path}/events",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code == 401:
                raise PermissionError("google token rejected")
            if r.status_code == 403:
                raise PermissionError("google api access denied")
            r.raise_for_status()
            data = r.json()
            items.extend(data.get("items", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
            if len(items) > 2000:
                break  # safety cap
    return items


def _parse_google_event(ev: dict[str, Any], calendar_id: str = "primary") -> dict[str, Any]:
    """Map a Google Calendar event dict → CRM ProjectCalendarEvent fields.

    external_event_id is prefixed with the calendar id — Google event IDs
    are only unique within their own calendar, so mirroring multiple
    calendars must not let two calendars overwrite each other's events.
    """
    start = ev.get("start", {})
    end = ev.get("end", {})
    # all-day events use date (YYYY-MM-DD) instead of dateTime
    if start.get("date"):
        start_dt = datetime.fromisoformat(start["date"]).replace(tzinfo=_UTC)
        end_dt = datetime.fromisoformat(end.get("date", start["date"])).replace(tzinfo=_UTC)
        is_all_day = True
    else:
        start_dt = datetime.fromisoformat(start.get("dateTime", "").replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.get("dateTime", start.get("dateTime", "")).replace("Z", "+00:00"))
        is_all_day = False

    updated = ev.get("updated")
    if updated:
        try:
            updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            updated_dt = None
    else:
        updated_dt = None

    return {
        "title": ev.get("summary") or "(untitled)",
        "description": ev.get("description"),
        "event_type": "meeting",
        "start": start_dt,
        "end": end_dt,
        "is_all_day": is_all_day,
        "location": ev.get("location"),
        "color": "#4285F4",  # Google blue
        "external_event_id": f"{calendar_id}:{ev.get('id', '')}",
        "external_updated": updated_dt,
    }


# ─────────────────────────────────────────────────────────────────────
# Outlook / Microsoft 365 calendar sync (platform-owned OAuth)
# ─────────────────────────────────────────────────────────────────────


async def _outlook_events(
    access_token: str, calendar_id: str = "calendar"
) -> list[dict[str, Any]]:
    """Fetch Outlook / Microsoft 365 calendar events via Microsoft Graph (paginated).

    calendar_id defaults to the user's primary "calendar" (/me/calendar); a
    specific calendar GUID can be stored in the integration config for later
    calendar picker support (mirrors the Google calendar picker).
    """
    time_min = (_now() - timedelta(days=SYNC_PAST_DAYS)).isoformat()
    time_max = (_now() + timedelta(days=SYNC_FUTURE_DAYS)).isoformat()

    from urllib.parse import quote
    cal_path = quote(calendar_id, safe="")
    items: list[dict[str, Any]] = []
    url: str | None = f"https://graph.microsoft.com/v1.0/me/calendars/{cal_path}/events"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        while url:
            params = {
                "$filter": (
                    f"start/dateTime ge '{time_min}' and start/dateTime lt '{time_max}'"
                ),
                "$top": 500,
                "$orderby": "start/dateTime",
                "$select": (
                    "id,iCalUId,subject,bodyPreview,start,end,"
                    "location,isAllDay,lastModifiedDateTime"
                ),
            }
            r = await client.get(
                url, params=params, headers={"Authorization": f"Bearer {access_token}"}
            )
            if r.status_code == 401:
                raise PermissionError("outlook token rejected")
            if r.status_code == 403:
                raise PermissionError("outlook api access denied")
            r.raise_for_status()
            data = r.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            if len(items) > 2000:
                break  # safety cap
    return items


def _parse_outlook_event(ev: dict[str, Any], calendar_id: str = "calendar") -> dict[str, Any]:
    """Map a Microsoft Graph event dict → CRM ProjectCalendarEvent fields.

    external_event_id is prefixed with the calendar id — Graph event IDs are
    only unique within their own calendar, so mirroring multiple calendars
    must not let two calendars overwrite each other's events (same rule as
    Google). Graph's iCalUId is used as the stable external id where present.
    """
    start = ev.get("start", {}) or {}
    end = ev.get("end", {}) or {}

    def _iso(dt_str: str | None):
        """Parse a Microsoft Graph datetime (RFC3339 "2026-08-07T20:00:00Z" or
        all-day date "2026-08-07") to a tz-aware datetime."""
        if not dt_str:
            return None
        s = dt_str.strip()
        if len(s) == 10 and s[4] == "-":  # pure date (all-day)
            return datetime.fromisoformat(s).replace(tzinfo=_UTC)
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    # all-day events carry only a date ("YYYY-MM-DD"), not a dateTime
    is_all_day = bool(ev.get("isAllDay"))
    if is_all_day or (start.get("date") and not start.get("dateTime")):
        start_dt = _iso(start.get("date")) or _now()
        end_dt = _iso(end.get("date")) or start_dt
        is_all_day = True
    else:
        start_dt = _iso(start.get("dateTime")) or _now()
        end_dt = _iso(end.get("dateTime")) or start_dt

    updated_dt = _iso(ev.get("lastModifiedDateTime")) if ev.get("lastModifiedDateTime") else None

    external_id = ev.get("iCalUId") or ev.get("id") or ""
    return {
        "title": ev.get("subject") or "(untitled)",
        "description": ev.get("bodyPreview"),
        "event_type": "meeting",
        "start": start_dt,
        "end": end_dt,
        "is_all_day": is_all_day,
        "location": (ev.get("location") or {}).get("displayName"),
        "color": "#0078D4",  # Outlook blue
        "external_event_id": f"{calendar_id}:{external_id}",
        "external_updated": updated_dt,
    }


# ─────────────────────────────────────────────────────────────────────
# ICS sync (URL subscription — no OAuth required)
# ─────────────────────────────────────────────────────────────────────


async def _fetch_ics(url: str) -> str:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _UA}, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


def _is_outlook_ics_url(url: str) -> bool:
    """True if an ICS subscription URL is hosted by Microsoft Outlook.

    Outlook ICS links (OWA "subscribe to calendar") point at
    outlook.office365.com / outlook.live.com / outlook.com. Everything else
    (Google Calendar, generic .ics hosts) stays tagged "ics".
    """
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    return any(
        host == d or host.endswith("." + d)
        for d in ("outlook.office365.com", "outlook.live.com", "outlook.com")
    )


def _parse_ics(text: str) -> list[dict[str, Any]]:
    """Minimal iCal parser — VEVENT components with UID, DTSTART, DTEND, SUMMARY.

    No external deps; handles UTC (Z), local-with-TZID (ignored — treated as
    naive→UTC), and all-day (DATE only) events.
    """
    events: list[dict[str, Any]] = []
    current: dict[str, str] = {}
    in_vevent = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # unfold continuation lines (starts with space/tab)
        if line[0] in (" ", "\t") and current:
            key = list(current.keys())[-1]
            current[key] = current[key] + line[1:]
            continue

        if line == "BEGIN:VEVENT":
            current = {}
            in_vevent = True
            continue
        if line == "END:VEVENT":
            if in_vevent and current.get("UID"):
                events.append(current)
            current = {}
            in_vevent = False
            continue
        if not in_vevent:
            continue

        if ":" in line:
            head, _, value = line.partition(":")
            parts = head.split(";")
            base_key = parts[0].strip().upper()
            tz_params = [p for p in parts[1:] if p.strip().upper().startswith("TZID=")]
            if tz_params:
                value = tz_params[0] + ":" + value
            current[base_key] = value.strip()

    out: list[dict[str, Any]] = []
    for ev in events:
        dtstart = _parse_ics_dt(ev.get("DTSTART", ""))
        dtend = _parse_ics_dt(ev.get("DTEND", ev.get("DURATION", "")))
        if dtstart is None:
            continue
        if dtend is None:
            dtend = dtstart + timedelta(hours=1)

        last_mod = _parse_ics_dt(ev.get("LAST-MODIFIED") or ev.get("DTSTAMP") or "")
        out.append({
            "title": ev.get("SUMMARY") or "(untitled)",
            "description": ev.get("DESCRIPTION"),
            "event_type": "meeting",
            "start": dtstart,
            "end": dtend,
            "is_all_day": len(ev.get("DTSTART", "")) == 8,
            "location": ev.get("LOCATION"),
            "color": "#34A853",  # ICS green
            "external_event_id": ev.get("UID", ""),
            "external_updated": last_mod,
        })
    return out


def _parse_ics_dt(raw: str) -> datetime | None:
    """Parse iCal datetime: YYYYMMDD, YYYYMMDDTHHMMSS, with/without Z, with TZID.

    - `...Z` → UTC
    - `TZID=xxx:local` → interpret in that zone, return .astimezone(UTC)
      (so a local time like China Standard 11:00 becomes 03:00Z — the frontend,
      which re-localizes to the viewer's browser zone, shows the correct wall clock)
    - naive (no Z, no TZID) → treat as UTC (backwards compatible)
    """
    raw = raw.strip()
    if not raw:
        return None
    # capture TZID if present (e.g. "TZID=China Standard Time:20251020T110000")
    tzid: str | None = None
    if raw.upper().startswith("TZID="):
        head, _, rest = raw.partition(":")
        tzid = head.split("=", 1)[-1].strip()
        raw = rest

    s = raw
    has_tz = s.endswith("Z")
    if has_tz:
        s = s[:-1]
        tzid = None  # Z means UTC; TZID ignored
    s = s.replace("T", "T")  # keep as-is
    try:
        if len(s) == 8:  # date only
            return datetime.strptime(s, "%Y%m%d").replace(tzinfo=_UTC)
        if len(s) < 15:
            return None
        naive = datetime.strptime(s[:15], "%Y%m%dT%H%M%S")
        if has_tz:
            return naive.replace(tzinfo=_UTC)
        if tzid:
            zone = _resolve_tzid(tzid)
            if zone is not None:
                return naive.replace(tzinfo=zone).astimezone(_UTC)
        return naive.replace(tzinfo=_UTC)  # no TZ info → treat as UTC
    except ValueError:
        return None


_TZID_ALIASES = {
    "china standard time": "Asia/Shanghai",
    "hong kong standard time": "Asia/Hong_Kong",
    "india standard time": "Asia/Kolkata",
    "pacific standard time": "America/Los_Angeles",
    "eastern standard time": "America/New_York",
    "central standard time": "America/Chicago",
    "mountain standard time": "America/Denver",
    "greenwich mean time": "Etc/GMT",
    "utc": "Etc/UTC",
}


def _resolve_tzid(tzid: str) -> ZoneInfo | None:
    key = tzid.strip().lower()
    candidate = _TZID_ALIASES.get(key)
    if candidate:
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            return None
    try:
        return ZoneInfo(tzid)
    except ZoneInfoNotFoundError:
        return None


# ─────────────────────────────────────────────────────────────────────
# Sync core — mirror check into project_calendar_events
# ─────────────────────────────────────────────────────────────────────


async def _upsert_events(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    source: str,
    remote: list[dict[str, Any]],
) -> dict[str, int]:
    """Mirror remote events into CRM. Returns {inserted, updated, deleted, unchanged}.

    - Remote event with external_event_id not in CRM → INSERT (source-scoped)
    - Same external_event_id but external_updated newer → UPDATE
    - Same but same timestamp → skip (unchanged)
    - CRM rows with this source+owner that are NOT in remote → DELETE
      (only rows whose external_event_id is non-null; manual rows untouched)
    """
    stats = {"inserted": 0, "updated": 0, "deleted": 0, "unchanged": 0}

    # existing CRM rows for this source+owner
    existing_rows = (
        await db.execute(
            select(ProjectCalendarEvent).where(
                ProjectCalendarEvent.tenant_id == tenant_id,
                ProjectCalendarEvent.owner_user_id == user_id,
                ProjectCalendarEvent.source == source,
            )
        )
    ).scalars().all()

    by_ext_id: dict[str, ProjectCalendarEvent] = {}
    for row in existing_rows:
        if row.external_event_id:
            by_ext_id[row.external_event_id] = row

    seen: set[str] = set()

    for ev in remote:
        ext_id = ev.get("external_event_id", "")
        if not ext_id:
            continue
        seen.add(ext_id)
        remote_updated = ev.get("external_updated")

        existing = by_ext_id.get(ext_id)
        if existing is None:
            # Cross-source dedup: the same event can be mirrored by multiple
            # sources (e.g. Google Calendar imports the user's Outlook
            # calendar → identical event arrives via google_oauth AND outlook).
            # Match on identical (title, start, end) so we never store the
            # same event twice. Sync is mirror-check only — skipping insert
            # keeps the existing row authoritative.
            dup = (
                await db.execute(
                    select(ProjectCalendarEvent.id).where(
                        ProjectCalendarEvent.tenant_id == tenant_id,
                        ProjectCalendarEvent.owner_user_id == user_id,
                        ProjectCalendarEvent.title == ev["title"],
                        ProjectCalendarEvent.start == ev["start"],
                        ProjectCalendarEvent.end == ev["end"],
                        ProjectCalendarEvent.external_event_id.is_not(None),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if dup is not None:
                stats["unchanged"] += 1
                continue
            db.add(ProjectCalendarEvent(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                source=source,
                title=ev["title"],
                description=ev.get("description"),
                event_type=ev.get("event_type", "meeting"),
                start=ev["start"],
                end=ev["end"],
                is_all_day=ev.get("is_all_day", False),
                color=ev.get("color"),
                location=ev.get("location"),
                external_event_id=ext_id,
                external_updated=remote_updated,
            ))
            stats["inserted"] += 1
            continue

        # change detection: only update when remote is newer
        local_updated = existing.external_updated
        if (
            remote_updated is not None
            and local_updated is not None
            and remote_updated <= local_updated
        ):
            stats["unchanged"] += 1
            continue

        existing.title = ev["title"]
        existing.description = ev.get("description")
        existing.start = ev["start"]
        existing.end = ev["end"]
        existing.is_all_day = ev.get("is_all_day", False)
        existing.color = ev.get("color")
        existing.location = ev.get("location")
        existing.external_updated = remote_updated
        stats["updated"] += 1

    # delete remote rows that vanished (only source-scoped, external-sourced rows)
    for ext_id, row in by_ext_id.items():
        if ext_id not in seen:
            await db.delete(row)
            stats["deleted"] += 1

    return stats


def _configured_calendar_ids(config: dict | None) -> list[str]:
    """Resolve which Google calendars to mirror from the integration config.

    New format: calendar_ids = [list]. Legacy: calendar_id = single string.
    Default: ["primary"] — only the user's primary calendar.
    """
    cfg = config or {}
    ids = cfg.get("calendar_ids")
    if isinstance(ids, list) and ids:
        return [str(i) for i in ids]
    legacy = cfg.get("calendar_id")
    if legacy:
        return [str(legacy)]
    return ["primary"]


async def sync_google_oauth(
    db: AsyncSession,
    integration_row,
) -> dict[str, Any]:
    """Sync one google_calendar OAuth integration. Returns stats dict."""
    tenant_id = integration_row.tenant_id
    user_id = integration_row.user_id

    access_token, cfg_update = await _valid_access_token(integration_row)
    if cfg_update:
        integration_row.config = cfg_update

    calendar_ids = _configured_calendar_ids(integration_row.config)
    parsed: list[dict[str, Any]] = []
    for cal_id in calendar_ids:
        try:
            events = await _google_events(access_token, cal_id)
        except PermissionError:
            continue  # one calendar may be denied (e.g. shared calendar revoked) — skip it
        parsed.extend(_parse_google_event(ev, cal_id) for ev in events)

    stats = await _upsert_events(db, tenant_id, user_id, "google_oauth", parsed)
    return stats


async def sync_outlook_oauth(
    db: AsyncSession,
    integration_row,
) -> dict[str, Any]:
    """Sync one outlook_calendar OAuth integration. Returns stats dict."""
    tenant_id = integration_row.tenant_id
    user_id = integration_row.user_id

    access_token, cfg_update = await _valid_access_token(integration_row)
    if cfg_update:
        integration_row.config = cfg_update

    calendar_ids = _configured_calendar_ids(integration_row.config) or ["calendar"]
    parsed: list[dict[str, Any]] = []
    for cal_id in calendar_ids:
        try:
            events = await _outlook_events(access_token, cal_id)
        except PermissionError:
            continue  # one calendar may be denied (e.g. shared calendar revoked) — skip it
        parsed.extend(_parse_outlook_event(ev, cal_id) for ev in events)

    stats = await _upsert_events(db, tenant_id, user_id, "outlook_oauth", parsed)
    return stats


async def sync_ics(
    db: AsyncSession,
    integration_row,
) -> dict[str, Any]:
    """Sync one ICS-URL integration. Returns stats dict."""
    cfg = integration_row.config or {}
    url = cfg.get("connection_url") or cfg.get("ics_url") or ""
    if not url:
        raise RuntimeError("no ICS url configured")

    text = await _fetch_ics(url)
    parsed = _parse_ics(text)

    # window filter — only events in -14d/+60d are mirrored to CRM
    # (historical events from a full-archive feed must not flood the table)
    lo = _now() - timedelta(days=SYNC_PAST_DAYS)
    hi = _now() + timedelta(days=SYNC_FUTURE_DAYS)
    parsed = [e for e in parsed if lo <= _ensure_tz(e["start"]) <= hi]

    # Source tag: Outlook-hosted ICS feeds are tagged "outlook" (not "ics") so
    # the UI badge reads Outlook. Detect by URL host — outlook.office365.com /
    # outlook.live.com / outlook.com. Google-hosted and generic feeds stay "ics".
    source = "outlook" if _is_outlook_ics_url(url) else "ics"

    stats = await _upsert_events(
        db, integration_row.tenant_id, integration_row.user_id, source, parsed
    )
    return stats


async def sync_integration(
    db: AsyncSession,
    integration_row,
) -> dict[str, Any]:
    """Dispatch by provider/config — OAuth vs ICS."""
    if integration_row.provider == "google_calendar" and integration_row.config.get("access_token"):
        return await sync_google_oauth(db, integration_row)
    if integration_row.provider == "outlook_calendar" and integration_row.config.get("access_token"):
        return await sync_outlook_oauth(db, integration_row)
    if integration_row.provider in ("google_calendar", "ics", "ical"):
        return await sync_ics(db, integration_row)
    raise RuntimeError(f"unsupported calendar provider: {integration_row.provider}")


async def sync_user_calendars(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    force: bool = False,
) -> dict[str, Any]:
    """Sync all active calendar integrations for one user.

    `force=True` ignores the interval policy (used before briefing generation).
    Returns per-integration stats.
    """
    from app.models.integration import Integration

    rows = (
        await db.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.user_id == user_id,
                Integration.status == "active",
                Integration.provider.in_(["google_calendar", "outlook_calendar", "ics", "ical"]),
            )
        )
    ).scalars().all()

    results: dict[str, Any] = {}
    for row in rows:
        if not force and not await _due_for_sync(db, row, _now()):
            results[str(row.id)] = {"skipped": "not_due"}
            continue
        try:
            stats = await sync_integration(db, row)
            row.last_sync_at = _now()
            results[str(row.id)] = stats
        except Exception as e:  # noqa: BLE001 — never crash the caller
            results[str(row.id)] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    await db.flush()
    return results


async def sync_all_due(db: AsyncSession) -> dict[str, Any]:
    """Fan-out: sync every due calendar integration across all tenants.

    Called by cron. Quota-safe by design — each integration only syncs when
    its interval has elapsed (15 min active / 60 min inactive).
    """
    from app.models.integration import Integration

    rows = (
        await db.execute(
            select(Integration).where(
                Integration.status == "active",
                Integration.provider.in_(["google_calendar", "outlook_calendar", "ics", "ical"]),
            )
        )
    ).scalars().all()

    results: dict[str, Any] = {}
    for row in rows:
        if not await _due_for_sync(db, row, _now()):
            continue
        try:
            stats = await sync_integration(db, row)
            row.last_sync_at = _now()
            results[str(row.id)] = stats
        except Exception as e:  # noqa: BLE001
            results[str(row.id)] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    await db.flush()
    return results

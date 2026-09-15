"""Calendar sync cron job — mirror-check all due calendar integrations.

Run every 15 minutes via crontab. Quota-safe by design: each integration
only syncs when its interval elapsed (15 min active / 60 min inactive),
so 50k connected users stay well under Google's 10M req/day project quota.

Usage:
    python calendar_sync_job.py            # sync all due
    python calendar_sync_job.py --dry-run  # show what WOULD sync
"""
import asyncio
import sys
from pathlib import Path

# Allow running as script from backend/ dir
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import async_session  # noqa: E402


async def run(dry_run: bool = False) -> dict:
    from app.models.integration import Integration
    from app.services.calendar_sync import _due_for_sync, _now, sync_integration
    from sqlalchemy import select

    stats = {"scanned": 0, "synced": 0, "skipped": 0, "failed": 0, "details": []}
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Integration).where(
                    Integration.status == "active",
                    Integration.provider.in_(["google_calendar", "ics", "ical"]),
                )
            )
        ).scalars().all()
        stats["scanned"] = len(rows)
        for row in rows:
            if not await _due_for_sync(db, row, _now()):
                stats["skipped"] += 1
                continue
            if dry_run:
                stats["details"].append(f"{str(row.user_id)[:8]} {row.provider}: DUE (dry)")
                stats["synced"] += 1
                continue
            try:
                res = await sync_integration(db, row)
                row.last_sync_at = _now()
                stats["synced"] += 1
                stats["details"].append(
                    f"{str(row.user_id)[:8]} {row.provider}: "
                    f"ins={res.get('inserted', 0)} upd={res.get('updated', 0)} "
                    f"del={res.get('deleted', 0)} unch={res.get('unchanged', 0)}"
                )
            except Exception as e:  # noqa: BLE001
                stats["failed"] += 1
                stats["details"].append(f"{str(row.user_id)[:8]} {row.provider}: ERR {type(e).__name__}: {str(e)[:100]}")
        await db.commit()
    return stats


def main() -> None:
    dry = "--dry-run" in sys.argv
    stats = asyncio.run(run(dry_run=dry))
    print(f"calendar_sync {'(DRY)' if dry else ''}: {stats['scanned']} integrations, "
          f"{stats['synced']} due, {stats['skipped']} not-due, {stats['failed']} failed")
    for d in stats["details"][:30]:
        print(" ", d)
    if len(stats["details"]) > 30:
        print(f"  ... and {len(stats['details']) - 30} more")


if __name__ == "__main__":
    main()

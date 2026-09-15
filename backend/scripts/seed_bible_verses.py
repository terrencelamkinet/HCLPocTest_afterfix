"""Seed bible_verses with public-domain KJV scripture (subset).

Usage: source venv/bin/activate && python scripts/seed_bible_verses.py
Fetches a representative subset from bible-api.com (public domain KJV),
so the bible_reading module has real verse content. Full corpus can be
extended later — the module already falls back to pending_seed gracefully.
"""
import asyncio
import json
import re
import urllib.request

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import async_session, Base
from app.models.bible_reading import BibleVerse

# (book_zh, book_en, chapter) — 中文 reference 同 _resolve_passages_for_day 對齊
SEED_PASSAGES = [
    ("創世記", "Genesis", 1),
    ("創世記", "Genesis", 2),
    ("詩篇", "Psalms", 1),
    ("詩篇", "Psalms", 23),
    ("箴言", "Proverbs", 1),
    ("馬太福音", "Matthew", 1),
    ("馬太福音", "Matthew", 2),
    ("馬太福音", "Matthew", 5),
    ("馬可福音", "Mark", 1),
    ("路加福音", "Luke", 1),
    ("約翰福音", "John", 1),
    ("約翰福音", "John", 3),
    ("羅馬書", "Romans", 1),
    ("羅馬書", "Romans", 8),
    ("啟示錄", "Revelation", 1),
]


def fetch_kjv_chapter(book_en: str, chapter: int) -> dict:
    url = f"https://bible-api.com/{book_en}+{chapter}?translation=kjv"
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def zh_ref(book_zh: str, chapter: int, verse: int) -> str:
    return f"{book_zh} {chapter}:{verse}"


async def main() -> None:
    async with async_session() as db:
        existing = set((await db.execute(select(BibleVerse.reference))).scalars().all())
        added = 0
        for book_zh, book_en, ch in SEED_PASSAGES:
            try:
                data = fetch_kjv_chapter(book_en, ch)
            except Exception as exc:  # noqa: BLE001
                print(f"SKIP {book_en} {ch}: {exc}")
                continue
            rows = []
            for v in data.get("verses", []):
                ref = zh_ref(book_zh, ch, v["verse"])
                if ref in existing:
                    continue
                rows.append({
                    "translation": "kjv",
                    "reference": ref,
                    "book": book_zh,
                    "text": v["text"].strip(),
                })
            if not rows:
                print(f"  {book_zh} {ch}: all exist / empty")
                continue
            stmt = insert(BibleVerse).values(rows).on_conflict_do_nothing(
                index_elements=[BibleVerse.translation, BibleVerse.reference],
            )
            await db.execute(stmt)
            added += len(rows)
            print(f"  + {book_zh} {ch}: {len(rows)} verses")
        await db.commit()
        print(f"DONE — added {added} verses")


if __name__ == "__main__":
    asyncio.run(main())

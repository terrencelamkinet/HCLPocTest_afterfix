#!/usr/bin/env python3
"""
Seed Bible KJV full text into nexus_ai.bible_verses from bible-api.com
(public domain KJV, free, no API key).

Strategy:
  - Fetch chapter-by-chapter (1189 chapters) via bible-api.com
  - Batch INSERT (1000 rows per batch) using SQLAlchemy Core
  - Resume support: skip chapters already present in DB
  - Rate-limit: 0.3s between requests (~6 min total)

Usage:
  python3 seed_bible_kjv.py            # full run (resumable)
  python3 seed_bible_kjv.py --status   # show coverage per book
"""
import asyncio, json, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db import async_session

# 66 books in canonical order (KJV names as bible-api.com expects, lowercase url-safe)
BOOKS = [
    "genesis","exodus","leviticus","numbers","deuteronomy","joshua","judges","ruth",
    "1samuel","2samuel","1kings","2kings","1chronicles","2chronicles","ezra","nehemiah",
    "esther","job","psalms","proverbs","ecclesiastes","songofsolomon","isaiah","jeremiah",
    "lamentations","ezekiel","daniel","hosea","joel","amos","obadiah","jonah","micah",
    "nahum","habakkuk","zephaniah","haggai","zechariah","malachi",
    "matthew","mark","luke","john","acts","romans","1corinthians","2corinthians",
    "galatians","ephesians","philippians","colossians","1thessalonians","2thessalonians",
    "1timothy","2timothy","titus","philemon","hebrews","james","1peter","2peter",
    "1john","2john","3john","jude","revelation",
]

# book -> chapter count (KJV)
CHAPTER_COUNTS = {
    "genesis":50,"exodus":40,"leviticus":27,"numbers":36,"deuteronomy":34,"joshua":24,
    "judges":21,"ruth":4,"1samuel":31,"2samuel":24,"1kings":22,"2kings":25,
    "1chronicles":29,"2chronicles":36,"ezra":10,"nehemiah":13,"esther":10,"job":42,
    "psalms":150,"proverbs":31,"ecclesiastes":12,"songofsolomon":8,"isaiah":66,
    "jeremiah":52,"lamentations":5,"ezekiel":48,"daniel":12,"hosea":14,"joel":3,
    "amos":9,"obadiah":1,"jonah":4,"micah":7,"nahum":3,"habakkuk":3,"zephaniah":3,
    "haggai":2,"zechariah":14,"malachi":4,
    "matthew":28,"mark":16,"luke":24,"john":21,"acts":28,"romans":16,
    "1corinthians":16,"2corinthians":13,"galatians":6,"ephesians":6,"philippians":4,
    "colossians":4,"1thessalonians":5,"2thessalonians":3,"1timothy":6,"2timothy":4,
    "titus":3,"philemon":1,"hebrews":13,"james":5,"1peter":5,"2peter":3,"1john":5,
    "2john":1,"3john":1,"jude":1,"revelation":22,
}

DISPLAY_NAMES = {
    "genesis":"創世記","exodus":"出埃及記","leviticus":"利未記","numbers":"民數記",
    "deuteronomy":"申命記","joshua":"約書亞記","judges":"士師記","ruth":"路得記",
    "1samuel":"撒母耳記上","2samuel":"撒母耳記下","1kings":"列王紀上","2kings":"列王紀下",
    "1chronicles":"歷代志上","2chronicles":"歷代志下","ezra":"以斯拉記","nehemiah":"尼希米記",
    "esther":"以斯帖記","job":"約伯記","psalms":"詩篇","proverbs":"箴言",
    "ecclesiastes":"傳道書","songofsolomon":"雅歌","isaiah":"以賽亞書","jeremiah":"耶利米書",
    "lamentations":"耶利米哀歌","ezekiel":"以西結書","daniel":"但以理書","hosea":"何西阿書",
    "joel":"約珥書","amos":"阿摩司書","obadiah":"俄巴底亞書","jonah":"約拿書",
    "micah":"彌迦書","nahum":"那鴻書","habakkuk":"哈巴谷書","zephaniah":"西番雅書",
    "haggai":"哈該書","zechariah":"撒迦利亞書","malachi":"瑪拉基書",
    "matthew":"馬太福音","mark":"馬可福音","luke":"路加福音","john":"約翰福音",
    "acts":"使徒行傳","romans":"羅馬書","1corinthians":"哥林多前書",
    "2corinthians":"哥林多後書","galatians":"加拉太書","ephesians":"以弗所書",
    "philippians":"腓立比書","colossians":"歌羅西書","1thessalonians":"帖撒羅尼迦前書",
    "2thessalonians":"帖撒羅尼迦後書","1timothy":"提摩太前書","2timothy":"提摩太後書",
    "titus":"提多書","philemon":"腓利門書","hebrews":"希伯來書","james":"雅各書",
    "1peter":"彼得前書","2peter":"彼得後書","1john":"約翰一書","2john":"約翰二書",
    "3john":"約翰三書","jude":"猶大書","revelation":"啟示錄",
}

KJV_JSON_URL = "https://raw.githubusercontent.com/thiagobodruk/bible/master/json/en_kjv.json"
KJV_JSON_CACHE = "/tmp/kjv_full.json"


def load_kjv_json() -> list[dict]:
    """Download (once) the full KJV JSON — 66 books, [abbrev, name, chapters[][]verse_text]."""
    if not Path(KJV_JSON_CACHE).exists():
        import urllib.request as _ur
        print(f"Downloading KJV full text from GitHub ({KJV_JSON_URL})...", flush=True)
        _ur.request.urlretrieve(KJV_JSON_URL, KJV_JSON_CACHE)
    with open(KJV_JSON_CACHE, encoding="utf-8-sig") as f:
        return json.load(f)


async def get_existing(book_cn: str) -> set[int]:
    """Chapters already present for a book (by display name)."""
    async with async_session() as db:
        rows = (await db.execute(
            text("SELECT DISTINCT reference FROM nexus_ai.bible_verses WHERE book = :b AND translation = 'kjv'"),
            {"b": book_cn},
        )).fetchall()
    out = set()
    for (ref,) in rows:
        # ref format: 創世記 1:1  or  詩篇 23:1
        try:
            ch = int(ref.split(" ")[-1].split(":")[0])
            out.add(ch)
        except (ValueError, IndexError):
            continue
    return out


async def seed() -> None:
    total_verses = 0
    new_chapters = 0
    start_t = time.time()
    kjv = load_kjv_json()
    # index: english name → {chapters: [[verse_text...], ...]}
    kjv_index = {b["name"].lower(): b for b in kjv}
    async with async_session() as db:
        for book in BOOKS:
            book_cn = DISPLAY_NAMES[book]
            existing = await get_existing(book_cn)
            src = kjv_index.get(book) or kjv_index.get(book.replace("1", "1 ").replace("2", "2 ").replace("3", "3 "))
            n_ch = len(src["chapters"]) if src else CHAPTER_COUNTS[book]
            done_ch = len(existing)
            print(f"[{book_cn}] {done_ch}/{n_ch} chapters in DB", flush=True)
            batch = []
            for ch_idx in range(1, n_ch + 1):
                if ch_idx in existing:
                    continue
                if src is None or ch_idx > len(src["chapters"]):
                    continue
                verses = src["chapters"][ch_idx - 1]
                for v_no, v_text in enumerate(verses, start=1):
                    batch.append({
                        "translation": "kjv",
                        "reference": f"{book_cn} {ch_idx}:{v_no}",
                        "book": book_cn,
                        "text": v_text.strip(),
                    })
                total_verses += len(verses)
                new_chapters += 1
                if len(batch) >= 1000:
                    await db.execute(text("""
                        INSERT INTO nexus_ai.bible_verses (translation, reference, book, text)
                        VALUES (:translation, :reference, :book, :text)
                    """), batch)
                    await db.commit()
                    batch = []
                    print(f"  ✓ flushed {new_chapters} chapters / {total_verses} verses", flush=True)
            if batch:
                await db.execute(text("""
                    INSERT INTO nexus_ai.bible_verses (translation, reference, book, text)
                    VALUES (:translation, :reference, :book, :text)
                """), batch)
                await db.commit()
            print(f"  ✓ {book_cn} done ({total_verses} verses total)", flush=True)
    elapsed = time.time() - start_t
    print(f"\n✅ SEED COMPLETE: {total_verses} verses, {new_chapters} new chapters, {elapsed:.0f}s")


async def status() -> None:
    async with async_session() as db:
        rows = (await db.execute(text(
            "SELECT book, count(*) FROM nexus_ai.bible_verses WHERE translation='kjv' GROUP BY book ORDER BY book"
        ))).fetchall()
    total = sum(r[1] for r in rows)
    print(f"KJV coverage: {total}/31102 verses across {len(rows)} books")
    for book, cnt in rows:
        print(f"  {book}: {cnt}")


if __name__ == "__main__":
    if "--status" in sys.argv:
        asyncio.run(status())
    else:
        asyncio.run(seed())

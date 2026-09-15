#!/usr/bin/env python3
"""
Seed Bible translations into nexus_ai.bible_verses.

Translations supported:
  - kjv   (English KJV, public domain)   — thiagobodruk/bible en_kjv.json
  - cuv   (和合本 繁體, public domain)    — thiagobodruk/bible zh_cuv.json
  - cuvmp (和合本修訂版, simplified)      — yilliot/cuvmps (per-book md files)
                                          → zhconv → 繁體

Usage:
  python3 seed_bible.py --translation kjv|cuv|cuvmp [--status]
"""
import asyncio, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from app.db import async_session

try:
    import zhconv
except ImportError:
    zhconv = None

CACHE_DIR = Path("/tmp/bible_seed")
CACHE_DIR.mkdir(exist_ok=True)

# ── Source definitions ──
SOURCES = {
    "kjv": {
        "url": "https://raw.githubusercontent.com/thiagobodruk/bible/master/json/en_kjv.json",
        "file": CACHE_DIR / "en_kjv.json",
        "cn_book_names": None,  # use english names as reference
        "spacey": False,
        "convert_trad": False,
    },
    "cuv": {
        "url": "https://raw.githubusercontent.com/thiagobodruk/bible/master/json/zh_cuv.json",
        "file": CACHE_DIR / "zh_cuv.json",
        "cn_book_names": None,  # book names in JSON are english; ref uses cn names below
        "spacey": True,  # zh_cuv has spaces between every char — must strip
        "convert_trad": False,
    },
}

# Chinese book display names (canonical order, used for reference + book column)
CN_BOOKS = [
    "創世記","出埃及記","利未記","民數記","申命記","約書亞記","士師記","路得記",
    "撒母耳記上","撒母耳記下","列王紀上","列王紀下","歷代志上","歷代志下","以斯拉記",
    "尼希米記","以斯帖記","約伯記","詩篇","箴言","傳道書","雅歌","以賽亞書","耶利米書",
    "耶利米哀歌","以西結書","但以理書","何西阿書","約珥書","阿摩司書","俄巴底亞書",
    "約拿書","彌迦書","那鴻書","哈巴谷書","西番雅書","哈該書","撒迦利亞書","瑪拉基書",
    "馬太福音","馬可福音","路加福音","約翰福音","使徒行傳","羅馬書","哥林多前書",
    "哥林多後書","加拉太書","以弗所書","腓立比書","歌羅西書","帖撒羅尼迦前書",
    "帖撒羅尼迦後書","提摩太前書","提摩太後書","提多書","腓利門書","希伯來書","雅各書",
    "彼得前書","彼得後書","約翰一書","約翰二書","約翰三書","猶大書","啟示錄",
]

# English book names as they appear in thiagobodruk JSON (lowercase)
EN_BOOKS = [
    "genesis","exodus","leviticus","numbers","deuteronomy","joshua","judges","ruth",
    "1 samuel","2 samuel","1 kings","2 kings","1 chronicles","2 chronicles","ezra",
    "nehemiah","esther","job","psalms","proverbs","ecclesiastes","song of solomon",
    "isaiah","jeremiah","lamentations","ezekiel","daniel","hosea","joel","amos",
    "obadiah","jonah","micah","nahum","habakkuk","zephaniah","haggai","zechariah",
    "malachi","matthew","mark","luke","john","acts","romans","1 corinthians",
    "2 corinthians","galatians","ephesians","philippians","colossians","1 thessalonians",
    "2 thessalonians","1 timothy","2 timothy","titus","philemon","hebrews","james",
    "1 peter","2 peter","1 john","2 john","3 john","jude","revelation",
]


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"  (cached) {dest.name}")
        return
    print(f"  downloading {url} ...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "nexus-crm-seed/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())
    print(f"  saved {dest.stat().st_size/1e6:.1f} MB", flush=True)


def load_thiago_json(translation: str) -> dict[str, dict]:
    """Returns {en_book_lower: {'cn': cn_name, 'chapters': [[verse...]]}}"""
    src = SOURCES[translation]
    download(src["url"], src["file"])
    with open(src["file"], encoding="utf-8-sig") as f:
        data = json.load(f)
    out = {}
    for i, book in enumerate(data):
        en = book["name"].lower()
        out[en] = {
            "cn": CN_BOOKS[i],
            "chapters": book["chapters"],
            "spacey": src["spacey"],
        }
    return out


def load_cuvmp() -> dict[str, dict]:
    """yilliot/cuvmps — per-book dirs of md files: 01_创世记_001 etc."""
    if zhconv is None:
        print("❌ zhconv not installed — cannot convert cuvmp simplified→traditional")
        return {}
    base = "https://raw.githubusercontent.com/yilliot/cuvmps/master"
    out = {}
    # book dirs 01..66
    for i, cn in enumerate(CN_BOOKS, start=1):
        dir_name = f"{i:02d}_{cn}" if i <= 39 else f"{i:02d}_{cn}"
        # get file list via git trees API (once)
    # fetch tree
    tree_url = "https://api.github.com/repos/yilliot/cuvmps/git/trees/master?recursive=1"
    req = urllib.request.Request(tree_url, headers={"User-Agent": "nexus-crm-seed/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        tree = json.loads(r.read())["tree"]
    files = [t["path"] for t in tree if t["type"] == "blob" and re.search(r"/\d+_", t["path"])]
    # group by book dir
    by_book: dict[int, list[str]] = {}
    for fp in files:
        parts = fp.split("/")
        if len(parts) != 2:
            continue
        try:
            book_idx = int(parts[0][:2])
        except ValueError:
            continue
        by_book.setdefault(book_idx, []).append(fp)
    for idx in sorted(by_book):
        cn = CN_BOOKS[idx - 1]
        files_list = sorted(by_book[idx], key=lambda p: int(re.search(r"_(\d+)$", p).group(1)))
        chapters = []
        for fp in files_list:
            url = f"{base}/{fp}"
            req = urllib.request.Request(urllib.parse.quote(url, safe="/:?&=%"), headers={"User-Agent": "nexus-crm-seed/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                md = r.read().decode("utf-8")
            verses = _parse_cuvmp_md(md)
            chapters.append(verses)
            time.sleep(0.1)
        out[cn] = {"cn": cn, "chapters": chapters, "spacey": False}
        print(f"  ✓ {cn}: {len(chapters)} chapters", flush=True)
    return out


def _parse_cuvmp_md(md: str) -> list[str]:
    """md format: lines '1 起初，神创造天地。' — convert to 繁體 via zhconv."""
    verses = []
    for line in md.splitlines():
        line = line.strip()
        m = re.match(r"^(\d+)\s+(.+)$", line)
        if m:
            text = m.group(2).strip()
            if zhconv:
                text = zhconv.convert(text, "cn2tw")
            verses.append(text)
    return verses


async def get_existing_chapters(translation: str, book_cn: str) -> set[int]:
    async with async_session() as db:
        rows = (await db.execute(
            text("SELECT DISTINCT reference FROM nexus_ai.bible_verses WHERE book = :b AND translation = :t"),
            {"b": book_cn, "t": translation},
        )).fetchall()
    out = set()
    for (ref,) in rows:
        try:
            out.add(int(ref.split(" ")[-1].split(":")[0]))
        except (ValueError, IndexError):
            continue
    return out


def clean_text(t: str, spacey: bool) -> str:
    t = t.strip()
    if spacey:
        t = re.sub(r"\s+", "", t)  # remove all spaces (zh_cuv has char-spacing)
    return t


async def seed(translation: str) -> None:
    print(f"=== Seeding translation: {translation} ===")
    if translation in ("kjv", "cuv"):
        data = load_thiago_json(translation)
        # key by english name
        books = []
        for en in EN_BOOKS:
            if en in data:
                books.append(data[en])
    elif translation == "cuvmp":
        books = list(load_cuvmp().values())
    else:
        print(f"❌ Unknown translation: {translation}")
        return

    total_verses = 0
    new_chapters = 0
    start_t = time.time()
    async with async_session() as db:
        for book in books:
            cn = book["cn"]
            existing = await get_existing_chapters(translation, cn)
            n_ch = len(book["chapters"])
            print(f"[{cn}] {len(existing)}/{n_ch} chapters in DB", flush=True)
            batch = []
            for ch_idx in range(1, n_ch + 1):
                if ch_idx in existing:
                    continue
                verses = book["chapters"][ch_idx - 1]
                for v_no, v_text in enumerate(verses, start=1):
                    txt = clean_text(v_text, book.get("spacey", False))
                    if not txt:
                        continue
                    batch.append({
                        "translation": translation,
                        "reference": f"{cn} {ch_idx}:{v_no}",
                        "book": cn,
                        "text": txt,
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
            if batch:
                await db.execute(text("""
                    INSERT INTO nexus_ai.bible_verses (translation, reference, book, text)
                    VALUES (:translation, :reference, :book, :text)
                """), batch)
                await db.commit()
            print(f"  ✓ {cn} done ({total_verses} verses total)", flush=True)
    elapsed = time.time() - start_t
    print(f"\n✅ {translation} SEED COMPLETE: {total_verses} verses, {new_chapters} new chapters, {elapsed:.0f}s")


async def status() -> None:
    async with async_session() as db:
        rows = (await db.execute(text(
            "SELECT translation, book, count(*) FROM nexus_ai.bible_verses GROUP BY translation, book ORDER BY translation, book"
        ))).fetchall()
    by_t = {}
    for t, b, c in rows:
        by_t.setdefault(t, []).append((b, c))
    for t, items in by_t.items():
        total = sum(c for _, c in items)
        print(f"{t}: {total} verses / {len(items)} books")
        missing = [b for b in CN_BOOKS if b not in dict(items)]
        if missing:
            print(f"  missing books: {missing}")


if __name__ == "__main__":
    if "--status" in sys.argv:
        asyncio.run(status())
    else:
        trans = "cuvmp"
        for a in sys.argv:
            if a.startswith("--translation"):
                trans = a.split("=")[1] if "=" in a else sys.argv[sys.argv.index(a) + 1]
        asyncio.run(seed(trans))

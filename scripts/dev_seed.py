#!/usr/bin/env python3
import re
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

try:
    from database import db as _db
except Exception:
    _db = None  # type: ignore

SNIPPETS_MD = Path(__file__).resolve().parent.parent / 'SNIPPETS.md'

def parse_snippets(md_text: str):
    # Very simple parser: find ```lang ... ``` blocks, use preceding '### ' as title when available
    blocks = []
    pattern = re.compile(r"^```(\w+)?\n([\s\S]*?)\n```", re.MULTILINE)
    titles = {}
    # Build map of line number -> title
    lines = md_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('### '):
            titles[i] = line[4:].strip()
    for m in pattern.finditer(md_text):
        lang = (m.group(1) or 'text').strip()
        code = m.group(2)
        start_idx = md_text[:m.start()].count('\n')
        # find nearest preceding title within 5 lines
        title = None
        for j in range(start_idx, max(-1, start_idx - 12), -1):
            if j in titles:
                title = titles[j]
                break
        if not title:
            title = f"Snippet {len(blocks)+1} ({lang})"
        desc = "Seeded from SNIPPETS.md"
        blocks.append({
            'title': title[:180],
            'description': desc,
            'code': code,
            'language': lang[:40],
        })
    return blocks


def _is_local_mongo() -> bool:
    """Best-effort safety: אל תזרע בדפולט ב-DB שאינו לוקאלי.

    מותר לעקוף עם --force או ALLOW_SEED_NON_LOCAL=1.
    """
    url = os.getenv('MONGODB_URL', '')
    if not url:
        # אין URL – נניח סביבת DEV (DatabaseManager עלול להיות noop)
        return True
    u = url.strip().lower()
    return ('localhost' in u) or ('127.0.0.1' in u)


def seed():
    if _db is None or getattr(_db, 'snippets_collection', None) is None:
        print('DB unavailable; skipping seed')
        return
    # Safety guard: require local DB unless forced
    forced = ('--force' in sys.argv) or (os.getenv('ALLOW_SEED_NON_LOCAL', '').strip() in {'1', 'true', 'yes'})
    if not _is_local_mongo() and not forced:
        print('Refusing to seed non-local MongoDB. Re-run with --force or ALLOW_SEED_NON_LOCAL=1')
        return

    text = SNIPPETS_MD.read_text(encoding='utf-8')
    items = parse_snippets(text)
    coll = _db.snippets_collection
    inserted = 0
    for it in items:
        # Idempotent upsert by (title, language) with a seed flag
        coll.update_one(
            {'title': it['title'], 'language': it['language']},
            {'$setOnInsert': {
                'description': it['description'],
                'code': it['code'],
                'status': 'approved',
                'submitted_at': datetime.now(timezone.utc),
                'approved_at': datetime.now(timezone.utc),
                'approved_by': 0,
                'user_id': 0,
            }},
            upsert=True,
        )
        inserted += 1
    print(f'Seed processed {inserted} snippets (idempotent upsert).')
    # סגירת חיבור ה-Mongo כדי למנוע ResourceWarning בסביבות CLI
    try:
        if hasattr(_db, 'close_connection'):
            _db.close_connection()  # type: ignore[attr-defined]
    except Exception:
        pass


if __name__ == '__main__':
    seed()

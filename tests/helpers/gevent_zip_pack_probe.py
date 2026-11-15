"""עוזר לטסט: מודד אם אריזת תיקייה מגיטהאב עוצרת את לולאת הבוט — תחת gevent, בתת-תהליך.

⚠️ הקובץ הזה עושה ``monkey.patch_all()`` בזמן ייבוא, ולכן הוא יושב ב-``tests/helpers``
ולא ישירות תחת ``tests/``: אסור שיתגלה או ייובא בטעות לתוך תהליך ה-pytest.

למה תת-תהליך: ``conftest.py`` מגדיר ``CODEBOT_DISABLE_GEVENT_PATCH=1``, כלומר ה-monkey
patching של gevent **מכובה בכל סוויטת הטסטים**. בלי patching, ``asyncio.to_thread``
רץ בחוט אמיתי ואי אפשר לראות את הבעיה. תהליך הבוט בפרודקשן מריץ ``patch_all()``
(``main.py``), ואחריו ``to_thread`` הוא גרינלט באותו OS thread, ועבודת CPU בו עוצרת
את הלולאה.

**מה נמדד:** משימה ברקע מתקתקת על הלולאה כל ``TICK_SECONDS``, ובזמן הזה
``GitHubMenuHandler._pack_folder_from_archive`` — הפונקציה האמיתית שהבוט קורא לה —
אורזת תיקייה ב-``asyncio.to_thread``, כמו ב-``_zip_folder_job``. הפער הגדול בין שני
תקתוקים הוא כמה זמן הלולאה עמדה. הארכיון גדול מספיק כדי שהדחיסה תיקח זמן נמדד.

הפלט: שורת JSON יחידה עם ``pack_seconds``, ``max_gap`` ו-``ticks``.
"""

from __future__ import annotations

# חייב להיות ראשון, לפני כל ייבוא של ספריות סטנדרטיות.
from gevent import monkey

monkey.patch_all()

import asyncio  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import zipfile  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017/probe")
os.environ.setdefault("BOT_TOKEN", "0:probe")
os.environ.setdefault("DISABLE_DB", "1")

import github_menu_handler as gh  # noqa: E402

TICK_SECONDS = 0.02
#: מספר הקבצים וגודלם. נבחרו כך שהדחיסה ב-``compresslevel=9`` תיקח עשיריות שנייה
#: לפחות (מתחת לתקרות של ``github_menu_handler``), ולכן עצירה של הלולאה בזמנה בולטת
#: מול מרווח התקתוק.
FILES = 4
FILE_BYTES = 500_000


def _build_archive(path: str) -> None:
    """zipball במבנה של GitHub: תיקיית שורש אחת, ובתוכה ``pack/`` עם קבצי טקסט."""
    rnd = random.Random(1234)
    words = [f"word{i}" for i in range(5000)]
    root = "o-r-abc1234"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        z.writestr(f"{root}/", b"")
        z.writestr(f"{root}/pack/", b"")
        for i in range(FILES):
            buf = io.StringIO()
            while buf.tell() < FILE_BYTES:
                buf.write(" ".join(rnd.choice(words) for _ in range(20)))
                buf.write("\n")
            z.writestr(f"{root}/pack/file{i}.txt", buf.getvalue().encode("utf-8"))


async def _ticker(stop: asyncio.Event, gaps: list) -> None:
    last = time.monotonic()
    while not stop.is_set():
        await asyncio.sleep(TICK_SECONDS)
        now = time.monotonic()
        gaps.append(now - last)
        last = now


async def _measure(workdir: str) -> dict:
    archive = os.path.join(workdir, "archive.zip")
    _build_archive(archive)
    stop, gaps = asyncio.Event(), []
    ticker = asyncio.create_task(_ticker(stop, gaps))
    await asyncio.sleep(0.1)
    started = time.monotonic()
    stats = await asyncio.to_thread(
        gh.GitHubMenuHandler._pack_folder_from_archive,
        archive,
        "pack",
        os.path.join(workdir, "packed.zip"),
        deadline_ts=time.monotonic() + 120,
    )
    pack_seconds = time.monotonic() - started
    stop.set()
    await ticker
    return {
        "patched": monkey.is_module_patched("threading"),
        "files": stats["total_files"],
        "pack_seconds": pack_seconds,
        "max_gap": max(gaps),
        "ticks": len(gaps),
    }


def main() -> None:
    # תיקיית העבודה מגיעה מהטסט (``tmp_path``), כדי שכל הקבצים יישארו בתיקייה שלו
    if len(sys.argv) != 2 or not sys.argv[1] or not os.path.isdir(sys.argv[1]):
        sys.exit("usage: gevent_zip_pack_probe.py <existing work dir>")
    result = asyncio.run(_measure(sys.argv[1]))
    print(json.dumps(result))


if __name__ == "__main__":
    main()

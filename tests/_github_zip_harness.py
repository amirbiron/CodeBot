"""עזרים משותפים לטסטים של הורדת ZIP מגיטהאב (``download_zip:``).

ההורדה רצה כמשימת רקע (``GitHubMenuHandler._start_zip_job``): ה-handler קורא
ל-``context.application.create_task`` וחוזר מיד. טסט שמפעיל את ה-handler
צריך לכן ``application`` מדומה, ולחכות למשימה לפני שהוא בודק תוצאה —
``FakeApplication.drain``.

והארכיון מגיע כ-zipball אחד של כל הריפו. ``zipball_bytes`` בונה ארכיון באותו
מבנה שנמדד על zipball אמיתי של הריפו הזה: תיקיית שורש אחת
``{owner}-{repo}-{sha}/``, רשומת תיקייה לכל תיקייה, קבצים עם
``create_system == 0``, וקישורים סימבוליים עם ``create_system == 3`` ו-mode
``0o120777`` שתוכנם הוא יעד הקישור.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from typing import Dict, Iterable, Optional

ZIPBALL_ROOT = "o-r-abc1234"


class FakeApplication:
    """מחליף את ``telegram.ext.Application`` לצורך ``create_task`` בלבד.

    ``Application.create_task`` של PTB מריץ את הקורוטינה כמשימה, מעביר חריגה
    ל-``process_error`` וזורק אותה שוב על המשימה. כאן אין error handlers, ולכן
    החריגה פשוט נשארת על המשימה — ו-``drain`` זורק אותה, כדי שבאג במשימה יפיל
    את הטסט ולא ייבלע.
    """

    def __init__(self) -> None:
        self.tasks: list[asyncio.Task] = []
        self.task_names: list[Optional[str]] = []

    def create_task(self, coroutine, update=None, *, name=None):
        task = asyncio.ensure_future(coroutine)
        self.tasks.append(task)
        self.task_names.append(name)
        return task

    async def drain(self, timeout: float = 5.0) -> None:
        """מחכה שכל המשימות שנוצרו עד עכשיו יסתיימו, ואז זורק את הכשל הראשון אם היה.

        ``return_exceptions=True`` כדי שכשל של משימה אחת לא יחזיר שליטה לטסט בזמן
        שמשימה אחרת עוד רצה — אז היא הייתה ממשיכה אחרי סוף הטסט. הכשל לא נבלע: הוא
        נזרק אחרי שכולן הסתיימו, גם בקריאה חוזרת ל-``drain``.
        """
        if not self.tasks:
            return
        results = await asyncio.wait_for(asyncio.gather(*self.tasks, return_exceptions=True), timeout=timeout)
        for result in results:
            if isinstance(result, BaseException):
                raise result


def make_context(**extra):
    """``CallbackContext`` מינימלי: ``user_data``, ``bot_data`` ו-``application``."""
    import types

    ctx = types.SimpleNamespace(user_data={}, bot_data={}, application=FakeApplication())
    for key, value in extra.items():
        setattr(ctx, key, value)
    return ctx


def zipball_bytes(
    files: Dict[str, bytes],
    *,
    root: str = ZIPBALL_ROOT,
    symlinks: Optional[Dict[str, str]] = None,
    executables: Iterable[str] = (),
) -> bytes:
    """בונה zipball במבנה של GitHub. ``files`` ממפה נתיב יחסי לשורש הריפו לתוכן."""
    executables = set(executables)
    symlinks = symlinks or {}
    dirs = {""}
    for path in list(files) + list(symlinks):
        parts = path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for d in sorted(dirs):
            name = f"{root}/{d}/" if d else f"{root}/"
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 15, 12, 0, 0))
            info.create_system = 0
            z.writestr(info, b"")
        for path, data in files.items():
            info = zipfile.ZipInfo(f"{root}/{path}", date_time=(2026, 11, 15, 12, 0, 0))
            if path in executables:
                info.create_system = 3
                info.external_attr = 0o100755 << 16
            else:
                info.create_system = 0
                info.external_attr = 0
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
        for path, target in symlinks.items():
            info = zipfile.ZipInfo(f"{root}/{path}", date_time=(2026, 11, 15, 12, 0, 0))
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            z.writestr(info, target.encode("utf-8"))
    return buf.getvalue()


class FakeArchiveResponse:
    """תשובת ``requests`` בהזרמה: ``iter_content``, ``headers``, ``close``.

    כמו codeload של GitHub, בלי ``Content-Length`` כברירת מחדל (נמדד).
    """

    def __init__(self, content: bytes, *, content_length: Optional[int] = None, status_error: Exception = None):
        self._content = content
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}
        self._status_error = status_error
        self.closed = False

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def iter_content(self, chunk_size=131072):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]

    def close(self):
        self.closed = True


class FakeArchiveRepo:
    """ריפו מזויף שמגיש zipball. רושם את ה-ref שכל בקשת ארכיון ביקשה.

    ``archives`` ממפה שם ענף ל-bytes של zipball. בקשה בלי ref מקבלת את הארכיון
    של ``default_branch``, כמו ב-GitHub.
    """

    def __init__(self, archives: Dict[Optional[str], bytes], *, name="r", full_name="o/r", default_branch="main"):
        self.name = name
        self.full_name = full_name
        self.default_branch = default_branch
        self.archives = archives
        self.archive_refs: list[Optional[str]] = []

    def get_archive_link(self, archive_format, ref=None):
        assert archive_format == "zipball"
        self.archive_refs.append(ref)
        return f"https://codeload.example/{self.full_name}/legacy.zip/{ref or 'HEAD'}"

    def get_contents(self, path="", ref=None):
        """לדפדפן הריפו שמוצג אחרי שמירה (``show_repo_browser``). האריזה לא משתמשת בו."""
        return []

    def archive_for_url(self, url: str) -> bytes:
        # כל מה שאחרי ``/legacy.zip/`` הוא ה-ref, כולל ``/`` שבתוכו (``feature/x``)
        marker = "/legacy.zip/"
        assert marker in url, url
        ref = url.split(marker, 1)[1]
        # בלי ref GitHub מחזיר את ענף ברירת המחדל (תיעוד ה-REST של zipball:
        # "If you omit :ref, the repository's default branch (usually main) will be used")
        key = self.default_branch if ref == "HEAD" else ref
        return self.archives[key]


def install_archive_http(monkeypatch, gh, repo: FakeArchiveRepo, responses: Optional[list] = None):
    """מחווט את ``gh.http_request`` להגיש את ה-zipball של ``repo``. מחזיר את רשימת התשובות."""
    responses = responses if responses is not None else []

    def _http_request(method, url, **kwargs):
        assert method == "GET"
        resp = FakeArchiveResponse(repo.archive_for_url(url))
        # הארגומנטים של הבקשה נשמרים, כדי שטסט יבדוק timeouts ו-retry
        resp.request_kwargs = kwargs
        responses.append(resp)
        return resp

    monkeypatch.setattr(gh, "http_request", _http_request)
    return responses

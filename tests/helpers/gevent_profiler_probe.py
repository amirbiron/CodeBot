"""עוזר לטסט: מריץ את ראוט הפרופיילר האמיתי תחת gevent, בתת-תהליך.

⚠️ הקובץ הזה עושה ``monkey.patch_all()`` בזמן ייבוא, ולכן הוא יושב ב-``tests/helpers``
ולא ישירות תחת ``tests/``: אסור שיתגלה או ייובא בטעות לתוך תהליך ה-pytest.

למה תת-תהליך: ``conftest.py`` מגדיר ``CODEBOT_DISABLE_GEVENT_PATCH=1``, כלומר
ה-monkey patching של gevent **מכובה בכל סוויטת הטסטים**. בלי זה אי אפשר לשחזר
את הבאג בכלל, כי הוא נובע בדיוק מכך שגרינלטים חולקים OS thread אחד.

**מה נבדק כאן, וזה העיקר:** הפרוב מייבא את אפליקציית ה-Flask **האמיתית** מ-
``webapp/app.py`` ופונה ל-``/api/profiler/slow-queries`` — הראוט שבו ישבה
המעטפת ``_run_awaitable_blocking`` שהוסרה. גרסה מוקדמת של הקובץ הזה הגדירה ראוט
משלה שקרא לשירות ישירות; היא עקפה בדיוק את הקוד שהכיל את הבאג, ולכן לא הבחינה
בין הקוד התקין לשבור. עכשיו נבדק ה-stack המלא: ראוט ← אימות ← שירות ← סריאליזציה.

התהליך מדמה את הפרודקשן: gunicorn עם ``worker_class=gevent`` מריץ
``gevent.pywsgi.WSGIServer`` (מקור: gunicorn/workers/ggevent.py), עם worker יחיד
(``WEB_CONCURRENCY=1``).

הפלט: שורת JSON יחידה עם קודי הסטטוס.
"""

from __future__ import annotations

# חייב להיות ראשון, לפני כל ייבוא של ספריות סטנדרטיות.
from gevent import monkey

monkey.patch_all()

import asyncio  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

#: הפרופיילר בפרודקשן נפתח על ידי אדמין מחובר מהדפדפן, ולכן הפרוב מתחזה בדיוק לזה:
#: ``_profiler_is_authorized`` (``webapp/app.py``) מאשר רק ``session["user_id"]`` שהוא אדמין —
#: ``X-Profiler-Token`` לבדו אינו מספיק שם (ראו ההערה בתיאור ה-PR).
#: ``is_admin`` (``user_roles.py:34``) קורא את ``ADMIN_USER_IDS`` בזמן ריצה.
ADMIN_USER_ID = 1
os.environ.setdefault("ADMIN_USER_IDS", str(ADMIN_USER_ID))
os.environ.setdefault("MONGODB_URL", "mongodb://localhost:27017/probe")
os.environ.setdefault("BOT_TOKEN", "0:probe")
os.environ.setdefault("DISABLE_DB", "1")
os.environ.setdefault("SECRET_KEY", "probe-secret")

import gevent  # noqa: E402
from gevent.pywsgi import WSGIServer  # noqa: E402

from flask.sessions import SecureCookieSessionInterface  # noqa: E402

from services.query_profiler_service import (  # noqa: E402
    PersistentQueryProfilerService,
)
from webapp import app as webapp_app  # noqa: E402

#: כמה זמן כל "שאילתה" נמשכת. תחת gevent ``time.sleep`` הוא yield קואופרטיבי,
#: בדיוק כמו I/O של pymongo — וזה מה שגורם לבקשות לחפוף.
QUERY_SECONDS = 0.4


#: הסטאב חייב לשקף את החוזה של השירות **בעץ שעליו הפרוב רץ**, אחרת הבדיקה
#: מאבדת את היכולת להיכשל: על הקוד הישן ``get_slow_queries`` הייתה ``async def``,
#: והמעטפת ``_run_awaitable_blocking`` היא שפתחה את הלולאה. סטאב סינכרוני שם היה
#: מחזיר רשימה רגילה, המעטפת לא הייתה פותחת לולאה בכלל, והפרוב היה עובר על קוד שבור.
_SERVICE_IS_ASYNC = inspect.iscoroutinefunction(
    getattr(PersistentQueryProfilerService, "get_slow_queries", None)
)


class _SyncStubProfilerService:
    """מחזיר את מה שהראוט מצפה לו, אחרי השהיה שמדמה I/O של מונגו."""

    def get_slow_queries(self, **kwargs):
        time.sleep(QUERY_SECONDS)
        return []


class _AsyncStubProfilerService:
    """אותו דבר, בחוזה האסינכרוני של הקוד שלפני התיקון."""

    async def get_slow_queries(self, **kwargs):
        await asyncio.sleep(QUERY_SECONDS)
        return []


def main() -> int:
    concurrency = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    # דורסים את ה-service הגלובלי כדי שהראוט לא ייגע במונגו. הראוט עצמו,
    # האימות והסריאליזציה — כולם הקוד האמיתי.
    webapp_app._WEBAPP_PROFILER_SERVICE = (
        _AsyncStubProfilerService() if _SERVICE_IS_ASYNC else _SyncStubProfilerService()
    )

    # עוגיית session חתומה במפתח של האפליקציה עצמה — בדיוק מה שהדפדפן שולח.
    interface = SecureCookieSessionInterface()
    serializer = interface.get_signing_serializer(webapp_app.app)
    if serializer is None:  # pragma: no cover - רק אם אין SECRET_KEY
        raise RuntimeError("לא ניתן לחתום session: אין SECRET_KEY לאפליקציה")
    cookie_name = interface.get_cookie_name(webapp_app.app)
    cookie_header = f"{cookie_name}={serializer.dumps({'user_id': ADMIN_USER_ID})}"

    server = WSGIServer(("127.0.0.1", 0), webapp_app.app, log=None)
    server.start()  # מקצה פורט פנוי ומתחיל להאזין
    port = server.server_port

    results: dict[int, object] = {}

    def hit(index: int, delay: float) -> None:
        gevent.sleep(delay)
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/profiler/slow-queries",
            headers={"Cookie": cookie_header},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                results[index] = response.status
        except urllib.error.HTTPError as exc:
            results[index] = exc.code
        except Exception as exc:  # pragma: no cover - רשת מקומית
            results[index] = f"{type(exc).__name__}: {exc}"

    # ההשהיות קטנות מ-QUERY_SECONDS כדי שכל הבקשות יחפפו בוודאות.
    greenlets = [
        gevent.spawn(hit, i, i * (QUERY_SECONDS / (concurrency * 2)))
        for i in range(concurrency)
    ]
    gevent.joinall(greenlets, timeout=60)
    server.stop()

    print(
        json.dumps(
            {
                "service_is_async": _SERVICE_IS_ASYNC,
                "statuses": [results.get(i) for i in range(concurrency)],
            }
        )
    )
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # יציאה מיידית: פירוק גרינלטים בסוף התהליך מייצר רעש ("greenlet is being finalized")
    # שאינו קשור לתוצאת המדידה. התוצאה כבר נכתבה ונשטפה ל-stdout.
    os._exit(code)

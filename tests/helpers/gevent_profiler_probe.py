"""עוזר לטסט: מריץ את הפרופיילר תחת gevent אמיתי, בתת-תהליך.

⚠️ הקובץ הזה עושה ``monkey.patch_all()`` בזמן ייבוא, ולכן הוא יושב ב-``tests/helpers``
ולא ישירות תחת ``tests/``: אסור שיתגלה או ייובא בטעות לתוך תהליך ה-pytest.

למה תת-תהליך: ``conftest.py`` מגדיר ``CODEBOT_DISABLE_GEVENT_PATCH=1``, כלומר
ה-monkey patching של gevent **מכובה בכל סוויטת הטסטים**. בלי זה אי אפשר לשחזר
את הבאג בכלל, כי הוא נובע בדיוק מכך שגרינלטים חולקים OS thread אחד.

התהליך מדמה את מה שרץ בפרודקשן: gunicorn עם ``worker_class=gevent`` מריץ
``gevent.pywsgi.WSGIServer`` (מקור: gunicorn/workers/ggevent.py), עם worker יחיד
(``WEB_CONCURRENCY=1``). כאן מוקם אותו שרת, עם ראוט Flask סינכרוני שקורא לשירות
הפרופיילר האמיתי, ונורות אליו כמה בקשות **חופפות**.

הפלט: שורת JSON יחידה עם קודי הסטטוס.
"""

from __future__ import annotations

# חייב להיות ראשון, לפני כל ייבוא של ספריות סטנדרטיות.
from gevent import monkey

monkey.patch_all()

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

import gevent  # noqa: E402
from flask import Flask, jsonify  # noqa: E402
from gevent.pywsgi import WSGIServer  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.query_profiler_service import PersistentQueryProfilerService  # noqa: E402

#: כמה זמן כל "שאילתה" נמשכת. תחת gevent ``time.sleep`` הוא yield קואופרטיבי,
#: בדיוק כמו I/O של pymongo — וזה מה שגורם לבקשות לחפוף.
QUERY_SECONDS = 0.4


class _StubCollection:
    def find(self, query, sort=None, limit=None):
        time.sleep(QUERY_SECONDS)
        return []

    def insert_one(self, doc):
        return None


class _StubDB:
    def __init__(self):
        self._coll = _StubCollection()

    def __getitem__(self, name):
        return self._coll


class _StubManager:
    def __init__(self):
        self.db = _StubDB()


def build_app() -> Flask:
    app = Flask(__name__)
    service = PersistentQueryProfilerService(_StubManager(), slow_threshold_ms=100)

    @app.route("/slow-queries")
    def slow_queries():
        # אותה צורה כמו api_profiler_slow_queries ב-webapp/app.py: ראוט סינכרוני
        # שקורא לשירות ישירות, בלי שום מעטפת asyncio.
        data = service.get_slow_queries(limit=10)
        return jsonify({"count": len(data)})

    return app


def main() -> int:
    concurrency = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    server = WSGIServer(("127.0.0.1", 0), build_app(), log=None)
    server.start()  # מקצה פורט פנוי ומתחיל להאזין
    port = server.server_port

    results: dict[int, object] = {}

    def hit(index: int, delay: float) -> None:
        gevent.sleep(delay)
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/slow-queries", timeout=30
            ) as response:
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

    print(json.dumps({"statuses": [results.get(i) for i in range(concurrency)]}))
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # יציאה מיידית: פירוק גרינלטים בסוף התהליך מייצר רעש ("greenlet is being finalized")
    # שאינו קשור לתוצאת המדידה. התוצאה כבר נכתבה ונשטפה ל-stdout.
    os._exit(code)

"""תקרת הזמן של "חלץ" מול רשת אמיתית, בתהליך ש-gevent החליף בו את הרשת — כמו ה-worker של הוובאפ.

**למה תת-תהליך:** ``conftest.py`` מכבה את ה-monkey patching של gevent בכל הסוויטה, ובתהליך כזה ``gevent.Timeout``
לא יכול לקטוע קריאה מהרשת (gevent 24.11.1, ``gevent/timeout.py``) — ולכן השירות מסרב בו לחלץ
(``test_a_process_gevent_did_not_patch_refuses_instead_of_running_without_a_deadline`` ב-
``tests/test_docs_extract_service.py``). כאן ``tests/helpers/docs_extract_deadline_probe.py`` עושה
``monkey.patch_all()`` בעצמו, וקורא ל-``_call_model`` של השירות, עם הלקוח האמיתי של ה-SDK, מול שרת שמטפטף תשובה
בתהליך נפרד.

**מה נבדק:** הקריאה נקטעת בתקרה — ב-HTTP, וב-HTTPS בשני המסלולים שבהם httpx2 בונה את ה-SSLContext — ובזמן
ההמתנה הלולאה של gevent ממשיכה לרוץ (``max_gap``), כלומר בקשות אחרות ב-worker לא נעצרות. והביקורת: אותה קריאה עם
התקרה של ה-SDK בלבד עדיין רצה, כי השרת שולח משהו לפני שהתקרה הזו נגמרת. בלי הביקורת, הטסט היה עובר גם אם השרת
פשוט היה סוגר את החיבור.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(REPO_ROOT, "tests", "helpers", "docs_extract_deadline_probe.py")


def test_the_extract_deadline_cuts_a_dripping_answer_without_blocking_the_worker(tmp_path):
    pytest.importorskip("gevent")
    completed = subprocess.run(
        [sys.executable, "-B", PROBE, str(tmp_path)], capture_output=True, text=True, timeout=50
    )
    assert completed.returncode == 0, f"stdout: {completed.stdout}\nstderr: {completed.stderr[-2000:]}"
    result = json.loads(completed.stdout.strip().splitlines()[-1])

    assert result["patched"] is True, "הפרוב לא רץ תחת gevent — הבדיקה לא בודקת כלום"
    assert result["deadline_enforceable"] is True
    deadline = result["deadline"]
    for case in ("http", "https", "https_truststore"):
        measured = result[case]
        assert measured["code"] == "extract_timeout", (case, measured)
        assert deadline <= measured["elapsed"] < deadline + 0.5, (case, measured)
        assert measured["max_gap"] < 0.25, (case, measured)
    assert result["sdk_ceiling_alone"] == {"waited": 3.0, "still_running": True}, result

"""קצב הדגימה של בועת התזכורות — נמדד בדפדפן אמיתי.

**למה זו חייבת להיות בדיקת דפדפן.** ההשהיה שהסקריפט מבקש מגיעה ל-
``setTimeout``, וזו פונקציה של הדפדפן עם התנהגות שאינה בחתימה: הארגומנט
מומר ל-int32 חתום, ולכן כל ערך מעל 2,147,483,647 מילישניות (כ-24.8 ימים)
**גולש**. תזכורת שנקבעה לעוד חודשיים מייצרת בדיוק ערך כזה, והתוצאה היא
טיימר שנורה בזמן שרירותי — או מיד. מקור: MDN, ``Window.setTimeout``, סעיף
"Maximum delay value".

בדיקת יחידה על חישוב ההשהיה הייתה עוברת בשמחה על הערך הגולש, כי בפייתון
אין גבול כזה. רק הדפדפן אוכף אותו.

**ריצת הבקרה.** ``test_removing_the_clamp_breaks_the_long_delay`` מריץ את
אותו סקריפט בלי ה-clamp ודורש שהערך **כן** יחרוג. בלי זה, שינוי עתידי היה
יכול להפוך את הבדיקה לחסרת משמעות בשקט — היא הייתה ממשיכה לעבור בלי לבדוק
כלום.

הסקריפט נחלץ מ-``base.html`` עצמו ולא מועתק לכאן, כדי שהבדיקה תיפול כשהוא
משתנה. מדולג בשקט כשאין Chromium; ``chromium_executable`` מגיע מ-
``tests/conftest.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_TEMPLATE = REPO_ROOT / "webapp" / "templates" / "base.html"

#: הגבול שמעליו ``setTimeout`` גולש. ראו את הדוקסטרינג למעלה.
INT32_MAX_MS = 2147483647

MIN_POLL_MS = 60 * 1000
MAX_POLL_MS = 30 * 60 * 1000

#: ה-DOM המינימלי שהסקריפט מחפש כדי לתלות עליו את הבועה.
PAGE = """<!doctype html><html lang="he"><head><meta charset="utf-8"></head><body>
  <a class="nav-link" href="/settings">הגדרות</a>
  <button class="mobile-menu-toggle">תפריט</button>
</body></html>"""

#: מחליף את ``fetch`` ואת ``setTimeout`` לפני שהסקריפט רץ, כדי לקרוא את
#: ההשהיה שהוא באמת ביקש. ה-``setTimeout`` האמיתי נקרא עם שעה, כדי שהטיימר
#: לא יירה בזמן הבדיקה ויציף את הרשימה.
HARNESS = """
window.__delays = [];
const _st = window.setTimeout;
window.setTimeout = function(fn, ms){ window.__delays.push(ms); return _st(fn, 3600000); };
window.fetch = async function(){
  return { ok: true, status: 200, headers: { get: () => null }, json: async () => window.__reply };
};
"""


def _polling_script() -> str:
    """הסקריפט האמיתי מתוך ``base.html``, לא העתק שלו."""
    src = BASE_TEMPLATE.read_text(encoding="utf-8")
    marker = "(function initStickyRemindersIndicator(){"
    start = src.index(marker)
    end = src.index("})();", start) + len("})();")
    script = src[start:end]
    assert "{%" not in script and "{{" not in script, "תחביר Jinja דלף לתוך בלוק ה-JS"
    return script


def _summary(**overrides):
    reply = {
        "ok": True,
        "has_due": False,
        "count_due": 0,
        "next": None,
        "next_in_seconds": None,
    }
    reply.update(overrides)
    return reply


def _requested_delay(chromium_executable, reply, script) -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium_executable)
        try:
            page = browser.new_page()
            page.set_content(PAGE)
            page.evaluate(HARNESS)
            page.evaluate(f"window.__reply = {json.dumps(reply)};")
            page.evaluate(script)
            page.wait_for_function("window.__delays.length > 0", timeout=5000)
            return page.evaluate("window.__delays")[-1]
        finally:
            browser.close()


@pytest.mark.parametrize(
    "name,reply,expected",
    [
        ("אין תזכורות כלל", _summary(), MAX_POLL_MS),
        ("התזכורת הבאה בעוד שתי דקות", _summary(next_in_seconds=120), 120 * 1000),
        ("קרובה מדי — נתפסת ברצפה", _summary(next_in_seconds=10), MIN_POLL_MS),
        ("רחוקה מדי — נתפסת בתקרה", _summary(next_in_seconds=5_184_000), MAX_POLL_MS),
        (
            "יש תזכורת בשלה",
            _summary(has_due=True, count_due=3, next={"note_id": "n1", "file_id": "f1", "remind_at": None}),
            MAX_POLL_MS,
        ),
    ],
)
def test_client_schedules_from_the_server_answer(chromium_executable, name, reply, expected):
    """הלקוח דוגם לפי מה שהשרת אמר, ובתוך גבולות בטוחים."""
    delay = _requested_delay(chromium_executable, reply, _polling_script())
    assert delay == expected, f"{name}: ביקש {delay}, ציפינו ל-{expected}"
    assert delay <= INT32_MAX_MS, f"{name}: {delay} חורג מגבול ה-int32 של setTimeout"


def test_removing_the_clamp_breaks_the_long_delay(chromium_executable):
    """ריצת בקרה: בלי ה-clamp, תזכורת רחוקה חורגת מגבול ה-int32.

    זה מה שהופך את הבדיקה שמעליה לראיה ולא לירוק. אם המוטציה הזו מפסיקה
    לחרוג, הבדיקה כבר אינה מודדת את מה שהיא מתיימרת למדוד.
    """
    script = _polling_script()
    clamped = "const delay = Math.min(MAX_POLL_MS, Math.max(MIN_POLL_MS, safe));"
    assert script.count(clamped) == 1, "ה-clamp לא נמצא בסקריפט — הבדיקה אינה תקפה יותר"
    mutated = script.replace(clamped, "const delay = safe;")

    delay = _requested_delay(chromium_executable, _summary(next_in_seconds=5_184_000), mutated)
    assert delay > INT32_MAX_MS, (
        "המוטציה לא ייצרה חריגה — כלומר הבדיקה למעלה אינה מסוגלת לתפוס את הבאג"
    )

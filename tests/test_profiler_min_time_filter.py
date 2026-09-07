"""‏``min_time`` — פרמטר מתועד שהפסיק לעבוד, ומה שמחזיר אותו.

**מה קרה.** עד המעבר ל-``get_slow_queries_page`` הראוט העביר
``min_execution_time_ms=float(min_time) if min_time else None``
(‏``webapp/app.py`` ב-``main``, שורות 5016 ו-5029). המעבר הפיל את הפרמטר
בשקט: הראוט המשיך לקבל אותו, להתעלם, ולהחזיר **200 עם שורות לא מסוננות**.
הוא לא נטוש — ``docs/observability/query-performance-profiler.rst`` מתעד אותו,
והראוט של הבוט (``handlers/profiler_handler.py``) עדיין משתמש בו.

זה ``state-record-without-state-change``: פרמטר מוצהר שאינו משנה דבר. תשובה
שנראית תקינה ואינה נכונה גרועה משגיאה, כי אין בה שום סימן שמשהו לא בסדר.

**איפה נבדק מה.** הקובץ הזה מכסה את שכבת ה-HTTP בלבד — פרסור, דחייה, ומה
שמגיע לשירות. ההשפעה על השורות ועל ``total`` נבדקת ב-
``test_profiler_paging_and_window.py``, כי שם כבר יושבת דמה שמבינה את תנאי
הקורסור (``$and``/``$or``). דמה שנייה וחלקית כאן הייתה חוזרת על הטעות שנתפסה
בסבב הקודם — אוסף מקרטון נדיב מדי מסתיר בדיוק את הבאג שהוא אמור לחשוף. וזה
לא תיאורטי: הגרסה הראשונה של הקובץ הזה **כן** ניסתה דמה משלה, והיא נפלה על
תנאי הקורסור עוד לפני שהספיקה לבדוק משהו.
"""

from __future__ import annotations

import pytest


class TestTheRouteHonoursIt:
    @pytest.fixture
    def seen(self, monkeypatch):
        """מה שהראוט באמת העביר לשירות."""
        import webapp.app as webapp_app

        monkeypatch.setattr(webapp_app, "_profiler_is_authorized", lambda: True, raising=True)
        monkeypatch.setattr(webapp_app, "_profiler_rate_limit_ok", lambda: True, raising=True)
        captured = {}

        class _Svc:
            def get_slow_queries_page(self, **kwargs):
                captured.update(kwargs)
                return {"records": [], "total": 0, "next_cursor": None}

        monkeypatch.setattr(webapp_app, "_get_webapp_profiler_service", lambda: _Svc(), raising=True)
        return webapp_app.app.test_client(), captured

    def test_the_documented_parameter_reaches_the_service(self, seen):
        client, captured = seen

        assert client.get("/api/profiler/slow-queries?min_time=1200").status_code == 200
        assert captured["min_execution_time_ms"] == 1200.0

    def test_without_it_the_filter_stays_off(self, seen):
        client, captured = seen

        client.get("/api/profiler/slow-queries")

        assert captured["min_execution_time_ms"] is None

    @pytest.mark.parametrize("bad", ["abc", "1,200", "--5", "1e"])
    def test_a_value_that_is_not_a_number_is_a_400_and_not_a_silent_skip(self, seen, bad):
        """ערך פסול ב-**מסנן** אינו מתעלמים ממנו.

        ‏``limit`` פסול מחזיר 50 שורות במקום 20 — מטריד ולא מזיק. ``min_time``
        פסול שמתעלמים ממנו מחזיר **שורות אחרות** מאלה שהתבקשו, ובלי שום סימן.
        """
        client, captured = seen

        response = client.get(f"/api/profiler/slow-queries?min_time={bad}")

        assert response.status_code == 400
        assert response.get_json()["message"] == "invalid_min_time"
        assert not captured, "הבקשה לא הייתה אמורה להגיע לשירות בכלל"

    @pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "NaN"])
    def test_a_non_finite_value_is_rejected_too(self, seen, bad):
        """‏``float("nan")`` **מתפרש בהצלחה** — וזו בדיוק הסכנה.

        ‏``{"$gte": nan}`` אינו מתאים לאף מסמך במונגו, כלומר טבלה ריקה בלי
        שום הסבר. אותו שיקול שמאחורי ``_reject_non_finite`` בסבב הקודם: ערך
        שעובר את הפרסור ומייצר תוצאה שקרית גרוע מערך שנדחה.
        """
        client, captured = seen

        response = client.get(f"/api/profiler/slow-queries?min_time={bad}")

        assert response.status_code == 400
        assert response.get_json()["message"] == "invalid_min_time"
        assert not captured

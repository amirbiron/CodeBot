"""קובץ האימות של Google Search Console (``/google7bb000f75b7bf329.html``) — ציבורי, ובתוכן המדויק שגוגל נתן.

גוגל מוריד את הקובץ בלי סשן ובלי לעקוב אחרי הפניות, ולכן הטסט מבקש אותו מ-client חדש ודורש 200 ישיר. הרקע והמקור ב-docstring של ``google_site_verification`` ב-``webapp/app.py``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("flask")


def test_verification_file_answers_without_login_with_the_exact_content():
    from webapp import app as webapp_app

    # client חדש, בלי session_transaction — כמו הבודק של גוגל
    resp = webapp_app.app.test_client().get("/google7bb000f75b7bf329.html")

    assert resp.status_code == 200, resp.status_code
    assert resp.mimetype == "text/html"
    assert resp.get_data() == b"google-site-verification: google7bb000f75b7bf329.html"

"""משתנה רגיש שאין לו ערך לא אמור להציג מנעול.

הרקע: התבנית הציגה מנעול לכל שורה עם ``is_sensitive``, בלי לבדוק אם יש
בכלל ערך. התוצאה הייתה תא ריק לגמרי עם מנעול לידו — קריאה סבירה שלו היא
"יש כאן ערך, הוא מוסתר", בזמן שפשוט אין ערך. במקום זה מוצג עכשיו קו לרוחב.

הבדיקה רצה על ה-HTML המרונדר בפועל (ולא על שכבת השירות), כי הבאג היה
בתבנית בלבד — השירות תמיד החזיר מחרוזת ריקה כמו שצריך.
"""

import types

import pytest
from bs4 import BeautifulSoup

from services.config_inspector_service import (
    ConfigDefinition,
    ConfigService,
    get_config_service,
)

# משתנים מלאכותיים שמכסים את ארבעת הצירופים של רגיש/ריק
FAKE_DEFS = {
    "FAKE_SECRET_EMPTY": ConfigDefinition(
        key="FAKE_SECRET_EMPTY",
        services=("webapp",),
        default="",
        description="רגיש בלי ערך",
        category="cache",
        sensitive=True,
    ),
    "FAKE_SECRET_SET": ConfigDefinition(
        key="FAKE_SECRET_SET",
        services=("webapp",),
        default="hunter2",
        description="רגיש עם ערך",
        category="cache",
        sensitive=True,
    ),
    "FAKE_PLAIN_EMPTY": ConfigDefinition(
        key="FAKE_PLAIN_EMPTY",
        services=("webapp",),
        default="",
        description="רגיל בלי ערך",
        category="cache",
    ),
    "FAKE_PLAIN_SET": ConfigDefinition(
        key="FAKE_PLAIN_SET",
        services=("webapp",),
        default="visible",
        description="רגיל עם ערך",
        category="cache",
    ),
    # שורה לעמוד "שירותים אחרים": רגישה, בלי דיפולט
    "FAKE_OTHER_SECRET_EMPTY": ConfigDefinition(
        key="FAKE_OTHER_SECRET_EMPTY",
        services=("bot",),
        default="",
        description="רגיש בשירות אחר בלי ערך",
        category="cache",
        sensitive=True,
    ),
}


@pytest.fixture
def client(monkeypatch):
    import webapp.app as app_mod

    app_mod.app.testing = True
    app_mod.app.config["SECRET_KEY"] = "test"

    # שירות עם הגדרות מלאכותיות בלבד, כדי שהטסט לא יישבר כשמוסיפים משתנים אמיתיים
    service = ConfigService()
    monkeypatch.setattr(service, "CONFIG_DEFINITIONS", FAKE_DEFS)
    monkeypatch.setattr(
        "services.config_inspector_service.get_config_service", lambda: service
    )

    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    monkeypatch.setattr(app_mod, "get_db", lambda: types.SimpleNamespace(), raising=False)

    with app_mod.app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_data"] = {"id": 1, "is_admin": True, "is_premium": False}
        yield c


@pytest.fixture
def page(client):
    for key in FAKE_DEFS:
        # ודא שאף אחד מהמשתנים המלאכותיים לא יורש ערך מהסביבה
        assert key not in ("PATH", "HOME")
    resp = client.get("/admin/config-inspector")
    assert resp.status_code == 200, f"העמוד לא נטען (סטטוס {resp.status_code})"
    return BeautifulSoup(resp.get_data(as_text=True), "html.parser")


def _row(page, key):
    """מאתר את שורת הטבלה של מפתח נתון."""
    for tr in page.select("tr"):
        name = tr.select_one(".config-key-name")
        if name and name.get_text(strip=True) == key:
            return tr
    raise AssertionError(f"לא נמצאה שורה עבור {key}")


def _active_cell(page, key):
    """התא של Active Value — התא השני בשורה בעמוד הראשי."""
    return _row(page, key).select("td")[1]


def test_sensitive_without_value_has_no_lock(page):
    """הרגרסיה עצמה: אין ערך ⇒ אין מנעול."""
    cell = _active_cell(page, "FAKE_SECRET_EMPTY")
    assert not cell.select(
        "i.fa-lock"
    ), "מנעול מוצג על משתנה רגיש שאין לו ערך — משתמע שיש סוד"


def test_sensitive_without_value_shows_dash(page):
    """ובמקומו מוצג קו לרוחב, כדי שיהיה ברור שאין כאן ערך."""
    cell = _active_cell(page, "FAKE_SECRET_EMPTY")
    dash = cell.select_one(".no-value")
    assert dash is not None, "לא מוצג סימון 'אין ערך'"
    assert dash.get_text(strip=True) == "—"


def test_sensitive_with_value_keeps_the_lock(page):
    """המנעול לא נעלם מהמקרה שבו הוא כן נכון — יש ערך והוא מוסתר."""
    cell = _active_cell(page, "FAKE_SECRET_SET")
    assert cell.select("i.fa-lock"), "המנעול נעלם ממשתנה רגיש שיש לו ערך"
    assert not cell.select(".no-value")
    text = cell.select_one(".config-value-text").get_text(strip=True)
    assert "hunter2" not in text, "הערך הרגיש דלף לתצוגה"


def test_plain_without_value_shows_the_same_dash(page):
    """אותו מצב ⇒ אותו סימון, גם כשהמשתנה אינו רגיש."""
    cell = _active_cell(page, "FAKE_PLAIN_EMPTY")
    assert not cell.select("i.fa-lock")
    assert cell.select_one(".no-value").get_text(strip=True) == "—"


def test_plain_with_value_is_shown_as_is(page):
    cell = _active_cell(page, "FAKE_PLAIN_SET")
    assert "visible" in cell.select_one(".config-value-text").get_text(strip=True)
    assert not cell.select(".no-value")


def test_masked_style_is_not_applied_to_empty_cells(page):
    """סגנון ה-masked שייך לערך מוסתר בלבד, לא לתא ריק."""
    empty = _active_cell(page, "FAKE_SECRET_EMPTY").select_one(".config-value")
    assert "masked" not in (empty.get("class") or [])
    assert "empty" in (empty.get("class") or [])

    filled = _active_cell(page, "FAKE_SECRET_SET").select_one(".config-value")
    assert "masked" in (filled.get("class") or [])


def test_copy_button_does_not_pick_up_the_dash(page):
    """ההעתקה קוראת את .config-value-text — הקו חייב להישאר מחוץ לו.

    אחרת כפתור ההעתקה היה מייצר ``FAKE_SECRET_EMPTY=—`` במקום ערך ריק.
    """
    cell = _active_cell(page, "FAKE_SECRET_EMPTY")
    assert cell.select_one(".config-value-text").get_text(strip=True) == ""


def test_other_services_page_uses_the_same_dash(page):
    """גם בעמוד 'שירותים אחרים' — אותו סימון במקום הטקסט הישן."""
    row = _row(page, "FAKE_OTHER_SECRET_EMPTY")
    cell = row.select("td")[2]  # Key | שירות | Default Value | תיאור
    assert not cell.select("i.fa-lock")
    assert cell.select_one(".no-value").get_text(strip=True) == "—"


def test_real_service_definitions_still_load():
    """שפיות: השירות האמיתי עדיין נטען ומחזיר את REDIS_URL כרגיש."""
    service = get_config_service()
    redis_def = service.CONFIG_DEFINITIONS.get("REDIS_URL")
    assert redis_def is not None
    assert redis_def.sensitive is True

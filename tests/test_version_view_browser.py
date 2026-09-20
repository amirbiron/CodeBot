"""המסלול שהמשתמש עובר בפועל: מהיסטוריה אל גרסה, ומשתי גרסאות אל דיף.

**למה דפדפן ולא ``test_client``.** שורות ההיסטוריה נבנות ב-JavaScript
מתוך תשובת ה-API, בתוך סקריפט אינליין ב-``view_file.html``. בדיקה שקוראת
את ה-HTML של התבנית רואה את **הקוד** ולא את **השורות**, ולכן היא עוברת
גם כשהקישור מפסיק להיווצר. בדיקת מוטציה הראתה את זה במפורש: החלפת
התנאי שבונה את הקישור ב-``false`` לא הפילה אף בדיקה אחרת.

זו גם הרצת המסלול המרכזי מקצה לקצה — פתיחת היסטוריה, מעבר לגרסה ישנה,
וסימון שתי גרסאות להשוואה.
"""

from __future__ import annotations

import pytest
from bson import ObjectId

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

#: ``admin_live_server`` בונה session למשתמש 1, ולכן הקבצים שלו.
USER_ID = 1
FILE_NAME = "history.py"


def _dismiss_welcome(p):
    """מודאל הפתיחה מכסה את העמוד וחוסם קליקים.

    ``add_init_script`` לבדו אינו מספיק: הוא מריץ localStorage בכל ניווט,
    אבל המודאל מרונדר ומקבל ``active`` גם כך, ולכן הוא מוסר מה-DOM אחרי
    כל מעבר עמוד — לא רק בטעינה הראשונה.
    """
    p.evaluate(
        "document.querySelectorAll('.welcome-modal, .welcome-modal__backdrop,"
        " #welcomeModal').forEach(e => e.remove())"
    )


@pytest.fixture
def seeded(wired_mongo):
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    db.large_files.delete_many({})
    ids = {}
    for version in (1, 2, 3):
        oid = ObjectId()
        db.code_snippets.insert_one({
            "_id": oid, "user_id": USER_ID, "file_name": FILE_NAME,
            "code": f"print({version})\n", "programming_language": "python",
            "version": version, "is_active": True,
        })
        ids[version] = str(oid)
    return ids


@pytest.fixture
def page(seeded, admin_live_server, chromium_executable):
    with sync_playwright() as pw:
        try:
            browser = (
                pw.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"אין Chromium זמין: {exc}")

        with browser, browser.new_context(
            viewport={"width": 1280, "height": 900},
        ) as context:
            context.add_cookies([{
                "name": "session", "value": admin_live_server.session_cookie,
                "domain": "127.0.0.1", "path": "/",
            }])
            p = context.new_page()
            p.add_init_script(
                "try{localStorage.setItem('welcomeModalSeen','1');"
                "localStorage.setItem('onboarding_completed','1');}catch(e){}"
            )
            p.goto(f"{admin_live_server.base_url}/file/{seeded[3]}",
                   wait_until="domcontentloaded")
            _dismiss_welcome(p)
            # המודאל נפתח דרך תפריט ה"עוד", ו-``openHistoryModal`` הוא
            # הגלובל שהתפריט קורא לו.
            p.evaluate("window.openHistoryModal && window.openHistoryModal()")
            p.wait_for_selector(".history-modal__item", timeout=10000)
            yield p


def test_a_history_row_is_a_link_to_that_version(page, seeded):
    href = page.get_attribute(
        ".history-modal__item:last-child .history-modal__title a", "href")
    assert href, "שורת ההיסטוריה אינה מקשרת לשום מקום"
    assert href.endswith(f"/file/{seeded[1]}"), (
        f"הקישור מצביע על {href} ולא על הגרסה שהשורה מתארת")


def test_the_current_version_row_is_not_a_link(page):
    """השורה שמתארת את העמוד שאנחנו כבר עליו אינה מקושרת."""
    assert page.query_selector(
        ".history-modal__item.is-current .history-modal__title a") is None


def test_opening_an_old_version_shows_the_banner(page, seeded):
    page.click(".history-modal__item:last-child .history-modal__title a")
    page.wait_for_load_state("domcontentloaded")
    assert page.url.endswith(f"/file/{seeded[1]}")
    banner = page.wait_for_selector(".version-banner", timeout=10000)
    assert "גרסה 1 מתוך 3" in banner.inner_text()


def test_selecting_two_versions_opens_a_diff_between_them(page, seeded):
    boxes = page.query_selector_all(".history-modal__select")
    assert len(boxes) == 3, f"נמצאו {len(boxes)} תיבות סימון"
    # הרשימה ממוינת יורד: [0] היא גרסה 3 ו-[2] היא גרסה 1.
    boxes[0].check()
    boxes[2].check()
    page.click(".history-modal__compare button")
    page.wait_for_load_state("domcontentloaded")
    assert f"/compare/{seeded[3]}" in page.url, f"נווטנו ל-{page.url}"
    assert "left=1" in page.url and "right=3" in page.url, page.url


def test_a_third_selection_replaces_the_oldest(page):
    boxes = page.query_selector_all(".history-modal__select")
    boxes[0].check()
    boxes[1].check()
    boxes[2].check()
    checked = [b for b in page.query_selector_all(".history-modal__select")
               if b.is_checked()]
    assert len(checked) == 2, "אפשר לסמן יותר משתי גרסאות להשוואה"


def test_restoring_from_the_banner_creates_a_new_version(page, seeded, wired_mongo):
    """הפעולה המרכזית של הבאנר, מקצה לקצה.

    השחזור הוא ``POST`` ולא קישור: פעולה שמשנה מצב מאחורי ``GET`` נורית
    על ידי prefetch, היסטוריה וסורקי תצוגה מקדימה של קישורים.
    """
    page.click(".history-modal__item:last-child .history-modal__title a")
    page.wait_for_selector("#versionBannerRestore", timeout=10000)
    _dismiss_welcome(page)
    page.click("#versionBannerRestore")
    # ``wait_for_url`` ולא ``wait_for_function``: ה-CSP של העמוד אינו
    # מתיר ``unsafe-eval``, ולכן הערכת מחרוזת כ-JavaScript נחסמת — וטוב
    # שכך. ההמתנה כאן היא על הכתובת, בלי להריץ קוד בדף.
    page.wait_for_url(lambda url: seeded[1] not in url, timeout=15000)

    db = wired_mongo.get_db()
    versions = sorted(d["version"] for d in
                      db.code_snippets.find({"file_name": FILE_NAME}, {"version": 1}))
    assert versions == [1, 2, 3, 4], f"גרסאות אחרי שחזור: {versions}"

    newest = db.code_snippets.find_one({"file_name": FILE_NAME, "version": 4})
    assert newest["code"] == "print(1)\n", "הגרסה החדשה אינה נושאת את תוכן גרסה 1"
    # העמוד שאליו הגענו הוא הגרסה החדשה, ולכן בלי באנר.
    assert page.query_selector(".version-banner") is None

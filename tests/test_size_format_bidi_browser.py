"""גודל קובץ נקרא בסדר לטיני גם בתוך טקסט בעברית — נמדד בדפדפן אמיתי.

**למה זו חייבת להיות בדיקת דפדפן.** ``"105 KB"`` בתוך פסקה בעברית מתהפך על
המסך ל-``"KB 105"``: אלגוריתם ה-bidi רואה מספר, רווח ניטרלי, ומילה לטינית,
והרווח הניטרלי אינו מדביק אותם אלא נופל לכיוון הפסקה. המחרוזת נשברת לשני
קטעים שמסודרים מימין ← לשמאל.

זה משהו שהדפדפן אוכף ו-Python אינו רואה. בדיקת יחידה על המחרוזת תעבור בשמחה
על קוד שמצייר את היחידה בצד הלא נכון, ולכן היא אינה ראיה כאן.

**ריצת הבקרה.** הבדיקה מודדת גם מחרוזת **בלי** בידוד ודורשת שהיא כן תתהפך.
בלי זה, שינוי עתידי בדפדפן או בעמוד היה יכול להפוך את הבדיקה לחסרת משמעות
בשקט — היא הייתה ממשיכה לעבור בלי לבדוק כלום.

מדולג בשקט כשאין Chromium. ``chromium_executable`` מגיע מ-``tests/conftest.py``;
pytest מוצא אותו לבד, בלי ייבוא בין קבצי טסט.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

from webapp.size_format import format_file_size  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
JS_MODULE = REPO_ROOT / "webapp" / "static" / "js" / "utils" / "size-format.js"

#: העמוד משחזר את ההקשר של כרטיס קובץ: ``dir="rtl"`` על השורש, ואחים בעברית.
#: ה-JS הנטען הוא הקובץ האמיתי, לא העתק — כדי שהבדיקה תיפול אם הוא ישתנה.
PAGE_TEMPLATE = """<!doctype html>
<html dir="rtl" lang="he"><head><meta charset="utf-8"></head><body>
  <div><span>12 שורות</span><span id="from-server">{server_value}</span></div>
  <div><span>12 שורות</span><span id="from-client"></span></div>
  <div><span>12 שורות</span><span id="control">105 KB</span></div>
  <script>{module_source}</script>
  <script>
    document.getElementById('from-client').textContent =
      window.SizeFormat.formatFileSize(107520);
  </script>
</body></html>
"""

#: מחזיר את מיקום ה-x שבו הדפדפן צייר בפועל כל תת-מחרוזת.
MEASURE_JS = """
(id) => {
  const node = document.getElementById(id).firstChild;
  const text = node.textContent;
  function leftOf(sub) {
    const i = text.indexOf(sub);
    if (i < 0) return null;
    const range = document.createRange();
    range.setStart(node, i);
    range.setEnd(node, i + sub.length);
    return range.getBoundingClientRect().left;
  }
  return { text, number: leftOf('105'), unit: leftOf('KB') };
}
"""


@pytest.fixture(scope="module")
def measured(chromium_executable, tmp_path_factory):
    """טוען את העמוד פעם אחת ומחזיר את המדידה של שלושת המקרים.

    ``chromium_executable`` הוא ``None`` כשאין דפדפן תחת
    ``PLAYWRIGHT_BROWSERS_PATH``, ו-``None`` פירושו "תן ל-Playwright לחפש
    בעצמו" ולא "אין דפדפן". דילוג במקרה הזה היה מבטל את הבדיקה בשקט בכל
    סביבה שהתקינה ``playwright install chromium`` כרגיל — וההגנה על ה-bidi
    הייתה נעלמת בלי שאיש ישים לב. מדלגים רק אם ההשקה עצמה נכשלת, כמו בשאר
    קובצי הדפדפן בריפו.
    """
    page_file = tmp_path_factory.mktemp("bidi") / "page.html"
    page_file.write_text(
        PAGE_TEMPLATE.format(
            server_value=format_file_size(105 * 1024),
            module_source=JS_MODULE.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )

    with sync_playwright() as p:
        try:
            browser = (
                p.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else p.chromium.launch()
            )
        except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            page = browser.new_page()
            page.goto(page_file.as_uri())
            results = {
                name: page.evaluate(MEASURE_JS, name)
                for name in ("from-server", "from-client", "control")
            }
        finally:
            browser.close()

    for name, measurement in results.items():
        assert measurement["number"] is not None, f"{name}: לא נמצא המספר בטקסט"
        assert measurement["unit"] is not None, f"{name}: לא נמצאה היחידה בטקסט"
    return results


def test_control_proves_the_flip_is_real(measured):
    """בלי בידוד היחידה באמת נוחתת משמאל למספר — אחרת אין מה לבדוק."""
    control = measured["control"]

    assert control["unit"] < control["number"], (
        "המחרוזת ללא בידוד לא התהפכה, ולכן הבדיקות למטה אינן מוכיחות דבר. "
        "ייתכן שהתנהגות ה-bidi של הדפדפן השתנתה, או שהעמוד כבר אינו RTL."
    )


@pytest.mark.parametrize("source", ["from-server", "from-client"])
def test_size_reads_left_to_right_inside_hebrew(measured, source):
    """המספר לפני היחידה, כמו בלטינית — משני צדי המערכת."""
    measurement = measured[source]

    assert measurement["number"] < measurement["unit"], (
        f"{source}: היחידה צוירה משמאל למספר — הערך מתהפך על המסך. "
        f"נמדד: 105 ב-x={measurement['number']}, KB ב-x={measurement['unit']}"
    )


def test_both_sides_render_the_same_string(measured):
    """מה שהשרת שולח ומה שהדפדפן מחשב הם אותו דבר, עד התו."""
    assert measured["from-server"]["text"] == measured["from-client"]["text"]

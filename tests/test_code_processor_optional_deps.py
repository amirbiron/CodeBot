"""``code_processor`` נטען גם כשהספריות האופציונליות שלו חסרות.

ב-PR #669 הייבוא של הספריות האופציונליות ב-``code_processor.py`` (``OPTIONAL_PACKAGES``
למטה) נעטף ב-``try/except`` עם חלופה. הטסט בודק שהמודול נטען בלעדיהן, שהחלופות באמת נכנסות
לפעולה, ושה-API הבסיסי עובד.

איך מדמים ספרייה חסרה: ``sys.modules[name] = None``. כשהערך הוא ``None``, פייתון זורק
``ModuleNotFoundError`` בייבוא במקום לחפש את החבילה בדיסק. מחיקה (``sys.modules.pop``) לא
מדמה כלום: הייבוא הבא פשוט טוען את החבילה מחדש. הגרסה הקודמת של הטסט מחקה, ולכן מעולם
לא בדקה את החלופות. גרוע מזה, היא השאירה את Pillow חצי טעון: ``PIL.Image`` נמחק,
והתוספים שלו (``PIL.JpegImagePlugin`` ואחרים) נשארו בזיכרון. הטסט הבא שייבא את Pillow קיבל
``PIL.Image`` חדש בלי אף פורמט רשום, ו-``Image.open`` נכשל ב-``UnidentifiedImageError``.
זה הפיל את ``test_link_preview_tags_point_to_absolute_urls_and_a_servable_image`` בהרצה
הסדרתית של ``deploy.yml``.

כל שינוי ב-``sys.modules`` עובר דרך ``monkeypatch``, שמחזיר בסוף הטסט את הערכים
הקודמים, כולל ``code_processor`` המקורי.
"""

import importlib
import sys

# החבילות שהייבוא שלהן ב-code_processor עטוף ב-try/except עם חלופה.
OPTIONAL_PACKAGES = ("cairosvg", "textstat", "langdetect", "PIL", "pygments")


def _block_package(monkeypatch, package):
    """חוסם את החבילה ואת כל תת-המודולים שלה שכבר טעונים.

    תת-מודולים נחסמים גם הם, כי ``from pygments.lexers import ...`` מחזיר את
    ``pygments.lexers`` מהזיכרון בלי לבדוק את ``pygments`` עצמו. היום הייבוא הראשון בכל
    בלוק הוא של החבילה, אבל הטסט לא צריך להישען על הסדר הזה.
    """
    monkeypatch.setitem(sys.modules, package, None)
    for name in list(sys.modules):
        if name.startswith(package + "."):
            monkeypatch.setitem(sys.modules, name, None)


def test_code_processor_imports_without_optional_deps(monkeypatch):
    # קודם טוענים את code_processor כרגיל, עם הספריות. כך כל מה שהוא מייבא (config,
    # cache_manager ועוד) כבר בזיכרון במצבו הרגיל, והחסימה למטה לא יכולה להיתקע בהם.
    # בלי זה, כשהטסט רץ לבד, הם היו נטענים לראשונה בזמן החסימה ונשארים כך לטסטים הבאים.
    importlib.import_module("code_processor")

    # highlight_code שומר תוצאות בקאש של cache_manager. את הקאש מרוקן לפני ואחרי כל טסט
    # ה-fixture האוטומטי _reset_cache_manager_state_between_tests ב-conftest.py שבשורש,
    # ולכן תוצאת החלופה לא נשארת לטסטים הבאים.
    for package in OPTIONAL_PACKAGES:
        _block_package(monkeypatch, package)

    # מוחקים את code_processor מהזיכרון, כדי שהייבוא הבא יריץ את המודול מחדש עם החסימה.
    monkeypatch.delitem(sys.modules, "code_processor")
    mod = importlib.import_module("code_processor")

    # בקרה: החסימה עבדה, והחלופה של כל ספרייה ב-OPTIONAL_PACKAGES פעילה. בלי זה הטסט היה
    # עובר גם כשהספריות נטענות.
    assert mod.cairosvg is None
    assert mod.textstat is None
    # langdetect אמיתי מחזיר קוד שפה מהפרופילים שלו, ואין ביניהם "text" (נבדק ב-langdetect 1.0.9).
    assert mod.detect("hello world") == "text"
    assert mod.Image is None and mod.ImageDraw is None and mod.ImageFont is None
    assert mod.highlight is None and mod.HtmlFormatter is None

    cp = mod.code_processor
    ok, cleaned, _msg = cp.validate_code_input("print('hi')", filename="x.py")
    assert ok is True
    assert cleaned == "print('hi')"
    # בלי pygments אין lexer, וההדגשה מחזירה את הקוד עטוף ב-<code>.
    assert cp.highlight_code("print('ok')", "python", output_format="html") == "<code>print('ok')</code>"

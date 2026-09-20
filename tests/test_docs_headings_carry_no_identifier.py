"""ההנחה שכל ההתאמה-לפי-מזהה נשענת עליה, כטסט ולא כמדידה חד-פעמית.

``find_sections`` מתאים שאילתה בצורת מזהה (``K11``, ``U3``) לכותרת שנפתחת
באותו מזהה. הטענה שהשינוי הזה **אינו נוגע בתיעוד של הריפו הזה** נכונה רק
בזכות עובדה אחת על הקורפוס: אף כותרת ב-``docs/`` אינה נפתחת במזהה, ולכן
הענף אינו נדלק כאן אף פעם.

**זו עובדה, לא חוק — ואיש אינו שומר עליה.** חלק מהקורפוס נוצר ב-autodoc
משמות מודולים, והצורה ``md5 package`` היא מזהה תקף לכל דבר. הטסט הזה הופך
את העובדה למשהו ש-CI מגן עליו: ביום שכותרת כזו תיכנס, הוא ייפול ויגיד
שההתנהגות של ``codekeeper_docs_get_section`` על אותו עמוד השתנתה — במקום
שזה יתגלה מסוכן שקיבל תשובה מוזרה.

הוא **אינו** מחליף את ``scripts/docs_section_zero_diff.py``: הסקריפט מצלם
מה הכלי מחזיר בפועל, והטסט אוכף את ההנחה. הראשון הוא ראיה, השני הוא שער.
"""

from pathlib import Path

import pytest

pytest.importorskip("docutils")

from services import doc_sections, rst_parser  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def _headings_with_identifier(root: Path | None = None) -> tuple[list[str], int]:
    """הכותרות שנפתחות במזהה, וכמה כותרות נסרקו בסך הכול.

    ``root`` הוא פרמטר ולא קבוע, כדי שאפשר יהיה לכוון את **אותו** אוסף
    ל-``tmp_path`` ולהראות שהוא מסוגל ליפול. בדיקה שרצה רק על הקורפוס
    האמיתי, שבו התשובה תמיד ריקה, אינה מבדילה בין "אין מזהים" לבין
    "האוסף לא מוצא מזהים".
    """
    offenders: list[str] = []
    total = 0
    for rst in sorted((root or DOCS).rglob("*.rst")):
        if "_build" in rst.parts:
            continue
        try:
            doc = rst_parser.parse_document(rst.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - קובץ פגום הוא ממצא, לא דילוג
            pytest.fail(f"{rst} אינו נפרסר: {exc!r}")
        for sec in doc.sections:
            total += 1
            identifier = doc_sections._leading_identifier(sec.title)
            if identifier is not None:
                rel = rst.relative_to(root or DOCS).as_posix()
                offenders.append(f"{rel}:{sec.heading_line}: {sec.title!r} ← {identifier!r}")
    return offenders, total


def test_no_heading_in_the_docs_corpus_opens_with_an_identifier():
    """אף כותרת ב-``docs/`` אינה נפתחת במזהה — ולכן ענף המזהה אינו נדלק כאן."""
    offenders, total = _headings_with_identifier()

    # תיקייה שמחזירה אפס כותרות היא כישלון ולא מעבר: הטסט איבד את מה שהוא מודד.
    assert total > 1000, f"נסרקו רק {total} כותרות תחת {DOCS} — האוסף שבור"
    assert not offenders, (
        "כותרת בתיעוד נפתחת במזהה, ולכן ``section=`` בצורת מזהה מתנהג עליה "
        "אחרת ממה שמתועד:\n  " + "\n  ".join(offenders) +
        "\nהריצו את scripts/docs_section_zero_diff.py כדי לראות מה בדיוק השתנה, "
        "והצהירו על השינוי — אל תסירו את הבדיקה."
    )


def test_the_scan_falls_on_a_realistic_autodoc_heading(tmp_path):
    """הבדיקה מסוגלת ליפול, ועל הצורה שבאמת עלולה להיכנס.

    ``md5 package`` אינה דוגמה מומצאת — זו בדיוק הצורה ש-autodoc מייצר
    משם מודול, ושלוש אותיות ואחריהן ספרה הן מזהה תקף.

    **ושתי בקרות נגדיות, שכל אחת יושבת על גבול אחר של הצורה** — כי בקרה
    שאינה יכולה להיתפס אינה בקרה. ``html5 spec`` מחטיא ב**אות אחת**
    (ארבע אותיות), והוא מה שנתפס ברגע שמישהו ירחיב את הצורה ל-``{1,4}``;
    ``i18n package`` מחטיא מסיבה אחרת לגמרי — הספרות אינן אחרונות — ולכן
    הרחבת מספר האותיות אינה נוגעת בו. הראשון נמדד: בלעדיו מוטציה שמרחיבה
    את הצורה שרדה את הטסט הזה.
    """
    (tmp_path / "ok.rst").write_text(
        "i18n package\n============\n\nגוף\n\n"
        "html5 spec\n----------\n\nגוף\n\n"
        "Plain heading\n-------------\n\nגוף\n",
        encoding="utf-8")
    (tmp_path / "autodoc.rst").write_text(
        "md5 package\n===========\n\nגוף\n", encoding="utf-8")

    offenders, total = _headings_with_identifier(tmp_path)

    assert total == 4, total
    assert len(offenders) == 1, offenders
    assert "md5 package" in offenders[0] and "'md5'" in offenders[0]
    assert all("i18n" not in o and "html5" not in o for o in offenders), (
        f"בקרה נגדית נתפסה — צורת המזהה רחבה מהכלל: {offenders}"
    )

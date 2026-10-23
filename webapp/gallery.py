"""הגלריה הציבורית (``/gallery``): צילומי מסך של CodeKeeper, אחד בכל פעם, עם כותרת ומשפט הסבר.

:data:`GALLERY_SLIDES` הוא המקום היחיד שקובע מה מוצג ובאיזה סדר — כל צילום הוא שורה אחת. ``image`` הוא שם קובץ תחת ``webapp/static/gallery/``, ואת הקבצים שם מייצר ``scripts/build_gallery_image.py`` מצילום המסך המקורי (צילומי המקור אינם נשמרים בענף הראשי). ``alt`` הוא תיאור של מה שרואים בתמונה, לקורא מסך ולמי שהתמונה לא נטענה אצלו — לא חזרה על הכותרת.

תמונת התצוגה המקדימה של הקישור בוואטסאפ ובטלגרם (``og:image``) היא JPEG של הצילום הראשון ברשימה, בקובץ נפרד לידו (:func:`share_image`), חתוך ל-``SHARE_SIZE`` שבסקריפט. מי שמחליף את הצילום הראשון מריץ עליו את הסקריפט עם ``--share``; ``tests/test_gallery_page.py`` נופל כשהקובץ חסר או לא בגודל.

התיעוד: ``docs/webapp/gallery.rst``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class GallerySlide:
    image: str
    title: str
    desc: str
    alt: str


GALLERY_SLIDES: tuple[GallerySlide, ...] = (
    GallerySlide(image="sticky-notes.webp", title="פתקים צפים (Sticky Notes)", desc="הצמדת פתקים ישירות למסמכי ה-Markdown של הפרויקט, בדיוק איפה שצריך אותם.", alt="מסמך Markdown בתצוגה של CodeKeeper, ועליו פתק צהוב צף שמוצמד לטקסט, עם רשימה ועם טבלה בכתב יד."),
    GallerySlide(image="note-threads.webp", title="שרשורי תגובות מול ה-AI", desc="שיתוף פעולה ישיר: המפתח וסוכן הקוד מנהלים דיון וסוגרים משימות בתוך הפתק.", alt="פתק על מסמך Markdown עם חלונית 'שרשור 1' פתוחה: תגובה של המשתמש, תשובה של סוכן הקוד מתחתיה, ותיבה לכתיבת תשובה עם הכפתורים 'שליחה בלי פתיחה' ו'שליחה ופתיחה מחדש'."),
    GallerySlide(image="code-view.webp", title="תצוגת קוד מתקדמת", desc="קריאה נוחה ונקייה של קבצי הפרויקט, כולל צביעת תחביר (Syntax Highlighting).", alt="הקובץ rate_limiter.py מוצג בבלוק קוד של Python עם צביעת תחביר, ומעליו פסקת הסבר בעברית."),
    GallerySlide(image="collections.webp", title="ארגון לפי אוספים", desc="מסך האוספים שמאפשר לסדר קבצים, מסמכים וערכות נושא (Themes) בתיקיות מסודרות.", alt="עמוד האוספים: בצד רשימת האוספים עם מספר הפריטים בכל אחד, ובמרכז האוסף 'ערכות נושא' עם כרטיס לכל קובץ JSON של ערכת נושא."),
    GallerySlide(image="boards.webp", title="לוחות חופשיים (Boards)", desc="משטח עבודה חופשי לניהול משימות, טבלאות, באגים ומחשבות במקום אחד נגיש.", alt="לוח פתקים ועליו פתקים צבעוניים: רשימת משימות עם תיבות סימון, טבלת מחירים, תיבות הדגשה של אזהרה, סכנה, חשוב ומידע, ופתקים של טקסט חופשי."),
    GallerySlide(image="markdown-toc.webp", title="תוכן עניינים צף", desc="במסמכי מארקדאון לניווט מהיר ונוח בתוך המסמך, ניתן להסתיר ולהחזיר בקלות.", alt="מסמך Markdown ובצידו חלונית 'תוכן עניינים' צפה עם רשימת הכותרות של המסמך, והכותרת שקוראים בה עכשיו מסומנת."),
    GallerySlide(image="agent-instructions.webp", title="בלוק ההנחיות לסוכן", desc="הנחיות שמנסחים כאן מגיעות ל-Claude Code בתחילת הסשן הבא, ובכל resume של הסשן.", alt="הכרטיס 'הוראות לסוכן' בעמוד ההגדרות: פסקת הסבר, תיבת טקסט עם הנחיות לסוכן, מונה בייטים וכפתור שמירה."),
)


def share_image(slide: GallerySlide) -> str:
    """שם קובץ ה-JPEG לתצוגה המקדימה של הקישור: אותו שם כמו התמונה, עם ``.jpg``."""
    return str(PurePosixPath(slide.image).with_suffix(".jpg"))

"""קישור שמוביל לעמוד נפתח בלשונית חדשה — הכלל של צד השרת, והרחבה של Python-Markdown שמחילה אותו.

**הכלל עצמו** הוא אותו כלל של ``webapp/static/js/md-link-target-plugin.js`` (``opensInNewTab``),
שמותקן בכל רנדרר של markdown-it בדפדפן. ההסבר המלא — מה נפתח בלשונית חדשה, מה לא, ולמה — כתוב שם,
ולא חוזר כאן. בקצרה: :func:`opens_in_new_tab` מחזיר ``True`` לכתובת בסכמה ``http`` או ``https``
ולכתובת בלי סכמה, ו-``False`` לעוגן (``#...``), ל-``href`` ריק ולכל סכמה אחרת (``mailto:``, ``tel:``).
שתי השפות נבדקות מול אותה טבלה, ``tests/fixtures/md_link_target_cases.json`` — ב-``tests/test_md_link_target.py``
וב-``tests/md-link-target-plugin.test.js`` — כדי שהעותק השני של הכלל לא ייסחף (R6).

**הצרכנים בצד השרת** — שני הרנדררים שבונים ``markdown.Markdown``: ``_render_markdown_preview``
ב-``webapp/app.py`` (מצב קריאה, ומסלול הגיבוי של התצוגה החיה כשהרינדור בדפדפן נכשל) ו-``markdown_to_html``
ב-``services/styled_export_service.py`` (הייצוא המעוצב כש-``STYLED_EXPORT_BROWSER_RENDER`` כבוי). שני המסננים
שאחריהם כבר מתירים ``target`` ו-``rel`` על ``a`` (``_LIVE_PREVIEW_ELEMENT_ATTRS`` ב-``webapp/app.py``,
``ALLOWED_ATTRS`` ב-``services/styled_export_service.py``).

**למה ה-``Treeprocessor`` רץ אחרי ``unescape`` ומפענח את הכתובת** (נקרא ב-``markdown`` 3.9,
``requirements/base.txt``):

- ``InlineProcessor`` (עדיפות 20 ב-``build_treeprocessors``, ``markdown/treeprocessors.py``) הוא שיוצר את
  אלמנטי ה-``a``, ו-``toc`` (5) מוסיף את קישורי תוכן העניינים. ``UnescapeTreeprocessor`` (0) מחזיר תווים
  שנכתבו עם ``\\`` — גם בערכי מאפיינים — מהצורה ``STX<קוד>ETX``. לפני כן ``[x](\\#a)`` היה נראה כאן כמו
  כתובת בלי סכמה. לכן העדיפות שלילית: אחרי כולם.
- קישור מייל אוטומטי (``<a@b.c>``, ``AutomailInlineProcessor`` ב-``markdown/inlinepatterns.py``) שומר את
  ה-``href`` כרצף של ``util.AMP_SUBSTITUTE + '#<קוד>;'`` לכל תו, ו-``AndSubstitutePostprocessor``
  (``markdown/postprocessors.py``) הופך אותו ל-``&#<קוד>;`` רק אחרי שהעץ נכתב למחרוזת. בלי הפענוח
  ב-:func:`_tree_href` הוא היה נראה כאן ככתובת בלי סכמה, ומקבל לשונית חדשה כמו עמוד. הפענוח הופך רק את
  הרצף הזה לתו, כמו שהדפדפן יקרא את ``&#<קוד>;``, ולא נוגע ב-``&`` אחר.

ייבוא קל בלבד: ``re`` ו-``markdown``; בזמן ייבוא רצה רק קומפילציה של הביטויים.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as etree

from markdown import util
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

#: סכמה לפי RFC 3986, סעיף 3.1. אותו ביטוי בדיוק ב-``SCHEME_RE`` של ``webapp/static/js/md-link-target-plugin.js``.
SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.-]*):", re.IGNORECASE)
NEW_TAB_SCHEMES = frozenset({"http", "https"})
NEW_TAB_REL = "noopener noreferrer"

#: תו שקודד בקישור מייל אוטומטי: ``util.AMP_SUBSTITUTE`` ואחריו ``#<קוד>;`` (``AutomailInlineProcessor``).
_AMP_CHAR_REF_RE = re.compile(re.escape(util.AMP_SUBSTITUTE) + r"#(\d+);")

#: אחרי ``unescape`` (עדיפות 0), האחרון בתור. ההסבר ב-docstring של המודול.
TREEPROCESSOR_PRIORITY = -10


def opens_in_new_tab(href: object) -> bool:
    """האם קישור עם ה-``href`` הזה נפתח בלשונית חדשה.

    הכלל וההסבר — ב-docstring של המודול וב-``md-link-target-plugin.js``.
    """
    if not isinstance(href, str) or href == "" or href.startswith("#"):
        return False
    match = SCHEME_RE.match(href)
    if match is None:
        return True
    return match.group(1).lower() in NEW_TAB_SCHEMES


def _tree_href(value: str) -> str:
    """ה-``href`` כמו שהדפדפן יקרא אותו, מהערך שבעץ: התווים שקישור מייל אוטומטי קידד חוזרים להיות תווים."""
    return _AMP_CHAR_REF_RE.sub(lambda m: chr(int(m.group(1))), value)


class _LinkTargetTreeprocessor(Treeprocessor):
    def run(self, root: etree.Element) -> None:
        for link in root.iter("a"):
            href = link.get("href")
            if href is not None and opens_in_new_tab(_tree_href(href)):
                link.set("target", "_blank")
                link.set("rel", NEW_TAB_REL)


class LinkTargetExtension(Extension):
    """מתקינה את הכלל במופע של ``markdown.Markdown``: ``Markdown(extensions=[..., LinkTargetExtension()])``."""

    def extendMarkdown(self, md) -> None:  # noqa: N802 — השם שהספרייה קוראת לו
        md.treeprocessors.register(_LinkTargetTreeprocessor(md), "link_target", TREEPROCESSOR_PRIORITY)

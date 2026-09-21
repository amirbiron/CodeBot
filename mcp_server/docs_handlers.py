"""Pure handler for the public docs tool ``codekeeper_docs_get_section``.

Same contract as ``repo_handlers.py``: a plain function, no MCP/Starlette imports,
clamped inputs, ``{"ok": False, "error": "..."}`` rejections. **Not** admin-gated —
this is a public tool; the tool body deliberately omits ``require_admin``.

It reuses ``RepoBackend.get_file`` to read the raw text from the mirror (that already
handles ref-default, secrets policy, and the ``sync_in_progress`` retry contract), then
the parser that matches the file's suffix — ``services.rst_parser`` for ``.rst``,
``services.md_parser`` for ``.md``. **שני הפארסרים ממלאים את אותו מודל**
(``services.doc_sections``), ולכן מעבר לבחירת המודול אין כאן מסלול קוד שני: כל
פונקציות העץ נקראות מ-``doc_sections`` ישירות. Guiding rule: never return only
"not found" — no section ⇒ TOC; missing ⇒ TOC + suggestions; duplicate ⇒
candidates with breadcrumb.
"""

from __future__ import annotations

import logging
import os
import posixpath
from dataclasses import dataclass
from types import MappingProxyType, ModuleType
from typing import Any, Mapping, NamedTuple

from services import doc_sections, md_parser, rst_parser
from .handlers import _clamp

logger = logging.getLogger(__name__)

MAX_CHARS_DEFAULT = 12_000
MAX_CHARS_MAX = 100_000
MAX_CHARS_MIN = 500

#: תקרת אורך ל-``path``, **הקלט החיצוני היחיד כאן שלא הייתה עליו תקרה**.
#: ``max_chars`` ו-``offset`` עוברים ``_clamp``; המחרוזת לא עברה כלום,
#: ולכן העבודה שנעשית עליה במורד הזרם גדלה עם מה שהקורא שולח.
#:
#: **מה נמדד.** ``repo_policy.is_denied`` — ההוראה הראשונה ב-
#: ``RepoBackend.get_file`` — סורקת כל רכיב בנתיב מול כל תבנית, ולכן
#: נתיב של 400KB עלה 608ms לעומת 2.4ms לפני שסריקת הרכיבים נוספה. הכלי
#: הזה ציבורי (אין ``require_admin``), ולשרת אין תקרת גוף בקשה ואין
#: הגבלת קצב — אישו #3430.
#:
#: **והמספר נגזר ממדידה ולא נבחר.** הנתיב הארוך ביותר בשלוש המראות
#: שהמדיניות חלה עליהן: ``amir-bug-patterns`` 53 תווים, CodeBot 97,
#: ו-Han 117. התקרה כאן היא פי 35 מהארוך שבהם, והיא גם ``PATH_MAX``
#: של לינוקס — כלומר גבול שכלי גיט וקבצים ממילא חיים בתוכו. אפס קבצים
#: אמיתיים נחסמים.
#:
#: זו הקטנת משטח ולא תחליף להגבלת קצב: היא חוסמת את ההגברה לכל בקשה,
#: ולא את מספר הבקשות.
MAX_PATH_CHARS = 4096

DEFAULT_DOCS_REPO = "CodeBot"
_TOC_MAX = 400  # תקרת פריטי TOC בתשובה (הגנת גודל)

#: תקרת המועמדים בתשובת ``ambiguous_section``. **אותו מספר כמו
#: ``doc_sections.MAX_IDENTIFIER_SUGGESTIONS``, ומאותה סיבה:** רשימת המועמדים
#: היא מלאי בסדר הופעה ולא דירוג, ולכן חיתוך שלה מסתיר פריטים בלי קריטריון —
#: והתקרה גבוהה מספיק כדי שכל עמוד אמיתי ייענה במלואו (כותרת כפולה בקורפוס
#: חוזרת פעמיים או שלוש). מה שהיא עוצרת נמדד בסקירת #3425: עמוד סינתטי של
#: 512KB עם 13,030 כותרות שנפתחות ב-``K11.`` החזיר 13,030 מועמדים — 1,393,787
#: בתים ושיא הקצאה של 12.6MB — על שאילתה בת שלושה תווים, וזה היה השדה היחיד
#: בתשובה בלי גבול (``toc`` ב-``_TOC_MAX``, ‏``suggestions``
#: ב-``MAX_IDENTIFIER_SUGGESTIONS``). הענף נדלק רק מכותרות שנושאות מזהה, ומאז
#: #3428 הקורפוס שנושא מזהים (``amir-bug-patterns``) מוגש. השוויון בין שני
#: המספרים מקובע בטסט, כמו שני גבולות האאוטליין והפארסר. אישו #3426.
_CANDIDATES_MAX = 50

#: הסיומת ← **המודול** שמפרסר אותה. זהו המקום היחיד שאומר איזה פורמט הכלי
#: יודע לקרוא בכלל, ו-``DOCS_PATH_POLICY`` למטה אומר מי מהם מוגש בכל ריפו.
#: שתי שאלות שונות, ולכן שתי טבלאות — ו-``_validate_policy_tables`` קושר
#: ביניהן בייבוא כדי ששתיהן לא ייסחפו בשקט.
#:
#: **מודול ולא פונקציה, וזה נושא משקל.** ``parser.parse_document`` נפתר בזמן
#: הקריאה, ולכן ``monkeypatch.setattr(docs_handlers.rst_parser, "parse_document",
#: spy)`` בטסטים נתפס. טבלה שהייתה מחזיקה ``rst_parser.parse_document`` הייתה
#: קופאת על הפונקציה המקורית וה-spy היה נעקף **בשקט** — בלי שאף טסט קיים
#: ייפול. ``tests/test_mcp_docs_handlers.py::test_the_parser_table_holds_modules_
#: so_a_monkeypatch_on_the_module_is_seen`` מקבע את זה.
_PARSER_TABLE: dict[str, ModuleType] = {".rst": rst_parser, ".md": md_parser}
#: **מה שמיוצא אינו ניתן לשינוי** (#3432, SUGG-021): ``_validate_policy_tables``
#: רץ פעם אחת בייבוא, ושינוי של הטבלה אחריו עוקף אותו בשקט. ``MappingProxyType``
#: הופך את ההבטחה לתכונה — ``_PARSERS[".txt"] = x`` הוא ``TypeError`` — והטבלה
#: שמתחת, ``_PARSER_TABLE``, נשארת התפר לטסטים (``monkeypatch.setitem`` עליה
#: נראה דרך הפרוקסי מיד, ומוחזר בסוף הטסט).
_PARSERS: Mapping[str, ModuleType] = MappingProxyType(_PARSER_TABLE)


@dataclass(frozen=True)
class _DocsPathPolicy:
    """איפה גרים קובצי התיעוד של ריפו אחד, ובאיזו צורה.

    **שדה אחד לכל שאלה, ולא רשימה.** הגרסה הראשונה הצהירה על ``roots``
    ו-``suffixes`` כרשימות ועל מוסכמה ש"אינדקס 0 הוא ברירת המחדל". אף
    רשומה לא החזיקה יותר מערך אחד, והריבוי גבה מחיר אמיתי: שתי
    ``@property`` שכל תפקידן לתת שם לאינדקס 0, שתי לולאות שרצו איטרציה
    אחת, ותיאור הפרמטר ב-``server.py`` שנגזר מ-``roots[0]`` בלבד — כלומר
    שורש שני היה **נעלם מהתיאור שהסוכן קורא** בלי שאף בדיקה תשים לב.
    היום יש שני שדות, אין מוסכמת סדר, ואין מאיפה לסחוף.

    ``root`` ריק פירושו **שורש הריפו**: כל נתיב יחסי שאינו יוצא החוצה.
    זו אינה "בלי מדיניות" — הסיומת עדיין מסננת, וזה מה שמונע
    מ-``.claude/settings.json`` להיות נגיש.

    ריפו שיצטרך באמת שני שורשים או שני פורמטים ירחיב את זה ביום שהוא
    יתווסף, עם הצרכן שמצדיק את ההרחבה מול העיניים.
    """

    root: str
    suffix: str


#: הריפו ← איפה התיעוד שלו. **הטבלה הזאת היא מה שהקוד יודע לקרוא**;
#: ``MCP_DOCS_REPO`` הוא מה שהפריסה **מתירה**. ריפו חייב לעבור את שניהם,
#: וריפו שנמצא ב-ENV ואינו כאן נדחה ב-``repo_not_configured`` — הוא אינו
#: נופל לברירת מחדל מתירנית, מאותו נימוק שבגללו ``is_denied`` נכשל-סגור.
#:
#: .. danger::
#:
#:    **הרחבת גבול ה-IDOR כאן היא מכוונת, ולא תוצר לוואי.** הכלי ציבורי —
#:    כל משתמש מאומת קורא לו, בלי ``require_admin`` — ומה ששמר על הגבול עד
#:    היום היה ה**צירוף** של רשימת ההיתר ושל ההגבלה ל-``docs/*.rst``.
#:    ``amir-bug-patterns`` מקבל כאן את **שורש הריפו** עם ``**/*.md``, כלומר
#:    כל קובץ ``.md`` בו, בכל עומק, כולל תחת ``.claude/``. זה אושר על ידי
#:    בעל הפרויקט, והריפו ציבורי ב-GitHub. נספר לפני ההחלטה: 95 קבצים, 93
#:    מהם ``.md`` וכולם מסמכי דפוסים שנועדו לקריאה על ידי סוכן; שני הקבצים
#:    שאינם ``.md`` מסוננים ממילא על ידי הסיומת.
#:
#:    **ומה שהטבלה הזאת סומכת עליו הוא שם, ולא כתובת.** ``RepoBackend``
#:    פותר מראה לפי **שם**; הקשר בין השם ל-URL חי ברשומת ``repo_metadata``
#:    במונגו, ו-``mcp_server/repo_autosync.py`` משכפל ממנה. כלומר מי
#:    שיכול לכתוב לאוסף הזה — בעל הפריסה — יכול גם להחליף את מה שמוגש
#:    תחת השם הזה, והכלי הציבורי יגיש אותו בלי לשאול. זה מקובל כאן כי
#:    מדובר באותו אדם שמחליט מה נכנס לטבלה למעלה; מה שאינו מקובל הוא
#:    שההסתמכות תישאר לא כתובה.
#:
#:    מה ש**לא** משתנה: ``mcp_server.repo_policy.is_denied`` הוא ההוראה
#:    הראשונה ב-``RepoBackend.get_file`` וחל על המסלול הזה במלואו, כך
#:    ש-``secrets.md``, ``credentials.md`` ו-``.env*`` חסומים גם כאן.
_DOCS_PATH_POLICY_TABLE: dict[str, _DocsPathPolicy] = {
    "CodeBot": _DocsPathPolicy(root="docs", suffix=".rst"),
    "amir-bug-patterns": _DocsPathPolicy(root="", suffix=".md"),
}
#: קריאה בלבד, מאותו נימוק שכתוב ליד ``_PARSERS``: הוולידציה בייבוא היא הבטחה
#: רק אם הטבלה אינה משתנה אחריה. הטסטים שמוסיפים ריפו סינתטי עושים זאת על
#: ``_DOCS_PATH_POLICY_TABLE``.
DOCS_PATH_POLICY: Mapping[str, _DocsPathPolicy] = MappingProxyType(_DOCS_PATH_POLICY_TABLE)


def _validate_policy_tables() -> None:
    """נופל **בזמן הייבוא** על טבלה פגומה, ולא בתוך בקשה של משתמש.

    התקדים הוא ``md_parser._build_parser``: ``ruler.before("front_matter", ...)``
    נופל ב-``KeyError`` בייבוא כשהתוסף לא נרשם, וה-docstring שם מנמק במפורש
    למה זה עדיף על כשל שקט בזמן פרסור. כאן הכשל השקט היה ``KeyError`` על
    ``_PARSERS`` באמצע קריאה — כלומר 500 למשתמש, במקום שרת שלא עולה.

    ``RuntimeError`` ולא ``assert``, כי ``assert`` נמחק תחת ``-O``.

    **מה שהצמצום לשדות סקלריים כבר לקח מכאן:** בדיקת "רשימה ריקה" נעלמה,
    כי אין רשימה, ושתי הלולאות הפכו לבדיקות בודדות. מה שנשאר הוא הבדיקה
    היחידה שיש לה מצב כשל אמיתי — סיומת שמוצהרת ואין לה פארסר, כלומר
    סחיפה בין שתי טבלאות — ושתי בדיקות נרמול שמגינות מפני הקלדה בקבוע
    שלוש שורות מכאן.
    """
    for repo, policy in DOCS_PATH_POLICY.items():
        suffix = policy.suffix
        if not suffix.startswith(".") or suffix != suffix.casefold():
            raise RuntimeError(f"סיומת לא מנורמלת ב-{repo!r}: {suffix!r}")
        if suffix not in _PARSERS:
            raise RuntimeError(
                f"{repo!r} מצהיר על {suffix!r} ואין לו פארסר ב-_PARSERS")
        root = policy.root
        if root and (root.startswith("/") or root != posixpath.normpath(root)):
            raise RuntimeError(f"שורש לא מנורמל ב-{repo!r}: {root!r}")


_validate_policy_tables()


class _ResolvedPath(NamedTuple):
    """או נתיב **עם הסיומת שהוכרעה לו**, או קוד סירוב.

    ``str | None`` הספיק כל עוד הייתה סיבת דחייה אחת. הצורה
    ``value-or-error-string`` שב-``repo_backend.normalize_line_range`` אינה
    עובדת כאן, כי הנתיב וקוד השגיאה שניהם ``str`` ו-``isinstance`` אינו
    מבדיל ביניהם. ארבעה קודים חיים כאן היום, אחד לכל דחייה: ``missing_path``
    (אין נתיב — ריק או עם NUL), ``path_too_long``, ``suffix_not_allowed``,
    ו-``path_outside_root`` (הנתיב תקין בצורתו ופותר אל מחוץ לשורש התיעוד;
    עד #3432 הוא חלק קוד עם ``missing_path``, והקורא לא ידע אם שכח נתיב או
    ניסה לצאת מהשורש).

    **ו-``suffix`` נישא ולא נגזר מחדש, וזה תיקון לבאג שנתפס בבדיקה.**
    הגרסה הראשונה קראה ל-``_suffix_of`` פעם שנייה על הנתיב המוגמר כדי
    לבחור פארסר — כלומר אותה שאלה נענתה משתי מחרוזות שונות, וזה בדיוק מה
    ש-``_suffix_of`` מצהיר שהוא בא למנוע. נמדד: ``path=".."`` הופך
    ל-``"...md"``, ו-``posixpath.splitext("...md")`` מחזיר סיומת **ריקה**
    (נקודות מובילות אינן מפריד סיומת), ולכן הגזירה השנייה נתנה תשובה
    אחרת מהראשונה והפילה ``KeyError`` מתוך בקשה של משתמש.
    """

    path: str | None
    suffix: str | None
    error: str | None


def _allowed_docs_repos() -> list[str]:
    """רשימת הריפואים המותרים לכלי (CSV ב-MCP_DOCS_REPO), עם fallback ל-CodeBot."""
    raw = os.getenv("MCP_DOCS_REPO", DEFAULT_DOCS_REPO) or DEFAULT_DOCS_REPO
    repos = [r.strip() for r in raw.split(",") if r.strip()]
    return repos or [DEFAULT_DOCS_REPO]


def _resolve_docs_repo(repo: str | None) -> str | None:
    """ברירת מחדל = הריפו הראשון ב-allowlist; repo מפורש מותר רק אם ב-allowlist (אחרת None).

    הכלי ציבורי — בלי האכיפה הזו כל משתמש מאומת יכול לקרוא מכל ריפו ב-mirror (IDOR).

    **והכניסה הראשונה ב-ENV קובעת יותר ממה שנראה:** מאז שלכל ריפו יש מדיניות
    נתיבים משלו, היא קובעת גם את השורש וגם את הפורמט של קריאה שלא נקבה בריפו.
    שינוי סדר ב-``MCP_DOCS_REPO`` הוא שינוי התנהגות, לא סידור.
    """
    allowed = _allowed_docs_repos()
    r = (repo or "").strip()
    if not r:
        return allowed[0]
    return r if r in allowed else None


def _suffix_of(path: str) -> str:
    """סיומת הנתיב, מנורמלת ברישיות; ``""`` כשאין.

    **מקור אחד לשתי השאלות** — "האם הריפו מגיש את הצורה הזאת" ו"איזה מודול
    מפרסר אותה". שתי גזירות של אותה סיומת היו נסחפות זו מזו ברישיות.

    ``casefold`` ולא השוואה רגישת-רישיות, וזו הקונבנציה שכבר קיימת בריפו:
    ``mcp_server/outline.py::_scanner_for`` מנרמל באותה צורה בדיוק, וההערה
    מעל ``_SCANNERS`` מנמקת אותה. הערך המנורמל משמש **רק** לחיפוש בטבלאות
    ולעולם לא לחיתוך הנתיב עצמו, ולכן ``casefold`` שמשנה אורך (``ß`` ←
    ``ss``) אינו יכול להזיז שום אינדקס.
    """
    return posixpath.splitext(path)[1].casefold()


def _is_under(norm: str, root: str) -> bool:
    """האם נתיב **מנורמל** יושב תחת ``root``. ``root`` ריק = שורש הריפו.

    **הגבול נבדק כיחידה ולא כרצף תווים.** זו מחלקת הבאג ``K16`` ב-
    ``amir-bug-patterns`` (``path-prefix-not-boundary``): ``norm.startswith("docs")``
    לבדו מקבל את ``docsecret.rst``, שאין לו שום קשר היררכי ל-``docs/``.
    המפריד כתוב במפורש, וזרוע השוויון היא ההגדרה של "התיקייה עצמה".

    **ושורש ריק אינו "הכול".** נתיב מוחלט, ``..``, ונתיב שמטפס מעל שורש
    הריפו — כולם נדחים כאן. זה מה שהופך אותו ל"כל דבר בתוך הריפו" ולא
    ל"כל דבר בדיסק".
    """
    if not root:
        return (not norm.startswith("/")
                and norm != ".."
                and not norm.startswith("../"))
    return norm == root or norm.startswith(root + "/")


def _resolve_docs_path(path: str, policy: _DocsPathPolicy) -> _ResolvedPath:
    """נתיב מלא או slug קצר ← נתיב מנורמל שהריפו הזה מגיש.

    **סדר הפעולות אינו שרירותי, ושתי נקודות בו הן באגי אבטחה אם יזוזו:**

    1. ``strip``, דחיית ``\\x00``, **ודחיית אורך** — הערך מגיע מחוץ
       לתהליך, ושלוש הבדיקות האלה הן מה שמותר להניח עליו מכאן והלאה.
    2. הכרעת הסיומת: מותרת ← כמו שהיא; **פורמט אחר שהכלי מכיר** ← סירוב
       מפורש; כל דבר אחר ← חלק מה-slug, והסיומת מתווספת.
    3. **עגינה, על המחרוזת שלפני הנרמול.** זו הנקודה הראשונה:
       ``docs/../secrets`` נושא ``/`` ולכן אינו נעגן, ואחרי הנרמול הוא
       ``secrets.rst`` — מחוץ ל-``docs/``, ונדחה. מי ש"ינקה" את הקוד
       ויקדים את ``normpath`` יקבל ``secrets.rst`` בלי ``/``, יעגן אותו
       ל-``docs/secrets.rst``, **ויגיש אותו**.
    4. ``normpath`` — כאן, ורק כאן.
    5. הגבול מול השורש. זו הנקודה השנייה: ``startswith`` חשוף הוא
       ``K16``, ולכן הוא עטוף ב-``_is_under`` — ונתיב שנופל בה נדחה
       ב-``path_outside_root``, בשמו, ולא כ"נתיב חסר".
    """
    p = (path or "").strip().strip("/")
    if not p or "\x00" in p:
        return _ResolvedPath(None, None, "missing_path")
    if len(p) > MAX_PATH_CHARS:
        # **קוד משלו ולא ``missing_path``.** סירוב שאינו נוקב בסיבתו הוא
        # בדיוק ``blanket-policy-silent-block``: מבחוץ הוא נראה כמו נתיב
        # שגוי, והקורא מחפש את הטעות בשם הקובץ. ו-``silent-truncation-
        # at-sink`` אוסר את החלופה השנייה — לחתוך את הנתיב ולהמשיך
        # כאילו כלום. סירוב מוצהר הוא הצורה שהשארנו.
        return _ResolvedPath(None, None, "path_too_long")

    suffix = _suffix_of(p)
    if suffix != policy.suffix:
        if suffix in _PARSERS:
            # פורמט שהכלי מכיר, אבל לא זה שהריפו הזה מגיש. השלמה שקטה של
            # הסיומת כאן הייתה בונה ``docs/CRITICAL-PATTERNS.md.rst``
            # ומחזירה ``not_found`` על קובץ שקיים — כלומר סירוב שמתחזה
            # להיעדר, והקורא היה מחפש את הבאג במקום הלא נכון.
            return _ResolvedPath(None, None, "suffix_not_allowed")
        p = p + policy.suffix
        suffix = policy.suffix

    if policy.root and "/" not in p:
        p = policy.root + "/" + p

    norm = posixpath.normpath(p)
    if _is_under(norm, policy.root):
        return _ResolvedPath(norm, suffix, None)
    return _ResolvedPath(None, None, "path_outside_root")


def _capped(items: list, limit: int) -> tuple[list, bool]:
    """‏``(items, truncated)`` — הרשימה עד ``limit``, והאם באמת נחתכה.

    **פונקציה אחת לשני הגבולות של התשובה** (``toc`` ו-``candidates``), כדי
    שהשאלה "מתי הדגל נכון" תיענה במקום אחד: ``True`` רק כשהיו יותר מהתקרה,
    ולעולם לא על רשימה שבדיוק בגודלה — אותו גבול כמו ``Capped.append``
    ב-``_ceiling`` וכמו ``max_sections`` בפארסר.
    """
    if len(items) > limit:
        return items[:limit], True
    return items, False


def _toc(doc: doc_sections.Document) -> tuple[list, bool]:
    return _capped(doc_sections.build_toc(doc), _TOC_MAX)


def _line_of(exc: BaseException) -> dict:
    """``{"line": N}`` כשהחריגה נושאת מספר שורה, ו-``{}`` כשלא.

    **הצורה המותנית ולא שדה שקיים תמיד**, ומאותו נימוק בדיוק שבגללו
    ``suggestions_truncated`` ו-``remaining_chars`` מותנים: שדה שיופיע
    גם כשאין מה לשים בו מלמד את הקורא ש-``line: null`` הוא מצב אפשרי,
    והוא אינו.

    ``args`` ולא אטריביוט ייעודי, כי זה מה ששתי החריגות באמת מחזיקות —
    שתיהן נבנות ב-``raise X(n)``. בדיקת הטיפוס אינה נימוס: ``args``
    יכול להיות ריק אם מישהו יעלה אותן בלי ארגומנט, ואז ``args[0]``
    היה מפיל את הבקשה במקום להחזיר סירוב.
    """
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], int):
        return {"line": args[0]}
    return {}


def _section_ref(sec: doc_sections.Section) -> dict:
    return {"title": sec.title, "level": sec.level,
            "line_range": [sec.heading_line, sec.end_line]}


def docs_get_section(
    backend: Any,
    *,
    path: str,
    section: str | None = None,
    include_subsections: bool = True,
    max_chars: int = MAX_CHARS_DEFAULT,
    offset: int = 0,
    repo: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    # **הריפו נבדק לפני הנתיב.** אחרת קורא שנקב בריפו שאינו רשאי לגעת בו
    # היה לומד ממנו משהו: ``suffix_not_allowed`` מול ``missing_path`` מספר
    # לו מה הפורמט שהריפו ההוא מגיש.
    repo_name = _resolve_docs_repo(repo)
    if not repo_name:
        return {"ok": False, "error": "repo_not_allowed", "requested_repo": repo}
    policy = DOCS_PATH_POLICY.get(repo_name)
    if policy is None:
        # fail-closed: ה-ENV מתיר, והקוד אינו יודע איפה גר התיעוד שם. זו
        # תקלת הפעלה שרק מי שמחזיק את ההגדרות יכול לתקן, ולכן גם שורת לוג
        # ולא רק תשובה לקורא — התשובה מגיעה לסוכן, הלוג מגיע למפעיל.
        logger.warning(
            "MCP_DOCS_REPO מתיר ריפו שאין לו מדיניות נתיבים: %r", repo_name)
        return {"ok": False, "error": "repo_not_configured", "repo": repo_name}

    resolved = _resolve_docs_path(path, policy)
    if resolved.error == "suffix_not_allowed":
        # ``allowed_suffixes`` נשאר **רשימה** אף שהמדיניות מחזיקה סיומת
        # אחת: זה החוזה שהלקוח כבר קורא, וצמצום שדה בתשובה כדי להתאים
        # אותו לצורה הפנימית הוא שינוי שובר בלי שום תמורה לקורא.
        return {"ok": False, "error": "suffix_not_allowed", "repo": repo_name,
                "requested_path": path, "allowed_suffixes": [policy.suffix]}
    if resolved.error == "path_too_long":
        return {"ok": False, "error": "path_too_long", "repo": repo_name,
                "max_chars": MAX_PATH_CHARS, "actual_chars": len(path or "")}
    if resolved.error == "path_outside_root":
        # השורש כבר כתוב בתיאור הכלי לכל ריפו, ולכן אמירתו כאן אינה מגלה
        # דבר — היא רק חוסכת לקורא לחפש את הטעות בשם הקובץ.
        return {"ok": False, "error": "path_outside_root", "repo": repo_name,
                "root": policy.root}
    if not resolved.path:
        return {"ok": False, "error": "missing_path"}
    file_path = resolved.path

    max_chars = _clamp(max_chars, MAX_CHARS_MIN, MAX_CHARS_MAX, MAX_CHARS_DEFAULT)
    offset = _clamp(offset, 0, 10 ** 9, 0)

    # קריאה — reuse מלא של RepoBackend.get_file (ref default, מדיניות סודות, sync_in_progress).
    # **בלי ``lines`` ובלי ``outline`` בכוונה:** כך ``wants_slice`` הוא False, לא מועבר
    # ``max_size``, ותקרת 500KB של שירות המראה נשארת ההגנה היחידה על הפרסור.
    res = backend.get_file(repo=repo_name, path=file_path, ref=((ref or "").strip() or None))
    if not res.get("ok"):
        # not_found / invalid_input / path_denied / sync_in_progress — מוסיפים הקשר ומעבירים הלאה
        res.setdefault("repo", repo_name)
        res.setdefault("path", file_path)
        return res
    if res.get("status") != "ok":
        # binary / too_large — אין תוכן טקסט לפרסר
        return {"ok": False, "error": f"unreadable_{res.get('status')}",
                "repo": repo_name, "path": file_path, "file": res.get("file")}

    content = res.get("content") or ""
    file_meta = res.get("file") or {}
    # ההקשר נבנה **לפני** הפרסור, כי גם סירוב צריך לומר איזה קובץ, באיזה ריפו
    # ובאיזה commit. ``{"error": "too_many_sections"}`` לבדו אינו ניתן לפעולה.
    context: dict[str, Any] = {
        "repo": repo_name, "path": file_path,
        "ref": file_meta.get("ref"),
        "resolved_commit": file_meta.get("resolved_commit"),
    }

    # ``resolved.suffix`` ולא גזירה שנייה מ-``file_path``: ראו :class:`_ResolvedPath`.
    parser = _PARSERS[resolved.suffix]  # לעולם לא KeyError: ראו _validate_policy_tables

    # **שני הפרסרים רצים על ברירת המחדל שלהם, והכלי אינו מעביר תקרה.**
    # ברירת המחדל של ``max_sections`` בשניהם היא ``doc_sections.MAX_SECTIONS``
    # (50,000; מיושרת מאז #3420 — בין #3429 ל-#3420 ברירת המחדל של
    # ``rst_parser`` הייתה ``None`` והכלי העביר לו את ``_ceiling.MAX_SYMBOLS``
    # במפורש). העברה מפורשת מכאן הייתה עותק שני של החלטה שהפארסר כבר הכריע,
    # ו-``parser is rst_parser`` היה מקום שלישי שבו סמנטיקת הסיומת חיה. הטסט
    # שמקטין את התקרה עושה זאת בפרסר (``functools.partial``), לא כאן.
    #
    # מה שהתקרה עוצרת ב-RST (סקירת #3429): כותרת בת תו אחד בכל שורה ב-500KB
    # עולה 44.0MiB לפרסור אחד — יותר מ-35.2MiB שמאגר הקריאות מקצה לחוט
    # (``_PARSE_COST_BYTES`` ב-``server.py``) — ואיתה נעצרת ב-20.1MiB. אף
    # עמוד אמיתי אינו מתקרב: 500KB של העמוד הצפוף ביותר הם כ-3,300 סקשנים.
    #
    # **ומה שאף תקרה כאן אינה עוצרת, ונשאר פתוח:** Markdown עוין של שורות-
    # תבליט בלי כותרות — 500KB עולים 141MiB ו-2.3 שניות, ו-``MAX_SECTIONS``
    # סופר כותרות ולכן אינו נוגע בו. זה אישו #3391 ולא #3429.

    # **ה-``try`` הזה אינו ``K11``, וזה נכתב כדי שסקירה עתידית לא תגזור זאת
    # מחדש.** ``parse_document`` מתועד כ"ערוץ הכשל הוא חריגה בלבד": הוא אינו
    # מחזיר ``None`` ואינו מחזיר ``Document`` חלקי בכשל, ומפה ריקה היא הצלחה
    # תקינה של קובץ בלי כותרות. זה ה-false-positive ש-K11 מונה במפורש —
    # "פונקציות raise-on-error מתועדות, שם try/except הוא הערוץ הנכון".
    #
    # **ושתי החריגות מיובאות מ-``doc_sections`` ולא מ-``parser.X``.**
    # ``rst_parser`` אינו מרים את ``InconsistentLineEndings`` לעולם ואינו
    # מייצא אותה, וייצוא משם היה מצהיר על סירוב שאינו קיים. התפיסה אינה
    # מותנית במי שפרסר, כי תנאי כזה היה רשימה שנייה לסנכרן.
    #
    # **ומה שלא נתפס כאן, בכוונה:** ``TypeError`` של שני הפרסרים (מאז #3421
    # גם ``rst_parser`` מרים אותה, דרך ``doc_sections.require_str``) ו-
    # ``RuntimeError`` של ``md_parser``. שניהם אומרים "חוזה נשבר" ולא "הקלט
    # נדחה", ועטיפתם הייתה בדיוק ``widened-exception-scope``. ``content`` הוא
    # תמיד מחרוזת במסלול הזה, כי ``binary`` ו-``too_large`` נחסמו למעלה.
    #
    # תקרת המקביליות על הפרסור אינה כאן ואינה צריכה להיות: היא נגזרת מגודל
    # מאגר הקריאות, ומקומה ב-lifespan של השרת — נחת ב-#3429.
    #
    # **והמופע נקשר, כי הוא נושא את מספר השורה.** שתי החריגות נבנות עם
    # ארגומנט אחד — השורה (1-מבוססת) שגרמה לסירוב — וזו כל הסיבה שהן
    # חריגות ולא דגל. ``except X:`` בלי ``as`` זרק בדיוק את הערך היחיד
    # שאפשר לפעול לפיו, בתוך הבלוק שההערה מעליו מסבירה למה קוד שגיאה
    # לבדו אינו ניתן לפעולה.
    #
    # ``_line_of`` ולא ``exc.args[0]`` ישירות: חריגה שתיבנה מחר בלי
    # ארגומנט לא תפיל כאן ``IndexError`` באמצע בקשה.
    #
    # ``"max"`` הוא ``doc_sections.MAX_SECTIONS`` — המספר שהפרסר באמת השתמש
    # בו, בשני המסלולים, ולא עותק שלו ממודול אחר.
    try:
        doc = parser.parse_document(content)
    except doc_sections.InconsistentLineEndings as exc:
        return {"ok": False, "error": "inconsistent_line_endings",
                **context, **_line_of(exc)}
    except doc_sections.TooManySections as exc:
        return {"ok": False, "error": "too_many_sections",
                "max": doc_sections.MAX_SECTIONS, **context, **_line_of(exc)}

    return _answer_from_document(doc, context=context, section=section,
                                 include_subsections=include_subsections,
                                 max_chars=max_chars, offset=offset)


def _answer_from_document(
    doc: doc_sections.Document,
    *,
    context: dict[str, Any],
    section: str | None,
    include_subsections: bool,
    max_chars: int,
    offset: int,
) -> dict[str, Any]:
    """ארבע צורות התשובה של הכלי, מתוך מסמך שכבר נפרסר.

    **מה שנפרד מ-``docs_get_section`` (#3432, SUGG-020):** הפונקציה ההיא
    פותרת ריפו, פותרת נתיב, קוראת קובץ ובוחרת פארסר — ארבע החלטות שכל אחת
    מהן יכולה לסרב — ומכאן והלאה יש רק מסמך ושאלה. הזנב הזה הוא החלק שנפרד
    הכי נקי, ואפס-דיף על 208 קובצי ה-RST (``scripts/docs_section_zero_diff.py``)
    הוא מה שמוכיח שהוא רק זז.

    ארבע הצורות: ``toc`` כשאין ``section``; ``section_not_found`` עם הצעות;
    ``ambiguous_section`` עם מועמדים; ו-``section`` עם התוכן, השכנים
    ותת-הסקשנים. ``context`` הוא ``repo``/``path``/``ref``/``resolved_commit``
    שכל תשובה נושאת.
    """
    toc_items, toc_truncated = _toc(doc)

    # ``includes`` הוא שדה של פארסר: ``rst_parser`` ממלא אותו מיעדי
    # ``.. include::``, ול-Markdown אין צורה כזאת ולכן הוא **תמיד ריק**.
    # הוא נשאר ללא תנאי — אפס כאן אינו "לא בדקנו" אלא "אין מה לבדוק",
    # והשמטה הייתה שוברת קורא שכותב ``res["includes"]`` וגם הייתה מקום
    # שלישי שבו סמנטיקת הסיומת חיה.
    base: dict[str, Any] = {"ok": True, **context, "includes": list(doc.includes)}

    # בלי section → עץ כותרות (הכלי משמש גם לניווט)
    if not (section or "").strip():
        base.update({"mode": "toc", "toc": toc_items, "toc_truncated": toc_truncated,
                     "section_count": len(doc.sections)})
        return base

    matches = doc_sections.find_sections(doc, section)

    # לא נמצא → TOC מלא + הצעות קרובות (לעולם לא רק "לא נמצא")
    if not matches:
        # ``n`` מפורש, וזו אמירה ולא מספר שרירותי: **התשובה הזאת היא מלאי,
        # לא קיצור.** ``suggest`` מגיש שני סוגי תשובה — דירוג קצר של כותרות
        # קרובות, ורשימת המזהים שקיימים בעמוד — ולשני הסוגים מתאימה כמות
        # אחרת. לשאלה "ביקשת מזהה שאינו קיים, אלה שכן" אין דירוג: חיתוך
        # שרירותי שלה מסתיר פריטים בלי שום קריטריון, ולסוכן אין פרמטר לבקש
        # את השאר. נמדד: עם ברירת המחדל (5), עמוד עם 16 מזהים החזיר את חמשת
        # הראשונים **בסדר הופעה**, וסוכן ששאל ``K11`` לא ראה אותו כלל.
        #
        # ה-handler הוא המקום היחיד שיודע איזו שאלה נשאלה, ולכן הבקשה יושבת
        # כאן ולא כברירת מחדל של הפונקציה.
        suggestions = doc_sections.suggest(
            doc, section, n=doc_sections.MAX_IDENTIFIER_SUGGESTIONS)
        base.update({
            "ok": False, "error": "section_not_found", "requested": section,
            # ``.titles`` ולא האובייקט: ``suggest`` מחזיר ``NamedTuple`` בן שני
            # שדות, ומי שישכח את זה ישלח לקורא ``[[...], false]`` בלי שום שגיאה.
            "suggestions": list(suggestions.titles),
            "toc": toc_items, "toc_truncated": toc_truncated,
        })
        if suggestions.truncated:
            # רק כשנחתכה, ולא שדה שקיים תמיד — ``remaining_chars`` ו-``next_offset``
            # למטה הם אותו תקדים בדיוק. וזו גם הסיבה המעשית: שדה שיופיע בכל תשובת
            # ``section_not_found`` היה משנה את הפלט על כל 208 קובצי ה-RST בלי ששום
            # התנהגות השתנתה, ושובר את הוכחת אפס-הדיף שהשינוי הזה נשען עליה.
            base["suggestions_truncated"] = True
        return base

    # כותרת כפולה → כל המועמדים עם breadcrumb (בלי לנחש)
    if len(matches) > 1:
        candidates, candidates_truncated = _capped(matches, _CANDIDATES_MAX)
        base.update({
            "ok": False, "error": "ambiguous_section", "requested": section,
            "candidates": [{
                "title": s.title, "breadcrumb": list(s.breadcrumb),
                "level": s.level, "line_range": [s.heading_line, s.end_line],
            } for s in candidates],
        })
        if candidates_truncated:
            # רק כשנחתך — אותה מוסכמה של ``suggestions_truncated`` ו-``remaining_chars``:
            # שדה שקיים תמיד היה משנה כל תשובת ``ambiguous_section`` בתצלום
            # אפס-הדיף בלי ששום התנהגות השתנתה.
            base["candidates_truncated"] = True
        return base

    # התאמה יחידה → הסקשן + ניווט (שכנים ותת-סקשנים)
    sec = matches[0]
    full = doc_sections.section_text(doc, sec, include_subsections)
    total = len(full)
    chunk = full[offset:offset + max_chars]
    truncated = (offset + len(chunk)) < total
    prev, nxt = doc_sections.neighbors(doc, sec)

    base.update({
        "mode": "section",
        "section": sec.title,
        "breadcrumb": list(sec.breadcrumb),
        "level": sec.level,
        "line_range": [sec.heading_line, sec.end_line],
        "include_subsections": bool(include_subsections),
        "offset": offset,
        "content": chunk,
        "truncated": truncated,
        "subsections": [_section_ref(s) for s in doc_sections.direct_subsections(doc, sec)],
        "neighbors": {
            "prev": _section_ref(prev) if prev else None,
            "next": _section_ref(nxt) if nxt else None,
        },
    })
    if truncated:
        base["remaining_chars"] = total - (offset + len(chunk))
        base["next_offset"] = offset + len(chunk)
    return base

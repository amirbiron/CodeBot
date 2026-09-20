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
from types import ModuleType
from typing import Any, NamedTuple

from services import doc_sections, md_parser, rst_parser
from .handlers import _clamp

logger = logging.getLogger(__name__)

MAX_CHARS_DEFAULT = 12_000
MAX_CHARS_MAX = 100_000
MAX_CHARS_MIN = 500
DEFAULT_DOCS_REPO = "CodeBot"
_TOC_MAX = 400  # תקרת פריטי TOC בתשובה (הגנת גודל)

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
_PARSERS: dict[str, ModuleType] = {".rst": rst_parser, ".md": md_parser}


@dataclass(frozen=True)
class _DocsPathPolicy:
    """איפה גרים קובצי התיעוד של ריפו אחד, ובאיזו צורה.

    **``roots[0]`` ו-``suffixes[0]`` הם ברירות המחדל, וזו מוסכמה אחת לשני
    השדות.** ``roots[0]`` הוא המקום שאליו עוגן slug קצר (``mcp-server`` ←
    איזה קובץ), ו-``suffixes[0]`` היא הסיומת שמתווספת לו. אפשר היה להצהיר
    על שניהם בשדות נפרדים — ואז היה צריך לאכוף ששדה ברירת המחדל נמצא
    ברשימה, כלומר **שתי רשימות שצריך לסנכרן** בתוך אובייקט אחד. כאן יש
    רשימה אחת, וסדר הוא נתון ולא כפילות.

    ``roots`` שמכיל ``""`` פירושו **שורש הריפו**: כל נתיב יחסי שאינו יוצא
    החוצה. זו אינה "בלי מדיניות" — הסיומות עדיין מסננות, וזה מה שמונע
    מ-``.claude/settings.json`` להיות נגיש.
    """

    roots: tuple[str, ...]
    suffixes: tuple[str, ...]

    @property
    def slug_root(self) -> str:
        """השורש שאליו עוגן קלט שאין בו ``/``."""
        return self.roots[0]

    @property
    def default_suffix(self) -> str:
        """הסיומת שמתווספת לקלט שאינו נושא סיומת שהכלי מכיר."""
        return self.suffixes[0]


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
#:    מה ש**לא** משתנה: ``mcp_server.repo_policy.is_denied`` הוא ההוראה
#:    הראשונה ב-``RepoBackend.get_file`` וחל על המסלול הזה במלואו, כך
#:    ש-``secrets.md``, ``credentials.md`` ו-``.env*`` חסומים גם כאן.
DOCS_PATH_POLICY: dict[str, _DocsPathPolicy] = {
    "CodeBot": _DocsPathPolicy(roots=("docs",), suffixes=(".rst",)),
    "amir-bug-patterns": _DocsPathPolicy(roots=("",), suffixes=(".md",)),
}


def _validate_policy_tables() -> None:
    """נופל **בזמן הייבוא** על טבלה פגומה, ולא בתוך בקשה של משתמש.

    התקדים הוא ``md_parser._build_parser``: ``ruler.before("front_matter", ...)``
    נופל ב-``KeyError`` בייבוא כשהתוסף לא נרשם, וה-docstring שם מנמק במפורש
    למה זה עדיף על כשל שקט בזמן פרסור. כאן הכשל השקט היה ``KeyError`` על
    ``_PARSERS`` באמצע קריאה — כלומר 500 למשתמש, במקום שרת שלא עולה.

    ``RuntimeError`` ולא ``assert``, כי ``assert`` נמחק תחת ``-O``.
    """
    for repo, policy in DOCS_PATH_POLICY.items():
        if not policy.roots or not policy.suffixes:
            raise RuntimeError(f"מדיניות נתיבים ריקה ל-{repo!r}")
        for suffix in policy.suffixes:
            if not suffix.startswith(".") or suffix != suffix.casefold():
                raise RuntimeError(f"סיומת לא מנורמלת ב-{repo!r}: {suffix!r}")
            if suffix not in _PARSERS:
                raise RuntimeError(
                    f"{repo!r} מצהיר על {suffix!r} ואין לו פארסר ב-_PARSERS")
        for root in policy.roots:
            if root and (root.startswith("/") or root != posixpath.normpath(root)):
                raise RuntimeError(f"שורש לא מנורמל ב-{repo!r}: {root!r}")


_validate_policy_tables()


class _ResolvedPath(NamedTuple):
    """או נתיב **עם הסיומת שהוכרעה לו**, או קוד סירוב.

    ``str | None`` הספיק כל עוד הייתה סיבת דחייה אחת. הצורה
    ``value-or-error-string`` שב-``repo_backend.normalize_line_range`` אינה
    עובדת כאן, כי הנתיב וקוד השגיאה שניהם ``str`` ו-``isinstance`` אינו
    מבדיל ביניהם.

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

    1. ``strip`` ודחיית ``\\x00`` — הערך מגיע מחוץ לתהליך.
    2. הכרעת הסיומת: מותרת ← כמו שהיא; **פורמט אחר שהכלי מכיר** ← סירוב
       מפורש; כל דבר אחר ← חלק מה-slug, והסיומת מתווספת.
    3. **עגינה, על המחרוזת שלפני הנרמול.** זו הנקודה הראשונה:
       ``docs/../secrets`` נושא ``/`` ולכן אינו נעגן, ואחרי הנרמול הוא
       ``secrets.rst`` — מחוץ ל-``docs/``, ונדחה. מי ש"ינקה" את הקוד
       ויקדים את ``normpath`` יקבל ``secrets.rst`` בלי ``/``, יעגן אותו
       ל-``docs/secrets.rst``, **ויגיש אותו**.
    4. ``normpath`` — כאן, ורק כאן.
    5. הגבול מול כל אחד מהשורשים. זו הנקודה השנייה: ``startswith`` חשוף
       הוא ``K16``, ולכן הוא עטוף ב-``_is_under``.
    """
    p = (path or "").strip().strip("/")
    if not p or "\x00" in p:
        return _ResolvedPath(None, None, "missing_path")

    suffix = _suffix_of(p)
    if suffix not in policy.suffixes:
        if suffix in _PARSERS:
            # פורמט שהכלי מכיר, אבל לא זה שהריפו הזה מגיש. השלמה שקטה של
            # הסיומת כאן הייתה בונה ``docs/CRITICAL-PATTERNS.md.rst``
            # ומחזירה ``not_found`` על קובץ שקיים — כלומר סירוב שמתחזה
            # להיעדר, והקורא היה מחפש את הבאג במקום הלא נכון.
            return _ResolvedPath(None, None, "suffix_not_allowed")
        p = p + policy.default_suffix
        suffix = policy.default_suffix

    if policy.slug_root and "/" not in p:
        p = policy.slug_root + "/" + p

    norm = posixpath.normpath(p)
    for root in policy.roots:
        if _is_under(norm, root):
            return _ResolvedPath(norm, suffix, None)
    return _ResolvedPath(None, None, "missing_path")


def _toc(doc: doc_sections.Document) -> tuple[list, bool]:
    items = doc_sections.build_toc(doc)
    if len(items) > _TOC_MAX:
        return items[:_TOC_MAX], True
    return items, False


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
        return {"ok": False, "error": "suffix_not_allowed", "repo": repo_name,
                "requested_path": path, "allowed_suffixes": list(policy.suffixes)}
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
    # **ומה שלא נתפס כאן, בכוונה:** ``TypeError`` ו-``RuntimeError`` של
    # ``md_parser``. שניהם אומרים "חוזה נשבר" ולא "הקלט נדחה", ועטיפתם
    # הייתה בדיוק ``widened-exception-scope``. ``content`` הוא תמיד מחרוזת
    # במסלול הזה, כי ``binary`` ו-``too_large`` נחסמו למעלה.
    #
    # תקרת המקביליות על הפרסור אינה כאן ואינה צריכה להיות: היא נגזרת מגודל
    # מאגר הקריאות, ומקומה ב-lifespan של השרת — אישו #3391.
    try:
        doc = parser.parse_document(content)
    except doc_sections.InconsistentLineEndings:
        return {"ok": False, "error": "inconsistent_line_endings", **context}
    except doc_sections.TooManySections:
        return {"ok": False, "error": "too_many_sections", **context}

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
        base.update({
            "ok": False, "error": "ambiguous_section", "requested": section,
            "candidates": [{
                "title": s.title, "breadcrumb": list(s.breadcrumb),
                "level": s.level, "line_range": [s.heading_line, s.end_line],
            } for s in matches],
        })
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

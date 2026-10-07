"""קריאת קובץ הייצוא של אתר התיעוד — הורדה, בדיקה מלאה, ושום כתיבה.

הקובץ נכתב בבניית האתר (``scripts/docs_export_sections.py``; ההסבר ב-``docs/doc-authoring.rst``,
"ייצוא הסעיפים בבניית האתר"), והוא הקלט של מעבר האינדוקס. כאן הוא עובר מהאתר לזיכרון, ונבדק
כולו לפני שמשהו ממנו נכנס למסד.

**שתי דרכים לבקש אותו.**

* **לפי קומיט** (``commit=``) — כשה-webhook של הפריסה מודיע על קומיט. הבקשה הולכת לעותק בשם
  של הקומיט (:func:`services.docs_search_contract.export_path_for_commit`), שאין לו עותק במטמון
  של האתר, ו-``source_commit`` שבקובץ חייב להיות אותו קומיט — אחרת :data:`EXPORT_STALE`.
* **הקובץ הראשי** — לרשת הביטחון ולכפתור "בדוק עכשיו", עם ``If-None-Match`` של הפעם הקודמת;
  304 אומר שאין מה לעשות. הוא עלול להיות ישן עד שהמטמון של האתר מתחלף, ולכן המעבר משווה את
  ``source_commit`` שבו למה שכבר באינדקס ולא סומך על כך שהוא "החדש".

**כל כשל הוא :class:`ExportFetchError`** עם קוד סיבה יציב (``EXPORT_*``), שנכתב למסמך המצב
ולאירוע — והמעבר עוצר לפני כל כתיבה. אין כאן נפילה-לאחור: עותק לפי קומיט שלא נמצא **אינו**
מוביל לקובץ הראשי, כי זה עלול להיות קובץ של פריסה אחרת.

**ההמתנה מוגבלת בשתי שכבות.** כל שלב של בקשה (חיבור, קריאה) מוגבל ב-timeout של הלקוח, וההורדה
כולה — ב-:data:`EXPORT_DOWNLOAD_DEADLINE_SECONDS`, שנבדק בין חתיכות, כך שגם תשובה שמטפטפת נעצרת.
והגודל נספר על הבתים אחרי פענוח (``iter_bytes``), כך שגם קובץ דחוס שמתפוצץ בפתיחה נעצר
ב-:data:`EXPORT_MAX_BYTES`.

**התקרות על השדות** (U3 §10 ב-amir-bug-patterns): כל מחרוזת שנכנסת למפתח, לכתובת או לטקסט
שמוטמע מוגבלת, והקובץ כולו מוגבל. המספרים נגזרים מהערך הארוך ביותר בקובץ האמיתי כפול שוליים;
הם נמדדו ב-7.10.2026 על הייצוא של הקומיט ``990a666`` ב-``scripts/measure_docs_export.py``, וכל
אחד מהם כתוב ככפולה של המדידה כדי שהמקור שלו יישאר גלוי. חריגה היא סירוב (:data:`EXPORT_INVALID`
או :data:`EXPORT_TOO_LARGE`) ולא חיתוך.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, NoReturn, Optional, Tuple

import httpx

from services import docs_search_contract as contract

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# תקרות
# ---------------------------------------------------------------------------

#: גודל הקובץ, בבתים אחרי פענוח. המדידה: 2,462,043. השוליים כפולים ולא יותר, כי המעבר
#: מפענח את הקובץ כולו לזיכרון; הרחבה מעבר לזה צריכה מדידת זיכרון קודם.
EXPORT_MAX_BYTES = 2 * 2_462_043

#: נתיב עמוד באתר וקובץ המקור שלו. המדידה: 45 ו-49.
MAX_PATH_BYTES = 4 * 49

#: כותרת של עמוד או של סעיף. המדידה: 99.
MAX_TITLE_BYTES = 4 * 99

#: עוגן. המדידה: 61.
MAX_ANCHOR_BYTES = 4 * 61

#: שביל הכותרות, כפי שהוא מחובר לטקסט שמוטמע (``" › "`` בין הכותרות). המדידה: 262. התקרה
#: היא גם מה שמבטיח שנשאר מקום לגוף בנתח של 2,000 בתים.
MAX_BREADCRUMB_BYTES = 4 * 262

#: המפריד בין הכותרות בשביל, כפי שהוא מחובר לטקסט שמוטמע.
BREADCRUMB_SEPARATOR = " › "

#: ההורדה כולה. הקובץ הוא כמה מגה-בייט, ובדרך כלל יורד דחוס בפחות משנייה; דקה היא תקרה
#: למקרה שבו משהו נתקע, לא הערכה של זמן רגיל.
EXPORT_DOWNLOAD_DEADLINE_SECONDS = 60.0

#: כל שלב בבקשה בודדת (חיבור, כתיבה, קריאה של חתיכה).
EXPORT_REQUEST_TIMEOUT_SECONDS = 20.0

#: ``ETag`` שנשמר במסמך המצב ונשלח בחזרה ב-``If-None-Match``. הדקדוק של entity-tag
#: (RFC 9110 §8.8.3), ותקרה כדי שלא יישמר ערך ארוך במסמך המצב.
_ETAG_RE = re.compile(r'(?:W/)?"[\x21\x23-\x7e]*"')
_MAX_ETAG_CHARS = 200

# ---------------------------------------------------------------------------
# קודי הכשל — נכתבים למסמך המצב ולאירועים, ולכן יציבים
# ---------------------------------------------------------------------------

EXPORT_NOT_FOUND = "export_not_found"
EXPORT_HTTP_ERROR = "export_http_error"
EXPORT_UNREACHABLE = "export_unreachable"
EXPORT_TIMEOUT = "export_timeout"
EXPORT_TOO_LARGE = "export_too_large"
EXPORT_INVALID = "export_invalid"
EXPORT_UNSUPPORTED_SCHEMA = "export_unsupported_schema"
EXPORT_SITE_MISMATCH = "export_site_mismatch"
EXPORT_STALE = "stale_export"

#: אורך מרבי של פרט בהודעת כשל. ההודעה נכתבת למסמך המצב, ולכן ערך מהקובץ לא נכנס אליה בשלמותו.
_DETAIL_MAX_CHARS = 300


class ExportFetchError(Exception):
    """הקובץ לא הורד, או שאינו בצורה שהוובאפ יודע לקרוא. ``code`` הוא אחד מ-``EXPORT_*``."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail[:_DETAIL_MAX_CHARS]


# ---------------------------------------------------------------------------
# המבנה, אחרי בדיקה
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocSection:
    anchor: str
    title: str
    breadcrumb: Tuple[str, ...]
    level: int
    markdown: str


@dataclass(frozen=True)
class DocPage:
    path: str
    source_path: str
    title: str
    sections: Tuple[DocSection, ...]


@dataclass(frozen=True)
class ExportDocument:
    schema_version: int
    source_commit: str
    built_at: datetime
    site_url: str
    pages: Tuple[DocPage, ...]

    @property
    def section_count(self) -> int:
        return sum(len(page.sections) for page in self.pages)


@dataclass(frozen=True)
class ExportFetch:
    """התוצאה של הורדה: ``not_modified`` (304, ואז אין מסמך), או מסמך שעבר בדיקה."""

    url: str
    not_modified: bool
    etag: Optional[str]
    document: Optional[ExportDocument]
    byte_count: int


# ---------------------------------------------------------------------------
# הורדה
# ---------------------------------------------------------------------------


def new_export_http_client(*, transport: Optional[httpx.BaseTransport] = None) -> httpx.Client:
    """לקוח להורדת הקובץ מהאתר: בלי כותרות של סודות, ובלי מעקב אחרי הפניות.

    לקוח נפרד מזה של Gemini (``SyncEmbeddingClient``), שנושא את מפתח ה-API בכותרת: יעד אחר
    מקבל לקוח משלו. הפניה מהאתר אינה צפויה, ולכן היא מוחזרת כסטטוס ולא נעקבת.
    """
    return httpx.Client(
        timeout=httpx.Timeout(EXPORT_REQUEST_TIMEOUT_SECONDS),
        follow_redirects=False,
        transport=transport,
    )


def export_url(commit: Optional[str] = None) -> str:
    """הכתובת של הקובץ הראשי, או של העותק לפי קומיט."""
    if commit is None:
        return contract.SITE_URL + contract.EXPORT_PATH
    return contract.SITE_URL + contract.export_path_for_commit(commit)


def fetch_export(
    client: httpx.Client,
    *,
    commit: Optional[str] = None,
    etag: Optional[str] = None,
    clock: Callable[[], float] = time.monotonic,
) -> ExportFetch:
    """מוריד את הקובץ ובודק אותו. זורק :class:`ExportFetchError` על כל כשל.

    ``commit`` — הקומיט שה-webhook של הפריסה הודיע עליו; אז הבקשה הולכת לעותק לפי הקומיט, ו-
    ``etag`` אינו נשלח (לכתובת הזו אין גרסה קודמת). בלי ``commit`` — הקובץ הראשי, עם
    ``If-None-Match`` כשיש ``etag``.
    """
    if commit is not None and not contract.is_commit_sha(commit):
        raise ValueError(f"expected a 40-character commit sha, got {commit!r}")
    url = export_url(commit)
    headers: Dict[str, str] = {}
    if commit is None and etag:
        headers["If-None-Match"] = etag

    deadline = clock() + EXPORT_DOWNLOAD_DEADLINE_SECONDS
    parts: List[bytes] = []
    total = 0
    try:
        with client.stream("GET", url, headers=headers) as response:
            status = response.status_code
            if status == 304 and commit is None and etag:
                return ExportFetch(url=url, not_modified=True, etag=etag, document=None, byte_count=0)
            if status == 404:
                raise ExportFetchError(EXPORT_NOT_FOUND, f"{url}: HTTP 404")
            if status != 200:
                raise ExportFetchError(EXPORT_HTTP_ERROR, f"{url}: HTTP {status}")
            declared = response.headers.get("Content-Length", "")
            if (
                declared.isdigit()
                and not response.headers.get("Content-Encoding")
                and int(declared) > EXPORT_MAX_BYTES
            ):
                raise ExportFetchError(
                    EXPORT_TOO_LARGE, f"{url}: {declared} bytes, max {EXPORT_MAX_BYTES}"
                )
            for part in response.iter_bytes():
                total += len(part)
                if total > EXPORT_MAX_BYTES:
                    raise ExportFetchError(
                        EXPORT_TOO_LARGE, f"{url}: more than {EXPORT_MAX_BYTES} bytes"
                    )
                if clock() > deadline:
                    raise ExportFetchError(
                        EXPORT_TIMEOUT,
                        f"{url}: not done after {EXPORT_DOWNLOAD_DEADLINE_SECONDS:g}s ({total} bytes)",
                    )
                parts.append(part)
            new_etag = _usable_etag(response.headers.get("ETag"), url)
    except httpx.DecodingError as exc:
        raise ExportFetchError(EXPORT_INVALID, f"{url}: {type(exc).__name__}") from exc
    except httpx.TransportError as exc:
        # רשת או timeout של בקשה בודדת. רק תת-העץ של התעבורה — חריגה אחרת היא באג, ועולה.
        raise ExportFetchError(EXPORT_UNREACHABLE, f"{url}: {type(exc).__name__}") from exc

    document = parse_export(b"".join(parts))
    if document.site_url != contract.SITE_URL:
        raise ExportFetchError(
            EXPORT_SITE_MISMATCH,
            f"the file was built for {document.site_url!r}, the webapp reads {contract.SITE_URL!r}",
        )
    if commit is not None and document.source_commit != commit:
        raise ExportFetchError(
            EXPORT_STALE, f"asked for {commit}, the file is from {document.source_commit}"
        )
    return ExportFetch(url=url, not_modified=False, etag=new_etag, document=document, byte_count=total)


def _usable_etag(value: Optional[str], url: str) -> Optional[str]:
    """ה-``ETag`` לשמירה, או ``None`` כשאין או כשאינו בדקדוק — ואז ההורדה הבאה מלאה, ונרשם למה."""
    if value is None:
        return None
    if len(value) <= _MAX_ETAG_CHARS and _ETAG_RE.fullmatch(value):
        return value
    logger.warning("docs export: ignoring an ETag that is not an entity-tag from %s", url)
    return None


# ---------------------------------------------------------------------------
# בדיקה
# ---------------------------------------------------------------------------


def parse_export(data: bytes) -> ExportDocument:
    """מפענח ובודק את הקובץ כולו. זורק :class:`ExportFetchError` על כל סטייה מהמבנה.

    מה שהבדיקה מבטיחה הוא מה ש-``_validated_sections`` בסקריפט הייצוא מבטיח בכתיבה (עוגן
    ייחודי בעמוד, כותרת לא ריקה, שביל שנגמר בכותרת, רמה שווה לאורך השביל), ובנוסף: הגרסה
    נתמכת, הספירות תואמות למה שבפועל, נתיבים ועוגנים בדקדוק של
    :mod:`services.docs_search_contract`, ותקרות על כל שדה.
    """
    try:
        raw = json.loads(data)
    except ValueError as exc:  # כולל ``UnicodeDecodeError``
        raise ExportFetchError(EXPORT_INVALID, f"not JSON: {exc}") from exc
    if not isinstance(raw, dict):
        _invalid("the file is not an object")

    schema_version = raw.get("schema_version")
    if type(schema_version) is not int:
        _invalid("schema_version is not an integer")
    if schema_version != contract.SCHEMA_VERSION:
        raise ExportFetchError(
            EXPORT_UNSUPPORTED_SCHEMA,
            f"schema_version {schema_version}, the webapp reads {contract.SCHEMA_VERSION}",
        )

    source_commit = raw.get("source_commit")
    if not contract.is_commit_sha(source_commit):
        _invalid(f"source_commit is not a commit sha: {source_commit!r}")
    site_url = raw.get("site_url")
    if not isinstance(site_url, str):
        _invalid("site_url is not a string")
    built_at = _aware_datetime(raw.get("built_at"))

    pages_raw = raw.get("pages")
    if not isinstance(pages_raw, list) or not pages_raw:
        _invalid("pages is not a non-empty list")
    pages = tuple(_page(item, index) for index, item in enumerate(pages_raw))

    paths = [page.path for page in pages]
    if len(set(paths)) != len(paths):
        _invalid("a page path appears twice")
    page_count = raw.get("page_count")
    section_count = raw.get("section_count")
    actual_sections = sum(len(page.sections) for page in pages)
    if type(page_count) is not int or page_count != len(pages):
        _invalid(f"page_count {page_count!r} does not match {len(pages)} pages")
    if type(section_count) is not int or section_count != actual_sections:
        _invalid(f"section_count {section_count!r} does not match {actual_sections} sections")

    return ExportDocument(
        schema_version=schema_version,
        source_commit=source_commit,
        built_at=built_at,
        site_url=site_url,
        pages=pages,
    )


def _page(item: Any, index: int) -> DocPage:
    where = f"pages[{index}]"
    if not isinstance(item, dict):
        _invalid(f"{where} is not an object")
    path = _bounded_text(item.get("path"), f"{where}.path", MAX_PATH_BYTES)
    if not contract.PAGE_PATH_RE.fullmatch(path):
        _invalid(f"{where}.path is not a page path: {path!r}")
    source_path = _bounded_text(item.get("source_path"), f"{where}.source_path", MAX_PATH_BYTES)
    if not contract.SOURCE_PATH_RE.fullmatch(source_path):
        _invalid(f"{where}.source_path is not a source path: {source_path!r}")
    title = _bounded_text(item.get("title"), f"{where}.title", MAX_TITLE_BYTES)
    sections_raw = item.get("sections")
    if not isinstance(sections_raw, list) or not sections_raw:
        _invalid(f"{where}.sections is not a non-empty list")
    sections = tuple(
        _section(entry, f"{where}.sections[{position}]") for position, entry in enumerate(sections_raw)
    )
    anchors = [section.anchor for section in sections]
    if len(set(anchors)) != len(anchors):
        _invalid(f"{where} ({path}) has an anchor twice")
    return DocPage(path=path, source_path=source_path, title=title, sections=sections)


def _section(item: Any, where: str) -> DocSection:
    if not isinstance(item, dict):
        _invalid(f"{where} is not an object")
    anchor = _bounded_text(item.get("anchor"), f"{where}.anchor", MAX_ANCHOR_BYTES)
    if not contract.ANCHOR_RE.fullmatch(anchor):
        _invalid(f"{where}.anchor is not an anchor: {anchor!r}")
    title = _bounded_text(item.get("title"), f"{where}.title", MAX_TITLE_BYTES)
    crumbs = item.get("breadcrumb")
    if not isinstance(crumbs, list) or not crumbs:
        _invalid(f"{where}.breadcrumb is not a non-empty list")
    breadcrumb = tuple(
        _bounded_text(crumb, f"{where}.breadcrumb[{position}]", MAX_TITLE_BYTES)
        for position, crumb in enumerate(crumbs)
    )
    if breadcrumb[-1] != title:
        _invalid(f"{where}.breadcrumb does not end with the title")
    if len(BREADCRUMB_SEPARATOR.join(breadcrumb).encode("utf-8")) > MAX_BREADCRUMB_BYTES:
        _invalid(f"{where}.breadcrumb is longer than {MAX_BREADCRUMB_BYTES} bytes")
    level = item.get("level")
    # ``type`` ולא ``isinstance``: ‏``True`` הוא ``int`` בפייתון.
    if type(level) is not int or level != len(breadcrumb):
        _invalid(f"{where}.level does not match the breadcrumb")
    markdown = item.get("markdown")
    if not isinstance(markdown, str):
        _invalid(f"{where}.markdown is not text")
    _utf8_size(markdown, f"{where}.markdown")
    return DocSection(
        anchor=anchor, title=title, breadcrumb=breadcrumb, level=level, markdown=markdown
    )


def _bounded_text(value: Any, where: str, max_bytes: int) -> str:
    """מחרוזת לא ריקה (אחרי ``strip``), עד ``max_bytes`` בתים. סירוב ולא חיתוך."""
    if not isinstance(value, str) or not value.strip():
        _invalid(f"{where} is not a non-empty string")
    size = _utf8_size(value, where)
    if size > max_bytes:
        _invalid(f"{where} is {size} bytes, max {max_bytes}")
    return value


def _aware_datetime(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        _invalid("built_at is not a short string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        _invalid(f"built_at is not an ISO timestamp: {value!r}")
    if parsed.utcoffset() is None:
        _invalid("built_at has no timezone")
    return parsed


def _utf8_size(value: str, where: str) -> int:
    """האורך בבתים של UTF-8. ‏``\\ud800`` ב-JSON מפוענח ל-surrogate בודד, שאינו תו ואין לו קידוד:
    ``encode`` זורק עליו ``UnicodeEncodeError``. ערך כזה הוא קובץ פגום (:data:`EXPORT_INVALID`),
    ולא חריגה שעולה מהקורא באמצע בניית הנתחים."""
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        _invalid(f"{where} is not valid text: it holds a lone surrogate")


def _invalid(detail: str) -> NoReturn:
    raise ExportFetchError(EXPORT_INVALID, detail)

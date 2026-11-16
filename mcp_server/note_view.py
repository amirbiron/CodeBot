"""MCP App: פתק אחד שנפתח בתוך Claude — הדף, הכתובת שלו, והרישום בשרת.

**מה זה MCP Apps, בשתי שורות.** הרחבה רשמית של MCP (``io.modelcontextprotocol/ui``,
SEP-1865, המפרט היציב ``2026-01-26`` בריפו ``modelcontextprotocol/ext-apps``): כלי מצביע
ב-``_meta.ui.resourceUri`` על משאב ``ui://``, המארח (Claude) מבקש אותו ב-``resources/read``,
מריץ את ה-HTML ב-iframe מבודד, ומעביר אליו את תוצאת הכלי ב-``postMessage``. **השרת לא שולח
ולא מקבל אף הודעה שמתחילה ב-``ui/``** — אלה עוברות בין המארח לדף בלבד (``note_view.js``).

**בלי ספרייה נוספת, ומדוע זה מספיק.** ``mcp 1.28.1`` אינו מכיר את ההרחבה בשם — התמיכה
המובנית (``mcp.server.apps``) נוספה רק בשורת 2.x — אבל כל מה שההרחבה דורשת מהשרת כבר
קיים בו: ``meta=`` על כלי ועל משאב, ו-``mime_type=`` שמקבל את ``text/html;profile=mcp-app``.
נבדק בהרצה מול הגרסה המותקנת: שני מפתחות ה-``_meta`` של הכלי מגיעים ל-``tools/list``,
וה-``_meta.ui`` של המשאב מגיע לפריט שבתשובה של ``resources/read`` — שם המארח קורא אותו.
``tests/test_mcp_note_view.py`` מקבע את שלושתם דרך session אמיתי של הפרוטוקול, כדי ששדרוג
גרסה שמשנה אותם יפיל את ה-CI ולא את התצוגה.

**הכתובת נושאת את הגרסה של הדף** (:func:`build_note_view`): ``ui://codekeeper/note-view/<hash>.html``.
המפרט מתיר למארח לשמור את הדף בקאש ("Host MAY prefetch and cache UI resource content"),
וכתובת קבועה הייתה מגישה אחרי דיפלוי את הדף הקודם בלי שום עקבה בשרת — זו
``stale-asset-cache-policy`` של ``amir-bug-patterns``: כתובת שמשתנה כשהתוכן משתנה. ולצידה
תבנית שעונה על **כל** גרסה שהשרת הזה פרסם פעם, עם הדף הנוכחי: שיחה ישנה שטוענת מחדש את
התצוגה שלה עם הכתובת שנרשמה אז אינה נופלת על "לא נמצא" אחרי כל דיפלוי. לכן הדף חייב
לדעת לקרוא גם תוצאה שכלי ישן החזיר — היום יש צורה אחת, וזו הערה למי שישנה אותה.

**הדף נבנה ברישום, לא בייבוא** (``import-time-side-effects``): :func:`build_note_view` קוראת
קבצים, ו-``build_mcp`` קוראת לה. קובץ חסר או מבנה שבור הם שגיאת פריסה, ולכן הם עוצרים את
עליית השרת ב-``RuntimeError`` — כמו ``_check_declared_size`` — ולא משאירים כלי שמצביע על
דף שאינו קיים.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: סוג התוכן שהמפרט מחייב לדף של MCP App: *"`mimeType` MUST be `text/html;profile=mcp-app`"*
#: (``specification/2026-01-26/apps.mdx``, "Content Requirements"). אותו ערך בדיוק כמו
#: ``RESOURCE_MIME_TYPE`` ב-``src/constants.ts`` של ext-apps.
APP_MIME_TYPE = "text/html;profile=mcp-app"

#: התחילית של כל כתובת שהשרת הזה מפרסם לתצוגת הפתק. ``ui://`` היא הסכימה שהמפרט שומר
#: ל-MCP Apps (*"URI MUST start with `ui://` scheme"*).
_URI_PREFIX = "ui://codekeeper/note-view/"

#: כמה תווי hex מה-SHA-256 של הדף נכנסים לכתובת. שישה-עשר תווים הם 64 ביט — התנגשות בין
#: שתי גרסאות של אותו דף אינה תרחיש. הערך הזה הוא גם מה שהתבנית מקבלת (:data:`_VERSION_RE`).
VERSION_HEX_CHARS = 16

#: התבנית שעונה על כל גרסה, כולל זו הנוכחית. ``{version}`` הוא מה ש-FastMCP מעביר לפונקציה.
URI_TEMPLATE = _URI_PREFIX + "{version}.html"

#: מה שהתבנית מקבלת כגרסה: בדיוק הצורה ש-:func:`build_note_view` מייצרת. כתובת אחרת אינה
#: גרסה שהשרת פרסם אי פעם, ולכן היא "לא נמצא" ולא הדף.
_VERSION_RE = re.compile(rf"[0-9a-f]{{{VERSION_HEX_CHARS}}}")

#: שם המשאב, ב-``resources/list`` וב-``resources/templates/list``.
RESOURCE_NAME = "codekeeper_note_view"

#: ``_meta.ui`` של המשאב. **אין ``csp``, בכוונה:** הדף אינו טוען שום דבר מבחוץ — הסקריפט
#: והסגנון כתובים בתוכו — ולכן הוא רץ תחת מדיניות ברירת המחדל הקשוחה של המפרט ("If
#: `ui.csp` is omitted, Host MUST use ... connect-src 'none'"). דף שיצטרך משהו מבחוץ
#: מצהיר עליו כאן, ב-``connectDomains`` / ``resourceDomains``, ולא מרפה בשום מקום אחר.
#: ``prefersBorder: false`` — מה שהתיעוד של Claude ממליץ לדף שקוף ("Transparent theming").
#: הערה למי שיוסיף כאן ``permissions``: הם חלים על ``iframe``, והתיעוד של Claude אומר שבמובייל
#: אין לדף מצלמה, מיקרופון או מיקום.
RESOURCE_META: dict[str, Any] = {"ui": {"prefersBorder": False}}

#: הקבצים של התצוגה עצמה, ליד המודול הזה.
_ASSETS_DIR = Path(__file__).with_name("apps")
#: הנכסים של הוובאפ שהדף כולל — מנוע התצוגה של הפתק והעיצוב שלו. **השרת רץ מהריפו כולו**
#: (הוא כבר מייבא ``sticky_notes_target`` משורש הריפו), ולכן הם קיימים לידו בפריסה.
_WEBAPP_STATIC = Path(__file__).resolve().parent.parent / "webapp" / "static"
_SHELL_FILE = "note_view.html"

#: מה שנכנס לבלוק הסגנון ולבלוק הסקריפט, ובאיזה סדר: ``(שורש, נתיב)``, כש-``"apps"`` הוא
#: :data:`_ASSETS_DIR` ו-``"webapp"`` הוא :data:`_WEBAPP_STATIC`.
#:
#: **אותם קבצים שהוובאפ טוען לפתק, ובסדר שבו הם מגיעים בלוח הפתקים**, כי זה מה שהופך את הפתק
#: כאן לאותו פתק: העיצוב של המנוע (``sticky-md-render.css``), הבסיס של האלרט והבלוק המתקפל
#: (``markdown-enhanced.css``), ואחריהם התצוגה, שמוסיפה רק את מה ששייך לה. בסקריפט — שמות הקבצים,
#: המפה של האלרטים וזיהוי העברית שהמנוע קורא מ-``window``, המנוע, ואז התצוגה. עותק של הכללים או
#: של הפרסר כאן היה ניב שלישי של "איך פתק נראה" (העמוד של המנוע, ``sticky-notes-md-engine-module``).
#:
#: **הסדר של הלוח, כי בוובאפ אין סדר אחד.** ``base.html`` טוען את ``markdown-enhanced.css`` אחרי
#: הבלוק ``extra_css``, ולכן בלוח, בארכיון ובעמוד הקבצים הוא מגיע **אחרי** העיצוב של הפתק; בתצוגת
#: קובץ Markdown העיצוב של הפתק נטען בגוף העמוד, כלומר **אחריו**. נמדד שזה לא משנה היום: כל כלל
#: ב-``sticky-md-render.css`` תחום ב-``.sticky-note`` וגובר בספציפיות, וסגנון מחושב של פתקים
#: מרונדרים יצא זהה בשני הסדרים. התצוגה הולכת אחרי הלוח, המשטח הראשי של הפתקים, כך שכלל עתידי
#: שישווה בספציפיות יכריע כאן כמו שם. ``tests/test_mcp_note_view.py`` גוזר את הסדר הזה מהתבניות.
STYLE_PARTS: tuple[tuple[str, str], ...] = (
    ("webapp", "css/sticky-md-render.css"),
    ("webapp", "css/markdown-enhanced.css"),
    ("apps", "note_view.css"),
)
SCRIPT_PARTS: tuple[tuple[str, str], ...] = (
    ("webapp", "js/utils/file-name.js"),
    ("webapp", "js/admonition-icons.js"),
    ("webapp", "js/utils/rtl-code.js"),
    ("webapp", "js/sticky-md-render.js"),
    ("apps", "note_view.js"),
)

#: הסימנים בשלד שבמקומם נכנסים הסגנון והסקריפט. כל אחד חייב להופיע בשלד **פעם אחת בדיוק**.
STYLE_SLOT = "/*NOTE_VIEW_STYLE*/"
SCRIPT_SLOT = "/*NOTE_VIEW_SCRIPT*/"


@dataclass(frozen=True)
class NoteView:
    """הדף שנבנה, והכתובת שנגזרת ממנו."""

    html: str
    version: str

    @property
    def uri(self) -> str:
        return f"{_URI_PREFIX}{self.version}.html"


def _inline(shell: str, slot: str, parts: list[tuple[str, str]], closing_tag: str) -> str:
    """מכניס את ``parts`` — ``(שם, תוכן)``, לפי הסדר — במקום ``slot``, אחרי שתי בדיקות שבלעדיהן
    הדף נשבר בשקט.

    * ``slot`` מופיע בשלד פעם אחת בדיוק — אחרת הקוד היה נכנס פעמיים, או לא נכנס כלל.
    * אף חלק אינו מכיל את התגית שסוגרת את הבלוק (``</script`` / ``</style``, בלי תלות ברישיות):
      הדפדפן סוגר את הבלוק בתגית הראשונה שהוא פוגש, גם בתוך מחרוזת, ושאר הקוד היה מוצג
      כטקסט. הבדיקה היא לכל חלק בנפרד, כדי שהשגיאה תנקוב בקובץ. ההכנסה היא ``str.replace`` עם
      ספירה אחת, ולכן שום תו בתוכן אינו מפורש.

    כל חלק נפתח בהערה עם השם שלו — בכלי הפיתוח רואים מאיזה קובץ הגיעה כל שורה.
    """
    if shell.count(slot) != 1:
        raise RuntimeError(
            f"note view: {_SHELL_FILE} must contain {slot!r} exactly once, "
            f"found {shell.count(slot)}"
        )
    for name, body in parts:
        if closing_tag in body.lower():
            raise RuntimeError(f"note view: {name} contains {closing_tag!r}, which would end the inline block")
    body = "\n".join(f"/* ---- {name} ---- */\n{text}" for name, text in parts)
    return shell.replace(slot, body, 1)


def build_note_view(assets_dir: Path = _ASSETS_DIR, webapp_static: Path = _WEBAPP_STATIC) -> NoteView:
    """בונה את הדף מהשלד ומהחלקים שב-:data:`STYLE_PARTS` ו-:data:`SCRIPT_PARTS`, וגוזר ממנו את
    הגרסה שבכתובת.

    **הגרסה היא hash של הדף כולו כפי שהוא נשלח**, ולכן כל שינוי — בשלד, בסגנון, בסקריפט, או
    במנוע ובעיצוב שהוובאפ משתף — משנה את הכתובת בלי שמישהו יצטרך לזכור להעלות מספר. קורא
    קבצים: נקראת מ-``build_mcp``, לעולם לא בזמן ייבוא. קובץ שאינו קיים הוא ``FileNotFoundError``
    כמו שהוא — שגיאת פריסה, שעוצרת את עליית השרת.
    """
    roots = {"apps": assets_dir, "webapp": webapp_static}

    def read(parts: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
        return [(rel, (roots[root] / rel).read_text(encoding="utf-8")) for root, rel in parts]

    shell = (assets_dir / _SHELL_FILE).read_text(encoding="utf-8")
    html = _inline(shell, STYLE_SLOT, read(STYLE_PARTS), "</style")
    html = _inline(html, SCRIPT_SLOT, read(SCRIPT_PARTS), "</script")
    version = hashlib.sha256(html.encode("utf-8")).hexdigest()[:VERSION_HEX_CHARS]
    return NoteView(html=html, version=version)


def tool_meta(view: NoteView) -> dict[str, Any]:
    """``_meta`` של הכלי שפותח את התצוגה — שני המפתחות, כמו ה-SDK הרשמי.

    ``_meta.ui.resourceUri`` הוא הצורה שבמפרט. ``"ui/resourceUri"`` השטוח מסומן שם כ-deprecated
    ("Will be removed before GA"), ובכל זאת ``registerAppTool`` ב-``src/server/index.ts`` של
    ext-apps כותב את שניהם ("If _meta.ui.resourceUri is set, also set the legacy flat key"),
    כדי שמארח שעוד קורא רק את הישן יציג את התצוגה. אותו דבר כאן, מאותה סיבה.
    """
    return {"ui": {"resourceUri": view.uri}, "ui/resourceUri": view.uri}


def app_tool_meta(view: NoteView) -> dict[str, Any]:
    """``_meta`` של כלי **שרק הדף מפעיל** — ``visibility: ["app"]`` ליד הקישור לתצוגה.

    "Host MUST NOT include tools in the agent's tool list when their visibility does not include
    \"model\"", ו-"Host MUST reject ``tools/call`` requests from apps for tools that don't include
    \"app\"" (המפרט, "Visibility"). הצורה היא של הדוגמה הרשמית (``registerAppTool`` עם
    ``visibility: ["app"]``, ``docs/patterns.md`` ב-ext-apps): הקישור לתצוגה ב-``_meta.ui`` יחד עם
    ``visibility``, והמפתח השטוח הישן לצידם, כמו ש-``registerAppTool`` מוסיף אותו לכל כלי עם
    ``resourceUri`` — ומאותו מקור כמו :func:`tool_meta`, כדי ששני הכלים יצביעו תמיד על אותו דף.
    """
    meta = tool_meta(view)
    meta["ui"] = {**meta["ui"], "visibility": ["app"]}
    return meta


def register_note_view(mcp: Any, view: NoteView) -> None:
    """רושם את הדף: משאב לכתובת הנוכחית, ותבנית לכל גרסה קודמת.

    **שניהם, ולא רק התבנית.** המפרט מתיר לשרת להשמיט משאב של תצוגה מ-``resources/list``
    ("Servers MAY omit UI-only resources"), אבל מה ש-Claude עושה עם הרשימה אינו מתועד. משאב
    רגיל לכתובת הנוכחית מופיע ברשימה, כמו אצל ``registerAppResource`` של ה-SDK. FastMCP
    בודק משאבים רגילים לפני תבניות (``ResourceManager.get_resource``), ולכן הכתובת הנוכחית
    נענית מהמשאב, וכל גרסה אחרת — מהתבנית.
    """
    from mcp.server.fastmcp.exceptions import ResourceError
    from mcp.server.fastmcp.resources import TextResource

    mcp.add_resource(
        TextResource(
            uri=view.uri,
            name=RESOURCE_NAME,
            title="CodeKeeper note",
            description="One sticky note, shown inside the conversation.",
            mime_type=APP_MIME_TYPE,
            text=view.html,
            meta=RESOURCE_META,
        )
    )

    @mcp.resource(
        URI_TEMPLATE,
        name=RESOURCE_NAME,
        title="CodeKeeper note",
        description="One sticky note, shown inside the conversation (any published version).",
        mime_type=APP_MIME_TYPE,
        meta=RESOURCE_META,
    )
    def note_view_any_version(version: str) -> str:
        # ``version`` מגיע מהמארח, כלומר מבחוץ: רק מה ש-``build_note_view`` מייצר הוא גרסה.
        if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            raise ResourceError(f"unknown note view version: {version!r}")
        return view.html

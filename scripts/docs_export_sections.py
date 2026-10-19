#!/usr/bin/env python3
"""ייצוא כל הסעיפים של אתר התיעוד שנבנה, כמארקדאון, לקובץ JSON אחד שנפרס עם האתר.

**מה יוצא.** הקובץ ``_export/sections.json`` בתוך תיקיית האתר שנבנתה (:data:`EXPORT_PATH`),
ועותק זהה שלו בשם שתלוי בקומיט (:func:`export_path_for_commit`).
לכל עמוד תוכן: הנתיב שלו באתר, קובץ המקור שלו, הכותרת, והקבצים האחרים בריפו שהוא נבנה מהם.
לכל סעיף בעמוד: המזהה שלו
(העוגן בכתובת), הכותרת כטקסט וכמארקדאון, שביל הכותרות מראש העמוד, הרמה, והתוכן של הסעיף
עצמו כמארקדאון — בלי תתי-הסעיפים שלו, שיוצאים כסעיפים נפרדים. הסעיפים של עמוד יוצאים בסדר
שבו הם מופיעים בו, ולכן אפשר להרכיב מהם את העמוד כולו. הקובץ נועד לוובאפ — לחיפוש בתיעוד
ולתצוגה המרונדרת של עמוד בדפדפן הריפו — ולכן הוא חוזה בין שני רכיבים: :data:`SCHEMA_VERSION`
עולה בכל שינוי במבנה.

**הכותרת פעמיים.** ``title`` הוא הטקסט שלה, וממנו שביל הכותרות ומה שמוטמע לחיפוש.
``title_markdown`` היא אותה כותרת בהמרה של הכפתור, ולכן קוד או הדגשה בתוכה נשארים; ממנה
העמוד המורכב מציג את הכותרת.

**הקבצים שעמוד נבנה מהם** (``dependencies``). עמוד יכול להציג תוכן מקבצים אחרים בריפו: קוד
ש-``literalinclude`` מציג, קובץ ש-``include`` משלב, תמונה, ומודול ש-autodoc מתעד. Sphinx רושם
אותם בעצמו, לכל מסמך, כדי לדעת איזה עמוד לבנות מחדש (``env.dependencies``; ``note_dependency``
ב-``sphinx/environment/__init__.py`` ו-``DependenciesCollector``, Sphinx 8.2.3). הסקריפט הוא לכן גם
הרחבה של Sphinx (:func:`setup`, ב-``extensions`` של ``docs/conf.py``): בסוף הבנייה הוא כותב את
הרשימה הזו ל-:data:`DEPENDENCIES_PATH`, והייצוא מצרף לכל עמוד את מה שבתוך הריפו
(:func:`page_dependencies`). כך שם הקובץ והמבנה שלו מוגדרים במקום אחד. דפדפן הריפו משווה אותם
כדי לדעת אם העמוד ישן מהקוד שהוא מציג (``services/docs_page_view.py``).

**למה עותק בשם של הקומיט.** האתר מוגש מאחורי מטמון (CDN) ששומר כל קובץ עד עשר דקות
(``cache-control: max-age=600``), ומפתח המטמון שלו אינו כולל את ה-query. נמדד מול הקובץ
החי ב-7.10.2026: בקשות עם ``?v=`` אקראי חדש חזרו ``x-cache: HIT`` עם אותו ``age`` כמו
בקשה בלי query, וגם ``Cache-Control: no-cache`` בבקשה לא עקף את המטמון. כלומר מי שמבקש
את ``sections.json`` מיד אחרי פריסה עלול לקבל את הקובץ של הפריסה הקודמת. לשם שתלוי
בקומיט אין עותק במטמון, ולכן הוובאפ, שיודע את הקומיט מה-webhook של הפריסה, מבקש בדיוק
את הקובץ של אותה בנייה.

**למה מהאתר שנבנה, ולא מקובצי ה-rst.** המזהה של סעיף שהכותרת שלו בעברית ואין לו תווית
הוא מספר רץ שנותן Sphinx (``id1``, ``id2``…), והוא זז כשמוסיפים סעיף מעליו. קישור
"פתח באתר" שמגיע מבנייה אחרת היה מוביל לסעיף אחר. כשהקובץ נכתב מאותה בנייה שנפרסת,
המזהה בו הוא המזהה באתר.

**למה בדפדפן אמיתי.** ההמרה לטקסט היא ההמרה של כפתור "העתק תוכן הדף" —
``window.DocCopyPage.toMarkdown`` ב-``docs/_static/copy-page.js`` — עם אותה גרסה
של Turndown ואותם כללים (הערות כ-``:::``, טבלאות, קוד עם שפה, תרשימי mermaid). ממיר
שני בפייתון היה נסחף מהכפתור. לכן הסקריפט פותח כל עמוד ב-Chromium דרך Playwright,
ומריץ עליו את הפונקציה שהעמוד עצמו טען.

**בלי רשת.** העמודים נפתחים מהדיסק (``file://``) בהקשר דפדפן שמדמה ניתוק
(``offline=True``). עמוד עם תרשים טוען את mermaid מ-CDN (כך sphinxcontrib-mermaid בונה
אותו); בלי רשת הבקשה הזו נכשלת, mermaid לא מצייר, ו-``captureMermaidSources``
ב-``copy-page.js`` לוכד את קוד המקור של התרשים מה-DOM. כך הייצוא לא תלוי ברשת ולא
בזמינות של CDN.

**מה מוסר מהסעיף לפני ההמרה, ולמה.** בלוקים שנוצרו מהקוד (``dl.py``, של autodoc)
יוצאים, כמו עמודי ``api/`` כולם (:data:`EXCLUDED_TOP_DIRS`). כל קישור הופך לכתובת
מלאה באתר, כדי שקישור בתוך כרטיס בוובאפ יוביל לאתר. ותמונה הופכת לקישור "תמונה: …",
כי ה-CSP של הוובאפ (``_add_default_csp`` ב-``webapp/app.py``) לא מתיר תמונות מהאתר.

**שלמות.** עמוד אחד שנכשל מכשיל את כל הייצוא, ואז לא נשאר קובץ בכלל: קבצים מהרצה
קודמת (הראשי וכל עותק לפי קומיט) מוסרים כבר בתחילת ההרצה, והחדשים נכתבים לקבצים זמניים
ומוחלפים בשמות הסופיים רק בסוף. גם ייצוא בלי עמודים או בלי סעיפים נכשל. אחרי הכתיבה
הקובץ נקרא מחדש מהדיסק, והספירות בו נבדקות מול מה שהסקריפט ספר בעצמו; והעותק נבדק
שהוא זהה לו בית-בבית.

**ההמתנה מוגבלת בשתי שכבות.** כל ניווט מוגבל ב-:data:`NAVIGATION_TIMEOUT_MS`. את
ההרצה כולה מגביל ``timeout-minutes`` של הצעד ב-``.github/workflows/documentation.yml``,
כי ``Page.evaluate`` אינו מקבל תקרת זמן משלו (נקרא במקור של Playwright 1.49.0).

שימוש, כמו בצעד הייצוא ב-``.github/workflows/documentation.yml``::

    python scripts/docs_export_sections.py docs/_build/html \\
        --site-url "$DOCS_SITE_URL" --source-commit "$SOURCE_COMMIT" --source-root docs
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

#: גרסת המבנה של הקובץ. עולה בכל שינוי במבנה, כדי שקורא שלא מכיר את הגרסה יוכל לסרב לה.
#: 2 — ``title_markdown`` לכל סעיף, ו-``dependencies`` לכל עמוד.
SCHEMA_VERSION = 2

#: מיקום הקובץ, יחסית לתיקיית האתר שנבנתה.
EXPORT_PATH = PurePosixPath("_export/sections.json")

#: מה ש-Sphinx רשם בבנייה כקבצים שכל מסמך נבנה מהם, יחסית לתיקיית האתר שנבנתה. ההרחבה (:func:`setup`)
#: כותבת אותו בסוף הבנייה, והייצוא קורא אותו (:func:`page_dependencies`).
DEPENDENCIES_PATH = PurePosixPath("_export/dependencies.json")

#: עמודים בשורש האתר שאינם תוכן: Sphinx מייצר אותם בעצמו.
EXCLUDED_PAGES = frozenset({"genindex.html", "search.html", "py-modindex.html"})

#: תיקיות שכל העמודים בהן נשארים בחוץ: ``api/`` הם עמודי autodoc שנוצרים מהקוד.
#: תיקיות שמתחילות ב-``_`` או ב-``.`` (``_static``, ``_sources``, ``_modules``,
#: ``.doctrees`` ועוד) הן של Sphinx עצמו, ומדולגות תמיד.
EXCLUDED_TOP_DIRS = frozenset({"api"})

#: סיומות המקור שעמוד יכול להיבנות מהן: rst, ו-md דרך MyST (``docs/conf.py``).
SOURCE_SUFFIXES = (".rst", ".md")

#: תקרה לכל ניווט לעמוד, כדי שעמוד שנתקע לא יעצור את הייצוא בלי סוף.
NAVIGATION_TIMEOUT_MS = 30_000

_SHA_RE = re.compile(r"[0-9a-f]{40}")

#: שם של עותק לפי קומיט, כדי להסיר בתחילת הרצה רק את מה שהסקריפט עצמו כותב.
_COMMIT_EXPORT_NAME_RE = re.compile(
    re.escape(f"{EXPORT_PATH.stem}-") + _SHA_RE.pattern + re.escape(EXPORT_PATH.suffix)
)


def export_path_for_commit(source_commit: str) -> PurePosixPath:
    """מיקום העותק של הקובץ בשם שתלוי בקומיט, יחסית לתיקיית האתר: ``_export/sections-<sha>.json``.

    ה-sha נכנס לשם קובץ ולכתובת באתר, ולכן כל ערך שאינו sha מלא של 40 תווי hex נדחה
    ב-``ValueError``.
    """
    if not isinstance(source_commit, str) or not _SHA_RE.fullmatch(source_commit):
        raise ValueError(f"expected a 40-character commit sha, got {source_commit!r}")
    return EXPORT_PATH.with_name(f"{EXPORT_PATH.stem}-{source_commit}{EXPORT_PATH.suffix}")


#: מה שרץ בתוך כל עמוד. מקבל את הכתובת של העמוד באתר, ומחזיר את הסעיפים שלו.
#: הבחירה של אלמנט המאמר וההמרה עצמה באות מ-``window.DocCopyPage``, ולא מוגדרות כאן
#: פעם שנייה.
_EXTRACT_SECTIONS_JS = r"""
({ pageUrl }) => {
  const api = window.DocCopyPage;
  if (!api || typeof api.toMarkdown !== 'function' || typeof api.articleSelector !== 'string') {
    throw new Error('window.DocCopyPage is missing: copy-page.js did not load');
  }
  const article = document.querySelector(api.articleSelector);
  if (!article) {
    throw new Error(`no article element matches ${api.articleSelector}`);
  }

  const headingOf = (section) =>
    Array.from(section.children).find((el) => /^H[1-6]$/.test(el.tagName)) || null;
  const titleOf = (section) => {
    const heading = headingOf(section);
    if (!heading) {
      throw new Error(`section #${section.id} has no heading`);
    }
    const copy = heading.cloneNode(true);
    copy.querySelectorAll('.headerlink').forEach((el) => el.remove());
    return (copy.textContent || '').replace(/\s+/g, ' ').trim();
  };
  const absolute = (value) => new URL(value, pageUrl).href;

  const sections = [];
  article.querySelectorAll('section').forEach((section) => {
    if (!section.id) {
      throw new Error('a section element has no id');
    }
    const breadcrumb = [];
    for (let node = section; node && article.contains(node); ) {
      breadcrumb.unshift(titleOf(node));
      node = node.parentElement ? node.parentElement.closest('section') : null;
    }

    const clone = section.cloneNode(true);
    clone.querySelectorAll('section').forEach((el) => el.remove());
    clone.querySelectorAll('dl.py').forEach((el) => el.remove());
    clone.querySelectorAll('a[href]').forEach((link) => {
      link.setAttribute('href', absolute(link.getAttribute('href')));
    });
    clone.querySelectorAll('img').forEach((img) => {
      const src = img.getAttribute('src') || '';
      const label = (img.getAttribute('alt') || '').trim() || src.split('/').pop();
      const link = document.createElement('a');
      link.setAttribute('href', absolute(src));
      link.textContent = `תמונה: ${label}`;
      img.replaceWith(link);
    });
    // הכותרת יוצאת מהעותק אחרי שהקישורים והתמונות שבו הוסבו, כדי שקישור בכותרת יוביל לאתר כמו
    // קישור בגוף.
    const heading = headingOf(clone);
    const titleMarkdown = api.toMarkdown(heading).trim();
    heading.remove();

    sections.push({
      anchor: section.id,
      title: breadcrumb[breadcrumb.length - 1],
      title_markdown: titleMarkdown,
      breadcrumb,
      level: breadcrumb.length,
      markdown: api.toMarkdown(clone),
    });
  });
  return { sections };
}
"""


class ExportError(Exception):
    """הייצוא נכשל. ההודעה אומרת איפה, ואין קובץ חלקי."""


def content_pages(html_dir: Path) -> list[str]:
    """עמודי התוכן באתר שנבנה, כנתיבים יחסיים בסדר קבוע.

    בחוץ: :data:`EXCLUDED_PAGES` בשורש, כל מה שתחת :data:`EXCLUDED_TOP_DIRS`, וכל מה
    שתחת תיקייה שמתחילה ב-``_`` או ב-``.``.
    """
    pages = []
    for path in html_dir.rglob("*.html"):
        relative = path.relative_to(html_dir)
        directories = relative.parts[:-1]
        if any(part.startswith(("_", ".")) for part in directories):
            continue
        if directories and directories[0] in EXCLUDED_TOP_DIRS:
            continue
        if not directories and relative.name in EXCLUDED_PAGES:
            continue
        pages.append(relative.as_posix())
    return sorted(pages)


def source_path(html_dir: Path, page: str, source_root: PurePosixPath) -> str:
    """קובץ המקור של עמוד, מהעותק ש-Sphinx שומר תחת ``_sources``.

    Sphinx מעתיק כל קובץ מקור ל-``_sources/<שם המסמך><סיומת>.txt``, כל עוד
    ``html_copy_source`` ו-``html_sourcelink_suffix`` לא נקבעים ב-``docs/conf.py``
    (ברירות המחדל שלהם ב-``sphinx/builders/html/__init__.py``, Sphinx 8.2.3). העמוד
    ``webapp/config-inspector.html`` נבנה מ-``webapp/config-inspector.rst`` אם קיים
    ``_sources/webapp/config-inspector.rst.txt``. עמוד שאין לו מקור אחד בדיוק מכשיל
    את הייצוא.
    """
    stem = page[: -len(".html")]
    found = [
        stem + suffix
        for suffix in SOURCE_SUFFIXES
        if (html_dir / "_sources" / f"{stem}{suffix}.txt").is_file()
    ]
    if len(found) != 1:
        raise ExportError(f"{page}: expected one source under _sources, found {found or 'none'}")
    return (source_root / found[0]).as_posix()


def page_dependencies(html_dir: Path, pages: list[str], source_root: PurePosixPath) -> dict[str, list[str]]:
    """הקבצים בריפו שכל עמוד נבנה מהם מלבד קובץ המקור שלו, יחסית לשורש הריפו וממוינים.

    הנתונים מ-:data:`DEPENDENCIES_PATH`, שההרחבה כתבה באותה בנייה. Sphinx רושם את הנתיבים יחסית לתיקיית
    המקור (``docs``), ו-``source_root`` היא המיקום שלה בריפו. קובץ שנמצא מחוץ לריפו — מודול של פייתון
    או של חבילה מותקנת, ש-autodoc קרא כשתיעד מחלקה שיורשת ממנו — לא נכנס: אין לו גרסה בריפו, ולכן אין
    לדפדפן הריפו מה להשוות. עמוד ש-Sphinx לא רשם לו כלום נבנה מקובץ המקור שלו בלבד. קובץ חסר, או
    שאינו בצורה שההרחבה כותבת, מכשיל את הייצוא: בלעדיו כל עמוד היה נראה כאילו לא נבנה משום קובץ אחר.
    """
    path = html_dir / DEPENDENCIES_PATH
    try:
        raw = json.loads(path.read_bytes())
    except FileNotFoundError as error:
        raise ExportError(
            f"{DEPENDENCIES_PATH} is missing: the build did not load this script as a Sphinx extension (docs/conf.py)"
        ) from error
    except ValueError as error:  # כולל ``UnicodeDecodeError``
        raise ExportError(f"{DEPENDENCIES_PATH} is not JSON: {error}") from error
    if not isinstance(raw, dict) or not all(
        isinstance(docname, str) and isinstance(files, list) and all(isinstance(file, str) for file in files)
        for docname, files in raw.items()
    ):
        raise ExportError(f"{DEPENDENCIES_PATH} is not a map of document names to lists of files")
    result = {}
    for page in pages:
        in_repo = set()
        for file in raw.get(page[: -len(".html")], []):
            repo_path = posixpath.normpath(posixpath.join(source_root.as_posix(), file))
            if posixpath.isabs(repo_path) or repo_path == ".." or repo_path.startswith("../"):
                continue
            in_repo.add(repo_path)
        result[page] = sorted(in_repo)
    return result


def dependency_map(dependencies: Mapping[str, Iterable[Any]], srcdir: Path) -> dict[str, list[str]]:
    """``env.dependencies`` של Sphinx בצורה ש-:data:`DEPENDENCIES_PATH` שומר: לכל מסמך, הנתיבים יחסית
    לתיקיית המקור, בכתיב posix, ממוינים ובלי כפילויות.

    Sphinx שומר נתיב יחסית לתיקיית המקור (``literalinclude`` ותמונות דרך ``relfn2path``, ‏``include``
    ו-autodoc דרך ``DependenciesCollector``), או מוחלט כשאין נתיב יחסי (כונן אחר ב-Windows). ``relpath``
    מחזיר את שניהם לאותה צורה.
    """
    return {
        docname: sorted({Path(os.path.relpath(srcdir / file, srcdir)).as_posix() for file in files})
        for docname, files in dependencies.items()
    }


def setup(app: Any) -> dict[str, Any]:
    """הסקריפט כהרחבה של Sphinx (``extensions`` ב-``docs/conf.py``): בסוף בנייה של HTML הוא כותב את
    :data:`DEPENDENCIES_PATH` מתוך ``env.dependencies``. ההסבר בראש הקובץ ("הקבצים שעמוד נבנה מהם")."""
    app.connect("build-finished", _write_dependencies)
    return {"version": str(SCHEMA_VERSION), "parallel_read_safe": True, "parallel_write_safe": True}


def _write_dependencies(app: Any, exception: BaseException | None) -> None:
    """``build-finished``: רק בבנייה שהצליחה, ורק של HTML (``builder.format``) — הייצוא רץ על האתר."""
    if exception is not None or app.builder.format != "html":
        return
    data = json.dumps(
        dependency_map(app.env.dependencies, Path(app.srcdir)), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    path = Path(app.outdir) / DEPENDENCIES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomically(path, data)


def _validated_sections(raw: Any, page: str) -> list[dict[str, Any]]:
    """הסעיפים שהעמוד החזיר, אחרי בדיקה של כל שדה.

    הערך מגיע מתוך הדפדפן, כלומר מחוץ לתהליך, ולכן כל רמה נבדקת לפני שהיא נכנסת לקובץ.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("sections"), list):
        raise ExportError(f"{page}: the page did not return a sections list")
    sections = raw["sections"]
    if not sections:
        raise ExportError(f"{page}: no sections")
    seen: set[str] = set()
    validated = []
    for index, item in enumerate(sections):
        where = f"{page}, section {index}"
        if not isinstance(item, dict):
            raise ExportError(f"{where}: not an object")
        anchor = item.get("anchor")
        title = item.get("title")
        title_markdown = item.get("title_markdown")
        breadcrumb = item.get("breadcrumb")
        level = item.get("level")
        markdown = item.get("markdown")
        if not isinstance(anchor, str) or not anchor:
            raise ExportError(f"{where}: missing anchor")
        if anchor in seen:
            raise ExportError(f"{where}: anchor #{anchor} appears twice")
        seen.add(anchor)
        if not isinstance(title, str) or not title:
            raise ExportError(f"{where} (#{anchor}): empty title")
        # כותרת במארקדאון היא שורה אחת: שבירת שורה הייתה מסיימת אותה באמצע, ושאר הטקסט היה יוצא
        # מתחתיה כפסקה.
        if not isinstance(title_markdown, str) or not title_markdown.strip():
            raise ExportError(f"{where} (#{anchor}): empty title_markdown")
        if "\n" in title_markdown or "\r" in title_markdown:
            raise ExportError(f"{where} (#{anchor}): title_markdown spans more than one line")
        if (
            not isinstance(breadcrumb, list)
            or not breadcrumb
            or not all(isinstance(crumb, str) and crumb for crumb in breadcrumb)
            or breadcrumb[-1] != title
        ):
            raise ExportError(f"{where} (#{anchor}): bad breadcrumb")
        # ``type`` ולא ``isinstance``: ‏``True`` הוא ``int`` בפייתון.
        if type(level) is not int or level != len(breadcrumb):
            raise ExportError(f"{where} (#{anchor}): level does not match the breadcrumb")
        if not isinstance(markdown, str):
            raise ExportError(f"{where} (#{anchor}): markdown is not text")
        validated.append(
            {
                "anchor": anchor,
                "title": title,
                "title_markdown": title_markdown,
                "breadcrumb": breadcrumb,
                "level": level,
                "markdown": markdown,
            }
        )
    return validated


def export_sections(
    html_dir: Path,
    *,
    site_url: str,
    source_commit: str,
    source_root: PurePosixPath,
    chromium_executable: str | None = None,
) -> dict[str, Any]:
    """מייצא את כל עמודי התוכן, כותב את הקובץ ואת העותק שלו, ומחזיר את מה שנקרא מהקובץ מחדש.

    זורק :class:`ExportError` על כל כשל, ואז אין קובץ ב-:data:`EXPORT_PATH` ואין עותק לפי
    קומיט.
    """
    out_path = html_dir / EXPORT_PATH
    commit_path = html_dir / export_path_for_commit(source_commit)
    # קבצים מהרצה קודמת לא נשארים: ייצוא שנכשל חייב להשאיר אתר בלי קובץ, ולא עם קובץ ישן
    # שנראה עדכני.
    _remove_previous_exports(out_path.parent)

    pages = content_pages(html_dir)
    if not pages:
        raise ExportError(f"no content pages under {html_dir}")
    sources = {page: source_path(html_dir, page, source_root) for page in pages}
    dependencies = page_dependencies(html_dir, pages, source_root)

    # הייבוא כאן ולא בראש הקובץ: את הפונקציות האחרות אפשר לייבא ולבדוק גם בלי Playwright.
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    exported_pages: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = (
            playwright.chromium.launch(executable_path=chromium_executable)
            if chromium_executable
            else playwright.chromium.launch()
        )
        try:
            context = browser.new_context(offline=True)
            tab = context.new_page()
            page_errors: list[str] = []
            tab.on("pageerror", lambda error: page_errors.append(str(error)))
            for page in pages:
                page_errors.clear()
                try:
                    response = tab.goto(
                        (html_dir / page).resolve().as_uri(),
                        wait_until="domcontentloaded",
                        timeout=NAVIGATION_TIMEOUT_MS,
                    )
                    if response is None or not response.ok:
                        status = None if response is None else response.status
                        raise ExportError(f"{page}: the page did not load (status {status})")
                    raw = tab.evaluate(_EXTRACT_SECTIONS_JS, {"pageUrl": site_url + page})
                except PlaywrightError as error:
                    detail = f" (page errors: {page_errors})" if page_errors else ""
                    raise ExportError(f"{page}: {error}{detail}") from error
                exported_pages.append(
                    {
                        "path": page,
                        "source_path": sources[page],
                        "dependencies": dependencies[page],
                        "sections": _validated_sections(raw, page),
                    }
                )
        finally:
            browser.close()

    document = build_document(exported_pages, site_url=site_url, source_commit=source_commit)

    # סריאליזציה אחת לשני הקבצים, כדי שהעותק יהיה זהה בית-בבית ולא רק "אותו תוכן".
    data = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_atomically(out_path, data)
        _write_atomically(commit_path, data)
        stored = _read_back(out_path, document)
        if commit_path.read_bytes() != out_path.read_bytes():
            raise ExportError(f"{commit_path}: the commit copy differs from {out_path}")
    except BaseException:
        # אחד בלי השני הוא מצב שאיש לא מצפה לו: הוובאפ מבקש את העותק לפי הקומיט ממסלול אחד
        # ואת הראשי ממסלול אחר.
        out_path.unlink(missing_ok=True)
        commit_path.unlink(missing_ok=True)
        raise
    return stored


def build_document(
    exported_pages: list[dict[str, Any]], *, site_url: str, source_commit: str
) -> dict[str, Any]:
    """המסמך שנכתב לקובץ, מהעמודים שיוצאו (כל אחד עם ``path``, ``source_path``, ``dependencies`` ו-``sections``).

    פונקציה נפרדת ולא חלק מ-:func:`export_sections`, כדי שאפשר יהיה להריץ אותה בלי דפדפן:
    ``tests/test_docs_search_contract.py`` מעביר את מה שהיא בונה דרך הקורא של הוובאפ
    (``services/docs_export_client.parse_export``), וכך מבנה הקובץ נבדק משני צדי החוזה.
    """
    section_count = sum(len(entry["sections"]) for entry in exported_pages)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_commit": source_commit,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site_url": site_url,
        "page_count": len(exported_pages),
        "section_count": section_count,
        "pages": [
            {
                "path": entry["path"],
                "source_path": entry["source_path"],
                # הכותרת של העמוד היא הכותרת של הסעיף הראשון בו, כמו ש-Sphinx קובע כותרת למסמך.
                "title": entry["sections"][0]["breadcrumb"][0],
                "dependencies": entry["dependencies"],
                "sections": entry["sections"],
            }
            for entry in exported_pages
        ],
    }


def _remove_previous_exports(export_dir: Path) -> None:
    """מסיר את הקובץ הראשי ואת כל העותקים לפי קומיט שבתיקייה, ולא נוגע בשום קובץ אחר."""
    (export_dir / EXPORT_PATH.name).unlink(missing_ok=True)
    if not export_dir.is_dir():
        return
    for path in export_dir.iterdir():
        if _COMMIT_EXPORT_NAME_RE.fullmatch(path.name):
            path.unlink()


def _write_atomically(path: Path, data: bytes) -> None:
    """כותב לקובץ זמני באותה תיקייה ומחליף בשם הסופי, כך שאין רגע שבו קיים קובץ חצי כתוב."""
    handle, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        # ``mkstemp`` יוצר קובץ שרק הבעלים יכול לקרוא (0600). הקובץ הזה הוא חלק מאתר שמוגש
        # לכולם, ולכן הוא מקבל את ההרשאות ש-Sphinx נותן לשאר הקבצים באתר (0644).
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_back(out_path: Path, written: dict[str, Any]) -> dict[str, Any]:
    """קורא את הקובץ מהדיסק ובודק אותו מול מה שהסקריפט ספר, ולא מסתפק בכך שהכתיבה לא זרקה."""
    stored = json.loads(out_path.read_text(encoding="utf-8"))
    pages = stored.get("pages") if isinstance(stored, dict) else None
    if not isinstance(pages, list):
        raise ExportError(f"{out_path}: the written file has no pages list")
    pages_read = len(pages)
    sections_read = sum(
        len(page["sections"])
        for page in pages
        if isinstance(page, dict) and isinstance(page.get("sections"), list)
    )
    checks = {
        "schema_version": (stored.get("schema_version"), written["schema_version"]),
        "source_commit": (stored.get("source_commit"), written["source_commit"]),
        "page_count": (stored.get("page_count"), written["page_count"]),
        "pages read": (pages_read, written["page_count"]),
        "section_count": (stored.get("section_count"), written["section_count"]),
        "sections read": (sections_read, written["section_count"]),
    }
    mismatched = {name: pair for name, pair in checks.items() if pair[0] != pair[1]}
    if mismatched:
        out_path.unlink(missing_ok=True)
        raise ExportError(f"{out_path}: the written file does not match the export: {mismatched}")
    return stored


def _site_url(value: str) -> str:
    """כתובת האתר: https, בלי שאילתה, בלי עוגן ובלי פרטי משתמש, ומסתיימת ב-``/``."""
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not parts.path.endswith("/")
    ):
        raise argparse.ArgumentTypeError(
            f"expected an https site URL that ends with '/', got {value!r}"
        )
    return value


def _source_commit(value: str) -> str:
    if not _SHA_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(f"expected a 40-character commit sha, got {value!r}")
    return value


def _source_root(value: str) -> PurePosixPath:
    root = PurePosixPath(value)
    if not value or root.is_absolute() or ".." in root.parts or str(root) == ".":
        raise argparse.ArgumentTypeError(
            f"expected the docs source folder relative to the repo, got {value!r}"
        )
    return root


def main(argv: list[str] | None = None) -> int:
    """נקודת הכניסה. ``argv`` כרשימה, כדי שאפשר יהיה להריץ אותה מטסט."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("html_dir", type=Path, help="תיקיית האתר שנבנתה (הפלט של sphinx -b html).")
    parser.add_argument(
        "--site-url", required=True, type=_site_url,
        help="הכתובת שבה האתר מוגש. ממנה נבנים הקישורים המלאים, והיא נכתבת לקובץ.",
    )
    parser.add_argument(
        "--source-commit", required=True, type=_source_commit,
        help="ה-sha של הקומיט שממנו האתר נבנה.",
    )
    parser.add_argument(
        "--source-root", required=True, type=_source_root,
        help="תיקיית המקור של התיעוד בריפו (זו שבה docs/conf.py), למשל docs.",
    )
    parser.add_argument(
        "--chromium-executable", default=None,
        help="נתיב ל-Chromium מסוים. בלי זה Playwright משתמש בדפדפן שהוא התקין.",
    )
    args = parser.parse_args(argv)

    html_dir = args.html_dir.resolve()
    if not html_dir.is_dir():
        print(f"אין תיקיית אתר: {html_dir}", file=sys.stderr)
        return 2

    started = time.monotonic()
    try:
        stored = export_sections(
            html_dir,
            site_url=args.site_url,
            source_commit=args.source_commit,
            source_root=args.source_root,
            chromium_executable=args.chromium_executable,
        )
    except ExportError as error:
        print(f"הייצוא נכשל, ולא נכתב קובץ: {error}", file=sys.stderr)
        return 1
    out_path = html_dir / EXPORT_PATH
    print(
        f"{out_path}: {stored['page_count']} עמודים, {stored['section_count']} סעיפים, "
        f"{out_path.stat().st_size} בתים, {time.monotonic() - started:.1f} שניות"
    )
    print(f"{html_dir / export_path_for_commit(args.source_commit)}: עותק זהה בשם של הקומיט")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""ייצוא הסעיפים של אתר התיעוד, בדפדפן אמיתי, על אתר קטן שבנוי כמו הפלט של Sphinx.

**למה דפדפן.** ``scripts/docs_export_sections.py`` לא ממיר בעצמו: הוא פותח כל עמוד
ב-Chromium ומריץ עליו את ``window.DocCopyPage.toMarkdown`` מ-``docs/_static/copy-page.js``,
הממיר של כפתור "העתק תוכן הדף". לכן הבדיקה טוענת את הקבצים האמיתיים — ``copy-page.js``
ו-Turndown מ-``docs/_static/vendor`` — לתוך עמודים שבנויים כמו העמודים שהאתר מייצר:
אותם עוטפים של ערכת הנושא, סעיפים מקוננים עם ``headerlink``, הערה, תמונה, תרשים mermaid,
בלוק autodoc, ותגית ``type="module"`` שטוענת את mermaid מ-CDN.

**ושהפונקציה היא באמת ההמרה של הכפתור** נבדק דרך הכפתור עצמו: לחיצה, ומה שנכתב ללוח,
מול מה שהפונקציה מחזירה לאותו מאמר.

מדולג כשאין Chromium (הפיקסצ'ר ``chromium_executable`` ב-``tests/conftest.py``).
"""

from __future__ import annotations

import functools
import http.server
import json
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path, PurePosixPath

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import docs_export_sections as export  # noqa: E402  (אחרי sys.path.insert, כמו בשאר טסטי הריפו)
from services import docs_index_service as index  # noqa: E402
from services import docs_search_contract as contract  # noqa: E402
from services.docs_export_client import parse_export  # noqa: E402

STATIC = ROOT / "docs" / "_static"
SITE_URL = "https://docs.example.test/CodeBot/"
COMMIT = "0123456789abcdef0123456789abcdef01234567"

_PAGE = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8" />
{scripts}
<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.2.0/dist/mermaid.esm.min.mjs";
window.addEventListener("load", () => mermaid.run());</script>
</head>
<body class="wy-body-for-nav">
<div class="wy-nav-content">
<div class="rst-content">
<div role="main" class="document" itemscope="itemscope" itemtype="http://schema.org/Article">
<div itemprop="articleBody">
{body}
</div>
</div>
</div>
</div>
</body>
</html>
"""

#: כמו ש-Sphinx מוסיף אותם (``app.add_js_file`` ב-``docs/conf.py``), כולל ``?v=``.
_SCRIPTS = """<script src="{static}/vendor/turndown.umd.js?v=1"></script>
<script src="{static}/vendor/turndown-plugin-gfm.js?v=1"></script>
<script src="{static}/copy-page.js?v=1"></script>"""

_INDEX_BODY = """<section id="guide">
<span id="label-guide"></span>
<h1>מדריך<a class="headerlink" href="#guide" title="Link to this heading">¶</a></h1>
<p>פתיחה עם
<a class="reference internal" href="guide/other.html#target"><span>קישור פנימי</span></a>
ועם <a class="reference external" href="https://example.com/page">קישור חיצוני</a>.</p>
<section id="id1">
<h2>סעיף ראשון<a class="headerlink" href="#id1" title="Link to this heading">¶</a></h2>
<div class="admonition warning">
<p class="admonition-title">אזהרה</p>
<p>זהירות בדרך.</p>
</div>
<p><img alt="תרשים זרימה" src="_images/flow.svg" style="width: 520px;" /></p>
<pre class="mermaid">
        graph TD
  A--&gt;B
</pre>
<dl class="py function">
<dt class="sig sig-object py" id="mod.func"><span class="sig-name descname">func</span>()</dt>
<dd><p>טקסט שנוצר מהקוד</p></dd>
</dl>
<p>עוד בסעיף <a class="reference internal" href="#deep">לעומק</a>.</p>
<section id="deep">
<h3>עמוק<a class="headerlink" href="#deep" title="Link to this heading">¶</a></h3>
<p>תוכן עמוק</p>
</section>
</section>
</section>"""

_OTHER_BODY = """<section id="other">
<h1>עמוד נוסף<a class="headerlink" href="#other" title="Link to this heading">¶</a></h1>
<section id="target">
<h2>היעד<a class="headerlink" href="#target" title="Link to this heading">¶</a></h2>
<p>חזרה <a class="reference internal" href="../index.html#guide">למדריך</a>.</p>
</section>
</section>"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(depth: int, body: str, *, with_copy_page: bool = True) -> str:
    static = "/".join([".."] * depth + ["_static"])
    scripts = _SCRIPTS.format(static=static) if with_copy_page else ""
    return _PAGE.format(scripts=scripts, body=body)


def _site(tmp_path: Path) -> Path:
    """אתר קטן בצורה של ``docs/_build/html``, עם הקבצים האמיתיים של כפתור ההעתקה."""
    site = tmp_path / "html"
    for name in ("copy-page.js", "vendor/turndown.umd.js", "vendor/turndown-plugin-gfm.js"):
        target = site / "_static" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STATIC / name, target)
    _write(site / "index.html", _page(0, _INDEX_BODY))
    _write(site / "_sources" / "index.rst.txt", "מדריך\n=====\n")
    _write(site / "guide" / "other.html", _page(1, _OTHER_BODY))
    _write(site / "_sources" / "guide" / "other.md.txt", "# עמוד נוסף\n")
    # עמודים שאינם תוכן: אם הייצוא היה פותח אותם, אין להם מקור והוא היה נכשל.
    _write(site / "api" / "module.html", _page(1, '<section id="api"><h1>api</h1></section>'))
    _write(site / "genindex.html", _page(0, '<section id="index"><h1>אינדקס</h1></section>'))
    _write(site / "_modules" / "mod.html", "<html><body>source</body></html>")
    return site


def _export(site: Path, chromium_executable: str | None) -> dict:
    return export.export_sections(
        site,
        site_url=SITE_URL,
        source_commit=COMMIT,
        source_root=PurePosixPath("docs"),
        chromium_executable=chromium_executable,
    )


def test_every_content_section_is_exported_on_its_own(chromium_executable, tmp_path):
    site = _site(tmp_path)

    returned = _export(site, chromium_executable)

    stored = json.loads((site / export.EXPORT_PATH).read_text(encoding="utf-8"))
    assert returned == stored
    # קובץ שמוגש באתר: קריא לכולם, כמו שאר הקבצים ש-Sphinx כותב.
    assert (site / export.EXPORT_PATH).stat().st_mode & 0o777 == 0o644
    # העותק בשם של הקומיט — אותם בתים בדיוק, ואותן הרשאות.
    commit_copy = site / "_export" / f"sections-{COMMIT}.json"
    assert commit_copy.read_bytes() == (site / export.EXPORT_PATH).read_bytes()
    assert commit_copy.stat().st_mode & 0o777 == 0o644
    assert sorted(path.name for path in commit_copy.parent.iterdir()) == sorted(
        ["sections.json", f"sections-{COMMIT}.json"]
    )
    assert stored["schema_version"] == export.SCHEMA_VERSION
    assert stored["source_commit"] == COMMIT
    assert stored["site_url"] == SITE_URL
    assert datetime.fromisoformat(stored["built_at"]).utcoffset() is not None
    assert (stored["page_count"], stored["section_count"]) == (2, 5)

    pages = {page["path"]: page for page in stored["pages"]}
    assert list(pages) == ["guide/other.html", "index.html"]
    assert pages["index.html"]["source_path"] == "docs/index.rst"
    assert pages["guide/other.html"]["source_path"] == "docs/guide/other.md"
    assert pages["index.html"]["title"] == "מדריך"

    sections = {section["anchor"]: section for section in pages["index.html"]["sections"]}
    assert list(sections) == ["guide", "id1", "deep"]
    assert [(s["title"], s["level"], s["breadcrumb"]) for s in sections.values()] == [
        ("מדריך", 1, ["מדריך"]),
        ("סעיף ראשון", 2, ["מדריך", "סעיף ראשון"]),
        ("עמוק", 3, ["מדריך", "סעיף ראשון", "עמוק"]),
    ]

    # הסעיף העליון: רק התוכן שלו, בלי הכותרת ובלי תתי-הסעיפים, וקישורים מלאים לאתר.
    top = sections["guide"]["markdown"]
    assert f"[קישור פנימי]({SITE_URL}guide/other.html#target)" in top
    assert "[קישור חיצוני](https://example.com/page)" in top
    assert "מדריך" not in top
    assert "זהירות" not in top and "תוכן עמוק" not in top

    first = sections["id1"]["markdown"]
    assert "::: warning\nזהירות בדרך.\n:::" in first
    assert f"[תמונה: תרשים זרימה]({SITE_URL}_images/flow.svg)" in first
    assert "```mermaid\ngraph TD\nA-->B\n```" in first
    assert f"[לעומק]({SITE_URL}index.html#deep)" in first
    assert "טקסט שנוצר מהקוד" not in first and "func" not in first
    assert "תוכן עמוק" not in first

    back = pages["guide/other.html"]["sections"][1]["markdown"]
    assert f"[למדריך]({SITE_URL}index.html#guide)" in back


def test_to_markdown_is_what_the_copy_button_copies(chromium_executable, tmp_path):
    """הפונקציה שהייצוא קורא לה היא ההמרה של הכפתור: אותו מאמר, אותו טקסט בדיוק."""
    site = _site(tmp_path)
    capture_clipboard = """
        Object.defineProperty(navigator, 'clipboard', {
          configurable: true,
          value: { writeText: async (text) => { window.__copied = text; } },
        });
    """
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
            context = browser.new_context(offline=True)
            context.add_init_script(capture_clipboard)
            page = context.new_page()
            page.goto((site / "index.html").as_uri(), wait_until="domcontentloaded")
            from_api = page.evaluate(
                "() => window.DocCopyPage.toMarkdown("
                "document.querySelector(window.DocCopyPage.articleSelector))"
            )
            page.click(".doc-copy-page__button")
            page.wait_for_function("() => typeof window.__copied === 'string'", timeout=10_000)
            from_button = page.evaluate("() => window.__copied")
        finally:
            browser.close()

    assert from_button == from_api
    assert "::: warning" in from_api and "```mermaid" in from_api


def test_a_broken_page_fails_the_whole_export_and_leaves_no_file(chromium_executable, tmp_path):
    site = _site(tmp_path)
    stale = site / export.EXPORT_PATH
    _write(stale, '{"schema_version": 1}')
    # עותק לפי קומיט מהרצה קודמת, וגם עותק של הקומיט הנוכחי: שניהם חייבים להיעלם.
    _write(site / "_export" / f"sections-{'f' * 40}.json", '{"schema_version": 1}')
    _write(site / "_export" / f"sections-{COMMIT}.json", '{"schema_version": 1}')
    # עמוד שלא טוען את copy-page.js: אין לו DocCopyPage, ולכן אין ממה לייצא.
    _write(site / "broken.html", _page(0, _OTHER_BODY, with_copy_page=False))
    _write(site / "_sources" / "broken.rst.txt", "שבור\n====\n")

    with pytest.raises(export.ExportError, match=r"broken\.html.*DocCopyPage"):
        _export(site, chromium_executable)

    assert not stale.exists()
    assert not list(stale.parent.iterdir())


def test_the_cli_runs_the_export_end_to_end(chromium_executable, tmp_path, capsys):
    site = _site(tmp_path)
    argv = [
        str(site),
        "--site-url", SITE_URL,
        "--source-commit", COMMIT,
        "--source-root", "docs",
    ]
    if chromium_executable:
        argv += ["--chromium-executable", chromium_executable]

    assert export.main(argv) == 0

    stored = json.loads((site / export.EXPORT_PATH).read_text(encoding="utf-8"))
    assert stored["section_count"] == 5
    out = capsys.readouterr().out
    assert str(site / export.EXPORT_PATH) in out
    assert str(site / "_export" / f"sections-{COMMIT}.json") in out


# ---------------------------------------------------------------------------
# יומן עדכונים: מהעמוד, דרך הייצוא והאינדקס, אל הקישור — בדפדפן
# ---------------------------------------------------------------------------


def _code(text: str) -> str:
    """קוד בשורה, כמו ש-Sphinx בונה אותו: ``<span class="pre">`` לכל מילה, ורווח ביניהן."""
    words = " ".join(f'<span class="pre">{word}</span>' for word in text.split(" "))
    return f'<code class="docutils literal notranslate">{words}</code>'


def _update_log_body() -> str:
    """עמוד What's New בצורה ש-Sphinx בונה (הקטעים נלקחו מהעמוד החי, 11.10.2026): יום עם עדכונים רבים,
    כך שעדכון בסוף היום רחוק מהעוגן של היום, ואחריו יום נוסף."""
    filler = "".join(
        f"<li><p><strong>fix: מילוי מספר {n}.</strong> טקסט שממלא את היום, כדי שהעדכונים שבסופו יהיו "
        f"רחוקים מהכותרת שלו.</p></li>\n"
        for n in range(30)
    )
    targets = "\n".join(
        f"<li><p>{inner}</p></li>"
        for inner in (
            f"<strong>docs: תוקנה סתירה בין התיעוד לקוד ב-</strong>{_code('POST /api/themes/import')}"
            "<strong>.</strong> העמוד תיעד גוף בקשה אחר.",
            "<strong>ההעתקה קוראת את המקור ולא את ה-DOM.</strong> שורה ריקה מרונדרת כרווח.",
            "<strong>docs (MCP): בלוק ה-``instructions`` מזכיר את ``x_y`` ו-*.</strong> עוד.",
            "<strong>fix: ``&amp;lt;div&amp;gt;`` נשמר כמו שהוקלד.</strong> עוד.",
            f"<strong>fix:</strong> {_code('page/per_page')} <strong>היה הפיצ’ר היחיד בלי טסט.</strong> הוחזר.",
            "<strong>מגבלה ידועה:</strong> אין מיגרציה.",
            "feat (פרופיילר): בלי פתיח מודגש. וקודם כול — <strong>חלון זמן אחד</strong>.",
        )
    )
    return f"""<section id="what-s-new">
<h1>What’s New<a class="headerlink" href="#what-s-new" title="Link to this heading">¶</a></h1>
<section id="id1">
<h2>2026-10-07<a class="headerlink" href="#id1" title="Link to this heading">¶</a></h2>
<ul class="simple">
{filler}{targets}
</ul>
<p>קישורים ל‑Issues רלוונטיים: <cite>#1198</cite>, <cite>#1239</cite>.</p>
</section>
<section id="id2">
<h2>2026-10-06<a class="headerlink" href="#id2" title="Link to this heading">¶</a></h2>
<ul class="simple">
<li><p><strong>מגבלה ידועה:</strong> החיפוש איטי בזמן ה-re-index.</p></li>
</ul>
</section>
</section>"""


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D401 — שקט בפלט של pytest
        pass


#: הטקסט שהעמוד מציג בפתיח של כל עדכון: ההדגשה הראשונה, ואחריה הדגשות וקטעי קוד צמודים או מופרדים
#: ברווח, עד ההדגשה האחרונה — אותו כלל של ``_headline`` ב-``services/docs_index_service.py``, על ה-DOM.
_DOM_HEADLINES = r"""
() => Array.from(document.querySelectorAll('section[id] > ul > li')).map((li) => {
  const p = li.querySelector(':scope > p') || li;
  const run = [];
  for (const node of p.childNodes) {
    const tag = node.nodeType === Node.ELEMENT_NODE ? node.tagName : null;
    if (tag === 'STRONG' || (run.length && (tag === 'CODE'
        || (node.nodeType === Node.TEXT_NODE && /^[ \t]*$/.test(node.textContent))))) {
      run.push(node);
      continue;
    }
    break;
  }
  while (run.length && run[run.length - 1].tagName !== 'STRONG') run.pop();
  return run.map((node) => node.textContent).join('').replace(/\s+/g, ' ').trim();
})
"""

_IN_VIEW = r"""
(needle) => {
  const norm = (text) => text.replace(/\s+/g, ' ').trim();
  const li = Array.from(document.querySelectorAll('section[id] > ul > li'))
    .find((item) => norm(item.textContent).startsWith(needle));
  const box = li.getBoundingClientRect();
  return box.bottom > 0 && box.top < window.innerHeight;
}
"""


def test_an_update_headline_is_the_text_on_the_page_and_its_link_jumps_to_it(chromium_executable, tmp_path):
    """השרשרת כולה, מול הצרכן האמיתי: העמוד ← הממיר של כפתור ההעתקה ← הרשומות של האינדקס ← הקישור.

    הכותרת של עדכון חייבת להיות בדיוק הטקסט שהעמוד מציג — אחרת הקפיצה (``text_fragment``) לא מוצאת
    אותו. והקפיצה היא מה שמביא את העדכון למסך: בלעדיה, הקישור מגיע לראש היום, רחוק מהעדכון. וכשהטקסט
    כבר אינו בעמוד (עדכון שנערך אחרי שהאינדקס נבנה), הקישור מגיע לראש היום, כמו קישור בלי קפיצה.
    """
    site = tmp_path / "html"
    for name in ("copy-page.js", "vendor/turndown.umd.js", "vendor/turndown-plugin-gfm.js"):
        target = site / "_static" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STATIC / name, target)
    _write(site / "whats-new.html", _page(0, _update_log_body()))
    _write(site / "_sources" / "whats-new.rst.txt", "What's New\n==========\n")

    exported = _export(site, chromium_executable)
    records, _chunks = index.build_records(parse_export(json.dumps(exported).encode("utf-8")))
    jumps = {record.link_text: record for record in records if record.link_text}
    expected = [
        "docs: תוקנה סתירה בין התיעוד לקוד ב-POST /api/themes/import.",
        "ההעתקה קוראת את המקור ולא את ה-DOM.",
        "docs (MCP): בלוק ה-``instructions`` מזכיר את ``x_y`` ו-*.",
        "fix: ``&lt;div&gt;`` נשמר כמו שהוקלד.",
        "fix: page/per_page היה הפיצ’ר היחיד בלי טסט.",
    ]
    assert all(title in jumps for title in expected), sorted(jumps)
    # תווית שחוזרת בעמוד, ועדכון בלי פתיח — בשם של היום, ובלי קפיצה.
    unlabeled = [(record.title, record.markdown.split(" ")[0]) for record in records if not record.link_text]
    assert unlabeled == [
        ("2026-10-07", "**מגבלה"), ("2026-10-07", "feat"), ("2026-10-07", "קישורים"), ("2026-10-06", "**מגבלה"),
    ]

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_QuietHandler, directory=site))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/whats-new.html"
    try:
        with sync_playwright() as p:
            try:
                browser = (
                    p.chromium.launch(executable_path=chromium_executable)
                    if chromium_executable
                    # בלי נתיב, Playwright 1.49 מרים במצב headless את chromium-headless-shell (``getExecutableName``
                    # ב-``playwright/driver/package/lib/server/chromium/chromium.js``), ושם הקפיצה לטקסט לא קורית:
                    # הדף מגיע לעוגן בלבד (נמדד על build 1148, 11.10.2026). ``channel="chromium"`` הוא ה-Chromium
                    # המלא, שקופץ.
                    else p.chromium.launch(channel="chromium")
                )
            except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
                pytest.skip(f"אין Chromium זמין: {exc}")
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 400})
                page.goto(base)
                on_page = set(page.evaluate(_DOM_HEADLINES))
                assert set(expected) <= on_page
                for title in expected:
                    record = jumps[title]
                    page.goto("about:blank")
                    page.goto(f"{base}#{record.anchor}")
                    assert page.evaluate(_IN_VIEW, title) is False, f"בלי הקפיצה, העדכון כבר על המסך: {title}"
                    page.goto("about:blank")
                    page.goto(f"{base}#{record.anchor}{contract.text_fragment(title)}")
                    poll(page, _IN_VIEW, f"הקפיצה מביאה את העדכון למסך: {title}", title)

                # טקסט שאינו בעמוד: הדפדפן עובר לעוגן שלפני ``:~:``, אבל רק אחרי שהחיפוש נכשל (ב-Chromium 141,
                # 300ms אחרי הטעינה הדף עוד היה בראש העמוד — נמדד 11.10.2026). לכן מחכים ל-``:target``.
                day = next(record.anchor for record in records if record.title == "2026-10-06")
                page.goto("about:blank")
                page.goto(f"{base}#{day}")
                at_day = page.evaluate("() => window.scrollY")
                assert at_day > 0, "היום השני כבר בראש העמוד, ואז אין הבדל בין מעבר לעוגן לבין הישארות בראש העמוד"
                page.goto("about:blank")
                page.goto(f"{base}#{day}{contract.text_fragment('עדכון שכבר אינו בעמוד')}")
                poll(page, "(day) => document.querySelector(':target')?.id === day", f"הדפדפן עובר לעוגן {day}", day)
                assert page.evaluate("() => window.scrollY") == at_day
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()

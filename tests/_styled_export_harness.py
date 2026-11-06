"""מה שמשותף לבדיקות הדפדפן של הייצוא ל-HTML מעוצב — מהעורך הציבורי ומעמוד הקובץ: המדידה של הקובץ שירד, ופתיחה
שלו לבד, בלי רשת.

**למה קובץ משותף.** שני המסלולים מייצרים את אותו קובץ מאותו מנוע (``MarkdownLiveRenderer.renderForExport``), ולכן
אותה מדידה בודקת את שניהם. עותק שני שלה היה נסחף מהראשון ביום שמוסיפים לה רכיב.

**ומה אין כאן, בכוונה: הרמת הדפדפן** (``tests/test_browser_suite_is_gated_once.py``). ``open_file`` מקבלת דפדפן שכבר
הורם.
"""

from __future__ import annotations

#: מה שנמדד בקובץ שירד: כל רכיב, והמצב שממנו אפשר לדעת שהוא עוצב.
PROBE_FILE = r"""
() => {
  const root = document.querySelector('main.container');
  const cs = (el) => getComputedStyle(el);
  const out = { header: !!document.querySelector('body > header'), footer: document.querySelector('footer').innerText };

  const alerts = [...root.querySelectorAll('.admonition')];
  out.alerts = { count: alerts.length,
    styled: alerts.filter((a) => parseFloat(cs(a).borderInlineStartWidth) >= 4 && cs(a).backgroundColor !== 'rgba(0, 0, 0, 0)').length };

  let tok = 0, colored = 0;
  root.querySelectorAll('pre code.hljs').forEach((code) => {
    const base = cs(code).color;
    const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      const len = n.textContent.replace(/\s+/g, '').length;
      const el = n.parentElement;
      if (!len || el === code) continue;
      tok += len;
      if (cs(el).color !== base) colored += len;
    }
  });
  out.code = { pres: root.querySelectorAll('pre').length, tokenChars: tok, coloredPct: tok ? Math.round(100 * colored / tok) : 0,
    copyButtonsPerPre: [...root.querySelectorAll('pre')].map((p) => p.querySelectorAll('.copy-btn').length),
    themeCopyButtons: root.querySelectorAll('.md-copy-btn').length,
    headerLabels: [...root.querySelectorAll('.md-code-header')].map((h) => h.textContent) };

  out.alignedCells = [...root.querySelectorAll('td[style]')].map((c) => cs(c).textAlign);
  out.nestedDepth = Math.max(0, ...[...root.querySelectorAll('li')].map((li) => { let d = 0, p = li; while ((p = p.parentElement && p.parentElement.closest('li'))) d++; return d; }));
  const boxes = [...root.querySelectorAll('input[type=checkbox]')];
  out.tasks = { count: boxes.length, checked: boxes.filter((b) => b.checked).length, disabled: boxes.filter((b) => b.disabled).length,
    bullets: boxes.filter((b) => cs(b.closest('li')).listStyleType !== 'none').length };
  const mark = root.querySelector('mark');
  out.markBg = mark ? cs(mark).backgroundColor : null;
  const strike = root.querySelector('s');
  out.strike = strike ? cs(strike).textDecorationLine : null;
  out.h5h6 = root.querySelectorAll('h5, h6').length;
  const internal = [...root.querySelectorAll('a[href^="#"]')];
  out.anchors = { internal: internal.length, broken: internal.filter((a) => !document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1)))).length };
  const k = root.querySelector('.katex');
  out.katex = { count: root.querySelectorAll('.katex').length,
    mathmlShown: k ? cs(k.querySelector('.katex-mathml')).position !== 'absolute' : null,
    font: k && k.querySelector('.mord') ? cs(k.querySelector('.mord')).fontFamily : null,
    fontsLoaded: [...document.fonts].filter((f) => f.family.includes('KaTeX') && f.status === 'loaded').length,
    pageScrollsSideways: document.scrollingElement.scrollWidth > document.scrollingElement.clientWidth };
  const rect = root.querySelector('.mermaid-diagram .node rect, .mermaid-diagram .node polygon');
  out.mermaid = { svgs: root.querySelectorAll('.mermaid-diagram svg').length, nodeFill: rect ? cs(rect).fill : null };
  out.internal = { sourceLines: root.querySelectorAll('[data-source-line]').length, highlighted: root.querySelectorAll('[data-highlighted]').length };
  return out;
}
"""


def open_file(browser, path):
    """פותח קובץ שירד, לבד, בהקשר חדש שבו כל בקשה שאינה לקובץ מקומי נחסמת ונרשמת."""
    b, _app = browser
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    attempts: list[str] = []
    dialogs: list[str] = []

    def block(route, request):
        if request.url.startswith("file://"):
            return route.continue_()
        attempts.append(request.url)
        return route.abort()

    ctx.route("**/*", block)
    page = ctx.new_page()
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    page.goto(path.as_uri())
    page.wait_for_function("document.readyState === 'complete'")
    return ctx, page, attempts, dialogs

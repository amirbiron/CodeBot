"""תצוגת ה-Markdown בדפדפן הריפו אינה תלויה בסדר שבו נטענים ``repo-browser.css`` ו-``markdown-preview.css``.

**למה הבדיקה קיימת.** הכללים של התצוגה עברו מ-``repo-browser.css`` לקובץ משותף,
``markdown-preview.css``, כדי שכרטיסי התיעוד בחיפוש בעמוד הקבצים ייראו בדיוק כמו התצוגה בדפדפן
הריפו. ההעברה שינתה את המקום שלהם ביחס לכללים שנשארו ב-``repo-browser.css``. כשכלל משותף וכלל
של ``repo-browser.css`` חלים על אותו מאפיין של אותו אלמנט, באותה ספציפיות, מי שנטען אחרון
מנצח. זה בדיוק מה שהעברה כזו משנה בשקט.

**מה נבדק.** אותו מסמך מרונדר בשני עמודים. הראשון הוא העמוד כמו שהשרת מגיש אותו. בשני, הכללים
המשותפים נטענים *לפני* כל ``repo-browser.css`` (התוכן מוגש דרך ``page.route``). בכל ערכה, כל
המאפיינים המחושבים של כל אלמנט בתצוגה, כולל ``::before``, ``::after`` ו-``::marker``, חייבים
להיות זהים בשני העמודים. אם הם זהים, אין התנגשות שהסדר מכריע בה. לכן גם הסדר שהיה לפני ההעברה,
שבו הכללים המשותפים ישבו באמצע ``repo-browser.css``, נותן את אותה תצוגה. ההשוואה הישירה מול
הקוד שלפני ההעברה נעשתה פעם אחת, ב-PR של ההעברה.

**ומה זה שומר מעכשיו.** כלל ב-``repo-browser.css`` שמתנגש בכלל משותף באותה ספציפיות תלוי בסדר
הקבצים בלבד: בסדר הרגיל הוא מת, ואם הסדר יתהפך הוא ישנה את התצוגה. הבדיקה נופלת עליו עם האלמנט,
המאפיין ושני הערכים.

**למה דפדפן ועמוד אמיתי (T1).** זו שאלה של מפל CSS, ורק דפדפן מחשב מפל. השרת הוא הוובאפ האמיתי
(``admin_live_server``) עם התבניות, ה-CSS, ה-JS והבאנדל מהדיסק. רק ה-API של הריפו מזויף.

מדולג כשאין Chromium.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _browser_harness import poll

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

CSS_DIR = Path(__file__).resolve().parent.parent / "webapp" / "static" / "css"
SHARED_CSS = "/static/css/markdown-preview.css"
REPO_CSS = "/static/css/repo-browser.css"

#: הריפו שהעמוד מרנדר כשאין לו ריפו אחר — ``DEFAULT_REPO_NAME`` ב-``webapp/routes/repo_browser.py``.
REPO = "CodeBot"
MD_PATH = "docs/style_probe.md"

#: כל ערכה שיש לה בורר משלה בכללים המשותפים או בגיליונות הגלובליים: ברירת המחדל, הכהות,
#: הבהירה עם הכללים הייעודיים לתרשימים, ניגודיות גבוהה (שאין לה בלוק ב-``base.html``),
#: מותאמת, ומשותפת (``shared:``).
THEMES = ("classic", "ocean", "rose-pine-dawn", "dark", "dim", "nebula", "high-contrast", "custom", "shared:probe")

#: מסמך שמפעיל כל סוג אלמנט שהכללים המשותפים צובעים: כותרות, רשימות ומשימות, ציטוט, טבלה, קוד עם
#: הדגשת תחביר בכמה שפות ובעברית, הערות מכל הסוגים, פרטים, תמונה, נוסחאות, ושני סוגי תרשים.
MARKDOWN = r"""# כותרת ראשית — תצוגת Markdown

[[toc]]

פסקה עם **מודגש**, *נטוי*, ~~מחוק~~, `קוד בשורה`, ==מסומן==, קישור [לאתר](https://example.com) ואמוג'י :smile:.
פסקה שנייה עם הערת שוליים[^1] וקישור אוטומטי https://example.org.

## כותרת שנייה <a id="explicit-anchor"></a>

### כותרת שלישית

#### כותרת רביעית

##### כותרת חמישית

###### כותרת שישית

> ציטוט עם **הדגשה**.
>
> > ציטוט מקונן.

- פריט ראשון
- פריט שני
  - פריט מקונן

1. ראשון
2. שני

- [x] משימה שבוצעה
- [ ] משימה פתוחה

| עמודה | ערך | הערה |
|:---|:---:|---:|
| א | 1 | `קוד` |
| ב | 2 | **מודגש** |
| ג | 3 | [קישור](https://example.com) |

---

```python
import os

def greet(name: str, times: int = 2) -> str:
    '''Docstring.'''
    # a comment
    return f"hello {name}" * times + str(42) + os.sep

class Foo(Bar):
    @property
    def size(self):
        return len(self.items)
```

```javascript
const re = /ab+c/i;
let x = true, y = null;
class A extends B { method(arg) { return this.value + `t${arg}`; } }
```

```css
#id .class > a:hover[href^="x"]::before { color: #ff0000; margin: 0 1px !important; }
```

```diff
- removed line
+ added line
```

```yaml
key: value
list:
  - item
```

```
קוד בלי שפה
- שורה עם מקף
```

```text
שורה בעברית בתוך בלוק קוד
```

::: note
הערה עם **הדגשה** ו-`קוד`.
:::

::: warning כותרת מותאמת
אזהרה.
:::

::: tip
טיפ.
:::

::: danger
סכנה.
:::

::: details פרטים נוספים
תוכן מוסתר.
:::

![תמונה](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==)

נוסחה בשורה $E=mc^2$ ונוסחה בבלוק:

$$\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$$

```mermaid
flowchart TD
  A[התחלה] --> B{החלטה}
  B -->|כן| C[סוף]
  subgraph קבוצה
    E[צומת]
  end
```

```mermaid
sequenceDiagram
  participant A as Alice
  participant B as Bob
  A->>B: הודעה
  Note right of B: הערה
  loop כל דקה
    B-->>A: תשובה
  end
```

[^1]: הערת השוליים.
"""

READY_JS = """() => {
  const c = document.getElementById('markdown-preview-content');
  if (!c) return {ok: false, why: 'אין תצוגה'};
  const state = {
    pendingDiagrams: c.querySelectorAll('code.language-mermaid').length,
    diagrams: c.querySelectorAll('.mermaid-diagram svg').length,
    math: c.querySelectorAll('.katex').length,
    highlighted: c.querySelectorAll('pre code.hljs').length,
    admonitions: c.querySelectorAll('.admonition').length,
  };
  state.ok = state.pendingDiagrams === 0 && state.diagrams === 2 && state.math >= 2
    && state.highlighted >= 5 && state.admonitions >= 4;
  return state;
}"""

#: מחיל ערכה כמו שהסקריפט שבראש ``base.html`` מחיל אותה, ומחכה שהיא תסיים לחול.
#: ``dark-mode.css`` מגדיר ``transition`` על ``[data-theme="..."] *``, ולכן מיד אחרי ההחלפה
#: הצבעים עוד באמצע מעבר. קריאת ``offsetHeight`` מכריחה את הדפדפן לחשב את הסגנון עכשיו, כך
#: שהמעברים כבר קיימים כש-``getAnimations`` נקרא, וההמתנה היא לכולם.
APPLY_THEME_JS = """async (theme) => {
  const html = document.documentElement;
  html.setAttribute('data-theme', theme);
  if (theme === 'custom' || theme.startsWith('shared:')) html.setAttribute('data-theme-type', 'custom');
  else html.removeAttribute('data-theme-type');
  void document.body.offsetHeight;
  await Promise.all(document.getAnimations().map((a) => a.finished.catch(() => null)));
}"""

#: כל המאפיינים המחושבים של כל אלמנט בתצוגה, לפי מסלול ב-DOM. בלי ``paths`` חוזרת טביעה
#: לכל אלמנט, ועם ``paths`` — הערכים המלאים של המסלולים האלה, כדי שכישלון יראה מה השתנה.
#: המזהים של Mermaid נגזרים מ-``Date.now()`` (``live-preview.js``) ומופיעים בערכים כמו
#: ``marker-end``, ולכן הם מנורמלים לפני ההשוואה. הטביעה נבנית מהמאפיינים ממוינים לפי שם:
#: משתני CSS נמנים לפי סדר ההצהרה עליהם, וזה בדיוק מה שמשתנה בין שני העמודים, גם כשהערכים זהים.
COLLECT_JS = """(paths) => {
  const norm = (v) => v.replace(/mmd_live_\\d+_/g, 'mmd_live_N_');
  const styleOf = (cs) => {
    const out = {};
    for (let i = 0; i < cs.length; i++) out[cs[i]] = norm(cs.getPropertyValue(cs[i]));
    return out;
  };
  const fnv = (text) => {
    let h = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return h.toString(16);
  };
  const entries = {};
  const visit = (el, path) => {
    const cs = getComputedStyle(el);
    entries[path] = styleOf(cs);
    for (const pseudo of ['::before', '::after']) {
      const ps = getComputedStyle(el, pseudo);
      if (ps.content !== 'none' && ps.content !== 'normal') entries[path + pseudo] = styleOf(ps);
    }
    if (cs.display === 'list-item') entries[path + '::marker'] = styleOf(getComputedStyle(el, '::marker'));
    const seen = {};
    for (const child of el.children) {
      const tag = child.tagName.toLowerCase();
      seen[tag] = (seen[tag] || 0) + 1;
      visit(child, path + '>' + tag + '[' + seen[tag] + ']');
    }
  };
  visit(document.getElementById('markdown-preview-container'), 'container');
  if (paths) {
    const picked = {};
    for (const p of paths) picked[p] = entries[p] || null;
    return picked;
  }
  const prints = {};
  for (const [p, style] of Object.entries(entries)) {
    prints[p] = fnv(Object.keys(style).sort().map((k) => k + ':' + style[k]).join(';'));
  }
  return prints;
}"""

#: מה נטען בפועל משני הקבצים בעמוד: מספר הכללים בכל אחד, והבורר של הכלל הראשון.
SHEETS_JS = """() => Array.from(document.styleSheets)
  .filter((s) => s.href && (s.href.includes('/css/repo-browser.css') || s.href.includes('/css/markdown-preview.css')))
  .map((s) => ({href: new URL(s.href).pathname, rules: s.cssRules.length,
                first: s.cssRules.length ? s.cssRules[0].selectorText || null : null}))"""


def _api(route, *, swapped: bool) -> None:
    """ה-API של הריפו מזויף; בעמוד ההפוך גם שני קובצי ה-CSS. כל השאר עובר לשרת האמיתי."""
    url = urlsplit(route.request.url)
    if url.hostname != "127.0.0.1":
        route.abort()
        return
    path = unquote(url.path)
    if swapped and path == REPO_CSS:
        shared = (CSS_DIR / "markdown-preview.css").read_text(encoding="utf-8")
        own = (CSS_DIR / "repo-browser.css").read_text(encoding="utf-8")
        route.fulfill(status=200, content_type="text/css", body=shared + "\n" + own)
        return
    if swapped and path == SHARED_CSS:
        route.fulfill(status=200, content_type="text/css", body="")
        return
    body = None
    if path == f"/repo/api/file/{MD_PATH}":
        body = {"content": MARKDOWN, "language": "markdown", "path": MD_PATH}
    elif path == "/repo/api/tree":
        body = [{"name": MD_PATH.rsplit("/", 1)[-1], "path": MD_PATH, "type": "file"}]
    elif path == "/repo/api/repos":
        body = {"success": True, "repos": [{"repo_name": REPO}], "current": REPO, "current_source": "default"}
    elif path.startswith("/repo/api/"):
        body = {"success": True, "types": []}
    elif path.startswith("/api/sticky-notes/"):
        body = {"ok": True, "notes": []}
    if body is None:
        route.continue_()
    else:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def _open_preview(browser, server, *, swapped: bool):
    """העמוד בהקשר משלו: בלי אחסון משותף, אף עמוד אינו משפיע על הערכה שהשני נפתח בה."""
    context = browser.new_context(viewport={"width": 1400, "height": 1000}, locale="he-IL")
    context.add_cookies([{
        "name": "session", "value": server.session_cookie,
        "domain": "127.0.0.1", "path": "/",
    }])
    context.add_init_script(
        "try{localStorage.setItem('welcomeModalSeen','1');localStorage.setItem('onboarding_completed','1');"
        "localStorage.setItem('repo-browser-markdown-preview','true');}catch(e){}"
    )
    page = context.new_page()
    page.route("**/*", lambda route: _api(route, swapped=swapped))
    page.goto(f"{server.base_url}/repo/#file={MD_PATH}", wait_until="load")
    poll(page, READY_JS, "התצוגה רונדרה במלואה, כולל תרשימים, נוסחאות והדגשת קוד")
    # תוכן של ``<details>`` סגור אינו מצויר, ו-Chromium מחשב לו סגנון רק לפי דרישה. נמדד כאן:
    # אחרי כמה החלפות ערכה הוא החזיר לו צבע גבול של ערכה קודמת, בעמוד אחד מהשניים. פתוח,
    # התוכן מצויר כמו כל השאר, והסגנון שנמדד הוא זה שהמשתמש רואה כשהוא פותח אותו.
    page.evaluate(
        "() => document.querySelectorAll('#markdown-preview-content details').forEach((d) => { d.open = true; })"
    )
    return page


@pytest.fixture(scope="module")
def measured(admin_live_server, chromium_executable):
    """שני העמודים, הטביעות בכל ערכה, והערכים המלאים של כל אלמנט שהטביעה שלו שונה."""
    with sync_playwright() as pw:
        try:
            browser = (
                pw.chromium.launch(executable_path=chromium_executable)
                if chromium_executable
                else pw.chromium.launch()
            )
        except Exception as exc:  # noqa: BLE001 — כל כשל השקה פירושו אין דפדפן
            pytest.skip(f"אין Chromium זמין: {exc}")
        try:
            served = _open_preview(browser, admin_live_server, swapped=False)
            swapped = _open_preview(browser, admin_live_server, swapped=True)
            result = {
                "ready": served.evaluate(READY_JS),
                "sheets": {"served": served.evaluate(SHEETS_JS), "swapped": swapped.evaluate(SHEETS_JS)},
                "prints": {},
                "differences": [],
            }
            for theme in THEMES:
                for page in (served, swapped):
                    page.evaluate(APPLY_THEME_JS, theme)
                a, b = served.evaluate(COLLECT_JS, None), swapped.evaluate(COLLECT_JS, None)
                result["prints"][theme] = (a, b)
                changed = sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))
                if changed:
                    full_a = served.evaluate(COLLECT_JS, changed[:20])
                    full_b = swapped.evaluate(COLLECT_JS, changed[:20])
                    for path in changed[:20]:
                        style_a, style_b = full_a.get(path) or {}, full_b.get(path) or {}
                        for prop in sorted(set(style_a) | set(style_b)):
                            if style_a.get(prop) != style_b.get(prop):
                                result["differences"].append((theme, path, prop, style_a.get(prop), style_b.get(prop)))
                    result["differences"].append((theme, f"{len(changed)} אלמנטים שונים", "", "", ""))
            return result
        finally:
            browser.close()


def test_the_preview_rendered_every_kind_of_element(measured):
    """בלי תרשימים, נוסחאות, קוד מודגש והערות, ההשוואה הייתה עוברת על מסמך חסר."""
    assert measured["ready"]["ok"], measured["ready"]


def test_the_swapped_page_really_loads_the_shared_rules_first(measured):
    """שהעמוד ההפוך באמת הפוך: הקובץ המשותף ריק, ו-``repo-browser.css`` נפתח בכללים המשותפים.

    בלעדי זה, ראוט שלא תפס את הבקשה (למשל אחרי שינוי שם) היה משאיר שני עמודים זהים, וההשוואה
    הייתה עוברת בלי לבדוק דבר.
    """
    served = {s["href"]: s for s in measured["sheets"]["served"]}
    swapped = {s["href"]: s for s in measured["sheets"]["swapped"]}
    assert served[SHARED_CSS]["rules"] > 0 and served[SHARED_CSS]["first"] == ".markdown-preview-container", served
    assert served[REPO_CSS]["first"] != ".markdown-preview-container", served
    assert swapped[SHARED_CSS]["rules"] == 0, swapped
    assert swapped[REPO_CSS]["first"] == ".markdown-preview-container", swapped
    assert swapped[REPO_CSS]["rules"] == served[REPO_CSS]["rules"] + served[SHARED_CSS]["rules"], swapped


def test_the_measurement_sees_the_themes(measured):
    """הטביעות משתנות בין ערכה לערכה. אילו לא, החלפת הערכה לא הייתה מגיעה לתצוגה, והשוויון היה ריק."""
    served = {theme: prints[0] for theme, prints in measured["prints"].items()}
    assert served["classic"]["container"] != served["dark"]["container"]
    assert served["classic"]["container"] != served["high-contrast"]["container"]


@pytest.mark.parametrize("theme", THEMES)
def test_the_preview_looks_the_same_whichever_file_loads_first(measured, theme):
    served, swapped = measured["prints"][theme]
    assert set(served) == set(swapped), "מבנה התצוגה שונה בין שני העמודים"
    differences = [d for d in measured["differences"] if d[0] == theme]
    assert not differences, "\n".join(
        f"{path} {prop}: בסדר הרגיל {a!r}, כשהמשותף נטען קודם {b!r}" for _t, path, prop, a, b in differences
    )

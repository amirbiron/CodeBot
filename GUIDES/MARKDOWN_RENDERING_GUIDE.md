# מדריך לרינדור Markdown ל־HTML (לשימוש חוזר בפרויקטים אחרים)

> מדריך מעשי שמתעד את הדרך שבה הוובאפ של CodeBot ממיר תוכן Markdown ל־HTML מעוצב ובטוח. אפשר להעתיק את החלקים הרלוונטיים לפרויקטים אחרים בלי תלות ב־Flask/MongoDB.

## על מה זה מבוסס בפרויקט?

בפרויקט יש **שלושה** מסלולי רינדור שונים – חשוב להכיר את כולם כדי לבחור את הנכון לפרויקט החדש:

1. **רינדור צד שרת לייצוא** – `services/styled_export_service.py::markdown_to_html`. מבוסס על Python‑Markdown + bleach + Pygments. משמש לייצוא קובץ HTML מעוצב להורדה.
2. **רינדור צד שרת לתצוגה מקדימה חיה** – `webapp/app.py::_render_markdown_preview`. גם הוא Python‑Markdown, אבל עם סניטציה דרך BeautifulSoup ופרופילים גמישים.
3. **רינדור צד לקוח של תצוגת ה־MD בוובאפ** – `webapp/templates/md_preview.html` + `webapp/static_build/md-preview-entry.js`. כאן הרינדור רץ **בדפדפן** עם `markdown-it` ותוספים (כולל `markdown-it-task-lists` עבור ה־`[ ]` / `[x]`). זה גם מה שמאפשר לסמן ✓ אינטראקטיבית.

המדריך הזה מתעד את **המסלול הראשון** ואת **המסלול השלישי** – יחד הם מכסים גם ייצוא סטטי וגם תצוגה אינטראקטיבית.

---

## תלויות

```bash
pip install markdown bleach pygments
```

חבילות:
- `markdown` – מנוע ההמרה (Python‑Markdown).
- `bleach` – סניטציה של HTML, מניעת XSS.
- `pygments` – הדגשת תחביר לבלוקי קוד.

---

## ארכיטקטורה במבט על

```
Markdown text
   │
   ▼
preprocess_markdown        # ::: note/warning/... → <div class="alert ...">
   │
   ▼
markdown.Markdown.convert  # fenced_code, tables, nl2br, toc, codehilite, attr_list
   │
   ▼
regex strip <script>/<style>
   │
   ▼
bleach.clean (allowlist tags + attrs + protocols)
   │
   ▼
add rel="noopener noreferrer" to target="_blank"
   │
   ▼
(אופציונלי) TOC נקי
   │
   ▼
HTML מוכן + (אופציונלי) Pygments CSS להזרקה
```

---

## הקוד המינימלי (העתק‑הדבק)

קובץ אחד עצמאי – `markdown_renderer.py`:

```python
"""
Markdown → HTML renderer with sanitization and syntax highlighting.
"""
from __future__ import annotations
import re
from typing import Tuple

import bleach
import markdown
from pygments.formatters import HtmlFormatter
from pygments.styles import get_style_by_name


# ---------- Allowlist לסניטציה ----------

ALLOWED_TAGS = list(bleach.sanitizer.ALLOWED_TAGS) + [
    "div", "span", "p", "br",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "code", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "blockquote", "ul", "ol", "li", "hr", "a",
    "b", "i", "strong", "em", "del", "ins",
    "sup", "sub", "mark", "nav",
]

ALLOWED_ATTRS = {
    "*": ["class", "id"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "th": ["colspan", "rowspan"],
    "td": ["colspan", "rowspan"],
    "code": ["class"],     # codehilite
    "span": ["class"],     # syntax tokens
    "pre":  ["class"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


# ---------- Preprocess: ::: note / warning / ... ----------

_ADMONITION_RE = re.compile(
    r"^:::\s*(note|info|warning|important|danger|success|tip)\b[^\n]*\n(.*?)\n:::$",
    flags=re.DOTALL | re.MULTILINE,
)

_TYPE_MAP = {
    "note": "info", "info": "info", "tip": "success", "success": "success",
    "warning": "warning", "important": "warning", "danger": "danger",
}


def preprocess_markdown(text: str) -> str:
    """ממיר בלוקי `::: type ... :::` ל־<div class='alert alert-*'>."""
    if not text:
        return ""

    def _replace(match: re.Match) -> str:
        kind = match.group(1).lower()
        body = match.group(2).strip()
        css_class = _TYPE_MAP.get(kind, "info")
        inner = markdown.markdown(body, extensions=["nl2br"])
        clean_inner = bleach.clean(
            inner,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRS,
            protocols=ALLOWED_PROTOCOLS,
            strip=True,
        )
        return f'<div class="alert alert-{css_class}">{clean_inner}</div>'

    return _ADMONITION_RE.sub(_replace, text)


# ---------- Main API ----------

def markdown_to_html(text: str, include_toc: bool = False) -> Tuple[str, str]:
    """
    ממיר Markdown ל־HTML נקי.
    מחזיר (html, toc_html). אם include_toc=False ה־TOC ריק.
    """
    if not text:
        return "", ""

    processed = preprocess_markdown(text)

    md = markdown.Markdown(
        extensions=[
            "fenced_code",   # ```code blocks```
            "tables",        # GFM tables
            "nl2br",         # שורה חדשה → <br>
            "toc",           # תוכן עניינים
            "codehilite",    # הדגשת קוד עם Pygments
            "attr_list",     # {: .class #id}
        ],
        extension_configs={
            "codehilite": {
                "css_class": "highlight",
                "linenums": False,
                "guess_lang": True,
            },
            "toc": {
                "title": "תוכן עניינים",
                "toc_depth": 3,
            },
        },
    )

    raw = md.convert(processed)

    # נפילת ביטחון: מסיר script/style גם אם נשתחלו דרך allow‑list של bleach
    raw = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )

    clean = bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )

    clean = _force_noopener(clean)

    toc_html = ""
    if include_toc and getattr(md, "toc", ""):
        toc_html = bleach.clean(
            md.toc,
            tags=["div", "nav", "ul", "li", "a"],
            attributes={"a": ["href", "title"], "*": ["class", "id"]},
            protocols=["http", "https", "#"],  # # = anchors פנימיים
            strip=True,
        )

    return clean, toc_html


# ---------- אבטחה: rel="noopener noreferrer" על target="_blank" ----------

def _force_noopener(html: str) -> str:
    def _fix(m: re.Match) -> str:
        tag = m.group(0)
        if re.search(r'\srel\s*=\s*(["\'])', tag):
            # החלפת rel קיים – חשוב להתאים את אותו סוג של מרכאות פתיחה/סגירה
            return re.sub(
                r'\srel\s*=\s*(["\']).*?\1',
                ' rel="noopener noreferrer"',
                tag,
                count=1,
                flags=re.IGNORECASE,
            )
        return tag.replace('target="_blank"', 'target="_blank" rel="noopener noreferrer"')

    return re.sub(r'<a\s[^>]*target="_blank"[^>]*>', _fix, html)


# ---------- Pygments CSS ----------

def pygments_css(style_name: str = "monokai", css_class: str = ".highlight") -> str:
    """מחזיר את ה־CSS של ערכת הצבעים שצריך להזריק לדף."""
    try:
        style = get_style_by_name(style_name)
    except Exception:
        style = get_style_by_name("default")
    formatter = HtmlFormatter(style=style, cssclass=css_class.lstrip("."))
    return formatter.get_style_defs(css_class)
```

שימוש:

```python
from markdown_renderer import markdown_to_html, pygments_css

html, toc = markdown_to_html(md_text, include_toc=True)
css = pygments_css("monokai")  # או "github-dark", "default", "friendly" וכו'

page = f"""<!doctype html>
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body>
  <aside>{toc}</aside>
  <article>{html}</article>
</body></html>"""
```

---

## הסברים – למה כל חלק קיים

### 1. Preprocessing של אדמוניציות (`:::`)
Python‑Markdown לא מכיר ב־`::: warning ... :::` כברירת מחדל. הוספנו preprocess קצר שמייצר `<div class="alert alert-warning">…</div>` ושומר על Markdown פנימי (כותרת, רשימה, **bold**). שים לב שאת ה־HTML הפנימי כבר מנקים מיד עם bleach – זה מחסום הגנה כפול.

> חלופה: אפשר להשתמש ב־extension המובנה `admonition` במקום ה־preprocess. עשינו preprocess כי תחביר `:::` יותר נפוץ במסמכים שלנו.

### 2. ה־extensions החיוניים
- `fenced_code` – בלוקי \`\`\`lang.
- `tables` – טבלאות GFM.
- `nl2br` – התנהגות "שורה חדשה = `<br>`" (סגנון GitHub/Telegram).
- `toc` – חושף `md.toc` עם תוכן עניינים מקושר ל־anchors.
- `codehilite` – הופך בלוקי קוד ל־HTML עם classים של Pygments. הזריקה של ה־CSS היא נפרדת (ראה `pygments_css`).
- `attr_list` – מאפשר `{: .my-class #my-id}` על אלמנטים.

### 3. שכבת הסניטציה
- **regex לפני bleach**: bleach לפעמים משאיר את התוכן של `<script>` ככלי טקסט. הסרה ידנית של בלוקים שלמים מבטלת את הסיכון לחלוטין.
- **bleach.clean עם `strip=True`**: תגיות שלא ב־allowlist מוסרות אבל הטקסט נשאר. עדיף על escape כי לא מקבלים `&lt;...&gt;` כמחרוזת.
- **`ALLOWED_PROTOCOLS`** – חוסם `javascript:` ו־`data:` בקישורים ובתמונות.
- **`rel="noopener noreferrer"`** – על כל `target="_blank"`, להגנה מפני tabnabbing.

### 4. Pygments
ה־`codehilite` עוטף קוד ב־`<div class="highlight"><pre><code class="language-x">…</code></pre></div>` עם classים פנימיים (`.k`, `.s`, `.c1` וכו'). ה־CSS עצמו לא מוזרק אוטומטית – צריך לקרוא ל־`pygments_css(...)` ולהדביק אותו ב־`<style>` בעמוד.

ערכי `style_name` שימושיים:
- כהים: `monokai`, `dracula`, `nord`, `github-dark`, `one-dark`, `gruvbox-dark`.
- בהירים: `default`, `friendly`, `github-dark` (עובד גם ל־light), `solarized-light`, `gruvbox-light`.

---

## גרסה מינימלית בלי `bleach` (לא מומלץ)

אם הפרויקט החדש שלך כבר עושה סניטציה אחרת (למשל ב־frontend עם DOMPurify), אפשר להחזיר את ה־HTML הגולמי ישירות מ־`md.convert(...)`. **אבל** – אז חובה לוודא שאף משתמש לא יכול להזין HTML גולמי בתוך ה־Markdown, כי Python‑Markdown מאפשר זאת כברירת מחדל. ב־Live Preview של הוובאפ אנחנו אפילו מסירים את `html_block` ו־`inlinehtml` מהמעבדים:

```python
md = markdown.Markdown(extensions=[...])
try: md.preprocessors.deregister("html_block")
except Exception: pass
try: md.inlinePatterns.deregister("html")
except Exception:
    try: md.inlinePatterns.deregister("inlinehtml")
    except Exception: pass
```

זו דרך טובה לוודא ש"רק Markdown" יוצא משם, בלי טריקים של HTML מוטבע.

---

## CSS בסיסי לעיצוב המסמך

ה־HTML שיוצא מתאים לכל עיצוב, אבל יש כמה classים שכדאי לסטייל:

- `.highlight` – בלוק קוד (מקבל את צבעי Pygments).
- `.alert.alert-info` / `.alert-warning` / `.alert-danger` / `.alert-success` – אדמוניציות.
- `.toc` – ה־TOC שנוצר על־ידי extension של `toc`.
- כותרות `h1..h6` עם `id` (אוטומטי מ־`toc`) – מאפשר deep‑link.

דוגמת CSS מינימלית:

```css
.highlight { padding: 12px; border-radius: 8px; overflow-x: auto; }
.alert { border-left: 4px solid; padding: 12px 16px; margin: 12px 0; border-radius: 6px; }
.alert-info    { border-color: #3498db; background: rgba(52,152,219,.08); }
.alert-warning { border-color: #f39c12; background: rgba(243,156,18,.08); }
.alert-danger  { border-color: #e74c3c; background: rgba(231,76,60,.08); }
.alert-success { border-color: #2ecc71; background: rgba(46,204,113,.08); }
table { border-collapse: collapse; }
th, td { border: 1px solid #ccc; padding: 6px 10px; }
```

---

## טיפים ופיטפולים

- **`nl2br`** משנה את ההתנהגות ל"שורה = שבירה". זה נחמד לתיעוד אבל יכול לשבור פסקאות מסוימות. הסר אותו אם אתה רוצה התנהגות Markdown סטנדרטית.
- **`guess_lang`** של `codehilite` לפעמים שוגה. אם הקלט תמיד מציין שפה ב־```, עדיף `"guess_lang": False`.
- **TOC לרשימה ארוכה**: `toc_depth: 3` בלבד – אחרת מקבלים TOC ענק.
- **Anchorים בעברית**: ה־`toc` בורא slug באנגלית, ולכן עברית יכולה להיחתך. אפשר להשתמש ב־`slugify` משלך דרך `extension_configs={"toc": {"slugify": my_slugify}}`.
- **תמונות חיצוניות**: הסניטציה מאפשרת `http/https` בלבד. אם אתה רוצה להציג רק תמונות שאתה אחראי עליהן, אפשר להוסיף בדיקה ידנית של ה־`src` אחרי ה־bleach.
- **גודל קלט**: אל תרנדר Markdown ענק בלי הגבלה. שווה להגדיר `MAX_MARKDOWN_LEN` בקלט (בפרויקט שלנו יש גם הגבלות לתמונות מוטבעות, ראה `MARKDOWN_IMAGE_LIMIT` ו־`MARKDOWN_IMAGE_MAX_BYTES`).
- **בדיקת זליגות XSS**: זרוק את הסטים הקלאסיים – `<script>`, `javascript:href`, `<img onerror>`, `<a target=_blank>` – ובדוק שהתוצאה נקייה.

---

## רינדור בצד לקוח עם markdown-it (תצוגת ה־MD החיה)

המסלול הזה הוא מה שמשמש את **תצוגת קבצי ה־Markdown בוובאפ** (`webapp/templates/md_preview.html`). הוא מאפשר תכונות שקשה להשיג בצד שרת:

- **רשימות משימות (`- [ ]` / `- [x]`)** עם סימון אינטראקטיבי בעין הקורא.
- **שמירת מצב הסימון ב־`localStorage`** לכל מסמך בנפרד.
- KaTeX, Mermaid, highlight.js – הכל בדפדפן ללא שרת.

### הסט המלא של החבילות

קובץ ה־entry של ה־bundle: `webapp/static_build/md-preview-entry.js`.

```js
import MarkdownIt from 'markdown-it';
import { full as markdownItEmoji } from 'markdown-it-emoji';
import markdownItTaskLists from 'markdown-it-task-lists';   // ← הצ'קבוקס
import markdownItAnchor from 'markdown-it-anchor';
import markdownItFootnote from 'markdown-it-footnote';
import markdownItTocDoneRight from 'markdown-it-toc-done-right';
import markdownItContainer from 'markdown-it-container';
import markdownItAdmonition from 'markdown-it-admonition';
import hljs from 'highlight.js/lib/common';
import renderMathInElement from 'katex/contrib/auto-render';
import mermaid from 'mermaid';

if (typeof window !== 'undefined') {
  window.markdownit = (opts) => new MarkdownIt(opts);
  window.markdownitTaskLists = markdownItTaskLists;
  window.markdownitEmoji = markdownItEmoji;
  window.markdownitAnchor = markdownItAnchor;
  window.markdownitFootnote = markdownItFootnote;
  window.markdownitTocDoneRight = markdownItTocDoneRight;
  window.markdownitContainer = markdownItContainer;
  window.markdownitAdmonition = markdownItAdmonition;
  window.hljs = hljs;
  window.renderMathInElement = renderMathInElement;
  window.mermaid = mermaid;
}
```

ב־CDN (אם לא משתמשים ב־bundler משלך):

```html
<script src="https://cdn.jsdelivr.net/npm/markdown-it/dist/markdown-it.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-task-lists/dist/markdown-it-task-lists.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-anchor/dist/markdownItAnchor.umd.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-footnote/dist/markdown-it-footnote.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-emoji/dist/markdown-it-emoji.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-container/dist/markdown-it-container.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js/lib/common.js"></script>
```

### הפעלת התוסף של רשימות משימות

ב־`md_preview.html`:

```js
const md = window.markdownit({
  html: false,        // לא מאפשרים HTML גולמי בקלט
  linkify: true,
  breaks: true,       // שורה חדשה = <br> (כמו GitHub/Telegram)
  typographer: false,
});

if (window.markdownitTaskLists) {
  md.use(window.markdownitTaskLists, {
    label: true,      // עוטף את הטקסט ב־<label>, כך שלחיצה על הטקסט מסמנת
    enabled: true,    // ה־checkbox פעיל ולא disabled (זה מה שמאפשר לסמן ✓)
  });
}
```

הפלט שמתקבל ל־`- [ ] foo` הוא:

```html
<ul class="contains-task-list">
  <li class="task-list-item">
    <input type="checkbox" disabled="" class="task-list-item-checkbox">
    <label> foo</label>
  </li>
</ul>
```

> שים לב: גם עם `enabled: true` יש דפדפנים שמשאירים את ה־`disabled` בגלל ה־HTML שהפלאגין מייצר. הקוד של הוובאפ מטפל בזה דרך הוספת מאזין `change` ידני (ראה למטה) – ובכל מקרה, ב־`md_preview.html` יש גם CSS שמסמן ויזואלית ש־checkbox פתוח/סגור גם כשהוא disabled.

### שמירת מצב הסימון ב־`localStorage`

זה החלק המעניין שלא מגיע מהפלאגין – הוא לוגיקה משלנו (`md_preview.html`, שורות 2157–2165 ו־3265–3280):

```js
const FILE_ID = "{{ file.id }}";
const STORAGE_KEY = `md_tasks_state:${FILE_ID}`;

function loadTaskState(){
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); }
  catch(_) { return {}; }
}
function saveTaskState(state){
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state || {})); }
  catch(_) {}
}

const taskState = loadTaskState();

// אחרי ש־md.render(...) הוצא ל־#md-content:
const container = document.getElementById('md-content');
const boxes = container.querySelectorAll('input[type="checkbox"]');
let idx = 0;
boxes.forEach(cb => {
  cb.classList.add('md-task-checkbox');
  const key = 'i' + (idx++);                       // אינדקס סדרתי לכל צ'קבוקס במסמך
  if (Object.prototype.hasOwnProperty.call(taskState, key)) {
    cb.checked = !!taskState[key];                 // שחזור מצב מהאחסון
  }
  cb.addEventListener('change', () => {
    taskState[key] = cb.checked;
    saveTaskState(taskState);                      // שמירת מצב על כל שינוי
  });
});
```

נקודות חשובות:
- **המפתח כולל `file.id`** – לכל מסמך אחסון נפרד, כך ששינוי בקובץ אחד לא משפיע על אחר.
- **המפתח של כל תיבה הוא אינדקס סדרתי (`i0`, `i1`, …)**. הצד הטוב: פשוט. הצד הרגיש: אם מוסיפים פריט באמצע המסמך, האינדקסים זזים והסימונים יזיזו תיקיה. בפרויקט גדול שווה לחשוב על מפתח יציב (hash של טקסט הפריט).
- **המידע לא חוזר לשרת** – לוקאלי לדפדפן. אם נדרש סנכרון בין מכשירים, צריך להוסיף API.

### עיצוב

```css
input.md-task-checkbox {
  margin-inline-end: .5rem;
  transform: scale(1.1);
}
.task-list-item { list-style: none; }
ul.contains-task-list,
ul:has(> li.task-list-item) { padding-inline-start: 1.2em; }
```

### דוגמה עצמאית (HTML אחד, מוכן להעתקה)

```html
<!doctype html>
<html><head>
<meta charset="utf-8">
<title>MD Preview</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }
  input.md-task-checkbox { margin-inline-end: .5rem; transform: scale(1.1); }
  .task-list-item { list-style: none; }
  ul.contains-task-list { padding-inline-start: 1.2em; }
  pre { background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }
  code { background: #f6f8fa; padding: 2px 4px; border-radius: 4px; }
</style>
</head><body>
<article id="md-content"></article>

<script src="https://cdn.jsdelivr.net/npm/markdown-it/dist/markdown-it.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/markdown-it-task-lists/dist/markdown-it-task-lists.min.js"></script>
<script>
  const FILE_ID = "doc-123";
  const STORAGE_KEY = `md_tasks_state:${FILE_ID}`;
  const loadState = () => { try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch(_) { return {}; } };
  const saveState = (s) => { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s || {})); } catch(_) {} };

  const md = window.markdownit({ html: false, linkify: true, breaks: true })
    .use(window.markdownitTaskLists, { label: true, enabled: true });

  const source = `# רשימת משימות
- [ ] לכתוב מדריך
- [x] לבדוק את הקוד בפרויקט
- [ ] לדחוף לפרויקט החדש
`;

  const container = document.getElementById('md-content');
  container.innerHTML = md.render(source);

  const state = loadState();
  let idx = 0;
  container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
    cb.classList.add('md-task-checkbox');
    const key = 'i' + (idx++);
    if (Object.prototype.hasOwnProperty.call(state, key)) cb.checked = !!state[key];
    cb.addEventListener('change', () => { state[key] = cb.checked; saveState(state); });
  });
</script>
</body></html>
```

### אבטחה בצד לקוח

`markdown-it` מגיע עם הגנות סבירות כברירת מחדל:
- `html: false` – חוסם הזרקת `<script>`/`<iframe>` מתוך ה־Markdown.
- `linkify: true` – הופך URLs לקישורים בלי לאפשר `javascript:`.
- אם אתה כן זקוק להציג HTML גולמי – הוסף `DOMPurify.sanitize(md.render(src))` לפני `innerHTML`.

לעומת המסלול בצד שרת – כאן ה־XSS מסוכן יותר אם ה־MD בא ממשתמשים אחרים, כי הסניטציה היא בדפדפן של הקורא. **תמיד** השאר `html: false` אם הקלט לא נאמן.

---

## תקציר ההבדל בין שלושת המסלולים בפרויקט

| היבט | `services/styled_export_service.markdown_to_html` (Py, ייצוא) | `webapp/app.py::_render_markdown_preview` (Py, preview) | `md_preview.html` + `markdown-it` (JS, תצוגה) |
|---|---|---|---|
| מטרה | ייצוא HTML מעוצב להורדה | תצוגה מקדימה חיה בעורך | תצוגת קובץ MD בוובאפ |
| מקום ריצה | שרת (Python) | שרת (Python) | דפדפן (JavaScript) |
| מנוע | Python‑Markdown | Python‑Markdown | markdown-it |
| סניטציה | `bleach.clean` עם allowlist קשיח | `BeautifulSoup` עם פרופילים | `html: false` של markdown-it |
| Task lists `[ ]/[x]` | ❌ (אפשר להוסיף `pymdownx.tasklist`) | ❌ | ✅ עם `markdown-it-task-lists` |
| סימון ✓ אינטראקטיבי | ❌ סטטי | ❌ סטטי | ✅ + שמירה ב־localStorage |
| TOC | ✅ (`include_toc=True`) | ❌ | ✅ (`markdown-it-toc-done-right`) |
| הדגשת קוד | Pygments | Pygments | highlight.js (post‑process) |
| מתמטיקה / Mermaid | ❌ | ❌ | ✅ (KaTeX + Mermaid) |

**המלצה לבחירה לפרויקט החדש:**
- צריך לייצא HTML/PDF סטטי? → המסלול הראשון (Python).
- צריך תצוגה אינטראקטיבית של MD עם משימות לסימון? → המסלול השלישי (markdown-it בדפדפן).
- אפשר גם **לשלב**: רנדר בשרת עם Python‑Markdown לטעינה ראשונית מהירה, ואז להפעיל בדפדפן רק את חלק שמירת המצב של הצ'קבוקסים על ה־HTML שכבר הוחזר.

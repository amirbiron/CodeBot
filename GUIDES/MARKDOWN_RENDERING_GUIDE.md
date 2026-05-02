# מדריך לרינדור Markdown ל־HTML (לשימוש חוזר בפרויקטים אחרים)

> מדריך מעשי שמתעד את הדרך שבה הוובאפ של CodeBot ממיר תוכן Markdown ל־HTML מעוצב ובטוח. אפשר להעתיק את החלקים הרלוונטיים לפרויקטים אחרים בלי תלות ב־Flask/MongoDB.

## על מה זה מבוסס בפרויקט?

יש בפרויקט שני מסלולי רינדור עיקריים, ושניהם נשענים על אותו רעיון: **Python‑Markdown → סניטציה ב־bleach → הדגשת קוד עם Pygments**.

1. **רינדור לייצוא/תצוגה מלאה** – `services/styled_export_service.py`, הפונקציה `markdown_to_html` (ברירת המחדל המומלצת).
2. **רינדור ל־Live Preview קצר** – `webapp/app.py`, הפונקציה `_render_markdown_preview` (משתמשת ב־BeautifulSoup לסניטציה גמישה יותר).

מה שמופיע למטה הוא תמצית המסלול הראשון – הוא היציב, המוקשח והנקי ביותר להעברה לפרויקט אחר.

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

## תקציר ההבדל בין שני המסלולים בפרויקט

| היבט | `services/styled_export_service.markdown_to_html` | `webapp/app.py::_render_markdown_preview` |
|---|---|---|
| מטרה | ייצוא מסמך מלא, הורדת HTML מעוצב | תצוגה מקדימה חיה בעורך |
| סניטציה | `bleach.clean` עם allowlist קשיח | `BeautifulSoup` עם פרופילים (markdown/code/html) |
| HTML גולמי בקלט | מוסר על־ידי bleach | מוסר ע"י deregister של `html_block`/`inlinehtml` |
| TOC | נתמך (`include_toc=True`) | לא |
| Theming | ערכות נושא דינמיות + Pygments style ממופה | Pygments `friendly` קבוע |

לרינדור "רגיל" בפרויקט אחר – לך עם המסלול הראשון. הוא פשוט, מוקשח ועצמאי.

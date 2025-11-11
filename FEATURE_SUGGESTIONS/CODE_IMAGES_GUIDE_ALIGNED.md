# 📋 מדריך יישום – יצירת תמונות קוד לשיתוף (מיושר לקוד)

מסמך זה מיישר את מדריך היישום לפיצ'ר יצירת תמונות קוד מול הקוד הקיים בריפו. הוא מסמן בבירור מה כבר קיים, מה חסר, ומה הדרך הפשוטה והאמינה ביותר להתחיל (MVP), עם נקודות הרחבה אופציונליות.

## ✨ מטרה קצרה
פקודה `/image <filename>` שתייצר תמונת PNG נקייה וקריאה מהקוד, עם הדגשת תחביר, מספרי שורות ולוגו קטן.

- פתרון פשוט קודם: שימוש ב־Pygments ImageFormatter + Pillow
- הרחבות אופציונליות: WeasyPrint/Playwright לרינדור HTML מתקדם, תמות, Batch, Preview, ניטור

---

## 📌 מצב נוכחי מול הריפו
- קיימים: `Pillow`, `pygments`, וכן `cairosvg` (ב־`requirements/base.txt`).
- לא קיים עדיין: `services/image_generator.py`, פקודות `/image` `/preview` `/image_all`, וקובץ קונפיג `config/image_settings.yaml`.
- Rate limiter קיים כ־`RateLimiter(max_per_minute)` עם מתודה אסינכרונית `check_rate_limit(user_id)`.
- הקוד משתמש ב־HTML להודעות (ParseMode.HTML) במסלולי תצוגה אחרים – ניישר גם כאן.

הערה: זהו Design Doc שמצריך מימוש בקוד (קבצים חדשים + חיווט ב־`bot_handlers.py`).

---

## 🧱 ארכיטקטורה מוצעת (MVP תחילה)

```
/workspace/
├── bot_handlers.py            # הוספת פקודות /image /preview /image_all
├── services/
│   └── image_generator.py     # חדש – מחולל תמונות (Pygments ImageFormatter + PIL)
└── config/
    └── image_settings.yaml    # אופציונלי – קונפיג
```

זרימה בסיסית:
1) `/image file.py` → שליפת קוד מ־`db.get_latest_version(user_id, file_name)`
2) קביעה/ניחוש שפה → הדגשה + רינדור לתמונה (Pygments ImageFormatter)
3) הוספת לוגו בפינה (Pillow)
4) שליחה ל־Telegram, מחיקת קובץ זמני

ל‑MVP נשמיט callbacks לא ממומשים (כמו `regenerate_image_*`, `save_to_drive_*`) ונחזור להוסיף כשנממש.

---

## ⚙️ תלויות
- חובה (כבר קיימות):
  - Pillow, Pygments
- אופציונלי:
  - WeasyPrint / Playwright (לרינדור HTML מתקדם) – לא מותקנים כיום; להשאיר כאופציה עתידית
  - קיימת כבר `cairosvg` אם נרצה מסלול HTML→SVG→PNG בעתיד

---

## 🧩 חיווט ב־bot_handlers.py

רישום פקודות:
```python
# בתוך AdvancedBotHandlers.setup_advanced_handlers
self.application.add_handler(CommandHandler("image", self.image_command))
self.application.add_handler(CommandHandler("preview", self.preview_command))
self.application.add_handler(CommandHandler("image_all", self.image_all_command))
```

Rate limiting תואם למחלקה הקיימת:
```python
from rate_limiter import RateLimiter
image_rate_limiter = RateLimiter(max_per_minute=10)

# בתוך הפקודה האסינכרונית
if not await image_rate_limiter.check_rate_limit(user_id):
    await update.message.reply_text("⏱️ יותר מדי בקשות. אנא נסה שוב בעוד דקה.")
    return
```

טעינת קונפיג (נתיב נכון ביחס ל־`bot_handlers.py`):
```python
from pathlib import Path
import yaml

def load_image_config() -> dict:
    path = Path(__file__).parent / 'config' / 'image_settings.yaml'
    if path.exists():
        with open(path, 'r') as f:
            return yaml.safe_load(f).get('image_generation', {})
    return {}

IMAGE_CONFIG = load_image_config()
```

שליחת הודעות: להשתמש ב־HTML באופן עקבי (לברוח עם `html.escape`):
```python
from telegram.constants import ParseMode
import html

await update.message.reply_text(
    "🖼️ <b>יצירת תמונת קוד</b>\n\n"
    "שימוש: <code>/image &lt;file_name&gt; [options]</code>",
    parse_mode=ParseMode.HTML,
)
```

---

## 🖼️ `services/image_generator.py` – MVP פשוט ואמין

שימוש ב־Pygments ImageFormatter (מייצר תמונה ישירות מ־PIL), כולל מספרי שורות, עם תוספת לוגו קטנה.

```python
# services/image_generator.py
from __future__ import annotations
import io
from typing import Optional
from PIL import Image  # type: ignore
from pygments import highlight  # type: ignore
from pygments.lexers import get_lexer_by_name  # type: ignore
from pygments.formatters import ImageFormatter  # type: ignore

class CodeImageGenerator:
    def __init__(self, style: str = 'monokai') -> None:
        self.style = style

    def generate_image(
        self,
        code: str,
        language: str = 'text',
        font_name: str = 'DejaVu Sans Mono',
        font_size: int = 14,
        line_numbers: bool = True,
    ) -> bytes:
        if not isinstance(code, str) or not code:
            raise ValueError('Code cannot be empty')
        try:
            lexer = get_lexer_by_name(language or 'text')
        except Exception:
            lexer = get_lexer_by_name('text')

        formatter = ImageFormatter(
            style=self.style,
            font_name=font_name,
            font_size=font_size,
            line_numbers=line_numbers,
            line_number_bg=None,
            line_number_fg=None,
            image_format='PNG',
        )
        out = io.BytesIO()
        highlight(code, lexer, formatter, outfile=out)
        return out.getvalue()
```

הערות MVP:
- ImageFormatter מספק הדגשה וייצוא PNG ישיר. אפשר להוסיף לוגו בהמשך ע"י פתיחת ה־PNG עם Pillow והדבקת שכבה שקופה.
- תמות (dark/light/monokai וכו') נשלטות ע"י פרמטר `style`.

הוספת לוגו קטנה (אופציונלי):
```python
from PIL import Image

def add_logo(image_bytes: bytes, logo_img: Image.Image) -> bytes:
    base = Image.open(io.BytesIO(image_bytes)).convert('RGBA')
    logo = logo_img.convert('RGBA')
    lx, ly = 80, 20
    pad = 10
    logo = logo.resize((lx, ly))
    pos = (base.width - lx - pad, base.height - ly - pad)
    base.alpha_composite(logo, dest=pos)
    out = io.BytesIO()
    base.convert('RGB').save(out, format='PNG', optimize=True, compress_level=9)
    return out.getvalue()
```

---

## 🧪 תצוגה מקדימה ו־Batch (אחרי MVP)

- `/preview <file>`: חיתוך ל־N שורות (לפי קונפיג), רוחב קטן, ללא לוגו.
- `/image_all`: מעבר על `db.get_user_files(user_id, limit=...)` עם עדכוני סטטוס ביניים. לוגיקה אסינכרונית זהירה כדי לא להציף.

הערה: אל תוסיף כפתורי callback בדוק עד שקיים handler מתאים.

---

## 🛠️ קובץ קונפיג (אופציונלי)
`config/image_settings.yaml` – אם קיים, נטען ברירות מחדל; אחרת להשתמש ב־defaults בקוד.

```yaml
image_generation:
  default_style: monokai
  font_size: 14
  preview:
    enabled: true
    max_lines: 50
```

---

## 🧪 בדיקות מוצעות (לשלב המימוש)
- יחידה:
  - `CodeImageGenerator.generate_image` מחזיר bytes לא ריקים ומתחיל ב־PNG signature
  - קלט ריק → ValueError
  - שפות שונות → החזרה תקינה
- אינטגרציה קלילה:
  - פקודת `/image` עם db mock + כתיבה ל־tempfile + `reply_photo` נקרא פעם אחת
- ביצועים:
  - זמן יצירה לקובץ קצר < 2s

דוגמת בדיקה מהירה:
```python
import pytest
from services.image_generator import CodeImageGenerator

def test_basic_png_signature():
    gen = CodeImageGenerator(style='monokai')
    img = gen.generate_image("print('hi')", language='python')
    assert img[:8] == b'\x89PNG\r\n\x1a\n'
```

---

## 🔐 הערות אבטחה ושימוש בקבצים זמניים
- שימוש ב־`tempfile.NamedTemporaryFile(delete=False, suffix='.png')`, מחיקה מייד לאחר שליחה
- אין כתיבה/מחיקה מחוץ ל־tmp
- אין לוגים עם תוכן קוד ארוך או נתיבים רגישים

---

## 📈 הרחבות עתידיות (לא חובה ל־MVP)
- WeasyPrint/Playwright לרינדור HTML מתקדם
- תמות מרובות בקונפיג
- Prometheus metrics (נפח תמונה, זמן יצירה, שגיאות)
- Cache על בסיס hash של (code, style, font_size)

---

## ✅ TL;DR – מה ליישם קודם
1) ליצור `services/image_generator.py` (כמו בדוגמה)
2) לחבר פקודה `/image` ב־`bot_handlers.py` (HTML, RateLimiter אסינכרוני)
3) קובץ tmp → `reply_photo` → ניקוי
4) רק אחר כך להוסיף Preview/Batch ותוספות

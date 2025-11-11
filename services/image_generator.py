"""
שירות ליצירת תמונות קוד עם היילייטינג (PIL + Pygments)
Code Image Generator Service

המודול אינו תלוי בתלויות כבדות. WeasyPrint אופציונלי בלבד.
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)

try:  # Pillow (נדרש)
    from PIL import Image, ImageDraw, ImageFont
    from PIL.ImageFont import FreeTypeFont  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]
    ImageFont = None  # type: ignore[assignment]
    FreeTypeFont = None  # type: ignore[assignment]

try:  # Pygments (נדרש)
    from pygments import highlight
    from pygments.formatters import HtmlFormatter
    from pygments.lexers import (
        get_lexer_by_name,
        get_lexer_for_filename,
        guess_lexer,
    )
    from pygments.styles import get_style_by_name
    from pygments.util import ClassNotFound
except Exception:  # pragma: no cover
    highlight = None  # type: ignore[assignment]
    HtmlFormatter = None  # type: ignore[assignment]
    get_lexer_by_name = None  # type: ignore[assignment]
    get_lexer_for_filename = None  # type: ignore[assignment]
    guess_lexer = None  # type: ignore[assignment]
    get_style_by_name = None  # type: ignore[assignment]
    ClassNotFound = Exception  # type: ignore[assignment]


class CodeImageGenerator:
    """מחולל תמונות לקוד עם הדגשת תחביר.

    מבוסס על PIL לציור טקסט ואזורי מספרי שורות, ועל Pygments ליצירת HTML מודגש
    שממנו מחולצים צבעים בסיסיים.
    """

    DEFAULT_WIDTH = 1200
    DEFAULT_PADDING = 40
    LINE_HEIGHT = 24
    FONT_SIZE = 14
    LINE_NUMBER_WIDTH = 60
    LOGO_SIZE = (80, 20)
    LOGO_PADDING = 10

    THEMES = {
        'dark': {
            'background': '#1e1e1e',
            'text': '#d4d4d4',
            'line_number_bg': '#252526',
            'line_number_text': '#858585',
            'border': '#3e3e42',
        },
        'light': {
            'background': '#ffffff',
            'text': '#333333',
            'line_number_bg': '#f5f5f5',
            'line_number_text': '#999999',
            'border': '#e0e0e0',
        },
        'github': {
            'background': '#0d1117',
            'text': '#c9d1d9',
            'line_number_bg': '#161b22',
            'line_number_text': '#7d8590',
            'border': '#30363d',
        },
        'monokai': {
            'background': '#272822',
            'text': '#f8f8f2',
            'line_number_bg': '#3e3d32',
            'line_number_text': '#75715e',
            'border': '#49483e',
        },
    }

    def __init__(self, style: str = 'monokai', theme: str = 'dark') -> None:
        if Image is None:
            raise ImportError("Pillow is required for image generation")
        if highlight is None:
            raise ImportError("Pygments is required for syntax highlighting")

        self.style = style
        self.theme = theme
        self.colors = self.THEMES.get(theme, self.THEMES['dark'])
        self._font_cache: dict[str, FreeTypeFont] = {}
        self._logo_cache: Optional[Image.Image] = None

        # אופציונלי – אם מותקן, נוכל להשתמש במסלול HTML→תמונה מדויק יותר
        try:  # pragma: no cover - תלות אופציונלית
            import weasyprint  # noqa: F401
            self._has_weasyprint = True
        except Exception:
            self._has_weasyprint = False

    # --- Fonts & Logo -----------------------------------------------------
    def _get_font(self, size: int, bold: bool = False) -> FreeTypeFont:
        cache_key = f"{size}_{int(bold)}"
        if cache_key in self._font_cache:
            return self._font_cache[cache_key]

        # מסלולי פונט מונוספייס נפוצים
        font_paths = [
            '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf',
            'C:/Windows/Fonts/consola.ttf',
            '/System/Library/Fonts/Menlo.ttc',
        ]
        font: Optional[FreeTypeFont] = None
        for p in font_paths:
            try:
                path = Path(p)
                if path.exists():
                    font = ImageFont.truetype(str(path), size)
                    if bold:
                        bold_path = str(path).replace('Regular', 'Bold').replace('.ttf', '-Bold.ttf')
                        if Path(bold_path).exists():
                            font = ImageFont.truetype(bold_path, size)
                    break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        self._font_cache[cache_key] = font  # type: ignore[assignment]
        return font  # type: ignore[return-value]

    def _get_logo_image(self) -> Optional[Image.Image]:
        if self._logo_cache is not None:
            return self._logo_cache
        # נסה לטעון לוגו מקובץ
        try:
            candidates = [
                Path(__file__).parent.parent / 'assets' / 'logo.png',
                Path(__file__).parent.parent / 'assets' / 'logo_small.png',
            ]
            for path in candidates:
                if path.exists():
                    logo = Image.open(str(path))
                    logo = logo.resize(self.LOGO_SIZE, Image.Resampling.LANCZOS)
                    self._logo_cache = logo
                    return logo
        except Exception:
            pass
        # Fallback: לוגו טקסטואלי קטן
        try:
            logo = Image.new('RGBA', self.LOGO_SIZE, (0, 0, 0, 0))
            draw = ImageDraw.Draw(logo)
            font = self._get_font(10, bold=True)
            text = "@my_code_keeper_bot"
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = max(0, bbox[2] - bbox[0])
            th = max(0, bbox[3] - bbox[1])
            x = max(0, (self.LOGO_SIZE[0] - tw) // 2)
            y = max(0, (self.LOGO_SIZE[1] - th) // 2)
            draw.rectangle([(0, 0), self.LOGO_SIZE], fill=(30, 30, 30, 200))
            draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)
            self._logo_cache = logo
            return logo
        except Exception as e:  # pragma: no cover
            logger.warning(f"Failed to create logo: {e}")
            return None

    # --- HTML colors extraction ------------------------------------------
    def _html_to_text_colors(self, html_str: str) -> List[Tuple[str, str]]:
        # הסר style/script
        s = re.sub(r'<style[^>]*>.*?</style>', '', html_str, flags=re.DOTALL | re.IGNORECASE)
        s = re.sub(r'<script[^>]*>.*?</script>', '', s, flags=re.DOTALL | re.IGNORECASE)

        text_colors: List[Tuple[str, str]] = []
        pattern = r'<span[^>]*style=\"[^\"]*color:\s*([^;\"\s]+)[^\\\"]*\"[^>]*>(.*?)</span>'
        last = 0
        for m in re.finditer(pattern, s, flags=re.DOTALL):
            before = s[last:m.start()]
            if before.strip():
                clean = re.sub(r'<[^>]+>', '', before)
                if clean:
                    text_colors.append((clean, self.colors['text']))
            color = m.group(1).strip()
            inner = re.sub(r'<[^>]+>', '', m.group(2))
            if inner:
                text_colors.append((inner, color))
            last = m.end()
        tail = s[last:]
        if tail.strip():
            clean = re.sub(r'<[^>]+>', '', tail)
            if clean:
                text_colors.append((clean, self.colors['text']))
        if not text_colors:
            clean_all = re.sub(r'<[^>]+>', '', s)
            if clean_all.strip():
                text_colors.append((clean_all, self.colors['text']))
        return text_colors

    @staticmethod
    def _parse_color(color_str: str) -> Tuple[int, int, int]:
        c = color_str.strip().lower()
        if c.startswith('#'):
            h = c[1:]
            if len(h) == 6:
                return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
            if len(h) == 3:
                return tuple(int(ch * 2, 16) for ch in h)  # type: ignore[return-value]
        m = re.match(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', c)
        if m:
            return tuple(int(x) for x in m.groups())  # type: ignore[return-value]
        common = {
            'white': (255, 255, 255),
            'black': (0, 0, 0),
            'red': (255, 0, 0),
            'green': (0, 255, 0),
            'blue': (0, 0, 255),
            'yellow': (255, 255, 0),
            'cyan': (0, 255, 255),
            'magenta': (255, 0, 255),
        }
        return common.get(c, (212, 212, 212))

    # --- Language detection & safety -------------------------------------
    def _detect_language_from_content(self, code: str, filename: Optional[str] = None) -> str:
        if filename:
            lang_map = {
                '.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.tsx': 'tsx', '.jsx': 'jsx',
                '.java': 'java', '.cpp': 'cpp', '.c': 'c', '.cs': 'csharp', '.php': 'php', '.rb': 'ruby',
                '.go': 'go', '.rs': 'rust', '.swift': 'swift', '.kt': 'kotlin', '.scala': 'scala',
                '.clj': 'clojure', '.hs': 'haskell', '.ml': 'ocaml', '.r': 'r', '.sql': 'sql', '.sh': 'bash',
                '.yaml': 'yaml', '.yml': 'yaml', '.json': 'json', '.xml': 'xml', '.html': 'html', '.css': 'css',
                '.scss': 'scss', '.md': 'markdown', '.tex': 'latex', '.vue': 'vue',
            }
            ext = Path(filename).suffix.lower()
            if ext in lang_map:
                return lang_map[ext]
        patterns = {
            'python': [r'def\s+\w+\s*\(', r'import\s+\w+', r'from\s+\w+\s+import', r'class\s+\w+.*:', r'__main__'],
            'javascript': [r'function\s+\w+\s*\(', r'const\s+\w+\s*=', r'=>\s*{', r'var\s+\w+\s*=', r'let\s+\w+\s*='],
            'java': [r'public\s+class\s+\w+', r'public\s+static\s+void\s+main', r'@Override', r'package\s+\w+'],
            'cpp': [r'#include\s*<', r'std::', r'int\s+main\s*\('],
            'bash': [r'#!/bin/(ba)?sh', r'\$\{', r' if \['],
            'sql': [r'SELECT\s+.*\s+FROM', r'INSERT\s+INTO', r'CREATE\s+TABLE'],
        }
        for lang, pats in patterns.items():
            if any(re.search(p, code, flags=re.IGNORECASE | re.MULTILINE) for p in pats):
                return lang
        return 'text'

    def _check_code_safety(self, code: str) -> None:
        suspicious = [r'exec\s*\(', r'eval\s*\(', r'__import__\s*\(', r'os\.system\s*\(', r'subprocess\.', r'compile\s*\(']
        for p in suspicious:
            if re.search(p, code, flags=re.IGNORECASE):
                logger.warning("Suspicious code pattern detected: %s", p)

    # --- Render helpers ---------------------------------------------------
    def optimize_image_size(self, img: Image.Image) -> Image.Image:
        if img.mode != 'RGB':
            img = img.convert('RGB')
        max_size = (2000, 2000)
        if img.width > max_size[0] or img.height > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
        return img

    def save_optimized_png(self, img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True, compress_level=9)
        data = buf.getvalue()
        if len(data) > 2 * 1024 * 1024:  # 2MB – פשרה: המרה ל-JPEG איכותי
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=95, optimize=True)
            data = buf.getvalue()
        return data

    # --- Public API -------------------------------------------------------
    def generate_image(
        self,
        code: str,
        language: str = 'text',
        filename: Optional[str] = None,
        max_width: int = DEFAULT_WIDTH,
        max_height: Optional[int] = None,
    ) -> bytes:
        if not isinstance(code, str):
            raise TypeError("Code must be a string")
        if not code:
            raise ValueError("Code cannot be empty")
        if len(code) > 100_000:
            raise ValueError("Code too large (max 100KB)")
        if language and not isinstance(language, str):
            raise TypeError("Language must be a string")

        self._check_code_safety(code)

        # Detect language if needed
        if not language or language == 'text':
            language = self._detect_language_from_content(code, filename)

        # Prepare lexer/formatter
        try:
            if filename:
                try:
                    lexer = get_lexer_for_filename(filename)  # type: ignore[misc]
                except ClassNotFound:
                    lexer = get_lexer_by_name(language, stripall=True)  # type: ignore[misc]
            else:
                lexer = get_lexer_by_name(language, stripall=True)  # type: ignore[misc]
        except Exception:
            lexer = get_lexer_by_name('text', stripall=True)  # type: ignore[misc]

        try:
            style = get_style_by_name(self.style)  # type: ignore[misc]
        except Exception:
            style = get_style_by_name('default')  # type: ignore[misc]

        formatter = HtmlFormatter(style=style, noclasses=True, nowrap=True)  # type: ignore[call-arg]
        highlighted_html = highlight(code, lexer, formatter)  # type: ignore[misc]

        # Layout calculations
        lines = code.split('\n')
        num_lines = len(lines)
        font = self._get_font(self.FONT_SIZE)
        line_height = self.LINE_HEIGHT

        max_line_width = 0
        for ln in lines:
            try:
                bbox = font.getbbox(ln)  # type: ignore[attr-defined]
                w = max(0, bbox[2] - bbox[0])
            except Exception:
                w = len(ln) * 8
            max_line_width = max(max_line_width, w)

        content_width = self.LINE_NUMBER_WIDTH + 20 + max_line_width + self.DEFAULT_PADDING
        image_width = min(int(content_width), int(max_width or self.DEFAULT_WIDTH))

        image_height = int(num_lines * line_height + self.DEFAULT_PADDING * 2)
        if max_height and image_height > max_height:
            max_lines = max(1, (int(max_height) - self.DEFAULT_PADDING * 2) // line_height)
            lines = lines[:max_lines]
            num_lines = len(lines)
            image_height = int(num_lines * line_height + self.DEFAULT_PADDING * 2)

        # Manual rendering via PIL (ברירת מחדל)
        img = Image.new('RGB', (image_width, image_height), self.colors['background'])
        draw = ImageDraw.Draw(img)

        # Line numbers background + divider
        ln_bg_x2 = self.DEFAULT_PADDING + self.LINE_NUMBER_WIDTH
        draw.rectangle([(0, 0), (ln_bg_x2, image_height)], fill=self.colors['line_number_bg'])
        draw.line([(ln_bg_x2, 0), (ln_bg_x2, image_height)], fill=self.colors['border'], width=1)

        code_x = ln_bg_x2 + 20
        code_y = self.DEFAULT_PADDING

        html_lines = highlighted_html.split('\n')
        ln_font = self._get_font(self.FONT_SIZE - 1)

        for i, (plain_line, html_line) in enumerate(zip(lines, html_lines[:len(lines)]), start=1):
            y = code_y + (i - 1) * line_height
            # line number
            num_str = str(i)
            try:
                bbox = ln_font.getbbox(num_str)  # type: ignore[attr-defined]
                num_w = max(0, bbox[2] - bbox[0])
            except Exception:
                num_w = len(num_str) * 6
            num_x = ln_bg_x2 - num_w - 10
            draw.text((num_x, y), num_str, fill=self.colors['line_number_text'], font=ln_font)

            # code segments according to spans
            x = code_x
            segments = self._html_to_text_colors(html_line)
            if not segments:
                segments = [(plain_line, self.colors['text'])]
            for text, color_str in segments:
                if not text:
                    continue
                color = self._parse_color(color_str)
                draw.text((x, y), text, fill=color, font=font)
                try:
                    bbox = font.getbbox(text)  # type: ignore[attr-defined]
                    w = max(0, bbox[2] - bbox[0])
                except Exception:
                    w = len(text) * 8
                x += w

        # Logo (optional)
        logo = self._get_logo_image()
        if logo is not None:
            lx = max(0, image_width - self.LOGO_SIZE[0] - self.LOGO_PADDING)
            ly = max(0, image_height - self.LOGO_SIZE[1] - self.LOGO_PADDING)
            if logo.mode == 'RGBA':
                img.paste(logo, (lx, ly), logo)
            else:
                img.paste(logo, (lx, ly))

        img = self.optimize_image_size(img)
        return self.save_optimized_png(img)

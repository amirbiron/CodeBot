"""יוצר מחדש את ``tests/fixtures/syntax_colors_vscode_reference.json`` — מה ש-VS Code עושה עם דוגמאות הקוד שבתיקייה.

הרצה, משורש הריפו (צריך Node, ותלויות שמותקנות פעם אחת לתיקייה הזו — ראו ``README.md``)::

    npm ci --prefix scripts/syntax_colors
    python scripts/syntax_colors/generate_reference.py

הסקריפט שולח ל-``reference.mjs`` את הדוגמאות (``samples/``) ואת ה-``tokenColors`` של ערכות הייצוא, ושומר את התשובה
יחד עם ה-hash של כל קלט. ``tests/test_vscode_token_theme.py`` בודק שה-hash תואם לערכות ולדוגמאות של היום, ולכן שינוי
באחת מהן נכשל שם עד שמריצים את הסקריפט מחדש.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "syntax_colors_vscode_reference.json"
SAMPLE_FILES = {"python": "python.txt", "javascript": "javascript.txt"}


def reference_themes() -> dict[str, list]:
    """ה-``tokenColors`` של ערכות הייצוא — ``EXPORT_PRESET_TOKEN_COLORS``, אותן רשימות שהמחוללים מקבלים."""
    sys.path.insert(0, str(REPO))
    from services.styled_export_service import EXPORT_PRESET_TOKEN_COLORS

    return dict(EXPORT_PRESET_TOKEN_COLORS)


def sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def main() -> int:
    samples = {lang: (HERE / "samples" / name).read_text(encoding="utf-8") for lang, name in SAMPLE_FILES.items()}
    themes = reference_themes()
    proc = subprocess.run(
        ["node", str(HERE / "reference.mjs")],
        input=json.dumps({"samples": samples, "themes": themes}),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode
    reference = json.loads(proc.stdout)
    reference["inputs"] = {
        "samples_sha256": {lang: sha256_json(code) for lang, code in samples.items()},
        "token_colors_sha256": {theme_id: sha256_json(tokens) for theme_id, tokens in themes.items()},
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(reference, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

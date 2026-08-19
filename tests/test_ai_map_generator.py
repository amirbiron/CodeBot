"""בדיקות למחולל מפת התיעוד (scripts/generate_ai_map.py).

מה נבדק כאן — ומה בכוונה לא: הבדיקות מוודאות שהמחולל רץ, דטרמיניסטי,
ומכסה עמודים אמיתיים. הן **לא** משוות את הפלט ל-AI-MAP.md שבריפו —
השוואה כזו הייתה מפילה כל PR שנוגע בתיעוד עד שמישהו מייצר מחדש ידנית,
וזו בדיוק המציקות שגורמת לכבות שמירות. את הרענון עושה GitHub Action
שמקמט את המפה בעצמו (.github/workflows/ai-map.yml).
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_ai_map", ROOT / "scripts" / "generate_ai_map.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_ai_map"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_output_is_deterministic():
    """אותו קלט ← אותו פלט, בייט בבייט. בלי זה כל השוואה היא רעש."""
    gen = _load_generator()
    assert gen.build_map() == gen.build_map()


def test_map_covers_known_manual_pages():
    """עמודים ידניים מרכזיים מופיעים; ההיררכיה באמת נגזרת מה-toctree."""
    content = _load_generator().build_map()
    for expected in (
        "docs/workflows/save-flow.rst",
        "docs/architecture.rst",
        "docs/quickstart-ai.rst",
    ):
        assert expected in content, f"עמוד ידני חסר במפה: {expected}"


def test_autodoc_scaffolds_are_filtered():
    """עמוד שהוא automodule בלבד לא נכנס — הוא ריק כשקוראים מהריפו."""
    content = _load_generator().build_map()
    assert "docs/api/bot_handlers.rst" not in content
    assert "עמודי פיגום autodoc שסוננו" in content, (
        "שורת הסיכום נעלמה — ההשמטה חייבת להישאר גלויה"
    )


def test_no_timestamps_in_generator_authored_lines():
    """חותמת זמן שהמחולל מוסיף הופכת כל ריצה ל-diff. אסור שתהיה.

    נבדקות רק השורות שהמחולל מחבר בעצמו (כותרת, הערת ה"נוצר אוטומטית",
    שורת הסיכום) — לא תקצירים שנשלפו מהעמודים, כי תאריך לגיטימי בפסקה
    ראשונה של דף היה הופך את הבדיקה למחסום מציק על עריכת תיעוד.
    """
    import re

    content = _load_generator().build_map()
    authored = [
        ln for ln in content.splitlines()
        if not ln.lstrip().startswith("-")  # שורות ערכים מגיעות מהעמודים
    ]
    stamp = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b|\d{2}:\d{2}:\d{2}")
    hits = [ln for ln in authored if stamp.search(ln)]
    assert not hits, f"חותמת זמן בשורות של המחולל: {hits}"

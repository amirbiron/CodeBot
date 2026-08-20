"""בדיקות למחולל מפת התיעוד (scripts/generate_ai_map.py).

מה נבדק כאן — ומה בכוונה לא: הבדיקות מוודאות שהמחולל עצמו רץ,
דטרמיניסטי, ומכסה עמודים אמיתיים. הן **לא** משוות את הפלט ל-AI-MAP.md
שבריפו; ההשוואה הזו היא בדיקה נפרדת, tests/test_ai_map_freshness.py,
כדי שכשל בה יקרא "המפה לא רועננה" ולא "המחולל שבור".

הערה על התיאור הקודם כאן: הוא טען שהשוואה כזו הייתה מפילה כל PR שנוגע
בתיעוד, ולכן הרענון הופקד ב-GitHub Action שמקמט את המפה בעצמו. אותו
Action נמחק. main מוגן, וכל ניסיון לתת לאוטומציה לכתוב אליו נתקל באותו
קיר בצורה אחרת. הכשל האדום הוא לא מציקות — הוא בדיוק הסימן שצריך
לרענן, והרענון הוא פקודה אחת באותו PR.
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


def test_table_first_page_does_not_hang(tmp_path):
    """עמוד שנפתח בטבלה לא תוקע את המחולל, ותחביר הטבלה לא חוזר כתקציר.

    רגרסיה: תנאי העצירה על שורת טבלה קפץ לפני קידום האינדקס, ואותה
    שורה נבדקה שוב לנצח. שום דף נוכחי לא נפתח בטבלה — הדף הראשון שכן
    היה תוקע את ה-Action בלי הודעת שגיאה.

    רץ בתת-תהליך ולא בת'רד: ת'רד daemon שנתקע ממשיך לסובב על ליבה
    שלמה עד סוף ריצת pytest ומאט את שאר הבדיקות, ובנוסף חריגה בתוכו
    נבלעת ומופיעה כ-KeyError מבלבל במקום כשורש הבעיה. תת-תהליך נהרג
    ב-timeout, ומחזיר את החריגה המקורית ב-stderr.

    שני סוגי הטבלאות של RST נבדקים: pipe ו-grid (``+---+``).
    """
    import subprocess
    import sys as _sys

    probe = tmp_path / "probe.py"
    probe.write_text(
        "import importlib.util, json, sys\n"
        f"spec = importlib.util.spec_from_file_location('g', {str(ROOT / 'scripts' / 'generate_ai_map.py')!r})\n"
        "g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)\n"
        "from pathlib import Path\n"
        "cases = {\n"
        "  'pipe': ['כותרת', '======', '', '| עמודה ראשונה ארוכה | שנייה ארוכה מאוד |', '',"
        " 'פסקת פרוזה ארוכה מספיק שנשלפת אחרי הטבלה כתקציר.'],\n"
        "  'grid': ['כותרת', '======', '', '+--------------------+------------------+',"
        " '| עמודה ארוכה מאוד   | עוד עמודה ארוכה  |', '+====================+==================+', '',"
        " 'פסקת פרוזה ארוכה מספיק שנשלפת אחרי הטבלה כתקציר.'],\n"
        "}\n"
        "print(json.dumps({k: g._first_prose_paragraph(v, Path('x.rst')) for k, v in cases.items()}))\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [_sys.executable, str(probe)], capture_output=True, text=True, timeout=30, cwd=tmp_path
    )
    assert proc.returncode == 0, f"המחולל נכשל על עמוד שנפתח בטבלה:\n{proc.stderr}"

    import json

    results = json.loads(proc.stdout)
    for kind, summary in results.items():
        assert "פסקת פרוזה" in summary, f"{kind}: הפסקה שאחרי הטבלה לא נשלפה"
        assert "|" not in summary and "+--" not in summary, (
            f"{kind}: תחביר טבלה הוחזר כתקציר במקום להיות מדולג"
        )


def test_pipeless_markdown_table_body_is_skipped():
    """שורות הנתונים של טבלת Markdown בלי pipe חיצוני לא נכנסות לתקציר.

    רגרסיה: הזיהוי הקודם טיפל בשורת הכותרת ובשורת המפריד בלבד, ולכן
    שורות הנתונים ("אלפא | ערך…") נפלו לאיסוף הפרוזה — ותקציר העמוד
    במפה יצא הטבלה עצמה במקום הפסקה שאחריה. השורש: טבלת Markdown היא
    בלוק, לא שורה, ולפי GFM היא נמשכת עד השורה הריקה הראשונה.

    השורות כאן ארוכות בכוונה: תקציר קצר מהסף נזרק ממילא, וטבלה עם
    שורות קצרות הייתה מעבירה את הבדיקה גם בלי התיקון.
    """
    g = _load_generator()
    page = [
        "כותרת",
        "======",
        "",
        "שם | ערך",
        "--- | ---",
        "אלפא | ערך ראשון שהוא ארוך מספיק כדי לעבור את סף התקציר",
        "ביתא | ערך שני שגם הוא ארוך מספיק כדי לעבור את סף התקציר",
        "",
        "פסקת פרוזה אמיתית שהיא זו שאמורה לשמש כתקציר של העמוד הזה.",
    ]
    summary = g._first_prose_paragraph(page, Path("x.rst"))
    assert "פסקת פרוזה" in summary, f"הפסקה שאחרי הטבלה לא נשלפה: {summary!r}"
    assert "אלפא" not in summary and "ביתא" not in summary, (
        f"שורות הנתונים של הטבלה דלפו לתקציר: {summary!r}"
    )


def test_block_start_ends_the_markdown_table_skip():
    """בלוק שמתחיל מיד אחרי טבלה, בלי שורה ריקה, לא נבלע יחד איתה.

    רגרסיה: דילוג הטבלה עצר בשורה ריקה בלבד, ולכן כותרת/גדר/קו מפריד
    שהופיעו צמוד לטבלה נבלעו — ואיתם הפרוזה שאחריהם. התקציר יצא ריק.

    הכלל נלקח מהמימוש שהתיעוד באמת נבנה איתו: לולאת הגוף של כלל הטבלה
    ב-``markdown_it/rules_block/table.py`` נשברת גם על ``terminatorRules``
    ולא רק על שורה ריקה. תחת ההגדרות ב-``docs/conf.py`` הרשימה היא
    front_matter, colon_fence, fence, line_comment, blockquote,
    block_break, target, hr, list_block, html_block, heading, deflist.
    """
    g = _load_generator()
    prose = "פסקת הפרוזה האמיתית של העמוד, ארוכה מספיק כדי לעבור את הסף."
    table = ["שם | ערך", "--- | ---", "אלפא | ערך ארוך מספיק כדי לעבור את הסף"]
    # הבלוקים סגורים בכוונה: גדר פתוחה באמת מכילה את כל מה שאחריה,
    # ובדיקה עם גדר פתוחה הייתה בודקת התנהגות שגויה ולא את הממצא.
    starters = {
        "כותרת ATX": ["## כותרת ביניים"],
        "fence": ["```", "code", "```"],
        "colon_fence": [":::{note}", "גוף ההערה", ":::"],
        "hr": ["***"],
        "blockquote": ["> ציטוט"],
    }
    for kind, starter in starters.items():
        page = ["כותרת", "======", ""] + table + starter + [prose]
        summary = g._first_prose_paragraph(page, Path("x.md"))
        assert prose[:20] in summary, f"{kind}: הפרוזה נבלעה עם הטבלה ({summary!r})"
        assert "אלפא" not in summary, f"{kind}: שורת טבלה דלפה לתקציר ({summary!r})"


# כל סוג בלוק ש-``_MD_BLOCK_START_RE`` מזהה, ומה שצריך כדי לסגור אותו.
# הרשימה הזו היא החוזה: כל מה שעוצר את דילוג הטבלה חייב גם להיות מדולג
# על ידי הלולאה הראשית, אחרת הוא נכנס לתקציר.
_BLOCK_KINDS = {
    "heading": ["## כותרת ביניים"],
    "fence_backtick": ["```", "code", "```"],
    "fence_tilde": ["~~~", "code", "~~~"],
    "colon_fence": [":::{note}", "גוף ההערה", ":::"],
    "blockquote": ["> ציטוט ארוך מספיק שאסור לו להופיע כתקציר של העמוד"],
    "list_dash": ["- פריט ברשימה"],
    "list_star": ["* פריט ברשימה"],
    "list_plus": ["+ פריט ברשימה"],
    "list_ordered": ["1. פריט ממוספר"],
    "html_block": ["<div>תוכן html ארוך מספיק שאינו אמור להיות תקציר</div>"],
    "line_comment": ["% הערת MyST ארוכה שאסור לה להופיע כתקציר של העמוד"],
    "block_break": ["+++"],
    "target": ["(שם-היעד)="],
    "hr_dash": ["---"],
    "hr_star": ["***"],
    "hr_underscore": ["___"],
}


def test_every_block_kind_is_skipped_after_a_table():
    """כל בלוק שעוצר את דילוג הטבלה גם מדולג בפועל, ולא נכנס לתקציר.

    רגרסיה כפולה. היו כאן שתי רשימות שחייבות להסכים: זו שעוצרת את דילוג
    הטבלה (``_MD_BLOCK_START_RE``) וזו שהלולאה הראשית מדלגת לפיה. הן
    נפרדו בשקט — ``%``, ``<`` ו-``(target)=`` עצרו את הדילוג אבל לא דולגו,
    אז הערת MyST שלמה נכנסה לתקציר של העמוד. השלמת הטאפל בלבד השאירה את
    ``+ פריט`` דולף, ולכן השורש הוא איחוד לרשימה אחת ולא הוספת פריטים.

    הבדיקה כאן היא החוזה שמונע את הפרידה הבאה: היא רצה על **כל** סוג בלוק,
    ולכן פריט חדש ברג'קס בלי טיפול תואם בלולאה נופל כאן מיד.
    """
    g = _load_generator()
    prose = "פסקת הפרוזה האמיתית של העמוד, ארוכה מספיק כדי לעבור את הסף."
    table = ["שם | ערך", "--- | ---", "אלפא | ערך ארוך מספיק כדי לעבור את הסף"]
    for kind, block in _BLOCK_KINDS.items():
        # בלי שורה ריקה בין הטבלה לבלוק, וזה כל העניין
        page = ["כותרת", "======", ""] + table + block + [prose]
        summary = g._first_prose_paragraph(page, Path("x.md")).strip()
        assert summary == prose, f"{kind}: התקציר אינו הפרוזה בלבד ({summary!r})"


def test_block_start_regex_matches_every_declared_kind():
    """כל סוג בלוק ברשימה למעלה באמת מזוהה על ידי הרג'קס.

    בלי הבדיקה הזו אפשר היה למחוק פריט מהרג'קס והבדיקה שמעליה הייתה
    ממשיכה לעבור — הלולאה הראשית מדלגת על חלק מהבלוקים גם בלעדיו,
    והכיסוי היה נשען על מקריות.
    """
    g = _load_generator()
    for kind, block in _BLOCK_KINDS.items():
        assert g._MD_BLOCK_START_RE.match(block[0]), f"{kind}: {block[0]!r} אינו מזוהה ברג'קס"


def test_table_row_that_starts_a_block_does_not_hang(tmp_path):
    """שורה שנכנסת לענף הטבלה **והיא בעצמה** תחילת בלוק לא תוקעת.

    בלי קידום ודאי לפני לולאת הדילוג, שורה כמו ``- פריט | עמודה`` שמתחתיה
    שורת מפריד הייתה מחזירה את הלולאה החיצונית לאותו אינדקס לנצח. אומת:
    הסרת הקידום מקפיאה גם ``.rst`` וגם ``.md``.

    רץ בתת-תהליך מאותה סיבה כמו הבדיקה שמעליה: ת'רד תקוע ממשיך לסובב
    על ליבה עד סוף ריצת pytest.
    """
    import subprocess
    import sys as _sys

    probe = tmp_path / "probe_loop.py"
    probe.write_text(
        "import importlib.util, json, sys\n"
        f"spec = importlib.util.spec_from_file_location('g', {str(ROOT / 'scripts' / 'generate_ai_map.py')!r})\n"
        "g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)\n"
        "from pathlib import Path\n"
        "page = ['כותרת', '======', '', '- פריט | עמודה', '--- | ---', 'אלפא | ערך', '',"
        " 'פסקת פרוזה ארוכה מספיק כדי לעבור את הסף של עשרים תווים.']\n"
        "print(json.dumps({s: g._first_prose_paragraph(page, Path('x' + s)) for s in ('.rst', '.md')}))\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [_sys.executable, str(probe)], capture_output=True, text=True, timeout=30, cwd=tmp_path
    )
    assert proc.returncode == 0, f"המחולל נכשל או נתקע:\n{proc.stderr}"

    import json

    for suffix, summary in json.loads(proc.stdout).items():
        assert "פסקת פרוזה" in summary, f"{suffix}: הפרוזה לא נשלפה ({summary!r})"


def test_prose_containing_a_pipe_is_not_mistaken_for_a_table():
    """פסקה שמכילה ``|`` בלי שורת מפריד מתחתיה נשארת תקציר תקין.

    הצד השני של הבדיקה שמעליה: דילוג על בלוק שלם מסוכן יותר מדילוג על
    שורה, ולכן צריך שומר שיתפוס הרחבה של הזיהוי לפרוזה רגילה.
    """
    g = _load_generator()
    page = [
        "כותרת",
        "======",
        "",
        "ההפרדה בין a | b כאן היא סימן ולא טבלה, והפסקה הזו אמורה לשרוד.",
    ]
    summary = g._first_prose_paragraph(page, Path("x.rst"))
    assert "ההפרדה בין" in summary, f"פרוזה עם pipe נבלעה כטבלה: {summary!r}"


def _run_cli(*args, cwd):
    """מריץ את המחולל כתהליך משנה. ``cwd`` חובה ותמיד תיקייה זמנית —
    למחולל נתיבים מוחלטים, ולפי הנחיות הריפו טסט לא רץ מתוך שורש הפרויקט."""
    import subprocess
    import sys as _sys

    return subprocess.run(
        [_sys.executable, str(ROOT / "scripts" / "generate_ai_map.py"), *args],
        capture_output=True, text=True, timeout=120, cwd=cwd,
    )


def test_cli_default_prints_and_writes_nothing(tmp_path):
    """בלי --out: המפה ב-stdout ואף קובץ לא נכתב — מדיניות אי-כתיבה ב-root."""
    before = {f: f.stat().st_mtime_ns for f in ROOT.glob("*.md")}
    proc = _run_cli(cwd=tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.startswith("# מפת התיעוד לסוכני AI")
    after = {f: f.stat().st_mtime_ns for f in ROOT.glob("*.md")}
    assert before == after, "הרצה בלי --out נגעה בקובץ בשורש"


def test_cli_out_writes_to_given_path(tmp_path):
    out = tmp_path / "map.md"
    proc = _run_cli("--out", str(out), cwd=tmp_path)
    assert proc.returncode == 0
    assert out.exists() and "docs/workflows/save-flow.rst" in out.read_text(encoding="utf-8")


def test_cli_check_exit_codes(tmp_path):
    """--check מחזיר 0 על קובץ תואם ו-1 על קובץ שסטה — בלי לכתוב כלום."""
    fresh = tmp_path / "fresh.md"
    assert _run_cli("--out", str(fresh), cwd=tmp_path).returncode == 0
    assert _run_cli("--check", str(fresh), cwd=tmp_path).returncode == 0

    stale = tmp_path / "stale.md"
    stale.write_text("מפה מיושנת", encoding="utf-8")
    proc = _run_cli("--check", str(stale), cwd=tmp_path)
    assert proc.returncode == 1
    assert stale.read_text(encoding="utf-8") == "מפה מיושנת", "--check אסור שיכתוב"


def test_grid_row_regex_has_no_catastrophic_backtracking(tmp_path):
    """שורת פלוסים ארוכה שאינה גבול טבלה לא תוקעת את המחולל.

    רגרסיה: '+' הופיע גם במחלקת התווים וגם כמפריד הקבוצה החוזרת —
    חפיפה שיוצרת backtracking אקספוננציאלי (נמדד ×2.6 לכל תו: 23ms
    ב-28 תווים, דקות ב-40). דף תיעוד עם שורה כזו היה תוקע את ה-CI.

    רץ בתת-תהליך עם timeout: על ה-regex הפגום הקריאה לא חוזרת לעולם,
    ותהליך אפשר להרוג — בניגוד לת'רד.
    """
    import subprocess
    import sys as _sys

    probe = tmp_path / "probe.py"
    probe.write_text(
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('g', {str(ROOT / 'scripts' / 'generate_ai_map.py')!r})\n"
        "g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)\n"
        "evil = '+' * 64 + 'x'\n"
        "assert g._GRID_ROW_RE.match(evil) is None\n"
        "assert g._GRID_ROW_RE.match('+----+====+')\n"
        "print('ok')\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [_sys.executable, str(probe)], capture_output=True, text=True,
        timeout=10, cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"

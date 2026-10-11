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


def test_the_map_carries_the_authority_warning():
    """המפה נושאת את הכלל שהתיעוד אינו סמכות, ולא רק הפריימר.

    את ``AI-MAP.md`` קורא גם מי שלא קיבל את הפריימר — סוכן בכלי אחר, או
    grep מקרי. כלל שגר במקום אחד בלבד לא ייקרא בדיוק כשצריך אותו, וזה
    הכלל שהכי יקר לפספס: כל סבבי הריוויו כאן מצאו טענות בפרוזה שסתרו את
    הקוד. הבדיקה נופלת אם מישהו יסיר את הסעיף מהמחולל.
    """
    lines = _load_generator().build_map().split("\n")

    assert "## סמכות התיעוד" in lines
    start = lines.index("## סמכות התיעוד")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start:end])

    assert "התמצאות, לא סמכות" in section
    # דווקא בתוך הסעיף, ולא ב-``content`` כולו: ``autodoc`` מופיע ממילא
    # ב-preamble של המפה ובשורת הסיכום, ולכן טענה על הטקסט המלא הייתה
    # עוברת גם אחרי מחיקת משפט החריגים — נמדד. ``literalinclude`` יחיד
    # היום, אבל מספיק שעמוד אחד יזכיר אותו בתקציר כדי שגם הוא יתרוקן.
    assert "literalinclude" in section
    assert "autodoc" in section


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


def test_declared_summary_reads_an_rst_field():
    """שדה ``:summary:`` ברשימת השדות שפותחת את הקובץ נקרא, כולל שורות המשך מוזחות.

    המיקום הוא לפני הכותרת: משם Sphinx מעביר את רשימת השדות למידע על
    העמוד ולא מציג אותה (ההסבר ליד ``_SUMMARY_FIELD_RE`` במחולל).
    """
    g = _load_generator()
    page = [":summary: התקציר המוצהר של העמוד.", "", "כותרת העמוד", "===========", "", "גוף."]
    assert g._declared_summary(page, Path("x.rst")) == "התקציר המוצהר של העמוד."

    wrapped = [":summary: שורה ראשונה של התקציר", "   והמשך מוזח שלה.", "",
               "כותרת העמוד", "===========", "", "גוף."]
    assert g._declared_summary(wrapped, Path("x.rst")) == "שורה ראשונה של התקציר והמשך מוזח שלה."


def test_declared_summary_ignores_an_indented_field():
    """``:summary:`` מוזח אינו הצהרה — הוא תוכן של בלוק אחר — וגם לא מדווח כהצהרה במקום הלא נכון.

    עמודה 0 בדיוק היא מה ש-``docutils`` מפרש כשדה ברמת המסמך; בלי הכלל
    הזה שורה בתוך ``.. note::`` או בתוך בלוק קוד — כמו הדוגמה שב-
    ``docs/doc-authoring.rst`` — הייתה נחשבת תקציר, או מפילה את
    ``test_no_rst_page_has_a_summary_away_from_the_top_of_the_file``.
    """
    g = _load_generator()
    page = ["כותרת", "=====", "", ".. note::", "   :summary: לא הצהרה.", "", "גוף."]
    assert g._declared_summary(page, Path("x.rst")) == ""
    assert g._misplaced_rst_summaries(page) == []

    # מוזח גם בראש הקובץ: זה ציטוט (block quote), לא רשימת שדות
    quoted = ["   :summary: לא הצהרה.", "", "כותרת", "=====", "", "גוף."]
    assert g._declared_summary(quoted, Path("x.rst")) == ""
    assert g._misplaced_rst_summaries(quoted) == []


def test_declared_summary_reads_markdown_front_matter():
    """``summary`` ב-front matter נקרא ב-``yaml.safe_load``, כמו ב-MyST.

    ``myst_parser/mdit_to_docutils/base.py``: ``data = yaml.safe_load(...)``.
    הערך כאן מכיל נקודתיים בכוונה — הוא חייב לעבור round-trip דרך YAML.
    """
    g = _load_generator()
    page = ["---", "summary: 'מטרה: להסביר משהו.'", "---", "", "# כותרת", "", "גוף."]
    assert g._declared_summary(page, Path("x.md")) == "מטרה: להסביר משהו."


def test_declared_summary_is_empty_without_a_declaration():
    """עמוד בלי הצהרה מחזיר ריק — ואז המפה מציגה כותרת בלבד."""
    g = _load_generator()
    assert g._declared_summary(["כותרת", "=====", "", "גוף."], Path("x.rst")) == ""
    assert g._declared_summary(["# כותרת", "", "גוף."], Path("x.md")) == ""
    assert g._declared_summary(["---", "author: פלוני", "---", "", "# כותרת"], Path("x.md")) == ""


def test_declared_summary_is_capped():
    """הצהרה ארוכה נחתכת בשורת המפה, ונשארת מלאה בעמוד.

    בלי החיתוך שורת מפה אחת יכולה להיות ארוכה מכל השאר יחד, וזה מבטל
    את התועלת של מפה. אומת: החיתוך הוא מה שהופך את הזריעה לזהה
    בייט-בייט למפה שנוצרה מחילוץ.
    """
    g = _load_generator()
    long = "מילה " * 200
    page = [f":summary: {long}", "", "כותרת", "=====", "", "גוף."]
    got = g._declared_summary(page, Path("x.rst"))
    assert len(got) <= g.SUMMARY_CAP, len(got)
    assert got.endswith("…")


def test_body_start_is_read_from_the_parser_and_not_computed_here(monkeypatch):
    """הגבול של ה-front matter מגיע מ-``services.md_parser.front_matter_end`` (#3419) — לא מכלל שנכתב כאן.

    ערך שאף כלל ידני לא היה מחזיר על הקלט הזה מוכיח שהפונקציה מאצילה ולא
    מחשבת; ההסכמה עם התוסף על כל צורה נבדקת ב-``tests/test_md_parser.py``.
    """
    from services import md_parser

    g = _load_generator()
    monkeypatch.setattr(md_parser, "front_matter_end", lambda text: 7)
    assert g._body_start(["# not front matter at all"]) == 7


def test_front_matter_does_not_become_the_title():
    """ה-``---`` הסוגר של front matter אינו קו-תחתון של כותרת setext.

    רגרסיה שנתפסה במבחן הקבלה של הזריעה: ``_UNDERLINE_RE`` מתאים גם
    ל-``---``, ולכן שורת ``summary:`` שמעליו נקראה ככותרת והכותרת של
    העמוד יצאה ``summary: '...'``.
    """
    g = _load_generator()
    page = ["---", "summary: תקציר כלשהו.", "---", "", "# הכותרת האמיתית", "", "גוף."]
    assert g._title(page, Path("x.md")) == "הכותרת האמיתית"


def test_check_warns_about_undeclared_pages_without_failing(tmp_path):
    """``--check`` מתריע על עמוד ידני בלי הצהרה, ומחזיר 0.

    ההידרדרות הדרגתית היא כל הרעיון: עמוד בלי תקציר עדיין מופיע במפה
    עם הכותרת שלו, ולכן אין סיבה להפיל עליו את ה-CI.
    """
    # מפה טרייה ב-tmp_path, ולא AI-MAP.md שבריפו: הצמדה למפה המקומטת
    # הייתה מפילה את הסוויטה הזו על "המפה לא רועננה" — כשל שכבר יש לו
    # בדיקה ייעודית (test_ai_map_freshness) עם הודעה שמסבירה מה לעשות.
    # כאן נבדק רק מה שהבדיקה מתיימרת לבדוק: --check מתריע ולא מפיל.
    fresh = tmp_path / "fresh-map.md"
    written = _run_cli("--out", str(fresh), cwd=tmp_path)
    assert written.returncode == 0, written.stdout + written.stderr

    proc = _run_cli("--check", str(fresh), cwd=tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "עדכני" in proc.stdout, proc.stdout

    g = _load_generator()
    g.build_map()
    if g.undeclared:
        assert "התרעה:" in proc.stdout, proc.stdout
        assert g.undeclared[0] in proc.stdout, proc.stdout


def test_a_summary_that_only_repeats_the_title_is_dropped(tmp_path):
    """תקציר שכל כולו הכותרת אינו נכנס לשורת המפה.

    שורה כמו ``**ניהול גיבויים**: ניהול גיבויים`` היא רעש: היא תופסת
    מקום בקובץ שכל מטרתו לחסוך קריאה, ולא מוסיפה מילה. הכלל המשלים
    לזה נמצא ב-``docs/doc-authoring.rst`` ("אל תתחילו בשם העמוד") —
    שם הוא מונע את הכפילות בכתיבה, וכאן המחולל מנקה מה שנשאר.

    אף עמוד בריפו אינו מפעיל את התנאי כרגע. הבדיקה שומרת על ההתנהגות,
    לא מתקנת עמוד קיים.

    התנאי הוא הכלה ולא שוויון, ולכן גם תקציר שהוא תת-מחרוזת של הכותרת
    יורד — ``partial`` למטה מכסה בדיוק את זה. ההשלכה מוצהרת ולא סמויה:
    תקציר קצר במיוחד יורד גם כשהוא לא כפילות מדויקת. אם אי פעם נהדק את
    התנאי לשוויון, ההצהרה הזו תיפול ברעש במקום שההתנהגות תשתנה בשקט.
    """
    g = _load_generator()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "index.rst").write_text(
        "שורש\n====\n\n.. toctree::\n   :caption: קבוצה\n\n"
        "   echo\n   ellipsis\n   partial\n   real\n",
        encoding="utf-8",
    )
    (docs / "echo.rst").write_text(
        ":summary: ניהול גיבויים\n\nניהול גיבויים\n=============\n\nגוף.\n",
        encoding="utf-8",
    )
    # אותו מקרה, אבל הכותב סיים בשלוש נקודות — ה-rstrip הוא שמזהה אותו
    (docs / "ellipsis.rst").write_text(
        ":summary: ניהול הרשאות…\n\nניהול הרשאות\n============\n\nגוף.\n",
        encoding="utf-8",
    )
    # הכלה חלקית: תקציר קצר שהוא תת-מחרוזת של כותרת ארוכה יותר
    (docs / "partial.rst").write_text(
        ":summary: התקנה\n\nמדריך התקנה והרצה מקומית\n========================\n\nגוף.\n",
        encoding="utf-8",
    )
    (docs / "real.rst").write_text(
        ":summary: איך מוסיפים תבנית חדשה.\n\nניהול תבניות\n============\n\nגוף.\n",
        encoding="utf-8",
    )
    g.ROOT, g.DOCS = tmp_path, docs

    content = g.build_map()

    assert "- `docs/echo.rst` — **ניהול גיבויים**" in content
    assert "**ניהול גיבויים**: " not in content
    assert "- `docs/ellipsis.rst` — **ניהול הרשאות**" in content
    assert "**ניהול הרשאות**: " not in content
    assert "- `docs/partial.rst` — **מדריך התקנה והרצה מקומית**" in content
    assert "**מדריך התקנה והרצה מקומית**: " not in content
    # בקרה: בלי זה הבדיקה הייתה עוברת גם אם *כל* התקצירים היו נופלים
    assert (
        "- `docs/real.rst` — **ניהול תבניות**: איך מוסיפים תבנית חדשה." in content
    )


def test_only_the_field_list_that_opens_the_file_is_the_declaration():
    """``:summary:`` בכל מקום אחר אינו ההצהרה — ו-``_misplaced_rst_summaries`` מדווח עליו.

    מתחת לכותרת — המקום שבו השדה ישב עד אוקטובר 2026 — הוא מוצג בעמוד;
    אחרי תווית בראש הקובץ הוא שובר את התווית בשקט; ובגוף העמוד הוא סתם
    מוצג. הערה לפני ההצהרה לא הייתה מזיקה ב-Sphinx, אבל גם היא נדחית: הכלל
    הוא "הדבר הראשון בקובץ", בלי רשימה של מה מותר לפניו (ההסבר ליד
    ``_SUMMARY_FIELD_RE`` במחולל).
    """
    g = _load_generator()
    cases = {
        "under_title": (["כותרת", "=====", ":summary: מתחת לכותרת.", "", "גוף."], [3]),
        "after_label": ([".. _label:", "", ":summary: אחרי תווית.", "", "כותרת", "=====", "", "גוף."], [3]),
        "after_comment": ([".. הערה", "", ":summary: אחרי הערה.", "", "כותרת", "=====", "", "גוף."], [3]),
        "in_body": (["כותרת", "=====", "", "פסקה.", "", "סעיף", "-----", "", ":summary: בגוף.", "", "עוד."], [9]),
        # בלי שורה ריקה בין פסקה לשדה, השדה הוא שורת המשך של הפסקה ומוצג כטקסט
        "glued_to_text": (["פסקה ראשונה", ":summary: דבוק לפסקה.", "", "כותרת", "=====", "", "גוף."], [2]),
    }
    for name, (page, misplaced) in cases.items():
        assert g._declared_summary(page, Path("x.rst")) == "", name
        assert g._misplaced_rst_summaries(page) == misplaced, name

    # עותק שנשאר מתחת לכותרת אחרי שההצהרה עברה לראש הקובץ: ההצהרה נקראת, והעותק מדווח
    both = [":summary: ההצהרה.", "", "כותרת", "=====", ":summary: עותק שנשכח.", "", "גוף."]
    assert g._declared_summary(both, Path("x.rst")) == "ההצהרה."
    assert g._misplaced_rst_summaries(both) == [5]


def test_the_declaration_may_share_its_field_list_and_come_before_any_markup():
    """המיקום התקין: שורות ריקות לפניה, שדה נוסף באותה רשימה, ואחריה תווית, הערה או directive.

    תווית שבאה אחרי ההצהרה נשארת צמודה לכותרת — כך נמדד ב-Sphinx 8.2.3 —
    ולכן זה הסדר בעמודים שיש להם תווית מעל הכותרת. גם הכותרת נמצאת: הבדיקה
    נופלת אם ``_title`` יקרא את שורת השדה, או גוף מוזח של directive, ככותרת.
    """
    g = _load_generator()
    pages = {
        "label": ["", ":orphan:", ":summary: זה כן התקציר.", "", ".. _label:", "",
                  "כותרת", "=====", "", "גוף."],
        "meta": [":summary: זה כן התקציר.", "", ".. meta::", "   :description: תיאור כלשהו",
                 "   :keywords: א, ב", "", "כותרת", "=====", "", "גוף."],
        "comment": [":summary: זה כן התקציר.", "", ".. הערה רב-שורות", "   המשך ההערה", "",
                    "כותרת", "=====", "", "גוף."],
    }
    for name, page in pages.items():
        assert g._declared_summary(page, Path("x.rst")) == "זה כן התקציר.", name
        assert g._misplaced_rst_summaries(page) == [], name
        assert g._title(page, Path("x.rst")) == "כותרת", name


def test_anything_before_the_field_list_means_there_is_no_declaration():
    """כל צורה שקודמת לרשימת השדות — explicit markup, פרוזה, רשימה, טבלה או קו — מבטלת את ההצהרה.

    זה ההיפוך של הבדיקה שהייתה כאן עד אוקטובר 2026, ששאלה אם כל explicit
    markup **מדולג** בדרך אל השדה שמתחת לכותרת. רשימת הצורות נשארה, ובה גם
    ``py:function``: שם directive עם ``:`` פנימי הוא ``Inliner.simplename``
    חוקי (``docutils/parsers/rst/states.py``), וניסוח קודם סיווג אותו לא
    נכון. אין כאן צורה שמותרת, והבדיקה נופלת אם מישהו יחזיר "דילוג על מה
    שקוף" לפני ההצהרה.
    """
    g = _load_generator()

    forms = (
        ".. _label:",
        ".. __: https://example.com",
        ".. הערה חופשית",
        "..",
        ".. הערה עם :: בתוכה",
        ".. meta::",
        ".. raw:: html",
        ".. note:: שים לב",
        ".. py:function:: foo(bar)",
        ".. js:class:: X",
        ".. default-role:: literal",
        ".. role:: hl(literal)",
        ".. index:: מונח",
        ".. toctree::",
        "פסקת פתיחה.",
        "- פריט ברשימה",
        "| טור | טור |",
        "====",
    )
    for form in forms:
        page = [form, "   גוף מוזח", "", ":summary: לא הצהרה.", "", "כותרת", "=====", "", "גוף."]
        assert g._declared_summary(page, Path("x.rst")) == "", form
        assert g._misplaced_rst_summaries(page) == [4], form


def test_a_declared_summary_means_the_page_is_not_a_scaffold():
    """עמוד עם הצהרת תקציר אינו פיגום autodoc, גם בלי פרוזה בגוף.

    רגרסיה: כשהוסרו פסקאות פתיחה שהיו כפילות של ההצהרה, ``docs/modules/index.rst``
    נשאר עם כותרות והוראות ``automodule`` בלבד — ולכן סווג כפיגום ונשר מהמפה
    בשקט. הצהרה היא תוכן שמישהו כתב, וזה בדיוק מה שהמסנן אמור לחפש.
    """
    g = _load_generator()
    scaffold = ["מודולים", "========", "", "חלק", "----", "",
                ".. automodule:: x", "   :members:"]
    assert g._is_autodoc_scaffold(scaffold, Path("x.rst")) is True

    declared = [":summary: תיעוד המודולים הראשיים.", "", "מודולים", "========", "",
                "חלק", "----", "", ".. automodule:: x", "   :members:"]
    assert g._is_autodoc_scaffold(declared, Path("x.rst")) is False


def test_scaffold_detection_handles_a_multiline_directive_first():
    """עמוד פיגום שנפתח ב-directive רב-שורות עדיין מזוהה כפיגום."""
    g = _load_generator()
    page = [".. meta::", "   :description: תיאור", "", "מודולים", "========", "",
            ".. automodule:: x", "   :members:"]
    assert g._is_autodoc_scaffold(page, Path("x.rst")) is True


def test_no_rst_page_has_a_summary_away_from_the_top_of_the_file():
    """אף עמוד ``.rst`` בריפו אינו מחזיק ``:summary:`` במקום שבו הוא מוצג או שובר תווית.

    זה השומר על הכלל שההסבר ליד ``_SUMMARY_FIELD_RE`` במחולל מפרט: ההצהרה
    היא רשימת השדות שפותחת את הקובץ. שדה מתחת לכותרת — ההרגל עד אוקטובר
    2026 — היה מוצג שוב בעמוד, ומשם בכפתור "העתק", בייצוא ובכרטיסי החיפוש;
    שדה אחרי תווית בראש הקובץ היה שובר אותה. Sphinx לא מתריע על אף אחד מהם
    (נמדד ב-8.2.3), ולכן הבדיקה כאן ולא בבניית האתר.
    """
    g = _load_generator()
    pages = sorted((ROOT / "docs").rglob("*.rst"))
    declared = [p for p in pages if g._rst_field_summary(g._read(p))]
    # שומר אי-ריקנות: בלעדיו הבדיקה הייתה עוברת גם על סריקה שלא מצאה אף הצהרה
    assert len(declared) > 100, len(declared)

    offenders = [
        f"{p.relative_to(ROOT).as_posix()}:{line_no}"
        for p in pages
        for line_no in g._misplaced_rst_summaries(g._read(p))
    ]
    assert not offenders, (
        "שדה :summary: שלא בראש הקובץ: הוא יוצג בעמוד, ואם הוא אחרי תווית הוא ישבור אותה. "
        "העבירו אותו לשורה הראשונה של הקובץ, לפני הכותרת ולפני תוויות "
        "(docs/doc-authoring.rst, \"הצהרת תקציר בראש העמוד\"):\n  " + "\n  ".join(offenders)
    )

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
    """שדה ``:summary:`` מתחת לכותרת נקרא, כולל שורות המשך מוזחות.

    המיקום הוא מה ש-``docutils`` מקדם ל-``<docinfo>``: field list שבא
    ראשון אחרי כותרת המסמך (``transforms/frontmatter.py``, ``DocInfo``).
    """
    g = _load_generator()
    page = ["כותרת העמוד", "===========", ":summary: התקציר המוצהר של העמוד.", "", "גוף."]
    assert g._declared_summary(page, Path("x.rst")) == "התקציר המוצהר של העמוד."

    wrapped = ["כותרת העמוד", "===========",
               ":summary: שורה ראשונה של התקציר", "   והמשך מוזח שלה.", "", "גוף."]
    assert g._declared_summary(wrapped, Path("x.rst")) == "שורה ראשונה של התקציר והמשך מוזח שלה."


def test_declared_summary_ignores_an_indented_field():
    """``:summary:`` מוזח אינו הצהרה — הוא תוכן של בלוק אחר.

    עמודה 0 בדיוק היא מה ש-``docutils`` מפרש כשדה ברמת המסמך; בלי הכלל
    הזה שורה בתוך ``.. note::`` או בתוך בלוק קוד הייתה נחשבת תקציר.
    """
    g = _load_generator()
    page = ["כותרת", "=====", "", ".. note::", "   :summary: לא הצהרה.", "", "גוף."]
    assert g._declared_summary(page, Path("x.rst")) == ""


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
    page = ["כותרת", "=====", f":summary: {long}", "", "גוף."]
    got = g._declared_summary(page, Path("x.rst"))
    assert len(got) <= g.SUMMARY_CAP, len(got)
    assert got.endswith("…")


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


def test_summary_field_must_sit_in_the_docinfo_position():
    """``:summary:`` אחרי פרוזה או בתוך סעיף אינו התקציר של המסמך.

    ``docutils`` מקדם ל-``<docinfo>`` רק field list שבא ראשון אחרי כותרת
    המסמך (``transforms/frontmatter.py``, ``DocInfo``). שדה מאוחר יותר
    מרונדר כשדה מקומי בתוך הסעיף שלו, ולכן הצגתו כתקציר העמוד סותרת את
    מה שהעמוד עצמו מציג.
    """
    g = _load_generator()

    late = ["כותרת", "=====", "", "פסקה רגילה שפותחת את העמוד.", "",
            "סעיף", "-----", "", ":summary: לא התקציר של המסמך.", "", "עוד."]
    assert g._declared_summary(late, Path("x.rst")) == ""

    after_blank = ["כותרת", "=====", "", "פסקה.", "", ":summary: גם לא.", ""]
    assert g._declared_summary(after_blank, Path("x.rst")) == ""

    # והמיקום התקין ממשיך לעבוד, גם עם יעד לפני הכותרת ועם שדה נוסף
    ok = [".. _label:", "", "כותרת", "=====", ":orphan:",
          ":summary: זה כן התקציר.", "", "גוף."]
    assert g._declared_summary(ok, Path("x.rst")) == "זה כן התקציר."


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

    declared = ["מודולים", "========", ":summary: תיעוד המודולים הראשיים.", "",
                "חלק", "----", "", ".. automodule:: x", "   :members:"]
    assert g._is_autodoc_scaffold(declared, Path("x.rst")) is False

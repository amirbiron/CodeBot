#!/usr/bin/env python3
"""תצלום דטרמיניסטי של כל מה ש-``codekeeper_docs_get_section`` מחזיר על קורפוס RST.

**למה סקריפט ולא טסט עם ערך מקובע.** הראיה שריפקטור לא שינה התנהגות היא
*אפס-דיף*: אותו פלט בדיוק לפני ואחרי. טסט שמקבע digest בקוד היה נשבר בכל
פעם שמישהו עורך עמוד תחת ``docs/`` — כלומר הוא היה מודד את התיעוד ולא את
הפארסר, והיה הופך לרעש שמישהו יעדכן בלי להסתכל. הסקריפט הזה מריץ את אותה
סוללה על שני עצי-קוד ומשווה ביניהם, ולכן הוא תקף גם כשהקורפוס משתנה.

**והקורפוס נמסר כארגומנט בכוונה.** שתי ההרצות חייבות לפרסר את אותם בייטים;
אם כל הרצה תקרא את ``docs/`` של העץ שלה, הבדל בתיעוד בין הענפים היה נראה
בדיוק כמו שינוי התנהגות. ``--corpus`` מצביע על עץ אחד לשתיהן.

**מה הסוללה מכסה** — כל ארבעת מסלולי התשובה של הכלי, ולא רק המסלול המרכזי:

============================  ==================================================
המסלול                        איך הוא נדלק
============================  ==================================================
``mode: toc``                 קריאה בלי ``section``
``mode: section``             כל כותרת בקובץ, עם תת-סקשנים ובלעדיהם
``error: ambiguous_section``  כותרת ששמה חוזר באותו קובץ — נדלק מעצמו
``error: section_not_found``  שאילתה שאינה קיימת, ועוד אחת שנגזרת מכותרת
                              אמיתית כדי ש-``difflib`` יחזיר הצעות בפועל
``truncated``                 ``max_chars`` מינימלי, ואז עמוד שני ב-``next_offset``
============================  ==================================================

**ורשימת השאילתות נרשמת בפלט, לא רק התשובות.** היא נגזרת מה-TOC של אותה
הרצה, ולכן שינוי ב-TOC משנה גם את מה שנשאל — ובלי לרשום אותה, שתי הרצות
שנשאלו שאלות שונות היו יכולות להיראות זהות. הרישום הוא מה שהופך את זה
לראיה ולא להשוואה של שני דברים שאינם אותו דבר.

**סוללה שנייה: שאילתות בצורת מזהה, שנגזרות מהקורפוס עצמו.** ``find_sections``
מתאים גם שאילתה שבנויה כמזהה (``K11``, ``U3``) לכותרת שנפתחת באותו מזהה, ורק
אחרי שהשוויון המלא לא מצא כלום. כל ה-PR נשען על הנחה אחת: **אף כותרת בקורפוס
הזה אינה נפתחת במזהה**, ולכן הענף אינו נדלק כאן.

**והשאלות נגזרות מהכותרות של כל קובץ, ולא מרשימה קבועה — וזה תיקון.** הגרסה
הראשונה שאלה שלוש-עשרה מחרוזות מוקלדות, והדוקסטרינג הצהיר שההרצה מבססת את
ההנחה כולה. זה היה רחב ממה שהכלי מודד: כותרת ``md5 package`` נושאת את המזהה
``md5``, אף פרוב לא שאל עליו, והסקריפט היה יוצא ב-0 ואומר שהכול בסדר. היום
כל קובץ נשאל על המזהים ש**הוא עצמו** נושא, ולכן הסוללה אינה יכולה להחמיץ
צורה שאיש לא ניחש. על הקורפוס של היום זה מייצר אפס שאלות, וזו התשובה הנכונה
— היא מדווחת כמספר ולא כסוללה שרצה בשקט.

הרשומות נרשמות ב**היטל מצומצם** (שאילתה, סוג התשובה, מה הותאם, ההצעות) ולא
כתשובה מלאה, כי תשובת ``section_not_found`` נושאת את ה-TOC כולו ועותקים כאלה
לכל קובץ היו מנפחים את התצלום בלי להוסיף מידע.

**ובקרות שליליות אינן כאן.** צורות כמעט-מזהה (``K``, ``11``, ``K-11``) יכולות
להחזיר רק "לא נמצא" על כל קובץ בקורפוס, כלומר אלף רשומות שאינן מסוגלות לומר
דבר. הן חיות ב-``tests/test_doc_sections.py`` כטסט יחידה, שם הן באמת נבדקות.

**ושתי בקרות סינתטיות, שאינן נכנסות ל-JSONL בכוונה.** בקרה אינה יכולה לרוץ
על הקורפוס, כי שם אין אף מזהה — סוללה שכל תשובותיה "לא נמצא" אינה מבדילה בין
"הענף כבוי" לבין "הפרובים לא מסוגלים לראות אותו". לכן שתי כותרות סינתטיות
נשאלות בסוף ההרצה ונדפסות בדוח: ``K1`` על קובץ שיש בו ``K10.`` בלבד (חייב
לא להתאים — מבחן הגבול), ו-``P3.`` על כותרת ``P3 — טקסט`` (חייב להתאים —
גבול רווח ונקודה בשאילתה). הן בדוח ולא בקובץ כדי שה-``diff`` יישאר בינארי:
**קובץ הקורפוס חייב להיות זהה, והבקרות חייבות להשתנות בין שתי ההרצות.**

**קוד היציאה אומר דבר אחד:** ההנחות שהסקריפט מקודד אינן מתארות את העץ הזה.
הוא ``1`` כש**בקרה אינה תואמת** את ערך ההשוואה שלה, או כש**הקורפוס מניב ולו
מזהה אחד** — כלומר כשההנחה שכל השינוי נשען עליה נשברה. שתיהן היו טענות
מודפסות בלבד קודם, כלומר בדיקות שלא היו מסוגלות ליפול. ה-JSONL נכתב בכל
מקרה, כדי שה-``diff`` יהיה אפשרי גם בריצה שנכשלה.

**וההנחה עצמה מוגנת גם בלי הסקריפט הזה**, ב-
``tests/test_docs_headings_carry_no_identifier.py`` — הוא סורק את כל קובצי
ה-RST ונופל על כותרת שנפתחת במזהה. הסקריפט מוסיף עליו את **התצלום**: כשההנחה
תישבר, ה-JSONL יראה מה בדיוק הכלי מחזיר על אותה כותרת, ולא רק שהיא קיימת.

.. warning::

   **על עץ שאין בו את התאמת המזהה, הבקרה השנייה אמורה לא להתאים, והסקריפט
   אמור לצאת ב-1.** זו אינה תקלה — זו ההוכחה שהפרובים אינם עיוורים. לכן אל
   תחברו את שתי ההרצות ב-``&&``: הריצו כל אחת בנפרד, והשוו את הקבצים אחר
   כך. הבקרה הראשונה, לעומת זאת, היא אינווריאנט אמיתי ותואמת בשני העצים.

שימוש::

    python scripts/docs_section_zero_diff.py --corpus docs --out before.jsonl
    # ... הריפקטור ...
    python scripts/docs_section_zero_diff.py --corpus docs --out after.jsonl
    diff before.jsonl after.jsonl && echo "אפס דיף"

**זהו כלי פיתוח ידני, והוא אינו רץ ב-CI — בכוונה.** הערך שלו הוא ה**דיף בין
שני עצים**, ו-CI אינו יכול לייצר אותו בהרצה אחת. גרוע מזה: ההרצה על עץ הבסיס
**אמורה** לצאת ב-1, כי הבקרה השנייה אינה מתהפכת שם — כלומר CI היה מדווח אדום
בדיוק על הדבר שמוכיח שהכלי עובד. מה ש-CI כן שומר עליו הוא ההנחה, דרך הטסט
שנקרא למעלה בשמו.

**מי מריץ:** מי שנוגע ב-``find_sections``, ב-``suggest`` או ב-``normalize_title``
ב-``services/doc_sections.py`` — לפני הקומיט, בנוהל שתי ההרצות שלמטה. אין
מנגנון שיזכיר, וזה מה שהדוקסטרינג הזה מחליף.

הסקריפט אינו כותב לשום מקום מלבד ``--out``, ואינו מוחק דבר.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp_server import docs_handlers  # noqa: E402
from services import doc_sections  # noqa: E402

# שאילתה שאין ולא יכולה להיות לה כותרת תואמת בקורפוס — כדי לקבע את מסלול
# ה-not-found גם בקובץ שכל כותרת בו נמצאת.
_ABSENT_QUERY = "זזזז לא קיימת זזזז"

#: סוגי תשובה שמשמעותם "הענף מצא משהו" — אלה שנספרים בדוח.
_RESOLVED = frozenset({"section", "ambiguous_section"})

#: שתי הבקרות הסינתטיות: שם, טקסט RST, השאילתה, **ערך ההשוואה**, והנימוק.
#: הן מודדות את מבחן הגבול עצמו ולא את צורת השאילתה, ולכן הן נחוצות — על
#: הקורפוס שתיהן היו מחזירות "לא נמצא", משתי סיבות שונות לגמרי.
#:
#: **ערך ההשוואה נפרד מהפרוזה בכוונה.** בגרסה הראשונה היה כאן שדה אחד,
#: משפט אנושי, והלולאה רק **הדפיסה** אותו לצד מה שהתקבל. כלומר בקרה
#: שתפסיק להתהפך — פרובים שיתעוורו — הייתה מדפיסה שורה שנראית כמעט נכונה,
#: וסומכת על כך שאדם ישים לב. בדיקה שאינה מסוגלת ליפול אינה ראיה, וזה כל
#: מה שהבקרות האלה קיימות בשבילו.
_CONTROLS = (
    ("גבול: K1 מול קובץ שיש בו K10 בלבד",
     "Doc\n===\n\nK10. עשירי\n----------\n\nגוף\n",
     "K1",
     "section_not_found",
     "קידומת אינה מזהה — ואינווריאנט אמיתי, תקף גם לפני השינוי וגם אחריו"),
    ("גבול: P3. עם נקודה מול כותרת P3 — טקסט",
     "Doc\n===\n\nP3 — טקסט\n---------\n\nגוף\n",
     "P3.",
     "section",
     "הגבול הוא רווח, והנקודה בשאילתה אופציונלית — הבקרה שחייבת להתהפך"),
)


class _TextBackend:
    """מחזיר טקסט RST נתון — לבקרות הסינתטיות בלבד, לא לקורפוס."""

    def __init__(self, text: str) -> None:
        self._text = text

    def get_file(self, *, repo: str, path: str, ref: str | None = None,
                 lines: Any = None) -> dict[str, Any]:
        return {"ok": True, "status": "ok",
                "file": {"path": path, "ref": "HEAD",
                         "resolved_commit": "fixed-for-snapshot"},
                "content": self._text}


def _outcome(response: dict[str, Any]) -> str:
    """סוג התשובה בשם אחד: ``mode`` בהצלחה, ``error`` בסירוב."""
    return str(response.get("error") or response.get("mode"))


def _matched_titles(response: dict[str, Any]) -> list[str]:
    """מה שהתשובה הצביעה עליו — סעיף יחיד, מועמדים, או כלום."""
    if response.get("mode") == "section":
        return [response.get("section")]
    return [c["title"] for c in response.get("candidates") or []]


def _corpus_identifiers(backend: Any, doc_path: str) -> list[str]:
    """המזהים שהקובץ הזה נושא בפועל, בסדר הופעתם ובלי כפילויות.

    **הפירוק נעשה בפונקציה של הייצור ולא בעותק שלה כאן.** מזהה הוא צורה
    שמוגדרת במקום אחד — ``_IDENTIFIER_TITLE_RE`` — ורגקס שני שמתאר אותה
    צורה בסקריפט הוא בדיוק ``duplicate-rule-second-copy``: ביום שהצורה
    תורחב, הסקריפט ימשיך לשאול לפי הצורה הישנה ויצהיר שהכול בסדר. השם
    פרטי, וזו הסיבה שהוא נקרא בכל זאת: הסקריפט חייב לשאול **בדיוק** מה
    שהייצור מפרסר.
    """
    toc = docs_handlers.docs_get_section(backend, path=doc_path).get("toc") or []
    found: list[str] = []
    seen: set[str] = set()
    for item in toc:
        identifier = doc_sections._leading_identifier(item.get("title") or "")
        if identifier is None:
            continue
        key = identifier.casefold()
        if key not in seen:
            seen.add(key)
            found.append(identifier)
    return found


def _identifier_probes(backend: Any, doc_path: str,
                       probes: list[str]) -> Iterator[dict[str, Any]]:
    """הסוללה השנייה, בהיטל מצומצם.

    ההצעות נכנסות לרשומה כי ``suggest`` משנה מסלול על אותו תנאי בדיוק —
    שאילתה בצורת מזהה — ובלעדיהן שינוי בענף ההוא היה עובר כאן בלי סימן.
    """
    for probe in probes:
        resp = docs_handlers.docs_get_section(backend, path=doc_path, section=probe)
        yield {
            "identifier_probe": {"path": doc_path, "section": probe},
            "outcome": _outcome(resp),
            "matched": _matched_titles(resp),
            "suggestions": resp.get("suggestions") or [],
        }


class _CorpusBackend:
    """מחקה את החוזה של ``RepoBackend.get_file`` מול עץ קבצים נתון.

    השדות שמוחזרים הם בדיוק אלה ש-``docs_get_section`` קורא: ``ok``,
    ``status``, ``content`` ו-``file``. ``resolved_commit`` קבוע ולא נגזר
    מגיט — הוא נכנס לתשובה כמו שהוא, וערך שמשתנה בין ההרצות היה מייצר דיף
    שאינו התנהגות.
    """

    def __init__(self, corpus_root: Path) -> None:
        self._root = corpus_root

    def get_file(self, *, repo: str, path: str, ref: str | None = None,
                 lines: Any = None) -> dict[str, Any]:
        # ``path`` מגיע מנורמל כ-``docs/<name>.rst``; הקורפוס הוא אותה תיקייה.
        rel = path[len("docs/"):] if path.startswith("docs/") else path
        f = self._root / rel
        if not f.is_file():
            return {"ok": False, "error": "not_found"}
        text = f.read_text(encoding="utf-8")
        return {
            "ok": True,
            "status": "ok",
            "file": {"path": path, "ref": ref or "refs/heads/main",
                     "resolved_commit": "fixed-for-snapshot"},
            "content": text,
        }


def _call(backend: Any, **kwargs: Any) -> dict[str, Any]:
    """קריאה אחת לכלי, עם השאילתה עצמה שמורה לצד התשובה."""
    out = docs_handlers.docs_get_section(backend, **kwargs)
    return {"query": dict(sorted(kwargs.items())), "response": out}


def _normalization_variants(title: str) -> list[str]:
    """צורות של אותה כותרת שרק ``normalize_title`` אמור להשוות אליה.

    **בלי אלה הסוללה עיוורת ל-``normalize_title`` לגמרי, וזה נמדד ולא הונח.**
    הגרסה הראשונה שאלה כל כותרת בדיוק כפי שה-TOC החזיר אותה — ואז שני הצדדים
    של ההשוואה עוברים את אותו נרמול, כך ש**ביטול ה-``casefold`` לא שינה את
    ה-digest בכלל**. כלומר מוטציה אמיתית בפונקציה עברה את ההוכחה בשקט, וזה
    הופך אותה מראיה להרגשה.

    שלוש הצורות מכסות את שלושת הכללים שהפונקציה מיישמת, כל אחת את שלה:
    ``swapcase`` את ה-``casefold``, הרווחים את כיווץ הרווחים ואת ה-``strip``,
    והמקף הארוך את איחוד המקפים.
    """
    variants = [
        title.swapcase(),
        f"  {re.sub(r'[ ]+', '   ', title)}  ",
        title.replace("-", "—"),
    ]
    # צורה שיוצאת זהה למקור אינה בודקת כלום, ורק מנפחת את התצלום.
    return [v for v in dict.fromkeys(variants) if v != title]


def _battery(backend: Any, doc_path: str) -> Iterator[dict[str, Any]]:
    """כל הקריאות לקובץ אחד, בסדר קבוע."""
    toc_rec = _call(backend, path=doc_path)
    yield toc_rec

    toc = toc_rec["response"].get("toc") or []
    titles = [item["title"] for item in toc]

    for title in titles:
        yield _call(backend, path=doc_path, section=title, include_subsections=True)
        yield _call(backend, path=doc_path, section=title, include_subsections=False)
        for variant in _normalization_variants(title):
            yield _call(backend, path=doc_path, section=variant)

    # not-found: אחת שלא קיימת בכלל, ואחת שנגזרת מכותרת אמיתית כדי
    # ש-``suggest`` יחזיר משהו ולא רשימה ריקה.
    yield _call(backend, path=doc_path, section=_ABSENT_QUERY)
    if titles and len(titles[0]) > 3:
        yield _call(backend, path=doc_path, section=titles[0][:-2])

    # truncation: העמוד הראשון בתקרה המינימלית, ואז העמוד שאחריו.
    if titles:
        first = _call(backend, path=doc_path, section=titles[0],
                      max_chars=docs_handlers.MAX_CHARS_MIN)
        yield first
        nxt = first["response"].get("next_offset")
        if nxt:
            yield _call(backend, path=doc_path, section=titles[0],
                        max_chars=docs_handlers.MAX_CHARS_MIN, offset=nxt)


def _edge_inputs(backend: Any) -> Iterator[dict[str, Any]]:
    """מסלולי הדחייה שאינם תלויים בקובץ — פעם אחת לכל ההרצה."""
    yield _call(backend, path="")
    yield _call(backend, path="../etc/passwd")
    yield _call(backend, path="webapp/app")
    yield _call(backend, path="environment-variables", repo="not-in-allowlist")
    yield _call(backend, path="does-not-exist-at-all")


def main(argv: list[str] | None = None) -> int:
    """נקודת הכניסה. ``argv`` כרשימה ולא ``sys.argv``, כדי שאפשר יהיה לבדוק אותה.

    זו המוסכמה בריפו — ``scripts/compare_md_parser_to_cmark.py`` בנוי כך,
    ו-``tests/test_md_parser.py`` מריץ אותו עם ``main([str(corpus)])``. אין
    באף טסט בריפו ``monkeypatch`` על ``sys.argv``, וזה לא במקרה: שער שאי
    אפשר להריץ מטסט הוא שער שאיש לא בודק.
    """
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=str(_ROOT / "docs"),
                    help="תיקיית קובצי ה-RST. אותה תיקייה לשתי ההרצות.")
    ap.add_argument("--out", required=True, help="קובץ הפלט (JSONL).")
    args = ap.parse_args(argv)

    corpus = Path(args.corpus).resolve()
    if not corpus.is_dir():
        print(f"אין תיקיית קורפוס: {corpus}", file=sys.stderr)
        return 2

    backend = _CorpusBackend(corpus)
    files = sorted(p.relative_to(corpus).as_posix()
                   for p in corpus.rglob("*.rst"))
    if not files:
        print(f"אין קובצי .rst תחת {corpus}", file=sys.stderr)
        return 2

    digest = hashlib.sha256()
    tally: Counter[str] = Counter()
    records = 0
    probes = 0
    lit: list[dict[str, Any]] = []      # שאילתות מזהה שהדליקו את הענף בקורפוס
    carried: list[dict[str, str]] = []  # כותרות בקורפוס שנושאות מזהה — ההנחה שנשברת

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in _edge_inputs(backend):
            line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
            fh.write(line + "\n")
            digest.update(line.encode("utf-8"))
            records += 1
            tally[str(rec["response"].get("error") or rec["response"].get("mode"))] += 1

        for rel in files:
            # הנתיב המלא ולא ה-slug הקצר: ``_resolve_docs_path`` מוסיף את
            # התחילית ``docs/`` רק כשאין ב-קלט ``/`` בכלל, ולכן קובץ בתת-תיקייה
            # (``observability/error_codes``) היה נדחה כ-``missing_path``.
            for rec in _battery(backend, f"docs/{rel}"):
                line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
                fh.write(line + "\n")
                digest.update(line.encode("utf-8"))
                records += 1
                resp = rec["response"]
                tally[str(resp.get("error") or resp.get("mode"))] += 1

            identifiers = _corpus_identifiers(backend, f"docs/{rel}")
            carried.extend({"path": f"docs/{rel}", "identifier": i} for i in identifiers)
            for rec in _identifier_probes(backend, f"docs/{rel}", identifiers):
                line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
                fh.write(line + "\n")
                digest.update(line.encode("utf-8"))
                records += 1
                probes += 1
                if rec["outcome"] in _RESOLVED:
                    lit.append(rec["identifier_probe"] | {"outcome": rec["outcome"]})

    print(f"קבצים:   {len(files)}")
    print(f"רשומות:  {records}")
    print(f"sha256:  {digest.hexdigest()}")
    print("פילוח מסלולי התשובה:")
    for key, count in sorted(tally.items()):
        print(f"  {key}: {count}")

    print(f"\nמזהים שנמצאו בקורפוס: {len(carried)} (מצופה: 0)")
    print(f"שאילתות שנגזרו מהם: {probes} — מהן נפתרו: {len(lit)}")
    for hit in carried[:20]:
        print(f"  {hit['path']} · כותרת שנפתחת במזהה {hit['identifier']!r}")

    # הבקרות מודפסות ואינן נכנסות ל-JSONL: ``diff`` על קובץ הקורפוס חייב
    # להיות ריק, ודווקא השורות האלה חייבות להשתנות בין שתי ההרצות. אם הן
    # זהות לפני ואחרי — הפרובים עיוורים, וקובץ זהה אינו מוכיח דבר.
    print("\nבקרות סינתטיות (לא ב-JSONL — ראו את ההסבר ב-docstring):")
    failed_controls = []
    for name, text, probe, expected, why in _CONTROLS:
        resp = docs_handlers.docs_get_section(_TextBackend(text), path="control",
                                              section=probe)
        actual = _outcome(resp)
        good = actual == expected
        if not good:
            failed_controls.append((name, expected, actual))
        print(f"  {'תואם' if good else 'לא תואם'}  {name}\n"
              f"    section={probe!r} → {actual} {_matched_titles(resp)}\n"
              f"    מצופה: {expected} — {why}")

    if failed_controls or carried:
        print("\nההנחות שהסקריפט מקודד אינן מתארות את העץ הזה:")
        for name, expected, actual in failed_controls:
            print(f"  בקרה: {name} — מצופה {expected}, התקבל {actual}")
        if carried:
            print(f"  קורפוס: {len(carried)} כותרות נושאות מזהה. ההנחה שכל "
                  f"ההתאמה לפי מזהה נשענת עליה — שאף כותרת כאן אינה נפתחת "
                  f"במזהה — אינה נכונה יותר. זהו שינוי התנהגות ב-RST שצריך "
                  f"להיות מוצהר, לא בדיקה שצריך להסיר.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

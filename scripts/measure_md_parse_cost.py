#!/usr/bin/env python3
"""כמה זיכרון ומעבד עולה פרסור מסמך אחד — המספרים שמאגר הקריאות ומגבלת הקצב של ה-MCP נגזרים מהם.

``mcp_server/server.py`` מגדיר את ``_PARSE_RSS_PER_INPUT_BYTE`` — שיא ה-RSS
שפרסור אחד מוסיף, לכל בית של תקרת הקריאה — ומחלק בו את תקציב הזיכרון של
הקונטיינר כדי לקבוע כמה קריאות רצות במקביל (#3391). ``services/md_parser.py``
מגדיר את ``WORST_CASE_CPU_SECONDS``, שממנו נגזרות מגבלת הקצב והדדליין של
``codekeeper_read_batch``. הסקריפט מודד את שניהם מחדש **לשני הפרסרים**:
``services.md_parser`` (markdown-it-py), שעליו הקבועים נמדדו, ו-
``services.rst_parser``. מריצים אותו כשאחד משניהם משתנה — כולל שדרוג של
``markdown-it-py`` ושינוי של תקרה — במקום להעתיק מספר מזיכרון.

מה נמדד, ולמה דווקא כך:

- **שיא** ה-RSS בזמן הפרסור (``VmHWM`` ב-``/proc/self/status``), ולא מה
  שנשאר אחריו — ``parse_document`` משחרר את הטוקנים ומחזיר ``Document`` קטן
  בהרבה, אבל כמה פרסורים במקביל מחזיקים כל אחד את השיא שלו בו-זמנית.
  ולצידו **זמן המעבד** של הפרסור עצמו (``time.process_time``).
- **``VmHWM`` מאופס רגע לפני הפרסור.** הוא השיא של **כל חיי התהליך**, ולכן
  הילד כותב ``5`` ל-``CLEAR_REFS_PATH`` (``/proc/self/clear_refs``), שמוריד את
  השיא לגובה ה-RSS הנוכחי, ומה שנזקף לפרסור הוא השיא שאחרי האיפוס פחות ה-RSS
  שלפני הפרסור — מה שהפרסור הוסיף (עד הפיגור של מוני הקרנל, למטה). **בלי
  האיפוס** — כך נמדד מ-#3429 ועד #3467 — הבסיס היה הגבוה מבין ה-RSS ושיא-העבר,
  וזיכרון שהתהליך כבר הגיע אליו
  ושחרר (בעיקר החוצץ של קריאת הקובץ) הסתיר את מה שהפרסור הקצה מתחתיו: בקלט
  העוין של 512KB כחצי MB, ותמיד לכיוון "נכנס". ``headroom_kb_before_reset``
  בפלט אומר כמה זה היה בכל מדידה, ו-``headroom_kb_before_parse`` כמה נשאר אחרי
  האיפוס.
- **האיפוס מוכח בכל מדידה, ובקול.** לפניו הקצאה של ``RESET_PROBE_BYTES`` שמשוחררת
  מרימה את השיא בכוונה, כדי שתמיד יהיה מה לאפס; אחריו נבדק שהשיא ירד עד הפיגור של
  מוני הקרנל (``counter_lag_bound_bytes``) מעל ה-RSS. ``/proc/self/clear_refs`` קיים
  רק בלינוקס, והערך ``5`` רק מגרסה 4.0. אם הכתיבה נכשלת, או מתקבלת ולא מאפסת, הילד
  עוצר עם הודעה שאומרת מה קרה, והריצה כולה נעצרת. אין נפילה חזרה לשיטה הישנה: היא
  הייתה מחזירה מספר מוטה בלי לומר זאת.
- **כל מדידת זיכרון רצה על ``LAYOUT_SEEDS`` — 40 סידורי זיכרון — והמספר שלה הוא
  המקסימום.** השיא של אותו פרסור על אותו קלט תלוי בסידור הזיכרון של התהליך רגע
  לפני הפרסור, וזרע הגיבוב (``PYTHONHASHSEED``) הוא אחד הדברים שמשנים אותו: ריצה
  אחת היא הגרלה, והמצב היקר נדיר. השורה נושאת גם את המינימום ואת כל הריצות
  (``peak_bytes_min``, ``peak_bytes_by_layout``), כדי שמי שמריץ פעם אחת יבין איפה
  המספר שלו נופל. גם קלטי המעבד רצים על כל ``LAYOUT_SEEDS``, וזמן המעבד שלהם נשפט על
  ``CPU_REPEATS`` הראשונות (הנימוק ליד הקבוע).
- **המספר שנשפט הוא חסם עליון:** המקסימום ועוד ``counter_lag_bound_bytes``. הקרנל
  רושם את השיא ממונים שכל מעבד מעדכן במנות, ולכן השיא שנרשם יכול לפגר אחרי האמיתי
  — עד ``RSS_COUNTERS × (batch − 1)`` עמודים, ותמיד לכיוון "נכנס". כדי שהפיגור יהיה
  של מעבד אחד, כל ילד מוצמד למעבד אחד מרגע ה-fork (``_pinned``) ובודק בעצמו שהוא
  מוצמד. **ההצמדה היא של המדידה בלבד** — השרת אינו מוצמד לשום מעבד — ואם היא לא
  אפשרית בסביבה, הריצה נעצרת בקול, כמו האיפוס. החסם מכסה את הסידורים שנמדדו, לא
  כל סידור אפשרי.
- דרך ``services.md_parser`` ו-``services.rst_parser`` עצמם. מדידה שרצה
  **כמו הכלי** — בלי ארגומנטים, כלומר על ברירות המחדל של התקרות — מסומנת
  ``as_tool``, ורק היא נכנסת למועמד לקבוע: היא מה שחוט קריאה באמת נושא.
- כל פרסור בתהליך נקי משלו (``python -B``, בתיקייה זמנית), כדי שהמדידה לא
  תכלול זיכרון של פרסור קודם, ועם ``RLIMIT_AS`` כדי שצורה שמתפוצצת תיפול
  ב-``MemoryError`` ולא תפיל את המכונה. הטקסט נקרא עם ``newline=""``, כך
  שהפרסר רואה בדיוק את הבתים שנכתבו — גם ``\\r\\n``.

**הצורות, לכל פרסר:** הקורפוס האמיתי של הריפו (כל הקבצים בסיומת שלו, חתוכים
לתקרת הקריאה ``MAX_FILE_SIZE_FOR_DISPLAY``); המסמך הצפוף ביותר בו משוכפל עד
התקרה; וצורה עוינת **בלי אף תקרה** (Markdown: שורות-תבליט בודדות, RST: כותרת
בת תו אחד בכל שורה) — הגבול של הפרסר עצמו, מה שהתקרות חוסכות, ולא מה שהכלי
מגיש. ל-RST נמדד גם מסלול ה-outline של ``codekeeper_get_repo_file``: המסמך
הצפוף ביותר משוכפל עד ``RANGE_READ_MAX_BYTES`` ומפורסר עם ``max_sections`` של
``MAX_SYMBOLS``, כי זו ההחזקה הגדולה ביותר שחוט קריאה נושא היום.

**ול-Markdown, מאז #3391, גם הקלט העוין כמו שהכלי מקבל אותו:** כל הצורות של
``HOSTILE_SHAPES`` בגודל הגדול ביותר שהכלי עוד מפרסר (``fit_to_the_tool``: תקרת
הקריאה בבתים ותקרת השורות), על ברירות המחדל של ``MAX_LINES`` ו-``MAX_TOKENS``; הקלט
המשולב שהוא הגרוע בזיכרון (``worst_memory_input``); והקלטים הגרועים במעבד
(``CPU_SHAPES``), שהמעבד שלהם נשפט על ``CPU_REPEATS`` ריצות — המעבד רועש, והמספר הוא
המקסימום.
התקרות הן מה שהופך את העוין לתקציבי, ולכן המועמד לקבוע הוא הגבוה מבין **כל**
המדידות שרצו כמו הכלי, בבתים לכל בית של תקרת הקריאה. גם הקורפוס והמסמך הצפוף
נחתכים כך — אחרת הם היו נדחים בתקרת השורות, ונמדד סירוב במקום פרסור.

**פסק הדין בשורה האחרונה**, והוא קוד היציאה (``passed``): 0 כשכל מדידה שרצה
כמו הכלי באמת מדדה פרסור (``MEASURED_OUTCOMES`` — לא סירוב לפני הפרסור, לא
``MemoryError``, ולא תוצאה ששונה בין הסידורים), **וגם** כל מדידה כזו רצה על כל
``LAYOUT_SEEDS``, **וגם** החסם העליון של המכריעה נכנס ב-``_PARSE_COST_BYTES``
(כלומר המועמד אינו עובר את ``_PARSE_RSS_PER_INPUT_BYTE``), **וגם** זמן המעבד הגבוה
אינו עובר את ``WORST_CASE_CPU_SECONDS``; 1 כשאחד מהם נשבר. כשהמדידות תקינות וקבוע
נשבר, הטענות שנגזרות ממנו (רוחב המאגר, מגבלת הקצב, הדדליין) צריכות חשבון חדש
לפני שמשנים משהו. זמן מעבד תלוי במכונה, ולכן השורה נושאת את שני המספרים.

**``--doubling`` — בדיקת ההכפלה.** כל צורה ב-``HOSTILE_SHAPES``, **בלי אף תקרה**,
בשלושה גדלים שכל אחד כפול מקודמו (``DOUBLING_SIZES``; לטבלאות מעל תקרת התאים
גדלים קטנים יותר, ``TABLE_DOUBLING_SIZES``, כי כבר ב-128KB הן עוברות 3GB), כל אחד
בתהליך נקי, מוצמד ומאופס כמו במדידה הרגילה — אבל על סידור אחד (זרע 0) ולא על
``LAYOUT_SEEDS``: כאן נשפט יחס בין שני גדלים מול ``SUPERLINEAR_GROWTH``, וריבועי הוא
פי ארבעה, הרבה מעבר לפיזור בין סידורים. בפרסר ליניארי העלות לבית קלט נשארת
קבועה כשהקלט גדל; עלות לבית שגדלה בין הגודל הקטן לגדול יותר מ-
``SUPERLINEAR_GROWTH``, ``MemoryError``, או חריגה
מהזמן, מסומנים ``superlinear``, וקוד היציאה הוא 1. משאב שהמדידה שלו מתחת לרצפת
הרעש שלו (``MEMORY_NOISE_FLOOR_BYTES``, ``CPU_NOISE_FLOOR_SECONDS``) אינו נבדק
לגדילה, והגדילה שלו בשורה היא ``None``. זו הבדיקה שהייתה תופסת מראש את הריבועיות
של הגדרות הקישור ב-markdown-it-py 3.0.0 (upstream #367 — 105 שניות על 8,000
הגדרות), ושדרוג הבא של הפרסר מריץ אותה.

הרצה מהשורש של הריפו::

    python scripts/measure_md_parse_cost.py
    python scripts/measure_md_parse_cost.py --doubling

הפלט: שורת JSON לכל מדידה ב-stdout, שורת ``skipped`` ב-stderr לכל קובץ שאינו
UTF-8, ובסוף שורת סיכום. אם אין בריפו אף קובץ בסיומת המבוקשת בגודל
``MIN_DOC_BYTES`` ומעלה, הסקריפט יוצא עם הודעה שאומרת זאת.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import mmap
import os
import pathlib
import statistics
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Iterator, Sequence

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from services.git_mirror_service import MAX_FILE_SIZE_FOR_DISPLAY  # noqa: E402

# חיתוך לתקרה בבתים על גבול תו — אותה פונקציה שהכלים עצמם משתמשים בה, ולא
# עותק מקומי (יש כבר שלושה בריפו; R6: מאחדים, לא מוסיפים רביעי).
from mcp_server.handlers import clip_to_bytes  # noqa: E402

#: מסמכים קטנים מזה אינם מייצגים — צפיפות של קובץ בן שורה אחת היא רעש.
MIN_DOC_BYTES = 2_000
_SKIP_PARTS = {"node_modules", ".git", "_build", "venv", ".venv"}

#: תקרת מרחב הכתובות של תהליך מדידה. צורה בלי תקרות יכולה לעבור אותה —
#: טבלאות מעל תקרת התאים הגיעו לשם כבר ב-128KB — ואז היא נופלת ב-``MemoryError``
#: שנרשם כתוצאה, במקום לדחוק את כל המכונה.
ADDRESS_SPACE_BYTES = 3 * 1024**3

#: כמה שניות מותר לתהליך מדידה אחד. פרסור ריבועי חורג ממנה, וזה נרשם כתוצאה.
CHILD_TIMEOUT_SECONDS = 600

#: הקובץ שכתיבת ``5`` אליו מאפסת את ``VmHWM`` לגובה ה-RSS הנוכחי. ``proc_pid_clear_refs(5)``:
#: "Reset the peak resident set size ("high water mark") to the process's current
#: resident set size value", מאז לינוקס 4.0, וכתיב רק לבעלים של התהליך. קבוע ולא
#: מחרוזת בתוך הילד, כדי שטסט יוכל להפנות אותו לנתיב שאינו קיים או לקובץ רגיל — ולוודא
#: שהסקריפט עוצר.
CLEAR_REFS_PATH = "/proc/self/clear_refs"

#: ה-probe שלפני האיפוס: 8MiB אנונימיים ב-``mmap``, שנוגעים בכל עמוד שלהם ומשחררים,
#: כך שהשיא עולה מעל ה-RSS לפני כל איפוס. בלעדיו, בקלט שאין לפניו headroom טבעי
#: (בכיול של 2026-09-27: אפס ב-128KB וב-256KB, 372–496KB בקלט הגרוע), קרנל שמתעלם
#: מהכתיבה היה נראה בדיוק כמו קרנל שמכבד אותה. ``mmap`` ולא ``bytearray``: הקצאה גדולה
#: דרך ``malloc`` ששוחררה מזיזה את סף ה-mmap של glibc ("when blocks larger than the
#: current threshold ... are freed, the threshold is adjusted upward to the size of
#: the freed block", ``mallopt(3)``, ``M_MMAP_THRESHOLD``), ואז הקצאות גדולות של
#: הפרסור היו נוחתות בערימה במקום ב-mmap — פרסור אחר מזה שבשרת. נבדק על glibc 2.39:
#: אחרי ``bytearray`` של 8MiB הקצאה של 2MiB נוחתת בערימה, ואחרי ה-probe הזה ב-mmap,
#: כמו בלי probe בכלל. חצי ממנו חייב להיות מעל ``counter_lag_bound_bytes``: איפוס
#: שקרה משאיר עד הפיגור של המונים, ואיפוס שלא קרה משאיר לפחות חצי probe — ורק כשיש
#: פער בין השניים אפשר להבדיל ביניהם (``peak_cost`` עוצר בקול אם אין).
RESET_PROBE_BYTES = 8 * 1024 * 1024

#: משתנה הסביבה שקובע לפייתון את זרע הגיבוב של ``str``/``bytes``: מספר שלם בין 0
#: ל-4,294,967,295, ו-0 מכבה את האקראיות (``PYTHONHASHSEED`` ב-docs.python.org, 3.11).
HASH_SEED_ENV = "PYTHONHASHSEED"

#: **מדיניות, לא קסם:** כל מדידת זיכרון רצה פעם אחת לכל זרע כאן — ``PYTHONHASHSEED``
#: מ-0 עד 39 — והמספר שלה הוא המקסימום. למה בכלל: השיא של אותו פרסור, על אותו קלט,
#: תלוי בסידור הזיכרון של התהליך רגע לפני הפרסור (אילו חורים פנויים יש בערימה ואיפה
#: נוחתות ההקצאות הגדולות), וזרע הגיבוב הוא אחד הדברים שמשנים אותו. ב-2026-09-27, בכל
#: הריצות עם האיפוס, השיא של הקלט הגרוע נע בין 34,004,992 ל-34,959,360 בתים (92.2%–94.8%
#: מ-``_PARSE_COST_BYTES``), בשני מצבים עיקריים — ו**איזה מהם שכיח תלוי בתוכנית הילד
#: עצמה**: בגרסה מוקדמת שלה 36 מ-40 הזרעים נפלו ב-92.5%–92.9% וארבעה ב-94.5%, ובזו
#: שכאן 39 נפלו ב-93.6%–94.3% ואחד ב-92.7%. מי שמריץ פעם אחת ומקבל מספר נמוך מהמתועד
#: פגש סידור, לא שינוי בקוד. למה 40 ולא 10: מצב שמופיע בעשירית מהסידורים חומק מעשר
#: ריצות ביותר משליש מהפעמים (0.9 בחזקת 10), ומארבעים בפחות מ-2% (0.9 בחזקת 40). זרעים
#: קבועים ולא אקראיים, כדי שהרצה חוזרת על אותו קוד תמדוד את אותם סידורים. גם כך זה
#: מדגם, לא כל הסידורים האפשריים — ולכן פסק הדין משווה חסם עליון ולא את המקסימום
#: לבדו (``counter_lag_bound_bytes``).
LAYOUT_SEEDS = range(40)

#: כמה מונים הקרנל מחבר כשהוא קורא את ה-RSS לשיא: ``get_mm_rss`` = קבצים + אנונימי +
#: זיכרון משותף (``include/linux/mm.h``), כל אחד ``percpu_counter`` נפרד.
RSS_COUNTERS = 3

#: הרצפה של ``percpu_counter_batch``: ``max(32, nr*2)`` כש-``nr`` הוא מספר המעבדים
#: המחוברים (``compute_batch_value`` ב-``lib/percpu_counter.c``).
PERCPU_BATCH_FLOOR = 32

#: שני הפרסרים שהמאגר צריך לדעת את עלותם: השם ב-``services``, הסיומת שהכלי
#: מגיש דרכו, טקסט חימום קטן, והצורה העוינת של כל אחד.
PARSERS = {
    "md": {
        "module": "md_parser",
        "suffix": ".md",
        "warm": "# warm\n\ntext\n",
        "hostile_unit": "- item\n",
    },
    "rst": {
        "module": "rst_parser",
        "suffix": ".rst",
        "warm": "Warm\n====\n\ntext\n",
        "hostile_unit": "a\n=\n\n",
    },
}

#: מה מכבה בכל פרסר את **כל** התקרות שלו — הארגומנטים של המדידה בלי תקרות. מילון
#: נפרד ולא עוד שדה ב-``PARSERS``, כדי שכל ערכי ``PARSERS`` יישארו מחרוזות.
UNCAPPED: dict[str, dict[str, None]] = {
    "md": {"max_sections": None, "max_lines": None, "max_tokens": None},
    "rst": {"max_sections": None},
}

_CHILD = textwrap.dedent(
    """
    import json, mmap, os, resource, sys, time
    # ההצמדה נעשתה לפני ה-fork (``_pinned``); כאן קוראים את המצב, לא מניחים אותו —
    # ילד שרץ על כמה מעבדים הוא ילד שהפיגור של המונה שלו אינו חסום.
    if os.sched_getaffinity(0) != {{{cpu}}}:
        raise SystemExit(
            "the measuring child is not pinned to CPU {cpu} (affinity "
            + str(sorted(os.sched_getaffinity(0))) + "); refusing to measure")
    resource.setrlimit(resource.RLIMIT_AS, ({address_space}, {address_space}))
    sys.path.insert(0, {repo!r})

    def status(key):
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith(key + ":"):
                    return int(line.split()[1])
        raise SystemExit("no " + key + " in /proc/self/status")

    from services import doc_sections
    from services import {module} as parser

    # ``newline=""``: בלי תרגום של סופי שורות, כדי ש-``\\r\\n`` יגיע לפרסר כמו שנכתב.
    text = open({path!r}, encoding="utf-8", newline="").read()
    parser.parse_document({warm!r})
    # מה שהשיטה הישנה הייתה מפספסת: הזיכרון שהתהליך כבר הגיע אליו ושחרר (בעיקר
    # החוצץ של קריאת הקובץ). נרשם בפלט, ואינו נכנס לשום חישוב.
    headroom_before_reset = status("VmHWM") - status("VmRSS")
    # ה-probe: headroom ידוע, כדי שהאיפוס יוכח בכל ריצה ולא רק כשיש מה לאפס.
    probe = mmap.mmap(-1, {probe_bytes})
    for offset in range(0, len(probe), mmap.PAGESIZE):
        probe[offset] = 1
    probe.close()
    probed = status("VmHWM") - status("VmRSS")
    if probed * 1024 < {probe_bytes} // 2:
        raise SystemExit(
            "the reset probe did not raise VmHWM above VmRSS (" + str(probed)
            + " kB), so the reset cannot be proven; refusing to measure")
    # האיפוס, ובקול: אין נפילה חזרה לשיא מעל שיא-העבר, שמפספס את מה שהפרסור
    # מקצה מתחתיו (כחצי MB בקלט של 512KB) — תמיד לכיוון "נכנס".
    try:
        with open({clear_refs!r}, "w") as f:
            f.write("5")
    except OSError as exc:
        raise SystemExit(
            "cannot reset VmHWM through " + {clear_refs!r} + " (" + str(exc) + "): the peak "
            "would be counted above the process's earlier high-water mark and miss what "
            "the parse allocates below it; refusing to measure") from exc
    rss_before, hwm_before = status("VmRSS"), status("VmHWM")
    # מה שנשאר מעל ה-RSS אחרי איפוס אמיתי הוא לכל היותר הפיגור של מוני הקרנל: האיפוס
    # כותב לשיא ערך משוער, שיכול לצאת גבוה מה-RSS המדויק (ספירת-יתר — הכיוון הבטוח).
    # איפוס שלא קרה משאיר לפחות חצי probe, הרבה מעבר לזה.
    if hwm_before - rss_before > {tolerance_kb}:
        raise SystemExit(
            {clear_refs!r} + " accepted the write but VmHWM was not reset ("
            + str(hwm_before - rss_before) + " kB above VmRSS, more than the kernel counter "
            "lag of {tolerance_kb} kB); refusing to measure")
    outcome, sections, line = "parsed", None, None
    cpu_before = time.process_time()
    # כל ענף כאן הוא **תוצאה** שנרשמת בשורת הפלט, לא בליעה: הסירובים
    # המתועדים של הפרסר, ו-``MemoryError`` מתחת ל-``RLIMIT_AS``. כל חריגה
    # אחרת היא באג, והיא מפילה את התהליך ואת הסקריפט.
    try:
        doc = parser.parse_document(text, **{kwargs!r})
        sections = len(doc.sections)
    except doc_sections.TooManySections as exc:
        outcome, line = "too_many_sections", exc.args[0] if exc.args else None
    except doc_sections.TooManyLines:
        outcome = "too_many_lines"
    except doc_sections.TooManyTokens as exc:
        outcome, line = "too_many_tokens", exc.line
    except MemoryError:
        outcome = "memory_error"
    cpu = time.process_time() - cpu_before
    hwm_after, rss_after = status("VmHWM"), status("VmRSS")
    # הילד רק קורא מהקרנל; מה שנגזר מהקריאות — השיא, העלות לבית — מחושב אצל ההורה
    # (``_from_the_kernel``), שם אפשר לבדוק את הנוסחה בלי תת-תהליך.
    print(json.dumps({{
        "module": {module!r},
        "hash_seed": os.environ.get({hash_seed_env!r}),
        "cpu": sorted(os.sched_getaffinity(0)),
        "input_bytes": len(text.encode("utf-8")),
        "input_lines": text.count("\\n") + 1 if text else 0,
        "outcome": outcome,
        "line": line,
        "sections": sections,
        "headroom_kb_before_reset": headroom_before_reset,
        "reset_probe_kb": probed,
        "rss_kb_before_parse": rss_before,
        "hwm_kb_before_parse": hwm_before,
        "hwm_kb_after_parse": hwm_after,
        "rss_kb_after_parse": rss_after,
        "cpu_seconds": round(cpu, 3),
    }}))
    """
)


def _from_the_kernel(raw: dict) -> dict:
    """שורת הילד, ועוד מה שנגזר מהקריאות שלו: השיא שהפרסור הוסיף, וממנו העלות לבית.

    השיא הוא ``VmHWM`` אחרי הפרסור פחות ה-RSS **שלפני** הפרסור — ולא פחות ``VmHWM``
    שלפניו. אחרי איפוס אמיתי שני אלה נבדלים רק בשארית שהאיפוס משאיר (עד
    ``counter_lag_bound_bytes``), ואז הנוסחה הזאת סופרת את השארית — ספירת-יתר, הכיוון
    הבטוח — ואילו חיסור של ``VmHWM`` שלפני הפרסור היה מוריד אותה מהשיא: ספירת-חסר,
    הכיוון שהסבב הזה בא לסגור. ``headroom_kb_before_parse`` הוא אותה שארית.
    """
    peak = (raw["hwm_kb_after_parse"] - raw["rss_kb_before_parse"]) * 1024
    n = max(1, raw["input_bytes"])
    return {
        **raw,
        "headroom_kb_before_parse": raw["hwm_kb_before_parse"] - raw["rss_kb_before_parse"],
        "peak_bytes": peak,
        "peak_mib": round(peak / 1024 / 1024, 1),
        "peak_bytes_per_input_byte": round(peak / n, 1),
        "retained_bytes_per_input_byte": round(
            (raw["rss_kb_after_parse"] - raw["rss_kb_before_parse"]) * 1024 / n, 1
        ),
    }


def counter_lag_bound_bytes() -> int:
    """בכמה השיא שהקרנל רושם יכול לפגר אחרי השיא האמיתי — מה שמוסיפים למקסימום כדי לקבל חסם עליון.

    הקרנל מעדכן את השיא (``update_hiwater_rss``) מ-``get_mm_rss``, שקורא מכל אחד משלושת
    המונים רק את הערך המשותף (``percpu_counter_read_positive``), בלי מה שכל מעבד עוד
    לא העביר אליו. מעבד מעביר כשהסכום אצלו מגיע ל-``percpu_counter_batch``, כלומר עד
    ``batch − 1`` עמודים לכל מונה נשארים בחוץ (``percpu_counter_add_batch``). ה-RSS
    עצמו נקרא מדויק (``get_mm_counter_sum`` ב-``task_mem``), ולכן הפיגור הוא רק בשיא —
    ותמיד לכיוון "נכנס". הילד מוצמד למעבד אחד מרגע היצירה, אז הפיגור הוא של מעבד אחד:
    ``RSS_COUNTERS × (batch − 1)`` עמודים. המקור: torvalds/linux, ``fs/proc/task_mmu.c``,
    ``include/linux/mm.h``, ``lib/percpu_counter.c``.

    ``os.cpu_count()`` הוא ``sysconf(_SC_NPROCESSORS_ONLN)`` (CPython 3.11) — המעבדים
    המחוברים של המכונה, גם בתוך קונטיינר. בדרך כלל זה המספר הלא נכון לגזור ממנו גודל,
    אבל כאן הוא הנכון: ה-batch של הקרנל נגזר מהמעבדים שהקרנל רואה, לא מהמכסה של
    הקונטיינר. בלי המספר אין חסם, והמדידה נעצרת.
    """
    online = os.cpu_count()
    if not online:
        raise SystemExit(
            "os.cpu_count() is unknown, so the kernel's counter lag cannot be bounded; "
            "refusing to measure"
        )
    batch = max(PERCPU_BATCH_FLOOR, 2 * online)
    return RSS_COUNTERS * (batch - 1) * mmap.PAGESIZE


def _measuring_cpu() -> int:
    """המעבד שכל ילד מדידה רץ עליו: הנמוך מבין המותרים לתהליך. בקול אם אין הצמדה בפלטפורמה."""
    if not hasattr(os, "sched_setaffinity"):
        raise SystemExit(
            "os.sched_setaffinity is not available on this platform, so the measuring child "
            "cannot be pinned to one CPU and the kernel's counter lag is not bounded; "
            "refusing to measure"
        )
    return min(os.sched_getaffinity(0))


@contextlib.contextmanager
def _pinned(cpu: int) -> Iterator[None]:
    """החוט הקורא מוצמד ל-``cpu`` עד שהבלוק נגמר, ואז חוזר למסכה שהייתה לו.

    ילד שנוצר בזמן הזה יורש את ההצמדה מרגע ה-fork, והיא נשמרת גם ב-execve
    (``sched_setaffinity(2)``: "A child created via fork(2) inherits its parent's CPU
    affinity mask. The affinity mask is preserved across an execve(2)."), כך שכל
    חיי הילד — כולל הטעינה של המפרש — עוברים על מעבד אחד. עם pid 0 הקריאה חלה על
    החוט הקורא בלבד, ולכן שאר החוטים של התהליך לא זזים, והחוט עצמו חוזר למסכה שלו.
    זו הצמדה של המדידה בלבד: השרת אינו מוצמד לשום מעבד.
    """
    before = os.sched_getaffinity(0)
    try:
        os.sched_setaffinity(0, {cpu})
    except OSError as exc:
        raise SystemExit(
            f"cannot pin the measuring child to CPU {cpu} ({exc}): without it the kernel's "
            "counter lag is not bounded; refusing to measure"
        ) from exc
    try:
        yield
    finally:
        os.sched_setaffinity(0, before)


def peak_cost(
    path: pathlib.Path,
    workdir: pathlib.Path,
    *,
    parser: str = "md",
    kwargs: dict | None = None,
    seed: int = 0,
) -> dict:
    """פרסור אחד בתהליך נקי; מחזיר את שיא ה-RSS שהוא הוסיף מאז איפוס ``VmHWM``, ואת זמן המעבד שלו.

    הילד רץ עם ``PYTHONHASHSEED=seed`` — סידור זיכרון אחד מתוך ``LAYOUT_SEEDS`` — ומוצמד
    למעבד אחד (``_pinned``). ``subprocess.TimeoutExpired`` עולה הלאה: מצב ``--doubling``
    רושם אותו כתוצאה, ובמצב הרגיל הוא באג שעוצר את הריצה. ילד שנכשל — כולל איפוס
    שלא נכתב או לא קרה, והצמדה שלא קרתה — עוצר את הריצה ב-``SystemExit`` עם ההודעה
    שלו, בשני המצבים.
    """
    spec = PARSERS[parser]
    cpu = _measuring_cpu()
    lag = counter_lag_bound_bytes()
    if lag >= RESET_PROBE_BYTES // 2:
        raise SystemExit(
            f"the kernel counter lag on this machine ({lag} bytes) is not below half the reset "
            f"probe ({RESET_PROBE_BYTES} bytes), so a reset that happened cannot be told from one "
            "that did not; raise RESET_PROBE_BYTES. Refusing to measure"
        )
    program = _CHILD.format(
        repo=str(REPO),
        path=str(path),
        module=spec["module"],
        warm=spec["warm"],
        kwargs=dict(kwargs or {}),
        address_space=ADDRESS_SPACE_BYTES,
        clear_refs=CLEAR_REFS_PATH,
        probe_bytes=RESET_PROBE_BYTES,
        tolerance_kb=lag // 1024,
        cpu=cpu,
        hash_seed_env=HASH_SEED_ENV,
    )
    with _pinned(cpu):
        proc = subprocess.run(
            [sys.executable, "-B", "-c", program],
            capture_output=True,
            text=True,
            cwd=str(workdir),
            env={**os.environ, HASH_SEED_ENV: str(seed)},
            timeout=CHILD_TIMEOUT_SECONDS,
            check=False,
        )
    if proc.returncode != 0:
        raise SystemExit(f"the measuring child failed on {path.name}:\n{proc.stderr}")
    return _from_the_kernel(json.loads(proc.stdout.strip().splitlines()[-1]))


def density(text: str, parser: str = "md") -> float:
    """צפיפות ל-KB: טוקני בלוק בתצורת ``md_parser``, סקשנים ב-``rst_parser``."""
    size = max(1, len(text.encode("utf-8")))
    if parser == "md":
        from services import md_parser

        return md_parser.token_count(text) * 1024 / size
    from services import rst_parser

    return len(rst_parser.parse_document(text).sections) * 1024 / size


def tiled_to_ceiling(text: str, limit: int = MAX_FILE_SIZE_FOR_DISPLAY) -> str:
    """המסמך משוכפל עד התקרה — הקלט הגדול ביותר שפרסור יכול לקבל בה."""
    copies = limit // max(1, len(text.encode("utf-8"))) + 1
    return clip_to_bytes((text + "\n\n") * copies, limit)


def fit_to_the_tool(text: str, parser: str) -> str:
    """הטקסט חתוך לגדול ביותר שהכלי מפרסר: תקרת הקריאה בבתים, ול-Markdown גם תקרת השורות.

    בלי החיתוך השני, הקורפוס, המסמך המשוכפל וכל הצורות העוינות היו נדחים ב-
    ``too_many_lines`` לפני הפרסור — 512KB של טקסט בשורות באורך רגיל הם יותר
    מ-``MAX_LINES`` שורות — והמדידה הייתה מדווחת עלות של סירוב, אפס, במקום העלות
    שהכלי משלם על הקלט הגדול ביותר שהוא עוד מקבל. תקרת הטוקנים אינה נחתכת כאן:
    היא נאכפת בתוך הפרסור, וקלט שנעצר בה הוא חלק ממה שנמדד.
    """
    if parser == "md":
        from services import md_parser

        text = "\n".join(text.split("\n")[: md_parser.MAX_LINES])
    return _without_a_torn_crlf(clip_to_bytes(text, MAX_FILE_SIZE_FOR_DISPLAY))


def _without_a_torn_crlf(text: str) -> str:
    """טקסט שנחתך בין ``\\r`` ל-``\\n`` — בלי ה-``\\r`` שנשאר לבדו בסוף.

    ה-``\\r`` שייך למעבר השורה שנחתך, לא לשורה. בלעדי זה החיתוך היה משאיר ``\\r``
    בודד, שהפרסר דוחה ב-``InconsistentLineEndings`` — ותהליך המדידה נופל עליו
    (כך זה נמצא: בהרצה על ``blank_lines_crlf`` החתוך לתקרת השורות).
    """
    return text[:-1] if text.endswith("\r") else text


# ─── הצורות העוינות של Markdown ───


def tile(unit: str, budget: int, *, head: str = "", tail: str = "") -> str:
    """``unit`` חוזר על עצמו עד ``budget`` בתים בדיוק (חתוך על גבול תו), בין ``head`` ל-``tail``."""
    body = budget - len(head.encode("utf-8")) - len(tail.encode("utf-8"))
    repeated = clip_to_bytes(unit * (body // max(1, len(unit.encode("utf-8"))) + 1), body)
    return head + _without_a_torn_crlf(repeated) + tail


def unique_reference_definitions(budget: int) -> str:
    """הגדרות קישור שכל אחת בשם אחר — הצורה של upstream #367 (ריבועית ב-3.0.0)."""
    lines = []
    size = 0
    for index in range(budget):  # חסם עליון: כל הגדרה היא לפחות בית אחד
        if size >= budget:
            break
        line = f"[r{index}]: b\n"
        lines.append(line)
        size += len(line)
    return clip_to_bytes("".join(lines), budget)


#: רוחב הטבלה שעוברת את תקרת התאים המשלימים של markdown-it-py 4.x: 256 תאים
#: משלימים בכל שורת גוף של תא אחד — אותה טבלה כמו ``_TABLE_CAP_COLUMNS`` באורקל.
TABLE_COLUMNS = 257


def table_over_autocomplete_cap(rows: int = 256) -> str:
    """טבלה אחת ברוחב ``TABLE_COLUMNS`` עם ``rows`` שורות גוף של תא אחד, ושורה ריקה אחריה."""
    return "|" + "a|" * TABLE_COLUMNS + "\n|" + "-|" * TABLE_COLUMNS + "\n" + "x\n" * rows + "\n"


def tables_over_autocomplete_cap(budget: int) -> str:
    """טבלאות כאלה ברצף עד ``budget`` — התקרה של upstream (#364) היא לכל טבלה, והמונה מתאפס."""
    unit = table_over_autocomplete_cap()
    return unit * max(1, budget // len(unit.encode("utf-8")))


def deep_quote_lazy(depth: int, budget: int) -> str:
    """ציטוט בעומק ``depth`` בשורה הראשונה, וכל השאר שורות המשך עצלות שלו."""
    return tile("a\n", budget, head=">" * depth + "a\n")


#: הצורות העוינות, כל אחת כפונקציה של תקציב בתים. העשר הראשונות הן אלה שנמדדו
#: לפני #3391; השאר — מה שמחקר המקור של markdown-it-py 4.2.0 העלה: טבלאות מעל
#: תקרת התאים, הגדרות קישור (שנשמרות ב-``env`` בלי טוקן), ציטוט מקונן (ארבע רשימות
#: לכל שורה בכל רמה), ו-``\r\n`` עם תו אסטרלי (שמנפחים כל עותק של הטקסט).
HOSTILE_SHAPES = {
    "bullets": lambda budget: tile("- item\n", budget),
    "empty_bullets": lambda budget: tile("-\n", budget),
    "blank_lines": lambda budget: tile("\n", budget),
    "paragraph_lines": lambda budget: tile("a\n", budget),
    "blockquote_lines": lambda budget: tile("> a\n", budget),
    "empty_blockquote": lambda budget: tile(">\n", budget),
    "ordered_list": lambda budget: tile("1. a\n", budget),
    "nested_bullets_4": lambda budget: tile("- - - - a\n", budget),
    "table_rows": lambda budget: tile("| a |\n", budget, head="| a |\n|---|\n"),
    "thematic_breaks": lambda budget: tile("***\n", budget),
    "tables_over_autocomplete_cap": tables_over_autocomplete_cap,
    "reference_definitions_unique": unique_reference_definitions,
    "reference_definitions_duplicate": lambda budget: tile("[a]: b\n", budget),
    "atx_empty_headings": lambda budget: tile("#\n", budget),
    "setext_headings": lambda budget: tile("a\n=\n", budget),
    "nested_bullets_10": lambda budget: tile("- " * 10 + "a\n", budget),
    "deep_quote_5_every_line": lambda budget: tile(">" * 5 + "a\n", budget),
    "deep_quote_10_every_line": lambda budget: tile(">" * 10 + "a\n", budget),
    "deep_quote_20_every_line": lambda budget: tile(">" * 20 + "a\n", budget),
    "deep_quote_5_lazy": lambda budget: deep_quote_lazy(5, budget),
    "deep_quote_10_lazy": lambda budget: deep_quote_lazy(10, budget),
    "deep_quote_19_lazy": lambda budget: deep_quote_lazy(19, budget),
    "deep_quote_20_lazy": lambda budget: deep_quote_lazy(20, budget),
    "fence_content": lambda budget: tile("a\n", budget, head="```\n"),
    "html_block_content": lambda budget: tile("a\n", budget, head="<div>\n"),
    "indented_code": lambda budget: tile("    a\n", budget),
    "front_matter_content": lambda budget: tile("a\n", budget, head="---\n", tail="---\n"),
    "blank_lines_crlf": lambda budget: tile("\r\n", budget),
    "blank_lines_crlf_astral": lambda budget: "\U0001F600" + tile("\r\n", budget - 4),
    "paragraph_crlf_astral": lambda budget: "\U0001F600" + tile("a\r\n", budget - 4),
}

#: עומק הציטוט של הקלט הגרוע: 19, רמה אחת מתחת ל-``maxNesting=20`` של הפריסט
#: ``commonmark`` — כדי שהטבלה בסוף עוד תיבנה בתוכו. בעומק 20 הטבלה אינה נבנית
#: והעלות יורדת בחצי (נמדד, 2026-09-27).
WORST_QUOTE_DEPTH = 19


def _table_tokens(rows: int) -> int:
    """כמה טוקנים יוצרת טבלה ברוחב ``TABLE_COLUMNS`` עם ``rows`` שורות גוף, כשהיא נבנית כולה.

    פתיחות ``table``/``thead``/``tr``, שלושה טוקנים לכל תא כותרת, סגירות ``tr``/``thead``,
    ``tbody_open`` — ולכל שורת גוף ``tr_open``, שלושה לכל תא (גם משלים), ``tr_close``.
    בלי הסגירות שבסוף, כי טבלה שעוברת את התקרה לא מגיעה אליהן.
    ``tests/test_measure_md_parse_cost_script.py`` משווה את זה לפרסר.
    """
    return 3 + 3 * TABLE_COLUMNS + 2 + 1 + rows * (2 + 3 * TABLE_COLUMNS)


def _table_past(max_tokens: int, prefix: str = "") -> list[str]:
    """שורות של טבלה אחת שעוברת את ``max_tokens`` בוודאות, כל אחת עם ``prefix``.

    שורת גוף אחת מעבר למינימום — אותה בנייה בדיוק כמו בקלט שנמדד ב-#3391, כדי
    שהסקריפט ישחזר את המדידה שהקבועים נשענים עליה ולא קלט שכן שלה.
    """
    header_tokens = _table_tokens(0)
    per_row = _table_tokens(1) - header_tokens
    rows = max(0, max_tokens - header_tokens) // per_row + 2
    header = [prefix + "|" + "a|" * TABLE_COLUMNS, prefix + "|" + "-|" * TABLE_COLUMNS]
    return header + [prefix + "x"] * rows


def worst_memory_input(
    max_lines: int, max_tokens: int, budget: int = MAX_FILE_SIZE_FOR_DISPLAY
) -> str:
    """הקלט הגרוע בזיכרון שנמצא תחת שתי התקרות — ושני המחירים חיים בו באותו רגע.

    ציטוט בעומק ``WORST_QUOTE_DEPTH`` בכל אחת מ-``max_lines`` השורות (כלל הציטוט
    שומר ארבע רשימות לכל שורה בכל רמה), ממולא עד ``budget`` בתים, עם ``\\r\\n``
    ותו אסטרלי בכל שורה (כל עותק של הטקסט מתנפח), ובסוף הציטוט — **בתוכו** —
    טבלה שעוברת את ``max_tokens``, כך שהטוקנים נוצרים בזמן שרשימות הציטוט חיות.
    """
    quote = ">" * WORST_QUOTE_DEPTH
    eol = "\r\n"
    tail = _table_past(max_tokens, quote)
    content_lines = max_lines - len(tail)
    if content_lines < 1:
        raise ValueError(
            f"max_lines={max_lines} אינו משאיר מקום לתוכן לפני טבלה של {len(tail)} שורות"
        )
    room = budget - sum(len(line.encode("utf-8")) for line in tail) - (max_lines - 1) * len(eol)
    pad = max(0, room // content_lines - len(quote) - 4)  # 4 בתים לתו האסטרלי
    text = eol.join([quote + "\U0001F600" + "a" * pad] * content_lines + tail)
    assert len(text.encode("utf-8")) <= budget, "הקלט הגרוע עבר את תקרת הקריאה"
    assert text.count("\n") + 1 == max_lines, "הקלט הגרוע אינו בדיוק בתקרת השורות"
    return text


def _lazy_quote_then(tail: list[str], max_lines: int) -> str:
    """שורה ראשונה של ציטוט בעומק ``WORST_QUOTE_DEPTH``, שורות המשך עצלות עד התקרה, ואז ``tail``."""
    lazy = max_lines - len(tail) - 2
    return "\n".join([">" * WORST_QUOTE_DEPTH + "a"] + ["a"] * lazy + [""] + tail)


def _nested_bullets_past(max_tokens: int) -> list[str]:
    """רשימה מקוננת בעומק ארבע שעוברת את ``max_tokens``: 17 טוקנים לשורה (נמדד)."""
    return ["- - - - a"] * (max_tokens // 17 + 2)


#: הקלטים הגרועים **במעבד** תחת שתי התקרות — כל אחד דוחף כיוון יקר אחד עד כמה
#: שהתקרות מתירות: ציטוט מקונן עם שורות המשך עד תקרת השורות, ואחריו טבלה או רשימה
#: שנעצרות בתקרת הטוקנים; וכל אחד מהם לבד. אף אחד מהם אינו עובר את תקרת השורות,
#: כך שכולם באמת מפורסרים. המקסימום שנמדד עליהם הוא ``WORST_CASE_CPU_SECONDS``.
CPU_SHAPES = {
    "lazy_quote_then_table": lambda lines, tokens: _lazy_quote_then(_table_past(tokens), lines),
    "lazy_quote_then_bullets": lambda lines, tokens: _lazy_quote_then(
        _nested_bullets_past(tokens), lines
    ),
    "lazy_quote_only": lambda lines, tokens: "\n".join(
        [">" * WORST_QUOTE_DEPTH + "a"] + ["a"] * (lines - 1)
    ),
    "nested_bullets_to_cap": lambda lines, tokens: "\n".join(_nested_bullets_past(tokens)),
    "ordered_to_cap": lambda lines, tokens: "\n".join(["1. a"] * min(lines, tokens // 5 + 2)),
}

#: על כמה ריצות של כל קלט מעבד נשפט זמן המעבד שלו: ה-``CPU_REPEATS`` הראשונות מתוך
#: ``LAYOUT_SEEDS``, והמספר שמושווה לקבוע הוא המקסימום שלהן — המעבד רועש (נמדד פער של עד
#: 10% בין ריצות). הקלטים עצמם רצים על **כל** ``LAYOUT_SEEDS``, כי גם הזיכרון שלהם נכנס
#: לפסק הדין ולמועמד לקבוע, והשיא היקר נדיר (סבב הסקירה השלישי של #3467: על חמישה סידורים
#: בלבד, קלט מעבד שיקר בסידור שלא הוגרל היה מתפספס). המעבד נשאר על ``CPU_REPEATS`` כי
#: ``WORST_CASE_CPU_SECONDS`` נגזר כך — מאז #3391 כל קלט מעבד נמדד ``CPU_REPEATS`` פעמים —
#: ומקסימום על יותר ריצות היה משנה את מה שהקבוע מודד; שאר הריצות נשמרות בשורה
#: (``cpu_seconds_all``) ואינן נשפטות.
CPU_REPEATS = 5

#: הגדלים של בדיקת ההכפלה — כל אחד כפול מקודמו, והגדול הוא תקרת הקריאה.
DOUBLING_SIZES = (
    MAX_FILE_SIZE_FOR_DISPLAY // 4,
    MAX_FILE_SIZE_FOR_DISPLAY // 2,
    MAX_FILE_SIZE_FOR_DISPLAY,
)

#: ולטבלאות מעל תקרת התאים גדלים קטנים בהרבה: בלי תקרות הן עברו 3GB כבר ב-128KB.
TABLE_DOUBLING_SIZES = (4_000, 8_000, 16_000)

#: מאיזו גדילה בעלות לבית קלט — בין הגודל הקטן לגדול, פי ארבעה בקלט — צורה
#: מסומנת ``superlinear``. בפרסר ליניארי היחס סביב 1 — ב-``--doubling`` עם האיפוס, על
#: markdown-it-py 4.2.0 (2026-09-27), כל הצורות נמדדו בזיכרון בין 0.90 ל-1.29 ובמעבד בין
#: 0.72 ל-1.56. הגבוה במעבד הוא ``tables_over_autocomplete_cap``, שבשתי הרצות מוקדמות
#: יותר באותו יום הגיע ל-1.73 — היחס הליניארי הגבוה ביותר שנצפה (זמן המעבד אינו תלוי
#: באיפוס). בריבועי היחס סביב 4. שתיים באמצע.
SUPERLINEAR_GROWTH = 2.0

#: מתחת לזמן הזה, בגודל **הגדול**, המעבד אינו נבדק לגדילה: יחס בין שני מספרים של
#: אלפיות בודדות הוא רעש, ועלות כזאת אינה בעיה גם אם היא ריבועית בגדלים האלה.
CPU_NOISE_FLOOR_SECONDS = 0.1

#: מתחת לשיא הזה, בגודל **הקטן**, הזיכרון אינו נבדק לגדילה — היחס מתחלק בו, ושני דברים
#: שאינם הפרסור מזיזים שיא כזה: פיגור מוני הקרנל (``counter_lag_bound_bytes``, לשני
#: הכיוונים) וסידור הזיכרון (בגדלים של ``DOUBLING_SIZES``, על 40 סידורים, נמדד ב-2026-09-27
#: פיזור של עד 16% — יחס שזז כך רחוק מ-``SUPERLINEAR_GROWTH``). שיא אפס היה הופך כל שיא
#: בגודל הגדול ליחס אינסופי, וצורה ליניארית הייתה מסומנת ``superlinear``. הרצפה חייבת
#: להיות מעל פי 2.25 מפיגור המונה, אחרת צורה ליניארית שנמדדת בה נראית ריבועית —
#: ``_require_a_memory_floor_above_the_counter_lag`` עוצר את בדיקת ההכפלה כשלא (כאן:
#: 1MiB מול 372KB). במעבד הרצפה יושבת על הגודל הגדול, כי שם הרעש הוא תנודה ולא סכום
#: במכנה. ועלות כזאת אינה בעיה גם אם היא ריבועית: ב-``DOUBLING_SIZES`` פי ארבעה בקלט
#: הם פי שישה-עשר בעלות, ועדיין בתוך ``_PARSE_COST_BYTES``. הצורה הזולה ביותר,
#: ``nested_bullets_10``, עלתה בגודל הקטן 1,134,592–1,282,048 בתים (על 40 סידורים, ובריצת
#: ``--doubling`` עצמה) — מעל הרצפה בכולם, כך שאף צורה אינה מאבדת את הבדיקה.
MEMORY_NOISE_FLOOR_BYTES = 1024 * 1024


def real_files(suffix: str) -> list[pathlib.Path]:
    """כל קובצי ``suffix`` בריפו שאינם vendored ואינם קטנים מ-``MIN_DOC_BYTES``."""
    return sorted(
        p
        for p in REPO.rglob("*" + suffix)
        if not (set(p.parts) & _SKIP_PARTS) and p.stat().st_size >= MIN_DOC_BYTES
    )


def rank(files: list[pathlib.Path], parser: str) -> list[tuple[float, pathlib.Path, str]]:
    """הקבצים לפי צפיפות, מהצפוף ביותר; קובץ שאינו UTF-8, או עם ``\\r`` בודד, מדולג בקול ב-stderr."""
    from services.doc_sections import InconsistentLineEndings

    ranked = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            # הכלל ב-CLAUDE.md: except שמדלג אומר זאת — אחרת המסמך הצפוף
            # ביותר יכול לצאת מהדירוג בלי שאיש יידע.
            print(json.dumps({"skipped": str(p), "reason": f"not utf-8: {exc.reason}"}), file=sys.stderr)
            continue
        try:
            ranked.append((density(text, parser), p, text))
        except InconsistentLineEndings as exc:
            # אותו כלל: הפרסר של הכלי מסרב לקובץ עם ``\r`` בודד (מאז SUGG-019
            # גם ``token_count`` עובר בשער הכניסה שלו), והכלי לא היה מגיש אותו.
            print(json.dumps({"skipped": str(p), "reason": f"lone CR at line {exc.args[0]}"}), file=sys.stderr)
            continue
    if not ranked:
        suffix = PARSERS[parser]["suffix"]
        raise SystemExit(f"no {suffix} file of at least {MIN_DOC_BYTES} bytes under {REPO} — nothing to measure")
    ranked.sort(key=lambda r: r[0], reverse=True)
    return ranked


def constant_candidate(results: list[dict], parser: str) -> float:
    """המועמד ל-``_PARSE_RSS_PER_INPUT_BYTE``: החסם העליון הגבוה מבין המדידות שרצו **כמו הכלי**.

    החסם העליון (``peak_upper_bound_bytes``) — המקסימום על ``LAYOUT_SEEDS`` ועוד
    ``counter_lag_bound_bytes`` — ולא המקסימום לבדו ולא ריצה אחת: מה שריצה אחת מפספסת
    (סידור נדיר, פיגור המונה) הוא תמיד לכיוון "נכנס". בבתים לכל בית של **תקרת
    הקריאה**, ולא של הקלט שנמדד: הקבוע מוכפל ב-``MAX_FILE_SIZE_FOR_DISPLAY`` כדי לתת את
    העלות של פרסור אחד, ולכן קלט קטן ויקר — טבלה של 17KB שנעצרת בתקרת הטוקנים — נמדד
    לפי מה שהוא באמת עולה לחוט. מדידות שאינן כמו הכלי (הצורה בלי תקרות, מסלול
    ה-outline) אינן נכנסות. שתי ספרות אחרי הנקודה, כי המרווח מהקבוע קטן.
    """
    return round(
        max(r["peak_upper_bound_bytes"] for r in results if r["parser"] == parser and r["as_tool"])
        / MAX_FILE_SIZE_FOR_DISPLAY,
        2,
    )


def hostile_bound(results: list[dict], parser: str) -> float:
    """הצורה העוינת **בלי אף תקרה** — הגבול של הפרסר עצמו, ומה שהתקרות חוסכות."""
    return next(r["peak_bytes_per_input_byte"] for r in results if r["parser"] == parser and r["shape"] == "hostile")


def worst_cpu_seconds(results: list[dict], parser: str) -> float:
    """זמן המעבד הגבוה מבין המדידות שרצו כמו הכלי — מה שמושווה ל-``WORST_CASE_CPU_SECONDS``."""
    return max(r["cpu_seconds"] for r in results if r["parser"] == parser and r["as_tool"])


#: התוצאה של מדידה שלא קיבלה אותה תוצאה בכל הסידורים. הפרסור דטרמיניסטי — אותו קלט
#: נעצר באותה תקרה בכל סידור — ולכן תוצאות שונות אומרות שבאחד מהם קרה משהו אחר (למשל
#: ``MemoryError``), והמקסימום אינו עלות של פרסור. אינה ב-``MEASURED_OUTCOMES``.
OUTCOME_DIFFERS_BY_LAYOUT = "differs_by_layout"


def across_layouts(runs: list[dict], *, cpu_runs: int | None = None) -> dict:
    """ריצות של אותו קלט על כמה סידורי זיכרון, כשורה אחת: הריצה הגבוהה, ועוד הפיזור והחסם העליון.

    ``peak_bytes`` הוא המקסימום, עם שאר השדות של אותה ריצה (כולל ``hash_seed``).
    ``peak_bytes_min`` ו-``peak_bytes_by_layout`` (לפי סדר הזרעים) הם הפיזור — כדי שמי
    שמריץ פעם אחת יבין איפה המספר שלו נופל. ``peak_upper_bound_bytes`` הוא המקסימום ועוד
    ``counter_lag_bound_bytes`` — המספר שנשפט מול התקציב, תמיד על **כל** הריצות.
    ``cpu_seconds`` הוא הגבוה מבין הריצות שנספרות למעבד — כולן, או ``cpu_runs`` הראשונות
    כשהמדיניות של הקלט אומרת כך (``CPU_REPEATS``) — ו-``cpu_timed_runs`` אומר כמה מהן;
    ``cpu_seconds_all`` מחזיק את כולן, גם את מה שלא נספר. תוצאה שאינה זהה בכל הריצות היא
    ``OUTCOME_DIFFERS_BY_LAYOUT``, ואז ``outcomes_by_layout`` אומר מה יצא בכל אחת.
    """
    peaks = [run["peak_bytes"] for run in runs]
    outcomes = [run["outcome"] for run in runs]
    worst = max(runs, key=lambda run: run["peak_bytes"])
    timed = runs if cpu_runs is None else runs[:cpu_runs]
    same_outcome = len(set(outcomes)) == 1
    return {
        **worst,
        "outcome": outcomes[0] if same_outcome else OUTCOME_DIFFERS_BY_LAYOUT,
        **({} if same_outcome else {"outcomes_by_layout": outcomes}),
        "layout_runs": len(runs),
        "peak_bytes_min": min(peaks),
        "peak_bytes_by_layout": peaks,
        "peak_upper_bound_bytes": max(peaks) + counter_lag_bound_bytes(),
        "cpu_seconds": max(run["cpu_seconds"] for run in timed),
        "cpu_timed_runs": len(timed),
        "cpu_seconds_all": [run["cpu_seconds"] for run in runs],
    }


def _measured(parser: str, shape: str, path: pathlib.Path, work: pathlib.Path, *,
              kwargs: dict | None = None, seeds: Sequence[int] = LAYOUT_SEEDS,
              cpu_runs: int | None = None, **extra) -> dict:
    """מדידה אחת על פני ``seeds`` — ריצה לכל זרע — עם הסימון אם היא רצה כמו הכלי, בלי ארגומנטים.

    ``cpu_runs`` מגביל רק את מה שנספר למעבד (``across_layouts``); הזיכרון נשפט על כל ``seeds``.
    """
    runs = [peak_cost(path, work, parser=parser, kwargs=kwargs, seed=seed) for seed in seeds]
    return {
        "parser": parser,
        "shape": shape,
        "as_tool": kwargs is None,
        **extra,
        **across_layouts(runs, cpu_runs=cpu_runs),
    }


def _write(work: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = work / name
    path.write_text(text, encoding="utf-8", newline="")
    return path


def measure(parser: str, work: pathlib.Path) -> list[dict]:
    """הצורות של פרסר אחד: קורפוס, מסמך צפוף, עוין בלי תקרות — ול-RST גם ה-outline."""
    spec = PARSERS[parser]
    ranked = rank(real_files(spec["suffix"]), parser)
    print(json.dumps({
        "parser": parser,
        "files": len(ranked),
        "median_density_per_kb": round(statistics.median(r[0] for r in ranked), 1),
        "read_ceiling_bytes": MAX_FILE_SIZE_FOR_DISPLAY,
    }))
    results = []
    # הקורפוס האמיתי, חתוך למה שהכלי מפרסר — העלות הטיפוסית.
    corpus = _write(
        work,
        "corpus" + spec["suffix"],
        fit_to_the_tool("\n\n".join(r[2] for r in sorted(ranked, key=lambda r: str(r[1]))), parser),
    )
    results.append(_measured(parser, "corpus", corpus, work))
    # המסמך הצפוף ביותר, משוכפל עד התקרה וחתוך למה שהכלי מפרסר — הצפוף ביותר
    # מהתוכן האמיתי. ב-Markdown הוא יכול להיעצר בתקרת הטוקנים, וזה חלק מהמדידה.
    top_density, top_path, top_text = ranked[0]
    tiled = _write(
        work, "tiled_" + top_path.name, fit_to_the_tool(tiled_to_ceiling(top_text), parser)
    )
    results.append(_measured(
        parser, "densest_real", tiled, work,
        source=str(top_path.relative_to(REPO)), density_per_kb=round(top_density, 1),
    ))
    # הצורה העוינת בלי אף תקרה — הגבול של הפרסר עצמו, ולא מה שהכלי מגיש.
    unit = spec["hostile_unit"]
    hostile = _write(
        work,
        "hostile" + spec["suffix"],
        clip_to_bytes(unit * (MAX_FILE_SIZE_FOR_DISPLAY // len(unit) + 1), MAX_FILE_SIZE_FOR_DISPLAY),
    )
    results.append(_measured(parser, "hostile", hostile, work, kwargs=dict(UNCAPPED[parser])))
    if parser == "rst":
        # מסלול ה-outline של codekeeper_get_repo_file: קריאה עד RANGE_READ_MAX_BYTES,
        # פרסור עם תקרת סקשנים — ההחזקה הגדולה ביותר של חוט קריאה היום.
        from mcp_server.outline_scanners._ceiling import MAX_SYMBOLS
        from mcp_server.repo_backend import RANGE_READ_MAX_BYTES

        outline = _write(
            work, "outline_" + top_path.name, tiled_to_ceiling(top_text, RANGE_READ_MAX_BYTES)
        )
        results.append(_measured(
            parser, "outline_densest_real", outline, work,
            kwargs={"max_sections": MAX_SYMBOLS}, source=str(top_path.relative_to(REPO)),
        ))
    if parser == "md":
        results.extend(measure_hostile_as_the_tool(work))
    return results


def measure_hostile_as_the_tool(work: pathlib.Path) -> list[dict]:
    """ה-Markdown העוין כמו שהכלי מקבל אותו: על ברירות המחדל של כל התקרות."""
    from services import md_parser

    results = []
    for name, build in HOSTILE_SHAPES.items():
        text = fit_to_the_tool(build(MAX_FILE_SIZE_FOR_DISPLAY), "md")
        path = _write(work, f"capped_{name}.md", text)
        results.append(_measured("md", f"capped:{name}", path, work))
    worst_text = worst_memory_input(md_parser.MAX_LINES, md_parser.MAX_TOKENS)
    worst = _write(work, "worst_memory.md", worst_text)
    results.append(_measured("md", "worst_memory", worst, work))
    for name, make in CPU_SHAPES.items():
        path = _write(work, f"cpu_{name}.md", make(md_parser.MAX_LINES, md_parser.MAX_TOKENS))
        # על כל ``LAYOUT_SEEDS``, כמו כל מדידה כמו הכלי — הזיכרון שלהם נשפט גם הוא — והמעבד
        # על ``CPU_REPEATS`` הראשונות בלבד; הנימוק ליד הקבוע.
        results.append(_measured("md", f"cpu:{name}", path, work, cpu_runs=CPU_REPEATS))
    return results


#: התוצאות שבהן מדידה שרצה כמו הכלי באמת מדדה פרסור: הפרסור רץ עד הסוף, או עד
#: תקרה שעצרה אותו באמצע — והעצירה היא בדיוק מה שהכלי משלם עליו (הקלט הגרוע בזיכרון
#: בנוי להגיע אליה). כל תוצאה אחרת אומרת שהמספרים בשורה אינם עלות של פרסור:
#: ``too_many_lines`` — הקלט נדחה לפני הפרסור, ונמדד אפס; ``memory_error`` — הפרסור
#: נפל על ``RLIMIT_AS``, והשיא הוא רק מה שהספיק לתפוס לפני ההקצאה שנכשלה, כך שהוא
#: יכול להיות מתחת לתקציב דווקא כשהפרסור אינו נכנס בו. רשימה של מה שמותר ולא של
#: מה שאסור, כדי שתוצאה חדשה תפיל את פסק הדין עד שמישהו יחליט מה היא.
MEASURED_OUTCOMES = frozenset({"parsed", "too_many_tokens", "too_many_sections"})


def verdict(results: list[dict]) -> dict:
    """השורה האחרונה: האם מה שנמדד עדיין בתוך הקבועים שנגזרו ממנו — ואם לא, מה נשבר.

    ארבע שאלות, כל אחת בשדה משלה: האם כל מדידה של Markdown שרצה כמו הכלי באמת מדדה
    פרסור (``every_input_measured``, ו-``md_unmeasured`` אומר אילו לא); האם כל מדידה
    כזו רצה על כל ``LAYOUT_SEEDS`` (``every_input_on_every_layout``, ו-``md_undersampled``
    אומר אילו לא); האם **החסם העליון** של המכריעה — המקסימום ועוד
    ``counter_lag_bound_bytes`` — נכנס ב-``_PARSE_COST_BYTES``; והאם זמן המעבד הגבוה אינו
    עובר את ``WORST_CASE_CPU_SECONDS``. ``passed`` הוא ארבעתן יחד, והוא קוד היציאה. לצד
    החסם השורה נושאת את המקסימום הנמדד ואת המינימום של אותו קלט — הפיזור בין הסידורים.
    """
    from mcp_server.server import _PARSE_COST_BYTES, _PARSE_RSS_PER_INPUT_BYTE
    from services import md_parser

    as_tool = [r for r in results if r["parser"] == "md" and r["as_tool"]]
    # K11: הילד מחזיר כשל כערך (``outcome``) ולא זורק, ולכן הוא נבדק כאן לפני כל
    # "נכנס בתקציב" — אחרת ``MemoryError`` עם שיא נמוך היה יוצא בקוד 0.
    unmeasured = [
        {"shape": r["shape"], "outcome": r["outcome"]}
        for r in as_tool
        if r["outcome"] not in MEASURED_OUTCOMES
    ]
    # כל מדידה, ולא רק המכריעה: מקסימום על פחות סידורים הוא הגרלה קטנה יותר, והוא נמוך
    # בדיוק כשהסידור היקר לא הוגרל — ולכן מדידה כזו היא דווקא זו שלא תיבחר כמכריעה.
    # בדיקה של המכריעה בלבד לא הייתה נדלקת על המקרה שבשבילו היא קיימת (סבב הסקירה
    # השלישי של #3467: קלטי המעבד רצו על חמישה סידורים, ושיא שלהם בסידור אחר לא נראה).
    undersampled = [
        {"shape": r["shape"], "layout_runs": r["layout_runs"]}
        for r in as_tool
        if r["layout_runs"] < len(LAYOUT_SEEDS)
    ]
    deciding = max(as_tool, key=lambda r: r["peak_upper_bound_bytes"])
    upper = deciding["peak_upper_bound_bytes"]
    worst_cpu = worst_cpu_seconds(results, "md")
    # בבתים ולא לפי המועמד המעוגל: ``_PARSE_COST_BYTES`` הוא מה שהמאגר מקצה לחוט.
    memory_ok = upper <= _PARSE_COST_BYTES
    cpu_ok = worst_cpu <= md_parser.WORST_CASE_CPU_SECONDS
    return {
        "md_unmeasured": unmeasured,
        "every_input_measured": not unmeasured,
        "md_undersampled": undersampled,
        "every_input_on_every_layout": not undersampled,
        "md_worst_shape": deciding["shape"],
        "md_worst_peak_bytes": deciding["peak_bytes"],
        "md_worst_peak_min_bytes": deciding["peak_bytes_min"],
        "counter_lag_bound_bytes": counter_lag_bound_bytes(),
        "md_worst_upper_bound_bytes": upper,
        "parse_cost_bytes": _PARSE_COST_BYTES,
        "md_worst_upper_bound_share_of_budget": round(upper / _PARSE_COST_BYTES, 4),
        "md_constant_candidate_bytes_per_ceiling_byte": constant_candidate(results, "md"),
        "parse_rss_per_input_byte": _PARSE_RSS_PER_INPUT_BYTE,
        "memory_within_budget": memory_ok,
        "md_worst_cpu_seconds": worst_cpu,
        "worst_case_cpu_seconds": md_parser.WORST_CASE_CPU_SECONDS,
        "cpu_within_constant": cpu_ok,
        "passed": not unmeasured and not undersampled and memory_ok and cpu_ok,
        "note": (
            "every_input_measured false: a run as the tool was refused before parsing, "
            "failed on MemoryError, or ended differently across layouts, so its numbers are "
            "not the cost of a parse. every_input_on_every_layout false: a run as the tool "
            "was measured on fewer layouts than LAYOUT_SEEDS (md_undersampled says which): its "
            "maximum is a smaller draw, low exactly when it missed the costly layout, and then "
            "another run decides in its place. The memory answer is on "
            "the upper bound (the maximum over the layouts plus the kernel counter lag), not "
            "on one run. Otherwise the pool, the rate limit and the batch deadline are derived "
            "from the two constants; a false means their arithmetic needs a new look before "
            "anything else changes (cpu time depends on the machine: both numbers are printed)"
        ),
    }


def _require_a_memory_floor_above_the_counter_lag() -> None:
    """רצפת הזיכרון של בדיקת ההכפלה חייבת להיות גבוהה מספיק מפיגור המונה — אחרת עוצרים.

    כל מדידה יכולה לסטות עד ``counter_lag_bound_bytes`` (L) לכל כיוון: מטה בשיא,
    ומעלה בשארית שהאיפוס משאיר. בין הגודל הקטן לגדול הקלט גדל פי r (4 ב-
    ``DOUBLING_SIZES`` וב-``TABLE_DOUBLING_SIZES``), והסף הוא g
    (``SUPERLINEAR_GROWTH``). צורה ליניארית שהשיא שלה בגודל הקטן הוא בדיוק הרצפה F
    נמדדת במקרה הגרוע ביחס ((r·F + L) / (F − L)) / r, והוא מתחת ל-g רק כש-
    F > L·(1 + g·r) / (r·(g − 1)) — פי 2.25 מהפיגור. כאן: F = 1MiB ו-L = 372KB.
    במכונה עם הרבה מעבדים הפיגור גדל, והבדיקה הייתה מסמנת צורה ליניארית כריבועית —
    ובפיגור גדול עוד יותר, מפספסת ריבועית. במקום אחד מאלה, היא עוצרת.
    """
    lag = counter_lag_bound_bytes()
    for sizes in (DOUBLING_SIZES, TABLE_DOUBLING_SIZES):
        r = sizes[-1] / sizes[0]
        g = SUPERLINEAR_GROWTH
        needed = lag * (1 + g * r) / (r * (g - 1))
        if MEMORY_NOISE_FLOOR_BYTES <= needed:
            raise SystemExit(
                f"MEMORY_NOISE_FLOOR_BYTES ({MEMORY_NOISE_FLOOR_BYTES}) is not above what the "
                f"kernel counter lag on this machine ({lag} bytes) needs ({int(needed)} bytes): a "
                "linear shape could read as superlinear, and a larger lag could hide a quadratic "
                "one. Refusing to run the doubling check"
            )


def doubling(work: pathlib.Path) -> list[dict]:
    """כל צורה בלי תקרות, בשלושה גדלים כפולים — ומה קרה לעלות לבית קלט כשהקלט גדל."""
    _require_a_memory_floor_above_the_counter_lag()
    uncapped = dict(UNCAPPED["md"])
    rows = []
    for name, build in HOSTILE_SHAPES.items():
        sizes = TABLE_DOUBLING_SIZES if name == "tables_over_autocomplete_cap" else DOUBLING_SIZES
        runs = []
        for size in sizes:
            path = _write(work, f"double_{name}_{size}.md", build(size))
            try:
                runs.append(peak_cost(path, work, parser="md", kwargs=uncapped))
            except subprocess.TimeoutExpired:
                # תוצאה, לא בליעה: חריגה מהזמן היא בדיוק מה שפרסור ריבועי עושה, והיא
                # מסמנת את הצורה ומפילה את קוד היציאה.
                runs.append({"outcome": "timeout", "input_bytes": len(path.read_bytes())})
        rows.append({"shape": name, "sizes": list(sizes), "runs": runs, **growth(runs)})
    return rows


def _per_input_byte(run: dict, key: str) -> float:
    """העלות במדידה אחת לכל בית של הקלט שלה — מה שבפרסר ליניארי נשאר קבוע כשהקלט גדל."""
    return run[key] / run["input_bytes"]


def growth(runs: list[dict]) -> dict:
    """הגדילה בעלות לבית קלט בין המדידה הקטנה לגדולה, והאם היא מעל ``SUPERLINEAR_GROWTH``.

    משאב שהמדידה שלו מתחת לרצפת הרעש שלו — ``MEMORY_NOISE_FLOOR_BYTES`` בגודל הקטן,
    ``CPU_NOISE_FLOOR_SECONDS`` בגודל הגדול — אינו נבדק, והגדילה שלו היא ``None``;
    רק גדילה שנמדדה יכולה לסמן ``superlinear``.
    """
    failed = [run["outcome"] for run in runs if run["outcome"] in ("memory_error", "timeout")]
    if failed:
        return {"memory_growth": None, "cpu_growth": None, "superlinear": True, "reason": failed[0]}
    first, last = runs[0], runs[-1]
    memory = None
    if first["peak_bytes"] >= MEMORY_NOISE_FLOOR_BYTES:
        memory = _per_input_byte(last, "peak_bytes") / _per_input_byte(first, "peak_bytes")
    cpu = None
    if last["cpu_seconds"] >= CPU_NOISE_FLOOR_SECONDS:
        first_cpu = _per_input_byte(first, "cpu_seconds")
        cpu = _per_input_byte(last, "cpu_seconds") / max(1e-9, first_cpu)
    superlinear = any(g is not None and g > SUPERLINEAR_GROWTH for g in (memory, cpu))
    return {
        "memory_growth": None if memory is None else round(memory, 2),
        "cpu_growth": None if cpu is None else round(cpu, 2),
        "superlinear": superlinear,
    }


def main(argv: list[str] | None = None) -> int:
    import markdown_it

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--doubling",
        action="store_true",
        help="בדיקת ההכפלה: כל צורה עוינת בלי תקרות, בשלושה גדלים כפולים",
    )
    args = parser.parse_args(argv)

    print(json.dumps({"markdown_it": markdown_it.__version__, "python": sys.version.split()[0]}))
    with tempfile.TemporaryDirectory(prefix="parse-cost-") as tmp:
        work = pathlib.Path(tmp)
        if args.doubling:
            rows = doubling(work)
            for row in rows:
                print(json.dumps(row, ensure_ascii=False))
            flagged = [row["shape"] for row in rows if row["superlinear"]]
            print(json.dumps({"superlinear": flagged, "threshold": SUPERLINEAR_GROWTH}))
            return 1 if flagged else 0
        results = []
        for name in PARSERS:
            results.extend(measure(name, work))
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    summary = verdict(results)
    print(json.dumps({
        name: {
            "constant_candidate_bytes_per_input_byte": constant_candidate(results, name),
            "hostile_bound_bytes_per_input_byte": hostile_bound(results, name),
        }
        for name in PARSERS
    } | {
        "note": (
            "the constant is the costliest parse run as the tool runs it, "
            "per byte of the read ceiling; "
            "the hostile bound is the same parser with every ceiling off"
        ),
        "verdict": summary,
    }))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

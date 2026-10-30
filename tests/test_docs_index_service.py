"""מעבר האינדוקס של התיעוד (``services/docs_index_service.py``): רשומות, תוכנית, מעבר, ו-lease.

מול דמה של מונגו (``_fake_mongo.FakeDB``), אתר מדומה ומטמיע מדומה (``_docs_index_harness``).
הקובץ עובר דרך ``fetch_export`` ו-``parse_export`` האמיתיים. ה-lease נבדק כאן גם עם threads (הדמה
מחזיקה מנעול על כל עדכון, כמו האטומיות של מסמך אחד במונגו), ושוב מול מונגו אמיתי ב-
``test_docs_index_mongo.py``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo.errors import ServerSelectionTimeoutError

# ‏``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _docs_index_harness import (
    DIMENSIONS,
    EARLY,
    LATE,
    LATER,
    MODEL,
    MODEL_KEY,
    SHA_A,
    SHA_B,
    SHA_C,
    export_bytes,
    fill,
    make_world,
    page,
    run_request,
    section,
    site_pages,
)
from _fake_mongo import FakeCollection, FakeDB

from services import docs_index_service as svc
from services import docs_search_contract as contract
from services.chunking_service import CHUNK_MAX_BYTES
from services.docs_export_client import EXPORT_NOT_FOUND, EXPORT_STALE, parse_export


@pytest.fixture
def world(monkeypatch):
    return make_world(monkeypatch, FakeDB())


def _chunks(world):
    return list(world.db[contract.CHUNKS_COLLECTION].find({}))


def _sections(world):
    return list(world.db[contract.SECTIONS_COLLECTION].find({}))


def _pages(world):
    return list(world.db[contract.PAGES_COLLECTION].find({}))


def _state(world):
    return svc.read_state(world.db)


def _event_names(world):
    return [name for name, _severity, _fields in world.events]


def _request(trigger=svc.TRIGGER_MANUAL_CHECK, commit=None, fingerprint=None):
    return {
        "trigger": trigger,
        "commit": commit,
        "approved_fingerprint": fingerprint,
        "requested_by": None,
        "requested_at": datetime.now(timezone.utc),
    }


def _records(pages, commit=SHA_A):
    return svc.build_records(parse_export(export_bytes(commit, pages)))


# ---------------------------------------------------------------------------
# סעיפים ונתחים
# ---------------------------------------------------------------------------


def test_a_section_that_fits_is_one_chunk_led_by_its_breadcrumb():
    sections, chunks = _records(site_pages())

    assert [s.title for s in sections] == ["חיפוש גלובלי", "סוגי החיפוש", "קטלוג אירועים", "אינדקס התיעוד"]
    types = sections[1]
    [chunk] = [c for c in chunks if c.section_id == types.id]
    assert chunk.text == "חיפוש גלובלי › סוגי החיפוש\n\n| סוג | מה |\n| --- | --- |\n| תוכן | טקסט |"
    assert chunk.part == 0
    assert chunk.content_sha == hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
    assert (types.page_path, types.source_path, types.page_title, types.anchor) == (
        "webapp/global-search.html", "docs/webapp/global-search.rst", "חיפוש גלובלי", "global-search-types",
    )


def test_a_long_section_is_split_within_the_byte_budget_breadcrumb_included():
    body = "\n".join(f"שורה {n}: " + "מילה " * 30 for n in range(200))
    sections, chunks = _records([page("a.html", "docs/a.rst", section("a", "עמוד", "סעיף ארוך", markdown=body))])

    prefix = "עמוד › סעיף ארוך\n\n"
    assert len(sections) == 1 and len(chunks) > 1
    assert all(c.text.startswith(prefix) for c in chunks)
    assert max(len(c.text.encode("utf-8")) for c in chunks) <= CHUNK_MAX_BYTES
    assert [c.part for c in chunks] == list(range(len(chunks)))
    covered = "\n".join(c.text[len(prefix):] for c in chunks)
    assert all(f"שורה {n}:" in covered for n in range(200))


def test_a_budget_smaller_than_the_breadcrumb_is_a_configuration_error(monkeypatch):
    monkeypatch.setattr(svc, "CHUNK_MAX_BYTES", 10)
    with pytest.raises(ValueError, match="no room for a body"):
        _records([page("a.html", "docs/a.rst", section("a", "עמוד", "סעיף", markdown="טקסט " * 10))])


@pytest.mark.parametrize(
    "markdown",
    [
        "- [אינדקסים](https://amirbiron.github.io/CodeBot/database/indexing.html)",
        "* [א](https://x.example/a) — הסבר קצר\n* [ב](https://x.example/b)",
        "1. [א](a.html)\n2. [ב](b.html).",
        "https://github.com/amirbiron/CodeBot",
        "::: seealso\n- [א](a.html)\n:::",
    ],
)
def test_a_list_of_links_is_links_only(markdown):
    assert svc.is_links_only(markdown) is True


@pytest.mark.parametrize(
    "markdown",
    ["", "טקסט רגיל.", "- [א](a.html) ועוד מילים", "ראו [א](a.html) בהמשך", "::: note\n:::", "- [א](a.html)\nטקסט"],
)
def test_text_is_not_links_only(markdown):
    assert svc.is_links_only(markdown) is False


@pytest.mark.parametrize("markdown", ["", "\n\n", "::: note\n:::", "- [א](a.html)"])
def test_an_empty_or_links_only_section_is_not_indexed(markdown):
    sections, chunks = _records(
        [page("a.html", "docs/a.rst", section("a", "עמוד"), section("b", "עמוד", "ריק", markdown=markdown))]
    )
    assert [s.title for s in sections] == ["עמוד"]
    assert len(chunks) == 1


def test_a_repeated_breadcrumb_gets_its_own_key():
    sections, chunks = _records(
        [
            page("a.html", "docs/a.rst", section("a", "עמוד"), section("id1", "עמוד", "דוגמה"),
                 section("id2", "עמוד", "דוגמה", markdown="דוגמה שנייה.")),
            page("b.html", "docs/b.rst", section("b", "עמוד"), section("id1", "עמוד", "דוגמה")),
        ]
    )
    assert len({s.id for s in sections}) == len(sections) == 5
    assert len({c.id for c in chunks}) == len(chunks) == 5


def test_the_keys_do_not_depend_on_the_anchor():
    moved = site_pages()
    moved[1]["sections"][1]["anchor"] = "id7"
    before_sections, before_chunks = _records(site_pages())
    after_sections, after_chunks = _records(moved)

    assert [s.id for s in after_sections] == [s.id for s in before_sections]
    assert [(c.id, c.content_sha) for c in after_chunks] == [(c.id, c.content_sha) for c in before_chunks]
    changed = [a for a, b in zip(after_sections, before_sections) if a.record_sha != b.record_sha]
    assert [s.anchor for s in changed] == ["id7"]


def test_the_section_sha_covers_every_field_the_card_shows():
    """שדה שנוסף ל-``content`` ולא נכנס ל-sha היה משאיר במסד ערך ישן בלי שאיש יעדכן אותו."""
    [record, *_] = _records(site_pages())[0]
    for field in record.content():
        value = getattr(record, field)
        if isinstance(value, tuple):
            changed = value + ("x",)
        elif isinstance(value, int):
            changed = value + 1
        else:
            changed = value + "x"
        assert dataclasses.replace(record, **{field: changed}).record_sha != record.record_sha, field
    assert set(record.document()) == {"_id", "record_sha", *record.content()}


# ---------------------------------------------------------------------------
# יומן עדכונים
# ---------------------------------------------------------------------------
#
# המארקדאון בטסטים כתוב כמו שכפתור ההעתקה ממיר את העמוד (Turndown, ``docs/_static/copy-page.js``):
# בולט הוא ``-   ``, שורות בתוכו מוזחות בארבעה רווחים, ובין בולטים שורה של רווחים — כמו בקובץ הייצוא
# של What's New. ``test_an_update_headline_is_the_text_on_the_page_and_its_link_jumps_to_it`` ב-
# ``tests/test_docs_export_sections_browser.py`` עובר באותה שרשרת עם הממיר עצמו, ובדפדפן.

WHATS_NEW = "docs/whats-new.rst"
TOP = "What’s New"


def _log_page(*days, source_path=WHATS_NEW):
    """עמוד יומן עדכונים: הסעיף העליון ריק, ואחריו יום לכל ``(עוגן, תאריך, מארקדאון)``."""
    return page(
        "whats-new.html", source_path, section("what-s-new", TOP, markdown=""),
        *(section(anchor, TOP, date, markdown=markdown) for anchor, date, markdown in days),
    )


def _updates(*lines):
    return "\n    \n".join(f"-   {line}" for line in lines)


def test_each_update_in_an_update_log_is_a_record_titled_by_its_headline():
    day = _updates(
        "**fix (WebApp): הקובץ מוצג כמו שהוא בריפו.** הסיבה: הצנזור רץ גם על התוכן.",
        "**feat (MCP): בלוק ה-instructions נכתב מחדש.** הוא נכנס בתקרה של הלקוח.",
    )
    sections, chunks = _records([_log_page(("id9", "2026-09-29", day))])

    first, second = "fix (WebApp): הקובץ מוצג כמו שהוא בריפו.", "feat (MCP): בלוק ה-instructions נכתב מחדש."
    assert [(s.title, s.breadcrumb, s.anchor, s.level, s.markdown, s.link_text) for s in sections] == [
        (first, (TOP, "2026-09-29", first), "id9", 3, "הסיבה: הצנזור רץ גם על התוכן.", first),
        (second, (TOP, "2026-09-29", second), "id9", 3, "הוא נכנס בתקרה של הלקוח.", second),
    ]
    assert [c.text for c in chunks] == [
        f"{TOP} › 2026-09-29 › {first}\n\nהסיבה: הצנזור רץ גם על התוכן.",
        f"{TOP} › 2026-09-29 › {second}\n\nהוא נכנס בתקרה של הלקוח.",
    ]


def test_a_page_that_is_not_an_update_log_keeps_one_record_per_section():
    day = _updates("**fix: א.** טקסט.", "**fix: ב.** טקסט.")
    sections, chunks = _records([_log_page(("id1", "2026-10-01", day), source_path="docs/other.rst")])

    assert [(s.title, s.breadcrumb, s.markdown, s.link_text) for s in sections] == [
        ("2026-10-01", (TOP, "2026-10-01"), day, "")
    ]
    assert len(chunks) == 1


def test_every_chunk_of_a_long_update_starts_with_its_headline():
    """ההקשר של עדכון ארוך לא נשאר רק בנתח הראשון: הפתיח בשביל, והשביל בראש כל נתח."""
    body = " ".join(f"מילה{n}" for n in range(700))
    sections, chunks = _records([_log_page(("id21", "2026-09-10", _updates(f"**feat: עדכון ארוך.** {body}")))])

    prefix = f"{TOP} › 2026-09-10 › feat: עדכון ארוך.\n\n"
    assert len(sections) == 1 and len(chunks) > 1
    assert all(c.text.startswith(prefix) for c in chunks)
    assert max(len(c.text.encode("utf-8")) for c in chunks) <= CHUNK_MAX_BYTES
    assert "מילה0 " in chunks[0].text and chunks[-1].text.endswith("מילה699")


@pytest.mark.parametrize(
    "update,title,body",
    [
        # rst לא מקנן סימון, ולכן קוד בתוך פתיח נכתב כהדגשה שמפוצלת סביבו — צמוד, או עם רווחים.
        (
            "**docs: תוקנה סתירה בין התיעוד לקוד ב-**`POST /api/themes/import`**.** העמוד תיעד גוף אחר.",
            "docs: תוקנה סתירה בין התיעוד לקוד ב-POST /api/themes/import.",
            "העמוד תיעד גוף אחר.",
        ),
        (
            "**fix:** `page/per_page` **היה הפיצ’ר היחיד בלי טסט.** הוא הוחזר לתיאור.",
            "fix: page/per_page היה הפיצ’ר היחיד בלי טסט.",
            "הוא הוחזר לתיאור.",
        ),
        # קוד אחרי ההדגשה האחרונה כבר שייך לגוף.
        ("**fix: בדיקת הגודל** `MAX_BYTES` רצה עכשיו ראשונה.", "fix: בדיקת הגודל", "`MAX_BYTES` רצה עכשיו ראשונה."),
        (
            "**change: מימוש אחד לגודל** (`size-format.js`, נטען בכל עמוד).",
            "change: מימוש אחד לגודל",
            "(`size-format.js`, נטען בכל עמוד).",
        ),
        ("**refactor: המנתב לפי סיומת**, והלוגיקה בקובץ משלה.", "refactor: המנתב לפי סיומת", ", והלוגיקה בקובץ משלה."),
    ],
)
def test_the_headline_is_the_bold_run_that_opens_the_update(update, title, body):
    [record], _chunks = _records([_log_page(("id3", "2026-10-07", _updates(update)))])
    assert (record.title, record.markdown, record.link_text) == (title, body, title)


@pytest.mark.parametrize(
    "update,title",
    [
        # Turndown מוסיף לוכסן לפני ` * _ [ ] \ — והעמוד מציג את התו עצמו.
        (
            r"**docs (MCP): בלוק ה-\`\`instructions\`\` מזכיר את \`\`x\_y\`\`.** עוד.",
            "docs (MCP): בלוק ה-``instructions`` מזכיר את ``x_y``.",
        ),
        (r"**fix: \*\*\* במקום הערך, ו-\[x\] בסוף.** עוד.", "fix: *** במקום הערך, ו-[x] בסוף."),
        (r"**fix: נתיב C:\\x נקרא נכון.** עוד.", "fix: נתיב C:\\x נקרא נכון."),
        # ישות נשארת כמו שהיא: כך היא כתובה בעמוד, ו-Turndown לא מוסיף escape ל-&.
        (r"**fix: \`\`&lt;div&gt;\`\` נשמר כמו שהוקלד.** עוד.", "fix: ``&lt;div&gt;`` נשמר כמו שהוקלד."),
        # קישור ← הטקסט שלו, גם עם title (Sphinx נותן אותו להפניה ל-:py:mod:) וגם עם סוגריים בכתובת.
        (
            r'**ראו [services.code\_service](https://x.example/a.html#m "services.code_service") '
            r"ו-[ב](https://x.example/\(b\)).** עוד.",
            "ראו services.code_service ו-ב.",
        ),
        # תחביר של קישור בתוך קוד, או עם escape, מוצג בעמוד כמו שהוא.
        ("**fix: התחביר** `[טקסט](כתובת)` **נשמר.** עוד.", "fix: התחביר [טקסט](כתובת) נשמר."),
        (r"**fix: \[טקסט\](כתובת) נשמר.** עוד.", "fix: [טקסט](כתובת) נשמר."),
    ],
)
def test_the_headline_is_the_text_the_page_shows(update, title):
    [record], _chunks = _records([_log_page(("id2", "2026-10-10", _updates(update)))])
    assert record.title == record.link_text == title


def test_a_headline_that_repeats_on_the_page_is_a_label_and_its_update_goes_under_its_day():
    """"מגבלה ידועה:" היא תווית ולא שם של עדכון, וקפיצה אליה הייתה מגיעה להופעה הראשונה שלה."""
    pages = [
        _log_page(
            (
                "id25",
                "2026-09-06",
                _updates("**מגבלה ידועה:** החיפוש איטי בזמן ה-re-index.", "**feat: חלון זמן אחד.** עוד."),
            ),
            ("id28", "2026-08-31", _updates("**מגבלה ידועה:** אין מיגרציה.")),
        )
    ]
    sections, _chunks = _records(pages)

    assert [(s.title, s.breadcrumb, s.markdown, s.link_text) for s in sections] == [
        ("2026-09-06", (TOP, "2026-09-06"), "**מגבלה ידועה:** החיפוש איטי בזמן ה-re-index.", ""),
        ("feat: חלון זמן אחד.", (TOP, "2026-09-06", "feat: חלון זמן אחד."), "עוד.", "feat: חלון זמן אחד."),
        ("2026-08-31", (TOP, "2026-08-31"), "**מגבלה ידועה:** אין מיגרציה.", ""),
    ]


def test_a_headline_quoted_in_another_update_is_not_unique_either():
    day = _updates("**fix: הקאש ממופתח לפי החלון.** עוד.", "ראו את ”fix: הקאש ממופתח לפי החלון.“ למעלה.")
    sections, _chunks = _records([_log_page(("id25", "2026-09-06", day))])
    assert [s.link_text for s in sections] == ["", ""]


@pytest.mark.parametrize(
    "headline,elsewhere",
    [
        ("fix: the parser keeps order.", "FIX: The Parser Keeps Order."),
        ("fix: שלום עולם.", "fix: שָׁלוֹם עוֹלָם."),
        ("fix: café crème.", "fix: cafe creme."),
    ],
)
def test_a_headline_that_differs_elsewhere_only_in_case_or_marks_is_not_unique(headline, elsewhere):
    """הדפדפן מחפש את הקפיצה בלי הבדל בין אותיות גדולות לקטנות ובלי ניקוד ואקסנטים (נמדד ב-Chromium), ולכן
    הופעה כזו בעדכון אחר מקדימה את הפתיח בעמוד, והקפיצה הייתה מגיעה אליה."""
    day = _updates(f"ראו {elsewhere} למטה.", f"**{headline}** עוד.")
    sections, _chunks = _records([_log_page(("id25", "2026-09-06", day))])
    assert [s.link_text for s in sections] == ["", ""]


@pytest.mark.parametrize(
    "earlier",
    [
        # הטה באמצע: בעמוד מוצג "fix: parser order.", והקפיצה הייתה מגיעה לכאן ולא לעדכון.
        "ראו fix: *parser* order. בהמשך.",
        # הטה סביב המשפט כולו: המשפט נשאר בטקסט כמו שהוא.
        "ראו *fix: parser order.* בהמשך.",
    ],
)
def test_a_headline_shown_earlier_in_italics_is_not_unique(earlier):
    """Turndown כותב הטה ב-``*`` (``emDelimiter`` ב-``docs/_static/copy-page.js``). בעמוד הסימן לא מוצג, ולכן
    גם לא בטקסט שהייחודיות נבדקת מולו."""
    day = _updates(earlier, "**fix: parser order.** גוף העדכון.")
    sections, _chunks = _records([_log_page(("id25", "2026-09-06", day))])
    assert [s.link_text for s in sections] == ["", ""]


def test_the_page_text_is_normalized_once_and_not_once_per_update(monkeypatch):
    """``_match_key`` עובר על כל תו בפייתון, ולכן על הטקסט של העמוד כולו הוא רץ פעם אחת. כשהוא רץ מחדש בבדיקה
    של כל עדכון, ``build_records`` על הייצוא של 11.10.2026 לקח 7.1 שניות. נבדק המבנה ולא הזמן, שתלוי במכונה."""
    lengths = []
    real = svc._match_key

    def counting(text):
        lengths.append(len(text))
        return real(text)

    monkeypatch.setattr(svc, "_match_key", counting)
    day = _updates(*(f"**fix: עדכון מספר {n}.** גוף העדכון, ארוך יותר מהפתיח שלו." for n in range(20)))

    sections, _chunks = _records([_log_page(("id1", "2026-10-11", day))])

    assert sum(1 for record in sections if record.link_text) == 20
    page = max(lengths)
    assert lengths.count(page) == 1, lengths
    assert sum(lengths) < 2 * page, lengths


def test_an_update_without_a_headline_goes_under_its_day_without_a_jump():
    update = "feat (פרופיילר): הדשבורד קיבל מיון. וקודם כול — **חלון זמן אחד**: שלושה מספרים על אותו מסך."
    [record], [chunk] = _records([_log_page(("id25", "2026-09-06", _updates(update)))])

    assert (record.title, record.breadcrumb, record.markdown, record.link_text) == (
        "2026-09-06", (TOP, "2026-09-06"), update, ""
    )
    assert chunk.text == f"{TOP} › 2026-09-06\n\n{update}"


def test_text_outside_the_updates_is_one_record_under_its_day():
    day = _updates("docs: Runbooks – צ’קליסט Incident חדש.") + "\n    \n\nקישורים ל‑Issues רלוונטיים: `#1198`, `#1239`."
    sections, _chunks = _records([_log_page(("id34", "2025-11-06", day))])

    assert [(s.title, s.markdown) for s in sections] == [
        ("2025-11-06", "docs: Runbooks – צ’קליסט Incident חדש."),
        ("2025-11-06", "קישורים ל‑Issues רלוונטיים: `#1198`, `#1239`."),
    ]
    assert len({s.id for s in sections}) == 2


def test_a_code_block_outside_the_updates_is_not_split_into_updates():
    """שורה בבלוק קוד שמתחילה כמו בולט אינה עדכון — הגבולות הם של הפרסר, לא של כלל על שורות."""
    day = _updates("**feat: הגדרה חדשה.** דוגמה למטה.") + "\n\n```yaml\n-   not an update\n```"
    sections, _chunks = _records([_log_page(("id5", "2026-10-05", day))])

    assert [(s.title, s.markdown) for s in sections] == [
        ("feat: הגדרה חדשה.", "דוגמה למטה."),
        ("2026-10-05", "```yaml\n-   not an update\n```"),
    ]


def test_an_update_with_a_nested_list_and_code_is_one_update():
    day = (
        "-   **feat: א.** טקסט.\n    \n    -   תת-בולט\n    \n    ```python\n    x = 1\n    ```\n"
        "-   **fix: ב.** עוד."
    )
    sections, _chunks = _records([_log_page(("id6", "2026-10-04", day))])

    assert [(s.title, s.markdown) for s in sections] == [
        ("feat: א.", "טקסט.\n\n-   תת-בולט\n\n```python\nx = 1\n```"),
        ("fix: ב.", "עוד."),
    ]


def test_an_unclosed_backtick_does_not_swallow_text_past_its_own_block():
    """לפי CommonMark קטע קוד לא חוצה גבול של בלוק. בלי זה, גרש יתום "בולע" טקסט עד הגרש הבא, ושם escape
    אינו מתבטל — ופתיח של עדכון אחר נעלם מהטקסט של העמוד, או נשאר בו פעם אחת פחות מדי."""
    across = _updates("**fix: א.** גרש ` יתום בשורה הזו.", r"**fix: x\_y.** עוד `קוד`.")
    sections, _chunks = _records([_log_page(("id1", "2026-10-11", across))])
    assert [s.link_text for s in sections] == ["fix: א.", "fix: x_y."]

    # בתוך עדכון אחד: הפסקה השנייה מצטטת את הפתיח של העדכון הבא, ולכן הוא אינו ייחודי.
    within = (
        "-   **fix: ג.** גרש ` יתום.\n    \n    ראו **fix: x\\_y.** למטה, וגם `קוד`.\n-   "
        + r"**fix: x\_y.** עוד."
    )
    sections, _chunks = _records([_log_page(("id1", "2026-10-11", within))])
    assert [s.link_text for s in sections] == ["fix: ג.", ""]


def test_windows_line_endings_give_the_same_updates():
    """markdown-it מנרמל ``\\r\\n`` לפני הפרסור, ולכן גם החיתוך לשורות — אחרת השורות שהוא מחזיר לא היו
    השורות שנחתכות מהטקסט, ו-``\\r`` היה נשאר בגוף של עדכון."""
    day = "-   **feat: א.** טקסט.\n    \n    שורה שנייה.\n-   **fix: ב.** עוד."
    expected = _records([_log_page(("id1", "2026-10-11", day))])

    assert _records([_log_page(("id1", "2026-10-11", day.replace("\n", "\r\n")))]) == expected
    assert expected[0][0].markdown == "טקסט.\n\nשורה שנייה."


def test_a_headline_over_the_title_ceiling_is_not_cut_and_its_update_goes_under_its_day(caplog):
    headline = "fix: " + "א" * 200  # מעל MAX_TITLE_BYTES
    with caplog.at_level(logging.WARNING, logger=svc.__name__):
        [record], _chunks = _records([_log_page(("id1", "2026-10-11", _updates(f"**{headline}** עוד.")))])

    assert (record.title, record.link_text) == ("2026-10-11", "")
    assert record.markdown == f"**{headline}** עוד."
    assert "whats-new.html#id1" in caplog.text and "over MAX_TITLE_BYTES" in caplog.text


def test_a_new_update_does_not_change_the_keys_of_the_others():
    """עדכון נוסף בראש היום (המקום הרגיל שלו) לא משנה את המפתחות של השאר, ולכן לא שולח אותם להטמעה."""
    older = ["**fix: א.** טקסט.", "**feat: ב.** טקסט.", "docs: בלי פתיח."]
    before_sections, before_chunks = _records([_log_page(("id1", "2026-10-11", _updates(*older)))])
    after_sections, after_chunks = _records(
        [_log_page(("id1", "2026-10-11", _updates("**fix: חדש.** טקסט.", *older)))]
    )

    assert [s.id for s in after_sections[1:]] == [s.id for s in before_sections]
    assert [(c.id, c.content_sha) for c in after_chunks[1:]] == [(c.id, c.content_sha) for c in before_chunks]


# ---------------------------------------------------------------------------
# עמודים מורכבים — מה שהתצוגה המרונדרת בדפדפן הריפו מציגה
# ---------------------------------------------------------------------------


def _pages_of(pages, commit=SHA_A):
    return svc.build_pages(parse_export(export_bytes(commit, pages)))


def _code_browser_page():
    """עמוד עם כל סוגי הסעיפים: כותרת בלי גוף משלה, סעיף עם קוד, תת-סעיף שבכותרת שלו קוד, ו"ראו גם"."""
    return page(
        "webapp/code-browser.html", "docs/webapp/code-browser.rst",
        section("code-browser", "דפדפן קוד", markdown=""),
        section("import", "דפדפן קוד", "ייבוא ריפו חדש", markdown="להריץ:\n\n```python\nimport x\n```\n"),
        section("webhook", "דפדפן קוד", "ייבוא ריפו חדש", "הגדרת Webhook",
                title_markdown="הגדרת `Webhook`", markdown="1.  כנסו לריפו"),
        section("see-also", "דפדפן קוד", "ראו גם",
                markdown="-   [סקירה](https://amirbiron.github.io/CodeBot/webapp/overview.html)"),
    )


def test_a_page_is_every_section_in_order_each_heading_at_its_level():
    """כותרת בלי גוף משלה ו"ראו גם" אינם בחיפוש, אבל הם חלק מהעמוד; והכותרת היא המארקדאון שלה."""
    [record] = _pages_of([_code_browser_page()])

    assert (record.id, record.page_path, record.title) == (
        "docs/webapp/code-browser.rst", "webapp/code-browser.html", "דפדפן קוד"
    )
    assert record.markdown == (
        "# דפדפן קוד\n\n"
        "## ייבוא ריפו חדש\n\n"
        "להריץ:\n\n```python\nimport x\n```\n\n"
        "### הגדרת `Webhook`\n\n"
        "1.  כנסו לריפו\n\n"
        "## ראו גם\n\n"
        "-   [סקירה](https://amirbiron.github.io/CodeBot/webapp/overview.html)\n"
    )
    # אותו עמוד בחיפוש: בלי הכותרת שאין לה גוף ובלי "ראו גם".
    assert [s.title for s in _records([_code_browser_page()])[0]] == ["ייבוא ריפו חדש", "הגדרת Webhook"]


def test_a_section_deeper_than_markdown_headings_is_written_at_the_deepest_level():
    """docutils נותן לסעיף עמוק מ-6 את התגית ``h6``, ולכן גם העמוד המורכב. שבעה ``#`` אינם כותרת."""
    crumbs = [f"רמה {n}" for n in range(1, 8)]
    [record] = _pages_of([page("a.html", "docs/a.rst", *(section(f"l{n}", *crumbs[:n]) for n in range(1, 8)))])

    headings = [line for line in record.markdown.splitlines() if line.startswith("#")]
    assert headings[-2:] == ["###### רמה 6", "###### רמה 7"]


def test_only_rst_pages_are_stored_as_pages():
    """עמוד md מוצג בדפדפן הריפו מהמקור שלו, בתצוגת ה-Markdown הקיימת."""
    records = _pages_of(
        [page("a.html", "docs/a.rst", section("a", "א")), page("b.html", "docs/b.md", section("b", "ב"))]
    )
    assert [record.id for record in records] == ["docs/a.rst"]


def test_an_update_log_page_keeps_its_days_whole():
    """בחיפוש יומן עדכונים מתפרק לעדכונים; העמוד שלו הוא הימים כמו שהם, עם הרשימה שלהם."""
    day = _updates("**fix: א.** טקסט.", "**feat: ב.** טקסט נוסף.")
    [record] = _pages_of([_log_page(("id1", "2026-10-11", day))])

    assert record.markdown == f"# {TOP}\n\n## 2026-10-11\n\n{day}\n"


def test_the_page_sha_covers_every_field_it_stores():
    [record] = _pages_of(site_pages()[:1])
    for field in record.content():
        value = getattr(record, field)
        changed = dataclasses.replace(record, **{field: value + ("x",) if isinstance(value, tuple) else value + "x"})
        assert changed.record_sha != record.record_sha, field
    assert record.document() == {"_id": record.source_path, **record.content(), "record_sha": record.record_sha}


def test_a_page_keeps_the_files_it_was_built_from():
    """דפדפן הריפו משווה אותם כדי לדעת אם העמוד ישן מהקוד שהוא מציג (``services/docs_page_view.py``)."""
    built_from = ["handlers/save_flow.py", "main.py"]
    [record] = _pages_of([page("a.html", "docs/a.rst", section("a", "א"), dependencies=built_from)])
    assert record.dependencies == ("handlers/save_flow.py", "main.py")
    assert record.document()["dependencies"] == built_from


# ---------------------------------------------------------------------------
# מילוי ראשון ואישור
# ---------------------------------------------------------------------------


def test_a_first_fill_waits_for_approval_and_changes_nothing(world):
    world.site.publish(SHA_A, site_pages())
    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    assert (run["status"], run["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.APPROVAL_FIRST_FILL)
    approval = _state(world)["approval"]
    assert approval["source_commit"] == SHA_A
    assert svc.is_fingerprint(approval["fingerprint"])
    assert (approval["plan"]["chunks_to_embed"], approval["plan"]["embed_requests"]) == (4, 1)
    assert world.embed_calls == [] and _chunks(world) == [] and _sections(world) == []
    assert _state(world).get("indexed_source_commit") is None
    assert _event_names(world) == ["docs_index_awaiting_approval", "docs_index_pass"]
    assert world.site.paths() == [contract.export_path_for_commit(SHA_A)]


def test_an_approved_first_fill_indexes_everything_and_records_the_commit(world):
    fill(world, requested_by=7)

    state = _state(world)
    assert (state["indexed_source_commit"], state["indexed_model_key"]) == (SHA_A, MODEL_KEY)
    assert state["approval"] is None and state["pending"] is None
    chunks = _chunks(world)
    assert len(chunks) == 4
    assert {c[contract.MODEL_KEY_FIELD] for c in chunks} == {MODEL_KEY}
    assert {(c["embeddingModel"], c["embeddingApiVersion"], c["embeddingDim"]) for c in chunks} == {
        (MODEL, "v1beta", DIMENSIONS)
    }
    assert all(len(c[contract.VECTOR_FIELD]) == DIMENSIONS for c in chunks)
    assert len(_sections(world)) == 4
    assert (state["chunk_count"], state["section_count"]) == (4, 4)
    assert state["run"]["verified"]["complete"] is True
    assert [len(call["texts"]) for call in world.embed_calls] == [4]
    # המעבר המאושר קרא את הקובץ של התוכנית שאושרה, ולא את הקובץ הראשי.
    assert world.site.paths()[-1] == contract.export_path_for_commit(SHA_A)
    [complete] = [fields for name, _s, fields in world.events if name == "docs_index_pass"][-1:]
    assert (complete["status"], complete["embedded"], complete["chunk_count"], complete["user_id"]) == (
        svc.STATUS_COMPLETE, 4, 4, 7
    )


def test_the_state_timestamps_carry_a_timezone(world):
    fill(world)
    state = _state(world)
    for field in ("updated_at", "indexed_at", "indexed_built_at", "applied_built_at", "created_at"):
        assert state[field].utcoffset() is not None, field


def test_a_second_pass_on_the_same_export_sends_nothing(world):
    fill(world)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    assert (run["status"], run["code"]) == (svc.STATUS_UNCHANGED, None)
    assert world.embed_calls == []


def test_the_main_file_is_not_downloaded_again_when_it_did_not_change(world):
    fill(world)
    # ה-ETag הוא של הכתובת שממנה הגיע: אחרי מעבר לפי קומיט אין עדיין ETag של הקובץ הראשי.
    assert _state(world)["export_etag"] is None
    first = run_request(world, svc.TRIGGER_PUSH)
    assert first["status"] == svc.STATUS_UNCHANGED
    assert _state(world)["export_etag"]

    second = run_request(world, svc.TRIGGER_PUSH)

    assert (second["status"], second["detail"]) == (
        svc.STATUS_UNCHANGED, "the export did not change since the last pass"
    )
    assert world.site.requests[-1].headers.get("If-None-Match")
    assert "export" not in second


def test_an_index_built_by_other_record_rules_is_not_complete():
    state = {
        "indexed_source_commit": SHA_A, "export_commit": SHA_A, "indexed_model_key": MODEL_KEY,
        "indexed_records_version": svc.RECORDS_VERSION,
    }
    assert svc.is_index_complete(state, MODEL_KEY) is True
    assert svc.is_index_complete({**state, "indexed_records_version": svc.RECORDS_VERSION - 1}, MODEL_KEY) is False
    del state["indexed_records_version"]  # אינדקס מלפני שהגרסה נשמרה
    assert svc.is_index_complete(state, MODEL_KEY) is False


def test_after_the_record_rules_change_a_check_reads_the_export_again_and_records_the_new_rules(world):
    """בלי זה, כללים חדשים על אותו קובץ לא היו מגיעים לאינדקס: הבדיקה הייתה נעצרת על 304."""
    fill(world)
    run_request(world, svc.TRIGGER_PUSH)  # שומר את ה-ETag של הקובץ הראשי
    assert _state(world)["indexed_records_version"] == svc.RECORDS_VERSION
    world.db[contract.STATE_COLLECTION].update_one(
        {"_id": svc.STATE_ID}, {"$set": {"indexed_records_version": svc.RECORDS_VERSION - 1}}
    )

    run = run_request(world, svc.TRIGGER_MANUAL_CHECK)

    assert world.site.requests[-1].headers.get("If-None-Match") is None
    assert run["status"] == svc.STATUS_COMPLETE
    assert _state(world)["indexed_records_version"] == svc.RECORDS_VERSION
    assert svc.is_index_complete(_state(world), MODEL_KEY)


def test_the_dry_run_plan_writes_nothing_and_can_be_approved(world):
    world.site.publish(SHA_A, site_pages())

    summary = svc.plan_for_admin(world.db)

    assert (summary["chunks_to_embed"], summary["approval_reason"]) == (4, svc.APPROVAL_FIRST_FILL)
    assert svc.read_state(world.db) is None and _chunks(world) == [] and world.embed_calls == []
    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=summary["fingerprint"])
    assert run["status"] == svc.STATUS_COMPLETE
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_an_approved_deployment_plan_reads_its_commit_file_again(world):
    """הקובץ הראשי זז מאז, אבל התוכנית שאושרה חושבה מהעותק של הקומיט — והוא מה שנקרא שוב."""
    world.site.publish(SHA_A, site_pages())
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    fingerprint = _state(world)["approval"]["fingerprint"]
    moved_on = site_pages()
    moved_on[0]["sections"][0]["markdown"] = "גרסה חדשה יותר."
    world.site.publish(SHA_B, moved_on)

    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=fingerprint)

    assert run["status"] == svc.STATUS_COMPLETE
    assert world.site.paths()[-1] == contract.export_path_for_commit(SHA_A)
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_an_approved_main_file_plan_reads_the_main_file_again(world):
    """תוכנית של "בדוק עכשיו" או של רשת הביטחון חושבה מהקובץ הראשי, ואין בהכרח עותק לפי קומיט:
    הוא קיים רק בפריסה שכתבה אותו. נמצא באימות מול האתר החי (7.10.2026): לפני התיקון, המעבר המאושר
    ביקש את העותק לפי הקומיט ונכשל ב-``export_not_found``."""
    world.site.publish(SHA_A, site_pages(), commit_copy=False)
    run_request(world, svc.TRIGGER_MANUAL_CHECK)
    approval = _state(world)["approval"]
    assert approval["by_commit"] is False

    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=approval["fingerprint"])

    assert run["status"] == svc.STATUS_COMPLETE, run
    assert world.site.paths()[-1] == contract.EXPORT_PATH
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_an_approval_of_a_plan_that_changed_waits_again(world):
    world.site.publish(SHA_A, site_pages())
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    outdated = _state(world)["approval"]["fingerprint"]
    newer = site_pages()
    newer[0]["sections"][0]["markdown"] = "טקסט חדש."
    world.site.publish(SHA_B, newer)
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=outdated)

    assert (run["status"], run["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.CODE_APPROVAL_MISMATCH)
    assert world.embed_calls == [] and _chunks(world) == []
    assert _state(world)["approval"]["fingerprint"] == run["plan"]["fingerprint"] != outdated


def test_an_approved_plan_that_changed_into_a_small_one_runs(world, monkeypatch):
    fill(world)
    monkeypatch.setattr(svc, "APPROVAL_THRESHOLD_CHUNKS", 1)
    big = site_pages()
    big[0]["sections"][0]["markdown"] = "שינוי ראשון."
    big[1]["sections"][0]["markdown"] = "שינוי שני."
    world.site.publish(SHA_B, big)
    dry = svc.plan_for_admin(world.db)
    assert dry["approval_reason"] == svc.APPROVAL_OVER_THRESHOLD
    small = site_pages()
    small[0]["sections"][0]["markdown"] = "שינוי ראשון."
    world.site.publish(SHA_C, small)

    run = run_request(world, svc.TRIGGER_APPROVED, approved_fingerprint=dry["fingerprint"])

    assert run["status"] == svc.STATUS_COMPLETE
    assert _state(world)["indexed_source_commit"] == SHA_C


def test_over_the_threshold_an_automatic_pass_waits(world, monkeypatch):
    fill(world)
    monkeypatch.setattr(svc, "APPROVAL_THRESHOLD_CHUNKS", 1)
    pages = site_pages()
    pages[0]["sections"][0]["markdown"] = "שינוי ראשון."
    pages[1]["sections"][0]["markdown"] = "שינוי שני."
    world.site.publish(SHA_B, pages)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.APPROVAL_OVER_THRESHOLD)
    assert world.embed_calls == []
    assert _state(world)["indexed_source_commit"] == SHA_A
    assert _state(world)["approval"]["plan"]["chunks_to_embed"] == 2


def test_a_model_change_waits_for_approval_and_then_reembeds_everything(world):
    fill(world)
    world.db["system_config"].update_one({"_id": "semantic_embedding"}, {"$set": {"dimensions": 8}})
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    assert (run["status"], run["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.APPROVAL_FIRST_FILL)
    assert (run["plan"]["model_key"], run["plan"]["chunks_to_embed"]) == (f"{MODEL}/8", 4)
    assert world.embed_calls == []
    done = run_request(
        world, svc.TRIGGER_APPROVED, approved_fingerprint=_state(world)["approval"]["fingerprint"]
    )
    assert done["status"] == svc.STATUS_COMPLETE
    assert {len(c[contract.VECTOR_FIELD]) for c in _chunks(world)} == {8}
    assert {c[contract.MODEL_KEY_FIELD] for c in _chunks(world)} == {f"{MODEL}/8"}
    assert _state(world)["indexed_model_key"] == f"{MODEL}/8"


# ---------------------------------------------------------------------------
# ההתראה לבוט כשהאינדקס נכנס להמתנה
# ---------------------------------------------------------------------------


def _publish_changes(world, commit, *texts):
    """פרסום של ``commit`` שבו הסעיפים הראשונים בכל עמוד מקבלים את ``texts`` — נתח להטמעה לכל טקסט."""
    pages = site_pages()
    for page_index, text in enumerate(texts):
        pages[page_index]["sections"][0]["markdown"] = text
    world.site.publish(commit, pages)


def test_a_first_fill_alerts_that_the_index_waits(world):
    world.site.publish(SHA_A, site_pages())
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    [alert] = world.alerts
    assert (alert["name"], alert["severity"]) == (svc.ALERT_APPROVAL_NEEDED, "warn")
    assert alert["details"] == {
        "alert_type": svc.ALERT_APPROVAL_NEEDED,
        "reason": svc.APPROVAL_FIRST_FILL,
        "chunks_to_embed": 4,
        "approval_threshold": svc.APPROVAL_THRESHOLD_CHUNKS,
        "source_commit": SHA_A,
    }
    assert "4 נתחים להטמעה" in alert["summary"] and SHA_A[:7] in alert["summary"]


def test_entering_the_wait_alerts_once_and_another_stop_on_the_same_gap_does_not(world, monkeypatch):
    """כל מיזוג אחרי הכניסה מחשב מחדש את הפער המצטבר ועוצר שוב — בלי עוד התראה."""
    fill(world)
    world.alerts.clear()
    monkeypatch.setattr(svc, "APPROVAL_THRESHOLD_CHUNKS", 1)
    _publish_changes(world, SHA_B, "שינוי ראשון.", "שינוי שני.")

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.APPROVAL_OVER_THRESHOLD)
    [alert] = world.alerts
    assert alert["details"] == {
        "alert_type": svc.ALERT_APPROVAL_NEEDED,
        "reason": svc.APPROVAL_OVER_THRESHOLD,
        "chunks_to_embed": 2,
        "approval_threshold": 1,
        "source_commit": SHA_B,
        "indexed_commit": SHA_A,
    }
    assert "2 נתחים להטמעה, מעל התקרה (1)" in alert["summary"]
    assert SHA_B[:7] in alert["summary"] and SHA_A[:7] in alert["summary"]

    _publish_changes(world, SHA_C, "שינוי ראשון.", "שינוי שני, מאוחר יותר.")
    again = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_C)

    assert (again["status"], again["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.APPROVAL_OVER_THRESHOLD)
    assert _state(world)["approval"]["source_commit"] == SHA_C
    assert len(world.alerts) == 1


def test_after_a_pass_that_succeeded_the_next_wait_alerts_again(world, monkeypatch):
    fill(world)
    world.alerts.clear()
    monkeypatch.setattr(svc, "APPROVAL_THRESHOLD_CHUNKS", 1)
    _publish_changes(world, SHA_B, "שינוי ראשון.", "שינוי שני.")
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)
    approved = run_request(
        world, svc.TRIGGER_APPROVED, approved_fingerprint=_state(world)["approval"]["fingerprint"]
    )
    assert approved["status"] == svc.STATUS_COMPLETE
    assert len(world.alerts) == 1

    _publish_changes(world, SHA_C, "שינוי שלישי.", "שינוי רביעי.")
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_C)

    assert [alert["details"]["source_commit"] for alert in world.alerts] == [SHA_B, SHA_C]
    assert world.alerts[1]["details"]["indexed_commit"] == SHA_B


def test_after_an_approved_pass_that_paused_midway_the_next_wait_alerts_again(world, monkeypatch):
    """ההמתנה נגמרת כשמעבר מתחיל לכתוב, ולא רק כשהוא מצליח: מעבר מאושר שנעצר במכסה, ואחריו מעבר שעוצר
    שוב על מה שנשאר, הוא בקשה חדשה לאישור — ולכן התראה חדשה."""
    fill(world)
    world.alerts.clear()
    monkeypatch.setattr(svc, "APPROVAL_THRESHOLD_CHUNKS", 1)
    _publish_changes(world, SHA_B, "שינוי ראשון.", "שינוי שני.")
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)
    world.embed_failures[len(world.embed_calls)] = (429, "http 429: RESOURCE_EXHAUSTED: quota")
    paused = run_request(
        world, svc.TRIGGER_APPROVED, approved_fingerprint=_state(world)["approval"]["fingerprint"]
    )
    assert paused["status"] == svc.STATUS_PAUSED_QUOTA
    assert len(world.alerts) == 1

    again = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (again["status"], again["code"]) == (svc.STATUS_AWAITING_APPROVAL, svc.APPROVAL_OVER_THRESHOLD)
    assert len(world.alerts) == 2
    assert "indexed_commit" not in world.alerts[1]["details"]


def test_the_alert_reaches_telegram_with_a_quick_fix_line_to_the_admin_page(world, monkeypatch):
    """מקצה לקצה, דרך מה שנשלח לטלגרם: ``emit_internal_alert`` האמיתי, ``alert_forwarder`` ו-runbook מתוך
    ``config/observability_runbooks.yml``. הסף של הטלגרם הוא ``warn``, כמו בייצור."""
    import alert_forwarder
    import internal_alerts

    monkeypatch.setattr(svc, "emit_internal_alert", internal_alerts.emit_internal_alert)
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("ALERT_TELEGRAM_MIN_SEVERITY", "warn")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    # הקישור המלא נבנה מ-WEBAPP_URL, שאין לו ברירת מחדל (webapp_url.py) — כמו בייצור, הוא מוגדר.
    monkeypatch.setenv("WEBAPP_URL", "https://webapp.test")
    sent = []

    def telegram(method, url, json=None, timeout=5):  # noqa: ARG001 — החתימה של http_sync.request
        sent.append(json)
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    monkeypatch.setattr(alert_forwarder, "_pooled_request", telegram)
    world.site.publish(SHA_A, site_pages())

    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    [payload] = sent
    lines = payload["text"].splitlines()
    assert lines[0] == f"🔔 {svc.ALERT_APPROVAL_NEEDED} (WARN)"
    [quick_fix] = [line for line in lines if line.startswith("Quick Fix: ")]
    link = quick_fix.rsplit(" → ", 1)[1]
    assert link.startswith(("http://", "https://")) and link.endswith("/admin/docs-index")


# ---------------------------------------------------------------------------
# מה שהשתנה
# ---------------------------------------------------------------------------


def test_only_what_changed_is_embedded_and_what_was_removed_is_deleted(world):
    fill(world)
    before = {c["_id"]: c for c in _chunks(world)}
    pages = site_pages()
    pages[0]["sections"][1]["markdown"] = "| סוג | מה |\n| --- | --- |\n| שם | שם הקובץ |"
    removed_title = pages[1]["sections"].pop(1)["title"]
    pages[1]["sections"].append(section("id9", "קטלוג אירועים", "אירוע חדש", markdown="``docs_index_failed``."))
    world.site.publish(SHA_B, pages)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_COMPLETE, run
    [call] = world.embed_calls
    assert sorted(text.split("\n\n")[0] for text in call["texts"]) == [
        "חיפוש גלובלי › סוגי החיפוש", "קטלוג אירועים › אירוע חדש"
    ]
    assert run["deleted"] == {"chunks": 1, "sections": 1, "pages": 0}
    after = {c["_id"]: c for c in _chunks(world)}
    assert len(after) == 4 and len(set(before) & set(after)) == 3
    assert removed_title not in {s["title"] for s in _sections(world)}
    assert _state(world)["indexed_source_commit"] == SHA_B


def _long_section_pages(lines: int):
    body = "\n".join(f"שורה {n}: " + "מילה " * 30 for n in range(lines))
    return [page("a.html", "docs/a.rst", section("a", "עמוד", "סעיף ארוך", markdown=body))]


def _stored_chunks(world):
    """מסמכי הנתחים בלי מה שמשתנה בכל כתיבה: הווקטור (המטמיע המדומה תלוי במקום באצווה) והחותמת."""
    volatile = {contract.VECTOR_FIELD, "updated_at"}
    return {c["_id"]: {k: v for k, v in c.items() if k not in volatile} for c in _chunks(world)}


def test_a_section_that_grows_leaves_the_chunks_a_fresh_fill_would_store(world, monkeypatch):
    """מעבר שמאריך סעיף לא כותב מחדש את הנתחים שלא השתנו, ולכן אסור שיישמר בהם שדה שתלוי בסעיף
    כולו (כמו כמה חלקים יש לו). ההשוואה היא למה שמילוי מאפס של אותו קובץ כותב."""
    fill(world, pages=_long_section_pages(40))
    world.site.publish(SHA_B, _long_section_pages(60))

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_COMPLETE, run
    assert 0 < run["plan"]["chunks_to_embed"] < len(_chunks(world)), "some chunks must stay as they were"
    incremental = _stored_chunks(world)

    fresh = make_world(monkeypatch, FakeDB())
    fill(fresh, pages=_long_section_pages(60), commit=SHA_B)
    assert incremental == _stored_chunks(fresh)


def test_a_fill_stores_a_page_for_every_rst_source(world):
    done = fill(world)

    pages = {p["_id"]: p for p in _pages(world)}
    assert sorted(pages) == ["docs/observability/events_catalog.rst", "docs/webapp/global-search.rst"]
    search_page = pages["docs/webapp/global-search.rst"]
    assert (search_page["page_path"], search_page["title"]) == ("webapp/global-search.html", "חיפוש גלובלי")
    assert search_page["markdown"] == (
        "# חיפוש גלובלי\n\nהחיפוש בעמוד הקבצים.\n\n"
        "## סוגי החיפוש\n\n| סוג | מה |\n| --- | --- |\n| תוכן | טקסט |\n\n"
        "## ראו גם\n\n- [אינדקסים](https://amirbiron.github.io/CodeBot/database/indexing.html)\n"
    )
    assert (done["verified"]["pages_desired"], done["verified"]["pages_matching"]) == (2, 2)
    assert _state(world)["page_count"] == 2


def test_a_page_that_changed_is_rewritten_and_one_that_left_the_export_is_deleted(world):
    """שינוי ב"ראו גם" אינו נוגע בחיפוש ולא שולח כלום להטמעה, אבל הוא מגיע לעמוד."""
    fill(world)
    pages = site_pages()[:1]
    pages[0]["sections"][2]["markdown"] = "- [אחר](https://amirbiron.github.io/CodeBot/other.html)"
    world.site.publish(SHA_B, pages)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_COMPLETE, run
    assert world.embed_calls == []
    assert (run["plan"]["pages_to_upsert"], run["plan"]["pages_to_delete"]) == (1, 1)
    assert run["deleted"]["pages"] == 1
    [stored] = _pages(world)
    assert stored["_id"] == "docs/webapp/global-search.rst"
    assert "[אחר](https://amirbiron.github.io/CodeBot/other.html)" in stored["markdown"]
    assert _state(world)["indexed_source_commit"] == SHA_B


def test_a_change_in_the_files_a_page_was_built_from_rewrites_the_page_only(world):
    """רשימת הקבצים היא חלק מהעמוד ששמור: שינוי בה מגיע למסד, בלי לגעת בחיפוש ובלי הטמעה."""
    fill(world)
    pages = site_pages()
    pages[0]["dependencies"] = ["handlers/save_flow.py"]
    world.site.publish(SHA_B, pages)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_COMPLETE, run
    assert world.embed_calls == []
    assert (run["plan"]["pages_to_upsert"], run["plan"]["pages_to_delete"]) == (1, 0)
    stored = {p["_id"]: p for p in _pages(world)}
    assert stored["docs/webapp/global-search.rst"]["dependencies"] == ["handlers/save_flow.py"]
    assert stored["docs/observability/events_catalog.rst"]["dependencies"] == []


def test_an_anchor_change_updates_the_card_without_embedding(world):
    fill(world)
    pages = site_pages()
    pages[1]["sections"][1]["anchor"] = "id7"
    world.site.publish(SHA_B, pages)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_COMPLETE
    assert world.embed_calls == []
    assert (run["plan"]["sections_to_upsert"], run["plan"]["chunks_to_embed"]) == (1, 0)
    assert {s["anchor"] for s in _sections(world)} >= {"id7"}
    assert "id3" not in {s["anchor"] for s in _sections(world)}


def test_an_export_that_knows_nothing_indexed_deletes_nothing_and_warns(world, caplog):
    fill(world)
    caplog.set_level(logging.WARNING, logger=svc.logger.name)
    others = [page("other/page.html", "docs/other/page.rst", section("other", "עמוד אחר", markdown="תוכן אחר."))]
    world.site.publish(SHA_B, others)

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    # ארבעה נתחים, ארבעה סעיפים ושני עמודים של המילוי הראשון.
    assert run["plan"]["deletions_spared"] == 10
    assert run["deleted"] == {"chunks": 0, "sections": 0, "pages": 0}
    assert len(_chunks(world)) == 5 and len(_sections(world)) == 5 and len(_pages(world)) == 3
    assert "spared 10 deletions" in caplog.text


def test_an_older_export_does_not_roll_the_index_back(world):
    fill(world, built_at=LATE)
    older = site_pages()
    older[0]["sections"][0]["markdown"] = "גרסה ישנה."
    world.site.publish(SHA_B, older, built_at=EARLY)
    world.embed_calls.clear()

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_UNCHANGED, svc.CODE_OLDER_EXPORT)
    assert world.embed_calls == []
    assert (_state(world)["indexed_source_commit"], _state(world)["export_commit"]) == (SHA_A, SHA_A)
    world.site.publish(SHA_C, older, built_at=LATER)
    assert run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_C)["status"] == svc.STATUS_COMPLETE
    assert _state(world)["indexed_source_commit"] == SHA_C


def test_a_timestamp_stored_without_a_timezone_is_read_as_utc(world):
    """לקוח מונגו שלא הוגדר ``tz_aware`` מחזיר חותמת נאיבית; ההשוואה לא נופלת עליה."""
    fill(world, built_at=LATE)
    naive = datetime.fromisoformat(LATE).replace(tzinfo=None)
    world.db[contract.STATE_COLLECTION].update_one({"_id": svc.STATE_ID}, {"$set": {"applied_built_at": naive}})
    world.site.publish(SHA_B, site_pages(), built_at=EARLY)

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_UNCHANGED, svc.CODE_OLDER_EXPORT)


# ---------------------------------------------------------------------------
# כשלים — כל אחד בשמו, ואינדקס חלקי אינו נרשם כשלם
# ---------------------------------------------------------------------------


def _approved_pass(world):
    """מעבר מאושר של מילוי ראשון, אחרי שמעבר הפריסה עצר לאישור."""
    world.site.publish(SHA_A, site_pages())
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    world.events.clear()
    return run_request(
        world, svc.TRIGGER_APPROVED, approved_fingerprint=_state(world)["approval"]["fingerprint"]
    )


def test_quota_pauses_the_pass_and_a_later_pass_finishes_it(world, monkeypatch):
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    world.embed_failures[1] = (429, "http 429: RESOURCE_EXHAUSTED: quota")

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_PAUSED_QUOTA, svc.CODE_EMBEDDING_QUOTA)
    assert run["progress"] == {"embedded": 2, "to_embed": 4}
    assert len(_chunks(world)) == 2
    assert _state(world)["indexed_source_commit"] is None
    assert _event_names(world) == ["docs_index_quota_paused", "docs_index_pass"]

    world.embed_failures.clear()
    world.embed_calls.clear()
    done = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    assert done["status"] == svc.STATUS_COMPLETE
    assert sum(len(call["texts"]) for call in world.embed_calls) == 2
    assert _state(world)["indexed_source_commit"] == SHA_A


@pytest.mark.parametrize(
    "status,detail,code",
    [
        (400, "http 400: INVALID_ARGUMENT: bad request", svc.CODE_EMBEDDING_REJECTED),
        (413, "input_too_long index=0 bytes=40000 max=30000", svc.CODE_EMBEDDING_REJECTED),
        (404, "http 404: NOT_FOUND: no such model", svc.CODE_EMBEDDING_MODEL_MISSING),
        (422, "dimension_mismatch expected=4 actual=768", svc.CODE_EMBEDDING_DIMENSION_MISMATCH),
        (0, "deadline_exceeded", svc.CODE_DEADLINE_EXCEEDED),
        (0, "missing_api_key", svc.CODE_MISSING_API_KEY),
        (0, "transport_error: ConnectError", svc.CODE_EMBEDDING_UNAVAILABLE),
        (503, "http 503: UNAVAILABLE: overloaded", svc.CODE_EMBEDDING_UNAVAILABLE),
        (403, "http 403: PERMISSION_DENIED: key", svc.CODE_EMBEDDING_UNAVAILABLE),
        (200, "malformed_response: expected 4 embeddings", svc.CODE_EMBEDDING_UNKNOWN_STATUS),
        (422, "http 422: something else", svc.CODE_EMBEDDING_UNKNOWN_STATUS),
        (418, "http 418: teapot", svc.CODE_EMBEDDING_UNKNOWN_STATUS),
    ],
)
def test_an_embedding_failure_stops_the_pass_by_name(world, status, detail, code):
    world.embed_failures[0] = (status, detail)

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, code)
    assert detail in run["detail"]
    assert _chunks(world) == []
    assert _state(world)["indexed_source_commit"] is None
    assert _event_names(world) == ["docs_index_failed", "docs_index_pass"]


def test_a_missing_api_key_stops_before_anything_is_written(world):
    world.api_key = False

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_MISSING_API_KEY)
    assert world.embed_calls == [] and _chunks(world) == [] and _sections(world) == []
    assert "applied_built_at" not in _state(world)


def test_a_stop_request_stops_the_pass_before_the_next_batch(world, monkeypatch):
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    world.on_embed[0] = lambda: svc.request_stop(world.db)

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_STOPPED, None)
    assert len(world.embed_calls) == 1 and len(_chunks(world)) == 2
    assert _state(world)["indexed_source_commit"] is None
    # העצירה חלה על המעבר ההוא בלבד: המעבר הבא רץ עד הסוף.
    assert run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)["status"] == svc.STATUS_COMPLETE


def test_the_deadline_stops_the_pass_between_batches(world, monkeypatch):
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    world.on_embed[0] = lambda: world.clock.__setitem__(0, svc.PASS_DEADLINE_SECONDS + 1.0)

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_DEADLINE_EXCEEDED)
    assert len(world.embed_calls) == 1 and len(_chunks(world)) == 2
    assert _state(world)["indexed_source_commit"] is None


def _after_the_first_call(monkeypatch, collection, method, action):
    """עוטף מתודה של אוסף בדמה: אחרי הקריאה הראשונה רץ ``action`` (עצירה, שעון). מחזיר את מספר הקריאות."""
    original = getattr(collection, method)
    calls = []

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(method)
        if len(calls) == 1:
            action()
        return result

    monkeypatch.setattr(collection, method, wrapper)
    return calls


def _every_anchor_moved():
    pages = site_pages()
    for item in pages:
        for entry in item["sections"]:
            entry["anchor"] += "-moved"
    return pages


def test_a_stop_between_section_writes_stops_a_pass_with_nothing_to_embed(world, monkeypatch):
    """עצירה היא גם בלם, ולא רק חיסכון בהטמעות: מעבר שכולו כתיבות למסד נעצר לפני האצווה הבאה."""
    fill(world)
    monkeypatch.setattr(svc, "DB_BATCH_SIZE", 1)
    world.site.publish(SHA_B, _every_anchor_moved())
    world.embed_calls.clear()
    sections = world.db[contract.SECTIONS_COLLECTION]
    calls = _after_the_first_call(monkeypatch, sections, "bulk_write", lambda: svc.request_stop(world.db))

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_STOPPED, None)
    assert (run["plan"]["chunks_to_embed"], run["plan"]["sections_to_upsert"]) == (0, 4)
    assert len(calls) == 1 and world.embed_calls == []
    assert sum(s["anchor"].endswith("-moved") for s in _sections(world)) == 1
    assert _state(world)["indexed_source_commit"] is None


def test_a_stop_between_deletions_stops_them_and_reports_what_was_deleted(world, monkeypatch):
    fill(world)
    monkeypatch.setattr(svc, "DB_BATCH_SIZE", 1)
    world.site.publish(SHA_B, site_pages()[:1])
    chunks = world.db[contract.CHUNKS_COLLECTION]
    _after_the_first_call(monkeypatch, chunks, "delete_many", lambda: svc.request_stop(world.db))

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_STOPPED, None)
    assert (run["plan"]["chunks_to_delete"], run["plan"]["sections_to_delete"]) == (2, 2)
    assert run["deleted"] == {"chunks": 1, "sections": 0, "pages": 0}
    assert (len(_chunks(world)), len(_sections(world))) == (3, 4)
    assert _state(world)["indexed_source_commit"] is None


def test_the_deadline_is_checked_between_database_batches_too(world, monkeypatch):
    fill(world)
    monkeypatch.setattr(svc, "DB_BATCH_SIZE", 1)
    world.site.publish(SHA_B, _every_anchor_moved())
    sections = world.db[contract.SECTIONS_COLLECTION]
    _after_the_first_call(
        monkeypatch, sections, "bulk_write",
        lambda: world.clock.__setitem__(0, svc.PASS_DEADLINE_SECONDS + 1.0),
    )

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_DEADLINE_EXCEEDED)
    assert sum(s["anchor"].endswith("-moved") for s in _sections(world)) == 1


def test_a_pass_that_lost_its_lease_writes_nothing_more(world, monkeypatch):
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    world.site.publish(SHA_A, site_pages())
    run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)
    fingerprint = _state(world)["approval"]["fingerprint"]
    world.on_embed[0] = lambda: world.db[contract.STATE_COLLECTION].update_one(
        {"_id": svc.STATE_ID}, {"$set": {"lease_holder": "another-runner"}}
    )
    world.events.clear()

    assert svc.request_pass(
        world.db, trigger=svc.TRIGGER_APPROVED, approved_fingerprint=fingerprint
    ) == svc.REQUEST_STARTED

    state = _state(world)
    assert state["lease_holder"] == "another-runner"
    assert state["run"]["status"] == svc.STATUS_RUNNING
    assert len(_chunks(world)) == 2
    assert [(name, fields.get("code")) for name, _s, fields in world.events] == [
        ("docs_index_failed", svc.CODE_LEASE_LOST)
    ]


class _DropsTheLastWrite(FakeCollection):
    def bulk_write(self, requests, ordered=True, **kwargs):
        return super().bulk_write(list(requests)[:-1], ordered=ordered)


class _LosesADocumentAfterWriting(FakeCollection):
    def bulk_write(self, requests, ordered=True, **kwargs):
        result = super().bulk_write(requests, ordered=ordered)
        self.docs.pop()
        return result


def test_a_pass_that_stops_half_way_leaves_the_index_marked_partial(world, monkeypatch):
    """מרגע הכתיבה הראשונה המסד אינו תואם לקומיט הקודם, ולכן הוא לא נשאר רשום כשלם."""
    fill(world)
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 1)
    pages = site_pages()
    pages[0]["sections"][0]["markdown"] = "שינוי ראשון."
    pages[1]["sections"][0]["markdown"] = "שינוי שני."
    world.site.publish(SHA_B, pages)
    world.embed_failures[len(world.embed_calls) + 1] = (429, "http 429: RESOURCE_EXHAUSTED: quota")

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert run["status"] == svc.STATUS_PAUSED_QUOTA
    state = _state(world)
    assert state["indexed_source_commit"] is None
    assert state["applied_built_at"] == datetime.fromisoformat(LATE)


def test_the_lease_is_renewed_before_every_batch(world, monkeypatch):
    """גם lease שכבר פג — המעבר איטי, אבל איש לא לקח אותו — מתחדש אצל מי שמחזיק בו."""
    monkeypatch.setattr(svc, "GEMINI_MAX_BATCH_REQUESTS", 2)
    seen = []

    def expire_the_lease():
        world.db[contract.STATE_COLLECTION].update_one(
            {"_id": svc.STATE_ID}, {"$set": {"lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}}
        )

    world.on_embed[0] = expire_the_lease
    world.on_embed[1] = lambda: seen.append(_state(world)["lease_expires_at"])

    run = _approved_pass(world)

    assert run["status"] == svc.STATUS_COMPLETE
    assert seen and seen[0] > datetime.now(timezone.utc) + timedelta(seconds=svc.LEASE_SECONDS - 60)


def test_a_write_that_touches_fewer_documents_fails_the_pass(world):
    world.db.c[contract.CHUNKS_COLLECTION] = _DropsTheLastWrite()

    run = _approved_pass(world)

    assert (run["status"], run["code"], run["detail"]) == (
        svc.STATUS_FAILED, svc.CODE_WRITE_MISMATCH, "chunks: wrote 3 of 4"
    )
    assert _state(world)["indexed_source_commit"] is None


def test_a_verification_that_reads_back_less_fails_the_pass(world):
    world.db.c[contract.CHUNKS_COLLECTION] = _LosesADocumentAfterWriting()

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_VERIFY_MISMATCH)
    assert run["detail"] == "3 of 4 chunks, 4 of 4 sections and 2 of 2 pages match the export"
    assert _state(world)["indexed_source_commit"] is None


def test_a_section_missing_on_read_back_fails_the_pass_too(world):
    """הכרטיס בחיפוש נבנה מהסעיף: נתח בלי הסעיף שלו הוא תוצאה שבורה, ולכן גם הסעיפים מאומתים."""
    world.db.c[contract.SECTIONS_COLLECTION] = _LosesADocumentAfterWriting()

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_VERIFY_MISMATCH)
    assert run["detail"] == "4 of 4 chunks, 3 of 4 sections and 2 of 2 pages match the export"


def test_a_page_missing_on_read_back_fails_the_pass_too(world):
    """התצוגה המרונדרת נבנית מהעמוד, ולכן גם העמודים מאומתים לפני שהאינדקס נרשם כשלם."""
    world.db.c[contract.PAGES_COLLECTION] = _LosesADocumentAfterWriting()

    run = _approved_pass(world)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_VERIFY_MISMATCH)
    assert run["detail"] == "4 of 4 chunks, 4 of 4 sections and 1 of 2 pages match the export"
    assert _state(world)["indexed_source_commit"] is None


class _Unreachable(FakeCollection):
    def find(self, *args, **kwargs):
        raise ServerSelectionTimeoutError("no primary available")

    def find_one(self, *args, **kwargs):
        raise ServerSelectionTimeoutError("no primary available")


def test_a_database_error_while_planning_is_named_and_deletes_nothing(world):
    world.db.c[contract.CHUNKS_COLLECTION] = _Unreachable()
    world.site.publish(SHA_A, site_pages())

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)

    assert (run["status"], run["code"], run["detail"]) == (
        svc.STATUS_FAILED, svc.CODE_DATABASE_ERROR, "ServerSelectionTimeoutError"
    )


def test_unreadable_settings_fail_the_pass_before_any_download(world):
    world.db.c["system_config"] = _Unreachable()

    run = run_request(world, svc.TRIGGER_PUSH)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_SETTINGS_UNAVAILABLE)
    assert world.site.requests == []


def test_a_missing_commit_file_fails_without_reading_the_main_file(world):
    fill(world)
    world.site.publish(SHA_B, site_pages(), main=True)
    del world.site.files[contract.export_path_for_commit(SHA_B)]

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, EXPORT_NOT_FOUND)
    assert world.site.paths()[-1] == contract.export_path_for_commit(SHA_B)
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_a_commit_file_from_another_commit_is_stale_and_changes_nothing(world):
    fill(world)
    world.site.files[contract.export_path_for_commit(SHA_B)] = export_bytes(SHA_C, site_pages())

    run = run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_B)

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, EXPORT_STALE)
    assert _state(world)["indexed_source_commit"] == SHA_A


def test_a_request_read_back_in_a_shape_it_was_never_written_in_is_refused(world):
    svc._put_pending(world.db, _request())
    assert svc._take_lease(world.db, "runner")

    run = svc.run_pass(world.db, holder="runner", request={"trigger": "nightly"})

    assert (run["status"], run["code"]) == (svc.STATUS_FAILED, svc.CODE_INVALID_REQUEST)
    assert world.site.requests == []


def test_a_crash_inside_the_pass_is_recorded_without_its_message(world, caplog):
    def crash():
        raise RuntimeError("detail-that-stays-in-the-log")

    world.on_embed[0] = crash

    run = _approved_pass(world)

    assert (run["status"], run["code"], run["detail"]) == (svc.STATUS_FAILED, svc.CODE_UNEXPECTED, "RuntimeError")
    assert _state(world)["lease_holder"] is None
    assert [(name, fields.get("detail")) for name, _s, fields in world.events] == [
        ("docs_index_failed", "RuntimeError")
    ]
    assert "docs index pass crashed" in caplog.text


# ---------------------------------------------------------------------------
# ה-lease והתור
# ---------------------------------------------------------------------------


def test_a_request_while_a_pass_runs_waits_and_runs_after_it(world, monkeypatch):
    started = []
    monkeypatch.setattr(svc, "_runner_factory", started.append)
    world.site.publish(SHA_A, site_pages())

    assert svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH) == svc.REQUEST_STARTED
    assert svc.request_pass(world.db, trigger=svc.TRIGGER_DEPLOY, commit=SHA_A) == svc.REQUEST_QUEUED
    assert len(started) == 1
    started[0]()

    state = _state(world)
    assert state["run"]["trigger"] == svc.TRIGGER_DEPLOY
    assert (state["pending"], state["lease_holder"]) == (None, None)


def test_a_request_that_arrives_just_before_the_release_is_not_lost(world, monkeypatch):
    real_release = svc._release
    raced = []

    def release_with_a_request_racing_in(db, holder):
        if not raced:
            raced.append(True)
            svc._put_pending(db, _request(svc.TRIGGER_DEPLOY, commit=SHA_A))
        return real_release(db, holder)

    monkeypatch.setattr(svc, "_release", release_with_a_request_racing_in)
    world.site.publish(SHA_A, site_pages())

    run = run_request(world, svc.TRIGGER_PUSH)

    assert run["trigger"] == svc.TRIGGER_DEPLOY
    assert _state(world)["pending"] is None


def test_one_of_many_concurrent_requests_takes_the_lease(world, monkeypatch):
    started = []
    lock = threading.Lock()

    def record(target):
        with lock:
            started.append(target)

    monkeypatch.setattr(svc, "_runner_factory", record)
    barrier = threading.Barrier(8)
    results = []

    def ask():
        barrier.wait()
        results.append(svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH))

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(results) == [svc.REQUEST_QUEUED] * 7 + [svc.REQUEST_STARTED]
    assert len(started) == 1


def test_an_expired_lease_is_taken_over_and_a_live_one_is_not(world, monkeypatch):
    started = []
    monkeypatch.setattr(svc, "_runner_factory", started.append)
    now = datetime.now(timezone.utc)
    world.db[contract.STATE_COLLECTION].insert_one(
        {"_id": svc.STATE_ID, "lease_holder": "dead-runner", "lease_expires_at": now - timedelta(seconds=1),
         "pending": None, "stop_requested": False}
    )

    assert svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH) == svc.REQUEST_STARTED
    assert _state(world)["lease_holder"] not in (None, "dead-runner")
    assert svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH) == svc.REQUEST_QUEUED
    assert len(started) == 1


def test_a_runner_that_cannot_start_gives_the_lease_back_and_keeps_the_request(world, monkeypatch):
    def cannot_start(target):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(svc, "_runner_factory", cannot_start)

    with pytest.raises(RuntimeError):
        svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH)

    state = _state(world)
    assert state["lease_holder"] is None
    assert state["lease_expires_at"] < datetime.now(timezone.utc)
    assert state["pending"]["trigger"] == svc.TRIGGER_PUSH


def test_a_runner_whose_lease_was_taken_over_stops_without_running(world):
    svc._put_pending(world.db, _request())
    assert svc._take_lease(world.db, "runner-a")
    world.db[contract.STATE_COLLECTION].update_one({"_id": svc.STATE_ID}, {"$set": {"lease_holder": "runner-b"}})

    svc._run_until_idle(world.db, "runner-a")

    state = _state(world)
    assert state["lease_holder"] == "runner-b"
    assert state["pending"]["trigger"] == svc.TRIGGER_MANUAL_CHECK
    assert "run" not in state


def test_a_stop_also_drops_the_request_waiting_behind_the_pass(world):
    svc._put_pending(world.db, _request())
    assert svc._take_lease(world.db, "runner")
    svc._put_pending(world.db, _request(svc.TRIGGER_DEPLOY, commit=SHA_A))

    assert svc.request_stop(world.db) is True

    state = _state(world)
    assert (state["stop_requested"], state["pending"]) == (True, None)
    assert svc._claim_next(world.db, "runner") is None
    assert svc._release(world.db, "runner") is True


def test_a_stop_without_a_live_pass_is_refused(world):
    assert svc.request_stop(world.db) is False
    fill(world)
    assert svc.request_stop(world.db) is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"trigger": "nightly"},
        {"trigger": ["deploy"]},
        {"trigger": svc.TRIGGER_DEPLOY, "commit": "abc"},
        {"trigger": svc.TRIGGER_DEPLOY, "commit": SHA_A.upper()},
        {"trigger": svc.TRIGGER_APPROVED},
        {"trigger": svc.TRIGGER_MANUAL_CHECK, "approved_fingerprint": "a" * 64},
        {"trigger": svc.TRIGGER_APPROVED, "approved_fingerprint": "xyz"},
        {"trigger": svc.TRIGGER_APPROVED, "approved_fingerprint": "A" * 64},
        {"trigger": svc.TRIGGER_MANUAL_CHECK, "requested_by": True},
        {"trigger": svc.TRIGGER_MANUAL_CHECK, "requested_by": "7"},
    ],
)
def test_a_request_with_a_value_that_cannot_be_stored_is_refused(world, kwargs):
    with pytest.raises(ValueError):
        svc.request_pass(world.db, **kwargs)
    assert svc.read_state(world.db) is None


@pytest.mark.parametrize("value", ["a" * 64, "0123456789abcdef" * 4])
def test_fingerprints_in_the_grammar(value):
    assert svc.is_fingerprint(value) is True


@pytest.mark.parametrize("value", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, None, 7, ["a" * 64]])
def test_fingerprints_outside_the_grammar(value):
    assert svc.is_fingerprint(value) is False

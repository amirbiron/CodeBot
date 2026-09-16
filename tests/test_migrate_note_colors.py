"""בדיקות ל-``scripts/migrate_note_colors`` — התכנון, ומה שהמסד באמת החזיר.

הסקריפט מיישר את ``color`` במסד מ-``hex`` למזהה מהפלטה. שני הדברים
שנבדקים כאן הם בדיוק שני הדברים שיכולים להיכשל בשקט: שהוא **מחליט נכון**
מה זז ומה נשאר, ושהוא **קורא את מה שהמסד ענה** במקום להניח שכתיבה
שלא זרקה חריגה הצליחה.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.migrate_note_colors import (  # noqa: E402  (אחרי sys.path.insert, כמו בשאר טסטי הריפו)
    apply_color_migration,
    plan_color_migration,
)


class _FakeResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count


class _FakeNotes:
    """אוסף פתקים מדומה שמחזיק רשימת מסמכים ומגיב כמו מונגו.

    ``update_many`` מחזיר ``modified_count`` אמיתי שנגזר מהמסמכים שהשתנו —
    ולא מספר שהוזן מראש — כך שבדיקה של ספירת העדכונים לא יכולה לעבור על
    סקריפט שלא כתב כלום.
    """

    def __init__(self, docs):
        self.docs = [dict(d) for d in docs]
        self.forced_modified = None

    def distinct(self, field):
        seen = []
        for doc in self.docs:
            value = doc.get(field)
            if value not in seen:
                seen.append(value)
        return seen

    def count_documents(self, query):
        if not query:
            return len(self.docs)
        (field, wanted), = query.items()
        return sum(1 for d in self.docs if d.get(field) == wanted)

    def update_many(self, query, update):
        (field, wanted), = query.items()
        new_value = update["$set"][field]
        changed = 0
        for doc in self.docs:
            if doc.get(field) == wanted:
                doc[field] = new_value
                changed += 1
        if self.forced_modified is not None:
            return _FakeResult(self.forced_modified)
        return _FakeResult(changed)


class _FakeDB:
    def __init__(self, docs):
        self.sticky_notes = _FakeNotes(docs)


def _plan_targets(plan, key):
    return {value: target for value, target, _count in plan[key]}


def test_every_spelling_of_a_palette_shade_is_planned_onto_one_id():
    """ארבע צורות כתיבה של אותו צהוב — ערך אחד אחרי המיגרציה.

    זו כל מטרת הסקריפט: סינון לפי צבע מחפש ערך אחד, ומסד שמחזיק את אותו
    צבע בארבע צורות מחזיר רבע מהתשובה — בלי שגיאה ובלי סימן.

    נופלת אם הקיפול לפלטה או הנורמליזציה ייפסקו.
    """
    db = _FakeDB([
        {"color": "#FFFFCC"}, {"color": "#ffffcc"}, {"color": "#ffc"},
        {"color": "#ffffba"}, {"color": "yellow_light"},
    ])

    plan = plan_color_migration(db)

    assert _plan_targets(plan, "to_palette") == {
        "#FFFFCC": "yellow_light",
        "#ffffcc": "yellow_light",
        "#ffc": "yellow_light",
        "#ffffba": "yellow_light",
    }
    assert plan["already_ok"] == 1, "מי שכבר מזהה אינו נספר כעבודה"

    apply_color_migration(db, plan)
    assert {d["color"] for d in db.sticky_notes.docs} == {"yellow_light"}


def test_a_colour_outside_the_palette_is_left_alone_by_default():
    """הדרישה המפורשת: ``hex`` שאינו תואם **אינו נמחק ואינו משתנה בכוח**.

    נופלת אם ברירת המחדל תתחיל לגעת בצבעי legacy.
    """
    db = _FakeDB([{"color": "#AABBCC"}, {"color": "#123456"}])

    plan = plan_color_migration(db)

    assert plan["to_palette"] == []
    assert plan["legacy_reshaped"] == []
    apply_color_migration(db, plan)
    assert [d["color"] for d in db.sticky_notes.docs] == ["#AABBCC", "#123456"]


def test_normalize_legacy_is_opt_in_and_only_touches_the_spelling():
    """הדגל מיישר כתיב, ולעולם לא צבע.

    ``#AABBCC`` ← ``#aabbcc`` הוא אותו פיקסל בדיוק; מה שהוא **לא** עושה
    הוא להזיז אותו לצבע מהפלטה.

    נופלת אם הדגל יתחיל לקפל צבעים, או אם יפסיק ליישר כתיב.
    """
    db = _FakeDB([{"color": "#AABBCC"}])

    assert plan_color_migration(db)["legacy_reshaped"] == [], "כבוי כברירת מחדל"

    plan = plan_color_migration(db, normalize_legacy=True)
    assert _plan_targets(plan, "legacy_reshaped") == {"#AABBCC": "#aabbcc"}
    assert plan["to_palette"] == [], "ולא נכנס לפלטה"

    apply_color_migration(db, plan)
    assert [d["color"] for d in db.sticky_notes.docs] == ["#aabbcc"]


def test_a_value_that_cannot_be_read_at_all_is_reported_and_not_written():
    """‏``None``, מספר או זבל — נספרים ומדווחים, ולא מקבלים ברירת מחדל.

    שכבת התצוגה כבר מציגה אותם כצהוב; כתיבת הניחוש הזה למסד הייתה הופכת
    אותו לעובדה, ומוחקת את העדות שהיה שם משהו אחר.

    נופלת אם הסקריפט יתחיל לכתוב ברירת מחדל על ערכים שאינם ניתנים לפענוח.
    """
    db = _FakeDB([{"color": None}, {"color": 5}, {"color": "שטויות"}])

    plan = plan_color_migration(db)

    assert plan["unreadable"] == 3
    assert plan["to_palette"] == []
    apply_color_migration(db, plan)
    assert [d["color"] for d in db.sticky_notes.docs] == [None, 5, "שטויות"]


def test_running_twice_finds_nothing_left_to_do():
    """בטוח להרצה חוזרת — לא הצהרה, אלא הרצה שנייה בפועל.

    נופלת אם הסקריפט יתחיל לתכנן עבודה על מה שכבר יושר.
    """
    db = _FakeDB([{"color": "#FFFFCC"}, {"color": "#ffdbdf"}])

    first = plan_color_migration(db)
    apply_color_migration(db, first)

    second = plan_color_migration(db)
    assert second["to_palette"] == []
    assert second["legacy_reshaped"] == []
    assert second["already_ok"] == 2


def test_a_write_that_moved_fewer_rows_than_counted_is_surfaced():
    """**מה שהמסד ענה, לא מה שביקשנו.**

    ``update_many`` אינו זורק כשלא נגע בכלום; הוא מדווח ב-``modified_count``.
    סקריפט שסופר את מה שתכנן היה מדפיס "עודכנו 3" גם כשאפס נכתבו — בדיוק
    האישור השקרי של ``CRITICAL-PATTERNS`` K11.

    נופלת אם המונה ייגזר מהתוכנית במקום מתשובת המסד.
    """
    db = _FakeDB([{"color": "#FFFFCC"}, {"color": "#FFFFCC"}, {"color": "#FFFFCC"}])
    plan = plan_color_migration(db)
    assert plan["to_palette"] == [("#FFFFCC", "yellow_light", 3)]

    db.sticky_notes.forced_modified = 1  # המסד מדווח על פחות ממה שנספר

    outcome = apply_color_migration(db, plan)

    assert outcome["moved"] == 1, "המונה נגזר מתשובת המסד"
    assert outcome["mismatched"] == 1, "והפער מדווח ולא נבלע"


@pytest.mark.parametrize("stored", [None, 5, [], {}, "", "yellow_light", "#ffffba"])
def test_planning_never_raises_on_whatever_sits_in_the_field(stored):
    """המסד הוא קלט חיצוני לכל דבר — גיבוי משוחזר, כתיבה ישנה, זבל.

    תכנון שקורס על מסמך אחד הוא סקריפט שאי אפשר להריץ כדי לראות מה המצב,
    וזה בדיוק מה שהוא נועד לאפשר.

    נופלת אם בדיקת טיפוס תוסר מהשכבה הטהורה.
    """
    plan = plan_color_migration(_FakeDB([{"color": stored}]))
    assert plan["total_notes"] == 1

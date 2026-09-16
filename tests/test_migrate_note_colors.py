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
    """אוסף פתקים מדומה שמגיב **כמו מונגו**, ולא כמו שנוח לבדיקה.

    ``update_many`` מחזיר ``modified_count`` אמיתי שנגזר מהמסמכים שהשתנו —
    ולא מספר שהוזן מראש — כך שבדיקה של ספירת העדכונים לא יכולה לעבור על
    סקריפט שלא כתב כלום.

    **ושלוש התנהגויות המערך משוחזרות כאן בכוונה**, כי בלעדיהן הבדיקה
    אינה מסוגלת ליפול על הבאג שהן יוצרות. כל אחת מתועדת במקור:

    * ``distinct`` **מפרק** מערך לאיברים — "distinct considers each element
      of the array as a separate value" (``reference/command/distinct``).
    * שאילתת שוויון תואמת **איבר** במערך — "To query if the array field
      contains at least one element with the specified value, use the filter
      ``{ <field>: <value> }``" (``tutorial/query-arrays``).
    * ``$type: "array"`` מתייחס ל**שדה עצמו** — "Queries for ``$type:
      'array'`` return documents where the field itself is an array"
      (``reference/operator/query/type``).

    ``$type`` כאן מקבל ``"array"`` בלבד, כי זה הטיפוס היחיד שהסקריפט
    שואל עליו. תמיכה רחבה יותר הייתה מדמה התנהגות שאיש אינו נשען עליה,
    ולכן גם אינה נבדקת.
    """

    def __init__(self, docs):
        self.docs = [dict(d) for d in docs]
        self.forced_modified = None

    def distinct(self, field):
        seen = []
        for doc in self.docs:
            value = doc.get(field)
            # פירוק המערך, בדיוק כמו מונגו
            for item in (value if isinstance(value, list) else [value]):
                if item not in seen:
                    seen.append(item)
        return seen

    @staticmethod
    def _matches(doc, field, cond):
        value = doc.get(field)
        if not isinstance(cond, dict) or not any(k.startswith("$") for k in cond):
            # שוויון: על שדה מערך — תואם אם **איבר** שווה.
            #
            # **השורה הזו נראית חסרת משקל ואינה.** מוטציה שמסירה אותה לבדה
            # אינה מפילה כלום, כי ההגנה מסננת את המערך קודם. אבל מוטציה
            # שמסירה את **ההגנה** ואת השורה הזו יחד — עוברת: בלי הסמנטיקה
            # הזו ה-fake פשוט אינו מסוגל לשחזר את הבאג. כלומר זו החוליה
            # שהופכת את הבדיקה למסוגלת להיכשל, ומחיקתה תשתיק אותה בשקט.
            return value == cond or (isinstance(value, list) and cond in value)
        for op, operand in cond.items():
            if op == "$eq":
                if not (value == operand or (isinstance(value, list) and operand in value)):
                    return False
            elif op == "$type":
                if operand != "array":
                    raise NotImplementedError("ה-fake מכיר רק $type: 'array'")
                if not isinstance(value, list):
                    return False
            elif op == "$not":
                if _FakeNotes._matches(doc, field, operand):
                    return False
            else:
                raise NotImplementedError(f"אופרטור שאינו נתמך ב-fake: {op}")
        return True

    def _select(self, query):
        if not query:
            return list(self.docs)
        (field, cond), = query.items()
        return [d for d in self.docs if self._matches(d, field, cond)]

    def count_documents(self, query):
        return len(self._select(query))

    def update_many(self, query, update):
        (field, _cond), = query.items()
        new_value = update["$set"][field]
        matched = self._select(query)
        for doc in matched:
            doc[field] = new_value
        if self.forced_modified is not None:
            return _FakeResult(self.forced_modified)
        return _FakeResult(len(matched))


class _FakeDB:
    def __init__(self, docs):
        self.sticky_notes = _FakeNotes(docs)


def _plan_targets(plan, key):
    return {value: target for value, target, _count in plan[key]}


def test_every_spelling_of_a_shade_is_planned_onto_its_own_id():
    """שלוש צורות כתיבה של אותו צהוב — ערך אחד אחרי המיגרציה.

    זו כל מטרת הסקריפט: סינון לפי צבע מחפש ערך אחד, ומסד שמחזיק את אותו
    צבע בשלוש צורות מחזיר שליש מהתשובה — בלי שגיאה ובלי סימן.

    **ושני הצהובים נשארים נפרדים.** ``#ffffba`` אינו צורת כתיבה של
    ``#FFFFCC`` אלא צבע אחר בפלטה, ומיפוי שהיה מאחד אותם היה משנה את
    הגוון של כל פתק שקיים היום.

    נופלת אם הקיפול לפלטה או הנורמליזציה ייפסקו, וגם אם שני הצהובים
    יתמזגו.
    """
    db = _FakeDB([
        {"color": "#FFFFCC"}, {"color": "#ffffcc"}, {"color": "#ffc"},
        {"color": "#ffffba"}, {"color": "yellow"},
    ])

    plan = plan_color_migration(db)

    assert _plan_targets(plan, "to_palette") == {
        "#FFFFCC": "yellow",
        "#ffffcc": "yellow",
        "#ffc": "yellow",
        "#ffffba": "yellow_light",
    }
    assert plan["already_ok"] == 1, "מי שכבר מזהה אינו נספר כעבודה"

    apply_color_migration(db, plan)
    assert sorted({d["color"] for d in db.sticky_notes.docs}) == ["yellow", "yellow_light"]


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


def test_a_note_whose_colour_is_an_array_is_reported_and_never_overwritten():
    """**המקרה היחיד שבו הסקריפט הזה יכול להרוס נתונים במקום ליישר אותם.**

    מסמך שבו ``color`` הוא מערך אינו פתק חוקי — אף כותב אינו מייצר אחד —
    אבל הוא יכול לשבת במסד מכתיבה ישירה או מגיבוי פגום. שלוש התנהגויות
    של מונגו מצטרפות שם לשרשרת: ``distinct`` מפרק את המערך ומגיש את
    ``"#FFFFCC"`` כאילו היה ערך רגיל, שאילתת שוויון תופסת את המסמך דרך
    האיבר, ו-``$set`` דורס את **כל** השדה — כלומר האיברים האחרים נמחקים,
    בפעולה שכל מטרתה לא לשנות שום צבע בכוח.

    נופלת אם ``$not: {$type: "array"}`` יוסר מהפילטר.
    """
    db = _FakeDB([
        {"color": ["#FFFFCC", "משהו אחר"]},   # פגום — לא לגעת
        {"color": "#FFFFCC"},                  # תקין — כן ליישר
    ])

    plan = plan_color_migration(db)

    assert plan["array_valued"] == 1, "המסמך הפגום נספר ומדווח"
    assert plan["to_palette"] == [("#FFFFCC", "yellow", 1)], (
        "רק המסמך התקין נספר לעדכון — ``distinct`` הגיש את שניהם"
    )

    apply_color_migration(db, plan)

    assert db.sticky_notes.docs[0]["color"] == ["#FFFFCC", "משהו אחר"], "המערך שרד שלם"
    assert db.sticky_notes.docs[1]["color"] == "yellow"


def test_a_value_that_only_exists_inside_an_array_is_not_planned_at_all():
    """ערך שהגיע **רק** מפירוק מערך אינו עבודה, וגם אינו ``legacy``.

    בלי הבדיקה הזו הוא היה נספר בדוח כאילו יש פתק שנושא אותו — מספר
    שאינו מתאר שום מסמך, ושהיה מבלבל בדיוק את מי שמריץ כדי לראות מה המצב.
    היא גם הבדיקה היחידה שנשענת על כך שה-fake **מפרק** מערכים כמו מונגו:
    בלי הפירוק הערך לא היה מגיע לסריקה כלל, ולא היה מה לדלג עליו.

    נופלת אם הדילוג על ``count == 0`` יוסר, ואם ה-fake יפסיק לפרק.
    """
    db = _FakeDB([{"color": ["#FFFFCC"]}])

    assert db.sticky_notes.distinct("color") == ["#FFFFCC"], (
        "``distinct`` מפרק את המערך — זו ההנחה שכל הסעיף הזה עומד עליה"
    )

    plan = plan_color_migration(db)

    assert plan["to_palette"] == []
    assert plan["already_ok"] == 0
    assert plan["unreadable"] == 0
    assert plan["array_valued"] == 1
    apply_color_migration(db, plan)
    assert db.sticky_notes.docs[0]["color"] == ["#FFFFCC"]


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
    assert plan["to_palette"] == [("#FFFFCC", "yellow", 3)]

    db.sticky_notes.forced_modified = 1  # המסד מדווח על פחות ממה שנספר

    outcome = apply_color_migration(db, plan)

    assert outcome["moved"] == 1, "המונה נגזר מתשובת המסד"
    assert outcome["mismatched"] == 1, "והפער מדווח ולא נבלע"


@pytest.mark.parametrize("stored", [None, 5, [], {}, "", "yellow", "#ffffcc"])
def test_planning_never_raises_on_whatever_sits_in_the_field(stored):
    """המסד הוא קלט חיצוני לכל דבר — גיבוי משוחזר, כתיבה ישנה, זבל.

    תכנון שקורס על מסמך אחד הוא סקריפט שאי אפשר להריץ כדי לראות מה המצב,
    וזה בדיוק מה שהוא נועד לאפשר.

    נופלת אם בדיקת טיפוס תוסר מהשכבה הטהורה.
    """
    plan = plan_color_migration(_FakeDB([{"color": stored}]))
    assert plan["total_notes"] == 1

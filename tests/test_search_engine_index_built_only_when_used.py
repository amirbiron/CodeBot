"""האינדקס בזיכרון נבנה רק עבור סוגי החיפוש שקוראים ממנו.

``AdvancedSearchEngine.search`` נהג לבנות את ``SearchIndex`` לפני שבדק איזה סוג
חיפוש התבקש. ‏``CONTENT``, ``REGEX`` ו-``FUZZY`` סורקים את ה-DB בעצמם ואינם
נוגעים באינדקס — ולכן הבנייה עבורם הייתה סריקה מלאה נוספת של כל קבצי המשתמש,
כולל ``code``, שאיש אינו קורא. ‏``CONTENT`` הוא ברירת המחדל של החיפוש ב-WebApp,
כך שזה היה המסלול הרגיל.

הטסטים כאן נועלים את שני הכיוונים: שהאינדקס **לא** נבנה במסלולים שאינם צורכים
אותו, ושהוא **כן** ממשיך להיבנות ב-``TEXT`` וב-``FUNCTION``, שבלעדיו אין להם
מה להחזיר.
"""

import pytest

import search_engine as se


@pytest.fixture
def rebuild_spy(monkeypatch):
    """מחליף את ``rebuild_index`` במרגל שסופר קריאות ואינו פונה ל-DB."""
    calls: list[int] = []

    def _spy(self, user_id: int) -> None:
        calls.append(int(user_id))
        # מדמה בנייה שהסתיימה, כדי ש-``should_rebuild`` לא יבקש עוד אחת
        self.last_update = se.datetime.now(se.timezone.utc)

    monkeypatch.setattr(se.SearchIndex, "rebuild_index", _spy, raising=True)
    return calls


class _StubDB:
    """דמה של שכבת ה-DB עם קובץ יחיד שמכיל את המילה ``needle``."""

    def __init__(self) -> None:
        self.doc = {
            "file_name": "demo.py",
            "code": "def helper():\n    return 'needle'\n",
            "programming_language": "python",
            "tags": ["demo"],
            "created_at": se.datetime.now(se.timezone.utc),
            "updated_at": se.datetime.now(se.timezone.utc),
            "version": 1,
        }

    def get_user_files(self, user_id, limit=200, *, skip=0, projection=None):
        # עמוד ראשון בלבד; אחריו רשימה ריקה כדי לעצור את לולאת העימוד
        return [dict(self.doc)] if skip == 0 else []

    def get_latest_version(self, user_id, file_name):
        return dict(self.doc)


@pytest.fixture
def stub_db(monkeypatch):
    db = _StubDB()
    monkeypatch.setattr(se, "db", db, raising=False)
    return db


@pytest.mark.parametrize(
    "search_type",
    [se.SearchType.CONTENT, se.SearchType.REGEX, se.SearchType.FUZZY],
)
def test_a_search_that_never_reads_the_index_does_not_build_it(
    search_type, rebuild_spy, stub_db
):
    engine = se.AdvancedSearchEngine()

    engine.search(user_id=1, query="needle", search_type=search_type)

    assert rebuild_spy == [], (
        f"{search_type} אינו קורא מהאינדקס, ולכן אסור שיפעיל בנייה שלו"
    )


@pytest.mark.parametrize(
    "search_type",
    [se.SearchType.TEXT, se.SearchType.FUNCTION],
)
def test_a_search_that_reads_the_index_still_builds_it(
    search_type, rebuild_spy, stub_db
):
    engine = se.AdvancedSearchEngine()

    engine.search(user_id=1, query="needle", search_type=search_type)

    assert rebuild_spy == [1], (
        f"{search_type} נשען על האינדקס — בלי בנייה אין לו מה להחזיר"
    )


def test_an_unknown_search_type_falls_back_to_text_and_builds_the_index(
    rebuild_spy, stub_db
):
    """``SearchType.SEMANTIC`` נופל ל-``_text_search`` דרך ה-``else``."""
    engine = se.AdvancedSearchEngine()

    engine.search(user_id=1, query="needle", search_type=se.SearchType.SEMANTIC)

    assert rebuild_spy == [1]


@pytest.mark.parametrize(
    "search_type",
    [se.SearchType.TEXT, se.SearchType.FUNCTION],
)
def test_the_env_switch_turns_the_memory_index_off(
    search_type, rebuild_spy, stub_db, monkeypatch
):
    """``SEARCH_MEMORY_INDEX_ENABLED=false`` מכבה גם את הענפים שכן צורכים אותו."""
    monkeypatch.setattr(se.config, "SEARCH_MEMORY_INDEX_ENABLED", False, raising=False)
    engine = se.AdvancedSearchEngine()

    results = engine.search(user_id=1, query="needle", search_type=search_type)

    assert rebuild_spy == []
    # אינדקס ריק ⇒ אין מועמדים; ב-WebApp ``_safe_search`` נופל מכאן ל-$text
    assert results == []
    # אינדקס שלא נבנה גם לא נשמר, כדי שלא ידלוף כאינדקס "טרי" להשלמות
    assert engine.indexes == {}


def test_the_switch_is_on_when_the_config_does_not_carry_it():
    """ברירת המחדל שומרת על ההתנהגות הקיימת — הכיבוי הוא בחירה מפורשת.

    ‏``tests/config.py`` מצל על מודול הקונפיג האמיתי ואינו מכיל את השדה, ולכן
    מה שנבדק כאן הוא בדיוק נתיב ה-fallback: קונפיג בלי המפתח ⇒ האינדקס פעיל.
    ברירת המחדל של השדה עצמו ב-``BotConfig`` נבדקת ב-``tests/test_config.py``.
    """
    assert not hasattr(se.config, "SEARCH_MEMORY_INDEX_ENABLED")
    assert se._memory_index_enabled() is True


def test_the_log_line_the_user_sees_is_gone_for_a_content_search(stub_db, caplog):
    """אימות מול הפלט שהמשתמש באמת רואה, עם ``rebuild_index`` האמיתי.

    השורה ``בונה אינדקס חיפוש עבור משתמש <id>`` היא הסימפטום שדווח מהלוג של
    הפרודקשן. הטסטים שמעליה מרגלים אחרי הקריאה; זה בודק את התוצאה הנצפית.
    """
    engine = se.AdvancedSearchEngine()

    with caplog.at_level("INFO", logger="search_engine"):
        engine.search(user_id=1, query="needle", search_type=se.SearchType.CONTENT)
    assert "בונה אינדקס חיפוש" not in caplog.text

    caplog.clear()
    with caplog.at_level("INFO", logger="search_engine"):
        engine.search(user_id=1, query="needle", search_type=se.SearchType.TEXT)
    assert "בונה אינדקס חיפוש" in caplog.text


def test_eager_build_restores_the_warm_index_for_suggestions(stub_db, monkeypatch):
    """``SEARCH_MEMORY_INDEX_EAGER_BUILD=true`` מחזיר את ההתנהגות שלפני השינוי.

    זו הסיבה שהמתג קיים: ``suggest_completions`` קורא את האינדקס דרך
    ``_get_ready_index``, שבמכוון אינו בונה אותו. לפני השינוי חיפוש ``CONTENT``
    בנה אותו כתופעת לוואי, וההשלמה נהנתה מזה. הטסט נועל את שני הכיוונים.
    """
    engine = se.AdvancedSearchEngine()

    # ברירת מחדל: אין חימום, ולכן אין ממה להציע
    engine.search(user_id=1, query="needle", search_type=se.SearchType.CONTENT)
    assert engine.indexes == {}
    assert engine.suggest_completions(1, "need", limit=10) == []

    # מתג דלוק: האינדקס חם, וההשלמה מוצאת מילים מתוך תוכן הקובץ
    monkeypatch.setattr(se.config, "SEARCH_MEMORY_INDEX_EAGER_BUILD", True, raising=False)
    warm = se.AdvancedSearchEngine()
    warm.search(user_id=1, query="needle", search_type=se.SearchType.CONTENT)
    assert list(warm.indexes) == [1]
    assert "needle" in warm.suggest_completions(1, "need", limit=10)


def test_the_master_switch_wins_over_eager_build(rebuild_spy, stub_db, monkeypatch):
    """כיבוי מלא גובר על חימום מקדים — אין נתיב שבו השילוב בונה אינדקס."""
    monkeypatch.setattr(se.config, "SEARCH_MEMORY_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(se.config, "SEARCH_MEMORY_INDEX_EAGER_BUILD", True, raising=False)
    engine = se.AdvancedSearchEngine()

    engine.search(user_id=1, query="needle", search_type=se.SearchType.CONTENT)

    assert rebuild_spy == []
    assert engine.indexes == {}


def test_eager_build_is_off_when_the_config_does_not_carry_it():
    assert not hasattr(se.config, "SEARCH_MEMORY_INDEX_EAGER_BUILD")
    assert se._memory_index_eager_build() is False

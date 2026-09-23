"""רשימות הקבצים ב-``/files``: שורה אחת לכל קובץ, בגרסה האחרונה שלו — ובתקציב הזיכרון של Atlas Flex.

**מה נבדק.** כל עריכה יוצרת מסמך גרסה חדש ב-``code_snippets``, ולכן "קובץ" הוא ``(user_id, file_name)`` ולא מסמך. שני באגים עלו בפרודקשן ב-23.9.2026, ושניהם נבדקים כאן דרך הראוט עצמו — המסלול שהדפדפן עובר בו — מול מונגו אמיתי:

1. **מועדפים** הציגו שורה לכל **גרסה**, כי ``api_toggle_favorite`` מסמן את כל הגרסאות של הקובץ והענף לא קיבץ בכלל. אותו ענף שירת גם תצוגת ריפו ספציפי.
2. **"שאר קבצים"** החזיר 500 עם שגיאה 292 (``QueryExceededMemoryLimitNoDiskUseAllowed``). הענף **כן** קיבץ, אבל המיון שלפני הקיבוץ נספר על מסמכים **מלאים**, כולל גוף הקובץ. למה, ומה נמדד על הקלאסטר — ב-docstring של ``_latest_version_per_file_stages`` ב-``webapp/app.py``.

**למה מונגו אמיתי ולא סטאב.** סטאב שמדמה ``$group`` מוכיח את הסטאב ולא את השאילתה, ושגיאה 292 היא התנהגות של המנוע — אין דרך לשחזר אותה בדמה. לכן ``wired_mongo``, ובלי ``NOTE_FONTS_TEST_MONGO_URI`` נגיש הקובץ מדולג. ⚠️ האם הן רצות ב-CI — ראו את ההערה ליד ``NOTE_FONTS_TEST_MONGO_URI`` ב-``.github/workflows/ci.yml``. ב-23.9.2026 הכתובת שם אינה נגישה, והן מדלגות; הן רצות מקומית.

**איך משחזרים את Flex.** שני הבדלים בין שרת מקומי ל-Atlas Flex, ושניהם מוגדרים בפיקסצ'ר ``flex_budget``:

- **תקרת המיון** (``internalQueryMaxBlockingSortMemoryUsageBytes``) מוקטנת ל-``SORT_BUDGET_BYTES``, והנתונים מוקטנים איתה באותו יחס שהיה בפרודקשן: גוף הקובץ גדול מהתקרה, והמטא-דאטה קטן ממנה בהרבה. הערך של Flex והמדידות — באותו docstring.
- **``allowDiskUse``.** Atlas Flex מתעלם ממנו ומתנהג כאילו הוא ``false`` (https://www.mongodb.com/docs/atlas/reference/free-shared-limitations/). שרת מקומי כן מכבד אותו ופשוט היה כותב לדיסק, ולכן הפיקסצ'ר מכבה אותו בצד הלקוח, על ``Collection.aggregate`` של PyMongo. כל השאר — השרת, הצינור, הראוט — אמיתי.

הרצה מקומית::

    MONGODB_URL='mongodb://127.0.0.1:27017/test' \\
    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \\
        pytest tests/test_files_list_one_row_per_file.py -v

שני המשתנים מצביעים לאותו שרת, כמו בהוראות ב-``docs/testing.rst``. אם ``MONGODB_URL`` מצביע לכתובת שאין בה שרת, קוד רקע שרץ בייבוא נכשל בהתחברות, ``get_db`` לא מנסה שוב עד שעובר ``MONGODB_CONNECT_RETRY_COOLDOWN_SECONDS``, והפיקסצ'ר מקבל ``None``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("flask")
pytest.importorskip("pymongo")

from bson import ObjectId  # noqa: E402

USER_ID = 7171
REPO_TAG = "repo:amirbiron/demo"
CREATED = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)

#: תקרת מיון מוקטנת לבדיקה. מספיקה בשפע למטא-דאטה של כל מסמכי הבדיקה, וקטנה מהגודל המלא שלהם.
SORT_BUDGET_BYTES = 1_000_000
#: גוף קובץ לכל גרסה בבדיקות התקציב. תשעה כאלה הם ~1.35MB — מעל ``SORT_BUDGET_BYTES``.
BIG_BODY_BYTES = 150_000
#: קבצים בבדיקת התקציב. תשעה ולא שלושה, כדי שגם הגרסאות **האחרונות** לבדן — מה שהמיון שאחרי הקיבוץ מחזיק — יהיו גדולות מהתקרה.
BUDGET_FILES = 9


# ------------------------------------------------------------------ חיווט


class _CacheDisabled:
    """העמוד שומר HTML מרונדר בקאש; בבדיקה כל בקשה חייבת להגיע למסד."""

    is_enabled = False


@pytest.fixture
def wa(wired_mongo, monkeypatch):
    monkeypatch.setattr(wired_mongo, "cache", _CacheDisabled(), raising=True)
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    db.recent_opens.delete_many({})
    return wired_mongo


@pytest.fixture
def flex_budget(wa, monkeypatch):
    """תקרת מיון קטנה ו-``allowDiskUse`` כבוי — כמו ב-Atlas Flex.

    ``setParameter`` חל על כל השרת, ולכן הערך הקודם נשמר ומוחזר בסיום, גם כשהבדיקה נכשלה.
    """
    import pymongo.collection

    admin = wa.get_db().client.admin
    previous = admin.command({"setParameter": 1, "internalQueryMaxBlockingSortMemoryUsageBytes": SORT_BUDGET_BYTES})["was"]

    original_aggregate = pymongo.collection.Collection.aggregate

    def _aggregate_without_disk(self, pipeline, *args, **kwargs):
        kwargs["allowDiskUse"] = False
        return original_aggregate(self, pipeline, *args, **kwargs)

    monkeypatch.setattr(pymongo.collection.Collection, "aggregate", _aggregate_without_disk)
    try:
        yield wa
    finally:
        admin.command({"setParameter": 1, "internalQueryMaxBlockingSortMemoryUsageBytes": previous})


def _seed(wa, file_name, versions=3, *, favorite=(), marked_at=None, tags=(), body_bytes=0, user_id=USER_ID):
    """קובץ אחד בכמה גרסאות, כולן פעילות. מחזיר את המזהים לפי סדר הגרסה.

    המסמכים בנויים כמו שהכותבים בייצור בונים אותם: ``created_at`` משותף לכל הגרסאות (הוא שייך לקובץ), ``updated_at`` עולה, ו-``file_size``/``lines_count`` שמורים. ``favorite`` הוא רשימת מספרי הגרסאות שמסומנות מועדפות, ו-``marked_at`` הוא ה-``favorited_at`` שלהן.
    """
    db = wa.get_db()
    ids = []
    for version in range(1, versions + 1):
        code = f"# {file_name} גרסה {version}\n" + ("x" * body_bytes)
        doc = {
            "_id": ObjectId(),
            "user_id": user_id,
            "file_name": file_name,
            "code": code,
            "programming_language": "markdown",
            "description": f"תיאור {file_name}",
            "tags": list(tags),
            "version": version,
            "is_active": True,
            "created_at": CREATED,
            "updated_at": CREATED + timedelta(hours=version),
            "file_size": len(code.encode("utf-8")),
            "lines_count": len(code.split("\n")),
        }
        if version in favorite:
            doc["is_favorite"] = True
            doc["favorited_at"] = marked_at or (CREATED + timedelta(days=1))
        db.code_snippets.insert_one(doc)
        ids.append(doc["_id"])
    return ids


def _get(wa, url):
    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה", "is_admin": False, "is_premium": False}
    return client.get(url)


def _shown_ids(html):
    """המזהים של כרטיסי הקבצים שהעמוד הציג, לפי הסדר."""
    return re.findall(r'class="glass-card file-card" data-file-id="([0-9a-f]{24})"', html)


def _total(html):
    """המספר ב"מציג X מתוך Y קבצים" — ה-Y, כלומר מה שהעמוד חושב שיש."""
    match = re.search(r"מציג\s+(\d+)\s+מתוך\s+(\d+)\s+קבצים", html)
    assert match, "לא נמצאה שורת הספירה בעמוד"
    return int(match.group(2))


# -------------------------------------------- שורה אחת לכל קובץ, בגרסה האחרונה


def test_favorites_list_each_file_once_at_its_latest_version(wa):
    """שלוש גרסאות מסומנות — כמו ש-``api_toggle_favorite`` משאיר אותן — הן שורה אחת, של הגרסה האחרונה."""
    three = _seed(wa, "plan.md", favorite=(1, 2, 3))
    single = _seed(wa, "notes.md", versions=1, favorite=(1,))
    _seed(wa, "not-a-favorite.md", versions=2)

    response = _get(wa, "/files?category=favorites")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    shown = _shown_ids(html)
    assert sorted(shown) == sorted([str(three[-1]), str(single[0])]), f"הוצגו: {shown}"
    assert _total(html) == 2, "הספירה סופרת גרסאות ולא קבצים"


def test_a_favorite_whose_latest_version_lost_the_mark_is_shown_at_its_latest_version(wa):
    """הכלל ברמת הקובץ: קובץ מועדף אם **איזושהי** גרסה פעילה שלו מסומנת — ומוצגת הגרסה האחרונה שלו.

    זה המצב שנמצא בפרודקשן בשני קבצים: עריכה בוובאפ כתבה גרסה חדשה בלי סימון המועדף. קיבוץ שמסנן את הגרסאות **לפני** שהוא בוחר את האחרונה היה מציג גרסה ישנה, ולחיצה עליה הייתה פותחת תוכן מלפני כמה עריכות.
    """
    ids = _seed(wa, "summary.md", favorite=(1, 2))

    html = _get(wa, "/files?category=favorites").get_data(as_text=True)

    assert _shown_ids(html) == [str(ids[-1])]


def test_favorites_are_ordered_by_the_last_mark_in_the_file(wa):
    """``favorited_at`` של השורה הוא הסימון האחרון **בקובץ**, והמועדפים ממוינים לפיו כברירת מחדל.

    בקובץ שהגרסה האחרונה שלו לא מסומנת, ל-``favorited_at`` של הגרסה עצמה אין ערך. שורה שלוקחת אותו מהגרסה הייתה יורדת לסוף הרשימה, אף שהקובץ סומן אחרון.
    """
    marked_last = _seed(wa, "marked-last.md", versions=2, favorite=(1,), marked_at=CREATED + timedelta(days=3))
    marked_first = _seed(wa, "marked-first.md", versions=1, favorite=(1,), marked_at=CREATED + timedelta(days=2))

    html = _get(wa, "/files?category=favorites").get_data(as_text=True)

    assert _shown_ids(html) == [str(marked_last[-1]), str(marked_first[0])]


def test_a_file_without_a_stored_size_is_listed_and_not_hidden(wa):
    """מסמך בלי ``file_size`` שמור נחשב לא-ריק — ``_NON_EMPTY_FILE_MATCH`` ב-``webapp/app.py``.

    בלי ``code`` אי אפשר לדעת את גודלו, והסתרת קובץ של משתמש גרועה מהצגתו. ובאותו מבחן, הצד השני: קובץ שהגרסה האחרונה שלו ריקה אינו מוצג.
    """
    db = wa.get_db()
    unsized = _seed(wa, "legacy.md", versions=1)
    db.code_snippets.update_many({"file_name": "legacy.md"}, {"$unset": {"file_size": "", "lines_count": ""}})
    _seed(wa, "empty.md", versions=1)
    db.code_snippets.update_many({"file_name": "empty.md"}, {"$set": {"code": "", "file_size": 0, "lines_count": 0}})

    for url in ("/files", "/files?category=other"):
        html = _get(wa, url).get_data(as_text=True)
        assert _shown_ids(html) == [str(unsized[0])], url
        assert _total(html) == 1, url


def test_other_lists_each_file_once_at_its_latest_version(wa):
    ids = _seed(wa, "draft.md")
    single = _seed(wa, "one.py", versions=1)

    response = _get(wa, "/files?category=other")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert sorted(_shown_ids(html)) == sorted([str(ids[-1]), str(single[0])])
    assert _total(html) == 2


def test_the_default_page_lists_each_file_once_at_its_latest_version(wa):
    ids = _seed(wa, "draft.md")

    html = _get(wa, "/files").get_data(as_text=True)

    assert _shown_ids(html) == [str(ids[-1])]
    assert _total(html) == 1


def test_a_single_repo_view_lists_each_file_once(wa):
    """``category=repo&repo=X`` עבר באותו ענף בלי קיבוץ כמו המועדפים."""
    ids = _seed(wa, "service.py", tags=(REPO_TAG,))

    response = _get(wa, "/files?category=repo&repo=amirbiron/demo")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert _shown_ids(html) == [str(ids[-1])]
    assert _total(html) == 1


# ------------------------------------- הקטגוריה של קובץ נקבעת לפי הגרסה האחרונה שלו


def _retag(wa, doc_id, tags):
    """התגיות של גרסה אחת — כמו עריכה שמשנה אותן, או ייבוא שמוסיף תגית ריפו."""
    wa.get_db().code_snippets.update_one({"_id": doc_id}, {"$set": {"tags": list(tags)}})


def _repo_counts(html):
    """רשימת הריפואים (``category=repo`` בלי ריפו נבחר): שם הריפו ← מספר הקבצים שהיא משייכת אליו."""
    return {
        name.strip(): int(count)
        for name, count in re.findall(
            r'<i class="fab fa-github"></i>\s*([^<]+?)\s*</span>\s*<span class="badge">(\d+)</span>', html
        )
    }


def test_a_file_that_moved_to_another_repo_is_listed_only_under_its_current_repo(wa):
    """הגרסה הישנה מתויגת בריפו אחד, והאחרונה באחר.

    רשימת הריפואים משייכת קובץ לריפו לפי **הגרסה האחרונה** שלו. תצוגת ריפו ספציפי סיננה גרסאות לפני הקיבוץ, ולכן הציגה את הקובץ גם בריפו הישן — בגרסה הישנה — ומה שהרשימה ספרה לא התאים למה שהתצוגה הציגה.
    """
    ids = _seed(wa, "moved.py", versions=2, tags=("repo:amirbiron/old",))
    _retag(wa, ids[-1], ("repo:amirbiron/new",))

    repo_list = _get(wa, "/files?category=repo").get_data(as_text=True)
    old_view = _get(wa, "/files?category=repo&repo=amirbiron/old").get_data(as_text=True)
    new_view = _get(wa, "/files?category=repo&repo=amirbiron/new").get_data(as_text=True)

    assert _repo_counts(repo_list) == {"amirbiron/new": 1}
    assert _shown_ids(old_view) == [], "הקובץ מוצג בריפו שהוא כבר לא שייך אליו"
    assert _shown_ids(new_view) == [str(ids[-1])]
    assert _total(new_view) == 1


def test_a_file_later_imported_into_a_repo_is_not_in_other_files(wa):
    """שמרת קובץ ידנית, ואחר כך ייבאת ריפו שיש בו קובץ באותו שם — הגרסה האחרונה מתויגת בריפו.

    "שאר קבצים" סינן גרסאות לפני הקיבוץ ("בלי תגית ריפו"), ולכן המשיך להציג את הקובץ — בגרסה הידנית הישנה — גם אחרי שהוא עבר לריפו.
    """
    ids = _seed(wa, "README.md", versions=2)
    _retag(wa, ids[-1], (REPO_TAG,))
    stays = _seed(wa, "notes.md", versions=1)

    html = _get(wa, "/files?category=other").get_data(as_text=True)

    assert _shown_ids(html) == [str(stays[0])], "קובץ שעבר לריפו מוצג ב'שאר קבצים' בגרסה ישנה"
    assert _total(html) == 1


def test_a_file_whose_repo_tag_was_removed_is_in_other_files_and_not_in_the_repo(wa):
    """הכיוון ההפוך: הגרסה הישנה בריפו, ובאחרונה התגית הוסרה."""
    ids = _seed(wa, "loose.py", versions=2, tags=(REPO_TAG,))
    _retag(wa, ids[-1], ())

    other = _get(wa, "/files?category=other").get_data(as_text=True)
    repo_view = _get(wa, "/files?category=repo&repo=amirbiron/demo").get_data(as_text=True)

    assert _shown_ids(other) == [str(ids[-1])]
    assert _shown_ids(repo_view) == [], "הקובץ מוצג בריפו אחרי שהתגית הוסרה ממנו"


def test_search_still_reaches_the_latest_version(wa):
    """``$text`` חייב לשבת ב-``$match`` הראשון של הצינור, והבנאי מוסיף ``$match`` משלו אחריו.

    מונגו מאחד את שניהם לשאילתה אחת (תיעוד ה-Aggregation Pipeline Optimization, "$match + $match Coalescence"). הבדיקה עוברת דרך אינדקס טקסט אמיתי, כי בלעדיו הראוט נופל לחיפוש ``$regex`` ולא בודק את הצירוף הזה בכלל.
    """
    db = wa.get_db()
    db.code_snippets.create_index(
        [("file_name", "text"), ("description", "text"), ("tags", "text")], name="text_file_desc_tags"
    )
    ids = _seed(wa, "zebra-notes.md")
    _seed(wa, "other.md")

    for url in ("/files?q=zebra", "/files?category=other&q=zebra"):
        response = _get(wa, url)
        assert response.status_code == 200, url
        assert _shown_ids(response.get_data(as_text=True)) == [str(ids[-1])], url


# ------------------------------------------------ תקציב המיון של Atlas Flex


@pytest.mark.parametrize(
    "url, tags",
    [
        ("/files?category=other", ()),
        ("/files?category=favorites", ()),
        ("/files?category=repo&repo=amirbiron/demo", (REPO_TAG,)),
        ("/files?category=recent", ()),
        ("/files", ()),
        ("/files?sort=file_name", ()),
    ],
)
def test_the_list_fits_the_flex_sort_budget(flex_budget, url, tags):
    """אותו קלט שהפיל את "שאר קבצים" בפרודקשן: גוף הקבצים גדול מתקרת המיון, המטא-דאטה קטן ממנה.

    על הקוד הקודם: ``other``, ``favorites``, תצוגת הריפו ו-``sort=file_name`` מחזירים 500 עם 292, ו-``recent`` בולע את השגיאה ומציג רשימה ריקה. ``/files`` עבר גם שם — דרך מסלול עוקף איטי שהוסר, ובלעדיו כשל כזה הוא 500. ראו ``test_a_failed_listing_is_an_error_and_not_a_quietly_different_list``.

    ``BUDGET_FILES`` קבצים בשתי גרסאות כל אחד: המיון **שאחרי** הקיבוץ מחזיק שורה לכל קובץ, ולכן גם שלב שמשאיר בה את גוף הקובץ — ``$addFields`` בין ה-``$match`` להיטלה — חורג כאן מהתקרה, ולא נתפס רק בבודק המבני שב-``tests/test_files_pipelines_drop_heavy_fields_early.py``.

    התגיות נקבעות לפי הכתובת, כי ``other`` מסנן בדיוק את מה שתצוגת הריפו דורשת — תגית ``repo:``.
    """
    wa = flex_budget
    names = [f"big-{i}.md" for i in range(BUDGET_FILES)]
    latest = []
    for name in names:
        ids = _seed(wa, name, versions=2, favorite=(1, 2), tags=tags, body_bytes=BIG_BODY_BYTES)
        latest.append(str(ids[-1]))
        wa.get_db().recent_opens.insert_one({"user_id": USER_ID, "file_name": name, "last_opened_at": CREATED})

    response = _get(wa, url)
    assert response.status_code == 200, f"{url} החזיר {response.status_code}"
    assert sorted(_shown_ids(response.get_data(as_text=True))) == sorted(latest), url


def test_the_mcp_file_list_fits_the_flex_sort_budget_on_its_last_page(flex_budget):
    """``codekeeper_list_files`` עובר ב-``Repository.get_regular_files_paginated``, ולא בבנאי של הוובאפ.

    שם מונגו קורא ישירות מהאינדקס רק את הגרסה האחרונה של כל קובץ, ולכן הקיבוץ עצמו זול. אבל ההיטלה ישבה **אחרי** המיון לפי ``updated_at``, והמיון החזיק מסמכים מלאים. ``$skip`` + ``$limit`` מאוחדים לתוך המיון, והוא שומר בזיכרון ``skip + per_page`` מסמכים (תיעוד ה-Aggregation Pipeline Optimization, "$sort + $limit Coalescence") — ולכן העמוד הראשון עבר והעמוד האחרון נפל, והסוכן קיבל "אין קבצים". המדידות מהפרודקשן — בהערה שמעל המיון ב-``get_regular_files_paginated``.
    """
    from database.manager import DatabaseManager
    from database.repository import Repository

    class _Manager:
        def __init__(self, collection):
            self.collection = collection

    wa = flex_budget
    collection = wa.get_db().code_snippets
    # **האינדקסים של הפרודקשן, כדי שתוכנית השאילתה תהיה שלו.** הם נוצרים ב-
    # ``DatabaseManager._create_indexes`` ולא בוובאפ, ולכן מסד הבדיקה נולד
    # בלעדיהם. בלי ``idx_snippets_latest_version`` מונגו ממיין את כל המסמכים
    # המלאים **לפני** הקיבוץ — מסלול שלא קיים בפרודקשן — והבדיקה הייתה נכשלת
    # על תצורה אחרת מזו שנבדקת (TESTING-PATTERNS T1, וריאציה e). הקריאה היא
    # לקוד הייצור ולא להעתק של הגדרת האינדקס, כמו ב-
    # ``tests/test_version_numbering_across_trash.py``. ה-explain שמתחת מוודא
    # שהתוכנית באמת זו שהאינדקס הזה נותן.
    mgr = DatabaseManager.__new__(DatabaseManager)
    mgr.db = collection.database
    mgr.client = None
    DatabaseManager._create_indexes(mgr)
    for i in range(9):
        _seed(wa, f"mcp-{i}.md", versions=1, body_bytes=BIG_BODY_BYTES)

    plan = collection.database.command({
        "explain": {"aggregate": "code_snippets", "cursor": {}, "pipeline": [
            {"$match": {"user_id": USER_ID, "is_active": True}},
            {"$sort": {"file_name": 1, "version": -1}},
            {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
        ]},
        "verbosity": "queryPlanner",
    })
    assert "DISTINCT_SCAN" in repr(plan), "מסד הבדיקה אינו מריץ את תוכנית הפרודקשן"

    files, total = Repository(_Manager(collection)).get_regular_files_paginated(USER_ID, page=2, per_page=5)

    assert total == 9
    assert len(files) == 4, f"העמוד האחרון חזר ריק או חלקי: {len(files)}"
    assert all("code" not in f for f in files)


def test_a_failed_listing_is_an_error_and_not_a_quietly_different_list(wa, monkeypatch):
    """כשהשאילתה של הרשימה נכשלת, העמוד אומר את זה — ולא מגיש רשימה אחרת בשקט.

    עד התיקון "כל הקבצים" עבר במצב כזה למסלול ``find`` עוקף. למה הוא הוסר — ב-docstring של ``_aggregate_code_snippets`` ב-``webapp/app.py``. הגרסה של הבדיקה הזו שרצה בלי מונגו נמצאת ב-``tests/test_webapp_files_aggregate_allow_disk_use.py``.
    """
    import pymongo.collection
    from pymongo.errors import OperationFailure

    _seed(wa, "draft.md")

    def _fails(self, pipeline, *args, **kwargs):
        raise OperationFailure("Sort exceeded memory limit", code=292)

    monkeypatch.setattr(pymongo.collection.Collection, "aggregate", _fails)

    response = _get(wa, "/files")
    assert response.status_code == 500

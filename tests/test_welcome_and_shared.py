import types

import pytest


class FakeUsersCollection:
    def __init__(self):
        self.docs = {}

    def update_one(self, query, update, upsert=False):
        def _set_dotted(doc, dotted_key, value):
            if '.' not in dotted_key:
                doc[dotted_key] = value
                return
            cur = doc
            parts = [p for p in str(dotted_key).split('.') if p]
            if not parts:
                return
            for p in parts[:-1]:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            cur[parts[-1]] = value

        user_id = query.get('user_id')
        doc = self.docs.setdefault(user_id, {'user_id': user_id})
        for key, value in (update.get('$setOnInsert') or {}).items():
            if '.' in str(key):
                # emulate MongoDB dotted keys on insert
                if key not in doc:
                    _set_dotted(doc, key, value)
            else:
                doc.setdefault(key, value)
        for key, value in (update.get('$set') or {}).items():
            _set_dotted(doc, key, value)
        return types.SimpleNamespace(acknowledged=True)

    def find_one(self, query, projection=None, *args, **kwargs):
        """חתימה כמו של ``Collection.find_one`` ב-pymongo, כדי שקורא שמעביר היטלה לא ייפול כאן."""
        return self.docs.get(query.get('user_id'))


class FakeCodeSnippetsCollection:
    def __init__(self):
        self.docs = []

    def find_one(self, query, projection=None, *args, sort=None, **kwargs):
        """חתימה כמו של ``Collection.find_one`` ב-pymongo: ההיטלה היא הארגומנט הפוזיציוני השני, ו-``sort`` מגיע בשם.

        בצורה הקודמת (``query, sort=None``) ההיטלה של שאילתת המועדף (``file_favorite.py``) נחתה ב-``sort``, והשמירה החזירה 500. ``$in`` על ``file_name`` נתמך מאותה סיבה — השאילתה שואלת את כל השמות של הקובץ.
        """
        user_id = query.get('user_id')
        file_name = query.get('file_name')
        names = list(file_name['$in']) if isinstance(file_name, dict) and '$in' in file_name else [file_name]
        for doc in reversed(self.docs):
            if doc.get('user_id') == user_id and doc.get('file_name') in names:
                return doc
        return None

    def insert_one(self, doc):
        stored = dict(doc)
        if '_id' not in stored:
            stored['_id'] = f"fake-{len(self.docs)+1}"
        self.docs.append(stored)
        return types.SimpleNamespace(inserted_id=stored['_id'])


def _stub_cache():
    class _Cache:
        def invalidate_user_cache(self, *args, **kwargs):
            return None

        def invalidate_file_related(self, *args, **kwargs):
            return None

    return _Cache()


def test_a_new_users_page_carries_no_onboarding_layer(monkeypatch):
    """משתמש חדש מקבל עמוד בלי מודאל פתיחה, בלי אשף ערכות ובלי Driver.js.

    המשתמש כאן הוא בדיוק מה ש-``save_user`` יצר עד הסרת ה-Onboarding: מסמך עם
    ``has_seen_welcome_modal: False``. על הקוד הקודם כל עמוד שיורש מ-``base.html``
    נשא את שלוש השכבות, והמודאל חסם קליקים עד שנסגר.

    הטסט רץ בשרת ולא בדפדפן בכוונה: ב-CI לא מותקן דפדפן (ראו
    ``chromium_executable`` ב-``tests/conftest.py``), ולכן טסטי הדפדפן מדולגים שם
    ולא היו תופסים חזרה של אחת השכבות.
    """
    import webapp.app as app_mod

    fake_users = FakeUsersCollection()
    fake_users.docs[42] = {'user_id': 42, 'has_seen_welcome_modal': False}
    fake_db = types.SimpleNamespace(users=fake_users)

    monkeypatch.setattr(app_mod, 'get_db', lambda: fake_db)

    app_mod.app.testing = True
    with app_mod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 42
            sess['user_data'] = {'id': 42}
        resp = client.get('/privacy')

    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # בקרה: העמוד נבנה למשתמש מחובר, כלומר המסלול שבו המודאל הופיע.
    assert 'href="/files"' in html
    markers = ('id="welcomeModal"', '/api/welcome/ack', 'id="themeWizard"', 'driver.js', 'codekeeper_walkthrough_v1')
    for marker in markers:
        assert marker not in html, f"שכבת Onboarding חזרה לעמוד: {marker}"


def test_save_shared_file_creates_snippet(monkeypatch):
    import webapp.app as app_mod

    fake_users = FakeUsersCollection()
    fake_snippets = FakeCodeSnippetsCollection()
    fake_db = types.SimpleNamespace(users=fake_users, code_snippets=fake_snippets)

    monkeypatch.setattr(app_mod, 'get_db', lambda: fake_db)
    monkeypatch.setattr(app_mod, 'cache', _stub_cache())
    monkeypatch.setattr(
        app_mod,
        'get_internal_share',
        lambda share_id: {
            'share_id': share_id,
            'code': '# מדריך\\nהתחלה מהירה',
            'language': 'markdown',
            'file_name': 'welcome-guide.md',
            'description': 'מדריך תפעול WebApp',
        },
    )

    app_mod.app.testing = True
    with app_mod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 7
            sess['user_data'] = {'id': 7}
        resp = client.post('/api/shared/save', json={'share_id': 'welcome'})
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload and payload['ok'] is True
        assert fake_snippets.docs, 'snippet should be inserted'
        saved = fake_snippets.docs[0]
        assert saved['user_id'] == 7
        assert saved['programming_language'] == 'markdown'
        assert saved['file_name'].lower().endswith('.md')


def test_builtin_welcome_share_uses_user_guide(monkeypatch, tmp_path):
    import webapp.app as app_mod

    guide_file = tmp_path / "USER_GUIDE.md"
    guide_file.write_text("# Guide 2.0\nתיאור חדש", encoding='utf-8')

    monkeypatch.setattr(app_mod, 'USER_GUIDE_PATH', guide_file)

    app_mod._load_user_guide_markdown.cache_clear()

    def _fail_get_db():
        raise AssertionError("get_db should not be called for builtin share")

    monkeypatch.setattr(app_mod, 'get_db', _fail_get_db)

    try:
        primary_doc = app_mod.get_internal_share(app_mod.WELCOME_GUIDE_PRIMARY_SHARE_ID)
        assert primary_doc
        assert '# Guide 2.0' in primary_doc['code']
        assert primary_doc['language'] == 'markdown'
        assert primary_doc['file_name'].endswith('.md')
        assert primary_doc['share_id'] == app_mod.WELCOME_GUIDE_PRIMARY_SHARE_ID

        alias_doc = app_mod.get_internal_share("JjvpJFTXZO0oHtoC")
        assert alias_doc
        assert alias_doc['share_id'] == "JjvpJFTXZO0oHtoC"
        assert alias_doc['code'] == primary_doc['code']
    finally:
        app_mod._load_user_guide_markdown.cache_clear()


@pytest.mark.parametrize(
    'onboarding',
    [
        {'walkthrough_v1_seen': True, 'theme_wizard_seen': True},
        'not-an-object',
    ],
    ids=['flags', 'malformed'],
)
def test_ui_prefs_ignores_the_removed_onboarding_key(monkeypatch, onboarding):
    """טאב שנטען לפני הסרת ה-Onboarding עדיין שולח ``onboarding`` ל-``/api/ui_prefs``.

    הוא מקבל 200 בלי שגיאה, ושום דבר לא נכתב — לפי הכלל שב-docstring של
    ``api_ui_prefs``: מפתח שאינו מטופל שם במפורש אינו נשמר. על הקוד הקודם
    הדגלים נכתבו ל-``ui_prefs.onboarding``, וערך שאינו אובייקט קיבל 400.
    """
    import webapp.app as app_mod

    fake_users = FakeUsersCollection()
    fake_db = types.SimpleNamespace(users=fake_users)

    monkeypatch.setattr(app_mod, 'get_db', lambda: fake_db)

    app_mod.app.testing = True
    with app_mod.app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 55
            sess['user_data'] = {}

        resp = client.post('/api/ui_prefs', json={'onboarding': onboarding})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data and data['ok'] is True
    assert 'onboarding' not in data
    assert 55 not in fake_users.docs, f"נכתב מסמך משתמש: {fake_users.docs.get(55)!r}"

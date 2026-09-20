import unittest
from unittest.mock import MagicMock
from datetime import datetime, timedelta, timezone

from flask import Flask, session, json

# Import blueprint and helpers to patch
import importlib
sticky_mod = importlib.import_module('webapp.sticky_notes_api')


def _matches(doc, query):
    """התאמת מסמך לשאילתה — האופרטורים שמסלול התזכורות באמת משתמש בהם.

    ``$lte``/``$gt`` על ``remind_at``, ``$in`` על ``status``, והשוואה ל-
    ``None``. האחרונה אינה שוויון פייתוני רגיל: במונגו ``{f: None}`` תופס
    גם מסמך **שאין בו השדה**, ו-``{f: {"$ne": None}}`` דורש שהשדה קיים
    ואינו ריק. דמה שמתעלמת מזה עוברת על קוד שבור.
    מקור: MongoDB Manual, "Query for Null or Missing Fields".
    """
    for k, v in query.items():
        actual = doc.get(k)
        if isinstance(v, dict):
            if '$in' in v and actual not in v['$in']:
                return False
            if '$lte' in v and not (isinstance(actual, datetime) and actual <= v['$lte']):
                return False
            if '$gt' in v and not (isinstance(actual, datetime) and actual > v['$gt']):
                return False
            if '$gte' in v and not (isinstance(actual, datetime) and actual >= v['$gte']):
                return False
            if '$ne' in v:
                if v['$ne'] is None:
                    if k not in doc or actual is None:
                        return False
                elif actual == v['$ne']:
                    return False
        elif v is None:
            # null או שדה חסר — שניהם מתאימים
            if actual is not None:
                return False
        elif actual != v:
            return False
    return True


class _StubColl:
    def __init__(self):
        self._docs = []
        self.calls = []

    # index methods
    def create_index(self, *args, **kwargs):
        return None

    def create_indexes(self, *args, **kwargs):
        return None

    # basic CRUD mocks
    def find_one(self, query, projection=None, *args, sort=None, **kwargs):
        docs = [d for d in self._docs if _matches(d, query)]
        if sort:
            for key, direction in reversed(list(sort)):
                docs.sort(key=lambda d: d.get(key), reverse=(direction < 0))
        return docs[0] if docs else None

    def count_documents(self, query, *args, **kwargs):
        return len([d for d in self._docs if _matches(d, query)])

    def insert_one(self, doc):
        self._docs.append(dict(doc))
        class R: inserted_id = '1'
        return R()

    def update_one(self, filt, update, upsert=False):
        # **מעדכן באמת.** הגרסה הקודמת רק רשמה את הקריאה והחזירה
        # ``matched_count=1``, ולכן כל טסט על *תוצאת* העדכון היה עובר גם
        # על קוד שלא כתב כלום.
        self.calls.append(('update_one', filt, update, upsert))
        matched = [d for d in self._docs if _matches(d, filt)]
        if matched:
            matched[0].update(dict(update.get('$set') or {}))
        elif upsert:
            fresh = {k: v for k, v in filt.items() if not isinstance(v, dict)}
            fresh.update(dict(update.get('$set') or {}))
            fresh.update(dict(update.get('$setOnInsert') or {}))
            self._docs.append(fresh)
        class R:
            matched_count = 1 if matched else 0
            modified_count = 1 if matched else 0
        return R()

    def update_many(self, filt, update):
        self.calls.append(('update_many', filt, update))
        matched = [d for d in self._docs if _matches(d, filt)]
        for d in matched:
            d.update(dict(update.get('$set') or {}))
        class R:
            matched_count = len(matched)
            modified_count = len(matched)
        return R()

    def delete_one(self, filt):
        self.calls.append(('delete_one', filt))
        class R:
            deleted_count = 1
        return R()

    def find(self, query, projection=None, *args, **kwargs):
        filtered = [d for d in self._docs if _matches(d, query)]

        class _Cursor:
            def __init__(self, items):
                self._items = list(items)
            def sort(self, key=None, direction=1, **kw):
                if key:
                    self._items.sort(key=lambda d: d.get(key), reverse=(direction < 0))
                return self
            def limit(self, n):
                self._items = self._items[:n]
                return self
            def __iter__(self):
                return iter(self._items)
            def __len__(self):
                return len(self._items)

        return _Cursor(filtered)

    def sort(self, *args, **kwargs):
        return self


class _StubDB:
    def __init__(self):
        self.sticky_notes = _StubColl()
        self.note_reminders = _StubColl()


def _make_app(db_stub):
    app = Flask(__name__)
    app.secret_key = 'test-secret'
    app.register_blueprint(sticky_mod.sticky_notes_bp)
    return app


class TestNoteRemindersAPI(unittest.TestCase):
    def setUp(self):
        self.db = _StubDB()
        # Seed a note for the user
        self.user_id = 123
        self.note_id = '507f1f77bcf86cd799439011'
        self.db.sticky_notes._docs.append({'_id': self.note_id, 'user_id': self.user_id, 'file_id': 'file-1'})
        # Patch module global but restore in tearDown to avoid leaking across suite
        self._orig_get_db = sticky_mod.get_db
        sticky_mod.get_db = lambda: self.db
        self.app = _make_app(self.db)
        self.client = self.app.test_client()

    def tearDown(self):
        try:
            sticky_mod.get_db = self._orig_get_db
        except Exception:
            pass

    def _login(self):
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user_id
            sess['user_data'] = {'first_name': 'Test'}

    def test_set_reminder_preset_1h(self):
        self._login()
        r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/reminder', json={'preset': '1h', 'tz': 'UTC'})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data['ok'])
        # ensure DB update called
        calls = [c for c in self.db.note_reminders.calls if c[0] == 'update_one']
        self.assertTrue(calls)

    def test_get_reminder_empty(self):
        self._login()
        r = self.client.get(f'/api/sticky-notes/note/{self.note_id}/reminder')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json().get('reminder'), None)

    def test_snooze_updates_time(self):
        self._login()
        # create existing reminder
        self.db.note_reminders._docs.append({
            '_id': 'r1', 'user_id': self.user_id, 'note_id': self.note_id,
            'status': 'pending', 'remind_at': datetime.now(timezone.utc)+timedelta(minutes=1)
        })
        r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/snooze', json={'minutes': 10})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])

    def test_summary_has_due(self):
        self._login()
        now = datetime.now(timezone.utc)
        self.db.note_reminders._docs.append({
            '_id': 'r1', 'user_id': self.user_id, 'note_id': self.note_id, 'file_id': 'file-1',
            'status': 'pending', 'remind_at': now - timedelta(minutes=1), 'ack_at': None
        })
        r = self.client.get('/api/sticky-notes/reminders/summary')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['has_due'])
        self.assertIsNotNone(data['next'])

    def test_delete_reminder(self):
        self._login()
        r = self.client.delete(f'/api/sticky-notes/note/{self.note_id}/reminder')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])

    # --- מחזור החיים: ack סוגר את שני השדות ---

    def _seed_due(self, **overrides):
        doc = {
            '_id': 'r1', 'user_id': self.user_id, 'note_id': self.note_id,
            'file_id': 'file-1', 'status': 'pending',
            'remind_at': datetime.now(timezone.utc) - timedelta(minutes=1),
            'ack_at': None,
        }
        doc.update(overrides)
        self.db.note_reminders._docs.append(doc)
        return doc

    def test_ack_closes_status_not_just_ack_at(self):
        """ack חייב להוציא את התזכורת ממצב פעיל, לא רק לחתום עליה.

        זה הטסט שנופל על הקוד שלפני התיקון: שם נכתב ``ack_at`` בלבד,
        ו-``status`` נשאר ``pending`` — ולכן כרטיס הדשבורד המשיך לספור
        אותה כ"בהמתנה".
        """
        self._login()
        doc = self._seed_due()
        r = self.client.post('/api/sticky-notes/reminders/ack', json={'note_id': self.note_id})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])
        self.assertIsNotNone(doc['ack_at'], 'ack_at לא נכתב')
        self.assertEqual(doc['status'], 'acked', 'status נשאר במצב פעיל אחרי ack')

    def test_summary_ignores_acked_reminder(self):
        """תזכורת שאושרה אינה נספרת, גם אם status שלה עדיין ישן.

        המסמך כאן מדמה את מה שיש היום במסד: ``ack_at`` מלא ו-``status``
        שנשאר ``pending``. הפילטר חייב לפסול אותו על סמך ``ack_at``.
        """
        self._login()
        self._seed_due(ack_at=datetime.now(timezone.utc))
        data = self.client.get('/api/sticky-notes/reminders/summary').get_json()
        self.assertFalse(data['has_due'])
        self.assertEqual(data['count_due'], 0)

    # --- next_in_seconds: מתי הלקוח צריך לחזור ---

    def test_summary_reports_seconds_until_next_reminder(self):
        self._login()
        self.db.note_reminders._docs.append({
            '_id': 'r-future', 'user_id': self.user_id, 'note_id': self.note_id,
            'status': 'pending', 'ack_at': None,
            'remind_at': datetime.now(timezone.utc) + timedelta(minutes=45),
        })
        data = self.client.get('/api/sticky-notes/reminders/summary').get_json()
        self.assertFalse(data['has_due'])
        self.assertIsNotNone(data['next_in_seconds'])
        # כ-45 דקות, עם מרווח לזמן הריצה
        self.assertGreater(data['next_in_seconds'], 45 * 60 - 60)
        self.assertLessEqual(data['next_in_seconds'], 45 * 60)

    def test_summary_reports_none_when_nothing_scheduled(self):
        """אין תזכורות כלל — הלקוח מקבל None ומפסיק לדגום.

        זה המצב שבו המערכת נמצאה בפועל: אוסף שכולו תזכורות סגורות,
        ו-954 קריאות ביממה שכולן החזירו "אין".
        """
        self._login()
        data = self.client.get('/api/sticky-notes/reminders/summary').get_json()
        self.assertFalse(data['has_due'])
        self.assertIsNone(data['next_in_seconds'])

    def test_summary_fails_loudly_when_the_count_query_fails(self):
        """שאילתה שנכשלה אינה "אין תזכורות".

        כאן ישב ``except`` שהחזיר ``count_due = 0``, והתשובה יצאה
        ``ok: true, has_due: false`` — כלומר "הכול נקי" על מסד שלא ענה.
        הלקוח היה מוחק את הבועה **ונרדם לחצי שעה** על סמך הכשל הזה.
        """
        self._login()
        self._seed_due()

        def _boom(*args, **kwargs):
            raise RuntimeError('mongo is down')

        self.db.note_reminders.count_documents = _boom
        r = self.client.get('/api/sticky-notes/reminders/summary')
        self.assertEqual(r.status_code, 500, 'כשל במסד הוחזר כתשובה תקינה')
        self.assertFalse(r.get_json()['ok'])

    def test_get_reminder_ignores_an_acknowledged_one(self):
        """מסמך ישן — ``ack_at`` מלא ו-``status`` שנשאר פעיל — אינו תזכורת חיה."""
        self._login()
        self._seed_due(ack_at=datetime.now(timezone.utc))
        r = self.client.get(f'/api/sticky-notes/note/{self.note_id}/reminder')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.get_json()['reminder'])

    def test_snooze_does_not_revive_an_acknowledged_reminder(self):
        """דחייה מחיה תזכורת פעילה, לא כזו שהמשתמש כבר סגר."""
        self._login()
        doc = self._seed_due(ack_at=datetime.now(timezone.utc))
        r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/snooze', json={'minutes': 10})
        self.assertEqual(r.status_code, 404)
        self.assertIsNotNone(doc['ack_at'], 'התזכורת הוחייתה בשקט')

    def test_summary_rejects_non_dict_json_body(self):
        """גוף JSON שאינו אובייקט מקבל 400, לא 500."""
        self._login()
        r = self.client.post(
            '/api/sticky-notes/reminders/ack',
            data=json.dumps([1, 2, 3]),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 400)

    def test_list_fails_loudly_when_the_db_handle_is_dead(self):
        """כשל בקבלת המסד אינו "אין תזכורות" — גם במסלול הרשימה.

        ``get_db()`` מחזיר ``None`` בחלון הצינון שאחרי כשל התחברות, וזה
        מה שהטסט מדמה. עד התיקון המסלול בלע את ה-``AttributeError`` הנובע
        מזה לתוך ``cursor = []`` וענה ``200 {"ok": true, "count": 0}``:
        הבועה אמרה "3", החלונית נפתחה ריקה ודיווחה הצלחה. ``reminders_summary``
        כבר עונה 500 על אותו מצב, ומסלולי הבועה חייבים חוזה אחד.

        ``_INDEX_READY`` מקובע ל-``True`` כדי ש-``_ensure_indexes`` — שרץ
        ראשון ובולע כשל של ``get_db`` בעצמו — לא ייגע במסד, וה-500 יגיע
        רק מהשאילתה של הרשימה ולא ממנו.
        """
        self._login()
        orig_ready = sticky_mod._INDEX_READY
        sticky_mod._INDEX_READY = True
        sticky_mod.get_db = lambda: None
        try:
            r = self.client.get('/api/sticky-notes/reminders/list')
        finally:
            sticky_mod._INDEX_READY = orig_ready
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.get_json().get('ok'))

    def test_list_returns_a_due_reminder_with_its_preview(self):
        """המסלול התקין: תזכורת בשלה חוזרת עם תצוגה מקדימה מהפתק.

        לרשימה לא היה טסט, ולכן הסרת הבליעה צריכה עד שהמסלול שנשאר
        עדיין עונה — אחרת "נופל בקול" ו"נופל תמיד" נראים אותו דבר.
        """
        self._login()
        self.db.sticky_notes._docs[0]['content'] = 'שלום עולם דביק'
        now = datetime.now(timezone.utc)
        self.db.note_reminders._docs.append({
            '_id': 'r1', 'user_id': self.user_id, 'note_id': self.note_id, 'file_id': 'file-1',
            'status': 'pending', 'remind_at': now - timedelta(minutes=1), 'ack_at': None,
        })
        r = self.client.get('/api/sticky-notes/reminders/list')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['items'][0]['note_id'], self.note_id)
        self.assertEqual(data['items'][0]['preview'], 'שלום עולם דביק')


class TestReminderStateHelpers(unittest.TestCase):
    """המודול הטהור — בלי Flask ובלי מסד."""

    def test_active_filter_returns_a_fresh_dict(self):
        from note_reminder_state import active_reminder_filter
        a = active_reminder_filter()
        a['user_id'] = 1
        self.assertNotIn('user_id', active_reminder_filter())

    def test_acknowledge_fields_sets_both_state_fields(self):
        from note_reminder_state import acknowledge_fields, REMINDER_STATUS_ACKED
        now = datetime.now(timezone.utc)
        fields = acknowledge_fields(now)
        self.assertEqual(fields['status'], REMINDER_STATUS_ACKED)
        self.assertEqual(fields['ack_at'], now)

    def test_seconds_until_tags_naive_values_as_utc(self):
        """ערך נאיבי מהמסד לא מפיל את החישוב.

        חיסור בין נאיבי למודע-אזור זורק TypeError בפייתון, והמסלול הזה
        נקרא בכל טעינת עמוד.
        """
        from note_reminder_state import seconds_until
        now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
        naive = datetime(2026, 9, 20, 12, 10, 0)  # בלי tzinfo
        self.assertEqual(seconds_until(naive, now), 600)

    def test_seconds_until_clamps_past_values_to_zero(self):
        from note_reminder_state import seconds_until
        now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
        past = datetime(2026, 9, 20, 11, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(seconds_until(past, now), 0)

    def test_seconds_until_returns_none_for_missing_value(self):
        from note_reminder_state import seconds_until
        now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
        self.assertIsNone(seconds_until(None, now))


if __name__ == '__main__':
    unittest.main()

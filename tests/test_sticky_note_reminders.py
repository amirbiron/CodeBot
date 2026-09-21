import ast
import unittest
from pathlib import Path
from unittest import mock
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


def _project(doc, projection):
    """מחיל היטלה כמו מונגו, במקום לזרוק אותה.

    הכללה (``{f: 1}``) שומרת את השדות שנקבו ואת ``_id`` אלא אם ``_id: 0``;
    החרגה (``{f: 0}``) מסירה את השדות שנקבו. בלי היטלה חוזר המסמך עצמו.
    הסטאב הישן קיבל ``projection`` וזרק אותו, ולכן טסט ראה מסמך מלא היכן
    שהייצור רואה שדה אחד — שינוי שמפיל שדה מההיטלה עבר את הסוויטה.
    מקור: MongoDB Manual, "Project Fields to Return from Query".
    """
    if not projection:
        return doc
    if isinstance(projection, (list, tuple)):
        projection = {k: 1 for k in projection}
    fields = {k: v for k, v in projection.items() if k != '_id'}
    # מצב ההכללה נקבע לפי השדות שאינם ``_id``; כשיש רק ``_id`` — לפי הערך שלו.
    # ``{_id: 1}`` לבדו מחזיר רק ``_id``, ו-``{_id: 1, f: 0}`` הוא החרגה, כי ``_id``
    # הוא היוצא מן הכלל היחיד לאיסור על ערבוב. נמדד מול MongoDB 8.0.32.
    inclusion = any(fields.values()) if fields else bool(projection.get('_id'))
    if inclusion:
        keep = {k for k, v in fields.items() if v} | ({'_id'} if projection.get('_id', 1) else set())
        return {k: v for k, v in doc.items() if k in keep}
    exclude = {k for k, v in projection.items() if not v}
    return {k: v for k, v in doc.items() if k not in exclude}


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
        return _project(docs[0], projection) if docs else None

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
            def __init__(self, items, projection=None):
                self._items = list(items)
                self._projection = projection
            def sort(self, key=None, direction=1, **kw):
                if key:
                    self._items.sort(key=lambda d: d.get(key), reverse=(direction < 0))
                return self
            def limit(self, n):
                self._items = self._items[:n]
                return self
            def __iter__(self):
                # המיון וה-limit רצים על המסמכים המלאים, כמו במונגו; ההיטלה חלה על מה שיוצא.
                return iter([_project(d, self._projection) for d in self._items])
            def __len__(self):
                return len(self._items)

        return _Cursor(filtered, projection)

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

    def test_summary_requires_a_session(self):
        """בלי סשן — 401 נקי, לא הפניה ולא 403.

        הלקוח (base.html) עוצר את הדגימה על הסטטוס הזה בדיוק; סטטוס אחר
        היה נכנס ל-backoff המסלים במקום לעצור. הטסט מצמיד את החוזה.
        """
        r = self.client.get('/api/sticky-notes/reminders/summary')
        self.assertEqual(r.status_code, 401)
        self.assertFalse((r.get_json() or {}).get('ok'))

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
        self.assertEqual(data['count_due'], 1)

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

    # --- יש בועה: השרת עדיין אומר מתי לחזור ---

    def _seed_upcoming(self, minutes, _id='r-future'):
        self.db.note_reminders._docs.append({
            '_id': _id, 'user_id': self.user_id, 'note_id': self.note_id, 'file_id': 'file-1',
            'status': 'pending', 'ack_at': None,
            'remind_at': datetime.now(timezone.utc) + timedelta(minutes=minutes),
        })

    def test_summary_with_a_due_reminder_says_when_to_come_back(self):
        """יש בועה ואין עתידית: השרת עונה "חזור בעוד חמש דקות", לא שותק.

        לפני התיקון ``next_in_seconds`` חושב רק כשאין בשלות, והלקוח נרדם
        לתקרה — חצי שעה שבה בועה שנוקתה ממכשיר אחר נשארה על המסך.
        """
        self._login()
        self._seed_due()
        data = self.client.get('/api/sticky-notes/reminders/summary').get_json()
        self.assertTrue(data['has_due'])
        self.assertEqual(data['next_in_seconds'], 300)

    def test_summary_with_a_due_reminder_wakes_for_the_next_maturity(self):
        """יש בועה ותזכורת נוספת בעוד שתי דקות: חוזרים כשהיא מבשילה, לא בעוד חמש."""
        self._login()
        self._seed_due()
        self._seed_upcoming(2)
        data = self.client.get('/api/sticky-notes/reminders/summary').get_json()
        self.assertTrue(data['has_due'])
        self.assertIsNotNone(data['next_in_seconds'])
        self.assertGreater(data['next_in_seconds'], 2 * 60 - 60)
        self.assertLessEqual(data['next_in_seconds'], 2 * 60)

    def test_summary_with_a_due_reminder_caps_a_far_maturity_at_the_refresh(self):
        """יש בועה והעתידית רחוקה (45 דקות): הריענון של חמש דקות גובר."""
        self._login()
        self._seed_due()
        self._seed_upcoming(45)
        data = self.client.get('/api/sticky-notes/reminders/summary').get_json()
        self.assertTrue(data['has_due'])
        self.assertEqual(data['next_in_seconds'], 300)

    def test_summary_no_longer_ships_the_unread_next_object(self):
        """``next`` ירד: אין לו צרכן, והשאילתה שבנתה אותו הייתה הסיבוב שיכול לא להסכים עם הספירה."""
        self._login()
        self._seed_due()
        data = self.client.get('/api/sticky-notes/reminders/summary').get_json()
        self.assertNotIn('next', data)
        self.assertEqual(data['count_due'], 1)

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

    def test_summary_failure_leaves_a_server_side_trace(self):
        """500 בלי לוג הוא כשל שקט: הלקוח הופך אותו ל-backoff, ו-``@traced`` רושם
        רק חריגה שיוצאת מהפונקציה — ה-``except`` הגורף תופס אותה קודם. לפני
        התיקון נתיב שנפל לא השאיר שום סימן בשרת.
        """
        self._login()
        self._seed_due()

        def _boom(*args, **kwargs):
            raise RuntimeError('mongo is down')

        self.db.note_reminders.count_documents = _boom
        with self.assertLogs('webapp.sticky_notes_api', level='ERROR') as cm:
            r = self.client.get('/api/sticky-notes/reminders/summary')
        self.assertEqual(r.status_code, 500)
        # חימום האינדקסים עלול לרשום שגיאה משלו קודם; מחפשים את הרשומה של המסלול.
        recs = [rec for rec in cm.records if 'reminders_summary' in rec.getMessage()]
        self.assertTrue(recs, [rec.getMessage() for rec in cm.records])
        rec = recs[0]
        self.assertIsNotNone(rec.exc_info, 'ה-traceback לא צורף ללוג')
        self.assertIn('mongo is down', str(rec.exc_info[1]))

    def test_list_failure_leaves_a_server_side_trace(self):
        """אותו חוזה במסלול הרשימה — הנתיב השני שמשרת את הבועה."""
        self._login()
        self._seed_due()

        def _boom(*args, **kwargs):
            raise RuntimeError('mongo is down')

        self.db.note_reminders.find = _boom
        with self.assertLogs('webapp.sticky_notes_api', level='ERROR') as cm:
            r = self.client.get('/api/sticky-notes/reminders/list')
        self.assertEqual(r.status_code, 500)
        recs = [rec for rec in cm.records if 'reminders_list' in rec.getMessage()]
        self.assertTrue(recs, [rec.getMessage() for rec in cm.records])
        rec = recs[0]
        self.assertIsNotNone(rec.exc_info)
        self.assertIn('mongo is down', str(rec.exc_info[1]))

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

    def _seed_pending(self):
        """תזכורת פעילה לעתיד הקרוב — מה שהדחייה אמורה להזיז."""
        return self._seed_due(remind_at=datetime.now(timezone.utc) + timedelta(minutes=1))

    def test_snooze_rejects_minutes_that_are_not_an_integer_without_a_server_error(self):
        """קלט פסול הוא 400 שקט, לא 500 עם traceback.

        ``int()`` על מחרוזת או רשימה זורק, ולפני התיקון ה-``except`` הגורף הפך
        את זה ל-500 ולשורת ERROR בלוג, כאילו השרת נפל. ועל ``True`` או ``3.9``
        ``int()`` ממיר בשקט (1, 3) ומקבע דחייה שאיש לא ביקש. לכן בדיקת טיפוס
        לפני ההמרה — מספר שלם בלבד — ולא ``except`` אחריה.
        """
        self._login()
        doc = self._seed_pending()
        before = doc['remind_at']
        for bad in ('abc', '10', True, 3.9, [10], '', 0):
            with self.subTest(minutes=bad):
                with self.assertNoLogs('webapp.sticky_notes_api', level='ERROR'):
                    r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/snooze', json={'minutes': bad})
                self.assertEqual(r.status_code, 400, r.get_data(as_text=True))
                self.assertEqual(r.get_json()['error'], 'Invalid minutes')
                self.assertEqual(doc['remind_at'], before, 'הדחייה נקבעה למרות הקלט הפסול')

    def test_snooze_without_minutes_keeps_the_documented_hour(self):
        """שומר: גוף בלי ``minutes`` עדיין דוחה בשעה, כמו שהתיעוד מבטיח.

        עובר גם על הקוד הישן, בכוונה — הוא מגן על ברירת המחדל מפני החמרת הטיפוס.
        """
        self._login()
        doc = self._seed_pending()
        r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/snooze', json={})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        delta = doc['remind_at'] - datetime.now(timezone.utc)
        self.assertGreater(delta, timedelta(minutes=59))
        self.assertLessEqual(delta, timedelta(minutes=60))

    def test_snooze_with_a_list_body_is_400_not_500(self):
        """גוף JSON שהוא רשימה עובר את ``or {}`` (הוא truthy), ואז ``.get`` זורק —
        וזה היה 500 עם traceback במקום 400."""
        self._login()
        self._seed_pending()
        with self.assertNoLogs('webapp.sticky_notes_api', level='ERROR'):
            r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/snooze', json=[10])
        self.assertEqual(r.status_code, 400, r.get_data(as_text=True))
        self.assertEqual(r.get_json()['error'], 'invalid_payload')

    def test_set_reminder_with_a_list_body_is_400_not_500(self):
        """אותו גוף-רשימה במסלול הקביעה. ``_INDEX_READY`` מקובע כמו בטסט הרשימה,
        כדי שחימום האינדקסים לא ירשום שגיאה משלו לתוך הבדיקה על הלוג."""
        self._login()
        orig_ready = sticky_mod._INDEX_READY
        sticky_mod._INDEX_READY = True
        try:
            with self.assertNoLogs('webapp.sticky_notes_api', level='ERROR'):
                r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/reminder', json=['1h'])
        finally:
            sticky_mod._INDEX_READY = orig_ready
        self.assertEqual(r.status_code, 400, r.get_data(as_text=True))
        self.assertEqual(r.get_json()['error'], 'invalid_payload')

    def test_ack_with_a_list_body_names_the_payload(self):
        """ack כבר ענה 400 על רשימה, אבל בשם השדה החסר; עכשיו שלושת מסלולי
        התזכורות שקוראים גוף עונים אותה תשובה, ``invalid_payload``."""
        self._login()
        r = self.client.post('/api/sticky-notes/reminders/ack', json=[1, 2, 3])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['error'], 'invalid_payload')

    def test_set_reminder_save_failure_leaves_a_server_side_trace(self):
        """ה-``except`` הפנימי סביב ``update_one`` החזיר ``Failed to save`` בלי לוג —
        אותו כשל שקט שתוקן בשאר המסלולים, רק בטקסט אחר, ולכן הספירה המילולית
        לא ראתה אותו. החוזה ללקוח נשאר; מה שנוסף הוא העקבה.
        """
        self._login()

        def _boom(*args, **kwargs):
            raise RuntimeError('mongo is down')

        self.db.note_reminders.update_one = _boom
        with self.assertLogs('webapp.sticky_notes_api', level='ERROR') as cm:
            r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/reminder', json={'preset': '1h', 'tz': 'UTC'})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.get_json()['error'], 'Failed to save')
        recs = [rec for rec in cm.records if 'set_note_reminder' in rec.getMessage()]
        self.assertTrue(recs, [rec.getMessage() for rec in cm.records])
        self.assertIsNotNone(recs[0].exc_info, 'ה-traceback לא צורף ללוג')
        self.assertIn('mongo is down', str(recs[0].exc_info[1]))

    # --- WARN-001: האישור סוגר את המועד שההתראה נשאה, לא "איזו שהיא" תזכורת של הפתק ---

    ACK = '/api/sticky-notes/reminders/ack'

    def test_ack_closes_only_the_occurrence_the_notification_carried(self):
        """התראה שישבה במגש מאתמול אינה סוגרת את התזכורת שנקבעה מחדש למחר.

        הפילטר התאים על ``(user_id, note_id, ack_at)`` בלי לומר *איזו* תזכורת, ו-
        ``set_note_reminder`` עושה upsert על אותו מסמך — כך שתמיד יש שורה אחת
        לפגוע בה. ההתראה נושאת את ``remind_at`` של המועד שבו נורתה; אישור עם
        מועד שאינו המועד השמור הוא 404, והתזכורת החדשה נשארת פעילה.
        """
        self._login()
        fired_at = datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc)
        doc = self._seed_due(remind_at=fired_at + timedelta(days=1))
        r = self.client.post(self.ACK, json={'note_id': self.note_id, 'remind_at': fired_at.isoformat()})
        self.assertEqual(r.status_code, 404, r.get_data(as_text=True))
        self.assertEqual(doc['status'], 'pending')
        self.assertIsNone(doc['ack_at'], 'התראה ישנה סגרה תזכורת חדשה')

    def test_ack_with_the_carried_occurrence_closes_it(self):
        self._login()
        fired_at = datetime(2026, 9, 20, 9, 0, 0, 123000, tzinfo=timezone.utc)
        doc = self._seed_due(remind_at=fired_at)
        r = self.client.post(self.ACK, json={'note_id': self.note_id, 'remind_at': fired_at.isoformat()})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(doc['status'], 'acked')
        self.assertIsNotNone(doc['ack_at'])

    def test_ack_tolerates_the_microseconds_the_database_dropped(self):
        """BSON שומר מילישניות; מחרוזת עם מיקרו-שניות חייבת עדיין להתאים למועד השמור.
        בקרה: הסרת החיתוך במפתח ← 404 על אישור נכון."""
        self._login()
        stored = datetime(2026, 9, 20, 9, 0, 0, 123000, tzinfo=timezone.utc)
        doc = self._seed_due(remind_at=stored)
        precise = stored.replace(microsecond=123456).isoformat()
        r = self.client.post(self.ACK, json={'note_id': self.note_id, 'remind_at': precise})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(doc['status'], 'acked')

    def test_ack_rejects_a_remind_at_it_cannot_read(self):
        self._login()
        doc = self._seed_due()
        # האחרון תקין תחבירית, אבל ההמרה ל-UTC יוצאת מטווח datetime — OverflowError
        # ולא ValueError, וזה היה 500 עם traceback על טעות של הלקוח.
        for bad in ('yesterday', 123, ['2026-09-20T09:00:00+00:00'], '0001-01-01T00:00:00+03:00'):
            with self.subTest(remind_at=bad):
                with self.assertNoLogs('webapp.sticky_notes_api', level='ERROR'):
                    r = self.client.post(self.ACK, json={'note_id': self.note_id, 'remind_at': bad})
                self.assertEqual(r.status_code, 400, r.get_data(as_text=True))
                self.assertEqual(r.get_json()['error'], 'invalid_remind_at')
        self.assertEqual(doc['status'], 'pending', 'קלט פסול סגר תזכורת')

    def test_ack_without_an_occurrence_still_closes_the_reminder(self):
        """שומר: לקוח ישן — SW שנשמר במטמון, או התראה שכבר הוצגה בלי המועד — שולח
        ``note_id`` בלבד, ועדיין סוגר. עובר גם על הקוד הישן בכוונה."""
        self._login()
        doc = self._seed_due()
        r = self.client.post(self.ACK, json={'note_id': self.note_id})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(doc['status'], 'acked')

    def test_list_items_carry_the_occurrence_for_the_ack(self):
        """החלונית מאשרת בלחיצה; כדי שהאישור ייקשר למועד, הרשימה חייבת לשאת אותו."""
        self._login()
        fired_at = datetime(2026, 9, 20, 9, 0, 0, 123000, tzinfo=timezone.utc)
        self._seed_due(remind_at=fired_at)
        r = self.client.get('/api/sticky-notes/reminders/list')
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        items = r.get_json()['items']
        self.assertEqual(len(items), 1, items)
        self.assertEqual(items[0]['remind_at'], fired_at.isoformat())

    # --- WARN-010 ו-SUGG-010: אתרי הכתיבה עוברים דרך המודול -----------------------

    def test_arming_writes_the_status_the_module_defines(self):
        """שינוי הקבוע שינה מה נקרא אבל לא מה נכתב, כי אתר הכתיבה החזיק מחרוזת משלו.
        הקבוע מוחלף לרגע, והכתיבה חייבת לעקוב אחריו."""
        self._login()
        with mock.patch('note_reminder_state.REMINDER_STATUS_PENDING', 'armed-by-test'):
            r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/reminder', json={'preset': '1h', 'tz': 'UTC'})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(self.db.note_reminders._docs[-1]['status'], 'armed-by-test')

    def test_snoozing_writes_the_status_the_module_defines(self):
        self._login()
        doc = self._seed_pending()
        with mock.patch('note_reminder_state.REMINDER_STATUS_SNOOZED', 'snoozed-by-test'):
            r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/snooze', json={'minutes': 10})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(doc['status'], 'snoozed-by-test')

    def test_snooze_does_not_rewrite_the_ack_it_already_required(self):
        """הפילטר דורש ``ack_at`` ריק, ולכן ``ack_at: None`` בכתיבה היה מת."""
        self._login()
        self._seed_pending()
        r = self.client.post(f'/api/sticky-notes/note/{self.note_id}/snooze', json={'minutes': 10})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        sets = [c[2]['$set'] for c in self.db.note_reminders.calls if c[0] == 'update_one']
        self.assertTrue(sets)
        self.assertNotIn('ack_at', sets[-1])

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


def _reminder_route_functions(tree):
    """הפונקציות שרשומות כמסלולי תזכורות — לפי הנתיב בדקורטור, לא לפי שם הפונקציה."""
    for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for dec in fn.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == 'route'):
                continue
            path = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else ''
            if isinstance(path, str) and ('reminder' in path or 'snooze' in path):
                yield fn
                break


def _returns_500(node):
    return any(
        isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple) and len(n.value.elts) == 2
        and isinstance(n.value.elts[1], ast.Constant) and n.value.elts[1].value == 500
        for n in ast.walk(node)
    )


def _leaves_a_trace(node):
    """``_failed`` או ``logger.error``/``exception``/``critical`` בגוף ה-``except``."""
    for n in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
        f = n.func
        if isinstance(f, ast.Name) and f.id == '_failed':
            return True
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == 'logger' \
                and f.attr in ('error', 'exception', 'critical'):
            return True
    return False


class TestReminderRoutesFailLoudly(unittest.TestCase):
    """כל 500 במסלולי התזכורות עובר דרך העוזר שרושם לוג — לא נשאר ``return`` חשוף.

    הטסטים למעלה מודדים מסלולים בודדים; אלה תופסים את השאר ואת הבא שייכתב.
    """

    def test_no_bare_500_is_left_in_the_module(self):
        source = Path(sticky_mod.__file__).read_text(encoding='utf-8')
        bare = "return jsonify({'ok': False, 'error': 'Failed'}), 500"
        self.assertIn('def _failed(', source, 'העוזר שרושם לוג לפני 500 חסר')
        self.assertEqual(source.count(bare), 0, 'אין 500 חשוף — הכול עובר דרך _failed')

    def test_every_500_in_a_reminder_route_leaves_a_trace(self):
        """סורק את ה-AST: כל ``except`` במסלול תזכורות שמחזיר 500 קורא ל-``_failed``
        או רושם ``logger.error``. תופס גם וריאנטים בטקסט אחר (``Failed to save``)
        שהספירה המילולית למעלה לא רואה. מוגבל למסלולי התזכורות בכוונה: שאר מסלולי
        הפתקים פולטים אירוע anomaly בלי traceback, וזה נושא נפרד.
        """
        tree = ast.parse(Path(sticky_mod.__file__).read_text(encoding='utf-8'))
        routes = list(_reminder_route_functions(tree))
        self.assertIn('snooze_note_reminder', [fn.name for fn in routes], 'הסריקה לא מצאה את מסלולי התזכורות')
        offenders = [
            f'{fn.name}:{handler.lineno}'
            for fn in routes
            for handler in ast.walk(fn) if isinstance(handler, ast.ExceptHandler)
            if _returns_500(handler) and not _leaves_a_trace(handler)
        ]
        self.assertEqual(offenders, [], 'except שמחזיר 500 בלי עקבה במסלול תזכורות')


class TestStubProjection(unittest.TestCase):
    """הסטאב מחיל היטלה כמו מונגו — חמשת המקרים נמדדו מול MongoDB 8.0.32 בייצור לפני הכתיבה.

    ``{_id: 1}`` לבדו הוא הכללה ומחזיר רק ``_id``; ``{_id: 1, f: 0}`` הוא החרגה,
    כי ``_id`` הוא היוצא מן הכלל היחיד לאיסור על ערבוב הכללה והחרגה.
    """

    DOC = {'_id': 'r1', 'remind_at': 'R', 'note_id': 'N'}

    def _keys(self, projection):
        return sorted(_project(dict(self.DOC), projection))

    def test_id_only_is_an_inclusion(self):
        self.assertEqual(self._keys({'_id': 1}), ['_id'])

    def test_id_alongside_an_exclusion_stays_an_exclusion(self):
        self.assertEqual(self._keys({'_id': 1, 'note_id': 0}), ['_id', 'remind_at'])

    def test_excluding_id_keeps_the_rest(self):
        self.assertEqual(self._keys({'_id': 0}), ['note_id', 'remind_at'])

    def test_inclusion_can_drop_id(self):
        self.assertEqual(self._keys({'remind_at': 1, '_id': 0}), ['remind_at'])

    def test_inclusion_keeps_id_by_default(self):
        self.assertEqual(self._keys({'remind_at': 1}), ['_id', 'remind_at'])


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

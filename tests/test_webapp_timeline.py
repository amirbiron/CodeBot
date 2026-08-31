from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from webapp import app as webapp_app


_SORT_FLOOR = datetime.min.replace(tzinfo=timezone.utc)


class StubCursor(list):
    def sort(self, key, direction=None):
        if isinstance(key, list):
            key, direction = key[0]
        reverse = bool(direction and direction < 0)
        return StubCursor(sorted(self, key=lambda doc: doc.get(key) or datetime.min.replace(tzinfo=timezone.utc), reverse=reverse))

    def limit(self, n):
        return StubCursor(self[:n])


class StubCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, *args, **kwargs):
        return StubCursor([doc.copy() for doc in self._docs])

    def aggregate(self, pipeline, **kwargs):
        """‏מספיק לשלבים שהטיימליין משתמש בהם בפועל.

        סטאב אינו ראיה שהצינור נכון — הוא רק מאפשר לבדיקה כאן להמשיך לבדוק
        את מה שהיא באמת בודקת (הקיבוץ לקטגוריות בממשק). נכונות ה-``$group``
        עצמו נבדקת מול MongoDB אמיתי.
        """
        docs = [doc.copy() for doc in self._docs]
        for stage in pipeline:
            if '$match' in stage:
                continue  # הבדיקות כאן מזינות רק מסמכים שאמורים לעבור
            if '$project' in stage:
                continue
            if '$sort' in stage:
                for key, direction in reversed(list(stage['$sort'].items())):
                    docs.sort(
                        key=lambda d: d.get(key) if d.get(key) is not None else _SORT_FLOOR,
                        reverse=int(direction) < 0,
                    )
            elif '$group' in stage:
                spec = stage['$group']
                latest = {}
                for doc in docs:
                    key = doc.get('file_name')
                    if key not in latest:
                        latest[key] = doc
                if 'latest' in spec:
                    docs = [{'_id': k, 'latest': v} for k, v in latest.items()]
                else:
                    docs = [{'_id': k} for k in latest]
            elif '$replaceRoot' in stage:
                docs = [dict(d.get('latest') or {}) for d in docs]
            elif '$limit' in stage:
                docs = docs[: int(stage['$limit'])]
            elif '$count' in stage:
                return [{stage['$count']: len(docs)}]
        return docs


def test_build_activity_timeline_groups(monkeypatch):
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    files = [
        {
            '_id': 'f1',
            'file_name': 'main.py',
            'programming_language': 'python',
            'updated_at': now - timedelta(minutes=5),
            'created_at': now - timedelta(days=1),
            'version': 2,
            'description': '',
        },
    ]
    reminders = [
        {
            'note_id': 'n1',
            'status': 'pending',
            'remind_at': now + timedelta(minutes=30),
            'updated_at': now - timedelta(minutes=2),
            'last_push_success_at': None,
            'ack_at': None,
        }
    ]
    notes = [
        {
            '_id': 'n1',
            'content': 'תזכורת לבדוק בדיקות',
            'file_id': 'f1',
            'updated_at': now - timedelta(minutes=3),
        }
    ]
    stub_db = SimpleNamespace(
        code_snippets=StubCollection(files),
        note_reminders=StubCollection(reminders),
        sticky_notes=StubCollection(notes),
    )
    monkeypatch.setattr(webapp_app.TimeUtils, "format_relative_time", lambda *_: "unit-test")

    timeline = webapp_app._build_activity_timeline(stub_db, user_id=1, active_query=None, now=now)

    assert timeline['has_events'] is True
    assert timeline['filters'][0]['count'] == len(timeline['feed'])
    groups = {group['id']: group for group in timeline['groups']}
    assert 'files' in groups and groups['files']['events']
    assert 'push' in groups and groups['push']['events']
    assert 'backups' not in groups
    assert timeline['feed'][0]['group'] in {'files', 'push'}


def test_build_activity_timeline_empty(monkeypatch):
    stub_db = SimpleNamespace(
        code_snippets=StubCollection([]),
        note_reminders=StubCollection([]),
        sticky_notes=StubCollection([]),
    )
    monkeypatch.setattr(webapp_app.TimeUtils, "format_relative_time", lambda *_: "unit-test")

    timeline = webapp_app._build_activity_timeline(stub_db, user_id=1, active_query=None, now=datetime.now(timezone.utc))

    assert timeline['has_events'] is False
    assert all(not group['events'] for group in timeline['groups'])


def test_a_file_with_many_versions_is_one_event(monkeypatch):
    """קובץ עם שלוש גרסאות מייצר אירוע אחד, לא שלושה.

    כל עריכה יוצרת מסמך חדש ב-``code_snippets``, ולכן שאילתה שאינה מקבצת
    לפי שם קובץ מציפה את היסטוריית הפעולות בשורה לכל גרסה. זה בלט במיוחד
    כשפעולת מטא-דאטה נגעה בכל הגרסאות בבת אחת והחזירה את כולן לראש הרשימה.

    הטענה כאן היא על **אתר הקריאה**: שהטיימליין מבקש את הגרסה האחרונה לכל
    קובץ ולא מסמכים גולמיים. שהצינור עצמו אכן מקבץ ב-Mongo נבדק בנפרד מול
    מסד אמיתי, כי סטאב שמדמה ``$group`` מוכיח את הסטאב ולא את השאילתה.
    """
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    files = [
        {
            '_id': f'v{v}',
            'file_name': 'amir.md',
            'programming_language': 'markdown',
            'updated_at': now - timedelta(minutes=v),
            'created_at': now - timedelta(days=14),
            'version': v,
            'description': '',
        }
        for v in (1, 2, 3)
    ]
    stub_db = SimpleNamespace(
        code_snippets=StubCollection(files),
        note_reminders=StubCollection([]),
        sticky_notes=StubCollection([]),
    )
    monkeypatch.setattr(webapp_app.TimeUtils, "format_relative_time", lambda *_: "unit-test")

    timeline = webapp_app._build_activity_timeline(stub_db, user_id=1, active_query=None, now=now)

    groups = {group['id']: group for group in timeline['groups']}
    file_events = groups['files']['events']
    assert len(file_events) == 1, [e['title'] for e in file_events]
    # והמונה סופר קבצים, אחרת "טען עוד" מבטיח יותר ממה שיוצג
    counts = {f['id']: f['count'] for f in timeline['filters']}
    assert counts.get('files') == 1, counts

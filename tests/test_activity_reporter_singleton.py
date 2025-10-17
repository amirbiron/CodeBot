import importlib
from types import SimpleNamespace


def test_reuse_existing_database_client_and_no_close(monkeypatch):
    # נטרל חיבור אמיתי למסד בטסט
    monkeypatch.setenv('DISABLE_DB', '1')

    import database  # noqa: WPS433 (טסטים)

    # רענון מודול ה-reporter כדי לאפס מצב גלובלי
    import activity_reporter as ar
    importlib.reload(ar)

    # לקוח קיים שמגיע מה-DatabaseManager
    closed = {'flag': False}

    def _close():
        closed['flag'] = True

    sentinel_client = SimpleNamespace(close=_close)
    database.db.client = sentinel_client

    # אמור להחזיר את אותו לקוח בדיוק (reuse) ולא לנסות לחבר מחדש
    client = ar.get_mongo_client('mongodb://unused')
    assert client is sentinel_client

    # סגירה לא אמורה לקרוא close כי לא אנחנו יצרנו את הלקוח
    ar.close_mongo_client()
    assert closed['flag'] is False


def test_create_own_client_and_close(monkeypatch):
    # ודא שמסד הנתונים במצב ללא לקוח קיים
    monkeypatch.setenv('DISABLE_DB', '1')
    import database  # noqa: WPS433 (טסטים)
    database.db.client = None

    # רענון מודול ה-reporter כדי לאפס מצב גלובלי
    import activity_reporter as ar
    importlib.reload(ar)

    # החלפת MongoClient למחלקה מזויפת כדי למנוע חיבור אמיתי
    class FakeMongoClient:
        def __init__(self, *args, **kwargs):
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(ar, 'MongoClient', FakeMongoClient)

    client = ar.get_mongo_client('mongodb://fake')
    assert isinstance(client, FakeMongoClient)

    # עכשיו סגירה כן אמורה לסגור כי אנחנו יצרנו את הלקוח
    ar.close_mongo_client()
    assert client.closed is True

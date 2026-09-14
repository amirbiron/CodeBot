import types


def test_webapp_maintenance_cleanup_route_registered_and_allows_query_token(monkeypatch):
    # Import the Flask webapp module
    import webapp.app as webapp_app

    monkeypatch.setenv("DB_HEALTH_TOKEN", "test-db-health-token")

    class _StubDeleteColl:
        """התנגשות אינדקסים לפי **מפתח**, כמו במונגו — לא לפי שם קשיח."""

        def __init__(self, *, indexes: dict | None = None):
            self.created_indexes = []
            self.deleted_calls = 0
            self.dropped_indexes: list[str] = []
            self._idx = dict(indexes or {})

        def delete_many(self, _q):
            self.deleted_calls += 1
            return types.SimpleNamespace(deleted_count=0)

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, _name: str):
            self.dropped_indexes.append(str(_name))
            self._idx.pop(str(_name), None)
            return None

        def create_index(self, _keys, **kwargs):
            want_key = [(str(k), int(v)) for k, v in list(_keys)]
            for existing_name, meta in self._idx.items():
                if list(meta.get("key") or []) != want_key:
                    continue
                same_name = str(existing_name) == str(kwargs.get("name") or "")
                same_ttl = meta.get("expireAfterSeconds") == kwargs.get("expireAfterSeconds")
                if not (same_name and same_ttl):
                    raise RuntimeError("IndexOptionsConflict: index on the same key already exists")
            self.created_indexes.append(kwargs)
            name = str(kwargs.get("name") or "idx")
            meta = {"key": want_key}
            if kwargs.get("expireAfterSeconds") is not None:
                meta["expireAfterSeconds"] = kwargs["expireAfterSeconds"]
            self._idx[name] = meta
            return name

    class _StubCodeSnippetsColl:
        def __init__(self):
            self._idx = {
                "_id_": {"key": [("_id", 1)]},
                "search_text_idx": {"key": [("file_name", "text")]},
                "user_id_1": {"key": [("user_id", 1)]},
                "user_file_unique": {"key": [("user_id", 1), ("file_name", 1)], "unique": True},
                "junk_idx": {"key": [("x", 1)]},
            }
            self.created = []

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name: str):
            self._idx.pop(name, None)

        def create_index(self, keys, **kwargs):
            self.created.append({"keys": keys, **kwargs})
            name = str(kwargs.get("name") or "idx")
            self._idx[name] = {"key": list(keys)}
            return name

    class _StubDB:
        def __init__(self):
            self.slow_queries_log = _StubDeleteColl()
            # TTL ישן של 24 שעות בשם שגרסה קודמת של ה-endpoint יצרה
            self.service_metrics = _StubDeleteColl(
                indexes={
                    # חוסם: אותו מפתח, שם אחר
                    "ttl_cleanup_ts": {"key": [("ts", 1)], "expireAfterSeconds": 86400},
                    # אינרטי: אין שום כותב לשדה ``timestamp`` באוסף הזה
                    "ttl_cleanup": {"key": [("timestamp", 1)], "expireAfterSeconds": 86400},
                }
            )
            self.code_snippets = _StubCodeSnippetsColl()

        def __getitem__(self, name):
            # pymongo מאפשרת גם ``db["name"]`` וגם ``db.name`` (4.15.3: שתי
            # המתודות מחזירות ``Collection(self, name)``, אומת מול המקור).
            return getattr(self, str(name))

    shared_db = _StubDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: shared_db, raising=True)

    with webapp_app.app.test_client() as client:
        # Query param auth should work for maintenance_cleanup
        resp = client.get("/api/debug/maintenance_cleanup?token=test-db-health-token")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload and payload.get("ok") is True
        ttl = payload.get("ttl") or {}
        # שני השרידים הופלו — החוסם, וגם האינרטי על ``timestamp`` שלא מוחק כלום
        assert sorted((ttl.get("service_metrics_pre_drop") or {}).get("dropped", [])) == [
            "ttl_cleanup",
            "ttl_cleanup_ts",
        ]
        # 30 יום מהקבוע המשותף, ולא 86400 קשיח שסתר את טווחי הדשבורד (אישיו #3331)
        assert (ttl.get("service_metrics_ts") or {}).get("expireAfterSeconds") == 30 * 24 * 3600
        assert (ttl.get("service_metrics_ts") or {}).get("name") == "metrics_ttl"
        # אין יותר TTL על ``timestamp`` — שדה שאף כותב אינו מייצר
        assert "service_metrics_timestamp" not in ttl
        ensured = (payload.get("indexes") or {}).get("ensured") or {}
        assert ensured.get("name") == "user_updated_at"

        # But query token should NOT authorize /api/db/*
        resp2 = client.get("/api/db/pool?token=test-db-health-token")
        assert resp2.status_code == 401
        payload2 = resp2.get_json()
        assert payload2 and payload2.get("error") == "unauthorized"

        # Preview should not mutate (no deletes)
        before_deletes = shared_db.slow_queries_log.deleted_calls + shared_db.service_metrics.deleted_calls
        resp3 = client.get("/api/debug/maintenance_cleanup?token=test-db-health-token&preview=1")
        assert resp3.status_code == 200
        payload3 = resp3.get_json()
        assert payload3 and payload3.get("preview") is True
        assert payload3.get("deleted_documents", {}).get("total") == 0
        after_deletes = shared_db.slow_queries_log.deleted_calls + shared_db.service_metrics.deleted_calls
        assert after_deletes == before_deletes



def test_failed_ttl_creation_restores_the_dropped_index_and_reports_failure(monkeypatch):
    """הסדר הוא drop ואז create, ולכן כשל ביצירה משאיר אוסף **בלי TTL בכלל**.

    קודם ה-endpoint החזיר במקרה הזה ``200`` ו-``ok: true`` — הכשל נשמר כשדה
    ``status`` בתוך ה-JSON, ואף אחד לא קרא אותו. כאן נבדק שהאינדקס הישן חוזר,
    ושהתשובה אומרת שנכשלה.
    """
    import webapp.app as webapp_app

    monkeypatch.setenv("DB_HEALTH_TOKEN", "test-db-health-token")

    class _RefusingColl:
        """יוצרת אינדקסים, ומסרבת ליצור את אינדקס ה-TTL בחלון המבוקש."""

        def __init__(self, indexes=None):
            self._idx = dict(indexes or {})
            self.dropped: list[str] = []

        def delete_many(self, _q):
            return types.SimpleNamespace(deleted_count=0)

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name):
            self.dropped.append(str(name))
            self._idx.pop(str(name), None)

        def create_index(self, keys, **kwargs):
            # נכשל רק על החלון החדש. שחזור ההגדרה הישנה חייב להיות אפשרי,
            # אחרת הבדיקה בודקת "גם השחזור נכשל" ולא את השחזור עצמו.
            if kwargs.get("expireAfterSeconds") == 30 * 24 * 3600:
                raise RuntimeError("IndexOptionsConflict: simulated")
            name = str(kwargs.get("name") or "idx")
            meta = {"key": [(str(k), v) for k, v in list(keys)]}
            if kwargs.get("expireAfterSeconds") is not None:
                meta["expireAfterSeconds"] = kwargs["expireAfterSeconds"]
            self._idx[name] = meta
            return name

    class _StubCodeSnippetsColl:
        def __init__(self):
            self._idx = {"_id_": {"key": [("_id", 1)]}}
            self.created = []

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name):
            self._idx.pop(name, None)

        def create_index(self, keys, **kwargs):
            self.created.append({"keys": keys, **kwargs})
            return str(kwargs.get("name") or "idx")

    metrics = _RefusingColl(
        {
            "metrics_ttl": {"key": [("ts", 1)], "expireAfterSeconds": 86400},
            # שריד שהפלת ה-pre-drop מסירה לפני היצירה. הוא TTL **עובד** על שדה
            # אחר, ולכן כשל ביצירה שמשאיר אותו מחוץ לאוסף גרוע מהמצב ההתחלתי.
            "ttl_cleanup": {"key": [("timestamp", 1)], "expireAfterSeconds": 86400},
        }
    )

    class _StubDB:
        def __init__(self):
            self.slow_queries_log = _RefusingColl()
            self.service_metrics = metrics
            self.code_snippets = _StubCodeSnippetsColl()

        def __getitem__(self, name):
            return getattr(self, str(name))

    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB(), raising=True)

    with webapp_app.app.test_client() as client:
        resp = client.get("/api/debug/maintenance_cleanup?token=test-db-health-token")

    payload = resp.get_json()
    assert resp.status_code == 500, "כשל ביצירת TTL חזר כ-200"
    assert payload.get("ok") is False
    assert "service_metrics_ts" in (payload.get("ttl_failures") or [])
    entry = (payload.get("ttl") or {}).get("service_metrics_ts") or {}
    assert entry.get("status") == "error"
    assert entry.get("restored_previous_index") == "restored"
    # והראיה האמיתית: מצב האוסף, לא מה שהתשובה מבטיחה
    state = metrics.index_information()
    assert state.get("metrics_ttl", {}).get("expireAfterSeconds") == 86400
    # גם מה שהופל ב-pre-drop חזר — אחרת האוסף יוצא מהקריאה עם פחות משנכנס
    pre_drop = (payload.get("ttl") or {}).get("service_metrics_pre_drop") or {}
    assert pre_drop.get("dropped") == ["ttl_cleanup"]
    assert (pre_drop.get("restored") or {}).get("ttl_cleanup") == "restored"
    assert state.get("ttl_cleanup", {}).get("expireAfterSeconds") == 86400


def test_deleted_documents_names_the_collection_that_was_actually_purged(monkeypatch):
    """``METRICS_COLLECTION`` מסיט את הכותב, ולכן גם את מה שה-endpoint מוחק.

    מפתח קשיח בתשובה מייחס את המחיקה לאוסף אחר מזה שנמחק. מפתח הפרויילר באותו
    dict כבר פרמטרי מאותה סיבה.
    """
    import webapp.app as webapp_app

    monkeypatch.setenv("DB_HEALTH_TOKEN", "test-db-health-token")
    monkeypatch.setenv("METRICS_COLLECTION", "metrics_v2")

    class _Coll:
        def __init__(self):
            self._idx = {"_id_": {"key": [("_id", 1)]}}
            self.purged = 0

        def delete_many(self, _q):
            self.purged += 1
            return types.SimpleNamespace(deleted_count=7)

        def index_information(self):
            return dict(self._idx)

        def drop_index(self, name):
            self._idx.pop(str(name), None)

        def create_index(self, keys, **kwargs):
            name = str(kwargs.get("name") or "idx")
            self._idx[name] = {"key": [(str(k), v) for k, v in list(keys)]}
            return name

    metrics_v2 = _Coll()

    class _StubDB:
        def __init__(self):
            self.slow_queries_log = _Coll()
            self.metrics_v2 = metrics_v2
            self.code_snippets = _Coll()

        def __getitem__(self, name):
            return getattr(self, str(name))

    monkeypatch.setattr(webapp_app, "get_db", lambda: _StubDB(), raising=True)

    with webapp_app.app.test_client() as client:
        payload = client.get("/api/debug/maintenance_cleanup?token=test-db-health-token").get_json()

    deleted = payload.get("deleted_documents") or {}
    assert metrics_v2.purged == 1, "האוסף שהוגדר ב-METRICS_COLLECTION לא נוקה"
    assert deleted.get("metrics_v2") == 7
    assert "service_metrics" not in deleted, "הדיווח ייחס את המחיקה לאוסף שלא נגעו בו"

import importlib
import os
import sys
import types

import pytest

from bot_handlers import AdvancedBotHandlers


class _Msg:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, *a, **k):  # noqa: D401
        self.texts.append(text)


class _Update:
    def __init__(self):
        self.message = _Msg()
        self.effective_user = types.SimpleNamespace(id=1)


class _Context:
    def __init__(self, args=None):
        self.user_data = {}
        self.args = list(args or [])
        self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_once=lambda *a, **k: None))


def _seed_alert_manager():
    import alert_manager as am

    am.reset_state_for_tests()
    for _ in range(100):
        am.note_request(200, 0.05)


@pytest.mark.asyncio
async def test_observe_verbose_memory_only(monkeypatch):
    app = types.SimpleNamespace(add_handler=lambda *a, **k: None)
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context(args=["-v", "source=memory", "window=5m"])

    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)
    _seed_alert_manager()

    # Ensure internal alerts buffer returns items with timestamps in-window
    import internal_alerts as ia

    # Clear and seed with two alerts (one critical, one warn)
    try:
        ia._ALERTS.clear()  # type: ignore[attr-defined]
    except Exception:
        pass
    now_iso = "2025-10-23T03:00:00+00:00"
    try:
        ia._ALERTS.append({"ts": now_iso, "name": "A", "severity": "critical", "summary": "s"})  # type: ignore[attr-defined]
        ia._ALERTS.append({"ts": now_iso, "name": "B", "severity": "warn", "summary": "s"})  # type: ignore[attr-defined]
    except Exception:
        pass

    await adv.observe_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Observability – verbose" in out
    assert "Alerts (Memory, window=5m):" in out
    assert "critical=1" in out


def _install_fake_pymongo_for_alerts(monkeypatch, items):
    class _Coll:
        def __init__(self):
            self._items = list(items)

        def find(self, *a, **k):  # noqa: D401
            class _Cursor:
                def __init__(self, docs):
                    self._docs = docs

                def sort(self, *_a, **_k):
                    # Already ordered newest-first
                    return self

                def limit(self, *_a, **_k):
                    return self

                def __iter__(self):
                    return iter(self._docs)

            return _Cursor(self._items)

        def count_documents(self, query):  # noqa: D401
            since = query.get("ts_dt", {}).get("$gte")
            sev = query.get("severity")
            total = 0
            for d in self._items:
                ts_dt = d.get("ts_dt")
                if ts_dt is None or since is None:
                    continue
                if ts_dt >= since:
                    if not sev:
                        total += 1
                    else:
                        if str(d.get("severity", "")).lower() == "critical":
                            total += 1
            return total

    class _DB:
        def __getitem__(self, name):
            return _Coll()

    class _Client:
        def __init__(self, *a, **k):
            self.admin = types.SimpleNamespace(command=lambda *a, **k: {"ok": 1})

        def __getitem__(self, name):
            return _DB()

    fake = types.SimpleNamespace(MongoClient=_Client, ASCENDING=1)
    monkeypatch.setitem(sys.modules, "pymongo", fake)


def _import_fresh_alerts_storage(monkeypatch):
    sys.modules.pop("monitoring.alerts_storage", None)
    return importlib.import_module("monitoring.alerts_storage")


@pytest.mark.asyncio
async def test_observe_verbose_db_and_ids(monkeypatch):
    app = types.SimpleNamespace(add_handler=lambda *a, **k: None)
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context(args=["-vv", "source=db", "window=24h"])

    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)
    _seed_alert_manager()

    # Prepare fake DB docs (newest first)
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    docs = [
        {"ts_dt": now, "alert_id": "id-1", "severity": "critical"},
        {"ts_dt": now, "_key": "h:abc", "severity": "warn"},
    ]
    _install_fake_pymongo_for_alerts(monkeypatch, docs)

    # Enable DB and set URL so storage initializes
    monkeypatch.setenv("ALERTS_DB_ENABLED", "1")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")

    # Reload alerts_storage to pick up fake pymongo
    _import_fresh_alerts_storage(monkeypatch)

    await adv.observe_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Observability – verbose" in out
    assert "Alerts (DB, window=24h):" in out
    assert "Recent Alert IDs (DB, N<=10):" in out
    # IDs presence (either full id or fallback _key)
    assert ("id-1" in out) or ("h:abc" in out)

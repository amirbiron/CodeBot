import io
import json
import os
import sys
import types
from collections import namedtuple
from urllib.parse import urlparse

import pytest


def _make_zip_bytes(meta_bid: str = "b1", user_id: int = 1) -> bytes:
    import zipfile
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", "A")
        zf.writestr("metadata.json", json.dumps({"backup_id": meta_bid, "user_id": user_id}))
    return mem.getvalue()


@pytest.mark.asyncio
async def test_disk_low_alert_sends_events_and_admin_dm(tmp_path, monkeypatch):
    # Environment: force FS storage and direct backups dir
    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))
    # Admins + bot token for DM
    monkeypatch.setenv("ADMIN_USER_IDS", "77,88")
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")
    # Threshold high to guarantee alert
    monkeypatch.setenv("BACKUPS_DISK_MIN_FREE_BYTES", str(200 * 1024 * 1024))

    # Shim observability/internal_alerts/http_sync
    captured = {"events": [], "alerts": [], "dms": []}

    def _emit_event(event, severity="info", **fields):
        captured["events"].append((event, severity, fields))

    def _emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):
        captured["alerts"].append((name, severity, summary, details))

    async def _no_async(*_a, **_k):
        return None

    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=_no_async,
        init_sentry=_no_async,
        bind_request_id=_no_async,
        generate_request_id=lambda: "id",
        emit_event=_emit_event,
    )
    fake_int = types.SimpleNamespace(emit_internal_alert=_emit_internal_alert)

    def _http_request(method, url, json=None, timeout=5):  # noqa: A002 - test stub
        captured["dms"].append({"method": method, "url": url, "json": json, "timeout": timeout})
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setitem(sys.modules, "observability", fake_obs)
    monkeypatch.setitem(sys.modules, "internal_alerts", fake_int)
    monkeypatch.setitem(sys.modules, "http_sync", types.SimpleNamespace(request=_http_request))

    import file_manager as fm

    # Fake disk usage: free < threshold
    DU = namedtuple("DU", "total used free")
    monkeypatch.setattr(fm.shutil, "disk_usage", lambda path: DU(10**9, 9*10**8, 50 * 1024 * 1024))

    mgr = fm.BackupManager()
    # Defensive: reset rate-limit to allow alert
    mgr._last_disk_warn_ts = 0.0

    # Trigger save (will also try to write to tmp_path)
    bid = mgr.save_backup_bytes(_make_zip_bytes("bid_1", 7), {"backup_id": "bid_1", "user_id": 7})
    assert bid == "bid_1"

    # Assert observability event emitted
    assert any(e[0] == "disk_low_space" for e in captured["events"])  # event name
    # Assert internal alert sent
    assert any(a[0] == "disk_low_space" and "כמעט מלא" in a[2] for a in captured["alerts"])  # name + summary text
    # Assert admin DMs were attempted for both admins
    assert len(captured["dms"]) >= 2
    for rec in captured["dms"]:
        url_host = urlparse(rec["url"]).hostname
        assert url_host == "api.telegram.org" and rec["json"].get("chat_id") in (77, 88)


@pytest.mark.asyncio
async def test_disk_low_alert_uses_default_when_env_empty(tmp_path, monkeypatch):
    # Force FS and dir
    monkeypatch.setenv("BACKUPS_STORAGE", "fs")
    monkeypatch.setenv("BACKUPS_DIR", str(tmp_path))
    # Env empty string → should fallback to default 100MB
    monkeypatch.setenv("BACKUPS_DISK_MIN_FREE_BYTES", "")
    # Admins + token for DM
    monkeypatch.setenv("ADMIN_USER_IDS", "99")
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")

    captured = {"events": [], "alerts": [], "dms": []}

    def _emit_event(event, severity="info", **fields):
        captured["events"].append((event, severity, fields))

    def _emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):
        captured["alerts"].append((name, severity, summary, details))

    def _http_request(method, url, json=None, timeout=5):
        captured["dms"].append({"method": method, "url": url, "json": json, "timeout": timeout})
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setitem(sys.modules, "observability", types.SimpleNamespace(emit_event=_emit_event))
    monkeypatch.setitem(sys.modules, "internal_alerts", types.SimpleNamespace(emit_internal_alert=_emit_internal_alert))
    monkeypatch.setitem(sys.modules, "http_sync", types.SimpleNamespace(request=_http_request))

    import file_manager as fm
    DU = namedtuple("DU", "total used free")
    # Free 50MB, default threshold=100MB → should alert
    monkeypatch.setattr(fm.shutil, "disk_usage", lambda path: DU(10**9, 9*10**8, 50 * 1024 * 1024))

    mgr = fm.BackupManager()
    mgr._last_disk_warn_ts = 0.0
    assert mgr.save_backup_bytes(_make_zip_bytes("bid_2", 5), {"backup_id": "bid_2", "user_id": 5}) == "bid_2"
    assert any(e[0] == "disk_low_space" for e in captured["events"])  # default used

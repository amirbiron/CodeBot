import io
import os
import json
from types import SimpleNamespace
from importlib import import_module

import pytest


def _import_fresh():
    import sys
    mod = 'services.google_drive_service'
    sys.modules.pop(mod, None)
    return import_module(mod)


def _make_http_error(gds, status=429, reason='rateLimitExceeded', retry_after=None):
    """Construct an HttpError-like object compatible with both real and stubbed gds.HttpError.

    When googleapiclient is installed, HttpError(resp, content) is required; otherwise
    gds.HttpError may be aliased to Exception. We handle both.
    """
    class _Resp:
        def __init__(self, status, headers):
            self.status = status
            # googleapiclient.errors.HttpError accesses resp.reason in ctor
            self.reason = "Service Unavailable" if int(status) >= 500 else "Error"
            self._h = headers or {}
        def get(self, key):
            return self._h.get(key)
    headers = {}
    if retry_after is not None:
        headers['Retry-After'] = str(retry_after)
    resp = _Resp(status, headers)
    payload = {"error": {"errors": [{"reason": reason}], "message": "err"}}
    content_bytes = json.dumps(payload).encode('utf-8')
    # Try the real constructor signature first; fallback to simple Exception-like instantiation
    try:
        err = gds.HttpError(resp, content_bytes)  # type: ignore[arg-type]
        # Ensure attributes are accessible in case implementation changes
        setattr(err, 'resp', getattr(err, 'resp', resp))
        setattr(err, 'content', getattr(err, 'content', content_bytes))
    except TypeError:
        err = gds.HttpError("drive error")  # type: ignore[call-arg]
        err.resp = resp
        err.content = content_bytes
    return err


def test_upload_bytes_retries_on_429_then_success(monkeypatch):
    gds = _import_fresh()

    # Fake Drive request that fails with 429 once then succeeds
    class _Req:
        def __init__(self):
            self.calls = 0
        def next_chunk(self):
            self.calls += 1
            if self.calls == 1:
                raise _make_http_error(gds, status=429, reason='rateLimitExceeded', retry_after=0)
            return None, {"id": "fid-429-ok"}

    class _Files:
        def create(self, body=None, media_body=None, fields=None):
            assert getattr(media_body, 'resumable', False) is True
            return _Req()

    class _Svc:
        def files(self):
            return _Files()

    monkeypatch.setattr(gds, "get_drive_service", lambda uid: _Svc(), raising=True)
    monkeypatch.setattr(gds, "ensure_subpath", lambda uid, sub: "folder123", raising=True)

    class _MediaIoBaseUpload:
        def __init__(self, fh, mimetype=None, resumable=False, chunksize=None):
            assert isinstance(fh, io.BytesIO)
            self.resumable = resumable
            self.chunksize = chunksize
    monkeypatch.setattr(gds, "MediaIoBaseUpload", _MediaIoBaseUpload, raising=True)

    fid = gds.upload_bytes(1, "file.zip", b"ZIPDATA", sub_path="zip")
    assert fid == "fid-429-ok"


def test_retryable_and_parse_helpers(monkeypatch):
    gds = _import_fresh()

    # Build an HttpError with status/reason and Retry-After
    err = _make_http_error(gds, status=503, reason='backendError', retry_after=2)

    # _parse_http_error_status_reason returns status and reason
    st, rs = gds._parse_http_error_status_reason(err)
    assert st == 503
    assert isinstance(rs, str) and ("backendError" in rs or rs == "backendError")

    # _is_retryable_http_error returns True and retry_after seconds
    should_retry, ra = gds._is_retryable_http_error(err)
    assert should_retry is True
    assert ra == 2.0


def test_sleep_backoff_honors_retry_after_and_jitter(monkeypatch):
    gds = _import_fresh()

    calls = {"sleep": []}
    monkeypatch.setattr(gds.time, "sleep", lambda s: calls["sleep"].append(s), raising=True)
    # Fix randomness to deterministic 0.5 → factor 0.7 + 0.6*0.5 = 1.0
    monkeypatch.setattr(gds.random, "random", lambda: 0.5, raising=True)

    # Case 1: explicit Retry-After wins
    gds._sleep_backoff(attempt=5, retry_after_s=1.25)
    # Case 2: exponential backoff with jitter (attempt=1 → base*2 = 1.0, factor=1.0)
    gds._sleep_backoff(attempt=1, retry_after_s=None)

    assert len(calls["sleep"]) == 2
    # First call uses Retry-After exactly
    assert abs(calls["sleep"][0] - 1.25) < 1e-6
    # Second call equals 1.0 (with deterministic jitter) and not clamped below 0.05
    assert 0.99 <= calls["sleep"][1] <= 1.01

def test_upload_file_retries_on_transport_then_success(tmp_path, monkeypatch):
    gds = _import_fresh()

    p = tmp_path / "b1.zip"
    p.write_bytes(b"PK\x03\x04dummy")

    class _Req:
        def __init__(self):
            self.calls = 0
        def next_chunk(self):
            self.calls += 1
            if self.calls < 3:
                # Generic transient error (not HttpError)
                raise RuntimeError("transient io error")
            return None, {"id": "fid-tx"}

    class _Files:
        def create(self, body=None, media_body=None, fields=None):
            assert getattr(media_body, 'resumable', False) is True
            return _Req()

    class _Svc:
        def files(self):
            return _Files()

    class _MediaFileUpload:
        def __init__(self, file_path, mimetype=None, resumable=False, chunksize=None):
            assert os.path.exists(file_path)
            self.resumable = resumable
            self.chunksize = chunksize
    monkeypatch.setattr(gds, "get_drive_service", lambda uid: _Svc(), raising=True)
    monkeypatch.setattr(gds, "ensure_subpath", lambda uid, sub: "folder123", raising=True)
    monkeypatch.setattr(gds, "MediaFileUpload", _MediaFileUpload, raising=True)

    fid = gds.upload_file(9, "BKP.zip", str(p), sub_path="zip")
    assert fid == "fid-tx"


def test_upload_file_nonretryable_http_error_returns_none(tmp_path, monkeypatch):
    gds = _import_fresh()

    p = tmp_path / "b2.zip"
    p.write_bytes(b"PK\x03\x04dummy")

    class _Req:
        def next_chunk(self):
            # 400 with non-retryable reason → should not retry
            raise _make_http_error(gds, status=400, reason='badRequest')

    class _Files:
        def create(self, body=None, media_body=None, fields=None):
            return _Req()

    class _Svc:
        def files(self):
            return _Files()

    class _MediaFileUpload:
        def __init__(self, file_path, mimetype=None, resumable=False, chunksize=None):
            assert os.path.exists(file_path)
            self.resumable = resumable
            self.chunksize = chunksize

    monkeypatch.setattr(gds, "get_drive_service", lambda uid: _Svc(), raising=True)
    monkeypatch.setattr(gds, "ensure_subpath", lambda uid, sub: "folder123", raising=True)
    monkeypatch.setattr(gds, "MediaFileUpload", _MediaFileUpload, raising=True)

    fid = gds.upload_file(7, "X.zip", str(p), sub_path="zip")
    assert fid is None


def test_ensure_valid_credentials_refresh_retry_and_invalid_grant(monkeypatch):
    gds = _import_fresh()

    # tokens present
    monkeypatch.setattr(gds, "_load_tokens", lambda uid: {"access_token": "t", "refresh_token": "r", "scope": "s"}, raising=True)

    # Supply a Request class so the code won't early-return
    class _ReqCls:
        def __call__(self, *a, **k):
            return object()
    monkeypatch.setattr(gds, "Request", _ReqCls, raising=True)

    saved = {"calls": 0}
    monkeypatch.setattr(gds, "save_tokens", lambda uid, t: saved.__setitem__("calls", saved["calls"] + 1) or True, raising=True)

    # Case 1: transient failure twice then success
    class _Creds1:
        def __init__(self):
            self.expired = True
            self.refresh_token = "r"
            self.scopes = ["s"]
            from datetime import datetime, timezone, timedelta
            self.expiry = datetime.now(timezone.utc)
            self.token = "t"
            self._calls = 0
        def refresh(self, req):
            self._calls += 1
            if self._calls < 3:
                raise RuntimeError("temporary")
            from datetime import datetime, timezone, timedelta
            self.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
            self.token = "t2"
    monkeypatch.setattr(gds, "_credentials_from_tokens", lambda tok: _Creds1(), raising=True)

    c = gds._ensure_valid_credentials(5)
    assert c is not None and saved["calls"] >= 1

    # Case 2: invalid_grant → early None and no save_tokens
    saved["calls"] = 0
    class _Creds2:
        def __init__(self):
            self.expired = True
            self.refresh_token = "r"
            self.scopes = ["s"]
            from datetime import datetime, timezone
            self.expiry = datetime.now(timezone.utc)
            self.token = "t"
        def refresh(self, req):
            raise RuntimeError("invalid_grant: expired")
    monkeypatch.setattr(gds, "_credentials_from_tokens", lambda tok: _Creds2(), raising=True)

    c2 = gds._ensure_valid_credentials(6)
    assert c2 is None and saved["calls"] == 0

"""
בדיקות ליחידות עזר של TLS/SSL בחיבור MongoDB (database/manager.py).

מכסה:
- זיהוי URI שמפעיל TLS (Atlas SRV / tls=true) לעומת חיבור מקומי לא מוצפן.
- בניית פרמטרי TLS (tlsCAFile) עם certifi, עקיפה מפורשת, וכיבוי.
- זיהוי שגיאת לחיצת יד TLS לפי טקסט השגיאה (למשל TLSV1_ALERT_INTERNAL_ERROR).

הפונקציות טהורות ולא נוגעות ב-DB אמיתי — בטוח להריץ ב-CI.
"""

import database.manager as mgr

# מחרוזות לדוגמה (ללא סודות אמיתיים)
SRV_URI = "mongodb+srv://user:pass@cluster.n40zbsq.mongodb.net/db?retryWrites=true"
SRV_URI_TLS_OFF = "mongodb+srv://user:pass@cluster.n40zbsq.mongodb.net/db?tls=false"
PLAIN_LOCAL = "mongodb://localhost:27017/test"
PLAIN_TLS_ON = "mongodb://host:27017/?tls=true"

# דוגמת השגיאה האמיתית מהלוגים
REAL_TLS_ERROR = (
    "SSL handshake failed: ac-uxq3stk-shard-00-02.n40zbsq.mongodb.net:27017: "
    "[SSL: TLSV1_ALERT_INTERNAL_ERROR] tlsv1 alert internal error (_ssl.c:1016)"
)


def test_uri_uses_tls_detection():
    assert mgr._uri_uses_tls(SRV_URI) is True
    assert mgr._uri_uses_tls(PLAIN_TLS_ON) is True
    assert mgr._uri_uses_tls(PLAIN_LOCAL) is False
    assert mgr._uri_uses_tls(SRV_URI_TLS_OFF) is False
    assert mgr._uri_uses_tls(None) is False
    assert mgr._uri_uses_tls("") is False


def test_build_tls_kwargs_uses_certifi_for_srv(monkeypatch):
    # ברירת מחדל: אין CA מפורש, certifi דלוק
    monkeypatch.delenv("MONGODB_TLS_CA_FILE", raising=False)
    monkeypatch.delenv("MONGODB_TLS_USE_CERTIFI", raising=False)

    kwargs = mgr._build_tls_kwargs(SRV_URI)
    if mgr._CERTIFI_AVAILABLE:
        assert "tlsCAFile" in kwargs
        assert kwargs["tlsCAFile"]  # נתיב לא ריק
    else:  # pragma: no cover - בסביבת CI certifi זמין
        assert kwargs == {}


def test_build_tls_kwargs_noop_for_plain_local(monkeypatch):
    monkeypatch.delenv("MONGODB_TLS_CA_FILE", raising=False)
    monkeypatch.delenv("MONGODB_TLS_USE_CERTIFI", raising=False)
    # חיבור מקומי לא מוצפן — אין להוסיף פרמטרי TLS כלל
    assert mgr._build_tls_kwargs(PLAIN_LOCAL) == {}


def test_build_tls_kwargs_explicit_ca_wins(monkeypatch, tmp_path):
    ca = tmp_path / "custom-ca.pem"
    ca.write_text("dummy")
    monkeypatch.setenv("MONGODB_TLS_CA_FILE", str(ca))
    # גם אם certifi דלוק — נתיב מפורש מנצח
    monkeypatch.setenv("MONGODB_TLS_USE_CERTIFI", "true")
    kwargs = mgr._build_tls_kwargs(SRV_URI)
    assert kwargs.get("tlsCAFile") == str(ca)


def test_build_tls_kwargs_disable_certifi(monkeypatch):
    monkeypatch.delenv("MONGODB_TLS_CA_FILE", raising=False)
    monkeypatch.setenv("MONGODB_TLS_USE_CERTIFI", "false")
    # כיבוי certifi ובלי CA מפורש — משאירים את ברירת המחדל של pymongo (בלי tlsCAFile)
    assert mgr._build_tls_kwargs(SRV_URI) == {}


def test_looks_like_tls_handshake_error():
    assert mgr._looks_like_tls_handshake_error(REAL_TLS_ERROR) is True
    assert mgr._looks_like_tls_handshake_error(Exception(REAL_TLS_ERROR)) is True
    assert mgr._looks_like_tls_handshake_error("certificate verify failed") is True
    assert mgr._looks_like_tls_handshake_error("some unrelated timeout") is False
    assert mgr._looks_like_tls_handshake_error(None) is False

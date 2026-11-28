"""ההפניה מכתובת ישנה של ה-WebApp לכתובת שב-``WEBAPP_URL`` (``webapp/legacy_host_redirect.py``).

מה מופנה ומה לא, ולמה — ב-docstring של המודול. כאן: התצורה (תקינה, חסרה, פגומה), ההחלטה לכל סוג בקשה, הכתובת שנבנית
(אותו נתיב ואותם פרמטרים, מקודדים), הרישום כ-``before_request`` הראשון, ``/health`` ושורת הלוג בעלייה. רוב הטסטים
עוברים דרך האפליקציה האמיתית, כמו דפדפן שמבקש את הכתובת הישנה; ההחלטה לפי מתודה ולפי נתיב נבדקת גם ישירות, על בקשה
מדומה, כדי לכסות נתיבים שה-handler שלהם עושה עבודה.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import logging
import re
import time
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

pytest.importorskip("flask")

from webapp import legacy_host_redirect as lhr  # noqa: E402

OLD_HOST = "codekeeper-webapp.onrender.com"
OLD = f"https://{OLD_HOST}"
NEW = "https://codekeeper.dev"
MCP = "https://codekeepermcp.onrender.com"
SECRET = "unit-test-secret-key-0123456789"
BOT_TOKEN = "123456:ABC-test-token"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("WEBAPP_URL", NEW)
    monkeypatch.setenv("WEBAPP_LEGACY_HOSTS", OLD_HOST)
    monkeypatch.delenv("WEBAPP_LEGACY_REDIRECT_PERMANENT", raising=False)


@pytest.fixture
def client():
    from webapp import app as webapp_app

    return webapp_app.app.test_client()


def _old_get(client, path, **kwargs):
    return client.get(path, base_url=OLD, follow_redirects=False, **kwargs)


def _fake_request(method="GET", host=OLD_HOST, path="/files", query_string=b"", endpoint="files"):
    return SimpleNamespace(method=method, host=host, path=path, query_string=query_string, endpoint=endpoint)


# --- התצורה -----------------------------------------------------------------------------------------------------


def test_without_legacy_hosts_the_redirect_is_off(monkeypatch):
    monkeypatch.setenv("WEBAPP_URL", NEW)
    monkeypatch.delenv("WEBAPP_LEGACY_HOSTS", raising=False)

    assert lhr.legacy_redirect_config().state == lhr.STATE_OFF
    assert lhr.legacy_redirect_for(_fake_request()) is None


def test_a_valid_configuration_is_on_with_302_by_default(configured):
    config = lhr.legacy_redirect_config()

    assert config.state == lhr.STATE_ON
    assert config.hosts == frozenset({OLD_HOST})
    assert config.target == NEW
    assert config.status_code == 302


@pytest.mark.parametrize("flag", ["true", "1", "YES", " on "])
def test_the_permanent_flag_switches_to_301(configured, monkeypatch, flag):
    monkeypatch.setenv("WEBAPP_LEGACY_REDIRECT_PERMANENT", flag)

    assert lhr.legacy_redirect_config().status_code == 301


@pytest.mark.parametrize("flag", ["", "false", "0", "no", "off"])
def test_a_false_flag_keeps_302(configured, monkeypatch, flag):
    monkeypatch.setenv("WEBAPP_LEGACY_REDIRECT_PERMANENT", flag)

    assert lhr.legacy_redirect_config().status_code == 302


@pytest.mark.parametrize(
    ("hosts", "webapp_url", "flag", "problem"),
    [
        (f"https://{OLD_HOST}", NEW, None, "bad_host"),  # scheme
        (f"{OLD_HOST}/files", NEW, None, "bad_host"),  # נתיב
        (f"{OLD_HOST},", NEW, None, "bad_host"),  # פריט ריק
        ("user@" + OLD_HOST, NEW, None, "bad_host"),
        (f"{OLD_HOST}:0", NEW, None, "bad_host"),  # פורט 0 — אותו דקדוק כמו WEBAPP_URL
        (OLD_HOST, None, None, "no_webapp_url"),
        (OLD_HOST, f"{NEW}/", None, "no_webapp_url"),  # WEBAPP_URL פגום — אין לאן להפנות
        ("codekeeper.dev", NEW, None, "legacy_is_canonical"),  # לולאה
        ("CodeKeeper.DEV", NEW, None, "legacy_is_canonical"),
        (OLD_HOST, NEW, "ture", "bad_permanent_flag"),
    ],
)
def test_an_invalid_configuration_redirects_nothing(monkeypatch, hosts, webapp_url, flag, problem):
    monkeypatch.setenv("WEBAPP_LEGACY_HOSTS", hosts)
    if webapp_url is None:
        monkeypatch.delenv("WEBAPP_URL", raising=False)
    else:
        monkeypatch.setenv("WEBAPP_URL", webapp_url)
    if flag is None:
        monkeypatch.delenv("WEBAPP_LEGACY_REDIRECT_PERMANENT", raising=False)
    else:
        monkeypatch.setenv("WEBAPP_LEGACY_REDIRECT_PERMANENT", flag)

    config = lhr.legacy_redirect_config()

    assert config.state == lhr.STATE_INVALID
    assert config.problem == problem
    assert lhr.legacy_redirect_for(_fake_request()) is None


def test_several_legacy_hosts_are_comma_separated(configured, monkeypatch):
    monkeypatch.setenv("WEBAPP_LEGACY_HOSTS", f" {OLD_HOST} , Old.Example.com ")

    assert lhr.legacy_redirect_config().hosts == frozenset({OLD_HOST, "old.example.com"})
    assert lhr.legacy_redirect_for(_fake_request(host="old.example.com")) is not None


# --- ההחלטה, על בקשה מדומה ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_only_get_and_head_are_redirected(configured, method):
    assert lhr.legacy_redirect_for(_fake_request(method=method)) is None


@pytest.mark.parametrize(
    "path",
    ["/api", "/api/", "/api/drive/callback", "/api/webhooks/github", "/api/sticky-notes/reminders/ack"],
)
def test_api_paths_are_not_redirected(configured, path):
    assert lhr.legacy_redirect_for(_fake_request(path=path, endpoint=None)) is None


def test_a_path_that_only_starts_with_api_is_a_page(configured):
    # גבול מקטע ולא קידומת של תווים (K16)
    assert lhr.legacy_redirect_for(_fake_request(path="/apiary", endpoint=None)) == (f"{NEW}/apiary", 302)


@pytest.mark.parametrize("endpoint", sorted(lhr.EXEMPT_ENDPOINTS))
def test_exempt_endpoints_are_not_redirected(configured, endpoint):
    assert lhr.legacy_redirect_for(_fake_request(path="/whatever", endpoint=endpoint)) is None


def test_every_exempt_endpoint_is_registered_in_the_app():
    """שם שלא קיים באפליקציה (נתיב ששמו שונה) היה מוציא את הנקודה מההחרגה בשקט — והיא הייתה מופנית."""
    from webapp import app as webapp_app

    assert lhr.EXEMPT_ENDPOINTS <= set(webapp_app.app.view_functions), sorted(
        lhr.EXEMPT_ENDPOINTS - set(webapp_app.app.view_functions)
    )


@pytest.mark.parametrize(
    "host",
    [
        "codekeeper.dev",
        f"{OLD_HOST}.evil.net",  # מתחיל באותם תווים
        f"x{OLD_HOST}",  # מסתיים באותם תווים
        f"{OLD_HOST}:8443",  # פורט אחר הוא מארח אחר
        "",
    ],
)
def test_only_the_exact_legacy_host_is_redirected(configured, host):
    assert lhr.legacy_redirect_for(_fake_request(host=host)) is None


def test_the_host_comparison_ignores_case(configured):
    assert lhr.legacy_redirect_for(_fake_request(host=OLD_HOST.upper())) == (f"{NEW}/files", 302)


@pytest.mark.parametrize(
    ("listed", "request_host"),
    [
        (f"{OLD_HOST}:443", OLD_HOST),  # הפורט ברשימה, לא בכותרת
        (OLD_HOST, f"{OLD_HOST}:443"),  # הפורט בכותרת, לא ברשימה
    ],
)
def test_the_default_https_port_is_the_same_host(configured, monkeypatch, listed, request_host):
    # RFC 9110, 4.2.3: פורט ששווה לברירת המחדל של ה-scheme מושמט בצורה הנורמלית
    monkeypatch.setenv("WEBAPP_LEGACY_HOSTS", listed)

    assert lhr.legacy_redirect_for(_fake_request(host=request_host)) == (f"{NEW}/files", 302)


def test_the_loop_guard_sees_through_the_default_port(monkeypatch):
    # ``WEBAPP_URL`` עם :443 והכתובת הקנונית בלעדיו ברשימה — אותו מארח, כלומר לולאה
    monkeypatch.setenv("WEBAPP_URL", f"{NEW}:443")
    monkeypatch.setenv("WEBAPP_LEGACY_HOSTS", "codekeeper.dev")

    config = lhr.legacy_redirect_config()

    assert config.state == lhr.STATE_INVALID
    assert config.problem == "legacy_is_canonical"


def test_a_path_that_looks_like_another_host_stays_on_the_new_host(configured):
    # שורת בקשה ``GET //evil.example/x`` מגיעה עם ``PATH_INFO`` כזה. ה-test client של Werkzeug מפרש את המחרוזת הזו
    # כמארח ונתיב, ולכן הבדיקה כאן על בקשה מדומה.
    location, _ = lhr.legacy_redirect_for(_fake_request(path="//evil.example/x", endpoint=None))

    assert location == f"{NEW}//evil.example/x"


# --- דרך האפליקציה --------------------------------------------------------------------------------------------------


def test_the_redirect_hook_runs_before_every_other_before_request():
    from webapp import app as webapp_app

    assert webapp_app.app.before_request_funcs[None][0] is webapp_app._redirect_legacy_host


@pytest.mark.parametrize("method", ["get", "head"])
def test_a_page_on_the_old_host_moves_with_its_path_and_query(configured, client, method):
    resp = getattr(client, method)("/share/abc123?view=raw&x=%D7%90&y=a%26b", base_url=OLD, follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["Location"] == f"{NEW}/share/abc123?view=raw&x=%D7%90&y=a%26b"


def test_the_permanent_flag_answers_301_through_the_app(configured, client, monkeypatch):
    monkeypatch.setenv("WEBAPP_LEGACY_REDIRECT_PERMANENT", "true")

    resp = _old_get(client, "/files")

    assert resp.status_code == 301
    assert resp.headers["Location"] == f"{NEW}/files"


def test_a_page_without_a_query_gets_no_question_mark(configured, client):
    assert _old_get(client, "/gallery").headers["Location"] == f"{NEW}/gallery"


@pytest.mark.parametrize(
    ("path", "expected_path"),
    [
        ("/read/%D7%A7%D7%95%D7%91%D7%A5.md", "/read/%D7%A7%D7%95%D7%91%D7%A5.md"),  # עברית בנתיב
        ("/read/100%25.md", "/read/100%25.md"),  # אחוז אמיתי חוזר כ-%25 ולא כ-% בודד
        ("/read/a%0D%0ALocation:%20x", "/read/a%0D%0ALocation:%20x"),  # שורה חדשה נשארת מקודדת — אין כותרת נוספת
    ],
)
def test_the_location_is_an_encoded_uri_on_the_new_host(configured, client, path, expected_path):
    resp = _old_get(client, path)

    assert resp.status_code == 302
    assert resp.headers["Location"] == NEW + expected_path
    assert "\n" not in resp.headers["Location"] and "\r" not in resp.headers["Location"]


def test_an_unknown_path_is_redirected_and_answers_404_on_the_new_host(configured, client):
    assert _old_get(client, "/no-such-page").headers["Location"] == f"{NEW}/no-such-page"


def test_the_new_host_is_never_redirected(configured, client):
    resp = client.get("/gallery", base_url=NEW, follow_redirects=False)

    assert resp.status_code == 200


def test_without_configuration_the_old_host_serves_the_page(client, monkeypatch):
    monkeypatch.setenv("WEBAPP_URL", NEW)
    monkeypatch.delenv("WEBAPP_LEGACY_HOSTS", raising=False)

    assert _old_get(client, "/gallery").status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/sw.js",
        "/static/manifest.json",
        "/favicon.ico",
        "/healthz",
        "/health",
        "/metrics",
        "/google7bb000f75b7bf329.html",
        "/api/push/public-key",
    ],
)
def test_machine_and_subresource_paths_answer_on_the_old_host(configured, client, path):
    resp = _old_get(client, path)

    assert not (300 <= resp.status_code < 400), (path, resp.status_code, resp.headers.get("Location"))


def test_the_service_worker_script_answers_200_on_the_old_host(configured, client):
    resp = _old_get(client, "/sw.js")

    assert resp.status_code == 200
    assert resp.mimetype == "application/javascript"


def test_a_post_on_the_old_host_is_not_redirected(configured, client):
    # ``/alertmanager/webhook`` — webhook שנשלח בגוף, ונשאר בכתובת הישנה עד שעובר בנפרד
    resp = client.post("/alertmanager/webhook", base_url=OLD, json={}, follow_redirects=False)

    assert not (300 <= resp.status_code < 400), resp.status_code


def test_the_bot_login_link_moves_before_the_token_is_used(configured, client, monkeypatch):
    """``/auth/token`` מופנה לפני שה-handler רץ: הטוקן החד-פעמי לא נצרך בכתובת הישנה, וה-session נוצר בחדשה."""
    import webapp.routes.auth_routes as auth_routes

    def _must_not_run():
        raise AssertionError("the token handler ran on the old host")

    monkeypatch.setattr(auth_routes, "_get_db_for_auth", _must_not_run)

    resp = _old_get(client, "/auth/token?token=t0k&user_id=42")

    assert resp.status_code == 302
    assert resp.headers["Location"] == f"{NEW}/auth/token?token=t0k&user_id=42"


def test_the_telegram_widget_callback_moves_with_its_signed_fields(configured, client):
    query = "id=77&first_name=A&auth_date=1700000000&hash=abc"

    resp = _old_get(client, f"/auth/telegram?{query}")

    assert resp.headers["Location"] == f"{NEW}/auth/telegram?{query}"


def _tg_hash(fields: dict) -> str:
    # האלגוריתם של Telegram Login Widget, כמו ב-``tests/test_webapp_oauth_identify.py``
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    return hmac.new(hashlib.sha256(BOT_TOKEN.encode()).digest(), dcs.encode(), hashlib.sha256).hexdigest()


def test_a_signed_out_user_keeps_the_oauth_parameters_from_the_old_host_through_telegram_login(
    configured, client, monkeypatch
):
    """הרשאה חדשה של הקונקטור, כשהמשתמש מנותק: מהכתובת הישנה, דרך התחברות עם טלגרם בדומיין החדש, ובחזרה ל-MCP.

    ה-MCP שולח את הדפדפן ל-``/oauth/identify`` עם ``txn`` ו-``return``. כאן הבקשה מגיעה לכתובת הישנה (``WEBAPP_URL`` של
    ה-MCP עוד לא עודכן, או דף שנפתח לפני המעבר), מופנית לדומיין החדש, ושם — בלי session — מוצג הווידג'ט. הכתובת
    שהווידג'ט חוזר אליה נלקחת מה-``data-auth-url`` שבדף, וטלגרם מוסיף לה את השדות החתומים. בסוף: טופס POST ל-MCP, עם
    אותו ``txn`` ועם הזדהות חתומה. החלק היחיד שלא רץ כאן הוא השרת של טלגרם; ההנחה שהוא מוסיף את השדות אחרי ה-query
    הקיים היא ההנחה שהזרימה כבר נשענת עליה בייצור (``_oauth_login_html`` ב-``webapp/routes/auth_routes.py``).
    """
    from mcp_server.oauth_identity import verify_identity

    monkeypatch.setenv("MCP_SERVER_URL", MCP)
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("BOT_TOKEN", BOT_TOKEN)
    txn = "txn/with spaces&symbols"
    return_url = f"{MCP}/oauth/consent"
    start = "/oauth/identify?" + urlencode({"txn": txn, "return": return_url})

    first = _old_get(client, start)
    assert first.status_code == 302
    assert first.headers["Location"] == NEW + start

    widget = client.get(first.headers["Location"], follow_redirects=False)
    assert widget.status_code == 200
    auth_url = html.unescape(re.search(r'data-auth-url="([^"]+)"', widget.get_data(as_text=True)).group(1))
    assert auth_url.startswith(f"{NEW}/oauth/identify?")

    tg = {"id": "77", "first_name": "A", "auth_date": str(int(time.time()))}
    back = client.get(f"{auth_url}&{urlencode({**tg, 'hash': _tg_hash(tg)})}", follow_redirects=False)

    assert back.status_code == 200
    body = back.get_data(as_text=True)
    assert f'action="{return_url}"' in body
    fields = dict(re.findall(r'name="([^"]+)"\s+value="([^"]*)"', body))
    assert html.unescape(fields["txn"]) == txn
    assert fields["user_id"] == "77"
    assert verify_identity(SECRET, "77", txn, fields["exp"], fields["sig"])


# --- הכתובת הקנונית של הדפים הציבוריים ------------------------------------------------------------------------------


def _public_endpoints():
    from webapp import app as webapp_app

    return list(webapp_app.SITEMAP_ENDPOINTS)


@pytest.mark.parametrize("endpoint", _public_endpoints())
def test_every_public_page_declares_webapp_url_as_canonical_and_og_url(configured, client, endpoint):
    """הדפים שב-``sitemap.xml`` מצביעים לסורקים על ``WEBAPP_URL`` — ב-``canonical`` וב-``og:url``."""
    from flask import url_for

    from webapp import app as webapp_app

    with webapp_app.app.test_request_context():
        path = url_for(endpoint)
    body = client.get(path, base_url=NEW).get_data(as_text=True)

    assert f'<link rel="canonical" href="{NEW}{path}">' in body
    assert f'<meta property="og:url" content="{NEW}{path}">' in body


# --- /health ושורת הלוג ---------------------------------------------------------------------------------------------


def test_health_shows_the_redirect_state_and_code(configured, client):
    config = client.get("/health", base_url=NEW).get_json()["config"]

    assert config["WEBAPP_LEGACY_REDIRECT"] == "on"
    assert config["WEBAPP_LEGACY_REDIRECT_CODE"] == 302
    assert "WEBAPP_LEGACY_REDIRECT_PROBLEM" not in config


def test_health_shows_the_problem_of_an_invalid_configuration(client, monkeypatch):
    monkeypatch.setenv("WEBAPP_URL", NEW)
    monkeypatch.setenv("WEBAPP_LEGACY_HOSTS", "codekeeper.dev")

    config = client.get("/health", base_url=NEW).get_json()["config"]

    assert config["WEBAPP_LEGACY_REDIRECT"] == "invalid"
    assert config["WEBAPP_LEGACY_REDIRECT_PROBLEM"] == "legacy_is_canonical"
    assert "WEBAPP_LEGACY_REDIRECT_CODE" not in config


def test_the_startup_line_is_info_when_on(configured, caplog):
    with caplog.at_level(logging.INFO):
        lhr.log_legacy_redirect_status(logging.getLogger("t"))

    (record,) = [r for r in caplog.records if r.name == "t"]
    assert record.levelno == logging.INFO
    assert OLD_HOST in record.getMessage() and NEW in record.getMessage()


def test_the_startup_line_is_an_error_when_invalid(monkeypatch, caplog):
    monkeypatch.setenv("WEBAPP_URL", NEW)
    monkeypatch.setenv("WEBAPP_LEGACY_HOSTS", f"https://{OLD_HOST}")

    with caplog.at_level(logging.INFO):
        lhr.log_legacy_redirect_status(logging.getLogger("t"))

    (record,) = [r for r in caplog.records if r.name == "t"]
    assert record.levelno == logging.ERROR
    assert "bad_host" in record.getMessage()

"""האפליקציה המלאה של שרת ה-MCP, בשני מצבי האימות — לטסטים שעוברים דרכה.

פונקציות ולא fixtures, מאותה סיבה של ``_save_layer_harness.py``: fixture מיובא
נרשם מחדש במודול שמייבא אותו (T3).

**מצב OAuth — הייצור — מאמת עכשיו גם PAT.** עד ההעלאות הרתמה של
``tests/test_mcp_limits.py`` בנתה את הספק עם ``pat_verify=lambda t: None``, כלומר
אף טוקן לא עבר, ובמצב שרץ בייצור רק 401 היה נבדק. ``load_access_token`` מנתב
טוקן שמתחיל ב-``ckmcp_`` ל-``pat_verify`` (``mcp_server/oauth_provider.py``), ולכן
טוקן כזה ב-``PatTokens`` עובר את ``authenticate_bearer`` בשני המצבים — וכך גם
201 ו-429 נבדקים במצב הייצור ולא רק ב-PAT.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from typing import Any

from _fake_mongo import FakeDB

OAUTH_BASE = "https://mcp.test"


class PatTokens:
    """‏``token_store`` מדומה: ``verify(token)`` כמו ``MCPTokenStore.verify``.

    ``principals`` ממפה טוקן ל-``{"user_id", "scopes"}``. אותו אובייקט משמש את
    שני המצבים: במצב PAT כ-``token_store``, ובמצב OAuth כ-``pat_verify`` של הספק.
    """

    def __init__(self, principals: dict[str, dict[str, Any]]) -> None:
        self.principals = dict(principals)

    def verify(self, token: str) -> dict[str, Any] | None:
        principal = self.principals.get(token)
        return dict(principal) if principal else None


def oauth_app(backend: Any, *, tokens: PatTokens | None = None, **kwargs: Any) -> Any:
    """האפליקציה במצב OAuth — הייצור — כפי ש-``tests/test_mcp_oauth_e2e.py`` בונה אותה.

    ``tokens`` — ה-PATs שהספק מקבל. בלעדיו אף טוקן אינו עובר, כמו ברתמה המקורית.
    """
    from pydantic import AnyHttpUrl

    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
    from mcp_server.oauth_provider import CodeKeeperOAuthProvider
    from mcp_server.oauth_routes import oauth_consent_routes
    from mcp_server.oauth_store import OAuthStore
    from mcp_server.server import build_app

    store = OAuthStore(FakeDB())
    provider = CodeKeeperOAuthProvider(
        store=store, pat_verify=tokens.verify if tokens is not None else (lambda t: None),
        identify_url=f"{OAUTH_BASE}/fake-identify", consent_url=f"{OAUTH_BASE}/oauth/consent",
    )
    settings = AuthSettings(
        issuer_url=AnyHttpUrl(OAUTH_BASE), resource_server_url=AnyHttpUrl(OAUTH_BASE),
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=["read", "write"], default_scopes=["read"]),
        revocation_options=RevocationOptions(enabled=True), required_scopes=[],
    )
    return build_app(backend, auth_provider=provider, auth_settings=settings,
                     consent_routes=oauth_consent_routes(store, "e2e-secret"), **kwargs)


def pat_app(backend: Any, *, tokens: PatTokens, **kwargs: Any) -> Any:
    """האפליקציה במצב PAT בלבד — ``PATAuthMiddleware`` שומר עליה."""
    from mcp_server.server import build_app

    return build_app(backend, tokens, **kwargs)


def app_in_mode(mode: str, backend: Any, *, tokens: PatTokens, **kwargs: Any) -> Any:
    if mode == "oauth":
        return oauth_app(backend, tokens=tokens, **kwargs)
    if mode == "pat":
        return pat_app(backend, tokens=tokens, **kwargs)
    raise ValueError(mode)


def tool_call_over_http(client: Any, token: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """``tools/call`` דרך ``POST /mcp`` כמו שלקוח שולח — ומה שבבלוק הטקסט של התשובה.

    ``is_error`` הוא ``isError`` של התוצאה, ו-``text`` הוא הטקסט כמו שהוא; מי שקורא
    לכלי שמחזיר JSON מפענח אותו בעצמו.
    """
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": name, "arguments": arguments}},
        headers={"authorization": f"Bearer {token}", "accept": "application/json, text/event-stream"},
    )
    assert response.status_code == 200, response.text
    data = next(line[len("data: "):] for line in response.text.splitlines() if line.startswith("data: "))
    result = json.loads(data)["result"]
    return {"is_error": result.get("isError"), "text": result["content"][0]["text"]}


class Served:
    """האפליקציה על uvicorn אמיתי, ב-127.0.0.1 ובפורט שמערכת ההפעלה בוחרת."""

    def __init__(self, app: Any) -> None:
        import uvicorn

        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "Served":
        self.thread.start()
        deadline = time.monotonic() + 20
        while not self.server.started:
            assert self.thread.is_alive(), "uvicorn did not start"
            assert time.monotonic() < deadline, "uvicorn did not start in time"
            time.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=20)


def curl_path() -> str:
    """הנתיב ל-``curl`` — ובקול, לא בדילוג, כשהוא חסר: טסט שמריץ את הפקודה שבתיאור כלי
    אינו בודק את מה שהסוכן מריץ בלעדיו."""
    path = shutil.which("curl")
    assert path, "curl is required: this test runs the command the tool description gives"
    return path


#: תחילית לסקריפט שרץ בתהליך נקי (``python -B -c``): מייבאת את ``mcp_server.app``, ולכן
#: הלוגים מוגדרים בדיוק כמו בשירות. השורות שהתהליך מדפיס הן הנראות היחידה בייצור, ולכן
#: הן נבדקות שם ולא ב-``caplog``. ``repo`` ו-``tests`` ממולאים ב-``str.format``.
SERVICE_LOGGING = """
import os, sys
sys.path.insert(0, {repo!r})
sys.path.insert(0, {tests!r})
os.environ["MCP_PUSH_NOTIFICATIONS_ENABLED"] = "false"
import mcp_server.app  # noqa: F401
print("SERVICE-LOGGING-READY", flush=True)
"""

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

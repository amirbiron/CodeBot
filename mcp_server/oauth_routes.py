"""MCP-side consent routes for the OAuth flow.

The webapp authenticates the user (Telegram) and redirects here with a signed
``user_id`` assertion bound to the pending ``txn``. We verify it, show a consent
screen, and on approval mint the authorization code and redirect back to the
OAuth client's ``redirect_uri`` (Claude). Denial redirects back with an error.
"""

from __future__ import annotations

import html
from typing import Any

import anyio
from mcp.server.auth.provider import construct_redirect_uri
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

from .oauth_identity import verify_identity
from .oauth_store import CODE_PREFIX, OAuthStore, new_secret


def _bad(msg: str) -> PlainTextResponse:
    return PlainTextResponse(msg, status_code=400)


def _consent_html(
    txn: str, user_id: str, exp: str, sig: str, *, client_name: str, scopes: str
) -> str:
    esc = html.escape
    return f"""<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CodeKeeper — חיבור ל‑Claude</title>
<style>
  body {{ font-family: system-ui, sans-serif; background:#0f1115; color:#e6e6e6;
         display:flex; min-height:100vh; align-items:center; justify-content:center; margin:0; }}
  .card {{ background:#1a1d24; border:1px solid #2a2f3a; border-radius:14px; padding:28px;
          max-width:420px; width:90%; box-shadow:0 10px 40px rgba(0,0,0,.4); }}
  h1 {{ font-size:20px; margin:0 0 6px; }} p {{ color:#a9b1bd; line-height:1.6; }}
  .scopes {{ background:#12151b; border-radius:8px; padding:10px 14px; margin:14px 0; }}
  .row {{ display:flex; gap:10px; margin-top:18px; }}
  button {{ flex:1; padding:12px; border-radius:10px; border:0; font-size:15px; cursor:pointer; }}
  .approve {{ background:#3b82f6; color:#fff; }} .deny {{ background:#2a2f3a; color:#e6e6e6; }}
</style></head><body>
  <div class="card">
    <h1>🔌 חיבור הקבצים שלך ל‑Claude</h1>
    <p><b>{esc(client_name)}</b> מבקש גישה <b>לקריאה בלבד</b> לקבצים ולאוספים שלך ב‑CodeKeeper.</p>
    <div class="scopes">הרשאות: {esc(scopes)}</div>
    <form method="post" action="/oauth/consent">
      <input type="hidden" name="txn" value="{esc(txn)}">
      <input type="hidden" name="user_id" value="{esc(user_id)}">
      <input type="hidden" name="exp" value="{esc(exp)}">
      <input type="hidden" name="sig" value="{esc(sig)}">
      <div class="row">
        <button class="deny" name="action" value="deny">ביטול</button>
        <button class="approve" name="action" value="approve">אישור וחיבור</button>
      </div>
    </form>
  </div>
</body></html>"""


def oauth_consent_routes(store: OAuthStore, secret: str) -> list[Route]:
    async def _load_valid_txn(params: Any) -> tuple[dict | None, str, str]:
        """Return (txn_doc|None, user_id, error). Verifies the signed assertion."""
        txn = params.get("txn") or ""
        uid = params.get("user_id") or ""
        exp = params.get("exp") or ""
        sig = params.get("sig") or ""
        if not (txn and uid and exp and sig):
            return None, uid, "missing_fields"
        if not verify_identity(secret, uid, txn, exp, sig):
            return None, uid, "bad_assertion"
        doc = await anyio.to_thread.run_sync(store.get_txn, txn)
        if not doc:
            return None, uid, "expired_txn"
        return doc, uid, ""

    async def consent_get(request):
        doc, uid, err = await _load_valid_txn(request.query_params)
        if err:
            return _bad(f"Authorization error: {err}")
        scopes = " ".join(doc.get("scopes") or ["read"])
        return HTMLResponse(
            _consent_html(
                request.query_params["txn"],
                uid,
                request.query_params["exp"],
                request.query_params["sig"],
                client_name=str(doc.get("client_id") or "Claude"),
                scopes=scopes,
            )
        )

    async def consent_post(request):
        form = await request.form()
        doc, uid, err = await _load_valid_txn(form)
        if err:
            return _bad(f"Authorization error: {err}")
        txn = form["txn"]
        redirect_base = doc["redirect_uri"]
        state = doc.get("state")

        if form.get("action") == "deny":
            await anyio.to_thread.run_sync(store.delete_txn, txn)
            uri = construct_redirect_uri(redirect_base, error="access_denied", state=state)
            return RedirectResponse(uri, status_code=302)

        code = new_secret(CODE_PREFIX)
        code_data = {
            "client_id": doc["client_id"],
            "subject": str(int(uid)),
            "code_challenge": doc.get("code_challenge"),
            "redirect_uri": redirect_base,
            "redirect_uri_provided_explicitly": doc.get("redirect_uri_provided_explicitly", True),
            "scopes": doc.get("scopes") or ["read"],
            "resource": doc.get("resource"),
        }
        await anyio.to_thread.run_sync(lambda: store.save_code(code, code_data))
        await anyio.to_thread.run_sync(store.delete_txn, txn)
        uri = construct_redirect_uri(redirect_base, code=code, state=state)
        return RedirectResponse(uri, status_code=302)

    return [
        Route("/oauth/consent", consent_get, methods=["GET"]),
        Route("/oauth/consent", consent_post, methods=["POST"]),
    ]

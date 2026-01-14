// NOTE:
// Cloudflare Workers do not fully support Node's `https.request` even with nodejs_compat.
// The `web-push` package relies on that API, which causes runtime errors like:
// "[unenv] https.request is not implemented yet!"
//
// לכן ב-Worker הזה אנחנו מעדיפים מצב Proxy: להעביר את הבקשה לשירות Node (push_worker)
// שמבצע את ה-web-push בפועל. זה גם מאפשר לוגים/סטטוסים אמינים.

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const method = request.method.toUpperCase();

    // Health check endpoint (used by /status_worker)
    if (url.pathname === "/healthz") {
      if (method !== "GET") {
        return json({ ok: false, status: 405, error: "method_not_allowed" }, 405, { Allow: "GET" });
      }
      return json({ ok: true }, 200);
    }

    // Only /send is supported for delivery
    if (url.pathname !== "/send") {
      return json({ ok: false, status: 404, error: "not_found" }, 404);
    }
    if (method !== "POST") {
      return json({ ok: false, status: 405, error: "method_not_allowed" }, 405, { Allow: "POST" });
    }

    // Auth check: Bearer token
    const auth = request.headers.get("authorization") || "";
    const expected = env.PUSH_DELIVERY_TOKEN ? `Bearer ${env.PUSH_DELIVERY_TOKEN}` : null;
    if (!expected || auth !== expected) {
      return json({ ok: false, status: 401, error: "unauthorized" }, 200);
    }

    let body;
    try {
      body = await request.json();
    } catch (e) {
      return json({ ok: false, status: 400, error: "invalid_json" }, 200);
    }

    const { subscription, payload, options } = body || {};
    if (!subscription || !payload) {
      return json({ ok: false, status: 400, error: "missing_fields" }, 200);
    }

    // Log endpoint hash
    const endpointHash = await hashEndpoint(subscription.endpoint || "");

    try {
      // Proxy mode: forward to Node push worker
      const forwardUrlRaw = (env.FORWARD_URL || "").trim();
      if (!forwardUrlRaw) {
        console.error("push_error", {
          endpoint_hash: endpointHash,
          status: 500,
          error: "missing_forward_url",
        });
        return json({ ok: false, status: 500, error: "worker_misconfigured", details: "FORWARD_URL missing" }, 502);
      }

      const forwardUrl = forwardUrlRaw.endsWith("/send") ? forwardUrlRaw : forwardUrlRaw.replace(/\/+$/, "") + "/send";
      const forwardToken = (env.FORWARD_TOKEN || env.PUSH_DELIVERY_TOKEN || "").trim();
      const headers = {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${forwardToken}`,
      };
      const idempotencyKey = request.headers.get("X-Idempotency-Key");
      if (idempotencyKey) headers["X-Idempotency-Key"] = idempotencyKey;

      console.log(JSON.stringify({
        event: "push_send_proxy",
        provider: "forward_url",
        endpoint_hash: endpointHash,
        forward_host: (() => { try { return new URL(forwardUrl).host; } catch (_) { return ""; } })(),
      }));

      const r = await fetch(forwardUrl, {
        method: "POST",
        headers,
        body: JSON.stringify({ subscription, payload, options }),
      });

      let outJson = null;
      try {
        outJson = await r.json();
      } catch (_) {
        outJson = null;
      }
      if (!r.ok) {
        console.error("push_error", {
          endpoint_hash: endpointHash,
          status: r.status,
          error: "forward_non_2xx",
        });
        return json({ ok: false, status: r.status, error: "forward_non_2xx" }, 200);
      }
      // Expect push_worker schema: { ok: true } or { ok:false, status, error, ... }
      if (outJson && typeof outJson === "object" && outJson.ok === false) {
        return json(outJson, 200);
      }
      return json(outJson && typeof outJson === "object" ? outJson : { ok: true }, 200);

    } catch (err) {
      const status = err.statusCode || 500;
      const errorBody = err.body || err.message;
      
      console.error("push_error", { 
        endpoint_hash: endpointHash, 
        status, 
        error: errorBody 
      });

      // Map WebPush errors to our API schema
      // 404/410/403/401 are "known failures" that the server should handle (e.g. remove sub)
      if (status >= 400 && status < 500) {
        return json({ 
          ok: false, 
          status: status, 
          error: "upstream_error", 
          details: errorBody 
        }, 200);
      }

      // 5xx or network errors
      return json({ 
        ok: false, 
        status: status, 
        error: "worker_send_failed" 
      }, 502);
    }
  },
};

function json(obj, status = 200, headers = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...headers,
    },
  });
}

async function hashEndpoint(endpoint) {
  if (!endpoint) return "";
  const enc = new TextEncoder();
  const data = enc.encode(endpoint);
  const digest = await crypto.subtle.digest("SHA-256", data);
  const bytes = new Uint8Array(digest);
  return [...bytes].slice(0, 16).map((b) => b.toString(16).padStart(2, "0")).join("");
}

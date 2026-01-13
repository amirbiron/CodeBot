import webpush from 'web-push';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const method = request.method.toUpperCase();

    // Default to 404 for unknown paths
    if (url.pathname !== "/send") {
      return json({ ok: false, status: 404, error: "not_found" }, 404);
    }
    if (method !== "POST") {
      return json({ ok: false, status: 405, error: "method_not_allowed" }, 405, {
        Allow: "POST",
      });
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

    // Validate VAPID config
    if (!env.WORKER_VAPID_PUBLIC_KEY || !env.WORKER_VAPID_PRIVATE_KEY) {
      console.error("Missing VAPID keys in Worker environment");
      return json({ ok: false, status: 500, error: "worker_misconfigured" }, 502);
    }

    // Set VAPID details globally for the library instance
    // Note: In Cloudflare Workers, env is only available in the handler, so we must set it here.
    let subject = env.WORKER_VAPID_SUB_EMAIL || 'mailto:support@example.com';
    if (!subject.startsWith('mailto:')) {
      subject = `mailto:${subject}`;
    }

    try {
      webpush.setVapidDetails(
        subject,
        env.WORKER_VAPID_PUBLIC_KEY,
        env.WORKER_VAPID_PRIVATE_KEY
      );
    } catch (err) {
      console.error("vapid_setup_error", err);
      return json({ ok: false, status: 500, error: "vapid_setup_failed" }, 502);
    }

    // Log endpoint hash
    const endpointHash = await hashEndpoint(subscription.endpoint || "");

    try {
      // Forward headers including Idempotency Key
      const sendHeaders = options?.headers || {};
      const idempotencyKey = request.headers.get("X-Idempotency-Key");
      if (idempotencyKey) {
        sendHeaders["X-Idempotency-Key"] = idempotencyKey;
      }

      // Send the notification
      const resp = await webpush.sendNotification(
        subscription,
        JSON.stringify(payload),
        {
          TTL: options?.ttl,
          headers: sendHeaders,
          contentEncoding: options?.contentEncoding || 'aes128gcm',
          urgency: options?.urgency
        }
      );

      // IMPORTANT: In some runtimes, non-2xx responses may not throw.
      // Treat non-2xx as failure and propagate back to server for cleanup/diagnosis.
      try {
        const st =
          (resp && typeof resp.statusCode === "number" ? resp.statusCode : 0) ||
          (resp && typeof resp.status === "number" ? resp.status : 0) ||
          0;
        if (st && (st < 200 || st >= 300)) {
          let details = "";
          try {
            // web-push (Node) returns { statusCode, body, headers }.
            // In some runtimes it may return a fetch Response-like object.
            if (resp && typeof resp.body === "string") {
              details = resp.body || "";
            } else if (resp && typeof resp.text === "function") {
              details = (await resp.text()) || "";
            } else {
              details = "";
            }
          } catch (_) {
            details = "";
          }
          console.error("push_error", {
            endpoint_hash: endpointHash,
            status: st,
            error: details ? details.slice(0, 300) : "non_2xx",
          });
          return json(
            {
              ok: false,
              status: st,
              error: "upstream_error",
              details: details ? details.slice(0, 300) : "",
            },
            200
          );
        }
      } catch (_) {}

      console.log(JSON.stringify({ 
        event: "push_sent", 
        endpoint_hash: endpointHash,
        status:
          (resp && typeof resp.statusCode === "number" ? resp.statusCode : 0) ||
          (resp && typeof resp.status === "number" ? resp.status : 0) ||
          201
      }));

      return json({ ok: true });

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

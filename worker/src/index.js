export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const method = request.method.toUpperCase();

    // ברירת מחדל ל-404
    if (url.pathname !== "/send") {
      return json({ ok: false, status: 404, error: "not_found" }, 404);
    }
    if (method !== "POST") {
      return json({ ok: false, status: 405, error: "method_not_allowed" }, 405, {
        Allow: "POST",
      });
    }

    // אימות Bearer מול סוד ב-Worker
    const auth = request.headers.get("authorization") || "";
    const expected = env.PUSH_DELIVERY_TOKEN ? `Bearer ${env.PUSH_DELIVERY_TOKEN}` : null;
    if (!expected || auth !== expected) {
      // לפי הסכמה: כשל ידוע יכול להיות 200 עם ok=false וסטטוס לוגי
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

    // אנונימיזציה של endpoint ללוגים בלבד
    const endpointHash = await hashEndpoint(subscription?.endpoint || "");

    // אם הוגדר יעד פרוקסי (Node Worker אמיתי) – נבצע שליחה דרך fetch
    const base = (env.FORWARD_URL || "").trim().replace(/\/$/, "");
    if (base) {
      const forwardUrl = `${base}/send`;
      const controller = new AbortController();
      const timeoutMs = Number(env.FORWARD_TIMEOUT_MS || 3000);
      const t = setTimeout(() => controller.abort("timeout"), Math.max(500, timeoutMs));
      try {
        const authHeader = env.FORWARD_TOKEN
          ? `Bearer ${env.FORWARD_TOKEN}`
          : (env.PUSH_DELIVERY_TOKEN ? `Bearer ${env.PUSH_DELIVERY_TOKEN}` : "");
        const resp = await fetch(forwardUrl, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            ...(authHeader ? { authorization: authHeader } : {}),
            // שמירת Idempotency אם נשלח מהשרת
            "X-Idempotency-Key": request.headers.get("X-Idempotency-Key") || "",
          },
          body: JSON.stringify({ subscription, payload, options }),
          signal: controller.signal,
        });
        clearTimeout(t);

        const status = resp.status;
        // Worker ה-Node מחזיר 200 עם ok:true/false למצבים ידועים; 5xx לשגיאות פנימיות
        if (status >= 500) {
          console.error("proxy_worker_5xx", { endpoint_hash: endpointHash, status });
          return json({ ok: false, error: "worker_5xx", status }, 502);
        }
        let bodyJson = {};
        try { bodyJson = await resp.json(); } catch (_) { bodyJson = {}; }
        if (typeof bodyJson === "object" && bodyJson && ("ok" in bodyJson)) {
          // החזר ישיר לשימור הסכמה
          return json(bodyJson, 200);
        }
        return json({ ok: false, error: "invalid_worker_response", status }, 200);
      } catch (e) {
        console.error("proxy_worker_error", { endpoint_hash: endpointHash, msg: String(e && e.message || e) });
        return json({ ok: false, error: "worker_timeout", status: 0 }, 200);
      }
    }

    // Fallback: מצב Stub (ללא שליחה אמיתית)
    console.log(JSON.stringify({ event: "push_send_stub", provider: "cloudflare_worker", endpoint_hash: endpointHash }));
    return json({ ok: true });
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
  const enc = new TextEncoder();
  const data = enc.encode(endpoint);
  const digest = await crypto.subtle.digest("SHA-256", data);
  const bytes = new Uint8Array(digest);
  // הקצרה לצורכי לוג בלבד
  return [...bytes].slice(0, 16).map((b) => b.toString(16).padStart(2, "0")).join("");
}

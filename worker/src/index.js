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

    // TODO: מימוש שליחה אמיתית (web-push) יתווסף בהמשך.
    // כרגע מחזיר הצלחה כדי לאפשר אינטגרציה ראשונית.
    // שים לב: אין לוג של subscription.keys.
    console.log(JSON.stringify({
      event: "push_send_stub",
      provider: "cloudflare_worker",
      endpoint_hash: endpointHash,
    }));

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

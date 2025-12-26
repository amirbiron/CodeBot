"use strict";

const express = require("express");
const crypto = require("crypto");
const webPush = require("web-push");

const PORT = process.env.PORT ? Number(process.env.PORT) : 8080;
const PUSH_DELIVERY_TOKEN = (process.env.PUSH_DELIVERY_TOKEN || "").trim();
// Prefer worker-specific env so שהמפתח הפרטי לא ייחשף ל-Flask
const VAPID_PUBLIC_KEY = (process.env.WORKER_VAPID_PUBLIC_KEY || process.env.VAPID_PUBLIC_KEY || "").trim();
const VAPID_PRIVATE_KEY = (process.env.WORKER_VAPID_PRIVATE_KEY || process.env.VAPID_PRIVATE_KEY || "").trim();
const VAPID_SUB_EMAIL = (process.env.WORKER_VAPID_SUB_EMAIL || process.env.VAPID_SUB_EMAIL || "support@example.com").trim();

if (VAPID_PUBLIC_KEY && VAPID_PRIVATE_KEY) {
  try {
    const subject = VAPID_SUB_EMAIL.startsWith("mailto:") ? VAPID_SUB_EMAIL : `mailto:${VAPID_SUB_EMAIL}`;
    webPush.setVapidDetails(subject, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY);
  } catch (e) {
    console.warn("Failed to set VAPID details on startup:", e && e.message);
  }
} else {
  console.warn("VAPID keys are missing. POST /send will fail until configured.");
}

const app = express();
app.use(express.json({ limit: "8kb" }));

app.get("/healthz", (_req, res) => {
  res.status(200).json({ ok: true });
});

function bearerOk(req) {
  try {
    const h = req.headers["authorization"] || req.headers["Authorization"];
    if (!PUSH_DELIVERY_TOKEN) return false;
    if (typeof h !== "string") return false;
    const parts = h.split(/\s+/);
    if (parts.length !== 2) return false;
    const [scheme, token] = parts;
    if (!/^Bearer$/i.test(scheme)) return false;
    // Constant-time comparison via hash to avoid length mismatch exceptions
    const ah = crypto.createHash("sha256").update(String(token || ""), "utf8").digest();
    const bh = crypto.createHash("sha256").update(String(PUSH_DELIVERY_TOKEN || ""), "utf8").digest();
    try {
      return crypto.timingSafeEqual(ah, bh);
    } catch (_) {
      return false;
    }
  } catch (_) {
    return false;
  }
}

function hashEndpoint(ep) {
  try {
    return crypto.createHash("sha256").update(String(ep || "")).digest("hex").slice(0, 12);
  } catch (_) {
    return "";
  }
}

app.post("/send", async (req, res) => {
  const start = Date.now();
  const endpoint = (req.body && req.body.subscription && req.body.subscription.endpoint) || "";
  const endpointHash = hashEndpoint(endpoint);
  const idempotencyKey = req.header("X-Idempotency-Key") || "";

  if (!bearerOk(req)) {
    console.warn("unauthorized", { endpoint_hash: endpointHash });
    return res.status(401).json({ ok: false, status: 401, error: "unauthorized" });
  }

  const sub = (req.body && req.body.subscription) || null;
  const payload = (req.body && req.body.payload) || null;
  const options = (req.body && req.body.options) || {};

  if (!sub || typeof sub !== "object" || !payload) {
    return res.status(400).json({ ok: false, status: 400, error: "invalid_request" });
  }

  const ttl = typeof options.ttl === "number" ? options.ttl : undefined;
  const urgency = typeof options.urgency === "string" ? options.urgency : undefined;
  const contentEncoding = typeof options.contentEncoding === "string" ? options.contentEncoding : undefined;

  try {
    if (!VAPID_PUBLIC_KEY || !VAPID_PRIVATE_KEY) {
      return res.status(500).json({ ok: false, error: "missing_vapid_keys" });
    }
    const wpOpts = {};
    if (ttl != null) wpOpts.TTL = ttl;
    if (urgency) wpOpts.urgency = urgency;
    if (contentEncoding) wpOpts.contentEncoding = contentEncoding;
    // Pass idempotency as header for visibility (upstream services ignore it).
    wpOpts.headers = { "X-Idempotency-Key": String(idempotencyKey || "") };

    await webPush.sendNotification(sub, JSON.stringify(payload), wpOpts);

    const ms = Date.now() - start;
    console.log("delivered", { endpoint_hash: endpointHash, ms });
    return res.status(200).json({ ok: true });
  } catch (e) {
    const code = (e && (e.statusCode || (e.response && e.response.statusCode))) || 0;
    const msg = (e && e.message) || "send_failed";
    const ms = Date.now() - start;
    if (code === 404 || code === 410 || code === 401 || code === 403) {
      console.warn("known_error", { endpoint_hash: endpointHash, status: code, ms, error: String(msg) });
      return res.status(200).json({ ok: false, status: Number(code), error: String(msg) });
    }
    console.error("worker_error", { endpoint_hash: endpointHash, status: code || 0, ms, msg: String(msg) });
    return res.status(502).json({ ok: false, error: String(msg), status: Number(code || 0) });
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`push-delivery-worker listening on :${PORT}`);
});

"""ה-Service Worker: דחייה שהשרת סירב לה אינה נראית כמו דחייה שהתקבלה.

``sw.js`` נטען כמו שהוא לתוך עמוד ב-Chromium עם דמה של ``registration``,
``clients`` ו-``fetch``, ואירוע ``notificationclick`` סינתטי מופעל — כלומר
ה-handler האמיתי רץ. לפני התיקון 404 לדחייה (תזכורת שכבר אושרה) נבלע:
``.catch`` אינו רואה תשובה שנפתרה, שום דיווח לא יצא, ולמשתמש לא היה
סימן שהדחייה לא התקבלה — וההתראה שנשאה את הכפתור כבר נסגרה.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright אינו מותקן")

from playwright.sync_api import sync_playwright  # noqa: E402

SW_SOURCE = Path(__file__).resolve().parent.parent / "webapp" / "static" / "sw.js"

#: מה שה-handler משווה כדי להבחין בין דחייה שהתקבלה לסירוב; המוטציה מוחקת אותו.
OUTCOME_FROM_RESPONSE = "outcome = resp.ok ? 'success' : 'refused';"

HARNESS = """
window.__reports = []; window.__shown = []; window.__fetches = []; window.__opened = null;
self.registration = {
  showNotification: (title, options) => {
    window.__shown.push({ title: title, options: options }); return Promise.resolve();
  },
  pushManager: { getSubscription: () => Promise.resolve(null) },
};
window.clients = {
  matchAll: () => Promise.resolve([]),
  openWindow: (u) => { window.__opened = String(u); return Promise.resolve(null); },
  claim: () => Promise.resolve(),
};
self.skipWaiting = () => Promise.resolve();
window.fetch = async (url, opts) => {
  const u = String(url);
  window.__fetches.push({ url: u, body: (opts && opts.body) ? String(opts.body) : '' });
  if (u.indexOf('/api/push/sw-report') !== -1) {
    try { window.__reports.push(JSON.parse(opts.body)); } catch (_) {}
    return { ok: true, status: 200 };
  }
  if (u.indexOf('/snooze') !== -1) {
    if (window.__snoozeMode === 'reject') { throw new TypeError('Failed to fetch'); }
    const st = window.__snoozeStatus || 200;
    return { ok: st < 400, status: st, json: async () => ({ ok: st < 400 }) };
  }
  return { ok: true, status: 200, json: async () => ({ ok: true }) };
};
"""

CLICK = """
() => {
  const ev = new Event('notificationclick');
  ev.notification = { data: { note_id: 'n1', file_id: 'f1' }, close: () => {} };
  ev.action = window.__action || 'snooze_60';
  ev.waitUntil = (p) => { window.__done = Promise.resolve(p).catch(() => {}); };
  window.dispatchEvent(ev);
  return window.__done;
}
"""


def _sw_source() -> str:
    return SW_SOURCE.read_text(encoding="utf-8")


def _mutate(script: str, anchor: str, replacement: str) -> str:
    assert script.count(anchor) == 1, f"העוגן נמצא {script.count(anchor)} פעמים: {anchor!r}"
    mutated = script.replace(anchor, replacement)
    assert mutated != script
    return mutated


@contextmanager
def _worker(chromium_executable, source: str, **window_vars):
    with sync_playwright() as p:
        browser = (
            p.chromium.launch(executable_path=chromium_executable) if chromium_executable else p.chromium.launch()
        )
        try:
            page = browser.new_page()
            page.set_content("<!doctype html><html><body></body></html>")
            page.evaluate(HARNESS)
            page.evaluate(f"Object.assign(window, {json.dumps(window_vars)});")
            page.add_script_tag(content=source)
            yield page
        finally:
            browser.close()


def _click(page):
    page.evaluate(CLICK)
    page.wait_for_timeout(200)
    return {
        "reports": [r for r in page.evaluate("window.__reports") if r.get("event") == "snooze"],
        "shown": page.evaluate("window.__shown"),
        "opened": page.evaluate("window.__opened"),
        "snooze_bodies": [f["body"] for f in page.evaluate("window.__fetches") if "/snooze" in f["url"]],
    }


def test_a_refused_snooze_is_reported_and_shown(chromium_executable):
    """404 לדחייה: דיווח ``snooze/refused`` עם קוד התשובה, והתראה שאומרת שהדחייה לא התקבלה."""
    with _worker(chromium_executable, _sw_source(), __snoozeStatus=404, __action="snooze_60") as page:
        out = _click(page)
    assert out["snooze_bodies"] == ['{"minutes":60}'], out["snooze_bodies"]
    assert [(r["status"], r.get("http_status")) for r in out["reports"]] == [("refused", 404)], out["reports"]
    assert len(out["shown"]) == 1, out["shown"]
    assert out["shown"][0]["title"] == "הדחייה לא התקבלה"
    assert out["shown"][0]["options"]["data"]["note_id"] == "n1"
    assert out["opened"] is None, "snooze_60 אינו פותח את הפתק"


def test_an_accepted_snooze_is_reported_and_stays_quiet(chromium_executable):
    """200: דיווח ``snooze/success`` — כדי שהקצב יימדד — ובלי התראה נוספת."""
    with _worker(chromium_executable, _sw_source(), __snoozeStatus=200) as page:
        out = _click(page)
    assert [r["status"] for r in out["reports"]] == ["success"], out["reports"]
    assert out["shown"] == [], out["shown"]


def test_a_network_error_on_snooze_is_reported_and_shown(chromium_executable):
    """שגיאת רשת: דיווח ``snooze/error`` עם הסיבה, והתראה — כי גם כאן הדחייה לא נקבעה."""
    with _worker(chromium_executable, _sw_source(), __snoozeMode="reject") as page:
        out = _click(page)
    assert [r["status"] for r in out["reports"]] == ["error"], out["reports"]
    assert "Failed to fetch" in out["reports"][0].get("error", "")
    assert len(out["shown"]) == 1 and out["shown"][0]["title"] == "הדחייה לא התקבלה", out["shown"]


def test_ignoring_the_response_breaks_the_test(chromium_executable):
    """ריצת בקרה: ``resp.ok`` לא נקרא — 404 מדווח כהצלחה ואין התראה."""
    source = _mutate(_sw_source(), OUTCOME_FROM_RESPONSE, "outcome = 'success';")
    with _worker(chromium_executable, source, __snoozeStatus=404) as page:
        out = _click(page)
    assert [r["status"] for r in out["reports"]] == ["success"], out["reports"]
    assert out["shown"] == []

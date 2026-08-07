// Web Push bindings for /settings (kept isolated and resilient)
// - Avoids reliance on other settings scripts
// - Uses updateViaCache:'none' to reduce SW caching issues
(function () {
  'use strict';

  try { window.__ckPushSettingsLoaded = true; } catch (_) {}

  function el(id) { return document.getElementById(id); }
  function setStatus(text) {
    var s = el('pushStatus');
    if (s) s.textContent = String(text || '');
  }

  function urlBase64ToUint8Array(base64String) {
    var padding = Array((4 - (base64String.length % 4)) % 4 + 1).join('=');
    var base64 = String(base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    var rawData = window.atob(base64);
    var outputArray = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
    return outputArray;
  }

  function registerSw() {
    if (!('serviceWorker' in navigator)) return Promise.reject(new Error('ServiceWorker לא נתמך'));
    // updateViaCache:'none' helps Chrome fetch the latest /sw.js
    return navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' })
      .then(function (reg) {
        try { reg && reg.update && reg.update().catch(function () { }); } catch (_) { }
        try {
          return navigator.serviceWorker.ready
            .then(function () { return reg; })
            .catch(function () { return reg; });
        } catch (_) {
          return reg;
        }
      });
  }

  function getReg() {
    if (!('serviceWorker' in navigator)) return Promise.reject(new Error('ServiceWorker לא נתמך'));
    return navigator.serviceWorker.getRegistration()
      .then(function (reg) { return reg || registerSw(); })
      .catch(function () { return registerSw(); });
  }

  function getVapid() {
    return fetch('/api/push/public-key', { cache: 'no-store', credentials: 'include' })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (j) {
        if (!j || j.ok === false || !j.vapidPublicKey) throw new Error('מפתח VAPID לא זמין');
        return j.vapidPublicKey;
      });
  }

  // משווה את מפתח ה-VAPID של מנוי קיים למפתח שהשרת מחזיר עכשיו.
  // מחזיר true/false, או null כשאי אפשר להשוות (דפדפן שלא חושף options).
  function sameApplicationServerKey(sub, keyBytes) {
    try {
      var existing = sub && sub.options && sub.options.applicationServerKey;
      if (!existing) return null;
      var a = new Uint8Array(existing);
      if (a.length !== keyBytes.length) return false;
      for (var i = 0; i < a.length; i++) {
        if (a[i] !== keyBytes[i]) return false;
      }
      return true;
    } catch (_) {
      return null;
    }
  }

  function saveSubscription(sub) {
    return fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(sub),
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (j) {
        if (!resp.ok || !j || j.ok === false) throw new Error('שמירת מנוי נכשלה');
        return j;
      });
    });
  }

  // כשכבר קיים מנוי עם מפתח אחר, הדפדפן זורק InvalidStateError.
  // במקרה כזה מבטלים את הישן ומנסים שוב — פעם אחת בלבד.
  function subscribeWithRecovery(reg, keyBytes, retried) {
    return reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes,
    }).catch(function (e) {
      if (!retried && e && e.name === 'InvalidStateError') {
        setStatus('נמצא מנוי ישן, מחדש...');
        return reg.pushManager.getSubscription().then(function (old) {
          return old ? old.unsubscribe().catch(function () { }) : null;
        }).then(function () {
          return subscribeWithRecovery(reg, keyBytes, true);
        });
      }
      throw e;
    });
  }

  function enablePush() {
    setStatus('טוען...');
    try {
      if (!('Notification' in window)) { setStatus('התראות לא נתמכות בדפדפן'); return; }
      if (!('serviceWorker' in navigator)) { setStatus('ServiceWorker לא נתמך'); return; }
      if (!('PushManager' in window)) { setStatus('PushManager לא נתמך'); return; }
    } catch (_) { }

    var reg = null;
    var keyBytes = null;

    getReg().then(function (r) {
      reg = r;
      return getVapid();
    }).then(function (key) {
      keyBytes = urlBase64ToUint8Array(key);
      return reg.pushManager.getSubscription();
    }).then(function (existing) {
      if (!existing) return null;
      // אם השרת החליף מפתח VAPID, המנוי הישן מת: הדפדפן עדיין מחזיק אותו,
      // אבל ה-push service ידחה כל שליחה אליו. מבטלים ונרשמים מחדש
      // במקום לדווח "ההתראות כבר מופעלות" על מנוי שלא יעבוד לעולם.
      if (sameApplicationServerKey(existing, keyBytes) === false) {
        setStatus('מפתח ההתראות התחלף, מחדש מנוי...');
        return existing.unsubscribe().catch(function () { }).then(function () { return null; });
      }
      return saveSubscription(existing).then(function () {
        setStatus('ההתראות כבר מופעלות');
        refreshUi();
        return 'done';
      });
    }).then(function (state) {
      if (state === 'done') return;
      return Notification.requestPermission().then(function (perm) {
        if (perm !== 'granted') { setStatus('הרשאת התראות נדחתה'); return; }
        setStatus('יוצר מנוי...');
        return subscribeWithRecovery(reg, keyBytes, false).then(function (sub) {
          return saveSubscription(sub).then(function () {
            setStatus('התראות הופעלו בהצלחה');
            refreshUi();
          });
        });
      });
    }).catch(function (e) {
      // מציגים את השגיאה עצמה. בלי זה מוצג "שגיאה" גנרית וצריך DevTools
      // כדי להבין מה קרה — לא זמין בטאבלט/מובייל.
      var detail = '';
      try {
        detail = (e && e.name ? e.name + ': ' : '') + ((e && e.message) || String(e || ''));
      } catch (_) { detail = ''; }
      setStatus('שגיאה בהפעלת התראות — ' + (detail || 'לא ידוע'));
      try { console.warn('push enable failed', e); } catch (_) { }
    });
  }

  function disablePush() {
    setStatus('מכבה התראות...');
    if (!('serviceWorker' in navigator)) { setStatus('הדפדפן לא תומך בהתראות'); return; }
    getReg().then(function (reg) {
      return reg.pushManager.getSubscription().then(function (sub) {
        if (!sub) { setStatus('ההתראות כבר כבויות'); refreshUi(); return; }
        try {
          var ep = (sub && typeof sub.endpoint === 'string') ? sub.endpoint : '';
          if (ep) {
            fetch('/api/push/subscribe', {
              method: 'DELETE',
              headers: { 'Content-Type': 'application/json' },
              credentials: 'include',
              body: JSON.stringify({ endpoint: ep }),
            }).catch(function () { });
          }
        } catch (_) { }
        return sub.unsubscribe().catch(function () { }).then(function () {
          setStatus('התראות כובו');
          refreshUi();
        });
      });
    }).catch(function (e) {
      setStatus('שגיאה בכיבוי התראות');
      try { console.warn('push disable failed', e); } catch (_) { }
    });
  }

  function testPush() {
    setStatus('שולח פוש בדיקה...');
    fetch('/api/push/test', { method: 'POST', credentials: 'include' })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { r: r, j: j }; }); })
      .then(function (out) {
        if (out.r && out.r.ok && out.j && out.j.ok) {
          if ((out.j.sent || 0) > 0) { setStatus('נשלחה התראת בדיקה'); return; }
          setStatus('לא נשלחה התראה (בדוק מפתח VAPID/מנויים)');
          return;
        }
        if (out.j && out.j.error === 'no_subscriptions') setStatus('אין מנוי פוש לשלח אליו — הפעל התראות');
        else if (out.j && out.j.error === 'missing_vapid_private_key') setStatus('חסר VAPID_PRIVATE_KEY בשרת');
        else if (out.j && out.j.error === 'pywebpush_not_available') setStatus('שרת: pywebpush לא מותקן/זמין');
        else if (out.j && out.j.error === 'internal_error') setStatus('שגיאה פנימית בשרת');
        else setStatus('בדיקת פוש נכשלה');
      })
      .catch(function (e) {
        setStatus('בדיקת פוש נכשלה');
        try { console.warn('push test failed', e); } catch (_) { }
      });
  }

  function refreshUi() {
    try {
      if (!('Notification' in window)) { setStatus('הדפדפן לא תומך בהתראות'); return; }
      var st = Notification.permission;
      getReg().then(function (reg) {
        return reg.pushManager.getSubscription().then(function (sub) {
          var hasSub = !!sub;
          if (st === 'granted' && hasSub) setStatus('התראות מופעלות בדפדפן זה');
          else if (st === 'denied') setStatus('המשתמש חסם התראות – יש לאפשר ידנית');
          else setStatus('נדרש להפעיל התראות');
        });
      }).catch(function () {
        if (st === 'denied') setStatus('המשתמש חסם התראות – יש לאפשר ידנית');
        else setStatus('נדרש להפעיל התראות');
      });
    } catch (_) {
      setStatus('מצב לא ידוע');
    }
  }

  function bind() {
    try {
      // Expose to inline handlers too (backward compatible)
      window.__ckPushEnable = enablePush;
      window.__ckPushDisable = disablePush;
      window.__ckPushTest = testPush;
    } catch (_) { }

    var en = el('pushEnableBtn');
    if (en) en.addEventListener('click', function (e) { try { e.preventDefault(); } catch (_) { } enablePush(); });
    var dis = el('pushDisableBtn');
    if (dis) dis.addEventListener('click', function (e) { try { e.preventDefault(); } catch (_) { } disablePush(); });
    var t = el('pushTestBtn');
    if (t) t.addEventListener('click', function (e) { try { e.preventDefault(); } catch (_) { } testPush(); });

    setStatus('טוען מצב התראות...');
    refreshUi();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bind, { once: true });
  } else {
    bind();
  }
})();


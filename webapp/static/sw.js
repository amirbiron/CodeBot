// SW Version for cache busting
const SW_VERSION = '2.3.0';

self.addEventListener('install', (event) => {
  console.log('[SW] Installing version:', SW_VERSION);
  // Skip waiting so the new SW takes control ASAP
  try { self.skipWaiting(); } catch (_) {}
});

self.addEventListener('activate', (event) => {
  console.log('[SW] Activating version:', SW_VERSION);
  // Claim clients without reload
  event.waitUntil((async () => {
    try { await self.clients.claim(); } catch (_) {}
  })());
});

self.addEventListener('message', (event) => {
  try {
    const msg = event && event.data ? event.data : null;
    if (!msg || msg.type !== 'ck_debug_ping') return;
    const endpointHash = (msg.endpoint_hash && String(msg.endpoint_hash)) || '';
    event.waitUntil(
      Promise.resolve()
        .then(() => reportToServer('debug_ping', 'received', { endpoint_hash: endpointHash || '' }))
        .catch((e) => {
          try {
            return reportToServer('debug_ping', 'error', { error: String(e) });
          } catch (_) {
            return Promise.resolve();
          }
        })
    );
  } catch (e) {
    try {
      event.waitUntil(reportToServer('debug_ping', 'error', { error: String(e) }));
    } catch (_) {}
  }
});

// Helper: report SW events back to server for debugging (no auth needed)
// This is CRITICAL for debugging - sends a POST to /api/push/sw-report
let __endpointHashPromise = null;
function _sha256Hex12(str) {
  try {
    if (!str || !self.crypto || !self.crypto.subtle || !self.TextEncoder) return Promise.resolve('');
    const data = new TextEncoder().encode(String(str));
    return crypto.subtle.digest('SHA-256', data).then((buf) => {
      const bytes = new Uint8Array(buf);
      let hex = '';
      for (let i = 0; i < bytes.length; i++) {
        const h = bytes[i].toString(16).padStart(2, '0');
        hex += h;
      }
      return hex.slice(0, 12);
    }).catch(() => '');
  } catch (_) {
    return Promise.resolve('');
  }
}

function getEndpointHash() {
  try {
    if (__endpointHashPromise) return __endpointHashPromise;
    if (!self.registration || !self.registration.pushManager) {
      __endpointHashPromise = Promise.resolve('');
      return __endpointHashPromise;
    }
    __endpointHashPromise = self.registration.pushManager.getSubscription()
      .then((sub) => {
        const ep = sub && sub.endpoint ? String(sub.endpoint) : '';
        return _sha256Hex12(ep);
      })
      .catch(() => '');
    return __endpointHashPromise;
  } catch (_) {
    return Promise.resolve('');
  }
}

function reportToServer(eventType, status, extra = {}) {
  console.log('[SW] Reporting to server:', eventType, status, extra);
  try {
    return getEndpointHash().then((endpointHash) => {
      const body = JSON.stringify({
        event: eventType,
        status: status,
        timestamp: new Date().toISOString(),
        sw_version: SW_VERSION,
        endpoint_hash: endpointHash || '',
        ...extra
      });
      return fetch('/api/push/sw-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body,
        keepalive: true
      }).then(resp => {
        console.log('[SW] Report sent, status:', resp.status);
      }).catch(err => {
        console.error('[SW] Report failed:', err);
      });
    }).catch(() => {});
  } catch (e) {
    console.error('[SW] reportToServer exception:', e);
    return Promise.resolve();
  }
}

self.addEventListener('push', (event) => {
  // CRITICAL: Call event.waitUntil IMMEDIATELY at the start
  // All logic must be inside this promise to keep SW alive
  event.waitUntil((async () => {
    const receivedAt = new Date().toISOString();
    let rawData = null;
    let parsedJson = null;
    
    try {
      // STEP 1: Log that we received a push
      console.log('========================================');
      console.log('[SW] PUSH EVENT RECEIVED at:', receivedAt);
      console.log('[SW] SW Version:', SW_VERSION);
      console.log('[SW] event.data exists:', !!event.data);
      console.log('========================================');
      
      // STEP 2: Send immediate report to server (await for reliability)
      try {
        await reportToServer('push_received', 'started', { received_at: receivedAt });
      } catch (_) {}
      
      // STEP 3: Extract and parse the push data
      console.log('[SW] Step 3: Extracting push data...');
      
      if (event.data) {
        try {
          // Use try-catch specifically for text() which can fail
          try {
            rawData = event.data.text();
          } catch (textErr) {
            console.error('[SW] event.data.text() failed:', textErr);
            // Try alternative methods
            try {
              rawData = await event.data.json();
              rawData = JSON.stringify(rawData);
            } catch (jsonErr) {
              console.error('[SW] event.data.json() also failed:', jsonErr);
              rawData = null;
            }
          }
          
          console.log('[SW] Raw push data received, length:', rawData ? rawData.length : 0);
          console.log('[SW] Raw data content:', rawData);
          
          if (rawData) {
            parsedJson = JSON.parse(rawData);
          } else {
            parsedJson = {};
          }
          console.log('[SW] Successfully parsed JSON');
          console.log('[SW] Parsed structure:', JSON.stringify(parsedJson, null, 2));
          
          reportToServer('push_parsed', 'success', { 
            raw_data: rawData || '(no data)',
            has_notification: !!(parsedJson && parsedJson.notification),
            has_data: !!(parsedJson && parsedJson.data),
            has_title: !!(parsedJson && (parsedJson.title || (parsedJson.notification && parsedJson.notification.title)))
          });
        } catch (parseErr) {
          console.error('[SW] JSON parse error:', parseErr);
          console.error('[SW] Raw data that failed to parse:', rawData);
          reportToServer('push_parsed', 'error', { 
            error: String(parseErr), 
            raw_data: rawData || '(null)'
          });
          parsedJson = {};
        }
      } else {
        console.warn('[SW] No event.data present in push event!');
        reportToServer('push_parsed', 'no_data');
        parsedJson = {};
      }
      
      // STEP 4: Extract title and body from payload
      // Priority: notification object (FCM standard) > data object > top-level
      console.log('[SW] Step 4: Extracting notification content...');
      
      let title = '🔔 יש פתק ממתין';  // default
      let body = '';
      
      // Check notification object first (this is how push_api.py sends it)
      if (parsedJson.notification && typeof parsedJson.notification === 'object') {
        console.log('[SW] Found notification object:', JSON.stringify(parsedJson.notification));
        title = parsedJson.notification.title || title;
        body = parsedJson.notification.body || body;
      }
      // Fallback to data object
      else if (parsedJson.data && typeof parsedJson.data === 'object') {
        console.log('[SW] Using data object for title/body');
        title = parsedJson.data.title || title;
        body = parsedJson.data.body || body;
      }
      // Fallback to top-level
      else if (parsedJson.title) {
        console.log('[SW] Using top-level title/body');
        title = parsedJson.title || title;
        body = parsedJson.body || body;
      }
      
      console.log('[SW] Final title:', title);
      console.log('[SW] Final body:', body);
      
      // STEP 5: Build notification options
      console.log('[SW] Step 5: Building notification options...');
      
      const customData = parsedJson.data || {};
      // Also check notification object for note_id/file_id
      if (parsedJson.notification) {
        if (!customData.note_id && parsedJson.notification.note_id) {
          customData.note_id = parsedJson.notification.note_id;
        }
        if (!customData.file_id && parsedJson.notification.file_id) {
          customData.file_id = parsedJson.notification.file_id;
        }
      }
      
      // Get tag from notification object or generate unique one
      const tag = (parsedJson.notification && parsedJson.notification.tag) || 
                  ('codekeeper-' + Date.now());
      
      const options = {
        body: body,
        icon: (parsedJson.notification && parsedJson.notification.icon) || '/static/icons/app-icon-512.png',
        data: customData,
        requireInteraction: (parsedJson.notification && parsedJson.notification.requireInteraction) || false,
        silent: (parsedJson.notification && parsedJson.notification.silent) || false,
        tag: tag,
        actions: (parsedJson.notification && parsedJson.notification.actions) || [
          { action: 'open_note', title: 'פתח פתק' },
          { action: 'snooze_10', title: 'דחה 10 דק׳' },
          { action: 'snooze_60', title: 'דחה שעה' },
          { action: 'snooze_1440', title: 'דחה 24 שעות' },
        ]
      };

      // Normalize icon URL to absolute (helps some desktop notification daemons)
      try {
        if (options.icon && typeof options.icon === 'string') {
          options.icon = new URL(options.icon, self.location.origin).toString();
        }
      } catch (_) {}
      
      console.log('[SW] Notification options:', JSON.stringify(options));
      
      // STEP 6: Show the notification (wrapped in try-catch)
      console.log('[SW] Step 6: Showing notification...');
      
      if (!self.registration) {
        console.error('[SW] CRITICAL: self.registration is undefined!');
        reportToServer('show_notification', 'error', { error: 'no_registration' });
        throw new Error('No service worker registration available');
      }
      
      try {
        await self.registration.showNotification(title, options);
        console.log('[SW] ✓ showNotification() succeeded!');
        reportToServer('show_notification', 'success', { title: title, tag: tag });
      } catch (showErr) {
        console.error('[SW] showNotification() FAILED:', showErr);
        reportToServer('show_notification', 'error', { 
          error: String(showErr),
          error_name: showErr.name,
          error_message: showErr.message,
          title: title
        });
        throw showErr;  // Re-throw to trigger fallback
      }
      
    } catch (err) {
      // STEP 7: Error handler - NEVER fail silently
      console.error('========================================');
      console.error('[SW] PUSH HANDLER ERROR:', err);
      console.error('[SW] Error name:', err.name);
      console.error('[SW] Error message:', err.message);
      console.error('[SW] Error stack:', err.stack);
      console.error('========================================');
      
      reportToServer('push_handler', 'error', { 
        error: String(err),
        error_name: err.name || 'unknown',
        error_message: err.message || '',
        raw_data: rawData
      });
      
      // STEP 8: Try to show a fallback notification
      console.log('[SW] Step 8: Attempting fallback notification...');
      try {
        if (self.registration) {
          await self.registration.showNotification('🔔 התראה חדשה', {
            body: 'לא הצלחנו לטעון את פרטי ההתראה',
            icon: new URL('/static/icons/app-icon-512.png', self.location.origin).toString(),
            tag: 'codekeeper-fallback-' + Date.now(),
            silent: false,
            requireInteraction: false
          });
          console.log('[SW] ✓ Fallback notification shown successfully');
          reportToServer('fallback_notification', 'success');
        } else {
          console.error('[SW] Cannot show fallback - no registration');
          reportToServer('fallback_notification', 'error', { error: 'no_registration' });
        }
      } catch (fallbackErr) {
        console.error('[SW] Fallback notification ALSO failed:', fallbackErr);
        reportToServer('fallback_notification', 'error', { 
          error: String(fallbackErr),
          error_name: fallbackErr.name,
          error_message: fallbackErr.message
        });
      }
    }
  })());  // Close the IIFE that was passed to event.waitUntil
});

self.addEventListener('notificationclick', (event) => {
  const d = (event.notification && event.notification.data) || {};
  event.notification && event.notification.close && event.notification.close();

  // דיווחים לשרת אינם חוסמים את מה שהמשתמש מחכה לו. ב-Chromium חלון חייב להיפתח תוך
  // ``kWindowInteractionTimeout`` — עשר שניות מהלחיצה, "otherwise the calls will fail"
  // (third_party/blink/renderer/modules/service_worker/wait_until_observer.cc). דיווח
  // שממתינים לו לפני ``openWindow`` — ``fetch`` בלי תקרת זמן, אחרי ``getSubscription``
  // ו-digest — יכול ברשת איטית לאכול את החלון כולו, ואז הפתק פשוט לא נפתח. לכן כל דיווח
  // יוצא מיד ונאסף כאן, ו-``waitUntil`` ממתין לכולם **בסוף**: ה-SW נשאר חי עד שהם נשלחו,
  // בלי שאף אחד מהם עומד בדרך.
  const reports = [];
  const report = (eventType, status, extra) => {
    reports.push(Promise.resolve().then(() => reportToServer(eventType, status, extra)).catch(() => {}));
  };

  const handled = (async () => {
    const fileId = (d && d.file_id != null) ? String(d.file_id) : '';
    const noteId = (d && d.note_id != null) ? String(d.note_id) : '';
    const remindAt = (d && d.remind_at != null) ? String(d.remind_at) : '';
    const action = (event && event.action) ? String(event.action) : '';
    // התראה על תגובה של סוכן בשרשור (``note_comment`` ב-``push_api.py``) — **לא תזכורת**.
    // היא נושאת ``note_id`` כדי לפתוח את הפתק, ולכן בלי הבידול הזה הלחיצה עליה הייתה
    // שולחת אישור תזכורת (ראו ``!isComment`` למטה) וסוגרת בשקט תזכורת פעילה על אותו
    // פתק. ‏``thread_id`` פותח את השרשור עצמו.
    const isComment = !!(d && d.type === 'note_comment');
    const threadId = (isComment && d.thread_id != null) ? String(d.thread_id) : '';

    // Report click (no PII: only presence + action)
    report('notification_click', 'started', {
      action: action || '',
      has_file_id: !!fileId,
      has_note_id: !!noteId,
    });

    // דחייה: קובעים את הדחייה, ובזה הלחיצה נגמרת — ההתראה כבר נסגרה בראש ה-handler.
    //
    // עד נובמבר 2026 "דחה 10 דק׳" גם פתח את הפתק: ``snooze_10`` היה ברשימת הפתיחה כפולבק
    // למקרה ש"כפתורי הפעולה ממופים שגוי" (נוסף בינואר 2026, PR #2733). אין מיפוי כזה —
    // לחיצה על כפתור מביאה את ה-``action`` שלו, ולחיצה על גוף ההתראה מביאה מחרוזת ריקה
    // (https://notifications.spec.whatwg.org/#activating-a-notification) — והדחייה עצמה
    // נקבעה ל-10 דקות בדיוק, כלומר השם הגיע נכון. ורק ``snooze_10`` היה שם: "דחה שעה" לא פתח.
    const isSnooze = !!(action && action.startsWith('snooze_') && noteId);
    if (isSnooze) {
      const minutes = Number(action.split('_')[1] || 10);
      // סירוב אינו כשל רשת: 404 על תזכורת שכבר אושרה (ממכשיר אחר, או מהחלונית
      // בזמן שההתראה עוד ישבה במגש) חוזר כתשובה רגילה, ו-.catch לא רואה אותו.
      // בלי לקרוא response.ok המשתמש חושב שנדחה, וההתראה שנשאה את הכפתור כבר
      // נסגרה — אין הזדמנות שנייה. לכן: מדווחים בכל תוצאה (כדי שהקצב יימדד),
      // וכשהדחייה לא נקבעה מראים התראה שאומרת זאת. קוד התשובה נקרא http_status
      // ולא status, כי status הוא שדה הדיווח עצמו.
      let outcome = 'error';
      const detail = { minutes: minutes };
      try {
        const resp = await fetch(`/api/sticky-notes/note/${encodeURIComponent(noteId)}/snooze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ minutes })
        });
        outcome = resp.ok ? 'success' : 'refused';
        detail.http_status = resp.status;
      } catch (e) {
        detail.error = String(e);
      }
      report('snooze', outcome, detail);
      if (outcome !== 'success') {
        try {
          await self.registration.showNotification('הדחייה לא התקבלה', {
            body: outcome === 'refused'
              ? 'התזכורת כבר טופלה או נמחקה, ולכן אין מה לדחות.'
              : 'לא הצלחתי להגיע לשרת. פתחו את הפתק כדי לקבוע תזכורת מחדש.',
            icon: '/static/icons/app-icon-512.png',
            tag: 'codekeeper-snooze-' + noteId,
            data: { note_id: noteId, file_id: fileId },
          });
        } catch (_) {}
      }
      return;
    }

    // פתיחה: רק "פתח פתק", או לחיצה על גוף ההתראה (בלי action).
    const shouldOpen = !action || action === 'open_note';
    if (!shouldOpen) {
      report('notification_click', 'skipped_open', { action: action || '' });
      return;
    }
    // הפרמלינק /note/<id> הוא הבונה היחיד של יעד הפתק. השרת יודע אם הפתק
    // יושב על קובץ או על לוח ומפנה בהתאם, ולכן ה-SW אינו צריך להכיר את
    // סוגי הפתקים — כולל סוג שלישי שיתווסף בעתיד.
    //
    // עד היום כאן נבנה /md/<file_id>, ולפתק לוח (שאין לו file_id) ההתראה
    // נחתה בשורש האתר.
    let urlToOpen = '/';
    try {
      if (noteId) {
        urlToOpen = `/note/${encodeURIComponent(noteId)}`;
        // ``thread`` הוא פרמטר חד-פעמי: הקישור הקבוע מעביר אותו הלאה, והעמוד פותח את
        // השרשור ומסיר אותו מהכתובת — כמו ``note``.
        if (threadId) {
          urlToOpen += `?thread=${encodeURIComponent(threadId)}`;
        }
      } else if (fileId) {
        // פולבק להתראות ישנות שכבר בתור ואין בהן note_id
        urlToOpen = `/md/${encodeURIComponent(fileId)}`;
      }
    } catch (_) {
      urlToOpen = '/';
    }
    // Normalize to absolute URL for best compatibility
    try { urlToOpen = new URL(urlToOpen, self.location.origin).toString(); } catch (_) {}

    // Best-effort ack when we actually have a note id.
    //
    // דחייה אינה מגיעה לכאן — היא חוזרת למעלה. עד נובמבר 2026 היא הגיעה (``snooze_10`` היה
    // ברשימת הפתיחה), ולכן כאן עמד גם ``!isSnooze``: בלעדיו ה-ack ביטל את הדחייה שזה עתה
    // נקבעה, כי שתי הפעולות סותרות — דחייה אומרת "תחזור אליי", אישור אומר "ראיתי, די".
    //
    // ‏`!isComment`: התראת תגובה נושאת `note_id` רק כדי לפתוח את הפתק. בלי
    // `remind_at` האישור **אינו קשור למועד**, ולכן לחיצה עליה הייתה סוגרת כל תזכורת פעילה
    // של הפתק. מכשיר שעדיין מריץ SW ישן (לפני 2.2.0) עדיין שולח כאן אישור עד שהדפדפן מעדכן
    // אותו — חלון מעבר מתועד, ב-``docs/deployment/workers.rst``.
    if (noteId && !isComment) {
      // המועד שההתראה נשאה חוזר לשרת, והאישור נקשר אליו: התראה שישבה במגש
      // מאתמול לא סוגרת תזכורת שנקבעה מחדש מאז. התראה בלי מועד (הוצגה לפני
      // שהשדה נוסף) מאשרת בלי קשירה, כמו קודם.
      const ackBody = { note_id: noteId };
      if (remindAt) { ackBody.remind_at = remindAt; }
      try {
        fetch('/api/sticky-notes/reminders/ack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(ackBody)
        }).catch(() => {});
      } catch (_) {}
    }

    // תמיד לשונית חדשה: ``openWindow`` יוצר top-level browsing context חדש
    // (https://w3c.github.io/ServiceWorker/#clients-openwindow — "Let newContext be a new
    // top-level browsing context").
    //
    // עד נובמבר 2026 כאן חיפשנו לשונית קיימת וניווטנו אותה: לשונית של אותו קובץ כשבהתראה
    // היה ``file_id``, ובלעדיו — ``windowClients[0]``, שהיא לפי המפרט הלשונית של האתר
    // שהייתה **אחרונה בפוקוס** (https://w3c.github.io/ServiceWorker/#clients-matchall). כלומר
    // תזכורת של פתק לוח, והתראת תגובה, חטפו את הלשונית שהמשתמש עבד בה. והחיפוש כלל גם
    // לשוניות שה-SW אינו שולט בהן (``includeUncontrolled``), שעליהן ``navigate`` נדחה ב-
    // TypeError (https://w3c.github.io/ServiceWorker/#client-navigate) — וה-catch פתח את שורש
    // האתר במקום את הפתק.
    try {
      await clients.openWindow(urlToOpen);
      report('notification_click', 'opened', { action: action || '', opened: true });
    } catch (e) {
      report('notification_click', 'error', { action: action || '', error: String(e) });
      try { await clients.openWindow('/'); } catch (_) {}
    }
  })();

  event.waitUntil(handled.finally(() => Promise.all(reports)));
});

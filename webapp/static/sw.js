// SW Version for cache busting
const SW_VERSION = '2.0.3';

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

  event.waitUntil((async () => {
    const fileId = (d && d.file_id != null) ? String(d.file_id) : '';
    const noteId = (d && d.note_id != null) ? String(d.note_id) : '';
    const action = (event && event.action) ? String(event.action) : '';

    // Report click (no PII: only presence + action)
    try {
      await reportToServer('notification_click', 'started', {
        action: action || '',
        has_file_id: !!fileId,
        has_note_id: !!noteId,
      });
    } catch (_) {}

    // Snooze actions
    if (action && action.startsWith('snooze_') && noteId) {
      const minutes = Number(action.split('_')[1] || 10);
      try {
        await fetch(`/api/sticky-notes/note/${encodeURIComponent(noteId)}/snooze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ minutes })
        }).catch(() => {});
      } catch (_) {}
      return;
    }

    // Open-note action OR clicking the notification body: open the markdown view with deep-link
    // (matches the in-app behavior: /md/<file_id>?note=<note_id>)
    let urlToOpen = '/';
    try {
      if (fileId) {
        urlToOpen = `/md/${encodeURIComponent(fileId)}` + (noteId ? `?note=${encodeURIComponent(noteId)}` : '');
      }
    } catch (_) {
      urlToOpen = '/';
    }
    // Normalize to absolute URL for best compatibility
    try { urlToOpen = new URL(urlToOpen, self.location.origin).toString(); } catch (_) {}

    // Best-effort ack when we actually have a note id
    if (noteId) {
      try {
        fetch('/api/sticky-notes/reminders/ack', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note_id: noteId })
        }).catch(() => {});
      } catch (_) {}
    }

    try {
      const windowClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
      let matchingClient = null;
      try {
        if (fileId) {
          const needle = `/md/${encodeURIComponent(fileId)}`;
          matchingClient = windowClients.find((client) => client && client.url && client.url.includes(needle));
        } else {
          matchingClient = windowClients.length ? windowClients[0] : null;
        }
      } catch (_) {}

      if (matchingClient && matchingClient.navigate) {
        const client = await matchingClient.navigate(urlToOpen);
        try { client && client.focus && client.focus(); } catch (_) {}
      } else {
        await clients.openWindow(urlToOpen);
      }
      try { await reportToServer('notification_click', 'opened', { action: action || '', opened: true }); } catch (_) {}
    } catch (e) {
      try { await reportToServer('notification_click', 'error', { action: action || '', error: String(e) }); } catch (_) {}
      try { await clients.openWindow('/'); } catch (_) {}
    }
  })());
});

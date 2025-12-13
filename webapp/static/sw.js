self.addEventListener('install', (event) => {
  // Skip waiting so the new SW takes control ASAP
  try { self.skipWaiting(); } catch (_) {}
});

self.addEventListener('activate', (event) => {
  // Claim clients without reload
  event.waitUntil((async () => {
    try { await self.clients.claim(); } catch (_) {}
  })());
});

self.addEventListener('push', (event) => {
  // Debug: log that we received the push event
  console.log('[SW] Push event received at:', new Date().toISOString());
  
  const handlePush = async () => {
    try {
      // Parse payload with detailed logging
      let json = {};
      let rawData = null;
      
      if (event.data) {
        try {
          rawData = event.data.text();
          console.log('[SW] Raw push data:', rawData);
          json = JSON.parse(rawData);
          console.log('[SW] Parsed JSON:', JSON.stringify(json));
        } catch (parseErr) {
          console.error('[SW] JSON parse error:', parseErr, 'raw:', rawData);
          // Still continue with empty json - fallback title will be used
        }
      } else {
        console.log('[SW] No event.data present');
      }
      
      // Robust extraction of title/body from various payload structures
      // 1. Top-level (Standard Web Push)
      // 2. notification key (FCM style)
      // 3. data key (Data-only style)
      const title = json.title || (json.notification && json.notification.title) || (json.data && json.data.title) || '🔔 יש פתק ממתין';
      const body = json.body || (json.notification && json.notification.body) || (json.data && json.data.body) || '';
      
      console.log('[SW] Extracted title:', title, 'body:', body);
      
      const customData = json.data || {};
      // Merge top-level custom fields if they exist and aren't in data
      if (json.note_id && !customData.note_id) customData.note_id = json.note_id;
      if (json.file_id && !customData.file_id) customData.file_id = json.file_id;

      const options = {
        body: body,
        icon: '/static/icons/app-icon-192.png',
        badge: '/static/icons/app-icon-192.png',
        data: customData,
        // Force notification to show even if browser would normally suppress it
        requireInteraction: false,
        silent: false,
        tag: 'codekeeper-' + Date.now(), // Unique tag prevents collapsing
        actions: [
          { action: 'open_note', title: 'פתח פתק' },
          { action: 'snooze_10', title: 'דחה 10 דק׳' },
          { action: 'snooze_60', title: 'דחה שעה' },
          { action: 'snooze_1440', title: 'דחה 24 שעות' },
        ]
      };
      
      console.log('[SW] Calling showNotification with title:', title);
      
      // Verify registration exists before showing notification
      if (!self.registration) {
        console.error('[SW] self.registration is undefined!');
        throw new Error('No service worker registration');
      }
      
      await self.registration.showNotification(title, options);
      console.log('[SW] showNotification succeeded');
      
    } catch (err) {
      // CRITICAL: Never let the push handler fail silently!
      console.error('[SW] Push handler error:', err);
      
      // Attempt to show a fallback notification so user knows something happened
      try {
        if (self.registration) {
          await self.registration.showNotification('🔔 התראה חדשה', {
            body: 'לא הצלחנו לטעון את פרטי ההתראה',
            icon: '/static/icons/app-icon-192.png',
            tag: 'codekeeper-fallback-' + Date.now()
          });
          console.log('[SW] Fallback notification shown');
        }
      } catch (fallbackErr) {
        console.error('[SW] Even fallback notification failed:', fallbackErr);
      }
    }
  };
  
  event.waitUntil(handlePush());
});

self.addEventListener('notificationclick', (event) => {
  const d = (event.notification && event.notification.data) || {};
  event.notification && event.notification.close && event.notification.close();

  if (event.action === 'open_note' && d.file_id && d.note_id) {
    const urlToOpen = `/file/${encodeURIComponent(d.file_id)}#note=${encodeURIComponent(d.note_id)}`;
    const ack = fetch('/api/sticky-notes/reminders/ack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ note_id: String(d.note_id) })
    }).catch(() => {});
    const nav = clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      let matchingClient = null;
      try {
        matchingClient = windowClients.find((client) => client && client.url && client.url.includes(`/file/${encodeURIComponent(d.file_id)}`));
      } catch(_) {}
      if (matchingClient && matchingClient.navigate) {
        return matchingClient.navigate(urlToOpen).then((client) => client && client.focus && client.focus());
      } else {
        return clients.openWindow(urlToOpen);
      }
    });
    event.waitUntil(Promise.all([ack, nav]));
  } else if (event.action && event.action.startsWith('snooze_') && d.note_id) {
    const minutes = Number(event.action.split('_')[1] || 10);
    event.waitUntil(
      fetch(`/api/sticky-notes/note/${encodeURIComponent(d.note_id)}/snooze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ minutes })
      }).catch(() => {})
    );
  } else {
    // Focus/open client on generic click
    event.waitUntil(
      clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
        if (windowClients.length > 0) {
          const client = windowClients[0];
          return client && client.focus && client.focus();
        }
        return clients.openWindow('/');
      })
    );
  }
});

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
  const json = event.data ? (() => { try { return event.data.json(); } catch(_) { return {}; } })() : {};
  
  // Robust extraction of title/body from various payload structures
  // 1. Top-level (Standard Web Push)
  // 2. notification key (FCM style)
  // 3. data key (Data-only style)
  const title = json.title || (json.notification && json.notification.title) || (json.data && json.data.title) || '🔔 יש פתק ממתין';
  const body = json.body || (json.notification && json.notification.body) || (json.data && json.data.body) || '';
  const customData = json.data || {};
  // Merge top-level custom fields if they exist and aren't in data
  if (json.note_id && !customData.note_id) customData.note_id = json.note_id;
  if (json.file_id && !customData.file_id) customData.file_id = json.file_id;

  const options = {
    body: body,
    icon: '/static/icons/app-icon-192.png',
    badge: '/static/icons/app-icon-192.png',
    data: customData,
    actions: [
      { action: 'open_note', title: 'פתח פתק' },
      { action: 'snooze_10', title: 'דחה 10 דק׳' },
      { action: 'snooze_60', title: 'דחה שעה' },
      { action: 'snooze_1440', title: 'דחה 24 שעות' },
    ]
  };
  event.waitUntil(
    self.registration.showNotification(title, options)
  );
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

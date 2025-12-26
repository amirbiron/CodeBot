self.addEventListener('install', (event) => {
    self.skipWaiting(); // הכרח עדכון מיידי
    console.log('Service Worker Installed');
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim()); // השתלטות מיידית
    console.log('Service Worker Activated');
});

self.addEventListener('push', function(event) {
    console.log('Push received via minimalist SW');

    // 1. דיווח מיידי לשרת - הכי פשוט שאפשר
    const reportPromise = fetch('/api/push/sw-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event: 'minimal_sw_push', status: 'alive' })
    }).catch(err => console.error('Report failed', err));

    // 2. התראה קבועה מראש (Hardcoded) - עוקף בעיות JSON
    const notificationPromise = self.registration.showNotification('בדיקת מערכת', {
        body: 'אם אתה רואה את זה - הצינור עובד!',
        icon: '/static/icons/app-icon-192.png', // וודא שהקובץ קיים!
        requireInteraction: true
    });

    event.waitUntil(Promise.all([reportPromise, notificationPromise]));
});

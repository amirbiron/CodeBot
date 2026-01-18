/**
 * Admin Impersonation Toggle
 * מאפשר לאדמינים לצפות במערכת כמשתמש רגיל
 * 
 * גרסה: 1.1 - כולל תמיכה ב-CSRF ו-Force Reload
 */

(function() {
    'use strict';
    
    const API_START = '/admin/impersonate/start';
    const API_STOP = '/admin/impersonate/stop';
    
    /**
     * מקבל את ה-CSRF Token מה-meta tag (אם קיים).
     * נדרש אם המערכת משתמשת ב-Flask-WTF או הגנת CSRF אחרת.
     */
    function getCsrfToken() {
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        return metaTag ? metaTag.getAttribute('content') : null;
    }
    
    /**
     * בונה את ה-headers לבקשה, כולל CSRF אם קיים.
     */
    function buildHeaders() {
        const headers = {
            'Content-Type': 'application/json',
        };
        
        const csrfToken = getCsrfToken();
        if (csrfToken) {
            headers['X-CSRFToken'] = csrfToken;
        }
        
        return headers;
    }
    
    /**
     * רענון "קשה" של הדף - מתעלם מ-cache.
     * משתמש ב-location.reload(true) שעובד ברוב הדפדפנים,
     * עם fallback לשינוי ה-URL אם לא עובד.
     */
    function forceReload() {
        // נסיון 1: reload(true) - deprecated אבל עדיין עובד בחלק מהדפדפנים
        try {
            window.location.reload(true);
        } catch (e) {
            // נסיון 2: הוספת timestamp ל-URL למניעת cache
            const url = new URL(window.location.href);
            url.searchParams.set('_t', Date.now());
            window.location.href = url.toString();
        }
    }
    
    function startImpersonation() {
        fetch(API_START, {
            method: 'POST',
            headers: buildHeaders(),
            credentials: 'same-origin',
            cache: 'no-store',  // 🔄 מונע cache ברמת הבקשה
        })
        .then(response => response.json())
        .then(data => {
            if (data.ok) {
                // 🔄 Force Reload - וידוא שאין cache
                forceReload();
            } else {
                alert(data.error || 'שגיאה בהפעלת מצב צפייה');
            }
        })
        .catch(err => {
            console.error('Impersonation start error:', err);
            alert('שגיאת תקשורת');
        });
    }
    
    function stopImpersonation() {
        fetch(API_STOP, {
            method: 'POST',
            headers: buildHeaders(),
            credentials: 'same-origin',
            cache: 'no-store',
        })
        .then(response => response.json())
        .then(data => {
            if (data.ok) {
                forceReload();
            } else {
                alert(data.error || 'שגיאה בכיבוי מצב צפייה');
            }
        })
        .catch(err => {
            console.error('Impersonation stop error:', err);
            alert('שגיאת תקשורת');
        });
    }
    
    // Event Listeners
    document.addEventListener('DOMContentLoaded', function() {
        const btnStart = document.getElementById('btn-start-impersonation');
        const btnStop = document.getElementById('btn-stop-impersonation');
        
        if (btnStart) {
            btnStart.addEventListener('click', function(e) {
                e.preventDefault();
                if (confirm('האם להפעיל מצב צפייה כמשתמש רגיל?\n\nבמצב זה לא תראה אפשרויות אדמין.\n\n💡 טיפ: אם תתקע, הוסף ?force_admin=1 ל-URL')) {
                    startImpersonation();
                }
            });
        }
        
        if (btnStop) {
            btnStop.addEventListener('click', function(e) {
                e.preventDefault();
                stopImpersonation();
            });
        }
    });
})();

/**
 * שחזור גרסה — עותק אחד של קריאת ה-POST.
 *
 * הקריאה הזו הייתה כתובה בתוך מודאל ההיסטוריה ב-``view_file.html``,
 * ובאנר הגרסה הישנה (שמוצג גם ב-``md_preview``) היה צריך אותה שוב.
 * שני עותקים של אותה קריאה הם שתי דרכים להיסחף — למשל כשתתווסף כותרת
 * CSRF לאחד מהם בלבד. לכן היא יושבת כאן, וכל מי שצריך לשחזר קורא לה.
 *
 * ‏POST ולא קישור: השחזור יוצר גרסה חדשה, ופעולה שמשנה מצב מאחורי GET
 * נורית על ידי prefetch, היסטוריה וסורקי תצוגה מקדימה של קישורים.
 */
(function () {
    'use strict';

    function toast(message, kind) {
        if (typeof window.showToast === 'function') {
            window.showToast(message, kind);
        }
    }

    /**
     * @param {string} fileId  מזהה המסמך שממנו משחזרים
     * @param {number} version מספר הגרסה לשחזור
     * @param {HTMLElement} button הכפתור שנלחץ (מושבת בזמן הפעולה)
     * @param {{onSuccess?: Function, viewPrefix?: string}} [options]
     */
    async function restoreFileVersion(fileId, version, button, options) {
        const opts = options || {};
        if (!fileId || !version || !button) {
            return false;
        }
        button.disabled = true;
        const originalText = button.textContent;
        button.textContent = 'משחזר...';
        try {
            const resp = await fetch('/api/file/' + encodeURIComponent(fileId) + '/restore', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ version: version }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || !data.ok) {
                throw new Error(data.error || 'שגיאה בשחזור הגרסה');
            }
            toast('הגרסה שוחזרה בהצלחה', 'success');
            if (typeof opts.onSuccess === 'function') {
                opts.onSuccess(data);
            }
            const nextId = data.file_id || data.id;
            if (nextId) {
                window.location.href = (opts.viewPrefix || '/file/') + nextId;
            } else {
                window.location.reload();
            }
            return true;
        } catch (err) {
            toast(err.message || 'שגיאה בשחזור הגרסה', 'error');
            button.disabled = false;
            button.textContent = originalText || 'שחזר';
            return false;
        }
    }

    window.restoreFileVersion = restoreFileVersion;
})();

/**
 * Export Modal - לוגיקת מודאל ייצוא HTML מעוצב
 *
 * **"תצוגה מקדימה" ו"הורד HTML" מרנדרים את הקובץ בדפדפן** (``data-browser-render="1"`` על המודאל): באותו מנוע כמו
 * התצוגה החיה והעורך הציבורי, כדי שיהיה מנוע אחד לכל הייצוא. השרת מגיש רק שלד — העמוד המעוצב של הערכה, עם שם
 * הקובץ (``export_styled_skeleton`` ב-``webapp/app.py``) — והטקסט נלקח מהעמוד (``#rawCode``), או, בקובץ שגדול
 * מכדי שהעמוד יציג אותו, מ-``/download/<id>``, שמחזיר בדיוק את אותה גרסה. המנוע נטען רק בלחיצה
 * (``StyledExportCore.loadEngine``), מתוך ``#styledExportEngine``. בלי ``data-browser-render`` (המתג
 * ``STYLED_EXPORT_BROWSER_RENDER``) — המסלול הקודם, שבו השרת ממיר בעצמו. "העתק קישור" עדיין יוצר את הקישור בשרת.
 */
(function () {
    'use strict';

    // 🔒 XSS Protection - escape HTML entities
    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // 🔒 Validate hex color (prevent CSS injection)
    function isValidHexColor(color) {
        return /^#[0-9a-fA-F]{3,8}$/.test(color);
    }

    function sanitizeColor(color) {
        return isValidHexColor(color) ? color : '#888888';
    }

    // State
    let selectedTheme = {
        id: 'tech-guide-dark',
        name: 'Tech Guide Dark',
        source: 'preset', // 'preset' | 'user' | 'vscode'
        vscodeJson: null,  // תוכן JSON אם מקור הוא VS Code
        mermaidTheme: 'dark', // ערכת ה-Mermaid של הקובץ — התרשימים מצוירים לפני שהשלד מגיע
    };
    let fileId = null;
    let presetsLoaded = false;

    // DOM Elements
    const modal = document.getElementById('exportThemeModal');
    if (!modal) return;

    const presetsGrid = document.getElementById('exportPresetsGrid');
    const userThemesGrid = document.getElementById('exportUserThemesGrid');
    const selectedNameEl = document.getElementById('exportSelectedThemeName');
    const uploadArea = document.getElementById('exportUploadArea');
    const uploadStatus = document.getElementById('exportUploadStatus');
    const uploadFileName = document.getElementById('exportUploadFileName');
    const fileInput = document.getElementById('exportThemeFileInput');

    // ============================================
    // Modal Open/Close
    // ============================================

    window.openExportModal = function (fid) {
        fileId = fid;
        modal.hidden = false;
        document.body.style.overflow = 'hidden';

        // איפוס מצב כפתור Copy Link
        resetCopyLinkButton();

        if (!presetsLoaded) {
            loadThemes();
        }
    };

    function closeModal() {
        modal.hidden = true;
        document.body.style.overflow = '';
    }

    // Close handlers
    modal.querySelectorAll('[data-export-close]').forEach(btn => {
        btn.addEventListener('click', closeModal);
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal.hidden) closeModal();
    });

    // ============================================
    // Tabs
    // ============================================

    const tabs = modal.querySelectorAll('.export-tab');
    const tabContents = modal.querySelectorAll('.export-tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;

            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));

            tab.classList.add('active');
            document.getElementById(`export-${targetTab}-tab`).classList.add('active');
        });
    });

    // ============================================
    // Load Themes
    // ============================================

    async function loadThemes() {
        try {
            const resp = await fetch('/api/export/themes');
            const data = await resp.json();

            if (!data.ok) throw new Error(data.error || 'Failed to load themes');

            renderPresets(data.presets || []);
            renderUserThemes(data.user_themes || []);
            presetsLoaded = true;
        } catch (err) {
            console.error('Load themes error:', err);
            if (presetsGrid) {
                presetsGrid.innerHTML = '<p class="export-error">שגיאה בטעינת ערכות</p>';
            }
        }
    }

    function renderPresets(presets) {
        if (!presetsGrid) return;
        if (!presets.length) {
            presetsGrid.innerHTML = '<p class="export-empty">אין ערכות מוכנות</p>';
            return;
        }

        // 🔒 XSS Protection - escape all user-provided data
        presetsGrid.innerHTML = presets.map(p => `
            <button type="button"
                    class="export-theme-card ${p.id === selectedTheme.id ? 'selected' : ''}"
                    data-theme-id="${escapeHtml(p.id)}"
                    data-theme-name="${escapeHtml(p.name)}"
                    data-mermaid-theme="${escapeHtml(p.mermaid_theme || 'dark')}"
                    data-source="preset">
                <div class="export-theme-preview">
                    ${(p.preview_colors || []).map(c => `<span style="background:${sanitizeColor(c)}"></span>`).join('')}
                </div>
                <div class="export-theme-info">
                    <strong>${escapeHtml(p.name)}</strong>
                    <small>${escapeHtml(p.description || '')}</small>
                </div>
            </button>
        `).join('');

        // ערכת ה-Mermaid של הערכה שנבחרה מראש מגיעה מהשרת, כמו של כל השאר — ה-``'dark'`` שבמצב ההתחלתי הוא רק למי
        // שמייצא לפני שהרשימה נטענה
        const preselected = presets.find((p) => p.id === selectedTheme.id);
        if (selectedTheme.source === 'preset' && preselected && preselected.mermaid_theme) {
            selectedTheme.mermaidTheme = preselected.mermaid_theme;
        }

        bindThemeCards(presetsGrid);
    }

    function renderUserThemes(themes) {
        if (!userThemesGrid) return;
        if (!themes.length) {
            userThemesGrid.innerHTML = `
                <p class="export-empty">
                    אין לך ערכות מותאמות אישית.
                    <a href="/settings/theme-gallery">צור ערכה חדשה</a>
                </p>
            `;
            return;
        }

        // 🔒 XSS Protection - escape all user-provided data
        userThemesGrid.innerHTML = themes.map(t => `
            <button type="button"
                    class="export-theme-card"
                    data-theme-id="${escapeHtml(t.id)}"
                    data-theme-name="${escapeHtml(t.name)}"
                    data-mermaid-theme="${escapeHtml(t.mermaid_theme || 'dark')}"
                    data-source="user">
                <div class="export-theme-info">
                    <strong>${escapeHtml(t.name)}</strong>
                    <small>${escapeHtml(t.description || 'ערכה מותאמת אישית')}</small>
                </div>
            </button>
        `).join('');

        bindThemeCards(userThemesGrid);
    }

    function bindThemeCards(container) {
        if (!container) return;
        container.querySelectorAll('.export-theme-card').forEach(card => {
            card.addEventListener('click', () => selectTheme(card));
        });
    }

    function selectTheme(card) {
        // Remove previous selection
        modal.querySelectorAll('.export-theme-card.selected').forEach(c => {
            c.classList.remove('selected');
        });

        card.classList.add('selected');

        selectedTheme = {
            id: card.dataset.themeId,
            name: card.dataset.themeName,
            source: card.dataset.source,
            vscodeJson: null,
            mermaidTheme: card.dataset.mermaidTheme || 'dark',
        };

        if (selectedNameEl) {
            selectedNameEl.textContent = selectedTheme.name;
        }
    }

    // ============================================
    // VS Code Import
    // ============================================

    if (uploadArea && fileInput) {
        uploadArea.addEventListener('click', () => fileInput.click());

        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });

        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });

        uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadArea.classList.remove('dragover');

            const file = e.dataTransfer.files[0];
            if (file) handleFileUpload(file);
        });

        fileInput.addEventListener('change', () => {
            const file = fileInput.files[0];
            if (file) handleFileUpload(file);
        });
    }

    // ============================================
    // Error Display (UI יפה במקום alert)
    // ============================================

    const errorContainer = document.createElement('div');
    errorContainer.className = 'export-error-message';
    errorContainer.hidden = true;
    // מוסיפים ל-modal content (נראה מכל הטאבים)
    const modalContent = modal.querySelector('.export-modal__content');
    if (modalContent) {
        modalContent.insertBefore(errorContainer, modalContent.firstChild);
    }

    // Store timeout reference to prevent premature hiding
    let errorHideTimeout = null;

    function showError(message) {
        // Clear any existing timeout to prevent premature hiding
        if (errorHideTimeout) {
            clearTimeout(errorHideTimeout);
            errorHideTimeout = null;
        }

        errorContainer.textContent = message;
        errorContainer.hidden = false;
        errorContainer.classList.add('shake');

        setTimeout(() => {
            errorContainer.classList.remove('shake');
        }, 500);

        // הסתרה אוטומטית אחרי 5 שניות
        errorHideTimeout = setTimeout(() => {
            errorContainer.hidden = true;
            errorHideTimeout = null;
        }, 5000);
    }

    function hideError() {
        if (errorHideTimeout) {
            clearTimeout(errorHideTimeout);
            errorHideTimeout = null;
        }
        errorContainer.hidden = true;
    }

    async function handleFileUpload(file) {
        hideError();

        // Case-insensitive check for .json extension
        if (!file.name.toLowerCase().endsWith('.json')) {
            showError('נא להעלות קובץ JSON בלבד');
            return;
        }

        try {
            const content = await file.text();

            // Parse and validate
            const resp = await fetch('/api/export/parse-vscode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ json_content: content }),
            });

            const data = await resp.json();

            if (!data.ok) {
                showError(`שגיאה בפרסור הערכה: ${data.error}`);
                return;
            }

            // Success - update state
            // Case-insensitive extension removal
            const displayName = data.name || file.name.replace(/\.json$/i, '');
            selectedTheme = {
                id: 'vscode-import',
                name: displayName,
                source: 'vscode',
                vscodeJson: content,
                mermaidTheme: data.mermaid_theme || 'dark',
            };

            if (selectedNameEl) {
                selectedNameEl.textContent = selectedTheme.name;
            }
            if (uploadStatus) uploadStatus.hidden = false;
            if (uploadFileName) uploadFileName.textContent = file.name;

            // Visual feedback
            if (uploadArea) {
                uploadArea.classList.add('success');
                setTimeout(() => uploadArea.classList.remove('success'), 2000);
            }

        } catch (err) {
            console.error('File upload error:', err);
            showError('שגיאה בקריאת הקובץ. וודא שזהו קובץ JSON תקין.');
        }
    }

    // ============================================
    // Actions: Preview & Download
    // ============================================

    const previewBtn = modal.querySelector('[data-action="preview"]');
    const downloadBtn = modal.querySelector('[data-action="download"]');
    const copyLinkBtn = modal.querySelector('[data-action="copy-link"]');

    if (previewBtn) {
        previewBtn.addEventListener('click', async () => {
            if (browserRender) {
                await browserExport('preview');
                return;
            }
            // מקרה מיוחד: תצוגה מקדימה של VS Code JSON (צריך POST עם Blob)
            if (selectedTheme.source === 'vscode' && selectedTheme.vscodeJson) {
                try {
                    const formData = new FormData();
                    formData.append('vscode_json', selectedTheme.vscodeJson);
                    formData.append('preview', '1');

                    const response = await fetch(`/export/styled/${fileId}`, {
                        method: 'POST',
                        body: formData
                    });

                    if (!response.ok) {
                        throw new Error('שגיאה בשרת');
                    }

                    // יצירת Blob URL ופתיחה בחלון חדש
                    const htmlBlob = await response.blob();
                    const blobUrl = URL.createObjectURL(htmlBlob);
                    window.open(blobUrl, '_blank');

                    // ניקוי ה-Blob URL אחרי זמן קצר
                    setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
                } catch (err) {
                    console.error('Preview error:', err);
                    showError('שגיאה ביצירת תצוגה מקדימה');
                }
                return;
            }

            // מקרה רגיל (GET)
            const url = buildExportUrl(true);
            window.open(url, '_blank');
        });
    }

    if (downloadBtn) {
        downloadBtn.addEventListener('click', async () => {
            if (browserRender) {
                if (await browserExport('download')) closeModal();
                return;
            }
            if (selectedTheme.source === 'vscode' && selectedTheme.vscodeJson) {
                // VS Code theme - need to POST the JSON
                await downloadWithVscodeTheme();
            } else {
                // Preset or user theme - simple GET
                const url = buildExportUrl(false);
                window.location.href = url;
            }

            closeModal();
        });
    }

    // ============================================
    // Browser Render — הייצוא בדפדפן
    // ============================================

    const Core = window.StyledExportCore;
    const browserRender = modal.dataset.browserRender === '1' && !!Core;
    const markerText = modal.dataset.contentMarker || '';
    const engineTemplate = document.getElementById('styledExportEngine');
    // תקרות זמן: לטעינת המנוע כולה (כ-1.4MB דחוס בטעינה הראשונה), לבקשת הטקסט ולבקשת השלד. הכפתורים מושבתים בזמן
    // הבנייה, ולכן המתנה שלא נגמרת לא יכולה להשאיר אותם מושבתים.
    const ENGINE_TIMEOUT_MS = 60000;
    const TEXT_TIMEOUT_MS = 30000;
    const SKELETON_TIMEOUT_MS = 15000;

    function setBusy(busy) {
        [previewBtn, downloadBtn, copyLinkBtn].forEach((btn) => { if (btn) btn.disabled = busy; });
        modal.setAttribute('aria-busy', busy ? 'true' : 'false');
    }

    // הטקסט של הקובץ: מהעמוד, או — בקובץ שגדול מכדי שהעמוד יציג אותו — מ-``/download/<id>``. שניהם מחזירים בדיוק
    // את הגרסה שבתצוגה (``/api/file/<id>/content`` היה מחזיר את האחרונה, גם כשמייצאים גרסה ישנה).
    async function markdownText() {
        const raw = document.getElementById('rawCode');
        if (raw) return raw.value;
        const resp = await Core.fetchText(`/download/${encodeURIComponent(fileId)}`, { timeoutMs: TEXT_TIMEOUT_MS });
        return resp.text;
    }

    async function fetchSkeleton(withMath) {
        const base = `/export/styled/${encodeURIComponent(fileId)}/skeleton`;
        if (selectedTheme.source === 'vscode' && selectedTheme.vscodeJson) {
            const form = new FormData();
            form.append('vscode_json', selectedTheme.vscodeJson);
            if (withMath) form.append('math', '1');
            return Core.fetchText(base, { method: 'POST', body: form, timeoutMs: SKELETON_TIMEOUT_MS });
        }
        const params = new URLSearchParams({ theme: selectedTheme.id });
        if (withMath) params.set('math', '1');
        return Core.fetchText(`${base}?${params}`, { timeoutMs: SKELETON_TIMEOUT_MS });
    }

    // מחזיר ``true`` כשהקובץ נמסר. "תצוגה מקדימה" פותחת את הטאב כבר עכשיו, בתוך הלחיצה (``openPreviewTab``).
    async function browserExport(mode) {
        hideError();
        let previewWindow = null;
        if (mode === 'preview') {
            previewWindow = Core.openPreviewTab();
            if (!previewWindow) {
                showError('הדפדפן חסם את הטאב החדש. אפשר להתיר חלונות קופצים לאתר, או להוריד את הקובץ.');
                return false;
            }
        }
        setBusy(true);
        try {
            await Core.loadEngine(engineTemplate, ENGINE_TIMEOUT_MS);
            const box = await Core.renderMarkdown(await markdownText(), selectedTheme.mermaidTheme);
            const skeleton = await fetchSkeleton(Core.hasMath(box));
            // שם המסמך הוא שם הקובץ, והוא כבר בשלד — לא הכותרת הראשונה, כמו בעורך הציבורי
            const html = Core.assemble(skeleton.text, box, markerText, null);
            const filename = decodeURIComponent(skeleton.headers.get('X-Export-Filename') || 'document.html');
            Core.deliver(html, previewWindow, filename);
            return true;
        } catch (err) {
            console.error('[export-modal] browser export failed', err);
            if (previewWindow) previewWindow.close();
            showError(Core.describeError(err));
            return false;
        } finally {
            setBusy(false);
        }
    }

    function buildExportUrl(isPreview) {
        let url = `/export/styled/${fileId}?theme=${encodeURIComponent(selectedTheme.id)}`;
        if (isPreview) url += '&preview=1';
        return url;
    }

    async function downloadWithVscodeTheme() {
        // For VS Code themes, we need to send the JSON content
        // Create a form and submit it
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/export/styled/${fileId}`;
        form.style.display = 'none';

        const jsonInput = document.createElement('input');
        jsonInput.type = 'hidden';
        jsonInput.name = 'vscode_json';
        jsonInput.value = selectedTheme.vscodeJson;
        form.appendChild(jsonInput);

        document.body.appendChild(form);
        form.submit();
        document.body.removeChild(form);
    }

    // ============================================
    // Copy Link - יצירת קישור שיתוף והעתקה ללוח
    // ============================================

    let copyLinkResetTimeout = null;
    const COPY_LINK_ORIGINAL_TEXT = 'העתק קישור';

    function resetCopyLinkButton() {
        if (!copyLinkBtn) return;

        // ביטול timeout קיים
        if (copyLinkResetTimeout) {
            clearTimeout(copyLinkResetTimeout);
            copyLinkResetTimeout = null;
        }

        // איפוס מצב הכפתור
        copyLinkBtn.disabled = false;
        copyLinkBtn.classList.remove('copy-success');
        const copyLinkText = copyLinkBtn.querySelector('.copy-link-text');
        if (copyLinkText) {
            copyLinkText.textContent = COPY_LINK_ORIGINAL_TEXT;
        }
    }

    if (copyLinkBtn) {
        copyLinkBtn.addEventListener('click', async () => {
            const copyLinkText = copyLinkBtn.querySelector('.copy-link-text');

            // הצגת מצב טעינה
            copyLinkBtn.disabled = true;
            if (copyLinkText) copyLinkText.textContent = 'יוצר קישור...';

            try {
                // בדיקת checkbox לקישור קבוע
                const permanentCheckbox = document.getElementById('exportPermanentLink');
                const isPermanent = permanentCheckbox ? permanentCheckbox.checked : false;

                // בניית הבקשה
                const requestBody = {
                    theme: selectedTheme.id,
                    permanent: isPermanent,
                };

                // אם זו ערכת VS Code, נוסיף את ה-JSON
                if (selectedTheme.source === 'vscode' && selectedTheme.vscodeJson) {
                    requestBody.vscode_json = selectedTheme.vscodeJson;
                }

                // קריאה ל-API
                const response = await fetch(`/api/export/styled/${fileId}/share`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody),
                });

                // ניסיון לפרסר JSON - גם אם הסטטוס לא ok, השרת עשוי להחזיר הודעת שגיאה ב-JSON
                let data;
                try {
                    data = await response.json();
                } catch (parseErr) {
                    // תגובה לא-JSON (כמו HTML 403 מ-decorators)
                    throw new Error('שגיאה בשרת');
                }

                if (!response.ok || !data.ok) {
                    throw new Error(data.error || 'שגיאה ביצירת קישור');
                }

                // ניסיון העתקה ללוח
                let clipboardSuccess = false;
                try {
                    await navigator.clipboard.writeText(data.share_url);
                    clipboardSuccess = true;
                } catch (clipboardErr) {
                    console.warn('Clipboard write failed:', clipboardErr);
                }

                if (clipboardSuccess) {
                    // הצגת הצלחה
                    copyLinkBtn.classList.add('copy-success');
                    if (copyLinkText) copyLinkText.textContent = 'הועתק!';

                    // החזרה למצב רגיל אחרי 2 שניות
                    copyLinkResetTimeout = setTimeout(() => {
                        copyLinkBtn.classList.remove('copy-success');
                        if (copyLinkText) copyLinkText.textContent = COPY_LINK_ORIGINAL_TEXT;
                        copyLinkBtn.disabled = false;
                        copyLinkResetTimeout = null;
                    }, 2000);
                } else {
                    // הצגת ה-URL למשתמש אם ההעתקה נכשלה
                    if (copyLinkText) copyLinkText.textContent = COPY_LINK_ORIGINAL_TEXT;
                    copyLinkBtn.disabled = false;
                    prompt('הקישור נוצר בהצלחה. העתק אותו ידנית:', data.share_url);
                }

            } catch (err) {
                console.error('Copy link error:', err);
                showError(err.message || 'שגיאה ביצירת קישור שיתוף');
                if (copyLinkText) copyLinkText.textContent = COPY_LINK_ORIGINAL_TEXT;
                copyLinkBtn.disabled = false;
            }
        });
    }

})();


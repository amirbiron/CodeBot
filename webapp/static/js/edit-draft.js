(function () {
  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function waitFor(fn, { timeoutMs = 2500, intervalMs = 100 } = {}) {
    const started = Date.now();
    // eslint-disable-next-line no-constant-condition
    while (true) {
      try {
        const value = fn();
        if (value) return value;
      } catch (_) {}
      if (Date.now() - started > timeoutMs) return null;
      // eslint-disable-next-line no-await-in-loop
      await sleep(intervalMs);
    }
  }

  function debounce(fn, wait) {
    let timeout;
    return (...args) => {
      clearTimeout(timeout);
      timeout = setTimeout(() => fn(...args), wait);
    };
  }

  function formatTime(value) {
    try {
      return new Intl.DateTimeFormat('he-IL', { hour: '2-digit', minute: '2-digit' }).format(new Date(value));
    } catch (_) {
      const date = new Date(value);
      const h = String(date.getHours()).padStart(2, '0');
      const m = String(date.getMinutes()).padStart(2, '0');
      return `${h}:${m}`;
    }
  }

  function getEditorContent(fallbackTextarea) {
    try {
      if (window.editorManager && window.editorManager.cmInstance && window.editorManager.cmInstance.state) {
        return window.editorManager.cmInstance.state.doc.toString();
      }
    } catch (_) {}
    const target = (window.editorManager && window.editorManager.textarea) || fallbackTextarea;
    return (target && target.value) || '';
  }

  function setEditorContent(nextValue, fallbackTextarea) {
    const value = typeof nextValue === 'string' ? nextValue : '';
    try {
      if (window.editorManager && window.editorManager.cmInstance && window.editorManager.cmInstance.state) {
        const view = window.editorManager.cmInstance;
        const length = view.state.doc.length;
        view.dispatch({ changes: { from: 0, to: length, insert: value } });
      }
    } catch (_) {}
    const target = (window.editorManager && window.editorManager.textarea) || fallbackTextarea;
    if (target) {
      target.value = value;
      try {
        target.dispatchEvent(new Event('input', { bubbles: true }));
      } catch (_) {}
    }
  }

  const supportsStorage = (() => {
    try {
      const testKey = '__editDraftTest__';
      localStorage.setItem(testKey, 'ok');
      localStorage.removeItem(testKey);
      return true;
    } catch (_) {
      return false;
    }
  })();

  function consumePendingDraftClears() {
    // תומך ב-reset אחרי "שמור גרסה חדשה": בעריכה יש redirect לעמוד צפייה,
    // ולכן אנחנו מסמנים ב-sessionStorage מה לנקות ומבצעים את הניקוי בטעינת העמוד הבא.
    try {
      if (!supportsStorage) return;
      const raw = sessionStorage.getItem('pendingDraftClearKeys.v1');
      if (!raw) return;
      const keys = JSON.parse(raw);
      if (!Array.isArray(keys) || keys.length === 0) {
        sessionStorage.removeItem('pendingDraftClearKeys.v1');
        return;
      }
      keys.forEach((k) => {
        try {
          if (k) localStorage.removeItem(String(k));
        } catch (_) {}
      });
      sessionStorage.removeItem('pendingDraftClearKeys.v1');
    } catch (_) {
      try {
        sessionStorage.removeItem('pendingDraftClearKeys.v1');
      } catch (_) {}
    }
  }

  function markDraftForClear(storageKey) {
    try {
      const raw = sessionStorage.getItem('pendingDraftClearKeys.v1');
      const curr = raw ? JSON.parse(raw) : [];
      const arr = Array.isArray(curr) ? curr : [];
      if (!arr.includes(storageKey)) arr.push(storageKey);
      sessionStorage.setItem('pendingDraftClearKeys.v1', JSON.stringify(arr));
    } catch (_) {
      // אם sessionStorage חסום - ננקה מיד (התנהגות דטרמיניסטית)
      try {
        localStorage.removeItem(storageKey);
      } catch (_) {}
    }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    consumePendingDraftClears();

    const form = document.getElementById('editForm');
    if (!form) {
      return;
    }

    const fileId = form.getAttribute('data-edit-file-id') || '';
    if (!fileId) {
      return;
    }

    const statusEl = document.getElementById('editDraftStatus');
    const restoreBtn = document.getElementById('restoreEditDraftBtn');
    const discardBtn = document.getElementById('discardEditDraftBtn');
    const storageKey = `editDraft.v1:${String(fileId)}`;

    if (!supportsStorage) {
      if (statusEl) statusEl.textContent = 'שמירה מקומית לא נתמכת בדפדפן';
      if (restoreBtn) restoreBtn.disabled = true;
      if (discardBtn) discardBtn.disabled = true;
      return;
    }

    const fileNameInput = document.getElementById('fileNameInput') || document.querySelector('input[name="file_name"]');
    const descriptionInput = document.querySelector('input[name="description"]');
    const tagsInput = document.querySelector('input[name="tags"]');
    const languageSelect = document.getElementById('languageSelect');
    const codeTextarea = document.getElementById('codeTextarea') || document.querySelector('textarea[name="code"]');
    const sourceUrlInput = document.getElementById('sourceUrlInput');
    const sourceUrlTouched = document.getElementById('sourceUrlTouched');

    const fileFormManager = await waitFor(() => window.fileFormManager, { timeoutMs: 2500, intervalMs: 100 });

    const initialState = collectState();
    const initialSnapshot = JSON.stringify(initialState);
    let lastSnapshot = initialSnapshot;

    const existingDraft = loadDraft();
    const draftSnapshot = existingDraft ? JSON.stringify(extractDraftState(existingDraft)) : '';

    const hasDraft = !!existingDraft;
    const shouldOfferRestore = hasDraft && draftSnapshot && draftSnapshot !== initialSnapshot;

    updateStatus(existingDraft && existingDraft.savedAt ? existingDraft.savedAt : null, shouldOfferRestore);
    toggleRestoreButton(!!shouldOfferRestore);
    toggleDiscardButton(!hasDraft);

    const debouncedSave = debounce(saveDraft, 800);
    const intervalId = setInterval(saveDraft, 30000);

    const observedInputs = [
      fileNameInput,
      descriptionInput,
      tagsInput,
      sourceUrlInput,
      languageSelect,
      (window.editorManager && window.editorManager.textarea) || codeTextarea,
    ].filter(Boolean);

    observedInputs.forEach((el) => {
      const eventName = el === languageSelect ? 'change' : 'input';
      el.addEventListener(eventName, debouncedSave);
    });

    // בלחיצה על "שמור גרסה חדשה" נסמן לניקוי; הניקוי עצמו יקרה בטעינת הדף הבא (view)
    form.addEventListener('submit', () => {
      markDraftForClear(storageKey);
    });

    window.addEventListener('beforeunload', () => {
      saveDraft();
      clearInterval(intervalId);
    });

    if (restoreBtn) {
      restoreBtn.addEventListener('click', () => {
        const draft = loadDraft();
        if (!draft) {
          toggleRestoreButton(false);
          toggleDiscardButton(true);
          updateStatus(null, false);
          return;
        }
        applyDraft(draft);
        lastSnapshot = JSON.stringify(collectState());
        updateStatus(draft.savedAt || null, false);
        toggleRestoreButton(false);
        toggleDiscardButton(false);
      });
    }

    if (discardBtn) {
      discardBtn.addEventListener('click', () => {
        const confirmed = window.confirm('למחוק את הטיוטה המקומית של העריכה הזו?');
        if (!confirmed) return;
        removeDraft(true);
        toggleRestoreButton(false);
        toggleDiscardButton(true);
      });
    }

    function collectState() {
      return {
        fileName: (fileNameInput && fileNameInput.value) || '',
        description: (descriptionInput && descriptionInput.value) || '',
        tags: (tagsInput && tagsInput.value) || '',
        language: (languageSelect && languageSelect.value) || '',
        code: getEditorContent(codeTextarea),
        sourceUrl: (sourceUrlInput && sourceUrlInput.value) || '',
      };
    }

    function extractDraftState(draft) {
      if (!draft || typeof draft !== 'object') return collectState();
      return {
        fileName: typeof draft.fileName === 'string' ? draft.fileName : '',
        description: typeof draft.description === 'string' ? draft.description : '',
        tags: typeof draft.tags === 'string' ? draft.tags : '',
        language: typeof draft.language === 'string' ? draft.language : '',
        code: typeof draft.code === 'string' ? draft.code : '',
        sourceUrl: typeof draft.sourceUrl === 'string' ? draft.sourceUrl : '',
      };
    }

    function saveDraft() {
      const state = collectState();
      const snapshot = JSON.stringify(state);
      if (snapshot === lastSnapshot) {
        return;
      }

      // בעמוד עריכה: טיוטה קיימת רק אם יש שינוי ביחס למצב המקורי
      if (snapshot === initialSnapshot) {
        removeDraft(true);
        lastSnapshot = snapshot;
        return;
      }

      const payload = { ...state, savedAt: Date.now(), fileId: String(fileId) };
      try {
        localStorage.setItem(storageKey, JSON.stringify(payload));
        lastSnapshot = snapshot;
        updateStatus(payload.savedAt, false);
        toggleDiscardButton(false);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[edit] failed to persist draft', err);
      }
    }

    function loadDraft() {
      try {
        const raw = localStorage.getItem(storageKey);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') return null;
        if (String(parsed.fileId || '') !== String(fileId)) return null;
        return parsed;
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[edit] failed to load draft', err);
        return null;
      }
    }

    function removeDraft(setStatus) {
      try {
        localStorage.removeItem(storageKey);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[edit] failed to remove draft', err);
      }
      if (setStatus) {
        updateStatus(null, false);
      }
    }

    function applyDraft(draft) {
      if (!draft) return;
      if (fileNameInput && typeof draft.fileName === 'string') {
        fileNameInput.value = draft.fileName;
      }
      if (descriptionInput && typeof draft.description === 'string') {
        descriptionInput.value = draft.description;
      }
      if (tagsInput && typeof draft.tags === 'string') {
        tagsInput.value = draft.tags;
      }
      if (typeof draft.language === 'string' && languageSelect) {
        const optionExists = !!Array.from(languageSelect.options || []).find((opt) => opt.value === draft.language);
        if (optionExists) {
          languageSelect.value = draft.language;
          languageSelect.dispatchEvent(new Event('change'));
        }
      }
      if (typeof draft.code === 'string') {
        setEditorContent(draft.code, codeTextarea);
      }
      if (sourceUrlInput && typeof draft.sourceUrl === 'string') {
        sourceUrlInput.value = draft.sourceUrl;
        if (sourceUrlTouched) {
          sourceUrlTouched.value = draft.sourceUrl.trim() ? 'edited' : '0';
        }
        if (fileFormManager && fileFormManager.sourceUrlManager) {
          fileFormManager.sourceUrlManager.setOpen(!!draft.sourceUrl.trim(), { focus: false, markTouched: !!draft.sourceUrl.trim() });
        }
      }
    }

    function updateStatus(savedAt, offerRestore) {
      if (!statusEl) return;
      if (offerRestore && savedAt) {
        statusEl.textContent = `נמצאה טיוטה שמורה מ-${formatTime(savedAt)}`;
        return;
      }
      if (!savedAt) {
        statusEl.textContent = 'טיוטה טרם נשמרה';
        return;
      }
      statusEl.textContent = `נשמר לאחרונה ב-${formatTime(savedAt)}`;
    }

    function toggleRestoreButton(show) {
      if (!restoreBtn) return;
      restoreBtn.hidden = !show;
      restoreBtn.disabled = !show;
    }

    function toggleDiscardButton(disable) {
      if (!discardBtn) return;
      discardBtn.disabled = !!disable;
    }
  });
})();


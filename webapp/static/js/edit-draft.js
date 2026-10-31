(function () {
  // העזרים המשותפים: webapp/static/js/utils/editor-page-utils.js, שנטען לפני הקובץ הזה.
  const {
    waitFor, debounce, formatTime, getEditorContent, setEditorContent, storageAvailable,
  } = window.EditorPageUtils;

  const supportsStorage = storageAvailable();

  function consumeServerConfirmedDraftClear() {
    // איפוס טיוטה רק אחרי שמירה מוצלחת (אישור מהשרת דרך data-clear-edit-draft-id בעמוד הצפייה).
    try {
      if (!supportsStorage) return;
      const meta = document.getElementById('fileMeta');
      const clearId = meta && meta.dataset ? meta.dataset.clearEditDraftId : '';
      const id = String(clearId || '').trim();
      if (!id) return;
      const key = `editDraft.v1:${id}`;
      localStorage.removeItem(key);
    } catch (_) {}
  }

  document.addEventListener('DOMContentLoaded', async () => {
    consumeServerConfirmedDraftClear();

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
        toggleRestoreButton(false);
        toggleDiscardButton(true);
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


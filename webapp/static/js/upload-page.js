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

  document.addEventListener('DOMContentLoaded', async () => {
    const form = document.getElementById('uploadForm');
    if (!form) {
      return;
    }

    const fileNameInput = document.querySelector('input[name="file_name"]');
    const descriptionInput = document.querySelector('input[name="description"]');
    const tagsInput = document.querySelector('input[name="tags"]');
    const languageSelect = document.getElementById('languageSelect');
    const codeTextarea = document.querySelector('textarea[name="code"]');
    const sourceUrlInput = document.getElementById('sourceUrlInput');
    const sourceUrlTouched = document.getElementById('sourceUrlTouched');

    // --- טיוטה מקומית (Upload בלבד) ---
    const statusEl = document.getElementById('draftSaveStatus');
    const clearBtn = document.getElementById('clearDraftBtn');
    const storageKey = 'uploadDraft.v1';

    const supportsStorage = (() => {
      try {
        const testKey = '__uploadDraftTest__';
        localStorage.setItem(testKey, 'ok');
        localStorage.removeItem(testKey);
        return true;
      } catch (_) {
        return false;
      }
    })();

    if (!supportsStorage) {
      if (statusEl) statusEl.textContent = 'שמירה מקומית לא נתמכת בדפדפן';
      if (clearBtn) clearBtn.disabled = true;
      return;
    }

    const uploadSucceeded = form.getAttribute('data-upload-success') === '1';
    const shouldResetDraft = form.getAttribute('data-reset-draft') === '1';
    if (uploadSucceeded || shouldResetDraft) {
      removeDraft(true);
    }

    const fileFormManager = await waitFor(() => window.fileFormManager, { timeoutMs: 2500, intervalMs: 100 });

    const initialState = collectState();
    let lastSnapshot = JSON.stringify(initialState);

    const prefilledFields = ['fileName', 'description', 'tags', 'code', 'sourceUrl'];
    const hasPrefill = prefilledFields.some((key) => {
      const val = (initialState[key] || '').trim();
      return val.length > 0;
    });

    const existingDraft = loadDraft();
    toggleClearButton(!existingDraft);
    if (existingDraft && !hasPrefill) {
      applyDraft(existingDraft);
      lastSnapshot = JSON.stringify(collectState());
      updateStatus(existingDraft.savedAt);
    } else if (existingDraft && existingDraft.savedAt) {
      updateStatus(existingDraft.savedAt);
    } else {
      updateStatus(null);
    }

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

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        const confirmed = window.confirm('למחוק את הטיוטה המקומית ולהתחיל מחדש?');
        if (!confirmed) {
          return;
        }
        removeDraft(true);
        resetFormFields();
        lastSnapshot = JSON.stringify(collectState());
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

    function hasMeaningfulContent(state) {
      return ['fileName', 'description', 'tags', 'code', 'sourceUrl'].some((key) => {
        const val = (state[key] || '').trim();
        return val.length > 0;
      });
    }

    function saveDraft() {
      const state = collectState();
      const snapshot = JSON.stringify(state);
      if (snapshot === lastSnapshot) {
        return;
      }
      if (!hasMeaningfulContent(state)) {
        removeDraft(true);
        lastSnapshot = snapshot;
        return;
      }
      const payload = { ...state, savedAt: Date.now() };
      try {
        localStorage.setItem(storageKey, JSON.stringify(payload));
        lastSnapshot = snapshot;
        updateStatus(payload.savedAt);
        toggleClearButton(false);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[upload] failed to persist draft', err);
      }
    }

    function loadDraft() {
      try {
        const raw = localStorage.getItem(storageKey);
        if (!raw) return null;
        return JSON.parse(raw);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[upload] failed to load draft', err);
        return null;
      }
    }

    function removeDraft(setStatus) {
      try {
        localStorage.removeItem(storageKey);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[upload] failed to remove draft', err);
      }
      if (setStatus) {
        updateStatus(null);
      }
      toggleClearButton(true);
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

    function resetFormFields() {
      if (fileNameInput) fileNameInput.value = '';
      if (descriptionInput) descriptionInput.value = '';
      if (tagsInput) tagsInput.value = '';
      if (sourceUrlInput) sourceUrlInput.value = '';
      if (sourceUrlTouched) sourceUrlTouched.value = '0';
      setEditorContent('', codeTextarea);
      if (languageSelect) {
        languageSelect.value = 'text';
        languageSelect.dispatchEvent(new Event('change'));
      }
      if (fileFormManager && fileFormManager.sourceUrlManager) {
        fileFormManager.sourceUrlManager.setOpen(false, { focus: false, markTouched: false });
      }
    }

    function updateStatus(savedAt) {
      if (!statusEl) return;
      if (!savedAt) {
        statusEl.textContent = 'טיוטה טרם נשמרה';
        return;
      }
      statusEl.textContent = `נשמר לאחרונה ב-${formatTime(savedAt)}`;
    }

    function toggleClearButton(disable) {
      if (!clearBtn) return;
      clearBtn.disabled = !!disable;
    }
  });
})();


(function(){
  const api = {
    async listCollections() {
      const r = await fetch('/api/collections');
      return r.json();
    },
    async createCollection(payload){
      const r = await fetch('/api/collections', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload||{})});
      return r.json();
    },
    async getCollection(id){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}`);
      return r.json();
    },
    async updateCollection(id, payload){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload||{})});
      return r.json();
    },
    async deleteCollection(id){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}`, {method:'DELETE'});
      return r.json();
    },
    async getItems(id, page=1, perPage=20){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/items?page=${page}&per_page=${perPage}&include_computed=true`);
      return r.json();
    },
    async addItems(id, items){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/items`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({items})});
      return r.json();
    },
    async removeItems(id, items){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/items`, {method:'DELETE', headers:{'Content-Type':'application/json'}, body: JSON.stringify({items})});
      return r.json();
    },
    async reorder(id, order){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/reorder`, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({order})});
      return r.json();
    },
    async updateShare(id, payload){
      const r = await fetch(`/api/collections/${encodeURIComponent(id)}/share`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload||{})});
      return r.json();
    },
    async updateItemTags(itemId, tags) {
      const r = await fetch(`/api/collections/items/${encodeURIComponent(itemId)}/tags`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tags }),
      });
      return r.json();
    },
    async getTagsMetadata() {
      const r = await fetch('/api/collections/tags/metadata');
      return r.json();
    },
    async logTagsFiltered(collectionId, tags) {
      const r = await fetch('/api/collections/tags/filtered', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ collection_id: collectionId, tags }),
      });
      return r.json();
    },
    // --- Folder API ---
    async createFolder(collectionId, payload){
      const r = await fetch(`/api/collections/${encodeURIComponent(collectionId)}/folders`, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload||{})});
      return r.json();
    },
    async updateFolder(collectionId, folderName, payload){
      const r = await fetch(`/api/collections/${encodeURIComponent(collectionId)}/folders/${encodeURIComponent(folderName)}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload||{})});
      return r.json();
    },
    async deleteFolder(collectionId, folderName){
      const r = await fetch(`/api/collections/${encodeURIComponent(collectionId)}/folders/${encodeURIComponent(folderName)}`, {method:'DELETE'});
      return r.json();
    },
    async reorderFolders(collectionId, order){
      const r = await fetch(`/api/collections/${encodeURIComponent(collectionId)}/folders/reorder`, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({order})});
      return r.json();
    },
    async moveItemFolder(collectionId, payload){
      const r = await fetch(`/api/collections/${encodeURIComponent(collectionId)}/items/move-folder`, {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      return r.json();
    },
    async updateWorkspaceState(itemId, state){
      const r = await fetch(`/api/workspace/items/${encodeURIComponent(itemId)}/state`, {
        method: 'PATCH',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ state }),
      });
      let data = null;
      try {
        data = await r.json();
      } catch (_err) {
        data = null;
      }
      if (!r.ok || !data || data.ok === false) {
        const err = (data && data.error) || 'workspace_state_update_failed';
        const error = new Error(err);
        error.code = err;
        throw error;
      }
      return data;
    },
  };

  const ALLOWED_ICONS = [
    "📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡","⭐","🔖","🚀",
    "🖥️","💼","🖱️","⌨️","📱","💻","🖨️","📊","📈","📉","🔧","🛠️",
    "🛒","📦","⚡","📢","🤖","💬","📨","🔔","🧰","🎵","🎥","📤","📥","📜","🪄"
  ];

  const ALLOWED_FOLDER_ICONS = [
    "📁","📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡",
    "⭐","🔖","🚀","🖥️","💼","📦","⚡","🤖","🧰","📜"
  ];

  /**
   * הצגת הודעת Toast
   * @param {string} message - ההודעה להצגה
   * @param {string} type - סוג ההודעה: 'info', 'success', 'error', 'warning'
   */
  function showToast(message, type = 'info') {
    // נסה להשתמש ב-toast גלובלי אם קיים
    if (typeof window.showNotification === 'function') {
      window.showNotification(message, type);
      return;
    }
    // fallback - יצירת toast פשוט
    const toast = document.createElement('div');
    const bgColor = {
      success: '#10b981',
      error: '#ef4444',
      warning: '#f59e0b',
      info: '#3b82f6'
    }[type] || '#3b82f6';
    
    toast.textContent = message;
    toast.style.cssText = `
      position: fixed;
      bottom: 2rem;
      left: 50%;
      transform: translateX(-50%);
      padding: 0.75rem 1.5rem;
      background: ${bgColor};
      color: white;
      border-radius: 8px;
      z-index: 20000;
      font-size: 0.9rem;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
      direction: rtl;
    `;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
  }

  // תגיות זמינות (יטען מהשרת)
  let TAGS_METADATA = null;
  let TAGS_FEATURE_ENABLED = true;
  // סרגל תגיות (סינון/מיון/ייבוא/ייצוא/בחירה מרובה) – ניתן לכיבוי ברמת מסך
  let TAGS_TOOLBAR_ENABLED = true;
  const MAX_TAGS_PER_ITEM = 10;

  // מטא-מידע על תגיות (default עד שיטען מהשרת)
  const DEFAULT_TAGS_METADATA = {
    allowed_tags: [
      "🐢", "🔥", "🔮", "♥️", "💎", "🔐", "💭",
      "⏸️", "🎯", "🐛", "🗄️", "🧪",
      "1️⃣", "2️⃣", "3️⃣",
    ],
    categories: {
      priority: ["🐢", "🔥"],
      sentiment: ["🔮", "♥️", "💎"],
      security: ["🔐"],
      status: ["💭", "⏸️", "🎯"],
      category: ["🐛", "🗄️", "🧪"],
      order: ["1️⃣", "2️⃣", "3️⃣"],
    },
    metadata: {
      "🐢": { name_he: "לא דחוף", name_en: "low priority", category: "priority" },
      "🔥": { name_he: "דחוף", name_en: "urgent", category: "priority" },
      "🔮": { name_he: "קסום", name_en: "magic", category: "sentiment" },
      "♥️": { name_he: "מועדף", name_en: "favorite", category: "sentiment" },
      "💎": { name_he: "איכותי", name_en: "quality", category: "sentiment" },
      "🔐": { name_he: "סודי", name_en: "secret", category: "security" },
      "💭": { name_he: "רעיון", name_en: "idea", category: "status" },
      "⏸️": { name_he: "מושהה", name_en: "paused", category: "status" },
      "🎯": { name_he: "מטרה", name_en: "goal", category: "status" },
      "🐛": { name_he: "באג", name_en: "bug", category: "category" },
      "🗄️": { name_he: "דאטה-בייס", name_en: "database", category: "category" },
      "🧪": { name_he: "ניסיוני", name_en: "experimental", category: "category" },
      "1️⃣": { name_he: "ראשון", name_en: "first", category: "order" },
      "2️⃣": { name_he: "שני", name_en: "second", category: "order" },
      "3️⃣": { name_he: "שלישי", name_en: "third", category: "order" },
    },
  };

  let currentTagsFilter = [];
  let currentTagsSort = 'default';
  let lastCollectionItems = [];
  let lastCollectionMeta = null;
  let lastCollectionIsWorkspace = false;
  let lastCollectionId = '';
  let lastCollectionTotal = 0;
  let lastCollectionPage = 1;
  let lastCollectionPerPage = 200;
  let isLoadingMoreItems = false;
  const tagsFilterCache = new Map();

  const resolvedFileIdCache = new Map();
  const RECYCLE_BIN_ALERT = 'הקובץ הועבר לסל מיחזור, ניתן לשחזר דרך סל מיחזור דרך הבוט';
  let currentCollectionId = '';
  let isBulkMode = false;
  let initialCollectionIdConsumed = false;
  const WORKSPACE_STATE_META = {
    todo: { label: 'לטיפול', description: 'משימות שטרם התחלת', shortcut: 'Shift+1' },
    in_progress: { label: 'בתהליך', description: 'עבודה בתהליך', shortcut: 'Shift+2' },
    done: { label: 'הושלם', description: 'סיימת לטפל', shortcut: 'Shift+3' },
  };
  const WORKSPACE_STATE_ORDER = Object.keys(WORKSPACE_STATE_META);
  let workspaceBoardCtx = null;
  let workspaceActiveCard = null;
  let activeDragContext = null;
  let workspaceDragPointer = null;
  let workspacePointerCleanup = null;
  let workspacePointerOwnerToken = null;
  let sidebarContainerEl = null;
  let sidebarShellEl = null;
  let sidebarHoverBtn = null;

  function getRemoveItemWithAnimation(){
    try {
      return (typeof window !== 'undefined' && typeof window.removeItemWithAnimation === 'function')
        ? window.removeItemWithAnimation
        : null;
    } catch (_err) {
      return null;
    }
  }

  async function removeElementWithAnimation(el){
    if (!el) {
      return;
    }
    const fn = getRemoveItemWithAnimation();
    if (fn) {
      try {
        await fn(el);
        return;
      } catch (_err) {
        // נפילה לאחור למחיקה רגילה
      }
    }
    try {
      el.remove();
    } catch (_err) {
      try { el.parentNode && el.parentNode.removeChild(el); } catch (_err2) {}
    }
  }

  function markElementAsNew(el){
    if (!el || !el.classList) return;
    el.classList.add('is-new');
    const cleanup = () => {
      try { el.classList.remove('is-new'); } catch (_err) {}
    };
    el.addEventListener('animationend', cleanup, { once: true });
    setTimeout(cleanup, 800);
  }

  function readInitialCollectionId() {
    let value = '';
    try {
      const container = document.getElementById('collectionsContent');
      if (container && container.hasAttribute('data-default-collection-id')) {
        value = container.getAttribute('data-default-collection-id') || '';
      }
    } catch (_err) {}
    if (!value) {
      try {
        const params = new URLSearchParams(window.location.search || '');
        value = params.get('collection') || '';
      } catch (_err) {}
    }
    if (!value) {
      try {
        const match = String(window.location.pathname || '').match(/^\/collections\/([^\/?#]+)/);
        if (match && match[1]) {
          value = decodeURIComponent(match[1]);
        }
      } catch (_err) {}
    }
    return value ? String(value).trim() : '';
  }

  function consumeInitialCollectionId() {
    if (initialCollectionIdConsumed) {
      return '';
    }
    initialCollectionIdConsumed = true;
    const val = readInitialCollectionId();
    if (val) {
      try {
        const container = document.getElementById('collectionsContent');
        if (container) {
          container.removeAttribute('data-default-collection-id');
        }
      } catch (_err) {}
    }
    return val;
  }

  function initTagsFeatureFlag() {
    try {
      const container = document.getElementById('collectionsContent');
      if (container && container.hasAttribute('data-tags-enabled')) {
        const raw = container.getAttribute('data-tags-enabled') || '';
        TAGS_FEATURE_ENABLED = String(raw).trim() !== '0';
      }
    } catch (_err) {}
  }

  function initTagsToolbarFlag() {
    try {
      const container = document.getElementById('collectionsContent');
      if (container && container.hasAttribute('data-tags-toolbar-enabled')) {
        const raw = container.getAttribute('data-tags-toolbar-enabled') || '';
        TAGS_TOOLBAR_ENABLED = String(raw).trim() !== '0';
      }
    } catch (_err) {}
  }

  function resolveTagsMetadata() {
    return TAGS_METADATA || DEFAULT_TAGS_METADATA;
  }

  function getTagLabel(tag) {
    const meta = resolveTagsMetadata();
    const info = (meta && meta.metadata && meta.metadata[tag]) || {};
    let lang = 'he';
    try {
      lang = String(document.documentElement.lang || 'he').toLowerCase();
    } catch (_err) {
      lang = 'he';
    }
    const labelKey = lang.startsWith('en') ? 'name_en' : 'name_he';
    return info[labelKey] || info.name_he || info.name_en || tag;
  }

  /**
   * אתחול מטאדאטה של תגיות
   */
  async function initTagsMetadata() {
    if (!TAGS_FEATURE_ENABLED) {
      TAGS_METADATA = DEFAULT_TAGS_METADATA;
      return;
    }
    try {
      const resp = await api.getTagsMetadata();
      if (resp && resp.ok) {
        TAGS_METADATA = resp;
      } else {
        TAGS_METADATA = DEFAULT_TAGS_METADATA;
      }
    } catch (err) {
      console.error('Failed to load tags metadata:', err);
      TAGS_METADATA = DEFAULT_TAGS_METADATA;
    }
  }

  /**
   * בניית HTML לתגיות של פריט
   * @param {Array} tags - רשימת תגיות (אימוג'ים)
   * @param {String} itemId - מזהה הפריט
   * @returns {String} HTML
   */
  function buildItemTagsHtml(tags, itemId) {
    if (!TAGS_FEATURE_ENABLED) {
      return '';
    }
    const safeTags = Array.isArray(tags) ? tags : [];
    if (!safeTags || safeTags.length === 0) {
      return '';
    }

    const meta = resolveTagsMetadata();
    const tagsHtml = safeTags.map(tag => {
      const tooltip = getTagLabel(tag);
      return `<span class="item-tag" data-tag="${escapeHtml(tag)}" title="${escapeHtml(tooltip)}">${escapeHtml(tag)}</span>`;
    }).join('');

    return `<div class="item-tags" data-item-id="${escapeHtml(itemId || '')}">${tagsHtml}</div>`;
  }

  function collectTagsFromElement(itemEl) {
    if (!itemEl) return [];
    const tagsContainer = itemEl.querySelector('.item-tags');
    if (!tagsContainer) {
      return [];
    }
    return Array.from(tagsContainer.querySelectorAll('.item-tag'))
      .map(el => el.dataset.tag)
      .filter(Boolean);
  }

  /**
   * פתיחת מודל לעריכת תגיות של פריט
   * @param {String} itemId - מזהה הפריט
   * @param {Array} currentTags - תגיות נוכחיות
   */
  function openTagsEditorModal(itemId, currentTags = [], options = {}) {
    if (!TAGS_FEATURE_ENABLED) {
      showToast('תיוג קבצים כבוי כרגע', 'warning');
      return;
    }
    const meta = resolveTagsMetadata();
    const uniqueTags = Array.from(new Set((currentTags || []).filter(Boolean)));
    const modalTitle = options.title || 'עריכת תגיות';
    const saveLabel = options.saveLabel || 'שמור';
    const onSave = typeof options.onSave === 'function' ? options.onSave : null;

    // בניית HTML של בוחר תגיות לפי קטגוריות
    let categoriesHtml = '';
    Object.entries(meta.categories || {}).forEach(([catKey, catTags]) => {
      const categoryNames = {
        priority: 'עדיפות',
        sentiment: 'סנטימנט',
        security: 'אבטחה',
        status: 'סטטוס',
        category: 'קטגוריה',
        order: 'סדר',
      };

      const catName = categoryNames[catKey] || catKey;
      const tagsHtml = (catTags || []).map(tag => {
        const selected = uniqueTags.includes(tag) ? 'selected' : '';
        const label = getTagLabel(tag);
        return `
          <button class="tag-option ${selected}"
                  data-tag="${escapeHtml(tag)}"
                  role="checkbox"
                  aria-checked="${selected ? 'true' : 'false'}"
                  aria-label="${escapeHtml(label)}">
            ${escapeHtml(tag)}
            <span class="tag-name">${escapeHtml(label)}</span>
            <span class="sr-only">${escapeHtml(label)}</span>
          </button>
        `;
      }).join('');

      categoriesHtml += `
        <div class="tag-category">
          <h4 class="tag-category-title">${escapeHtml(catName)}</h4>
          <div class="tag-category-options">
            ${tagsHtml}
          </div>
        </div>
      `;
    });

    const modalHtml = `
      <div class="tags-editor-modal" id="tagsEditorModal" role="dialog" aria-modal="true" aria-label="עריכת תגיות">
        <div class="modal-content">
          <div class="modal-header">
            <h3>${escapeHtml(modalTitle)}</h3>
            <button class="modal-close" aria-label="סגירה">&times;</button>
          </div>
          <div class="modal-body">
            <div class="tags-selected-preview" aria-live="polite">
              <strong>תגיות נבחרות:</strong>
              <div class="selected-tags-container">
                ${uniqueTags.length > 0
                  ? uniqueTags.map(t => `<span class="selected-tag">${escapeHtml(t)}</span>`).join('')
                  : '<span class="no-tags">לא נבחרו תגיות</span>'}
              </div>
            </div>
            <div class="tags-categories">
              ${categoriesHtml}
            </div>
          </div>
          <div class="modal-footer">
            <button class="btn btn-primary" id="saveTagsBtn">${escapeHtml(saveLabel)}</button>
            <button class="btn btn-secondary modal-close">ביטול</button>
          </div>
        </div>
      </div>
    `;

    // הוספת המודל ל-DOM
    const existingModal = document.getElementById('tagsEditorModal');
    if (existingModal) existingModal.remove();

    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modal = document.getElementById('tagsEditorModal');
    if (!modal) {
      return;
    }

    const previousFocus = document.activeElement;

    // Selected tags state
    let selectedTags = [...uniqueTags];

    // Event listeners לבחירת תגיות
    modal.querySelectorAll('.tag-option').forEach(btn => {
      btn.addEventListener('click', () => {
        const tag = btn.dataset.tag;
        if (!tag) return;

        if (selectedTags.includes(tag)) {
          // הסרת תגית
          selectedTags = selectedTags.filter(t => t !== tag);
          btn.classList.remove('selected');
          btn.setAttribute('aria-checked', 'false');
        } else {
          // הוספת תגית
          if (selectedTags.length >= MAX_TAGS_PER_ITEM) {
            showToast(`ניתן לבחור עד ${MAX_TAGS_PER_ITEM} תגיות`, 'warning');
            return;
          }
          selectedTags.push(tag);
          btn.classList.add('selected');
          btn.setAttribute('aria-checked', 'true');
        }

        // עדכון תצוגת תגיות נבחרות
        updateSelectedTagsPreview();
      });
    });

    // עדכון תצוגה
    function updateSelectedTagsPreview() {
      const container = modal.querySelector('.selected-tags-container');
      if (!container) return;
      if (selectedTags.length === 0) {
        container.innerHTML = '<span class="no-tags">לא נבחרו תגיות</span>';
      } else {
        container.innerHTML = selectedTags
          .map(t => `<span class="selected-tag">${escapeHtml(t)}</span>`)
          .join('');
      }
    }

    const closeModal = () => {
      modal.remove();
      if (previousFocus && typeof previousFocus.focus === 'function') {
        try { previousFocus.focus(); } catch (_err) {}
      }
    };

    // שמירת תגיות
    const saveBtn = modal.querySelector('#saveTagsBtn');
    if (saveBtn) {
      const debouncedSave = debounce(async () => {
        try {
          if (onSave) {
            await onSave(selectedTags);
            closeModal();
          } else {
            const resp = await api.updateItemTags(itemId, selectedTags);
            if (resp && resp.ok) {
              showToast('התגיות עודכנו בהצלחה', 'success');
              closeModal();
              await renderCollectionItems(currentCollectionId);
            } else {
              showToast((resp && resp.error) || 'שגיאה בעדכון תגיות', 'error');
            }
          }
        } catch (err) {
          console.error('Error updating tags:', err);
          showToast('שגיאה בעדכון תגיות', 'error');
        }
      }, 300);
      saveBtn.addEventListener('click', () => debouncedSave());
    }

    // סגירת מודל
    modal.querySelectorAll('.modal-close').forEach(btn => {
      btn.addEventListener('click', () => closeModal());
    });

    // סגירה בלחיצה מחוץ למודל - מעוכב כדי למנוע סגירה מיידית מהלחיצה המקורית
    setTimeout(() => {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
      });
    }, 100);

    // סגירה ב-Escape
    modal.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        closeModal();
      }
    });

    // הצגת המודל
    modal.style.display = 'flex';
    const firstTag = modal.querySelector('.tag-option');
    if (firstTag && typeof firstTag.focus === 'function') {
      firstTag.focus();
    }
  }

  /**
   * סינון פריטים לפי תגיות
   * @param {Array} items - כל הפריטים
   * @param {Array} filterTags - תגיות לסינון
   * @returns {Array} פריטים מסוננים
   */
  function filterItemsByTags(items, filterTags) {
    if (!filterTags || filterTags.length === 0) {
      return items;
    }
    return (items || []).filter(item => {
      const itemTags = item.tags || [];
      // בדיקה אם הפריט מכיל לפחות אחת מהתגיות
      return filterTags.some(tag => itemTags.includes(tag));
    });
  }

  function sortItemsByTags(items, mode) {
    if (!Array.isArray(items) || !items.length) {
      return items || [];
    }
    if (!mode || mode === 'default') {
      return items.slice();
    }
    const priorityWeight = (tags) => {
      if (tags.includes('🔥')) return 0;
      if (tags.includes('🐢')) return 1;
      return 2;
    };
    const orderWeight = (tags) => {
      if (tags.includes('1️⃣')) return 1;
      if (tags.includes('2️⃣')) return 2;
      if (tags.includes('3️⃣')) return 3;
      return 99;
    };
    return items
      .map((item, idx) => ({ item, idx }))
      .sort((a, b) => {
        const tagsA = a.item.tags || [];
        const tagsB = b.item.tags || [];
        let cmp = 0;
        if (mode === 'priority') {
          cmp = priorityWeight(tagsA) - priorityWeight(tagsB);
        } else if (mode === 'order') {
          cmp = orderWeight(tagsA) - orderWeight(tagsB);
        }
        if (cmp !== 0) return cmp;
        const nameA = String(a.item.file_name || '').toLowerCase();
        const nameB = String(b.item.file_name || '').toLowerCase();
        if (nameA < nameB) return -1;
        if (nameA > nameB) return 1;
        return a.idx - b.idx;
      })
      .map(entry => entry.item);
  }

  function buildTagsFilterCacheKey(filterTags, sortMode) {
    const tagsKey = (filterTags || []).slice().sort().join('|');
    return `${tagsKey}::${sortMode || 'default'}`;
  }

  function applyTagsFilterAndSort(items) {
    if (!TAGS_FEATURE_ENABLED || !TAGS_TOOLBAR_ENABLED) {
      return items || [];
    }
    const key = buildTagsFilterCacheKey(currentTagsFilter, currentTagsSort);
    if (tagsFilterCache.has(key)) {
      return tagsFilterCache.get(key);
    }
    const filtered = filterItemsByTags(items || [], currentTagsFilter);
    const sorted = sortItemsByTags(filtered, currentTagsSort);
    tagsFilterCache.set(key, sorted);
    return sorted;
  }

  function buildTagsFilterPanelHtml() {
    const meta = resolveTagsMetadata();
    let categoriesHtml = '';
    Object.entries(meta.categories || {}).forEach(([catKey, catTags]) => {
      const categoryNames = {
        priority: 'עדיפות',
        sentiment: 'סנטימנט',
        security: 'אבטחה',
        status: 'סטטוס',
        category: 'קטגוריה',
        order: 'סדר',
      };
      const catName = categoryNames[catKey] || catKey;
      const tagsHtml = (catTags || []).map(tag => {
        const selected = currentTagsFilter.includes(tag) ? 'selected' : '';
        const label = getTagLabel(tag);
        return `
          <button type="button" class="tag-filter-option ${selected}"
                  data-tag="${escapeHtml(tag)}"
                  aria-pressed="${selected ? 'true' : 'false'}"
                  aria-label="${escapeHtml(label)}">
            ${escapeHtml(tag)}
            <span class="tag-name">${escapeHtml(label)}</span>
          </button>
        `;
      }).join('');
      categoriesHtml += `
        <div class="tag-category">
          <h4 class="tag-category-title">${escapeHtml(catName)}</h4>
          <div class="tag-category-options">
            ${tagsHtml}
          </div>
        </div>
      `;
    });
    return categoriesHtml;
  }

  function buildTagsToolbarHtml() {
    if (!TAGS_FEATURE_ENABLED || !TAGS_TOOLBAR_ENABLED) {
      return '';
    }
    const selectedTags = currentTagsFilter || [];
    const filterLabel = selectedTags.length ? `סינון (${selectedTags.length})` : 'סינון תגיות';
    const sortOptions = [
      { value: 'default', label: 'מיון רגיל' },
      { value: 'priority', label: 'מיון לפי עדיפות' },
      { value: 'order', label: 'מיון לפי סדר' },
    ];
    const selectedTagsHtml = selectedTags.length
      ? selectedTags.map(t => `<span class="selected-tag-chip">${escapeHtml(t)}</span>`).join('')
      : '';

    return `
      <div class="tags-toolbar" data-tags-toolbar="1">
        <div class="tags-toolbar__row">
          <button type="button" class="btn btn-secondary btn-sm tags-filter-toggle" aria-expanded="false">${escapeHtml(filterLabel)}</button>
          <select class="tags-sort-select" aria-label="מיון תגיות">
            ${sortOptions.map(opt => `<option value="${opt.value}" ${currentTagsSort === opt.value ? 'selected' : ''}>${escapeHtml(opt.label)}</option>`).join('')}
          </select>
          <button type="button" class="btn btn-secondary btn-sm tags-clear-filter" ${selectedTags.length ? '' : 'disabled'}>נקה סינון</button>
          <button type="button" class="btn btn-secondary btn-sm tags-export-btn">ייצוא תגיות</button>
          <label class="btn btn-secondary btn-sm tags-import-btn">
            ייבוא תגיות
            <input class="tags-import-input" type="file" accept=".csv,application/json" hidden>
          </label>
          <button type="button" class="btn btn-secondary btn-sm tags-bulk-toggle">${isBulkMode ? 'בטל בחירה' : 'בחירה מרובה'}</button>
          <button type="button" class="btn btn-secondary btn-sm tags-bulk-edit" ${isBulkMode ? '' : 'disabled'}>עדכן תגיות</button>
        </div>
        <div class="tags-filter-panel" data-tags-filter-panel="1" hidden>
          ${buildTagsFilterPanelHtml()}
        </div>
        <div class="tags-selected-summary" data-tags-summary="1">
          ${selectedTagsHtml}
        </div>
      </div>
    `;
  }

  function setBulkMode(container, enabled) {
    isBulkMode = !!enabled;
    if (container) {
      container.classList.toggle('bulk-mode', isBulkMode);
      if (!isBulkMode) {
        container.querySelectorAll('.item-select:checked').forEach((cb) => {
          cb.checked = false;
        });
      }
    }
  }

  function getSelectedItemIds(container) {
    if (!container) return [];
    return Array.from(container.querySelectorAll('.item-select:checked'))
      .map(cb => cb.getAttribute('data-item-id'))
      .filter(Boolean);
  }

  function updateBulkActionsState(toolbar, container) {
    if (!toolbar) return;
    const bulkEditBtn = toolbar.querySelector('.tags-bulk-edit');
    if (!bulkEditBtn) return;
    const selected = getSelectedItemIds(container);
    bulkEditBtn.disabled = selected.length === 0;
  }

  function downloadFile(filename, content, mimeType) {
    try {
      const blob = new Blob([content], { type: mimeType || 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename || 'download.txt';
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (_err) {
      showToast('שגיאה בהורדת הקובץ', 'error');
    }
  }

  function escapeCsvField(value) {
    const raw = String(value == null ? '' : value);
    return `"${raw.replace(/"/g, '""')}"`;
  }

  async function fetchAllCollectionItems(collectionId, perPage = 200) {
    const allItems = [];
    let page = 1;
    while (true) {
      const resp = await api.getItems(collectionId, page, perPage);
      if (!resp || !resp.ok) {
        throw new Error((resp && resp.error) || 'שגיאה בטעינת פריטים');
      }
      const items = Array.isArray(resp.items) ? resp.items : [];
      allItems.push(...items);
      const total = Number(resp.total_items || resp.total_manual || items.length);
      if (allItems.length >= total || items.length === 0) {
        break;
      }
      page += 1;
    }
    return allItems;
  }

  async function exportCollectionWithTags(collectionId) {
    try {
      const allItems = await fetchAllCollectionItems(collectionId, 200);
      const rows = allItems.map(item => {
        const fileName = String(item.file_name || '');
        const tags = (item.tags || []).join(',');
        const note = String(item.note || '');
        return [
          escapeCsvField(fileName),
          escapeCsvField(tags),
          escapeCsvField(note),
        ].join(',');
      });
      const csv = ['file_name,tags,note', ...rows].join('\n');
      downloadFile('collection_export.csv', csv, 'text/csv;charset=utf-8');
      showToast('היצוא הושלם', 'success');
    } catch (err) {
      console.error('Export error:', err);
      showToast('שגיאה בייצוא תגיות', 'error');
    }
  }

  function parseCsvLine(line) {
    const result = [];
    let current = '';
    let inQuotes = false;
    for (let i = 0; i < line.length; i += 1) {
      const ch = line[i];
      if (ch === '"') {
        if (inQuotes && line[i + 1] === '"') {
          current += '"';
          i += 1;
        } else {
          inQuotes = !inQuotes;
        }
      } else if (ch === ',' && !inQuotes) {
        result.push(current);
        current = '';
      } else {
        current += ch;
      }
    }
    result.push(current);
    return result;
  }

  async function importCollectionWithTags(collectionId, file, container) {
    if (!file) return;
    try {
      const text = await file.text();
      const itemsByName = new Map();
      const allItems = await fetchAllCollectionItems(collectionId, 200);
      allItems.forEach((item) => {
        if (!item || !item.id) return;
        const key = String(item.file_name || '');
        if (!itemsByName.has(key)) {
          itemsByName.set(key, []);
        }
        itemsByName.get(key).push(item);
      });

      let rows = [];
      if (file.name.endsWith('.json')) {
        const parsed = JSON.parse(text || '[]');
        rows = Array.isArray(parsed) ? parsed : [];
      } else {
        const lines = text.split(/\r?\n/).filter(Boolean);
        const dataLines = lines[0] && lines[0].includes('file_name') ? lines.slice(1) : lines;
        rows = dataLines.map(line => {
          const [fileName, tagsRaw, note] = parseCsvLine(line);
          return { file_name: fileName, tags: tagsRaw, note };
        });
      }

      const updates = [];
      rows.forEach((row) => {
        const fileName = String(row.file_name || '').trim();
        if (!fileName) return;
        const tagsRaw = row.tags || row.tags_raw || '';
        const tags = String(tagsRaw).split(',').map(t => t.trim()).filter(Boolean);
        const targets = itemsByName.get(fileName) || [];
        targets.forEach((item) => {
          if (item && item.id) {
            updates.push({ itemId: item.id, tags });
          }
        });
      });

      if (!updates.length) {
        showToast('לא נמצאו פריטים לעדכון', 'warning');
        return;
      }
      const results = await Promise.all(updates.map(u => api.updateItemTags(u.itemId, u.tags)));
      const failed = results.filter(r => !r || !r.ok).length;
      if (failed > 0) {
        showToast(`עודכנו ${updates.length - failed}, נכשלו ${failed}`, 'warning');
      } else {
        showToast('התגיות יובאו בהצלחה', 'success');
      }
      await renderCollectionItems(collectionId);
    } catch (err) {
      console.error('Import error:', err);
      showToast('שגיאה בייבוא תגיות', 'error');
    } finally {
      if (container) {
        const input = container.querySelector('.tags-import-input');
        if (input) {
          input.value = '';
        }
      }
    }
  }

  function wireTagsToolbar(container, collectionId) {
    if (!container) return;
    const toolbar = container.querySelector('[data-tags-toolbar="1"]');
    if (!toolbar) return;

    const filterToggle = toolbar.querySelector('.tags-filter-toggle');
    const filterPanel = toolbar.querySelector('[data-tags-filter-panel="1"]');
    const clearBtn = toolbar.querySelector('.tags-clear-filter');
    const sortSelect = toolbar.querySelector('.tags-sort-select');
    const exportBtn = toolbar.querySelector('.tags-export-btn');
    const importInput = toolbar.querySelector('.tags-import-input');
    const bulkToggle = toolbar.querySelector('.tags-bulk-toggle');
    const bulkEdit = toolbar.querySelector('.tags-bulk-edit');

    const debouncedLogFilter = debounce(() => {
      if (currentTagsFilter.length) {
        api.logTagsFiltered(collectionId, currentTagsFilter).catch(() => {});
      }
    }, 300);

    const rerender = () => {
      renderCollectionItemsFromCache();
      debouncedLogFilter();
    };

    if (filterToggle && filterPanel) {
      filterToggle.addEventListener('click', () => {
        const isHidden = filterPanel.hasAttribute('hidden');
        if (isHidden) {
          filterPanel.removeAttribute('hidden');
          filterToggle.setAttribute('aria-expanded', 'true');
        } else {
          filterPanel.setAttribute('hidden', '');
          filterToggle.setAttribute('aria-expanded', 'false');
        }
      });
    }

    if (filterPanel) {
      filterPanel.querySelectorAll('.tag-filter-option').forEach((btn) => {
        btn.addEventListener('click', () => {
          const tag = btn.dataset.tag;
          if (!tag) return;
          if (currentTagsFilter.includes(tag)) {
            currentTagsFilter = currentTagsFilter.filter(t => t !== tag);
            btn.classList.remove('selected');
            btn.setAttribute('aria-pressed', 'false');
          } else {
            currentTagsFilter = [...currentTagsFilter, tag];
            btn.classList.add('selected');
            btn.setAttribute('aria-pressed', 'true');
          }
          tagsFilterCache.clear();
          rerender();
        });
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        currentTagsFilter = [];
        tagsFilterCache.clear();
        rerender();
      });
    }

    if (sortSelect) {
      sortSelect.addEventListener('change', () => {
        currentTagsSort = sortSelect.value || 'default';
        tagsFilterCache.clear();
        renderCollectionItemsFromCache();
      });
    }

    if (exportBtn) {
      exportBtn.addEventListener('click', () => exportCollectionWithTags(collectionId));
    }

    if (importInput) {
      importInput.addEventListener('change', () => {
        const file = importInput.files && importInput.files[0];
        if (file) {
          importCollectionWithTags(collectionId, file, toolbar);
        }
      });
    }

    if (bulkToggle) {
      bulkToggle.addEventListener('click', () => {
        setBulkMode(container, !isBulkMode);
        bulkToggle.textContent = isBulkMode ? 'בטל בחירה' : 'בחירה מרובה';
        updateBulkActionsState(toolbar, container);
      });
    }

    if (bulkEdit) {
      bulkEdit.addEventListener('click', () => {
        const selectedIds = getSelectedItemIds(container);
        if (!selectedIds.length) {
          showToast('לא נבחרו פריטים', 'warning');
          return;
        }
        const selectedItems = lastCollectionItems.filter(it => selectedIds.includes(String(it.id)));
        const unionTags = Array.from(new Set(selectedItems.flatMap(it => it.tags || [])));
        openTagsEditorModal('bulk', unionTags, {
          title: 'עדכון תגיות מרובה',
          saveLabel: 'עדכן',
          onSave: async (tags) => {
            const results = await Promise.all(selectedIds.map(id => api.updateItemTags(id, tags)));
            const failed = results.filter(r => !r || !r.ok).length;
            if (failed > 0) {
              showToast(`עודכנו ${selectedIds.length - failed}, נכשלו ${failed}`, 'warning');
            } else {
              showToast('התגיות עודכנו בהצלחה', 'success');
            }
            await renderCollectionItems(collectionId);
          },
        });
      });
    }

    container.addEventListener('change', (ev) => {
      const target = ev.target;
      if (target && target.classList && target.classList.contains('item-select')) {
        updateBulkActionsState(toolbar, container);
      }
    });
    updateBulkActionsState(toolbar, container);
  }

  function markSidebarSelection(cid){
    try {
      const list = document.querySelector('#collectionsSidebar #collectionsList');
      if (!list) return;
      const desired = String(cid || '').trim();
      list.querySelectorAll('.sidebar-item').forEach(btn => {
        const id = String(btn.getAttribute('data-id') || '').trim();
        btn.classList.toggle('active', desired && id === desired);
      });
    } catch (_err) {}
  }

  async function ensureCollectionsSidebar(){
    const root = document.getElementById('collectionsSidebar');
    if (!root) return;
    root.innerHTML = '<div class="loading">טוען…</div>';
    try {
      const data = await api.listCollections();
      if (!data || !data.ok) throw new Error(data && data.error || 'שגיאה');
        const items = (data.collections || []).map((c) => {
          const iconChar = (ALLOWED_ICONS.includes(c.icon) ? c.icon : (ALLOWED_ICONS[0] || '📂')) || '📂';
          const shareActive = !!(c.share && c.share.enabled);
          const countHtml = `${shareActive ? '<span class="share-indicator" title="האוסף משותף">🔗</span>' : ''}<span class="count-number">${Number(c.items_count || 0)}</span>`;
          return `
            <button class="sidebar-item" data-id="${c.id}">
              <span class="emoji">${escapeHtml(iconChar)}</span>
              <span class="name">${escapeHtml(c.name || 'ללא שם')}</span>
              <span class="count">${countHtml}</span>
            </button>
          `;
        }).join('');
      root.innerHTML = `
        <div class="sidebar-header">
          <div class="title">האוספים שלי</div>
          <button id="createCollectionBtn" class="btn btn-secondary btn-icon" title="צור אוסף חדש">➕</button>
        </div>
        <div class="sidebar-search">
          <input id="collectionsSearch" type="text" placeholder="חפש אוספים…"/>
        </div>
        <div class="sidebar-list" id="collectionsList">${items || '<div class="empty">אין אוספים</div>'}</div>
      `;
      wireSidebarHandlers(root);
      setupSidebarDropHandlers(root);
      if (currentCollectionId) {
        markSidebarSelection(currentCollectionId);
      } else {
        const pending = readInitialCollectionId();
        if (pending) {
          markSidebarSelection(pending);
        }
      }
      // התאמת טקסט דינמית לשמות אוספים ארוכים בסיידבר
      autoFitText('#collectionsSidebar .sidebar-item .name', { minPx: 12, maxPx: 16 });
    } catch (e) {
      root.innerHTML = '<div class="error">שגיאה בטעינת האוספים</div>';
    }
  }

  function setShareControlsBusy(toggleEl, copyBtn, busy){
    if (toggleEl) toggleEl.disabled = !!busy;
    if (copyBtn) {
      const hasUrl = ((copyBtn.getAttribute('data-url') || '').trim().length > 0);
      copyBtn.disabled = !!busy || !(toggleEl && toggleEl.checked) || !hasUrl;
    }
  }

  function resolvePublicUrl(col){
    try {
      if (!col) return '';
      const share = col.share || {};
      if (!share.enabled) return '';
      const direct = (col.public_url || col.publicUrl || '').trim();
      if (direct) return String(direct);
      const token = share.token || '';
      if (!token) return '';
      const base = String(window.location.origin || '').replace(/\/$/, '');
      return `${base}/collections/shared/${encodeURIComponent(String(token))}`;
    } catch (_err) {
      return '';
    }
  }

  function buildIconGridHtml(selected){
    const fallback = ALLOWED_ICONS[0] || '📂';
    const current = ALLOWED_ICONS.includes(selected) ? selected : fallback;
    return ALLOWED_ICONS.map(icon => {
      const isActive = icon === current;
      const cls = `icon-option${isActive ? ' active' : ''}`;
      return `<button type="button" class="${cls}" data-icon="${escapeHtml(icon)}">${escapeHtml(icon)}</button>`;
    }).join('');
  }

  function openCreateCollectionDialog(){
    if (document.querySelector('.collection-modal[data-modal="create-collection"]')) {
      return;
    }
    const defaultIcon = ALLOWED_ICONS[0] || '📂';
    const overlay = document.createElement('div');
    overlay.className = 'collection-modal';
    overlay.setAttribute('data-modal', 'create-collection');
    overlay.innerHTML = `
      <div class="collection-modal__backdrop"></div>
      <div class="collection-modal__panel" role="dialog" aria-modal="true">
        <h3 class="collection-modal__title">אוסף חדש</h3>
        <div class="collection-modal__field">
          <label for="collectionNameInput">שם האוסף</label>
          <input id="collectionNameInput" type="text" maxlength="80" placeholder="לדוגמה: קטעים מועדפים">
        </div>
        <div class="collection-modal__field">
          <label>בחר אייקון</label>
          <div class="icon-grid">${buildIconGridHtml(defaultIcon)}</div>
        </div>
        <div class="collection-modal__error" aria-live="polite"></div>
        <div class="collection-modal__actions">
          <button type="button" class="btn btn-secondary cancel">בטל</button>
          <button type="button" class="btn btn-primary confirm">צור</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const nameInput = overlay.querySelector('#collectionNameInput');
    const iconGrid = overlay.querySelector('.icon-grid');
    const errorBox = overlay.querySelector('.collection-modal__error');
    const cancelBtn = overlay.querySelector('.cancel');
    const confirmBtn = overlay.querySelector('.confirm');
    const backdrop = overlay.querySelector('.collection-modal__backdrop');
    let selectedIcon = defaultIcon;

    if (iconGrid) {
      iconGrid.addEventListener('click', (ev) => {
        const btn = ev.target.closest('.icon-option');
        if (!btn) return;
        selectedIcon = btn.getAttribute('data-icon') || defaultIcon;
        iconGrid.querySelectorAll('.icon-option').forEach(el => el.classList.toggle('active', el === btn));
      });
    }

    const showError = (msg) => {
      if (!errorBox) return;
      if (msg) {
        errorBox.textContent = msg;
        errorBox.style.display = 'block';
      } else {
        errorBox.textContent = '';
        errorBox.style.display = 'none';
      }
    };

    const cleanup = () => {
      document.removeEventListener('keydown', onKeydown);
      try { overlay.remove(); } catch (_err) {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      }
    };

    const close = () => {
      cleanup();
    };

    const onKeydown = (ev) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        close();
      } else if (ev.key === 'Enter' && document.activeElement === nameInput) {
        ev.preventDefault();
        confirmBtn && confirmBtn.click();
      }
    };

    document.addEventListener('keydown', onKeydown);
    backdrop && backdrop.addEventListener('click', close);
    cancelBtn && cancelBtn.addEventListener('click', close);

    if (confirmBtn) {
      confirmBtn.addEventListener('click', async () => {
        const nameRaw = String(nameInput && nameInput.value ? nameInput.value : '').trim();
        if (!nameRaw) {
          showError('יש להזין שם לאוסף');
          nameInput && nameInput.focus();
          return;
        }
        showError('');
        const iconToSend = ALLOWED_ICONS.includes(selectedIcon) ? selectedIcon : defaultIcon;
        confirmBtn.disabled = true;
        const originalLabel = confirmBtn.textContent || 'צור';
        confirmBtn.textContent = 'יוצר...';
        try {
          const res = await api.createCollection({ name: nameRaw.slice(0, 80), mode: 'manual', icon: iconToSend });
          if (!res || !res.ok) {
            showError((res && res.error) || 'שגיאה ביצירת האוסף');
            confirmBtn.disabled = false;
            confirmBtn.textContent = originalLabel;
            return;
          }
          close();
          ensureCollectionsSidebar();
          if (res.collection && res.collection.id) {
            await renderCollectionItems(res.collection.id);
          }
        } catch (_err) {
          showError('שגיאה ביצירת האוסף');
          confirmBtn.disabled = false;
          confirmBtn.textContent = originalLabel;
        }
      });
    }

    requestAnimationFrame(() => {
      if (nameInput) {
        nameInput.focus();
        nameInput.select();
      }
    });
  }

  function openIconPicker(initialIcon){
    if (document.querySelector('.collection-modal[data-modal="icon-picker"]')) {
      return Promise.resolve(null);
    }
    const defaultIcon = ALLOWED_ICONS.includes(initialIcon) ? initialIcon : (ALLOWED_ICONS[0] || '📂');
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'collection-modal';
      overlay.setAttribute('data-modal', 'icon-picker');
      overlay.innerHTML = `
        <div class="collection-modal__backdrop"></div>
        <div class="collection-modal__panel" role="dialog" aria-modal="true">
          <h3 class="collection-modal__title">בחר אייקון</h3>
          <div class="collection-modal__field">
            <div class="icon-grid">${buildIconGridHtml(defaultIcon)}</div>
          </div>
          <div class="collection-modal__actions">
            <button type="button" class="btn btn-secondary cancel">בטל</button>
            <button type="button" class="btn btn-primary confirm">שמור</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const iconGrid = overlay.querySelector('.icon-grid');
      const cancelBtn = overlay.querySelector('.cancel');
      const confirmBtn = overlay.querySelector('.confirm');
      const backdrop = overlay.querySelector('.collection-modal__backdrop');
      let selectedIcon = defaultIcon;

      if (iconGrid) {
        iconGrid.addEventListener('click', (ev) => {
          const btn = ev.target.closest('.icon-option');
          if (!btn) return;
          selectedIcon = btn.getAttribute('data-icon') || defaultIcon;
          iconGrid.querySelectorAll('.icon-option').forEach(el => el.classList.toggle('active', el === btn));
        });
      }

      const cleanup = () => {
        document.removeEventListener('keydown', onKeydown);
        try { overlay.remove(); } catch (_err) {
          if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        }
      };

      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        cleanup();
        resolve(value);
      };

      const onKeydown = (ev) => {
        if (ev.key === 'Escape') {
          ev.preventDefault();
          finish(null);
        } else if (ev.key === 'Enter') {
          ev.preventDefault();
          confirmBtn && confirmBtn.click();
        }
      };

      document.addEventListener('keydown', onKeydown);
      backdrop && backdrop.addEventListener('click', () => finish(null));
      cancelBtn && cancelBtn.addEventListener('click', () => finish(null));
      if (confirmBtn) {
        confirmBtn.addEventListener('click', () => {
          const iconToSend = ALLOWED_ICONS.includes(selectedIcon) ? selectedIcon : defaultIcon;
          finish(iconToSend);
        });
      }

      requestAnimationFrame(() => {
        const activeBtn = overlay.querySelector('.icon-option.active');
        if (activeBtn) {
          activeBtn.focus();
        }
      });
    });
  }

    function wireSidebarHandlers(root){
      const list = root.querySelector('#collectionsList');
      const search = root.querySelector('#collectionsSearch');
      const createBtn = root.querySelector('#createCollectionBtn');
      if (createBtn) {
        createBtn.addEventListener('click', () => {
          openCreateCollectionDialog();
        });
      }

    if (search) {
      search.addEventListener('input', () => {
        const q = (search.value||'').trim().toLowerCase();
        list.querySelectorAll('.sidebar-item').forEach(btn => {
          const name = (btn.querySelector('.name')?.textContent||'').toLowerCase();
          btn.style.display = (!q || name.includes(q)) ? '' : 'none';
        });
      });
    }

    if (list) {
      list.addEventListener('click', async (ev) => {
        const btn = ev.target.closest('.sidebar-item');
        if (!btn) return;
        const cid = btn.getAttribute('data-id');
        await renderCollectionItems(cid);
      });
    }
  }

  function updateSidebarShell(root){
    sidebarContainerEl = root || document.getElementById('collectionsSidebar');
    const host = sidebarContainerEl ? sidebarContainerEl.closest('.collections-sidebar') : null;
    sidebarShellEl = host || document.querySelector('.collections-sidebar');
  }

  function resolveSidebarContainer(){
    if (!sidebarContainerEl || !sidebarContainerEl.isConnected) {
      sidebarContainerEl = document.getElementById('collectionsSidebar');
    }
    return sidebarContainerEl;
  }

  function setSidebarDragVisual(active){
    if (!sidebarShellEl || !sidebarShellEl.isConnected) {
      sidebarShellEl = document.querySelector('.collections-sidebar');
    }
    if (!sidebarShellEl) return;
    sidebarShellEl.classList.toggle('drag-active', !!active);
  }

  function setSidebarDropHover(btn, mode){
    if (sidebarHoverBtn === btn) {
      if (!btn) return;
      if (mode === 'hover') {
        btn.classList.add('sidebar-item--drop-hover');
      } else {
        btn.classList.remove('sidebar-item--drop-hover');
      }
      return;
    }
    if (sidebarHoverBtn) {
      sidebarHoverBtn.classList.remove('sidebar-item--drop-ready', 'sidebar-item--drop-hover', 'sidebar-item--drop-busy');
    }
    sidebarHoverBtn = btn && btn.isConnected ? btn : null;
    if (sidebarHoverBtn) {
      sidebarHoverBtn.classList.add('sidebar-item--drop-ready');
      if (mode === 'hover') {
        sidebarHoverBtn.classList.add('sidebar-item--drop-hover');
      }
    }
  }

  function withSidebarDropBusy(btn){
    if (!btn || !btn.classList) {
      return () => {};
    }
    btn.classList.add('sidebar-item--drop-busy');
    return () => {
      btn.classList.remove('sidebar-item--drop-busy');
    };
  }

  function canDropOnSidebar(targetId){
    if (!activeDragContext) return false;
    const desired = String(targetId || '').trim();
    if (!desired) return false;
    return desired !== String(activeDragContext.collectionId || '').trim();
  }

  function beginCollectionItemDrag(row, collectionId, listEl, origin){
    if (isBulkMode) return;
    const payload = buildItemPayloadFromRow(row);
    if (!payload) return;
    const ctx = {
      element: row,
      collectionId: collectionId,
      container: listEl,
      payload,
      origin,
      dropInProgress: false,
    };
    if (origin === 'workspace') {
      ctx.workspacePointerToken = startWorkspacePointerTracking();
    }
    activeDragContext = ctx;
    setSidebarDragVisual(true);
  }

  function resetDragUi(){
    setSidebarDropHover(null);
    setSidebarDragVisual(false);
  }

  function clearActiveDragContext(){
    const ctx = activeDragContext;
    activeDragContext = null;
    resetDragUi();
    if (ctx && ctx.origin === 'workspace') {
      stopWorkspacePointerTracking(ctx.workspacePointerToken);
    }
  }

  function trackWorkspacePointer(event){
    if (!event) return;
    const { clientX, clientY } = event;
    if (typeof clientX !== 'number' || typeof clientY !== 'number') {
      return;
    }
    workspaceDragPointer = { x: clientX, y: clientY };
  }

  function consumeWorkspacePointer(){
    const point = workspaceDragPointer;
    workspaceDragPointer = null;
    return point;
  }

  function startWorkspacePointerTracking(){
    if (typeof document === 'undefined') {
      return null;
    }
    stopWorkspacePointerTracking();
    const token = Symbol('workspace-pointer');
    const handlers = [];
    const updateFromEvent = (ev) => {
      if (!ev) return;
      let pointX = null;
      let pointY = null;
      if (typeof ev.clientX === 'number' && typeof ev.clientY === 'number') {
        pointX = ev.clientX;
        pointY = ev.clientY;
      } else if (ev.touches && ev.touches[0]) {
        pointX = ev.touches[0].clientX;
        pointY = ev.touches[0].clientY;
      }
      if (typeof pointX !== 'number' || typeof pointY !== 'number') {
        return;
      }
      trackWorkspacePointer({ clientX: pointX, clientY: pointY });
      if (activeDragContext && activeDragContext.origin === 'workspace') {
        updateSidebarHoverFromPoint(pointX, pointY);
      }
    };
    const hasPointer = typeof window !== 'undefined' && 'onpointermove' in window;
    if (hasPointer) {
      const pointerHandler = (ev) => updateFromEvent(ev);
      document.addEventListener('pointermove', pointerHandler);
      handlers.push(() => {
        document.removeEventListener('pointermove', pointerHandler);
      });
    } else {
      const mouseHandler = (ev) => updateFromEvent(ev);
      const touchHandler = (ev) => updateFromEvent(ev);
      document.addEventListener('mousemove', mouseHandler);
      document.addEventListener('touchmove', touchHandler);
      handlers.push(() => {
        document.removeEventListener('mousemove', mouseHandler);
        document.removeEventListener('touchmove', touchHandler);
      });
    }
    workspacePointerCleanup = () => {
      handlers.forEach((fn) => {
        try { fn(); } catch (_err) {}
      });
      workspacePointerCleanup = null;
      workspacePointerOwnerToken = null;
    };
    workspacePointerOwnerToken = token;
    return token;
  }

  function stopWorkspacePointerTracking(token){
    if (token && workspacePointerOwnerToken && token !== workspacePointerOwnerToken) {
      return;
    }
    if (typeof workspacePointerCleanup === 'function') {
      try { workspacePointerCleanup(); } catch (_err) {}
    }
    workspacePointerCleanup = null;
    workspacePointerOwnerToken = null;
  }

  function buildItemPayloadFromRow(row){
    if (!row) return null;
    const fileName = row.getAttribute('data-name') || '';
    if (!fileName) return null;
    const payload = {
      source: row.getAttribute('data-source') || 'regular',
      file_name: fileName,
      folder: row.getAttribute('data-folder') || '',
    };
    const tags = collectTagsFromElement(row);
    if (tags && tags.length) {
      payload.tags = tags;
    }
    const pinnedAttr = row.getAttribute('data-pinned');
    if (pinnedAttr === '1') {
      payload.pinned = true;
    }
    return payload;
  }

  function ensureItemsContainerState(container){
    if (!container || !container.isConnected) return;
    // Support both old and new card classes
    if (container.querySelector('.collection-card') || container.querySelector('.collection-item')) {
      return;
    }
    container.innerHTML = '<div class="empty">אין פריטים</div>';
  }

  function findSidebarButtonFromPoint(x, y){
    if (typeof document === 'undefined') return null;
    let el = null;
    try {
      el = document.elementFromPoint(x, y);
    } catch (_err) {
      el = null;
    }
    if (el) {
      const directBtn = el.closest('#collectionsSidebar .sidebar-item');
      if (directBtn) {
        return directBtn;
      }
    }
    return findSidebarButtonByBounds(x, y);
  }

  function findSidebarButtonByBounds(x, y){
    if (typeof x !== 'number' || typeof y !== 'number') {
      return null;
    }
    const container = resolveSidebarContainer();
    if (!container) {
      return null;
    }
    const rect = container.getBoundingClientRect();
    if (!rect) {
      return null;
    }
    const padding = 16;
    const insideSidebar = (
      x >= rect.left - padding &&
      x <= rect.right + padding &&
      y >= rect.top - padding &&
      y <= rect.bottom + padding
    );
    if (!insideSidebar) {
      return null;
    }
    const buttons = container.querySelectorAll('.sidebar-item');
    let fallbackBtn = null;
    let smallestDelta = Number.POSITIVE_INFINITY;
    for (let i = 0; i < buttons.length; i += 1) {
      const btn = buttons[i];
      if (!(btn instanceof HTMLElement)) continue;
      const btnRect = btn.getBoundingClientRect();
      if (!btnRect) continue;
      const tolerance = 8;
      const withinBtn = (
        x >= btnRect.left - tolerance &&
        x <= btnRect.right + tolerance &&
        y >= btnRect.top - tolerance &&
        y <= btnRect.bottom + tolerance
      );
      if (withinBtn) {
        return btn;
      }
      const centerY = (btnRect.top + btnRect.bottom) / 2;
      const delta = Math.abs(centerY - y);
      const withinHorizontal = x >= btnRect.left - padding && x <= btnRect.right + padding;
      if (withinHorizontal && delta < smallestDelta) {
        smallestDelta = delta;
        fallbackBtn = btn;
      }
    }
    return fallbackBtn;
  }

  function updateSidebarHoverFromPoint(x, y){
    if (!activeDragContext) return;
    const btn = findSidebarButtonFromPoint(x, y);
    if (btn && canDropOnSidebar(btn.getAttribute('data-id') || '')) {
      setSidebarDropHover(btn, 'hover');
    } else {
      setSidebarDropHover(null);
    }
  }

  async function handleSidebarDropRequest(targetId, targetBtn){
    if (!canDropOnSidebar(targetId)) {
      setSidebarDropHover(null);
      return;
    }
    if (!activeDragContext || activeDragContext.dropInProgress) {
      return;
    }
    activeDragContext.dropInProgress = true;
    await moveDraggedItemToCollection(targetId, targetBtn || sidebarHoverBtn);
  }

  async function moveDraggedItemToCollection(targetCollectionId, targetBtn){
    const ctx = activeDragContext;
    if (!ctx) {
      resetDragUi();
      return;
    }
    const payload = ctx.payload;
    if (!payload || !payload.file_name) {
      ctx.dropInProgress = false;
      if (activeDragContext === ctx) {
        clearActiveDragContext();
      } else if (ctx.origin === 'workspace') {
        stopWorkspacePointerTracking(ctx.workspacePointerToken);
      }
      return;
    }
    setSidebarDropHover(targetBtn || sidebarHoverBtn, 'hover');
    const stopBusy = withSidebarDropBusy(targetBtn || sidebarHoverBtn);
    try {
      const crossPayload = Object.assign({}, payload, {folder: ''});
      const addRes = await api.addItems(targetCollectionId, [crossPayload]);
      if (!addRes || !addRes.ok) {
        throw new Error((addRes && addRes.error) || 'שגיאה בהעברת הפריט');
      }
      const removeRes = await api.removeItems(ctx.collectionId, [{ source: ctx.payload.source || 'regular', file_name: ctx.payload.file_name, folder: ctx.payload.folder || '' }]);
      if (!removeRes || !removeRes.ok) {
        throw new Error((removeRes && removeRes.error) || 'שגיאה בהעברת הפריט');
      }
      if (ctx.element && ctx.element.remove) {
        const listEl = (ctx.container && ctx.container.isConnected) ? ctx.container : ctx.element.parentElement;
        await removeElementWithAnimation(ctx.element);
        if (listEl && typeof listEl.hasAttribute === 'function' && listEl.hasAttribute('data-state-list')) {
          if (workspaceBoardCtx) {
            updateWorkspaceEmptyStates(workspaceBoardCtx);
          }
        } else {
          ensureItemsContainerState(listEl);
        }
      }
      await ensureCollectionsSidebar();
    } catch (err) {
      alert((err && err.message) || 'שגיאה בהעברת הפריט');
      throw err;
    } finally {
      ctx.dropInProgress = false;
      stopBusy();
      if (activeDragContext === ctx) {
        clearActiveDragContext();
      } else if (ctx.origin === 'workspace') {
        stopWorkspacePointerTracking(ctx.workspacePointerToken);
      }
    }
  }

  function setupSidebarDropHandlers(root){
    updateSidebarShell(root);
    const buttons = root.querySelectorAll('.sidebar-item');
    buttons.forEach((btn) => {
      btn.addEventListener('dragenter', handleSidebarDragEnter);
      btn.addEventListener('dragover', handleSidebarDragOver);
      btn.addEventListener('dragleave', handleSidebarDragLeave);
      btn.addEventListener('drop', handleSidebarDrop);
    });
    if (activeDragContext) {
      setSidebarDragVisual(true);
    }
  }

  function handleSidebarDragEnter(ev){
    const btn = ev.currentTarget;
    if (!(btn instanceof HTMLElement)) return;
    const cid = btn.getAttribute('data-id') || '';
    if (!canDropOnSidebar(cid)) return;
    ev.preventDefault();
    setSidebarDropHover(btn, 'ready');
  }

  function handleSidebarDragOver(ev){
    const btn = ev.currentTarget;
    if (!(btn instanceof HTMLElement)) return;
    const cid = btn.getAttribute('data-id') || '';
    if (!canDropOnSidebar(cid)) return;
    ev.preventDefault();
    if (ev.dataTransfer) {
      ev.dataTransfer.dropEffect = 'move';
    }
    setSidebarDropHover(btn, 'hover');
  }

  function handleSidebarDragLeave(ev){
    const btn = ev.currentTarget;
    if (!(btn instanceof HTMLElement)) return;
    const related = ev.relatedTarget;
    if (related && btn.contains(related)) {
      return;
    }
    if (sidebarHoverBtn === btn) {
      setSidebarDropHover(null);
    }
  }

  function handleSidebarDrop(ev){
    const btn = ev.currentTarget;
    if (!(btn instanceof HTMLElement)) return;
    const cid = btn.getAttribute('data-id') || '';
    if (!canDropOnSidebar(cid)) return;
    ev.preventDefault();
    handleSidebarDropRequest(cid, btn).catch(() => {});
  }

  async function loadMoreCollectionItems(collectionId) {
    if (isLoadingMoreItems) return;
    if (lastCollectionItems.length >= lastCollectionTotal) return;
    const container = document.getElementById('collectionsContent');
    if (!container) return;
    const nextPage = lastCollectionPage + 1;
    isLoadingMoreItems = true;
    try {
      const resp = await api.getItems(collectionId, nextPage, lastCollectionPerPage);
      if (!resp || !resp.ok) {
        throw new Error((resp && resp.error) || 'שגיאה בטעינת פריטים נוספים');
      }
      const items = Array.isArray(resp.items) ? resp.items : [];
      lastCollectionItems = [...lastCollectionItems, ...items];
      lastCollectionPage = nextPage;
      lastCollectionTotal = Number(resp.total_items || resp.total_manual || lastCollectionItems.length);
      tagsFilterCache.clear();
      renderCollectionItemsView(container, collectionId, lastCollectionMeta || {}, lastCollectionItems, lastCollectionIsWorkspace);
    } catch (err) {
      console.error('Load more error:', err);
      showToast('שגיאה בטעינת פריטים נוספים', 'error');
    } finally {
      isLoadingMoreItems = false;
    }
  }

  function renderCollectionItemsFromCache() {
    const container = document.getElementById('collectionsContent');
    if (!container || !lastCollectionMeta || !lastCollectionId) {
      return;
    }
    renderCollectionItemsView(container, lastCollectionId, lastCollectionMeta, lastCollectionItems, lastCollectionIsWorkspace);
  }

  function renderCollectionItemsView(container, collectionId, col, baseItems, isWorkspace) {
    if (!container) return;
    resetDragUi();
    activeDragContext = null;
    teardownWorkspaceBoard();
    markSidebarSelection(collectionId);

    const displayItems = applyTagsFilterAndSort(baseItems || []);
    const iconChar = (col.icon && ALLOWED_ICONS.includes(col.icon)) ? col.icon : (ALLOWED_ICONS[0] || '📂');
    const share = col.share || {};
    const shareEnabled = !!share.enabled;
    const shareUrl = resolvePublicUrl(col);
    const tagsToolbarHtml = buildTagsToolbarHtml();
    const headerHtml = `
      <div class="collection-header">
        <div class="title">
          <button class="collection-icon-btn" type="button" aria-label="בחר אייקון" title="בחר אייקון">${escapeHtml(iconChar)}</button>
          <div class="name" title="${escapeHtml(col.name || 'ללא שם')}">${escapeHtml(col.name || 'ללא שם')}</div>
        </div>
        <div class="share-controls" data-enabled="${shareEnabled ? '1' : '0'}">
          <label class="share-toggle">
            <input type="checkbox" class="share-enabled" ${shareEnabled ? 'checked' : ''}>
            <span class="share-toggle__text">שיתוף</span>
          </label>
          <span class="share-divider" aria-hidden="true">|</span>
          <button class="btn btn-secondary btn-sm share-copy" ${shareEnabled && shareUrl ? '' : 'disabled'} data-url="${shareUrl ? escapeHtml(shareUrl) : ''}" title="העתק קישור לשיתוף" aria-label="העתק קישור לשיתוף">
            <span class="share-copy__text">העתק</span>
          </button>
        </div>
        <div class="actions">
          ${isWorkspace ? '' : '<button class="btn btn-secondary add-folder-btn" title="תיקיה חדשה">📁 תיקיה חדשה</button>'}
          <button class="btn btn-secondary rename">שנה שם</button>
          <button class="btn btn-danger delete">מחק</button>
        </div>
      </div>`;

    if (isWorkspace) {
      const boardHtml = buildWorkspaceBoardHtml(displayItems);
      container.innerHTML = `${headerHtml}${tagsToolbarHtml}${boardHtml}`;
    } else {
      // קיבוץ פריטים לפי תיקיה
      const folders = Array.isArray(col.folders) ? col.folders : [];
      const folderItemsHtml = buildFolderGroupedHtml(displayItems, folders, collectionId);
      const loadMoreHtml = (lastCollectionItems.length < lastCollectionTotal)
        ? '<div class="collection-load-more"><button type="button" class="btn btn-secondary load-more">טען עוד</button></div>'
        : '';
      container.innerHTML = `${headerHtml}${tagsToolbarHtml}<div id="collectionItems">${folderItemsHtml || '<div class="empty">אין פריטים</div>'}</div>${loadMoreHtml}`;
    }

    setBulkMode(container, isBulkMode);
    if (TAGS_FEATURE_ENABLED && TAGS_TOOLBAR_ENABLED) {
      wireTagsToolbar(container, collectionId);
    }
    // חיבור אירועי תיקיות (לא ב-workspace)
    if (!isWorkspace) {
      wireFolderEvents(container, collectionId);
    }

    const iconBtn = container.querySelector('.collection-icon-btn');
    if (iconBtn) {
      iconBtn.addEventListener('click', async () => {
        try {
          const nextIcon = await openIconPicker(iconChar);
          if (!nextIcon || nextIcon === iconChar) {
            return;
          }
          const res = await api.updateCollection(collectionId, { icon: nextIcon });
          if (!res || !res.ok) {
            alert((res && res.error) || 'שגיאה בעדכון האייקון');
            return;
          }
          ensureCollectionsSidebar();
          await renderCollectionItems(collectionId);
        } catch (_err) {
          alert('שגיאה בעדכון האייקון');
        }
      });
    }

    const shareControls = container.querySelector('.share-controls');
    const shareToggleEl = shareControls ? shareControls.querySelector('.share-enabled') : null;
    const shareCopyBtn = shareControls ? shareControls.querySelector('.share-copy') : null;
    const shareCopyLabel = shareCopyBtn ? shareCopyBtn.querySelector('.share-copy__text') : null;
    if (shareCopyBtn && !shareCopyBtn.dataset.label) {
      const labelText = shareCopyLabel ? shareCopyLabel.textContent : shareCopyBtn.textContent;
      shareCopyBtn.dataset.label = labelText && labelText.trim() ? labelText.trim() : 'העתק';
    }
    setShareControlsBusy(shareToggleEl, shareCopyBtn, false);

    if (shareCopyBtn) {
      shareCopyBtn.addEventListener('click', async () => {
        const url = shareCopyBtn.getAttribute('data-url') || '';
        if (!url) {
          alert('אין קישור שיתוף פעיל');
          return;
        }
        const original = shareCopyBtn.dataset.label || (shareCopyLabel ? shareCopyLabel.textContent : '') || 'העתק';
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(url);
          } else {
            throw new Error('clipboard_unavailable');
          }
          if (shareCopyLabel) {
            shareCopyLabel.textContent = 'הועתק!';
          } else {
            shareCopyBtn.textContent = 'הועתק!';
          }
          setTimeout(() => {
            if (shareCopyLabel) {
              shareCopyLabel.textContent = original;
            } else {
              shareCopyBtn.textContent = original;
            }
          }, 1600);
        } catch (_err) {
          try {
            const manual = prompt('העתק את הקישור הבא:', url);
            if (manual !== null) {
              if (shareCopyLabel) {
                shareCopyLabel.textContent = 'הועתק!';
              } else {
                shareCopyBtn.textContent = 'הועתק!';
              }
              setTimeout(() => {
                if (shareCopyLabel) {
                  shareCopyLabel.textContent = original;
                } else {
                  shareCopyBtn.textContent = original;
                }
              }, 1600);
            }
          } catch (_) {
            alert('לא ניתן להעתיק את הקישור אוטומטית');
          }
        }
      });
    }

    if (shareToggleEl) {
      shareToggleEl.addEventListener('change', async () => {
        const enabled = shareToggleEl.checked;
        let errorMessage = '';
        setShareControlsBusy(shareToggleEl, shareCopyBtn, true);
        try {
          const res = await api.updateShare(collectionId, { enabled });
          if (!res || !res.ok) {
            errorMessage = (res && res.error) || '';
            throw new Error(errorMessage || 'share_update_failed');
          }
        } catch (_err) {
          shareToggleEl.checked = !enabled;
          alert(errorMessage || 'שגיאה בעדכון שיתוף');
        } finally {
          setShareControlsBusy(shareToggleEl, shareCopyBtn, false);
        }
        ensureCollectionsSidebar();
        await renderCollectionItems(collectionId);
      });
    }

    let itemsContainer = null;
    if (isWorkspace) {
      hydrateWorkspaceBoard(container, collectionId, displayItems);
      autoFitText('.workspace-card__name', { minPx: 12, maxPx: 16, allowWrap: true });
    } else {
      itemsContainer = container.querySelector('#collectionItems');
      // Wire DnD on each card section (root + each folder)
      itemsContainer.querySelectorAll('.collection-cards').forEach(section => {
        wireDnd(section, collectionId);
      });
      // Auto fit text for both old and new card styles
      autoFitText('#collectionItems .collection-card__name', { minPx: 12, maxPx: 16, allowWrap: true });
      autoFitText('#collectionItems .file', { minPx: 12, maxPx: 16 });
      const loadMoreBtn = container.querySelector('.load-more');
      if (loadMoreBtn) {
        loadMoreBtn.addEventListener('click', async () => {
          loadMoreBtn.disabled = true;
          loadMoreBtn.textContent = 'טוען...';
          await loadMoreCollectionItems(collectionId);
        });
      }
    }

    // Header actions
    const renameBtn = container.querySelector('.collection-header .rename');
    const deleteBtn = container.querySelector('.collection-header .delete');
    if (renameBtn) renameBtn.addEventListener('click', async () => {
      const current = String(col.name || '');
      const name = prompt('שם חדש לאוסף:', current);
      if (!name) return;
      const res = await api.updateCollection(collectionId, { name: name.slice(0, 80) });
      if (!res || !res.ok) return alert((res && res.error) || 'שגיאה בעדכון שם');
      ensureCollectionsSidebar();
      await renderCollectionItems(collectionId);
    });
    if (deleteBtn) deleteBtn.addEventListener('click', async () => {
      if (!confirm('למחוק את האוסף? הפעולה תסיר את האוסף ואת הקישורים שבו, אבל הקבצים עצמם יישארו זמינים בבוט ובקבצים.')) return;
      const res = await api.deleteCollection(collectionId);
      if (!res || !res.ok) return alert((res && res.error) || 'שגיאה במחיקה');
      ensureCollectionsSidebar();
      container.innerHTML = '<div class="empty">האוסף נמחק. הקבצים נשארים זמינים בבוט ובמסך הקבצים.</div>';
    });

    if (!isWorkspace && itemsContainer) {
      itemsContainer.addEventListener('click', async (ev) => {
        // Support both old .collection-item and new .collection-card classes
        const row = ev.target.closest('.collection-card') || ev.target.closest('.collection-item');
        if (!row) return;

        // טיפול ישיר בלחיצה על כפתור עריכת תגיות
        const tagBtn = ev.target.closest('.btn-tag-edit');
        if (tagBtn) {
          ev.preventDefault();
          ev.stopPropagation();
          const itemId = tagBtn.dataset.itemId || row.getAttribute('data-item-id') || '';
          if (itemId && TAGS_FEATURE_ENABLED) {
            const currentTags = collectTagsFromElement(row);
            openTagsEditorModal(itemId, currentTags);
          }
          return;
        }

        if (ev.target.closest('.item-select')) {
          return;
        }
        const source = row.getAttribute('data-source') || 'regular';
        const name = row.getAttribute('data-name') || '';
        const folder = row.getAttribute('data-folder') || '';

        const rm = ev.target.closest('.remove');
        if (rm) {
          if (!confirm('להסיר את הפריט מהאוסף? הקובץ עצמו יישאר זמין בבוט ובמסך הקבצים.')) return;
          const res = await api.removeItems(collectionId, [{ source, file_name: name, folder }]);
          if (!res || !res.ok) return alert((res && res.error) || 'שגיאה במחיקה');
          await removeElementWithAnimation(row);
          if (!itemsContainer.querySelector('.collection-card') && !itemsContainer.querySelector('.collection-item')) {
            itemsContainer.innerHTML = '<div class="empty">אין פריטים</div>';
          }
          return;
        }

        const openBtn = ev.target.closest('.open-view');
        if (openBtn) {
          ev.preventDefault();
          await handleDirectViewClick(row, openBtn, name);
          return;
        }

        const previewBtn = ev.target.closest('.preview');
        if (previewBtn) {
          ev.preventDefault();
          await handlePreviewClick(row, previewBtn, name);
          return;
        }

        if (ev.target.closest('.card-code-preview-wrapper')) {
          return;
        }
        // Support both old and new link selectors
        const link = ev.target.closest('a.collection-card__link[data-open]') || ev.target.closest('a.file[data-open]');
        if (link) {
          ev.preventDefault();
          const fname = link.getAttribute('data-open') || '';
          await openFileByName(fname);
          return;
        }
      });
    }

    currentCollectionId = collectionId;
  }

  async function renderCollectionItems(cid){
    const container = document.getElementById('collectionsContent');
    if (!container) return;
    const collectionId = String(cid || '').trim();
    if (!collectionId) {
      container.innerHTML = '<div class="error">האוסף לא נמצא</div>';
      markSidebarSelection('');
      return;
    }
    if (collectionId !== lastCollectionId) {
      currentTagsFilter = [];
      currentTagsSort = 'default';
      setBulkMode(container, false);
    }
    container.innerHTML = '<div class="loading">טוען…</div>';
    try {
      const perPage = lastCollectionPerPage || 200;
      const [colRes, data] = await Promise.all([
        api.getCollection(collectionId),
        api.getItems(collectionId, 1, perPage),
      ]);
      if (!data || !data.ok) throw new Error((data && data.error) || 'שגיאה');
      if (!colRes || !colRes.ok) throw new Error((colRes && colRes.error) || 'שגיאה');
      const col = colRes.collection || {};
      const isWorkspace = isWorkspaceCollection(col);
      const baseItems = Array.isArray(data.items) ? data.items : [];
      lastCollectionItems = baseItems;
      lastCollectionMeta = col;
      lastCollectionIsWorkspace = isWorkspace;
      lastCollectionId = collectionId;
      lastCollectionPage = 1;
      lastCollectionPerPage = perPage;
      lastCollectionTotal = Number(data.total_items || data.total_manual || baseItems.length);
      tagsFilterCache.clear();
      renderCollectionItemsView(container, collectionId, col, baseItems, isWorkspace);
    } catch (e) {
      container.innerHTML = '<div class="error">שגיאה בטעינת פריטים</div>';
    }
  }

  async function resolveFileId(name){
    const key = String(name || '').trim();
    if (!key) {
      const err = new Error('missing_name');
      err.code = 'missing_name';
      throw err;
    }
    if (resolvedFileIdCache.has(key)) {
      return resolvedFileIdCache.get(key);
    }
    let resp;
    try {
      resp = await fetch(`/api/files/resolve?name=${encodeURIComponent(key)}`);
    } catch (_networkErr) {
      const err = new Error('network_error');
      err.code = 'network_error';
      throw err;
    }
    let data = null;
    try {
      data = await resp.json();
    } catch (_jsonErr) {
      data = null;
    }
    if (!resp.ok || !data || data.ok === false || !data.id) {
      const errorCode = (data && data.error) || 'not_found';
      const err = new Error(errorCode);
      err.code = errorCode;
      err.data = data;
      throw err;
    }
    resolvedFileIdCache.set(key, data.id);
    return data.id;
  }

  function setPreviewLoading(button){
    if (!button) return () => {};
    const originalHtml = button.innerHTML;
    button.disabled = true;
    button.classList.add('preview-loading');
    button.innerHTML = '⏳';
    return () => {
      button.disabled = false;
      button.classList.remove('preview-loading');
      button.innerHTML = originalHtml;
    };
  }

  async function handlePreviewClick(row, previewBtn, rawName){
    if (!row || !previewBtn) return;
    if (!window.cardPreview || typeof window.cardPreview.expand !== 'function') {
      alert('תצוגה מקדימה אינה זמינה כרגע');
      return;
    }
    const fname = String(rawName || '').trim();
    if (!fname) {
      alert('שם הקובץ חסר');
      return;
    }
    let fileId = row.getAttribute('data-file-id') || '';
    if (!fileId) {
      const restore = setPreviewLoading(previewBtn);
      try {
        fileId = await resolveFileId(fname);
        if (fileId) {
          row.setAttribute('data-file-id', fileId);
        }
      } catch (err) {
        const code = (err && (err.code || err.message)) || 'error';
        if (code === 'in_recycle_bin') {
          alert(RECYCLE_BIN_ALERT);
        } else if (code === 'not_found') {
          alert('הקובץ לא נמצא להצגה מקדימה');
        } else if (code === 'missing_name') {
          alert('שם הקובץ חסר');
        } else {
          alert('שגיאה בפתיחת התצוגה המקדימה');
        }
        return;
      } finally {
        restore();
      }
    }
    if (!fileId) {
      alert('הקובץ לא נמצא להצגה מקדימה');
      return;
    }
    try { row.dataset.previewHost = '1'; } catch (_e) {}
    window.cardPreview.expand(fileId, row);
  }

  function getDirectViewMode(fileName){
    const lower = String(fileName || '').trim().toLowerCase();
    if (!lower) return '';
    if (lower.endsWith('.md') || lower.endsWith('.markdown')) return 'md';
    if (lower.endsWith('.html') || lower.endsWith('.htm')) return 'html';
    return '';
  }

  function directViewTitle(mode){
    if (mode === 'md') return 'פתח תצוגת Markdown';
    if (mode === 'html') return 'פתח תצוגת דפדפן';
    return 'פתח תצוגה';
  }

  async function handleDirectViewClick(row, button, rawName){
    if (!row || !button) return;
    const fname = String(rawName || '').trim();
    if (!fname) {
      alert('שם הקובץ חסר');
      return;
    }
    const mode = String(button.getAttribute('data-view') || '').trim() || getDirectViewMode(fname);
    if (!mode) {
      // אם זה לא Markdown/HTML, נפול חזרה להתנהגות הרגילה
      await openFileByName(fname);
      return;
    }

    let fileId = row.getAttribute('data-file-id') || '';
    if (!fileId) {
      const restore = setPreviewLoading(button);
      try {
        fileId = await resolveFileId(fname);
        if (fileId) {
          row.setAttribute('data-file-id', fileId);
        }
      } catch (err) {
        const code = (err && (err.code || err.message)) || 'error';
        if (code === 'in_recycle_bin') {
          alert(RECYCLE_BIN_ALERT);
        } else if (code === 'not_found') {
          alert('הקובץ לא נמצא לפתיחה');
        } else if (code === 'missing_name') {
          alert('שם הקובץ חסר');
        } else {
          alert('שגיאה בפתיחת התצוגה');
        }
        return;
      } finally {
        restore();
      }
    }
    if (!fileId) {
      alert('הקובץ לא נמצא לפתיחה');
      return;
    }

    const url = (mode === 'md')
      ? `/md/${encodeURIComponent(fileId)}`
      : `/html/${encodeURIComponent(fileId)}`;
    // דרישת UX: לפתוח באותו טאב (לא בכרטיסייה חדשה)
    window.location.href = url;
  }

  // פתיחת קובץ לפי שם הקובץ (שימושי גם ללחיצה על כל השורה)
  async function openFileByName(fname){
    const name = String(fname || '').trim();
    if (!name) return;
    try {
      const fileId = await resolveFileId(name);
      if (fileId) {
        window.location.href = `/file/${encodeURIComponent(fileId)}`;
      } else {
        alert('הקובץ לא נמצא לצפייה');
      }
    } catch (err) {
      const code = (err && (err.code || err.message)) || 'error';
      if (code === 'in_recycle_bin') {
        alert(RECYCLE_BIN_ALERT);
      } else if (code === 'not_found') {
        alert('הקובץ לא נמצא לצפייה');
      } else if (code !== 'missing_name') {
        alert('שגיאה בפתיחת הקובץ');
      }
    }
  }

  function isWorkspaceCollection(col){
    if (!col) return false;
    try {
      const name = String(col.name || '').trim();
      if (name === 'שולחן עבודה') {
        return true;
      }
      const slug = String(col.slug || '').trim().toLowerCase();
      return slug === 'workspace' || slug === 'שולחן-עבודה';
    } catch (_err) {
      return false;
    }
  }

  function normalizeWorkspaceState(value){
    const key = String(value || '').trim().toLowerCase();
    if (WORKSPACE_STATE_META[key]) {
      return key;
    }
    return WORKSPACE_STATE_ORDER[0];
  }

  function workspaceStateLabel(state){
    const key = normalizeWorkspaceState(state);
    return WORKSPACE_STATE_META[key]?.label || WORKSPACE_STATE_META[WORKSPACE_STATE_ORDER[0]].label;
  }

  function buildWorkspaceBoardHtml(items){
    const groups = {};
    WORKSPACE_STATE_ORDER.forEach((state) => { groups[state] = []; });
    (items || []).forEach((item) => {
      const state = normalizeWorkspaceState(item.workspace_state);
      if (!groups[state]) {
        groups[state] = [];
      }
      groups[state].push(item);
    });
    return `
      <div class="workspace-board" data-workspace-board="1">
        <div class="workspace-board__live" aria-live="polite" aria-atomic="true"></div>
        <div class="workspace-board__helper">טיפ: גרור באמצעות הידית או השתמש בקיצורים (Shift+1/2/3)</div>
        <div class="workspace-board__grid">
          ${WORKSPACE_STATE_ORDER.map((state) => {
            const meta = WORKSPACE_STATE_META[state] || {};
            const itemsHtml = (groups[state] || []).map(renderWorkspaceCard).join('');
            const emptyAttr = itemsHtml ? '0' : '1';
            return `
              <section class="workspace-column" data-state="${state}">
                <div class="workspace-column__header">
                  <div class="workspace-column__title">
                    <span>${escapeHtml(meta.label || state)}</span>
                    <span class="workspace-column__count">${Number((groups[state] || []).length)}</span>
                  </div>
                  <div class="workspace-column__meta">
                    <span class="workspace-column__description">${escapeHtml(meta.description || '')}</span>
                    ${meta.shortcut ? `<span class="workspace-shortcut-hint">${escapeHtml(meta.shortcut)}</span>` : ''}
                  </div>
                </div>
                <div class="workspace-column__list stagger-feed" data-state-list="${state}" data-empty="${emptyAttr}">
                  ${itemsHtml}
                </div>
              </section>
            `;
          }).join('')}
        </div>
      </div>
    `;
  }

  function renderWorkspaceCard(item){
    const state = normalizeWorkspaceState(item.workspace_state);
    const rawItemId = item.id || item._id || '';
    const itemId = String(rawItemId || '');
    const fileName = String(item.file_name || '').trim();
    const mode = getDirectViewMode(fileName);
    const btnLabel = directViewTitle(mode);
    const directBtn = mode
      ? `<button type="button" class="open-view" data-view="${escapeHtml(mode)}" title="${escapeHtml(btnLabel)}" aria-label="${escapeHtml(btnLabel)}">🌐</button>`
      : '';
    const tagsHtml = buildItemTagsHtml(item.tags || [], itemId);
    const tagBtn = (TAGS_FEATURE_ENABLED && itemId)
      ? `<button type="button" class="btn-tag-edit" data-item-id="${escapeHtml(itemId)}" title="ערוך תגיות" aria-label="ערוך תגיות">🏷️</button>`
      : '';
    const tagsAttr = Array.isArray(item.tags) ? item.tags.join(',') : '';
    const selectBox = (TAGS_TOOLBAR_ENABLED && itemId)
      ? `<input type="checkbox" class="item-select" data-item-id="${escapeHtml(itemId)}" aria-label="בחר פריט">`
      : '';
    return `
      <article class="workspace-card" data-item-id="${escapeHtml(itemId)}" data-state="${escapeHtml(state)}" data-source="${escapeHtml(item.source || 'regular')}" data-name="${escapeHtml(item.file_name || '')}" data-tags="${escapeHtml(tagsAttr)}" data-file-id="${escapeHtml(item.file_id || '')}">
        <div class="workspace-card__top">
          ${selectBox}
          <button class="workspace-card__drag" type="button" aria-label="גרור להזזת הפריט">⋮⋮</button>
          <div class="workspace-card__body">
            <div class="workspace-card__name">
              <a class="workspace-card__link" href="#" data-open="${escapeHtml(item.file_name || '')}">${escapeHtml(item.file_name || '')}</a>
            </div>
            <div class="workspace-card__meta">
              <span class="workspace-card__tag">
                <span class="workspace-card__status-indicator" data-state="${escapeHtml(state)}"></span>
                <span class="workspace-card__tag-text">${escapeHtml(workspaceStateLabel(state))}</span>
              </span>
              ${tagsHtml}
              ${item.note ? `<span>📝 ${escapeHtml(item.note)}</span>` : ''}
            </div>
          </div>
        </div>
        <div class="workspace-card__actions">
          ${tagBtn}
          ${directBtn}
          <button type="button" class="preview" title="תצוגה מקדימה" aria-label="תצוגה מקדימה">🧾</button>
          <button type="button" class="remove" title="הסר">✕</button>
        </div>
      </article>
    `;
  }

  /**
   * Renders a collection item as a card (similar to workspace card but without workspace-specific features)
   * @param {Object} item - The collection item to render
   * @returns {string} HTML string for the card
   */
  // --- Folder rendering ---

  function buildFolderGroupedHtml(items, folders, collectionId) {
    // הפרדת פריטים: root vs תיקיות
    const rootItems = [];
    const folderMap = {}; // folderName -> [items]
    for (const item of items) {
      const f = String(item.folder || '').trim();
      if (!f) {
        rootItems.push(item);
      } else {
        if (!folderMap[f]) folderMap[f] = [];
        folderMap[f].push(item);
      }
    }

    // אם אין פריטים בכלל ואין תיקיות מוגדרות — נחזיר ריק כדי שה-caller יציג "אין פריטים"
    const hasFolders = (folders || []).length > 0 || Object.keys(folderMap).length > 0;
    if (items.length === 0 && !hasFolders) {
      return '';
    }

    let html = '';

    // קבצים ב-root — תמיד מרנדרים את ה-container כדי שיהיה drop zone גם כשריק
    const rootCardsHtml = rootItems.map(renderCollectionCard).join('');
    html += `<div class="collection-cards stagger-feed" data-folder="">${rootCardsHtml}</div>`;

    // תיקיות - לפי סדר ה-folders metadata
    const sortedFolders = (folders || []).slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
    const renderedFolders = new Set();

    for (const folderMeta of sortedFolders) {
      const name = String(folderMeta.name || '').trim();
      if (!name) continue;
      renderedFolders.add(name);
      const folderItems = folderMap[name] || [];
      html += renderFolderSection(name, folderMeta.icon || '📁', folderItems, collectionId);
    }

    // תיקיות שיש להן פריטים אבל לא הוגדרו ב-metadata (backward compat)
    for (const [name, fItems] of Object.entries(folderMap)) {
      if (renderedFolders.has(name)) continue;
      html += renderFolderSection(name, '📁', fItems, collectionId);
    }

    return html;
  }

  function renderFolderSection(folderName, icon, items, collectionId) {
    const cardsHtml = items.length > 0
      ? items.map(renderCollectionCard).join('')
      : '<div class="collection-folder--empty">התיקיה ריקה</div>';
    return `
      <details class="collection-folder" open data-folder="${escapeHtml(folderName)}" data-collection-id="${escapeHtml(collectionId)}">
        <summary class="collection-folder__header">
          <span class="collection-folder__icon">${escapeHtml(icon)}</span>
          <span class="collection-folder__name">${escapeHtml(folderName)}</span>
          <span class="collection-folder__count">${items.length}</span>
          <div class="collection-folder__actions">
            <button type="button" class="rename-folder" title="שנה שם תיקיה">✏️</button>
            <button type="button" class="delete-folder" title="מחק תיקיה">✕</button>
          </div>
        </summary>
        <div class="collection-folder__items">
          <div class="collection-cards stagger-feed" data-folder="${escapeHtml(folderName)}">${cardsHtml}</div>
        </div>
      </details>
    `;
  }

  function wireFolderEvents(container, collectionId) {
    if (!container) return;

    // כפתור יצירת תיקיה
    const addFolderBtn = container.querySelector('.add-folder-btn');
    if (addFolderBtn) {
      addFolderBtn.addEventListener('click', () => openCreateFolderDialog(collectionId));
    }

    // אירועי תיקיות
    container.addEventListener('click', async (ev) => {
      const folderEl = ev.target.closest('.collection-folder');
      if (!folderEl) return;
      const folderName = folderEl.getAttribute('data-folder') || '';

      // שינוי שם תיקיה
      const renameBtn = ev.target.closest('.rename-folder');
      if (renameBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        startFolderInlineRename(folderEl, collectionId, folderName);
        return;
      }

      // מחיקת תיקיה
      const deleteBtn = ev.target.closest('.delete-folder');
      if (deleteBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!confirm(`למחוק את התיקיה "${folderName}"? הקבצים יועברו לרמה הראשית.`)) return;
        const res = await api.deleteFolder(collectionId, folderName);
        if (!res || !res.ok) {
          alert((res && res.error) || 'שגיאה במחיקת תיקיה');
          return;
        }
        await renderCollectionItems(collectionId);
        ensureCollectionsSidebar();
        return;
      }
    });

    // Drag & drop על תיקיות
    container.querySelectorAll('.collection-folder__header').forEach((header) => {
      const folderEl = header.closest('.collection-folder');
      if (!folderEl) return;
      const targetFolder = folderEl.getAttribute('data-folder') || '';

      header.addEventListener('dragover', (ev) => {
        ev.preventDefault();
        folderEl.classList.add('collection-folder--drop-target');
      });
      header.addEventListener('dragleave', () => {
        folderEl.classList.remove('collection-folder--drop-target');
      });
      header.addEventListener('drop', async (ev) => {
        ev.preventDefault();
        folderEl.classList.remove('collection-folder--drop-target');
        // סימון שה-drop בוצע כדי שה-dragend לא ישלח reorder מיותר
        if (activeDragContext) activeDragContext.dropInProgress = true;
        let dragData;
        try {
          dragData = JSON.parse(ev.dataTransfer.getData('text/plain'));
        } catch (_e) {
          return;
        }
        if (!dragData || !dragData.file_name) return;
        const sourceFolder = String(dragData.folder || '');
        if (sourceFolder === targetFolder) return; // כבר באותה תיקיה
        // העברה עם שמירת מטאדאטה (note, tags, pinned וכו')
        const moveRes = await api.moveItemFolder(collectionId, {
          source: dragData.source || 'regular',
          file_name: dragData.file_name,
          old_folder: sourceFolder,
          new_folder: targetFolder,
        });
        if (!moveRes || !moveRes.ok) {
          alert((moveRes && moveRes.error) || 'שגיאה בהעברת קובץ');
          return;
        }
        await renderCollectionItems(collectionId);
      });
    });

    // Drop zone על root area
    const rootCards = container.querySelector('.collection-cards[data-folder=""]');
    if (rootCards) {
      rootCards.addEventListener('dragover', (ev) => {
        if (ev.dataTransfer.types.includes('text/plain')) {
          ev.preventDefault();
          rootCards.classList.add('collection-folder--drop-target');
        }
      });
      rootCards.addEventListener('dragleave', () => {
        rootCards.classList.remove('collection-folder--drop-target');
      });
      rootCards.addEventListener('drop', async (ev) => {
        ev.preventDefault();
        rootCards.classList.remove('collection-folder--drop-target');
        if (activeDragContext) activeDragContext.dropInProgress = true;
        let dragData;
        try {
          dragData = JSON.parse(ev.dataTransfer.getData('text/plain'));
        } catch (_e) {
          return;
        }
        if (!dragData || !dragData.file_name) return;
        const sourceFolder = String(dragData.folder || '');
        if (!sourceFolder) return; // כבר ב-root
        // העברה ל-root עם שמירת מטאדאטה
        const moveRes = await api.moveItemFolder(collectionId, {
          source: dragData.source || 'regular',
          file_name: dragData.file_name,
          old_folder: sourceFolder,
          new_folder: '',
        });
        if (!moveRes || !moveRes.ok) {
          alert((moveRes && moveRes.error) || 'שגיאה בהעברת קובץ');
          return;
        }
        await renderCollectionItems(collectionId);
      });
    }
  }

  function startFolderInlineRename(folderEl, collectionId, oldName) {
    const nameSpan = folderEl.querySelector('.collection-folder__name');
    if (!nameSpan) return;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'collection-folder__name-input';
    input.value = oldName;
    input.maxLength = 60;
    nameSpan.replaceWith(input);
    input.focus();
    input.select();

    const finish = async () => {
      const newName = input.value.trim();
      if (!newName || newName === oldName) {
        // ביטול
        const span = document.createElement('span');
        span.className = 'collection-folder__name';
        span.textContent = oldName;
        input.replaceWith(span);
        return;
      }
      const res = await api.updateFolder(collectionId, oldName, { name: newName });
      if (!res || !res.ok) {
        alert((res && res.error) || 'שגיאה בשינוי שם תיקיה');
        const span = document.createElement('span');
        span.className = 'collection-folder__name';
        span.textContent = oldName;
        input.replaceWith(span);
        return;
      }
      await renderCollectionItems(collectionId);
    };

    input.addEventListener('blur', finish);
    input.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
      if (ev.key === 'Escape') { input.value = oldName; input.blur(); }
    });
  }

  function openCreateFolderDialog(collectionId) {
    if (document.querySelector('.collection-modal[data-modal="create-folder"]')) return;
    const overlay = document.createElement('div');
    overlay.className = 'collection-modal';
    overlay.setAttribute('data-modal', 'create-folder');
    overlay.innerHTML = `
      <div class="collection-modal__backdrop"></div>
      <div class="collection-modal__panel" role="dialog" aria-modal="true">
        <h3 class="collection-modal__title">תיקיה חדשה</h3>
        <div class="collection-modal__field">
          <label for="folderNameInput">שם התיקיה</label>
          <input id="folderNameInput" type="text" maxlength="60" placeholder="לדוגמה: Frontend">
        </div>
        <div class="collection-modal__field">
          <label>בחר אייקון</label>
          <div class="icon-grid">${buildFolderIconGridHtml('📁')}</div>
        </div>
        <div class="collection-modal__error" aria-live="polite"></div>
        <div class="collection-modal__actions">
          <button type="button" class="btn btn-secondary cancel">בטל</button>
          <button type="button" class="btn btn-primary confirm">צור</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const nameInput = overlay.querySelector('#folderNameInput');
    const iconGrid = overlay.querySelector('.icon-grid');
    const errorBox = overlay.querySelector('.collection-modal__error');
    const cancelBtn = overlay.querySelector('.cancel');
    const confirmBtn = overlay.querySelector('.confirm');
    const backdrop = overlay.querySelector('.collection-modal__backdrop');
    let selectedIcon = '📁';

    if (iconGrid) {
      iconGrid.addEventListener('click', (ev) => {
        const btn = ev.target.closest('.icon-option');
        if (!btn) return;
        selectedIcon = btn.getAttribute('data-icon') || '📁';
        iconGrid.querySelectorAll('.icon-option').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      });
    }

    const close = () => overlay.remove();
    if (backdrop) backdrop.addEventListener('click', close);
    if (cancelBtn) cancelBtn.addEventListener('click', close);

    if (confirmBtn) {
      confirmBtn.addEventListener('click', async () => {
        const name = (nameInput ? nameInput.value : '').trim();
        if (!name) {
          if (errorBox) errorBox.textContent = 'יש להזין שם לתיקיה';
          return;
        }
        confirmBtn.disabled = true;
        const res = await api.createFolder(collectionId, { name, icon: selectedIcon });
        confirmBtn.disabled = false;
        if (!res || !res.ok) {
          if (errorBox) errorBox.textContent = (res && res.error) || 'שגיאה ביצירת תיקיה';
          return;
        }
        close();
        await renderCollectionItems(collectionId);
      });
    }

    if (nameInput) {
      nameInput.focus();
      nameInput.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' && confirmBtn) confirmBtn.click();
        if (ev.key === 'Escape') close();
      });
    }
  }

  function buildFolderIconGridHtml(selected) {
    const current = ALLOWED_FOLDER_ICONS.includes(selected) ? selected : '📁';
    return ALLOWED_FOLDER_ICONS.map(icon => {
      const isActive = icon === current;
      const cls = `icon-option${isActive ? ' active' : ''}`;
      return `<button type="button" class="${cls}" data-icon="${escapeHtml(icon)}">${escapeHtml(icon)}</button>`;
    }).join('');
  }

  function renderCollectionCard(item){
    const rawItemId = item.id || item._id || '';
    const itemId = String(rawItemId || '');
    const fileName = String(item.file_name || '').trim();
    const mode = getDirectViewMode(fileName);
    const btnLabel = directViewTitle(mode);
    const directBtn = mode
      ? `<button type="button" class="open-view" data-view="${escapeHtml(mode)}" title="${escapeHtml(btnLabel)}" aria-label="${escapeHtml(btnLabel)}">🌐</button>`
      : '';
    const tagsHtml = buildItemTagsHtml(item.tags || [], itemId);
    const tagBtn = (TAGS_FEATURE_ENABLED && itemId)
      ? `<button type="button" class="btn-tag-edit" data-item-id="${escapeHtml(itemId)}" title="ערוך תגיות" aria-label="ערוך תגיות">🏷️</button>`
      : '';
    const tagsAttr = Array.isArray(item.tags) ? item.tags.join(',') : '';
    const selectBox = (TAGS_TOOLBAR_ENABLED && itemId)
      ? `<input type="checkbox" class="item-select" data-item-id="${escapeHtml(itemId)}" aria-label="בחר פריט">`
      : '';
    const pinnedClass = item.pinned ? ' collection-card--pinned' : '';
    const folderAttr = String(item.folder || '');
    return `
      <article class="collection-card${pinnedClass}" data-item-id="${escapeHtml(itemId)}" data-source="${escapeHtml(item.source || 'regular')}" data-name="${escapeHtml(fileName)}" data-folder="${escapeHtml(folderAttr)}" data-tags="${escapeHtml(tagsAttr)}" data-file-id="${escapeHtml(item.file_id || '')}" data-pinned="${item.pinned ? '1' : '0'}">
        <div class="collection-card__top">
          ${selectBox}
          <span class="collection-card__drag" draggable="true">⋮⋮</span>
          <div class="collection-card__body">
            <div class="collection-card__name">
              <a class="collection-card__link" href="#" draggable="false" data-open="${escapeHtml(fileName)}">${escapeHtml(fileName)}</a>
            </div>
            <div class="collection-card__meta">
              ${tagsHtml}
              ${item.note ? `<span class="collection-card__note">📝 ${escapeHtml(item.note)}</span>` : ''}
            </div>
          </div>
        </div>
        <div class="collection-card__actions">
          ${tagBtn}
          ${directBtn}
          <button type="button" class="preview" title="תצוגה מקדימה" aria-label="תצוגה מקדימה">🧾</button>
          <button type="button" class="remove" title="הסר">✕</button>
        </div>
      </article>
    `;
  }

  function hydrateWorkspaceBoard(container, collectionId, items){
    const board = container.querySelector('.workspace-board');
    if (!board) {
      return;
    }
    const lists = {};
    board.querySelectorAll('[data-state-list]').forEach((listEl) => {
      const state = listEl.getAttribute('data-state-list');
      if (!state) {
        return;
      }
      lists[state] = listEl;
      listEl.dataset.empty = listEl.querySelector('.workspace-card') ? '0' : '1';
    });
    const ctx = {
      board,
      collectionId,
      lists,
      liveRegion: board.querySelector('.workspace-board__live'),
      cleanup: null,
      keyboardHandler: null,
    };
    workspaceBoardCtx = ctx;
    bindWorkspaceCardEvents(ctx);
    setupWorkspaceSortable(ctx);
    setupWorkspaceKeyboard(ctx);
  }

  function bindWorkspaceCardEvents(ctx){
    const board = ctx.board;
    board.addEventListener('focusin', (ev) => {
      const card = ev.target.closest('.workspace-card');
      if (card) {
        workspaceActiveCard = card;
      }
    });
    board.addEventListener('click', async (ev) => {
      const card = ev.target.closest('.workspace-card');
      if (card) {
        workspaceActiveCard = card;
      }
      if (!card) return;

      // טיפול ישיר בלחיצה על כפתור עריכת תגיות
      const tagBtn = ev.target.closest('.btn-tag-edit');
      if (tagBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        const itemId = tagBtn.dataset.itemId || card.getAttribute('data-item-id') || '';
        if (itemId && TAGS_FEATURE_ENABLED) {
          const currentTags = collectTagsFromElement(card);
          openTagsEditorModal(itemId, currentTags);
        }
        return;
      }

      if (ev.target.closest('.item-select')) {
        return;
      }
      const source = card.getAttribute('data-source') || 'regular';
      const name = card.getAttribute('data-name') || '';
      const itemId = card.getAttribute('data-item-id') || '';
      const folder = card.getAttribute('data-folder') || '';

      const removeBtn = ev.target.closest('.remove');
      if (removeBtn) {
        if (!confirm('להסיר את הפריט מהאוסף? הקובץ עצמו יישאר זמין בבוט ובמסך הקבצים.')) return;
        const res = await api.removeItems(ctx.collectionId, [{ source, file_name: name, folder }]);
        if (!res || !res.ok) {
          alert((res && res.error) || 'שגיאה במחיקה');
          return;
        }
        await removeElementWithAnimation(card);
        updateWorkspaceEmptyStates(ctx);
        return;
      }

      const openBtn = ev.target.closest('.open-view');
      if (openBtn) {
        ev.preventDefault();
        await handleDirectViewClick(card, openBtn, name);
        return;
      }

      const previewBtn = ev.target.closest('.preview');
      if (previewBtn) {
        ev.preventDefault();
        await handlePreviewClick(card, previewBtn, name);
        return;
      }

      if (ev.target.closest('.workspace-card__drag')) {
        return;
      }
      const link = ev.target.closest('a[data-open]');
      if (link) {
        ev.preventDefault();
        const fname = link.getAttribute('data-open') || '';
        await openFileByName(fname);
        return;
      }
    });
  }

  function setupWorkspaceSortable(ctx){
    if (typeof Sortable === 'undefined') {
      return;
    }
    Object.values(ctx.lists || {}).forEach((listEl) => {
      new Sortable(listEl, {
        group: 'workspace-board',
        handle: '.workspace-card__drag',
        animation: 150,
        forceFallback: true,
        fallbackTolerance: 8,
        dragClass: 'workspace-card--dragging',
        ghostClass: 'workspace-card--ghost',
        onStart(evt) {
          if (!evt || !evt.item) return;
          const originContainer = evt.from || listEl;
          evt.item.__workspacePrevContainer = originContainer;
          evt.item.__workspacePrevIndex = Array.prototype.indexOf.call(originContainer ? originContainer.children : [], evt.item);
          evt.item.__workspacePrevState = evt.item.getAttribute('data-state') || '';
          beginCollectionItemDrag(evt.item, ctx.collectionId, originContainer, 'workspace');
        },
        onMove(evt, originalEvent) {
          const event = originalEvent || (evt && evt.originalEvent) || null;
          if (!event) return;
          trackWorkspacePointer(event);
          if (activeDragContext && activeDragContext.origin === 'workspace') {
            updateSidebarHoverFromPoint(event.clientX, event.clientY);
          }
        },
        async onEnd(evt) {
          const item = evt && evt.item;
          const prevContainer = item && item.__workspacePrevContainer;
          const prevIndex = (item && typeof item.__workspacePrevIndex === 'number') ? item.__workspacePrevIndex : null;
          const prevState = item ? (item.__workspacePrevState || '') : '';
          if (item) {
            delete item.__workspacePrevContainer;
            delete item.__workspacePrevIndex;
            delete item.__workspacePrevState;
          }
          const event = (evt && (evt.originalEvent || evt.event)) || null;
          if (event) {
            trackWorkspacePointer(event);
          }
          const point = consumeWorkspacePointer();
          if (point && activeDragContext && activeDragContext.origin === 'workspace') {
            const dropBtn = findSidebarButtonFromPoint(point.x, point.y);
            const dropId = dropBtn ? (dropBtn.getAttribute('data-id') || '') : '';
            if (dropBtn && canDropOnSidebar(dropId)) {
              try {
                await handleSidebarDropRequest(dropId, dropBtn);
              } catch (_err) {
                restoreWorkspaceCardPosition(prevContainer, item, prevIndex);
                if (prevState) {
                  refreshWorkspaceCardState(item, prevState);
                }
                updateWorkspaceEmptyStates(ctx);
                setSidebarDropHover(null);
              }
              return;
            }
          }
          if (activeDragContext && activeDragContext.origin === 'workspace') {
            clearActiveDragContext();
          }
          handleWorkspaceDrop(ctx, evt.item, evt.from, evt.to);
        },
      });
    });
  }

  function refreshWorkspaceCardState(card, state){
    if (!card) {
      return;
    }
    const nextState = normalizeWorkspaceState(state);
    card.setAttribute('data-state', nextState);
    const indicator = card.querySelector('.workspace-card__status-indicator');
    if (indicator) {
      indicator.setAttribute('data-state', nextState);
    }
    const labelTextEl = card.querySelector('.workspace-card__tag-text');
    if (labelTextEl) {
      labelTextEl.textContent = workspaceStateLabel(nextState);
    }
  }

  function handleWorkspaceDrop(ctx, card, _from, to){
    if (!card || !to) {
      updateWorkspaceEmptyStates(ctx);
      return;
    }
    const newState = to.getAttribute('data-state-list');
    const prevState = card.getAttribute('data-state') || '';
    if (!newState || newState === prevState) {
      updateWorkspaceEmptyStates(ctx);
      return;
    }
    const itemId = card.getAttribute('data-item-id') || '';
    if (!itemId) {
      updateWorkspaceEmptyStates(ctx);
      return;
    }
    const name = card.getAttribute('data-name') || '';
    refreshWorkspaceCardState(card, newState);
    markElementAsNew(card);
    updateWorkspaceEmptyStates(ctx);
    commitWorkspaceState(ctx, card, itemId, newState, prevState, name);
  }

  async function commitWorkspaceState(ctx, card, itemId, nextState, prevState, name){
    if (!itemId) {
      return;
    }
    card.classList.add('workspace-card--updating');
    try {
      await api.updateWorkspaceState(itemId, nextState);
      announceWorkspaceChange(ctx, name, nextState);
    } catch (err) {
      const list = ctx.lists?.[prevState];
      if (list) {
        list.appendChild(card);
      }
      refreshWorkspaceCardState(card, prevState);
      updateWorkspaceEmptyStates(ctx);
      const code = (err && err.code) || '';
      if (code === 'workspace_item_not_found') {
        alert('הפריט לא נמצא לעדכון');
      } else if (code && code !== 'workspace_state_update_failed') {
        alert(code);
      } else {
        alert('שגיאה בעדכון הסטטוס');
      }
    } finally {
      card.classList.remove('workspace-card--updating');
    }
  }

  function announceWorkspaceChange(ctx, name, state){
    if (!ctx || !ctx.liveRegion) {
      return;
    }
    const label = workspaceStateLabel(state);
    const trimmedName = String(name || '').trim();
    ctx.liveRegion.textContent = trimmedName ? `הפריט "${trimmedName}" הועבר לסטטוס ${label}` : `הסטטוס עודכן ל-${label}`;
  }

  function updateWorkspaceEmptyStates(ctx){
    Object.entries(ctx.lists || {}).forEach(([state, listEl]) => {
      const cards = listEl.querySelectorAll('.workspace-card').length;
      listEl.dataset.empty = cards ? '0' : '1';
      const column = listEl.closest('.workspace-column');
      if (column) {
        const countEl = column.querySelector('.workspace-column__count');
        if (countEl) {
          countEl.textContent = String(cards);
        }
      }
    });
  }

  function restoreWorkspaceCardPosition(container, card, index){
    if (!container || !card || !container.insertBefore) {
      return;
    }
    const children = Array.from(container.children || []).filter(el => el !== card);
    if (typeof index === 'number' && index >= 0 && index < children.length) {
      container.insertBefore(card, children[index]);
    } else {
      container.appendChild(card);
    }
  }

  function moveWorkspaceCardToState(ctx, card, targetState){
    if (!ctx || !card) return;
    const itemId = card.getAttribute('data-item-id') || '';
    if (!itemId) return;
    const prevState = card.getAttribute('data-state') || '';
    if (prevState === targetState) {
      announceWorkspaceChange(ctx, card.getAttribute('data-name') || '', targetState);
      return;
    }
    const list = ctx.lists?.[targetState];
    if (!list) return;
    list.appendChild(card);
    refreshWorkspaceCardState(card, targetState);
    markElementAsNew(card);
    updateWorkspaceEmptyStates(ctx);
    commitWorkspaceState(ctx, card, itemId, targetState, prevState, card.getAttribute('data-name') || '');
  }

  function setupWorkspaceKeyboard(ctx){
    if (ctx.cleanup) {
      try { ctx.cleanup(); } catch (_err) {}
    }
    const handler = (ev) => {
      if (!ev.shiftKey) return;
      const lookup = { '1': 'todo', '2': 'in_progress', '3': 'done' };
      const nextState = lookup[ev.key];
      if (!nextState) return;
      if (!workspaceBoardCtx || workspaceBoardCtx !== ctx) return;
      let targetCard = null;
      if (workspaceActiveCard && ctx.board.contains(workspaceActiveCard)) {
        targetCard = workspaceActiveCard;
      } else {
        targetCard = ctx.board.querySelector('.workspace-card');
      }
      if (!targetCard) return;
      ev.preventDefault();
      workspaceActiveCard = targetCard;
      moveWorkspaceCardToState(ctx, targetCard, nextState);
    };
    document.addEventListener('keydown', handler);
    ctx.keyboardHandler = handler;
    ctx.cleanup = () => {
      document.removeEventListener('keydown', handler);
    };
  }

  function teardownWorkspaceBoard(){
    if (workspaceBoardCtx && typeof workspaceBoardCtx.cleanup === 'function') {
      try { workspaceBoardCtx.cleanup(); } catch (_err) {}
    }
    workspaceBoardCtx = null;
    workspaceActiveCard = null;
  }

  function wireDnd(container, cid){
    let dragEl = null;
    // Support both old .collection-item and new .collection-card classes
    container.querySelectorAll('.collection-card, .collection-item').forEach(el => {
      const handle = el.querySelector('.collection-card__drag') || el.querySelector('.drag');
      if (!handle) return;
      // גרירה מותרת רק מהידית כדי לא לחסום לחיצות על שם הקובץ
      handle.addEventListener('dragstart', (event) => {
        dragEl = el;
        el.classList.add('dragging');
        beginCollectionItemDrag(el, cid, container, 'html');
        if (event && event.dataTransfer) {
          event.dataTransfer.effectAllowed = 'move';
          try {
            const dragPayload = JSON.stringify({
              source: el.getAttribute('data-source') || 'regular',
              file_name: el.getAttribute('data-name') || '',
              folder: el.getAttribute('data-folder') || '',
            });
            event.dataTransfer.setData('text/plain', dragPayload);
          } catch (_err) {}
        }
      });
      handle.addEventListener('dragend', async () => {
        el.classList.remove('dragging');
        if (activeDragContext && activeDragContext.dropInProgress) {
          return;
        }
        clearActiveDragContext();
        // שליחת סדר חדש לשרת — אוספים מכל ה-sections (root + תיקיות) כדי לא לאבד פריטים
        const allContainer = container.closest('#collectionItems') || container;
        const order = Array.from(allContainer.querySelectorAll('.collection-cards .collection-card, .collection-cards .collection-item')).map(x => ({
          source: x.getAttribute('data-source')||'regular',
          file_name: x.getAttribute('data-name')||'',
          folder: x.getAttribute('data-folder')||''
        }));
        try{ await api.reorder(cid, order); } catch(_){ /* ignore */ }
      });

      // --- Fallback לתמיכת מסכי מגע באמצעות Pointer Events ---
      // HTML5 Drag & Drop אינו נתמך היטב במכשירי מגע. נשתמש ב-pointer events כדי לאפשר סידור.
      const supportsPointer = 'PointerEvent' in window;
      if (supportsPointer) {
        let pointerDragging = false;
        let moveHandler = null;
        let upHandler = null;
        let activePointerId = null;

        const cleanupPointerListeners = () => {
          window.removeEventListener('pointermove', moveHandler);
          window.removeEventListener('pointerup', upHandler);
          window.removeEventListener('pointercancel', upHandler);
        };

        const onPointerDown = (ev) => {
          // נטפל רק במגע/עט כדי לא לשבש עכבר בדסקטופ
          const type = (ev.pointerType || '').toLowerCase();
          if (type !== 'touch' && type !== 'pen') return;
          try { ev.preventDefault(); } catch(_) {}
          try { handle.setPointerCapture && handle.setPointerCapture(ev.pointerId); } catch(_) {}
          pointerDragging = true;
          activePointerId = ev.pointerId;
          dragEl = el;
          el.classList.add('dragging');
          beginCollectionItemDrag(el, cid, container, 'pointer');
          const prevUserSelect = document.body.style.userSelect;
          document.body.dataset.prevUserSelect = prevUserSelect || '';
          document.body.style.userSelect = 'none';

          moveHandler = (e) => {
            if (!pointerDragging) return;
            if (e.pointerId !== activePointerId) return;
            try { e.preventDefault(); } catch(_) {}
            const clientX = e.clientX;
            const clientY = e.clientY;
            const after = getDragAfterElement(container, clientY, clientX);
            if (!after) {
              container.appendChild(dragEl);
            } else {
              container.insertBefore(dragEl, after);
            }
            updateSidebarHoverFromPoint(clientX, clientY);
          };

          upHandler = async (e) => {
            if (!pointerDragging) return;
            if (e.pointerId !== activePointerId) return;
            pointerDragging = false;
            el.classList.remove('dragging');
            try { handle.releasePointerCapture && handle.releasePointerCapture(e.pointerId); } catch(_) {}
            // שחזור בחירת טקסט
            document.body.style.userSelect = document.body.dataset.prevUserSelect || '';
            delete document.body.dataset.prevUserSelect;

            const dropBtn = findSidebarButtonFromPoint(e.clientX, e.clientY);
            const dropId = dropBtn ? (dropBtn.getAttribute('data-id') || '') : '';

            // ניקוי מאזינים
            activePointerId = null;
            cleanupPointerListeners();

            if (dropBtn && canDropOnSidebar(dropId)) {
              try {
                await handleSidebarDropRequest(dropId, dropBtn);
                return;
              } catch (_err) {
                // ניפול חזרה להמשך הלוגיקה כדי להשיב את הפריט למקום
              }
            }

            clearActiveDragContext();

            // שליחת סדר חדש לשרת — אוספים מכל ה-sections (root + תיקיות)
            const allCont = container.closest('#collectionItems') || container;
            const order = Array.from(allCont.querySelectorAll('.collection-cards .collection-card, .collection-cards .collection-item')).map(x => ({
              source: x.getAttribute('data-source')||'regular',
              file_name: x.getAttribute('data-name')||'',
              folder: x.getAttribute('data-folder')||''
            }));
            try { await api.reorder(cid, order); } catch(_){ /* ignore */ }
          };

          window.addEventListener('pointermove', moveHandler, { passive: false });
          window.addEventListener('pointerup', upHandler, { passive: false });
          window.addEventListener('pointercancel', upHandler, { passive: false });
        };

        handle.addEventListener('pointerdown', onPointerDown, { passive: false });
      } else {
        // דפדפנים ישנים ללא PointerEvent: שימוש ב-Touch Events כגיבוי
        let touchDragging = false;
        let moveHandler = null;
        let endHandler = null;
        let activeTouchId = null;

        const onTouchStart = (ev) => {
          if (!ev.touches || !ev.touches.length) return;
          try { ev.preventDefault(); } catch(_) {}
          touchDragging = true;
          dragEl = el;
          el.classList.add('dragging');
          beginCollectionItemDrag(el, cid, container, 'touch');
          const prevUserSelect = document.body.style.userSelect;
          document.body.dataset.prevUserSelect = prevUserSelect || '';
          document.body.style.userSelect = 'none';
          // לנעול לזיהוי המגע הראשון שהתחיל את הגרירה
          try {
            activeTouchId = (ev.changedTouches && ev.changedTouches[0] && ev.changedTouches[0].identifier) || ev.touches[0].identifier;
          } catch(_) { activeTouchId = null; }

          moveHandler = (e) => {
            if (!touchDragging) return;
            try { e.preventDefault(); } catch(_) {}
            // מציאת המגע הרלוונטי לפי identifier
            let t = null;
            if (typeof activeTouchId === 'number' || typeof activeTouchId === 'string') {
              const list = e.touches || [];
              for (let i = 0; i < list.length; i++) {
                if (list[i].identifier === activeTouchId) { t = list[i]; break; }
              }
            }
            if (!t) return;
            const clientX = t.clientX;
            const clientY = t.clientY;
            const after = getDragAfterElement(container, clientY, clientX);
            if (!after) {
              container.appendChild(dragEl);
            } else {
              container.insertBefore(dragEl, after);
            }
            updateSidebarHoverFromPoint(clientX, clientY);
          };
          endHandler = async (e) => {
            if (!touchDragging) return;
            // נסיים רק כשאותו מזהה מגע השתחרר
            let endedActive = false;
            const cl = e.changedTouches || [];
            let relevantTouch = null;
            for (let i = 0; i < cl.length; i++) {
              if (cl[i].identifier === activeTouchId) { endedActive = true; relevantTouch = cl[i]; break; }
            }
            if (!endedActive) return;
            touchDragging = false;
            el.classList.remove('dragging');
            document.body.style.userSelect = document.body.dataset.prevUserSelect || '';
            delete document.body.dataset.prevUserSelect;

            activeTouchId = null;
            window.removeEventListener('touchmove', moveHandler);
            window.removeEventListener('touchend', endHandler);
            window.removeEventListener('touchcancel', endHandler);

            const dropBtn = relevantTouch ? findSidebarButtonFromPoint(relevantTouch.clientX, relevantTouch.clientY) : null;
            const dropId = dropBtn ? (dropBtn.getAttribute('data-id') || '') : '';
            if (dropBtn && canDropOnSidebar(dropId)) {
              try {
                await handleSidebarDropRequest(dropId, dropBtn);
                return;
              } catch (_err) {
                // במקרה של כשל בהעברה נמשיך להמשך הלוגיקה כדי להשיב את הפריט
              }
            }

            clearActiveDragContext();

            // Support both old and new card classes
            const order = Array.from(container.querySelectorAll('.collection-card, .collection-item')).map(x => ({
              source: x.getAttribute('data-source')||'regular',
              file_name: x.getAttribute('data-name')||''
            }));
            try { await api.reorder(cid, order); } catch(_){ /* ignore */ }
          };

          window.addEventListener('touchmove', moveHandler, { passive: false });
          window.addEventListener('touchend', endHandler);
          window.addEventListener('touchcancel', endHandler);
        };
        handle.addEventListener('touchstart', onTouchStart, { passive: false });
      }
    });
    container.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (!dragEl) return;
      const after = getDragAfterElement(container, e.clientY, e.clientX);
      if (after == null) {
        container.appendChild(dragEl);
      } else {
        container.insertBefore(dragEl, after);
      }
    });
  }

  function getDragAfterElement(container, y, x){
    // Support both old and new card classes
    const els = [...container.querySelectorAll('.collection-card:not(.dragging), .collection-item:not(.dragging)')];

    // Check if container uses grid layout (for collection-cards)
    const isGrid = container.classList.contains('collection-cards');

    if (isGrid && typeof x === 'number') {
      // For grid layouts, find the element closest to cursor position in 2D
      let closest = null;
      let closestDist = Infinity;

      for (const child of els) {
        const box = child.getBoundingClientRect();
        const centerX = box.left + box.width / 2;
        const centerY = box.top + box.height / 2;

        // Only consider elements below or to the right of cursor
        if (y < box.bottom && x < box.right) {
          const dist = Math.sqrt(Math.pow(x - centerX, 2) + Math.pow(y - centerY, 2));
          if (dist < closestDist) {
            closestDist = dist;
            closest = child;
          }
        }
      }
      return closest;
    }

    // For vertical list layouts, use original Y-based logic
    return els.reduce((closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = y - box.top - box.height / 2;
      if (offset < 0 && offset > closest.offset) {
        return { offset, element: child }
      } else {
        return closest
      }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
  }

  function escapeHtml(s){ const d=document.createElement('div'); d.textContent=String(s||''); return d.innerHTML; }

  // --- התאמת טקסט דינמית לאורכים משתנים ---
  function autoFitText(selector, opts){
    try {
      const {
        minPx = 12,
        maxPx = 16,
        allowWrap = false,
        wrapClass = 'is-wrapped',
      } = opts || {};
      const els = document.querySelectorAll(selector);
      if (!els || !els.length) return;
      els.forEach(el => {
        if (!(el instanceof HTMLElement)) return;
        if (allowWrap && wrapClass) {
          el.classList.remove(wrapClass);
        }
        // שחזור גודל בסיסי אם נשמר, אחרת קבע ושמור
        let base = Number(el.dataset.baseFontPx || '');
        if (!base || Number.isNaN(base)) {
          base = parseFloat(getComputedStyle(el).fontSize) || maxPx;
          el.dataset.baseFontPx = String(base);
        }
        // אפס לגודל בסיס לפני מדידה
        el.style.fontSize = base + 'px';
        // כפייה של חישוב פריסה
        const available = el.clientWidth;
        const needed = el.scrollWidth;
        if (available <= 0) return;
        if (needed <= available) {
          // תוודא שלא עברנו את maxPx
          const current = parseFloat(getComputedStyle(el).fontSize) || base;
          const target = Math.min(Math.max(current, minPx), maxPx);
          el.style.fontSize = target + 'px';
          return;
        }
        const ratio = Math.max(minPx / base, Math.min(1, available / Math.max(1, needed)));
        const next = Math.max(minPx, Math.min(maxPx, Math.floor(base * ratio)));
        el.style.fontSize = next + 'px';
        if (allowWrap && wrapClass && next <= minPx) {
          if (el.scrollWidth > el.clientWidth + 1) {
            el.classList.add(wrapClass);
          }
        }
      });
    } catch(_e){ /* ignore */ }
  }

  // תזמון/חסימה של ארועי resize כדי לא להציף חישובים
  function debounce(fn, wait){
    let t = null;
    return function(...args){
      if (t) clearTimeout(t);
      t = setTimeout(() => {
        t = null;
        try { fn.apply(this, args); } catch(_) {}
      }, wait);
    };
  }

  function throttle(fn, wait){
    let t = null;
    return function(){
      if (t) return;
      t = setTimeout(() => { t = null; try { fn(); } catch(_){} }, wait);
    }
  }

  // עדכון אוטומטי בהתאמת חלון
  const onResize = throttle(() => {
    autoFitText('#collectionItems .file', { minPx: 12, maxPx: 16 });
    autoFitText('#collectionItems .collection-card__name', { minPx: 12, maxPx: 16, allowWrap: true });
    autoFitText('#collectionsSidebar .sidebar-item .name', { minPx: 12, maxPx: 16 });
    autoFitText('.workspace-card__name', { minPx: 12, maxPx: 16, allowWrap: true });
  }, 150);
  window.addEventListener('resize', onResize);

  // חשיפת API מינימלי לכפתור "הוסף לאוסף"
  window.CollectionsUI = {
    async addFilesToCollection(collectionId, fileNames, tags = []){
      if (!Array.isArray(fileNames) || !fileNames.length) return {ok:false, error:'אין קבצים'};
      const tagList = Array.isArray(tags) ? tags : [];
      const items = fileNames.map(fn => ({source:'regular', file_name: String(fn), tags: tagList}));
      return api.addItems(String(collectionId), items);
    },
    async addFileToCollection(collectionId, fileName, tags = []){
      const tagList = Array.isArray(tags) ? tags : [];
      const items = [{ source: 'regular', file_name: String(fileName), tags: tagList }];
      return api.addItems(String(collectionId), items);
    },
    refreshSidebar: ensureCollectionsSidebar,
  };
  async function initCollectionsPage(){
    initTagsFeatureFlag();
    initTagsToolbarFlag();
    await initTagsMetadata();
    const initialId = consumeInitialCollectionId();
    // טען את הסיידבר במקביל לטעינת הפריטים כדי לא "לשרשר" שתי בקשות ברצף בתחילת העמוד.
    const sidebarPromise = ensureCollectionsSidebar().catch(() => {});
    if (!initialId) {
      await sidebarPromise;
      return;
    }
    try {
      await Promise.all([
        sidebarPromise,
        renderCollectionItems(initialId),
      ]);
    } catch (_err) {
      const container = document.getElementById('collectionsContent');
      if (container) {
        container.innerHTML = '<div class="error">האוסף שביקשת לא נמצא</div>';
      }
    }
  }

  // אתחול אוטומטי אם קיימים אזורים בעמוד
  window.addEventListener('DOMContentLoaded', () => {
    initCollectionsPage().catch(() => {});

    // Global fallback handler לכפתור עריכת תגיות
    // מטפל בלחיצות שלא נתפסות על ידי handlers ספציפיים
    document.addEventListener('click', (ev) => {
      const tagBtn = ev.target.closest('.btn-tag-edit');
      if (!tagBtn) return;

      // מונע התנהגות ברירת מחדל ועצירת propagation
      ev.preventDefault();
      ev.stopPropagation();

      if (!TAGS_FEATURE_ENABLED) {
        showToast('תיוג קבצים כבוי כרגע', 'warning');
        return;
      }

      const itemId = tagBtn.dataset.itemId || '';
      if (!itemId) {
        showToast('שגיאה: חסר מזהה פריט', 'error');
        return;
      }

      // מציאת האלמנט המכיל (card או row) לקבלת התגיות הנוכחיות
      const itemEl = tagBtn.closest('.workspace-card') ||
                     tagBtn.closest('.collection-card') ||
                     tagBtn.closest('.collection-item') ||
                     document.querySelector(`[data-item-id="${itemId}"]`);
      const currentTags = collectTagsFromElement(itemEl);

      try {
        openTagsEditorModal(itemId, currentTags);
      } catch (err) {
        showToast('שגיאה בפתיחת עורך התגיות: ' + (err.message || err), 'error');
      }
    }, true); // capture phase כדי לתפוס לפני handlers אחרים
  });
})();

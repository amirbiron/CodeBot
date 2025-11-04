(function(){
  const pageRoot = document.querySelector('.shared-collection-page');
  if (!pageRoot) return;

  const iconEl = document.getElementById('sharedCollectionIcon');
  const nameEl = document.getElementById('sharedCollectionName');
  const metaEl = document.getElementById('sharedCollectionMeta');
  const descriptionEl = document.getElementById('sharedCollectionDescription');
  const itemsContainer = document.getElementById('sharedCollectionItems');
  const visibilityNoteEl = document.querySelector('.shared-collection-visibility-note');
  const viewerEl = document.getElementById('sharedCollectionViewer');
  const downloadAllBtn = document.getElementById('sharedCollectionDownloadAll');

  const token = pageRoot.getAttribute('data-share-token') || '';
  const scriptRootAttr = pageRoot.getAttribute('data-script-root') || '';
  const apiUrlAttr = pageRoot.getAttribute('data-api-url') || '';

  let exportUrl = '';
  let activeFileId = '';
  let currentItems = [];

  const joinWithScriptRoot = (root, path) => {
    const normalizedPath = String(path || '');
    if (!root) {
      return normalizedPath;
    }
    const normalizedRoot = String(root).trim().replace(/\/$/, '');
    if (!normalizedPath.startsWith('/')) {
      return `${normalizedRoot}/${normalizedPath}`;
    }
    return `${normalizedRoot}${normalizedPath}`;
  };

  const apiUrl = apiUrlAttr || (token ? joinWithScriptRoot(scriptRootAttr, `/api/collections/shared/${encodeURIComponent(token)}`) : '');

  if (!token || !apiUrl) {
    renderError('קישור השיתוף אינו תקין');
    return;
  }

  function escapeHtml(value){
    const div = document.createElement('div');
    div.textContent = String(value == null ? '' : value);
    return div.innerHTML;
  }

  function renderError(message){
    if (nameEl) nameEl.textContent = 'שגיאה בטעינה';
    if (metaEl) metaEl.textContent = '';
    if (descriptionEl) descriptionEl.textContent = '';
    updateDownloadAllButton('');
    if (itemsContainer) {
      itemsContainer.innerHTML = `<div class="error">${escapeHtml(message || 'שגיאה בהצגת האוסף')}</div>`;
    }
    if (viewerEl) {
      viewerEl.innerHTML = `<div class="viewer-error">${escapeHtml(message || 'שגיאה בהצגת האוסף')}</div>`;
    }
  }

  function formatDate(value){
    if (!value) return '';
    try {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return '';
      return new Intl.DateTimeFormat('he-IL', {
        dateStyle: 'medium',
        timeStyle: 'short'
      }).format(date);
    } catch (_err) {
      return '';
    }
  }

  function updateDownloadAllButton(url){
    if (!downloadAllBtn) return;
    exportUrl = url || '';
    if (exportUrl) {
      downloadAllBtn.disabled = false;
    } else {
      downloadAllBtn.disabled = true;
    }
  }

  function setViewerPlaceholder(){
    if (viewerEl) {
      viewerEl.innerHTML = '<div class="viewer-placeholder">בחרו קובץ מתוך הרשימה כדי לצפות בתוכן</div>';
    }
  }

  function setViewerLoading(){
    if (viewerEl) {
      viewerEl.innerHTML = '<div class="loading">טוען תוכן…</div>';
    }
  }

  function markActiveItem(fileId){
    if (!itemsContainer) return;
    const items = itemsContainer.querySelectorAll('.shared-collection-item');
    items.forEach((el) => {
      if (!el.dataset) return;
      if (fileId && el.dataset.fileId === fileId) {
        el.classList.add('active');
        el.setAttribute('aria-current', 'true');
      } else {
        el.classList.remove('active');
        el.removeAttribute('aria-current');
      }
    });
  }

  function renderItems(items){
    currentItems = Array.isArray(items) ? items : [];
    if (!itemsContainer) return;
    if (!currentItems.length) {
      itemsContainer.innerHTML = '<div class="empty">אין עדיין פריטים משותפים</div>';
      setViewerPlaceholder();
      return;
    }
    const html = currentItems.map((item) => {
      const name = item && item.file_name ? item.file_name : item && item.name ? item.name : '';
      const note = item && item.note ? String(item.note) : '';
      const pinned = item && item.pinned;
      const share = item && item.share ? item.share : {};
      const badges = pinned ? '<span class="shared-item-badge">📌 מוצמד</span>' : '';
      const metaParts = [];
      if (share.language) {
        metaParts.push(`שפה: ${escapeHtml(share.language)}`);
      }
      if (share.size_label) {
        metaParts.push(`גודל: ${escapeHtml(share.size_label)}`);
      }
      if (Number.isFinite(share.lines_count)) {
        metaParts.push(`${Number(share.lines_count)} שורות`);
      }
      const metaHtml = metaParts.length ? `<div class="shared-item-meta">${metaParts.join(' · ')}</div>` : '';
      return `
        <li class="shared-collection-item" tabindex="0" data-file-id="${escapeHtml(share.file_id || '')}" data-view-url="${escapeHtml(share.view_url || '')}" data-download-url="${escapeHtml(share.download_url || '')}">
          <div class="shared-item-row">
            <span class="shared-item-name">${escapeHtml(name || 'ללא שם')}</span>
            <div class="shared-item-actions">
              ${share.view_url ? '<button type="button" class="shared-item-action" data-action="view">👁️ הצג</button>' : ''}
              ${share.download_url ? '<button type="button" class="shared-item-action" data-action="download">📥 הורד</button>' : ''}
              ${badges}
            </div>
          </div>
          ${note ? `<div class="shared-item-note">${escapeHtml(note)}</div>` : ''}
          ${metaHtml}
        </li>
      `;
    }).join('');
    itemsContainer.innerHTML = `<ul class="shared-collection-list">${html}</ul>`;
    markActiveItem(activeFileId);
  }

  function renderCollection(collection, items, itemsTotal){
    const allowedIcons = ["📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡","⭐","🔖","🚀"];
    const icon = collection && allowedIcons.includes(collection.icon) ? collection.icon : '📂';
    const name = collection && collection.name ? collection.name : 'אוסף משותף';
    const description = collection && collection.description ? collection.description : '';
    const updatedAt = collection && collection.updated_at ? formatDate(collection.updated_at) : '';

    const metaParts = [];
    const total = Number.isFinite(itemsTotal) ? Number(itemsTotal) : (Array.isArray(items) ? items.length : Number(collection && collection.items_count));
    if (Number.isFinite(total)) {
      metaParts.push(total === 1 ? 'פריט אחד' : `${total} פריטים`);
    }
    if (updatedAt) {
      metaParts.push(`עודכן ${updatedAt}`);
    }

    if (iconEl) {
      iconEl.textContent = icon;
    }
    if (nameEl) {
      nameEl.textContent = name;
    }
    if (metaEl) {
      metaEl.textContent = metaParts.join(' · ');
    }
    if (descriptionEl) {
      descriptionEl.textContent = description;
      descriptionEl.style.display = description ? '' : 'none';
    }
    if (visibilityNoteEl) {
      visibilityNoteEl.innerHTML = '<span class="badge badge-link">קישור</span> כל מי שמחזיק בקישור הזה יכול לצפות בקבצים, להוריד פריטים בודדים או את כל האוסף כקובץ ZIP.';
    }

    renderItems(items);
  }

  function renderViewer(file){
    if (!viewerEl) return;
    if (!file) {
      setViewerPlaceholder();
      return;
    }
    const metaParts = [];
    if (file.language) metaParts.push(`שפה: ${escapeHtml(file.language)}`);
    if (file.size_label) metaParts.push(`גודל: ${escapeHtml(file.size_label)}`);
    if (Number.isFinite(file.lines_count)) metaParts.push(`${Number(file.lines_count)} שורות`);
    const metaHtml = metaParts.length ? `<div class="shared-viewer-meta">${metaParts.join(' · ')}</div>` : '';
    const header = `
      <div class="shared-viewer-header">
        <div class="file-name">${escapeHtml(file.file_name || 'קובץ')}</div>
        ${file.download_url ? '<button type="button" class="shared-viewer-download" data-download-url="' + escapeHtml(file.download_url) + '">📥 הורד</button>' : ''}
      </div>
      ${metaHtml}
    `;
    let body = '';
    if (file.is_binary) {
      body = '<div class="viewer-error">לא ניתן להציג תצוגה מקדימה לקובץ בינארי, ניתן להוריד אותו באמצעות הכפתור.</div>';
    } else if (file.content) {
      body = `<pre class="viewer-content"><code>${escapeHtml(file.content)}</code></pre>`;
    } else {
      body = '<div class="viewer-error">התוכן לא זמין לצפייה</div>';
    }
    viewerEl.innerHTML = header + body;
    const downloadBtn = viewerEl.querySelector('.shared-viewer-download');
    if (downloadBtn) {
      downloadBtn.addEventListener('click', () => {
        const url = downloadBtn.getAttribute('data-download-url');
        if (url) {
          window.open(url, '_blank');
        }
      });
    }
  }

  async function fetchJson(url){
    const response = await fetch(url, { headers: { 'Accept': 'application/json' }, cache: 'no-store' });
    if (!response.ok) {
      const errorText = response.status === 404 ? 'לא נמצא' : 'בקשה נכשלה';
      throw new Error(errorText);
    }
    return response.json();
  }

  async function loadFile(viewUrl, fileId){
    if (!viewUrl) return;
    activeFileId = fileId || '';
    markActiveItem(activeFileId);
    setViewerLoading();
    try {
      const data = await fetchJson(viewUrl);
      if (!data || data.ok === false) {
        throw new Error(data && data.error ? data.error : 'שגיאה בטעינת הקובץ');
      }
      const file = data.file || {};
      renderViewer({
        id: file.id,
        file_name: file.file_name,
        content: file.content,
        language: file.language,
        size_label: file.size_label,
        size_bytes: file.size_bytes,
        lines_count: file.lines_count,
        download_url: file.download_url,
        is_binary: file.is_binary,
        updated_at: file.updated_at,
        created_at: file.created_at,
        source: file.source,
      });
    } catch (error) {
      const message = error && error.message ? error.message : 'שגיאה בטעינת הקובץ';
      if (viewerEl) {
        viewerEl.innerHTML = `<div class="viewer-error">${escapeHtml(message)}</div>`;
      }
    }
  }

  async function load(){
    if (itemsContainer) {
      itemsContainer.innerHTML = '<div class="loading">טוען…</div>';
    }
    setViewerPlaceholder();
    try {
      const data = await fetchJson(apiUrl);
      if (!data || data.ok === false) {
        throw new Error(data && data.error ? data.error : 'שגיאה בהצגת האוסף');
      }
      updateDownloadAllButton(data.export_url || '');
      renderCollection(data.collection || {}, data.items || [], data.items_total);
      const firstItem = Array.isArray(data.items) ? data.items.find(it => it && it.share && it.share.view_url) : null;
      if (firstItem && firstItem.share && firstItem.share.view_url) {
        loadFile(firstItem.share.view_url, firstItem.share.file_id || '');
      }
    } catch (error) {
      renderError(error && error.message ? error.message : 'שגיאה בטעינת האוסף המשותף');
    }
  }

  if (downloadAllBtn) {
    downloadAllBtn.addEventListener('click', () => {
      if (downloadAllBtn.disabled || !exportUrl) return;
      window.open(exportUrl, '_blank');
    });
  }

  if (itemsContainer) {
    itemsContainer.addEventListener('click', (event) => {
      const actionBtn = event.target.closest('.shared-item-action');
      const itemEl = event.target.closest('.shared-collection-item');
      if (!itemEl) return;
      const viewUrl = itemEl.dataset.viewUrl || '';
      const downloadUrl = itemEl.dataset.downloadUrl || '';
      const fileId = itemEl.dataset.fileId || '';
      if (actionBtn) {
        const action = actionBtn.getAttribute('data-action');
        if (action === 'view') {
          event.preventDefault();
          loadFile(viewUrl, fileId);
        } else if (action === 'download' && downloadUrl) {
          event.preventDefault();
          window.open(downloadUrl, '_blank');
        }
        return;
      }
      if (viewUrl) {
        loadFile(viewUrl, fileId);
      }
    });

    itemsContainer.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const itemEl = event.target.closest('.shared-collection-item');
      if (!itemEl) return;
      const viewUrl = itemEl.dataset.viewUrl || '';
      const fileId = itemEl.dataset.fileId || '';
      if (viewUrl) {
        event.preventDefault();
        loadFile(viewUrl, fileId);
      }
    });
  }

  window.addEventListener('DOMContentLoaded', load, { once: true });
})();

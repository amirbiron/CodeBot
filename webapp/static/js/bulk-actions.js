(function(){
  function postJSON(url, body, opts) {
    return fetch(url, Object.assign({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }, opts || {}));
  }

  function ensureToolbar() {
    let el = document.getElementById('bulkActionsToolbar');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'bulkActionsToolbar';
    el.className = 'bulk-actions-toolbar hidden';
    el.innerHTML = '<div class="toolbar-content">\
      <div class="selection-info"><span class="selected-count">0</span> קבצים נבחרים</div>\
      <div class="toolbar-actions">\
        <button class="btn btn-icon" data-action="fav"><i class="fas fa-star"></i> הוסף למועדפים</button>\
        <button class="btn btn-icon" data-action="tag"><i class="fas fa-tags"></i> הוסף תגיות</button>\
        <button class="btn btn-icon" data-action="zip"><i class="fas fa-file-archive"></i> הורד כ-ZIP</button>\
        <button class="btn btn-secondary btn-icon" data-action="clear"><i class="fas fa-times"></i> ביטול בחירה</button>\
      </div></div>';
    document.body.appendChild(el);
    el.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      const action = btn.getAttribute('data-action');
      if (action === 'fav') bulkAddToFavorites();
      else if (action === 'tag') showBulkTagDialog();
      else if (action === 'zip') bulkDownloadZip();
      else if (action === 'clear') window.multiSelect && window.multiSelect.clearSelection();
    });
    return el;
  }

  function getSelectedIds(){ return (window.multiSelect && window.multiSelect.getSelectedIds()) || []; }
  function selectedCount(){ return (window.multiSelect && window.multiSelect.getSelectedCount()) || 0; }

  function showNotification(message, type){
    // minimal toast
    const contId = 'notificationContainer';
    let cont = document.getElementById(contId);
    if (!cont) { cont = document.createElement('div'); cont.id = contId; cont.className = 'notification-container'; document.body.appendChild(cont); }
    const item = document.createElement('div');
    item.className = `notification ${type||'info'}`;
    item.innerHTML = `<div class="notification-content"><i class="fas fa-info-circle"></i><div>${message}</div></div>`;
    cont.appendChild(item);
    requestAnimationFrame(() => item.classList.add('show'));
    setTimeout(() => { item.classList.add('fade-out'); setTimeout(()=> item.remove(), 300); }, 3000);
  }

  function showProcessing(text){
    let ov = document.getElementById('processingOverlay');
    if (!ov) {
      ov = document.createElement('div');
      ov.id = 'processingOverlay';
      ov.className = 'processing-overlay hidden';
      ov.innerHTML = '<div class="processing-content">\
        <div class="spinner"></div>\
        <div class="processing-text"></div>\
      </div>';
      document.body.appendChild(ov);
    }
    ov.querySelector('.processing-text').textContent = text || 'מעבד...';
    ov.classList.remove('hidden');
  }
  function hideProcessing(){ const ov = document.getElementById('processingOverlay'); if (ov) ov.classList.add('hidden'); }

  async function bulkAddToFavorites() {
    const ids = getSelectedIds();
    if (ids.length === 0) return;
    showProcessing(`מוסיף למועדפים ${ids.length} קבצים...`);
    try {
      const resp = await postJSON('/api/files/bulk-favorite', { file_ids: ids });
      const js = await (resp.headers.get('content-type')||'').includes('application/zip') ? null : resp.json();
      if (resp.ok && js && js.ok) {
        showNotification(`עודכנו ${js.updated} פריטים`, 'success');
      } else {
        showNotification(js && js.error ? js.error : 'שגיאה בעדכון מועדפים', 'error');
      }
    } catch (e) {
      showNotification('שגיאה ברשת', 'error');
    } finally { hideProcessing(); }
  }

  function openModal(title, bodyHTML, onConfirm){
    const ov = document.createElement('div');
    ov.className = 'modal-overlay';
    ov.innerHTML = `<div class="modal-content">\
      <div class="modal-header"><h3><i class=\"fas fa-tags\"></i> ${title}</h3><button class=\"modal-close\">×</button></div>\
      <div class="modal-body">${bodyHTML}</div>\
      <div class="modal-footer">\
        <button class="btn btn-secondary">בטל</button>\
        <button class="btn btn-primary">אשר</button>\
      </div></div>`;
    document.body.appendChild(ov);
    const close = ()=> ov.remove();
    ov.querySelector('.modal-close').onclick = close;
    ov.querySelector('.btn.btn-secondary').onclick = close;
    ov.querySelector('.btn.btn-primary').onclick = async () => { try { await onConfirm(); } finally { close(); } };
  }

  function showBulkTagDialog(){
    const ids = getSelectedIds();
    if (ids.length === 0) return;
    const body = '<p>הוסף תגיות (מופרדות בפסיקים):</p>\
      <input type="text" class="tag-input" id="bulkTagsInput" placeholder="#backend, performance, bugfix" />';
    openModal('הוספת תגיות', body, async () => {
      const val = document.getElementById('bulkTagsInput').value || '';
      const tags = val.split(/[,#\n]+/).map(s => s.trim()).filter(Boolean);
      if (tags.length === 0) return;
      showProcessing('מוסיף תגיות...');
      try {
        const resp = await postJSON('/api/files/bulk-tag', { file_ids: ids, tags });
        const js = await resp.json();
        if (resp.ok && js.ok) showNotification(`תגיות נוספו (${js.tags_added})`, 'success');
        else showNotification(js.error || 'שגיאה בהוספת תגיות', 'error');
      } catch (e) {
        showNotification('שגיאת רשת', 'error');
      } finally { hideProcessing(); }
    });
  }

  async function bulkDownloadZip(){
    const ids = getSelectedIds();
    if (ids.length === 0) return;
    showProcessing('מייצר ZIP...');
    try {
      const resp = await postJSON('/api/files/create-zip', { file_ids: ids });
      const blob = await resp.blob();
      if (resp.ok) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'codebot-files.zip';
        document.body.appendChild(a); a.click(); a.remove();
        window.URL.revokeObjectURL(url);
        showNotification('ZIP ירד בהצלחה', 'success');
      } else {
        showNotification('יצירת ZIP נכשלה', 'error');
      }
    } catch (e) {
      showNotification('שגיאת רשת', 'error');
    } finally { hideProcessing(); }
  }

  window.bulkActions = { bulkAddToFavorites, showBulkTagDialog, bulkDownloadZip, showNotification, showProcessing, hideProcessing };
  document.addEventListener('DOMContentLoaded', ensureToolbar);
})();

(function(){
  const pageRoot = document.querySelector('.shared-collection-page');
  if (!pageRoot) return;

  const iconEl = document.getElementById('sharedCollectionIcon');
  const nameEl = document.getElementById('sharedCollectionName');
  const metaEl = document.getElementById('sharedCollectionMeta');
  const descriptionEl = document.getElementById('sharedCollectionDescription');
  const itemsContainer = document.getElementById('sharedCollectionItems');
  const visibilityNoteEl = document.querySelector('.shared-collection-visibility-note');

  const token = pageRoot.getAttribute('data-share-token') || '';
  const apiUrlAttr = pageRoot.getAttribute('data-api-url') || '';
  const apiUrl = apiUrlAttr || (token ? `/api/collections/shared/${encodeURIComponent(token)}` : '');

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
    if (itemsContainer) {
      itemsContainer.innerHTML = `<div class="error">${escapeHtml(message || 'שגיאה בהצגת האוסף')}</div>`;
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

  function renderItems(items){
    if (!itemsContainer) return;
    if (!Array.isArray(items) || !items.length) {
      itemsContainer.innerHTML = '<div class="empty">אין עדיין פריטים משותפים</div>';
      return;
    }
    const html = items.map((item) => {
      const name = item && item.file_name ? item.file_name : item && item.name ? item.name : '';
      const note = (item && item.note) ? String(item.note) : '';
      const pinned = !!(item && item.pinned);
      const badges = [];
      if (pinned) {
        badges.push('<span class="shared-item-badge">📌 מוצמד</span>');
      }
      return `
        <li class="shared-collection-item">
          <div class="shared-item-row">
            <span class="shared-item-name">${escapeHtml(name || 'ללא שם')}</span>
            ${badges.join('')}
          </div>
          ${note ? `<div class="shared-item-note">${escapeHtml(note)}</div>` : ''}
        </li>
      `;
    }).join('');
    itemsContainer.innerHTML = `<ul class="shared-collection-list">${html}</ul>`;
  }

  function renderCollection(collection, items){
    const allowedIcons = ["📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡","⭐","🔖","🚀"];
    const icon = collection && allowedIcons.includes(collection.icon) ? collection.icon : '📂';
    const name = collection && collection.name ? collection.name : 'אוסף משותף';
    const description = collection && collection.description ? collection.description : '';
    const updatedAt = collection && collection.updated_at ? formatDate(collection.updated_at) : '';
    const share = (collection && collection.share) || {};
    const visibility = String(share.visibility || 'link').toLowerCase();

    const itemsCount = Array.isArray(items) ? items.length : Number(collection && collection.items_count);
    const metaParts = [];
    if (Number.isFinite(itemsCount)) {
      const count = Number(itemsCount);
      metaParts.push(count === 1 ? 'פריט אחד' : `${count} פריטים`);
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
      if (visibility === 'private') {
        visibilityNoteEl.innerHTML = `<span class="badge badge-private">פרטי</span> רק אתה רואה את האוסף כרגע.`;
      } else {
        visibilityNoteEl.innerHTML = `<span class="badge badge-link">קישור</span> כל מי שמחזיק בקישור הזה יכול לצפות ברשימה. לפתיחת קבצים דרושה התחברות ל-Code Keeper.`;
      }
    }

    renderItems(items);
  }

  async function load(){
    if (itemsContainer) {
      itemsContainer.innerHTML = '<div class="loading">טוען…</div>';
    }
    try {
      const response = await fetch(apiUrl, {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
        cache: 'no-store'
      });
      if (!response.ok) {
        renderError(response.status === 404 ? 'האוסף הזה לא זמין יותר לשיתוף' : 'שגיאה בטעינת האוסף המשותף');
        return;
      }
      const data = await response.json().catch(() => null);
      if (!data || data.ok === false) {
        const msg = data && data.error ? data.error : 'שגיאה בהצגת האוסף';
        renderError(msg);
        return;
      }
      renderCollection(data.collection || {}, data.items || []);
    } catch (_err) {
      renderError('בעיית רשת בעת טעינת השיתוף');
    }
  }

  window.addEventListener('DOMContentLoaded', load, { once: true });
})();

(function(){
  class MultiSelectManager {
    constructor() {
      this.selectedFiles = new Map();
      this.toolbar = document.getElementById('bulkActionsToolbar');
      this.lastSelectedIndex = -1;
      this.init();
    }
    init() {
      this.setupCheckboxListeners();
      this.setupKeyboardShortcuts();
      this.setupSelectAllButton();
      this.restoreSelection();
      window.multiSelect = this;
    }
    setupCheckboxListeners() {
      document.addEventListener('change', (e) => {
        const el = e.target;
        if (el && el.classList && el.classList.contains('file-checkbox')) {
          this.handleFileSelection(el);
        }
      });
      document.addEventListener('click', (e) => {
        const el = e.target;
        if (el && el.classList && el.classList.contains('file-checkbox') && e.shiftKey) {
          e.preventDefault();
          this.handleRangeSelection(el);
        }
      });
    }
    handleFileSelection(checkbox) {
      const fileId = checkbox.dataset.fileId;
      const fileName = checkbox.dataset.fileName;
      const card = checkbox.closest('.file-card');
      if (checkbox.checked) {
        this.selectedFiles.set(fileId, { id: fileId, name: fileName });
        if (card) card.classList.add('selected');
      } else {
        this.selectedFiles.delete(fileId);
        if (card) card.classList.remove('selected');
      }
      const all = Array.from(document.querySelectorAll('.file-checkbox'));
      this.lastSelectedIndex = all.indexOf(checkbox);
      this.updateToolbar();
      this.persistSelection();
    }
    handleRangeSelection(checkbox) {
      const all = Array.from(document.querySelectorAll('.file-checkbox'));
      const currentIndex = all.indexOf(checkbox);
      if (this.lastSelectedIndex === -1) {
        this.lastSelectedIndex = currentIndex;
        return;
      }
      const start = Math.min(this.lastSelectedIndex, currentIndex);
      const end = Math.max(this.lastSelectedIndex, currentIndex);
      for (let i = start; i <= end; i++) {
        const cb = all[i];
        if (!cb.checked) {
          cb.checked = true;
          this.handleFileSelection(cb);
        }
      }
    }
    updateToolbar() {
      const count = this.selectedFiles.size;
      if (!this.toolbar) return;
      const countEl = this.toolbar.querySelector('.selected-count');
      if (count > 0) {
        if (countEl) countEl.textContent = String(count);
        this.toolbar.classList.remove('hidden');
        this.toolbar.classList.add('visible');
        document.querySelectorAll('.file-selection').forEach(el => el.classList.add('has-selection'));
      } else {
        this.toolbar.classList.remove('visible');
        this.toolbar.classList.add('hidden');
        document.querySelectorAll('.file-selection').forEach(el => el.classList.remove('has-selection'));
      }
    }
    setupKeyboardShortcuts() {
      document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
          if (['INPUT','TEXTAREA'].includes((e.target && e.target.tagName) || '')) return;
          e.preventDefault();
          this.selectAll();
        }
        if (e.key === 'Escape') {
          this.clearSelection();
        }
      });
    }
    setupSelectAllButton() {
      const filtersSection = document.querySelector('.filters-section');
      if (filtersSection && !document.getElementById('selectAllBtn')) {
        const btn = document.createElement('button');
        btn.id = 'selectAllBtn';
        btn.className = 'btn btn-secondary btn-icon';
        btn.innerHTML = '<i class="fas fa-check-square"></i> בחר הכל';
        btn.onclick = () => this.selectAll();
        filtersSection.appendChild(btn);
      }
    }
    selectAll() {
      const checkboxes = document.querySelectorAll('.file-checkbox');
      const allChecked = this.selectedFiles.size === checkboxes.length;
      checkboxes.forEach(cb => {
        cb.checked = !allChecked;
        this.handleFileSelection(cb);
      });
    }
    clearSelection() {
      document.querySelectorAll('.file-checkbox:checked').forEach(cb => {
        cb.checked = false;
        this.handleFileSelection(cb);
      });
    }
    persistSelection() {
      const ids = Array.from(this.selectedFiles.keys());
      sessionStorage.setItem('selectedFiles', JSON.stringify(ids));
    }
    restoreSelection() {
      try {
        const stored = sessionStorage.getItem('selectedFiles');
        if (!stored) return;
        const ids = JSON.parse(stored);
        ids.forEach(id => {
          const cb = document.querySelector(`.file-checkbox[data-file-id="${id}"]`);
          if (cb) {
            cb.checked = true;
            this.handleFileSelection(cb);
          }
        });
      } catch (_) {
        sessionStorage.removeItem('selectedFiles');
      }
    }
    getSelectedIds() { return Array.from(this.selectedFiles.keys()); }
    getSelectedCount() { return this.selectedFiles.size; }
  }
  document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.files-grid') || document.querySelector('.file-card')) {
      new MultiSelectManager();
    }
  });
})();

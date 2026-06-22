(function(){
  // Legacy (no-module) editor manager — supports older browsers (no ESM)
  // Avoid modern syntax: no arrow functions, no let/const, no template strings, no classes
  try { if (typeof console !== 'undefined') console.log('[EditorManager] Legacy script loaded at:', new Date().toISOString()); } catch(_){ }

  function safeLog(){ try { if (typeof console !== 'undefined' && console.log) console.log.apply(console, arguments); } catch(_){} }
  function safeWarn(){ try { if (typeof console !== 'undefined' && console.warn) console.warn.apply(console, arguments); } catch(_){} }

  function withTimeout(promise, ms, label){
    return new Promise(function(resolve, reject){
      var settled = false;
      var id = setTimeout(function(){
        if (settled) return;
        settled = true;
        var err = new Error('timeout_' + (label || 'operation'));
        err.code = 'ETIMEOUT';
        reject(err);
      }, ms);
      Promise.resolve(promise).then(function(val){ if (!settled){ settled = true; clearTimeout(id); resolve(val); } }, function(err){ if (!settled){ settled = true; clearTimeout(id); reject(err); } });
    });
  }

  function absoluteStatic(path){
    try {
      var origin = (window.location && window.location.origin) ? window.location.origin : '';
      return origin + path;
    } catch(_){ return path; }
  }

  function loadLocalBundleIfNeeded(timeoutMs){
    if (window.CodeMirror6 && window.CodeMirror6.EditorState && window.CodeMirror6.EditorView){ return Promise.resolve(); }
    var src = absoluteStatic('/static/js/codemirror.local.js');
    safeLog('[EditorManager] (legacy) Attempting to load local CodeMirror bundle from:', src);
    return withTimeout(new Promise(function(resolve, reject){
      try {
        var s = document.createElement('script');
        s.src = src;
        s.async = false; // preserve order
        s.onload = function(){
          try {
            if (window.CodeMirror6 && window.CodeMirror6.EditorState && window.CodeMirror6.EditorView){
              safeLog('[EditorManager] (legacy) Local CodeMirror bundle loaded successfully');
              resolve();
            } else {
              reject(new Error('codemirror_bundle_missing_api'));
            }
          } catch(e){ reject(e); }
        };
        s.onerror = function(){ reject(new Error('codemirror_bundle_load_error')); };
        (document.head || document.body || document.documentElement).appendChild(s);
      } catch (e){ reject(e); }
    }), timeoutMs || 12000, 'codemirror_local_legacy_load');
  }

  function showLoading(container){
    try {
      if (container.querySelector('.editor-loading')) return;
      var el = document.createElement('div');
      el.className = 'editor-loading';
      el.innerHTML = '<div class="spinner"><i class="fas fa-spinner fa-spin"></i> טוען עורך...</div>';
      container.className += (container.className ? ' ' : '') + 'editor-transitioning';
      container.appendChild(el);
    } catch(_){ }
  }
  function hideLoading(container){
    try {
      var el = container.querySelector('.editor-loading');
      if (el) el.parentNode.removeChild(el);
      container.className = String(container.className || '').replace(/\beditor-transitioning\b/, '').trim();
    } catch(_){ }
  }

  function createSwitcher(container, mgr){
    try {
      if (container.querySelector('.editor-switcher')) return;
      var switcher = document.createElement('div');
      switcher.className = 'editor-switcher';
      switcher.innerHTML = (
        '<button type="button" class="btn-switch-editor" title="החלף עורך">' +
        '  <i class="fas fa-exchange-alt"></i>' +
        '  <span>עורך פשוט</span>' + // אם עורך מתקדם פעיל, הכפתור מציע לעבור לפשוט
        '</button>' +
        '<div class="editor-info"><span><i class="fas fa-keyboard"></i> קיצורי מקלדת זמינים</span></div>'
      );
      var codeLabel = container.querySelector('label') || container;
      codeLabel.parentNode.insertBefore(switcher, codeLabel.nextSibling);
      var btn = switcher.querySelector('.btn-switch-editor');
      if (btn){
        btn.addEventListener('click', function(){
          try {
            if (mgr && typeof mgr.initSimpleEditor === 'function'){
              mgr.initSimpleEditor(container, { value: mgr._textarea ? mgr._textarea.value : '' });
              var span = switcher.querySelector('span');
              if (span) span.textContent = 'עורך מתקדם';
            }
          } catch(_){ }
        });
      }
    } catch(_){ }
  }

  var EditorManagerLegacy = {
    _textarea: null,
    _cm: null,

    initSimpleEditor: function(container, opts){
      try {
        if (this._cm && this._cm.destroy) {
          try { this._textarea.value = this._cm.state && this._cm.state.doc ? this._cm.state.doc.toString() : this._textarea.value; } catch(_){ }
          try { this._cm.destroy(); } catch(_){ }
          this._cm = null;
        }
        if (this._textarea){ this._textarea.style.display = 'block'; }
        var existing = container.querySelector('.codemirror-container');
        if (existing) { try { existing.parentNode.removeChild(existing); } catch(_){ } }
      } catch(_){ }
    },

    initEditor: function(container, options){
      options = options || {};
      var language = options.language || 'text';
      var value = options.value || '';
      var theme = options.theme || 'dark';

      try { safeLog('[EditorManager] (legacy) initEditor called with:', { language: language, theme: theme, valueLength: (typeof value === 'string' ? value.length : 0) }); } catch(_){ }

      // Find textarea
      this._textarea = null;
      try {
        this._textarea = container.querySelector('textarea[name="code"]') || container.querySelector('textarea');
      } catch(_){ this._textarea = null; }
      if (!this._textarea){ safeWarn('[EditorManager] (legacy) Textarea not found in container'); return; }
      try { safeLog('[EditorManager] (legacy) Textarea found:', this._textarea); } catch(_){ }

      var self = this;
      showLoading(container);
      try { this._textarea.style.display = 'none'; } catch(_){ }

      return withTimeout(loadLocalBundleIfNeeded(12000).then(function(){
        var CM = window.CodeMirror6 || {};
        if (!CM.EditorState || !CM.EditorView){ throw new Error('codemirror_modules_missing'); }

        // build container
        var wrap = document.createElement('div');
        wrap.className = 'codemirror-container';
        try { self._textarea.parentNode.insertBefore(wrap, self._textarea.nextSibling); } catch(_){ container.appendChild(wrap); }

        // Prepare language and theme (best-effort)
        var langSupport = [];
        try { if (typeof CM.getLanguageSupport === 'function') { langSupport = CM.getLanguageSupport(language) || []; } } catch(_){ }
        var themeExt = [];
        try { if (typeof CM.getTheme === 'function') { themeExt = CM.getTheme(theme) || []; } } catch(_){ }

        // Debounced sync
        var syncTimer = null;
        function syncValue(val){
          try { self._textarea.value = val; } catch(_){ }
          try { if (typeof Event === 'function') { self._textarea.dispatchEvent(new Event('input', { bubbles: true })); } } catch(_){ }
        }

        var state = CM.EditorState.create({
          doc: (self._textarea.value || value || ''),
          extensions: [].concat(
            CM.basicSetup || [],
            CM.languageCompartment ? [CM.languageCompartment.of(langSupport || [])] : [],
            CM.themeCompartment ? [CM.themeCompartment.of(themeExt || [])] : [],
            CM.EditorView ? [CM.EditorView.lineWrapping] : []
          )
        });

        self._cm = new CM.EditorView({ state: state, parent: wrap });
        try { safeLog('[EditorManager] (legacy) CodeMirror editor instance created'); } catch(_){ }

        // Listen for changes
        try {
          self._cm.dispatch({ effects: [] }); // no-op, ensure active
          var updateListener = CM.EditorView && CM.EditorView.updateListener && CM.EditorView.updateListener.of
            ? CM.EditorView.updateListener.of(function(update){
                try {
                  if (update && update.docChanged){
                    if (syncTimer) { clearTimeout(syncTimer); }
                    syncTimer = setTimeout(function(){
                      try { syncValue(update.state.doc.toString()); } catch(_){ }
                    }, 100);
                  }
                } catch(_){ }
              })
            : null;
          if (updateListener){ self._cm.dispatch({ effects: [] }); /* already attached through extensions above if any */ }
        } catch(_){ }

        createSwitcher(container, self);
      }).catch(function(e){
        safeWarn('CodeMirror (legacy) init failed', e);
        self.initSimpleEditor(container, { value: value });
        try {
          var errBanner = document.createElement('div');
          errBanner.className = 'editor-error-banner alert alert-error';
          errBanner.style.marginTop = '.5rem';
          errBanner.textContent = 'טעינת העורך המתקדם נכשלה. הוחזר לעורך הפשוט.';
          container.appendChild(errBanner);
        } catch(_){ }
        throw e;
      }).finally(function(){
        hideLoading(container);
      });
    },

    updateLanguage: function(lang){
      try {
        var CM = window.CodeMirror6 || {};
        if (!this._cm || !CM.languageCompartment) return;
        var support = [];
        try { if (typeof CM.getLanguageSupport === 'function') { support = CM.getLanguageSupport(lang) || []; } } catch(_){ support = []; }
        try { this._cm.dispatch({ effects: CM.languageCompartment.reconfigure(support || []) }); } catch(_){ }
      } catch(_){ }
    },

    updateTheme: function(themeName){
      try {
        var CM = window.CodeMirror6 || {};
        if (!this._cm || !CM.themeCompartment) return;
        var theme = [];
        try { if (typeof CM.getTheme === 'function') { theme = CM.getTheme(themeName) || []; } } catch(_){ theme = []; }
        try { this._cm.dispatch({ effects: CM.themeCompartment.reconfigure(theme || []) }); } catch(_){ }
      } catch(_){ }
    }
  };

  try { if (!window.editorManager) { window.editorManager = EditorManagerLegacy; safeLog('[EditorManager] (legacy) Initialized'); } } catch(_){ }
})();

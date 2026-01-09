/* Fun Mode – אנימציות אינטראקטיביות (Matrix / Confetti / Hacker Typer / Gravity)
 *
 * עקרונות:
 * - לא משאיר מאזינים/טיימרים רצים ברקע אחרי stop
 * - סגירה ב-ESC, ולרוב גם בלחיצה (ב-Overlay)
 * - בלי שגיאות קונסול: כל פעולה עטופה ב-try/catch
 */
(function () {
  'use strict';

  function createCleanupBag() {
    const fns = [];
    return {
      add(fn) {
        if (typeof fn === 'function') fns.push(fn);
      },
      run() {
        while (fns.length) {
          const fn = fns.pop();
          try {
            fn();
          } catch (_) {}
        }
      },
    };
  }

  function closeFunMenuIfExists() {
    try {
      if (typeof window.closeFunModeMenu === 'function') window.closeFunModeMenu();
    } catch (_) {}
  }

  let activeCleanup = null;

  function stopAll() {
    try {
      if (activeCleanup) activeCleanup.run();
    } catch (_) {}
    activeCleanup = null;
  }

  function bindStopOnKey(bag, mode) {
    const onKeyDown = function (e) {
      try {
        if (!e) return;
        if (mode === 'escape') {
          if (e.key === 'Escape') stopAll();
          return;
        }

        // mode === 'any': כל מקש “אמיתי” מבטל (מתעלמים ממקשי modifier)
        const key = String(e.key || '');
        if (key === 'Shift' || key === 'Control' || key === 'Alt' || key === 'Meta') return;
        stopAll();
      } catch (_) {}
    };
    try {
      window.addEventListener('keydown', onKeyDown, true);
      bag.add(() => window.removeEventListener('keydown', onKeyDown, true));
    } catch (_) {}
  }

  function startMatrix() {
    stopAll();
    closeFunMenuIfExists();

    const bag = createCleanupBag();
    activeCleanup = bag;
    bindStopOnKey(bag, 'escape');

    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-hidden', 'true');
    Object.assign(canvas.style, {
      position: 'fixed',
      top: '0',
      left: '0',
      width: '100vw',
      height: '100vh',
      zIndex: '99999',
      background: 'black',
      cursor: 'pointer',
    });

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      stopAll();
      return;
    }

    const letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789@#$%^&*()*&^%';
    const fontSize = 16;
    let drops = [];
    let w = 0;
    let h = 0;
    let rafId = 0;
    let last = 0;

    function resize() {
      try {
        w = window.innerWidth || document.documentElement.clientWidth || 0;
        h = window.innerHeight || document.documentElement.clientHeight || 0;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.max(1, Math.floor(w * dpr));
        canvas.height = Math.max(1, Math.floor(h * dpr));
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const columns = Math.max(1, Math.floor(w / fontSize));
        drops = Array(columns).fill(1);
      } catch (_) {}
    }

    function draw(now) {
      try {
        // throttle to ~30fps
        if (!last || now - last >= 33) {
          last = now;
          ctx.fillStyle = 'rgba(0, 0, 0, 0.05)';
          ctx.fillRect(0, 0, w, h);

          ctx.fillStyle = '#0F0';
          ctx.font = fontSize + 'px monospace';

          for (let i = 0; i < drops.length; i++) {
            const text = letters.charAt(Math.floor(Math.random() * letters.length));
            ctx.fillText(text, i * fontSize, drops[i] * fontSize);

            if (drops[i] * fontSize > h && Math.random() > 0.975) {
              drops[i] = 0;
            }
            drops[i]++;
          }
        }
      } catch (_) {}

      try {
        rafId = window.requestAnimationFrame(draw);
      } catch (_) {}
    }

    function stop() {
      stopAll();
    }

    try {
      document.body.appendChild(canvas);
      bag.add(() => {
        try {
          canvas.remove();
        } catch (_) {}
      });
    } catch (_) {
      stopAll();
      return;
    }

    try {
      canvas.addEventListener('click', stop);
      bag.add(() => canvas.removeEventListener('click', stop));
    } catch (_) {}

    try {
      window.addEventListener('resize', resize, { passive: true });
      bag.add(() => window.removeEventListener('resize', resize));
    } catch (_) {}

    resize();

    try {
      rafId = window.requestAnimationFrame(draw);
      bag.add(() => {
        try {
          if (rafId) window.cancelAnimationFrame(rafId);
        } catch (_) {}
      });
    } catch (_) {}
  }

  function startConfetti() {
    stopAll();
    closeFunMenuIfExists();

    const bag = createCleanupBag();
    activeCleanup = bag;
    bindStopOnKey(bag, 'escape');

    if (typeof window.confetti !== 'function') {
      try {
        alert('הקונפטי לא נטען (חסימה/רשת). נסה שוב בעוד רגע.');
      } catch (_) {}
      stopAll();
      return;
    }

    const duration = 3 * 1000;
    const end = Date.now() + duration;
    let rafId = 0;
    let cancelled = false;

    function frame() {
      if (cancelled) return;
      try {
        window.confetti({
          particleCount: 5,
          angle: 60,
          spread: 55,
          origin: { x: 0 },
        });
        window.confetti({
          particleCount: 5,
          angle: 120,
          spread: 55,
          origin: { x: 1 },
        });
      } catch (_) {}

      if (Date.now() < end) {
        try {
          rafId = window.requestAnimationFrame(frame);
        } catch (_) {}
      } else {
        stopAll();
      }
    }

    bag.add(() => {
      cancelled = true;
      try {
        if (rafId) window.cancelAnimationFrame(rafId);
      } catch (_) {}
    });

    try {
      rafId = window.requestAnimationFrame(frame);
    } catch (_) {}
  }

  function startHackerTyper() {
    stopAll();
    closeFunMenuIfExists();

    const bag = createCleanupBag();
    activeCleanup = bag;
    bindStopOnKey(bag, 'escape');

    const overlay = document.createElement('div');
    Object.assign(overlay.style, {
      position: 'fixed',
      top: '0',
      left: '0',
      width: '100vw',
      height: '100vh',
      background: 'black',
      color: '#0f0',
      fontFamily: 'monospace',
      padding: '20px',
      fontSize: '18px',
      zIndex: '99999',
      overflow: 'hidden',
      whiteSpace: 'pre-wrap',
      boxSizing: 'border-box',
      cursor: 'pointer',
    });

    const header = document.createElement('div');
    header.style.color = '#fff';
    header.style.marginBottom = '12px';
    header.textContent = 'Accessing Mainframe... (Press any key to hack)  •  ESC לסגירה  •  קליק/טאפ לסגירה';

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'סגור');
    closeBtn.textContent = '✕';
    Object.assign(closeBtn.style, {
      position: 'fixed',
      top: '10px',
      right: '10px',
      zIndex: '100000',
      width: '44px',
      height: '44px',
      borderRadius: '12px',
      border: '1px solid rgba(255,255,255,0.25)',
      background: 'rgba(0,0,0,0.6)',
      color: '#fff',
      fontSize: '20px',
      cursor: 'pointer',
    });

    const codeEl = document.createElement('pre');
    Object.assign(codeEl.style, {
      margin: '0',
      whiteSpace: 'pre-wrap',
      overflow: 'auto',
      height: 'calc(100vh - 72px)',
      paddingBottom: '24px',
    });

    overlay.appendChild(header);
    overlay.appendChild(codeEl);
    overlay.appendChild(closeBtn);

    const codeSnippet =
      'struct group_info init_groups = { .usage = ATOMIC_INIT(2) };\n' +
      'struct group_info *groups_alloc(int gidsetsize){\n' +
      '    struct group_info *group_info;\n' +
      '    int nblocks;\n' +
      '    int i;\n' +
      '    nblocks = (gidsetsize + NGROUPS_PER_BLOCK - 1) / NGROUPS_PER_BLOCK;\n' +
      '    nblocks = nblocks ? : 1;\n' +
      '    group_info = kmalloc(sizeof(*group_info) + nblocks*sizeof(gid_t *), GFP_USER);\n' +
      '    if (!group_info)\n' +
      '        return NULL;\n' +
      '    group_info->ngroups = gidsetsize;\n' +
      '    group_info->nblocks = nblocks;\n' +
      '    atomic_set(&group_info->usage, 1);\n' +
      '}\n';

    let idx = 0;
    const charsPerKey = 3;

    function onKeyDown(e) {
      try {
        if (!e) return;
        if (e.key === 'Escape') {
          stopAll();
          return;
        }

        // מתעלמים ממקשי שליטה כדי לא "למלא" בטעות
        if (e.ctrlKey || e.metaKey || e.altKey) return;
        if (e.key && e.key.length > 1 && e.key !== 'Enter' && e.key !== 'Backspace' && e.key !== 'Tab') return;

        const next = codeSnippet.slice(idx, idx + charsPerKey);
        idx = (idx + charsPerKey) % codeSnippet.length;
        codeEl.textContent += next;
        codeEl.scrollTop = codeEl.scrollHeight;
      } catch (_) {}
    }

    function onClick() {
      stopAll();
    }

    try {
      document.body.appendChild(overlay);
      bag.add(() => {
        try {
          overlay.remove();
        } catch (_) {}
      });
    } catch (_) {
      stopAll();
      return;
    }

    try {
      document.addEventListener('keydown', onKeyDown, true);
      bag.add(() => document.removeEventListener('keydown', onKeyDown, true));
    } catch (_) {}

    try {
      overlay.addEventListener('click', onClick);
      bag.add(() => overlay.removeEventListener('click', onClick));
    } catch (_) {}

    // מובייל/Telegram MiniApp: לפעמים click לא מספיק עקבי, אז מוסיפים touchstart
    try {
      overlay.addEventListener('touchstart', onClick, { capture: true, passive: true });
      bag.add(() => overlay.removeEventListener('touchstart', onClick, { capture: true }));
    } catch (_) {}

    try {
      closeBtn.addEventListener('click', onClick);
      bag.add(() => closeBtn.removeEventListener('click', onClick));
    } catch (_) {}
  }

  function startGravity() {
    stopAll();
    closeFunMenuIfExists();

    let ok = true;
    try {
      ok = window.confirm('אזהרה: האפקט מזיז את כל הדף. אפשר לבטל בכל מקש, בטאפ/קליק, או בכפתור "⟲ בטל". להמשיך?');
    } catch (_) {}
    if (!ok) return;

    const bag = createCleanupBag();
    activeCleanup = bag;
    // גם ESC וגם "כל מקש" למי שיש מקלדת (חשוב למקלדות בלי ESC נוח)
    bindStopOnKey(bag, 'any');

    const els = [];
    try {
      const children = Array.from(document.body ? document.body.children : []);
      for (const el of children) {
        try {
          if (!el || !el.tagName) continue;
          const tag = String(el.tagName || '').toUpperCase();
          if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'LINK' || tag === 'META' || tag === 'NOSCRIPT') continue;
          els.push(el);
        } catch (_) {}
      }
    } catch (_) {}

    const prev = new Map();
    try {
      for (const el of els) {
        try {
          prev.set(el, {
            transition: el.style.transition || '',
            transform: el.style.transform || '',
            willChange: el.style.willChange || '',
          });

          el.style.willChange = 'transform';
          el.style.transition = 'transform 1s cubic-bezier(0.5, 0, 0.5, 1)';

          const rect = el.getBoundingClientRect();
          const randomRotate = (Math.random() - 0.5) * 60;
          const dropDistance = Math.max(0, (window.innerHeight || 0) - rect.top);
          el.style.transform = 'translateY(' + dropDistance + 'px) rotate(' + randomRotate + 'deg)';
        } catch (_) {}
      }
    } catch (_) {}

    // כפתור ביטול קטן למובייל + Tap/Click על המסך לביטול
    const resetBtn = document.createElement('button');
    resetBtn.type = 'button';
    resetBtn.textContent = '⟲ בטל';
    resetBtn.setAttribute('aria-label', 'בטל אפקט');
    Object.assign(resetBtn.style, {
      position: 'fixed',
      top: '12px',
      left: '12px',
      zIndex: '100000',
      padding: '10px 12px',
      borderRadius: '12px',
      border: '1px solid rgba(255,255,255,0.25)',
      background: 'rgba(0,0,0,0.55)',
      color: '#fff',
      fontSize: '14px',
      fontWeight: '700',
      cursor: 'pointer',
    });

    function cancelGravity(e) {
      try {
        if (e && e.preventDefault) e.preventDefault();
        if (e && e.stopPropagation) e.stopPropagation();
      } catch (_) {}
      stopAll();
    }

    try {
      document.body.appendChild(resetBtn);
      bag.add(() => {
        try {
          resetBtn.remove();
        } catch (_) {}
      });
    } catch (_) {}

    try {
      resetBtn.addEventListener('click', cancelGravity, true);
      bag.add(() => resetBtn.removeEventListener('click', cancelGravity, true));
    } catch (_) {}

    try {
      document.addEventListener('click', cancelGravity, true);
      bag.add(() => document.removeEventListener('click', cancelGravity, true));
    } catch (_) {}

    try {
      document.addEventListener('touchstart', cancelGravity, { capture: true, passive: false });
      bag.add(() => document.removeEventListener('touchstart', cancelGravity, { capture: true }));
    } catch (_) {}

    bag.add(() => {
      try {
        for (const [el, st] of prev.entries()) {
          try {
            el.style.transition = st.transition;
            el.style.transform = st.transform;
            el.style.willChange = st.willChange;
          } catch (_) {}
        }
      } catch (_) {}
    });
  }

  window.FunMode = window.FunMode || {};
  window.FunMode.stopAll = stopAll;
  window.FunMode.startMatrix = startMatrix;
  window.FunMode.startConfetti = startConfetti;
  window.FunMode.startHackerTyper = startHackerTyper;
  window.FunMode.startGravity = startGravity;
})();


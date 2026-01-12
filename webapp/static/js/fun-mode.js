/* Fun Mode – אנימציות אינטראקטיביות (Synthwave / Confetti / Fireflies / Gravity)
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

        // mode === 'any': כל מקש "אמיתי" מבטל (מתעלמים ממקשי modifier)
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

  function startSynthwave() {
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
      cursor: 'pointer',
    });

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      stopAll();
      return;
    }

    let w = 0;
    let h = 0;
    let rafId = 0;
    let gridOffset = 0;
    let stars = [];

    function resize() {
      try {
        w = window.innerWidth || document.documentElement.clientWidth || 0;
        h = window.innerHeight || document.documentElement.clientHeight || 0;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.max(1, Math.floor(w * dpr));
        canvas.height = Math.max(1, Math.floor(h * dpr));
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        // Generate stars
        stars = [];
        for (let i = 0; i < 100; i++) {
          stars.push({
            x: Math.random() * w,
            y: Math.random() * h * 0.5,
            size: Math.random() * 2 + 0.5,
            twinkle: Math.random() * Math.PI * 2
          });
        }
      } catch (_) {}
    }

    function draw() {
      try {
        // Background gradient (dark purple to dark blue)
        const bgGrad = ctx.createLinearGradient(0, 0, 0, h);
        bgGrad.addColorStop(0, '#0f0c29');
        bgGrad.addColorStop(0.5, '#302b63');
        bgGrad.addColorStop(1, '#24243e');
        ctx.fillStyle = bgGrad;
        ctx.fillRect(0, 0, w, h);

        // Stars
        for (const star of stars) {
          star.twinkle += 0.05;
          const opacity = 0.5 + Math.sin(star.twinkle) * 0.5;
          ctx.fillStyle = `rgba(255, 255, 255, ${opacity})`;
          ctx.beginPath();
          ctx.arc(star.x, star.y, star.size, 0, Math.PI * 2);
          ctx.fill();
        }

        // Sun
        const sunY = h * 0.45;
        const sunRadius = Math.min(w, h) * 0.15;
        const sunGrad = ctx.createLinearGradient(w / 2, sunY - sunRadius, w / 2, sunY + sunRadius);
        sunGrad.addColorStop(0, '#ff6b6b');
        sunGrad.addColorStop(0.5, '#feca57');
        sunGrad.addColorStop(1, '#ff9ff3');
        ctx.fillStyle = sunGrad;
        ctx.beginPath();
        ctx.arc(w / 2, sunY, sunRadius, 0, Math.PI * 2);
        ctx.fill();

        // Sun stripes
        ctx.fillStyle = '#24243e';
        const stripeCount = 8;
        for (let i = 0; i < stripeCount; i++) {
          const stripeY = sunY - sunRadius + (i * 2 + 1) * (sunRadius * 2) / (stripeCount * 2);
          const stripeHeight = sunRadius * 0.08;
          // Calculate stripe width based on circle geometry
          const dy = Math.abs(stripeY - sunY);
          if (dy < sunRadius) {
            const stripeHalfWidth = Math.sqrt(sunRadius * sunRadius - dy * dy);
            ctx.fillRect(w / 2 - stripeHalfWidth, stripeY, stripeHalfWidth * 2, stripeHeight);
          }
        }

        // Horizon line
        const horizonY = h * 0.55;
        ctx.fillStyle = '#24243e';
        ctx.fillRect(0, horizonY, w, h - horizonY);

        // Grid
        gridOffset = (gridOffset + 0.5) % 40;

        // Horizontal lines (perspective)
        ctx.strokeStyle = '#ff00ff';
        ctx.lineWidth = 1.5;
        const lineCount = 20;
        for (let i = 0; i < lineCount; i++) {
          const t = (i + gridOffset / 40) / lineCount;
          const y = horizonY + Math.pow(t, 1.5) * (h - horizonY);
          ctx.globalAlpha = Math.min(1, t * 2);
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(w, y);
          ctx.stroke();
        }

        // Vertical lines (perspective from center)
        ctx.strokeStyle = '#00ffff';
        ctx.globalAlpha = 0.8;
        const vLineCount = 20;
        for (let i = -vLineCount / 2; i <= vLineCount / 2; i++) {
          const topX = w / 2 + i * 5;
          const bottomX = w / 2 + i * (w / vLineCount) * 2;
          ctx.beginPath();
          ctx.moveTo(topX, horizonY);
          ctx.lineTo(bottomX, h);
          ctx.stroke();
        }

        ctx.globalAlpha = 1;

        // Hint text
        ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
        ctx.font = '14px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('לחץ לסגירה | ESC', w / 2, h - 20);
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

  function startFireflies() {
    stopAll();
    closeFunMenuIfExists();

    const bag = createCleanupBag();
    activeCleanup = bag;
    bindStopOnKey(bag, 'escape');

    // נגישות: למי שמבקש להפחית אנימציות - לא מריצים אפקטים כאלה
    try {
      if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
      }
    } catch (_) {}

    const overlay = document.createElement('div');
    overlay.setAttribute('aria-hidden', 'true');
    Object.assign(overlay.style, {
      position: 'fixed',
      top: '0',
      left: '0',
      width: '100vw',
      height: '100vh',
      zIndex: '99999',
      background: 'radial-gradient(ellipse at bottom, #1B2735 0%, #090A0F 100%)',
      cursor: 'pointer',
      overflow: 'hidden',
    });

    // Add CSS keyframes
    const style = document.createElement('style');
    style.textContent = `
      @keyframes firefly-drift {
        0% { transform: translate(0, 0); }
        100% { transform: translate(var(--moveX), var(--moveY)); }
      }
      @keyframes firefly-flash {
        0%, 100% { opacity: 0; }
        50% { opacity: var(--max-opacity); box-shadow: 0 0 25px #ffd700; }
      }
      .firefly-particle {
        position: absolute;
        border-radius: 50%;
        background-color: #ffd700;
        box-shadow: 0 0 10px #ffd700, 0 0 20px #ff8c00;
        opacity: 0;
        pointer-events: none;
      }
    `;

    const container = document.createElement('div');
    Object.assign(container.style, {
      position: 'absolute',
      top: '0',
      left: '0',
      width: '100%',
      height: '100%',
      pointerEvents: 'none',
    });

    // Hint text
    const hint = document.createElement('div');
    Object.assign(hint.style, {
      position: 'absolute',
      bottom: '20px',
      left: '0',
      right: '0',
      textAlign: 'center',
      color: 'rgba(255, 255, 255, 0.5)',
      fontSize: '14px',
      fontFamily: 'sans-serif',
      pointerEvents: 'none',
    });
    hint.textContent = 'לחץ לסגירה | ESC';

    overlay.appendChild(style);
    overlay.appendChild(container);
    overlay.appendChild(hint);

    const fireflyCount = 50;

    function createFirefly() {
      try {
        const fly = document.createElement('div');
        fly.className = 'firefly-particle';

        // Size (2-5 pixels)
        const size = Math.random() * 3 + 2;
        fly.style.width = size + 'px';
        fly.style.height = size + 'px';

        // Starting position
        fly.style.left = Math.random() * 100 + '%';
        fly.style.top = Math.random() * 100 + '%';

        // Movement direction
        const moveX = (Math.random() - 0.5) * 300 + 'px';
        const moveY = (Math.random() - 0.5) * 300 + 'px';
        fly.style.setProperty('--moveX', moveX);
        fly.style.setProperty('--moveY', moveY);

        // Max opacity
        const maxOpacity = Math.random() * 0.6 + 0.4;
        fly.style.setProperty('--max-opacity', maxOpacity);

        // Animation timing
        const duration = Math.random() * 10 + 10;
        const delay = Math.random() * 5;
        const flashDuration = Math.random() * 3 + 2;

        fly.style.animation = 
          'firefly-drift ' + duration + 's ease-in-out infinite alternate, ' +
          'firefly-flash ' + flashDuration + 's ease-in-out infinite alternate ' + delay + 's';

        container.appendChild(fly);
      } catch (_) {}
    }

    // Create all fireflies
    for (let i = 0; i < fireflyCount; i++) {
      createFirefly();
    }

    function stop() {
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
      overlay.addEventListener('click', stop);
      bag.add(() => overlay.removeEventListener('click', stop));
    } catch (_) {}

    try {
      overlay.addEventListener('touchstart', stop, { capture: true, passive: true });
      bag.add(() => overlay.removeEventListener('touchstart', stop, { capture: true }));
    } catch (_) {}
  }

  function startGravity() {
    stopAll();
    closeFunMenuIfExists();

    let ok = true;
    try {
      ok = window.confirm('אזהרה: האפקט מזיז את כל הדף. אפשר לבטל בכל מקש או בטאפ/קליק על המסך. להמשיך?');
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

    function cancelGravity(e) {
      try {
        if (e && e.preventDefault) e.preventDefault();
        if (e && e.stopPropagation) e.stopPropagation();
      } catch (_) {}
      stopAll();
    }

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
  window.FunMode.startSynthwave = startSynthwave;
  window.FunMode.startConfetti = startConfetti;
  window.FunMode.startFireflies = startFireflies;
  window.FunMode.startGravity = startGravity;
})();

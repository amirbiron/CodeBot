/* Smooth scrolling manager (basic implementation) */
(function () {
  'use strict';
  function clamp(val, min, max) {
    return Math.min(Math.max(val, min), max);
  }
  function isEditableTarget(el) {
    if (!el || el === document.body) return false;
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
    if (el.isContentEditable) return true;
    return false;
  }
  function getOverflowStyle(el) {
    try {
      const cs = window.getComputedStyle(el);
      return (cs && (cs.overflowY || cs.overflow)) || '';
    } catch (_) {
      return '';
    }
  }
  function isScrollable(el) {
    if (!el) return false;
    const overflowY = getOverflowStyle(el);
    const canScrollY = overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay';
    return canScrollY && (el.scrollHeight - el.clientHeight > 2);
  }
  function findScrollableContainer(startEl) {
    let el = startEl;
    while (el && el !== document.body && el !== document.documentElement) {
      if (isScrollable(el)) return el;
      el = el.parentElement;
    }
    return null;
  }
  function prefersReducedMotion() {
    try {
      return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (_) {
      return false;
    }
  }

  class SmoothScrollManager {
    constructor(options = {}) {
      const reduce = prefersReducedMotion();
      this.config = {
        duration: reduce ? 0 : 400,
        easing: 'ease-in-out',
        offset: 0,
        enabled: !reduce,
        wheelSensitivity: 1,
        keyboardSensitivity: 1.5,
        ...options,
      };
      this.isScrolling = false;
      this.rafId = null;
      this.startTime = 0;
      this.startPos = 0;
      this.targetPos = 0;
      this.bound = null;
      this.listenersAttached = false;
      // Android-specific state
      this.isAndroid = /Android/i.test((navigator.userAgent || ''));
      this.isSamsungBrowser = /SamsungBrowser/i.test((navigator.userAgent || ''));
      this.isAndroidWebView = (() => {
        try {
          const ua = (navigator.userAgent || '').toLowerCase();
          const ios = /iphone|ipod|ipad/.test(ua);
          const android = /android/.test(ua);
          if (ios) return false;
          if (!android) return false;
          if (ua.includes('wv')) return true;
          if (!ua.includes('chrome') && !ua.includes('firefox')) return true;
          return false;
        } catch (_) { return false; }
      })();
      this.touchActive = false;
      this._lastScrollY = 0;
      this._lastScrollTime = 0;
      this.touchVelocity = 0;
      this.momentumId = null;
      this.loadPreferences();
      this.init();
      try {
        document.documentElement.classList.add('js-smooth-scroll');
      } catch (_) {}
      if (this.isAndroid) {
        this.initAndroidOptimizations();
      }
    }

    init() {
      if (!this.config.enabled) return;
      if (this.listenersAttached) this.removeListeners();
      if (!this.bound) {
        this.bound = {
          wheel: this.throttle(this.onWheel.bind(this), 16),
          keydown: this.onKeyDown.bind(this),
          anchorClick: this.onAnchorClick.bind(this),
        };
      }
      // Note: passive must be false to be able to preventDefault() on wheel
      document.addEventListener('wheel', this.bound.wheel, { passive: false });
      document.addEventListener('keydown', this.bound.keydown);
      document.addEventListener('click', this.bound.anchorClick);
      this.listenersAttached = true;
    }

    initAndroidOptimizations() {
      try {
        document.body.classList.add('android-optimized', 'android-no-bounce');
      } catch (_) {}
      // Samsung Internet: avoid double smoothing quirks
      try {
        if (this.isSamsungBrowser) {
          document.documentElement.style.scrollBehavior = 'auto';
        }
      } catch (_) {}
      // Passive touch listeners to avoid main-thread blocking
      const touchOpts = { passive: true };
      const onTouchStart = (e) => {
        this.touchActive = true;
        this.touchVelocity = 0;
        this._lastScrollY = window.pageYOffset || window.scrollY || 0;
        this._lastScrollTime = performance.now();
        if (this.momentumId) {
          try { cancelAnimationFrame(this.momentumId); } catch (_) {}
          this.momentumId = null;
        }
      };
      const onTouchMove = () => {
        // Sample actual scroll velocity to align momentum direction
        const nowY = window.pageYOffset || window.scrollY || 0;
        const nowT = performance.now();
        const dt = nowT - this._lastScrollTime;
        if (dt > 0) {
          const dy = nowY - this._lastScrollY; // +dy => scrolled down
          this.touchVelocity = dy / dt; // px per ms
          this._lastScrollY = nowY;
          this._lastScrollTime = nowT;
        }
      };
      const onTouchEnd = () => {
        this.touchActive = false;
        // If the page keeps moving naturally after touchend, don't add momentum
        const startY = window.pageYOffset || window.scrollY || 0;
        setTimeout(() => {
          const afterY = window.pageYOffset || window.scrollY || 0;
          const moved = Math.abs(afterY - startY);
          const speed = Math.abs(this.touchVelocity);
          if (moved < 2 && speed > 0.4) {
            this.startMomentumScroll(this.touchVelocity);
          }
        }, 60);
      };
      window.addEventListener('touchstart', onTouchStart, touchOpts);
      window.addEventListener('touchmove', onTouchMove, touchOpts);
      window.addEventListener('touchend', onTouchEnd, touchOpts);
      window.addEventListener('touchcancel', onTouchEnd, touchOpts);
      // Lightweight performance monitor (Android only)
      this.startAndroidPerformanceMonitor();
    }

    startMomentumScroll(initialVelocity) {
      let v = initialVelocity * 24; // convert px/ms to px/frame (@~60fps)
      const friction = 0.94;
      const threshold = 0.35;
      const step = () => {
        v *= friction;
        if (Math.abs(v) > threshold) {
          // v>0 means we were scrolling down (content goes up => scrollY increases)
          window.scrollBy(0, v);
          this.momentumId = requestAnimationFrame(step);
        } else {
          this.momentumId = null;
        }
      };
      if (!this.momentumId) {
        this.momentumId = requestAnimationFrame(step);
      }
    }

    startAndroidPerformanceMonitor() {
      try {
        let last = performance.now();
        let frames = 0;
        const fpsWindow = [];
        const MAX_SAMPLES = 10;
        const loop = (t) => {
          frames++;
          if (t - last >= 1000) {
            const fps = Math.round((frames * 1000) / (t - last));
            fpsWindow.push(fps);
            if (fpsWindow.length > MAX_SAMPLES) fpsWindow.shift();
            // if median fps is low, reduce animation duration to minimize jank
            const sorted = [...fpsWindow].sort((a, b) => a - b);
            const median = sorted[Math.floor(sorted.length / 2)];
            if (median < 40 && this.config.duration > 250) {
              this.updateConfig({ duration: Math.max(200, this.config.duration - 100), easing: 'ease-out' });
            }
            last = t; frames = 0;
          }
          requestAnimationFrame(loop);
        };
        requestAnimationFrame(loop);
      } catch (_) {}
    }

    enableAndroidFallback() {
      // Minimize custom animation to rely more on platform behavior
      this.updateConfig({ duration: 0 });
    }

    removeListeners() {
      if (!this.listenersAttached) return;
      try {
        if (this.bound?.wheel) document.removeEventListener('wheel', this.bound.wheel);
        if (this.bound?.keydown) document.removeEventListener('keydown', this.bound.keydown);
        if (this.bound?.anchorClick) document.removeEventListener('click', this.bound.anchorClick);
      } catch (_) {}
      this.listenersAttached = false;
    }

    onWheel(event) {
      if (!this.config.enabled) return;
      if (event.defaultPrevented) return;
      // Avoid intercepting pinch-to-zoom and similar gestures
      if (event.ctrlKey) return;
      const target = event.target;
      // Skip editable/inputs
      if (isEditableTarget(target)) return;
      // Allow native scroll inside known scrollable widgets (e.g., TOC)
      try {
        if (target && (target.closest && target.closest('#mdTocNav'))) return;
      } catch (_) {}
      const container = findScrollableContainer(target);
      const delta = this.normalizeWheelDelta(event);
      if (delta === 0) return;
      const distance = delta * this.config.wheelSensitivity;
      if (container) {
        // Animate the scrollable element itself
        event.preventDefault();
        const to = clamp(container.scrollTop + distance, 0, container.scrollHeight - container.clientHeight);
        this.animateElementScroll(container, container.scrollTop, to);
      } else {
        // Animate the window
        event.preventDefault();
        this.smoothScrollBy(distance);
      }
    }

    onKeyDown(event) {
      if (!this.config.enabled) return;
      // Ignore when typing in inputs or editable content
      if (isEditableTarget(event.target)) return;
      const key = event.key;
      const page = window.innerHeight * 0.9;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      let distance;
      if (key === 'PageDown' || (key === ' ' && !event.shiftKey)) distance = page;
      else if (key === 'PageUp' || (key === ' ' && event.shiftKey)) distance = -page;
      else if (key === 'Home') distance = -document.documentElement.scrollHeight;
      else if (key === 'End') distance = document.documentElement.scrollHeight;
      else if (key === 'ArrowDown') distance = 100;
      else if (key === 'ArrowUp') distance = -100;
      else return;
      event.preventDefault();
      if (key === 'Home' || key === 'End') {
        const from = window.pageYOffset || window.scrollY || 0;
        const to = clamp(key === 'Home' ? 0 : max, 0, max);
        this.animateScroll(from, to);
      } else {
        this.smoothScrollBy(distance * this.config.keyboardSensitivity);
      }
    }

    onAnchorClick(e) {
      if (!this.config.enabled) return;
      try {
        const anchor = e.target && e.target.closest ? e.target.closest('a[href^="#"]') : null;
        if (!anchor) return;
        const href = (anchor.getAttribute('href') || '').trim();
        if (!href || href === '#') return;
        const id = decodeURIComponent(href.slice(1));
        const target = document.getElementById(id);
        if (!target) return;
        e.preventDefault();
        this.smoothScrollTo(target);
      } catch (_) {}
    }

    smoothScrollBy(distance) {
      const currentPos = window.pageYOffset || window.scrollY || 0;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      const targetPos = clamp(currentPos + distance, 0, Math.max(0, max));
      this.animateScroll(currentPos, targetPos);
    }

    smoothScrollTo(target, options = {}) {
      const el = typeof target === 'string' ? document.querySelector(target) : target;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const absoluteTop = (window.pageYOffset || window.scrollY || 0) + rect.top;
      const targetPos = Math.max(0, absoluteTop - (options.offset ?? this.config.offset));
      this.animateScroll(window.pageYOffset || window.scrollY || 0, targetPos, options);
    }

    animateScroll(from, to, options = {}) {
      if (this.rafId) {
        try { cancelAnimationFrame(this.rafId); } catch (_) {}
        this.rafId = null;
      }
      const duration = typeof options.duration === 'number' ? options.duration : this.config.duration;
      const easing = this.getEasingFunction(options.easing || this.config.easing);
      if (duration <= 0) {
        window.scrollTo(0, to);
        if (typeof options.callback === 'function') {
          try { options.callback(); } catch (_) {}
        }
        return;
      }
      this.startPos = from;
      this.targetPos = to;
      this.startTime = performance.now();
      this.isScrolling = true;
      const step = (now) => {
        const elapsed = now - this.startTime;
        const t = clamp(elapsed / duration, 0, 1);
        const eased = easing(t);
        const y = this.startPos + (this.targetPos - this.startPos) * eased;
        window.scrollTo(0, y);
        if (t < 1) {
          this.rafId = requestAnimationFrame(step);
        } else {
          this.isScrolling = false;
          this.rafId = null;
          if (typeof options.callback === 'function') {
            try { options.callback(); } catch (_) {}
          }
        }
      };
      this.rafId = requestAnimationFrame(step);
    }

    animateElementScroll(element, from, to, options = {}) {
      const duration = typeof options.duration === 'number' ? options.duration : this.config.duration;
      const easing = this.getEasingFunction(options.easing || this.config.easing);
      if (duration <= 0) {
        element.scrollTop = to;
        return;
      }
      let start = 0;
      const step = (now) => {
        if (!start) start = now;
        const elapsed = now - start;
        const t = clamp(elapsed / duration, 0, 1);
        const eased = easing(t);
        element.scrollTop = from + (to - from) * eased;
        if (t < 1) {
          requestAnimationFrame(step);
        }
      };
      requestAnimationFrame(step);
    }

    // Easing functions
    getEasingFunction(name) {
      const e = {
        linear: (t) => t,
        'ease-in': (t) => t * t,
        'ease-out': (t) => t * (2 - t),
        'ease-in-out': (t) => (t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t),
      };
      return e[name] || e['ease-in-out'];
    }

    // Normalize delta across browsers
    normalizeWheelDelta(event) {
      let deltaY = Number(event.deltaY || 0);
      const mode = Number(event.deltaMode || 0);
      // 0: pixels, 1: lines, 2: pages
      if (mode === 1) deltaY *= 40;
      else if (mode === 2) deltaY *= window.innerHeight || 800;
      // Cap delta to avoid huge jumps
      if (!isFinite(deltaY)) deltaY = 0;
      const capped = Math.sign(deltaY) * Math.min(Math.abs(deltaY), 200);
      return capped;
    }

    throttle(fn, wait) {
      let last = 0;
      let timer = null;
      return (...args) => {
        const now = Date.now();
        const remain = wait - (now - last);
        if (remain <= 0) {
          if (timer) {
            clearTimeout(timer);
            timer = null;
          }
          last = now;
          fn.apply(this, args);
        } else if (!timer) {
          timer = setTimeout(() => {
            last = Date.now();
            timer = null;
            fn.apply(this, args);
          }, remain);
        }
      };
    }

    async savePreferences() {
      try {
        const prefs = {
          enabled: !!this.config.enabled,
          duration: Number(this.config.duration) || 0,
          easing: String(this.config.easing || 'ease-in-out'),
          wheelSensitivity: Number(this.config.wheelSensitivity) || 1,
          keyboardSensitivity: Number(this.config.keyboardSensitivity) || 1.5,
          offset: Number(this.config.offset) || 0,
        };
        localStorage.setItem('smoothScrollPrefs', JSON.stringify(prefs));
        // Best-effort server post (ignored server-side if unsupported)
        const body = JSON.stringify({ smooth_scroll: prefs });
        const headers = { 'Content-Type': 'application/json' };
        try { fetch('/api/ui_prefs', { method: 'POST', headers, body }).catch(() => {}); } catch (_) {}
      } catch (_) {}
    }

    loadPreferences() {
      try {
        const raw = localStorage.getItem('smoothScrollPrefs');
        if (!raw) return;
        const obj = JSON.parse(raw);
        if (obj && typeof obj === 'object') Object.assign(this.config, obj);
      } catch (_) {}
    }

    enable() {
      if (this.config.enabled) return;
      this.config.enabled = true;
      this.init();
      this.savePreferences();
    }
    disable() {
      if (!this.config.enabled) return;
      this.config.enabled = false;
      if (this.rafId) {
        try { cancelAnimationFrame(this.rafId); } catch (_) {}
        this.rafId = null;
        this.isScrolling = false;
      }
      this.removeListeners();
      this.savePreferences();
    }
    updateConfig(newCfg) {
      try {
        Object.assign(this.config, newCfg || {});
      } catch (_) {}
      this.savePreferences();
    }
  }

  window.smoothScroll = new SmoothScrollManager();
})(); 


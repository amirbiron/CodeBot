/**
 * Animation Utilities for CodeBot WebApp
 * ======================================
 * 
 * Provides:
 * - Skeleton loaders for async content
 * - CRUD operation feedback animations
 * - Toast notifications
 * - Loading states
 * - Ripple effects
 * - Smooth transitions
 * 
 * All animations respect prefers-reduced-motion
 */

(function() {
  'use strict';

  // Check for reduced motion preference
  const prefersReducedMotion = () => {
    try {
      return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (e) {
      return false;
    }
  };

  // ==============================================
  // Skeleton Loader Generator
  // ==============================================
  
  const Skeleton = {
    /**
     * Create a skeleton element
     * @param {string} type - 'text' | 'title' | 'avatar' | 'card' | 'button'
     * @param {object} options - { width, height, lines, className }
     * @returns {HTMLElement}
     */
    create(type = 'text', options = {}) {
      const el = document.createElement('div');
      
      switch (type) {
        case 'text':
          el.className = `skeleton skeleton-text ${options.className || ''}`.trim();
          if (options.width) el.style.width = options.width;
          break;
          
        case 'title':
          el.className = `skeleton skeleton-title ${options.className || ''}`.trim();
          if (options.width) el.style.width = options.width;
          break;
          
        case 'avatar':
          el.className = `skeleton skeleton-avatar ${options.className || ''}`.trim();
          if (options.width) {
            el.style.width = options.width;
            el.style.height = options.width;
          }
          break;
          
        case 'button':
          el.className = `skeleton ${options.className || ''}`.trim();
          el.style.width = options.width || '80px';
          el.style.height = options.height || '36px';
          el.style.borderRadius = '8px';
          break;
          
        case 'card':
          el.className = `skeleton-card ${options.className || ''}`.trim();
          el.innerHTML = `
            <div class="skeleton-header">
              <div class="skeleton skeleton-avatar"></div>
              <div style="flex:1">
                <div class="skeleton skeleton-title" style="width:60%"></div>
                <div class="skeleton skeleton-text" style="width:40%"></div>
              </div>
            </div>
            <div class="skeleton-content">
              <div class="skeleton skeleton-text"></div>
              <div class="skeleton skeleton-text"></div>
              <div class="skeleton skeleton-text" style="width:75%"></div>
            </div>
          `;
          break;
          
        case 'lines':
          el.className = `skeleton-lines ${options.className || ''}`.trim();
          const lineCount = options.lines || 3;
          for (let i = 0; i < lineCount; i++) {
            const line = document.createElement('div');
            line.className = 'skeleton skeleton-text';
            if (i === lineCount - 1) line.style.width = '75%';
            el.appendChild(line);
          }
          break;
          
        default:
          el.className = `skeleton ${options.className || ''}`.trim();
          if (options.width) el.style.width = options.width;
          if (options.height) el.style.height = options.height;
      }
      
      return el;
    },
    
    /**
     * Replace container content with skeletons
     * @param {HTMLElement|string} container 
     * @param {object} options - { type, count }
     */
    show(container, options = {}) {
      const el = typeof container === 'string' 
        ? document.querySelector(container) 
        : container;
      if (!el) return;
      
      el.dataset.originalContent = el.innerHTML;
      el.innerHTML = '';
      
      const type = options.type || 'card';
      const count = options.count || 1;
      
      for (let i = 0; i < count; i++) {
        el.appendChild(this.create(type, options));
      }
    },
    
    /**
     * Remove skeletons and restore original content
     * @param {HTMLElement|string} container 
     */
    hide(container) {
      const el = typeof container === 'string' 
        ? document.querySelector(container) 
        : container;
      if (!el) return;
      
      if ('originalContent' in el.dataset) {
        el.innerHTML = el.dataset.originalContent;
        delete el.dataset.originalContent;
      }
    }
  };

  // ==============================================
  // Loading State Manager
  // ==============================================
  
  const Loading = {
    /**
     * Show loading spinner inside an element
     * @param {HTMLElement|string} element 
     * @param {object} options - { size: 'sm'|'lg', overlay: boolean }
     */
    show(element, options = {}) {
      const el = typeof element === 'string' 
        ? document.querySelector(element) 
        : element;
      if (!el) return;
      
      // For buttons, use the btn-loading class
      if (el.tagName === 'BUTTON' || el.classList.contains('btn')) {
        el.dataset.originalText = el.innerHTML;
        el.classList.add('btn-loading');
        el.disabled = true;
        return;
      }
      
      // For containers, add overlay
      if (options.overlay !== false) {
        const overlay = document.createElement('div');
        overlay.className = 'loading-overlay';
        overlay.innerHTML = `<div class="spinner ${options.size === 'sm' ? 'spinner-sm' : options.size === 'lg' ? 'spinner-lg' : ''}"></div>`;
        el.style.position = 'relative';
        el.appendChild(overlay);
        
        // Force reflow and show
        requestAnimationFrame(() => {
          overlay.classList.add('is-active');
        });
      }
    },
    
    /**
     * Hide loading state
     * @param {HTMLElement|string} element 
     */
    hide(element) {
      const el = typeof element === 'string' 
        ? document.querySelector(element) 
        : element;
      if (!el) return;
      
      // For buttons
      if (el.classList.contains('btn-loading')) {
        el.classList.remove('btn-loading');
        el.disabled = false;
        if (el.dataset.originalText) {
          el.innerHTML = el.dataset.originalText;
          delete el.dataset.originalText;
        }
        return;
      }
      
      // For containers
      const overlay = el.querySelector('.loading-overlay');
      if (overlay) {
        overlay.classList.remove('is-active');
        setTimeout(() => overlay.remove(), 150);
      }
    },
    
    /**
     * Create a standalone spinner element
     * @param {string} size - 'sm' | 'lg' | default
     * @returns {HTMLElement}
     */
    createSpinner(size) {
      const spinner = document.createElement('span');
      spinner.className = `spinner ${size === 'sm' ? 'spinner-sm' : size === 'lg' ? 'spinner-lg' : ''}`;
      return spinner;
    },
    
    /**
     * Create a dots spinner
     * @returns {HTMLElement}
     */
    createDotsSpinner() {
      const container = document.createElement('span');
      container.className = 'spinner-dots';
      for (let i = 0; i < 3; i++) {
        container.appendChild(document.createElement('span'));
      }
      return container;
    }
  };

  // ==============================================
  // Toast Notification System
  // ==============================================
  
  const Toast = {
    container: null,
    
    /**
     * Initialize or get the toast container
     * @returns {HTMLElement}
     */
    getContainer() {
      if (!this.container || !this.container.isConnected) {
        this.container = document.createElement('div');
        this.container.className = 'toast-container';
        this.container.style.cssText = `
          position: fixed;
          bottom: 20px;
          left: 20px;
          right: 20px;
          z-index: 10000;
          display: flex;
          flex-direction: column;
          gap: 10px;
          align-items: flex-end;
          pointer-events: none;
        `;
        document.body.appendChild(this.container);
      }
      return this.container;
    },
    
    /**
     * Show a toast notification
     * @param {string} message 
     * @param {object} options - { type: 'success'|'error'|'warning'|'info', duration: ms, icon: string }
     */
    show(message, options = {}) {
      const container = this.getContainer();
      const type = options.type || 'info';
      const duration = options.duration || 4000;
      
      const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ'
      };
      
      const toast = document.createElement('div');
      toast.className = `toast toast-${type}`;
      toast.style.cssText = `
        background: var(--bookmarks-notification-bg, rgba(255, 255, 255, 0.97));
        color: var(--bookmarks-notification-color, #212529);
        border-radius: 8px;
        padding: 12px 20px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 250px;
        max-width: 400px;
        pointer-events: auto;
        border-left: 4px solid var(--bookmarks-${type}-color, var(--${type}, #17a2b8));
      `;
      
      toast.innerHTML = `
        <span class="toast-icon" style="font-size: 18px; font-weight: bold; color: var(--bookmarks-${type}-color, var(--${type}));">${options.icon || icons[type]}</span>
        <span class="toast-message" style="flex: 1; font-size: 14px;">${this.escapeHtml(message)}</span>
        <button class="toast-close" style="background: none; border: none; cursor: pointer; font-size: 18px; opacity: 0.6; padding: 0;">&times;</button>
      `;
      
      // Add to container (will animate via CSS)
      container.appendChild(toast);
      
      // Trigger animation
      if (!prefersReducedMotion()) {
        toast.classList.add('toast-enter');
      }
      
      // Close button handler
      const closeBtn = toast.querySelector('.toast-close');
      const closeToast = () => {
        if (!prefersReducedMotion()) {
          toast.classList.remove('toast-enter');
          toast.classList.add('toast-exit');
          toast.addEventListener('animationend', () => toast.remove(), { once: true });
        } else {
          toast.remove();
        }
      };
      
      closeBtn.addEventListener('click', closeToast);
      
      // Auto-remove after duration
      if (duration > 0) {
        setTimeout(closeToast, duration);
      }
      
      return toast;
    },
    
    success(message, options = {}) {
      return this.show(message, { ...options, type: 'success' });
    },
    
    error(message, options = {}) {
      return this.show(message, { ...options, type: 'error' });
    },
    
    warning(message, options = {}) {
      return this.show(message, { ...options, type: 'warning' });
    },
    
    info(message, options = {}) {
      return this.show(message, { ...options, type: 'info' });
    },
    
    escapeHtml(str) {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
      return String(str || '').replace(/[&<>"']/g, m => map[m]);
    }
  };

  // ==============================================
  // CRUD Animation Helpers
  // ==============================================
  
  const Animate = {
    /**
     * Animate an element entering the DOM
     * @param {HTMLElement} element 
     * @param {string} type - 'fadeIn' | 'slideIn' | 'popIn' | 'stagger'
     */
    enter(element, type = 'fadeIn') {
      if (prefersReducedMotion()) {
        element.style.opacity = '1';
        return Promise.resolve();
      }
      
      const animations = {
        fadeIn: 'anim-fade-in',
        fadeInUp: 'anim-fade-in-up',
        fadeInDown: 'anim-fade-in-down',
        slideIn: 'anim-slide-in-right',
        slideInLeft: 'anim-slide-in-left',
        popIn: 'anim-pop-in',
        scaleIn: 'anim-scale-in'
      };
      
      const animClass = animations[type] || animations.fadeIn;
      element.classList.add(animClass);
      
      return new Promise(resolve => {
        element.addEventListener('animationend', () => {
          element.classList.remove(animClass);
          resolve();
        }, { once: true });
      });
    },
    
    /**
     * Animate an element leaving the DOM
     * @param {HTMLElement} element 
     * @param {string} type - 'fadeOut' | 'slideOut' | 'popOut'
     */
    exit(element, type = 'fadeOut') {
      if (prefersReducedMotion()) {
        element.remove();
        return Promise.resolve();
      }
      
      return new Promise(resolve => {
        element.classList.add('item-exit');
        element.addEventListener('animationend', () => {
          element.remove();
          resolve();
        }, { once: true });
      });
    },
    
    /**
     * Flash success animation on an element
     * @param {HTMLElement} element 
     */
    success(element) {
      if (prefersReducedMotion()) return;
      element.classList.add('anim-success-flash');
      element.addEventListener('animationend', () => {
        element.classList.remove('anim-success-flash');
      }, { once: true });
    },
    
    /**
     * Shake element to indicate error
     * @param {HTMLElement} element 
     */
    error(element) {
      if (prefersReducedMotion()) return;
      element.classList.add('anim-error-shake');
      element.addEventListener('animationend', () => {
        element.classList.remove('anim-error-shake');
      }, { once: true });
    },
    
    /**
     * Pulse attention animation
     * @param {HTMLElement} element 
     */
    pulse(element) {
      if (prefersReducedMotion()) return;
      element.classList.add('anim-pulse');
    },
    
    /**
     * Stop pulse animation
     * @param {HTMLElement} element 
     */
    stopPulse(element) {
      element.classList.remove('anim-pulse');
    },
    
    /**
     * Glow effect for highlighting
     * @param {HTMLElement} element 
     * @param {number} duration - ms
     */
    glow(element, duration = 2000) {
      if (prefersReducedMotion()) return;
      element.classList.add('anim-glow');
      if (duration > 0) {
        setTimeout(() => element.classList.remove('anim-glow'), duration);
      }
    },
    
    /**
     * Animate badge count update
     * @param {HTMLElement} badge 
     * @param {number|string} newValue 
     */
    updateBadge(badge, newValue) {
      badge.textContent = newValue;
      if (!prefersReducedMotion()) {
        badge.classList.add('updated');
        badge.addEventListener('animationend', () => {
          badge.classList.remove('updated');
        }, { once: true });
      }
    },
    
    /**
     * Stagger animate children elements
     * @param {HTMLElement} container 
     */
    staggerChildren(container) {
      if (prefersReducedMotion()) return;
      container.classList.add('stagger-children');
    }
  };

  // ==============================================
  // Ripple Effect for Buttons
  // ==============================================
  
  const Ripple = {
    /**
     * Add ripple effect to elements
     * @param {string|HTMLElement|NodeList} selector 
     */
    init(selector = '.btn-ripple') {
      const elements = typeof selector === 'string' 
        ? document.querySelectorAll(selector)
        : selector instanceof NodeList ? selector : [selector];
      
      elements.forEach(el => {
        if (el._rippleInit) return;
        el._rippleInit = true;
        
        el.addEventListener('click', (e) => this.create(e, el));
      });
    },
    
    /**
     * Create ripple on click
     * @param {MouseEvent} event 
     * @param {HTMLElement} element 
     */
    create(event, element) {
      if (prefersReducedMotion()) return;
      
      const rect = element.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      
      const ripple = document.createElement('span');
      ripple.className = 'ripple-effect';
      ripple.style.cssText = `
        left: ${x}px;
        top: ${y}px;
        width: ${Math.max(rect.width, rect.height)}px;
        height: ${Math.max(rect.width, rect.height)}px;
      `;
      
      element.appendChild(ripple);
      
      ripple.addEventListener('animationend', () => ripple.remove());
    }
  };

  // ==============================================
  // Modal Animation Helper
  // ==============================================
  
  const Modal = {
    /**
     * Open modal with animation
     * @param {HTMLElement|string} modal 
     */
    open(modal) {
      const el = typeof modal === 'string' ? document.querySelector(modal) : modal;
      if (!el) return;
      
      const backdrop = el.querySelector('.modal-backdrop, .collection-modal__backdrop');
      const content = el.querySelector('.modal-content, .collection-modal__panel');
      
      el.style.display = 'flex';
      
      requestAnimationFrame(() => {
        if (backdrop) backdrop.classList.add('is-visible');
        if (content) content.classList.add('is-visible');
      });
    },
    
    /**
     * Close modal with animation
     * @param {HTMLElement|string} modal 
     */
    close(modal) {
      const el = typeof modal === 'string' ? document.querySelector(modal) : modal;
      if (!el) return;
      
      const backdrop = el.querySelector('.modal-backdrop, .collection-modal__backdrop');
      const content = el.querySelector('.modal-content, .collection-modal__panel');
      
      if (backdrop) backdrop.classList.remove('is-visible');
      if (content) content.classList.remove('is-visible');
      
      const duration = prefersReducedMotion() ? 0 : 250;
      setTimeout(() => {
        el.style.display = 'none';
        // Optionally remove the modal entirely
        // el.remove();
      }, duration);
    }
  };

  // ==============================================
  // Smooth Content Transitions
  // ==============================================
  
  const Transition = {
    /**
     * Smoothly transition content of an element
     * @param {HTMLElement|string} container 
     * @param {Function} updateFn - Function that updates the content
     * @param {object} options - { duration, animation }
     */
    async content(container, updateFn, options = {}) {
      const el = typeof container === 'string' ? document.querySelector(container) : container;
      if (!el) return;
      
      if (prefersReducedMotion()) {
        await updateFn();
        return;
      }
      
      const duration = options.duration || 150;
      
      // Fade out
      el.style.transition = `opacity ${duration}ms ease`;
      el.style.opacity = '0';
      
      await new Promise(resolve => setTimeout(resolve, duration));
      
      // Update content
      await updateFn();
      
      // Fade in
      el.style.opacity = '1';
      
      await new Promise(resolve => setTimeout(resolve, duration));
      
      // Clean up
      el.style.transition = '';
    },
    
    /**
     * Crossfade between two elements
     * @param {HTMLElement} fromEl 
     * @param {HTMLElement} toEl 
     * @param {number} duration 
     */
    crossfade(fromEl, toEl, duration = 300) {
      if (prefersReducedMotion()) {
        fromEl.style.display = 'none';
        toEl.style.display = '';
        return Promise.resolve();
      }
      
      return new Promise(resolve => {
        toEl.style.opacity = '0';
        toEl.style.display = '';
        
        const step = 16 / duration;
        let progress = 0;
        
        const animate = () => {
          progress += step;
          if (progress >= 1) {
            fromEl.style.display = 'none';
            fromEl.style.opacity = '1';
            toEl.style.opacity = '1';
            resolve();
            return;
          }
          
          fromEl.style.opacity = String(1 - progress);
          toEl.style.opacity = String(progress);
          requestAnimationFrame(animate);
        };
        
        requestAnimationFrame(animate);
      });
    }
  };

  // ==============================================
  // Collapse/Expand Animation
  // ==============================================
  
  const Collapse = {
    /**
     * Toggle collapse state with animation
     * @param {HTMLElement|string} element 
     * @param {boolean} show - Force show/hide, or toggle if undefined
     */
    toggle(element, show) {
      const el = typeof element === 'string' ? document.querySelector(element) : element;
      if (!el) return;
      
      const isExpanded = el.classList.contains('is-expanded');
      const shouldExpand = show !== undefined ? show : !isExpanded;
      
      if (shouldExpand) {
        el.style.maxHeight = el.scrollHeight + 'px';
        el.classList.add('is-expanded');
        // Clear inline maxHeight after transition to allow content to grow
        const onTransitionEnd = () => {
          el.style.maxHeight = '';
          el.removeEventListener('transitionend', onTransitionEnd);
        };
        el.addEventListener('transitionend', onTransitionEnd);
      } else {
        el.style.maxHeight = el.scrollHeight + 'px';
        requestAnimationFrame(() => {
          el.style.maxHeight = '0';
          el.classList.remove('is-expanded');
        });
      }
    },
    
    /**
     * Initialize collapsible elements
     * @param {string} triggerSelector 
     * @param {string} targetAttr - Attribute containing target selector
     */
    init(triggerSelector, targetAttr = 'data-collapse-target') {
      document.querySelectorAll(triggerSelector).forEach(trigger => {
        trigger.addEventListener('click', () => {
          const targetSelector = trigger.getAttribute(targetAttr);
          if (targetSelector) {
            this.toggle(targetSelector);
          }
        });
      });
    }
  };

  // ==============================================
  // Initialize Auto-Features
  // ==============================================
  
  function initAutoFeatures() {
    // Auto-init ripple effects on buttons with class
    Ripple.init('.btn-ripple');
    
    // Add animated class to inputs
    document.querySelectorAll('input:not([type="checkbox"]):not([type="radio"]), textarea, select').forEach(el => {
      if (!el.classList.contains('input-animated')) {
        // el.classList.add('input-animated'); // Uncomment to auto-apply
      }
    });
    
    // Add hover lift to cards with class
    document.querySelectorAll('.card-hover').forEach(el => {
      el.classList.add('card-hover-lift');
    });
  }

  // Run on DOMContentLoaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAutoFeatures);
  } else {
    initAutoFeatures();
  }

  // ==============================================
  // Export to Global Scope
  // ==============================================
  
  window.AnimUtils = {
    Skeleton,
    Loading,
    Toast,
    Animate,
    Ripple,
    Modal,
    Transition,
    Collapse,
    prefersReducedMotion
  };

  // Shorthand aliases
  window.showToast = Toast.show.bind(Toast);
  window.showLoading = Loading.show.bind(Loading);
  window.hideLoading = Loading.hide.bind(Loading);

})();

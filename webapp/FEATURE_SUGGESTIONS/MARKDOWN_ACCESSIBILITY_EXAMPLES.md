# 🔍 דוגמאות מעשיות למימוש Markdown נגיש

## 📝 דוגמאות קוד מלאות

### 1. קובץ HTML מלא עם כל התכונות

```html
<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>תצוגת Markdown נגישה</title>
  
  <!-- סגנונות נגישות -->
  <style>
    /* משתנים לנושאים */
    :root {
      --text-color: #1a1a1a;
      --bg-color: #ffffff;
      --accent-color: #0366d6;
      --code-bg: #f6f8fa;
      --focus-color: #0366d6;
      --focus-outline: 2px solid var(--focus-color);
    }
    
    /* Dark mode */
    @media (prefers-color-scheme: dark) {
      :root {
        --text-color: #e0e0e0;
        --bg-color: #1a1a1a;
        --accent-color: #58a6ff;
        --code-bg: #2d2d2d;
      }
    }
    
    /* High contrast mode */
    @media (prefers-contrast: high) {
      :root {
        --focus-outline: 3px solid var(--focus-color);
      }
      
      .header-anchor,
      .md-copy-btn {
        border-width: 2px !important;
      }
    }
    
    /* Base styles */
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: var(--text-color);
      background: var(--bg-color);
      line-height: 1.6;
      padding: 20px;
    }
    
    /* Skip to content link */
    .skip-link {
      position: absolute;
      top: -40px;
      left: 0;
      background: var(--accent-color);
      color: white;
      padding: 8px;
      text-decoration: none;
      z-index: 100;
    }
    
    .skip-link:focus {
      top: 0;
    }
    
    /* Header anchors */
    h1, h2, h3, h4, h5, h6 {
      position: relative;
      scroll-margin-top: 80px; /* מרווח לגלילה חלקה */
    }
    
    .header-anchor {
      position: absolute;
      right: 100%;
      padding-left: 0.5em;
      opacity: 0;
      color: var(--accent-color);
      text-decoration: none;
      transition: opacity 0.2s;
    }
    
    h1:hover .header-anchor,
    h2:hover .header-anchor,
    h3:hover .header-anchor,
    .header-anchor:focus {
      opacity: 1;
    }
    
    .header-anchor:focus {
      outline: var(--focus-outline);
      outline-offset: 2px;
      border-radius: 3px;
    }
    
    /* Code blocks */
    .code-block {
      position: relative;
      margin: 1em 0;
    }
    
    pre {
      background: var(--code-bg);
      padding: 1em;
      border-radius: 8px;
      overflow-x: auto;
      tab-size: 2;
    }
    
    .md-copy-btn {
      position: absolute;
      top: 8px;
      left: 8px;
      background: white;
      border: 1px solid #d1d5da;
      border-radius: 6px;
      padding: 4px 8px;
      font-size: 12px;
      cursor: pointer;
      transition: all 0.2s;
    }
    
    .md-copy-btn:focus {
      outline: var(--focus-outline);
      outline-offset: 2px;
    }
    
    .md-copy-btn:hover {
      background: #f6f8fa;
      transform: translateY(-1px);
    }
    
    .md-copy-btn.copied {
      background: #28a745;
      color: white;
      border-color: #28a745;
    }
    
    /* Accessibility helpers */
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    
    /* Announcement area */
    #aria-live-region {
      position: absolute;
      left: -10000px;
      width: 1px;
      height: 1px;
      overflow: hidden;
    }
    
    /* Focus indicator */
    *:focus-visible {
      outline: var(--focus-outline);
      outline-offset: 2px;
    }
    
    /* Print styles */
    @media print {
      .header-anchor,
      .md-copy-btn,
      .skip-link {
        display: none !important;
      }
      
      h1, h2, h3, h4, h5, h6 {
        page-break-after: avoid;
      }
      
      pre {
        page-break-inside: avoid;
      }
    }
  </style>
</head>
<body>
  <!-- Skip navigation -->
  <a href="#main-content" class="skip-link">דלג לתוכן הראשי</a>
  
  <!-- ARIA live region for announcements -->
  <div id="aria-live-region" aria-live="polite" aria-atomic="true"></div>
  
  <!-- Main content -->
  <main id="main-content" role="main" aria-label="תוכן המסמך">
    <article id="md-content">
      <!-- Content will be rendered here -->
    </article>
  </main>
  
  <!-- Table of contents (נגיש) -->
  <nav id="toc" role="navigation" aria-label="תוכן עניינים">
    <h2 id="toc-heading">תוכן עניינים</h2>
    <ul aria-labelledby="toc-heading">
      <!-- TOC items will be added here -->
    </ul>
  </nav>
  
  <script type="module">
    // Import markdown-it and plugins
    import markdownit from 'markdown-it';
    import markdownitAnchor from 'markdown-it-anchor';
    
    // Initialize markdown parser
    const md = markdownit({
      html: false,
      linkify: true,
      typographer: true
    });
    
    // Configure anchor plugin for accessibility
    md.use(markdownitAnchor, {
      level: [1, 2, 3, 4],
      permalink: markdownitAnchor.permalink.headerLink({
        class: 'header-anchor',
        symbol: '🔗',
        renderAttrs: (slug, state) => {
          // Generate accessible attributes
          const headingText = state.tokens
            .filter(token => token.type === 'inline')
            .map(token => token.content)
            .join('');
          
          return {
            'aria-label': `קישור קבוע לסעיף: ${headingText}`,
            'title': 'לחץ להעתקת קישור',
            'role': 'link',
            'tabindex': '0'
          };
        }
      }),
      slugify: (str) => {
        // Support Hebrew and special characters
        return str
          .trim()
          .toLowerCase()
          .replace(/[^\w\u0590-\u05FF\s-]/g, '')
          .replace(/[\s_]+/g, '-')
          .replace(/^-+|-+$/g, '');
      }
    });
    
    // Main initialization function
    async function initializeAccessibleMarkdown() {
      try {
        // Fetch or get markdown content
        const markdownContent = await getMarkdownContent();
        
        // Render markdown
        const htmlContent = md.render(markdownContent);
        document.getElementById('md-content').innerHTML = htmlContent;
        
        // Enhance accessibility
        await enhanceAccessibility();
        
        // Build table of contents
        buildAccessibleTOC();
        
        // Setup keyboard navigation
        setupKeyboardShortcuts();
        
        // Initialize copy buttons
        addCopyButtons();
        
        // Setup permalink handlers
        setupPermalinkHandlers();
        
        // Restore scroll position if needed
        restoreScrollPosition();
        
        // Announce ready state
        announce('המסמך מוכן לקריאה');
        
      } catch (error) {
        console.error('Failed to initialize:', error);
        announce('שגיאה בטעינת המסמך');
      }
    }
    
    // Accessibility enhancement function
    async function enhanceAccessibility() {
      // Add language attributes for mixed content
      document.querySelectorAll('code').forEach(code => {
        code.setAttribute('lang', 'en');
        code.setAttribute('dir', 'ltr');
      });
      
      // Ensure all images have alt text
      document.querySelectorAll('img').forEach(img => {
        if (!img.hasAttribute('alt')) {
          img.setAttribute('alt', 'תמונה במסמך');
        }
      });
      
      // Make tables accessible
      document.querySelectorAll('table').forEach(table => {
        if (!table.querySelector('caption')) {
          const caption = document.createElement('caption');
          caption.textContent = 'טבלת נתונים';
          caption.className = 'sr-only';
          table.prepend(caption);
        }
        
        // Mark header cells
        table.querySelectorAll('thead th').forEach(th => {
          th.setAttribute('scope', 'col');
        });
        
        table.querySelectorAll('tbody tr th').forEach(th => {
          th.setAttribute('scope', 'row');
        });
      });
      
      // Add ARIA labels to lists
      document.querySelectorAll('ul, ol').forEach(list => {
        const items = list.querySelectorAll('li').length;
        list.setAttribute('aria-label', `רשימה עם ${items} פריטים`);
      });
    }
    
    // Build accessible table of contents
    function buildAccessibleTOC() {
      const toc = document.getElementById('toc');
      const tocList = toc.querySelector('ul');
      const headings = document.querySelectorAll('h1, h2, h3, h4');
      
      // Clear existing TOC
      tocList.innerHTML = '';
      
      headings.forEach((heading, index) => {
        const level = parseInt(heading.tagName.substring(1));
        const text = heading.textContent.replace('🔗', '').trim();
        const id = heading.id || `heading-${index}`;
        
        // Ensure heading has ID
        if (!heading.id) {
          heading.id = id;
        }
        
        // Create TOC item
        const li = document.createElement('li');
        li.setAttribute('role', 'none');
        li.style.marginRight = `${(level - 1) * 20}px`;
        
        const link = document.createElement('a');
        link.href = `#${id}`;
        link.textContent = text;
        link.setAttribute('aria-label', `עבור ל: ${text}`);
        
        // Add click handler for smooth scroll
        link.addEventListener('click', (e) => {
          e.preventDefault();
          heading.scrollIntoView({ behavior: 'smooth', block: 'start' });
          heading.focus();
          announce(`עברת לסעיף: ${text}`);
        });
        
        li.appendChild(link);
        tocList.appendChild(li);
      });
      
      // Hide TOC if no headings
      if (headings.length === 0) {
        toc.style.display = 'none';
      }
    }
    
    // Add copy buttons to code blocks
    function addCopyButtons() {
      document.querySelectorAll('pre').forEach(pre => {
        // Skip if button already exists
        if (pre.querySelector('.md-copy-btn')) return;
        
        // Create wrapper
        const wrapper = document.createElement('div');
        wrapper.className = 'code-block';
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);
        
        // Create copy button
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'md-copy-btn';
        btn.innerHTML = '📋 העתק';
        btn.setAttribute('aria-label', 'העתק קוד');
        
        // Add click handler
        btn.addEventListener('click', async () => {
          const code = pre.textContent;
          
          try {
            await navigator.clipboard.writeText(code);
            handleCopySuccess(btn);
          } catch (err) {
            handleCopyFallback(code, btn);
          }
        });
        
        wrapper.appendChild(btn);
      });
    }
    
    // Handle successful copy
    function handleCopySuccess(btn) {
      btn.classList.add('copied');
      btn.innerHTML = '✅ הועתק!';
      announce('הקוד הועתק ללוח');
      
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.innerHTML = '📋 העתק';
      }, 2000);
    }
    
    // Fallback copy method
    function handleCopyFallback(text, btn) {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      textarea.setAttribute('aria-hidden', 'true');
      
      document.body.appendChild(textarea);
      textarea.select();
      
      try {
        document.execCommand('copy');
        handleCopySuccess(btn);
      } catch (err) {
        btn.innerHTML = '❌ שגיאה';
        announce('ההעתקה נכשלה');
        setTimeout(() => {
          btn.innerHTML = '📋 העתק';
        }, 2000);
      } finally {
        document.body.removeChild(textarea);
      }
    }
    
    // Setup permalink handlers
    function setupPermalinkHandlers() {
      document.querySelectorAll('.header-anchor').forEach(anchor => {
        anchor.addEventListener('click', async (e) => {
          e.preventDefault();
          
          const url = new URL(window.location);
          url.hash = anchor.getAttribute('href').substring(1);
          
          try {
            await navigator.clipboard.writeText(url.toString());
            showTooltip(anchor, 'הקישור הועתק!');
            announce('קישור לכותרת הועתק');
          } catch (err) {
            console.error('Failed to copy link:', err);
          }
          
          // Scroll to header
          const targetId = anchor.getAttribute('href').substring(1);
          const target = document.getElementById(targetId);
          if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
            target.focus();
          }
        });
        
        // Support keyboard activation
        anchor.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            anchor.click();
          }
        });
      });
    }
    
    // Show tooltip near element
    function showTooltip(element, message) {
      const tooltip = document.createElement('div');
      tooltip.className = 'tooltip';
      tooltip.textContent = message;
      tooltip.setAttribute('role', 'tooltip');
      tooltip.style.cssText = `
        position: absolute;
        background: rgba(0, 0, 0, 0.8);
        color: white;
        padding: 5px 10px;
        border-radius: 4px;
        font-size: 12px;
        z-index: 1000;
        pointer-events: none;
      `;
      
      // Position tooltip
      const rect = element.getBoundingClientRect();
      tooltip.style.top = `${rect.top - 30}px`;
      tooltip.style.left = `${rect.left}px`;
      
      document.body.appendChild(tooltip);
      
      setTimeout(() => {
        tooltip.style.opacity = '0';
        setTimeout(() => document.body.removeChild(tooltip), 300);
      }, 2000);
    }
    
    // Keyboard shortcuts
    function setupKeyboardShortcuts() {
      document.addEventListener('keydown', (e) => {
        // Ctrl+Alt+C - Copy first code block
        if (e.ctrlKey && e.altKey && e.key === 'c') {
          e.preventDefault();
          const firstCopyBtn = document.querySelector('.md-copy-btn');
          if (firstCopyBtn) {
            firstCopyBtn.click();
            firstCopyBtn.focus();
          }
        }
        
        // Ctrl+Alt+T - Jump to TOC
        if (e.ctrlKey && e.altKey && e.key === 't') {
          e.preventDefault();
          const toc = document.getElementById('toc');
          if (toc) {
            toc.scrollIntoView({ behavior: 'smooth' });
            toc.querySelector('a')?.focus();
          }
        }
        
        // Ctrl+Alt+L - Copy link to current section
        if (e.ctrlKey && e.altKey && e.key === 'l') {
          e.preventDefault();
          const currentHeader = getCurrentVisibleHeader();
          if (currentHeader) {
            const anchor = currentHeader.querySelector('.header-anchor');
            if (anchor) anchor.click();
          }
        }
      });
    }
    
    // Get currently visible header
    function getCurrentVisibleHeader() {
      const headers = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
      const scrollPos = window.scrollY + 100;
      
      let current = null;
      headers.forEach(header => {
        if (header.offsetTop <= scrollPos) {
          current = header;
        }
      });
      
      return current || headers[0];
    }
    
    // Restore scroll position from URL hash
    function restoreScrollPosition() {
      const hash = window.location.hash;
      if (hash) {
        const element = document.querySelector(hash);
        if (element) {
          setTimeout(() => {
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
            element.focus();
            
            // Announce navigation
            const text = element.textContent.replace('🔗', '').trim();
            announce(`עברת לסעיף: ${text}`);
          }, 100);
        }
      }
    }
    
    // Announce message to screen readers
    function announce(message) {
      const region = document.getElementById('aria-live-region');
      region.textContent = message;
      
      // Clear after announcement
      setTimeout(() => {
        region.textContent = '';
      }, 1000);
    }
    
    // Mock function to get markdown content
    async function getMarkdownContent() {
      // In real implementation, fetch from server
      return `
# דוגמה למסמך Markdown נגיש

## מבוא
זהו מסמך דוגמה המדגים תכונות נגישות.

### קוד לדוגמה
\`\`\`javascript
function hello() {
  console.log("שלום עולם!");
}
\`\`\`

## סיכום
מסמך זה כולל:
- עוגני כותרות נגישים
- כפתורי העתקה לקוד
- תמיכה מלאה במקלדת
- תמיכה בקוראי מסך
      `;
    }
    
    // Initialize on DOM ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initializeAccessibleMarkdown);
    } else {
      initializeAccessibleMarkdown();
    }
  </script>
</body>
</html>
```

### 2. בדיקות Cypress לנגישות

```javascript
// cypress/integration/markdown_accessibility.spec.js

describe('Markdown Accessibility Features', () => {
  beforeEach(() => {
    cy.visit('/md_preview/test-file');
    cy.injectAxe(); // Inject axe-core for a11y testing
  });

  describe('Keyboard Navigation', () => {
    it('should navigate with Tab key', () => {
      // Start from top
      cy.get('body').tab();
      
      // Should focus skip link first
      cy.focused().should('have.class', 'skip-link');
      
      // Tab through header anchors
      cy.tab();
      cy.focused().should('have.class', 'header-anchor');
      
      // Tab to copy buttons
      cy.tab();
      cy.focused().should('have.class', 'md-copy-btn');
    });

    it('should activate buttons with Enter and Space', () => {
      cy.get('.md-copy-btn').first().focus();
      
      // Test Enter key
      cy.focused().type('{enter}');
      cy.get('.md-copy-btn').first().should('have.class', 'copied');
      
      // Wait for reset
      cy.wait(2100);
      
      // Test Space key
      cy.focused().type(' ');
      cy.get('.md-copy-btn').first().should('have.class', 'copied');
    });

    it('should support keyboard shortcuts', () => {
      // Test Ctrl+Alt+C
      cy.get('body').type('{ctrl}{alt}c');
      cy.get('.md-copy-btn').first().should('have.class', 'copied');
      
      // Test Ctrl+Alt+T
      cy.get('body').type('{ctrl}{alt}t');
      cy.focused().should('be.visible')
        .and('have.attr', 'href')
        .and('include', '#');
      
      // Test Ctrl+Alt+L
      cy.get('body').type('{ctrl}{alt}l');
      cy.window().its('navigator.clipboard')
        .invoke('readText')
        .should('include', window.location.origin);
    });
  });

  describe('Screen Reader Support', () => {
    it('should have proper ARIA attributes', () => {
      // Check main landmarks
      cy.get('main').should('have.attr', 'role', 'main');
      cy.get('nav').should('have.attr', 'role', 'navigation');
      
      // Check header anchors
      cy.get('.header-anchor').each($anchor => {
        expect($anchor).to.have.attr('aria-label');
        expect($anchor).to.have.attr('role', 'link');
      });
      
      // Check copy buttons
      cy.get('.md-copy-btn').each($btn => {
        expect($btn).to.have.attr('aria-label', 'העתק קוד');
      });
      
      // Check live region
      cy.get('#aria-live-region')
        .should('have.attr', 'aria-live', 'polite')
        .and('have.attr', 'aria-atomic', 'true');
    });

    it('should announce actions to screen readers', () => {
      // Click copy button
      cy.get('.md-copy-btn').first().click();
      
      // Check announcement
      cy.get('#aria-live-region')
        .should('have.text', 'הקוד הועתק ללוח');
      
      // Click header anchor
      cy.get('.header-anchor').first().click();
      
      // Check announcement
      cy.get('#aria-live-region')
        .should('contain', 'קישור לכותרת הועתק');
    });
  });

  describe('Focus Management', () => {
    it('should show focus indicators', () => {
      cy.get('.header-anchor').first().focus();
      cy.focused().should('have.css', 'outline-style', 'solid');
      
      cy.get('.md-copy-btn').first().focus();
      cy.focused().should('have.css', 'outline-style', 'solid');
    });

    it('should trap focus in modals', () => {
      // If there are modals, test focus trap
      cy.get('.modal-trigger').click();
      
      // Tab should cycle within modal
      cy.tab();
      cy.focused().should('be.visible')
        .and('have.class', 'modal-element');
      
      // Escape should close modal
      cy.get('body').type('{esc}');
      cy.get('.modal').should('not.be.visible');
    });
  });

  describe('Visual Accessibility', () => {
    it('should have sufficient color contrast', () => {
      cy.checkA11y(null, {
        rules: {
          'color-contrast': { enabled: true }
        }
      });
    });

    it('should support dark mode', () => {
      // Simulate dark mode
      cy.get('html').invoke('attr', 'data-theme', 'dark');
      
      // Check that colors changed
      cy.get('body')
        .should('have.css', 'background-color')
        .and('not.equal', 'rgb(255, 255, 255)');
      
      // Still accessible in dark mode
      cy.checkA11y();
    });

    it('should support high contrast mode', () => {
      // Simulate high contrast
      cy.get('html').invoke('attr', 'data-contrast', 'high');
      
      // Check enhanced focus indicators
      cy.get('.header-anchor').first().focus();
      cy.focused()
        .should('have.css', 'outline-width')
        .and('equal', '3px');
    });

    it('should be responsive', () => {
      // Mobile view
      cy.viewport(320, 568);
      cy.checkA11y();
      
      // Tablet view
      cy.viewport(768, 1024);
      cy.checkA11y();
      
      // Desktop view
      cy.viewport(1920, 1080);
      cy.checkA11y();
    });
  });

  describe('Axe Accessibility Tests', () => {
    it('should have no detectable accessibility violations', () => {
      cy.checkA11y(null, {
        includedImpacts: ['critical', 'serious', 'moderate', 'minor']
      });
    });

    it('should have no violations in specific components', () => {
      // Test header anchors
      cy.checkA11y('.header-anchor');
      
      // Test copy buttons
      cy.checkA11y('.md-copy-btn');
      
      // Test table of contents
      cy.checkA11y('#toc');
      
      // Test code blocks
      cy.checkA11y('.code-block');
    });
  });
});
```

### 3. מקרי קצה וטיפול בשגיאות

```javascript
// Edge cases and error handling

class AccessibleMarkdownRenderer {
  constructor(options = {}) {
    this.options = {
      maxHeaderLength: 200,
      maxCodeBlockSize: 100000,
      enableKeyboardShortcuts: true,
      announceActions: true,
      ...options
    };
    
    this.init();
  }

  init() {
    this.setupErrorHandling();
    this.detectCapabilities();
    this.loadPolyfills();
  }

  // Error handling wrapper
  async safeExecute(fn, fallback = null) {
    try {
      return await fn();
    } catch (error) {
      console.error('Execution error:', error);
      
      // Report to analytics
      if (window.gtag) {
        gtag('event', 'exception', {
          description: error.message,
          fatal: false
        });
      }
      
      // Execute fallback
      if (fallback) {
        return fallback(error);
      }
      
      return null;
    }
  }

  // Detect browser capabilities
  detectCapabilities() {
    this.capabilities = {
      clipboard: 'clipboard' in navigator,
      intersectionObserver: 'IntersectionObserver' in window,
      smoothScroll: 'scrollBehavior' in document.documentElement.style,
      customElements: 'customElements' in window,
      focus: 'focus' in document.documentElement,
      ariaLive: true // Assume support, graceful degradation
    };
  }

  // Load polyfills for missing features
  async loadPolyfills() {
    const polyfills = [];
    
    // Clipboard API polyfill
    if (!this.capabilities.clipboard) {
      polyfills.push(this.loadClipboardPolyfill());
    }
    
    // Smooth scroll polyfill
    if (!this.capabilities.smoothScroll) {
      polyfills.push(this.loadSmoothScrollPolyfill());
    }
    
    // Intersection Observer polyfill
    if (!this.capabilities.intersectionObserver) {
      polyfills.push(this.loadIntersectionObserverPolyfill());
    }
    
    await Promise.all(polyfills);
  }

  // Handle special characters in headers
  sanitizeHeaderId(text) {
    // Handle Hebrew
    const hebrewNormalized = text.replace(/[\u0591-\u05C7]/g, ''); // Remove Hebrew diacritics
    
    // Handle emojis
    const emojiRemoved = hebrewNormalized.replace(/[\u{1F600}-\u{1F64F}]|[\u{1F300}-\u{1F5FF}]|[\u{1F680}-\u{1F6FF}]|[\u{1F700}-\u{1F77F}]|[\u{1F780}-\u{1F7FF}]|[\u{1F800}-\u{1F8FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]/gu, '');
    
    // Handle special characters
    const cleaned = emojiRemoved
      .trim()
      .toLowerCase()
      .replace(/[^\w\u0590-\u05FF\u0400-\u04FF\s-]/g, '') // Keep Hebrew, Cyrillic
      .replace(/[\s_]+/g, '-')
      .replace(/^-+|-+$/g, '');
    
    // Ensure not empty
    return cleaned || `section-${Date.now()}`;
  }

  // Handle very long headers
  truncateHeaderText(text, maxLength = 200) {
    if (text.length <= maxLength) return text;
    
    // Find last word boundary before max length
    const truncated = text.substring(0, maxLength);
    const lastSpace = truncated.lastIndexOf(' ');
    
    if (lastSpace > maxLength * 0.8) {
      return truncated.substring(0, lastSpace) + '...';
    }
    
    return truncated + '...';
  }

  // Handle large code blocks
  async handleLargeCodeBlock(code, language = '') {
    const sizeInBytes = new Blob([code]).size;
    
    // If too large, offer download
    if (sizeInBytes > this.options.maxCodeBlockSize) {
      return this.createDownloadableCodeBlock(code, language);
    }
    
    // If moderately large, use virtual scrolling
    if (code.split('\n').length > 1000) {
      return this.createVirtualScrollCodeBlock(code, language);
    }
    
    // Otherwise render normally
    return this.createStandardCodeBlock(code, language);
  }

  // Create downloadable code block for very large code
  createDownloadableCodeBlock(code, language) {
    const blob = new Blob([code], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    
    const container = document.createElement('div');
    container.className = 'large-code-block';
    container.innerHTML = `
      <div class="code-info">
        <p>קוד גדול מדי לתצוגה (${this.formatBytes(blob.size)})</p>
        <a href="${url}" 
           download="code.${language || 'txt'}"
           class="download-code-btn"
           aria-label="הורד קובץ קוד">
          📥 הורד קוד
        </a>
      </div>
      <details>
        <summary>הצג 100 שורות ראשונות</summary>
        <pre><code class="language-${language}">${this.escapeHtml(
          code.split('\n').slice(0, 100).join('\n')
        )}</code></pre>
      </details>
    `;
    
    return container;
  }

  // Handle clipboard API fallbacks
  async copyToClipboard(text) {
    // Try modern API
    if (this.capabilities.clipboard) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (err) {
        console.warn('Clipboard API failed:', err);
      }
    }
    
    // Try execCommand
    if (document.queryCommandSupported('copy')) {
      return this.copyWithExecCommand(text);
    }
    
    // Try IE specific
    if (window.clipboardData) {
      try {
        window.clipboardData.setData('Text', text);
        return true;
      } catch (err) {
        console.warn('IE clipboard failed:', err);
      }
    }
    
    // Show manual copy dialog
    return this.showManualCopyDialog(text);
  }

  // Manual copy dialog for unsupported browsers
  showManualCopyDialog(text) {
    const dialog = document.createElement('div');
    dialog.className = 'manual-copy-dialog';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-label', 'העתק טקסט ידנית');
    
    dialog.innerHTML = `
      <div class="dialog-content">
        <h3>העתק ידנית</h3>
        <p>הדפדפן שלך לא תומך בהעתקה אוטומטית. אנא סמן והעתק:</p>
        <textarea readonly aria-label="טקסט להעתקה">${this.escapeHtml(text)}</textarea>
        <div class="dialog-actions">
          <button class="select-all-btn">בחר הכל</button>
          <button class="close-dialog-btn">סגור</button>
        </div>
      </div>
    `;
    
    document.body.appendChild(dialog);
    
    // Focus and select
    const textarea = dialog.querySelector('textarea');
    textarea.focus();
    textarea.select();
    
    // Handle buttons
    dialog.querySelector('.select-all-btn').addEventListener('click', () => {
      textarea.select();
    });
    
    dialog.querySelector('.close-dialog-btn').addEventListener('click', () => {
      document.body.removeChild(dialog);
    });
    
    return false;
  }

  // Handle broken images
  handleBrokenImages() {
    document.querySelectorAll('img').forEach(img => {
      img.addEventListener('error', () => {
        // Add broken image indicator
        img.classList.add('broken-image');
        
        // Update alt text
        const originalAlt = img.getAttribute('alt') || '';
        img.setAttribute('alt', `תמונה לא זמינה: ${originalAlt}`);
        
        // Add placeholder
        img.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAwIiBoZWlnaHQ9IjMwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iNDAwIiBoZWlnaHQ9IjMwMCIgZmlsbD0iI2VlZSIvPjx0ZXh0IHRleHQtYW5jaG9yPSJtaWRkbGUiIHg9IjIwMCIgeT0iMTUwIiBzdHlsZT0iZmlsbDojOTk5O2ZvbnQtZmFtaWx5OkFyaWFsLHNhbnMtc2VyaWY7Zm9udC1zaXplOjI2cHgiPuKcmCDXqtee15XXoNeUINeW157XmdeZ16DXlDwvdGV4dD48L3N2Zz4=';
      });
    });
  }

  // Helper functions
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  }
}

// Usage
const renderer = new AccessibleMarkdownRenderer({
  maxHeaderLength: 150,
  maxCodeBlockSize: 50000,
  enableKeyboardShortcuts: true,
  announceActions: true
});
```

## 🧩 אינטגרציות מתקדמות

### אינטגרציה עם מערכת Bookmarks

```javascript
// Integration with existing bookmark system
class MarkdownBookmarkIntegration {
  constructor() {
    this.bookmarkManager = window.bookmarkManager;
    this.init();
  }

  init() {
    if (!this.bookmarkManager) {
      console.warn('Bookmark manager not available');
      return;
    }

    this.enhanceHeadersWithBookmarks();
    this.setupBookmarkShortcuts();
  }

  enhanceHeadersWithBookmarks() {
    document.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(header => {
      const bookmarkBtn = document.createElement('button');
      bookmarkBtn.className = 'bookmark-header-btn';
      bookmarkBtn.innerHTML = '🔖';
      bookmarkBtn.setAttribute('aria-label', `הוסף סימניה ל: ${header.textContent}`);
      
      bookmarkBtn.addEventListener('click', async () => {
        const result = await this.bookmarkManager.api.toggleBookmarkAnchor(
          header.id,
          header.textContent,
          'markdown_header'
        );
        
        if (result.ok) {
          bookmarkBtn.classList.toggle('bookmarked');
          this.announce(result.bookmarked ? 'סימניה נוספה' : 'סימניה הוסרה');
        }
      });

      header.appendChild(bookmarkBtn);
    });
  }

  setupBookmarkShortcuts() {
    document.addEventListener('keydown', (e) => {
      // Ctrl+B - Bookmark current section
      if (e.ctrlKey && e.key === 'b') {
        e.preventDefault();
        const currentHeader = this.getCurrentHeader();
        if (currentHeader) {
          const btn = currentHeader.querySelector('.bookmark-header-btn');
          if (btn) btn.click();
        }
      }
    });
  }

  getCurrentHeader() {
    // Find currently visible header
    const headers = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
    const scrollPos = window.scrollY + 100;
    
    let current = null;
    headers.forEach(header => {
      if (header.offsetTop <= scrollPos) {
        current = header;
      }
    });
    
    return current;
  }

  announce(message) {
    // Use existing announcement system
    if (window.announceToScreenReader) {
      window.announceToScreenReader(message);
    }
  }
}
```

## 📱 Progressive Web App Support

```javascript
// PWA offline support for markdown
class OfflineMarkdownSupport {
  constructor() {
    this.init();
  }

  async init() {
    if ('serviceWorker' in navigator) {
      await this.registerServiceWorker();
      this.setupOfflineUI();
    }
  }

  async registerServiceWorker() {
    try {
      const registration = await navigator.serviceWorker.register('/sw.js');
      console.log('Service Worker registered:', registration);
    } catch (error) {
      console.error('Service Worker registration failed:', error);
    }
  }

  setupOfflineUI() {
    window.addEventListener('online', () => {
      this.updateConnectionStatus(true);
    });

    window.addEventListener('offline', () => {
      this.updateConnectionStatus(false);
    });
  }

  updateConnectionStatus(isOnline) {
    const indicator = document.getElementById('connection-indicator');
    if (!indicator) return;

    indicator.className = isOnline ? 'online' : 'offline';
    indicator.textContent = isOnline ? '🟢 מחובר' : '🔴 לא מחובר';
    indicator.setAttribute('aria-label', 
      isOnline ? 'מחובר לרשת' : 'עובד במצב לא מקוון'
    );
  }
}
```

---

*דוגמאות אלו מספקות בסיס מוצק למימוש מלא של תכונות נגישות ב-Markdown.*
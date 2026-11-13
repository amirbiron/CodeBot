(function () {
  const STATUS = {
    IDLE: 'idle',
    EMPTY: 'empty',
    LOADING: 'loading',
    READY: 'ready',
    ERROR: 'error',
  };

  // שניהם מגיעים מ-admonition-icons.js, שהוא המקור היחיד למטא-דאטה של סוגי
  // האלרט. אותה צורת קריאה בדיוק לשניהם: מפה חסרה מדרדרת לשם הסוג
  // (``|| type`` באתר השימוש) ולא שוברת את הרינדור.
  const MARKDOWN_DEFAULT_TITLES = (typeof window !== 'undefined' && window.ADMONITION_TITLES) || {};
  const ADMONITION_ICONS = (typeof window !== 'undefined' && window.ADMONITION_ICONS) || {};
  // ``::: details`` אינו אלרט ולכן אין לו ערך ב-``ADMONITION_TITLES``, אבל
  // תווית ברירת המחדל שלו מגיעה מאותו קובץ ומאותה סיבה — ראו
  // ``admonition-icons.js``.
  const DETAILS_DEFAULT_TITLE =
    (typeof window !== 'undefined' && window.DETAILS_DEFAULT_TITLE) || '';

  function slugifyHeadingId(rawText) {
    try {
      let slug = (rawText || '')
        .toString()
        .trim()
        .toLowerCase()
        .normalize('NFKD')
        .replace(/[\u200B-\u200D\uFEFF]/g, '')
        .replace(/\p{M}+/gu, '')
        .replace(/[^\p{L}\p{N}\s-]+/gu, '')
        .replace(/\s+/g, '-')
        .replace(/-{2,}/g, '-')
        .replace(/^-+|-+$/g, '');
      if (!slug) {
        slug = 'section';
      }
      return slug;
    } catch (_) {
      const fallback = (rawText || '')
        .toString()
        .trim()
        .toLowerCase()
        .replace(/\s+/g, '-')
        .replace(/[^a-z0-9-]/g, '');
      return fallback || 'section';
    }
  }

  function getFileExtension(name = '') {
    const parts = (name || '').trim().toLowerCase().split('.');
    if (parts.length < 2) {
      return '';
    }
    return parts.pop();
  }

  const isMarkdownLanguage = (value = '') => {
    const normalized = value.toString().trim().toLowerCase();
    return normalized === 'markdown' || normalized === 'md';
  };

  const isHtmlLanguage = (value = '') => {
    const normalized = value.toString().trim().toLowerCase();
    return normalized === 'html' || normalized === 'htm';
  };

  const isMarkdownExtension = (value = '') => {
    const ext = getFileExtension(value);
    return ext === 'md' || ext === 'markdown';
  };

  const isHtmlExtension = (value = '') => {
    const ext = getFileExtension(value);
    return ext === 'html' || ext === 'htm';
  };

  // ``[ ]`` / ``[x]`` של פריט משימה בתחילת שורה — אחרי סימן רשימה (``-``, ``*``, ``+``, ``1.``, ``1)``), גם בתוך
  // ציטוט. זו הצורה ש-markdown-it-task-lists מזהה: פריט רשימה שהטקסט שלו נפתח ב-``[ ] `` או ב-``[x] ``.
  // לא לאחד עם ``TASK_LINE_RE`` ב-``sticky-notes.js``: שם הדקדוק המצומצם של הפתק (רק ``-`` / ``*``, בלי ציטוט
  // ובלי רשימה ממוספרת), שחייב להיות זהה ל-``_TASK_RE`` ב-``sticky_notes_tasks.py``, שסופר לפיו את המשימות.
  const TASK_MARKER_RE = /^(\s*(?:>\s*)*(?:[-*+]|\d+[.)])\s+\[)([ xX])\]/;

  // המיקום (offset בטקסט) של התו שבתוך הסוגריים של פריט המשימה בשורה ``line`` (0-based), והאם הוא מסומן;
  // ``null`` כשהשורה אינה פריט משימה.
  function locateTaskMarker(content, line) {
    const lines = String(content || '').split('\n');
    if (!Number.isInteger(line) || line < 0 || line >= lines.length) return null;
    const match = TASK_MARKER_RE.exec(lines[line]);
    if (!match) return null;
    let offset = 0;
    for (let i = 0; i < line; i += 1) offset += lines[i].length + 1;
    return { offset: offset + match[1].length, checked: match[2] !== ' ' };
  }

  function resolvePreviewMode(language, fileName) {
    const lang = (language || '').trim().toLowerCase();
    if (lang === 'markdown' || lang === 'md') {
      return 'markdown';
    }
    if (lang === 'html' || lang === 'htm') {
      return 'html';
    }
    const ext = getFileExtension(fileName || '');
    if (ext === 'md' || ext === 'markdown') {
      return 'markdown';
    }
    if (ext === 'html' || ext === 'htm') {
      return 'html';
    }
    return 'code';
  }

  const MarkdownLiveRenderer = (() => {
    // שלושה מופעים של markdown-it, באותם תוספים, ששונים בשלושה דברים בלבד:
    // - ``default`` — דפדפן הריפו וכרטיסי החיפוש בתיעוד: קישור ``¶`` ליד כל כותרת, וכל שש רמות הכותרות.
    // - ``livePreview`` — התצוגה החיה בעמודי העורך (``LivePreviewController``): בלי ``¶`` (אין לתצוגה כתובת
    //   לשתף, והסמן הופיע בנגיעה), ועם רמות הכותרות של תצוגת המסמך — בלי H5/H6. כותרת כזו נשארת כמו שנכתבה,
    //   ``##### טקסט``, כפסקה. המגבלה והסיבה לה — ב-``md-heading-level-plugin.js`` (``DOCUMENT_MAX_LEVEL``), שגם
    //   ``md_preview.html`` מתקין. ועם שורות המקור על כל בלוק (``md-source-lines-plugin.js``, שגם ``md_preview.html``
    //   מתקין): לפיהן לחיצה על צ'קבוקס משנה את השורה שלו בעורך, והגלילה בעורך ובתצוגה מסונכרנת
    //   (``live-preview-scroll-sync.js``).
    // - ``export`` — הייצוא ל-HTML מעוצב מהעורך הציבורי (``renderForExport``): כמו ``livePreview``, אבל בלי שורות
    //   המקור — אין בקובץ עורך לסנכרן איתו.
    // כל מופע נבנה פעם אחת, בבקשה הראשונה שלו, ונשמר רק אחרי שכל התוספים הותקנו בו: תוסף שזורק באמצע לא
    // משאיר מופע חלקי במטמון, והבקשה הבאה בונה אותו שוב.
    const RENDERER_VARIANTS = {
      default: { headingPermalinks: true, documentHeadingLevels: false, sourceLines: false },
      livePreview: { headingPermalinks: false, documentHeadingLevels: true, sourceLines: true },
      export: { headingPermalinks: false, documentHeadingLevels: true, sourceLines: false },
    };
    const renderers = new Map();
    const containerTypes = [
      'details',
      'note',
      'tip',
      'warning',
      'important',
      'danger',
      'info',
      'success',
      'question',
      'example',
      'quote',
      'experimental',
      'deprecated',
      'todo',
      'abstract',
    ];

    function ensureRenderer(variant = 'default') {
      const config = RENDERER_VARIANTS[variant];
      if (!config) {
        throw new Error(`unknown_markdown_renderer_variant: ${variant}`);
      }
      const cached = renderers.get(variant);
      if (cached) {
        return cached;
      }
      if (typeof window === 'undefined' || typeof window.markdownit !== 'function') {
        return null;
      }
      const md = window.markdownit({
        breaks: true,
        linkify: true,
        typographer: true,
        html: false,
        highlight: function (str, lang) {
          return window.SafeHighlight ? window.SafeHighlight.markdownItHighlight(str, lang) : '';
        },
      });
      const defaultInlineCode = md.renderer.rules.code_inline;
      const escapeHtml = (str) => {
        if (md.utils && typeof md.utils.escapeHtml === 'function') {
          return md.utils.escapeHtml(str);
        }
        return (str || '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      };
      md.renderer.rules.code_inline = (tokens, idx, options, env, slf) => {
        try {
          const content = tokens[idx] && typeof tokens[idx].content === 'string' ? tokens[idx].content : '';
          const escaped = escapeHtml(content);
          return `<code class="inline-code">${escaped}</code>`;
        } catch (_) {
          return defaultInlineCode ? defaultInlineCode(tokens, idx, options, env, slf) : '';
        }
      };
      // תמיכה בהדגשת "מארקר" בתחביר Markdown: ==טקסט== -> <mark>טקסט</mark>
      // התוסף חי ב-webapp/static/js/md-mark-plugin.js, ומשותף עם md_preview.html.
      // **בכוונה בלי try/catch:** קודם הוא היה מוטמע כאן, עטוף ב-catch שבלע הכול,
      // ולכן תוסף שלא נטען נכשל בשקט. אם הקובץ לא נטען, עדיף שזה ייראה.
      //
      // כאן אין צורך בבדיקה על ``md.use`` (בניגוד ל-md_preview.html): ``ensureRenderer``
      // חוזר null עוד קודם אם ``window.markdownit`` אינו פונקציה, ולכן ``md`` כאן הוא
      // תמיד מופע אמיתי של markdown-it ולא אובייקט גיבוי.
      if (window.MdMarkPlugin) md.use(window.MdMarkPlugin);
      // נוסחאות: ``$...$`` ו-``$$...$$`` מזוהות בתוך הפענוח ומרונדרות ב-KaTeX (מהבאנדל) משם.
      // התוסף חי ב-webapp/static/js/md-math-plugin.js, ומשותף עם md_preview.html. קודם
      // ``renderMathInElement`` רץ ב-``enhance`` על ה-HTML המוכן — ראו את ההסבר בראש התוסף.
      if (window.MdMathPlugin) md.use(window.MdMathPlugin, { katex: window.katex });
      // קישור אוטומטי רק לכתובת עם פרוטוקול, ולא לשם קובץ כמו ``readme.md``. ההסבר בראש
      // webapp/static/js/md-linkify-plugin.js, שמשותף עם md_preview.html ועם repo-browser.js.
      if (window.MdLinkifyPlugin) {
        md.use(window.MdLinkifyPlugin);
      } else {
        console.warn('md-linkify-plugin.js לא נטען: שם קובץ כמו readme.md יוצג כקישור לאתר בתצוגה החיה');
      }
      // קישור שמוביל לעמוד נפתח בלשונית חדשה, ועוגן בתוך המסמך נשאר באותה לשונית — בשלושת הסוגים, כולל הייצוא.
      // הכלל וההסבר בראש webapp/static/js/md-link-target-plugin.js, שמשותף עם md_preview.html ועם repo-browser.js.
      if (window.MdLinkTargetPlugin) {
        md.use(window.MdLinkTargetPlugin);
      } else {
        console.warn('md-link-target-plugin.js לא נטען: קישור בתצוגה יחליף את העמוד במקום להיפתח בלשונית חדשה');
      }
      if (window.markdownitEmoji) {
        md.use(window.markdownitEmoji);
      }
      if (window.markdownitTaskLists) {
        md.use(window.markdownitTaskLists, { label: true, enabled: true });
      }
      // הפסקה שכותרת כזו הופכת אליה מסומנת, ונשארת יעד לעוגן מפורש (``ANCHOR_TARGETS`` ב-``md-anchors.js``) — ולכן
      // החילוץ לא צריך לדעת אם התוסף הותקן.
      if (config.documentHeadingLevels) {
        if (window.MdHeadingLevel) {
          md.use(window.MdHeadingLevel.plugin, { maxLevel: window.MdHeadingLevel.DOCUMENT_MAX_LEVEL });
        } else {
          console.warn('md-heading-level-plugin.js לא נטען: H5/H6 מרונדרות ככותרות בתצוגה החיה');
        }
      }
      if (window.markdownitAnchor) {
        const anchorOptions = config.headingPermalinks
          ? { permalink: true, permalinkSymbol: '¶', slugify: slugifyHeadingId }
          : { slugify: slugifyHeadingId };
        try {
          md.use(window.markdownitAnchor, anchorOptions);
        } catch (_) {
          try {
            md.use(window.markdownitAnchor, { slugify: slugifyHeadingId });
          } catch (err) {
            console.warn('markdown-it-anchor failed', err);
          }
        }
      }
      if (window.markdownitFootnote) {
        md.use(window.markdownitFootnote);
      }
      if (window.markdownitAdmonition) {
        try {
          md.use(window.markdownitAdmonition, { types: containerTypes.filter((t) => t !== 'details') });
        } catch (err) {
          console.warn('markdown-it-admonition failed', err);
        }
      }
      if (window.markdownitContainer) {
        const containerPlugin = window.markdownitContainer;
        try {
          md.use(containerPlugin, 'details', {
            validate(params) {
              return /^details\b/i.test((params || '').trim());
            },
            // ``slf.renderAttrs`` — המאפיינים של הטוקן: בתצוגה החיה ``data-source-line`` של הקונטיינר
            // (``extraBlockTypes`` למטה). בווריאנט ``default`` אין לו מאפיינים, וה-HTML לא משתנה.
            render(tokens, idx, _options, _env, slf) {
              const info = (tokens[idx].info || '').trim();
              // ``\b\s*`` ולא ``\s+`` — **אותה צורה בדיוק** שכל שאר הסוגים
              // משתמשים בה מטה, וזו התאמה שנמדדה: עם ``\s+`` הכותרת של
              // ``::: details.x`` נבלעה וירדה לברירת המחדל, בעוד ש-
              // ``::: note.x`` כן קיבל כותרת. שני הצרכנים האחרים גוזרים את
              // הכותרת מ-``\b`` ולכן הציגו ``.x``; החריג היחיד היה כאן.
              const match = info.match(/^details\b\s*(.*)$/i);
              const title = (match && match[1] && match[1].trim()) || DETAILS_DEFAULT_TITLE;
              if (tokens[idx].nesting === 1) {
                return `<details class="markdown-details"${slf.renderAttrs(tokens[idx])}><summary class="markdown-summary">${md.utils.escapeHtml(
                  title
                )}</summary><div class="details-content">`;
              }
              return '</div></details>\n';
            },
          });
          containerTypes
            .filter((type) => type !== 'details')
            .forEach((type) => {
              const rxOpen = new RegExp(`^${type}\\b\\s*(.*)$`, 'i');
              md.use(containerPlugin, type, {
                validate(params) {
                  return rxOpen.test((params || '').trim());
                },
                render(tokens, idx, _options, _env, slf) {
                  const info = (tokens[idx].info || '').trim();
                  const match = info.match(rxOpen);
                  const title = (match && match[1] && match[1].trim()) || MARKDOWN_DEFAULT_TITLES[type] || type;
                  if (tokens[idx].nesting === 1) {
                    const icon = ADMONITION_ICONS[type] || '';
                    return `<div class="admonition admonition-${type}"${slf.renderAttrs(tokens[idx])}><div class="admonition-title">${icon}${md.utils.escapeHtml(
                      title
                    )}</div><div class="admonition-content">`;
                  }
                  return '</div></div>\n';
                },
              });
            });
        } catch (err) {
          console.warn('markdown-it-container failed', err);
        }
      }
      if (window.markdownitTocDoneRight) {
        try {
          md.use(window.markdownitTocDoneRight, { slugify: slugifyHeadingId });
        } catch (err) {
          console.warn('markdown-it-toc-done-right failed', err);
        }
      }
      // אחרון, כי התוסף עוטף כללי רינדור: תוסף שיותקן אחריו ויחליף כלל של אחד מסוגי הבלוקים ידרוס את העטיפה
      // (ההסבר בראש ``md-source-lines-plugin.js``). השורות מתורגמות לשורות בעורך דרך ``env.sourceLineMap``, שמגיע
      // מ-``renderMarkdownSource``. ``extraBlockTypes`` — גם הקונטיינרים (``::: note``, ``::: details``) והאלרטים
      // (``!!! note``) מסומנים, כדי שהגלילה המסונכרנת תדע איפה הכותרת שלהם; ``md_preview.html`` לא מסמן אותם.
      if (config.sourceLines) {
        if (window.MdSourceLines) {
          md.use(window.MdSourceLines.plugin, {
            extraBlockTypes: ['admonition_open'].concat(containerTypes.map((type) => `container_${type}_open`)),
          });
        } else {
          console.warn('md-source-lines-plugin.js לא נטען: בלי שורות מקור — לחיצה על צ\'קבוקס לא תשנה את העורך, ואין גלילה מסונכרנת');
        }
      }
      renderers.set(variant, md);
      return md;
    }

    // ``copyButtons: false`` — רק הדגשה. הכפתור הקטן בפינת ה-``pre`` (``.code-copy-btn``) הוא של דפדפן
    // הריפו ושל כרטיסי החיפוש בתיעוד; התצוגה החיה בונה במקומו את בלוק הקוד של המסמך (ראו ``enhance``).
    function highlightBlocks(root, options) {
      if (!root || typeof window === 'undefined') {
        return;
      }
      const copyButtons = !options || options.copyButtons !== false;
      root.querySelectorAll('pre code').forEach((block) => {
        try {
          const parent = block.closest('pre');
          // בדיקת עברית *לפני* hljs כדי שלא ישתנה ה-class
          if (window.RtlCode) {
            window.RtlCode.applyRtlIfHebrew(block);
          }
          // הדגשת תחביר בטוחה (מונע זיהוי שגוי כ-diff)
          if (window.SafeHighlight) {
            window.SafeHighlight.highlightBlock(block);
          }
          // קוד בתוך בלוק עברי משמאל לימין — *אחרי* ההדגשה, שבונה את הבלוק
          // מחדש. ראו wrapInnerFences ב-utils/rtl-code.js.
          // try משלו, ורחב בכוונה: אין כאן תקלה צפויה — חריגה היא באג, והיא
          // נרשמת במלואה. בלעדיו היא הייתה נתפסת למטה בתווית "hljs highlight
          // failed", ומבטלת את כפתור ההעתקה של הבלוק.
          if (window.RtlCode) {
            try {
              window.RtlCode.wrapInnerFences(block);
            } catch (err) {
              console.warn('wrapInnerFences failed', err);
            }
          }
          if (parent && copyButtons) {
            parent.style.position = 'relative';

            // הוספת כפתור העתקה אם לא קיים
            if (!parent.querySelector('.code-copy-btn')) {
              const copyBtn = document.createElement('button');
              copyBtn.className = 'code-copy-btn';
              copyBtn.innerHTML = '<i class="bi bi-clipboard"></i>';
              copyBtn.title = 'העתק קוד';
              copyBtn.setAttribute('aria-label', 'העתק קוד');
              copyBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                const code = block.textContent || '';
                try {
                  await navigator.clipboard.writeText(code);
                  copyBtn.innerHTML = '<i class="bi bi-check2"></i>';
                  copyBtn.classList.add('copied');
                  setTimeout(() => {
                    copyBtn.innerHTML = '<i class="bi bi-clipboard"></i>';
                    copyBtn.classList.remove('copied');
                  }, 2000);
                } catch (err) {
                  console.warn('Copy failed', err);
                }
              });
              parent.appendChild(copyBtn);
            }
          }
        } catch (err) {
          console.warn('hljs highlight failed', err);
        }
      });
    }

    // ``interactive`` — הצ'קבוקסים פעילים: רק בתצוגה החיה, שבה לחיצה משנה את הטקסט בעורך (ראו
    // ``LivePreviewController.handleTaskToggle``). בדפדפן הריפו ובכרטיסי החיפוש בתיעוד אין טקסט לשנות, והם
    // נשארים לקריאה בלבד.
    function enhanceTaskLists(root, interactive) {
      if (!root) {
        return;
      }
      root.querySelectorAll('input[type="checkbox"]').forEach((input) => {
        if (!interactive) input.setAttribute('disabled', 'true');
        input.setAttribute('role', 'checkbox');
      });
    }

    function lazyLoadImages(root) {
      if (!root) {
        return;
      }
      root.querySelectorAll('img').forEach((img) => {
        if (!img.hasAttribute('loading')) {
          img.loading = 'lazy';
        }
        img.decoding = 'async';
        img.referrerPolicy = img.referrerPolicy || 'no-referrer';
      });
    }

    // ערכת ה-Mermaid לפי הערכה של העמוד (כמו ב-md_preview.html): בהירה בערכות בהירות, ובערכה מותאמת או משותפת —
    // לפי הבהירות של ``--bg-primary``.
    function pageMermaidTheme() {
      const currentTheme = (document.documentElement && document.documentElement.getAttribute('data-theme')) || 'dark';
      const knownLightThemes = ['light', 'classic', 'rose-pine-dawn'];
      let mermaidTheme = 'dark';
      if (knownLightThemes.includes(currentTheme)) {
        mermaidTheme = 'default';
      } else if (currentTheme === 'custom' || currentTheme.startsWith('shared:')) {
        // For custom/shared themes, check actual background color brightness
        const bgColor = getComputedStyle(document.documentElement).getPropertyValue('--bg-primary').trim();
        if (bgColor) {
          const hex = bgColor.replace('#', '');
          if (hex.length >= 6) {
            const r = parseInt(hex.substr(0, 2), 16);
            const g = parseInt(hex.substr(2, 2), 16);
            const b = parseInt(hex.substr(4, 2), 16);
            const brightness = (r * 299 + g * 587 + b * 114) / 1000;
            mermaidTheme = brightness > 128 ? 'default' : 'dark';
          }
        }
      }
      return mermaidTheme;
    }

    // **שני רינדורים יכולים לרוץ יחד** — התצוגה החיה, והייצוא ל-HTML מהעורך הציבורי (``renderForExport``), שמרנדר
    // לערכה אחרת. לכן שני דברים כאן משותפים לכל המודול ולא לרינדור אחד:
    // - **התור** (``mermaidQueue``): ``mermaid.initialize`` משנה הגדרה גלובלית, ו-``render`` שאחריו ממתין. בלי
    //   תור, רינדור שני היה מאתחל ערכה משלו בזמן שהראשון עוד מצייר, והתרשימים של הראשון היו יוצאים בערכה של השני.
    // - **המונה** (``mermaidPassCount``): עד נובמבר 2026 המזהה של כל SVG נבנה מ-``Date.now()`` וממונה שמתחיל מאפס
    //   בכל רינדור, ושני רינדורים באותה אלפית שנייה היו מקבלים אותם מזהים. ה-CSS שבתוך כל SVG מכוון למזהה שלו.
    let mermaidQueue = Promise.resolve();
    let mermaidPassCount = 0;

    // ``mermaidTheme`` — ערכה מפורשת (הייצוא, לפי ערכת הקובץ); בלעדיה — לפי העמוד.
    // ``isCurrent`` — האם הרינדור עדיין רלוונטי. התצוגה החיה מעבירה אותו: רינדור שרינדור חדש כבר החליף לא מצייר את
    // התרשימים שנשארו לו, וכך לא מעכב בתור את הרינדור החדש, ואת הייצוא, בעבודה שאיש לא יראה.
    function renderMermaid(root, mermaidTheme, isCurrent) {
      if (!root || typeof window === 'undefined' || typeof window.mermaid === 'undefined') {
        return Promise.resolve();
      }
      const blocks = root.querySelectorAll('code.language-mermaid, pre code.language-mermaid');
      if (!blocks.length) {
        return Promise.resolve();
      }
      const stillCurrent = typeof isCurrent === 'function' ? isCurrent : () => true;
      const run = mermaidQueue.then(() => renderMermaidBlocks(blocks, mermaidTheme || pageMermaidTheme(), stillCurrent));
      // התור ממשיך גם אחרי רינדור שנכשל: הכשל עצמו חוזר לקורא דרך ``run``, ורק השרשרת לא נעצרת בגללו.
      mermaidQueue = run.catch(() => {});
      return run;
    }

    async function renderMermaidBlocks(blocks, mermaidTheme, isCurrent) {
      if (!isCurrent()) return;
      try {
        // התצורה של האתר (רוחב הגלישה של התוויות, ``securityLevel``) — ``window.mermaidSiteConfig`` מהבאנדל,
        // ``webapp/static_build/mermaid-site-config.mjs``. אותה תצורה כמו בתצוגת המסמך.
        window.mermaid.initialize(window.mermaidSiteConfig(mermaidTheme));
      } catch (err) {
        console.warn('mermaid initialize failed', err);
      }
      mermaidPassCount += 1;
      const pass = mermaidPassCount;
      let counter = 0;
      for (const block of blocks) {
        if (!isCurrent()) return;
        const code = block.textContent || '';
        const parent = block.closest('pre') || block.parentElement;
        const wrapper = document.createElement('div');
        wrapper.className = 'mermaid-diagram';
        // שורות המקור של הבלוק (``md-source-lines-plugin.js``, על ה-``<code>``) עוברות לתרשים שמחליף אותו — בלעדיהן
        // לתרשים אין מקום בטבלת ההתאמה של הגלילה המסונכרנת.
        ['data-source-line', 'data-source-line-end'].forEach((name) => {
          if (block.hasAttribute(name)) wrapper.setAttribute(name, block.getAttribute(name));
        });
        if (parent && parent.parentNode) {
          parent.parentNode.replaceChild(wrapper, parent);
        } else if (parent) {
          parent.replaceWith(wrapper);
        } else {
          block.replaceWith(wrapper);
        }
        try {
          const { svg } = await window.mermaid.render(`mmd_live_${pass}_${counter++}`, code);
          wrapper.innerHTML = svg;
        } catch (err) {
          wrapper.innerHTML = '<div class="alert alert-warning">Mermaid render failed</div>';
          console.warn('mermaid render failed', err);
        }
      }
    }

    // ``options.documentCodeBlocks`` — בלוקי קוד של תצוגת המסמך (``md-code-blocks.js``): מסגרת, פס
    // כותרת עם שם השפה וכפתור העתקה. התצוגה החיה מבקשת אותם; דפדפן הריפו וכרטיסי החיפוש בתיעוד לא,
    // והעיצוב של הכפתור הקטן שלהם ב-``markdown-preview.css``. הבנייה אחרי ה-Mermaid, כמו בתצוגת המסמך:
    // בלוק ```mermaid כבר הוחלף בתרשים ולא נעטף במסגרת.
    // ``options.copyButtons: false`` — בלי שום כפתור העתקה, לא הקטן ולא זה שבפס הכותרת; ``options.mermaidTheme`` —
    // ערכת Mermaid מפורשת. שתיהן של הייצוא (``renderForExport``). ``options.isCurrent`` — של התצוגה החיה: רינדור שהוחלף
    // מפסיק לצייר תרשימים (``renderMermaid``).
    async function enhance(root, anchors, options) {
      const documentCodeBlocks = !!(options && options.documentCodeBlocks);
      const copyButtons = !(options && options.copyButtons === false);
      applyExplicitAnchors(root, anchors);
      highlightBlocks(root, { copyButtons: copyButtons && !documentCodeBlocks });
      enhanceTaskLists(root, !!(options && options.interactiveTasks));
      lazyLoadImages(root);
      await renderMermaid(root, options && options.mermaidTheme, options && options.isCurrent);
      if (documentCodeBlocks) {
        if (window.MdCodeBlocks) {
          window.MdCodeBlocks.enhance(root, { copyButton: copyButtons });
        } else {
          console.warn('live-preview: md-code-blocks.js לא נטען — בלוקי הקוד בלי מסגרת וכפתור העתקה');
        }
      }
    }

    // החלת עוגני ה-HTML שנשלפו מהמקור (`## סעיף <a id="x"></a>`). ה-renderer רץ עם
    // html:false ולכן התגית לא שורדת — ראו webapp/static/js/md-anchors.js.
    // העוגנים מועברים במפורש מהקורא (ולא דרך מצב מודולרי), כדי ששני רינדורים
    // עוקבים לא ידרסו זה את העוגנים של זה.
    function applyExplicitAnchors(root, anchors) {
      if (!root || !anchors || !anchors.length) {
        return;
      }
      try {
        if (typeof window !== 'undefined' && window.MdAnchors) {
          window.MdAnchors.applyExplicitAnchors(root, anchors);
        }
      } catch (_) {
        // best-effort — כשל בהחלת עוגנים לא אמור לשבור את התצוגה המקדימה
      }
    }

    // רינדור + שליפת העוגנים המפורשים. משמש גם את render() (שמחזיר HTML בלבד,
    // לשמירת תאימות עם קוראים קיימים) וגם את renderWithAnchors().
    function renderMarkdownSource(text, variant = 'default') {
      const md = ensureRenderer(variant);
      if (!md) {
        throw new Error('markdown_renderer_missing');
      }
      let source = text || '';
      let anchors = [];
      let sourceLineMap = null;
      try {
        if (typeof window !== 'undefined' && window.MdAnchors) {
          const extracted = window.MdAnchors.extractExplicitAnchors(source);
          source = extracted.source;
          anchors = extracted.anchors;
          sourceLineMap = extracted.lineMap || null;
        }
      } catch (_) {
        // אם השליפה נכשלה — ממשיכים עם המקור המקורי, ושורות הפענוח הן שורות המקור
      }
      return { html: md.render(source, { sourceLineMap }), anchors: anchors };
    }

    return {
      isSupported() {
        return !!ensureRenderer();
      },
      isMarkdownLanguage(value) {
        return isMarkdownLanguage(value);
      },
      isMarkdownFile(value) {
        return isMarkdownExtension(value);
      },
      // מחזיר HTML בלבד (חתימה קיימת). הכותרות מנוקות מתגיות העוגן, אך כדי גם
      // *להחיל* את העוגנים יש להשתמש ב-renderWithAnchors ולהעביר אותם ל-enhance.
      async render(text) {
        return renderMarkdownSource(text).html;
      },
      // מחזיר { html, anchors } — העוגנים מועברים לאחר מכן ל-enhance(root, anchors). ``options.variant`` — אחד
      // המפתחות של ``RENDERER_VARIANTS``; בלעדיו ``default``.
      async renderWithAnchors(text, options) {
        return renderMarkdownSource(text, (options && options.variant) || 'default');
      },
      // הייצוא ל-HTML מעוצב מהעורך הציבורי (``markdown-editor-export.js``): רינדור נפרד מהתצוגה החיה, באותו מנוע,
      // לתוך אלמנט שאינו בעמוד. לא העתקה של מה שמוצג — כי התצוגה יכולה להיות כבויה (ואז מוצג בה רק טקסט
      // הסבר), באמצע רינדור, או עם תרשימים בערכה של העמוד. מחזיר את האלמנט אחרי שכל התרשימים צוירו.
      // ``options.mermaidTheme`` — ערכת ה-Mermaid של ערכת הקובץ.
      async renderForExport(text, options) {
        const rendered = renderMarkdownSource(text, 'export');
        const box = document.createElement('div');
        box.innerHTML = rendered.html || '';
        await enhance(box, rendered.anchors, {
          documentCodeBlocks: true,
          copyButtons: false,
          interactiveTasks: false,
          mermaidTheme: options && options.mermaidTheme,
        });
        // הסימון של highlight.js ש"הבלוק כבר הודגש" — שייך לעמוד שמדגיש, ואין לו משמעות בקובץ.
        box.querySelectorAll('[data-highlighted]').forEach((el) => el.removeAttribute('data-highlighted'));
        return box;
      },
      enhance,
    };
  })();

  if (typeof window !== 'undefined') {
    window.MarkdownLiveRenderer = MarkdownLiveRenderer;
  }

  class LivePreviewController {
    constructor(root) {
      this.root = root;
      this.toggleBtn = root ? root.querySelector('[data-action="toggle-live-preview"]') : null;
      this.shortcutHint = root ? root.querySelector('.split-toolbar-hint') : null;
      this.textarea = document.querySelector('textarea[name="code"]');
      this.languageSelect = document.getElementById('languageSelect');
      this.fileNameInput = document.querySelector('input[name="file_name"]');
      this.previewContent = root ? root.querySelector('[data-preview-content]') : null;
      this.previewCanvas = root ? root.querySelector('[data-preview-canvas]') : null;
      this.previewMeta = root ? root.querySelector('[data-preview-meta]') : null;
      this.statusEl = root ? root.querySelector('[data-preview-status]') : null;
      // אפשרויות לעמוד שאין בו שם קובץ ושפה, כמו העורך הציבורי (/markdown-editor). עמודי העריכה
      // וההעלאה לא מציבים אף אחת מהן, ובהם הכול נשאר כמו שהיה.
      // - data-preview-mode="markdown": התצוגה תמיד במצב Markdown. בלעדיה המצב נקבע לפי השפה
      //   ושם הקובץ, ובעמוד בלי השדות האלה התצוגה לא הייתה זמינה בכלל.
      // - data-preview-autostart: התצוגה דלוקה מההתחלה, בלי לחיצה על הכפתור.
      // - data-preview-client-only: רינדור בדפדפן בלבד. בלעדיה, כשהרינדור בדפדפן נכשל, הבקר פונה
      //   ל-/api/preview/live, שדורש התחברות; בעמוד ציבורי הפנייה הזו רק הייתה נכשלת.
      const fixedMode = root ? root.getAttribute('data-preview-mode') : '';
      this.options = {
        fixedMode: fixedMode === 'markdown' ? 'markdown' : '',
        autostart: !!(root && root.hasAttribute('data-preview-autostart')),
        clientOnly: !!(root && root.hasAttribute('data-preview-client-only')),
      };
      this.styleEl = null;
      this.abortController = null;
      // הגלילה המסונכרנת בין העורך לתצוגה (``live-preview-scroll-sync.js``) — נבנית ב-``init``.
      this.scrollSync = null;
      this.state = {
        enabled: false,
        layoutPanel: 'editor',
        debounceTimer: null,
        lastRenderedHash: null,
        inflightHash: null,
        previewAllowed: false,
        // הטקסט שממנו רונדרו הצ'קבוקסים שבתצוגה עכשיו — המיפוי שלהם לשורות (data-source-line) נכון רק לו.
        taskSourceContent: null,
        // עולה בכל פעם שהתוכן בתצוגה מוחלף (``invalidateRenderedContent``).
        renderGeneration: 0,
      };
      this.init();
    }

    init() {
      if (!this.root || !this.toggleBtn || !this.textarea || !this.previewContent || !this.previewCanvas) {
        return;
      }
      this.root.classList.remove('is-active');
      this.syncToggleButton(false);

      this.toggleBtn.addEventListener('click', () => this.toggle());
      this.previewCanvas.addEventListener('change', (event) => this.handleTaskToggle(event));
      // הדבקה שהחליפה את כל המסמך (EditorManager.getFullPasteExtension): העורך חוזר להתחלה, וגם התצוגה. הרינדור
      // הבא מחליף את התוכן ואינו נוגע בגלילה, ולכן התצוגה נשארת בראש המסמך החדש.
      this.textarea.addEventListener('editor:document-replaced', () => {
        this.previewCanvas.scrollTop = 0;
      });
      document.addEventListener('keydown', (event) => {
        const key = (event.key || '').toLowerCase();
        if (key === 'enter' && event.shiftKey && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          this.toggle();
        }
      });
      this.textarea.addEventListener('input', () => {
        if (this.state.enabled) {
          this.scheduleUpdate();
        } else {
          this.setStatus(STATUS.IDLE);
        }
      });
      if (this.languageSelect) {
        this.languageSelect.addEventListener('change', () => {
          if (this.state.enabled) {
            this.scheduleUpdate();
          }
          this.updatePreviewAvailability();
        });
      }
      if (this.fileNameInput) {
        ['input', 'change', 'blur'].forEach((evt) => {
          this.fileNameInput.addEventListener(evt, () => {
            this.updatePreviewAvailability();
            if (this.state.enabled) {
              this.scheduleUpdate(true);
            }
          });
        });
      }
      this.setupScrollSync();
      this.setupTabs();
      this.updatePreviewAvailability({ silentDisable: true });
      this.setStatus(STATUS.IDLE);
      if (this.options.autostart && this.state.previewAllowed) {
        this.enablePreview();
        this.scheduleUpdate(true);
      }
    }

    toggle() {
      const nextState = !this.state.enabled;
      if (nextState && !this.isPreviewEligible()) {
        this.disablePreview('Live Preview זמין רק לקבצי Markdown/HTML');
        return;
      }
      if (nextState) {
        this.enablePreview();
        this.scheduleUpdate(true);
        return;
      }
      this.disablePreview('תצוגה חיה כבויה');
    }

    scheduleUpdate(immediate = false) {
      if (!this.state.enabled) {
        return;
      }
      if (this.state.debounceTimer) {
        clearTimeout(this.state.debounceTimer);
      }
      if (immediate) {
        this.fetchPreview();
        return;
      }
      this.state.debounceTimer = setTimeout(() => this.fetchPreview(), 500);
    }

    cancelPending() {
      if (this.abortController) {
        this.abortController.abort();
        this.abortController = null;
      }
      if (this.state.debounceTimer) {
        clearTimeout(this.state.debounceTimer);
        this.state.debounceTimer = null;
      }
      this.state.inflightHash = null;
    }

    async fetchPreview() {
      if (!this.textarea) {
        return;
      }
      const payload = {
        content: this.textarea.value || '',
        language: this.languageSelect ? this.languageSelect.value : '',
        file_name: this.fileNameInput ? this.fileNameInput.value : '',
      };
      payload.mode = this.options.fixedMode || resolvePreviewMode(payload.language, payload.file_name);
      const payloadHash = JSON.stringify(payload);
      this.cancelPending();
      if (
        payloadHash === this.state.lastRenderedHash ||
        payloadHash === this.state.inflightHash
      ) {
        return;
      }
      const preferClientMarkdown = payload.mode === 'markdown' && MarkdownLiveRenderer.isSupported();
      if (preferClientMarkdown) {
        try {
          await this.renderClientMarkdown(payload, payloadHash);
          return;
        } catch (err) {
          if (this.options.clientOnly) {
            console.warn('Client Markdown preview failed (client-only page, no server fallback)', err);
            this.setStatus(STATUS.ERROR, this.translateError('render_failed'));
            return;
          }
          console.warn('Falling back to server preview after client Markdown failure', err);
        }
      }
      if (this.options.clientOnly) {
        // בלי שרת אין מי שירנדר: במצב Markdown הגענו לכאן כי ספריית ה-Markdown לא נטענה, ובכל
        // מצב אחר אין רינדור בדפדפן בכלל. lastRenderedHash לא מתעדכן, ולכן ההקלדה הבאה תנסה שוב.
        const reason = payload.mode === 'markdown' ? 'markdown_renderer_missing' : 'render_failed';
        this.setStatus(STATUS.ERROR, this.translateError(reason));
        return;
      }
      this.state.inflightHash = payloadHash;
      this.abortController = new AbortController();
      this.setStatus(STATUS.LOADING);
      try {
        const resp = await fetch('/api/preview/live', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: this.abortController.signal,
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.ok) {
          const message = (data && data.error) || 'preview_failed';
          throw new Error(message);
        }
        this.renderPreview({ ...data, mode: data.mode || payload.mode });
        this.state.lastRenderedHash = payloadHash;
      } catch (err) {
        if (err.name === 'AbortError') {
          return;
        }
        console.warn('Live preview failed', err);
        this.setStatus(STATUS.ERROR, this.translateError(err.message));
      } finally {
        this.abortController = null;
        if (this.state.inflightHash === payloadHash) {
          this.state.inflightHash = null;
        }
      }
    }

    renderPreview(data) {
      if (!data) {
        this.setStatus(STATUS.ERROR, 'תגובה ריקה מהשרת');
        return;
      }
      const html = data.html || '';
      const presentation = data.presentation || 'fragment';
      // רינדור מהשרת: הצ'קבוקסים שלו אינם ממופים לשורות, ולחיצה עליהם לא כותבת לעורך — ומאותה סיבה אין בו גלילה
      // מסונכרנת.
      this.invalidateRenderedContent();
      const mode = data.mode || 'code';
      this.setMarkdownContext(mode === 'markdown' && presentation !== 'iframe');
      if (presentation === 'iframe') {
        const iframe = document.createElement('iframe');
        iframe.setAttribute('sandbox', '');
        iframe.setAttribute('aria-label', 'תצוגה מקדימה ל-HTML');
        iframe.srcdoc = html;
        this.previewCanvas.replaceChildren(iframe);
      } else {
        this.previewCanvas.innerHTML = html || '<p>אין תוכן להצגה.</p>';
      }
      const metaStyles = data.meta && Array.isArray(data.meta.styles) ? data.meta.styles : null;
      const styles = metaStyles ? metaStyles.join('\n') : '';
      if (styles) {
        if (!this.styleEl) {
          this.styleEl = document.createElement('style');
          this.styleEl.dataset.previewStyle = 'live';
          this.previewContent.appendChild(this.styleEl);
        }
        this.styleEl.textContent = styles;
      } else if (this.styleEl) {
        this.styleEl.textContent = '';
      }
      this.updateMeta({ ...data.meta, mode });
      this.setStatus(STATUS.READY);
    }

    async renderClientMarkdown(payload, payloadHash) {
      if (!this.previewCanvas) {
        return;
      }
      const content = payload.content || '';
      const trimmed = content.trim();
      if (!trimmed) {
        this.invalidateRenderedContent();
        this.setMarkdownContext(true);
        this.previewCanvas.innerHTML = '<p>אין תוכן להצגה.</p>';
        this.updateMeta({ language: 'markdown', mode: 'markdown', bytes: 0, characters: 0, duration_ms: 0 });
        this.setStatus(STATUS.EMPTY, 'אין טקסט להצגה.');
        this.state.lastRenderedHash = payloadHash;
        return;
      }
      const started = typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now();
      this.state.inflightHash = payloadHash;
      this.setStatus(STATUS.LOADING);
      try {
        const rendered = await MarkdownLiveRenderer.renderWithAnchors(content, { variant: 'livePreview' });
        const html = rendered.html;
        // לפני שהתוכן מוחלף: עד ``contentRendered`` שלמטה הבלוקים בתצוגה אינם של הרינדור שהגלילה המסונכרנת מכירה
        // (ההסבר ב-``attach`` שב-``live-preview-scroll-sync.js``). אם הרינדור נכשל באמצע, הסנכרון נשאר כבוי עד
        // הרינדור הבא שמצליח.
        const generation = this.invalidateRenderedContent();
        this.setMarkdownContext(true);
        this.previewCanvas.innerHTML = html || '<p>אין תוכן להצגה.</p>';
        if (this.styleEl) {
          this.styleEl.textContent = '';
        }
        await MarkdownLiveRenderer.enhance(this.previewCanvas, rendered.anchors, {
          documentCodeBlocks: true,
          interactiveTasks: true,
          isCurrent: () => generation === this.state.renderGeneration,
        });
        // בזמן ש-``enhance`` חיכה לתרשימים התחיל רינדור חדש, והתוכן בתצוגה כבר שלו: הוא זה שיודיע כשיסתיים.
        if (generation !== this.state.renderGeneration) return;
        this.state.taskSourceContent = content;
        // אחרי ``enhance``: התרשימים כבר במקומם, ולכן הגבהים שהגלילה המסונכרנת מודדת הם הסופיים.
        if (this.scrollSync) this.scrollSync.contentRendered(content.split('\n').length);
        const duration = typeof performance !== 'undefined' && typeof performance.now === 'function'
          ? Math.max(1, Math.round(performance.now() - started))
          : 0;
        const meta = {
          language: 'markdown',
          mode: 'markdown',
          bytes: this.bytesFromString(content),
          characters: content.length,
          duration_ms: duration,
        };
        this.updateMeta(meta);
        this.setStatus(STATUS.READY);
        this.state.lastRenderedHash = payloadHash;
      } finally {
        if (this.state.inflightHash === payloadHash) {
          this.state.inflightHash = null;
        }
      }
    }

    // לחיצה על צ'קבוקס של משימה בתצוגה משנה את ``[ ]`` / ``[x]`` בשורה שלה בעורך, והתצוגה מתרנדרת מהטקסט החדש —
    // הטקסט הוא מקור האמת, ובלי זה הסימון היה נמחק ברינדור הבא. המיפוי לשורה (data-source-line) נכון רק לטקסט
    // שממנו התצוגה רונדרה, ולכן לפני הכתיבה בודקים מול העורך עצמו, ברגע הלחיצה: הטקסט בו שווה לזה שרונדר,
    // והשורה עדיין משימה, במצב שהצ'קבוקס הציג. אחרת לא כותבים: הצ'קבוקס חוזר למצבו, והתצוגה מתרנדרת מחדש.
    // הכתיבה בלי פוקוס לעורך — בנייד, פוקוס היה פותח מקלדת.
    handleTaskToggle(event) {
      const input = event.target;
      if (!input || typeof input.matches !== 'function' || !input.matches('input.task-list-item-checkbox')) {
        return;
      }
      const item = input.closest('[data-source-line]');
      const line = item ? Number(item.getAttribute('data-source-line')) : NaN;
      const manager = window.editorManager;
      const current = manager && typeof manager.getEditorContent === 'function'
        ? manager.getEditorContent()
        : (this.textarea.value || '');
      const target = current === this.state.taskSourceContent ? locateTaskMarker(current, line) : null;
      if (!target || target.checked === input.checked) {
        input.checked = !input.checked;
        this.scheduleUpdate(true);
        return;
      }
      const mark = input.checked ? 'x' : ' ';
      let written = false;
      if (manager && typeof manager.insertTextAtRange === 'function') {
        written = manager.insertTextAtRange(mark, target.offset, target.offset + 1, { focus: false });
      } else {
        this.textarea.setRangeText(mark, target.offset, target.offset + 1, 'preserve');
        this.textarea.dispatchEvent(new Event('input', { bubbles: true }));
        written = true;
      }
      if (!written) {
        console.warn('live-preview: the task checkbox could not be written to the editor');
        input.checked = !input.checked;
        return;
      }
      // השינוי הוא תו אחד בתוך השורה, ולכן המיפוי של כל הצ'קבוקסים נשאר נכון גם לטקסט החדש — ולחיצה נוספת
      // לפני שהתצוגה מתרנדרת מחדש לא תיחסם.
      this.state.taskSourceContent = current.slice(0, target.offset) + mark + current.slice(target.offset + 1);
    }

    // במצב Markdown ה-canvas מקבל את ``id="md-content"`` של תצוגת המסמך, ולכן הצבעים של המסמך
    // (``md-content-colors.css``) חלים עליו כמו שהם; והמכל מקבל ``data-mode``, שבו ``split-view.css``
    // צובע אותו בנייר של המסמך. **אין כאן ``data-theme`` על המכל, בכוונה.** עד אוקטובר 2026 הוצב שם
    // ``data-theme="dark"``, וזה הכניס לתצוגה את כללי הטקסט של הערכות הכהות ב-``dark-mode.css``
    // (כותרות, פסקאות, קישורים) עם צבעי הטקסט של העמוד: ב-Classic וב-Ocean — לבן. מזה נולד הרקע הכהה
    // הקבוע של התצוגה החיה. בלי התווית, הטקסט בתצוגה יורש את צבע הנייר, כמו במסמך.
    setMarkdownContext(isMarkdown) {
      if (!this.previewCanvas) {
        return;
      }
      if (isMarkdown) {
        this.previewCanvas.setAttribute('id', 'md-content');
        this.previewCanvas.dataset.mode = 'markdown';
        if (this.previewContent) {
          this.previewContent.dataset.mode = 'markdown';
        }
      } else {
        if (this.previewCanvas.id === 'md-content') {
          this.previewCanvas.removeAttribute('id');
        }
        this.previewCanvas.removeAttribute('data-mode');
        if (this.previewContent) {
          this.previewContent.removeAttribute('data-mode');
        }
      }
    }

    bytesFromString(value) {
      try {
        return new TextEncoder().encode(value || '').length;
      } catch (_) {
        return (value || '').length;
      }
    }

    updateMeta(meta = {}) {
      if (!this.previewMeta) return;
      const language = meta.language || '';
      const duration = typeof meta.duration_ms === 'number' ? `${meta.duration_ms}ms` : '';
      // המימוש הקודם חילק ב-1024 פעם אחת והציג תמיד KB, ולכן קובץ של 582
      // בתים הופיע כ-"0.6KB" ושל 3.5 מגה כ-"3584KB".
      const size = typeof meta.bytes === 'number' ? window.SizeFormat.formatFileSize(meta.bytes) : '';
      this.previewMeta.textContent = [language, size, duration].filter(Boolean).join(' • ');
    }

    translateError(code) {
      switch (code) {
        case 'missing_content':
        case 'empty_content':
          return 'אין טקסט להצגה.';
        case 'content_too_large':
          return 'התוכן גדול מדי לתצוגה חיה.';
        case 'markdown_renderer_missing':
          return 'ספריית Markdown טרם נטענה.';
        case 'render_failed':
        default:
          return 'שגיאה ברינדור התצוגה.';
      }
    }

    setStatus(state, message) {
      if (!this.previewContent || !this.statusEl) {
        return;
      }
      this.previewContent.classList.toggle('is-loading', state === STATUS.LOADING);
      this.statusEl.textContent = message || this.defaultMessage(state);
      this.statusEl.dataset.state = state;
    }

    defaultMessage(state) {
      switch (state) {
        case STATUS.LOADING:
          return 'מרענן תצוגה...';
        case STATUS.ERROR:
          return 'שגיאה ברענון התצוגה.';
        case STATUS.READY:
          return 'התצוגה מעודכנת.';
        case STATUS.EMPTY:
          return 'אין טקסט להצגה.';
        case STATUS.IDLE:
        default:
          return 'הפעל את Live Preview כדי לראות עדכון בזמן אמת.';
      }
    }

    // כל מסלול שמחליף את התוכן בתצוגה קורא לזה לפני ההחלפה: מה שהיה מוצג, והמיפוי של הצ'קבוקסים ושל הגלילה המסונכרנת
    // אליו, כבר לא בתוקף. מחזיר את מספר הרינדור החדש. רינדור בדפדפן שחיכה לתרשימים (``enhance``) בודק אותו אחרי ה-
    // ``await``: אם בינתיים התחיל רינדור אחר — הקלדה בזמן שתרשים מצויר — התוכן בתצוגה כבר של האחר, והרינדור הישן לא
    // שומר את התוצאות שלו. בלי זה, רינדור ישן שהסתיים אחרון הדליק את הגלילה המסונכרנת עם מספר השורות שלו, והחזיר
    // לצ'קבוקסים טקסט שאינו מה שמוצג.
    invalidateRenderedContent() {
      this.state.renderGeneration += 1;
      this.state.taskSourceContent = null;
      if (this.scrollSync) this.scrollSync.contentCleared();
      return this.state.renderGeneration;
    }

    // גלילה בעורך מזיזה את התצוגה לאותו מקום בטקסט, וגלילה בתצוגה מזיזה את העורך — ההסבר בראש
    // ``live-preview-scroll-sync.js``. רק כש-CodeMirror הוא העורך הפעיל: בעורך הפשוט אין סנכרון (החלטת המשתמש).
    // ``renderClientMarkdown`` מודיע על כל רינדור, וכל מסלול אחר — רינדור מהשרת, טקסט ריק, תצוגה כבויה — מודיע
    // שבתצוגה אין תוכן מסומן.
    setupScrollSync() {
      const editorPanel = this.root.querySelector('.split-panel--editor');
      const previewPanel = this.root.querySelector('.split-panel--preview');
      if (!editorPanel || !previewPanel) return;
      if (!window.LivePreviewScrollSync) {
        console.warn('live-preview: live-preview-scroll-sync.js לא נטען — אין גלילה מסונכרנת בין העורך לתצוגה');
        return;
      }
      this.scrollSync = window.LivePreviewScrollSync.attach({
        editorPanel,
        previewPanel,
        canvas: this.previewCanvas,
        getEditorView: () => {
          const manager = window.editorManager;
          return manager && manager.currentEditor === 'codemirror' && manager.cmInstance ? manager.cmInstance : null;
        },
      });
    }

    setupTabs() {
      const tabs = Array.from(this.root.querySelectorAll('[data-panel-target]'));
      if (!tabs.length) return;
      tabs.forEach((btn) => {
        btn.addEventListener('click', () => {
          const target = btn.dataset.panelTarget || 'editor';
          this.state.layoutPanel = target;
          this.root.dataset.activePanel = target;
          tabs.forEach((el) => {
            el.setAttribute('aria-selected', el === btn ? 'true' : 'false');
          });
        });
      });
    }

    isPreviewEligible() {
      if (this.options.fixedMode) {
        return true;
      }
      const language = this.languageSelect ? this.languageSelect.value : '';
      const fileName = this.fileNameInput ? this.fileNameInput.value : '';
      return (
        isMarkdownLanguage(language) ||
        isHtmlLanguage(language) ||
        isMarkdownExtension(fileName) ||
        isHtmlExtension(fileName)
      );
    }

    updatePreviewAvailability(options = {}) {
      const allowed = this.isPreviewEligible();
      this.state.previewAllowed = allowed;
      this.root.classList.toggle('preview-enabled', allowed);
      if (this.toggleBtn) {
        this.toggleBtn.hidden = !allowed;
        this.toggleBtn.tabIndex = allowed ? 0 : -1;
        this.toggleBtn.setAttribute('aria-disabled', allowed ? 'false' : 'true');
      }
      if (this.shortcutHint) {
        this.shortcutHint.hidden = !allowed;
      }
      if (!allowed && this.state.enabled) {
        this.disablePreview(options.silentDisable ? undefined : 'Live Preview זמין רק לקבצי Markdown/HTML');
      }
    }

    enablePreview() {
      this.state.enabled = true;
      this.syncToggleButton(true);
      this.root.classList.add('is-active');
    }

    // מצב הכפתור. ברירת המחדל: כיתוב קבוע ו-``aria-pressed``. כפתור עם ``data-label-active`` (העורך הציבורי)
    // מחליף כיתוב ואייקון — ``data-label-inactive`` / ``data-label-active`` ו-``data-icon-inactive`` /
    // ``data-icon-active`` — ובלי ``aria-pressed``: הכיתוב שלו אומר מה הלחיצה הבאה תעשה ("הסתר תצוגה"), וקורא מסך היה
    // מקריא לצדו "לחוץ". המראה של מצב דלוק — ``.split-view.is-active .split-toggle`` ב-``split-view.css``.
    syncToggleButton(active) {
      const btn = this.toggleBtn;
      if (!btn) return;
      const activeLabel = btn.getAttribute('data-label-active');
      if (!activeLabel) {
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        return;
      }
      btn.removeAttribute('aria-pressed');
      const text = btn.querySelector('.split-toggle__text');
      if (text) text.textContent = active ? activeLabel : (btn.getAttribute('data-label-inactive') || '');
      const icon = btn.querySelector('i');
      const iconActive = btn.getAttribute('data-icon-active');
      const iconInactive = btn.getAttribute('data-icon-inactive');
      if (icon && iconActive && iconInactive) {
        icon.classList.toggle(iconActive, active);
        icon.classList.toggle(iconInactive, !active);
      }
    }

    disablePreview(message) {
      this.state.enabled = false;
      this.cancelPending();
      this.state.lastRenderedHash = null;
      this.state.inflightHash = null;
      this.invalidateRenderedContent();
      this.syncToggleButton(false);
      this.root.classList.remove('is-active');
      this.root.dataset.activePanel = 'editor';
      const tabs = this.root.querySelectorAll('[data-panel-target]');
      if (tabs && tabs.length) {
        tabs.forEach((el) => {
          const target = el.dataset.panelTarget || 'editor';
          el.setAttribute('aria-selected', target === 'editor' ? 'true' : 'false');
        });
      }
      this.setStatus(STATUS.IDLE, message || this.defaultMessage(STATUS.IDLE));
      if (this.previewCanvas) {
        this.previewCanvas.innerHTML = '<div class="split-preview-placeholder"><p>תצוגה חיה תופיע כאן</p><small>הפעל את Live Preview כדי לרענן בזמן אמת</small></div>';
      }
      if (this.previewMeta) {
        this.previewMeta.textContent = '';
      }
      this.setMarkdownContext(false);
      if (this.styleEl) {
        this.styleEl.textContent = '';
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const root = document.getElementById('livePreviewRoot');
    if (root) {
      window.livePreviewController = new LivePreviewController(root);
    }
  });
})();

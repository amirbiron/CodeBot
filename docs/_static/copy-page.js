(function () {
  const ARTICLE_SELECTOR = '.wy-nav-content .document';
  const ACTIVE_CLASS = 'doc-copy-page__button--active';
  const ERROR_CLASS = 'doc-copy-page__status--error';
  const RESET_DELAY_MS = 2800;
  const BUTTON_TEXT = {
    idle: 'העתק תוכן הדף',
    busy: 'מעתיק...',
    success: 'הועתק ✔',
  };
  const STATUS_TEXT = {
    success: 'הטקסט הועתק ללוח',
    error: 'שגיאה בהעתקה',
  };
  const CLEANUP_SELECTORS = [
    '.doc-copy-page',
    '.wy-breadcrumbs',
    '.rst-breadcrumbs-buttons',
    'script',
    'style',
    '.headerlink',
    '.toc-backref',
    '.viewcode-block',
  ];
  const MARKDOWN_NEWLINE_REGEX = /\n{3,}/g;

  // ── תרשימי Mermaid ─────────────────────────────────────────────────────────
  // Sphinx מייצר <pre class="mermaid"> שבתוכו קוד המקור של התרשים, אבל ספריית
  // mermaid מוחקת את הטקסט הזה מה-DOM בזמן הרינדור ושמה במקומו <svg>.
  // הכפתור רץ רק בלחיצת המשתמש – הרבה אחרי הרינדור – ולכן בלי לכידה מוקדמת
  // היינו מעתיקים את הטקסט שבתוך ה-SVG (שמות התיבות מודבקים) במקום את הקוד.
  // לכן שומרים את המקור ברגע שה-DOM מוכן, לפני ש-mermaid מספיק לרוץ.
  const MERMAID_SELECTOR = 'pre.mermaid, div.mermaid, code.mermaid';
  const MERMAID_ID_ATTR = 'data-copy-page-mermaid-id';
  const mermaidSources = new Map();
  let mermaidCounter = 0;

  /**
   * מסיר הזחה משותפת מבלוק קוד.
   * Sphinx מזיח רק את השורה הראשונה של תרשים Mermaid (למשל 8 רווחים לפני
   * "graph TD" מול 2 רווחים בשאר השורות), ולכן חישוב מינימום על כל השורות
   * היה משאיר את השורה הראשונה עקומה. במקרה כזה מיישרים אותה בנפרד ומחשבים
   * את ההזחה המשותפת רק משאר השורות – כך שההיררכיה הפנימית נשמרת.
   */
  const dedentCodeBlock = (raw) => {
    const text = (raw || '')
      .replace(/\u00a0/g, ' ')
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n')
      .replace(/\t/g, '  ');
    const lines = text.split('\n');
    while (lines.length && !lines[0].trim()) {
      lines.shift();
    }
    while (lines.length && !lines[lines.length - 1].trim()) {
      lines.pop();
    }
    if (!lines.length) {
      return '';
    }

    const leadingSpaces = (line) => {
      const match = line.match(/^[ ]*/);
      return match ? match[0].length : 0;
    };

    const firstIndent = leadingSpaces(lines[0]);
    let restIndent = null;
    for (let i = 1; i < lines.length; i += 1) {
      if (!lines[i].trim()) {
        continue;
      }
      const leading = leadingSpaces(lines[i]);
      restIndent = restIndent === null ? leading : Math.min(restIndent, leading);
    }

    if (restIndent === null) {
      return lines[0].trim();
    }

    if (firstIndent > restIndent) {
      // המקרה של Sphinx: השורה הראשונה מוזחת יותר מכל השאר.
      lines[0] = lines[0].replace(/^[ ]+/, '');
      if (restIndent > 0) {
        const pattern = new RegExp(`^[ ]{0,${restIndent}}`);
        for (let i = 1; i < lines.length; i += 1) {
          lines[i] = lines[i].replace(pattern, '');
        }
      }
      return lines.join('\n');
    }

    // הזחה אחידה: מסירים את המינימום מכל השורות ושומרים על ההיררכיה.
    const indent = Math.min(firstIndent, restIndent);
    if (indent > 0) {
      const pattern = new RegExp(`^[ ]{0,${indent}}`);
      for (let i = 0; i < lines.length; i += 1) {
        lines[i] = lines[i].replace(pattern, '');
      }
    }
    return lines.join('\n');
  };

  /**
   * בונה גדר (fence) שארוכה מכל רצף גרשיים שקיים בתוך הקוד עצמו,
   * כדי שבלוק שמכיל ``` (למשל דוגמת Markdown של תרשים) לא ייסגר באמצע.
   */
  const buildFence = (code) => {
    const matches = (code || '').match(/`{3,}/g) || [];
    let longest = 0;
    matches.forEach((match) => {
      if (match.length > longest) {
        longest = match.length;
      }
    });
    return '`'.repeat(Math.max(3, longest + 1));
  };

  const wrapInFence = (code, language) => {
    const body = (code || '').replace(/\u00a0/g, ' ').trimEnd();
    const fence = buildFence(body);
    return `\n\n${fence}${language || ''}\n${body}\n${fence}\n\n`;
  };

  const isMermaidRendered = (node) => {
    if (!node) {
      return false;
    }
    if (node.getAttribute && node.getAttribute('data-processed')) {
      return true;
    }
    return Boolean(node.querySelector && node.querySelector('svg'));
  };

  /**
   * שומר את קוד המקור של כל תרשים Mermaid בדף ומסמן את האלמנט במזהה.
   * המזהה נשמר כ-attribute ולכן שורד גם את ה-cloneNode ואת המעבר דרך
   * innerHTML אל Turndown. בטוח לקריאה חוזרת – לא דורס מקור שכבר נלכד.
   */
  const captureMermaidSources = (root) => {
    const scope = root || document;
    if (!scope || typeof scope.querySelectorAll !== 'function') {
      return;
    }
    scope.querySelectorAll(MERMAID_SELECTOR).forEach((node) => {
      if (node.getAttribute(MERMAID_ID_ATTR)) {
        return;
      }
      if (isMermaidRendered(node)) {
        // האלמנט כבר רונדר – אין ממה לשחזר, ועדיף לא לשמור את טקסט ה-SVG.
        return;
      }
      const source = dedentCodeBlock(node.textContent || '');
      if (!source) {
        return;
      }
      mermaidCounter += 1;
      const id = String(mermaidCounter);
      node.setAttribute(MERMAID_ID_ATTR, id);
      mermaidSources.set(id, source);
    });
  };

  const getMermaidSource = (node) => {
    if (!node) {
      return '';
    }
    const id =
      typeof node.getAttribute === 'function'
        ? node.getAttribute(MERMAID_ID_ATTR)
        : '';
    if (id && mermaidSources.has(id)) {
      return mermaidSources.get(id);
    }
    // נפילה בטוחה: קוראים מה-DOM רק אם התרשים עדיין לא הומר ל-SVG.
    if (isMermaidRendered(node)) {
      return '';
    }
    return dedentCodeBlock(node.textContent || '');
  };

  const createControls = () => {
    const container = document.createElement('div');
    container.className = 'doc-copy-page';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'doc-copy-page__button';
    button.setAttribute('aria-live', 'polite');
    button.setAttribute('data-copy-state', 'idle');
    button.textContent = BUTTON_TEXT.idle;

    const status = document.createElement('span');
    status.className = 'doc-copy-page__status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'assertive');

    container.appendChild(button);
    container.appendChild(status);
    return { container, button, status };
  };

  const copyTextToClipboard = async (text) => {
    if (!text) {
      throw new Error('missing text');
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    textarea.style.opacity = '0';
    textarea.setAttribute('readonly', 'readonly');
    document.body.appendChild(textarea);
    textarea.select();

    const success = document.execCommand('copy');
    document.body.removeChild(textarea);
    if (!success) {
      throw new Error('execCommand failed');
    }
  };

  const normalizeText = (text) =>
    text.replace(/\u00a0/g, ' ').replace(/\n{3,}/g, '\n\n').trim();

  const detectCodeLanguage = (node) => {
    if (!node) {
      return '';
    }
    if (node.dataset && node.dataset.lang) {
      return node.dataset.lang;
    }
    const dataLanguage =
      typeof node.getAttribute === 'function'
        ? node.getAttribute('data-language')
        : '';
    if (dataLanguage) {
      return dataLanguage;
    }
    const className = node.className || '';
    if (className) {
      const classList = className.split(/\s+/);
      for (const token of classList) {
        if (token.startsWith('language-')) {
          return token.replace('language-', '');
        }
        if (token.startsWith('highlight-')) {
          const value = token.replace('highlight-', '');
          if (value && value !== 'default' && value !== 'text') {
            return value;
          }
        }
      }
    }
    return detectCodeLanguage(node.parentElement);
  };

  const createMarkdownService = () => {
    if (typeof TurndownService !== 'function') {
      return null;
    }
    try {
      const service = new TurndownService({
        headingStyle: 'atx',
        codeBlockStyle: 'fenced',
        fence: '```',
        bulletListMarker: '-',
        hr: '---',
        emDelimiter: '*',
        strongDelimiter: '**',
        blankReplacement(_, node) {
          if (node && node.nodeName === 'BR') {
            return '  \n';
          }
          return '';
        },
      });

      if (
        typeof turndownPluginGfm !== 'undefined' &&
        typeof turndownPluginGfm.gfm === 'function'
      ) {
        service.use(turndownPluginGfm.gfm);
      }

      const inlineMarkdownFromNode = (node) => {
        if (!node) {
          return '';
        }
        const html = node.innerHTML || '';
        if (html.trim()) {
          try {
            const markdown = service.turndown(html).trim();
            if (markdown) {
              return markdown;
            }
          } catch (error) {
            /* noop */
          }
        }
        return (node.textContent || '').trim();
      };

      const ADMONITION_TYPES = new Set([
        'note',
        'warning',
        'tip',
        'important',
        'caution',
        'attention',
        'danger',
        'error',
        'hint',
        'seealso',
        'success',
        'info',
        'admonition',
      ]);

      // התאמה לפורמט ה-Markdown של הווב-אפ (containers עם :::).
      // מיפוי סוגים של Sphinx → סוגים שהווב-אפ יודע להציג בצורה עקבית.
      const WEBAPP_ADMONITION_TYPE_ALIASES = {
        attention: 'warning',
        caution: 'warning',
        error: 'danger',
        hint: 'tip',
        seealso: 'info',
        admonition: 'info',
      };
      const WEBAPP_ADMONITION_TYPES = new Set([
        'note',
        'warning',
        'tip',
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
      ]);

      const detectAdmonitionType = (node) => {
        if (!node) {
          return 'note';
        }
        const tokens = node.classList
          ? Array.from(node.classList)
          : (node.className || '').split(/\s+/);
        for (const token of tokens) {
          if (!token || token === 'admonition') {
            continue;
          }
          if (ADMONITION_TYPES.has(token)) {
            return token;
          }
        }
        return tokens.find((token) => token && token !== 'admonition') || 'note';
      };

      const normalizeAdmonitionTypeForWebapp = (rawType) => {
        const normalized = (rawType || '').toString().trim().toLowerCase();
        if (!normalized) {
          return 'note';
        }
        const aliased = WEBAPP_ADMONITION_TYPE_ALIASES[normalized] || normalized;
        if (WEBAPP_ADMONITION_TYPES.has(aliased)) {
          return aliased;
        }
        return 'info';
      };

      const renderAdmonitionBlock = (node, fallbackContent) => {
        if (!node) {
          return fallbackContent;
        }
        const clone = node.cloneNode(true);
        clone
          .querySelectorAll('.admonition-title')
          .forEach((title) => title.remove());

        const innerHtml = clone.innerHTML || '';

        let bodyMarkdown = '';
        if (innerHtml.trim()) {
          try {
            bodyMarkdown = service.turndown(innerHtml).trim();
          } catch (error) {
            bodyMarkdown = '';
          }
        }
        if (!bodyMarkdown && fallbackContent) {
          bodyMarkdown = fallbackContent.trim();
        }

        const rawType = detectAdmonitionType(node);
        const type = normalizeAdmonitionTypeForWebapp(rawType);
        const normalizedBody = (bodyMarkdown || '')
          .replace(/\u00a0/g, ' ')
          .replace(/\r\n/g, '\n')
          .replace(/\n{3,}/g, '\n\n')
          .trim();

        // חשוב: לא מוסיפים כותרת אחרי הסוג כדי לשמור תאימות למימושים שונים בווב-אפ.
        // פורמט יעד:
        // ::: warning
        // תוכן...
        // :::
        return `\n\n::: ${type}\n${normalizedBody}\n:::\n\n`;
      };

      const formatTableCell = (cell) => {
        if (!cell) {
          return ' ';
        }
        const inline = inlineMarkdownFromNode(cell);
        if (!inline) {
          return ' ';
        }
        return inline
          .replace(/\u00a0/g, ' ')
          .replace(/\r?\n/g, '\n')
          .split('\n')
          .map((line) => line.trim())
          .filter((line, index, lines) => line || lines.length === 1)
          .join('<br />')
          .replace(/\|/g, '\\|');
      };

      const collectRowCells = (row) => {
        if (!row) {
          return [];
        }
        const cells = [];
        Array.from(row.cells || []).forEach((cell) => {
          const span = Number(cell.getAttribute('colspan') || 1);
          const repeats = Number.isNaN(span) || span < 1 ? 1 : span;
          const value = formatTableCell(cell);
          for (let i = 0; i < repeats; i += 1) {
            cells.push(value);
          }
        });
        return cells;
      };

      const renderDocutilsTable = (tableNode, fallbackContent) => {
        if (!tableNode || typeof tableNode.querySelector !== 'function') {
          return fallbackContent;
        }

        const headerRows = tableNode.tHead
          ? Array.from(tableNode.tHead.rows || [])
          : [];
        const bodyRows =
          tableNode.tBodies && tableNode.tBodies.length
            ? Array.from(tableNode.tBodies).reduce((acc, tbody) => {
                const rows = Array.from(tbody.rows || []);
                return acc.concat(rows);
              }, [])
            : Array.from(tableNode.rows || []).filter(
                (row) => !headerRows.includes(row)
              );

        let headers = headerRows.length ? collectRowCells(headerRows[0]) : [];
        let dataRows = bodyRows;

        if (!headers.length && dataRows.length) {
          headers = collectRowCells(dataRows[0]);
          dataRows = dataRows.slice(1);
        }

        if (!headers.length) {
          return fallbackContent;
        }

        const headerLine = `| ${headers.join(' | ')} |`;
        const separatorLine = `| ${headers.map(() => '---').join(' | ')} |`;
        const bodyLines = dataRows.map((row) => {
          const rowCells = collectRowCells(row);
          const filled = [...rowCells];
          while (filled.length < headers.length) {
            filled.push(' ');
          }
          return `| ${filled.join(' | ')} |`;
        });

        const captionNode =
          (tableNode.caption &&
            tableNode.caption.querySelector('.caption-text')) ||
          tableNode.caption ||
          null;
        const captionText = inlineMarkdownFromNode(captionNode);

        let tableMarkdown = [headerLine, separatorLine, ...bodyLines]
          .filter((line) => Boolean(line))
          .join('\n');

        if (captionText) {
          tableMarkdown = `**${captionText}**\n\n${tableMarkdown}`;
        }

        return `\n\n${tableMarkdown}\n\n`;
      };

      service.addRule('sphinxAdmonitions', {
        filter(node) {
          if (!node || node.nodeName !== 'DIV') {
            return false;
          }
          const className = node.className || '';
          return /\badmonition\b/.test(className);
        },
        replacement(content, node) {
          return renderAdmonitionBlock(node, content);
        },
      });

      service.addRule('docutilsTables', {
        filter(node) {
          if (!node || node.nodeName !== 'TABLE') {
            return false;
          }
          if (node.classList && node.classList.contains('docutils')) {
            return true;
          }
          const className = node.className || '';
          return /docutils|longtable|colwidths-auto/.test(className);
        },
        replacement(content, node) {
          return renderDocutilsTable(node, content);
        },
      });

      service.addRule('mermaidBlocks', {
        filter(node) {
          if (!node || !node.classList) {
            return false;
          }
          const hasMermaidClass = node.classList.contains('mermaid');
          if (!hasMermaidClass) {
            return false;
          }
          return node.nodeName === 'PRE' || node.nodeName === 'DIV' || node.nodeName === 'CODE';
        },
        replacement(content, node) {
          // \u05d4\u05e7\u05d5\u05d3 \u05e0\u05dc\u05e7\u05d7 \u05de\u05d4\u05de\u05e7\u05d5\u05e8 \u05e9\u05e0\u05e9\u05de\u05e8 \u05dc\u05e4\u05e0\u05d9 \u05d4\u05e8\u05d9\u05e0\u05d3\u05d5\u05e8, \u05d5\u05dc\u05d0 \u05de\u05d4-DOM (\u05e9\u05db\u05d1\u05e8 \u05de\u05db\u05d9\u05dc SVG).
          const mermaidContent = getMermaidSource(node);
          if (!mermaidContent) {
            return '\n\n```mermaid\n```\n\n';
          }
          return wrapInFence(mermaidContent, 'mermaid');
        },
      });

      service.addRule('sphinxHighlightBlocks', {
        filter(node) {
          if (node.nodeName !== 'DIV') {
            return false;
          }
          const className = node.className || '';
          return /highlight-|literal-block/.test(className) && node.querySelector('pre');
        },
        replacement(content, node) {
          const pre = node.querySelector('pre');
          if (!pre) {
            return content;
          }
          const language = detectCodeLanguage(node);
          return wrapInFence(pre.textContent || '', language);
        },
      });

      return service;
    } catch (error) {
      console.warn('doc copy page: markdown converter unavailable', error);
      return null;
    }
  };

  const markdownService = createMarkdownService();

  const cleanupArticleClone = (articleNode) => {
    CLEANUP_SELECTORS.forEach((selector) => {
      articleNode.querySelectorAll(selector).forEach((el) => el.remove());
    });
    return articleNode;
  };

  const normalizeMarkdown = (markdown) => {
    if (!markdown) {
      return '';
    }
    const normalized = markdown
      .replace(/\u00a0/g, ' ')
      .replace(/\r\n/g, '\n')
      .replace(MARKDOWN_NEWLINE_REGEX, '\n\n')
      .trim();
    return normalized ? `${normalized}\n` : '';
  };

  const extractArticleContent = (articleNode) => {
    const clone = cleanupArticleClone(articleNode.cloneNode(true));
    if (markdownService) {
      try {
        const markdown = normalizeMarkdown(
          markdownService.turndown(clone.innerHTML)
        );
        if (markdown) {
          return markdown;
        }
      } catch (error) {
        console.warn('doc copy page: markdown conversion failed, using text', error);
      }
    }
    const rawText = clone.innerText || clone.textContent || '';
    return normalizeText(rawText);
  };

  const setState = (button, statusEl, state, statusMessage, isError) => {
    button.dataset.copyState = state;
    button.textContent = BUTTON_TEXT[state];
    button.disabled = state === 'busy';
    button.classList.toggle(ACTIVE_CLASS, state === 'success');
    statusEl.textContent = statusMessage || '';
    statusEl.classList.toggle(ERROR_CLASS, Boolean(isError));
  };

  const attachHandler = (article) => {
    if (article.dataset.copyPageAttached === 'true') {
      return;
    }
    article.dataset.copyPageAttached = 'true';

    const { container, button, status } = createControls();
    article.insertBefore(container, article.firstChild);

    let resetHandle = null;
    const resetState = () => {
      setState(button, status, 'idle', '');
      resetHandle = null;
    };

    button.addEventListener('click', async () => {
      if (button.dataset.copyState === 'busy') {
        return;
      }

      try {
        setState(button, status, 'busy', 'מעתיק...');
        const text = extractArticleContent(article);
        await copyTextToClipboard(text);
        setState(button, status, 'success', STATUS_TEXT.success);
      } catch (error) {
        console.error('copy page failed', error);
        setState(button, status, 'idle', STATUS_TEXT.error, true);
      } finally {
        if (resetHandle) {
          clearTimeout(resetHandle);
        }
        resetHandle = window.setTimeout(resetState, RESET_DELAY_MS);
      }
    });
  };

  const init = () => {
    // חייב לרוץ לפני ש-mermaid מרנדר (הוא רץ ב-window load, כלומר מאוחר יותר).
    captureMermaidSources(document);
    const article = document.querySelector(ARTICLE_SELECTOR);
    if (!article) {
      return;
    }
    attachHandler(article);
  };

  // init מבצע את הלכידה בעצמו בשני המסלולים (DOMContentLoaded או מיידי),
  // ולכן אין צורך בסריקת DOM נוספת כאן.
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  }

  // ייצוא לצורכי בדיקות בלבד (Node). התנאי כולל בדיקת window כדי שהבלוק לא ירוץ
  // בדפדפן שבו קיים shim/loader של CommonJS ומגדיר module גלובלי.
  if (
    typeof window === 'undefined' &&
    typeof module !== 'undefined' &&
    module.exports
  ) {
    module.exports = {
      dedentCodeBlock,
      buildFence,
      wrapInFence,
      captureMermaidSources,
      getMermaidSource,
    };
  }
})();

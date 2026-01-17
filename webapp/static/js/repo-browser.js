/**
 * Repo Browser - Main JavaScript Module
 * 
 * Features:
 * - Tree View with lazy loading
 * - CodeMirror integration
 * - Global search with keyboard shortcuts
 * - Resizable sidebar
 * - Recent files (localStorage)
 */

// ========================================
// Configuration
// ========================================

const CONFIG = {
    repoName: 'CodeBot',  // יוחלף דינמית
    apiBase: '/repo/api',
    maxRecentFiles: 5,
    searchDebounceMs: 300,
    modeMap: {
        'python': 'python',
        'javascript': 'javascript',
        'typescript': 'javascript',
        'html': 'htmlmixed',
        'css': 'css',
        'scss': 'css',
        'json': 'javascript',
        'yaml': 'yaml',
        'markdown': 'markdown',
        'shell': 'shell',
        'bash': 'shell',
        'sql': 'sql',
        'text': 'null'
    }
};

// ========================================
// State
// ========================================

let state = {
    currentFile: null,
    treeData: null,
    editor: null, // CodeMirror 5 instance
    editorView6: null, // CodeMirror 6 EditorView instance (fallback)
    expandedFolders: new Set(),
    selectedElement: null,
    searchTimeout: null
};

// ========================================
// Initialization
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    initTree();
    initSearch();
    initResizer();
    initKeyboardShortcuts();
    loadRecentFiles();
    applyInitialNavigationFromUrl();
});

function applyInitialNavigationFromUrl() {
    try {
        const url = new URL(window.location.href);
        const fileFromQuery = url.searchParams.get('file');
        const hashRaw = (window.location.hash || '').replace(/^#/, '');
        const hashParams = new URLSearchParams(hashRaw);
        const fileFromHash = hashParams.get('file');
        const searchFromHash = hashParams.get('search');

        const initialFile = (fileFromQuery || fileFromHash || '').trim();
        if (initialFile) {
            // Open file without relying on tree selection (works even if folder nodes are not loaded yet)
            const normalized = initialFile.replace(/^\/+/, '');
            selectFile(normalized);
        }

        // Support legacy redirect: /repo/search?q=... -> /repo/#search=...
        const searchValue = (searchFromHash || '').trim();
        if (searchValue) {
            const searchInput = document.getElementById('global-search');
            if (searchInput) {
                searchInput.value = searchValue;
                // Trigger the existing input listener to execute the search
                searchInput.dispatchEvent(new Event('input', { bubbles: true }));
                searchInput.focus();
            }
        }
    } catch (e) {
        // Never break the page because of URL parsing
        console.warn('Initial navigation parsing failed:', e);
    }
}

// ========================================
// Security helpers (XSS / quotes)
// ========================================

function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function escapeJsStr(text) {
    if (text === null || text === undefined) return '';
    // Escape backslashes + single quotes for onclick="... '...'"
    return String(text).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

// ========================================
// Tree View
// ========================================

async function initTree() {
    const treeContainer = document.getElementById('file-tree');
    if (!treeContainer) return;

    try {
        const response = await fetch(`${CONFIG.apiBase}/tree`);
        const data = await response.json();
        state.treeData = data;
        renderTree(treeContainer, data);
    } catch (error) {
        console.error('Failed to load tree:', error);
        treeContainer.innerHTML = `
            <div class="error-message">
                <i class="bi bi-exclamation-triangle"></i>
                <span>Failed to load file tree</span>
            </div>
        `;
    }
}

function renderTree(container, data, level = 0) {
    container.innerHTML = '';
    
    // Sort: folders first, then files, alphabetically
    const items = [...data].sort((a, b) => {
        if (a.type === 'directory' && b.type !== 'directory') return -1;
        if (a.type !== 'directory' && b.type === 'directory') return 1;
        return a.name.localeCompare(b.name);
    });

    items.forEach(item => {
        const node = createTreeNode(item, level);
        container.appendChild(node);
    });
}

function createTreeNode(item, level) {
    const node = document.createElement('div');
    node.className = 'tree-node';
    node.dataset.path = item.path;
    node.dataset.type = item.type;

    const itemEl = document.createElement('div');
    itemEl.className = 'tree-item';
    itemEl.style.paddingLeft = `${8 + level * 16}px`;

    // Toggle arrow for folders
    const toggle = document.createElement('span');
    toggle.className = `tree-toggle ${item.type !== 'directory' ? 'hidden' : ''}`;
    toggle.innerHTML = '<i class="bi bi-chevron-right"></i>';

    // Icon
    const icon = document.createElement('span');
    icon.className = `tree-icon ${getIconClass(item)}`;
    icon.innerHTML = getIcon(item);

    // Name
    const name = document.createElement('span');
    name.className = 'tree-name';
    name.textContent = item.name;

    itemEl.appendChild(toggle);
    itemEl.appendChild(icon);
    itemEl.appendChild(name);
    node.appendChild(itemEl);

    // Children container for folders
    if (item.type === 'directory') {
        const children = document.createElement('div');
        children.className = 'tree-children';
        node.appendChild(children);

        itemEl.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleFolder(node, item);
        });
    } else {
        itemEl.addEventListener('click', (e) => {
            e.stopPropagation();
            selectFile(item.path, itemEl);
        });
    }

    return node;
}

async function toggleFolder(node, item) {
    const children = node.querySelector('.tree-children');
    const toggle = node.querySelector('.tree-toggle');
    const icon = node.querySelector('.tree-icon');
    const isExpanded = children.classList.contains('expanded');

    if (isExpanded) {
        // Collapse
        children.classList.remove('expanded');
        toggle.classList.remove('expanded');
        // עדכון class + innerHTML לאייקון (חשוב ל-Collapse All)
        icon.classList.remove('folder-open');
        icon.classList.add('folder');
        icon.innerHTML = '<i class="bi bi-folder-fill"></i>';
        state.expandedFolders.delete(item.path);
    } else {
        // Expand (עדכון UI רק אחרי טעינה מוצלחת)
        try {
            if (children.children.length === 0) {
                // spinner זמני בזמן טעינת children
                icon.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"></div>';
                const response = await fetch(`${CONFIG.apiBase}/tree?path=${encodeURIComponent(item.path)}`);
                if (!response.ok) throw new Error('Network error');
                const data = await response.json();
                renderTree(children, data, getLevel(node) + 1);
            }

            children.classList.add('expanded');
            toggle.classList.add('expanded');
            // עדכון class + innerHTML לאייקון
            icon.classList.remove('folder');
            icon.classList.add('folder-open');
            icon.innerHTML = '<i class="bi bi-folder2-open"></i>';
            state.expandedFolders.add(item.path);
        } catch (error) {
            console.error('Failed to load folder:', error);
            showToast('Failed to load folder contents');
            // מחזירים אייקון סגור (למקרה ששמנו spinner)
            icon.classList.remove('folder-open');
            icon.classList.add('folder');
            icon.innerHTML = '<i class="bi bi-folder-fill"></i>';
        }
    }
}

function getLevel(node) {
    let level = 0;
    let parent = node.parentElement;
    while (parent && !parent.id) {
        if (parent.classList.contains('tree-children')) {
            level++;
        }
        parent = parent.parentElement;
    }
    return level;
}

function getIconClass(item) {
    if (item.type === 'directory') {
        return 'folder';
    }
    const ext = item.name.split('.').pop().toLowerCase();
    const classes = {
        'py': 'file-python',
        'js': 'file-javascript',
        'jsx': 'file-javascript',
        'ts': 'file-typescript',
        'tsx': 'file-typescript',
        'html': 'file-html',
        'htm': 'file-html',
        'css': 'file-css',
        'scss': 'file-css',
        'json': 'file-json',
        'md': 'file-markdown',
        'yml': 'file-yaml',
        'yaml': 'file-yaml',
        'sh': 'file-shell',
        'bash': 'file-shell',
        'sql': 'file-sql'
    };
    return classes[ext] || 'file-default';
}

function getIcon(item) {
    if (item.type === 'directory') {
        return '<i class="bi bi-folder-fill"></i>';
    }
    const ext = item.name.split('.').pop().toLowerCase();
    const icons = {
        'py': '<i class="bi bi-filetype-py"></i>',
        'js': '<i class="bi bi-filetype-js"></i>',
        'jsx': '<i class="bi bi-filetype-jsx"></i>',
        'ts': '<i class="bi bi-filetype-ts"></i>',   // תוקן: היה tsx בטעות
        'tsx': '<i class="bi bi-filetype-tsx"></i>',
        'html': '<i class="bi bi-filetype-html"></i>',
        'css': '<i class="bi bi-filetype-css"></i>',
        'scss': '<i class="bi bi-filetype-scss"></i>',
        'json': '<i class="bi bi-filetype-json"></i>',
        'md': '<i class="bi bi-filetype-md"></i>',
        'yml': '<i class="bi bi-filetype-yml"></i>',
        'yaml': '<i class="bi bi-filetype-yml"></i>',
        'sh': '<i class="bi bi-terminal"></i>',
        'sql': '<i class="bi bi-filetype-sql"></i>'
    };
    return icons[ext] || '<i class="bi bi-file-earmark-code"></i>';
}

// ========================================
// File Selection & CodeMirror
// ========================================

async function selectFile(path, element) {
    // Update selection UI
    if (state.selectedElement) {
        state.selectedElement.classList.remove('selected');
    }
    if (element) {
        element.classList.add('selected');
        state.selectedElement = element;
    }

    state.currentFile = path;

    // Show loading
    const wrapper = document.getElementById('code-editor-wrapper');
    const welcome = document.getElementById('welcome-screen');
    const header = document.getElementById('code-header');
    const footer = document.getElementById('code-footer');

    welcome.style.display = 'none';
    wrapper.style.display = 'block';
    header.style.display = 'flex';
    footer.style.display = 'flex';
    
    // Force the container to recalculate layout
    const container = document.getElementById('code-viewer-container');
    if (container) {
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
    }

    try {
        // Fetch file content
        const response = await fetch(`${CONFIG.apiBase}/file/${encodeURIComponent(path)}`);
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Update breadcrumbs
        updateBreadcrumbs(path);

        // Update file info
        updateFileInfo(data);

        // Initialize or update CodeMirror
        await initCodeViewer(data.content, data.language || detectLanguage(path));

        // Save to recent files
        addToRecentFiles(path);

    } catch (error) {
        console.error('Failed to load file:', error);
        wrapper.innerHTML = `
            <div class="error-message" style="padding: 20px; color: var(--accent-red);">
                <i class="bi bi-exclamation-triangle"></i>
                <span>Failed to load file: ${escapeHtml(error && error.message ? error.message : String(error))}</span>
            </div>
        `;
    }
}

async function initCodeViewer(content, language) {
    const wrapper = document.getElementById('code-editor-wrapper');
    if (!wrapper) return;

    const kind = await ensureCodeMirrorRuntime();

    // Destroy previous instances
    if (state.editor) {
        try { state.editor.toTextArea(); } catch (_) {}
        state.editor = null;
    }
    if (state.editorView6) {
        try { state.editorView6.destroy(); } catch (_) {}
        state.editorView6 = null;
    }

    if (kind === 'cm5') {
        if (!document.getElementById('code-editor')) {
            wrapper.innerHTML = '<textarea id="code-editor"></textarea>';
        }

        const textarea = document.getElementById('code-editor');
        const mode = CONFIG.modeMap[language] || 'null';

        state.editor = CodeMirror.fromTextArea(textarea, {
            value: content,
            mode: mode,
            theme: 'dracula',
            lineNumbers: true,
            readOnly: true,
            lineWrapping: false,
            foldGutter: true,
            gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
            styleActiveLine: true,
            matchBrackets: true,
            autoCloseBrackets: true,
            tabSize: 4,
            indentUnit: 4,
            extraKeys: {
                'Ctrl-F': 'findPersistent',
                'Cmd-F': 'findPersistent',
                'Ctrl-G': 'findNext',
                'Cmd-G': 'findNext',
                'Shift-Ctrl-G': 'findPrev',
                'Shift-Cmd-G': 'findPrev',
                'Ctrl-H': 'replace',
                'Cmd-Option-F': 'replace'
            }
        });

        state.editor.setValue(content);
        
        // Refresh editor after DOM update
        setTimeout(() => {
            // Get the actual available height from viewport
            const wrapper = document.getElementById('code-editor-wrapper');
            const header = document.getElementById('code-header');
            const footer = document.getElementById('code-footer');
            const searchBar = document.getElementById('in-file-search');
            const repoSearchBar = document.querySelector('.repo-search-bar');
            
            if (wrapper && state.editor) {
                // Calculate used height
                const headerHeight = header && header.style.display !== 'none' ? header.offsetHeight : 0;
                const footerHeight = footer && footer.style.display !== 'none' ? footer.offsetHeight : 0;
                const searchBarHeight = searchBar && searchBar.style.display !== 'none' ? searchBar.offsetHeight : 0;
                const repoSearchHeight = repoSearchBar ? repoSearchBar.offsetHeight : 52;
                
                // Calculate available height (viewport - all fixed elements)
                const viewportHeight = window.innerHeight;
                const navbarHeight = 56; // --header-height
                const availableHeight = viewportHeight - navbarHeight - repoSearchHeight - headerHeight - footerHeight - searchBarHeight - 20;
                
                if (availableHeight > 200) {
                    wrapper.style.height = availableHeight + 'px';
                    state.editor.setSize(null, availableHeight + 'px');
                }
                
                state.editor.refresh();
            }
        }, 100);
        return;
    }

    if (kind === 'cm6') {
        wrapper.innerHTML = '<div id="code-editor-cm6" style="height:100%;"></div>';
        const mountEl = document.getElementById('code-editor-cm6');

        const { EditorState, EditorView } = window.CodeMirror6;
        const basicSetup = window.CodeMirror6.basicSetup || [];

        const extensions = [...basicSetup];

        // שפה
        if (typeof window.CodeMirror6.getLanguageSupport === 'function') {
            const support = window.CodeMirror6.getLanguageSupport(language);
            if (support) extensions.push(support);
        }

        // Read-only
        if (EditorView && EditorView.editable) {
            extensions.push(EditorView.editable.of(false));
        }
        if (EditorState && EditorState.readOnly) {
            extensions.push(EditorState.readOnly.of(true));
        }

        const cmState = EditorState.create({
            doc: String(content || ''),
            extensions
        });

        state.editorView6 = new EditorView({
            state: cmState,
            parent: mountEl
        });

        return;
    }

    throw new Error('CodeMirror failed to load');
}

async function ensureCodeMirrorRuntime() {
    // CodeMirror 5 from CDN (guide)
    if (window.CodeMirror && typeof window.CodeMirror.fromTextArea === 'function') {
        return 'cm5';
    }

    // Fallback: use existing in-app CodeMirror 6 loader (local bundle)
    if (window.editorManager && typeof window.editorManager.loadCodeMirror === 'function') {
        try {
            await window.editorManager.loadCodeMirror();
        } catch (_) {
            // ignore - handled by checks below
        }
    }

    if (window.CodeMirror6 && window.CodeMirror6.EditorView && window.CodeMirror6.EditorState) {
        return 'cm6';
    }

    return null;
}

function detectLanguage(path) {
    const ext = path.split('.').pop().toLowerCase();
    const langMap = {
        'py': 'python',
        'js': 'javascript',
        'jsx': 'javascript',
        'ts': 'typescript',
        'tsx': 'typescript',
        'html': 'html',
        'htm': 'html',
        'css': 'css',
        'scss': 'css',
        'json': 'json',
        'md': 'markdown',
        'yml': 'yaml',
        'yaml': 'yaml',
        'sh': 'shell',
        'bash': 'shell',
        'sql': 'sql'
    };
    return langMap[ext] || 'text';
}

function updateBreadcrumbs(path) {
    const breadcrumb = document.getElementById('file-breadcrumb');
    const parts = path.split('/');
    
    breadcrumb.innerHTML = parts.map((part, index) => {
        const isLast = index === parts.length - 1;
        const partPath = parts.slice(0, index + 1).join('/');
        const safePart = escapeHtml(part);
        const safeJsPartPath = escapeJsStr(partPath);
        
        if (isLast) {
            return `<li class="breadcrumb-item active">${safePart}</li>`;
        }
        return `<li class="breadcrumb-item"><a href="#" onclick="navigateToFolder('${safeJsPartPath}')">${safePart}</a></li>`;
    }).join('');

    // Update copy path button
    document.getElementById('copy-path').onclick = () => {
        navigator.clipboard.writeText(path);
        showToast('Path copied!');
    };
    
    // Update copy content button
    const copyContentBtn = document.getElementById('copy-content');
    if (copyContentBtn) {
        copyContentBtn.onclick = () => {
            let content = null;
            
            // Try CodeMirror 5 first
            if (state.editor && typeof state.editor.getValue === 'function') {
                content = state.editor.getValue();
            }
            // Fallback to CodeMirror 6
            else if (state.editorView6 && state.editorView6.state && state.editorView6.state.doc) {
                content = state.editorView6.state.doc.toString();
            }
            
            if (content !== null) {
                navigator.clipboard.writeText(content);
                showToast('Content copied!');
            } else {
                showToast('No content to copy');
            }
        };
    }
    
    // Update GitHub link (encode path for special characters)
    const githubLink = document.getElementById('github-link');
    if (githubLink) {
        // Encode each path segment separately to preserve slashes
        const encodedPath = path.split('/').map(segment => encodeURIComponent(segment)).join('/');
        githubLink.href = `https://github.com/amirbiron/CodeBot/blob/main/${encodedPath}`;
    }
}

function updateFileInfo(data) {
    const info = document.getElementById('file-info');
    const lines = data.content ? data.content.split('\n').length : 0;
    const size = data.content ? formatBytes(data.content.length) : '0 B';
    const lang = data.language || 'text';
    
    info.innerHTML = `
        <span><i class="bi bi-list-ol"></i> ${lines} lines</span>
        <span><i class="bi bi-hdd"></i> ${size}</span>
        <span><i class="bi bi-code"></i> ${lang}</span>
    `;
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// ========================================
// Search
// ========================================

function initSearch() {
    const searchInput = document.getElementById('global-search');
    const dropdown = document.getElementById('search-results-dropdown');
    const shortcuts = document.querySelector('.search-shortcuts');
    
    if (!searchInput || !dropdown) return;
    
    const resultsList = dropdown.querySelector('.search-results-list');

    // הסתרת shortcuts כשיש טקסט בחיפוש (JS fallback)
    function updateShortcutsVisibility() {
        if (shortcuts) {
            shortcuts.style.opacity = searchInput.value.length > 0 ? '0' : '1';
        }
    }

    searchInput.addEventListener('input', (e) => {
        updateShortcutsVisibility();
        clearTimeout(state.searchTimeout);
        const query = e.target.value.trim();

        if (query.length < 2) {
            dropdown.classList.add('hidden');
            return;
        }

        state.searchTimeout = setTimeout(async () => {
            try {
                const response = await fetch(`${CONFIG.apiBase}/search?q=${encodeURIComponent(query)}&type=content`);
                const data = await response.json();
                
                if (data.error) {
                    resultsList.innerHTML = `
                        <div class="search-result-item">
                            <span class="text-muted">${escapeHtml(data.error)}</span>
                        </div>
                    `;
                } else {
                    renderSearchResults(resultsList, data.results || [], query);
                }
                dropdown.classList.remove('hidden');
            } catch (error) {
                console.error('Search failed:', error);
                resultsList.innerHTML = `
                    <div class="search-result-item">
                        <span class="text-muted">Search unavailable</span>
                    </div>
                `;
                dropdown.classList.remove('hidden');
            }
        }, CONFIG.searchDebounceMs);
    });

    searchInput.addEventListener('focus', () => {
        updateShortcutsVisibility();
        if (searchInput.value.length >= 2) {
            dropdown.classList.remove('hidden');
        }
    });
    
    searchInput.addEventListener('blur', () => {
        // מחזירים את ה-shortcuts כשמאבדים פוקוס (רק אם ריק)
        setTimeout(() => {
            if (searchInput.value.length === 0 && shortcuts) {
                shortcuts.style.opacity = '1';
            }
        }, 100);
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-wrapper') && !e.target.closest('.search-results-dropdown')) {
            dropdown.classList.add('hidden');
        }
    });
}

function renderSearchResults(container, results, query) {
    if (results.length === 0) {
        container.innerHTML = `
            <div class="search-result-item">
                <span class="text-muted">No results found</span>
            </div>
        `;
        return;
    }

    container.innerHTML = results.slice(0, 20).map(result => {
        const safePath = escapeHtml(result.path);
        const safeJsPath = escapeJsStr(result.path);
        const highlightedContent = result.content 
            ? highlightMatch(escapeHtml(result.content), query)
            : '';
        
        return `
            <div class="search-result-item" onclick="selectFile('${safeJsPath}')">
                <div class="search-result-path">
                    <span class="file-icon">${getIcon({name: result.path, type: 'file'})}</span>
                    <span>${safePath}</span>
                    ${result.line ? `<span class="search-result-line">L${result.line}</span>` : ''}
                </div>
                ${highlightedContent ? `<div class="search-result-preview">${highlightedContent}</div>` : ''}
            </div>
        `;
    }).join('');
}

function highlightMatch(text, query) {
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${escaped})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

function focusSearch() {
    const searchInput = document.getElementById('global-search');
    if (searchInput) {
        searchInput.focus();
        searchInput.select();
    }
}

// In-file search state
let searchState = {
    matches: [],
    currentIndex: -1,
    query: ''
};

function searchInFile() {
    // Show custom search bar (works on mobile too)
    const searchBar = document.getElementById('in-file-search');
    const searchInput = document.getElementById('in-file-search-input');
    
    if (searchBar && searchInput) {
        searchBar.style.display = 'flex';
        searchInput.focus();
        searchInput.select();
        // Refresh editor to adjust height after search bar appears
        setTimeout(() => {
            if (state.editor) state.editor.refresh();
        }, 50);
    } else if (state.editor) {
        // Fallback to CM5 built-in search
        state.editor.focus();
        if (typeof state.editor.execCommand === 'function') {
            state.editor.execCommand('find');
        }
    } else {
        showToast('Open a file first');
    }
}

function closeInFileSearch() {
    const searchBar = document.getElementById('in-file-search');
    if (searchBar) {
        searchBar.style.display = 'none';
    }
    clearSearchHighlights();
    searchState = { matches: [], currentIndex: -1, query: '' };
    document.getElementById('in-file-search-count').textContent = '';
    // Refresh editor to adjust height after search bar closes
    setTimeout(() => {
        if (state.editor) state.editor.refresh();
    }, 50);
}

function performInFileSearch(query) {
    if (!query || query.length < 1) {
        clearSearchHighlights();
        searchState = { matches: [], currentIndex: -1, query: '' };
        document.getElementById('in-file-search-count').textContent = '';
        return;
    }
    
    searchState.query = query;
    searchState.matches = [];
    searchState.currentIndex = -1;
    
    let content = '';
    
    // Get content from editor
    if (state.editor && typeof state.editor.getValue === 'function') {
        content = state.editor.getValue();
    } else if (state.editorView6 && state.editorView6.state && state.editorView6.state.doc) {
        content = state.editorView6.state.doc.toString();
    }
    
    if (!content) return;
    
    // Find all matches (case insensitive)
    const regex = new RegExp(escapeRegex(query), 'gi');
    let match;
    while ((match = regex.exec(content)) !== null) {
        searchState.matches.push({
            index: match.index,
            length: match[0].length
        });
    }
    
    // Update count display
    const countEl = document.getElementById('in-file-search-count');
    if (searchState.matches.length > 0) {
        countEl.textContent = `${searchState.matches.length} found`;
        findNextMatch();
    } else {
        countEl.textContent = 'No results';
    }
}

function findNextMatch() {
    if (searchState.matches.length === 0) return;
    
    searchState.currentIndex = (searchState.currentIndex + 1) % searchState.matches.length;
    goToMatch(searchState.currentIndex);
}

function findPrevMatch() {
    if (searchState.matches.length === 0) return;
    
    searchState.currentIndex = searchState.currentIndex <= 0 
        ? searchState.matches.length - 1 
        : searchState.currentIndex - 1;
    goToMatch(searchState.currentIndex);
}

function goToMatch(index) {
    const match = searchState.matches[index];
    if (!match) return;
    
    // Update count display
    const countEl = document.getElementById('in-file-search-count');
    countEl.textContent = `${index + 1} / ${searchState.matches.length}`;
    
    // Navigate to match in editor
    if (state.editor) {
        const doc = state.editor.getDoc();
        const startPos = doc.posFromIndex(match.index);
        const endPos = doc.posFromIndex(match.index + match.length);
        
        // Select the match
        doc.setSelection(startPos, endPos);
        state.editor.scrollIntoView({ from: startPos, to: endPos }, 100);
        state.editor.focus();
    } else if (state.editorView6) {
        // CM6 navigation
        state.editorView6.dispatch({
            selection: { anchor: match.index, head: match.index + match.length },
            scrollIntoView: true
        });
        state.editorView6.focus();
    }
}

function clearSearchHighlights() {
    // Clear any search highlights if needed
}

function escapeRegex(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Initialize in-file search input listener
document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('in-file-search-input');
    if (searchInput) {
        let debounceTimer;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                performInFileSearch(e.target.value);
            }, 200);
        });
        
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                if (e.shiftKey) {
                    findPrevMatch();
                } else {
                    findNextMatch();
                }
            } else if (e.key === 'Escape') {
                closeInFileSearch();
            }
        });
    }
});

// Make functions available globally
window.searchInFile = searchInFile;
window.closeInFileSearch = closeInFileSearch;
window.findNextMatch = findNextMatch;
window.findPrevMatch = findPrevMatch;

// ========================================
// Keyboard Shortcuts
// ========================================

function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl+K or Cmd+K - Focus search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            focusSearch();
        }
        
        // Escape - Close search dropdown
        if (e.key === 'Escape') {
            const dropdown = document.getElementById('search-results-dropdown');
            dropdown?.classList.add('hidden');
        }
    });
}

// ========================================
// Resizable Sidebar
// ========================================

function initResizer() {
    const resizer = document.getElementById('sidebar-resizer');
    const sidebar = document.getElementById('repo-sidebar');
    
    if (!resizer || !sidebar) return;

    let isResizing = false;
    let startX, startWidth;

    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = sidebar.offsetWidth;
        resizer.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        
        const width = startWidth + (e.clientX - startX);
        const minWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-min-width'));
        const maxWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-max-width'));
        
        if (width >= minWidth && width <= maxWidth) {
            sidebar.style.width = `${width}px`;
        }
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            resizer.classList.remove('active');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
}

// ========================================
// Recent Files
// ========================================

function loadRecentFiles() {
    const container = document.getElementById('recent-files-list');
    if (!container) return;

    const recent = getRecentFiles();
    
    if (recent.length === 0) {
        container.innerHTML = '<li class="text-muted" style="cursor: default;">No recent files</li>';
        return;
    }

    container.innerHTML = recent.map(path => `
        <li onclick="selectFile('${escapeJsStr(path)}')">
            ${getIcon({name: path, type: 'file'})}
            <span>${escapeHtml(path.split('/').pop())}</span>
        </li>
    `).join('');
}

function getRecentFiles() {
    try {
        return JSON.parse(localStorage.getItem('recentFiles') || '[]');
    } catch {
        return [];
    }
}

function addToRecentFiles(path) {
    let recent = getRecentFiles();
    recent = recent.filter(p => p !== path);
    recent.unshift(path);
    recent = recent.slice(0, CONFIG.maxRecentFiles);
    localStorage.setItem('recentFiles', JSON.stringify(recent));
    loadRecentFiles();
}

// ========================================
// Utilities
// ========================================

function showToast(message, duration = 2000) {
    const toast = document.createElement('div');
    toast.className = 'toast-message';
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 12px 20px;
        background: var(--bg-secondary);
        color: var(--text-primary);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 9999;
        animation: slideIn 0.3s ease;
    `;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

function navigateToFolder(path) {
    // Find and expand the folder in tree (בלי CSS selector injection)
    const node = findNodeByPath(path);
    if (node) {
        const item = node.querySelector('.tree-item');
        item?.click();
    }
}

function findNodeByPath(path) {
    const nodes = document.querySelectorAll('[data-path]');
    for (const node of nodes) {
        if (node && node.dataset && node.dataset.path === path) {
            return node;
        }
    }
    return null;
}

// Collapse all folders
document.getElementById('collapse-all')?.addEventListener('click', () => {
    // Remove expanded class from children containers
    document.querySelectorAll('.tree-children.expanded').forEach(el => {
        el.classList.remove('expanded');
    });
    
    // Remove expanded class from toggle arrows
    document.querySelectorAll('.tree-toggle.expanded').forEach(el => {
        el.classList.remove('expanded');
    });
    
    // Reset folder icons from open to closed
    // תיקון: בלי זה, האייקונים נשארים פתוחים למרות שהתיקייה סגורה
    document.querySelectorAll('.tree-icon.folder-open').forEach(el => {
        el.classList.remove('folder-open');
        el.classList.add('folder');
        el.innerHTML = '<i class="bi bi-folder-fill"></i>';
    });
    
    // Clear state
    state.expandedFolders.clear();
});


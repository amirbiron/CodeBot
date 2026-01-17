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
    editor: null,
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
});

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
        // Expand
        if (children.children.length === 0) {
            // Load children
            try {
                const response = await fetch(`${CONFIG.apiBase}/tree?path=${encodeURIComponent(item.path)}`);
                const data = await response.json();
                renderTree(children, data, getLevel(node) + 1);
            } catch (error) {
                console.error('Failed to load folder:', error);
            }
        }
        children.classList.add('expanded');
        toggle.classList.add('expanded');
        // עדכון class + innerHTML לאייקון
        icon.classList.remove('folder');
        icon.classList.add('folder-open');
        icon.innerHTML = '<i class="bi bi-folder2-open"></i>';
        state.expandedFolders.add(item.path);
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
        initCodeMirror(data.content, data.language || detectLanguage(path));

        // Save to recent files
        addToRecentFiles(path);

    } catch (error) {
        console.error('Failed to load file:', error);
        wrapper.innerHTML = `
            <div class="error-message" style="padding: 20px; color: var(--accent-red);">
                <i class="bi bi-exclamation-triangle"></i>
                <span>Failed to load file: ${error.message}</span>
            </div>
        `;
    }
}

function initCodeMirror(content, language) {
    const textarea = document.getElementById('code-editor');
    
    // Destroy existing editor
    if (state.editor) {
        state.editor.toTextArea();
    }

    // Get mode from language
    const mode = CONFIG.modeMap[language] || 'null';

    // Create new editor
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
        indentUnit: 4
    });

    state.editor.setValue(content);
    state.editor.refresh();
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
        
        if (isLast) {
            return `<li class="breadcrumb-item active">${part}</li>`;
        }
        return `<li class="breadcrumb-item"><a href="#" onclick="navigateToFolder('${partPath}')">${part}</a></li>`;
    }).join('');

    // Update copy button
    document.getElementById('copy-path').onclick = () => {
        navigator.clipboard.writeText(path);
        showToast('Path copied!');
    };
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
    const resultsList = dropdown.querySelector('.search-results-list');

    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
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
                
                renderSearchResults(resultsList, data.results || [], query);
                dropdown.classList.remove('hidden');
            } catch (error) {
                console.error('Search failed:', error);
            }
        }, CONFIG.searchDebounceMs);
    });

    searchInput.addEventListener('focus', () => {
        if (searchInput.value.length >= 2) {
            dropdown.classList.remove('hidden');
        }
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
        const highlightedContent = result.content 
            ? highlightMatch(result.content, query)
            : '';
        
        return `
            <div class="search-result-item" onclick="selectFile('${result.path}')">
                <div class="search-result-path">
                    <span class="file-icon">${getIcon({name: result.path, type: 'file'})}</span>
                    <span>${result.path}</span>
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
        <li onclick="selectFile('${path}')">
            ${getIcon({name: path, type: 'file'})}
            <span>${path.split('/').pop()}</span>
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
    // Find and expand the folder in tree
    const node = document.querySelector(`[data-path="${path}"]`);
    if (node) {
        const item = node.querySelector('.tree-item');
        item?.click();
    }
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


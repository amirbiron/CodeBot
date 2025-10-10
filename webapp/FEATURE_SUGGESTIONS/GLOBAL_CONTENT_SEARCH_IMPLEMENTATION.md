# מדריך מימוש: חיפוש גלובלי בתוכן קבצים

## תיאור הפיצ'ר
הוספת יכולת חיפוש גלובלי בתוכן כל הקבצים של המשתמש, בנוסף לחיפוש הקיים בקובץ בודד. 
הפיצ'ר מאפשר למצוא במהירות קטעי קוד, טקסט או דפוסים בכל הקבצים השמורים.

## סטטוס נוכחי
- ✅ קיימת תשתית מלאה של מנוע חיפוש ב-`/workspace/search_engine.py`
- ✅ המנוע כולל פונקציה `_content_search` לחיפוש בתוכן
- ✅ קיים אינדקס אוטומטי לביצועים טובים
- ⏳ חסר: endpoint ב-webapp וממשק משתמש

## ארכיטקטורה

```
┌─────────────────────────────┐
│      ממשק משתמש (UI)        │
│  ┌───────────────────┐      │
│  │ תיבת חיפוש גלובלי │      │
│  └───────────────────┘      │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│    API Endpoint             │
│  /api/search/global         │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│    Search Engine            │
│  search_engine.search()     │
│  ┌──────────────────┐       │
│  │  SearchIndex      │       │
│  │  - word_index     │       │
│  │  - function_index │       │
│  │  - language_index │       │
│  └──────────────────┘       │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│        Database             │
│    get_user_files()         │
└─────────────────────────────┘
```

## שלבי מימוש

### שלב 1: הוספת API Endpoint

**קובץ:** `webapp/app.py`

**מיקום:** אחרי שאר ה-API endpoints (בסביבות שורה 2000+)

```python
from search_engine import search_engine, SearchType, SearchFilter, SortOrder

@app.route('/api/search/global', methods=['POST'])
@login_required
def global_content_search():
    """חיפוש גלובלי בתוכן כל הקבצים של המשתמש
    
    Parameters (JSON):
        - query: string (חובה) - טקסט החיפוש
        - search_type: string - סוג החיפוש (content/regex/fuzzy/function)
        - filters: object - פילטרים אופציונליים
            - languages: array - סינון לפי שפות
            - tags: array - סינון לפי תגיות
            - date_from: string - תאריך התחלה
            - date_to: string - תאריך סיום
        - sort: string - סדר מיון (relevance/date_desc/date_asc/name_asc/name_desc)
        - limit: number - מספר תוצאות מקסימלי (ברירת מחדל: 50)
        - page: number - עמוד לעימוד (ברירת מחדל: 1)
    """
    try:
        data = request.get_json()
        
        # ולידציה
        query = data.get('query', '').strip()
        if not query:
            return jsonify({'error': 'נא להזין טקסט לחיפוש'}), 400
        
        # פרמטרים
        search_type_str = data.get('search_type', 'content')
        search_types = {
            'content': SearchType.CONTENT,
            'regex': SearchType.REGEX,
            'fuzzy': SearchType.FUZZY,
            'function': SearchType.FUNCTION,
            'text': SearchType.TEXT
        }
        search_type = search_types.get(search_type_str, SearchType.CONTENT)
        
        # פילטרים
        filter_data = data.get('filters', {})
        filters = SearchFilter(
            languages=filter_data.get('languages', []),
            tags=filter_data.get('tags', []),
            date_from=filter_data.get('date_from'),
            date_to=filter_data.get('date_to'),
            min_size=filter_data.get('min_size'),
            max_size=filter_data.get('max_size'),
            has_functions=filter_data.get('has_functions'),
            has_classes=filter_data.get('has_classes'),
            file_pattern=filter_data.get('file_pattern')
        )
        
        # מיון
        sort_str = data.get('sort', 'relevance')
        sort_orders = {
            'relevance': SortOrder.RELEVANCE,
            'date_desc': SortOrder.DATE_DESC,
            'date_asc': SortOrder.DATE_ASC,
            'name_asc': SortOrder.NAME_ASC,
            'name_desc': SortOrder.NAME_DESC,
            'size_desc': SortOrder.SIZE_DESC,
            'size_asc': SortOrder.SIZE_ASC
        }
        sort_order = sort_orders.get(sort_str, SortOrder.RELEVANCE)
        
        # עימוד
        page = max(1, data.get('page', 1))
        limit = min(100, data.get('limit', 50))
        
        # ביצוע חיפוש
        results = search_engine.search(
            user_id=session['user_id'],
            query=query,
            search_type=search_type,
            filters=filters,
            sort_order=sort_order,
            limit=limit * page  # קח יותר ודלג לעמוד הנכון
        )
        
        # עימוד תוצאות
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_results = results[start_idx:end_idx]
        
        # המרת תוצאות ל-JSON
        response_data = {
            'success': True,
            'query': query,
            'total_results': len(results),
            'page': page,
            'per_page': limit,
            'results': [
                {
                    'file_id': hashlib.md5(f"{session['user_id']}:{r.file_name}".encode()).hexdigest(),
                    'file_name': r.file_name,
                    'language': r.programming_language,
                    'tags': r.tags,
                    'score': round(r.relevance_score, 2),
                    'snippet': r.snippet_preview[:200] if r.snippet_preview else '',
                    'highlights': r.highlight_ranges,
                    'matches': r.matches[:5],  # מקסימום 5 התאמות
                    'updated_at': r.updated_at.isoformat(),
                    'size': len(r.content)
                }
                for r in paginated_results
            ]
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"שגיאה בחיפוש גלובלי: {e}")
        return jsonify({'error': 'אירעה שגיאה בחיפוש'}), 500


@app.route('/api/search/suggestions', methods=['GET'])
@login_required
def search_suggestions():
    """הצעות השלמה אוטומטית לחיפוש"""
    try:
        partial = request.args.get('q', '').strip()
        if len(partial) < 2:
            return jsonify({'suggestions': []})
        
        suggestions = search_engine.suggest_completions(
            user_id=session['user_id'],
            partial_query=partial,
            limit=10
        )
        
        return jsonify({'suggestions': suggestions})
        
    except Exception as e:
        logger.error(f"שגיאה בהצעות חיפוש: {e}")
        return jsonify({'suggestions': []})
```

### שלב 2: הוספת ממשק משתמש

#### 2.1 הוספת תיבת חיפוש גלובלי

**קובץ:** `webapp/templates/files.html` או `webapp/templates/dashboard.html`

**מיקום:** בראש העמוד, אחרי הכותרת

```html
<!-- חיפוש גלובלי בתוכן -->
<div class="card mb-4">
    <div class="card-body">
        <h5 class="card-title">🔍 חיפוש גלובלי בכל הקבצים</h5>
        
        <div class="row">
            <div class="col-md-8">
                <div class="input-group">
                    <input type="text" 
                           id="globalSearchInput" 
                           class="form-control"
                           placeholder="חפש טקסט, קוד או ביטוי רגולרי בכל הקבצים..."
                           autocomplete="off">
                    <div class="input-group-append">
                        <button class="btn btn-primary" 
                                onclick="performGlobalSearch()"
                                id="searchBtn">
                            <i class="fas fa-search"></i> חפש
                        </button>
                    </div>
                </div>
                <!-- הצעות אוטומטיות -->
                <div id="searchSuggestions" class="list-group position-absolute w-100" 
                     style="z-index: 1000; display: none;"></div>
            </div>
            
            <div class="col-md-4">
                <button class="btn btn-outline-secondary btn-sm" 
                        onclick="toggleAdvancedSearch()">
                    <i class="fas fa-cog"></i> חיפוש מתקדם
                </button>
            </div>
        </div>
        
        <!-- אפשרויות מתקדמות -->
        <div id="advancedSearchOptions" class="mt-3" style="display: none;">
            <div class="row">
                <div class="col-md-3">
                    <label>סוג חיפוש:</label>
                    <select id="searchType" class="form-control form-control-sm">
                        <option value="content">תוכן</option>
                        <option value="text">טקסט (מילים)</option>
                        <option value="regex">ביטוי רגולרי</option>
                        <option value="fuzzy">חיפוש מטושטש</option>
                        <option value="function">שמות פונקציות</option>
                    </select>
                </div>
                
                <div class="col-md-3">
                    <label>שפות תכנות:</label>
                    <select id="filterLanguages" class="form-control form-control-sm" multiple>
                        <option value="python">Python</option>
                        <option value="javascript">JavaScript</option>
                        <option value="java">Java</option>
                        <option value="cpp">C++</option>
                        <option value="html">HTML</option>
                        <option value="css">CSS</option>
                        <option value="sql">SQL</option>
                    </select>
                </div>
                
                <div class="col-md-3">
                    <label>מיון לפי:</label>
                    <select id="sortOrder" class="form-control form-control-sm">
                        <option value="relevance">רלוונטיות</option>
                        <option value="date_desc">תאריך (חדש לישן)</option>
                        <option value="date_asc">תאריך (ישן לחדש)</option>
                        <option value="name_asc">שם קובץ (א-ת)</option>
                        <option value="size_desc">גודל (גדול לקטן)</option>
                    </select>
                </div>
                
                <div class="col-md-3">
                    <label>תוצאות לעמוד:</label>
                    <select id="resultsPerPage" class="form-control form-control-sm">
                        <option value="10">10</option>
                        <option value="20" selected>20</option>
                        <option value="50">50</option>
                        <option value="100">100</option>
                    </select>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- אזור תוצאות חיפוש -->
<div id="searchResultsContainer" style="display: none;">
    <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
            <h5 class="mb-0">תוצאות חיפוש</h5>
            <button class="btn btn-sm btn-outline-secondary" onclick="clearSearch()">
                <i class="fas fa-times"></i> נקה חיפוש
            </button>
        </div>
        <div class="card-body">
            <div id="searchInfo" class="mb-3"></div>
            <div id="searchResults"></div>
            <div id="searchPagination" class="mt-3"></div>
        </div>
    </div>
</div>
```

#### 2.2 JavaScript לטיפול בחיפוש

**קובץ חדש:** `webapp/static/js/global_search.js`

```javascript
// משתני מצב
let currentSearchQuery = '';
let currentSearchPage = 1;
let searchTimeout = null;
let suggestionsTimeout = null;

// אתחול
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('globalSearchInput');
    
    // חיפוש בלחיצת Enter
    searchInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            performGlobalSearch();
        }
    });
    
    // הצעות אוטומטיות
    searchInput.addEventListener('input', function(e) {
        clearTimeout(suggestionsTimeout);
        const query = e.target.value.trim();
        
        if (query.length >= 2) {
            suggestionsTimeout = setTimeout(() => {
                fetchSuggestions(query);
            }, 300);
        } else {
            hideSuggestions();
        }
    });
    
    // הסתרת הצעות בלחיצה החוצה
    document.addEventListener('click', function(e) {
        if (!e.target.closest('#globalSearchInput') && 
            !e.target.closest('#searchSuggestions')) {
            hideSuggestions();
        }
    });
});

// ביצוע חיפוש
async function performGlobalSearch(page = 1) {
    const query = document.getElementById('globalSearchInput').value.trim();
    
    if (!query) {
        showNotification('נא להזין טקסט לחיפוש', 'warning');
        return;
    }
    
    // שמירת מצב
    currentSearchQuery = query;
    currentSearchPage = page;
    
    // הצגת מצב טעינה
    const searchBtn = document.getElementById('searchBtn');
    const originalBtnText = searchBtn.innerHTML;
    searchBtn.disabled = true;
    searchBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> מחפש...';
    
    try {
        // בניית בקשה
        const searchData = {
            query: query,
            search_type: document.getElementById('searchType')?.value || 'content',
            page: page,
            limit: parseInt(document.getElementById('resultsPerPage')?.value || '20'),
            sort: document.getElementById('sortOrder')?.value || 'relevance'
        };
        
        // הוספת פילטרים אם נבחרו
        const selectedLanguages = getSelectedValues('filterLanguages');
        if (selectedLanguages.length > 0) {
            searchData.filters = { languages: selectedLanguages };
        }
        
        // שליחת בקשה
        const response = await fetch('/api/search/global', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(searchData)
        });
        
        const data = await response.json();
        
        if (response.ok && data.success) {
            displaySearchResults(data);
        } else {
            showNotification(data.error || 'אירעה שגיאה בחיפוש', 'error');
        }
        
    } catch (error) {
        console.error('Search error:', error);
        showNotification('אירעה שגיאה בחיפוש', 'error');
    } finally {
        searchBtn.disabled = false;
        searchBtn.innerHTML = originalBtnText;
        hideSuggestions();
    }
}

// הצגת תוצאות חיפוש
function displaySearchResults(data) {
    const container = document.getElementById('searchResultsContainer');
    const info = document.getElementById('searchInfo');
    const results = document.getElementById('searchResults');
    const pagination = document.getElementById('searchPagination');
    
    // הצגת מידע כללי
    info.innerHTML = `
        <div class="alert alert-info">
            נמצאו <strong>${data.total_results}</strong> תוצאות עבור: 
            <strong>"${escapeHtml(data.query)}"</strong>
            (מציג ${data.results.length} תוצאות)
        </div>
    `;
    
    // הצגת תוצאות
    if (data.results.length === 0) {
        results.innerHTML = '<p class="text-muted">לא נמצאו תוצאות התואמות לחיפוש</p>';
    } else {
        results.innerHTML = data.results.map(result => createResultCard(result)).join('');
    }
    
    // עימוד
    createPagination(pagination, data);
    
    // הצגת הקונטיינר
    container.style.display = 'block';
    
    // גלילה לתוצאות
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// יצירת כרטיס תוצאה
function createResultCard(result) {
    const highlightedSnippet = highlightText(result.snippet, result.highlights);
    const fileIcon = getFileIcon(result.language);
    
    return `
        <div class="search-result-card mb-3 p-3 border rounded">
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1">
                    <h6 class="mb-1">
                        ${fileIcon}
                        <a href="/file/${result.file_id}" target="_blank">
                            ${escapeHtml(result.file_name)}
                        </a>
                        <span class="badge badge-secondary ml-2">${result.language}</span>
                    </h6>
                    
                    ${result.tags.length > 0 ? `
                        <div class="mb-2">
                            ${result.tags.map(tag => 
                                `<span class="badge badge-info mr-1">${escapeHtml(tag)}</span>`
                            ).join('')}
                        </div>
                    ` : ''}
                    
                    <div class="code-snippet bg-light p-2 rounded">
                        <pre class="mb-0"><code>${highlightedSnippet}</code></pre>
                    </div>
                    
                    ${result.matches && result.matches.length > 0 ? `
                        <small class="text-muted">
                            ${result.matches.length} התאמות 
                            (שורות: ${result.matches.map(m => m.line).join(', ')})
                        </small>
                    ` : ''}
                </div>
                
                <div class="text-right ml-3">
                    <div class="text-muted small">
                        <div>ציון: ${result.score}</div>
                        <div>גודל: ${formatFileSize(result.size)}</div>
                        <div>עדכון: ${formatDate(result.updated_at)}</div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// סימון טקסט שנמצא
function highlightText(text, highlights) {
    if (!text || !highlights || highlights.length === 0) {
        return escapeHtml(text);
    }
    
    let result = escapeHtml(text);
    
    // מיין highlights לפי מיקום בסדר יורד (מהסוף להתחלה)
    highlights.sort((a, b) => b[0] - a[0]);
    
    highlights.forEach(([start, end]) => {
        const before = result.substring(0, start);
        const match = result.substring(start, end);
        const after = result.substring(end);
        result = before + `<mark class="bg-warning">${match}</mark>` + after;
    });
    
    return result;
}

// עימוד
function createPagination(container, data) {
    const totalPages = Math.ceil(data.total_results / data.per_page);
    const currentPage = data.page;
    
    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '<nav><ul class="pagination justify-content-center">';
    
    // כפתור קודם
    html += `
        <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="performGlobalSearch(${currentPage - 1}); return false;">
                <i class="fas fa-chevron-right"></i>
            </a>
        </li>
    `;
    
    // מספרי עמודים
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    
    for (let i = startPage; i <= endPage; i++) {
        html += `
            <li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="performGlobalSearch(${i}); return false;">
                    ${i}
                </a>
            </li>
        `;
    }
    
    // כפתור הבא
    html += `
        <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" onclick="performGlobalSearch(${currentPage + 1}); return false;">
                <i class="fas fa-chevron-left"></i>
            </a>
        </li>
    `;
    
    html += '</ul></nav>';
    container.innerHTML = html;
}

// הצעות אוטומטיות
async function fetchSuggestions(query) {
    try {
        const response = await fetch(`/api/search/suggestions?q=${encodeURIComponent(query)}`);
        const data = await response.json();
        
        if (data.suggestions && data.suggestions.length > 0) {
            showSuggestions(data.suggestions);
        } else {
            hideSuggestions();
        }
    } catch (error) {
        console.error('Suggestions error:', error);
        hideSuggestions();
    }
}

function showSuggestions(suggestions) {
    const container = document.getElementById('searchSuggestions');
    
    container.innerHTML = suggestions.map(suggestion => `
        <a href="#" class="list-group-item list-group-item-action" 
           onclick="selectSuggestion('${escapeHtml(suggestion)}'); return false;">
            <i class="fas fa-search text-muted"></i> ${escapeHtml(suggestion)}
        </a>
    `).join('');
    
    container.style.display = 'block';
}

function hideSuggestions() {
    document.getElementById('searchSuggestions').style.display = 'none';
}

function selectSuggestion(suggestion) {
    document.getElementById('globalSearchInput').value = suggestion;
    hideSuggestions();
    performGlobalSearch();
}

// חיפוש מתקדם
function toggleAdvancedSearch() {
    const options = document.getElementById('advancedSearchOptions');
    options.style.display = options.style.display === 'none' ? 'block' : 'none';
}

// ניקוי חיפוש
function clearSearch() {
    document.getElementById('globalSearchInput').value = '';
    document.getElementById('searchResultsContainer').style.display = 'none';
    currentSearchQuery = '';
    currentSearchPage = 1;
}

// פונקציות עזר
function getSelectedValues(selectId) {
    const select = document.getElementById(selectId);
    if (!select) return [];
    
    return Array.from(select.selectedOptions).map(option => option.value);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getFileIcon(language) {
    const icons = {
        'python': '🐍',
        'javascript': '📜',
        'java': '☕',
        'cpp': '⚙️',
        'html': '🌐',
        'css': '🎨',
        'sql': '🗄️',
        'json': '📋',
        'xml': '📄',
        'markdown': '📝'
    };
    return icons[language.toLowerCase()] || '📄';
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('he-IL', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function showNotification(message, type = 'info') {
    // אם יש מערכת התראות קיימת
    if (typeof toastr !== 'undefined') {
        toastr[type](message);
    } else {
        alert(message);
    }
}
```

#### 2.3 הוספת סגנונות CSS

**קובץ חדש:** `webapp/static/css/global_search.css`

```css
/* סגנונות לחיפוש גלובלי */

/* תיבת חיפוש */
#globalSearchInput {
    font-size: 16px;
    padding: 10px 15px;
}

#globalSearchInput:focus {
    box-shadow: 0 0 0 0.2rem rgba(0,123,255,.25);
}

/* הצעות אוטומטיות */
#searchSuggestions {
    max-height: 300px;
    overflow-y: auto;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    margin-top: 2px;
    border-radius: 4px;
}

#searchSuggestions .list-group-item {
    padding: 8px 15px;
    cursor: pointer;
    border-left: none;
    border-right: none;
}

#searchSuggestions .list-group-item:hover {
    background-color: #f8f9fa;
}

#searchSuggestions .list-group-item:first-child {
    border-top: none;
}

/* כרטיס תוצאה */
.search-result-card {
    transition: all 0.3s ease;
    background: white;
}

.search-result-card:hover {
    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    transform: translateY(-2px);
}

.search-result-card h6 a {
    color: #007bff;
    text-decoration: none;
    font-weight: 600;
}

.search-result-card h6 a:hover {
    text-decoration: underline;
}

/* קטע קוד */
.code-snippet {
    font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
    font-size: 13px;
    max-height: 200px;
    overflow: auto;
    position: relative;
}

.code-snippet pre {
    white-space: pre-wrap;
    word-wrap: break-word;
}

.code-snippet mark {
    background-color: #ffeb3b;
    color: #000;
    padding: 2px 4px;
    border-radius: 2px;
    font-weight: bold;
}

/* אפשרויות מתקדמות */
#advancedSearchOptions {
    background-color: #f8f9fa;
    padding: 15px;
    border-radius: 4px;
    margin-top: 15px;
}

#advancedSearchOptions label {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 5px;
    color: #495057;
}

/* עימוד */
.pagination {
    margin-top: 20px;
}

.pagination .page-link {
    color: #007bff;
    border-color: #dee2e6;
}

.pagination .page-item.active .page-link {
    background-color: #007bff;
    border-color: #007bff;
}

.pagination .page-item.disabled .page-link {
    color: #6c757d;
    background-color: #fff;
}

/* אנימציה לטעינה */
@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}

.fa-spin {
    animation: spin 1s linear infinite;
}

/* תמיכה ב-Dark Mode */
@media (prefers-color-scheme: dark) {
    .search-result-card {
        background: #2b2b2b;
        color: #e0e0e0;
    }
    
    .code-snippet {
        background-color: #1e1e1e !important;
        color: #d4d4d4;
    }
    
    #advancedSearchOptions {
        background-color: #2b2b2b;
        color: #e0e0e0;
    }
    
    .search-result-card h6 a {
        color: #4db8ff;
    }
}

/* רספונסיביות */
@media (max-width: 768px) {
    #advancedSearchOptions .row {
        flex-direction: column;
    }
    
    #advancedSearchOptions .col-md-3 {
        margin-bottom: 10px;
    }
    
    .search-result-card {
        padding: 10px !important;
    }
    
    .search-result-card .d-flex {
        flex-direction: column;
    }
    
    .search-result-card .text-right {
        text-align: left !important;
        margin-left: 0 !important;
        margin-top: 10px;
    }
}
```

### שלב 3: הוספת הקובצים לתבנית הבסיס

**קובץ:** `webapp/templates/base.html`

**מיקום:** בתוך ה-`<head>`

```html
<!-- CSS לחיפוש גלובלי -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/global_search.css') }}">
```

**מיקום:** לפני סגירת `</body>`

```html
<!-- JavaScript לחיפוש גלובלי -->
<script src="{{ url_for('static', filename='js/global_search.js') }}"></script>
```

### שלב 4: אופטימיזציות וביצועים

#### 4.1 עדכון אינדקס אוטומטי

**קובץ:** `webapp/app.py`

**הוספה בפונקציות upload וedit:**

```python
def invalidate_search_index(user_id):
    """מחיקת אינדקס חיפוש לאחר שינוי בקבצים"""
    if hasattr(search_engine, 'indexes') and user_id in search_engine.indexes:
        del search_engine.indexes[user_id]

# בסוף פונקציית upload_file:
invalidate_search_index(user_id)

# בסוף פונקציית edit_file_page (אחרי שמירה מוצלחת):
invalidate_search_index(user_id)

# בסוף פונקציית delete_file:
invalidate_search_index(user_id)
```

#### 4.2 Caching לשיפור ביצועים

```python
from functools import lru_cache
from datetime import datetime, timedelta

# Cache לתוצאות חיפוש
search_cache = {}

def get_cached_search(user_id, cache_key):
    """בדיקת cache לחיפוש"""
    if user_id not in search_cache:
        return None
    
    cached = search_cache[user_id].get(cache_key)
    if not cached:
        return None
    
    # בדוק אם פג תוקף (5 דקות)
    if datetime.now() - cached['time'] > timedelta(minutes=5):
        del search_cache[user_id][cache_key]
        return None
    
    return cached['results']

def set_cached_search(user_id, cache_key, results):
    """שמירת תוצאות ב-cache"""
    if user_id not in search_cache:
        search_cache[user_id] = {}
    
    search_cache[user_id][cache_key] = {
        'time': datetime.now(),
        'results': results
    }
```

### שלב 5: בדיקות

#### 5.1 בדיקות יחידה

**קובץ חדש:** `tests/test_global_search.py`

```python
import pytest
from webapp.app import app
from search_engine import search_engine, SearchType

class TestGlobalSearch:
    
    def test_search_endpoint_requires_login(self, client):
        """בדיקה שה-endpoint דורש התחברות"""
        response = client.post('/api/search/global', 
                              json={'query': 'test'})
        assert response.status_code == 401
    
    def test_search_with_empty_query(self, client, logged_in_user):
        """בדיקת חיפוש עם שאילתה ריקה"""
        response = client.post('/api/search/global', 
                              json={'query': ''})
        assert response.status_code == 400
        assert 'error' in response.json
    
    def test_successful_search(self, client, logged_in_user, sample_files):
        """בדיקת חיפוש מוצלח"""
        response = client.post('/api/search/global',
                              json={'query': 'function'})
        assert response.status_code == 200
        data = response.json
        assert 'results' in data
        assert 'total_results' in data
    
    def test_search_with_filters(self, client, logged_in_user, sample_files):
        """בדיקת חיפוש עם פילטרים"""
        response = client.post('/api/search/global',
                              json={
                                  'query': 'test',
                                  'filters': {
                                      'languages': ['python']
                                  }
                              })
        assert response.status_code == 200
        data = response.json
        # בדוק שכל התוצאות הן Python
        for result in data['results']:
            assert result['language'] == 'python'
    
    def test_search_pagination(self, client, logged_in_user, many_files):
        """בדיקת עימוד בתוצאות"""
        # עמוד ראשון
        response1 = client.post('/api/search/global',
                               json={'query': 'code', 'page': 1, 'limit': 10})
        data1 = response1.json
        
        # עמוד שני
        response2 = client.post('/api/search/global',
                               json={'query': 'code', 'page': 2, 'limit': 10})
        data2 = response2.json
        
        # ודא שהתוצאות שונות
        assert data1['results'][0]['file_id'] != data2['results'][0]['file_id']
```

#### 5.2 בדיקות אינטגרציה

```python
def test_full_search_flow():
    """בדיקת תהליך חיפוש מלא"""
    # 1. העלה קובץ
    # 2. בצע חיפוש
    # 3. ודא שהקובץ נמצא
    # 4. ערוך קובץ
    # 5. בצע חיפוש חדש
    # 6. ודא שהשינויים משתקפים
    pass
```

### שלב 6: תיעוד למשתמש

#### הוספת הסבר בעמוד העזרה

```html
<h3>חיפוש גלובלי בקבצים</h3>
<p>המערכת מאפשרת חיפוש מהיר וחכם בכל הקבצים שלך:</p>

<h4>סוגי חיפוש:</h4>
<ul>
    <li><strong>חיפוש תוכן:</strong> מחפש את הטקסט המדויק בתוכן הקבצים</li>
    <li><strong>חיפוש טקסט:</strong> מחפש מילים בודדות עם התאמה חלקית</li>
    <li><strong>ביטוי רגולרי:</strong> חיפוש מתקדם עם regex</li>
    <li><strong>חיפוש מטושטש:</strong> מוצא התאמות דומות (לא מדויקות)</li>
    <li><strong>שמות פונקציות:</strong> מחפש הגדרות פונקציות בקוד</li>
</ul>

<h4>טיפים לחיפוש יעיל:</h4>
<ul>
    <li>השתמש במרכאות לחיפוש ביטוי מדויק: "user login"</li>
    <li>השתמש ב-* לחיפוש wildcard: user*</li>
    <li>סנן לפי שפת תכנות להקטנת התוצאות</li>
    <li>מיין לפי תאריך למציאת קבצים עדכניים</li>
</ul>

<h4>קיצורי מקלדת:</h4>
<ul>
    <li><kbd>Ctrl</kbd> + <kbd>K</kbd> - פתח חיפוש מהיר</li>
    <li><kbd>Enter</kbd> - בצע חיפוש</li>
    <li><kbd>Esc</kbd> - סגור חיפוש</li>
</ul>
```

## בדיקות קבלה (Acceptance Criteria)

- [ ] ניתן לחפש טקסט בכל הקבצים
- [ ] תוצאות מוצגות עם קטעי תצוגה מקדימה
- [ ] הטקסט שנמצא מודגש בתוצאות
- [ ] ניתן לסנן לפי שפת תכנות
- [ ] ניתן למיין תוצאות (רלוונטיות/תאריך/שם)
- [ ] עימוד עובד לתוצאות רבות
- [ ] הצעות אוטומטיות מופיעות בזמן הקלדה
- [ ] ניתן לחפש עם ביטויים רגולריים
- [ ] האינדקס מתעדכן אוטומטית בשינוי קבצים
- [ ] ביצועים סבירים גם עם מאות קבצים

## שיקולי ביצועים

### מגבלות מומלצות:
- מקסימום 1000 קבצים לסריקה בחיפוש
- מקסימום 100 תוצאות בעמוד
- זמן תגובה מקסימלי: 3 שניות
- גודל אינדקס מקסימלי: 50MB למשתמש

### אופטימיזציות:
- שימוש באינדקס מילים לחיפוש מהיר
- Cache לתוצאות חיפוש נפוצות
- Lazy loading לקבצים גדולים
- דחיסת אינדקס בזיכרון

## אבטחה

### בדיקות קלט:
- סניטציה של query למניעת XSS
- הגבלת אורך query ל-500 תווים
- מניעת ReDoS בביטויים רגולריים
- Rate limiting לבקשות חיפוש

### הרשאות:
- בדיקת user_id בכל בקשה
- מניעת גישה לקבצים של משתמשים אחרים
- לוג לכל פעולות החיפוש

## תוספות עתידיות אפשריות

1. **חיפוש סמנטי** - שימוש ב-embeddings לחיפוש לפי משמעות
2. **חיפוש בהיסטוריה** - חיפוש בגרסאות קודמות של קבצים
3. **חיפוש מתקדם עם אופרטורים** - AND, OR, NOT
4. **שמירת חיפושים** - חיפושים שמורים ומועדפים
5. **חיפוש קולי** - הכתבה קולית לחיפוש
6. **חיפוש בתמונות** - OCR לקבצי תמונה
7. **אינטגרציה עם IDE** - plugin ל-VSCode
8. **חיפוש חכם** - הצעות על סמך היסטוריית חיפושים

## סיכום

הפיצ'ר מוסיף ערך משמעותי למערכת ומאפשר למשתמשים למצוא במהירות קוד וטקסט בכל הקבצים שלהם. המימוש מנצל את התשתית הקיימת של מנוע החיפוש ומוסיף רק את השכבות החסרות של API וממשק משתמש.

זמן פיתוח משוער: 2-3 ימים
מורכבות: בינונית
השפעה: גבוהה
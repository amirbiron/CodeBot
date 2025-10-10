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

### שלב 1: הוספת Dependencies וImports

**קובץ:** `webapp/requirements.txt`

**הוספת תלויות נוספות:**
```txt
flask-limiter==3.5.0  # Rate limiting
tenacity==8.2.3  # Retry logic
prometheus-client==0.19.0  # Metrics
sentry-sdk[flask]==1.39.1  # Error monitoring (אופציונלי)
```

**קובץ:** `webapp/app.py`

**Imports בראש הקובץ:**
```python
from search_engine import search_engine, SearchType, SearchFilter, SortOrder
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from tenacity import retry, stop_after_attempt, wait_exponential
from prometheus_client import Counter, Histogram, Gauge, generate_latest
import time
import hashlib

# Optional: Sentry integration
try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    SENTRY_ENABLED = True
except ImportError:
    SENTRY_ENABLED = False
```

### שלב 2: הגדרת Rate Limiting ו-Metrics

**קובץ:** `webapp/app.py`

**אחרי יצירת ה-app instance:**
```python
# Rate Limiting Configuration
limiter = Limiter(
    app=app,
    key_func=lambda: session.get('user_id') if 'user_id' in session else get_remote_address(),
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)

# Prometheus Metrics
search_counter = Counter('search_requests_total', 'Total number of search requests', ['search_type', 'status'])
search_duration = Histogram('search_duration_seconds', 'Search request duration in seconds')
search_results_count = Histogram('search_results_count', 'Number of results returned')
cache_hits = Counter('search_cache_hits_total', 'Total number of cache hits')
cache_misses = Counter('search_cache_misses_total', 'Total number of cache misses')
active_indexes = Gauge('search_active_indexes', 'Number of active search indexes')

# Optional: Sentry Configuration
if SENTRY_ENABLED and config.SENTRY_DSN:
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1,
        environment=config.ENVIRONMENT
    )
```

### שלב 3: מימוש API Endpoint מתקדם

**קובץ:** `webapp/app.py`

**מיקום:** אחרי שאר ה-API endpoints

```python
# Helper function for safe search with retry logic
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry_error_callback=lambda retry_state: logger.warning(f"Search retry attempt {retry_state.attempt_number}")
)
def safe_search(user_id, query, **kwargs):
    """ביצוע חיפוש עם retry logic ו-circuit breaker"""
    return search_engine.search(user_id, query, **kwargs)

@app.route('/api/search/global', methods=['POST'])
@login_required
@limiter.limit("30 per minute")  # הגבלה ספציפית לחיפוש
def global_content_search():
    """חיפוש גלובלי בתוכן כל הקבצים עם monitoring ו-error handling מתקדם"""
    
    start_time = time.time()
    user_id = session['user_id']
    
    try:
        data = request.get_json()
        
        # Dynamic rate limiting based on query length
        query = data.get('query', '').strip()
        if len(query) > 100:
            # הגבלה מחמירה יותר לשאילתות ארוכות
            limiter.limit("5 per minute")(lambda: None)()
        
        # Validation
        if not query:
            search_counter.labels(search_type='invalid', status='error').inc()
            return jsonify({'error': 'נא להזין טקסט לחיפוש'}), 400
        
        if len(query) > 500:
            search_counter.labels(search_type='invalid', status='error').inc()
            return jsonify({'error': 'השאילתה ארוכה מדי (מקסימום 500 תווים)'}), 400
        
        # Parameters
        search_type_str = data.get('search_type', 'content')
        search_types = {
            'content': SearchType.CONTENT,
            'regex': SearchType.REGEX,
            'fuzzy': SearchType.FUZZY,
            'function': SearchType.FUNCTION,
            'text': SearchType.TEXT
        }
        search_type = search_types.get(search_type_str, SearchType.CONTENT)
        
        # Check cache first
        cache_key = hashlib.md5(
            f"{user_id}:{query}:{search_type_str}:{data.get('filters', {})}:{data.get('sort', 'relevance')}".encode()
        ).hexdigest()
        
        cached_results = get_cached_search(user_id, cache_key)
        if cached_results:
            cache_hits.inc()
            search_counter.labels(search_type=search_type_str, status='cache_hit').inc()
            logger.info(f"Cache hit for user {user_id}, query: {query[:50]}")
            return jsonify(cached_results)
        
        cache_misses.inc()
        
        # Filters
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
        
        # Validate regex pattern if regex search
        if search_type == SearchType.REGEX:
            try:
                import re
                re.compile(query)
            except re.error as e:
                search_counter.labels(search_type='regex', status='invalid_pattern').inc()
                return jsonify({'error': f'ביטוי רגולרי לא תקין: {str(e)}'}), 400
        
        # Sorting
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
        
        # Pagination
        page = max(1, data.get('page', 1))
        limit = min(100, data.get('limit', 50))
        
        # Execute search with retry logic
        try:
            results = safe_search(
                user_id=user_id,
                query=query,
                search_type=search_type,
                filters=filters,
                sort_order=sort_order,
                limit=min(1000, limit * page)  # Cap total results
            )
        except Exception as search_error:
            # Log to Sentry if available
            if SENTRY_ENABLED:
                with sentry_sdk.push_scope() as scope:
                    scope.set_user({"id": user_id})
                    scope.set_context("search", {
                        "query": query,
                        "type": search_type_str,
                        "filters": filter_data
                    })
                    sentry_sdk.capture_exception(search_error)
            
            search_counter.labels(search_type=search_type_str, status='error').inc()
            logger.error(f"Search failed for user {user_id}: {search_error}")
            raise
        
        # Update metrics
        search_results_count.observe(len(results))
        active_indexes.set(len(search_engine.indexes))
        
        # Paginate results
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_results = results[start_idx:end_idx]
        
        # Convert to JSON
        response_data = {
            'success': True,
            'query': query,
            'total_results': len(results),
            'page': page,
            'per_page': limit,
            'search_time': round(time.time() - start_time, 3),
            'cached': False,
            'results': [
                {
                    'file_id': hashlib.md5(f"{user_id}:{r.file_name}".encode()).hexdigest(),
                    'file_name': r.file_name,
                    'language': r.programming_language,
                    'tags': r.tags,
                    'score': round(r.relevance_score, 2),
                    'snippet': r.snippet_preview[:200] if r.snippet_preview else '',
                    'highlights': r.highlight_ranges,
                    'matches': r.matches[:5] if r.matches else [],
                    'updated_at': r.updated_at.isoformat(),
                    'size': len(r.content)
                }
                for r in paginated_results
            ]
        }
        
        # Cache the results
        set_cached_search(user_id, cache_key, response_data)
        
        # Log successful search
        search_counter.labels(search_type=search_type_str, status='success').inc()
        logger.info(f"Search completed for user {user_id}: {len(results)} results in {response_data['search_time']}s")
        
        return jsonify(response_data)
        
    except Exception as e:
        search_counter.labels(search_type='unknown', status='error').inc()
        
        # Enhanced error logging
        error_context = {
            'user_id': user_id,
            'query': query[:100] if 'query' in locals() else 'N/A',
            'search_type': search_type_str if 'search_type_str' in locals() else 'N/A',
            'error': str(e),
            'traceback': traceback.format_exc()
        }
        logger.error(f"Global search error: {error_context}")
        
        # Send to Sentry if available
        if SENTRY_ENABLED:
            sentry_sdk.capture_exception(e)
        
        return jsonify({'error': 'אירעה שגיאה בחיפוש', 'details': str(e) if app.debug else None}), 500
        
    finally:
        # Record search duration
        search_duration.observe(time.time() - start_time)


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

## שלב 7: הוספת Health Check ו-Monitoring Endpoints

**קובץ:** `webapp/app.py`

```python
@app.route('/api/search/health', methods=['GET'])
def search_health_check():
    """בדיקת תקינות מנוע החיפוש - endpoint ציבורי לmonitoring"""
    try:
        # Test basic search engine functionality
        test_user_id = -1  # Special test user ID
        
        # Check if search engine is responsive
        search_engine.get_index(test_user_id)
        
        # Check metrics collection
        metrics_ok = search_counter._value is not None
        
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'checks': {
                'search_engine': 'ok',
                'metrics': 'ok' if metrics_ok else 'degraded',
                'cache': 'ok' if len(search_cache) < 1000 else 'warning',  # Warn if cache is too large
                'indexes': len(search_engine.indexes)
            }
        }
        
        return jsonify(health_status), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.now().isoformat(),
            'error': str(e)
        }), 503

@app.route('/metrics')
def metrics_endpoint():
    """Prometheus metrics endpoint"""
    # Update gauge metrics
    active_indexes.set(len(search_engine.indexes))
    
    # Generate Prometheus format metrics
    return generate_latest(), 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/admin/search/stats')
@login_required
@admin_required  # הוסף decorator למנהלים בלבד
def search_statistics():
    """דף סטטיסטיקות חיפוש למנהלים"""
    if not session.get('is_admin'):
        return redirect(url_for('index'))
    
    # Calculate statistics
    total_searches = sum(search_counter._samples())
    cache_hit_rate = 0
    if total_searches > 0:
        cache_hit_rate = (cache_hits._value / total_searches) * 100 if cache_hits._value else 0
    
    avg_search_time = 0
    if search_duration._count:
        avg_search_time = search_duration._sum / search_duration._count
    
    stats = {
        'total_searches': total_searches,
        'searches_today': search_counter._value,  # Reset daily
        'cache_hit_rate': round(cache_hit_rate, 2),
        'avg_search_time': round(avg_search_time, 3),
        'active_indexes': len(search_engine.indexes),
        'cache_size': len(search_cache),
        'top_queries': get_top_queries(),  # Implement if needed
        'search_types_distribution': get_search_types_distribution(),
        'errors_count': search_counter.labels(search_type='unknown', status='error')._value
    }
    
    return render_template('admin/search_stats.html', stats=stats)

def get_top_queries(limit=10):
    """Get most popular search queries"""
    # This would need a separate tracking mechanism
    # For now, return empty list
    return []

def get_search_types_distribution():
    """Get distribution of search types used"""
    distribution = {}
    for search_type in ['content', 'regex', 'fuzzy', 'function', 'text']:
        count = search_counter.labels(search_type=search_type, status='success')._value
        if count:
            distribution[search_type] = count
    return distribution
```

### שלב 8: תבנית HTML לדף הסטטיסטיקות

**קובץ חדש:** `webapp/templates/admin/search_stats.html`

```html
{% extends "base.html" %}

{% block title %}סטטיסטיקות חיפוש - מנהל{% endblock %}

{% block content %}
<div class="container mt-4">
    <h2>📊 סטטיסטיקות מערכת החיפוש</h2>
    
    <div class="row mt-4">
        <!-- כרטיסי סטטיסטיקה -->
        <div class="col-md-3">
            <div class="card text-center">
                <div class="card-body">
                    <h5 class="card-title">סה"כ חיפושים</h5>
                    <h2 class="text-primary">{{ stats.total_searches }}</h2>
                </div>
            </div>
        </div>
        
        <div class="col-md-3">
            <div class="card text-center">
                <div class="card-body">
                    <h5 class="card-title">Cache Hit Rate</h5>
                    <h2 class="text-success">{{ stats.cache_hit_rate }}%</h2>
                </div>
            </div>
        </div>
        
        <div class="col-md-3">
            <div class="card text-center">
                <div class="card-body">
                    <h5 class="card-title">זמן חיפוש ממוצע</h5>
                    <h2 class="text-info">{{ stats.avg_search_time }}s</h2>
                </div>
            </div>
        </div>
        
        <div class="col-md-3">
            <div class="card text-center">
                <div class="card-body">
                    <h5 class="card-title">אינדקסים פעילים</h5>
                    <h2 class="text-warning">{{ stats.active_indexes }}</h2>
                </div>
            </div>
        </div>
    </div>
    
    <div class="row mt-4">
        <!-- גרף התפלגות סוגי חיפוש -->
        <div class="col-md-6">
            <div class="card">
                <div class="card-header">
                    <h5>התפלגות סוגי חיפוש</h5>
                </div>
                <div class="card-body">
                    <canvas id="searchTypesChart"></canvas>
                </div>
            </div>
        </div>
        
        <!-- רשימת שאילתות פופולריות -->
        <div class="col-md-6">
            <div class="card">
                <div class="card-header">
                    <h5>שאילתות פופולריות</h5>
                </div>
                <div class="card-body">
                    {% if stats.top_queries %}
                    <ul class="list-group">
                        {% for query in stats.top_queries %}
                        <li class="list-group-item d-flex justify-content-between">
                            <span>{{ query.text }}</span>
                            <span class="badge badge-primary">{{ query.count }}</span>
                        </li>
                        {% endfor %}
                    </ul>
                    {% else %}
                    <p class="text-muted">אין נתונים זמינים</p>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
    
    <!-- מידע נוסף -->
    <div class="row mt-4">
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <h5>מידע מערכת</h5>
                </div>
                <div class="card-body">
                    <dl class="row">
                        <dt class="col-sm-3">גודל Cache</dt>
                        <dd class="col-sm-9">{{ stats.cache_size }} ערכים</dd>
                        
                        <dt class="col-sm-3">שגיאות</dt>
                        <dd class="col-sm-9">
                            <span class="badge badge-danger">{{ stats.errors_count }}</span>
                        </dd>
                        
                        <dt class="col-sm-3">Health Check</dt>
                        <dd class="col-sm-9">
                            <a href="/api/search/health" target="_blank" class="btn btn-sm btn-info">
                                בדוק תקינות
                            </a>
                        </dd>
                        
                        <dt class="col-sm-3">Prometheus Metrics</dt>
                        <dd class="col-sm-9">
                            <a href="/metrics" target="_blank" class="btn btn-sm btn-secondary">
                                צפה ב-Metrics
                            </a>
                        </dd>
                    </dl>
                </div>
            </div>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
// גרף התפלגות סוגי חיפוש
const ctx = document.getElementById('searchTypesChart').getContext('2d');
const searchTypesData = {{ stats.search_types_distribution | tojson }};

new Chart(ctx, {
    type: 'pie',
    data: {
        labels: Object.keys(searchTypesData),
        datasets: [{
            data: Object.values(searchTypesData),
            backgroundColor: [
                '#007bff',
                '#28a745',
                '#ffc107',
                '#dc3545',
                '#6c757d'
            ]
        }]
    },
    options: {
        responsive: true,
        plugins: {
            legend: {
                position: 'bottom'
            }
        }
    }
});

// Auto-refresh every 30 seconds
setTimeout(() => location.reload(), 30000);
</script>
{% endblock %}
```

## בדיקות קבלה (Acceptance Criteria)

### פונקציונליות בסיסית
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

### Production-Ready Features
- [ ] Rate limiting עובד ומונע spam
- [ ] מערכת Cache מפחיתה עומס
- [ ] Retry logic מטפל בכשלים זמניים
- [ ] Error monitoring עם Sentry (אם מוגדר)
- [ ] Prometheus metrics נאספים
- [ ] Health check endpoint זמין
- [ ] דף סטטיסטיקות למנהלים
- [ ] לוגים מפורטים לכל פעולה
- [ ] תמיכה ב-regex validation
- [ ] הגבלת אורך query (500 תווים)

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

## Configuration Template לProduction

**קובץ:** `webapp/config.py`

```python
# Search Configuration
SEARCH_CONFIG = {
    'ENABLE_CACHE': True,
    'CACHE_TTL_SECONDS': 300,  # 5 minutes
    'MAX_CACHE_SIZE': 1000,
    'MAX_QUERY_LENGTH': 500,
    'MAX_RESULTS_PER_PAGE': 100,
    'DEFAULT_RESULTS_PER_PAGE': 20,
    'INDEX_REBUILD_INTERVAL': 1800,  # 30 minutes
    'ENABLE_METRICS': True,
    'ENABLE_HEALTH_CHECK': True,
}

# Rate Limiting Configuration
RATELIMIT_STORAGE_URL = 'redis://localhost:6379'  # Use Redis in production
RATELIMIT_DEFAULT = "200 per day, 50 per hour"
RATELIMIT_SEARCH = "30 per minute"
RATELIMIT_SEARCH_HEAVY = "5 per minute"  # For complex queries

# Monitoring Configuration
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')  # Set via environment variable
PROMETHEUS_ENABLED = True
ENVIRONMENT = os.environ.get('ENV', 'development')  # development/staging/production

# Admin Users (for statistics page)
ADMIN_USER_IDS = [1, 2, 3]  # Replace with actual admin user IDs
```

## Docker Compose לסביבת Production

**קובץ:** `docker-compose.yml`

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "5000:5000"
    environment:
      - FLASK_ENV=production
      - SENTRY_DSN=${SENTRY_DSN}
      - REDIS_URL=redis://redis:6379
    depends_on:
      - redis
      - prometheus
    volumes:
      - ./data:/app/data
    restart: unless-stopped

  redis:
    image: redis:alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    restart: unless-stopped

  prometheus:
    image: prom/prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
    restart: unless-stopped

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-data:/var/lib/grafana
      - ./grafana-dashboards:/etc/grafana/provisioning/dashboards
    depends_on:
      - prometheus
    restart: unless-stopped

volumes:
  redis-data:
  prometheus-data:
  grafana-data:
```

## Prometheus Configuration

**קובץ:** `prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'flask-app'
    static_configs:
      - targets: ['web:5000']
    metrics_path: '/metrics'
```

## Grafana Dashboard JSON

**קובץ:** `grafana-dashboards/search-dashboard.json`

```json
{
  "dashboard": {
    "title": "Search Engine Monitoring",
    "panels": [
      {
        "title": "Search Requests Rate",
        "targets": [
          {
            "expr": "rate(search_requests_total[5m])"
          }
        ]
      },
      {
        "title": "Search Duration",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, search_duration_seconds_bucket)"
          }
        ]
      },
      {
        "title": "Cache Hit Rate",
        "targets": [
          {
            "expr": "rate(search_cache_hits_total[5m]) / (rate(search_cache_hits_total[5m]) + rate(search_cache_misses_total[5m]))"
          }
        ]
      },
      {
        "title": "Active Indexes",
        "targets": [
          {
            "expr": "search_active_indexes"
          }
        ]
      }
    ]
  }
}
```

## סיכום

הפיצ'ר מוסיף ערך משמעותי למערכת ומאפשר למשתמשים למצוא במהירות קוד וטקסט בכל הקבצים שלהם. המימוש כולל:

### רמת הבסיס
- חיפוש גלובלי מלא בכל הקבצים
- תמיכה בסוגי חיפוש מגוונים
- ממשק משתמש אינטואיטיבי
- הצעות אוטומטיות וסינון מתקדם

### רמת Production
- **Rate Limiting** - מניעת ניצול לרעה
- **Caching** - שיפור ביצועים משמעותי
- **Retry Logic** - טיפול בכשלים זמניים
- **Error Monitoring** - מעקב אחר בעיות בזמן אמת
- **Metrics & Monitoring** - ניטור ביצועים מלא
- **Health Checks** - בדיקות תקינות אוטומטיות
- **Admin Dashboard** - ממשק ניהול לסטטיסטיקות

### זמני פיתוח משוערים
- **מימוש בסיסי**: 2-3 ימים
- **תוספות Production**: 1-2 ימים נוספים
- **סה"כ**: 3-5 ימים לפתרון מלא

### מורכבות
- **בסיס**: בינונית
- **Production Features**: בינונית-גבוהה

### השפעה
- **חוויית משתמש**: גבוהה מאוד
- **ביצועים**: שיפור משמעותי עם caching
- **אמינות**: גבוהה מאוד עם monitoring ו-retry logic

המימוש המלא הופך את הפיצ'ר מ"עובד" ל"production-ready" עם כל מה שנדרש למערכת מקצועית ואמינה.
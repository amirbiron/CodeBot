# מדריך מימוש: Modal לתצוגת שגיאות Sentry ללא Runbook

## 📋 תיאור הפיצ'ר

**מטרה:** הוספת כפתור '👁️' ליד המונה של "Missing Runbooks" בלשונית Coverage של Config Radar, שפותח Modal עם טבלה מפורטת של חתימות השגיאה מסנטרי שאין להן Runbook, כולל לינקים ישירים לכל שגיאה בסנטרי.

**מיקום נוכחי:** ב-Coverage tab מופיע:
```
🔴 Missing Runbooks (18)
┌─────────────────┬───────┬────────────┬───────────────────────────────┐
│ alert_type      │ Count │ Last Seen  │ דוגמה                        │
├─────────────────┼───────┼────────────┼───────────────────────────────┤
│ sentry_issue    │ 18    │ ...        │ ...                          │
└─────────────────┴───────┴────────────┴───────────────────────────────┘
```

**התוצאה הרצויה:**
```
🔴 Missing Runbooks (18) [👁️]  ← כפתור חדש
```
לחיצה על הכפתור פותחת Modal עם פירוט של כל השגיאות הספציפיות, כולל לינק ישיר לסנטרי.

---

## 🏗️ ארכיטקטורה נוכחית

### קבצים רלוונטיים

| קובץ | תפקיד |
|------|-------|
| `webapp/templates/settings.html` | UI של Config Radar, כולל Coverage tab |
| `services/observability_dashboard.py` | `build_coverage_report()` - בונה את הדוח |
| `monitoring/alerts_storage.py` | שאילתות לקטלוג ה-alert types |
| `alert_forwarder.py` | `_build_sentry_link()` - בניית לינקים לסנטרי |
| `services/sentry_polling.py` | שמירת נתוני סנטרי (sentry_issue_id, sentry_permalink) |

### זרימת נתונים נוכחית

```
┌─────────────────────────────────────────────────────────────────────┐
│  Sentry Polling                                                      │
│  services/sentry_polling.py                                          │
│  ↓                                                                   │
│  שומר: sentry_issue_id, sentry_permalink, sentry_short_id בdetails  │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  alerts_storage.save_alert()                                         │
│  monitoring/alerts_storage.py                                        │
│  ↓                                                                   │
│  נשמר ב-MongoDB: alerts_log + catalog                               │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  build_coverage_report()                                             │
│  services/observability_dashboard.py                                 │
│  ↓                                                                   │
│  מחזיר: { missing_runbooks: [{alert_type, count, ...}], ... }       │
│  ⚠️ כרגע לא כולל sentry_permalink או רשימת השגיאות הספציפיות        │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  /api/observability/coverage                                         │
│  webapp/app.py                                                       │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  settings.html - Coverage Tab                                        │
│  renderCoverage() → buildCoverageTable()                             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 שלבי המימוש

### שלב 1: הרחבת ה-API להחזרת רשימת שגיאות ספציפיות

#### 1.1 הוספת פונקציה ב-`monitoring/alerts_storage.py`

צור פונקציה חדשה שמחזירה את **כל האלרטים** מסוג מסוים עם הפרטים המלאים:

```python
def fetch_alerts_by_type(
    *,
    alert_type: str,
    limit: int = 100,
    include_details: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch recent alerts of a specific type with Sentry details.
    
    Returns a list of dicts:
      {
        "alert_id": str,
        "ts_dt": datetime,
        "name": str,
        "summary": str,
        "sentry_issue_id": Optional[str],
        "sentry_permalink": Optional[str],
        "sentry_short_id": Optional[str],
      }
    """
    coll = _get_collection()
    if coll is None:
        return []
    
    normalized_type = _safe_str(alert_type, limit=128).lower()
    if not normalized_type:
        return []
    
    try:
        limit_int = max(1, min(500, int(limit)))
    except Exception:
        limit_int = 100
    
    match = {
        "alert_type": {"$regex": f"^{normalized_type}$", "$options": "i"},
        "details.is_drill": {"$ne": True},
    }
    
    projection = {
        "_id": 0,
        "alert_id": 1,
        "ts_dt": 1,
        "name": 1,
        "summary": 1,
    }
    
    if include_details:
        projection["details.sentry_issue_id"] = 1
        projection["details.sentry_permalink"] = 1
        projection["details.sentry_short_id"] = 1
        projection["details.error_signature"] = 1
    
    try:
        cursor = (
            coll.find(match, projection)
            .sort([("ts_dt", -1)])
            .limit(limit_int)
        )
    except Exception:
        return []
    
    out: List[Dict[str, Any]] = []
    for doc in cursor:
        try:
            details = doc.get("details") or {}
            out.append({
                "alert_id": str(doc.get("alert_id") or ""),
                "ts_dt": doc.get("ts_dt"),
                "name": _safe_str(doc.get("name"), limit=128),
                "summary": _safe_str(doc.get("summary"), limit=256),
                "sentry_issue_id": _safe_str(details.get("sentry_issue_id"), limit=64),
                "sentry_permalink": _safe_str(details.get("sentry_permalink"), limit=512),
                "sentry_short_id": _safe_str(details.get("sentry_short_id"), limit=32),
                "error_signature": _safe_str(details.get("error_signature"), limit=128),
            })
        except Exception:
            continue
    return out
```

#### 1.2 הוספת endpoint חדש ב-`webapp/app.py`

הוסף endpoint שמחזיר את השגיאות הספציפיות:

```python
@app.route('/api/observability/alerts-by-type', methods=['GET'])
@login_required
def api_observability_alerts_by_type():
    """Return specific alerts for a given alert_type (e.g., sentry_issue)."""
    if not _require_admin_user():
        return jsonify({'ok': False, 'error': 'admin_only'}), 403
    
    alert_type = request.args.get('alert_type', '').strip().lower()
    if not alert_type:
        return jsonify({'ok': False, 'error': 'missing_alert_type'}), 400
    
    try:
        limit = int(request.args.get('limit') or 100)
    except Exception:
        limit = 100
    limit = max(1, min(500, limit))
    
    try:
        from monitoring import alerts_storage
        rows = alerts_storage.fetch_alerts_by_type(
            alert_type=alert_type,
            limit=limit,
            include_details=True,
        )
        
        # Build Sentry links for alerts without permalink
        from alert_forwarder import _build_sentry_link
        for row in rows:
            if not row.get('sentry_permalink'):
                row['sentry_link'] = _build_sentry_link(
                    direct_url=None,
                    request_id=None,
                    error_signature=row.get('error_signature'),
                )
            else:
                row['sentry_link'] = row.get('sentry_permalink')
            
            # Format timestamp
            if row.get('ts_dt'):
                row['ts_iso'] = row['ts_dt'].isoformat()
        
        return jsonify({
            'ok': True,
            'alert_type': alert_type,
            'count': len(rows),
            'alerts': rows,
        })
    except Exception:
        logger.exception("alerts_by_type_failed")
        return jsonify({'ok': False, 'error': 'internal_error'}), 500
```

---

### שלב 2: הוספת ה-Modal ב-HTML

#### 2.1 הוספת מבנה ה-Modal ב-`settings.html`

הוסף את ה-Modal **מתחת** ל-`</div>` של `configRadarCard` (בסביבות שורה 275):

```html
<!-- Missing Runbooks Detail Modal -->
<div id="missingRunbooksModal" class="radar-modal" hidden>
  <div class="radar-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="missingRunbooksModalTitle">
    <div class="radar-modal__header">
      <h3 id="missingRunbooksModalTitle">👁️ פירוט שגיאות Sentry ללא Runbook</h3>
      <button class="radar-modal__close" type="button" data-modal-close aria-label="סגור">✕</button>
    </div>
    <div class="radar-modal__body" id="missingRunbooksModalBody">
      <div class="radar-empty-state">טוען נתונים...</div>
    </div>
    <div class="radar-modal__footer">
      <button type="button" class="btn btn-secondary" data-modal-close>סגור</button>
    </div>
  </div>
</div>
```

#### 2.2 הוספת סגנונות CSS ל-Modal

הוסף את ה-CSS **בתוך** תג ה-`<style>` הקיים (בסביבות שורה 1130):

```css
/* Missing Runbooks Modal */
.radar-modal {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.7);
  z-index: 3000;
}
.radar-modal[hidden] {
  display: none;
}
.radar-modal__dialog {
  background: rgba(18, 24, 38, 0.97);
  border-radius: 18px;
  max-width: 900px;
  width: 95%;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.radar-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.radar-modal__header h3 {
  margin: 0;
  font-size: 1.15rem;
}
.radar-modal__close {
  background: transparent;
  border: none;
  color: inherit;
  font-size: 1.4rem;
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 0.2s;
}
.radar-modal__close:hover {
  opacity: 1;
}
.radar-modal__body {
  padding: 1rem 1.25rem;
  overflow-y: auto;
  flex: 1;
}
.radar-modal__footer {
  padding: 0.75rem 1.25rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

/* Modal Table Styles */
.radar-modal-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.radar-modal-table th,
.radar-modal-table td {
  padding: 0.6rem 0.75rem;
  text-align: right;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.radar-modal-table th {
  font-weight: 600;
  opacity: 0.85;
  white-space: nowrap;
}
.radar-modal-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.04);
}
.radar-modal-table code {
  font-size: 0.85em;
  background: rgba(255, 255, 255, 0.1);
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}

/* Sentry Link Button */
.sentry-link-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.3rem 0.6rem;
  background: rgba(130, 80, 223, 0.2);
  color: #a78bfa;
  border: 1px solid rgba(130, 80, 223, 0.3);
  border-radius: 6px;
  font-size: 0.8rem;
  text-decoration: none;
  transition: all 0.2s;
}
.sentry-link-btn:hover {
  background: rgba(130, 80, 223, 0.35);
  border-color: rgba(130, 80, 223, 0.5);
}

/* Eye Button for Modal Trigger */
.radar-eye-btn {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: inherit;
  font-size: 1rem;
  cursor: pointer;
  padding: 0.2rem 0.5rem;
  border-radius: 6px;
  margin-right: 0.5rem;
  transition: all 0.2s;
}
.radar-eye-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.3);
}

/* Light theme adjustments */
:root[data-theme="rose-pine-dawn"] .radar-modal__dialog {
  background: rgba(250, 244, 237, 0.98);
  border-color: rgba(0, 0, 0, 0.1);
}
:root[data-theme="rose-pine-dawn"] .radar-modal__header,
:root[data-theme="rose-pine-dawn"] .radar-modal__footer {
  border-color: rgba(0, 0, 0, 0.1);
}
:root[data-theme="rose-pine-dawn"] .sentry-link-btn {
  background: rgba(130, 80, 223, 0.1);
  border-color: rgba(130, 80, 223, 0.2);
}
```

---

### שלב 3: הוספת הלוגיקה ב-JavaScript

#### 3.1 עדכון הפונקציה `buildCoverageTable`

מצא את הפונקציה `buildCoverageTable` (שורה ~1871) ועדכן את הכותרת להוספת כפתור העין:

**לפני:**
```javascript
const buildCoverageTable = (title, rows, kind) => {
  const header = `
    <h4 style="margin: 0.25rem 0 0.6rem;">${escapeHtml(title)} <span class="radar-chip">${escapeHtml(String(rows.length))}</span></h4>
  `;
```

**אחרי:**
```javascript
const buildCoverageTable = (title, rows, kind) => {
  // Add eye button only for "Missing Runbooks" when there are sentry_issue types
  const hasSentryIssues = kind === 'missing' && rows.some(r => r.alert_type === 'sentry_issue');
  const eyeButton = hasSentryIssues
    ? `<button class="radar-eye-btn" type="button" data-show-sentry-details title="צפה בפירוט השגיאות">👁️</button>`
    : '';
  
  const header = `
    <h4 style="margin: 0.25rem 0 0.6rem;">
      ${escapeHtml(title)} 
      <span class="radar-chip">${escapeHtml(String(rows.length))}</span>
      ${eyeButton}
    </h4>
  `;
```

#### 3.2 הוספת פונקציות לניהול ה-Modal

הוסף את הקוד הבא **בתוך** בלוק ה-`initConfigRadar` (אחרי הגדרת `slots`):

```javascript
// Missing Runbooks Modal Logic
const missingRunbooksModal = document.getElementById('missingRunbooksModal');
const missingRunbooksBody = document.getElementById('missingRunbooksModalBody');

const openMissingRunbooksModal = async () => {
  if (!missingRunbooksModal) return;
  missingRunbooksModal.hidden = false;
  missingRunbooksBody.innerHTML = '<div class="radar-empty-state">טוען נתונים מסנטרי...</div>';
  
  try {
    const res = await fetch('/api/observability/alerts-by-type?alert_type=sentry_issue&limit=100', {
      cache: 'no-store',
      credentials: 'same-origin',
    });
    if (!res.ok) throw new Error('request_failed');
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || 'unknown_error');
    
    renderSentryAlertsTable(data.alerts || []);
  } catch (e) {
    missingRunbooksBody.innerHTML = `<div class="radar-empty-state">שגיאה בטעינת נתונים: ${escapeHtml(String(e.message || e))}</div>`;
  }
};

const closeMissingRunbooksModal = () => {
  if (missingRunbooksModal) missingRunbooksModal.hidden = true;
};

const renderSentryAlertsTable = (alerts) => {
  if (!alerts.length) {
    missingRunbooksBody.innerHTML = '<div class="radar-empty-state">לא נמצאו שגיאות סנטרי ללא Runbook</div>';
    return;
  }
  
  // Group by summary/signature for deduplication display
  const grouped = {};
  for (const alert of alerts) {
    const key = alert.summary || alert.name || 'Unknown';
    if (!grouped[key]) {
      grouped[key] = {
        summary: key,
        count: 0,
        sentry_link: alert.sentry_link || alert.sentry_permalink,
        sentry_short_id: alert.sentry_short_id,
        last_seen: alert.ts_iso,
        alerts: [],
      };
    }
    grouped[key].count++;
    grouped[key].alerts.push(alert);
    if (alert.ts_iso > grouped[key].last_seen) {
      grouped[key].last_seen = alert.ts_iso;
    }
  }
  
  const rows = Object.values(grouped).sort((a, b) => b.count - a.count);
  
  const tableRows = rows.map((row) => {
    const summary = escapeHtml(row.summary.length > 80 ? row.summary.slice(0, 77) + '...' : row.summary);
    const shortId = row.sentry_short_id ? escapeHtml(row.sentry_short_id) : '—';
    const lastSeen = row.last_seen ? formatDateTime(row.last_seen) : '—';
    const sentryLink = row.sentry_link
      ? `<a class="sentry-link-btn" href="${escapeHtml(row.sentry_link)}" target="_blank" rel="noopener">
           🔗 פתח בסנטרי
         </a>`
      : '<span class="radar-chip">לא זמין</span>';
    
    return `
      <tr>
        <td><code dir="ltr">${shortId}</code></td>
        <td title="${escapeHtml(row.summary)}">${summary}</td>
        <td>${escapeHtml(String(row.count))}</td>
        <td>${escapeHtml(lastSeen)}</td>
        <td>${sentryLink}</td>
      </tr>
    `;
  }).join('');
  
  missingRunbooksBody.innerHTML = `
    <p style="margin: 0 0 1rem; opacity: 0.85;">
      סה״כ ${escapeHtml(String(alerts.length))} אירועים, ${escapeHtml(String(rows.length))} חתימות ייחודיות
    </p>
    <table class="radar-modal-table">
      <thead>
        <tr>
          <th>Sentry ID</th>
          <th>חתימה / תיאור</th>
          <th>כמות</th>
          <th>נראה לאחרונה</th>
          <th>פעולות</th>
        </tr>
      </thead>
      <tbody>${tableRows}</tbody>
    </table>
  `;
};

// Modal event listeners
if (missingRunbooksModal) {
  missingRunbooksModal.addEventListener('click', (e) => {
    // Close on backdrop click
    if (e.target === missingRunbooksModal) closeMissingRunbooksModal();
  });
  missingRunbooksModal.querySelectorAll('[data-modal-close]').forEach((btn) => {
    btn.addEventListener('click', closeMissingRunbooksModal);
  });
  // ESC key to close
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !missingRunbooksModal.hidden) {
      closeMissingRunbooksModal();
    }
  });
}
```

#### 3.3 הוספת Event Delegation לכפתור העין

הוסף את הקוד הבא **בתוך** הפונקציה `renderCoverage`, **אחרי** שורת `slots.coverage.innerHTML = ...`:

```javascript
// Bind eye button click
const eyeBtn = slots.coverage.querySelector('[data-show-sentry-details]');
if (eyeBtn) {
  eyeBtn.addEventListener('click', openMissingRunbooksModal);
}
```

---

## 🧪 בדיקות

### בדיקת יחידה ל-API החדש

הוסף ב-`tests/test_observability_api.py`:

```python
def test_alerts_by_type_returns_sentry_details(monkeypatch, client):
    """Test that /api/observability/alerts-by-type returns Sentry details."""
    from datetime import datetime, timezone
    
    fake_alerts = [
        {
            "alert_id": "abc123",
            "ts_dt": datetime.now(timezone.utc),
            "name": "Sentry: TEST-1",
            "summary": "NullPointerException in handler",
            "sentry_issue_id": "12345",
            "sentry_permalink": "https://sentry.io/issues/12345",
            "sentry_short_id": "TEST-1",
            "error_signature": None,
        },
    ]
    
    def mock_fetch(*args, **kwargs):
        return fake_alerts
    
    monkeypatch.setattr("monitoring.alerts_storage.fetch_alerts_by_type", mock_fetch)
    
    resp = client.get('/api/observability/alerts-by-type?alert_type=sentry_issue')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    assert data['count'] == 1
    assert data['alerts'][0]['sentry_permalink'] == "https://sentry.io/issues/12345"
```

### בדיקה ידנית

1. **פתח את Config Radar** → לשונית Coverage
2. **ודא שמופיע כפתור 👁️** ליד "Missing Runbooks" (רק אם יש sentry_issue)
3. **לחץ על הכפתור** → Modal נפתח עם טבלה
4. **בדוק שהלינקים עובדים** → פותחים את סנטרי בטאב חדש
5. **בדוק סגירה** → לחיצה על X / על הרקע / ESC סוגרת

---

## 📊 תרשים זרימה מעודכן

```
┌─────────────────────────────────────────────────────────────────────┐
│  User clicks 👁️ button                                              │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  openMissingRunbooksModal()                                          │
│  → fetch('/api/observability/alerts-by-type?alert_type=sentry_issue')│
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  api_observability_alerts_by_type()                                  │
│  webapp/app.py                                                       │
│  ↓                                                                   │
│  alerts_storage.fetch_alerts_by_type(alert_type='sentry_issue')     │
│  ↓                                                                   │
│  Returns: [{alert_id, summary, sentry_permalink, ...}, ...]         │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  renderSentryAlertsTable(alerts)                                     │
│  → Groups by signature                                               │
│  → Builds table with Sentry links                                    │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Modal displays:                                                     │
│  ┌────────────┬────────────────────────┬───────┬──────────┬────────┐│
│  │ Sentry ID  │ חתימה                  │ כמות  │ נראה     │ לינק   ││
│  ├────────────┼────────────────────────┼───────┼──────────┼────────┤│
│  │ PROJ-123   │ NullPointerException   │ 5     │ 10:30    │ 🔗     ││
│  │ PROJ-456   │ ConnectionTimeout      │ 3     │ 09:15    │ 🔗     ││
│  └────────────┴────────────────────────┴───────┴──────────┴────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔐 שיקולי אבטחה

1. **הרשאות Admin** – ה-endpoint `/api/observability/alerts-by-type` דורש `@login_required` + `_require_admin_user()`
2. **Sanitization** – כל הנתונים עוברים `escapeHtml()` לפני הצגה
3. **Links** – משתמשים ב-`rel="noopener"` על לינקים חיצוניים
4. **Limit** – מגבלה של 500 תוצאות למניעת עומס

---

## 📝 הערות נוספות

### התאמה לנתונים קיימים

- אם `sentry_permalink` לא קיים (אלרטים ישנים), הקוד משתמש ב-`_build_sentry_link()` לבניית לינק מ-`error_signature`
- אם אף לינק לא זמין, מוצג "לא זמין"

### הרחבות עתידיות אפשריות

1. **פילטרים** – הוספת חיפוש/סינון בתוך ה-Modal
2. **Pagination** – טעינת דפים אם יש הרבה שגיאות
3. **Export** – כפתור לייצוא ל-CSV
4. **Bulk Actions** – יצירת Runbook לקבוצת שגיאות במכה אחת

---

## ✅ צ'קליסט למימוש

- [ ] הוספת `fetch_alerts_by_type()` ב-`monitoring/alerts_storage.py`
- [ ] הוספת endpoint `/api/observability/alerts-by-type` ב-`webapp/app.py`
- [ ] הוספת מבנה HTML של ה-Modal ב-`settings.html`
- [ ] הוספת CSS ל-Modal ב-`settings.html`
- [ ] עדכון `buildCoverageTable()` להוספת כפתור 👁️
- [ ] הוספת פונקציות JS לניהול ה-Modal
- [ ] הוספת binding לכפתור העין
- [ ] בדיקת יחידה ל-API
- [ ] בדיקה ידנית מקצה לקצה
- [ ] עדכון תיעוד (אופציונלי)

---

*נוצר על ידי Cursor Agent • תאריך: December 2024*

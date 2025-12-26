# מדריך מימוש: מערכת תיוג ידני להתראות (Alert Tagging)

> **תאריך:** דצמבר 2025  
> **עדכון אחרון:** דצמבר 2025 – תמיכה בתיוג גלובלי 🆕  
> **סטטוס:** מדריך טכני למימוש  
> **קבצים רלוונטיים:** `admin_observability.html`, `observability_dashboard.py`, `alert_tags_storage.py`

---

## תוכן עניינים

1. [סקירת הפיצ'ר](#סקירת-הפיצ'ר)
2. [שלב 1: מודל מסד הנתונים (DB Model)](#שלב-1-מודל-מסד-הנתונים)
3. [שלב 2: Flask API](#שלב-2-flask-api)
4. [שלב 3: Frontend & JavaScript](#שלב-3-frontend--javascript)
5. [שלב 4: תיוג גלובלי לפי סוג התראה](#שלב-4-תיוג-גלובלי-לפי-סוג-התראה) 🆕
6. [בדיקות](#בדיקות)
7. [שיקולי ביצועים](#שיקולי-ביצועים)
8. [שיקולי אבטחה ובאגים נפוצים](#שיקולי-אבטחה-ובאגים-נפוצים)

---

## סקירת הפיצ'ר

### מטרה
לאפשר למשתמשים לתייג התראות (Alerts) בטבלת ההיסטוריה בדשבורד Observability, כדי לסווג, לסנן ולחפש אירועים בקלות.

### שני סוגי תיוג

| סוג | תיאור | שימוש |
|-----|-------|-------|
| **תיוג ספציפי (Instance)** | תגיות על מופע בודד של התראה לפי `alert_uid` | ברירת מחדל |
| **תיוג גלובלי (Type)** 🆕 | תגיות קבועות לכל ההתראות עם אותו שם | כשמסמנים "החל באופן קבוע" |

> **💡 דוגמה:** תייג "CPU High" כ-"Infrastructure" פעם אחת, וכל התראה עתידית (או קיימת) עם אותו שם תקבל את התגית אוטומטית!

### דרישות מוצר
| דרישה | תיאור |
|--------|--------|
| **DB** | שמירת תגיות ב-Collection נפרד (`alert_tags`) עם קישור ל-`alert_uid` + `timestamp` (כדי שישרדו Log Rotation) |
| **UI** | עמודת "Tags" בטבלה, הצגת תגיות כ-Badges צבעוניים, וכפתור `+` להוספה |
| **UX** | Modal/Popover עם Autocomplete לתגיות קיימות + צ'קבוקס לתיוג גלובלי 🆕 |
| **API** | מסלולים ל-POST (שמירה) ו-GET (הצעות/שליפה) + Endpoint לתגיות גלובליות 🆕 |

---

## שלב 1: מודל מסד הנתונים

### 1.1 סכמת Collection: `alert_tags`

צור קובץ חדש או הוסף ל-`monitoring/__init__.py`:

```python
# monitoring/alert_tags_storage.py
"""
Alert Tags Storage - שמירת תגיות ידניות להתראות.

Collection: alert_tags
מבנה מסמך:
{
    "_id": ObjectId,
    "alert_uid": str,           # מזהה ייחודי של ההתראה
    "alert_timestamp": datetime, # זמן ההתראה המקורית (לשרידות log rotation)
    "tags": [str],              # רשימת תגיות
    "created_at": datetime,
    "updated_at": datetime,
    "created_by": int           # user_id (אופציונלי)
}

אינדקסים:
- alert_uid (unique)
- tags (לחיפוש לפי תגית)
- alert_timestamp (לשאילתות לפי טווח זמן)
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# הפניה ל-DB (יש להתאים לפי הארכיטקטורה הקיימת)
_db = None  # type: ignore

def _get_collection():
    """מחזיר את ה-collection של alert_tags."""
    global _db
    if _db is None:
        from database.manager import get_database
        _db = get_database()
    return _db["alert_tags"]


def ensure_indexes() -> None:
    """יצירת אינדקסים נדרשים."""
    coll = _get_collection()
    coll.create_index("alert_uid", unique=True)
    coll.create_index("tags")
    coll.create_index("alert_timestamp")
    coll.create_index([("tags", 1), ("alert_timestamp", -1)])
    logger.info("alert_tags indexes ensured")


def get_tags_for_alert(alert_uid: str) -> List[str]:
    """מחזיר תגיות עבור התראה ספציפית."""
    if not alert_uid:
        return []
    doc = _get_collection().find_one({"alert_uid": alert_uid})
    return doc.get("tags", []) if doc else []


def get_tags_for_alerts(alert_uids: List[str]) -> Dict[str, List[str]]:
    """מחזיר מיפוי של alert_uid -> tags עבור רשימת התראות."""
    if not alert_uids:
        return {}
    cursor = _get_collection().find({"alert_uid": {"$in": alert_uids}})
    return {doc["alert_uid"]: doc.get("tags", []) for doc in cursor}


def set_tags_for_alert(
    alert_uid: str,
    alert_timestamp: datetime,
    tags: List[str],
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """שמירת/עדכון תגיות להתראה."""
    if not alert_uid:
        raise ValueError("alert_uid is required")
    
    # נרמול תגיות: lowercase, ללא רווחים מיותרים, ללא כפילויות
    normalized_tags = list(dict.fromkeys(
        tag.strip().lower() for tag in tags if tag and tag.strip()
    ))
    
    now = datetime.now(timezone.utc)
    
    result = _get_collection().update_one(
        {"alert_uid": alert_uid},
        {
            "$set": {
                "tags": normalized_tags,
                "alert_timestamp": alert_timestamp,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
                "created_by": user_id,
            }
        },
        upsert=True
    )
    
    return {
        "alert_uid": alert_uid,
        "tags": normalized_tags,
        "upserted": result.upserted_id is not None,
        "modified": result.modified_count > 0,
    }


def add_tag_to_alert(
    alert_uid: str,
    alert_timestamp: datetime,
    tag: str,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """הוספת תגית בודדת להתראה (ללא מחיקת קיימות)."""
    if not alert_uid or not tag:
        raise ValueError("alert_uid and tag are required")
    
    normalized_tag = tag.strip().lower()
    if not normalized_tag:
        raise ValueError("tag cannot be empty")
    
    now = datetime.now(timezone.utc)
    
    result = _get_collection().update_one(
        {"alert_uid": alert_uid},
        {
            "$addToSet": {"tags": normalized_tag},
            "$set": {
                "alert_timestamp": alert_timestamp,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
                "created_by": user_id,
            }
        },
        upsert=True
    )
    
    # שליפת התגיות המעודכנות
    updated_tags = get_tags_for_alert(alert_uid)
    
    return {
        "alert_uid": alert_uid,
        "tags": updated_tags,
        "added": normalized_tag,
    }


def remove_tag_from_alert(alert_uid: str, tag: str) -> Dict[str, Any]:
    """הסרת תגית מהתראה."""
    if not alert_uid or not tag:
        raise ValueError("alert_uid and tag are required")
    
    normalized_tag = tag.strip().lower()
    
    result = _get_collection().update_one(
        {"alert_uid": alert_uid},
        {
            "$pull": {"tags": normalized_tag},
            "$set": {"updated_at": datetime.now(timezone.utc)},
        }
    )
    
    updated_tags = get_tags_for_alert(alert_uid)
    
    return {
        "alert_uid": alert_uid,
        "tags": updated_tags,
        "removed": normalized_tag,
        "modified": result.modified_count > 0,
    }


def get_all_tags(limit: int = 100) -> List[Dict[str, Any]]:
    """
    מחזיר רשימת כל התגיות הקיימות עם ספירה.
    משמש ל-Autocomplete.
    """
    pipeline = [
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
        {"$project": {"tag": "$_id", "count": 1, "_id": 0}}
    ]
    return list(_get_collection().aggregate(pipeline))


def search_tags(prefix: str, limit: int = 20) -> List[str]:
    """
    חיפוש תגיות לפי prefix (ל-Autocomplete).
    
    Note: משתמש ב-re.escape() כדי למנוע injection של תווים מיוחדים
    כמו c++, tag(1), [test] וכו'.
    """
    if not prefix:
        return [item["tag"] for item in get_all_tags(limit)]
    
    normalized_prefix = prefix.strip().lower()
    # 🛡️ חשוב: Escape תווים מיוחדים של Regex למניעת שגיאות/תוצאות לא צפויות
    safe_prefix = re.escape(normalized_prefix)
    
    pipeline = [
        {"$unwind": "$tags"},
        {"$match": {"tags": {"$regex": f"^{safe_prefix}", "$options": "i"}}},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    
    results = list(_get_collection().aggregate(pipeline))
    return [doc["_id"] for doc in results]


def get_alerts_by_tag(
    tag: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 100
) -> List[str]:
    """מחזיר רשימת alert_uids שמתויגים בתגית מסוימת."""
    if not tag:
        return []
    
    normalized_tag = tag.strip().lower()
    query: Dict[str, Any] = {"tags": normalized_tag}
    
    if start_time or end_time:
        time_filter: Dict[str, Any] = {}
        if start_time:
            time_filter["$gte"] = start_time
        if end_time:
            time_filter["$lte"] = end_time
        if time_filter:
            query["alert_timestamp"] = time_filter
    
    cursor = _get_collection().find(query, {"alert_uid": 1}).limit(limit)
    return [doc["alert_uid"] for doc in cursor]
```

### 1.2 אתחול אינדקסים

הוסף קריאה ל-`ensure_indexes()` בעת עליית האפליקציה:

```python
# בקובץ הראשי או ב-startup hook
from monitoring.alert_tags_storage import ensure_indexes
ensure_indexes()
```

---

## שלב 2: Flask API

### 2.1 נתיבי API חדשים

הוסף ל-`services/observability_dashboard.py` או צור קובץ נפרד:

```python
# services/observability_dashboard.py - הוספה בסוף הקובץ

# ==========================================
# Alert Tags API
# ==========================================

from monitoring import alert_tags_storage


def get_alert_tags(alert_uid: str) -> Dict[str, Any]:
    """
    GET /api/observability/alerts/<alert_uid>/tags
    מחזיר תגיות עבור התראה ספציפית.
    """
    if not alert_uid:
        return {"ok": False, "error": "missing_alert_uid"}
    
    try:
        tags = alert_tags_storage.get_tags_for_alert(alert_uid)
        return {"ok": True, "alert_uid": alert_uid, "tags": tags}
    except Exception as e:
        logger.exception("get_alert_tags failed: %s", e)
        return {"ok": False, "error": "internal_error"}


def set_alert_tags(
    alert_uid: str,
    alert_timestamp: str,
    tags: List[str],
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    POST /api/observability/alerts/<alert_uid>/tags
    שמירת תגיות להתראה (מחליף את הקיימות).
    
    Body: {"tags": ["tag1", "tag2"], "alert_timestamp": "ISO8601"}
    """
    if not alert_uid:
        return {"ok": False, "error": "missing_alert_uid"}
    if not tags:
        return {"ok": False, "error": "missing_tags"}
    
    try:
        ts = datetime.fromisoformat(alert_timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ts = datetime.now(timezone.utc)
    
    try:
        result = alert_tags_storage.set_tags_for_alert(
            alert_uid=alert_uid,
            alert_timestamp=ts,
            tags=tags,
            user_id=user_id,
        )
        return {"ok": True, **result}
    except ValueError as ve:
        return {"ok": False, "error": str(ve)}
    except Exception as e:
        logger.exception("set_alert_tags failed: %s", e)
        return {"ok": False, "error": "internal_error"}


def add_alert_tag(
    alert_uid: str,
    alert_timestamp: str,
    tag: str,
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    POST /api/observability/alerts/<alert_uid>/tags/add
    הוספת תגית בודדת (ללא מחיקת קיימות).
    
    Body: {"tag": "my-tag", "alert_timestamp": "ISO8601"}
    """
    if not alert_uid:
        return {"ok": False, "error": "missing_alert_uid"}
    if not tag:
        return {"ok": False, "error": "missing_tag"}
    
    try:
        ts = datetime.fromisoformat(alert_timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ts = datetime.now(timezone.utc)
    
    try:
        result = alert_tags_storage.add_tag_to_alert(
            alert_uid=alert_uid,
            alert_timestamp=ts,
            tag=tag,
            user_id=user_id,
        )
        return {"ok": True, **result}
    except ValueError as ve:
        return {"ok": False, "error": str(ve)}
    except Exception as e:
        logger.exception("add_alert_tag failed: %s", e)
        return {"ok": False, "error": "internal_error"}


def remove_alert_tag(alert_uid: str, tag: str) -> Dict[str, Any]:
    """
    DELETE /api/observability/alerts/<alert_uid>/tags/<tag>
    הסרת תגית מהתראה.
    """
    if not alert_uid or not tag:
        return {"ok": False, "error": "missing_params"}
    
    try:
        result = alert_tags_storage.remove_tag_from_alert(alert_uid, tag)
        return {"ok": True, **result}
    except ValueError as ve:
        return {"ok": False, "error": str(ve)}
    except Exception as e:
        logger.exception("remove_alert_tag failed: %s", e)
        return {"ok": False, "error": "internal_error"}


def suggest_tags(prefix: str = "", limit: int = 20) -> Dict[str, Any]:
    """
    GET /api/observability/tags/suggest?q=<prefix>
    הצעות תגיות ל-Autocomplete.
    """
    try:
        suggestions = alert_tags_storage.search_tags(prefix, limit)
        return {"ok": True, "suggestions": suggestions}
    except Exception as e:
        logger.exception("suggest_tags failed: %s", e)
        return {"ok": False, "error": "internal_error", "suggestions": []}


def get_popular_tags(limit: int = 50) -> Dict[str, Any]:
    """
    GET /api/observability/tags/popular
    רשימת תגיות פופולריות עם ספירה.
    """
    try:
        tags = alert_tags_storage.get_all_tags(limit)
        return {"ok": True, "tags": tags}
    except Exception as e:
        logger.exception("get_popular_tags failed: %s", e)
        return {"ok": False, "error": "internal_error", "tags": []}
```

### 2.2 רישום ה-Routes ב-Flask

הוסף ל-`services/webserver.py` (או לקובץ הנתיבים הרלוונטי):

```python
# services/webserver.py - הוספה לאזור נתיבי observability

from services import observability_dashboard as obs_dash


# === Alert Tags Routes ===

@app.route('/api/observability/alerts/<alert_uid>/tags', methods=['GET'])
@admin_required  # או decorator אחר לפי הארכיטקטורה
def api_get_alert_tags(alert_uid: str):
    """שליפת תגיות להתראה."""
    result = obs_dash.get_alert_tags(alert_uid)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/alerts/<alert_uid>/tags', methods=['POST'])
@admin_required
def api_set_alert_tags(alert_uid: str):
    """עדכון כל התגיות להתראה."""
    data = request.get_json() or {}
    user_id = getattr(g, 'user_id', None)  # התאם לפי הארכיטקטורה
    result = obs_dash.set_alert_tags(
        alert_uid=alert_uid,
        alert_timestamp=data.get("alert_timestamp", ""),
        tags=data.get("tags", []),
        user_id=user_id,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/alerts/<alert_uid>/tags/add', methods=['POST'])
@admin_required
def api_add_alert_tag(alert_uid: str):
    """הוספת תגית בודדת."""
    data = request.get_json() or {}
    user_id = getattr(g, 'user_id', None)
    result = obs_dash.add_alert_tag(
        alert_uid=alert_uid,
        alert_timestamp=data.get("alert_timestamp", ""),
        tag=data.get("tag", ""),
        user_id=user_id,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/alerts/<alert_uid>/tags/<tag>', methods=['DELETE'])
@admin_required
def api_remove_alert_tag(alert_uid: str, tag: str):
    """הסרת תגית."""
    result = obs_dash.remove_alert_tag(alert_uid, tag)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@app.route('/api/observability/tags/suggest', methods=['GET'])
@admin_required
def api_suggest_tags():
    """הצעות תגיות (Autocomplete)."""
    prefix = request.args.get("q", "")
    limit = min(int(request.args.get("limit", 20)), 50)
    result = obs_dash.suggest_tags(prefix, limit)
    return jsonify(result)


@app.route('/api/observability/tags/popular', methods=['GET'])
@admin_required
def api_popular_tags():
    """תגיות פופולריות."""
    limit = min(int(request.args.get("limit", 50)), 100)
    result = obs_dash.get_popular_tags(limit)
    return jsonify(result)
```

### 2.3 שילוב תגיות בשליפת התראות

עדכן את פונקציית `get_alerts_history` הקיימת:

```python
# services/observability_dashboard.py - עדכון פונקציה קיימת

def get_alerts_history(...) -> Dict[str, Any]:
    # ... קוד קיים לשליפת alerts ...
    
    alerts = list(cursor)  # שליפת ההתראות
    
    # === הוספה: מיזוג תגיות ===
    alert_uids = [a.get("alert_uid") for a in alerts if a.get("alert_uid")]
    tags_map = alert_tags_storage.get_tags_for_alerts(alert_uids)
    
    for alert in alerts:
        uid = alert.get("alert_uid")
        alert["tags"] = tags_map.get(uid, [])
    # === סוף הוספה ===
    
    return {
        "ok": True,
        "alerts": alerts,
        "total": total,
        # ...
    }
```

---

## שלב 3: Frontend & JavaScript

### 3.1 עדכון ה-HTML: הוספת עמודת Tags

**מיקום:** `webapp/templates/admin_observability.html`

#### 3.1.1 הוספת `<th>` לכותרת הטבלה (שורה ~752)

```html
<!-- עדכון ה-thead של טבלת alertsTable -->
<thead>
  <tr>
    <th>זמן</th>
    <th>שם</th>
    <th>חומרה</th>
    <th>סיכום</th>
    <th>Meta</th>
    <th>Tags</th>           <!-- 👈 עמודה חדשה -->
    <th>גרף</th>
    <th>Quick Fix</th>
    <th>הסבר AI</th>
    <th>סיפור אירוע</th>
  </tr>
</thead>
```

#### 3.1.2 עדכון `colspan` בשורות skeleton ו-empty (אם יש)

```html
<!-- עדכון מ-colspan="9" ל-colspan="10" -->
<tr class="skeleton-row">
  <td colspan="10">
    <!-- ... -->
  </td>
</tr>
```

### 3.2 הוספת CSS לתגיות

הוסף בתוך בלוק `<style>` הקיים (לפני `{% endblock %}`):

```css
/* === Alert Tags Styles === */
.tags-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  align-items: center;
}
.tag-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  background: rgba(100, 255, 218, 0.12);
  color: #64ffda;
  border-radius: 999px;
  padding: 0.15rem 0.5rem;
  font-size: 0.75rem;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tag-badge:hover {
  background: rgba(100, 255, 218, 0.22);
}
.tag-badge .tag-remove {
  cursor: pointer;
  opacity: 0.6;
  font-size: 0.65rem;
  margin-right: 0.15rem;
}
.tag-badge .tag-remove:hover {
  opacity: 1;
  color: #ff627c;
}
.add-tag-btn {
  border: 1px dashed rgba(255,255,255,0.25);
  background: transparent;
  color: rgba(255,255,255,0.6);
  border-radius: 999px;
  width: 22px;
  height: 22px;
  font-size: 0.9rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}
.add-tag-btn:hover {
  border-color: #64ffda;
  color: #64ffda;
  background: rgba(100, 255, 218, 0.08);
}

/* Tag Modal */
.tag-modal {
  position: fixed;
  inset: 0;
  background: rgba(4,6,12,0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 3000;
}
.tag-modal[hidden] { display: none; }
.tag-modal__dialog {
  background: rgba(18,24,38,0.95);
  border-radius: 18px;
  border: 1px solid rgba(255,255,255,0.08);
  width: min(420px, 95vw);
  max-height: 80vh;
  overflow-y: auto;
  padding: 1.25rem;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6);
}
.tag-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}
.tag-modal__header h3 { margin: 0; font-size: 1.1rem; }
.tag-modal__close {
  background: transparent;
  border: none;
  color: #fff;
  font-size: 1.25rem;
  cursor: pointer;
}
.tag-input-wrapper {
  position: relative;
  margin-bottom: 0.75rem;
}
.tag-input {
  width: 100%;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 12px;
  color: #fff;
  padding: 0.5rem 0.75rem;
  font-size: 0.9rem;
}
.tag-input:focus {
  outline: none;
  border-color: #64ffda;
}
.tag-suggestions {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: rgba(18,24,38,0.98);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  margin-top: 0.25rem;
  max-height: 180px;
  overflow-y: auto;
  z-index: 10;
}
.tag-suggestions[hidden] { display: none; }
.tag-suggestion-item {
  padding: 0.45rem 0.75rem;
  cursor: pointer;
  font-size: 0.85rem;
  border-bottom: 1px solid rgba(255,255,255,0.05);
}
.tag-suggestion-item:last-child { border-bottom: none; }
.tag-suggestion-item:hover,
.tag-suggestion-item.selected {
  background: rgba(100, 255, 218, 0.12);
  color: #64ffda;
}
.current-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.75rem;
}
.tag-modal__actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
}
.tag-modal__actions button {
  flex: 1;
  border: none;
  border-radius: 10px;
  padding: 0.45rem 0.9rem;
  cursor: pointer;
  font-weight: 500;
}
.tag-save-btn {
  background: linear-gradient(135deg,#64ffda,#36c2ff);
  color: #08111d;
}
.tag-cancel-btn {
  background: rgba(255,255,255,0.1);
  color: #fff;
}
```

### 3.3 הוספת Modal לתגיות

הוסף לפני סגירת ה-`</div>` הראשי של `.obs-page`:

```html
<!-- Tag Modal -->
<div id="tagModal" class="tag-modal" hidden>
  <div class="tag-modal__dialog" role="dialog" aria-modal="true">
    <div class="tag-modal__header">
      <h3>🏷️ ניהול תגיות</h3>
      <button class="tag-modal__close" type="button" data-tag-close>✕</button>
    </div>
    <div class="tag-input-wrapper">
      <input type="text" class="tag-input" id="tagInput" placeholder="הקלד תגית חדשה..." autocomplete="off">
      <div class="tag-suggestions" id="tagSuggestions" hidden></div>
    </div>
    <div class="current-tags" id="currentTags"></div>
    <div class="tag-modal__actions">
      <button type="button" class="tag-cancel-btn" data-tag-close>ביטול</button>
      <button type="button" class="tag-save-btn" id="tagSaveBtn">שמור</button>
    </div>
  </div>
</div>
```

### 3.4 עדכון JavaScript

הוסף את הקוד הבא בתוך ה-IIFE הקיים (לפני `refreshAll()`):

```javascript
// ==========================================
// Alert Tags System
// ==========================================

const tagModal = document.getElementById('tagModal');
const tagInput = document.getElementById('tagInput');
const tagSuggestions = document.getElementById('tagSuggestions');
const currentTagsEl = document.getElementById('currentTags');
const tagSaveBtn = document.getElementById('tagSaveBtn');

const tagState = {
  alertUid: null,
  alertTimestamp: null,
  tags: [],
  suggestions: [],
  selectedIndex: -1,
};

// --- Render Functions ---

function renderTagsCell(alert) {
  const tags = alert.tags || [];
  const uid = alert.alert_uid || '';
  const ts = alert.timestamp || '';
  
  if (!uid) {
    return '<span style="opacity:0.4;">—</span>';
  }
  
  const payload = encodeURIComponent(JSON.stringify({
    alert_uid: uid,
    timestamp: ts,
    tags: tags,
  }));
  
  const badges = tags.slice(0, 3).map(tag => 
    `<span class="tag-badge" title="${escapeHtml(tag)}">${escapeHtml(tag)}</span>`
  ).join('');
  
  const moreCount = tags.length > 3 ? `<span class="tag-badge">+${tags.length - 3}</span>` : '';
  
  return `
    <div class="tags-cell">
      ${badges}${moreCount}
      <button class="add-tag-btn" data-tags="${payload}" title="ניהול תגיות">+</button>
    </div>
  `;
}

// --- Modal Functions ---

function openTagModal(payload) {
  if (!payload) return;
  try {
    const data = JSON.parse(decodeURIComponent(payload));
    tagState.alertUid = data.alert_uid;
    tagState.alertTimestamp = data.timestamp;
    tagState.tags = [...(data.tags || [])];
    tagState.selectedIndex = -1;
    
    renderCurrentTags();
    tagInput.value = '';
    hideSuggestions();
    
    if (tagModal) tagModal.hidden = false;
    tagInput.focus();
    
    // טעינת הצעות פופולריות
    loadTagSuggestions('');
  } catch (err) {
    console.warn('tag modal parse failed', err);
  }
}

function closeTagModal() {
  if (tagModal) tagModal.hidden = true;
  tagState.alertUid = null;
  tagState.tags = [];
}

function renderCurrentTags() {
  if (!currentTagsEl) return;
  if (!tagState.tags.length) {
    currentTagsEl.innerHTML = '<span style="opacity:0.5; font-size:0.85rem;">אין תגיות עדיין</span>';
    return;
  }
  currentTagsEl.innerHTML = tagState.tags.map(tag => `
    <span class="tag-badge">
      ${escapeHtml(tag)}
      <span class="tag-remove" data-remove-tag="${escapeHtml(tag)}">✕</span>
    </span>
  `).join('');
}

// --- Autocomplete Functions ---

async function loadTagSuggestions(prefix) {
  try {
    const params = new URLSearchParams({ q: prefix, limit: '15' });
    const res = await fetchJson(`/api/observability/tags/suggest?${params.toString()}`);
    if (res.ok !== false) {
      tagState.suggestions = res.suggestions || [];
      renderSuggestions();
    }
  } catch (err) {
    console.debug('tag suggestions failed', err);
  }
}

function renderSuggestions() {
  if (!tagSuggestions) return;
  
  const filtered = tagState.suggestions.filter(s => !tagState.tags.includes(s));
  
  if (!filtered.length) {
    hideSuggestions();
    return;
  }
  
  tagSuggestions.innerHTML = filtered.map((tag, idx) => `
    <div class="tag-suggestion-item${idx === tagState.selectedIndex ? ' selected' : ''}" 
         data-suggestion="${escapeHtml(tag)}">${escapeHtml(tag)}</div>
  `).join('');
  
  tagSuggestions.hidden = false;
}

function hideSuggestions() {
  if (tagSuggestions) tagSuggestions.hidden = true;
  tagState.selectedIndex = -1;
}

function selectSuggestion(tag) {
  if (!tag) return;
  const normalized = tag.trim().toLowerCase();
  if (normalized && !tagState.tags.includes(normalized)) {
    tagState.tags.push(normalized);
    renderCurrentTags();
  }
  tagInput.value = '';
  hideSuggestions();
  tagInput.focus();
}

// --- API Functions ---

async function saveAlertTags() {
  if (!tagState.alertUid) return;
  
  try {
    if (tagSaveBtn) tagSaveBtn.disabled = true;
    
    const res = await fetch(`/api/observability/alerts/${tagState.alertUid}/tags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tags: tagState.tags,
        alert_timestamp: tagState.alertTimestamp,
      }),
    });
    
    const data = await res.json();
    
    if (data.ok === false) {
      showToast('שגיאה בשמירת תגיות');
      return;
    }
    
    showToast('התגיות נשמרו');
    closeTagModal();
    
    // רענון הטבלה
    refreshHistory().catch(() => {});
    
  } catch (err) {
    console.error('save tags failed', err);
    showToast('שגיאה בשמירת תגיות');
  } finally {
    if (tagSaveBtn) tagSaveBtn.disabled = false;
  }
}

// --- Event Handlers ---

function initTagHandlers() {
  // פתיחת Modal
  document.querySelectorAll('.add-tag-btn').forEach(btn => {
    if (btn.dataset.tagBound === '1') return;
    btn.dataset.tagBound = '1';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      openTagModal(btn.dataset.tags);
    });
  });
  
  // הסרת תגית מהרשימה הנוכחית
  // 🛡️ חשוב: Guard למניעת כפילות Listeners (הפונקציה נקראת בכל רענון טבלה)
  if (currentTagsEl) {
    if (currentTagsEl.dataset.listenerAttached === '1') return;
    currentTagsEl.dataset.listenerAttached = '1';
    
    currentTagsEl.addEventListener('click', (e) => {
      const removeBtn = e.target.closest('[data-remove-tag]');
      if (removeBtn) {
        const tagToRemove = removeBtn.dataset.removeTag;
        tagState.tags = tagState.tags.filter(t => t !== tagToRemove);
        renderCurrentTags();
      }
    });
  }
}

// Modal close handlers
if (tagModal) {
  tagModal.addEventListener('click', (e) => {
    if (e.target === tagModal) closeTagModal();
  });
  tagModal.querySelectorAll('[data-tag-close]').forEach(btn => {
    btn.addEventListener('click', closeTagModal);
  });
}

// Save button
if (tagSaveBtn) {
  tagSaveBtn.addEventListener('click', saveAlertTags);
}

// Input handlers
if (tagInput) {
  let debounceTimer;
  
  tagInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      loadTagSuggestions(tagInput.value.trim());
    }, 200);
  });
  
  tagInput.addEventListener('keydown', (e) => {
    const items = tagSuggestions?.querySelectorAll('.tag-suggestion-item') || [];
    
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      tagState.selectedIndex = Math.min(tagState.selectedIndex + 1, items.length - 1);
      renderSuggestions();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      tagState.selectedIndex = Math.max(tagState.selectedIndex - 1, -1);
      renderSuggestions();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (tagState.selectedIndex >= 0 && items[tagState.selectedIndex]) {
        selectSuggestion(items[tagState.selectedIndex].dataset.suggestion);
      } else if (tagInput.value.trim()) {
        selectSuggestion(tagInput.value);
      }
    } else if (e.key === 'Escape') {
      hideSuggestions();
    }
  });
  
  tagInput.addEventListener('blur', () => {
    // עיכוב קל כדי לאפשר לחיצה על הצעות
    setTimeout(hideSuggestions, 150);
  });
}

// Suggestions click handler
if (tagSuggestions) {
  tagSuggestions.addEventListener('click', (e) => {
    const item = e.target.closest('.tag-suggestion-item');
    if (item) {
      selectSuggestion(item.dataset.suggestion);
    }
  });
}
```

### 3.5 עדכון `renderAlertsTable`

מצא את הפונקציה `renderAlertsTable` ועדכן את בניית השורות:

```javascript
// בתוך הפונקציה renderAlertsTable, עדכן את יצירת השורות:

alerts.forEach(alert => {
  const meta = alert.metadata || {};
  const metaItems = Object.keys(meta)
    .slice(0, 3)
    .map(key => `<span>${key}: ${meta[key]}</span>`)
    .join('');
  
  rows.push(`
    <tr data-timestamp="${alert.timestamp || ''}" data-alert-uid="${alert.alert_uid || ''}" class="alert-row">
      <td>${formatTimestamp(alert.timestamp)}</td>
      <td>${alert.name || '-'}</td>
      <td><span class="status-pill ${severityClass(alert.severity)}">${alert.severity || '-'}</span></td>
      <td>${alert.summary || '-'}</td>
      <td><div class="meta-list">${metaItems || ''}</div></td>
      <td>${renderTagsCell(alert)}</td>      <!-- 👈 עמודה חדשה -->
      <td>${renderGraphCell(alert)}</td>
      <td>${renderQuickFixCell(alert)}</td>
      <td>${renderAiExplainCell(alert)}</td>
      <td>${renderStoryCell(alert)}</td>
    </tr>
  `);
  // ... המשך הקוד הקיים ...
});

// בסוף הפונקציה, הוסף קריאה ל-initTagHandlers:
initQuickFixHandlers();
initStoryHandlers();
initVisualContextHandlers();
initAiExplainHandlers();
initTagHandlers();  // 👈 חדש
highlightFocusedRow();
```

### 3.6 עדכון colspan בשורות נוספות

עדכן את כל המקומות שמשתמשים ב-`colspan="9"` ל-`colspan="10"`:

```javascript
// בפונקציית renderAlertsTable - שורת "לא נמצאו התראות"
if (!alerts || !alerts.length) {
  body.innerHTML = '<tr><td colspan="10">לא נמצאו התראות בטווח שנבחר</td></tr>';
  return;
}

// בפונקציית renderGraphRow - עדכון colspan
return `
  <tr class="visual-context-row" ...>
    <td colspan="10">  <!-- 👈 עדכון -->
      ...
    </td>
  </tr>
`;

// בפונקציית renderAiExplainRow - עדכון colspan
return `
  <tr class="ai-explain-row" ...>
    <td colspan="10">  <!-- 👈 עדכון -->
      ...
    </td>
  </tr>
`;
```

---

## שלב 4: תיוג גלובלי לפי סוג התראה

### 💡 הרעיון

המימוש הבסיסי (שלבים 1-3) עובד לפי **מזהה ייחודי (Instance)** - כל התראה מקבלת תגיות משלה. 

אבל מה אם תרצה שפעם אחת תתייג "CPU High" כ-"Infrastructure", וזה יופיע **אוטומטית** בכל פעם שתהיה שוב התראת "CPU High" בעתיד (ובעבר)?

**הפתרון:** הוספת לוגיקה של "תגיות גלובליות" - תיוג לפי **שם ההתראה** ולא רק לפי ה-UID.

### 4.1 איך זה עובד

| סוג תיוג | מזהה | התנהגות |
|---------|------|---------|
| **ספציפי (Instance)** | `alert_uid` | תגיות על מופע בודד של התראה |
| **גלובלי (Type)** | `alert_name` | תגיות קבועות לכל ההתראות עם אותו שם |

**תרחיש לדוגמה:**

1. נכנסת התראה חדשה: "Low Disk Space" (UID: `abc-123`)
2. פותח את המודל ומוסיף תגית "Critical"
3. **מסמן ✅ "החל באופן קבוע על כל ההתראות מסוג זה"**
4. המערכת שומרת את זה תחת השם "Low Disk Space"
5. מחר, כשתופיע התראה חדשה עם אותו שם (UID: `xyz-789`) – היא תופיע ברשימה **ישר עם התגית "Critical"**

---

### 4.2 עדכון בסיס הנתונים

הוסף את הפונקציות הבאות ל-`monitoring/alert_tags_storage.py`:

```python
# monitoring/alert_tags_storage.py - הוספה לסוף הקובץ

# ==========================================
# Global Tags (לפי סוג התראה)
# ==========================================

def get_tags_map_for_alerts(alerts_list: List[dict]) -> Dict[str, List[str]]:
    """
    מחזיר מפה משולבת: גם תגיות ספציפיות למופע, וגם תגיות קבועות לסוג ההתראה.
    
    Args:
        alerts_list: רשימת התראות, כל אחת עם alert_uid ו-name
        
    Returns:
        מיפוי של alert_uid -> רשימת תגיות (משולבת)
    """
    uids = [a.get("alert_uid") for a in alerts_list if a.get("alert_uid")]
    names = [a.get("name") for a in alerts_list if a.get("name")]
    
    # 1. שליפת תגיות ספציפיות (לפי UID)
    instance_cursor = _get_collection().find({"alert_uid": {"$in": uids}})
    instance_map = {doc["alert_uid"]: set(doc.get("tags", [])) for doc in instance_cursor}
    
    # 2. שליפת תגיות גלובליות (לפי שם ההתראה)
    global_cursor = _get_collection().find({"alert_type_name": {"$in": names}})
    global_map = {doc["alert_type_name"]: set(doc.get("tags", [])) for doc in global_cursor}
    
    # 3. איחוד התוצאות - תגיות גלובליות + ספציפיות
    final_map = {}
    for alert in alerts_list:
        uid = alert.get("alert_uid")
        name = alert.get("name")
        
        if not uid:
            continue
            
        tags = set()
        
        # תגיות ספציפיות למופע
        if uid in instance_map:
            tags.update(instance_map[uid])
        
        # תגיות גלובליות לסוג
        if name in global_map:
            tags.update(global_map[name])
            
        final_map[uid] = list(tags)
        
    return final_map


def set_global_tags_for_name(
    alert_name: str,
    tags: List[str],
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    שמירת תגיות קבועות לכל ההתראות עם השם הזה.
    
    Args:
        alert_name: שם ההתראה (לדוגמה: "CPU High", "Low Disk Space")
        tags: רשימת תגיות לשמור
        user_id: מזהה המשתמש (אופציונלי)
        
    Returns:
        תוצאת העדכון
    """
    if not alert_name:
        raise ValueError("alert_name is required")
    
    # נרמול תגיות
    normalized_tags = list(dict.fromkeys(
        t.strip().lower() for t in tags if t and t.strip()
    ))
    
    now = datetime.now(timezone.utc)
    
    result = _get_collection().update_one(
        {"alert_type_name": alert_name},  # מזהה ייחודי לסוג
        {
            "$set": {
                "tags": normalized_tags,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
                "created_by": user_id,
            }
        },
        upsert=True
    )
    
    return {
        "alert_type_name": alert_name,
        "tags": normalized_tags,
        "upserted": result.upserted_id is not None,
        "modified": result.modified_count > 0,
    }


def get_global_tags_for_name(alert_name: str) -> List[str]:
    """מחזיר תגיות גלובליות עבור סוג התראה."""
    if not alert_name:
        return []
    doc = _get_collection().find_one({"alert_type_name": alert_name})
    return doc.get("tags", []) if doc else []


def remove_global_tags_for_name(alert_name: str) -> Dict[str, Any]:
    """מחיקת תגיות גלובליות לסוג התראה."""
    if not alert_name:
        raise ValueError("alert_name is required")
    
    result = _get_collection().delete_one({"alert_type_name": alert_name})
    
    return {
        "alert_type_name": alert_name,
        "deleted": result.deleted_count > 0,
    }
```

### 4.3 עדכון אינדקסים

הוסף אינדקס חדש עבור תגיות גלובליות:

```python
# בתוך ensure_indexes()

def ensure_indexes() -> None:
    """יצירת אינדקסים נדרשים."""
    coll = _get_collection()
    coll.create_index("alert_uid", unique=True, sparse=True)  # sparse - מתעלם מ-null
    coll.create_index("alert_type_name", unique=True, sparse=True)  # 👈 חדש
    coll.create_index("tags")
    coll.create_index("alert_timestamp")
    coll.create_index([("tags", 1), ("alert_timestamp", -1)])
    logger.info("alert_tags indexes ensured")
```

> **💡 הערה:** שימוש ב-`sparse=True` מבטיח שמסמכים ללא השדה לא ייכנסו לאינדקס ולא יגרמו לכפילויות.

---

### 4.4 עדכון ה-API

#### 4.4.1 Route חדש לתגיות גלובליות

הוסף ל-`services/observability_dashboard.py`:

```python
# services/observability_dashboard.py - הוספה

def set_global_alert_tags(
    alert_name: str,
    tags: List[str],
    user_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    POST /api/observability/alerts/global-tags
    שמירת תגיות קבועות לסוג התראה.
    
    Body: {"alert_name": "CPU High", "tags": ["infrastructure", "critical"]}
    """
    if not alert_name:
        return {"ok": False, "error": "missing_alert_name"}
    if not tags:
        return {"ok": False, "error": "missing_tags"}
    
    try:
        result = alert_tags_storage.set_global_tags_for_name(
            alert_name=alert_name,
            tags=tags,
            user_id=user_id,
        )
        return {"ok": True, **result}
    except ValueError as ve:
        return {"ok": False, "error": str(ve)}
    except Exception as e:
        logger.exception("set_global_alert_tags failed: %s", e)
        return {"ok": False, "error": "internal_error"}
```

#### 4.4.2 רישום ה-Route

הוסף ל-`services/webserver.py`:

```python
@app.route('/api/observability/alerts/global-tags', methods=['POST'])
@admin_required
def api_set_global_alert_tags():
    """שמירת תגיות גלובליות לסוג התראה."""
    data = request.get_json() or {}
    user_id = getattr(g, 'user_id', None)
    result = obs_dash.set_global_alert_tags(
        alert_name=data.get("alert_name", ""),
        tags=data.get("tags", []),
        user_id=user_id,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status
```

#### 4.4.3 עדכון `get_alerts_history`

**החלף** את הקריאה הקיימת בקריאה החדשה שמשלבת את שני סוגי התגיות:

```python
def get_alerts_history(...) -> Dict[str, Any]:
    # ... קוד קיים לשליפת alerts ...
    
    alerts = list(cursor)
    
    # === עדכון: שליפה משולבת של תגיות ===
    # במקום get_tags_for_alerts הישנה, משתמשים בפונקציה החכמה:
    tags_map = alert_tags_storage.get_tags_map_for_alerts(alerts)
    
    for alert in alerts:
        uid = alert.get("alert_uid")
        alert["tags"] = tags_map.get(uid, [])
    # === סוף עדכון ===
    
    return {
        "ok": True,
        "alerts": alerts,
        "total": total,
        # ...
    }
```

---

### 4.5 עדכון ה-UI

#### 4.5.1 הוספת צ'קבוקס למודל

הוסף בתוך `#tagModal`, לפני ה-`tag-modal__actions`:

```html
<!-- בתוך tag-modal__dialog, אחרי current-tags -->
<div class="tag-modal__options" style="margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.1);">
  <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 0.9rem;">
    <input type="checkbox" id="tagGlobalCheckbox">
    <span>החל תגיות אלו באופן קבוע על כל ההתראות מסוג זה</span>
  </label>
  <small style="display: block; margin-top: 5px; opacity: 0.6; font-size: 0.8rem;">
    💡 תגיות גלובליות יופיעו אוטומטית בכל התראה עם אותו שם (גם בעבר וגם בעתיד)
  </small>
</div>
```

#### 4.5.2 CSS נוסף (אופציונלי)

```css
/* Global tag checkbox styling */
#tagGlobalCheckbox {
  width: 16px;
  height: 16px;
  accent-color: #64ffda;
}
```

---

### 4.6 עדכון ה-JavaScript

#### 4.6.1 עדכון `tagState`

```javascript
const tagState = {
  alertUid: null,
  alertTimestamp: null,
  alertName: null,    // 👈 חדש - שמירת שם ההתראה
  tags: [],
  suggestions: [],,
  selectedIndex: -1,
};
```

#### 4.6.2 עדכון `renderTagsCell`

הוסף את `alert.name` ל-payload:

```javascript
function renderTagsCell(alert) {
  const tags = alert.tags || [];
  const uid = alert.alert_uid || '';
  const ts = alert.timestamp || '';
  const name = alert.name || '';  // 👈 חדש
  
  if (!uid) {
    return '<span style="opacity:0.4;">—</span>';
  }
  
  const payload = encodeURIComponent(JSON.stringify({
    alert_uid: uid,
    timestamp: ts,
    alert_name: name,  // 👈 חדש
    tags: tags,
  }));
  
  // ... המשך ללא שינוי ...
}
```

#### 4.6.3 עדכון `openTagModal`

שמור את שם ההתראה כשפותחים את המודל:

```javascript
function openTagModal(payload) {
  if (!payload) return;
  try {
    const data = JSON.parse(decodeURIComponent(payload));
    tagState.alertUid = data.alert_uid;
    tagState.alertTimestamp = data.timestamp;
    tagState.alertName = data.alert_name;  // 👈 חדש
    tagState.tags = [...(data.tags || [])];
    tagState.selectedIndex = -1;
    
    // איפוס הצ'קבוקס בכל פתיחה
    const globalCheckbox = document.getElementById('tagGlobalCheckbox');
    if (globalCheckbox) globalCheckbox.checked = false;
    
    // ... המשך ללא שינוי ...
  } catch (err) {
    console.warn('tag modal parse failed', err);
  }
}
```

#### 4.6.4 עדכון `saveAlertTags`

בדיקה אם הצ'קבוקס מסומן ושליחה ל-Endpoint המתאים:

```javascript
async function saveAlertTags() {
  if (!tagState.alertUid) return;
  
  const isGlobal = document.getElementById('tagGlobalCheckbox')?.checked || false;
  
  try {
    if (tagSaveBtn) tagSaveBtn.disabled = true;
    
    let endpoint, payload;
    
    if (isGlobal && tagState.alertName) {
      // 🌍 שמירה גלובלית - לפי שם ההתראה
      endpoint = '/api/observability/alerts/global-tags';
      payload = {
        alert_name: tagState.alertName,
        tags: tagState.tags,
      };
    } else {
      // 📌 שמירה ספציפית - לפי UID (ברירת מחדל)
      endpoint = `/api/observability/alerts/${tagState.alertUid}/tags`;
      payload = {
        tags: tagState.tags,
        alert_timestamp: tagState.alertTimestamp,
      };
    }
    
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    
    const data = await res.json();
    
    if (data.ok === false) {
      showToast('שגיאה בשמירת תגיות');
      return;
    }
    
    // הודעה מותאמת
    const message = isGlobal 
      ? `התגיות יופיעו בכל ההתראות מסוג "${tagState.alertName}"`
      : 'התגיות נשמרו';
    showToast(message);
    
    closeTagModal();
    refreshHistory().catch(() => {});
    
  } catch (err) {
    console.error('save tags failed', err);
    showToast('שגיאה בשמירת תגיות');
  } finally {
    if (tagSaveBtn) tagSaveBtn.disabled = false;
  }
}
```

---

### 4.7 דוגמה מלאה לזרימה

```
┌─────────────────────────────────────────────────────────────────┐
│  1. משתמש פותח התראה "CPU High" ומוסיף תגית "Infrastructure"   │
│     ומסמן ✅ "החל באופן קבוע"                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. הקוד שומר ב-DB מסמך:                                       │
│     { "alert_type_name": "CPU High",                            │
│       "tags": ["infrastructure"] }                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. בשליפת התראות, get_tags_map_for_alerts() מאחדת:           │
│     • תגיות ספציפיות (לפי UID)                                  │
│     • תגיות גלובליות (לפי שם)                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. כל התראה חדשה עם שם "CPU High" מקבלת אוטומטית              │
│     את התגית "Infrastructure" - גם אם ה-UID שונה לגמרי!        │
└─────────────────────────────────────────────────────────────────┘
```

---

### 4.8 שיקולים חשובים

#### 🔄 מה קורה כשיש גם תגיות גלובליות וגם ספציפיות?

**הן מתמזגות!** ההתראה מציגה את האיחוד של שתיהן.

| סוג | תגיות |
|-----|-------|
| גלובלי ("CPU High") | `infrastructure`, `production` |
| ספציפי (UID: abc-123) | `urgent`, `investigated` |
| **תוצאה סופית** | `infrastructure`, `production`, `urgent`, `investigated` |

#### 🗑️ איך מוחקים תגית גלובלית?

כרגע, כדי להסיר תגית גלובלית, צריך לערוך אותה מחדש או למחוק ישירות מה-DB. אפשר להוסיף UI נפרד לניהול תגיות גלובליות אם יש צורך.

#### ⚡ ביצועים

הפונקציה `get_tags_map_for_alerts` מבצעת **2 שאילתות בלבד**, בלי קשר לכמות ההתראות:
1. שליפת תגיות ספציפיות (`$in` על UIDs)
2. שליפת תגיות גלובליות (`$in` על Names)

---

## בדיקות

### 5.1 בדיקות יחידה (Backend)

```python
# tests/test_alert_tags_storage.py

import pytest
from datetime import datetime, timezone
from monitoring import alert_tags_storage


@pytest.fixture
def clean_tags_collection(mongodb):
    """ניקוי collection לפני כל טסט."""
    mongodb["alert_tags"].delete_many({})
    yield
    mongodb["alert_tags"].delete_many({})


class TestAlertTagsStorage:
    
    def test_set_and_get_tags(self, clean_tags_collection):
        alert_uid = "test-alert-123"
        ts = datetime.now(timezone.utc)
        tags = ["bug", "production", "urgent"]
        
        result = alert_tags_storage.set_tags_for_alert(alert_uid, ts, tags)
        
        assert result["alert_uid"] == alert_uid
        assert set(result["tags"]) == {"bug", "production", "urgent"}
        
        fetched = alert_tags_storage.get_tags_for_alert(alert_uid)
        assert set(fetched) == {"bug", "production", "urgent"}
    
    def test_add_single_tag(self, clean_tags_collection):
        alert_uid = "test-alert-456"
        ts = datetime.now(timezone.utc)
        
        alert_tags_storage.set_tags_for_alert(alert_uid, ts, ["existing"])
        result = alert_tags_storage.add_tag_to_alert(alert_uid, ts, "new-tag")
        
        assert "new-tag" in result["tags"]
        assert "existing" in result["tags"]
    
    def test_remove_tag(self, clean_tags_collection):
        alert_uid = "test-alert-789"
        ts = datetime.now(timezone.utc)
        
        alert_tags_storage.set_tags_for_alert(alert_uid, ts, ["keep", "remove"])
        result = alert_tags_storage.remove_tag_from_alert(alert_uid, "remove")
        
        assert "remove" not in result["tags"]
        assert "keep" in result["tags"]
    
    def test_tag_normalization(self, clean_tags_collection):
        alert_uid = "test-normalize"
        ts = datetime.now(timezone.utc)
        tags = ["  BUG  ", "Production", "URGENT", "bug"]  # duplicates & case
        
        result = alert_tags_storage.set_tags_for_alert(alert_uid, ts, tags)
        
        # Should be normalized and deduplicated
        assert result["tags"] == ["bug", "production", "urgent"]
    
    def test_search_tags(self, clean_tags_collection):
        ts = datetime.now(timezone.utc)
        alert_tags_storage.set_tags_for_alert("a1", ts, ["production", "bug"])
        alert_tags_storage.set_tags_for_alert("a2", ts, ["production", "feature"])
        alert_tags_storage.set_tags_for_alert("a3", ts, ["staging"])
        
        results = alert_tags_storage.search_tags("prod")
        
        assert "production" in results
        assert "staging" not in results
    
    def test_get_tags_for_multiple_alerts(self, clean_tags_collection):
        ts = datetime.now(timezone.utc)
        alert_tags_storage.set_tags_for_alert("a1", ts, ["tag1"])
        alert_tags_storage.set_tags_for_alert("a2", ts, ["tag2"])
        
        result = alert_tags_storage.get_tags_for_alerts(["a1", "a2", "a3"])
        
        assert result["a1"] == ["tag1"]
        assert result["a2"] == ["tag2"]
        assert "a3" not in result  # doesn't exist
    
    def test_search_tags_with_regex_special_chars(self, clean_tags_collection):
        """🛡️ וידוא ש-search_tags לא פגיע ל-Regex injection."""
        ts = datetime.now(timezone.utc)
        alert_tags_storage.set_tags_for_alert("a1", ts, ["production", "c++", "tag(1)"])
        
        # חיפוש עם תווים מיוחדים - צריך להחזיר רק התאמות מדויקות
        assert "c++" in alert_tags_storage.search_tags("c++")
        assert "tag(1)" in alert_tags_storage.search_tags("tag(1)")
        
        # תווי regex לא צריכים לפעול כ-regex
        assert "production" not in alert_tags_storage.search_tags(".*")
        assert "production" not in alert_tags_storage.search_tags("[prod]")


class TestGlobalAlertTags:
    """בדיקות לפיצ'ר תיוג גלובלי לפי סוג התראה."""
    
    def test_set_and_get_global_tags(self, clean_tags_collection):
        """בדיקת שמירה ושליפה של תגיות גלובליות."""
        alert_name = "CPU High"
        tags = ["infrastructure", "critical"]
        
        result = alert_tags_storage.set_global_tags_for_name(alert_name, tags)
        
        assert result["alert_type_name"] == alert_name
        assert set(result["tags"]) == {"infrastructure", "critical"}
        
        fetched = alert_tags_storage.get_global_tags_for_name(alert_name)
        assert set(fetched) == {"infrastructure", "critical"}
    
    def test_global_tags_normalization(self, clean_tags_collection):
        """וידוא נרמול תגיות גלובליות."""
        alert_name = "Memory Warning"
        tags = ["  URGENT  ", "Infrastructure", "urgent"]  # duplicates & case
        
        result = alert_tags_storage.set_global_tags_for_name(alert_name, tags)
        
        # Should be normalized and deduplicated
        assert result["tags"] == ["urgent", "infrastructure"]
    
    def test_get_tags_map_merges_instance_and_global(self, clean_tags_collection):
        """
        בדיקה שהפונקציה get_tags_map_for_alerts מאחדת 
        תגיות ספציפיות וגלובליות.
        """
        ts = datetime.now(timezone.utc)
        
        # תגיות ספציפיות להתראה מסוימת
        alert_tags_storage.set_tags_for_alert("uid-123", ts, ["specific-tag"])
        
        # תגיות גלובליות לסוג "CPU High"
        alert_tags_storage.set_global_tags_for_name("CPU High", ["global-tag"])
        
        # רשימת התראות לבדיקה
        alerts = [
            {"alert_uid": "uid-123", "name": "CPU High"},     # יש לה גם ספציפי וגם גלובלי
            {"alert_uid": "uid-456", "name": "CPU High"},     # יש לה רק גלובלי
            {"alert_uid": "uid-789", "name": "Other Alert"},  # אין לה תגיות
        ]
        
        result = alert_tags_storage.get_tags_map_for_alerts(alerts)
        
        # uid-123: צריכה לקבל את שתי התגיות
        assert "specific-tag" in result["uid-123"]
        assert "global-tag" in result["uid-123"]
        
        # uid-456: צריכה לקבל רק את התגית הגלובלית
        assert result["uid-456"] == ["global-tag"]
        
        # uid-789: ללא תגיות
        assert result["uid-789"] == []
    
    def test_global_tags_apply_to_all_alerts_with_same_name(self, clean_tags_collection):
        """
        בדיקה שתגית גלובלית מופיעה בכל ההתראות עם אותו שם,
        גם אם יש להן UIDs שונים לגמרי.
        """
        # יצירת תגית גלובלית
        alert_tags_storage.set_global_tags_for_name("Low Disk Space", ["storage"])
        
        # 5 התראות שונות עם אותו שם
        alerts = [
            {"alert_uid": f"uid-{i}", "name": "Low Disk Space"}
            for i in range(5)
        ]
        
        result = alert_tags_storage.get_tags_map_for_alerts(alerts)
        
        # כולן צריכות לקבל את התגית הגלובלית
        for i in range(5):
            assert "storage" in result[f"uid-{i}"], f"Alert uid-{i} should have global tag"
    
    def test_remove_global_tags(self, clean_tags_collection):
        """בדיקת מחיקת תגיות גלובליות."""
        alert_name = "Test Alert"
        alert_tags_storage.set_global_tags_for_name(alert_name, ["tag1", "tag2"])
        
        result = alert_tags_storage.remove_global_tags_for_name(alert_name)
        
        assert result["deleted"] is True
        assert alert_tags_storage.get_global_tags_for_name(alert_name) == []
    
    def test_global_tags_empty_name_raises_error(self, clean_tags_collection):
        """וידוא שלא ניתן לשמור תגיות גלובליות ללא שם."""
        with pytest.raises(ValueError, match="alert_name is required"):
            alert_tags_storage.set_global_tags_for_name("", ["tag"])
```

### 5.2 בדיקות API

```python
# tests/test_alert_tags_api.py

import pytest


class TestAlertTagsAPI:
    
    def test_set_tags_endpoint(self, client, admin_auth):
        response = client.post(
            '/api/observability/alerts/test-uid/tags',
            json={"tags": ["bug", "urgent"], "alert_timestamp": "2025-01-01T00:00:00Z"},
            headers=admin_auth,
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert data["ok"] is True
        assert set(data["tags"]) == {"bug", "urgent"}
    
    def test_add_single_tag(self, client, admin_auth):
        # Setup
        client.post(
            '/api/observability/alerts/test-uid/tags',
            json={"tags": ["existing"], "alert_timestamp": "2025-01-01T00:00:00Z"},
            headers=admin_auth,
        )
        
        # Add tag
        response = client.post(
            '/api/observability/alerts/test-uid/tags/add',
            json={"tag": "new", "alert_timestamp": "2025-01-01T00:00:00Z"},
            headers=admin_auth,
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert "new" in data["tags"]
        assert "existing" in data["tags"]
    
    def test_remove_tag(self, client, admin_auth):
        # Setup
        client.post(
            '/api/observability/alerts/test-uid/tags',
            json={"tags": ["keep", "remove"], "alert_timestamp": "2025-01-01T00:00:00Z"},
            headers=admin_auth,
        )
        
        response = client.delete(
            '/api/observability/alerts/test-uid/tags/remove',
            headers=admin_auth,
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert "remove" not in data["tags"]
    
    def test_suggest_tags(self, client, admin_auth):
        response = client.get(
            '/api/observability/tags/suggest?q=bug',
            headers=admin_auth,
        )
        
        assert response.status_code == 200
        data = response.get_json()
        assert "suggestions" in data
```

---

## שיקולי ביצועים

### 6.1 אינדקסים

האינדקסים המוגדרים ב-`ensure_indexes()` מכסים את התרחישים העיקריים:
- `alert_uid` (unique) - שליפה לפי התראה
- `tags` - חיפוש לפי תגית
- `alert_timestamp` - סינון לפי טווח זמן
- Compound index על `tags` + `alert_timestamp` - שאילתות משולבות

### 6.2 Batch Loading

פונקציית `get_tags_for_alerts` מאפשרת טעינת תגיות במכה אחת עבור כל ההתראות בדף, במקום N+1 שאילתות.

### 6.3 Caching (אופציונלי)

אם יש צורך, אפשר להוסיף cache לתגיות פופולריות:

```python
import functools
import time

@functools.lru_cache(maxsize=1)
def _cached_popular_tags():
    """Cache popular tags for 5 minutes."""
    return (time.time(), get_all_tags(100))

def get_popular_tags_cached(limit: int = 50):
    cached_time, tags = _cached_popular_tags()
    if time.time() - cached_time > 300:  # 5 min TTL
        _cached_popular_tags.cache_clear()
        cached_time, tags = _cached_popular_tags()
    return tags[:limit]
```

---

## שיקולי אבטחה ובאגים נפוצים

### 7.1 🛡️ Regex Injection ב-MongoDB

**הבעיה:** חיפוש תגיות עם תווי Regex מיוחדים (`c++`, `tag(1)`, `[test]`) עלול לגרום לשגיאות או תוצאות לא צפויות.

**הפתרון:** שימוש ב-`re.escape()` לפני הכנסת קלט משתמש לשאילתת `$regex`:

```python
# ❌ שגוי - פגיע ל-Regex injection
{"$regex": f"^{user_input}"}

# ✅ נכון - מנקה תווים מיוחדים
safe_input = re.escape(user_input)
{"$regex": f"^{safe_input}"}
```

**דוגמאות לקלט בעייתי:**
| קלט | התנהגות ללא escape |
|-----|---------------------|
| `c++` | `+` הוא quantifier - שגיאת regex |
| `tag(1)` | `()` הם capturing group |
| `[prod]` | `[]` הם character class - יתאים ל-p/r/o/d |
| `.*` | יתאים לכל מחרוזת |

### 7.2 🖱️ כפילות Event Listeners

**הבעיה:** פונקציות `init*Handlers` שנקראות בכל רענון טבלה מוסיפות listeners כפולים לאלמנטים קבועים (כמו Modal).

**הפתרון:** שימוש ב-data attribute כ-guard:

```javascript
// ❌ שגוי - מוסיף listener בכל קריאה
if (element) {
  element.addEventListener('click', handler);
}

// ✅ נכון - מוסיף פעם אחת בלבד
if (element) {
  if (element.dataset.listenerAttached === '1') return;
  element.dataset.listenerAttached = '1';
  element.addEventListener('click', handler);
}
```

**למה זה קריטי:**
- Handler שרץ N פעמים עלול למחוק נתונים שגויים
- ביצועים - N קריאות API במקום אחת
- Race conditions בקריאות אסינכרוניות

### 7.3 בדיקות נוספות לאבטחה

הוסף את הבדיקות הבאות:

```python
# tests/test_alert_tags_security.py

def test_regex_special_chars_in_search():
    """וידוא ש-search_tags מטפל נכון בתווים מיוחדים."""
    # Setup - תגית עם שם רגיל
    ts = datetime.now(timezone.utc)
    alert_tags_storage.set_tags_for_alert("a1", ts, ["production"])
    
    # חיפוש עם תווים מיוחדים לא צריך להחזיר תוצאות שגויות
    dangerous_inputs = [".*", "prod.*", "[prod]", "prod(", "c++", "tag|other"]
    
    for dangerous in dangerous_inputs:
        results = alert_tags_storage.search_tags(dangerous)
        # לא צריך להחזיר "production" כי זה לא prefix אמיתי
        assert "production" not in results, f"Regex injection with: {dangerous}"


def test_empty_and_whitespace_tags():
    """וידוא שתגיות ריקות או עם רווחים בלבד לא נשמרות."""
    ts = datetime.now(timezone.utc)
    result = alert_tags_storage.set_tags_for_alert(
        "a1", ts, ["", "   ", "valid", "  spaces  "]
    )
    
    # רק תגיות תקינות צריכות להישמר
    assert result["tags"] == ["valid", "spaces"]
```

---

## סיכום

### Checklist למימוש

#### תיוג בסיסי (Instance-based)
- [ ] **שלב 1:** יצירת `monitoring/alert_tags_storage.py`
- [ ] **שלב 1:** הוספת `ensure_indexes()` ל-startup
- [ ] **שלב 2:** הוספת פונקציות API ל-`observability_dashboard.py`
- [ ] **שלב 2:** רישום Routes ב-`webserver.py`
- [ ] **שלב 2:** עדכון `get_alerts_history` לכלול תגיות
- [ ] **שלב 3:** עדכון `<th>` בטבלה
- [ ] **שלב 3:** הוספת CSS לתגיות
- [ ] **שלב 3:** הוספת Tag Modal HTML
- [ ] **שלב 3:** הוספת JavaScript logic
- [ ] **שלב 3:** עדכון `renderAlertsTable` ו-`initTagHandlers`

#### תיוג גלובלי (Type-based) 🆕
- [ ] **שלב 4:** הוספת פונקציות גלובליות ל-`alert_tags_storage.py`
- [ ] **שלב 4:** עדכון אינדקסים עם `sparse=True`
- [ ] **שלב 4:** הוספת Route ל-`/api/observability/alerts/global-tags`
- [ ] **שלב 4:** החלפת `get_tags_for_alerts` ב-`get_tags_map_for_alerts`
- [ ] **שלב 4:** הוספת צ'קבוקס "החל באופן קבוע" ל-Modal
- [ ] **שלב 4:** עדכון `tagState` לכלול `alertName`
- [ ] **שלב 4:** עדכון `saveAlertTags` לתמוך בשמירה גלובלית

#### בדיקות ואבטחה
- [ ] **בדיקות:** כתיבת unit tests לתיוג בסיסי
- [ ] **בדיקות:** כתיבת unit tests לתיוג גלובלי
- [ ] **בדיקות:** בדיקת integration עם הדשבורד
- [ ] **אבטחה:** וידוא `re.escape()` בפונקציית `search_tags`
- [ ] **אבטחה:** וידוא guards למניעת כפילות listeners

---

**הערות נוספות:**
- הקוד משתמש ב-Classes קיימים (`story-modal`, `status-pill`) לשמירת אחידות עיצובית
- ה-Autocomplete משתמש ב-debounce למניעת שאילתות מיותרות
- התגיות מנורמלות ל-lowercase ללא כפילויות
- שמירת `alert_timestamp` מבטיחה שהתגיות ישרדו log rotation

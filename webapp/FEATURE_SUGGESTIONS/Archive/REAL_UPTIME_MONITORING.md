# מדריך יישום: מעקב זמינות אמיתי (Real Uptime Monitoring)

## הבעיה הנוכחית
כרגע מוצג בדף הבית "99.9% זמינות" כערך סטטי שלא משקף את המצב האמיתי.

## פתרונות אפשריים

### פתרון 1: מעקב זמינות פנימי (מומלץ לפרויקטים קטנים)

#### 1.1 הוספת טבלה לבסיס הנתונים

```sql
CREATE TABLE uptime_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT CHECK(status IN ('up', 'down', 'degraded')),
    response_time_ms INTEGER,
    error_message TEXT
);

CREATE INDEX idx_uptime_timestamp ON uptime_logs(timestamp);
```

#### 1.2 הוספת Health Check אוטומטי

**קובץ:** `webapp/health_monitor.py`

```python
import time
import sqlite3
from datetime import datetime, timedelta
from threading import Thread
import requests
import logging

logger = logging.getLogger(__name__)

class HealthMonitor:
    def __init__(self, db_path, check_interval=60):
        """
        מנטר הבריאות של המערכת
        
        Args:
            db_path: נתיב לבסיס הנתונים
            check_interval: מרווח בדיקה בשניות (ברירת מחדל: 60)
        """
        self.db_path = db_path
        self.check_interval = check_interval
        self.running = False
        self.thread = None
        
    def start(self):
        """התחל ניטור"""
        if self.running:
            return
        
        self.running = True
        self.thread = Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("Health monitoring started")
        
    def stop(self):
        """עצור ניטור"""
        self.running = False
        if self.thread:
            self.thread.join()
        logger.info("Health monitoring stopped")
        
    def _monitor_loop(self):
        """לולאת הניטור הראשית"""
        while self.running:
            self._perform_health_check()
            time.sleep(self.check_interval)
            
    def _perform_health_check(self):
        """בצע בדיקת בריאות"""
        start_time = time.time()
        status = 'up'
        error_message = None
        
        try:
            # בדיקות בסיסיות
            self._check_database()
            self._check_disk_space()
            self._check_memory()
            
            # אם יש URL לבדיקה חיצונית
            # response = requests.get('http://localhost:5000/health', timeout=5)
            # if response.status_code != 200:
            #     status = 'degraded'
            
        except Exception as e:
            status = 'down'
            error_message = str(e)
            logger.error(f"Health check failed: {e}")
            
        response_time = int((time.time() - start_time) * 1000)
        
        # שמור בבסיס הנתונים
        self._log_health_status(status, response_time, error_message)
        
    def _check_database(self):
        """בדוק שהדאטאבייס עובד"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        conn.close()
        
    def _check_disk_space(self):
        """בדוק שיש מספיק מקום בדיסק"""
        import shutil
        total, used, free = shutil.disk_usage("/")
        free_percentage = (free / total) * 100
        
        if free_percentage < 5:
            raise Exception(f"Low disk space: {free_percentage:.1f}% free")
            
    def _check_memory(self):
        """בדוק שיש מספיק זיכרון"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                raise Exception(f"High memory usage: {memory.percent}%")
        except ImportError:
            pass  # psutil not installed
            
    def _log_health_status(self, status, response_time, error_message):
        """שמור סטטוס בבסיס הנתונים"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO uptime_logs (status, response_time_ms, error_message)
            VALUES (?, ?, ?)
        """, (status, response_time, error_message))
        
        # נקה רשומות ישנות (שמור רק 30 יום)
        cursor.execute("""
            DELETE FROM uptime_logs 
            WHERE timestamp < datetime('now', '-30 days')
        """)
        
        conn.commit()
        conn.close()

def calculate_uptime(db_path, hours=24):
    """
    חשב אחוז זמינות
    
    Args:
        db_path: נתיב לבסיס הנתונים
        hours: מספר שעות אחורה לחישוב (ברירת מחדל: 24)
        
    Returns:
        dict עם נתוני זמינות
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # קבל את כל הבדיקות מהשעות האחרונות
    since = datetime.now() - timedelta(hours=hours)
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_checks,
            SUM(CASE WHEN status = 'up' THEN 1 ELSE 0 END) as up_checks,
            SUM(CASE WHEN status = 'degraded' THEN 1 ELSE 0 END) as degraded_checks,
            SUM(CASE WHEN status = 'down' THEN 1 ELSE 0 END) as down_checks,
            AVG(CASE WHEN status = 'up' THEN response_time_ms ELSE NULL END) as avg_response_time,
            MIN(timestamp) as first_check,
            MAX(timestamp) as last_check
        FROM uptime_logs
        WHERE timestamp >= ?
    """, (since.isoformat(),))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result or result[0] == 0:
        return {
            'uptime_percentage': 100.0,
            'total_checks': 0,
            'status': 'unknown',
            'avg_response_time': 0
        }
    
    total = result[0]
    up = result[1] or 0
    degraded = result[2] or 0
    down = result[3] or 0
    
    # חישוב אחוז זמינות (up + degraded נחשבים זמינים)
    available = up + degraded
    uptime_percentage = (available / total) * 100 if total > 0 else 100
    
    # קבע סטטוס נוכחי
    if down > 0 and down >= total * 0.1:  # יותר מ-10% down
        current_status = 'issues'
    elif degraded > 0 and degraded >= total * 0.2:  # יותר מ-20% degraded
        current_status = 'degraded'
    else:
        current_status = 'operational'
    
    return {
        'uptime_percentage': round(uptime_percentage, 2),
        'total_checks': total,
        'up_checks': up,
        'degraded_checks': degraded,
        'down_checks': down,
        'status': current_status,
        'avg_response_time': round(result[4], 2) if result[4] else 0,
        'monitoring_since': result[5],
        'last_check': result[6]
    }

def get_uptime_history(db_path, days=7):
    """
    קבל היסטוריית זמינות
    
    Args:
        db_path: נתיב לבסיס הנתונים
        days: מספר ימים אחורה
        
    Returns:
        list של נתוני זמינות יומיים
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    since = datetime.now() - timedelta(days=days)
    
    cursor.execute("""
        SELECT 
            DATE(timestamp) as date,
            COUNT(*) as total_checks,
            SUM(CASE WHEN status IN ('up', 'degraded') THEN 1 ELSE 0 END) as available_checks,
            AVG(response_time_ms) as avg_response_time
        FROM uptime_logs
        WHERE timestamp >= ?
        GROUP BY DATE(timestamp)
        ORDER BY date DESC
    """, (since.isoformat(),))
    
    history = []
    for row in cursor.fetchall():
        date, total, available, avg_response = row
        uptime = (available / total * 100) if total > 0 else 100
        history.append({
            'date': date,
            'uptime_percentage': round(uptime, 2),
            'total_checks': total,
            'avg_response_time': round(avg_response, 2) if avg_response else 0
        })
    
    conn.close()
    return history
```

#### 1.3 עדכון ה-App להפעלת הניטור

**קובץ:** `webapp/app.py`

```python
from health_monitor import HealthMonitor, calculate_uptime, get_uptime_history

# אתחול מנטר הבריאות
health_monitor = HealthMonitor(DATABASE_PATH, check_interval=60)

# התחל ניטור בהפעלת האפליקציה
@app.before_first_request
def start_monitoring():
    health_monitor.start()

# הוסף את נתוני הזמינות לדף הבית
@app.route('/')
def index():
    # ... קוד קיים ...
    
    # חשב זמינות
    uptime_data = calculate_uptime(DATABASE_PATH, hours=24)
    
    return render_template('index.html',
                         uptime=uptime_data,
                         # ... פרמטרים אחרים ...
                         )

# API endpoint לנתוני זמינות
@app.route('/api/uptime')
def api_uptime():
    """API endpoint להצגת נתוני זמינות"""
    period = request.args.get('period', '24h')
    
    if period == '24h':
        hours = 24
    elif period == '7d':
        hours = 24 * 7
    elif period == '30d':
        hours = 24 * 30
    else:
        hours = 24
    
    uptime_data = calculate_uptime(DATABASE_PATH, hours)
    uptime_data['history'] = get_uptime_history(DATABASE_PATH, days=7)
    
    return jsonify(uptime_data)

# Status page
@app.route('/status')
def status_page():
    """דף סטטוס מערכת"""
    uptime_24h = calculate_uptime(DATABASE_PATH, hours=24)
    uptime_7d = calculate_uptime(DATABASE_PATH, hours=24*7)
    uptime_30d = calculate_uptime(DATABASE_PATH, hours=24*30)
    history = get_uptime_history(DATABASE_PATH, days=30)
    
    return render_template('status.html',
                         uptime_24h=uptime_24h,
                         uptime_7d=uptime_7d,
                         uptime_30d=uptime_30d,
                         history=history)
```

#### 1.4 עדכון התבנית להצגת זמינות אמיתית

**קובץ:** `webapp/templates/index.html`

```html
<!-- במקום הערך הסטטי -->
<div>
    <div style="font-size: 2rem; font-weight: bold;">
        {{ uptime.uptime_percentage }}%
    </div>
    <div style="opacity: 0.8;">זמינות (24 שעות)</div>
    {% if uptime.status != 'operational' %}
        <div style="font-size: 0.8rem; color: #f56565;">
            {% if uptime.status == 'degraded' %}
                ביצועים מופחתים
            {% elif uptime.status == 'issues' %}
                בעיות זמינות
            {% endif %}
        </div>
    {% endif %}
</div>
```

### פתרון 2: שימוש בשירות חיצוני (מומלץ לproduction)

#### שירותי Monitoring חיצוניים:

1. **UptimeRobot** (חינמי עד 50 מוניטורים)
   ```javascript
   // Widget של UptimeRobot
   <script src="https://uptime.betterstack.com/widgets/announcement.js" 
           data-id="YOUR_ID" async></script>
   ```

2. **Better Uptime**
   ```python
   # API Integration
   import requests
   
   def get_uptime_from_better_uptime():
       response = requests.get(
           'https://uptime.betterstack.com/api/v2/monitors/YOUR_MONITOR_ID/sla',
           headers={'Authorization': f'Bearer {API_KEY}'}
       )
       return response.json()['data']['availability']
   ```

3. **Pingdom**
4. **StatusCake**

### פתרון 3: שילוב עם Prometheus (לסביבות מתקדמות)

```python
from prometheus_client import Gauge

uptime_gauge = Gauge('app_uptime_percentage', 'Application uptime percentage')

def update_uptime_metrics():
    """עדכן מטריקות Prometheus"""
    uptime = calculate_uptime(DATABASE_PATH, hours=24)
    uptime_gauge.set(uptime['uptime_percentage'])
```

## תבנית Status Page

**קובץ חדש:** `webapp/templates/status.html`

```html
{% extends "base.html" %}

{% block title %}סטטוס המערכת{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1>📊 סטטוס המערכת</h1>
    
    <!-- סטטוס נוכחי -->
    <div class="alert {% if uptime_24h.status == 'operational' %}alert-success{% elif uptime_24h.status == 'degraded' %}alert-warning{% else %}alert-danger{% endif %}">
        <h4>
            {% if uptime_24h.status == 'operational' %}
                ✅ כל המערכות פועלות כראוי
            {% elif uptime_24h.status == 'degraded' %}
                ⚠️ ביצועים מופחתים
            {% else %}
                ❌ תקלות במערכת
            {% endif %}
        </h4>
        <p>זמן תגובה ממוצע: {{ uptime_24h.avg_response_time }}ms</p>
    </div>
    
    <!-- כרטיסי זמינות -->
    <div class="row mt-4">
        <div class="col-md-4">
            <div class="card text-center">
                <div class="card-body">
                    <h5>24 שעות אחרונות</h5>
                    <h2 class="{% if uptime_24h.uptime_percentage >= 99.9 %}text-success{% elif uptime_24h.uptime_percentage >= 95 %}text-warning{% else %}text-danger{% endif %}">
                        {{ uptime_24h.uptime_percentage }}%
                    </h2>
                    <small class="text-muted">
                        {{ uptime_24h.up_checks }}/{{ uptime_24h.total_checks }} בדיקות מוצלחות
                    </small>
                </div>
            </div>
        </div>
        
        <div class="col-md-4">
            <div class="card text-center">
                <div class="card-body">
                    <h5>7 ימים אחרונים</h5>
                    <h2 class="{% if uptime_7d.uptime_percentage >= 99.9 %}text-success{% elif uptime_7d.uptime_percentage >= 95 %}text-warning{% else %}text-danger{% endif %}">
                        {{ uptime_7d.uptime_percentage }}%
                    </h2>
                    <small class="text-muted">
                        {{ uptime_7d.up_checks }}/{{ uptime_7d.total_checks }} בדיקות מוצלחות
                    </small>
                </div>
            </div>
        </div>
        
        <div class="col-md-4">
            <div class="card text-center">
                <div class="card-body">
                    <h5>30 ימים אחרונים</h5>
                    <h2 class="{% if uptime_30d.uptime_percentage >= 99.9 %}text-success{% elif uptime_30d.uptime_percentage >= 95 %}text-warning{% else %}text-danger{% endif %}">
                        {{ uptime_30d.uptime_percentage }}%
                    </h2>
                    <small class="text-muted">
                        {{ uptime_30d.up_checks }}/{{ uptime_30d.total_checks }} בדיקות מוצלחות
                    </small>
                </div>
            </div>
        </div>
    </div>
    
    <!-- גרף היסטוריה -->
    <div class="card mt-4">
        <div class="card-header">
            <h5>היסטוריית זמינות (30 ימים אחרונים)</h5>
        </div>
        <div class="card-body">
            <canvas id="uptimeChart"></canvas>
        </div>
    </div>
    
    <!-- טבלת היסטוריה -->
    <div class="card mt-4">
        <div class="card-header">
            <h5>פירוט יומי</h5>
        </div>
        <div class="card-body">
            <table class="table">
                <thead>
                    <tr>
                        <th>תאריך</th>
                        <th>זמינות</th>
                        <th>בדיקות</th>
                        <th>זמן תגובה ממוצע</th>
                    </tr>
                </thead>
                <tbody>
                    {% for day in history %}
                    <tr>
                        <td>{{ day.date }}</td>
                        <td>
                            <span class="badge {% if day.uptime_percentage >= 99.9 %}badge-success{% elif day.uptime_percentage >= 95 %}badge-warning{% else %}badge-danger{% endif %}">
                                {{ day.uptime_percentage }}%
                            </span>
                        </td>
                        <td>{{ day.total_checks }}</td>
                        <td>{{ day.avg_response_time }}ms</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
// גרף זמינות
const ctx = document.getElementById('uptimeChart').getContext('2d');
const historyData = {{ history|tojson }};

new Chart(ctx, {
    type: 'line',
    data: {
        labels: historyData.map(d => d.date).reverse(),
        datasets: [{
            label: 'זמינות (%)',
            data: historyData.map(d => d.uptime_percentage).reverse(),
            borderColor: '#48bb78',
            backgroundColor: 'rgba(72, 187, 120, 0.1)',
            tension: 0.4,
            fill: true
        }]
    },
    options: {
        responsive: true,
        scales: {
            y: {
                beginAtZero: false,
                min: 90,
                max: 100,
                ticks: {
                    callback: function(value) {
                        return value + '%';
                    }
                }
            }
        },
        plugins: {
            legend: {
                display: false
            }
        }
    }
});

// רענון אוטומטי כל דקה
setTimeout(() => location.reload(), 60000);
</script>
{% endblock %}
```

## יישום מהיר - שימוש בפתרון פשוט

אם אתה רוצה פתרון מהיר בינתיים, אפשר להציג זמינות בסיסית על סמך זמן הפעלת השרת:

```python
import time
from datetime import datetime

# בתחילת האפליקציה
app.start_time = time.time()

@app.route('/')
def index():
    # חישוב uptime פשוט
    uptime_seconds = time.time() - app.start_time
    uptime_days = uptime_seconds / (24 * 3600)
    
    # הנחה: אם האפליקציה רצה, הזמינות היא 100%
    # אחרת אפשר לחשב על סמך מספר שגיאות 500
    uptime_percentage = 99.9 if uptime_days > 0.1 else 100.0
    
    return render_template('index.html',
                         uptime={'uptime_percentage': uptime_percentage},
                         ...)
```

## המלצות

1. **לפיתוח מקומי**: השתמש בפתרון 1 (ניטור פנימי)
2. **לProduction**: שלב שירות חיצוני כמו UptimeRobot
3. **למערכות קריטיות**: שילוב של כמה שיטות + alerting

## יתרונות של מעקב זמינות אמיתי

- 📊 **שקיפות** - המשתמשים רואים את המצב האמיתי
- 🔔 **התראות** - אפשר לקבל התראה כשיש בעיה
- 📈 **מגמות** - זיהוי בעיות לפני שהן הופכות קריטיות
- 🎯 **SLA** - מעקב אחר עמידה ביעדי זמינות
- 🐛 **דיבוג** - קל יותר לזהות מתי ולמה היו בעיות

## סיכום

המעבר מערך סטטי לזמינות אמיתית דורש:
- מנגנון לבדיקות תקופתיות
- שמירת היסטוריה
- חישוב אחוזי זמינות
- הצגה דינמית בממשק

זמן יישום: 2-4 שעות לפתרון בסיסי